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

from onboarding.models import OnboardingSession as S
from onboarding.registry import Step, StepForm, register_step


def plan_model():
    try:
        return apps.get_model('pricing', 'ServicePlan')
    except LookupError:
        return None


def plan_price(plan):
    """Monthly list price of a plan from its included price book items, or
    None when it cannot be worked out (the technician then enters it)."""
    try:
        total = Decimal('0')
        found = False
        for pi in plan.plan_items.select_related('item'):
            price = getattr(pi.item, 'default_price', None)
            if price is not None and getattr(pi, 'is_included', True):
                total += Decimal(str(price)) * Decimal(str(pi.quantity))
                found = True
        return total if found else None
    except Exception:
        return None


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
        return model.objects.filter(is_active=True, is_addon=addon, organization_id=session.organization_id)


class ServicePlanForm(StepForm):
    plan = forms.ModelChoiceField(queryset=None, label='Service plan')
    monthly_price = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, required=False,
                                       label='Monthly price',
                                       help_text='Blank uses the plan\'s list price when it can be worked out.')

    def __init__(self, *args, plans=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plan'].queryset = plans


class ServicePlanStep(_PricingStep):
    key = 'service_plan'
    title = 'Service plan'
    summary = 'Choose the plan from the price book. The choice feeds the draft quote or agreement; the plan is attached to the customer after signature.'
    form_class = ServicePlanForm

    def form_kwargs(self, session, user):
        return {'plans': self.plans(session, False)}

    def initial(self, session):
        d = session.step_data(self.key)
        return {'plan': d.get('plan_id'), 'monthly_price': d.get('monthly_price')}

    def apply(self, session, cleaned, user, request=None):
        plan = cleaned['plan']
        price = cleaned.get('monthly_price')
        price = price if price is not None else plan_price(plan)
        session.set_step_data(self.key, {'plan_id': plan.pk, 'plan_name': plan.name,
                                         'monthly_price': str(price) if price is not None else ''})
        session.save(update_fields=['data', 'updated_at'])
        return f'Plan "{plan.name}" chosen' + ('' if price is not None else ' (no list price: enter it on the draft)')

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
    summary = 'Optional add-on plans from the price book, added as lines on the draft.'
    form_class = AddOnsForm

    def form_kwargs(self, session, user):
        return {'plans': self.plans(session, True)}

    def initial(self, session):
        return {'addons': [i.get('id') for i in session.step_data(self.key).get('items') or []]}

    def apply(self, session, cleaned, user, request=None):
        items = []
        for plan in cleaned['addons']:
            price = plan_price(plan)
            items.append({'id': plan.pk, 'name': plan.name, 'quantity': 1,
                          'price': str(price) if price is not None else ''})
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
        d = cleaned.get('discount_percent')
        return f'Discount {d}% recorded for the draft' if d else 'No customer-specific discount'


for _cls in (ServicePlanStep, AddOnsStep, CustomerPricingStep):
    register_step(_cls)
