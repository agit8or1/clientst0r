"""The device an alert or incident names, for the detail pages' links.

Alerts and incidents carry a free-text ``asset_hint`` (hostname / device
name). This finds the documented asset and the RMM device with that exact
name in the record's own customer, and returns a link only where the
technician could open the page anyway:

* Device Workspace (assets.workspace_views.device_workspace): MSP staff, the
  /assets/ section permission, the asset found the way that page finds it
  (the selected client and its sub-clients, or any client in global view),
  and ``assets_view`` in the asset's customer. The workspace applies the RMM
  permission decision (rmm_permissions) itself before showing RMM data.
* RMM device page (integrations.views.rmm_device_detail): MSP staff, the
  /integrations/ section permission, a device of the selected client with a
  resolved owner, and no RMM permission block (the page would answer 403).

No lookups run for customer users (the /security/ pages are staff-only).
"""
from __future__ import annotations

from django.db.models import Q
from django.urls import reverse

MAX = 3


def related_devices(request, record):
    hint = (getattr(record, 'asset_hint', '') or '').strip()
    if not hint:
        return {'hint': '', 'assets': [], 'rmm': []}
    out = {'hint': hint, 'assets': [], 'rmm': []}
    from psa.visibility import is_msp_staff
    user = request.user
    if not is_msp_staff(user):
        return out
    from accounts.permission_utils import filter_by_org_perm
    from core import navigation
    from core.middleware import get_request_organization
    from core.utils import descendant_org_ids

    customer_id = record.client_org_id or record.organization_id
    org = get_request_organization(request)
    probe = navigation._PermProbe(navigation.request_context(request))

    from assets.models import Asset
    assets = Asset.objects.filter(organization_id=customer_id).filter(
        Q(name__iexact=hint) | Q(hostname__iexact=hint))
    if org is not None:
        assets = assets.filter(organization_id__in=descendant_org_ids(org))
    elif not (user.is_superuser or getattr(request, 'is_staff_user', False)):
        assets = assets.none()
    for a in filter_by_org_perm(assets, user, 'assets_view').order_by('name')[:MAX]:
        url = reverse('assets:device_workspace', args=[a.pk])
        if probe.allows(url):
            out['assets'].append({'name': a.name, 'hostname': a.hostname, 'url': url})

    if org is not None and probe.allows(reverse('integrations:rmm_devices')):
        from integrations.models import RMMDevice
        from rmm_permissions.decision import can
        devices = (RMMDevice.objects.for_organization(org)
                   .filter(ownership_status=RMMDevice.OWNERSHIP_RESOLVED, organization_id=customer_id)
                   .filter(Q(device_name__iexact=hint) | Q(hostname__iexact=hint))
                   .select_related('organization').order_by('device_name')[:MAX])
        for d in devices:
            try:
                blocked = can(user, d.organization, 'device.view', device=d).blocked
            except Exception:
                blocked = True
            if not blocked:
                out['rmm'].append({'name': d.device_name, 'online': d.is_online,
                                   'url': reverse('integrations:rmm_device_detail', args=[d.pk])})
    return out
