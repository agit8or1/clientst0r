"""
Feature-flag helpers for the native PSA module.

PSA is OFF by default at both the system and per-client level. Routes,
background jobs, and navigation must consult these helpers and return
404/PermissionDenied when disabled — never silently expose data.
"""
from functools import wraps

from django.http import Http404
from django.shortcuts import redirect


def is_psa_enabled():
    """True if the PSA feature is globally enabled in SystemSetting."""
    try:
        from core.models import SystemSetting
        settings = SystemSetting.get_settings()
        return bool(getattr(settings, 'psa_enabled', False))
    except Exception:
        # If settings can't be loaded for any reason, fail closed.
        return False


def client_has_external_psa(organization):
    """
    True if this organization is already managed by a third-party PSA
    integration (ConnectWise, Halo, Autotask, etc.) via integrations.PSAConnection.

    The native PSA is intended for clients WITHOUT another PSA — having an
    active external connection is the natural opt-out signal.
    """
    if organization is None:
        return False
    try:
        from integrations.models import PSAConnection
    except Exception:
        return False
    try:
        return _external_psa_connections(organization).exists()
    except Exception:
        return False


def _external_psa_connections(organization):
    """Active external PSA connections that manage this customer: its own
    connection, or a platform-owned one with a company mapped to it."""
    from django.db.models import Q
    from integrations.models import PSAConnection
    return PSAConnection.objects.filter(
        Q(organization=organization)
        | Q(organization__isnull=True, companies__organization=organization),
        is_active=True,
    ).distinct()


def clients_eligible_for_native_psa(user):
    """
    Return a queryset of Organizations the given user can create native
    PSA tickets for, excluding any that have an active external
    PSAConnection (the hard product rule).

    Visibility:
      * superuser / staff_user → every active org
      * org user               → only orgs they're a member of
    """
    try:
        from core.models import Organization
        from integrations.models import PSAConnection
    except Exception:
        return []
    qs = Organization.objects.filter(is_active=True)
    is_staff_like = user.is_superuser or getattr(user, '_is_staff_user_cache', False)
    if not is_staff_like:
        # Best-effort detection — UserProfile.is_staff_user() if available;
        # otherwise fall back to membership-scoped orgs.
        profile = getattr(user, 'profile', None)
        if profile is not None and hasattr(profile, 'is_staff_user') and profile.is_staff_user():
            is_staff_like = True
    if not is_staff_like:
        member_org_ids = []
        if hasattr(user, 'memberships'):
            member_org_ids = list(
                user.memberships.filter(is_active=True).values_list('organization_id', flat=True)
            )
        qs = qs.filter(id__in=member_org_ids)
    # Exclude orgs with an active external PSA — that's the hard opt-out.
    # A platform-owned connection has no organization (NULL must not reach a
    # NOT IN list); it manages the customers its companies are mapped to.
    from integrations.models import PSACompany
    external_org_ids = (PSAConnection.objects.filter(is_active=True, organization__isnull=False)
                        .values_list('organization_id', flat=True))
    platform_org_ids = (PSACompany.objects.filter(connection__is_active=True,
                                                  connection__organization__isnull=True,
                                                  organization__isnull=False)
                        .values_list('organization_id', flat=True))
    qs = qs.exclude(id__in=external_org_ids).exclude(id__in=platform_org_ids)
    # Exclude orgs with an explicit ClientPSASettings.enabled=False override.
    try:
        from psa.models import ClientPSASettings
        opted_out_ids = ClientPSASettings.objects.filter(enabled=False).values_list('organization_id', flat=True)
        qs = qs.exclude(id__in=opted_out_ids)
    except Exception:
        pass
    return qs.order_by('name')


def get_external_psa_summary(organization):
    """
    Return a human-readable summary of the external PSA(s) connected to this
    org, e.g. "ConnectWise Manage". Used for the client-settings page banner.
    Empty string if none.
    """
    if organization is None:
        return ''
    try:
        from integrations.models import PSAConnection
    except Exception:
        return ''
    try:
        names = list(_external_psa_connections(organization).values_list('provider_type', 'name'))
    except Exception:
        return ''
    if not names:
        return ''
    return ', '.join(f'{name or provider} ({provider})' for provider, name in names)


def is_psa_enabled_for_client(organization):
    """
    Decide whether the native PSA is active for `organization`.

    Hard product rule: the native PSA exists only for clients who do NOT
    already have another PSA. An active external PSAConnection is an
    absolute opt-out — there is no admin override path that re-enables
    native PSA in the presence of one. To use native PSA for a client,
    deactivate or remove their external PSAConnection first.

    Resolution order (first match wins):
      1. Global flag off                         → False
      2. No organization                         → False
      3. Active external PSAConnection exists    → False (HARD opt-out)
      4. Explicit ClientPSASettings row exists   → return its `enabled` field
         (admin can still opt OUT a no-external-PSA client)
      5. Otherwise                               → True (cascade default)

    Per-surface flags (portal, SMS, desktop alerts, anonymous form,
    email-to-ticket, external alert ingest) are independent from this
    helper and remain OFF by default at the model level.
    """
    if not is_psa_enabled():
        return False
    if organization is None:
        return False
    # HARD RULE: external PSA always wins.
    if client_has_external_psa(organization):
        return False
    try:
        from psa.models import ClientPSASettings
        cps = ClientPSASettings.objects.filter(organization=organization).first()
    except Exception:
        return False
    if cps is not None:
        return bool(cps.enabled)
    return True


def require_psa_enabled(view_func):
    """
    View decorator: 404 if PSA is globally disabled.
    Use on every PSA route. Pair with @login_required first.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_psa_enabled():
            raise Http404("PSA is not enabled")
        return view_func(request, *args, **kwargs)
    return wrapper


def require_client_psa_enabled(view_func):
    """
    View decorator: 404 if PSA is disabled globally OR for the active
    organization on the request. Use on routes that operate within a
    client/org context.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_psa_enabled():
            raise Http404("PSA is not enabled")
        org = getattr(request, 'current_organization', None)
        if not is_psa_enabled_for_client(org):
            raise Http404("PSA is not enabled for this client")
        return view_func(request, *args, **kwargs)
    return wrapper
