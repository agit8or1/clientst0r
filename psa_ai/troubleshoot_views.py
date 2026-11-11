"""
AI Troubleshoot (OPTIONAL AI, gated by psa_ai_enabled; services/troubleshoot.py).

  POST /psa/ai/troubleshoot/ticket/<ticket_number>/   start on a ticket
  POST /psa/ai/troubleshoot/device/<device_id>/       start on an RMM device
  GET  /psa/ai/troubleshoot/<uuid>/                   the session (HTML; ?format=json for JSON)
  GET  /psa/ai/troubleshoot/<uuid>/action/<ref>/      confirm a suggested action
  POST /psa/ai/troubleshoot/<uuid>/action/<ref>/      request it through the normal flow

With AI off every route answers 404. Tickets resolve through the same scoped
queryset as the ticket page and technician access is re-checked with the
ticket, so another customer's ticket or device gets 404 like one that
doesn't exist. Nothing here runs anything, calls an RMM directly, or posts
to the ticket; "Request" hands the action to rmm_actions, which sends it to
the paired RMM for its own approval.
"""
from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core.ai_gate import ai_features_enabled

from .models import TroubleshootSession
from .services import troubleshoot


def _gate(request):
    from tech_access.resolver import is_technician
    if not ai_features_enabled() or not is_technician(request.user):
        raise Http404()


def _wants_json(request):
    return request.GET.get('format') == 'json' or 'application/json' in request.headers.get('Accept', '')


def _ticket(request, ticket_number):
    from psa.views import _scoped_ticket_qs
    from psa_ai.permissions import has_capability
    ticket = get_object_or_404(_scoped_ticket_qs(request).select_related('related_asset', 'organization'),
                               ticket_number=ticket_number)
    if not has_capability(request.user, ticket.organization, 'view_output', ticket=ticket):
        raise Http404()
    return ticket


def _device(request, device_id):
    from integrations.models import RMMDevice
    device = get_object_or_404(RMMDevice.objects.select_related('organization', 'connection', 'linked_asset'),
                               pk=device_id)
    if not troubleshoot.device_visible(request.user, device):
        raise Http404()
    return device


def _session(request, session_id):
    s = get_object_or_404(TroubleshootSession.objects.select_related('organization', 'ticket', 'device', 'actor'),
                          pk=session_id)
    if s.ticket_id:
        from psa.views import _scoped_ticket_qs
        if not _scoped_ticket_qs(request).filter(pk=s.ticket_id, organization_id=s.organization_id).exists():
            raise Http404()
    if not troubleshoot.visible(request.user, s):
        raise Http404()
    return s


def _start(request, *, ticket=None, device=None):
    multi = request.POST.get('multi') in ('1', 'true', 'on')
    key = request.POST.get('idempotency_key') or ''
    try:
        session, _ = troubleshoot.start(request.user, ticket=ticket, device=device, multi=multi, key=key,
                                        request=request)
    except troubleshoot.Refused as e:
        if _wants_json(request):
            return JsonResponse({'ok': False, 'error': e.message}, status=e.status)
        messages.error(request, f'AI Troubleshoot: {e.message}')
        back = request.POST.get('next') or ''
        if back.startswith('/') and not back.startswith('//'):
            return redirect(back)
        if ticket is not None:
            return redirect(reverse('psa:ticket_detail', args=[ticket.ticket_number]))
        return redirect(reverse('integrations:rmm_device_detail', args=[device.pk]))
    url = reverse('psa_ai:troubleshoot_session', args=[session.id])
    if _wants_json(request):
        return JsonResponse({'ok': True, 'session_id': str(session.id), 'status': session.status, 'url': url})
    return redirect(url)


@login_required
@require_POST
def start_ticket(request, ticket_number):
    _gate(request)
    return _start(request, ticket=_ticket(request, ticket_number))


@login_required
@require_POST
def start_device(request, device_id):
    _gate(request)
    return _start(request, device=_device(request, device_id))


def _json_view(data):
    s = data['session']

    def when(dt):
        return dt.isoformat() if dt else None
    return {
        'session_id': str(s.id), 'status': s.status, 'status_label': s.get_status_display(),
        'terminal': data['terminal'], 'mode': s.mode, 'error': s.error,
        'subject': (s.observations or {}).get('subject'),
        'layers': {
            'observations': data['observations'],
            'inferences': data['runs'],
            'technician_actions': [{'ref': r['ref'], 'label': r['label'], 'status': r['status'],
                                    'requested_at': when(r['at']),
                                    'requested_by': r['by'].get_username() if r['by'] else '',
                                    'approval_url': r['approval_url']} for r in data['requested']],
            'verified_results': [dict(r['verified'], ref=r['ref'], at=when(r['verified']['at']))
                                 for r in data['requested'] if r['verified']],
        },
        'comparison': data['comparison'], 'sharing': data['sharing'], 'excluded': data['excluded'],
        'redactions': data['redactions'],
        'notice': 'AI output is advisory. Nothing was executed; suggested actions open the normal request flow.',
    }


@login_required
@require_http_methods(['GET'])
def session_detail(request, session_id):
    _gate(request)
    s = _session(request, session_id)
    troubleshoot.expire_stale()
    s.refresh_from_db()
    data = troubleshoot.view(s, request.user)
    if _wants_json(request):
        return JsonResponse(_json_view(data))
    return render(request, 'psa_ai/troubleshoot_session.html', dict(data, key=uuid.uuid4().hex))


@login_required
@require_http_methods(['GET', 'POST'])
def request_action(request, session_id, ref):
    _gate(request)
    s = _session(request, session_id)
    action = next((a for a in (s.observations or {}).get('actions') or [] if a['id'] == ref), None)
    if action is None:
        raise Http404()
    back = reverse('psa_ai:troubleshoot_session', args=[s.id])
    if request.method == 'POST':
        try:
            req, repeat = troubleshoot.request_action(request.user, s, ref, request.POST.get('idempotency_key', ''),
                                                      description=request.POST.get('description', ''),
                                                      request=request)
        except troubleshoot.Refused as e:
            messages.error(request, e.message)
            return redirect(back)
        if repeat:
            messages.info(request, 'That request was already made.')
        else:
            messages.success(request, f'Requested: {action["label"]}. Status: {req.get_status_display()}. The RMM '
                                      'decides whether it is approved and run.')
        return redirect(back)
    ok, reason = troubleshoot.current_actions(request.user, s).get(ref, (False, ''))
    why = ''
    for r in s.runs.filter(status='succeeded').select_related('profile'):
        for x in (r.result or {}).get('recommended_actions') or []:
            if x.get('id') == ref and x.get('why'):
                why = f'{r.profile.name}: {x["why"]}'
                break
    return render(request, 'psa_ai/troubleshoot_action_confirm.html', {
        'session': s, 'action': action, 'ok': ok, 'reason': reason, 'why': why, 'key': uuid.uuid4().hex,
        'back': back,
    })
