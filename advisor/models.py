"""
Profitability and Pricing Advisor (Phase 76).

The advisor reads contracts, time, invoices and costs, computes per-customer
facts (advisor.facts), runs rule-based detectors over them (advisor.detectors)
and stores what they find:

  Finding         one per customer + detector + period while open, updated in
                  place by the nightly run (`manage.py run_advisor`);
  Recommendation  0..n per finding, with deterministic numbers and the full
                  calculation ("show your work"). Accepting one creates a DRAFT
                  quote or contract amendment; nothing active is ever changed;
  Narrative       the optional AI explanation (OPTIONAL AI), cached per
                  finding version and only kept when every figure in it was
                  found in the facts it was given;
  AdvisorSettings thresholds, install-wide (organization empty) or per customer.

Every figure here is an operational estimate, not an accounting P&L.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings as django_settings
from django.db import models
from django.utils import timezone


class AdvisorSettings(models.Model):
    """Detector thresholds. The row with no organization is the install-wide
    default; a customer's own row (or its parent's) overrides it."""

    organization = models.OneToOneField(
        'core.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='advisor_settings',
        help_text='Customer these thresholds apply to. Empty = install-wide default.',
    )
    lookback_months = models.PositiveSmallIntegerField(
        default=3, choices=[(3, '3 months'), (6, '6 months'), (12, '12 months')],
        help_text='Trailing window the detectors evaluate (full calendar months).')
    target_margin_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('35'),
        help_text='Gross margin the advisor prices towards (percent of revenue).')
    loss_margin_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0'),
        help_text='A customer whose gross margin is below this is loss-making.')
    margin_decline_pts = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('10'),
        help_text='Drop in margin (percentage points) versus the prior period that raises a finding.')
    overage_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('20'),
        help_text='Support hours above the included hours by this percent count as over contract.')
    overage_months = models.PositiveSmallIntegerField(
        default=2, help_text='Months over contract (within the window) before a finding is raised.')
    unused_allowance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('40'),
        help_text='Average use of included hours below this percent counts as unused allowance.')
    unbilled_min_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('100'),
        help_text='Unbilled billable work worth at least this much raises a finding.')
    unbilled_stale_days = models.PositiveSmallIntegerField(
        default=14, help_text='Billable time younger than this is not yet counted as unbilled.')
    leakage_min_hours = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('2'),
        help_text='Hours of billable work with no contract or charge that raise a finding.')
    renewal_min_days = models.PositiveSmallIntegerField(default=60)
    renewal_max_days = models.PositiveSmallIntegerField(default=90)
    cost_increase_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('5'),
        help_text='Unit cost increase (percent) that must be matched by a price change.')
    tier_fit_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('120'),
        help_text='Consumption at this percent of a plan\'s included hours suggests a higher plan.')
    after_hours_share_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('20'),
        help_text='Share of hours worked outside business hours that suggests an after-hours rate.')
    business_hours_start = models.PositiveSmallIntegerField(default=8)
    business_hours_end = models.PositiveSmallIntegerField(default=18)
    disabled_detectors = models.JSONField(default=list, blank=True,
                                          help_text='Detector keys not run for this scope.')
    updated_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    THRESHOLD_FIELDS = (
        'lookback_months', 'target_margin_pct', 'loss_margin_pct', 'margin_decline_pts', 'overage_pct',
        'overage_months', 'unused_allowance_pct', 'unbilled_min_amount', 'unbilled_stale_days',
        'leakage_min_hours', 'renewal_min_days', 'renewal_max_days', 'cost_increase_pct', 'tier_fit_pct',
        'after_hours_share_pct', 'business_hours_start', 'business_hours_end',
    )

    class Meta:
        db_table = 'advisor_settings'
        verbose_name = 'advisor settings'
        verbose_name_plural = 'advisor settings'

    def __str__(self):
        return f'Advisor settings ({self.organization or "install default"})'

    @classmethod
    def install_default(cls):
        row = cls.objects.filter(organization__isnull=True).first()
        return row if row is not None else cls()

    @classmethod
    def for_client(cls, org):
        """The customer's own row, else the nearest parent's, else the
        install default (unsaved defaults when there is none)."""
        node, seen = org, set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            row = cls.objects.filter(organization_id=node.pk).first()
            if row is not None:
                return row
            node = getattr(node, 'parent', None)
        return cls.install_default()

    def thresholds(self):
        return {f: getattr(self, f) for f in self.THRESHOLD_FIELDS}


class Finding(models.Model):
    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('info', 'Information'),
    ]
    SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('resolved', 'Resolved (no longer detected)'),
        ('superseded', 'Superseded by a later period'),
    ]
    ASSESSMENT_CHOICES = [
        ('raised', 'Raised'),
        ('incomplete', 'Could not be evaluated: missing inputs'),
    ]

    client_org = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                   related_name='advisor_findings')
    detector = models.CharField(max_length=60, db_index=True)
    period_key = models.CharField(max_length=40, help_text='e.g. "3m:2026-10" (window and last month).')
    period_start = models.DateField()
    period_end = models.DateField()
    subject_key = models.CharField(max_length=60, blank=True, default='',
                                   help_text='Narrows the finding to one record, e.g. "contract:12".')
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='medium')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='open', db_index=True)
    assessment = models.CharField(max_length=12, choices=ASSESSMENT_CHOICES, default='raised')
    title = models.CharField(max_length=300)
    summary = models.TextField(help_text='Deterministic plain-language summary.')
    is_complete = models.BooleanField(default=True)
    missing_inputs = models.JSONField(default=list, blank=True)
    facts = models.JSONField(default=dict, blank=True,
                             help_text='The facts the detector used, with sources.')
    evidence = models.JSONField(default=dict, blank=True,
                                help_text='Detector-specific figures and the thresholds applied.')
    facts_hash = models.CharField(max_length=64, blank=True, default='')
    version = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_evaluated_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'advisor_findings'
        ordering = ['-last_evaluated_at']
        indexes = [
            models.Index(fields=['client_org', 'status']),
            models.Index(fields=['status', 'severity']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['client_org', 'detector', 'period_key', 'subject_key'],
                condition=models.Q(status='open'),
                name='advisor_one_open_finding_per_period',
            ),
        ]

    def __str__(self):
        return f'{self.get_detector_label()}: {self.client_org} ({self.period_key})'

    def get_detector_label(self):
        from .detectors import REGISTRY
        d = REGISTRY.get(self.detector)
        return d.label if d else self.detector

    @property
    def severity_rank(self):
        return self.SEVERITY_ORDER.get(self.severity, 9)


class Recommendation(models.Model):
    TYPE_CHOICES = [
        ('price_increase', 'Price increase'),
        ('renegotiate', 'Renegotiate'),
        ('after_hours_rate', 'After-hours rate'),
        ('per_device_price', 'Per-device price'),
        ('bundle_review', 'Bundle review'),
        ('upsell', 'Upsell'),
        ('tier_change', 'Tier change'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('accepted', 'Accepted (draft created)'),
        ('dismissed', 'Dismissed'),
        ('implemented', 'Implemented'),
    ]

    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name='recommendations')
    key = models.CharField(max_length=80, help_text='Stable within the finding, e.g. "price_increase:contract:12".')
    rec_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=300)
    rationale = models.TextField(blank=True)
    contract = models.ForeignKey('psa.Contract', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='advisor_recommendations',
                                 help_text='The contract this recommendation is about (never modified).')
    proposed = models.JSONField(default=dict, blank=True,
                                help_text='Proposed numbers: current, proposed, change, unit.')
    work = models.JSONField(default=dict, blank=True,
                            help_text='Show your work: formula, inputs (values + record links), '
                                      'assumptions, unknowns.')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='open', db_index=True)
    dismiss_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    draft_quote = models.ForeignKey('psa.Quote', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    draft_contract = models.ForeignKey('psa.Contract', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    implemented_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'advisor_recommendations'
        ordering = ['pk']
        constraints = [
            models.UniqueConstraint(fields=['finding', 'key'], name='advisor_recommendation_key_once'),
        ]

    def __str__(self):
        return f'{self.get_rec_type_display()}: {self.title}'

    @property
    def is_actionable(self):
        return self.status == 'open'


class Narrative(models.Model):
    """OPTIONAL AI explanation of one version of a finding."""
    STATUS_CHOICES = [
        ('accepted', 'Accepted (every figure verified)'),
        ('rejected', 'Rejected (contained a figure not in the facts)'),
    ]

    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name='narratives')
    finding_version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    text = models.TextField(blank=True, help_text='Kept only when accepted.')
    rejected_figures = models.JSONField(default=list, blank=True)
    model_label = models.CharField(max_length=100, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'advisor_narratives'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['finding', 'finding_version'],
                                    name='advisor_one_narrative_per_version'),
        ]

    def __str__(self):
        return f'Narrative for finding {self.finding_id} v{self.finding_version} ({self.status})'


class AdvisorRun(models.Model):
    """One run of the detectors: what was evaluated and what was not."""
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    customers = models.PositiveIntegerField(default=0)
    raised = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    resolved = models.PositiveIntegerField(default=0)
    coverage = models.JSONField(default=dict, blank=True,
                                help_text='Detector key -> {"evaluated": bool, "reason": str}.')
    error = models.TextField(blank=True)

    class Meta:
        db_table = 'advisor_runs'
        ordering = ['-started_at']

    def __str__(self):
        return f'Advisor run {self.started_at:%Y-%m-%d %H:%M}'
