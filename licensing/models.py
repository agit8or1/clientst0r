"""Software licensing: what each customer has bought, what is assigned, and
when it renews.

A customer is a `core.Organization`. A `LicenseSubscription` is one
purchased entitlement (a Microsoft 365 SKU, a Pax8 subscription, or a manual
entry); `LicenseAssignment` rows say who holds a seat.

Counts (all computed, never stored):
  purchased      quantity_purchased
  assigned       assignment rows when there are any, otherwise the vendor's
                 own consumed-unit figure (Microsoft reports consumedUnits
                 even when per-user assignments are not synced)
  available      purchased - assigned, never below zero ("unused")
  over_allocated assigned - purchased, never below zero
  utilization    assigned / purchased, as a percentage

`unit_cost` is what the MSP pays the vendor. It is internal and must only be
shown to people holding the `view_internal_cost_rates` role permission; use
`LicenseSubscription.cost_for(can_see_cost)` or check the flag in the view.
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import BaseModel, Organization
from core.utils import OrganizationManager


class SoftwareProduct(BaseModel):
    """A vendor product / SKU. Shared catalog (names only, no customer data)."""
    TYPE_CHOICES = [
        ('subscription', 'Subscription'),
        ('perpetual', 'Perpetual'),
        ('per_user', 'Per user'),
        ('per_device', 'Per device'),
        ('concurrent', 'Concurrent'),
        ('site', 'Site'),
    ]
    vendor = models.CharField(max_length=120)
    name = models.CharField(max_length=255)
    vendor_sku = models.CharField(max_length=120, blank=True)
    license_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='subscription')

    class Meta:
        db_table = 'licensing_product'
        ordering = ['vendor', 'name']
        constraints = [
            models.UniqueConstraint(fields=['vendor', 'vendor_sku'], condition=~Q(vendor_sku=''),
                                    name='licensing_product_vendor_sku_uniq'),
        ]

    def __str__(self):
        return f'{self.vendor} {self.name}'.strip()


class LicenseSubscription(BaseModel):
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('m365', 'Microsoft 365'),
        ('pax8', 'Pax8'),
        ('google_workspace', 'Google Workspace'),
    ]
    BILLING_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annual', 'Annual'),
        ('biennial', '2-year'),
        ('triennial', '3-year'),
        ('one_time', 'One-time'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('trial', 'Trial'),
        ('pending', 'Pending'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    LIVE_STATUSES = ('active', 'trial')

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='license_subscriptions',
                                     help_text='The customer the licenses belong to.')
    product = models.ForeignKey(SoftwareProduct, on_delete=models.PROTECT, related_name='subscriptions')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    vendor_subscription_id = models.CharField(
        max_length=255, blank=True,
        help_text='The vendor\'s id for this subscription (unique per source and customer).')

    quantity_purchased = models.PositiveIntegerField(default=0)
    vendor_consumed = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Units the vendor reports as in use (e.g. Microsoft consumedUnits).")
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
        help_text='What the MSP pays per unit. Internal: requires view_internal_cost_rates.')
    unit_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True,
                                     help_text='What the customer pays per unit.')
    currency = models.CharField(max_length=3, default='USD')
    billing_frequency = models.CharField(max_length=12, choices=BILLING_CHOICES, default='monthly')

    term_start = models.DateField(null=True, blank=True)
    renewal_date = models.DateField(null=True, blank=True, db_index=True)
    auto_renew = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='active')

    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True)

    # Link to the pricing app's price book once it exists (a SKU string for
    # now; deliberately not a foreign key).
    price_book_item_ref = models.CharField(max_length=120, blank=True, null=True)
    notes = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'licensing_subscription'
        ordering = ['organization__name', 'product__vendor', 'product__name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'source', 'vendor_subscription_id'],
                                    condition=~Q(vendor_subscription_id=''),
                                    name='licensing_sub_vendor_id_uniq'),
        ]
        indexes = [models.Index(fields=['organization', 'status'])]

    def __str__(self):
        return f'{self.organization} / {self.product}'

    # ---- computed counts --------------------------------------------------

    def assignment_count(self):
        # uses the prefetch cache when present
        return len(self.assignments.all())

    @property
    def assigned(self):
        n = self.assignment_count()
        if n:
            return n
        return self.vendor_consumed or 0

    @property
    def available(self):
        return max(self.quantity_purchased - self.assigned, 0)

    unused = available

    @property
    def over_allocated(self):
        return max(self.assigned - self.quantity_purchased, 0)

    @property
    def utilization_pct(self):
        if not self.quantity_purchased:
            return None
        return round(self.assigned * 100.0 / self.quantity_purchased, 1)

    @property
    def has_usage_data(self):
        """True when assigned/unused figures mean something: assignments are
        tracked or the vendor reports consumption. A manual entry with
        neither would otherwise read as 100% unused."""
        return self.vendor_consumed is not None or self.assignment_count() > 0

    @property
    def is_live(self):
        return self.status in self.LIVE_STATUSES

    @property
    def days_to_renewal(self):
        if not self.renewal_date:
            return None
        return (self.renewal_date - timezone.localdate()).days

    @property
    def total_price(self):
        return None if self.unit_price is None else self.unit_price * self.quantity_purchased

    def cost_for(self, can_see_cost):
        """unit_cost, or None unless the viewer may see internal cost."""
        return self.unit_cost if can_see_cost else None


class LicenseAssignment(BaseModel):
    subscription = models.ForeignKey(LicenseSubscription, on_delete=models.CASCADE,
                                     related_name='assignments')
    assigned_to = models.CharField(max_length=255, help_text='Person, mailbox or device name / sign-in.')
    contact = models.ForeignKey('assets.Contact', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='license_assignments')
    asset = models.ForeignKey('assets.Asset', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='license_assignments')
    assigned_at = models.DateField(default=timezone.localdate)
    external_id = models.CharField(max_length=255, blank=True,
                                   help_text="The vendor's id for the assignee (e.g. Entra object id).")

    class Meta:
        db_table = 'licensing_assignment'
        ordering = ['assigned_to']
        constraints = [
            models.UniqueConstraint(fields=['subscription', 'external_id'],
                                    condition=~Q(external_id=''),
                                    name='licensing_assignment_external_uniq'),
        ]

    def __str__(self):
        return f'{self.assigned_to} -> {self.subscription_id}'


class ExternalCustomerMap(BaseModel):
    """Maps a vendor-side customer (a Pax8 company id) to a customer here.
    Subscriptions of an unmapped vendor customer are not imported."""
    source = models.CharField(max_length=20, choices=LicenseSubscription.SOURCE_CHOICES)
    external_id = models.CharField(max_length=255)
    external_name = models.CharField(max_length=255, blank=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='license_customer_maps')

    class Meta:
        db_table = 'licensing_customer_map'
        ordering = ['source', 'external_name']
        constraints = [
            models.UniqueConstraint(fields=['source', 'external_id'], name='licensing_map_uniq'),
        ]

    def __str__(self):
        return f'{self.source}:{self.external_id} -> {self.organization}'


class LicenseAlertLog(BaseModel):
    """One row per alert already raised, so a condition mails once.

    `key` encodes the condition (for renewals: the renewal date and the
    30/60/90 window), so a new term or a closer window alerts again."""
    KIND_CHOICES = [
        ('renewal', 'Renewal'),
        ('unused', 'Unused licenses'),
        ('over_allocated', 'Over-allocated'),
    ]
    subscription = models.ForeignKey(LicenseSubscription, on_delete=models.CASCADE,
                                     related_name='alert_log')
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    key = models.CharField(max_length=64)
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'licensing_alert_log'
        constraints = [
            models.UniqueConstraint(fields=['subscription', 'kind', 'key'], name='licensing_alert_uniq'),
        ]
