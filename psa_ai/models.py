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
    history_retention_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Days to keep this customer\'s ticket AI and automation history (AI drafts, analysis jobs, '
                  'RMM requests and the decisions on them). Blank = the installation default '
                  '(PSA_AI_HISTORY_RETENTION_DAYS, 365). 0 = keep until deleted by hand.')

    # --- tenant exclusion (every AI feature, enforced in profiles.profile_refusal
    # and therefore inside the gateway too) ---------------------------------------
    ai_excluded = models.BooleanField(
        default=False, help_text='Exclude this customer from every AI feature, whatever else is set here.')

    # --- AI Troubleshoot (OPTIONAL AI; services/troubleshoot.py) -----------------
    ROUTE_PRIMARY, ROUTE_FALLBACK, ROUTE_LOCAL_FIRST, ROUTE_CHEAPEST = 'primary', 'fallback', 'local_first', 'cheapest'
    ROUTING_CHOICES = [
        (ROUTE_PRIMARY, 'Primary model only'),
        (ROUTE_FALLBACK, 'Primary, then the secondary model if the primary is unusable or fails'),
        (ROUTE_LOCAL_FIRST, 'Prefer an approved on-premises model of the two'),
        (ROUTE_CHEAPEST, 'Prefer the cheaper of the two'),
    ]
    troubleshoot_enabled = models.BooleanField(
        default=False, help_text='Allow AI Troubleshoot on this customer\'s tickets and devices.')
    primary_profile = models.ForeignKey(
        AIModelProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Troubleshoot: primary model. Blank = the policy default / economical model.')
    secondary_profile = models.ForeignKey(
        AIModelProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Troubleshoot: secondary model (fallback, or the second opinion in multi-model analysis).')
    multi_model_enabled = models.BooleanField(
        default=False, help_text='Troubleshoot: allow running primary and secondary side by side and comparing.')
    model_routing = models.CharField(max_length=12, choices=ROUTING_CHOICES, default=ROUTE_PRIMARY)
    monthly_budget_cents = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Spend ceiling per calendar month across all AI runs, in cents. Blank = no monthly ceiling '
                  '(the daily ceiling still applies).')
    troubleshoot_daily_runs = models.PositiveIntegerField(
        default=50, help_text='Troubleshoot runs per day for this customer, all technicians together. 0 = none.')
    troubleshoot_technician_daily_runs = models.PositiveIntegerField(
        default=20, help_text='Troubleshoot runs per day per technician at this customer. 0 = none.')

    # --- information-sharing rules: what may leave for a model -------------------
    # Enforced in services/troubleshoot.build_observations before any prompt
    # text exists; what was withheld is listed on the preview and the session.
    share_ticket_text = models.BooleanField(
        default=True, help_text='Ticket subject, description and public conversation.')
    share_device_data = models.BooleanField(
        default=True, help_text='Device name, OS, RMM status, alerts and read-only diagnostic output.')
    share_network_identifiers = models.BooleanField(
        default=False, help_text='Hostnames, IP and MAC addresses. Off = replaced with placeholders.')
    share_contact_data = models.BooleanField(
        default=False, help_text='Contact and requester names. Off = replaced with [contact].')
    share_kb_titles = models.BooleanField(
        default=True, help_text='Titles of this customer\'s and global KB articles and runbooks, so the model '
                                'can point at relevant ones.')
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
    PROTOCOL_HMAC = 'hmac'
    PROTOCOL_REM0TE = 'rem0te-ed25519'
    PROTOCOL_CHOICES = [(PROTOCOL_HMAC, 'ticket-rmm-v1 (HMAC pairing)'),
                        (PROTOCOL_REM0TE, "ticket-rmm-v1 (Rem0te's Ed25519 protocol)")]

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
    # Rem0te (Ed25519) jobs: the exact job request sent (canonical, defaults
    # applied — its sha256 is what the delegation token is bound to), and
    # Rem0te's signed, staff-only result.
    protocol = models.CharField(max_length=20, choices=PROTOCOL_CHOICES, default=PROTOCOL_HMAC)
    processor_request = models.JSONField(default=dict, blank=True)
    processor_result = models.JSONField(default=dict, blank=True)
    processor_error_code = models.CharField(max_length=64, blank=True, default='')
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
    # What actually ran, recorded when the gateway executes the run: the
    # provider/model the profile named at that moment (profiles can be
    # edited later) and the system prompt's stable version (file name +
    # content hash, services/prompt_versions.py). Blank = never executed.
    resolved_model = models.CharField(max_length=150, blank=True, default='')
    prompt_version = models.CharField(max_length=80, blank=True, default='')
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
# RMM handoffs, read-only diagnostics and fix referrals (v3.17.658,
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
    # Rem0te action proposals: where Rem0te's approvers approve (shown, never
    # acted on here), and Rem0te's own status word.
    approval_url = models.URLField(max_length=500, blank=True, default='')
    remote_status = models.CharField(max_length=40, blank=True, default='')
    # Rem0te's own answer about approval and outcome, as last reported
    # (integrations/rem0te/actions.py). Shown in the ticket's AI and
    # automation history; never acted on here.
    approvals_required = models.PositiveSmallIntegerField(null=True, blank=True)
    customer_signoff = models.BooleanField(null=True, blank=True)
    approval_expires_at = models.DateTimeField(
        null=True, blank=True, help_text="End of Rem0te's approval/execution window (window.not_after).")
    remote_outcome = models.CharField(max_length=20, blank=True, default='')
    observed = models.JSONField(default=dict, blank=True,
                                help_text="Rem0te's observed result, sanitised and size-limited.")
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


# ===========================================================================
# Rem0te monitoring alerts → tickets (contract ticket-rmm-v1, Rem0te ≥ 0.29).
# integrations/rem0te/alerts.py has the rules.
# ===========================================================================

class Rem0teAlertEvent(models.Model):
    """A signed alert event received from Rem0te (pushed or polled), kept for
    de-duplication, gap detection and audit."""
    connection = models.ForeignKey('integrations.RMMConnection', on_delete=models.CASCADE, related_name='+')
    event_id = models.CharField(max_length=64)
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=20)
    alert_id = models.CharField(max_length=64)
    body = models.JSONField(default=dict)
    received_via = models.CharField(max_length=8, default='push')
    received_at = models.DateTimeField(auto_now_add=True)
    # False: authentic (signature verified) but not applied — e.g. a shape
    # this ClientSt0r does not understand. Kept so the gap-free cursor moves
    # on, shown on the connection's health, and re-tried by reconciliation
    # after the next successful capabilities check.
    applied = models.BooleanField(default=True)
    problem = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        db_table = 'psa_ai_rem0te_alert_events'
        constraints = [
            models.UniqueConstraint(fields=['connection', 'event_id'], name='psa_ai_rem0te_alert_event_once'),
        ]
        indexes = [models.Index(fields=['connection', 'sequence'])]


class Rem0teAlertTicket(models.Model):
    """The one ticket opened for one Rem0te alert. The unique constraint is
    what makes `alert.raised` → exactly one ticket, however often the event
    is pushed, polled or retried, and across restarts."""
    LINK_PENDING, LINK_LINKED, LINK_CONFLICT, LINK_FAILED = 'pending', 'linked', 'conflict', 'failed'
    LINK_CHOICES = [(LINK_PENDING, 'Not linked in Rem0te yet'), (LINK_LINKED, 'Linked in Rem0te'),
                    (LINK_CONFLICT, 'Rem0te has another ticket for this alert'), (LINK_FAILED, 'Link failed')]
    connection = models.ForeignKey('integrations.RMMConnection', on_delete=models.CASCADE, related_name='+')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    alert_id = models.CharField(max_length=64)
    ticket = models.ForeignKey('psa.Ticket', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='rem0te_alerts')
    rem0te_endpoint_id = models.CharField(max_length=64, blank=True, default='')
    computer_name = models.CharField(max_length=128, blank=True, default='')
    kind = models.CharField(max_length=20, blank=True, default='')
    severity = models.CharField(max_length=10, blank=True, default='')
    state = models.CharField(max_length=15, blank=True, default='')
    title = models.CharField(max_length=300, blank=True, default='')
    last_sequence = models.PositiveIntegerField(default=0)
    link_status = models.CharField(max_length=10, choices=LINK_CHOICES, default=LINK_PENDING)
    link_error = models.CharField(max_length=300, blank=True, default='')
    link_attempts = models.PositiveIntegerField(default=0)
    next_link_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Contract revision 2: Rem0te's redacted patch summary of the computer on
    # a REBOOT_PENDING alert (KB numbers, states, ages, labels only), as of
    # the latest event. Empty for other alerts and revision-1 peers.
    patch_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_rem0te_alert_tickets'
        constraints = [
            models.UniqueConstraint(fields=['connection', 'alert_id'], name='psa_ai_rem0te_alert_one_ticket'),
        ]


# ===========================================================================
# Ticket AI and automation history (staff only). services/history.py builds
# the timeline; these rows hold what no other model records.
# ===========================================================================

class AIDraftDecision(models.Model):
    """What a technician did with an AI draft: recorded by the server when a
    comment that came from an AI draft is posted (or refused). The marker the
    composer sends is only a hint; the draft is resolved against this
    ticket's own suggestions and analysis jobs (services/drafts.py)."""
    SOURCE_SUGGESTION = 'suggestion'
    SOURCE_ANALYSIS = 'analysis'
    SOURCE_REM0TE = 'rem0te'
    SOURCE_CHOICES = [(SOURCE_SUGGESTION, 'AI reply suggestion'), (SOURCE_ANALYSIS, 'Ticket analysis draft'),
                      (SOURCE_REM0TE, "Rem0te's verified draft")]
    SENT = 'sent'
    SENT_EDITED = 'sent_edited'
    KEPT_INTERNAL = 'kept_internal'
    SEND_REFUSED = 'send_refused'
    DECISION_CHOICES = [
        (SENT, 'Sent to the customer unchanged'),
        (SENT_EDITED, 'Edited, then sent to the customer'),
        (KEPT_INTERNAL, 'Kept as an internal note'),
        (SEND_REFUSED, 'Send refused (no permission to send AI-assisted replies)'),
    ]

    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.CASCADE, related_name='ai_draft_decisions')
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES)
    suggestion = models.ForeignKey(AISuggestion, null=True, blank=True, on_delete=models.CASCADE,
                                   related_name='draft_decisions')
    job = models.ForeignKey(AnalysisJob, null=True, blank=True, on_delete=models.CASCADE,
                            related_name='draft_decisions')
    draft_index = models.PositiveSmallIntegerField(null=True, blank=True)
    decision = models.CharField(max_length=14, choices=DECISION_CHOICES)
    comment = models.ForeignKey('psa.TicketComment', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    actor = models.ForeignKey(django_settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'psa_ai_draft_decisions'
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['ticket', 'created_at'])]

    def __str__(self):
        return f'{self.get_decision_display()} ({self.source}) on ticket {self.ticket_id}'


class AIHistoryPurgeState(models.Model):
    """One row (pk=1): when the AI and automation history was last purged,
    so the every-minute poll_analysis_jobs task purges at most every few hours."""
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_deleted = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'psa_ai_history_purge_state'


class AIBudgetMonth(models.Model):
    """Per-organization spend for one calendar month, in 1/100 cent. Kept by
    services/budget.py next to AIBudgetDay with the same conditional UPDATE,
    so AIBusinessPolicy.monthly_budget_cents can't be overshot either."""
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    month = models.DateField(help_text='First day of the month.')
    reserved = models.PositiveBigIntegerField(default=0)
    spent = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = 'psa_ai_budget_months'
        unique_together = [('organization', 'month')]


# ===========================================================================
# AI Troubleshoot (OPTIONAL AI, gated by psa_ai_enabled; services/troubleshoot.py).
#
# Four layers, never mixed, in storage as in the UI:
#   Observation        TroubleshootSession.observations — data with its source
#                      and freshness, filtered by the sharing rules
#   AI inference       TroubleshootRun.result — labelled with model + prompt version
#   Technician action  TroubleshootActionLink → the RMMRequest the technician
#                      created through the normal request/approval flow
#   Verified result    that RMMRequest's signed outcome from the RMM
# The AI never executes anything and never calls an RMM.
# ===========================================================================

class TroubleshootSession(models.Model):
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('partial', 'Completed with some models failing'),
        ('failed', 'Failed'),
    ]
    TERMINAL = {'completed', 'partial', 'failed'}
    MODE_SINGLE, MODE_MULTI = 'single', 'multi'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    ticket = models.ForeignKey('psa.Ticket', null=True, blank=True, on_delete=models.CASCADE,
                               related_name='ai_troubleshoot_sessions')
    device = models.ForeignKey('integrations.RMMDevice', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    actor = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    mode = models.CharField(max_length=8, choices=[(MODE_SINGLE, 'One model'), (MODE_MULTI, 'Multi-model')])
    routing = models.CharField(max_length=12, blank=True, default='')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    observations = models.JSONField(default=dict, help_text='Redacted observations exactly as sent.')
    observations_digest = models.CharField(max_length=64)
    sharing = models.JSONField(default=dict, blank=True,
                               help_text='The sharing rules applied, and what was withheld.')
    comparison = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=64)
    error = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_troubleshoot_sessions'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['actor', 'idempotency_key'], name='psa_ai_troubleshoot_idempotency'),
        ]
        indexes = [models.Index(fields=['ticket', '-created_at']), models.Index(fields=['device', '-created_at']),
                   models.Index(fields=['organization', 'created_at'])]

    def __str__(self):
        return f'TroubleshootSession {self.id} ({self.status})'

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL


class TroubleshootRun(models.Model):
    """One model's inference inside a session. `result` is the validated
    structure from services/troubleshoot_result.py, never raw model text."""
    ROLE_CHOICES = [('primary', 'Primary'), ('secondary', 'Secondary'), ('fallback', 'Fallback')]
    session = models.ForeignKey(TroubleshootSession, on_delete=models.CASCADE, related_name='runs')
    profile = models.ForeignKey(AIModelProfile, on_delete=models.PROTECT, related_name='+')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='primary')
    status = models.CharField(max_length=10, choices=AnalysisRun.STATUS_CHOICES, default='pending')
    reserved_cost = models.PositiveIntegerField(default=0, help_text='1/100 cent')
    actual_cost = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True, default='')
    resolved_model = models.CharField(max_length=150, blank=True, default='')
    prompt_version = models.CharField(max_length=80, blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'psa_ai_troubleshoot_runs'
        unique_together = [('session', 'profile')]
        ordering = ['pk']


class TroubleshootActionLink(models.Model):
    """A suggested action a technician chose to request, and the RMMRequest
    it created through the normal request/approval flow. The AI suggestion
    authorises nothing; this row only records that a person asked."""
    session = models.ForeignKey(TroubleshootSession, on_delete=models.CASCADE, related_name='action_links')
    action_ref = models.CharField(max_length=20, help_text='The action ID in the session observations (X1, X2…).')
    action_key = models.CharField(max_length=100)
    rmm_request = models.ForeignKey(RMMRequest, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='troubleshoot_links')
    requested_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'psa_ai_troubleshoot_action_links'
        ordering = ['created_at', 'pk']


# ===========================================================================
# Installation-wide AI settings (superusers; psa_ai/profile_views.py).
# ===========================================================================

class AIInstallationSettings(models.Model):
    """One row (pk=1): settings that apply across every customer.

    monthly_budget_cents caps what the whole installation spends on AI in a
    calendar month, on top of each customer's own daily and monthly ceilings
    (services/budget.reserve takes all of them in the same reservation).
    command_allowlist narrows the read-only commands AI Troubleshoot may show
    (services/troubleshoot_result); the built-in denylist always applies."""
    monthly_budget_cents = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Spend cap per calendar month for the whole installation, all customers together, in cents. '
                  'Blank = no installation-wide cap (each customer\'s own ceilings still apply).')
    command_allowlist = models.TextField(
        blank=True,
        help_text='AI Troubleshoot: read-only command patterns, one per line (* matches anything, ? one '
                  'character; case-insensitive; lines starting with # are comments). When any are set, a '
                  'suggested command is kept only if it matches one. The built-in denylist of commands that '
                  'change a system always applies. Commands are only ever shown as text.')
    updated_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'psa_ai_installation_settings'

    def __str__(self):
        return 'AI installation settings'

    @classmethod
    def load(cls):
        from django.db import IntegrityError, transaction
        row = cls.objects.filter(pk=1).first()
        if row is None:
            try:
                with transaction.atomic():
                    row = cls.objects.create(pk=1)
            except IntegrityError:
                row = cls.objects.get(pk=1)
        return row


class AIBudgetInstallMonth(models.Model):
    """Installation-wide spend for one calendar month, in 1/100 cent, kept by
    services/budget.py with the same conditional UPDATE as AIBudgetMonth so
    AIInstallationSettings.monthly_budget_cents can't be overshot."""
    month = models.DateField(unique=True, help_text='First day of the month.')
    reserved = models.PositiveBigIntegerField(default=0)
    spent = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = 'psa_ai_budget_install_months'
