"""Where off-host archives go: an SFTP server or a mounted directory.

S3-compatible object storage is not offered: neither boto3/botocore nor
another S3 client is installed, and the request signing is not something to
hand-roll. A bucket can still be used through an SFTP gateway or a mounted
directory (s3fs, rclone mount).

SFTP connections
    * The address is resolved and checked with core.safe_http's LAN policy
      before connecting (LAN addresses allowed — a NAS is the usual target;
      cloud metadata and non-unicast always refused; loopback/link-local only
      with ALLOW_PRIVATE_IP_INTEGRATIONS), and the socket goes to the checked
      address, so DNS cannot be re-pointed between check and connect.
    * The server must prove it holds the **approved host key** before any
      credential is sent — the same pinning as network-config collection
      (netconfig.hostkeys, v3.17.629). An unknown or changed key is parked as
      pending for an administrator to compare and approve; nothing is
      trusted on first use.
    * Credentials (password or private key) are stored with EncryptedTextField
      and never logged or included in error messages.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import stat
import types
from pathlib import Path

from django.conf import settings

NAME_PREFIX = 'clientst0r-offhost-'
NAME_SUFFIX = '.csbk'
NAME_RE = re.compile(r'^clientst0r-offhost-(\d{8})T(\d{6})Z\.csbk$')


class DestinationError(Exception):
    """The destination could not be used. The message is safe to show and log."""


def is_archive_name(name):
    return bool(NAME_RE.match(name or ''))


class LocalDirDestination:
    def __init__(self, path):
        if not path:
            raise DestinationError('No directory is configured.')
        self.root = Path(path).expanduser()
        resolved = self.root.resolve()
        for label, inside in (('the application directory', settings.BASE_DIR),
                              ('the uploaded-files directory', settings.MEDIA_ROOT)):
            try:
                resolved.relative_to(Path(inside).resolve())
            except ValueError:
                continue
            raise DestinationError(f'The backup directory may not be inside {label}.')
        if not self.root.is_dir():
            raise DestinationError(f'{self.root} does not exist or is not a directory (is the share mounted?).')
        if not os.access(self.root, os.W_OK):
            raise DestinationError(f'{self.root} is not writable by the application user.')

    def label(self):
        return str(self.root)

    def same_filesystem_as_app(self):
        try:
            return os.stat(self.root).st_dev == os.stat(settings.BASE_DIR).st_dev
        except OSError:
            return False

    def put(self, local_path, name):
        tmp = self.root / f'.{name}.part'
        with open(local_path, 'rb') as s:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as d:
                shutil.copyfileobj(s, d, 1 << 20)
                d.flush()
                os.fsync(d.fileno())
        os.replace(tmp, self.root / name)

    def list(self):
        out = []
        for p in self.root.iterdir():
            if is_archive_name(p.name) and p.is_file():
                st = p.stat()
                out.append({'name': p.name, 'size': st.st_size})
        return sorted(out, key=lambda r: r['name'])

    def get(self, name, local_path):
        if not is_archive_name(name):
            raise DestinationError('not a backup archive name')
        shutil.copyfile(self.root / name, local_path)

    def delete(self, name):
        if not is_archive_name(name):
            raise DestinationError('refusing to delete a file that is not a backup archive')
        (self.root / name).unlink()

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def load_private_key(text):
    import paramiko
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except Exception:  # noqa: BLE001 — try the next key type
            continue
    raise DestinationError('The stored SSH private key could not be read (unsupported type or passphrase-protected).')


def generate_ssh_keypair():
    """(private OpenSSH PEM, public 'ssh-ed25519 …' line) for the SFTP account."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                           serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                      serialization.PublicFormat.OpenSSH).decode()
    return priv, pub + ' clientst0r-offhost-backup'


def public_key_of(private_text):
    if not private_text:
        return ''
    try:
        k = load_private_key(private_text)
    except DestinationError:
        return ''
    return f'{k.get_name()} {k.get_base64()} clientst0r-offhost-backup'


def _resolve(host, port):
    from core.safe_http import UnsafeURLError, lan_controller_policy, resolve_public_addresses
    try:
        return resolve_public_addresses(host, port, lan_controller_policy())[0]
    except UnsafeURLError as e:
        raise DestinationError(f'{host} may not be used as a backup destination: {e}') from None
    except OSError as e:
        raise DestinationError(f'{host} could not be resolved ({e.__class__.__name__}).') from None


def _transport(cfg, timeout=30):
    from netconfig import hostkeys
    ip = _resolve(cfg.sftp_host, cfg.sftp_port or 22)
    proxy = types.SimpleNamespace(host=ip, port=cfg.sftp_port or 22, allow_legacy_ssh_rsa=cfg.allow_legacy_ssh_rsa)
    try:
        transport = hostkeys.open_transport(proxy, timeout=timeout, pinned_type=cfg.host_key_type)
    except hostkeys.HostKeyError as e:
        raise DestinationError(str(e)) from None
    return transport


def fetch_host_key(cfg, user=None):
    """Connect without authenticating and park the server's key as pending.
    Returns (type, fingerprint, already_approved)."""
    from netconfig import hostkeys
    transport = _transport(cfg, timeout=15)
    try:
        key_type, key_b64, fp = hostkeys.presented_key(transport)
    finally:
        transport.close()
    if key_b64 == cfg.host_key and key_type == cfg.host_key_type:
        return key_type, fp, True
    hostkeys.record_pending(cfg, key_type, key_b64, fp, user=user, reason='fetched')
    return key_type, fp, False


class SFTPDestination:
    def __init__(self, cfg, timeout=30):
        from netconfig import hostkeys
        if not (cfg.sftp_host and cfg.sftp_username):
            raise DestinationError('The SFTP server and user name are not configured.')
        if not cfg.host_key:
            raise DestinationError('No approved SSH host key for the backup server. Fetch and approve it in '
                                   'Settings -> Off-host Backups; credentials were not sent.')
        self.cfg = cfg
        self.dir = (cfg.sftp_path or '.').rstrip('/') or '/'
        transport = _transport(cfg, timeout=timeout)
        try:
            key_type, key_b64, fp = hostkeys.presented_key(transport)
            if key_type != cfg.host_key_type or key_b64 != cfg.host_key:
                hostkeys.record_pending(cfg, key_type, key_b64, fp, reason='changed')
                raise DestinationError(
                    f'SSH HOST KEY MISMATCH for {cfg.sftp_host}: expected {cfg.host_key_fingerprint}, the server '
                    f'presented {fp}. Credentials were NOT sent and nothing was uploaded. If the server was '
                    f'replaced or re-keyed, compare the new fingerprint on the server and approve it.')
            try:
                if cfg.sftp_private_key:
                    transport.auth_publickey(cfg.sftp_username, load_private_key(cfg.sftp_private_key))
                else:
                    transport.auth_password(cfg.sftp_username, cfg.sftp_password)
            except DestinationError:
                raise
            except Exception as e:  # noqa: BLE001 — message never includes the secret
                raise DestinationError(f'SFTP sign-in as {cfg.sftp_username} was refused '
                                       f'({e.__class__.__name__}).') from None
            import paramiko
            self.sftp = paramiko.SFTPClient.from_transport(transport)
        except BaseException:
            transport.close()
            raise
        self.transport = transport

    def label(self):
        return self.cfg.destination_label()

    def _p(self, name):
        return f'{self.dir}/{name}'

    def put(self, local_path, name):
        tmp = self._p(f'.{name}.part')
        self.sftp.put(str(local_path), tmp, confirm=True)
        try:
            self.sftp.chmod(tmp, 0o600)
        except OSError:
            pass
        try:
            self.sftp.posix_rename(tmp, self._p(name))
        except (OSError, IOError):
            self.sftp.rename(tmp, self._p(name))

    def list(self):
        out = []
        try:
            entries = self.sftp.listdir_attr(self.dir)
        except (OSError, IOError) as e:
            raise DestinationError(f'Cannot list {self.dir} on the backup server ({e}).') from None
        for a in entries:
            if is_archive_name(a.filename) and stat.S_ISREG(a.st_mode or 0):
                out.append({'name': a.filename, 'size': a.st_size})
        return sorted(out, key=lambda r: r['name'])

    def get(self, name, local_path):
        if not is_archive_name(name):
            raise DestinationError('not a backup archive name')
        self.sftp.get(self._p(name), str(local_path))

    def delete(self, name):
        if not is_archive_name(name):
            raise DestinationError('refusing to delete a file that is not a backup archive')
        self.sftp.remove(self._p(name))

    def close(self):
        try:
            self.sftp.close()
        finally:
            self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_destination(cfg):
    if cfg.destination_type == cfg.DEST_LOCAL:
        return LocalDirDestination(cfg.local_path)
    if cfg.destination_type == cfg.DEST_SFTP:
        return SFTPDestination(cfg)
    raise DestinationError(f'Unknown destination type {cfg.destination_type!r}.')
