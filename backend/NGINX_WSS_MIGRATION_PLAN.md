# OCPP Server WSS Migration - Implementation Plan

## 1. Problem Statement

### Current State
- **Backend deployed on Vultr** as a systemd service (FastAPI + Uvicorn)
- **Cloudflare proxy** configured to provide HTTPS for frontend requirements
- **High latency** due to Cloudflare intermediary layer
- **WSS connection failures** on Render.com endpoint (`https://ocpp-server-uwli.onrender.com`)
- **WSS connections work** on GCP Cloud Run endpoint (`https://ocpp-server-148413839561.asia-south1.run.app`)

### Root Causes
1. **No native SSL/TLS on Vultr backend** - relies on Cloudflare proxy
2. **Cloudflare introduces latency** - additional network hops and potential buffering
3. **Render.com WebSocket limitations** - platform-specific issues with long-lived OCPP connections
4. **OCPP chargers require WSS** - cannot connect to unencrypted WebSocket endpoints

### Business Impact
- Chargers cannot reliably connect to production server
- High latency affects real-time charging operations
- Dependency on third-party proxy reduces control
- Inconsistent behavior across deployment environments

---

## 2. Primary Approach

### Architecture Overview

```
┌─────────────────┐
│  EV Chargers    │
│  (OCPP 1.6)     │
└────────┬────────┘
         │ WSS (Port 443)
         │ TLS 1.2/1.3
         ▼
┌─────────────────────────────────────────┐
│         Nginx Reverse Proxy             │
│  - SSL/TLS Termination (Certbot)       │
│  - WebSocket Protocol Upgrade           │
│  - Request Routing                      │
│  - Timeout Management (3600s)           │
│  Port 443 (HTTPS/WSS)                   │
└────────┬────────────────────────────────┘
         │ WS (Local)
         │ Port 8080
         ▼
┌─────────────────────────────────────────┐
│      FastAPI Application (Uvicorn)      │
│  - OCPP 1.6 Protocol Handler           │
│  - WebSocket Endpoint: /ocpp/{id}      │
│  - REST API Endpoints                   │
│  Port 8080 (localhost only)             │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│    PostgreSQL + Redis                   │
│  - Transaction Storage                  │
│  - Connection State                     │
└─────────────────────────────────────────┘
```

### Key Strategy
1. **Remove Cloudflare dependency** - Direct SSL termination on Vultr
2. **Nginx as reverse proxy** - Industry-standard WebSocket handling
3. **Let's Encrypt via Certbot** - Free, auto-renewing SSL certificates
4. **Zero-downtime deployment** - Keep current service running during migration
5. **Rollback capability** - Maintain Cloudflare as backup during testing

---

## 3. Detailed Implementation Steps

### Phase 1: Prerequisites & Preparation (30 minutes)

#### Step 1.1: Verify Current System State
```bash
# SSH into Vultr server
ssh user@your-vultr-ip

# Check current service status
sudo systemctl status ocpp-server

# Verify ports in use
sudo netstat -tlnp | grep -E ':(8000|8080|443|80)'

# Check current FastAPI configuration
cat /etc/systemd/system/ocpp-server.service

# Verify database connections
psql -h localhost -U your_user -d ocpp_db -c "SELECT 1;"
```

**Expected Output:**
- OCPP service running on port 8000 or 8080
- No service currently on ports 80/443
- Database accessible

#### Step 1.2: Domain Configuration
```bash
# Verify DNS records point to Vultr IP
dig +short yourdomain.com
nslookup yourdomain.com

# Should return your Vultr server IP
```

**Action Required:**
- If using Cloudflare DNS: Set DNS record to "DNS only" (grey cloud, not proxied)
- Add A record: `yourdomain.com` → `your-vultr-ip`
- Wait for DNS propagation (5-15 minutes)

#### Step 1.3: Backup Current Configuration
```bash
# Backup current service configuration
sudo cp /etc/systemd/system/ocpp-server.service \
       /etc/systemd/system/ocpp-server.service.backup

# Export environment variables
env | grep -E '(DATABASE|REDIS|SUPABASE|CLERK)' > ~/env_backup.txt

# Backup current nginx config if exists
if [ -d /etc/nginx ]; then
    sudo tar -czf ~/nginx_backup_$(date +%F).tar.gz /etc/nginx
fi
```

---

### Phase 2: Install & Configure Nginx (45 minutes)

#### Step 2.1: Install Nginx and Certbot
```bash
# Update package list
sudo apt update

# Install Nginx
sudo apt install nginx -y

# Install Certbot for Let's Encrypt
sudo apt install certbot python3-certbot-nginx -y

# Verify installations
nginx -v
certbot --version
```

**Expected Output:**
```
nginx version: nginx/1.18.0 (Ubuntu)
certbot 1.21.0
```

#### Step 2.2: Configure Firewall
```bash
# Allow HTTP (needed for Certbot validation)
sudo ufw allow 80/tcp

# Allow HTTPS
sudo ufw allow 443/tcp

# Verify firewall status
sudo ufw status
```

#### Step 2.3: Create Initial Nginx Configuration
```bash
# Remove default configuration
sudo rm /etc/nginx/sites-enabled/default

# Create new OCPP server configuration
sudo nano /etc/nginx/sites-available/ocpp-server
```

**Configuration Content:**
```nginx
# Upstream backend definition
upstream ocpp_backend {
    server 127.0.0.1:8080;
    keepalive 64;
}

# HTTP server - for Certbot validation and redirect
server {
    listen 80;
    listen [::]:80;
    server_name yourdomain.com;  # REPLACE WITH YOUR DOMAIN

    # Certbot ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect all other HTTP to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server - will be enhanced after SSL cert obtained
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yourdomain.com;  # REPLACE WITH YOUR DOMAIN

    # Temporary self-signed cert (Certbot will replace)
    ssl_certificate /etc/ssl/certs/ssl-cert-snakeoil.pem;
    ssl_certificate_key /etc/ssl/private/ssl-cert-snakeoil.key;

    # Basic response for testing
    location / {
        return 200 "Nginx configured, waiting for SSL\n";
        add_header Content-Type text/plain;
    }
}
```

```bash
# Create directory for Certbot challenges
sudo mkdir -p /var/www/certbot

# Enable the site
sudo ln -s /etc/nginx/sites-available/ocpp-server /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Start Nginx
sudo systemctl enable nginx
sudo systemctl start nginx
sudo systemctl status nginx
```

#### Step 2.4: Obtain SSL Certificate
```bash
# Obtain Let's Encrypt certificate
sudo certbot --nginx -d yourdomain.com

# Follow prompts:
# - Enter email address
# - Agree to terms of service
# - Choose whether to redirect HTTP to HTTPS (select Yes)
```

**Expected Output:**
```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/yourdomain.com/fullchain.pem
Key is saved at: /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

#### Step 2.5: Update Nginx with Full Production Configuration
```bash
sudo nano /etc/nginx/sites-available/ocpp-server
```

**Replace with:**
```nginx
# Upstream backend definition
upstream ocpp_backend {
    server 127.0.0.1:8080;
    keepalive 64;
}

# HTTP server - redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name yourdomain.com;  # REPLACE WITH YOUR DOMAIN

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server with WebSocket support
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yourdomain.com;  # REPLACE WITH YOUR DOMAIN

    # SSL configuration (updated by Certbot)
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # Modern SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Logging
    access_log /var/log/nginx/ocpp_access.log;
    error_log /var/log/nginx/ocpp_error.log;

    # OCPP WebSocket endpoint - CRITICAL CONFIGURATION
    location /ocpp/ {
        proxy_pass http://ocpp_backend;

        # WebSocket upgrade headers
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Preserve client information
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # OCPP-specific timeouts (long-lived connections)
        proxy_read_timeout 3600s;  # 1 hour
        proxy_send_timeout 3600s;  # 1 hour
        proxy_connect_timeout 60s;

        # Disable buffering for real-time WebSocket
        proxy_buffering off;
        proxy_request_buffering off;

        # Keep-alive
        proxy_set_header Connection "";
    }

    # REST API endpoints
    location /api/ {
        proxy_pass http://ocpp_backend;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Standard timeouts for REST API
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
        proxy_connect_timeout 10s;
    }

    # Root and docs endpoints
    location / {
        proxy_pass http://ocpp_backend;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    # Health check endpoint (optional)
    location /health {
        access_log off;
        proxy_pass http://ocpp_backend;
    }
}
```

```bash
# Test new configuration
sudo nginx -t

# Reload Nginx with new config
sudo systemctl reload nginx
```

---

### Phase 3: Update FastAPI Service (30 minutes)

#### Step 3.1: Modify Service Configuration
```bash
# Edit systemd service file
sudo nano /etc/systemd/system/ocpp-server.service
```

**Ensure it contains:**
```ini
[Unit]
Description=OCPP Central System API
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=your-app-user  # REPLACE with your user
WorkingDirectory=/path/to/ocpp-server/backend  # REPLACE with your path
Environment="PATH=/path/to/venv/bin:$PATH"  # REPLACE with your venv

# Environment variables (or use EnvironmentFile)
Environment="DATABASE_URL=postgresql://..."
Environment="REDIS_URL=redis://localhost:6379"
Environment="SUPABASE_URL=..."
Environment="CLERK_SECRET_KEY=..."

# CRITICAL: Bind to localhost only, port 8080
ExecStart=/path/to/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080 --workers 2

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Key Changes:**
- `--host 127.0.0.1` (NOT 0.0.0.0) - Only accessible via Nginx
- `--port 8080` - Match Nginx upstream configuration
- Remove any SSL-related flags

#### Step 3.2: Update CORS Configuration in main.py

Check your current CORS settings (main.py:48-54):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://ocpp-frontend-mu.vercel.app",
        "https://lyncpower.com",
        "https://www.lyncpower.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Verify this includes your production domain** (add if missing):
```python
allow_origins=[
    # ... existing origins ...
    "https://yourdomain.com",  # Add your Vultr domain
],
```

#### Step 3.3: Reload Service
```bash
# Reload systemd configuration
sudo systemctl daemon-reload

# Restart the OCPP service
sudo systemctl restart ocpp-server

# Check status
sudo systemctl status ocpp-server

# Verify it's listening on port 8080
sudo netstat -tlnp | grep 8080
```

**Expected Output:**
```
tcp  0  0  127.0.0.1:8080  0.0.0.0:*  LISTEN  12345/python
```

---

### Phase 4: Testing & Validation (45 minutes)

#### Step 4.1: SSL Certificate Validation
```bash
# Test SSL certificate from external perspective
echo | openssl s_client -connect yourdomain.com:443 -servername yourdomain.com 2>/dev/null | openssl x509 -noout -text | grep -A 2 "Subject:"

# Check certificate expiry
echo | openssl s_client -connect yourdomain.com:443 -servername yourdomain.com 2>/dev/null | openssl x509 -noout -dates

# Verify SSL grade (optional, requires external tool)
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=yourdomain.com
```

**Expected:**
- Subject should be your domain
- Valid for 90 days (Let's Encrypt standard)
- Issuer: Let's Encrypt Authority

#### Step 4.2: HTTP to HTTPS Redirect Test
```bash
# Should redirect to HTTPS
curl -I http://yourdomain.com

# Expected output should include:
# HTTP/1.1 301 Moved Permanently
# Location: https://yourdomain.com/
```

#### Step 4.3: REST API Endpoint Test
```bash
# Test root endpoint
curl https://yourdomain.com/

# Test API endpoint
curl https://yourdomain.com/api/

# Test with authentication (if needed)
curl -H "Authorization: Bearer YOUR_TOKEN" https://yourdomain.com/api/charge-points
```

**Expected:**
- JSON responses from your FastAPI app
- No SSL errors
- Response times < 100ms

#### Step 4.4: WebSocket Connection Test

**From your local machine:**
```bash
# Install websocat if not available
# brew install websocat  (macOS)
# apt install websocat   (Ubuntu)

# Test WSS connection
websocat wss://yourdomain.com/ocpp/TEST_CHARGER_01

# Should see connection established
# Try sending a test OCPP message (BootNotification)
```

**Using Python test script:**
```python
# test_wss.py
import asyncio
import websockets
import json

async def test_ocpp_connection():
    uri = "wss://yourdomain.com/ocpp/TEST_CHARGER_01"

    try:
        async with websockets.connect(uri) as websocket:
            print(f"✓ Connected to {uri}")

            # Send BootNotification
            boot_notification = [
                2,  # Call message
                "12345",  # Unique ID
                "BootNotification",
                {
                    "chargePointVendor": "TestVendor",
                    "chargePointModel": "TestModel"
                }
            ]

            await websocket.send(json.dumps(boot_notification))
            print(f"→ Sent: {boot_notification}")

            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=10)
            print(f"← Received: {response}")

            print("✓ WebSocket test successful!")

    except Exception as e:
        print(f"✗ Connection failed: {e}")

asyncio.run(test_ocpp_connection())
```

```bash
# Run the test
python test_wss.py
```

**Expected Output:**
```
✓ Connected to wss://yourdomain.com/ocpp/TEST_CHARGER_01
→ Sent: [2, '12345', 'BootNotification', {...}]
← Received: [3, '12345', {'currentTime': '2025-10-10T...', ...}]
✓ WebSocket test successful!
```

#### Step 4.5: Real Charger Connection Test

**Prerequisites:**
- Physical OCPP charger or simulator
- Charger must be configured with: `wss://yourdomain.com/ocpp/CHARGER_ID`

**Steps:**
1. Configure charger backend URL to `wss://yourdomain.com/ocpp/`
2. Set charge point ID in charger configuration
3. Reboot charger or restart connection
4. Monitor server logs:

```bash
# Watch application logs
sudo journalctl -u ocpp-server -f

# Watch Nginx access logs
sudo tail -f /var/log/nginx/ocpp_access.log

# Watch Nginx error logs
sudo tail -f /var/log/nginx/ocpp_error.log
```

**Expected Log Output:**
```
[OCPP][IN] [2,"12345","BootNotification",{...}]
BootNotification from CHARGER_01: vendor=...
[OCPP][OUT] [3,"12345",{"currentTime":"2025-10-10T...","status":"Accepted"}]
```

#### Step 4.6: Load & Latency Testing

```bash
# Install Apache Bench
sudo apt install apache2-utils -y

# Test REST API performance
ab -n 1000 -c 10 https://yourdomain.com/api/

# Monitor WebSocket latency
# Use your charger's heartbeat interval (300s from main.py:83)
# Check logs for heartbeat response times
```

**Performance Targets:**
- REST API: < 50ms average response time
- WebSocket upgrade: < 100ms
- Heartbeat round-trip: < 500ms
- No dropped connections over 24 hours

#### Step 4.7: Certificate Auto-Renewal Test

```bash
# Test renewal process (dry run)
sudo certbot renew --dry-run

# Check renewal timer
sudo systemctl status certbot.timer

# View renewal logs
sudo cat /var/log/letsencrypt/letsencrypt.log
```

**Expected:**
```
Congratulations, all simulated renewals succeeded
```

---

## 4. Prerequisites & Dependencies

### System Requirements

| Component | Requirement | Current Status |
|-----------|-------------|----------------|
| **OS** | Ubuntu 20.04+ / Debian 11+ | ✓ (Vultr) |
| **Python** | 3.11+ | ✓ (From Dockerfile) |
| **Memory** | 2GB minimum, 4GB recommended | ? (Check with `free -h`) |
| **Disk** | 20GB minimum | ? (Check with `df -h`) |
| **Ports** | 80, 443, 8080 available | ? (Check with `netstat`) |
| **Domain** | Valid DNS A record | ⚠ (Need to configure) |

### Software Dependencies

**Server-side (Vultr):**
- Nginx 1.18+
- Certbot with Nginx plugin
- Python 3.11 + virtualenv
- PostgreSQL client libraries
- Redis (already configured per main.py:20)
- systemd (service management)

**Already Installed (from requirements.txt):**
- FastAPI 0.115.12
- Uvicorn 0.34.3
- websockets 15.0.1
- ocpp 2.0.0
- tortoise-orm 0.25.1
- redis 6.2.0

**DNS Configuration:**
```
Type: A
Name: @ (or yourdomain.com)
Value: YOUR_VULTR_IP
TTL: 300 (5 minutes)
Proxy: Disabled (DNS only, no Cloudflare proxy)
```

### Access Requirements
- Root/sudo access to Vultr server
- SSH key authentication configured
- Domain registrar access (for DNS changes)
- Cloudflare account access (to disable proxy)

---

## 5. Validation & Success Criteria

### Phase-by-Phase Validation

**Phase 1 - Prerequisites:** ✓
- [ ] DNS resolves to Vultr IP
- [ ] Ports 80/443 not blocked
- [ ] Current service running and backed up
- [ ] Database/Redis connections verified

**Phase 2 - Nginx Setup:** ✓
- [ ] Nginx installed and running
- [ ] SSL certificate obtained from Let's Encrypt
- [ ] Certificate valid for 90 days
- [ ] Auto-renewal configured
- [ ] HTTP redirects to HTTPS

**Phase 3 - FastAPI Service:** ✓
- [ ] Service binds to 127.0.0.1:8080 only
- [ ] Service restarts successfully
- [ ] Health check endpoint responds
- [ ] Logs show no errors

**Phase 4 - Integration Testing:** ✓
- [ ] HTTPS REST API accessible
- [ ] WSS connection establishes
- [ ] OCPP messages flow bidirectionally
- [ ] Real charger connects successfully
- [ ] No connection drops over 1 hour
- [ ] Latency < 100ms for API calls

### Rollback Plan

**If issues occur:**

```bash
# 1. Restore original service
sudo systemctl stop nginx
sudo cp /etc/systemd/system/ocpp-server.service.backup \
       /etc/systemd/system/ocpp-server.service
sudo systemctl daemon-reload
sudo systemctl restart ocpp-server

# 2. Re-enable Cloudflare proxy
# In Cloudflare dashboard: Toggle DNS record to "Proxied" (orange cloud)

# 3. Verify old setup works
curl http://YOUR_VULTR_IP:8000/
```

### Production Readiness Checklist

**Before removing Cloudflare:**
- [ ] SSL certificate valid and auto-renewing
- [ ] At least 2 chargers connected successfully
- [ ] 24-hour stability test passed
- [ ] Monitoring/alerting configured
- [ ] Backup/disaster recovery tested

**Security:**
- [ ] Only localhost:8080 accessible internally
- [ ] Firewall configured (UFW)
- [ ] Nginx security headers enabled
- [ ] Rate limiting configured (optional)
- [ ] Fail2ban configured (optional)

**Monitoring:**
- [ ] Nginx access logs readable
- [ ] FastAPI application logs accessible
- [ ] Disk space monitoring
- [ ] SSL expiry alerts (Certbot emails)

---

## 6. Timeline & Effort Estimate

| Phase | Duration | Can Run in Parallel? |
|-------|----------|---------------------|
| Phase 1: Prerequisites | 30 min | No |
| Phase 2: Nginx Setup | 45 min | No |
| Phase 3: Service Update | 30 min | No |
| Phase 4: Testing | 45 min | Partially |
| **Total Active Work** | **2.5 hours** | |
| DNS Propagation Wait | 15-60 min | Yes (do other work) |
| 24hr Stability Test | 24 hours | Yes (passive) |

**Recommended Execution:**
- **Day 1 (2-3 hours):** Complete Phases 1-4, run initial tests
- **Day 2-3 (passive):** Monitor stability, keep Cloudflare as backup
- **Day 4:** Remove Cloudflare proxy if all tests pass

---

## 7. Post-Implementation Monitoring

### Daily Checks (Week 1)
```bash
# Certificate validity
sudo certbot certificates

# Service status
sudo systemctl status nginx ocpp-server

# Connection count
ss -tn | grep :8080 | wc -l

# Error log check
sudo grep -i error /var/log/nginx/ocpp_error.log | tail -20
```

### Weekly Maintenance
- Review Nginx access logs for anomalies
- Check disk space usage
- Verify certificate auto-renewal timer active
- Review application error logs

### Alerts to Configure
1. **SSL expiry** < 30 days (Certbot emails)
2. **Service down** (systemd notifications)
3. **Disk space** > 80% full
4. **High error rate** in Nginx logs

---

## 8. Key Configuration Files Reference

**File Locations:**
```
/etc/nginx/sites-available/ocpp-server          # Nginx config
/etc/systemd/system/ocpp-server.service         # Service definition
/etc/letsencrypt/live/yourdomain.com/           # SSL certificates
/var/log/nginx/ocpp_access.log                  # Nginx access logs
/var/log/nginx/ocpp_error.log                   # Nginx error logs
/var/log/letsencrypt/letsencrypt.log            # Certbot logs
```

**Environment Variables Needed:**
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis connection
- `SUPABASE_URL` - Supabase API
- `CLERK_SECRET_KEY` - Clerk authentication
- (Any others from your current setup)

---

## 9. Certificate Analysis - Understanding the Difference

### Render.com Certificate
```
Subject: CN=onrender.com
Issuer: Google Trust Services (WE1)
Subject Alternative Names: onrender.com, *.onrender.com
Validity: ~90 days
Algorithm: ECDSA with SHA256
```

### GCP Cloud Run Certificate
```
Subject: CN=*.a.run.app
Issuer: Google Trust Services (WR2)
Subject Alternative Names: Extensive list covering all GCP regions
Validity: ~90 days
Algorithm: SHA256 with RSA
```

### Your Certbot Certificate (Expected)
```
Subject: CN=yourdomain.com
Issuer: Let's Encrypt (R3 or R10)
Subject Alternative Names: yourdomain.com
Validity: 90 days (auto-renewed)
Algorithm: ECDSA or RSA
```

**Key Insight:** All three certificates are functionally equivalent for WSS support. The issue is NOT the certificate itself, but the platform configuration and WebSocket handling.

---

## 10. Why Nginx + Certbot Will Work

### Comparison

| Aspect | Cloudflare Proxy | GCP Cloud Run | Vultr + Nginx |
|--------|------------------|---------------|---------------|
| **SSL Provider** | Cloudflare | Google Trust Services | Let's Encrypt |
| **WSS Support** | Yes (with limits) | Yes (native) | Yes (full control) |
| **Latency** | High (3 hops) | Medium | Low (1 hop) |
| **Timeout Control** | Limited | Limited | Full control |
| **Auto-renewal** | Automatic | Automatic | Automatic (Certbot) |
| **Cost** | Free (proxy tier) | Pay-per-use | Fixed VPS cost |
| **Configuration** | Limited | Medium | Full |

### Why Certbot Works for WSS

1. **Standard TLS/SSL** - Let's Encrypt certificates are identical in function to commercial certs
2. **Trusted by all clients** - EV chargers trust the Let's Encrypt root CA
3. **Proper certificate chain** - Certbot configures intermediate certificates correctly
4. **Auto-renewal** - Zero manual intervention every 90 days
5. **Industry standard** - Used by millions of production WebSocket applications

---

## Summary

This plan provides a **complete, production-ready migration** from Cloudflare-proxied to direct SSL termination with Nginx. The approach:

1. **Zero-downtime** - Run new setup in parallel, test before switching
2. **Reversible** - Can rollback to Cloudflare if issues arise
3. **Industry-standard** - Uses proven Nginx + Certbot architecture
4. **OCPP-optimized** - Configured for long-lived WebSocket connections
5. **Maintainable** - Auto-renewing certificates, clear monitoring

**Expected Results:**
- ✓ Chargers connect reliably via WSS
- ✓ Latency reduced by 60-80% (no Cloudflare hops)
- ✓ Full control over WebSocket timeouts
- ✓ Professional SSL/TLS configuration
- ✓ Auto-renewing certificates (no manual intervention)

---

## Next Steps

1. Review this plan and adjust domain names/paths as needed
2. Schedule a maintenance window for implementation
3. Ensure you have backup access to the server
4. Begin with Phase 1: Prerequisites & Preparation
5. Follow each phase sequentially, validating before proceeding

Good luck with the migration!
