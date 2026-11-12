"""Who may do what with contract documents.

A thin layer over the roles program: every decision goes through
`accounts.contract_access.can_contract(user, contract_org, action, contract)`
(which reads the RoleTemplate flags per customer, see
docs/ROLES_AND_ACCESS.md) and list / dashboard querysets go through
`accounts.scope.scoped_queryset`, so a technician whose grant covers only
assigned or own records sees only those contracts.

Actions (accounts.contract_access.STAFF_ACTIONS) and what they unlock here:

    view              contracts, the dashboard, timelines, the client card
    view_pricing      totals, line items, the full document (preview,
                      snapshot, issued PDF)
    edit_draft        create / edit drafts, clone, amend, renew, revise
    manage_templates  templates and clauses (provider-wide)
    submit_approval   freeze a draft and submit it for approval / ready it
    approve           internal approval (never the version's own author or
                      submitter)
    send              send and resend signing invitations
    manage_links      copy a new link, revoke, replace a signer
    countersign       sign as the provider's internal signer
    void              void a contract
    download_signed   the final signed PDF
    view_audit        IP addresses, browsers, the evidence package
    settings          contract settings (provider-wide)

The whole /contracts/ section is MSP-staff only
(accounts.middleware.SectionPermissionMiddleware.STAFF_ONLY_PREFIXES).
"""
from __future__ import annotations

from types import SimpleNamespace

from django.core.exceptions import PermissionDenied

VIEW = 'view'
PRICING = 'view_pricing'
EDIT = 'edit_draft'
TEMPLATES = 'manage_templates'
SUBMIT = 'submit_approval'
APPROVE = 'approve'
SEND = 'send'
LINKS = 'manage_links'
COUNTERSIGN = 'countersign'
VOID = 'void'
DOWNLOAD = 'download_signed'
AUDIT = 'view_audit'
SETTINGS = 'settings'
ALL = (VIEW, PRICING, EDIT, TEMPLATES, SUBMIT, APPROVE, SEND, LINKS, COUNTERSIGN, VOID, DOWNLOAD, AUDIT,
       SETTINGS)

# Record scope: who "owns" a contract and who it is "assigned" to, for a
# grant limited to own / assigned records.
OWNER_FIELDS = ('created_by', 'owner')
ASSIGNEE_FIELDS = ('owner', 'account_manager')


def _flags(action):
    from accounts.contract_access import STAFF_ACTIONS
    return STAFF_ACTIONS[action]


def _provider_wide(action):
    from accounts.contract_access import PROVIDER_WIDE
    return action in PROVIDER_WIDE


def _is_staff(user):
    from accounts.permission_utils import is_msp_staff
    return bool(getattr(user, 'is_authenticated', False) and (user.is_superuser or is_msp_staff(user)))


def approval_subject(contract, version=None):
    """What can_contract('approve') compares the approver with: the
    contract's author and the version's submitter."""
    return SimpleNamespace(created_by_id=getattr(contract, 'created_by_id', None),
                           submitted_by_id=getattr(version, 'issued_by_id', None) if version is not None else None)


def denial(user, action, organization, contract=None) -> str:
    from accounts.contract_access import contract_denial
    org_id = getattr(organization, 'pk', organization)
    if _provider_wide(action):
        why = contract_denial(user, None, action)
        if why or org_id is None:
            return why
        return contract_denial(user, org_id, VIEW)
    return contract_denial(user, org_id, action, contract)


def has(user, action, organization, contract=None) -> bool:
    return denial(user, action, organization, contract) == ''


def require(user, action, organization, contract=None):
    why = denial(user, action, organization, contract)
    if why:
        raise PermissionDenied(why)


def allowed_orgs(user, action=VIEW):
    """Customers the action reaches: None = every customer, else a set of ids.
    For pickers and counts; rows go through scope()."""
    from accounts.contract_access import can_contract
    from accounts.scope import reachable_org_ids
    if not _is_staff(user):
        return set()
    if _provider_wide(action):
        if not can_contract(user, None, action):
            return set()
        action = VIEW
    out = None
    for flag in _flags(action):
        ids = reachable_org_ids(user, flag)
        if ids is None:
            continue
        out = set(ids) if out is None else (out & set(ids))
    return out


def has_global(user, action) -> bool:
    if _provider_wide(action):
        from accounts.contract_access import can_contract
        return can_contract(user, None, action)
    return allowed_orgs(user, action) is None


def has_any(user, action) -> bool:
    allowed = allowed_orgs(user, action)
    return allowed is None or bool(allowed)


def scope(qs, user, action=VIEW, field='organization'):
    """Contracts (or rows with a contract organization at `field`) the user
    may use `action` on, one grant at a time (organization AND record scope)."""
    from accounts.scope import scoped_queryset
    if not _is_staff(user):
        return qs.none()
    prefix = field.rsplit('organization', 1)[0]
    flags = _flags(VIEW if _provider_wide(action) else action)
    for flag in flags:
        qs = scoped_queryset(qs, user, flag, org_field=field,
                             owner_fields=tuple(prefix + f for f in OWNER_FIELDS),
                             assignee_fields=tuple(prefix + f for f in ASSIGNEE_FIELDS))
    return qs


def template_scope(qs, user, action=VIEW):
    """Templates and clauses: deployment-wide rows plus the customers' own."""
    from django.db.models import Q
    if not _is_staff(user):
        return qs.none()
    allowed = allowed_orgs(user, action)
    if allowed is None:
        return qs
    return qs.filter(Q(organization__isnull=True) | Q(organization_id__in=allowed))


def can_manage_template(user, template) -> bool:
    if template.organization_id is None:
        return has_global(user, TEMPLATES)
    return has(user, TEMPLATES, template.organization_id)


def flags_for(user, contract) -> dict:
    org = contract.organization_id
    out = {a: has(user, a, org) for a in ALL if a != APPROVE}
    out[APPROVE] = has(user, APPROVE, org, approval_subject(contract, contract.current_version))
    out['may_approve'] = has(user, APPROVE, org)    # holds the flag (even if this version is their own)
    return out


def alert_recipients(users, contract):
    """Users allowed to be told about `contract` right now (generation and
    delivery time): an active, unlocked account that can view this contract,
    including record scope."""
    from accounts.alert_access import may_receive_alert
    out = []
    for u in users:
        if u is None or not _is_staff(u):
            continue
        if not may_receive_alert(u, 'contracts_view', obj=contract, owner_fields=OWNER_FIELDS,
                                 assignee_fields=ASSIGNEE_FIELDS):
            continue
        if has(u, VIEW, contract.organization_id):
            out.append(u)
    return out
