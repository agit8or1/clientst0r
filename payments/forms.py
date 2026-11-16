from __future__ import annotations

from decimal import Decimal

from django import forms


class ConnectionForm(forms.Form):
    """A payment connection plus its sealed credentials and gateway settings.
    Secret fields are write-only: left blank, the stored value is kept."""
    name = forms.CharField(max_length=200)
    provider_type = forms.ChoiceField(choices=[('stripe', 'Stripe (cards + ACH)'),
                                               ('gocardless', 'GoCardless (Direct Debit / ACH)')])
    is_active = forms.BooleanField(required=False, initial=True)
    sync_enabled = forms.BooleanField(required=False, label='Live collection enabled',
                                      help_text='Off: nothing is charged and the portal shows no Pay button.')
    secret_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
                                 label='Secret key / access token',
                                 help_text='Stripe secret or restricted key; GoCardless access token. '
                                           'Blank keeps the stored value.')
    publishable_key = forms.CharField(required=False, label='Publishable key (Stripe)')
    webhook_secret = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
                                     label='Webhook signing secret', help_text='Blank keeps the stored value.')
    environment = forms.ChoiceField(choices=[('live', 'Live'), ('sandbox', 'Sandbox')], initial='live',
                                    help_text='GoCardless only. Stripe test mode follows the key (sk_test_...).')
    portal_payments_enabled = forms.BooleanField(required=False, initial=True,
                                                 label='Customers can pay invoices in the portal')
    autopay_enabled = forms.BooleanField(required=False, label='Autopay')
    autopay_lead_days = forms.IntegerField(min_value=0, max_value=30, initial=0)
    autopay_max_attempts = forms.IntegerField(min_value=1, max_value=10, initial=3)
    autopay_retry_days = forms.RegexField(regex=r'^\s*\d+(\s*,\s*\d+)*\s*$', initial='3,5,7', max_length=60)
    failure_notify_email = forms.CharField(required=False, max_length=500)


class RefundForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal('0.01'), max_digits=12, decimal_places=2)
    reason = forms.CharField(required=False, max_length=300)
    confirm = forms.BooleanField(required=True, label='I confirm this refund')
