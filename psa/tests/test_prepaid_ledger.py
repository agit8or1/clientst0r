"""Phase 101.1-101.3: coverage resolver, prepaid-hour ledger, approval-time
consumption.

SQLite note: the test database is SQLite, where SELECT ... FOR UPDATE is a
no-op and threads cannot share the in-memory test database reliably. The
concurrency tests therefore simulate the race: a second worker that read the
entry before the first committed (its "already posted?" check sees nothing)
must still not deduct twice - the unique idempotency keys stop it. On MySQL /
PostgreSQL the account row lock (ledger.lock_account) serializes the workers
before that point; on SQLite the UPDATE in lock_account takes the database
write lock first.
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.forms.models import model_to_dict
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, RoleTemplate
from audit.models import AuditLog
from core.models import Organization
from psa.billing import coverage, ledger, seed
from psa.models import (
    Charge, Contract, Invoice, LedgerImmutable, PrepaidBlock, PrepaidLedgerAccount, PrepaidPosting,
    Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType, TimesheetSubmission,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed

D = Decimal


class _Base(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.msp = Organization.objects.create(name='MSP', slug='pl-msp')
        self.cust = Organization.objects.create(name='Cust A', slug='pl-cust-a')
        _enable_psa_for(self.cust)
        self.admin = User.objects.create_superuser('pl_admin', 'a@x.test', 'pw-pl-123')
        self.tech = User.objects.create_user('pl_tech', 't@x.test', 'pw')
        self.ticket = self._ticket(self.cust)
        self.today = timezone.localdate()

    def _ticket(self, org):
        return Ticket.objects.create(
            organization=org, subject='Fix it', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.first())

    def _contract(self, **kw):
        d = dict(organization=self.msp, client_org=self.cust, name='Block 10h', contract_type='block_hours',
                 status='active', start_date=self.today - timedelta(days=30),
                 end_date=self.today + timedelta(days=300), total_hours=D('10'),
                 hourly_rate=D('100'), overage_rate=D('150'))
        d.update(kw)
        return Contract.objects.create(**d)

    def _entry(self, minutes, *, days_ago=0, ticket=None, billable=True, role_code=''):
        start = timezone.now() - timedelta(days=days_ago, minutes=minutes)
        return TicketTimeEntry.objects.create(
            ticket=ticket or self.ticket, user=self.tech, started_at=start,
            ended_at=start + timedelta(minutes=minutes), duration_minutes=minutes,
            is_billable=billable, role_code=role_code)

    def _submit(self, *entries):
        sub = TimesheetSubmission.objects.create(
            user=self.tech, period_start=self.today - timedelta(days=400),
            period_end=self.today + timedelta(days=1),
            revision=TimesheetSubmission.objects.count() + 1, status='pending')
        TicketTimeEntry.objects.filter(pk__in=[e.pk for e in entries]).update(submission=sub)
        return sub

    def _approve(self, *entries):
        sub = self._submit(*entries)
        sub.approve(user=self.admin)
        return sub

    def _remaining(self, contract):
        contract = Contract.objects.get(pk=contract.pk)
        return ledger.summary(contract).remaining_hours

    def _active(self, entry, kind='consumption'):
        return PrepaidPosting.objects.filter(time_entry_ref=entry.pk, kind=kind, reversed_by__isnull=True)

    def _sum(self, qs):
        return sum((p.hours for p in qs), D('0'))


class ApprovalConsumptionTests(_Base):

    def test_contract_save_opens_ledger_with_purchase(self):
        c = self._contract()
        acc = PrepaidLedgerAccount.objects.get(contract=c)
        self.assertEqual(acc.mode, 'window')
        block = PrepaidBlock.objects.get(contract=c)
        self.assertEqual(block.kind, 'allowance')
        self.assertEqual(self._sum(block.postings.filter(kind='purchase')), D('10'))
        self.assertEqual(self._remaining(c), D('10.00'))

    def test_draft_pending_and_rejected_time_consume_nothing(self):
        c = self._contract()
        e = self._entry(120)
        self.assertEqual(self._remaining(c), D('10.00'))
        sub = self._submit(e)
        self.assertEqual(self._remaining(c), D('10.00'))
        sub.reject(user=self.admin)
        self.assertEqual(self._remaining(c), D('10.00'))
        self.assertFalse(PrepaidPosting.objects.filter(kind='consumption').exists())
        # The old counter (still read by invoicing until 101.4) is unchanged.
        self.assertEqual(Contract.objects.get(pk=c.pk).hours_used_minutes, 120)

    def test_approval_deducts_block_hours(self):
        c = self._contract()
        e = self._entry(120)
        self._approve(e)
        self.assertEqual(self._remaining(c), D('8.00'))
        e.refresh_from_db()
        self.assertEqual(e.billing_contract_id, c.pk)
        self.assertEqual(e.billing_resolution, 'prepaid')
        self.assertEqual(self._sum(self._active(e)), D('-2'))
        self.assertTrue(AuditLog.objects.filter(object_type='psa.PrepaidPosting',
                                                extra_data__kind='consumption').exists())

    def test_partial_coverage_splits_into_block_and_overage(self):
        c = self._contract(total_hours=D('1'))
        e = self._entry(180)
        res = coverage.resolve(e)
        self.assertEqual((res.status, res.treatment), ('resolved', 'prepaid'))
        self.assertEqual(res.prepaid_hours, D('1'))
        self.assertEqual(res.chargeable_hours, D('2'))
        self.assertEqual(res.chargeable_amount, D('300.00'))
        self._approve(e)
        self.assertEqual(self._sum(self._active(e)), D('-1'))
        self.assertEqual(self._sum(self._active(e, 'overage')), D('2'))
        e.refresh_from_db()
        self.assertEqual(e.billing_resolution, 'partial')
        self.assertEqual(self._remaining(c), D('0.00'))
        self.assertTrue(ledger.summary(c).depleted)

    def test_unlimited_coverage_consumes_nothing_and_charges_nothing(self):
        c = self._contract(contract_type='managed_services', total_hours=D('0'))
        e = self._entry(240)
        res = coverage.resolve(e)
        self.assertEqual(res.treatment, 'covered')
        self.assertEqual(res.chargeable_amount, D('0'))
        self.assertEqual(res.covered_hours, D('4'))
        self._approve(e)
        self.assertFalse(PrepaidPosting.objects.exists())
        self.assertFalse(PrepaidLedgerAccount.objects.filter(contract=c).exists())
        e.refresh_from_db()
        self.assertEqual(e.billing_resolution, 'covered')

    def test_non_billable_time_consumes_nothing(self):
        self._contract()
        e = self._entry(60, billable=False)
        self._approve(e)
        self.assertFalse(PrepaidPosting.objects.filter(kind='consumption').exists())
        e.refresh_from_db()
        self.assertEqual(e.billing_resolution, 'non_billable')

    def test_release_after_approval_reverses_exactly(self):
        c = self._contract(total_hours=D('1'))
        e = self._entry(100)
        self._approve(e)
        consumed = list(self._active(e)) + list(self._active(e, 'overage'))
        self.assertEqual(len(consumed), 2)
        ledger.release_entry(e, actor=self.admin, reason='Reopened')
        for p in consumed:
            rev = PrepaidPosting.objects.get(reverses=p)
            self.assertEqual(rev.hours, -p.hours)
            self.assertEqual(rev.block_id, p.block_id)
        self.assertEqual(self._remaining(c), D('1.00'))
        self.assertFalse(self._active(e).exists())
        # Releasing again posts nothing more.
        n = PrepaidPosting.objects.count()
        self.assertEqual(ledger.release_entry(e, actor=self.admin), 0)
        self.assertEqual(PrepaidPosting.objects.count(), n)
        # Immutable: the reversal is a new row, the consumption row is untouched.
        with self.assertRaises(LedgerImmutable):
            consumed[0].save()
        with self.assertRaises(LedgerImmutable):
            consumed[0].delete()

    def test_deleting_approved_entry_gives_hours_back(self):
        c = self._contract()
        e = self._entry(90)
        self._approve(e)
        self.assertEqual(self._remaining(c), D('8.50'))
        pk = e.pk
        e.delete()
        self.assertEqual(self._remaining(c), D('10.00'))
        self.assertTrue(PrepaidPosting.objects.filter(time_entry_ref=pk, kind='reversal').exists())

    def test_change_after_approval_reallocates(self):
        c = self._contract()
        e = self._entry(60)
        self._approve(e)
        e = TicketTimeEntry.objects.get(pk=e.pk)
        e.duration_minutes = 90
        e.save(_force_unlock=True, _audit_user=self.admin, _audit_note='typo')
        self.assertEqual(self._sum(self._active(e)), D('-1.5'))
        self.assertEqual(self._remaining(c), D('8.50'))

    def test_returned_entry_releases(self):
        c = self._contract()
        e1, e2 = self._entry(60), self._entry(30)
        sub = self._submit(e1, e2)
        self.assertEqual(sub.decide_with_returns({e2.pk: 'wrong ticket'}, user=self.admin), 'approved')
        self.assertEqual(self._remaining(c), D('9.00'))


class IdempotencyAndConcurrencyTests(_Base):

    def test_retried_posting_is_idempotent(self):
        c = self._contract()
        e = self._entry(60)
        sub = self._approve(e)
        n = PrepaidPosting.objects.count()
        self.assertEqual(ledger.post_entry(e, actor=self.admin), 'unchanged')
        sub.approve(user=self.admin)  # double click / retried request
        self.assertEqual(PrepaidPosting.objects.count(), n)
        self.assertEqual(self._remaining(c), D('9.00'))

    def test_concurrent_worker_cannot_deduct_twice(self):
        c = self._contract()
        e = self._entry(60)
        self._approve(e)
        n = PrepaidPosting.objects.count()
        # A second worker that read the entry before the first committed: it
        # sees no postings, plans the same allocation and hits the unique keys.
        with mock.patch.object(ledger, 'active_entry_postings', return_value=[]):
            self.assertEqual(ledger.post_entry(e, actor=self.admin), 'unchanged')
        self.assertEqual(PrepaidPosting.objects.count(), n)
        self.assertEqual(self._remaining(c), D('9.00'))

    def test_every_write_takes_the_account_lock(self):
        c = self._contract()
        before = PrepaidLedgerAccount.objects.get(contract=c).revision
        e = self._entry(30)
        self._approve(e)
        self.assertGreater(PrepaidLedgerAccount.objects.get(contract=c).revision, before)

    def test_two_entries_never_overdraw_the_block(self):
        c = self._contract(total_hours=D('1'))
        e1, e2 = self._entry(45), self._entry(45)
        self._approve(e1, e2)
        consumed = -self._sum(PrepaidPosting.objects.filter(contract=c, kind='consumption'))
        over = self._sum(PrepaidPosting.objects.filter(contract=c, kind='overage'))
        self.assertEqual(consumed, D('1'))
        self.assertEqual(over, D('0.5'))
        self.assertEqual(self._remaining(c), D('0.00'))


class BlocksExpiryRolloverTests(_Base):

    def test_earliest_expiry_block_is_used_first(self):
        c = self._contract()
        block, _p = ledger.purchase_block(c, D('2'), actor=self.admin, reason='INV-1', idempotency_key='k1',
                                          starts_on=self.today - timedelta(days=1),
                                          expires_on=self.today + timedelta(days=20))
        e = self._entry(180)
        self._approve(e)
        rows = {p.block_id: p.hours for p in self._active(e)}
        self.assertEqual(rows[block.pk], D('-2'))
        allowance = PrepaidBlock.objects.get(contract=c, kind='allowance')
        self.assertEqual(rows[allowance.pk], D('-1'))
        self.assertEqual(self._remaining(c), D('9.00'))
        # Recording the same purchase again (retry) adds nothing.
        ledger.purchase_block(c, D('2'), actor=self.admin, reason='INV-1', idempotency_key='k1')
        self.assertEqual(PrepaidBlock.objects.filter(contract=c, kind='purchase').count(), 1)

    def test_rollover_consumed_before_allowance_and_expires(self):
        c = self._contract(rolled_over_minutes=120, rollover_expires_at=self.today + timedelta(days=5))
        roll = PrepaidBlock.objects.get(contract=c, kind='rollover')
        e = self._entry(60)
        self._approve(e)
        self.assertEqual(self._active(e).get().block_id, roll.pk)
        self.assertEqual(self._remaining(c), D('11.00'))
        # Once the rollover date passes, the display drops it at once...
        later = self.today + timedelta(days=6)
        self.assertEqual(ledger.summary(Contract.objects.get(pk=c.pk), as_of=later).remaining_hours, D('10.00'))
        # ...and the expiry posting comes after the grace period, once.
        self.assertEqual(ledger.expire_due(as_of=later), 0)
        far = self.today + timedelta(days=6 + ledger.EXPIRY_GRACE_DAYS)
        self.assertEqual(ledger.expire_due(as_of=far), 1)
        self.assertEqual(ledger.expire_due(as_of=far), 0)
        exp = PrepaidPosting.objects.get(block=roll, kind='expiry')
        self.assertEqual(exp.hours, D('-1'))
        self.assertEqual(ledger.block_balances(c)[roll.pk], D('0'))

    def test_late_approval_uses_block_valid_on_work_date(self):
        c = self._contract(start_date=self.today - timedelta(days=60), end_date=self.today - timedelta(days=5))
        e = self._entry(60, days_ago=10)
        self._approve(e)
        self.assertEqual(self._active(e).count(), 1)
        self.assertEqual(self._remaining(c), D('9.00'))

    def test_retainer_allowance_resets_each_cycle(self):
        start = self.today.replace(day=1) - timedelta(days=1)
        start = start.replace(day=1)  # first day of the previous month
        c = self._contract(contract_type='retainer', total_hours=D('5'), billing_frequency='monthly',
                           start_date=start, end_date=None)
        self.assertEqual(PrepaidLedgerAccount.objects.get(contract=c).mode, 'cycle')
        last_cycle = self._entry(240, days_ago=(self.today - start).days - 1)
        this_cycle = self._entry(60)
        self._approve(last_cycle, this_cycle)
        self.assertEqual(self._remaining(c), D('4.00'))
        cycles = {b.starts_on: ledger.block_balances(c)[b.pk]
                  for b in PrepaidBlock.objects.filter(contract=c, kind='cycle')}
        self.assertEqual(cycles[start], D('1'))
        self.assertEqual(len(cycles), 2)

    def test_allowance_change_on_contract_is_posted(self):
        c = self._contract()
        c.total_hours = D('12')
        c.save()
        block = PrepaidBlock.objects.get(contract=c, kind='allowance')
        self.assertEqual(self._sum(block.postings.filter(kind='purchase')), D('12'))
        self.assertEqual(block.postings.filter(kind='purchase').count(), 2)
        c.save()  # no change, no posting
        self.assertEqual(block.postings.filter(kind='purchase').count(), 2)

    def test_negative_balance_only_when_allowed(self):
        c = self._contract(total_hours=D('1'))
        e = self._entry(120)
        self._approve(e)
        self.assertEqual(self._remaining(c), D('0.00'))
        self.assertEqual(self._sum(self._active(e, 'overage')), D('1'))
        with self.assertRaises(ledger.LedgerError):
            ledger.adjust(c, D('-1'), actor=self.admin, reason='x', idempotency_key='neg1')

        c2 = self._contract(name='Neg OK', total_hours=D('1'), allow_negative_balance=True,
                            client_org=self._other_customer())
        e2 = self._entry(120, ticket=self._ticket(c2.client_org))
        self._approve(e2)
        self.assertEqual(self._remaining(c2), D('-1.00'))
        self.assertFalse(self._active(e2, 'overage').exists())
        self.assertTrue(ledger.summary(c2).negative)

    def _other_customer(self):
        return Organization.objects.create(name='Cust N', slug='pl-cust-n')


class AgreementPrecedenceTests(_Base):

    def test_overlapping_contracts_do_not_double_count(self):
        a = self._contract(name='Block A')
        b = self._contract(name='Block B')
        e = self._entry(60)
        res = coverage.resolve(e)
        self.assertEqual(res.status, 'needs_choice')
        self._approve(e)
        self.assertFalse(PrepaidPosting.objects.filter(kind='consumption').exists())
        e.refresh_from_db()
        self.assertEqual(e.billing_resolution, 'needs_choice')
        self.assertEqual(ledger.choose_agreement(e, b, actor=self.admin), 'posted')
        self.assertEqual(self._remaining(a), D('10.00'))
        self.assertEqual(self._remaining(b), D('9.00'))
        e.refresh_from_db()
        self.assertTrue(e.billing_contract_chosen)
        # Moving it to the other agreement reverses B and consumes A: once.
        ledger.choose_agreement(e, a, actor=self.admin)
        self.assertEqual(self._remaining(a), D('9.00'))
        self.assertEqual(self._remaining(b), D('10.00'))

    def test_highest_priority_wins(self):
        self._contract(name='Low')
        high = self._contract(name='High', billing_priority=5)
        e = self._entry(60)
        res = coverage.resolve(e)
        self.assertEqual((res.status, res.agreement.pk), ('resolved', high.pk))

    def test_consumption_follows_entry_agreement_not_customer_and_date(self):
        a = self._contract(name='Block A', billing_priority=1)
        b = self._contract(name='Block B')
        e = self._entry(60)
        self._approve(e)
        self.assertEqual(self._remaining(a), D('9.00'))
        self.assertEqual(self._remaining(b), D('10.00'))

    def test_role_gates_and_no_agreement(self):
        self._contract(excluded_role_codes=['project'])
        e = self._entry(60, role_code='project')
        res = coverage.resolve(e)
        self.assertEqual((res.status, res.treatment), ('no_agreement', 'chargeable'))
        self.assertEqual(res.invoice_rate, D('0'))

    def test_draft_contract_is_not_a_candidate(self):
        self._contract(status='draft')
        self.assertEqual(coverage.resolve(self._entry(30)).status, 'no_agreement')

    def test_charge_resolves_to_agreement(self):
        c = self._contract()
        ch = Charge.objects.create(organization=self.msp, client_org=self.cust, description='Cable',
                                   amount=D('25'), charge_date=self.today)
        res = coverage.resolve(ch)
        self.assertEqual((res.agreement.pk, res.treatment, res.chargeable_amount), (c.pk, 'chargeable', D('25')))


class AdjustmentPermissionTests(_Base):

    def _tech_with(self, **flags):
        role = RoleTemplate.objects.create(name=f'role-{len(flags)}-{RoleTemplate.objects.count()}', **flags)
        u = User.objects.create_user(f'pl_t{User.objects.count()}', 'x@x.test', 'pw')
        _make_msp_tech(u)
        u.profile.global_role_template = role
        u.profile.save()
        return u

    def test_adjustment_needs_permission_reason_and_is_audited(self):
        c = self._contract()
        viewer = self._tech_with(billing_view_invoices=True)
        with self.assertRaises(PermissionDenied):
            ledger.adjust(c, D('1'), actor=viewer, reason='goodwill', idempotency_key='a1')
        manager = self._tech_with(billing_view_invoices=True, billing_manage_charges=True)
        with self.assertRaises(ledger.LedgerError):
            ledger.adjust(c, D('1'), actor=manager, reason='  ', idempotency_key='a1')
        p = ledger.adjust(c, D('1.5'), actor=manager, reason='goodwill', idempotency_key='a1')
        self.assertEqual((p.kind, p.hours, p.actor_id), ('adjustment', D('1.5'), manager.pk))
        self.assertEqual(ledger.adjust(c, D('1.5'), actor=manager, reason='goodwill', idempotency_key='a1').pk,
                         p.pk)
        self.assertEqual(self._remaining(c), D('11.50'))
        log = AuditLog.objects.get(object_type='psa.PrepaidPosting', object_id=p.pk)
        self.assertEqual(log.user_id, manager.pk)
        self.assertEqual(log.organization_id, self.cust.pk)

    def test_customer_user_cannot_adjust(self):
        c = self._contract()
        role = RoleTemplate.objects.create(name='cust-billing', billing_view_invoices=True,
                                           billing_manage_charges=True)
        u = User.objects.create_user('pl_cust', 'c@x.test', 'pw')
        Membership.objects.create(user=u, organization=self.cust, role_template=role, is_active=True)
        with self.assertRaises(PermissionDenied):
            ledger.adjust(c, D('1'), actor=u, reason='x', idempotency_key='c1')


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LedgerScopingViewTests(_Base):

    def setUp(self):
        super().setUp()
        self.other = Organization.objects.create(name='Cust B', slug='pl-cust-b')
        _enable_psa_for(self.other)
        self.ca = self._contract(name='A block')
        self.cb = self._contract(name='B block', client_org=self.other)
        role = RoleTemplate.objects.create(name='Billing tech', billing_view_invoices=True,
                                           billing_manage_charges=True, tickets_view=True)
        self.restricted = User.objects.create_user('pl_restricted', 'r@x.test', 'pw')
        _make_msp_tech(self.restricted)
        p = self.restricted.profile
        p.global_role_template = role
        p.client_scope = 'selected'
        p.save()
        p.scope_organizations.set([self.cust])

    def test_restricted_tech_sees_and_adjusts_only_in_scope(self):
        c = _login(self.restricted)
        self.assertEqual(c.get(f'/psa/contracts/{self.ca.pk}/ledger/').status_code, 200)
        self.assertEqual(c.get(f'/psa/contracts/{self.cb.pk}/ledger/').status_code, 404)
        r = c.post(f'/psa/contracts/{self.cb.pk}/ledger/adjust/',
                   {'hours': '5', 'reason': 'x', 'form_key': 'k-b'})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(PrepaidPosting.objects.filter(contract=self.cb, kind='adjustment').exists())
        r = c.post(f'/psa/contracts/{self.ca.pk}/ledger/adjust/',
                   {'hours': '2', 'reason': 'goodwill', 'form_key': 'k-a'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._remaining(self.ca), D('12.00'))
        # Same form posted twice (double click): one adjustment.
        c.post(f'/psa/contracts/{self.ca.pk}/ledger/adjust/', {'hours': '2', 'reason': 'goodwill',
                                                                'form_key': 'k-a'})
        self.assertEqual(self._remaining(self.ca), D('12.00'))

    def test_restricted_tech_cannot_choose_agreement_for_other_customer(self):
        e = self._entry(30, ticket=self._ticket(self.other))
        r = _login(self.restricted).post(f'/psa/time/{e.pk}/agreement/', {'contract_id': self.cb.pk})
        self.assertEqual(r.status_code, 404)

    def test_view_only_tech_cannot_adjust(self):
        role = RoleTemplate.objects.create(name='Viewer', billing_view_invoices=True, tickets_view=True)
        u = User.objects.create_user('pl_viewer', 'v@x.test', 'pw')
        _make_msp_tech(u)
        u.profile.global_role_template = role
        u.profile.save()
        c = _login(u)
        resp = c.get(f'/psa/contracts/{self.ca.pk}/ledger/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Post adjustment')
        r = c.post(f'/psa/contracts/{self.ca.pk}/ledger/adjust/', {'hours': '2', 'reason': 'x', 'form_key': 'v'})
        self.assertEqual(r.status_code, 403)

    def test_contract_pages_show_ledger_balance(self):
        e = self._entry(90)
        self._approve(e)
        c = _login(self.admin)
        s = c.session
        s['current_organization_id'] = self.msp.pk
        s.save()
        resp = c.get(f'/psa/contracts/{self.ca.pk}/')
        self.assertContains(resp, '8.50h')
        self.assertContains(resp, 'Prepaid-hour ledger')
        resp = c.get('/psa/contracts/')
        self.assertContains(resp, '8.50 left')


class LowBalanceTests(_Base):

    def test_low_balance_marks_audits_and_warns(self):
        c = self._contract()
        e = self._entry(8 * 60 + 30)
        self._approve(e)
        acc = PrepaidLedgerAccount.objects.get(contract=c)
        self.assertIsNotNone(acc.low_since)
        self.assertTrue(AuditLog.objects.filter(object_type='psa.Contract', object_id=c.pk,
                                                description__startswith='Prepaid balance low').exists())
        from core.system_warnings import collect_system_warnings
        ids = [w['id'] for w in collect_system_warnings(min_severity='info')]
        self.assertIn(f'prepaid_low:{c.pk}:{acc.low_since:%Y%m%d}', ids)
        ledger.release_entry(e, actor=self.admin)
        self.assertIsNone(PrepaidLedgerAccount.objects.get(contract=c).low_since)


class UpgradeSeedingTests(_Base):
    """Existing contracts and invoices are unchanged when the ledger opens."""

    def _pre_upgrade(self):
        with ledger.suspended():
            self.block = self._contract(total_hours=D('3'))
            self.ret = self._contract(name='Retainer', contract_type='retainer', total_hours=D('2'),
                                      billing_frequency='none', client_org=self._org('pl-ret'))
            self.e_draft = self._entry(30, days_ago=4)  # never approved
            self.e1 = self._entry(90, days_ago=3)
            self.e2 = self._entry(150, days_ago=2)   # 1h fits, 1.5h overage under the old rules
        TimesheetSubmission.objects.filter(pk=self._submit(self.e1, self.e2).pk).update(status='approved')

    def _org(self, slug):
        return Organization.objects.create(name=slug, slug=slug)

    def test_seed_keeps_contracts_and_remaining_hours(self):
        self._pre_upgrade()
        contract = Contract.objects.get(pk=self.block.pk)
        before_fields = model_to_dict(contract)
        legacy = seed.legacy_remaining(contract, self.today)
        # What "Invoice this ticket" billed before the upgrade (old counter).
        from psa.billing.legacy import legacy_ticket_billing_lines
        lines_before, info_before = legacy_ticket_billing_lines(self.ticket, contract)

        from importlib import import_module
        from django.apps import apps as live_apps
        import_module('psa.migrations.0092_prepaid_ledger_opening').forwards(live_apps, None)

        contract = Contract.objects.get(pk=self.block.pk)
        self.assertEqual(model_to_dict(contract), before_fields)
        self.assertEqual(ledger.summary(contract).remaining_hours, legacy)
        self.assertEqual(ledger.summary(contract).used_hours, D('3.00'))
        self.assertTrue(PrepaidPosting.objects.filter(status='migrated').exists())
        # Phase 101.4: the ledger opening balance bills the pre-upgrade
        # time exactly as the old counter did.
        lines_after, info_after = self.ticket.uninvoiced_billing_lines(contract)
        self.assertEqual(lines_after, lines_before)
        self.assertEqual((info_after['covered_minutes'], info_after['overage_minutes']),
                         (info_before['covered_minutes'], info_before['overage_minutes']))

        # Approving pre-upgrade time again changes nothing.
        n = PrepaidPosting.objects.count()
        self.assertEqual(ledger.post_entry(self.e1), 'unchanged')
        self.assertEqual(PrepaidPosting.objects.count(), n)
        # Rejecting unapproved pre-upgrade time gives its hours back.
        self.assertEqual(self._sum(self._active(self.e_draft)), D('-0.5'))
        self._submit(self.e_draft).reject(user=self.admin)
        self.assertFalse(self._active(self.e_draft).exists())
        self.assertEqual(ledger.summary(Contract.objects.get(pk=contract.pk)).remaining_hours, D('0.50'))

        # Seeding is idempotent.
        seed.seed_all()
        self.assertEqual(PrepaidLedgerAccount.objects.filter(contract=contract).count(), 1)
        self.assertEqual(PrepaidPosting.objects.filter(status='migrated', kind='purchase',
                                                       contract=contract).count(), 1)

    def test_existing_draft_invoice_totals_unchanged(self):
        self._pre_upgrade()
        contract = Contract.objects.get(pk=self.block.pk)
        from psa.billing.legacy import legacy_ticket_billing_lines
        lines, _ = legacy_ticket_billing_lines(self.ticket, contract)  # drafted before the upgrade
        from psa.models import InvoiceLineItem
        draft = Invoice.objects.create(organization=self.cust, client_org=self.cust, title='Draft',
                                       invoice_date=self.today, source_contract=contract)
        for ln in lines:
            InvoiceLineItem.objects.create(invoice=draft, **ln)
        draft.recompute_totals()
        before = (draft.subtotal, draft.tax_amount if hasattr(draft, 'tax_amount') else None, draft.total,
                  list(draft.line_items.values_list('description', 'quantity', 'unit_price')))
        self.assertGreater(draft.total, 0)  # the overage is billed
        seed.seed_all()
        self._approve(self._entry(60))  # post-upgrade activity does not reprice it
        draft = Invoice.objects.get(pk=draft.pk)
        draft.recompute_totals()
        after = (draft.subtotal, draft.tax_amount if hasattr(draft, 'tax_amount') else None, draft.total,
                 list(draft.line_items.values_list('description', 'quantity', 'unit_price')))
        self.assertEqual(after, before)

    def test_invoice_totals_unchanged_by_approval(self):
        self._pre_upgrade()
        seed.seed_all()
        contract = Contract.objects.get(pk=self.block.pk)
        lines_before, _ = self.ticket.uninvoiced_billing_lines(contract)
        e3 = self._entry(60)
        lines_with_draft, _ = self.ticket.uninvoiced_billing_lines(Contract.objects.get(pk=contract.pk))
        # Phase 101.4: unapproved prepaid time is not invoiced yet.
        self.assertEqual(lines_with_draft, lines_before)
        self._approve(e3)
        lines_after, _ = self.ticket.uninvoiced_billing_lines(Contract.objects.get(pk=contract.pk))
        new = [ln for ln in lines_after if ln['source_id'] == str(e3.pk)]
        self.assertEqual([(ln['quantity'], ln['unit_price']) for ln in new], [(D('1.00'), D('150.00'))])
        self.assertEqual([ln for ln in lines_after if ln['source_id'] != str(e3.pk)], lines_before)

    def test_reconcile_dry_run_reports_and_writes_nothing(self):
        self._pre_upgrade()
        seed.seed_all()
        n = PrepaidPosting.objects.count()
        out = io.StringIO()
        call_command('prepaid_ledger_reconcile', '--dry-run', stdout=out)
        text = out.getvalue()
        self.assertIn('remaining before (old counter) 0.00  after (ledger) 0.00', text)
        self.assertIn('unapproved', text)
        self.assertIn('dry run', text)
        self.assertEqual(PrepaidPosting.objects.count(), n)

    def test_reconcile_opens_missing_ledger(self):
        with ledger.suspended():
            c = self._contract()
        e = self._entry(60)
        self._approve(e)  # contract has no ledger yet: opened on approval
        self.assertEqual(self._remaining(c), D('9.00'))
        with ledger.suspended():
            c2 = self._contract(name='No ledger', client_org=self._org('pl-nl'))
        out = io.StringIO()
        call_command('prepaid_ledger_reconcile', stdout=out)
        self.assertIn('NO LEDGER', out.getvalue())
        self.assertTrue(PrepaidLedgerAccount.objects.filter(contract=c2).exists())
