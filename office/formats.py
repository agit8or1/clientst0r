"""File formats Office handling knows about, and content validation.

Three groups:

* EDITABLE: OOXML without macros (.docx/.xlsx/.pptx). Editable in place when a
  provider advertises the format.
* READ_ONLY: legacy binary (.doc/.xls/.ppt) and macro-enabled OOXML
  (.docm/.xlsm/.pptm). Always kept byte-for-byte; they open read-only, and
  "Convert to a new copy" turns them into the matching EDITABLE format when a
  provider can convert. Macros are never run by clientst0r and VBA projects
  are not promised to survive any editor.
* TEMPLATE: .dotx/.xltx/.potx, accepted as template uploads only. A copy made
  from one becomes the matching EDITABLE format.
"""
from __future__ import annotations

import io
import os
import zipfile

KIND_WORD, KIND_CELL, KIND_SLIDE = 'word', 'cell', 'slide'

EDITABLE = {'docx': KIND_WORD, 'xlsx': KIND_CELL, 'pptx': KIND_SLIDE}
LEGACY = {'doc': KIND_WORD, 'xls': KIND_CELL, 'ppt': KIND_SLIDE}
MACRO = {'docm': KIND_WORD, 'xlsm': KIND_CELL, 'pptm': KIND_SLIDE}
READ_ONLY = {**LEGACY, **MACRO}
TEMPLATE = {'dotx': KIND_WORD, 'xltx': KIND_CELL, 'potx': KIND_SLIDE}
ALL_OFFICE = {**EDITABLE, **READ_ONLY}

EDITABLE_FOR_KIND = {KIND_WORD: 'docx', KIND_CELL: 'xlsx', KIND_SLIDE: 'pptx'}

MIME = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'dotx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
    'xltx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.template',
    'potx': 'application/vnd.openxmlformats-officedocument.presentationml.template',
    'docm': 'application/vnd.ms-word.document.macroEnabled.12',
    'xlsm': 'application/vnd.ms-excel.sheet.macroEnabled.12',
    'pptm': 'application/vnd.ms-powerpoint.presentation.macroEnabled.12',
    'doc': 'application/msword',
    'xls': 'application/vnd.ms-excel',
    'ppt': 'application/vnd.ms-powerpoint',
    'pdf': 'application/pdf',
}

# Content type of the main part in [Content_Types].xml.
MAIN_PART_TYPES = {
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml',
    'dotx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml',
    'docm': 'application/vnd.ms-word.document.macroEnabled.main+xml',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
    'xltx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml',
    'xlsm': 'application/vnd.ms-excel.sheet.macroEnabled.main+xml',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml',
    'potx': 'application/vnd.openxmlformats-officedocument.presentationml.template.main+xml',
    'pptm': 'application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml',
}
MAIN_PART_NAMES = {
    KIND_WORD: '/word/document.xml',
    KIND_CELL: '/xl/workbook.xml',
    KIND_SLIDE: '/ppt/presentation.xml',
}

OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

# Zip-bomb limits, checked from the central directory before anything is read.
MAX_ZIP_MEMBERS = 10000
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_CONTENT_TYPES_BYTES = 1024 * 1024


class InvalidOfficeFile(ValueError):
    """The bytes are not a valid file of the claimed format. User-safe message."""


def extension(name: str) -> str:
    return os.path.splitext(name or '')[1].lower().lstrip('.')


def kind_for(name: str):
    ext = extension(name)
    return ALL_OFFICE.get(ext) or TEMPLATE.get(ext)


def is_office(name: str) -> bool:
    return extension(name) in ALL_OFFICE


def is_editable(name: str) -> bool:
    return extension(name) in EDITABLE


def is_read_only_format(name: str) -> bool:
    return extension(name) in READ_ONLY


def conversion_target(name: str):
    """'docx' for a .doc, etc. None when the file needs no conversion."""
    ext = extension(name)
    kind = READ_ONLY.get(ext) or TEMPLATE.get(ext)
    return EDITABLE_FOR_KIND[kind] if kind else None


def ext_for_mime(mime: str) -> str:
    """'docx' for the .docx MIME type; '' when unknown or ambiguous."""
    mime = (mime or '').split(';')[0].strip().lower()
    for ext in ('docx', 'xlsx', 'pptx', 'docm', 'xlsm', 'pptm', 'doc', 'xls', 'ppt',
                'dotx', 'xltx', 'potx'):
        if MIME[ext] == mime:
            return ext
    return ''


def mime_for(name: str) -> str:
    return MIME.get(extension(name), 'application/octet-stream')


def _content_types(zf: zipfile.ZipFile) -> dict:
    """{part name: content type} from [Content_Types].xml (overrides only)."""
    from defusedxml import ElementTree as ET
    try:
        info = zf.getinfo('[Content_Types].xml')
    except KeyError:
        raise InvalidOfficeFile('Not an Office Open XML file: [Content_Types].xml is missing.')
    if info.file_size > MAX_CONTENT_TYPES_BYTES:
        raise InvalidOfficeFile('The file\'s content-type table is too large.')
    data = zf.read(info)
    if b'<!DOCTYPE' in data[:4096].upper():
        raise InvalidOfficeFile('The file\'s content-type table is not valid.')
    try:
        root = ET.fromstring(data)
    except Exception:
        raise InvalidOfficeFile('The file\'s content-type table is not valid XML.')
    out = {}
    for el in root:
        if el.tag.endswith('Override'):
            out[el.get('PartName', '')] = el.get('ContentType', '')
    return out


def validate_ooxml(fh, ext: str) -> None:
    """Raise InvalidOfficeFile unless `fh` is an OOXML package of type `ext`."""
    try:
        zf = zipfile.ZipFile(fh)
    except (zipfile.BadZipFile, OSError, ValueError):
        raise InvalidOfficeFile(f'Not a valid .{ext} file (not a ZIP package).')
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise InvalidOfficeFile('The file has too many parts.')
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            raise InvalidOfficeFile('The file would expand to more than the allowed size.')
        for i in infos:
            name = i.filename
            if name.startswith('/') or '..' in name.split('/') or '\\' in name:
                raise InvalidOfficeFile('The file contains an unsafe part name.')
        types = _content_types(zf)
        kind = kind_for('x.' + ext)
        main = types.get(MAIN_PART_NAMES[kind])
        if main != MAIN_PART_TYPES[ext]:
            raise InvalidOfficeFile(f'The content is not a .{ext} file.')
        if ext in EDITABLE:
            # A macro-free format must not carry a VBA project.
            if any(i.filename.lower().endswith('vbaproject.bin') for i in infos):
                raise InvalidOfficeFile(f'A .{ext} file must not contain macros.')


def validate_file(path_or_fh, name: str) -> None:
    """Validate content against the extension of `name`. Raises InvalidOfficeFile."""
    ext = extension(name)
    opened = None
    if isinstance(path_or_fh, (str, os.PathLike)):
        opened = fh = open(path_or_fh, 'rb')
    else:
        fh = path_or_fh
    try:
        fh.seek(0)
        if ext in LEGACY:
            if fh.read(8) != OLE_MAGIC:
                raise InvalidOfficeFile(f'The content is not a .{ext} file.')
        elif ext in MAIN_PART_TYPES:
            validate_ooxml(fh, ext)
        else:
            raise InvalidOfficeFile(f'.{ext or "?"} is not an Office format.')
    finally:
        if opened is not None:
            opened.close()
        else:
            fh.seek(0)


def template_to_document(data: bytes, template_ext: str) -> bytes:
    """Rewrite a .dotx/.xltx/.potx package as the matching document format.

    Only [Content_Types].xml changes: the main part's content type. Every other
    part is copied byte for byte.
    """
    kind = TEMPLATE[template_ext]
    doc_ext = EDITABLE_FOR_KIND[kind]
    old, new = MAIN_PART_TYPES[template_ext].encode(), MAIN_PART_TYPES[doc_ext].encode()
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            content = src.read(info)
            if info.filename == '[Content_Types].xml':
                content = content.replace(old, new)
            dst.writestr(info, content)
    return out.getvalue()
