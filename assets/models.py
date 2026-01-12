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
    ASSET_TYPES = sorted([
        ('access_control', 'Access Control System'),
        ('appliance', 'Appliance'),
        ('av_receiver', 'AV Receiver'),
        ('backup_appliance', 'Backup Appliance'),
        ('badge_printer', 'Badge Printer'),
        ('biometric_scanner', 'Biometric Scanner'),
        ('bridge', 'Network Bridge'),
        ('card_reader', 'Card Reader'),
        ('conference_phone', 'Conference Phone'),
        ('console_server', 'Console Server'),
        ('copier', 'Copier/MFP'),
        ('desktop', 'Desktop Computer'),
        ('digital_signage', 'Digital Signage'),
        ('display', 'Display/Monitor'),
        ('door_controller', 'Door Controller'),
        ('dvr', 'Digital Video Recorder (DVR)'),
        ('environmental_monitor', 'Environmental Monitor'),
        ('fiber_panel', 'Fiber Patch Panel'),
        ('firewall', 'Firewall'),
        ('gateway', 'Gateway'),
        ('generator', 'Generator'),
        ('handheld', 'Handheld Scanner/Device'),
        ('hvac', 'HVAC System'),
        ('iot_device', 'IoT Device'),
        ('kvm', 'KVM Switch'),
        ('label_printer', 'Label Printer'),
        ('laptop', 'Laptop'),
        ('lighting_control', 'Lighting Control'),
        ('load_balancer', 'Load Balancer'),
        ('mobile', 'Mobile Device'),
        ('modem', 'Modem'),
        ('nas', 'Network Attached Storage (NAS)'),
        ('nvr', 'Network Video Recorder (NVR)'),
        ('other', 'Other'),
        ('paging_system', 'Paging System'),
        ('patch_panel', 'Patch Panel'),
        ('pbx', 'PBX System'),
        ('pda', 'PDA'),
        ('pdu', 'Power Distribution Unit (PDU)'),
        ('phone', 'IP Phone'),
        ('plotter', 'Plotter'),
        ('printer', 'Printer'),
        ('projector', 'Projector'),
        ('rack', 'Server Rack/Cabinet'),
        ('router', 'Router'),
        ('san', 'Storage Area Network (SAN)'),
        ('scanner', 'Scanner'),
        ('security_camera', 'Security Camera'),
        ('sensor', 'Sensor'),
        ('server', 'Server'),
        ('switch', 'Network Switch'),
        ('tablet', 'Tablet'),
        ('tape_drive', 'Tape Drive/Library'),
        ('terminal', 'Terminal'),
        ('thermostat', 'Smart Thermostat'),
        ('thin_client', 'Thin Client'),
        ('ups', 'UPS (Uninterruptible Power Supply)'),
        ('video_conferencing', 'Video Conferencing System'),
        ('voip_gateway', 'VoIP Gateway'),
        ('wireless_ap', 'Wireless Access Point'),
        ('wireless_controller', 'Wireless Controller'),
        ('workstation', 'Workstation'),
    ], key=lambda x: x[1])

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='assets')
    name = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=50, choices=ASSET_TYPES, default='other')
    asset_tag = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)

    # Equipment model from vendor database (optional, auto-fills fields below)
    equipment_model = models.ForeignKey(
        'EquipmentModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assets',
        help_text="Select equipment model from vendor database (auto-fills manufacturer/model)"
    )

    # Keep existing fields for backward compatibility
    manufacturer = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=255, blank=True)

    # Network fields
    hostname = models.CharField(max_length=255, blank=True, help_text='Network hostname/FQDN')
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text='IPv4 or IPv6 address')
    mac_address = models.CharField(max_length=17, blank=True, help_text='MAC address (e.g., 00:11:22:33:44:55)')

    # Rackmount fields
    is_rackmount = models.BooleanField(default=False, help_text='Is this asset rackmountable?')
    rack_units = models.PositiveIntegerField(null=True, blank=True, help_text='Height in rack units (U)')

    # Port configuration (for switches, routers, firewalls, patch panels)
    port_count = models.PositiveIntegerField(null=True, blank=True, help_text='Number of ports')
    ports = models.JSONField(default=list, blank=True, help_text='Port configuration data')
    vlans = models.JSONField(default=list, blank=True, help_text='VLAN configuration data')

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

    def save(self, *args, **kwargs):
        """Auto-populate manufacturer/model from equipment_model if set."""
        if self.equipment_model:
            # Auto-fill from equipment model
            self.manufacturer = self.equipment_model.vendor.name
            self.model = self.equipment_model.model_name

            # Auto-fill rack info if available
            if self.equipment_model.is_rackmount:
                self.is_rackmount = True
                if self.equipment_model.rack_units:
                    self.rack_units = self.equipment_model.rack_units

        super().save(*args, **kwargs)

    def get_equipment_specs(self):
        """Get equipment specifications from linked model."""
        if self.equipment_model:
            return self.equipment_model.specifications
        return {}

    def get_equipment_image(self):
        """Get equipment image from linked model."""
        if self.equipment_model:
            return self.equipment_model.get_primary_image()
        return None

    def has_ports(self):
        """Check if this asset type supports ports."""
        return self.asset_type in [
            'switch', 'router', 'firewall', 'load_balancer',
            'wireless_controller', 'patch_panel', 'fiber_panel',
            'wireless_ap', 'gateway', 'bridge', 'pbx'
        ]

    def get_port_count(self):
        """Get total number of ports."""
        if not self.ports:
            return 0
        return len(self.ports)

    def get_active_port_count(self):
        """Get number of active/enabled ports."""
        if not self.ports:
            return 0
        return len([p for p in self.ports if p.get('status') in ['active', 'in-use']])

    def get_ports_by_vlan(self, vlan_id):
        """Get all ports assigned to a specific VLAN."""
        if not self.ports:
            return []
        return [p for p in self.ports if p.get('vlan') == vlan_id]

    def initialize_ports(self, count, port_type='switch'):
        """Initialize port configuration based on asset type."""
        self.port_count = count
        self.ports = []

        if port_type in ['patch_panel', 'fiber_panel']:
            # Patch panel ports
            for i in range(1, count + 1):
                self.ports.append({
                    'port_number': i,
                    'label': f'Port {i}',
                    'destination': '',
                    'cable_type': 'Cat6',
                    'notes': '',
                    'status': 'available'
                })
        else:
            # Network equipment ports
            for i in range(1, count + 1):
                self.ports.append({
                    'port_number': i,
                    'description': f'Port {i}',
                    'type': 'access',
                    'vlan': '',
                    'speed': '',
                    'status': 'inactive'
                })


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


# ============================================================================
# Hardware Vendor & Equipment Database
# ============================================================================

class Vendor(BaseModel):
    """
    Hardware vendor/manufacturer (Dell, HP, Cisco, etc).
    Global model - shared across all organizations.
    """
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Vendor name (e.g., Dell, HP, Cisco)"
    )

    slug = models.SlugField(
        max_length=200,
        unique=True,
        help_text="URL-safe identifier"
    )

    website = models.URLField(
        blank=True,
        help_text="Vendor website URL"
    )

    support_url = models.URLField(
        blank=True,
        help_text="Vendor support/documentation URL"
    )

    support_phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Vendor support phone number"
    )

    description = models.TextField(
        blank=True,
        help_text="Brief description of vendor"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether vendor is actively used"
    )

    custom_fields = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional vendor metadata"
    )

    class Meta:
        db_table = 'vendors'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name

    def get_logo_attachment(self):
        """Get vendor logo from Attachment model."""
        from files.models import Attachment
        return Attachment.objects.filter(
            entity_type='vendor',
            entity_id=self.id
        ).first()


class EquipmentModel(BaseModel):
    """
    Specific equipment model from a vendor (e.g., Dell PowerEdge R740).
    Global model - shared across all organizations.
    """
    EQUIPMENT_TYPES = [
        ('server', 'Server'),
        ('workstation', 'Workstation'),
        ('laptop', 'Laptop'),
        ('switch', 'Network Switch'),
        ('router', 'Router'),
        ('firewall', 'Firewall'),
        ('access_point', 'Wireless Access Point'),
        ('storage', 'Storage Device'),
        ('ups', 'UPS'),
        ('pdu', 'Power Distribution Unit'),
        ('patch_panel', 'Patch Panel'),
        ('kvm', 'KVM Switch'),
        ('phone', 'IP Phone'),
        ('camera', 'IP Camera'),
        ('other', 'Other'),
    ]

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name='equipment_models',
        help_text="Equipment manufacturer"
    )

    model_name = models.CharField(
        max_length=200,
        help_text="Marketing/display name (e.g., PowerEdge R740)"
    )

    model_number = models.CharField(
        max_length=200,
        blank=True,
        help_text="Specific model/part number (e.g., R740XD)"
    )

    slug = models.SlugField(
        max_length=250,
        unique=True,
        help_text="URL-safe identifier"
    )

    equipment_type = models.CharField(
        max_length=50,
        choices=EQUIPMENT_TYPES,
        help_text="Type of equipment"
    )

    description = models.TextField(
        blank=True,
        help_text="Equipment description"
    )

    # Rack mounting
    is_rackmount = models.BooleanField(
        default=False,
        help_text="Whether equipment is rackmountable"
    )

    rack_units = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Height in rack units (1U, 2U, etc.)"
    )

    # Physical specifications (JSONField for flexibility)
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="""Equipment specifications in JSON format"""
    )

    # Data sheet and documentation
    datasheet_url = models.URLField(
        blank=True,
        help_text="Link to vendor datasheet/spec sheet"
    )

    documentation_url = models.URLField(
        blank=True,
        help_text="Link to user manual/documentation"
    )

    # EOL tracking
    release_date = models.DateField(
        null=True,
        blank=True,
        help_text="Product release date"
    )

    eol_date = models.DateField(
        null=True,
        blank=True,
        help_text="End of life date"
    )

    eos_date = models.DateField(
        null=True,
        blank=True,
        help_text="End of support date"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether model is actively used/sold"
    )

    custom_fields = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional model-specific metadata"
    )

    class Meta:
        db_table = 'equipment_models'
        ordering = ['vendor__name', 'model_name']
        unique_together = [['vendor', 'model_name']]
        indexes = [
            models.Index(fields=['vendor', 'model_name']),
            models.Index(fields=['equipment_type']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.vendor.name} {self.model_name}"

    def get_display_name(self):
        """Full display name with vendor."""
        return str(self)

    def get_images(self):
        """Get all product images."""
        from files.models import Attachment
        return Attachment.objects.filter(
            entity_type='equipment_model',
            entity_id=self.id
        ).order_by('created_at')

    def get_primary_image(self):
        """Get first/primary product image."""
        return self.get_images().first()

    def has_port_configuration(self):
        """Check if equipment has port configuration."""
        return self.equipment_type in ['switch', 'router', 'firewall', 'patch_panel']


class NetworkPortConfiguration(BaseModel):
    """
    Port configuration for switches, routers, firewalls.
    Organization-scoped - can be customized per organization.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        help_text="Organization this configuration belongs to"
    )

    equipment_model = models.ForeignKey(
        EquipmentModel,
        on_delete=models.CASCADE,
        related_name='port_configurations',
        help_text="Equipment model this configuration is for"
    )

    # Can also be linked to specific asset instance
    asset = models.ForeignKey(
        'Asset',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='port_configurations',
        help_text="Specific asset instance (optional)"
    )

    configuration_name = models.CharField(
        max_length=200,
        help_text="Configuration name (e.g., 'Default', 'Production VLAN Setup')"
    )

    # Port definitions stored as JSON
    ports = models.JSONField(
        default=list,
        help_text="Port configuration array"
    )

    # VLAN definitions
    vlans = models.JSONField(
        default=list,
        blank=True,
        help_text="VLAN definitions"
    )

    notes = models.TextField(
        blank=True,
        help_text="Configuration notes"
    )

    is_template = models.BooleanField(
        default=False,
        help_text="Whether this is a template configuration"
    )

    objects = OrganizationManager()

    class Meta:
        db_table = 'network_port_configurations'
        ordering = ['equipment_model', 'configuration_name']
        indexes = [
            models.Index(fields=['equipment_model']),
            models.Index(fields=['asset']),
            models.Index(fields=['is_template']),
        ]

    def __str__(self):
        if self.asset:
            return f"{self.asset.name} - {self.configuration_name}"
        return f"{self.equipment_model} - {self.configuration_name}"

    def get_port_count(self):
        """Get total number of ports."""
        return len(self.ports)

    def get_active_port_count(self):
        """Get number of active/enabled ports."""
        return len([p for p in self.ports if p.get('status') == 'active'])

    def get_ports_by_vlan(self, vlan_id):
        """Get all ports assigned to a specific VLAN."""
        return [p for p in self.ports if p.get('vlan') == vlan_id]
