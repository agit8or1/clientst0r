"""
API permissions - Role-based permissions for API
"""
from rest_framework import permissions
from accounts.models import Role


class HasOrganizationAccess(permissions.BasePermission):
    """
    Check if user has access to the organization in request.
    """
    def has_permission(self, request, view):
        if not hasattr(request, 'current_organization') or not request.current_organization:
            return False
        return True


class IsReadOnly(permissions.BasePermission):
    """
    Check if user can read (all roles can read).
    """
    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS


class CanWrite(permissions.BasePermission):
    """
    Check if user can write (Owner, Admin, Editor).
    """
    def has_permission(self, request, view):
        if not hasattr(request, 'api_key'):
            # Session auth - check membership
            if hasattr(request, 'current_organization'):
                membership = request.user.memberships.filter(
                    organization=request.current_organization,
                    is_active=True
                ).first()
                if membership:
                    return membership.can_write()
            return False

        # API key auth
        return request.api_key.role in [Role.OWNER, Role.ADMIN, Role.EDITOR]


class CanAdmin(permissions.BasePermission):
    """
    Check if user can perform admin actions (Owner, Admin).
    """
    def has_permission(self, request, view):
        if not hasattr(request, 'api_key'):
            # Session auth
            if hasattr(request, 'current_organization'):
                membership = request.user.memberships.filter(
                    organization=request.current_organization,
                    is_active=True
                ).first()
                if membership:
                    return membership.can_admin()
            return False

        # API key auth
        return request.api_key.role in [Role.OWNER, Role.ADMIN]


class OrganizationPermission(permissions.BasePermission):
    """
    Combined permission: must have org access, and appropriate role for action.
    """
    def has_permission(self, request, view):
        # Must have organization context
        if not hasattr(request, 'current_organization') or not request.current_organization:
            return False

        # Safe methods (GET, HEAD, OPTIONS) - any role
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write methods - need write permission
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            if hasattr(request, 'api_key'):
                return request.api_key.role in [Role.OWNER, Role.ADMIN, Role.EDITOR]
            else:
                membership = request.user.memberships.filter(
                    organization=request.current_organization,
                    is_active=True
                ).first()
                return membership and membership.can_write()

        return False
