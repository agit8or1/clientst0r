"""
v3.17.611 — share/link tokens, partner payload and license keys at rest.

* SecureNote links: hash only, shown once, regenerate.
* Status page / wallboard / quote sign links: encrypted (re-displayable)
  plus an HMAC lookup column.
* CSAT survey links: hash only, the email carries the token.
* Existing tokens keep working after the data migrations.
* The partner ticket-share payload never carries the shared secret.
* Vault license keys are masked and revealed only through the audited gate.
"""
import importlib
from types import SimpleNamespace
import json
import re
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SecureNote
from vault import secret_fields as sf

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _login_in_org(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


def _row(model, pk, *cols):
    qn = connection.ops.quote_name
    with connection.cursor() as cur:
        cur.execute(f'SELECT {", ".join(qn(c) for c in cols)} FROM {qn(model._meta.db_table)} '
                    f'WHERE {qn(model._meta.pk.column)} = %s', [pk])
        return cur.fetchone()


def _set(model, pk, **cols):
    qn = connection.ops.quote_name
    sets = ', '.join(f'{qn(c)} = %s' for c in cols)
    with connection.cursor() as cur:
        cur.execute(f'UPDATE {qn(model._meta.db_table)} SET {sets} '
                    f'WHERE {qn(model._meta.pk.column)} = %s', list(cols.values()) + [pk])


def _run(op_or_func):
    from django.apps import apps
    func = getattr(op_or_func, 'code', op_or_func)
    func(apps, SimpleNamespace(connection=connection))


def _ticket(org, **kw):
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    from psa.tests._base import _setup_seed
    _setup_seed()
    return Ticket.objects.create(
        organization=org, queue=Queue.objects.first(),
        priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
        status=TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first(),
        **kw)


def _migration_op(module, index):
    return importlib.import_module(module).Migration.operations[index]


# ---------------------------------------------------------------------------
# SecureNote
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecureNoteLinkTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='LinkOrg', slug='link-org')
        self.sender = User.objects.create_user('link-sender', password='pw')
        Membership.objects.create(user=self.sender, organization=self.org,
                                  role=Role.OWNER, is_active=True)
        self.c = Client()
        _login_in_org(self.c, self.sender, self.org)

    def _create(self):
        resp = self.c.post('/core/secure-notes/create/', {
            'title': 'wifi', 'content': 'the-wifi-password', 'link_only': 'on'})
        self.assertEqual(resp.status_code, 200)
        url = resp.context['share_url']
        token = re.search(r'/core/secret/([^/]+)/', url).group(1)
        return SecureNote.objects.get(title='wifi'), token

    def test_link_shown_once_and_only_hash_stored(self):
        note, token = self._create()
        stored, issued = _row(SecureNote, note.pk, 'access_token_hash', 'link_issued_at')
        self.assertEqual(stored, SecureNote.hash_access_token(token))
        self.assertNotIn(token, stored)
        self.assertIsNotNone(issued)
        resp = Client().get(f'/core/secret/{token}/')
        self.assertContains(resp, 'the-wifi-password')
        # Later screens cannot show it — they offer a regenerate action.
        for path in (f'/core/secure-notes/{note.pk}/link/',
                     '/core/secure-notes/links-dashboard/',
                     f'/core/secure-notes/{note.pk}/analytics/'):
            page = self.c.get(path)
            self.assertEqual(page.status_code, 200, path)
            self.assertNotContains(page, token)
            self.assertContains(page, f'/core/secure-notes/{note.pk}/link/regenerate/')

    def test_regenerate_revokes_old_link(self):
        note, old = self._create()
        resp = self.c.post(f'/core/secure-notes/{note.pk}/link/regenerate/')
        self.assertEqual(resp.status_code, 200)
        new = re.search(r'/core/secret/([^/]+)/', resp.context['share_url']).group(1)
        self.assertNotEqual(old, new)
        self.assertEqual(Client().get(f'/core/secret/{old}/').status_code, 404)
        self.assertContains(Client().get(f'/core/secret/{new}/'), 'the-wifi-password')

    def test_other_user_cannot_regenerate(self):
        note, _token = self._create()
        other = User.objects.create_user('nosy', password='pw')
        c = Client()
        _login_in_org(c, other, self.org)
        self.assertEqual(c.post(f'/core/secure-notes/{note.pk}/link/regenerate/').status_code, 404)

    def test_recipient_notes_do_not_collide(self):
        # '' in a UNIQUE column used to make the second non-link note fail.
        a = SecureNote(sender=self.sender, title='a')
        a.set_content('x')
        a.save()
        b = SecureNote(sender=self.sender, title='b')
        b.set_content('y')
        b.save()
        self.assertIsNone(_row(SecureNote, b.pk, 'access_token_hash')[0])

    def test_legacy_raw_token_still_works_after_migration(self):
        note, _ = self._create()
        legacy = 'L' * 64
        _set(SecureNote, note.pk, access_token_hash=legacy, link_issued_at=None)
        self.assertEqual(Client().get(f'/core/secret/{legacy}/').status_code, 404)
        _run(importlib.import_module('core.migrations.0076_hash_share_link_tokens').hash_tokens)
        stored, issued = _row(SecureNote, note.pk, 'access_token_hash', 'link_issued_at')
        self.assertTrue(sf.looks_like_token_hash(stored))
        self.assertIsNotNone(issued)
        self.assertContains(Client().get(f'/core/secret/{legacy}/'), 'the-wifi-password')


# ---------------------------------------------------------------------------
# Status page, wallboard, quote: encrypted + hash
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReDisplayableLinkTests(TestCase):
    def test_status_page_token_encrypted_and_lookup_by_hash(self):
        from statuspage.models import StatusPage
        page = StatusPage.objects.create(title='S', is_enabled=True)
        token = page.token
        raw_token, raw_hash = _row(StatusPage, page.pk, 'token', 'token_hash')
        self.assertTrue(sf.is_sealed(raw_token))
        self.assertNotIn(token, raw_token)
        self.assertEqual(raw_hash, StatusPage.hash_link_token(token))
        self.assertEqual(StatusPage.objects.get(pk=page.pk).token, token)  # re-displayable
        self.assertEqual(Client().get(f'/status/p/{token}/').status_code, 200)
        old = token
        page.rotate_token()
        self.assertEqual(Client().get(f'/status/p/{old}/').status_code, 404)
        self.assertEqual(Client().get(f'/status/p/{page.token}/').status_code, 200)

    def test_status_page_legacy_token_migrated(self):
        from statuspage.models import StatusPage
        page = StatusPage.objects.create(title='S', is_enabled=True)
        legacy = 'legacy-status-token-0123456789abcdefghijklmn'
        _set(StatusPage, page.pk, token=legacy, token_hash='')
        _run(_migration_op('statuspage.migrations.0005_encrypt_hash_link_token', 2))
        raw_token, raw_hash = _row(StatusPage, page.pk, 'token', 'token_hash')
        self.assertTrue(sf.is_sealed(raw_token))
        self.assertEqual(StatusPage.objects.get(pk=page.pk).token, legacy)
        self.assertEqual(Client().get(f'/status/p/{legacy}/').status_code, 200)

    def test_wallboard_token_encrypted_and_legacy_migrated(self):
        from scheduling.models import SchedulerWallboard
        board = SchedulerWallboard.get_board()
        board.is_enabled = True
        board.save()
        token = board.token
        raw_token, raw_hash = _row(SchedulerWallboard, board.pk, 'token', 'token_hash')
        self.assertTrue(sf.is_sealed(raw_token))
        self.assertEqual(raw_hash, SchedulerWallboard.hash_link_token(token))
        self.assertEqual(Client().get(f'/scheduling/wallboard/{token}/').status_code, 200)

        legacy = 'legacy-wallboard-token-0123456789abcdefghijk'
        _set(SchedulerWallboard, board.pk, token=legacy, token_hash='')
        _run(_migration_op('scheduling.migrations.0005_encrypt_hash_wallboard_token', 2))
        self.assertTrue(sf.is_sealed(_row(SchedulerWallboard, board.pk, 'token')[0]))
        self.assertEqual(Client().get(f'/scheduling/wallboard/{legacy}/').status_code, 200)
        self.assertEqual(Client().get(f'/scheduling/wallboard/{token}/').status_code, 404)

    def _quote(self):
        from psa.models import Quote
        org = Organization.objects.create(name='QOrg', slug='q-org')
        client_org = Organization.objects.create(name='QClient', slug='q-client')
        return Quote.objects.create(organization=org, client_org=client_org, title='Q')

    def test_quote_token_encrypted_and_sign_page_works(self):
        from psa.models import Quote
        q = self._quote()
        token = q.customer_token
        raw_token, raw_hash = _row(Quote, q.pk, 'customer_token', 'customer_token_hash')
        self.assertTrue(sf.is_sealed(raw_token))
        self.assertNotIn(token, raw_token)
        self.assertEqual(raw_hash, Quote.hash_customer_token(token))
        self.assertEqual(Quote.objects.get(pk=q.pk).customer_token, token)
        self.assertEqual(Client().get(f'/portal/quote/{token}/sign/').status_code, 200)
        self.assertEqual(Client().get('/portal/quote/not-a-token/sign/').status_code, 404)

    def test_quote_legacy_token_migrated(self):
        from psa.models import Quote
        q = self._quote()
        legacy = 'legacy-quote-token-0123456789abcdefghijklmnop'
        _set(Quote, q.pk, customer_token=legacy, customer_token_hash='')
        _run(_migration_op('psa.migrations.0074_quote_csat_link_tokens', 2))
        self.assertTrue(sf.is_sealed(_row(Quote, q.pk, 'customer_token')[0]))
        self.assertEqual(Client().get(f'/portal/quote/{legacy}/sign/').status_code, 200)

    def test_csat_legacy_token_migrated(self):
        from psa.models import Ticket, TicketCSATSurvey
        org = Organization.objects.create(name='CsatOrg', slug='csat-org')
        ticket = _ticket(org, subject='s', requester_email='r@x.com')
        survey = TicketCSATSurvey.objects.create(ticket=ticket, organization=org,
                                                 recipient_email='r@x.com')
        fresh = survey.raw_token
        self.assertEqual(_row(TicketCSATSurvey, survey.pk, 'token_hash')[0],
                         TicketCSATSurvey.hash_survey_token(fresh))
        self.assertEqual(Client().get(f'/psa/csat/{fresh}/').status_code, 200)

        legacy = 'legacy-csat-token-0123456789abcdefghijklmnopq'
        _set(TicketCSATSurvey, survey.pk, token_hash=legacy)
        _run(_migration_op('psa.migrations.0074_quote_csat_link_tokens', 4))
        self.assertTrue(sf.looks_like_token_hash(_row(TicketCSATSurvey, survey.pk, 'token_hash')[0]))
        self.assertEqual(Client().get(f'/psa/csat/{legacy}/').status_code, 200)


# ---------------------------------------------------------------------------
# Partner share payload
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PartnerSharePayloadTests(TestCase):
    def test_payload_has_no_shared_secret(self):
        from psa.models import Ticket
        org = Organization.objects.create(name='MSP', slug='msp-share')
        partner = Organization.objects.create(
            name='Partner', slug='partner-share', is_outsourcing_partner=True,
            partner_endpoint_url='https://partner.example.com/hook')
        secret = Organization.objects.get(pk=partner.pk).partner_secret
        self.assertTrue(secret)
        admin = User.objects.create_superuser('share-admin', password='pw')
        Membership.objects.create(user=admin, organization=org, role=Role.OWNER, is_active=True)
        ticket = _ticket(org, subject='Help')
        c = Client()
        _login_in_org(c, admin, org)

        sent = {}

        class _Resp:
            status_code = 200

        def fake_post(self_session, url, data=None, headers=None, **kw):
            sent['body'] = data
            sent['headers'] = headers
            return _Resp()

        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        if hasattr(s, 'psa_enabled'):
            s.psa_enabled = True
            s.save()
        with mock.patch('requests.Session.post', fake_post), \
                mock.patch('core.safe_http.guard_session', lambda sess, policy: sess):
            c.post(f'/psa/t/{ticket.ticket_number}/share/', {'partner_org': str(partner.pk)})

        self.assertIn('body', sent, 'partner webhook was not called')
        body = sent['body'].decode('utf-8')
        self.assertNotIn(secret, body)
        self.assertNotIn(secret, json.dumps(sent['headers']))
        payload = json.loads(body)
        self.assertNotIn('partner_secret_token', payload)
        self.assertEqual(payload['partner_id'], partner.pk)
        # The signature still proves possession of the secret.
        import hashlib
        import hmac
        self.assertEqual(sent['headers']['X-CST0R-Signature'],
                         hmac.new(secret.encode(), sent['body'], hashlib.sha256).hexdigest())


# ---------------------------------------------------------------------------
# Vault license key
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LicenseKeyRevealTests(TestCase):
    KEY = 'LIC-AAAA-BBBB-CCCC'

    def setUp(self):
        from vault.models import Password
        self.org = Organization.objects.create(name='LicOrg', slug='lic-org')
        self.user = User.objects.create_user('lic-user', password='pw')
        Membership.objects.create(user=self.user, organization=self.org,
                                  role=Role.OWNER, is_active=True)
        self.pw = Password.objects.create(organization=self.org, title='Office',
                                          password_type='software_license',
                                          license_key=self.KEY)
        self.pw.set_password('pw-value')
        self.pw.save()
        self.c = Client()
        _login_in_org(self.c, self.user, self.org)

    def test_detail_page_masks_license_key(self):
        resp = self.c.get(f'/vault/{self.pw.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self.KEY)
        self.assertContains(resp, 'reveal-license-btn')

    def test_reveal_returns_key_and_is_audited(self):
        from audit.models import AuditLog
        resp = self.c.post(f'/vault/{self.pw.pk}/reveal/?field=license_key')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'license_key': self.KEY})
        self.assertTrue(AuditLog.objects.filter(
            action='reveal', object_id=self.pw.pk, extra_data__field='license_key').exists())

    def test_reveal_requires_approval_when_configured(self):
        self.pw.requires_reveal_approval = True
        self.pw.save()
        resp = self.c.post(f'/vault/{self.pw.pk}/reveal/?field=license_key')
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(self.KEY, resp.content.decode())

    def test_unknown_field_rejected(self):
        resp = self.c.post(f'/vault/{self.pw.pk}/reveal/?field=notes')
        self.assertEqual(resp.status_code, 400)

    def test_api_masks_unless_revealed(self):
        from api.serializers import PasswordDetailSerializer

        class _View:
            action = 'retrieve'

        class _Req:
            def __init__(self, reveal):
                self.query_params = {'reveal': 'true'} if reveal else {}
                self.user = None

        masked = PasswordDetailSerializer(self.pw, context={'request': _Req(False), 'view': _View()})
        self.assertEqual(masked.data['license_key'], '**********')
        shown = PasswordDetailSerializer(self.pw, context={'request': _Req(True), 'view': _View()})
        self.assertEqual(shown.data['license_key'], self.KEY)
