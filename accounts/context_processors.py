"""
Context processors for accounts app
"""

def user_theme(request):
    """
    Add user theme and background to template context.
    """
    theme = 'default'
    background_mode = 'none'
    background_url = None

    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        profile = request.user.profile
        theme = profile.theme
        background_mode = profile.background_mode

        # Handle background image based on mode
        if background_mode == 'custom' and profile.background_image:
            background_url = profile.background_image.url
        elif background_mode == 'random':
            # Get a random background from the gallery
            import random
            from django.conf import settings
            import os

            bg_dir = os.path.join(settings.STATIC_ROOT or settings.BASE_DIR / 'static', 'images/backgrounds')
            if os.path.exists(bg_dir):
                backgrounds = [f for f in os.listdir(bg_dir) if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                if backgrounds:
                    random_bg = random.choice(backgrounds)
                    background_url = f'/static/images/backgrounds/{random_bg}'

    return {
        'user_theme': theme,
        'user_background_mode': background_mode,
        'user_background_url': background_url,
    }
