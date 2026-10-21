"""
CSRF failure handling (CSRF_FAILURE_VIEW).

Signing in rotates the CSRF token. If the sign-in form is submitted twice
(a double click, Enter pressed twice, a password manager submitting it), the
second copy carries the old token and Django answered with its bare
"CSRF verification failed" page, although the first copy had signed the user
in. A user who is already signed in is sent on to where they were going;
everyone else gets a page that says the form expired.
"""
from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def _safe_url(request, target):
    if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return None


def csrf_failure(request, reason=''):
    user = getattr(request, 'user', None)
    login_path = reverse(settings.LOGIN_URL)
    if (user is not None and user.is_authenticated
            and request.path.startswith(login_path)):
        target = request.GET.get('next') or request.POST.get('next')
        return redirect(_safe_url(request, target) or settings.LOGIN_REDIRECT_URL)
    if request.path.startswith(login_path):
        retry_url = request.get_full_path()
    else:
        retry_url = _safe_url(request, request.META.get('HTTP_REFERER')) or '/'
    return render(request, '403_csrf.html', {'retry_url': retry_url}, status=403)
