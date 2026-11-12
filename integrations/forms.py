"""
Integrations forms
"""
from django import forms
from vault.secret_fields import SecretInput
from .models import PSAConnection, RMMConnection, UnifiConnection, M365Connection, OmadaConnection, GrandstreamConnection


class KeepStoredSecretsMixin:
    """Never echo stored secrets into the form; blank keeps the stored value.

    `SECRET_FIELDS` maps form field -> (provider_type, credential key); a
    provider_type of '*' applies to every provider. On an edit the inputs
    render empty; in clean() a blank secret for the connection's current
    provider is filled from the stored credentials, so the provider's
    required-field checks and save() see the existing value.
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
            if (provider != '*' and provider != provider_type) or cleaned_data.get(name):
                continue
            if stored is None:
                stored = self.instance.get_credentials() or {}
            if stored.get(key):
                cleaned_data[name] = stored[key]
                self.errors.pop(name, None)


class OwnerFieldMixin:
    """Owner: Platform / a specific customer.

    A connection created in global view gets an Owner choice (platform admins
    only — the view decides who reaches it): the platform, which is the
    default, or one customer. Inside a customer the owner is that customer.
    An existing connection's owner is shown, never edited here: the only way
    to change it is the audited "Make platform-owned" action.
    """
    OWNER_HELP = ("Platform: the MSP's own connection; what it syncs is assigned to customers "
                  "through its mappings and anything unmapped waits for platform staff. "
                  "A customer: that customer's own connection (e.g. their Microsoft 365 tenant "
                  "or on-site controller).")

    def _init_owner(self, organization, owner_choices=None):
        self.organization = organization
        self._owner_choices = list(owner_choices or [])
        self._owner = organization
        if self.instance is not None and self.instance.pk:
            self._owner = self.instance.organization
            return
        if organization is None and self._owner_choices:
            self.fields['owner'] = forms.ChoiceField(
                label='Owner', choices=self._owner_choices, required=False, initial='',
                help_text=self.OWNER_HELP, widget=forms.Select(attrs={'class': 'form-select'}))

    @property
    def owner_display(self):
        if self.instance is not None and self.instance.pk:
            return self.instance.owner_label
        if self.organization is not None:
            return self.organization.name
        return None if 'owner' in self.fields else 'Platform'

    @property
    def owner_is_platform(self):
        if self.instance is not None and self.instance.pk:
            return self.instance.organization_id is None
        return self.organization is None

    def clean(self):
        cleaned_data = super().clean()
        self._owner = self._resolve_owner(cleaned_data)
        name = (cleaned_data.get('name') or '').strip()
        if name:
            model = self._meta.model
            clash = model._default_manager.filter(organization=self._owner, name=name)
            if self.instance is not None and self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error('name', f'{"The platform" if self._owner is None else self._owner.name} '
                                       f'already has a connection with this name.')
        return cleaned_data

    def _resolve_owner(self, cleaned_data):
        if self.instance is not None and self.instance.pk:
            return self.instance.organization
        if self.organization is not None:
            return self.organization
        raw = cleaned_data.get('owner') or ''
        if not raw:
            return None
        from core.models import Organization
        allowed = {k for k, _ in self._owner_choices if k}
        if raw not in allowed:
            self.add_error('owner', 'Choose the platform or a customer you can assign.')
            return None
        return Organization.objects.filter(pk=int(raw), is_active=True).first()

    def _apply_owner(self, instance):
        if not instance.pk:
            instance.organization = self._owner
        return instance


class PSAConnectionForm(OwnerFieldMixin, KeepStoredSecretsMixin, forms.ModelForm):
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
        organization = kwargs.pop('organization', None)
        owner_choices = kwargs.pop('owner_choices', None)
        super().__init__(*args, **kwargs)
        self._init_owner(organization, owner_choices)

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
        self._apply_owner(connection)

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


class RMMConnectionForm(OwnerFieldMixin, KeepStoredSecretsMixin, forms.ModelForm):
    """Form for creating/editing RMM connections."""
    SECRET_FIELDS = {
        'ninja_client_secret': ('ninjaone', 'client_secret'),
        'ninja_refresh_token': ('ninjaone', 'refresh_token'),
        'datto_api_key': ('datto_rmm', 'api_key'),
        'datto_api_secret': ('datto_rmm', 'api_secret'),
        'cwa_password': ('connectwise_automate', 'password'),
        'atera_api_key': ('atera', 'api_key'),
        'tactical_api_key': ('tactical_rmm', 'api_key'),
        'rem0te_api_key': ('rem0te', 'api_key'),
        # Ticket integration pairing (ticket-rmm-v1): any provider.
        'ticket_rmm_outbound_secret': ('*', 'integration_outbound_secret'),
        'ticket_rmm_inbound_secret': ('*', 'integration_inbound_secret'),
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

    # Rem0te credentials
    rem0te_api_key = forms.CharField(
        label='API Key',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'rk_…'})
    )
    # Ticket integration pairing (docs/contracts/ticket-rmm-v1), for any
    # provider that implements the contract. Turning it on or marking it
    # on-premises is a protected change; see _apply_pairing().
    ticket_rmm_enabled = forms.BooleanField(
        label='Pair this RMM for ticket integration (ticket-rmm-v1)', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    ticket_rmm_url = forms.URLField(
        label='Integration address', required=False, max_length=500,
        help_text="Where the RMM serves /api/integration/v1/. Leave blank to use this connection's address.",
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://rmm.example.com'}))
    ticket_rmm_key_id = forms.CharField(
        label='Integration key ID', required=False, max_length=64,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
    ticket_rmm_outbound_secret = forms.CharField(
        label='Secret ClientSt0r signs with', required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}))
    ticket_rmm_inbound_secret = forms.CharField(
        label='Secret the RMM signs with', required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}))
    ticket_rmm_location = forms.ChoiceField(
        label='Where this RMM runs', required=False,
        choices=(('hosted', 'Hosted / off-premises'), ('local', 'On-premises')),
        widget=forms.Select(attrs={'class': 'form-control'}))
    # Rem0te only: its Ed25519 protocol replaces the key ID and shared secrets.
    rem0te_audience = forms.CharField(
        label="Rem0te's audience", required=False, max_length=256,
        help_text="The peers file's peers[].audience — what ClientSt0r signs its requests to Rem0te for "
                  '(Rem0te shows it in its capabilities).',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off',
                                      'placeholder': 'rem0te:example'}))
    rem0te_signing_keys = forms.CharField(
        label="Rem0te's public signing keys", required=False, max_length=8000,
        help_text="Rem0te's Ed25519 public key(s): a key id line followed by its PEM block, repeated for a "
                  "previous key during rotation (or Rem0te's capabilities signing_keys JSON). Public keys only.",
        widget=forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 5, 'spellcheck': 'false',
                                     'placeholder': 'rem0te-2026-11\n-----BEGIN PUBLIC KEY-----\n…\n'
                                                    '-----END PUBLIC KEY-----'}))

    class Meta:
        model = RMMConnection
        fields = ['provider_type', 'name', 'base_url', 'console_base_url', 'customer_scope', 'sync_enabled',
                  'sync_devices', 'sync_alerts', 'sync_software', 'sync_services', 'map_to_assets', 'sync_interval_minutes',
                  'import_organizations', 'org_import_as_active', 'org_name_prefix']
        widgets = {
            'provider_type': forms.Select(attrs={'class': 'form-control', 'id': 'id_rmm_provider_type'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'base_url': forms.URLInput(attrs={'class': 'form-control'}),
            'console_base_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://rmm.example.com'}),
            'customer_scope': forms.Select(attrs={'class': 'form-control'}),
            'sync_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_devices': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_alerts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_software': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_services': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'map_to_assets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sync_interval_minutes': forms.NumberInput(attrs={'class': 'form-control'}),
            'import_organizations': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'org_import_as_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'org_name_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., RMM-'}),
        }
        help_texts = {
            'map_to_assets': 'Automatically create/update Assets from RMM devices',
            'import_organizations': 'Automatically create organizations from RMM sites/clients',
            'customer_scope': ('Single: every device belongs to this organization. Multiple: each device is '
                               "matched to its RMM customer; devices whose customer can't be resolved wait "
                               'for review instead of landing here.'),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        owner_choices = kwargs.pop('owner_choices', None)
        super().__init__(*args, **kwargs)
        self._init_owner(organization, owner_choices)
        self.pairing_request = None
        self._pairing_before = None
        if self.instance and self.instance.pk:
            from integrations.ticket_rmm import secrets, settings
            p, sec = settings(self.instance), secrets(self.instance)
            self._pairing_before = {'on': p['requested'], 'key_id': p['key_id'], 'location': p['location'],
                                    'outbound': sec['outbound'], 'inbound': sec['inbound'],
                                    'site': p['site'], 'provider': self.instance.provider_type,
                                    'audience': p.get('rem0te_audience', ''),
                                    'keys': p.get('signing_keys', [])}
            if self.instance.provider_type == 'rem0te':
                from integrations.rem0te.pairing import format_signing_keys
                self.fields['rem0te_audience'].initial = p.get('rem0te_audience', '')
                self.fields['rem0te_signing_keys'].initial = format_signing_keys(p.get('signing_keys', []))
            self.fields['ticket_rmm_enabled'].initial = p['requested']
            self.fields['ticket_rmm_key_id'].initial = p['key_id']
            self.fields['ticket_rmm_location'].initial = p['location']
            self.fields['ticket_rmm_url'].initial = p['url']

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
            elif provider == 'rem0te':
                self.fields['rem0te_api_key'].initial = creds.get('api_key', '')

        self._protect_secret_fields()

    def clean(self):
        cleaned_data = super().clean()
        provider_type = cleaned_data.get('provider_type')
        self._fill_blank_secrets_from_storage(cleaned_data)

        # A platform-owned RMM serves many customers: each device's customer
        # comes from the RMM's own customer identity, never from an owner.
        platform = self._owner is None
        if platform:
            if provider_type == 'rem0te':
                self.add_error('provider_type', "A Rem0te key belongs to one business, so a Rem0te connection is "
                                                "always one customer's own. Choose that customer as the owner.")
            cleaned_data['customer_scope'] = RMMConnection.CUSTOMER_SCOPE_MULTI

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
        elif provider_type == 'rem0te':
            if not cleaned_data.get('rem0te_api_key'):
                self.add_error('rem0te_api_key', 'This field is required for Rem0te')
            # A Rem0te key belongs to one business, so the connection is
            # always one customer: this organization.
            cleaned_data['customer_scope'] = RMMConnection.CUSTOMER_SCOPE_SINGLE
            cleaned_data['import_organizations'] = False

        self._clean_pairing(cleaned_data)
        return cleaned_data

    def _clean_pairing(self, cleaned_data):
        """Ticket integration pairing, the same for every provider — except
        Rem0te, which pairs with Ed25519 keys and never with shared secrets."""
        if cleaned_data.get('provider_type') == 'rem0te':
            return self._clean_rem0te_pairing(cleaned_data)
        if not cleaned_data.get('ticket_rmm_enabled'):
            return
        for f in ('ticket_rmm_key_id', 'ticket_rmm_outbound_secret', 'ticket_rmm_inbound_secret'):
            if not cleaned_data.get(f):
                self.add_error(f, 'Required to pair this RMM for ticket integration.')
        o, i = (cleaned_data.get('ticket_rmm_outbound_secret') or '',
                cleaned_data.get('ticket_rmm_inbound_secret') or '')
        if o and i and o == i:
            self.add_error('ticket_rmm_inbound_secret', 'Use two different secrets.')
        if (o and len(o) < 32) or (i and len(i) < 32):
            self.add_error('ticket_rmm_outbound_secret', 'Secrets must be at least 32 characters.')
        key_id = (cleaned_data.get('ticket_rmm_key_id') or '').strip()
        if key_id and not all(ch.isalnum() or ch in '-_.' for ch in key_id):
            self.add_error('ticket_rmm_key_id', 'Use letters, digits, ".", "-" and "_" only.')
        if key_id and self._key_id_taken(key_id):
            self.add_error('ticket_rmm_key_id', 'Another RMM connection already uses this key ID.')
        url = (cleaned_data.get('ticket_rmm_url') or '').strip()
        local = cleaned_data.get('ticket_rmm_location') == 'local'
        if url and not (url.startswith('https://') or (local and url.startswith('http://'))):
            self.add_error('ticket_rmm_url', 'Use https (plain http only for an on-premises RMM).')
        if self._owner is None:
            self.add_error('ticket_rmm_enabled', "A ticket integration pairing serves one customer: pair a "
                                                 "customer's own connection, not a platform-owned one.")
        elif (cleaned_data.get('provider_type') != 'rem0te'
                and cleaned_data.get('customer_scope') != RMMConnection.CUSTOMER_SCOPE_SINGLE):
            self.add_error('customer_scope', 'A ticket integration pairing serves one customer: choose '
                                             'Single customer to pair this connection.')

    def _clean_rem0te_pairing(self, cleaned_data):
        from integrations.rem0te.pairing import parse_signing_keys
        cleaned_data['ticket_rmm_key_id'] = ''
        cleaned_data['ticket_rmm_outbound_secret'] = ''
        cleaned_data['ticket_rmm_inbound_secret'] = ''
        audience = (cleaned_data.get('rem0te_audience') or '').strip()
        cleaned_data['rem0te_audience'] = audience
        if audience and not all(0x21 <= ord(ch) <= 0x7e for ch in audience):
            self.add_error('rem0te_audience', 'Use printable characters without spaces, exactly as in the peers file.')
        try:
            cleaned_data['rem0te_signing_keys_parsed'] = parse_signing_keys(cleaned_data.get('rem0te_signing_keys') or '')
        except ValueError as e:
            self.add_error('rem0te_signing_keys', str(e))
            cleaned_data['rem0te_signing_keys_parsed'] = None
        url = (cleaned_data.get('ticket_rmm_url') or '').strip()
        local = cleaned_data.get('ticket_rmm_location') == 'local'
        if url and not (url.startswith('https://') or (local and url.startswith('http://'))):
            self.add_error('ticket_rmm_url', 'Use https (plain http only for an on-premises Rem0te).')
        if not cleaned_data.get('ticket_rmm_enabled'):
            return
        if not audience:
            self.add_error('rem0te_audience', "Required to pair with Rem0te: copy it from Rem0te's peers file.")
        if not cleaned_data.get('rem0te_signing_keys_parsed') and 'rem0te_signing_keys' not in self.errors:
            self.add_error('rem0te_signing_keys', "Required to pair with Rem0te: paste Rem0te's public signing key.")

    def _key_id_taken(self, key_id):
        from integrations.ticket_rmm import KEY_ID
        others = RMMConnection.objects.exclude(pk=getattr(self.instance, 'pk', None) or 0)
        return any(str((m or {}).get(KEY_ID) or '') == key_id
                   for m in others.values_list('field_mappings', flat=True))

    def save(self, commit=True):
        connection = super().save(commit=False)
        self._apply_owner(connection)

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
        elif provider_type == 'rem0te':
            credentials = {'api_key': self.cleaned_data.get('rem0te_api_key', '')}

        # Ticket integration pairing secrets, whatever the provider (not
        # Rem0te: it pairs with Ed25519 keys only).
        for field, name in (('ticket_rmm_outbound_secret', 'integration_outbound_secret'),
                            ('ticket_rmm_inbound_secret', 'integration_inbound_secret')):
            if self.cleaned_data.get(field) and provider_type != 'rem0te':
                credentials[name] = self.cleaned_data[field]

        self.pairing_request = None
        self._apply_pairing(connection, credentials)

        connection.set_credentials(credentials)

        if commit:
            connection.save()

        return connection


def _ticket_rmm_pairing_apply(self, connection, credentials):
    """Narrowing pairing changes apply now; widening ones become
    `self.pairing_request` for the view to propose as a protected change.
    The same for every provider.

    Widening: switching the pairing on, or marking the RMM on-premises.
    Re-pairing a live pairing — new secrets, key ID, address or provider —
    switches it off until it is approved again. A provider change also
    clears the tenant pin and capabilities: another product pins afresh."""
    from integrations import ticket_rmm
    if connection.provider_type == 'rem0te':
        return _rem0te_pairing_apply(self, connection)
    mappings = dict(connection.field_mappings or {})
    before = self._pairing_before or {}
    want_on = bool(self.cleaned_data.get('ticket_rmm_enabled'))
    want_local = self.cleaned_data.get('ticket_rmm_location') == 'local'
    key_id = (self.cleaned_data.get('ticket_rmm_key_id') or '').strip()
    url = (self.cleaned_data.get('ticket_rmm_url') or '').strip()
    if not (want_on or want_local or key_id or url or before.get('on') or before.get('key_id')
            or any(k in mappings for k in (ticket_rmm.ENABLED, ticket_rmm.KEY_ID, ticket_rmm.URL))):
        self.pairing_request = None  # never paired, and still not: leave the connection as it was
        return
    mappings[ticket_rmm.URL] = url
    connection.field_mappings = mappings
    site = ticket_rmm.contract_site(connection)
    provider_changed = bool(before) and connection.provider_type != before.get('provider')
    repaired = before.get('on') and (
        key_id != before.get('key_id')
        or credentials.get('integration_outbound_secret', '') != (before.get('outbound') or '')
        or credentials.get('integration_inbound_secret', '') != (before.get('inbound') or '')
        or site != before.get('site')
        or provider_changed)
    if provider_changed:
        mappings.pop(ticket_rmm.TENANT_PIN, None)
        mappings.pop(ticket_rmm.CAPS, None)
    mappings[ticket_rmm.KEY_ID] = key_id
    if not want_on or repaired:
        mappings[ticket_rmm.ENABLED] = False
    if not want_local:
        mappings[ticket_rmm.LOCATION] = 'hosted'
    connection.field_mappings = mappings
    widen = {}
    if want_on and (repaired or not before.get('on')):
        widen['enable'] = True
    if want_local and before.get('location') != 'local':
        widen['location'] = 'local'
    elif want_local and widen.get('enable'):
        widen['location'] = 'local'
    self.pairing_request = widen or None


RMMConnectionForm._apply_pairing = _ticket_rmm_pairing_apply


class UnifiConnectionForm(OwnerFieldMixin, forms.ModelForm):
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

    def __init__(self, *args, organization=None, owner_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_owner(organization, owner_choices)
        if self.instance and self.instance.pk:
            self.fields['api_key'].required = False
            self.fields['api_key'].help_text += ' (leave blank to keep existing key)'
            self.fields['password'].help_text = 'Leave blank to keep existing password.'

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_owner(instance)
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


class M365ConnectionForm(OwnerFieldMixin, forms.ModelForm):
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

    def __init__(self, *args, organization=None, owner_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_owner(organization, owner_choices)
        if self.instance and self.instance.pk:
            self.fields['client_id'].required = False
            self.fields['client_secret'].required = False
            for f in ('client_id', 'client_secret'):
                self.fields[f].help_text += ' (leave blank to keep existing)'

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_owner(instance)
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


class OmadaConnectionForm(OwnerFieldMixin, forms.ModelForm):
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

    def __init__(self, *args, organization=None, owner_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_owner(organization, owner_choices)
        if self.instance and self.instance.pk:
            creds = self.instance.get_credentials()
            self.fields['username'].initial = creds.get('username', '')
            self.fields['password'].required = False
            self.fields['password'].help_text = 'Leave blank to keep existing password.'

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_owner(instance)
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


class GrandstreamConnectionForm(OwnerFieldMixin, forms.ModelForm):
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

    def __init__(self, *args, organization=None, owner_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_owner(organization, owner_choices)
        if self.instance and self.instance.pk:
            self.fields['api_key'].required = False
            self.fields['api_key'].help_text = 'Leave blank to keep existing API key.'

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_owner(instance)
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


def _rem0te_pairing_apply(self, connection):
    """Rem0te: Rem0te's audience and public signing keys instead of a key ID
    and shared secrets. The same protection as every pairing: turning it on
    or marking it on-premises waits for a second administrator, and changing
    the audience, the keys, the address or the provider of a live pairing
    switches it off until approved again. Saving complete Ed25519 settings
    clears "needs re-pairing"; the old HMAC settings stay kept (for the
    migration's reverse) and are never used."""
    from integrations import ticket_rmm
    from integrations.rem0te import pairing
    mappings = dict(connection.field_mappings or {})
    before = self._pairing_before or {}
    want_on = bool(self.cleaned_data.get('ticket_rmm_enabled'))
    want_local = self.cleaned_data.get('ticket_rmm_location') == 'local'
    url = (self.cleaned_data.get('ticket_rmm_url') or '').strip()
    audience = self.cleaned_data.get('rem0te_audience') or ''
    keys = self.cleaned_data.get('rem0te_signing_keys_parsed') or []
    if not (want_on or want_local or url or audience or keys or before.get('on')
            or any(k in mappings for k in (ticket_rmm.ENABLED, ticket_rmm.URL, pairing.AUDIENCE))):
        self.pairing_request = None
        return
    mappings[ticket_rmm.URL] = url
    mappings[pairing.AUDIENCE] = audience
    mappings[pairing.SIGNING_KEYS] = keys
    mappings[pairing.AUTH] = 'ed25519'
    mappings.pop(ticket_rmm.KEY_ID, None)
    if audience and keys:
        mappings.pop(pairing.NEEDS_REPAIR, None)
    connection.field_mappings = mappings
    site = ticket_rmm.contract_site(connection)
    provider_changed = bool(before) and connection.provider_type != before.get('provider')
    same_keys = pairing.format_signing_keys(keys) == pairing.format_signing_keys(before.get('keys') or [])
    repaired = before.get('on') and (audience != before.get('audience') or not same_keys
                                     or site != before.get('site') or provider_changed)
    if provider_changed:
        mappings.pop(ticket_rmm.TENANT_PIN, None)
        mappings.pop(ticket_rmm.CAPS, None)
    if not want_on or repaired:
        mappings[ticket_rmm.ENABLED] = False
    if not want_local:
        mappings[ticket_rmm.LOCATION] = 'hosted'
    connection.field_mappings = mappings
    widen = {}
    if want_on and (repaired or not before.get('on')):
        widen['enable'] = True
    if want_local and (before.get('location') != 'local' or widen.get('enable')):
        widen['location'] = 'local'
    self.pairing_request = widen or None
