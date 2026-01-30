"""
Core models - Organization and Tags
"""
from django.db import models
from django.utils.text import slugify
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


class Organization(models.Model):
    """
    Multi-tenant organization/tenant model.
    All data is scoped to an organization.
    """
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    # Company Information
    legal_name = models.CharField(max_length=255, blank=True, help_text="Full legal business name")
    tax_id = models.CharField(max_length=50, blank=True, help_text="Tax ID / EIN")

    # Address
    street_address = models.CharField(max_length=255, blank=True)
    street_address_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='United States', blank=True)

    # Contact Information
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    # Primary Contact Person
    primary_contact_name = models.CharField(max_length=255, blank=True)
    primary_contact_title = models.CharField(max_length=100, blank=True)
    primary_contact_email = models.EmailField(blank=True)
    primary_contact_phone = models.CharField(max_length=50, blank=True)

    # Branding
    logo = models.ImageField(upload_to='organizations/logos/', blank=True, null=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def full_address(self):
        """Get full formatted address."""
        parts = []
        if self.street_address:
            parts.append(self.street_address)
        if self.street_address_2:
            parts.append(self.street_address_2)
        if self.city and self.state and self.postal_code:
            parts.append(f"{self.city}, {self.state} {self.postal_code}")
        elif self.city:
            parts.append(self.city)
        if self.country and self.country != 'United States':
            parts.append(self.country)
        return ', '.join(parts) if parts else ''

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Tag(models.Model):
    """
    Generic tagging model for various entities.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='tags')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    color = models.CharField(max_length=7, default='#6c757d')  # Hex color
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tags'
        unique_together = [['organization', 'slug']]
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class BaseModel(models.Model):
    """
    Abstract base model with common fields.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Relation(BaseModel):
    """
    Generic relationship model that can link any two objects.
    Links from 'source' to 'target' with a relationship type.

    Examples:
    - Asset -> Document (relation_type='documented_by')
    - Asset -> Password (relation_type='credentials')
    - Document -> Asset (relation_type='applies_to')
    - Contact -> Asset (relation_type='responsible_for')
    """
    RELATION_TYPES = [
        ('applies_to', 'Applies To'),
        ('contains', 'Contains'),
        ('credentials', 'Credentials'),
        ('depends_on', 'Depends On'),
        ('documented_by', 'Documented By'),
        ('related_to', 'Related To'),
        ('responsible_for', 'Responsible For'),
        ('used_by', 'Used By'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='relations')
    relation_type = models.CharField(max_length=50, choices=RELATION_TYPES, default='related_to')

    # Source object (what is linking)
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='source_relations'
    )
    source_object_id = models.PositiveIntegerField()
    source_object = GenericForeignKey('source_content_type', 'source_object_id')

    # Target object (what is being linked to)
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='target_relations'
    )
    target_object_id = models.PositiveIntegerField()
    target_object = GenericForeignKey('target_content_type', 'target_object_id')

    # Optional description/notes about the relationship
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'relations'
        indexes = [
            models.Index(fields=['organization', 'source_content_type', 'source_object_id']),
            models.Index(fields=['organization', 'target_content_type', 'target_object_id']),
            models.Index(fields=['relation_type']),
        ]

    def __str__(self):
        return f"{self.source_object} -> {self.get_relation_type_display()} -> {self.target_object}"

    def get_source_type(self):
        """Get human-readable source type."""
        return self.source_content_type.model

    def get_target_type(self):
        """Get human-readable target type."""
        return self.target_content_type.model


class Favorite(models.Model):
    """
    Generic favorites/bookmarks system.
    Users can favorite any object type (passwords, documents, assets, etc).
    """
    from django.contrib.auth.models import User

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='favorites', null=True, blank=True)

    # Generic relation to any favoritable object
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # Optional notes about why favorited
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'favorites'
        unique_together = [['user', 'content_type', 'object_id']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'content_type']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} favorited {self.content_object}"


class SecureNote(BaseModel):
    """
    Encrypted notes that can be sent securely between users.
    Notes are encrypted and can have expiration/read-once behavior.
    """
    from django.contrib.auth.models import User

    # Sender
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_secure_notes')

    # Recipients (many-to-many for group sharing)
    recipients = models.ManyToManyField(User, related_name='received_secure_notes')

    # Organization context (optional)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='secure_notes', null=True, blank=True)

    # Content
    title = models.CharField(max_length=255)
    encrypted_content = models.TextField()  # Encrypted message body
    label = models.CharField(max_length=255, blank=True, help_text='Optional label for tracking/organizing secret links')

    # Link-only mode (Issue #47)
    link_only = models.BooleanField(default=False, help_text='Link-only mode: no recipients, share via URL')
    access_token = models.CharField(max_length=64, unique=True, blank=True, help_text='Unique token for link-only access')

    # Security settings
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Auto-delete after this time')
    read_once = models.BooleanField(default=False, help_text='Delete after first read')
    require_password = models.BooleanField(default=False, help_text='Require password to decrypt')
    access_password = models.CharField(max_length=255, blank=True, help_text='Hashed password for access')

    # Tracking
    read_by = models.ManyToManyField(User, related_name='read_secure_notes', blank=True)
    read_count = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'secure_notes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sender', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"SecureNote from {self.sender.username}: {self.title}"

    def set_content(self, plaintext_content):
        """Encrypt and store content."""
        from vault.encryption import encrypt
        self.encrypted_content = encrypt(plaintext_content)

    def get_content(self):
        """Decrypt and return content."""
        from vault.encryption import decrypt
        if not self.encrypted_content:
            return ''
        return decrypt(self.encrypted_content)

    def generate_access_token(self):
        """Generate a unique cryptographically secure access token for link-only mode."""
        import secrets
        self.access_token = secrets.token_urlsafe(48)
        return self.access_token

    def get_share_url(self, request=None):
        """Get the shareable URL for link-only mode."""
        if not self.link_only or not self.access_token:
            return None
        from django.urls import reverse
        path = reverse('core:secure_note_view_link', kwargs={'token': self.access_token})
        if request:
            return request.build_absolute_uri(path)
        return path

    def mark_as_read(self, user):
        """Mark note as read by user."""
        if user not in self.read_by.all():
            self.read_by.add(user)
            self.read_count += 1
            self.save(update_fields=['read_count'])

            # Delete if read_once is enabled
            if self.read_once:
                self.is_deleted = True
                self.save(update_fields=['is_deleted'])

    def can_be_read_by(self, user):
        """Check if user can read this note."""
        if self.is_deleted:
            return False
        if self.sender == user:
            return True
        # Link-only notes can be read by anyone with the link
        if self.link_only:
            return True
        return user in self.recipients.all()

    @property
    def is_expired(self):
        """Check if note has expired."""
        if not self.expires_at:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at


class SystemSetting(models.Model):
    """
    Global system settings stored in database.
    Singleton pattern - only one instance should exist.
    """
    # General Settings
    site_name = models.CharField(max_length=255, default='HuduGlue')
    site_url = models.URLField(max_length=500, blank=True, help_text='Base URL for email links')
    default_timezone = models.CharField(max_length=50, default='UTC', help_text='Default timezone for new users')

    # Whitelabeling Settings
    custom_company_name = models.CharField(max_length=255, blank=True, help_text='Custom company name (replaces HuduGlue branding)')
    custom_logo = models.ImageField(upload_to='branding/', blank=True, null=True, help_text='Custom logo (recommended: 200x40px PNG with transparent background)')
    custom_logo_height = models.PositiveIntegerField(default=30, help_text='Logo height in pixels (default: 30px)')

    # Security Settings
    session_timeout_minutes = models.PositiveIntegerField(default=480, help_text='Session timeout in minutes (default: 8 hours)')
    require_2fa = models.BooleanField(default=True, help_text='Require 2FA for all users')
    password_min_length = models.PositiveIntegerField(default=12, help_text='Minimum password length')
    password_require_special = models.BooleanField(default=True, help_text='Require special characters in passwords')
    failed_login_attempts = models.PositiveIntegerField(default=5, help_text='Max failed login attempts before lockout')
    lockout_duration_minutes = models.PositiveIntegerField(default=30, help_text='Account lockout duration')

    # SMTP/Email Settings
    smtp_enabled = models.BooleanField(default=False, help_text='Enable email notifications')
    smtp_host = models.CharField(max_length=255, blank=True, help_text='SMTP server hostname')
    smtp_port = models.PositiveIntegerField(default=587, help_text='SMTP server port')
    smtp_username = models.CharField(max_length=255, blank=True, help_text='SMTP username')
    smtp_password = models.CharField(max_length=255, blank=True, help_text='SMTP password (encrypted)')
    smtp_use_tls = models.BooleanField(default=True, help_text='Use TLS for SMTP')
    smtp_use_ssl = models.BooleanField(default=False, help_text='Use SSL for SMTP')
    smtp_from_email = models.EmailField(blank=True, help_text='From email address')
    smtp_from_name = models.CharField(max_length=255, default='HuduGlue', help_text='From name')

    # Notification Settings
    notify_on_user_created = models.BooleanField(default=True, help_text='Notify admins when users are created')
    notify_on_ssl_expiry = models.BooleanField(default=True, help_text='Send SSL expiration warnings')
    notify_on_domain_expiry = models.BooleanField(default=True, help_text='Send domain expiration warnings')
    ssl_expiry_warning_days = models.PositiveIntegerField(default=30, help_text='Days before SSL expiry to warn')
    domain_expiry_warning_days = models.PositiveIntegerField(default=60, help_text='Days before domain expiry to warn')

    # LDAP/Active Directory Settings
    ldap_enabled = models.BooleanField(default=False, help_text='Enable LDAP/Active Directory authentication')
    ldap_server_uri = models.CharField(max_length=500, blank=True, help_text='LDAP server URI (e.g., ldap://dc.example.com:389)')
    ldap_bind_dn = models.CharField(max_length=500, blank=True, help_text='Bind DN for LDAP queries (e.g., CN=ServiceAccount,OU=Users,DC=example,DC=com)')
    ldap_bind_password = models.CharField(max_length=255, blank=True, help_text='Password for bind DN (encrypted)')
    ldap_user_search_base = models.CharField(max_length=500, blank=True, help_text='Base DN for user searches (e.g., OU=Users,DC=example,DC=com)')
    ldap_user_search_filter = models.CharField(max_length=255, default='(sAMAccountName=%(user)s)', help_text='LDAP filter for user lookups')
    ldap_group_search_base = models.CharField(max_length=500, blank=True, help_text='Base DN for group searches (optional)')
    ldap_require_group = models.CharField(max_length=500, blank=True, help_text='Require membership in this group (DN, optional)')
    ldap_start_tls = models.BooleanField(default=True, help_text='Use StartTLS for secure connection')

    # Azure AD / Microsoft Entra ID Settings
    azure_ad_enabled = models.BooleanField(default=False, help_text='Enable Azure AD / Microsoft Entra ID authentication')
    azure_ad_tenant_id = models.CharField(max_length=255, blank=True, help_text='Azure AD Tenant ID (GUID)')
    azure_ad_client_id = models.CharField(max_length=255, blank=True, help_text='Application (client) ID from Azure portal')
    azure_ad_client_secret = models.CharField(max_length=500, blank=True, help_text='Client secret (encrypted)')
    azure_ad_redirect_uri = models.CharField(max_length=500, blank=True, help_text='Redirect URI configured in Azure (e.g., https://yourapp.com/auth/callback)')
    azure_ad_auto_create_users = models.BooleanField(default=True, help_text='Automatically create users on first Azure AD login')
    azure_ad_sync_groups = models.BooleanField(default=False, help_text='Sync Azure AD groups to roles')

    # Snyk Security Scanning Settings
    snyk_enabled = models.BooleanField(default=False, help_text='Enable Snyk security scanning')
    snyk_api_token = models.CharField(max_length=500, blank=True, help_text='Snyk API token for vulnerability scanning')
    snyk_org_id = models.CharField(max_length=255, blank=True, help_text='Snyk organization ID (optional)')
    snyk_severity_threshold = models.CharField(
        max_length=20,
        default='high',
        choices=[
            ('critical', 'Critical'),
            ('high', 'High'),
            ('low', 'Low'),
            ('medium', 'Medium'),
        ],
        help_text='Minimum severity level to report'
    )
    snyk_scan_frequency = models.CharField(
        max_length=20,
        default='daily',
        choices=[
            ('daily', 'Daily'),
            ('hourly', 'Every Hour'),
            ('manual', 'Manual Only'),
            ('weekly', 'Weekly'),
        ],
        help_text='How often to run automatic scans'
    )
    snyk_last_scan = models.DateTimeField(null=True, blank=True, help_text='Timestamp of last Snyk scan')

    # Bug Reporting
    github_pat = models.CharField(max_length=500, blank=True, help_text='GitHub Personal Access Token for bug reporting (encrypted)')

    # SMS Provider Settings
    sms_provider = models.CharField(
        max_length=20,
        default='twilio',
        choices=[
            ('twilio', 'Twilio'),
            ('plivo', 'Plivo'),
            ('sinch', 'Sinch'),
            ('vonage', 'Vonage/Nexmo'),
            ('aws_sns', 'AWS SNS'),
            ('telnyx', 'Telnyx'),
        ],
        help_text='SMS provider for sending navigation links and notifications'
    )
    sms_enabled = models.BooleanField(default=False, help_text='Enable SMS functionality')
    sms_account_sid = models.CharField(max_length=255, blank=True, help_text='SMS provider account SID/API key')
    sms_auth_token = models.CharField(max_length=500, blank=True, help_text='SMS provider auth token (encrypted)')
    sms_from_number = models.CharField(max_length=20, blank=True, help_text='From phone number (E.164 format, e.g., +15551234567)')

    # Feature Toggles
    monitoring_enabled = models.BooleanField(default=True, help_text='Enable Monitoring feature (Website & Service Monitoring)')
    global_kb_enabled = models.BooleanField(default=True, help_text='Enable Global Knowledge Base (Staff-only shared KB)')
    workflows_enabled = models.BooleanField(default=True, help_text='Enable Workflows & Automation feature')

    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='system_settings_updates')

    class Meta:
        db_table = 'system_settings'
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return f"System Settings (Updated: {self.updated_at})"

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """Enforce singleton pattern."""
        self.pk = 1
        super().save(*args, **kwargs)

    def get_smtp_password_decrypted(self):
        """Get decrypted SMTP password."""
        if not self.smtp_password:
            return ''
        try:
            from vault.encryption import decrypt
            return decrypt(self.smtp_password)
        except Exception:
            # If decryption fails, assume it's not encrypted (backward compatibility)
            return self.smtp_password

    def delete(self, *args, **kwargs):
        """Prevent deletion of settings."""
        pass


class ScheduledTask(models.Model):
    """
    Database-driven task scheduler.
    Defines recurring tasks with their schedules.
    """
    TASK_TYPES = [
        ('cleanup_stuck_scans', 'Cleanup Stuck Security Scans'),
        ('domain_expiry_check', 'Domain Expiry Check'),
        ('equipment_catalog_update', 'Equipment Catalog Update'),
        ('password_breach_scan', 'Password Breach Scanning'),
        ('psa_sync', 'PSA Synchronization'),
        ('rmm_sync', 'RMM Synchronization'),
        ('ssl_expiry_check', 'SSL Certificate Expiry Check'),
        ('update_check', 'System Update Check'),
        ('website_monitoring', 'Website Monitoring Checks'),
    ]

    task_type = models.CharField(max_length=50, choices=TASK_TYPES, unique=True)
    description = models.TextField(blank=True)

    # Schedule configuration
    enabled = models.BooleanField(default=True, help_text='Enable/disable this scheduled task')
    interval_minutes = models.PositiveIntegerField(
        default=5,
        help_text='How often to run this task (in minutes)'
    )

    # Execution tracking
    last_run_at = models.DateTimeField(null=True, blank=True, help_text='Last successful execution time')
    next_run_at = models.DateTimeField(null=True, blank=True, help_text='Next scheduled execution time')
    last_status = models.CharField(
        max_length=20,
        choices=[
            ('failed', 'Failed'),
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('success', 'Success'),
        ],
        default='pending'
    )
    last_error = models.TextField(blank=True, help_text='Last error message if failed')
    run_count = models.PositiveIntegerField(default=0, help_text='Total number of executions')

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheduled_tasks'
        ordering = ['task_type']

    def __str__(self):
        return f"{self.get_task_type_display()} (every {self.interval_minutes} min)"

    def should_run(self):
        """Check if this task should run now based on schedule."""
        if not self.enabled:
            return False

        # Never run if status is 'running' (prevent overlapping executions)
        if self.last_status == 'running':
            return False

        from django.utils import timezone
        now = timezone.now()

        # If never run, should run
        if not self.last_run_at:
            return True

        # Check if next_run_at is in the past
        if self.next_run_at and now >= self.next_run_at:
            return True

        return False

    def calculate_next_run(self):
        """Calculate the next run time based on interval."""
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        if self.last_run_at:
            self.next_run_at = self.last_run_at + timedelta(minutes=self.interval_minutes)
        else:
            self.next_run_at = now + timedelta(minutes=self.interval_minutes)

    def mark_started(self):
        """Mark task as started."""
        from django.utils import timezone
        self.last_status = 'running'
        self.last_run_at = timezone.now()
        self.save(update_fields=['last_status', 'last_run_at'])

    def mark_completed(self, error=None):
        """Mark task as completed (success or failed)."""
        from django.utils import timezone

        if error:
            self.last_status = 'failed'
            self.last_error = str(error)
        else:
            self.last_status = 'success'
            self.last_error = ''

        self.run_count += 1
        self.calculate_next_run()
        self.save(update_fields=['last_status', 'last_error', 'run_count', 'next_run_at'])

    @classmethod
    def get_or_create_defaults(cls):
        """Create default scheduled tasks if they don't exist."""
        defaults = [
            {
                'task_type': 'website_monitoring',
                'description': 'Check website monitor statuses and SSL certificates',
                'interval_minutes': 5,
                'enabled': True,
            },
            {
                'task_type': 'psa_sync',
                'description': 'Synchronize data from PSA integrations',
                'interval_minutes': 60,
                'enabled': False,
            },
            {
                'task_type': 'password_breach_scan',
                'description': 'Check all passwords against HaveIBeenPwned breach database',
                'interval_minutes': 1440,  # Once per day (24 hours)
                'enabled': True,
            },
            {
                'task_type': 'ssl_expiry_check',
                'description': 'Check for expiring SSL certificates and send notifications',
                'interval_minutes': 1440,  # Once per day
                'enabled': True,
            },
            {
                'task_type': 'domain_expiry_check',
                'description': 'Check for expiring domains and send notifications',
                'interval_minutes': 1440,  # Once per day
                'enabled': True,
            },
            {
                'task_type': 'cleanup_stuck_scans',
                'description': 'Find and mark stuck security scans as timed out (scans running > 2 hours)',
                'interval_minutes': 60,  # Every hour
                'enabled': True,
            },
        ]

        for task_data in defaults:
            task, created = cls.objects.get_or_create(
                task_type=task_data['task_type'],
                defaults=task_data
            )
            if created:
                task.calculate_next_run()


class SnykScan(models.Model):
    """Track Snyk security scan results."""
    
    STATUS_CHOICES = [
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('timeout', 'Timed Out'),
    ]

    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('low', 'Low'),
        ('medium', 'Medium'),
    ]
    
    # Scan metadata
    scan_id = models.CharField(max_length=100, unique=True, help_text="Unique scan identifier")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    cancel_requested = models.BooleanField(default=False, help_text="User requested cancellation")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True, help_text="Scan duration in seconds")
    
    # Scan results
    total_vulnerabilities = models.IntegerField(default=0)
    critical_count = models.IntegerField(default=0)
    high_count = models.IntegerField(default=0)
    medium_count = models.IntegerField(default=0)
    low_count = models.IntegerField(default=0)
    
    # Raw scan output
    scan_output = models.TextField(blank=True, help_text="Full Snyk scan output")
    error_message = models.TextField(blank=True, help_text="Error message if scan failed")
    
    # Scan configuration
    severity_threshold = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='high')
    project_path = models.CharField(max_length=500, default='/home/administrator')
    
    # User who triggered the scan
    triggered_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='snyk_scans'
    )
    
    # JSON field for detailed vulnerability data
    vulnerabilities = models.JSONField(default=dict, blank=True, help_text="Detailed vulnerability information")

    # Vulnerability tracking
    new_vulnerabilities_count = models.IntegerField(default=0, help_text="New vulnerabilities not in previous scan")
    resolved_vulnerabilities_count = models.IntegerField(default=0, help_text="Vulnerabilities resolved since last scan")
    recurring_vulnerabilities_count = models.IntegerField(default=0, help_text="Vulnerabilities present in previous scan")

    class Meta:
        db_table = 'snyk_scans'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['status']),
            models.Index(fields=['critical_count', 'high_count']),
        ]
    
    def __str__(self):
        return f"Snyk Scan {self.scan_id} - {self.status} ({self.total_vulnerabilities} issues)"
    
    def get_severity_counts(self):
        """Return dict of severity counts."""
        return {
            'critical': self.critical_count,
            'high': self.high_count,
            'medium': self.medium_count,
            'low': self.low_count,
        }
    
    def has_critical_issues(self):
        """Check if scan found critical issues."""
        return self.critical_count > 0 or self.high_count > 0
    
    def get_status_badge_class(self):
        """Return Bootstrap badge class for status."""
        badge_map = {
            'pending': 'bg-secondary',
            'running': 'bg-info',
            'completed': 'bg-success' if not self.has_critical_issues() else 'bg-danger',
            'failed': 'bg-danger',
            'cancelled': 'bg-warning',
            'timeout': 'bg-warning',
        }
        return badge_map.get(self.status, 'bg-secondary')

    def compare_with_previous_scan(self):
        """
        Compare this scan's vulnerabilities with the previous completed scan.

        Returns:
            dict: {
                'new': list of new vulnerability IDs,
                'resolved': list of resolved vulnerability IDs,
                'recurring': list of recurring vulnerability IDs
            }
        """
        # Get the previous completed scan
        previous_scan = SnykScan.objects.filter(
            status='completed',
            completed_at__lt=self.started_at
        ).order_by('-completed_at').first()

        if not previous_scan:
            # No previous scan to compare with
            current_vulns = self.vulnerabilities.get('vulnerabilities', [])
            current_ids = {v.get('id') for v in current_vulns if v.get('id')}
            return {
                'new': list(current_ids),
                'resolved': [],
                'recurring': []
            }

        # Extract vulnerability IDs from both scans
        current_vulns = self.vulnerabilities.get('vulnerabilities', [])
        previous_vulns = previous_scan.vulnerabilities.get('vulnerabilities', [])

        current_ids = {v.get('id') for v in current_vulns if v.get('id')}
        previous_ids = {v.get('id') for v in previous_vulns if v.get('id')}

        # Calculate differences
        new_ids = current_ids - previous_ids
        resolved_ids = previous_ids - current_ids
        recurring_ids = current_ids & previous_ids

        return {
            'new': list(new_ids),
            'resolved': list(resolved_ids),
            'recurring': list(recurring_ids)
        }

    def update_vulnerability_tracking(self):
        """Update the new/resolved/recurring vulnerability counts based on comparison with previous scan."""
        comparison = self.compare_with_previous_scan()

        self.new_vulnerabilities_count = len(comparison['new'])
        self.resolved_vulnerabilities_count = len(comparison['resolved'])
        self.recurring_vulnerabilities_count = len(comparison['recurring'])

        self.save(update_fields=[
            'new_vulnerabilities_count',
            'resolved_vulnerabilities_count',
            'recurring_vulnerabilities_count'
        ])

    def is_stuck(self, timeout_hours=2):
        """
        Check if scan is stuck (running/pending for too long).

        Args:
            timeout_hours: Hours after which a scan is considered stuck (default: 2)

        Returns:
            bool: True if scan is stuck
        """
        from django.utils import timezone
        from datetime import timedelta

        # Only check scans in pending or running state
        if self.status not in ['pending', 'running']:
            return False

        # Check if started_at is more than timeout_hours ago
        now = timezone.now()
        timeout_threshold = now - timedelta(hours=timeout_hours)

        return self.started_at < timeout_threshold

    def mark_as_timeout(self):
        """Mark this scan as timed out."""
        from django.utils import timezone

        self.status = 'timeout'
        self.completed_at = timezone.now()
        self.error_message = 'Scan timed out - took longer than expected to complete'

        # Calculate duration if not already set
        if not self.duration_seconds and self.started_at:
            duration = timezone.now() - self.started_at
            self.duration_seconds = int(duration.total_seconds())

        self.save(update_fields=['status', 'completed_at', 'error_message', 'duration_seconds'])

    @classmethod
    def cleanup_stuck_scans(cls, timeout_hours=2):
        """
        Find and mark all stuck scans as timed out.

        Args:
            timeout_hours: Hours after which a scan is considered stuck (default: 2)

        Returns:
            int: Number of scans marked as timed out
        """
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        timeout_threshold = now - timedelta(hours=timeout_hours)

        # Find all stuck scans
        stuck_scans = cls.objects.filter(
            status__in=['pending', 'running'],
            started_at__lt=timeout_threshold
        )

        count = 0
        for scan in stuck_scans:
            scan.mark_as_timeout()
            count += 1

        return count


class FirewallSettings(models.Model):
    """
    Global firewall settings (singleton).
    Controls IP-based and GeoIP-based access restrictions.
    """
    # IP Firewall
    ip_firewall_enabled = models.BooleanField(
        default=False,
        help_text='Enable IP-based firewall'
    )
    ip_firewall_mode = models.CharField(
        max_length=20,
        default='blocklist',
        choices=[
            ('allowlist', 'Allow List (block all except listed IPs)'),
            ('blocklist', 'Block List (allow all except listed IPs)'),
        ],
        help_text='Firewall operation mode'
    )

    # GeoIP Firewall
    geoip_firewall_enabled = models.BooleanField(
        default=False,
        help_text='Enable GeoIP country-based firewall'
    )
    geoip_firewall_mode = models.CharField(
        max_length=20,
        default='blocklist',
        choices=[
            ('allowlist', 'Allow List (block all except listed countries)'),
            ('blocklist', 'Block List (allow all except listed countries)'),
        ],
        help_text='GeoIP operation mode'
    )

    # Bypass settings
    bypass_for_staff = models.BooleanField(
        default=True,
        help_text='Allow staff users to bypass firewall rules'
    )
    bypass_for_api = models.BooleanField(
        default=False,
        help_text='Allow API requests to bypass firewall rules'
    )

    # Logging
    log_blocked_requests = models.BooleanField(
        default=True,
        help_text='Log all blocked requests to audit log'
    )

    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='firewall_settings_updates'
    )

    class Meta:
        db_table = 'firewall_settings'
        verbose_name = 'Firewall Settings'
        verbose_name_plural = 'Firewall Settings'

    def __str__(self):
        return f"Firewall Settings (Updated: {self.updated_at})"

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """Enforce singleton pattern."""
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of settings."""
        pass


class FirewallIPRule(models.Model):
    """
    IP address or IP range (CIDR) allow/block rule.
    """
    ip_address = models.CharField(
        max_length=50,
        help_text='IP address or CIDR range (e.g., 192.168.1.100 or 192.168.0.0/16)'
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional description (e.g., "Office Network", "VPN Gateway")'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Enable/disable this rule'
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ip_rules'
    )

    class Meta:
        db_table = 'firewall_ip_rules'
        ordering = ['ip_address']
        indexes = [
            models.Index(fields=['is_active', 'ip_address']),
        ]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        desc = f" - {self.description}" if self.description else ""
        return f"{self.ip_address}{desc} ({status})"

    def matches_ip(self, ip_address):
        """
        Check if the given IP address matches this rule.
        Supports both single IPs and CIDR ranges.
        """
        import ipaddress
        try:
            # Parse the rule (could be single IP or network)
            if '/' in self.ip_address:
                # CIDR notation
                network = ipaddress.ip_network(self.ip_address, strict=False)
                ip_obj = ipaddress.ip_address(ip_address)
                return ip_obj in network
            else:
                # Single IP address
                return self.ip_address == ip_address
        except (ValueError, ipaddress.AddressValueError):
            return False


class FirewallCountryRule(models.Model):
    """
    Country-based allow/block rule using GeoIP.
    """
    country_code = models.CharField(
        max_length=2,
        help_text='2-letter ISO country code (e.g., US, GB, CN)'
    )
    country_name = models.CharField(
        max_length=100,
        help_text='Country name for display'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Enable/disable this rule'
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_country_rules'
    )

    class Meta:
        db_table = 'firewall_country_rules'
        ordering = ['country_name']
        unique_together = [['country_code']]
        indexes = [
            models.Index(fields=['is_active', 'country_code']),
        ]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.country_name} ({self.country_code}) - {status}"


class FirewallLog(models.Model):
    """
    Log of blocked firewall requests for audit trail.
    """
    BLOCK_REASON_CHOICES = [
        ('country_blocklist', 'Country in blocklist'),
        ('country_not_in_allowlist', 'Country not in allowlist'),
        ('geoip_lookup_failed', 'GeoIP lookup failed'),
        ('ip_blocklist', 'IP in blocklist'),
        ('ip_not_in_allowlist', 'IP not in allowlist'),
    ]

    ip_address = models.GenericIPAddressField()
    country_code = models.CharField(max_length=2, blank=True)
    country_name = models.CharField(max_length=100, blank=True)
    block_reason = models.CharField(max_length=50, choices=BLOCK_REASON_CHOICES)
    request_path = models.CharField(max_length=500)
    request_method = models.CharField(max_length=10)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Optional user if authenticated
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='firewall_blocks'
    )

    class Meta:
        db_table = 'firewall_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['ip_address', '-timestamp']),
            models.Index(fields=['country_code', '-timestamp']),
        ]

    def __str__(self):
        return f"Blocked {self.ip_address} ({self.get_block_reason_display()}) at {self.timestamp}"
