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
"""
from django.urls import reverse, NoReverseMatch


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


# (key, label, icon (FA), url-name, tooltip, gate-callable)
QUICK_ACTIONS_REGISTRY = [
    {'key': 'new_ticket', 'label': 'New Ticket',
     'icon': 'fa-headset', 'url_name': 'psa:ticket_create',
     'tooltip': 'Create a new support ticket', 'enabled': _ctx_psa},
    {'key': 'add_asset', 'label': 'Add Asset',
     'icon': 'fa-server', 'url_name': 'assets:asset_create',
     'tooltip': 'Add a new asset to inventory', 'enabled': _always},
    {'key': 'new_password', 'label': 'New Password',
     'icon': 'fa-key', 'url_name': 'vault:password_create',
     'tooltip': 'Create a new encrypted password', 'enabled': _always},
    {'key': 'add_document', 'label': 'Add Document',
     'icon': 'fa-file-alt', 'url_name': 'docs:document_create',
     'tooltip': 'Create a new documentation article', 'enabled': _always},
    {'key': 'scan_receipt', 'label': 'Scan Receipt',
     'icon': 'fa-receipt', 'url_name': 'vehicles:receipt_quick',
     'tooltip': 'Quickly scan or upload a receipt', 'enabled': _ctx_vehicles},
    {'key': 'run_workflow', 'label': 'Run Workflow',
     'icon': 'fa-diagram-project', 'url_name': 'processes:process_list',
     'tooltip': 'Pick a workflow template and run it on a client',
     'enabled': _always},
    {'key': 'new_quote', 'label': 'New Quote',
     'icon': 'fa-file-signature', 'url_name': 'psa:quote_create',
     'tooltip': 'Create a new quote', 'enabled': _ctx_psa},
    {'key': 'new_invoice', 'label': 'New Invoice',
     'icon': 'fa-file-invoice-dollar', 'url_name': 'psa:invoice_create',
     'tooltip': 'Create a new invoice', 'enabled': _ctx_psa},
    {'key': 'evidence_pack', 'label': 'Evidence Pack',
     'icon': 'fa-shield-halved',
     'url_name': None,  # resolved per-org at render time
     'tooltip': 'Generate compliance evidence pack for the active org',
     'enabled': _always, 'requires_org': True},
    {'key': 'wallboard', 'label': 'Wallboards',
     'icon': 'fa-tv', 'url_name': 'reports:wallboard_list',
     'tooltip': 'TV-ready dashboards', 'enabled': _ctx_reports},
    {'key': 'agreement_recon', 'label': 'Agreement Recon.',
     'icon': 'fa-balance-scale', 'url_name': 'reports:agreement_reconciliation',
     'tooltip': 'Agreement Reconciliation report', 'enabled': _ctx_psa_reports},
    {'key': 'runbook_dashboard', 'label': 'Runbooks',
     'icon': 'fa-tasks', 'url_name': 'processes:runbook_dashboard',
     'tooltip': 'Per-org runbook completion dashboard', 'enabled': _always},
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


def resolve_for_user(user, context):
    """
    Return the ordered, gated, URL-resolved list of action dicts to
    render for `user`. `context` is a flat dict containing
    `psa_enabled` / `vehicles_enabled` / `current_organization` etc.
    Unknown keys + actions whose URL won't reverse are silently dropped.
    """
    profile = getattr(user, 'profile', None)
    saved = (getattr(profile, 'quick_actions_config', None) or []) if profile else []
    keys = [k for k in saved if get_action(k)]
    if not keys:
        keys = list(DEFAULT_QUICK_ACTION_KEYS)

    org = context.get('current_organization')
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
