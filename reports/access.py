"""
Who may read MSP-wide report figures (roles & permissions program).

Most report pages aggregate every customer: profitability, AR aging, MRR,
hardware margin, SLA trends. Two different checks used to guard them:

  * `@require_perm(flag)` — `accounts.permission_utils.user_has_perm`, which
    is True when the flag is held on *any* membership. A technician whose
    global role leaves the flag out, but who holds it through some customer
    membership, could read every customer's figures: a permission granted in
    one organization combined with an all-customers scope.
  * a bare "is MSP staff" test — no role flag at all, so a Level 1 technician
    could read every customer's invoices, margins and vendor costs.

`has_msp_wide_perm` is the one rule both now use:

  * superusers — yes;
  * MSP staff with a global role template — that template decides (it is the
    role that carries an all-customers scope);
  * MSP staff without a global role — unchanged legacy behaviour, given by
    `legacy` ('membership' = the old `user_has_perm` answer, 'staff' = the
    old "staff may see it" answer);
  * anyone else — no.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied


def _global_role(user):
    profile = getattr(user, 'profile', None)
    if profile is None or not getattr(profile, 'is_staff_user', lambda: False)():
        return False, None
    return True, profile.get_global_permissions()


def has_msp_wide_perm(user, perm_name, legacy='membership'):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    is_staff, global_perms = _global_role(user)
    if not is_staff:
        return False
    if global_perms is not None:
        return bool(getattr(global_perms, perm_name, False))
    if legacy == 'staff':
        return True
    from accounts.permission_utils import user_has_perm
    return user_has_perm(user, perm_name)


def require_msp_wide_perm(perm_name, legacy='membership'):
    """View decorator for has_msp_wide_perm."""
    def decorator(view_fn):
        @wraps(view_fn)
        def _wrapped(request, *args, **kwargs):
            if not has_msp_wide_perm(request.user, perm_name, legacy=legacy):
                raise PermissionDenied(
                    f"Your role does not include the '{perm_name}' permission across every customer."
                )
            return view_fn(request, *args, **kwargs)
        return _wrapped
    return decorator


# Report template types (reports.models.ReportTemplate.REPORT_TYPES) and the
# per-customer view flag the data behind each needs. A generated report is a
# copy of that data, so the same flag is checked again on download.
REPORT_TYPE_PERMS = {
    'asset_summary': 'assets_view',
    'asset_lifecycle': 'assets_view',
    'password_audit': 'vault_view',
    'document_usage': 'docs_view',
    'monitor_uptime': 'monitoring_view',
    'expiration_forecast': 'monitoring_view',
    # Audit-log activity: who did what in the organization.
    'user_activity': 'audit_view',
    'organization_metrics': 'org_view_members',
}


def report_type_perm(report_type):
    return REPORT_TYPE_PERMS.get(report_type)


def may_see_report_type(user, report_type, organization):
    """True when `user` may see a `report_type` report for `organization`."""
    from accounts.permission_utils import has_perm_for_org, user_has_org_perm
    perm = report_type_perm(report_type)
    if perm is None:
        return True
    if organization is None:
        return has_perm_for_org(user, None, perm)
    # has_perm_for_org follows orgs_with_perm (global role authoritative,
    # vault flags membership-scoped); user_has_org_perm adds the plain
    # membership answer for staff without a global role.
    return (has_perm_for_org(user, organization, perm)
            or user_has_org_perm(user, organization, perm))
