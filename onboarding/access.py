"""Who may open onboarding sessions.

Every decision is per organization through the role-permission helpers
(accounts.permission_utils): the wizard permission `manage_customer_onboarding`
must be held at the session's organization, or at the customer it is about.
A session is never reachable by id alone: views resolve it with
`session_for_user`, which answers 404 for anything outside the caller's reach
(no hint that the id exists).
"""
from django.db.models import Q
from django.http import Http404

PERM = 'manage_customer_onboarding'


def is_staff(user) -> bool:
    from psa.visibility import is_msp_staff
    return bool(user is not None and user.is_authenticated and (user.is_superuser or is_msp_staff(user)))


def can_use(user, organization) -> bool:
    """May `user` run onboarding wizards at `organization` (an Organization or pk)?"""
    from accounts.permission_utils import user_has_org_perm
    if not is_staff(user):
        return False
    return bool(organization is not None and user_has_org_perm(user, organization, PERM))


def can_use_anywhere(user) -> bool:
    from accounts.permission_utils import user_has_perm_any_org
    return is_staff(user) and user_has_perm_any_org(user, PERM)


def can_open(user, session) -> bool:
    return can_use(user, session.organization_id) or (
        session.client_id is not None and can_use(user, session.client_id))


def sessions_for(user):
    """The sessions `user` may see."""
    from accounts.permission_utils import orgs_with_perm
    from .models import OnboardingSession
    qs = OnboardingSession.objects.select_related('organization', 'client', 'created_by')
    if not is_staff(user):
        return qs.none()
    allowed = orgs_with_perm(user, PERM)
    if allowed is None:
        return qs
    return qs.filter(Q(organization_id__in=allowed) | Q(client_id__in=allowed))


def session_for_user(user, pk):
    try:
        return sessions_for(user).get(pk=pk)
    except Exception:
        raise Http404('No such onboarding session.')


def reachable_clients(user):
    """Customers (active or onboarding) the user may run a change for."""
    from accounts.permission_utils import orgs_with_perm
    from core.models import Organization
    if not is_staff(user):
        return Organization.objects.none()
    allowed = orgs_with_perm(user, PERM)
    qs = Organization.objects.all()
    return qs if allowed is None else qs.filter(pk__in=allowed)


def tenant_for(user, request=None):
    """The organization a new session is filed under: the one the technician
    is working in, else the first organization they may run wizards at
    (global view)."""
    org = getattr(request, 'current_organization', None) if request is not None else None
    if org is not None and can_use(user, org):
        return org
    from core.models import Organization
    qs = reachable_clients(user).filter(is_active=True).order_by('pk')
    return qs.filter(organization_type=Organization.TYPE_INTERNAL).first() or qs.first()
