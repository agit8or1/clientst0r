"""
Context processors for accounts app
"""

def user_theme(request):
    """
    Add user theme to template context.
    """
    theme = 'default'

    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        theme = request.user.profile.theme

    return {
        'user_theme': theme,
    }
