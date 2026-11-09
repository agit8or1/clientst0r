"""Edit the navbar shortcut strip (core/shortcut_strip.py)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from core import shortcut_strip
from .models import UserProfile


def _safe_next(request):
    nxt = request.POST.get('next') or request.GET.get('next') or ''
    if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return ''


@login_required
@require_http_methods(['GET', 'POST'])
def shortcut_pins_edit(request):
    """Choose up to three shortcuts. POST `pins` (repeated); each must be on
    the whitelist and currently permitted for this user. `reset` returns to
    the defaults."""
    if not shortcut_strip.strip_eligible(request.user):
        raise PermissionDenied('Shortcuts are available to MSP staff only.')
    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    available = shortcut_strip.available_for_user(request.user)
    error = None
    chosen = shortcut_strip.saved_keys(request.user)

    if request.method == 'POST':
        nxt = _safe_next(request)
        if 'reset' in request.POST:
            profile.shortcut_pins = None
            profile.save(update_fields=['shortcut_pins'])
            messages.success(request, _('Shortcuts reset to the defaults.'))
            return redirect(nxt or 'accounts:shortcut_pins_edit')
        clean, error = shortcut_strip.validate_choice(request.user, request.POST.getlist('pins'))
        if error is None:
            profile.shortcut_pins = clean
            profile.save(update_fields=['shortcut_pins'])
            messages.success(request, _('Shortcuts saved.'))
            return redirect(nxt or 'accounts:shortcut_pins_edit')
        chosen = request.POST.getlist('pins')

    chosen_set = set(chosen)
    return render(request, 'accounts/shortcut_pins_edit.html', {
        'available': [dict(item, checked=item['key'] in chosen_set) for item in available],
        'max_pins': shortcut_strip.MAX_PINS,
        'error': error,
        'next': _safe_next(request),
    }, status=400 if error else 200)
