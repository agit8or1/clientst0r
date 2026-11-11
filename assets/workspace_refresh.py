"""
"Refresh from RMM" on the Device Workspace.

    POST /assets/<pk>/workspace/refresh/   device=<rmm device pk>

MSP technicians only (404 otherwise, as for the page). The device must be
one of the asset's own verified devices (rmm_association.exposed_devices).
Permission is the RMM permission model's `device.view` for that device at
the asset's customer, checked with rmm_action() right before acting (that
call audits the allow or deny). The outcome is audited too. The refresh
itself (integrations/rmm_refresh.py) is rate limited per device and runs
the provider's single-device read; the page never calls a provider.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .workspace_views import _asset


def _back(asset, device=None, ticket=''):
    q = {}
    if device is not None:
        q['device'] = device.pk
    if ticket:
        q['ticket'] = ticket[:32]
    url = reverse('assets:device_workspace', args=[asset.pk])
    return redirect(url + ('?' + urlencode(q) if q else ''))


def _audit(request, asset, device, result):
    from audit.models import AuditLog
    AuditLog.log(user=request.user, action='sync', organization=asset.organization,
                 object_type='rmm_device_refresh', object_id=device.pk, object_repr=str(device)[:200],
                 description=f'Refresh from RMM ({result.outcome}): {result.message}'[:500],
                 success=result.ok,
                 extra_data={'device': device.pk, 'asset': asset.pk, 'connection': device.connection_id,
                             'outcome': result.outcome},
                 ip_address=request.META.get('REMOTE_ADDR') or None, path=request.path[:500])


@login_required
@require_POST
def refresh_from_rmm(request, pk):
    from integrations.rmm_association import exposed_devices
    from integrations.rmm_refresh import RefreshResult, REFUSED, refresh_device
    from psa.visibility import is_msp_staff
    from rmm_permissions import rmm_action
    if not is_msp_staff(request.user):
        raise Http404()
    asset = _asset(request, pk)
    wanted = (request.POST.get('device') or '').strip()
    device = exposed_devices(asset).filter(pk=int(wanted)).first() if wanted.isdigit() else None
    if device is None:
        raise Http404()
    ticket = (request.POST.get('ticket') or '').strip()
    decision = rmm_action(request.user, asset.organization, 'device.view', device=device, request=request)
    if not decision.permitted_now:
        result = RefreshResult(REFUSED, f'Not allowed: {decision.reason}')
    else:
        result = refresh_device(device)
    _audit(request, asset, device, result)
    (messages.success if result.ok else messages.warning)(request, result.message)
    return _back(asset, device, ticket)
