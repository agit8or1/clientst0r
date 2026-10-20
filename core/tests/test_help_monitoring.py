"""The monitoring help page describes what the product does (v3.17.616).

It used to list TCP/ping/DNS monitor types, Slack and Teams alerts,
escalation policies and maintenance windows that silence alerts, none of which
exist, and implied WAN connections were checked on a schedule."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MonitoringHelpPageTests(TestCase):

    def setUp(self):
        user = User.objects.create_superuser('helpadmin', 'h@x.com', 'pw')
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def test_page_renders_accurate_content(self):
        r = self.client.get('/core/help/monitoring/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for text in ('Website Monitors', 'WAN Connection Checks', 'monitor.down', 'wan.down',
                     'WAN_DOWN_ALERT_THRESHOLD', '2 failed checks in a row', 'no WHOIS lookup'):
            self.assertIn(text, html)
        for text in ('TCP Port:', 'ICMP Ping:', 'Escalation Policies', 'Alert Grouping',
                     'Silence alerts during maintenance', 'Email, webhook, Slack, Teams'):
            self.assertNotIn(text, html)

    def test_search_index_points_at_existing_anchors(self):
        from core import help_views
        r = self.client.get('/core/help/monitoring/')
        html = r.content.decode()
        entries = [e for e in help_views.HELP_INDEX if e['url_name'] == 'core:help_monitoring']
        self.assertEqual(len(entries), 6)
        for e in entries:
            self.assertIn(f'id="{e["anchor"]}"', html)
