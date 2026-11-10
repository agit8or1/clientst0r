"""
What a technician can be allowed to do with ticket AI and RMM tools.

Three kinds of entries:

  OPTIONAL   a preset sets it to one of
               off       — not available
               allowed   — available inside the assignment's scope
               request   — the technician may ask for time-limited access;
                           the grant itself comes from elsewhere (the paired RMM for
                           endpoint access), never from ClientSt0r alone
  LOCKED     a mandatory safeguard. Shown as Locked; no preset, assignment
             or administrator can switch it on.
  (Unavailable is computed, not stored: an optional capability whose
   integration can't support it — see `unavailable_reason`.)

Ordinary manual ticket work (viewing, replying, internal notes, escalation)
keeps its existing permissions and is not governed here. Customer portal
users are outside technician access entirely.
"""
from __future__ import annotations

OFF, ALLOWED, REQUEST = 'off', 'allowed', 'request'
STATES = (OFF, ALLOWED, REQUEST)
STATE_LABELS = {OFF: 'Off', ALLOWED: 'Allowed in scope', REQUEST: 'Request time-limited access'}

# key → (label, group, description, states a preset may choose)
OPTIONAL = {
    'ai_analyze': ('Analyze ticket (one model)', 'Ticket AI',
                   'Single-model analysis of a ticket, staff-only result.', (OFF, ALLOWED)),
    'ai_draft': ('AI reply drafts', 'Ticket AI',
                 'Editable draft replies placed in the composer. Sending stays a separate step.', (OFF, ALLOWED)),
    'ai_send': ('Send reviewed AI replies', 'Ticket AI',
                'Send a reply that started as an AI draft, through the normal Send button.', (OFF, ALLOWED)),
    'ai_compare': ('Compare models', 'Ticket AI',
                   'Run the same analysis on several models; shows recipients and cost first.', (OFF, ALLOWED)),
    'ai_apply_change': ('Apply AI-suggested ticket changes', 'Ticket AI',
                        'Status, priority, assignment, KB links and workflows proposed by AI.', (OFF, ALLOWED)),
    'review_others': ("Work on other technicians' tickets", 'Scope',
                      'Without this, ticket AI and RMM tools work only on tickets assigned to you.', (OFF, ALLOWED)),
    'rmm_handoff': ('Private RMM handoff', 'RMM',
                    'Send a verified, private handoff of the ticket to the RMM that manages its device.', (OFF, ALLOWED)),
    'diagnostics_readonly': ('Read-only diagnostics (standard workstations)', 'RMM',
                             'Bounded, read-only checks on a ticket\'s workstation through the paired RMM.',
                             (OFF, ALLOWED)),
    'diagnostics_advanced': ('Advanced scoped diagnostics', 'RMM',
                             'Wider read-only diagnostics, including servers, through the paired RMM.', (OFF, ALLOWED)),
    'remote_view': ('Attended view-only session', 'Remote access',
                    'Ask the paired RMM for an attended, view-only session.', (OFF, REQUEST)),
    'remote_control': ('Interactive control', 'Remote access',
                       'Time-limited control, granted by the paired RMM per session.', (OFF, REQUEST)),
    'elevation': ('Elevation', 'Remote access',
                  'Time-limited elevated rights, granted by the paired RMM per session.', (OFF, REQUEST)),
    'fix_request_low': ('Request a low-risk catalog fix', 'Fixes',
                        'Propose a low-risk catalog fix; the paired RMM approves and runs it.', (OFF, ALLOWED)),
    'fix_request_high': ('Request higher-risk catalog work', 'Fixes',
                         'Propose higher-risk catalog work; the paired RMM approves and runs it.', (OFF, ALLOWED)),
    'fix_refer': ('Refer a fix for independent approval', 'Fixes',
                  "Send another technician's proposed fix to the paired RMM's approval page.", (OFF, ALLOWED)),
    'export': ('Export ticket data', 'Data',
               'Download or export ticket data for a customer.', (OFF, ALLOWED)),
    'unattended_access': ('Unattended access', 'Remote access',
                          'Connect with nobody at the device.', (OFF, REQUEST)),
    'clipboard': ('Clipboard sharing', 'Remote access', 'Clipboard sync in a remote session.', (OFF, REQUEST)),
    'file_transfer': ('File transfer', 'Remote access', 'Move files in a remote session.', (OFF, REQUEST)),
}

# Mandatory safeguards. Always enforced; shown as Locked.
LOCKED = {
    'fix_approval': ('Approve an endpoint fix',
                     'Only the paired RMM approves endpoint work, on its own approval page. ClientSt0r never approves.'),
    'endpoint_commands': ('Run commands on a device from ClientSt0r',
                          'ClientSt0r sends no endpoint commands. Device work is requested from the paired RMM.'),
    'vault_to_ai': ('Vault data in AI evidence',
                    'Vault entries, keys and backup credentials are never part of analysis evidence.'),
    'cross_customer': ('Cross-customer access from one assignment',
                       'Every assignment covers one customer. Nothing carries over to another.'),
    'bulk_export': ('Bulk export across customers', 'Not available through technician presets.'),
    'security_admin': ('Security administration',
                       'Changing technician access needs a security administrator, not a preset.'),
    'auto_publish': ('Publishing without Send',
                     'No AI draft, model vote, callback or remote action can send a customer reply or close a ticket.'),
}

ALL_KEYS = tuple(OPTIONAL) + tuple(LOCKED)

# Capabilities that act on a device and therefore need the paired RMM's live
# authorization on top of the preset.
NEEDS_LIVE_REMOTE = {'remote_view', 'remote_control', 'elevation', 'unattended_access',
                     'clipboard', 'file_transfer', 'diagnostics_readonly', 'diagnostics_advanced',
                     'fix_request_low', 'fix_request_high', 'fix_refer'}

# What a paired RMM must advertise (ticket-rmm-v1 capabilities document)
# before each RMM / Remote access / Fixes capability stops being Unavailable.
# Fix capabilities all ride on signed_actions: ClientSt0r only refers a fix,
# the RMM approves and runs it.
INTEGRATION_REQUIRES = {
    'rmm_handoff': 'rmm_handoff',
    'diagnostics_readonly': 'diagnostics_readonly',
    'diagnostics_advanced': 'diagnostics_advanced',
    'remote_view': 'remote_view',
    'remote_control': 'remote_control',
    'elevation': 'elevation',
    'unattended_access': 'unattended_access',
    'clipboard': 'clipboard',
    'file_transfer': 'file_transfer',
    'fix_request_low': 'signed_actions',
    'fix_request_high': 'signed_actions',
    'fix_refer': 'signed_actions',
}

# Ticket-scoped capabilities: on someone else's ticket they also need review_others.
TICKET_SCOPED = {'ai_analyze', 'ai_draft', 'ai_send', 'ai_compare', 'ai_apply_change', 'rmm_handoff',
                 'diagnostics_readonly', 'diagnostics_advanced', 'remote_view', 'remote_control',
                 'elevation', 'fix_request_low', 'fix_request_high'}

# Device classes read-only diagnostics may touch without diagnostics_advanced.
STANDARD_WORKSTATION_TYPES = {'workstation', 'laptop', 'desktop', 'thin_client'}


def _preset(**on):
    caps = {k: OFF for k in OPTIONAL}
    caps.update(on)
    return caps


L1 = _preset(ai_analyze=ALLOWED, ai_draft=ALLOWED)
L2 = _preset(ai_analyze=ALLOWED, ai_draft=ALLOWED, ai_send=ALLOWED, ai_compare=ALLOWED,
             ai_apply_change=ALLOWED, rmm_handoff=ALLOWED, diagnostics_readonly=ALLOWED,
             remote_view=REQUEST, remote_control=REQUEST, fix_request_low=ALLOWED)
L3 = dict(L2, diagnostics_advanced=ALLOWED, fix_request_high=ALLOWED, elevation=REQUEST,
          review_others=ALLOWED, fix_refer=ALLOWED)

BUILTIN_PRESETS = [
    ('l1', 'L1 — Help Desk', 1,
     'Assigned tickets: single-model analysis and editable drafts. AI-assisted Send, comparison, RMM, '
     'diagnostics, remote access, exports and fixes are off.', L1),
    ('l2', 'L2 — Technician', 2,
     'L1 plus reviewed AI replies, model comparison, private RMM handoffs and read-only diagnostics on '
     'assigned standard workstations. May request view-only access or a low-risk catalog fix; '
     'control needs a time-limited grant from rem0te.', L2),
    ('l3', 'L3 — Senior Technician', 3,
     "L2 plus advanced scoped diagnostics, higher-risk catalog requests, time-limited control or "
     "elevation requests, and other technicians' tickets. May refer a fix to rem0te for independent "
     'approval. Grants no endpoint approval, security administration, vault access, bulk export or '
     'cross-customer access.', L3),
]

RANK = {OFF: 0, REQUEST: 1, ALLOWED: 2}


def widens(before: dict, after: dict) -> list:
    """Capabilities `after` grants more of than `before`."""
    return [k for k in OPTIONAL if RANK[after.get(k, OFF)] > RANK[before.get(k, OFF)]]


def clean_capabilities(raw: dict) -> dict:
    """A capability map limited to known keys and each key's allowed states."""
    out = {}
    for key, (_label, _group, _desc, states) in OPTIONAL.items():
        value = (raw or {}).get(key, OFF)
        out[key] = value if value in states else OFF
    return out
