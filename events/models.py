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
SOURCE_CONNECT = 'connect'
SOURCES = (
    (SOURCE_SECURITY, 'Security alerts (vendors and SIEM)'),
    (SOURCE_RMM, 'RMM alerts'),
    (SOURCE_REM0TE, 'Rem0te alerts'),
    (SOURCE_BACKUP, 'Backup alerts'),
    (SOURCE_MONITOR, 'Website monitors'),
    (SOURCE_CONNECT, 'Connected applications'),
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
    # Monitoring coverage (82.15–82.20): the source's own event time, kept
    # apart from when Clientst0r received it (first_seen_at for security
    # alerts is the ingestion time). An alert that arrived only after a
    # monitoring outage is marked delivered late: nobody saw it in real time.
    occurred_at = models.DateTimeField(null=True, blank=True,
                                       help_text="The source's own event time, when it gave a valid one")
    delivered_late = models.BooleanField(default=False,
                                         help_text='Arrived only after a monitoring coverage gap (backfill or the '
                                                   'first read after recovery)')
    delivery_delay_seconds = models.PositiveBigIntegerField(null=True, blank=True,
                                                            help_text='Ingestion time minus the event time')

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
    # Monitoring coverage (82.15–82.20).
    backfill_enabled = models.BooleanField(default=True, help_text='Retrieve missed events after a monitoring '
                                                                   'source recovers, where the source supports it')
    backfill_max_lookback_hours = models.PositiveIntegerField(
        default=168, help_text='Never ask a source for events older than this (hours), whatever it allows')
    coverage_gap_notify_minutes = models.PositiveIntegerField(
        default=60, help_text='E-mail technicians once when a critical source has been interrupted this long '
                              '(0 = never)')
    coverage_recovery_notify = models.BooleanField(
        default=True, help_text='E-mail technicians once when a gap could not be fully recovered')
    retention_days = models.PositiveIntegerField(default=180, help_text='Delete closed events after this many days')
    raw_retention_days = models.PositiveIntegerField(default=30,
                                                     help_text='Clear the raw payload copy after this many days')
    max_events = models.PositiveIntegerField(default=200000,
                                             help_text='Storage quota: oldest closed events go first when exceeded')
    source_retention_days = models.JSONField(default=dict, blank=True,
                                             help_text='Per-source override of retention_days {source: days}')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'events_settings'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class CustomerRetention(models.Model):
    """Per-customer retention for closed events (82.4); wins over the source
    and install-wide settings."""
    organization = models.OneToOneField('core.Organization', on_delete=models.CASCADE,
                                        related_name='event_retention')
    retention_days = models.PositiveIntegerField(help_text='Delete closed events after this many days (0 = keep)')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'events_customer_retention'


# --- monitoring coverage (82.15–82.20) -------------------------------------------------------

COVERAGE_GAP = 'coverage_gap'
RECOVERED_LATE = 'recovered_late'
PARTIAL_RECOVERY = 'partial_recovery'
UNRECOVERABLE_GAP = 'unrecoverable_gap'
WINDOW_STATES = ((COVERAGE_GAP, 'Coverage Gap'), (RECOVERED_LATE, 'Recovered – Delivered Late'),
                 (PARTIAL_RECOVERY, 'Partial Recovery'), (UNRECOVERABLE_GAP, 'Unrecoverable Gap'))
BACKFILL_STATES = (('', 'Not started'), ('pending', 'Pending'), ('running', 'Running'), ('complete', 'Complete'),
                   ('incomplete', 'Incomplete'), ('failed', 'Failed'), ('unsupported', 'Not supported'),
                   ('disabled', 'Switched off'))


class CoverageWindow(models.Model):
    """One interruption of one monitoring source (82.15). Opened by the first
    failed read (or by the freshness sweep when a collector stops), closed
    when the missed window has been backfilled or found unrecoverable. Rows
    are never overwritten by a later outage: each gap stays in the history.

    The customer is copied from the source's health row (which copies it
    from the connection), never from a payload.
    """
    organization = models.ForeignKey('core.Organization', null=True, blank=True, on_delete=models.CASCADE,
                                     related_name='coverage_windows',
                                     help_text='The customer; empty = MSP-wide source')
    health = models.ForeignKey('integrations.IntegrationSyncHealth', null=True, blank=True,
                               on_delete=models.SET_NULL, related_name='coverage_windows')
    source_key = models.CharField(max_length=80, db_index=True,
                                  help_text='kind:content_type:object_id, as in the reliability feed')
    kind = models.CharField(max_length=20)
    source_name = models.CharField(max_length=200, blank=True, default='')
    state = models.CharField(max_length=24, choices=WINDOW_STATES, default=COVERAGE_GAP)
    cause = models.CharField(max_length=30, blank=True, default='', help_text='Failure reason that opened it')
    coverage_lost_at = models.DateTimeField(help_text='Last verified coverage: events after this were not seen')
    first_failure_at = models.DateTimeField(help_text='Outage start: the first failed read')
    last_failure_at = models.DateTimeField(null=True, blank=True)
    failed_reads = models.PositiveIntegerField(default=0)
    recovered_at = models.DateTimeField(null=True, blank=True, help_text='First successful read after the outage')
    backfill_state = models.CharField(max_length=12, choices=BACKFILL_STATES, blank=True, default='')
    backfill_from = models.DateTimeField(null=True, blank=True, help_text='Start actually requested (lookback cap)')
    backfill_to = models.DateTimeField(null=True, blank=True)
    checkpoint_cursor = models.CharField(max_length=500, blank=True, default='',
                                        help_text='Durable resume point: the next page to request')
    checkpoint_at = models.DateTimeField(null=True, blank=True,
                                         help_text='Coverage established up to here (time-ordered sources only)')
    pages_fetched = models.PositiveIntegerField(default=0)
    records_fetched = models.PositiveIntegerField(default=0)
    backfill_attempts = models.PositiveSmallIntegerField(default=0)
    backfill_next_at = models.DateTimeField(null=True, blank=True)
    backfill_error = models.CharField(max_length=300, blank=True, default='')
    recovered_count = models.PositiveIntegerField(default=0, help_text='Events delivered late')
    duplicate_count = models.PositiveIntegerField(default=0, help_text='Already stored; not stored again')
    rejected_count = models.PositiveIntegerField(default=0)
    max_delay_seconds = models.PositiveBigIntegerField(null=True, blank=True)
    lookback_truncated = models.BooleanField(default=False)
    capability = models.JSONField(default=dict, blank=True, help_text='Declared history capability when resolved')
    resolved_at = models.DateTimeField(null=True, blank=True)
    notified_prolonged_at = models.DateTimeField(null=True, blank=True)
    notified_unrecovered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'events_coverage_windows'
        ordering = ['-first_failure_at']
        constraints = [models.UniqueConstraint(fields=['source_key'], condition=models.Q(state='coverage_gap'),
                                               name='uniq_open_coverage_window')]
        indexes = [models.Index(fields=['organization', '-first_failure_at']),
                   models.Index(fields=['state', 'backfill_state'])]

    def __str__(self):
        return f'{self.source_name or self.source_key}: {self.get_state_display()}'

    @property
    def is_open(self):
        return self.state == COVERAGE_GAP

    @property
    def outage_seconds(self):
        end = self.recovered_at or timezone.now()
        return max(0, int((end - self.first_failure_at).total_seconds()))

    @property
    def gap_seconds(self):
        end = self.recovered_at or timezone.now()
        return max(0, int((end - self.coverage_lost_at).total_seconds()))
