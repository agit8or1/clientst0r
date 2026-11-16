"""The nineteen steps of new-customer onboarding (the pricing ones live in
steps/pricing.py, the lifecycle-only ones in steps/lifecycle.py).

Rules every step follows:
  * Setup facts (customer record, locations, integration mappings) are written
    directly - they are what a technician would otherwise click through.
  * Anything that changes price or contract terms only creates or edits a
    DRAFT (a ContractDocument draft or a draft quote) and goes through the
    existing approval / e-signature flow from the "send for approval" step.
  * Each step also checks the permission of the thing it changes.
"""
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from onboarding import access
from onboarding.models import OnboardingSession as S
from onboarding.registry import Step, StepError, StepForm, register_step
from . import common
from .common import has_org_perm, need

NEW = (S.NEW_CUSTOMER,)


# --- 1. customer -------------------------------------------------------------------

class CustomerForm(StepForm):
    mode = forms.ChoiceField(choices=[('new', 'Create a new customer'), ('existing', 'Use an existing customer')],
                             widget=forms.RadioSelect, initial='new', required=False)
    existing = forms.ModelChoiceField(queryset=None, required=False, label='Existing customer')
    name = forms.CharField(max_length=255, required=False, label='Customer name')
    legal_name = forms.CharField(max_length=255, required=False)
    organization_type = forms.ChoiceField(required=False, label='Service type')
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=50, required=False)
    street_address = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=50, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    country = forms.CharField(max_length=100, required=False, initial='United States')
    primary_contact_name = forms.CharField(max_length=255, required=False)
    primary_contact_email = forms.EmailField(required=False)
    primary_contact_phone = forms.CharField(max_length=50, required=False)
    hide_until_activation = forms.BooleanField(
        required=False, initial=True,
        label='Keep the customer inactive until the "Activate customer" step',
        help_text='Inactive customers do not appear in client pickers. Untick to make the customer usable now.')

    def __init__(self, *args, user=None, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Organization
        self.client = client
        self.fields['existing'].queryset = access.reachable_clients(user) if user else Organization.objects.none()
        self.fields['organization_type'].choices = Organization.ORGANIZATION_TYPE_CHOICES
        if client is not None:
            del self.fields['mode'], self.fields['existing'], self.fields['hide_until_activation']

    def clean(self):
        data = super().clean()
        from core.models import Organization
        if self.client is None and (data.get('mode') or 'new') == 'existing':
            if not data.get('existing'):
                self.add_error('existing', 'Choose the customer.')
            return data
        if not (data.get('name') or '').strip():
            self.add_error('name', 'Enter the customer name.')
        else:
            clash = Organization.objects.filter(name__iexact=data['name'].strip())
            if self.client is not None:
                clash = clash.exclude(pk=self.client.pk)
            if clash.exists():
                self.add_error('name', 'A customer with this name already exists. Use "an existing customer" to '
                                       'continue with it.')
        return data


CUSTOMER_FIELDS = ('name', 'legal_name', 'organization_type', 'email', 'phone', 'street_address', 'city', 'state',
                   'postal_code', 'country', 'primary_contact_name', 'primary_contact_email',
                   'primary_contact_phone')


def _unique_slug(name):
    from core.models import Organization
    base = slugify(name)[:200] or 'customer'
    slug, n = base, 1
    while Organization.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    return slug


class CustomerStep(Step):
    key = 'customer'
    title = 'Customer'
    summary = 'Create the customer record, or continue with one that already exists. This is the only step needed to create the customer.'
    needs_client = False
    skippable = False
    form_class = CustomerForm

    def form_kwargs(self, session, user):
        return {'user': user, 'client': session.client}

    def initial(self, session):
        c = session.client
        if c is None:
            return {}
        return {f: getattr(c, f) for f in CUSTOMER_FIELDS}

    def apply(self, session, cleaned, user, request=None):
        from accounts.delegation import is_customer_actor
        from accounts.models import Membership
        from core.models import Organization
        if is_customer_actor(user):
            raise StepError('Customer users cannot create customers.')
        if session.client_id:
            client = session.client
            if not has_org_perm(user, client, 'org_manage_settings'):
                raise StepError('You need the "org_manage_settings" permission to change the customer record.')
            for f in CUSTOMER_FIELDS:
                if f in cleaned:
                    setattr(client, f, cleaned[f] if f != 'name' else cleaned[f].strip())
            client.save()
            return f'Updated customer "{client.name}"'
        if (cleaned.get('mode') or 'new') == 'existing':
            client = cleaned['existing']
            if not access.can_use(user, client):
                raise StepError('You cannot run onboarding wizards for that customer.')
            verb = 'Continuing with existing customer'
        else:
            client = Organization(slug=_unique_slug(cleaned['name']), is_active=not cleaned.get('hide_until_activation'))
            for f in CUSTOMER_FIELDS:
                setattr(client, f, (cleaned.get(f) or '').strip() if f != 'organization_type' else cleaned.get(f, ''))
            if not client.country:
                client.country = 'United States'
            client.save()
            Membership.objects.get_or_create(user=user, organization=client,
                                             defaults={'role': 'owner', 'is_active': True})
            verb = 'Created customer'
        session.client = client
        if not session.title:
            session.title = f'New customer: {client.name}'[:255]
        session.save(update_fields=['client', 'title', 'updated_at'])
        return f'{verb} "{client.name}"'


# --- 2. locations ---------------------------------------------------------------------

class LocationForm(StepForm):
    name = forms.CharField(max_length=255, label='Location name', initial='Headquarters')
    location_type = forms.ChoiceField()
    street_address = forms.CharField(max_length=255)
    city = forms.CharField(max_length=100)
    state = forms.CharField(max_length=50, required=False)
    postal_code = forms.CharField(max_length=20)
    country = forms.CharField(max_length=100, initial='United States')
    is_primary = forms.BooleanField(required=False, label='Primary location')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from locations.models import Location
        self.fields['location_type'].choices = Location.LOCATION_TYPES


class LocationsStep(Step):
    key = 'locations'
    title = 'Locations'
    summary = 'Add the customer\'s sites. Run the step again to add more.'
    form_class = LocationForm

    def initial(self, session):
        c = session.client
        if c is None:
            return {}
        out = {f: getattr(c, f) for f in ('street_address', 'city', 'state', 'postal_code', 'country')}
        out['is_primary'] = not c.locations.exists() if hasattr(c, 'locations') else True
        return out

    def permission_denial(self, user, session):
        return need(user, session.client, 'assets_create', 'creating locations')

    def context(self, session, user=None):
        from locations.models import Location
        return {'existing_locations': Location.objects.filter(organization=session.client) if session.client else []}

    def apply(self, session, cleaned, user, request=None):
        from locations.models import Location
        primary = cleaned['is_primary'] or not Location.objects.filter(organization=session.client,
                                                                        is_primary=True).exists()
        loc = Location.objects.create(
            organization=session.client, name=cleaned['name'].strip(), location_type=cleaned['location_type'],
            street_address=cleaned['street_address'].strip(), city=cleaned['city'].strip(),
            state=cleaned['state'].strip(), postal_code=cleaned['postal_code'].strip(),
            country=cleaned['country'].strip(), status='active', is_primary=primary)
        ids = list(session.step_data(self.key).get('location_ids') or []) + [loc.pk]
        session.set_step_data(self.key, {'location_ids': ids})
        session.save(update_fields=['data', 'updated_at'])
        return f'Added location "{loc.name}"'

    def saved_data(self, session, cleaned):
        return session.step_data(self.key)


# --- 4. quantities ----------------------------------------------------------------------

class QuantitiesForm(StepForm):
    users = forms.IntegerField(min_value=0, required=False, label='Users')
    devices = forms.IntegerField(min_value=0, required=False, label='Workstations / devices')
    servers = forms.IntegerField(min_value=0, required=False, label='Servers')
    locations = forms.IntegerField(min_value=0, required=False, label='Locations')
    price_users = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False,
                                     label='Price per user per month')
    price_devices = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False,
                                       label='Price per device per month')
    price_servers = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False,
                                       label='Price per server per month')
    price_locations = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False,
                                         label='Price per location per month')


class QuantitiesStep(Step):
    key = 'quantities'
    title = 'Quantities'
    summary = 'How many users, devices, servers and locations are covered, and (without a price book) the monthly unit prices. These become the lines of the draft quote or agreement; nothing is billed from here.'
    needs_client = False
    form_class = QuantitiesForm
    commercial = True

    def apply(self, session, cleaned, user, request=None):
        parts = [f'{cleaned[k]} {k}' for k in ('users', 'devices', 'servers', 'locations') if cleaned.get(k)]
        return 'Recorded ' + (', '.join(parts) if parts else 'no quantities')


# --- 7. contract template -----------------------------------------------------------------

class TemplateForm(StepForm):
    template = forms.ModelChoiceField(queryset=None, required=False, empty_label='Blank agreement',
                                      label='Contract template')
    title = forms.CharField(max_length=255, required=False, label='Agreement title',
                            help_text='Leave empty to use the template name.')

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        from contracts.models import ContractTemplate
        qs = ContractTemplate.objects.filter(is_active=True)
        if client is not None:
            qs = qs.filter(Q(organization__isnull=True) | Q(organization=client))
        self.fields['template'].queryset = qs.order_by('name')


class ContractTemplateStep(Step):
    key = 'contract_template'
    title = 'Contract template'
    summary = 'Start the agreement as a draft from a template. It stays a draft until you send it for approval.'
    form_class = TemplateForm
    commercial = True

    def form_kwargs(self, session, user):
        return {'client': session.client}

    def permission_denial(self, user, session):
        from contracts import permissions as perms
        return common.contract_denial(user, session.client, perms.EDIT)

    def context(self, session, user=None):
        return {'agreement': session.agreement}

    def apply(self, session, cleaned, user, request=None):
        from contracts import services
        from contracts.models import ContractDocument as D
        if session.agreement_id and session.agreement.status != D.DRAFT:
            raise StepError('The agreement already left draft; revise it from the contracts page.')
        if session.agreement_id:
            return f'Agreement {session.agreement.reference} already exists; kept it as it is'
        try:
            doc = services.create_contract(session.client, user, template=cleaned.get('template'),
                                           title=cleaned.get('title') or '', request=request)
        except services.ContractError as exc:
            raise StepError(str(exc))
        session.agreement = doc
        session.save(update_fields=['agreement', 'updated_at'])
        common.sync_agreement_settings(session, user)
        return f'Created draft agreement {doc.reference}'


# --- 8. SLA -----------------------------------------------------------------------------------

class SLAForm(StepForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from psa.models import TicketPriority
        self.priorities = list(TicketPriority.objects.all().order_by('sort_order'))
        for p in self.priorities:
            self.fields[f'response_{p.code}'] = forms.IntegerField(
                min_value=1, required=False, label=f'{p.code} {p.name}: first response (minutes)',
                widget=forms.NumberInput(attrs={'placeholder': str(p.response_target_minutes)}))
            self.fields[f'resolution_{p.code}'] = forms.IntegerField(
                min_value=1, required=False, label=f'{p.code} {p.name}: resolution (minutes)',
                widget=forms.NumberInput(attrs={'placeholder': str(p.resolution_target_minutes)}))
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'form-control')


class SLAStep(Step):
    key = 'sla'
    title = 'SLA'
    summary = 'Per-priority response and resolution targets for this customer. Blank keeps the default for that priority.'
    form_class = SLAForm

    def initial(self, session):
        out = {}
        for code, entry in ((session.client.sla_overrides if session.client else {}) or {}).items():
            if isinstance(entry, dict):
                out[f'response_{code}'] = entry.get('response_minutes')
                out[f'resolution_{code}'] = entry.get('resolution_minutes')
        return out

    def permission_denial(self, user, session):
        return need(user, session.client, 'org_manage_settings', 'changing the customer\'s SLA')

    def apply(self, session, cleaned, user, request=None):
        from psa.models import TicketPriority
        matrix = {}
        for p in TicketPriority.objects.all():
            entry = {}
            if cleaned.get(f'response_{p.code}'):
                entry['response_minutes'] = cleaned[f'response_{p.code}']
            if cleaned.get(f'resolution_{p.code}'):
                entry['resolution_minutes'] = cleaned[f'resolution_{p.code}']
            if entry:
                matrix[p.code] = entry
        client = session.client
        client.sla_overrides = matrix
        client.save(update_fields=['sla_overrides', 'updated_at'])
        return f'SLA overrides set for {len(matrix)} priorit{"y" if len(matrix) == 1 else "ies"}'


# --- 9. account manager -----------------------------------------------------------------------

class AccountManagerForm(StepForm):
    user = forms.ModelChoiceField(queryset=None, label='Account manager')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from psa.visibility import msp_staff_q
        self.fields['user'].queryset = get_user_model().objects.filter(msp_staff_q(), is_active=True).order_by(
            'first_name', 'username')
        self.fields['user'].label_from_instance = lambda u: u.get_full_name() or u.username


class AccountManagerStep(Step):
    key = 'account_manager'
    title = 'Account manager'
    summary = 'The technician who owns the relationship. The platform has no customer-level account manager field, so this is recorded here and set on the agreement draft (shown on the agreement and used for its notifications).'
    form_class = AccountManagerForm
    commercial = True

    def apply(self, session, cleaned, user, request=None):
        am = cleaned['user']
        session.set_step_data(self.key, {'user': am.pk})
        session.save(update_fields=['data', 'updated_at'])
        common.sync_agreement_settings(session, user)
        where = ' and set on the agreement draft' if session.agreement_id else ' (applied when the agreement draft is created)'
        return f'Account manager {am.get_full_name() or am.username} recorded{where}'


# --- 10. billing frequency ----------------------------------------------------------------------

class BillingFrequencyForm(StepForm):
    frequency = forms.ChoiceField(label='Billing frequency')
    first_invoice_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}),
                                         label='First invoice date')
    proration = forms.BooleanField(required=False, initial=True, label='Prorate the first period')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from contracts.models import BILLING_FREQUENCIES
        self.fields['frequency'].choices = BILLING_FREQUENCIES


class BillingFrequencyStep(Step):
    key = 'billing_frequency'
    title = 'Billing frequency'
    summary = 'How often the customer is invoiced. Set on the agreement draft; the billing contract is made from the signed agreement.'
    form_class = BillingFrequencyForm
    commercial = True

    def apply(self, session, cleaned, user, request=None):
        session.set_step_data(self.key, {'frequency': cleaned['frequency']})
        session.save(update_fields=['data', 'updated_at'])
        common.sync_agreement_settings(session, user)
        return f'Billing frequency {cleaned["frequency"]}'


# --- 11. accounting mapping ----------------------------------------------------------------------

class AccountingForm(StepForm):
    connection = forms.ModelChoiceField(queryset=None, label='Accounting connection')
    provider_customer_id = forms.CharField(max_length=120, label='Customer ID in the accounting system')
    display_name = forms.CharField(max_length=255, required=False, label='Name in the accounting system')

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        from integrations.models import AccountingConnection
        qs = AccountingConnection.objects.filter(is_active=True)
        if session is not None:
            qs = qs.filter(common.owned_by_scope(session))
        self.fields['connection'].queryset = qs.order_by('name')


class AccountingStep(Step):
    key = 'accounting_mapping'
    title = 'Accounting customer'
    summary = 'Link the customer to its record in QuickBooks Online or Xero so invoices can be pushed. Enter the existing customer\'s ID; creating a new customer in the provider is done from the accounting page.'
    form_class = AccountingForm

    def form_kwargs(self, session, user):
        return {'session': session}

    def permission_denial(self, user, session):
        return '' if common.can_configure_integrations(user, session) else \
            'You need the "integrations_configure" permission (or platform administration) to map accounting customers.'

    def apply(self, session, cleaned, user, request=None):
        from integrations.models import AccountingCustomerLink
        conn, pid = cleaned['connection'], cleaned['provider_customer_id'].strip()
        taken = AccountingCustomerLink.objects.filter(connection=conn, provider_customer_id=pid).exclude(
            client_org=session.client).first()
        if taken is not None:
            raise StepError('That accounting customer is already linked to another customer.')
        AccountingCustomerLink.objects.update_or_create(
            connection=conn, client_org=session.client,
            defaults={'organization': conn.organization, 'provider_customer_id': pid,
                      'display_name': cleaned.get('display_name') or session.client.name, 'source': 'matched'})
        return f'Linked to {conn.name} customer {pid}'


# --- 12. payment terms / method --------------------------------------------------------------------

TERMS = [('Due on receipt', 'Due on receipt'), ('Net 15', 'Net 15'), ('Net 30', 'Net 30'), ('Net 45', 'Net 45'),
         ('Net 60', 'Net 60')]
METHODS = [('', 'Not decided'), ('invoice', 'Invoice / bank transfer'), ('card', 'Card on file'),
           ('direct_debit', 'Direct debit (ACH / SEPA)')]


def payments_installed():
    from django.apps import apps
    return apps.is_installed('payments')


class PaymentForm(StepForm):
    terms = forms.ChoiceField(choices=TERMS, initial='Net 30', label='Payment terms')
    method = forms.ChoiceField(choices=METHODS, required=False, label='Preferred payment method')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not payments_installed():
            del self.fields['method']


class PaymentStep(Step):
    key = 'payment'
    title = 'Payment terms and method'
    summary = 'Payment terms go on the agreement draft. The preferred payment method is available once the payments feature is enabled; collecting the card or mandate itself is done by the customer through the payment setup link.'
    form_class = PaymentForm
    commercial = True

    def context(self, session, user=None):
        return {'note': '' if payments_installed() else
                'Payment methods: available once payments is enabled. Only the terms are recorded for now.'}

    def apply(self, session, cleaned, user, request=None):
        session.set_step_data(self.key, {'terms': cleaned['terms'], 'method': cleaned.get('method', '')})
        session.save(update_fields=['data', 'updated_at'])
        common.sync_agreement_settings(session, user)
        return f'Terms {cleaned["terms"]}' + (f', preferred method {cleaned["method"]}' if cleaned.get('method') else '')

    def saved_data(self, session, cleaned):
        return session.step_data(self.key)


# --- 13. distributors ----------------------------------------------------------------------------------

class DistributorForm(StepForm):
    connections = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Distributors',
                                                 widget=forms.CheckboxSelectMultiple)
    account_numbers = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}),
                                      label='Customer account numbers / notes')

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        from integrations.models import DistributorConnection
        qs = DistributorConnection.objects.filter(is_active=True)
        if session is not None:
            qs = qs.filter(common.owned_by_scope(session))
        self.fields['connections'].queryset = qs.order_by('name')
        self.fields['connections'].widget.attrs.pop('class', None)


class DistributorStep(Step):
    key = 'distributors'
    title = 'Distributor relationships'
    summary = 'Which distributors will supply this customer. The platform has no per-customer distributor mapping, so the choice and account numbers are kept on this onboarding record only.'
    form_class = DistributorForm

    def form_kwargs(self, session, user):
        return {'session': session}

    def apply(self, session, cleaned, user, request=None):
        names = ', '.join(c.name for c in cleaned['connections']) or 'none'
        return f'Recorded distributors: {names}'

    def saved_data(self, session, cleaned):
        return {'connections': [c.pk for c in cleaned['connections']], 'names': [c.name for c in cleaned['connections']],
                'account_numbers': cleaned.get('account_numbers', '')}


# --- 14. RMM ---------------------------------------------------------------------------------------------

class RMMForm(StepForm):
    connection = forms.ModelChoiceField(queryset=None, label='RMM connection')
    rmm_client_id = forms.CharField(max_length=120, required=False, label='RMM customer / tenant ID')
    rmm_client_name = forms.CharField(max_length=255, required=False, label='RMM customer name',
                                      help_text='Used when the RMM identifies customers by name only.')

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        from integrations.models import RMMConnection
        qs = RMMConnection.objects.filter(is_active=True)
        if session is not None:
            qs = qs.filter(common.owned_by_scope(session))
        self.fields['connection'].queryset = qs.order_by('name')

    def clean(self):
        data = super().clean()
        if not (data.get('rmm_client_id') or data.get('rmm_client_name')):
            raise forms.ValidationError('Enter the RMM customer ID or name.')
        return data


class RMMStep(Step):
    key = 'rmm'
    title = 'RMM integration'
    summary = 'Map this customer to its tenant / site in the RMM so its devices land under the right customer on the next sync.'
    form_class = RMMForm

    def form_kwargs(self, session, user):
        return {'session': session}

    def permission_denial(self, user, session):
        return '' if common.can_configure_integrations(user, session) else \
            'You need the "integrations_configure" permission (or platform administration) to map RMM customers.'

    def apply(self, session, cleaned, user, request=None):
        from integrations.rmm_association import CustomerIdentity, clean_external_id, map_customer
        cid = clean_external_id(cleaned.get('rmm_client_id'))
        name = (cleaned.get('rmm_client_name') or '').strip()
        identity = (CustomerIdentity(f'id:{cid}', cid, name, False) if cid
                    else CustomerIdentity(f'name:{name.casefold()}', '', name, True))
        map_customer(cleaned['connection'], identity, session.client)
        return f'Mapped RMM customer {identity.label} on {cleaned["connection"].name}'


# --- 15. backup monitoring ---------------------------------------------------------------------------------

def _backup_model():
    from django.apps import apps
    try:
        return apps.get_model('backup_monitoring', 'BackupConnection')
    except LookupError:
        return None


class BackupForm(StepForm):
    connection = forms.ModelChoiceField(queryset=None, label='Backup connection')

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        model = _backup_model()
        qs = model.objects.filter(active=True) if model is not None else []
        if model is not None and session is not None:
            ids = [i for i in (session.organization_id, session.client_id) if i]
            qs = qs.filter(Q(organization_id__in=ids) | Q(customer_id=session.client_id))
        self.fields['connection'].queryset = qs.order_by('name') if model is not None else \
            get_user_model().objects.none()


class BackupStep(Step):
    key = 'backup_monitoring'
    title = 'Backup monitoring'
    summary = 'Pin a backup connection to this customer so the jobs it reports are monitored under them.'
    requires_apps = ('backup_monitoring',)
    feature_name = 'backup monitoring'
    form_class = BackupForm

    def extra_available(self):
        return _backup_model() is not None

    def form_kwargs(self, session, user):
        return {'session': session}

    def permission_denial(self, user, session):
        return '' if common.can_configure_integrations(user, session) else \
            'You need the "integrations_configure" permission to attach backup connections.'

    def apply(self, session, cleaned, user, request=None):
        conn = cleaned['connection']
        conn.customer = session.client
        conn.save(update_fields=['customer', 'updated_at'])
        return f'Backup connection "{conn.name}" pinned to the customer'


# --- 16. warranty ----------------------------------------------------------------------------------------------

class WarrantyForm(StepForm):
    track = forms.BooleanField(required=False, initial=True, label='Track warranty expiry for this customer\'s devices')
    note = forms.CharField(required=False, max_length=300, label='Note')


class WarrantyStep(Step):
    key = 'warranty'
    title = 'Warranty tracking'
    summary = 'Warranty lookups (Dell, HP, Lenovo) run for every customer\'s devices once they are in the asset list and the platform setting is on; there is no per-customer switch, so this records the decision and shows the platform status.'
    form_class = WarrantyForm

    def context(self, session, user=None):
        from core.models import SystemSetting
        try:
            enabled = bool(SystemSetting.get_settings().warranty_checks_enabled)
        except Exception:
            enabled = False
        return {'note': 'Platform warranty lookups are ' + ('enabled.' if enabled else
                'switched off (Settings, Assets). Turn them on there for the lookups to run.')}

    def apply(self, session, cleaned, user, request=None):
        return 'Warranty tracking ' + ('wanted' if cleaned.get('track') else 'not wanted')


# --- 17. quote / agreement ---------------------------------------------------------------------------------------

class DocumentForm(StepForm):
    document = forms.ChoiceField(choices=[('agreement', 'Agreement (draft contract document)'),
                                          ('quote', 'Quote (draft)'), ('both', 'Both')], initial='agreement')
    valid_days = forms.IntegerField(min_value=1, max_value=365, initial=30, required=False,
                                    label='Quote valid for (days)')
    leave_out_unpriced = forms.BooleanField(
        required=False, label='Create the draft without the items whose price is missing',
        help_text='Missing prices are never filled in with zero; they are left out and listed on the draft note.')


class GenerateDocumentStep(Step):
    key = 'generate_document'
    title = 'Quote or agreement'
    summary = 'Build the draft from the quantities, plan and prices recorded so far. Drafts are never sent from here.'
    form_class = DocumentForm
    commercial = True

    def context(self, session, user=None):
        return {'lines': common.lines_from_session(session), 'agreement': session.agreement, 'quote': session.quote,
                'missing_prices': common.missing_prices(session)}

    def permission_denial(self, user, session):
        return ''

    def apply(self, session, cleaned, user, request=None):
        want = cleaned['document']
        made = []
        missing = common.missing_prices(session)
        if missing and not cleaned.get('leave_out_unpriced'):
            raise StepError('These have no price: ' + '; '.join(missing) +
                            '. Enter or fix them, or tick the box to leave them out of the draft.')
        if want in ('agreement', 'both'):
            from contracts import permissions as perms
            why = common.contract_denial(user, session.client, perms.EDIT)
            if why:
                raise StepError(why)
            made.append(build_agreement_draft(session, user, request))
        if want in ('quote', 'both'):
            why = need(user, session.client, 'crm_manage_pipeline', 'creating quotes')
            if why:
                raise StepError(why)
            made.append(build_quote_draft(session, user, common.lines_from_session(session),
                                          f'{session.display_title}', cleaned.get('valid_days') or 30))
        return 'Draft ready: ' + ', '.join(made)


def build_agreement_draft(session, user, request=None, lines=None):
    from contracts import services
    from contracts.models import ContractDocument as D
    if session.agreement_id is None:
        doc = services.create_contract(session.client, user, title=f'Services agreement: {session.client.name}',
                                       request=request)
        session.agreement = doc
        session.save(update_fields=['agreement', 'updated_at'])
    doc = session.agreement
    if doc.status != D.DRAFT:
        raise StepError('The agreement already left draft; revise it from the contracts page.')
    lines = common.lines_from_session(session) if lines is None else lines
    try:
        services.save_draft(doc, {'line_items': lines}, user)
    except services.ContractError as exc:
        raise StepError(str(exc))
    common.sync_agreement_settings(session, user)
    session.agreement.refresh_from_db()
    return f'agreement {session.agreement.reference}'


def build_quote_draft(session, user, lines, title, valid_days=30):
    from datetime import timedelta
    from decimal import Decimal
    from core.models import SystemSetting
    from psa.models import Quote, QuoteLineItem
    client = session.client
    tax = SystemSetting.get_settings().psa_default_tax_rate or Decimal('0')
    quote = Quote.objects.create(organization=client, client_org=client, title=title[:300], status='draft',
                                 valid_until=timezone.localdate() + timedelta(days=valid_days), tax_rate=tax,
                                 created_by=user,
                                 description=f'Created by the onboarding wizard (session {session.pk}).')
    for i, ln in enumerate(lines):
        qty = Decimal(str(ln['quantity']))
        price = common.money(ln['unit_price'])
        disc = common.money(ln.get('discount_percent'))
        if disc:
            price = (price * (Decimal('100') - disc) / Decimal('100')).quantize(Decimal('0.01'))
        QuoteLineItem.objects.create(quote=quote, sort_order=i, description=ln['description'][:300],
                                     quantity=qty, unit_price=price, is_taxable=bool(ln.get('taxable')))
    quote.recompute_totals()
    session.quote = quote
    session.save(update_fields=['quote', 'updated_at'])
    return f'quote {quote.quote_number}'


# --- 18. approval and signature --------------------------------------------------------------------------------------

class SubmitForm(StepForm):
    submit_agreement = forms.BooleanField(required=False, initial=True, label='Submit the agreement for approval')
    submit_quote = forms.BooleanField(required=False, initial=True, label='Send the quote through its approval chain')
    send_for_signature = forms.BooleanField(
        required=False, label='Also send the agreement for signature when no approval is needed',
        help_text='Needs the permission to send contracts. Signers are the agreement\'s listed signers.')

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        if session is not None:
            if session.agreement_id is None:
                del self.fields['submit_agreement'], self.fields['send_for_signature']
            if session.quote_id is None:
                del self.fields['submit_quote']


class SendForApprovalStep(Step):
    key = 'send_approval'
    title = 'Send for approval and signature'
    summary = 'Hands the drafts to the existing approval and e-signature flows. Nothing becomes active until it is approved and signed.'
    form_class = SubmitForm
    commercial = True

    def form_kwargs(self, session, user):
        return {'session': session}

    def blocked_reason(self, session):
        base = super().blocked_reason(session)
        if base:
            return base
        if session.agreement_id is None and session.quote_id is None:
            return 'Generate a quote or agreement first.'
        return ''

    def context(self, session, user=None):
        return {'agreement': session.agreement, 'quote': session.quote}

    def apply(self, session, cleaned, user, request=None):
        from contracts import permissions as perms
        from contracts import services
        from contracts.models import ContractDocument as D
        did = []
        if cleaned.get('submit_agreement') and session.agreement_id:
            doc = session.agreement
            why = common.contract_denial(user, session.client, perms.SUBMIT)
            if why:
                raise StepError(why)
            if doc.status == D.DRAFT:
                try:
                    services.submit(doc, user, request=request)
                except services.ContractError as exc:
                    raise StepError(str(exc))
                doc.refresh_from_db()
            did.append(f'agreement {doc.reference} is "{doc.get_status_display()}"')
            if doc.status == D.READY and cleaned.get('send_for_signature'):
                why = common.contract_denial(user, session.client, perms.SEND)
                if why:
                    raise StepError(why)
                try:
                    services.send(doc, user, email=True, request=request)
                except services.ContractError as exc:
                    raise StepError(str(exc))
                doc.refresh_from_db()
                did.append('sent for signature')
        if cleaned.get('submit_quote') and session.quote_id:
            why = need(user, session.client, 'crm_manage_pipeline', 'sending quotes for approval')
            if why:
                raise StepError(why)
            chain = session.quote.send_for_approval(user=user)
            did.append(f'quote {session.quote.quote_number} in approval ({len(chain)} stage(s))')
        if not did:
            raise StepError('Choose something to submit.')
        _status_from_drafts(session)
        return '; '.join(did)


def _status_from_drafts(session):
    from contracts.models import ContractDocument as D
    ag = session.agreement
    if ag is not None and ag.status in D.OPEN_FOR_SIGNING:
        session.status = S.AWAITING_SIGNATURE
    else:
        session.status = S.AWAITING_APPROVAL
    session.save(update_fields=['status', 'updated_at'])


# --- 19. activate -------------------------------------------------------------------------------------------------------

class ActivateForm(StepForm):
    activate_unsigned = forms.BooleanField(
        required=False, label='Activate even though the agreement is not signed yet',
        help_text='Only tick this when the customer is starting before the paperwork is complete.')


class ActivateStep(Step):
    key = 'activate'
    title = 'Activate customer'
    summary = 'Makes the customer active and closes the wizard. When the agreement is signed, a draft billing contract is created for review.'
    form_class = ActivateForm

    def permission_denial(self, user, session):
        return need(user, session.client, 'org_manage_settings', 'activating the customer')

    def context(self, session, user=None):
        return {'agreement': session.agreement}

    def apply(self, session, cleaned, user, request=None):
        from contracts import services
        from contracts.models import ContractDocument as D
        from onboarding import engine
        ag = session.agreement
        extra = ''
        if ag is not None and ag.status != D.SIGNED and not cleaned.get('activate_unsigned'):
            raise StepError(f'Agreement {ag.reference} is "{ag.get_status_display()}", not signed. Tick the box to '
                            'activate anyway.')
        client = session.client
        if ag is not None and ag.status == D.SIGNED:
            try:
                bc = services.create_billing_contract(ag, user, request)
                extra = f'; draft billing contract #{bc.pk} for review'
            except Exception as exc:  # contracts permission / state
                extra = f'; billing contract not created ({exc})'
        client.is_active = True
        client.save(update_fields=['is_active', 'updated_at'])
        engine.complete_session(session, user)
        return f'Customer "{client.name}" activated{extra}'


# --- registration -----------------------------------------------------------------------------------------------------------

for _cls in (CustomerStep, LocationsStep, QuantitiesStep, ContractTemplateStep, SLAStep, AccountManagerStep,
             BillingFrequencyStep, AccountingStep, PaymentStep, DistributorStep, RMMStep, BackupStep,
             WarrantyStep, GenerateDocumentStep, SendForApprovalStep, ActivateStep):
    register_step(_cls)

# Order for a new customer. The pricing steps (service plan, add-ons,
# customer-specific pricing) are registered by steps/pricing.py into their
# slots; see ONBOARDING_STEPS.md.
from onboarding.registry import set_kind_steps  # noqa: E402

set_kind_steps(S.NEW_CUSTOMER, [
    'customer', 'locations', 'service_plan', 'quantities', 'add_ons', 'customer_pricing', 'contract_template',
    'sla', 'account_manager', 'billing_frequency', 'accounting_mapping', 'payment', 'distributors', 'rmm',
    'backup_monitoring', 'warranty', 'generate_document', 'send_approval', 'activate',
])
