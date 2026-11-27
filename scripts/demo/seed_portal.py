"""Demo data for the customer portal guide (docs/CUSTOMER_PORTAL.md).

Adds, for Northwind Logistics only and idempotently:
  * a billing contact and a customer administrator, so the guide can show
    what each sees;
  * a portal status page with a few services and one planned maintenance;
  * two credentials shared with the customer (one for everyone, one the
    customer administrator hands out);
  * a policy acknowledgment waiting for signature.

Isolated demo database only. Every name, address and secret is invented.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Membership, RoleTemplate, UserProfile, UserType
from core.models import Organization

User = get_user_model()
now = timezone.now()
nwl = Organization.objects.get(name='Northwind Logistics')
lead = User.objects.get(username='demo.tech')


def customer(username, first, last, email, template_key, org_admin=False):
    u, _ = User.objects.get_or_create(
        username=username, defaults={'email': email, 'first_name': first, 'last_name': last})
    u.set_unusable_password()
    u.is_staff = u.is_superuser = False
    u.save()
    profile, _ = UserProfile.objects.get_or_create(user=u)
    profile.user_type = UserType.ORG_USER
    profile.save()
    tpl = RoleTemplate.objects.filter(seed_key=template_key).first()
    m, _ = Membership.objects.get_or_create(user=u, organization=nwl, defaults={'role': 'readonly', 'is_active': True})
    m.role_template = tpl
    m.is_org_admin = org_admin
    m.is_active = True
    m.save()
    return u


rosa = customer('demo.rbennett', 'Rosa', 'Bennett', 'rosa.bennett@northwind.example', 'customer_billing_contact')
nora = customer('demo.nlindgren', 'Nora', 'Lindgren', 'nora.lindgren@northwind.example', 'customer_admin',
                org_admin=True)
print('  portal: billing contact', rosa.username, '; customer administrator', nora.username)

# --- status page for the customer's portal ---------------------------------
from monitoring.models import WebsiteMonitor
from statuspage.models import MaintenanceWindow, StatusPage, StatusPageService

page = StatusPage.objects.filter(organization=nwl, visibility=StatusPage.VISIBILITY_PORTAL).first()
if page is None:
    page = StatusPage.objects.create(title='Northwind service status', organization=nwl,
                                     visibility=StatusPage.VISIBILITY_PORTAL, is_enabled=True,
                                     show_uptime=True, created_by=lead)
for order, (mon_name, shown, desc) in enumerate([
        ('Northwind WMS', 'Warehouse system', 'Order picking and stock'),
        ('Northwind public site', 'Public website', ''),
        ('Northwind customer portal', 'Customer ordering portal', 'Trade customers placing orders')]):
    mon = WebsiteMonitor.objects.filter(organization=nwl, name=mon_name).first()
    if mon:
        StatusPageService.objects.get_or_create(
            page=page, monitor=mon, defaults=dict(display_name=shown, description=desc, sort_order=order))
if not page.maintenance_windows.exists():
    start = now + timedelta(days=3, hours=2)
    MaintenanceWindow.objects.create(
        page=page, title='Core switch firmware update', starts_at=start, ends_at=start + timedelta(hours=1),
        body='The depot network is offline for about ten minutes while the switch restarts.')
print('  portal: status page', page.pk)

# --- shared credentials -----------------------------------------------------
from vault.models import Password, PasswordFolder

folder, _ = PasswordFolder.objects.get_or_create(name='Shared with customer', organization=nwl)
for title, user_name, url, mode in [
        ('Guest Wi-Fi (front office)', 'guest', '', 'all_org'),
        ('Supplier ordering site', 'orders@northwind.example', 'https://supplier.example/login',
         'org_admin_managed')]:
    p = Password.objects.filter(title=title, organization=nwl).first()
    if p is None:
        p = Password(title=title, organization=nwl, folder=folder, username=user_name, url=url,
                     created_by=lead)
        p.set_password('Demo-Placeholder-4821')
    p.client_visible = True
    p.client_access_mode = mode
    p.save()
    if mode == 'org_admin_managed':
        p.client_allowed_users.set([nora])
print('  portal: shared credentials')

# --- an agreement waiting for signature ---------------------------------------
from docs import agreements
from docs.models import Document

doc = Document.objects.filter(organization=nwl, slug='acceptable-use-policy').first()
if doc is None:
    doc = Document.objects.create(
        organization=nwl, slug='acceptable-use-policy', title='Acceptable use policy', content_type='html',
        category=None, is_published=True, created_by=lead,
        body='<h2>Using Northwind systems</h2><p>Company laptops, accounts and the network are for '
             'Northwind business. Keep your password private, report lost devices the same day, and do not '
             'install software the IT team has not approved.</p>')
agreements.make_agreement(doc, lead, kind='policy', mode='acknowledgment', audience='each')
print('  portal: agreement', doc.title)
