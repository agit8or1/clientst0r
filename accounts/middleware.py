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

        # Skip 2FA for Azure AD authenticated users (SSO is already secure)
        # FIX: Add audit logging for 2FA bypass
        if request.session.get('azure_ad_authenticated', False):
            # Log Azure AD 2FA bypass (once per session to avoid spam)
            if not request.session.get('azure_2fa_bypass_logged', False):
                from audit.models import AuditLog
                try:
                    AuditLog.objects.create(
                        user=request.user,
                        username=request.user.username,
                        action='azure_ad_2fa_bypass',
                        description=f'User authenticated via Azure AD SSO - 2FA requirement bypassed',
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                    )
                    request.session['azure_2fa_bypass_logged'] = True
                except Exception:
                    pass  # Don't break authentication flow if logging fails

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
