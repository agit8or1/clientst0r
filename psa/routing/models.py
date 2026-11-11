"""Ticket routing models.

Everything here is staff-only. Nothing in this app ever changes a ticket's
customer, SLA clock, memberships or access grants; the service layer writes
only `assigned_to`, `queue` and `assigned_team` on a ticket.
"""
from datetime import time

from django.conf import settings as django_settings
from django.db import models
from django.utils import timezone


MODE_OFF = 'off'
MODE_SUGGEST = 'suggest'
MODE_AUTO = 'auto'
MODE_INHERIT = 'inherit'
MODE_CHOICES = [
    (MODE_OFF, 'Off'),
    (MODE_SUGGEST, 'Suggest only'),
    (MODE_AUTO, 'Automatic'),
]
CUSTOMER_MODE_CHOICES = [(MODE_INHERIT, 'Inherit MSP default')] + MODE_CHOICES


def _default_business_days():
    return [0, 1, 2, 3, 4]  # Monday..Friday


class RoutingSettings(models.Model):
    """MSP-wide routing defaults. One row (pk=1), created on first save.

    Reading never creates the row: `RoutingSettings.load()` returns unsaved
    defaults (mode Off) when it is missing, so a fresh install and an upgraded
    one behave the same until an administrator saves this page.
    """
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_OFF)
    reroute_on_reply = models.BooleanField(
        default=False, help_text='Re-evaluate when the customer replies.')
    reroute_on_reopen = models.BooleanField(
        default=False, help_text='Re-evaluate when a closed ticket is reopened.')
    reroute_on_sla = models.BooleanField(
        default=False, help_text='Re-evaluate once when the resolution SLA reaches the threshold.')
    sla_reroute_pct = models.PositiveSmallIntegerField(
        default=75, help_text='Percent of the resolution SLA window elapsed.')
    preserve_manual_assignment = models.BooleanField(
        default=True,
        help_text='Never move a ticket away from someone a person assigned it to.')
    max_reroutes = models.PositiveSmallIntegerField(
        default=5, help_text='Automatic reroutes allowed per ticket (loop guard).')
    business_days = models.JSONField(default=_default_business_days, blank=True,
                                     help_text='Weekdays 0=Monday .. 6=Sunday.')
    business_start = models.TimeField(default=time(8, 0))
    business_end = models.TimeField(default=time(17, 0))
    business_timezone = models.CharField(
        max_length=64, blank=True, help_text='Blank = the server time zone.')

    updated_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_routing_settings'
        verbose_name = 'Ticket routing settings'
        verbose_name_plural = 'Ticket routing settings'

    def __str__(self):
        return f'Ticket routing ({self.get_mode_display()})'

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)


class CustomerRoutingSettings(models.Model):
    """Per-customer override. No row = inherit the MSP default."""
    organization = models.OneToOneField('core.Organization', on_delete=models.CASCADE,
                                        related_name='ticket_routing_settings')
    mode = models.CharField(max_length=10, choices=CUSTOMER_MODE_CHOICES, default=MODE_INHERIT)
    restrict_technicians = models.BooleanField(
        default=False,
        help_text='Only the technicians listed may be chosen by routing for this customer.')
    authorized_technicians = models.ManyToManyField(
        django_settings.AUTH_USER_MODEL, blank=True, related_name='+')
    updated_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_routing_customer_settings'

    def __str__(self):
        return f'Routing for {self.organization} ({self.get_mode_display()})'


DEST_QUEUE = 'queue'
DEST_TECHNICIAN = 'technician'
DEST_TEAM = 'team'
DEST_ROUND_ROBIN = 'round_robin'
DEST_SKILL = 'skill_match'
DEST_LEAST_LOADED = 'least_loaded'
DESTINATION_CHOICES = [
    (DEST_QUEUE, 'Queue only'),
    (DEST_TECHNICIAN, 'Named technician'),
    (DEST_TEAM, 'Team'),
    (DEST_ROUND_ROBIN, 'Round-robin'),
    (DEST_SKILL, 'Skill match'),
    (DEST_LEAST_LOADED, 'Least-loaded eligible technician'),
]
PICKING_DESTINATIONS = {DEST_TECHNICIAN, DEST_ROUND_ROBIN, DEST_SKILL, DEST_LEAST_LOADED}

FALLBACK_QUEUE = 'queue'
FALLBACK_TRIAGE = 'triage'
FALLBACK_CHOICES = [
    (FALLBACK_QUEUE, 'Put it in a queue'),
    (FALLBACK_TRIAGE, 'Leave unassigned in triage'),
]


class RoutingRule(models.Model):
    """An editable routing rule. What runs is `current_version`, an immutable
    snapshot taken when the rule is saved through the review step; editing a
    rule never changes how tickets already routed were decided.

    conditions: {sources, ticket_types, priorities, queues, tags_any,
                 keywords_any, services, contract_types, contract
                 ('any'|'yes'|'no'), hours ('any'|'business'|'after'),
                 sla_pct_at_least}
    destination: {type, queue_id, user_id, team_id, skills, min_proficiency,
                  require_on_call, require_available}
    fallback: {type: 'queue'|'triage', queue_id}
    """
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='ticket_routing_rules',
        help_text='Blank = every customer (inherited). Customer rules are evaluated first.')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=100, help_text='Lower is evaluated first.')
    is_active = models.BooleanField(default=False)
    conditions = models.JSONField(default=dict, blank=True)
    destination = models.JSONField(default=dict, blank=True)
    fallback = models.JSONField(default=dict, blank=True)
    current_version = models.ForeignKey('RoutingRuleVersion', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='+')
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_routing_rules'
        ordering = ['organization__name', 'priority', 'pk']
        indexes = [models.Index(fields=['is_active', 'organization', 'priority'])]

    def __str__(self):
        return self.name


class RoutingRuleVersion(models.Model):
    """Immutable snapshot of a rule. Decisions point at the version that made them."""
    rule = models.ForeignKey(RoutingRule, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    organization_id_snapshot = models.IntegerField(null=True, blank=True)
    priority = models.PositiveIntegerField(default=100)
    conditions = models.JSONField(default=dict, blank=True)
    destination = models.JSONField(default=dict, blank=True)
    fallback = models.JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True)
    published_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    published_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'ticket_routing_rule_versions'
        ordering = ['rule', '-number']
        constraints = [models.UniqueConstraint(fields=['rule', 'number'],
                                               name='uniq_ticket_routing_rule_version')]

    def __str__(self):
        return f'{self.name} v{self.number}'


TRIGGER_CREATED = 'created'
TRIGGER_REPLY = 'reply'
TRIGGER_REOPEN = 'reopen'
TRIGGER_SLA = 'sla'
TRIGGER_MANUAL = 'manual'
TRIGGER_CHOICES = [
    (TRIGGER_CREATED, 'Ticket created'),
    (TRIGGER_REPLY, 'Customer replied'),
    (TRIGGER_REOPEN, 'Ticket reopened'),
    (TRIGGER_SLA, 'SLA threshold'),
    (TRIGGER_MANUAL, 'Manual assignment'),
]

STATUS_PENDING = 'pending'
STATUS_APPLIED = 'applied'
STATUS_FALLBACK = 'fallback'
STATUS_SUGGESTED = 'suggested'
STATUS_ACCEPTED = 'accepted'
STATUS_REJECTED = 'rejected'
STATUS_SUPERSEDED = 'superseded'
STATUS_SKIPPED = 'skipped'
STATUS_OVERRIDE = 'override'
STATUS_CHOICES = [
    (STATUS_PENDING, 'Pending'),
    (STATUS_APPLIED, 'Applied'),
    (STATUS_FALLBACK, 'Fallback applied'),
    (STATUS_SUGGESTED, 'Suggested'),
    (STATUS_ACCEPTED, 'Suggestion accepted'),
    (STATUS_REJECTED, 'Suggestion rejected'),
    (STATUS_SUPERSEDED, 'Superseded'),
    (STATUS_SKIPPED, 'No change'),
    (STATUS_OVERRIDE, 'Manual override'),
]


class RoutingDecision(models.Model):
    """Staff-only routing history for a ticket. Never shown in the portal.

    `(ticket, idempotency_key)` is unique: the row is inserted before anything
    else happens, so a repeated delivery of the same trigger (a duplicate
    email, a retried job, two workers) finds the claim and does nothing.
    """
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.CASCADE, related_name='routing_decisions')
    trigger = models.CharField(max_length=10, choices=TRIGGER_CHOICES)
    idempotency_key = models.CharField(max_length=191)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    rule = models.ForeignKey(RoutingRule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='decisions')
    rule_version = models.ForeignKey(RoutingRuleVersion, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='decisions')
    destination_type = models.CharField(max_length=20, blank=True)
    previous_assignee = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='+')
    previous_queue = models.ForeignKey('psa.Queue', on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+')
    previous_team = models.CharField(max_length=100, blank=True)
    new_assignee = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    new_queue = models.ForeignKey('psa.Queue', on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name='+')
    new_team = models.CharField(max_length=100, blank=True)
    round_robin_key = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True)
    skipped_candidates = models.JSONField(default=list, blank=True)
    decided_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ticket_routing_decisions'
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['ticket', 'idempotency_key'],
                                               name='uniq_ticket_routing_decision_key')]
        indexes = [models.Index(fields=['ticket', '-created_at']),
                   models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f'{self.ticket_id} {self.trigger} {self.status}'

    @property
    def changes_something(self):
        return (self.new_assignee_id != self.previous_assignee_id
                or (self.new_queue_id and self.new_queue_id != self.previous_queue_id)
                or (self.new_team and self.new_team != self.previous_team))


class RoundRobinPointer(models.Model):
    """How many tickets a round-robin rule has handed out. Incremented with an
    UPDATE ... SET counter = counter + 1 inside the routing transaction, which
    takes the row lock (MariaDB/Postgres) or the write lock (SQLite) before the
    next technician is read, so two tickets arriving together get different
    technicians."""
    key = models.CharField(max_length=100, unique=True)
    counter = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_routing_round_robin'

    def __str__(self):
        return f'{self.key}: {self.counter}'


class OnCallShift(models.Model):
    """A technician is on call between two moments, optionally for one team."""
    user = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='ticket_routing_on_call')
    team = models.ForeignKey('auth.Group', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+', help_text='Blank = on call for every team.')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ticket_routing_on_call'
        ordering = ['starts_at']
        indexes = [models.Index(fields=['starts_at', 'ends_at'])]

    def __str__(self):
        return f'{self.user} on call {self.starts_at:%Y-%m-%d %H:%M} – {self.ends_at:%Y-%m-%d %H:%M}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'The shift must end after it starts.'})


# ===========================================================================
# Alert → ticket policy (Phase 6). Optional, off by default ("legacy": Rem0te
# alerts open one ticket each exactly as before; synced RMM alerts open
# none). Decides whether a monitoring alert opens a ticket, joins an
# existing one, is held, suppressed or ignored. Never starts a remote session
# and never asks for an endpoint action. Works with AI switched off.
# alert_policy.py has the rules.
# ===========================================================================

ALERT_MODE_LEGACY = 'legacy'
ALERT_MODE_POLICY = 'policy'
ALERT_MODE_CHOICES = [
    (ALERT_MODE_LEGACY, 'Legacy (one ticket per Rem0te alert, no policy)'),
    (ALERT_MODE_POLICY, 'Alert policy'),
]

ALERT_CREATE = 'create'
ALERT_ATTACH = 'attach'
ALERT_IGNORE = 'ignore'
ALERT_ACTION_CHOICES = [
    (ALERT_CREATE, 'Open a ticket (repeats join it)'),
    (ALERT_ATTACH, "Join the device's open ticket, else open one"),
    (ALERT_IGNORE, 'Record only, no ticket'),
]

ALERT_CATEGORY_CHOICES = [
    ('offline', 'Computer offline'),
    ('disk', 'Disk nearly full'),
    ('service', 'Service stopped'),
    ('windows_update', 'Windows Update failure'),
    ('cpu', 'High CPU'),
    ('memory', 'High memory'),
    ('reboot_pending', 'Pending reboot'),
    ('application', 'Application failure'),
    ('network', 'Network connectivity'),
    ('unresponsive_app', 'Unresponsive application'),
    ('security', 'Endpoint security alert'),
    ('backup', 'Backup failure'),
    ('site_outage', 'Site outage'),
    ('other', 'Other'),
]
ALERT_SEVERITY_CHOICES = [('info', 'Info'), ('warning', 'Warning'), ('error', 'Error'),
                          ('critical', 'Critical')]

ASSIGN_ROUTING = 'routing'
ASSIGN_TECHNICIAN = 'technician'
ASSIGN_ON_CALL = 'on_call'
ASSIGN_CHOICES = [
    (ASSIGN_ROUTING, 'Leave to ticket routing (or the queue)'),
    (ASSIGN_TECHNICIAN, 'Named technician'),
    (ASSIGN_ON_CALL, 'Whoever is on call now'),
]
AFTER_HOURS_CREATE = 'create'
AFTER_HOURS_HOLD = 'hold'
AFTER_HOURS_ON_CALL = 'on_call'
AFTER_HOURS_CHOICES = [
    (AFTER_HOURS_CREATE, 'Same as business hours'),
    (AFTER_HOURS_HOLD, 'Hold until business hours (critical alerts are never held)'),
    (AFTER_HOURS_ON_CALL, 'Open it for whoever is on call'),
]
RECOVERY_NOTE = 'note'
RECOVERY_CLOSE_IF_SOLE = 'close_if_sole'
RECOVERY_CHOICES = [
    (RECOVERY_NOTE, 'Add a staff note; people close the ticket'),
    (RECOVERY_CLOSE_IF_SOLE, 'Resolve the ticket only if this alert alone opened it and nobody has worked on it'),
]


class AlertPolicySettings(models.Model):
    """MSP-wide alert policy settings. One row (pk=1); reading never creates it."""
    mode = models.CharField(max_length=10, choices=ALERT_MODE_CHOICES, default=ALERT_MODE_LEGACY)
    include_rmm_sync = models.BooleanField(
        default=False, help_text='Also apply the policy to alerts synced from other RMM providers.')
    default_action = models.CharField(max_length=10, choices=ALERT_ACTION_CHOICES, default=ALERT_CREATE,
                                      help_text='When no alert rule matches.')
    default_queue = models.ForeignKey('psa.Queue', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='+')
    offline_hold_minutes = models.PositiveSmallIntegerField(
        default=5, help_text='Hold "computer offline" alerts this long before opening a ticket, so a site '
                             'outage becomes one incident and a quick reboot opens nothing. 0 = no hold.')
    site_outage_threshold = models.PositiveSmallIntegerField(
        default=5, help_text='Computers offline at one site within the window that make a site outage '
                             '(one parent ticket). 0 = off.')
    site_outage_window_minutes = models.PositiveSmallIntegerField(default=15)
    post_recovery_notes = models.BooleanField(
        default=True, help_text='Add a staff-only note to the ticket when its alert recovers.')
    updated_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_alert_policy_settings'
        verbose_name = 'Alert policy settings'
        verbose_name_plural = 'Alert policy settings'

    def __str__(self):
        return f'Alert policy ({self.get_mode_display()})'

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)


class AlertPolicyRule(models.Model):
    """One alert rule. Customer rules are evaluated before all-customer rules,
    each by priority. The rule as it stood is snapshotted onto every alert it
    decided, so editing it later does not rewrite history.

    conditions: {sources: ['rem0te','rmm'], categories: [...], severities: [...],
                 sites: [site names], device_types: [...]}  (empty = any)
    """
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='alert_policy_rules',
                                     help_text='Blank = every customer.')
    name = models.CharField(max_length=200)
    priority = models.PositiveIntegerField(default=100, help_text='Lower is evaluated first.')
    is_active = models.BooleanField(default=True)
    conditions = models.JSONField(default=dict, blank=True)
    action = models.CharField(max_length=10, choices=ALERT_ACTION_CHOICES, default=ALERT_CREATE)
    queue = models.ForeignKey('psa.Queue', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    ticket_priority = models.ForeignKey('psa.TicketPriority', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+', help_text='Blank = from the alert severity.')
    ticket_type = models.ForeignKey('psa.TicketType', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    assign_mode = models.CharField(max_length=12, choices=ASSIGN_CHOICES, default=ASSIGN_ROUTING)
    assign_user = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='+')
    after_hours = models.CharField(max_length=10, choices=AFTER_HOURS_CHOICES, default=AFTER_HOURS_CREATE)
    escalate_after_minutes = models.PositiveIntegerField(
        null=True, blank=True, help_text='Escalate when nobody has responded and the alert is still open.')
    escalation_priority = models.ForeignKey('psa.TicketPriority', on_delete=models.SET_NULL, null=True,
                                            blank=True, related_name='+')
    escalation_queue = models.ForeignKey('psa.Queue', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='+')
    on_recovery = models.CharField(max_length=15, choices=RECOVERY_CHOICES, default=RECOVERY_NOTE)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_alert_policy_rules'
        ordering = ['organization__name', 'priority', 'pk']
        indexes = [models.Index(fields=['is_active', 'organization', 'priority'])]

    def __str__(self):
        return self.name

    def snapshot(self):
        return {'id': self.pk, 'name': self.name, 'organization_id': self.organization_id,
                'priority': self.priority, 'conditions': self.conditions, 'action': self.action,
                'queue_id': self.queue_id, 'ticket_priority_id': self.ticket_priority_id,
                'ticket_type_id': self.ticket_type_id, 'assign_mode': self.assign_mode,
                'assign_user_id': self.assign_user_id, 'after_hours': self.after_hours,
                'escalate_after_minutes': self.escalate_after_minutes,
                'escalation_priority_id': self.escalation_priority_id,
                'escalation_queue_id': self.escalation_queue_id, 'on_recovery': self.on_recovery,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None}


MAINT_TICKET_IF_OPEN = 'ticket_if_open'
MAINT_DROP = 'drop'
MAINT_AFTER_CHOICES = [
    (MAINT_TICKET_IF_OPEN, 'Apply the policy when the window ends if the alert is still open'),
    (MAINT_DROP, 'Never open a ticket for it'),
]


class AlertMaintenanceWindow(models.Model):
    """Planned work: alerts that match are suppressed while the window is open."""
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='alert_maintenance_windows')
    site_name = models.CharField(max_length=255, blank=True, help_text='Blank = every site.')
    device = models.ForeignKey('integrations.RMMDevice', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='+', help_text='Blank = every device.')
    categories = models.JSONField(default=list, blank=True, help_text='Empty = every alert category.')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=300, blank=True)
    after_window = models.CharField(max_length=15, choices=MAINT_AFTER_CHOICES, default=MAINT_TICKET_IF_OPEN)
    is_cancelled = models.BooleanField(default=False)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ticket_alert_maintenance_windows'
        ordering = ['-starts_at']
        indexes = [models.Index(fields=['organization', 'starts_at', 'ends_at'])]

    def __str__(self):
        return f'{self.organization} maintenance {self.starts_at:%Y-%m-%d %H:%M} – {self.ends_at:%Y-%m-%d %H:%M}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'The window must end after it starts.'})


class AlertIncident(models.Model):
    """A site outage: several computers at one site offline together. One
    parent ticket; the member alerts are recorded against it instead of each
    opening a ticket."""
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    site_key = models.CharField(max_length=300)
    site_name = models.CharField(max_length=255, blank=True)
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='alert_incidents')
    source_alert_key = models.CharField(max_length=300, blank=True,
                                        help_text="The RMM's own site-outage alert, when it sent one.")
    status = models.CharField(max_length=10, default='open',
                              choices=[('open', 'Open'), ('resolved', 'Resolved')])
    member_count = models.PositiveIntegerField(default=0)
    opened_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ticket_alert_incidents'
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['organization', 'site_key', 'status'])]

    def __str__(self):
        return f'Site outage {self.site_name or self.site_key} ({self.status})'


DISP_CREATED = 'created'
DISP_ATTACHED = 'attached'
DISP_OUTAGE = 'outage_member'
DISP_HELD = 'held'
DISP_SUPPRESSED = 'suppressed'
DISP_IGNORED = 'ignored'
DISP_UNMATCHED = 'unmatched'
DISPOSITION_CHOICES = [
    (DISP_CREATED, 'Opened a ticket'),
    (DISP_ATTACHED, 'Joined an existing ticket'),
    (DISP_OUTAGE, 'Part of a site outage'),
    (DISP_HELD, 'Held'),
    (DISP_SUPPRESSED, 'Suppressed by maintenance'),
    (DISP_IGNORED, 'Ignored by policy'),
    (DISP_UNMATCHED, 'Customer or device not matched'),
]


class AlertTicketLink(models.Model):
    """What the alert policy did with one alert. `(connection, external_id)` is
    unique: a pushed, polled, retried or re-synced alert finds its row and
    nothing happens twice."""
    SOURCE_REM0TE = 'rem0te'
    SOURCE_RMM = 'rmm'
    source = models.CharField(max_length=10, choices=[(SOURCE_REM0TE, 'Rem0te'), (SOURCE_RMM, 'RMM sync')])
    connection = models.ForeignKey('integrations.RMMConnection', on_delete=models.CASCADE, related_name='+')
    external_id = models.CharField(max_length=255)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='+')
    device = models.ForeignKey('integrations.RMMDevice', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='+')
    endpoint_id = models.CharField(max_length=255, blank=True)
    device_name = models.CharField(max_length=255, blank=True)
    site_key = models.CharField(max_length=300, blank=True)
    site_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=20, choices=ALERT_CATEGORY_CHOICES, default='other')
    severity = models.CharField(max_length=10, choices=ALERT_SEVERITY_CHOICES, default='warning')
    state = models.CharField(max_length=15, default='open')
    title = models.CharField(max_length=300, blank=True)
    issue_key = models.CharField(max_length=300, blank=True)
    disposition = models.CharField(max_length=15, choices=DISPOSITION_CHOICES)
    hold_reason = models.CharField(max_length=20, blank=True)
    hold_until = models.DateTimeField(null=True, blank=True)
    maintenance = models.ForeignKey(AlertMaintenanceWindow, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='alert_links')
    incident = models.ForeignKey(AlertIncident, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='members')
    rule = models.ForeignKey(AlertPolicyRule, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+')
    rule_snapshot = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True,
                                help_text='Sanitised alert facts as received (staff only).')
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    occurrences = models.PositiveIntegerField(default=1)
    last_sequence = models.PositiveIntegerField(default=0)
    recovered_at = models.DateTimeField(null=True, blank=True)
    recovery_handled = models.BooleanField(default=False)
    escalated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ticket_alert_links'
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'],
                                               name='uniq_ticket_alert_link')]
        indexes = [models.Index(fields=['organization', 'issue_key', 'state']),
                   models.Index(fields=['organization', 'site_key', 'category', 'state']),
                   models.Index(fields=['disposition', 'hold_until']),
                   models.Index(fields=['ticket', 'state'])]

    def __str__(self):
        return f'{self.get_source_display()} alert {self.external_id} ({self.get_disposition_display()})'

    @property
    def is_open(self):
        return self.state != 'resolved'
