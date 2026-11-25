"""Seed the demo knowledge base so the review, approval and suggestion screens
have something to show: two articles waiting for approval (one customer's, one
global), a customer-visible published article with a tag, and a ticket tagged so
that article is suggested on it.

Isolated demo database only. Every name and body is invented. Idempotent.
"""
import os, sys

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Organization, Tag
from docs.models import Document, DocumentCategory
from psa.models import Ticket

User = get_user_model()
now = timezone.now()
org = Organization.objects.get(name='Northwind Logistics')
home = Organization.objects.order_by('pk').first()
tech = User.objects.get(username='demo.tech')
priya = User.objects.get(username='demo.ipatel')
mo = User.objects.get(username='demo.mokafor')


def article(slug, title, body, owner, **kw):
    org_ = kw.pop('organization', org)
    doc, created = Document.objects.get_or_create(
        organization=org_, slug=slug,
        defaults=dict(title=title, body=body, content_type='markdown', owner=owner,
                      created_by=owner, last_modified_by=owner, **kw))
    return doc


article('guest-wi-fi-onboarding-steps', 'Guest Wi-Fi onboarding steps',
        '# Guest Wi-Fi onboarding\n\n1. Create the voucher in the controller.\n2. Print the card.\n'
        '3. Tell the visitor the network is isolated from the warehouse VLAN.\n',
        priya, is_published=False, is_draft=True, requires_approval=True)

article('conditional-access-policy-checklist', 'Conditional access policy checklist',
        '# Conditional access checklist\n\n- Block legacy authentication\n- Require MFA for admins\n'
        '- Review sign-in risk weekly\n',
        mo, organization=home, is_global=True, is_published=False, is_draft=True,
        requires_approval=True)

zebra = article('zebra-label-printer-blank-labels', 'Zebra label printer prints blank labels',
                '# Blank labels\n\nUsually the wrong media type is set. Run the media calibration, then check the '
                'darkness setting.\n\n:::internal\nThe dock 2 unit has a worn platen; swap it if calibration fails.\n:::\n',
                tech, is_published=True, is_client_visible=True, review_interval_days=90,
                published_at=now - timedelta(days=20))
tag, _ = Tag.objects.get_or_create(organization=org, slug='zebra-printer', defaults={'name': 'zebra-printer'})
zebra.tags.add(tag)

t = Ticket.objects.filter(ticket_number='PSA-2026-000013').first()
if t and 'zebra-printer' not in (t.tags or []):
    t.tags = list(t.tags or []) + ['zebra-printer']
    t.save(update_fields=['tags'])
print('kb seed done')
