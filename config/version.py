"""
Version information for HuduGlue
"""

VERSION = '2.24.8'
VERSION_INFO = {
    'major': 2,
    'minor': 24,
    'patch': 8,
    'status': 'stable',  # alpha, beta, rc, stable
}

def get_version():
    """Return version string."""
    return VERSION

def get_version_info():
    """Return version info dict."""
    return VERSION_INFO

def get_full_version():
    """Return full version string with status."""
    status = VERSION_INFO['status']
    if status == 'stable':
        return VERSION
    return f"{VERSION}-{status}"
