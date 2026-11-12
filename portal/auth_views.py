"""
Customer portal sign-in, sign-out, password reset, invitation and 2FA pages.

The portal has its own sign-in at /portal/login/ (and on the portal host
name when one is configured, core/portal_surface.py). Only customer portal
users sign in here; staff and superuser accounts are refused with the same
message as a wrong password, so the open portal sign-in never confirms that
a staff password is right. The staff sign-in (/account/login/,
accounts.views.StaffLoginView) refuses portal users and points them here.

Brute-force protection is the same as on the staff side: authenticate() runs
through django-axes (lockouts by username + IP), the 2FA token step is the
same two_factor wizard, and a locked-out portal sign-in gets the portal's own
lockout page (lockout_response, settings.AXES_LOCKOUT_CALLABLE).
"""
from __future__ import annotations

import logging
from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth import login as auth_login, views as auth_views
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.core.mail import EmailMultiAlternatives
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.template import loader
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from two_factor.forms import AuthenticationTokenForm, BackupTokenForm
from two_factor.views.core import (
    LoginView as _TwoFactorLoginView,
    QRGeneratorView as _QRGeneratorView,
    SetupCompleteView as _SetupCompleteView,
    SetupView as _SetupView,
)

from accounts.otp_views import BackupTokensView as _HashedBackupTokensView
from core import portal_surface

logger = logging.getLogger(__name__)

# Shown for a wrong password AND for a staff account's right password.
PORTAL_LOGIN_ERROR = (
    'Please enter a correct email address or username and password. '
    'This sign-in is for customer accounts; staff accounts use the staff sign-in page.'
)


def _client_ip_key(group, request):
    from core.client_ip import get_client_ip
    return get_client_ip(request) or ''


class PortalAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': PORTAL_LOGIN_ERROR,
    }

    # `request` must stay a named parameter: two_factor passes it only to
    # forms whose signature asks for it, and axes needs it to authenticate.
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['username'].label = 'Email or username'
        self.fields['username'].widget.attrs.setdefault('autocomplete', 'username')

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not portal_surface.is_portal_user(user):
            raise forms.ValidationError(PORTAL_LOGIN_ERROR, code='invalid_login')


class PortalLoginView(_TwoFactorLoginView):
    """The two_factor login wizard with the portal form, templates and
    redirects. A signed-in session is marked as a portal session."""
    template_name = 'portal/auth/login.html'
    form_list = (
        (_TwoFactorLoginView.AUTH_STEP, PortalAuthenticationForm),
        (_TwoFactorLoginView.TOKEN_STEP, AuthenticationTokenForm),
        (_TwoFactorLoginView.BACKUP_STEP, BackupTokenForm),
    )

    @classmethod
    def get_prefix(cls, request, *args, **kwargs):
        return 'portal_login'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated and portal_surface.is_portal_user(request.user):
            return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)

    def get_redirect_url(self):
        url = super().get_redirect_url()
        return portal_surface.safe_portal_next(self.request, url)

    def get_success_url(self):
        return self.get_redirect_url() or reverse('portal:ticket_list')

    def done(self, form_list, **kwargs):
        response = super().done(form_list, **kwargs)
        self.request.session['_auth_surface'] = portal_surface.PORTAL
        # two_factor sends users without a device to its own setup page when
        # `next` is an OTP view; the portal has its own.
        if response.get('Location', '') == reverse('two_factor:setup'):
            response['Location'] = reverse('portal_auth:two_factor_setup')
        return response


portal_login = PortalLoginView.as_view()


class PortalLogoutView(auth_views.LogoutView):
    next_page = reverse_lazy('portal_auth:login')
    template_name = 'portal/auth/logged_out.html'


# ---------------------------------------------------------------------------
# Password reset (self-service, portal users only)
# ---------------------------------------------------------------------------

class PortalPasswordResetForm(PasswordResetForm):
    """Sends reset links only to customer portal accounts, and only links to
    the portal. The response never says whether the address matched."""

    def get_users(self, email):
        for user in super().get_users(email):
            if portal_surface.is_portal_user(user):
                yield user

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        from core import mailer
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        path = reverse('portal_auth:password_reset_confirm',
                       kwargs={'uidb64': context['uid'], 'token': context['token']})
        request = getattr(self, '_request', None)
        context = {
            **context,
            'brand': mailer.brand_name(ss),
            'reset_url': portal_surface.portal_absolute_url(path, request),
            'login_url': portal_surface.portal_absolute_url(
                portal_surface.portal_login_path(), request),
        }
        subject = ''.join(loader.render_to_string(subject_template_name, context).splitlines())
        body = loader.render_to_string(email_template_name, context)
        from_email = mailer.default_from_email(ss) or from_email
        message = EmailMultiAlternatives(
            subject, body, from_email or None, [to_email],
            connection=mailer.get_smtp_connection(ss))
        try:
            message.send()
        except Exception:
            logger.exception('Portal password reset email to %s failed', to_email)


@method_decorator(ratelimit(key=_client_ip_key, rate='10/h', method='POST', block=False), name='post')
@method_decorator(ratelimit(key='post:email', rate='3/h', method='POST', block=False), name='post')
class PortalPasswordResetView(auth_views.PasswordResetView):
    form_class = PortalPasswordResetForm
    template_name = 'portal/auth/password_reset_form.html'
    email_template_name = 'portal/auth/password_reset_email.txt'
    subject_template_name = 'portal/auth/password_reset_subject.txt'
    success_url = reverse_lazy('portal_auth:password_reset_done')

    def form_valid(self, form):
        if getattr(self.request, 'limited', False):
            # Same answer as a normal request; nothing is sent.
            return HttpResponseRedirect(self.get_success_url())
        form._request = self.request
        return super().form_valid(form)


class PortalPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'portal/auth/password_reset_done.html'


class PortalPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'portal/auth/password_reset_confirm.html'
    success_url = reverse_lazy('portal_auth:password_reset_complete')
    post_reset_login = False

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user is not None and not portal_surface.is_portal_user(user):
            return None
        return user


class PortalPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'portal/auth/password_reset_complete.html'


# ---------------------------------------------------------------------------
# Invitation: first password (link from psa.views.portal_invite)
# ---------------------------------------------------------------------------

def portal_set_password(request, uidb64, token):
    """Token-protected page where an invited portal user sets their first
    password (Django's password-reset token, default lifetime 3 days).
    Refuses MSP staff accounts: an invitation must never reset a staff
    password."""
    from django.contrib.auth.models import User
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_str
    from django.utils.http import urlsafe_base64_decode

    template = 'portal/auth/set_password.html'
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return render(request, template, {'invalid': True})

    if portal_surface.is_msp_staff(user) or not default_token_generator.check_token(user, token):
        return render(request, template, {'invalid': True})

    if request.method == 'POST':
        pw1 = request.POST.get('password1') or ''
        pw2 = request.POST.get('password2') or ''
        if not pw1 or pw1 != pw2:
            messages.error(request, 'Passwords must match and be non-empty.')
        elif len(pw1) < 12:
            messages.error(request, 'Password must be at least 12 characters.')
        else:
            user.set_password(pw1)
            user.is_active = True
            user.save()
            # Signed in straight away; the 2FA middleware then asks for
            # enrolment on the portal's 2FA pages when 2FA is required.
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            auth_login(request, user)
            request.session['_auth_surface'] = portal_surface.PORTAL
            messages.success(request, 'Password set. You are now signed in.')
            return redirect('portal:ticket_list')

    return render(request, template, {
        'invalid': False,
        'user_email': user.email,
    })


# ---------------------------------------------------------------------------
# Two-factor enrolment on the portal
# ---------------------------------------------------------------------------

def _portal_users_only(cls):
    """Signed-in staff accounts get a short page instead of the portal's 2FA
    screens; anonymous visitors fall through to login_required."""
    original = cls.dispatch

    @wraps(original)
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not portal_surface.is_portal_user(request.user):
            return render(request, 'portal/auth/staff_account.html', status=404)
        return original(self, request, *args, **kwargs)

    cls.dispatch = dispatch
    return cls


@_portal_users_only
class PortalTwoFactorSetupView(_SetupView):
    template_name = 'portal/auth/two_factor_setup.html'
    success_url = 'portal_auth:two_factor_setup_complete'
    qrcode_url = 'portal_auth:two_factor_qr'

    @classmethod
    def get_prefix(cls, request, *args, **kwargs):
        return 'portal_setup'

    def get_redirect_url(self):
        return portal_surface.safe_portal_next(self.request, super().get_redirect_url())


@_portal_users_only
class PortalTwoFactorSetupCompleteView(_SetupCompleteView):
    template_name = 'portal/auth/two_factor_setup_complete.html'

    def get(self, request, *args, **kwargs):
        nxt = portal_surface.safe_portal_next(request, request.session.pop('next', '') or '')
        if nxt:
            return redirect(nxt)
        return super(_SetupCompleteView, self).get(request, *args, **kwargs)


@_portal_users_only
class PortalQRGeneratorView(_QRGeneratorView):
    pass


@_portal_users_only
class PortalBackupTokensView(_HashedBackupTokensView):
    template_name = 'portal/auth/backup_tokens.html'
    success_url = 'portal_auth:two_factor_backup_tokens'


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------

def _lockout_context():
    from core import security_policy
    cooloff = security_policy.lockout_cooloff()
    minutes = int(cooloff.total_seconds() // 60)
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        display = f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        display = f"{minutes} minute{'s' if minutes != 1 else ''}"
    return {'cooloff_display': display, 'failure_limit': security_policy.lockout_failure_limit()}


def portal_locked(request):
    return render(request, 'portal/auth/locked.html', _lockout_context(), status=403)


def lockout_response(request, credentials=None, *args, **kwargs):
    """settings.AXES_LOCKOUT_CALLABLE: the portal's lockout page for portal
    sign-ins, the staff lockout page (AXES_LOCKOUT_URL) for everything else."""
    from django.conf import settings
    from django.http import JsonResponse
    if request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        return JsonResponse({'detail': 'Too many failed sign-in attempts.'}, status=429)
    if portal_surface.request_surface(request) == portal_surface.PORTAL \
            and portal_surface.classify_path(request.path_info) == portal_surface.PORTAL:
        return redirect('portal_auth:locked')
    from urllib.parse import urlencode
    username = ''
    try:
        from axes.helpers import get_client_username
        username = get_client_username(request, credentials) or ''
    except Exception:
        pass
    return redirect(f"{settings.AXES_LOCKOUT_URL}?{urlencode({'username': username})}")
