"""
Audit models - Comprehensive audit logging
"""
from django.db import models
from django.contrib.auth.models import User
from core.models import Organization, BaseModel


class AuditLog(models.Model):
    """
    Audit log for all significant actions.
    Records who/what/when/where/how.
    """
    ACTION_TYPES = [
        ('create', 'Create'),
        ('read', 'Read'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('login_failed', 'Login Failed'),
        ('api_call', 'API Call'),
        ('sync', 'PSA Sync'),
        ('export', 'Export'),
        ('import', 'Import'),
    ]

    # Who
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    username = models.CharField(max_length=150, blank=True)  # Store username in case user is deleted

    # What
    action = models.CharField(max_length=50, choices=ACTION_TYPES)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    # Where
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    path = models.CharField(max_length=500, blank=True)

    # When
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # Additional context
    extra_data = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['organization', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
            models.Index(fields=['object_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.username} - {self.action} - {self.object_type}:{self.object_id} at {self.timestamp}"

    @classmethod
    def log(cls, user, action, organization=None, object_type='', object_id=None, object_repr='',
            description='', ip_address=None, user_agent='', path='', extra_data=None, success=True):
        """
        Helper method to create audit log entry.
        """
        return cls.objects.create(
            user=user,
            username=user.username if user else '',
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_repr=object_repr,
            description=description,
            organization=organization,
            ip_address=ip_address,
            user_agent=user_agent,
            path=path,
            extra_data=extra_data or {},
            success=success
        )
