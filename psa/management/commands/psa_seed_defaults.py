"""
Seed default PSA reference data: queues, statuses, priorities, ticket types,
plus service-catalog items.

Idempotent — safe to run repeatedly. Uses get_or_create so existing
operator-customised rows are preserved.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from psa.models import (
    Queue, ServiceCatalogItem, TicketPriority, TicketStatus, TicketType,
)


QUEUES = [
    'Helpdesk',
    'Escalations',
    'Projects',
    'Security',
    'Monitoring',
    'Procurement',
    'Client Success',
]

# (name, is_terminal, pauses_sla)
STATUSES = [
    ('New', False, False),
    ('Assigned', False, False),
    ('In Progress', False, False),
    ('Waiting on Client', False, True),
    ('Waiting on Vendor', False, True),
    ('Scheduled', False, False),
    ('Escalated', False, False),
    ('Resolved', True, False),
    ('Closed', True, False),
    ('Cancelled', True, False),
]

# (code, name, description, response_minutes, resolution_minutes)
# Defaults match the spec; admins can edit per-priority targets.
PRIORITIES = [
    ('P1', 'Critical', 'Production down or imminent business impact.', 15, 240),
    ('P2', 'High',     'Significant impact, workaround partially available.', 30, 480),
    ('P3', 'Normal',   'Single-user impact or routine issue.', 240, 4320),
    ('P4', 'Low',      'Minor issue, low impact.', 1440, 7200),
    ('P5', 'Informational', 'No service impact, informational only.', 2880, 14400),
]

TYPES = [
    'Incident',
    'Service Request',
    'Change Request',
    'Problem',
    'Project Task',
    'Security Event',
    'Monitoring Alert',
    'Onboarding',
    'Offboarding',
    'Procurement',
    'Documentation Request',
    'Access Request',
    'Vendor Escalation',
    'Calendar Dispatch',
]

# (slug, name, description) — explicit-slug ticket types. The Phase 6.1 'change'
# slug is the contract for the auto-spawning ChangeRequest signal.
EXPLICIT_SLUG_TYPES = [
    ('change', 'Change', 'Change request - requires CAB approval before implementing'),
]

# Catalog item schema:
# {
#   name, description, type, queue, priority, icon,
#   subject_tpl   — uses {{key}} placeholders
#   body_tpl      — uses {{key}} placeholders; rendered into the ticket body
#   fields        — list of {key, label, type, required, placeholder?, options?}
#                   types: text, email, date, number, textarea, select, checkbox
# }
CATALOG = [
    {
        'name': 'New User', 'description': 'Create accounts and access for a new employee.',
        'type': 'Onboarding', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-user-plus',
        'subject_tpl': 'New user setup — {{full_name}}',
        'body_tpl': 'Please create accounts for the new user.\n\n'
                    'Full name: {{full_name}}\nEmail: {{email}}\nManager: {{manager}}\n'
                    'Start date: {{start_date}}\nGroups / licenses: {{groups}}\n'
                    'Equipment needed: {{equipment}}',
        'fields': [
            {'key': 'full_name', 'label': 'Full name', 'type': 'text', 'required': True},
            {'key': 'email',     'label': 'Email',     'type': 'email', 'required': True},
            {'key': 'manager',   'label': 'Manager',   'type': 'text'},
            {'key': 'start_date','label': 'Start date','type': 'date', 'required': True},
            {'key': 'groups',    'label': 'Groups / licenses', 'type': 'textarea',
             'placeholder': 'e.g. Sales, Office E3, Salesforce'},
            {'key': 'equipment', 'label': 'Equipment needed', 'type': 'textarea',
             'placeholder': 'Laptop model, monitor count, headset, …'},
        ],
    },
    {
        'name': 'Terminate User', 'description': 'Disable / off-board a leaving employee.',
        'type': 'Offboarding', 'queue': 'Helpdesk', 'priority': 'P2', 'icon': 'fas fa-user-slash',
        'subject_tpl': 'User termination — {{full_name}}',
        'body_tpl': 'Please disable accounts and reclaim equipment.\n\n'
                    'Full name: {{full_name}}\nLast day: {{last_day}}\n'
                    'Reason: {{reason}}\nForward email to: {{forward_to}}\n'
                    'Reassign data to: {{reassign_to}}',
        'fields': [
            {'key': 'full_name',   'label': 'Full name',   'type': 'text', 'required': True},
            {'key': 'last_day',    'label': 'Last day',    'type': 'date', 'required': True},
            {'key': 'reason',      'label': 'Reason',      'type': 'select',
             'options': ['Resignation', 'Termination', 'Contract end', 'Other']},
            {'key': 'forward_to',  'label': 'Forward email to', 'type': 'email'},
            {'key': 'reassign_to', 'label': 'Reassign data to', 'type': 'text'},
        ],
    },
    {
        'name': 'Password Reset', 'description': 'Reset an existing user account password.',
        'type': 'Service Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-key',
        'subject_tpl': 'Password reset — {{username}}',
        'body_tpl': 'Account requiring reset: {{username}}\nUser identity verified by: {{verified_by}}',
        'fields': [
            {'key': 'username',    'label': 'Username / account', 'type': 'text', 'required': True},
            {'key': 'verified_by', 'label': 'Identity verified by', 'type': 'select',
             'options': ['Photo ID', 'Manager confirmation', 'Voice recognition', 'Knowledge questions']},
        ],
    },
    {
        'name': 'MFA Reset', 'description': 'Re-enroll multi-factor authentication for a user.',
        'type': 'Service Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-mobile-alt',
        'subject_tpl': 'MFA reset — {{username}}',
        'body_tpl': 'User: {{username}}\nIdentity verification method: {{verified_by}}',
        'fields': [
            {'key': 'username',    'label': 'Username', 'type': 'text', 'required': True},
            {'key': 'verified_by', 'label': 'Identity verified by', 'type': 'select',
             'options': ['Photo ID', 'Manager confirmation', 'Voice recognition', 'Knowledge questions']},
        ],
    },
    {
        'name': 'Software Install', 'description': 'Install or update software on a workstation/server.',
        'type': 'Change Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-download',
        'subject_tpl': 'Software install — {{software}} on {{asset}}',
        'body_tpl': 'User / asset: {{user}} / {{asset}}\nSoftware + version: {{software}} {{version}}\n'
                    'License source: {{license}}',
        'fields': [
            {'key': 'user',     'label': 'User',     'type': 'text'},
            {'key': 'asset',    'label': 'Asset / hostname', 'type': 'text', 'required': True},
            {'key': 'software', 'label': 'Software', 'type': 'text', 'required': True},
            {'key': 'version',  'label': 'Version',  'type': 'text'},
            {'key': 'license',  'label': 'License source', 'type': 'text',
             'placeholder': 'e.g. existing volume license, new purchase, vendor portal'},
        ],
    },
    {
        'name': 'New Computer', 'description': 'Provision and ship a new workstation.',
        'type': 'Procurement', 'queue': 'Procurement', 'priority': 'P3', 'icon': 'fas fa-laptop',
        'subject_tpl': 'New computer for {{user}}',
        'body_tpl': 'User: {{user}}\nRole / requirements: {{role}}\nDelivery address: {{address}}\n'
                    'Apps to pre-install: {{apps}}',
        'fields': [
            {'key': 'user',    'label': 'User',    'type': 'text', 'required': True},
            {'key': 'role',    'label': 'Role / requirements', 'type': 'textarea'},
            {'key': 'address', 'label': 'Delivery address', 'type': 'textarea', 'required': True},
            {'key': 'apps',    'label': 'Apps to pre-install', 'type': 'textarea'},
        ],
    },
    {
        'name': 'Printer Issue', 'description': 'Diagnose and resolve printer / MFP problem.',
        'type': 'Incident', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-print',
        'subject_tpl': 'Printer issue — {{printer}}',
        'body_tpl': 'Printer model + location: {{printer}}\nError message: {{error}}\n'
                    'When did it start: {{started}}',
        'fields': [
            {'key': 'printer', 'label': 'Printer model + location', 'type': 'text', 'required': True},
            {'key': 'error',   'label': 'Error message', 'type': 'textarea'},
            {'key': 'started', 'label': 'When did it start', 'type': 'text',
             'placeholder': 'date/time or "after X update"'},
        ],
    },
    {
        'name': 'VPN Access', 'description': 'Grant or troubleshoot VPN.',
        'type': 'Access Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-shield-alt',
        'subject_tpl': 'VPN access — {{user}}',
        'body_tpl': 'User: {{user}}\nDevice: {{device}}\nIssue / request: {{issue}}',
        'fields': [
            {'key': 'user',   'label': 'User',   'type': 'text', 'required': True},
            {'key': 'device', 'label': 'Device', 'type': 'text'},
            {'key': 'issue',  'label': 'Issue / request', 'type': 'textarea', 'required': True},
        ],
    },
    {
        'name': 'Firewall Change', 'description': 'Change a firewall rule.',
        'type': 'Change Request', 'queue': 'Security', 'priority': 'P2', 'icon': 'fas fa-fire',
        'subject_tpl': 'Firewall change — {{source}} → {{destination}}',
        'body_tpl': 'Source: {{source}}\nDestination: {{destination}}\nPort / protocol: {{port}}\n'
                    'Direction: {{direction}}\nReason: {{reason}}\nApproved by: {{approved_by}}',
        'fields': [
            {'key': 'source',      'label': 'Source',      'type': 'text', 'required': True},
            {'key': 'destination', 'label': 'Destination', 'type': 'text', 'required': True},
            {'key': 'port',        'label': 'Port / protocol', 'type': 'text', 'required': True},
            {'key': 'direction',   'label': 'Direction',   'type': 'select',
             'options': ['Inbound', 'Outbound', 'Both'], 'required': True},
            {'key': 'reason',      'label': 'Reason',      'type': 'textarea', 'required': True},
            {'key': 'approved_by', 'label': 'Approved by', 'type': 'text', 'required': True},
        ],
    },
    {
        'name': 'DNS Change', 'description': 'Add / edit / remove a DNS record.',
        'type': 'Change Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-globe',
        'subject_tpl': 'DNS change — {{record_type}} {{record_name}}',
        'body_tpl': 'Domain: {{domain}}\nRecord type / name / value: {{record_type}} / {{record_name}} / {{record_value}}\n'
                    'TTL: {{ttl}}\nReason: {{reason}}',
        'fields': [
            {'key': 'domain',       'label': 'Domain',     'type': 'text', 'required': True},
            {'key': 'record_type',  'label': 'Record type','type': 'select',
             'options': ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'SRV', 'NS', 'CAA', 'PTR'], 'required': True},
            {'key': 'record_name',  'label': 'Record name','type': 'text', 'required': True},
            {'key': 'record_value', 'label': 'Record value','type': 'text', 'required': True},
            {'key': 'ttl',          'label': 'TTL (seconds)', 'type': 'number', 'placeholder': '3600'},
            {'key': 'reason',       'label': 'Reason',     'type': 'textarea'},
        ],
    },
    {
        'name': 'Shared Mailbox', 'description': 'Create or modify a shared mailbox.',
        'type': 'Service Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-envelope',
        'subject_tpl': 'Shared mailbox — {{mailbox}}',
        'body_tpl': 'Mailbox name + alias: {{mailbox}}\nMembers: {{members}}\n'
                    'Delegates: {{delegates}}\nRetention: {{retention}}',
        'fields': [
            {'key': 'mailbox',   'label': 'Mailbox name + alias', 'type': 'text', 'required': True},
            {'key': 'members',   'label': 'Members',   'type': 'textarea'},
            {'key': 'delegates', 'label': 'Delegates', 'type': 'textarea'},
            {'key': 'retention', 'label': 'Retention', 'type': 'text',
             'placeholder': 'e.g. 7 years, default policy'},
        ],
    },
    {
        'name': 'Backup Restore', 'description': 'Restore data from backup.',
        'type': 'Service Request', 'queue': 'Helpdesk', 'priority': 'P2', 'icon': 'fas fa-database',
        'subject_tpl': 'Backup restore — {{what}}',
        'body_tpl': 'What to restore: {{what}}\nFrom when: {{when}}\nDestination: {{destination}}\n'
                    'User requesting: {{requester}}',
        'fields': [
            {'key': 'what',        'label': 'What to restore', 'type': 'textarea', 'required': True},
            {'key': 'when',        'label': 'From when',       'type': 'date', 'required': True},
            {'key': 'destination', 'label': 'Destination',     'type': 'text', 'required': True},
            {'key': 'requester',   'label': 'User requesting', 'type': 'text'},
        ],
    },
    {
        'name': 'SSL Renewal', 'description': 'Renew an SSL/TLS certificate.',
        'type': 'Change Request', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-lock',
        'subject_tpl': 'SSL renewal — {{hostname}}',
        'body_tpl': 'Hostname / cert subject: {{hostname}}\nExpiry: {{expiry}}\nProvider: {{provider}}',
        'fields': [
            {'key': 'hostname', 'label': 'Hostname / cert subject', 'type': 'text', 'required': True},
            {'key': 'expiry',   'label': 'Expiry date',  'type': 'date'},
            {'key': 'provider', 'label': 'Provider / CA','type': 'text'},
        ],
    },
    {
        'name': 'Vendor Access', 'description': 'Grant short-term access to a third-party vendor.',
        'type': 'Access Request', 'queue': 'Security', 'priority': 'P2', 'icon': 'fas fa-handshake',
        'subject_tpl': 'Vendor access — {{vendor}}',
        'body_tpl': 'Vendor: {{vendor}}\nAccess level: {{access_level}}\nDuration: {{duration}}\n'
                    'Reason: {{reason}}\nApproved by: {{approved_by}}',
        'fields': [
            {'key': 'vendor',       'label': 'Vendor',       'type': 'text', 'required': True},
            {'key': 'access_level', 'label': 'Access level', 'type': 'text', 'required': True},
            {'key': 'duration',     'label': 'Duration',     'type': 'text', 'required': True,
             'placeholder': 'e.g. 1 day, until 2026-05-30'},
            {'key': 'reason',       'label': 'Reason',       'type': 'textarea', 'required': True},
            {'key': 'approved_by',  'label': 'Approved by',  'type': 'text', 'required': True},
        ],
    },
    {
        'name': 'Security Incident', 'description': 'Suspected breach / phishing / malware.',
        'type': 'Security Event', 'queue': 'Security', 'priority': 'P1', 'icon': 'fas fa-bug',
        'subject_tpl': 'Security incident — {{summary}}',
        'body_tpl': 'What was observed: {{observation}}\nAffected user / asset: {{affected}}\n'
                    'When: {{when}}\nActions taken so far: {{actions}}',
        'fields': [
            {'key': 'summary',     'label': 'One-line summary', 'type': 'text', 'required': True},
            {'key': 'observation', 'label': 'What was observed', 'type': 'textarea', 'required': True},
            {'key': 'affected',    'label': 'Affected user / asset', 'type': 'text'},
            {'key': 'when',        'label': 'When',        'type': 'text',
             'placeholder': 'e.g. 2026-04-28 09:14 UTC, "this morning"'},
            {'key': 'actions',     'label': 'Actions taken so far', 'type': 'textarea'},
        ],
    },
    {
        'name': 'Schedule Onsite Visit', 'description': 'Dispatch a technician to a client site.',
        'type': 'Calendar Dispatch', 'queue': 'Helpdesk', 'priority': 'P3', 'icon': 'fas fa-truck',
        'subject_tpl': 'Onsite visit — {{site}} on {{when}}',
        'body_tpl': 'Site address: {{site}}\nDate / time: {{when}}\nTech needed: {{tech}}\n'
                    'Work to perform: {{work}}',
        'fields': [
            {'key': 'site', 'label': 'Site address', 'type': 'textarea', 'required': True},
            {'key': 'when', 'label': 'Date / time',  'type': 'text', 'required': True,
             'placeholder': 'YYYY-MM-DD HH:MM'},
            {'key': 'tech', 'label': 'Tech needed (skills/named)', 'type': 'text'},
            {'key': 'work', 'label': 'Work to perform', 'type': 'textarea', 'required': True},
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed default PSA queues, statuses, priorities, and ticket types'

    def handle(self, *args, **opts):
        created_total = 0
        existing_total = 0

        # Queues
        for i, name in enumerate(QUEUES):
            _, created = Queue.objects.get_or_create(
                name=name,
                defaults={'slug': slugify(name), 'sort_order': i, 'is_active': True},
            )
            created_total += 1 if created else 0
            existing_total += 0 if created else 1

        # Statuses
        for i, (name, is_terminal, pauses_sla) in enumerate(STATUSES):
            _, created = TicketStatus.objects.get_or_create(
                name=name,
                defaults={
                    'slug': slugify(name),
                    'is_terminal': is_terminal,
                    'pauses_sla': pauses_sla,
                    'sort_order': i,
                },
            )
            created_total += 1 if created else 0
            existing_total += 0 if created else 1

        # Priorities
        for i, (code, name, desc, resp, res) in enumerate(PRIORITIES):
            _, created = TicketPriority.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'description': desc,
                    'response_target_minutes': resp,
                    'resolution_target_minutes': res,
                    'sort_order': i,
                },
            )
            created_total += 1 if created else 0
            existing_total += 0 if created else 1

        # Ticket types
        for i, name in enumerate(TYPES):
            _, created = TicketType.objects.get_or_create(
                name=name,
                defaults={'slug': slugify(name), 'sort_order': i, 'is_active': True},
            )
            created_total += 1 if created else 0
            existing_total += 0 if created else 1

        # Explicit-slug ticket types (Phase 6.1: 'change' for ChangeRequest)
        for i, (slug, name, desc) in enumerate(EXPLICIT_SLUG_TYPES):
            _, created = TicketType.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': desc,
                    'sort_order': len(TYPES) + i,
                    'is_active': True,
                },
            )
            created_total += 1 if created else 0
            existing_total += 0 if created else 1

        # Service catalog — structured fields + body/subject templates
        for i, item in enumerate(CATALOG):
            existing = ServiceCatalogItem.objects.filter(name=item['name'], organization__isnull=True).first()
            if existing:
                # Always refresh fields_json + templates so re-running the seed
                # picks up schema changes. Operator-customised name / icon /
                # queue / priority / type are preserved if already non-default.
                existing.description = existing.description or item['description']
                existing.default_subject = item['subject_tpl']
                existing.default_body = item['body_tpl']
                existing.fields_json = item['fields']
                if not existing.icon:
                    existing.icon = item['icon']
                if existing.default_type_id is None:
                    existing.default_type = TicketType.objects.filter(name=item['type']).first()
                if existing.default_queue_id is None:
                    existing.default_queue = Queue.objects.filter(name=item['queue']).first()
                if existing.default_priority_id is None:
                    existing.default_priority = TicketPriority.objects.filter(code=item['priority']).first()
                existing.save()
                existing_total += 1
                continue
            ServiceCatalogItem.objects.create(
                name=item['name'], slug=slugify(item['name']),
                description=item['description'],
                default_subject=item['subject_tpl'],
                default_body=item['body_tpl'],
                default_type=TicketType.objects.filter(name=item['type']).first(),
                default_queue=Queue.objects.filter(name=item['queue']).first(),
                default_priority=TicketPriority.objects.filter(code=item['priority']).first(),
                icon=item['icon'],
                fields_json=item['fields'],
                sort_order=i,
                is_active=True,
            )
            created_total += 1

        self.stdout.write(self.style.SUCCESS(
            f'PSA seed complete — {created_total} created, {existing_total} already existed.'
        ))
