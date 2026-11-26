"""The Setup Assistant's steps (Phase 96.3 core steps, 96.4 service steps).

Each step is an onboarding engine step (onboarding.registry.Step) of the
install kind. Rules every step follows:

* It writes the settings that already exist, through the save helper the
  regular settings page uses (core.settings_views.apply_*_post,
  core.modules.set_enabled, psa.routing.views.set_msp_mode,
  accounts.forms.OrganizationForm). It never keeps a copy of a setting.
* Forms start from the live values, so reopening shows what is set. Only
  fields the administrator actually changed are written; an unchanged form
  saves nothing (idempotent).
* Only the names of changed fields are stored on the session and written to
  the audit log; values, and secrets in particular, never are.
* Nothing here makes an outbound call. Connection tests stay on the pages
  that own them (SMTP "Send test", each integration's Test button).
"""
from __future__ import annotations

from django import forms
from django.urls import NoReverseMatch, reverse

from onboarding.models import OnboardingSession as S
from onboarding.registry import Step, StepError, StepForm, register_step, set_kind_steps


def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _settings():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def _on(field):
    return bool(getattr(_settings(), field, False))


def _names(changed):
    return ', '.join(f.replace('_', ' ') for f in changed)


class SetupStep(Step):
    """Install-wide: no customer needed; superusers only (the engine checks
    onboarding.access.can_open for the install kind)."""
    needs_client = False
    icon = 'fa-circle'
    #: Part of the basic (essentials only) path.
    basic = True
    #: Must be done before the review can finish.
    required = False
    #: One line of help shown above the form.
    help = ''
    body_template = ''

    @property
    def skippable(self):
        return not self.required

    def initial(self, session):
        return {}

    def saved_data(self, session, cleaned):
        # Only the names of the fields that changed; never values.
        return {'changed': list(cleaned.get('_changed') or [])}

    def configured(self, user=None):
        """True / False for the review ("configured" / "not configured"), or
        None when the step has no such state."""
        return None


def _bool_post(value):
    return 'on' if value else ''


# ---------------------------------------------------------------------------
# 1. MSP details and branding
# ---------------------------------------------------------------------------

def _timezone_choices():
    import pytz
    return [(tz, tz) for tz in pytz.common_timezones]


class MspForm(StepForm):
    site_name = forms.CharField(label='Site name', max_length=255,
                                help_text='Shown in the browser title and in e-mails.')
    custom_company_name = forms.CharField(
        label='Your company name', max_length=255, required=False,
        help_text='Replaces the product name in the top bar. Leave empty to keep it.')
    site_url = forms.URLField(
        label='Public address of this server', max_length=200, assume_scheme='https',
        help_text='The address people use, for example https://msp.example.com. Links in e-mails and '
                  'the customer portal use it.')
    default_timezone = forms.ChoiceField(label='Time zone', choices=(),
                                         help_text='The default for new users and schedules.')
    clear_logo = forms.BooleanField(label='Remove the current logo', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['default_timezone'].choices = _timezone_choices()


class MspStep(SetupStep):
    key = 'setup_msp'
    title = 'MSP details and branding'
    summary = 'Your company name, the public address of this server, time zone and logo.'
    icon = 'fa-building'
    required = True
    form_class = MspForm
    body_template = 'core/setup_assistant/steps/msp.html'
    FIELDS = ('site_name', 'custom_company_name', 'site_url', 'default_timezone')

    def initial(self, session):
        ss = _settings()
        return {f: getattr(ss, f) for f in self.FIELDS}

    def context(self, session, user=None):
        ss = _settings()
        return {'has_logo': bool(ss.custom_logo), 'settings_url': _url('core:settings_general')}

    def apply(self, session, cleaned, user, request=None):
        from django.core.exceptions import ValidationError

        from core.image_safety import sanitize_image
        from core.settings_views import apply_identity_post
        ss = _settings()
        changed = [f for f in self.FIELDS if (cleaned.get(f) or '') != (getattr(ss, f) or '')]
        files = {}
        upload = request.FILES.get('custom_logo') if request is not None else None
        if upload:
            try:
                files['custom_logo'] = sanitize_image(
                    upload, max_bytes=2 * 1024 * 1024, max_edge=800,
                    allowed=frozenset({'PNG', 'JPEG', 'WEBP', 'GIF'}))
            except ValidationError as exc:
                raise StepError(' '.join(exc.messages))
            changed.append('custom_logo')
        elif cleaned.get('clear_logo') and ss.custom_logo:
            changed.append('custom_logo')
        cleaned['_changed'] = changed
        if not changed:
            return 'Reviewed; nothing changed'
        post = {f: cleaned.get(f) or '' for f in self.FIELDS}
        post['clear_logo'] = _bool_post(cleaned.get('clear_logo'))
        apply_identity_post(ss, post, files)
        ss.updated_by = user
        ss.save()
        return f'Saved {_names(changed)}'

    def configured(self, user=None):
        ss = _settings()
        return bool((ss.site_url or '').strip() and (ss.site_name or '').strip())


# ---------------------------------------------------------------------------
# 2. Administrator security
# ---------------------------------------------------------------------------

# Which way is stricter for each Security setting. The assistant accepts a
# change only when the new value is at least as strict as the shipped
# default; anything looser is left to Settings → Security.
STRICTER = {
    'session_idle_timeout_minutes': 'lower',
    'session_timeout_minutes': 'lower',
    'password_min_length': 'higher',
    'failed_login_attempts': 'lower',
    'lockout_duration_minutes': 'higher',
}
SECURITY_LABELS = {
    'require_2fa': ('Require two-factor sign-in for everyone',
                    'On by default. Every account must enrol an authenticator before using the app.'),
    'session_idle_timeout_minutes': ('Sign out after this many idle minutes',
                                     'Shorter is safer on shared desks; longer means fewer sign-ins.'),
    'session_timeout_minutes': ('Longest session, in minutes',
                                'A session ends after this long even when in use.'),
    'password_min_length': ('Minimum password length',
                            'Applies to new and changed passwords.'),
    'password_require_special': ('Passwords need a special character', ''),
    'failed_login_attempts': ('Lock an account after this many failed sign-ins',
                              'Fewer attempts slows password guessing.'),
    'lockout_duration_minutes': ('Lockout length, in minutes', ''),
}


class SecurityForm(StepForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core import security_policy
        self.effective = security_policy.describe()
        fields = {}
        for key, item in security_policy.ITEMS.items():
            label, help_text = SECURITY_LABELS.get(key, (key.replace('_', ' '), ''))
            if isinstance(item.default, bool):
                f = forms.BooleanField(label=label, required=False, help_text=help_text)
            else:
                f = forms.IntegerField(label=label, min_value=item.minimum, max_value=item.maximum,
                                       help_text=help_text)
            if self.effective[key]['locked']:
                f.disabled = True
                f.help_text = (help_text + ' ' if help_text else '') + \
                    f'Set by the {self.effective[key]["env"]} environment variable on the server.'
            fields[key] = f
        self.fields.update(fields)
        # StepForm styled the fields that existed before these were added.
        for field in self.fields.values():
            w = field.widget
            css = w.attrs.get('class', '')
            if 'form-' not in css:
                w.attrs['class'] = (css + (' form-check-input' if isinstance(w, forms.CheckboxInput)
                                           else ' form-control')).strip()

    def clean(self):
        from core import security_policy
        data = super().clean()
        changed = []
        for key, item in security_policy.ITEMS.items():
            if self.effective[key]['locked'] or key not in data or data[key] is None:
                continue
            current = self.effective[key]['value']
            new = data[key]
            if new == current:
                continue
            if isinstance(item.default, bool):
                if item.default and not new:
                    self.add_error(key, 'The Setup Assistant never turns this off. Settings → Security '
                                        'can, after explaining what that changes.')
                    continue
            else:
                way = STRICTER.get(key)
                if (way == 'lower' and new > item.default) or (way == 'higher' and new < item.default):
                    self.add_error(key, f'Looser than the default ({item.default}). The Setup Assistant only '
                                        'tightens security; Settings → Security can loosen it.')
                    continue
            changed.append(key)
        data['_changed'] = changed
        return data


class SecurityStep(SetupStep):
    key = 'setup_security'
    title = 'Administrator security'
    summary = ('Two-factor sign-in, recovery codes, the installer\'s password and the session policy. '
               'The assistant can tighten these settings, never loosen them.')
    icon = 'fa-shield-halved'
    required = True
    form_class = SecurityForm
    body_template = 'core/setup_assistant/steps/security.html'

    def initial(self, session):
        from core import security_policy
        return {k: v['value'] for k, v in security_policy.describe().items()}

    def context(self, session, user=None):
        from django_otp import user_has_device

        from core import readiness
        return {
            'has_device': bool(user is not None and user_has_device(user)),
            'default_password': bool(user is not None and readiness.default_password_in_use(user)),
            'password_url': _url('accounts:password_change'),
            'two_factor_url': _url('two_factor:profile'),
            'backup_tokens_url': _url('two_factor:backup_tokens'),
            'settings_url': _url('core:settings_security'),
        }

    def apply(self, session, cleaned, user, request=None):
        from core import readiness, security_policy
        from core.settings_views import apply_security_post
        if readiness.default_password_in_use(user):
            raise StepError('Your account still uses the installer\'s default password. Change it first '
                            '(the link is above), then save this step.')
        changed = list(cleaned.get('_changed') or [])
        if not changed:
            return 'Reviewed; nothing changed'
        post = {}
        for key in changed:
            value = cleaned[key]
            post[key] = _bool_post(value) if isinstance(value, bool) else str(value)
        ss = _settings()
        bad = apply_security_post(ss, post, keys=set(changed))
        if bad:
            raise StepError(f'Invalid value for {bad.replace("_", " ")}.')
        ss.updated_by = user
        ss.save()
        security_policy.invalidate()
        return f'Tightened {_names(changed)}'

    def configured(self, user=None):
        from django_otp import user_has_device

        from core import readiness
        if user is None:
            return None
        return bool(user_has_device(user) and not readiness.default_password_in_use(user))


# ---------------------------------------------------------------------------
# 3. Modules
# ---------------------------------------------------------------------------

def _switchable_rows(ss):
    """Module rows the assistant may switch: SystemSetting switches managed
    on Administration → Modules, never the OPTIONAL AI ones (those keep their
    own opt-in on the AI page)."""
    from core import modules
    out = []
    for group, rows in modules.describe(ss):
        keep = [r for r in rows if r['switchable'] and not r['module'].optional_ai]
        if keep:
            out.append((group, keep))
    return out


class ModulesForm(StepForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.groups = []
        for group, rows in _switchable_rows(_settings()):
            names = []
            for r in rows:
                m = r['module']
                name = f'module_{m.key}'
                help_text = m.summary
                if r['requires']:
                    help_text += ' Needs: ' + ', '.join(x.label for x in r['requires']) + '.'
                self.fields[name] = forms.BooleanField(
                    label=m.label, required=False, help_text=help_text,
                    widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}))
                names.append(name)
            self.groups.append((group, names))


class ModulesStep(SetupStep):
    key = 'setup_modules'
    title = 'Modules'
    summary = ('Switch off the areas your team does not use; they disappear from the menus and can be '
               'switched on again any time under Administration → Modules. Every module is on by default.')
    icon = 'fa-puzzle-piece'
    basic = False
    form_class = ModulesForm
    body_template = 'core/setup_assistant/steps/modules.html'

    def initial(self, session):
        from core import modules
        ss = _settings()
        return {f'module_{r["module"].key}': modules.is_on(r['module'], ss)
                for _g, rows in _switchable_rows(ss) for r in rows}

    def context(self, session, user=None):
        return {'settings_url': _url('core:settings_modules')}

    def apply(self, session, cleaned, user, request=None):
        from core import modules
        from core.modules_views import audit_module_switch
        ss = _settings()
        wanted = {}
        for _g, rows in _switchable_rows(ss):
            for r in rows:
                m = r['module']
                want = bool(cleaned.get(f'module_{m.key}'))
                if want != modules.is_on(m, ss):
                    wanted[m] = want
        changed = []
        # Off first (dependants before what they need), then on, repeating
        # while something still waits for a dependency switched on this pass.
        for m in sorted([m for m, w in wanted.items() if not w], key=lambda m: -len(m.requires)):
            modules.set_enabled(m, ss, False, user=user)
            changed.append(m)
        pending = [m for m, w in wanted.items() if w]
        while pending:
            progress = False
            for m in list(pending):
                if not modules.missing_requirements(m, ss):
                    modules.set_enabled(m, ss, True, user=user)
                    pending.remove(m)
                    changed.append(m)
                    progress = True
            if not progress:
                missing = {x.label for m in pending for x in modules.missing_requirements(m, ss)}
                raise StepError(f'{", ".join(m.label for m in pending)} cannot be switched on while '
                                f'{", ".join(sorted(missing))} is off. Nothing was changed.')
        if request is not None:
            for m in changed:
                audit_module_switch(request, ss, m, not wanted[m], wanted[m])
        cleaned['_changed'] = [m.field for m in changed]
        if not changed:
            return 'Reviewed; nothing changed'
        return 'Switched ' + ', '.join(f'{m.label} {"on" if wanted[m] else "off"}' for m in changed)


# ---------------------------------------------------------------------------
# 4. Technicians, access groups and roles
# ---------------------------------------------------------------------------

def _staff_count():
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()
    return User.objects.filter(Q(is_superuser=True) | Q(profile__user_type='staff'),
                               is_active=True).distinct().count()


def _count(app_label, model):
    from django.apps import apps
    try:
        return apps.get_model(app_label, model).objects.count()
    except Exception:
        return 0


class TeamStep(SetupStep):
    key = 'setup_team'
    title = 'Technicians, access groups and roles'
    summary = ('Add your technicians and decide what each may do. The built-in roles (Owner, Service '
               'Manager, Level 1/2/3 Technician, Sales, Billing, Auditor) are ready to assign; access '
               'groups limit technicians to some customers.')
    icon = 'fa-users-gear'
    basic = False
    body_template = 'core/setup_assistant/steps/team.html'

    def context(self, session, user=None):
        return {
            'staff_count': _staff_count(),
            'role_count': _count('accounts', 'RoleTemplate'),
            'group_count': _count('tech_access', 'TechnicianGroup'),
            'links': [l for l in (
                ('Add a user', _url('accounts:user_create'), 'Create an account for a technician; they '
                 'set up two-factor sign-in on their first sign-in.'),
                ('Users', _url('accounts:user_list'), 'Everyone with an account, and their roles.'),
                ('Roles', _url('accounts:role_list'), 'What each role may do, permission by permission.'),
                ('Access groups', _url('accounts:access_group_list'),
                 'Which customers a group of technicians may work for.'),
            ) if l[1]],
        }

    def apply(self, session, cleaned, user, request=None):
        cleaned['_changed'] = []
        return (f'Reviewed: {_staff_count()} staff account(s), {_count("accounts", "RoleTemplate")} role(s), '
                f'{_count("tech_access", "TechnicianGroup")} access group(s)')

    def configured(self, user=None):
        return _staff_count() > 1


# ---------------------------------------------------------------------------
# 5. First customer
# ---------------------------------------------------------------------------

def _customer_qs():
    from core.models import Organization
    return Organization.objects.exclude(organization_type=Organization.TYPE_INTERNAL)


class CustomerForm(StepForm):
    name = forms.CharField(label='Customer name', max_length=255, required=False,
                           help_text='Leave empty to continue without adding one.')
    organization_type = forms.ChoiceField(label='Type of service', required=False, choices=())
    email = forms.EmailField(label='E-mail', required=False)
    phone = forms.CharField(label='Phone', max_length=50, required=False)
    website = forms.URLField(label='Website', required=False, assume_scheme='https')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Organization
        self.fields['organization_type'].choices = [
            c for c in Organization.ORGANIZATION_TYPE_CHOICES if c[0] != Organization.TYPE_INTERNAL]


class CustomerStep(SetupStep):
    key = 'setup_customer'
    title = 'First customer'
    summary = ('Add the first customer organization, or import your customers from a file or another '
               'system with Data Import.')
    icon = 'fa-users'
    form_class = CustomerForm
    body_template = 'core/setup_assistant/steps/customer.html'

    def context(self, session, user=None):
        qs = _customer_qs()
        return {
            'customer_count': qs.count(),
            'customers': list(qs.order_by('name').values_list('name', flat=True)[:5]),
            'import_url': _url('imports:import_list'),
            'onboarding_url': _url('onboarding:start') if _on('onboarding_enabled') else '',
            'lead_url': _url('crm:lead_create') if _on('crm_enabled') else '',
        }

    def apply(self, session, cleaned, user, request=None):
        from accounts.forms import OrganizationForm
        from accounts.models import Membership
        from core.models import Organization
        cleaned['_changed'] = []
        name = (cleaned.get('name') or '').strip()
        if not name:
            n = _customer_qs().count()
            return f'Reviewed: {n} customer(s)' if n else 'No customer added yet'
        if Organization.objects.filter(name__iexact=name).exists():
            return f'"{name}" already exists; nothing added'
        data = {
            'name': name,
            'organization_type': cleaned.get('organization_type') or '',
            'email': cleaned.get('email') or '',
            'phone': cleaned.get('phone') or '',
            'website': cleaned.get('website') or '',
            'country': Organization._meta.get_field('country').default,
            'is_active': 'on',
        }
        form = OrganizationForm(data)
        if not form.is_valid():
            raise StepError(' '.join(f'{form.fields[f].label if f in form.fields else ""}: {e}'.lstrip(': ')
                                     for f, errs in form.errors.items() for e in errs))
        org = form.save()
        # As on Organizations → New: the creator becomes the owner.
        Membership.objects.create(user=user, organization=org, role='owner', is_active=True)
        cleaned['_changed'] = ['organization']
        return f'Added customer "{org.name}"'

    def configured(self, user=None):
        return _customer_qs().exists()


# ---------------------------------------------------------------------------
# 6. Service desk mail
# ---------------------------------------------------------------------------

class MailForm(StepForm):
    smtp_enabled = forms.BooleanField(label='Send e-mail (notifications, invitations, ticket replies)',
                                      required=False)
    smtp_host = forms.CharField(label='SMTP server', max_length=255, required=False)
    smtp_port = forms.IntegerField(label='Port', min_value=1, max_value=65535,
                                   help_text='Usually 587 with STARTTLS, or 465 with SSL.')
    smtp_username = forms.CharField(label='User name', max_length=255, required=False)
    smtp_password = forms.CharField(
        label='Password', required=False, strip=True,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Write-only. Leave empty to keep the saved password.')
    smtp_use_tls = forms.BooleanField(label='Use STARTTLS', required=False)
    smtp_use_ssl = forms.BooleanField(label='Use SSL/TLS', required=False)
    smtp_from_email = forms.EmailField(label='From address', required=False)
    smtp_from_name = forms.CharField(label='From name', max_length=255, required=False)

    def clean(self):
        data = super().clean()
        if data.get('smtp_enabled') and not (data.get('smtp_host') or '').strip():
            self.add_error('smtp_host', 'Enter the SMTP server, or untick "Send e-mail".')
        if data.get('smtp_use_tls') and data.get('smtp_use_ssl'):
            self.add_error('smtp_use_ssl', 'Choose STARTTLS or SSL/TLS, not both.')
        return data


class MailStep(SetupStep):
    key = 'setup_mail'
    title = 'Service desk mail'
    summary = ('The outgoing mail server for notifications and ticket replies, and the mailboxes that turn '
               'incoming e-mail into tickets. Optional: without it the app works, it just sends no mail.')
    icon = 'fa-envelope'
    form_class = MailForm
    body_template = 'core/setup_assistant/steps/mail.html'
    FIELDS = ('smtp_enabled', 'smtp_host', 'smtp_port', 'smtp_username', 'smtp_use_tls', 'smtp_use_ssl',
              'smtp_from_email', 'smtp_from_name')

    def initial(self, session):
        ss = _settings()
        return {f: getattr(ss, f) for f in self.FIELDS}  # never the password

    def context(self, session, user=None):
        ss = _settings()
        ctx = {
            'password_saved': bool(ss.smtp_password),
            'test_url': _url('core:test_smtp_email'),
            'test_to': getattr(user, 'email', '') or '',
            'smtp_ready': bool(ss.smtp_enabled and ss.smtp_host),
            'settings_url': _url('core:settings_smtp'),
            'psa_on': bool(ss.psa_enabled),
        }
        if ss.psa_enabled:
            ctx['inbound_count'] = _count('psa', 'EmailIngestionConfig')
            ctx['inbound_url'] = _url('psa:email_config_list')
            ctx['inbound_new_url'] = _url('psa:email_config_create')
        return ctx

    def apply(self, session, cleaned, user, request=None):
        from core.settings_views import apply_smtp_post
        ss = _settings()
        changed = [f for f in self.FIELDS if cleaned.get(f) not in (None,) and
                   (cleaned.get(f) or '') != (getattr(ss, f) or '')]
        if cleaned.get('smtp_password'):
            changed.append('smtp_password')
        cleaned['_changed'] = changed
        if not changed:
            return 'Reviewed; nothing changed'
        post = {}
        for f in self.FIELDS:
            v = cleaned.get(f)
            post[f] = _bool_post(v) if isinstance(v, bool) else ('' if v is None else str(v))
        post['smtp_password'] = cleaned.get('smtp_password') or ''
        error = apply_smtp_post(ss, post)
        if error:
            raise StepError(error)
        ss.updated_by = user
        ss.save()
        # Names only: "smtp password" says it changed, never what to.
        return f'Saved {_names(changed)}'

    def saved_data(self, session, cleaned):
        return {'changed': list(cleaned.get('_changed') or [])}

    def configured(self, user=None):
        ss = _settings()
        return bool(ss.smtp_enabled and ss.smtp_host)


# ---------------------------------------------------------------------------
# 7. Routing and notifications
# ---------------------------------------------------------------------------

def _routing_available():
    from django.apps import apps
    if not _on('psa_enabled'):
        return False
    try:
        apps.get_model('ticket_routing', 'RoutingSettings')
    except LookupError:
        try:
            from psa.routing.models import RoutingSettings  # noqa: F401
        except Exception:
            return False
    return True


class RoutingForm(StepForm):
    routing_mode = forms.ChoiceField(
        label='Ticket routing', required=False, choices=(),
        help_text='Off: tickets wait in the queue for someone to take them (the default). Suggest only: '
                  'the rules suggest a technician, a person confirms. Automatic: the rules assign. Rules, '
                  'on-call and business hours are set on the Ticket Routing page.')
    notify_on_user_created = forms.BooleanField(label='E-mail new users their account details',
                                                required=False)
    notify_on_ssl_expiry = forms.BooleanField(label='Warn before SSL certificates expire', required=False)
    ssl_expiry_warning_days = forms.IntegerField(label='Days of warning for certificates', min_value=1,
                                                 max_value=365)
    notify_on_domain_expiry = forms.BooleanField(label='Warn before domains expire', required=False)
    domain_expiry_warning_days = forms.IntegerField(label='Days of warning for domains', min_value=1,
                                                    max_value=365)
    notify_on_password_expiry = forms.BooleanField(label='Warn before stored passwords expire', required=False)
    password_expiry_warning_days = forms.IntegerField(label='Days of warning for passwords', min_value=1,
                                                      max_value=365)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if _routing_available():
            from psa.routing.models import MODE_CHOICES
            self.fields['routing_mode'].choices = MODE_CHOICES
        else:
            del self.fields['routing_mode']


class RoutingStep(SetupStep):
    key = 'setup_routing'
    title = 'Routing and notifications'
    summary = 'Who gets new tickets, and which reminders the app e-mails. The defaults are safe to keep.'
    icon = 'fa-route'
    basic = False
    form_class = RoutingForm
    body_template = 'core/setup_assistant/steps/routing.html'

    def _fields(self):
        from core.settings_views import NOTIFICATION_DAYS, NOTIFICATION_FLAGS
        return NOTIFICATION_FLAGS + NOTIFICATION_DAYS

    def initial(self, session):
        ss = _settings()
        out = {f: getattr(ss, f) for f in self._fields()}
        if _routing_available():
            from psa.routing.models import RoutingSettings
            out['routing_mode'] = RoutingSettings.load().mode
        return out

    def context(self, session, user=None):
        return {'routing_url': _url('ticket_routing:overview') if _routing_available() else '',
                'settings_url': _url('core:settings_smtp')}

    def apply(self, session, cleaned, user, request=None):
        from core.settings_views import apply_notification_post
        ss = _settings()
        changed = [f for f in self._fields() if cleaned.get(f) is not None and cleaned.get(f) != getattr(ss, f)]
        if changed:
            post = {f: (_bool_post(cleaned[f]) if isinstance(cleaned[f], bool) else str(cleaned[f]))
                    for f in self._fields()}
            apply_notification_post(ss, post)
            ss.updated_by = user
            ss.save()
        mode = cleaned.get('routing_mode')
        if mode and _routing_available():
            from psa.routing.models import RoutingSettings
            if mode != RoutingSettings.load().mode:
                if request is None:
                    raise StepError('The routing mode can only be changed from the page.')
                from psa.routing.views import set_msp_mode
                set_msp_mode(request, mode)
                changed.append('routing_mode')
        cleaned['_changed'] = changed
        return f'Saved {_names(changed)}' if changed else 'Reviewed; nothing changed'

    def configured(self, user=None):
        if not _routing_available():
            return None
        from psa.routing.models import RoutingSettings
        return RoutingSettings.objects.filter(pk=1).exists()


# ---------------------------------------------------------------------------
# 8. Optional integrations (and OPTIONAL AI)
# ---------------------------------------------------------------------------

def integration_cards():
    """Status of each optional integration from the local database only (no
    outbound call). Every card is optional; tests run on the owning page."""
    from django.apps import apps

    def model(label, name):
        try:
            return apps.get_model(label, name)
        except LookupError:
            return None

    cards = []
    RMM = model('integrations', 'RMMConnection')
    if RMM is not None:
        qs = RMM.objects.filter(is_active=True)
        cards.append({
            'key': 'rmm', 'title': 'RMM', 'icon': 'fa-desktop',
            'text': 'Devices, alerts and remote sessions from an RMM (Rem0te, NinjaOne, Datto, ConnectWise '
                    'Automate, Tactical RMM and others). Each connection has a Test button on its page.',
            'count': qs.count(),
            'items': [{'name': c.name, 'status': c.last_sync_status or 'not synced yet',
                       'at': c.last_sync_at, 'url': _url('integrations:rmm_detail', c.pk)}
                      for c in qs.order_by('name')[:5]],
            'setup_url': _url('integrations:rmm_create'),
            'extra': [('Set up Rem0te', _url('integrations:rem0te_setup'))],
        })
    PSA = model('integrations', 'PSAConnection')
    if PSA is not None:
        qs = PSA.objects.filter(is_active=True)
        cards.append({
            'key': 'psa', 'title': 'External PSA',
            'icon': 'fa-ticket-alt',
            'text': 'Sync companies, contacts and tickets from a PSA you already use (ConnectWise Manage, '
                    'Autotask, HaloPSA and others). Not needed when you use the built-in service desk.',
            'count': qs.count(),
            'items': [{'name': c.name, 'status': c.last_sync_status or 'not synced yet',
                       'at': c.last_sync_at, 'url': _url('integrations:integration_detail', c.pk)}
                      for c in qs.order_by('name')[:5]],
            'setup_url': _url('integrations:integration_create'),
            'extra': [],
        })
    Conn = model('connect', 'Connection')
    if Conn is not None:
        cards.append({
            'key': 'connect', 'title': 'Connected applications', 'icon': 'fa-link',
            'text': 'Pair this install with another application over Agit8or Connect. Optional; nothing '
                    'here depends on it.',
            'count': Conn.objects.count(), 'items': [],
            'setup_url': _url('connect:index'), 'extra': [],
        })
    cards.append({
        'key': 'all', 'title': 'Everything else', 'icon': 'fa-plug',
        'text': 'Accounting, Microsoft 365, network controllers, distributors and more live under '
                'Administration → Integrations.',
        'count': None, 'items': [], 'setup_url': _url('integrations:integration_list'), 'extra': [],
    })
    return cards


class IntegrationsStep(SetupStep):
    key = 'setup_integrations'
    title = 'Optional integrations'
    summary = ('Connect the tools you already use. Every integration is optional and can be added later '
               'under Administration → Integrations; setup never needs one.')
    icon = 'fa-plug'
    basic = False
    body_template = 'core/setup_assistant/steps/integrations.html'

    def context(self, session, user=None):
        ss = _settings()
        return {'cards': integration_cards(), 'ai_on': bool(ss.psa_ai_enabled),
                'ai_url': _url('core:settings_ai')}

    def apply(self, session, cleaned, user, request=None):
        cleaned['_changed'] = []
        n = sum(c['count'] or 0 for c in integration_cards())
        return f'Reviewed: {n} connection(s) configured' if n else 'Reviewed: none configured (optional)'

    def configured(self, user=None):
        return any(c['count'] for c in integration_cards())


# ---------------------------------------------------------------------------
# 9. Backups and health readiness (the 96.1 readiness check)
# ---------------------------------------------------------------------------

class ReadinessStep(SetupStep):
    key = 'setup_readiness'
    title = 'Backups and health'
    summary = ('The install readiness check: backups, scheduler, disk, pending migrations, mail and the '
               'other items a new install should have. Saving runs it again.')
    icon = 'fa-clipboard-check'
    body_template = 'core/setup_assistant/steps/readiness.html'

    def context(self, session, user=None):
        from core import readiness
        checks, checked_at = readiness.latest()
        return {'checks': checks, 'checked_at': checked_at, 'summary': readiness.summary(checks),
                'backup_url': _url('core:offhost_backup'), 'status_url': _url('core:system_status')}

    def apply(self, session, cleaned, user, request=None):
        from core import readiness
        checks = readiness.run_checks()
        cleaned['_changed'] = []
        open_ = sum(1 for c in checks if not c['ok'])
        return f'Readiness checked: {open_} of {len(checks)} item(s) need attention'

    def configured(self, user=None):
        from core import readiness
        checks, _at = readiness.latest()
        return bool(checks) and not readiness.summary(checks)['open']


# ---------------------------------------------------------------------------
# 10. Review
# ---------------------------------------------------------------------------

class ReviewStep(SetupStep):
    key = 'setup_review'
    title = 'Review and finish'
    summary = 'What is configured, what was skipped, and what still needs attention.'
    icon = 'fa-flag-checkered'
    required = True
    body_template = 'core/setup_assistant/steps/review.html'

    def missing_required(self, session):
        from onboarding.models import OnboardingStepState as St
        done = set(session.step_states.filter(status=St.DONE).values_list('step_key', flat=True))
        return [s for s in ordered() if s.required and s.key != self.key and s.key not in done]

    def context(self, session, user=None):
        from onboarding.models import OnboardingStepState as St
        states = {s.step_key: s for s in session.step_states.all()}
        rows = []
        for s in ordered():
            if s.key == self.key:
                continue
            st = states.get(s.key)
            rows.append({'step': s, 'status': st.status if st else St.NOT_STARTED,
                         'note': st.notes if st else '', 'configured': s.configured(user)})
        return {'rows': rows, 'missing': self.missing_required(session)}

    def apply(self, session, cleaned, user, request=None):
        from core import readiness
        from core.models import SystemSetting
        from core.setup_assistant import set_state
        from onboarding import engine
        missing = self.missing_required(session)
        if missing:
            raise StepError('Finish the required steps first: ' + ', '.join(s.title for s in missing) + '.')
        if readiness.default_password_in_use(user):
            raise StepError('Change the installer\'s default password first (Administrator security).')
        cleaned['_changed'] = []
        set_state(SystemSetting.SETUP_COMPLETED, user=user)
        engine.complete_session(session, user)
        return 'Setup finished'


# ---------------------------------------------------------------------------

STEP_CLASSES = (MspStep, SecurityStep, ModulesStep, TeamStep, CustomerStep, MailStep, RoutingStep,
                IntegrationsStep, ReadinessStep, ReviewStep)
STEP_BY_KEY = {}


def ordered():
    from onboarding.registry import steps_for
    return steps_for(S.INSTALL)


def register():
    for cls in STEP_CLASSES:
        register_step(cls)
    set_kind_steps(S.INSTALL, [c.key for c in STEP_CLASSES])
    from onboarding.registry import get_step
    STEP_BY_KEY.clear()
    STEP_BY_KEY.update({c.key: get_step(c.key) for c in STEP_CLASSES})
