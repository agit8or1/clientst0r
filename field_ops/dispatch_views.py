"""Geo-aware dispatch pages (Phase 11 deferred items).

* /field-ops/dispatch-sharing/   — a technician sees exactly what dispatch
                                   sees about them and opts in or out
* /field-ops/dispatch-geo/       — superuser settings: on/off, freshness,
                                   retention, speed, optional routing server

Customer users never reach either page.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog

from . import geo_dispatch
from .models import (
    DISTANCE_UNIT_CHOICES, ROUTING_PROVIDER_CHOICES, DispatchGeoSettings, DispatchPosition,
)


def _is_tech(user):
    from psa.visibility import is_msp_staff
    return bool(user.is_authenticated and user.is_active and is_msp_staff(user))


def _audit(request, description, extra=None):
    try:
        from core.client_ip import get_client_ip
        ip = get_client_ip(request)
    except Exception:  # noqa: BLE001
        ip = None
    AuditLog.log(user=request.user, action='update', object_type='field_ops.DispatchGeo',
                 object_repr='Dispatch locations', description=description[:1000],
                 ip_address=ip, path=request.path, extra_data=extra or {})


@login_required
@require_http_methods(['GET', 'POST'])
def dispatch_sharing(request):
    if not _is_tech(request.user):
        raise Http404()
    if request.method == 'POST':
        share = request.POST.get('share') == 'on'
        geo_dispatch.set_consent(request.user, share)
        _audit(request, f'{request.user.get_username()} '
                        f'{"started" if share else "stopped"} sharing their position with dispatch')
        messages.success(request, 'You now share your last known position with dispatch.' if share else
                         'You no longer share your position with dispatch; your last known position was deleted.')
        return redirect('field_ops:dispatch_sharing')
    cfg = geo_dispatch.load_settings()
    return render(request, 'field_ops/dispatch_sharing.html', {
        'cfg': cfg, 'sharing': geo_dispatch.has_consent(request.user),
        'position': DispatchPosition.objects.filter(user=request.user).first(),
    })


def _int(raw, default, lo, hi):
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


@login_required
@require_http_methods(['GET', 'POST'])
def dispatch_geo_settings(request):
    if not (request.user.is_superuser and _is_tech(request.user)):
        raise Http404()
    cfg = DispatchGeoSettings.load()
    if request.method == 'POST':
        before = {'enabled': cfg.enabled, 'routing_provider': cfg.routing_provider,
                  'routing_base_url': cfg.routing_base_url, 'retention_hours': cfg.retention_hours}
        cfg.enabled = request.POST.get('enabled') == 'on'
        cfg.freshness_minutes = _int(request.POST.get('freshness_minutes'), 30, 1, 1440)
        cfg.retention_hours = _int(request.POST.get('retention_hours'), 8, 1, 168)
        unit = request.POST.get('distance_unit')
        cfg.distance_unit = unit if unit in dict(DISTANCE_UNIT_CHOICES) else 'mi'
        cfg.average_speed = _int(request.POST.get('average_speed'), 30, 1, 200)
        try:
            factor = Decimal(str(request.POST.get('road_factor') or '1.30'))
            cfg.road_factor = min(Decimal('3'), max(Decimal('1'), factor)).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            cfg.road_factor = Decimal('1.30')
        provider = request.POST.get('routing_provider')
        cfg.routing_provider = provider if provider in dict(ROUTING_PROVIDER_CHOICES) else 'none'
        url = (request.POST.get('routing_base_url') or '').strip()[:200]
        if url:
            from core.safe_http import UnsafeURLError, configured_service_policy, validate_url
            try:
                validate_url(url, configured_service_policy())
            except UnsafeURLError:
                messages.error(request, 'That routing server address is not allowed by the outbound policy; '
                                        'it was not saved.')
                url = cfg.routing_base_url
        cfg.routing_base_url = url
        if cfg.routing_provider == 'osrm' and not cfg.routing_base_url:
            cfg.routing_provider = 'none'
            messages.warning(request, 'No routing server address, so estimates stay straight-line.')
        cfg.updated_by = request.user
        cfg.save()
        purged = geo_dispatch.purge_expired(cfg=cfg)
        after = {'enabled': cfg.enabled, 'routing_provider': cfg.routing_provider,
                 'routing_base_url': cfg.routing_base_url, 'retention_hours': cfg.retention_hours}
        _audit(request, f'Dispatch locations {"on" if cfg.enabled else "off"}'
                        + (f'; {purged} position(s) deleted' if purged else ''),
               extra={'changed': {k: [before[k], after[k]] for k in before if before[k] != after[k]}})
        messages.success(request, 'Dispatch location settings saved.')
        return redirect('field_ops:dispatch_geo_settings')
    from field_ops.models import DispatchLocationConsent
    return render(request, 'field_ops/dispatch_geo_settings.html', {
        'cfg': cfg, 'unit_choices': DISTANCE_UNIT_CHOICES, 'provider_choices': ROUTING_PROVIDER_CHOICES,
        'sharing_count': DispatchLocationConsent.objects.filter(share_with_dispatch=True).count(),
        'position_count': DispatchPosition.objects.count(),
    })
