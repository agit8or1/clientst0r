"""
Phase 12 v2 (v3.17.232): Portal Announcements.

A portal announcement is a banner posted by an MSP admin (or a client
admin when granted) that's visible to all portal users of a given org
until it expires or is dismissed.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class PortalAnnouncement(models.Model):
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('danger', 'Critical'),
    ]

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.CASCADE,
        related_name='portal_announcements',
        help_text='Client org whose portal users should see this banner.',
    )
    title = models.CharField(max_length=200)
    body = models.TextField(
        blank=True,
        help_text='Plain-text body. Rendered with newlines preserved.',
    )
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default='info',
        help_text='Visual treatment — info (blue), success (green), warning (yellow), danger (red).',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive announcements are hidden from the portal regardless of expiry.',
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='If set, announcement is hidden after this time. Leave blank for no expiry.',
    )
    is_dismissable = models.BooleanField(
        default=True,
        help_text='When true, portal users can hide the banner for themselves '
                  '(stored per-session). Critical announcements should set this to False.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='portal_announcements_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portal_announcements'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_active', '-created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title} ({self.organization.name})'

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @classmethod
    def active_for_org(cls, organization):
        """Visible announcements for `organization` right now."""
        now = timezone.now()
        return cls.objects.filter(
            organization=organization, is_active=True,
        ).exclude(expires_at__lte=now).order_by('-created_at')


class PortalStatusPhrase(models.Model):
    """
    Customer-facing progress phrase for an internal TicketStatus.

    Customers see one of five plain phrases instead of the MSP's internal
    status names. Defaults come from the status flags (see
    portal/progress.py); a row here overrides the default for one status.
    """
    PHRASE_RECEIVED = 'received'
    PHRASE_IN_PROGRESS = 'in_progress'
    PHRASE_WAITING_ON_CUSTOMER = 'waiting_on_customer'
    PHRASE_WAITING_APPROVAL = 'waiting_approval'
    PHRASE_RESOLVED = 'resolved'
    PHRASE_CHOICES = [
        (PHRASE_RECEIVED, 'Received'),
        (PHRASE_IN_PROGRESS, 'In progress'),
        (PHRASE_WAITING_ON_CUSTOMER, 'Waiting for you'),
        (PHRASE_WAITING_APPROVAL, 'Waiting for approval'),
        (PHRASE_RESOLVED, 'Resolved'),
    ]

    status = models.OneToOneField(
        'psa.TicketStatus', on_delete=models.CASCADE,
        related_name='portal_phrase',
    )
    phrase = models.CharField(max_length=30, choices=PHRASE_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portal_status_phrases'
        verbose_name = 'Portal status phrase'
        verbose_name_plural = 'Portal status phrases'

    def __str__(self):
        return f'{self.status} → {self.get_phrase_display()}'
