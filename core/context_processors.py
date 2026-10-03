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
    # Get system settings for feature toggles and branding
    from .models import SystemSetting
    try:
        settings = SystemSetting.get_settings()
        feature_toggles = {
            'monitoring_enabled': settings.monitoring_enabled,
            'global_kb_enabled': settings.global_kb_enabled,
            'workflows_enabled': settings.workflows_enabled,
            'vehicles_enabled': settings.vehicles_enabled,
            'inventory_enabled': settings.inventory_enabled,
            'scheduling_enabled': settings.scheduling_enabled,
            'psa_enabled': settings.psa_enabled,
            'crm_enabled': settings.crm_enabled,
            # Phase 12 portal feature toggles (v3.17.243).
            'psa_portal_announcements_enabled': getattr(settings, 'psa_portal_announcements_enabled', False),
            'psa_portal_voting_enabled': getattr(settings, 'psa_portal_voting_enabled', False),
            'psa_portal_escalation_enabled': getattr(settings, 'psa_portal_escalation_enabled', False),
            'psa_portal_customer_approvals_enabled': getattr(settings, 'psa_portal_customer_approvals_enabled', False),
            'psa_csat_enabled': getattr(settings, 'psa_csat_enabled', False),
        }
        system_settings = settings
    except Exception:
        # If settings don't exist or there's an error, default to all enabled
        # EXCEPT psa_enabled and crm_enabled which are opt-in.
        feature_toggles = {
            'monitoring_enabled': True,
            'global_kb_enabled': True,
            'workflows_enabled': True,
            'vehicles_enabled': True,
            'inventory_enabled': True,
            'scheduling_enabled': True,
            'psa_enabled': False,
            'crm_enabled': False,
        }
        system_settings = None

    context = {
        'current_organization': getattr(request, 'current_organization', None),
        'is_staff_user': getattr(request, 'is_staff_user', False),
        'app_version': get_version(),  # Add version to all templates
        'DJANGO_VERSION': f"{'.'.join(map(str, django.VERSION[:3]))}",
        'PYTHON_VERSION': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'system_settings': system_settings,  # Add system settings for whitelabeling
        # v3.17.314 — surface `require_organization_context` warning
        # state so templates that include `org_selector_warning.html`
        # render the org-picker banner correctly even when the view
        # uses `render()` (not TemplateResponse).
        'show_org_selector_warning': getattr(
            request, '_show_org_selector_warning', False),
        'available_organizations': getattr(
            request, '_available_organizations', []),
        **feature_toggles,  # Add feature toggles to context
    }

    # v3.17.230: resolve user's quick actions for the dashboard partial.
    if request.user.is_authenticated:
        try:
            from .quick_actions import resolve_for_user
            context['resolved_quick_actions'] = resolve_for_user(request.user, context)
        except Exception:
            context['resolved_quick_actions'] = []

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


def support_links(request):
    """Expose the "Help Us Grow" destinations to every template.

    The support modal lives in `base.html` on every page, so the data it
    renders has to be in the global context rather than passed by a view.
    Everything comes from `config/support_links.py` — see that file before
    adding a URL anywhere in the modal markup.
    """
    from config.support_links import get_support_links
    try:
        return {'support': get_support_links()}
    except Exception:
        # A bad override must not take out every page in the app.
        return {'support': None}
