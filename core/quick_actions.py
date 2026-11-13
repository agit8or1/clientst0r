"""
Dashboard Quick Actions registry + per-user resolution (v3.17.230).

Each entry advertises a single shortcut tile rendered on the user's
dashboard. The user can pick which tiles to show + reorder them via
`/accounts/quick-actions/`. Their selection is stored on
`UserProfile.quick_actions_config` as an ordered list of `key` strings.

Adding a new tile = one entry in `QUICK_ACTIONS_REGISTRY`. The `enabled`
callable receives the request context and returns True/False so we can
gate tiles on feature flags (psa_enabled, vehicles_enabled, etc.) the
same way the static template did before.

Phase 67: every entry also carries `allowed(request)`, which mirrors the
target view's own check (decorators, role flags, the URL-prefix gate in
SectionPermissionMiddleware), so a tile is drawn only when the page would
let the user in. The pages keep their checks; this is presentation.
"""
from types import SimpleNamespace

from django.urls import reverse, NoReverseMatch

MAX_SAVED = 16  # registry size is 12; the cap only bounds a hand-made POST


def _ctx_psa(ctx):
    return bool(ctx.get('psa_enabled'))


def _ctx_vehicles(ctx):
    return bool(ctx.get('vehicles_enabled'))


def _always(ctx):
    return True


def _ctx_reports(ctx):
    # Settings -> Features -> Reports & Analytics (missing = on, as before).
    return ctx.get('reports_enabled', True) is not False


def _ctx_psa_reports(ctx):
    return _ctx_psa(ctx) and _ctx_reports(ctx)


def _w():
    from core import dashboard_widgets as w
    return w


def _any_org_perm(request, perm):
    from accounts.permission_utils import orgs_with_perm
    allowed = orgs_with_perm(request.user, perm)
    return allowed is None or bool(allowed)


def _org_flag(request, flag):
    """`flag` in the selected customer. With none selected the create views
    (require_organization_context, monitoring_perm) let only cross-tenant
    users through, to pick a customer first."""
    w = _w()
    if w.current_org(request) is None:
        return w.is_staff(request)
    return w.org_perm(request, flag)


def _can_ticket(request):
    # psa:ticket_create: @require_write, @require_psa_enabled, then
    # tickets_create for the chosen client.
    return _w().write_ok(request) and _any_org_perm(request, 'tickets_create')


def _can_asset(request):
    # assets:asset_create: /assets/ section (assets_view), @require_write,
    # @org_flag_required('assets_create') in the selected customer.
    w = _w()
    return (w.section_ok(request, 'assets_view') and w.write_ok(request)
            and _org_flag(request, 'assets_create'))


def _can_password(request):
    # vault:password_create: /vault/ section (vault_view), @require_write,
    # vault_create in the customer unless the account has full vault reach.
    w = _w()
    if not (w.section_ok(request, 'vault_view') and w.write_ok(request)):
        return False
    from vault.views import _vault_full_reach
    return _vault_full_reach(request.user) or _org_flag(request, 'vault_create')


def _can_document(request):
    # docs:document_create: /docs/ section (docs_view), @require_write,
    # docs_create in the customer (docs.permissions.can_create_in_org).
    w = _w()
    if not (w.section_ok(request, 'docs_view') and w.write_ok(request)):
        return False
    org = w.current_org(request)
    if org is None:
        return w.is_staff(request)
    from docs.permissions import can_create_in_org
    return can_create_in_org(request.user, org)


def _can_receipt(request):
    # The view needs a login only; the navigation offers Vehicles to MSP
    # staff only, so the tile follows the navigation.
    return _w().is_staff(request)


def _can_quote(request):
    # psa:quote_create: @require_write, PSA on, MSP staff only
    # (_require_quote_writer).
    return _w().write_ok(request) and _w().is_staff(request)


def _can_invoice(request):
    # psa:invoice_create: @require_write and billing_send_invoices somewhere.
    return _w().write_ok(request) and _any_org_perm(request, 'billing_send_invoices')


def _can_evidence(request):
    # compliance:evidence_pack: compliance.views._user_can_access_pack.
    org = _w().current_org(request)
    if org is None:
        return False
    from compliance.views import _user_can_access_pack
    return _user_can_access_pack(request.user, org)


def _can_wallboards(request):
    # reports:wallboard_list: /reports/ is MSP staff only, then
    # @require_perm('reports_view_dashboards').
    from accounts.permission_utils import user_has_perm
    return _w().is_staff(request) and user_has_perm(request.user, 'reports_view_dashboards')


def _can_agreement_recon(request):
    # reports:agreement_reconciliation: staff only and
    # @require_msp_wide_perm('reports_view_financial', legacy='staff').
    from reports.access import has_msp_wide_perm
    return _w().is_staff(request) and has_msp_wide_perm(
        request.user, 'reports_view_financial', legacy='staff')


def _signed_in(request):
    # processes:process_list and processes:runbook_dashboard need a login and
    # a selected customer (or MSP staff in Global View).
    return request.user.is_authenticated


# (key, label, icon (FA), url-name, tooltip, gate-callable, allowed(request))
QUICK_ACTIONS_REGISTRY = [
    {'key': 'new_ticket', 'label': 'New Ticket',
     'icon': 'fa-headset', 'url_name': 'psa:ticket_create',
     'tooltip': 'Create a new support ticket', 'enabled': _ctx_psa,
     'allowed': _can_ticket},
    {'key': 'add_asset', 'label': 'Add Asset',
     'icon': 'fa-server', 'url_name': 'assets:asset_create',
     'tooltip': 'Add a new asset to inventory', 'enabled': _always,
     'allowed': _can_asset},
    {'key': 'new_password', 'label': 'New Password',
     'icon': 'fa-key', 'url_name': 'vault:password_create',
     'tooltip': 'Create a new encrypted password', 'enabled': _always,
     'allowed': _can_password},
    {'key': 'add_document', 'label': 'Add Document',
     'icon': 'fa-file-alt', 'url_name': 'docs:document_create',
     'tooltip': 'Create a new documentation article', 'enabled': _always,
     'allowed': _can_document},
    {'key': 'scan_receipt', 'label': 'Scan Receipt',
     'icon': 'fa-receipt', 'url_name': 'vehicles:receipt_quick',
     'tooltip': 'Quickly scan or upload a receipt', 'enabled': _ctx_vehicles,
     'allowed': _can_receipt},
    {'key': 'run_workflow', 'label': 'Run Workflow',
     'icon': 'fa-diagram-project', 'url_name': 'processes:process_list',
     'tooltip': 'Pick a workflow template and run it on a client',
     'enabled': _always, 'allowed': _signed_in},
    {'key': 'new_quote', 'label': 'New Quote',
     'icon': 'fa-file-signature', 'url_name': 'psa:quote_create',
     'tooltip': 'Create a new quote', 'enabled': _ctx_psa,
     'allowed': _can_quote},
    {'key': 'new_invoice', 'label': 'New Invoice',
     'icon': 'fa-file-invoice-dollar', 'url_name': 'psa:invoice_create',
     'tooltip': 'Create a new invoice', 'enabled': _ctx_psa,
     'allowed': _can_invoice},
    {'key': 'evidence_pack', 'label': 'Evidence Pack',
     'icon': 'fa-shield-halved',
     'url_name': None,  # resolved per-org at render time
     'tooltip': 'Generate compliance evidence pack for the active org',
     'enabled': _always, 'requires_org': True, 'allowed': _can_evidence},
    {'key': 'wallboard', 'label': 'Wallboards',
     'icon': 'fa-tv', 'url_name': 'reports:wallboard_list',
     'tooltip': 'TV-ready dashboards', 'enabled': _ctx_reports,
     'allowed': _can_wallboards},
    {'key': 'agreement_recon', 'label': 'Agreement Recon.',
     'icon': 'fa-balance-scale', 'url_name': 'reports:agreement_reconciliation',
     'tooltip': 'Agreement Reconciliation report', 'enabled': _ctx_psa_reports,
     'allowed': _can_agreement_recon},
    {'key': 'runbook_dashboard', 'label': 'Runbooks',
     'icon': 'fa-tasks', 'url_name': 'processes:runbook_dashboard',
     'tooltip': 'Per-org runbook completion dashboard', 'enabled': _always,
     'allowed': _signed_in},
]

# Default ordering when a user hasn't customized.
DEFAULT_QUICK_ACTION_KEYS = [
    'new_ticket', 'add_asset', 'new_password', 'add_document',
    'scan_receipt', 'run_workflow', 'new_quote', 'new_invoice',
]


def get_action(key):
    for a in QUICK_ACTIONS_REGISTRY:
        if a['key'] == key:
            return a
    return None


def clean_keys(keys):
    """Known action keys only, de-duplicated, at most MAX_SAVED."""
    out, seen = [], set()
    for k in (keys or [])[:MAX_SAVED * 4]:
        if isinstance(k, str) and k not in seen and get_action(k):
            seen.add(k)
            out.append(k)
    return out[:MAX_SAVED]


def action_allowed(action, request):
    """The target view's check for this user (fails closed)."""
    check = action.get('allowed')
    if check is None:
        return False
    try:
        return bool(check(request))
    except Exception:
        return False


def resolve_for_user(user, context, request=None):
    """
    Return the ordered, gated, URL-resolved list of action dicts to
    render for `user`. `context` is a flat dict containing
    `psa_enabled` / `vehicles_enabled` / `current_organization` etc.
    Unknown keys + actions whose URL won't reverse are silently dropped,
    and so is every action whose target page would refuse the user.
    """
    profile = getattr(user, 'profile', None)
    saved = (getattr(profile, 'quick_actions_config', None) or []) if profile else []
    keys = clean_keys(saved)
    if not keys:
        keys = list(DEFAULT_QUICK_ACTION_KEYS)

    org = context.get('current_organization')
    if request is None:
        # The context processor has no request handy: the checks need only
        # the user and the selected customer.
        request = SimpleNamespace(user=user, current_organization=org)
    out = []
    for key in keys:
        action = get_action(key)
        if not action:
            continue
        try:
            if not action['enabled'](context):
                continue
        except Exception:
            continue
        if action.get('requires_org') and not org:
            continue
        if not action_allowed(action, request):
            continue

        url = ''
        if action.get('url_name'):
            try:
                url = reverse(action['url_name'])
            except NoReverseMatch:
                continue
        elif key == 'evidence_pack' and org:
            try:
                url = reverse('compliance:evidence_pack', kwargs={'org_id': org.id})
            except NoReverseMatch:
                continue
        if not url:
            continue
        out.append({
            'key': key,
            'label': action['label'],
            'icon': action['icon'],
            'url': url,
            'tooltip': action.get('tooltip', ''),
        })
    return out
