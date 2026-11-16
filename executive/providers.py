"""The Business Overview metrics, one provider per card.

Every provider reads an existing source. Where a canonical reporting function
exists in `reports.queries` (or `reports.costing`) it is looked up with
getattr / find_spec at call time, so a server without it reports the card as
"not configured" instead of computing a stand-in. Apps that are not installed
(backup monitoring, licensing) are detected through the app registry.

The value and the drill-down rows always come from the same collect() call;
see executive.metrics. docs/plans/EXECUTIVE_METRICS.md lists every metric,
its source and which branch completes it.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal
from importlib.util import find_spec

from django.apps import apps
from django.db.models import F, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .metrics import (
    ALL_FILTERS, F_CUSTOMER, F_DATE, F_LOCATION, F_SERVICE_LINE, Collected, Column,
    Forbidden, MetricProvider, NotConfigured, limit_customer_or_owner, limit_to, months_between,
)

ZERO = Decimal('0')
# Issued invoices, the set revenue reports count (reports.queries.revenue_by_client).
REVENUE_STATUSES = ('sent', 'partial', 'paid', 'overdue')
# Invoices that can still carry a receivable.
AR_STATUSES = ('sent', 'partial', 'overdue')
PROFITABILITY_BRANCH = 'dev/profitability'


# -- shared helpers ------------------------------------------------------------

def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _queries_fn(name):
    """reports.queries.<name> when this server has it, else None."""
    try:
        from reports import queries
    except Exception:  # pragma: no cover - reports is always installed
        return None
    return getattr(queries, name, None)


def has_costing():
    """reports.costing: per-entry cost and bill rates with completeness
    (no placeholder rates). Lands with dev/profitability."""
    try:
        return find_spec('reports.costing') is not None
    except (ImportError, ValueError):
        return False


def _psa_off():
    from core.models import SystemSetting
    if not SystemSetting.get_settings().psa_enabled:
        return 'The PSA module is switched off (Administration → Modules).'
    return None


def _as_set(ids):
    return None if ids is None else set(ids)


def _money(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'))


def _hours(minutes):
    return round((minutes or 0) / 60.0, 2)


def _perm_known(key):
    from accounts.permission_registry import is_known
    return is_known(key)


def _monthly_amount(contract):
    """reports.queries.monthly_amount (dev/profitability) when present."""
    fn = _queries_fn('monthly_amount')
    if fn is None:
        return None
    m = fn(contract)
    return None if m is None else Decimal(str(m))


class PsaProvider(MetricProvider):
    def availability(self):
        return _psa_off()


# -- revenue -------------------------------------------------------------------

class MrrArr(PsaProvider):
    key = 'mrr_arr'
    title = 'MRR & ARR'
    section = 'Revenue'
    icon = 'fa-arrows-rotate'
    unit = 'currency'
    chart = 'line'
    order = 10
    source = ('Billing contracts: recurring amount normalized to a month '
              '(reports.queries.recurring_revenue / mrr_trend)')
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('label', 'Contract'), Column('client_name', 'Customer'),
               Column('frequency', 'Billing frequency'), Column('mrr', 'MRR', 'currency'),
               Column('next_billing_date', 'Next billing', 'date'), Column('end_date', 'Ends', 'date'))

    def availability(self):
        if _queries_fn('recurring_revenue') is None or _queries_fn('mrr_trend') is None:
            return ('Recurring revenue reporting (reports.queries.recurring_revenue) is not on this '
                    f'server yet; it arrives with {PROFITABILITY_BRANCH}.')
        return super().availability()

    def as_of(self, filters):
        return filters.end

    def collect(self, scope, filters):
        ids = _as_set(scope.customer_ids(filters))
        rr = _queries_fn('recurring_revenue')(filters.end, ids)
        trend = _queries_fn('mrr_trend')(12, filters.end, ids)
        rows = [dict(c, label=c.get('contract_name', ''),
                     url=_url('psa:contract_detail', c['contract_id']))
                for c in rr.get('contracts', [])]
        reasons, notes = [], []
        if rr.get('contracts_unknown_end'):
            reasons.append(f"{rr['contracts_unknown_end']} stopped contracts have no end date")
        if rr.get('contracts_without_amount'):
            notes.append(f"{rr['contracts_without_amount']} running contracts have no recurring "
                         'amount and add nothing to MRR.')
        return Collected(
            value=rr.get('mrr'), rows=rows,
            trend=[{'label': p['month'], 'value': p['mrr']} for p in trend.get('points', [])],
            breakdown=[{'label': 'ARR', 'value': rr.get('arr'), 'unit': 'currency'},
                       {'label': 'Contracts', 'value': rr.get('contract_count', len(rows))}],
            is_complete=bool(rr.get('is_complete', True)) and bool(trend.get('is_complete', True)),
            unknown_reason='; '.join(reasons) or (
                '' if trend.get('is_complete', True) else 'Some months include contracts with no end date'),
            notes=notes,
        )


class RevenueTrend(PsaProvider):
    key = 'revenue_trend'
    title = 'Invoiced revenue'
    section = 'Revenue'
    icon = 'fa-file-invoice-dollar'
    unit = 'currency'
    chart = 'bar'
    order = 20
    source = 'Issued invoices (sent, partially paid, paid, overdue) by invoice date'
    supported_filters = (F_DATE, F_CUSTOMER, F_SERVICE_LINE)
    columns = (Column('label', 'Invoice'), Column('client_name', 'Customer'),
               Column('invoice_date', 'Date', 'date'), Column('status', 'Status'),
               Column('service_line', 'Service line'), Column('total', 'Total', 'currency'))

    def collect(self, scope, filters):
        from psa.models import Contract, Invoice
        ids = scope.customer_ids(filters)
        qs = Invoice.objects.filter(invoice_date__gte=filters.start, invoice_date__lte=filters.end,
                                    status__in=REVENUE_STATUSES)
        qs = limit_to(qs, 'client_org', ids)
        if filters.service_line:
            qs = qs.filter(source_contract__contract_type=filters.service_line)
        labels = dict(Contract.CONTRACT_TYPES)
        rows, by_month = [], OrderedDict((m[0], ZERO) for m in months_between(filters.start, filters.end))
        for inv in qs.select_related('client_org', 'source_contract').order_by('invoice_date', 'pk'):
            total = _money(inv.total)
            by_month[inv.invoice_date.strftime('%Y-%m')] = by_month.get(
                inv.invoice_date.strftime('%Y-%m'), ZERO) + total
            sl = inv.source_contract.contract_type if inv.source_contract_id else ''
            rows.append({'id': inv.pk, 'label': inv.invoice_number or f'#{inv.pk}',
                         'client_name': inv.client_org.name, 'invoice_date': inv.invoice_date,
                         'status': inv.status, 'service_line': labels.get(sl, ''),
                         'total': total, 'url': _url('psa:invoice_detail', inv.pk)})
        total = sum((r['total'] for r in rows), ZERO)
        return Collected(value=total, rows=rows,
                         trend=[{'label': k, 'value': v} for k, v in by_month.items()],
                         breakdown=[{'label': 'Invoices', 'value': len(rows)}])


class _Profitability(PsaProvider):
    """Shared source for the margin cards: reports.queries.profitability_by_client
    as rewritten on dev/profitability (each entry costed at its technician's
    rate on the day; hours without a rate reported as unknown_cost_hours)."""
    section = 'Profitability'
    label = 'Operational estimate, not accounting results'
    source = ('Invoiced revenue less labour cost at each technician\'s cost rate '
              '(reports.queries.profitability_by_client, reports.costing)')
    supported_filters = (F_DATE, F_CUSTOMER)

    def permission_key(self):
        return 'view_profitability' if _perm_known('view_profitability') else 'reports_view_financial'

    @property
    def permission_note(self):
        if _perm_known('view_profitability'):
            return ''
        return ('Gated by reports_view_financial: the view_profitability permission is not on this '
                f'server yet ({PROFITABILITY_BRANCH}).')

    def availability(self):
        if not has_costing() or _queries_fn('profitability_by_client') is None:
            return ('Cost and margin need per-technician cost rates without placeholder fallbacks '
                    f'(reports.costing), which arrive with {PROFITABILITY_BRANCH}.')
        return super().availability()

    def _rows(self, scope, filters, start=None, end=None):
        ids = scope.customer_ids(filters)
        # Called for every customer and narrowed here: the per-client rows are
        # the records, so filtering them is exact, and it does not depend on
        # which invoice field the query function filters on.
        raw = _queries_fn('profitability_by_client')(start or filters.start, end or filters.end, None)
        out = []
        for r in raw:
            if ids is not None and r.get('client_id') not in ids:
                continue
            out.append(r)
        return out

    @staticmethod
    def _totals(rows):
        revenue = sum((_money(r.get('revenue')) for r in rows), ZERO)
        cost = sum((_money(r.get('cost')) for r in rows), ZERO)
        unknown = sum(float(r.get('unknown_cost_hours') or 0) for r in rows)
        return revenue, cost, unknown


def _unknown_hours_reason(hours):
    if not hours:
        return ''
    return f'{round(hours, 1):g} hours without a cost rate'


class GrossMargin(_Profitability):
    key = 'gross_margin'
    title = 'Gross margin'
    icon = 'fa-scale-balanced'
    unit = 'percent'
    chart = 'line'
    order = 30
    columns = (Column('client_name', 'Customer'), Column('revenue', 'Revenue', 'currency'),
               Column('cost', 'Labour cost (known)', 'currency'), Column('margin', 'Margin', 'currency'),
               Column('margin_pct', 'Margin %', 'percent'),
               Column('unknown_cost_hours', 'Hours without cost rate', 'hours'))

    def collect(self, scope, filters):
        rows = self._rows(scope, filters)
        revenue, cost, unknown = self._totals(rows)
        pct = float((revenue - cost) / revenue * 100) if revenue else None
        trend = []
        for label, m_start, m_end in months_between(filters.start, filters.end):
            m_rev, m_cost, _u = self._totals(self._rows(scope, filters, m_start, m_end))
            trend.append({'label': label,
                          'value': round(float((m_rev - m_cost) / m_rev * 100), 1) if m_rev else None})
        out = [dict(r, label=r.get('client_name', ''),
                    url=_url('accounts:organization_detail', r['client_id'])) for r in rows]
        return Collected(
            value=None if pct is None else round(pct, 1), rows=out, trend=trend,
            breakdown=[{'label': 'Revenue', 'value': revenue, 'unit': 'currency'},
                       {'label': 'Labour cost', 'value': cost, 'unit': 'currency'},
                       {'label': 'Margin', 'value': revenue - cost, 'unit': 'currency'}],
            is_complete=not unknown, unknown_reason=_unknown_hours_reason(unknown),
            secondary='' if revenue else 'No invoiced revenue in this period.',
        )


class CustomerProfitability(_Profitability):
    key = 'customer_profitability'
    title = 'Customer profitability'
    icon = 'fa-ranking-star'
    unit = 'count'
    chart = 'bars_signed'
    order = 40
    columns = GrossMargin.columns

    def collect(self, scope, filters):
        rows = self._rows(scope, filters)
        _r, _c, unknown = self._totals(rows)
        ranked = [r for r in rows if r.get('margin') is not None]
        ranked.sort(key=lambda r: r['margin'], reverse=True)
        top, bottom = ranked[:5], list(reversed(ranked[-5:])) if len(ranked) > 5 else []
        breakdown = [{'label': r['client_name'], 'value': r['margin'], 'unit': 'currency', 'group': 'Top'}
                     for r in top]
        breakdown += [{'label': r['client_name'], 'value': r['margin'], 'unit': 'currency',
                       'group': 'Bottom'} for r in bottom]
        unranked = len(rows) - len(ranked)
        out = [dict(r, label=r.get('client_name', ''),
                    url=_url('accounts:organization_detail', r['client_id']))
               for r in sorted(rows, key=lambda r: (r.get('margin') is None, -(r.get('margin') or 0)))]
        reason = _unknown_hours_reason(unknown)
        if unranked:
            reason = (reason + '; ' if reason else '') + f'{unranked} customers cannot be ranked'
        return Collected(value=len(rows), rows=out, breakdown=breakdown,
                         is_complete=not unknown and not unranked, unknown_reason=reason,
                         secondary=f'{len(ranked)} ranked by margin')


# -- customers & contracts -----------------------------------------------------

def _running_contracts(on_date, ids, service_line=''):
    """Non-draft contracts running on `on_date` and the stopped ones whose
    stop date is unknown (cancelled / expired, no end date)."""
    from psa.models import Contract
    qs = Contract.objects.exclude(status='draft').filter(start_date__lte=on_date).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=on_date))
    qs = limit_to(qs, 'client_org', ids)
    if service_line:
        qs = qs.filter(contract_type=service_line)
    running, unknown = [], []
    for c in qs.select_related('client_org'):
        if c.status == 'active' or c.end_date is not None:
            running.append(c)
        else:
            unknown.append(c)
    return running, unknown


class CustomerGrowth(PsaProvider):
    key = 'customer_growth'
    title = 'Customers: growth & churn'
    section = 'Customers'
    icon = 'fa-users'
    unit = 'count'
    chart = 'line'
    order = 50
    source = ('Customers with a running billing contract; churn from '
              'reports.queries.contract_churn when available')
    supported_filters = (F_DATE, F_CUSTOMER, F_SERVICE_LINE)
    columns = (Column('label', 'Customer'), Column('contracts', 'Running contracts', 'number'),
               Column('first_start', 'Customer since', 'date'), Column('new_in_period', 'New in period', 'bool'))

    def as_of(self, filters):
        return filters.end

    def collect(self, scope, filters):
        from psa.models import Contract
        ids = scope.customer_ids(filters)
        running, unknown = _running_contracts(filters.end, ids, filters.service_line)
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
        unknown_months = 0
        for label, _s, m_end in months_between(filters.start, filters.end):
            r, u = _running_contracts(m_end, ids, filters.service_line)
            unknown_months += bool(u)
            trend.append({'label': label, 'value': len({c.client_org_id for c in r})})
        breakdown = [{'label': 'New customers in period', 'value': len(new_ids)}]
        reasons, notes = [], []
        if unknown:
            reasons.append(f'{len(unknown)} stopped contracts have no end date')
        churn_fn = _queries_fn('contract_churn')
        if churn_fn is None:
            reasons.append(f'contract churn reporting arrives with {PROFITABILITY_BRANCH}')
        else:
            churn = churn_fn(filters.start, filters.end, _as_set(ids))
            breakdown.append({'label': 'Churned contracts', 'value': churn.get('churned_count')})
            breakdown.append({'label': 'Churned MRR', 'value': churn.get('churned_mrr'), 'unit': 'currency'})
            if churn.get('churn_rate_pct') is not None:
                breakdown.append({'label': 'Revenue churn', 'value': churn['churn_rate_pct'],
                                  'unit': 'percent'})
            if filters.service_line:
                notes.append('Churn figures cover every service line.')
            if not churn.get('is_complete', True):
                reasons.append(f"{churn.get('undated_cancellations', 0)} cancellations have no end date")
        return Collected(value=len(rows), rows=rows, trend=trend, breakdown=breakdown,
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
    source = 'Active billing contracts by end date'
    supported_filters = (F_CUSTOMER, F_SERVICE_LINE)
    columns = (Column('label', 'Contract'), Column('client_name', 'Customer'),
               Column('end_date', 'Ends', 'date'), Column('days_left', 'Days left', 'number'),
               Column('auto_renew', 'Auto-renews', 'bool'), Column('mrr', 'MRR at stake', 'currency'))

    def collect(self, scope, filters):
        from psa.models import Contract
        ids = scope.customer_ids(filters)
        today = timezone.localdate()
        qs = Contract.objects.filter(status='active', end_date__isnull=False,
                                     end_date__gte=today, end_date__lte=today + timedelta(days=90))
        qs = limit_to(qs, 'client_org', ids)
        if filters.service_line:
            qs = qs.filter(contract_type=filters.service_line)
        priced = _queries_fn('monthly_amount') is not None
        rows = []
        for c in qs.select_related('client_org').order_by('end_date', 'pk'):
            rows.append({'id': c.pk, 'label': c.name, 'client_name': c.client_org.name,
                         'end_date': c.end_date, 'days_left': (c.end_date - today).days,
                         'auto_renew': c.auto_renew, 'mrr': _monthly_amount(c) if priced else None,
                         'url': _url('psa:contract_detail', c.pk)})
        breakdown = []
        for w in (30, 60, 90):
            inside = [r for r in rows if r['days_left'] <= w]
            item = {'label': f'{w} days', 'value': len(inside)}
            breakdown.append(item)
        notes = []
        if priced:
            breakdown.append({'label': 'MRR at stake (90 days)', 'unit': 'currency',
                              'value': sum((r['mrr'] or ZERO for r in rows), ZERO)})
        else:
            notes.append(f'MRR at stake appears once recurring revenue reporting lands ({PROFITABILITY_BRANCH}).')
        return Collected(value=len(rows), rows=rows, breakdown=breakdown, notes=notes,
                         secondary=f"{sum(1 for r in rows if r['auto_renew'])} set to auto-renew")


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
    unit = 'hours'
    chart = 'bar'
    order = 80
    source = ('Billable, finished time entries not on any live invoice '
              '(InvoiceLineItem.billed_source_ids)')
    supported_filters = (F_DATE, F_CUSTOMER, F_LOCATION)
    columns = (Column('label', 'Ticket'), Column('client_name', 'Customer'),
               Column('technician', 'Technician'), Column('date', 'Date', 'date'),
               Column('hours', 'Hours', 'hours'), Column('amount', 'Value at bill rate', 'currency'))

    def collect(self, scope, filters):
        from psa.models import InvoiceLineItem, TicketTimeEntry
        ids = scope.customer_ids(filters)
        qs = TicketTimeEntry.objects.filter(
            started_at__date__gte=filters.start, started_at__date__lte=filters.end,
            is_billable=True, ended_at__isnull=False, duration_minutes__gt=0, rejected_at__isnull=True)
        qs = limit_to(qs, 'ticket__organization', ids)
        if filters.location:
            qs = qs.filter(ticket__site_id=filters.location)
        billed = InvoiceLineItem.billed_source_ids('time')
        book = None
        if has_costing():
            from reports.costing import RateBook
            book = RateBook()
        rows, by_client = [], OrderedDict()
        without_rate = 0
        for te in qs.select_related('ticket', 'ticket__organization', 'user').order_by('started_at', 'pk'):
            if te.pk in billed:
                continue
            org = te.ticket.organization
            hours = _hours(te.duration_minutes)
            amount = None
            if book is not None:
                rate = book.bill_rate_for(te)
                if rate is None:
                    without_rate += 1
                else:
                    amount = _money(Decimal(str(hours)) * Decimal(str(rate)))
            rows.append({'id': te.pk, 'label': te.ticket.ticket_number or f'#{te.ticket_id}',
                         'client_name': org.name if org else '', 'technician': te.user.username if te.user else '',
                         'date': te.started_at.date(), 'hours': hours, 'amount': amount,
                         'url': _url('psa:ticket_detail', te.ticket.ticket_number)})
            key = org.name if org else '—'
            by_client[key] = by_client.get(key, 0) + hours
        total_hours = round(sum(r['hours'] for r in rows), 2)
        top = sorted(by_client.items(), key=lambda kv: -kv[1])[:8]
        breakdown = [{'label': k, 'value': round(v, 2), 'unit': 'hours'} for k, v in top]
        if book is None:
            return Collected(value=total_hours, rows=rows, breakdown=breakdown,
                             secondary=f'{len(rows)} time entries',
                             notes=['Valued in hours. Valuation at bill rates arrives with '
                                    f'{PROFITABILITY_BRANCH} (rate snapshots).'])
        amount = sum((r['amount'] or ZERO for r in rows), ZERO)
        return Collected(value=amount, unit='currency', rows=rows, breakdown=breakdown,
                         secondary=f'{total_hours:g} hours in {len(rows)} time entries',
                         is_complete=not without_rate,
                         unknown_reason=f'{without_rate} entries without a bill rate' if without_rate else '')


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
    supported_filters = (F_CUSTOMER,)
    columns = (Column('label', 'Invoice'), Column('client_name', 'Customer'),
               Column('due', 'Due', 'date'), Column('days_overdue', 'Days past due', 'number'),
               Column('balance', 'Balance due', 'currency'), Column('synced', 'Synced from accounting', 'bool'))
    BUCKETS = ('Current', '1–30 days', '31–60 days', '61–90 days', 'Over 90 days')

    @staticmethod
    def _bucket(days):
        if days <= 0:
            return 'Current'
        if days <= 30:
            return '1–30 days'
        if days <= 60:
            return '31–60 days'
        if days <= 90:
            return '61–90 days'
        return 'Over 90 days'

    def collect(self, scope, filters):
        from psa.models import Invoice
        ids = scope.customer_ids(filters)
        qs = Invoice.objects.filter(status__in=AR_STATUSES, is_credit_memo=False)
        qs = limit_to(qs, 'client_org', ids)
        today = timezone.localdate()
        rows = []
        buckets = OrderedDict((b, ZERO) for b in self.BUCKETS)
        last_sync = None
        for inv in qs.select_related('client_org').prefetch_related('credit_memos').order_by('due_date', 'pk'):
            balance = _money(inv.net_balance_due)
            if balance <= 0:
                continue
            due = inv.due_date or inv.invoice_date
            days = (today - due).days if due else 0
            bucket = self._bucket(days)
            buckets[bucket] += balance
            synced = bool(inv.provider_synced_at)
            if synced and (last_sync is None or inv.provider_synced_at > last_sync):
                last_sync = inv.provider_synced_at
            rows.append({'id': inv.pk, 'label': inv.invoice_number or f'#{inv.pk}',
                         'client_name': inv.client_org.name, 'due': due, 'days_overdue': max(days, 0),
                         'balance': balance, 'bucket': bucket, 'synced': synced,
                         'url': _url('psa:invoice_detail', inv.pk)})
        synced_n = sum(1 for r in rows if r['synced'])
        if synced_n:
            source = (f'Invoices; payment status synced from the accounting provider for {synced_n} of '
                      f'{len(rows)} (last read {timezone.localtime(last_sync):%Y-%m-%d %H:%M})')
        else:
            source = 'Invoices and payments recorded here (no accounting sync on these invoices)'
        overdue = sum((r['balance'] for r in rows if r['days_overdue'] > 0), ZERO)
        return Collected(value=sum((r['balance'] for r in rows), ZERO), rows=rows, source=source,
                         breakdown=[{'label': k, 'value': v, 'unit': 'currency'} for k, v in buckets.items()],
                         secondary=f'{len(rows)} invoices; {overdue:,.2f} past due')


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

    def availability(self):
        if _queries_fn('utilization_summary') is None:
            return ('Utilization against available hours (reports.queries.utilization_summary) is not on '
                    f'this server yet; it arrives with {PROFITABILITY_BRANCH}.')
        return super().availability()

    def collect(self, scope, filters):
        ids = _as_set(scope.customer_ids(filters))
        s = _queries_fn('utilization_summary')(filters.start, filters.end, ids)
        rows = [dict(r, label=r.get('tech_username', '')) for r in s.get('rows', [])]
        without = s.get('techs_without_basis', 0)
        return Collected(
            value=s.get('utilization_pct'), rows=rows,
            breakdown=[{'label': r['label'], 'value': r.get('utilization_pct'), 'unit': 'percent'}
                       for r in rows if r.get('utilization_pct') is not None][:12],
            is_complete=bool(s.get('is_complete', not without)),
            unknown_reason=(f'{without} technicians have no shifts, working hours or billable target'
                            if without else ''),
            secondary=f"{s.get('billable_hours', 0):g} of {s.get('available_hours', 0):g} available hours",
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
    source = ('Tickets created in the period: resolution SLA met '
              '(same breach rules as reports.queries.sla_trend_by_priority)')
    supported_filters = (F_DATE, F_CUSTOMER)
    columns = (Column('label', 'Ticket'), Column('client_name', 'Customer'), Column('priority', 'Priority'),
               Column('created', 'Created', 'date'), Column('response_breached', 'Response breached', 'bool'),
               Column('resolution_breached', 'Resolution breached', 'bool'))

    def collect(self, scope, filters):
        from psa.models import Ticket
        from reports.queries import sla_trend_by_priority
        ids = scope.customer_ids(filters)
        now = timezone.now()
        qs = Ticket.objects.filter(priority__code__in=PRIORITY_CODES,
                                   created_at__date__gte=filters.start, created_at__date__lte=filters.end)
        qs = limit_to(qs, 'organization', ids)
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
        n = len(rows)
        breaches = sum(1 for r in rows if r['resolution_breached'])
        resp_breaches = sum(1 for r in rows if r['response_breached'])
        trend_src = sla_trend_by_priority(filters.start, filters.end, _as_set(ids), bucket='month')
        trend = []
        for i, label in enumerate(trend_src['buckets']):
            t = sum(trend_src['series'][p][i]['tickets'] for p in trend_src['priorities'])
            b = sum(trend_src['series'][p][i]['resolution_breaches'] for p in trend_src['priorities'])
            trend.append({'label': label, 'value': round(100 - b / t * 100, 1) if t else None})
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
        reasons, notes = [], []
        sec = scope.other('security_alerts_view')
        incidents = 0
        if filters.location:
            notes.append('Security incidents carry no location; with a location filter only P1 tickets count.')
        else:
            try:
                inc_ids = sec.customer_ids(filters)
            except Forbidden:
                inc_ids = None
                reasons.append('security incidents hidden: your role lacks security_alerts_view')
        if not filters.location and not reasons:
            iqs = SecurityIncident.objects.filter(status__in=self.INCIDENT_OPEN, severity__in=('high', 'critical'))
            iqs = limit_customer_or_owner(iqs, inc_ids)
            for i in iqs.select_related('client_org', 'organization').order_by('opened_at', 'pk'):
                incidents += 1
                cust = i.client_org or i.organization
                rows.append({'part': 'incident', 'kind': f'{i.get_severity_display()} incident', 'id': i.pk,
                             'label': f'INC-{i.pk}', 'title': i.title, 'client_name': cust.name,
                             'opened': i.opened_at, 'url': _url('security_alerts:incident_detail', i.pk)})
        p1 = len(rows) - incidents
        return Collected(value=len(rows), rows=rows,
                         breakdown=[{'label': 'Open P1 tickets', 'value': p1, 'part': 'p1'},
                                    {'label': 'Security incidents', 'value': incidents, 'part': 'incident'}],
                         is_complete=not reasons, unknown_reason='; '.join(reasons), notes=notes)


# -- risk ----------------------------------------------------------------------

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
        return 'view_backup_status' if _perm_known('view_backup_status') else 'monitoring_view'

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
            kind = getattr(a, 'kind', '')
            kinds[kind or 'other'] = kinds.get(kind or 'other', 0) + 1
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
        qs = sub.objects.filter(status__in=self.LIVE, renewal_date__gte=today,
                                renewal_date__lte=today + timedelta(days=90))
        qs = limit_to(qs, 'organization', ids)
        rows, unpriced = [], 0
        for s in qs.select_related('organization', 'product').order_by('renewal_date', 'pk'):
            value = None
            if s.unit_price is None:
                unpriced += 1
            else:
                value = _money(Decimal(str(s.unit_price)) * s.quantity_purchased)
            rows.append({'id': s.pk, 'label': str(getattr(s, 'product', '') or s.pk),
                         'client_name': s.organization.name, 'renewal_date': s.renewal_date,
                         'days_left': (s.renewal_date - today).days, 'quantity': s.quantity_purchased,
                         'value': value, 'url': ''})
        breakdown = [{'label': f'{w} days', 'unit': 'currency',
                      'value': sum((r['value'] or ZERO for r in rows if r['days_left'] <= w), ZERO)}
                     for w in (30, 60, 90)]
        return Collected(value=sum((r['value'] or ZERO for r in rows), ZERO), rows=rows, breakdown=breakdown,
                         is_complete=not unpriced,
                         unknown_reason=f'{unpriced} subscriptions have no customer price' if unpriced else '',
                         secondary=f'{len(rows)} subscriptions renewing')


PROVIDERS = tuple(sorted((
    MrrArr(), RevenueTrend(), GrossMargin(), CustomerProfitability(), CustomerGrowth(),
    ContractRenewals(), OutstandingQuotes(), UnbilledWork(), AccountsReceivable(),
    TechnicianUtilization(), SlaAttainment(), TicketBacklog(), CriticalIssues(),
    SecurityIssues(), BackupFailures(), ProcurementStatus(), LicensingRenewals(),
), key=lambda p: p.order))
REGISTRY = {p.key: p for p in PROVIDERS}
assert all(set(p.supported_filters) <= set(ALL_FILTERS) for p in PROVIDERS)


def get(key):
    return REGISTRY.get(key)
