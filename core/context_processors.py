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
            'reports_enabled': settings.reports_enabled,
            'secure_notes_enabled': settings.secure_notes_enabled,
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
            'reports_enabled': True,
            'secure_notes_enabled': True,
        }
        system_settings = None

    context = {
        'current_organization': getattr(request, 'current_organization', None),
        'is_staff_user': getattr(request, 'is_staff_user', False),
        'app_version': get_version(),  # Add version to all templates
        'DJANGO_VERSION': f"{'.'.join(map(str, django.VERSION[:3]))}",
        'PYTHON_VERSION': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'system_settings': system_settings,  # Add system settings for whitelabeling
        'update_badge': _update_badge(request, system_settings),
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

    # Which role-gated sections the user may open in the current customer,
    # by the same rule as accounts.middleware.SectionPermissionMiddleware, so
    # the navbar doesn't offer links that end in a 403.
    context['section_view'] = _section_view(request)

    # Navbar client switcher (templates/core/_client_switcher.html): recents,
    # search and the "View all clients" link, bounded for large client lists.
    if request.user.is_authenticated:
        try:
            from .client_switcher import switcher_context
            context['client_switcher'] = switcher_context(
                request, context['user_organizations'])
        except Exception:
            context['client_switcher'] = None

    return context


class _SectionView(dict):
    """Lazy {perm: bool}: each flag is resolved on first lookup in a template."""

    def __init__(self, request):
        super().__init__()
        self._request = request

    def __missing__(self, perm):
        from accounts.middleware import SectionPermissionMiddleware
        user = getattr(self._request, 'user', None)
        ok = bool(user is not None and user.is_authenticated
                  and SectionPermissionMiddleware.denial(self._request, user, perm) is None)
        self[perm] = ok
        return ok


def _section_view(request):
    return _SectionView(request)


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


def csp_nonce(request):
    """Per-request CSP nonce for inline <script nonce="{{ csp_nonce }}">.

    Set by core.csp_middleware.ContentSecurityPolicyMiddleware. Lazy: the
    nonce is generated (and added to the header) only when a template uses
    it. Empty string when the middleware is not installed, so templates never
    render nonce="None".
    """
    nonce = getattr(request, '_csp_nonce', None)
    return {'csp_nonce': nonce if nonce is not None else ''}


def _update_badge(request, system_settings):
    """The newer release the last update check found, for the navbar badge —
    superusers only (they are the ones who can apply it), and never a network
    call: it compares what the scheduled check stored with the running
    version, so it disappears as soon as the update is applied."""
    user = getattr(request, 'user', None)
    if not (user is not None and user.is_authenticated and user.is_superuser and system_settings is not None):
        return None
    latest = (getattr(system_settings, 'latest_release_version', '') or '').strip()
    if not latest:
        return None
    try:
        from packaging import version
        if version.parse(latest) <= version.parse(get_version()):
            return None
    except Exception:
        return None
    return {'version': latest}
