"""Who sees what. The score is for MSP staff only (customers never see it,
in the portal or anywhere else) and only for clients the user can reach.
Money signals need the billing / financial permission and margin needs
`view_profitability` (see `hidden_requirements`). Changing weights needs
`manage_health_score_settings`."""
from __future__ import annotations

from reports.access import has_msp_wide_perm
from accounts.permission_utils import user_has_org_perm, user_has_perm
from core.tenancy import accessible_org_ids
from psa.visibility import is_msp_staff

SETTINGS_PERM = 'manage_health_score_settings'


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


def hidden_requirements(user, client):
    """Signal requirements (`Signal.requires`) this user may not see for
    `client`: 'billing' (invoices, renewals, payments: billing_view_invoices
    or reports_view_financial at the client) and 'profitability' (labour cost
    and margin: the MSP-wide view_profitability permission, staff only)."""
    hidden = set()
    if not is_msp_staff(user):
        return {'billing', 'profitability'}
    if not (user.is_superuser or user_has_org_perm(user, client, 'billing_view_invoices')
            or user_has_org_perm(user, client, 'reports_view_financial')):
        hidden.add('billing')
    if not has_msp_wide_perm(user, 'view_profitability'):
        hidden.add('profitability')
    return hidden


def can_manage_settings(user, client=None):
    if not is_msp_staff(user):
        return False
    if client is not None:
        return user_has_org_perm(user, client, SETTINGS_PERM)
    return user.is_superuser or user_has_perm(user, SETTINGS_PERM)
