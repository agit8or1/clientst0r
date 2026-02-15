"""
Forms for webhook management.
"""
from django import forms
from core.models import Webhook


class WebhookForm(forms.ModelForm):
    """Form for creating and editing webhooks."""

    events = forms.MultipleChoiceField(
        choices=Webhook.EVENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select which events should trigger this webhook'
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
            'secret': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional: Secret key for signing payloads'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'custom_headers': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '{"Authorization": "Bearer your-token-here"}'
            }),
        }
        help_texts = {
            'name': 'Descriptive name to identify this webhook',
            'url': 'Destination URL for webhook POST requests',
            'secret': 'Secret key for HMAC-SHA256 signature in X-Webhook-Signature header (optional)',
            'is_active': 'Enable or disable this webhook',
            'custom_headers': 'JSON object of custom HTTP headers (optional)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing existing webhook, convert events list to selected choices
        if self.instance and self.instance.pk:
            self.initial['events'] = self.instance.events

    def clean_custom_headers(self):
        """Validate custom headers JSON."""
        import json
        custom_headers = self.cleaned_data.get('custom_headers', '')

        if not custom_headers:
            return {}

        try:
            headers = json.loads(custom_headers)
            if not isinstance(headers, dict):
                raise forms.ValidationError('Custom headers must be a JSON object (dictionary).')
            return headers
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {str(e)}')

    def clean_events(self):
        """Convert selected events to list for JSONField."""
        events = self.cleaned_data.get('events', [])
        return list(events)


class WebhookTestForm(forms.Form):
    """Form for testing webhook delivery."""

    test_event = forms.ChoiceField(
        choices=Webhook.EVENT_CHOICES,
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
