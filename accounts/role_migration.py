"""
Roles & access migration: preserve existing access explicitly, then list
what an administrator should review.

Used by accounts 0046 (historical models, passed in) and by
`manage.py roles_migration_report` (live models). It never decides anything
from a username, e-mail address or job title, never removes access and
never hands anybody a new powerful role: it only

  1. sets the permissions introduced by this program on EXISTING role
     templates to values that keep what their holders could already do
     (EXPLICIT_MAPPING below), and
  2. records ambiguous assignments as RoleReviewItem rows.

Memberships without a template keep the simple role; their new
permissions come from accounts.models.LEGACY_ROLE_EXTRA_FLAGS and
accounts.models.derive_legacy_flags, which follow the same mapping.
"""
from __future__ import annotations

WRITE_FLAGS = ('vault_create', 'assets_create', 'docs_create', 'files_upload', 'monitoring_create')

# new permission -> how its value is derived for an existing role template
EXPLICIT_MAPPING = [
    ('roles_manage', 'org_manage_settings',
     'Whoever could change organization settings could manage roles (Membership.can_admin).'),
    ('org_manage_privileged', 'org_manage_members AND org_manage_settings',
     'Assigning any role needed only org_manage_members before; now roles holding administration need '
     'this too. Kept for roles that also manage settings (owner-like); customer admin-style roles lose it.'),
    ('tickets_view_internal', 'True',
     'Every MSP staff role saw internal notes; customers never do (staff-only permission).'),
    ('quotes_view', 'True', 'Quotes were readable by every role.'),
    ('quotes_edit / quotes_send / quotes_approve_discount', 'any write permission',
     'Quotes were gated by "can write" (any create / upload permission).'),
    ('portal_tickets_view_org / portal_tickets_create / portal_tickets_reply / portal_approve_requests / '
     'portal_agreements_view_org', 'True',
     "Every portal user saw all of the customer's shared tickets, could file and reply to tickets, decide "
     "client approvals and see coworkers' agreement signatures."),
    ('billing_approve_invoices / billing_issue_credit / billing_manage_charges', 'billing_send_invoices',
     'These actions were gated by billing_send_invoices.'),
    ('crm_approve_commissions', 'crm_view_forecast', 'Commission decisions were gated by the forecast flag.'),
    ('timesheets_approve', 'resourcing_approve_leave', 'Timesheet review was gated by the leave-approval flag.'),
    ('reports_export', 'True', 'Exports rode on the report page view permission.'),
    ('vehicles_view', 'True', 'Fleet pages had no role permission.'),
    ('vehicles_manage', 'any write permission', 'Fleet records were editable by any writer.'),
    ('scheduling_manage_wallboard / psa_manage_workflow_rules', 'org_manage_settings',
     'Gated by require_admin (Membership.can_admin) before.'),
    ('vault_approve_reveal / netconfig_view_configs', 'vault_view_password',
     'Reveal approval and stored device configurations were gated by vault_view_password.'),
    ('integrations_view_synced_psa', 'integrations_view', 'Synced PSA data was gated by integrations_view.'),
    ('docs_view_internal', 'False', 'Customer users do not see internal documentation unless granted.'),
    ('resourcing_view_payroll', 'only Owner / Full Admin',
     'Gated by Django is_staff only before; not inferred for other roles.'),
    ('contracts_*', 'only Owner / Full Admin',
     'New feature: denied until assigned, except for the full-access owner templates.'),
    ('org_owner', 'only Owner / Full Admin', 'Owner identity; given otherwise only by ownership transfer.'),
    ('portal_billing_contact / portal_contract_review / portal_contract_sign', 'False',
     'New customer permissions: never granted automatically (a customer administrator is not a signer).'),
]

FULL_ACCESS_NAMES = ('Owner', 'Full Admin')


def preserve_existing_access(RoleTemplate):
    """Step 1, for templates that existed before the program (no seed_key)."""
    from .role_seeds import CONTRACT_KEYS
    changed = []
    for rt in RoleTemplate.objects.filter(seed_key=''):
        before = {}
        full = rt.organization_id is None and rt.name in FULL_ACCESS_NAMES
        writer = any(getattr(rt, f) for f in WRITE_FLAGS)
        values = {
            'roles_manage': bool(rt.org_manage_settings) or full,
            'org_manage_privileged': (bool(rt.org_manage_members) and bool(rt.org_manage_settings)) or full,
            'tickets_view_internal': True,
            'quotes_view': True,
            'quotes_edit': writer or full,
            'quotes_send': writer or full,
            'quotes_approve_discount': writer or full,
            'portal_tickets_view_org': True,
            'portal_tickets_create': True,
            'portal_tickets_reply': True,
            'portal_approve_requests': True,
            'portal_agreements_view_org': True,
            'billing_approve_invoices': bool(rt.billing_send_invoices) or full,
            'billing_issue_credit': bool(rt.billing_send_invoices) or full,
            'billing_manage_charges': bool(rt.billing_send_invoices) or full,
            'crm_approve_commissions': bool(rt.crm_view_forecast) or full,
            'timesheets_approve': bool(rt.resourcing_approve_leave) or full,
            'reports_export': True,
            'vehicles_view': True,
            'vehicles_manage': writer or full,
            'scheduling_manage_wallboard': bool(rt.org_manage_settings) or full,
            'psa_manage_workflow_rules': bool(rt.org_manage_settings) or full,
            'resourcing_view_payroll': full,
            'vault_approve_reveal': bool(rt.vault_view_password) or full,
            'netconfig_view_configs': bool(rt.vault_view_password) or full,
            'integrations_view_synced_psa': bool(rt.integrations_view) or full,
            'docs_view_internal': False,
            'org_owner': full,
        }
        for k in CONTRACT_KEYS:
            values[k] = full
        for k, v in values.items():
            before[k] = getattr(rt, k)
            setattr(rt, k, v)
        if any(before[k] != v for k, v in values.items()):
            rt.save()
            changed.append(rt.name)
    return changed


def _is_staff(profile):
    return profile is not None and profile.user_type == 'staff'


def find_review_items(Membership, UserProfile, RoleTemplate, Organization, User):
    """Step 2: [(reason, dict(user=, organization=, membership=, role_template=, detail=))]."""
    from .permission_registry import CUSTOMER_ASSIGNABLE_KEYS, ALL_KEYS
    items = []
    profiles = {p.user_id: p for p in UserProfile.objects.all()}

    for p in UserProfile.objects.filter(user_type='staff', global_role_template__isnull=True,
                                        user__is_active=True, user__is_superuser=False):
        items.append(('staff_no_global_role', dict(
            user_id=p.user_id,
            detail='MSP staff account without a global role: a permission any of its memberships grants '
                   'applies at every client (vault permissions only where a membership grants them). Give it '
                   'a global role (and a client scope) or confirm.')))

    for m in Membership.objects.filter(is_active=True, user__is_active=True).select_related('role_template'):
        prof = profiles.get(m.user_id)
        customer = not _is_staff(prof) and not m.user.is_superuser and not m.user.is_staff
        rt = m.role_template
        if customer and rt is None and m.role in ('owner', 'admin', 'editor'):
            items.append(('customer_legacy_write_role', dict(
                user_id=m.user_id, organization_id=m.organization_id, membership_id=m.pk,
                detail=f'Customer user on the simple {m.role.title()} role: it can create and edit '
                       'documentation and assets and reveal vault passwords of this customer. Pick a customer '
                       'role (Customer Administrator / Manager / Standard User / Read-Only) or confirm.')))
        if customer and rt is not None:
            extra = sorted(k for k in ALL_KEYS if getattr(rt, k, False) and k not in CUSTOMER_ASSIGNABLE_KEYS)
            if extra:
                items.append(('customer_internal_role', dict(
                    user_id=m.user_id, organization_id=m.organization_id, membership_id=m.pk,
                    role_template_id=rt.pk,
                    detail=f"Customer user holds '{rt.name}', which includes internal permissions: "
                           + ', '.join(extra[:12]) + ('...' if len(extra) > 12 else ''))))
        if rt is not None and m.role in ('owner', 'admin') and not (rt.org_manage_settings or rt.org_owner):
            items.append(('template_overrides_role', dict(
                user_id=m.user_id, organization_id=m.organization_id, membership_id=m.pk,
                role_template_id=rt.pk,
                detail=f"Saved as simple role {m.role.title()} with the template '{rt.name}'. The template "
                       'decides (it always overrode the simple role for permissions); the simple role no '
                       'longer makes the member an administrator.')))

    for m in Membership.objects.filter(is_active=True, user__is_active=False, role='owner',
                                       role_template__isnull=True):
        items.append(('inactive_user_owner', dict(
            user_id=m.user_id, organization_id=m.organization_id, membership_id=m.pk,
            detail='Owner membership of a deactivated account: it does not count as an active owner.')))

    for org in Organization.objects.filter(is_active=True):
        owners = Membership.objects.filter(organization=org, is_active=True, user__is_active=True)
        has_owner = (owners.filter(role_template__isnull=True, role='owner').exists()
                     or owners.filter(role_template__org_owner=True).exists())
        if not has_owner:
            items.append(('no_active_owner', dict(
                organization_id=org.pk,
                detail='No active owner. Superusers and MSP staff still manage it; add an owner if the '
                       'organization should administer itself.')))
    return items


def record_review_items(RoleReviewItem, items, source):
    created = 0
    for reason, data in items:
        lookup = {k: data.get(k) for k in ('user_id', 'organization_id', 'membership_id', 'role_template_id')}
        _, was_created = RoleReviewItem.objects.get_or_create(
            reason=reason, status='open', **lookup,
            defaults={'detail': data.get('detail', ''), 'source': source})
        created += int(was_created)
    return created
