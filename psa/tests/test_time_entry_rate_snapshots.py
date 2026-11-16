"""Time entries snapshot their bill / cost rate when created (pricing app).

Later rate card or cost rate edits never change an existing entry, entries
without any pricing configuration are flagged rate-missing (no invented
rate), and entries that existed before pricing are left alone.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from pricing.models import LaborRole, RateCard, RateCardLine
from psa.models import Contract, Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType
from psa.tests._base import _setup_seed
from resourcing.models import TechCostRate

D = Decimal


class TimeEntryRateSnapshotTests(TestCase):
    def setUp(self):
        _setup_seed()
        # One install = one MSP; organizations are its customers.
        self.client_org = Organization.objects.create(name='Client', slug='snap-client')
        self.other = Organization.objects.create(name='Other client', slug='snap-other')
        self.user = User.objects.create_user('snap-tech', password='pw')
        self.contract = Contract.objects.create(
            organization=self.client_org, client_org=self.client_org, name='Block', status='active',
            contract_type='block_hours', start_date=timezone.localdate() - timedelta(days=10),
            total_hours=D('1'))
        self.ticket = Ticket.objects.create(
            organization=self.client_org, subject='Rates', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())
        self.role = LaborRole.objects.create(name='Help desk', code='T1')
        self.card = RateCard.objects.create(name='MSP default')
        self.line = RateCardLine.objects.create(rate_card=self.card, role=self.role, hourly_rate=D('125'))
        TechCostRate.objects.create(user=self.user, rate_per_hour=D('48'),
                                    effective_from=timezone.localdate() - timedelta(days=100))

    def _entry(self, minutes=30, **kw):
        now = timezone.now()
        defaults = dict(ticket=self.ticket, user=self.user, started_at=now - timedelta(minutes=minutes),
                        ended_at=now, duration_minutes=minutes, role_code='T1')
        defaults.update(kw)
        return TicketTimeEntry.objects.create(**defaults)

    def test_snapshot_on_create(self):
        e = self._entry()
        e.refresh_from_db()
        self.assertEqual(e.bill_rate_snapshot, D('125'))
        self.assertEqual(e.cost_rate_snapshot, D('48'))
        self.assertEqual(e.rate_card_line, self.line)
        self.assertEqual(e.labor_role, self.role)
        self.assertEqual(e.contract, self.contract)
        self.assertEqual(e.rate_type, 'standard')
        self.assertIs(e.rate_missing, False)
        self.assertEqual(e.included_vs_overage, 'included')

    def test_later_rate_edits_do_not_change_existing_entries(self):
        e = self._entry()
        self.line.hourly_rate = D('175')
        self.line.save()
        TechCostRate.objects.create(user=self.user, rate_per_hour=D('70'), effective_from=timezone.localdate()
                                    - timedelta(days=1))
        e.refresh_from_db()
        e.notes = 'edited'
        e.duration_minutes = 45
        e.save()
        e.refresh_from_db()
        self.assertEqual((e.bill_rate_snapshot, e.cost_rate_snapshot), (D('125'), D('48')))
        new = self._entry()
        new.refresh_from_db()
        self.assertEqual((new.bill_rate_snapshot, new.cost_rate_snapshot), (D('175'), D('70')))

    def test_deleted_rate_line_keeps_snapshot_value(self):
        e = self._entry()
        self.line.delete()
        e.refresh_from_db()
        self.assertIsNone(e.rate_card_line)
        self.assertEqual(e.bill_rate_snapshot, D('125'))

    def test_no_configuration_flags_missing(self):
        self.card.delete()
        TechCostRate.objects.all().delete()
        e = self._entry()
        e.refresh_from_db()
        self.assertIsNone(e.bill_rate_snapshot)
        self.assertIsNone(e.cost_rate_snapshot)
        self.assertIs(e.rate_missing, True)
        self.assertTrue(e.rate_missing_reason)

    def test_other_customers_rate_card_is_not_used(self):
        self.card.delete()
        card = RateCard.objects.create(client_org=self.other, name='Theirs')
        RateCardLine.objects.create(rate_card=card, role=None, hourly_rate=D('999'))
        e = self._entry()
        e.refresh_from_db()
        self.assertIsNone(e.bill_rate_snapshot)
        self.assertIs(e.rate_missing, True)

    def test_non_billable_is_not_flagged(self):
        self.card.delete()
        e = self._entry(is_billable=False)
        e.refresh_from_db()
        self.assertIs(e.rate_missing, False)
        self.assertEqual(e.included_vs_overage, 'non_billable')

    def test_overage_and_partial(self):
        self._entry(minutes=50)
        partial = self._entry(minutes=20)
        over = self._entry(minutes=15)
        partial.refresh_from_db()
        over.refresh_from_db()
        self.assertEqual(partial.included_vs_overage, 'partial')
        self.assertEqual(over.included_vs_overage, 'overage')

    def test_customer_rate_card_beats_default(self):
        card = RateCard.objects.create(name='Client', client_org=self.client_org)
        RateCardLine.objects.create(rate_card=card, role=self.role, hourly_rate=D('140'))
        e = self._entry()
        e.refresh_from_db()
        self.assertEqual(e.bill_rate_snapshot, D('140'))

    def test_explicit_values_are_kept(self):
        e = self._entry(bill_rate_snapshot=D('90'), rate_type='onsite')
        e.refresh_from_db()
        self.assertEqual((e.bill_rate_snapshot, e.rate_type), (D('90'), 'onsite'))

    def test_legacy_entries_are_not_rated_on_save(self):
        e = self._entry()
        TicketTimeEntry.objects.filter(pk=e.pk).update(
            bill_rate_snapshot=None, cost_rate_snapshot=None, rate_missing=None, rate_card_line=None,
            contract=None, labor_role=None, rate_type='', included_vs_overage='')
        e.refresh_from_db()
        e.notes = 'touched'
        e.save()
        e.refresh_from_db()
        self.assertIsNone(e.rate_missing)
        self.assertIsNone(e.bill_rate_snapshot)
        # Contract hour accounting is unchanged by pricing.
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.hours_used_minutes, 30)
