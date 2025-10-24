# OCPP Server WSS Deployment Guide

Complete guide to deploy OCPP server with WSS (WebSocket Secure) support on Vultr using Nginx and Let's Encrypt.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [DNS Configuration](#dns-configuration)
3. [Server Setup](#server-setup)
4. [SSL Certificate](#ssl-certificate)
5. [Service Configuration](#service-configuration)
6. [Testing](#testing)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Server Requirements
- **VPS**: Vultr instance (or any Ubuntu/Debian server)
- **IP**: `139.84.209.71` (your Vultr IP)
- **Domain**: `lyncpower.com` (pointing to your Vultr IP)
- **OS**: Ubuntu 20.04+ or Debian 11+
- **Memory**: 2GB minimum, 4GB recommended
- **Disk**: 20GB minimum

### Software Requirements
- Python 3.11+
- PostgreSQL (database)
- Redis (connection state)
- Nginx (reverse proxy)
- Certbot (SSL certificates)

### Access Requirements
- SSH access to Vultr server
- sudo/root privileges
- GoDaddy account (for DNS configuration)

---

## DNS Configuration

### Step 1: Configure GoDaddy DNS

1. Log in to **GoDaddy**
2. Go to **My Products** → **Domains** → `lyncpower.com`
3. Click **DNS** or **Manage DNS**

### Step 2: Update A Record

**Option A: Use Main Domain (Recommended)**
```
Type: A
Name: @
Data: 139.84.209.71
TTL: 600 seconds
```

Result: `lyncpower.com` → `139.84.209.71`

**Option B: Use Subdomain**
```
Type: A
Name: ocpp
Data: 139.84.209.71
TTL: 600 seconds
```

Result: `ocpp.lyncpower.com` → `139.84.209.71`

### Step 3: Remove Conflicting Records

**IMPORTANT**: Delete the "Parked" A record if it exists:
```
a    @    Parked    600 seconds  [DELETE THIS]
```

### Step 4: Verify DNS Propagation

Wait 5-15 minutes, then test:

```bash
# From your local machine
nslookup lyncpower.com

# Should show:
# Name: lyncpower.com
# Address: 139.84.209.71

# Alternative test
dig lyncpower.com +short
# Should output: 139.84.209.71
```

---

## Server Setup

### Step 1: SSH into Vultr Server

```bash
ssh root@139.84.209.71
```

### Step 2: Update System

```bash
sudo apt update
sudo apt upgrade -y
```

### Step 3: Install Required Software

```bash
# Install Nginx
sudo apt install nginx -y

# Install Certbot (for Let's Encrypt SSL)
sudo apt install certbot python3-certbot-nginx -y

# Install PostgreSQL (if not already installed)
sudo apt install postgresql postgresql-contrib -y

# Install Redis (if not already installed)
sudo apt install redis-server -y

# Verify installations
nginx -v
certbot --version
psql --version
redis-cli --version
```

### Step 4: Configure Firewall

```bash
# Allow SSH (if not already allowed)
sudo ufw allow 22/tcp

# Allow HTTP (needed for Let's Encrypt validation)
sudo ufw allow 80/tcp

# Allow HTTPS (for WSS and API)
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

Expected output:
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
```

---

## SSL Certificate

### Step 1: Stop Services Using Port 80

```bash
# Check what's using port 80
sudo netstat -tlnp | grep :80

# If OCPP server is running, stop it
sudo systemctl stop ocpp-server

# If nginx is running, stop it
sudo systemctl stop nginx
```

### Step 2: Obtain SSL Certificate

```bash
# Get certificate using standalone mode
sudo certbot certonly --standalone -d lyncpower.com

# Follow prompts:
# - Enter email: your-email@example.com
# - Agree to terms: Y
# - Share email with EFF: Y or N (your choice)
```

**Expected output:**
```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/lyncpower.com/fullchain.pem
Key is saved at:         /etc/letsencrypt/live/lyncpower.com/privkey.pem
This certificate expires on 2026-01-08.
```

### Step 3: Verify Certificate

```bash
sudo ls -la /etc/letsencrypt/live/lyncpower.com/

# Should show:
# fullchain.pem -> ../../archive/lyncpower.com/fullchain1.pem
# privkey.pem -> ../../archive/lyncpower.com/privkey1.pem
# cert.pem
# chain.pem
```

### Step 4: Test Auto-Renewal

```bash
# Dry run renewal
sudo certbot renew --dry-run

# Expected output:
# Congratulations, all simulated renewals succeeded
```

---

## Service Configuration

### Step 1: Deploy Nginx Configuration

```bash
# Create certbot directory
sudo mkdir -p /var/www/certbot

# Copy nginx config from this repo
sudo cp backend/docs/server-config/nginx-ocpp-server.conf /etc/nginx/sites-available/ocpp-server

# OR create it manually:
sudo nano /etc/nginx/sites-available/ocpp-server
# Paste contents from nginx-ocpp-server.conf file
```

### Step 2: Enable Nginx Site

```bash
# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Enable OCPP server site
sudo ln -s /etc/nginx/sites-available/ocpp-server /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Should output:
# nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### Step 3: Start Nginx

```bash
sudo systemctl enable nginx
sudo systemctl start nginx
sudo systemctl status nginx

# Should show: active (running)
```

### Step 4: Deploy OCPP Service Configuration

**First, check your current service configuration:**

```bash
# Check if service exists
sudo systemctl status ocpp-server

# View current configuration
sudo cat /etc/systemd/system/ocpp-server.service
```

**Update the service to bind to 127.0.0.1:8080:**

```bash
# Backup existing service
sudo cp /etc/systemd/system/ocpp-server.service /etc/systemd/system/ocpp-server.service.backup

# Edit service file
sudo nano /etc/systemd/system/ocpp-server.service
```

**Key changes needed in the service file:**

1. Change `ExecStart` to:
```ini
ExecStart=/path/to/your/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080 --workers 2
```

2. Ensure these are set:
```ini
WorkingDirectory=/root/ocpp-server/backend  # Your actual path
Environment="PATH=/root/ocpp-server/backend/.venv/bin:$PATH"  # Your venv path
```

**Example complete service file** (use `backend/docs/server-config/ocpp-server.service` as reference):

```ini
[Unit]
Description=OCPP Central System API
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=root  # Change to your app user
WorkingDirectory=/root/ocpp-server/backend  # Your path
Environment="PATH=/root/ocpp-server/backend/.venv/bin:$PATH"
Environment="DATABASE_URL=postgresql://user:pass@localhost/ocpp_db"
Environment="REDIS_URL=redis://localhost:6379"

ExecStart=/root/ocpp-server/backend/.venv/bin/uvicorn main:app \
    --host 127.0.0.1 \
    --port 8080 \
    --workers 2

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Step 5: Start OCPP Service

```bash
# Reload systemd to pick up changes
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable ocpp-server

# Start service
sudo systemctl start ocpp-server

# Check status
sudo systemctl status ocpp-server

# Verify it's listening on 127.0.0.1:8080
sudo netstat -tlnp | grep 8080

# Should show:
# tcp  0  0  127.0.0.1:8080  0.0.0.0:*  LISTEN  12345/python
```

---

## Testing

### Test 1: HTTP to HTTPS Redirect

```bash
curl -I http://lyncpower.com

# Expected output:
# HTTP/1.1 301 Moved Permanently
# Location: https://lyncpower.com/
```

### Test 2: HTTPS API Endpoint

```bash
curl https://lyncpower.com/

# Expected output (JSON):
# {
#   "message": "OCPP Central System API",
#   "version": "0.1.0",
#   "docs": "/docs",
#   "ocpp_endpoint": "/ocpp/{charge_point_id}"
# }
```

### Test 3: API Documentation

Open in browser:
```
https://lyncpower.com/docs
```

Should show FastAPI Swagger documentation.

### Test 4: WebSocket Connection (from local machine)

**Option A: Using websocat**

```bash
# Install websocat (if not installed)
# macOS: brew install websocat
# Ubuntu: apt install websocat

# Test WSS connection
websocat wss://lyncpower.com/ocpp/TEST_CHARGER_01
```

**Option B: Using Python script**

Create `test_wss.py` on your local machine:

```python
import asyncio
import websockets
import json

async def test_ocpp_connection():
    uri = "wss://lyncpower.com/ocpp/TEST_CHARGER_01"

    try:
        async with websockets.connect(uri) as websocket:
            print(f"✅ Connected to {uri}")

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

            print("✅ WebSocket test successful!")

    except Exception as e:
        print(f"❌ Connection failed: {e}")

asyncio.run(test_ocpp_connection())
```

Run the test:
```bash
python test_wss.py
```

Expected output:
```
✅ Connected to wss://lyncpower.com/ocpp/TEST_CHARGER_01
→ Sent: [2, '12345', 'BootNotification', {...}]
← Received: [3, '12345', {'currentTime': '2025-10-10T...', 'status': 'Accepted', ...}]
✅ WebSocket test successful!
```

### Test 5: Check SSL Certificate

```bash
# From local machine
openssl s_client -connect lyncpower.com:443 -servername lyncpower.com < /dev/null

# Look for:
# - subject=CN=lyncpower.com
# - issuer=C=US, O=Let's Encrypt
# - Verify return code: 0 (ok)
```

---

## Monitoring

### Check Service Status

```bash
# OCPP service status
sudo systemctl status ocpp-server

# Nginx status
sudo systemctl status nginx

# View OCPP logs (live)
sudo journalctl -u ocpp-server -f

# View Nginx access logs
sudo tail -f /var/log/nginx/ocpp_access.log

# View Nginx error logs
sudo tail -f /var/log/nginx/ocpp_error.log
```

### Check Active Connections

```bash
# Number of connections to backend
sudo netstat -an | grep :8080 | grep ESTABLISHED | wc -l

# Active WebSocket connections
sudo ss -tn | grep :8080
```

### Check Certificate Expiry

```bash
sudo certbot certificates

# Shows certificate details and expiry date
```

---

## Troubleshooting

### Problem: Nginx config test fails

```bash
# Check syntax errors
sudo nginx -t

# View detailed error
sudo nginx -t 2>&1 | less
```

**Common issues:**
- Missing semicolons
- SSL certificate paths wrong
- Duplicate server_name directives

### Problem: Can't connect via HTTPS

```bash
# Check if nginx is running
sudo systemctl status nginx

# Check if port 443 is open
sudo netstat -tlnp | grep :443

# Check firewall
sudo ufw status

# Check SSL certificate
sudo ls -la /etc/letsencrypt/live/lyncpower.com/
```

### Problem: OCPP service won't start

```bash
# View detailed errors
sudo journalctl -u ocpp-server -xe

# Check if port 8080 is already used
sudo netstat -tlnp | grep 8080

# Verify Python environment
/root/ocpp-server/backend/.venv/bin/python --version

# Test service manually
cd /root/ocpp-server/backend
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080
```

### Problem: WebSocket connection fails

**Check backend logs:**
```bash
sudo journalctl -u ocpp-server -f
```

**Check nginx error logs:**
```bash
sudo tail -f /var/log/nginx/ocpp_error.log
```

**Common issues:**
- Backend not listening on 127.0.0.1:8080
- Nginx not configured for WebSocket upgrade
- Firewall blocking port 443
- DNS not resolving correctly

### Problem: 502 Bad Gateway

```bash
# Backend not running
sudo systemctl status ocpp-server

# Backend crashed
sudo journalctl -u ocpp-server -xe

# Wrong port configuration
sudo netstat -tlnp | grep 8080
# Should show: 127.0.0.1:8080
```

---

## Production Checklist

Before going live, verify:

- [ ] DNS resolves correctly: `nslookup lyncpower.com`
- [ ] SSL certificate valid: `sudo certbot certificates`
- [ ] Nginx running: `sudo systemctl status nginx`
- [ ] OCPP service running: `sudo systemctl status ocpp-server`
- [ ] Service binds to localhost only: `sudo netstat -tlnp | grep 8080`
- [ ] HTTP redirects to HTTPS: `curl -I http://lyncpower.com`
- [ ] HTTPS API works: `curl https://lyncpower.com/`
- [ ] WSS connection works (test script above)
- [ ] Logs are accessible: `sudo journalctl -u ocpp-server -f`
- [ ] Auto-renewal configured: `sudo certbot renew --dry-run`
- [ ] Services start on boot: `sudo systemctl is-enabled ocpp-server nginx`

---

## Charger Configuration

Update your OCPP chargers with:

**WebSocket URL:**
```
wss://lyncpower.com/ocpp/{CHARGER_ID}
```

**Example:**
- Charger ID: `LYNC_CHARGER_001`
- URL: `wss://lyncpower.com/ocpp/LYNC_CHARGER_001`

**Connection Parameters:**
- Protocol: OCPP 1.6J
- Security: TLS 1.2+
- Heartbeat Interval: 300 seconds (default from your main.py)

---

## Maintenance

### Restart Services

```bash
# After code changes
sudo systemctl restart ocpp-server

# After nginx config changes
sudo nginx -t && sudo systemctl reload nginx

# Full restart
sudo systemctl restart ocpp-server nginx
```

### Update SSL Certificate (Automatic)

Certbot runs automatically via systemd timer:

```bash
# Check timer status
sudo systemctl status certbot.timer

# Manual renewal (if needed)
sudo certbot renew

# Test renewal
sudo certbot renew --dry-run
```

### View Logs

```bash
# Last 100 lines
sudo journalctl -u ocpp-server -n 100

# Follow logs (live)
sudo journalctl -u ocpp-server -f

# Logs from today
sudo journalctl -u ocpp-server --since today

# Logs from specific time
sudo journalctl -u ocpp-server --since "2025-10-10 10:00:00"
```

---

## Security Recommendations

1. **Don't run as root**: Create a dedicated user for the OCPP service
2. **Use EnvironmentFile**: Store secrets in `.env` file with `chmod 600`
3. **Enable fail2ban**: Protect against brute force attacks
4. **Regular updates**: Keep system and packages updated
5. **Monitor logs**: Set up log rotation and monitoring
6. **Backup**: Regular database and configuration backups

---

## Support

For issues or questions:
- Check troubleshooting section above
- View logs: `sudo journalctl -u ocpp-server -f`
- Check nginx errors: `sudo tail -f /var/log/nginx/ocpp_error.log`
- Test configuration: `sudo nginx -t`

---

**Deployment completed! 🚀**

Your OCPP server is now accessible via:
- **API**: `https://lyncpower.com/api/`
- **Docs**: `https://lyncpower.com/docs`
- **WSS**: `wss://lyncpower.com/ocpp/{charger_id}`
