"""
2FA enforcement middleware
"""
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from django_otp import user_has_device


class Enforce2FAMiddleware:
    """
    Enforce 2FA enrollment for all users if REQUIRE_2FA is True.
    Allows access to 2FA setup pages and logout.
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
        if not settings.REQUIRE_2FA:
            return self.get_response(request)

        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for allowed paths
        if any(request.path.startswith(path) for path in self.ALLOWED_PATHS):
            return self.get_response(request)

        # Check if user has 2FA device configured
        if not user_has_device(request.user):
            # Redirect to 2FA setup
            setup_url = reverse('two_factor:setup')
            if request.path != setup_url:
                return redirect(setup_url)

        response = self.get_response(request)
        return response
