"""
Mobile API field-ops endpoints — locations / timeclock / active-ticket.

Phase 8 v3.17.410 — Sub-phase 8.1 REST surface.

All endpoints require token auth. Off-shift GPS pings are dropped at the
API layer per Sub-phase 8.5: pings outside the user's `WorkingHours` are
audit-logged and discarded — never written to `TechnicianLocation`.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.models import AuditLog
from api_mobile.scoping import accessible_org_ids
from core.models import Organization
from locations.models import Location
from psa.models import Project, Ticket
from field_ops.models import (
    ClientSiteGeofence,
    GeofenceVisit,
    OrganizationFieldOpsSettings,
    TechnicianLocation,
    TimeclockEntry,
)


def _audit(user, action, request, extra=None):
    try:
        AuditLog.objects.create(
            user=user,
            username=getattr(user, 'username', '') or '',
            action=action,
            object_type='FieldOps',
            ip_address=_client_ip(request),
            extra_data=extra or {},
        )
    except Exception:
        pass


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None


def _is_off_shift(user, when):
    """Return True if `when` falls outside the user's WorkingHours.

    Backwards compatible: if the user has no WorkingHours rows at all,
    we treat them as always working (False).
    """
    try:
        import zoneinfo
        profile = getattr(user, 'profile', None)
        tz_name = getattr(profile, 'timezone', None) or 'UTC'
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo('UTC')
        local = when.astimezone(tz)
        weekday = local.weekday()
        rows = user.resourcing_working_hours.filter(weekday=weekday, is_active=True)
        if not rows.exists():
            # If user has any WorkingHours rows for other weekdays, they're off today
            if user.resourcing_working_hours.exists():
                return True
            return False
        t = local.time()
        return not any(r.start_time <= t <= r.end_time for r in rows)
    except Exception:
        # On any failure, do not drop pings — fail-open keeps GPS flowing.
        return False


def _scoped_fk(raw, field, allowed_qs):
    """Validate one client-supplied foreign key.

    Returns `(pk_or_None, None)` when acceptable, or `(None, Response)` to
    return straight to the caller. A value the technician cannot reach is a
    404, not a 403, so the response does not confirm that the row exists in
    some other tenant.
    """
    if raw in (None, '', 0):
        return None, None
    try:
        pk = int(raw)
    except (TypeError, ValueError):
        return None, Response({'detail': f'{field} must be an integer'}, status=400)
    if not allowed_qs.filter(pk=pk).exists():
        return None, Response({'detail': f'{field} not found'}, status=404)
    return pk, None


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def location_ping_view(request):
    """
    POST /api/mobile/v1/locations/

    Body: `{lat, lon, accuracy?, timestamp?}`. Off-shift pings return 204
    and are NOT stored. On-shift pings save a `TechnicianLocation` and
    return 201 with the row id.
    """
    data = request.data or {}
    try:
        lat = Decimal(str(data.get('lat')))
        lon = Decimal(str(data.get('lon')))
    except (InvalidOperation, TypeError, ValueError):
        return Response({'detail': 'lat and lon are required'}, status=400)

    try:
        accuracy = int(data.get('accuracy') or 0)
    except (TypeError, ValueError):
        accuracy = 0

    when_raw = data.get('timestamp')
    when = timezone.now()
    if when_raw:
        try:
            parsed = datetime.fromisoformat(str(when_raw).replace('Z', '+00:00'))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.utc)
            when = parsed
        except (ValueError, TypeError):
            pass

    user = request.user

    if _is_off_shift(user, when):
        _audit(user, 'api_call', request, {
            'event': 'locations_dropped_offshift',
            'channel': 'mobile',
            'timestamp': when.isoformat(),
        })
        return Response(status=status.HTTP_204_NO_CONTENT)

    # Geofence-only mode: any active OrgFieldOpsSettings with
    # geofence_only_mode=True for an org whose geofence the tech is
    # inside means we never persist raw lat/lon. We log a GeofenceVisit
    # row instead and audit the privacy-preserving write.
    fence = _first_geofence_only_match(lat, lon)
    if fence is not None:
        visit = _open_or_extend_visit(user, fence, when)
        _audit(user, 'api_call', request, {
            'event': 'locations_geofence_only_write',
            'channel': 'mobile',
            'geofence_id': fence.id,
            'visit_id': visit.id,
        })
        return Response(
            {'id': visit.id, 'mode': 'geofence_only',
             'geofence_id': fence.id,
             'entered_at': visit.entered_at.isoformat()},
            status=status.HTTP_201_CREATED,
        )

    loc = TechnicianLocation.objects.create(
        tech=user,
        lat=lat,
        lon=lon,
        accuracy=accuracy,
        timestamp=when,
        source='mobile',
    )
    return Response(
        {'id': loc.id, 'timestamp': loc.timestamp.isoformat()},
        status=status.HTTP_201_CREATED,
    )


def _first_geofence_only_match(lat, lon):
    """Return the first ClientSiteGeofence whose org has geofence_only_mode=True
    AND that contains (lat, lon), or None."""
    org_ids = list(
        OrganizationFieldOpsSettings.objects
        .filter(geofence_only_mode=True)
        .values_list('organization_id', flat=True)
    )
    if not org_ids:
        return None
    qs = ClientSiteGeofence.objects.filter(
        active=True, organization_id__in=org_ids,
    )
    for fence in qs:
        if fence.contains(lat, lon):
            return fence
    return None


def _open_or_extend_visit(user, fence, when):
    """Reuse a visit row that doesn't have an exited_at yet, otherwise
    create a new one. (Exit-detection is handled by the auto-document
    engine; here we just keep the entered_at row up to date.)"""
    visit = GeofenceVisit.objects.filter(
        user=user, geofence=fence, exited_at__isnull=True,
    ).first()
    if visit is None:
        visit = GeofenceVisit.objects.create(
            user=user, geofence=fence, entered_at=when,
        )
    return visit


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def clock_in_view(request):
    """
    POST /api/mobile/v1/timeclock/clock-in/

    Body: `{organization_id?, location_id?, ticket_id?, project_id?, notes?,
            lat?, lon?, accuracy?}`.
    400 if the user already has an open clock-in.

    v3.17.452: optional `lat` / `lon` / `accuracy` for warn-but-allow
    geofence enforcement. If the destination organization has at least
    one active `ClientSiteGeofence` and the supplied point falls inside
    none of them, the clock-in still succeeds (201) but the response
    payload carries `geofence_override: true` so the mobile UI can show
    a confirmation toast. The audit log captures the override and the
    matched fence (if any).
    """
    user = request.user
    if TimeclockEntry.objects.filter(tech=user, clocked_out_at__isnull=True).exists():
        return Response(
            {'detail': 'You already have an open clock-in.'},
            status=400,
        )

    data = request.data or {}

    # GPS — optional. Bad coords return 400 instead of silently dropping
    # them, since the client deliberately attached them.
    gps_lat = gps_lon = None
    gps_accuracy = None
    if data.get('lat') is not None and data.get('lon') is not None:
        try:
            gps_lat = Decimal(str(data['lat']))
            gps_lon = Decimal(str(data['lon']))
        except (InvalidOperation, ValueError, TypeError):
            return Response({'detail': 'Invalid lat/lon'}, status=400)
        try:
            if data.get('accuracy') is not None:
                gps_accuracy = max(0, int(data['accuracy']))
        except (TypeError, ValueError):
            gps_accuracy = None

    # Every foreign key here arrives from the client, so each one is checked
    # against the technician's memberships before it is stored. Without this a
    # clock-in could be filed against any organization, ticket, project or
    # location by id — and TimeclockEntry.derived_time_entry means such an
    # entry can go on to become billable time against that client.
    #
    # Same shape as views_tickets, views_vault, views_dispatch and
    # views_workflows, which all validate organization_id this way.
    org_ids = list(accessible_org_ids(user))

    org_id, err = _scoped_fk(data.get('organization_id'), 'organization_id',
                             Organization.objects.filter(id__in=org_ids))
    if err:
        return err
    location_id, err = _scoped_fk(data.get('location_id'), 'location_id',
                                  Location.objects.filter(organization_id__in=org_ids))
    if err:
        return err
    ticket_id, err = _scoped_fk(data.get('ticket_id'), 'ticket_id',
                                Ticket.objects.filter(organization_id__in=org_ids))
    if err:
        return err
    project_id, err = _scoped_fk(data.get('project_id'), 'project_id',
                                 Project.objects.filter(client_org_id__in=org_ids))
    if err:
        return err

    entry = TimeclockEntry(
        tech=user,
        organization_id=org_id,
        location_id=location_id,
        ticket_id=ticket_id,
        project_id=project_id,
        notes=(data.get('notes') or '')[:2000],
        source='mobile',
    )
    entry.save()

    # Geofence: warn-but-allow. Only meaningful when GPS provided AND the
    # entry is scoped to an organization (so we know which fences to test).
    geofence_match_id = None
    geofence_override = False
    if gps_lat is not None and gps_lon is not None and entry.organization_id:
        try:
            active = ClientSiteGeofence.objects.filter(
                organization_id=entry.organization_id, active=True,
            )
            for fence in active:
                if fence.contains(gps_lat, gps_lon):
                    geofence_match_id = fence.id
                    break
            # If the org has at least one active fence and we matched none,
            # this is an outside-fence clock-in. Warn but allow.
            if geofence_match_id is None and active.exists():
                geofence_override = True
        except Exception:
            # Geofence subsystem missing/broken — don't block the clock-in.
            pass

    _audit(user, 'api_call', request, {
        'event': 'timeclock_in',
        'entry_id': entry.id,
        'gps_provided': gps_lat is not None,
        'gps_accuracy_m': gps_accuracy,
        'geofence_match_id': geofence_match_id,
        'geofence_override': geofence_override,
    })

    payload = _timeclock_payload(entry)
    payload['geofence_override'] = geofence_override
    payload['geofence_match_id'] = geofence_match_id
    return Response(payload, status=201)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def clock_out_view(request):
    """
    POST /api/mobile/v1/timeclock/clock-out/

    Body: `{notes?}`. 400 if the user has no open entry.
    """
    user = request.user
    entry = TimeclockEntry.objects.filter(
        tech=user, clocked_out_at__isnull=True,
    ).first()
    if entry is None:
        return Response({'detail': 'No open clock-in.'}, status=400)

    notes = ((request.data or {}).get('notes') or '').strip()
    if notes:
        entry.notes = (entry.notes + '\n' + notes).strip()[:2000]
    entry.clocked_out_at = timezone.now()
    entry.save()
    _audit(user, 'api_call', request, {'event': 'timeclock_out', 'entry_id': entry.id})
    return Response(_timeclock_payload(entry))


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def timeclock_me_view(request):
    """
    GET /api/mobile/v1/timeclock/me/

    Returns `{entry: ...}` with the user's open entry, or `{entry: null}`.
    """
    entry = TimeclockEntry.objects.filter(
        tech=request.user, clocked_out_at__isnull=True,
    ).first()
    return Response({'entry': _timeclock_payload(entry) if entry else None})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def active_ticket_view(request):
    """
    GET /api/mobile/v1/active-ticket/

    Returns the user's most recent unsubmitted TicketTimeEntry's ticket,
    or null if none. Used by the mobile app to pre-fill the ticket
    selector on Clock In.
    """
    try:
        from psa.models import TicketTimeEntry
    except Exception:
        return Response({'ticket': None})

    tte = (
        TicketTimeEntry.objects.filter(user=request.user, submission__isnull=True)
        .select_related('ticket', 'ticket__organization')
        .order_by('-started_at')
        .first()
    )
    if tte is None or tte.ticket is None:
        return Response({'ticket': None})

    t = tte.ticket
    return Response({
        'ticket': {
            'id': t.id,
            'ticket_number': getattr(t, 'ticket_number', '') or '',
            'subject': getattr(t, 'subject', '') or '',
            'organization_id': t.organization_id,
            'organization_name': t.organization.name if t.organization_id else '',
            'last_started_at': tte.started_at.isoformat() if tte.started_at else None,
        },
    })


def _timeclock_payload(entry: TimeclockEntry) -> dict:
    return {
        'id': entry.id,
        'tech_id': entry.tech_id,
        'organization_id': entry.organization_id,
        'location_id': entry.location_id,
        'ticket_id': entry.ticket_id,
        'project_id': entry.project_id,
        'clocked_in_at': entry.clocked_in_at.isoformat() if entry.clocked_in_at else None,
        'clocked_out_at': entry.clocked_out_at.isoformat() if entry.clocked_out_at else None,
        'duration_minutes': entry.duration_minutes,
        'source': entry.source,
        'notes': entry.notes,
    }
