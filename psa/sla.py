"""
SLA computation helpers.

Phase 2c keeps it pragmatic: due-dates are computed from the priority's
`response_target_minutes` / `resolution_target_minutes`, anchored at
`Ticket.created_at`. Business hours and holidays land in a later phase
(needs a calendar source we don't yet have).

Pause logic (v3.17.563): entering a status with `pauses_sla=True`
(Waiting on Client / Vendor) stamps `Ticket.sla_paused_at`. Leaving it
adds the elapsed time to `Ticket.sla_paused_minutes` and pushes both
due-dates out by the same amount, so time spent waiting on someone
else is not charged against the technician's SLA.

Until v3.17.563 this module's docstring claimed that already happened.
It did not: a paused status only suppressed the breach badge, the
declared `sla_paused_until` field was never written by any code, and a
ticket parked for three days came back with its original deadline and
breached immediately.

Breach state (v3.17.563): `refresh_breach_flags` persists the live
computation onto `Ticket.sla_breached_response` / `_resolution`. Those
columns are what the SLA breach report and the breach KPI read, and
nothing had ever set them, so both reported zero while the ticket badge
— computed live by the functions below — said otherwise.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone


def compute_due_dates(ticket):
    """Return (first_response_due_at, resolution_due_at) — both UTC dt
    or None if priority has no targets.

    The contract's per-priority SLA matrix overrides the priority's
    default targets when the ticket's client has an active contract.
    Schema: contract.sla_matrix = {"<priority_code_or_slug>": {
        "response_minutes": int, "resolution_minutes": int}, ...}.
    """
    if ticket.priority_id is None:
        return None, None
    base = ticket.created_at or timezone.now()
    rt = int(getattr(ticket.priority, 'response_target_minutes', 0) or 0)
    res = int(getattr(ticket.priority, 'resolution_target_minutes', 0) or 0)

    # Contract override — only when an active contract exists for the
    # ticket's client AND the matrix has an entry for this priority.
    try:
        from .models import Contract
        contract = Contract.for_ticket(ticket)
    except Exception:
        contract = None
    if contract and isinstance(contract.sla_matrix, dict):
        prio_key = (
            getattr(ticket.priority, 'code', None)
            or getattr(ticket.priority, 'slug', None)
            or ''
        )
        entry = contract.sla_matrix.get(prio_key) or contract.sla_matrix.get(prio_key.lower())
        if isinstance(entry, dict):
            try:
                rt = int(entry.get('response_minutes', rt) or rt)
                res = int(entry.get('resolution_minutes', res) or res)
            except (TypeError, ValueError):
                pass
    return (
        base + timedelta(minutes=rt) if rt else None,
        base + timedelta(minutes=res) if res else None,
    )


def apply_due_dates(ticket, *, save=True):
    """Set the due-date columns from the priority. Used on create + when
    priority changes."""
    fr, res = compute_due_dates(ticket)
    ticket.first_response_due_at = fr
    ticket.resolution_due_at = res
    if save:
        ticket.save(update_fields=['first_response_due_at', 'resolution_due_at', 'updated_at'])


def pause_sla(ticket, *, now=None, save=True):
    """Stamp the start of a pause. No-op if already paused."""
    if ticket.sla_paused_at is not None:
        return False
    ticket.sla_paused_at = now or timezone.now()
    if save:
        ticket.save(update_fields=['sla_paused_at', 'updated_at'])
    return True


def resume_sla(ticket, *, now=None, save=True):
    """Close out a pause and push the due-dates out by its duration.

    Returns the number of minutes credited. No-op if not paused.

    The deadlines move rather than the elapsed time being subtracted at
    comparison time, so a due-date shown in the UI, exported to a report, or
    handed to a workflow rule is the real one and every reader agrees.
    """
    if ticket.sla_paused_at is None:
        return 0
    now = now or timezone.now()
    elapsed = now - ticket.sla_paused_at
    minutes = max(0, int(elapsed.total_seconds() // 60))

    fields = ['sla_paused_at', 'sla_paused_minutes', 'updated_at']
    ticket.sla_paused_minutes = (ticket.sla_paused_minutes or 0) + minutes
    ticket.sla_paused_at = None

    if elapsed.total_seconds() > 0:
        if ticket.first_response_due_at and not ticket.first_response_at:
            ticket.first_response_due_at += elapsed
            fields.append('first_response_due_at')
        if ticket.resolution_due_at and not ticket.resolved_at:
            ticket.resolution_due_at += elapsed
            fields.append('resolution_due_at')

    if save:
        ticket.save(update_fields=fields)
    return minutes


def refresh_breach_flags(ticket, *, now=None, save=True):
    """Persist the live breach computation onto the ticket.

    `sla_breached_response` and `sla_breached_resolution` are what
    `reports.generators.PSASLABreachesReport` filters on and what the
    `sla_breach_count_30d` KPI counts. Nothing ever wrote them, so both
    reported zero breaches however many there had been, while the badge on the
    ticket — computed live by the functions above — said otherwise.

    Clears as well as sets: extending a deadline or reopening a ticket must not
    leave a breach recorded against it.

    But only where there is a deadline to judge against. With no
    `resolution_due_at` the question "did this breach?" has no answer, and
    "no answer" must not be written down as "no". A breach is a historical
    fact; clearing one requires evidence it did not happen, not an absence of
    evidence that it did. So a ticket with no SLA target keeps whatever is
    already recorded — including a flag set by an import, a migration, or an
    integration.

    Returns True when a flag changed.
    """
    now = now or timezone.now()
    changed = False

    if ticket.first_response_due_at:
        response = response_breached(ticket, now=now)
        if ticket.sla_breached_response != response:
            ticket.sla_breached_response = response
            changed = True

    if ticket.resolution_due_at:
        resolution = resolution_breached(ticket, now=now)
        if ticket.sla_breached_resolution != resolution:
            ticket.sla_breached_resolution = resolution
            changed = True

    if changed and save:
        ticket.save(update_fields=['sla_breached_response',
                                   'sla_breached_resolution', 'updated_at'])
    return changed


def is_paused(ticket):
    return bool(ticket.status_id and ticket.status.pauses_sla)


def is_resolved(ticket):
    return bool(ticket.resolved_at) or (ticket.status_id and ticket.status.is_terminal)


def response_breached(ticket, *, now=None):
    """True if the response SLA is breached AND we haven't yet responded."""
    if not ticket.first_response_due_at:
        return False
    if ticket.first_response_at is not None:
        # Already responded — was it on time?
        return ticket.first_response_at > ticket.first_response_due_at
    if is_paused(ticket):
        return False
    return (now or timezone.now()) > ticket.first_response_due_at


def resolution_breached(ticket, *, now=None):
    if not ticket.resolution_due_at:
        return False
    if ticket.resolved_at is not None:
        return ticket.resolved_at > ticket.resolution_due_at
    if is_paused(ticket) or is_resolved(ticket):
        # Paused means clock isn't running; resolved means done.
        return False
    return (now or timezone.now()) > ticket.resolution_due_at


def status_chip(ticket, *, now=None):
    """
    Return a dict for the UI: {kind, label, due_at, minutes_remaining}.
    `kind` ∈ {'breached', 'warning', 'on_track', 'paused', 'resolved', 'no_sla'}.
    Warning threshold = 25% of the resolution window remaining.
    """
    now = now or timezone.now()
    if is_resolved(ticket):
        return {'kind': 'resolved', 'label': 'Resolved'}
    if is_paused(ticket):
        return {'kind': 'paused', 'label': f'Paused ({ticket.status.name})'}
    if not ticket.resolution_due_at:
        return {'kind': 'no_sla', 'label': 'No SLA'}

    if response_breached(ticket, now=now) or resolution_breached(ticket, now=now):
        which = 'response' if response_breached(ticket, now=now) and not ticket.first_response_at else 'resolution'
        return {'kind': 'breached', 'label': f'SLA breached ({which})',
                'due_at': ticket.resolution_due_at}

    # Warning: < 25% of resolution window remaining
    if ticket.resolution_due_at and ticket.created_at:
        total = (ticket.resolution_due_at - ticket.created_at).total_seconds()
        remaining = (ticket.resolution_due_at - now).total_seconds()
        if total > 0 and remaining / total < 0.25:
            mins_left = int(max(0, remaining // 60))
            return {'kind': 'warning', 'label': f'SLA warning — {mins_left} min left',
                    'due_at': ticket.resolution_due_at,
                    'minutes_remaining': mins_left}

    remaining = (ticket.resolution_due_at - now).total_seconds()
    mins_left = int(max(0, remaining // 60))
    return {'kind': 'on_track', 'label': f'On track — {mins_left} min',
            'due_at': ticket.resolution_due_at, 'minutes_remaining': mins_left}


# -- Hygiene flags ----------------------------------------------------------

def hygiene_flags(ticket):
    """Return a list of {key, message} dicts describing hygiene issues
    on this ticket. Used to surface "things to fix before close" hints."""
    flags = []
    if not ticket.assigned_to_id:
        flags.append({'key': 'unassigned', 'message': 'No assignee'})
    if ticket.related_asset_id is None and ticket.organization.assets.exists() if hasattr(ticket.organization, 'assets') else False:
        flags.append({'key': 'no_asset', 'message': 'No asset linked (this client has assets)'})
    if not ticket.time_entries.exists():
        flags.append({'key': 'no_time', 'message': 'No time logged'})
    if ticket.first_response_due_at and not ticket.first_response_at and not is_paused(ticket):
        flags.append({'key': 'no_first_response', 'message': 'No first response yet'})
    return flags


# ---------------------------------------------------------------------------
# Recurring-issue detection (Phase 2c)
# ---------------------------------------------------------------------------

def find_similar_tickets(ticket, *, window_days=90, limit=5):
    """
    Cheap similarity match: same client + same asset (if set) + token
    overlap on subject. Returns list of (ticket, score) tuples sorted by
    score desc. Does not pull pgvector or external services — Phase 4
    can swap in something fancier.
    """
    from datetime import timedelta
    from django.db.models import Q
    from django.utils import timezone as _tz
    from psa.models import Ticket

    cutoff = _tz.now() - timedelta(days=window_days)
    qs = Ticket.objects.filter(
        organization=ticket.organization,
        created_at__gte=cutoff,
    ).exclude(pk=ticket.pk).order_by('-created_at')

    if ticket.related_asset_id:
        # Same-asset hits are strong signals — check those first.
        same_asset = list(qs.filter(related_asset_id=ticket.related_asset_id)[:limit])
    else:
        same_asset = []

    # Token overlap on subject — keep tokens >= 4 chars to drop noise words
    subject_tokens = {t.lower() for t in (ticket.subject or '').split() if len(t) >= 4}
    candidates = list(qs.exclude(pk__in=[t.pk for t in same_asset])[:200])

    scored = []
    for cand in candidates:
        cand_tokens = {t.lower() for t in (cand.subject or '').split() if len(t) >= 4}
        if not cand_tokens or not subject_tokens:
            continue
        overlap = len(subject_tokens & cand_tokens)
        if overlap == 0:
            continue
        # Jaccard-ish score
        score = overlap / float(len(subject_tokens | cand_tokens))
        if score >= 0.3:
            scored.append((cand, round(score, 2)))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    out = [(t, 1.0) for t in same_asset] + scored
    return out[:limit]
