"""Rules every stored attachment must pass, shared by the upload view and the
IT Glue / Hudu migration (which stores source attachments the same way)."""
from __future__ import annotations

import mimetypes

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB

ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',  # Documents
    'txt', 'csv', 'md', 'log',  # Text files
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp',  # Images
    'zip', '7z', 'tar', 'gz', 'rar',  # Archives
    'json', 'xml', 'yaml', 'yml',  # Data files
}

DANGEROUS_PATTERNS = ['.exe', '.bat', '.cmd', '.sh', '.php', '.jsp', '.asp', '.aspx', '.js', '.vbs', '.scr']

# Magic bytes signatures for common file types
MAGIC_BYTES = {
    'pdf': [b'%PDF'],
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF87a', b'GIF89a'],
    'zip': [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
    'docx': [b'PK\x03\x04'],  # DOCX is a ZIP archive
    'xlsx': [b'PK\x03\x04'],  # XLSX is a ZIP archive
    'pptx': [b'PK\x03\x04'],  # PPTX is a ZIP archive
    '7z': [b'7z\xbc\xaf\x27\x1c'],
    'gz': [b'\x1f\x8b'],
    'bmp': [b'BM'],
}

GENERIC_CONTENT_TYPES = {'', 'application/octet-stream', 'binary/octet-stream',
                         'application/x-download', 'application/download'}


def extension(filename) -> str:
    name = (filename or '').lower()
    return name.rsplit('.', 1)[-1] if '.' in name else ''


def check_name(filename) -> str:
    """'' when the file name is acceptable, otherwise the reason."""
    ext = extension(filename)
    if not ext or ext not in ALLOWED_EXTENSIONS:
        return 'file type not allowed'
    lowered = (filename or '').lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in lowered:
            return 'file type not allowed'
    return ''


def check_magic(filename, header: bytes) -> str:
    ext = extension(filename)
    if ext in MAGIC_BYTES and not any(header.startswith(m) for m in MAGIC_BYTES[ext]):
        return 'file content does not match its extension'
    return ''


def content_type_for(filename) -> str:
    return mimetypes.guess_type(filename or '')[0] or 'application/octet-stream'


def check_declared_type(filename, declared) -> str:
    """A declared (source) content type must agree with the extension."""
    declared = (declared or '').split(';')[0].strip().lower()
    if declared in GENERIC_CONTENT_TYPES:
        return ''
    expected = content_type_for(filename)
    if declared == expected:
        return ''
    if declared.split('/')[0] == expected.split('/')[0] and declared.split('/')[0] in ('image', 'text'):
        return ''
    if expected == 'application/octet-stream':
        return ''
    return f'declared content type {declared} does not match .{extension(filename)}'


def check_file(filename, content: bytes, declared_type='', max_bytes=MAX_FILE_SIZE) -> str:
    """'' when ``content`` may be stored as an attachment, otherwise the reason."""
    if len(content) > max_bytes:
        return f'file exceeds the {max_bytes // (1024 * 1024)}MB limit'
    return (check_name(filename) or check_declared_type(filename, declared_type)
            or check_magic(filename, content[:512]))
