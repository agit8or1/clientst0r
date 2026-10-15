"""
Seed sample guided service requests for the customer portal.

    python manage.py psa_seed_portal_requests            # create missing items
    python manage.py psa_seed_portal_requests --update   # also refresh existing ones
    python manage.py psa_seed_portal_requests --hidden   # create them but keep them out of the portal

Not run automatically. Items are matched by slug; existing items are left
alone unless --update is passed. Routing uses the queues / types /
priorities created by `psa_seed_defaults` when they exist and falls back
to "none" (portal submissions then use the first active queue/type).
"""
from django.core.management.base import BaseCommand

from psa.models import Queue, ServiceCatalogItem, TicketPriority, TicketType
from psa.service_requests import legacy_fields_from_schema, normalize_schema

ITEMS = [
    {
        'slug': 'portal-employee-onboarding',
        'name': 'Employee onboarding',
        'category': 'People',
        'icon': 'fas fa-user-plus',
        'description': 'Set up accounts, licenses and equipment for someone joining your team.',
        'queue': 'Helpdesk', 'type': 'Onboarding', 'priority': 'P3',
        'turnaround_text': '3 business days', 'turnaround_hours': 72,
        'subject': 'New starter — {{full_name}} ({{start_date}})',
        'body': 'Please set up a new starter.\n\nName: {{full_name}}\nJob title: {{job_title}}\n'
                'Start date: {{start_date}}\nManager: {{manager}}',
        'schema': [
            {'key': 'full_name', 'label': 'Full name', 'type': 'text', 'required': True},
            {'key': 'job_title', 'label': 'Job title', 'type': 'text'},
            {'key': 'start_date', 'label': 'Start date', 'type': 'date', 'required': True},
            {'key': 'manager', 'label': 'Manager', 'type': 'user', 'required': True,
             'help': 'Name or email of their line manager.'},
            {'key': 'licenses', 'label': 'Software needed', 'type': 'multiselect',
             'options': ['Email + Office', 'Accounting', 'CRM', 'Design tools', 'VPN']},
            {'key': 'needs_laptop', 'label': 'Needs a laptop', 'type': 'checkbox'},
            {'key': 'laptop_type', 'label': 'Laptop type', 'type': 'select', 'required': True,
             'options': ['Standard', 'Performance', 'Mac'],
             'show_if': {'field': 'needs_laptop', 'equals': True}},
            {'key': 'notes', 'label': 'Anything else we should know?', 'type': 'textarea'},
        ],
    },
    {
        'slug': 'portal-employee-offboarding',
        'name': 'Employee offboarding',
        'category': 'People',
        'icon': 'fas fa-user-minus',
        'description': 'Remove access and recover equipment when someone leaves.',
        'queue': 'Helpdesk', 'type': 'Offboarding', 'priority': 'P2',
        'turnaround_text': 'By their last day', 'turnaround_hours': 24,
        'subject': 'Leaver — {{full_name}} (last day {{last_day}})',
        'body': 'Please offboard a leaver.\n\nName: {{full_name}}\nLast day: {{last_day}}',
        'schema': [
            {'key': 'full_name', 'label': 'Full name', 'type': 'text', 'required': True},
            {'key': 'email', 'label': 'Their email address', 'type': 'email', 'required': True},
            {'key': 'last_day', 'label': 'Last working day', 'type': 'date', 'required': True},
            {'key': 'mailbox', 'label': 'What should happen to their mailbox?', 'type': 'select',
             'required': True,
             'options': ['Forward to someone', 'Convert to shared mailbox', 'Archive and remove']},
            {'key': 'forward_to', 'label': 'Forward email to', 'type': 'user', 'required': True,
             'show_if': {'field': 'mailbox', 'in': ['Forward to someone', 'Convert to shared mailbox']}},
            {'key': 'equipment', 'label': 'Equipment to collect', 'type': 'textarea',
             'placeholder': 'Laptop, phone, badge…'},
        ],
    },
    {
        'slug': 'portal-access-request',
        'name': 'Access request',
        'category': 'Access',
        'icon': 'fas fa-key',
        'description': 'Request access to a system, shared folder or mailbox.',
        'queue': 'Helpdesk', 'type': 'Access Request', 'priority': 'P3',
        'turnaround_text': '1 business day', 'turnaround_hours': 8,
        'approval': ServiceCatalogItem.APPROVAL_CUSTOMER,
        'subject': 'Access request — {{system}} for {{person}}',
        'body': 'Access requested.\n\nFor: {{person}}\nSystem: {{system}}\nLevel: {{access_level}}',
        'schema': [
            {'key': 'person', 'label': 'Who needs access?', 'type': 'user', 'required': True},
            {'key': 'system', 'label': 'System, folder or mailbox', 'type': 'text', 'required': True},
            {'key': 'access_level', 'label': 'Access level', 'type': 'select', 'required': True,
             'options': ['Read only', 'Read and write', 'Administrator']},
            {'key': 'admin_reason', 'label': 'Why is administrator access needed?', 'type': 'textarea',
             'required': True,
             'show_if': {'field': 'access_level', 'equals': 'Administrator'}},
            {'key': 'temporary', 'label': 'Temporary access', 'type': 'checkbox'},
            {'key': 'until', 'label': 'Access until', 'type': 'date', 'required': True,
             'show_if': {'field': 'temporary', 'equals': True}},
        ],
    },
    {
        'slug': 'portal-new-equipment',
        'name': 'New equipment',
        'category': 'Hardware',
        'icon': 'fas fa-laptop',
        'description': 'Order a laptop, monitor, phone or accessory.',
        'queue': 'Procurement', 'type': 'Procurement', 'priority': 'P4',
        'turnaround_text': '5–7 business days', 'turnaround_hours': 168,
        'approval': ServiceCatalogItem.APPROVAL_CUSTOMER,
        'subject': 'Equipment request — {{item_type}} for {{for_whom}}',
        'body': 'Equipment requested.\n\nItem: {{item_type}}\nFor: {{for_whom}}\nNeeded by: {{needed_by}}',
        'schema': [
            {'key': 'item_type', 'label': 'What do you need?', 'type': 'select', 'required': True,
             'options': ['Laptop', 'Monitor', 'Phone', 'Headset', 'Other']},
            {'key': 'other_item', 'label': 'Describe the item', 'type': 'text', 'required': True,
             'show_if': {'field': 'item_type', 'equals': 'Other'}},
            {'key': 'for_whom', 'label': 'Who is it for?', 'type': 'user', 'required': True},
            {'key': 'needed_by', 'label': 'Needed by', 'type': 'date'},
            {'key': 'replacement', 'label': 'This replaces broken or old equipment', 'type': 'checkbox'},
            {'key': 'business_reason', 'label': 'Business reason', 'type': 'textarea'},
        ],
    },
    {
        'slug': 'portal-application-change',
        'name': 'Application change',
        'category': 'Applications',
        'icon': 'fas fa-sliders',
        'description': 'Ask for a configuration change to one of your business applications.',
        'queue': 'Helpdesk', 'type': 'Change Request', 'priority': 'P3',
        'turnaround_text': '', 'turnaround_hours': 40,
        'approval': ServiceCatalogItem.APPROVAL_CUSTOMER,
        'subject': 'Change request — {{application}}',
        'body': 'Change requested to {{application}}.\n\nWhat: {{change}}\nWhen: {{when}}',
        'schema': [
            {'key': 'application', 'label': 'Application', 'type': 'text', 'required': True},
            {'key': 'change', 'label': 'What should change?', 'type': 'textarea', 'required': True},
            {'key': 'when', 'label': 'When should it happen?', 'type': 'select', 'required': True,
             'options': ['As soon as possible', 'Outside business hours', 'On a specific date']},
            {'key': 'change_date', 'label': 'Date', 'type': 'date', 'required': True,
             'show_if': {'field': 'when', 'equals': 'On a specific date'}},
            {'key': 'affected_users', 'label': 'Who is affected?', 'type': 'text'},
            {'key': 'contact_email', 'label': 'Contact for questions', 'type': 'email'},
        ],
    },
]


class Command(BaseCommand):
    help = 'Create sample guided service requests for the customer portal (not run automatically).'

    def add_arguments(self, parser):
        parser.add_argument('--update', action='store_true',
                            help='Refresh items that already exist (by slug).')
        parser.add_argument('--hidden', action='store_true',
                            help='Create items with portal_visible=False.')

    def handle(self, *args, **opts):
        created = updated = skipped = 0
        base_sort = 500
        for i, spec in enumerate(ITEMS):
            schema = normalize_schema(spec['schema'], allow_legacy_types=False)
            values = {
                'name': spec['name'],
                'description': spec['description'],
                'category': spec['category'],
                'icon': spec['icon'],
                'default_subject': spec['subject'],
                'default_body': spec['body'],
                'form_schema': schema,
                'fields_json': legacy_fields_from_schema(schema),
                'approval_policy': spec.get('approval', ServiceCatalogItem.APPROVAL_NONE),
                'expected_turnaround_text': spec['turnaround_text'],
                'expected_turnaround_hours': spec['turnaround_hours'],
                'default_queue': (Queue.objects.filter(name=spec['queue'], is_active=True).first()
                                  or Queue.objects.filter(name='Helpdesk', is_active=True).first()),
                'default_type': (TicketType.objects.filter(name=spec['type'], is_active=True).first()
                                 or TicketType.objects.filter(name='Service Request', is_active=True).first()),
                'default_priority': TicketPriority.objects.filter(code=spec['priority']).first(),
                'portal_visible': not opts['hidden'],
                'is_active': True,
                'sort_order': base_sort + i,
            }
            item = ServiceCatalogItem.objects.filter(slug=spec['slug']).first()
            if item is None:
                if ServiceCatalogItem.objects.filter(name=spec['name']).exists():
                    self.stdout.write(f'  skip {spec["name"]}: another item already uses that name')
                    skipped += 1
                    continue
                ServiceCatalogItem.objects.create(slug=spec['slug'], **values)
                created += 1
            elif opts['update']:
                for k, v in values.items():
                    setattr(item, k, v)
                item.save()
                updated += 1
            else:
                skipped += 1
        self.stdout.write(self.style.SUCCESS(
            f'Portal request seed: {created} created, {updated} updated, {skipped} left as-is.'))
