"""
Assets models - Devices, Contacts, and Relationships
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager


class Contact(BaseModel):
    """
    Contact/person associated with assets or organizations.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='contacts')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'contacts'
        ordering = ['last_name', 'first_name']
        indexes = [
            models.Index(fields=['organization', 'last_name']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Asset(BaseModel):
    """
    Asset/device with flexible JSON fields.
    """
    ASSET_TYPES = [
        ('server', 'Server'),
        ('workstation', 'Workstation'),
        ('laptop', 'Laptop'),
        ('network', 'Network Device'),
        ('printer', 'Printer'),
        ('phone', 'Phone'),
        ('mobile', 'Mobile Device'),
        ('other', 'Other'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='assets')
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=50, choices=ASSET_TYPES, default='other')
    asset_tag = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)
    manufacturer = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=255, blank=True)

    # Network fields
    hostname = models.CharField(max_length=255, blank=True, help_text='Network hostname/FQDN')
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text='IPv4 or IPv6 address')
    mac_address = models.CharField(max_length=17, blank=True, help_text='MAC address (e.g., 00:11:22:33:44:55)')

    # Flexible fields stored as JSON
    custom_fields = models.JSONField(default=dict, blank=True)

    # Relations
    tags = models.ManyToManyField(Tag, blank=True, related_name='assets')
    primary_contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name='primary_assets')

    # Metadata
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assets_created')

    objects = OrganizationManager()

    class Meta:
        db_table = 'assets'
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'name']),
            models.Index(fields=['asset_type']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_asset_type_display()})"


class Relationship(BaseModel):
    """
    Generic relationships between any objects (asset<->asset, asset<->doc, etc).
    """
    RELATION_TYPES = [
        ('related', 'Related To'),
        ('parent', 'Parent Of'),
        ('child', 'Child Of'),
        ('depends', 'Depends On'),
        ('documents', 'Documents'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='relationships')

    # Source object
    source_type = models.CharField(max_length=50)  # e.g., 'asset', 'document', 'password'
    source_id = models.PositiveIntegerField()

    # Target object
    target_type = models.CharField(max_length=50)
    target_id = models.PositiveIntegerField()

    relation_type = models.CharField(max_length=50, choices=RELATION_TYPES, default='related')
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'relationships'
        unique_together = [['source_type', 'source_id', 'target_type', 'target_id', 'relation_type']]
        indexes = [
            models.Index(fields=['organization', 'source_type', 'source_id']),
            models.Index(fields=['organization', 'target_type', 'target_id']),
        ]

    def __str__(self):
        return f"{self.source_type}:{self.source_id} {self.relation_type} {self.target_type}:{self.target_id}"
"""
Flexible Asset Type System - Customizable asset tracking engine
Allows users to define their own asset types with custom fields
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel


class AssetType(BaseModel):
    """
    Defines a custom asset type with configurable fields.
    Examples: Servers, Workstations, Network Devices, Software Licenses, Vehicles, etc.
    """
    ICON_CHOICES = [
        ('fa-server', 'Server'),
        ('fa-desktop', 'Desktop'),
        ('fa-laptop', 'Laptop'),
        ('fa-network-wired', 'Network'),
        ('fa-mobile-alt', 'Mobile'),
        ('fa-database', 'Database'),
        ('fa-cloud', 'Cloud'),
        ('fa-key', 'License'),
        ('fa-hdd', 'Storage'),
        ('fa-print', 'Printer'),
        ('fa-phone', 'Phone'),
        ('fa-car', 'Vehicle'),
        ('fa-building', 'Building'),
        ('fa-plug', 'Equipment'),
        ('fa-box', 'Generic'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='asset_types')
    name = models.CharField(max_length=100, help_text="e.g., Server, Workstation, Network Device")
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, choices=ICON_CHOICES, default='fa-box')
    color = models.CharField(max_length=7, default='#0d6efd', help_text="Hex color for UI display")

    # Behavior flags
    is_active = models.BooleanField(default=True)
    show_in_menu = models.BooleanField(default=True)

    # Auto-numbering for assets of this type
    auto_number_prefix = models.CharField(max_length=20, blank=True, help_text="e.g., SRV-, WKS-")
    auto_number_next = models.PositiveIntegerField(default=1)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='asset_types_created')

    class Meta:
        db_table = 'asset_types'
        unique_together = [['organization', 'slug']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name}"

    def get_next_asset_number(self):
        """Generate next auto-numbered asset name."""
        if self.auto_number_prefix:
            number = f"{self.auto_number_prefix}{self.auto_number_next:04d}"
            self.auto_number_next += 1
            self.save(update_fields=['auto_number_next'])
            return number
        return None


class AssetTypeField(BaseModel):
    """
    Defines a custom field for an asset type.
    Supports various field types: text, number, date, dropdown, checkbox, etc.
    """
    FIELD_TYPES = [
        ('text', 'Text'),
        ('textarea', 'Textarea'),
        ('number', 'Number'),
        ('decimal', 'Decimal'),
        ('date', 'Date'),
        ('datetime', 'DateTime'),
        ('checkbox', 'Checkbox'),
        ('dropdown', 'Dropdown'),
        ('url', 'URL'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('ip_address', 'IP Address'),
        ('mac_address', 'MAC Address'),
    ]

    asset_type = models.ForeignKey(AssetType, on_delete=models.CASCADE, related_name='fields')
    name = models.CharField(max_length=100, help_text="Field label")
    slug = models.SlugField(max_length=100, help_text="Internal field name")
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default='text')
    help_text = models.CharField(max_length=255, blank=True)

    # Field configuration
    is_required = models.BooleanField(default=False)
    show_in_list = models.BooleanField(default=True, help_text="Show in asset list view")
    order = models.PositiveIntegerField(default=0, help_text="Display order")

    # For dropdown fields
    dropdown_options = models.JSONField(default=list, blank=True, help_text="List of options for dropdown fields")

    # Validation
    min_value = models.FloatField(null=True, blank=True, help_text="For number/decimal fields")
    max_value = models.FloatField(null=True, blank=True, help_text="For number/decimal fields")
    regex_pattern = models.CharField(max_length=255, blank=True, help_text="Regex validation pattern")

    class Meta:
        db_table = 'asset_type_fields'
        unique_together = [['asset_type', 'slug']]
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.asset_type.name}.{self.name}"


class FlexibleAsset(BaseModel):
    """
    A flexible asset instance based on an AssetType.
    Stores custom field values in JSON.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='flexible_assets')
    asset_type = models.ForeignKey(AssetType, on_delete=models.CASCADE, related_name='assets')

    # Core fields (always present)
    name = models.CharField(max_length=255)
    asset_number = models.CharField(max_length=100, blank=True, help_text="Auto-generated or manual")

    # Custom field values stored as JSON
    # Format: {"field_slug": "value", "hostname": "server01", "ip_address": "192.168.1.10"}
    field_values = models.JSONField(default=dict)

    # Common metadata
    tags = models.ManyToManyField(Tag, blank=True, related_name='flexible_assets')
    notes = models.TextField(blank=True)

    # Ownership/tracking
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='flexible_assets_created')
    last_modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='flexible_assets_modified')

    # Status
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'flexible_assets'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'asset_type']),
            models.Index(fields=['asset_number']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        if self.asset_number:
            return f"{self.asset_number}: {self.name}"
        return self.name

    def get_field_value(self, field_slug, default=None):
        """Get value for a specific custom field."""
        return self.field_values.get(field_slug, default)

    def set_field_value(self, field_slug, value):
        """Set value for a specific custom field."""
        self.field_values[field_slug] = value

    def get_all_fields_with_values(self):
        """
        Get all field definitions with their current values.
        Returns list of dicts with field metadata and values.
        """
        fields = []
        for field in self.asset_type.fields.all():
            fields.append({
                'field': field,
                'value': self.get_field_value(field.slug),
            })
        return fields
