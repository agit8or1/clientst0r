"""
Document import — extract text from uploaded DOCX / PDF / TXT / Markdown files
so they can be stored as editable Knowledge Base documents and (optionally)
reviewed by AI.

Issue #140: "AI review and import function for docx and pdf".

Design notes:
- DOCX is parsed dependency-free via the stdlib ``zipfile`` + ``xml`` modules
  (a .docx is a ZIP whose ``word/document.xml`` holds the body). This avoids
  adding python-docx just for text extraction.
- PDF uses PyMuPDF (``fitz``), which is added to requirements.txt. If it is
  not importable on an older install, PDF extraction degrades to a clean
  error for that one file instead of raising.
- Everything returns a plain dict so callers never have to catch exceptions.
"""

import os
import re
import xml.etree.ElementTree as ET
import zipfile

# Hard ceiling on extracted text we keep / hand to the AI. Protects against a
# 500-page PDF blowing up token usage or the request body. Truncation is
# flagged in the result so the caller can surface it.
MAX_EXTRACTED_CHARS = 60000

# Extensions we know how to turn into editable text.
SUPPORTED_EXTENSIONS = ('.docx', '.pdf', '.txt', '.md', '.markdown')

# WordprocessingML namespace used inside word/document.xml.
_W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _clean_text(text: str) -> tuple[str, bool]:
    """Collapse excess blank lines and enforce the character ceiling.

    Returns (text, truncated).
    """
    # Normalise Windows / Mac newlines, trim trailing whitespace per line.
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    # Collapse 3+ blank lines down to a single blank line.
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    truncated = False
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS].rstrip()
        truncated = True
    return text, truncated


def _extract_docx(file_obj) -> str:
    """Extract visible paragraph text from a .docx file object.

    Walks word/document.xml, joining ``<w:t>`` runs and inserting a newline for
    each ``<w:p>`` paragraph and a tab for each ``<w:tab>``.
    """
    with zipfile.ZipFile(file_obj) as zf:
        with zf.open('word/document.xml') as doc_xml:
            tree = ET.parse(doc_xml)

    root = tree.getroot()
    paragraphs = []
    for para in root.iter(f'{_W_NS}p'):
        parts = []
        for node in para.iter():
            tag = node.tag
            if tag == f'{_W_NS}t':
                parts.append(node.text or '')
            elif tag == f'{_W_NS}tab':
                parts.append('\t')
            elif tag in (f'{_W_NS}br', f'{_W_NS}cr'):
                parts.append('\n')
        paragraphs.append(''.join(parts))
    return '\n\n'.join(paragraphs)


def _extract_pdf(file_obj) -> str:
    """Extract text from a PDF file object using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF — imported lazily so a missing wheel degrades gracefully.

    file_obj.seek(0)
    data = file_obj.read()
    text_pages = []
    with fitz.open(stream=data, filetype='pdf') as pdf:
        for page in pdf:
            text_pages.append(page.get_text('text'))
    return '\n\n'.join(text_pages)


def extract_document_text(uploaded_file) -> dict:
    """Extract text from an uploaded file.

    Args:
        uploaded_file: a Django UploadedFile (or any object with ``.name`` and a
            file-like read/seek interface).

    Returns:
        dict:
          {'success': True, 'text': str, 'kind': 'docx'|'pdf'|'text',
           'truncated': bool}
          or
          {'success': False, 'error': str}
    """
    name = getattr(uploaded_file, 'name', '') or ''
    ext = os.path.splitext(name)[1].lower()

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    try:
        if ext == '.docx':
            raw = _extract_docx(uploaded_file)
            kind = 'docx'
        elif ext == '.pdf':
            raw = _extract_pdf(uploaded_file)
            kind = 'pdf'
        elif ext in ('.txt', '.md', '.markdown'):
            uploaded_file.seek(0)
            raw = uploaded_file.read()
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            kind = 'text'
        elif ext == '.doc':
            return {
                'success': False,
                'error': 'Legacy .doc files are not supported — please save as .docx or PDF and re-upload.',
            }
        else:
            return {
                'success': False,
                'error': f'Unsupported file type "{ext or "unknown"}". Supported: DOCX, PDF, TXT, Markdown.',
            }
    except ImportError:
        return {
            'success': False,
            'error': 'PDF support (PyMuPDF) is not installed on this server. Run the updater to install requirements, or import the document as DOCX / text.',
        }
    except KeyError:
        # zipfile raises KeyError when word/document.xml is missing.
        return {'success': False, 'error': 'This does not look like a valid Word (.docx) document.'}
    except zipfile.BadZipFile:
        return {'success': False, 'error': 'The DOCX file is corrupt or not a valid Word document.'}
    except Exception as exc:  # noqa: BLE001 — last-resort so one bad file never 500s a bulk import.
        return {'success': False, 'error': f'Could not read file: {exc}'}

    text, truncated = _clean_text(raw)
    if not text:
        return {
            'success': False,
            'error': 'No readable text found in the file (it may be image-only / scanned — OCR is not supported).',
        }

    return {'success': True, 'text': text, 'kind': kind, 'truncated': truncated}
