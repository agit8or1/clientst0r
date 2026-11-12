"""Who may do what with contract documents.

Eight role flags on `accounts.RoleTemplate`, each checked against the
contract's customer (MSP staff use their global role; staff without a global
role keep the every-customer reach they have elsewhere, exactly as
`accounts.permission_utils.orgs_with_perm` defines it):

    contracts_view            see contracts, the dashboard, timelines
    contracts_edit            create / edit drafts, clone, amend, revise
    contracts_manage_templates  templates and clauses
    contracts_approve         internal approval
    contracts_send            send, resend, copy links, revoke invitations
    contracts_void            void a contract
    contracts_view_audit      IP addresses, browsers, evidence downloads
    contracts_manage_settings contract settings

The whole /contracts/ section is MSP-staff only
(accounts.middleware.SectionPermissionMiddleware.STAFF_ONLY_PREFIXES).
Deployment-wide starter templates and the deployment default settings need
every-customer reach for the flag.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied

VIEW = 'contracts_view'
EDIT = 'contracts_edit'
TEMPLATES = 'contracts_manage_templates'
APPROVE = 'contracts_approve'
SEND = 'contracts_send'
VOID = 'contracts_void'
AUDIT = 'contracts_view_audit'
SETTINGS = 'contracts_manage_settings'
ALL = (VIEW, EDIT, TEMPLATES, APPROVE, SEND, VOID, AUDIT, SETTINGS)


def allowed_orgs(user, perm):
    """None = every customer, else a set of organization ids."""
    from accounts.permission_utils import orgs_with_perm
    from psa.visibility import is_msp_staff
    if not is_msp_staff(user):
        return set()
    return orgs_with_perm(user, perm)


def has(user, perm, organization) -> bool:
    allowed = allowed_orgs(user, perm)
    if allowed is None:
        return True
    org_id = getattr(organization, 'pk', organization)
    return org_id is not None and org_id in allowed


def has_global(user, perm) -> bool:
    return allowed_orgs(user, perm) is None


def has_any(user, perm) -> bool:
    allowed = allowed_orgs(user, perm)
    return allowed is None or bool(allowed)


def require(user, perm, organization):
    if not has(user, perm, organization):
        raise PermissionDenied(f"You don't have the '{perm}' permission for this customer.")


def scope(qs, user, perm=VIEW, field='organization'):
    allowed = allowed_orgs(user, perm)
    if allowed is None:
        return qs
    return qs.filter(**{f'{field}_id__in': allowed})


def template_scope(qs, user, perm=VIEW):
    """Templates and clauses: deployment-wide rows plus the customers' own."""
    from django.db.models import Q
    allowed = allowed_orgs(user, perm)
    if allowed is None:
        return qs
    return qs.filter(Q(organization__isnull=True) | Q(organization_id__in=allowed))


def can_manage_template(user, template) -> bool:
    if template.organization_id is None:
        return has_global(user, TEMPLATES)
    return has(user, TEMPLATES, template.organization_id)


def flags_for(user, contract) -> dict:
    org = contract.organization_id
    return {p.replace('contracts_', ''): has(user, p, org) for p in ALL}
