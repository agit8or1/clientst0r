"""
Phase 32 (v3.17.556) — remote network discovery import.

A technician generates a script, runs it on a Windows host inside a client's
network, and the results come back as Asset records. The whole design is shaped
by one constraint from the roadmap, worth restating because every decision here
follows from it:

    do not turn this into an RMM agent: no persistent agents, no permanent API
    keys, no exploit scanning.

So the credential the script carries is short-lived, single-use, scoped to one
organization *and* one location, write-only, revocable, and stored hashed. It
can add inventory to exactly one place and read nothing at all. If it leaks, the
worst it does is let someone file device records against one client site until
it expires — which is why every use is audit-logged with its source IP.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets

from django.conf import settings as django_settings
from django.db import models
from django.utils import timezone

from core.models import BaseModel, Organization

# 15 minutes. Long enough to walk to a machine and run a script, short enough
# that a token left in a chat log is worthless by the time anyone finds it.
DEFAULT_TOKEN_TTL_MINUTES = 15

# A plausible upper bound for one site's sweep. Past this the payload is more
# likely a mistake or an attempt to fill the table than a real network.
MAX_DEVICES_PER_UPLOAD = 5000


def hash_token(raw: str) -> str:
    """SHA-256 of the plaintext token.

    Plain SHA-256 rather than a password hash on purpose: this is a 43-character
    value from `secrets`, not a human-chosen password, so there is no dictionary
    to slow down and a fast hash keeps the upload endpoint cheap enough to rate
    limit meaningfully.
    """
    return hashlib.sha256((raw or '').encode('utf-8')).hexdigest()


def normalise_mac(value: str) -> str:
    """`AA-BB-CC-DD-EE-FF`, or '' if it is not a MAC.

    Windows reports MACs in at least three formats depending on whether they
    came from `arp -a`, `Get-NetNeighbor` or WMI. Deduplication matches on this
    field, so a device arriving in two formats would otherwise be imported
    twice.
    """
    if not value:
        return ''
    cleaned = re.sub(r'[^0-9A-Fa-f]', '', str(value))
    if len(cleaned) != 12:
        return ''
    cleaned = cleaned.upper()
    return '-'.join(cleaned[i:i + 2] for i in range(0, 12, 2))


def valid_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(str(value)), ipaddress.IPv4Address)
    except (ValueError, TypeError):
        return False


class NetworkDiscoveryToken(BaseModel):
    """A one-shot credential for uploading one site's discovery results.

    The plaintext is shown once, at generation, and never again — only its hash
    is stored. There is deliberately no way to recover it: a token you can
    re-read is a token that lives in the database as a working credential, which
    is the thing this design is avoiding.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='network_discovery_tokens')
    location = models.ForeignKey(
        'locations.Location', on_delete=models.CASCADE,
        related_name='network_discovery_tokens')

    token_hash = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='SHA-256 of the token. The plaintext is never stored.')

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='network_discovery_tokens_created')

    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(
        null=True, blank=True, help_text='First successful use.')

    max_uses = models.PositiveIntegerField(
        default=1,
        help_text='Single-use by default. A sweep that has to be re-run gets a '
                  'new token rather than a reusable one.')
    use_count = models.PositiveIntegerField(default=0)

    source_ip_last_used = models.GenericIPAddressField(null=True, blank=True)
    user_agent_last_used = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'network_discovery_tokens'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'location', '-created_at'],
                         name='nd_token_org_loc_idx'),
        ]

    def __str__(self):
        return f'discovery token for {self.location_id} ({self.state})'

    # --- lifecycle ---

    @classmethod
    def issue(cls, *, organization, location, created_by=None,
              ttl_minutes=DEFAULT_TOKEN_TTL_MINUTES, max_uses=1, notes=''):
        """Create a token and return `(token_row, plaintext)`.

        The plaintext is returned to the caller and nowhere else. Whoever calls
        this is responsible for showing it once; there is no second chance.
        """
        raw = secrets.token_urlsafe(32)
        token = cls.objects.create(
            organization=organization,
            location=location,
            created_by=created_by,
            token_hash=hash_token(raw),
            expires_at=timezone.now() + timezone.timedelta(
                minutes=max(1, int(ttl_minutes or DEFAULT_TOKEN_TTL_MINUTES))),
            max_uses=max(1, int(max_uses or 1)),
            notes=(notes or '')[:255],
        )
        return token, raw

    @classmethod
    def find_usable(cls, raw: str):
        """The live token matching this plaintext, or None.

        Looks up by hash, so an unknown token and a wrong token are the same
        query. Every rejection reason returns None rather than a message: the
        upload endpoint must not tell an anonymous caller whether a token exists
        but is expired, or never existed at all.
        """
        if not raw:
            return None
        token = cls.objects.filter(token_hash=hash_token(raw)).first()
        if token is None or not token.is_usable:
            return None
        return token

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_spent(self) -> bool:
        return self.use_count >= self.max_uses

    @property
    def is_usable(self) -> bool:
        return not (self.is_revoked or self.is_expired or self.is_spent)

    @property
    def state(self) -> str:
        """One word for the UI. Order matters: a revoked token that has also
        expired is described as revoked, because that is the fact somebody
        acted on."""
        if self.is_revoked:
            return 'revoked'
        if self.is_spent:
            return 'used'
        if self.is_expired:
            return 'expired'
        return 'active'

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at', 'updated_at'])
        return self

    def record_use(self, *, source_ip=None, user_agent=''):
        self.use_count += 1
        if self.used_at is None:
            self.used_at = timezone.now()
        self.source_ip_last_used = source_ip
        self.user_agent_last_used = (user_agent or '')[:255]
        self.save(update_fields=[
            'use_count', 'used_at', 'source_ip_last_used',
            'user_agent_last_used', 'updated_at',
        ])
        return self


class NetworkDiscoveryImport(models.Model):
    """One upload from one run of the script."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='network_discovery_imports')
    location = models.ForeignKey(
        'locations.Location', on_delete=models.CASCADE,
        related_name='network_discovery_imports')
    token = models.ForeignKey(
        NetworkDiscoveryToken, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='imports',
        help_text='The token used. SET_NULL so an import survives a token purge.')

    uploaded_by_user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='network_discovery_imports',
        help_text='Whoever generated the token. The upload itself is '
                  'unauthenticated, so this is attribution, not identity.')
    source_ip = models.GenericIPAddressField(null=True, blank=True)

    device_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    is_dry_run = models.BooleanField(
        default=False,
        help_text='A preview: results were parsed and matched but nothing was '
                  'written to the asset register.')

    raw_payload = models.JSONField(
        default=dict, blank=True,
        help_text='Summarised submission. Not the full device list — that is '
                  'in the result rows.')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'network_discovery_imports'
        ordering = ['-created_at']

    def __str__(self):
        return f'import #{self.pk} ({self.device_count} devices)'


class NetworkDiscoveryAssetResult(models.Model):
    """What happened to one discovered device.

    Kept per device rather than only as counters so "why was that switch
    skipped" has an answer three weeks later.
    """
    STATUS_CHOICES = [
        ('created', 'Created a new asset'),
        ('updated', 'Updated an existing asset'),
        ('matched', 'Matched an existing asset; nothing to change'),
        ('skipped', 'Skipped'),
        ('error', 'Error'),
        ('preview', 'Preview only — nothing written'),
    ]

    discovery_import = models.ForeignKey(
        NetworkDiscoveryImport, on_delete=models.CASCADE, related_name='results')
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='network_discovery_results')
    location = models.ForeignKey(
        'locations.Location', on_delete=models.CASCADE,
        related_name='network_discovery_results')
    asset = models.ForeignKey(
        'assets.Asset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='network_discovery_results')

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mac_address = models.CharField(max_length=32, blank=True)
    hostname = models.CharField(max_length=255, blank=True)
    vendor = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=60, blank=True)
    discovery_method = models.CharField(max_length=60, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    detail = models.CharField(max_length=255, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'network_discovery_asset_results'
        ordering = ['ip_address', 'id']

    def __str__(self):
        return f'{self.ip_address or self.mac_address or "?"} → {self.status}'
