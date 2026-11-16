"""
Who may see and act on the advisor.

  * MSP staff only. Customer users never see cost, margin or the advisor,
    whatever their role says (the flags are staff_only, /reports/ is an
    MSP-staff-only section, and every check here starts with is_msp_staff).
  * Viewing a customer's findings: `view_profitability` at that customer
    (falls back to `reports_view_financial` on installs that predate it).
    The technician's client scope applies (accounts.permission_utils).
  * Accepting or dismissing: also `act_on_pricing_recommendations` there.
"""
from __future__ import annotations

from accounts import permission_registry as registry
from accounts.permission_utils import orgs_with_perm, user_has_org_perm

ACT_PERM = 'act_on_pricing_recommendations'


def view_perm():
    return 'view_profitability' if registry.is_known('view_profitability') else 'reports_view_financial'


def _staff(user):
    if user is None or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user))


def visible_client_ids(user):
    """None (every customer) or the set of customer ids whose findings `user` may see."""
    if not _staff(user):
        return set()
    return orgs_with_perm(user, view_perm())


def can_view_any(user):
    ids = visible_client_ids(user)
    return ids is None or bool(ids)


def can_view_client(user, org):
    if not _staff(user) or org is None:
        return False
    ids = visible_client_ids(user)
    if ids is not None and getattr(org, 'pk', org) not in ids:
        return False
    return bool(user_has_org_perm(user, org, view_perm()))


def can_act(user, org):
    return can_view_client(user, org) and user_has_org_perm(user, org, ACT_PERM)


def filter_findings(qs, user):
    ids = visible_client_ids(user)
    if ids is None:
        return qs
    return qs.filter(client_org_id__in=ids)


def can_use_ai(user, org):
    """OPTIONAL AI: master switch on and the technician's AI capability at this customer."""
    from core.ai_gate import ai_features_enabled
    if not ai_features_enabled() or not can_view_client(user, org):
        return False
    try:
        from psa_ai.permissions import has_capability
        return bool(has_capability(user, org, 'analyze'))
    except Exception:
        return False
