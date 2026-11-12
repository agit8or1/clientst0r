"""
Contract permissions for the contract generator and digital signing.

The contracts app calls these instead of reading role flags itself, so
contract access follows the same per-organization rules as everything else
(accounts.permission_utils.user_has_org_perm: a permission held at one
customer never answers for another).

    can_contract(user, contract_org, action, contract=None) -> bool
    contract_denial(user, contract_org, action, contract=None) -> str  ('' = allowed)
    contract_alert_recipients(users, contract_org, contract=None) -> [users]

Provider (MSP staff) actions and the RoleTemplate flag each needs:

    view               contracts_view
    view_pricing       contracts_view + contracts_view_pricing
    edit_draft         contracts_view + contracts_edit_draft
    manage_templates   contracts_manage_templates (provider-wide; contract_org may be None)
    submit_approval    contracts_view + contracts_submit_approval
    approve            contracts_view + contracts_approve; never the version's own
                       author / submitter (contract.created_by_id / submitted_by_id)
    send               contracts_view + contracts_send
    manage_links       contracts_view + contracts_manage_links
    countersign        contracts_view + contracts_countersign
    void               contracts_view + contracts_void
    download_signed    contracts_view + contracts_download_signed
    view_audit         contracts_view + contracts_view_audit
    settings           contracts_settings (provider-wide)

Customer (portal) actions, from the customer user's membership in the
contract's customer:

    portal_view             portal_contract_review or portal_contract_sign
    portal_view_pricing     same as portal_view, or portal_billing_contact
    portal_download_signed  portal_contract_review or portal_contract_sign
    portal_sign             portal_contract_sign, on a membership in the
                            contract's own customer (not a parent's)

A customer administrator is NOT a signer unless the role holds
portal_contract_sign. Customer users never get provider actions and
provider staff never get portal actions.

External signers (people without an account) are outside this module: a
signing invitation token grants exactly one contract version and the sign
action, verified by the contracts app; it never opens the portal or any
other record.
"""
from __future__ import annotations

from .permission_utils import is_msp_staff, memberships_covering, user_has_org_perm

STAFF_ACTIONS = {
    'view': ('contracts_view',),
    'view_pricing': ('contracts_view', 'contracts_view_pricing'),
    'edit_draft': ('contracts_view', 'contracts_edit_draft'),
    'manage_templates': ('contracts_manage_templates',),
    'submit_approval': ('contracts_view', 'contracts_submit_approval'),
    'approve': ('contracts_view', 'contracts_approve'),
    'send': ('contracts_view', 'contracts_send'),
    'manage_links': ('contracts_view', 'contracts_manage_links'),
    'countersign': ('contracts_view', 'contracts_countersign'),
    'void': ('contracts_view', 'contracts_void'),
    'download_signed': ('contracts_view', 'contracts_download_signed'),
    'view_audit': ('contracts_view', 'contracts_view_audit'),
    'settings': ('contracts_settings',),
}
PROVIDER_WIDE = {'manage_templates', 'settings'}

PORTAL_ACTIONS = {
    'portal_view': ('portal_contract_review', 'portal_contract_sign'),
    'portal_view_pricing': ('portal_contract_review', 'portal_contract_sign', 'portal_billing_contact'),
    'portal_download_signed': ('portal_contract_review', 'portal_contract_sign'),
    'portal_sign': ('portal_contract_sign',),
}

ALL_ACTIONS = tuple(STAFF_ACTIONS) + tuple(PORTAL_ACTIONS)


def _active(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False)
                and getattr(user, 'is_active', False))


def contract_denial(user, contract_org, action, contract=None) -> str:
    """'' when allowed, otherwise the reason."""
    if action not in STAFF_ACTIONS and action not in PORTAL_ACTIONS:
        return f'Unknown contract action {action!r}.'
    if not _active(user):
        return 'Not signed in.'
    org_id = getattr(contract_org, 'pk', contract_org)

    if action in STAFF_ACTIONS:
        if not (user.is_superuser or is_msp_staff(user)):
            return 'Only provider staff can do this.'
        if org_id is None and action not in PROVIDER_WIDE:
            return 'No customer given.'
        for flag in STAFF_ACTIONS[action]:
            if action in PROVIDER_WIDE:
                from .permission_utils import user_has_perm
                if not user_has_perm(user, flag):
                    return f"Your role does not include '{flag}'."
            elif not user_has_org_perm(user, org_id, flag):
                return f"Your role does not include '{flag}' for this customer."
        if action == 'approve' and contract is not None:
            authors = {getattr(contract, 'created_by_id', None), getattr(contract, 'submitted_by_id', None)}
            if user.pk in authors:
                return 'Nobody approves a contract version they wrote or submitted.'
        return ''

    # Portal actions: customer users only.
    if user.is_superuser or is_msp_staff(user):
        return 'Portal contract actions are for the customer.'
    if org_id is None:
        return 'No customer given.'
    memberships = memberships_covering(user, org_id)
    if action == 'portal_sign':
        memberships = [m for m in memberships if m.organization_id == org_id]
    for m in memberships:
        perms = m.get_permissions()
        if any(getattr(perms, flag, False) for flag in PORTAL_ACTIONS[action]):
            return ''
    return 'Your customer role does not include this.'


def can_contract(user, contract_org, action, contract=None) -> bool:
    return contract_denial(user, contract_org, action, contract) == ''


def contract_alert_recipients(users, contract_org, contract=None):
    """The subset of `users` currently allowed to view the contract.

    Call it when an alert is generated AND again right before it is
    delivered (a queued e-mail must not reach someone whose access was
    revoked in between). Staff need `view`; customer users `portal_view`.
    Message bodies should name the contract only by a neutral label and a
    link that re-checks access; never include pricing, clauses or signing
    links in the notification itself."""
    out = []
    for u in users:
        if not _active(u):
            continue
        action = 'view' if (u.is_superuser or is_msp_staff(u)) else 'portal_view'
        if can_contract(u, contract_org, action, contract):
            out.append(u)
    return out
