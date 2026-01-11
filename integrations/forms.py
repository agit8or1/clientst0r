"""
Integrations forms
"""
from django import forms
from .models import PSAConnection, RMMConnection


class PSAConnectionForm(forms.ModelForm):
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

    class Meta:
        model = PSAConnection
        fields = ['provider_type', 'name', 'base_url', 'sync_enabled', 'sync_companies',
                  'sync_contacts', 'sync_tickets', 'sync_interval_minutes']
        widgets = {
            'provider_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_provider_type'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'base_url': forms.URLInput(attrs={'class': 'form-control'}),
            'sync_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_companies': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_contacts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_tickets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_interval_minutes': forms.NumberInput(attrs={'class': 'form-control'}),
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

    def clean(self):
        cleaned_data = super().clean()
        provider_type = cleaned_data.get('provider_type')

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

        return cleaned_data

    def save(self, commit=True):
        connection = super().save(commit=False)

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

        connection.set_credentials(credentials)

        if commit:
            connection.save()

        return connection


class RMMConnectionForm(forms.ModelForm):
    """Form for creating/editing RMM connections."""

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
                  'sync_alerts', 'sync_software', 'map_to_assets', 'sync_interval_minutes']
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
        }
        help_texts = {
            'map_to_assets': 'Automatically create/update Assets from RMM devices',
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

    def clean(self):
        cleaned_data = super().clean()
        provider_type = cleaned_data.get('provider_type')

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
