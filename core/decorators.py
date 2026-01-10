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
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
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
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
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
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        membership = get_user_membership(request)

        if not membership:
            messages.error(request, "Please select an organization first.")
            return redirect('home')

        if not membership.can_manage_users():
            messages.error(request, "You don't have permission to perform this action. Owner role required.")
            raise PermissionDenied("Owner permission required")

        return view_func(request, *args, **kwargs)

    return wrapper
