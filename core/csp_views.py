"""
CSP violation report endpoint (POST /csp-report/).

Browsers send reports here from the `report-uri` / `report-to` directives
added by core.csp_middleware. Each report is summarised to the
`security.csp` logger so an operator running in Report-Only mode can see what
an enforcing policy would block before switching CSP_REPORT_ONLY off.

Anonymous by design (reports carry no cookies we rely on), CSRF-exempt,
size-capped and rate limited per client IP plus a global ceiling, so it
cannot be used to flood the logs.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.client_ip import get_client_ip

logger = logging.getLogger('security.csp')

MAX_BODY = 16 * 1024
GLOBAL_LIMIT_FACTOR = 10  # global ceiling = per-IP limit x this
_FIELDS = (
    ('document-uri', 'documentURL'),
    ('effective-directive', 'effectiveDirective'),
    ('violated-directive', None),
    ('blocked-uri', 'blockedURL'),
    ('source-file', 'sourceFile'),
    ('line-number', 'lineNumber'),
    ('script-sample', 'sample'),
    ('disposition', 'disposition'),
)


def _over_limit(key, limit):
    cache.add(key, 0, 60)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, 60)
        count = 1
    return count > limit


def _reports(payload):
    """Normalise report-uri ({"csp-report": {...}}) and Reporting API
    ([{"type": "csp-violation", "body": {...}}]) payloads."""
    if isinstance(payload, dict) and isinstance(payload.get('csp-report'), dict):
        yield payload['csp-report'], False
    elif isinstance(payload, list):
        for item in payload[:20]:
            if isinstance(item, dict) and item.get('type') == 'csp-violation' and isinstance(item.get('body'), dict):
                yield item['body'], True


def _summary(report, reporting_api):
    parts = []
    for legacy, modern in _FIELDS:
        key = modern if reporting_api and modern else legacy
        value = report.get(key)
        if value in (None, ''):
            continue
        parts.append(f'{legacy}={str(value)[:200]!r}')
    return ' '.join(parts)


@csrf_exempt
@require_POST
def csp_report(request):
    limit = max(int(getattr(settings, 'CSP_REPORT_RATE_LIMIT', 30)), 1)
    ip = get_client_ip(request) or 'unknown'
    if _over_limit(f'csp-report:ip:{ip}', limit) or _over_limit('csp-report:all', limit * GLOBAL_LIMIT_FACTOR):
        return HttpResponse(status=429)

    try:
        length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        return HttpResponse(status=413)
    body = request.body[:MAX_BODY + 1]
    if len(body) > MAX_BODY:
        return HttpResponse(status=413)

    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return HttpResponse(status=400)

    logged = 0
    for report, reporting_api in _reports(payload):
        logger.warning('CSP violation from %s: %s', ip, _summary(report, reporting_api))
        logged += 1
    return HttpResponse(status=204 if logged else 400)
