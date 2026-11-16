"""
Customer backup monitoring.

Not the platform's own pre-upgrade backups (that is the `backups` app, which
this module never touches). These models record what customers' backup
products report: jobs, runs, repositories, the alerts derived from them, and
restore tests, which are tracked separately from backup success on purpose:
a backup that ran proves nothing about whether it can be restored.

Tenancy: every data row carries `organization`, the customer whose data it is
(the boundary views filter on). A connection's `organization` is the owner
that configured it; `customer` optionally pins everything it discovers to one
customer, otherwise discovered systems start at the owner and are reassigned
in the UI.
"""
import json
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from vault.secret_fields import SealedTextField

PROVIDER_PBS = 'pbs'
PROVIDER_RESTIC = 'restic'
PROVIDER_BORG = 'borg'
PROVIDER_KOPIA = 'kopia'
PROVIDER_CHOICES = [
    (PROVIDER_PBS, 'Proxmox Backup Server'),
    (PROVIDER_RESTIC, 'restic (push reports)'),
    (PROVIDER_BORG, 'BorgBackup (push reports)'),
    (PROVIDER_KOPIA, 'Kopia (push reports)'),
]

RUN_SUCCESS, RUN_WARNING, RUN_FAILED, RUN_MISSED, RUN_RUNNING = (
    'success', 'warning', 'failed', 'missed', 'running')
RUN_STATUS_CHOICES = [
    (RUN_SUCCESS, 'Success'), (RUN_WARNING, 'Warning'), (RUN_FAILED, 'Failed'),
    (RUN_MISSED, 'Missed'), (RUN_RUNNING, 'Running'),
]


class BackupConnection(models.Model):
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='backup_connections',
                                     help_text='The organization that owns this connection.')
    customer = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='backup_connections_for_customer',
                                 help_text='Optional: pin everything this connection reports to one customer.')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    name = models.CharField(max_length=120)
    # JSON blob, e.g. {"api_token": "user@realm!token:secret"}. Never echoed.
    credentials = SealedTextField(blank=True)
    base_url = models.URLField(blank=True, help_text='e.g. https://pbs.example.com:8007 (API providers only).')
    verify_tls = models.BooleanField(default=True)

    # Push (ingest) providers: public id in the URL, secret signs the body.
    ingest_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ingest_secret = SealedTextField(blank=True)
    last_ingest_at = models.DateTimeField(null=True, blank=True)

    last_poll_at = models.DateTimeField(null=True, blank=True,
                                        help_text='Last successful contact (poll or accepted report).')
    last_poll_attempt_at = models.DateTimeField(null=True, blank=True)
    last_poll_status = models.CharField(max_length=20, blank=True, help_text='ok / error')
    last_poll_error = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'

    @property
    def is_push(self):
        from .providers import is_push_provider
        return is_push_provider(self.provider)

    @property
    def default_customer(self):
        return self.customer or self.organization

    def get_credentials(self):
        field = self._meta.get_field('credentials')
        try:
            return field.unseal_json(self.credentials)
        except Exception:
            return {}

    def set_credentials(self, data):
        self.credentials = self._meta.get_field('credentials').seal_json(data or {})

    def issue_ingest_secret(self):
        """New signing secret. Returned once; only the sealed copy is kept."""
        raw = secrets.token_urlsafe(32)
        self.ingest_secret = self._meta.get_field('ingest_secret').seal(raw)
        self.issued_ingest_secret = raw
        return raw

    def get_ingest_secret(self):
        if not self.ingest_secret:
            return ''
        try:
            return self._meta.get_field('ingest_secret').unseal_text(self.ingest_secret)
        except Exception:
            return ''


class ProtectedSystem(models.Model):
    connection = models.ForeignKey(BackupConnection, on_delete=models.CASCADE, related_name='systems')
    customer = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                 related_name='backup_protected_systems')
    asset = models.ForeignKey('assets.Asset', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='backup_systems')
    name = models.CharField(max_length=255)
    external_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'], name='uniq_bm_system')]

    def __str__(self):
        return self.name


class BackupJob(models.Model):
    connection = models.ForeignKey(BackupConnection, on_delete=models.CASCADE, related_name='jobs')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='backup_jobs',
                                     help_text='The customer whose data this job protects.')
    system = models.ForeignKey(ProtectedSystem, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='jobs')
    external_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    schedule = models.CharField(max_length=255, blank=True)
    retention = models.CharField(max_length=255, blank=True)
    expected_interval_hours = models.PositiveIntegerField(
        null=True, blank=True, help_text='Overrides the policy "missed" threshold for this job.')
    # Denormalised from the runs (maintained by ingest.record_run).
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=10, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'], name='uniq_bm_job')]

    def __str__(self):
        return self.name


class BackupRun(models.Model):
    job = models.ForeignKey(BackupJob, on_delete=models.CASCADE, related_name='runs')
    connection = models.ForeignKey(BackupConnection, on_delete=models.CASCADE, related_name='runs')
    external_id = models.CharField(max_length=255)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=RUN_STATUS_CHOICES)
    bytes_processed = models.BigIntegerField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at']
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'], name='uniq_bm_run')]
        indexes = [models.Index(fields=['job', '-started_at'])]

    def __str__(self):
        return f'{self.job.name} {self.started_at:%Y-%m-%d %H:%M} {self.status}'


class BackupRepository(models.Model):
    connection = models.ForeignKey(BackupConnection, on_delete=models.CASCADE, related_name='repositories')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='backup_repositories')
    external_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    total_bytes = models.BigIntegerField(null=True, blank=True)
    used_bytes = models.BigIntegerField(null=True, blank=True)
    available = models.BooleanField(default=True)
    message = models.CharField(max_length=500, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'], name='uniq_bm_repo')]

    def __str__(self):
        return self.name

    @property
    def used_pct(self):
        if not self.total_bytes or self.used_bytes is None:
            return None
        return round(100.0 * self.used_bytes / self.total_bytes, 1)


class RestoreTest(models.Model):
    """A restore somebody actually performed (or an imported record of one).
    Deliberately not derived from backup runs."""
    RESULT_PASSED, RESULT_PARTIAL, RESULT_FAILED = 'passed', 'partial', 'failed'
    RESULT_CHOICES = [(RESULT_PASSED, 'Passed'), (RESULT_PARTIAL, 'Partial'), (RESULT_FAILED, 'Failed')]
    SOURCE_CHOICES = [('manual', 'Recorded manually'), ('imported', 'Imported')]

    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='backup_restore_tests')
    system = models.ForeignKey(ProtectedSystem, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='restore_tests')
    system_name = models.CharField(max_length=255, blank=True,
                                   help_text='Used when the system is not one of the monitored systems.')
    tested_on = models.DateField()
    result = models.CharField(max_length=10, choices=RESULT_CHOICES)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    verified_by_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-tested_on', '-pk']

    def __str__(self):
        return f'{self.system_name or self.system} restore {self.tested_on} {self.result}'

    @property
    def label(self):
        return self.system.name if self.system_id else self.system_name


class BackupAlertPolicy(models.Model):
    """Thresholds. One per organization; the row with organization NULL is the
    default for organizations without their own."""
    organization = models.OneToOneField('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='backup_alert_policy')
    missed_threshold_hours = models.PositiveIntegerField(default=26,
        help_text='Alert when a job has no successful run for this long.')
    consecutive_failures = models.PositiveIntegerField(default=2,
        help_text='Alert when the last N runs of a job all failed.')
    capacity_pct = models.PositiveIntegerField(default=85, help_text='Alert when a repository is this full.')
    alert_missing_protected_device = models.BooleanField(default=True,
        help_text='Alert when a protected system has no backup job.')
    restore_test_max_age_days = models.PositiveIntegerField(default=180,
        help_text='Restore tests older than this are shown as overdue.')
    auto_ticket = models.BooleanField(default=False,
        help_text='Open a PSA ticket for each new warning/critical alert (one per alert, never duplicated).')
    updated_at = models.DateTimeField(auto_now=True)

    DEFAULTS = dict(missed_threshold_hours=26, consecutive_failures=2, capacity_pct=85,
                    alert_missing_protected_device=True, restore_test_max_age_days=180, auto_ticket=False)

    class Meta:
        verbose_name_plural = 'backup alert policies'

    def __str__(self):
        return f'Backup alert policy ({self.organization or "default"})'

    @classmethod
    def for_org(cls, organization):
        row = None
        if organization is not None:
            row = cls.objects.filter(organization=organization).first()
        return row or cls.objects.filter(organization__isnull=True).first() or cls(**cls.DEFAULTS)


ALERT_KINDS = [
    ('missed', 'Missed backup'),
    ('failed', 'Backup failed'),
    ('repeated_failures', 'Repeated failures'),
    ('capacity', 'Repository capacity'),
    ('repo_unavailable', 'Repository unavailable'),
    ('no_job', 'Protected system has no job'),
    ('stale', 'No recent data from connection'),
]
ALERT_OPEN, ALERT_ACK, ALERT_RESOLVED = 'open', 'acknowledged', 'resolved'
ALERT_STATUS_CHOICES = [(ALERT_OPEN, 'Open'), (ALERT_ACK, 'Acknowledged'), (ALERT_RESOLVED, 'Resolved')]
SEVERITY_CHOICES = [('warning', 'Warning'), ('critical', 'Critical')]


class BackupAlert(models.Model):
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='backup_alerts')
    connection = models.ForeignKey(BackupConnection, on_delete=models.CASCADE, related_name='alerts')
    job = models.ForeignKey(BackupJob, on_delete=models.CASCADE, null=True, blank=True, related_name='alerts')
    system = models.ForeignKey(ProtectedSystem, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='alerts')
    repository = models.ForeignKey(BackupRepository, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='alerts')
    kind = models.CharField(max_length=20, choices=ALERT_KINDS)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='warning')
    status = models.CharField(max_length=15, choices=ALERT_STATUS_CHOICES, default=ALERT_OPEN)
    title = models.CharField(max_length=300)
    detail = models.TextField(blank=True)
    dedup_key = models.CharField(max_length=300)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    occurrences = models.PositiveIntegerField(default=1)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                        blank=True, related_name='+')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='+')

    class Meta:
        ordering = ['-last_seen_at']
        constraints = [
            # One live alert per (connection, key): a re-poll updates it.
            models.UniqueConstraint(fields=['connection', 'dedup_key'],
                                    condition=Q(status__in=['open', 'acknowledged']),
                                    name='uniq_bm_live_alert'),
        ]
        indexes = [models.Index(fields=['organization', 'status'])]

    def __str__(self):
        return self.title

    @property
    def is_live(self):
        return self.status != ALERT_RESOLVED
