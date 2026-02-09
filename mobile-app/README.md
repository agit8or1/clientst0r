# HuduGlue Mobile App

React Native mobile application for HuduGlue IT Documentation Platform.

## Features

- 📱 **Cross-Platform** - Works on iOS and Android
- 🔐 **Secure Authentication** - Token-based auth with secure storage
- 📊 **Dashboard** - Quick overview of your IT environment
- 💼 **Asset Management** - View and manage assets on the go
- 🔒 **Password Vault** - Secure password access
- 📚 **Documentation** - Access knowledge base articles
- 🌙 **Dark Mode** - Beautiful dark theme optimized for mobile
- 🔄 **Real-time Sync** - GraphQL API integration
- 📴 **Offline Support** - Works with cached data (coming soon)

## Prerequisites

- Node.js 18+ and npm
- Expo CLI (`npm install -g expo-cli`)
- iOS Simulator (Mac only) or Android Studio
- HuduGlue backend running with GraphQL API enabled

## Installation

1. **Install dependencies:**
   ```bash
   cd mobile-app
   npm install
   ```

2. **Configure API URL:**

   Edit `app.json` and set your HuduGlue server URL:
   ```json
   "extra": {
     "apiUrl": "https://your-huduglue-server.com",
     "graphqlUrl": "https://your-huduglue-server.com/api/v2/graphql/"
   }
   ```

3. **Start the development server:**
   ```bash
   npm start
   ```

4. **Run on device/simulator:**

   - **iOS**: Press `i` in terminal or run `npm run ios`
   - **Android**: Press `a` in terminal or `npm run android`
   - **Web**: Press `w` in terminal or run `npm run web`

## Development

### Project Structure

```
mobile-app/
├── App.js                 # Main app component
├── app.json              # Expo configuration
├── package.json          # Dependencies
├── src/
│   ├── contexts/         # React contexts (Auth)
│   ├── navigation/       # Navigation configuration
│   ├── screens/          # Screen components
│   ├── components/       # Reusable components
│   ├── graphql/          # GraphQL queries/mutations
│   └── utils/            # Utility functions
└── assets/               # Images, fonts, icons
```

### Key Technologies

- **React Native 0.74** - Mobile framework
- **Expo ~51.0** - Development platform
- **React Navigation 6** - Navigation library
- **React Native Paper 5** - Material Design UI components
- **Apollo Client 3** - GraphQL client
- **Expo Secure Store** - Encrypted credential storage

### Adding New Screens

1. Create screen component in `src/screens/`
2. Import in `src/navigation/AppNavigator.js`
3. Add to appropriate navigator (Tab, Stack, Drawer)

### GraphQL Queries

Add queries in `src/graphql/queries.js`:

```javascript
export const MY_QUERY = gql`
  query MyQuery {
    myData {
      field
    }
  }
`;
```

## Building for Production

### iOS

1. Configure app signing in Xcode
2. Build:
   ```bash
   expo build:ios
   ```

### Android

1. Configure keystore for signing
2. Build APK:
   ```bash
   expo build:android -t apk
   ```
3. Or build App Bundle (for Google Play):
   ```bash
   expo build:android -t app-bundle
   ```

## API Integration

The app connects to HuduGlue's GraphQL API at `/api/v2/graphql/`.

### Required Backend Setup

1. Ensure GraphQL is enabled (install `requirements-graphql.txt`)
2. CORS must allow your mobile app origin
3. API authentication token endpoint must be accessible

### Authentication Flow

1. User enters credentials on login screen
2. App calls `/api/token/` to get auth token
3. Token stored in Expo Secure Store
4. Token added to all GraphQL requests via Apollo Link

## Troubleshooting

### "Network request failed"

- Check that the API URL in `app.json` is correct
- Ensure HuduGlue backend is running and accessible
- Verify CORS settings allow mobile app origin

### "No module named graphene_django"

- Install GraphQL dependencies on backend: `pip install -r requirements-graphql.txt`
- Restart HuduGlue server

### iOS build issues

- Clear cache: `rm -rf node_modules && npm install`
- Clear Expo cache: `expo start -c`
- Update CocoaPods: `cd ios && pod install`

## Features Roadmap

- [ ] Push notifications for monitors and alerts
- [ ] Biometric authentication (Face ID / Fingerprint)
- [ ] Offline mode with local cache
- [ ] QR code scanner for asset tagging
- [ ] File upload support
- [ ] Dark/Light theme toggle
- [ ] Password generator
- [ ] Quick actions from home screen
- [ ] Widget support

## Contributing

See main HuduGlue repository for contribution guidelines.

## License

MIT License - Same as HuduGlue parent project
