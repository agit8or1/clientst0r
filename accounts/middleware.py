"""
2FA enforcement middleware and language middleware
"""
import time
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from django.utils import translation
from django_otp import user_has_device


class SessionIdleTimeoutMiddleware:
    """
    Expire authenticated sessions after a period of inactivity, and after a
    maximum total length counted from the first authenticated request.

    Both limits resolve per request through core.security_policy:
    SESSION_IDLE_TIMEOUT / SESSION_COOKIE_AGE in the environment when set,
    else Settings → Security (idle timeout / maximum session length), else
    60 min / 8 h. On expiry the user is logged out and sent to the login page.
    """

    EXEMPT_PATHS = ['/account/login/', '/account/logout/', '/static/', '/media/', '/csp-report/']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not any(
            request.path.startswith(p) for p in self.EXEMPT_PATHS
        ):
            from core import security_policy
            now = time.time()
            last_activity = request.session.get('_last_activity')
            started = request.session.get('_auth_started')

            expired = bool(last_activity) and (now - last_activity) > security_policy.idle_timeout_seconds()
            if not expired and started:
                expired = (now - started) > security_policy.session_max_age_seconds()
            if expired:
                logout(request)
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.path)

            request.session['_last_activity'] = now
            if not started:
                request.session['_auth_started'] = now

        return self.get_response(request)


class UserLanguageMiddleware:
    """
    Activate the UI language saved in the user's profile.

    Runs after Enforce2FAMiddleware (and after LocaleMiddleware) so the
    authenticated user's preference always wins over the Accept-Language header.
    Language is deactivated at the end of each request so it doesn't leak
    across requests on the same thread.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                lang = request.user.profile.locale  # e.g. 'fr', 'pt-br'
                translation.activate(lang)
                request.LANGUAGE_CODE = lang
            except Exception:
                pass
        response = self.get_response(request)
        translation.deactivate()
        return response


class Enforce2FAMiddleware:
    """
    Enforce or encourage 2FA enrollment for users.

    When 2FA is required: Forces 2FA enrollment (cannot be skipped)
    Otherwise: Prompts for 2FA enrollment once per session (can be dismissed)

    "Required" resolves per request via core.security_policy.require_2fa():
    the REQUIRE_2FA environment variable when set, else Settings → Security.
    """
    ALLOWED_PATHS = [
        '/account/login/',
        '/account/logout/',
        '/account/two_factor/',
        '/admin/login/',
        '/static/',
        '/csp-report/',
    ]
    # What an authenticated-but-unverified session (user has a device, the
    # session never passed OTP) may still reach. Deliberately excludes
    # /account/two_factor/ (device management) and /admin/.
    UNVERIFIED_ALLOWED_PATHS = [
        '/account/login/',
        '/account/logout/',
        '/static/',
        '/csp-report/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _is_verified(request):
        is_verified = getattr(request.user, 'is_verified', None)
        return bool(is_verified()) if callable(is_verified) else False

    def __call__(self, request):
        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # A user with a 2FA device must have passed it in *this* session.
        # Password-only logins (e.g. the stock /admin/login/ form) leave the
        # session unverified: end it and send them through the 2FA login.
        if (not request.session.get('azure_ad_authenticated', False)
                and user_has_device(request.user)
                and not self._is_verified(request)):
            if any(request.path.startswith(path) for path in self.UNVERIFIED_ALLOWED_PATHS):
                return self.get_response(request)
            from django.contrib.auth.views import redirect_to_login
            next_url = request.get_full_path()
            logout(request)
            return redirect_to_login(next_url, reverse('two_factor:login'))

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

            from core.security_policy import require_2fa
            if require_2fa():
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


class SectionPermissionMiddleware:
    """
    Enforce the role flags `vault_view`, `docs_view` and `assets_view` on the
    staff UI, by URL prefix.

    Those flags were stored and editable on every role template but nothing
    read them. Gating the whole section here covers every list, detail, edit
    and JSON view under the prefix at once, instead of trusting each of the
    ~150 views to remember a decorator.

    The rule, with `allowed = orgs_with_perm(user, flag)`:
      * None (every customer: superusers, MSP staff whose global role grants
        the flag or who have no global role) — pass;
      * empty — the user holds the flag nowhere: 403, *unless* they are a
        customer-side user with no active membership at all. Such a user has
        no role to consult; they are left to the views' own scoping, which
        already shows them nothing org-owned (only e.g. KB articles they
        own), exactly as before this gate existed;
      * a customer is selected and isn't in `allowed` — 403;
      * otherwise pass. With no customer selected the views already scope to
        nothing / the selected org, so there is nothing more to gate.

    Runs after CurrentOrganizationMiddleware (needs request.current_organization).
    Raises PermissionDenied so Django renders the normal 403 response.
    """

    SECTIONS = (
        ('/vault/', 'vault_view'),
        ('/docs/', 'docs_view'),
        ('/assets/', 'assets_view'),
    )

    EXEMPT_PREFIXES = (
        '/vault/personal/',        # the user's own personal vault
        '/vault/api/extension/',   # token-authenticated browser extension
        '/vault/api/generate/',    # password generator utility
        '/vault/api/strength/',    # password strength utility
    )

    def __init__(self, get_response):
        self.get_response = get_response

    # Sections only MSP technicians may open. Most of /reports/ (wallboards,
    # profitability, AR aging, ticket and SLA reports, the executive
    # scorecard) aggregates every customer, and a customer's Owner role
    # grants reports_view_financial, so until v3.17.618 a customer user could
    # read other customers' figures and recent ticket subjects there.
    STAFF_ONLY_PREFIXES = ('/reports/',)

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            if request.path.startswith(self.STAFF_ONLY_PREFIXES):
                from django.core.exceptions import PermissionDenied
                from psa.visibility import is_msp_staff
                if not is_msp_staff(user):
                    raise PermissionDenied('Reports are available to MSP staff only.')
            perm = self._required_perm(request.path)
            if perm is not None:
                self._check(request, user, perm)
        return self.get_response(request)

    def _required_perm(self, path):
        if path.startswith(self.EXEMPT_PREFIXES):
            return None
        for prefix, perm in self.SECTIONS:
            if path.startswith(prefix):
                return perm
        return None

    @staticmethod
    def _has_role_anywhere(user):
        """True when some role decides this user's access: MSP staff (their
        global role) or a customer user with an active membership."""
        profile = getattr(user, 'profile', None)
        if profile is not None and getattr(profile, 'is_staff_user', lambda: False)():
            return True
        return user.memberships.filter(
            is_active=True, organization__is_active=True).exists()

    def _check(self, request, user, perm):
        from django.core.exceptions import PermissionDenied
        from accounts.permission_utils import orgs_with_perm

        allowed = orgs_with_perm(user, perm)
        if allowed is None:
            return
        if not allowed:
            if not self._has_role_anywhere(user):
                return
            raise PermissionDenied(f"Your role does not include the '{perm}' permission.")
        org = getattr(request, 'current_organization', None)
        if org is not None and org.pk not in allowed:
            raise PermissionDenied(
                f"Your role does not include the '{perm}' permission for this customer.")
