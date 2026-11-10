"""The only code that changes anything for routing.

Writes are limited to: RoutingDecision rows (history), RoundRobinPointer
counters, and — in Automatic mode or when a dispatcher accepts a suggestion —
a ticket's `assigned_to`, `queue` and `assigned_team`. Never the customer,
never SLA columns, never memberships, access grants, remote sessions or
endpoint actions.

Concurrency: each routing pass runs in one transaction that starts by
inserting its RoutingDecision claim. `(ticket, idempotency_key)` is unique, so
a repeated trigger finds the claim and stops. The insert is the first
statement, so on SQLite it takes the write lock before anything is read; on
MariaDB/Postgres the ticket row is then locked with select_for_update and the
round-robin counter is advanced with an UPDATE (row lock) before it is read.
"""
from __future__ import annotations

import logging
import threading
import uuid

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import engine
from .models import (
    MODE_AUTO, MODE_OFF, MODE_SUGGEST, STATUS_ACCEPTED, STATUS_APPLIED, STATUS_FALLBACK,
    STATUS_OVERRIDE, STATUS_REJECTED, STATUS_SKIPPED, STATUS_SUGGESTED, STATUS_SUPERSEDED,
    TRIGGER_CREATED, TRIGGER_MANUAL, TRIGGER_REOPEN, TRIGGER_REPLY, TRIGGER_SLA,
    RoundRobinPointer, RoutingDecision, RoutingSettings,
)

logger = logging.getLogger('psa.routing')

_local = threading.local()

ROUTED_STATUSES = (STATUS_APPLIED, STATUS_FALLBACK, STATUS_ACCEPTED)


class _Applying:
    """Marks saves made by routing so the manual-override detector ignores them."""

    def __enter__(self):
        _local.depth = getattr(_local, 'depth', 0) + 1

    def __exit__(self, *exc):
        _local.depth -= 1
        return False


def is_applying() -> bool:
    return getattr(_local, 'depth', 0) > 0


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

def schedule(ticket_id, trigger, key):
    """Route after the surrounding transaction commits (immediately when there
    is none). Intake that rolls back never routes, and errors never reach
    the intake path."""
    transaction.on_commit(lambda: route_safely(ticket_id, trigger, key), robust=True)


def route_safely(ticket_id, trigger, key, **kw):
    try:
        return route(ticket_id, trigger, key, **kw)
    except Exception:  # noqa: BLE001 — routing must never break intake
        logger.exception('ticket routing failed for ticket %s (%s)', ticket_id, trigger)
        return None


def _mode_for(ticket, msp):
    return engine.effective_mode(ticket.organization, msp=msp)[0]


def on_ticket_created(ticket):
    schedule(ticket.pk, TRIGGER_CREATED, 'created')


def on_customer_reply(ticket):
    """Called by psa.my_work.record_customer_reply (portal + email replies)."""
    msp = RoutingSettings.load()
    if not msp.reroute_on_reply or _mode_for(ticket, msp) == MODE_OFF:
        return
    stamp = (ticket.last_client_response_at or timezone.now()).isoformat()
    schedule(ticket.pk, TRIGGER_REPLY, f'reply:{stamp}')


def on_reopened(ticket):
    msp = RoutingSettings.load()
    if not msp.reroute_on_reopen or _mode_for(ticket, msp) == MODE_OFF:
        return
    schedule(ticket.pk, TRIGGER_REOPEN, f'reopen:{timezone.now().isoformat()}')


def on_sla_tick(ticket):
    """Called by psa_sla_workflow_tick for open tickets. Once per ticket per
    threshold value (the idempotency key carries the threshold)."""
    msp = RoutingSettings.load()
    if not msp.reroute_on_sla or _mode_for(ticket, msp) == MODE_OFF:
        return None
    from psa.workflow_engine import _sla_pct_elapsed
    if _sla_pct_elapsed(ticket) < msp.sla_reroute_pct:
        return None
    key = f'sla:{msp.sla_reroute_pct}'
    if RoutingDecision.objects.filter(ticket_id=ticket.pk, idempotency_key=key).exists():
        return None
    return route_safely(ticket.pk, TRIGGER_SLA, key)


# ---------------------------------------------------------------------------
# Routing pass
# ---------------------------------------------------------------------------

def reserve_round_robin(key) -> int:
    """Advance the counter and return the turn this caller owns (0-based)."""
    RoundRobinPointer.objects.get_or_create(key=key)
    RoundRobinPointer.objects.filter(key=key).update(counter=F('counter') + 1,
                                                     updated_at=timezone.now())
    return int(RoundRobinPointer.objects.filter(key=key).values_list('counter', flat=True).get()) - 1


def last_routed_assignee_id(ticket_id):
    d = (RoutingDecision.objects.filter(ticket_id=ticket_id, status__in=ROUTED_STATUSES)
         .order_by('-created_at', '-pk').first())
    return d.new_assignee_id if d else None


def _hold_reason(ticket, trigger, msp):
    if trigger == TRIGGER_CREATED:
        if ticket.assigned_to_id:
            return (f'Already assigned to {ticket.assigned_to.get_username()} at intake '
                    '(by a person, a catalog default or a workflow rule); routing leaves it.')
        return ''
    if ticket.status_id and ticket.status.is_terminal:
        return 'The ticket is closed.'
    reroutes = (RoutingDecision.objects.filter(ticket_id=ticket.pk, status__in=ROUTED_STATUSES)
                .exclude(trigger=TRIGGER_CREATED).count())
    if reroutes >= msp.max_reroutes:
        return f'Loop guard: already rerouted {reroutes} times (limit {msp.max_reroutes}).'
    if ticket.assigned_to_id and msp.preserve_manual_assignment:
        if last_routed_assignee_id(ticket.pk) != ticket.assigned_to_id:
            return (f'Kept the assignment to {ticket.assigned_to.get_username()}: it was made by a '
                    'person, and manual assignments are preserved.')
    return ''


def route(ticket_id, trigger, key, *, now=None):
    """One routing pass. Returns the RoutingDecision, or None when routing is
    off or this trigger was already handled."""
    from psa.models import Ticket
    msp = RoutingSettings.load()
    head = Ticket.objects.select_related('organization').filter(pk=ticket_id).first()
    if head is None:
        return None
    mode = _mode_for(head, msp)
    if mode == MODE_OFF:
        return None

    with transaction.atomic():
        try:
            with transaction.atomic():
                decision = RoutingDecision.objects.create(
                    ticket_id=ticket_id, trigger=trigger,
                    idempotency_key=str(key)[:191], mode=mode)
        except IntegrityError:
            return None  # already handled (duplicate delivery / concurrent worker)

        ticket = (Ticket.objects.select_for_update()
                  .select_related('organization', 'status', 'priority', 'queue',
                                  'ticket_type', 'assigned_to')
                  .get(pk=ticket_id))
        decision.previous_assignee_id = ticket.assigned_to_id
        decision.previous_queue_id = ticket.queue_id
        decision.previous_team = ticket.assigned_team or ''

        hold = _hold_reason(ticket, trigger, msp)
        if hold:
            return _finish(decision, STATUS_SKIPPED, hold, keep=True)

        ev = engine.evaluate(ticket, now=now, msp=msp)
        decision.rule = ev.rule
        decision.rule_version = ev.version
        decision.destination_type = ev.destination_type
        decision.skipped_candidates = ev.skipped[:100]
        decision.round_robin_key = ev.round_robin_key

        if not ev.verified:
            return _finish(decision, STATUS_FALLBACK, ev.reason, keep=True)
        if not ev.matched:
            return _finish(decision, STATUS_SKIPPED, ev.reason, keep=True)

        if (trigger != TRIGGER_CREATED and ticket.assigned_to_id and ev.assignee is not None
                and any(u.pk == ticket.assigned_to_id for u in ev.eligible)):
            return _finish(decision, STATUS_SKIPPED,
                           f'{ev.reason} The current assignee still qualifies, so it stays.', keep=True)

        assignee, reason = ev.assignee, ev.reason
        if mode == MODE_AUTO and ev.round_robin_key and ev.eligible:
            turn = reserve_round_robin(ev.round_robin_key)
            assignee, how = engine.choose(ev.destination_type, ev.eligible, turn)
            reason = f'Rule "{ev.version.name}" v{ev.version.number}: {assignee.get_username()} ({how}).'

        decision.new_assignee = assignee
        decision.new_queue_id = (ev.queue.pk if ev.queue is not None else ticket.queue_id)
        decision.new_team = ev.team or (ticket.assigned_team or '')
        status_done = STATUS_FALLBACK if ev.used_fallback else STATUS_APPLIED

        if not decision.changes_something:
            return _finish(decision, status_done if ev.used_fallback else STATUS_SKIPPED,
                           f'{reason} Already there; nothing to change.')

        if mode == MODE_SUGGEST:
            (RoutingDecision.objects.filter(ticket_id=ticket_id, status=STATUS_SUGGESTED)
             .update(status=STATUS_SUPERSEDED))
            return _finish(decision, STATUS_SUGGESTED, f'Suggested: {reason}')

        _apply(ticket, decision)
        return _finish(decision, status_done, reason)


def _finish(decision, status, reason, keep=False):
    decision.status = status
    decision.reason = reason[:4000]
    if keep:
        decision.new_assignee_id = decision.previous_assignee_id
        decision.new_queue_id = decision.previous_queue_id
        decision.new_team = decision.previous_team
    decision.save()
    return decision


def _apply(ticket, decision):
    """Write the decision onto the ticket: assignee, queue, team — nothing else."""
    ticket.assigned_to_id = decision.new_assignee_id
    ticket.queue_id = decision.new_queue_id or ticket.queue_id
    ticket.assigned_team = (decision.new_team or '')[:100]
    # Not saved: keeps the assignment e-mail from being mistaken for a
    # self-assignment by whoever last edited the ticket.
    ticket.updated_by = None
    with _Applying():
        ticket.save(update_fields=['assigned_to', 'queue', 'assigned_team', 'updated_at'])


# ---------------------------------------------------------------------------
# Dispatcher actions
# ---------------------------------------------------------------------------

def accept_suggestion(decision_id, user):
    """Apply a suggestion. Returns (decision, message)."""
    from psa.models import Ticket
    with transaction.atomic():
        d = RoutingDecision.objects.select_for_update().get(pk=decision_id)
        if d.status != STATUS_SUGGESTED:
            return d, 'This suggestion was already decided.'
        ticket = (Ticket.objects.select_for_update().select_related('organization')
                  .get(pk=d.ticket_id))
        d.decided_by, d.decided_at = user, timezone.now()
        if (ticket.assigned_to_id != d.previous_assignee_id
                or ticket.queue_id != d.previous_queue_id):
            d.status = STATUS_SUPERSEDED
            d.reason = (d.reason + ' Not applied: the ticket changed after the suggestion.')[:4000]
            d.save()
            return d, 'The ticket changed since this was suggested; nothing was applied.'
        if d.new_assignee_id:
            cust = engine.customer_settings(ticket.organization)
            authorized = set()
            if cust is not None and cust.restrict_technicians:
                authorized = set(cust.authorized_technicians.values_list('pk', flat=True))
            problem = engine._authorization_problem(d.new_assignee, ticket.organization, cust, authorized)
            if problem:
                d.status = STATUS_SUPERSEDED
                d.reason = (d.reason + f' Not applied: {d.new_assignee.get_username()} is {problem}.')[:4000]
                d.save()
                return d, f'{d.new_assignee.get_username()} can no longer take this ticket; nothing was applied.'
        if d.round_robin_key:
            reserve_round_robin(d.round_robin_key)
        _apply(ticket, d)
        d.status = STATUS_ACCEPTED
        d.save()
        return d, 'Suggestion applied.'


def reject_suggestion(decision_id, user):
    with transaction.atomic():
        d = RoutingDecision.objects.select_for_update().get(pk=decision_id)
        if d.status != STATUS_SUGGESTED:
            return d, 'This suggestion was already decided.'
        d.status, d.decided_by, d.decided_at = STATUS_REJECTED, user, timezone.now()
        d.save()
        return d, 'Suggestion dismissed.'


def record_manual_override(ticket, previous_assignee_id, actor=None):
    """A person changed the assignee of a ticket routing has handled. Logged in
    the staff-only history; open suggestions for the ticket are superseded."""
    if not RoutingDecision.objects.filter(ticket_id=ticket.pk).exclude(status=STATUS_OVERRIDE).exists():
        return None
    (RoutingDecision.objects.filter(ticket_id=ticket.pk, status=STATUS_SUGGESTED)
     .update(status=STATUS_SUPERSEDED))
    from django.contrib.auth import get_user_model
    prev = get_user_model().objects.filter(pk=previous_assignee_id).first() if previous_assignee_id else None
    new = ticket.assigned_to if ticket.assigned_to_id else None
    who = actor.get_username() if actor is not None else 'someone'
    return RoutingDecision.objects.create(
        ticket=ticket, trigger=TRIGGER_MANUAL, idempotency_key=f'manual:{uuid.uuid4().hex}',
        status=STATUS_OVERRIDE, previous_assignee=prev, new_assignee=new,
        previous_queue_id=ticket.queue_id, new_queue_id=ticket.queue_id,
        previous_team=ticket.assigned_team or '', new_team=ticket.assigned_team or '',
        decided_by=actor, decided_at=timezone.now(),
        reason=(f'Manual assignment by {who}: '
                f'{prev.get_username() if prev else "unassigned"} → '
                f'{new.get_username() if new else "unassigned"}. Routing will keep it.'),
    )
