"""
Connection status helper for the integrations dashboard.

`connection_status(conn)` returns a small dict the templates use to render the
status pill on each integration tile / row. The helper is intentionally tolerant
of the various per-provider connection models — they all expose the same
canonical status fields (`is_active`, `last_sync_at`, `last_sync_status`,
`last_error`) but a few use slightly different conventions for the status string.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.utils import timezone


# How fresh "last sync" must be to count as "working" when there's no error.
WORKING_FRESHNESS = timedelta(hours=24)

# Status strings that providers write into `last_sync_status` to indicate
# success vs failure. We accept several spellings because providers were
# implemented at different times.
_OK_STATUSES = {'ok', 'success', 'completed', 'complete'}
_ERROR_STATUSES = {'error', 'failed', 'failure'}
# v3.17.582 — the sync ran and reached the provider, but dropped some records
# on the way in. Not broken, and emphatically not working: the records are
# missing and the next run retries them because the status is not 'success'.
_PARTIAL_STATUSES = {'partial', 'degraded'}


def _is_enabled(conn) -> bool:
    """A connection is 'on' when both is_active and (sync_enabled if present) are true."""
    if not getattr(conn, 'is_active', True):
        return False
    # `sync_enabled` only exists on PSA / RMM / Distributor / Accounting. For
    # connections that don't have it (UniFi, M365, Omada, Grandstream) the
    # missing attribute means "no separate enable toggle" — fall back to True.
    if hasattr(conn, 'sync_enabled') and not conn.sync_enabled:
        return False
    return True


def connection_status(conn) -> dict:
    """
    Return the visual status of an integration connection.

    Returns a dict with keys:
      - state: 'off' | 'working' | 'partial' | 'broken' | 'unknown'
      - label: short human label (e.g. 'OFF', 'ON · Working')
      - tooltip: long-form description / error message for hover
      - last_at: datetime of last sync attempt, or None
    """
    last_at = getattr(conn, 'last_sync_at', None)
    last_status = (getattr(conn, 'last_sync_status', '') or '').strip().lower()
    last_error = (getattr(conn, 'last_error', '') or '').strip()

    if not _is_enabled(conn):
        return {
            'state': 'off',
            'label': 'OFF',
            'tooltip': 'This integration is disabled.',
            'last_at': last_at,
        }

    # Enabled. Decide working / partial / broken / unknown.
    #
    # Partial is checked before the error branch on purpose: a partial sync
    # writes its summary into `last_error` so the operator can see what was
    # dropped, and the error branch keys on that field being non-empty. Read
    # in the other order, every partial sync would report as broken.
    if last_status in _PARTIAL_STATUSES:
        msg = last_error or 'Some records were not synced.'
        if len(msg) > 240:
            msg = msg[:237] + '...'
        return {
            'state': 'partial',
            'label': 'ON · Partial',
            'tooltip': f'{msg}. The next sync will retry them.',
            'last_at': last_at,
        }

    if last_error or last_status in _ERROR_STATUSES:
        # Truncate huge tracebacks for the tooltip.
        msg = last_error or 'Last sync reported an error.'
        if len(msg) > 240:
            msg = msg[:237] + '...'
        return {
            'state': 'broken',
            'label': 'ON · Broken',
            'tooltip': msg,
            'last_at': last_at,
        }

    if last_status in _OK_STATUSES:
        # If the last sync was a long time ago we still call it working — the
        # admin gets the timestamp and can decide. We only flip to "unknown"
        # when nothing has ever synced.
        return {
            'state': 'working',
            'label': 'ON · Working',
            'tooltip': _working_tooltip(last_at),
            'last_at': last_at,
        }

    # Enabled but no concrete sync result yet. If a recent sync exists with
    # an unrecognised status string, treat it as working; otherwise unknown.
    if last_at and (timezone.now() - last_at) < WORKING_FRESHNESS:
        return {
            'state': 'working',
            'label': 'ON · Working',
            'tooltip': _working_tooltip(last_at),
            'last_at': last_at,
        }

    return {
        'state': 'unknown',
        'label': 'ON · Unknown',
        'tooltip': 'Enabled but has not been tested or synced yet.',
        'last_at': last_at,
    }


def _working_tooltip(last_at: Optional[object]) -> str:
    if not last_at:
        return 'Enabled and reporting OK.'
    return f'Last sync OK at {last_at:%Y-%m-%d %H:%M %Z}.'
