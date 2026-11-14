"""Find the landing pages of the URLconf: named GET pages with no path
arguments that are not an API, a form action, a portal or a public page.

Used by test_nav_reachability.py. A heuristic, hand-corrected below; it was
written for the navigation audit of 2026-11 (v3.17.676).
"""
import inspect
import re

from django.urls import URLPattern, URLResolver, get_resolver

ACTION = re.compile(
    r'(^|_)(create|add|new|edit|update|delete|remove|toggle|export|download|upload|sync|test|run|save|'
    r'approve|reject|ajax|autocomplete|bulk|set|switch|mark|ack|acknowledge|clear|start|stop|preview|'
    r'csv|pdf|ical|ics|feed|json|submit|callback|webhook|verify|confirm|revoke|reset|resend|send|copy|'
    r'clone|duplicate|move|reorder|assign|unassign|claim|merge|close|reopen|enable|disable|archive|'
    r'restore|apply|install|dismiss|snooze|pin|unpin|favorite|unfavorite|refresh|poll|status|check|'
    r'lookup|search_api|suggest|render|thumbnail|image|qr|print|raw|data|chart|ping|heartbeat|trigger|'
    r'execute|launch|connect|rollback|cancel|accept|decline|sign|generate|scan|import_run|retry|'
    r'wizard_step|step|logout|login|oauth|authorize|token|redirect|go|jump|serve|file|attachment|'
    r'stream|events|count|counts|badge|widget|partial|fragment|modal|inline|quick|zip|backup_download|'
    r'calendar_feed)(_|$)')

# Hand corrections (the name says "action" but the page is a landing page,
# or the reverse).
TO_LANDING = {'core:favorite_list', 'core:webhook_list', 'core:system_status', 'core:fail2ban_status',
              'core:settings_data_export', 'core:beta_test_admin', 'pulse:check_list',
              'assets:network_scan_import', 'hardware:import_csv', 'accounts:quick_add_menu',
              'core:beta_test_signup', 'core:install_app', 'core:download_browser_extension', 'home'}
NOT_LANDING = {'core:cleanup_old_snyk_scans', 'core:restart_application', 'core:client_switcher_search',
               'core:debug_version', 'vault:password_list_datatables', 'accounts:lockout',
               'backup_tokens_hashed', 'legacy_inbox', 'office:managed_progress', 'beta_onboarding',
               'psa:ticket_client_assets', 'hardware:model_request', 'network_discovery:collector_config'}


def _routes():
    out = {}

    def walk(patterns, prefix='', ns=None):
        for p in patterns:
            if isinstance(p, URLResolver):
                n = ns
                if p.namespace:
                    n = f'{ns}:{p.namespace}' if ns else p.namespace
                walk(p.url_patterns, prefix + str(p.pattern), n)
            elif isinstance(p, URLPattern) and p.name:
                out.setdefault(f'{ns}:{p.name}' if ns else p.name, (prefix + str(p.pattern), p.callback))
    walk(get_resolver().url_patterns)
    return out


def _post_only(cb):
    vc = getattr(cb, 'view_class', None)
    if vc is not None:
        names = getattr(vc, 'http_method_names', None)
        return not hasattr(vc, 'get') and (hasattr(vc, 'post') or (bool(names) and 'get' not in names))
    try:
        src = inspect.getsource(inspect.unwrap(cb))
    except (OSError, TypeError):
        return False
    head = src.split('def ', 1)[0]
    return bool(re.search(r'require_POST|require_http_methods\(\s*\[\s*["\']POST["\']\s*\]\)', head))


def _is_landing(name, pattern, cb):
    if name in TO_LANDING:
        return True
    if name in NOT_LANDING:
        return False
    ns = name.rsplit(':', 1)[0] if ':' in name else ''
    short = name.rsplit(':', 1)[-1]
    if ns.startswith('admin') or pattern.startswith('admin/'):
        return False
    if re.search(r'<|\(\?P|\(\?', pattern):
        return False
    if (ns in ('api', 'api_mobile', 'integration_api')
            or re.search(r'(^|/)api/|\.json|\.xml|\.ics|\.csv|\.js$', pattern)
            or short.startswith('api_') or short.endswith('_api')):
        return False
    if ns.startswith(('portal', 'contract_sign')) or pattern.startswith(('portal/', 'sign/')):
        return False
    if (ns == 'two_factor' or short in ('login', 'logout', 'health')
            or pattern.startswith(('status/', 'health', 'csp-report', 'offline', 'privacy-policy', 'logout',
                                   'public/', 's/', '.well-known', 'robots', 'manifest', 'sw.js', 'i18n'))):
        return False
    if _post_only(cb):
        return False
    return not ACTION.search(short)


def landing_routes():
    return {name for name, (pattern, cb) in _routes().items() if _is_landing(name, pattern, cb)}
