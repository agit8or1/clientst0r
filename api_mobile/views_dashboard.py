"""
Mobile API dashboard + organizations endpoints (v3.17.347).
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids, perm_org_ids


def _safe_count(model_path, **filters):
    """Count rows defensively — missing app / model returns 0 instead of 500."""
    try:
        from importlib import import_module
        module_name, cls_name = model_path.rsplit('.', 1)
        mod = import_module(module_name)
        Model = getattr(mod, cls_name)
        return Model.objects.filter(**filters).count()
    except Exception:
        return 0


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    """
    GET /api/mobile/v1/dashboard/

    Returns the shape the mobile DashboardScreen consumes (v3.17.448 —
    aligned with `mobile/src/types/api.ts::DashboardSummary`):
      - counts: open_tickets, critical_tickets, my_open_tickets,
        expiring_soon, monitors_down
      - recent_tickets: list of Ticket dicts (max 5, most recently updated)
      - recent_assets:  list of Asset dicts (max 5, most recently created)
      - security: SecuritySummary with severity counts + recent_alerts

    Org-scoped to the user's active memberships. Each section is wrapped
    in a try/except so a missing optional app (psa, security_alerts, …)
    leaves its slice empty/zero rather than 500ing the whole dashboard.
    """
    org_ids = list(accessible_org_ids(request.user))
    now = timezone.now()
    soon = now + timezone.timedelta(days=30)

    # === Tickets ===
    open_tickets = critical_tickets = my_open_tickets = new_tickets = 0
    recent_tickets: list = []
    try:
        from psa.models import Ticket  # noqa: WPS433 — soft import: PSA may be uninstalled
        from .views_tickets import _serialize_ticket
        open_qs = Ticket.objects.filter(
            organization_id__in=org_ids, status__is_terminal=False,
        )
        open_tickets = open_qs.count()
        critical_tickets = open_qs.filter(priority__code='P1').count()
        my_open_tickets = open_qs.filter(assigned_to=request.user).count()
        # v3.17.477 — "Open (New)" tile on the mobile dashboard. Counts
        # tickets currently sitting in the 'new' status (un-triaged) so
        # techs can see backlog separately from total open.
        new_tickets = open_qs.filter(status__slug='new').count()
        for t in (open_qs
                  .select_related('status', 'priority', 'organization', 'assigned_to')
                  .order_by('-updated_at')[:5]):
            recent_tickets.append(_serialize_ticket(t))
    except Exception:
        pass

    # === Recent assets (most recently created, 5) ===
    recent_assets: list = []
    try:
        from assets.models import Asset  # noqa: WPS433 — soft import
        from .views_assets import _serialize_asset
        asset_org_ids = perm_org_ids(request.user, 'assets_view')
        for a in (Asset.objects
                  .filter(organization_id__in=asset_org_ids)
                  .order_by('-created_at')[:5]):
            recent_assets.append(_serialize_asset(a))
    except Exception:
        pass

    # === Expirations (within next 30 days) ===
    expiring_soon = _safe_count(
        'monitoring.models.Expiration',
        organization_id__in=org_ids, expires_at__lte=soon, expires_at__gte=now,
    )

    # === Monitors offline ===
    monitors_down = _safe_count(
        'monitoring.models.WebsiteMonitor',
        organization_id__in=org_ids, last_status='down',
    )

    # === Security alerts ===
    security = {
        'open_alert_count': 0,
        'critical_alert_count': 0,
        'high_alert_count': 0,
        'medium_alert_count': 0,
        'low_alert_count': 0,
        'recent_alerts': [],
    }
    try:
        from security_alerts.models import SecurityAlert  # noqa: WPS433
        open_alerts = SecurityAlert.objects.filter(
            organization_id__in=org_ids, status='open',
        )
        security['open_alert_count'] = open_alerts.count()
        for sev in ('critical', 'high', 'medium', 'low'):
            security[f'{sev}_alert_count'] = open_alerts.filter(severity=sev).count()
        for sa in open_alerts.order_by('-created_at')[:5]:
            security['recent_alerts'].append({
                'id': sa.id,
                'severity': sa.severity,
                'title': sa.title,
                'created_at': sa.created_at.isoformat() if sa.created_at else None,
            })
    except Exception:
        pass

    return Response({
        'open_tickets': open_tickets,
        'critical_tickets': critical_tickets,
        'my_open_tickets': my_open_tickets,
        'new_tickets': new_tickets,
        'expiring_soon': expiring_soon,
        'monitors_down': monitors_down,
        'recent_tickets': recent_tickets,
        'recent_assets': recent_assets,
        'security': security,
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def organization_list_view(request):
    """
    GET /api/mobile/v1/organizations/?search=&page=

    Paginated list of organizations the user has access to.
    """
    from core.models import Organization

    org_ids = accessible_org_ids(request.user)
    qs = Organization.objects.filter(id__in=org_ids).order_by('name')

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(slug__icontains=search))

    # Manual pagination — DRF default class would add overhead from a generic view.
    try:
        page = max(int(request.query_params.get('page', 1)), 1)
    except ValueError:
        page = 1
    page_size = 50
    start = (page - 1) * page_size
    total = qs.count()
    rows = qs[start:start + page_size]

    return Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': [
            {
                'id': o.id,
                'name': o.name,
                'slug': o.slug,
                'organization_type': getattr(o, 'organization_type', '') or '',
            }
            for o in rows
        ],
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def organization_detail_view(request, pk: int):
    """
    GET /api/mobile/v1/organizations/<id>/

    Detail with related counts. Cross-org reads are rejected with 404.
    """
    from core.models import Organization

    org_ids = accessible_org_ids(request.user)
    if pk not in org_ids:
        return Response({'detail': 'Not found'}, status=404)

    try:
        org = Organization.objects.get(pk=pk)
    except Organization.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    # Assets and contacts are both gated by `assets_view` in this customer;
    # without it the counts read as zero rather than leaking the volume.
    can_view_assets = pk in perm_org_ids(request.user, 'assets_view')
    asset_count = (_safe_count('assets.models.Asset', organization_id=pk)
                   if can_view_assets else 0)
    ticket_count = _safe_count(
        'psa.models.Ticket', organization_id=pk, status__is_terminal=False,
    )
    contact_count = (_safe_count('assets.models.Contact', organization_id=pk)
                     if can_view_assets else 0)

    return Response({
        'id': org.id,
        'name': org.name,
        'slug': org.slug,
        'organization_type': getattr(org, 'organization_type', '') or '',
        'asset_count': asset_count,
        'open_ticket_count': ticket_count,
        'contact_count': contact_count,
    })
