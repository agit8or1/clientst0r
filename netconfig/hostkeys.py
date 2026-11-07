"""
SSH host-key pinning for config collection (v3.17.629).

Before v3.17.629 the collector used Paramiko's ``AutoAddPolicy`` on a fresh
client: whatever key a device presented was accepted, so anything able to
answer on the device's address received the vault password.

Now:

* Each ``BackupTarget`` holds one **approved** host key. Collection compares
  the key the server proves it holds with the approved key *before* any
  authentication message is sent; a different or missing key stops the
  collection and the password is never transmitted.
* A presented key that is not the approved one is stored as **pending** with
  its SHA-256 fingerprint, for a person to compare against the device
  (console ``show ip ssh`` / ``ssh-keygen -lf``) and approve. Nothing is
  approved automatically, including the first key ("trust on first use" is
  not used).
* Enrollment, approval, rotation and removal are written to the audit log
  with old and new fingerprints.
* GHSA-r374-rxx8-8654 (Paramiko accepts SHA-1 RSA signatures, no fixed
  release): ``ssh-rsa`` host-key signatures are disabled unless the target is
  explicitly allowed legacy SHA-1 — RSA keys still work over rsa-sha2-256/512.
"""
from __future__ import annotations

import base64
import hashlib
import socket

from django.utils import timezone


class HostKeyError(Exception):
    """The device's identity could not be confirmed. The message reaches the operator."""


def fingerprint(key_bytes: bytes) -> str:
    """OpenSSH-style SHA256 fingerprint of a public key blob."""
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key_bytes).digest()).decode().rstrip('=')


def disabled_algorithms(target):
    if getattr(target, 'allow_legacy_ssh_rsa', False):
        return {}
    return {'keys': ['ssh-rsa'], 'pubkeys': ['ssh-rsa']}


def _preferred_key_types(transport, pinned_type=''):
    """Put the pinned key's family first so the server proves the key we hold."""
    available = list(transport.get_security_options().key_types)
    if not pinned_type:
        return available
    family = ['rsa-sha2-512', 'rsa-sha2-256', 'ssh-rsa'] if pinned_type == 'ssh-rsa' else [pinned_type]
    first = [k for k in family if k in available]
    return first + [k for k in available if k not in first]


def open_transport(target, *, timeout=30, pinned_type=''):
    """A started (key-exchanged, not authenticated) Paramiko transport."""
    import paramiko
    try:
        sock = socket.create_connection((target.host, target.port or 22), timeout=timeout)
    except OSError as exc:
        raise HostKeyError(f'Could not connect to {target.host}:{target.port or 22}: {exc}') from exc
    transport = paramiko.Transport(sock, disabled_algorithms=disabled_algorithms(target))
    transport.banner_timeout = timeout
    try:
        transport.get_security_options().key_types = _preferred_key_types(transport, pinned_type)
        transport.start_client(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — negotiation can fail many ways
        transport.close()
        hint = ''
        if 'ssh-rsa' not in getattr(transport, '_preferred_keys', ()) and not target.allow_legacy_ssh_rsa:
            hint = (' If this device only offers SHA-1 "ssh-rsa" host keys, it can be allowed explicitly '
                    'in its connection settings (legacy).')
        raise HostKeyError(f'SSH negotiation failed: {exc}.{hint}') from exc
    return transport


def presented_key(transport):
    key = transport.get_remote_server_key()
    blob = key.asbytes()
    return key.get_name(), base64.b64encode(blob).decode(), fingerprint(blob)


def _audit(user, target, action, description, extra):
    from audit.models import AuditLog
    AuditLog.log(user=user, action=action, organization=target.organization,
                 object_type='backuptarget', object_id=target.pk, object_repr=str(target)[:255],
                 description=description, extra_data=extra)


def record_pending(target, key_type, key_b64, fp, user=None, reason='observed'):
    """Park a key the device presented for review. Never approves it."""
    if target.pending_host_key == key_b64 and target.pending_host_key_type == key_type:
        target.pending_host_key_seen_at = timezone.now()
        target.save(update_fields=['pending_host_key_seen_at', 'updated_at'])
        return
    target.pending_host_key_type, target.pending_host_key = key_type, key_b64
    target.pending_host_key_fingerprint, target.pending_host_key_seen_at = fp, timezone.now()
    target.save(update_fields=['pending_host_key_type', 'pending_host_key', 'pending_host_key_fingerprint',
                               'pending_host_key_seen_at', 'updated_at'])
    _audit(user, target, 'update', f'SSH host key {reason}: {fp} (pending approval)',
           {'event': f'host_key_{reason}', 'pending_fingerprint': fp, 'pending_type': key_type,
            'approved_fingerprint': target.host_key_fingerprint})


def fetch_host_key(target, user=None, timeout=15):
    """Connect without authenticating and park the presented key as pending."""
    transport = open_transport(target, timeout=timeout, pinned_type=target.host_key_type)
    try:
        key_type, key_b64, fp = presented_key(transport)
    finally:
        transport.close()
    if key_b64 == target.host_key and key_type == target.host_key_type:
        return key_type, fp, True
    record_pending(target, key_type, key_b64, fp, user=user, reason='fetched')
    return key_type, fp, False


def approve_pending(target, user, expected_fingerprint):
    """Approve the parked key. `expected_fingerprint` is what the operator saw."""
    if not target.pending_host_key:
        raise HostKeyError('There is no pending host key to approve.')
    if expected_fingerprint.strip() != target.pending_host_key_fingerprint:
        raise HostKeyError('The pending key changed since the page was loaded. Review it again before approving.')
    _set_approved(target, user, target.pending_host_key_type, target.pending_host_key,
                  target.pending_host_key_fingerprint, source='fetched key')


def parse_public_key(text):
    """(type, base64, fingerprint) from "type base64 [comment]" or a known_hosts line."""
    import binascii
    import paramiko
    parts = (text or '').strip().split()
    for i in range(len(parts) - 1):
        key_type, b64 = parts[i], parts[i + 1]
        if not (key_type.startswith(('ssh-', 'ecdsa-', 'sk-'))):
            continue
        try:
            blob = base64.b64decode(b64, validate=True)
            key = paramiko.PKey.from_type_string(key_type, blob)
        except (binascii.Error, ValueError, paramiko.SSHException) as exc:
            raise HostKeyError(f'That is not a valid {key_type} public key ({exc}).') from exc
        return key.get_name(), base64.b64encode(key.asbytes()).decode(), fingerprint(key.asbytes())
    raise HostKeyError('Paste a public key line such as "ssh-ed25519 AAAA…" or a known_hosts entry.')


def approve_pasted(target, user, text):
    key_type, key_b64, fp = parse_public_key(text)
    _set_approved(target, user, key_type, key_b64, fp, source='pasted key')
    return fp


def _set_approved(target, user, key_type, key_b64, fp, source):
    old_fp = target.host_key_fingerprint
    target.host_key_type, target.host_key, target.host_key_fingerprint = key_type, key_b64, fp
    target.host_key_approved_at, target.host_key_approved_by = timezone.now(), user
    if target.pending_host_key == key_b64:
        target.pending_host_key_type = target.pending_host_key = target.pending_host_key_fingerprint = ''
        target.pending_host_key_seen_at = None
    target.save()
    action = 'rotated' if old_fp and old_fp != fp else 'approved'
    _audit(user, target, 'update', f'SSH host key {action} ({source}): {old_fp or "none"} → {fp}',
           {'event': f'host_key_{action}', 'old_fingerprint': old_fp, 'new_fingerprint': fp, 'type': key_type,
            'source': source})


def clear_host_key(target, user):
    old = target.host_key_fingerprint
    target.host_key_type = target.host_key = target.host_key_fingerprint = ''
    target.host_key_approved_at, target.host_key_approved_by = None, None
    target.save()
    _audit(user, target, 'update', f'SSH host key removed: {old or "none"}',
           {'event': 'host_key_removed', 'old_fingerprint': old})


def set_legacy_rsa(target, user, allowed):
    if bool(target.allow_legacy_ssh_rsa) == bool(allowed):
        return
    target.allow_legacy_ssh_rsa = bool(allowed)
    target.save(update_fields=['allow_legacy_ssh_rsa', 'updated_at'])
    _audit(user, target, 'update', f'Legacy SHA-1 ssh-rsa host keys {"allowed" if allowed else "disallowed"}',
           {'event': 'legacy_ssh_rsa', 'allowed': bool(allowed)})


def verified_transport(target, *, timeout=30):
    """A transport whose server proved it holds the approved key — or HostKeyError.

    Checked after key exchange and before authentication, so a mismatch never
    reaches the point where a password is sent.
    """
    if not target.host_key:
        raise HostKeyError('No approved SSH host key for this device; credentials were not sent.')
    transport = open_transport(target, timeout=timeout, pinned_type=target.host_key_type)
    try:
        key_type, key_b64, fp = presented_key(transport)
    except Exception:
        transport.close()
        raise
    if key_type != target.host_key_type or key_b64 != target.host_key:
        transport.close()
        record_pending(target, key_type, key_b64, fp, reason='changed')
        raise HostKeyError(
            f'SSH HOST KEY MISMATCH for {target.host}: expected {target.host_key_fingerprint} '
            f'({target.host_key_type}), the device presented {fp} ({key_type}). Credentials were NOT sent. '
            f'If the device was replaced or re-keyed, verify the new fingerprint on its console and approve it '
            f'in the connection settings.')
    return transport
