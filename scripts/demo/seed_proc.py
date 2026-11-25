"""Give the demo procurement vendors purchasing details and link the demo
purchase orders to them, so the Vendors pages show open orders and spend.

Isolated demo database only. Idempotent. Every name and address is invented.
"""
import os, sys

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from assets.models import Vendor
from psa.models import PurchaseOrder

VENDORS = [
    # name, slug, terms, lead days, contact method, email, phone, account, distributor, address, notes
    ('Dell', 'dell', 'net_30', 5, 'portal', 'orders@dell-sales.example', '555-0141', 'BMI-20417', '',
     '1 Commerce Way\nRound Rock, TX 78664', 'Business desktops and laptops. Quote numbers go in the PO notes.'),
    ('Cisco Meraki', 'cisco-meraki', 'net_30', 10, 'email', 'orders@meraki-resale.example', '555-0162', 'BMI-77120', 'ingram',
     '500 Terry Francois Blvd\nSan Francisco, CA 94158', 'Licences are co-termed; order hardware and licence together.'),
    ('HP', 'hp', 'net_45', 7, 'email', 'orders@hp-channel.example', '555-0188', 'BMI-31955', 'synnex',
     '1501 Page Mill Rd\nPalo Alto, CA 94304', ''),
    ('Panduit', 'panduit', 'prepaid', 14, 'phone', 'sales@panduit-dist.example', '555-0123', '', '',
     '18900 Panduit Dr\nTinley Park, IL 60487', 'Cabling and patch panels.'),
]
for (name, slug, terms, lead, method, email, phone, acct, dist, addr, notes) in VENDORS:
    v = Vendor.objects.filter(name=name).first() or Vendor(name=name, slug=slug)
    v.is_active = True
    v.payment_terms = terms
    v.default_lead_time_days = lead
    v.preferred_contact_method = method
    v.contact_email = email
    v.contact_phone = phone
    v.account_number = acct
    v.distributor_provider = dist
    v.billing_address = addr
    v.notes = notes
    v.save()

for po in PurchaseOrder.objects.filter(vendor__isnull=True):
    v = Vendor.objects.filter(name=po.vendor_name).first()
    if v:
        po.vendor = v
        po.vendor_email = po.vendor_email or v.contact_email
        po.save(update_fields=['vendor', 'vendor_email'])
print('vendors', Vendor.objects.count(), 'linked POs', PurchaseOrder.objects.filter(vendor__isnull=False).count())
