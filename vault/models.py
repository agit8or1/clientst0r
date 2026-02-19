"""
Vault models - Password storage with encryption
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager
from .encryption_v2 import (
    encrypt_password, decrypt_password,
    encrypt_totp_secret, decrypt_totp_secret,
    encrypt_v2, decrypt_v2,
    KEY_CONTEXT_GENERIC,
    EncryptionError
)


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
        ('api_key', 'API Key'),
        ('credit_card', 'Credit Card'),
        ('database', 'Database'),
        ('email', 'Email Account'),
        ('ftp', 'FTP/SFTP'),
        ('network_device', 'Network Device'),
        ('otp', 'OTP/TOTP (2FA)'),
        ('other', 'Other'),
        ('server', 'Server/VPS'),
        ('software_license', 'Software License'),
        ('ssh_key', 'SSH Key'),
        ('vpn', 'VPN'),
        ('website', 'Website Login'),
        ('wifi', 'WiFi Network'),
        ('windows_ad', 'Windows/Active Directory'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='passwords')
    folder = models.ForeignKey(PasswordFolder, on_delete=models.SET_NULL, null=True, blank=True, related_name='passwords', help_text='Password folder for organization')
    title = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=2000, blank=True)
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

    # Password strength (0-100, calculated on save)
    strength_score = models.IntegerField(default=0, help_text='Password strength score (0=weak, 100=strong)')

    # My Vault (personal passwords)
    is_personal = models.BooleanField(default=False, help_text='Personal password (My Vault)')
    personal_owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='personal_passwords')

    # Metadata
    tags = models.ManyToManyField(Tag, blank=True, related_name='passwords')
    custom_fields = models.JSONField(default=dict, blank=True, help_text='Additional custom data (e.g., breach scan frequency)')
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
        Encrypt and store password using v2 encryption with AAD context.
        Includes organization ID but NOT password ID (since it may not exist yet).
        This ensures AAD remains consistent between encryption and decryption.
        Also calculates and stores password strength score.
        """
        from .utils import calculate_password_strength

        self.encrypted_password = encrypt_password(
            plaintext_password,
            org_id=self.organization_id,
            password_id=None  # Don't use ID in AAD to avoid mismatch on create
        )

        # Calculate and store password strength
        strength_result = calculate_password_strength(plaintext_password)
        self.strength_score = strength_result['score']

    def get_password(self):
        """
        Decrypt and return password using v2 encryption with AAD verification.
        Falls back to v1 decryption for legacy passwords.
        """
        return decrypt_password(
            self.encrypted_password,
            org_id=self.organization_id,
            password_id=None  # Match encryption: don't use ID in AAD
        )

    def set_otp_secret(self, plaintext_secret):
        """
        Encrypt and store OTP secret using TOTP-specific encryption context.
        """
        self.otp_secret = encrypt_totp_secret(
            plaintext_secret,
            org_id=self.organization_id
        )

    def get_otp_secret(self):
        """
        Decrypt and return OTP secret using TOTP-specific decryption context.
        Falls back to v1 decryption for legacy secrets.
        """
        if not self.otp_secret:
            return None
        return decrypt_totp_secret(
            self.otp_secret,
            org_id=self.organization_id
        )

    def generate_otp(self):
        """
        Generate current TOTP code.
        Returns dict with code and seconds until expiry, or None if no secret.
        Returns error dict if generation fails.
        """
        import logging
        logger = logging.getLogger('vault')

        if not self.otp_secret:
            return None

        import pyotp
        import time
        import urllib.parse

        try:
            secret = self.get_otp_secret()
            if not secret:
                return None

            # Handle otpauth:// URI format from Bitwarden
            if secret.startswith('otpauth://'):
                logger.debug(f"Password {self.id}: TOTP secret is otpauth:// URI, parsing...")
                logger.debug(f"Password {self.id}: Full URI: {secret[:100]}...")  # Log first 100 chars
                try:
                    parsed = urllib.parse.urlparse(secret)
                    params = urllib.parse.parse_qs(parsed.query)
                    logger.debug(f"Password {self.id}: Parsed parameters: {list(params.keys())}")
                    if 'secret' in params:
                        secret = params['secret'][0]
                        logger.info(f"Password {self.id}: Extracted secret from otpauth:// URI")
                    else:
                        logger.error(f"Password {self.id}: otpauth:// URI missing 'secret' parameter. Available params: {list(params.keys())}")
                        return {
                            'error': True,
                            'message': f'Invalid TOTP URI format (missing secret parameter). Found: {", ".join(params.keys()) if params else "no parameters"}'
                        }
                except Exception as e:
                    logger.error(f"Password {self.id}: Failed to parse otpauth:// URI: {e}")
                    return {
                        'error': True,
                        'message': f'Failed to parse TOTP URI: {str(e)}'
                    }

            # Clean the secret (remove spaces, ensure uppercase)
            secret = secret.strip().replace(' ', '').replace('-', '').upper()

            # Validate base32 format
            try:
                import base64
                base64.b32decode(secret)
            except Exception as e:
                logger.error(f"Password {self.id}: Invalid base32 secret: {e}")
                return {
                    'error': True,
                    'message': 'Invalid TOTP secret format (not valid base32)'
                }

            totp = pyotp.TOTP(secret)
            code = totp.now()

            # Calculate seconds until next code
            current_time = time.time()
            time_remaining = 30 - (int(current_time) % 30)

            return {
                'code': code,
                'time_remaining': time_remaining,
                'issuer': self.otp_issuer or self.title
            }

        except Exception as e:
            logger.error(f"Password {self.id} ({self.title}): OTP generation failed: {e}", exc_info=True)
            return {
                'error': True,
                'message': f'OTP generation error: {str(e)}'
            }

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

    @property
    def password_status(self):
        """
        Get password status: 'breached', 'weak', or 'safe'.
        Priority: breached > weak > safe
        """
        # Check if breached first (highest priority)
        if self.is_breached:
            return 'breached'

        # Check if weak (strength score < 50)
        if self.strength_score < 50:
            return 'weak'

        # Otherwise it's safe
        return 'safe'

    @property
    def password_status_display(self):
        """Get user-friendly display label for password status."""
        status_labels = {
            'breached': 'Breached',
            'weak': 'Weak',
            'safe': 'Safe'
        }
        return status_labels.get(self.password_status, 'Unknown')

    @property
    def password_status_color(self):
        """Get Bootstrap color class for password status."""
        status_colors = {
            'breached': 'danger',
            'weak': 'warning',
            'safe': 'success'
        }
        return status_colors.get(self.password_status, 'secondary')

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
        """
        Encrypt and store content using v2 encryption.
        Uses user ID as context for user-specific encryption.
        """
        self.encrypted_content = encrypt_v2(
            plaintext_content,
            context=KEY_CONTEXT_GENERIC,
            org_id=None,  # Personal vault is not org-scoped
            record_type='personal_vault',
            record_id=self.user_id
        )

    def get_content(self):
        """
        Decrypt and return content using v2 encryption.
        Falls back to v1 decryption for legacy content.
        """
        if not self.encrypted_content:
            return ''
        return decrypt_v2(
            self.encrypted_content,
            context=KEY_CONTEXT_GENERIC,
            org_id=None,
            record_type='personal_vault',
            record_id=self.user_id
        )


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
