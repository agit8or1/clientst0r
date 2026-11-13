"""Text in an OOXML file, to prove typed text reached clientst0r's storage.

DOCX: word/document.xml; XLSX: xl/sharedStrings.xml plus inline strings in
the sheets; PPTX: ppt/slides/slide*.xml. The XML is parsed and the text
nodes joined (editors split runs, so a marker typed in one go can still be
spread over several <w:t>/<a:t> nodes when spell-check or autocorrect
intervenes); ``contains`` also matches with whitespace removed.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

PARTS = {
    'docx': (r'^word/(document|header\d*|footer\d*)\.xml$',),
    'xlsx': (r'^xl/sharedStrings\.xml$', r'^xl/worksheets/sheet\d+\.xml$'),
    'pptx': (r'^ppt/slides/slide\d+\.xml$',),
}
TEXT_TAGS = ('}t', '}v')     # w:t, a:t, x:t; x:v (inline/number values)
MAX_PART = 50 * 1024 * 1024


def text_of(data: bytes, fmt: str) -> str:
    if fmt not in PARTS:
        raise ValueError(f'unsupported format {fmt}')
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(n for n in z.namelist() if any(re.match(p, n) for p in PARTS[fmt]))
        for name in names:
            info = z.getinfo(name)
            if info.file_size > MAX_PART:
                continue
            try:
                root = ElementTree.fromstring(z.read(name))
            except ElementTree.ParseError:
                continue
            for el in root.iter():
                if isinstance(el.tag, str) and el.tag.endswith(TEXT_TAGS) and el.text:
                    out.append(el.text)
    return ' '.join(out)


def contains(data: bytes, fmt: str, marker: str) -> bool:
    text = text_of(data, fmt)
    if marker in text:
        return True
    squash = re.sub(r'\s+', '', text)
    return re.sub(r'\s+', '', marker) in squash


def with_comment(data: bytes, comment: str) -> bytes:
    """The same package with a different ZIP comment: valid, but other bytes."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info))
        dst.comment = comment.encode()[:200]
    return out.getvalue()
