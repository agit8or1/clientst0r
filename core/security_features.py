"""
Catalog of security safeguards with status and scope, shown on the About
page (Security Features) and the documentation page, so both say the same
thing and nothing is described as stronger than it is.

status:  'enforced'        always on, cannot be switched off
         'on_by_default'   on unless an administrator changes it
         'opt_in'          available, off until configured
         'partial'         works within the stated scope; the gap is named
"""

STATUS_LABELS = {
    'enforced': 'Enforced',
    'on_by_default': 'On by default',
    'opt_in': 'Opt-in',
    'partial': 'Partial',
}

TECHNICIAN_SAFEGUARDS = [
    {
        'key': 'per_route_authorization',
        'title': 'Per-customer technician access',
        'status': 'enforced',
        'scope': 'Ticket AI and RMM tools on every route: ticket page, AI routes, old AI inbox/apply/workflow '
                 'routes, direct IDs, result reads, the gateway (re-checked when a queued job runs).',
        'detail': 'L1/L2/L3 presets or custom presets are assigned per technician or group, per customer. '
                  'A capability and its scope come from the same assignment; explicit denies and customer '
                  'restrictions always win. Staff, admin and superuser flags grant nothing on their own.',
        'link': 'tech_access:index',
        'doc': 'docs/TECHNICIAN_ACCESS.md',
    },
    {
        'key': 'vault_isolation',
        'title': 'AI gateway isolation from the vault',
        'status': 'partial',
        'scope': 'AI provider keys are sealed to the gateway key; the worker runs without APP_MASTER_KEY or '
                 'other secrets. Isolation applies when AI_GATEWAY_MODE=worker; in the default in_process mode '
                 'the web app opens provider keys itself and this is shown as not isolated. The worker runs as '
                 'the same OS user; a separate OS user is a deployment step.',
        'detail': 'Outbound model calls go only to fixed provider hosts or an approved Ollama origin; '
                  'redirects are not followed; metadata addresses and DNS rebinding are refused at connect time.',
        'link': 'psa_ai:profiles',
        'doc': 'docs/TECHNICIAN_ACCESS.md#vault-isolation',
    },
    {
        'key': 'protected_changes',
        'title': 'Two-person protected changes',
        'status': 'enforced',
        'scope': 'Technician access above L1, preset widening, group additions, lifted denies/restrictions, '
                 'Rem0te ticket-processor pairings, Ollama destinations, approvers, recovery contact, loosened '
                 'theft-detection limits, and the e-mail address of superusers, approvers and MSP technicians.',
        'detail': 'The requester re-authenticates (password plus authenticator code), a different approver '
                  're-authenticates and approves. Self-promotion and approving your own recovery address are '
                  'refused; the previously verified recovery contact is notified, and an account\'s old e-mail '
                  'address hears about a move at every step. A one-administrator install cannot widen access.',
        'link': 'tech_access:index',
        'doc': 'docs/TECHNICIAN_ACCESS.md#protected-changes',
    },
    {
        'key': 'theft_detection',
        'title': 'Read-only theft detection',
        'status': 'on_by_default',
        'scope': 'Distinct tickets, customers and exports read, and diagnostic bytes, per identity, across the '
                 'web UI, REST API and mobile API, over 1-hour and 24-hour windows.',
        'detail': 'Tunable thresholds and recipients, optional customer reports, containment by level. '
                  'Alerts carry counts and identities only — no ticket text or secrets.',
        'link': 'tech_access:index',
        'doc': 'docs/TECHNICIAN_ACCESS.md#theft-detection',
    },
    {
        'key': 'no_endpoint_actions',
        'title': 'No endpoint actions or auto-publishing from AI',
        'status': 'enforced',
        'scope': 'Ticket AI Assist and the rem0te integration.',
        'detail': 'ClientSt0r sends no endpoint commands; the run_rmm_script AI action was removed. A draft, '
                  'model vote, remote launch or callback cannot approve a fix, send a customer reply or close '
                  'a ticket — only the composer\'s Send publishes.',
        'link': '',
        'doc': 'docs/contracts/ticket-rmm-v1/README.md',
    },
]


def catalog():
    return [dict(f, status_label=STATUS_LABELS[f['status']]) for f in TECHNICIAN_SAFEGUARDS]
