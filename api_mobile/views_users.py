"""
Mobile API — users endpoints (v3.17.477).

Currently exposes a single endpoint: `GET /users/assignable/`. The mobile
ticket-detail screen surfaces an assignee picker; this endpoint returns
the users the caller can reassign a ticket to.

Without `tickets_assign`, the caller can only "self-claim" a ticket
(assign it to themselves), so the endpoint returns just the caller.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models import Q
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import user_has_perm
from psa.visibility import is_msp_staff, msp_technicians


def _serialize_user(u) -> dict:
    full = (u.get_full_name() or '').strip() or u.username
    return {
        'id': u.id,
        'username': u.username,
        'full_name': full,
        'email': u.email or '',
    }


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def assignable_users_view(request):
    """
    GET /api/mobile/v1/users/assignable/?search=

    Returns the users the caller can assign tickets to — MSP technicians
    only (a customer's own users are never assignees):
      * without `tickets_assign`: the caller themselves if they are a
        technician (self-claim), otherwise nobody,
      * with `tickets_assign`: every active MSP technician, when the caller
        is MSP staff; a customer user gets an empty list.
    """
    search = (request.query_params.get('search') or '').strip()

    if not user_has_perm(request.user, 'tickets_assign'):
        # Self-claim only — no picker. Mobile UI hides the control
        # entirely when this returns a single row that's the caller.
        rows = [request.user] if is_msp_staff(request.user) else []
    elif is_msp_staff(request.user):
        rows = list(msp_technicians()[:200])
    else:
        # Customer users never see the MSP's technician roster.
        rows = []

    if search:
        q = search.lower()
        rows = [
            u for u in rows
            if q in u.username.lower()
            or q in (u.get_full_name() or '').lower()
            or q in (u.email or '').lower()
        ]

    return Response({
        'count': len(rows),
        'results': [_serialize_user(u) for u in rows],
    })
