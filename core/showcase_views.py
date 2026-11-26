"""Interface components showcase view (113.11).

Read-only: static invented sample data, no writes, no outbound calls.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import component_showcase as cs


@login_required
@require_GET
def component_showcase(request):
    """Staff-only (superusers and MSP staff); customers get a 403."""
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        raise PermissionDenied
    return render(request, 'core/component_showcase.html', {
        'sections': cs.COMPONENTS,
        'meta': cs.section_meta(),
        'themes': cs.THEMES,
        'spec_url': cs.SPEC_URL,
    })
