"""
Technician access: who may use ticket AI and RMM tools, at which customer.

  AccessPreset        a named capability map (catalog.OPTIONAL key → state).
                      L1/L2/L3 are built in and seeded idempotently; admins
                      clone them into custom presets.
  TechnicianGroup     a set of technicians, so one assignment covers many.
  AccessAssignment    preset × (technician or group) × one customer, with an
                      optional expiry. The capability and its scope live on
                      the same row: nothing combines one assignment's
                      capability with another's customer.
  CustomerAccessPolicy per customer: the default preset offered for new
                      assignments, and capabilities switched off there for
                      everyone (a customer restriction always wins).
  ExplicitDeny        a capability removed from one technician, everywhere or
                      at one customer. Always wins.
  ProtectedChange     a widening change waiting for a second administrator.
  ReadEvent / TheftAlert / Containment   read-only theft detection.

Without an assignment a technician has nothing here — new technicians
start at L1 only once someone assigns them a customer. Staff, editor and
admin flags never imply a preset.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import catalog


class AccessPreset(models.Model):
    key = models.SlugField(max_length=40, unique=True, null=True, blank=True,
                           help_text='Set on built-in presets only (l1, l2, l3).')
    name = models.CharField(max_length=100, unique=True)
    level = models.PositiveSmallIntegerField(default=1, help_text='1, 2 or 3; for ordering and reports.')
    description = models.TextField(blank=True)
    capabilities = models.JSONField(default=dict)
    builtin = models.BooleanField(default=False)
    based_on = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='clones')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tech_access_presets'
        ordering = ['level', 'name']

    def __str__(self):
        return self.name

    def caps(self) -> dict:
        return catalog.clean_capabilities(self.capabilities)

    def builtin_caps(self) -> dict | None:
        """The shipped capability map for a built-in preset (for reset)."""
        for key, _name, _level, _desc, caps in catalog.BUILTIN_PRESETS:
            if key == self.key:
                return dict(caps)
        return None


class TechnicianGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='technician_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tech_access_groups'
        ordering = ['name']

    def __str__(self):
        return self.name


class AccessAssignmentQuerySet(models.QuerySet):
    def live(self, now=None):
        now = now or timezone.now()
        return self.filter(revoked_at__isnull=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


class AccessAssignment(models.Model):
    preset = models.ForeignKey(AccessPreset, on_delete=models.PROTECT, related_name='assignments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='tech_access_assignments')
    group = models.ForeignKey(TechnicianGroup, on_delete=models.CASCADE, null=True, blank=True,
                              related_name='assignments')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='tech_access_assignments')
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # The protected change that created this assignment (when
    # it widened access) and who revoked it. Older rows are matched to their
    # change by payload in tech_access.explain.
    approved_change = models.ForeignKey('ProtectedChange', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+')
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')

    objects = AccessAssignmentQuerySet.as_manager()

    class Meta:
        db_table = 'tech_access_assignments'
        ordering = ['organization__name', 'pk']
        constraints = [
            models.CheckConstraint(
                condition=(Q(user__isnull=False, group__isnull=True) | Q(user__isnull=True, group__isnull=False)),
                name='tech_access_assignment_one_subject'),
        ]

    def __str__(self):
        who = self.user.username if self.user_id else f'group {self.group.name}'
        return f'{who} → {self.preset.name} at {self.organization.name}'

    @property
    def subject_label(self):
        return self.user.get_username() if self.user_id else f'Group: {self.group.name}'

    def status(self, now=None) -> str:
        """'revoked', 'expired' or 'active'."""
        now = now or timezone.now()
        if self.revoked_at:
            return 'revoked'
        if self.expires_at and self.expires_at <= now:
            return 'expired'
        return 'active'


class CustomerAccessPolicy(models.Model):
    organization = models.OneToOneField('core.Organization', on_delete=models.CASCADE,
                                        related_name='tech_access_policy')
    default_preset = models.ForeignKey(AccessPreset, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+',
                                       help_text='Offered first when assigning a technician to this customer.')
    restricted = models.JSONField(default=list, blank=True,
                                  help_text='Capabilities switched off at this customer for every technician.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tech_access_customer_policies'


class ExplicitDeny(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tech_access_denies')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='+', help_text='Empty = at every customer.')
    capability = models.CharField(max_length=40, help_text="A catalog key, or '*' for everything.")
    reason = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tech_access_denies'


class ProtectedChange(models.Model):
    """A widening change to a protected setting. It takes effect only when a
    different administrator approves it after re-authenticating."""
    KINDS = [
        ('assignment', 'Technician access assignment'),
        ('preset', 'Preset capabilities'),
        ('group_members', 'Group membership'),
        ('business_mapping', 'RMM business mapping'),
        ('approvers', 'Approvers'),
        ('recovery_contact', 'Recovery contact'),
        ('provider_destination', 'AI provider destination'),
        ('security_limits', 'Security limits'),
        ('account_email', 'Account e-mail address'),
        ('superuser_grant', 'Superuser grant'),
        ('superuser_policy', 'Superuser-grant approval policy'),
        ('global_role', 'Global role with an RMM tier'),
        ('rmm_tier', 'Role template RMM tier'),
    ]
    PENDING, APPLIED, REJECTED, CANCELLED, EXPIRED = 'pending', 'applied', 'rejected', 'cancelled', 'expired'
    STATUSES = [(s, s.title()) for s in (PENDING, APPLIED, REJECTED, CANCELLED, EXPIRED)]

    kind = models.CharField(max_length=30, choices=KINDS)
    summary = models.CharField(max_length=300)
    payload = models.JSONField(default=dict)
    widening = models.JSONField(default=list, blank=True, help_text='What it grants beyond the current state.')
    affected_users = models.JSONField(default=list, blank=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', help_text='The technician whose access widens, if one.')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name='+')
    requested_at = models.DateTimeField(auto_now_add=True)
    requester_reauth_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_reauth_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default=PENDING)
    notified = models.JSONField(default=list, blank=True, help_text='Verified contacts told about this change.')
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'tech_access_protected_changes'
        ordering = ['-requested_at']


# --- read-only theft detection -------------------------------------------

class ReadEvent(models.Model):
    """One distinct thing an identity read in one hour. Unique per
    (user, kind, key, hour), so counting rows counts distinct items."""
    KINDS = [('ticket', 'Ticket'), ('customer', 'Customer'), ('export', 'Export'),
             ('diagnostic_bytes', 'Diagnostic bytes')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    kind = models.CharField(max_length=20, choices=KINDS)
    key = models.CharField(max_length=64)
    organization_id = models.IntegerField(null=True)
    channel = models.CharField(max_length=10, default='ui')  # ui / api / mobile
    hour = models.DateTimeField()
    amount = models.BigIntegerField(default=0)  # bytes, for diagnostic_bytes

    class Meta:
        db_table = 'tech_access_read_events'
        constraints = [models.UniqueConstraint(fields=['user', 'kind', 'key', 'hour'],
                                               name='tech_access_read_event_unique')]
        indexes = [models.Index(fields=['user', 'kind', 'hour'])]


class DetectionSettings(models.Model):
    """Singleton (pk=1). Enabled by default with the catalog thresholds."""
    enabled = models.BooleanField(default=True)
    thresholds = models.JSONField(default=dict, blank=True)
    recipients = models.TextField(blank=True, help_text='Extra alert e-mail addresses, one per line.')
    notify_customers = models.BooleanField(default=False,
                                           help_text='Also send each affected customer a short report.')
    containment = models.JSONField(default=dict, blank=True,
                                   help_text='Per level (1/2/3): "alert" or "contain".')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tech_access_detection_settings'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TheftAlert(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    rule = models.CharField(max_length=40)
    window = models.CharField(max_length=10)
    observed = models.BigIntegerField()
    threshold = models.BigIntegerField()
    organizations = models.JSONField(default=list, blank=True)
    contained = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                        blank=True, related_name='+')
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'tech_access_theft_alerts'
        ordering = ['-created_at']


class Containment(models.Model):
    """While active, the technician's optional capabilities are all off and
    ticket/customer/export reads beyond their own assigned tickets are
    refused. Lifted by an administrator."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    alert = models.ForeignKey(TheftAlert, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reason = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='+')

    class Meta:
        db_table = 'tech_access_containments'


class ProtectionSettings(models.Model):
    """Singleton (pk=1): who may review protected changes and where they are
    announced. Changing either is itself a protected change."""
    approvers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+',
                                       help_text='Empty = every active superuser.')
    recovery_email = models.EmailField(blank=True,
                                       help_text='Verified security contact told about every protected change.')
    recovery_verified_at = models.DateTimeField(null=True, blank=True)
    superuser_grant_requires_approval = models.BooleanField(
        default=False,
        help_text='Granting superuser takes a second administrator\'s approval. Turning this off is '
                  'itself a protected change.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tech_access_protection_settings'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
