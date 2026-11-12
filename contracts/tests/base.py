"""Shared helpers for the contract-document tests."""
import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech

BROWSER = {
    'HTTP_USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/131.0 Safari/537.36',
    'HTTP_ACCEPT_LANGUAGE': 'en-US,en;q=0.9',
    'HTTP_SEC_FETCH_MODE': 'navigate',
    'HTTP_SEC_FETCH_SITE': 'none',
}
LINK_RE = re.compile(r'https?://[^\s]+/sign/t/([A-Za-z0-9_\-]+)/')


def make_org(name='Acme Dental', email='owner@acme.test'):
    from core.models import Organization
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return Organization.objects.create(name=name, slug=slug, primary_contact_name='Pat Client',
                                       primary_contact_email=email, primary_contact_title='Owner')


def make_staff(username='tech', superuser=False, **extra):
    u = User.objects.create_user(username, f'{username}@msp.test', 'pw-Long-enough-123',
                                 first_name=username.title(), is_superuser=superuser, **extra)
    _make_msp_tech(u)
    return u


def links_in_outbox(to=None):
    out = []
    for m in mail.outbox:
        if to and to not in m.to:
            continue
        out += LINK_RE.findall(m.body)
    return out


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, SITE_URL='https://msp.example.test')
class ContractTestCase(TestCase):
    """A client, an MSP superuser technician and a ready-to-edit contract."""

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.org = make_org()
        self.staff = make_staff('alice', superuser=True)
        self.client.force_login(self.staff)

    # --- building blocks -------------------------------------------------------
    def new_contract(self, org=None, *, signers=None, sections=None, items=None, **fields):
        from contracts import services
        from contracts.models import ContractSigner
        org = org or self.org
        c = services.create_contract(org, self.staff, title=fields.pop('title', 'Managed services agreement'))
        c.signers.all().delete()
        c.sections = sections or [
            {'title': 'Services', 'type': 'text', 'body': '<p>We look after {{client.name}}.</p>'},
            {'title': 'Fees', 'type': 'pricing', 'body': '<p>Fees are below.</p>'},
            {'title': 'Signatures', 'type': 'signatures', 'body': ''}]
        c.line_items = items if items is not None else [
            {'description': 'Setup', 'kind': 'one_time', 'quantity': '1', 'unit_price': '500'},
            {'description': 'Per user', 'kind': 'recurring', 'quantity': '10', 'unit_price': '25'}]
        for k, v in fields.items():
            setattr(c, k, v)
        from contracts.content import normalize_line_items, normalize_sections
        c.sections = normalize_sections(c.sections)
        c.line_items = normalize_line_items(c.line_items)
        c.save()
        services._recompute_totals(c)
        c.save()
        for i, s in enumerate(signers or [{'name': 'Pat Client', 'email': 'pat@acme.test'}]):
            ContractSigner.objects.create(contract=c, role=s.get('role', 'client'), name=s['name'], email=s['email'],
                                          order=s.get('order', i + 1), user=s.get('user'))
        return c

    def issue_and_send(self, c, email=True):
        from contracts import services
        services.submit(c, self.staff)
        c.refresh_from_db()
        return services.send(c, self.staff, email=email)

    def signer_client(self, token, **headers):
        """A fresh browser that opened the e-mailed link."""
        cl = Client(**{**BROWSER, **headers})
        r = cl.get(f'/sign/t/{token}/')
        self.assertEqual(r.status_code, 302, r.content[:300])
        return cl, r['Location']

    def sign_post(self, cl, inv, **over):
        inv.refresh_from_db()
        v = inv.version
        data = {'printed_name': inv.name, 'method': 'typed', 'typed_signature': inv.name, 'consent': 'yes',
                'intent': 'yes', 'version_id': v.pk, 'content_hash': v.content_hash}
        data.update(over)
        return cl.post(f'/sign/i/{inv.public_id}/sign/', data)
