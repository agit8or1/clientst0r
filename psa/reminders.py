"""Ticket reminders (roadmap 52.21): views, My Work feed and the scheduler step.

Reminders are private to their owner and MSP-staff only. Creating one needs a
ticket the user can open (psa.views._scoped_ticket_qs, the ticket page's own
check); every list re-applies that scope, so a reminder on a ticket the owner
lost access to is hidden rather than leaking the subject.
"""
import logging
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.decorators import require_write
from core.safe_redirect import safe_post_next

from .feature_flags import require_psa_enabled
from .models import TicketReminder
from .visibility import is_msp_staff

logger = logging.getLogger('psa.reminders')

NOTE_MAX = 200
PER_TICKET_LIMIT = 25


def reminders_for(user, ticket_qs, *, include_done=False):
    """The user's reminders on tickets in ``ticket_qs`` (a scoped queryset)."""
    qs = (TicketReminder.objects.filter(user=user, ticket__in=ticket_qs.values('pk'))
          .select_related('ticket', 'ticket__organization'))
    if not include_done:
        qs = qs.filter(completed_at__isnull=True)
    return qs


def fire_due(now=None):
    """Mark every due, unfired reminder fired exactly once. Returns the count.

    The conditional UPDATE is the idempotency guard: two overlapping runs
    cannot both claim a row.
    """
    now = now or timezone.now()
    fired = 0
    due = TicketReminder.objects.filter(
        remind_at__lte=now, fired_at__isnull=True, completed_at__isnull=True)
    for pk in list(due.values_list('pk', flat=True)):
        fired += TicketReminder.objects.filter(
            pk=pk, fired_at__isnull=True).update(fired_at=now)
    if fired:
        # The bell caches counts for a minute; the authz generation key is
        # not involved, so nothing to invalidate beyond that short TTL.
        logger.info('fired %d ticket reminder(s)', fired)
    return fired


def _parse_when(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _staff_ticket(request, ticket_number):
    from .views import _scoped_ticket_qs
    if not is_msp_staff(request.user):
        raise Http404('Not found')
    return get_object_or_404(_scoped_ticket_qs(request), ticket_number=ticket_number)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def reminder_create(request, ticket_number):
    ticket = _staff_ticket(request, ticket_number)
    back = redirect(reverse('psa:ticket_detail', kwargs={'ticket_number': ticket.ticket_number}))
    when = _parse_when(request.POST.get('remind_at'))
    if when is None:
        messages.error(request, 'Choose a valid date and time for the reminder.')
        return back
    if TicketReminder.objects.filter(
            ticket=ticket, user=request.user, completed_at__isnull=True).count() >= PER_TICKET_LIMIT:
        messages.error(request, 'Too many open reminders on this ticket. Complete or delete some first.')
        return back
    TicketReminder.objects.create(
        ticket=ticket, user=request.user, remind_at=when,
        note=(request.POST.get('note') or '').strip()[:NOTE_MAX])
    messages.success(request, 'Reminder set.')
    return back


def _own(request, pk):
    # Another user's reminder is a 404, the same as a missing one.
    if not is_msp_staff(request.user):
        raise Http404('Not found')
    return get_object_or_404(TicketReminder, pk=pk, user=request.user)


def _return(request, reminder):
    fallback = reverse('psa:ticket_detail', kwargs={'ticket_number': reminder.ticket.ticket_number})
    return redirect(safe_post_next(request, fallback))


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def reminder_complete(request, pk):
    reminder = _own(request, pk)
    if reminder.completed_at is None:
        reminder.completed_at = timezone.now()
        reminder.save(update_fields=['completed_at'])
    return _return(request, reminder)


@login_required
@require_write
@require_psa_enabled
@require_http_methods(['POST'])
def reminder_delete(request, pk):
    reminder = _own(request, pk)
    back = _return(request, reminder)
    reminder.delete()
    return back
