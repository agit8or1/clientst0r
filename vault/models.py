"""
Vault models - Password storage with encryption
"""
from django.conf import settings as django_settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Organization, Tag, BaseModel
from core.utils import OrganizationManager
from .secret_fields import EncryptedTextField, hash_token
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

    license_key = EncryptedTextField(blank=True, help_text='Software license key (encrypted at rest)')

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

    # Phase 37 (v3.17.241): per-credential approval gate. When True, the
    # `password_reveal` endpoint requires an approved VaultRevealRequest
    # (or a break-glass override) before it returns the plaintext.
    requires_reveal_approval = models.BooleanField(
        default=False,
        help_text='When set, revealing this password requires an approved '
                  'VaultRevealRequest (or an explicit break-glass override) '
                  'rather than just the requester\'s permissions.',
    )
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
        Falls back to v1 decryption for legacy secrets, or returns plaintext if stored unencrypted.
        """
        import logging
        logger = logging.getLogger('vault')

        if not self.otp_secret:
            return None

        # Check if it's stored as plaintext (migration case - old imports stored otpauth:// URIs unencrypted)
        if self.otp_secret.startswith('otpauth://'):
            logger.warning(f"Password {self.id}: TOTP secret is stored as plaintext otpauth:// URI, re-encrypting...")
            plaintext_secret = self.otp_secret
            # Re-encrypt it properly for future use
            try:
                self.set_otp_secret(plaintext_secret)
                self.save(update_fields=['otp_secret'])
                logger.info(f"Password {self.id}: TOTP secret re-encrypted successfully")
            except Exception as e:
                logger.error(f"Password {self.id}: Failed to re-encrypt TOTP secret: {e}")
            return plaintext_secret  # Return the plaintext URI for parsing

        # Check for corrupted encrypted data (less than minimum viable length)
        try:
            import base64
            encrypted_bytes = base64.b64decode(self.otp_secret)
            if len(encrypted_bytes) < 28:  # Minimum: 12 (nonce) + 16 (tag for empty plaintext)
                logger.error(f"Password {self.id}: TOTP secret is corrupted (only {len(encrypted_bytes)} bytes, expected 28+)")
                logger.error(f"Password {self.id}: This appears to be incomplete encrypted data from a failed import")
                # Mark the field as corrupted so it can be identified
                return None
        except Exception as e:
            logger.warning(f"Password {self.id}: Could not check encrypted data length: {e}")

        try:
            logger.debug(f"Password {self.id}: Attempting TOTP decryption with org_id={self.organization_id}")
            return decrypt_totp_secret(
                self.otp_secret,
                org_id=self.organization_id
            )
        except Exception as e:
            logger.error(f"Password {self.id}: TOTP decryption failed: {e}", exc_info=True)
            raise

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

            # Clean the secret (remove spaces, dashes, underscores)
            secret = secret.strip().replace(' ', '').replace('-', '').replace('_', '').upper()

            # Handle URL encoding (e.g., %3D for =)
            if '%' in secret:
                logger.debug(f"Password {self.id}: Secret contains URL encoding, decoding...")
                import urllib.parse
                try:
                    secret = urllib.parse.unquote(secret)
                    logger.info(f"Password {self.id}: URL-decoded secret")
                except Exception as e:
                    logger.warning(f"Password {self.id}: URL decode failed: {e}")

            # Log secret characteristics (without exposing the full secret)
            # Length only: any slice of a TOTP seed is part of the secret.
            logger.debug(f"Password {self.id}: Secret length={len(secret)}")

            # Add base32 padding if needed (must be multiple of 8)
            padding_needed = len(secret) % 8
            if padding_needed:
                secret += '=' * (8 - padding_needed)
                logger.debug(f"Password {self.id}: Added {8 - padding_needed} characters of base32 padding")

            # Validate base32 format
            try:
                import base64
                base64.b32decode(secret)
            except Exception as e:
                # Check for common issues
                invalid_chars = set(c for c in secret if c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=')
                if invalid_chars:
                    logger.error(f"Password {self.id}: Secret contains invalid base32 characters: {invalid_chars}")
                    return {
                        'error': True,
                        'message': f'Invalid TOTP secret: contains invalid characters ({", ".join(sorted(invalid_chars))})'
                    }
                else:
                    logger.error(f"Password {self.id}: Invalid base32 secret: {e}")
                    return {
                        'error': True,
                        'message': f'Invalid TOTP secret format (base32 decode error: {str(e)[:50]})'
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


# ---------------------------------------------------------------------------
# Client portal access — extends Password with portal-visibility flags.
# Defined as a separate "extension" to avoid touching Password's main field
# layout. Migrations add the columns onto the password table directly.
# ---------------------------------------------------------------------------

# These fields are attached via add_to_class so existing Password rows
# remain untouched; only new behaviour is layered on.

CLIENT_ACCESS_MODES = [
    ('none', 'Staff only — never shown in client portal'),
    ('all_org', 'All members of the client organization'),
    ('specific_users', 'Specific portal users (explicit list)'),
    ('org_admin_managed', 'Delegated — the client org admin manages access'),
]


Password.add_to_class(
    'client_visible',
    models.BooleanField(
        default=False,
        help_text='If False, this password never appears in the customer portal — '
                  'regardless of access mode.',
    ),
)
Password.add_to_class(
    'client_access_mode',
    models.CharField(
        max_length=20, choices=CLIENT_ACCESS_MODES, default='none',
        help_text='Who within the client org can see this password in the portal.',
    ),
)
Password.add_to_class(
    'client_allowed_users',
    models.ManyToManyField(
        User, blank=True, related_name='vault_passwords_granted',
        help_text='Explicit user list — only honoured when access_mode="specific_users".',
    ),
)


def password_visible_to_portal_user(self, user):
    """Return True if `user` should see this password in the customer portal.

    Rules:
      * `is_personal=True` is never portal-visible
      * `client_visible=False` is never portal-visible
      * Mode `none`            → False
      * Mode `all_org`         → user has Membership in this Password.organization
      * Mode `specific_users`  → user in `client_allowed_users` AND has Membership
      * Mode `org_admin_managed` → handled like `specific_users` (the org_admin
        is responsible for adding users to `client_allowed_users`)

    Always denies if the user has no active membership in this org.
    """
    if not user or not user.is_authenticated or self.is_personal or not self.client_visible:
        return False
    try:
        from accounts.models import Membership
        is_member = Membership.objects.filter(
            user=user, organization=self.organization, is_active=True,
        ).exists()
    except Exception:
        is_member = False
    if not is_member:
        return False
    mode = self.client_access_mode or 'none'
    if mode == 'all_org':
        return True
    if mode in ('specific_users', 'org_admin_managed'):
        return self.client_allowed_users.filter(pk=user.pk).exists()
    return False


Password.add_to_class('visible_to_portal_user', password_visible_to_portal_user)


# ---------------------------------------------------------------------------
# VaultAccessRule (v3.17.163) — GeoIP / IP / time-of-day access gates for
# vault Passwords. Decision engine lives in `vault/access_rules.py`.
# ---------------------------------------------------------------------------


class VaultAccessRule(models.Model):
    """
    Access rule that gates a vault Password's reveal/view based on
    the requester's GeoIP country, source IP / CIDR, and current time.

    Rules are scoped to one of: a specific Password, a specific User,
    or an Organization. Multiple rules can apply -- DENY rules win,
    then highest-priority ALLOW. If no rule matches, default is ALLOW
    (back-compat with installs that have no rules configured).
    """
    SCOPE_CHOICES = [
        ('item', 'Specific Password'),
        ('user', 'Specific User'),
        ('organization', 'Organization'),
    ]
    EFFECT_CHOICES = [
        ('allow', 'Allow access'),
        ('deny', 'Deny access'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='vault_access_rules',
        help_text='Tenant that owns the rule. For organization-scoped '
                  'rules this is also the target.',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(
        default=100,
        help_text='Lower number = checked first.',
    )
    effect = models.CharField(
        max_length=20, choices=EFFECT_CHOICES, default='allow',
    )

    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    target_password = models.ForeignKey(
        'vault.Password', on_delete=models.CASCADE, null=True, blank=True,
        related_name='access_rules',
        help_text='Required when scope=item.',
    )
    target_user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='vault_access_rules',
        help_text='Required when scope=user.',
    )
    # scope=organization uses the `organization` FK above

    # GeoIP restrictions -- list of ISO 3166-1 alpha-2 codes
    allowed_countries = models.JSONField(
        default=list, blank=True,
        help_text='ISO codes that pass. Empty = no country restriction. '
                  'Example: ["US", "CA", "GB"].',
    )
    blocked_countries = models.JSONField(
        default=list, blank=True,
        help_text='ISO codes that fail (overrides allowed_countries).',
    )

    # IP restrictions -- list of CIDR strings
    allowed_cidrs = models.JSONField(
        default=list, blank=True,
        help_text='Source IP CIDRs that pass. Empty = no IP restriction. '
                  'Example: ["10.0.0.0/8", "203.0.113.0/24"].',
    )
    blocked_cidrs = models.JSONField(
        default=list, blank=True,
        help_text='Source IP CIDRs that fail (overrides allowed_cidrs).',
    )

    # Time-of-day restrictions
    allowed_weekdays = models.JSONField(
        default=list, blank=True,
        help_text='List of weekday integers 0=Monday .. 6=Sunday. '
                  'Empty = all days allowed.',
    )
    allowed_hour_start = models.TimeField(
        null=True, blank=True,
        help_text='Earliest hour (in `timezone`) that access is allowed. '
                  'Blank = no time floor.',
    )
    allowed_hour_end = models.TimeField(
        null=True, blank=True,
        help_text='Latest hour. Blank = no time ceiling.',
    )
    timezone = models.CharField(
        max_length=60, default='UTC',
        help_text='IANA timezone name for the time window.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        db_table = 'vault_access_rules'
        ordering = ['priority', '-updated_at']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['scope', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_scope_display()} - {self.get_effect_display()})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.scope == 'item' and not self.target_password_id:
            raise ValidationError({'target_password': 'Required when scope=item.'})
        if self.scope == 'user' and not self.target_user_id:
            raise ValidationError({'target_user': 'Required when scope=user.'})
        if self.allowed_hour_start and self.allowed_hour_end and \
                self.allowed_hour_end <= self.allowed_hour_start:
            raise ValidationError({
                'allowed_hour_end': 'End time must be after start time.',
            })

    def matches_target(self, password, user):
        """True if this rule's scope-target matches (password, user)."""
        if self.scope == 'item':
            return self.target_password_id == password.pk
        if self.scope == 'user':
            return user is not None and self.target_user_id == user.pk
        if self.scope == 'organization':
            return self.organization_id == password.organization_id
        return False


class VaultRevealRequest(models.Model):
    """
    Phase 37 (v3.17.241): a request from a user to reveal a password
    that has `requires_reveal_approval=True`. Either approved by an
    admin (normal flow) or self-approved with `is_break_glass=True`
    and a mandatory justification (emergency flow).
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ]

    password = models.ForeignKey(
        Password, on_delete=models.CASCADE, related_name='reveal_requests',
    )
    requester = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='vault_reveal_requests',
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    justification = models.TextField(
        help_text='Why the requester needs to reveal this password.',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    decided_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='vault_reveal_decisions',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True)

    is_break_glass = models.BooleanField(
        default=False,
        help_text='True when the requester self-approved via the emergency '
                  'break-glass flow. Logs harder + auto-notifies admins.',
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the approved reveal window closes. Default: 1 hour '
                  'after approval. Reveals after this point require a fresh request.',
    )
    revealed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the requester actually revealed the password using '
                  'this approval. Single-use (cleared on use).',
    )

    class Meta:
        db_table = 'vault_reveal_requests'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['password', 'status']),
            models.Index(fields=['requester', '-requested_at']),
            models.Index(fields=['status', 'expires_at']),
        ]

    def __str__(self):
        flag = ' (break-glass)' if self.is_break_glass else ''
        return f'{self.requester.username} → {self.password.title}{flag} [{self.status}]'

    @property
    def is_currently_valid(self) -> bool:
        """True if this approval can be used to reveal right now."""
        if self.status != 'approved':
            return False
        if self.revealed_at is not None:
            return False  # single-use
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def approve(self, *, user, notes='', window_minutes=60):
        from datetime import timedelta as _td
        self.status = 'approved'
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_notes = (notes or '')[:5000]
        self.expires_at = self.decided_at + _td(minutes=window_minutes)
        self.save(update_fields=['status', 'decided_by', 'decided_at',
                                  'decision_notes', 'expires_at'])

    def deny(self, *, user, notes=''):
        self.status = 'denied'
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_notes = (notes or '')[:5000]
        self.save(update_fields=['status', 'decided_by', 'decided_at',
                                  'decision_notes'])

    def mark_revealed(self):
        self.revealed_at = timezone.now()
        self.save(update_fields=['revealed_at'])


# ---------------------------------------------------------------------------
# WebExtensionAuthToken (Phase 28 — v3.17.327) — short-lived bearer tokens
# scoped to browser-extension sessions. Extensions never carry the user's
# Django session cookie; they exchange the user's password for a token via
# the Settings UI, then send `Authorization: Bearer <token>` on every API
# call. Tokens are revocable, expire automatically, and carry an optional
# organization pin for cross-org-aware extensions.
# ---------------------------------------------------------------------------


class WebExtensionAuthToken(models.Model):
    """
    Bearer-auth token issued to a browser-extension installation. One user
    can have multiple tokens (e.g. Chrome on Mac + Firefox on a different
    machine); each is independently revocable.

    Fields:
      * user            — owning user (membership scope is resolved at call
                          time via the standard org middleware).
      * organization    — optional pin; when set, the token only resolves
                          requests whose `X-Organization-Id` header matches
                          (or is omitted, in which case the pinned org is
                          used). When None, the extension can switch orgs
                          freely (still constrained by user memberships).
      * token_hash      — HMAC-SHA256 of the bearer token (see
                          `vault.secret_fields.hash_token`). The token itself
                          is returned once at issue and never stored, so a
                          database read does not yield working credentials.
      * token_prefix    — first characters of the token, for display only.
      * label           — user-supplied free text ("Chrome on Mac"). Helps
                          the user identify which extension to revoke.
      * created_at      — issue timestamp.
      * last_used_at    — bumped on every authenticated extension call so
                          the user can see "last seen 5 minutes ago".
      * expires_at      — hard expiry. Tokens past this point cannot
                          authenticate even if not explicitly revoked.
      * revoked_at      — explicit revocation timestamp. Once set, the
                          token is permanently dead.
    """
    DEFAULT_TTL_DAYS = 30

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='extension_tokens',
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True,
        related_name='extension_tokens',
        help_text='Optional organization pin. NULL = token honours the '
                  'X-Organization-Id header per request.',
    )
    token_hash = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='HMAC-SHA256 of the bearer token. The token itself is '
                  'returned to the extension once and never stored.',
    )
    token_prefix = models.CharField(
        max_length=12, blank=True,
        help_text='First characters of the token, for identification only.',
    )
    label = models.CharField(
        max_length=120, blank=True,
        help_text='User-friendly label (e.g. "Chrome on Mac").',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        help_text='Hard expiry. Tokens past this point cannot authenticate.',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'vault_webextension_tokens'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f'{self.user.username} — {self.label or "extension"}'

    @classmethod
    def issue(cls, *, user, organization=None, label='', ttl_days=None):
        """
        Issue a new token. Returns the (unsaved-token-string, model_row)
        tuple so the view can return the secret to the client exactly once.
        """
        import secrets
        from datetime import timedelta as _td
        ttl = ttl_days or cls.DEFAULT_TTL_DAYS
        token_str = secrets.token_urlsafe(32)
        row = cls.objects.create(
            user=user,
            organization=organization,
            token_hash=cls.hash(token_str),
            token_prefix=token_str[:8],
            label=(label or '')[:120],
            expires_at=timezone.now() + _td(days=ttl),
        )
        return token_str, row

    HASH_PURPOSE = 'vault.webextension'

    @classmethod
    def hash(cls, raw_token):
        return hash_token(raw_token, cls.HASH_PURPOSE)

    @classmethod
    def lookup(cls, raw_token):
        """Row for a presented bearer token, or None."""
        if not raw_token:
            return None
        return (cls.objects.select_related('user', 'organization')
                .filter(token_hash=cls.hash(raw_token)).first())

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def touch(self):
        """Bump last_used_at to now. Cheap single-field save."""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])
