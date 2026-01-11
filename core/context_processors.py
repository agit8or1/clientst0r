"""
Core context processors for templates
"""
from config.version import get_version


def organization_context(request):
    """
    Add organization context to all templates.
    """
    context = {
        'current_organization': getattr(request, 'current_organization', None),
        'is_staff_user': getattr(request, 'is_staff_user', False),
        'app_version': get_version(),  # Add version to all templates
    }

    # Add user's organizations for org switcher
    if request.user.is_authenticated:
        # Staff users see all organizations
        if getattr(request, 'is_staff_user', False):
            from .models import Organization
            context['user_organizations'] = list(Organization.objects.filter(is_active=True).order_by('name'))
        # Org users see only their memberships
        elif hasattr(request.user, 'memberships'):
            context['user_organizations'] = [
                m.organization for m in request.user.memberships.filter(is_active=True).select_related('organization').order_by('organization__name')
            ]
        else:
            context['user_organizations'] = []
    else:
        context['user_organizations'] = []

    return context
