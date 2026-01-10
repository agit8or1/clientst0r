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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    def __str__(self):
        return self.name

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
        ('documented_by', 'Documented By'),
        ('credentials', 'Credentials'),
        ('applies_to', 'Applies To'),
        ('related_to', 'Related To'),
        ('responsible_for', 'Responsible For'),
        ('depends_on', 'Depends On'),
        ('contains', 'Contains'),
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
        ('website_monitoring', 'Website Monitoring Checks'),
        ('psa_sync', 'PSA Synchronization'),
        ('ssl_expiry_check', 'SSL Certificate Expiry Check'),
        ('domain_expiry_check', 'Domain Expiry Check'),
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
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('running', 'Running'),
            ('pending', 'Pending'),
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
        ]

        for task_data in defaults:
            task, created = cls.objects.get_or_create(
                task_type=task_data['task_type'],
                defaults=task_data
            )
            if created:
                task.calculate_next_run()
