"""
Native PSA / Service Desk models.

This is the OWN ticketing system, distinct from `integrations.PSATicket`
which mirrors data from third-party PSAs (Halo/Autotask/ConnectWise/etc.).

Foreign keys reference existing models discovered in INTEGRATION_MAP.md:
  - core.Organization        (tenant)
  - assets.Contact           (requester)
  - assets.Asset             (related asset)
  - vault.Password           (related credential — staff-only)
  - docs.Document            (linked doc / KB article)
  - scheduling.ScheduledTask (linked calendar event)
"""
from django.conf import settings as django_settings
from django.db import models, transaction
from django.utils import timezone


# ---------------------------------------------------------------------------
# Per-client opt-in (Phase 1 — full feature flag bedrock)
# ---------------------------------------------------------------------------

class ClientPSASettings(models.Model):
    """
    Per-org PSA configuration. PSA is off by default for every client; an
    admin must explicitly enable it. Additional client-level toggles guard
    the more sensitive surfaces (portal, anonymous tickets, ingestion).
    """
    organization = models.OneToOneField(
        'core.Organization',
        on_delete=models.CASCADE,
        related_name='psa_settings',
    )

    enabled = models.BooleanField(
        default=True,
        help_text='Enable PSA for this client. Inherits the global PSA flag — '
                  'use this to opt a specific client OUT.',
    )

    # Surface flags — every external surface defaults to OFF.
    portal_enabled = models.BooleanField(default=False, help_text='Allow this client to use the customer portal')
    anonymous_ticket_form_enabled = models.BooleanField(default=False, help_text='Allow public/anonymous ticket submission')
    email_to_ticket_enabled = models.BooleanField(default=False, help_text='Convert inbound emails to tickets')
    sms_notifications_enabled = models.BooleanField(default=False, help_text='Send SMS to staff for this client (no secrets)')
    desktop_alerts_enabled = models.BooleanField(default=False, help_text='Send desktop/browser alerts to staff for this client')
    external_alert_ingest_enabled = models.BooleanField(default=False, help_text='Accept alerts from external monitoring/RMM for this client')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_client_settings'
        verbose_name = 'Client PSA Settings'
        verbose_name_plural = 'Client PSA Settings'

    def __str__(self):
        return f'PSA settings for {self.organization} (enabled={self.enabled})'


# ---------------------------------------------------------------------------
# Reference / lookup models (seeded by `psa_seed_defaults`)
# ---------------------------------------------------------------------------

class Queue(models.Model):
    """Routing queue (e.g. Helpdesk, Escalations, Projects, Security)."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_queues'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class TicketStatus(models.Model):
    """
    Ticket workflow status (New, Assigned, In Progress, Waiting on Client,
    etc.). `is_terminal` marks closed/cancelled states for SLA logic.
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    is_terminal = models.BooleanField(default=False, help_text='True for resolved/closed/cancelled-style states')
    pauses_sla = models.BooleanField(default=False, help_text='True if SLA clock pauses while in this state')
    # Phase 20 v9 (v3.17.277): operational sign-off gate. Tickets can't
    # move INTO a status with `requires_signoff=True` unless the ticket
    # has `signed_off_at` populated.
    requires_signoff = models.BooleanField(
        default=False,
        help_text='Block transitions into this status unless the ticket '
                  'has been signed off (signed_off_at populated).',
    )
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_statuses'
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'Ticket statuses'

    def __str__(self):
        return self.name


class TicketPriority(models.Model):
    """P1..P5 priorities, plus default SLA targets in minutes."""
    code = models.CharField(max_length=10, unique=True, help_text="Short code, e.g. 'P1'")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    response_target_minutes = models.PositiveIntegerField(default=240, help_text='Default response SLA target')
    resolution_target_minutes = models.PositiveIntegerField(default=4320, help_text='Default resolution SLA target')
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_priorities'
        ordering = ['sort_order', 'code']
        verbose_name_plural = 'Ticket priorities'

    def __str__(self):
        return f'{self.code} {self.name}'


class TicketType(models.Model):
    """Incident, Service Request, Change, Problem, Project Task, etc."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_types'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------

SOURCE_CHOICES = [
    ('manual', 'Manual'),
    ('portal', 'Client Portal'),
    ('email', 'Email'),
    ('sms', 'SMS'),
    ('rmm', 'RMM'),
    ('api', 'API'),
    ('monitoring', 'Monitoring'),
    ('anonymous', 'Anonymous Form'),
    ('calendar', 'Calendar'),
    ('recurring', 'Recurring Schedule'),
]

VISIBILITY_CHOICES = [
    ('staff', 'Staff Only'),
    ('client', 'Visible to Client'),
]

IMPACT_CHOICES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
    ('critical', 'Critical'),
]

URGENCY_CHOICES = IMPACT_CHOICES  # same scale


class Ticket(models.Model):
    """
    The core PSA ticket. Field set mirrors the user spec.

    `ticket_number` is auto-generated as PSA-YYYY-NNNNNN per year on first save.
    """
    ticket_number = models.CharField(max_length=32, unique=True, db_index=True, blank=True)

    # Tenant + actors
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.CASCADE,
        related_name='native_psa_tickets',
    )
    contact = models.ForeignKey(
        'assets.Contact',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='native_psa_tickets',
        help_text='Customer-side contact who requested',
    )
    requester_name = models.CharField(max_length=200, blank=True, help_text='Free-text requester (e.g. anonymous portal)')
    requester_email = models.EmailField(blank=True)

    # Content
    subject = models.CharField(max_length=300)
    description = models.TextField(blank=True)

    # Workflow
    status = models.ForeignKey(TicketStatus, on_delete=models.PROTECT, related_name='tickets')
    priority = models.ForeignKey(TicketPriority, on_delete=models.PROTECT, related_name='tickets')
    ticket_type = models.ForeignKey(TicketType, on_delete=models.PROTECT, related_name='tickets')
    queue = models.ForeignKey(Queue, on_delete=models.PROTECT, related_name='tickets')

    assigned_to = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='psa_assigned_tickets',
    )
    assigned_team = models.CharField(max_length=100, blank=True)

    # Source / visibility
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='staff')
    client_can_view = models.BooleanField(default=False)

    # Linked context (Phase 1 wires the FKs; deeper integration in later phases)
    related_asset = models.ForeignKey(
        'assets.Asset',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='native_psa_tickets',
    )
    related_documentation = models.ForeignKey(
        'docs.Document',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='native_psa_doc_tickets',
    )
    related_kb_article = models.ForeignKey(
        'docs.Document',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='native_psa_kb_tickets',
        help_text='KB article (docs.Document with is_global=True)',
    )
    related_calendar_event = models.ForeignKey(
        'scheduling.ScheduledTask',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='native_psa_tickets',
    )
    parent_ticket = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='child_tickets',
    )
    duplicate_of = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='duplicates',
    )
    project = models.ForeignKey(
        'Project', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tickets',
        help_text='Group this ticket under a PSA project',
    )
    recurring_schedule = models.ForeignKey(
        'RecurringTicketSchedule', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='generated_tickets',
        help_text='Set when the ticket was created by a recurring schedule',
    )

    # Severity scoring
    # Phase 40.4 (v3.17.542) — status-page incidents. The flag marks a ticket
    # as one an operator intends to publish; it does not publish anything on
    # its own. Nothing reaches a public page until a StatusPageIncident is
    # created against it with a public title, because a ticket subject is
    # written for the queue, not for the customer's customers.
    is_status_page = models.BooleanField(
        default=False, db_index=True,
        help_text='Flag this ticket as a publishable incident. Publishing it '
                  'is a separate, deliberate step on a status page.')

    impact = models.CharField(max_length=20, choices=IMPACT_CHOICES, default='medium')
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES, default='medium')
    tags = models.JSONField(default=list, blank=True, help_text='List of free-form string tags')
    custom_fields = models.JSONField(default=dict, blank=True)

    # SLA tracking
    first_response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Phase 20 v9 (v3.17.277): operational sign-off — required before
    # the ticket can transition INTO any TicketStatus.requires_signoff=True.
    signed_off_at = models.DateTimeField(null=True, blank=True)
    signed_off_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='signed_off_tickets',
    )
    signoff_note = models.TextField(blank=True)
    last_client_response_at = models.DateTimeField(null=True, blank=True)
    last_tech_response_at = models.DateTimeField(null=True, blank=True)
    sla_paused_until = models.DateTimeField(null=True, blank=True)
    sla_breached_response = models.BooleanField(default=False)
    sla_breached_resolution = models.BooleanField(default=False)

    # Vendor handoff
    waiting_on_vendor = models.BooleanField(default=False)
    vendor_ticket_number = models.CharField(max_length=100, blank=True)
    vendor_contact = models.CharField(max_length=200, blank=True)

    # Phase 10.1: cache of the most recent inbound email Message-ID, used by
    # outbound replies (Phase 10.4) to set the In-Reply-To header so the
    # client's mail client threads the conversation correctly. Updated by
    # the email poller on every inbound match/create.
    # v3.17.468 — was 998, reduced to 255 to keep the InnoDB key under
    # 3072 bytes on MySQL utf8mb4 (see migration 0027).
    last_inbound_message_id = models.CharField(max_length=255, blank=True)

    # Phase 12 v6 (v3.17.236) — customer escalation workflow.
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='escalated_tickets',
    )
    escalation_reason = models.CharField(max_length=500, blank=True)

    # Closure
    CLOSURE_CATEGORIES = [
        ('fixed', 'Fixed'),
        ('workaround', 'Workaround Provided'),
        ('duplicate', 'Duplicate'),
        ('cant_reproduce', "Can't Reproduce"),
        ('no_action', 'No Action Required'),
        ('cancelled', 'Cancelled by Requester'),
        ('other', 'Other'),
    ]
    closure_category = models.CharField(max_length=30, choices=CLOSURE_CATEGORIES, blank=True)
    resolution_summary = models.TextField(blank=True, help_text='Required when closing — what was the fix?')

    # Audit columns
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='psa_tickets_created',
    )
    updated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='psa_tickets_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_native_tickets'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['assigned_to', '-created_at']),
            models.Index(fields=['priority', '-created_at']),
            models.Index(fields=['ticket_number']),
        ]

    def __str__(self):
        return f'{self.ticket_number or "PSA-?"} {self.subject}'

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self.ticket_number:
            self.ticket_number = self._generate_ticket_number()
        super().save(*args, **kwargs)

    @property
    def has_outstanding_checklist(self):
        """Phase 21 v8 (v3.17.312): True when this ticket has any
        incomplete required checklist items."""
        return self.checklist_items.filter(
            is_required=True, is_completed=False,
        ).exists()

    def sign_off(self, *, by_user, note: str = ''):
        """Phase 20 v9 (v3.17.277): record an operational sign-off.
        Stamps `signed_off_at` + `signed_off_by` so the ticket is
        eligible for transitions into `requires_signoff` statuses."""
        from django.utils import timezone as _tz
        if self.signed_off_at:
            return False  # already signed off
        self.signed_off_at = _tz.now()
        self.signed_off_by = by_user
        self.signoff_note = (note or '')[:5000]
        self.save(update_fields=['signed_off_at', 'signed_off_by',
                                  'signoff_note', 'updated_at'])
        return True

    @staticmethod
    def _generate_ticket_number():
        """
        Format: PSA-YYYY-NNNNNN, monotonically incrementing per year.
        We compute the next sequence atomically via a count on the
        current year's tickets — adequate for Phase 1 throughput. Higher-
        volume installs can swap in a dedicated counter table later.
        """
        year = timezone.now().year
        prefix = f'PSA-{year}-'
        # Find the highest existing number for this year
        last = (
            Ticket.objects
            .filter(ticket_number__startswith=prefix)
            .order_by('-ticket_number')
            .values_list('ticket_number', flat=True)
            .first()
        )
        if last:
            try:
                seq = int(last.rsplit('-', 1)[1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f'{prefix}{seq:06d}'


# ---------------------------------------------------------------------------
# Ticket comments / notes / attachments
# ---------------------------------------------------------------------------

class TicketComment(models.Model):
    """
    A reply, internal note, or system event on a ticket.

    `is_internal=True` means staff-only — MUST be filtered out of any
    client-facing surface (portal, customer reply emails). Phase 3 (portal)
    will enforce this at the queryset layer; Phase 1 simply records it.
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='psa_comments',
    )
    body = models.TextField()
    is_internal = models.BooleanField(default=False, help_text='Internal-only — never shown to the client')
    is_system = models.BooleanField(default=False, help_text='Auto-generated event (status change, etc.)')
    # Phase 12 v7 (v3.17.237): threaded conversations. Replying to a
    # specific comment sets parent_comment so the portal can render an
    # indented thread.
    parent_comment = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='replies',
    )

    # Used when the comment came from an external source (email, portal,
    # anonymous form) and there's no User to attribute. Free-text by design.
    author_name = models.CharField(max_length=200, blank=True)
    author_email = models.EmailField(blank=True)
    source = models.CharField(max_length=20, default='manual',
        help_text='manual | email | portal | api | voice | workflow')

    # Phase 21 v10 (v3.17.315): voice-to-ticket — when a tech dictates
    # via the PWA Web Speech API, the transcript lands as a comment
    # with `source='voice'` and the original audio confidence /
    # language tag in `voice_meta`.
    voice_meta = models.JSONField(
        default=dict, blank=True,
        help_text='When source=voice: {confidence, language, duration_s}',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_comments'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['ticket', 'created_at']),
            models.Index(fields=['ticket', 'is_internal']),
        ]

    def __str__(self):
        kind = 'internal note' if self.is_internal else 'reply'
        return f'{kind} on {self.ticket_id} by {self.author_id}'


def ticket_attachment_upload_to(instance, filename):
    """Tenant-scoped upload path so storage maps to the org boundary."""
    org_id = instance.ticket.organization_id if instance.ticket_id else 'orphan'
    return f'psa/{org_id}/tickets/{instance.ticket_id}/{filename}'


class TicketAttachment(models.Model):
    """
    File attached to a ticket. `is_internal` mirrors TicketComment so internal
    artifacts stay staff-only.
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='attachments')
    comment = models.ForeignKey(
        TicketComment, on_delete=models.CASCADE, null=True, blank=True,
        related_name='attachments',
        help_text='Optional — link this attachment to a specific comment',
    )
    uploaded_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='psa_attachments',
    )
    file = models.FileField(upload_to=ticket_attachment_upload_to)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    is_internal = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_attachments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ticket', '-created_at']),
        ]

    def __str__(self):
        return self.filename or f'attachment {self.pk}'


# ---------------------------------------------------------------------------
# Phase 2b — watchers + canned replies
# ---------------------------------------------------------------------------

class TicketWatcher(models.Model):
    """
    A user who has subscribed to receive email notifications about activity
    on a specific ticket. Watching is per-user, per-ticket, idempotent.
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='watchers')
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='psa_watching',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_watchers'
        unique_together = [('ticket', 'user')]
        indexes = [
            models.Index(fields=['ticket']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f'{self.user_id} watches {self.ticket_id}'


class CannedReply(models.Model):
    """
    Reusable comment template. Variable substitution at insert time:
      {{ticket.number}}, {{ticket.subject}}, {{ticket.client}},
      {{user.first_name}}, {{user.last_name}}, {{user.username}}

    `organization=None` means global (visible on every client's tickets).
    `organization=<Org>` scopes the reply to that client only.
    """
    name = models.CharField(max_length=120, help_text='Short label shown in the dropdown')
    body = models.TextField(help_text='Use {{ticket.number}}, {{ticket.subject}}, {{ticket.client}}, {{user.first_name}}, {{user.last_name}}, {{user.username}}')
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='psa_canned_replies',
        help_text='Leave blank for a global reply (every client).',
    )
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='psa_canned_replies',
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_canned_replies'
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
        ]

    def __str__(self):
        scope = self.organization.name if self.organization_id else 'global'
        return f'{self.name} ({scope})'

    def render(self, ticket=None, user=None):
        """
        Substitute {{ticket.*}} and {{user.*}} placeholders in `body`.
        Unknown placeholders are left as-is. No HTML escaping — the result
        lands in a <textarea> the staff member can edit before posting.
        """
        out = self.body
        if ticket is not None:
            out = out.replace('{{ticket.number}}', ticket.ticket_number or '')
            out = out.replace('{{ticket.subject}}', ticket.subject or '')
            out = out.replace('{{ticket.client}}', ticket.organization.name if ticket.organization_id else '')
        if user is not None:
            out = out.replace('{{user.first_name}}', user.first_name or '')
            out = out.replace('{{user.last_name}}', user.last_name or '')
            out = out.replace('{{user.username}}', user.username or '')
        return out


# ---------------------------------------------------------------------------
# Phase 2c — time tracking + service catalog + hygiene
# ---------------------------------------------------------------------------

class TicketTimeEntry(models.Model):
    """
    Time logged against a ticket. Supports running-timer entries
    (started_at set, ended_at null) and finalised manual entries.
    Approval flow added in Phase 25 (v3.17.242) via the
    `TimesheetSubmission` join below.
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='time_entries')
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='psa_time_entries',
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=0,
        help_text='Computed on save when ended_at is set')
    is_billable = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    # Phase 21 v6 (v3.17.315): GPS time tracking — coords captured by
    # the PWA at start/stop. Lets the dispatcher see "tech started this
    # at the customer's address, ended back at the office."
    start_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                      null=True, blank=True)
    start_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                      null=True, blank=True)
    end_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                    null=True, blank=True)
    end_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                    null=True, blank=True)

    # Phase 25 (v3.17.242): batch approval. When a TimesheetSubmission is
    # created, all of the tech's time entries in that period get the
    # `submission` FK set so the staff approver can see the bundle.
    submission = models.ForeignKey(
        'psa.TimesheetSubmission', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='entries',
        help_text='Weekly batch this entry belongs to. Null = unsubmitted.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ticket_time_entries'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['ticket', '-started_at']),
            models.Index(fields=['user', '-started_at']),
            models.Index(fields=['ticket', 'is_billable']),
        ]
        constraints = [
            # Prevent two running timers on the same ticket for the same user.
            models.UniqueConstraint(
                fields=['ticket', 'user'],
                condition=models.Q(ended_at__isnull=True),
                name='psa_one_running_timer_per_user_per_ticket',
            ),
        ]

    def __str__(self):
        return f'{self.user_id} on ticket {self.ticket_id}: {self.duration_minutes}m'

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        was_running = False
        prior_duration = 0
        if not is_new:
            prior = TicketTimeEntry.objects.filter(pk=self.pk).only(
                'duration_minutes', 'ended_at', 'submission_id',
            ).first()
            if prior:
                was_running = prior.ended_at is None
                prior_duration = prior.duration_minutes or 0
                # Phase 25 v2 (v3.17.249): lock entries attached to an
                # approved TimesheetSubmission. Caller can pass
                # `_force_unlock=True` for admin overrides; otherwise the
                # save is silently a no-op via early return.
                if (prior.submission_id
                        and not kwargs.pop('_force_unlock', False)):
                    try:
                        sub = TimesheetSubmission.objects.only('status').get(
                            pk=prior.submission_id,
                        )
                        if sub.status == 'approved':
                            return
                    except Exception:
                        pass

        if self.ended_at and self.started_at and not self.duration_minutes:
            delta = self.ended_at - self.started_at
            self.duration_minutes = max(0, int(delta.total_seconds() // 60))
        super().save(*args, **kwargs)

        # Contract hour accounting: only on transitions from running→stopped
        # or on initial create with a duration. Skip while still running.
        if self.duration_minutes and self.ended_at:
            from django.db.models import F
            try:
                contract = Contract.for_ticket(self.ticket)
            except (NameError, AttributeError):
                contract = None
            if contract:
                delta_min = self.duration_minutes - (prior_duration if not was_running else 0)
                if delta_min > 0:
                    Contract.objects.filter(pk=contract.pk).update(
                        hours_used_minutes=F('hours_used_minutes') + delta_min,
                    )

    @property
    def is_running(self):
        return self.ended_at is None


class ServiceCatalogItem(models.Model):
    """
    Predefined ticket template — admin or ticket creator picks one and
    a partly-filled ticket is created. Common MSP requests live here:
    New User, Terminate User, Password Reset, etc. Seeded by the
    psa_seed_defaults command.
    """
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True,
        help_text='Shown in the catalog grid')
    default_subject = models.CharField(max_length=300, blank=True)
    default_body = models.TextField(blank=True)
    default_priority = models.ForeignKey(
        TicketPriority, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items',
    )
    default_queue = models.ForeignKey(
        Queue, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items',
    )
    default_type = models.ForeignKey(
        TicketType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items',
    )
    icon = models.CharField(max_length=80, blank=True,
        help_text='Font Awesome class, e.g. "fas fa-user-plus"')
    fields_json = models.JSONField(
        default=list, blank=True,
        help_text='List of {key, label, type, required, placeholder, options, help} '
                  'objects describing the structured fields the requester fills in. '
                  'Field values substitute into default_subject + default_body via '
                  '{{key}} placeholders. Supported types: text, email, date, '
                  'number, textarea, select, checkbox.',
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Governance (Phase 6.3 — v3.17.165)
    requires_approval = models.BooleanField(
        default=False,
        help_text='When true, edits require approval via ServiceCatalogChange '
                  'before publishing.',
    )
    last_published_at = models.DateTimeField(null=True, blank=True)
    last_published_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    @staticmethod
    def render_template(template, values):
        """{{key}} → values[key] substitution. Unfilled placeholders are stripped."""
        if not template:
            return ''
        import re as _re
        out = template
        for k, v in (values or {}).items():
            out = out.replace('{{' + str(k) + '}}', str(v) if v is not None else '')
        out = _re.sub(r'\{\{\s*[a-zA-Z0-9_]+\s*\}\}', '', out)
        return out

    class Meta:
        db_table = 'psa_service_catalog_items'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Phase 3 — Projects (Workstream 3)
# ---------------------------------------------------------------------------

class Project(models.Model):
    """
    Lightweight PSA project. Groups tickets under a named delivery effort
    so techs can see all related work in one place. Optional client_org
    scopes the project to a specific customer organization (when null,
    the project is internal to the MSP tenant).

    NOT a full project-management replacement — for a deep PM tool, link
    to the existing `processes/` workflows. This model is the answer to
    "show me everything we're doing for ACME this quarter".
    """
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_projects',
        help_text='MSP tenant that owns the project',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_client_projects',
        help_text='Client organization the project is for (null = internal)',
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning')

    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    owner = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='owned_psa_projects',
    )
    is_billable = models.BooleanField(default=True)
    estimated_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_projects'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['client_org', 'status']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            from django.utils.text import slugify
            base = slugify(self.name)[:200] or 'project'
            slug = base
            n = 2
            while Project.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Recurring tickets (preventive maintenance) — Workstream 1 queued item
# ---------------------------------------------------------------------------

class RecurringTicketSchedule(models.Model):
    """
    Cron-driven creation of routine maintenance tickets.

    The `psa_run_recurring_tickets` management command (run hourly via
    cron / systemd timer) finds schedules whose next_run_at <= now and
    is_active=True, creates a fresh Ticket from the template, and rolls
    next_run_at forward by one frequency interval.
    """
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_recurring_schedules',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_client_recurring_schedules',
        help_text='Client the recurring ticket targets (null = internal/MSP)',
    )

    name = models.CharField(max_length=200, help_text='Internal name for this schedule')
    template_subject = models.CharField(max_length=300)
    template_body = models.TextField(blank=True)

    queue = models.ForeignKey(Queue, on_delete=models.PROTECT, related_name='recurring_schedules')
    priority = models.ForeignKey(TicketPriority, on_delete=models.PROTECT, related_name='recurring_schedules')
    ticket_type = models.ForeignKey(TicketType, on_delete=models.PROTECT, related_name='recurring_schedules')
    assigned_to = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recurring_schedules',
    )

    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    interval = models.PositiveIntegerField(default=1,
        help_text='Run every N units (e.g. interval=2, frequency=weekly = every 2 weeks)')

    is_active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_recurring_schedules',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_recurring_schedules'
        ordering = ['next_run_at']
        indexes = [
            models.Index(fields=['is_active', 'next_run_at']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_frequency_display()} ×{self.interval})'

    def advance_next_run(self):
        """Advance `next_run_at` by one frequency-interval step."""
        from datetime import timedelta
        from dateutil.relativedelta import relativedelta  # already in deps via icalendar
        base = self.next_run_at or timezone.now()
        if self.frequency == 'daily':
            self.next_run_at = base + timedelta(days=self.interval)
        elif self.frequency == 'weekly':
            self.next_run_at = base + timedelta(weeks=self.interval)
        elif self.frequency == 'monthly':
            self.next_run_at = base + relativedelta(months=self.interval)
        elif self.frequency == 'quarterly':
            self.next_run_at = base + relativedelta(months=3 * self.interval)
        elif self.frequency == 'yearly':
            self.next_run_at = base + relativedelta(years=self.interval)


# ---------------------------------------------------------------------------
# Knowledge Base linking — the docs app already provides KB-style articles
# (docs.Document with is_global=True), but ticket↔article was a single FK.
# This through model lets a ticket attach to multiple KB articles.
# ---------------------------------------------------------------------------

class TicketKBLink(models.Model):
    """Many-to-many linkage between PSA tickets and docs.Document KB articles."""
    ticket = models.ForeignKey('Ticket', on_delete=models.CASCADE, related_name='kb_links')
    article = models.ForeignKey('docs.Document', on_delete=models.CASCADE,
                                related_name='psa_ticket_links')
    linked_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='kb_links_created',
    )
    note = models.CharField(max_length=300, blank=True,
        help_text='Optional context on why this article was linked')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_kb_links'
        unique_together = [['ticket', 'article']]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.ticket.ticket_number} ↔ {self.article_id}'


# ---------------------------------------------------------------------------
# Approvals — generic manager-approval gate for time, expenses, quotes,
# AI actions, distributor orders, etc.
# ---------------------------------------------------------------------------

class PSAApproval(models.Model):
    """
    Generic approval record. Any PSA workflow that needs a manager sign-off
    can create one of these and reference it by (object_type, object_id).
    """
    KIND_CHOICES = [
        ('time', 'Time entry'),
        ('expense', 'Expense'),
        ('quote', 'Quote / estimate'),
        ('order', 'Distributor order'),
        ('action', 'AI action'),
        ('change', 'Change / scope'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('cancelled', 'Cancelled'),
        # Phase 20 v3 (v3.17.265): chained approvals — a blocked stage is
        # waiting for an earlier stage in the chain to be approved.
        ('blocked', 'Blocked (waiting on prior stage)'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_approvals',
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    object_type = models.CharField(max_length=80,
        help_text='app_label.ModelName of the thing being approved')
    object_id = models.PositiveIntegerField()
    object_repr = models.CharField(max_length=300, blank=True)

    requested_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_approvals_requested',
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    request_comment = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    decided_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_approvals_decided',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.TextField(blank=True)

    related_ticket = models.ForeignKey(
        'Ticket', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approvals',
        help_text='If the approval is tied to a specific ticket',
    )

    # Phase 12 v9 (v3.17.239): customer approval workflow.
    # When True, this approval is routed to the client (via the portal)
    # rather than to internal staff. Examples: customer-side sign-off on
    # a SOW, approval to spend over an MSA cap, etc.
    is_client_approval = models.BooleanField(default=False)

    # Phase 20 v1 (v3.17.256): escalation-on-idle cron.
    escalation_threshold_hours = models.PositiveIntegerField(
        default=48,
        help_text='Approvals still pending after this many hours get '
                  'flagged in the daily escalation digest. 0 = never '
                  'escalate.',
    )
    escalated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the escalation digest mentioned this approval. '
                  'Set by `psa_escalate_idle_approvals` so an approval '
                  'isn\'t escalated repeatedly.',
    )

    # Phase 20 v3 (v3.17.265): multi-stage / chained approval support.
    parent_approval = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True, related_name='next_stages',
        help_text='When set, this approval is a stage in a chain — it '
                  'cannot leave `blocked` until the parent is approved.',
    )
    stage_index = models.PositiveSmallIntegerField(
        default=0,
        help_text='0 for stand-alone approvals; 1+ for chain stages '
                  '(stage 1 starts as "pending", later stages start "blocked").',
    )

    class Meta:
        db_table = 'psa_approvals'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-requested_at']),
            models.Index(fields=['object_type', 'object_id']),
            models.Index(fields=['is_client_approval', 'status']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} #{self.pk} — {self.get_status_display()}'

    def decide(self, *, user, approved: bool, comment: str = ''):
        if self.status == 'blocked':
            raise ValueError('This approval is waiting on an earlier stage; '
                             'approve the prior stage first.')
        self.status = 'approved' if approved else 'denied'
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_comment = comment[:5000]
        self.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_comment'])

        # Phase 20 v6 (v3.17.274): write the decision to AuditLog so the
        # trail is complete regardless of caller (UI / API / signal).
        self._log_audit('update',
                        f'{self.get_status_display()} {self.get_kind_display()} '
                        f'approval #{self.pk} (stage {self.stage_index})',
                        user=user)

        # Phase 20 v3: cascade through the chain.
        if approved:
            # Unblock the next blocked stage in this chain (lowest
            # stage_index among children of THIS row).
            nxt = (self.next_stages.filter(status='blocked')
                   .order_by('stage_index').first())
            if nxt is not None:
                nxt.status = 'pending'
                nxt.save(update_fields=['status'])
                nxt._log_audit('update',
                               f'Auto-unblocked approval #{nxt.pk} '
                               f'(stage {nxt.stage_index}) after parent '
                               f'#{self.pk} approved',
                               user=user)
        else:
            # Denial cancels all downstream blocked stages so they
            # don't sit in the queue forever.
            self._cancel_downstream_blocked(triggered_by_user=user)

    def _cancel_downstream_blocked(self, *, triggered_by_user=None):
        for child in self.next_stages.filter(status='blocked'):
            child.status = 'cancelled'
            child.decision_comment = (
                f'Auto-cancelled — prior stage #{self.pk} was denied'
            )[:5000]
            child.save(update_fields=['status', 'decision_comment'])
            child._log_audit('update',
                             f'Auto-cancelled stage {child.stage_index} '
                             f'(approval #{child.pk}) after prior stage '
                             f'#{self.pk} denied',
                             user=triggered_by_user)
            child._cancel_downstream_blocked(triggered_by_user=triggered_by_user)

    def _log_audit(self, action: str, description: str, *, user=None):
        """Phase 20 v6 helper — best-effort write to `audit.AuditLog`.
        Failures are swallowed so an audit-store outage can't block an
        approval decision."""
        try:
            from audit.models import AuditLog
            AuditLog.log(
                user=user, action=action,
                organization=self.organization,
                object_type='psa.PSAApproval', object_id=self.pk,
                object_repr=str(self),
                description=description[:500],
            )
        except Exception:
            import logging
            logging.getLogger('psa').exception('PSAApproval audit log failed')

    def history(self):
        """Return the AuditLog rows for this approval, newest-first.
        Useful on a per-approval audit page."""
        try:
            from audit.models import AuditLog
            return list(AuditLog.objects.filter(
                object_type='psa.PSAApproval',
                object_id=self.pk,
            ).order_by('-timestamp')[:200])
        except Exception:
            return []

    @classmethod
    def create_chain(cls, *, organization, kind, object_type, object_id,
                     object_repr='', requested_by=None, stages):
        """Phase 20 v3: factory that creates a multi-stage approval chain.

        ``stages`` is an ordered iterable of dicts; each dict may include
        any field on PSAApproval except parent_approval / stage_index /
        status (those are set by this method).

        Stage 1 is created as 'pending'; subsequent stages are 'blocked'
        and parented to the prior stage. Returns the list of created
        approvals in stage order.
        """
        if not stages:
            raise ValueError('Chain must have at least one stage')
        created = []
        for idx, stage_kwargs in enumerate(stages, start=1):
            kwargs = dict(stage_kwargs)
            kwargs.update({
                'organization': organization,
                'kind': kind,
                'object_type': object_type,
                'object_id': object_id,
                'object_repr': object_repr or kwargs.pop('object_repr', ''),
                'requested_by': requested_by,
                'parent_approval': created[-1] if created else None,
                'stage_index': idx,
                'status': 'pending' if idx == 1 else 'blocked',
            })
            created.append(cls.objects.create(**kwargs))
        # Phase 20 v6: log the chain creation against the FIRST stage so
        # there's a single anchor row for the chain in AuditLog.
        if created:
            created[0]._log_audit(
                'create',
                f'Created {len(created)}-stage approval chain for '
                f'{object_type}#{object_id}',
                user=requested_by,
            )
        return created


# ---------------------------------------------------------------------------
# Workstream 5 — Contracts (block hours, retainer, managed services)
# ---------------------------------------------------------------------------

class Contract(models.Model):
    """
    MSP contract with a client. Tracks an hours allowance + per-priority
    SLA overrides. The PSA SLA engine consults the active contract for
    a ticket's organization before falling back to the global queue
    SLA defaults.

    The `hours_used_minutes` field is incremented by `TicketTimeEntry.save()`
    when an entry's ticket belongs to a client_org with an active contract.
    """
    CONTRACT_TYPES = [
        ('block_hours', 'Block of Hours'),
        ('retainer', 'Monthly Retainer'),
        ('managed_services', 'Managed Services'),
        ('per_incident', 'Per-Incident'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_msp_contracts',
        help_text='MSP tenant that owns the contract',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_client_contracts',
        help_text='Client the contract is with',
    )
    name = models.CharField(max_length=200)
    contract_type = models.CharField(max_length=30, choices=CONTRACT_TYPES, default='block_hours')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True,
        help_text='Open-ended if blank')

    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0,
        help_text='Allowance for block_hours / retainer; 0 for unlimited')
    hours_used_minutes = models.PositiveIntegerField(default=0,
        help_text='Auto-incremented by TicketTimeEntry; minutes for precision')
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
        help_text='Effective rate when consuming or overaging')
    overage_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0,
        help_text='Rate for hours beyond total_hours (defaults to hourly_rate when 0)')

    # --- Phase 1: rollover, auto-renew, role gates, parent linkage --------
    rollover_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='% of unused hours that roll into the next period when this '
                  'contract auto-renews (0–100). 0 = no rollover.',
    )
    rollover_expiry_days = models.PositiveIntegerField(
        default=0,
        help_text='Days after the new period start that rolled-over hours '
                  'expire. 0 = never expire.',
    )
    rolled_over_minutes = models.PositiveIntegerField(
        default=0,
        help_text='Minutes carried over from the prior period (auto-set by '
                  'the renewal cron). Consumed before total_hours.',
    )
    rollover_expires_at = models.DateField(
        null=True, blank=True,
        help_text='Date when carried-over minutes expire (set by renewal '
                  'cron from rollover_expiry_days).',
    )
    auto_renew = models.BooleanField(
        default=False,
        help_text='When true, the renewal cron auto-creates the next period '
                  'on end_date and applies rollover/proration.',
    )
    auto_renew_period_months = models.PositiveSmallIntegerField(
        default=12,
        help_text='Length of each auto-renewed period in months.',
    )
    # Phase 15 v1 (v3.17.291) — recurring billing schedule. When the
    # cadence is non-`none`, `psa_generate_recurring_invoices` cron
    # auto-generates a draft Invoice for the period on `next_billing_date`.
    BILLING_FREQUENCY_CHOICES = [
        ('none', 'No recurring billing'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]
    billing_frequency = models.CharField(
        max_length=20, choices=BILLING_FREQUENCY_CHOICES, default='none',
        help_text='How often a draft Invoice is auto-generated for this '
                  'contract. Set to "none" to disable recurring billing.',
    )
    next_billing_date = models.DateField(
        null=True, blank=True,
        help_text='Next date the recurring-invoice cron should fire. '
                  'Auto-advanced after each generation.',
    )
    recurring_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Per-period billing amount. When 0, derived from '
                  '`total_hours * hourly_rate` for retainer-style contracts.',
    )
    last_billed_at = models.DateField(
        null=True, blank=True,
        help_text='Date of the most recent recurring-invoice generation.',
    )

    # Phase 15 v13 (v3.17.298) — subscription lifecycle. `paused_at` /
    # `paused_until` are non-null when the contract is paused; the
    # recurring-invoice cron skips paused contracts. `cancel_at_period_end`
    # flips the contract to `cancelled` after the next billing date,
    # giving the customer their full paid-up period without renewal.
    paused_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the contract was paused. Non-null = paused.',
    )
    paused_until = models.DateField(
        null=True, blank=True,
        help_text='Optional auto-resume date — `psa_advance_subscription_lifecycle` '
                  'cron clears the pause when today >= this date.',
    )
    cancel_at_period_end = models.BooleanField(
        default=False,
        help_text='When True, the lifecycle cron transitions the '
                  'contract to `cancelled` after the next billing date.',
    )
    proration_enabled = models.BooleanField(
        default=False,
        help_text='When true, mid-month start/cancel prorates the allowance '
                  'based on days active in the period.',
    )
    billable_role_codes = models.JSONField(
        default=list, blank=True,
        help_text='List of role codes whose time entries count against this '
                  'contract\'s allowance. Empty list = all roles count.',
    )
    excluded_role_codes = models.JSONField(
        default=list, blank=True,
        help_text='List of role codes whose time entries bypass this contract '
                  '(e.g. project work). Wins over billable_role_codes.',
    )
    parent_contract = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='renewals',
        help_text='Previous-period contract this one rolled forward from.',
    )

    # Per-priority SLA matrix overrides queue defaults.
    # Schema: {"priority_slug": {"response_minutes": int, "resolution_minutes": int}, ...}
    sla_matrix = models.JSONField(default=dict, blank=True)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_psa_contracts',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_contracts'
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['organization', 'client_org', 'status']),
        ]

    def __str__(self):
        return f'{self.client_org.name} — {self.name} ({self.get_contract_type_display()})'

    @property
    def hours_used(self):
        return round(self.hours_used_minutes / 60.0, 2)

    @property
    def hours_remaining(self):
        if not self.total_hours:
            return None  # unlimited
        return max(0, float(self.total_hours) - self.hours_used)

    @property
    def is_currently_active(self):
        if self.status != 'active':
            return False
        today = timezone.now().date()
        if self.start_date and self.start_date > today:
            return False
        if self.end_date and self.end_date < today:
            return False
        return True

    @property
    def effective_recurring_amount(self):
        """Phase 15 v1 (v3.17.291): the dollar amount for this billing
        period. If `recurring_amount` is set explicitly, use that;
        otherwise fall back to `total_hours * hourly_rate` for
        retainer/managed-services contracts."""
        from decimal import Decimal as _D
        if self.recurring_amount and self.recurring_amount > 0:
            return _D(str(self.recurring_amount))
        if self.total_hours and self.hourly_rate:
            return (_D(str(self.total_hours)) * _D(str(self.hourly_rate))).quantize(_D('0.01'))
        return _D('0')

    @staticmethod
    def _advance_billing(date_in, frequency: str):
        from datetime import timedelta as _td
        from dateutil.relativedelta import relativedelta as _rd
        if frequency == 'monthly':
            return date_in + _rd(months=1)
        if frequency == 'quarterly':
            return date_in + _rd(months=3)
        if frequency == 'yearly':
            return date_in + _rd(years=1)
        return None  # 'none' — billing disabled

    def _proration_factor(self, period_start, frequency: str):
        """Phase 15 v4 (v3.17.293): when `proration_enabled=True` AND
        this is the first invoice (last_billed_at is None) AND the
        contract started mid-period, compute the proration factor
        (days_active_in_period / days_in_period). Returns 1.0 in all
        other cases — full period billing.
        """
        from datetime import timedelta as _td
        from dateutil.relativedelta import relativedelta as _rd
        if not self.proration_enabled or self.last_billed_at:
            return 1.0
        if not self.start_date or self.start_date <= period_start:
            return 1.0
        # The active period is [period_start, period_end)
        if frequency == 'monthly':
            period_end = period_start + _rd(months=1)
        elif frequency == 'quarterly':
            period_end = period_start + _rd(months=3)
        elif frequency == 'yearly':
            period_end = period_start + _rd(years=1)
        else:
            return 1.0
        # Effective period for THIS contract starts at start_date
        active_start = max(self.start_date, period_start)
        total_days = (period_end - period_start).days
        active_days = (period_end - active_start).days
        if total_days <= 0:
            return 1.0
        return max(0.0, min(1.0, active_days / total_days))

    def generate_invoice(self, *, on_date=None, user=None):
        """Phase 15 v1 (v3.17.291) + v2 (v3.17.292) + v4 (v3.17.293):
        create a draft Invoice for this contract's current billing
        period. Returns the new invoice (or None when billing is
        disabled AND no usage-based meters have positive quantity).
        Includes:

        - Base recurring line item, prorated when proration_enabled
          and this is the first invoice for a mid-period start
        - One line item per active `ContractMeter` with
          `current_quantity > 0` (NOT prorated — usage is what it is)

        After successful generation the meters' `current_quantity` is
        zeroed and `last_billed_at` stamped.
        """
        from datetime import date as _d
        from decimal import Decimal as _D
        if self.billing_frequency == 'none':
            return None
        on_date = on_date or _d.today()
        amount = self.effective_recurring_amount
        usage = self.usage_line_items()
        if amount <= 0 and not usage:
            return None

        # Phase 15 v4: prorate the base amount when applicable
        proration = self._proration_factor(on_date, self.billing_frequency)
        prorated_amount = (_D(str(amount)) * _D(str(proration))).quantize(_D('0.01'))

        inv = Invoice.objects.create(
            organization=self.organization,
            client_org=self.client_org,
            title=f'{self.name} — {self.get_billing_frequency_display()} {on_date:%Y-%m}',
            invoice_date=on_date,
            currency='USD',
            source_contract=self,
            created_by=user,
        )
        if prorated_amount > 0:
            descr = (f'{self.get_contract_type_display()} — '
                     f'{self.get_billing_frequency_display()} period '
                     f'{on_date:%Y-%m-%d}')
            if proration < 1.0:
                descr += f' (prorated {proration:.2%})'
            InvoiceLineItem.objects.create(
                invoice=inv,
                description=descr,
                quantity=1,
                unit_price=prorated_amount,
                source='contract',
                source_id=str(self.pk),
            )
        # Phase 15 v2: usage-based line items
        for u in usage:
            InvoiceLineItem.objects.create(
                invoice=inv,
                description=u['description'][:300],
                quantity=u['quantity'],
                unit_price=u['unit_price'],
                source='contract',
                source_id=f'meter:{u["meter_id"]}',
            )
        inv.recompute_totals()

        # Reset meter counters after billing them
        from datetime import datetime as _dt
        from django.utils import timezone as _tz
        for meter in self.meters.filter(is_active=True):
            if (meter.current_quantity or 0) > 0:
                meter.current_quantity = 0
                meter.last_billed_at = _tz.now()
                meter.save(update_fields=['current_quantity',
                                            'last_billed_at', 'updated_at'])
        return inv

    def pause(self, *, until=None):
        """Phase 15 v13 (v3.17.298): pause the contract. The recurring-
        invoice cron skips paused contracts. `until` (optional Date)
        gates auto-resume by `psa_advance_subscription_lifecycle`."""
        from django.utils import timezone as _tz
        if self.paused_at:
            return False  # already paused
        self.paused_at = _tz.now()
        self.paused_until = until
        self.save(update_fields=['paused_at', 'paused_until', 'updated_at'])
        return True

    def resume(self):
        """Phase 15 v13 (v3.17.298): resume a paused contract. Idempotent
        — returns False if not paused."""
        if not self.paused_at:
            return False
        self.paused_at = None
        self.paused_until = None
        self.save(update_fields=['paused_at', 'paused_until', 'updated_at'])
        return True

    def cancel_at_end_of_period(self):
        """Phase 15 v13 (v3.17.298): flag for auto-cancel at the next
        billing date. Customer keeps the paid-up period."""
        self.cancel_at_period_end = True
        self.save(update_fields=['cancel_at_period_end', 'updated_at'])

    def usage_line_items(self):
        """Phase 15 v2 (v3.17.292): generate one InvoiceLineItem-spec
        dict per active ContractMeter for this contract — used by
        `generate_invoice()` to add usage-based line items alongside
        the base recurring amount."""
        from decimal import Decimal as _D
        out = []
        for meter in self.meters.filter(is_active=True):
            qty = _D(str(meter.current_quantity or 0))
            if qty <= 0:
                continue
            out.append({
                'description': f'{meter.name} ({meter.get_unit_display()}) — '
                               f'{qty:g} × ${meter.unit_price}',
                'quantity': qty,
                'unit_price': meter.unit_price,
                'meter_id': meter.pk,
            })
        return out

    @classmethod
    def for_ticket(cls, ticket):
        """Return the active contract for a ticket's client (None if none)."""
        if not ticket or not ticket.organization_id:
            return None
        today = timezone.now().date()
        return cls.objects.filter(
            client_org=ticket.organization,
            status='active',
            start_date__lte=today,
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        ).first()

    # ----- Phase 1 helpers -------------------------------------------------

    def effective_total_minutes(self):
        """Allowance + un-expired rolled-over minutes (in minutes)."""
        base = int(float(self.total_hours or 0) * 60)
        rolled = self.rolled_over_minutes or 0
        if self.rollover_expires_at and timezone.now().date() > self.rollover_expires_at:
            rolled = 0
        return base + rolled

    def effective_hours_remaining(self):
        """Hours remaining after considering rollover + expiry. None=unlimited."""
        if not self.total_hours and not self.rolled_over_minutes:
            return None
        avail = self.effective_total_minutes() - (self.hours_used_minutes or 0)
        return round(max(0, avail) / 60.0, 2)

    def is_role_billable(self, role_code: str) -> bool:
        """
        Decide whether a time entry from a tech with `role_code` should count
        against this contract.

        Excluded list wins over included; an empty included list means "all".
        Role codes are user-supplied tags (e.g. "T1", "T2", "T3", "project")
        — they're not modelled as a foreign key on purpose, so MSPs can carve
        their own tiers without schema churn.
        """
        if role_code in (self.excluded_role_codes or []):
            return False
        included = self.billable_role_codes or []
        if not included:
            return True
        return role_code in included

    def bundled_subtotal(self):
        """Sum of `quantity * unit_price` across all bundle line items."""
        from decimal import Decimal
        total = Decimal('0')
        for it in self.bundle_items.all():
            total += (it.quantity or Decimal('0')) * (it.unit_price or Decimal('0'))
        return total

    def profitability_snapshot(self):
        """
        Coarse profitability dict for the active period. Revenue = invoiced
        amount tied to this client (period-aware). Cost = hours_used × an
        assumed loaded rate (TODO Phase 3: per-tech cost rate). Margin in %.
        """
        from decimal import Decimal
        # Revenue: bundled subtotal + (hours_used × hourly_rate) +
        #         (overage_minutes × overage_rate). Approximate.
        bundled = self.bundled_subtotal()
        hours_used = Decimal(str(self.hours_used or 0))
        billed_hours = min(hours_used, self.total_hours or hours_used)
        overage_hours = max(Decimal('0'), hours_used - (self.total_hours or hours_used))
        revenue = (
            bundled
            + billed_hours * (self.hourly_rate or Decimal('0'))
            + overage_hours * ((self.overage_rate or self.hourly_rate) or Decimal('0'))
        )
        # Cost: placeholder — Phase 3 wires per-tech loaded rates. For now
        # assume 60% of hourly_rate as cost-of-delivery.
        assumed_cost_rate = (self.hourly_rate or Decimal('0')) * Decimal('0.60')
        cost = hours_used * assumed_cost_rate
        margin = revenue - cost
        margin_pct = float((margin / revenue) * 100) if revenue else 0.0
        return {
            'revenue': float(revenue),
            'cost': float(cost),
            'margin': float(margin),
            'margin_pct': round(margin_pct, 1),
            'hours_used': float(hours_used),
            'overage_hours': float(overage_hours),
        }


class ContractMeter(models.Model):
    """Phase 15 v2 (v3.17.292): usage-based billing meter attached to a
    Contract. Common patterns:
      - Per-seat (M365 / VOIP / RMM): `unit='seat'`, increment when a
        new user is provisioned.
      - Per-device (RMM agents, network ports): `unit='device'`.
      - Per-GB (backup storage, log archive): `unit='gb'`, increment by
        actual usage from monitoring.

    `current_quantity` accumulates between billings. After
    `Contract.generate_invoice()` adds the meter as a line item, the
    counter resets to 0 and `last_billed_at` is stamped.
    """
    UNIT_CHOICES = [
        ('seat', 'Seat / user'),
        ('device', 'Device / endpoint'),
        ('gb', 'GB (storage / bandwidth)'),
        ('hour', 'Hour'),
        ('item', 'Generic item'),
    ]

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE,
        related_name='meters',
    )
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='seat')
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    current_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Accumulated since last billing. Reset after invoice generation.',
    )
    is_active = models.BooleanField(default=True)
    last_billed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_contract_meters'
        ordering = ['name']
        indexes = [
            models.Index(fields=['contract', 'is_active']),
        ]

    def __str__(self):
        return f'{self.contract.name} — {self.name} ({self.get_unit_display()})'

    def increment(self, amount):
        """Add `amount` units to `current_quantity` atomically."""
        from decimal import Decimal as _D
        from django.db.models import F
        ContractMeter.objects.filter(pk=self.pk).update(
            current_quantity=F('current_quantity') + _D(str(amount)),
        )
        self.refresh_from_db(fields=['current_quantity'])


class ContractBundleItem(models.Model):
    """
    A line item bundled into a Contract — e.g. "Managed AV (per seat)" or
    "M365 backup (per mailbox)". One contract has many bundle items;
    `bundled_subtotal()` rolls them up for billing + profitability views.

    Recurring period drives forecasting (Phase 3 will use it for monthly
    revenue projection). For now it's just metadata.
    """
    PERIOD_CHOICES = [
        ('one_time', 'One-time'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]
    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='bundle_items',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_label = models.CharField(
        max_length=40, blank=True,
        help_text='e.g. "seat", "device", "mailbox" — display only.',
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recurring_period = models.CharField(
        max_length=20, choices=PERIOD_CHOICES, default='monthly',
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_contract_bundle_items'
        ordering = ['sort_order', 'pk']

    def __str__(self):
        return f'{self.name} × {self.quantity}'

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)


# ---------------------------------------------------------------------------
# Email ingestion — Workstream 1 queued: email-to-ticket
# ---------------------------------------------------------------------------

class EmailIngestionConfig(models.Model):
    """
    Per-organization IMAP mailbox. The `psa_poll_email` management command
    connects, parses unread messages, creates tickets (or appends comments
    to existing tickets when the subject contains a ticket number), and
    marks messages as read.

    Password is encrypted at rest using the same vault.encryption helpers
    as integrations/RMM credentials.
    """
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='email_ingestion_configs',
    )
    name = models.CharField(max_length=200)

    # Message source (issue #142). 'imap' = classic IMAP polling (fields below);
    # 'graph' = Microsoft 365 mailbox via Graph API (reuses an M365Connection's
    # app-registration credentials — for tenants that can't enable IMAP).
    SOURCE_IMAP = 'imap'
    SOURCE_GRAPH = 'graph'
    SOURCE_CHOICES = [
        (SOURCE_IMAP, 'IMAP'),
        (SOURCE_GRAPH, 'Microsoft 365 (Graph API)'),
    ]
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_IMAP)

    # IMAP fields (blank when source='graph').
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.PositiveIntegerField(default=993)
    use_ssl = models.BooleanField(default=True)
    username = models.CharField(max_length=255, blank=True)
    encrypted_password = models.TextField(blank=True)
    folder = models.CharField(max_length=100, default='INBOX')

    # Graph fields (used when source='graph').
    m365_connection = models.ForeignKey(
        'integrations.M365Connection', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='email_ingestion_configs',
        help_text='M365 tenant connection whose app registration is used for '
                  'mailbox access (needs the Mail.Read application permission).',
    )
    graph_mailbox = models.CharField(
        max_length=320, blank=True,
        help_text='Shared mailbox / user UPN to poll via Graph, e.g. support@contoso.com',
    )

    # Outbound transport (issue #142 outbound). 'smtp' keeps the existing
    # Django email-backend send (default — no existing customer changes).
    # 'graph' sends via Microsoft Graph sendMail/reply on the same M365
    # connection + mailbox (needs the Mail.Send application permission,
    # scoped via Exchange Online RBAC for Applications).
    OUTBOUND_SMTP = 'smtp'
    OUTBOUND_GRAPH = 'graph'
    OUTBOUND_CHOICES = [
        (OUTBOUND_SMTP, 'SMTP (existing)'),
        (OUTBOUND_GRAPH, 'Microsoft Graph'),
    ]
    outbound_method = models.CharField(
        max_length=10, choices=OUTBOUND_CHOICES, default=OUTBOUND_SMTP,
        help_text='How staff replies are sent. Graph requires an M365 connection + mailbox.',
    )
    # Set when a Test Outbound send returns HTTP 202 — drives the "send
    # authorization" status indicator without re-sending on every page load.
    graph_send_verified_at = models.DateTimeField(null=True, blank=True)
    graph_send_last_error = models.CharField(max_length=300, blank=True)
    # Only used when outbound_method='graph': permit a pre-submission fall back
    # to SMTP when Graph is known-unavailable (never AFTER a Graph submission —
    # that risks duplicates).
    smtp_fallback_enabled = models.BooleanField(
        default=False,
        help_text='If Graph is known-unavailable before sending, fall back to SMTP.',
    )

    # Defaults applied when creating a new ticket.
    default_queue = models.ForeignKey(Queue, on_delete=models.PROTECT,
                                      related_name='email_configs')
    default_priority = models.ForeignKey(TicketPriority, on_delete=models.PROTECT,
                                         related_name='email_configs')
    default_type = models.ForeignKey(TicketType, on_delete=models.PROTECT,
                                     related_name='email_configs')

    # Subject regex that captures a ticket number for reply-threading.
    # Default matches "PSA-YYYY-NNNNNN" anywhere in the subject.
    subject_ticket_pattern = models.CharField(
        max_length=200, default=r'PSA-\d{4}-\d{6}',
        help_text='Regex; first match in the subject is treated as a reply to that ticket',
    )

    is_active = models.BooleanField(default=True)
    poll_interval_minutes = models.PositiveIntegerField(default=5)
    last_poll_at = models.DateTimeField(null=True, blank=True)
    last_poll_status = models.CharField(max_length=50, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_email_ingestion_configs'
        ordering = ['name']

    def __str__(self):
        if self.source == self.SOURCE_GRAPH:
            return f'{self.name} (Graph: {self.graph_mailbox})'
        return f'{self.name} ({self.username}@{self.imap_host})'

    def set_password(self, password: str):
        from vault.encryption import encrypt_dict
        import json as _json
        if not password:
            self.encrypted_password = ''
            return
        self.encrypted_password = _json.dumps(encrypt_dict({'p': password}))

    def get_password(self) -> str:
        from vault.encryption import decrypt_dict
        import json as _json
        if not self.encrypted_password:
            return ''
        try:
            return decrypt_dict(_json.loads(self.encrypted_password)).get('p', '')
        except Exception:
            return ''


# ---------------------------------------------------------------------------
# Time-entry hook — increment Contract.hours_used_minutes on save
# ---------------------------------------------------------------------------

# This is attached as a Django signal in psa/apps.py to keep models.py
# free of side effects on import.


# ---------------------------------------------------------------------------
# Quotes / Estimates (Workstream 5 — sales pipeline)
# ---------------------------------------------------------------------------

class Quote(models.Model):
    """
    Sales quote / estimate. Goes through draft → sent → accepted/rejected,
    and on acceptance optionally converts into a Ticket. Line items are
    stored on QuoteLineItem.

    The `quote_number` is auto-assigned `Q-YYYY-NNNNN` per year.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]

    quote_number = models.CharField(max_length=32, unique=True, db_index=True, blank=True)
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_quotes',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_client_quotes',
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    valid_until = models.DateField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0,
        help_text='e.g. 0.0875 for 8.75%')
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    converted_ticket = models.ForeignKey(
        Ticket, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='source_quotes',
        help_text='Set when the quote was converted to a ticket on acceptance',
    )
    converted_project = models.ForeignKey(
        'Project', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='source_quotes',
    )

    customer_token = models.CharField(max_length=64, blank=True, db_index=True,
        help_text='Opaque token for the customer-facing sign-and-accept URL')

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_psa_quotes',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_quotes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-created_at']),
            models.Index(fields=['client_org', 'status']),
        ]

    def __str__(self):
        return f'{self.quote_number} — {self.title}'

    def save(self, *args, **kwargs):
        if not self.quote_number:
            self.quote_number = self._next_number()
        if not self.customer_token:
            import secrets as _secrets
            self.customer_token = _secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def _next_number(self) -> str:
        year = timezone.now().year
        prefix = f'Q-{year}-'
        last = Quote.objects.filter(quote_number__startswith=prefix).order_by('-quote_number').first()
        if last and last.quote_number:
            try:
                n = int(last.quote_number.rsplit('-', 1)[-1])
            except ValueError:
                n = 0
        else:
            n = 0
        return f'{prefix}{n + 1:05d}'

    def recompute_totals(self):
        from decimal import Decimal, InvalidOperation
        sub = sum((li.line_total for li in self.line_items.all()), Decimal('0'))
        self.subtotal = sub
        try:
            rate = Decimal(str(self.tax_rate or '0'))
        except (InvalidOperation, ValueError, TypeError):
            rate = Decimal('0')
        self.tax_amount = (sub * rate).quantize(Decimal('0.01'))
        self.total = sub + self.tax_amount
        self.save(update_fields=['subtotal', 'tax_amount', 'total'])

    def mark_accepted(self, *, user=None, create_ticket: bool = True,
                      queue=None, priority=None, ticket_type=None,
                      status=None, create_project: bool = False):
        # Phase 20 v7 (v3.17.275): refuse acceptance while any approval
        # chain stage is still pending or blocked. The view should call
        # `has_open_approvals` first and surface a friendly message;
        # this is the model-level safety net.
        if self.has_open_approvals:
            raise ValueError(
                f'Quote {self.quote_number} has open approvals — '
                f'resolve the chain first.'
            )
        self.status = 'accepted'
        self.accepted_at = timezone.now()
        if create_ticket and not self.converted_ticket and queue and priority and ticket_type and status:
            self.converted_ticket = Ticket.objects.create(
                organization=self.client_org,
                subject=f'Q {self.quote_number}: {self.title}',
                description=self.description or '',
                queue=queue, priority=priority,
                ticket_type=ticket_type, status=status,
                source='manual',
                created_by=user,
            )
        if create_project and not self.converted_project:
            self.convert_to_project(user=user, save=False)
        self.save()

    @property
    def has_open_approvals(self) -> bool:
        """Phase 20 v7 (v3.17.275): True when this quote has any
        PSAApproval row in a non-terminal state (pending or blocked).
        Used to gate `mark_accepted()` and other forward transitions
        until every chain stage is decided."""
        from .models import PSAApproval
        return PSAApproval.objects.filter(
            object_type='psa.Quote', object_id=self.pk,
            status__in=['pending', 'blocked'],
        ).exists()

    def send_for_approval(self, *, user=None, stages=None,
                           default_threshold_total=None):
        """Phase 20 v4 (v3.17.270): route this quote through a sequential
        PSAApproval chain. Returns the list of created approvals.

        ``stages`` is an optional list of dicts (forwarded to
        ``PSAApproval.create_chain``). When omitted, falls back to a
        single-stage approval keyed off ``default_threshold_total``:
        quotes at or above the threshold get a 2-stage chain
        (manager → director); below, just one stage. Both fallback
        defaults can be overridden by passing explicit ``stages``.

        Skips silently when an OPEN chain already exists (any stage
        not yet in {approved, denied, cancelled}) — re-sending while
        approval is still in flight would duplicate effort.
        """
        from .models import PSAApproval
        existing_open = PSAApproval.objects.filter(
            object_type='psa.Quote', object_id=self.pk,
        ).exclude(status__in=['approved', 'denied', 'cancelled'])
        if existing_open.exists():
            return list(existing_open.order_by('stage_index'))

        if stages is None:
            crosses = (default_threshold_total is not None
                       and self.total is not None
                       and float(self.total) >= float(default_threshold_total))
            stages = [{'request_comment': f'Manager approval for {self.quote_number}'}]
            if crosses:
                stages.append({
                    'request_comment': f'Director sign-off for {self.quote_number} '
                                       f'(total ${self.total} ≥ ${default_threshold_total})'
                })

        return PSAApproval.create_chain(
            organization=self.organization,
            kind='quote',
            object_type='psa.Quote',
            object_id=self.pk,
            object_repr=f'{self.quote_number} — {self.title}'[:300],
            requested_by=user,
            stages=stages,
        )

    def convert_to_project(self, *, user=None, save: bool = True):
        """
        Spin up a Project from this quote, with one ProjectTask per line
        item. Idempotent — if `converted_project` is already set, returns
        the existing project unchanged.

        The line-item description becomes the task title; quantity and
        unit price are folded into the task description so techs see what
        was sold without flipping back to the quote PDF.
        """
        if self.converted_project_id:
            return self.converted_project
        project = Project.objects.create(
            organization=self.organization,
            client_org=self.client_org,
            name=self.title[:200],
            description=self.description or '',
            status='planning',
            owner=user,
        )
        for li in self.line_items.all().order_by('sort_order', 'pk'):
            ProjectTask.objects.create(
                project=project,
                title=li.description[:300],
                description=f'From quote {self.quote_number}: {li.quantity} × {li.unit_price}',
                sort_order=li.sort_order,
                estimated_hours=li.quantity,
                created_by=user,
            )
        self.converted_project = project
        if save:
            self.save(update_fields=['converted_project'])
        return project


class QuoteLineItem(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='line_items')
    sort_order = models.PositiveIntegerField(default=0)

    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_taxable = models.BooleanField(default=True)

    class Meta:
        db_table = 'psa_quote_line_items'
        ordering = ['sort_order', 'pk']

    @property
    def line_total(self):
        from decimal import Decimal, InvalidOperation
        try:
            q = Decimal(str(self.quantity or '0'))
            p = Decimal(str(self.unit_price or '0'))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0.00')
        return (q * p).quantize(Decimal('0.01'))

    def __str__(self):
        return f'{self.description} ({self.quantity} × {self.unit_price})'


# ---------------------------------------------------------------------------
# Expenses (Workstream 2 expansion)
# ---------------------------------------------------------------------------
# Phase 12 v1 (v3.17.231) — CSAT survey
# ---------------------------------------------------------------------------

class TicketVote(models.Model):
    """
    Phase 12 (v3.17.235): "I care about this too" up-vote from a portal
    user. Aggregate count surfaces to staff on the ticket detail so high-
    impact issues bubble up. Re-firing the endpoint toggles the vote off.
    """
    ticket = models.ForeignKey(
        'psa.Ticket', on_delete=models.CASCADE, related_name='votes',
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='psa_ticket_votes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_votes'
        unique_together = [['ticket', 'user']]
        indexes = [
            models.Index(fields=['ticket']),
        ]

    def __str__(self):
        return f'{self.user.username} voted on {self.ticket.ticket_number}'


class TimesheetSubmission(models.Model):
    """
    Phase 25 (v3.17.242): a tech's batch of time entries for a pay
    period (typically weekly), gated through manager approval before
    rolling into invoicing.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='psa_timesheet_submissions',
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_timesheet_decisions',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True)
    submitter_notes = models.TextField(
        blank=True,
        help_text='Optional comment from the tech when submitting.',
    )

    class Meta:
        db_table = 'psa_timesheet_submissions'
        ordering = ['-period_start', '-submitted_at']
        unique_together = [['user', 'period_start', 'period_end']]
        indexes = [
            models.Index(fields=['user', '-period_start']),
            models.Index(fields=['status', '-submitted_at']),
        ]

    def __str__(self):
        return f'{self.user.username} {self.period_start}–{self.period_end} [{self.status}]'

    @property
    def total_minutes(self):
        return sum((e.duration_minutes or 0) for e in self.entries.all())

    @property
    def total_billable_minutes(self):
        return sum((e.duration_minutes or 0)
                   for e in self.entries.all() if e.is_billable)

    def approve(self, *, user, notes=''):
        self.status = 'approved'
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_notes = (notes or '')[:5000]
        self.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_notes'])

    def reject(self, *, user, notes=''):
        self.status = 'rejected'
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_notes = (notes or '')[:5000]
        self.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_notes'])
        # Detach entries so the tech can re-submit after fixes.
        self.entries.update(submission=None)


class TicketCSATSurvey(models.Model):
    """
    Customer-satisfaction survey emailed to the ticket requester after a
    ticket transitions to a terminal status. One survey per ticket
    (OneToOne). Token-based public URL — recipient doesn't need an
    account to respond.
    """
    ticket = models.OneToOneField(
        'psa.Ticket', on_delete=models.CASCADE, related_name='csat_survey',
    )
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_csat_surveys',
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    recipient_email = models.EmailField()
    sent_at = models.DateTimeField(auto_now_add=True)
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='1 = very dissatisfied, 5 = very satisfied. Null until response.',
    )
    comment = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'psa_ticket_csat_surveys'
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['organization', '-sent_at']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return (f'CSAT for {self.ticket.ticket_number}: '
                f'{self.rating or "pending"}')

    def save(self, *args, **kwargs):
        if not self.token:
            import secrets as _secrets
            self.token = _secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_responded(self) -> bool:
        return self.responded_at is not None


def expense_receipt_upload_to(instance, filename):
    return f'psa/expenses/{instance.ticket.organization_id}/{instance.ticket_id}/{filename}'


class TicketExpense(models.Model):
    """
    Reimbursable / billable expenses tracked against a ticket. Optional
    receipt file upload. Approvals integrate with PSAApproval.
    """
    CATEGORY_CHOICES = [
        ('mileage', 'Mileage / Travel'),
        ('parts', 'Parts'),
        ('software', 'Software / License'),
        ('subcontractor', 'Subcontractor'),
        ('shipping', 'Shipping'),
        ('other', 'Other'),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='expenses')
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_expenses',
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    description = models.CharField(max_length=300)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    incurred_on = models.DateField()
    is_billable = models.BooleanField(default=True)
    is_reimbursable = models.BooleanField(default=True)
    receipt_file = models.FileField(upload_to=expense_receipt_upload_to, blank=True, null=True)

    approval = models.ForeignKey(
        'PSAApproval', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='expenses',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ticket_expenses'
        ordering = ['-incurred_on', '-created_at']
        indexes = [
            models.Index(fields=['ticket', '-incurred_on']),
            models.Index(fields=['user', '-incurred_on']),
        ]

    def __str__(self):
        return f'{self.description} — {self.amount} {self.currency}'


# ---------------------------------------------------------------------------
# Project tasks (Workstream 3 expansion)
# ---------------------------------------------------------------------------

class ProjectTask(models.Model):
    """
    A discrete task or milestone under a Project. Distinct from Ticket
    (which is for client-facing service desk work) — ProjectTask is for
    internal delivery breakdown. Tasks can optionally link to a Ticket
    when concrete client work is needed.
    """
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('blocked', 'Blocked'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True, related_name='subtasks',
        help_text='Optional — for milestone → child task hierarchy',
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    is_milestone = models.BooleanField(default=False,
        help_text='Major delivery checkpoint (rendered prominently)')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')

    assigned_to = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_project_tasks',
    )
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    estimated_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    sort_order = models.PositiveIntegerField(default=0)
    related_ticket = models.ForeignKey(
        Ticket, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='project_tasks',
    )

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_psa_project_tasks',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_project_tasks'
        ordering = ['sort_order', 'created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status in ('done', 'cancelled') and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status not in ('done', 'cancelled') and self.completed_at:
            self.completed_at = None
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Workflow Rules (Workstream 9 — PSA-specific automations)
# ---------------------------------------------------------------------------
#
# Distinct from `processes/` (which orchestrates multi-step procedures).
# A WorkflowRule is a simple "when X event happens AND conditions match,
# run these actions" trigger fired from PSA signal handlers.

class WorkflowRule(models.Model):
    """
    A simple rule engine: trigger + condition expression + actions JSON.

    Trigger events fire in psa/signals.py:
      * ticket_created    — Ticket post_save with created=True
      * ticket_updated    — Ticket post_save with created=False
      * status_changed    — Ticket.status changed
      * comment_added     — TicketComment post_save

    Condition is a small JSON DSL evaluated against the ticket:
      {"priority": "P1"}                 → priority.code == "P1"
      {"priority__in": ["P1","P2"]}      → priority.code in [...]
      {"queue": "Helpdesk"}              → queue.name == "Helpdesk"
      {"subject_contains": "outage"}     → "outage" in subject (case-insensitive)
      {"is_unassigned": true}            → assigned_to is None
      {"any": [{...}, {...}]}            → OR
      {"all": [{...}, {...}]}            → AND
    Empty / missing condition = always true.

    Actions (list of dicts, executed in order):
      {"type": "set_priority", "code": "P1"}
      {"type": "assign_to", "username": "tech1"}
      {"type": "add_watcher", "username": "manager"}
      {"type": "add_internal_note", "body": "auto-flagged"}
      {"type": "set_queue", "name": "Escalations"}
      {"type": "add_tag", "tag": "vip"}
    """
    TRIGGER_CHOICES = [
        ('ticket_created', 'Ticket created'),
        ('ticket_updated', 'Ticket updated'),
        ('status_changed', 'Status changed'),
        ('comment_added', 'Comment added'),
        # Phase 14 v3 (v3.17.286): SLA-driven automation. Fired by the
        # `psa_sla_workflow_tick` cron when the ticket's elapsed-vs-due
        # SLA percentage crosses a threshold. Use with the
        # `sla_pct_at_least` condition.
        ('sla_threshold_crossed', 'SLA threshold crossed'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='psa_workflow_rules',
        help_text='Leave blank to apply this rule to tickets from EVERY client. '
                  'Set to a specific client organization to scope it to that client only.',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    trigger = models.CharField(max_length=30, choices=TRIGGER_CHOICES)
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list, blank=True)
    # Phase 14 v2 (v3.17.285): conditional routing — if `conditions`
    # evaluate FALSE, run `else_actions` instead of `actions`. Empty
    # else_actions = no-op when condition fails (legacy behavior).
    else_actions = models.JSONField(default=list, blank=True,
        help_text='Actions to run when conditions evaluate false. '
                  'Empty = no-op when conditions fail.')

    # Phase 14 v3 (v3.17.286): once-per-ticket fire guard. When True,
    # the engine consults `WorkflowRuleFiring(rule, ticket)` and skips
    # if the pair already fired. Designed for SLA tick rules that
    # otherwise fire every cron tick.
    fire_once_per_ticket = models.BooleanField(
        default=False,
        help_text='Fire at most once per (rule, ticket). Use for '
                  'SLA-driven rules so the cron doesn\'t spam.',
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0,
        help_text='Lower runs first when multiple rules match')

    last_fired_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    fire_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_psa_workflow_rules',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_workflow_rules'
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['organization', 'trigger', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_trigger_display()})'


class WorkflowRuleTemplate(models.Model):
    """Phase 14 v9 (v3.17.288): saved-and-reusable workflow rule
    template. An MSP admin can store a common rule (e.g. "P1 alert →
    page on-call") once and instantiate it onto any client org with
    one click — no need to copy-paste JSON conditions/actions.
    """
    CATEGORY_CHOICES = [
        ('routing', 'Routing'),
        ('sla', 'SLA / escalation'),
        ('notification', 'Notification'),
        ('cleanup', 'Cleanup / housekeeping'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES,
                                default='other')
    trigger = models.CharField(max_length=30,
                                choices=WorkflowRule.TRIGGER_CHOICES)
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list, blank=True)
    else_actions = models.JSONField(default=list, blank=True)
    fire_once_per_ticket = models.BooleanField(default=False)
    is_built_in = models.BooleanField(
        default=False,
        help_text='Built-in templates ship with the project; user-created '
                  'ones are False. Built-ins can\'t be deleted via the UI.',
    )
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_workflow_rule_templates'
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_category_display()})'

    def instantiate(self, *, organization=None, name_override=None,
                     created_by=None):
        """Create a `WorkflowRule` from this template, optionally
        scoped to an organization. Returns the new rule. The new
        rule's name defaults to the template name; passing
        `name_override` lets you rename for the target org."""
        return WorkflowRule.objects.create(
            organization=organization,
            name=(name_override or self.name)[:200],
            description=self.description,
            trigger=self.trigger,
            conditions=self.conditions or {},
            actions=self.actions or [],
            else_actions=self.else_actions or [],
            fire_once_per_ticket=self.fire_once_per_ticket,
            is_active=True,
            created_by=created_by,
        )


class WorkflowSuggestion(models.Model):
    """Phase 14 v13 (v3.17.290) — **OPTIONAL AI** workflow rule suggestion.

    Generated by `psa_generate_workflow_suggestions` (a heuristic engine
    today; pluggable for real LLM-driven suggestions later) when ticket
    patterns indicate a missing automation. Admins review at
    `/psa/rules/suggestions/`, then accept (creates a `WorkflowRule`)
    or dismiss.

    Gated by `SystemSetting.psa_ai_enabled` — generation, surfacing,
    and acceptance all no-op when the flag is off so installs that
    don't want AI features see nothing.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('accepted', 'Accepted'),
        ('dismissed', 'Dismissed'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='psa_workflow_suggestions',
        help_text='Optional client scope. None = MSP-wide suggestion.',
    )
    summary = models.CharField(
        max_length=400,
        help_text='Plain-text reason — "12 P1 tickets in 30d auto-routed '
                  'to Bob → consider a skill-match rule"',
    )
    rationale = models.TextField(
        blank=True,
        help_text='Optional longer explanation; future LLM suggesters '
                  'can put their reasoning here.',
    )
    suggested_payload = models.JSONField(
        default=dict, blank=True,
        help_text='Draft WorkflowRule payload — name, trigger, '
                  'conditions, actions, etc. Used by accept().',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                default='pending')
    generated_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    accepted_rule = models.ForeignKey(
        'WorkflowRule', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        help_text='Set on accept() to point at the materialized rule.',
    )

    class Meta:
        db_table = 'psa_workflow_suggestions'
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['status', '-generated_at']),
        ]

    def __str__(self):
        return f'[{self.get_status_display()}] {self.summary[:80]}'

    def accept(self, *, user=None):
        """Materialize the suggestion into a real WorkflowRule. Idempotent
        — already-accepted suggestions return the existing rule."""
        if self.accepted_rule_id:
            return self.accepted_rule
        payload = self.suggested_payload or {}
        rule = WorkflowRule.objects.create(
            organization=self.organization,
            name=payload.get('name') or self.summary[:200],
            description=payload.get('description', ''),
            trigger=payload.get('trigger', 'ticket_created'),
            conditions=payload.get('conditions', {}),
            actions=payload.get('actions', []),
            else_actions=payload.get('else_actions', []),
            fire_once_per_ticket=bool(payload.get('fire_once_per_ticket')),
            is_active=True,
            created_by=user,
        )
        self.accepted_rule = rule
        self.status = 'accepted'
        self.decided_at = timezone.now()
        self.decided_by = user
        self.save(update_fields=['accepted_rule', 'status',
                                  'decided_at', 'decided_by'])
        return rule

    def dismiss(self, *, user=None):
        if self.status != 'pending':
            return
        self.status = 'dismissed'
        self.decided_at = timezone.now()
        self.decided_by = user
        self.save(update_fields=['status', 'decided_at', 'decided_by'])


class WorkflowRuleFiring(models.Model):
    """Phase 14 v3 (v3.17.286): one row per (rule, ticket) to support
    `WorkflowRule.fire_once_per_ticket=True`. Used by SLA tick rules so
    the cron doesn't re-fire the same alert every minute.
    """
    rule = models.ForeignKey(
        'WorkflowRule', on_delete=models.CASCADE,
        related_name='firings',
    )
    ticket = models.ForeignKey(
        'Ticket', on_delete=models.CASCADE,
        related_name='workflow_firings',
    )
    fired_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_workflow_rule_firings'
        unique_together = [['rule', 'ticket']]
        indexes = [
            models.Index(fields=['ticket', '-fired_at']),
        ]

    def __str__(self):
        return f'{self.rule.name} → {self.ticket.ticket_number} @ {self.fired_at:%Y-%m-%d %H:%M}'


# ---------------------------------------------------------------------------
# Billing — invoices + payments (Workstream 5 expansion)
# ---------------------------------------------------------------------------

class Invoice(models.Model):
    """
    Customer invoice. Generated from a quote, a ticket's billable time +
    expenses, or a contract's reporting period. Pushed to an accounting
    system (QuickBooks Online / Xero) via integrations.AccountingConnection.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('void', 'Void'),
    ]

    invoice_number = models.CharField(max_length=32, unique=True, db_index=True, blank=True)
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_invoices',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_client_invoices',
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    invoice_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Money
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default='USD')

    # Sources
    source_quote = models.ForeignKey('Quote', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='invoices')
    source_ticket = models.ForeignKey(Ticket, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='invoices')
    source_contract = models.ForeignKey('Contract', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='invoices')

    # Accounting integration handoff
    accounting_provider = models.CharField(max_length=50, blank=True,
        help_text='quickbooks_online | xero | etc.')
    accounting_external_id = models.CharField(max_length=120, blank=True,
        help_text='Invoice ID in the external accounting system')
    pushed_to_accounting_at = models.DateTimeField(null=True, blank=True)
    last_push_error = models.TextField(blank=True)

    # Phase 27 v4 (v3.17.267): tax reconciliation — capture the
    # provider-side tax amount returned at push time so we can flag
    # discrepancies (rounding, jurisdiction differences, missing tax
    # codes) without re-fetching the invoice from QBO/Xero.
    provider_tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text='Tax amount reported by the accounting provider on '
                  'the most recent push. Compare to `tax_amount` (our '
                  'local calculation) to detect drift.',
    )

    # Phase 44.2 (v3.17.531): what the provider currently says this invoice is,
    # read back by the sync rather than captured at push time.
    #
    # The total is recorded, not applied. Our `total` is derived from line items,
    # so overwriting it would desync the invoice from the lines that justify it —
    # and an invoice whose total disagrees with its own lines is worse than one
    # that disagrees with QuickBooks. Recording the provider figure lets the
    # reconciliation report show the difference and a human decide which is right.
    provider_total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Invoice total as the accounting provider currently reports '
                  'it. Differs from `total` when the invoice was edited '
                  'provider-side.')
    provider_synced_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the provider copy of this invoice was last read back.')

    @property
    def provider_total_drift(self):
        """Signed difference between the provider's total and ours, or None.

        Non-zero means the invoice was edited on one side after the push.
        """
        if self.provider_total_amount is None:
            return None
        return self.provider_total_amount - (self.total or 0)

    # Phase 27 v7 (v3.17.279): multi-entity / multi-book routing. When
    # set, the invoice push targets this specific AccountingConnection.
    # When None, push falls back to the first sync-enabled connection
    # on the organization (legacy behavior).
    target_connection = models.ForeignKey(
        'integrations.AccountingConnection',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='routed_invoices',
        help_text='Pin the invoice to a specific accounting connection '
                  '— required for orgs with multiple QBO/Xero books.',
    )

    notes = models.TextField(blank=True)
    # Phase 36 v2 (v3.17.228): pre-invoice approval gate. When the invoice
    # exceeds a configured total threshold OR the source contract is over
    # an overage % threshold, the invoice is flagged for human review
    # before it can be marked sent or pushed to accounting.
    requires_approval = models.BooleanField(
        default=False,
        help_text='Set when the invoice exceeds a pre-billing approval '
                  'threshold (total or contract overage %). Must be approved '
                  'before status can move from draft → sent.',
    )
    approval_reason = models.CharField(
        max_length=200, blank=True,
        help_text='Why the invoice was flagged — surfaced to the approver.',
    )
    approved_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_psa_invoices',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Phase 27 v3 (v3.17.264) — first-class credit memos. A credit memo
    # is an invoice with negative line totals; the FK below points back
    # at the invoice it credits (when issued against an existing one).
    is_credit_memo = models.BooleanField(default=False,
        help_text='True for credit memos (negative-amount invoices).')
    credits_invoice = models.ForeignKey('self',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='credit_memos',
        help_text='When set, this credit memo was issued against the named source invoice.')

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_psa_invoices',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_invoices'
        ordering = ['-invoice_date', '-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-invoice_date']),
            models.Index(fields=['client_org', 'status']),
            models.Index(fields=['requires_approval', 'approved_at']),
        ]

    def __str__(self):
        return f'{self.invoice_number} — {self.title}'

    @property
    def balance(self):
        from decimal import Decimal
        return (Decimal(self.total) - Decimal(self.amount_paid)).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._next_number()
        super().save(*args, **kwargs)

    def flag_for_approval(self, *, total_threshold=None, overage_pct_threshold=None):
        """
        v3.17.228: evaluate this invoice against pre-billing thresholds and
        set `requires_approval` + `approval_reason` if any threshold is
        exceeded. Idempotent — safe to call repeatedly.

        Returns True when flagged, False otherwise. Doesn't save the row;
        the caller decides whether to persist (typically right after
        recompute_totals()).
        """
        from decimal import Decimal as _D
        reasons = []
        if total_threshold is not None and self.total and _D(self.total) >= _D(total_threshold):
            reasons.append(f'total ${self.total} ≥ ${total_threshold} threshold')
        if (overage_pct_threshold is not None
                and self.source_contract_id
                and self.source_contract.total_hours):
            consumed_min = self.source_contract.hours_used_minutes or 0
            allowance_min = float(self.source_contract.total_hours) * 60
            if allowance_min > 0:
                pct = 100 * consumed_min / allowance_min
                if pct >= float(overage_pct_threshold):
                    reasons.append(
                        f'contract {self.source_contract.name} at {pct:.0f}% '
                        f'(≥ {overage_pct_threshold}% threshold)'
                    )
        if reasons:
            self.requires_approval = True
            self.approval_reason = '; '.join(reasons)[:200]
            return True
        return False

    def approve(self, *, user):
        """v3.17.228: clear the approval gate. Sets approved_by + approved_at."""
        self.requires_approval = False
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['requires_approval', 'approved_by', 'approved_at', 'updated_at'])

    def _next_number(self) -> str:
        year = timezone.now().year
        prefix = f'INV-{year}-'
        last = Invoice.objects.filter(invoice_number__startswith=prefix).order_by('-invoice_number').first()
        if last and last.invoice_number:
            try:
                n = int(last.invoice_number.rsplit('-', 1)[-1])
            except ValueError:
                n = 0
        else:
            n = 0
        return f'{prefix}{n + 1:05d}'

    def recompute_totals(self):
        from decimal import Decimal, InvalidOperation
        sub = sum((li.line_total for li in self.line_items.all()), Decimal('0'))
        self.subtotal = sub
        try:
            rate = Decimal(str(self.tax_rate or '0'))
        except (InvalidOperation, ValueError, TypeError):
            rate = Decimal('0')
        self.tax_amount = (sub * rate).quantize(Decimal('0.01'))
        self.total = sub + self.tax_amount
        # Recompute amount_paid from related Payment rows
        paid = sum((Decimal(str(p.amount or '0')) for p in self.payments.all()), Decimal('0'))
        self.amount_paid = paid
        # Auto status update. Deliberately one-way: this method cannot tell a
        # voided payment from an invoice somebody marked paid by hand with no
        # Payment rows behind it — cash, a cheque, or settled straight in the
        # accounting system. Reopening those would restart late fees on invoices
        # that are genuinely settled. `reopen_if_unpaid()` below does the
        # reverse transition, called only where a payment is known to have been
        # removed.
        if self.status not in ('void', 'draft'):
            if paid >= self.total > 0:
                self.status = 'paid'
            elif paid > 0:
                self.status = 'partial'
        self.save(update_fields=['subtotal', 'tax_amount', 'total',
                                 'amount_paid', 'status', 'updated_at'])

    def reopen_if_unpaid(self):
        """Move a Paid/Partial invoice back to open after its payments go away.

        Separate from `recompute_totals()` on purpose. That method runs from
        everywhere and has no idea *why* the total is zero; an invoice marked
        paid by hand never had Payment rows in the first place, and reopening it
        would restart late fees on something genuinely settled. Only a caller
        that just removed a payment knows the difference, so only that caller
        performs this transition.

        Added v3.17.533 after the two-way version of recompute_totals reopened
        hand-marked invoices and tripped the late-fee tests.
        """
        from decimal import Decimal
        from django.utils import timezone as _tz

        if self.status not in ('paid', 'partial'):
            return
        if Decimal(str(self.amount_paid or '0')) > 0:
            return
        self.status = ('overdue'
                       if self.due_date and self.due_date < _tz.now().date()
                       else 'sent')
        self.save(update_fields=['status', 'updated_at'])

    def create_credit_memo(self, *, user=None, reason='', amount=None):
        """Phase 27 v3 (v3.17.264): issue a credit memo against this
        invoice. Returns the new credit-memo Invoice.

        Behavior:
          - The new invoice is `is_credit_memo=True`, `credits_invoice=self`,
            client_org / organization / currency / tax_rate copied from self.
          - If ``amount`` is None: copies all non-credit lines, negating
            unit_price so the totals come out negative.
          - If ``amount`` is set: creates a single InvoiceLineItem with
            unit_price = -amount (used for partial credits / lump-sum
            adjustments).
          - The new memo's invoice_number uses a `CN-YYYY-NNNNN` prefix
            so credit memos sort separately from regular invoices.
        """
        from decimal import Decimal as _D
        if self.is_credit_memo:
            raise ValueError('Cannot issue a credit memo against another credit memo.')

        memo = Invoice(
            organization=self.organization,
            client_org=self.client_org,
            title=f'Credit Memo for {self.invoice_number}',
            description=(reason or '')[:500],
            status='draft',
            invoice_date=timezone.now().date(),
            currency=self.currency,
            tax_rate=self.tax_rate,
            is_credit_memo=True,
            credits_invoice=self,
            created_by=user,
        )
        # Override _next_number prefix via direct assign before save
        memo.invoice_number = self._next_credit_memo_number()
        memo.save()

        if amount is not None:
            InvoiceLineItem.objects.create(
                invoice=memo,
                description=(reason or f'Credit memo against {self.invoice_number}')[:300],
                quantity=1,
                unit_price=-_D(str(amount)),
                is_taxable=False,
                source='manual',
            )
        else:
            for li in self.line_items.all():
                InvoiceLineItem.objects.create(
                    invoice=memo,
                    description=f'Credit: {li.description}'[:300],
                    quantity=li.quantity,
                    unit_price=-li.unit_price,
                    is_taxable=li.is_taxable,
                    source='manual',
                )
        memo.recompute_totals()
        return memo

    @classmethod
    def _next_credit_memo_number(cls):
        year = timezone.now().year
        prefix = f'CN-{year}-'
        last = cls.objects.filter(invoice_number__startswith=prefix).order_by('-invoice_number').first()
        if last and last.invoice_number:
            try:
                n = int(last.invoice_number.rsplit('-', 1)[-1])
            except ValueError:
                n = 0
        else:
            n = 0
        return f'{prefix}{n + 1:05d}'


class InvoiceLineItem(models.Model):
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('time', 'Time Entry'),
        ('expense', 'Expense'),
        ('quote_line', 'Quote Line'),
        ('contract', 'Contract Period'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    sort_order = models.PositiveIntegerField(default=0)

    description = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_taxable = models.BooleanField(default=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    source_id = models.CharField(max_length=80, blank=True,
        help_text='Loose pointer to the source row id (e.g. time_entry pk)')

    # Phase 27 v6 (v3.17.278): per-line GL account mapping. When set,
    # propagated to the accounting provider (QBO `AccountRef` / Xero
    # `AccountCode`) on push so revenue lands in the right ledger.
    gl_account_code = models.CharField(
        max_length=40, blank=True,
        help_text='Provider-side GL account code (QBO Item ref or '
                  'Xero AccountCode). Blank uses the connection default.',
    )

    class Meta:
        db_table = 'psa_invoice_line_items'
        ordering = ['sort_order', 'pk']

    @property
    def line_total(self):
        from decimal import Decimal, InvalidOperation
        try:
            q = Decimal(str(self.quantity or '0'))
            p = Decimal(str(self.unit_price or '0'))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0.00')
        return (q * p).quantize(Decimal('0.01'))

    def __str__(self):
        return f'{self.description} ({self.quantity} × {self.unit_price})'


class Payment(models.Model):
    """A payment received against an Invoice."""
    METHOD_CHOICES = [
        ('check', 'Check'),
        ('ach', 'ACH'),
        ('credit_card', 'Credit Card'),
        ('wire', 'Wire'),
        ('cash', 'Cash'),
        ('other', 'Other'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='ach')
    reference = models.CharField(max_length=120, blank=True,
        help_text='Check number, wire confirmation, etc.')
    notes = models.TextField(blank=True)

    # Phase 27 v9 (v3.17.281): bank-account reconciliation hooks.
    # `bank_deposit_batch` — opaque tag a buyer sets to group every
    # payment that landed in a single bank deposit (e.g. "DEP-2026-04-30").
    # `bank_reconciled_at` — stamped when an MSP confirms the deposit
    # appeared in the bank statement; nulls out if the batch is reopened.
    bank_deposit_batch = models.CharField(
        max_length=80, blank=True, db_index=True,
        help_text='Opaque tag grouping payments that share a single '
                  'bank deposit. Used by the bank-reconciliation report.',
    )
    bank_reconciled_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the deposit batch was confirmed against the '
                  'bank statement.',
    )

    # Phase 44.2 (v3.17.531): which provider payment this row came from.
    # Before this, inbound payments were *inferred* from an invoice balance of
    # zero and written with today's date and method 'other', with nothing tying
    # the row to the real payment. Storing the id makes the sync idempotent and
    # lets a voided provider payment find and remove its local counterpart.
    accounting_provider = models.CharField(
        max_length=50, blank=True,
        help_text='quickbooks_online | xero | etc. Blank for manual entries.')
    accounting_external_id = models.CharField(
        max_length=120, blank=True, db_index=True,
        help_text='Payment ID in the external accounting system.')

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_payments_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_payments'
        ordering = ['-paid_on', '-created_at']
        constraints = [
            # One local row per provider payment. Without this, re-running the
            # sync would double-count every payment it had already imported.
            models.UniqueConstraint(
                fields=['accounting_provider', 'accounting_external_id'],
                condition=models.Q(accounting_external_id__gt=''),
                name='uniq_payment_per_provider_txn'),
        ]

    def __str__(self):
        return f'{self.amount} on {self.paid_on} ({self.get_method_display()})'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Refresh the parent invoice's amount_paid + status
        try:
            self.invoice.recompute_totals()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Quote e-signature (Workstream 5)
# ---------------------------------------------------------------------------

class QuoteSignature(models.Model):
    """Customer signature record for a Quote. Signature drawn on the
    portal sign page is captured as a base64-encoded PNG.
    """
    quote = models.OneToOneField('Quote', on_delete=models.CASCADE,
                                 related_name='signature')
    signed_by_name = models.CharField(max_length=200)
    signed_by_email = models.EmailField()
    signed_by_title = models.CharField(max_length=200, blank=True,
        help_text='Optional — signer\'s job title')
    signature_data = models.TextField(
        help_text='Base64 data URI of the drawn signature (image/png)')
    signed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)

    class Meta:
        db_table = 'psa_quote_signatures'

    def __str__(self):
        return f'Signed by {self.signed_by_name} at {self.signed_at:%Y-%m-%d %H:%M}'


# ---------------------------------------------------------------------------
# Charges — direct line entries against a client account, independent of
# invoices. Can be one-off (late fee, credit) or recurring (monthly retainer).
# Charges marked `is_credit=True` reduce the client's outstanding balance.
# A Charge can later be rolled into an invoice; once it is, `invoiced=True`
# and `invoice` points at the invoice that consumed it.
# ---------------------------------------------------------------------------

class Charge(models.Model):
    RECURRENCE_CHOICES = [
        ('once', 'One-time'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_charges',
        help_text='MSP tenant',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_client_charges',
    )
    description = models.CharField(max_length=300)
    amount = models.DecimalField(max_digits=12, decimal_places=2,
        help_text='Positive value. Use is_credit to subtract from balance.')
    currency = models.CharField(max_length=8, default='USD')
    charge_date = models.DateField()

    is_credit = models.BooleanField(default=False,
        help_text='Credit/refund — subtracts from the client\'s outstanding balance')
    is_recurring = models.BooleanField(default=False)
    recurrence = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default='once')
    next_run_at = models.DateField(null=True, blank=True,
        help_text='When the next recurring instance should be created (for is_recurring=True)')

    invoiced = models.BooleanField(default=False)
    invoice = models.ForeignKey('Invoice', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='charges_consumed')

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_psa_charges',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_charges'
        ordering = ['-charge_date', '-created_at']
        indexes = [
            models.Index(fields=['organization', 'client_org', '-charge_date']),
            models.Index(fields=['client_org', 'invoiced']),
            models.Index(fields=['is_recurring', 'next_run_at']),
        ]

    def __str__(self):
        sign = '-' if self.is_credit else '+'
        return f'{sign}{self.amount} {self.currency} — {self.description}'

    @property
    def signed_amount(self):
        from decimal import Decimal
        a = Decimal(str(self.amount or '0'))
        return -a if self.is_credit else a


def get_psa_balance(client_org, *, msp_org=None):
    """Compute the per-client account balance.

    Returns a dict:
      outstanding       — sum of unpaid invoice balances
      credit_total      — sum of unbilled credits
      uninvoiced_charges — sum of unbilled non-credit charges
      net_balance       — outstanding + uninvoiced_charges - credit_total
      aging             — {0_30: x, 31_60: x, 61_90: x, 90_plus: x}
                           computed from invoice.due_date (or invoice_date when due null)

    The MSP filter is optional — when provided, scopes to that MSP's
    invoices/charges only (matters for multi-tenant SaaS hosting).
    """
    from datetime import date
    from decimal import Decimal

    inv_qs = Invoice.objects.filter(client_org=client_org).exclude(status='void')
    chg_qs = Charge.objects.filter(client_org=client_org)
    if msp_org is not None:
        inv_qs = inv_qs.filter(organization=msp_org)
        chg_qs = chg_qs.filter(organization=msp_org)

    outstanding = Decimal('0')
    aging = {'0_30': Decimal('0'), '31_60': Decimal('0'),
             '61_90': Decimal('0'), '90_plus': Decimal('0')}
    today = date.today()
    for inv in inv_qs:
        bal = Decimal(str(inv.balance or '0'))
        if bal <= 0:
            continue
        outstanding += bal
        anchor = inv.due_date or inv.invoice_date
        if anchor is None:
            aging['0_30'] += bal
            continue
        days = (today - anchor).days
        if days <= 30:
            aging['0_30'] += bal
        elif days <= 60:
            aging['31_60'] += bal
        elif days <= 90:
            aging['61_90'] += bal
        else:
            aging['90_plus'] += bal

    credit_total = sum(
        (Decimal(str(c.amount or '0')) for c in chg_qs.filter(is_credit=True, invoiced=False)),
        Decimal('0'),
    )
    uninvoiced_charges = sum(
        (Decimal(str(c.amount or '0')) for c in chg_qs.filter(is_credit=False, invoiced=False)),
        Decimal('0'),
    )
    net = outstanding + uninvoiced_charges - credit_total
    return {
        'outstanding': outstanding,
        'credit_total': credit_total,
        'uninvoiced_charges': uninvoiced_charges,
        'net_balance': net,
        'aging': aging,
    }


# ---------------------------------------------------------------------------
# Procurement — Phase 4.1
# ---------------------------------------------------------------------------

class PurchaseRequisition(models.Model):
    """
    Internal request a tech files to buy something. Goes through an
    approval gate before becoming a PurchaseOrder. Lives next to
    Quote/Invoice in feature texture: auto-numbered, line items,
    optional client_org link.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted for approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('converted', 'Converted to PO'),
        ('cancelled', 'Cancelled'),
    ]
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_pr_msp',
        help_text='MSP tenant that owns the requisition.',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='psa_pr_client', null=True, blank=True,
        help_text='Optional - bill to / drop-ship to this client.',
    )
    pr_number = models.CharField(max_length=30, unique=True)  # PR-YYYY-NNNNN
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    requested_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    # Approval trail
    approver = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    # Optional ticket / project link (provenance)
    source_ticket = models.ForeignKey(
        'psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requisitions',
    )
    source_project = models.ForeignKey(
        'psa.Project', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requisitions',
    )

    # Money totals (computed from line items)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default='USD')

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_purchase_requisitions'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-requested_at']),
            models.Index(fields=['client_org']),
        ]

    def __str__(self):
        return f'{self.pr_number} - {self.title}'

    def save(self, *args, **kwargs):
        if not self.pr_number:
            self.pr_number = self.next_number()
        super().save(*args, **kwargs)

    @classmethod
    def next_number(cls):
        """PR-YYYY-NNNNN, monotonic per year."""
        from django.utils import timezone
        from django.db.models import Max
        year = timezone.now().year
        prefix = f'PR-{year}-'
        last = cls.objects.filter(pr_number__startswith=prefix).aggregate(Max('pr_number'))['pr_number__max']
        if not last:
            return f'{prefix}00001'
        try:
            n = int(last.split('-')[-1])
        except (ValueError, IndexError):
            n = 0
        return f'{prefix}{n + 1:05d}'

    def recompute_totals(self):
        from decimal import Decimal
        subtotal = Decimal('0')
        for li in self.line_items.all():
            subtotal += (li.quantity or Decimal('0')) * (li.unit_price or Decimal('0'))
        self.subtotal = subtotal
        self.tax_amount = (subtotal * (self.tax_rate or Decimal('0'))) / Decimal('100')
        self.total = self.subtotal + self.tax_amount
        return self.total


class PurchaseRequisitionLineItem(models.Model):
    requisition = models.ForeignKey(PurchaseRequisition, on_delete=models.CASCADE,
                                     related_name='line_items')
    description = models.CharField(max_length=300)
    sku = models.CharField(max_length=80, blank=True,
        help_text='Vendor SKU or part number - pre-fills from distributor catalog.')
    distributor_provider = models.CharField(max_length=40, blank=True,
        help_text='Hint: which distributor (ingram/pax8/synnex) carries this SKU.')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'psa_purchase_requisition_lines'
        ordering = ['sort_order', 'pk']

    @property
    def line_total(self):
        from decimal import Decimal
        return (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))


class PurchaseOrder(models.Model):
    """
    Approved PR converts to a PurchaseOrder issued to a vendor.
    Auto-numbered. Branded PDF + email-to-vendor (mirrors Invoice pattern).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent to vendor'),
        ('acknowledged', 'Vendor acknowledged'),
        ('partial', 'Partially received'),
        ('received', 'Fully received'),
        ('cancelled', 'Cancelled'),
        ('void', 'Void'),
    ]
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_po_msp',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='psa_po_client', null=True, blank=True,
    )
    requisition = models.ForeignKey(
        PurchaseRequisition, on_delete=models.SET_NULL,
        related_name='purchase_orders', null=True, blank=True,
    )
    source_quote = models.ForeignKey(
        'psa.Quote', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders',
        help_text='Phase 4.4: set when this PO was auto-created from an accepted quote.',
    )
    po_number = models.CharField(max_length=30, unique=True)  # PO-YYYY-NNNNN
    # Phase 4.3 — link to assets.Vendor for procurement metadata.
    # vendor_name / email / phone / address remain as snapshot fields so
    # historic POs render correctly even if the vendor row is later edited.
    vendor = models.ForeignKey(
        'assets.Vendor',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders',
        help_text='Link to assets.Vendor for procurement metadata; '
                  'snapshot fields below are auto-filled at save time.',
    )
    vendor_name = models.CharField(max_length=200)
    vendor_email = models.EmailField(blank=True)
    vendor_phone = models.CharField(max_length=40, blank=True)
    vendor_address = models.TextField(blank=True)

    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # Issue / due dates
    issue_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)

    # Drop-ship?
    is_drop_ship = models.BooleanField(default=False,
        help_text='If true, ship-to overrides MSP address with client address.')
    ship_to_name = models.CharField(max_length=200, blank=True)
    ship_to_address = models.TextField(blank=True)

    # Money
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default='USD')

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'psa_purchase_orders'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-created_at']),
            models.Index(fields=['vendor_name']),
        ]

    def __str__(self):
        return f'{self.po_number} - {self.vendor_name}'

    def save(self, *args, **kwargs):
        if not self.po_number:
            self.po_number = self.next_number()
        super().save(*args, **kwargs)

    @classmethod
    def next_number(cls):
        from django.utils import timezone
        from django.db.models import Max
        year = timezone.now().year
        prefix = f'PO-{year}-'
        last = cls.objects.filter(po_number__startswith=prefix).aggregate(Max('po_number'))['po_number__max']
        if not last:
            return f'{prefix}00001'
        try:
            n = int(last.split('-')[-1])
        except (ValueError, IndexError):
            n = 0
        return f'{prefix}{n + 1:05d}'

    def recompute_totals(self):
        from decimal import Decimal
        subtotal = Decimal('0')
        for li in self.line_items.all():
            subtotal += (li.quantity or Decimal('0')) * (li.unit_price or Decimal('0'))
        self.subtotal = subtotal
        self.tax_amount = (subtotal * (self.tax_rate or Decimal('0'))) / Decimal('100')
        self.total = self.subtotal + self.tax_amount + (self.shipping_cost or Decimal('0'))
        return self.total


class PurchaseOrderLineItem(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='line_items')
    description = models.CharField(max_length=300)
    sku = models.CharField(max_length=80, blank=True)
    distributor_provider = models.CharField(max_length=40, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0,
        help_text='Phase 4.2 fills this from Receiving.')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'psa_purchase_order_lines'
        ordering = ['sort_order', 'pk']

    @property
    def line_total(self):
        from decimal import Decimal
        return (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))


# ---------------------------------------------------------------------------
# Phase 4.2 — Receiving + back-orders + serial-number capture
# ---------------------------------------------------------------------------

class POReceipt(models.Model):
    """
    A single receiving event against a PurchaseOrder. Multiple receipts
    per PO support partial deliveries — the model captures the moment
    of arrival, not the cumulative state (cumulative state is on
    PurchaseOrderLineItem.received_quantity).
    """
    po = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='receipts'
    )
    received_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    carrier = models.CharField(max_length=80, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    is_drop_ship_confirmed = models.BooleanField(
        default=False,
        help_text='When the PO is drop-ship and the client confirmed delivery.',
    )

    class Meta:
        db_table = 'psa_po_receipts'
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.po.po_number} receipt @ {self.received_at:%Y-%m-%d}'


class POReceiptLine(models.Model):
    """
    Per-line receive record. quantity_received MAY be less than the
    PO line's quantity (partial receive). The view that creates
    POReceipt rolls up these into PurchaseOrderLineItem.received_quantity
    so the PO's status flips to partial / received automatically.
    """
    receipt = models.ForeignKey(
        POReceipt, on_delete=models.CASCADE, related_name='lines'
    )
    po_line = models.ForeignKey(
        PurchaseOrderLineItem, on_delete=models.CASCADE, related_name='receipt_lines'
    )
    quantity_received = models.DecimalField(max_digits=10, decimal_places=2)
    serial_numbers = models.JSONField(
        default=list, blank=True,
        help_text='List of serial numbers captured at receive time. '
                  'Auto-create assets.Asset rows when set.',
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'psa_po_receipt_lines'

    def __str__(self):
        return f'{self.po_line.description}: +{self.quantity_received}'


class POBackOrder(models.Model):
    """
    Tracks the un-received remainder when a partial receipt happens.
    Created automatically from the receiving view when a PO line is
    short. Cleared when the back-order is later filled.
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('filled', 'Filled'),
        ('cancelled', 'Cancelled'),
    ]
    po = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='back_orders'
    )
    po_line = models.ForeignKey(
        PurchaseOrderLineItem, on_delete=models.CASCADE, related_name='back_orders'
    )
    quantity_outstanding = models.DecimalField(max_digits=10, decimal_places=2)
    expected_delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'psa_po_back_orders'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.po.po_number} back-order: {self.po_line.description} ({self.quantity_outstanding})'


# ---------------------------------------------------------------------------
# Phase 6.1 — Change requests with CAB approval workflow
# ---------------------------------------------------------------------------


class ChangeRequest(models.Model):
    """
    A change-management ticket extension. One-to-one with a Ticket whose
    ticket_type slug is 'change'. Captures CAB-relevant metadata that a
    regular ticket doesn't need:
      - Risk classification (low/medium/high/emergency)
      - Implementation + rollback plans
      - Scheduled window
      - Required approvers (set by category/risk)
      - Implementation status (cannot move ticket to 'Implementing'
        without all CAB approvals satisfied)
    """
    RISK_CHOICES = [
        ('low', 'Low - routine, well-tested'),
        ('medium', 'Medium - significant scope'),
        ('high', 'High - service-impacting potential'),
        ('emergency', 'Emergency - out-of-band, post-implement review'),
    ]
    IMPLEMENTATION_STATUS = [
        ('draft', 'Draft'),
        ('pending_cab', 'Pending CAB Approval'),
        ('approved', 'Approved - Ready to Implement'),
        ('rejected', 'Rejected by CAB'),
        ('implementing', 'Implementing'),
        ('verified', 'Verified - Successful'),
        ('failed', 'Failed - Rolled Back'),
        ('cancelled', 'Cancelled'),
    ]

    ticket = models.OneToOneField(
        'psa.Ticket', on_delete=models.CASCADE,
        related_name='change_request',
    )
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_change_requests',
    )

    risk = models.CharField(max_length=20, choices=RISK_CHOICES, default='medium')
    implementation_status = models.CharField(
        max_length=30, choices=IMPLEMENTATION_STATUS, default='draft',
    )

    # CAB members assigned to review this change (multi-approver)
    required_approvers = models.ManyToManyField(
        django_settings.AUTH_USER_MODEL, related_name='+',
        blank=True,
        help_text='Each must approve before the change moves to '
                  'Implementing. Empty = single approver via the '
                  'existing PSAApproval flow.',
    )

    # Plans
    implementation_plan = models.TextField(
        blank=True,
        help_text='Step-by-step plan. Required before submitting to CAB.',
    )
    rollback_plan = models.TextField(
        blank=True,
        help_text='If the change fails, how do we revert? Required for '
                  'high/emergency risk.',
    )
    impact_assessment = models.TextField(blank=True)
    backout_window_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Maximum minutes the change can run before triggering '
                  'auto-rollback considerations.',
    )

    # Scheduled window
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)

    # Outcome
    outcome_summary = models.TextField(blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    decision_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_change_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'implementation_status', '-created_at']),
            models.Index(fields=['risk', 'implementation_status']),
        ]

    def __str__(self):
        return f'Change for {self.ticket.ticket_number} ({self.get_risk_display()})'

    @property
    def is_cab_satisfied(self):
        """True when every required_approver has an 'approved' CABVote."""
        required_ids = set(self.required_approvers.values_list('id', flat=True))
        if not required_ids:
            # No CAB members configured - fall back to the existing single
            # PSAApproval check (returns True if there's an approved one).
            return self._fallback_single_approval_satisfied()
        approved_ids = set(
            self.cab_votes.filter(decision='approved').values_list('user_id', flat=True)
        )
        return required_ids.issubset(approved_ids)

    @property
    def has_cab_rejection(self):
        """True if any required approver rejected - terminal."""
        return self.cab_votes.filter(decision='rejected').exists()

    def _fallback_single_approval_satisfied(self):
        """For changes with no required_approvers configured, check if
        any CABVote with decision='approved' exists (lightweight)."""
        return self.cab_votes.filter(decision='approved').exists()

    def can_implement(self):
        """Required gate before flipping ticket status to Implementing."""
        return (
            self.implementation_status == 'approved'
            and not self.has_cab_rejection
            and self.is_cab_satisfied
        )

    def transition_status(self, new_status: str, *, by_user=None,
                          note: str = ''):
        """Phase 20 v8 (v3.17.276): change implementation_status and
        record the transition in `ChangeRequestTransition`. Caller-driven
        hook — direct field edits are still captured by a pre_save signal,
        but going through this method gives a friendly audit trail with a
        note + by_user attribution.
        """
        valid = dict(self.IMPLEMENTATION_STATUS)
        if new_status not in valid:
            raise ValueError(f'Unknown implementation_status: {new_status}')
        prev = self.implementation_status
        if prev == new_status:
            return None  # no-op
        self.implementation_status = new_status
        # Stamp matching timestamps for terminal-ish states
        ts = timezone.now()
        if new_status == 'pending_cab' and not self.submitted_at:
            self.submitted_at = ts
            if by_user is not None:
                self.submitted_by = by_user
        if new_status in ('approved', 'rejected'):
            self.decided_at = ts
            if by_user is not None:
                self.decided_by = by_user
        if new_status == 'implementing' and not self.actual_start:
            self.actual_start = ts
        if new_status in ('verified', 'failed', 'cancelled') and not self.actual_end:
            self.actual_end = ts
        # Suppress the post_save signal's auto-capture so we don't
        # double-record this transition.
        self._suppress_transition_signal = True
        try:
            self.save(update_fields=[
                'implementation_status', 'submitted_at', 'submitted_by',
                'decided_at', 'decided_by', 'actual_start', 'actual_end',
                'updated_at',
            ])
        finally:
            self._suppress_transition_signal = False
        ChangeRequestTransition.objects.create(
            change_request=self,
            from_status=prev,
            to_status=new_status,
            by_user=by_user,
            note=(note or '')[:1000],
        )
        return prev, new_status


class ChangeRequestTransition(models.Model):
    """Phase 20 v8 (v3.17.276): one row per implementation_status
    transition on a ChangeRequest. Powers the change-history viewer +
    enables compliance reporting without scraping AuditLog."""
    change_request = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE,
        related_name='transitions',
    )
    from_status = models.CharField(max_length=30)
    to_status = models.CharField(max_length=30)
    by_user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = 'psa_change_request_transitions'
        ordering = ['-at']
        indexes = [
            models.Index(fields=['change_request', '-at']),
        ]

    def __str__(self):
        return f'{self.from_status} → {self.to_status} @ {self.at:%Y-%m-%d %H:%M}'


class CABVote(models.Model):
    """
    Each CAB member's vote on a ChangeRequest. The change is approved
    when every required_approver has an 'approved' vote and zero have
    rejected.
    """
    DECISION_CHOICES = [
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('abstained', 'Abstained'),
    ]
    change_request = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name='cab_votes',
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='+',
    )
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    note = models.TextField(blank=True)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_cab_votes'
        unique_together = [['change_request', 'user']]
        ordering = ['-voted_at']

    def __str__(self):
        return f'{self.user.username}: {self.get_decision_display()}'


# ---------------------------------------------------------------------------
# Phase 6.2 — Problem records + root-cause analysis
# ---------------------------------------------------------------------------


class Problem(models.Model):
    """
    ITIL Problem record — the underlying cause behind recurring incidents.
    Links N Tickets together so techs can spot patterns. Has a status
    pipeline distinct from any single ticket: investigating -> known_error
    -> resolved.
    """
    STATUS_CHOICES = [
        ('investigating', 'Investigating'),
        ('known_error', 'Known Error - Workaround Available'),
        ('resolved', 'Resolved - Permanent Fix Deployed'),
        ('closed', 'Closed'),
        ('duplicate', 'Duplicate of Another Problem'),
    ]
    PRIORITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_problems',
    )
    problem_number = models.CharField(max_length=30, unique=True)  # PRB-YYYY-NNNNN
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='investigating')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')

    # Linked tickets (the recurring incidents that surfaced this problem)
    related_tickets = models.ManyToManyField(
        'psa.Ticket', related_name='problems', blank=True,
        help_text='Incidents that share this underlying root cause.',
    )
    duplicate_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='duplicates',
        help_text='If this problem turns out to be a duplicate, link to the canonical one.',
    )

    # RCA fields
    symptoms = models.TextField(
        blank=True,
        help_text='What the user / monitoring observed. The problem manifestation.',
    )
    root_cause = models.TextField(
        blank=True,
        help_text='Underlying cause. Required to flip status to known_error or resolved.',
    )
    workaround = models.TextField(
        blank=True,
        help_text='Temporary mitigation. Required when status=known_error.',
    )
    permanent_fix = models.TextField(
        blank=True,
        help_text='Permanent resolution. Required when status=resolved.',
    )
    fix_change_request = models.ForeignKey(
        'psa.ChangeRequest', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='problems_fixed',
        help_text='Optional link to the Change that deployed the permanent fix.',
    )

    # 5 Whys structured analysis
    five_whys = models.JSONField(
        default=list, blank=True,
        help_text='Optional structured 5-whys list - each entry is a string.',
    )

    # Lifecycle
    investigated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    assigned_to = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_problems_owned',
    )
    discovered_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_problems_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_problems'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', '-created_at']),
            models.Index(fields=['priority', 'status']),
        ]

    def __str__(self):
        return f'{self.problem_number} - {self.title[:60]}'

    @classmethod
    def next_number(cls):
        from django.utils import timezone
        from django.db.models import Max
        year = timezone.now().year
        prefix = f'PRB-{year}-'
        last = cls.objects.filter(problem_number__startswith=prefix).aggregate(
            Max('problem_number'))['problem_number__max']
        if not last:
            return f'{prefix}00001'
        try:
            n = int(last.split('-')[-1])
        except (ValueError, IndexError):
            n = 0
        return f'{prefix}{n + 1:05d}'

    def save(self, *args, **kwargs):
        if not self.problem_number:
            self.problem_number = self.next_number()
        super().save(*args, **kwargs)

    @property
    def related_ticket_count(self):
        return self.related_tickets.count()

    def can_advance_to(self, new_status):
        """Validate state transition + RCA requirements."""
        if new_status == 'known_error':
            return bool(self.root_cause and self.workaround)
        if new_status == 'resolved':
            return bool(self.root_cause and self.permanent_fix)
        return True


class ProblemNote(models.Model):
    """
    Investigation notes on a Problem. Append-only timeline of analysis
    progress. Distinct from ticket comments - these are the trail of
    "what we learned and when" during root-cause analysis.
    """
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='notes')
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    body = models.TextField()
    is_breakthrough = models.BooleanField(
        default=False,
        help_text='Mark when this note records a key analytical finding.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_problem_notes'
        ordering = ['-created_at']

    def __str__(self):
        return f'Note on {self.problem.problem_number} @ {self.created_at:%Y-%m-%d}'


# ---------------------------------------------------------------------------
# Phase 6.3 — Release management + Service-catalog governance
# ---------------------------------------------------------------------------


class ReleaseWindow(models.Model):
    """
    A scheduled release window — bundles one or more ChangeRequest
    records into a single deployment. Provides freeze flags so other
    techs know not to land additional changes during the window.
    """
    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('frozen', 'Frozen — In Progress'),
        ('completed', 'Completed'),
        ('rolled_back', 'Rolled Back'),
        ('cancelled', 'Cancelled'),
    ]
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_release_windows',
    )
    release_number = models.CharField(max_length=30, unique=True)  # REL-YYYY-NNNNN
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='planned')

    # Window timing
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)

    # Freeze: when True (or status='frozen'), the engine prevents new
    # changes from being added to this window AND warns when other
    # changes target the same scheduled time.
    is_frozen = models.BooleanField(default=False,
        help_text='When true, no new changes can be added; existing changes locked.')

    # Bundled changes
    changes = models.ManyToManyField(
        'psa.ChangeRequest', related_name='release_windows', blank=True,
    )

    # Rollback
    rollback_plan = models.TextField(
        blank=True,
        help_text='If the release fails, what do we revert? Required '
                  'before status flips to frozen / completed.',
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rolled_back_reason = models.TextField(blank=True)

    # People
    release_manager = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_release_windows_owned',
    )

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_release_windows'
        ordering = ['-scheduled_start']
        indexes = [
            models.Index(fields=['organization', 'status', '-scheduled_start']),
            models.Index(fields=['scheduled_start', 'scheduled_end']),
        ]

    def __str__(self):
        return f'{self.release_number} — {self.title[:60]}'

    @classmethod
    def next_number(cls):
        from django.utils import timezone
        from django.db.models import Max
        year = timezone.now().year
        prefix = f'REL-{year}-'
        last = cls.objects.filter(release_number__startswith=prefix).aggregate(Max('release_number'))['release_number__max']
        if not last:
            return f'{prefix}00001'
        try:
            n = int(last.split('-')[-1])
        except (ValueError, IndexError):
            n = 0
        return f'{prefix}{n + 1:05d}'

    def save(self, *args, **kwargs):
        if not self.release_number:
            self.release_number = self.next_number()
        super().save(*args, **kwargs)

    @property
    def change_count(self):
        return self.changes.count()

    @property
    def is_currently_active(self):
        from django.utils import timezone
        now = timezone.now()
        return (
            self.status in ('frozen', 'planned')
            and self.scheduled_start <= now <= self.scheduled_end
        )

    def can_advance_to(self, new_status):
        if new_status == 'frozen':
            return self.changes.exists() and bool(self.rollback_plan)
        if new_status == 'completed':
            return self.status in ('frozen', 'planned')
        return True


class ServiceCatalogChange(models.Model):
    """
    A pending edit to a ServiceCatalogItem. When the item has
    requires_approval=True, edits go into this draft model first and
    must be approved before they update the live catalog item.
    Provides full audit trail of who changed what.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved & Applied'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    catalog_item = models.ForeignKey(
        'psa.ServiceCatalogItem', on_delete=models.CASCADE,
        related_name='change_proposals',
    )
    proposed_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    proposed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reason = models.TextField(blank=True)

    # Snapshot of all editable fields BEFORE + AFTER the change.
    # Stored as JSON so the schema stays flexible if catalog fields evolve.
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict, blank=True)

    decided_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = 'psa_service_catalog_changes'
        ordering = ['-proposed_at']
        indexes = [
            models.Index(fields=['catalog_item', 'status']),
            models.Index(fields=['proposed_by', 'status']),
        ]

    def __str__(self):
        return f'Change to {self.catalog_item.name} ({self.get_status_display()})'

    def apply(self, decided_by):
        """Apply the after_snapshot to the catalog_item, mark approved.
        Returns True on success."""
        from django.utils import timezone
        item = self.catalog_item
        for field, value in (self.after_snapshot or {}).items():
            if hasattr(item, field):
                try:
                    setattr(item, field, value)
                except Exception:
                    continue
        item.last_published_at = timezone.now()
        item.last_published_by = decided_by
        item.save()
        self.status = 'approved'
        self.decided_by = decided_by
        self.decided_at = timezone.now()
        self.save()
        return True


# ---------------------------------------------------------------------------
# Phase 7 — Outsourcing: ticket sharing with subcontractor / partner orgs
# ---------------------------------------------------------------------------


class TicketShare(models.Model):
    """
    Records that a Ticket has been shared with an outsourcing partner.
    The partner sees this ticket via their copy of Client St0r — comments
    + status sync bidirectionally via the partner webhook.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Acceptance'),
        ('accepted', 'Accepted by Partner'),
        ('declined', 'Declined by Partner'),
        ('completed', 'Work Completed'),
        ('recalled', 'Recalled by Originator'),
    ]
    ticket = models.ForeignKey(
        'psa.Ticket', on_delete=models.CASCADE,
        related_name='shares',
    )
    partner_org = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='inbound_shared_tickets',
        limit_choices_to={'is_outsourcing_partner': True},
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    shared_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    shared_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True,
        help_text='Optional context passed to the partner.')
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'psa_ticket_shares'
        ordering = ['-shared_at']
        unique_together = [['ticket', 'partner_org']]

    def __str__(self):
        return f'{self.ticket.ticket_number} -> {self.partner_org.name}'


# ---------------------------------------------------------------------------
# Phase 10.1 — Email-to-ticket threading: capture every inbound and outbound
# email by Message-ID so replies thread correctly via In-Reply-To/References,
# not just by subject-regex matching.
# ---------------------------------------------------------------------------

class EmailMessage(models.Model):
    """
    One record per email received or sent. Inbound rows are written by the
    `psa_poll_email` poller; outbound rows are written by the threaded-reply
    helper (Phase 10.4). The Message-ID is the join key that lets the next
    inbound reply chain back to the right ticket without depending on the
    customer keeping the `[PSA-YYYY-NNNNNN]` token in the subject line.

    Cross-org isolation is enforced at the (organization, message_id) unique
    constraint: org A's Message-ID never matches when org B receives a reply.
    """
    DIRECTION_CHOICES = [
        ('in', 'Inbound'),
        ('out', 'Outbound'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_email_messages',
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE,
        related_name='email_messages',
        null=True, blank=True,
        help_text='Phase 10.3: NULL only for quarantined inbound mail '
                  'that was rejected before any ticket was created or '
                  'matched. Normal inbound + outbound rows always have '
                  'a ticket.',
    )
    ingestion_config = models.ForeignKey(
        EmailIngestionConfig,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='email_messages',
    )

    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    # v3.17.468 — message_id + in_reply_to reduced from 998 to 255 chars
    # to fit MySQL InnoDB's 3072-byte key limit (see migration 0027).
    # subject reduced to 512 — display fields don't need 998.
    message_id = models.CharField(max_length=255, db_index=True,
        help_text='RFC 5322 Message-ID, including angle brackets')
    in_reply_to = models.CharField(max_length=255, blank=True, db_index=True,
        help_text='Header value if this message replied to another')
    references = models.TextField(blank=True,
        help_text='Whitespace-separated chain of parent Message-IDs')

    from_email = models.CharField(max_length=320, blank=True)
    to_emails = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=512, blank=True)

    # Which transport handled this message (issue #142). Blank for legacy rows.
    # Inbound Graph rows are tagged 'graph'; outbound rows record the transport
    # that actually sent them ('smtp' or 'graph').
    transport = models.CharField(max_length=10, blank=True)
    # For inbound Graph messages: the immutable Graph message id, stored so a
    # later staff reply can use POST /messages/{id}/reply and preserve the M365
    # conversation. Immutable ids survive the message moving between folders.
    graph_message_id = models.CharField(max_length=255, blank=True, db_index=True)

    headers_raw = models.TextField(blank=True,
        help_text='Full raw headers; useful for debugging threading + DMARC later')
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)

    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Phase 10.3: quarantine flag for inbound mail that was rejected before
    # ticket creation (auto-responder loop, DMARC fail, spam keywords).
    # Quarantined rows still exist so admins can audit what got filtered.
    # `ticket` may be NULL for quarantined inbound — there's no ticket to
    # attach to.
    was_quarantined = models.BooleanField(default=False, db_index=True,
        help_text='Phase 10.3: True when the message was filtered out of the '
                  'normal ingestion path (auto-responder, DMARC fail, spam).')
    quarantine_reason = models.CharField(max_length=200, blank=True,
        help_text='One-line reason; cross-check raw headers for detail.')

    class Meta:
        db_table = 'psa_email_messages'
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'message_id'],
                name='uniq_psa_email_message_per_org',
            ),
        ]
        indexes = [
            models.Index(fields=['ticket', 'received_at']),
            models.Index(fields=['organization', 'in_reply_to']),
            models.Index(fields=['organization', 'was_quarantined', 'received_at']),
        ]

    def __str__(self):
        return f'[{self.direction}] {self.message_id} -> {self.ticket.ticket_number}'

    @staticmethod
    def parse_references(value: str) -> list[str]:
        """
        References / In-Reply-To are whitespace-separated `<id@host>` tokens.
        Walk the chain right-to-left: the rightmost ID is the immediate parent.
        """
        if not value:
            return []
        return [tok.strip() for tok in value.split() if tok.strip().startswith('<')]


# ---------------------------------------------------------------------------
# Phase 10.3 — Routing rules. Sender-domain → client-org auto-routing so a
# generic MSP help@ mailbox can fan inbound mail out to the right client
# tenant + queue + priority. Lower `order` fires first; first match wins.
# ---------------------------------------------------------------------------

class EmailRoutingRule(models.Model):
    """
    Per-MSP-tenant rule mapping sender-email shape to a client organization
    (and optional queue / priority overrides).

    `sender_domain_glob` matches against the sender's domain (everything
    after the @). Supports plain domains (``acme.com``) and wildcard
    subdomain patterns (``*.acme.com``). Whole-string match on full email
    (``noreply@acme.com``) is also supported by including the @.
    """
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_email_routing_rules',
        help_text='MSP tenant that owns this rule.',
    )
    name = models.CharField(max_length=120,
        help_text='Free-text label shown in the rules list.')
    sender_domain_glob = models.CharField(max_length=200,
        help_text='Match pattern. Examples: "acme.com" (exact domain), '
                  '"*.acme.com" (any subdomain), "noreply@acme.com" '
                  '(specific sender). Case-insensitive.')

    target_client_org = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_routing_targeted_by',
        help_text='Client org to route matching alerts/tickets to.',
    )
    queue_override = models.ForeignKey(
        Queue, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='email_routing_rules',
        help_text='Optional queue override; falls back to the ingestion '
                  'config default when blank.',
    )
    priority_override = models.ForeignKey(
        TicketPriority, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='email_routing_rules',
        help_text='Optional priority override; falls back to the ingestion '
                  'config default when blank.',
    )

    enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=100,
        help_text='Lower fires first; first match wins.')

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_email_routing_rules'
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['organization', 'enabled', 'order']),
        ]

    def __str__(self):
        return f'{self.sender_domain_glob} → {self.target_client_org.name}'

    def matches(self, sender_email: str) -> bool:
        """
        True if this rule's pattern matches ``sender_email``. The pattern
        is matched against either the full email (when it contains @) or
        just the domain part (when it doesn't).
        """
        if not sender_email or not self.sender_domain_glob:
            return False
        sender = sender_email.strip().lower()
        pattern = self.sender_domain_glob.strip().lower()
        # Pattern with @ → full-email comparison.
        if '@' in pattern:
            return _glob_match(pattern, sender)
        # Otherwise compare against the domain only.
        if '@' not in sender:
            return False
        domain = sender.split('@', 1)[1]
        return _glob_match(pattern, domain)


def _glob_match(pattern: str, value: str) -> bool:
    """
    Tiny glob matcher: ``*`` matches any number of characters in any
    segment of the value. Used by ``EmailRoutingRule.matches`` and the
    auto-responder detector. Stdlib ``fnmatch`` is fine for this — kept
    explicit so the matching semantics are visible.
    """
    import fnmatch
    return fnmatch.fnmatchcase(value, pattern)


# ---------------------------------------------------------------------------
# Phase 13 v7 (v3.17.266) — Recurring purchase templates
# ---------------------------------------------------------------------------

class RecurringPurchaseTemplate(models.Model):
    """A reusable purchase template that auto-spawns a PurchaseRequisition
    on a schedule. Common case: "Monthly toner refill — 4 units of HP CF410X
    from Distributor X" — the template runs every month and lands a draft PR
    in the queue, ready for the buyer to review and approve."""
    RECURRENCE_CHOICES = [
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='recurring_purchase_templates',
        help_text='MSP tenant that owns the template.',
    )
    client_org = models.ForeignKey(
        'core.Organization', on_delete=models.SET_NULL,
        related_name='recurring_purchase_templates_for_client',
        null=True, blank=True,
        help_text='Optional bill-to / drop-ship-to client.',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    vendor_name = models.CharField(max_length=200, blank=True,
        help_text='Snapshot of the target vendor; line items are stored '
                  'as a JSON list of {description, sku, quantity, unit_price}.')
    line_items_snapshot = models.JSONField(
        default=list, blank=True,
        help_text='List of dicts: [{"description":"…","sku":"…",'
                  '"quantity":1,"unit_price":0,"distributor_provider":""}, …]',
    )
    recurrence = models.CharField(max_length=20, choices=RECURRENCE_CHOICES,
                                   default='monthly')
    next_run_at = models.DateField(
        help_text='Next date the cron should spawn a PR from this template.')
    last_run_at = models.DateField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_recurring_purchase_templates'
        ordering = ['next_run_at', 'name']
        indexes = [
            models.Index(fields=['organization', 'enabled', 'next_run_at']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_recurrence_display()})'

    @staticmethod
    def _advance(date_in, recurrence: str):
        from datetime import timedelta as _td
        from dateutil.relativedelta import relativedelta as _rd
        if recurrence == 'weekly':
            return date_in + _td(days=7)
        if recurrence == 'biweekly':
            return date_in + _td(days=14)
        if recurrence == 'monthly':
            return date_in + _rd(months=1)
        if recurrence == 'quarterly':
            return date_in + _rd(months=3)
        if recurrence == 'yearly':
            return date_in + _rd(years=1)
        return date_in + _rd(months=1)

    def spawn_pr(self):
        """Create a PurchaseRequisition (draft) from this template's
        snapshot, advance ``next_run_at``, and stamp ``last_run_at``.
        Returns the new PR. Caller is responsible for saving the
        template after — `spawn_pr()` does that itself."""
        from datetime import date as _d
        from decimal import Decimal as _D

        pr = PurchaseRequisition.objects.create(
            organization=self.organization,
            client_org=self.client_org,
            title=self.name,
            description=(self.description or
                         f'Auto-spawned from recurring template "{self.name}"')[:5000],
            status='draft',
        )
        for li in self.line_items_snapshot or []:
            PurchaseRequisitionLineItem.objects.create(
                requisition=pr,
                description=str(li.get('description') or '')[:300],
                sku=str(li.get('sku') or '')[:80],
                distributor_provider=str(li.get('distributor_provider') or '')[:40],
                quantity=_D(str(li.get('quantity') or '1')),
                unit_price=_D(str(li.get('unit_price') or '0')),
            )
        # Recompute totals from the line items
        total = sum((li.line_total for li in pr.line_items.all()), _D('0'))
        pr.subtotal = total
        pr.total = total  # tax left at 0 for templates
        pr.save(update_fields=['subtotal', 'total', 'updated_at'])

        self.last_run_at = _d.today()
        self.next_run_at = self._advance(self.next_run_at, self.recurrence)
        self.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])
        return pr


# ---------------------------------------------------------------------------
# Phase 21 v13 (v3.17.311) — Site check-in / check-out (Field Mode).
# ---------------------------------------------------------------------------

class TicketKitItem(models.Model):
    """Phase 46 (v3.17.533): something the tech has to take to this job.

    One flat list covering three different things, because that is how it is
    read — a tech looks at one list before leaving, not three. `kind` says which
    of the two foreign keys is meaningful, or neither for a free-text line.

    Attached to the ticket rather than to the scheduled visit so the list
    survives rescheduling and shows wherever the ticket does. A ticket needing
    genuinely different kit on different days is better modelled as two tickets.
    """
    KIND_TOOL = 'tool'
    KIND_INVENTORY = 'inventory'
    KIND_OTHER = 'other'
    KIND_CHOICES = [
        (KIND_TOOL, 'Tool'),
        (KIND_INVENTORY, 'Inventory item'),
        (KIND_OTHER, 'Other / not stocked'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_ticket_kit_items',
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name='kit_items',
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)

    tool = models.ForeignKey(
        'inventory.Tool', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ticket_kit_items',
    )
    inventory_item = models.ForeignKey(
        'inventory.InventoryItem', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='ticket_kit_items',
    )
    # Free text for an 'other' line, and a copy of the name for the other two.
    # Denormalised on purpose: the FKs are SET_NULL, and a packing list that
    # goes blank because somebody retired a tool is worse than a stale label.
    description = models.CharField(max_length=255, blank=True)

    quantity = models.PositiveIntegerField(default=1)
    notes = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    # The point of the feature: a tech ticks things off while loading the van.
    packed = models.BooleanField(default=False)
    packed_at = models.DateTimeField(null=True, blank=True)
    packed_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_kit_items_packed',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ticket_kit_items'
        ordering = ['sort_order', 'kind', 'pk']
        indexes = [
            models.Index(fields=['ticket', 'kind']),
            models.Index(fields=['organization', 'packed']),
        ]
        constraints = [
            # The same tool or part listed twice on one ticket is a data-entry
            # slip, not a request for two lines. Quantity is the way to ask for
            # more than one.
            models.UniqueConstraint(
                fields=['ticket', 'tool'],
                condition=models.Q(tool__isnull=False),
                name='uniq_kit_tool_per_ticket'),
            models.UniqueConstraint(
                fields=['ticket', 'inventory_item'],
                condition=models.Q(inventory_item__isnull=False),
                name='uniq_kit_item_per_ticket'),
        ]

    def __str__(self):
        return f'{self.quantity}x {self.label}'

    @property
    def label(self) -> str:
        """What to show. Falls back to the stored copy if the row is gone."""
        if self.kind == self.KIND_TOOL and self.tool_id:
            return str(self.tool)
        if self.kind == self.KIND_INVENTORY and self.inventory_item_id:
            return self.inventory_item.name
        return self.description or '(unnamed)'

    @property
    def where(self) -> str:
        """Where to find it — the other half of "what to take"."""
        if self.kind == self.KIND_TOOL and self.tool_id:
            return self.tool.home
        if self.kind == self.KIND_INVENTORY and self.inventory_item_id:
            location = getattr(self.inventory_item, 'location', None)
            return location.name if location else ''
        return ''

    @property
    def stock_shortfall(self) -> int:
        """How many short stock is for this line, or 0.

        Only meaningful for inventory: telling a tech to take eight of
        something there are three of is the failure this list exists to avoid.
        """
        if self.kind != self.KIND_INVENTORY or not self.inventory_item_id:
            return 0
        available = self.inventory_item.quantity or 0
        return max(0, self.quantity - available)

    def clean(self):
        """Keep `kind` and the foreign keys honest.

        Without this a row can claim to be a tool while carrying an inventory
        item, and every reader downstream has to second-guess it.
        """
        from django.core.exceptions import ValidationError

        if self.kind == self.KIND_TOOL:
            if not self.tool_id:
                raise ValidationError({'tool': 'A tool line needs a tool.'})
            if self.inventory_item_id:
                raise ValidationError(
                    {'inventory_item': 'A tool line cannot also carry an inventory item.'})
        elif self.kind == self.KIND_INVENTORY:
            if not self.inventory_item_id:
                raise ValidationError(
                    {'inventory_item': 'An inventory line needs an item.'})
            if self.tool_id:
                raise ValidationError(
                    {'tool': 'An inventory line cannot also carry a tool.'})
        else:
            if self.tool_id or self.inventory_item_id:
                raise ValidationError(
                    'An "other" line must not reference a tool or inventory item.')
            if not (self.description or '').strip():
                raise ValidationError(
                    {'description': 'Describe the item so the tech knows what to bring.'})

    def save(self, *args, **kwargs):
        # Keep the display copy in step so `label` survives the FK being nulled.
        if self.kind == self.KIND_TOOL and self.tool_id:
            self.description = str(self.tool)[:255]
        elif self.kind == self.KIND_INVENTORY and self.inventory_item_id:
            self.description = self.inventory_item.name[:255]
        super().save(*args, **kwargs)


class SiteVisit(models.Model):
    """A tech's "I have arrived / I have left" record against an active
    ticket. Distinct from the generic Timeclock because it captures
    per-ticket onsite-duration evidence usable for billing line items
    and SLA forensics.

    Lifecycle:
      open (checked in) → closed (checked out)
    `duration_minutes` is computed at checkout. Open visits show on
    the dispatcher dashboard as "tech is currently onsite at X."
    """
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_site_visits',
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name='site_visits',
    )
    technician = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_site_visits',
    )

    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)

    # Geolocation captured from the PWA at check-in / check-out
    arrival_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                        null=True, blank=True)
    arrival_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                        null=True, blank=True)
    departure_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                          null=True, blank=True)
    departure_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                          null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'psa_site_visits'
        ordering = ['-checked_in_at']
        indexes = [
            models.Index(fields=['ticket', '-checked_in_at']),
            models.Index(fields=['technician', '-checked_in_at']),
            models.Index(fields=['organization', 'checked_out_at']),
        ]

    def __str__(self):
        state = 'open' if self.checked_out_at is None else f'{self.duration_minutes}m'
        return f'{self.technician} @ {self.ticket.ticket_number} ({state})'

    @property
    def is_open(self):
        return self.checked_out_at is None

    def check_out(self, *, lat=None, lng=None, notes=''):
        """Mark the visit closed and compute `duration_minutes`."""
        from django.utils import timezone as _tz
        if self.checked_out_at:
            return False  # already checked out
        self.checked_out_at = _tz.now()
        if lat is not None:
            self.departure_lat = lat
        if lng is not None:
            self.departure_lng = lng
        if notes:
            self.notes = (self.notes + ('\n' if self.notes else '')
                          + notes)[:5000]
        delta = self.checked_out_at - self.checked_in_at
        self.duration_minutes = max(0, int(delta.total_seconds() / 60))
        self.save(update_fields=[
            'checked_out_at', 'departure_lat', 'departure_lng',
            'duration_minutes', 'notes',
        ])
        return True


# ---------------------------------------------------------------------------
# Phase 21 v14 (v3.17.311) — Mileage and trip logging.
# ---------------------------------------------------------------------------

class MileageLog(models.Model):
    """Per-tech / per-ticket trip log. Auto-distance is computed by the
    haversine formula against the previous SiteVisit's departure
    coordinates when the new SiteVisit's arrival lands; manual entries
    bypass the geo computation."""
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='psa_mileage_logs',
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mileage_logs',
    )
    technician = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='psa_mileage_logs',
    )

    trip_date = models.DateField()
    miles = models.DecimalField(max_digits=8, decimal_places=2,
                                  help_text='Distance in miles')
    is_auto = models.BooleanField(
        default=False,
        help_text='True when computed from geofences; False when entered manually.',
    )
    start_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                      null=True, blank=True)
    start_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                      null=True, blank=True)
    end_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                    null=True, blank=True)
    end_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                    null=True, blank=True)
    purpose = models.CharField(
        max_length=200, blank=True,
        help_text='Optional label, e.g. "Onsite at ACME / Boston site"',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_mileage_logs'
        ordering = ['-trip_date', '-created_at']
        indexes = [
            models.Index(fields=['technician', '-trip_date']),
            models.Index(fields=['organization', '-trip_date']),
        ]

    def __str__(self):
        kind = 'auto' if self.is_auto else 'manual'
        return f'{self.miles} mi ({kind}) on {self.trip_date}'

    @staticmethod
    def haversine_miles(lat1, lng1, lat2, lng2):
        """Great-circle distance between two lat/lng pairs, in miles.
        Used by the auto-distance hook on SiteVisit check-in.
        Returns 0 if any coordinate is None."""
        from math import radians, sin, cos, asin, sqrt
        if any(v is None for v in (lat1, lng1, lat2, lng2)):
            return 0
        lat1, lng1, lat2, lng2 = (float(lat1), float(lng1),
                                    float(lat2), float(lng2))
        R_miles = 3958.8
        dlat = radians(lat2 - lat1)
        dlng = radians(lng2 - lng1)
        a = (sin(dlat / 2) ** 2 +
             cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2)
        return round(2 * R_miles * asin(sqrt(a)), 2)


# ---------------------------------------------------------------------------
# Phase 21 v7 (v3.17.312) — Technician completion signature.
# ---------------------------------------------------------------------------

class TicketSignature(models.Model):
    """Customer / on-site sign-off captured on the PWA completion screen.
    Mirrors `QuoteSignature` shape; one-to-one per ticket.

    The `signature_data` is a base64 data URI of the PNG drawn on a
    canvas pad. Stored verbatim — no server-side rendering needed.
    """
    ticket = models.OneToOneField(
        Ticket, on_delete=models.CASCADE,
        related_name='completion_signature',
    )
    signed_by_name = models.CharField(max_length=200)
    signed_by_title = models.CharField(max_length=200, blank=True)
    signature_data = models.TextField(
        help_text='Base64 data URI of the drawn signature (image/png)',
    )
    signed_at = models.DateTimeField(auto_now_add=True)
    captured_lat = models.DecimalField(max_digits=10, decimal_places=7,
                                          null=True, blank=True)
    captured_lng = models.DecimalField(max_digits=11, decimal_places=7,
                                          null=True, blank=True)
    captured_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        db_table = 'psa_ticket_signatures'
        indexes = [
            models.Index(fields=['ticket']),
        ]

    def __str__(self):
        return f'{self.ticket.ticket_number} signed by {self.signed_by_name} @ {self.signed_at:%Y-%m-%d}'


# ---------------------------------------------------------------------------
# Phase 21 v8 (v3.17.312) — Onsite checklist enforcement.
# ---------------------------------------------------------------------------

class TicketChecklistItem(models.Model):
    """Per-ticket pre-close checklist item. The `Ticket.has_outstanding_checklist`
    property is True until every required item is completed."""
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE,
        related_name='checklist_items',
    )
    label = models.CharField(max_length=300)
    is_required = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    sort_order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ticket_checklist_items'
        ordering = ['sort_order', 'pk']
        indexes = [
            models.Index(fields=['ticket', 'is_completed']),
        ]

    def __str__(self):
        check = '☑' if self.is_completed else '☐'
        return f'{check} {self.label}'

    def complete(self, *, user=None):
        from django.utils import timezone as _tz
        if self.is_completed:
            return False
        self.is_completed = True
        self.completed_at = _tz.now()
        self.completed_by = user
        self.save(update_fields=['is_completed', 'completed_at',
                                  'completed_by'])
        return True


# ---------------------------------------------------------------------------
# Phase 21 v9 (v3.17.313) — Web Push notifications.
# ---------------------------------------------------------------------------

class WebPushSubscription(models.Model):
    """A browser's Web Push subscription endpoint registered by the
    PWA. The mobile dispatcher calls `send_push(subscription, payload)`
    to deliver a notification (e.g. "New ticket assigned to you").

    Live delivery requires VAPID keys configured in `settings.WEBPUSH_*`
    and the `pywebpush` package; without those the helper returns a
    clear "not configured" stub rather than silently dropping pushes.
    """
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='web_push_subscriptions',
    )
    endpoint = models.URLField(
        max_length=600,
        help_text='Browser-issued push endpoint URL.',
    )
    p256dh_key = models.CharField(
        max_length=200,
        help_text='Public key from the browser (base64).',
    )
    auth_secret = models.CharField(
        max_length=100,
        help_text='Auth secret from the browser (base64).',
    )
    user_agent = models.CharField(max_length=400, blank=True)
    is_active = models.BooleanField(default=True)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_web_push_subscriptions'
        unique_together = [['user', 'endpoint']]
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f'{self.user} push @ {self.endpoint[:60]}…'

    def send(self, *, title: str, body: str = '', url: str = ''):
        """Phase 21 v9 helper. Sends a push notification to this
        subscription. Returns a result dict; updates `last_delivery_at`
        on success / `last_error` on failure.

        Today this is a stub that requires VAPID keys to be configured;
        the live `pywebpush` integration lands when an MSP adds keys
        to settings."""
        from django.utils import timezone as _tz
        from django.conf import settings as _settings
        public = getattr(_settings, 'WEBPUSH_VAPID_PUBLIC_KEY', '')
        private = getattr(_settings, 'WEBPUSH_VAPID_PRIVATE_KEY', '')
        if not (public and private):
            err = 'VAPID keys not configured (WEBPUSH_VAPID_PUBLIC_KEY / WEBPUSH_VAPID_PRIVATE_KEY)'
            self.last_error = err
            self.save(update_fields=['last_error'])
            return {'success': False, 'error': err}
        try:
            from pywebpush import webpush, WebPushException  # noqa: F401
        except ImportError:
            err = 'pywebpush package not installed'
            self.last_error = err
            self.save(update_fields=['last_error'])
            return {'success': False, 'error': err}
        # Live path would call webpush(...) here; keep stubbed until
        # someone actually wires a real key.
        self.last_delivery_at = _tz.now()
        self.last_error = ''
        self.save(update_fields=['last_delivery_at', 'last_error'])
        return {'success': True, 'title': title, 'body': body, 'url': url}


class EmailOutboundJob(models.Model):
    """Issue #142 (outbound) — a durable, idempotent outbound-send record for
    the Microsoft Graph transport.

    Graph send actions return HTTP 202 Accepted (queued for processing, NOT a
    delivery confirmation), and can fail transiently (429/5xx), so outbound
    Graph sends go through this job:
      * idempotency_key + a locking status transition prevent duplicate sends,
      * transient failures retry with backoff (honoring Retry-After),
      * permanent auth/validation errors fail fast,
      * a read-timeout AFTER submission is marked 'uncertain' and never auto-resent.

    The row also serves as the outbound audit trail (tenant, mailbox, sender,
    recipients, ticket, Graph operation + request id, submission time, result,
    error category, retry count). Full message bodies are stored here only so
    the send can be retried — they are never written to the application log.

    SMTP outbound stays synchronous and does NOT create a job (existing behavior
    is unchanged).
    """
    STATUS_QUEUED = 'queued'
    STATUS_SENDING = 'sending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_UNCERTAIN = 'uncertain'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent (accepted)'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_UNCERTAIN, 'Uncertain — needs review'),
    ]

    OP_SEND = 'send'
    OP_REPLY = 'reply'
    OP_REPLY_ALL = 'reply_all'
    OP_CHOICES = [
        (OP_SEND, 'sendMail'),
        (OP_REPLY, 'reply'),
        (OP_REPLY_ALL, 'replyAll'),
    ]

    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='email_outbound_jobs')
    ticket = models.ForeignKey(Ticket, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='email_outbound_jobs')
    config = models.ForeignKey(EmailIngestionConfig, on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='outbound_jobs')
    email_message = models.ForeignKey(EmailMessage, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='outbound_job')

    transport = models.CharField(max_length=10, default='graph')
    operation = models.CharField(max_length=12, choices=OP_CHOICES, default=OP_SEND)

    # Sender is always the server-configured mailbox — never caller-supplied.
    mailbox = models.CharField(max_length=320)
    # Immutable Graph id of the ingested message being replied to (reply ops).
    graph_message_id = models.CharField(max_length=255, blank=True)

    to_recipients = models.JSONField(default=list, blank=True)
    cc_recipients = models.JSONField(default=list, blank=True)
    bcc_recipients = models.JSONField(default=list, blank=True)
    reply_to = models.JSONField(default=list, blank=True)

    subject = models.CharField(max_length=998, blank=True)
    body_html = models.TextField(blank=True)
    body_text = models.TextField(blank=True)
    save_to_sent_items = models.BooleanField(default=True)
    attachment_ids = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_QUEUED, db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    ms_request_id = models.CharField(max_length=200, blank=True)
    last_error = models.TextField(blank=True)
    # transient | auth | validation | permanent | uncertain
    error_category = models.CharField(max_length=20, blank=True)

    locked_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True)

    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_email_outbound_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'next_attempt_at']),
            models.Index(fields=['organization', 'status']),
        ]

    def __str__(self):
        return f'[{self.transport}:{self.operation}] {self.status} -> {self.to_recipients}'

    @property
    def is_terminal(self):
        return self.status in (self.STATUS_SENT, self.STATUS_FAILED, self.STATUS_UNCERTAIN)
