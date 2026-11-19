"""Shared operational event layer (roadmap Phase 82).

Each alert source keeps its own model (security alerts, RMM alerts, Rem0te
alerts, backup alerts, website monitors). This app holds a normalized copy of
each — one OperationalEvent per source alert or outage — plus one link table to
incidents and tickets, a bounded work queue and per-source ingestion health.
The Operations Center, wallboards, correlation, notifications and reports read
this layer; the sources stay authoritative.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

SOURCE_SECURITY = 'security_alert'
SOURCE_RMM = 'rmm'
SOURCE_REM0TE = 'rem0te'
SOURCE_BACKUP = 'backup'
SOURCE_MONITOR = 'monitor'
SOURCES = (
    (SOURCE_SECURITY, 'Security alerts (vendors and SIEM)'),
    (SOURCE_RMM, 'RMM alerts'),
    (SOURCE_REM0TE, 'Rem0te alerts'),
    (SOURCE_BACKUP, 'Backup alerts'),
    (SOURCE_MONITOR, 'Website monitors'),
)

SEVERITIES = (('critical', 'Critical'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('info', 'Info'))
SEVERITY_RANK = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}

STATUS_OPEN = 'open'
STATUS_ACK = 'acknowledged'
STATUS_RESOLVED = 'resolved'
STATUS_SUPPRESSED = 'suppressed'
STATUSES = ((STATUS_OPEN, 'Open'), (STATUS_ACK, 'Acknowledged'), (STATUS_RESOLVED, 'Resolved'),
            (STATUS_SUPPRESSED, 'Suppressed'))

RAW_MAX_BYTES = 8 * 1024


class OperationalEvent(models.Model):
    """The normalized envelope (82.1). One row per source alert / outage."""
    organization = models.ForeignKey('core.Organization', null=True, blank=True, on_delete=models.CASCADE,
                                     related_name='operational_events',
                                     help_text='The customer; empty = MSP-wide or not yet mapped')
    source = models.CharField(max_length=20, choices=SOURCES)
    source_id = models.PositiveBigIntegerField(help_text='Primary key of the source row')
    connection_label = models.CharField(max_length=160, blank=True, default='')
    vendor_event_id = models.CharField(max_length=200, blank=True, default='')
    event_type = models.CharField(max_length=120, blank=True, default='')
    title = models.CharField(max_length=300)
    severity = models.CharField(max_length=10, choices=SEVERITIES, default='medium')
    source_severity = models.CharField(max_length=20, blank=True, default='')
    confidence = models.PositiveSmallIntegerField(null=True, blank=True, help_text='0–100 when the source says')
    status = models.CharField(max_length=15, choices=STATUSES, default=STATUS_OPEN)
    source_status = models.CharField(max_length=20, blank=True, default='')
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    occurrences = models.PositiveIntegerField(default=1)
    rule_name = models.CharField(max_length=200, blank=True, default='')
    asset = models.ForeignKey('assets.Asset', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    asset_hint = models.CharField(max_length=200, blank=True, default='')
    source_address = models.GenericIPAddressField(null=True, blank=True)
    destination_address = models.GenericIPAddressField(null=True, blank=True)
    account = models.CharField(max_length=200, blank=True, default='')
    mitre_techniques = models.JSONField(default=list, blank=True)
    iocs = models.JSONField(default=list, blank=True)
    dedup_key = models.CharField(max_length=300)
    correlation_group = models.CharField(max_length=120, blank=True, default='', db_index=True)
    raw = models.JSONField(default=dict, blank=True, help_text=f'Size-capped copy of the source payload '
                                                               f'({RAW_MAX_BYTES // 1024} KB)')
    created_at = models.DateTimeField(auto_now_add=True)
    projected_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'events_operational_events'
        ordering = ['-last_seen_at']
        constraints = [models.UniqueConstraint(fields=['source', 'dedup_key'], name='uniq_event_source_dedup')]
        indexes = [
            models.Index(fields=['organization', 'status', '-last_seen_at']),
            models.Index(fields=['source', 'source_id']),
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['-last_seen_at']),
        ]

    def __str__(self):
        return f'{self.get_source_display()}: {self.title}'

    @property
    def is_live(self):
        return self.status in (STATUS_OPEN, STATUS_ACK)


class EventLink(models.Model):
    """One alert ↔ incident ↔ ticket link (82.2). Lifecycles stay separate."""
    ORIGIN_SOURCE = 'source'
    ORIGIN_MANUAL = 'manual'
    event = models.ForeignKey(OperationalEvent, on_delete=models.CASCADE, related_name='links')
    incident = models.ForeignKey('security_alerts.SecurityIncident', null=True, blank=True,
                                 on_delete=models.CASCADE, related_name='event_links')
    ticket = models.ForeignKey('psa.Ticket', null=True, blank=True, on_delete=models.CASCADE,
                               related_name='event_links')
    origin = models.CharField(max_length=10, default=ORIGIN_SOURCE,
                              choices=((ORIGIN_SOURCE, 'From the source'), (ORIGIN_MANUAL, 'Linked by a person')))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'events_links'
        constraints = [
            models.UniqueConstraint(fields=['event', 'ticket'], condition=models.Q(ticket__isnull=False),
                                    name='uniq_event_ticket_link'),
            models.UniqueConstraint(fields=['event', 'incident'], condition=models.Q(incident__isnull=False),
                                    name='uniq_event_incident_link'),
            models.CheckConstraint(condition=models.Q(ticket__isnull=False) | models.Q(incident__isnull=False),
                                   name='event_link_has_target'),
        ]


class ProjectionQueueItem(models.Model):
    """A source row that changed and needs projecting (82.3). One row per
    source object, so a burst of saves queues it once."""
    source = models.CharField(max_length=20, choices=SOURCES)
    source_id = models.PositiveBigIntegerField()
    queued_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True, default='')
    dead = models.BooleanField(default=False, help_text='Gave up after repeated failures (dead letter)')

    class Meta:
        db_table = 'events_projection_queue'
        constraints = [models.UniqueConstraint(fields=['source', 'source_id'], name='uniq_projection_item')]
        indexes = [models.Index(fields=['dead', 'queued_at'])]


class SourceHealth(models.Model):
    """Ingestion health per source (82.5)."""
    source = models.CharField(max_length=20, choices=SOURCES, unique=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True, default='')
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_batch = models.PositiveIntegerField(default=0)
    total_projected = models.PositiveBigIntegerField(default=0)
    scan_watermark = models.PositiveBigIntegerField(default=0, help_text='Highest source pk scanned for new rows')
    last_duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'events_source_health'
        ordering = ['source']

    @property
    def state(self):
        if self.consecutive_failures >= 3:
            return 'failing'
        if self.consecutive_failures:
            return 'degraded'
        if self.last_success_at is None:
            return 'pending'
        return 'ok'


class EventSettings(models.Model):
    """Install-wide switches and retention (82.4, 82.6). One row."""
    ingestion_enabled = models.BooleanField(default=True, help_text='Copy source alerts into the shared event layer')
    retention_days = models.PositiveIntegerField(default=180, help_text='Delete closed events after this many days')
    raw_retention_days = models.PositiveIntegerField(default=30,
                                                     help_text='Clear the raw payload copy after this many days')
    max_events = models.PositiveIntegerField(default=200000,
                                             help_text='Storage quota: oldest closed events go first when exceeded')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'events_settings'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
