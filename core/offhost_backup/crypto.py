"""Streaming encryption for off-host backup archives (Phase 94.3, SR-17).

The archive is encrypted with a **backup key**: 32 random bytes generated in
Settings -> Off-host Backups, shown once for escrow, and stored on this host
only sealed with the application's secret mechanism
(``EncryptedTextField``). It is not APP_MASTER_KEY and it is never written
into an archive.

Construction: AES-256-GCM from ``cryptography`` in the segmented "STREAM"
layout (Hoang, Reyhanitabar, Rogaway, Vizar 2015 — the layout age and Tink's
AES-GCM-HKDF streaming AEAD use). Nothing new is invented here:

* A per-archive key is derived with HKDF-SHA256 from the backup key and a
  random 32-byte salt, so nonces never repeat across archives.
* The plaintext is cut into fixed-size segments. Segment ``i`` is sealed with
  nonce ``prefix(7) || i (uint32, big endian) || last-flag (1 byte)`` and the
  file header as associated data.
* The last segment carries last-flag 1. A reader refuses a stream that ends
  without a last segment (truncation), continues after one (extension),
  reorders segments (counter in the nonce) or has a changed header.

File layout::

    MAGIC(8) VERSION(1) KEY_ID(8) SALT(32) NONCE_PREFIX(7) SEGMENT_SIZE(4)
    segment_0 ... segment_n        each = ciphertext || 16-byte GCM tag

KEY_ID is the first 8 bytes of SHA-256(backup key): it tells a restorer which
escrowed key an archive needs without revealing anything about it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b'CS0RBK1\n'
VERSION = 1
SEGMENT_SIZE = 1 << 20
TAG = 16
HKDF_INFO = b'clientst0r offhost backup v1'
KEY_PREFIX = 'csbk1_'
_HEADER = struct.Struct('>8sB8s32s7sI')
HEADER_SIZE = _HEADER.size


class BackupCryptoError(Exception):
    """Wrong key, damaged or truncated archive. The message is safe to show."""


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------

def generate_key() -> str:
    """A new backup key in its printable form (``csbk1_`` + base64url)."""
    return KEY_PREFIX + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')


def decode_key(text: str) -> bytes:
    t = ''.join((text or '').split())
    if t.startswith(KEY_PREFIX):
        t = t[len(KEY_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(t + '=' * (-len(t) % 4))
    except (binascii.Error, ValueError):
        raise BackupCryptoError('That is not a backup key (expected csbk1_…).') from None
    if len(raw) != 32:
        raise BackupCryptoError('That is not a backup key (wrong length).')
    return raw


def key_id(text_or_raw) -> bytes:
    raw = text_or_raw if isinstance(text_or_raw, bytes) else decode_key(text_or_raw)
    return hashlib.sha256(raw).digest()[:8]


def key_fingerprint(text_or_raw) -> str:
    """Shown next to the key and recorded per archive, e.g. ``3fa2-91c0-77d1-0b4e``."""
    h = key_id(text_or_raw).hex()
    return '-'.join(h[i:i + 4] for i in range(0, 16, 4))


def _derive(raw_key, salt):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=HKDF_INFO).derive(raw_key)


def _nonce(prefix, counter, last):
    if counter > 0xFFFFFFFF:
        raise BackupCryptoError('archive too large for one stream')
    return prefix + struct.pack('>I', counter) + (b'\x01' if last else b'\x00')


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------

class EncryptingWriter:
    """File-like: ``write()`` plaintext, ``close()`` to seal the last segment.

    Writes ciphertext to ``sink`` (any binary file object). The sink is not
    closed. ``sha256`` is the hash of the ciphertext written, available after
    close."""

    def __init__(self, sink, key_text, segment_size=SEGMENT_SIZE):
        raw = decode_key(key_text)
        self._sink = sink
        self._seg = int(segment_size)
        salt, prefix = os.urandom(32), os.urandom(7)
        self._header = _HEADER.pack(MAGIC, VERSION, key_id(raw), salt, prefix, self._seg)
        self._aead = AESGCM(_derive(raw, salt))
        self._prefix = prefix
        self._counter = 0
        self._buf = bytearray()
        self._hash = hashlib.sha256()
        self._closed = False
        self.bytes_out = 0
        self._emit(self._header)

    def _emit(self, data):
        self._sink.write(data)
        self._hash.update(data)
        self.bytes_out += len(data)

    def _seal(self, chunk, last):
        ct = self._aead.encrypt(_nonce(self._prefix, self._counter, last), bytes(chunk), self._header)
        self._counter += 1
        self._emit(ct)

    def write(self, data):
        if self._closed:
            raise ValueError('write to closed EncryptingWriter')
        self._buf += data
        # Strictly more than a segment: the remainder at close() is the last.
        while len(self._buf) > self._seg:
            self._seal(self._buf[:self._seg], False)
            del self._buf[:self._seg]
        return len(data)

    def flush(self):
        pass

    def close(self):
        if self._closed:
            return
        self._seal(self._buf, True)
        self._buf = bytearray()
        self._closed = True

    @property
    def sha256(self):
        return self._hash.hexdigest()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.close()


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------

def read_header(f):
    head = f.read(HEADER_SIZE)
    if len(head) != HEADER_SIZE:
        raise BackupCryptoError('Not a Clientst0r off-host backup (file too short).')
    magic, version, kid, salt, prefix, seg = _HEADER.unpack(head)
    if magic != MAGIC:
        raise BackupCryptoError('Not a Clientst0r off-host backup (bad header).')
    if version != VERSION:
        raise BackupCryptoError(f'Unsupported backup format version {version}.')
    if not 1024 <= seg <= (64 << 20):
        raise BackupCryptoError('Damaged header (segment size).')
    return head, kid, salt, prefix, seg


def archive_key_fingerprint(path) -> str:
    """Which key an archive needs, read from its header."""
    with open(path, 'rb') as f:
        _, kid, *_ = read_header(f)
    h = kid.hex()
    return '-'.join(h[i:i + 4] for i in range(0, 16, 4))


def decrypt_stream(src, sink, key_text):
    """Decrypt ``src`` (binary file object) into ``sink``. Raises
    BackupCryptoError on a wrong key, tampering, truncation or extension.
    Returns the number of plaintext bytes written."""
    raw = decode_key(key_text)
    head, kid, salt, prefix, seg = read_header(src)
    if kid != key_id(raw):
        raise BackupCryptoError(
            f'This archive was encrypted with a different backup key '
            f'(archive needs key {"-".join(kid.hex()[i:i + 4] for i in range(0, 16, 4))}, '
            f'given {key_fingerprint(raw)}).')
    aead = AESGCM(_derive(raw, salt))
    size = seg + TAG
    counter, total = 0, 0
    cur = src.read(size)
    if not cur:
        raise BackupCryptoError('Archive is truncated (no data after the header).')
    while True:
        nxt = src.read(size)
        last = not nxt
        if len(cur) < TAG:
            raise BackupCryptoError('Archive is truncated.')
        try:
            pt = aead.decrypt(_nonce(prefix, counter, last), cur, head)
        except InvalidTag:
            if last:
                raise BackupCryptoError('Archive is damaged or truncated (final segment failed '
                                        'authentication).') from None
            raise BackupCryptoError(f'Archive is damaged (segment {counter} failed authentication).') from None
        sink.write(pt)
        total += len(pt)
        counter += 1
        if last:
            return total
        cur = nxt


def encrypt_file(src_path, dst_path, key_text, segment_size=SEGMENT_SIZE):
    with open(src_path, 'rb') as s, open(dst_path, 'wb') as d:
        w = EncryptingWriter(d, key_text, segment_size)
        for chunk in iter(lambda: s.read(1 << 20), b''):
            w.write(chunk)
        w.close()
    return w.sha256


def decrypt_file(src_path, dst_path, key_text):
    fd = os.open(str(dst_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(src_path, 'rb') as s, os.fdopen(fd, 'wb') as d:
        return decrypt_stream(s, d, key_text)
