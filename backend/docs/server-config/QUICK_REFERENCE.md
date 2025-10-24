# OCPP Server - Quick Reference Card

## 🚀 Quick Commands

### Service Management
```bash
# Start service
sudo systemctl start ocpp-server

# Stop service
sudo systemctl stop ocpp-server

# Restart service
sudo systemctl restart ocpp-server

# Check status
sudo systemctl status ocpp-server

# Enable on boot
sudo systemctl enable ocpp-server

# View logs (live)
sudo journalctl -u ocpp-server -f
```

### Nginx Management
```bash
# Test config
sudo nginx -t

# Reload (no downtime)
sudo systemctl reload nginx

# Restart
sudo systemctl restart nginx

# Check status
sudo systemctl status nginx
```

### Check Connections
```bash
# What's using port 8080
sudo netstat -tlnp | grep 8080

# Active connections
sudo ss -tn | grep :8080

# Number of connections
sudo netstat -an | grep :8080 | grep ESTABLISHED | wc -l
```

### View Logs
```bash
# OCPP service logs (live)
sudo journalctl -u ocpp-server -f

# Nginx access log
sudo tail -f /var/log/nginx/ocpp_access.log

# Nginx error log
sudo tail -f /var/log/nginx/ocpp_error.log

# Last 100 log entries
sudo journalctl -u ocpp-server -n 100

# Logs from today
sudo journalctl -u ocpp-server --since today
```

### SSL Certificate
```bash
# View certificates
sudo certbot certificates

# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal

# Check expiry
echo | openssl s_client -connect lyncpower.com:443 2>/dev/null | openssl x509 -noout -dates
```

### DNS & Connectivity
```bash
# Check DNS
nslookup lyncpower.com
dig lyncpower.com +short

# Test HTTPS
curl -I https://lyncpower.com

# Test API
curl https://lyncpower.com/api/
```

## 📁 Important File Locations

```
# Nginx Configuration
/etc/nginx/sites-available/ocpp-server
/etc/nginx/sites-enabled/ocpp-server
/var/log/nginx/ocpp_access.log
/var/log/nginx/ocpp_error.log

# Systemd Service
/etc/systemd/system/ocpp-server.service

# SSL Certificates
/etc/letsencrypt/live/lyncpower.com/fullchain.pem
/etc/letsencrypt/live/lyncpower.com/privkey.pem

# Application
/root/ocpp-server/backend/  (or your path)
/root/ocpp-server/backend/.venv/
```

## 🔧 Common Tasks

### After Code Changes
```bash
cd /root/ocpp-server/backend
git pull  # or however you deploy code
.venv/bin/pip install -r requirements.txt  # if deps changed
sudo systemctl restart ocpp-server
sudo journalctl -u ocpp-server -f  # watch logs
```

### After Nginx Config Changes
```bash
sudo nano /etc/nginx/sites-available/ocpp-server
sudo nginx -t  # test first!
sudo systemctl reload nginx
```

### Check Everything is Running
```bash
# One-liner status check
sudo systemctl status nginx ocpp-server postgresql redis

# Detailed check
echo "=== Nginx ===" && sudo systemctl status nginx --no-pager
echo "=== OCPP Service ===" && sudo systemctl status ocpp-server --no-pager
echo "=== Port 8080 ===" && sudo netstat -tlnp | grep 8080
echo "=== Certificates ===" && sudo certbot certificates
```

## 🐛 Quick Troubleshooting

### Service Won't Start
```bash
# Check detailed error
sudo journalctl -u ocpp-server -xe

# Check if port already in use
sudo netstat -tlnp | grep 8080

# Test manually
cd /root/ocpp-server/backend
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080
```

### 502 Bad Gateway
```bash
# Is backend running?
sudo systemctl status ocpp-server

# Is it on the right port?
sudo netstat -tlnp | grep 8080
# Should show: tcp 0 0 127.0.0.1:8080

# Backend logs
sudo journalctl -u ocpp-server -f
```

### Can't Connect via WSS
```bash
# Test locally first
curl http://127.0.0.1:8080/

# Check nginx errors
sudo tail -f /var/log/nginx/ocpp_error.log

# Check SSL
openssl s_client -connect lyncpower.com:443 < /dev/null

# Check DNS
nslookup lyncpower.com
```

### High CPU/Memory
```bash
# Check resource usage
htop
# or
top

# Check number of connections
sudo netstat -an | grep :8080 | wc -l

# Restart service
sudo systemctl restart ocpp-server
```

## 🌐 URLs

| Purpose | URL |
|---------|-----|
| **API Root** | https://lyncpower.com/ |
| **API Docs** | https://lyncpower.com/docs |
| **REST API** | https://lyncpower.com/api/ |
| **WebSocket** | wss://lyncpower.com/ocpp/{charger_id} |

## 🔒 Security Checklist

- [ ] Firewall configured (ports 22, 80, 443 only)
- [ ] Service runs as non-root user
- [ ] Secrets in `.env` file (not in service file)
- [ ] `.env` file permissions: `chmod 600 .env`
- [ ] SSL certificate auto-renewal working
- [ ] Regular system updates: `sudo apt update && sudo apt upgrade`
- [ ] Fail2ban installed (optional)
- [ ] Database backups configured

## 📊 Monitoring Commands

```bash
# Service uptime
sudo systemctl status ocpp-server | grep Active

# Check for errors in last hour
sudo journalctl -u ocpp-server --since "1 hour ago" | grep -i error

# Connection count
sudo ss -tn | grep :8080 | wc -l

# Disk space
df -h

# Memory usage
free -h

# Certificate expiry
sudo certbot certificates | grep "Expiry Date"
```

## 🚨 Emergency Procedures

### Service Crashed
```bash
sudo systemctl status ocpp-server
sudo journalctl -u ocpp-server -xe  # view error
sudo systemctl restart ocpp-server
```

### Nginx Down
```bash
sudo nginx -t  # test config
sudo systemctl restart nginx
```

### Certificate Expired
```bash
sudo certbot renew --force-renewal
sudo systemctl reload nginx
```

### Rollback Deployment
```bash
# Stop new version
sudo systemctl stop ocpp-server

# Restore backup service
sudo cp /etc/systemd/system/ocpp-server.service.backup \
       /etc/systemd/system/ocpp-server.service

sudo systemctl daemon-reload
sudo systemctl start ocpp-server
```

## 💡 Performance Tips

```bash
# Increase worker count in service file
ExecStart=... --workers 4  # adjust based on CPU cores

# Monitor worker count
ps aux | grep uvicorn

# Check for slow queries
sudo journalctl -u ocpp-server | grep -i "slow"

# Optimize database
# Connect to PostgreSQL and run VACUUM
psql -h localhost -U your_user -d ocpp_db -c "VACUUM ANALYZE;"
```

## 📞 Support Resources

- **Logs Location**: `/var/log/nginx/` and `journalctl -u ocpp-server`
- **Config Files**: `/etc/nginx/sites-available/ocpp-server`
- **Service File**: `/etc/systemd/system/ocpp-server.service`
- **Deployment Guide**: `backend/docs/server-config/DEPLOYMENT_GUIDE.md`

---

**Quick Health Check:**
```bash
curl -s https://lyncpower.com/ | grep -q "OCPP Central System" && echo "✅ Server OK" || echo "❌ Server Error"
```
