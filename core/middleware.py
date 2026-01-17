"""
Core middleware for organization context
"""
from django.shortcuts import redirect
from django.urls import reverse
from .models import Organization


class CurrentOrganizationMiddleware:
    """
    Sets current_organization on the request based on session.
    If user has only one org membership, auto-select it.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.current_organization = None
        request.is_staff_user = False

        if request.user.is_authenticated:
            # Check if user is a staff user (MSP tech)
            profile = getattr(request.user, 'profile', None)
            if profile and hasattr(profile, 'is_staff_user'):
                request.is_staff_user = profile.is_staff_user()

            # Try to get org from session
            org_id = request.session.get('current_organization_id')
            if org_id:
                try:
                    org = Organization.objects.get(id=org_id, is_active=True)
                    # Superusers and staff users have access to all orgs, org users need membership
                    if request.user.is_superuser or request.is_staff_user:
                        request.current_organization = org
                    elif hasattr(request.user, 'memberships'):
                        if request.user.memberships.filter(organization=org, is_active=True).exists():
                            request.current_organization = org
                except Organization.DoesNotExist:
                    pass

            # If no org selected, auto-select first available org
            if not request.current_organization:
                if request.user.is_superuser or request.is_staff_user:
                    # Superusers and staff users: select first active organization
                    first_org = Organization.objects.filter(is_active=True).first()
                    if first_org:
                        request.current_organization = first_org
                        request.session['current_organization_id'] = first_org.id
                        request.session.modified = True
                elif hasattr(request.user, 'memberships'):
                    # Org users: select first membership with active organization
                    memberships = request.user.memberships.filter(
                        is_active=True,
                        organization__is_active=True
                    ).select_related('organization')
                    if memberships.exists():
                        request.current_organization = memberships.first().organization
                        request.session['current_organization_id'] = request.current_organization.id
                        request.session.modified = True

        response = self.get_response(request)
        return response


def get_request_organization(request):
    """
    Helper to get current organization from request.
    Returns None if not set, allowing views to handle it gracefully.
    """
    if hasattr(request, 'current_organization'):
        return request.current_organization
    return None
