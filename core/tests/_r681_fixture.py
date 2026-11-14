"""Shared fixture for the v3.17.681 security matrix (test_security_r681).

Real roles only: every role template comes from accounts.role_seeds (seeded
by migration) — never a hand-built flag set. Users:

  superuser          Django superuser
  msp_admin          MSP staff, global role org_admin
  msp_owner          MSP staff, global role org_owner
  manager            MSP staff, global role service_manager
  l1 / l2 / l3       MSP staff, global roles tech_l1 / tech_l2 / tech_l3
  sales              MSP staff, global role sales_rep
  cust_admin         member of Alpha, customer_admin
  cust_user          member of Alpha, customer_user
  limited            member of Alpha's subsidiary only, customer_admin
  revoked            membership at Alpha switched off (is_active=False)

Data: Alpha (with subsidiary Alpha Branch) and Bravo, plus an inactive
client. Every searchable row carries the marker "qzx" so one query finds
them all; Bravo's rows carry "bravo" in their names.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

Q = 'qzx'


def builtin(key):
    """The built-in role `key` as accounts.role_seeds defines it. Seeded by
    migration; re-seeded from the same definitions when a --keepdb run lost
    the migration rows (a TransactionTestCase flush elsewhere)."""
    from accounts.models import RoleTemplate
    row = RoleTemplate.objects.filter(seed_key=key, organization__isnull=True).first()
    if row is None:
        from accounts.role_seeds import seed_builtin_roles
        seed_builtin_roles(RoleTemplate)
        row = RoleTemplate.objects.get(seed_key=key, organization__isnull=True)
    return row


def staff(username, template_key=None):
    from accounts.models import UserType
    u = User.objects.create_user(username, f'{username}@msp.test', 'pw-r681-sec')
    u.profile.user_type = UserType.STAFF
    u.profile.global_role_template = builtin(template_key) if template_key else None
    u.profile.save()
    return u


def member(username, org, template_key, role='readonly', active=True):
    from accounts.models import Membership
    u = User.objects.create_user(username, f'{username}@cust.test', 'pw-r681-sec')
    Membership.objects.create(user=u, organization=org, role=role, is_active=active,
                              role_template=builtin(template_key))
    return u


class R681Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        from assets.models import Asset, Contact
        from core.models import Organization, SystemSetting
        from docs.models import Document
        from integrations.models import RMMConnection, RMMDevice
        from psa.models import ClientPSASettings, Queue, Ticket, TicketPriority, TicketStatus, TicketType
        from vault.models import Password

        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()

        cls.a = Organization.objects.create(name='Alpha Qzx Co', slug='r681-alpha')
        cls.a1 = Organization.objects.create(name='Alpha Qzx Branch', slug='r681-alpha-br', parent=cls.a)
        cls.b = Organization.objects.create(name='Bravo Qzx Co', slug='r681-bravo')
        cls.gone = Organization.objects.create(name='Gone Qzx Co', slug='r681-gone', is_active=False)
        for org in (cls.a, cls.a1, cls.b, cls.gone):
            cps, _ = ClientPSASettings.objects.get_or_create(organization=org)
            cps.enabled = True
            cps.save()

        cls.su = User.objects.create_superuser('r681_root', 'root@msp.test', 'pw-r681-sec')
        cls.msp_admin = staff('r681_admin', 'org_admin')
        cls.msp_owner = staff('r681_owner', 'org_owner')
        cls.manager = staff('r681_mgr', 'service_manager')
        cls.l1 = staff('r681_l1', 'tech_l1')
        cls.l2 = staff('r681_l2', 'tech_l2')
        cls.l3 = staff('r681_l3', 'tech_l3')
        cls.sales = staff('r681_sales', 'sales_rep')
        cls.cust_admin = member('r681_cadmin', cls.a, 'customer_admin', role='admin')
        cls.cust_user = member('r681_cuser', cls.a, 'customer_user')
        cls.limited = member('r681_limited', cls.a1, 'customer_admin', role='admin')
        cls.revoked = member('r681_revoked', cls.a, 'customer_admin', role='admin', active=False)

        status = TicketStatus.objects.filter(is_terminal=False).first()
        base = dict(status=status, priority=TicketPriority.objects.first(),
                    ticket_type=TicketType.objects.first(), queue=Queue.objects.first())
        cls.t_a_shared = Ticket.objects.create(organization=cls.a, subject='qzx alpha shared printer',
                                               client_can_view=True, **base)
        cls.t_a_internal = Ticket.objects.create(organization=cls.a, subject='qzx alpha internal escalation',
                                                 client_can_view=False, **base)
        cls.t_b = Ticket.objects.create(organization=cls.b, subject='qzx bravo merger plan',
                                        client_can_view=True, **base)

        cls.asset_a = Asset.objects.create(organization=cls.a, name='qzx-alpha-fw', hostname='qzx-a.local')
        cls.asset_b = Asset.objects.create(organization=cls.b, name='qzx-bravo-fw', hostname='qzx-b.local')
        Contact.objects.create(organization=cls.a, first_name='Qzx', last_name='Alphason')
        Contact.objects.create(organization=cls.b, first_name='Qzx', last_name='Bravoson')

        conn = RMMConnection.objects.create(organization=cls.a, provider_type='ninjaone',
                                            name='R681 RMM', base_url='https://rmm.r681.test')
        cls.dev_a = RMMDevice.objects.create(organization=cls.a, connection=conn, external_id='qa',
                                             device_name='QZX-ALPHA-DC', hostname='qzx-alpha-dc')
        cls.dev_b = RMMDevice.objects.create(organization=cls.b, connection=conn, external_id='qb',
                                             device_name='QZX-BRAVO-DC', hostname='qzx-bravo-dc')

        doc = dict(is_published=True)
        cls.doc_a_public = Document.objects.create(
            organization=cls.a, title='Alpha public guide', is_client_visible=True,
            body='Printer setup. qzxpublic', **doc)
        # Shared with the customer, but the matching word only lives in an
        # internal-only block.
        cls.doc_a_mixed = Document.objects.create(
            organization=cls.a, title='Alpha VPN guide', is_client_visible=True, content_type='markdown',
            body='Connect with the client.\n\n:::internal\nbreakglass qzxsecretword admin\n:::\n', **doc)
        cls.doc_a_mixed_html = Document.objects.create(
            organization=cls.a, title='Alpha firewall guide', is_client_visible=True, content_type='html',
            body='<p>Rules overview.</p><div class="kb-internal">qzxhtmlsecret override</div>', **doc)
        cls.doc_a_internal = Document.objects.create(
            organization=cls.a, title='qzx alpha internal runbook', is_client_visible=False,
            body='internal', **doc)
        cls.doc_b = Document.objects.create(
            organization=cls.b, title='qzx bravo runbook', is_client_visible=True, body='x', **doc)
        cls.kb = Document.objects.create(
            organization=cls.a, title='qzx global kb article', is_global=True, body='kb', **doc)

        cls.pw_a = Password(organization=cls.a, title='qzx alpha router', username='netadmin')
        cls.pw_a.set_password('Sup3r-Secret-Value!')
        cls.pw_a.save()
        cls.pw_b = Password(organization=cls.b, title='qzx bravo router', username='netadmin')
        cls.pw_b.set_password('Sup3r-Secret-Value!')
        cls.pw_b.save()

    def setUp(self):
        cache.clear()

    # -- clients -------------------------------------------------------------

    def login(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.pk
        else:
            s.pop('current_organization_id', None)
            s['global_view_mode'] = True
        s.save()
        return c

    def search_html(self, client, q=Q):
        r = client.get(reverse('core:search'), {'q': q})
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def palette(self, client, q=Q):
        r = client.get(reverse('core:palette_search'), HTTP_X_PALETTE_QUERY=q)
        self.assertEqual(r.status_code, 200, r.content[:300])
        return r.json()

    @staticmethod
    def labels(data):
        return ' | '.join(f"{i['label']} {i.get('detail', '')}" for g in data['groups'] for i in g['items'])

    def workspace(self, client, org, tab=None):
        url = reverse('accounts:organization_detail', args=[org.pk])
        return client.get(url, {'tab': tab} if tab else {})
