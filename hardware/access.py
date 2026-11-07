"""
Access rules for the hardware module.

* Inventory records are client data. Every lookup goes through
  ``org_get(Model, request, ...)``, which filters by the *current* client
  and answers 404 for anything else — including records of other clients the
  user could otherwise reach. Staff work one client at a time, exactly as in
  the rest of the application.
* Role flags are the existing asset flags: ``assets_view`` to read,
  ``assets_create`` to add devices / import, ``assets_edit`` to document
  ports, cables, VLANs and placements, ``assets_delete`` to delete.
* The catalog is global. Reading it needs ``assets_view`` somewhere;
  changing it (models, layouts, imports) needs catalog management rights
  (``assets.views_custom.can_manage_asset_catalog``), because a change there
  is seen by every client.
"""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect

from accounts.permission_utils import user_has_org_perm, user_has_perm
from core.middleware import get_request_organization


def current_org(request):
    return get_request_organization(request)


def can(request, perm, org=None):
    org = org or current_org(request)
    return org is not None and user_has_org_perm(request.user, org, perm)


def can_manage_catalog(user):
    from assets.views_custom import can_manage_asset_catalog
    return can_manage_asset_catalog(user)


def _is_json(request):
    return request.path.startswith('/hardware/api/') or request.headers.get('Accept', '').startswith('application/json')


def org_view(perm='assets_view'):
    """Require a selected client and `perm` in it. Passes `org` to the view."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if _is_json(request):
                    return JsonResponse({'error': 'Sign in required.'}, status=401)
                return redirect(f'/account/login/?next={request.path}')
            org = current_org(request)
            if org is None:
                if _is_json(request):
                    return JsonResponse({'error': 'Select a client first.'}, status=400)
                messages.info(request, 'Select a client to see its hardware inventory.')
                return redirect('core:dashboard')
            if not user_has_org_perm(request.user, org, perm):
                if _is_json(request):
                    return JsonResponse({'error': f'You need the {perm.replace("_", " ")} permission here.'},
                                        status=403)
                raise PermissionDenied(f'You need the {perm} permission for {org}.')
            return view(request, *args, org=org, **kwargs)
        return wrapper
    return deco


def catalog_view(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/account/login/?next={request.path}')
        if not (user_has_perm(request.user, 'assets_view') or can_manage_catalog(request.user)):
            raise PermissionDenied('You need permission to view assets.')
        return view(request, *args, **kwargs)
    return wrapper


def catalog_admin(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/account/login/?next={request.path}')
        if not can_manage_catalog(request.user):
            if _is_json(request):
                return JsonResponse({'error': 'Only catalog administrators can change shared catalog templates.'},
                                    status=403)
            raise PermissionDenied('Only MSP staff who can edit assets for every client may change the shared catalog.')
        return view(request, *args, **kwargs)
    return wrapper


def org_get(model, org, **lookup):
    """get_object_or_404 bounded to the client. Never crosses tenants."""
    return get_object_or_404(model, organization=org, **lookup)


def org_filter_ids(model, org, ids):
    """The subset of `ids` that exist at this client; raise if any don't."""
    ids = [int(i) for i in ids if str(i).strip().isdigit()]
    objs = list(model.objects.filter(organization=org, pk__in=ids))
    if len(objs) != len(set(ids)):
        raise Http404('One or more records were not found for this client.')
    order = {pk: i for i, pk in enumerate(ids)}
    return sorted(objs, key=lambda o: order[o.pk])
