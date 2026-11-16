"""Customer health score (Phase 78): configuration and nightly snapshots.

The score itself is not stored as a model: `health_score.scoring` computes it
from the signal providers (`health_score.registry`). A snapshot keeps the
result of one computation so a later one can explain what changed.
"""
from django.db import models
from django.utils import timezone

from . import registry

DEFAULT_OK_AT = 75
DEFAULT_WARN_AT = 50


class HealthScoreConfig(models.Model):
    """Weights and thresholds. One row with no organization is the install
    default; a row for a client organization overrides it for that client."""
    organization = models.OneToOneField(
        'core.Organization', null=True, blank=True, on_delete=models.CASCADE,
        related_name='health_score_config',
        help_text='Empty = the default for every client without its own configuration.')
    dimension_weights = models.JSONField(default=dict, blank=True,
                                         help_text='Dimension key -> weight (0 turns a dimension off).')
    signal_weights = models.JSONField(default=dict, blank=True,
                                      help_text='Signal key -> weight inside its dimension (0 turns it off).')
    ok_threshold = models.PositiveSmallIntegerField(default=DEFAULT_OK_AT,
                                                    help_text='A value at or above this is healthy.')
    warn_threshold = models.PositiveSmallIntegerField(default=DEFAULT_WARN_AT,
                                                      help_text='At or above this (and below healthy): needs attention. Below: critical.')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')

    class Meta:
        verbose_name = 'health score configuration'

    def __str__(self):
        return f'Health score configuration ({self.organization or "default"})'

    def dimension_weight(self, key):
        return _weight(self.dimension_weights, key, registry.DEFAULT_DIMENSION_WEIGHTS.get(key, 1))

    def signal_weight(self, key):
        return _weight(self.signal_weights, key, registry.default_signal_weight(key))

    def status_for(self, value):
        if value is None:
            return 'unknown'
        if value >= self.ok_threshold:
            return 'ok'
        if value >= self.warn_threshold:
            return 'warn'
        return 'critical'

    @classmethod
    def for_client(cls, client):
        """The configuration that applies to `client`: its own, else the default
        (an unsaved one with the built-in weights when nobody saved either)."""
        own = cls.objects.filter(organization=client).first()
        if own:
            return own
        return cls.objects.filter(organization__isnull=True).first() or cls()


def _weight(mapping, key, default):
    try:
        value = float((mapping or {}).get(key, default))
    except (TypeError, ValueError):
        return float(default)
    return max(value, 0.0)


class CustomerHealthSnapshot(models.Model):
    """One client's computed health on one day."""
    client = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='health_snapshots')
    date = models.DateField(default=timezone.localdate)
    computed_at = models.DateTimeField(default=timezone.now)
    overall = models.FloatField(null=True, blank=True,
                                help_text='Weighted over the dimensions with known data only; null when none is known.')
    status = models.CharField(max_length=10, default='unknown')
    known_dimensions = models.PositiveSmallIntegerField(default=0)
    total_dimensions = models.PositiveSmallIntegerField(default=0)
    dimensions = models.JSONField(default=dict, blank=True,
                                  help_text='Per dimension: value, status, weight and every signal with its contributing records.')

    class Meta:
        ordering = ['-date', '-computed_at']
        constraints = [models.UniqueConstraint(fields=['client', 'date'], name='health_snapshot_client_date')]
        indexes = [models.Index(fields=['client', '-date'])]

    def __str__(self):
        return f'{self.client_id} {self.date}: {self.overall}'

    @property
    def coverage_pct(self):
        if not self.total_dimensions:
            return 0
        return round(100 * self.known_dimensions / self.total_dimensions)
