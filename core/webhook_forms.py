"""
Forms for webhook management.
"""
import json

from django import forms
from core.models import Webhook
from vault.secret_fields import SecretInput
from core.webhook_events import SUPPORTED_EVENTS

# Shown in place of each stored header value. Submitting it back unchanged
# keeps that header's stored value.
HEADER_VALUE_MASK = '********'

# Only event types that actually fire (core.webhook_events). The model still
# lists every historical constant; offering ones with no source made the form
# promise deliveries that could never happen.
OFFERED_EVENT_CHOICES = [
    (value, label) for value, label in Webhook.EVENT_CHOICES
    if value in SUPPORTED_EVENTS
]


class WebhookForm(forms.ModelForm):
    """Form for creating and editing webhooks."""

    events = forms.MultipleChoiceField(
        choices=OFFERED_EVENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select which events should trigger this webhook'
    )
    # Header values are often credentials (Authorization: Bearer ...). They
    # are stored encrypted and rendered back masked — names only.
    custom_headers = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': '{"Authorization": "Bearer your-token-here"}'
        }),
        help_text='JSON object of custom HTTP headers (optional). Stored values '
                  f'are shown as {HEADER_VALUE_MASK}; leave a value as '
                  f'{HEADER_VALUE_MASK} to keep it.',
    )

    class Meta:
        model = Webhook
        fields = ['name', 'url', 'events', 'secret', 'is_active', 'custom_headers']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Asset Notifications'
            }),
            'url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://your-api.com/webhooks/clientst0r'
            }),
            # Never rendered back; blank keeps the stored secret.
            'secret': SecretInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional: Secret key for signing payloads (blank keeps the current one)'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
        help_texts = {
            'name': 'Descriptive name to identify this webhook',
            'url': 'Destination URL for webhook POST requests',
            'secret': 'Secret key for HMAC-SHA256 signature in X-Webhook-Signature header (optional)',
            'is_active': 'Enable or disable this webhook',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing existing webhook, convert events list to selected choices
        if self.instance and self.instance.pk:
            self.initial['events'] = [
                e for e in (self.instance.events or []) if e in SUPPORTED_EVENTS
            ]
            headers = self.instance.custom_headers
            if isinstance(headers, dict) and headers:
                self.initial['custom_headers'] = json.dumps(
                    {k: HEADER_VALUE_MASK for k in headers}, indent=2)
            else:
                self.initial['custom_headers'] = ''

    def clean_custom_headers(self):
        """Validate custom headers JSON; masked values keep the stored value."""
        custom_headers = self.cleaned_data.get('custom_headers', '')

        if not custom_headers:
            return {}

        try:
            headers = json.loads(custom_headers)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {str(e)}')
        if not isinstance(headers, dict):
            raise forms.ValidationError('Custom headers must be a JSON object (dictionary).')
        existing = {}
        if self.instance and self.instance.pk and isinstance(self.instance.custom_headers, dict):
            existing = self.instance.custom_headers
        for key, value in list(headers.items()):
            if value == HEADER_VALUE_MASK:
                if key not in existing:
                    raise forms.ValidationError(
                        f'Header "{key}" has no stored value; enter one.')
                headers[key] = existing[key]
        return headers

    def clean_events(self):
        """Convert selected events to list for JSONField."""
        events = self.cleaned_data.get('events', [])
        return list(events)


class WebhookTestForm(forms.Form):
    """Form for testing webhook delivery."""

    test_event = forms.ChoiceField(
        choices=OFFERED_EVENT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Select an event type to test'
    )

    test_payload = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 10,
            'placeholder': '{"test": true, "message": "This is a test webhook"}'
        }),
        help_text='Custom JSON payload for testing (optional)',
        required=False
    )

    def clean_test_payload(self):
        """Validate test payload JSON."""
        import json
        payload = self.cleaned_data.get('test_payload', '')

        if not payload:
            return {'test': True, 'message': 'Test webhook delivery'}

        try:
            return json.loads(payload)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {str(e)}')
