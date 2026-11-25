"""Whole-module switches enforced at the URL layer.

Every optional module has a SystemSetting boolean (Settings → Modules). Off
means:

  * every route of the module 404s (wrapped once in the module's urls.py
    with `gate_patterns`, so a route added later is covered too);
  * the menu entries, quick actions, dashboard cards and shortcut pins that
    lead there are hidden (the navigation reads the same flags from the
    context processor, and `_PermProbe` skips a link whose view is gated
    off);
  * the module's scheduled jobs are skipped (`TASK_SWITCHES`, read by
    core/management/commands/run_scheduler.py).

Turning a module off never deletes anything; turning it back on shows every
record again. Every switch is on for a new install. A switch added for a
module that used to be always available is added on, so an upgrade changes
nothing until an administrator turns it off. If the settings row cannot be
read the module stays available (fail open), except PSA, which keeps its
own fail-closed check in psa.feature_flags.
"""
from functools import wraps

from django.http import Http404
from django.urls import URLPattern, URLResolver

# Every module switch, in Settings → Modules order. The context processor
# puts each one in the template context, the navigation cache keys on them,
# and a fresh SystemSetting row has every one of them on.
MODULE_SWITCHES = (
    # Service desk
    'psa_enabled',
    'projects_enabled',
    'quotes_enabled',
    'change_management_enabled',
    'procurement_enabled',
    'security_alerts_enabled',
    'pulse_enabled',
    'client_health_enabled',
    # Sales and contracts
    'crm_enabled',
    'contracts_enabled',
    'licensing_enabled',
    # Operations
    'monitoring_enabled',
    'status_pages_enabled',
    'netconfig_enabled',
    'backup_monitoring_enabled',
    'workflows_enabled',
    'scheduling_enabled',
    'inventory_enabled',
    'vehicles_enabled',
    'field_ops_enabled',
    'onboarding_enabled',
    'webhooks_enabled',
    'reports_enabled',
    # Documentation and vault
    'global_kb_enabled',
    'diagrams_enabled',
    'readiness_enabled',
    'secure_notes_enabled',
    'locations_map_enabled',
)

# Scheduled jobs (core.models.ScheduledTask.task_type) that belong to one
# module: the scheduler skips them while the module is off. Jobs that erase
# data on a retention schedule (location history, check history, expired
# secure replies) keep running whatever the switch says.
TASK_SWITCHES = {
    'website_monitoring': 'monitoring_enabled',
    'ssl_expiry_check': 'monitoring_enabled',
    'domain_expiry_check': 'monitoring_enabled',
    'check_wans': 'monitoring_enabled',
    'network_config_backup': 'netconfig_enabled',
    'scheduling_alerts': 'scheduling_enabled',
    'vehicles_service_alerts': 'vehicles_enabled',
    'run_scheduled_reports': 'reports_enabled',
    'run_advisor': 'reports_enabled',
    'poll_security_alerts': 'security_alerts_enabled',
    'check_incident_sla_breaches': 'security_alerts_enabled',
    'recompute_exposure_scores': 'security_alerts_enabled',
    'send_security_digests': 'security_alerts_enabled',
    'poll_backup_monitoring': 'backup_monitoring_enabled',
    'sync_licenses': 'licensing_enabled',
    'licensing_alerts': 'licensing_enabled',
    'compute_health_scores': 'client_health_enabled',
    'contracts_jobs': 'contracts_enabled',
    'contracts_maintenance': 'contracts_enabled',
    'psa_run_recurring_purchases': 'procurement_enabled',
    'sync_distributors': 'procurement_enabled',
    'auto_document_field_visits': 'field_ops_enabled',
    'pulse_send_due': 'pulse_enabled',
}


def _settings_row():
    from core.models import SystemSetting
    return SystemSetting.get_settings_for_request()


def feature_on(field):
    try:
        return bool(getattr(_settings_row(), field, True))
    except Exception:
        return True


def task_allowed(task_type):
    """False while the module a scheduled job belongs to is off."""
    field = TASK_SWITCHES.get(task_type)
    return field is None or feature_on(field)


def require_feature(field):
    """View decorator: 404 while SystemSetting.<field> is off."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not feature_on(field):
                raise Http404('This module is turned off.')
            return view(request, *args, **kwargs)
        wrapped.feature_gate = field
        wrapped.feature_gates = tuple(getattr(view, 'feature_gates', ())) + (field,)
        return wrapped
    return decorator


def gate_patterns(patterns, field, only=None, exclude=()):
    """Wrap views in `patterns` (recursing into includes) with
    `require_feature(field)`: every one, or only the URL names in `only`.
    URL names in `exclude` are left alone. A name in `only` or `exclude`
    that no pattern carries is a typo and fails at import."""
    seen = set()
    _gate(patterns, field, only, exclude, seen)
    unknown = (set(only or ()) | set(exclude)) - seen
    if unknown:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(f'gate_patterns({field!r}): no URL named {sorted(unknown)}')
    return patterns


def _gate(patterns, field, only, exclude, seen):
    for p in patterns:
        if isinstance(p, URLResolver):
            _gate(p.url_patterns, field, only, exclude, seen)
        elif isinstance(p, URLPattern):
            seen.add(p.name)
            if p.name not in exclude and (only is None or p.name in only):
                if field not in getattr(p.callback, 'feature_gates', ()):
                    p.callback = require_feature(field)(p.callback)


def gates_of(func):
    """The module switches a view is gated by (outermost wrapper)."""
    return tuple(getattr(func, 'feature_gates', ()) or ())


_PATH_GATES = {}


def path_gates(path):
    """The module switches the view serving `path` is gated by. Cached per
    path; the URLconf does not change at run time."""
    hit = _PATH_GATES.get(path)
    if hit is not None:
        return hit
    from django.urls import Resolver404, resolve
    try:
        gates = gates_of(resolve(path).func)
    except Resolver404:
        gates = ()
    except Exception:
        return ()
    if len(_PATH_GATES) < 8192:
        _PATH_GATES[path] = gates
    return gates


def path_enabled(path, flags=None):
    """False when `path` is served by a module that is turned off. `flags`
    is a mapping (a template context) that may already hold the switches;
    anything missing is read from SystemSetting."""
    for field in path_gates((path or '').split('?', 1)[0]):
        if flags is not None and field in flags:
            if not flags.get(field):
                return False
        elif not feature_on(field):
            return False
    return True


def flags_from(settings_row):
    """{switch: bool} for every module switch (fail open on a missing row)."""
    if settings_row is None:
        return {name: True for name in MODULE_SWITCHES}
    return {name: bool(getattr(settings_row, name, True)) for name in MODULE_SWITCHES}
