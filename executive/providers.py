"""The Business Overview metrics, one provider per card.

Every provider reads an existing source and reuses the calculation the
reports already make (one source of truth):

  reports.financials  billed / collected / recognized revenue, direct cost,
                    gross profit and margin — the one set of definitions
  reports.queries   recurring_revenue / mrr_trend (contracted MRR, ARR), contract_churn,
                    _contracts_running_on (active customers), revenue_by_client
                    and revenue_by_service_line (billed revenue),
                    profitability_by_client + reports.costing.summarize (margin),
                    contracts_expiring, unbilled_time, utilization_summary,
                    sla_trend_by_priority
  psa.models        get_psa_balance (accounts receivable, as the aging report)
  payments          payment attempts and disputes
  security_alerts   alerts and incidents

Each carries the source's completeness: a figure the source cannot know is
reported as unknown and incomplete, never as zero or healthy. Apps that are
not installed (backup monitoring, licensing) are detected through the app
registry and reported as "not configured".

Every collect() receives the viewer's customer ids (their client scope, the
same rule as the profitability reports) and passes them to the source as
`organization=`, so aggregates only add up customers the viewer may see.
The value and the drill-down rows always come from the same collect() call
(executive.metrics). docs/plans/EXECUTIVE_METRICS.md lists every metric.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.db.models import F, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from reports import financials, queries
from reports.costing import summarize
from reports.financials import attributed_invoice, invoice_revenue

from .metrics import (
    ALL_FILTERS, F_CUSTOMER, F_DATE, F_LOCATION, F_SERVICE_LINE, Collected, Column,
    Forbidden, MetricProvider, NotConfigured, limit_customer_or_owner, limit_to, months_between,
)

ZERO = Decimal('0')
# Issued invoices, the set billed revenue counts (reports.financials).
REVENUE_STATUSES = financials.ISSUED_STATUSES
PROFITABILITY_LABEL = 'Operational estimate, not accounting results'


# -- shared helpers ------------------------------------------------------------

def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _psa_off():
    from core.models import SystemSetting
    if not SystemSetting.get_settings().psa_enabled:
        return 'The PSA module is switched off (Administration → Modules).'
    return None


def _org_arg(ids):
    """The `organization=` argument the reports.queries functions take."""
    return None if ids is None else sorted(ids)


def _money(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'))


class PsaProvider(MetricProvider):
    def availability(self):
        return _psa_off()


# -- revenue -------------------------------------------------------------------

class MrrArr(PsaProvider):
    key = 'mrr_arr'
    title = 'Contracted MRR & ARR'
    section = 'Revenue'
    icon = 'fa-arrows-rotate'
    unit = 'currency'
    chart = 'line'
    order = 10
    source = ('Contracted, not billed: billing contracts\' recurring amount normalized to a month '
              '(reports.queries.recurring_revenue, mrr_trend)')
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('label', 'Contract'), Column('client_name', 'Customer'),
               Column('frequency', 'Billing frequency'), Column('mrr', 'MRR', 'currency'),
               Column('next_billing_date', 'Next billing', 'date'), Column('end_date', 'Ends', 'date'))

    def as_of(self, filters):
        return filters.end

    def collect(self, scope, filters):
        org = _org_arg(scope.customer_ids(filters))
        rr = queries.recurring_revenue(filters.end, org)
        trend = queries.mrr_trend(12, filters.end, org)
        rows = [dict(c, label=c.get('contract_name', ''), url=_url('psa:contract_detail', c['contract_id']))
                for c in rr['contracts']]
        reasons, notes = [], []
        if rr.get('contracts_unknown_end'):
            reasons.append(f"{rr['contracts_unknown_end']} stopped contracts have no end date")
        incomplete_months = [p['month'] for p in trend['points'] if not p.get('is_complete', True)]
        if incomplete_months and not reasons:
            reasons.append(f'{len(incomplete_months)} months include stopped contracts with no end date')
        if rr.get('contracts_without_amount'):
            notes.append(f"{rr['contracts_without_amount']} running contracts have no recurring amount "
                         'and add nothing to MRR.')
        growth = trend.get('mom_growth_pct')
        return Collected(
            value=rr['mrr'], rows=rows,
            trend=[{'label': p['month'], 'value': p['mrr']} for p in trend['points']],
            breakdown=[{'label': 'ARR', 'value': rr['arr'], 'unit': 'currency'},
                       {'label': 'Month-over-month', 'value': growth, 'unit': 'percent'},
                       {'label': 'Contracts', 'value': rr['contract_count']}],
            is_complete=bool(rr['is_complete']) and bool(trend['is_complete']),
            unknown_reason='; '.join(reasons), notes=notes,
        )


class RevenueTrend(PsaProvider):
    key = 'revenue_trend'
    title = 'Billed revenue'
    section = 'Revenue'
    icon = 'fa-file-invoice-dollar'
    unit = 'currency'
    chart = 'bar'
    order = 20
    source = ('Billed revenue: issued invoices (sent, partially paid, paid, overdue) by invoice date, '
              'excluding tax, net of credit notes (reports.financials)')
    supported_filters = (F_DATE, F_CUSTOMER, F_SERVICE_LINE)
    columns = (Column('label', 'Invoice'), Column('client_name', 'Customer'),
               Column('invoice_date', 'Date', 'date'), Column('status', 'Status'),
               Column('service_line', 'Service line'), Column('revenue', 'Billed (excl. tax)', 'currency'),
               Column('total', 'Total incl. tax', 'currency'))

    @staticmethod
    def _total(start, end, org, service_line):
        if service_line:
            lines = queries.revenue_by_service_line(start, end, org)
            return _money(sum(r['revenue'] for r in lines['rows'] if r['key'] == service_line))
        return _money(sum(r['invoiced'] for r in queries.revenue_by_client(start, end, org)))

    def collect(self, scope, filters):
        from psa.models import Contract, Invoice
        ids = scope.customer_ids(filters)
        org = _org_arg(ids)
        total = self._total(filters.start, filters.end, org, filters.service_line)
        trend = [{'label': label, 'value': self._total(m_start, m_end, org, filters.service_line)}
                 for label, m_start, m_end in months_between(filters.start, filters.end)]
        # The records: the invoices revenue_by_client sums (same statuses, dates
        # and customer field), narrowed like revenue_by_service_line for a line.
        qs = Invoice.objects.filter(invoice_date__gte=filters.start, invoice_date__lte=filters.end,
                                    status__in=REVENUE_STATUSES)
        qs = limit_to(qs, 'client_org', ids)
        if filters.service_line:
            # A credit memo counts under the service line of what it credits.
            qs = qs.filter(Q(source_contract__contract_type=filters.service_line)
                           | Q(is_credit_memo=True,
                               credits_invoice__source_contract__contract_type=filters.service_line))
        labels = dict(Contract.CONTRACT_TYPES)
        rows = []
        for inv in qs.select_related('client_org', 'source_contract',
                                     'credits_invoice__source_contract').order_by('invoice_date', 'pk'):
            src = attributed_invoice(inv)
            sl = src.source_contract.contract_type if src.source_contract_id else ''
            rows.append({'id': inv.pk, 'label': inv.invoice_number or f'#{inv.pk}',
                         'client_name': inv.client_org.name, 'invoice_date': inv.invoice_date,
                         'status': inv.status, 'service_line': labels.get(sl, ''),
                         'revenue': invoice_revenue(inv),
                         'total': _money(inv.total), 'url': _url('psa:invoice_detail', inv.pk)})
        notes, breakdown = [], []
        if not filters.service_line:
            lines = queries.revenue_by_service_line(filters.start, filters.end, org)
            breakdown = [{'label': r['label'], 'value': r['revenue'], 'unit': 'currency'}
                         for r in lines['rows']]
            if lines['unattributed']:
                notes.append(f"{lines['unattributed']:,.2f} of revenue is not attributed to a service line.")
        if not filters.service_line:
            collected = financials.collected_revenue(filters.start, filters.end, org)
            recognized = financials.recognized_revenue(filters.start, filters.end, org)
            breakdown += [{'label': 'Collected (excl. tax)', 'value': _money(collected.amount),
                           'unit': 'currency', 'group': 'Other definitions'},
                          {'label': 'Recognized', 'value': _money(recognized.amount),
                           'unit': 'currency', 'group': 'Other definitions'}]
            notes += collected.reasons + recognized.notes
        return Collected(value=total, rows=rows, trend=trend, breakdown=breakdown, notes=notes,
                         secondary=f'{len(rows)} invoices')


class _Profitability(PsaProvider):
    """Shared source for the margin cards: reports.queries.profitability_by_client
    (each entry costed at its technician's rate on the day; hours without a
    rate are unknown) summed with reports.costing.summarize, exactly as the
    profitability report does. Margin is unknown while any hour lacks a rate."""
    section = 'Profitability'
    label = PROFITABILITY_LABEL
    permission = 'view_profitability'
    source = ('Billed revenue (excluding tax, net of credit notes) less direct cost: labour at each '
              'technician\'s cost rate, ticket items at unit cost and ticket expenses (reports.financials)')
    supported_filters = (F_DATE, F_CUSTOMER)

    def _rows(self, scope, filters, start=None, end=None):
        return queries.profitability_by_client(start or filters.start, end or filters.end,
                                               organization=_org_arg(scope.customer_ids(filters)))

    @staticmethod
    def _rows_out(rows):
        return [dict(r, label=r.get('client_name', ''), url=_url('accounts:organization_detail', r['client_id']))
                for r in rows]


def _unknown_reason(summary):
    """The 'Partial — …' reason for a margin card (reports.costing.summarize)."""
    reasons = summary.get('partial_reasons') or ()
    return ('Partial — ' + '; '.join(reasons)) if reasons else ''


class GrossMargin(_Profitability):
    key = 'gross_margin'
    title = 'Gross margin'
    icon = 'fa-scale-balanced'
    unit = 'percent'
    chart = 'line'
    order = 30
    columns = (Column('label', 'Customer'), Column('revenue', 'Billed revenue', 'currency'),
               Column('cost', 'Direct cost (known)', 'currency'), Column('margin', 'Gross profit', 'currency'),
               Column('margin_pct', 'Margin %', 'percent'),
               Column('unknown_cost_hours', 'Hours without cost rate', 'hours'))

    def collect(self, scope, filters):
        rows = self._rows(scope, filters)
        s = summarize(rows)
        trend = []
        for label, m_start, m_end in months_between(filters.start, filters.end):
            trend.append({'label': label,
                          'value': summarize(self._rows(scope, filters, m_start, m_end))['blended_margin_pct']})
        return Collected(
            value=s['blended_margin_pct'], rows=self._rows_out(rows), trend=trend,
            breakdown=[{'label': 'Billed revenue', 'value': s['total_revenue'], 'unit': 'currency'},
                       {'label': 'Direct cost (known)', 'value': s['total_cost'], 'unit': 'currency'},
                       {'label': 'Gross profit', 'value': s['total_margin'], 'unit': 'currency'}],
            is_complete=s['is_complete'], unknown_reason=_unknown_reason(s),
            secondary='' if s['total_revenue'] else 'No billed revenue in this period.',
        )


class CustomerProfitability(_Profitability):
    key = 'customer_profitability'
    title = 'Customer profitability'
    icon = 'fa-ranking-star'
    unit = 'count'
    chart = 'none'
    order = 40
    columns = GrossMargin.columns

    def collect(self, scope, filters):
        rows = self._rows(scope, filters)
        s = summarize(rows)
        ranked = sorted((r for r in rows if r.get('margin') is not None), key=lambda r: r['margin'], reverse=True)
        top = ranked[:5]
        bottom = list(reversed(ranked[5:][-5:]))
        breakdown = [{'label': r['client_name'], 'value': r['margin'], 'unit': 'currency', 'group': 'Most profitable'}
                     for r in top]
        breakdown += [{'label': r['client_name'], 'value': r['margin'], 'unit': 'currency',
                       'group': 'Least profitable'} for r in bottom]
        unranked = len(rows) - len(ranked)
        reason = _unknown_reason(s)
        if unranked:
            reason = (reason + '; ' if reason else '') + f'{unranked} customers have an unknown margin'
        ordered = ranked + [r for r in rows if r.get('margin') is None]
        return Collected(value=len(rows), rows=self._rows_out(ordered), breakdown=breakdown,
                         is_complete=not unranked and s['is_complete'], unknown_reason=reason,
                         secondary=f'{len(ranked)} customers ranked by margin')


# -- customers & contracts -----------------------------------------------------

class CustomerGrowth(PsaProvider):
    key = 'customer_growth'
    title = 'Customers: growth & churn'
    section = 'Customers'
    icon = 'fa-users'
    unit = 'count'
    chart = 'line'
    order = 50
    source = ('Customers with a running billing contract (reports.queries._contracts_running_on); '
              'churn from reports.queries.contract_churn')
    supported_filters = (F_DATE, F_CUSTOMER, F_SERVICE_LINE)
    columns = (Column('label', 'Customer'), Column('contracts', 'Running contracts', 'number'),
               Column('first_start', 'Customer since', 'date'), Column('new_in_period', 'New in period', 'bool'))

    def as_of(self, filters):
        return filters.end

    @staticmethod
    def _running(on_date, org, service_line):
        running, undated = queries._contracts_running_on(on_date, org)
        if service_line:
            running = [c for c in running if c.contract_type == service_line]
            undated = [c for c in undated if c.contract_type == service_line]
        return running, undated

    def collect(self, scope, filters):
        from psa.models import Contract
        ids = scope.customer_ids(filters)
        org = _org_arg(ids)
        running, undated = self._running(filters.end, org, filters.service_line)
        customers = OrderedDict()
        for c in sorted(running, key=lambda c: c.client_org.name.lower()):
            customers.setdefault(c.client_org_id, {'org': c.client_org, 'contracts': 0})
            customers[c.client_org_id]['contracts'] += 1
        first = {}
        first_qs = limit_to(Contract.objects.exclude(status='draft'), 'client_org', ids)
        if filters.service_line:
            first_qs = first_qs.filter(contract_type=filters.service_line)
        for org_id, start in first_qs.values_list('client_org_id', 'start_date'):
            if org_id not in first or start < first[org_id]:
                first[org_id] = start
        new_ids = {o for o, s in first.items() if filters.start <= s <= filters.end}
        rows = [{'id': oid, 'label': v['org'].name, 'contracts': v['contracts'],
                 'first_start': first.get(oid), 'new_in_period': oid in new_ids,
                 'url': _url('accounts:organization_detail', oid)} for oid, v in customers.items()]
        trend = []
        for label, _s, m_end in months_between(filters.start, filters.end):
            r, _u = self._running(m_end, org, filters.service_line)
            trend.append({'label': label, 'value': len({c.client_org_id for c in r})})
        churn = queries.contract_churn(filters.start, filters.end, org)
        reasons, notes = [], []
        if undated:
            reasons.append(f'{len(undated)} stopped contracts have no end date')
        if not churn['is_complete']:
            reasons.append(f"{churn['undated_cancellations']} cancellations have no end date")
        if filters.service_line:
            notes.append('Churn figures cover every service line.')
        return Collected(
            value=len(rows), rows=rows, trend=trend,
            breakdown=[{'label': 'New customers in period', 'value': len(new_ids)},
                       {'label': 'Churned contracts', 'value': churn['churned_count']},
                       {'label': 'Churned MRR', 'value': churn['churned_mrr'], 'unit': 'currency'},
                       {'label': 'Revenue churn', 'value': churn['churn_rate_pct'], 'unit': 'percent'}],
            is_complete=not reasons, unknown_reason='; '.join(reasons), notes=notes)


class ContractRenewals(PsaProvider):
    key = 'contract_renewals'
    title = 'Contract renewals (90 days)'
    section = 'Customers'
    icon = 'fa-file-contract'
    unit = 'count'
    chart = 'bar'
    order = 60
    point_in_time = True
    source = 'Active billing contracts by end date (reports.queries.contracts_expiring)'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Contract'), Column('client_name', 'Customer'),
               Column('end_date', 'Ends', 'date'), Column('days_left', 'Days left', 'number'),
               Column('auto_renew', 'Auto-renews', 'bool'), Column('mrr', 'MRR at stake', 'currency'))

    def collect(self, scope, filters):
        exp = queries.contracts_expiring(timezone.localdate(), _org_arg(scope.customer_ids(filters)))
        w = exp['windows']
        rows = [dict(c, id=c['contract_id'], label=c['contract_name'], url=_url('psa:contract_detail', c['contract_id']))
                for c in w[90]['contracts']]
        breakdown = [{'label': f'{d} days', 'value': w[d]['count']} for d in (30, 60, 90)]
        breakdown.append({'label': 'MRR at stake (90 days)', 'unit': 'currency', 'value': w[90]['mrr']})
        without = exp['contracts_without_amount']
        return Collected(value=w[90]['count'], rows=rows, breakdown=breakdown,
                         is_complete=exp['is_complete'],
                         unknown_reason=(f'{without} contracts have no recurring amount; MRR at stake '
                                         'leaves them out' if without else ''),
                         secondary=f"{w[90]['auto_renew']} set to auto-renew")


class OutstandingQuotes(PsaProvider):
    key = 'outstanding_quotes'
    title = 'Outstanding quotes'
    section = 'Sales'
    icon = 'fa-file-signature'
    unit = 'currency'
    chart = 'bar'
    order = 70
    point_in_time = True
    source = 'Quotes sent and awaiting the customer\'s decision'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Quote'), Column('client_name', 'Customer'),
               Column('sent', 'Sent', 'date'), Column('age_days', 'Age (days)', 'number'),
               Column('valid_until', 'Valid until', 'date'), Column('total', 'Total', 'currency'))
    BUCKETS = ((7, '0–7 days'), (30, '8–30 days'), (60, '31–60 days'), (None, 'Over 60 days'))

    def collect(self, scope, filters):
        from psa.models import Quote
        ids = scope.customer_ids(filters)
        qs = limit_to(Quote.objects.filter(status='sent'), 'client_org', ids)
        now = timezone.now()
        today = timezone.localdate()
        rows = []
        buckets = OrderedDict((label, {'count': 0, 'value': ZERO}) for _d, label in self.BUCKETS)
        for q in qs.select_related('client_org').order_by('sent_at', 'created_at', 'pk'):
            sent = q.sent_at or q.created_at
            age = max((now - sent).days, 0) if sent else 0
            label = next(lbl for limit, lbl in self.BUCKETS if limit is None or age <= limit)
            total = _money(q.total)
            buckets[label]['count'] += 1
            buckets[label]['value'] += total
            rows.append({'id': q.pk, 'label': q.quote_number or f'#{q.pk}', 'client_name': q.client_org.name,
                         'sent': sent, 'age_days': age, 'valid_until': q.valid_until,
                         'lapsed': bool(q.valid_until and q.valid_until < today), 'total': total,
                         'bucket': label, 'url': _url('psa:quote_detail', q.pk)})
        lapsed = sum(1 for r in rows if r['lapsed'])
        return Collected(
            value=sum((r['total'] for r in rows), ZERO), rows=rows,
            breakdown=[{'label': k, 'value': v['value'], 'unit': 'currency', 'count': v['count']}
                       for k, v in buckets.items()],
            secondary=f'{len(rows)} quotes' + (f', {lapsed} past their valid-until date' if lapsed else ''),
        )


# -- billing -------------------------------------------------------------------

class UnbilledWork(PsaProvider):
    key = 'unbilled_work'
    title = 'Unbilled work'
    section = 'Billing'
    icon = 'fa-hourglass-half'
    unit = 'currency'
    chart = 'bar'
    order = 80
    source = ('Billable, finished time entries on no live invoice, at each entry\'s bill rate '
              '(reports.queries.unbilled_time)')
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('label', 'Customer'), Column('entries', 'Time entries', 'number'),
               Column('hours', 'Hours', 'hours'), Column('amount', 'Value (priced entries)', 'currency'),
               Column('hours_without_rate', 'Hours without a bill rate', 'hours'))

    def collect(self, scope, filters):
        u = queries.unbilled_time(filters.start, filters.end, _org_arg(scope.customer_ids(filters)))
        rows = [dict(r, id=r['client_id'], label=r['client_name'],
                     url=_url('accounts:organization_detail', r['client_id'])) for r in u['rows']]
        reason = ''
        if u['entries_without_rate']:
            reason = (f"{u['entries_without_rate']} entries ({u['hours_without_rate']:g} hours) "
                      'without a bill rate')
        # Nothing priced: the value is unknown, not zero.
        priced = u['entries'] - u['entries_without_rate']
        return Collected(
            value=u['amount'] if priced or not u['entries'] else None, rows=rows,
            breakdown=[{'label': r['client_name'], 'value': r['hours'], 'unit': 'hours'} for r in u['rows'][:8]],
            is_complete=u['is_complete'], unknown_reason=reason,
            secondary=f"{u['hours']:g} hours in {u['entries']} time entries")


class AccountsReceivable(PsaProvider):
    key = 'accounts_receivable'
    title = 'Accounts receivable'
    section = 'Billing'
    icon = 'fa-money-check-dollar'
    unit = 'currency'
    chart = 'bar'
    order = 90
    point_in_time = True
    permission = 'billing_view_aging'
    source = 'Invoice balances and aging per customer (psa.get_psa_balance, as the aging report)'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Invoice'), Column('client_name', 'Customer'), Column('status', 'Status'),
               Column('due', 'Due', 'date'), Column('days', 'Days since due', 'number'),
               Column('balance', 'Balance', 'currency'), Column('synced', 'Synced from accounting', 'bool'))
    BUCKETS = (('0_30', '0–30 days'), ('31_60', '31–60 days'), ('61_90', '61–90 days'), ('90_plus', 'Over 90 days'))

    def collect(self, scope, filters):
        from core.models import Organization
        from psa.models import Invoice, get_psa_balance
        ids = scope.customer_ids(filters)
        # The aging report's rule: every customer with a non-void invoice,
        # each summed by get_psa_balance.
        client_ids = set(limit_to(Invoice.objects.exclude(status='void'), 'client_org', ids)
                         .values_list('client_org_id', flat=True))
        totals = {'outstanding': ZERO, 'net_balance': ZERO, 'credits': ZERO}
        aging = OrderedDict((k, ZERO) for k, _l in self.BUCKETS)
        for client in Organization.objects.filter(pk__in=client_ids):
            s = get_psa_balance(client)
            totals['outstanding'] += s['outstanding']
            totals['net_balance'] += s['net_balance']
            totals['credits'] += s['credit_total'] + s['invoice_credits']
            for k in aging:
                aging[k] += s['aging'][k]
        # The records: the invoices get_psa_balance counts as outstanding.
        today = timezone.localdate()
        rows, last_sync = [], None
        qs = Invoice.objects.filter(client_org_id__in=client_ids).exclude(status='void')
        for inv in qs.select_related('client_org').order_by('due_date', 'invoice_date', 'pk'):
            bal = _money(inv.balance)
            if bal <= 0:
                continue
            due = inv.due_date or inv.invoice_date
            if inv.provider_synced_at and (last_sync is None or inv.provider_synced_at > last_sync):
                last_sync = inv.provider_synced_at
            rows.append({'id': inv.pk, 'label': inv.invoice_number or f'#{inv.pk}', 'client_name': inv.client_org.name,
                         'status': inv.status, 'due': due, 'days': (today - due).days if due else None,
                         'balance': bal, 'synced': bool(inv.provider_synced_at),
                         'url': _url('psa:invoice_detail', inv.pk)})
        synced = sum(1 for r in rows if r['synced'])
        if synced:
            source = (f'Invoices; payment status synced from the accounting provider for {synced} of '
                      f'{len(rows)} (last read {timezone.localtime(last_sync):%Y-%m-%d %H:%M}); '
                      'aging as psa.get_psa_balance')
        else:
            source = 'Invoices and payments recorded here, no accounting sync (aging as psa.get_psa_balance)'
        breakdown = [{'label': label, 'value': aging[k], 'unit': 'currency'} for k, label in self.BUCKETS]
        breakdown.append({'label': 'Net of credits', 'value': totals['net_balance'], 'unit': 'currency'})
        return Collected(value=totals['outstanding'], rows=rows, source=source, breakdown=breakdown,
                         secondary=f'{len(rows)} invoices with a balance')


class PaymentCollection(MetricProvider):
    key = 'payment_collection'
    title = 'Payments needing attention'
    section = 'Billing'
    icon = 'fa-credit-card'
    unit = 'count'
    chart = 'none'
    order = 95
    permission = 'billing_view_invoices'
    source = 'Online payment attempts and disputes (payments)'
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('kind', 'Type'), Column('label', 'Invoice'), Column('client_name', 'Customer'),
               Column('amount', 'Amount', 'currency'), Column('detail', 'Detail'), Column('when', 'When', 'date'))

    def availability(self):
        if not apps.is_installed('payments'):
            return 'Online payments are not installed on this server.'
        from integrations.models import PaymentConnection
        if not PaymentConnection.objects.exists():
            return 'No payment gateway connection is set up.'
        return None

    def collect(self, scope, filters):
        from payments.models import Dispute, PaymentAttempt
        ids = scope.customer_ids(filters)
        window = Q(created_at__date__gte=filters.start, created_at__date__lte=filters.end)
        attempts = limit_to(PaymentAttempt.objects.filter(window), 'client_org', ids)
        rows = []
        for a in attempts.filter(status='failed').select_related('invoice', 'client_org').order_by('created_at', 'pk'):
            rows.append({'part': 'failed', 'kind': f'Failed {a.get_kind_display().lower()}', 'id': a.pk,
                         'label': a.invoice.invoice_number, 'client_name': a.client_org.name,
                         'amount': _money(a.amount), 'detail': a.failure_message or a.failure_code,
                         'when': a.created_at, 'autopay': a.kind == 'autopay',
                         'url': _url('payments:attempt_detail', a.pk)})
        disputes = limit_to(Dispute.objects.filter(status='open'), 'attempt__client_org', ids)
        for d in disputes.select_related('attempt', 'attempt__invoice', 'attempt__client_org').order_by('opened_at'):
            rows.append({'part': 'dispute', 'kind': 'Open dispute', 'id': d.pk,
                         'label': d.attempt.invoice.invoice_number, 'client_name': d.attempt.client_org.name,
                         'amount': _money(d.amount), 'detail': d.reason, 'when': d.opened_at, 'autopay': False,
                         'url': _url('payments:attempt_detail', d.attempt_id)})
        collected = sum((_money(a.amount_received if a.amount_received is not None else a.amount)
                         for a in attempts.filter(status='succeeded')), ZERO)
        failed = sum(1 for r in rows if r['part'] == 'failed')
        return Collected(value=len(rows), rows=rows, breakdown=[
            {'label': 'Failed payments', 'value': failed, 'part': 'failed'},
            {'label': 'of which autopay', 'value': sum(1 for r in rows if r['autopay'])},
            {'label': 'Open disputes', 'value': len(rows) - failed, 'part': 'dispute'},
            {'label': 'Collected online in period', 'value': collected, 'unit': 'currency'},
        ])


# -- delivery ------------------------------------------------------------------

class TechnicianUtilization(PsaProvider):
    key = 'technician_utilization'
    title = 'Technician utilization'
    section = 'Service delivery'
    icon = 'fa-user-clock'
    unit = 'percent'
    chart = 'bar'
    order = 100
    permission = 'reports_view_capacity'
    source = ('Billable hours ÷ available hours from shifts, working hours or billable targets '
              '(reports.queries.utilization_summary)')
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('label', 'Technician'), Column('billable_hours', 'Billable hours', 'hours'),
               Column('available_hours', 'Available hours', 'hours'), Column('basis', 'Basis'),
               Column('utilization_pct', 'Utilization', 'percent'))

    def collect(self, scope, filters):
        s = queries.utilization_summary(filters.start, filters.end, _org_arg(scope.customer_ids(filters)))
        rows = [dict(r, id=r['tech_id'], label=r['tech_username']) for r in s['rows']]
        without = s['techs_without_basis']
        return Collected(
            value=s['utilization_pct'], rows=rows,
            breakdown=[{'label': r['label'], 'value': r['utilization_pct'], 'unit': 'percent'}
                       for r in rows if r['utilization_pct'] is not None][:12],
            is_complete=s['is_complete'],
            unknown_reason=(f'{without} technicians have no shifts, working hours or billable target'
                            if without else ''),
            secondary=f"{s['billable_hours']:g} of {s['available_hours']:g} available hours",
        )


PRIORITY_CODES = ('P1', 'P2', 'P3', 'P4', 'P5')


class SlaAttainment(PsaProvider):
    key = 'sla_attainment'
    title = 'SLA attainment'
    section = 'Service delivery'
    icon = 'fa-stopwatch'
    unit = 'percent'
    chart = 'line'
    order = 110
    permission = 'reports_view_sla'
    source = ('Tickets created in the period without a resolution SLA breach '
              '(reports.queries.sla_trend_by_priority)')
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('label', 'Ticket'), Column('client_name', 'Customer'), Column('priority', 'Priority'),
               Column('created', 'Created', 'date'), Column('response_breached', 'Response breached', 'bool'),
               Column('resolution_breached', 'Resolution breached', 'bool'))

    def collect(self, scope, filters):
        from psa.models import Ticket
        ids = scope.customer_ids(filters)
        sla = queries.sla_trend_by_priority(filters.start, filters.end, _org_arg(ids), bucket='month')
        totals = sla['totals_by_priority'].values()
        n = sum(t['tickets'] for t in totals)
        breaches = sum(t['resolution_breaches'] for t in totals)
        resp_breaches = sum(t['response_breaches'] for t in totals)
        trend = []
        for i, label in enumerate(sla['buckets']):
            t = sum(sla['series'][p][i]['tickets'] for p in sla['priorities'])
            b = sum(sla['series'][p][i]['resolution_breaches'] for p in sla['priorities'])
            trend.append({'label': label, 'value': round(100 - b / t * 100, 1) if t else None})
        # The records: the tickets that report counts, flagged with its breach rules.
        now = timezone.now()
        qs = limit_to(Ticket.objects.filter(priority__code__in=sla['priorities'],
                                            created_at__date__gte=filters.start,
                                            created_at__date__lte=filters.end), 'organization', ids)
        resp = set(qs.exclude(first_response_due_at__isnull=True).filter(
            Q(first_response_at__gt=F('first_response_due_at'))
            | Q(first_response_at__isnull=True, first_response_due_at__lt=now)).values_list('pk', flat=True))
        res = set(qs.exclude(resolution_due_at__isnull=True).filter(
            closed_at__gt=F('resolution_due_at')).values_list('pk', flat=True))
        rows = [{'id': t.pk, 'label': t.ticket_number, 'client_name': t.organization.name,
                 'priority': t.priority.code, 'created': t.created_at,
                 'response_breached': t.pk in resp, 'resolution_breached': t.pk in res,
                 'url': _url('psa:ticket_detail', t.ticket_number)}
                for t in qs.select_related('organization', 'priority').order_by('created_at', 'pk')]
        return Collected(
            value=round(100 - breaches / n * 100, 1) if n else None, rows=rows, trend=trend,
            breakdown=[{'label': 'Tickets', 'value': n},
                       {'label': 'Resolution breaches', 'value': breaches},
                       {'label': 'Response SLA met', 'unit': 'percent',
                        'value': round(100 - resp_breaches / n * 100, 1) if n else None}],
            secondary='' if n else 'No tickets created in this period.',
        )


class TicketBacklog(PsaProvider):
    key = 'ticket_backlog'
    title = 'Ticket backlog'
    section = 'Service delivery'
    icon = 'fa-layer-group'
    unit = 'count'
    chart = 'bar'
    order = 120
    point_in_time = True
    permission = 'reports_view_sla'
    source = 'Open tickets (status not terminal) by age'
    supported_filters = (F_CUSTOMER, F_LOCATION)
    columns = (Column('label', 'Ticket'), Column('subject', 'Subject'), Column('client_name', 'Customer'),
               Column('priority', 'Priority'), Column('age_days', 'Age (days)', 'number'),
               Column('bucket', 'Age band'))
    BUCKETS = ((1, 'Under 1 day'), (3, '1–3 days'), (7, '3–7 days'), (30, '7–30 days'), (None, 'Over 30 days'))

    def collect(self, scope, filters):
        from psa.models import Ticket
        ids = scope.customer_ids(filters)
        qs = limit_to(Ticket.objects.filter(status__is_terminal=False), 'organization', ids)
        if filters.location:
            qs = qs.filter(site_id=filters.location)
        now = timezone.now()
        counts = OrderedDict((label, 0) for _l, label in self.BUCKETS)
        rows, ages = [], []
        for t in qs.select_related('organization', 'priority').order_by('created_at', 'pk'):
            age = (now - t.created_at).total_seconds() / 86400
            label = next(lbl for limit, lbl in self.BUCKETS if limit is None or age < limit)
            counts[label] += 1
            ages.append(age)
            rows.append({'id': t.pk, 'label': t.ticket_number, 'subject': t.subject,
                         'client_name': t.organization.name, 'priority': t.priority.code,
                         'age_days': round(age, 1), 'bucket': label,
                         'url': _url('psa:ticket_detail', t.ticket_number)})
        avg = round(sum(ages) / len(ages), 1) if ages else None
        return Collected(value=len(rows), rows=rows,
                         breakdown=[{'label': k, 'value': v} for k, v in counts.items()],
                         secondary=f'average age {avg:g} days' if avg is not None else 'No open tickets.')


class CriticalIssues(PsaProvider):
    key = 'critical_issues'
    title = 'Critical customer issues'
    section = 'Risk'
    icon = 'fa-triangle-exclamation'
    unit = 'count'
    chart = 'none'
    order = 130
    point_in_time = True
    permission = 'tickets_view'
    source = 'Open P1 tickets and open high / critical security incidents'
    supported_filters = (F_CUSTOMER, F_LOCATION)
    columns = (Column('kind', 'Type'), Column('label', 'Record'), Column('title', 'Title'),
               Column('client_name', 'Customer'), Column('opened', 'Opened', 'date'))
    INCIDENT_OPEN = ('open', 'investigating', 'contained')

    def collect(self, scope, filters):
        from psa.models import Ticket
        from security_alerts.models import SecurityIncident
        ids = scope.customer_ids(filters)
        qs = limit_to(Ticket.objects.filter(status__is_terminal=False, priority__code='P1'), 'organization', ids)
        if filters.location:
            qs = qs.filter(site_id=filters.location)
        rows = [{'part': 'p1', 'kind': 'P1 ticket', 'id': t.pk, 'label': t.ticket_number, 'title': t.subject,
                 'client_name': t.organization.name, 'opened': t.created_at,
                 'url': _url('psa:ticket_detail', t.ticket_number)}
                for t in qs.select_related('organization').order_by('created_at', 'pk')]
        reasons, notes, incidents = [], [], 0
        if filters.location:
            notes.append('Security incidents carry no location; with a location filter only P1 tickets count.')
        else:
            try:
                inc_ids = scope.other('security_alerts_view').customer_ids(filters)
            except Forbidden:
                reasons.append('security incidents hidden: your role lacks security_alerts_view')
            else:
                iqs = SecurityIncident.objects.filter(status__in=self.INCIDENT_OPEN, severity__in=('high', 'critical'))
                for i in limit_customer_or_owner(iqs, inc_ids).select_related(
                        'client_org', 'organization').order_by('opened_at', 'pk'):
                    incidents += 1
                    cust = i.client_org or i.organization
                    rows.append({'part': 'incident', 'kind': f'{i.get_severity_display()} incident', 'id': i.pk,
                                 'label': f'INC-{i.pk}', 'title': i.title, 'client_name': cust.name,
                                 'opened': i.opened_at, 'url': _url('security_alerts:incident_detail', i.pk)})
        return Collected(value=len(rows), rows=rows,
                         breakdown=[{'label': 'Open P1 tickets', 'value': len(rows) - incidents, 'part': 'p1'},
                                    {'label': 'Security incidents', 'value': incidents, 'part': 'incident'}],
                         is_complete=not reasons, unknown_reason='; '.join(reasons), notes=notes)


# -- risk / operations -----------------------------------------------------------

class SecurityIssues(MetricProvider):
    key = 'security_issues'
    title = 'Security alerts'
    section = 'Risk'
    icon = 'fa-shield-halved'
    unit = 'count'
    chart = 'bar'
    order = 140
    point_in_time = True
    permission = 'security_alerts_view'
    source = 'Security alerts not yet resolved or dismissed (security_alerts)'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Alert'), Column('client_name', 'Customer'), Column('severity', 'Severity'),
               Column('status', 'Status'), Column('seen', 'Seen', 'date'))
    SEVERITIES = ('critical', 'high', 'medium', 'low', 'info')

    def availability(self):
        from security_alerts.models import SecurityAlert, SecurityVendorConnection, SIEMWebhookEndpoint
        if not (SecurityVendorConnection.objects.exists() or SIEMWebhookEndpoint.objects.exists()
                or SecurityAlert.objects.exists()):
            return 'No security vendor connection or SIEM endpoint is set up.'
        return None

    def collect(self, scope, filters):
        from security_alerts.models import SecurityAlert
        ids = scope.customer_ids(filters)
        qs = limit_customer_or_owner(SecurityAlert.objects.filter(status__in=('new', 'acknowledged')), ids)
        labels = dict(SecurityAlert.SEVERITY_CHOICES)
        counts = OrderedDict((s, 0) for s in self.SEVERITIES)
        rows = []
        for a in qs.select_related('client_org', 'organization').order_by('-seen_at', '-pk'):
            counts[a.severity] = counts.get(a.severity, 0) + 1
            cust = a.client_org or a.organization
            rows.append({'id': a.pk, 'label': a.title, 'client_name': cust.name,
                         'severity': labels.get(a.severity, a.severity), 'status': a.status,
                         'seen': a.seen_at, 'url': _url('security_alerts:alert_detail', a.pk)})
        return Collected(value=len(rows), rows=rows,
                         breakdown=[{'label': labels.get(k, k), 'value': v} for k, v in counts.items()],
                         secondary=f"{counts['critical'] + counts['high']} high or critical")


class BackupFailures(MetricProvider):
    key = 'backup_failures'
    title = 'Backup failures'
    section = 'Risk'
    icon = 'fa-database'
    unit = 'count'
    chart = 'bar'
    order = 150
    point_in_time = True
    source = 'Open backup alerts (backup_monitoring)'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Alert'), Column('client_name', 'Customer'), Column('kind', 'Kind'),
               Column('severity', 'Severity'), Column('last_seen', 'Last seen', 'date'))

    def permission_key(self):
        from accounts.permission_registry import is_known
        return 'view_backup_status' if is_known('view_backup_status') else 'monitoring_view'

    def availability(self):
        if not apps.is_installed('backup_monitoring'):
            return 'Backup monitoring is not installed on this server (dev/backup-monitoring).'
        try:
            conn = apps.get_model('backup_monitoring', 'BackupConnection')
            apps.get_model('backup_monitoring', 'BackupAlert')
        except LookupError:
            return 'Backup monitoring is installed but has no alert records.'
        if not conn.objects.exists():
            return 'No backup connection is set up.'
        return None

    def collect(self, scope, filters):
        alert = apps.get_model('backup_monitoring', 'BackupAlert')
        names = {f.name for f in alert._meta.get_fields()}
        if not {'organization', 'status', 'title'} <= names:
            raise NotConfigured('The installed backup monitoring app has an unexpected alert schema.')
        ids = scope.customer_ids(filters)
        qs = limit_to(alert.objects.filter(status__in=('open', 'acknowledged')), 'organization', ids)
        rows, kinds = [], OrderedDict()
        for a in qs.select_related('organization').order_by('-pk'):
            kind = getattr(a, 'kind', '') or 'other'
            kinds[kind] = kinds.get(kind, 0) + 1
            job_id = getattr(a, 'job_id', None)
            rows.append({'id': a.pk, 'label': a.title, 'client_name': a.organization.name, 'kind': kind,
                         'severity': getattr(a, 'severity', ''), 'last_seen': getattr(a, 'last_seen_at', None),
                         'url': (_url('backup_monitoring:job_detail', job_id) if job_id
                                 else _url('backup_monitoring:alert_list'))})
        return Collected(value=len(rows), rows=rows,
                         breakdown=[{'label': k, 'value': v} for k, v in kinds.items()])


class ProcurementStatus(PsaProvider):
    key = 'procurement_status'
    title = 'Procurement'
    section = 'Operations'
    icon = 'fa-cart-shopping'
    unit = 'count'
    chart = 'none'
    order = 160
    point_in_time = True
    permission = 'procurement_view'
    source = 'Requisitions awaiting approval, open purchase orders and open back-orders'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('kind', 'Type'), Column('label', 'Number'), Column('title', 'Title'),
               Column('client_name', 'Customer'), Column('status', 'Status'), Column('since', 'Since', 'date'))
    PO_OPEN = ('sent', 'acknowledged', 'partial')

    def collect(self, scope, filters):
        from psa.models import POBackOrder, PurchaseOrder, PurchaseRequisition
        ids = scope.customer_ids(filters)
        rows = []
        prs = limit_customer_or_owner(PurchaseRequisition.objects.filter(status='submitted'), ids)
        for pr in prs.select_related('client_org', 'organization').order_by('requested_at', 'pk'):
            rows.append({'part': 'requisitions', 'kind': 'Requisition awaiting approval', 'id': pr.pk,
                         'label': pr.pr_number, 'title': pr.title,
                         'client_name': (pr.client_org or pr.organization).name, 'status': pr.status,
                         'since': pr.requested_at, 'url': _url('psa:requisition_detail', pr.pk)})
        pos = limit_customer_or_owner(PurchaseOrder.objects.filter(status__in=self.PO_OPEN), ids)
        for po in pos.select_related('client_org', 'organization').order_by('issue_date', 'pk'):
            rows.append({'part': 'purchase_orders', 'kind': 'Open purchase order', 'id': po.pk,
                         'label': po.po_number, 'title': po.title,
                         'client_name': (po.client_org or po.organization).name,
                         'status': po.get_status_display(), 'since': po.issue_date,
                         'url': _url('psa:po_detail', po.pk)})
        bos = limit_customer_or_owner(POBackOrder.objects.filter(status='open'), ids,
                                      customer='po__client_org', owner='po__organization')
        for bo in bos.select_related('po', 'po__client_org', 'po__organization', 'po_line').order_by('created_at', 'pk'):
            rows.append({'part': 'back_orders', 'kind': 'Back-order', 'id': bo.pk, 'label': bo.po.po_number,
                         'title': f'{bo.po_line.description} ({bo.quantity_outstanding:g} outstanding)',
                         'client_name': (bo.po.client_org or bo.po.organization).name, 'status': bo.status,
                         'since': bo.created_at, 'url': _url('psa:po_detail', bo.po_id)})
        count = {p: sum(1 for r in rows if r['part'] == p) for p in ('requisitions', 'purchase_orders', 'back_orders')}
        return Collected(value=len(rows), rows=rows, breakdown=[
            {'label': 'Awaiting approval', 'value': count['requisitions'], 'part': 'requisitions'},
            {'label': 'Open purchase orders', 'value': count['purchase_orders'], 'part': 'purchase_orders'},
            {'label': 'Open back-orders', 'value': count['back_orders'], 'part': 'back_orders'},
        ])


class LicensingRenewals(MetricProvider):
    key = 'licensing_renewals'
    title = 'License renewals (90 days)'
    section = 'Operations'
    icon = 'fa-id-card'
    unit = 'currency'
    chart = 'bar'
    order = 170
    point_in_time = True
    source = 'Live license subscriptions renewing in the next 90 days at customer price (licensing)'
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Subscription'), Column('client_name', 'Customer'),
               Column('renewal_date', 'Renews', 'date'), Column('days_left', 'Days left', 'number'),
               Column('quantity', 'Seats', 'number'), Column('value', 'Renewal value', 'currency'))
    LIVE = ('active', 'trial')

    def availability(self):
        if not apps.is_installed('licensing'):
            return 'License tracking is not installed on this server (dev/licensing).'
        try:
            sub = apps.get_model('licensing', 'LicenseSubscription')
        except LookupError:
            return 'License tracking is installed but has no subscription model.'
        if not sub.objects.exists():
            return 'No license subscriptions are recorded.'
        return None

    def collect(self, scope, filters):
        sub = apps.get_model('licensing', 'LicenseSubscription')
        names = {f.name for f in sub._meta.get_fields()}
        if not {'organization', 'renewal_date', 'status', 'quantity_purchased', 'unit_price'} <= names:
            raise NotConfigured('The installed licensing app has an unexpected subscription schema.')
        ids = scope.customer_ids(filters)
        today = timezone.localdate()
        qs = limit_to(sub.objects.filter(status__in=self.LIVE, renewal_date__gte=today,
                                         renewal_date__lte=today + timedelta(days=90)), 'organization', ids)
        rows, unpriced = [], 0
        for s in qs.select_related('organization').order_by('renewal_date', 'pk'):
            value = None
            if s.unit_price is None:
                unpriced += 1
            else:
                value = _money(Decimal(str(s.unit_price)) * s.quantity_purchased)
            rows.append({'id': s.pk, 'label': str(s), 'client_name': s.organization.name,
                         'renewal_date': s.renewal_date, 'days_left': (s.renewal_date - today).days,
                         'quantity': s.quantity_purchased, 'value': value, 'url': ''})
        breakdown = [{'label': f'{w} days', 'unit': 'currency',
                      'value': sum((r['value'] or ZERO for r in rows if r['days_left'] <= w), ZERO)}
                     for w in (30, 60, 90)]
        return Collected(value=sum((r['value'] or ZERO for r in rows), ZERO), rows=rows, breakdown=breakdown,
                         is_complete=not unpriced,
                         unknown_reason=f'{unpriced} subscriptions have no customer price' if unpriced else '',
                         secondary=f'{len(rows)} subscriptions renewing')


PROVIDERS = tuple(sorted((
    MrrArr(), RevenueTrend(), GrossMargin(), CustomerProfitability(), CustomerGrowth(),
    ContractRenewals(), OutstandingQuotes(), UnbilledWork(), AccountsReceivable(), PaymentCollection(),
    TechnicianUtilization(), SlaAttainment(), TicketBacklog(), CriticalIssues(),
    SecurityIssues(), BackupFailures(), ProcurementStatus(), LicensingRenewals(),
), key=lambda p: p.order))
REGISTRY = {p.key: p for p in PROVIDERS}
assert all(set(p.supported_filters) <= set(ALL_FILTERS) for p in PROVIDERS)


def get(key):
    return REGISTRY.get(key)
