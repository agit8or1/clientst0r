"""Who sees what. The score is for MSP staff only (customers never see it,
in the portal or anywhere else) and only for clients the user can reach; the
commercial dimension also needs the financial permission (`view_profitability`
where the profitability feature is installed, else `reports_view_financial`).
Changing weights needs `manage_health_score_settings`."""
from __future__ import annotations

from accounts import permission_registry
from accounts.permission_utils import user_has_org_perm, user_has_perm
from core.tenancy import accessible_org_ids
from psa.visibility import is_msp_staff

SETTINGS_PERM = 'manage_health_score_settings'


def financial_permission_key():
    return 'view_profitability' if permission_registry.is_known('view_profitability') else 'reports_view_financial'


def can_use(request):
    """MSP staff only; customer users never."""
    return is_msp_staff(request.user)


def client_ids(request):
    """Client organization ids this request may see health for (None = all)."""
    if not can_use(request):
        return set()
    return accessible_org_ids(request)


def can_view_client(request, client):
    if not can_use(request):
        return False
    allowed = accessible_org_ids(request)
    return allowed is None or client.pk in allowed


def can_view_commercial(user, client):
    if not is_msp_staff(user):
        return False
    return user.is_superuser or user_has_org_perm(user, client, financial_permission_key())


def hidden_dimensions(user, client):
    """Dimension keys this user may not see for `client`."""
    return () if can_view_commercial(user, client) else ('commercial',)


def can_manage_settings(user, client=None):
    if not is_msp_staff(user):
        return False
    if client is not None:
        return user_has_org_perm(user, client, SETTINGS_PERM)
    return user.is_superuser or user_has_perm(user, SETTINGS_PERM)
