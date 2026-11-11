"""
Device Workspace page (ClientSt0r ↔ RMM Phase 3).

    GET /assets/<pk>/workspace/[?device=<rmm device pk>][&ticket=<ticket number>]
    GET /assets/workspace/   the sidebar's entry point: recently opened
                             devices, each opening its workspace

MSP technicians only; everyone else gets 404, as for an asset that doesn't
exist. The asset is found the same way as on the asset page (the selected
customer, or any customer in global view for staff). `device` picks one of
the asset's own verified RMM devices; anything else falls back to the
default. `ticket` keeps the ticket's context (back link, ticket-scoped
actions) only when that ticket is visible to the technician, is the same
customer's, and lists this asset as one of its devices; otherwise it is
ignored and the page says so.

Builds from stored data only (assets/device_workspace.py): no RMM call while
the page renders.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from core.middleware import get_request_organization
from core.tenancy import get_org_object_or_404

from . import device_workspace as ws
from .models import Asset


def _asset(request, pk):
    org = get_request_organization(request)
    is_staff = getattr(request, 'is_staff_user', False)
    if not org and (request.user.is_superuser or is_staff):
        return get_object_or_404(Asset.objects.select_related('organization'), pk=pk)
    if not org:
        raise Http404()
    return get_org_object_or_404(Asset, org, pk=pk)


def _ticket_context(request, asset):
    """(ticket or None, note). Only a ticket this technician can open, of
    the asset's own customer, that lists this asset."""
    number = (request.GET.get('ticket') or '').strip()[:32]
    if not number:
        return None, ''
    from psa.affected import is_affected
    from psa.views import _scoped_ticket_qs
    ticket = _scoped_ticket_qs(request).select_related('related_asset').filter(ticket_number=number).first()
    if ticket is None or ticket.organization_id != asset.organization_id or not is_affected(ticket, asset):
        return None, 'The ticket in the link is not one of this device\'s tickets, so its context was not used.'
    return ticket, ''


@login_required
def device_workspace(request, pk):
    from integrations.rmm_association import exposed_devices
    from psa.feature_flags import is_psa_enabled_for_client
    from psa.visibility import is_msp_staff
    from rmm_permissions import can
    from rmm_permissions.decision import scoped
    if not is_msp_staff(request.user):
        raise Http404()
    asset = _asset(request, pk)
    ticket, ticket_note = _ticket_context(request, asset)
    now = timezone.now()
    # Logged-in user names are personal data about the customer's staff:
    # shown only to a technician with live access at this customer.
    show_user = scoped(request.user, asset.organization)
    # The page has always opened for every MSP technician; an RMM permission
    # block (a deny override, a technician-access deny, containment) now
    # withholds what the RMMs report about the device.
    view_decision = can(request.user, asset.organization, 'device.view', device=asset)
    blocked_reason = view_decision.reason if view_decision.blocked else ''
    devices = [] if blocked_reason else list(exposed_devices(asset).order_by('-data_refreshed_at', 'pk'))
    views = [ws.device_view(d, show_user=show_user, now=now) for d in devices]
    selected = None
    wanted = (request.GET.get('device') or '').strip()
    if wanted.isdigit():
        selected = next((v for v in views if v['device'].pk == int(wanted)), None)
    if selected is None and views:
        # Default: freshest online device, else the most recently refreshed.
        selected = next((v for v in views if v['status']['state'] == 'online'), views[0])
    try:
        psa_on = is_psa_enabled_for_client(asset.organization)
    except Exception:
        psa_on = False
    toolbar = ws.toolbar(request.user, asset, selected, ticket=ticket, psa_on=psa_on, blocked_reason=blocked_reason)
    sites = sorted({v['device'].site_name for v in views if v['device'].site_name})
    return render(request, 'assets/device_workspace.html', {
        'asset': asset,
        'views': views,
        'sel': selected,
        'ticket': ticket,
        'ticket_note': ticket_note,
        'toolbar': toolbar,
        'disabled_reasons': [b for b in toolbar if not b['enabled'] and b['reason']],
        'sites': sites,
        'show_user': show_user,
        'blocked_reason': blocked_reason,
        'tickets': ws.related_tickets(asset) if psa_on else [],
        'psa_on': psa_on,
        'docs': ws.related_docs(asset),
        'runbooks': ws.related_runbooks(asset),
        'credentials': ws.related_credentials(asset, request.user),
        'history': ws.remediation_history(devices),
        'launches': ws.launch_history(devices),
    })


@login_required
def device_workspace_home(request):
    """Devices → Device Workspace in the sidebar: the technician's recently
    opened devices (core.workspace.recent_devices, re-scoped on every read)
    that have a workspace, each opened in its customer's context."""
    from core.workspace import recent_devices
    from psa.visibility import is_msp_staff
    if not is_msp_staff(request.user):
        raise Http404()
    here = reverse('assets:device_workspace_home')
    recent = [d for d in recent_devices(request, limit=20, next_url=here) if d.get('workspace_url')]
    return render(request, 'assets/device_workspace_home.html', {'recent': recent[:12]})
