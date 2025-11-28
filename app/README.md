# LyncPower User Mobile App

Capacitor-based mobile application for LyncPower EV charging stations - built for end users (customers).

## Tech Stack

- **Framework**: React 19 + TypeScript + Vite
- **Mobile**: Capacitor 7 (iOS & Android)
- **Authentication**: Clerk
- **State Management**: TanStack Query (React Query)
- **Styling**: Tailwind CSS v4
- **Navigation**: React Router v6

## Native Features

- **Maps**: Google Maps via `@capacitor/google-maps`
- **QR Scanning**: Barcode Scanner via `@capacitor/barcode-scanner`
- **Payments**: Razorpay via `capacitor-razorpay`
- **Location**: Geolocation via `@capacitor/geolocation`

## Setup Instructions

### 1. Environment Variables

Create a `.env` file in the `/app` directory:

```bash
cp .env.example .env
```

Then fill in the required values:

```env
# API Configuration
VITE_API_URL=http://localhost:8000  # or your production API URL

# Clerk Authentication
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...

# Google Maps
VITE_GOOGLE_MAPS_API_KEY=AIzaSy...

# Razorpay
VITE_RAZORPAY_KEY_ID=rzp_test_...
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Development

#### Web Development (Browser)

```bash
npm run dev
```

Access the app at `http://localhost:5173`

#### iOS Development

```bash
# Build the web assets
npm run build

# Sync with Capacitor
npx cap sync ios

# Open Xcode
npx cap open ios
```

#### Android Development

```bash
# Build the web assets
npm run build

# Sync with Capacitor
npx cap sync android

# Open Android Studio
npx cap open android
```

## Project Structure

```
app/
├── src/
│   ├── components/        # Reusable UI components
│   │   └── Layout.tsx     # Main layout with bottom navigation
│   ├── lib/               # Utilities and services
│   │   ├── api-client.ts  # API client with Clerk auth
│   │   └── api-services.ts # API service functions
│   ├── screens/           # Screen components (pages)
│   │   ├── HomeScreen.tsx
│   │   ├── StationsScreen.tsx
│   │   ├── ScannerScreen.tsx
│   │   ├── ChargeScreen.tsx
│   │   └── SessionsScreen.tsx
│   ├── types/             # TypeScript type definitions
│   │   └── api.ts
│   ├── App.tsx            # Root component with providers
│   ├── routes.tsx         # Route configuration
│   └── index.css          # Global styles
├── ios/                   # iOS native project
├── android/               # Android native project
├── capacitor.config.ts    # Capacitor configuration
└── package.json
```

## Features

### Implemented (Basic Structure)

✅ Clerk authentication with sign-in/sign-out
✅ Bottom tab navigation (Home, Stations, Scanner, Sessions)
✅ API client with JWT token management
✅ Basic screen layouts

### To Be Implemented

⏳ QR Code Scanner (using Capacitor Barcode Scanner)
⏳ Station Finder with Google Maps
⏳ Live Charging Session with real-time updates
⏳ Wallet & Razorpay payment integration
⏳ Transaction History
⏳ iOS configuration (Info.plist, permissions)
⏳ Android configuration (AndroidManifest.xml, permissions)

## API Integration

The app connects to the backend API and supports:

- **Public Endpoints**: Station listing (no auth required)
- **User Endpoints**:
  - My sessions and transactions
  - Wallet balance and recharge
  - Transaction details with meter values
- **Charger Control**: Remote start/stop charging

## Native Permissions

### iOS (Info.plist)

- Camera: For QR code scanning
- Location: For finding nearby stations
- Internet: For API calls

### Android (AndroidManifest.xml)

- Camera: For QR code scanning
- Location (Fine & Coarse): For finding nearby stations
- Internet: For API calls

## Building for Production

### iOS

1. Open project in Xcode: `npx cap open ios`
2. Configure signing & capabilities
3. Update bundle ID to match your Apple Developer account
4. Add required permissions in Info.plist
5. Build and archive for App Store

### Android

1. Open project in Android Studio: `npx cap open android`
2. Configure app signing
3. Update application ID in `build.gradle`
4. Add required permissions in AndroidManifest.xml
5. Build signed APK/AAB for Play Store

## Troubleshooting

### Build Fails

```bash
# Clean and rebuild
rm -rf node_modules dist
npm install
npm run build
```

### Capacitor Sync Issues

```bash
# Remove and re-add platforms
npx cap remove ios
npx cap remove android
npx cap add ios
npx cap add android
npx cap sync
```

### TypeScript Errors

```bash
# Rebuild TypeScript
npx tsc -b --clean
npx tsc -b
```

## Next Steps

1. Get Clerk publishable key from your Clerk dashboard
2. Set up Google Maps API key for station finder
3. Configure Razorpay test keys for payments
4. Implement the pending features (Scanner, Maps, Charging, Wallet)
5. Test on physical devices (iOS & Android)
6. Configure native permissions
7. Submit to app stores

## Resources

- [Capacitor Docs](https://capacitorjs.com/docs)
- [Clerk React Docs](https://clerk.com/docs/references/react/overview)
- [TanStack Query Docs](https://tanstack.com/query/latest)
- [Google Maps Capacitor Plugin](https://github.com/ionic-team/capacitor-google-maps)
- [Razorpay Capacitor Plugin](https://www.npmjs.com/package/capacitor-razorpay)
