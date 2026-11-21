"""Contract terms (month-to-month, annual, multi-year, custom fixed term) and
the e-signature rule that hangs off them.

One vocabulary for both kinds of contract:

* `psa.Contract` — the billing record (activation, recurring invoices);
* `contracts.ContractDocument` — the agreement the customer signs.

The rule (owner, 2026-11-21): every contract whose term is not
month-to-month must be accepted by the customer's e-signature before it is
activated or billed. Whether month-to-month is exempt is the install setting
`SystemSetting.contracts_esign_exempt_month_to_month` (Settings → Billing),
on by default. Quotes always need an e-signature (psa.Quote.mark_accepted).

Nothing here is evaluated retroactively against billing that already ran:
contracts that existed before this rule carry `legacy_terms_hash` (a
fingerprint of their commercial terms at upgrade time, written by migration
psa 0099) and keep billing exactly as before as long as those terms are not
changed. See psa.Contract.esign_status.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

MONTH_TO_MONTH = 'month_to_month'
ANNUAL = 'annual'
MULTI_YEAR = 'multi_year'
FIXED = 'fixed'

TERM_TYPES = [
    (MONTH_TO_MONTH, 'Month-to-month'),
    (ANNUAL, 'Annual (12 months)'),
    (MULTI_YEAR, 'Multi-year'),
    (FIXED, 'Custom fixed term'),
]
TERM_LABELS = dict(TERM_TYPES)


class ESignatureRequired(ValueError):
    """Activating, converting or billing something the customer has not
    accepted by e-signature."""


def normalize(term_type, months):
    """(term_type, months) made consistent: annual is always 12 months,
    month-to-month has no length, multi-year is at least 24 months."""
    term_type = term_type if term_type in TERM_LABELS else MONTH_TO_MONTH
    try:
        months = int(months) if months not in (None, '') else None
    except (TypeError, ValueError):
        months = None
    if months is not None and months < 1:
        months = None
    if term_type == MONTH_TO_MONTH:
        return term_type, None
    if term_type == ANNUAL:
        return term_type, 12
    if term_type == MULTI_YEAR:
        return term_type, max(24, months or 36)
    return term_type, months


def term_errors(term_type, months) -> list[str]:
    if term_type not in TERM_LABELS:
        return ['Term: choose month-to-month, annual, multi-year or a custom fixed term.']
    if term_type == FIXED and not months:
        return ['Term: enter the length of the fixed term in months.']
    if term_type == MULTI_YEAR and months is not None and months < 24:
        return ['Term: a multi-year term is at least 24 months.']
    return []


def label(term_type, months=None) -> str:
    if term_type == MULTI_YEAR and months:
        return f'Multi-year ({months} months)'
    if term_type == FIXED and months:
        return f'Fixed term ({months} months)'
    return TERM_LABELS.get(term_type, TERM_LABELS[MONTH_TO_MONTH])


def months_between(start, end):
    """Whole months covered by an inclusive [start, end] window (a contract
    from 2026-01-01 to 2026-12-31 is 12 months)."""
    if not start or not end or end < start:
        return None
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta
    rd = relativedelta(end + timedelta(days=1), start)
    months = rd.years * 12 + rd.months
    if rd.days >= 15:
        months += 1
    return max(1, months)


def infer(start, end):
    """The term an existing contract's dates imply (used once, by the
    upgrade migration): no end date → month-to-month (it bills until it is
    cancelled); 12 months → annual; 24+ months in whole years → multi-year;
    anything else → a custom fixed term of that many months."""
    if not end:
        return MONTH_TO_MONTH, None
    months = months_between(start, end)
    if months is None:
        return FIXED, None
    if months == 12:
        return ANNUAL, 12
    if months >= 24 and months % 12 == 0:
        return MULTI_YEAR, months
    return FIXED, months


def infer_from_months(months):
    """The term a bare length implies: none → month-to-month, 12 → annual,
    24+ in whole years → multi-year, else a custom fixed term."""
    if not months:
        return MONTH_TO_MONTH
    if months == 12:
        return ANNUAL
    if months >= 24 and months % 12 == 0:
        return MULTI_YEAR
    return FIXED


def month_to_month_exempt() -> bool:
    try:
        from core.models import SystemSetting
        return bool(SystemSetting.get_settings().contracts_esign_exempt_month_to_month)
    except Exception:  # noqa: BLE001 — fail closed: require the signature
        return False


def requires_signature(term_type) -> bool:
    if term_type == MONTH_TO_MONTH:
        return not month_to_month_exempt()
    return True


# --- commercial terms of a billing contract -------------------------------------

COMMERCIAL_FIELDS = ('client_org_id', 'term_type', 'term_months', 'billing_frequency', 'recurring_amount',
                     'total_hours', 'hourly_rate', 'overage_rate', 'auto_renew', 'auto_renew_period_months',
                     'notice_period_days')


def _plain(v):
    if isinstance(v, Decimal):
        return f'{v:.2f}'
    if isinstance(v, float):
        return f'{Decimal(str(v)):.2f}'
    return v


def commercial_terms(values) -> dict:
    """The terms a customer agrees to, from a psa.Contract (or a dict of its
    field values). Dates are left out so a renewal of the same terms
    matches."""
    get = values.get if isinstance(values, dict) else (lambda k: getattr(values, k, None))
    out = {}
    for f in COMMERCIAL_FIELDS:
        v = get(f)
        if f in ('recurring_amount', 'total_hours', 'hourly_rate', 'overage_rate'):
            v = f'{Decimal(str(v if v not in (None, "") else 0)):.2f}'
        out[f] = _plain(v)
    return out


def terms_hash(values) -> str:
    data = json.dumps({'schema': 'clientst0r.contract-terms.v1', **commercial_terms(values)},
                      sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


# Billing frequency on the signed document → psa.Contract.billing_frequency
DOC_TO_BILLING_FREQUENCY = {'monthly': 'monthly', 'quarterly': 'quarterly', 'annually': 'yearly'}
