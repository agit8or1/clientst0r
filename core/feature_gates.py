"""Whole-module switches enforced at the URL layer.

`reports_enabled` and `secure_notes_enabled` (Settings → Features) were
saved but read by nothing until the development branch after v3.17.659.
They now gate their module:

  * every route of the module 404s while the switch is off (wrapped once in
    the module's urls.py with `gate_patterns`, so a route added later is
    covered too);
  * the menu entries, quick actions and shortcut pins that lead there are
    hidden (they read the same flag from the context processor);
  * background jobs of the module skip their run (run_scheduled_reports).

Both default to on, and migration core 0085 sets them on for existing
installs, so an upgrade changes nothing until an administrator turns one
off. If the settings row cannot be read the module stays available — the
same fail-open default the context processor uses for these toggles.
"""
from functools import wraps

from django.http import Http404
from django.urls import URLPattern, URLResolver


def feature_on(field):
    try:
        from core.models import SystemSetting
        return bool(getattr(SystemSetting.get_settings(), field, True))
    except Exception:
        return True


def require_feature(field):
    """View decorator: 404 while SystemSetting.<field> is off."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not feature_on(field):
                raise Http404('This module is turned off.')
            return view(request, *args, **kwargs)
        wrapped.feature_gate = field
        return wrapped
    return decorator


def gate_patterns(patterns, field, only=None, exclude=()):
    """Wrap views in `patterns` (recursing into includes) with
    `require_feature(field)`: every one, or only the URL names in `only`.
    URL names in `exclude` are left alone."""
    for p in patterns:
        if isinstance(p, URLResolver):
            gate_patterns(p.url_patterns, field, only, exclude)
        elif (isinstance(p, URLPattern) and p.name not in exclude
              and (only is None or p.name in only)):
            if getattr(p.callback, 'feature_gate', None) != field:
                p.callback = require_feature(field)(p.callback)
    return patterns
