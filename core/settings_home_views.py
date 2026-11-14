"""The settings center: Administration's landing page.

The ten settings categories (core.navigation.SETTINGS_CATEGORIES) as
compact, searchable cards, each listing the pages this user may open. The
list is navigation.settings_workspace() — every link already passed its
page's own check — so the page shows nothing a user could not open anyway,
and a user with no settings page at all is refused.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

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
    return render(request, 'core/settings_home.html', {
        'categories': categories,
        'page_count': sum(len(c['tabs']) for c in categories),
    })
