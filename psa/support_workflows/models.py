"""Support workflow definitions (data) and runs on tickets.

A run records, for one ticket and one alert: the evidence gathered (each
item with when it was observed and whether that is fresh), the likely
causes the rules found, the remediations offered (only Rem0te catalog
actions the paired Rem0te advertises), the proposal sent through the
existing fix-referral flow (psa_ai.RMMRequest — approval happens on
Rem0te's approval signer, never here), and how monitoring confirmed the
outcome. Staff only. Nothing here runs anything on a computer.
"""
import uuid

from django.conf import settings as django_settings
from django.db import models


class SupportWorkflowDefinition(models.Model):
    """An administrator's workflow: a customised built-in (same slug) or a new one."""
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    definition = models.JSONField(default=dict)
    updated_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'support_workflow_definitions'
        ordering = ['name']

    def __str__(self):
        return self.name


class WorkflowRun(models.Model):
    STATUS_CHOICES = [
        ('ready', 'Evidence gathered'),
        ('awaiting_approval', 'Waiting for approval in Rem0te'),
        ('approved', 'Approved in Rem0te'),
        ('running', 'Running'),
        ('manual', 'Manual steps in progress'),
        ('verifying', 'Waiting for monitoring to confirm'),
        ('verified', 'Confirmed by monitoring'),
        ('not_verified', 'Not confirmed by monitoring'),
        ('failed', 'Failed'),
        ('rejected', 'Rejected'),
        ('approval_expired', 'Approval expired'),
        ('unavailable', 'RMM unavailable'),
        ('cancelled', 'Cancelled'),
    ]
    OPEN = {'ready', 'awaiting_approval', 'approved', 'running', 'manual', 'verifying'}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    ticket = models.ForeignKey('psa.Ticket', on_delete=models.CASCADE, related_name='support_workflow_runs')
    alert_link = models.ForeignKey('ticket_routing.AlertTicketLink', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='workflow_runs')
    device = models.ForeignKey('integrations.RMMDevice', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='+')
    workflow_slug = models.SlugField(max_length=64)
    workflow_name = models.CharField(max_length=120)
    definition = models.JSONField(default=dict, help_text='The definition as it was when the run started.')
    actor = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ready')
    evidence = models.JSONField(default=list, blank=True)
    facts = models.JSONField(default=dict, blank=True)
    causes = models.JSONField(default=list, blank=True)
    remediations = models.JSONField(default=list, blank=True)
    diagnostics = models.JSONField(default=list, blank=True,
                                   help_text='Read-only diagnostics the RMM offers for this device.')
    rmm_request = models.ForeignKey('psa_ai.RMMRequest', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    chosen_action = models.CharField(max_length=64, blank=True)
    verify_by = models.DateTimeField(null=True, blank=True)
    outcome_note = models.TextField(blank=True)
    history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'support_workflow_runs'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['ticket', '-created_at']), models.Index(fields=['status', 'updated_at'])]

    def __str__(self):
        return f'{self.workflow_name} on {self.ticket_id} ({self.status})'

    @property
    def is_open(self):
        return self.status in self.OPEN
