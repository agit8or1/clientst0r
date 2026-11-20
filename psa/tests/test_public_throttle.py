"""Rate limits on the public, token-only pages: quote signing and CSAT
responses. POSTs are limited harder than page views, per client address and
per token, and a limited request never records anything or reveals whether a
token exists."""
import re
from decimal import Decimal

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from core.models import Organization, SystemSetting
from django.contrib.auth.models import User
from psa.models import Quote, QuoteLineItem, QuoteSignature, TicketCSATSurvey

from ._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed
from .test_quote_signature_binding import PNG

IP_A, IP_B = '203.0.113.10', '203.0.113.11'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuoteSignThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        _enable_psa_global()
        _setup_seed()
        self.msp = Organization.objects.create(name='MSP', slug='msp-t')
        self.client_org = Organization.objects.create(name='Acme', slug='acme-t')
        self.quotes = [self._quote(i) for i in range(2)]

    def _quote(self, i):
        q = Quote.objects.create(organization=self.msp, client_org=self.client_org,
                                 title=f'Quote {i}', status='sent', tax_rate=Decimal('0'))
        QuoteLineItem.objects.create(quote=q, sort_order=0, description='Thing',
                                     quantity=Decimal('1'), unit_price=Decimal('100'))
        q.recompute_totals()
        return q

    def _url(self, q):
        return f'/portal/quote/{q.customer_token}/sign/'

    def _post(self, q, ip=IP_A, content_hash='x'):
        return Client().post(self._url(q), {
            'signed_by_name': 'Pat', 'signed_by_email': 'p@acme.test',
            'signature_data': PNG, 'content_hash': content_hash}, REMOTE_ADDR=ip)

    def test_normal_view_and_sign(self):
        q = self.quotes[0]
        r = Client().get(self._url(q), REMOTE_ADDR=IP_A)
        self.assertEqual(r.status_code, 200)
        r = self._post(q, content_hash=r.context['content_hash'])
        self.assertNotEqual(r.status_code, 429)
        self.assertEqual(QuoteSignature.objects.filter(quote=q).count(), 1)

    def test_post_limit_returns_429_and_records_nothing(self):
        q = self.quotes[0]
        for _ in range(10):
            self.assertNotEqual(self._post(q).status_code, 429)  # stale hash: refused, not recorded
        h = Client().get(self._url(q), REMOTE_ADDR=IP_B).context['content_hash']
        r = self._post(q, content_hash=h)  # right hash, but the 11th submission
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r['Retry-After'], '60')
        self.assertEqual(QuoteSignature.objects.count(), 0)

    def test_limits_are_per_token_and_per_ip(self):
        q, other = self.quotes
        for _ in range(10):
            self._post(q)
        # Same token from another address: the token bucket still blocks it.
        self.assertEqual(self._post(q, ip=IP_B).status_code, 429)
        # Another token from another address is unaffected.
        self.assertNotEqual(self._post(other, ip=IP_B).status_code, 429)
        # Same address, another token: the address bucket blocks it.
        self.assertEqual(self._post(other, ip=IP_A).status_code, 429)

    def test_view_limit_is_looser_and_unknown_tokens_look_the_same(self):
        q = self.quotes[0]
        for _ in range(60):
            self.assertEqual(Client().get(self._url(q), REMOTE_ADDR=IP_A).status_code, 200)
        self.assertEqual(Client().get(self._url(q), REMOTE_ADDR=IP_A).status_code, 429)
        # A made-up token is limited the same way (404 until the cap, then 429).
        bogus = '/portal/quote/nope-nope/sign/'
        self.assertEqual(Client().get(bogus, REMOTE_ADDR=IP_B).status_code, 404)
        for _ in range(59):
            Client().get(bogus, REMOTE_ADDR=IP_B)
        r = Client().get(bogus, REMOTE_ADDR=IP_B)
        self.assertEqual(r.status_code, 429)
        self.assertNotIn(b'nope', r.content)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CSATThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_csat_enabled = True
        s.save()
        self.org = Organization.objects.create(name='CSATThr', slug='csat-thr')
        self.tokens = [self._survey(i) for i in range(2)]

    def _survey(self, i):
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        t = Ticket.objects.create(
            organization=self.org, subject=f'S{i}', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            requester_email='c@example.com', requester_name='C')
        t.status = TicketStatus.objects.filter(is_terminal=True).first()
        t.save()
        return re.search(r'/psa/csat/([^/\s]+)/', mail.outbox[-1].body).group(1)

    def _post(self, token, rating='5', ip=IP_A):
        return Client().post(f'/psa/csat/{token}/', {'rating': rating}, REMOTE_ADDR=ip)

    def test_normal_use_records_rating(self):
        r = self._post(self.tokens[0])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(TicketCSATSurvey.objects.filter(rating=5).count(), 1)

    def test_post_limit_returns_429_and_records_nothing(self):
        t = self.tokens[0]
        for _ in range(10):
            self.assertEqual(self._post(t, rating='99').status_code, 200)  # invalid: not recorded
        r = self._post(t, rating='4')
        self.assertEqual(r.status_code, 429)
        self.assertEqual(TicketCSATSurvey.objects.exclude(rating=None).count(), 0)

    def test_limits_are_per_token_and_per_ip(self):
        a, b = self.tokens
        for _ in range(10):
            self._post(a, rating='99')
        self.assertEqual(self._post(a, ip=IP_B).status_code, 429)
        self.assertEqual(self._post(b, ip=IP_B).status_code, 200)

    def test_unknown_token_is_limited_without_leaking(self):
        for _ in range(10):
            self.assertEqual(self._post('bogus-token', ip=IP_B).status_code, 404)
        r = self._post('bogus-token', ip=IP_B)
        self.assertEqual(r.status_code, 429)
