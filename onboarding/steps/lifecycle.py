"""Steps for the lifecycle wizards (plan change, add / remove users or devices,
add location, renewal, price increase, offboarding).

They reuse the engine and the shared steps (locations, pricing, send for
approval). The step that changes price or contract - `change_draft` - only ever
produces a draft amendment, renewal or quote, which then goes through the
existing approval workflow from `send_approval`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django import forms
from django.utils import timezone
from django.utils.html import escape

from onboarding import access
from onboarding.models import OnboardingSession as S
from onboarding.registry import Step, StepError, StepForm, register_step, set_kind_steps
from . import common
from .common import need


class SelectClientForm(StepForm):
    client = forms.ModelChoiceField(queryset=None, label='Customer')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = access.reachable_clients(user).filter(is_active=True).order_by('name') \
            if user else []


class SelectClientStep(Step):
    key = 'select_client'
    title = 'Customer'
    summary = 'The customer this change is for.'
    needs_client = False
    skippable = False
    form_class = SelectClientForm

    def form_kwargs(self, session, user):
        return {'user': user}

    def initial(self, session):
        return {'client': session.client_id}

    def apply(self, session, cleaned, user, request=None):
        client = cleaned['client']
        if not access.can_use(user, client):
            raise StepError('You cannot run onboarding wizards for that customer.')
        session.client = client
        session.save(update_fields=['client', 'updated_at'])
        return f'Customer "{client.name}"'


# --- change details ------------------------------------------------------------------------

def _date_field(label='Effective date'):
    return forms.DateField(label=label, initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))


class QuantityChangeForm(StepForm):
    quantity = forms.IntegerField(min_value=1, label='How many')
    unit_price = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False,
                                    label='Price each per month')
    effective_date = _date_field()
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class LocationChangeForm(StepForm):
    monthly_price = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False,
                                       label='Extra monthly price for the location')
    effective_date = _date_field()
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class PlanChangeForm(StepForm):
    new_plan_name = forms.CharField(max_length=200, required=False, label='New plan',
                                    help_text='Free text; the price book plan chosen above is used when present.')
    new_monthly_price = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, required=False,
                                           label='New monthly price')
    effective_date = _date_field()
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class RenewalForm(StepForm):
    term_months = forms.IntegerField(min_value=1, max_value=120, initial=12, label='New term (months)')
    price_adjustment_percent = forms.DecimalField(min_value=-100, max_value=100, max_digits=5, decimal_places=2,
                                                  required=False, label='Price adjustment (%)')
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class PriceIncreaseForm(StepForm):
    percent = forms.DecimalField(min_value=0, max_value=100, max_digits=5, decimal_places=2,
                                 label='Increase (%)')
    effective_date = _date_field()
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


class OffboardingForm(StepForm):
    end_date = _date_field('Services end on')
    reason = forms.CharField(max_length=300, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Final billing notes')


FORMS = {S.ADD_USERS: QuantityChangeForm, S.REMOVE_USERS: QuantityChangeForm, S.ADD_DEVICES: QuantityChangeForm,
         S.REMOVE_DEVICES: QuantityChangeForm, S.ADD_LOCATION: LocationChangeForm, S.PLAN_CHANGE: PlanChangeForm,
         S.RENEWAL: RenewalForm, S.PRICE_INCREASE: PriceIncreaseForm, S.OFFBOARDING: OffboardingForm}
QUANTITY_NOUN = {S.ADD_USERS: 'users', S.REMOVE_USERS: 'users', S.ADD_DEVICES: 'devices',
                 S.REMOVE_DEVICES: 'devices'}
REMOVALS = (S.REMOVE_USERS, S.REMOVE_DEVICES)


def monthly_delta(session, details=None):
    """The change in monthly price the details describe (negative for
    removals), or None when no price was given."""
    d = details if details is not None else session.step_data('change_details')
    kind = session.kind
    if kind in QUANTITY_NOUN:
        if not d.get('unit_price'):
            return None
        amount = Decimal(str(d.get('quantity') or 0)) * Decimal(str(d['unit_price']))
        return -amount if kind in REMOVALS else amount
    if kind == S.ADD_LOCATION and d.get('monthly_price'):
        return Decimal(str(d['monthly_price']))
    return None


def proration_preview(session, details=None):
    """What the first period of the change costs, using the helper psa.Contract
    already has for mid-period starts (`_proration_factor`). Returns a dict for
    the template, or {'note': ...} when it cannot be shown."""
    from dateutil.relativedelta import relativedelta
    from psa.models import Contract
    d = details if details is not None else session.step_data('change_details')
    delta = monthly_delta(session, d)
    eff = d.get('effective_date')
    if delta is None or not eff or session.client is None:
        return {'note': 'Enter a price and an effective date to see the prorated first period.'}
    eff = date.fromisoformat(eff) if isinstance(eff, str) else eff
    active = Contract.objects.filter(client_org=session.client, status='active').exclude(
        billing_frequency='none').first()
    freq = active.billing_frequency if active else 'monthly'
    months = {'monthly': 1, 'quarterly': 3, 'yearly': 12}.get(freq, 1)
    if freq == 'monthly':
        start = eff.replace(day=1)
    elif freq == 'quarterly':
        start = eff.replace(month=3 * ((eff.month - 1) // 3) + 1, day=1)
    else:
        start = eff.replace(month=1, day=1)
    probe = Contract(proration_enabled=True, start_date=eff, billing_frequency=freq)
    factor = Decimal(str(probe._proration_factor(start, freq)))
    prorated = (delta * months * factor).quantize(Decimal('0.01'))
    return {'factor': factor.quantize(Decimal('0.0001')), 'frequency': freq, 'period_start': start,
            'period_end': start + relativedelta(months=months), 'full': (delta * months).quantize(Decimal('0.01')),
            'prorated': prorated, 'contract': active,
            'proration_on': bool(active and active.proration_enabled),
            'note': ('The active billing contract has proration switched ' + ('on.' if active.proration_enabled
                     else 'off; turn it on there, or the full period is billed.')) if active else
                    'The customer has no active billing contract; a monthly period is assumed.'}


class ChangeDetailsStep(Step):
    key = 'change_details'
    title = 'Change details'
    summary = 'What is changing and from when. Recorded here; the draft is made in the next step.'
    commercial = True

    def get_form(self, session, data=None, user=None):
        cls = FORMS.get(session.kind)
        return cls(data, initial=self.initial(session)) if cls else None

    def context(self, session, user=None):
        return {'proration': proration_preview(session) if session.kind in
                (*QUANTITY_NOUN, S.ADD_LOCATION) else None}

    def apply(self, session, cleaned, user, request=None):
        return f'{session.get_kind_display()} details recorded'


# --- draft -------------------------------------------------------------------------------------

class ChangeDraftForm(StepForm):
    target = forms.ChoiceField(choices=[('auto', 'Automatic (amend the signed agreement when there is one, otherwise a quote)'),
                                        ('agreement', 'Draft amendment / renewal of the signed agreement'),
                                        ('quote', 'Draft quote')], initial='auto')


def latest_signed_agreement(client):
    from contracts.models import ContractDocument as D
    return D.objects.filter(organization=client, status=D.SIGNED).exclude(
        kind__in=('amendment',)).order_by('-signed_at', '-pk').first() or D.objects.filter(
        organization=client, status=D.SIGNED).order_by('-signed_at', '-pk').first()


def change_lines(session):
    """Line items the change adds, in the contract-document format."""
    d = session.step_data('change_details')
    kind = session.kind
    lines = []
    if kind in QUANTITY_NOUN and d.get('unit_price') and kind not in REMOVALS:
        lines.append({'description': f'Additional {QUANTITY_NOUN[kind]} (per month, from {d.get("effective_date")})',
                      'kind': 'recurring', 'quantity': str(d['quantity']), 'unit_price': str(d['unit_price']),
                      'discount_percent': '0', 'taxable': False})
    elif kind == S.ADD_LOCATION and d.get('monthly_price'):
        lines.append({'description': f'Additional location (per month, from {d.get("effective_date")})',
                      'kind': 'recurring', 'quantity': '1', 'unit_price': str(d['monthly_price']),
                      'discount_percent': '0', 'taxable': False})
    elif kind == S.PLAN_CHANGE:
        lines = common.lines_from_session(session)
        if not lines and d.get('new_monthly_price'):
            lines.append({'description': f'Service plan: {d.get("new_plan_name") or "new plan"}',
                          'kind': 'recurring', 'quantity': '1', 'unit_price': str(d['new_monthly_price']),
                          'discount_percent': '0', 'taxable': False})
    return lines


def summary_html(session):
    d = session.step_data('change_details')
    kind = session.kind
    noun = QUANTITY_NOUN.get(kind, '')
    eff = d.get('effective_date', '')
    if kind in QUANTITY_NOUN:
        what = f'{"Remove" if kind in REMOVALS else "Add"} {d.get("quantity")} {noun} effective {eff}.'
    elif kind == S.ADD_LOCATION:
        what = f'Add a location effective {eff}.'
    elif kind == S.PLAN_CHANGE:
        what = f'Change the service plan to {d.get("new_plan_name") or session.step_data("service_plan").get("plan_name") or "the new plan"} effective {eff}.'
    elif kind == S.RENEWAL:
        what = f'Renew for {d.get("term_months")} months.'
    elif kind == S.PRICE_INCREASE:
        what = f'Increase recurring prices by {d.get("percent")}% effective {eff}.'
    else:
        what = f'Services end on {d.get("end_date", "")}. Reason: {d.get("reason", "") or "not stated"}.'
    notes = d.get('notes') or ''
    return f'<p>{escape(what)}</p>' + (f'<p>{escape(notes)}</p>' if notes else '')


class ChangeDraftStep(Step):
    key = 'change_draft'
    title = 'Draft the change'
    summary = 'Creates a DRAFT amendment, renewal or quote for the change. It is not active until it goes through approval and signature.'
    form_class = ChangeDraftForm
    commercial = True

    def blocked_reason(self, session):
        base = super().blocked_reason(session)
        if base:
            return base
        if not session.step_states.filter(step_key='change_details', status='done').exists():
            return 'Fill in the change details first.'
        return ''

    def context(self, session, user=None):
        return {'agreement': session.agreement, 'quote': session.quote,
                'signed': latest_signed_agreement(session.client) if session.client else None,
                'proration': proration_preview(session) if session.kind in (*QUANTITY_NOUN, S.ADD_LOCATION) else None}

    def apply(self, session, cleaned, user, request=None):
        from contracts import permissions as perms
        client = session.client
        src = latest_signed_agreement(client)
        target = cleaned['target']
        if target == 'auto':
            target = 'agreement' if src is not None else 'quote'
        if session.kind in (S.RENEWAL, S.PRICE_INCREASE, S.OFFBOARDING) and (target == 'quote' or src is None):
            raise StepError('This change needs a signed agreement to renew or amend, and this customer has none.')
        if target == 'agreement':
            if src is None:
                raise StepError('This customer has no signed agreement to amend; choose a quote.')
            why = common.contract_denial(user, client, perms.EDIT)
            if why:
                raise StepError(why)
            return self._agreement(session, src, user, request)
        why = need(user, client, 'crm_manage_pipeline', 'creating quotes')
        if why:
            raise StepError(why)
        lines = change_lines(session)
        if session.kind in REMOVALS:
            d = session.step_data('change_details')
            lines.append({'description': f'Remove {d.get("quantity")} {QUANTITY_NOUN[session.kind]} (credit per month)',
                          'kind': 'recurring', 'quantity': f'-{d.get("quantity")}',
                          'unit_price': str(d.get('unit_price') or 0), 'discount_percent': '0', 'taxable': False})
        if not lines:
            raise StepError('Nothing to quote: enter a price in the change details.')
        from .core import build_quote_draft
        ref = build_quote_draft(session, user, lines, session.display_title)
        return f'Draft {ref}'

    def _agreement(self, session, src, user, request):
        from contracts import services
        from contracts.content import normalize_sections
        d = session.step_data('change_details')
        try:
            doc = services.renew(src, user, request) if session.kind == S.RENEWAL else services.amend(src, user, request)
            data = {}
            items = [dict(li) for li in (doc.line_items or [])]
            pct = None
            if session.kind == S.PRICE_INCREASE:
                pct = Decimal(str(d.get('percent') or 0))
            elif session.kind == S.RENEWAL and d.get('price_adjustment_percent'):
                pct = Decimal(str(d['price_adjustment_percent']))
            if pct:
                for li in items:
                    if li.get('kind') == 'recurring':
                        li['unit_price'] = str((Decimal(li['unit_price']) * (Decimal('100') + pct) / Decimal('100')
                                                ).quantize(Decimal('0.01')))
            items += change_lines(session)
            data['line_items'] = items
            if session.kind == S.RENEWAL:
                data['duration_months'] = int(d.get('term_months') or 12)
            sections = [dict(s) for s in doc.sections]
            at = next((i for i, s in enumerate(sections) if s.get('type') == 'signatures'), len(sections))
            sections.insert(at, {'title': 'Change summary', 'type': 'text', 'body': summary_html(session),
                                 'include': True})
            data['sections'] = normalize_sections(sections)
            services.save_draft(doc, data, user)
        except services.ContractError as exc:
            raise StepError(str(exc))
        session.agreement = doc
        session.save(update_fields=['agreement', 'updated_at'])
        return f'Draft {doc.get_relation_display().lower() or "document"} {doc.reference} of {src.reference}'


for _cls in (SelectClientStep, ChangeDetailsStep, ChangeDraftStep):
    register_step(_cls)

_TAIL = ['change_details', 'change_draft', 'send_approval']
set_kind_steps(S.PLAN_CHANGE, ['select_client', 'service_plan', 'add_ons', 'customer_pricing'] + _TAIL)
for _k in (S.ADD_USERS, S.REMOVE_USERS, S.ADD_DEVICES, S.REMOVE_DEVICES, S.RENEWAL, S.PRICE_INCREASE,
           S.OFFBOARDING):
    set_kind_steps(_k, ['select_client'] + _TAIL)
set_kind_steps(S.ADD_LOCATION, ['select_client', 'locations'] + _TAIL)
