"""Refuse a form save made under a different client than the form was opened for.

The current client lives in the session, so it is shared by every tab. A form
opened for client A, left open while the user switches to client B in another
tab, and then saved, would be handled under B: a "new asset" form creates the
asset at B, and edit views scoped to the current client fail in ways that lose
the edits.

``static/js/form_guard.js`` stamps POST forms on the page with a hidden
``_org_context`` field holding the client the page was rendered for (empty in
Global View). When a POST carries that field and it no longer matches the
session's current client, nothing reaches the view: the user gets a 409 page
naming both clients, with a way back to the form and a way to switch back.

A POST without the field — API clients, tests, forms the script did not stamp
— is not affected.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import render

FIELD = '_org_context'
_FORM_TYPES = ('application/x-www-form-urlencoded', 'multipart/form-data')


def _visible_org(request, org_id):
    """The organization `org_id` names, if this user may see it."""
    from core.models import Organization
    if not str(org_id).isdigit():
        return None
    org = Organization.objects.filter(pk=int(org_id)).first()
    if org is None:
        return None
    user = request.user
    if user.is_superuser or getattr(request, 'is_staff_user', False):
        return org
    memberships = getattr(user, 'memberships', None)
    if memberships is not None and memberships.filter(organization=org, is_active=True).exists():
        return org
    return None


class OrgContextGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != 'POST' or request.content_type not in _FORM_TYPES:
            return None
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        # Views that read the raw body (webhooks) are csrf-exempt; reading
        # request.POST here would consume a multipart body before they can.
        if getattr(view_func, 'csrf_exempt', False):
            return None
        posted = request.POST.get(FIELD)
        if posted is None:
            return None
        current = getattr(request, 'current_organization', None)
        current_id = str(current.pk) if current is not None else ''
        posted = posted.strip()
        if posted == current_id:
            return None

        opened_for = _visible_org(request, posted)
        opened_name = opened_for.name if opened_for else ('Global View' if not posted else 'another client')
        current_name = current.name if current is not None else 'Global View'
        message = (f'This form was opened for {opened_name}, but you have since switched to '
                   f'{current_name}. Nothing was saved.')
        wants_json = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
                      or 'application/json' in request.headers.get('accept', ''))
        if wants_json:
            return JsonResponse({'error': message, 'code': 'org_context_changed'}, status=409)
        return render(request, 'core/org_context_mismatch.html', {
            'message': message,
            'opened_for': opened_for,
            'opened_global': not posted,
            'current_name': current_name,
            'return_path': request.path,
        }, status=409)
