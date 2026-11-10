"""
PSA AI Assist — models.

`AISuggestion` is the proposal (drafted by the model, may or may not be
applied). `AIActionLog` is the structured outcome record once a
suggestion is approved + executed. `AIUsageBucket` tracks token spend
per (org, day) and (user, day) for cost guardrails.

All models scoped to `core.Organization`. Cross-tenant access is
prevented at the queryset layer in views; defence-in-depth checks at
the service layer too.
"""
from django.conf import settings as django_settings
from django.db import models


KIND_CHOICES = [
    ('reply', 'Reply'),
    ('action', 'Action'),
    ('triage', 'Triage Guidance'),
]
REVIEW_STATES = [
    ('draft', 'Drafted by AI — awaiting tech review'),
    ('pending_review', 'Awaiting senior approval'),
    ('approved', 'Approved (and applied)'),
    ('rejected', 'Rejected by reviewer'),
    ('expired', 'Expired before action'),
    ('superseded', 'Replaced by a newer suggestion'),
    ('failed', 'Generation failed'),
    ('blocked', 'Blocked by safety filter'),
]
RISK_LEVELS = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]


class AISuggestion(models.Model):
    """A single AI proposal attached to a PSA ticket."""
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, related_name='ai_suggestions'
    )
    # Either native_ticket or psa_ticket is set (never both, never neither).
    native_ticket = models.ForeignKey(
        'psa.Ticket', null=True, blank=True,
        on_delete=models.CASCADE, related_name='ai_suggestions',
    )
    psa_ticket = models.ForeignKey(
        'integrations.PSATicket', null=True, blank=True,
        on_delete=models.CASCADE, related_name='ai_suggestions',
    )

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    risk_level = models.CharField(max_length=20, choices=RISK_LEVELS, default='medium')
    review_state = models.CharField(max_length=20, choices=REVIEW_STATES, default='draft')

    # Generation metadata
    model_name = models.CharField(max_length=100)
    model_version = models.CharField(max_length=50, blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    prompt_version = models.CharField(max_length=50, blank=True)

    # Reply content (when kind='reply')
    suggested_body = models.TextField(blank=True)
    final_body = models.TextField(blank=True, help_text='What was actually sent (after edits)')

    # Action payload (when kind='action')
    action_type = models.CharField(max_length=50, blank=True)
    action_payload = models.JSONField(default=dict, blank=True)

    # Context audit — what we fed the model. Vault data is forbidden here;
    # the no-secrets test verifies it. Stored for replay/diagnose only.
    context_snapshot = models.JSONField(default=dict, blank=True)

    # Token accounting — for cost guardrails + per-user rate-limit.
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    requested_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )

    # Review trail
    created_at = models.DateTimeField(auto_now_add=True)
    requested_review_at = models.DateTimeField(null=True, blank=True)
    requested_review_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    reviewer = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    class Meta:
        db_table = 'psa_ai_suggestions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'review_state', '-created_at']),
            models.Index(fields=['native_ticket', '-created_at']),
            models.Index(fields=['psa_ticket', '-created_at']),
            models.Index(fields=['requested_by', '-created_at']),
        ]

    def __str__(self):
        ref = self.native_ticket_id or self.psa_ticket_id or '?'
        return f'AISuggestion {self.kind}/{self.review_state} on ticket {ref}'

    def ticket_obj(self):
        return self.native_ticket or self.psa_ticket


class AIActionLog(models.Model):
    """Append-only outcome record for an applied AISuggestion."""
    suggestion = models.ForeignKey(
        AISuggestion, on_delete=models.CASCADE, related_name='action_logs'
    )
    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE, related_name='ai_action_logs'
    )
    actor = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField()
    error = models.TextField(blank=True)
    diff = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'psa_ai_action_logs'
        ordering = ['-applied_at']


class AIUsageBucket(models.Model):
    """
    Daily token spend per scope. One row per (organization, day) and
    one per (user, day). Used for cost ceilings — checked BEFORE every
    generation. Updated atomically via F() expressions.
    """
    SCOPE_CHOICES = [('org', 'Organization'), ('user', 'User')]
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    organization = models.ForeignKey(
        'core.Organization', null=True, blank=True,
        on_delete=models.CASCADE, related_name='ai_usage_buckets',
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name='ai_usage_buckets',
    )
    day = models.DateField(db_index=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    generations = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'psa_ai_usage_buckets'
        unique_together = [
            ('scope', 'organization', 'user', 'day'),
        ]
        indexes = [
            models.Index(fields=['scope', 'day']),
            models.Index(fields=['organization', 'day']),
            models.Index(fields=['user', 'day']),
        ]

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens


# ===========================================================================
# Ticket AI Assist (v3.17.646): profiles, policy, analysis jobs, budgets.
#
# Who holds what: ClientSt0r keeps every provider credential here, sealed,
# and calls providers only from its own inference gateway
# (services/gateway.py). rem0te processes the job and asks the gateway for
# each model run; it never receives a key. See docs/contracts/ticket-rmm-v1/.
# ===========================================================================

import uuid



class AIModelProfile(models.Model):
    """One provider + model the gateway may call, and whose key it uses.

    Off until an administrator enables it. Credential ownership decides who
    may spend it:
      company    — the customer's own key; usable for that organization only
      msp        — the MSP's key; usable only for organizations it is
                   explicitly assigned to
      technician — one technician's own key; usable only by them, and only
                   for organizations whose policy allows technician keys
    """
    PROVIDER_CHOICES = [
        ('anthropic', 'Claude (Anthropic)'),
        ('openai', 'OpenAI'),
        ('ollama', 'Ollama (local)'),
    ]
    OWNER_COMPANY = 'company'
    OWNER_MSP = 'msp'
    OWNER_TECHNICIAN = 'technician'
    OWNER_CHOICES = [
        (OWNER_COMPANY, 'Customer company'),
        (OWNER_MSP, 'MSP (assigned customers only)'),
        (OWNER_TECHNICIAN, 'Technician (only where the customer allows it)'),
    ]
    LOCATION_CLOUD = 'cloud'
    LOCATION_LOCAL = 'local'

    name = models.CharField(max_length=100, unique=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    model = models.CharField(max_length=100)
    enabled = models.BooleanField(default=False)
    economical = models.BooleanField(
        default=False, help_text='Default model for "Analyze ticket" when a policy names none.')
    # Ollama only: where the model runs. A local profile must also be
    # approved before a local-only policy will use it.
    base_url = models.URLField(blank=True, default='')
    local_approved = models.BooleanField(
        default=False, help_text='An administrator confirmed this Ollama host is on-premises.')

    credential_owner = models.CharField(max_length=12, choices=OWNER_CHOICES)
    owner_organization = models.ForeignKey(
        'core.Organization', null=True, blank=True, on_delete=models.CASCADE,
        related_name='owned_ai_profiles')
    owner_user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name='owned_ai_profiles')
    assigned_organizations = models.ManyToManyField(
        'core.Organization', blank=True, related_name='assigned_ai_profiles',
        help_text='MSP-owned keys: the customers this key may be spent on.')
    # Sealed to the AI gateway's public key (services/gateway_keys.py). The
    # web app can store a key but never read it back; only the gateway
    # process, which holds the private key and not APP_MASTER_KEY, opens it.
    sealed_api_key = models.TextField(blank=True, default='')
    # The origin (scheme://host:port) an administrator approved for an
    # Ollama profile through a protected change. The gateway refuses any
    # other destination, so editing base_url alone sends nothing anywhere.
    approved_destination = models.CharField(max_length=300, blank=True, default='')

    # Pricing for estimates and budgets, in hundredths of a cent per 1k tokens.
    input_price_per_1k = models.PositiveIntegerField(default=0, help_text='1/100 cent per 1k input tokens')
    output_price_per_1k = models.PositiveIntegerField(default=0, help_text='1/100 cent per 1k output tokens')
    max_output_tokens = models.PositiveIntegerField(default=1500)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_model_profiles'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()} {self.model})'

    @property
    def location(self):
        return self.LOCATION_LOCAL if self.provider == 'ollama' else self.LOCATION_CLOUD

    def set_api_key(self, key):
        from psa_ai.services.gateway_keys import seal
        self.sealed_api_key = seal(key) if key else ''

    @property
    def has_api_key(self):
        return bool(self.sealed_api_key)


class AIBusinessPolicy(models.Model):
    """What AI one customer allows. Without a row, nothing is allowed."""
    organization = models.OneToOneField(
        'core.Organization', on_delete=models.CASCADE, related_name='ai_policy')
    analysis_enabled = models.BooleanField(default=False)
    compare_enabled = models.BooleanField(default=False)
    allowed_profiles = models.ManyToManyField(AIModelProfile, blank=True, related_name='policies')
    default_profile = models.ForeignKey(
        AIModelProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    allow_technician_credentials = models.BooleanField(default=False)
    local_only = models.BooleanField(
        default=False, help_text='Both the processor and the model must be on-premises.')
    daily_budget_cents = models.PositiveIntegerField(
        default=0, help_text='Spend ceiling per day across all AI runs, in cents. 0 = no spend.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_business_policies'

    def __str__(self):
        return f'AI policy for {self.organization}'


class AIBudgetDay(models.Model):
    """Per-organization spend for one day, in 1/100 cent. Reservations are
    taken with one conditional UPDATE (services/budget.py), so concurrent
    runs can never overshoot the ceiling."""
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    day = models.DateField()
    reserved = models.PositiveBigIntegerField(default=0)
    spent = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = 'psa_ai_budget_days'
        unique_together = [('organization', 'day')]


class AnalysisJob(models.Model):
    """One technician-requested analysis of one ticket, processed by rem0te.

    Everything the job may touch is bound here at submit time — tenant,
    business, ticket revision, actor, profiles, evidence digest, expiry —
    and the gateway refuses any inference request that disagrees."""
    KIND_ANALYZE = 'analyze'
    KIND_COMPARE = 'compare'
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('submitted', 'Submitted'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('partial', 'Completed with some models failing'),
        ('failed', 'Failed'),
        ('unavailable', 'Processor unavailable'),
        ('expired', 'Expired'),
    ]
    TERMINAL = {'completed', 'partial', 'failed', 'unavailable', 'expired'}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.CASCADE, related_name='ai_analysis_jobs')
    ticket_revision = models.CharField(max_length=64)
    actor = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    kind = models.CharField(max_length=10, choices=[(KIND_ANALYZE, 'Analyze'), (KIND_COMPARE, 'Compare')])
    connection = models.ForeignKey(
        'integrations.RMMConnection', on_delete=models.PROTECT, related_name='+',
        help_text='The rem0te pairing that processes this job.')
    business_id = models.CharField(max_length=100)
    endpoint_device = models.ForeignKey(
        'integrations.RMMDevice', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    evidence = models.JSONField(default=dict, help_text='Redacted evidence exactly as sent.')
    evidence_digest = models.CharField(max_length=64)
    payload_digest = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=64)
    correlation_id = models.UUIDField(default=uuid.uuid4)
    expires_at = models.DateTimeField()

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='created')
    processor_job_id = models.CharField(max_length=100, blank=True, default='')
    last_event_sequence = models.PositiveIntegerField(default=0)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    disagreements = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_analysis_jobs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['actor', 'idempotency_key'], name='psa_ai_job_idempotency'),
        ]
        indexes = [models.Index(fields=['ticket', '-created_at'])]

    def __str__(self):
        return f'AnalysisJob {self.id} ({self.kind}, {self.status})'

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL


class AnalysisRun(models.Model):
    """One model's run inside a job. The result is the validated structure
    from services/analysis_result.py, never raw model text."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('dispatched', 'Claimed, waiting for the gateway'),
        ('executing', 'Running in the gateway'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('refused', 'Refused by the gateway'),
    ]
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='runs')
    profile = models.ForeignKey(AIModelProfile, on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    estimated_cost = models.PositiveIntegerField(default=0, help_text='1/100 cent')
    reserved_cost = models.PositiveIntegerField(default=0)
    actual_cost = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'psa_ai_analysis_runs'
        unique_together = [('job', 'profile')]
        ordering = ['pk']


class ProcessorEvent(models.Model):
    """A signed callback from rem0te, kept for de-duplication and audit."""
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='events')
    event_id = models.CharField(max_length=100)
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=40)
    applied = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ai_processor_events'
        unique_together = [('job', 'event_id')]


class IntegrationNonce(models.Model):
    """Request nonces seen on the integration API, so a captured signed
    request cannot be replayed (shared across every worker, unlike a cache)."""
    connection_id = models.PositiveIntegerField()
    nonce = models.CharField(max_length=64)
    seen_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'psa_ai_integration_nonces'
        unique_together = [('connection_id', 'nonce')]


# ===========================================================================
# RMM handoffs, read-only diagnostics and fix referrals (v3.17.657,
# Phase 56.5 / 56.6). Not AI features: they work with AI switched off.
#
# ClientSt0r records what a technician asked the paired RMM for and shows
# the RMM's signed status updates. It never runs anything on a device, never
# marks a fix approved itself, and no status from the RMM can close the
# ticket or send a customer reply (services/rmm_actions.py).
# ===========================================================================

class RMMRequest(models.Model):
    """One technician request to the paired RMM about one ticket's device."""
    KIND_HANDOFF = 'handoff'
    KIND_DIAGNOSTIC = 'diagnostic'
    KIND_FIX = 'fix_referral'
    KIND_CHOICES = [(KIND_HANDOFF, 'Handoff'), (KIND_DIAGNOSTIC, 'Read-only diagnostic'),
                    (KIND_FIX, 'Fix referral')]
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('pending', 'Waiting for the RMM to confirm'),
        ('sent', 'Sent — receipt confirmed'),
        ('received', 'Received by the RMM'),
        ('running', 'Running in the RMM'),
        ('completed', 'Completed'),
        ('approved', 'Approved in the RMM'),
        ('rejected', 'Rejected by the RMM'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('unavailable', 'RMM unavailable'),
        ('expired', 'Expired without an answer'),
    ]
    TERMINAL = {'sent', 'completed', 'rejected', 'succeeded', 'failed', 'unavailable', 'expired'}
    RISK_CHOICES = [('low', 'Low'), ('high', 'Higher')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.CASCADE, related_name='rmm_requests')
    connection = models.ForeignKey('integrations.RMMConnection', on_delete=models.PROTECT, related_name='+')
    device = models.ForeignKey('integrations.RMMDevice', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    device_external_id = models.CharField(max_length=255, help_text='The RMM device ID as sent.')
    device_name = models.CharField(max_length=255, blank=True, default='')
    tenant_id = models.CharField(max_length=100)
    actor = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    diagnostic_key = models.CharField(max_length=64, blank=True, default='')
    diagnostic_label = models.CharField(max_length=100, blank=True, default='')
    fix_title = models.CharField(max_length=200, blank=True, default='')
    fix_risk = models.CharField(max_length=4, choices=RISK_CHOICES, blank=True, default='')
    payload = models.JSONField(default=dict, help_text='What was sent, exactly (redacted).')
    payload_digest = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=64)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='created')
    remote_id = models.CharField(max_length=100, blank=True, default='')
    last_event_sequence = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True, default='')
    status_note = models.CharField(max_length=500, blank=True, default='',
                                   help_text="The RMM's own words for the latest status, sanitised.")
    # Diagnostic output: staff-only, sanitised text, size-limited.
    result_text = models.TextField(blank=True, default='')
    result_bytes = models.PositiveIntegerField(default=0)
    result_truncated = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_rmm_requests'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['actor', 'idempotency_key'], name='psa_ai_rmm_request_idempotency'),
        ]
        indexes = [models.Index(fields=['ticket', '-created_at'])]

    def __str__(self):
        return f'RMMRequest {self.id} ({self.kind}, {self.status})'

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL


class RMMRequestEvent(models.Model):
    """A signed status callback for an RMMRequest, kept for de-duplication and audit."""
    request = models.ForeignKey(RMMRequest, on_delete=models.CASCADE, related_name='events')
    event_id = models.CharField(max_length=100)
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=40)
    applied = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ai_rmm_request_events'
        unique_together = [('request', 'event_id')]
        ordering = ['pk']
