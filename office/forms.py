from urllib.parse import urlsplit

from django import forms

from .models import PROVIDER_CHOICES, EditorInstance, OfficeSettings, OrganizationOfficePolicy

_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')


def _check_url(value, mode, label, *, allow_path=True):
    if not value:
        return value
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise forms.ValidationError(f'{label} must not contain a user name or password.')
    if parts.query or parts.fragment:
        raise forms.ValidationError(f'{label} must not contain a query string or fragment.')
    host = (parts.hostname or '').lower()
    if parts.scheme == 'https':
        pass
    elif parts.scheme == 'http' and mode == 'same_server' and host in _LOOPBACK_HOSTS:
        pass
    else:
        raise forms.ValidationError(
            f'{label} must use https (plain http is accepted only for a loopback '
            f'address of an editor installed on this server).')
    if not allow_path and parts.path not in ('', '/'):
        raise forms.ValidationError(f'{label} must not contain a path.')
    return value.rstrip('/') + '/'


def _check_ca_bundle(text):
    text = (text or '').strip()
    if not text:
        return ''
    if 'PRIVATE KEY' in text:
        raise forms.ValidationError('Paste only CA certificates — never a private key.')
    from cryptography import x509
    try:
        certs = x509.load_pem_x509_certificates(text.encode('ascii'))
    except Exception:
        raise forms.ValidationError('Not a valid PEM certificate bundle.')
    if not certs:
        raise forms.ValidationError('Not a valid PEM certificate bundle.')
    return text + '\n'


class EditorInstanceForm(forms.ModelForm):
    class Meta:
        model = EditorInstance
        fields = ['provider', 'name', 'mode', 'browser_url', 'internal_url', 'callback_base_url',
                  'shared_secret', 'ca_bundle', 'max_file_mb', 'connect_timeout_s',
                  'request_timeout_s', 'conversion_timeout_s', 'enabled', 'shared',
                  'organizations']
        widgets = {
            'ca_bundle': forms.Textarea(attrs={'rows': 5, 'class': 'form-control font-monospace',
                                               'placeholder': '-----BEGIN CERTIFICATE-----'}),
            'organizations': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')
        # Required for ONLYOFFICE only (JWT); checked in clean() once the
        # provider is known. Collabora shares no secret with clientst0r.
        self.fields['shared_secret'].required = False
        self.fields['shared_secret'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['organizations'].required = False

    def clean(self):
        data = super().clean()
        mode = data.get('mode')
        for field, label in (('browser_url', 'Browser URL'), ('internal_url', 'Internal URL'),
                             ('callback_base_url', 'Callback URL')):
            try:
                data[field] = _check_url(data.get(field), mode, label)
            except forms.ValidationError as e:
                self.add_error(field, e)
        try:
            data['ca_bundle'] = _check_ca_bundle(data.get('ca_bundle'))
        except forms.ValidationError as e:
            self.add_error('ca_bundle', e)
        secret = data.get('shared_secret')
        has_stored = bool(self.instance and self.instance.pk and self.instance.shared_secret)
        if data.get('provider') == 'onlyoffice' and not secret and not has_stored:
            self.add_error('shared_secret', 'ONLYOFFICE needs the JWT secret set on the Document Server.')
        if secret:
            from .models import secret_problem
            problem = secret_problem(secret)
            if problem:
                self.add_error('shared_secret', problem)
        if not data.get('shared') and not data.get('organizations'):
            self.add_error('organizations', 'Pick the organizations a dedicated instance serves.')
        return data


class OfficeSettingsForm(forms.ModelForm):
    enabled_providers = forms.MultipleChoiceField(
        choices=PROVIDER_CHOICES, required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = OfficeSettings
        fields = ['enabled_providers', 'default_instance', 'allow_org_override',
                  'quarantine_retention_days', 'session_ttl_minutes', 'session_max_hours',
                  'token_ttl_minutes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxSelectMultiple):
                continue
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')
        self.fields['quarantine_retention_days'].min_value = 1
        self.fields['token_ttl_minutes'].min_value = 5
        self.fields['session_ttl_minutes'].min_value = 15
        self.fields['session_max_hours'].min_value = 1

    def clean_quarantine_retention_days(self):
        v = self.cleaned_data['quarantine_retention_days']
        if v < 1 or v > 3650:
            raise forms.ValidationError('Between 1 and 3650 days.')
        return v


class OrganizationPolicyForm(forms.ModelForm):
    class Meta:
        model = OrganizationOfficePolicy
        fields = ['office_enabled', 'preferred_instance']

    def __init__(self, *args, allowed_instances=None, allow_override=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['office_enabled'].widget.attrs['class'] = 'form-check-input'
        field = self.fields['preferred_instance']
        field.queryset = allowed_instances if allowed_instances is not None else \
            EditorInstance.objects.none()
        field.required = False
        field.widget.attrs['class'] = 'form-select'
        field.empty_label = 'Platform default'
        if not allow_override:
            field.disabled = True


class TemplateUploadForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={'class': 'form-control',
                                                                  'accept': '.docx,.xlsx,.pptx,.dotx,.xltx,.potx'}))
    description = forms.CharField(required=False, max_length=500,
                                  widget=forms.TextInput(attrs={'class': 'form-control'}))
    scope = forms.ChoiceField(choices=[('org', 'This organization'), ('global', 'All organizations')],
                              widget=forms.Select(attrs={'class': 'form-select'}))
