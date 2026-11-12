"""Inventory is MSP-internal (roles & permissions program, authz-tech).

Stock levels, unit cost, reorder links, storage locations and tools are the
MSP's own operations data. `/inventory/` was outside the section middleware
with no flag, so every member of the selected customer could read it.
MSP staff = superusers and users whose profile is Staff; their existing
per-customer checks in the views still apply.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied


def is_inventory_staff(user) -> bool:
    if user is None or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    try:
        return bool(profile is not None and profile.is_staff_user())
    except Exception:
        return False


def msp_staff_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        # Anonymous requests reach the view's @login_required redirect.
        if request.user.is_authenticated and not is_inventory_staff(request.user):
            raise PermissionDenied('Inventory is available to MSP staff only.')
        return view(request, *args, **kwargs)
    return wrapped
