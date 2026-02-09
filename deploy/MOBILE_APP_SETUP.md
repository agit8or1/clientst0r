# Mobile App Setup Guide

Complete guide for setting up and deploying the HuduGlue mobile apps for iOS and Android.

## Overview

HuduGlue includes a native React Native mobile application that provides full access to your IT documentation platform on iOS and Android devices.

**Key Features:**
- Native performance on iOS and Android
- Secure token-based authentication
- Real-time data sync via GraphQL
- Offline-capable (coming soon)
- Dark mode optimized UI
- Biometric authentication support (coming soon)

## Prerequisites

### Backend Requirements

1. **HuduGlue v2.66.0+** installed and running
2. **GraphQL API enabled** - Required for mobile app
3. **HTTPS enabled** - Recommended for production (mobile apps require secure connections)

### Development Requirements

To develop or build the mobile app, you need:

1. **Node.js 18+** and npm
2. **Expo CLI**: `npm install -g expo-cli`
3. **Development environment:**
   - **iOS**: Mac with Xcode 14+
   - **Android**: Android Studio with SDK 33+
   - **Testing**: iOS Simulator or Android Emulator

## Backend Setup

### 1. Install GraphQL Dependencies

The mobile app requires the GraphQL API to be enabled on your HuduGlue backend.

```bash
cd ~/huduglue
source venv/bin/activate
pip install -r requirements-graphql.txt
sudo systemctl restart huduglue-gunicorn.service
```

### 2. Configure CORS

The GraphQL API is already configured to allow mobile app origins:
- `http://localhost:19006` (Expo default)
- `http://localhost:8081` (React Native)

For production, add your mobile app's production URLs to `config/settings.py`:

```python
CORS_ALLOWED_ORIGINS = [
    # ... existing origins ...
    "https://your-mobile-app-domain.com",
]
```

### 3. Verify GraphQL API

Test that the GraphQL API is accessible:

```bash
curl -X POST http://localhost:8000/api/v2/graphql/ \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { queryType { name } } }"}'
```

You should see a JSON response with schema information.

## Mobile App Setup

### 1. Install Dependencies

```bash
cd ~/huduglue/mobile-app
npm install
```

This will install all required packages including:
- React Native and Expo
- Apollo Client for GraphQL
- React Navigation
- React Native Paper (UI components)

### 2. Configure API Endpoint

Edit `mobile-app/app.json` and update the API URLs:

```json
{
  "expo": {
    "extra": {
      "apiUrl": "https://your-huduglue-server.com",
      "graphqlUrl": "https://your-huduglue-server.com/api/v2/graphql/"
    }
  }
}
```

**Development:** Use `http://YOUR_LOCAL_IP:8000` (not localhost - phones need real IP)
**Production:** Use your public HTTPS URL

### 3. Create App Icons

The mobile app needs branded icons. You can:

**Option A: Use existing HuduGlue logo**
```bash
cd mobile-app/assets
# Copy and resize your logo to create:
# - icon.png (1024x1024)
# - adaptive-icon.png (1024x1024)
# - splash.png (1242x2436)
```

**Option B: Auto-generate from a single image**
```bash
npm install -g expo-icon
cd mobile-app
expo-icon generate path/to/your-logo.png
```

## Running the App

### Development Mode

Start the Expo development server:

```bash
cd ~/huduglue/mobile-app
npm start
```

This opens the Expo DevTools in your browser. From here you can:

- Press `i` to run on iOS Simulator
- Press `a` to run on Android Emulator
- Scan QR code with Expo Go app on physical device

### iOS Simulator

**Requirements:** Mac with Xcode installed

```bash
npm run ios
```

This will:
1. Build the app
2. Start iOS Simulator
3. Install and launch the app

### Android Emulator

**Requirements:** Android Studio with emulator set up

```bash
npm run android
```

This will:
1. Build the app
2. Start Android Emulator (if not running)
3. Install and launch the app

### Physical Device Testing

**Option 1: Expo Go App (Easiest)**

1. Install "Expo Go" from App Store or Play Store
2. Run `npm start` in mobile-app directory
3. Scan the QR code with your phone
4. App loads and connects to your dev server

**Option 2: Development Build**

For testing features not supported by Expo Go (like biometrics):

```bash
# iOS
expo build:ios -t simulator

# Android
expo build:android -t apk
```

## Building for Production

### iOS App Store

1. **Join Apple Developer Program** ($99/year)

2. **Configure app signing:**
   ```bash
   cd mobile-app
   expo build:ios
   ```

3. Follow prompts to:
   - Choose credentials (let Expo manage or provide your own)
   - Select distribution method
   - Wait for build to complete

4. **Download IPA and upload to App Store Connect**

### Google Play Store

1. **Create Google Play Developer account** ($25 one-time)

2. **Generate upload keystore:**
   ```bash
   cd mobile-app
   expo build:android -t app-bundle
   ```

3. Follow prompts to:
   - Generate or provide keystore
   - Wait for build to complete

4. **Download AAB and upload to Play Console**

### Alternative: Standalone APK

For distribution outside app stores:

```bash
expo build:android -t apk
```

Download and distribute the APK directly.

## App Configuration

### Environment Variables

Create `mobile-app/.env` for environment-specific settings:

```bash
API_URL=https://your-server.com
GRAPHQL_URL=https://your-server.com/api/v2/graphql/
ENABLE_DEV_TOOLS=false
```

### Feature Flags

Edit `App.js` to enable/disable features:

```javascript
const FEATURES = {
  biometrics: true,
  offline: false,  // Coming soon
  pushNotifications: false,  // Coming soon
};
```

## Troubleshooting

### "Network request failed"

**Problem:** App can't connect to backend

**Solutions:**
1. Check API URL in `app.json`
2. Ensure backend is running: `sudo systemctl status huduglue-gunicorn`
3. Verify CORS settings allow mobile app origin
4. On physical device, use real IP not localhost
5. Check firewall allows connections

### "No module named 'graphene_django'"

**Problem:** GraphQL not installed on backend

**Solution:**
```bash
cd ~/huduglue
source venv/bin/activate
pip install -r requirements-graphql.txt
sudo systemctl restart huduglue-gunicorn.service
```

### App crashes on startup

**Solutions:**
1. Clear Expo cache: `expo start -c`
2. Clear node modules: `rm -rf node_modules && npm install`
3. Check console for errors
4. Verify all dependencies installed correctly

### iOS build fails

**Solutions:**
1. Update Xcode to latest version
2. Clear derived data: `rm -rf ~/Library/Developer/Xcode/DerivedData`
3. Update CocoaPods: `sudo gem install cocoapods`
4. Clean and rebuild

### Android build fails

**Solutions:**
1. Update Android SDK in Android Studio
2. Clear Gradle cache: `cd android && ./gradlew clean`
3. Verify Java version (should be 11 or 17)
4. Check Android SDK path in environment variables

## Security Considerations

### Production Checklist

- [ ] **HTTPS only** - Never use HTTP in production
- [ ] **Certificate pinning** - Consider implementing SSL pinning
- [ ] **Token storage** - Tokens stored in Expo Secure Store (encrypted)
- [ ] **Biometric auth** - Enable biometric authentication for sensitive data
- [ ] **Code obfuscation** - Consider ProGuard/R8 for Android
- [ ] **API rate limiting** - Ensure backend has rate limiting enabled
- [ ] **Session timeout** - Implement automatic logout after inactivity

### Network Security

- Use HTTPS for all API calls
- Validate SSL certificates
- Implement certificate pinning for production
- Never log sensitive data (passwords, tokens)

## Maintenance

### Updating the App

When HuduGlue backend is updated:

1. Check for API changes in release notes
2. Update mobile app to match new API
3. Test all features
4. Build and deploy new version

### Over-the-Air Updates

Expo supports OTA updates for JavaScript changes:

```bash
expo publish
```

Users get updates automatically without app store approval.

**Note:** Native code changes (dependencies, permissions) require full rebuild and app store submission.

## Support

### Getting Help

1. Check mobile app logs: Expo DevTools console
2. Check backend logs: `/var/log/itdocs/gunicorn-error.log`
3. Review GraphQL errors in browser DevTools (Network tab)
4. File issues: https://github.com/agit8or1/huduglue/issues

### Documentation

- Main README: `/home/administrator/README.md`
- Mobile app README: `/home/administrator/mobile-app/README.md`
- Expo docs: https://docs.expo.dev/
- React Native docs: https://reactnative.dev/

## Roadmap

Planned features for future releases:

- [ ] Offline mode with local caching
- [ ] Push notifications for alerts
- [ ] Biometric authentication
- [ ] QR code scanner for asset tagging
- [ ] File upload from camera
- [ ] Dark/Light theme toggle
- [ ] iPad/Tablet optimized layout
- [ ] Apple Watch companion app
- [ ] Android Wear support
- [ ] Share Sheet integration
- [ ] Home screen widgets

## License

MIT License - Same as HuduGlue parent project
