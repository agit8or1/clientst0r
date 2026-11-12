"""
Standard sync health for every integration connection.

Each connection model already carries `last_sync_at` / `last_sync_status` /
`last_error`, but those three fields cannot say *when the last successful sync
was* once a later attempt has failed, how many records a run created, updated,
skipped or dropped, which customer or site was affected, or what the admin
should do about it. `IntegrationSyncHealth` (one row per connection, generic
FK) holds that, and this module is the one place that writes and reads it:

    record_sync(conn, 'unifi', status='partial', created=3, skipped=2,
                issues=[issue('Site "Branch" is not mapped', site='Branch',
                              action='Map site "Branch" to a customer ...')])

    health_for(conn)   # -> dict for templates; falls back to the legacy
                       #    fields for connections that never wrote a row

Everything that goes into storage or onto a page passes through `redact()`,
so tokens, keys, passwords and URLs with embedded credentials never reach the
health row, the connection's `last_error`, the UI or the audit log.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from django.utils import timezone

STATUS_SUCCESS = 'success'
STATUS_PARTIAL = 'partial'
STATUS_ERROR = 'error'
STATUS_NEVER = 'never'

_LEGACY_OK = {'ok', 'success', 'completed', 'complete'}
_LEGACY_PARTIAL = {'partial', 'degraded'}
_LEGACY_ERROR = {'error', 'failed', 'failure'}

MAX_ERROR = 2000
MAX_ISSUES = 50

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_SECRET_WORDS = (
    r'api[ _-]?key|apikey|x-api-key|access[_-]?token|refresh[_-]?token|id[_-]?token|'
    r'auth[_-]?token|token|client[_-]?secret|secret|password|passwd|pwd|passphrase|'
    r'private[_-]?key|public[_-]?key|signature|sig|session[_-]?id|sessionid|unifises|'
    r'csrf[_-]?token'
)

_REDACTIONS = [
    # scheme://user:password@host  /  scheme://token@host
    (re.compile(r'(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@\'"<>]+@'), r'\1***@'),
    # Authorization: Bearer xyz / Basic xyz / Token xyz
    (re.compile(r'(?i)\b(authorization|proxy-authorization)(["\']?\s*[:=]\s*["\']?)'
                r'(?:(bearer|basic|token|digest)\s+)?[^\s,"\'}]+'),
     lambda m: f"{m.group(1)}{m.group(2)}{(m.group(3) + ' ') if m.group(3) else ''}***"),
    (re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}'), r'\1 ***'),
    # "password": "x"  /  'api_key': 'x'
    (re.compile(r'(?i)(["\'](?:' + _SECRET_WORDS + r')["\']\s*:\s*)(["\'])(?:\\.|(?!\2).)*\2'),
     r'\1\2***\2'),
    # password=x, ?api_key=x&..., X-API-KEY: x, token: x
    (re.compile(r'(?i)\b(' + _SECRET_WORDS + r')(\s*[=:]\s*)(?!\*\*\*)([^\s&,;"\'<>)}\]]+)'),
     r'\1\2***'),
    # JSON web tokens anywhere
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}'), '***'),
]


def credential_values(conn) -> list[str]:
    """Plain credential values held by `conn` (to scrub literally from text)."""
    values = []
    getter = getattr(conn, 'get_credentials', None)
    if not callable(getter):
        return values
    try:
        creds = getter() or {}
    except Exception:
        return values
    for key, value in creds.items():
        if isinstance(value, str) and len(value) >= 4:
            # A username alone is not a secret, but it is often half of one and
            # harmless to hide; hostnames and tenant ids are left alone because
            # admins need them to diagnose reachability.
            if key in ('host', 'base_url', 'tenant_id', 'region', 'site'):
                continue
            values.append(value)
    return values


def redact(text, secrets: Iterable[str] = ()) -> str:
    """Return `text` with credentials replaced by ***."""
    if text is None:
        return ''
    out = str(text)
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        out = out.replace(secret, '***')
    for pattern, repl in _REDACTIONS:
        out = pattern.sub(repl, out)
    return out


def redact_for(conn, text) -> str:
    return redact(text, credential_values(conn))


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------

def _edit_hint(conn) -> str:
    name = getattr(conn, 'name', '') or 'this connection'
    return f'Integrations → {name} → Edit'


def suggest_action(error: str, conn=None) -> str:
    """A specific next step for the admin, derived from a (redacted) error."""
    if not error:
        return ''
    e = error.lower()
    edit = _edit_hint(conn)
    host = (getattr(conn, 'host', '') or getattr(conn, 'base_url', '') or '') if conn else ''
    host_part = f' ({redact(host)})' if host else ''

    if any(s in e for s in ('certificate verify failed', 'certificate_verify_failed',
                            'ssl: ', 'sslerror', 'self signed', 'self-signed')):
        return (f'TLS certificate check failed{host_part}: install a trusted certificate on the '
                f'server, or untick "Verify SSL" in {edit}.')
    if any(s in e for s in ('address not allowed', 'resolves to an address this connection may not use',
                            'hostname not allowed', 'port not allowed', 'scheme not allowed',
                            'embedded credentials')):
        return (f'The outbound request policy blocked this address{host_part}. Use a permitted '
                f'URL in {edit}, or ask a superuser to allow LAN integrations.')
    if any(s in e for s in ('401', 'unauthorized', 'unauthorised', '403', 'forbidden',
                            'invalid api key', 'invalid_api_key', 'invalid credentials',
                            'authentication failed', 'login failed', 'invalid_client',
                            'invalid_grant', 'aadsts', 'access denied', 'not authorized',
                            'bad credentials', 'expired token', 'token expired')):
        return f'The provider rejected the credentials: re-enter the API key / password in {edit}.'
    if any(s in e for s in ('connection refused', 'timed out', 'timeout', 'name or service not known',
                            'failed to resolve', 'did not resolve', 'nodename nor servname',
                            'temporary failure in name resolution', 'max retries exceeded',
                            'no route to host', 'network is unreachable', 'newconnectionerror',
                            'connectionerror', 'connection reset', 'connection aborted')):
        return (f'Unreachable{host_part}: check the URL and port in {edit}, and that this server '
                'can reach it through the firewall.')
    if '429' in e or 'rate limit' in e or 'too many requests' in e:
        return 'The provider is rate-limiting requests: lower the sync frequency or retry later.'
    if '404' in e or 'not found' in e:
        return f'Endpoint not found: check the URL / base path in {edit}.'
    if any(s in e for s in ('500', '502', '503', '504', 'internal server error', 'bad gateway',
                            'service unavailable')):
        return 'The provider returned a server error: retry later; if it persists, check the provider status.'
    if 'failed to sync' in e:
        return 'Some records were rejected: the next sync retries them. Check the log for the record-level error.'
    return 'Fix the error above, then use Test / Sync Now to retry.'


def issue(message: str, *, customer: str = '', site: str = '', action: str = '',
          kind: str = '') -> dict:
    """One affected customer / site with what to do about it."""
    return {'message': message, 'customer': customer or '', 'site': site or '',
            'action': action or '', 'kind': kind or ''}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def record_sync(conn, kind: str, *, status: str, created: int = 0, updated: int = 0,
                skipped: int = 0, failed: int = 0, error: str = '',
                issues: Optional[list] = None, action: str = '',
                update_connection: bool = True, legacy_ok: str = 'ok', when=None):
    """Store the outcome of one sync attempt for `conn`.

    `status` is success / partial / error. With `update_connection` (default)
    the connection's own `last_sync_at` / `last_sync_status` / `last_error` are
    written too (`legacy_ok` is the spelling that connection type uses for a
    clean run, e.g. 'ok' for network controllers); pass False when the caller
    already maintains those fields, as the PSA/RMM engines do.
    Never raises: health bookkeeping must not break a sync.
    """
    import logging
    from django.contrib.contenttypes.models import ContentType
    from .models import IntegrationSyncHealth

    logger = logging.getLogger('integrations')
    now = when or timezone.now()
    secrets = credential_values(conn)
    clean_error = redact(error, secrets)[:MAX_ERROR]
    clean_issues = []
    for it in (issues or [])[:MAX_ISSUES]:
        clean_issues.append({k: redact(v, secrets) if isinstance(v, str) else v
                             for k, v in it.items()})
    if not action:
        if clean_error:
            action = suggest_action(clean_error, conn)
        elif clean_issues:
            action = next((i['action'] for i in clean_issues if i.get('action')), '')
    action = redact(action, secrets)

    if update_connection:
        try:
            conn.last_sync_at = now
            conn.last_sync_status = legacy_ok if status == STATUS_SUCCESS else status
            summary = clean_error
            if not summary and status == STATUS_PARTIAL:
                summary = '; '.join(i['message'] for i in clean_issues[:5])
            conn.last_error = summary[:MAX_ERROR]
            conn.save(update_fields=['last_sync_at', 'last_sync_status', 'last_error'])
        except Exception:
            logger.exception('could not update sync fields on %s', conn)

    try:
        ct = ContentType.objects.get_for_model(type(conn))
        row, _ = IntegrationSyncHealth.objects.get_or_create(
            content_type=ct, object_id=conn.pk, kind=kind,
            defaults={'organization_id': getattr(conn, 'organization_id', None)})
        row.organization_id = getattr(conn, 'organization_id', None)
        row.status = status
        row.last_attempt_at = now
        if status in (STATUS_SUCCESS, STATUS_PARTIAL):
            # A partial run did reach the provider and land records, so it
            # counts as "last sync that got through"; `status` still says partial.
            row.last_success_at = now
        row.created_count = max(int(created or 0), 0)
        row.updated_count = max(int(updated or 0), 0)
        row.skipped_count = max(int(skipped or 0), 0)
        row.failed_count = max(int(failed or 0), 0)
        row.error = clean_error
        row.issues = clean_issues
        row.corrective_action = action[:1000]
        row.save()
        return row
    except Exception:
        logger.exception('could not record sync health for %s', conn)
        return None


def stats_counts(stats: dict) -> dict:
    """Sum a PSA/RMM-style {entity: {created, updated, errors}} dict."""
    out = {'created': 0, 'updated': 0, 'failed': 0}
    for counts in (stats or {}).values():
        out['created'] += counts.get('created', 0) or 0
        out['updated'] += counts.get('updated', 0) or 0
        out['failed'] += counts.get('errors', 0) or 0
    return out


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

# Health rows that describe a connection's contract pairing rather than its
# sync (integrations.rem0te.health). The sync health of a connection never
# reads them.
SUBSYSTEM_KINDS = ('rem0te',)


def get_health_row(conn, kind=None):
    """The connection's sync health row (or the row of `kind`)."""
    from django.contrib.contenttypes.models import ContentType
    from .models import IntegrationSyncHealth
    if conn is None or not getattr(conn, 'pk', None):
        return None
    try:
        ct = ContentType.objects.get_for_model(type(conn))
        qs = IntegrationSyncHealth.objects.filter(content_type=ct, object_id=conn.pk)
        qs = qs.filter(kind=kind) if kind else qs.exclude(kind__in=SUBSYSTEM_KINDS)
        return qs.order_by('-updated_at').first()
    except Exception:
        return None


def health_for(conn, row=None) -> dict:
    """Template-ready health for `conn`, from its health row or legacy fields.

    `row=False` means "known to have no row": skip the lookup.
    """
    if row is None:
        row = get_health_row(conn)
    secrets = credential_values(conn)
    if row:
        error = redact(row.error, secrets)
        return {
            'status': row.status or STATUS_NEVER,
            'last_attempt_at': row.last_attempt_at,
            'last_success_at': row.last_success_at,
            'created': row.created_count,
            'updated': row.updated_count,
            'skipped': row.skipped_count,
            'failed': row.failed_count,
            'has_counts': True,
            'error': error,
            'issues': [{k: redact(v, secrets) if isinstance(v, str) else v for k, v in i.items()}
                       for i in (row.issues or [])],
            'action': redact(row.corrective_action, secrets) or suggest_action(error, conn),
            'source': 'health',
        }

    legacy = (getattr(conn, 'last_sync_status', '') or '').strip().lower()
    last_at = getattr(conn, 'last_sync_at', None)
    error = redact(getattr(conn, 'last_error', '') or '', secrets)
    if legacy in _LEGACY_PARTIAL:
        status = STATUS_PARTIAL
    elif legacy in _LEGACY_ERROR or (error and legacy not in _LEGACY_OK):
        status = STATUS_ERROR
    elif legacy in _LEGACY_OK:
        status = STATUS_SUCCESS
    elif last_at:
        status = STATUS_SUCCESS
    else:
        status = STATUS_NEVER
    return {
        'status': status,
        'last_attempt_at': last_at,
        'last_success_at': last_at if status in (STATUS_SUCCESS, STATUS_PARTIAL) else None,
        'created': None, 'updated': None, 'skipped': None, 'failed': None,
        'has_counts': False,
        'error': error,
        'issues': [],
        'action': suggest_action(error, conn) if status in (STATUS_ERROR, STATUS_PARTIAL) else '',
        'source': 'legacy',
    }


def record_owner_change(conn):
    """Keep the connection's health rows with its owner (a platform-owned
    connection's rows belong to no customer)."""
    from django.contrib.contenttypes.models import ContentType
    from .models import IntegrationSyncHealth
    ct = ContentType.objects.get_for_model(type(conn))
    IntegrationSyncHealth.objects.filter(content_type=ct, object_id=conn.pk).update(
        organization_id=getattr(conn, 'organization_id', None))
