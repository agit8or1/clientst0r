"""Customer follow-up and confirm-or-close (roadmap 52.24).

A ticket sitting in a waiting-on-customer status gets a follow-up email after
N days, an optional second reminder, and is closed after M days of silence
with the reason recorded on the timeline and in the audit log.

Safety properties
-----------------
* Off by default (``FollowUpPolicy.enabled``); a customer can be forced on or
  off with ``ClientPSASettings.followup_override``.
* Day counts run from ``wait_since``: when the ticket entered its waiting
  status, or the customer's last reply if later. Each stage is stamped on the
  ticket for that waiting period (``followup_*_at``), so it happens once; a
  new period resets the stamps.
* Overlapping scheduler runs: a stage is claimed with a conditional UPDATE
  before anything is sent; the loser of the race sends nothing.
* Never messages a ticket without a requester address, whose requester is an
  MSP staff user, or whose requester has turned email notifications off.
* Runs from ``psa_sla_workflow_tick`` (every few minutes), bounded per run.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('psa.followup')

BATCH_LIMIT = 200


# ---------------------------------------------------------------------------
# Time arithmetic
# ---------------------------------------------------------------------------

def add_days(start, days, business=False):
    """``start`` plus ``days`` calendar days, or weekdays when ``business``."""
    if not business:
        return start + timedelta(days=days)
    cur, left = start, days
    while left > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            left -= 1
    return cur


def wait_since(ticket):
    """Start of the current waiting-on-customer period, or None."""
    base = ticket.sla_paused_at or ticket.updated_at
    reply = ticket.last_client_response_at
    if reply and base and reply > base:
        return reply
    return base


# ---------------------------------------------------------------------------
# Policy and eligibility
# ---------------------------------------------------------------------------

def effective_enabled(policy, override):
    from .models import ClientPSASettings as C
    if override == C.FOLLOWUP_ON:
        return True
    if override == C.FOLLOWUP_OFF:
        return False
    return policy.enabled


def _override_for(org_id):
    from .models import ClientPSASettings
    return (ClientPSASettings.objects.filter(organization_id=org_id)
            .values_list('followup_override', flat=True).first()
            or ClientPSASettings.FOLLOWUP_INHERIT)


def ticket_in_cycle(ticket, policy=None):
    """True when the follow-up cycle applies to this ticket right now."""
    from .my_work import is_customer_wait_status
    policy = policy or _policy()
    if ticket.closed_at is not None or not ticket.status_id or ticket.status.is_terminal:
        return False
    if not is_customer_wait_status(ticket.status):
        return False
    from .models import ClientPSASettings
    if ClientPSASettings.objects.filter(
            organization_id=ticket.organization_id, enabled=False).exists():
        return False  # customer opted out of the PSA: never message them
    return effective_enabled(policy, _override_for(ticket.organization_id))


def _policy():
    from .models import FollowUpPolicy
    return FollowUpPolicy.get()


def schedule_for(ticket, policy=None):
    """Staff-facing view of the cycle: None when the ticket is not in it, else
    a dict of the next follow-up / close dates and whether it is paused."""
    policy = policy or _policy()
    if not ticket_in_cycle(ticket, policy):
        return None
    ws = wait_since(ticket)
    if ws is None:
        return None
    biz = policy.business_days
    first_due = ticket.followup_first_at or add_days(ws, policy.first_after_days, biz)
    second_due = None
    if policy.second_after_days:
        second_due = ticket.followup_second_at or add_days(first_due, policy.second_after_days, biz)
    close_due = add_days(ws, policy.close_after_days, biz) if policy.close_after_days else None
    return {
        'paused': ticket.followup_paused,
        'first_due': first_due, 'first_sent': ticket.followup_first_at is not None,
        'second_due': second_due, 'second_sent': ticket.followup_second_at is not None,
        'close_due': close_due,
    }


def _requester_recipients(ticket):
    """(to, cc) for a customer message, or None when nobody may be messaged."""
    from django.contrib.auth import get_user_model
    from .visibility import is_msp_staff
    User = get_user_model()

    def allowed(addr):
        users = list(User.objects.filter(email__iexact=addr, is_active=True)[:5])
        if any(is_msp_staff(u) for u in users):
            return False
        for u in users:
            prof = getattr(u, 'profile', None)
            if prof is not None and prof.email_notifications is False:
                return False
        return True

    to = (ticket.requester_email or '').strip()
    if not to or not allowed(to):
        return None
    cc = []
    for addr in (ticket.cc_emails or []):
        addr = (addr or '').strip()
        if addr and addr.lower() != to.lower() and allowed(addr) and addr not in cc:
            cc.append(addr)
    return to, cc


class _SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def render(template, ticket, policy, days):
    values = _SafeDict(ticket_number=ticket.ticket_number, subject=ticket.subject,
                       requester=ticket.requester_name or ticket.requester_email,
                       days=days, close_days=policy.close_after_days)
    try:
        return (template or '').format_map(values)
    except (ValueError, IndexError, KeyError, AttributeError):
        return template or ''


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def _claim(ticket, field, now, ws):
    """Stamp ``field`` once for this waiting period. True if this run won."""
    from .models import Ticket
    return Ticket.objects.filter(
        pk=ticket.pk, followup_paused=False, followup_wait_since=ws,
        **{f'{field}__isnull': True},
    ).update(**{field: now}) == 1


def _release(ticket, field):
    from .models import Ticket
    Ticket.objects.filter(pk=ticket.pk).update(**{field: None})


def _send(ticket, policy, field, now, body_template, label):
    from .email_outbound import resolve_ticket_email_config, send_ticket_reply
    from .models import TicketComment
    recipients = _requester_recipients(ticket)
    if recipients is None:
        return False
    to, cc = recipients
    ws = ticket.followup_wait_since
    if not _claim(ticket, field, now, ws):
        return False
    days = max(0, (now - ws).days)
    body = render(body_template, ticket, policy, days)
    comment = TicketComment.objects.create(
        ticket=ticket, body=body, is_internal=False, is_system=True,
        source='followup', author_name='Automatic follow-up')
    try:
        send_ticket_reply(ticket=ticket, config=resolve_ticket_email_config(ticket),
                          comment=comment, body_text=body, to_emails=[to],
                          cc_emails=cc or None)
    except Exception as exc:  # noqa: BLE001 - retried next tick
        logger.warning('follow-up email failed ticket=%s: %s', ticket.ticket_number, exc)
        comment.delete()
        _release(ticket, field)
        return False
    _audit(ticket, f'Customer follow-up sent ({label})',
           {'event': 'followup_sent', 'stage': label, 'to': to, 'cc': cc})
    return True


def _audit(ticket, description, extra):
    from audit.models import AuditLog
    AuditLog.log(
        user=None, action='update', organization=ticket.organization,
        object_type='psa.Ticket', object_id=ticket.pk,
        object_repr=f'{ticket.ticket_number} customer follow-up'[:255],
        description=f'{description} on {ticket.ticket_number}', extra_data=extra)


def closing_status(policy):
    from .models import TicketStatus
    if policy.closing_status_id and policy.closing_status.is_terminal:
        return policy.closing_status
    return (TicketStatus.objects.filter(slug='closed').first()
            or TicketStatus.objects.filter(is_terminal=True).order_by('sort_order', 'id').first())


def _close(ticket, policy, now, ws):
    from django.core.exceptions import ValidationError
    from .models import Ticket, TicketComment
    target = closing_status(policy)
    if target is None:
        return False
    days = max(1, (now - ws).days)
    reason = f'Closed after {days} days without a reply from the customer'
    with transaction.atomic():
        fresh = (Ticket.objects.select_for_update().select_related('status')
                 .filter(pk=ticket.pk).first())
        if (fresh is None or fresh.closed_at is not None or fresh.status.is_terminal
                or fresh.followup_paused or fresh.followup_wait_since != ws
                or fresh.status_id != ticket.status_id):
            return False
        prev = fresh.status.name
        fresh.status = target
        fresh.closure_category = 'no_action'
        fresh.resolution_summary = reason
        fresh.resolved_at = fresh.resolved_at or now
        fields = ['status', 'closure_category', 'resolution_summary', 'resolved_at', 'updated_at']
        if 'close' in target.slug:
            fresh.closed_at = now
            fields.append('closed_at')
        try:
            fresh.save(update_fields=fields)
        except ValidationError as exc:
            logger.warning('auto-close refused ticket=%s: %s', fresh.ticket_number, exc.messages)
            return False
        TicketComment.objects.create(
            ticket=fresh, body=f'{reason}. Status changed: {prev} → {target.name}',
            is_internal=True, is_system=True, source='followup')
        # The customer-visible closure notice.
        body = render(policy.closure_message, fresh, policy, days)
        TicketComment.objects.create(
            ticket=fresh, body=body or reason, is_internal=False, is_system=True,
            source='followup', author_name='Automatic follow-up')
        _audit(fresh, reason, {'event': 'followup_closed', 'from': prev,
                               'to': target.name, 'days': days})
    # Tell the customer too (best effort; the ticket is already closed).
    recipients = _requester_recipients(fresh)
    if recipients and body:
        from .email_outbound import resolve_ticket_email_config, send_ticket_reply
        try:
            send_ticket_reply(ticket=fresh, config=resolve_ticket_email_config(fresh),
                              body_text=body, to_emails=[recipients[0]],
                              cc_emails=recipients[1] or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning('closure email failed ticket=%s: %s', fresh.ticket_number, exc)
    return True


def _sync_period(ticket, ws):
    """Reset the stage stamps when a new waiting period has begun."""
    from .models import Ticket
    if ticket.followup_wait_since == ws:
        return
    Ticket.objects.filter(pk=ticket.pk, followup_wait_since=ticket.followup_wait_since).update(
        followup_wait_since=ws, followup_first_at=None, followup_second_at=None)
    ticket.refresh_from_db(fields=['followup_wait_since', 'followup_first_at',
                                   'followup_second_at'])


def process_ticket(ticket, policy, now):
    """Advance one ticket. Returns 'followup' / 'reminder' / 'closed' / None."""
    ws = wait_since(ticket)
    if ws is None or ticket.followup_paused:
        return None
    _sync_period(ticket, ws)
    if ticket.followup_wait_since != ws:  # lost a race with another run
        return None
    biz = policy.business_days

    if ticket.followup_first_at is None:
        if now >= add_days(ws, policy.first_after_days, biz):
            return 'followup' if _send(ticket, policy, 'followup_first_at', now,
                                       policy.followup_message, 'first') else None
        return None
    if policy.close_after_days and now >= add_days(ws, policy.close_after_days, biz):
        return 'closed' if _close(ticket, policy, now, ws) else None
    if (policy.second_after_days and ticket.followup_second_at is None
            and now >= add_days(ticket.followup_first_at, policy.second_after_days, biz)):
        return 'reminder' if _send(ticket, policy, 'followup_second_at', now,
                                   policy.followup_message, 'second') else None
    return None


def run(now=None, limit=BATCH_LIMIT):
    """One scheduler pass. Returns a dict of counts."""
    from .models import ClientPSASettings, Ticket
    from .my_work import customer_wait_status_q, open_q
    now = now or timezone.now()
    policy = _policy()
    stats = {'followup': 0, 'reminder': 0, 'closed': 0}
    off = list(ClientPSASettings.objects.filter(
        followup_override=ClientPSASettings.FOLLOWUP_OFF).values_list('organization_id', flat=True))
    off += list(ClientPSASettings.objects.filter(
        enabled=False).values_list('organization_id', flat=True))
    on = list(ClientPSASettings.objects.filter(
        followup_override=ClientPSASettings.FOLLOWUP_ON, enabled=True
    ).values_list('organization_id', flat=True))
    if not policy.enabled and not on:
        return stats
    qs = Ticket.objects.filter(open_q(), customer_wait_status_q(), followup_paused=False)
    if not policy.enabled:
        qs = qs.filter(organization_id__in=on)
    if off:
        qs = qs.exclude(organization_id__in=off)
    earliest = now - timedelta(days=max(0, policy.first_after_days))
    qs = (qs.filter(sla_paused_at__lte=earliest)
          .select_related('status', 'organization')
          .order_by('sla_paused_at', 'pk')[:limit])
    for ticket in qs:
        try:
            result = process_ticket(ticket, policy, now)
        except Exception:  # noqa: BLE001 - one bad ticket never stops the batch
            logger.exception('follow-up failed ticket=%s', ticket.ticket_number)
            continue
        if result:
            stats[result] += 1
    return stats
