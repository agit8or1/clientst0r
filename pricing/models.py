"""
Pricing: price books, service plans and labor rate cards.

Ownership: one install serves exactly one MSP, and `core.Organization` is a
customer of that MSP. So MSP-level objects (PriceBook, ServicePlan,
LaborRole) follow the platform-owned pattern of the integrations app
(`ConnectionOwnership`): `organization` NULL = install-wide (the MSP's own,
the normal case); set = that one customer's own book / plan / role, used only
for that customer. Customer-specific objects (CustomerPriceOverride,
ClientServicePlan, and customer-scoped RateCard / BillingRule rows) are keyed
by `client_org`; a RateCard / BillingRule with neither client_org nor
contract is the MSP-wide default. Resolution (pricing.services) never lets
one customer's overrides, plans, rates or own books apply to another.

Money is `Decimal` throughout. Nothing here supplies a made-up default
price or rate: an unset price is NULL and the resolver reports it missing.

Name clashes to avoid: `psa.ServiceCatalogItem` is a ticket REQUEST template
and `hardware.CatalogSource` is a hardware-spec import source. Neither has
anything to do with prices.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

ZERO = Decimal('0')
OWNER_HELP = ("Empty: install-wide (the MSP's own, the normal case). "
              "Set: this customer's own, used only for this customer.")
HUNDRED = Decimal('100')
CURRENCY_HELP = 'ISO 4217 code, e.g. USD, EUR, GBP.'


def _money(**kw):
    return models.DecimalField(max_digits=12, decimal_places=2, **kw)


def _pct(**kw):
    return models.DecimalField(max_digits=7, decimal_places=3, **kw)


def _in_effect(qs, on_date, from_field='effective_from', to_field='effective_to'):
    """Rows whose [from, to] window (either end open when NULL) covers on_date."""
    return qs.filter(
        models.Q(**{f'{from_field}__isnull': True}) | models.Q(**{f'{from_field}__lte': on_date}),
    ).filter(
        models.Q(**{f'{to_field}__isnull': True}) | models.Q(**{f'{to_field}__gte': on_date}),
    )


def _check_window(obj, from_field='effective_from', to_field='effective_to'):
    start, end = getattr(obj, from_field), getattr(obj, to_field)
    if start and end and end < start:
        raise ValidationError({to_field: 'The end date is before the start date.'})


# ---------------------------------------------------------------------------
# Price books
# ---------------------------------------------------------------------------

class PriceBook(models.Model):
    """A named list of sellable items (install-wide, or one customer's own)."""
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='price_books',
        help_text=OWNER_HELP)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default='USD', help_text=CURRENCY_HELP)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text='The book new quotes start from. At most one install-wide, and one per customer.')
    copied_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copies')
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing_price_books'
        ordering = ['organization_id', 'name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='pricing_book_unique_name'),
            models.UniqueConstraint(fields=['name'], condition=models.Q(organization__isnull=True),
                                    name='pricing_book_unique_name_install'),
            models.UniqueConstraint(fields=['organization'], condition=models.Q(is_default=True),
                                    name='pricing_one_default_book_per_org'),
            models.UniqueConstraint(fields=['is_default'],
                                    condition=models.Q(is_default=True, organization__isnull=True),
                                    name='pricing_one_default_book_install'),
        ]

    @property
    def is_install_wide(self):
        return self.organization_id is None

    def applies_to(self, client_org):
        """Install-wide books apply to every customer; a customer's own book
        only to that customer."""
        return self.organization_id is None or (
            client_org is not None and self.organization_id == getattr(client_org, 'pk', client_org))

    def __str__(self):
        return f'{self.name} ({self.currency})'

    def duplicate(self, name=None, user=None):
        """Copy the book, its items and their tiers. Customer overrides and
        scheduled changes stay with the original (they name original items).
        The copy is inactive and not the default until someone turns it on."""
        with transaction.atomic():
            copy = PriceBook.objects.create(
                organization=self.organization, name=name or f'{self.name} (copy)',
                description=self.description, currency=self.currency, is_active=False,
                is_default=False, copied_from=self, created_by=user)
            for item in self.items.all().prefetch_related('tiers'):
                tiers = list(item.tiers.all())
                item.pk = None
                item.id = None
                item.price_book = copy
                item._state.adding = True
                item.save(_history_source='duplicate', _changed_by=user, _skip_history=True)
                for t in tiers:
                    PriceTier.objects.create(item=item, min_quantity=t.min_quantity,
                                             max_quantity=t.max_quantity, unit_price=t.unit_price)
        return copy


class PriceBookItem(models.Model):
    ITEM_TYPES = [
        ('managed_service', 'Managed service'),
        ('per_user', 'Per-user service'),
        ('per_device', 'Per-device service'),
        ('per_server', 'Per-server service'),
        ('per_site', 'Per-site service'),
        ('security', 'Security service'),
        ('backup', 'Backup service'),
        ('m365', 'Microsoft 365'),
        ('gws', 'Google Workspace'),
        ('hosting', 'Hosting'),
        ('storage', 'Storage'),
        ('hardware', 'Hardware'),
        ('software_license', 'Software license'),
        ('labor', 'Labor'),
        ('project', 'Project'),
        ('consulting', 'Consulting'),
        ('vcio', 'vCIO / strategy'),
        ('onsite', 'Onsite service'),
        ('remote', 'Remote service'),
        ('emergency', 'Emergency service'),
        ('after_hours', 'After-hours service'),
        ('maintenance', 'Maintenance'),
        ('one_time', 'One-time fee'),
        ('usage', 'Usage-based'),
        ('custom', 'Custom'),
    ]
    PRICING_MODELS = [
        ('fixed', 'Fixed'),
        ('per_user', 'Per user'),
        ('per_device', 'Per device'),
        ('per_server', 'Per server'),
        ('per_site', 'Per site'),
        ('per_license', 'Per license'),
        ('per_gb', 'Per GB'),
        ('per_tb', 'Per TB'),
        ('per_month', 'Per month'),
        ('per_year', 'Per year'),
        ('per_hour', 'Per hour'),
        ('per_incident', 'Per incident'),
        ('per_project', 'Per project'),
        ('per_transaction', 'Per transaction'),
        ('metered', 'Metered'),
        ('tiered', 'Tiered (graduated)'),
        ('volume', 'Volume'),
        ('bundle', 'Bundle'),
        ('pass_through', 'Pass-through'),
    ]
    TIERED_MODELS = ('tiered', 'volume')
    BILLING_FREQUENCIES = [
        ('', 'Not recurring'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semiannual', 'Every six months'),
        ('yearly', 'Yearly'),
        ('multi_year', 'Multi-year'),
    ]
    # Fields whose changes are recorded in PriceChangeHistory.
    TRACKED_FIELDS = ('cost', 'default_price', 'minimum_price', 'target_margin_pct')
    # Internal cost data: hidden from anyone without
    # `pricing_view_internal_cost_rates` (pricing.permissions).
    COST_FIELDS = ('cost', 'target_margin_pct', 'internal_notes', 'vendor_sku', 'distributor')

    price_book = models.ForeignKey(PriceBook, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=80, help_text='Unique within the price book.')
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    item_type = models.CharField(max_length=30, choices=ITEM_TYPES, default='custom')
    unit_of_measure = models.CharField(max_length=40, blank=True,
                                       help_text='e.g. user, device, hour, GB, each.')
    pricing_model = models.CharField(max_length=30, choices=PRICING_MODELS, default='fixed')

    cost = _money(null=True, blank=True, help_text='Internal unit cost. Blank = unknown.')
    default_price = _money(null=True, blank=True,
                           help_text='Unit sell price. Blank = no list price (resolution reports it missing).')
    minimum_price = _money(null=True, blank=True,
                           help_text='Floor below which a price needs discount approval.')
    target_margin_pct = _pct(null=True, blank=True)

    tax_category = models.CharField(max_length=60, blank=True)
    revenue_account_code = models.CharField(max_length=40, blank=True,
                                            help_text='GL / accounting item code for revenue.')
    vendor = models.ForeignKey('assets.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='price_book_items')
    vendor_sku = models.CharField(max_length=120, blank=True)
    distributor = models.CharField(
        max_length=50, blank=True,
        choices=[('', '—')] + [
            ('ingram_xvantage', 'Ingram Micro Xvantage'), ('synnex', 'TD Synnex'),
            ('d_and_h', 'D&H Distributing'), ('scansource', 'ScanSource'), ('pax8', 'Pax8'),
            ('qbs', 'QBS Software'), ('westcoast', 'Westcoast'), ('other', 'Other'),
        ],
        help_text='Same keys as integrations.DistributorConnection.provider_type.')

    is_recurring = models.BooleanField(default=False)
    billing_frequency = models.CharField(max_length=20, choices=BILLING_FREQUENCIES, blank=True, default='')
    min_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    customer_visible = models.BooleanField(default=True,
                                           help_text='Shown to customers (quotes, portal).')
    internal_notes = models.TextField(blank=True)
    external_ids = models.JSONField(default=dict, blank=True,
                                    help_text='Provider ids, e.g. {"qbo_item": "42", "pax8": "..."}')
    currency = models.CharField(max_length=3, blank=True, help_text='Blank = the price book currency.')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing_price_book_items'
        ordering = ['price_book_id', 'category', 'name']
        constraints = [
            models.UniqueConstraint(fields=['price_book', 'sku'], name='pricing_item_unique_sku_per_book'),
        ]
        indexes = [models.Index(fields=['price_book', 'is_active'])]

    def __str__(self):
        return f'{self.sku} — {self.name}'

    @property
    def organization(self):
        return self.price_book.organization

    @property
    def organization_id(self):
        return self.price_book.organization_id

    @property
    def effective_currency(self):
        return self.currency or self.price_book.currency

    def clean(self):
        _check_window(self)
        if self.min_quantity is not None and self.max_quantity is not None \
                and self.max_quantity < self.min_quantity:
            raise ValidationError({'max_quantity': 'Maximum quantity is below the minimum.'})
        if self.is_recurring and not self.billing_frequency:
            raise ValidationError({'billing_frequency': 'A recurring item needs a billing frequency.'})
        for f in ('cost', 'default_price', 'minimum_price'):
            v = getattr(self, f)
            if v is not None and v < 0:
                raise ValidationError({f: 'Must not be negative.'})

    def is_in_effect(self, on_date):
        if self.effective_from and on_date < self.effective_from:
            return False
        if self.effective_to and on_date > self.effective_to:
            return False
        return True

    def save(self, *args, **kwargs):
        """Pass `_changed_by` / `_history_source` / `_history_note` to label
        the PriceChangeHistory rows written for changed TRACKED_FIELDS."""
        changed_by = kwargs.pop('_changed_by', None)
        source = kwargs.pop('_history_source', 'edit')
        note = kwargs.pop('_history_note', '')
        skip = kwargs.pop('_skip_history', False)
        prior = None
        if self.pk and not skip:
            prior = PriceBookItem.objects.filter(pk=self.pk).values(*self.TRACKED_FIELDS).first()
        super().save(*args, **kwargs)
        if skip:
            return
        if prior is None:
            changes = {f: (None, getattr(self, f)) for f in self.TRACKED_FIELDS
                       if getattr(self, f) is not None}
        else:
            changes = {f: (prior[f], getattr(self, f)) for f in self.TRACKED_FIELDS
                       if _dec(prior[f]) != _dec(getattr(self, f))}
        for f, (old, new) in changes.items():
            PriceChangeHistory.record(self, f, old, new, changed_by=changed_by, source=source, note=note)


def _dec(v):
    if v is None:
        return None
    return Decimal(str(v))


class PriceTier(models.Model):
    """One quantity band of a `tiered` (graduated) or `volume` item.

    tiered: each unit is priced by the band it falls in (units 1-10 at A,
            11-50 at B, ...), and the line total is the sum.
    volume: every unit is priced at the band the total quantity falls in.
    `max_quantity` NULL = open-ended top band.
    """
    item = models.ForeignKey(PriceBookItem, on_delete=models.CASCADE, related_name='tiers')
    min_quantity = models.DecimalField(max_digits=12, decimal_places=2,
                                       help_text='First quantity of the band (inclusive), e.g. 1.')
    max_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                       help_text='Last quantity of the band (inclusive). Blank = no limit.')
    unit_price = _money()

    class Meta:
        db_table = 'pricing_price_tiers'
        ordering = ['item_id', 'min_quantity']
        constraints = [
            models.UniqueConstraint(fields=['item', 'min_quantity'], name='pricing_tier_unique_start'),
        ]

    def __str__(self):
        top = self.max_quantity if self.max_quantity is not None else '∞'
        return f'{self.min_quantity}–{top} @ {self.unit_price}'

    def clean(self):
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValidationError({'max_quantity': 'Maximum is below the minimum.'})


class CustomerPriceOverride(models.Model):
    """A negotiated price for one customer, optionally only under one contract.

    Exactly one of `unit_price` (fixed) and `markup_pct` (cost + %) is set.
    A markup on an item without a cost does not resolve (reported missing)."""
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                   related_name='pricing_overrides')
    item = models.ForeignKey(PriceBookItem, on_delete=models.CASCADE, related_name='customer_overrides')
    contract = models.ForeignKey('psa.Contract', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='price_overrides',
                                 help_text='Only under this contract. Blank = any.')
    unit_price = _money(null=True, blank=True)
    markup_pct = _pct(null=True, blank=True, help_text='Price = item cost × (1 + markup / 100).')
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='Who approved a price below the item minimum (pricing_approve_discounts).')
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def organization_id(self):
        """The customer this override belongs to (audit / permission scope)."""
        return self.client_org_id

    class Meta:
        db_table = 'pricing_customer_overrides'
        ordering = ['client_org_id', 'item_id', '-effective_from']
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(unit_price__isnull=False, markup_pct__isnull=True)
                           | models.Q(unit_price__isnull=True, markup_pct__isnull=False)),
                name='pricing_override_price_xor_markup'),
        ]
        indexes = [models.Index(fields=['client_org', 'item'])]

    def __str__(self):
        how = f'{self.unit_price}' if self.unit_price is not None else f'cost +{self.markup_pct}%'
        return f'{self.client_org} · {self.item.sku}: {how}'

    def clean(self):
        _check_window(self)
        if (self.unit_price is None) == (self.markup_pct is None):
            raise ValidationError('Set either a fixed unit price or a markup percentage (not both).')
        if self.item_id and self.client_org_id and not self.item.price_book.applies_to(self.client_org_id):
            raise ValidationError({'item': 'The item is in another customer\'s own price book.'})
        if self.contract_id and self.contract.client_org_id != self.client_org_id:
            raise ValidationError({'contract': 'The contract is with a different customer.'})

    def save(self, *args, **kwargs):
        changed_by = kwargs.pop('_changed_by', None)
        prior = None
        if self.pk:
            prior = CustomerPriceOverride.objects.filter(pk=self.pk).values('unit_price', 'markup_pct').first()
        super().save(*args, **kwargs)
        for f in ('unit_price', 'markup_pct'):
            old = prior[f] if prior else None
            if _dec(old) != _dec(getattr(self, f)):
                PriceChangeHistory.record(self, f, old, getattr(self, f), changed_by=changed_by,
                                          source='override')


class ScheduledPriceChange(models.Model):
    """A future change to a price book item field.

    `apply_due()` writes the new value onto the item (recording history) on
    or after `effective_date`. It never touches prices already copied onto
    quotes, invoices, contracts or time entries; those keep their snapshots.
    Until applied, `pricing.services.resolve_price` already uses the new
    value for dates on or after `effective_date`."""
    FIELDS = [('default_price', 'Sell price'), ('cost', 'Cost'), ('minimum_price', 'Minimum price')]
    item = models.ForeignKey(PriceBookItem, on_delete=models.CASCADE, related_name='scheduled_changes')
    field = models.CharField(max_length=30, choices=FIELDS, default='default_price')
    new_value = _money()
    effective_date = models.DateField()
    applied_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pricing_scheduled_changes'
        ordering = ['effective_date', 'pk']
        indexes = [models.Index(fields=['applied_at', 'effective_date'])]

    def __str__(self):
        return f'{self.item.sku}.{self.field} → {self.new_value} on {self.effective_date}'

    @property
    def is_pending(self):
        return self.applied_at is None and self.cancelled_at is None

    @classmethod
    def pending(cls):
        return cls.objects.filter(applied_at__isnull=True, cancelled_at__isnull=True)

    def apply(self, user=None):
        if not self.is_pending:
            return False
        with transaction.atomic():
            item = PriceBookItem.objects.select_for_update().get(pk=self.item_id)
            setattr(item, self.field, self.new_value)
            item.save(_changed_by=user or self.created_by, _history_source='scheduled',
                      _history_note=f'Scheduled change #{self.pk}')
            self.applied_at = timezone.now()
            self.save(update_fields=['applied_at'])
        return True

    @classmethod
    def apply_due(cls, on_date=None, organization=None):
        """Apply every pending change due on or before `on_date`. Returns the count."""
        on_date = on_date or timezone.localdate()
        qs = cls.pending().filter(effective_date__lte=on_date).order_by('effective_date', 'pk')
        if organization is not None:
            qs = qs.filter(item__price_book__organization=organization)
        return sum(1 for c in qs if c.apply())


class PriceChangeHistory(models.Model):
    """Append-only record of price changes (items, overrides, rate card lines,
    service plans). Rows cannot be edited or deleted through the ORM."""
    # The customer the changed price applies to; NULL = install-wide.
    organization = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='+')
    object_type = models.CharField(max_length=60)
    object_id = models.PositiveBigIntegerField()
    object_repr = models.CharField(max_length=255, blank=True)
    price_book_item = models.ForeignKey(PriceBookItem, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='price_history')
    field = models.CharField(max_length=60)
    old_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    new_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    changed_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    changed_by_username = models.CharField(max_length=150, blank=True)
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)
    source = models.CharField(max_length=30, blank=True,
                              help_text='edit / admin / scheduled / override / rate_card / plan / duplicate')
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'pricing_price_change_history'
        ordering = ['-changed_at', '-pk']
        indexes = [models.Index(fields=['object_type', 'object_id'])]

    def __str__(self):
        return f'{self.object_type}#{self.object_id}.{self.field}: {self.old_value} → {self.new_value}'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError('Price change history is append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Price change history is append-only.')

    @classmethod
    def record(cls, obj, field, old, new, changed_by=None, source='', note=''):
        org_id = getattr(obj, 'organization_id', None)
        item = obj if isinstance(obj, PriceBookItem) else getattr(obj, 'item', None)
        if not isinstance(item, PriceBookItem):
            item = None
        return cls.objects.create(
            organization_id=org_id, object_type=obj._meta.label_lower, object_id=obj.pk,
            object_repr=str(obj)[:255], price_book_item=item, field=field,
            old_value=_dec(old), new_value=_dec(new), changed_by=changed_by,
            changed_by_username=getattr(changed_by, 'username', '') or '', source=source,
            note=(note or '')[:300])


# ---------------------------------------------------------------------------
# Service plans
# ---------------------------------------------------------------------------

class ServicePlan(models.Model):
    """A sellable managed-service plan (e.g. "Essentials", "Complete") or add-on."""
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='service_plans',
        help_text=OWNER_HELP)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=60, blank=True)
    description = models.TextField(blank=True)
    is_addon = models.BooleanField(default=False,
                                   help_text='An add-on sold on top of a primary plan.')
    is_active = models.BooleanField(default=True)
    currency = models.CharField(max_length=3, default='USD', help_text=CURRENCY_HELP)

    monthly_price = _money(null=True, blank=True)
    annual_price = _money(null=True, blank=True)
    per_user_price = _money(null=True, blank=True)
    per_device_price = _money(null=True, blank=True)
    per_server_price = _money(null=True, blank=True)
    minimum_monthly_charge = _money(null=True, blank=True)
    minimum_users = models.PositiveIntegerField(null=True, blank=True)
    minimum_devices = models.PositiveIntegerField(null=True, blank=True)
    minimum_servers = models.PositiveIntegerField(null=True, blank=True)
    included_support_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                                 help_text='Per month. Blank = none / not hour-based.')
    # There is no SLA model in this codebase; contracts carry the same JSON
    # shape (`psa.Contract.sla_matrix`), so a plan's SLA copies onto them.
    sla_matrix = models.JSONField(default=dict, blank=True,
                                  help_text='Same shape as psa.Contract.sla_matrix, '
                                            'e.g. {"p1": {"response_minutes": 15}}.')
    contract_term_months = models.PositiveSmallIntegerField(null=True, blank=True)
    renewal_terms = models.TextField(blank=True)
    auto_renew = models.BooleanField(default=False)
    onboarding_fee = _money(null=True, blank=True)
    offboarding_fee = _money(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    PRICE_FIELDS = ('monthly_price', 'annual_price', 'per_user_price', 'per_device_price',
                    'per_server_price', 'minimum_monthly_charge', 'onboarding_fee', 'offboarding_fee')

    class Meta:
        db_table = 'pricing_service_plans'
        ordering = ['organization_id', 'is_addon', 'name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='pricing_plan_unique_name'),
            models.UniqueConstraint(fields=['name'], condition=models.Q(organization__isnull=True),
                                    name='pricing_plan_unique_name_install'),
        ]

    def applies_to(self, client_org):
        return self.organization_id is None or (
            client_org is not None and self.organization_id == getattr(client_org, 'pk', client_org))

    def __str__(self):
        return f'{self.name}{" (add-on)" if self.is_addon else ""}'

    def save(self, *args, **kwargs):
        changed_by = kwargs.pop('_changed_by', None)
        prior = ServicePlan.objects.filter(pk=self.pk).values(*self.PRICE_FIELDS).first() if self.pk else None
        super().save(*args, **kwargs)
        if prior is None:
            return
        for f in self.PRICE_FIELDS:
            if _dec(prior[f]) != _dec(getattr(self, f)):
                PriceChangeHistory.record(self, f, prior[f], getattr(self, f), changed_by=changed_by,
                                          source='plan')


class ServicePlanItem(models.Model):
    """A price book item that a plan contains (included) or offers (optional)."""
    plan = models.ForeignKey(ServicePlan, on_delete=models.CASCADE, related_name='plan_items')
    item = models.ForeignKey(PriceBookItem, on_delete=models.PROTECT, related_name='plan_memberships')
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1'))
    is_included = models.BooleanField(default=True,
                                      help_text='Included in the plan price; otherwise an optional extra.')
    per_unit_of_plan = models.BooleanField(default=False,
                                           help_text='Quantity is per covered user / device (not per plan).')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pricing_service_plan_items'
        ordering = ['plan_id', 'sort_order', 'pk']
        constraints = [models.UniqueConstraint(fields=['plan', 'item'], name='pricing_plan_item_once')]

    def __str__(self):
        return f'{self.plan}: {self.item.sku} × {self.quantity}'

    def clean(self):
        if self.plan_id and self.item_id:
            book_org = self.item.price_book.organization_id
            if book_org is not None and book_org != self.plan.organization_id:
                raise ValidationError({'item': 'The item is in another customer\'s own price book.'})


class ServicePlanEntitlement(models.Model):
    """A named contractual entitlement of a service plan, e.g. "24x7 P1
    response", "Quarterly business review", "Up to 4 onsite visits / month".

    This is NOT a permission. It grants no access to anything in the
    application and is never consulted by authorization checks; it records
    what the customer is entitled to receive under the plan, for quotes,
    agreements and service delivery. Permissions live in accounts.RoleTemplate
    (accounts.permission_registry)."""
    UNITS = [('', '—'), ('hours', 'Hours'), ('visits', 'Visits'), ('incidents', 'Incidents'),
             ('users', 'Users'), ('devices', 'Devices'), ('gb', 'GB'), ('count', 'Count')]
    PERIODS = [('', '—'), ('month', 'Per month'), ('quarter', 'Per quarter'), ('year', 'Per year'),
               ('term', 'Per contract term')]
    plan = models.ForeignKey(ServicePlan, on_delete=models.CASCADE, related_name='entitlements')
    key = models.SlugField(max_length=80, help_text='Stable identifier, e.g. "onsite_visits".')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                   help_text='Blank = unlimited / not quantified.')
    unit = models.CharField(max_length=20, choices=UNITS, blank=True, default='')
    period = models.CharField(max_length=20, choices=PERIODS, blank=True, default='')
    customer_visible = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pricing_service_plan_entitlements'
        ordering = ['plan_id', 'sort_order', 'pk']
        constraints = [models.UniqueConstraint(fields=['plan', 'key'], name='pricing_entitlement_unique_key')]

    def __str__(self):
        return f'{self.plan}: {self.name}'


class ClientServicePlan(models.Model):
    """A customer's subscription to a plan. One live primary plan per
    customer (status pending / active); any number of add-ons."""
    ROLE_PRIMARY, ROLE_ADDON = 'primary', 'addon'
    ROLES = [(ROLE_PRIMARY, 'Primary plan'), (ROLE_ADDON, 'Add-on')]
    STATUSES = [('pending', 'Pending'), ('active', 'Active'), ('suspended', 'Suspended'),
                ('ended', 'Ended'), ('cancelled', 'Cancelled')]
    LIVE_STATUSES = ('pending', 'active')

    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                   related_name='client_service_plans')
    plan = models.ForeignKey(ServicePlan, on_delete=models.PROTECT, related_name='subscriptions')
    role = models.CharField(max_length=10, choices=ROLES, default=ROLE_PRIMARY)
    location = models.ForeignKey('locations.Location', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='service_plans')
    contract = models.ForeignKey('psa.Contract', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='service_plans')
    users = models.PositiveIntegerField(null=True, blank=True)
    devices = models.PositiveIntegerField(null=True, blank=True)
    servers = models.PositiveIntegerField(null=True, blank=True)
    sites = models.PositiveIntegerField(null=True, blank=True)
    # Negotiated prices; blank = the plan's price.
    monthly_price = _money(null=True, blank=True)
    per_user_price = _money(null=True, blank=True)
    per_device_price = _money(null=True, blank=True)
    per_server_price = _money(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default='pending')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing_client_service_plans'
        ordering = ['client_org_id', 'role', '-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['client_org'],
                condition=models.Q(role='primary', status__in=['pending', 'active']),
                name='pricing_one_live_primary_plan_per_client'),
        ]

    def __str__(self):
        return f'{self.client_org} · {self.plan}'

    def clean(self):
        _check_window(self, 'start_date', 'end_date')
        if self.plan_id:
            if not self.plan.applies_to(self.client_org_id):
                raise ValidationError({'plan': 'The plan is another customer\'s own plan.'})
            if self.plan.is_addon and self.role == self.ROLE_PRIMARY:
                raise ValidationError({'role': 'An add-on plan cannot be the primary plan.'})
            if not self.plan.is_addon and self.role == self.ROLE_ADDON:
                raise ValidationError({'role': 'A primary plan cannot be attached as an add-on.'})
        if self.contract_id and self.contract.client_org_id != self.client_org_id:
            raise ValidationError({'contract': 'The contract is with a different customer.'})

    @property
    def organization_id(self):
        return self.client_org_id

    def effective(self, field):
        """Negotiated value when set, else the plan's."""
        own = getattr(self, field, None)
        return own if own is not None else getattr(self.plan, field, None)


# ---------------------------------------------------------------------------
# Labor rates
# ---------------------------------------------------------------------------

class LaborRole(models.Model):
    """A billable labor role (e.g. "Help desk", "Senior engineer"). `code`
    matches `psa.TicketTimeEntry.role_code` so existing tagged time maps on."""
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='labor_roles',
        help_text=OWNER_HELP)
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40, help_text='Matches TicketTimeEntry.role_code, e.g. "T1".')
    description = models.TextField(blank=True)
    default_bill_rate = _money(
        null=True, blank=True,
        help_text='Explicitly configured fallback hourly rate, used only when no rate card applies. '
                  'Blank = none (the time is flagged rate-missing).')
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pricing_labor_roles'
        ordering = ['organization_id', 'sort_order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'code'], name='pricing_role_unique_code'),
            models.UniqueConstraint(fields=['code'], condition=models.Q(organization__isnull=True),
                                    name='pricing_role_unique_code_install'),
        ]

    def applies_to(self, client_org):
        return self.organization_id is None or (
            client_org is not None and self.organization_id == getattr(client_org, 'pk', client_org))

    def __str__(self):
        return self.name


class RateCard(models.Model):
    """Hourly labor rates. Scope is derived from what is set:

        client_org + contract  -> customer + contract (most specific)
        client_org only        -> customer
        contract only          -> contract
        neither                -> MSP-wide default
    """
    SCOPE_CUSTOMER_CONTRACT = 'customer_contract'
    SCOPE_CUSTOMER = 'customer'
    SCOPE_CONTRACT = 'contract'
    SCOPE_DEFAULT = 'default'
    SCOPES = [(SCOPE_CUSTOMER_CONTRACT, 'Customer + contract'), (SCOPE_CUSTOMER, 'Customer'),
              (SCOPE_CONTRACT, 'Contract'), (SCOPE_DEFAULT, 'MSP-wide default')]

    name = models.CharField(max_length=200)
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='customer_rate_cards')
    contract = models.ForeignKey('psa.Contract', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='rate_cards')
    scope = models.CharField(max_length=20, choices=SCOPES, editable=False, default=SCOPE_DEFAULT)
    currency = models.CharField(max_length=3, default='USD', help_text=CURRENCY_HELP)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing_rate_cards'
        ordering = ['scope', '-effective_from', 'name']
        indexes = [models.Index(fields=['scope', 'is_active'])]

    @property
    def organization_id(self):
        """The customer this card is scoped to (its contract's customer for a
        contract-only card); None for the MSP-wide default."""
        if self.client_org_id:
            return self.client_org_id
        if self.contract_id:
            return self.contract.client_org_id
        return None

    def __str__(self):
        return f'{self.name} [{self.get_scope_display()}]'

    def compute_scope(self):
        if self.client_org_id and self.contract_id:
            return self.SCOPE_CUSTOMER_CONTRACT
        if self.client_org_id:
            return self.SCOPE_CUSTOMER
        if self.contract_id:
            return self.SCOPE_CONTRACT
        return self.SCOPE_DEFAULT

    def clean(self):
        _check_window(self)
        if self.contract_id and self.client_org_id and self.contract.client_org_id != self.client_org_id:
            raise ValidationError({'contract': 'The contract is with a different customer.'})

    def save(self, *args, **kwargs):
        self.scope = self.compute_scope()
        super().save(*args, **kwargs)


class RateCardLine(models.Model):
    RATE_TYPES = [
        ('standard', 'Standard'),
        ('after_hours', 'After hours'),
        ('weekend', 'Weekend'),
        ('holiday', 'Holiday'),
        ('emergency', 'Emergency'),
        ('onsite', 'Onsite'),
        ('remote', 'Remote'),
        ('travel', 'Travel'),
        ('project', 'Project'),
        ('consulting', 'Consulting'),
        ('fixed', 'Fixed'),
        ('minimum_charge', 'Minimum charge'),
    ]
    QUALIFIERS = ('technician_id', 'skill', 'service_category', 'location_id')

    rate_card = models.ForeignKey(RateCard, on_delete=models.CASCADE, related_name='lines')
    role = models.ForeignKey(LaborRole, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='rate_lines', help_text='Blank = applies to any role.')
    rate_type = models.CharField(max_length=20, choices=RATE_TYPES, default='standard')
    hourly_rate = _money()
    # Optional qualifiers: a line with a qualifier set applies only when it
    # matches; the most specific matching line wins.
    technician = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   null=True, blank=True, related_name='+')
    skill = models.CharField(max_length=100, blank=True,
                             help_text='Matches resourcing.UserSkill.name of the technician.')
    service_category = models.CharField(max_length=100, blank=True)
    location = models.ForeignKey('locations.Location', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='+')
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'pricing_rate_card_lines'
        ordering = ['rate_card_id', 'role_id', 'rate_type']

    def __str__(self):
        who = self.role.name if self.role_id else 'Any role'
        return f'{who} · {self.get_rate_type_display()}: {self.hourly_rate}/h'

    @property
    def organization_id(self):
        return self.rate_card.organization_id

    @property
    def specificity(self):
        return (2 if self.role_id else 0) + sum(1 for q in ('technician_id', 'skill', 'service_category',
                                                          'location_id') if getattr(self, q))

    def clean(self):
        if self.hourly_rate is not None and self.hourly_rate < 0:
            raise ValidationError({'hourly_rate': 'Must not be negative.'})
        if self.role_id and self.rate_card_id and self.role.organization_id is not None \
                and self.role.organization_id != self.rate_card.organization_id:
            raise ValidationError({'role': 'The role is another customer\'s own role.'})

    def save(self, *args, **kwargs):
        changed_by = kwargs.pop('_changed_by', None)
        prior = RateCardLine.objects.filter(pk=self.pk).values_list('hourly_rate', flat=True).first() \
            if self.pk else None
        super().save(*args, **kwargs)
        if prior is not None and _dec(prior) != _dec(self.hourly_rate):
            PriceChangeHistory.record(self, 'hourly_rate', prior, self.hourly_rate, changed_by=changed_by,
                                      source='rate_card')


class BillingRule(models.Model):
    """How labor time is rounded and what fees attach. Same scoping as
    RateCard (customer + contract > customer > contract > MSP-wide default);
    resolved by pricing.services.resolve_billing_rule."""
    ROUNDING = [('none', 'No rounding'), ('up', 'Round up'), ('nearest', 'Round to nearest'),
                ('down', 'Round down')]
    name = models.CharField(max_length=200)
    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='customer_billing_rules')
    contract = models.ForeignKey('psa.Contract', on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='billing_rules')
    minimum_billable_minutes = models.PositiveIntegerField(default=0)
    increment_minutes = models.PositiveIntegerField(default=1, help_text='Bill in blocks of N minutes.')
    rounding_mode = models.CharField(max_length=10, choices=ROUNDING, default='none')
    travel_fee = _money(null=True, blank=True)
    dispatch_fee = _money(null=True, blank=True)
    emergency_premium_pct = _pct(null=True, blank=True,
                                 help_text='Added to the rate for rate type "emergency" when the card '
                                           'has no emergency line. Blank = none.')
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pricing_billing_rules'
        ordering = ['name']

    @property
    def organization_id(self):
        if self.client_org_id:
            return self.client_org_id
        if self.contract_id:
            return self.contract.client_org_id
        return None

    def __str__(self):
        return self.name

    def clean(self):
        _check_window(self)
        if self.increment_minutes < 1:
            raise ValidationError({'increment_minutes': 'Must be at least 1 minute.'})

    def billable_minutes(self, minutes):
        """Apply minimum, then increment rounding, to `minutes` (int)."""
        m = max(int(minutes or 0), 0)
        if m == 0:
            return 0
        m = max(m, self.minimum_billable_minutes or 0)
        inc = max(self.increment_minutes or 1, 1)
        if inc > 1 and self.rounding_mode != 'none':
            q, r = divmod(m, inc)
            if r:
                if self.rounding_mode == 'up' or (self.rounding_mode == 'nearest' and r * 2 >= inc):
                    q += 1
                m = q * inc
        return m
