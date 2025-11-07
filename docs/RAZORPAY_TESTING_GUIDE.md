# Razorpay Integration Testing Guide

## Step 1: Create Razorpay Test Account

### Sign Up for Razorpay
1. Go to https://dashboard.razorpay.com/signup
2. Sign up with your email
3. Complete the registration process
4. **Stay in TEST MODE** for now (look for test/live toggle in dashboard)

## Step 2: Get Test API Keys

### Get Your Test Keys
1. Login to Razorpay Dashboard: https://dashboard.razorpay.com/
2. Go to **Settings** → **API Keys**
3. Click **Generate Test Key** (if not already generated)
4. You'll see:
   - **Key Id**: Starts with `rzp_test_` (e.g., `rzp_test_1234567890`)
   - **Key Secret**: Click "Show" to reveal (e.g., `abcdefghijklmnop1234567890`)

### Add Keys to Backend .env
Open `/backend/.env` and replace the placeholders:

```bash
# Razorpay Configuration (Test Mode)
RAZORPAY_KEY_ID=rzp_test_1234567890  # Replace with your test key
RAZORPAY_KEY_SECRET=abcdefghijklmnop1234567890  # Replace with your secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret_here  # We'll get this in Step 3
```

## Step 3: Configure Webhook (Optional for Initial Testing)

### Set Up Webhook
1. Go to **Settings** → **Webhooks**
2. Click **Create New Webhook**
3. Enter your webhook URL:
   - **Development**: `https://your-ngrok-url.ngrok.io/webhooks/razorpay`
   - **Production**: `https://your-domain.com/webhooks/razorpay`
4. Select events to listen to:
   - ✅ `payment.captured`
   - ✅ `payment.failed`
   - ✅ `order.paid`
5. Click **Create Webhook**
6. Copy the **Webhook Secret** (starts with `whsec_`)
7. Add it to your `.env`:
   ```bash
   RAZORPAY_WEBHOOK_SECRET=whsec_abc123xyz...
   ```

### Using ngrok for Local Testing (Webhook)
If you want to test webhooks locally:

```bash
# Install ngrok (if not installed)
# Download from https://ngrok.com/download

# Start your backend server first
cd backend
source .venv/bin/activate
python main.py

# In another terminal, start ngrok
ngrok http 8000

# Copy the https URL (e.g., https://abc123.ngrok.io)
# Use this URL in Razorpay webhook settings as: https://abc123.ngrok.io/webhooks/razorpay
```

**Note**: For initial testing, you can skip webhooks! The frontend verification will work fine.

## Step 4: Install Dependencies

### Backend
```bash
cd backend
source .venv/bin/activate
pip install razorpay==2.0.0
# OR
pip install -r requirements.txt
```

### Frontend
No additional dependencies needed! Razorpay script loads from CDN.

## Step 5: Start Your Servers

### Start Backend
```bash
cd backend
source .venv/bin/activate
python main.py
# Should start on http://localhost:8000
```

### Start Frontend
```bash
cd frontend
npm run dev
# Should start on http://localhost:3000
```

## Step 6: Test the Integration

### Test Flow

1. **Login to your app**
   - Use your Clerk authentication

2. **Navigate to My Sessions page**
   - Should see "Recharge Wallet" button

3. **Click "Recharge Wallet"**
   - Modal should open

4. **Enter amount**
   - Try: ₹100, ₹500, or use quick buttons
   - Min: ₹1, Max: ₹1,00,000

5. **Click "Recharge"**
   - Razorpay checkout modal should open

6. **Complete payment with test card**

### Razorpay Test Cards

#### Success Scenarios

**Successful Payment (Domestic)**
- Card Number: `4111 1111 1111 1111`
- Expiry: Any future date (e.g., `12/25`)
- CVV: Any 3 digits (e.g., `123`)
- Name: Any name

**Successful Payment (International)**
- Card Number: `4012 0010 3714 1112`
- Expiry: Any future date
- CVV: Any 3 digits
- Name: Any name

#### Failure Scenarios

**Card Declined**
- Card Number: `4000 0000 0000 0002`
- Expiry: Any future date
- CVV: Any 3 digits

**Insufficient Funds**
- Card Number: `4000 0000 0000 9995`
- Expiry: Any future date
- CVV: Any 3 digits

**Authentication Failed**
- Card Number: `4000 0025 0000 3155`
- Expiry: Any future date
- CVV: Any 3 digits

### Test UPI (Optional)
- UPI ID: `success@razorpay`
- This will simulate a successful UPI payment

## Step 7: Verify the Payment

### Expected Behavior

**After Successful Payment:**
1. ✅ Razorpay modal closes
2. ✅ Success toast message appears
3. ✅ Wallet balance updates immediately
4. ✅ New balance shows in UI
5. ✅ Transaction appears in wallet history

**After Failed Payment:**
1. ❌ Error message appears
2. ❌ Wallet balance unchanged
3. ❌ Transaction marked as FAILED in database

### Check Backend Logs

```bash
# In backend terminal, you should see:
INFO Creating Razorpay order: ₹500 (50000 paise)
INFO Razorpay order created: order_abc123xyz
INFO Payment signature verified successfully for order order_abc123xyz
INFO ✅ Successfully processed wallet top-up: Transaction 123, Amount ₹500, New balance ₹500
```

### Check Database

```sql
-- Check wallet transaction
SELECT * FROM wallet_transaction
WHERE type = 'TOP_UP'
ORDER BY created_at DESC
LIMIT 5;

-- Check wallet balance
SELECT u.email, w.balance
FROM wallet w
JOIN app_user u ON w.user_id = u.id;
```

## Step 8: Test Webhook (Optional)

### With ngrok Running

1. Complete a payment
2. Check backend logs for webhook:
   ```
   INFO Received Razorpay webhook: payment.captured
   INFO Webhook signature verified successfully
   INFO ✅ Webhook: Successfully processed payment for order order_abc123, Amount ₹500, New balance ₹500
   ```

### Test Webhook Directly

Use Razorpay's webhook test feature:
1. Go to **Settings** → **Webhooks**
2. Click on your webhook
3. Click **Send Test Webhook**
4. Select `payment.captured` event
5. Check backend logs

## Common Issues & Solutions

### Issue 1: "Payment service is currently unavailable"
**Solution**: Check that `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` are set in `.env`

### Issue 2: Razorpay modal doesn't open
**Solution**:
- Check browser console for errors
- Ensure internet connection (Razorpay script loads from CDN)
- Check if popup blocker is enabled

### Issue 3: "Invalid payment signature"
**Solution**:
- Check that `RAZORPAY_KEY_SECRET` is correct
- Ensure using correct test/live keys

### Issue 4: Webhook not receiving events
**Solution**:
- Check ngrok is running
- Verify webhook URL is correct in Razorpay dashboard
- Check webhook secret matches in `.env`
- Check Razorpay dashboard → Webhooks → Logs

### Issue 5: Payment succeeds but wallet not credited
**Solution**:
- Check backend logs for errors
- Verify database connection
- Check if webhook is configured (if relying on it)
- Frontend verification should still work even without webhook

## Testing Checklist

- [ ] Backend .env has Razorpay credentials
- [ ] Backend server is running
- [ ] Frontend server is running
- [ ] Can open "Recharge Wallet" modal
- [ ] Can enter amount and see quick buttons
- [ ] Razorpay modal opens on click
- [ ] Test card payment succeeds
- [ ] Wallet balance updates
- [ ] Success toast appears
- [ ] Transaction appears in history
- [ ] Backend logs show successful processing
- [ ] Test card decline works
- [ ] Error message shows on failure
- [ ] (Optional) Webhook receives events
- [ ] (Optional) Webhook updates wallet correctly

## Going Live

### Before Production

1. **Switch to Live Keys**
   - Get Live API keys from Razorpay dashboard
   - Update `.env` with live keys (starts with `rzp_live_`)

2. **Complete KYC**
   - Submit business documents to Razorpay
   - Get account activated for live mode

3. **Update Webhook URL**
   - Use production domain
   - Test webhook in production

4. **Test with Small Amount**
   - Use real card with small amount (₹1)
   - Verify complete flow

5. **Monitor Logs**
   - Check for errors
   - Monitor Razorpay dashboard

## Support & Documentation

### Razorpay Resources
- Dashboard: https://dashboard.razorpay.com/
- Docs: https://razorpay.com/docs/
- Python SDK: https://github.com/razorpay/razorpay-python
- Test Cards: https://razorpay.com/docs/payments/payments/test-card-details/
- Support: support@razorpay.com

### Your Implementation
- Backend Service: `/backend/services/razorpay_service.py`
- Payment Router: `/backend/routers/wallet_payments.py`
- Webhook Handler: `/backend/routers/webhooks.py`
- Frontend Modal: `/frontend/components/WalletRechargeModal.tsx`

## Quick Start (TL;DR)

```bash
# 1. Get Razorpay test keys
# Visit: https://dashboard.razorpay.com/signup

# 2. Add to backend/.env
RAZORPAY_KEY_ID=rzp_test_YOUR_KEY
RAZORPAY_KEY_SECRET=YOUR_SECRET
RAZORPAY_WEBHOOK_SECRET=whsec_YOUR_SECRET  # Optional for initial test

# 3. Install & run
cd backend
source .venv/bin/activate
pip install -r requirements.txt
python main.py

# 4. Run frontend
cd frontend
npm run dev

# 5. Test with card
# Card: 4111 1111 1111 1111
# Expiry: 12/25
# CVV: 123

# Done! 🎉
```
