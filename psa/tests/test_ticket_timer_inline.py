"""113.9: inline ticket timer (JSON start/stop, no full reload) and its
placement in the first viewport."""
import time
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import (Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _make_msp_tech, _setup_seed

JSON = {'HTTP_ACCEPT': 'application/json'}


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InlineTimerTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME', slug='acme')
        _enable_psa_for(self.org)
        self.user = _make_msp_tech(User.objects.create_user('tech', password='pw', email='t@x.com'))
        Membership.objects.update_or_create(
            user=self.user, organization=self.org, defaults={'role': Role.OWNER, 'is_active': True})
        self.client = Client(); self.client.force_login(self.user)
        s = self.client.session; s['current_organization_id'] = self.org.id; s.save()
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Timer test', queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(is_terminal=False).first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first())
        self.base = f'/psa/t/{self.ticket.ticket_number}/timer/'

    def test_json_start_and_stop(self):
        r = self.client.post(self.base + 'start/', {'is_billable': '1'}, **JSON)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['running']); self.assertIn('started_at', d)
        e = TicketTimeEntry.objects.get(ticket=self.ticket, user=self.user)
        self.assertTrue(e.is_running); self.assertTrue(e.is_billable)
        TicketTimeEntry.objects.filter(pk=e.pk).update(started_at=timezone.now() - timedelta(minutes=7))
        r = self.client.post(self.base + 'stop/', **JSON)
        d = r.json()
        self.assertFalse(d['running']); self.assertGreaterEqual(d['minutes'], 6)
        e.refresh_from_db()
        self.assertFalse(e.is_running); self.assertGreaterEqual(e.duration_minutes, 6)

    def test_start_is_idempotent_and_state_endpoint(self):
        self.client.post(self.base + 'start/', **JSON)
        d = self.client.post(self.base + 'start/', **JSON).json()
        self.assertTrue(d['running'])
        self.assertEqual(TicketTimeEntry.objects.filter(ticket=self.ticket).count(), 1)
        st = self.client.get(self.base + 'state/', **JSON)
        self.assertTrue(st.json()['running']); self.assertIn('no-store', st['Cache-Control'])
        self.client.post(self.base + 'stop/', **JSON)
        self.assertFalse(self.client.get(self.base + 'state/').json()['running'])

    def test_stop_without_timer_is_not_an_error(self):
        d = self.client.post(self.base + 'stop/', **JSON).json()
        self.assertFalse(d['running'])
        self.assertEqual(TicketTimeEntry.objects.count(), 0)

    def test_csrf_required(self):
        c = Client(enforce_csrf_checks=True); c.force_login(self.user)
        s = c.session; s['current_organization_id'] = self.org.id; s.save()
        r = c.post(self.base + 'start/', **JSON)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(TicketTimeEntry.objects.count(), 0)

    def test_get_not_allowed_on_start(self):
        self.assertEqual(self.client.get(self.base + 'start/', **JSON).status_code, 405)

    def test_customer_user_denied(self):
        other = User.objects.create_user('cust', password='pw', email='c@x.com')
        Membership.objects.update_or_create(
            user=other, organization=self.org, defaults={'role': Role.OWNER, 'is_active': True})
        c = Client(); c.force_login(other)
        s = c.session; s['current_organization_id'] = self.org.id; s.save()
        for url in ('start/', 'stop/'):
            self.assertEqual(c.post(self.base + url, **JSON).status_code, 403)
        self.assertEqual(c.get(self.base + 'state/', **JSON).status_code, 403)
        self.assertEqual(TicketTimeEntry.objects.count(), 0)

    def test_other_users_timer_not_visible_or_stoppable(self):
        other = _make_msp_tech(User.objects.create_user('tech2', password='pw', email='t2@x.com'))
        Membership.objects.update_or_create(
            user=other, organization=self.org, defaults={'role': Role.OWNER, 'is_active': True})
        e = TicketTimeEntry.objects.create(ticket=self.ticket, user=other, started_at=timezone.now())
        d = self.client.post(self.base + 'stop/', **JSON).json()
        self.assertFalse(d['running'])
        e.refresh_from_db(); self.assertTrue(e.is_running)

    def test_no_js_fallback_redirects_and_creates_same_entry(self):
        r = self.client.post(self.base + 'start/', {'is_billable': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(TicketTimeEntry.objects.get(ticket=self.ticket).is_running)
        r = self.client.post(self.base + 'stop/', {'notes': 'done'})
        self.assertEqual(r.status_code, 302)
        e = TicketTimeEntry.objects.get(ticket=self.ticket)
        self.assertFalse(e.is_running); self.assertEqual(e.notes, 'done')

    def test_server_time_budget(self):
        t0 = time.perf_counter(); self.client.post(self.base + 'start/', **JSON)
        start_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); self.client.post(self.base + 'stop/', **JSON)
        stop_ms = (time.perf_counter() - t0) * 1000
        print(f'\n[113.9] server time start={start_ms:.0f} ms stop={stop_ms:.0f} ms')
        self.assertLess(start_ms, 300); self.assertLess(stop_ms, 300)

    def test_include_before_conversation_and_state_reflects_timer(self):
        html = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        i, j = html.find('id="ticketTimerInline"'), html.find('id="conversation"')
        self.assertGreater(i, 0); self.assertGreater(j, i)
        self.assertIn('data-running="0"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.client.post(self.base + 'start/')
        html = self.client.get(f'/psa/t/{self.ticket.ticket_number}/').content.decode()
        self.assertIn('data-running="1"', html)
        self.assertIn('aria-pressed="true"', html)
        self.assertIn('/timer/stop/', html[html.find('id="ticketTimerInline"'):html.find('id="conversation"')])
