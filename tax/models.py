"""Sales tax: settings, manual rates, categories, exemptions and the audit
record of every calculation.

Scope: one MSP per install, and an Organization is one of its customers.
TaxSettings, ManualTaxRate and TaxCategory are MSP-wide: they are the rows
with no organization (the platform-owned pattern used by integration
connections); the organization column is kept nullable for that pattern and
is not used for lookups. CustomerTaxExemption belongs to one customer, and the
jurisdiction comes from that customer's billing address.

Nothing here is a psa migration: the link from a quote / invoice to its
current calculation is `TaxCalculation(document_type, document_id,
is_current=True)`, so the psa schema is untouched (see docs/TAX.md).
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import BaseModel


class TaxSettings(BaseModel):
    MODE_NONE = 'none'
    MODE_FLAT = 'flat'
    MODE_MANUAL = 'manual'
    MODE_AVALARA = 'avalara'
    MODE_TAXJAR = 'taxjar'
    MODES = [
        (MODE_NONE, 'No sales tax (documents show "tax not configured", tax is zero)'),
        (MODE_FLAT, 'Flat rate typed on each quote / invoice (legacy)'),
        (MODE_MANUAL, 'Manual jurisdiction rates (ClientSt0r rate table)'),
        (MODE_AVALARA, 'Avalara AvaTax'),
        (MODE_TAXJAR, 'TaxJar'),
    ]
    PROVIDER_MODES = (MODE_AVALARA, MODE_TAXJAR)

    AUTHORITY_CHOICES = [
        ('clientst0r', 'ClientSt0r calculates; the accounting system records the amount it is sent'),
        ('provider', 'The tax provider calculates and reports; ClientSt0r and accounting record it'),
        ('accounting', 'The accounting system calculates its own tax (ClientSt0r amounts are estimates)'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='tax_settings',
        help_text='Blank: install-wide (MSP-wide). The only scope used.')
    mode = models.CharField(max_length=20, choices=MODES, default=MODE_FLAT)
    authoritative_system = models.CharField(max_length=20, choices=AUTHORITY_CHOICES,
                                            default='clientst0r')
    authority_note = models.TextField(
        blank=True, help_text='Which system is authoritative for tax, and why (shown on the settings page).')
    connection = models.ForeignKey(
        'integrations.TaxConnection', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tax_settings',
        help_text='Avalara / TaxJar credentials (sealed). Required for a provider mode.')
    sandbox = models.BooleanField(default=False, help_text='Use the provider sandbox endpoint.')
    labor_taxable = models.BooleanField(
        default=False, help_text='Default treatment of labor lines (a jurisdiction rate can override).')
    shipping_taxable = models.BooleanField(default=False)
    nexus_regions = models.JSONField(
        default=list, blank=True,
        help_text='Regions where tax is collected, e.g. ["US-CA", "US-NY"]. Empty: everywhere a rate matches.')

    # Ship-from / origin address sent to providers.
    origin_line1 = models.CharField(max_length=255, blank=True)
    origin_city = models.CharField(max_length=100, blank=True)
    origin_region = models.CharField(max_length=50, blank=True, help_text='State / province code, e.g. CA')
    origin_postal_code = models.CharField(max_length=20, blank=True)
    origin_country = models.CharField(max_length=2, default='US')

    class Meta:
        db_table = 'tax_settings'
        constraints = [
            models.UniqueConstraint(fields=['organization'], name='tax_settings_one_per_org'),
        ]

    def __str__(self):
        return f'Tax settings ({self.organization or "platform"}): {self.get_mode_display()}'

    @property
    def is_provider_mode(self):
        return self.mode in self.PROVIDER_MODES

    def origin(self):
        return {'line1': self.origin_line1, 'city': self.origin_city, 'region': self.origin_region,
                'postal_code': self.origin_postal_code, 'country': self.origin_country or 'US'}


class TaxCategory(BaseModel):
    KIND_CHOICES = [
        ('goods', 'Goods / hardware'),
        ('service', 'Services'),
        ('labor', 'Labor'),
        ('software', 'Software / subscriptions'),
        ('shipping', 'Shipping'),
        ('other', 'Other'),
    ]
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='tax_categories')
    code = models.SlugField(max_length=50)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='goods')
    taxable = models.BooleanField(
        default=True, help_text='Default taxability (labor and shipping follow the settings instead).')
    is_default = models.BooleanField(default=False, help_text='Used for lines with no category.')
    avalara_tax_code = models.CharField(max_length=50, blank=True)
    taxjar_product_tax_code = models.CharField(max_length=50, blank=True)
    qbo_tax_code_id = models.CharField(max_length=50, blank=True, help_text='QuickBooks Online TaxCode Id')
    xero_tax_type = models.CharField(max_length=50, blank=True, help_text='Xero TaxType, e.g. OUTPUT')

    class Meta:
        db_table = 'tax_categories'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'code'], name='tax_category_code_per_org'),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'


class ManualTaxRate(BaseModel):
    """One jurisdiction's combined rate. Matching picks the single most
    specific rate (zip > city > county > state > country); rates do not stack."""
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='manual_tax_rates')
    name = models.CharField(max_length=120, help_text='Shown in the jurisdiction breakdown')
    country = models.CharField(max_length=2, default='US')
    state = models.CharField(max_length=50, blank=True, help_text='State / region code, e.g. CA')
    county = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    zip_pattern = models.CharField(
        max_length=20, blank=True,
        help_text='Exact zip ("94105"), prefix with * ("941*") or blank for any.')
    rate = models.DecimalField(max_digits=7, decimal_places=5,
                               validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('1'))],
                               help_text='Combined rate as a fraction: 0.0875 = 8.75%')
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    applies_to = models.ManyToManyField(
        TaxCategory, blank=True, related_name='manual_rates',
        help_text='Categories this rate taxes. Empty: every taxable category.')
    labor_taxable = models.BooleanField(
        null=True, blank=True, help_text='Override the settings default for labor here (blank: use default).')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'tax_manual_rates'
        ordering = ['country', 'state', 'county', 'city', 'zip_pattern']

    def __str__(self):
        return f'{self.name} {self.rate}'

    @property
    def rate_percent(self):
        return (self.rate * 100).normalize()


class CustomerTaxExemption(BaseModel):
    REASONS = [
        ('resale', 'Resale'),
        ('government', 'Government'),
        ('nonprofit', 'Nonprofit / charitable'),
        ('education', 'Education'),
        ('religious', 'Religious'),
        ('other', 'Other'),
    ]
    # Avalara entity/use codes and TaxJar exemption types per reason.
    AVALARA_ENTITY_USE = {'resale': 'G', 'government': 'B', 'nonprofit': 'E', 'education': 'M',
                          'religious': 'D', 'other': 'L'}
    TAXJAR_EXEMPTION = {'resale': 'wholesale', 'government': 'government', 'nonprofit': 'other',
                        'education': 'other', 'religious': 'other', 'other': 'other'}

    client = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                               related_name='tax_exemptions')
    reason = models.CharField(max_length=20, choices=REASONS)
    certificate_number = models.CharField(max_length=100)
    certificate = models.ForeignKey('files.Attachment', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    jurisdictions = models.JSONField(
        default=list, blank=True, help_text='Regions covered, e.g. ["US-CA"]. Empty: everywhere.')
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='+')
    verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'tax_customer_exemptions'
        ordering = ['-valid_to', '-created_at']

    def __str__(self):
        return f'{self.client} exempt ({self.get_reason_display()}) #{self.certificate_number}'

    def covers(self, on_date, region_key: str = '') -> bool:
        """Valid on `on_date` for `region_key` ('US-CA'): active, verified,
        a certificate number, inside its dates, and the region listed (or
        no regions listed)."""
        if not (self.is_active and self.verified_at and (self.certificate_number or '').strip()):
            return False
        if self.valid_from and on_date < self.valid_from:
            return False
        if self.valid_to and on_date > self.valid_to:
            return False
        regions = [r.upper() for r in (self.jurisdictions or [])]
        return not regions or (region_key or '').upper() in regions

    @property
    def status_label(self):
        today = timezone.localdate()
        if not self.is_active:
            return 'inactive'
        if not self.verified_at:
            return 'unverified'
        if self.valid_to and today > self.valid_to:
            return 'expired'
        if self.valid_from and today < self.valid_from:
            return 'not yet valid'
        return 'valid'


class TaxCalculation(models.Model):
    """One tax determination for a document, kept for audit and
    reconciliation. The document's current one has is_current=True."""
    STATUS_OK = 'ok'
    STATUS_ERROR = 'error'
    STATUS_EXEMPT = 'exempt'
    STATUS_NOT_CONFIGURED = 'not_configured'
    STATUS_CHOICES = [
        (STATUS_OK, 'Calculated'),
        (STATUS_ERROR, 'Error'),
        (STATUS_EXEMPT, 'Exempt'),
        (STATUS_NOT_CONFIGURED, 'Tax not configured'),
    ]
    PROVIDERS = [
        ('none', 'None'), ('flat', 'Flat rate'), ('manual', 'Manual rates'),
        ('avalara', 'Avalara AvaTax'), ('taxjar', 'TaxJar'), ('override', 'Manual override'),
    ]
    PURPOSES = [('preview', 'Preview'), ('finalize', 'Finalize'), ('override', 'Override')]

    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True,
                                     related_name='tax_calculations')
    document_type = models.CharField(max_length=20, db_index=True)   # quote | invoice
    document_id = models.PositiveIntegerField(db_index=True)
    document_number = models.CharField(max_length=40, blank=True)
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    purpose = models.CharField(max_length=20, choices=PURPOSES, default='preview')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    request_hash = models.CharField(max_length=64, blank=True)
    lines_fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    ship_to = models.JSONField(default=dict, blank=True)
    line_breakdown = models.JSONField(default=list, blank=True)
    jurisdiction_breakdown = models.JSONField(default=list, blank=True)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    committed = models.BooleanField(default=False)
    committed_at = models.DateTimeField(null=True, blank=True)
    provider_transaction_code = models.CharField(max_length=100, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_error = models.TextField(blank=True)
    error = models.TextField(blank=True)
    reason = models.TextField(blank=True, help_text='Why this result: not configured, exemption, override')
    exemption = models.ForeignKey(CustomerTaxExemption, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='calculations')
    is_current = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_calculations'
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['document_type', 'document_id', 'is_current'])]

    def __str__(self):
        return f'{self.document_type} {self.document_number or self.document_id}: {self.status} {self.total_tax}'

    @property
    def blocks_finalization(self):
        return self.status == self.STATUS_ERROR


class LineTaxCategory(models.Model):
    """Category picked for one quote / invoice line (no psa column needed)."""
    line_type = models.CharField(max_length=20)    # quote_line | invoice_line
    line_id = models.PositiveIntegerField()
    category = models.ForeignKey(TaxCategory, on_delete=models.CASCADE, related_name='line_assignments')

    class Meta:
        db_table = 'tax_line_categories'
        constraints = [models.UniqueConstraint(fields=['line_type', 'line_id'], name='tax_line_category_once')]
