"""
Permission decorators for role-based access control
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from accounts.models import Membership


def get_user_membership(request):
    """
    Get the current user's membership for the active organization.
    Returns None if no active organization or no membership.
    """
    if not request.user.is_authenticated:
        return None

    org_id = request.session.get('current_organization_id')
    if not org_id:
        return None

    try:
        return Membership.objects.select_related('organization').get(
            user=request.user,
            organization_id=org_id,
            is_active=True
        )
    except Membership.DoesNotExist:
        return None


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

        membership = get_user_membership(request)

        if not membership:
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

        membership = get_user_membership(request)

        if not membership:
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

        membership = get_user_membership(request)

        if not membership:
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

        org = get_request_organization(request)

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
                    selected_org = Organization.objects.get(id=selected_org_id, is_active=True)
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
                except Organization.DoesNotExist:
                    messages.error(request, "Selected organization not found.")
            else:
                messages.error(request, "Please select an organization before creating this resource.")

        # GET request or POST without org - show form with warning
        organizations = Organization.objects.filter(is_active=True).order_by('name')

        # Call the view to render form
        response = view_func(request, *args, **kwargs)

        # Inject context for warning banner (if response has context_data)
        if hasattr(response, 'context_data'):
            response.context_data['show_org_selector_warning'] = True
            response.context_data['available_organizations'] = organizations

        return response

    return wrapper
