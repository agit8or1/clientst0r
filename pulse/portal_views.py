"""Customer-facing pulse check pages, mounted in the portal namespace
(portal/urls.py), so they are on the portal surface.

  * Feedback page (signed in): the portal user's own pulse checks at the
    active customer, and their opt-out switch.
  * Answer (signed in): one of the user's own responses at the active
    customer. Anyone else's response is a 404.
  * Link (no sign-in): the e-mailed token opens exactly one response, until
    the send's deadline, and can be answered once.
  * Opt-out (no sign-in): a signed link naming one e-mail address.

Every page is a 404 while pulse checks are turned off.
"""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from audit.models import AuditLog
from core.client_ip import get_client_ip
from portal.views import portal_required

from .models import PulseOptOut, PulseResponse
from .results import parse_answers
from .sending import opt_out_email, opt_out_token, pulse_enabled


def pulse_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not pulse_enabled():
            raise Http404('Pulse checks are turned off.')
        return view(request, *args, **kwargs)
    return wrapped


def _answer(request, response, *, via, template, extra=None):
    """Shared GET/POST handling for one response."""
    ctx = {'response': response, 'send': response.send, 'questions': response.send.questions,
           'organization': response.organization, 'posted': {}, 'errors': []}
    ctx.update(extra or {})
    if response.is_answered:
        return render(request, template, dict(ctx, state='answered'))
    if response.is_expired:
        return render(request, template, dict(ctx, state='expired'), status=410)
    if request.method == 'POST':
        answers, errors = parse_answers(response.send.questions, request.POST)
        if errors:
            return render(request, template, dict(ctx, state='open', errors=errors,
                                                  posted=request.POST), status=400)
        # Single use: only an unanswered row is updated, so a second submit
        # racing the first changes nothing.
        updated = PulseResponse.objects.filter(pk=response.pk, responded_at__isnull=True).update(
            answers=answers, responded_at=timezone.now(), responded_via=via,
            responded_ip=get_client_ip(request))
        if not updated:
            response.refresh_from_db()
            return render(request, template, dict(ctx, state='answered'))
        return render(request, template, dict(ctx, state='thanks'))
    return render(request, template, dict(ctx, state='open'))


@pulse_required
@require_http_methods(['GET', 'POST'])
@ratelimit(key='ip', rate='60/h', method='POST', block=True)
def respond(request, token):
    response = PulseResponse.lookup(token)
    if response is None:
        return render(request, 'pulse/portal_invalid.html', status=404)
    unsub = opt_out_token(response.email)
    return _answer(request, response, via=PulseResponse.VIA_LINK, template='pulse/respond_public.html',
                   extra={'opt_out_token': unsub})


@pulse_required
@portal_required
def feedback(request):
    org = request.portal_membership.organization
    mine = (PulseResponse.objects.filter(user=request.user, organization=org)
            .select_related('send', 'send__pulse_check').order_by('-send__created_at'))
    now = timezone.now()
    email = (request.user.email or '').strip()
    if request.method == 'POST' and email:
        on = request.POST.get('receive') == 'on'
        if on:
            PulseOptOut.opt_in(email)
        else:
            PulseOptOut.opt_out(email, via='portal')
        AuditLog.log(user=request.user, action='update', organization=org,
                     object_type='pulse.PulseOptOut', object_repr=email.lower(),
                     description=f'{email.lower()} turned pulse check e-mails {"on" if on else "off"} in the portal',
                     path=request.path, extra_data={'event': 'pulse_opt_out', 'on': on})
        messages.success(request, 'Preference saved.')
        return redirect('portal:pulse_feedback')
    open_rows = [r for r in mine if not r.responded_at and r.send.expires_at > now]
    past_rows = [r for r in mine if r.responded_at or r.send.expires_at <= now]
    return render(request, 'pulse/portal_feedback.html', {
        'organization': org, 'open_rows': open_rows, 'past_rows': past_rows[:20],
        'receiving': not PulseOptOut.is_opted_out(email), 'has_email': bool(email),
    })


@pulse_required
@portal_required
@require_http_methods(['GET', 'POST'])
def answer(request, pk):
    response = get_object_or_404(
        PulseResponse.objects.select_related('send', 'organization'),
        pk=pk, user=request.user, organization=request.portal_membership.organization)
    return _answer(request, response, via=PulseResponse.VIA_PORTAL, template='pulse/portal_answer.html')


@pulse_required
@require_http_methods(['GET', 'POST'])
def opt_out(request, token):
    email = opt_out_email(token)
    if not email:
        return render(request, 'pulse/opt_out.html', {'invalid': True}, status=404)
    if request.method == 'POST':
        PulseOptOut.opt_out(email, via='link')
        AuditLog.log(user=None, action='update', object_type='pulse.PulseOptOut', object_repr=email,
                     description=f'{email} opted out of pulse checks from an e-mail link',
                     ip_address=get_client_ip(request), path=request.path,
                     extra_data={'event': 'pulse_opt_out', 'on': False})
        return render(request, 'pulse/opt_out.html', {'done': True, 'email': email})
    return render(request, 'pulse/opt_out.html', {'email': email})
