"""Optional mutual TLS for API keys (roadmap 81.8).

TLS ends at the reverse proxy, which verifies the client certificate against
your CA and passes the result on:

    X-SSL-Client-Verify: SUCCESS            ($ssl_client_verify)
    X-SSL-Client-Cert:   <URL-escaped PEM>  ($ssl_client_escaped_cert)

These headers are read only from a trusted proxy (core.client_ip), so a client
cannot claim a certificate by sending them itself. The app fingerprints the
certificate (SHA-256 of its DER form) and compares it with the fingerprint
pinned on the API key."""
import hashlib
import re
from urllib.parse import unquote

VERIFY_HEADER = 'HTTP_X_SSL_CLIENT_VERIFY'
CERT_HEADER = 'HTTP_X_SSL_CLIENT_CERT'
MAX_CERT_CHARS = 16 * 1024
_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def normalize_fingerprint(value):
    """'AB:CD:…' / 'abcd…' / 'sha256:abcd…' -> 64 lowercase hex chars, or '' (empty input).
    Raises ValueError for anything else."""
    text = (value or '').strip().lower()
    if not text:
        return ''
    if text.startswith('sha256:') or text.startswith('sha256='):
        text = text[7:]
    text = text.replace(':', '').replace(' ', '')
    if not _HEX64.match(text):
        raise ValueError('Enter the SHA-256 fingerprint of the client certificate (64 hex characters).')
    return text


def fingerprint_pem(pem_text):
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    cert = x509.load_pem_x509_certificate(pem_text.encode('ascii'))
    return hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()


def client_certificate(request):
    """(fingerprint or None, note) for the verified client certificate on this request."""
    from core.client_ip import is_trusted_peer
    verify = request.META.get(VERIFY_HEADER, '')
    raw = request.META.get(CERT_HEADER, '')
    if not verify and not raw:
        return None, 'no client certificate was presented (or the proxy does not pass one)'
    if not is_trusted_peer(request):
        return None, 'certificate headers ignored: they did not come from a trusted proxy'
    if verify != 'SUCCESS':
        return None, f'the proxy did not verify the certificate ({verify[:40] or "no result"})'
    if not raw or len(raw) > MAX_CERT_CHARS:
        return None, 'the proxy verified a certificate but did not pass it'
    try:
        return fingerprint_pem(unquote(raw)), 'verified by the proxy'
    except Exception:
        return None, 'the certificate passed by the proxy could not be read'


def key_certificate_ok(request, api_key):
    """True when the key pins no certificate, or the request presents that certificate."""
    pinned = getattr(api_key, 'client_cert_sha256', '') or ''
    if not pinned:
        return True
    fingerprint, _ = client_certificate(request)
    import hmac
    return bool(fingerprint) and hmac.compare_digest(fingerprint, pinned)
