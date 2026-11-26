"""
Price, labor-rate and cost-rate resolution.

Every resolver returns a result object. When nothing applies it returns
`missing=True` (or `unknown=True` for cost) with a human-readable `reason`;
it NEVER substitutes a made-up number. The legacy fallbacks elsewhere
(reports.queries DEFAULT_LOADED_RATE = 60, DEFAULT_BILL_RATE = 150, the 60%
placeholder in psa.Contract.profitability_snapshot, and
resourcing.TechCostRate.rate_for) are left as they are for their existing
callers; new code should use these resolvers instead.

Precedence

  resolve_labor_rate:
    1. customer + contract rate card   (RateCard with client_org AND contract)
    2. customer rate card              (client_org only)
    3. contract rate card              (contract only)
    4. MSP-wide default rate card      (neither)
    5. explicitly configured default   (LaborRole.default_bill_rate)
  Rate cards and roles are MSP-wide unless scoped to a customer; a
  customer's own LaborRole applies only to that customer.
  Within one level, among cards in effect on the date, the card with the
  latest effective_from wins, and within it the most specific matching line
  (role, then technician / skill / service category / location qualifiers).

  resolve_price:
    1. customer + contract override    (CustomerPriceOverride with contract)
    2. customer override               (no contract)
    3. price book item list price      (tiers for tiered / volume items,
                                        pending ScheduledPriceChange applied
                                        for dates on or after its date)

Isolation: one install serves one MSP; `core.Organization` is a customer.
Install-wide books, plans, roles and default rate cards apply to every
customer. Customer-scoped rows (overrides, customer / contract rate cards,
billing rules, a customer's own book or role) apply only to that customer,
and a contract is only honoured for the customer it is with, so customer A
never resolves customer B's prices or rates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from django.db.models import Q
from django.utils import timezone

from .models import (
    ZERO, HUNDRED, BillingRule, CustomerPriceOverride, LaborRole, PriceBookItem, RateCard, RateCardLine,
    ScheduledPriceChange, _in_effect,
)

CENT = Decimal('0.01')
UNIT_PLACES = Decimal('0.0001')


def _q2(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _as_date(on_date):
    if on_date is None:
        return timezone.localdate()
    if isinstance(on_date, datetime):
        if timezone.is_aware(on_date):
            return timezone.localtime(on_date).date()
        return on_date.date()
    return on_date


def _pk(obj):
    return getattr(obj, 'pk', obj)


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------

@dataclass
class PriceResult:
    unit_price: Optional[Decimal] = None      # effective unit price (4 dp for tiered math)
    total: Optional[Decimal] = None           # quantity x price, 2 dp half-up
    quantity: Decimal = Decimal('1')
    unit_cost: Optional[Decimal] = None       # internal; hide without view_internal_cost_rates
    list_price: Optional[Decimal] = None      # the price book price before overrides
    currency: str = ''
    source: str = ''                          # customer_contract_override / customer_override / price_book / tiers
    override: Any = None
    missing: bool = False
    reason: str = ''
    below_minimum: bool = False               # needs pricing_approve_discounts
    minimum_price: Optional[Decimal] = None
    warnings: list = field(default_factory=list)


@dataclass
class LaborRateResult:
    rate: Optional[Decimal] = None
    source: str = ''                          # customer_contract / customer / contract / default / role_default
    rate_card: Any = None
    rate_card_line: Any = None
    role: Any = None
    rate_type: str = 'standard'
    currency: str = ''
    missing: bool = False
    reason: str = ''


@dataclass
class CostRateResult:
    rate: Optional[Decimal] = None
    unknown: bool = False
    reason: str = ''
    source_row: Any = None
    burdened: bool = False


# ---------------------------------------------------------------------------
# Tenancy / contract helpers
# ---------------------------------------------------------------------------

def contract_for_client(client_org, on_date=None):
    """The active psa.Contract with `client_org` covering `on_date` (or None).
    Dated version of psa.Contract.for_ticket (which always uses today)."""
    from psa.models import Contract
    if client_org is None:
        return None
    d = _as_date(on_date)
    return (Contract.objects.filter(client_org_id=_pk(client_org), status='active', start_date__lte=d)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=d))
            .order_by('-start_date', 'pk').first())


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def _scheduled_value(item, field_name, on_date):
    """Value of `field_name` on `on_date`, honouring pending scheduled changes."""
    change = (ScheduledPriceChange.pending().filter(item=item, field=field_name, effective_date__lte=on_date)
              .order_by('-effective_date', '-pk').first())
    return change.new_value if change is not None else getattr(item, field_name)


def tier_total(item, quantity):
    """(total, warnings) for a tiered / volume item, or (None, reason)."""
    tiers = list(item.tiers.all().order_by('min_quantity'))
    if not tiers:
        return None, f'{item.sku} is priced by {item.get_pricing_model_display().lower()} but has no tiers.'
    qty = Decimal(quantity)
    if item.pricing_model == 'volume':
        for t in tiers:
            if qty >= t.min_quantity and (t.max_quantity is None or qty <= t.max_quantity):
                return qty * t.unit_price, None
        return None, f'No volume tier of {item.sku} covers quantity {qty}.'
    # graduated: units are numbered from 1; a band covers [min, max] units.
    total = ZERO
    priced = ZERO
    for t in tiers:
        if priced >= qty:
            break
        band_start = max(t.min_quantity, Decimal('1')) - 1          # units already below this band
        if band_start > priced:
            return None, f'Tiers of {item.sku} leave a gap before quantity {t.min_quantity}.'
        band_end = qty if t.max_quantity is None else min(qty, t.max_quantity)
        units = band_end - priced
        if units > 0:
            total += units * t.unit_price
            priced = band_end
    if priced < qty:
        return None, f'Tiers of {item.sku} stop before quantity {qty}.'
    return total, None


def _contract_mismatch(client, contract):
    return (contract is not None and client is not None
            and contract.client_org_id != _pk(client))


def resolve_price(item, client=None, contract=None, on_date=None, qty=1):
    """Sell price of `item` for `client` (optionally under `contract`) on `on_date`."""
    d = _as_date(on_date)
    quantity = Decimal(str(qty if qty is not None else 1))
    book = item.price_book
    res = PriceResult(quantity=quantity, currency=item.effective_currency)
    if contract is not None and client is None:
        client = contract.client_org
    if not book.applies_to(client):
        res.missing, res.reason = True, 'The item is in another customer\'s own price book.'
        return res
    if _contract_mismatch(client, contract):
        res.missing, res.reason = True, 'The contract is with a different customer.'
        return res
    if not book.is_active:
        res.missing, res.reason = True, f'Price book "{book.name}" is inactive.'
        return res
    if not item.is_active:
        res.missing, res.reason = True, f'{item.sku} is inactive.'
        return res
    if not item.is_in_effect(d):
        res.missing, res.reason = True, f'{item.sku} is not in effect on {d.isoformat()}.'
        return res
    if item.min_quantity is not None and quantity < item.min_quantity:
        res.warnings.append(f'Quantity {quantity} is below the item minimum {item.min_quantity}.')
    if item.max_quantity is not None and quantity > item.max_quantity:
        res.warnings.append(f'Quantity {quantity} is above the item maximum {item.max_quantity}.')

    cost = _scheduled_value(item, 'cost', d)
    list_price = _scheduled_value(item, 'default_price', d)
    minimum = _scheduled_value(item, 'minimum_price', d)
    res.unit_cost, res.list_price, res.minimum_price = cost, list_price, minimum

    unit = None
    total = None
    if client is not None:
        ov_qs = _in_effect(CustomerPriceOverride.objects.filter(
            client_org_id=_pk(client), item=item, is_active=True), d)
        candidates = []
        if contract is not None:
            candidates.append(('customer_contract_override', ov_qs.filter(contract=contract)))
        candidates.append(('customer_override', ov_qs.filter(contract__isnull=True)))
        for source, qs in candidates:
            ov = qs.order_by('-effective_from', '-pk').first()
            if ov is None:
                continue
            res.source, res.override = source, ov
            if ov.unit_price is not None:
                unit = ov.unit_price
            elif cost is None:
                res.missing = True
                res.reason = (f'The customer price for {item.sku} is cost + {ov.markup_pct}% but the item '
                              'has no cost.')
                return res
            else:
                unit = (cost * (1 + ov.markup_pct / HUNDRED)).quantize(UNIT_PLACES, rounding=ROUND_HALF_UP)
            break

    if unit is None:
        if item.pricing_model in PriceBookItem.TIERED_MODELS:
            total, problem = tier_total(item, quantity)
            if total is None:
                res.missing, res.reason = True, problem
                return res
            res.source = 'tiers'
            unit = (total / quantity).quantize(UNIT_PLACES, rounding=ROUND_HALF_UP) if quantity else ZERO
        elif list_price is None:
            res.missing, res.reason = True, f'{item.sku} has no list price.'
            return res
        else:
            res.source = 'price_book'
            unit = list_price

    res.unit_price = unit
    res.total = _q2(total if total is not None else quantity * unit)
    if minimum is not None and unit < minimum:
        res.below_minimum = True
        res.warnings.append(f'Price {unit} is below the minimum {minimum}; needs discount approval.')
    return res


SNAPSHOT_SOURCE_PREFIX = 'pricing:'


def apply_price_to_line(line, item, client=None, contract=None, on_date=None, qty=None, set_unit_price=True):
    """Copy a resolved price onto a QuoteLineItem / InvoiceLineItem /
    ContractBundleItem (does not save). The line keeps these values even if
    the price book changes later: nothing re-resolves an existing line.
    Returns the PriceResult; on `missing` the line's unit_price is left alone."""
    quantity = qty if qty is not None else (getattr(line, 'quantity', None) or 1)
    res = resolve_price(item, client=client, contract=contract, on_date=on_date, qty=quantity)
    line.price_book_item = item
    line.unit_cost = res.unit_cost
    line.list_price_snapshot = res.list_price
    line.price_source = (SNAPSHOT_SOURCE_PREFIX + (res.source or 'missing'))[:40]
    line.price_resolved_at = timezone.now()
    if not getattr(line, 'description', '') and hasattr(line, 'description'):
        line.description = item.name[:300]
    if hasattr(line, 'name') and not getattr(line, 'name', ''):
        line.name = item.name[:200]
    if set_unit_price and not res.missing:
        line.unit_price = _q2(res.unit_price)
    return res


# ---------------------------------------------------------------------------
# Labor rates
# ---------------------------------------------------------------------------

def _technician_skills(technician):
    if technician is None:
        return set()
    try:
        return {s.lower() for s in technician.resourcing_skills.values_list('name', flat=True)}
    except Exception:
        from resourcing.models import UserSkill
        return {s.lower() for s in UserSkill.objects.filter(user=technician).values_list('name', flat=True)}


def _line_matches(line, role, technician, skills, service_category, location):
    if line.role_id and (role is None or line.role_id != role.pk):
        return False
    if line.technician_id and (technician is None or line.technician_id != technician.pk):
        return False
    if line.skill and line.skill.lower() not in skills:
        return False
    if line.service_category and (not service_category
                                  or line.service_category.lower() != str(service_category).lower()):
        return False
    if line.location_id and (location is None or line.location_id != _pk(location)):
        return False
    return True


LEVELS = (
    (RateCard.SCOPE_CUSTOMER_CONTRACT, 'customer + contract rate card'),
    (RateCard.SCOPE_CUSTOMER, 'customer rate card'),
    (RateCard.SCOPE_CONTRACT, 'contract rate card'),
    (RateCard.SCOPE_DEFAULT, 'MSP-wide default rate card'),
)


def _cards_for_level(scope, client_id, contract, d):
    qs = RateCard.objects.filter(is_active=True, scope=scope)
    if scope == RateCard.SCOPE_CUSTOMER_CONTRACT:
        if client_id is None or contract is None:
            return []
        qs = qs.filter(client_org_id=client_id, contract=contract)
    elif scope == RateCard.SCOPE_CUSTOMER:
        if client_id is None:
            return []
        qs = qs.filter(client_org_id=client_id)
    elif scope == RateCard.SCOPE_CONTRACT:
        if contract is None:
            return []
        qs = qs.filter(contract=contract)
    return list(_in_effect(qs, d).order_by('-effective_from', '-pk').prefetch_related('lines'))


def resolve_labor_rate(technician=None, client=None, contract=None, role=None, rate_type='standard',
                       on_date=None, service_category='', location=None):
    """Hourly bill rate. `role` is a LaborRole (or None for "any role")."""
    d = _as_date(on_date)
    rate_type = rate_type or 'standard'
    res = LaborRateResult(role=role, rate_type=rate_type)
    if _contract_mismatch(client, contract):
        res.missing, res.reason = True, 'The contract is with a different customer.'
        return res
    client_id = _pk(client) if client is not None else (contract.client_org_id if contract else None)
    if role is not None and not role.applies_to(client_id):
        res.missing, res.reason = True, 'The labor role is another customer\'s own role.'
        return res
    skills = _technician_skills(technician)
    for scope, label in LEVELS:
        for card in _cards_for_level(scope, client_id, contract, d):
            lines = [ln for ln in card.lines.all() if ln.rate_type == rate_type
                     and _line_matches(ln, role, technician, skills, service_category, location)]
            if not lines:
                continue
            best = max(lines, key=lambda ln: (ln.specificity, ln.pk))
            res.rate, res.source = best.hourly_rate, scope
            res.rate_card, res.rate_card_line, res.currency = card, best, card.currency
            return res
    if role is not None and role.default_bill_rate is not None and role.is_active:
        res.rate, res.source = role.default_bill_rate, 'role_default'
        return res
    who = f'role "{role.name}"' if role is not None else 'untagged time'
    res.missing = True
    res.reason = (f'No {dict(RateCardLine.RATE_TYPES).get(rate_type, rate_type).lower()} rate for {who} '
                  f'on {d.isoformat()}: no customer, contract or MSP-wide rate card line applies and '
                  'the role has no configured default rate.')
    return res


def resolve_billing_rule(client=None, contract=None, on_date=None):
    """Most specific active BillingRule (customer + contract > customer >
    contract > MSP-wide default), or None when none is configured."""
    d = _as_date(on_date)
    if _contract_mismatch(client, contract):
        return None
    client_id = _pk(client) if client is not None else (contract.client_org_id if contract else None)
    base = _in_effect(BillingRule.objects.filter(is_active=True), d)
    tries = []
    if client_id and contract is not None:
        tries.append(base.filter(client_org_id=client_id, contract=contract))
    if client_id:
        tries.append(base.filter(client_org_id=client_id, contract__isnull=True))
    if contract is not None:
        tries.append(base.filter(client_org__isnull=True, contract=contract))
    tries.append(base.filter(client_org__isnull=True, contract__isnull=True))
    for qs in tries:
        rule = qs.order_by('-effective_from', '-pk').first()
        if rule is not None:
            return rule
    return None


class BillingRuleBook:
    """resolve_billing_rule for many lookups (a read-only pass such as the
    Ready for Billing queue), with the active rules of these customers and the
    MSP-wide ones read in one query. The rows stay in the database's own
    '-effective_from, -pk' order (NULLs where the database puts them); each
    lookup keeps the first row of that order whose scope and window match, in
    the same precedence, so it returns exactly what resolve_billing_rule does.
    """

    def __init__(self, client_ids):
        from .models import BillingRule
        ids = [i for i in set(client_ids) if i]
        self.rows = list(BillingRule.objects.filter(is_active=True)
                         .filter(Q(client_org__isnull=True) | Q(client_org_id__in=ids))
                         .order_by('-effective_from', '-pk'))
        self.client_ids = set(ids)

    def covers(self, client_id):
        return not client_id or client_id in self.client_ids

    def resolve(self, client=None, contract=None, on_date=None):
        d = _as_date(on_date)
        if _contract_mismatch(client, contract):
            return None
        client_id = _pk(client) if client is not None else (contract.client_org_id if contract else None)
        contract_id = contract.pk if contract is not None else None
        tries = []
        if client_id and contract is not None:
            tries.append((client_id, contract_id))
        if client_id:
            tries.append((client_id, None))
        if contract is not None:
            tries.append((None, contract_id))
        tries.append((None, None))
        live = [r for r in self.rows if (r.effective_from is None or r.effective_from <= d)
                and (r.effective_to is None or r.effective_to >= d)]
        for want_client, want_contract in tries:
            for r in live:
                if r.client_org_id == want_client and r.contract_id == want_contract:
                    return r
        return None


# ---------------------------------------------------------------------------
# Cost rates
# ---------------------------------------------------------------------------

def resolve_cost_rate(technician, on_date=None):
    """Loaded (fully burdened when burden fields are set) cost per hour.

    Unlike the legacy `resourcing.TechCostRate.rate_for`, which falls back to
    reports.queries.DEFAULT_LOADED_RATE ($60) and is left that way for its
    existing callers, this returns `unknown=True, rate=None` when no rate is
    configured."""
    from resourcing.models import TechCostRate
    d = _as_date(on_date)
    if technician is None:
        return CostRateResult(unknown=True, reason='No technician.')
    row = (TechCostRate.objects.filter(user=technician, effective_from__lte=d)
           .order_by('-effective_from').first())
    if row is None:
        return CostRateResult(unknown=True, reason=f'No cost rate configured for {technician} on {d.isoformat()}.')
    burdened = row.fully_burdened
    if burdened is not None:
        return CostRateResult(rate=burdened, source_row=row, burdened=True)
    return CostRateResult(rate=row.rate_per_hour, source_row=row)


# ---------------------------------------------------------------------------
# Time entry snapshot
# ---------------------------------------------------------------------------

def labor_role_for_code(client_org, role_code):
    """The LaborRole for a time entry's role_code: the customer's own role
    with that code first, else the install-wide one."""
    if not role_code:
        return None
    qs = LaborRole.objects.filter(code__iexact=role_code.strip(), is_active=True)
    if client_org is not None:
        own = qs.filter(organization_id=_pk(client_org)).first()
        if own is not None:
            return own
    return qs.filter(organization__isnull=True).first()


def coverage_for(contract, entry, prior_minutes=None):
    """included / overage / partial / flat_fee / no_contract / non_billable.

    A FORECAST label stored on a new time entry (`included_vs_overage`), from
    the contract's old usage counter, which also counts unapproved time. It
    never deducts or bills anything and shows no balance: prepaid hours are
    used when the timesheet is approved and invoices read the prepaid-hour
    ledger (Phase 101.3/101.4). Balances shown anywhere come from the ledger
    (`Contract.prepaid`)."""
    if not entry.is_billable:
        return 'non_billable'
    if contract is None:
        return 'no_contract'
    allowance = contract.effective_total_minutes()
    if allowance <= 0:
        return 'flat_fee' if contract.contract_type in contract.FLAT_FEE_TYPES else 'overage'
    used = contract.hours_used_minutes if prior_minutes is None else prior_minutes
    minutes = entry.duration_minutes or 0
    if used >= allowance:
        return 'overage'
    if used + minutes <= allowance:
        return 'included'
    return 'partial'


def _is_holiday(on, client):
    try:
        from resourcing.models import Holiday
        return Holiday.is_holiday(_as_date(on), organization=client)
    except Exception:  # pragma: no cover - resourcing app unavailable
        return False


def snapshot_time_entry(entry):
    """Fill the rate snapshot fields of a NEW psa.TicketTimeEntry (unsaved
    or just saved). Explicit values the caller set (contract, labor_role,
    rate_type, rates) are kept. Never raises for missing configuration; the
    entry is flagged `rate_missing` with a reason instead."""
    ticket = entry.ticket
    client = ticket.organization if ticket is not None else None
    on = entry.started_at or timezone.now()
    if entry.contract_id is None:
        entry.contract = contract_for_client(client, on)
    contract = entry.contract
    if entry.labor_role_id is None:
        entry.labor_role = labor_role_for_code(client, entry.role_code)
    if not entry.rate_type:
        entry.rate_type = 'standard'
        # Phase 101.4: time worked on a holiday (resourcing.Holiday, the
        # customer's or install-wide) is rated with the rate card's holiday
        # line when there is one. After-hours / weekend are not inferred:
        # there is no business-hours calendar yet (Phase 93).
        if entry.bill_rate_snapshot is None and _is_holiday(on, client):
            hol = resolve_labor_rate(technician=entry.user, client=client, contract=contract,
                                     role=entry.labor_role, rate_type='holiday', on_date=on)
            if not hol.missing and hol.rate_card_line is not None:  # a real holiday line
                entry.rate_type = 'holiday'
    if entry.bill_rate_snapshot is None:
        res = resolve_labor_rate(technician=entry.user, client=client, contract=contract,
                                 role=entry.labor_role, rate_type=entry.rate_type, on_date=on)
        entry.bill_rate_snapshot = res.rate
        entry.rate_card_line = res.rate_card_line
        missing = res.missing
        entry.rate_missing_reason = res.reason[:300] if missing else ''
    else:
        missing = False
    # Non-billable time is not charged, so a missing rate is not a billing gap.
    entry.rate_missing = bool(missing and entry.is_billable)
    if entry.cost_rate_snapshot is None:
        cost = resolve_cost_rate(entry.user, on)
        entry.cost_rate_snapshot = cost.rate
    if not entry.included_vs_overage:
        entry.included_vs_overage = coverage_for(contract, entry)
    return entry
