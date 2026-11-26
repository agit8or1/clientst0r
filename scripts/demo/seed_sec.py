"""Give the demo's security pages a believable shape: vendor connections and a
SIEM endpoint that the existing demo alerts arrived through, one alert turned
into a ticket, a customer on the weekly digest, and exposure scores.

Isolated demo database only. Every name, host and address is invented
(`.example`); nothing here is polled and no request leaves the machine: the
vendors are webhook-only, and the connections have polling switched off.
Idempotent.
"""
import os, sys

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.utils import timezone
from assets.models import Contact
from core.models import Organization
from psa.models import Ticket
from security_alerts.exposure import compute_exposure_score
from security_alerts.models import (
    SecurityAlert, SecurityDigestSubscription, SecurityVendorConnection, SIEMWebhookEndpoint,
)

msp = Organization.objects.get(name='Beacon Managed IT')

# (name, provider, category, client or None)
CONNECTIONS = [
    ('Huntress - all clients', 'huntress', 'edr', None),
    ('Fortinet edge firewalls', 'fortinet', 'firewall', None),
    ('Defender - Northwind', 'defender', 'edr', 'Northwind Logistics'),
]
conns = {}
for name, provider, category, client in CONNECTIONS:
    obj = SecurityVendorConnection.objects.filter(organization=msp, name=name).first()
    if obj is None:
        obj = SecurityVendorConnection(
            organization=msp, name=name, provider=provider, category=category,
            client_org=Organization.objects.filter(name=client).first() if client else None,
            base_url='https://security.example', sync_enabled=False, is_active=True)
        obj.save()
    conns[provider] = obj

siem = SIEMWebhookEndpoint.objects.filter(organization=msp, name='Graylog - Microsoft 365 audit').first()
if siem is None:
    siem = SIEMWebhookEndpoint(organization=msp, name='Graylog - Microsoft 365 audit', expected_format='json')
    siem.save()
siem.received_count = 6
siem.last_seen_at = timezone.now()
siem.save()

SOURCE = {
    'Ransomware behaviour blocked: mass file renames': ('conn', 'huntress'),
    'Potentially unwanted program detected: browser toolbar': ('conn', 'huntress'),
    'Repeated VPN login failures from one address': ('conn', 'fortinet'),
    'Impossible travel: sign-ins 4,000 km apart within 20 minutes': ('siem', None),
    'Suspicious inbox rule created after sign-in from new country': ('siem', None),
}
for a in SecurityAlert.objects.filter(organization=msp, connection__isnull=True, siem_endpoint__isnull=True):
    kind, key = SOURCE.get(a.title, (None, None))
    if kind == 'conn':
        a.connection = conns[key]
    elif kind == 'siem':
        a.siem_endpoint = siem
    else:
        continue
    a.save(update_fields=['connection', 'siem_endpoint'])

# One alert that already became a ticket.
alert = SecurityAlert.objects.filter(title__startswith='Suspicious inbox rule', client_org__name='Northwind Logistics').first()
ticket = Ticket.objects.filter(organization__name='Northwind Logistics').order_by('pk').first()
if alert and ticket and not alert.auto_ticket_id:
    alert.auto_ticket = ticket
    alert.save(update_fields=['auto_ticket'])

# Weekly digest for one customer.
nwl = Organization.objects.get(name='Northwind Logistics')
contact = Contact.objects.filter(organization=nwl).exclude(email='').first()
if contact:
    sub, _ = SecurityDigestSubscription.objects.get_or_create(organization=nwl, email=contact.email.lower())
    if not sub.contact_id:
        sub.contact = contact
    sub.set_subscribed(True, via='staff')

for org in Organization.objects.filter(is_active=True):
    org.exposure_score = compute_exposure_score(org)
    org.exposure_score_updated_at = timezone.now()
    org.save(update_fields=['exposure_score', 'exposure_score_updated_at'])
print('security demo data ready')
