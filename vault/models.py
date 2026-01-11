"""
Vault models - Password storage with encryption
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager
from .encryption import encrypt, decrypt


class PasswordFolder(BaseModel):
    """
    Folder for organizing passwords within an organization.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='password_folders')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='subfolders')
    color = models.CharField(max_length=7, default='#6c757d', help_text='Hex color for folder icon')
    icon = models.CharField(max_length=50, default='fa-folder', help_text='FontAwesome icon class')

    objects = OrganizationManager()

    class Meta:
        db_table = 'password_folders'
        ordering = ['name']
        unique_together = [['organization', 'name', 'parent']]
        indexes = [
            models.Index(fields=['organization', 'parent']),
        ]

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} / {self.name}"
        return self.name

    @property
    def full_path(self):
        """Get full folder path."""
        if self.parent:
            return f"{self.parent.full_path} / {self.name}"
        return self.name

    @property
    def password_count(self):
        """Count passwords in this folder (including subfolders)."""
        count = self.passwords.count()
        for subfolder in self.subfolders.all():
            count += subfolder.password_count
        return count


class Password(BaseModel):
    """
    Password vault entry with encrypted secret.
    Never stores plaintext passwords.
    """
    PASSWORD_TYPES = [
        ('website', 'Website Login'),
        ('email', 'Email Account'),
        ('windows_ad', 'Windows/Active Directory'),
        ('database', 'Database'),
        ('ssh_key', 'SSH Key'),
        ('api_key', 'API Key'),
        ('otp', 'OTP/TOTP (2FA)'),
        ('credit_card', 'Credit Card'),
        ('network_device', 'Network Device'),
        ('server', 'Server/VPS'),
        ('ftp', 'FTP/SFTP'),
        ('vpn', 'VPN'),
        ('wifi', 'WiFi Network'),
        ('software_license', 'Software License'),
        ('other', 'Other'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='passwords')
    folder = models.ForeignKey(PasswordFolder, on_delete=models.SET_NULL, null=True, blank=True, related_name='passwords', help_text='Password folder for organization')
    title = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)

    # Type of password entry
    password_type = models.CharField(max_length=20, choices=PASSWORD_TYPES, default='website')

    # Encrypted fields (stored as base64 nonce||ciphertext)
    encrypted_password = models.TextField()

    # Type-specific fields
    email_server = models.CharField(max_length=255, blank=True, help_text='Email server (IMAP/SMTP)')
    email_port = models.CharField(max_length=10, blank=True, help_text='Email port')

    domain = models.CharField(max_length=255, blank=True, help_text='Domain name for Windows/AD')

    database_type = models.CharField(max_length=50, blank=True, help_text='Database type (MySQL, PostgreSQL, etc.)')
    database_host = models.CharField(max_length=255, blank=True, help_text='Database hostname')
    database_port = models.CharField(max_length=10, blank=True, help_text='Database port')
    database_name = models.CharField(max_length=255, blank=True, help_text='Database name')

    ssh_host = models.CharField(max_length=255, blank=True, help_text='SSH hostname/IP')
    ssh_port = models.CharField(max_length=10, blank=True, default='22', help_text='SSH port')

    license_key = models.TextField(blank=True, help_text='Software license key')

    # OTP/TOTP fields
    otp_secret = models.TextField(blank=True, help_text='Encrypted TOTP secret')
    otp_issuer = models.CharField(max_length=255, blank=True)

    # Expiration tracking
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Password expiration date')
    expiry_notification_sent = models.BooleanField(default=False)

    # My Vault (personal passwords)
    is_personal = models.BooleanField(default=False, help_text='Personal password (My Vault)')
    personal_owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='personal_passwords')

    # Metadata
    tags = models.ManyToManyField(Tag, blank=True, related_name='passwords')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='passwords_created')
    last_modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='passwords_modified')

    # Organization-scoped manager
    objects = OrganizationManager()

    class Meta:
        db_table = 'passwords'
        ordering = ['title']
        indexes = [
            models.Index(fields=['organization', 'title']),
        ]

    def __str__(self):
        return f"{self.title} ({self.organization.slug})"

    def set_password(self, plaintext_password):
        """
        Encrypt and store password.
        """
        self.encrypted_password = encrypt(plaintext_password)

    def get_password(self):
        """
        Decrypt and return password.
        """
        return decrypt(self.encrypted_password)

    def set_otp_secret(self, plaintext_secret):
        """
        Encrypt and store OTP secret.
        """
        self.otp_secret = encrypt(plaintext_secret)

    def get_otp_secret(self):
        """
        Decrypt and return OTP secret.
        """
        if not self.otp_secret:
            return None
        return decrypt(self.otp_secret)

    def generate_otp(self):
        """
        Generate current TOTP code.
        """
        if not self.otp_secret or self.password_type != 'otp':
            return None

        import pyotp
        secret = self.get_otp_secret()
        totp = pyotp.TOTP(secret)
        return totp.now()

    @property
    def is_expired(self):
        """Check if password has expired."""
        if not self.expires_at:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def days_until_expiration(self):
        """Days until password expires."""
        if not self.expires_at:
            return None
        from django.utils import timezone
        delta = self.expires_at - timezone.now()
        return delta.days

    def save(self, *args, **kwargs):
        # Ensure password is never stored in plaintext
        if hasattr(self, '_plaintext_password'):
            self.set_password(self._plaintext_password)
            delattr(self, '_plaintext_password')
        super().save(*args, **kwargs)


class PasswordRelation(BaseModel):
    """
    Generic relation linking passwords to other entities (assets, docs, etc).
    """
    RELATION_TYPES = [
        ('asset', 'Asset'),
        ('document', 'Document'),
        ('contact', 'Contact'),
        ('integration', 'Integration'),
    ]

    password = models.ForeignKey(Password, on_delete=models.CASCADE, related_name='relations')
    relation_type = models.CharField(max_length=50, choices=RELATION_TYPES)
    relation_id = models.PositiveIntegerField()

    class Meta:
        db_table = 'password_relations'
        unique_together = [['password', 'relation_type', 'relation_id']]
        indexes = [
            models.Index(fields=['relation_type', 'relation_id']),
        ]

    def __str__(self):
        return f"{self.password.title} -> {self.relation_type}:{self.relation_id}"


class PersonalVault(BaseModel):
    """
    User-specific encrypted vault for personal quick notes.
    Each user has their own vault with user-specific encryption.
    Not tied to any organization - purely personal.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='personal_vault_items')
    title = models.CharField(max_length=255)

    # Encrypted content
    encrypted_content = models.TextField()

    # Optional metadata (not encrypted)
    category = models.CharField(max_length=100, blank=True, help_text="Optional: Organize, Notes, Snippets, etc.")

    # Quick access favorites
    is_favorite = models.BooleanField(default=False)

    class Meta:
        db_table = 'personal_vault'
        ordering = ['-is_favorite', '-updated_at']
        indexes = [
            models.Index(fields=['user', 'title']),
            models.Index(fields=['user', 'is_favorite']),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.title}"

    def set_content(self, plaintext_content):
        """Encrypt and store content."""
        self.encrypted_content = encrypt(plaintext_content)

    def get_content(self):
        """Decrypt and return content."""
        if not self.encrypted_content:
            return ''
        return decrypt(self.encrypted_content)


class PasswordBreachCheck(BaseModel):
    """
    Track password breach check results from HaveIBeenPwned.
    Stores historical breach checks for each password.
    """
    password = models.ForeignKey(
        Password,
        on_delete=models.CASCADE,
        related_name='breach_checks'
    )
    checked_at = models.DateTimeField(auto_now_add=True)
    is_breached = models.BooleanField(default=False)
    breach_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of times password found in breaches'
    )
    breach_source = models.CharField(
        max_length=50,
        default='haveibeenpwned',
        help_text='Source of breach data'
    )

    objects = OrganizationManager()

    class Meta:
        db_table = 'password_breach_checks'
        ordering = ['-checked_at']
        indexes = [
            models.Index(fields=['password', '-checked_at']),
            models.Index(fields=['is_breached']),
        ]

    def __str__(self):
        status = "BREACHED" if self.is_breached else "Safe"
        return f"{self.password.title} - {status} ({self.checked_at})"


# Add helper methods to Password model
def get_latest_breach_check(self):
    """Get most recent breach check result."""
    return self.breach_checks.first()


def is_breached(self):
    """Check if password is currently marked as breached."""
    latest = self.get_latest_breach_check()
    return latest and latest.is_breached


# Attach methods to Password model
Password.get_latest_breach_check = get_latest_breach_check
Password.is_breached = property(is_breached)
