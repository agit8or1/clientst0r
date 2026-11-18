from django import forms
from django.core.exceptions import ValidationError

from .groups import ENDPOINT_GROUPS, INTEGRATIONS
from .models import ApiAccessRule, ApiAccessSettings, normalize_network


def target_choices():
    return [
        ('', '—'),
        ('Integrations', [(k, v) for k, v in INTEGRATIONS.items()]),
        ('Endpoint groups', [(k, label) for k, (label, _s) in ENDPOINT_GROUPS.items()]),
    ]


class RuleForm(forms.ModelForm):
    target = forms.ChoiceField(required=False, label='Integration or endpoint group')

    class Meta:
        model = ApiAccessRule
        fields = ['name', 'network', 'action', 'surface', 'scope', 'organization', 'api_key',
                  'target', 'description', 'is_active', 'expires_at']
        widgets = {
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'},
                                              format='%Y-%m-%dT%H:%M'),
            'description': forms.TextInput(),
        }
        labels = {'network': 'Address or CIDR range', 'organization': 'Customer',
                  'api_key': 'API key', 'expires_at': 'Expires'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from api.models import APIKey
        from core.models import Organization
        self.fields['target'].choices = target_choices()
        self.fields['organization'].queryset = Organization.objects.filter(is_active=True).order_by('name')
        self.fields['api_key'].queryset = (APIKey.objects.filter(is_active=True)
                                           .select_related('organization').order_by('name'))
        self.fields['api_key'].label_from_instance = (
            lambda k: f'{k.name} ({k.key_prefix}…) — {k.organization}')
        self.fields['expires_at'].input_formats = ['%Y-%m-%dT%H:%M']
        self.fields['network'].widget.attrs['placeholder'] = '203.0.113.10, 10.0.0.0/24 or 2001:db8::/48'
        for name, field in self.fields.items():
            css = 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else (
                'form-select' if isinstance(field.widget, forms.Select) else 'form-control')
            field.widget.attrs.setdefault('class', css)

    def clean_network(self):
        return normalize_network(self.cleaned_data.get('network'))

    def clean(self):
        data = super().clean()
        scope = data.get('scope')
        target = data.get('target') or ''
        if scope == ApiAccessRule.SCOPE_INTEGRATION and target not in INTEGRATIONS:
            self.add_error('target', 'Choose an integration.')
        if scope == ApiAccessRule.SCOPE_ENDPOINT_GROUP and target not in ENDPOINT_GROUPS:
            self.add_error('target', 'Choose an endpoint group.')
        if scope == ApiAccessRule.SCOPE_CUSTOMER and not data.get('organization'):
            self.add_error('organization', 'Choose a customer.')
        if scope == ApiAccessRule.SCOPE_API_KEY and not data.get('api_key'):
            self.add_error('api_key', 'Choose an API key.')
        return data


class ModeForm(forms.Form):
    api_mode = forms.ChoiceField(choices=ApiAccessSettings.MODES, label='Inbound API')
    webhook_mode = forms.ChoiceField(choices=ApiAccessSettings.MODES, label='Inbound webhooks')
    confirm = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('api_mode', 'webhook_mode'):
            self.fields[name].widget.attrs['class'] = 'form-select'


class LimitsForm(forms.Form):
    api_rate_per_address = forms.IntegerField(min_value=0, max_value=100000, label='API requests per minute per address')
    webhook_rate_per_address = forms.IntegerField(min_value=0, max_value=100000, label='Webhook requests per minute per address')
    api_max_body_kb = forms.IntegerField(min_value=0, max_value=1024 * 1024, label='Largest API request (KB)')
    webhook_max_body_kb = forms.IntegerField(min_value=0, max_value=1024 * 1024, label='Largest webhook request (KB)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control form-control-sm', 'min': 0})


class TestAddressForm(forms.Form):
    ip = forms.CharField(label='Source address', max_length=64)
    group = forms.ChoiceField(label='Endpoint group',
                              choices=[(k, label) for k, (label, _s) in ENDPOINT_GROUPS.items()])
    api_key = forms.ModelChoiceField(queryset=None, required=False, label='API key (optional)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from api.models import APIKey
        self.fields['api_key'].queryset = APIKey.objects.filter(is_active=True).order_by('name')
        self.fields['api_key'].label_from_instance = lambda k: f'{k.name} ({k.key_prefix}…)'
        for field in self.fields.values():
            field.widget.attrs['class'] = ('form-select' if isinstance(field.widget, forms.Select)
                                           else 'form-control')

    def clean_ip(self):
        from .policy import parse_ip
        ip = parse_ip(self.cleaned_data['ip'])
        if ip is None:
            raise ValidationError('Enter a single IPv4 or IPv6 address.')
        return ip


class ImportForm(forms.Form):
    file = forms.FileField(label='Rules file (JSON, from Export)',
                           widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.json,application/json'}))
