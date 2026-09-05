"""
Phase 40.2 (v3.17.540) — public / client-facing status pages.

A status page answers "is anything broken?" without the client phoning the
queue. It is read by people who are not logged in, which drives most of the
design here: nothing appears on one of these pages unless somebody explicitly
put it there, under a name they explicitly chose.
"""
import secrets

from django.db import models
from django.contrib.auth.models import User

from core.models import Organization, BaseModel
from monitoring.models import WebsiteMonitor


class StatusPage(BaseModel):
    """One published status page.

    Follows the Phase 47 wallboard's disclosure rules, for the same reason —
    an unauthenticated URL is the only thing between this and the internet:

      * off by default (`is_enabled=False`), and a disabled page 404s rather
        than 403s, because a 403 confirms the page exists;
      * the address carries a 43-character random token rather than the org id,
        so it cannot be found by walking integers;
      * the token rotates, which invalidates a leaked link immediately.

    Unlike the wallboard this is **not** a singleton. An MSP typically wants one
    broadcast page covering shared infrastructure plus, later, a page per client
    (Sub-phase 40.5). `organization` null means "not scoped to one client" — it
    is the MSP's own page and can carry services from anywhere.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True,
        related_name='status_pages',
        help_text='Leave empty for a page not tied to one client.')

    # Phase 40.5 (v3.17.543). Default is `public` so every page that existed
    # before this field keeps behaving exactly as it did.
    VISIBILITY_PUBLIC = 'public'
    VISIBILITY_PORTAL = 'portal'
    VISIBILITY_CHOICES = [
        (VISIBILITY_PUBLIC, 'Public — anyone with the link'),
        (VISIBILITY_PORTAL, 'Portal — signed-in client users only'),
    ]
    visibility = models.CharField(
        max_length=10, choices=VISIBILITY_CHOICES, default=VISIBILITY_PUBLIC,
        help_text='Public pages are read by anyone holding the link. Portal '
                  'pages are read only by signed-in users of the client they '
                  'belong to, and their link does not work anonymously.')

    is_enabled = models.BooleanField(
        default=False,
        help_text='Off by default. While off, the URL returns 404.')
    token = models.CharField(
        max_length=64, unique=True, db_index=True,
        help_text='Random component of the public URL. Rotating it breaks '
                  'every existing link immediately.')

    title = models.CharField(
        max_length=120, blank=True,
        help_text='Heading on the page. Defaults to "Service status".')
    intro = models.TextField(
        blank=True,
        help_text='Optional paragraph under the heading. Plain text.')

    show_uptime = models.BooleanField(
        default=True,
        help_text='Show 30 / 90 / 365-day uptime percentages per service.')
    show_response_time = models.BooleanField(
        default=False,
        help_text='Show the last response time. Off by default — it invites '
                  'questions that a status page cannot answer.')

    refresh_seconds = models.PositiveIntegerField(
        default=120,
        help_text='How often the page reloads itself. Minimum 30.')

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='status_pages_created')

    class Meta:
        db_table = 'statuspage_pages'
        ordering = ['organization__name', 'title']

    def __str__(self):
        scope = self.organization.name if self.organization_id else 'All clients'
        return f'{self.display_title} ({scope}, {"on" if self.is_enabled else "off"})'

    @staticmethod
    def new_token() -> str:
        """43 URL-safe characters from `secrets` — not `random`, which is
        seeded predictably and has no business generating anything that acts as
        a credential."""
        return secrets.token_urlsafe(32)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = self.new_token()
        # A status page that reloads every second would hammer the server for
        # no human benefit; nobody watches one at that resolution.
        self.refresh_seconds = max(30, int(self.refresh_seconds or 120))
        super().save(*args, **kwargs)

    def rotate_token(self):
        self.token = self.new_token()
        self.save(update_fields=['token', 'updated_at'])
        return self.token

    @property
    def display_title(self) -> str:
        return self.title or 'Service status'

    @property
    def is_public(self) -> bool:
        return self.visibility == self.VISIBILITY_PUBLIC

    def get_public_url(self) -> str:
        from django.urls import reverse
        return reverse('statuspage:public', args=[self.token])

    def get_portal_url(self) -> str:
        from django.urls import reverse
        return reverse('portal:status')

    @classmethod
    def for_portal_user(cls, organization):
        """Phase 40.5: the portal page a signed-in client user should see.

        A page scoped to their own organization wins over a broadcast one. Both
        must be explicitly set to portal visibility — a public page is not
        silently reused here, because the two have different audiences and an
        operator may deliberately publish less on the anonymous one.
        """
        qs = cls.objects.filter(
            is_enabled=True, visibility=cls.VISIBILITY_PORTAL)
        own = qs.filter(organization=organization).first()
        if own is not None:
            return own
        return qs.filter(organization__isnull=True).first()

    # --- What the page says overall ---

    def overall_status(self):
        """`operational` / `degraded` / `outage` / `unknown`.

        Worst wins: one service down makes the page say outage, because a
        client whose mail is down does not care that the website is fine.
        """
        states = [s.current_status() for s in self.visible_services()]
        if not states:
            return 'unknown'
        if 'outage' in states:
            return 'outage'
        if 'degraded' in states:
            return 'degraded'
        if all(s == 'unknown' for s in states):
            return 'unknown'
        return 'operational'

    def visible_services(self):
        return list(
            self.services.filter(is_visible=True)
            .select_related('monitor')
            .order_by('sort_order', 'display_name')
        )


class StatusPageService(models.Model):
    """A monitor, as published on a page.

    The indirection is the point. A `WebsiteMonitor` carries an internal name
    and the URL being polled, and neither belongs on an anonymous page — "PROD
    mail relay (10.4.0.7)" tells a stranger more about the estate than the
    client needs to read. `display_name` is required and is what the public
    sees; the monitor behind it is never disclosed.

    Not a `BaseModel` — this is a join row with an ordering, and nobody needs to
    know when a service was reordered.
    """
    page = models.ForeignKey(
        StatusPage, on_delete=models.CASCADE, related_name='services')
    monitor = models.ForeignKey(
        WebsiteMonitor, on_delete=models.CASCADE, related_name='status_page_entries')

    display_name = models.CharField(
        max_length=120,
        help_text='What the public sees. Never the monitor name or its URL.')
    description = models.CharField(
        max_length=255, blank=True,
        help_text='Optional one-liner, e.g. "Webmail and calendar".')

    sort_order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(
        default=True,
        help_text='Hide without deleting — keeps the history if you re-show it.')

    class Meta:
        db_table = 'statuspage_services'
        ordering = ['sort_order', 'display_name']
        # The same monitor twice on one page is a mistake every time.
        unique_together = [['page', 'monitor']]

    def __str__(self):
        return f'{self.display_name} → {self.page_id}'

    def current_status(self):
        """Monitor status translated into status-page vocabulary.

        `warning` becomes `degraded` rather than an outage: a redirect or an
        expiring certificate means the service answered. A page that showed a
        301 as an outage would cry wolf until nobody read it.
        """
        return {
            'active': 'operational',
            'warning': 'degraded',
            'down': 'outage',
        }.get(self.monitor.status, 'unknown')

    def uptime_windows(self):
        """30 / 90 / 365-day uptime, for the page's uptime row.

        Each is `None` when there are no checks in that window rather than a
        number — history only began accumulating in v3.17.538, so a 365-day
        figure is genuinely unknown until a year after that deploy, and
        printing 100% would be an invention.
        """
        return [
            {'days': days, **self.monitor.uptime(days)}
            for days in (30, 90, 365)
        ]


class MaintenanceWindow(BaseModel):
    """Phase 40.3 (v3.17.541): planned work, announced before it happens.

    The point of a status page is to stop the "is anything broken?" call. Planned
    work generates exactly that call unless it is posted in advance, so a window
    is visible from the moment it is created — not from the moment it starts.

    State is derived from the clock rather than stored, with one exception.
    A stored status would need a job to advance it and would be wrong in the gap
    between the window opening and that job running; `cancelled` is the
    exception because no amount of looking at the clock can tell you a window
    was called off.
    """
    page = models.ForeignKey(
        StatusPage, on_delete=models.CASCADE, related_name='maintenance_windows')

    title = models.CharField(max_length=160)
    body = models.TextField(
        blank=True,
        help_text='What is happening and what the client should expect. '
                  'Plain text — this is read by people outside the business.')

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    # Optional. A window affecting everything leaves this empty rather than
    # listing every service, which would need updating whenever one is added.
    services = models.ManyToManyField(
        StatusPageService, blank=True, related_name='maintenance_windows',
        help_text='Leave empty if the work affects everything on the page.')

    is_cancelled = models.BooleanField(
        default=False,
        help_text='Called off. Stays on the page as cancelled rather than '
                  'vanishing, so anyone who read the original notice can see '
                  'it is no longer happening.')

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='maintenance_windows_created')

    class Meta:
        db_table = 'statuspage_maintenance_windows'
        ordering = ['-starts_at']

    def __str__(self):
        return f'{self.title} ({self.starts_at:%Y-%m-%d %H:%M})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'Maintenance must end after it starts.'})

    @property
    def state(self):
        """`cancelled` / `upcoming` / `in_progress` / `completed`."""
        from django.utils import timezone as tz
        if self.is_cancelled:
            return 'cancelled'
        now = tz.now()
        if now < self.starts_at:
            return 'upcoming'
        if now >= self.ends_at:
            return 'completed'
        return 'in_progress'

    @property
    def affects_everything(self) -> bool:
        return not self.services.exists()

    def affected_names(self):
        """Service names for display, or None when it affects everything."""
        if self.affects_everything:
            return None
        return [s.display_name for s in self.services.all()]


class StatusPageIncident(BaseModel):
    """Phase 40.4 (v3.17.542): an incident, as published.

    The roadmap called for "each incident is a ticket with is_status_page =
    True". The flag exists on `psa.Ticket` and marks a ticket as publishable,
    but the published record is this one, for the same reason
    `StatusPageService` exists rather than pointing straight at a monitor: a
    ticket subject is written for the queue. "Exchange transport stuck, DAG
    node 2 down again" is a fine subject and a terrible thing to show a
    client's customers.

    So `title` is required and written for the audience. The ticket link is
    optional — an incident can be posted without one, and often should be
    before anyone has opened a ticket.
    """
    page = models.ForeignKey(
        StatusPage, on_delete=models.CASCADE, related_name='incidents')
    ticket = models.ForeignKey(
        'psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='status_page_incidents',
        help_text='Optional. Links the published incident back to the work.')

    title = models.CharField(
        max_length=200,
        help_text='What the public sees. Not the ticket subject.')
    started_at = models.DateTimeField()
    resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the incident is over. Until then it reads as ongoing.')

    root_cause = models.TextField(
        blank=True,
        help_text='Optional, published once known. Plain text.')

    services = models.ManyToManyField(
        StatusPageService, blank=True, related_name='incidents',
        help_text='Leave empty if the incident affected everything on the page.')

    is_published = models.BooleanField(
        default=True,
        help_text='Unpublish to pull it from the page without deleting the '
                  'record and its updates.')

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='status_page_incidents_created')

    class Meta:
        db_table = 'statuspage_incidents'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.title} ({self.started_at:%Y-%m-%d})'

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def state(self) -> str:
        return 'resolved' if self.is_resolved else 'ongoing'

    @property
    def affects_everything(self) -> bool:
        return not self.services.exists()

    def affected_names(self):
        if self.affects_everything:
            return None
        return [s.display_name for s in self.services.all()]

    def timeline(self):
        """Updates oldest-first — an incident is read as a story."""
        return self.updates.order_by('posted_at')


class IncidentUpdate(models.Model):
    """Phase 40.4 (v3.17.542): one entry on an incident's timeline.

    Deliberately **not** sourced from ticket comments. A comment marked
    non-internal is visible to the client in the portal, which is a different
    and much smaller audience than an anonymous status page — the two are not
    interchangeable, and quietly treating them as the same would republish
    ticket chatter to the internet. Updates here are written for the page.

    Not a `BaseModel`: an update is a dated statement of what was true at a
    point in time. Editing one silently would rewrite history, so there is no
    `updated_at` to suggest that is normal.
    """
    STAGES = [
        ('investigating', 'Investigating'),
        ('identified', 'Identified'),
        ('monitoring', 'Monitoring'),
        ('resolved', 'Resolved'),
    ]

    incident = models.ForeignKey(
        StatusPageIncident, on_delete=models.CASCADE, related_name='updates')
    stage = models.CharField(max_length=20, choices=STAGES, default='investigating')
    body = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='incident_updates_posted')

    class Meta:
        db_table = 'statuspage_incident_updates'
        ordering = ['posted_at']

    def __str__(self):
        return f'{self.get_stage_display()} @ {self.posted_at:%Y-%m-%d %H:%M}'
