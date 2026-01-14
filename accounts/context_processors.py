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
            # Get a random background from the internet
            # Using Unsplash Source API for high-quality random images
            # Categories: nature, architecture, technology, abstract, business
            import random

            categories = ['nature', 'architecture', 'technology', 'abstract', 'business', 'minimal']
            category = random.choice(categories)

            # Use timestamp-based seed for randomization (changes every page load)
            import time
            seed = int(time.time() * 1000) % 10000

            # Unsplash Source provides random images in various categories
            background_url = f'https://source.unsplash.com/1920x1080/?{category}&sig={seed}'

    return {
        'user_theme': theme,
        'user_background_mode': background_mode,
        'user_background_url': background_url,
    }
