"""
Payment processing: collecting money against Clientst0r invoices.

Who does what (mandatory architecture):

  * Clientst0r owns the billing schedule. Invoices are created, numbered and
    dated here (psa.Invoice); autopay decides here when an invoice is due.
  * The payment gateway (Stripe, GoCardless) only collects. We never create
    invoices, subscriptions or prices in the gateway: Stripe gets a Checkout
    Session / PaymentIntent for an amount that names our invoice, GoCardless a
    payment against a mandate. There is nothing in the gateway that could
    bill the customer a second time.
  * The accounting system (QuickBooks Online / Xero) records. A settled
    payment becomes a psa.Payment row here and is flagged
    `accounting_post_status='pending'` for the accounting pipeline to post;
    this app never talks to the accounting system (see payments.accounting).

No card numbers, CVVs or bank account numbers are stored: only the provider's
own identifiers (customer id, payment method id, mandate id) and display
details the provider returns (brand, last four digits, expiry, bank name).
`payments.tests.NoCardDataTests` asserts this over every model field.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings as django_settings
from django.db import models


PROVIDERS = [('stripe', 'Stripe'), ('gocardless', 'GoCardless')]

ACCOUNTING_POST_CHOICES = [
    ('not_required', 'Not required'),
    ('pending', 'Waiting for accounting'),
    ('posted', 'Posted to accounting'),
    ('failed', 'Posting failed'),
]


class GatewaySettings(models.Model):
    """Per-connection payment settings that are not credentials.

    The secret key / access token, webhook signing secret and publishable key
    live in the connection's sealed credential blob
    (integrations.PaymentConnection.encrypted_credentials); this row holds the
    plain settings: portal payments and autopay policy.
    """
    connection = models.OneToOneField(
        'integrations.PaymentConnection', on_delete=models.CASCADE,
        related_name='gateway_settings')
    portal_payments_enabled = models.BooleanField(
        default=True,
        help_text='Let billing contacts pay invoices from the customer portal.')
    autopay_enabled = models.BooleanField(
        default=False,
        help_text='Charge the stored, customer-authorized default method when an invoice is due.')
    autopay_lead_days = models.PositiveSmallIntegerField(
        default=0, help_text='Charge this many days before the due date (0 = on the due date).')
    autopay_max_attempts = models.PositiveSmallIntegerField(
        default=3, help_text='Attempts per invoice due date, including the first.')
    autopay_retry_days = models.CharField(
        max_length=60, default='3,5,7',
        help_text='Days to wait before each retry, comma separated (the last value repeats).')
    failure_notify_email = models.CharField(
        max_length=500, blank=True,
        help_text='Who to e-mail when autopay gives up on an invoice (comma separated). '
                  'Blank: superusers and the customer\'s administrators.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments_gateway_settings'

    def __str__(self):
        return f'Settings for {self.connection}'

    def retry_delays(self):
        out = []
        for part in (self.autopay_retry_days or '').split(','):
            part = part.strip()
            if part.isdigit():
                out.append(int(part))
        return out or [3]

    def retry_delay_after(self, attempt_number: int) -> int:
        delays = self.retry_delays()
        return delays[min(max(attempt_number, 1), len(delays)) - 1]


class GatewayCustomer(models.Model):
    """The provider's customer record for one client organization."""
    connection = models.ForeignKey('integrations.PaymentConnection', on_delete=models.CASCADE,
                                   related_name='gateway_customers')
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                   related_name='gateway_customers')
    provider_customer_id = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments_gateway_customers'
        constraints = [
            models.UniqueConstraint(fields=['connection', 'client_org'],
                                    name='uniq_gateway_customer_per_client'),
            models.UniqueConstraint(fields=['connection', 'provider_customer_id'],
                                    name='uniq_gateway_customer_provider_id'),
        ]

    def __str__(self):
        return f'{self.client_org_id} -> {self.provider_customer_id}'


class StoredPaymentMethod(models.Model):
    """A provider-held payment method or mandate. Identifiers and display
    details only: never a card number, CVV or bank account number."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),       # mandate submitted, not active yet
        ('active', 'Active'),
        ('inactive', 'Inactive'),     # cancelled / failed / expired mandate
        ('detached', 'Removed'),
    ]
    TYPE_CHOICES = [
        ('card', 'Card'),
        ('us_bank_account', 'US bank account (ACH)'),
        ('sepa_debit', 'SEPA Direct Debit'),
        ('bacs_debit', 'Bacs Direct Debit'),
        ('direct_debit', 'Direct Debit mandate'),
        ('other', 'Other'),
    ]

    connection = models.ForeignKey('integrations.PaymentConnection', on_delete=models.CASCADE,
                                   related_name='stored_methods')
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                   related_name='stored_payment_methods')
    gateway_customer = models.ForeignKey(GatewayCustomer, on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='methods')
    provider_method_id = models.CharField(
        max_length=120, help_text='Stripe PaymentMethod id (pm_...) or GoCardless mandate id (MD...).')
    mandate_id = models.CharField(max_length=120, blank=True)
    method_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='card')
    brand = models.CharField(max_length=40, blank=True)
    last4 = models.CharField(max_length=4, blank=True)
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_default = models.BooleanField(default=False)
    authorized_for_autopay = models.BooleanField(default=False)
    autopay_authorized_at = models.DateTimeField(null=True, blank=True)
    autopay_authorized_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments_stored_methods'
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['connection', 'provider_method_id'],
                                    name='uniq_stored_method_per_connection'),
        ]

    def __str__(self):
        return self.display

    @property
    def display(self):
        if self.method_type == 'card':
            label = (self.brand or 'Card').title()
            exp = f' (exp {self.exp_month:02d}/{self.exp_year})' if self.exp_month and self.exp_year else ''
            return f'{label} ending {self.last4 or "????"}{exp}'
        bank = self.bank_name or self.get_method_type_display()
        return f'{bank} ending {self.last4}' if self.last4 else bank

    @property
    def usable(self):
        return self.status in ('active', 'pending')


class SetupRequest(models.Model):
    """A provider-hosted flow that adds or replaces a payment method
    (Stripe Checkout mode=setup, GoCardless billing request for a mandate)."""
    STATUS_CHOICES = [('open', 'Open'), ('completed', 'Completed'), ('expired', 'Expired'),
                      ('failed', 'Failed')]
    connection = models.ForeignKey('integrations.PaymentConnection', on_delete=models.CASCADE,
                                   related_name='setup_requests')
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    provider_reference = models.CharField(max_length=120, blank=True,
                                          help_text='Checkout Session id or billing request id.')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    autopay_requested = models.BooleanField(default=False)
    requested_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    payment_method = models.ForeignKey(StoredPaymentMethod, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payments_setup_requests'
        constraints = [
            models.UniqueConstraint(fields=['connection', 'provider_reference'],
                                    condition=models.Q(provider_reference__gt=''),
                                    name='uniq_setup_request_reference'),
        ]


class PaymentAttempt(models.Model):
    """One attempt to collect money for one invoice.

    `idempotency_key` is sent to the provider as the Idempotency-Key header,
    so a retried request can never charge twice; it is unique here too.
    Autopay attempts carry the due cycle (the invoice due date) and an attempt
    number, and (invoice, cycle, number) is unique, so running autopay twice
    creates one attempt.

    `local_payment` is the psa.Payment created when the money settles —
    exactly once per attempt (OneToOne, written under a row lock).
    """
    KIND_CHOICES = [('checkout', 'Customer checkout'), ('autopay', 'Autopay'),
                    ('staff', 'Staff-initiated charge')]
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('requires_action', 'Waiting for the customer'),
        ('processing', 'Processing'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('canceled', 'Canceled'),
    ]
    OPEN_STATUSES = ('created', 'requires_action', 'processing')

    invoice = models.ForeignKey('psa.Invoice', on_delete=models.PROTECT, related_name='payment_attempts')
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    connection = models.ForeignKey('integrations.PaymentConnection', on_delete=models.PROTECT,
                                   related_name='payment_attempts')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='checkout')
    payment_method = models.ForeignKey(StoredPaymentMethod, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='attempts')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    idempotency_key = models.CharField(max_length=120, unique=True)
    provider_object_id = models.CharField(
        max_length=120, blank=True, db_index=True,
        help_text='Stripe PaymentIntent id (pi_...) or GoCardless payment id (PM...).')
    provider_session_id = models.CharField(
        max_length=120, blank=True, db_index=True,
        help_text='Stripe Checkout Session id or GoCardless billing request id.')
    provider_status = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    failure_code = models.CharField(max_length=80, blank=True)
    failure_message = models.TextField(blank=True)
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                     help_text='Processing fee charged by the provider (separate from the payment).')
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    save_for_autopay = models.BooleanField(default=False)

    autopay_cycle = models.CharField(max_length=20, blank=True,
                                     help_text='Autopay: the invoice due date this attempt belongs to.')
    attempt_number = models.PositiveSmallIntegerField(default=1)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    final_failure_notified_at = models.DateTimeField(null=True, blank=True)

    local_payment = models.OneToOneField('psa.Payment', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='gateway_attempt')
    accounting_post_status = models.CharField(max_length=20, choices=ACCOUNTING_POST_CHOICES,
                                              default='not_required', db_index=True)
    accounting_posted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payments_attempts'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['invoice', 'status']),
                   models.Index(fields=['client_org', '-created_at'])]
        constraints = [
            models.UniqueConstraint(fields=['invoice', 'autopay_cycle', 'attempt_number'],
                                    condition=models.Q(kind='autopay'),
                                    name='uniq_autopay_attempt_per_cycle'),
        ]

    def __str__(self):
        return f'{self.get_provider_display()} {self.amount} {self.currency} for {self.invoice_id} ({self.status})'

    @property
    def refunded_amount(self):
        total = Decimal('0')
        for r in self.refunds.filter(status='succeeded'):
            total += r.amount
        return total

    @property
    def refundable_amount(self):
        if self.status != 'succeeded':
            return Decimal('0')
        received = self.amount_received if self.amount_received is not None else self.amount
        pending = sum((r.amount for r in self.refunds.filter(status='pending')), Decimal('0'))
        return max(Decimal('0'), received - self.refunded_amount - pending)


class GatewayEvent(models.Model):
    """A webhook event received from a provider. (provider, event_id) is
    unique: a redelivered event is recognised and not processed again."""
    connection = models.ForeignKey('integrations.PaymentConnection', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='gateway_events')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=120, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = 'payments_gateway_events'
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(fields=['provider', 'event_id'], name='uniq_gateway_event'),
        ]

    def __str__(self):
        return f'{self.provider}:{self.event_id} {self.event_type}'


class Refund(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('succeeded', 'Succeeded'), ('failed', 'Failed'),
                      ('canceled', 'Canceled')]
    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.PROTECT, related_name='refunds')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    reason = models.CharField(max_length=300, blank=True)
    idempotency_key = models.CharField(max_length=120, unique=True)
    provider_refund_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    failure_message = models.TextField(blank=True)
    local_payment = models.OneToOneField(
        'psa.Payment', on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_refund',
        help_text='The negative psa.Payment row that takes the refund off the invoice.')
    accounting_post_status = models.CharField(max_length=20, choices=ACCOUNTING_POST_CHOICES,
                                              default='not_required', db_index=True)
    accounting_posted_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payments_refunds'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['provider_refund_id'], condition=models.Q(provider_refund_id__gt=''),
                                    name='uniq_provider_refund_id'),
        ]

    def __str__(self):
        return f'Refund {self.amount} {self.currency} ({self.status})'


class Dispute(models.Model):
    """A card dispute (Stripe) or Direct Debit chargeback (GoCardless)."""
    STATUS_CHOICES = [('open', 'Open'), ('won', 'Won'), ('lost', 'Lost')]
    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.PROTECT, related_name='disputes')
    provider_dispute_id = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    reason = models.CharField(max_length=120, blank=True)
    provider_status = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    evidence_due_by = models.DateTimeField(null=True, blank=True)
    local_payment = models.OneToOneField(
        'psa.Payment', on_delete=models.SET_NULL, null=True, blank=True, related_name='gateway_dispute',
        help_text='The negative psa.Payment row written when the dispute is lost.')
    accounting_post_status = models.CharField(max_length=20, choices=ACCOUNTING_POST_CHOICES,
                                              default='not_required', db_index=True)
    accounting_posted_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payments_disputes'
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(fields=['provider_dispute_id'], name='uniq_provider_dispute_id'),
        ]

    def __str__(self):
        return f'Dispute {self.provider_dispute_id} ({self.status})'
