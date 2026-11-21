"""Phase 102.8: Settings → Billing — the billing settings, their validation,
and where each effective value comes from.

The install-wide values live on core.SystemSetting (they existed before this
page, settable only from a shell). Approval thresholds and late-fee terms are
also per-customer / per-contract terms: psa.BillingSettingOverride holds a
customer's or a contract's own value, blank = inherit. Resolution order:

    contract override > customer override > Settings → Billing (global)

`effective(key, client=..., contract=...)` returns the value and its source;
every reader (the invoice approval flag, the late-fee job) goes through it.
The other settings here are install behaviour or defaults for new documents
and have no override.

No setting is applied retroactively: the approval flag is evaluated only
while an invoice is a draft (psa.signals), late fees are separate account
charges created by the late-fee job, and the defaults are copied onto a new
document when it is created. Nothing here rewrites an existing invoice.

Permissions: superusers, and MSP staff holding `billing_approve_invoices`
(the billing administrator's permission: it already decides invoices held
by these thresholds). Global values need that permission for every
customer; a customer's or contract's override needs it at that customer
(accounts.permission_utils, per customer). Customer (portal) users get
nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

PERM = 'billing_approve_invoices'
GLOBAL, CUSTOMER, CONTRACT = 'global', 'customer', 'contract'
SOURCE_LABELS = {GLOBAL: 'Settings → Billing (all customers)', CUSTOMER: 'Customer override',
                 CONTRACT: 'Contract override'}


class SettingError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    help: str
    kind: str                 # money | percent | int | bool | tax_rate | currency
    section: str
    overridable: bool = False
    maximum: Decimal | int | None = None
    unit: str = ''


SPECS = (
    Spec('invoice_approval_threshold_total', 'Invoice approval threshold',
         'A draft invoice whose total reaches this amount needs approval before it can be sent or pushed to '
         'accounting. 0 turns the total check off.', 'money', 'Invoice approval', True,
         Decimal('9999999999.99'), '$'),
    Spec('invoice_approval_overage_pct', 'Agreement usage threshold',
         'A draft invoice for an agreement whose prepaid hours are used to this percent (or beyond) needs '
         'approval. 0 turns it off.', 'int', 'Invoice approval', True, 1000, '%'),
    Spec('quote_approval_threshold_total', 'Quote approval threshold',
         'A quote whose total reaches this amount is routed for internal approval. 0 turns it off.',
         'money', 'Invoice approval', False, Decimal('9999999999.99'), '$'),
    Spec('contracts_esign_exempt_month_to_month', 'Month-to-month contracts without e-signature',
         'Contracts whose term is not month-to-month, and every quote, must be accepted by the customer\'s '
         'e-signature before they are activated, converted or billed. On: month-to-month contracts are '
         'exempt. Off: every new month-to-month activation needs the signature too; contracts already active keep billing.',
         'bool', 'E-signature'),
    Spec('late_fee_pct', 'Late fee',
         'Percent of the overdue balance charged once per overdue invoice by the daily late-fee job, as a '
         'separate account charge. 0 turns late fees off.', 'percent', 'Late fees', True, Decimal('100'), '%'),
    Spec('late_fee_min_days_overdue', 'Days overdue before a late fee',
         'Days past the due date before the late fee is charged. 0 turns late fees off.', 'int',
         'Late fees', True, 3650, 'days'),
    Spec('psa_auto_push_recurring_invoices', 'Push recurring invoices to accounting automatically',
         'The recurring-invoice job pushes each new agreement invoice to the connected accounting system. '
         'Invoices held for approval are never pushed until approved.', 'bool', 'Accounting'),
    Spec('psa_default_tax_rate', 'Default tax rate for new quotes and invoices',
         'Used when the sales tax mode is "flat" (Settings → Sales Tax). Each quote or invoice can still '
         'change it. Existing documents keep their rate.', 'tax_rate', 'Defaults for new documents', False,
         Decimal('100'), '%'),
    Spec('psa_default_currency', 'Default currency for new invoices',
         'ISO 4217 code (e.g. USD). Existing invoices keep their currency.', 'currency',
         'Defaults for new documents'),
)
BY_KEY = {s.key: s for s in SPECS}
OVERRIDABLE = tuple(s.key for s in SPECS if s.overridable)


def sections():
    out = {}
    for s in SPECS:
        out.setdefault(s.section, []).append(s)
    return list(out.items())


# --- parsing / validation -------------------------------------------------------

def _decimal(raw, label):
    text = str(raw if raw is not None else '').strip().replace(',', '')
    try:
        v = Decimal(text)
    except (InvalidOperation, ValueError):
        raise SettingError(f'{label}: enter a number.')
    if not v.is_finite():
        raise SettingError(f'{label}: enter a number.')
    return v


def parse(key, raw, *, allow_blank=False):
    """The stored value for `raw` (a POSTed string), or None when blank and
    `allow_blank`. Raises SettingError with a message naming the setting."""
    spec = BY_KEY[key]
    text = '' if raw is None else str(raw).strip()
    if spec.kind == 'bool':
        return text in ('1', 'on', 'true', 'yes')
    if text == '':
        if allow_blank:
            return None
        raise SettingError(f'{spec.label}: a value is required.')
    if spec.kind == 'currency':
        code = text.upper()
        if not re.fullmatch(r'[A-Z]{3}', code):
            raise SettingError(f'{spec.label}: enter a three-letter ISO 4217 code such as USD.')
        return code
    if spec.kind == 'int':
        if not re.fullmatch(r'\d+', text):
            raise SettingError(f'{spec.label}: enter a whole number of 0 or more.')
        v = int(text)
        if spec.maximum is not None and v > spec.maximum:
            raise SettingError(f'{spec.label}: at most {spec.maximum}.')
        return v
    v = _decimal(text, spec.label)
    if v < 0:
        raise SettingError(f'{spec.label}: cannot be negative.')
    if spec.maximum is not None and v > spec.maximum:
        raise SettingError(f'{spec.label}: at most {spec.maximum}.')
    if spec.kind == 'tax_rate':
        # Entered as a percent (8.75), stored as a fraction (0.0875).
        if v != v.quantize(Decimal('0.01')):
            raise SettingError(f'{spec.label}: at most two decimal places.')
        return (v / Decimal('100')).quantize(Decimal('0.0001'))
    if v != v.quantize(Decimal('0.01')):
        raise SettingError(f'{spec.label}: at most two decimal places.')
    return v.quantize(Decimal('0.01'))


def display(key, value):
    """A stored value as the page shows it (and as a form field is filled)."""
    spec = BY_KEY[key]
    if value is None:
        return ''
    if spec.kind == 'bool':
        return 'On' if value else 'Off'
    if spec.kind == 'tax_rate':
        return f'{(Decimal(str(value)) * 100).quantize(Decimal("0.01"))}'
    return str(value)


def audit_value(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


# --- resolution -------------------------------------------------------------------

@dataclass
class Effective:
    key: str
    value: object
    source: str
    global_value: object
    customer_value: object = None
    contract_value: object = None

    @property
    def spec(self):
        return BY_KEY[self.key]

    @property
    def source_label(self):
        return SOURCE_LABELS[self.source]

    @property
    def shown(self):
        return display(self.key, self.value)


def _overrides(client_id, contract_id):
    from psa.models import BillingSettingOverride
    keys = []
    if contract_id:
        keys.append(f'contract:{contract_id}')
    if client_id:
        keys.append(f'customer:{client_id}')
    if not keys:
        return None, None
    rows = {r.scope_key: r for r in BillingSettingOverride.objects.filter(scope_key__in=keys)}
    return (rows.get(f'customer:{client_id}') if client_id else None,
            rows.get(f'contract:{contract_id}') if contract_id else None)


def resolve(client=None, contract=None, *, ss=None, keys=None):
    """{key: Effective} for `keys` (every setting by default)."""
    from core.models import SystemSetting
    ss = ss or SystemSetting.get_settings()
    contract_id = getattr(contract, 'pk', contract)
    client_id = getattr(client, 'pk', client)
    if contract is not None and client_id is None and hasattr(contract, 'client_org_id'):
        client_id = contract.client_org_id
    cust_row, contract_row = _overrides(client_id, contract_id)
    out = {}
    for key in keys or BY_KEY:
        spec = BY_KEY[key]
        g = getattr(ss, key)
        e = Effective(key=key, value=g, source=GLOBAL, global_value=g)
        if spec.overridable:
            cv = getattr(cust_row, key) if cust_row is not None else None
            kv = getattr(contract_row, key) if contract_row is not None else None
            e.customer_value, e.contract_value = cv, kv
            if kv is not None:
                e.value, e.source = kv, CONTRACT
            elif cv is not None:
                e.value, e.source = cv, CUSTOMER
        out[key] = e
    return out


def effective(key, client=None, contract=None, *, ss=None):
    return resolve(client, contract, ss=ss, keys=[key])[key]


def for_invoice(invoice, keys, *, ss=None):
    """{key: value} for an invoice: its contract (source_contract) and customer."""
    res = resolve(invoice.client_org_id, invoice.source_contract_id, ss=ss, keys=keys)
    return {k: e.value for k, e in res.items()}


# --- permissions ----------------------------------------------------------------------

def _is_staff(user):
    from psa.visibility import is_msp_staff
    return bool(user and user.is_authenticated and (user.is_superuser or is_msp_staff(user)))


def manageable_customers(user):
    """None = every customer, else the set of customer ids whose overrides
    `user` may change (empty for everyone else)."""
    from accounts.permission_utils import orgs_with_perm
    if not _is_staff(user):
        return set()
    if user.is_superuser:
        return None
    return orgs_with_perm(user, PERM)


def can_view(user):
    allowed = manageable_customers(user)
    return allowed is None or bool(allowed)


def can_edit_global(user):
    return _is_staff(user) and manageable_customers(user) is None


def can_edit_customer(user, client):
    allowed = manageable_customers(user)
    cid = getattr(client, 'pk', client)
    return allowed is None or cid in allowed


# --- writes (audited) ------------------------------------------------------------------

def save_global(values, *, actor, request=None):
    """Write the changed install-wide values. `values` is {key: raw string};
    keys missing from it keep their value (a checkbox that is not posted is
    off). Validates everything first; nothing is saved on any error. Returns
    {key: (before, after)} of what changed."""
    from core.models import SystemSetting
    if not can_edit_global(actor):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Changing the billing settings for every customer needs the '
                               f"'{PERM}' permission for every customer.")
    parsed, errors = {}, []
    for spec in SPECS:
        if spec.kind != 'bool' and spec.key not in values:
            continue
        try:
            parsed[spec.key] = parse(spec.key, values.get(spec.key))
        except SettingError as exc:
            errors.append(str(exc))
    if errors:
        raise SettingError(' '.join(errors))
    ss = SystemSetting.get_settings()
    changed = {k: (getattr(ss, k), v) for k, v in parsed.items() if getattr(ss, k) != v}
    if not changed:
        return {}
    for k, (_b, v) in changed.items():
        setattr(ss, k, v)
    ss.updated_by = actor
    ss.save(update_fields=list(changed) + ['updated_by', 'updated_at'])
    _audit(actor, None, 'core.SystemSetting', ss.pk, 'Settings → Billing (all customers)',
           'Billing settings: ' + '; '.join(
               f'{BY_KEY[k].label} {display(k, b) or "blank"} → {display(k, a) or "blank"}'
               for k, (b, a) in changed.items()),
           {'event': 'billing_settings', 'scope': GLOBAL,
            'changed': {k: {'from': audit_value(b), 'to': audit_value(a)} for k, (b, a) in changed.items()}},
           request)
    return changed


def save_override(client, contract, values, *, actor, note='', request=None):
    """Set a customer's (contract=None) or a contract's overrides. `values`
    is {key: raw string}; blank = inherit. All blank removes the override.
    Returns {key: (before, after)}."""
    from django.core.exceptions import PermissionDenied

    from psa.models import BillingSettingOverride
    if not can_edit_customer(actor, client):
        raise PermissionDenied(f"You don't have the '{PERM}' permission for this customer.")
    if contract is not None and contract.client_org_id != client.pk:
        raise SettingError('That contract is not one of this customer\'s.')
    parsed, errors = {}, []
    for key in OVERRIDABLE:
        try:
            parsed[key] = parse(key, values.get(key), allow_blank=True)
        except SettingError as exc:
            errors.append(str(exc))
    if errors:
        raise SettingError(' '.join(errors))
    scope_key = f'contract:{contract.pk}' if contract is not None else f'customer:{client.pk}'
    row = BillingSettingOverride.objects.filter(scope_key=scope_key).first()
    before = row.values() if row is not None else {k: None for k in OVERRIDABLE}
    changed = {k: (before[k], v) for k, v in parsed.items() if before[k] != v}
    note = (note or '').strip()[:300]
    if all(v is None for v in parsed.values()):
        if row is None:
            return {}
        row.delete()
        action = 'delete'
    else:
        if row is None:
            row = BillingSettingOverride(client_org=client, contract=contract)
        elif not changed and note == row.note:
            return {}
        for k, v in parsed.items():
            setattr(row, k, v)
        row.note = note
        row.updated_by = actor
        row.save()
        action = 'update'
    scope = CONTRACT if contract is not None else CUSTOMER
    label = f'{client.name}' + (f' — contract {contract.name}' if contract is not None else '')
    _audit(actor, client, 'psa.BillingSettingOverride', getattr(row, 'pk', None) or 0, label,
           (f'Removed billing overrides for {label}' if action == 'delete' else
            f'Billing overrides for {label}: ' + ('; '.join(
                f'{BY_KEY[k].label} {display(k, b) or "inherit"} → {display(k, a) or "inherit"}'
                for k, (b, a) in changed.items()) or 'note changed')),
           {'event': 'billing_settings', 'scope': scope, 'customer': client.pk,
            'contract': getattr(contract, 'pk', None),
            'changed': {k: {'from': audit_value(b), 'to': audit_value(a)} for k, (b, a) in changed.items()}},
           request, action=action)
    return changed


def _audit(actor, org, obj_type, obj_id, repr_, description, extra, request=None, action='update'):
    from audit.models import AuditLog
    kw = {}
    if request is not None:
        kw = {'ip_address': request.META.get('REMOTE_ADDR'), 'path': request.path}
    AuditLog.log(user=actor, action=action, organization=org, object_type=obj_type, object_id=obj_id,
                 object_repr=str(repr_)[:200], description=description[:1000], extra_data=extra, **kw)
