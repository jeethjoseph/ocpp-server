# Quick Start Guide - LyncPower Mobile App

Get the app running in under 5 minutes!

## 🚀 Quick Start (Browser Testing)

### 1. Setup Environment

```bash
cd app

# Copy environment template
cp .env.example .env
```

### 2. Edit `.env` File

Get the Clerk publishable key from your web frontend:

```bash
# From frontend directory
cat ../frontend/.env.local | grep CLERK
```

Update `/app/.env`:
```env
VITE_API_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=pk_test_[your_key_here]
VITE_GOOGLE_MAPS_API_KEY=AIzaSy...  # Optional for now
VITE_RAZORPAY_KEY_ID=rzp_test_...   # Optional for now
```

### 3. Start Development Server

```bash
npm run dev
```

Open http://localhost:5173 in your browser.

## 📱 Test on Mobile Device (iOS/Android)

### Prerequisites
- Xcode (for iOS)
- Android Studio (for Android)
- Device or simulator

### Build & Deploy

```bash
# 1. Build web assets
npm run build

# 2. Sync with Capacitor
npx cap sync ios      # or android

# 3. Open in native IDE
npx cap open ios      # or android

# 4. Run from Xcode or Android Studio
```

## 🧪 What to Test

### ✅ Working Features (Test Now!)

1. **Sign In**
   - Use your existing Clerk account
   - Should redirect to home screen

2. **Home Screen**
   - See welcome message with your name
   - Click quick action buttons

3. **QR Scanner**
   - Try manual input: Enter `1` as charger ID
   - Or scan real QR code (on device only)

4. **Charging Session**
   - If charger #1 exists, you'll see:
     - Charger status
     - Start/Stop buttons
     - Live updates every 5 seconds

5. **Transaction History**
   - View your past sessions
   - See wallet balance
   - Try "Recharge Wallet" button

6. **Navigation**
   - Test bottom tabs
   - Back navigation
   - Sign out

### ⏳ Partial Features

1. **Wallet Recharge**
   - Modal opens ✅
   - Amount input works ✅
   - Payment flow pending ⏳

### ❌ Not Yet Available

1. **Station Finder**
   - Shows placeholder screen
   - Google Maps not integrated yet

## 🔧 Troubleshooting

### Build Errors

```bash
# Clean and rebuild
rm -rf node_modules dist
npm install
npm run build
```

### Can't Sign In

1. Check Clerk key in `.env`
2. Ensure backend is running on port 8000
3. Check console for errors

### API Errors

1. Verify backend is running: `http://localhost:8000/docs`
2. Check API_URL in `.env`
3. Check network tab in browser dev tools

### Capacitor Sync Fails

```bash
# Remove and re-add platforms
npx cap remove ios
npx cap add ios
npx cap sync ios
```

## 📚 Development Commands

```bash
# Development
npm run dev              # Start dev server

# Production Build
npm run build            # Build for production

# Capacitor
npx cap sync             # Sync all platforms
npx cap sync ios         # Sync iOS only
npx cap sync android     # Sync Android only
npx cap open ios         # Open Xcode
npx cap open android     # Open Android Studio

# Clean
rm -rf dist              # Clean build files
rm -rf node_modules      # Clean dependencies
```

## 🎯 Test Scenarios

### Scenario 1: Complete Charging Flow

1. Sign in with your account
2. Go to Scanner tab
3. Enter charger ID manually (e.g., `1`)
4. Click "Start Charging"
5. Watch live meter values update
6. Click "Stop Charging"
7. Go to Sessions tab
8. See the session in history

### Scenario 2: Wallet Management

1. Go to Sessions tab
2. Check your wallet balance
3. Click "Recharge Wallet"
4. Select quick amount or enter custom
5. See modal with payment options
6. (Payment flow pending integration)

### Scenario 3: Browse Stations

1. Go to Stations tab
2. Currently shows placeholder
3. (Will show map with station markers)

## 🔑 API Endpoints Being Used

- `GET /api/public/stations` - List charging stations
- `GET /api/admin/chargers/:id` - Get charger details
- `POST /api/admin/chargers/:id/remote-start` - Start charging
- `POST /api/admin/chargers/:id/remote-stop` - Stop charging
- `GET /api/users/my-sessions` - Get user sessions + wallet
- `GET /api/users/transaction/:id` - Get transaction details
- `GET /api/users/transaction/:id/meter-values` - Live meter data
- `POST /api/wallet/create-recharge` - Create Razorpay order

## 🐛 Known Issues

1. **Large bundle size warning**: Normal for development, will be optimized
2. **Station finder placeholder**: Feature not implemented yet
3. **Razorpay payment**: Modal works but payment flow pending
4. **Camera on web**: QR scanner camera only works on physical devices

## 💡 Tips

1. **Use React DevTools**: Install browser extension for debugging
2. **Check Network Tab**: Monitor API calls in browser dev tools
3. **Use Manual Input**: For testing charging without QR codes
4. **Hot Reload**: Changes reflect immediately in browser
5. **Mobile View**: Use browser dev tools to test mobile layout

## 🎉 Success Checklist

- [ ] App runs in browser (`npm run dev`)
- [ ] Can sign in with Clerk
- [ ] Home screen shows your name
- [ ] All bottom tabs work
- [ ] Can navigate to charging session
- [ ] Can see transaction history
- [ ] Wallet balance displays
- [ ] Can sign out

If all items are checked, the app is working correctly! 🚀

## 📞 Need Help?

1. Check `README.md` for detailed setup instructions
2. Check `IMPLEMENTATION_STATUS.md` for feature status
3. Check console logs for error messages
4. Verify backend is running and accessible
5. Ensure all environment variables are set

---

Happy testing! 🎊
