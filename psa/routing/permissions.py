"""Who may do what with ticket routing.

Three separate role flags (accounts.RoleTemplate):
  routing_manage_rules  settings, customer overrides, rules, on-call shifts
  routing_test          the Test routing page (read-only dry run)
  routing_override      accept / reject suggestions on a ticket

All three require an MSP technician; customer users never qualify, whatever
their role says. Superusers hold all three. None of them lets routing (or
anyone through routing) start a remote session or authorise an endpoint action:
this app has no code path that does either.
"""
from django.core.exceptions import PermissionDenied

PERM_MANAGE = 'routing_manage_rules'
PERM_TEST = 'routing_test'
PERM_OVERRIDE = 'routing_override'


def has_routing_perm(user, perm) -> bool:
    from psa.visibility import is_msp_staff
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if not is_msp_staff(user):
        return False
    if user.is_superuser:
        return True
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, perm)


def can_manage(user):
    return has_routing_perm(user, PERM_MANAGE)


def can_test(user):
    return has_routing_perm(user, PERM_TEST)


def can_override(user):
    return has_routing_perm(user, PERM_OVERRIDE)


def require_routing_perm(perm):
    from functools import wraps

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_routing_perm(request.user, perm):
                raise PermissionDenied(f"You don't have the '{perm}' permission.")
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
