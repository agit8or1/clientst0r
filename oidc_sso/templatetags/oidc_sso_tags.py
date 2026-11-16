from django import template

register = template.Library()


@register.inclusion_tag('oidc_sso/_login_buttons.html', takes_context=True)
def oidc_login_buttons(context):
    """'Sign in with <provider>' for every enabled provider (none: nothing)."""
    from oidc_sso.models import OIDCProvider
    request = context.get('request')
    next_url = ''
    if request is not None:
        next_url = request.GET.get('next', '')
    try:
        providers = list(OIDCProvider.objects.filter(enabled=True).only('name', 'slug'))
    except Exception:  # table missing before migrate: never break the login page
        providers = []
    return {'providers': providers, 'next': next_url}


@register.inclusion_tag('oidc_sso/_stepup_buttons.html', takes_context=True)
def oidc_stepup_buttons(context, next_url=''):
    """'Confirm with <provider>' for providers the signed-in user has linked."""
    from oidc_sso.models import OIDCProvider
    request = context.get('request')
    user = getattr(request, 'user', None)
    providers = []
    if user is not None and user.is_authenticated:
        try:
            providers = list(OIDCProvider.objects.filter(enabled=True, identities__user=user).distinct())
        except Exception:
            providers = []
    return {'providers': providers, 'next': next_url or (request.get_full_path() if request else ''),
            'csrf_token': context.get('csrf_token')}


@register.inclusion_tag('oidc_sso/_user_identities.html', takes_context=True)
def oidc_user_identities(context, viewed_user):
    """Admin user page: the user's linked SSO accounts (pre-link / unlink on
    the provider settings page)."""
    from oidc_sso.models import OIDCIdentity, OIDCProvider
    from oidc_sso.permissions import can_manage_sso
    request = context.get('request')
    try:
        if not OIDCProvider.objects.exists():
            return {'show': False}
        identities = list(OIDCIdentity.objects.filter(user=viewed_user).select_related('provider'))
    except Exception:
        return {'show': False}
    return {'show': True, 'identities': identities,
            'can_manage': can_manage_sso(getattr(request, 'user', None))}
