"""What a ticket attachment may be (SR-06).

Used by the ticket upload view and inbound e-mail. The stored type comes from
the extension through this map, which mirrors the attachment allowlist, never
from the type a browser or mail sender declared; the content must match the
extension where the type has a signature; a blocked type anywhere in the name
("invoice.pdf.exe" is caught by the last part, "report.exe.pdf" by an inner
one) is refused. Serving is separately safe (type from the stored name,
nosniff, SVG downloads with a sandbox CSP).
"""
from files import upload_rules

TYPES_BY_EXT = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp',
    'svg': 'image/svg+xml',
    'txt': 'text/plain', 'log': 'text/plain', 'csv': 'text/csv', 'md': 'text/markdown',
    'json': 'application/json',
    'zip': 'application/zip',
}
BLOCKED_INNER = {'exe', 'dll', 'msi', 'scr', 'com', 'bat', 'cmd', 'ps1', 'vbs', 'js', 'jse', 'wsf', 'hta',
                 'sh', 'php', 'jsp', 'asp', 'aspx', 'html', 'htm', 'xhtml'}


def check(name, header: bytes):
    """(content type to store, '') or ('', reason)."""
    parts = (name or '').lower().split('.')
    ext = parts[-1] if len(parts) > 1 else ''
    content_type = TYPES_BY_EXT.get(ext)
    if not content_type or any(p in BLOCKED_INNER for p in parts[1:-1]):
        return '', f'File type ".{ext}" not allowed.' if ext else 'Files without an extension are not allowed.'
    if upload_rules.check_magic(name, header):
        return '', 'The file content does not match its type.'
    return content_type, ''


def attachment_problem(f):
    """check() for an uploaded file; leaves the file at its start."""
    header = f.read(512)
    f.seek(0)
    return check(f.name or '', header)
