"""
Integrations forms
"""
from django import forms
from vault.secret_fields import SecretInput
from .models import PSAConnection, RMMConnection, UnifiConnection, M365Connection, OmadaConnection, GrandstreamConnection


class KeepStoredSecretsMixin:
    """Never echo stored secrets into the form; blank keeps the stored value.

    `SECRET_FIELDS` maps form field -> (provider_type, credential key). On an
    edit the inputs render empty; in clean() a blank secret for the
    connection's current provider is filled from the stored credentials, so
    the provider's required-field checks and save() see the existing value.
    """
    SECRET_FIELDS = {}

    def _protect_secret_fields(self):
        editing = bool(self.instance and self.instance.pk)
        for name in self.SECRET_FIELDS:
            field = self.fields.get(name)
            if field is None:
                continue
            field.initial = None
            attrs = dict(field.widget.attrs)
            attrs.pop('value', None)
            if editing:
                attrs['placeholder'] = 'Stored encrypted — leave blank to keep'
            field.widget = SecretInput(attrs=attrs)

    def _fill_blank_secrets_from_storage(self, cleaned_data):
        if not (self.instance and self.instance.pk):
            return
        provider_type = cleaned_data.get('provider_type')
        if provider_type != self.instance.provider_type:
            return  # switching provider: the old secrets do not apply
        stored = None
        for name, (provider, key) in self.SECRET_FIELDS.items():
            if provider != provider_type or cleaned_data.get(name):
                continue
            if stored is None:
                stored = self.instance.get_credentials() or {}
            if stored.get(key):
                cleaned_data[name] = stored[key]
                self.errors.pop(name, None)


class PSAConnectionForm(KeepStoredSecretsMixin, forms.ModelForm):
    SECRET_FIELDS = {
        'cw_private_key': ('connectwise_manage', 'private_key'),
        'at_secret': ('autotask', 'secret'),
        'halo_client_secret': ('halo_psa', 'client_secret'),
        'kaseya_api_key': ('kaseya_bms', 'api_key'),
        'kaseya_api_secret': ('kaseya_bms', 'api_secret'),
        'syncro_api_key': ('syncro', 'api_key'),
        'fresh_api_key': ('freshservice', 'api_key'),
        'zendesk_api_token': ('zendesk', 'api_token'),
        'itflow_api_key': ('itflow', 'api_key'),
        'ranger_api_key': ('rangermsp', 'api_key'),
        'alga_api_key': ('alga_psa', 'api_key'),
    }

    # ConnectWise Manage credentials
    cw_company_id = forms.CharField(
        label='Company ID',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'yourcompany'})
    )
    cw_public_key = forms.CharField(
        label='Public Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your public API key'})
    )
    cw_private_key = forms.CharField(
        label='Private Key',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your private API key'})
    )
    cw_client_id = forms.CharField(
        label='Client ID',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your client ID (integrator login)'})
    )

    # Autotask PSA credentials
    at_username = forms.CharField(
        label='Username (Email)',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'api@yourcompany.com'})
    )
    at_secret = forms.CharField(
        label='API Secret',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your API secret'})
    )
    at_integration_code = forms.CharField(
        label='Integration Code',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your integration code'})
    )

    # HaloPSA credentials
    halo_client_id = forms.CharField(
        label='Client ID',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your OAuth2 client ID'})
    )
    halo_client_secret = forms.CharField(
        label='Client Secret',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your OAuth2 client secret'})
    )
    halo_tenant = forms.CharField(
        label='Tenant (Optional)',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank for single-tenant'})
    )

    # Kaseya BMS credentials
    kaseya_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your API key'})
    )
    kaseya_api_secret = forms.CharField(
        label='API Secret',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your API secret'})
    )

    # Syncro credentials
    syncro_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your API key'})
    )
    syncro_subdomain = forms.CharField(
        label='Subdomain',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'yourcompany (from yourcompany.syncromsp.com)'})
    )

    # Freshservice credentials
    fresh_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your API key'})
    )
    fresh_domain = forms.CharField(
        label='Domain',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'yourcompany (from yourcompany.freshservice.com)'})
    )

    # Zendesk credentials
    zendesk_email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'admin@yourcompany.com'})
    )
    zendesk_api_token = forms.CharField(
        label='API Token',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your API token'})
    )
    zendesk_subdomain = forms.CharField(
        label='Subdomain',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'yourcompany (from yourcompany.zendesk.com)'})
    )

    # ITFlow credentials
    itflow_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your ITFlow API key'})
    )

    # RangerMSP (CommitCRM) credentials
    ranger_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your RangerMSP API key'})
    )
    ranger_account_id = forms.CharField(
        label='Account ID (Optional)',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'For cloud-hosted instances'})
    )

    # Alga PSA credentials
    alga_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your Alga PSA API key'})
    )
    alga_tenant_id = forms.CharField(
        label='Tenant ID',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your tenant/organization UUID'})
    )

    class Meta:
        model = PSAConnection
        fields = ['provider_type', 'name', 'base_url', 'sync_enabled', 'sync_companies',
                  'sync_contacts', 'sync_tickets', 'sync_interval_minutes',
                  'import_organizations', 'org_import_as_active', 'org_name_prefix']
        widgets = {
            'provider_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_provider_type'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'base_url': forms.URLInput(attrs={'class': 'form-control'}),
            'sync_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_companies': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_contacts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_tickets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_interval_minutes': forms.NumberInput(attrs={'class': 'form-control'}),
            'import_organizations': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'org_import_as_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'org_name_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., PSA-'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # If editing existing connection, populate credential fields
        if self.instance and self.instance.pk:
            creds = self.instance.get_credentials()
            provider = self.instance.provider_type

            if provider == 'connectwise_manage':
                self.fields['cw_company_id'].initial = creds.get('company_id', '')
                self.fields['cw_public_key'].initial = creds.get('public_key', '')
                self.fields['cw_private_key'].initial = creds.get('private_key', '')
                self.fields['cw_client_id'].initial = creds.get('client_id', '')
            elif provider == 'autotask':
                self.fields['at_username'].initial = creds.get('username', '')
                self.fields['at_secret'].initial = creds.get('secret', '')
                self.fields['at_integration_code'].initial = creds.get('integration_code', '')
            elif provider == 'halo_psa':
                self.fields['halo_client_id'].initial = creds.get('client_id', '')
                self.fields['halo_client_secret'].initial = creds.get('client_secret', '')
                self.fields['halo_tenant'].initial = creds.get('tenant', '')
            elif provider == 'kaseya_bms':
                self.fields['kaseya_api_key'].initial = creds.get('api_key', '')
                self.fields['kaseya_api_secret'].initial = creds.get('api_secret', '')
            elif provider == 'syncro':
                self.fields['syncro_api_key'].initial = creds.get('api_key', '')
                self.fields['syncro_subdomain'].initial = creds.get('subdomain', '')
            elif provider == 'freshservice':
                self.fields['fresh_api_key'].initial = creds.get('api_key', '')
                self.fields['fresh_domain'].initial = creds.get('domain', '')
            elif provider == 'zendesk':
                self.fields['zendesk_email'].initial = creds.get('email', '')
                self.fields['zendesk_api_token'].initial = creds.get('api_token', '')
                self.fields['zendesk_subdomain'].initial = creds.get('subdomain', '')
            elif provider == 'itflow':
                self.fields['itflow_api_key'].initial = creds.get('api_key', '')
            elif provider == 'rangermsp':
                self.fields['ranger_api_key'].initial = creds.get('api_key', '')
                self.fields['ranger_account_id'].initial = creds.get('account_id', '')
            elif provider == 'alga_psa':
                self.fields['alga_api_key'].initial = creds.get('api_key', '')
                self.fields['alga_tenant_id'].initial = creds.get('tenant_id', '')

        self._protect_secret_fields()

    def clean_base_url(self):
        """Validate and normalize base URL with provider-specific checks."""
        base_url = self.cleaned_data.get('base_url', '').strip()

        if not base_url:
            raise forms.ValidationError('Base URL is required')

        # Ensure it starts with http:// or https://
        if not base_url.startswith(('http://', 'https://')):
            base_url = f'https://{base_url}'

        # Remove trailing slash
        base_url = base_url.rstrip('/')

        # Provider-specific URL validation
        provider_type = self.data.get('provider_type')

        if provider_type == 'syncro':
            # Syncro must include subdomain
            if not 'syncromsp.com' in base_url:
                raise forms.ValidationError(
                    'Syncro Base URL should end with syncromsp.com. '
                    'Example: https://yourcompany.syncromsp.com'
                )
            # Check it has subdomain (should be at least yourcompany.syncromsp.com)
            parts = base_url.replace('https://', '').replace('http://', '').split('.')
            if len(parts) < 3:
                raise forms.ValidationError(
                    'Syncro Base URL must include your company subdomain. '
                    'Correct format: https://yourcompany.syncromsp.com'
                )

        return base_url

    def clean(self):
        cleaned_data = super().clean()
        provider_type = cleaned_data.get('provider_type')
        self._fill_blank_secrets_from_storage(cleaned_data)

        # Validate that required credentials are provided for selected provider
        if provider_type == 'connectwise_manage':
            required_fields = ['cw_company_id', 'cw_public_key', 'cw_private_key', 'cw_client_id']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for ConnectWise Manage')
        elif provider_type == 'autotask':
            required_fields = ['at_username', 'at_secret', 'at_integration_code']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Autotask PSA')
        elif provider_type == 'halo_psa':
            required_fields = ['halo_client_id', 'halo_client_secret']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for HaloPSA')
        elif provider_type == 'kaseya_bms':
            required_fields = ['kaseya_api_key', 'kaseya_api_secret']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Kaseya BMS')
        elif provider_type == 'syncro':
            required_fields = ['syncro_api_key', 'syncro_subdomain']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Syncro')
        elif provider_type == 'freshservice':
            required_fields = ['fresh_api_key', 'fresh_domain']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Freshservice')
        elif provider_type == 'zendesk':
            required_fields = ['zendesk_email', 'zendesk_api_token', 'zendesk_subdomain']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Zendesk')
        elif provider_type == 'itflow':
            if not cleaned_data.get('itflow_api_key'):
                self.add_error('itflow_api_key', 'This field is required for ITFlow')
        elif provider_type == 'rangermsp':
            if not cleaned_data.get('ranger_api_key'):
                self.add_error('ranger_api_key', 'This field is required for RangerMSP')
        elif provider_type == 'alga_psa':
            required_fields = ['alga_api_key', 'alga_tenant_id']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Alga PSA')

        return cleaned_data

    def save(self, commit=True):
        connection = super().save(commit=False)

        # Set organization from form if provided
        if self.organization:
            connection.organization = self.organization

        # Build credentials dict based on provider type
        provider_type = self.cleaned_data.get('provider_type')
        credentials = {}

        if provider_type == 'connectwise_manage':
            credentials = {
                'company_id': self.cleaned_data.get('cw_company_id', ''),
                'public_key': self.cleaned_data.get('cw_public_key', ''),
                'private_key': self.cleaned_data.get('cw_private_key', ''),
                'client_id': self.cleaned_data.get('cw_client_id', ''),
            }
        elif provider_type == 'autotask':
            credentials = {
                'username': self.cleaned_data.get('at_username', ''),
                'secret': self.cleaned_data.get('at_secret', ''),
                'integration_code': self.cleaned_data.get('at_integration_code', ''),
            }
        elif provider_type == 'halo_psa':
            credentials = {
                'client_id': self.cleaned_data.get('halo_client_id', ''),
                'client_secret': self.cleaned_data.get('halo_client_secret', ''),
                'tenant': self.cleaned_data.get('halo_tenant', ''),
            }
        elif provider_type == 'kaseya_bms':
            credentials = {
                'api_key': self.cleaned_data.get('kaseya_api_key', ''),
                'api_secret': self.cleaned_data.get('kaseya_api_secret', ''),
            }
        elif provider_type == 'syncro':
            credentials = {
                'api_key': self.cleaned_data.get('syncro_api_key', ''),
                'subdomain': self.cleaned_data.get('syncro_subdomain', ''),
            }
        elif provider_type == 'freshservice':
            credentials = {
                'api_key': self.cleaned_data.get('fresh_api_key', ''),
                'domain': self.cleaned_data.get('fresh_domain', ''),
            }
        elif provider_type == 'zendesk':
            credentials = {
                'email': self.cleaned_data.get('zendesk_email', ''),
                'api_token': self.cleaned_data.get('zendesk_api_token', ''),
                'subdomain': self.cleaned_data.get('zendesk_subdomain', ''),
            }
        elif provider_type == 'itflow':
            credentials = {
                'api_key': self.cleaned_data.get('itflow_api_key', ''),
            }
        elif provider_type == 'rangermsp':
            credentials = {
                'api_key': self.cleaned_data.get('ranger_api_key', ''),
                'account_id': self.cleaned_data.get('ranger_account_id', ''),
            }
        elif provider_type == 'alga_psa':
            credentials = {
                'api_key': self.cleaned_data.get('alga_api_key', ''),
                'tenant_id': self.cleaned_data.get('alga_tenant_id', ''),
            }

        connection.set_credentials(credentials)

        if commit:
            connection.save()

        return connection


class RMMConnectionForm(KeepStoredSecretsMixin, forms.ModelForm):
    """Form for creating/editing RMM connections."""
    SECRET_FIELDS = {
        'ninja_client_secret': ('ninjaone', 'client_secret'),
        'ninja_refresh_token': ('ninjaone', 'refresh_token'),
        'datto_api_key': ('datto_rmm', 'api_key'),
        'datto_api_secret': ('datto_rmm', 'api_secret'),
        'cwa_password': ('connectwise_automate', 'password'),
        'atera_api_key': ('atera', 'api_key'),
        'tactical_api_key': ('tactical_rmm', 'api_key'),
    }

    # NinjaOne credentials
    ninja_client_id = forms.CharField(
        label='Client ID',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your OAuth2 client ID'})
    )
    ninja_client_secret = forms.CharField(
        label='Client Secret',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your OAuth2 client secret'})
    )
    ninja_refresh_token = forms.CharField(
        label='Refresh Token',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your refresh token'})
    )

    # Datto RMM credentials
    datto_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your API key'})
    )
    datto_api_secret = forms.CharField(
        label='API Secret',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your API secret'})
    )

    # ConnectWise Automate credentials
    cwa_server = forms.CharField(
        label='Server URL',
        required=False,
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://your-automate.server.com'})
    )
    cwa_username = forms.CharField(
        label='Username',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'API username'})
    )
    cwa_password = forms.CharField(
        label='Password',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'API password'})
    )

    # Atera credentials
    atera_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your X-API-KEY'})
    )

    # Tactical RMM credentials
    tactical_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your Tactical RMM API key'})
    )

    class Meta:
        model = RMMConnection
        fields = ['provider_type', 'name', 'base_url', 'sync_enabled', 'sync_devices',
                  'sync_alerts', 'sync_software', 'map_to_assets', 'sync_interval_minutes',
                  'import_organizations', 'org_import_as_active', 'org_name_prefix']
        widgets = {
            'provider_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_rmm_provider_type'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'base_url': forms.URLInput(attrs={'class': 'form-control'}),
            'sync_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_devices': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_alerts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_software': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'map_to_assets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_interval_minutes': forms.NumberInput(attrs={'class': 'form-control'}),
            'import_organizations': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'org_import_as_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'org_name_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., RMM-'}),
        }
        help_texts = {
            'map_to_assets': 'Automatically create/update Assets from RMM devices',
            'import_organizations': 'Automatically create organizations from RMM sites/clients',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # If editing existing connection, populate credential fields
        if self.instance and self.instance.pk:
            creds = self.instance.get_credentials()
            provider = self.instance.provider_type

            if provider == 'ninjaone':
                self.fields['ninja_client_id'].initial = creds.get('client_id', '')
                self.fields['ninja_client_secret'].initial = creds.get('client_secret', '')
                self.fields['ninja_refresh_token'].initial = creds.get('refresh_token', '')
            elif provider == 'datto_rmm':
                self.fields['datto_api_key'].initial = creds.get('api_key', '')
                self.fields['datto_api_secret'].initial = creds.get('api_secret', '')
            elif provider == 'connectwise_automate':
                self.fields['cwa_server'].initial = creds.get('server', '')
                self.fields['cwa_username'].initial = creds.get('username', '')
                self.fields['cwa_password'].initial = creds.get('password', '')
            elif provider == 'atera':
                self.fields['atera_api_key'].initial = creds.get('api_key', '')
            elif provider == 'tactical_rmm':
                self.fields['tactical_api_key'].initial = creds.get('api_key', '')

        self._protect_secret_fields()

    def clean(self):
        cleaned_data = super().clean()
        provider_type = cleaned_data.get('provider_type')
        self._fill_blank_secrets_from_storage(cleaned_data)

        # Validate that organization is provided (required for RMM connections)
        if not self.organization:
            raise forms.ValidationError(
                "An organization must be selected before creating an RMM connection. "
                "Please select an organization from the top navigation bar and try again."
            )

        # Validate that required credentials are provided for selected provider
        if provider_type == 'ninjaone':
            required_fields = ['ninja_client_id', 'ninja_client_secret', 'ninja_refresh_token']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for NinjaOne')
        elif provider_type == 'datto_rmm':
            required_fields = ['datto_api_key', 'datto_api_secret']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for Datto RMM')
        elif provider_type == 'connectwise_automate':
            required_fields = ['cwa_server', 'cwa_username', 'cwa_password']
            for field in required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, 'This field is required for ConnectWise Automate')
        elif provider_type == 'atera':
            if not cleaned_data.get('atera_api_key'):
                self.add_error('atera_api_key', 'This field is required for Atera')
        elif provider_type == 'tactical_rmm':
            if not cleaned_data.get('tactical_api_key'):
                self.add_error('tactical_api_key', 'This field is required for Tactical RMM')

        return cleaned_data

    def save(self, commit=True):
        connection = super().save(commit=False)

        # Set organization from form if provided
        if self.organization:
            connection.organization = self.organization

        # Build credentials dict based on provider type
        provider_type = self.cleaned_data.get('provider_type')
        credentials = {}

        if provider_type == 'ninjaone':
            credentials = {
                'client_id': self.cleaned_data.get('ninja_client_id', ''),
                'client_secret': self.cleaned_data.get('ninja_client_secret', ''),
                'refresh_token': self.cleaned_data.get('ninja_refresh_token', ''),
            }
        elif provider_type == 'datto_rmm':
            credentials = {
                'api_key': self.cleaned_data.get('datto_api_key', ''),
                'api_secret': self.cleaned_data.get('datto_api_secret', ''),
            }
        elif provider_type == 'connectwise_automate':
            credentials = {
                'server': self.cleaned_data.get('cwa_server', ''),
                'username': self.cleaned_data.get('cwa_username', ''),
                'password': self.cleaned_data.get('cwa_password', ''),
            }
        elif provider_type == 'atera':
            credentials = {
                'api_key': self.cleaned_data.get('atera_api_key', ''),
            }
        elif provider_type == 'tactical_rmm':
            credentials = {
                'api_key': self.cleaned_data.get('tactical_api_key', ''),
            }

        connection.set_credentials(credentials)

        if commit:
            connection.save()

        return connection


class UnifiConnectionForm(forms.ModelForm):
    """Form for creating/editing UniFi connections."""

    api_key = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'UniFi API key'}),
        required=True,
        label='API Key',
        help_text='Self-hosted: generate in UniFi OS → Settings → API → Create API Key. '
                  'Cloud: generate at account.ui.com → API Keys.',
    )
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'UniFi local admin username'}),
        required=False,
        label='Username (optional)',
        help_text='Self-hosted only — local admin account for legacy API (WLANs, VLANs, firewall rules). '
                  'Leave blank for devices-only or when using cloud mode.',
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        required=False,
        label='Password (optional)',
    )

    class Meta:
        model = UnifiConnection
        fields = ['name', 'mode', 'host', 'verify_ssl', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Office UniFi'}),
            'mode': forms.Select(attrs={'class': 'form-select', 'id': 'id_mode'}),
            'host': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://192.168.1.1'}),
            'verify_ssl': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if self.instance and self.instance.pk:
            self.fields['api_key'].required = False
            self.fields['api_key'].help_text += ' (leave blank to keep existing key)'
            self.fields['password'].help_text = 'Leave blank to keep existing password.'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        api_key = self.cleaned_data.get('api_key', '').strip()
        username = self.cleaned_data.get('username', '').strip()
        password = self.cleaned_data.get('password', '').strip()
        # Merge with existing credentials so partial edits don't wipe fields
        existing = instance.get_credentials() if instance.pk else {}
        creds = dict(existing)
        if api_key:
            creds['api_key'] = api_key
        if username:
            creds['username'] = username
        if password:
            creds['password'] = password
        if creds:
            instance.set_credentials(creds)
        if commit:
            instance.save()
        return instance


class M365ConnectionForm(forms.ModelForm):
    """Form for creating/editing M365 tenant connections."""

    client_id = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Application (client) ID'}),
        required=True,
        label='Client ID',
        help_text='App registration → Overview → Application (client) ID',
    )
    client_secret = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Client secret value'}),
        required=True,
        label='Client Secret',
        help_text='App registration → Certificates & secrets → New client secret',
    )

    class Meta:
        model = M365Connection
        fields = ['name', 'tenant_id', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Contoso M365'}),
            'tenant_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'tenant_id': 'Azure portal → Azure Active Directory → Overview → Directory (tenant) ID',
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if self.instance and self.instance.pk:
            self.fields['client_id'].required = False
            self.fields['client_secret'].required = False
            for f in ('client_id', 'client_secret'):
                self.fields[f].help_text += ' (leave blank to keep existing)'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        client_id = self.cleaned_data.get('client_id', '').strip()
        client_secret = self.cleaned_data.get('client_secret', '').strip()
        if client_id and client_secret:
            instance.set_credentials({'client_id': client_id, 'client_secret': client_secret})
        elif client_id or client_secret:
            # Partial update: merge with existing
            existing = instance.get_credentials()
            if client_id:
                existing['client_id'] = client_id
            if client_secret:
                existing['client_secret'] = client_secret
            instance.set_credentials(existing)
        if commit:
            instance.save()
        return instance


class OmadaConnectionForm(forms.ModelForm):
    """Form for creating/editing TP-Link Omada SDN Controller connections."""

    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Omada admin username'}),
        required=True,
        label='Username',
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Omada admin password'}),
        required=True,
        label='Password',
    )

    class Meta:
        model = OmadaConnection
        fields = ['name', 'host', 'verify_ssl', 'is_active', 'auto_sync_assets', 'sync_interval_minutes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Office Omada'}),
            'host': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://192.168.1.1:8043'}),
            'verify_ssl': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'auto_sync_assets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_interval_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }
        help_texts = {
            'host': 'Omada controller URL including port, e.g. https://192.168.1.1:8043',
            'sync_interval_minutes': 'Minutes between auto-syncs (0 = disabled)',
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if self.instance and self.instance.pk:
            creds = self.instance.get_credentials()
            self.fields['username'].initial = creds.get('username', '')
            self.fields['password'].required = False
            self.fields['password'].help_text = 'Leave blank to keep existing password.'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        username = self.cleaned_data.get('username', '').strip()
        password = self.cleaned_data.get('password', '').strip()
        existing = instance.get_credentials() if instance.pk else {}
        creds = dict(existing)
        if username:
            creds['username'] = username
        if password:
            creds['password'] = password
        if creds:
            instance.set_credentials(creds)
        if commit:
            instance.save()
        return instance


class GrandstreamConnectionForm(forms.ModelForm):
    """Form for creating/editing Grandstream GWN Manager connections."""

    api_key = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'GWN Manager API key'}),
        required=True,
        label='API Key',
    )

    class Meta:
        model = GrandstreamConnection
        fields = ['name', 'host', 'verify_ssl', 'is_active', 'auto_sync_assets', 'sync_interval_minutes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Office GWN'}),
            'host': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://gwn.cloud'}),
            'verify_ssl': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'auto_sync_assets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_interval_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }
        help_texts = {
            'host': 'GWN Manager URL. Use https://gwn.cloud for cloud, or your self-hosted URL.',
            'sync_interval_minutes': 'Minutes between auto-syncs (0 = disabled)',
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if self.instance and self.instance.pk:
            self.fields['api_key'].required = False
            self.fields['api_key'].help_text = 'Leave blank to keep existing API key.'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        api_key = self.cleaned_data.get('api_key', '').strip()
        existing = instance.get_credentials() if instance.pk else {}
        creds = dict(existing)
        if api_key:
            creds['api_key'] = api_key
        if creds:
            instance.set_credentials(creds)
        if commit:
            instance.save()
        return instance
