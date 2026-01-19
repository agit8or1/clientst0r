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

    # Preset background mappings - High quality abstract Unsplash images
    PRESET_BACKGROUNDS = {
        'abstract-1': 'https://images.unsplash.com/photo-1557672172-298e090bd0f1?w=1920&h=1080&fit=crop',  # Purple gradient
        'abstract-2': 'https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=1920&h=1080&fit=crop',  # Blue wave
        'abstract-3': 'https://images.unsplash.com/photo-1557682224-5b8590cd9ec5?w=1920&h=1080&fit=crop',  # Orange sunset
        'abstract-4': 'https://images.unsplash.com/photo-1557682268-e3955ed5d83f?w=1920&h=1080&fit=crop',  # Green aurora
        'abstract-5': 'https://images.unsplash.com/photo-1557682260-96773eb01377?w=1920&h=1080&fit=crop',  # Pink nebula
        'abstract-6': 'https://images.unsplash.com/photo-1558591710-4b4a1ae0f04d?w=1920&h=1080&fit=crop',  # Cyan fluid
        'abstract-7': 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1920&h=1080&fit=crop',  # Red geometric
        'abstract-8': 'https://images.unsplash.com/photo-1558618666-fcd25c85e535?w=1920&h=1080&fit=crop',  # Teal gradient
        'abstract-9': 'https://images.unsplash.com/photo-1558618666-d87448f5a3b8?w=1920&h=1080&fit=crop',  # Yellow light
        'abstract-10': 'https://images.unsplash.com/photo-1558618666-d14e2e3f7d0f?w=1920&h=1080&fit=crop',  # Indigo smoke
        'abstract-11': 'https://images.unsplash.com/photo-1558591710-4b4a1ae0f04c?w=1920&h=1080&fit=crop',  # Magenta flow
        'abstract-12': 'https://images.unsplash.com/photo-1558591710-4b4a1ae0f8bd?w=1920&h=1080&fit=crop',  # Navy waves
    }

    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        profile = request.user.profile
        theme = profile.theme
        background_mode = profile.background_mode

        # Handle background image based on mode
        if background_mode == 'custom' and profile.background_image:
            background_url = profile.background_image.url
        elif background_mode == 'preset':
            # Use preset abstract background
            preset_key = getattr(profile, 'preset_background', 'abstract-1')
            background_url = PRESET_BACKGROUNDS.get(preset_key, PRESET_BACKGROUNDS['abstract-1'])
        elif background_mode == 'random':
            # Get a random background from the internet
            # Using Lorem Picsum for high-quality random images
            import time

            # Use timestamp-based seed for randomization (changes every page load)
            seed = int(time.time() * 1000)

            # Lorem Picsum provides random placeholder images
            # Grayscale option for subtle backgrounds: &grayscale
            # Blur option for softer backgrounds: &blur=2
            background_url = f'https://picsum.photos/1920/1080?random={seed}'

    return {
        'user_theme': theme,
        'user_background_mode': background_mode,
        'user_background_url': background_url,
    }
