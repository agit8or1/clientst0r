"""
Per-customer, per-action overrides and second-person approvals for RMM work.

  RMMPermissionOverride  allow / deny / require approval, for one action
                         (or '*', deny and require-approval only), at one
                         customer (or every customer: deny and
                         require-approval only), for one technician, one
                         role template, or everyone.
                           - deny and require-approval narrow access and
                             apply at once;
                           - allow widens it, so it waits (pending) until a
                             different Platform Administrator approves it;
                             lifting a deny / require-approval also waits
                             for a second administrator.
  RMMApproval            one high-impact operation waiting for a second
                         person. Bound to requester, customer, action,
                         device and an operation digest; single use.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import catalog

APPROVAL_LIFETIME = timedelta(hours=24)


class OverrideQuerySet(models.QuerySet):
    def live(self, now=None):
        now = now or timezone.now()
        return self.filter(status=RMMPermissionOverride.ACTIVE).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now))


class RMMPermissionOverride(models.Model):
    ALLOW, DENY, REQUIRE_APPROVAL = 'allow', 'deny', 'require_approval'
    EFFECTS = [(ALLOW, 'Allow'), (DENY, 'Deny'), (REQUIRE_APPROVAL, 'Require approval')]
    PENDING, ACTIVE, REVOKED, REJECTED = 'pending', 'active', 'revoked', 'rejected'
    STATUSES = [(s, s.title()) for s in (PENDING, ACTIVE, REVOKED, REJECTED)]

    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='rmm_permission_overrides',
                                     help_text='Empty = every customer (deny / require approval only).')
    action = models.CharField(max_length=40, help_text="An RMM action key, or '*' (deny / require approval).")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='rmm_permission_overrides')
    role_template = models.ForeignKey('accounts.RoleTemplate', on_delete=models.CASCADE, null=True, blank=True,
                                      related_name='rmm_permission_overrides',
                                      help_text="Matches technicians whose global role is this template.")
    effect = models.CharField(max_length=20, choices=EFFECTS)
    approval_level = models.CharField(max_length=20, blank=True, default='',
                                      choices=[(k, k) for k in catalog.APPROVAL_LEVELS])
    reason = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Lifting a deny / require-approval widens access: it stays in force
    # until a different administrator confirms the lift.
    lift_requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                          blank=True, related_name='+')
    lift_requested_at = models.DateTimeField(null=True, blank=True)

    objects = OverrideQuerySet.as_manager()

    class Meta:
        db_table = 'rmm_permission_overrides'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=~(Q(user__isnull=False) & Q(role_template__isnull=False)),
                                   name='rmm_override_one_subject'),
        ]

    def __str__(self):
        return f'{self.get_effect_display()} {self.action} for {self.subject_label} at {self.where_label}'

    @property
    def subject_label(self):
        if self.user_id:
            return self.user.get_username()
        if self.role_template_id:
            return f'role {self.role_template.name}'
        return 'every technician'

    @property
    def where_label(self):
        return self.organization.name if self.organization_id else 'every customer'

    def matches(self, user, global_role_id) -> bool:
        if self.user_id:
            return self.user_id == user.pk
        if self.role_template_id:
            return self.role_template_id == global_role_id
        return True


class RMMApproval(models.Model):
    PENDING, APPROVED, REJECTED, CONSUMED, EXPIRED, CANCELLED = (
        'pending', 'approved', 'rejected', 'consumed', 'expired', 'cancelled')
    STATUSES = [(s, s.title()) for s in (PENDING, APPROVED, REJECTED, CONSUMED, EXPIRED, CANCELLED)]

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='rmm_approvals')
    action = models.CharField(max_length=40)
    device_key = models.CharField(max_length=80, blank=True, help_text='e.g. integrations.rmmdevice:12')
    device_label = models.CharField(max_length=255, blank=True)
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    digest = models.CharField(max_length=64, blank=True,
                              help_text="The caller's digest of the exact operation; approval binds to it.")
    summary = models.CharField(max_length=500, blank=True)
    approval_level = models.CharField(max_length=20, choices=[(k, k) for k in catalog.APPROVAL_LEVELS])
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'rmm_approvals'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['requester', 'organization', 'action', 'status'])]

    def __str__(self):
        return f'{self.action} by {self.requester} at {self.organization} ({self.status})'

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + APPROVAL_LIFETIME
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status == self.PENDING and self.expires_at > timezone.now()
