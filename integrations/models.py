"""
Integrations models - PSA connections and synced data
"""
import json
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, BaseModel
from core.utils import OrganizationManager
from vault.encryption import encrypt, decrypt, encrypt_dict, decrypt_dict


class PSAConnection(BaseModel):
    """
    PSA provider connection configuration per organization.
    Credentials and tokens are encrypted at rest.
    """
    PROVIDER_TYPES = [
        ('alga_psa', 'Alga PSA'),
        ('autotask', 'Autotask PSA'),
        ('connectwise_manage', 'ConnectWise Manage'),
        ('freshservice', 'Freshservice'),
        ('halo_psa', 'HaloPSA'),
        ('itflow', 'ITFlow'),
        ('kaseya_bms', 'Kaseya BMS'),
        ('rangermsp', 'RangerMSP (CommitCRM)'),
        ('syncro', 'Syncro'),
        ('zendesk', 'Zendesk'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='psa_connections')
    provider_type = models.CharField(max_length=50, choices=PROVIDER_TYPES)
    name = models.CharField(max_length=255, help_text="Friendly name for this connection")

    # Connection settings (varies by provider)
    base_url = models.URLField(max_length=500)

    # Encrypted credentials (stored as JSON)
    encrypted_credentials = models.TextField(help_text="Encrypted JSON with API keys, secrets, tokens")

    # Sync settings
    sync_enabled = models.BooleanField(default=True)
    sync_companies = models.BooleanField(default=True)
    sync_contacts = models.BooleanField(default=True)
    sync_tickets = models.BooleanField(default=True)
    sync_agreements = models.BooleanField(default=False)
    sync_projects = models.BooleanField(default=False)
    sync_interval_minutes = models.PositiveIntegerField(default=60)

    # Organization import settings
    import_organizations = models.BooleanField(default=False, help_text="Automatically import/create organizations from PSA companies")
    org_import_as_active = models.BooleanField(default=True, help_text="Set imported organizations as active")
    org_name_prefix = models.CharField(max_length=50, blank=True, default='', help_text='Prefix to add to imported organization names (e.g., "PSA-")')

    # Field mappings (JSON)
    field_mappings = models.JSONField(default=dict, blank=True, help_text="Custom field mappings")

    # Status
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'psa_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name} ({self.get_provider_type_display()})"

    def set_credentials(self, credentials_dict):
        """
        Encrypt and store credentials.
        credentials_dict: dict with keys like 'api_key', 'client_id', 'client_secret', 'oauth_token', etc.
        """
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        """
        Decrypt and return credentials dict.
        """
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)


class ExternalObjectMap(BaseModel):
    """
    Mapping table between external PSA objects and local objects.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='external_object_maps')
    connection = models.ForeignKey(PSAConnection, on_delete=models.CASCADE, related_name='object_maps')

    # External object
    external_id = models.CharField(max_length=255, db_index=True)
    external_type = models.CharField(max_length=50)  # e.g., 'company', 'contact', 'ticket'
    external_hash = models.CharField(max_length=64, blank=True)  # For change detection

    # Local object
    local_type = models.CharField(max_length=50)  # e.g., 'psa_company', 'psa_contact'
    local_id = models.PositiveIntegerField()

    # Sync metadata
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'external_object_maps'
        unique_together = [['connection', 'external_type', 'external_id']]
        indexes = [
            models.Index(fields=['organization', 'external_type', 'external_id']),
            models.Index(fields=['local_type', 'local_id']),
        ]

    def __str__(self):
        return f"{self.connection.name}:{self.external_type}:{self.external_id} -> {self.local_type}:{self.local_id}"


class PSACompany(BaseModel):
    """
    Synced company from PSA.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='psa_companies')
    connection = models.ForeignKey(PSAConnection, on_delete=models.CASCADE, related_name='companies')

    external_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=100, blank=True)
    website = models.URLField(max_length=500, blank=True)
    address = models.TextField(blank=True)

    # Raw PSA data (JSON)
    raw_data = models.JSONField(default=dict, blank=True)

    last_synced_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'psa_companies'
        unique_together = [['connection', 'external_id']]
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'name']),
        ]

    def __str__(self):
        return f"{self.name} ({self.connection.get_provider_type_display()})"


class PSAContact(BaseModel):
    """
    Synced contact from PSA.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='psa_contacts')
    connection = models.ForeignKey(PSAConnection, on_delete=models.CASCADE, related_name='contacts')
    company = models.ForeignKey(PSACompany, on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts')

    external_id = models.CharField(max_length=255)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=100, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'psa_contacts'
        unique_together = [['connection', 'external_id']]
        ordering = ['last_name', 'first_name']
        indexes = [
            models.Index(fields=['organization', 'last_name']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class PSATicket(BaseModel):
    """
    Synced ticket from PSA.
    """
    STATUS_CHOICES = [
        ('closed', 'Closed'),
        ('in_progress', 'In Progress'),
        ('new', 'New'),
        ('resolved', 'Resolved'),
        ('waiting', 'Waiting'),
    ]

    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('urgent', 'Urgent'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='psa_tickets')
    connection = models.ForeignKey(PSAConnection, on_delete=models.CASCADE, related_name='tickets')
    company = models.ForeignKey(PSACompany, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    contact = models.ForeignKey(PSAContact, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')

    external_id = models.CharField(max_length=255)
    ticket_number = models.CharField(max_length=100, blank=True)
    subject = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='new')
    priority = models.CharField(max_length=50, choices=PRIORITY_CHOICES, default='medium')

    external_created_at = models.DateTimeField(null=True, blank=True)
    external_updated_at = models.DateTimeField(null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'psa_tickets'
        unique_together = [['connection', 'external_id']]
        ordering = ['-external_updated_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['external_updated_at']),
        ]

    def __str__(self):
        return f"{self.ticket_number}: {self.subject}"


# ============================================================================
# RMM Integration Models
# ============================================================================

class RMMConnection(BaseModel):
    """
    RMM provider connection configuration per organization.
    Credentials and tokens are encrypted at rest.
    """
    PROVIDER_TYPES = [
        ('atera', 'Atera'),
        ('connectwise_automate', 'ConnectWise Automate'),
        ('datto_rmm', 'Datto RMM'),
        ('ninjaone', 'NinjaOne'),
        ('tactical_rmm', 'Tactical RMM'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='rmm_connections')
    provider_type = models.CharField(max_length=50, choices=PROVIDER_TYPES)
    name = models.CharField(max_length=255, help_text="Friendly name for this connection")

    # Connection settings (varies by provider)
    base_url = models.URLField(max_length=500)

    # Encrypted credentials (stored as JSON)
    encrypted_credentials = models.TextField(help_text="Encrypted JSON with API keys, secrets, tokens")

    # Sync settings
    sync_enabled = models.BooleanField(default=True)
    sync_devices = models.BooleanField(default=True)
    sync_alerts = models.BooleanField(default=True)
    sync_software = models.BooleanField(default=False)
    sync_network_config = models.BooleanField(default=False)
    sync_interval_minutes = models.PositiveIntegerField(default=60)

    # Asset mapping - link RMM devices to Asset model
    map_to_assets = models.BooleanField(default=True, help_text="Automatically map RMM devices to Assets")

    # Organization import settings
    import_organizations = models.BooleanField(default=False, help_text="Automatically import/create organizations from RMM sites/clients")
    org_import_as_active = models.BooleanField(default=True, help_text="Set imported organizations as active")
    org_name_prefix = models.CharField(max_length=50, blank=True, default='', help_text='Prefix to add to imported organization names (e.g., "RMM-")')

    # Field mappings (JSON) for custom asset type mapping
    field_mappings = models.JSONField(default=dict, blank=True, help_text="Custom field mappings")

    # Status
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'rmm_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name} ({self.get_provider_type_display()})"

    def set_credentials(self, credentials_dict):
        """
        Encrypt and store credentials.
        credentials_dict: dict with keys like 'api_key', 'client_id', 'client_secret', 'access_token', etc.
        """
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        """
        Decrypt and return credentials dict.
        """
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)


class RMMDevice(BaseModel):
    """
    Synced device/asset from RMM.
    """
    DEVICE_TYPES = [
        ('laptop', 'Laptop'),
        ('mobile', 'Mobile Device'),
        ('network', 'Network Device'),
        ('server', 'Server'),
        ('unknown', 'Unknown'),
        ('virtual', 'Virtual Machine'),
        ('workstation', 'Workstation'),
    ]

    OS_TYPES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('linux', 'Linux'),
        ('macos', 'macOS'),
        ('other', 'Other'),
        ('windows', 'Windows'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='rmm_devices')
    connection = models.ForeignKey(RMMConnection, on_delete=models.CASCADE, related_name='devices')

    # Device identification
    external_id = models.CharField(max_length=255)
    device_name = models.CharField(max_length=255)
    device_type = models.CharField(max_length=50, choices=DEVICE_TYPES, default='unknown')

    # Hardware info
    manufacturer = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)

    # OS info
    os_type = models.CharField(max_length=50, choices=OS_TYPES, blank=True)
    os_version = models.CharField(max_length=255, blank=True)

    # Network info
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mac_address = models.CharField(max_length=17, blank=True)

    # Site/Client info (for organization mapping)
    site_id = models.CharField(max_length=255, blank=True, help_text="RMM site/client ID")
    site_name = models.CharField(max_length=255, blank=True, help_text="RMM site/client name")

    # Location info (for mapping devices on location maps)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, help_text="Device latitude for map display")
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, help_text="Device longitude for map display")

    # Status
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)

    # Link to local Asset
    linked_asset = models.ForeignKey(
        'assets.Asset',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rmm_devices',
        help_text="Associated Asset if mapped"
    )

    # Raw RMM data (JSON)
    raw_data = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'rmm_devices'
        unique_together = [['connection', 'external_id']]
        ordering = ['device_name']
        indexes = [
            models.Index(fields=['organization', 'device_name']),
            models.Index(fields=['is_online']),
            models.Index(fields=['last_seen']),
        ]

    def __str__(self):
        return f"{self.device_name} ({self.connection.get_provider_type_display()})"


class RMMAlert(BaseModel):
    """
    Monitoring alert from RMM.
    """
    SEVERITY_CHOICES = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='rmm_alerts')
    connection = models.ForeignKey(RMMConnection, on_delete=models.CASCADE, related_name='alerts')
    device = models.ForeignKey(RMMDevice, on_delete=models.CASCADE, related_name='alerts')

    external_id = models.CharField(max_length=255)
    alert_type = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=50, choices=SEVERITY_CHOICES, default='info')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='active')

    triggered_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'rmm_alerts'
        unique_together = [['connection', 'external_id']]
        ordering = ['-triggered_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['triggered_at']),
        ]

    def __str__(self):
        return f"{self.alert_type} on {self.device.device_name} ({self.severity})"


class RMMSoftware(BaseModel):
    """
    Software inventory from RMM.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='rmm_software')
    connection = models.ForeignKey(RMMConnection, on_delete=models.CASCADE, related_name='software_inventory')
    device = models.ForeignKey(RMMDevice, on_delete=models.CASCADE, related_name='software')

    external_id = models.CharField(max_length=255, blank=True)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=255, blank=True)
    vendor = models.CharField(max_length=255, blank=True)
    install_date = models.DateTimeField(null=True, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'rmm_software'
        ordering = ['name', 'version']
        indexes = [
            models.Index(fields=['organization', 'name']),
            models.Index(fields=['device', 'name']),
        ]

    def __str__(self):
        vendor_str = f" by {self.vendor}" if self.vendor else ""
        version_str = f" {self.version}" if self.version else ""
        return f"{self.name}{version_str}{vendor_str}"
