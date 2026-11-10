"""
Catalog of security safeguards, grouped the way an administrator thinks about
them, shown on the About page, the documentation page and the administrators'
Security Features page — so all three say the same thing and nothing is
described as stronger than it is.

Each entry says what it protects, its default, what it needs before it works,
where it is configured, and the doc and tests that back it. The public pages
show only that shipped description. The administrators' page adds the
effective state at one customer (`effective_states`), read from the same
settings the code enforces, with environment overrides named.

status:  'enforced'        always on, cannot be switched off
         'on_by_default'   on unless an administrator changes it
         'opt_in'          available, off until configured
         'partial'         works within the stated scope; the gap is named

Planned safeguards don't belong here; they stay in docs/ROADMAP.md.
"""
from django.conf import settings

STATUS_LABELS = {
    'enforced': 'Enforced',
    'on_by_default': 'On by default',
    'opt_in': 'Opt-in',
    'partial': 'Partial',
}

GROUPS = [
    ('signin', 'Sign-in'),
    ('client_access', 'Client access'),
    ('vault', 'Vault and secrets'),
    ('tickets_ai', 'Tickets and AI'),
    ('audit', 'Audit'),
]

FEATURES = [
    # ---- Sign-in ---------------------------------------------------------
    {
        'key': 'two_factor',
        'group': 'signin',
        'title': 'Two-factor sign-in',
        'status': 'on_by_default',
        'protects': 'Accounts whose password is guessed or reused elsewhere.',
        'default': 'Required for every user: a user without an authenticator is sent to set one up.',
        'prerequisites': 'None. Azure AD single sign-on sessions skip the TOTP step (the identity provider is '
                         'trusted for it); each such sign-in is audited as azure_ad_2fa_bypass.',
        'detail': 'TOTP authenticator codes. A password-only session (for example from /admin/login/) is ended '
                  'and sent through the two-factor sign-in.',
        'link': 'core:settings_security',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#sign-in',
        'tests': ['core.tests.test_security_policy', 'core.tests.test_security_hardening'],
    },
    {
        'key': 'lockout',
        'group': 'signin',
        'title': 'Failed sign-in lockout',
        'status': 'on_by_default',
        'protects': 'Accounts against password guessing.',
        'default': '5 failed attempts for the same username and address lock sign-in for 30 minutes.',
        'prerequisites': 'None.',
        'detail': 'django-axes, keyed on username plus IP address; reset on a successful sign-in.',
        'link': 'core:settings_security',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#sign-in',
        'tests': ['core.tests.test_security_policy'],
    },
    {
        'key': 'password_policy',
        'group': 'signin',
        'title': 'Password rules and hashing',
        'status': 'enforced',
        'protects': 'Stored sign-in passwords, if the database is copied.',
        'default': 'At least 12 characters including a special character; stored as Argon2 hashes.',
        'prerequisites': 'None. Hashes made before v3.17.650 (PBKDF2) are re-hashed with Argon2 at next sign-in.',
        'detail': 'Common-password and similarity checks also apply.',
        'link': 'core:settings_security',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#sign-in',
        'tests': ['security_tests.test_release_650'],
    },
    {
        'key': 'sessions',
        'group': 'signin',
        'title': 'Session time limits',
        'status': 'on_by_default',
        'protects': 'Unattended or stolen browser sessions.',
        'default': 'Signed out after 60 minutes idle and 8 hours after sign-in.',
        'prerequisites': 'None. Mobile app tokens are separate: they last until revoked unless '
                         'MOBILE_TOKEN_TTL_DAYS is set.',
        'detail': 'Session cookies are Secure and HttpOnly behind HTTPS; HSTS is one year.',
        'link': 'core:settings_security',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#sign-in',
        'tests': ['core.tests.test_security_policy'],
    },
    {
        'key': 'network_firewall',
        'group': 'signin',
        'title': 'IP and country firewall',
        'status': 'opt_in',
        'protects': 'The sign-in page and app from unexpected networks or countries.',
        'default': 'Off.',
        'prerequisites': 'A GeoIP country database for country rules. Covers the web app.',
        'detail': 'Allow or block lists by address range or country; blocked requests are logged.',
        'link': 'core:firewall_settings',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#sign-in',
        'tests': ['core.tests.test_geoip_firewall', 'core.tests.test_client_ip'],
    },
    {
        'key': 'csp',
        'group': 'signin',
        'title': 'Content Security Policy',
        'status': 'partial',
        'protects': 'Pages against injected scripts.',
        'default': 'Report-only: violations are logged, not blocked.',
        'prerequisites': 'Set CSP_REPORT_ONLY=False to enforce, after checking the security.csp log.',
        'detail': 'Templates use nonces and no inline event handlers.',
        'link': '',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#limitations',
        'tests': ['core.tests.test_csp'],
    },
    # ---- Client access ---------------------------------------------------
    {
        'key': 'org_roles',
        'group': 'client_access',
        'title': 'Per-customer roles',
        'status': 'enforced',
        'protects': "One customer's records from another customer's users.",
        'default': 'A customer user sees only organizations they are a member of, with that membership\'s role '
                   '(Owner, Admin, Editor, Read-only, or a custom role).',
        'prerequisites': 'None. A membership in a parent organization also covers its subsidiaries.',
        'detail': 'MSP staff (User Type Staff) and superusers reach every customer by design; a staff global '
                  'role narrows what they can do there. The vault is the exception: see "Vault titles stay '
                  'inside assigned customers".',
        'link': 'accounts:role_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#who-can-see-what',
        'tests': ['accounts.tests', 'psa.tests.test_internal_ticket_visibility'],
    },
    {
        'key': 'customer_ticket_view',
        'group': 'client_access',
        'title': "Customers see their tickets' shared conversation only",
        'status': 'enforced',
        'protects': 'Internal notes and technician working data.',
        'default': 'Customer users see tickets shared with them and the public conversation; internal notes, '
                   'time, expenses, kit, workflows, similar tickets and RMM data stay with technicians.',
        'prerequisites': 'None.',
        'detail': 'Technician actions answer 403 to customer users even by direct URL; a customer\'s '
                  'attachment is always public.',
        'link': '',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#a-shared-ticket-seen-by-the-customer',
        'tests': ['psa.tests.test_customer_on_staff_ticket_page', 'psa.tests.test_internal_ticket_visibility', 'integrations.tests_rmm_association'],
    },
    {
        'key': 'per_route_authorization',
        'group': 'client_access',
        'title': 'Per-customer technician access',
        'status': 'enforced',
        'protects': 'Ticket AI and RMM tools, per customer.',
        'default': 'No technician can use ticket AI or RMM tools at a customer until an L1/L2/L3 (or custom) '
                   'preset is assigned there.',
        'prerequisites': 'An assignment per technician or group, per customer.',
        'detail': 'Checked on every route: ticket page, AI routes, direct IDs, result reads, the gateway '
                  '(re-checked when a queued job runs). Explicit denies and customer restrictions always win. '
                  'Staff, admin and superuser flags grant nothing on their own.',
        'link': 'tech_access:index',
        'doc': 'docs/TECHNICIAN_ACCESS.md',
        'tests': ['tech_access.tests'],
    },
    {
        'key': 'protected_changes',
        'group': 'client_access',
        'title': 'Two-person protected changes',
        'status': 'enforced',
        'protects': 'Access and security settings against one compromised or rogue administrator.',
        'default': 'On; cannot be switched off.',
        'prerequisites': 'A second administrator to approve. A one-administrator install cannot widen access.',
        'detail': 'Technician access above L1, preset widening, group additions, lifted denies/restrictions, '
                  'Rem0te ticket-processor pairings, Ollama destinations, approvers, recovery contact, loosened '
                  'theft-detection limits, and the e-mail address of superusers, approvers and MSP technicians. '
                  'The requester and a different approver each re-authenticate (password plus authenticator '
                  'code). Granting superuser joins them when Superuser Approval is on.',
        'link': 'tech_access:index',
        'doc': 'docs/TECHNICIAN_ACCESS.md#protected-changes',
        'tests': ['tech_access.tests'],
    },
    {
        'key': 'superuser_approval',
        'group': 'client_access',
        'title': 'Superuser Approval',
        'status': 'opt_in',
        'protects': 'Installation-wide control from being handed out by one administrator.',
        'default': 'Off on upgrade. When on, a superuser grant waits for a different administrator.',
        'prerequisites': 'Two different eligible administrators (active superusers who approve protected '
                         'changes). Turning it off again is itself a protected change.',
        'detail': 'Covers creating a superuser and promoting an account on the user page and in Django admin. '
                  'Host-level commands (manage.py createsuperuser, the Django shell) are outside the app: '
                  'recorded and announced, not blocked.',
        'link': 'tech_access:superuser_policy',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#granting-superuser',
        'tests': ['tech_access.tests_superuser_653'],
    },
    {
        'key': 'vault_title_scope',
        'group': 'client_access',
        'title': 'Vault titles stay inside assigned customers',
        'status': 'enforced',
        'protects': 'What a credential\'s title, username or count says about a customer, e.g. "Payroll '
                    'Administrator".',
        'default': 'A technician sees a customer\'s vault entries only where a membership grants "view vault", '
                   'or everywhere when their global role grants it.',
        'prerequisites': 'None. Admin → Security → Vault Visibility lists staff who lost cross-customer '
                         'visibility in 3.17.653; it grants nothing.',
        'detail': 'Applies to the web vault and its counts, global search, REST, GraphQL and mobile APIs, the '
                  'browser extension, dashboards, process-stage pickers, relationship maps, readiness and '
                  'vault reports. Seeing an entry and revealing it remain separate permissions.',
        'link': 'core:vault_visibility',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#who-can-see-what',
        'tests': ['vault.tests_release_653', 'accounts.tests_view_permissions'],
    },
    # ---- Vault and secrets -----------------------------------------------
    {
        'key': 'encryption_at_rest',
        'group': 'vault',
        'title': 'Encrypted secrets at rest',
        'status': 'enforced',
        'protects': 'Vault passwords, TOTP seeds and stored integration credentials, if the database is copied.',
        'default': 'AES-256-GCM with a separate HKDF-derived key per purpose, from APP_MASTER_KEY.',
        'prerequisites': 'APP_MASTER_KEY kept outside the database (production refuses to start without it).',
        'detail': 'API tokens are stored as HMAC-SHA256 hashes. Ticket text and attachments are not encrypted '
                  'by the app.',
        'link': '',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#encryption',
        'tests': ['vault.tests_secrets_at_rest'],
    },
    {
        'key': 'reveal_permission',
        'group': 'vault',
        'title': 'Reveal permission per customer',
        'status': 'enforced',
        'protects': 'Credential values, separately from credential titles.',
        'default': 'Owner, Admin and Editor roles may reveal; Read-only may not; new custom roles may not '
                   'unless "View actual password values" is ticked.',
        'prerequisites': 'None.',
        'detail': 'The same check guards the web vault, REST API, mobile API and browser extension; '
                  'reveals are limited to 30 per hour per user.',
        'link': 'accounts:role_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#revealing-a-vault-credential',
        'tests': ['vault.tests', 'security_tests.test_vault_and_proxy', 'security_tests.test_release_650'],
    },
    {
        'key': 'reveal_approval',
        'group': 'vault',
        'title': 'Approval before reveal',
        'status': 'opt_in',
        'protects': 'Selected high-value credentials.',
        'default': 'Off; switched on per credential.',
        'prerequisites': 'Someone to approve requests. Break-glass self-approval needs a written justification '
                         'and is audited.',
        'detail': 'An approval is single-use and time-limited.',
        'link': 'vault:reveal_request_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#revealing-a-vault-credential',
        'tests': ['vault.tests'],
    },
    {
        'key': 'access_rules',
        'group': 'vault',
        'title': 'Vault access rules',
        'status': 'opt_in',
        'protects': 'Reveals from unexpected places or times.',
        'default': 'No rules; reveal is allowed wherever the permission allows it.',
        'prerequisites': 'A GeoIP database for country conditions.',
        'detail': 'Allow or deny by country, address range and time, per credential, user or customer. Deny '
                  'wins; if the rules can\'t be evaluated, reveal is refused.',
        'link': 'vault:access_rule_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#revealing-a-vault-credential',
        'tests': ['vault.tests_extension_gate'],
    },
    {
        'key': 'breach_check',
        'group': 'vault',
        'title': 'Breached password check',
        'status': 'on_by_default',
        'protects': 'Customers from vault passwords that appear in public breach lists.',
        'default': 'Checked on save and in a daily scan.',
        'prerequisites': 'Outbound HTTPS to the HaveIBeenPwned range API. Only the first 5 characters of a '
                         'SHA-1 hash are sent.',
        'detail': 'Results show on each entry; nothing is changed automatically.',
        'link': '',
        'doc': 'SECURITY.md',
        'tests': ['vault.tests_release_652', 'core.tests.test_scheduler_periodic_jobs'],
    },
    {
        'key': 'vault_isolation',
        'group': 'vault',
        'title': 'AI gateway isolation from the vault',
        'status': 'partial',
        'protects': 'Vault keys from the process that talks to AI providers.',
        'default': 'Not isolated: AI_GATEWAY_MODE=in_process, and the web app opens provider keys itself.',
        'prerequisites': 'AI_GATEWAY_MODE=worker and a gateway worker running without APP_MASTER_KEY. The '
                         'worker runs as the same OS user unless you deploy it as another.',
        'detail': 'Outbound model calls go only to fixed provider hosts or an approved Ollama origin; '
                  'redirects are not followed; metadata addresses and DNS rebinding are refused.',
        'link': 'psa_ai:profiles',
        'doc': 'docs/TECHNICIAN_ACCESS.md#vault-isolation',
        'tests': ['psa_ai.tests'],
    },
    {
        'key': 'offline_cache',
        'group': 'vault',
        'title': 'Browser-extension offline cache',
        'status': 'opt_in',
        'protects': 'Restricted credentials from being usable on a device without a live check.',
        'default': 'Off: no role has "extension offline cache" unless you tick it.',
        'prerequisites': 'The extension role permission at the customer.',
        'detail': 'Entries that need approval, or that any active access rule applies to (on the entry, its '
                  'customer, or the technician), sync without their secret and say "Connect to ClientSt0r to '
                  'reveal this password." The next complete sync replaces older local copies; a device that '
                  'stays offline keeps its copy until it reconnects.',
        'link': 'vault:access_rule_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#offline-copies-in-the-browser-extension',
        'tests': ['vault.tests_release_653', 'vault.tests_release_652'],
    },
    # ---- Tickets and AI --------------------------------------------------
    {
        'key': 'ai_opt_in',
        'group': 'tickets_ai',
        'title': 'Ticket AI is off until enabled per customer (OPTIONAL AI)',
        'status': 'opt_in',
        'protects': 'Ticket data from leaving the server without a decision.',
        'default': 'Off: AI features off globally, and no customer has an AI policy.',
        'prerequisites': 'A superuser turns on AI in Settings, adds a provider profile, and sets each '
                         "customer's AI policy (analysis, comparison, allowed profiles, daily budget, "
                         "on-premises only, technicians' own keys).",
        'detail': "Provider keys are write-only once saved. A technician's own key is usable only by them and "
                  'only where the customer allows it.',
        'link': 'psa_ai:profiles',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#ticket-ai',
        'tests': ['psa_ai.tests', 'psa_ai.tests_assist'],
    },
    {
        'key': 'ai_evidence',
        'group': 'tickets_ai',
        'title': 'What ticket AI may see',
        'status': 'enforced',
        'protects': 'Secrets and internal notes from AI providers.',
        'default': 'Subject, description, the public conversation and a verified asset/RMM status summary, '
                   'redacted, and shown to the technician before sending.',
        'prerequisites': 'None.',
        'detail': 'Never included: vault data, attachments, internal-note bodies, raw RMM payloads, session '
                  'or remote-access data. Keys, passwords, tokens, card numbers, e-mail addresses and phone '
                  'numbers are redacted.',
        'link': '',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#ticket-ai',
        'tests': ['psa_ai.tests_assist'],
    },
    {
        'key': 'no_endpoint_actions',
        'group': 'tickets_ai',
        'title': 'No endpoint actions or auto-publishing from AI',
        'status': 'enforced',
        'protects': 'Customer devices and customer-facing replies from unreviewed AI output.',
        'default': 'On; cannot be switched off.',
        'prerequisites': 'None.',
        'detail': 'ClientSt0r sends no endpoint commands. A draft, model vote, remote launch or callback '
                  'cannot approve a fix, send a customer reply or close a ticket; only the composer\'s Send '
                  'publishes. Endpoint access is decided by rem0te, not ClientSt0r.',
        'link': '',
        'doc': 'docs/contracts/ticket-rmm-v1/README.md',
        'tests': ['psa_ai.tests_assist', 'tech_access.tests'],
    },
    # ---- Audit -----------------------------------------------------------
    {
        'key': 'audit_log',
        'group': 'audit',
        'title': 'Audit log',
        'status': 'partial',
        'protects': 'Accountability: who did what, when, from where.',
        'default': 'On: sign-ins, record changes, reveals and access decisions are recorded per customer.',
        'prerequisites': 'None.',
        'detail': 'Not tamper-proof: superusers can delete entries (Django admin, and the maintenance clean-up). '
                  'Each deletion is itself recorded with a count. There is no automatic retention, and exports '
                  'are not themselves recorded.',
        'link': 'audit:audit_log_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#limitations',
        'tests': ['audit.tests'],
    },
    {
        'key': 'reveal_audit',
        'group': 'audit',
        'title': 'Every reveal is recorded',
        'status': 'enforced',
        'protects': 'Credential use, after the fact.',
        'default': "On: a reveal (or copy) writes an audit event with the user, credential, customer and address.",
        'prerequisites': 'None.',
        'detail': 'Recorded as action "reveal", object type "password", from the web vault, REST API, mobile '
                  'API and browser extension; a copy is recorded as a reveal.',
        'link': 'audit:audit_log_list',
        'doc': 'docs/CLIENT_DATA_PROTECTION.md#revealing-a-vault-credential',
        'tests': ['api.tests', 'vault.tests_release_652'],
    },
    {
        'key': 'theft_detection',
        'group': 'audit',
        'title': 'Read-only theft detection',
        'status': 'on_by_default',
        'protects': 'Customers from a technician account quietly reading in bulk.',
        'default': 'On, with built-in thresholds over 1-hour and 24-hour windows.',
        'prerequisites': 'Alert recipients.',
        'detail': 'Counts distinct tickets, customers and exports read, and diagnostic bytes, per identity, '
                  'across the web UI, REST API and mobile API. Alerts carry counts and identities only.',
        'link': 'tech_access:index',
        'doc': 'docs/TECHNICIAN_ACCESS.md#theft-detection',
        'tests': ['tech_access.tests'],
    },
]

GROUP_LABELS = dict(GROUPS)


def catalog():
    return [dict(f, status_label=STATUS_LABELS[f['status']], group_label=GROUP_LABELS[f['group']])
            for f in FEATURES]


def grouped(features=None):
    """[(group_label, [feature, ...]), ...] in GROUPS order, skipping empty groups."""
    features = catalog() if features is None else features
    out = []
    for key, label in GROUPS:
        items = [f for f in features if f['group'] == key]
        if items:
            out.append((label, items))
    return out


# ---- effective state at one customer (administrators' page) --------------
#
# Each function returns (state, text, env) where state is 'on', 'off',
# 'partial' or 'info', and env names the environment variables that fixed
# the value (the UI can't change those).

def _policy(*keys):
    from core import security_policy
    d = security_policy.describe()
    return [d[k] for k in keys], [d[k]['env'] for k in keys if d[k]['locked']]


def _two_factor(org):
    from django_otp.plugins.otp_totp.models import TOTPDevice
    (req,), env = _policy('require_2fa')
    members = _member_ids(org)
    with_device = set(TOTPDevice.objects.filter(user_id__in=members, confirmed=True)
                      .values_list('user_id', flat=True))
    text = (f"{'Required' if req['value'] else 'Optional'}; {len(with_device)} of {len(members)} "
            f"members here have an authenticator.")
    if env and not req['value']:
        # install.sh wrote REQUIRE_2FA=False into .env until v3.17.660,
        # which turns the requirement off and locks Settings → Security.
        text += (' Turned off by REQUIRE_2FA=False in the .env file (older installers wrote it): '
                 'remove that line to manage 2FA in Settings → Security, where it is required by default.')
    return ('on' if req['value'] and len(with_device) == len(members) else
            'partial' if req['value'] else 'off'), text, env


def _lockout(org):
    (n, mins), env = _policy('failed_login_attempts', 'lockout_duration_minutes')
    return 'on', f"{n['value']} attempts, {mins['value']} minutes.", env


def _password_policy(org):
    from django.contrib.auth.hashers import get_hasher
    (length, special), env = _policy('password_min_length', 'password_require_special')
    algo = get_hasher().algorithm
    text = (f"Minimum {length['value']} characters{', special character required' if special['value'] else ''}; "
            f"new hashes use {algo}.")
    return ('on' if algo == 'argon2' else 'partial'), text, env


def _sessions(org):
    (idle, maximum), env = _policy('session_idle_timeout_minutes', 'session_timeout_minutes')
    ttl = getattr(settings, 'MOBILE_TOKEN_TTL_DAYS', None)
    text = (f"Idle {idle['value']} min, maximum {maximum['value']} min. Mobile tokens: "
            f"{f'{ttl} days' if ttl else 'until revoked'}.")
    return ('on' if ttl else 'partial'), text, env + (['MOBILE_TOKEN_TTL_DAYS'] if ttl else [])


def _network_firewall(org):
    from core.models import FirewallSettings
    fw = FirewallSettings.get_settings()
    parts = [name for name, on in (('IP rules', fw.ip_firewall_enabled), ('country rules', fw.geoip_firewall_enabled))
             if on]
    return ('on', f"{' and '.join(parts).capitalize()} on (whole install).", []) if parts else \
        ('off', 'Off (whole install).', [])


def _csp(org):
    if settings.CSP_REPORT_ONLY:
        return 'partial', 'Report-only.', (['CSP_REPORT_ONLY'] if 'CSP_REPORT_ONLY' in _environ() else [])
    return 'on', 'Enforced.', ['CSP_REPORT_ONLY']


def _member_ids(org):
    from accounts.models import Membership
    return set(Membership.objects.filter(organization=org, is_active=True, user__is_active=True)
               .values_list('user_id', flat=True))


def _org_roles(org):
    from accounts.models import Membership
    from django.contrib.auth.models import User
    members = Membership.objects.filter(organization=org, is_active=True, user__is_active=True)
    staff = User.objects.filter(is_active=True, profile__user_type='staff').count()
    supers = User.objects.filter(is_active=True, is_superuser=True).count()
    return 'info', (f'{members.count()} active members here; {staff} MSP staff and {supers} superusers '
                    f'reach every customer.'), []


def _superuser_approval(org):
    from tech_access.services import eligible_admins, superuser_policy_on
    n = eligible_admins().count()
    if superuser_policy_on():
        return 'on', f'On for the whole install; {n} eligible administrators.', []
    return 'off', (f'Off. {n} eligible administrators' + ('' if n >= 2 else '; two are needed to turn it on')
                   + '.'), []


def _vault_title_scope(org):
    from django.contrib.auth.models import User
    from accounts.permission_utils import has_perm_for_org
    staff = [u for u in User.objects.filter(is_active=True, is_superuser=False, profile__user_type='staff')
             .select_related('profile__global_role_template')]
    can = sum(1 for u in staff if has_perm_for_org(u, org, 'vault_view'))
    return 'on', f'{can} of {len(staff)} MSP staff (not superusers) can see vault entries here.', []


def _offline_cache(org):
    from accounts.permission_utils import user_has_org_perm
    from django.contrib.auth.models import User
    from vault.access_rules import online_only_ids
    from vault.models import Password
    members = User.objects.filter(pk__in=_member_ids(org))
    can = sum(1 for u in members if user_has_org_perm(u, org, 'vault_extension_offline_cache'))
    entries = Password.objects.filter(organization=org, is_personal=False)
    restricted = len(online_only_ids(entries, None))
    text = f'{can} members here may sync an offline cache; {restricted} of {entries.count()} entries are online-only.'
    return ('on' if can else 'off'), text, []


def _customer_ticket_view(org):
    from psa.models import Ticket
    shared = Ticket.objects.filter(organization=org, client_can_view=True).count()
    return 'on', f'{shared} tickets here are shared with the customer.', []


def _per_route_authorization(org):
    from tech_access.models import AccessAssignment
    n = AccessAssignment.objects.live().filter(organization=org).count()
    return ('on' if n else 'off'), (f'{n} live assignments here.' if n else
                                    'No assignments here: no technician can use ticket AI or RMM tools.'), []


def _protected_changes(org):
    from tech_access.models import ProtectedChange
    pending = ProtectedChange.objects.filter(status='pending').count()
    return 'on', f'{pending} pending changes (whole install).', []


def _encryption_at_rest(org):
    if settings.APP_MASTER_KEY:
        return 'on', 'APP_MASTER_KEY is set.', ['APP_MASTER_KEY']
    return 'off', 'APP_MASTER_KEY is not set (development only).', []


def _reveal_permission(org):
    from accounts.permission_utils import user_has_org_perm
    from django.contrib.auth.models import User
    members = User.objects.filter(pk__in=_member_ids(org))
    can = sum(1 for u in members if user_has_org_perm(u, org, 'vault_view_password'))
    return 'on', f'{can} of {members.count()} members here may reveal (plus MSP staff whose role allows it).', []


def _reveal_approval(org):
    from vault.models import Password
    total = Password.objects.filter(organization=org).count()
    gated = Password.objects.filter(organization=org, requires_reveal_approval=True).count()
    return ('on' if gated else 'off'), f'{gated} of {total} credentials here need approval.', []


def _access_rules(org):
    from vault.models import VaultAccessRule
    n = VaultAccessRule.objects.filter(organization=org, is_active=True).count()
    return ('on' if n else 'off'), f'{n} active rules here.', []


def _breach_check(org):
    from core.models import ScheduledTask
    task = ScheduledTask.objects.filter(task_type='password_breach_scan').first()
    if task is None or not task.enabled:
        return 'partial', 'Checked on save; the daily scan is off.', []
    return 'on', 'Checked on save and daily.', []


def _vault_isolation(org):
    mode = getattr(settings, 'AI_GATEWAY_MODE', 'in_process')
    env = ['AI_GATEWAY_MODE'] if 'AI_GATEWAY_MODE' in _environ() else []
    if mode == 'worker':
        return 'on', 'Gateway worker mode.', env
    return 'off', 'In-process gateway: not isolated.', env


def _ai_opt_in(org):
    from core.models import SystemSetting
    from psa_ai.models import AIBusinessPolicy
    if not SystemSetting.get_settings().psa_ai_enabled:
        return 'off', 'AI is off for the whole install.', []
    policy = AIBusinessPolicy.objects.filter(organization=org).first()
    if policy is None or not (policy.analysis_enabled or policy.compare_enabled):
        return 'off', 'This customer has no AI analysis allowed.', []
    bits = ['analysis' if policy.analysis_enabled else '', 'comparison' if policy.compare_enabled else '',
            'on-premises only' if policy.local_only else '',
            "technicians' own keys" if policy.allow_technician_credentials else '',
            f'budget ${policy.daily_budget_cents / 100:.2f}/day']
    return 'on', 'Allowed here: ' + ', '.join(b for b in bits if b) + '.', []


def _always_on(org):
    return 'on', 'Always on.', []


def _audit_log(org):
    from datetime import timedelta
    from django.utils import timezone
    from audit.models import AuditLog
    n = AuditLog.objects.filter(organization=org, timestamp__gte=timezone.now() - timedelta(days=30)).count()
    return 'partial', f'{n} events here in the last 30 days. Superusers can delete entries.', []


def _reveal_audit(org):
    from datetime import timedelta
    from django.utils import timezone
    from audit.models import AuditLog
    n = AuditLog.objects.filter(organization=org, action='reveal',
                                timestamp__gte=timezone.now() - timedelta(days=30)).count()
    return 'on', f'{n} reveals here in the last 30 days.', []


def _theft_detection(org):
    from tech_access.models import DetectionSettings
    s = DetectionSettings.load()
    recipients = len([r for r in (s.recipients or '').splitlines() if r.strip()])
    if not s.enabled:
        return 'off', 'Switched off (whole install).', []
    return 'on', (f"On (whole install); {recipients} extra recipients; customer reports "
                  f"{'on' if s.notify_customers else 'off'}."), []


def _environ():
    import os
    return os.environ


EFFECTIVE = {
    'two_factor': _two_factor,
    'lockout': _lockout,
    'password_policy': _password_policy,
    'sessions': _sessions,
    'network_firewall': _network_firewall,
    'csp': _csp,
    'org_roles': _org_roles,
    'customer_ticket_view': _customer_ticket_view,
    'per_route_authorization': _per_route_authorization,
    'protected_changes': _protected_changes,
    'superuser_approval': _superuser_approval,
    'vault_title_scope': _vault_title_scope,
    'encryption_at_rest': _encryption_at_rest,
    'reveal_permission': _reveal_permission,
    'reveal_approval': _reveal_approval,
    'access_rules': _access_rules,
    'breach_check': _breach_check,
    'vault_isolation': _vault_isolation,
    'offline_cache': _offline_cache,
    'ai_opt_in': _ai_opt_in,
    'ai_evidence': _always_on,
    'no_endpoint_actions': _always_on,
    'audit_log': _audit_log,
    'reveal_audit': _reveal_audit,
    'theft_detection': _theft_detection,
}

STATE_LABELS = {'on': 'On', 'off': 'Off', 'partial': 'Partly', 'info': 'Info', 'unknown': 'Unknown'}


def effective_states(org):
    """The catalog with `effective` = {state, label, text, env} at `org`.

    A check that fails shows as Unknown with the error class, never as On."""
    out = []
    for f in catalog():
        try:
            state, text, env = EFFECTIVE[f['key']](org)
        except Exception as exc:  # one broken check must not hide the page
            state, text, env = 'unknown', f'Could not be read ({type(exc).__name__}).', []
        out.append(dict(f, effective={'state': state, 'label': STATE_LABELS[state], 'text': text, 'env': env}))
    return out
