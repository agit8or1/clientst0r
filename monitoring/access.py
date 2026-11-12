"""Role flags for monitoring and asset writes (roles & permissions program, authz-tech).

`core.decorators.require_write` passes anyone holding *any* create flag in
the selected customer (vault, assets, docs, files or monitoring), so the
built-in Editor, whose role leaves out monitoring_delete, could delete
racks, subnets and monitors, and a role with only files_upload could
create them. The JSON rack/patch-panel endpoints had no write check at all.

`monitoring_perm(flag, owner=...)` checks the flag in the customer that owns
the record (`owner` resolves it from the URL kwargs), or in the selected
customer for creates. It also closes the unscoped "Global View" fallback
the views use when no customer is selected: only cross-tenant users
(superusers and MSP staff) get it.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse

from accounts.permission_utils import has_perm_for_org
from core.middleware import get_request_organization
from core.tenancy import is_cross_tenant_user


def owner(model, path='organization_id', kwarg='pk'):
    """Resolve the owning customer id of `model` from the view kwarg."""
    def resolve(kwargs):
        pk = kwargs.get(kwarg)
        if pk is None:
            return None
        m = model
        if isinstance(m, str):  # 'app_label.Model', resolved lazily
            from django.apps import apps
            m = apps.get_model(m)
        return m.objects.filter(pk=pk).values_list(path, flat=True).first()
    return resolve


def monitoring_perm(flags=None, owner=None, json=False):
    """`flags`: a flag, a tuple of flags, a {method: flag(s)} dict, or None
    (only the Global View guard)."""
    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            org = get_request_organization(request)
            if org is None and not is_cross_tenant_user(request):
                raise Http404('Select a customer first.')
            wanted = flags.get(request.method) if isinstance(flags, dict) else flags
            if wanted:
                if isinstance(wanted, str):
                    wanted = (wanted,)
                org_id = owner(kwargs) if owner else (org.pk if org else None)
                if org_id is not None or owner is None:
                    for flag in wanted:
                        if not has_perm_for_org(request.user, org_id, flag):
                            if org is not None and owner is not None and org_id != org.pk:
                                # Another customer's record: the same 404 the
                                # scoped lookup gives, not a 403 that
                                # confirms it exists.
                                raise Http404('Not found.')
                            if json:
                                return JsonResponse(
                                    {'success': False,
                                     'error': f'Your role does not allow this here ({flag}).'},
                                    status=403)
                            raise PermissionDenied(f'Your role does not allow this here ({flag}).')
            return view(request, *args, **kwargs)
        return wrapped
    return deco


# The helper is not monitoring-specific; assets/ uses it under this name.
org_flag_required = monitoring_perm
