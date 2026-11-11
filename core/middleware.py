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
            # Pattern: getattr with None default, then explicit null check
            profile = getattr(request.user, 'profile', None)
            if profile is not None and hasattr(profile, 'is_staff_user'):
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

            # If no org selected, auto-select based on preferred org or first available
            if not request.current_organization:
                # Check if user explicitly wants global view (superusers only)
                global_view_mode = request.session.get('global_view_mode', False)

                # Check preferred_organization from user profile (#115)
                preferred_org = None
                if profile is not None:
                    pref = getattr(profile, 'preferred_organization', None)
                    if pref is not None and pref.is_active:
                        # Verify access
                        if request.user.is_superuser or request.is_staff_user:
                            preferred_org = pref
                        elif hasattr(request.user, 'memberships'):
                            if request.user.memberships.filter(organization=pref, is_active=True).exists():
                                preferred_org = pref

                # No preference: carry on in the client this user last worked
                # in (core.RecentClient), so a new session doesn't drop them
                # into an arbitrary first client and make them pick again.
                # Access is re-checked here, exactly like the session value.
                recent_org = None
                if not preferred_org and not global_view_mode:
                    from .models import RecentClient
                    for rc in (RecentClient.objects.filter(user=request.user, organization__is_active=True)
                               .select_related('organization').order_by('-switched_at')[:5]):
                        if request.user.is_superuser or request.is_staff_user or (
                                hasattr(request.user, 'memberships') and request.user.memberships.filter(
                                    organization=rc.organization, is_active=True).exists()):
                            recent_org = rc.organization
                            break

                if preferred_org and not global_view_mode:
                    request.current_organization = preferred_org
                    request.session['current_organization_id'] = preferred_org.id
                    request.session.modified = True
                elif recent_org is not None:
                    request.current_organization = recent_org
                    request.session['current_organization_id'] = recent_org.id
                    request.session.modified = True
                elif request.user.is_superuser or request.is_staff_user:
                    # Skip auto-select if in global view mode
                    if not global_view_mode:
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

    Returns:
        Organization: The current organization set by CurrentOrganizationMiddleware
        None: If no organization is set (global view mode) or request not processed

    Note: Views should check for None and handle global view mode appropriately.
    """
    if hasattr(request, 'current_organization'):
        return request.current_organization
    return None
