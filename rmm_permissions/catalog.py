"""
RMM actions, what each role tier holds, and how each maps to Rem0te.

An action key names one thing a person may do with an RMM: read a device,
run an approved diagnostic, deploy patches, configure an integration...
Every RMM code path asks `rmm_permissions.can()` / `rmm_action()` with one
of these keys. Unknown keys are refused.

Scopes:
  device    work on a customer's devices or alerts. Needs an MSP
            technician scoped to that customer (a live technician-access
            assignment there) for any tier or override grant.
  platform  administration (integrations, policy, security, audit). A
            Platform Administrator tier holds these everywhere.

Tier entries: state ALLOWED or REQUEST (the paired RMM grants the session
itself), or GRANTABLE (the tier doesn't hold it; an approved allow override
for this customer can). `approval` is the second-person approval level the
action then needs; `workstation_only` limits it to standard workstations.

Rem0te mapping (REM0TE): the ticket-rmm-v1 delegation scope ClientSt0r uses
for the action, '' for actions Rem0te serves without a delegation (synced
devices, inbound alerts), or None: Rem0te's contract has no route for it,
so on a Rem0te-managed device the answer is no. Scopes are Rem0te's own
(integrations.rem0te.protocol.SCOPES); none is invented here. Rem0te then
makes its own decision and its refusal always wins (`record_remote_refusal`).
"""
from __future__ import annotations

from collections import namedtuple

ALLOWED, REQUEST, GRANTABLE = 'allowed', 'request', 'grantable'

# Approval levels, weakest first.
PEER, L3, PLATFORM_ADMIN = 'peer', 'l3', 'platform_admin'
APPROVAL_LEVELS = (PEER, L3, PLATFORM_ADMIN)
APPROVAL_RANK = {None: 0, '': 0, PEER: 1, L3: 2, PLATFORM_ADMIN: 3}
APPROVAL_LABELS = {
    PEER: 'another technician who may do this here',
    L3: 'an L3 technician at this customer',
    PLATFORM_ADMIN: 'a Platform Administrator',
}

TIER_RANK = {'': 0, 'l1': 1, 'l2': 2, 'l3': 3}
TIER_LABELS = {'l1': 'RMM L1', 'l2': 'RMM L2', 'l3': 'RMM L3', 'platform_admin': 'Platform Administrator'}

Action = namedtuple('Action', 'label group scope tech_capability default_approval description')

ACTIONS = {
    # --- read ---------------------------------------------------------------
    'device.view': Action('View permitted devices', 'Devices', 'device', None, None,
                          "See this customer's RMM devices and their status."),
    'alert.view': Action('View alerts', 'Devices', 'device', None, None,
                         "See this customer's RMM alerts."),
    'diagnostics.view': Action('View approved diagnostics', 'Diagnostics', 'device', None, None,
                               'See the approved diagnostics for a device and their results.'),
    # --- requests -------------------------------------------------------------
    'remote.request_support': Action('Request remote support', 'Remote access', 'device', 'remote_view', None,
                                     'Ask the paired RMM for an attended, view-only session.'),
    'remediation.request_low': Action('Submit a remediation request', 'Remediation', 'device',
                                      'fix_request_low', None,
                                      'Propose a low-risk catalog fix; the paired RMM approves and runs it.'),
    # --- L2 -------------------------------------------------------------------
    'rmm.handoff': Action('Private RMM handoff', 'Devices', 'device', 'rmm_handoff', None,
                          'Send a verified, private handoff of a ticket to its RMM.'),
    'diagnostics.run': Action('Run approved diagnostics', 'Diagnostics', 'device', 'diagnostics_readonly', None,
                              'Bounded, read-only checks the paired RMM lists for the device.'),
    'workflow.run_approved': Action('Run approved workflows', 'Automation', 'device', None, None,
                                    'Run a workflow from the approved list against a device.'),
    'remote.request_control': Action('Request interactive control', 'Remote access', 'device', 'remote_control',
                                     None, 'Time-limited control, granted by the paired RMM per session.'),
    'script.run_scoped': Action('Run a scoped script', 'Automation', 'device', None, L3,
                                'Run one script from the approved, parameter-bound list. Never free-form.'),
    'patch.deploy': Action('Deploy patches', 'Patching', 'device', None, L3,
                           'Deploy approved updates to a device. High impact: second-person approval.'),
    # --- L3 -------------------------------------------------------------------
    'diagnostics.run_advanced': Action('Advanced diagnostics', 'Diagnostics', 'device', 'diagnostics_advanced',
                                       None, 'Wider read-only diagnostics, including servers.'),
    'remediation.request_high': Action('Request higher-risk remediation', 'Remediation', 'device',
                                       'fix_request_high', None,
                                       'Propose higher-risk catalog work; the paired RMM approves and runs it.'),
    'remediation.refer': Action("Refer another technician's fix", 'Remediation', 'device', 'fix_refer', None,
                                "Send another technician's proposed fix for independent approval."),
    'remote.request_elevation': Action('Request elevation', 'Remote access', 'device', 'elevation', None,
                                       'Time-limited elevated rights, granted by the paired RMM per session.'),
    'device.administer': Action('Administer a device', 'Devices', 'device', None, PEER,
                                'Change device settings, agents, maintenance mode. High impact.'),
    'automation.deploy': Action('Deploy automation', 'Automation', 'device', None, PEER,
                                'Create or deploy policies and automation to devices. High impact.'),
    'credential.reveal': Action('Reveal a device credential', 'Credentials', 'device', None, None,
                                'Needs the vault reveal permission at this customer; no RMM tier grants it.'),
    # --- platform ---------------------------------------------------------------
    'integration.configure': Action('Configure RMM integrations', 'Administration', 'platform', None, None,
                                    'Pairings, keys, mappings and provider settings.'),
    'policy.manage': Action('Manage RMM policy and roles', 'Administration', 'platform', None, None,
                            'RMM overrides, approvals policy and role tiers.'),
    'security.settings': Action('Security settings', 'Administration', 'platform', None, None,
                                'Security limits and settings for RMM work.'),
    'audit.review': Action('Review the audit log', 'Administration', 'platform', None, None,
                           'Read RMM permission decisions and their audit trail.'),
}

# Never available. Nothing — tier, override, superuser — switches these on.
LOCKED = {
    'shell.unrestricted': 'Unrestricted shell or free-form scripts are never available from ClientSt0r.',
    'tenant.all_access': 'No role grants device access at every customer; access is per customer.',
    'approval.self': 'Nobody approves their own request.',
    'endpoint.approve': 'Only the paired RMM approves endpoint work, on its own approval page.',
}

HIGH_IMPACT = {k for k, a in ACTIONS.items() if a.default_approval}
STANDARD_WORKSTATION_TYPES = {'workstation', 'laptop', 'desktop', 'thin_client'}


def _e(state=ALLOWED, approval=None, workstation_only=False):
    return {'state': state, 'approval': approval, 'workstation_only': workstation_only}


L1_MATRIX = {
    'device.view': _e(), 'alert.view': _e(), 'diagnostics.view': _e(),
    'remote.request_support': _e(REQUEST), 'remediation.request_low': _e(),
}
L2_MATRIX = dict(
    L1_MATRIX,
    **{'rmm.handoff': _e(), 'diagnostics.run': _e(workstation_only=True), 'workflow.run_approved': _e(),
       'remote.request_control': _e(REQUEST), 'script.run_scoped': _e(GRANTABLE, L3),
       'patch.deploy': _e(ALLOWED, L3, workstation_only=True)})
L3_MATRIX = dict(
    L2_MATRIX,
    **{'diagnostics.run': _e(), 'diagnostics.run_advanced': _e(), 'remediation.request_high': _e(),
       'remediation.refer': _e(), 'remote.request_elevation': _e(REQUEST),
       'script.run_scoped': _e(ALLOWED, PEER), 'patch.deploy': _e(ALLOWED, PEER),
       'device.administer': _e(ALLOWED, PEER), 'automation.deploy': _e(ALLOWED, PEER)})
PLATFORM_MATRIX = {k: _e() for k in ('integration.configure', 'policy.manage', 'security.settings', 'audit.review')}

MATRIX = {'l1': L1_MATRIX, 'l2': L2_MATRIX, 'l3': L3_MATRIX, 'platform_admin': PLATFORM_MATRIX}

# ticket-rmm-v1 delegation scope per action (see module docstring).
REM0TE = {
    'device.view': '',
    'alert.view': '',
    'remediation.request_low': 'actions:propose',
    'remediation.request_high': 'actions:propose',
    'remediation.refer': 'actions:propose',
}


def rem0te_scope(action):
    """'' / a scope string / None (no Rem0te route)."""
    if ACTIONS.get(action) and ACTIONS[action].scope == 'platform':
        return ''
    return REM0TE.get(action)


def entry(tier, action):
    return MATRIX.get(tier or '', {}).get(action)


def stronger(a, b):
    """The stricter of two approval levels."""
    return a if APPROVAL_RANK.get(a, 0) >= APPROVAL_RANK.get(b, 0) else b
