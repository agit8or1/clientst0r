"""
Inventory models - Spare parts, hardware, consumables, and stock management
"""
import uuid
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager


class InventoryCategory(BaseModel):
    """
    Category for grouping inventory items.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#6c757d', help_text='Hex color code, e.g. #ff0000')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='inventory_categories')

    objects = OrganizationManager()

    class Meta:
        db_table = 'inventory_categories'
        ordering = ['name']
        verbose_name = 'Inventory Category'
        verbose_name_plural = 'Inventory Categories'

    def __str__(self):
        return self.name


class InventoryLocation(BaseModel):
    """
    Physical storage location for inventory items.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='inventory_locations')

    objects = OrganizationManager()

    class Meta:
        db_table = 'inventory_locations'
        ordering = ['name']
        verbose_name = 'Inventory Location'
        verbose_name_plural = 'Inventory Locations'

    def __str__(self):
        return self.name


class InventoryItem(BaseModel):
    """
    An inventory item - spare part, hardware, consumable, tool, cable, license, or other.
    """
    ITEM_TYPES = [
        ('spare_part', 'Spare Part'),
        ('hardware', 'Hardware'),
        ('consumable', 'Consumable'),
        ('tool', 'Tool'),
        ('cable', 'Cable'),
        ('license', 'License'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, blank=True, help_text='Stock Keeping Unit / internal part number')
    manufacturer_part_number = models.CharField(max_length=100, blank=True)
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES, default='other')
    category = models.ForeignKey(
        InventoryCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='items'
    )
    storage_location = models.ForeignKey(
        InventoryLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='items'
    )
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Stock
    quantity = models.IntegerField(default=0)
    unit = models.CharField(max_length=50, blank=True, default='ea', help_text='Unit of measure (ea, box, pack, etc.)')
    min_quantity = models.IntegerField(default=0, help_text='Minimum stock level before reorder alert')
    reorder_quantity = models.IntegerField(default=0, help_text='Quantity to reorder when low')
    reorder_link = models.URLField(blank=True, help_text='URL to purchase / reorder this item')

    # Phase 4.3 — auto-replenish hints
    preferred_vendor = models.ForeignKey(
        'assets.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='preferred_inventory_items',
        help_text='Vendor to suggest in auto-replenish.',
    )
    last_replenished_at = models.DateTimeField(null=True, blank=True)

    # Cost
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # QR Code
    qr_code = models.CharField(max_length=50, unique=True, blank=True)

    # Tags
    tags = models.ManyToManyField(Tag, blank=True, related_name='inventory_items')

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='inventory_items')

    objects = OrganizationManager()

    class Meta:
        db_table = 'inventory_items'
        ordering = ['name']
        verbose_name = 'Inventory Item'
        verbose_name_plural = 'Inventory Items'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.qr_code:
            self.qr_code = 'INV-' + uuid.uuid4().hex[:12].upper()
        super().save(*args, **kwargs)

    @property
    def is_low_stock(self):
        """Returns True if quantity is at or below minimum."""
        return self.quantity <= self.min_quantity

    @property
    def total_value(self):
        """Returns total value of stock (quantity * unit_cost)."""
        if self.unit_cost is not None:
            return self.quantity * self.unit_cost
        return None


class InventoryTransaction(models.Model):
    """
    Record of stock changes for an inventory item.
    """
    TRANSACTION_TYPES = [
        ('stock_in', 'Stock In'),
        ('stock_out', 'Stock Out'),
        ('adjustment', 'Adjustment'),
        ('transfer', 'Transfer'),
    ]

    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity_change = models.IntegerField(help_text='Positive for additions, negative for removals')
    quantity_after = models.IntegerField(help_text='Stock quantity after this transaction')
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_transactions'
    )
    reference = models.CharField(max_length=255, blank=True, help_text='Reference number, ticket, PO, etc.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inventory_transactions'
        ordering = ['-created_at']
        verbose_name = 'Inventory Transaction'
        verbose_name_plural = 'Inventory Transactions'

    def __str__(self):
        return f"{self.item.name} {self.transaction_type} {self.quantity_change:+d}"


class Tool(BaseModel):
    """Phase 46 (v3.17.533): durable equipment a tech takes to a job.

    Deliberately separate from InventoryItem. A consumable is spent — you take
    eight patch cables and come back with none, and stock decrements. A tool
    goes out and comes back, and the question its record has to answer is
    "where is it and who has it", not "how many are left". Modelling both as
    stock rows would mean either lying about quantities or explaining why the
    cable tester's count never drops.
    """
    CONDITIONS = [
        ('good', 'Good'),
        ('needs_service', 'Needs service'),
        ('out_of_service', 'Out of service'),
        ('lost', 'Lost'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='tools')
    name = models.CharField(max_length=255)
    code = models.CharField(
        max_length=50, blank=True,
        help_text='Asset tag or internal identifier, e.g. TL-014.')
    category = models.ForeignKey(
        InventoryCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tools')
    description = models.TextField(blank=True)

    # Where it lives when nobody has it out. Either a shelf or a van; both are
    # optional because plenty of shops track neither.
    home_location = models.ForeignKey(
        InventoryLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tools')
    assigned_vehicle = models.ForeignKey(
        'vehicles.ServiceVehicle', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tools',
        help_text='Van this tool normally rides in, if any.')

    condition = models.CharField(max_length=20, choices=CONDITIONS, default='good')
    is_active = models.BooleanField(
        default=True,
        help_text='Uncheck to retire a tool without deleting its history.')
    notes = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'inventory_tools'
        ordering = ['name']
        constraints = [
            # A code is optional, but a used one must be unique per tenant —
            # two tools answering to TL-014 makes the tag useless.
            models.UniqueConstraint(
                fields=['organization', 'code'],
                condition=models.Q(code__gt=''),
                name='uniq_tool_code_per_org'),
        ]
        indexes = [models.Index(fields=['organization', 'is_active'])]

    def __str__(self):
        return f'{self.code} {self.name}'.strip() if self.code else self.name

    @property
    def is_available(self) -> bool:
        """Usable right now — retired and broken tools are not."""
        return self.is_active and self.condition in ('good', 'needs_service')

    @property
    def home(self) -> str:
        """Where to go looking for it, in one string."""
        if self.assigned_vehicle_id:
            # `display_name` is the van's nickname ("Van 3"); __str__ is the
            # year/make/model/plate, which is not how anyone refers to a van.
            return self.assigned_vehicle.display_name
        if self.home_location_id:
            return self.home_location.name
        return ''
