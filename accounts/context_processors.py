"""
Context processors for accounts app
"""

from django.db.utils import OperationalError, ProgrammingError

from core.backgrounds import DEFAULT_COLOR, DEFAULT_PRESET, preset_url, random_url
from core.models import SystemSetting

LOCALE_LABELS = {
    'en-us': 'English (US)',
    'es':    'Spanish',
    'fr':    'French',
    'de':    'German',
    'pt-br': 'Portuguese (Brazil)',
}


def user_theme(request):
    """
    Add user theme, background, and UI preferences to template context.

    v3.17.527: the background is a two-step decision. The system-wide policy in
    SystemSetting decides *who* chooses; only when it is 'user' do we look at
    the profile at all. Everything else is enforced for every user, which is the
    point of a master setting.
    """
    theme = 'default'
    background_mode = 'none'
    background_url = None
    background_color = None
    background_locked = False
    background_locked_label = ''
    tooltips_enabled = True  # Default to enabled for non-authenticated users
    time_format = '24'

    policy, policy_settings = _background_policy()

    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        profile = request.user.profile
        theme = profile.theme
        tooltips_enabled = getattr(profile, 'tooltips_enabled', True)
        time_format = getattr(profile, 'time_format', '24')

        if policy == 'user':
            background_mode = profile.background_mode
            if background_mode == 'custom' and profile.background_image:
                background_url = profile.background_image.url
            elif background_mode == 'preset':
                background_url = preset_url(
                    getattr(profile, 'preset_background', DEFAULT_PRESET))
            elif background_mode == 'solid_color':
                background_color = getattr(profile, 'background_color', DEFAULT_COLOR)
            elif background_mode == 'random':
                background_url = random_url()

    if policy != 'user':
        background_mode, background_url, background_color = _enforced_background(
            policy, policy_settings)
        background_locked = True
        background_locked_label = dict(
            SystemSetting.BACKGROUND_POLICIES).get(policy, policy)

    # Language / locale
    user_locale_code = getattr(request, 'LANGUAGE_CODE', 'en-us') or 'en-us'
    user_locale_label = LOCALE_LABELS.get(user_locale_code, 'English (US)')

    return {
        'user_theme': theme,
        'user_background_mode': background_mode,
        'user_background_url': background_url,
        'user_background_color': background_color,
        # Set when an admin policy is in force; the profile page uses these to
        # grey out its own controls and say why.
        'background_locked': background_locked,
        'background_locked_label': background_locked_label,
        'tooltips_enabled': tooltips_enabled,
        'user_time_format': time_format,
        'user_locale_code': user_locale_code,
        'user_locale_label': user_locale_label,
    }


def background_is_locked() -> bool:
    """True when an administrator policy overrides per-user backgrounds.

    Public because the profile view needs it too: the controls render inside a
    disabled <fieldset>, which submits nothing, so the view has to preserve the
    stored values rather than let a save blank them.
    """
    policy, _ = _background_policy()
    return policy != 'user'


def _background_policy():
    """Return (policy, settings). Falls back to 'user' if settings are absent.

    Deliberately narrow except: a missing settings row (fresh install, or a
    migration that has not run yet) must not take down every page render, but a
    real error should still surface.
    """
    try:
        settings_obj = SystemSetting.get_settings()
    except (OperationalError, ProgrammingError, SystemSetting.DoesNotExist):
        return 'user', None
    return getattr(settings_obj, 'background_policy', 'user') or 'user', settings_obj


def _enforced_background(policy, settings_obj):
    """(mode, url, color) for an admin-enforced policy.

    An 'image' policy with no image uploaded yet falls back to no background
    rather than a broken one — the admin has chosen the mode but not finished.
    """
    if settings_obj is None:
        return 'none', None, None
    if policy == 'image':
        image = getattr(settings_obj, 'background_image', None)
        return ('custom', image.url, None) if image else ('none', None, None)
    if policy == 'random':
        return 'random', random_url(), None
    if policy == 'color':
        if getattr(settings_obj, 'background_color_style', 'solid') == 'preset':
            return 'preset', preset_url(settings_obj.background_preset), None
        return 'solid_color', None, settings_obj.background_color or DEFAULT_COLOR
    return 'none', None, None
