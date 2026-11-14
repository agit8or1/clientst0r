"""Settings → General → Customer portal (/core/settings/portal/).

One page for everything about the customer portal that used to be spread
over Settings → General (host name), Optional modules (the four portal
feature switches), per-customer PSA settings (portal on/off) and the
firewall page (country policy, shown here read-only):

* Address: the portal host name (moved here from General, same validation
  as before: core.portal_surface.validate_portal_hostname), the effective
  portal URL and a link to the portal sign-in.
* Branding: portal name, logo, default accent colour, sign-in background
  and welcome message, support contact.
* Layout: top bar or side navigation, content width, default theme.
* Features: psa_portal_* switches (only while PSA is on).
* Customers: portal on/off for every customer, in bulk (only while PSA is on).

Superuser only, like Settings → General. Saves set `updated_by` and write an
audit entry listing the changed fields (the request is also logged by
audit.middleware, as every settings POST is).
"""
from __future__ import annotations

from django import forms
from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse

from . import portal_branding, portal_surface
from .models import FirewallCountryRule, FirewallSettings, Organization, SystemSetting

LOGO_MAX_BYTES = 2 * 1024 * 1024
BACKGROUND_MAX_BYTES = 5 * 1024 * 1024
IMAGE_FORMATS = {'PNG', 'JPEG', 'MPO', 'WEBP'}
_IMAGE_MESSAGES = {
    'type': 'Upload a PNG, JPEG or WebP image.',
}

FEATURE_FIELDS = (
    ('psa_portal_announcements_enabled', 'Announcements',
     'An announcements panel on the portal home page.'),
    ('psa_portal_voting_enabled', '"I\'m affected too" votes',
     'Portal users can mark a ticket they can see as affecting them too.'),
    ('psa_portal_escalation_enabled', 'Escalation',
     'Portal users can escalate one of their tickets.'),
    ('psa_portal_customer_approvals_enabled', 'Customer approvals',
     'Approvals flagged for the customer appear in the portal menu for portal users to decide.'),
)

BRANDING_FIELDS = (
    'portal_name', 'portal_accent_color', 'portal_login_background',
    'portal_login_background_color', 'portal_login_message',
    'portal_support_email', 'portal_support_phone', 'portal_support_url',
    'portal_navigation', 'portal_content_width', 'portal_default_theme',
)
IMAGE_FIELDS = ('portal_logo', 'portal_login_background_image')


def _is_superuser(user):
    return user.is_superuser


def _hex_or_blank(value):
    value = (value or '').strip()
    if value and not portal_branding.HEX6.match(value):
        raise ValidationError('Enter a colour as #rrggbb, for example #0f766e.')
    return value.lower()


class PortalSettingsForm(forms.Form):
    portal_hostname = forms.CharField(required=False, max_length=253)

    portal_name = forms.CharField(required=False, max_length=100)
    portal_logo = forms.FileField(required=False)
    clear_portal_logo = forms.BooleanField(required=False)
    portal_accent_custom = forms.BooleanField(required=False)
    portal_accent_color = forms.CharField(required=False, max_length=7)
    portal_login_background = forms.ChoiceField(choices=SystemSetting.PORTAL_LOGIN_BACKGROUNDS)
    portal_login_background_color = forms.CharField(required=False, max_length=7)
    portal_login_background_image = forms.FileField(required=False)
    clear_portal_login_background_image = forms.BooleanField(required=False)
    portal_login_message = forms.CharField(
        required=False, max_length=SystemSetting.PORTAL_LOGIN_MESSAGE_MAX, strip=True)
    portal_support_email = forms.EmailField(required=False, max_length=254)
    portal_support_phone = forms.CharField(required=False, max_length=40)
    portal_support_url = forms.CharField(required=False, max_length=500)

    portal_navigation = forms.ChoiceField(choices=SystemSetting.PORTAL_NAVIGATION_CHOICES)
    portal_content_width = forms.ChoiceField(choices=SystemSetting.PORTAL_CONTENT_WIDTHS)
    portal_default_theme = forms.ChoiceField(choices=SystemSetting.PORTAL_DEFAULT_THEMES)

    psa_portal_announcements_enabled = forms.BooleanField(required=False)
    psa_portal_voting_enabled = forms.BooleanField(required=False)
    psa_portal_escalation_enabled = forms.BooleanField(required=False)
    psa_portal_customer_approvals_enabled = forms.BooleanField(required=False)

    def __init__(self, *args, instance, request, **kwargs):
        self.instance = instance
        self.request = request
        super().__init__(*args, **kwargs)

    def clean_portal_hostname(self):
        if portal_surface.portal_hostname_env_locked():
            return self.instance.portal_hostname
        host, error = portal_surface.validate_portal_hostname(
            self.cleaned_data.get('portal_hostname'), self.request)
        if error:
            raise ValidationError(error)
        return host

    def clean_portal_accent_color(self):
        return _hex_or_blank(self.cleaned_data.get('portal_accent_color'))

    def clean_portal_login_background_color(self):
        return _hex_or_blank(self.cleaned_data.get('portal_login_background_color'))

    def clean_portal_support_phone(self):
        value = (self.cleaned_data.get('portal_support_phone') or '').strip()
        if value and not portal_branding.tel_href(value):
            raise ValidationError('Enter a phone number such as +1 555 010 2000 (digits, spaces, + - ( ) . and an optional "ext").')
        return value

    def clean_portal_support_url(self):
        value = (self.cleaned_data.get('portal_support_url') or '').strip()
        if value:
            try:
                URLValidator(schemes=['http', 'https'])(value)
            except ValidationError:
                raise ValidationError('Enter a full web address starting with https:// (or http://).')
        return value

    def _image(self, name, max_bytes, max_edge):
        upload = self.cleaned_data.get(name)
        if not upload:
            return None
        from .image_safety import sanitize_image
        return sanitize_image(upload, max_bytes=max_bytes, max_edge=max_edge,
                              allowed=IMAGE_FORMATS, messages=_IMAGE_MESSAGES)

    def clean_portal_logo(self):
        return self._image('portal_logo', LOGO_MAX_BYTES, 800)

    def clean_portal_login_background_image(self):
        return self._image('portal_login_background_image', BACKGROUND_MAX_BYTES, 2560)

    def clean(self):
        data = super().clean()
        if not data.get('portal_accent_custom'):
            data['portal_accent_color'] = ''
        elif 'portal_accent_color' in data and not data['portal_accent_color']:
            self.add_error('portal_accent_color', 'Pick a colour, or untick "Use my own accent colour".')
        mode = data.get('portal_login_background')
        if mode == 'color' and 'portal_login_background_color' in data \
                and not data['portal_login_background_color']:
            self.add_error('portal_login_background_color', 'Pick a background colour.')
        if mode == 'image' and 'portal_login_background_image' in self.errors:
            pass
        elif mode == 'image' and not data.get('portal_login_background_image') and (
                data.get('clear_portal_login_background_image')
                or not self.instance.portal_login_background_image):
            self.add_error('portal_login_background_image', 'Upload a background image, or choose another background.')
        return data


def _field_repr(value):
    return getattr(value, 'name', value) if value is not None else None


def _apply(form, ss, psa_on):
    """Copy the cleaned form onto `ss`; return {field: {'from', 'to'}}."""
    data = form.cleaned_data
    changed = {}

    def put(field, value):
        before = getattr(ss, field)
        if before != value:
            changed[field] = {'from': _field_repr(before), 'to': _field_repr(value)}
            setattr(ss, field, value)

    if not portal_surface.portal_hostname_env_locked():
        put('portal_hostname', data['portal_hostname'])
    for field in BRANDING_FIELDS:
        put(field, data.get(field) or ('' if field not in (
            'portal_login_background', 'portal_navigation', 'portal_content_width',
            'portal_default_theme') else getattr(ss, field)))
    for field in IMAGE_FIELDS:
        upload = data.get(field)
        if upload:
            before = getattr(ss, field).name or None
            setattr(ss, field, upload)
            changed[field] = {'from': before, 'to': 'new upload'}
        elif data.get(f'clear_{field}') and getattr(ss, field):
            changed[field] = {'from': getattr(ss, field).name, 'to': None}
            setattr(ss, field, None)
    if psa_on:
        for field, _label, _help in FEATURE_FIELDS:
            put(field, bool(data.get(field)))
    return changed


def _audit(request, changed, *, organization=None, object_type='core.SystemSetting',
           object_id=1, object_repr='Customer portal settings', action='update', description=''):
    from audit.models import AuditLog
    from .client_ip import get_client_ip
    AuditLog.log(
        user=request.user, action=action, organization=organization,
        object_type=object_type, object_id=object_id, object_repr=object_repr[:255],
        description=description or ('Updated customer portal settings: ' + ', '.join(sorted(changed))),
        ip_address=get_client_ip(request), path=request.path,
        extra_data={'changed_fields': changed},
    )


def _customers():
    """Active customers, plus any inactive one whose portal is still on."""
    from psa.models import ClientPSASettings
    on_ids = set(ClientPSASettings.objects.filter(portal_enabled=True)
                 .values_list('organization_id', flat=True))
    orgs = list(Organization.objects.filter(is_active=True).order_by('name')) + list(
        Organization.objects.filter(is_active=False, pk__in=on_ids).order_by('name'))
    return [{'org': o, 'portal_on': o.pk in on_ids} for o in orgs]


def _save_customers(request):
    from psa.models import ClientPSASettings
    try:
        ids = {int(v) for v in request.POST.getlist('org_ids')}
    except (TypeError, ValueError):
        messages.error(request, 'Nothing was changed: the customer list was not valid.')
        return
    rows = {r.organization_id: r for r in ClientPSASettings.objects.filter(organization_id__in=ids)}
    turned_on, turned_off = [], []
    with transaction.atomic():
        for org in Organization.objects.filter(pk__in=ids):
            want = f'portal_{org.pk}' in request.POST
            row = rows.get(org.pk)
            before = bool(row and row.portal_enabled)
            if want == before:
                continue
            created = row is None
            if created:
                # Same default row the per-customer PSA settings page creates.
                row = ClientPSASettings(organization=org)
            row.portal_enabled = want
            row.save()
            _audit(request, {'portal_enabled': {'from': before, 'to': want}},
                   organization=org, object_type='psa.ClientPSASettings', object_id=row.pk,
                   object_repr=f'PSA settings for {org.name}',
                   action='create' if created else 'update',
                   description=f'{"Turned on" if want else "Turned off"} the customer portal for {org.name}')
            (turned_on if want else turned_off).append(org.name)
    if turned_on or turned_off:
        parts = []
        if turned_on:
            parts.append('on for ' + ', '.join(turned_on))
        if turned_off:
            parts.append('off for ' + ', '.join(turned_off))
        messages.success(request, 'Customer portal turned ' + '; '.join(parts) + '.')
    else:
        messages.info(request, 'No customer portal switches changed.')


def _effective_url(request, ss):
    path = reverse('portal:ticket_list')
    origin = portal_surface.portal_origin()
    if origin:
        return origin + path
    site = (ss.site_url or '').strip().rstrip('/')
    return site + path if site else request.build_absolute_uri(path)


def _geoip_summary():
    fw = FirewallSettings.get_settings()
    mode = fw.portal_geoip_mode
    if mode == FirewallSettings.PORTAL_GEOIP_INHERIT:
        if fw.geoip_firewall_enabled:
            detail = (f'The staff GeoIP rules apply ({fw.get_geoip_firewall_mode_display()}).')
        else:
            detail = 'The staff GeoIP firewall is off, so no country restriction applies.'
    elif mode == FirewallSettings.PORTAL_GEOIP_OFF:
        detail = 'The portal is reachable from every country.'
    else:
        n = FirewallCountryRule.objects.filter(
            surface=FirewallCountryRule.SURFACE_PORTAL, is_active=True).count()
        detail = f'{n} active portal country rule(s).'
    return {'mode': mode, 'label': fw.get_portal_geoip_mode_display(), 'detail': detail}


@login_required
@user_passes_test(_is_superuser)
def settings_portal(request):
    ss = SystemSetting.get_settings()
    psa_on = bool(ss.psa_enabled)

    form = None
    if request.method == 'POST':
        if request.POST.get('action') == 'customers':
            if not psa_on:
                messages.error(request, 'Turn PSA on before switching the customer portal on for customers.')
            else:
                _save_customers(request)
            return redirect(reverse('core:settings_portal') + '#portal-customers')

        form = PortalSettingsForm(request.POST, request.FILES, instance=ss, request=request)
        if form.is_valid():
            changed = _apply(form, ss, psa_on)
            if changed:
                ss.updated_by = request.user
                ss.save()
                _audit(request, changed)
                messages.success(request, 'Customer portal settings saved.')
            else:
                messages.info(request, 'Nothing changed.')
            return redirect('core:settings_portal')
        messages.error(request, 'Nothing was saved. Correct the fields marked below.')

    if form is None:
        form = PortalSettingsForm(instance=ss, request=request, initial={
            'portal_hostname': ss.portal_hostname,
            'portal_accent_custom': bool(ss.portal_accent_color),
            **{f: getattr(ss, f) for f in BRANDING_FIELDS},
            **{f: getattr(ss, f) for f, _l, _h in FEATURE_FIELDS},
        })

    def value(name):
        """What the field shows: the posted value after a failed save."""
        return form[name].value() if form.is_bound else form.initial.get(name)

    env_host = django_settings.PORTAL_HOSTNAME if portal_surface.portal_hostname_env_locked() else ''
    return render(request, 'core/settings_portal.html', {
        'settings': ss,
        'form': form,
        'v': {name: value(name) for name in form.fields},
        'portal_hostname_env': env_host,
        'effective_url': _effective_url(request, ss),
        'login_url': portal_surface.portal_login_url(request),
        'psa_on': psa_on,
        'features': [{'field': f, 'label': l, 'help': h, 'on': bool(value(f))}
                     for f, l, h in FEATURE_FIELDS],
        'customers': _customers() if psa_on else [],
        'geoip': _geoip_summary(),
        'background_choices': SystemSetting.PORTAL_LOGIN_BACKGROUNDS,
        'navigation_choices': SystemSetting.PORTAL_NAVIGATION_CHOICES,
        'width_choices': SystemSetting.PORTAL_CONTENT_WIDTHS,
        'theme_choices': SystemSetting.PORTAL_DEFAULT_THEMES,
        'message_max': SystemSetting.PORTAL_LOGIN_MESSAGE_MAX,
        'logo_max_mb': LOGO_MAX_BYTES // (1024 * 1024),
        'background_max_mb': BACKGROUND_MAX_BYTES // (1024 * 1024),
        'current_tab': 'portal',
    })
