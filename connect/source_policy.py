"""Default-deny source-address policy for the Agit8or Connect endpoints
(Quick Connect increment B1; DESIGN.md §5, roadmap 79.10 / 79.11).

Covered: ``/.well-known/agit8or-connect`` and everything under
``/connect/v1/`` (the ``connect`` surface of api_access.groups). Web pages,
the REST API, webhooks, the mobile API and ticket-rmm-v1 are not touched.

Evaluation order for one request (DESIGN.md §5.3):

  0. AGIT8OR_CONNECT_ENABLED off           -> the views answer 404 (unchanged)
  1. client address via core.client_ip      -> unreadable -> 403
     (X-Forwarded-For only from trusted proxies; IPv4-mapped IPv6 folded)
  2. compiled policy for the current version -> unavailable -> 403 (fail closed)
  3/4. installation layer: deny wins, empty allowlist denies
  5. which connection the request names (before authentication, §5.4)
  6/7. connection layer of that connection: deny wins, empty denies
  ... rate limits, body cap, kill switch, protocol authentication (views)
  11. binding: the connection proven by authentication must be one whose
      rules matched in 6/7 (``bind()``), else 403 + security event.

Both layers are evaluated by ``api_access.policy.evaluate`` (the same
engine as the REST API policy) over rules compiled from ``SourceRule``
rows, always in allowlist-with-deny-exceptions mode ("combined"). There is
no setting that opens it: no mode switch, no implicit trust of private or
loopback sources, no exemption for discovery, health or pairing, and the
site firewall's LAN exemption runs later and does not apply here.

Every rule change goes through ``apply_rules()`` in one transaction that
bumps ``InstallationIdentity.connect_policy_version``. Each request reads
that version (one indexed single-row read); a worker whose cached rules
are older reloads them. If the database cannot be read, the cached policy
is used for at most CACHE_MAX_AGE seconds, then every request is refused.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.utils import timezone

from agit8or_connect.errors import ConnectError

logger = logging.getLogger('connect')

SOURCE_NOT_AUTHORISED = 'source_not_authorised'
PUBLIC_MESSAGE = 'This source address is not authorised for Agit8or Connect.'
CACHE_MAX_AGE = 60          # seconds a cached policy may be used while the database is unreadable
OBSERVE_DAYS = 14           # observe period for connections that existed before B1 (DESIGN §13.2)
MAX_PAIRING_SOURCES = 4

# Allowlist entries (installation and connection layer): never "any address".
SOURCE_MIN_PREFIX = {4: 16, 6: 32}

# Refusal reasons in the folded api_access refusal log (prefix "connect_" is
# summarised into the Connect audit chain once a minute, connect/denials.py).
R_NO_ADDRESS = 'connect_source_no_address'
R_UNAVAILABLE = 'connect_policy_unavailable'
R_INSTALLATION = 'connect_source_installation'
R_CONNECTION = 'connect_source_connection'
R_DENIED = 'connect_source_deny_rule'
R_BINDING = 'connect_binding_mismatch'

UNION_ROUTES = frozenset({'discovery', 'health'})
PAIRING_ROUTES = frozenset({'pairing_submit', 'pairing_status'})
# Quick Connect exchange (PROTOCOL-1.1.md §5.6, §7.2): only the temporary
# pairing rule of the attempt whose one-time code the request carries.
QC_EXCHANGE_ROUTE = 'qc_exchange'
TOKEN_ROUTES = frozenset({'capabilities', 'test', 'customers', 'customer_current'})


class PolicyUnavailable(Exception):
    pass


# --- validation ------------------------------------------------------------------------

def validate_entry(network: str, *, private: bool = False, action: str = 'allow') -> tuple:
    """(canonical network, is_private) for one source rule entry, or
    ValidationError. Allow entries: no /0, IPv4 /16 or narrower, IPv6 /32 or
    narrower; private / loopback / link-local only as single addresses the
    administrator flagged. Deny entries may be wider (never /0)."""
    from api_access.models import normalize_limited_network
    if action == 'deny':
        return normalize_limited_network(network, min_prefix={4: 1, 6: 1}, private_ok=True, label='deny rule')
    return normalize_limited_network(network, min_prefix=SOURCE_MIN_PREFIX, private_ok=private,
                                     private_exact=True, label='Connect allow rule')


def parse_pairing_sources(values, *, private: bool = False) -> List[str]:
    """Exact addresses given with an invitation or a pairing (one per line or
    a list). Ranges are not accepted at pairing time; add them later as a
    reviewed change on the Network page."""
    if isinstance(values, str):
        values = values.replace(',', '\n').splitlines()
    out = []
    for raw in values or []:
        raw = str(raw).strip()
        if not raw:
            continue
        net, _ = validate_entry(raw, private=private)
        n = ipaddress.ip_network(net)
        if n.prefixlen != n.max_prefixlen:
            raise ValidationError(f'{net}: give the other application\'s exact address here. Ranges can be '
                                  'added later under Network, as a reviewed change.')
        if net not in out:
            out.append(net)
    if not out:
        raise ValidationError('Enter the address the other application connects from (its egress address). '
                              'Connect refuses every source address that is not listed.')
    if len(out) > MAX_PAIRING_SOURCES:
        raise ValidationError(f'At most {MAX_PAIRING_SOURCES} addresses at pairing time.')
    return out


# --- compiled policy -----------------------------------------------------------------------

def _compiled_rule(row):
    from api_access.models import ApiAccessRule as R, SURFACE_CONNECT
    from api_access.policy import CompiledRule
    return CompiledRule(id=row['id'], name=f"{row['layer']}:{row['id']}", action=row['action'],
                        surfaces=frozenset({SURFACE_CONNECT}), scope=R.SCOPE_GLOBAL, organization_id=None,
                        api_key_id=None, target='', network=ipaddress.ip_network(row['network'], strict=False),
                        expires_at=row['expires_at'])


def _policy(version, compiled_rules):
    from api_access.models import ApiAccessSettings as S
    from api_access.policy import Policy
    # Combined = allowlist with deny exceptions; an empty allowlist refuses all.
    return Policy(version=version, api_mode=S.MODE_COMBINED, webhook_mode=S.MODE_COMBINED,
                  rules=tuple(compiled_rules))


def _purposes(route: str) -> frozenset:
    from .models import SourceRule as SR
    if route in UNION_ROUTES:
        return frozenset({SR.PAIRING, SR.DISCOVERY, SR.ALL})
    if route in PAIRING_ROUTES:
        return frozenset({SR.PAIRING, SR.ALL})
    if route == QC_EXCHANGE_ROUTE:
        return frozenset({SR.PAIRING})
    return frozenset({SR.ALL})


@dataclass
class Compiled:
    version: int
    checked_at: float
    installation: object
    keyed: Dict[str, list]              # key -> [(CompiledRule, purpose)]; key = connection id or "inv:<id>"
    observe_until: object = None
    observe_connections: frozenset = frozenset()
    _per_route: dict = field(default_factory=dict)

    def policy_for(self, key: str, route: str):
        purposes = _purposes(route)
        ck = (key, purposes)
        hit = self._per_route.get(ck)
        if hit is None:
            rules = [r for r, purpose in self.keyed.get(key, ()) if r.action == 'deny' or purpose in purposes]
            hit = self._per_route[ck] = _policy(self.version, rules)
        return hit

    def observing(self, now=None) -> bool:
        return bool(self.observe_until and (now or timezone.now()) < self.observe_until)


_lock = threading.Lock()
_state = {'compiled': None}

_RULE_FIELDS = ('id', 'layer', 'status', 'connection_id', 'invitation_id', 'network', 'action', 'purpose', 'expires_at',
                'connection__state', 'invitation__used_at', 'invitation__burned_at')


def _build(version, observe_until, observe_connections, rows) -> Compiled:
    from .models import Connection, SourceRule as SR
    installation, keyed = [], {}
    for row in rows:
        if row['connection_id'] and row['connection__state'] == Connection.REVOKED:
            continue
        if row['connection_id'] and row['connection__state'] == Connection.FAILED and not (
                row['status'] == SR.TEMPORARY and row['purpose'] == SR.PAIRING):
            # A failed pairing keeps only its short-lived pairing rule, so the
            # other side can still poll and learn the outcome (rejected).
            continue
        if row['layer'] == SR.CONNECTION and not row['connection_id']:
            if not row['invitation_id'] or row['invitation__used_at'] or row['invitation__burned_at']:
                continue
        try:
            compiled = [_compiled_rule(row)]
        except ValueError:
            logger.error('Connect source rule %s has an unreadable network %r', row['id'], row['network'])
            if row['action'] != SR.DENY:
                continue
            compiled = [_compiled_rule({**row, 'network': '0.0.0.0/0'}), _compiled_rule({**row, 'network': '::/0'})]
        if row['layer'] == SR.INSTALLATION:
            installation.extend(compiled)
            continue
        key = str(row['connection_id']) if row['connection_id'] else f"inv:{row['invitation_id']}"
        keyed.setdefault(key, []).extend((c, row['purpose']) for c in compiled)
    return Compiled(version=version, checked_at=time.monotonic(), installation=_policy(version, installation),
                    keyed=keyed, observe_until=observe_until,
                    observe_connections=frozenset(str(c) for c in (observe_connections or [])))


def current() -> Compiled:
    """The compiled policy for the stored version. Raises PolicyUnavailable
    when the database cannot be read and the cache is older than
    CACHE_MAX_AGE (or empty)."""
    from .models import InstallationIdentity, SourceRule as SR
    cached = _state['compiled']
    try:
        row = (InstallationIdentity.objects.order_by('pk')
               .values_list('connect_policy_version', 'source_observe_until', 'source_observe_connections').first())
        version, observe_until, observe_conns = row if row else (0, None, [])
        if cached is not None and cached.version == version and cached.observe_until == observe_until:
            cached.checked_at = time.monotonic()
            return cached
        rows = list(SR.objects.filter(status__in=(SR.TEMPORARY, SR.ACTIVE)).values(*_RULE_FIELDS))
    except DatabaseError as e:
        if cached is not None and time.monotonic() - cached.checked_at < CACHE_MAX_AGE:
            return cached
        raise PolicyUnavailable(str(e)) from e
    compiled = _build(version, observe_until, observe_conns, rows)
    with _lock:
        _state['compiled'] = compiled
    return compiled


def reset_cache():
    with _lock:
        _state['compiled'] = None


# --- request classification ------------------------------------------------------------------

def route_name(request) -> str:
    from django.urls import Resolver404, resolve
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return ''
    return match.url_name if match.namespace == 'connect_api' else ''


def _uuid(value) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value or '').strip()))
    except (ValueError, AttributeError):
        return None


def named_connection(request, route: str) -> Optional[str]:
    """The connection id the request names before it is authenticated
    (DESIGN.md §5.4), or None. Never trusted on its own: bind() re-checks
    it against the authenticated connection."""
    from django.urls import resolve
    if route == 'pairing_status':
        from .models import PairingRequest
        rid = _uuid(resolve(request.path_info).kwargs.get('request_id'))
        if rid is None:
            return None
        cid = PairingRequest.objects.filter(pk=rid).values_list('connection_id', flat=True).first()
        return str(cid) if cid else None
    if route == 'jwks':
        return _uuid(resolve(request.path_info).kwargs.get('connection_id'))
    if route == QC_EXCHANGE_ROUTE:
        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            return None
        if length <= 0 or length > 64 * 1024:
            return None
        try:
            data = json.loads(request.body or b'{}')
        except Exception:   # not JSON, RequestDataTooBig, client disconnect
            return None
        from . import quick_connect
        return quick_connect.named_attempt(data.get('exchange') if isinstance(data, dict) else None)
    if route == 'events':
        from agit8or_connect import webhooks
        return _uuid(request.headers.get(webhooks.H_CONNECTION, ''))
    if route == 'token':
        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            return None
        if length <= 0 or length > 64 * 1024:
            return None
        from urllib.parse import parse_qs
        try:
            body = request.body
        except Exception:   # RequestDataTooBig, client disconnect
            return None
        values = parse_qs(body.decode('ascii', 'replace'), max_num_fields=10).get('client_id') or ['']
        return _uuid(values[0]) if len(values) == 1 else None
    if route in TOKEN_ROUTES:
        from agit8or_connect import tokens as sdk_tokens
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('DPoP '):
            return None
        return _uuid(sdk_tokens.token_client_id(auth[5:].strip()))
    return None


# --- evaluation ------------------------------------------------------------------------------

@dataclass
class SourceContext:
    ip: object = None
    route: str = ''
    named: Optional[str] = None
    matched: frozenset = frozenset()     # keys whose connection layer allowed the request
    lenient: bool = False                # allowed only by the observe period
    observe_connections: frozenset = frozenset()
    policy_version: int = 0

    @property
    def rate_key(self) -> str:
        return f'{self.ip}:{self.named or "-"}'


@dataclass
class Result:
    allowed: bool
    ctx: SourceContext
    reason: str = ''
    detail: str = ''


def evaluate_address(ip, route: str, named: Optional[str], compiled: Compiled, now=None) -> Result:
    """Steps 3-7 for one address. Pure: no database access."""
    from api_access.models import SURFACE_CONNECT
    from api_access.policy import DENY_RULE, Context, evaluate
    ctx = SourceContext(ip=ip, route=route, named=named, observe_connections=compiled.observe_connections,
                        policy_version=compiled.version)
    if ip is None:
        return Result(False, ctx, R_NO_ADDRESS, 'source address unreadable')
    pctx = Context(ip=ip, surface=SURFACE_CONNECT)
    inst = evaluate(compiled.installation, pctx, now=now)
    if route in UNION_ROUTES:
        candidates = list(compiled.keyed)
    elif route == 'pairing_submit':
        candidates = [k for k in compiled.keyed if k.startswith('inv:')]
    else:
        candidates = [named] if named and named in compiled.keyed else []
    matched, denied = set(), False
    for key in candidates:
        d = evaluate(compiled.policy_for(key, route), pctx, now=now)
        if d.allowed:
            matched.add(key)
        elif d.reason == DENY_RULE and key == named:
            denied = True
    ctx.matched = frozenset(matched)
    if not inst.allowed:
        reason = R_DENIED if inst.reason == DENY_RULE else R_INSTALLATION
        result = Result(False, ctx, reason, f'installation layer: {inst.reason}')
    elif not matched:
        reason = R_DENIED if denied else R_CONNECTION
        result = Result(False, ctx, reason, f'connection layer; connection {named or "-"}'[:255])
    else:
        return Result(True, ctx)
    # Observe period (DESIGN §13.2): connections that existed before source
    # rules shipped keep working until it ends; pairing is never lenient.
    if compiled.observing(now) and route not in ('pairing_submit', QC_EXCHANGE_ROUTE) and (
            route in UNION_ROUTES or (named and named in compiled.observe_connections)):
        ctx.lenient = True
        result.allowed = True
    return result


def check(request) -> Result:
    from api_access.enforce import client_ip_text
    from api_access.policy import parse_ip
    route = route_name(request)
    ip = parse_ip(client_ip_text(request))
    if ip is None:
        return Result(False, SourceContext(route=route), R_NO_ADDRESS, 'source address unreadable')
    try:
        compiled = current()
        named = named_connection(request, route)
    except (PolicyUnavailable, DatabaseError):
        logger.warning('Connect source policy unavailable; refusing %s', request.path_info)
        return Result(False, SourceContext(ip=ip, route=route), R_UNAVAILABLE, 'policy could not be loaded')
    result = evaluate_address(ip, route, named, compiled)
    if result.allowed and not result.ctx.lenient:
        _note_matches(compiled, result.ctx)
    return result


def refusal_response():
    r = JsonResponse({'error': {'code': SOURCE_NOT_AUTHORISED, 'message': PUBLIC_MESSAGE}}, status=403)
    r['Cache-Control'] = 'no-store'
    return r


def _record_refusal(request, route, result):
    """One folded Refused-requests row per source and reason per minute
    (exact counts), summarised into the Connect chain once a minute."""
    from . import denials
    denials.note(result.reason, source_ip=str(result.ctx.ip or ''), path=request.path_info or '',
                 method=request.method or '', detail=result.detail or '')


def middleware_check(request, route):
    """Called by api_access.enforce.ApiAccessMiddleware for the connect
    surface, before any view or authentication. None = continue."""
    from . import identity
    if not identity.enabled():
        return None      # step 0: every Connect view answers 404
    if route_name(request) == QC_EXCHANGE_ROUTE:
        from . import quick_connect
        if not quick_connect.available():
            return None  # Quick Connect off: the view answers 404, like any unserved route
    result = check(request)
    request.connect_source = result.ctx
    if result.allowed:
        return None
    _record_refusal(request, route, result)
    if result.ctx.route == QC_EXCHANGE_ROUTE and result.ctx.named and result.ctx.ip is not None:
        # Observed vs approved address, shown on the attempt; adds nothing.
        from . import quick_connect
        quick_connect.note_refused_source(result.ctx.named, result.ctx.ip)
    return refusal_response()


# --- binding (step 11) and observation -----------------------------------------------------

def _source_of(request) -> Optional[SourceContext]:
    return getattr(request, 'connect_source', None) or getattr(getattr(request, '_request', None),
                                                                'connect_source', None)


def bind(request, conn):
    """After authentication: the connection proven by the credentials must be
    one whose rules matched this request's source. Refuses (403
    source_not_authorised) and records a security event otherwise. During
    the observe period, a connection listed for it is let through and the
    source is recorded as observed instead."""
    src = _source_of(request)
    cid = str(conn.pk)
    if src is None:
        raise ConnectError(SOURCE_NOT_AUTHORISED, PUBLIC_MESSAGE, 403)
    if cid in src.matched:
        _note_source(conn, src.ip)
        return
    if src.lenient and cid in src.observe_connections:
        record_observation(conn, src.ip)
        return
    _binding_mismatch(request, conn, src)
    raise ConnectError(SOURCE_NOT_AUTHORISED, PUBLIC_MESSAGE, 403)


def bind_invitation(request, invitation) -> None:
    """Pairing submit: the request must come from an address the
    administrator attached to THIS invitation."""
    src = _source_of(request)
    if src is not None and f'inv:{invitation.pk}' in src.matched:
        return
    from . import denials
    denials.note(R_BINDING, source_ip=str(getattr(src, 'ip', '') or ''), path=request.path_info,
                 detail=f'invitation {invitation.pk}')
    raise ConnectError(SOURCE_NOT_AUTHORISED, PUBLIC_MESSAGE, 403)


def _binding_mismatch(request, conn, src):
    from . import audit_log, denials
    ip = str(src.ip or '')
    denials.note(R_BINDING, source_ip=ip, path=request.path_info, detail=f'connection {conn.pk}')
    # A security event, after valid credentials: one chain record per
    # connection per minute at most.
    if cache.add(f'connect:binding:{conn.pk}', 1, 60):
        audit_log.record('source.binding_mismatch', 'denied', connection=conn, app=conn.remote_installation_id,
                         detail={'source_ip': ip, 'route': src.route,
                                 'named': src.named or '', 'matched': sorted(src.matched)[:10]})


def _note_source(conn, ip):
    if ip is None:
        return
    from .models import Connection
    text = str(ip)
    if conn.last_source_ip != text or not conn.last_source_at or \
            (timezone.now() - conn.last_source_at).total_seconds() > 300:
        Connection.objects.filter(pk=conn.pk).update(last_source_ip=text, last_source_at=timezone.now())
        conn.last_source_ip = text


def _host_network(ip) -> str:
    return str(ipaddress.ip_network(f'{ip}/{ip.max_prefixlen}'))


def record_observation(conn, ip):
    """An authenticated request allowed only by the observe period: listed on
    the connection's Network section for an administrator to approve. Never
    grants anything by itself."""
    from . import audit_log
    from .models import SourceRule as SR
    if ip is None:
        return
    net = _host_network(ip)
    now = timezone.now()
    row, created = SR.objects.get_or_create(
        layer=SR.CONNECTION, connection=conn, network=net, status=SR.OBSERVED,
        defaults={'observed_first_at': now, 'last_matched_at': now, 'match_count': 1,
                  'private': ipaddress.ip_address(ip).is_private,
                  'description': 'Seen during the observe period'})
    if not created:
        SR.objects.filter(pk=row.pk).update(match_count=F('match_count') + 1, last_matched_at=now)
    else:
        audit_log.record('source.observed', 'ok', connection=conn, app=conn.remote_installation_id,
                         detail={'source_ip': str(ip)})
    _note_source(conn, ip)


# --- match counters (at most once a minute per process) -------------------------------------

_pending: Dict[int, int] = {}
_last_flush = [time.monotonic()]


def _note_matches(compiled: Compiled, ctx: SourceContext):
    from api_access.policy import Context, evaluate
    from api_access.models import SURFACE_CONNECT
    ids = []
    pctx = Context(ip=ctx.ip, surface=SURFACE_CONNECT)
    d = evaluate(compiled.installation, pctx)
    ids.extend(r.id for r in d.matched)
    for key in ctx.matched:
        ids.extend(r.id for r in evaluate(compiled.policy_for(key, ctx.route), pctx).matched)
    with _lock:
        for i in ids:
            _pending[i] = _pending.get(i, 0) + 1
        if time.monotonic() - _last_flush[0] < 60:
            return
        batch = dict(_pending)
        _pending.clear()
        _last_flush[0] = time.monotonic()
    from .models import SourceRule
    now = timezone.now()
    for rule_id, n in batch.items():
        try:
            SourceRule.objects.filter(pk=rule_id).update(match_count=F('match_count') + n, last_matched_at=now)
        except DatabaseError:
            pass


# --- applying rule changes --------------------------------------------------------------------

def _bump():
    from . import identity
    from .models import InstallationIdentity
    ident = identity.get()
    InstallationIdentity.objects.filter(pk=ident.pk).update(
        connect_policy_version=F('connect_policy_version') + 1)


def _audit(operation, *, user=None, connection=None, detail=None, result='ok'):
    from . import audit_log
    audit_log.record(operation, result, connection=connection, user=user, detail=detail or {})


def _audit_admin(user, description, extra):
    """Administrator configuration actions also go to AuditLog (sealed by
    audit/chain.py), as tech_access does."""
    try:
        from audit.models import AuditLog
        AuditLog.log(user=user if getattr(user, 'pk', None) else None, action='update',
                     object_type='connect_source_policy', object_repr=description[:255], description=description,
                     extra_data=extra)
    except Exception:   # the Connect chain record is the authoritative one
        logger.exception('could not write the AuditLog record for a Connect policy change')


def create_rules(entries: Iterable[dict], *, user=None, approver=None, change=None, status=None):
    """Write rule rows and bump the policy version (caller holds the
    transaction). Entries are already validated."""
    from .models import SourceRule as SR
    rows = []
    for e in entries:
        rows.append(SR.objects.create(
            layer=e['layer'], connection_id=e.get('connection') or None, invitation_id=e.get('invitation') or None,
            network=e['network'], private=bool(e.get('private')), action=e.get('action', SR.ALLOW),
            status=status or e.get('status', SR.ACTIVE), purpose=e.get('purpose', SR.ALL),
            expires_at=e.get('expires_at'), description=str(e.get('description') or '')[:200],
            change=change, created_by=user if getattr(user, 'pk', None) else None,
            approved_by=approver if getattr(approver, 'pk', None) else None))
    return rows


def pairing_rules_for_invitation(invitation, sources: List[str], user, *, private=False):
    """Temporary pairing rules for one invitation (DESIGN §6.6): only these
    addresses may submit a pairing request with this code, and only to the
    pairing endpoints, until the invitation expires."""
    from .models import SourceRule as SR
    with transaction.atomic():
        create_rules([{'layer': SR.CONNECTION, 'invitation': invitation.pk, 'network': n, 'private': private,
                       'status': SR.TEMPORARY, 'purpose': SR.PAIRING, 'expires_at': invitation.expires_at,
                       'description': 'Pairing (invitation)'} for n in sources], user=user, approver=user)
        _bump()
    _audit('source_rules.temporary', user=user, detail={'invitation': str(invitation.pk), 'sources': sources,
                                                        'expires': invitation.expires_at.isoformat()})


def pairing_rules_for_connection(conn, sources: List[str], user, *, expires_at, private=False):
    """Temporary pairing rules for an outbound pairing: the other application
    may read our discovery (and later reach us) from these addresses."""
    from .models import SourceRule as SR
    with transaction.atomic():
        create_rules([{'layer': SR.CONNECTION, 'connection': conn.pk, 'network': n, 'private': private,
                       'status': SR.TEMPORARY, 'purpose': SR.PAIRING, 'expires_at': expires_at,
                       'description': 'Pairing'} for n in sources], user=user, approver=user)
        _bump()
    _audit('source_rules.temporary', user=user, connection=conn, detail={'sources': sources,
                                                                         'expires': expires_at.isoformat()})


def link_invitation(invitation, conn, expires_at):
    """The invitation's pairing rules now belong to the connection its
    request created (status polls are evaluated against them)."""
    from .models import SourceRule as SR
    n = SR.objects.filter(invitation=invitation, connection__isnull=True, status=SR.TEMPORARY).update(
        connection=conn, expires_at=expires_at)
    if n:
        _bump()


def promote_on_activate(conn, user):
    """At activation (caller's transaction): the connection's temporary
    pairing rules become its active rules for every Connect endpoint. The
    administrator approving the connection approved these addresses with the
    pairing; nothing else is added."""
    from .models import ConnectChange, SourceRule as SR
    temp = list(SR.objects.filter(connection=conn, layer=SR.CONNECTION, status=SR.TEMPORARY,
                                  action=SR.ALLOW))
    if not temp:
        return []
    change = ConnectChange.objects.create(
        connection=conn, kind=ConnectChange.SOURCE_RULES, status=ConnectChange.APPLIED, widening=True,
        payload={'add': [{'layer': SR.CONNECTION, 'connection': str(conn.pk), 'network': r.network,
                          'action': SR.ALLOW, 'private': r.private, 'purpose': SR.ALL} for r in temp],
                 'remove': [r.pk for r in temp], 'via': 'pairing approval'},
        proposed_by=user if getattr(user, 'pk', None) else None, approved_by=user if getattr(user, 'pk', None)
        else None, applied_at=timezone.now(), note='Addresses approved with the pairing')
    now = timezone.now()
    SR.objects.filter(pk__in=[r.pk for r in temp]).update(status=SR.REMOVED, removed_at=now)
    create_rules([{'layer': SR.CONNECTION, 'connection': conn.pk, 'network': r.network, 'private': r.private,
                   'action': SR.ALLOW, 'purpose': SR.ALL, 'description': 'Approved with the pairing'}
                  for r in temp], user=temp[0].created_by, approver=user, change=change)
    _bump()
    _audit('source_rules.applied', user=user, connection=conn,
           detail={'change': change.pk, 'added': [r.network for r in temp], 'via': 'pairing approval'})
    return temp


RESULT_POLL_WINDOW = 3600


def remove_connection_rules(conn, reason='', *, keep_result_poll=False):
    """A revoked or failed connection keeps no reachable source rule. With
    ``keep_result_poll`` (a rejected or expired pairing) its temporary
    pairing rule stays for at most an hour, for the status poll only."""
    from .models import SourceRule as SR
    now = timezone.now()
    qs = SR.objects.filter(connection=conn, status__in=(SR.STAGED, SR.TEMPORARY, SR.ACTIVE))
    if keep_result_poll:
        until = now + timedelta(seconds=RESULT_POLL_WINDOW)
        keep = qs.filter(status=SR.TEMPORARY, purpose=SR.PAIRING, action=SR.ALLOW)
        keep.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=until)).update(expires_at=until)
        qs = qs.exclude(pk__in=list(keep.values_list('pk', flat=True)))
    n = qs.update(status=SR.REMOVED, removed_at=now)
    if n:
        _bump()
        _audit('source_rules.removed', connection=conn, detail={'count': n, 'reason': reason})
    return n


def remove_invitation_rules(invitation):
    from .models import SourceRule as SR
    n = SR.objects.filter(invitation=invitation, connection__isnull=True,
                          status__in=(SR.TEMPORARY, SR.STAGED)).update(status=SR.REMOVED, removed_at=timezone.now())
    if n:
        _bump()
    return n


# --- staged changes (DESIGN §11) --------------------------------------------------------------

class ChangeRefused(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _scope_state(payload) -> list:
    """The committed rules a change touches: the installation layer and every
    connection the change names."""
    from .models import SourceRule as SR
    conns = sorted({str(e.get('connection')) for e in payload.get('add', []) if e.get('connection')}
                   | {str(c) for c in SR.objects.filter(pk__in=payload.get('remove', []))
                      .values_list('connection_id', flat=True) if c})
    layers = {e['layer'] for e in payload.get('add', [])} | set(
        SR.objects.filter(pk__in=payload.get('remove', [])).values_list('layer', flat=True))
    qs = SR.objects.filter(status__in=(SR.ACTIVE, SR.TEMPORARY))
    rows = []
    for r in qs.filter(layer=SR.INSTALLATION) if SR.INSTALLATION in layers else []:
        rows.append(['installation', '', r.pk, r.network, r.action, r.status])
    for r in qs.filter(layer=SR.CONNECTION, connection_id__in=conns):
        rows.append(['connection', str(r.connection_id), r.pk, r.network, r.action, r.status])
    return sorted(rows)


def fingerprint(payload) -> str:
    raw = json.dumps({'payload': payload, 'state': _scope_state(payload)}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _active_sets(payload, extra_remove=()) -> dict:
    from .models import SourceRule as SR
    remove = set(payload.get('remove', [])) | set(extra_remove)
    out = {}
    for r in SR.objects.filter(status=SR.ACTIVE):
        if r.pk in remove:
            continue
        key = (r.layer, str(r.connection_id or ''))
        out.setdefault(key, {'allow': set(), 'deny': set()})[r.action].add(r.network)
    return out


def _simulate(rules_by_key, conn_id, ip):
    """Would ``ip`` pass both layers for ``conn_id`` under the given sets?"""
    from api_access.models import SURFACE_CONNECT
    from api_access.policy import Context, evaluate
    def pol(sets):
        rows, n = [], 0
        for action in ('allow', 'deny'):
            for net in sorted(sets.get(action, ())):
                n += 1
                rows.append(_compiled_rule({'id': -n, 'layer': 'sim', 'action': action, 'network': net,
                                            'expires_at': None}))
        return _policy(0, rows)
    ctx = Context(ip=ip, surface=SURFACE_CONNECT)
    inst = rules_by_key.get(('installation', ''), {})
    conn = rules_by_key.get(('connection', conn_id), {})
    return evaluate(pol(inst), ctx).allowed and evaluate(pol(conn), ctx).allowed


def compute_preview(payload) -> dict:
    """Server-side impact preview: what gains and loses access, whether it
    widens, and which active connection would stop passing (lockout check
    against each connection's last authenticated source)."""
    from api_access.policy import parse_ip
    from .models import Connection, SourceRule as SR
    before = _active_sets({})
    after = _active_sets(payload)
    removed = list(SR.objects.filter(pk__in=payload.get('remove', [])))
    for e in payload.get('add', []):
        key = (e['layer'], str(e.get('connection') or '') if e['layer'] == SR.CONNECTION else '')
        after.setdefault(key, {'allow': set(), 'deny': set()})[e.get('action', SR.ALLOW)].add(e['network'])
    gains = [f"{e['layer']} {e['network']}" for e in payload.get('add', []) if e.get('action', 'allow') == 'allow']
    gains += [f'{r.layer} {r.network} (deny removed)' for r in removed if r.action == SR.DENY]
    loses = [f'{r.layer} {r.network}' for r in removed if r.action == SR.ALLOW]
    loses += [f"{e['layer']} {e['network']} (denied)" for e in payload.get('add', []) if e.get('action') == 'deny']
    lockout = []
    for c in Connection.objects.filter(state=Connection.ACTIVE).exclude(last_source_ip=None):
        ip = parse_ip(c.last_source_ip)
        if ip is not None and _simulate(before, str(c.pk), ip) and not _simulate(after, str(c.pk), ip):
            lockout.append({'connection': str(c.pk), 'name': c.remote_display_name or c.remote_app_type,
                            'source': c.last_source_ip})
    ser = lambda d: {f'{k[0]}:{k[1]}': {a: sorted(v) for a, v in s.items()} for k, s in d.items()}  # noqa: E731
    return {'gains': gains, 'loses': loses, 'widening': bool(gains), 'lockout': lockout,
            'before': ser(before), 'after': ser(after)}


def propose(*, add=(), remove=(), user, connection=None, note='') -> 'ConnectChange':
    """Stage a source-rule change. ``add``: dicts with layer, connection (for
    the connection layer), network, action, private, purpose, expires_at,
    description. ``remove``: SourceRule ids (active or temporary)."""
    from .models import Connection, ConnectChange, SourceRule as SR
    entries = []
    for e in add:
        layer = e.get('layer')
        if layer not in (SR.INSTALLATION, SR.CONNECTION):
            raise ValidationError('Choose the installation or a connection.')
        action = e.get('action') or SR.ALLOW
        if action not in (SR.ALLOW, SR.DENY):
            raise ValidationError('Choose allow or deny.')
        net, private = validate_entry(e.get('network', ''), private=bool(e.get('private')), action=action)
        cid = ''
        if layer == SR.CONNECTION:
            c = Connection.objects.filter(pk=_uuid(e.get('connection'))).exclude(
                state__in=(Connection.REVOKED, Connection.FAILED)).first() if _uuid(e.get('connection')) else None
            if c is None:
                raise ValidationError('That connection does not exist or is no longer usable.')
            cid = str(c.pk)
        purpose = e.get('purpose') or SR.ALL
        if purpose not in dict(SR.PURPOSES):
            raise ValidationError('Unknown purpose.')
        expires = e.get('expires_at')
        entries.append({'layer': layer, 'connection': cid, 'network': net, 'action': action, 'private': private,
                        'purpose': purpose, 'expires_at': expires.isoformat() if expires else None,
                        'description': str(e.get('description') or '')[:200]})
    rm = sorted({int(x) for x in remove})
    if rm and SR.objects.filter(pk__in=rm, status__in=(SR.ACTIVE, SR.TEMPORARY)).count() != len(rm):
        raise ValidationError('A rule to remove is no longer active.')
    if not entries and not rm:
        raise ValidationError('Nothing to change.')
    payload = {'add': entries, 'remove': rm}
    preview = compute_preview(payload)
    from . import identity
    ident = identity.get()
    conn = connection or (Connection.objects.filter(pk=entries[0]['connection']).first()
                          if entries and entries[0]['connection'] else None)
    change = ConnectChange.objects.create(
        connection=conn, kind=ConnectChange.SOURCE_RULES, payload=payload, preview=preview,
        widening=preview['widening'], fingerprint=fingerprint(payload),
        base_version=ident.connect_policy_version, proposed_by=user, note=note[:300])
    _audit('source_rules.proposed', user=user, connection=conn,
           detail={'change': change.pk, 'gains': preview['gains'], 'loses': preview['loses'],
                   'widening': preview['widening'], 'lockout': len(preview['lockout'])})
    return change


def _fresh(request) -> bool:
    from tech_access.protected import has_fresh_auth
    return request is not None and has_fresh_auth(request)


def approve(change, request):
    """Narrowing: applied now by this administrator (fresh re-auth).
    Widening: opens a tech_access protected change (kind app_connection) that
    a second administrator approves; it is applied by the applier with the
    fingerprint re-checked. Returns the ProtectedChange or None."""
    from .models import ConnectChange
    user = request.user
    if change.status != ConnectChange.STAGED:
        raise ChangeRefused(f'This change is {change.get_status_display().lower()}.')
    if not _fresh(request):
        raise ChangeRefused('Re-enter your password to approve a network change.')
    if fingerprint(change.payload) != change.fingerprint:
        raise ChangeRefused('The rules changed since this was proposed. Propose it again.')
    if change.widening:
        from tech_access.protected import can_widen_at_all, propose as tp
        if not can_widen_at_all(user):
            raise ChangeRefused('Widening Connect network access needs a second administrator (an approver for '
                                'protected changes), and there is none other than you.')
        pc = tp('app_connection', f'Agit8or Connect network change #{change.pk}: allow '
                + ', '.join(change.preview.get('gains', []))[:200],
                {'connect_change': change.pk, 'fingerprint': change.fingerprint},
                [f'Connect source {g}' for g in change.preview.get('gains', [])], user, request=request)
        change.status, change.protected_change_id = ConnectChange.AWAITING_SECOND, pc.pk
        change.save(update_fields=['status', 'protected_change_id'])
        _audit('source_rules.second_approval_requested', user=user, connection=change.connection,
               detail={'change': change.pk, 'protected_change': pc.pk}, result='pending')
        return pc
    apply_change(change, user)
    return None


def apply_change(change, approver, *, protected=False):
    """Apply atomically: rules written, version bumped, audit recorded.
    Refused if the touched rules changed since the proposal."""
    from .models import ConnectChange, InstallationIdentity, SourceRule as SR
    from . import identity
    expected = ConnectChange.AWAITING_SECOND if protected else ConnectChange.STAGED
    ident = identity.get()
    with transaction.atomic():
        InstallationIdentity.objects.select_for_update().get(pk=ident.pk)
        change = ConnectChange.objects.select_for_update().get(pk=change.pk)
        if change.status != expected:
            raise ChangeRefused('This change is no longer waiting to be applied.')
        if fingerprint(change.payload) != change.fingerprint:
            raise ChangeRefused('The rules changed since this was proposed. Propose it again.')
        now = timezone.now()
        SR.objects.filter(pk__in=change.payload.get('remove', [])).update(status=SR.REMOVED, removed_at=now)
        entries = []
        for e in change.payload.get('add', []):
            exp = e.get('expires_at')
            entries.append({**e, 'connection': e.get('connection') or None,
                            'expires_at': datetime.fromisoformat(exp) if exp else None,
                            'status': SR.ACTIVE})
        create_rules(entries, user=change.proposed_by, approver=approver, change=change)
        change.status, change.approved_by, change.applied_at = ConnectChange.APPLIED, approver, now
        change.save(update_fields=['status', 'approved_by', 'applied_at'])
        _bump()
        _audit('source_rules.applied', user=approver, connection=change.connection,
               detail={'change': change.pk, 'gains': change.preview.get('gains', []),
                       'loses': change.preview.get('loses', []), 'widening': change.widening})
    _audit_admin(approver, f'Agit8or Connect source rules change #{change.pk} applied',
                 {'gains': change.preview.get('gains', []), 'loses': change.preview.get('loses', [])})
    return change


def apply_protected(protected_change, reviewer):
    """tech_access applier branch (connect/approvals.py)."""
    from tech_access.protected import ProtectedChangeError
    from .models import ConnectChange
    p = protected_change.payload
    change = ConnectChange.objects.filter(pk=p.get('connect_change')).first()
    if change is None or change.fingerprint != p.get('fingerprint'):
        raise ProtectedChangeError('The network change no longer matches what was proposed.')
    try:
        if change.kind == ConnectChange.DESTINATION:
            from . import destinations
            destinations.apply_change(change, reviewer, protected=True)
        else:
            apply_change(change, reviewer, protected=True)
    except ChangeRefused as e:
        raise ProtectedChangeError(e.message)


def reject(change, user):
    from .models import ConnectChange
    if change.status not in (ConnectChange.STAGED, ConnectChange.AWAITING_SECOND):
        raise ChangeRefused('This change is no longer waiting for a decision.')
    change.status = ConnectChange.REJECTED
    change.save(update_fields=['status'])
    _audit('source_rules.rejected', user=user, connection=change.connection, detail={'change': change.pk})


def rollback(change, request):
    """Undo an applied change WITHOUT ever widening (DESIGN §11.4): allow
    entries it added are removed, deny entries it removed are restored.
    Allow entries it removed are not restored (that needs a new, approved
    change), so the result is never wider than either version."""
    from .models import ConnectChange, InstallationIdentity, SourceRule as SR
    from . import identity
    user = request.user
    if change.status != ConnectChange.APPLIED or change.kind != ConnectChange.SOURCE_RULES:
        raise ChangeRefused('Only an applied source-rule change can be rolled back.')
    if not _fresh(request):
        raise ChangeRefused('Re-enter your password to roll back a network change.')
    ident = identity.get()
    with transaction.atomic():
        InstallationIdentity.objects.select_for_update().get(pk=ident.pk)
        now = timezone.now()
        added_allow = list(SR.objects.filter(change=change, action=SR.ALLOW,
                                             status__in=(SR.ACTIVE, SR.TEMPORARY)))
        removed_deny = list(SR.objects.filter(pk__in=change.payload.get('remove', []), action=SR.DENY))
        rb = ConnectChange.objects.create(
            connection=change.connection, kind=ConnectChange.SOURCE_RULES, status=ConnectChange.APPLIED,
            widening=False, rollback_of=change, proposed_by=user, approved_by=user, applied_at=now,
            payload={'add': [{'layer': r.layer, 'connection': str(r.connection_id or ''), 'network': r.network,
                              'action': SR.DENY} for r in removed_deny],
                     'remove': [r.pk for r in added_allow]},
            note=f'Rollback of change #{change.pk} (narrowing only)')
        SR.objects.filter(pk__in=[r.pk for r in added_allow]).update(status=SR.REMOVED, removed_at=now)
        create_rules([{'layer': r.layer, 'connection': r.connection_id, 'network': r.network, 'action': SR.DENY,
                       'purpose': SR.ALL, 'description': f'Restored by rollback of #{change.pk}'}
                      for r in removed_deny], user=user, approver=user, change=rb)
        change.status = ConnectChange.ROLLED_BACK
        change.save(update_fields=['status'])
        _bump()
        _audit('source_rules.rolled_back', user=user, connection=change.connection,
               detail={'change': change.pk, 'rollback': rb.pk, 'removed': [r.network for r in added_allow],
                       'restored_deny': [r.network for r in removed_deny]})
    _audit_admin(user, f'Agit8or Connect source rules change #{change.pk} rolled back (narrowing only)',
                 {'rollback': rb.pk})
    return rb


def enforce_now(user):
    """End the observe period early (DESIGN §13.2). Cannot be undone."""
    from . import identity
    from .models import InstallationIdentity
    ident = identity.get()
    if not ident.source_observe_until:
        return False
    InstallationIdentity.objects.filter(pk=ident.pk).update(source_observe_until=None)
    _bump()
    _audit('source_policy.enforced', user=user, detail={'was_until': ident.source_observe_until.isoformat()})
    _audit_admin(user, 'Agit8or Connect source policy enforced (observe period ended)', {})
    return True


def observe_status():
    from . import identity
    ident = identity.get()
    until = ident.source_observe_until
    if until and until > timezone.now():
        return {'until': until, 'connections': list(ident.source_observe_connections or [])}
    return None


# --- administrator helpers -------------------------------------------------------------------

def test_address(ip_text: str, connection_id: str = '', route: str = 'capabilities') -> dict:
    """'Would this address pass?' for the Network page, without recording."""
    from api_access.policy import parse_ip
    ip = parse_ip(ip_text)
    if ip is None:
        raise ValidationError('Enter a single IPv4 or IPv6 address.')
    compiled = current()
    result = evaluate_address(ip, route, _uuid(connection_id) if connection_id else None, compiled)
    return {'ip': str(ip), 'allowed': result.allowed and not result.ctx.lenient, 'lenient': result.ctx.lenient,
            'reason': result.reason, 'detail': result.detail, 'matched': sorted(result.ctx.matched)}


def installation_allows(network: str) -> bool:
    """Does the committed installation layer allow this address (or the
    first address of this network)?"""
    from api_access.models import SURFACE_CONNECT
    from api_access.policy import Context, evaluate, parse_ip
    try:
        ip = parse_ip(str(network).split('/')[0])
        return ip is not None and evaluate(current().installation, Context(ip=ip, surface=SURFACE_CONNECT)).allowed
    except PolicyUnavailable:
        return False


def recent_refusals(connection=None, limit=25):
    from api_access.models import ApiAccessDecision, SURFACE_CONNECT
    qs = ApiAccessDecision.objects.filter(surface=SURFACE_CONNECT)
    if connection is not None:
        qs = qs.filter(detail__contains=str(connection.pk))
    return qs.order_by('-created_at')[:limit]


def apply_direct(entries=(), remove=(), *, via='manage.py', user=None):
    """Server-side recovery (manage.py connect_source_rules): applied at
    once, audited. Whoever runs it already controls the server."""
    from .models import SourceRule as SR
    clean = []
    for e in entries:
        net, private = validate_entry(e['network'], private=bool(e.get('private')), action=e.get('action', 'allow'))
        clean.append({**e, 'network': net, 'private': private})
    with transaction.atomic():
        now = timezone.now()
        n = SR.objects.filter(pk__in=list(remove), status__in=(SR.ACTIVE, SR.TEMPORARY)).update(
            status=SR.REMOVED, removed_at=now) if remove else 0
        rows = create_rules(clean, user=user, approver=user)
        _bump()
        _audit('source_rules.applied', user=user, detail={'via': via, 'added': [r.network for r in rows],
                                                          'removed': n})
    _audit_admin(user, f'Agit8or Connect source rules changed via {via}',
                 {'added': [r.network for r in rows], 'removed': n})
    return rows


def observe_deadline_for_migration(now=None):
    return (now or timezone.now()) + timedelta(days=OBSERVE_DAYS)
