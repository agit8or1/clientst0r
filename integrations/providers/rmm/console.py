"""Links from a ClientSt0r page into an RMM's own web console.

An adapter offers a device link only when the vendor documents (or itself
returns) a per-device console address for that deployment. The link is
rebuilt from synced data at render time, so a vendor outage never stops a
page from loading, and it is checked here before it reaches the browser:
https only, a host from the adapter's list for this connection, no user
info, and nothing that looks like a credential in the query string.
"""
from urllib.parse import urlsplit, parse_qsl

CREDENTIAL_WORDS = ('key', 'token', 'secret', 'password', 'passwd', 'auth', 'apikey', 'signature', 'sig')


def host_of(url):
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


def validated_console_url(url, allowed_hosts):
    """`url` if it is safe to show for these hosts, else ''."""
    if not url or not isinstance(url, str):
        return ''
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ''
    if parts.scheme != 'https' or parts.username or parts.password or not parts.hostname:
        return ''
    host = parts.hostname.lower()
    allowed = {h.lower() for h in allowed_hosts if h}
    if host not in allowed:
        return ''
    for name, _value in parse_qsl(parts.query, keep_blank_values=True):
        low = name.lower()
        if any(word in low for word in CREDENTIAL_WORDS):
            return ''
    return url.strip()
