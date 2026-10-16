"""
Mobile API bearer tokens, stored hashed.

The mobile app signs in once and then carries an opaque token in the
``Authorization: Token <key>`` header (the header format the shipped app
already uses). Until v3.17.611 that token was a DRF ``authtoken.Token``:
one per user, stored raw, so a database read yielded working credentials
and logging out on one phone signed every phone out.

Now each sign-in issues its own token. Only an HMAC of it is stored
(``vault.secret_fields.hash_token``, the same keying as API keys and
browser-extension tokens), so the value is returned to the app exactly
once. Each token is independently revocable; ``revoke_all_for`` ends every
mobile session of a user.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from vault.secret_fields import hash_token


class MobileAuthToken(models.Model):
    HASH_PURPOSE = 'api_mobile.token'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='mobile_auth_tokens')
    key_hash = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='HMAC-SHA256 of the token. The token itself is returned to '
                  'the app once and never stored.')
    key_prefix = models.CharField(
        max_length=12, blank=True,
        help_text='First characters of the token, for identification only.')
    device_label = models.CharField(
        max_length=120, blank=True,
        help_text='What signed in, e.g. the app/platform reported at login.')
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Optional hard expiry. Empty = valid until revoked.')
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'api_mobile_auth_tokens'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user} — {self.device_label or "mobile"} ({self.key_prefix}…)'

    # ------------------------------------------------------------------
    @classmethod
    def hash(cls, raw: str) -> str:
        return hash_token(raw, cls.HASH_PURPOSE)

    @classmethod
    def issue(cls, user, *, device_label='', ttl_days=None):
        """Create a token. Returns (raw_token, row); the raw token is not kept."""
        raw = secrets.token_urlsafe(32)
        ttl_days = ttl_days if ttl_days is not None else getattr(
            settings, 'MOBILE_TOKEN_TTL_DAYS', None)
        row = cls.objects.create(
            user=user,
            key_hash=cls.hash(raw),
            key_prefix=raw[:8],
            device_label=(device_label or '')[:120],
            expires_at=(timezone.now() + timedelta(days=int(ttl_days))) if ttl_days else None,
        )
        return raw, row

    @classmethod
    def lookup(cls, raw: str):
        """Row for a presented token (active or not), or None."""
        if not raw:
            return None
        return (cls.objects.select_related('user')
                .filter(key_hash=cls.hash(raw)).first())

    @classmethod
    def active_for(cls, user):
        """Unrevoked, unexpired tokens of `user`, newest first."""
        return (cls.objects.filter(user=user, revoked_at__isnull=True)
                .filter(models.Q(expires_at__isnull=True)
                        | models.Q(expires_at__gt=timezone.now())))

    @classmethod
    def revoke_all_for(cls, user) -> int:
        """End every mobile session of `user`. Returns how many were active."""
        return cls.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now())

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])

    def touch(self):
        """Bump last_used_at, at most once a minute (one write per request
        would be a write on every mobile API call)."""
        now = timezone.now()
        if self.last_used_at is None or now - self.last_used_at > timedelta(seconds=60):
            type(self).objects.filter(pk=self.pk).update(last_used_at=now)
            self.last_used_at = now
