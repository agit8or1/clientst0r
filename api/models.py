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


def generate_api_key():
    """
    Generate a random API key.
    Format: itdocs_live_<32 random bytes hex>
    """
    random_part = secrets.token_hex(32)
    return f"itdocs_live_{random_part}"


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

    # Status
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'api_keys'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    @classmethod
    def create_key(cls, organization, user, name, role=Role.READONLY):
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
            role=role
        )

        return api_key, plaintext_key

    @classmethod
    def verify_key(cls, plaintext_key):
        """
        Verify API key and return APIKey object if valid.
        Returns None if invalid.
        """
        key_hash = hash_api_key(plaintext_key)
        try:
            api_key = cls.objects.select_related('organization', 'user').get(
                key_hash=key_hash,
                is_active=True
            )
            return api_key
        except cls.DoesNotExist:
            return None
