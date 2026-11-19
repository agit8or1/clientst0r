"""Checks for files stored as documents (SR-05).

Documentation accepts a wide range of file types, so this is not the narrow
attachment allowlist: it refuses executable and script types and HTML (active
content), enforces the 50MB limit the upload form states, checks magic bytes
for the types that have one, and gives the stored type from the file name
rather than the browser's declared type. Serving is separately safe: the media
view derives the type from the stored name, sends nosniff and only shows
allowlisted types inline.
"""
from files import upload_rules

MAX_DOCUMENT_BYTES = 50 * 1024 * 1024

BLOCKED_EXTENSIONS = {
    # executables and installers
    'exe', 'dll', 'com', 'msi', 'msp', 'scr', 'pif', 'cpl', 'jar', 'apk', 'app', 'deb', 'rpm',
    # scripts
    'bat', 'cmd', 'sh', 'bash', 'ps1', 'psm1', 'vbs', 'vbe', 'js', 'jse', 'mjs', 'wsf', 'wsh', 'hta',
    'php', 'phtml', 'jsp', 'asp', 'aspx', 'cgi', 'pl', 'py', 'rb',
    # active web content
    'html', 'htm', 'xhtml', 'shtml', 'mht', 'mhtml', 'svgz',
}


def check(uploaded) -> str:
    """'' when the uploaded file may be stored as a document, otherwise why not."""
    name = getattr(uploaded, 'name', '') or ''
    if getattr(uploaded, 'size', 0) > MAX_DOCUMENT_BYTES:
        return f'file exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB limit'
    parts = name.lower().split('.')
    # Any blocked extension anywhere in the name refuses it ("invoice.pdf.exe",
    # "x.exe.txt"); a name with no extension at all is refused too.
    if len(parts) < 2 or any(p in BLOCKED_EXTENSIONS for p in parts[1:]):
        return 'file type not allowed'
    header = uploaded.read(512)
    uploaded.seek(0)
    return upload_rules.check_magic(name, header)


def stored_type(uploaded) -> str:
    """The type recorded for the file: from its name, never the declared one."""
    return upload_rules.content_type_for(getattr(uploaded, 'name', ''))
