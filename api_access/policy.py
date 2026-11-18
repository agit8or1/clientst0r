"""The API access policy: one decision function for every API and webhook request.

Precedence (docs/API_ACCESS_CONTROL.md):

1. An explicit deny rule that applies to the request always wins.
2. Every scope level that has at least one applicable allow rule is an
   allowlist: the source address must match one of that level's rules.
   Levels: global, customer, integration, endpoint group, API key.
3. Otherwise the request goes on to normal authentication and permissions.

Global rules follow the surface's mode: allow rules count in Allowlist and
Combined, deny rules in Denylist and Combined; Unrestricted ignores global
rules. Scoped rules always apply while they are active and unexpired.

An allowlist mode with no global allow rules refuses everything (default
deny). A source address that cannot be read, or a policy that cannot be
evaluated, is refused whenever any restriction applies (fail closed).
Private addresses get no special treatment.

Evaluation runs in two stages with disjoint scopes, so the combined result
is the same as one evaluation over all scopes:

* network stage (middleware, before authentication): global, integration
  and endpoint-group rules;
* credential stage (API key authentication): customer and API-key rules.
"""
import ipaddress
import logging
import threading
import time
from dataclasses import dataclass, field

from django.db import DatabaseError
from django.utils import timezone

from .models import ApiAccessRule as R, ApiAccessSettings as S, SURFACE_WEBHOOK

logger = logging.getLogger('api_access')

STAGE_NETWORK = frozenset({R.SCOPE_GLOBAL, R.SCOPE_INTEGRATION, R.SCOPE_ENDPOINT_GROUP})
STAGE_CREDENTIAL = frozenset({R.SCOPE_CUSTOMER, R.SCOPE_API_KEY})
ALL_SCOPES = STAGE_NETWORK | STAGE_CREDENTIAL

# Reasons recorded with a refusal.
DENY_RULE = 'deny_rule'
NOT_ALLOWLISTED = 'not_in_allowlist'
ALLOWLIST_EMPTY = 'allowlist_empty'
NO_ADDRESS = 'no_source_address'
POLICY_ERROR = 'policy_error'
POLICY_UNAVAILABLE = 'policy_unavailable'
RATE_LIMITED = 'rate_limited'
TOO_LARGE = 'body_too_large'
REASONS = {
    DENY_RULE: 'Matched a deny rule',
    NOT_ALLOWLISTED: 'Not in the allowlist',
    ALLOWLIST_EMPTY: 'Allowlist mode with no allow rules',
    NO_ADDRESS: 'Source address could not be read',
    POLICY_ERROR: 'Policy could not be evaluated',
    POLICY_UNAVAILABLE: 'Policy could not be loaded',
    RATE_LIMITED: 'Too many requests from this address',
    TOO_LARGE: 'Request body too large',
}

_SCOPE_ORDER = (R.SCOPE_GLOBAL, R.SCOPE_CUSTOMER, R.SCOPE_INTEGRATION,
                R.SCOPE_ENDPOINT_GROUP, R.SCOPE_API_KEY)


@dataclass(frozen=True)
class CompiledRule:
    id: int
    name: str
    action: str
    surfaces: frozenset
    scope: str
    organization_id: int
    api_key_id: int
    target: str
    network: object
    expires_at: object

    def applies_to(self, ctx):
        if ctx.surface not in self.surfaces:
            return False
        if self.scope == R.SCOPE_GLOBAL:
            return True
        if self.scope == R.SCOPE_CUSTOMER:
            return ctx.organization_id is not None and ctx.organization_id == self.organization_id
        if self.scope == R.SCOPE_API_KEY:
            return ctx.api_key_id is not None and ctx.api_key_id == self.api_key_id
        if self.scope == R.SCOPE_INTEGRATION:
            return bool(ctx.integration) and ctx.integration == self.target
        if self.scope == R.SCOPE_ENDPOINT_GROUP:
            return ctx.group == self.target
        return False

    def contains(self, ip):
        return ip is not None and ip.version == self.network.version and ip in self.network


@dataclass(frozen=True)
class Policy:
    version: int
    api_mode: str
    webhook_mode: str
    rules: tuple
    # (per-address requests per minute, max body KB) per surface; 0 = off
    api_limits: tuple = (0, 0)
    webhook_limits: tuple = (0, 0)

    def mode_for(self, surface):
        return self.webhook_mode if surface == SURFACE_WEBHOOK else self.api_mode

    def limits_for(self, surface):
        return self.webhook_limits if surface == SURFACE_WEBHOOK else self.api_limits


@dataclass
class Context:
    ip: object                    # ipaddress object or None
    surface: str
    group: str = ''
    integration: str = ''
    organization_id: int = None
    api_key_id: int = None


@dataclass
class Decision:
    allowed: bool
    reason: str = ''
    rule: CompiledRule = None
    detail: str = ''
    policy_version: int = 0
    matched: list = field(default_factory=list)


def parse_ip(value):
    """An ipaddress object for a client address string, or None.

    IPv4-mapped IPv6 addresses (::ffff:192.0.2.1) are treated as the IPv4
    address so one rule covers both spellings; zone ids are dropped."""
    text = (value or '').strip()
    if not text:
        return None
    text = text.split('%', 1)[0]
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


# --- loading -------------------------------------------------------------

_lock = threading.Lock()
_cache = {'policy': None}


def _compile(row):
    surfaces = (frozenset({'api', 'webhook'}) if row['surface'] == R.SURFACE_BOTH
                else frozenset({row['surface']}))
    return CompiledRule(
        id=row['id'], name=row['name'], action=row['action'], surfaces=surfaces,
        scope=row['scope'], organization_id=row['organization_id'],
        api_key_id=row['api_key_id'], target=row['target'],
        network=ipaddress.ip_network(row['network'], strict=False),
        expires_at=row['expires_at'])


def build_policy(settings_row, rule_rows):
    rules = []
    for row in rule_rows:
        try:
            rules.append(_compile(row))
        except ValueError:
            # Saved rules are validated, so this is a damaged row. Skipping an
            # allow rule only narrows access; a damaged deny rule is kept as a
            # deny of everything in its scope rather than silently dropped.
            logger.error('API access rule %s has an unreadable network %r', row['id'], row['network'])
            if row['action'] == R.ACTION_DENY:
                rules.append(_compile({**row, 'network': '0.0.0.0/0'}))
                rules.append(_compile({**row, 'network': '::/0'}))
    row = settings_row or {}
    return Policy(
        version=row.get('policy_version', 0),
        api_mode=row.get('api_mode', S.MODE_UNRESTRICTED),
        webhook_mode=row.get('webhook_mode', S.MODE_UNRESTRICTED),
        rules=tuple(rules),
        api_limits=(row.get('api_rate_per_address', 0) or 0, row.get('api_max_body_kb', 0) or 0),
        webhook_limits=(row.get('webhook_rate_per_address', 0) or 0, row.get('webhook_max_body_kb', 0) or 0))


SETTINGS_FIELDS = ('policy_version', 'api_mode', 'webhook_mode', 'api_rate_per_address',
                   'webhook_rate_per_address', 'api_max_body_kb', 'webhook_max_body_kb')

_RULE_FIELDS = ('id', 'name', 'action', 'surface', 'scope', 'organization_id', 'api_key_id',
                'target', 'network', 'expires_at')


def current_policy():
    """The policy, reloaded whenever the stored version changes.

    One indexed single-row read per covered request; the rules themselves are
    cached per process. If the database cannot be read, the last loaded
    policy is used; with none loaded yet, DatabaseError is raised."""
    row = S.objects.filter(pk=1).values(*SETTINGS_FIELDS, 'revert_at').first()
    if row and row['revert_at'] is not None and row['revert_at'] <= timezone.now():
        # A rollback window has ended without the change being kept: undo it
        # before deciding this request (v3.17.717, roadmap 81.6).
        from . import rollback
        try:
            rollback.revert_if_due()
        except Exception:  # never let the undo break request handling
            logger.exception('API access rollback could not be applied')
        row = S.objects.filter(pk=1).values(*SETTINGS_FIELDS, 'revert_at').first()
    cached = _cache['policy']
    version = row['policy_version'] if row else 0
    if cached is not None and cached.version == version:
        return cached
    rules = list(R.objects.filter(is_active=True).values(*_RULE_FIELDS))
    policy = build_policy(row, rules)
    with _lock:
        _cache['policy'] = policy
    return policy


def reset_cache():
    with _lock:
        _cache['policy'] = None


# --- evaluation ------------------------------------------------------------

def evaluate(policy, ctx, scopes=ALL_SCOPES, now=None):
    """Decide one request against ``policy`` for the given scope levels."""
    now = now or timezone.now()
    mode = policy.mode_for(ctx.surface)
    global_allow = mode in (S.MODE_ALLOWLIST, S.MODE_COMBINED)
    global_deny = mode in (S.MODE_DENYLIST, S.MODE_COMBINED)

    applicable = []
    for rule in policy.rules:
        if rule.scope not in scopes or not rule.applies_to(ctx):
            continue
        if rule.expires_at is not None and rule.expires_at <= now:
            continue
        if rule.scope == R.SCOPE_GLOBAL:
            if rule.action == R.ACTION_ALLOW and not global_allow:
                continue
            if rule.action == R.ACTION_DENY and not global_deny:
                continue
        applicable.append(rule)

    empty_global_allowlist = (
        R.SCOPE_GLOBAL in scopes and global_allow
        and not any(r.scope == R.SCOPE_GLOBAL and r.action == R.ACTION_ALLOW for r in applicable))

    if not applicable and not empty_global_allowlist:
        return Decision(True, policy_version=policy.version)
    if ctx.ip is None:
        return Decision(False, NO_ADDRESS, policy_version=policy.version)

    for rule in applicable:
        if rule.action == R.ACTION_DENY and rule.contains(ctx.ip):
            return Decision(False, DENY_RULE, rule=rule, policy_version=policy.version)

    if empty_global_allowlist:
        return Decision(False, ALLOWLIST_EMPTY, detail='global',
                        policy_version=policy.version)

    matched = []
    for level in _SCOPE_ORDER:
        allows = [r for r in applicable if r.scope == level and r.action == R.ACTION_ALLOW]
        if not allows:
            continue
        hit = next((r for r in allows if r.contains(ctx.ip)), None)
        if hit is None:
            return Decision(False, NOT_ALLOWLISTED, detail=level, policy_version=policy.version)
        matched.append(hit)
    return Decision(True, policy_version=policy.version, matched=matched)


def decide(ctx, scopes):
    """Load and evaluate, failing closed on errors when restrictions exist."""
    try:
        policy = current_policy()
    except DatabaseError:
        cached = _cache['policy']
        if cached is None:
            logger.exception('API access policy could not be loaded')
            return Decision(False, POLICY_UNAVAILABLE)
        policy = cached
    try:
        decision = evaluate(policy, ctx, scopes)
    except Exception:  # never let a bug turn a configured restriction into "allow"
        logger.exception('API access policy evaluation failed')
        restrictive = bool(policy.rules) or policy.mode_for(ctx.surface) != S.MODE_UNRESTRICTED
        return Decision(not restrictive, POLICY_ERROR if restrictive else '',
                        policy_version=policy.version)
    if decision.matched:
        note_matches(decision.matched)
    return decision


# --- match counters (written at most once a minute per process) ------------

_pending = {}
_last_flush = [time.monotonic()]
FLUSH_SECONDS = 60


def note_matches(rules):
    with _lock:
        for rule in rules:
            _pending[rule.id] = _pending.get(rule.id, 0) + 1
        due = time.monotonic() - _last_flush[0] >= FLUSH_SECONDS
        if not due:
            return
        batch = dict(_pending)
        _pending.clear()
        _last_flush[0] = time.monotonic()
    flush_matches(batch)


def flush_matches(batch):
    from django.db.models import F
    now = timezone.now()
    for rule_id, count in batch.items():
        try:
            R.objects.filter(pk=rule_id).update(match_count=F('match_count') + count,
                                                last_matched_at=now)
        except DatabaseError:
            logger.warning('could not update API access rule %s match count', rule_id)
