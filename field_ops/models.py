"""
Phase 8 (Field Ops) — models.

Backend foundation for GPS auto-documentation + timeclock + privacy.

Built across the v3.17.397 → v3.17.417 release train. This module is split
across releases:

- v3.17.397 — TechnicianLocation + ClientSiteGeofence
- v3.17.409 — TimeclockEntry + MobileDevice
- v3.17.411 — LocationRetentionPolicy
- v3.17.412 — AutoTimePreference
- v3.17.415 — OrganizationFieldOpsSettings + GeofenceVisit (geofence-only mode)
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


# -----------------------------------------------------------------------------
# Sub-phase 8.1 — TechnicianLocation
# -----------------------------------------------------------------------------

SOURCE_CHOICES = (
    ('mobile', 'Mobile app'),
    ('web', 'Web browser'),
)


class TechnicianLocation(models.Model):
    """
    Append-only GPS ping from a tech's device. Never updated, only created
    + pruned. Off-shift pings are dropped at the API layer (Phase 8.5) and
    never get a row here.
    """

    tech = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gps_pings',
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lon = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy = models.PositiveIntegerField(
        help_text='Reported accuracy radius in meters',
        default=0,
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default='mobile')
    # Pre-computed retention deadline so the prune mgmt cmd is a one-shot
    # WHERE retention_until < today() rather than a per-org join.
    retention_until = models.DateField(db_index=True)

    class Meta:
        verbose_name = 'Technician GPS ping'
        verbose_name_plural = 'Technician GPS pings'
        indexes = [
            models.Index(fields=['tech', 'timestamp']),
        ]
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if not self.retention_until:
            # Default 90 days. The org-level policy (v3.17.389) overrides
            # this when the row is created via the API.
            self.retention_until = (timezone.now().date() + timedelta(days=90))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.tech_id}@{self.lat},{self.lon} {self.timestamp:%Y-%m-%d %H:%M}'


# -----------------------------------------------------------------------------
# Sub-phase 8.1 — ClientSiteGeofence
# -----------------------------------------------------------------------------

GEOFENCE_KIND_CHOICES = (
    ('radius', 'Radius (lat/lon + meters)'),
    ('polygon', 'Polygon (list of lat/lon vertices)'),
)


class ClientSiteGeofence(models.Model):
    """
    Geofence boundary used to auto-detect "tech is on site" for a client.

    Two modes:
    - radius:  center_lat / center_lon + radius_meters.
    - polygon: polygon_json = [[lat, lon], [lat, lon], ...] (closed ring,
               first vertex repeated implicitly).
    """

    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.CASCADE,
        related_name='geofences',
    )
    # Optional FK to a per-org location (Phase 18 multi-location); soft FK so
    # we don't break installs that don't use multi-location yet.
    location = models.ForeignKey(
        'locations.Location',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='geofences',
    )
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=GEOFENCE_KIND_CHOICES, default='radius')
    center_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    center_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_meters = models.PositiveIntegerField(default=100)
    polygon_json = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Client site geofence'
        verbose_name_plural = 'Client site geofences'
        ordering = ['organization_id', 'name']

    def __str__(self) -> str:
        return f'{self.organization_id}:{self.name}'

    def contains(self, lat: Decimal, lon: Decimal) -> bool:
        """
        Quick membership test. Radius mode uses the equirectangular
        approximation (good enough at MSP scale, ~100m geofences). Polygon
        mode uses ray casting.
        """
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return False

        if self.kind == 'radius':
            if self.center_lat is None or self.center_lon is None:
                return False
            # Equirectangular: distance ≈ R * sqrt(dlat² + (cos(lat) * dlon)²)
            import math
            R = 6_371_000  # meters
            clat = float(self.center_lat)
            clon = float(self.center_lon)
            dlat = math.radians(lat_f - clat)
            dlon = math.radians(lon_f - clon)
            mlat = math.radians((lat_f + clat) / 2.0)
            x = dlon * math.cos(mlat)
            y = dlat
            distance = R * math.sqrt(x * x + y * y)
            return distance <= float(self.radius_meters)

        if self.kind == 'polygon':
            poly = self.polygon_json or []
            if len(poly) < 3:
                return False
            # Ray casting algorithm.
            inside = False
            n = len(poly)
            j = n - 1
            for i in range(n):
                pi = poly[i]
                pj = poly[j]
                if not (isinstance(pi, (list, tuple)) and len(pi) == 2):
                    continue
                if not (isinstance(pj, (list, tuple)) and len(pj) == 2):
                    continue
                yi, xi = float(pi[0]), float(pi[1])
                yj, xj = float(pj[0]), float(pj[1])
                if ((yi > lat_f) != (yj > lat_f)) and (
                    lon_f < (xj - xi) * (lat_f - yi) / ((yj - yi) or 1e-12) + xi
                ):
                    inside = not inside
                j = i
            return inside

        return False


# -----------------------------------------------------------------------------
# Sub-phase 8.1 (part 2) — TimeclockEntry + MobileDevice (v3.17.409)
# -----------------------------------------------------------------------------

TIMECLOCK_SOURCE_CHOICES = (
    ('mobile', 'Mobile app'),
    ('web', 'Web browser'),
    ('manual', 'Manual entry'),
)


class TimeclockEntry(models.Model):
    """
    Tech clock-in / clock-out event.

    `clocked_out_at` null = currently on the clock. On save with both
    `clocked_out_at` AND `ticket` set, we derive a `psa.TicketTimeEntry`
    so the existing billing rollup works unchanged.
    """

    tech = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='timeclock_entries',
    )
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='timeclock_entries',
    )
    location = models.ForeignKey(
        'locations.Location',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='timeclock_entries',
    )
    ticket = models.ForeignKey(
        'psa.Ticket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='timeclock_entries',
    )
    project = models.ForeignKey(
        'psa.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='timeclock_entries',
    )
    clocked_in_at = models.DateTimeField(default=timezone.now, db_index=True)
    clocked_out_at = models.DateTimeField(null=True, blank=True, db_index=True)
    source = models.CharField(max_length=12, choices=TIMECLOCK_SOURCE_CHOICES, default='mobile')
    notes = models.TextField(blank=True)
    # Tracks the auto-derived TicketTimeEntry created on clock-out so a re-save
    # doesn't double-bill.
    derived_time_entry = models.ForeignKey(
        'psa.TicketTimeEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Timeclock entry'
        verbose_name_plural = 'Timeclock entries'
        ordering = ['-clocked_in_at']
        indexes = [
            models.Index(fields=['tech', '-clocked_in_at']),
            models.Index(fields=['organization', '-clocked_in_at']),
        ]
        constraints = [
            # Only one open clock-in per tech.
            models.UniqueConstraint(
                fields=['tech'],
                condition=models.Q(clocked_out_at__isnull=True),
                name='field_ops_one_open_timeclock_per_tech',
            ),
        ]

    def __str__(self) -> str:
        state = 'open' if self.clocked_out_at is None else 'closed'
        return f'TC#{self.pk or "?"} {self.tech_id} ({state})'

    @property
    def duration_minutes(self) -> int:
        end = self.clocked_out_at or timezone.now()
        delta = end - self.clocked_in_at
        return max(0, int(delta.total_seconds() // 60))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # On clock-out + ticket attached: derive TicketTimeEntry once.
        if (
            self.clocked_out_at
            and self.ticket_id
            and self.derived_time_entry_id is None
        ):
            try:
                from psa.models import TicketTimeEntry
                tte = TicketTimeEntry.objects.create(
                    ticket_id=self.ticket_id,
                    user=self.tech,
                    started_at=self.clocked_in_at,
                    ended_at=self.clocked_out_at,
                    notes=(self.notes or '')[:500],
                    is_billable=True,
                )
                # Bypass our own save() — direct UPDATE to avoid recursion.
                TimeclockEntry.objects.filter(pk=self.pk).update(
                    derived_time_entry=tte
                )
                self.derived_time_entry_id = tte.pk
            except Exception:
                # Never block timeclock on billing-derivation failures.
                pass


MOBILE_PLATFORM_CHOICES = (
    ('ios', 'iOS'),
    ('android', 'Android'),
)


class MobileDevice(models.Model):
    """
    A registered mobile device for a user. May be tied to the hashed
    mobile API token (api_mobile.MobileAuthToken) it signed in with.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mobile_devices',
    )
    device_id = models.UUIDField(unique=True)
    platform = models.CharField(max_length=10, choices=MOBILE_PLATFORM_CHOICES)
    name = models.CharField(max_length=200, blank=True)
    token = models.ForeignKey(
        'api_mobile.MobileAuthToken',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # v3.17.463 — Expo push token for notifications. Format
    # `ExponentPushToken[...]`. Routed through Expo's push service which
    # handles FCM (Android) + APNS (iOS) without per-project setup.
    # `notifications_enabled` lets a user mute pushes without
    # unregistering the device entirely.
    expo_push_token = models.CharField(max_length=200, blank=True, default='')
    notifications_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Mobile device'
        verbose_name_plural = 'Mobile devices'
        ordering = ['-last_seen_at']
        indexes = [
            models.Index(fields=['user', '-last_seen_at']),
        ]

    def __str__(self) -> str:
        return f'{self.user_id}/{self.platform}/{self.name or self.device_id}'


# -----------------------------------------------------------------------------
# Sub-phase 8.5 (part 1) — LocationRetentionPolicy (v3.17.411)
# -----------------------------------------------------------------------------


class LocationRetentionPolicy(models.Model):
    """
    Per-organization retention policy for `TechnicianLocation` rows.

    A nightly mgmt cmd uses this to derive the `retention_until` deadline
    for new pings, and prunes older rows. Default is 90 days. When
    `apply_to_geofence_only` is True, regular ping rows are pruned but
    geofence-visit aggregates (introduced in v3.17.415) are kept.
    """

    organization = models.OneToOneField(
        'core.Organization',
        on_delete=models.CASCADE,
        related_name='location_retention_policy',
    )
    retention_days = models.PositiveIntegerField(default=90)
    apply_to_geofence_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Location retention policy'
        verbose_name_plural = 'Location retention policies'

    def __str__(self) -> str:
        return f'{self.organization_id}: {self.retention_days}d'


# -----------------------------------------------------------------------------
# Sub-phase 8.2 — AutoTimePreference (v3.17.412)
# -----------------------------------------------------------------------------

AUTO_TIME_MODE_CHOICES = (
    ('always_on', 'Always on (auto-start time entries silently)'),
    ('ask_first', 'Ask first (push notification, requires confirm)'),
    ('off', 'Off (no auto-time)'),
)


class AutoTimePreference(models.Model):
    """
    Per-tech preference for the GPS auto-documentation engine.

    `always_on` — entering a known geofence auto-starts a `TicketTimeEntry`
        against the tech's last-active ticket for that org.
    `ask_first` — the engine creates a pending confirmation row and emits
        a Web Push notification; the time entry is only committed when the
        tech taps Confirm.
    `off`       — engine skips this user entirely.

    Default is `ask_first` (privacy-preserving).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='auto_time_preference',
    )
    mode = models.CharField(
        max_length=12, choices=AUTO_TIME_MODE_CHOICES, default='ask_first',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Auto-time preference'
        verbose_name_plural = 'Auto-time preferences'

    def __str__(self) -> str:
        return f'{self.user_id}: {self.mode}'


class PendingAutoTime(models.Model):
    """
    Sub-phase 8.2 ask-first staging row. Created when an `ask_first`
    tech enters a geofence; the engine emits a push, then this row is
    promoted to a real `TicketTimeEntry` if the tech confirms before
    the auto-expiry.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pending_auto_time',
    )
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.CASCADE,
        related_name='+',
    )
    geofence = models.ForeignKey(
        ClientSiteGeofence,
        on_delete=models.CASCADE,
        related_name='+',
    )
    suggested_ticket = models.ForeignKey(
        'psa.Ticket',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    entered_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-entered_at']
        indexes = [
            models.Index(fields=['user', '-entered_at']),
        ]

    def __str__(self) -> str:
        return f'PendingAutoTime#{self.pk or "?"} u={self.user_id}'


# -----------------------------------------------------------------------------
# Sub-phase 8.5 (parts 1+2) — OrganizationFieldOpsSettings + GeofenceVisit
# (v3.17.415)
# -----------------------------------------------------------------------------


class OrganizationFieldOpsSettings(models.Model):
    """
    Per-organization field-ops privacy + retention settings.

    `geofence_only_mode` — when True, the locations POST endpoint stores
        only `(geofence, entered_at, exited_at)` triples in `GeofenceVisit`
        for techs working under this org's umbrella; raw lat/lon is never
        persisted.
    `retention_days` — controls TechnicianLocation retention deadlines
        (existing `LocationRetentionPolicy` predates this and remains
        valid; this row supersedes it when both exist).
    """

    organization = models.OneToOneField(
        'core.Organization',
        on_delete=models.CASCADE,
        related_name='field_ops_settings',
    )
    geofence_only_mode = models.BooleanField(default=False)
    retention_days = models.PositiveIntegerField(default=90)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Org Field Ops settings'
        verbose_name_plural = 'Org Field Ops settings'

    def __str__(self) -> str:
        return f'{self.organization_id} fops (geofence_only={self.geofence_only_mode})'


class GeofenceVisit(models.Model):
    """
    Privacy-preserving alternative to TechnicianLocation. When an org
    enables `geofence_only_mode`, the locations endpoint logs a row here
    on first inside-ping and updates `exited_at` when the tech leaves.
    Raw coordinates are never stored — just the geofence id + timestamps.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='geofence_visits',
    )
    geofence = models.ForeignKey(
        ClientSiteGeofence,
        on_delete=models.CASCADE,
        related_name='visits',
    )
    entered_at = models.DateTimeField(default=timezone.now)
    exited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-entered_at']
        indexes = [
            models.Index(fields=['user', '-entered_at']),
            models.Index(fields=['geofence', '-entered_at']),
        ]

    def __str__(self) -> str:
        return f'GeofenceVisit#{self.pk or "?"} u={self.user_id} g={self.geofence_id}'
