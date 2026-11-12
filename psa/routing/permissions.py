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


def has_routing_perm(user, perm, organization=None) -> bool:
    """`perm` for an MSP technician. With `organization` (a customer, or its
    pk) the permission must hold AT that customer, inside the technician's
    client scope (accounts.permission_utils.user_has_org_perm); without one
    it is the page-level capability."""
    from psa.visibility import is_msp_staff
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if not is_msp_staff(user):
        return False
    if user.is_superuser:
        return True
    if organization is not None:
        from accounts.permission_utils import user_has_org_perm
        return user_has_org_perm(user, organization, perm)
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, perm)


def require_routing_org(user, organization, perm):
    """PermissionDenied unless `perm` holds for this customer's routing
    (an MSP-wide object, organization None, needs the capability only)."""
    if not has_routing_perm(user, perm, organization):
        raise PermissionDenied(f"You don't have the '{perm}' permission for this customer.")


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
