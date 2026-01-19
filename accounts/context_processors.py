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

    # Preset background mappings - High quality abstract images
    PRESET_BACKGROUNDS = {
        'abstract-1': 'https://images.unsplash.com/photo-1618005198919-d3d4b5a92ead?w=1920&q=80',  # Purple gradient
        'abstract-2': 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=1920&q=80',  # Blue gradient
        'abstract-3': 'https://images.unsplash.com/photo-1553356084-58ef4a67b2a7?w=1920&q=80',  # Orange/coral gradient
        'abstract-4': 'https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=1920&q=80',  # Teal/green wave
        'abstract-5': 'https://images.unsplash.com/photo-1550859492-d5da9d8e45f3?w=1920&q=80',  # Pink/purple nebula
        'abstract-6': 'https://images.unsplash.com/photo-1620121692029-d088224ddc74?w=1920&q=80',  # Cyan fluid
        'abstract-7': 'https://images.unsplash.com/photo-1557682224-5b8590cd9ec5?w=1920&q=80',  # Red/orange geometric
        'abstract-8': 'https://images.unsplash.com/photo-1542281286-9e0a16bb7366?w=1920&q=80',  # Blue/teal gradient
        'abstract-9': 'https://images.unsplash.com/photo-1534796636912-3b95b3ab5986?w=1920&q=80',  # Yellow/gold gradient
        'abstract-10': 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=1920&q=80',  # Dark blue/indigo
        'abstract-11': 'https://images.unsplash.com/photo-1557672172-298e090bd0f1?w=1920&q=80',  # Magenta/purple flow
        'abstract-12': 'https://images.unsplash.com/photo-1419242902214-272b3f66ee7a?w=1920&q=80',  # Navy/dark space
    }

    background_color = None

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
        elif background_mode == 'solid_color':
            # Use solid color background
            background_color = getattr(profile, 'background_color', '#1a1a2e')
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
        'user_background_color': background_color,
    }
