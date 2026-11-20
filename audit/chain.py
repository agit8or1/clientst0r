"""Tamper evidence for the audit log (security review SR-07).

Rows are written as before and sealed shortly after (scheduler task
``audit_chain``, or ``manage.py audit_chain seal``): in id order, each row
gets the next sequence number and

    chain_mac = HMAC-SHA256(key, previous chain_mac + canonical(row))

The key is derived from APP_MASTER_KEY (falling back to SECRET_KEY on
installs without one), which lives in the environment, not the database. So
someone with database access alone can change or remove rows, but cannot
produce MACs that verify:

- a changed row no longer matches its MAC;
- a removed row leaves a gap in the sequence;
- removed rows at the end no longer reach the recorded head;
- a row slipped in among sealed history is reported as unsealed.

The head (sequence and MAC) is also written to the application log on every
seal, so a copy exists outside the database for installs that ship logs.

Retention (``prune_before``) removes only sealed rows from the start of the
chain, after writing them to a compressed archive; the chain then starts from
the last removed row's MAC, so verification still covers what remains.

What it does not do: stop someone holding both the database and the key
from rewriting history. That needs an external append-only copy (planned).
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('audit.chain')

SEAL_BATCH = 2000
VERIFY_EVERY = timedelta(hours=24)
_LABEL = b'clientst0r audit chain v1'


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def _derive(secret):
    if not secret:
        return None
    if isinstance(secret, str):
        secret = secret.encode()
    return hmac.new(secret, _LABEL, hashlib.sha256).digest()


def _kid(key):
    return hashlib.sha256(b'kid:' + key).hexdigest()[:16]


def current_key():
    key = _derive(getattr(settings, 'APP_MASTER_KEY', '') or settings.SECRET_KEY)
    return _kid(key), key


def _keys():
    """Every key a sealed row may have used: current, then previous."""
    out = {}
    for secret in (getattr(settings, 'APP_MASTER_KEY', ''), getattr(settings, 'APP_MASTER_KEY_PREVIOUS', ''),
                   settings.SECRET_KEY):
        key = _derive(secret)
        if key:
            out.setdefault(_kid(key), key)
    return out


# ---------------------------------------------------------------------------
# Canonical form
# ---------------------------------------------------------------------------

def canonical(row):
    """The bytes a row's MAC covers: every recorded field, in a fixed order."""
    ts = row.timestamp
    data = [
        row.pk, row.chain_seq, row.user_id, row.username, row.action, row.object_type, row.object_id,
        row.object_repr, row.description, row.organization_id, row.ip_address, row.user_agent, row.path,
        ts.isoformat(timespec='microseconds') if ts else None, row.extra_data, bool(row.success),
    ]
    return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str).encode()


def _mac(key, prev_mac, row):
    return hmac.new(key, prev_mac.encode() + b'\n' + canonical(row), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------

def seal(batch=SEAL_BATCH):
    """Seal unsealed rows in id order. Returns how many were sealed.

    Safe to run from several processes: the state row is advanced with a
    compare-and-set on head_seq, so a second sealer that read the same head
    rolls back instead of forking the chain."""
    from .models import AuditChainState, AuditLog
    kid, key = current_key()
    total = 0
    while True:
        with transaction.atomic():
            state = AuditChainState.get()
            rows = list(AuditLog.objects.filter(chain_seq__isnull=True).order_by('pk')[:batch])
            if not rows:
                break
            # head_mac is the last sealed row's MAC; after a clean-up that
            # removed everything it equals base_mac, and both start empty.
            seq, prev = state.head_seq, state.head_mac
            for row in rows:
                seq += 1
                row.chain_seq = seq
                row.chain_kid = kid
                row.chain_mac = _mac(key, prev, row)
                prev = row.chain_mac
            AuditLog.objects.bulk_update(rows, ['chain_seq', 'chain_mac', 'chain_kid'])
            now = timezone.now()
            moved = AuditChainState.objects.filter(pk=state.pk, head_seq=state.head_seq).update(
                head_seq=seq, head_mac=prev, sealed_at=now)
            if not moved:
                transaction.set_rollback(True)
                logger.warning('audit chain: another sealer advanced the head; stopping this run')
                break
        total += len(rows)
        logger.info('audit chain head seq=%s mac=%s', seq, prev)
        if len(rows) < batch:
            break
    return total


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify(record=True, max_problems=20):
    """Walk the chain from its base to its head. Returns (ok, problems)."""
    from .models import AuditChainState, AuditLog
    state = AuditChainState.get()
    keys = _keys()
    problems = []
    expected, prev = state.base_seq, state.base_mac
    last_mac = prev
    qs = (AuditLog.objects.filter(chain_seq__isnull=False).order_by('chain_seq')
          .only('id', 'chain_seq', 'chain_mac', 'chain_kid', 'user_id', 'username', 'action', 'object_type',
                'object_id', 'object_repr', 'description', 'organization_id', 'ip_address', 'user_agent',
                'path', 'timestamp', 'extra_data', 'success'))
    max_pk = 0
    for row in qs.iterator(chunk_size=2000):
        if len(problems) >= max_problems:
            break
        max_pk = max(max_pk, row.pk)
        if row.chain_seq <= state.base_seq:
            problems.append(f'entry #{row.chain_seq} is older than the start of the chain')
            continue
        if row.chain_seq != expected + 1:
            problems.append(f'entries #{expected + 1}–#{row.chain_seq - 1} are missing')
        key = keys.get(row.chain_kid)
        if key is None:
            problems.append(f'entry #{row.chain_seq} was sealed with an unknown key ({row.chain_kid or "none"})')
        elif not hmac.compare_digest(_mac(key, prev, row), row.chain_mac):
            problems.append(f'entry #{row.chain_seq} (id {row.pk}) does not match its seal: changed, '
                            'or the entry before it was removed')
        expected, prev, last_mac = row.chain_seq, row.chain_mac, row.chain_mac
    if len(problems) < max_problems:
        if expected != state.head_seq or (state.head_seq and last_mac != state.head_mac):
            problems.append(f'the chain ends at #{expected} but the recorded head is #{state.head_seq}: '
                            'the newest sealed entries were removed or changed')
        inserted = AuditLog.objects.filter(chain_seq__isnull=True, pk__lt=max_pk).count()
        if inserted:
            problems.append(f'{inserted} unsealed entr{"y sits" if inserted == 1 else "ies sit"} among sealed '
                            'history (added after the fact)')
    ok = not problems
    if record:
        AuditChainState.objects.filter(pk=state.pk).update(
            verified_at=timezone.now(), verify_ok=ok, verify_detail='\n'.join(problems)[:5000])
    if not ok:
        logger.error('audit chain verification failed: %s', '; '.join(problems[:5]))
    return ok, problems


def tick():
    """Scheduler entry: seal, and verify once a day."""
    from .models import AuditChainState
    sealed = seal()
    state = AuditChainState.get()
    verified = None
    if state.verified_at is None or timezone.now() - state.verified_at >= VERIFY_EVERY:
        verified, _ = verify()
    return sealed, verified


# ---------------------------------------------------------------------------
# Export and retention
# ---------------------------------------------------------------------------

def _row_dict(row):
    return {
        'id': row.pk, 'chain_seq': row.chain_seq, 'chain_mac': row.chain_mac, 'chain_kid': row.chain_kid,
        'timestamp': row.timestamp.isoformat() if row.timestamp else None,
        'user_id': row.user_id, 'username': row.username, 'action': row.action,
        'object_type': row.object_type, 'object_id': row.object_id, 'object_repr': row.object_repr,
        'description': row.description, 'organization_id': row.organization_id,
        'ip_address': row.ip_address, 'user_agent': row.user_agent, 'path': row.path,
        'extra_data': row.extra_data, 'success': row.success,
    }


def export(queryset, path):
    """Write rows as gzip'd JSON lines (owner-only file). Returns the count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    n = 0
    with os.fdopen(fd, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb') as gz:
        for row in queryset.order_by('chain_seq', 'pk').iterator(chunk_size=2000):
            gz.write(json.dumps(_row_dict(row), default=str).encode() + b'\n')
            n += 1
        gz.flush()
        raw.flush()
        os.fsync(raw.fileno())
    return n


def archive_dir():
    from core.upgrade import journal
    return Path(journal.backup_root()) / 'audit-archive'


class PruneRefused(Exception):
    pass


def prune_before(cutoff):
    """Archive, then delete, sealed entries older than ``cutoff`` from the
    start of the chain. Returns ``(deleted, archive_path or None)``.

    Only a contiguous run from the chain's base is removed, so the chain
    stays verifiable from its new base. Refuses when the chain does not
    verify: a clean-up must not erase the evidence of tampering."""
    from .models import AuditChainState, AuditLog
    seal()
    ok, problems = verify()
    if not ok:
        raise PruneRefused('The audit log does not verify, so nothing was deleted: ' + problems[0])
    state = AuditChainState.get()
    first_kept = (AuditLog.objects.filter(chain_seq__isnull=False, timestamp__gte=cutoff)
                  .order_by('chain_seq').values_list('chain_seq', flat=True).first())
    last_removed = (first_kept - 1) if first_kept is not None else state.head_seq
    if last_removed <= state.base_seq:
        return 0, None
    doomed = AuditLog.objects.filter(chain_seq__gt=state.base_seq, chain_seq__lte=last_removed)
    stamp = timezone.now().strftime('%Y%m%dT%H%M%S')
    path = archive_dir() / f'audit-{state.base_seq + 1}-{last_removed}-{stamp}.jsonl.gz'
    written = export(doomed, path)
    boundary = AuditLog.objects.filter(chain_seq=last_removed).values_list('chain_mac', flat=True).first()
    with transaction.atomic():
        deleted = doomed.delete()[0]
        AuditChainState.objects.filter(pk=state.pk).update(base_seq=last_removed, base_mac=boundary or '')
    logger.info('audit chain pruned #%s-#%s (%s rows, archive %s)', state.base_seq + 1, last_removed,
                deleted, path)
    if written != deleted:
        logger.error('audit prune: archived %s rows but deleted %s', written, deleted)
    return deleted, path
