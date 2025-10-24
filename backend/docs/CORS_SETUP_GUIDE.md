# CORS Setup Guide for powerlync.com + lyncpower.com

## Architecture Overview

```
Frontend (Client):     https://powerlync.com
Backend (API):         https://lyncpower.com
WebSocket (OCPP):      wss://lyncpower.com/ocpp/
```

Since these are **different domains**, CORS (Cross-Origin Resource Sharing) is required.

---

## The Problem

### What is CORS?

CORS is a browser security feature that blocks JavaScript from making requests to different domains without permission.

### The OPTIONS Preflight Request Flow

When your frontend makes an authenticated request:

```
1. Browser: "I want to send GET /api/admin/chargers with Authorization header"

2. Browser sends OPTIONS (preflight) request FIRST:
   OPTIONS /api/admin/chargers HTTP/1.1
   Origin: https://powerlync.com
   Access-Control-Request-Method: GET
   Access-Control-Request-Headers: authorization
   (NO Authorization header!)

3. Server MUST respond with 200 OK + CORS headers:
   HTTP/1.1 200 OK
   Access-Control-Allow-Origin: https://powerlync.com
   Access-Control-Allow-Methods: GET, POST, PUT, DELETE
   Access-Control-Allow-Headers: Authorization, Content-Type
   Access-Control-Allow-Credentials: true

4. If 200 OK, browser sends actual GET request:
   GET /api/admin/chargers HTTP/1.1
   Authorization: Bearer token123...
```

**Your issue:** OPTIONS requests were hitting authentication middleware, which returned `400 Bad Request` because there was no Authorization header.

---

## The Solution

### What We Changed

1. **Updated CORS origins** to include `powerlync.com`
2. **Added OPTIONS middleware** to intercept OPTIONS requests BEFORE authentication
3. **Return 200 OK** for all OPTIONS requests with proper CORS headers

### Code Changes in `main.py`

#### Change 1: CORS Origins
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://powerlync.com",        # ✅ Production frontend
        "https://www.powerlync.com",    # ✅ Production frontend (www)
        # ... other origins
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### Change 2: OPTIONS Middleware
```python
class OptionsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            # Return 200 OK immediately, skip authentication
            return Response(status_code=200, headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Credentials": "true",
            })
        return await call_next(request)

app.add_middleware(OptionsMiddleware)
```

---

## Deployment Instructions

### Step 1: Update Backend Code

The code has already been updated in `main.py`. Verify the changes:

```bash
cd /root/ocpp_server
git pull  # If using git
# Or manually copy the updated main.py to the server
```

### Step 2: Restart Backend Service

On your Vultr server:

```bash
# Restart the FastAPI service
sudo systemctl restart ocpp-server-production

# Check if it started successfully
sudo systemctl status ocpp-server-production

# Monitor logs for errors
sudo journalctl -u ocpp-server-production -f
```

### Step 3: Test CORS from Browser

Open your browser console on `https://powerlync.com` and run:

```javascript
// Test OPTIONS request
fetch('https://lyncpower.com/api/admin/chargers?limit=1', {
  method: 'OPTIONS',
  headers: {
    'Origin': 'https://powerlync.com'
  }
})
.then(r => console.log('OPTIONS:', r.status, r.headers))

// Test actual GET request with auth
fetch('https://lyncpower.com/api/admin/chargers?limit=1', {
  method: 'GET',
  headers: {
    'Authorization': 'Bearer YOUR_TOKEN_HERE',
    'Content-Type': 'application/json'
  },
  credentials: 'include'
})
.then(r => r.json())
.then(data => console.log('GET:', data))
```

**Expected Results:**
- OPTIONS request: `200 OK`
- GET request: `200 OK` with charger data

### Step 4: Verify in Server Logs

Watch the logs to confirm OPTIONS requests are returning 200:

```bash
sudo journalctl -u ocpp-server-production -f | grep OPTIONS
```

You should see:
```
INFO: 49.36.138.12:0 - "OPTIONS /api/admin/chargers?limit=100 HTTP/1.1" 200 OK
```

Instead of the previous:
```
INFO: 49.36.138.12:0 - "OPTIONS /api/admin/chargers?limit=100 HTTP/1.1" 400 Bad Request
```

---

## How It Works

### Request Flow with Middleware

```
┌─────────────────────────────────────────────────┐
│ Browser sends OPTIONS request                    │
│ Origin: https://powerlync.com                    │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ Nginx (port 443)                                 │
│ - SSL termination                                │
│ - Proxy to localhost:8080                        │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ FastAPI (localhost:8080)                         │
│                                                  │
│ 1. CORSMiddleware (checks origin)                │
│    ✅ powerlync.com is in allowed list           │
│                                                  │
│ 2. OptionsMiddleware                             │
│    ✅ Request method = OPTIONS                   │
│    ✅ Return 200 OK immediately                  │
│    ⛔ SKIP all remaining middleware              │
│    ⛔ SKIP authentication                        │
│    ⛔ SKIP endpoint handlers                     │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ Response: 200 OK                                 │
│ Access-Control-Allow-Origin: powerlync.com       │
│ Access-Control-Allow-Methods: GET, POST, ...     │
│ Access-Control-Allow-Headers: Authorization      │
│ Access-Control-Allow-Credentials: true           │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ Browser receives 200 OK                          │
│ ✅ CORS preflight successful                     │
│ ✅ Now sends actual GET/POST request with auth   │
└─────────────────────────────────────────────────┘
```

---

## Troubleshooting

### Issue 1: Still getting 400 Bad Request

**Symptom:**
```
INFO: "OPTIONS /api/admin/chargers HTTP/1.1" 400 Bad Request
```

**Solution:**
1. Verify `OptionsMiddleware` is added AFTER `CORSMiddleware` in `main.py`
2. Restart the backend service
3. Clear browser cache and try again

### Issue 2: CORS error in browser

**Symptom:**
```
Access to fetch at 'https://lyncpower.com/api/...' from origin 'https://powerlync.com'
has been blocked by CORS policy
```

**Solution:**
1. Check that `powerlync.com` is in the `allow_origins` list
2. Verify the origin matches exactly (check for `www.` prefix)
3. Check browser Network tab to see the actual Origin header sent

### Issue 3: Authentication still failing on OPTIONS

**Symptom:**
```
{"detail": "Authorization header required"}
```

**Solution:**
The `OptionsMiddleware` might not be intercepting OPTIONS requests. Check:
1. Middleware order in `main.py`
2. Restart the service
3. Check if another middleware is interfering

### Issue 4: Working locally but not in production

**Check these:**
```bash
# 1. Verify service is running with updated code
sudo systemctl status ocpp-server-production

# 2. Check which code is actually running
cat /root/ocpp_server/main.py | grep -A 30 "OptionsMiddleware"

# 3. Restart service to reload code
sudo systemctl restart ocpp-server-production

# 4. Monitor logs for startup errors
sudo journalctl -u ocpp-server-production -n 100 --no-pager
```

---

## Security Considerations

### Why This Approach is Secure

1. **Origin validation**: We only allow specific origins in the allowed list
2. **Credentials required**: `allow_credentials=true` means cookies/auth are included
3. **OPTIONS doesn't execute business logic**: It just returns headers, no data access
4. **Actual requests still require authentication**: GET/POST/PUT/DELETE all need valid JWT

### What OPTIONS Requests Can't Do

- ❌ Access data
- ❌ Modify data
- ❌ Bypass authentication on actual requests
- ❌ Execute any endpoint logic
- ✅ Only checks if the request is allowed

---

## Alternative Solutions (Not Recommended)

### Alternative 1: Disable authentication on OPTIONS in each endpoint

**Pros:** Granular control
**Cons:** Need to modify every protected endpoint

### Alternative 2: Use same domain for frontend and backend

**Example:** Both on `lyncpower.com`
```
Frontend: https://lyncpower.com/
Backend:  https://lyncpower.com/api/
```

**Pros:** No CORS issues at all
**Cons:** Can't use Vercel for frontend, need to host on Vultr

### Alternative 3: Use subdomains

**Example:**
```
Frontend: https://app.lyncpower.com
Backend:  https://api.lyncpower.com
```

**Pros:** Cleaner separation
**Cons:** Still requires CORS (subdomains are different origins)

---

## Summary

✅ **What we fixed:**
- Added `powerlync.com` to CORS allowed origins
- Created middleware to handle OPTIONS requests
- OPTIONS requests now return 200 OK before hitting authentication

✅ **What works now:**
- Browser can make CORS preflight requests successfully
- Frontend at `powerlync.com` can call backend at `lyncpower.com`
- Authentication works on actual GET/POST/PUT/DELETE requests

✅ **No security compromises:**
- Only OPTIONS gets special treatment
- Actual API requests still require valid authentication
- Only whitelisted origins are allowed

---

## Next Steps

1. ✅ Deploy updated code to Vultr server
2. ✅ Restart backend service
3. ✅ Test from `powerlync.com` frontend
4. ✅ Monitor logs for any CORS errors
5. ✅ Update frontend to use `https://lyncpower.com` API URL

---

## Questions?

If you see any CORS errors:
1. Check browser Network tab (look at OPTIONS request/response headers)
2. Check backend logs (`sudo journalctl -u ocpp-server-production -f`)
3. Verify the origin header matches exactly what's in the allowed list