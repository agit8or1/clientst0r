"""
Core context processors for templates
"""
from config.version import get_version
import django
import sys


def organization_context(request):
    """
    Add organization context to all templates.
    """
    # Get system settings for feature toggles
    from .models import SystemSetting
    try:
        settings = SystemSetting.get_settings()
        feature_toggles = {
            'monitoring_enabled': settings.monitoring_enabled,
            'global_kb_enabled': settings.global_kb_enabled,
            'workflows_enabled': settings.workflows_enabled,
        }
    except Exception:
        # If settings don't exist or there's an error, default to all enabled
        feature_toggles = {
            'monitoring_enabled': True,
            'global_kb_enabled': True,
            'workflows_enabled': True,
        }

    context = {
        'current_organization': getattr(request, 'current_organization', None),
        'is_staff_user': getattr(request, 'is_staff_user', False),
        'app_version': get_version(),  # Add version to all templates
        'DJANGO_VERSION': f"{'.'.join(map(str, django.VERSION[:3]))}",
        'PYTHON_VERSION': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        **feature_toggles,  # Add feature toggles to context
    }

    # Add user's organizations for org switcher
    if request.user.is_authenticated:
        # Superusers and staff users see all organizations
        if request.user.is_superuser or getattr(request, 'is_staff_user', False):
            from .models import Organization
            context['user_organizations'] = list(Organization.objects.filter(is_active=True).order_by('name'))
        # Org users see only their memberships
        elif hasattr(request.user, 'memberships'):
            context['user_organizations'] = [
                m.organization for m in request.user.memberships.filter(
                    is_active=True,
                    organization__is_active=True
                ).select_related('organization').order_by('organization__name')
            ]
        else:
            context['user_organizations'] = []
    else:
        context['user_organizations'] = []

    return context
