"""
API models - API keys with hashing
"""
import secrets
import hmac
import hashlib
from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from core.models import Organization, BaseModel
from accounts.models import Role


# Prefix for newly issued keys. Older keys start with the
# old product name (``itdocs_live_``) and keep working: a key is looked up by
# the HMAC of the whole plaintext, never by its prefix, so the prefix carries
# no meaning for verification.
API_KEY_PREFIX = 'cst_live_'
LEGACY_API_KEY_PREFIXES = ('itdocs_live_',)


def generate_api_key():
    """
    Generate a random API key.
    Format: cst_live_<32 random bytes hex>
    """
    random_part = secrets.token_hex(32)
    return f"{API_KEY_PREFIX}{random_part}"


def hash_api_key(api_key):
    """
    Hash API key using HMAC-SHA256 with server secret.
    """
    secret = settings.API_KEY_SECRET.encode('utf-8')
    key_bytes = api_key.encode('utf-8')
    return hmac.new(secret, key_bytes, hashlib.sha256).hexdigest()


def get_key_prefix(api_key):
    """
    Extract prefix from API key for identification.
    Returns first 12 characters.
    """
    return api_key[:12] if len(api_key) >= 12 else api_key


class APIKeyScope(models.TextChoices):
    """
    Multi-organization reach of an API key (issue #134).

    - SINGLE      (default, legacy): the key may only ever read/write its
      home `organization`. 100% backward-compatible — every key that
      existed before this field was added is SINGLE.
    - DESCENDANTS: the home organization plus any sub-location under it via
      the `Organization.parent` hierarchy (Phase 18).
    - ALL:         every organization the key's *owner* is entitled to —
      all active orgs for an MSP staff user / superuser, or the owner's
      active memberships for a regular org user. This is the
      single-pane-of-glass / multi-client mode.

    A key's effective reach is always bounded by what its owner can already
    access; the scope never grants access the user themselves lacks.
    """
    SINGLE = 'single', 'Single organization'
    DESCENDANTS = 'descendants', 'Organization + sub-locations'
    ALL = 'all', 'All accessible organizations'


class APIKey(BaseModel):
    """
    API key for programmatic access.
    Key is hashed using HMAC-SHA256 and only prefix is stored in plaintext.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='api_keys')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    name = models.CharField(max_length=100, help_text="Descriptive name for this API key")

    # Only store hashed key and prefix
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    key_prefix = models.CharField(max_length=20)

    # Permissions
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READONLY)

    # Multi-org reach (issue #134). Defaults to SINGLE so existing keys are
    # unchanged.
    scope = models.CharField(
        max_length=20, choices=APIKeyScope.choices, default=APIKeyScope.SINGLE,
        help_text="Which organizations this key can address",
    )

    # Status
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)

    # Lifecycle (v3.17.714, roadmap 81.4). No expiry and no own limit keep the
    # behaviour of keys made before.
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="The key stops working at this time")
    rate_limit_per_minute = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Requests per minute for this key; empty uses the standard API limits")
    rotated_from = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='rotated_to',
        help_text="The key this one replaced")
    rotated_at = models.DateTimeField(null=True, blank=True,
                                      help_text="When this key was replaced by a new one")
    # Mutual TLS (v3.17.718, roadmap 81.8): when set, requests with this key
    # must present this client certificate, verified by a trusted proxy.
    client_cert_sha256 = models.CharField(
        max_length=64, blank=True, default='',
        help_text="SHA-256 fingerprint of the client certificate this key requires")

    class Meta:
        db_table = 'api_keys'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    @property
    def is_expired(self):
        from django.utils import timezone
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def expires_soon(self):
        """Within 14 days of expiry (and not yet expired)."""
        from datetime import timedelta
        from django.utils import timezone
        return bool(self.expires_at and not self.is_expired
                    and self.expires_at <= timezone.now() + timedelta(days=14))

    @classmethod
    def create_key(cls, organization, user, name, role=Role.READONLY,
                   scope=APIKeyScope.SINGLE):
        """
        Create new API key and return the plaintext key (only time it's available).
        Returns tuple: (api_key_object, plaintext_key)
        """
        plaintext_key = generate_api_key()
        key_hash = hash_api_key(plaintext_key)
        key_prefix = get_key_prefix(plaintext_key)

        api_key = cls.objects.create(
            organization=organization,
            user=user,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            role=role,
            scope=scope,
        )

        return api_key, plaintext_key

    @classmethod
    def verify_key(cls, plaintext_key):
        """
        Verify API key and return APIKey object if valid.
        Returns None if invalid. Uses timing-safe comparison to prevent
        timing-based enumeration of valid key hashes.
        """
        import hmac as _hmac
        key_hash = hash_api_key(plaintext_key)
        try:
            api_key = cls.objects.select_related('organization', 'user').get(
                key_hash=key_hash,
                is_active=True,
                user__is_active=True,
            )
            return api_key
        except cls.DoesNotExist:
            # Constant-time pad to prevent timing side-channel on hash lookup
            _hmac.compare_digest(key_hash, 'x' * len(key_hash))
            return None
