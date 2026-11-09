"""
Sealing AI provider keys to the gateway.

Provider API keys are encrypted to an X25519 public key (ephemeral ECDH →
HKDF-SHA256 → AES-256-GCM). The web app holds only the public key, so it
can store a key an administrator typed but can never decrypt it again. The
private key lives in its own file, read by the gateway process alone.

Files (AI_GATEWAY_KEY_DIR, default ~/.config/clientst0r/ai-gateway/):
  public.key    base64 raw public key, readable by the web app
  private.key   base64 raw private key, mode 0600

Modes (AI_GATEWAY_MODE):
  worker        Only a process started with config.settings_ai_gateway
                (AI_GATEWAY_ROLE == 'worker') may load the private key.
                That process never has APP_MASTER_KEY, so it cannot open a
                vault entry, an integration credential or a backup secret.
                The web app hands it claimed runs through the database.
  in_process    The web app opens the key itself. Simpler, NOT isolated:
                the process that calls the model also holds APP_MASTER_KEY.
                Reported as such on the AI settings page.

`manage.py ai_gateway_keygen` creates the pair.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

PREFIX = 'aigw1.'
_INFO = b'clientst0r ai-gateway provider key v1'


class GatewayKeyError(Exception):
    pass


def key_dir() -> Path:
    configured = getattr(settings, 'AI_GATEWAY_KEY_DIR', '') or ''
    return Path(configured) if configured else Path.home() / '.config' / 'clientst0r' / 'ai-gateway'


def mode() -> str:
    return 'worker' if getattr(settings, 'AI_GATEWAY_MODE', 'in_process') == 'worker' else 'in_process'


def is_worker_process() -> bool:
    return getattr(settings, 'AI_GATEWAY_ROLE', '') == 'worker'


def _raw(key) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def generate(directory: Path | None = None, force=False) -> Path:
    d = directory or key_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    priv_path, pub_path = d / 'private.key', d / 'public.key'
    if priv_path.exists() and not force:
        raise GatewayKeyError(f'{priv_path} already exists. Keys sealed to it would become unreadable '
                              'if it were replaced; pass --force only if you mean to re-enter every key.')
    priv = X25519PrivateKey.generate()
    raw_priv = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption())
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as fh:
        fh.write(base64.b64encode(raw_priv).decode())
    pub_path.write_text(base64.b64encode(_raw(priv.public_key())).decode())
    os.chmod(pub_path, 0o644)
    return d


def public_key() -> X25519PublicKey:
    path = key_dir() / 'public.key'
    try:
        return X25519PublicKey.from_public_bytes(base64.b64decode(path.read_text().strip()))
    except FileNotFoundError:
        raise GatewayKeyError('The AI gateway has no key pair yet. Run: manage.py ai_gateway_keygen')
    except Exception:
        raise GatewayKeyError('The AI gateway public key is unreadable.')


def configured() -> bool:
    return (key_dir() / 'public.key').exists()


def _private_key() -> X25519PrivateKey:
    if mode() == 'worker' and not is_worker_process():
        raise GatewayKeyError('Provider keys can only be opened by the AI gateway worker.')
    path = key_dir() / 'private.key'
    try:
        return X25519PrivateKey.from_private_bytes(base64.b64decode(path.read_text().strip()))
    except FileNotFoundError:
        raise GatewayKeyError('The AI gateway private key is missing.')
    except PermissionError:
        raise GatewayKeyError('This process may not read the AI gateway private key.')


def _derive(shared: bytes, eph_pub: bytes, recipient_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=eph_pub + recipient_pub, info=_INFO).derive(shared)


def seal(plaintext: str) -> str:
    recipient = public_key()
    eph = X25519PrivateKey.generate()
    eph_pub, rec_pub = _raw(eph.public_key()), _raw(recipient)
    key = _derive(eph.exchange(recipient), eph_pub, rec_pub)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode('utf-8'), eph_pub)
    return PREFIX + base64.b64encode(eph_pub + nonce + ct).decode()


def unseal(sealed: str) -> str:
    if not sealed or not sealed.startswith(PREFIX):
        raise GatewayKeyError('Not a gateway-sealed value.')
    blob = base64.b64decode(sealed[len(PREFIX):])
    eph_pub, nonce, ct = blob[:32], blob[32:44], blob[44:]
    priv = _private_key()
    key = _derive(priv.exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, _raw(priv.public_key()))
    try:
        return AESGCM(key).decrypt(nonce, ct, eph_pub).decode('utf-8')
    except Exception:
        raise GatewayKeyError('A provider key could not be opened with this gateway key.')
