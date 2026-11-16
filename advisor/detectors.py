"""
Detectors: rule classes in a registry. Each reads a customer's facts and the
customer's thresholds (AdvisorSettings) and returns zero or more `Raised`
results; the engine (advisor.engine) stores them as Findings.

Rules every detector follows:

  * A conclusion is only drawn from complete figures, or from a bound that
    makes it certain (costs are never negative, so revenue minus the costs we
    know is an upper bound on profit). Otherwise the result is "incomplete":
    stored as information with the missing inputs, never as a loss.
  * A detector whose data source is not installed is not evaluated, and says
    so (`availability()`), instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List

from . import inputs
from .facts import HUNDRED, ZERO, CustomerFacts, Fact, money_str, q2, url
from .recommend import (RecSpec, ceil_hours, fact_inp, inp, main_recurring_contract, price_change,
                        price_for_margin, required_monthly_for_target, work)


@dataclass
class Context:
    client: object
    settings: object
    window: object
    facts: CustomerFacts
    prior: CustomerFacts
    today: object


@dataclass
class Raised:
    severity: str
    title: str
    summary: str
    facts: List[Fact]
    evidence: dict = field(default_factory=dict)
    subject_key: str = ''
    assessment: str = 'raised'
    is_complete: bool = True
    missing: List[str] = field(default_factory=list)
    recommendations: List[RecSpec] = field(default_factory=list)


class Detector:
    key = ''
    label = ''
    description = ''

    def availability(self):
        """(True, '') when this detector can run on this install, else (False, why)."""
        return True, ''

    def evaluate(self, ctx: Context) -> List[Raised]:  # pragma: no cover - abstract
        raise NotImplementedError


REGISTRY: Dict[str, Detector] = {}


def register(cls):
    REGISTRY[cls.key] = cls()
    return cls


def _pct(v):
    return 'unknown' if v is None else f'{q2(v):.2f}%'


def _money(v):
    return 'unknown' if v is None else f'${q2(v):,.2f}'


def _contract_record(c):
    return [{'label': c.name, 'model': 'psa.Contract', 'id': c.pk, 'url': url('psa:contract_detail', c.pk)}]


def _margin_price_recs(ctx, key_prefix, cost_fact, revenue_fact, rec_type, title_word, minimum=False):
    """Price needed on the main recurring contract (or a quote) for the
    customer's window cost to leave the target margin."""
    s, w, f = ctx.settings, ctx.window, ctx.facts
    cost = cost_fact.value if cost_fact.value is not None else cost_fact.lower
    if cost is None or cost <= 0:
        return []
    monthly_cost, required = required_monthly_for_target(cost, w.months, s.target_margin_pct)
    if required is None:
        return []
    current_monthly = q2(revenue_fact.value / w.months) if revenue_fact.value is not None else None
    contract = main_recurring_contract(f.active_contracts())
    unknown = [] if cost_fact.is_complete else (
        ['Some costs are unknown: this is the MINIMUM price, based on the costs that are known.']
        + list(cost_fact.missing))
    steps = [
        f'Monthly cost = {_money(cost)} ÷ {w.months} months = {_money(monthly_cost)}',
        f'Required monthly revenue = {_money(monthly_cost)} ÷ (1 − {q2(s.target_margin_pct)}%) = {_money(required)}',
    ]
    assumptions = [f'Target gross margin {q2(s.target_margin_pct)}% (advisor settings).',
                   f'Costs of the last {w.months} months ({w.label}) continue at the same level.']
    inputs_ = [fact_inp(cost_fact), fact_inp(revenue_fact),
               inp('Target margin', s.target_margin_pct, 'pct', 'verified', note='advisor settings')]
    if contract is not None:
        current = inputs.monthly_amount(contract)
        other = q2((current_monthly or ZERO) - current) if current_monthly is not None else ZERO
        proposed = q2(max(current, required - max(other, ZERO)))
        steps.append(f'Other monthly revenue = {_money(current_monthly)} − contract {_money(current)} = '
                     f'{_money(max(other, ZERO))}')
        steps.append(f'Proposed contract amount = max({_money(current)}, {_money(required)} − '
                     f'{_money(max(other, ZERO))}) = {_money(proposed)} per month')
        inputs_.append(inp(f'Current monthly amount of {contract.name}', current, records=_contract_record(contract),
                           note='contract terms'))
        if proposed <= current:
            return []
        return [price_change(
            f'{key_prefix}:contract:{contract.pk}', rec_type,
            f'{title_word} {contract.name} to {_money(proposed)}/month',
            'Bring the customer to the target margin by raising the main recurring contract.',
            contract=contract, current=current, proposed=proposed, unit='per month',
            formula='required monthly revenue = monthly cost ÷ (1 − target margin)', steps=steps, inputs=inputs_,
            assumptions=assumptions, unknown=unknown, minimum=minimum or not cost_fact.is_complete)]
    steps.append(f'No recurring contract: propose a monthly agreement of {_money(required)}')
    return [price_change(
        f'{key_prefix}:quote', 'renegotiate' if rec_type == 'price_increase' else rec_type,
        f'Quote a monthly agreement of {_money(required)}',
        'The customer has no recurring contract to adjust; quote one that covers cost at the target margin.',
        contract=None, current=current_monthly, proposed=required, unit='per month',
        formula='required monthly revenue = monthly cost ÷ (1 − target margin)', steps=steps, inputs=inputs_,
        assumptions=assumptions, unknown=unknown, minimum=minimum or not cost_fact.is_complete)]


def fixable_missing(f):
    """Missing cost inputs someone can fill in (cost rates, license unit costs).
    Costs from a module this install does not have are not listed: there is
    nothing to fix, and they are stated on the coverage panel instead."""
    out = [m for part in (f.labor(), f.hardware(), f.delivery()) for m in part.missing]
    if inputs.licensing_installed():
        out += f.licensing().missing
    return out


# --- 1. loss-making customer -------------------------------------------------------

@register
class LossMakingCustomer(Detector):
    key = 'loss_making_customer'
    label = 'Loss-making customer'
    description = 'Gross margin below the loss threshold over the window.'

    def evaluate(self, ctx):
        f, s = ctx.facts, ctx.settings
        rev, cost, gm, gp = f.revenue(), f.total_cost(), f.gross_margin(), f.gross_profit()
        facts = [rev, f.labor(), f.licensing(), f.hardware(), f.delivery(), cost, gp, gm]
        threshold = Decimal(str(s.loss_margin_pct))
        has_activity = bool(rev.value) or bool(cost.lower)
        if not has_activity:
            return []
        if not rev.value:
            # Costs with no revenue at all: a loss whatever the unknown costs are.
            certain_loss = bool(cost.lower and cost.lower > 0)
            if not certain_loss:
                return []
            margin_text = f'no invoiced revenue against at least {_money(cost.lower)} of cost'
        elif gm.is_complete:
            if gm.value >= threshold:
                return []
            margin_text = f'gross margin {_pct(gm.value)} on revenue {_money(rev.value)}'
        elif gm.upper is not None and gm.upper < threshold:
            margin_text = (f'gross margin at most {_pct(gm.upper)} on revenue {_money(rev.value)} '
                           '(some costs unknown; the true margin is lower)')
        else:
            if not fixable_missing(f):
                # Only costs this install does not track are missing: nothing to fix, and no
                # conclusion either way. The coverage panel states that vendor costs are untracked.
                return []
            return [Raised(
                severity='info', assessment='incomplete', is_complete=False, missing=list(cost.missing),
                title=f'Margin of {ctx.client.name} cannot be evaluated: cost inputs missing',
                summary=(f'Revenue {_money(rev.value)} over {ctx.window.label}. Known costs {_money(cost.lower)} '
                         f'leave at most {_pct(gm.upper)}, but {len(cost.missing)} cost input(s) are missing, so '
                         'the advisor does not say whether this customer is profitable.'),
                facts=facts, evidence={'threshold_pct': money_str(threshold)})]
        loss = gp.value if gp.value is not None else gp.upper
        severity = 'critical' if (loss is not None and rev.value and loss < -(rev.value * Decimal('0.25'))) else 'high'
        recs = _margin_price_recs(ctx, 'price_increase', cost, rev, 'price_increase', 'Raise')
        return [Raised(
            severity=severity, is_complete=cost.is_complete, missing=list(cost.missing),
            title=f'{ctx.client.name} is loss-making ({ctx.window.label})',
            summary=f'{ctx.client.name}: {margin_text}. Threshold: {_pct(threshold)}.',
            facts=facts, evidence={'threshold_pct': money_str(threshold),
                                   'gross_profit': money_str(loss)},
            recommendations=recs)]


# --- 2. declining margin -------------------------------------------------------

@register
class DecliningMargin(Detector):
    key = 'declining_margin'
    label = 'Declining margin'
    description = 'Margin dropped by more than the configured points versus the prior period.'

    def evaluate(self, ctx):
        f, p, s = ctx.facts, ctx.prior, ctx.settings
        now_g, before_g = f.gross_margin(), p.gross_margin()
        if now_g.value is not None and before_g.value is not None:
            now, before, kind, complete, missing = now_g, before_g, 'gross margin', True, []
        else:
            now, before = f.labor_margin(), p.labor_margin()
            if now.value is None or before.value is None:
                return []
            kind, complete = 'margin after labour', False
            missing = ['Vendor, hardware or delivery costs are incomplete, so labour-only margin is compared.'] \
                + [m for m in now_g.missing + before_g.missing if m not in now.missing]
        drop = q2(before.value - now.value)
        if drop < Decimal(str(s.margin_decline_pts)):
            return []
        prior_fact = Fact(f'prior_{now.key}', f'{now.label} (prior period {ctx.window.prior().label})', 'pct',
                          before.value, before.basis, source=before.source)
        severity = 'high' if now.value < Decimal(str(s.target_margin_pct)) else 'medium'
        recs = []
        if now.value < Decimal(str(s.target_margin_pct)):
            cost_fact = f.total_cost() if complete else f.labor()
            recs = _margin_price_recs(ctx, 'renegotiate', cost_fact, f.revenue(), 'renegotiate', 'Renegotiate')
        return [Raised(
            severity=severity, is_complete=complete, missing=missing,
            title=f'{ctx.client.name}: {kind} down {q2(drop)} points',
            summary=(f'{kind.capitalize()} fell from {_pct(before.value)} ({ctx.window.prior().label}) to '
                     f'{_pct(now.value)} ({ctx.window.label}), a drop of {q2(drop)} points '
                     f'(threshold {q2(s.margin_decline_pts)}).'),
            facts=[f.revenue(), p.revenue(), now, prior_fact, f.labor()],
            evidence={'drop_pts': money_str(drop), 'compared': kind}, recommendations=recs)]


# --- 3. underpriced contract -------------------------------------------------------

@register
class UnderpricedContract(Detector):
    key = 'underpriced_contract'
    label = 'Underpriced contract'
    description = 'Effective rate (revenue ÷ hours) below cost or below the rate that gives the target margin.'

    def evaluate(self, ctx):
        f, s, w = ctx.facts, ctx.settings, ctx.window
        out = []
        for row in f.contract_rows():
            c, hours = row['contract'], row['hours']
            if not hours or row['effective_rate'] is None:
                continue
            eff = row['effective_rate']
            if row['cost_complete']:
                cost_rate = row['cost_rate']
                target_rate = price_for_margin(cost_rate, s.target_margin_pct)
                if eff < cost_rate:
                    severity, verdict = 'high', f'below cost ({_money(cost_rate)}/h)'
                elif target_rate is not None and eff < target_rate:
                    severity, verdict = 'medium', f'below the target-margin rate ({_money(target_rate)}/h)'
                else:
                    continue
                missing, complete = [], True
            else:
                floor = q2(row['cost_known_part'] / hours)
                if eff >= floor:
                    continue  # cannot tell without the missing cost rates
                severity, verdict = 'high', f'below the known part of cost alone ({_money(floor)}/h)'
                cost_rate, target_rate, complete = floor, price_for_margin(floor, s.target_margin_pct), False
                missing = [f"{row['unknown_cost_hours']} h on this contract have no cost rate; figures are minimums."]
            rev_fact = Fact('contract_revenue', f'Revenue of {c.name}', 'money', row['revenue'],
                            row['revenue_basis'], records=row['invoice_records'] or _contract_record(c),
                            note='' if row['revenue_basis'] == 'verified' else
                            'No invoice in the window: expected recurring amount used.')
            hours_fact = Fact('contract_hours', f'Hours on {c.name}', 'hours', hours, 'verified',
                              records=_contract_record(c))
            cost_fact = Fact('contract_cost', f'Labour cost of {c.name}', 'money', row['cost'], 'estimate',
                             is_complete=complete, missing=missing, lower=row['cost_known_part'])
            eff_fact = Fact('effective_rate', 'Effective rate (revenue ÷ hours)', 'money', eff, 'estimate')
            recs = self._recs(ctx, row, cost_rate, target_rate, complete, missing, [rev_fact, hours_fact, cost_fact])
            out.append(Raised(
                severity=severity, subject_key=f'contract:{c.pk}', is_complete=complete, missing=missing,
                title=f'{c.name} is underpriced: {_money(eff)}/h effective',
                summary=(f'{c.name} earned {_money(row["revenue"])} for {hours} h over {w.label}: an effective '
                         f'rate of {_money(eff)}/h, {verdict}.'),
                facts=[rev_fact, hours_fact, cost_fact, eff_fact],
                evidence={'effective_rate': money_str(eff), 'cost_rate': money_str(cost_rate),
                          'target_rate': money_str(target_rate)},
                recommendations=recs))
        return out

    def _recs(self, ctx, row, cost_rate, target_rate, complete, missing, facts):
        s, w, c = ctx.settings, ctx.window, row['contract']
        recs = []
        unknown = [] if complete else ['Cost is partly unknown: proposed figures are minimums.'] + missing
        base_inputs = [fact_inp(x) for x in facts] + [
            inp('Target margin', s.target_margin_pct, 'pct', note='advisor settings')]
        assumptions = [f'Target gross margin {q2(s.target_margin_pct)}%.',
                       f'Hours of {w.label} continue at the same level.']
        cost = row['cost'] if row['cost'] is not None else row['cost_known_part']
        if row['monthly'] is not None:
            monthly_cost, required = required_monthly_for_target(cost, w.months, s.target_margin_pct)
            if required is not None and required > row['monthly']:
                recs.append(price_change(
                    f'price_increase:contract:{c.pk}', 'price_increase',
                    f'Raise {c.name} to {_money(required)}/month', 'Cover delivery cost at the target margin.',
                    contract=c, current=row['monthly'], proposed=required, unit='per month',
                    formula='proposed monthly amount = monthly labour cost ÷ (1 − target margin)',
                    steps=[f'Monthly labour cost = {_money(cost)} ÷ {w.months} = {_money(monthly_cost)}',
                           f'Proposed = {_money(monthly_cost)} ÷ (1 − {q2(s.target_margin_pct)}%) = {_money(required)}'],
                    inputs=base_inputs + [inp('Current monthly amount', row['monthly'], records=_contract_record(c))],
                    assumptions=assumptions, unknown=unknown, minimum=not complete))
                devices = ctx.facts.device_count()
                if devices:
                    per_device = q2(required / devices)
                    recs.append(price_change(
                        f'per_device_price:contract:{c.pk}', 'per_device_price',
                        f'Price {c.name} per device: {_money(per_device)}/device/month',
                        'A per-device price grows with the estate the customer asks you to support.',
                        contract=c, current=q2(row['monthly'] / devices), proposed=per_device,
                        unit='per device per month', field_name='per_device_price',
                        formula='per-device price = required monthly amount ÷ managed devices',
                        steps=[f'{_money(required)} ÷ {devices} devices = {_money(per_device)}'],
                        inputs=base_inputs + [inp('Managed devices (assets)', devices, 'count')],
                        assumptions=assumptions + ['Every asset recorded for the customer is a billable device.'],
                        unknown=unknown, minimum=not complete))
        elif target_rate is not None and (c.hourly_rate or 0) < target_rate:
            recs.append(price_change(
                f'price_increase:hourly:{c.pk}', 'price_increase',
                f'Raise the hourly rate of {c.name} to {_money(target_rate)}/h',
                'Bill hours at a rate that covers cost at the target margin.', contract=c,
                current=c.hourly_rate or None, proposed=target_rate, unit='per hour', field_name='hourly_rate',
                formula='proposed hourly rate = cost per hour ÷ (1 − target margin)',
                steps=[f'Cost per hour = {_money(cost)} ÷ {row["hours"]} h = {_money(cost_rate)}',
                       f'Proposed = {_money(cost_rate)} ÷ (1 − {q2(s.target_margin_pct)}%) = {_money(target_rate)}'],
                inputs=base_inputs, assumptions=assumptions, unknown=unknown, minimum=not complete))
        share, after, total = ctx.facts.after_hours_share()
        if share is not None and share >= Decimal(str(s.after_hours_share_pct)) and target_rate is not None:
            recs.append(price_change(
                f'after_hours_rate:contract:{c.pk}', 'after_hours_rate',
                f'Bill after-hours work on {c.name} at {_money(target_rate)}/h or more',
                f'{_pct(share)} of the hours were worked outside business hours.', contract=c,
                current=c.overage_rate or c.hourly_rate or None, proposed=target_rate, unit='per hour',
                field_name='after_hours_rate',
                formula='after-hours rate ≥ cost per hour ÷ (1 − target margin)',
                steps=[f'After-hours share = {after} h ÷ {total} h = {_pct(share)}',
                       f'Minimum after-hours rate = {_money(target_rate)}/h'],
                inputs=base_inputs + [inp('After-hours hours', after, 'hours'), inp('All hours', total, 'hours')],
                assumptions=[f'Business hours {s.business_hours_start}:00–{s.business_hours_end}:00 on weekdays.',
                             'No premium over the target-margin rate is assumed; set one in the draft if you charge it.'],
                unknown=unknown, minimum=True))
        return recs


# --- 4/7. allowance usage --------------------------------------------------------

def _allowance_rows(ctx):
    for c in ctx.facts.active_contracts():
        allowance = ctx.facts.monthly_allowance_hours(c)
        if allowance is None or allowance <= 0:
            continue
        yield c, q2(allowance), ctx.facts.contract_month_usage(c)


@register
class SupportOverContract(Detector):
    key = 'support_over_contract'
    label = 'Support above contract'
    description = 'Hours above the included hours by the configured percent for the configured number of months.'

    def evaluate(self, ctx):
        s = ctx.settings
        limit_factor = Decimal('1') + Decimal(str(s.overage_pct)) / HUNDRED
        out = []
        for c, allowance, months in _allowance_rows(ctx):
            over = [(m, h) for m, h in months if h > allowance * limit_factor]
            if len(over) < s.overage_months:
                continue
            avg = q2(sum((h for _m, h in months), ZERO) / len(months))
            severity = 'high' if len(over) == len(months) else 'medium'
            usage = Fact('monthly_usage', f'Hours per month on {c.name}', 'hours', avg, 'verified',
                         records=_contract_record(c),
                         note='; '.join(f'{m:%b %Y}: {h} h' for m, h in months))
            incl = Fact('included_hours', 'Included hours per month', 'hours', allowance, 'verified',
                        records=_contract_record(c), note='contract total hours ÷ billing period months')
            recs = []
            monthly = inputs.monthly_amount(c)
            new_hours = ceil_hours(avg)
            if monthly is not None:
                per_hour = q2(monthly / allowance)
                proposed = q2(new_hours * per_hour)
                recs.append(price_change(
                    f'upsell:contract:{c.pk}', 'upsell',
                    f'Offer {c.name} with {new_hours} included hours at {_money(proposed)}/month',
                    'The customer consistently uses more support than the contract includes.', contract=c,
                    current=monthly, proposed=proposed, unit='per month',
                    formula='proposed = hours actually used (rounded up) × the contract\'s own price per included hour',
                    steps=[f'Price per included hour = {_money(monthly)} ÷ {allowance} h = {_money(per_hour)}',
                           f'Average use {avg} h → {new_hours} h; {new_hours} × {_money(per_hour)} = {_money(proposed)}'],
                    inputs=[fact_inp(usage), fact_inp(incl), inp('Current monthly amount', monthly,
                                                                   records=_contract_record(c))],
                    assumptions=['The current price per included hour is kept.',
                                 'Use in the window continues at the same level.'],
                    extra={'included_hours': str(new_hours)}))
            out.append(Raised(
                severity=severity, subject_key=f'contract:{c.pk}',
                title=f'{c.name}: support above contract in {len(over)} of {len(months)} months',
                summary=(f'{c.name} includes {allowance} h a month; usage exceeded it by more than '
                         f'{q2(s.overage_pct)}% in {len(over)} month(s) (average {avg} h).'),
                facts=[usage, incl], evidence={'months_over': len(over), 'months': len(months)},
                recommendations=recs))
        return out


@register
class UnusedAllowance(Detector):
    key = 'unused_allowance'
    label = 'Unused allowance'
    description = 'Average use of included hours below the configured percent.'

    def evaluate(self, ctx):
        s = ctx.settings
        out = []
        for c, allowance, months in _allowance_rows(ctx):
            avg = q2(sum((h for _m, h in months), ZERO) / len(months))
            pct = q2(avg / allowance * HUNDRED)
            if pct >= Decimal(str(s.unused_allowance_pct)):
                continue
            usage = Fact('monthly_usage', f'Hours per month on {c.name}', 'hours', avg, 'verified',
                         records=_contract_record(c), note='; '.join(f'{m:%b %Y}: {h} h' for m, h in months))
            incl = Fact('included_hours', 'Included hours per month', 'hours', allowance, 'verified',
                        records=_contract_record(c))
            recs = []
            monthly = inputs.monthly_amount(c)
            new_hours = max(ceil_hours(avg), Decimal('1'))
            if monthly is not None:
                per_hour = q2(monthly / allowance)
                proposed = q2(new_hours * per_hour)
                recs.append(price_change(
                    f'bundle_review:contract:{c.pk}', 'bundle_review',
                    f'Review the {c.name} bundle: {new_hours} included hours at {_money(proposed)}/month',
                    'Hours paid for but not used are a renewal risk; right-size the bundle or add services.',
                    contract=c, current=monthly, proposed=proposed, unit='per month',
                    formula='proposed = hours actually used (rounded up) × the contract\'s own price per included hour',
                    steps=[f'Price per included hour = {_money(monthly)} ÷ {allowance} h = {_money(per_hour)}',
                           f'{new_hours} h × {_money(per_hour)} = {_money(proposed)}'],
                    inputs=[fact_inp(usage), fact_inp(incl), inp('Current monthly amount', monthly,
                                                                   records=_contract_record(c))],
                    assumptions=['A smaller bundle keeps the same price per hour; a review may instead add services.'],
                    extra={'included_hours': str(new_hours)}))
            out.append(Raised(
                severity='low', subject_key=f'contract:{c.pk}',
                title=f'{c.name}: {_pct(pct)} of included hours used',
                summary=(f'{c.name} includes {allowance} h a month but averaged {avg} h over '
                         f'{ctx.window.label} ({_pct(pct)}; threshold {_pct(s.unused_allowance_pct)}).'),
                facts=[usage, incl], evidence={'use_pct': money_str(pct)}, recommendations=recs))
        return out


# --- 5. unbilled work -----------------------------------------------------------------

@register
class UnbilledWork(Detector):
    key = 'unbilled_work'
    label = 'Unbilled work'
    description = 'Billable work not on any invoice (beyond allowances and flat fees).'

    def evaluate(self, ctx):
        s = ctx.settings
        fact = ctx.facts.unbilled()
        amount = fact.value if fact.value is not None else fact.lower
        threshold = Decimal(str(s.unbilled_min_amount))
        if amount is None or amount < threshold:
            if fact.is_complete or not fact.missing:
                return []
            return [Raised(
                severity='info', assessment='incomplete', is_complete=False, missing=list(fact.missing),
                title=f'{ctx.client.name}: unbilled work cannot be valued',
                summary=f'Unbilled billable work has no bill rate: {"; ".join(fact.missing)}',
                facts=[fact])]
        severity = 'high' if amount >= threshold * 5 else 'medium'
        prefix = 'at least ' if not fact.is_complete else ''
        return [Raised(
            severity=severity, is_complete=fact.is_complete, missing=list(fact.missing),
            title=f'{ctx.client.name}: {prefix}{_money(amount)} of billable work not invoiced',
            summary=(f'{prefix.capitalize()}{_money(amount)} of billable work is on no invoice. Invoice it from the '
                     'ticket or contract; nothing else needs to change.'),
            facts=[fact], evidence={'threshold': money_str(threshold)})]


# --- 6. service without charge ----------------------------------------------------------

@register
class ServiceWithoutCharge(Detector):
    key = 'service_without_charge'
    label = 'Service delivered without a charge'
    description = 'Billable work on tickets with no covering contract and no invoice.'

    def evaluate(self, ctx):
        s, f, w = ctx.settings, ctx.facts, ctx.window
        hours = f.leakage_hours()
        if hours.value is None or hours.value < Decimal(str(s.leakage_min_hours)):
            return []
        amount = f.leakage()
        recs = []
        split = f._billing_split()
        leaked_cost = split['leak_cost']
        cost_known = not split['leak_cost_unknown_hours']
        monthly_hours = q2(hours.value / w.months)
        if cost_known and leaked_cost > 0:
            monthly_cost, required = required_monthly_for_target(leaked_cost, w.months, s.target_margin_pct)
            recs.append(price_change(
                'upsell:support_agreement', 'upsell',
                f'Quote a support agreement of {_money(required)}/month',
                'Work is being delivered with no contract; an agreement makes it billable.', contract=None,
                current=None, proposed=required, unit='per month',
                formula='proposed = monthly cost of the uncharged work ÷ (1 − target margin)',
                steps=[f'Cost of uncharged work = {_money(leaked_cost)} over {w.months} months = {_money(monthly_cost)}/month',
                       f'{_money(monthly_cost)} ÷ (1 − {q2(s.target_margin_pct)}%) = {_money(required)}'],
                inputs=[fact_inp(hours), inp('Labour cost of that work', leaked_cost, basis='estimate'),
                        inp('Target margin', s.target_margin_pct, 'pct')],
                assumptions=[f'About {monthly_hours} h a month of this work continues.']))
        else:
            recs.append(RecSpec(
                'upsell:support_agreement', 'upsell', 'Quote a support agreement for this work',
                'Work is being delivered with no contract. No price is proposed because the cost of the work '
                'is not fully known.',
                {'field': 'recurring_amount', 'unit': 'per month', 'current': None, 'proposed': None,
                 'change': None, 'change_pct': None, 'is_minimum': False},
                work('no price computed', [f'{hours.value} h over {w.months} months = {monthly_hours} h/month'],
                     [fact_inp(hours)], unknown=['Cost of the uncharged work (technician cost rates missing).'])))
        return [Raised(
            severity='medium', is_complete=amount.is_complete, missing=list(amount.missing),
            title=f'{ctx.client.name}: {hours.value} h of billable work with no contract or charge',
            summary=(f'{hours.value} billable hours over {w.label} were on tickets with no covering contract and '
                     'have not been invoiced.'),
            facts=[hours, amount], evidence={'hours': money_str(hours.value)}, recommendations=recs)]


# --- 8. renewal review --------------------------------------------------------------------

@register
class RenewalReview(Detector):
    key = 'renewal_review'
    label = 'Renewal to review'
    description = 'Contract renews within the window (default 60–90 days) with margin below target.'

    def evaluate(self, ctx):
        from datetime import timedelta
        s, f = ctx.settings, ctx.facts
        lo, hi = ctx.today + timedelta(days=s.renewal_min_days), ctx.today + timedelta(days=s.renewal_max_days)
        due = [c for c in f.active_contracts() if c.end_date and lo <= c.end_date <= hi]
        if not due:
            return []
        gm, lm = f.gross_margin(), f.labor_margin()
        target = Decimal(str(s.target_margin_pct))
        out = []
        for c in due:
            days = (c.end_date - ctx.today).days
            if gm.value is not None:
                margin, complete, missing, kind = gm.value, True, [], 'gross margin'
            elif gm.upper is not None and gm.upper < target:
                margin, complete, missing, kind = gm.upper, False, list(gm.missing), 'gross margin (at most)'
            else:
                if f.revenue().value and not fixable_missing(f):
                    continue
                out.append(Raised(
                    severity='info', assessment='incomplete', subject_key=f'contract:{c.pk}', is_complete=False,
                    missing=list(gm.missing) or ['No invoiced revenue in the window.'],
                    title=f'{c.name} renews in {days} days: margin unknown',
                    summary=(f'{c.name} ends {c.end_date:%Y-%m-%d}. The margin cannot be evaluated, so review the '
                             'price before renewal with the missing costs filled in.'),
                    facts=[f.revenue(), f.total_cost(), gm, lm]))
                continue
            if margin >= target:
                continue
            cost_fact = f.total_cost()
            recs = _margin_price_recs(ctx, 'renegotiate', cost_fact, f.revenue(), 'renegotiate', 'Renew')
            for r in recs:
                r.key = f'renegotiate:renewal:{c.pk}' if r.contract is None else r.key
            out.append(Raised(
                severity='high' if margin < 0 else 'medium', subject_key=f'contract:{c.pk}',
                is_complete=complete, missing=missing,
                title=f'{c.name} renews in {days} days at {_pct(margin)} margin',
                summary=(f'{c.name} ends {c.end_date:%Y-%m-%d} ({days} days). The customer\'s {kind} over '
                         f'{ctx.window.label} is {_pct(margin)}, below the {_pct(target)} target.'),
                facts=[f.revenue(), cost_fact, gm, Fact('renewal_date', f'Contract end date: {c.end_date:%Y-%m-%d}',
                                                         'count', None, 'not_applicable',
                                                         note=f'{c.end_date:%Y-%m-%d}',
                                                         records=_contract_record(c))],
                evidence={'days_to_renewal': days, 'margin_pct': money_str(margin)}, recommendations=recs))
        return out


# --- 9. cost increase not passed through ------------------------------------------------

@register
class CostIncreaseNotPassedThrough(Detector):
    key = 'cost_increase_not_passed_through'
    label = 'Cost increase not passed through'
    description = 'A price book item this customer buys rose in cost with no matching price change.'

    def availability(self):
        if inputs.cost_history_available():
            return True, ''
        return False, ('Not evaluated: no cost history on this install (needs the price book cost history; '
                       'distributor prices are looked up live and not stored).')

    def evaluate(self, ctx):
        s, w = ctx.settings, ctx.window
        out = []
        # Increases from the start of the window up to today: a recent one matters most.
        for inc in inputs.cost_increases(ctx.client, w.start, ctx.today):
            pct = q2((inc['new_cost'] - inc['old_cost']) / inc['old_cost'] * HUNDRED)
            if inc['price_changed_since'] or pct < Decimal(str(s.cost_increase_pct)):
                continue
            recs = []
            price = inc['price']
            if price is not None:
                proposed = q2(price * inc['new_cost'] / inc['old_cost'])
                recs.append(price_change(
                    f"price_increase:item:{inc['item_id']}", 'price_increase',
                    f"Raise {inc['item']} to {_money(proposed)}",
                    'Keep the same markup after the supplier\'s cost increase.', contract=None, current=price,
                    proposed=proposed, unit='per unit', field_name='unit_price',
                    formula='proposed price = current price × new cost ÷ old cost',
                    steps=[f"{_money(price)} × {_money(inc['new_cost'])} ÷ {_money(inc['old_cost'])} = {_money(proposed)}"],
                    inputs=[inp('Current price', price), inp('Old unit cost', inc['old_cost']),
                            inp('New unit cost', inc['new_cost'])],
                    assumptions=['The current markup is the intended one.']))
            out.append(Raised(
                severity='medium', subject_key=f"item:{inc['item_id']}",
                title=f"{inc['item']}: cost up {_pct(pct)}, price unchanged",
                summary=(f"Unit cost of {inc['item']} rose from {_money(inc['old_cost'])} to "
                         f"{_money(inc['new_cost'])} on {inc['changed_at']:%Y-%m-%d} with no price change since."),
                facts=[Fact('old_cost', 'Old unit cost', 'money', inc['old_cost']),
                       Fact('new_cost', 'New unit cost', 'money', inc['new_cost']),
                       Fact('price', 'Current price', 'money', price, 'verified' if price is not None else 'unknown',
                            is_complete=price is not None)],
                evidence={'increase_pct': money_str(pct)}, recommendations=recs))
        return out


# --- 10. tier fit ------------------------------------------------------------------------

@register
class TierFit(Detector):
    key = 'tier_fit'
    label = 'Plan tier fit'
    description = 'Consumption suggests a higher service plan.'

    def availability(self):
        if inputs.pricing_installed():
            return True, ''
        return False, 'Not evaluated: service plans (price book) are not installed.'

    def evaluate(self, ctx):
        s, f, w = ctx.settings, ctx.facts, ctx.window
        out = []
        hours_total = f.total_hours()
        for sub in inputs.service_plans(ctx.client):
            plan = sub.plan
            included = plan.included_support_hours
            if not included:
                continue
            per_month = q2(hours_total / w.months) if hours_total else ZERO
            if per_month < included * Decimal(str(s.tier_fit_pct)) / HUNDRED:
                continue
            candidates = [p for p in inputs.higher_plans(plan) if p.included_support_hours >= per_month]
            target = candidates[0] if candidates else None
            recs = []
            current_price = sub.monthly_price if sub.monthly_price is not None else plan.monthly_price
            if target is not None:
                recs.append(price_change(
                    f'tier_change:plan:{sub.pk}', 'tier_change',
                    f'Move to {target.name} ({target.included_support_hours} h included)',
                    'The next plan up covers the hours actually used.', contract=getattr(sub, 'contract', None),
                    current=current_price, proposed=target.monthly_price, unit='per month',
                    field_name='service_plan',
                    formula='smallest plan whose included hours ≥ average monthly use',
                    steps=[f'Average use {per_month} h ≥ {q2(s.tier_fit_pct)}% of {included} h',
                           f'{target.name} includes {target.included_support_hours} h'],
                    inputs=[inp('Average hours per month', per_month, 'hours'),
                            inp(f'{plan.name} included hours', included, 'hours'),
                            inp(f'{plan.name} monthly price (this customer)', current_price,
                                basis='verified' if current_price is not None else 'unknown'),
                            inp(f'{target.name} monthly price', target.monthly_price,
                                basis='verified' if target.monthly_price is not None else 'unknown')],
                    unknown=[] if (current_price is not None and target.monthly_price is not None)
                    else ['A plan has no monthly price; the price change is not computed.']))
            out.append(Raised(
                severity='medium', subject_key=f'plan:{sub.pk}',
                title=f'{ctx.client.name} uses {per_month} h/month on {plan.name} ({included} h included)',
                summary=f'Consumption is at least {q2(s.tier_fit_pct)}% of what {plan.name} includes.',
                facts=[Fact('hours_per_month', 'Average hours per month', 'hours', per_month)],
                evidence={'plan': plan.name}, recommendations=recs))
        return out
