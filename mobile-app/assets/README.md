# Mobile App Assets

This directory contains app icons, splash screens, and other assets.

## Required Assets

To fully configure the mobile app, you'll need to create these assets:

### App Icons

- **icon.png** - 1024x1024px app icon
- **adaptive-icon.png** - 1024x1024px Android adaptive icon (foreground)
- **favicon.png** - 48x48px web favicon

### Splash Screen

- **splash.png** - 1242x2436px splash screen image

## Creating Icons

You can use the HuduGlue logo and create properly sized versions:

1. Take the main HuduGlue logo from `/static/images/`
2. Use an image editor or online tool to create proper sizes
3. Save in this directory with the filenames above

## Temporary Placeholder

Until proper icons are created, Expo will use default placeholder images. The app will still function correctly but won't have branded icons.

## Automated Icon Generation

You can use `expo-icon` to automatically generate all required sizes from a single image:

```bash
npm install -g expo-icon
expo-icon generate icon.png
```
