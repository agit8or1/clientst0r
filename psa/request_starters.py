"""
Starter request types an administrator can add and then customise.

Adding a starter creates an ordinary request type as a **draft**: nothing is
offered to customers until an administrator reviews and publishes it.

These forms collect requests. None of them asks for a password, MFA code,
recovery code or other secret (the schema validator refuses such fields),
and submitting one never provisions an account, grants or removes access,
disables a user or changes a phone system: it opens a ticket for a
technician.
"""
from __future__ import annotations

from .service_requests import normalize_schema

YES_NO = [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'}]

ACCESS_NOTE = ('Naming an existing user tells us which access is similar. It does not '
               'authorise copying all of their permissions: list what the new person '
               'actually needs below.')

STARTERS = [
    {
        'key': 'new_employee',
        'name': 'New employee / new user',
        'category': 'People',
        'icon': 'fas fa-user-plus',
        'description': 'Set up accounts, access and equipment for someone joining your team.',
        'subject': 'New user: {{first_name}} {{last_name}} — starts {{start_date}}',
        'turnaround_text': '3 business days',
        'approval': 'customer',
        'confirmation': ("Thanks — we've got the details for your new starter. We'll confirm "
                         "timing and ask if anything is missing. No accounts are created until "
                         "a technician has reviewed the request."),
        'schema': [
            {'key': 'sec_person', 'type': 'heading', 'label': 'The new person'},
            {'key': 'first_name', 'label': 'First name', 'type': 'text', 'required': True},
            {'key': 'last_name', 'label': 'Last name', 'type': 'text', 'required': True},
            {'key': 'display_name', 'label': 'Preferred display name', 'type': 'text',
             'help': 'How their name should appear in email and chat, if different.'},
            {'key': 'job_title', 'label': 'Job title', 'type': 'text'},
            {'key': 'department', 'label': 'Department', 'type': 'text'},
            {'key': 'manager', 'label': 'Manager', 'type': 'contact', 'required': True},
            {'key': 'start_date', 'label': 'Start date', 'type': 'date', 'required': True,
             'requested_date': True},
            {'key': 'sec_where', 'type': 'heading', 'label': 'Where they will work'},
            {'key': 'remote', 'label': 'Remote employee?', 'type': 'radio', 'required': True,
             'options': YES_NO},
            {'key': 'office', 'label': 'Office / location', 'type': 'location',
             'show_if': {'field': 'remote', 'op': 'equals', 'value': 'no'},
             'required_if': {'field': 'remote', 'op': 'equals', 'value': 'no'}},
            {'key': 'shipping_address', 'label': 'Shipping address for equipment',
             'type': 'textarea', 'sensitive': True,
             'show_if': {'field': 'remote', 'op': 'equals', 'value': 'yes'},
             'required_if': {'field': 'remote', 'op': 'equals', 'value': 'yes'}},
            {'key': 'sec_access', 'type': 'heading', 'label': 'Accounts and access'},
            {'key': 'requested_email', 'label': 'Requested email address or username',
             'type': 'text', 'placeholder': 'e.g. jane.smith'},
            {'key': 'applications', 'label': 'Applications and access they need',
             'type': 'textarea', 'required': True},
            {'key': 'reference_user', 'label': 'Existing user with similar access (optional)',
             'type': 'contact', 'help': ACCESS_NOTE},
            {'key': 'groups', 'label': 'Distribution groups or shared mailboxes', 'type': 'textarea'},
            {'key': 'sec_equipment', 'type': 'heading', 'label': 'Equipment'},
            {'key': 'needs_computer', 'label': 'Needs a computer?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'computer_requirements', 'label': 'Computer requirements', 'type': 'textarea',
             'placeholder': 'e.g. laptop, two monitors, design software',
             'show_if': {'field': 'needs_computer', 'op': 'equals', 'value': 'yes'},
             'required_if': {'field': 'needs_computer', 'op': 'equals', 'value': 'yes'}},
            {'key': 'needs_phone', 'label': 'Needs a phone or extension?', 'type': 'radio',
             'options': YES_NO},
            {'key': 'phone_details', 'label': 'Phone / extension details', 'type': 'text',
             'show_if': {'field': 'needs_phone', 'op': 'equals', 'value': 'yes'}},
            {'key': 'instructions', 'label': 'Additional instructions', 'type': 'textarea'},
            {'key': 'no_secrets', 'type': 'info', 'label': '',
             'help': "Please don't include passwords or sign-in codes. We set credentials up "
                     "securely and share them with the new person directly."},
        ],
    },
    {
        'key': 'new_phone',
        'name': 'New phone / extension',
        'category': 'Phones',
        'icon': 'fas fa-phone-volume',
        'description': 'Request a desk phone, softphone or extension, or port an existing number.',
        'subject': 'New phone / extension: {{employee}}',
        'turnaround_text': '5 business days',
        'confirmation': "Thanks — we'll review the phone request and confirm the timing with you.",
        'schema': [
            {'key': 'employee', 'label': 'Employee / contact', 'type': 'contact', 'required': True},
            {'key': 'location', 'label': 'Location', 'type': 'location'},
            {'key': 'device', 'label': 'What do they need?', 'type': 'radio', 'required': True,
             'options': [{'value': 'desk', 'label': 'Desk phone'},
                         {'value': 'softphone', 'label': 'Softphone (app)'},
                         {'value': 'both', 'label': 'Both'}]},
            {'key': 'number', 'label': 'Phone number', 'type': 'radio', 'required': True,
             'options': [{'value': 'new', 'label': 'A new number'},
                         {'value': 'existing', 'label': 'Keep / port an existing number'}]},
            {'key': 'extension', 'label': 'Requested extension', 'type': 'text',
             'placeholder': 'e.g. 214'},
            {'key': 'port_number', 'label': 'Existing number to port', 'type': 'tel',
             'show_if': {'field': 'number', 'op': 'equals', 'value': 'existing'},
             'required_if': {'field': 'number', 'op': 'equals', 'value': 'existing'}},
            {'key': 'port_provider', 'label': 'Current provider', 'type': 'text',
             'show_if': {'field': 'number', 'op': 'equals', 'value': 'existing'},
             'required_if': {'field': 'number', 'op': 'equals', 'value': 'existing'}},
            {'key': 'features', 'label': 'Calling features', 'type': 'multiselect',
             'options': ['Voicemail', 'Voicemail to email', 'Call group / hunt group',
                         'Call forwarding', 'International calling', 'Call recording']},
            {'key': 'call_groups', 'label': 'Call groups to join', 'type': 'text',
             'show_if': {'field': 'features', 'op': 'contains', 'value': 'Call group / hunt group'}},
            {'key': 'ship', 'label': 'Ship the phone somewhere other than the location above?',
             'type': 'checkbox', 'show_if': {'field': 'device', 'op': 'in', 'value': ['desk', 'both']}},
            {'key': 'shipping_details', 'label': 'Shipping / delivery details', 'type': 'textarea',
             'sensitive': True, 'show_if': {'field': 'ship', 'equals': True},
             'required_if': {'field': 'ship', 'op': 'equals', 'value': True}},
            {'key': 'needed_by', 'label': 'Needed by', 'type': 'date', 'requested_date': True,
             'not_in_past': True},
            {'key': 'instructions', 'label': 'Additional instructions', 'type': 'textarea'},
        ],
    },
    {
        'key': 'offboard',
        'name': 'Offboard an employee',
        'category': 'People',
        'icon': 'fas fa-user-minus',
        'description': 'Remove access and recover equipment when someone leaves.',
        'subject': 'Offboard: {{employee}} — last day {{last_day}}',
        'turnaround_text': 'By the disable time you give',
        'approval': 'customer',
        'confirmation': ("Thanks. Nothing is disabled automatically: a technician schedules the "
                         "change for the date and time you gave, once the request is approved."),
        'schema': [
            {'key': 'employee', 'label': 'Employee / account', 'type': 'contact', 'required': True},
            {'key': 'last_day', 'label': 'Last working day', 'type': 'date', 'required': True},
            {'key': 'disable_at', 'label': 'Disable access at', 'type': 'datetime', 'required': True,
             'help': 'The exact time access should stop, in the time zone you pick.'},
            {'key': 'approver', 'label': 'Manager or approving contact', 'type': 'contact',
             'required': True},
            {'key': 'sec_data', 'type': 'heading', 'label': 'Email and files'},
            {'key': 'mailbox', 'label': 'Mailbox', 'type': 'select', 'required': True,
             'options': ['Convert to shared mailbox', 'Delegate to someone', 'Forward email',
                         'Archive and remove', 'Not sure — please advise']},
            {'key': 'mailbox_delegate', 'label': 'Who should get access to the mailbox?',
             'type': 'contact',
             'show_if': {'field': 'mailbox', 'op': 'in',
                         'value': ['Delegate to someone', 'Forward email']},
             'required_if': {'field': 'mailbox', 'op': 'in',
                             'value': ['Delegate to someone', 'Forward email']}},
            {'key': 'files', 'label': 'File ownership / transfer', 'type': 'textarea',
             'placeholder': 'Who should receive their files and shared folders?'},
            {'key': 'sec_kit', 'type': 'heading', 'label': 'Equipment and phone'},
            {'key': 'equipment', 'label': 'Equipment return details', 'type': 'textarea'},
            {'key': 'phone', 'label': 'Phone handling', 'type': 'select',
             'options': ['Remove the extension', 'Reassign to someone', 'Forward calls',
                         'No phone']},
            {'key': 'instructions', 'label': 'Additional instructions', 'type': 'textarea'},
        ],
    },
    {
        'key': 'general_support',
        'name': 'General support',
        'category': 'Support',
        'icon': 'fas fa-life-ring',
        'description': "Something not working, or a request that doesn't fit another category.",
        'subject': '{{subject}}',
        'confirmation': "Thanks — we've received your request and will be in touch.",
        'schema': [
            {'key': 'subject', 'label': 'Subject', 'type': 'text', 'required': True,
             'max_length': 200, 'placeholder': 'e.g. Email is not working on my laptop'},
            {'key': 'description', 'label': 'Describe the problem', 'type': 'textarea',
             'required': True,
             'placeholder': 'When did it start? What have you tried? Any error messages?'},
            {'key': 'affected', 'label': 'Affected user, device or location', 'type': 'text'},
            {'key': 'impact', 'label': 'Business impact', 'type': 'radio', 'maps_to': 'urgency',
             'help': 'This helps us understand the impact. Priority is set by our support '
                     'team under your service agreement.',
             'options': [{'value': 'low', 'label': 'Minor — I can work around it'},
                         {'value': 'medium', 'label': 'Slows me down'},
                         {'value': 'high', 'label': 'I or my team cannot work'},
                         {'value': 'critical', 'label': 'The whole business is affected'}]},
            {'key': 'attachments', 'label': 'Attachments', 'type': 'file', 'max_files': 5,
             'help': 'Screenshots or documents (up to 5 files, 25 MB each).'},
        ],
    },
    {
        'key': 'change_access', 'name': 'Change user access', 'category': 'Access',
        'icon': 'fas fa-user-lock',
        'description': 'Add or remove access to an application, folder, group or mailbox.',
        'subject': 'Access change: {{person}}',
        'approval': 'customer',
        'schema': [
            {'key': 'person', 'label': 'Who is it for?', 'type': 'contact', 'required': True},
            {'key': 'change', 'label': 'Add or remove access?', 'type': 'radio', 'required': True,
             'options': [{'value': 'add', 'label': 'Add access'},
                         {'value': 'remove', 'label': 'Remove access'}]},
            {'key': 'what', 'label': 'Which system, folder, group or mailbox?',
             'type': 'textarea', 'required': True},
            {'key': 'needed_by', 'label': 'Needed by', 'type': 'date', 'requested_date': True},
        ],
    },
    {
        'key': 'phone_problem', 'name': 'Phone problem', 'category': 'Phones',
        'icon': 'fas fa-phone-slash', 'description': 'A phone, extension or voicemail is not working.',
        'subject': 'Phone problem: {{summary}}',
        'schema': [
            {'key': 'summary', 'label': "What's wrong?", 'type': 'text', 'required': True},
            {'key': 'extension', 'label': 'Extension or number affected', 'type': 'text'},
            {'key': 'location', 'label': 'Location', 'type': 'location'},
            {'key': 'details', 'label': 'Details', 'type': 'textarea'},
        ],
    },
    {
        'key': 'new_equipment', 'name': 'New computer / equipment', 'category': 'Hardware',
        'icon': 'fas fa-laptop', 'description': 'Order a computer, monitor, dock or other equipment.',
        'subject': 'Equipment request: {{item}}',
        'approval': 'customer',
        'schema': [
            {'key': 'for_whom', 'label': 'Who is it for?', 'type': 'contact', 'required': True},
            {'key': 'item', 'label': 'What do you need?', 'type': 'text', 'required': True},
            {'key': 'replacing', 'label': 'Is it replacing a device?', 'type': 'checkbox'},
            {'key': 'old_device', 'label': 'Device being replaced', 'type': 'asset',
             'show_if': {'field': 'replacing', 'equals': True}},
            {'key': 'needed_by', 'label': 'Needed by', 'type': 'date', 'requested_date': True},
            {'key': 'notes', 'label': 'Notes', 'type': 'textarea'},
        ],
    },
    {
        'key': 'software_access', 'name': 'Software / application access',
        'category': 'Access', 'icon': 'fas fa-window-restore',
        'description': 'Install software or get access to an application.',
        'subject': 'Software request: {{application}} for {{person}}',
        'schema': [
            {'key': 'person', 'label': 'Who is it for?', 'type': 'contact', 'required': True},
            {'key': 'application', 'label': 'Application', 'type': 'text', 'required': True},
            {'key': 'licence', 'label': 'Do you already have a licence for it?', 'type': 'radio',
             'options': [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'},
                         {'value': 'unsure', 'label': 'Not sure'}]},
            {'key': 'device', 'label': 'Which device?', 'type': 'asset'},
            {'key': 'notes', 'label': 'Notes', 'type': 'textarea'},
        ],
    },
    {
        'key': 'network_problem', 'name': 'Network / internet problem', 'category': 'Support',
        'icon': 'fas fa-wifi', 'description': 'The internet, Wi-Fi or a network connection is down or slow.',
        'subject': 'Network problem at {{location}}',
        'schema': [
            {'key': 'location', 'label': 'Location', 'type': 'location', 'required': True},
            {'key': 'scope', 'label': 'Who is affected?', 'type': 'radio', 'required': True,
             'options': [{'value': 'me', 'label': 'Just me'},
                         {'value': 'some', 'label': 'Some people'},
                         {'value': 'everyone', 'label': 'Everyone at this location'}]},
            {'key': 'symptom', 'label': 'What are you seeing?', 'type': 'multiselect',
             'options': ['No internet', 'Slow', 'Wi-Fi only', 'Wired only', 'Drops in and out']},
            {'key': 'since', 'label': 'Since when?', 'type': 'text'},
            {'key': 'details', 'label': 'Details', 'type': 'textarea'},
        ],
    },
]

BY_KEY = {s['key']: s for s in STARTERS}


def starter_schema(key):
    return normalize_schema(BY_KEY[key]['schema'], allow_legacy_types=False)


def install(key, user):
    """Create the starter as a draft request type and return it."""
    from django.utils import timezone

    from .models import ServiceCatalogItem
    from .request_forms import name_taken, unique_slug
    from .service_requests import legacy_fields_from_schema
    spec = BY_KEY[key]
    schema = starter_schema(key)
    name, n = spec['name'], 1
    while name_taken(name, None):
        n += 1
        name = f'{spec["name"]} ({n})'
    return ServiceCatalogItem.objects.create(
        name=name, slug=unique_slug(spec['name']),
        description=spec['description'], category=spec['category'], icon=spec['icon'],
        default_subject=spec['subject'],
        approval_policy=spec.get('approval', ServiceCatalogItem.APPROVAL_NONE),
        expected_turnaround_text=spec.get('turnaround_text', ''),
        confirmation_message=spec.get('confirmation', ''),
        lifecycle=ServiceCatalogItem.LIFECYCLE_DRAFT, is_active=True, portal_visible=True,
        form_schema=schema, fields_json=legacy_fields_from_schema(schema),
        draft_schema=schema, draft_updated_at=timezone.now(), draft_updated_by=user,
        starter_key=key, sort_order=100 + STARTERS.index(spec),
    )
