"""
Content-Security-Policy on every HTML response.

Built on Django's own CSP primitives (django.utils.csp): each request gets a
lazy nonce (`request._csp_nonce`, exposed to templates as `{{ csp_nonce }}` by
core.context_processors.csp_nonce). Inline <script> blocks carry
nonce="{{ csp_nonce }}"; the nonce is only put in the header when a template
actually used it.

Settings (config/settings.py):
  CSP_ENABLED      -- False sends no CSP header at all.
  CSP_POLICY       -- directive -> list of sources (django.utils.csp.CSP values).
  CSP_REPORT_ONLY  -- True (default) sends Content-Security-Policy-Report-Only
                      so nothing is blocked; False enforces.
  CSP_REPORT_URI   -- violation report endpoint ('' = none).

Responses that already carry a CSP header (protected file downloads set a
stricter sandbox policy) are left alone. Non-HTML responses get no header.
"""
from django.conf import settings
from django.utils.csp import CSP, LazyNonce, build_policy

REPORT_GROUP = 'csp-endpoint'


def _is_html(response):
    content_type = response.get('Content-Type', '')
    return content_type.split(';', 1)[0].strip().lower() in ('text/html', 'application/xhtml+xml')


def build_csp_header(request, response, policy=None):
    """Return (header_name, value, extra_headers) for this response."""
    config = dict(policy if policy is not None else getattr(settings, 'CSP_POLICY', {}))

    # A view that explicitly allows same-origin framing (e.g. the in-app PDF
    # preview) gets the matching frame-ancestors.
    if response.get('X-Frame-Options', '').upper() == 'SAMEORIGIN':
        config['frame-ancestors'] = [CSP.SELF]

    extra = {}
    report_uri = getattr(settings, 'CSP_REPORT_URI', '')
    if report_uri:
        config['report-uri'] = [report_uri]
        if request.is_secure():
            # Reporting API (Chromium) wants an absolute https endpoint;
            # Firefox/Safari keep using report-uri.
            config['report-to'] = [REPORT_GROUP]
            extra['Reporting-Endpoints'] = f'{REPORT_GROUP}="{request.build_absolute_uri(report_uri)}"'

    header = CSP.HEADER_REPORT_ONLY if getattr(settings, 'CSP_REPORT_ONLY', True) else CSP.HEADER_ENFORCE
    return str(header), build_policy(config, getattr(request, '_csp_nonce', None)), extra


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request._csp_nonce = LazyNonce()
        response = self.get_response(request)

        if not getattr(settings, 'CSP_ENABLED', True):
            return response
        if CSP.HEADER_ENFORCE in response or CSP.HEADER_REPORT_ONLY in response:
            return response  # the view set its own (stricter) policy
        if not _is_html(response):
            return response

        header, value, extra = build_csp_header(request, response)
        if value:
            response[header] = value
            for name, val in extra.items():
                response[name] = val
        return response
