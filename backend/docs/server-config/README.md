# Server Configuration Files

This directory contains all configuration files and documentation needed to deploy the OCPP server with WSS (WebSocket Secure) support.

## 📁 Files Overview

| File | Purpose | Deploy Location |
|------|---------|-----------------|
| **nginx-ocpp-server.conf** | Nginx reverse proxy config with WSS support | `/etc/nginx/sites-available/ocpp-server` |
| **ocpp-server.service** | Systemd service configuration | `/etc/systemd/system/ocpp-server.service` |
| **DEPLOYMENT_GUIDE.md** | Complete step-by-step deployment guide | Documentation only |
| **QUICK_REFERENCE.md** | Quick command reference | Documentation only |

## 🚀 Quick Start

### Prerequisites
- Vultr server (or any Ubuntu/Debian VPS)
- Domain pointing to your server IP (lyncpower.com → 139.84.209.71)
- SSH access with sudo privileges

### Deployment Steps

1. **Read the deployment guide first:**
   ```bash
   cat DEPLOYMENT_GUIDE.md
   ```

2. **Configure DNS:**
   - Update GoDaddy A record: `@` → `139.84.209.71`
   - Wait for DNS propagation (5-15 mins)

3. **Deploy nginx configuration:**
   ```bash
   sudo cp nginx-ocpp-server.conf /etc/nginx/sites-available/ocpp-server
   sudo ln -s /etc/nginx/sites-available/ocpp-server /etc/nginx/sites-enabled/
   sudo nginx -t
   ```

4. **Get SSL certificate:**
   ```bash
   sudo certbot certonly --standalone -d lyncpower.com
   ```

5. **Update and deploy service configuration:**
   ```bash
   # Edit ocpp-server.service with your actual paths
   sudo cp ocpp-server.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable ocpp-server
   sudo systemctl start ocpp-server
   ```

6. **Start nginx:**
   ```bash
   sudo systemctl start nginx
   ```

7. **Test connection:**
   ```bash
   curl https://lyncpower.com/
   ```

## 📖 Documentation

### For Initial Deployment
Start here: [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)

This comprehensive guide covers:
- Prerequisites and requirements
- DNS configuration
- Server setup and installation
- SSL certificate setup
- Service configuration
- Testing procedures
- Troubleshooting

### For Daily Operations
Use: [QUICK_REFERENCE.md](./QUICK_REFERENCE.md)

Quick reference for:
- Common commands
- Service management
- Log viewing
- Troubleshooting
- Emergency procedures

## 🔧 Configuration Details

### Nginx Configuration (nginx-ocpp-server.conf)

**Key features:**
- HTTP to HTTPS redirect
- WebSocket upgrade for `/ocpp/` endpoint
- Long-lived connection support (3600s timeout)
- REST API proxying
- Modern SSL/TLS configuration
- Security headers

**Upstream backend:**
- FastAPI running on `127.0.0.1:8080`
- Not exposed to internet (nginx is the only entry point)

### Service Configuration (ocpp-server.service)

**Key settings:**
- Binds to `127.0.0.1:8080` (localhost only)
- Runs with 2 uvicorn workers
- Auto-restart on failure
- Depends on PostgreSQL and Redis

**Important:** Update these before deploying:
- User and Group
- WorkingDirectory
- Environment PATH
- Database credentials
- API keys

## 🌐 Architecture

```
Internet
    ↓
HTTPS/WSS (Port 443)
    ↓
Nginx (SSL Termination + Reverse Proxy)
    ↓
HTTP/WS (Port 8080, localhost only)
    ↓
FastAPI + Uvicorn
    ↓
PostgreSQL + Redis
```

**Security benefits:**
- FastAPI not exposed to internet
- Nginx handles all SSL/TLS
- Firewall only allows 22, 80, 443
- Let's Encrypt auto-renewal

## 🔒 Security Checklist

Before going live:

- [ ] Service runs as non-root user
- [ ] Secrets in `.env` file (chmod 600)
- [ ] Firewall configured (UFW)
- [ ] SSL certificate obtained
- [ ] Auto-renewal tested
- [ ] Service binds to 127.0.0.1 only
- [ ] Regular backups configured

## 🧪 Testing

### Test WSS Connection (from local machine)

**Using Python:**
```python
import asyncio
import websockets
import json

async def test():
    uri = "wss://lyncpower.com/ocpp/TEST_CHARGER"
    async with websockets.connect(uri) as ws:
        msg = [2, "123", "BootNotification",
               {"chargePointVendor": "Test", "chargePointModel": "Model"}]
        await ws.send(json.dumps(msg))
        response = await ws.recv()
        print(response)

asyncio.run(test())
```

**Using curl:**
```bash
# Test HTTPS
curl https://lyncpower.com/

# Test API
curl https://lyncpower.com/api/

# View docs
open https://lyncpower.com/docs
```

## 🐛 Troubleshooting

### Common Issues

**502 Bad Gateway:**
```bash
# Check if backend is running
sudo systemctl status ocpp-server
sudo netstat -tlnp | grep 8080
```

**Can't connect via WSS:**
```bash
# Check nginx logs
sudo tail -f /var/log/nginx/ocpp_error.log

# Check backend logs
sudo journalctl -u ocpp-server -f
```

**Certificate errors:**
```bash
# Check certificate
sudo certbot certificates

# Renew if needed
sudo certbot renew
```

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) troubleshooting section for more details.

## 📞 Support

For detailed help:
1. Check [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) troubleshooting section
2. View service logs: `sudo journalctl -u ocpp-server -f`
3. View nginx logs: `sudo tail -f /var/log/nginx/ocpp_error.log`
4. Test nginx config: `sudo nginx -t`

## 📝 Customization

### Change Domain

Update in:
- `nginx-ocpp-server.conf`: `server_name lyncpower.com;`
- SSL certificate command: `sudo certbot ... -d yourdomain.com`

### Change Port

If you need to use a different backend port:
1. Update `nginx-ocpp-server.conf`: `server 127.0.0.1:YOUR_PORT;`
2. Update `ocpp-server.service`: `--port YOUR_PORT`
3. Reload both services

### Add Subdomains

To add `api.lyncpower.com` or `ocpp.lyncpower.com`:
1. Add DNS A record
2. Get new certificate: `sudo certbot ... -d lyncpower.com -d api.lyncpower.com`
3. Update nginx `server_name` directive

## 🔄 Updates

### Update nginx config:
```bash
sudo nano /etc/nginx/sites-available/ocpp-server
sudo nginx -t
sudo systemctl reload nginx
```

### Update service config:
```bash
sudo nano /etc/systemd/system/ocpp-server.service
sudo systemctl daemon-reload
sudo systemctl restart ocpp-server
```

### Deploy code changes:
```bash
cd /root/ocpp-server/backend
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart ocpp-server
```

## 📊 Monitoring

### Key Metrics to Watch

```bash
# Connection count
sudo ss -tn | grep :8080 | wc -l

# Service uptime
sudo systemctl status ocpp-server | grep Active

# Certificate expiry
sudo certbot certificates | grep "Expiry Date"

# Disk space
df -h

# Memory
free -h
```

## 🎯 Production URLs

After deployment, your OCPP server will be accessible at:

| Service | URL |
|---------|-----|
| **API Root** | https://lyncpower.com/ |
| **API Documentation** | https://lyncpower.com/docs |
| **REST API** | https://lyncpower.com/api/* |
| **OCPP WebSocket** | wss://lyncpower.com/ocpp/{charger_id} |

## 📚 Additional Resources

- **Nginx Documentation**: https://nginx.org/en/docs/
- **Let's Encrypt**: https://letsencrypt.org/docs/
- **Systemd Service**: https://www.freedesktop.org/software/systemd/man/systemd.service.html
- **FastAPI**: https://fastapi.tiangolo.com/
- **OCPP 1.6**: https://www.openchargealliance.org/protocols/ocpp-16/

---

**Ready to deploy? Start with [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** 🚀
