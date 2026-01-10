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
        ('connectwise_manage', 'ConnectWise Manage'),
        ('autotask', 'Autotask PSA'),
        ('halo_psa', 'HaloPSA'),
        ('kaseya_bms', 'Kaseya BMS'),
        ('syncro', 'Syncro'),
        ('freshservice', 'Freshservice'),
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
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('waiting', 'Waiting'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
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
