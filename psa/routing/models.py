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
DEST_NEAREST = 'nearest'
DESTINATION_CHOICES = [
    (DEST_QUEUE, 'Queue only'),
    (DEST_TECHNICIAN, 'Named technician'),
    (DEST_TEAM, 'Team'),
    (DEST_ROUND_ROBIN, 'Round-robin'),
    (DEST_SKILL, 'Skill match'),
    (DEST_LEAST_LOADED, 'Least-loaded eligible technician'),
    (DEST_NEAREST, 'Nearest eligible technician (shared position)'),
]
PICKING_DESTINATIONS = {DEST_TECHNICIAN, DEST_ROUND_ROBIN, DEST_SKILL, DEST_LEAST_LOADED, DEST_NEAREST}

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
                 sla_pct_at_least, sites (Location ids), site
                 ('any'|'set'|'unset')}
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
