"""Steps that build on the price book (the `pricing` app).

Each is feature-detected: without the app (or without its ServicePlan model)
the step is listed as "Available once the price book is enabled" and can be
skipped. With it they only RECORD the selection and feed draft quote /
agreement lines; no ClientServicePlan or price override is created from here,
because that would be an active commercial change. Attaching the plan to the
customer follows the signed agreement.
"""
from __future__ import annotations

from decimal import Decimal

from django import forms
from django.apps import apps
from django.db.models import Q

from onboarding.models import OnboardingSession as S
from onboarding.registry import Step, StepForm, register_step


def plan_model():
    try:
        return apps.get_model('pricing', 'ServicePlan')
    except LookupError:
        return None


def plan_lines(plan, client, quantities=None):
    """Sell-price lines of a plan.

    A plan carries its own prices (flat monthly, per user / device / server,
    one-time onboarding fee); items that are "included" are covered by those
    and not priced again. A price the plan does not set, or a per-unit price
    with no quantity recorded, is returned as a row with `unit_price` None and
    a `reason`: it is reported as missing and never replaced by a number.
    Only sell prices are read; cost and margin never enter the session.
    """
    q = quantities or {}
    rows = []

    def row(name, kind, qty, price, reason=''):
        rows.append({'name': name, 'kind': kind, 'quantity': str(qty) if qty is not None else None,
                     'unit_price': str(price) if price is not None else None, 'reason': reason})

    if plan.monthly_price is not None:
        row(f'{plan.name}', 'recurring', 1, plan.monthly_price)
    for field, key, label in (('per_user_price', 'users', 'user'), ('per_device_price', 'devices', 'device'),
                              ('per_server_price', 'servers', 'server')):
        price = getattr(plan, field)
        if price is None:
            continue
        qty = int(q.get(key) or 0)
        if qty:
            row(f'{plan.name}: per {label}', 'recurring', qty, price)
        else:
            row(f'{plan.name}: per {label}', 'recurring', None, None,
                f'Priced per {label} but no number of {key} was recorded.')
    if plan.onboarding_fee is not None:
        row(f'{plan.name}: onboarding fee', 'one_time', 1, plan.onboarding_fee)
    if not rows:
        row(plan.name, 'recurring', None, None, 'The plan has no price set.')
    return rows


class _PricingStep(Step):
    requires_apps = ('pricing',)
    feature_name = 'the price book'
    commercial = True

    def extra_available(self):
        return plan_model() is not None

    def plans(self, session, addon):
        model = plan_model()
        if model is None:
            return []
        # One MSP per install: install-wide plans (no organization) plus this
        # customer's own.
        return model.objects.filter(is_active=True, is_addon=addon).filter(
            Q(organization__isnull=True) | Q(organization_id=session.client_id))


class ServicePlanForm(StepForm):
    plan = forms.ModelChoiceField(queryset=None, label='Service plan')

    def __init__(self, *args, plans=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plan'].queryset = plans


class ServicePlanStep(_PricingStep):
    key = 'service_plan'
    title = 'Service plan'
    summary = 'Choose the plan from the price book. Its prices (flat, per user / device / server, onboarding fee) feed the draft quote or agreement; the plan is attached to the customer after signature. Anything without a price is listed as missing, never priced at zero.'
    form_class = ServicePlanForm

    def form_kwargs(self, session, user):
        return {'plans': self.plans(session, False)}

    def initial(self, session):
        return {'plan': session.step_data(self.key).get('plan_id')}

    def context(self, session, user=None):
        return {'missing': [r for r in session.step_data(self.key).get('lines', []) if r.get('unit_price') is None]}

    def apply(self, session, cleaned, user, request=None):
        plan = cleaned['plan']
        rows = plan_lines(plan, session.client, session.step_data('quantities'))
        missing = sum(1 for r in rows if r['unit_price'] is None)
        session.set_step_data(self.key, {'plan_id': plan.pk, 'plan_name': plan.name, 'lines': rows})
        session.save(update_fields=['data', 'updated_at'])
        return f'Plan "{plan.name}" chosen' + (f' ({missing} item(s) without a price)' if missing else '')

    def saved_data(self, session, cleaned):
        return session.step_data(self.key)


class AddOnsForm(StepForm):
    addons = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Add-ons',
                                            widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, plans=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['addons'].queryset = plans
        self.fields['addons'].widget.attrs.pop('class', None)


class AddOnsStep(_PricingStep):
    key = 'add_ons'
    title = 'Add-ons'
    summary = 'Optional add-on plans from the price book, priced for this customer and added as lines on the draft.'
    form_class = AddOnsForm

    def form_kwargs(self, session, user):
        return {'plans': self.plans(session, True)}

    def initial(self, session):
        return {'addons': [i.get('id') for i in session.step_data(self.key).get('items') or []]}

    def apply(self, session, cleaned, user, request=None):
        q = session.step_data('quantities')
        items = [{'id': p.pk, 'name': p.name, 'lines': plan_lines(p, session.client, q)}
                 for p in cleaned['addons']]
        session.set_step_data(self.key, {'items': items})
        session.save(update_fields=['data', 'updated_at'])
        return f'{len(items)} add-on(s) chosen'

    def saved_data(self, session, cleaned):
        return session.step_data(self.key)


class CustomerPricingForm(StepForm):
    discount_percent = forms.DecimalField(min_value=0, max_value=100, max_digits=5, decimal_places=2,
                                          required=False, label='Customer-specific discount (%)')
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}),
                            label='Negotiated terms')


class CustomerPricingStep(_PricingStep):
    key = 'customer_pricing'
    title = 'Customer-specific pricing'
    summary = 'A negotiated discount applied to the draft lines. Price overrides that need discount approval are requested through the draft\'s approval, never applied here.'
    form_class = CustomerPricingForm

    def apply(self, session, cleaned, user, request=None):
        from pricing import permissions as pp
        d = cleaned.get('discount_percent')
        needs = bool(d) and not pp.has(user, pp.APPROVE_DISCOUNTS, session.client)
        session.set_step_data(self.key, {'discount_percent': str(d or ''), 'notes': cleaned.get('notes', ''),
                                         'needs_discount_approval': needs})
        session.save(update_fields=['data', 'updated_at'])
        if not d:
            return 'No customer-specific discount'
        return f'Discount {d}% recorded for the draft' + (' (needs discount approval)' if needs else '')

    def saved_data(self, session, cleaned):
        return session.step_data(self.key)


for _cls in (ServicePlanStep, AddOnsStep, CustomerPricingStep):
    register_step(_cls)
