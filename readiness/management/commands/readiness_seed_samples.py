"""Create the sample "Microsoft 365 tenant documentation" standard.

Not run automatically. Idempotent: an existing standard with the same name is
left untouched. Documentation only — nothing here talks to Microsoft 365.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from readiness.models import DocumentationStandard, StandardRequirement as R
from readiness.params import validate_params

NAME = 'Microsoft 365 tenant documentation'

REQUIREMENTS = [
    ('Tenant identifier documented', R.KIND_DOCUMENT_EXISTS,
     {'tag': 'm365', 'title_contains': 'tenant'}, 3,
     'A document tagged "m365" with "tenant" in the title records the tenant name, '
     'tenant ID and primary domain. Without it, nobody can open a vendor case or '
     'confirm which tenant a change was made in.'),
    ('Responsible contacts', R.KIND_CONTACT_ROLE,
     {'title_contains': 'm365|microsoft 365|office 365|it contact|it manager', 'min_count': 1}, 2,
     'At least one customer contact whose title names them as the Microsoft 365 / IT '
     'contact, so approvals and licence decisions have someone to go to.'),
    ('Licensing & renewal documented', R.KIND_DOCUMENT_EXISTS,
     {'tag': 'm365', 'title_contains': 'licens|renewal|subscription'}, 2,
     'Which licences the customer holds, how many, who bills them and when they renew. '
     'Missed renewals take mailboxes offline.'),
    ('Admin credential reference exists', R.KIND_CREDENTIAL_REFERENCE,
     {'title_contains': 'global admin|m365 admin|microsoft 365 admin|office 365 admin|break glass'}, 3,
     'A vault entry for the tenant admin / break-glass account exists, so the team '
     'knows where the credential lives (the secret itself is never shown here).'),
    ('Recovery procedure documented', R.KIND_DOCUMENT_EXISTS,
     {'tag': 'm365', 'title_contains': 'recovery|break glass|break-glass|restore'}, 3,
     'How to regain admin access and restore mail/files if the tenant is compromised '
     'or an admin locks themselves out.'),
    ('Tenant documentation verified in the last 180 days', R.KIND_DOCUMENT_FRESH,
     {'tag': 'm365', 'title_contains': 'tenant', 'max_age_days': 180, 'basis': 'reviewed'}, 2,
     'Someone has marked the tenant document reviewed in the last 180 days, so the '
     'domains, admins and settings it lists can be trusted.'),
]


class Command(BaseCommand):
    help = 'Create the sample "Microsoft 365 tenant documentation" readiness standard.'

    def add_arguments(self, parser):
        parser.add_argument('--inactive', action='store_true',
                            help='Create the standard switched off.')

    @transaction.atomic
    def handle(self, *args, **opts):
        if DocumentationStandard.objects.filter(name=NAME).exists():
            self.stdout.write(f'"{NAME}" already exists; left unchanged.')
            return
        std = DocumentationStandard.objects.create(
            name=NAME, scope=DocumentationStandard.SCOPE_ALL, is_active=not opts['inactive'],
            description='What every customer using Microsoft 365 should have documented. '
                        'Add an exception for customers who do not use Microsoft 365.')
        for i, (title, kind, params, weight, desc) in enumerate(REQUIREMENTS):
            R.objects.create(standard=std, title=title, kind=kind,
                             params=validate_params(kind, params), weight=weight,
                             description=desc, order=i)
        self.stdout.write(self.style.SUCCESS(
            f'Created "{NAME}" with {len(REQUIREMENTS)} requirements.'))
