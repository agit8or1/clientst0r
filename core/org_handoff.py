"""
Org handoff for links that name the customer they are about (v3.17.655).

Readiness is read across customers, but create / edit forms work in the
session's current organization. A link built for customer B carries
`?org=<B id>`; views wrapped in `org_handoff`:

* on GET, switch the session to B when the user may switch there (the same
  rule as the client switcher, `core.client_switcher.authorized_organizations`)
  and answer 404 when they may not — the form is never shown for another
  customer instead. The section gate (accounts SectionPermissionMiddleware,
  e.g. vault_view for /vault/) is re-checked for B before switching;
* on POST, refuse to save when the form was opened for a different customer
  than the session is in now (another tab switched it meanwhile). The form
  posts the customer it was rendered for as `_org`
  (templates/core/_form_org.html); `?org=` on the action URL counts too.

Nothing is ever saved by the handoff itself.
"""
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect

ORG_PARAM = 'org'
POST_FIELD = '_org'


def _as_id(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    if not raw.isdigit() or len(raw) > 12:
        raise Http404
    return int(raw)


def switch_session_org(request, org):
    """Make `org` the session's current customer (access already checked).
    The same steps `accounts.views.switch_organization` takes."""
    from .client_switcher import record_recent_client
    request.session['current_organization_id'] = org.id
    request.session.pop('global_view_mode', None)
    request.session.modified = True
    request.current_organization = org
    record_recent_client(request.user, org)


def _check_section_perm(request, org):
    """SectionPermissionMiddleware already gated this path for the customer
    the session was in; gate it again for the customer we switch to, so a
    link can't carry someone into a section their role there doesn't grant.
    Answers 404 (like an unknown customer) without switching."""
    from django.core.exceptions import PermissionDenied
    from accounts.middleware import SectionPermissionMiddleware
    gate = SectionPermissionMiddleware(None)
    perm = gate._required_perm(request.path)
    if perm is None:
        return
    previous = getattr(request, 'current_organization', None)
    request.current_organization = org
    try:
        gate._check(request, request.user, perm)
    except PermissionDenied:
        raise Http404
    finally:
        request.current_organization = previous


def with_org(url, org, **params):
    """`url` plus `?org=<id>` and any extra query params (fragment kept)."""
    base, _, fragment = url.partition('#')
    query = {ORG_PARAM: getattr(org, 'pk', org)}
    query.update({k: v for k, v in params.items() if v not in (None, '')})
    sep = '&' if '?' in base else '?'
    return base + sep + urlencode(query) + (f'#{fragment}' if fragment else '')


def org_handoff(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        current = getattr(request, 'current_organization', None)
        if request.method == 'POST':
            expected = _as_id(request.POST.get(POST_FIELD)) or _as_id(request.GET.get(ORG_PARAM))
            if expected is not None and (current is None or current.pk != expected):
                now = current.name if current else 'Global View'
                messages.error(
                    request,
                    f'Nothing was saved: this form was opened for another customer, and you are '
                    f'now working in {now}. The form has been reopened for the customer it was for.')
                query = request.GET.copy()
                query[ORG_PARAM] = str(expected)
                return redirect(f'{request.path}?{query.urlencode()}')
            return view(request, *args, **kwargs)

        target_id = _as_id(request.GET.get(ORG_PARAM))
        if target_id is not None:
            if current is None or current.pk != target_id:
                from .client_switcher import authorized_organizations
                org = authorized_organizations(request).filter(pk=target_id).first()
                if org is None:
                    raise Http404
                _check_section_perm(request, org)
                switch_session_org(request, org)
                messages.info(request, f'Switched to {org.name}.')
            request.org_handoff = request.current_organization
        return view(request, *args, **kwargs)
    return wrapper
