"""
Reports and Analytics Models
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Organization

User = get_user_model()


class ReportTemplate(models.Model):
    """Pre-defined report templates"""

    REPORT_TYPES = [
        ('asset_summary', 'Asset Summary'),
        ('asset_lifecycle', 'Asset Lifecycle'),
        ('password_audit', 'Password Security Audit'),
        ('document_usage', 'Document Usage'),
        ('monitor_uptime', 'Monitor Uptime'),
        ('expiration_forecast', 'Expiration Forecast'),
        ('user_activity', 'User Activity'),
        ('organization_metrics', 'Organization Metrics'),
        ('custom', 'Custom Query'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    report_type = models.CharField(max_length=50, choices=REPORT_TYPES)
    query_template = models.TextField(help_text='SQL or Django ORM query template')
    parameters = models.JSONField(default=dict, help_text='Report parameters schema')
    is_global = models.BooleanField(default=False, help_text='Available to all users')
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='report_templates'
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ScheduledReport(models.Model):
    """Scheduled report generation"""

    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
    ]

    DELIVERY_METHODS = [
        ('email', 'Email'),
        ('download', 'Download Only'),
        ('both', 'Email and Download'),
    ]

    name = models.CharField(max_length=200)
    template = models.ForeignKey(ReportTemplate, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    delivery_method = models.CharField(max_length=20, choices=DELIVERY_METHODS, default='email')
    recipients = models.JSONField(default=list, help_text='List of email addresses')
    parameters = models.JSONField(default=dict)
    output_format = models.CharField(
        max_length=10, default='pdf',
        help_text='Output format: pdf | csv | excel | json',
    )
    is_active = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    # `next_run` left as nullable in the migration (was previously required) so
    # the cron runner can pick up rows where it's been blanked out, and so
    # newly-saved schedules can auto-populate it from `frequency`.
    next_run = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['next_run']

    def __str__(self):
        return f"{self.name} - {self.get_frequency_display()}"

    def save(self, *args, **kwargs):
        """v3.17.147: auto-set next_run from frequency when blank.

        Lets the cron runner (`run_scheduled_reports`) immediately pick up
        a freshly-created schedule on the next 15-minute tick instead of
        requiring callers to compute it themselves.
        """
        if not self.next_run:
            self.next_run = self._compute_next_run(timezone.now())
        super().save(*args, **kwargs)

    def _compute_next_run(self, from_dt):
        from datetime import timedelta
        freq = (self.frequency or 'daily').lower()
        if freq == 'hourly':
            return from_dt + timedelta(hours=1)
        if freq == 'daily':
            return from_dt + timedelta(days=1)
        if freq == 'weekly':
            return from_dt + timedelta(days=7)
        if freq == 'monthly':
            return from_dt + timedelta(days=30)
        if freq == 'quarterly':
            return from_dt + timedelta(days=90)
        return from_dt + timedelta(days=1)


class GeneratedReport(models.Model):
    """Generated report instances"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generating', 'Generating'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
        ('json', 'JSON'),
    ]

    template = models.ForeignKey(ReportTemplate, on_delete=models.CASCADE)
    scheduled_report = models.ForeignKey(
        ScheduledReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='pdf')
    parameters = models.JSONField(default=dict)
    file = models.FileField(upload_to='reports/%Y/%m/', null=True, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    generation_time = models.DurationField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.template.name} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class Dashboard(models.Model):
    """Custom dashboards"""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    is_default = models.BooleanField(default=False)
    is_global = models.BooleanField(default=False)
    layout = models.JSONField(default=dict, help_text='Dashboard widget layout')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class DashboardWidget(models.Model):
    """Dashboard widgets"""

    WIDGET_TYPES = [
        ('metric', 'Metric Card'),
        ('chart_line', 'Line Chart'),
        ('chart_bar', 'Bar Chart'),
        ('chart_pie', 'Pie Chart'),
        ('table', 'Data Table'),
        ('list', 'List View'),
        ('calendar', 'Calendar'),
        ('map', 'Map'),
    ]

    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name='widgets')
    title = models.CharField(max_length=200)
    widget_type = models.CharField(max_length=20, choices=WIDGET_TYPES)
    data_source = models.CharField(max_length=100, help_text='Data source identifier')
    query_params = models.JSONField(default=dict)
    position = models.JSONField(default=dict, help_text='Grid position {x, y, width, height}')
    refresh_interval = models.IntegerField(
        default=300,
        help_text='Auto-refresh interval in seconds (0 = no auto-refresh)'
    )
    configuration = models.JSONField(default=dict, help_text='Widget-specific configuration')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['dashboard', 'position']

    def __str__(self):
        return f"{self.dashboard.name} - {self.title}"


class AnalyticsEvent(models.Model):
    """Track user and system events for analytics"""

    EVENT_CATEGORIES = [
        ('user', 'User Action'),
        ('system', 'System Event'),
        ('api', 'API Call'),
        ('security', 'Security Event'),
    ]

    event_name = models.CharField(max_length=100)
    event_category = models.CharField(max_length=20, choices=EVENT_CATEGORIES)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    metadata = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['event_name', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['organization', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.event_name} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


# ---------------------------------------------------------------------------
# v3.17.211 — Configurable wallboards
#
# A wallboard is a TV-ready dashboard view: a grid of widgets sourced from
# the v3.17.142 widget registry (`reports.widget_sources.REGISTRY`), with
# its own refresh cadence. Each org can have multiple named wallboards
# (Operations / Sales / NOC etc.) and the rotation view cycles through
# them on an NOC TV without requiring user input.
# ---------------------------------------------------------------------------

class Wallboard(models.Model):
    """
    A named TV-ready dashboard.

    Two flavors:
    - **Org-scoped** (`organization` set) — visible to members of that
      organization plus staff/superusers. The original v3.17.211 mode.
    - **Global** (`organization=NULL`, v3.17.216) — visible to any
      staff_user / superuser; widgets render aggregates across every
      tenant in the system. Use this for an "Operations Overview" TV
      board in the NOC.

    `refresh_seconds` controls the meta-refresh on the rendered page;
    `rotate_seconds` (when > 0) is used by the rotation view to cycle to
    the next active wallboard. Rotation cycles within scope: a global
    board cycles only with other globals; an org board cycles with that
    org's other boards.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='wallboards',
        null=True, blank=True,
        help_text='Org that owns this wallboard. Leave empty for a '
                  '"Global" board visible to staff/superusers and '
                  'aggregating across every tenant.',
    )
    name = models.CharField(
        max_length=120,
        help_text='Free-text label shown in the wallboard list and as the page title.',
    )
    description = models.TextField(blank=True)

    refresh_seconds = models.PositiveIntegerField(
        default=60,
        help_text='How often each widget refreshes on the rendered page. '
                  'Set to 0 to disable auto-refresh.',
    )
    rotate_seconds = models.PositiveIntegerField(
        default=0,
        help_text='If > 0, the rotation view will move to the next wallboard '
                  'after this many seconds. 0 means rotation skips this board.',
    )

    is_active = models.BooleanField(default=True,
        help_text='Off ⇒ board still saves but is hidden from rotation + the list view.')
    order = models.PositiveIntegerField(default=100,
        help_text='Rotation position. Lower fires first; ties broken by name.')

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='wallboards_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reports_wallboards'
        ordering = ['order', 'name']
        unique_together = [['organization', 'name']]
        indexes = [
            models.Index(fields=['organization', 'is_active', 'order']),
        ]

    @property
    def is_global(self) -> bool:
        return self.organization_id is None

    def __str__(self):
        if self.organization_id is None:
            return f'{self.name} (Global)'
        return f'{self.name} ({self.organization.name})'

    def next_in_rotation(self):
        """
        Return the next wallboard in the same rotation scope, or self
        when there's only one rotatable board. Global boards rotate only
        with other globals; org boards rotate within their own org.
        """
        rotatable = (Wallboard.objects
                     .filter(organization=self.organization,
                             is_active=True, rotate_seconds__gt=0)
                     .order_by('order', 'name'))
        boards = list(rotatable)
        if not boards or len(boards) == 1:
            return self
        try:
            idx = boards.index(self)
        except ValueError:
            return boards[0]
        return boards[(idx + 1) % len(boards)]


class WallboardWidget(models.Model):
    """
    One widget on a wallboard. Sourced from the same data-source registry
    as `DashboardWidget` (`reports.widget_sources.REGISTRY`) so any new
    widget added there automatically becomes pickable for wallboards.
    """
    WIDGET_TYPES = DashboardWidget.WIDGET_TYPES  # keep the enum aligned

    wallboard = models.ForeignKey(
        Wallboard, on_delete=models.CASCADE, related_name='widgets',
    )
    title = models.CharField(max_length=200)
    widget_type = models.CharField(max_length=20, choices=WIDGET_TYPES)
    data_source = models.CharField(
        max_length=100,
        help_text='Key from reports.widget_sources.REGISTRY '
                  '(e.g. "open_tickets_count", "revenue_trend_30d").',
    )
    query_params = models.JSONField(default=dict, blank=True)
    configuration = models.JSONField(default=dict, blank=True,
        help_text='Widget-specific config (color, sub-title, etc.)')

    # Grid position. {x, y, width, height} in 12-column grid units.
    position = models.JSONField(
        default=dict,
        help_text='12-column grid position as {x, y, width, height}.',
    )
    order = models.PositiveIntegerField(
        default=100,
        help_text='Render order within the wallboard. Lower first.',
    )

    refresh_seconds = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Per-widget refresh override. NULL ⇒ inherit from the wallboard.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reports_wallboard_widgets'
        ordering = ['wallboard', 'order']

    def __str__(self):
        return f'{self.wallboard.name} → {self.title}'

    @property
    def effective_refresh_seconds(self) -> int:
        """Per-widget override wins; otherwise fall back to the wallboard."""
        if self.refresh_seconds is not None:
            return self.refresh_seconds
        return self.wallboard.refresh_seconds


# ---------------------------------------------------------------------------
# Phase 26 v1 (v3.17.246) — Custom Report Writer + Saved Queries
# ---------------------------------------------------------------------------

class SavedQuery(models.Model):
    """
    User-defined saved query. The filter set + sort + columns are
    persisted as JSON; the security boundary is `target_model` (must be
    in `reports.saved_query.MODEL_CONFIG`) and the filterable_fields
    allow-list inside that config.
    """
    TARGET_MODEL_CHOICES = [
        ('psa.Ticket', 'PSA Tickets'),
        ('assets.Asset', 'Assets'),
        ('vault.Password', 'Vault Passwords'),
        # Phase 26 v2 (v3.17.251)
        ('psa.Invoice', 'Invoices'),
        ('psa.TicketTimeEntry', 'Time Entries'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='saved_queries',
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='saved_queries',
        null=True, blank=True,
        help_text='Optional. When set, results are filtered to this org. '
                  'Null = run against every org the requester can see.',
    )
    target_model = models.CharField(
        max_length=80, choices=TARGET_MODEL_CHOICES,
        help_text='Which app+model to query.',
    )
    filters = models.JSONField(
        default=list, blank=True,
        help_text='List of {field, op, value} dicts. Bad fields are '
                  'silently ignored at run time.',
    )
    columns = models.JSONField(
        default=list, blank=True,
        help_text='Ordered list of field names to render. Empty = all '
                  'columns from the target_model\'s default set.',
    )
    sort_by = models.CharField(max_length=120, blank=True)
    is_shared = models.BooleanField(
        default=False,
        help_text='When true, other members of the same organization '
                  'can see + run this query.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'reports_saved_queries'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['owner', '-updated_at']),
            models.Index(fields=['organization', 'is_shared']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_target_model_display()})'

    def visible_to(self, user) -> bool:
        if self.owner_id == user.id:
            return True
        if user.is_superuser or getattr(user, 'is_staff', False):
            return True
        if self.is_shared and self.organization_id and user.is_authenticated:
            return user.memberships.filter(
                organization_id=self.organization_id, is_active=True,
            ).exists()
        return False

    def can_edit(self, user) -> bool:
        return self.owner_id == user.id or user.is_superuser


# ---------------------------------------------------------------------------
# Wallboard displays: a TV shows one board without anyone signing in.
#
# A display holds a long random credential in a cookie scoped to
# /reports/wallboards/display/. Only an HMAC of it is stored
# (vault.secret_fields.hash_token), like share links and API keys. The data a
# display sees is fixed when it is authorised (`scope`): the board's customer,
# or every customer only when the person who authorised it could see every
# customer. Nothing about that person's rights is consulted afterwards.
# See reports/displays.py and docs/WALLBOARD_DISPLAYS.md.
# ---------------------------------------------------------------------------

class WallboardDisplay(models.Model):
    """One TV (paired) or one secret display link allowed to show a board."""

    KIND_PAIRED = 'paired'
    KIND_LINK = 'link'
    KIND_CHOICES = [
        (KIND_PAIRED, 'Paired display'),
        (KIND_LINK, 'Display link'),
    ]

    wallboard = models.ForeignKey(
        Wallboard, on_delete=models.CASCADE, related_name='displays',
    )
    name = models.CharField(max_length=120, help_text='e.g. "NOC TV left".')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_PAIRED)

    credential_hash = models.CharField(
        max_length=64, unique=True, null=True, blank=True, editable=False,
        help_text='HMAC-SHA256 of the display credential (paired) or link token '
                  '(link). Empty until a paired TV collects its credential.',
    )
    scope = models.JSONField(
        default=dict, blank=True, editable=False,
        help_text='Data scope fixed when the display was authorised: '
                  '{"org_ids": [id] | null, "perm_orgs": {perm: [ids] | null}}.',
    )
    allowed_networks = models.TextField(
        blank=True,
        help_text='Optional IP addresses / CIDR ranges, one per line. '
                  'Empty = any network.',
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='wallboard_displays_revoked',
    )

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='wallboard_displays_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Where the TV asked to be paired from (paired displays only).
    pairing_ip = models.GenericIPAddressField(null=True, blank=True)
    pairing_user_agent = models.CharField(max_length=255, blank=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_ip = models.GenericIPAddressField(null=True, blank=True)
    last_seen_user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'reports_wallboard_displays'
        ordering = ['wallboard', '-created_at']

    def __str__(self):
        return f'{self.name} → {self.wallboard.name}'

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_usable(self):
        return not self.is_revoked and not self.is_expired

    @property
    def network_list(self):
        return [n.strip() for n in (self.allowed_networks or '').replace(',', '\n').splitlines()
                if n.strip()]


class WallboardPairingRequest(models.Model):
    """A TV asking to be paired: a short code shown on screen and a random
    secret in its cookie. Valid 10 minutes, single use; only hashes stored."""

    code_hash = models.CharField(max_length=64, unique=True, editable=False)
    secret_hash = models.CharField(max_length=64, unique=True, editable=False)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    display = models.OneToOneField(
        WallboardDisplay, on_delete=models.CASCADE, null=True, blank=True,
        related_name='pairing_request',
        help_text='Set when someone approves the code; the TV then collects '
                  'its credential and this request is deleted.',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'reports_wallboard_pairing_requests'

    def __str__(self):
        return f'Pairing request {self.pk} ({"approved" if self.display_id else "pending"})'

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()
