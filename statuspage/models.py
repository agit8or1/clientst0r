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

    is_enabled = models.BooleanField(
        default=False,
        help_text='Off by default. While off, the public URL returns 404.')
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

    def get_public_url(self) -> str:
        from django.urls import reverse
        return reverse('statuspage:public', args=[self.token])

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
