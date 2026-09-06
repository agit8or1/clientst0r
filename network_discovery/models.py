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


# ---------------------------------------------------------------------------
# Phase 33.1 (v3.17.557) — persistent per-site collectors
# ---------------------------------------------------------------------------

class DiscoverySite(BaseModel):
    """A site running a collector on a schedule.

    Phase 32's token is single-use and expires in fifteen minutes, which is
    right for a technician standing at a machine and wrong for something that
    has to run every night unattended. This is the standing equivalent, and the
    difference is deliberate rather than a relaxation:

      * the key is **rotatable and revocable**, and rotation invalidates the old
        one the instant it happens;
      * it is scoped to one organization and one location, exactly like a
        Phase 32 token;
      * it can read **only its own scan configuration** and write **only**
        discovery results. It cannot read an asset, a password, a ticket, or
        another site's anything.

    That last point is what keeps this from being an RMM agent credential. A
    collector key that leaks tells the holder which subnets to sweep at one
    site, and lets them file device records there. It is not a way in.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='discovery_sites')
    location = models.ForeignKey(
        'locations.Location', on_delete=models.CASCADE,
        related_name='discovery_sites')

    name = models.CharField(
        max_length=120,
        help_text='What this collector is, e.g. "HQ closet Raspberry Pi".')

    key_hash = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='SHA-256 of the collector key. The plaintext is never stored.')
    key_rotated_at = models.DateTimeField(null=True, blank=True)

    is_enabled = models.BooleanField(
        default=True,
        help_text='Disable to stop a collector without deleting its history.')
    revoked_at = models.DateTimeField(null=True, blank=True)

    # --- what the collector is told to do ---
    subnets = models.JSONField(
        default=list, blank=True,
        help_text='CIDR ranges to sweep. Empty means "work it out locally", '
                  'the same behaviour as the Phase 32 script.')
    scan_interval_minutes = models.PositiveIntegerField(
        default=1440,
        help_text='How often the collector should scan. Daily by default; an '
                  'hourly sweep of a large site is mostly noise.')
    snmp_enabled = models.BooleanField(
        default=False,
        help_text='Read SNMP for neighbour and port data. Community strings '
                  'live in the vault, never here.')
    snmp_credential = models.ForeignKey(
        'vault.Password', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='discovery_sites',
        help_text='Vault entry holding the SNMP community or v3 credentials.')
    classify_enabled = models.BooleanField(
        default=False,
        help_text='Probe a handful of well-known ports to guess device types.')

    # --- what it has actually done ---
    last_seen_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Last time the collector asked for its configuration.')
    last_scan_at = models.DateTimeField(null=True, blank=True)
    last_source_ip = models.GenericIPAddressField(null=True, blank=True)
    collector_version = models.CharField(max_length=40, blank=True)

    # Phase 33.4 (v3.17.558) — on-demand scan. The collector polls; it does not
    # listen. So "scan now" is a flag it picks up on its next config fetch
    # rather than a push, which would mean an inbound connection to a box
    # inside a client's network — exactly the thing this design avoids.
    scan_requested_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set by an operator asking for a scan. Cleared when the '
                  'collector next fetches its configuration.')

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='discovery_sites_created')

    class Meta:
        db_table = 'network_discovery_sites'
        ordering = ['organization__name', 'name']
        unique_together = [['organization', 'location', 'name']]

    def __str__(self):
        return f'{self.name} ({self.location_id})'

    @classmethod
    def register(cls, *, organization, location, name, created_by=None, **kw):
        """Create a site and return `(site, plaintext_key)`."""
        raw = secrets.token_urlsafe(32)
        site = cls.objects.create(
            organization=organization, location=location,
            name=name[:120], key_hash=hash_token(raw),
            created_by=created_by, **kw)
        return site, raw

    @classmethod
    def find_usable(cls, raw: str):
        """The live site for this key, or None. Same silence as Phase 32 —
        disabled, revoked and unknown are one answer."""
        if not raw:
            return None
        site = cls.objects.filter(key_hash=hash_token(raw)).first()
        if site is None or not site.is_usable:
            return None
        return site

    @property
    def is_usable(self) -> bool:
        return self.is_enabled and self.revoked_at is None

    @property
    def state(self) -> str:
        if self.revoked_at is not None:
            return 'revoked'
        if not self.is_enabled:
            return 'disabled'
        return 'active'

    def rotate_key(self):
        """New key, old one dead immediately. Returns the plaintext once."""
        raw = secrets.token_urlsafe(32)
        self.key_hash = hash_token(raw)
        self.key_rotated_at = timezone.now()
        self.save(update_fields=['key_hash', 'key_rotated_at', 'updated_at'])
        return raw

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.is_enabled = False
            self.save(update_fields=['revoked_at', 'is_enabled', 'updated_at'])
        return self

    def note_checkin(self, *, source_ip=None, version=''):
        self.last_seen_at = timezone.now()
        self.last_source_ip = source_ip
        if version:
            self.collector_version = version[:40]
        self.save(update_fields=[
            'last_seen_at', 'last_source_ip', 'collector_version', 'updated_at'])

    @property
    def is_overdue(self) -> bool:
        """True when a collector has missed its window by a wide margin.

        Three intervals rather than one: a collector that is a few minutes late
        because a scan ran long is not a problem, and an alert that fires on
        that is an alert people learn to ignore.
        """
        if not self.is_usable or self.last_seen_at is None:
            return False
        grace = timezone.timedelta(
            minutes=max(1, self.scan_interval_minutes) * 3)
        return timezone.now() - self.last_seen_at > grace

    def request_scan(self):
        self.scan_requested_at = timezone.now()
        self.save(update_fields=['scan_requested_at', 'updated_at'])
        return self

    @property
    def scan_pending(self) -> bool:
        return self.scan_requested_at is not None

    def scan_config(self):
        """Exactly what the collector is allowed to know.

        Deliberately narrow: subnets, cadence and which probes to run. No asset
        data, no credentials — the SNMP secret is fetched by the collector from
        its own configuration store or passed at install time, never handed out
        by this endpoint.
        """
        return {
            'site_id': self.pk,
            'name': self.name,
            'subnets': self.subnets if isinstance(self.subnets, list) else [],
            'scan_interval_minutes': self.scan_interval_minutes,
            'snmp_enabled': self.snmp_enabled,
            'classify_enabled': self.classify_enabled,
            'scan_now': self.scan_pending,
        }


# ---------------------------------------------------------------------------
# Phase 33.2 (v3.17.558) — topology and switch-port correlation
# ---------------------------------------------------------------------------

class NetworkLink(models.Model):
    """One physical adjacency between two devices, learned from LLDP or CDP.

    Stored as a directed row (local device reported seeing remote device) but
    read as an undirected edge. Keeping the direction matters for provenance:
    when two switches disagree about a link, you want to know which one said
    what rather than a merged assertion neither would recognise.
    """
    SOURCE_CHOICES = [
        ('lldp', 'LLDP'),
        ('cdp', 'CDP'),
        ('manual', 'Entered by hand'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='network_links')
    location = models.ForeignKey(
        'locations.Location', on_delete=models.CASCADE,
        related_name='network_links')
    site = models.ForeignKey(
        DiscoverySite, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='links')

    local_asset = models.ForeignKey(
        'assets.Asset', on_delete=models.CASCADE,
        related_name='network_links_local')
    local_port = models.CharField(max_length=120, blank=True)

    # The far end often cannot be resolved to an asset — a neighbour that has
    # never been swept is a name and a MAC and nothing else. Recording it
    # unresolved is better than dropping the edge, because "there is something
    # on port 12 we do not manage" is exactly what a topology map should show.
    remote_asset = models.ForeignKey(
        'assets.Asset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='network_links_remote')
    remote_name = models.CharField(max_length=255, blank=True)
    remote_port = models.CharField(max_length=120, blank=True)
    remote_mac = models.CharField(max_length=32, blank=True)
    remote_description = models.CharField(max_length=255, blank=True)

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='lldp')
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'network_discovery_links'
        ordering = ['local_asset__name', 'local_port']
        unique_together = [['local_asset', 'local_port', 'remote_name', 'remote_port']]
        indexes = [
            models.Index(fields=['organization', 'location', '-last_seen_at'],
                         name='nd_link_org_loc_idx'),
        ]

    def __str__(self):
        return (f'{self.local_asset_id}:{self.local_port} → '
                f'{self.remote_name or self.remote_asset_id}:{self.remote_port}')

    @property
    def is_resolved(self) -> bool:
        return self.remote_asset_id is not None

    @property
    def remote_label(self) -> str:
        if self.remote_asset_id:
            return self.remote_asset.name
        return self.remote_name or self.remote_mac or 'unknown neighbour'


class SwitchPortEntry(models.Model):
    """What was seen on one switch port, in one VLAN, at one moment.

    Answers "which port is this device on", which is the question that
    otherwise costs a technician twenty minutes and a walk to the comms room.

    A port legitimately holds many MACs — an uplink carries everything behind
    it — so this is one row per (port, VLAN, MAC) rather than per port, and the
    uplink case is a fact to display rather than a conflict to resolve.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='switch_ports')
    location = models.ForeignKey(
        'locations.Location', on_delete=models.CASCADE,
        related_name='switch_ports')
    site = models.ForeignKey(
        DiscoverySite, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='switch_ports')

    switch_asset = models.ForeignKey(
        'assets.Asset', on_delete=models.CASCADE, related_name='switch_ports')
    port_name = models.CharField(max_length=120)
    vlan_id = models.PositiveIntegerField(null=True, blank=True)

    mac_address = models.CharField(max_length=32, db_index=True)
    # Filled in when the MAC can be tied to something known. Left empty rather
    # than guessed: a port entry with a wrong device attached is worse than one
    # with none.
    device_asset = models.ForeignKey(
        'assets.Asset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='switch_port_entries')
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'network_discovery_switch_ports'
        ordering = ['switch_asset__name', 'port_name', 'mac_address']
        unique_together = [['switch_asset', 'port_name', 'vlan_id', 'mac_address']]
        indexes = [
            models.Index(fields=['organization', 'mac_address'],
                         name='nd_port_org_mac_idx'),
        ]

    def __str__(self):
        return f'{self.switch_asset_id} {self.port_name} → {self.mac_address}'
