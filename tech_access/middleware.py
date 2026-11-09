"""
Counts reads for theft detection and enforces containment, on every route
that opens a ticket or returns a file — web UI, REST API and mobile API —
without each view having to remember to.

Ticket routes are recognised by their URL kwargs: any route with a
`ticket_number`, and the mobile API's `tickets/<pk>/`. A response is an
export when it is sent as an attachment.

Token-authenticated API requests only have their user after the view has
run (DRF authenticates inside the view), so containment is checked again
on the response: a contained identity gets 403 instead of the body.
"""
from __future__ import annotations

import logging

from django.http import HttpResponseForbidden

from . import detection

logger = logging.getLogger('tech_access')

MOBILE_TICKET_ROUTES = {'api_mobile:ticket_detail', 'api_mobile:ticket_comment'}
EXPORT_HINTS = ('export', 'csv', 'download', 'backup')
REFUSAL = ('Your access is contained pending review by an administrator after unusually broad reads. '
           'Tickets assigned to you still open.')


def _channel(request):
    path = request.path
    if path.startswith('/api/mobile') or path.startswith('/api_mobile'):
        return 'mobile'
    return 'api' if path.startswith('/api/') else 'ui'


def _ticket(match):
    if match is None:
        return None
    from psa.models import Ticket
    kw = match.kwargs or {}
    if 'ticket_number' in kw:
        return Ticket.objects.filter(ticket_number=kw['ticket_number']).only(
            'pk', 'organization_id', 'assigned_to_id').first()
    if match.view_name in MOBILE_TICKET_ROUTES and 'pk' in kw:
        return Ticket.objects.filter(pk=kw['pk']).only('pk', 'organization_id', 'assigned_to_id').first()
    return None


def _looks_like_export(match):
    name = (match.view_name or '') if match else ''
    return any(h in name for h in EXPORT_HINTS)


def _match(request):
    from django.urls import Resolver404, resolve
    try:
        return resolve(request.path_info)
    except Resolver404:
        return None


def _relevant(match):
    """Only ticket and export routes cost a query; everything else passes."""
    if match is None:
        return False
    kw = match.kwargs or {}
    return ('ticket_number' in kw or match.view_name in MOBILE_TICKET_ROUTES or _looks_like_export(match))


class ReadTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = _match(request)
        if not _relevant(match):
            return self.get_response(request)
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and detection.contained(user):
            if _looks_like_export(match):
                return HttpResponseForbidden(REFUSAL)
            ticket = _ticket(match)
            if ticket is not None and ticket.assigned_to_id != user.pk:
                return HttpResponseForbidden(REFUSAL)
        response = self.get_response(request)
        try:
            return self._after(request, response, match)
        except Exception:  # detection must never break a page
            logger.exception('read tracking failed')
            return response

    def _after(self, request, response, match):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or response.status_code >= 400:
            return response
        ticket = _ticket(match)
        disposition = response.get('Content-Disposition', '') if hasattr(response, 'get') else ''
        is_export = 'attachment' in disposition.lower()
        if detection.contained(user):
            # API token users are only known now (see module docstring).
            if is_export or _looks_like_export(match) or (
                    ticket is not None and ticket.assigned_to_id != user.pk):
                return HttpResponseForbidden(REFUSAL)
        if request.method not in ('GET', 'HEAD'):
            return response
        channel = _channel(request)
        if ticket is not None:
            detection.record(user, 'ticket', ticket.pk, ticket.organization_id, channel)
        if is_export:
            detection.record(user, 'export', detection.export_key(request), None, channel)
        return response
