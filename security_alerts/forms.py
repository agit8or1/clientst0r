from django import forms
from .models import (
    SecurityAlertRule,
    SecurityVendorConnection,
    SIEMWebhookEndpoint,
)


# Bootstrap 5 widget classes applied at form-class level so the templates
# don't need ad-hoc CSS overrides (the previous inline `<style>` block in
# rule_form.html / connection_form.html was working around this).
_TEXT = {'class': 'form-control'}
_SELECT = {'class': 'form-select'}
_CHECK = {'class': 'form-check-input'}
_NUMBER = {'class': 'form-control', 'inputmode': 'numeric'}
_URL = {'class': 'form-control', 'inputmode': 'url'}


class SecurityVendorConnectionForm(forms.ModelForm):
    class Meta:
        model = SecurityVendorConnection
        fields = [
            'name', 'provider', 'category', 'client_org',
            'base_url', 'credentials_encrypted',
            'poll_interval_minutes', 'is_active', 'sync_enabled', 'require_signature', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs=_TEXT),
            'provider': forms.Select(attrs=_SELECT),
            'category': forms.Select(attrs=_SELECT),
            'client_org': forms.Select(attrs=_SELECT),
            'base_url': forms.URLInput(attrs=_URL),
            'credentials_encrypted': forms.Textarea(attrs={**_TEXT, 'rows': 3,
                'placeholder': 'JSON or vendor-specific credential blob (encrypted at rest)'}),
            'poll_interval_minutes': forms.NumberInput(attrs={**_NUMBER, 'min': 1, 'max': 1440}),
            'is_active': forms.CheckboxInput(attrs=_CHECK),
            'sync_enabled': forms.CheckboxInput(attrs=_CHECK),
            'require_signature': forms.CheckboxInput(attrs=_CHECK),
            'notes': forms.Textarea(attrs={**_TEXT, 'rows': 3,
                'placeholder': 'Internal notes — e.g. who set this up, ticket links, vendor portal account.'}),
        }


class SecurityAlertRuleForm(forms.ModelForm):
    class Meta:
        model = SecurityAlertRule
        fields = [
            'name', 'is_active', 'priority',
            'match_provider', 'match_category', 'match_severity_min',
            'match_client_org',
            'action', 'ticket_queue_id', 'ticket_priority_code', 'ticket_assignee',
            'suppress_start_hour', 'suppress_end_hour',
            'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs=_TEXT),
            'is_active': forms.CheckboxInput(attrs=_CHECK),
            'priority': forms.NumberInput(attrs={**_NUMBER, 'min': 0, 'max': 9999}),
            'match_provider': forms.TextInput(attrs={**_TEXT,
                'placeholder': 'e.g. security_defender (blank = any provider)'}),
            'match_category': forms.TextInput(attrs={**_TEXT,
                'placeholder': 'e.g. security_edr (blank = any category)'}),
            'match_severity_min': forms.Select(attrs=_SELECT),
            'match_client_org': forms.Select(attrs=_SELECT),
            'action': forms.TextInput(attrs={**_TEXT, 'placeholder': 'create_ticket'}),
            'ticket_queue_id': forms.NumberInput(attrs=_NUMBER),
            'ticket_priority_code': forms.TextInput(attrs={**_TEXT, 'placeholder': 'P1 / P2 / P3 / P4'}),
            'ticket_assignee': forms.Select(attrs=_SELECT),
            'suppress_start_hour': forms.NumberInput(attrs={**_NUMBER, 'min': 0, 'max': 23,
                'placeholder': '0-23'}),
            'suppress_end_hour': forms.NumberInput(attrs={**_NUMBER, 'min': 0, 'max': 23,
                'placeholder': '0-23'}),
            'notes': forms.Textarea(attrs={**_TEXT, 'rows': 3,
                'placeholder': 'Why this rule exists; who owns it.'}),
        }


class SIEMWebhookEndpointForm(forms.ModelForm):
    """Phase 23 v3.17.337 — generic SIEM/Syslog/CEF inbound endpoint."""

    class Meta:
        model = SIEMWebhookEndpoint
        fields = [
            'name', 'expected_format', 'client_org',
            'require_hmac', 'default_severity',
            'is_active', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs=_TEXT),
            'expected_format': forms.Select(attrs=_SELECT),
            'client_org': forms.Select(attrs=_SELECT),
            'require_hmac': forms.CheckboxInput(attrs=_CHECK),
            'default_severity': forms.Select(attrs=_SELECT),
            'is_active': forms.CheckboxInput(attrs=_CHECK),
            'notes': forms.Textarea(attrs={**_TEXT, 'rows': 3,
                'placeholder': 'Source SIEM, who configured it, intended use case.'}),
        }
