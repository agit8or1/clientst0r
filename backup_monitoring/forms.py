from django import forms
from django.utils import timezone

from vault.secret_fields import SECRET_PLACEHOLDER

from .models import (BackupAlertPolicy, BackupConnection, ProtectedSystem, RestoreTest)
from .providers import is_push_provider


class BackupConnectionForm(forms.ModelForm):
    api_token = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'off'}),
        label='API token',
        help_text='Proxmox Backup Server: user@realm!tokenname:secret. Stored encrypted; never shown again.')

    class Meta:
        model = BackupConnection
        fields = ['name', 'provider', 'organization', 'customer', 'base_url', 'verify_tls',
                  'allow_private_address', 'active']

    def __init__(self, *args, orgs=None, msp_wide=False, can_allow_private=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.msp_wide = msp_wide
        # SR-02: only MSP staff who manage every customer may point a
        # connection at a private address; for others the field is shown
        # read-only and a posted value is ignored (disabled field).
        if not can_allow_private:
            self.fields['allow_private_address'].disabled = True
        if orgs is not None:
            self.fields['organization'].queryset = orgs
            self.fields['customer'].queryset = orgs
        # Empty owner = MSP-wide connection (one server, many customers):
        # only users who reach every customer may create one.
        self.fields['organization'].required = not msp_wide
        self.fields['organization'].empty_label = 'MSP-wide (all customers)' if msp_wide else None
        self.fields['customer'].required = False
        if self.instance.pk and self.instance.credentials:
            self.fields['api_token'].widget.attrs['placeholder'] = SECRET_PLACEHOLDER

    def clean(self):
        data = super().clean()
        if not data.get('organization') and not self.msp_wide:
            self.add_error('organization', 'Choose a customer.')
        provider = data.get('provider')
        if provider and not is_push_provider(provider):
            url = data.get('base_url') or ''
            if not url.lower().startswith('https://'):
                self.add_error('base_url', 'An https:// URL is required for this provider.')
            elif url:
                from core.safe_http import OutboundPolicy, UnsafeURLError, configured_service_policy, validate_url
                base = configured_service_policy()
                policy = (OutboundPolicy(allow_lan=True, allow_local=base.allow_local, allowed_ports=None)
                          if data.get('allow_private_address') else base)
                try:
                    validate_url(url, policy)
                except UnsafeURLError as exc:
                    hint = (' Tick "Server is on a private network" for a LAN address.'
                            if not data.get('allow_private_address') and not self.fields['allow_private_address'].disabled
                            else '')
                    self.add_error('base_url', f'This address is not allowed ({exc}).{hint}')
            if not data.get('api_token') and not (self.instance.pk and self.instance.credentials):
                self.add_error('api_token', 'An API token is required for this provider.')
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        token = self.cleaned_data.get('api_token')
        if token:
            obj.set_credentials({'api_token': token.strip()})
        created = obj.pk is None
        if obj.is_push and (created or not obj.ingest_secret):
            obj.issue_ingest_secret()
        if commit:
            obj.save()
        return obj


class RestoreTestForm(forms.ModelForm):
    class Meta:
        model = RestoreTest
        fields = ['organization', 'system', 'system_name', 'tested_on', 'result', 'verified_by_name', 'notes']
        widgets = {'tested_on': forms.DateInput(attrs={'type': 'date'}), 'notes': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, orgs=None, systems=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['organization'].queryset = orgs
        self.fields['system'].queryset = systems
        self.fields['system'].required = False
        self.fields['tested_on'].initial = timezone.now().date()

    def clean(self):
        data = super().clean()
        system, org = data.get('system'), data.get('organization')
        if system and org and system.customer_id != org.pk:
            self.add_error('system', 'That system belongs to a different customer.')
        if not system and not (data.get('system_name') or '').strip():
            self.add_error('system', 'Choose a monitored system or type its name.')
        if data.get('tested_on') and data['tested_on'] > timezone.now().date():
            self.add_error('tested_on', 'A restore test cannot be dated in the future.')
        return data


class BackupAlertPolicyForm(forms.ModelForm):
    class Meta:
        model = BackupAlertPolicy
        exclude = ['organization']


class ProtectedSystemForm(forms.ModelForm):
    class Meta:
        model = ProtectedSystem
        fields = ['name', 'customer', 'asset']

    def __init__(self, *args, orgs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = orgs
        self.fields['customer'].required = True
        from assets.models import Asset
        self.fields['asset'].required = False
        self.fields['asset'].queryset = Asset.objects.filter(organization__in=orgs).order_by('name')

    def clean(self):
        data = super().clean()
        asset, customer = data.get('asset'), data.get('customer')
        if asset and customer and asset.organization_id != customer.pk:
            self.add_error('asset', "That asset belongs to a different customer.")
        return data


class ManualSystemForm(ProtectedSystemForm):
    class Meta(ProtectedSystemForm.Meta):
        fields = ['connection', 'name', 'customer', 'asset']

    def __init__(self, *args, connections=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['connection'].queryset = connections
