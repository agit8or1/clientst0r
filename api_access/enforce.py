"""Enforcement points: the middleware (network stage) and the API key check
(credential stage), plus the refusal log."""
import logging

from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone

from . import policy as P
from .groups import classify
from .models import ApiAccessDecision

logger = logging.getLogger('api_access')

FOLD_SECONDS = 60      # repeats inside this window are counted on one row
FOLD_FLUSH_EVERY = 25  # write the running count every N repeats

PUBLIC_MESSAGE = 'Access from this network address is not allowed.'


def client_ip_text(request):
    from core.client_ip import get_client_ip
    try:
        return get_client_ip(request) or ''
    except Exception:
        return ''


def context_for(request, route, api_key=None):
    return P.Context(
        ip=P.parse_ip(client_ip_text(request)),
        surface=route.surface, group=route.group, integration=route.integration,
        organization_id=getattr(api_key, 'organization_id', None),
        api_key_id=getattr(api_key, 'pk', None))


def record_refusal(request, route, ctx, decision, api_key=None):
    """Log a refusal, folding repeats so a flood writes a handful of rows."""
    rule_id = decision.rule.id if decision.rule else 0
    ip_text = str(ctx.ip) if ctx.ip is not None else ''
    fold = f'apiacc:deny:{ip_text}:{decision.reason}:{rule_id}:{route.group}:{ctx.api_key_id or 0}'
    try:
        if not cache.add(fold, 1, FOLD_SECONDS):
            try:
                n = cache.incr(fold)
            except ValueError:
                return
            row_id = cache.get(fold + ':row')
            if row_id and n % FOLD_FLUSH_EVERY == 0:
                ApiAccessDecision.objects.filter(pk=row_id).update(
                    count=F('count') + FOLD_FLUSH_EVERY, last_seen_at=timezone.now())
            return
        row = ApiAccessDecision.objects.create(
            source_ip=ip_text or None, surface=route.surface, endpoint_group=route.group,
            integration=route.integration, method=(request.method or '')[:10],
            path=(request.path_info or '')[:255], reason=decision.reason,
            detail=(decision.detail or '')[:255], rule_id=rule_id or None,
            rule_name=(decision.rule.name if decision.rule else '')[:120],
            api_key=api_key, api_key_prefix=getattr(api_key, 'key_prefix', '') or '',
            organization_id=ctx.organization_id, policy_version=decision.policy_version)
        cache.set(fold + ':row', row.pk, FOLD_SECONDS)
        _maybe_note_repeat_source(ip_text)
    except DatabaseError:
        logger.warning('could not record an API access refusal', exc_info=True)


def _maybe_note_repeat_source(ip_text):
    """Write one warning to the server log when a source keeps getting refused."""
    if not ip_text:
        return
    key = f'apiacc:src:{ip_text}'
    if cache.add(key, 1, 3600):
        return
    try:
        n = cache.incr(key)
    except ValueError:
        return
    if n in (10, 100, 1000):
        logger.warning('API access: %s refused %s times in the last hour', ip_text, n)


def refusal_response(decision):
    status = 503 if decision.reason == P.POLICY_UNAVAILABLE else 403
    return JsonResponse({'detail': PUBLIC_MESSAGE if status == 403
                         else 'Access policy unavailable; try again shortly.'}, status=status)


class ApiAccessMiddleware:
    """Network stage: global, integration and endpoint-group rules, before
    any view or authentication runs. Web pages are not touched."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        route = classify(request.path_info)
        if route is None:
            return self.get_response(request)
        request.api_access_route = route
        ctx = context_for(request, route)
        decision = P.decide(ctx, P.STAGE_NETWORK)
        if not decision.allowed:
            record_refusal(request, route, ctx, decision)
            return refusal_response(decision)
        return self.get_response(request)


def check_api_key(request, api_key):
    """Credential stage for an authenticated API key. Returns a Decision.

    Called from APIKeyAuthentication; ``request`` may be a DRF Request."""
    django_request = getattr(request, '_request', request)
    route = getattr(django_request, 'api_access_route', None) or classify(django_request.path_info)
    if route is None:  # an API key used on a non-API path: treat as the REST API
        from .groups import Route
        route = Route('rest_api', '')
    ctx = context_for(django_request, route, api_key)
    decision = P.decide(ctx, P.STAGE_CREDENTIAL)
    if not decision.allowed:
        record_refusal(django_request, route, ctx, decision, api_key=api_key)
    return decision
