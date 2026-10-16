"""
Mobile API tickets endpoints (v3.17.349).
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import user_has_perm
from psa.visibility import customer_visible_tickets, is_msp_staff, visible_comments

from .scoping import accessible_org_ids


def _serialize_ticket(t, *, detail=False, viewer=None):
    # v3.17.477 — surface organization_name / assigned_to_name / number /
    # updated_at so the mobile list rows render without extra round trips.
    org_name = None
    if t.organization_id and getattr(t, 'organization', None) is not None:
        org_name = getattr(t.organization, 'name', None)
    assignee_name = None
    if t.assigned_to_id and getattr(t, 'assigned_to', None) is not None:
        full = (t.assigned_to.get_full_name() or '').strip()
        assignee_name = full or t.assigned_to.username
    out = {
        'id': t.id,
        'number': t.ticket_number,
        'ticket_number': t.ticket_number,
        'subject': t.subject,
        'status': t.status.name if t.status_id else None,
        'status_id': t.status_id,
        'priority': t.priority.code if t.priority_id else None,
        'priority_id': t.priority_id,
        'organization_id': t.organization_id,
        'organization_name': org_name,
        'assigned_to_id': t.assigned_to_id,
        'assigned_to_name': assignee_name,
        'created_at': t.created_at.isoformat() if t.created_at else None,
        'updated_at': t.updated_at.isoformat()
            if getattr(t, 'updated_at', None) else None,
    }
    if detail:
        # v3.17.479 — bill rollup. Sum all TicketTimeEntry rows for this
        # ticket and surface total / billable / non-billable minutes so
        # the mobile detail screen can render the totals card without a
        # second round trip. When the client has an active block_hours
        # contract, also include a `contract` sub-object with used /
        # remaining / type so the techs can see how much bucket is left.
        total_minutes = 0
        billable_minutes = 0
        try:
            for e in t.time_entries.all():
                total_minutes += e.duration_minutes or 0
                if e.is_billable:
                    billable_minutes += e.duration_minutes or 0
        except Exception:
            pass

        contract_obj = None
        try:
            from psa.models import Contract
            c = Contract.for_ticket(t)
            if c is not None:
                total_alw = c.effective_total_minutes()
                used = c.hours_used_minutes or 0
                # Unlimited contracts (total_hours == 0) get remaining=None.
                if total_alw:
                    remaining = max(0, total_alw - used)
                else:
                    total_alw = None
                    remaining = None
                contract_obj = {
                    'id': c.id,
                    'name': c.name,
                    'type': c.contract_type,
                    'total_minutes': total_alw,
                    'used_minutes': used,
                    'remaining_minutes': remaining,
                }
        except Exception:
            contract_obj = None

        out.update({
            'description': t.description,
            'requester_name': t.requester_name,
            'requester_email': t.requester_email,
            'is_terminal': t.status.is_terminal if t.status_id else False,
            'resolution_due_at': t.resolution_due_at.isoformat()
                if getattr(t, 'resolution_due_at', None) else None,
            'total_minutes': total_minutes,
            'billable_minutes': billable_minutes,
            'non_billable_minutes': max(0, total_minutes - billable_minutes),
            'contract': contract_obj,
            'comments': [
                {
                    'id': c.id,
                    'body': c.body,
                    'is_internal': c.is_internal,
                    'is_system': c.is_system,
                    'author_id': c.author_id,
                    'author_name': c.author_name,
                    'created_at': c.created_at.isoformat() if c.created_at else None,
                }
                for c in (visible_comments(t, viewer) if viewer is not None
                          else t.comments.all()).order_by('created_at')
            ],
        })
    return out


@api_view(['GET', 'POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def ticket_list_view(request):
    """
    GET  /api/mobile/v1/tickets/?status=&priority=&assigned_to_me=true&organization_id=&search=&page=
    POST /api/mobile/v1/tickets/  (create)
    """
    from psa.models import Ticket, TicketStatus, TicketPriority, TicketType, Queue

    org_ids = accessible_org_ids(request.user)

    if request.method == 'POST':
        # v3.17.477 — explicit per-role gate. Default Owner / Admin /
        # Tech roles get tickets_create=True so the rank-and-file paths
        # keep working; Read-Only / Documentation Writer get blocked.
        if not user_has_perm(request.user, 'tickets_create'):
            return Response(
                {'detail': "You don't have permission to file tickets."},
                status=403,
            )
        data = request.data or {}
        org_id = data.get('organization_id')
        try:
            org_id = int(org_id) if org_id is not None else None
        except (TypeError, ValueError):
            return Response({'detail': 'organization_id must be an integer'}, status=400)
        if not org_id or org_id not in org_ids:
            return Response({'detail': 'organization_id required + must be accessible'}, status=403)

        subject = (data.get('subject') or '').strip()
        if not subject:
            return Response({'detail': 'subject is required'}, status=400)

        # Pick reasonable defaults
        status_obj = (
            TicketStatus.objects.filter(slug='new').first()
            or TicketStatus.objects.first()
        )
        priority_obj = (
            TicketPriority.objects.filter(code='P3').first()
            or TicketPriority.objects.first()
        )
        type_obj = TicketType.objects.first()
        queue_obj = Queue.objects.first()
        if not all([status_obj, priority_obj, type_obj, queue_obj]):
            return Response(
                {'detail': 'PSA seed data missing — cannot create ticket'},
                status=409,
            )

        ticket = Ticket.objects.create(
            organization_id=org_id,
            subject=subject,
            description=data.get('description', ''),
            status=status_obj,
            priority=priority_obj,
            ticket_type=type_obj,
            queue=queue_obj,
            source='api',
            requester_name=data.get('requester_name', ''),
            requester_email=data.get('requester_email', ''),
        )
        return Response(_serialize_ticket(ticket, detail=True, viewer=request.user), status=201)

    # GET
    qs = Ticket.objects.select_related(
        'status', 'priority', 'organization', 'assigned_to',
    )
    # v3.17.477 — tickets_view_all unlocks cross-org reads. Without it
    # we keep the membership scope.
    # tickets_view_all is an MSP-staff capability; customer users stay in
    # their own customers and see only tickets shared with the client.
    if not (is_msp_staff(request.user) and user_has_perm(request.user, 'tickets_view_all')):
        qs = qs.filter(organization_id__in=org_ids)
    qs = customer_visible_tickets(qs, request.user)

    status_filter = request.query_params.get('status')
    if status_filter:
        if status_filter == 'open':
            qs = qs.filter(status__is_terminal=False)
        elif status_filter == 'closed':
            qs = qs.filter(status__is_terminal=True)
        else:
            qs = qs.filter(status__slug=status_filter)

    priority_filter = request.query_params.get('priority')
    if priority_filter:
        # v3.17.474 (bug from dashboard critical tile) — mobile dashboard
        # sends ?priority=critical but TicketPriority rows use P1..P4
        # codes, so the previous filter returned zero. Accept friendly
        # labels and map them to codes; fall back to literal match for
        # raw P-codes / priority names.
        label_to_code = {
            'critical': 'P1', 'urgent': 'P1',
            'high':     'P2',
            'medium':   'P3', 'normal': 'P3',
            'low':      'P4',
        }
        raw = priority_filter.strip().lower()
        code = label_to_code.get(raw, raw.upper() if len(raw) <= 4 else raw)
        qs = qs.filter(
            Q(priority__code__iexact=code)
            | Q(priority__name__iexact=raw)
        )

    if request.query_params.get('assigned_to_me') == 'true':
        qs = qs.filter(assigned_to=request.user)

    org_filter = request.query_params.get('organization_id')
    if org_filter:
        try:
            oid = int(org_filter)
            if oid in org_ids:
                qs = qs.filter(organization_id=oid)
            else:
                qs = qs.none()
        except ValueError:
            pass

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(subject__icontains=search)
            | Q(ticket_number__icontains=search)
            | Q(description__icontains=search)
        )

    qs = qs.order_by('-created_at')

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
        'results': [_serialize_ticket(t) for t in rows],
    })


@api_view(['GET', 'PATCH'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def ticket_detail_view(request, pk: int):
    """
    GET   /api/mobile/v1/tickets/<id>/      — detail with comments
    PATCH /api/mobile/v1/tickets/<id>/      — partial update (status / priority / assignee)
    """
    from psa.models import Ticket, TicketStatus, TicketPriority

    org_ids = accessible_org_ids(request.user)
    base_qs = Ticket.objects.select_related(
        'status', 'priority', 'organization', 'assigned_to',
    )
    if not (is_msp_staff(request.user) and user_has_perm(request.user, 'tickets_view_all')):
        base_qs = base_qs.filter(organization_id__in=org_ids)
    base_qs = customer_visible_tickets(base_qs, request.user)
    try:
        ticket = base_qs.get(pk=pk)
    except Ticket.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'GET':
        return Response(_serialize_ticket(ticket, detail=True, viewer=request.user))

    # PATCH
    data = request.data or {}

    # v3.17.450: also accept `status` and `priority` as friendly strings.
    # The mobile UI surfaces statuses as `'open'` / `'in_progress'` /
    # `'closed'` and priorities as `'low'` / `'medium'` / `'high'` /
    # `'critical'`. Without these branches the mobile PATCH silently
    # no-op'd because only `status_id` / `priority_id` keys were honored.
    if 'status_id' in data:
        try:
            ticket.status = TicketStatus.objects.get(pk=int(data['status_id']))
        except (TicketStatus.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'invalid status_id'}, status=400)
    elif 'status' in data:
        raw = (str(data['status']) or '').strip().lower()
        # Mobile sends `in_progress` and friends; DB slugs use dashes.
        slug = raw.replace('_', '-')
        match = (TicketStatus.objects.filter(slug=slug).first()
                 or TicketStatus.objects.filter(slug__iexact=raw).first()
                 or TicketStatus.objects.filter(name__iexact=raw).first())
        if match is None:
            return Response({'detail': f'unknown status: {raw}'}, status=400)
        ticket.status = match
    if 'priority_id' in data:
        try:
            ticket.priority = TicketPriority.objects.get(pk=int(data['priority_id']))
        except (TicketPriority.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'invalid priority_id'}, status=400)
    elif 'priority' in data:
        raw = (str(data['priority']) or '').strip().lower()
        # Mobile labels → P-codes. Falls through to direct code/name match
        # for backends that already use 'P1' / 'urgent' / etc.
        label_to_code = {
            'critical': 'P1', 'urgent': 'P1',
            'high':     'P2',
            'medium':   'P3', 'normal': 'P3',
            'low':      'P4',
        }
        candidate_codes = [label_to_code[raw]] if raw in label_to_code else [raw.upper(), raw]
        match = None
        for code in candidate_codes:
            match = TicketPriority.objects.filter(code__iexact=code).first()
            if match:
                break
        if match is None:
            match = TicketPriority.objects.filter(name__iexact=raw).first()
        if match is None:
            return Response({'detail': f'unknown priority: {raw}'}, status=400)
        ticket.priority = match
    # v3.17.479 — accept `resolution_due_at` (and the convenience alias
    # `due_at`) so users can schedule a ticket on a calendar day from
    # mobile. Pass `null` / empty to clear. ISO 8601 input; gated on
    # tickets_edit.
    if 'resolution_due_at' in data or 'due_at' in data:
        if not user_has_perm(request.user, 'tickets_edit'):
            return Response(
                {'detail': "You don't have permission to edit tickets."},
                status=403,
            )
        raw = data.get('resolution_due_at', data.get('due_at'))
        if raw in (None, ''):
            ticket.resolution_due_at = None
        else:
            from datetime import datetime
            from django.utils import timezone as _tz
            try:
                parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            except (ValueError, TypeError):
                return Response(
                    {'detail': 'resolution_due_at must be ISO 8601'},
                    status=400,
                )
            if _tz.is_naive(parsed):
                parsed = _tz.make_aware(parsed)
            ticket.resolution_due_at = parsed

    if 'assigned_to_id' in data:
        # v3.17.477 — gate re-assignment on tickets_assign. Self-claim
        # (assigning to yourself) is allowed even without the perm so
        # techs can still pick up unowned tickets.
        from django.contrib.auth.models import User
        v = data['assigned_to_id']
        target_id = None
        if v not in (None, '', 0):
            try:
                target_id = int(v)
            except (TypeError, ValueError):
                return Response({'detail': 'invalid assigned_to_id'}, status=400)
        is_self_claim = target_id is not None and target_id == request.user.id
        is_unassign = target_id is None
        if not (is_self_claim or is_unassign):
            if not user_has_perm(request.user, 'tickets_assign'):
                return Response(
                    {'detail': "You don't have permission to reassign tickets."},
                    status=403,
                )
        if target_id is None:
            ticket.assigned_to = None
        else:
            try:
                ticket.assigned_to = User.objects.get(pk=target_id)
            except User.DoesNotExist:
                return Response({'detail': 'invalid assigned_to_id'}, status=400)
    ticket.save()
    return Response(_serialize_ticket(ticket, detail=True, viewer=request.user))


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def ticket_comment_view(request, pk: int):
    """POST /api/mobile/v1/tickets/<id>/comments/ — add a comment."""
    from psa.models import Ticket, TicketComment

    org_ids = accessible_org_ids(request.user)
    try:
        ticket = customer_visible_tickets(
            Ticket.objects.filter(organization_id__in=org_ids), request.user).get(pk=pk)
    except Ticket.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    body = (request.data.get('body') or '').strip()
    if not body:
        return Response({'detail': 'body is required'}, status=400)

    is_internal = bool(request.data.get('is_internal', False))
    comment = TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=body,
        is_internal=is_internal,
        source='api',
    )
    return Response({
        'id': comment.id,
        'body': comment.body,
        'is_internal': comment.is_internal,
        'author_id': comment.author_id,
        'created_at': comment.created_at.isoformat() if comment.created_at else None,
    }, status=201)


@api_view(['GET', 'POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def ticket_time_view(request, pk: int):
    """
    GET  /api/mobile/v1/tickets/<id>/time/  — list time entries on this ticket
    POST /api/mobile/v1/tickets/<id>/time/  — log time on this ticket (v3.17.454)

    POST body (one of two shapes):
      * Manual entry: `{duration_minutes, notes?, is_billable?, started_at?}`
        — `started_at` defaults to (now - duration). `ended_at` set to now.
      * Running timer: `{started_at, ended_at?, notes?, is_billable?}`
        — if `ended_at` omitted, server computes from `started_at` and now.
    """
    from psa.models import Ticket, TicketTimeEntry
    from django.utils import timezone
    from datetime import datetime, timedelta

    org_ids = accessible_org_ids(request.user)
    try:
        ticket = customer_visible_tickets(
            Ticket.objects.filter(organization_id__in=org_ids), request.user).get(pk=pk)
    except Ticket.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'GET':
        entries = (TicketTimeEntry.objects
                   .filter(ticket=ticket)
                   .order_by('-started_at')[:50])
        return Response({
            'count': entries.count() if hasattr(entries, 'count')
                     else len(list(entries)),
            'results': [_serialize_time_entry(t) for t in entries],
        })

    # POST
    data = request.data or {}

    def _parse_dt(raw):
        if raw is None:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.utc)
        return parsed

    started_at = _parse_dt(data.get('started_at'))
    ended_at = _parse_dt(data.get('ended_at'))

    duration_minutes = data.get('duration_minutes')
    if duration_minutes is not None:
        try:
            duration_minutes = max(0, int(duration_minutes))
        except (TypeError, ValueError):
            return Response({'detail': 'invalid duration_minutes'}, status=400)

    if duration_minutes is None and started_at is None:
        return Response(
            {'detail': 'provide either duration_minutes or started_at'},
            status=400,
        )

    now = timezone.now()
    if started_at is None:
        started_at = now - timedelta(minutes=duration_minutes or 0)
    if ended_at is None:
        if duration_minutes is not None:
            ended_at = started_at + timedelta(minutes=duration_minutes)
        else:
            ended_at = now
    if duration_minutes is None:
        duration_minutes = max(0, int((ended_at - started_at).total_seconds() // 60))

    is_billable = bool(data.get('is_billable', True))
    notes = (data.get('notes') or '').strip()[:2000]
    role_code = str(data.get('role_code') or '').strip()[:40]

    entry = TicketTimeEntry.objects.create(
        ticket=ticket,
        user=request.user,
        started_at=started_at,
        ended_at=ended_at,
        duration_minutes=duration_minutes,
        is_billable=is_billable,
        notes=notes,
        role_code=role_code,
    )
    return Response(_serialize_time_entry(entry), status=201)


def _serialize_time_entry(t):
    return {
        'id': t.id,
        'ticket_id': t.ticket_id,
        'user_id': t.user_id,
        'started_at': t.started_at.isoformat() if t.started_at else None,
        'ended_at': t.ended_at.isoformat() if t.ended_at else None,
        'duration_minutes': t.duration_minutes,
        'is_billable': t.is_billable,
        'role_code': t.role_code,
        'notes': t.notes,
    }
