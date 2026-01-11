"""
2FA enforcement middleware
"""
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from django_otp import user_has_device


class Enforce2FAMiddleware:
    """
    Enforce or encourage 2FA enrollment for users.

    When REQUIRE_2FA=True: Forces 2FA enrollment (cannot be skipped)
    When REQUIRE_2FA=False: Prompts for 2FA enrollment once per session (can be dismissed)
    """
    ALLOWED_PATHS = [
        '/account/login/',
        '/account/logout/',
        '/account/two_factor/',
        '/admin/login/',
        '/static/',
        '/media/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for allowed paths
        if any(request.path.startswith(path) for path in self.ALLOWED_PATHS):
            return self.get_response(request)

        # Check if user has 2FA device configured
        if not user_has_device(request.user):
            setup_url = reverse('two_factor:setup')

            if settings.REQUIRE_2FA:
                # REQUIRED: Force redirect to 2FA setup (cannot skip)
                if request.path != setup_url:
                    return redirect(setup_url)
            else:
                # OPTIONAL: Prompt once per session, can be dismissed
                # Check if we've already prompted in this session
                if not request.session.get('2fa_prompted', False):
                    # Mark as prompted so we don't keep redirecting
                    request.session['2fa_prompted'] = True

                    # Only redirect if not already on setup page
                    if request.path != setup_url:
                        # Add a flag to indicate this is optional
                        request.session['2fa_optional'] = True
                        return redirect(setup_url)

        response = self.get_response(request)
        return response
