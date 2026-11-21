"""
Permission decorators for role-based access control
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from accounts.models import Membership


def _request_membership(user, org_id):
    import copy

    from accounts import authz_cache
    if authz_cache.current_context() is None:
        return None
    try:
        org_pk = int(org_id)
    except (TypeError, ValueError):
        return None
    from accounts.permission_utils import _membership_rows
    for membership in _membership_rows(user):
        if membership.organization_id == org_pk:
            return copy.copy(membership)
    return None


def get_user_membership(request, org_id=None):
    """
    Get the current user's membership for the active organization - or, when
    the URL names one (`org_id`), for that organization. A role held in the
    selected organization never authorizes an action on a different
    organization named in the URL.
    Returns None if no active organization or no membership.
    """
    if not request.user.is_authenticated:
        return None

    if org_id is None:
        org_id = request.session.get('current_organization_id')
    if not org_id:
        return None

    # Inside a request the user's active memberships are already read once
    # (accounts.permission_utils._membership_rows, dropped on any membership
    # or role change); a dashboard asks for the same membership several
    # times. A copy is returned, so a caller changing it never touches the
    # shared row. A membership of an inactive organization is not in that
    # list and is read below as before.
    found = _request_membership(request.user, org_id)
    if found is not None:
        return found
    try:
        return Membership.objects.select_related('organization').get(
            user=request.user,
            organization_id=org_id,
            is_active=True
        )
    except Membership.DoesNotExist:
        return None


def _is_msp_tech(user):
    from accounts.permission_utils import is_msp_staff, staff_client_org_ids
    return is_msp_staff(user) and staff_client_org_ids(user) is None


# Membership.can_write(): any of these create permissions.
WRITE_PERMS = ('vault_create', 'assets_create', 'docs_create', 'files_upload', 'monitoring_create')


def _staff_profile_can_write(request, org_id=None):
    """MSP technicians (profile type Staff) without the Django staff flag and
    without a membership in the customer: write access comes from their
    global role (or, without one, their memberships together), within their
    customer scope - the rules of accounts.permission_utils. In Global View
    (no customer selected) they pass when they may write at some customer;
    the create form then asks for one (require_organization_context), and
    the view's own permission check runs for the customer picked."""
    from accounts.permission_utils import is_msp_staff, user_has_org_perm, user_has_perm_any_org
    user = request.user
    if not is_msp_staff(user):
        return False
    target = org_id if org_id is not None else request.session.get('current_organization_id')
    if target:
        return any(user_has_org_perm(user, target, p) for p in WRITE_PERMS)
    return any(user_has_perm_any_org(user, p) for p in WRITE_PERMS)


def require_write(view_func):
    """
    Decorator that checks if user has write permission (Editor or above).
    Read-only users will be denied access.
    Superusers and staff always have access.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Superusers and staff always have write access
        if request.user.is_superuser or request.user.is_staff:
            return view_func(request, *args, **kwargs)

        membership = get_user_membership(request, kwargs.get('org_id'))

        if not membership and kwargs.get('org_id') is not None and _is_msp_tech(request.user):
            # MSP technicians reach every client; their role comes from the
            # organization they work in (unchanged behaviour).
            membership = get_user_membership(request)

        if not membership and _staff_profile_can_write(request, kwargs.get('org_id')):
            return view_func(request, *args, **kwargs)

        if not membership:
            if kwargs.get('org_id') is not None:
                # The URL names an organization this user is not a member of.
                raise Http404
            messages.error(request, "Please select an organization first.")
            return redirect('home')

        if not membership.can_write():
            messages.error(request, "You don't have permission to perform this action. Editor role or higher required.")
            raise PermissionDenied("Write permission required")

        return view_func(request, *args, **kwargs)

    return wrapper


def require_admin(view_func):
    """
    Decorator that checks if user has admin permission (Admin or Owner).
    Editors and Read-only users will be denied access.
    Superusers and staff always have access.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Superusers and staff always have admin access
        if request.user.is_superuser or request.user.is_staff:
            return view_func(request, *args, **kwargs)

        membership = get_user_membership(request, kwargs.get('org_id'))

        if not membership and kwargs.get('org_id') is not None and _is_msp_tech(request.user):
            # MSP technicians reach every client; their role comes from the
            # organization they work in (unchanged behaviour).
            membership = get_user_membership(request)

        if not membership:
            if kwargs.get('org_id') is not None:
                # The URL names an organization this user is not a member of.
                raise Http404
            messages.error(request, "Please select an organization first.")
            return redirect('home')

        if not membership.can_admin():
            messages.error(request, "You don't have permission to perform this action. Admin role or higher required.")
            raise PermissionDenied("Admin permission required")

        return view_func(request, *args, **kwargs)

    return wrapper


def require_owner(view_func):
    """
    Decorator that checks if user is an owner of the organization.
    Only owners can manage users and critical org settings.
    Superusers and staff always have access.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Superusers and staff always have owner access
        if request.user.is_superuser or request.user.is_staff:
            return view_func(request, *args, **kwargs)

        membership = get_user_membership(request, kwargs.get('org_id'))

        if not membership and kwargs.get('org_id') is not None and _is_msp_tech(request.user):
            # MSP technicians reach every client; their role comes from the
            # organization they work in (unchanged behaviour).
            membership = get_user_membership(request)

        if not membership:
            if kwargs.get('org_id') is not None:
                # The URL names an organization this user is not a member of.
                raise Http404
            messages.error(request, "Please select an organization first.")
            return redirect('home')

        if not membership.can_manage_users():
            messages.error(request, "You don't have permission to perform this action. Owner role required.")
            raise PermissionDenied("Owner permission required")

        return view_func(request, *args, **kwargs)

    return wrapper


def require_organization_context(view_func):
    """
    Decorator that ensures organization context exists before creating org-tied resources.
    If user is in global view (staff/superuser with no current_organization), shows
    warning banner with org selector and requires selection before proceeding.

    Apply to create views for models with ForeignKey to Organization.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from core.middleware import get_request_organization
        from core.models import Organization
        from core.tenancy import accessible_org_ids

        org = get_request_organization(request)

        def _choosable():
            qs = Organization.objects.filter(is_active=True)
            reach = accessible_org_ids(request)
            if reach is not None:
                qs = qs.filter(id__in=reach)
            return qs.order_by('name')

        # If org context exists, proceed normally
        if org:
            return view_func(request, *args, **kwargs)

        # Check if user can access global view (staff/superuser)
        is_staff = getattr(request, 'is_staff_user', False)
        if not (request.user.is_superuser or is_staff):
            # Regular user without org - shouldn't happen (middleware auto-selects)
            messages.error(request, "Organization context required. Please contact your administrator.")
            return redirect('core:dashboard')

        # User is in global view
        if request.method == 'POST':
            # Check if organization was selected via the warning banner
            selected_org_id = request.POST.get('_selected_organization_id')
            if selected_org_id:
                try:
                    # Only a customer this user may work in (not any active one).
                    selected_org = _choosable().get(id=selected_org_id)
                    # Switch to selected organization (same logic as switch_organization view)
                    request.session['current_organization_id'] = selected_org.id
                    if 'global_view_mode' in request.session:
                        del request.session['global_view_mode']
                    request.session.modified = True

                    # Set on request for this cycle
                    request.current_organization = selected_org

                    messages.success(request, f"Switched to organization: {selected_org.name}")

                    # Proceed with the view
                    return view_func(request, *args, **kwargs)
                except (Organization.DoesNotExist, ValueError):
                    messages.error(request, "Selected organization not found.")
            else:
                messages.error(request, "Please select an organization before creating this resource.")

            # POST without a valid org — redirect back as GET so the org selector warning
            # is shown. Never fall through to the view: it would try to save with org=None
            # and raise IntegrityError.
            return redirect(request.path)

        # GET request with no org — show form with warning banner.
        # Stash the warning state on `request` so the
        # `core.context_processors.organization_context` processor can
        # surface it to every template (the historic
        # `response.context_data` injection only worked for
        # TemplateResponse, which most views don't use — bug fixed
        # in v3.17.314).
        organizations = _choosable()
        request._show_org_selector_warning = True
        request._available_organizations = list(organizations)

        # Call the view to render the empty form
        response = view_func(request, *args, **kwargs)

        # Best-effort context_data injection for legacy TemplateResponse
        # callers; harmless if response.context_data doesn't exist.
        if hasattr(response, 'context_data'):
            response.context_data['show_org_selector_warning'] = True
            response.context_data['available_organizations'] = organizations

        return response

    return wrapper
