"""Ticket closeout rules shared by every path that moves a ticket into a
terminal (resolved/closed) status: the web Close button and status menu,
the mobile API, AI-suggested actions and change-request verification.

A path that closes a ticket calls :func:`closeout_errors` first and refuses
the move when it returns anything.
"""
from __future__ import annotations


def requires_time():
    """True when Settings → PSA requires logged time before closing."""
    try:
        from core.models import SystemSetting
        return bool(SystemSetting.get_settings().psa_closeout_require_time)
    except Exception:
        return False


def closeout_errors(ticket, target_status, summary, category, *, show_labels=True,
                    check_time=True):
    """Why `ticket` may not move to the terminal `target_status` yet.

    Checks the resolution summary, the closure category, the operational
    sign-off, required checklist items and the optional "time logged" rule
    (skipped with ``check_time=False`` — a merged duplicate has no work of
    its own to log). Empty list = OK to close.
    """
    from .models import Ticket

    errors = []
    if not (summary or '').strip():
        errors.append('A resolution summary is required to close a ticket.')
    if category not in {key for key, _ in Ticket.CLOSURE_CATEGORIES}:
        errors.append('Pick a valid closure category.')
    if getattr(target_status, 'requires_signoff', False) and not ticket.signed_off_at:
        errors.append(
            f'"{target_status.name}" needs an operational sign-off first — '
            f'use Sign off in the closeout checklist panel.')
    outstanding = list(
        ticket.checklist_items.filter(is_required=True, is_completed=False)
        .values_list('label', flat=True)[:5]
    )
    if outstanding:
        errors.append('Required checklist items are incomplete'
                      + (': ' + '; '.join(outstanding) if show_labels else '.'))
    if check_time and requires_time() and not ticket.time_entries.filter(
            ended_at__isnull=False, duration_minutes__gt=0).exists():
        errors.append('Log time on this ticket before closing it.')
    return errors
