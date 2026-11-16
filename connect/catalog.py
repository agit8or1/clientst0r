"""What Clientst0r offers over Agit8or Connect, and which apps it knows.

`available=False` scopes are advertised so a peer can plan against them, but
granting them is refused until the feature ships (PROTOCOL.md §7.4).
"""
from agit8or_connect.scopes import ADMIN, HIGH_RISK, READ, WRITE, Catalog, Scope

APP_TYPE = 'clientst0r'

CATALOG = Catalog([
    Scope('connection:read', 'See this connection: its permissions, customers and health', READ),
    Scope('customers:read', 'Read the names of the customers granted to the connection', READ),
    Scope('events:publish', 'Send events (alerts, status changes) about granted customers', WRITE,
          events=('connect.test', 'alert.raised', 'alert.updated', 'alert.resolved')),
    Scope('assets:read', 'Read assets and devices of granted customers (planned)', READ, available=False),
    Scope('tickets:read', 'Read tickets of granted customers (planned)', READ, available=False),
    Scope('tickets:write', 'Create tickets and add notes for granted customers (planned)', WRITE, available=False),
    Scope('ticket_analysis:submit', 'Transitional ticket-rmm-v1 profile: submit ticket analysis (planned)', WRITE,
          available=False),
    Scope('remote_actions:execute', 'Ask Clientst0r to run a remote action; every action needs its own approval '
                                    '(planned)', HIGH_RISK, available=False),
    Scope('connection:admin', 'Change this connection\'s settings from the other application (planned)', ADMIN,
          available=False),
])

# Event types we accept when the sender holds events:publish.
INBOUND_EVENT_TYPES = ('connect.test', 'alert.raised', 'alert.updated', 'alert.resolved')
OUTBOUND_EVENT_TYPES = ('connect.test', 'connect.connection.revoked')

TENANT_MODEL = {
    'name': 'organization',
    'description': 'One Clientst0r installation serves one MSP. A tenant is one of that MSP\'s customer '
                   'organizations; ids look like "org-<number>". Only customers an administrator granted to the '
                   'connection are ever reachable.',
}

# Application catalog in the wizard. Honest about status.
APPLICATIONS = [
    {'type': 'rem0te', 'name': 'Rem0te', 'icon': 'fa-desktop',
     'description': 'Remote support and RMM: devices, alerts and remote sessions for your customers.',
     'status': 'available', 'note': 'Needs a Rem0te release with Agit8or Connect support (not yet released). '
                                    'The existing Rem0te ticket integration keeps working meanwhile.'},
    {'type': 'office-unbound', 'name': 'Office Unbound', 'icon': 'fa-file-word', 'status': 'planned',
     'description': 'Document editing and collaboration.'},
    {'type': 'exploithound', 'name': 'ExploitHound', 'icon': 'fa-bug', 'status': 'planned',
     'description': 'Vulnerability discovery and exposure tracking.'},
    {'type': 'mailthreatzero', 'name': 'MailThreatZero', 'icon': 'fa-envelope-open-text', 'status': 'planned',
     'description': 'E-mail threat protection.'},
    {'type': 'roots-hq', 'name': 'Roots-HQ', 'icon': 'fa-sitemap', 'status': 'planned',
     'description': 'Business operations hub.'},
    {'type': 'm0nitor', 'name': 'm0nitor', 'icon': 'fa-heart-pulse', 'status': 'planned',
     'description': 'Uptime and service monitoring.'},
    {'type': 'myappdone', 'name': 'MyAppDone', 'icon': 'fa-list-check', 'status': 'planned',
     'description': 'Project and task delivery.'},
    {'type': 'other', 'name': 'Another Agit8or Connect application', 'icon': 'fa-plug', 'status': 'available',
     'description': 'Any application that implements agit8or-connect/1 (enter its address).'},
]
APPLICATIONS_BY_TYPE = {a['type']: a for a in APPLICATIONS}


def tenant_id(org) -> str:
    return f'org-{getattr(org, "pk", org)}'
