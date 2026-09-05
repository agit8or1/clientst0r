"""
Phase 34.1 (v3.17.544) — versioned network device configuration backups.

The routine this replaces is exporting a firewall config to a file, dropping it
in a folder, and never diffing it against anything. So the two things that
matter most here are that a snapshot is *stored immutably* and that any two
snapshots can be *compared*.

Collection over SSH is Sub-phase 34.2. This sub-phase deliberately works with
nothing but a paste box, because a config pasted by hand is worth versioning and
waiting for device credentials before storing anything would be the wrong order.
"""
import difflib
import hashlib

from django.contrib.auth.models import User
from django.db import models

from assets.models import Asset
from core.models import BaseModel, Organization


class ConfigBackup(models.Model):
    """One captured configuration, immutable once written.

    Not a `BaseModel`: a snapshot is a statement about what a device's config
    was at a moment in time. An `updated_at` would imply editing one is normal,
    and editing one destroys the only thing it is for.

    Identical consecutive captures are **not** stored again — see
    `record_for_asset`. A daily backup of a device nobody touches for a year
    should be one row plus a moving `last_seen_at`, not 365 copies of the same
    text.
    """
    SOURCE_CHOICES = [
        ('manual', 'Pasted or uploaded by hand'),
        ('ssh', 'Collected over SSH'),
        ('scp', 'Collected over SCP'),
        ('api', 'Collected from a vendor API'),
        ('import', 'Imported from another system'),
    ]

    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name='config_backups')
    # Denormalised so a backup can still be scoped after an asset moves org,
    # and so listing by org does not need a join through assets.
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='config_backups')

    body = models.TextField(help_text='The configuration text as captured.')
    content_hash = models.CharField(
        max_length=64, db_index=True,
        help_text='SHA-256 of the body. Used to detect an unchanged config.')

    captured_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(
        help_text='Most recent capture that produced this exact config. A '
                  'device left alone moves this rather than writing a copy.')

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    firmware_version = models.CharField(
        max_length=120, blank=True,
        help_text='Running firmware at capture time, when the device reports it.')

    # Phase 34.3 will diff against the approved snapshot to classify drift.
    # The field lives here from the start so approving one is not a migration
    # away when that lands.
    is_approved = models.BooleanField(
        default=False,
        help_text='Marks this as the known-good configuration to compare against.')

    captured_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='config_backups_captured')
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'netconfig_backups'
        ordering = ['-captured_at']
        indexes = [
            models.Index(fields=['asset', '-captured_at'],
                         name='netcfg_asset_time_idx'),
        ]

    def __str__(self):
        return f'{self.asset_id} @ {self.captured_at:%Y-%m-%d %H:%M}'

    # --- Capture ---

    @staticmethod
    def hash_body(body: str) -> str:
        # Trailing whitespace and line-ending churn are not config changes.
        # Normalising here rather than at display time means a device that
        # switches from CRLF to LF does not read as "everything changed".
        normalised = '\n'.join(line.rstrip() for line in (body or '').splitlines())
        return hashlib.sha256(normalised.encode('utf-8')).hexdigest()

    @classmethod
    def record_for_asset(cls, asset, body, *, source='manual', captured_at=None,
                         firmware_version='', captured_by=None, note=''):
        """Store a capture, or note that nothing changed.

        Returns `(backup, created)`. When the newest existing snapshot has the
        same content hash, `last_seen_at` moves and `created` is False — the
        device was reachable and its config is unchanged, which is information
        worth keeping without another copy of the text.
        """
        from django.utils import timezone

        captured_at = captured_at or timezone.now()
        digest = cls.hash_body(body)

        latest = cls.objects.filter(asset=asset).order_by('-captured_at').first()
        if latest is not None and latest.content_hash == digest:
            if captured_at > latest.last_seen_at:
                latest.last_seen_at = captured_at
                latest.save(update_fields=['last_seen_at'])
            return latest, False

        backup = cls.objects.create(
            asset=asset,
            organization_id=asset.organization_id,
            body=body or '',
            content_hash=digest,
            captured_at=captured_at,
            last_seen_at=captured_at,
            source=source,
            firmware_version=firmware_version or '',
            captured_by=captured_by,
            note=note or '',
        )
        return backup, True

    # --- Comparison ---

    @property
    def line_count(self) -> int:
        return len(self.body.splitlines()) if self.body else 0

    def previous(self):
        """The snapshot immediately before this one for the same device."""
        return (ConfigBackup.objects
                .filter(asset_id=self.asset_id, captured_at__lt=self.captured_at)
                .order_by('-captured_at')
                .first())

    def diff_against(self, other):
        """Unified diff from `other` to `self`, as a list of lines.

        `other` is the older side. Passing None returns an empty diff rather
        than raising — the first capture of a device has nothing to compare
        against, and that is a normal state, not an error.
        """
        if other is None:
            return []
        return list(difflib.unified_diff(
            (other.body or '').splitlines(),
            (self.body or '').splitlines(),
            fromfile=f'{other.captured_at:%Y-%m-%d %H:%M}',
            tofile=f'{self.captured_at:%Y-%m-%d %H:%M}',
            lineterm='',
        ))

    def diff_stats(self, other):
        """`{added, removed}` line counts against `other`."""
        added = removed = 0
        for line in self.diff_against(other):
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1
        return {'added': added, 'removed': removed}

    @property
    def changed_from_previous(self) -> bool:
        prev = self.previous()
        return prev is not None and prev.content_hash != self.content_hash
