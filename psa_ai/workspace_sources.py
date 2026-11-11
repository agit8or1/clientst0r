"""
My Work data sources for remote sessions and remote jobs
(core.workspace.register_source; registered in PsaAiConfig.ready).

    remote_sessions(request, customer_ids)
        The remote-session launch links this technician was issued recently
        (psa_ai.services.rmm_actions.launch audits each one). No paired RMM
        tells ClientSt0r whether a session followed a launch, so every item
        says "launch link issued — session not confirmed"; nothing here
        claims a session started or is running. None (the panel is not
        drawn, My Work lists it under "Set up more") until a paired RMM at
        one of the technician's customers offers remote sessions.

    jobs(request, customer_ids)
        Extra rows for "Needs your review": this technician's Rem0te action
        proposals waiting for Rem0te's approvers, AI analysis jobs that
        finished or failed (OPTIONAL AI: only while AI is on), and support
        workflow runs that wait on a technician's decision. Failed and
        finished RMM requests are already listed by My Work itself.

Scoping is the other panels' (core/workspace.py): the technician's own
records only, narrowed to `customer_ids` (None = every customer they can
reach) and to the customers where they hold the role flag the linked page
needs (`tickets_view` for ticket pages, `assets_view` for device pages).
MSP staff only: My Work calls sources for staff alone.
"""
from __future__ import annotations

from datetime import timedelta

from django.urls import NoReverseMatch, reverse
from django.utils import timezone

LIMIT = 6
LAUNCH_LOOKBACK = timedelta(hours=2)
REVIEW_LOOKBACK = timedelta(days=7)
REMOTE_CAPS = {'remote_view', 'remote_control'}
WORKFLOW_REVIEW = {'ready', 'not_verified', 'failed', 'rejected', 'approval_expired', 'unavailable'}


def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _allowed(request, customer_ids, flag):
    from accounts.permission_utils import orgs_with_perm
    from core.workspace import _intersect
    return _intersect(customer_ids, orgs_with_perm(request.user, flag))


def _remote_capable(customer_ids) -> bool:
    """A live pairing that offers remote sessions, held by one of these
    customers or (an MSP-level connection) reaching devices of one."""
    from django.db.models import Q
    from integrations.models import RMMConnection
    from integrations.ticket_rmm import advertised
    qs = RMMConnection.objects.filter(is_active=True)
    if customer_ids is not None:
        qs = qs.filter(Q(organization_id__in=customer_ids) | Q(devices__organization_id__in=customer_ids))
    return any(REMOTE_CAPS & advertised(c) for c in qs.distinct().order_by('pk')[:50])


def remote_sessions(request, customer_ids):
    from audit.models import AuditLog
    from core.workspace import _narrow, device_open_url
    from integrations.models import RMMDevice
    if not _remote_capable(customer_ids):
        return None
    allowed = _allowed(request, customer_ids, 'assets_view')
    since = timezone.now() - LAUNCH_LOOKBACK
    rows = _narrow(AuditLog.objects.filter(user=request.user, object_type='psa_ai.RemoteLaunch', success=True,
                                           timestamp__gte=since), allowed).order_by('-timestamp')[:50]
    rows = [r for r in rows if isinstance((r.extra_data or {}).get('device'), int)]
    devices = {d.pk: d for d in RMMDevice.objects.filter(
        pk__in={r.extra_data['device'] for r in rows}, ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
        .select_related('organization')}
    items = []
    for r in rows:
        d = devices.get(r.extra_data['device'])
        if d is None or d.organization_id != r.organization_id:
            continue
        mode = 'control' if r.extra_data.get('mode') == 'control' else 'view'
        items.append({
            'title': d.device_name,
            'context': f'{d.organization.name} · remote {mode} · launch link issued '
                       f'{timezone.localtime(r.timestamp).strftime("%H:%M")} — session not confirmed',
            'state': 'Launch link issued — session not confirmed',
            'session_confirmed': False,
            'url': device_open_url('rmm_device', d.pk, _url('psa:my_work'), workspace=True),
            'action': 'Open device',
        })
    return {
        'count': len(items),
        'items': items[:LIMIT],
        'title': 'Remote session launches',
        'empty': 'No remote session launch links issued to you in the last two hours.',
        'note': ('ClientSt0r records the launch links it hands out. The RMM runs the session and does not tell '
                 'ClientSt0r whether one started, so none is shown as active.'),
    }


def jobs(request, customer_ids):
    from core.workspace import _narrow
    from psa_ai.models import AnalysisJob, RMMRequest
    allowed = _allowed(request, customer_ids, 'tickets_view')
    since = timezone.now() - REVIEW_LOOKBACK
    items, count = [], 0

    proposals = _narrow(RMMRequest.objects.filter(
        actor=request.user, kind=RMMRequest.KIND_FIX, connection__provider_type='rem0te',
        status__in=('created', 'pending', 'received'), updated_at__gte=since), allowed).select_related('ticket')
    count += proposals.count()
    for p in proposals.order_by('-updated_at')[:LIMIT]:
        items.append({'title': p.fix_title or 'Rem0te action proposal',
                      'context': f'{p.device_name or p.device_external_id} · {p.ticket.ticket_number}',
                      'state': 'Waiting for approval in Rem0te', 'bad': False,
                      'url': _url('psa:ticket_detail', p.ticket.ticket_number) + '#ticket-rmm-panel',
                      'action': 'Track'})

    from core.ai_gate import ai_features_enabled
    if ai_features_enabled():
        done = _narrow(AnalysisJob.objects.filter(actor=request.user, updated_at__gte=since,
                                                  status__in=AnalysisJob.TERMINAL), allowed).select_related('ticket')
        count += done.count()
        for j in done.order_by('-updated_at')[:LIMIT]:
            ok = j.status in ('completed', 'partial')
            items.append({'title': f'AI analysis ({j.get_kind_display().lower()})',
                          'context': j.ticket.ticket_number,
                          'state': 'Results ready' if ok else j.get_status_display(), 'bad': not ok,
                          'url': _url('psa:ticket_detail', j.ticket.ticket_number),
                          'action': 'Read results' if ok else 'Review'})

    try:
        from psa.support_workflows.models import WorkflowRun
    except Exception:  # noqa: BLE001 — support workflows not installed
        WorkflowRun = None
    if WorkflowRun is not None:
        runs = _narrow(WorkflowRun.objects.filter(actor=request.user, status__in=WORKFLOW_REVIEW,
                                                  updated_at__gte=since), allowed).select_related('ticket')
        count += runs.count()
        for r in runs.order_by('-updated_at')[:LIMIT]:
            items.append({'title': r.workflow_name, 'context': r.ticket.ticket_number,
                          'state': r.get_status_display(), 'bad': r.status != 'ready',
                          'url': _url('support_workflows:run', r.pk),
                          'action': 'Choose next step' if r.status == 'ready' else 'Review'})
    return {'count': count, 'items': items[:LIMIT]}


def register():
    from core.workspace import register_source
    register_source('remote_sessions', remote_sessions)
    register_source('jobs', jobs)

