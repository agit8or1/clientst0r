"""API access control: network rules for the API and inbound webhooks (Phase 81).

Rules add to authentication, permissions, rate limits and customer isolation;
they never grant access on their own. See docs/API_ACCESS_CONTROL.md for the
precedence and the recovery procedure.
"""
import ipaddress

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
from django.utils import timezone


SURFACE_API = 'api'
SURFACE_WEBHOOK = 'webhook'
SURFACES = ((SURFACE_API, 'Inbound API'), (SURFACE_WEBHOOK, 'Inbound webhooks'))


def normalize_network(value):
    """'10.0.0.5' -> '10.0.0.5/32'; '2001:db8::/48' -> canonical text.

    Host bits are dropped (strict=False) so '10.0.0.5/24' means 10.0.0.0/24.
    Raises ValidationError for anything that is not an address or a range.
    """
    text = (value or '').strip()
    if not text:
        raise ValidationError('Enter an IPv4 or IPv6 address or CIDR range.')
    try:
        return str(ipaddress.ip_network(text, strict=False))
    except ValueError:
        raise ValidationError(f'"{text[:64]}" is not an IPv4 or IPv6 address or CIDR range.')


class ApiAccessSettings(models.Model):
    """Singleton: the global mode for each surface and the policy version."""

    MODE_UNRESTRICTED = 'unrestricted'
    MODE_ALLOWLIST = 'allowlist'
    MODE_DENYLIST = 'denylist'
    MODE_COMBINED = 'combined'
    MODES = (
        (MODE_UNRESTRICTED, 'Unrestricted'),
        (MODE_ALLOWLIST, 'Allowlist only'),
        (MODE_DENYLIST, 'Denylist'),
        (MODE_COMBINED, 'Combined'),
    )
    MODE_HELP = (
        (MODE_UNRESTRICTED, 'Any source address; global rules are ignored (authentication still applies).'),
        (MODE_ALLOWLIST, 'Only addresses in the global allow rules; everything else is refused.'),
        (MODE_DENYLIST, 'Addresses in the global deny rules are refused.'),
        (MODE_COMBINED, 'Global allowlist, with deny rules as exceptions.'),
    )

    api_mode = models.CharField(max_length=20, choices=MODES, default=MODE_UNRESTRICTED)
    webhook_mode = models.CharField(max_length=20, choices=MODES, default=MODE_UNRESTRICTED)
    # Bumped on every rule or mode change: workers reload their cached rules,
    # and each logged decision records the version it was made under.
    policy_version = models.PositiveIntegerField(default=1)
    decision_retention_days = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'api_access_settings'
        verbose_name = 'API access settings'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def bump(cls, user=None):
        cls.get()
        fields = {'policy_version': F('policy_version') + 1, 'updated_at': timezone.now()}
        if user is not None and getattr(user, 'pk', None):
            fields['updated_by'] = user
        cls.objects.filter(pk=1).update(**fields)

    def mode_for(self, surface):
        return self.webhook_mode if surface == SURFACE_WEBHOOK else self.api_mode


class ApiAccessRule(models.Model):
    ACTION_ALLOW = 'allow'
    ACTION_DENY = 'deny'
    ACTIONS = ((ACTION_ALLOW, 'Allow'), (ACTION_DENY, 'Deny'))

    SURFACE_API = SURFACE_API
    SURFACE_WEBHOOK = SURFACE_WEBHOOK
    SURFACE_BOTH = 'both'
    RULE_SURFACES = SURFACES + ((SURFACE_BOTH, 'API and webhooks'),)

    SCOPE_GLOBAL = 'global'
    SCOPE_CUSTOMER = 'customer'
    SCOPE_API_KEY = 'api_key'
    SCOPE_INTEGRATION = 'integration'
    SCOPE_ENDPOINT_GROUP = 'endpoint_group'
    SCOPES = (
        (SCOPE_GLOBAL, 'Global'),
        (SCOPE_CUSTOMER, 'Customer'),
        (SCOPE_API_KEY, 'API key'),
        (SCOPE_INTEGRATION, 'Integration'),
        (SCOPE_ENDPOINT_GROUP, 'Endpoint group'),
    )

    name = models.CharField(max_length=120)
    network = models.CharField(max_length=64, help_text='IPv4 / IPv6 address or CIDR range')
    action = models.CharField(max_length=10, choices=ACTIONS, default=ACTION_ALLOW)
    surface = models.CharField(max_length=10, choices=RULE_SURFACES, default=SURFACE_API)
    scope = models.CharField(max_length=20, choices=SCOPES, default=SCOPE_GLOBAL)
    organization = models.ForeignKey('core.Organization', null=True, blank=True,
                                     on_delete=models.CASCADE, related_name='api_access_rules')
    api_key = models.ForeignKey('api.APIKey', null=True, blank=True,
                                on_delete=models.CASCADE, related_name='access_rules')
    # Integration or endpoint-group key from api_access.groups.
    target = models.CharField(max_length=40, blank=True, default='')
    description = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True,
                                      help_text='Temporary rule: stops applying at this time')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    match_count = models.PositiveBigIntegerField(default=0)
    last_matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'api_access_rules'
        ordering = ['scope', 'action', 'name']
        indexes = [models.Index(fields=['is_active', 'scope'])]

    def __str__(self):
        return f'{self.get_action_display()} {self.network} ({self.name})'

    def clean(self):
        self.network = normalize_network(self.network)
        from .groups import ENDPOINT_GROUPS, INTEGRATIONS
        need = {
            self.SCOPE_CUSTOMER: ('organization', self.organization_id),
            self.SCOPE_API_KEY: ('api_key', self.api_key_id),
        }
        if self.scope in need and not need[self.scope][1]:
            raise ValidationError({need[self.scope][0]: 'Required for this scope.'})
        if self.scope == self.SCOPE_INTEGRATION and self.target not in INTEGRATIONS:
            raise ValidationError({'target': 'Choose an integration.'})
        if self.scope == self.SCOPE_ENDPOINT_GROUP and self.target not in ENDPOINT_GROUPS:
            raise ValidationError({'target': 'Choose an endpoint group.'})
        # Keep only the field that belongs to the scope.
        if self.scope != self.SCOPE_CUSTOMER:
            self.organization = None
        if self.scope != self.SCOPE_API_KEY:
            self.api_key = None
        if self.scope not in (self.SCOPE_INTEGRATION, self.SCOPE_ENDPOINT_GROUP):
            self.target = ''

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def status(self):
        if not self.is_active:
            return 'disabled'
        return 'expired' if self.is_expired else 'active'

    def scope_label(self):
        from .groups import ENDPOINT_GROUPS, INTEGRATIONS
        if self.scope == self.SCOPE_CUSTOMER and self.organization_id:
            return f'Customer: {self.organization}'
        if self.scope == self.SCOPE_API_KEY and self.api_key_id:
            return f'API key: {self.api_key.name} ({self.api_key.key_prefix}…)'
        if self.scope == self.SCOPE_INTEGRATION:
            return f'Integration: {INTEGRATIONS.get(self.target, self.target)}'
        if self.scope == self.SCOPE_ENDPOINT_GROUP:
            return f'Endpoint group: {ENDPOINT_GROUPS.get(self.target, (self.target,))[0]}'
        return 'Global'


class ApiAccessDecision(models.Model):
    """A refused request. Repeats from the same source for the same reason
    within a minute are folded into one row (``count``), so a flood cannot
    flood the log. Never stores request bodies, headers or key secrets."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    count = models.PositiveIntegerField(default=1)
    source_ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    surface = models.CharField(max_length=10, choices=SURFACES)
    endpoint_group = models.CharField(max_length=40, blank=True, default='')
    integration = models.CharField(max_length=40, blank=True, default='')
    method = models.CharField(max_length=10, blank=True, default='')
    path = models.CharField(max_length=255, blank=True, default='')
    reason = models.CharField(max_length=40)
    detail = models.CharField(max_length=255, blank=True, default='')
    rule = models.ForeignKey(ApiAccessRule, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='decisions')
    rule_name = models.CharField(max_length=120, blank=True, default='')
    api_key = models.ForeignKey('api.APIKey', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    api_key_prefix = models.CharField(max_length=20, blank=True, default='')
    organization = models.ForeignKey('core.Organization', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    policy_version = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'api_access_decisions'
        ordering = ['-created_at']
