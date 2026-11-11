"""Geo-aware dispatch: last known technician positions and travel estimates.

Privacy rules, enforced here so every caller gets them:

  * Off unless an administrator switches it on (DispatchGeoSettings.enabled).
  * Opt-in per technician (DispatchLocationConsent). Without consent no
    position is kept or used. Withdrawing consent deletes the position.
  * MSP technicians only; customer users are never tracked and never see
    positions, distances or travel times.
  * Only a position newer than `freshness_minutes` is used. Positions are
    deleted after `retention_hours`, when consent is withdrawn and when the
    feature is switched off.
  * Positions come from on-shift mobile pings (off-shift pings are dropped
    before they reach this module). For a customer in geofence-only mode the
    geofence centre is kept, never the raw coordinates.

Estimates are a straight-line (haversine) distance times a road factor at an
average speed. An optional OSRM-compatible routing server can refine a
dispatcher's on-demand estimate; it is configured by the administrator, is
called only through the outbound HTTP guard (core.safe_http) and is never
called while a page renders or while routing evaluates a ticket.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

logger = logging.getLogger('field_ops.geo_dispatch')

KM_PER_MILE = 1.609344
EARTH_RADIUS_KM = 6371.0088


def load_settings():
    from .models import DispatchGeoSettings
    return DispatchGeoSettings.load()


def _is_tech(user) -> bool:
    from psa.visibility import is_msp_staff
    return bool(user is not None and getattr(user, 'is_active', False) and is_msp_staff(user))


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def has_consent(user) -> bool:
    from .models import DispatchLocationConsent
    return DispatchLocationConsent.objects.filter(user=user, share_with_dispatch=True).exists()


def set_consent(user, share: bool):
    """Record the technician's choice. Withdrawing deletes their position."""
    from .models import DispatchLocationConsent, DispatchPosition
    if share and not _is_tech(user):
        raise PermissionError('Only MSP technicians can share a position with dispatch.')
    DispatchLocationConsent.objects.update_or_create(
        user=user, defaults={'share_with_dispatch': bool(share), 'decided_at': timezone.now()})
    if not share:
        DispatchPosition.objects.filter(user=user).delete()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def purge_expired(now=None, cfg=None) -> int:
    """Delete positions past retention (all of them when the feature is off)."""
    from .models import DispatchPosition
    now = now or timezone.now()
    cfg = cfg or load_settings()
    if not cfg.enabled:
        deleted, _ = DispatchPosition.objects.all().delete()
        return deleted
    cutoff = now - timedelta(hours=max(1, int(cfg.retention_hours or 1)))
    deleted, _ = DispatchPosition.objects.filter(recorded_at__lt=cutoff).delete()
    return deleted


def record_ping(user, lat, lon, *, accuracy=0, when=None, geofence=None) -> bool:
    """Keep the technician's last known position for dispatch, when allowed.
    Called by the mobile location endpoint after an on-shift ping. Returns
    True when a position was stored. Never raises."""
    try:
        from .models import DispatchPosition
        cfg = load_settings()
        if not cfg.enabled or not _is_tech(user) or not has_consent(user):
            return False
        when = when or timezone.now()
        source = 'gps'
        if geofence is not None:
            if geofence.center_lat is None or geofence.center_lon is None:
                return False
            lat, lon, accuracy, source = geofence.center_lat, geofence.center_lon, geofence.radius_meters, 'geofence'
        existing = DispatchPosition.objects.filter(user=user).first()
        if existing is not None and existing.recorded_at > when:
            return False  # an older ping arriving late
        DispatchPosition.objects.update_or_create(user=user, defaults={
            'lat': Decimal(str(lat)).quantize(Decimal('0.000001')),
            'lon': Decimal(str(lon)).quantize(Decimal('0.000001')),
            'accuracy': max(0, int(accuracy or 0)), 'recorded_at': when, 'source': source})
        purge_expired(cfg=cfg)
        return True
    except Exception:  # noqa: BLE001 — dispatch geo must never break a ping
        logger.exception('dispatch position update failed')
        return False


@dataclass
class Position:
    user_id: int
    lat: float
    lon: float
    recorded_at: object
    source: str
    accuracy: int

    @property
    def age_minutes(self) -> int:
        return max(0, int((timezone.now() - self.recorded_at).total_seconds() // 60))

    @property
    def source_label(self) -> str:
        return 'inside a customer geofence' if self.source == 'geofence' else 'mobile GPS'


def positions(users, now=None, cfg=None) -> Dict[int, Position]:
    """{user_id: Position} for fresh, consented technician positions."""
    from .models import DispatchLocationConsent, DispatchPosition
    cfg = cfg or load_settings()
    if not cfg.enabled:
        return {}
    now = now or timezone.now()
    ids = [u.pk for u in users if _is_tech(u)]
    if not ids:
        return {}
    consented = set(DispatchLocationConsent.objects.filter(user_id__in=ids, share_with_dispatch=True)
                    .values_list('user_id', flat=True))
    fresh_after = now - timedelta(minutes=max(1, int(cfg.freshness_minutes or 1)))
    out = {}
    for p in DispatchPosition.objects.filter(user_id__in=consented, recorded_at__gte=fresh_after,
                                             recorded_at__lte=now + timedelta(minutes=5)):
        out[p.user_id] = Position(p.user_id, float(p.lat), float(p.lon), p.recorded_at, p.source, p.accuracy)
    return out


# ---------------------------------------------------------------------------
# Sites + estimates
# ---------------------------------------------------------------------------

def site_point(ticket) -> Optional[Tuple[float, float, str]]:
    """(lat, lon, label) of where the ticket's work is: the ticket's site when
    it has coordinates, else the customer's primary site with coordinates."""
    from psa.ticket_site import site_allowed
    site = ticket.site if getattr(ticket, 'site_id', None) else None
    if site is not None and site.has_coordinates and site_allowed(ticket.organization, site):
        return float(site.latitude), float(site.longitude), site.name
    from locations.models import Location
    primary = (Location.objects.filter(organization_id=ticket.organization_id, is_primary=True,
                                       latitude__isnull=False, longitude__isnull=False)
               .exclude(status__in=('inactive', 'closed')).first())
    if primary is not None:
        return float(primary.latitude), float(primary.longitude), f'{primary.name} (primary site)'
    return None


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class Estimate:
    distance_km: float
    minutes: int
    method: str          # 'straight_line' | 'routing'
    unit: str = 'mi'

    @property
    def distance(self) -> float:
        return round(self.distance_km / KM_PER_MILE if self.unit == 'mi' else self.distance_km, 1)

    @property
    def label(self) -> str:
        approx = '~' if self.method == 'straight_line' else ''
        return f'{self.distance} {self.unit} · {approx}{self.minutes} min'

    def as_dict(self):
        return {'distance': self.distance, 'unit': self.unit, 'distance_km': round(self.distance_km, 2),
                'minutes': self.minutes, 'method': self.method, 'label': self.label}


def estimate(pos: Position, point, cfg=None) -> Estimate:
    """Straight-line distance × road factor at the average speed. No network."""
    cfg = cfg or load_settings()
    km = haversine_km(pos.lat, pos.lon, point[0], point[1])
    speed_kmh = max(1, int(cfg.average_speed or 30)) * (KM_PER_MILE if cfg.distance_unit == 'mi' else 1)
    road_km = km * float(cfg.road_factor or 1)
    minutes = int(math.ceil(road_km / speed_kmh * 60)) if road_km > 0 else 0
    return Estimate(distance_km=km, minutes=minutes, method='straight_line', unit=cfg.distance_unit)


def road_estimate(pos: Position, point, cfg=None, *, timeout=5) -> Estimate:
    """On-demand estimate from the administrator's routing server when one is
    configured; falls back to the straight-line estimate on any problem."""
    cfg = cfg or load_settings()
    fallback = estimate(pos, point, cfg)
    if cfg.routing_provider != 'osrm' or not cfg.routing_base_url:
        return fallback
    try:
        import requests
        from core.safe_http import configured_service_policy, guard_session, validate_url
        base = cfg.routing_base_url.rstrip('/')
        url = f'{base}/route/v1/driving/{pos.lon:.6f},{pos.lat:.6f};{point[1]:.6f},{point[0]:.6f}'
        policy = configured_service_policy()
        validate_url(url, policy)
        session = requests.Session()
        session.trust_env = False  # no proxies / .netrc: the guard resolves the host itself
        session = guard_session(session, policy)
        resp = session.get(url, params={'overview': 'false'}, timeout=timeout, allow_redirects=False)
        resp.raise_for_status()
        route = (resp.json().get('routes') or [None])[0]
        if not route:
            return fallback
        return Estimate(distance_km=float(route['distance']) / 1000.0,
                        minutes=int(math.ceil(float(route['duration']) / 60.0)),
                        method='routing', unit=cfg.distance_unit)
    except Exception as exc:  # noqa: BLE001 — the estimate is advisory
        logger.warning('routing provider estimate failed: %s', exc)
        return fallback


def nearest(ticket, users, now=None, cfg=None) -> Tuple[List[tuple], List[dict], Optional[tuple]]:
    """([(user, Estimate)] nearest first, [{user_id, username, reason}] for
    technicians without a usable position, site point or None)."""
    cfg = cfg or load_settings()
    point = site_point(ticket)
    users = list(users)
    if point is None or not cfg.enabled:
        return [], [], point
    pos = positions(users, now=now, cfg=cfg)
    ranked, missing = [], []
    for u in users:
        p = pos.get(u.pk)
        if p is None:
            missing.append({'user_id': u.pk, 'username': u.get_username(),
                            'reason': 'no recent shared position'})
            continue
        ranked.append((u, estimate(p, point, cfg)))
    ranked.sort(key=lambda r: (r[1].distance_km, r[0].pk))
    return ranked, missing, point
