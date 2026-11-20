"""The settings center: Administration's landing page.

The ten settings categories (core.navigation.SETTINGS_CATEGORIES) as
compact, searchable cards, each listing the pages this user may open. The
list is navigation.settings_workspace() — every link already passed its
page's own check — so the page shows nothing a user could not open anyway,
and a user with no settings page at all is refused.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core import navigation


@login_required
def settings_home(request):
    ctx = navigation.request_context(request)
    workspace = navigation.settings_workspace(ctx)
    if not workspace['categories']:
        raise PermissionDenied('No settings pages are available to you.')
    ai_on = bool(getattr(ctx['system_settings'], 'psa_ai_enabled', False))
    categories = []
    for cat in workspace['categories']:
        categories.append({**cat, 'optional_ai': cat['key'] == 'settings_ai', 'ai_on': ai_on})
    readiness_ctx = {}
    if request.user.is_superuser:
        from core import readiness
        checks, checked_at = readiness.latest()
        readiness_ctx = {'readiness': {'checks': checks, 'checked_at': checked_at,
                                       'summary': readiness.summary(checks)}}
    return render(request, 'core/settings_home.html', {
        'categories': categories,
        'page_count': sum(len(c['tabs']) for c in categories),
        **readiness_ctx,
    })


@login_required
@require_POST
def readiness_run(request):
    """Run the install readiness check (core.readiness) and return to the
    settings center. Superusers only: the result names administrators and
    install paths."""
    if not request.user.is_superuser:
        raise PermissionDenied('Only administrators can run the readiness check.')
    from core import readiness
    checks = readiness.run_checks()
    open_ = sum(1 for c in checks if not c['ok'])
    if open_:
        messages.warning(request, f'Readiness check: {open_} of {len(checks)} item(s) need attention.')
    else:
        messages.success(request, 'Readiness check: everything is ready.')
    return redirect('core:settings_home')
