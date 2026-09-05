"""
Integrations models - PSA connections and synced data
"""
import json
from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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

    def delete(self, *args, **kwargs):
        """
        Override delete to clean up imported organizations.
        When a PSA connection is deleted, automatically delete all organizations
        that were imported from it (tracked via ExternalObjectMap).
        """
        from audit.models import AuditLog

        # Find all organizations imported from this connection
        imported_orgs = set()
        for mapping in self.object_maps.filter(local_type='organization'):
            try:
                org = Organization.objects.get(id=mapping.local_id)
                imported_orgs.add(org)
            except Organization.DoesNotExist:
                pass

        # Log the cleanup
        if imported_orgs:
            org_names = [org.name for org in imported_orgs]
            AuditLog.objects.create(
                action='delete',
                object_type='PSAConnection',
                object_id=self.id,
                object_repr=self.name,
                description=f'Deleted PSA connection "{self.name}" and {len(imported_orgs)} imported organizations: {", ".join(org_names)}',
                organization=self.organization,
                extra_data={
                    'connection_name': self.name,
                    'provider_type': self.provider_type,
                    'imported_org_count': len(imported_orgs),
                    'imported_org_names': org_names,
                }
            )

        # Delete imported organizations (this will cascade delete their data)
        for org in imported_orgs:
            org.delete()

        # Now delete the connection (mappings will cascade delete)
        super().delete(*args, **kwargs)


class ExternalObjectMap(BaseModel):
    """
    Mapping table between external PSA/RMM objects and local objects.
    Uses GenericForeignKey to support both PSAConnection and RMMConnection.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='external_object_maps')

    # Generic connection field (supports PSAConnection or RMMConnection)
    connection_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    connection_id = models.PositiveIntegerField()
    connection = GenericForeignKey('connection_type', 'connection_id')

    # External object
    external_id = models.CharField(max_length=255, db_index=True)
    external_type = models.CharField(max_length=50)  # e.g., 'company', 'contact', 'ticket', 'rmm_client', 'rmm_site'
    external_hash = models.CharField(max_length=64, blank=True)  # For change detection

    # Local object
    local_type = models.CharField(max_length=50)  # e.g., 'psa_company', 'psa_contact', 'organization'
    local_id = models.PositiveIntegerField()

    # Sync metadata
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'external_object_maps'
        unique_together = [['connection_type', 'connection_id', 'external_type', 'external_id']]
        indexes = [
            models.Index(fields=['organization', 'external_type', 'external_id']),
            models.Index(fields=['local_type', 'local_id']),
            models.Index(fields=['connection_type', 'connection_id']),
        ]

    def __str__(self):
        conn_name = getattr(self.connection, 'name', 'Unknown')
        return f"{conn_name}:{self.external_type}:{self.external_id} -> {self.local_type}:{self.local_id}"


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

    def delete(self, *args, **kwargs):
        """
        Override delete to clean up imported organizations.
        When an RMM connection is deleted, automatically delete organizations
        that were auto-created from RMM sites (identified by name prefix and device ownership).
        """
        from audit.models import AuditLog

        # Find organizations that match the import criteria
        imported_orgs = []

        if self.org_name_prefix:
            # Find orgs with the RMM prefix
            potential_orgs = Organization.objects.filter(name__startswith=self.org_name_prefix)
        else:
            # No prefix - look for orgs that only have RMM devices and nothing else
            potential_orgs = Organization.objects.filter(
                rmm_devices__connection=self,
            ).distinct()

        # For each potential org, check if it should be deleted
        for org in potential_orgs:
            # Skip the parent organization (the one that owns this connection)
            if org.id == self.organization.id:
                continue

            # Check if org only has RMM devices and no other data
            has_other_data = (
                org.passwords.exists() or
                org.assets.exists() or
                org.documents.exists() or
                org.processes.exists() or
                org.contacts.exists() or
                org.website_monitors.exists()
            )

            # Only delete if it has no other data (pure RMM import)
            if not has_other_data:
                imported_orgs.append(org)

        # Log the cleanup
        if imported_orgs:
            org_names = [org.name for org in imported_orgs]
            AuditLog.objects.create(
                action='delete',
                object_type='RMMConnection',
                object_id=self.id,
                object_repr=self.name,
                description=f'Deleted RMM connection "{self.name}" and {len(imported_orgs)} imported organizations: {", ".join(org_names)}',
                organization=self.organization,
                extra_data={
                    'connection_name': self.name,
                    'provider_type': self.provider_type,
                    'imported_org_count': len(imported_orgs),
                    'imported_org_names': org_names,
                }
            )

        # Delete imported organizations (this will cascade delete their RMM devices)
        for org in imported_orgs:
            org.delete()

        # Now delete the connection
        super().delete(*args, **kwargs)


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


# ============================================================================
# UniFi Integration Models
# ============================================================================

class UnifiConnection(BaseModel):
    """
    UniFi Network Application connection per organization.
    Pulls network topology data for documentation generation.
    mode='self_hosted' uses a local controller URL (default).
    mode='cloud' uses the UniFi Site Manager cloud API (api.ui.com).
    """
    MODE_SELF_HOSTED = 'self_hosted'
    MODE_CLOUD = 'cloud'
    MODE_CHOICES = [
        (MODE_SELF_HOSTED, 'Self-hosted (local controller)'),
        (MODE_CLOUD, 'Cloud (UniFi Site Manager / ui.com)'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='unifi_connections')
    name = models.CharField(max_length=255, help_text="Friendly name for this connection")
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_SELF_HOSTED,
                            help_text="Self-hosted controller or UniFi Site Manager cloud API")
    host = models.URLField(max_length=500, blank=True,
                           help_text="UniFi controller URL (self-hosted only), e.g. https://192.168.1.1")
    verify_ssl = models.BooleanField(default=False, help_text="Verify SSL certificate (disable for self-signed)")

    # Encrypted API key
    encrypted_credentials = models.TextField(blank=True, help_text="Encrypted JSON with api_key")

    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)
    cached_data = models.JSONField(default=dict, blank=True)

    # Auto-sync / asset import settings
    auto_sync_assets = models.BooleanField(default=False, help_text='Automatically import devices to asset registry on each sync')
    sync_interval_minutes = models.PositiveIntegerField(default=720, help_text='Auto-sync interval in minutes (0=disabled)')
    last_asset_sync_at = models.DateTimeField(null=True, blank=True)

    # Cloud org assignment: maps site name → Organization.id (cloud mode only)
    site_org_map = models.JSONField(default=dict, blank=True,
                                    help_text='Cloud mode: maps site name to organization ID')

    # Link to generated doc
    doc = models.ForeignKey('docs.Document', on_delete=models.SET_NULL, null=True, blank=True, related_name='unifi_connections')

    objects = OrganizationManager()

    class Meta:
        db_table = 'unifi_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name}"

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)


# ============================================================================
# Omada Integration Models
# ============================================================================

class OmadaConnection(models.Model):
    """
    TP-Link Omada SDN Controller connection per organization.
    Pulls network device data for documentation and asset import.
    """
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='omada_connections')
    name = models.CharField(max_length=200)
    host = models.URLField(help_text='Omada controller URL, e.g. https://192.168.1.1:8043')
    verify_ssl = models.BooleanField(default=False)

    # Encrypted credentials: {username, password}
    encrypted_credentials = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, blank=True)
    last_error = models.TextField(blank=True)
    cached_data = models.JSONField(default=dict, blank=True)

    # Auto-sync / asset import settings
    auto_sync_assets = models.BooleanField(default=False, help_text='Automatically import devices to asset registry on each sync')
    sync_interval_minutes = models.PositiveIntegerField(default=720, help_text='Auto-sync interval in minutes (0=disabled)')
    last_asset_sync_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'omada_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name}"

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)


# ============================================================================
# Grandstream Integration Models
# ============================================================================

class GrandstreamConnection(models.Model):
    """
    Grandstream GWN Manager (WiFi controller) connection per organization.
    Supports cloud (gwn.cloud) and self-hosted deployments.
    """
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='grandstream_connections')
    name = models.CharField(max_length=200)
    host = models.URLField(default='https://gwn.cloud', help_text='GWN Manager URL, e.g. https://gwn.cloud or self-hosted URL')
    verify_ssl = models.BooleanField(default=False)

    # Encrypted credentials: {api_key}
    encrypted_credentials = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, blank=True)
    last_error = models.TextField(blank=True)
    cached_data = models.JSONField(default=dict, blank=True)

    # Auto-sync / asset import settings
    auto_sync_assets = models.BooleanField(default=False, help_text='Automatically import devices to asset registry on each sync')
    sync_interval_minutes = models.PositiveIntegerField(default=720, help_text='Auto-sync interval in minutes (0=disabled)')
    last_asset_sync_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'grandstream_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name}"

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)


# ============================================================================
# Microsoft 365 Integration Models
# ============================================================================

class M365Connection(BaseModel):
    """
    Microsoft 365 tenant connection per organization.
    Uses Azure AD app registration (client credentials flow) to read tenant data via Graph API.
    Credentials are encrypted at rest.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='m365_connections')
    name = models.CharField(max_length=255, help_text="Friendly name for this connection")
    tenant_id = models.CharField(max_length=255, help_text="Azure AD tenant ID (Directory ID)")

    # Encrypted credentials: client_id, client_secret
    encrypted_credentials = models.TextField(blank=True, help_text="Encrypted JSON with client_id and client_secret")

    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)
    cached_data = models.JSONField(default=dict, blank=True)

    # Link to generated doc
    doc = models.ForeignKey('docs.Document', on_delete=models.SET_NULL, null=True, blank=True, related_name='m365_connections')

    objects = OrganizationManager()

    class Meta:
        db_table = 'm365_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.slug}:{self.name}"

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)


# ---------------------------------------------------------------------------
# Distributor connections (Workstream 8)
# ---------------------------------------------------------------------------

class DistributorConnection(BaseModel):
    """
    Distributor catalog/pricing connection per organization. Distinct
    from PSAConnection (different methods — distributors return product
    catalog, pricing, stock, orders; not tickets).
    """
    PROVIDER_TYPES = [
        ('ingram_xvantage', 'Ingram Micro Xvantage'),
        ('synnex', 'TD Synnex'),
        ('d_and_h', 'D&H Distributing'),
        ('scansource', 'ScanSource'),
        ('pax8', 'Pax8'),
        ('qbs', 'QBS Software'),
        ('westcoast', 'Westcoast'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='distributor_connections')
    provider_type = models.CharField(max_length=50, choices=PROVIDER_TYPES)
    name = models.CharField(max_length=255)

    base_url = models.URLField(max_length=500, blank=True,
        help_text='Optional — defaults to the provider\'s production endpoint')
    encrypted_credentials = models.TextField(blank=True,
        help_text='Encrypted JSON with API keys, customer IDs, etc.')

    # Webhook signing secret (separate from credentials so admins can rotate
    # without re-issuing API keys). Encrypted.
    encrypted_webhook_secret = models.TextField(blank=True)
    webhook_token = models.CharField(max_length=64, blank=True, db_index=True,
        help_text='Random token in the webhook URL — first defence-in-depth check before signature validation')

    sync_enabled = models.BooleanField(default=True)
    sync_catalog = models.BooleanField(default=False,
        help_text='Sync the full product catalog (large; opt-in)')
    sync_pricing = models.BooleanField(default=True,
        help_text='Pull pricing on-demand for SKUs in tickets')
    sync_interval_minutes = models.PositiveIntegerField(default=1440,
        help_text='How often the catalog sync runs (default daily)')

    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'distributor_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f'{self.organization.slug}:{self.name} ({self.get_provider_type_display()})'

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        encrypted = json.loads(self.encrypted_credentials)
        return decrypt_dict(encrypted)

    def set_webhook_secret(self, secret: str):
        if not secret:
            self.encrypted_webhook_secret = ''
            return
        encrypted = encrypt_dict({'s': secret})
        self.encrypted_webhook_secret = json.dumps(encrypted)

    def get_webhook_secret(self) -> str:
        if not self.encrypted_webhook_secret:
            return ''
        try:
            d = decrypt_dict(json.loads(self.encrypted_webhook_secret))
            return d.get('s', '') or ''
        except Exception:
            return ''

    def save(self, *args, **kwargs):
        if not self.webhook_token:
            import secrets as _secrets
            self.webhook_token = _secrets.token_urlsafe(32)
        super().save(*args, **kwargs)


class DistributorWebhookEvent(BaseModel):
    """
    Append-only log of every distributor webhook hit. Stores the raw
    payload (limited to 64KB) for forensics. Used by sync workers to
    update orders / ASNs.
    """
    connection = models.ForeignKey(DistributorConnection, on_delete=models.CASCADE,
                                   related_name='webhook_events')
    event_type = models.CharField(max_length=80, blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    signature_valid = models.BooleanField(default=False)
    body_truncated = models.TextField(blank=True)  # capped to 64KB upstream
    headers_summary = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    process_error = models.TextField(blank=True)

    class Meta:
        db_table = 'distributor_webhook_events'
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['connection', '-received_at']),
        ]

    def __str__(self):
        return f'{self.connection_id}/{self.event_type or "?"}@{self.received_at:%Y-%m-%d %H:%M}'


# ---------------------------------------------------------------------------
# Accounting integrations — push invoices to QuickBooks Online / Xero / etc.
# ---------------------------------------------------------------------------

class AccountingConnection(BaseModel):
    """
    Per-organization OAuth2 connection to an accounting system. Distinct
    from PSAConnection (third-party PSAs) and DistributorConnection
    (catalogs/orders). Stores client_id + client_secret + refresh_token
    encrypted; accessing the access_token refreshes it automatically when
    near expiry.
    """
    PROVIDER_TYPES = [
        ('quickbooks_online', 'QuickBooks Online'),
        ('xero', 'Xero'),
        ('freshbooks', 'FreshBooks'),
        ('wave', 'Wave Accounting'),
        ('zoho_books', 'Zoho Books'),
        ('sage_business_cloud', 'Sage Business Cloud'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='accounting_connections',
    )
    provider_type = models.CharField(max_length=50, choices=PROVIDER_TYPES)
    name = models.CharField(max_length=255)

    base_url = models.URLField(max_length=500, blank=True,
        help_text='Defaults to provider production endpoint when blank')

    # All credentials (client_id, client_secret, refresh_token, access_token,
    # expires_at, realm_id for QBO, tenant_id for Xero, etc.) encrypted as
    # a single JSON blob.
    encrypted_credentials = models.TextField(blank=True)

    # Default tax rate to apply when creating invoices on the provider side
    # (when our line items don't have an explicit tax rate already mapped).
    default_tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)

    sync_enabled = models.BooleanField(default=False,
        help_text='Allow live invoice push (off by default — sandbox first)')
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'accounting_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f'{self.organization.slug}:{self.name} ({self.get_provider_type_display()})'

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        try:
            return decrypt_dict(json.loads(self.encrypted_credentials))
        except Exception:
            return {}

    def update_credentials(self, **kwargs):
        """Merge new fields into the encrypted credentials blob."""
        creds = self.get_credentials()
        creds.update(kwargs)
        self.set_credentials(creds)


class AccountingAuditLog(BaseModel):
    """Phase 27 v2 (v3.17.260): one row per accounting-system interaction.

    Captures every push_invoice / record_payment call so reconciliation can
    explain *why* an invoice's status diverges from QBO/Xero. Stores small
    request/response summaries (truncated; never full payloads) — enough to
    debug without pulling secrets or PII into the table.
    """
    ACTION_CHOICES = [
        ('push_invoice', 'Push Invoice'),
        ('record_payment', 'Record Payment'),
        ('test_connection', 'Test Connection'),
        ('refresh_token', 'Refresh Token'),
        # v3.17.531: `poll_balance` had been written since v3.17.280 without
        # being registered here, so those rows rendered with a blank label.
        ('poll_balance', 'Poll Invoice Balance'),
        ('push_customer', 'Push Customer'),
        ('pull_customers', 'Pull Customers'),
        ('pull_payments', 'Pull Payments'),
        ('pull_invoices', 'Pull Invoice State'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='accounting_audit_logs',
    )
    connection = models.ForeignKey(
        AccountingConnection, on_delete=models.CASCADE,
        related_name='audit_logs', null=True, blank=True,
    )
    provider_type = models.CharField(max_length=50)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=40, blank=True,
        help_text='e.g. invoice, payment')
    resource_id = models.CharField(max_length=120, blank=True,
        help_text='Local PK of the source row (Invoice.pk / Payment.pk)')
    external_id = models.CharField(max_length=120, blank=True,
        help_text='Provider-side ID returned on success')
    success = models.BooleanField(default=False)
    http_status = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    request_summary = models.CharField(max_length=500, blank=True)
    response_summary = models.CharField(max_length=500, blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'accounting_audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
            models.Index(fields=['connection', '-created_at']),
            models.Index(fields=['action', 'success']),
        ]

    def __str__(self):
        ok = 'ok' if self.success else 'fail'
        return f'{self.provider_type}:{self.action} ({ok}) #{self.pk}'


class AccountingCustomerLink(BaseModel):
    """Phase 44.1 (v3.17.531): which provider customer an organization maps to.

    This mapping used to live as a `customer_map` dict inside the connection's
    encrypted credentials blob. That made it invisible to queries, absent from
    the admin, impossible to report on, and — worst — collateral damage of a
    credentials reset, which would silently orphan every mapping and cause the
    next push to create duplicate customers provider-side.

    The unique constraints are the point of the model. One organization maps to
    at most one customer per connection, and one provider customer is claimed by
    at most one organization, so a mapping cannot silently fork.
    """
    SOURCES = [
        ('push', 'Created here, pushed to the provider'),
        ('matched', 'Matched an existing provider customer by name'),
        ('pull', 'Imported from the provider'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='accounting_customer_links',
        help_text='The tenant that owns the connection.',
    )
    connection = models.ForeignKey(
        AccountingConnection, on_delete=models.CASCADE,
        related_name='customer_links',
    )
    client_org = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='accounting_customer_mappings',
        help_text='The client this provider customer represents.',
    )
    provider_customer_id = models.CharField(
        max_length=120,
        help_text='Customer Id in the accounting system.')
    display_name = models.CharField(
        max_length=255, blank=True,
        help_text='Provider-side DisplayName, kept for reporting and matching.')
    source = models.CharField(max_length=20, choices=SOURCES, default='push')
    last_pushed_at = models.DateTimeField(null=True, blank=True)
    last_pulled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'accounting_customer_links'
        ordering = ['display_name']
        constraints = [
            models.UniqueConstraint(
                fields=['connection', 'client_org'],
                name='uniq_accounting_link_per_client'),
            models.UniqueConstraint(
                fields=['connection', 'provider_customer_id'],
                name='uniq_accounting_link_per_customer'),
        ]
        indexes = [
            models.Index(fields=['organization', 'connection']),
        ]

    def __str__(self):
        return f'{self.client_org_id} -> {self.provider_customer_id}'


# ---------------------------------------------------------------------------
# Phase 15 v8 (v3.17.296) — ACH / payment processor connections.
# ---------------------------------------------------------------------------

class PaymentConnection(BaseModel):
    """Per-organization OAuth2 / API-key connection to an ACH / card
    processor. Adapter stubs for Stripe + GoCardless ship today;
    completing the OAuth dance + live `charge()` calls happens when
    an MSP connects a real account.
    """
    PROVIDER_TYPES = [
        ('stripe', 'Stripe (cards + ACH)'),
        ('gocardless', 'GoCardless (Direct Debit / ACH)'),
        ('manual', 'Manual / external (no automation)'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='payment_connections',
    )
    provider_type = models.CharField(max_length=40, choices=PROVIDER_TYPES,
                                      default='manual')
    name = models.CharField(max_length=200)
    base_url = models.URLField(max_length=500, blank=True)
    encrypted_credentials = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sync_enabled = models.BooleanField(default=False,
        help_text='Allow live charges (off by default — sandbox first).')
    last_charge_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'payment_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f'{self.organization.slug}:{self.name} ({self.get_provider_type_display()})'

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        try:
            return decrypt_dict(json.loads(self.encrypted_credentials))
        except Exception:
            return {}

    def update_credentials(self, **kwargs):
        creds = self.get_credentials()
        creds.update(kwargs)
        self.set_credentials(creds)


# ---------------------------------------------------------------------------
# Phase 17 v5 (v3.17.309) — Vendor warranty lookup connections.
# ---------------------------------------------------------------------------

class WarrantyConnection(BaseModel):
    """Per-org connection to a hardware vendor's warranty-lookup API.
    Adapter stubs for Dell + HPE + Lenovo ship today; live
    `lookup_warranty()` calls land when an MSP wires up real
    credentials."""
    PROVIDER_TYPES = [
        ('dell', 'Dell TechDirect Warranty'),
        ('hpe', 'HPE iLO Warranty'),
        ('lenovo', 'Lenovo Support Warranty'),
        ('manual', 'Manual / external (no automation)'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='warranty_connections',
    )
    provider_type = models.CharField(max_length=40, choices=PROVIDER_TYPES,
                                      default='manual')
    name = models.CharField(max_length=200)
    base_url = models.URLField(max_length=500, blank=True)
    encrypted_credentials = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    last_lookup_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'warranty_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f'{self.organization.slug}:{self.name} ({self.get_provider_type_display()})'

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        try:
            return decrypt_dict(json.loads(self.encrypted_credentials))
        except Exception:
            return {}

    def update_credentials(self, **kwargs):
        creds = self.get_credentials()
        creds.update(kwargs)
        self.set_credentials(creds)


# ---------------------------------------------------------------------------
# Phase 15 v12 (v3.17.297) — Tax compute connections (Avalara / TaxJar).
# ---------------------------------------------------------------------------

class TaxConnection(BaseModel):
    """Per-organization connection to a sales-tax compute service.
    Adapter stubs for Avalara + TaxJar ship today; live `compute_tax()`
    lands when an MSP wires up a real account."""
    PROVIDER_TYPES = [
        ('avalara', 'Avalara AvaTax'),
        ('taxjar', 'TaxJar'),
        ('manual', 'Manual / external (use invoice tax_rate)'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='tax_connections',
    )
    provider_type = models.CharField(max_length=40, choices=PROVIDER_TYPES,
                                      default='manual')
    name = models.CharField(max_length=200)
    base_url = models.URLField(max_length=500, blank=True)
    encrypted_credentials = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    last_lookup_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    objects = OrganizationManager()

    class Meta:
        db_table = 'tax_connections'
        unique_together = [['organization', 'name']]
        ordering = ['name']

    def __str__(self):
        return f'{self.organization.slug}:{self.name} ({self.get_provider_type_display()})'

    def set_credentials(self, credentials_dict):
        encrypted = encrypt_dict(credentials_dict)
        self.encrypted_credentials = json.dumps(encrypted)

    def get_credentials(self):
        if not self.encrypted_credentials:
            return {}
        try:
            return decrypt_dict(json.loads(self.encrypted_credentials))
        except Exception:
            return {}

    def update_credentials(self, **kwargs):
        creds = self.get_credentials()
        creds.update(kwargs)
        self.set_credentials(creds)
