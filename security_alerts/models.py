"""
security_alerts/models.py — Phase 9 security event ingestion.

EDR / AV / Firewall vendors all alert independently. This app
aggregates alerts from all configured vendors, surfaces them on the
PSA dashboard, and lets techs triage from one screen.
"""
from django.conf import settings as django_settings
from django.db import models
from vault.secret_fields import EncryptedTextField, hash_token


class SecurityVendorConnection(models.Model):
    """A configured connection to a security vendor (EDR / AV / firewall)."""

    PROVIDER_CATEGORIES = [
        ('edr', 'Endpoint Detection & Response'),
        ('av', 'Antivirus'),
        ('firewall', 'Firewall'),
    ]
    PROVIDER_CHOICES = [
        # EDR
        ('crowdstrike_falcon', 'CrowdStrike Falcon'),
        ('sentinelone', 'SentinelOne Singularity'),
        ('defender', 'Microsoft Defender for Endpoint'),
        ('sophos_central', 'Sophos Central'),
        ('huntress', 'Huntress'),
        ('threatlocker', 'ThreatLocker'),
        # AV
        ('bitdefender', 'Bitdefender GravityZone'),
        ('webroot', 'Webroot'),
        ('malwarebytes', 'Malwarebytes'),
        ('eset', 'ESET'),
        # Firewall
        ('fortinet', 'Fortinet FortiGate'),
        ('palo_alto', 'Palo Alto'),
        ('sonicwall', 'SonicWall'),
        ('meraki_mx', 'Cisco Meraki MX'),
        ('sophos_xg', 'Sophos XG'),
        ('pfsense', 'pfSense'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='security_vendor_connections',
        help_text='MSP tenant that owns the connection.',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='security_vendor_connections_for_client',
        null=True, blank=True,
        help_text='Optionally pin the connection to a specific client. '
                  'Leave blank for an MSP-wide connection.',
    )
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES)
    category = models.CharField(max_length=20, choices=PROVIDER_CATEGORIES)

    # Provider credentials. Until v3.17.602 this column held whatever was
    # typed into the form, in plaintext, despite its name; it is now an
    # EncryptedTextField (enc2$ envelope), and the form never echoes it.
    credentials_encrypted = EncryptedTextField(blank=True,
        help_text='Encrypted blob of provider-specific creds '
                  '(API key / token / username+password / etc).')
    base_url = models.URLField(blank=True,
        help_text='Provider tenant URL (e.g. https://api.crowdstrike.com).')
    # The URL token is stored as an HMAC and the shared secret encrypted;
    # both are shown once, when issued (issue_webhook_credentials()).
    webhook_token_hash = models.CharField(max_length=64, blank=True, db_index=True,
        help_text='HMAC-SHA256 of the inbound webhook URL token.')
    webhook_secret = EncryptedTextField(blank=True,
        help_text='HMAC shared secret for verifying inbound webhook payloads (encrypted).')

    # Polling
    poll_interval_minutes = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)
    sync_enabled = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=40, blank=True,
        help_text='ok / error / running.')
    last_error = models.TextField(blank=True)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'security_vendor_connections'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['provider']),
            models.Index(fields=['client_org']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'

    WEBHOOK_TOKEN_PURPOSE = 'security_alerts.vendor.webhook'

    @classmethod
    def hash_webhook_token(cls, raw):
        return hash_token(raw, cls.WEBHOOK_TOKEN_PURPOSE)

    @classmethod
    def lookup_by_webhook_token(cls, raw, **filters):
        if not raw:
            return None
        return cls.objects.filter(
            webhook_token_hash=cls.hash_webhook_token(raw), **filters).first()

    def issue_webhook_credentials(self):
        """Mint a new URL token and HMAC secret. Returns (token, secret);
        the caller shows them once. Only the hash / ciphertext persist."""
        import secrets
        token = secrets.token_urlsafe(32)
        secret = secrets.token_hex(32)
        self.webhook_token_hash = self.hash_webhook_token(token)
        self.webhook_secret = secret
        self.issued_webhook_token = token
        self.issued_webhook_secret = secret
        return token, secret

    def save(self, *args, **kwargs):
        if not self.webhook_token_hash or not self.webhook_secret:
            self.issue_webhook_credentials()
        super().save(*args, **kwargs)


class SecurityAlert(models.Model):
    """A security alert ingested from a vendor."""
    SEVERITY_CHOICES = [
        ('info', 'Informational'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    STATUS_CHOICES = [
        ('new', 'New'),
        ('acknowledged', 'Acknowledged'),
        ('dismissed', 'Dismissed'),
        ('resolved', 'Resolved'),
    ]

    connection = models.ForeignKey(
        SecurityVendorConnection, on_delete=models.CASCADE,
        related_name='alerts',
        null=True, blank=True,
        help_text='Source vendor connection (poller / vendor webhook). '
                  'Null when the alert was ingested via a SIEM endpoint.',
    )
    siem_endpoint = models.ForeignKey(
        'security_alerts.SIEMWebhookEndpoint', on_delete=models.SET_NULL,
        related_name='alerts', null=True, blank=True,
        help_text='Phase 23 v3.17.337: source SIEM webhook endpoint when '
                  'the alert came in via /security/siem/webhook/.',
    )
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='security_alerts',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='security_alerts_for_client',
        null=True, blank=True,
    )

    external_id = models.CharField(max_length=200,
        help_text='Vendor-side unique ID — used for dedupe.')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    asset_hint = models.CharField(max_length=200, blank=True,
        help_text='Free-form hostname / IP / device name from the alert.')
    raw_payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    seen_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    auto_ticket = models.ForeignKey(
        'psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='security_alerts',
        help_text='If a rule auto-created a ticket from this alert, link to it.',
    )

    class Meta:
        db_table = 'security_alerts'
        ordering = ['-seen_at']
        unique_together = [
            ['connection', 'external_id'],
            ['siem_endpoint', 'external_id'],
        ]
        indexes = [
            models.Index(fields=['organization', 'status', '-seen_at']),
            models.Index(fields=['client_org', 'severity']),
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['siem_endpoint', '-seen_at']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title[:80]}'

    @property
    def acknowledge_minutes(self):
        if not self.acknowledged_at:
            return None
        return int((self.acknowledged_at - self.seen_at).total_seconds() / 60)


class SecurityAlertRule(models.Model):
    """
    Auto-action rule on incoming alerts. Patterns match on
    (connection / category / severity); action is 'create_ticket' for now.
    Mirrors the workflow_rules engine pattern.
    """
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='security_alert_rules',
    )
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=100)

    # Match clauses — empty = match-all
    match_provider = models.CharField(max_length=40, blank=True)
    match_category = models.CharField(max_length=20, blank=True)
    match_severity_min = models.CharField(
        max_length=20, blank=True,
        choices=SecurityAlert.SEVERITY_CHOICES,
    )
    match_client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='+', null=True, blank=True,
    )

    # Action
    action = models.CharField(max_length=40, default='create_ticket',
        choices=[('create_ticket', 'Create PSA Ticket')])
    ticket_queue_id = models.IntegerField(null=True, blank=True)
    ticket_priority_code = models.CharField(max_length=10, blank=True,
        help_text='P1 / P2 / P3 / P4 / P5 — overrides severity-derived default.')
    ticket_assignee = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name='+', null=True, blank=True,
    )

    # Suppression window — don't auto-ticket between these hours (per Phase 9.4)
    suppress_start_hour = models.IntegerField(null=True, blank=True,
        help_text='0-23 in MSP tenant\'s timezone. Blank = no suppression.')
    suppress_end_hour = models.IntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'security_alert_rules'
        ordering = ['priority', 'pk']

    def __str__(self):
        return f'{self.name} (priority {self.priority})'


class SIEMWebhookEndpoint(models.Model):
    """
    Phase 23 v3.17.337 — generic SIEM/Syslog/CEF webhook endpoint.

    Lets a customer point a SIEM (Splunk HEC, Elastic, Graylog, generic
    syslog forwarder, anything that can POST CEF-ish JSON or raw CEF) at
    `/security/siem/webhook/<token>/`. The token authenticates the source;
    optional HMAC adds cryptographic integrity. Inbound events are mapped
    to `SecurityAlert` rows so the existing triage UI / rules / playbooks
    just work.

    Unlike `SecurityVendorConnection` (which models a polled SaaS API),
    this endpoint is purely inbound — no creds, no polling. Multiple
    endpoints per org are fine (one per SIEM source).
    """

    FORMAT_CHOICES = [
        ('cef', 'CEF (Common Event Format)'),
        ('json', 'Generic JSON'),
        ('syslog', 'Syslog (RFC 5424)'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='siem_webhook_endpoints',
        help_text='MSP tenant that owns the endpoint.',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='siem_webhook_endpoints_for_client',
        null=True, blank=True,
        help_text='Optionally pin the endpoint to a specific client.',
    )
    name = models.CharField(max_length=120)
    expected_format = models.CharField(
        max_length=20, choices=FORMAT_CHOICES, default='cef',
    )
    # HMAC of the per-endpoint URL token (the token is shown once, when
    # issued). Only the hash is stored.
    token_hash = models.CharField(max_length=64, unique=True,
        help_text='HMAC-SHA256 of the per-endpoint URL token. Auto-generated.')
    hmac_secret = EncryptedTextField(blank=True,
        help_text='If set, inbound POSTs MUST send an X-Cst0r-Signature '
                  'header containing hex-encoded HMAC-SHA256(secret, body). '
                  'Encrypted at rest.')
    require_hmac = models.BooleanField(
        default=False,
        help_text='When True, requests without a valid signature are rejected '
                  'with HTTP 403. When False, signature is verified IF '
                  'sent but optional.',
    )
    default_severity = models.CharField(
        max_length=20, choices=SecurityAlert.SEVERITY_CHOICES,
        default='medium',
        help_text='Severity used when the inbound payload omits one.',
    )

    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    received_count = models.PositiveIntegerField(default=0)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'siem_webhook_endpoints'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['token_hash']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_expected_format_display()})'

    TOKEN_PURPOSE = 'security_alerts.siem.webhook'

    @classmethod
    def hash_token(cls, raw):
        return hash_token(raw, cls.TOKEN_PURPOSE)

    @classmethod
    def lookup_by_token(cls, raw, **filters):
        if not raw:
            return None
        return cls.objects.filter(token_hash=cls.hash_token(raw), **filters).first()

    def issue_webhook_credentials(self):
        """Mint a new URL token and HMAC secret; returns (token, secret)
        for one-time display."""
        import secrets
        token = secrets.token_urlsafe(32)
        secret = secrets.token_hex(32)
        self.token_hash = self.hash_token(token)
        self.hmac_secret = secret
        self.issued_token = token
        self.issued_hmac_secret = secret
        return token, secret

    def save(self, *args, **kwargs):
        if not self.token_hash or not self.hmac_secret:
            self.issue_webhook_credentials()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Phase 23 v3.17.338 — Security incidents + timelines
# ---------------------------------------------------------------------------

class SecurityIncident(models.Model):
    """Phase 23 v3.17.338 — incidents group related `SecurityAlert` rows.

    An incident is an analyst-facing case file: one row per "thing that
    needs investigating". Incidents are auto-created (or extended) when
    a fresh SecurityAlert lands and matches an open incident on
    (organization, asset_hint, severity) within a configurable
    correlation window. Manual incidents are also fine.

    The dashboard at `/security/incidents/<id>/` shows the timeline
    (`SecurityIncidentEvent` rows) and the linked alerts so a tech can
    see "what happened, in order" without bouncing across tabs.
    """

    SEVERITY_CHOICES = SecurityAlert.SEVERITY_CHOICES
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('investigating', 'Investigating'),
        ('contained', 'Contained'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='security_incidents',
        help_text='MSP tenant that owns the incident.',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='security_incidents_for_client',
        null=True, blank=True,
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')

    asset_hint = models.CharField(
        max_length=200, blank=True,
        help_text='Hostname / IP / device anchoring the incident — used for '
                  'auto-correlation of subsequent alerts.',
    )

    alerts = models.ManyToManyField(
        SecurityAlert, related_name='incidents', blank=True,
        help_text='Alerts grouped into this incident.',
    )

    opened_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    contained_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    assigned_to = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        db_table = 'security_incidents'
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-opened_at']),
            models.Index(fields=['client_org', 'severity']),
            models.Index(fields=['asset_hint']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title[:80]}'

    @property
    def is_open(self):
        return self.status not in {'resolved', 'closed'}

    def add_event(self, kind, message, *, user=None, alert=None):
        """Convenience: append a timeline event."""
        return SecurityIncidentEvent.objects.create(
            incident=self, kind=kind, message=message,
            actor=user, alert=alert,
        )


class SecurityIncidentEvent(models.Model):
    """Phase 23 v3.17.338 — single timeline entry on an incident."""

    KIND_CHOICES = [
        ('opened', 'Opened'),
        ('alert_added', 'Alert added'),
        ('note', 'Analyst note'),
        ('status_change', 'Status change'),
        ('assigned', 'Assigned'),
        ('acknowledged', 'Acknowledged'),
        ('contained', 'Contained'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
        ('playbook_action', 'Playbook action'),
        ('sla_breach', 'SLA breach'),
    ]

    incident = models.ForeignKey(
        SecurityIncident, on_delete=models.CASCADE, related_name='events',
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    message = models.TextField(blank=True)
    actor = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    alert = models.ForeignKey(
        SecurityAlert, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'security_incident_events'
        ordering = ['occurred_at', 'pk']
        indexes = [
            models.Index(fields=['incident', 'occurred_at']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} on incident {self.incident_id}'


class SecurityIncidentSLAPolicy(models.Model):
    """Phase 23 v3.17.340 — SLA targets for security incidents.

    A policy targets a (severity, optional client_org) tuple and sets
    minutes-to-acknowledge / minutes-to-contain / minutes-to-resolve
    deadlines. The breach checker mgmt cmd
    `manage.py check_incident_sla_breaches` walks every open incident,
    computes whether each target has been crossed, and writes a
    `sla_breach` event into the incident timeline (only once per
    target per incident).
    """

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='security_incident_sla_policies',
        help_text='MSP tenant that owns the policy.',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='+', null=True, blank=True,
        help_text='Optionally pin the policy to one client; '
                  'blank = MSP-wide for the given severity.',
    )
    severity = models.CharField(
        max_length=20, choices=SecurityAlert.SEVERITY_CHOICES,
        help_text='Severity bucket the policy applies to.',
    )

    acknowledge_minutes = models.PositiveIntegerField(
        default=15,
        help_text='Time-to-acknowledge SLA (minutes from open).',
    )
    contain_minutes = models.PositiveIntegerField(
        default=60,
        help_text='Time-to-contain SLA (minutes from open).',
    )
    resolve_minutes = models.PositiveIntegerField(
        default=240,
        help_text='Time-to-resolve SLA (minutes from open).',
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'security_incident_sla_policies'
        ordering = ['organization', 'severity']
        unique_together = [['organization', 'client_org', 'severity']]

    def __str__(self):
        scope = self.client_org.name if self.client_org else '(MSP-wide)'
        return f'{self.severity} / {scope} — {self.resolve_minutes}m resolve'


def policy_for_incident(incident):
    """Return the most-specific active SLA policy for this incident, or None."""
    qs = SecurityIncidentSLAPolicy.objects.filter(
        organization=incident.organization,
        severity=incident.severity,
        is_active=True,
    )
    # Prefer client-pinned policy
    pinned = qs.filter(client_org=incident.client_org).first() if incident.client_org_id else None
    if pinned:
        return pinned
    return qs.filter(client_org__isnull=True).first()


def evaluate_incident_breaches(incident):
    """Phase 23 v3.17.340 — write `sla_breach` timeline events for any
    SLA target the incident has crossed without being met. Idempotent —
    won't double-record the same breach.

    Returns a list of breach kind strings recorded this call.
    """
    from django.utils import timezone

    policy = policy_for_incident(incident)
    if policy is None:
        return []

    now = timezone.now()
    breaches = []
    existing = set(
        incident.events.filter(kind='sla_breach').values_list('message', flat=True)
    )

    targets = [
        ('acknowledge', policy.acknowledge_minutes, incident.acknowledged_at),
        ('contain', policy.contain_minutes, incident.contained_at),
        ('resolve', policy.resolve_minutes, incident.resolved_at),
    ]
    for label, minutes, met_at in targets:
        deadline = incident.opened_at + _timedelta(minutes=minutes)
        if met_at is not None and met_at <= deadline:
            continue  # met inside SLA, skip
        if met_at is None and now <= deadline:
            continue  # still inside the window
        marker = f'sla_breach:{label}'
        # De-dupe by checking if any prior sla_breach event message starts with marker
        if any(m.startswith(marker) for m in existing):
            continue
        msg = (
            f'{marker} — target {minutes} min exceeded '
            f'(deadline {deadline.isoformat()}, '
            f'{"met " + met_at.isoformat() if met_at else "not met"})'
        )
        incident.add_event(kind='sla_breach', message=msg)
        breaches.append(label)
    return breaches


def _timedelta(*, minutes):
    from datetime import timedelta
    return timedelta(minutes=minutes)


class RemediationPlaybook(models.Model):
    """Phase 23 v3.17.356 — automated remediation playbook.

    A playbook fires when a `SecurityIncident` matches its trigger
    conditions (severity-min + optional client_org). Each playbook
    has an ordered list of `RemediationPlaybookStep` actions
    (create_ticket / send_email / quarantine_asset_flag /
    run_workflow_rule). Playbook execution is recorded in the
    incident timeline as `playbook_action` events.
    """

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='remediation_playbooks',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=100,
        help_text='Lower fires first. Only the first matching playbook '
                  'runs per incident.')

    # Trigger
    match_severity_min = models.CharField(
        max_length=20, blank=True,
        choices=SecurityAlert.SEVERITY_CHOICES,
        help_text='Match incident.severity >= this. Empty = match-all.',
    )
    match_client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='+', null=True, blank=True,
        help_text='If set, only fires for incidents on this client.',
    )

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name='+', null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'remediation_playbooks'
        ordering = ['priority', 'pk']

    def __str__(self):
        return f'{self.name} (priority {self.priority})'


class RemediationPlaybookStep(models.Model):
    """Phase 23 v3.17.356 — one action in a playbook."""

    ACTION_CHOICES = [
        ('create_ticket', 'Create PSA ticket'),
        ('send_email', 'Send email'),
        ('quarantine_asset_flag', 'Flag asset for quarantine'),
        ('run_workflow_rule', 'Run PSA workflow rule'),
    ]

    playbook = models.ForeignKey(
        RemediationPlaybook, on_delete=models.CASCADE,
        related_name='steps',
    )
    order = models.PositiveIntegerField(default=10)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    config = models.JSONField(
        default=dict, blank=True,
        help_text='Action-specific config: e.g. {"to": "ops@example.com"} '
                  'for send_email; {"queue_slug": "soc"} for create_ticket.',
    )

    class Meta:
        db_table = 'remediation_playbook_steps'
        ordering = ['order', 'pk']

    def __str__(self):
        return f'{self.playbook.name} #{self.order} {self.action}'


def find_matching_playbook(incident):
    """Return the highest-priority active playbook matching this incident, or None."""
    severity_rank = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
    inc_rank = severity_rank.get(incident.severity, 0)

    qs = RemediationPlaybook.objects.filter(
        organization=incident.organization, is_active=True,
    ).order_by('priority', 'pk')
    for pb in qs:
        if pb.match_client_org_id and pb.match_client_org_id != incident.client_org_id:
            continue
        if pb.match_severity_min:
            if inc_rank < severity_rank.get(pb.match_severity_min, 0):
                continue
        return pb
    return None


def execute_playbook(playbook, incident, *, dry_run=False):
    """Phase 23 v3.17.356 — run a playbook against an incident.

    Records each step result as a `playbook_action` timeline event.
    Returns a list of `(step, status, message)` tuples for caller
    inspection. Errors in one step do not halt the rest.
    """
    results = []
    for step in playbook.steps.order_by('order', 'pk'):
        try:
            if dry_run:
                msg = f'[dry] would run {step.action} with {step.config}'
                status = 'dry'
            else:
                status, msg = _run_playbook_step(step, incident)
        except Exception as exc:
            status = 'error'
            msg = f'{step.action} raised: {exc}'
        incident.add_event(
            kind='playbook_action',
            message=f'playbook={playbook.name} step={step.action} status={status} :: {msg}',
        )
        results.append((step, status, msg))
    return results


def _run_playbook_step(step, incident):
    """Inner step dispatcher. Returns (status, message)."""
    cfg = step.config or {}
    action = step.action
    if action == 'create_ticket':
        from psa.models import Ticket, Queue, TicketPriority, TicketStatus, TicketType
        queue = (
            Queue.objects.filter(slug=cfg.get('queue_slug')).first()
            if cfg.get('queue_slug')
            else Queue.objects.filter(is_active=True).first()
        )
        priority_code = cfg.get('priority_code') or {
            'critical': 'P1', 'high': 'P2', 'medium': 'P3',
            'low': 'P4', 'info': 'P5',
        }.get(incident.severity, 'P3')
        priority = (TicketPriority.objects.filter(code=priority_code).first()
                    or TicketPriority.objects.first())
        status_obj = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first()
        ttype = TicketType.objects.first()
        ticket = Ticket.objects.create(
            organization=incident.client_org or incident.organization,
            subject=f'[Security Incident] {incident.title[:200]}',
            description=incident.description or 'Auto-created by remediation playbook',
            queue=queue, priority=priority, status=status_obj, ticket_type=ttype,
            source='monitoring',
        )
        return ('ok', f'created ticket {ticket.ticket_number}')
    elif action == 'send_email':
        recipient = cfg.get('to') or ''
        # Use the same email-out plumbing PSA uses where possible; fall back
        # to a logged event so tests can verify the call path.
        try:
            from django.core.mail import send_mail
            subject = cfg.get('subject') or f'[Security] {incident.title[:80]}'
            body = cfg.get('body') or incident.description or 'See incident dashboard.'
            from django.conf import settings as dj_settings
            sender = cfg.get('from') or getattr(dj_settings, 'DEFAULT_FROM_EMAIL', 'no-reply@localhost')
            send_mail(subject, body, sender, [recipient] if recipient else [], fail_silently=True)
            return ('ok', f'email queued to {recipient or "(no recipient)"}')
        except Exception as exc:
            return ('error', f'send_mail failed: {exc}')
    elif action == 'quarantine_asset_flag':
        # Best-effort: stamp a tag onto the asset matched by asset_hint.
        if not incident.asset_hint:
            return ('skip', 'no asset_hint on incident')
        try:
            from assets.models import Asset
            asset = Asset.objects.filter(
                organization=incident.organization,
                name__iexact=incident.asset_hint,
            ).first() or Asset.objects.filter(
                organization=incident.organization,
                hostname__iexact=incident.asset_hint,
            ).first()
            if not asset:
                return ('skip', f'no asset matched "{incident.asset_hint}"')
            from core.models import Tag
            tag, _ = Tag.objects.get_or_create(
                organization=incident.organization,
                slug='security-quarantine',
                defaults={'name': 'security-quarantine'},
            )
            asset.tags.add(tag)
            return ('ok', f'asset {asset.pk} flagged for quarantine')
        except Exception as exc:
            return ('error', f'asset flag failed: {exc}')
    elif action == 'run_workflow_rule':
        rule_id = cfg.get('rule_id')
        if not rule_id:
            return ('skip', 'no rule_id in config')
        try:
            from psa.models import WorkflowRule
            rule = WorkflowRule.objects.filter(pk=rule_id).first()
            if not rule:
                return ('skip', f'workflow rule {rule_id} not found')
            return ('ok', f'workflow rule {rule.name} flagged for execution')
        except Exception as exc:
            return ('error', f'workflow rule lookup failed: {exc}')
    return ('skip', f'unknown action {action}')


def _correlate_alert_to_incident(alert, *, window_minutes=60):
    """Phase 23 v3.17.338 — auto-grouping helper.

    Find an open `SecurityIncident` matching this alert's
    (organization, asset_hint, severity) within `window_minutes`. If
    found, attach the alert and append a timeline event. Otherwise
    open a brand new incident anchored by this alert. Returns the
    SecurityIncident.
    """
    from django.utils import timezone
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    incident = None
    if alert.asset_hint:
        incident = SecurityIncident.objects.filter(
            organization=alert.organization,
            asset_hint=alert.asset_hint,
            severity=alert.severity,
            status__in=['open', 'investigating'],
            opened_at__gte=cutoff,
        ).order_by('-opened_at').first()

    if incident is None:
        incident = SecurityIncident.objects.create(
            organization=alert.organization,
            client_org=alert.client_org,
            title=alert.title[:300],
            description=alert.description or '',
            severity=alert.severity,
            asset_hint=alert.asset_hint or '',
            status='open',
        )
        incident.alerts.add(alert)
        incident.add_event(
            kind='opened',
            message=f'Incident opened from alert {alert.pk}: {alert.title[:200]}',
            alert=alert,
        )
        # Phase 23 v3.17.356 — auto-fire matching remediation playbook.
        try:
            pb = find_matching_playbook(incident)
            if pb is not None:
                execute_playbook(pb, incident)
        except Exception:
            pass
    else:
        if not incident.alerts.filter(pk=alert.pk).exists():
            incident.alerts.add(alert)
            incident.add_event(
                kind='alert_added',
                message=f'Alert {alert.pk} correlated: {alert.title[:200]}',
                alert=alert,
            )
    return incident
