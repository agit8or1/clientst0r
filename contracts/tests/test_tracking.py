"""Link requests vs likely human views vs verified views, alert de-duplication
and the repeat-view cooldown."""
from datetime import timedelta

from django.test import RequestFactory, override_settings
from django.utils import timezone

from contracts import tracking
from contracts.models import ContractAlert, ContractDocument as D, ContractInvitation, ContractNotification

from .base import BROWSER, ContractTestCase, links_in_outbox, make_staff


class ClassifierTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def _cls(self, method='get', inv=None, **meta):
        req = getattr(self.rf, method)('/sign/t/x/', **meta)
        return tracking.classify(req, inv)

    def test_real_browser_is_not_automated(self):
        self.assertFalse(self._cls(**BROWSER)['automated'])

    def test_strong_indicators(self):
        cases = {
            'head': dict(method='head', **BROWSER),
            'prefetch': dict(HTTP_SEC_PURPOSE='prefetch', **BROWSER),
            'preview': dict(HTTP_PURPOSE='preview', **BROWSER),
            'no ua': {k: v for k, v in BROWSER.items() if k != 'HTTP_USER_AGENT'},
            'safelinks': {**BROWSER, 'HTTP_USER_AGENT': 'Mozilla/5.0 (compatible; SafeLinks scanner)'},
            'proofpoint': {**BROWSER, 'HTTP_USER_AGENT': 'Proofpoint URL Defense'},
            'slack': {**BROWSER, 'HTTP_USER_AGENT': 'Slackbot-LinkExpanding 1.0'},
            'curl': {**BROWSER, 'HTTP_USER_AGENT': 'curl/8.4.0'},
            'headless': {**BROWSER, 'HTTP_USER_AGENT': 'Mozilla/5.0 HeadlessChrome/120.0'},
        }
        for name, meta in cases.items():
            with self.subTest(name):
                method = meta.pop('method', 'get')
                self.assertTrue(self._cls(method, **meta)['automated'], name)

    @override_settings(CONTRACTS_SCANNER_NETWORKS=['203.0.113.0/24'])
    def test_scanner_network(self):
        from unittest import mock
        with mock.patch('core.client_ip.get_client_ip', return_value='203.0.113.9'):
            self.assertIn('scanner_network', self._cls(**BROWSER)['indicators'])

    def test_weak_indicators_need_two(self):
        one = {k: v for k, v in BROWSER.items() if k != 'HTTP_ACCEPT_LANGUAGE'}
        self.assertFalse(self._cls(**one)['automated'])
        two = {k: v for k, v in one.items() if not k.startswith('HTTP_SEC_FETCH')}
        self.assertTrue(self._cls(**two)['automated'])

    def test_request_right_after_the_email_is_weak(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        ContractInvitation.objects.filter(pk=inv.pk).update(last_sent_at=timezone.now())
        inv.refresh_from_db()
        res = self._cls(inv=inv, **{k: v for k, v in BROWSER.items() if k != 'HTTP_ACCEPT_LANGUAGE'})
        self.assertIn('requested_seconds_after_email', res['indicators'])
        self.assertTrue(res['automated'])


class ViewTrackingTests(ContractTestCase):

    def _sent(self, **kw):
        c = self.new_contract(**kw)
        self.issue_and_send(c)
        return c, c.invitations.get(), links_in_outbox()[0]

    def test_scanner_fetches_never_count_as_views(self):
        c, inv, token = self._sent()
        scanner = self.client_class(HTTP_USER_AGENT='Mozilla/5.0 (compatible; Barracuda Sentinel)')
        r = scanner.head(f'/sign/t/{token}/')
        self.assertEqual(r.status_code, 200)
        r = scanner.get(f'/sign/t/{token}/')
        page = r['Location']
        r = scanner.get(page)
        self.assertEqual(r.status_code, 200)
        # even posting the beacon from an automated client does nothing
        scanner.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': r.context['nonce'], 'interacted': '1'})
        c.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(c.status, D.SENT)
        self.assertEqual((c.view_count, inv.view_count), (0, 0))
        self.assertEqual(inv.link_request_count, 2)
        self.assertFalse(ContractNotification.objects.filter(kind='view').exists())
        ev = c.events.filter(kind='link_requested').first()
        self.assertTrue(ev.data['automated'])
        # The prefetching browser (Sec-Purpose: prefetch) is also only a link request.
        pre = self.client_class(HTTP_SEC_PURPOSE='prefetch', **BROWSER)
        pre.get(f'/sign/t/{token}/')
        c.refresh_from_db()
        self.assertEqual(c.view_count, 0)

    def test_page_load_without_interaction_is_not_a_view(self):
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)
        cl.get(page)
        c.refresh_from_db()
        self.assertEqual(c.view_count, 0)
        r = cl.get(page)
        cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': r.context['nonce']})   # no interaction flag
        cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': 'forged', 'interacted': '1'})
        c.refresh_from_db()
        self.assertEqual(c.view_count, 0)

    def test_beacon_counts_once_per_page_view_and_alerts_once(self):
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)
        r = cl.get(page)
        nonce = r.context['nonce']
        for _ in range(3):   # replays of the same page view
            cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': nonce, 'interacted': '1'})
        c.refresh_from_db()
        self.assertEqual(c.view_count, 1)
        self.assertEqual(c.status, D.VIEWED)
        first = ContractNotification.objects.filter(contract=c, user=self.staff, kind='view')
        self.assertEqual(first.count(), 1)
        self.assertIn('identity not verified', first.get().message)
        # A second real page view counts but the first-view alert is not repeated.
        r = cl.get(page)
        cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': r.context['nonce'], 'interacted': '1'})
        c.refresh_from_db()
        self.assertEqual(c.view_count, 2)
        self.assertEqual(first.count(), 1)

    def test_beacon_needs_the_signing_session(self):
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)
        nonce = cl.get(page).context['nonce']
        other = self.client_class(**BROWSER)
        other.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': nonce, 'interacted': '1'})
        c.refresh_from_db()
        self.assertEqual(c.view_count, 0)

    def test_repeat_view_alerts_respect_cooldown(self):
        from contracts.models import ContractSettings
        s = ContractSettings.deployment_default()
        s.notify_repeat_views = True
        s.repeat_view_cooldown_minutes = 60
        s.save()
        c, inv, token = self._sent()
        cl, page = self.signer_client(token)

        def view():
            n = cl.get(page).context['nonce']
            cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': n, 'interacted': '1'})
        view()                      # first view alert
        view()                      # within cooldown: counted, no alert
        alerts = ContractNotification.objects.filter(contract=c, user=self.staff, kind='view')
        self.assertEqual(alerts.count(), 1)
        ContractInvitation.objects.filter(pk=inv.pk).update(last_view_alert_at=timezone.now() - timedelta(hours=2))
        view()                      # after cooldown: repeat-view alert
        self.assertEqual(alerts.count(), 2)
        view()
        self.assertEqual(alerts.count(), 2)
        c.refresh_from_db()
        self.assertEqual(c.view_count, 4)

    def test_verified_view_wording(self):
        c, inv, token = self._sent(require_email_verification=True)
        self.assertIn('after entering a code', tracking.view_message(inv, 'email_code'))
        self.assertIn(inv.email, tracking.view_message(inv, 'email_code'))
        self.assertNotIn(inv.name, tracking.view_message(inv, 'link'))

    def test_alert_keys_are_unique(self):
        c, inv, token = self._sent()
        from contracts import notify
        self.assertTrue(notify.raise_alert(c, 'k:1', 'x'))
        self.assertFalse(notify.raise_alert(c, 'k:1', 'x'))
        self.assertEqual(ContractAlert.objects.filter(key='k:1').count(), 1)

    def test_notifications_go_to_owner_and_configured_people(self):
        dave = make_staff('dave', role={'contracts_view': True})
        c, inv, token = self._sent()
        c.notify_users.add(dave)
        cl, page = self.signer_client(token)
        n = cl.get(page).context['nonce']
        cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': n, 'interacted': '1'})
        self.assertTrue(ContractNotification.objects.filter(contract=c, user=dave).exists())
        self.assertTrue(ContractNotification.objects.filter(contract=c, user=self.staff).exists())
