"""Pulse checks: periodic service-feedback surveys sent by the MSP to people
at its client organizations.

Distinct from the per-ticket CSAT survey (psa.TicketCSATSurvey): a pulse
check asks about the relationship as a whole, goes to an audience chosen by
organization and role, and can repeat monthly or quarterly.

  PulseCheck    the template staff manage: intro, questions, audience, schedule
  PulseQuestion one question of a template (1-5 rating, NPS 0-10, yes/no, text)
  PulseSend     one round of a check; questions are copied onto it, so editing
                the template later never changes what a past round asked
  PulseResponse one recipient of one round, with a single-use link token
  PulseOptOut   an e-mail address that asked not to get pulse checks
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings as django_settings
from django.db import models
from django.utils import timezone


class PulseCheck(models.Model):
    SCHEDULE_NONE, SCHEDULE_MONTHLY, SCHEDULE_QUARTERLY = 'none', 'monthly', 'quarterly'
    SCHEDULE_CHOICES = [
        (SCHEDULE_NONE, 'Not repeated (send by hand)'),
        (SCHEDULE_MONTHLY, 'Monthly'),
        (SCHEDULE_QUARTERLY, 'Quarterly'),
    ]

    AUDIENCE_ALL, AUDIENCE_ROLES, AUDIENCE_SPECIFIC = 'all', 'roles', 'specific'
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, 'Everyone with a portal account at the organization'),
        (AUDIENCE_ROLES, 'Only people with the roles below'),
        (AUDIENCE_SPECIFIC, 'Only the people chosen below'),
    ]

    # Role groups for AUDIENCE_ROLES (see pulse.audience.membership_matches).
    ROLE_OWNERS, ROLE_ADMINS, ROLE_EDITORS, ROLE_READONLY = 'owners', 'admins', 'editors', 'readonly'
    ROLE_GROUP_CHOICES = [
        (ROLE_OWNERS, 'Owners'),
        (ROLE_ADMINS, 'Managers / administrators'),
        (ROLE_EDITORS, 'Editors'),
        (ROLE_READONLY, 'Read-only users'),
    ]

    name = models.CharField(max_length=200)
    intro = models.TextField(blank=True, help_text='Shown above the questions and in the e-mail.')
    is_active = models.BooleanField(default=True)

    schedule = models.CharField(max_length=20, choices=SCHEDULE_CHOICES, default=SCHEDULE_NONE)
    send_day = models.PositiveSmallIntegerField(
        default=1, help_text='Day of the month (1-28) a repeated check is sent; quarterly checks '
                             'go out in the first month of each quarter.')
    starts_on = models.DateField(default=timezone.localdate,
                                 help_text='Repeated sends start on or after this date.')
    response_days = models.PositiveSmallIntegerField(
        default=14, help_text='How many days the link in each send stays open.')

    all_organizations = models.BooleanField(
        default=False, help_text='Every active client (internal and subcontractor organizations are left out).')
    organizations = models.ManyToManyField('core.Organization', blank=True, related_name='pulse_checks')

    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    audience_roles = models.JSONField(default=list, blank=True,
                                      help_text='Role groups for the "roles" audience.')
    audience_role_templates = models.ManyToManyField(
        'accounts.RoleTemplate', blank=True, related_name='pulse_checks',
        help_text='Named roles for the "roles" audience (primary or additional role).')
    include_contacts = models.BooleanField(
        default=False, help_text='Everyone audience: also send to the organization\'s contacts '
                                 'that have an e-mail address.')
    specific_users = models.ManyToManyField(django_settings.AUTH_USER_MODEL, blank=True,
                                            related_name='pulse_checks_chosen')
    specific_contacts = models.ManyToManyField('assets.Contact', blank=True,
                                               related_name='pulse_checks_chosen')

    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='pulse_checks_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pulse_checks'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_recurring(self):
        return self.schedule in (self.SCHEDULE_MONTHLY, self.SCHEDULE_QUARTERLY)

    def period_key(self, day):
        """The schedule period `day` falls in ('2026-11', '2026-Q4'), or None."""
        if self.schedule == self.SCHEDULE_MONTHLY:
            return f'{day.year:04d}-{day.month:02d}'
        if self.schedule == self.SCHEDULE_QUARTERLY:
            return f'{day.year:04d}-Q{(day.month - 1) // 3 + 1}'
        return None

    def is_due(self, day):
        """Whether a scheduled send belongs on `day` (ignoring whether this
        period was already sent: PulseSend's unique period key covers that)."""
        if not (self.is_active and self.is_recurring) or day < self.starts_on:
            return False
        if day.day < max(1, min(self.send_day or 1, 28)):
            return False
        if self.schedule == self.SCHEDULE_QUARTERLY and (day.month - 1) % 3 != 0:
            return False
        return True

    def question_snapshot(self):
        return [{'id': q.pk, 'kind': q.kind, 'text': q.text, 'required': q.required}
                for q in self.questions.all()]


class PulseQuestion(models.Model):
    KIND_RATING, KIND_NPS, KIND_YES_NO, KIND_TEXT = 'rating', 'nps', 'yes_no', 'text'
    KIND_CHOICES = [
        (KIND_RATING, 'Rating 1-5'),
        (KIND_NPS, 'Likelihood to recommend 0-10'),
        (KIND_YES_NO, 'Yes / no'),
        (KIND_TEXT, 'Free text'),
    ]

    pulse_check = models.ForeignKey(PulseCheck, on_delete=models.CASCADE, related_name='questions')
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_RATING)
    text = models.CharField(max_length=500)
    required = models.BooleanField(default=True)

    class Meta:
        db_table = 'pulse_questions'
        ordering = ['order', 'pk']

    def __str__(self):
        return self.text


class PulseSend(models.Model):
    TRIGGER_MANUAL, TRIGGER_SCHEDULE = 'manual', 'schedule'
    TRIGGER_CHOICES = [(TRIGGER_MANUAL, 'Sent by hand'), (TRIGGER_SCHEDULE, 'Scheduled')]

    pulse_check = models.ForeignKey(PulseCheck, on_delete=models.CASCADE, related_name='sends')
    trigger = models.CharField(max_length=10, choices=TRIGGER_CHOICES, default=TRIGGER_MANUAL)
    # Scheduled sends carry their period ('2026-11', '2026-Q4'); the unique
    # constraint makes a second scheduler run in the same period a no-op.
    # Manual sends leave it null (NULLs never collide).
    period_key = models.CharField(max_length=10, null=True, blank=True)
    questions = models.JSONField(default=list)
    intro = models.TextField(blank=True)
    sent_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='pulse_sends')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    recipient_count = models.PositiveIntegerField(default=0)
    emailed_count = models.PositiveIntegerField(default=0)
    opted_out_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pulse_sends'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['pulse_check', 'period_key'], name='pulse_send_one_per_period'),
        ]

    def __str__(self):
        return f'{self.pulse_check.name} — {self.created_at:%Y-%m-%d}'

    @property
    def is_open(self):
        return timezone.now() < self.expires_at


class PulseResponse(models.Model):
    EMAIL_SENT, EMAIL_FAILED, EMAIL_NOT_SENT = 'sent', 'failed', 'not_sent'
    EMAIL_CHOICES = [
        (EMAIL_SENT, 'E-mailed'),
        (EMAIL_FAILED, 'E-mail failed'),
        (EMAIL_NOT_SENT, 'Not e-mailed (no outgoing e-mail)'),
    ]
    VIA_LINK, VIA_PORTAL = 'link', 'portal'

    send = models.ForeignKey(PulseSend, on_delete=models.CASCADE, related_name='responses')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='pulse_responses')
    user = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                             null=True, blank=True, related_name='pulse_responses')
    contact = models.ForeignKey('assets.Contact', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='pulse_responses')
    email = models.EmailField()
    name = models.CharField(max_length=255, blank=True)
    # HMAC of the link token; the raw token is only ever in the e-mail.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    email_status = models.CharField(max_length=10, choices=EMAIL_CHOICES, default=EMAIL_NOT_SENT)
    created_at = models.DateTimeField(auto_now_add=True)
    answers = models.JSONField(default=dict, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_via = models.CharField(max_length=10, blank=True)
    responded_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'pulse_responses'
        ordering = ['organization__name', 'email']
        constraints = [
            models.UniqueConstraint(fields=['send', 'organization', 'email'],
                                    name='pulse_response_one_per_recipient'),
        ]
        indexes = [
            models.Index(fields=['organization', 'responded_at']),
            models.Index(fields=['user', 'responded_at']),
        ]

    def __str__(self):
        return f'{self.email} @ {self.organization_id} ({"answered" if self.responded_at else "open"})'

    TOKEN_PURPOSE = 'pulse.response'

    @classmethod
    def hash_response_token(cls, raw: str) -> str:
        from vault.secret_fields import hash_token
        return hash_token(raw, cls.TOKEN_PURPOSE)

    @classmethod
    def lookup(cls, raw: str):
        if not raw or len(raw) > 128:
            return None
        return (cls.objects.select_related('send', 'send__pulse_check', 'organization')
                .filter(token_hash=cls.hash_response_token(raw)).first())

    def issue_token(self) -> str:
        raw = secrets.token_urlsafe(32)
        self.token_hash = self.hash_response_token(raw)
        self.raw_token = raw
        return raw

    def save(self, *args, **kwargs):
        if not self.token_hash:
            self.issue_token()
        super().save(*args, **kwargs)

    @property
    def is_answered(self):
        return self.responded_at is not None

    @property
    def is_expired(self):
        return timezone.now() >= self.send.expires_at


class PulseOptOut(models.Model):
    """An address that asked not to receive pulse checks. Checked at send
    time; staff can see the list but opting back in is the person's call
    (portal Feedback page)."""
    email = models.EmailField(unique=True)
    via = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pulse_opt_outs'
        ordering = ['email']

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().lower()
        super().save(*args, **kwargs)

    @classmethod
    def is_opted_out(cls, email):
        return bool(email) and cls.objects.filter(email=email.strip().lower()).exists()

    @classmethod
    def opt_out(cls, email, via=''):
        email = (email or '').strip().lower()
        if not email:
            return None
        row, _ = cls.objects.get_or_create(email=email, defaults={'via': via})
        return row

    @classmethod
    def opt_in(cls, email):
        cls.objects.filter(email=(email or '').strip().lower()).delete()


def default_expiry(check, now=None):
    return (now or timezone.now()) + timedelta(days=max(1, check.response_days or 14))
