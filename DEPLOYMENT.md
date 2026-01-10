# Production Deployment Checklist

## Pre-Deployment

- [ ] **Server Requirements**
  - Ubuntu 20.04+ server
  - Minimum 2GB RAM, 2 CPU cores
  - 20GB+ disk space
  - Root/sudo access

- [ ] **Domain & DNS**
  - Domain name registered
  - A record pointing to server IP
  - (Optional) AAAA record for IPv6

## Installation Steps

### 1. Copy Files to Server
```bash
# On your server
cd /opt
sudo mkdir itdocs
sudo chown $(whoami):$(whoami) itdocs

# Copy all files from this directory to /opt/itdocs
# Or use git clone if you have a repository
```

### 2. Generate Secrets
```bash
cd /opt/itdocs

# Generate SECRET_KEY
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Generate APP_MASTER_KEY (32 bytes, base64)
python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"

# Generate API_KEY_SECRET
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3. Configure Environment
```bash
cp .env.example .env
nano .env
```

Set these values:
```
SECRET_KEY=<from step 2>
APP_MASTER_KEY=<from step 2>
API_KEY_SECRET=<from step 2>
DB_PASSWORD=<create a strong password>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DEBUG=False
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

### 4. Run Bootstrap
```bash
chmod +x scripts/bootstrap_ubuntu.sh
./scripts/bootstrap_ubuntu.sh
```

Follow prompts to:
- Create superuser
- Seed demo data (optional)

### 5. Create Service User
```bash
sudo useradd -r -s /bin/bash -d /opt/itdocs itdocs
sudo chown -R itdocs:itdocs /opt/itdocs
sudo chown -R itdocs:itdocs /var/lib/itdocs
sudo chown -R itdocs:itdocs /var/log/itdocs
```

### 6. Install Gunicorn Service
```bash
sudo cp deploy/itdocs-gunicorn.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable itdocs-gunicorn
sudo systemctl start itdocs-gunicorn
sudo systemctl status itdocs-gunicorn
```

**Expected output**: `active (running)`

### 7. Install PSA Sync Timer
```bash
sudo cp deploy/itdocs-psa-sync.service /etc/systemd/system/
sudo cp deploy/itdocs-psa-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable itdocs-psa-sync.timer
sudo systemctl start itdocs-psa-sync.timer
sudo systemctl status itdocs-psa-sync.timer
```

### 8. Configure Nginx
```bash
# Copy and edit
sudo cp deploy/nginx-itdocs.conf /etc/nginx/sites-available/itdocs
sudo nano /etc/nginx/sites-available/itdocs
# Change server_name to your domain

# Enable site
sudo ln -s /etc/nginx/sites-available/itdocs /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 9. Configure Firewall
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
sudo ufw status
```

### 10. Install SSL Certificate
```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Test auto-renewal
sudo certbot renew --dry-run
```

## Post-Deployment

### Verify Installation
```bash
# Check Gunicorn
sudo systemctl status itdocs-gunicorn
sudo journalctl -u itdocs-gunicorn -n 50

# Check Nginx
sudo systemctl status nginx
sudo nginx -t

# Check logs
sudo tail -f /var/log/itdocs/django.log
sudo tail -f /var/log/nginx/itdocs-access.log
sudo tail -f /var/log/nginx/itdocs-error.log

# Test web access
curl -I https://yourdomain.com
```

### Access the Platform
1. Navigate to: `https://yourdomain.com`
2. Login with created superuser
3. Set up 2FA (REQUIRED)
4. Create organization
5. Add users and assign roles

### Configure First PSA Integration

1. **ConnectWise Manage:**
   - Go to Integrations → Add Integration
   - Select "ConnectWise Manage"
   - Base URL: `https://your-cw-site.com` (or cloud URL)
   - Credentials JSON:
   ```json
   {
     "company_id": "YourCompanyID",
     "public_key": "YourPublicKey",
     "private_key": "YourPrivateKey",
     "client_id": "itdocs"
   }
   ```
   - Click "Test" to verify
   - Enable sync, configure entities
   - Click "Sync" for immediate sync

2. **Autotask PSA:**
   - Go to Integrations → Add Integration
   - Select "Autotask PSA"
   - Base URL: Your zone URL (e.g., `https://webservices5.autotask.net`)
   - Credentials JSON:
   ```json
   {
     "username": "api@yourusername.com",
     "secret": "YourAPISecret",
     "integration_code": "ITDOCS"
   }
   ```
   - Click "Test" to verify
   - Enable sync, configure entities
   - Click "Sync" for immediate sync

### Create First API Key
1. Login as admin
2. Navigate to Profile or Admin → API Keys
3. Create new API key with appropriate role
4. **COPY THE KEY IMMEDIATELY** (shown only once)
5. Test with curl:
```bash
curl -H "Authorization: Bearer itdocs_live_YOUR_KEY" \
  https://yourdomain.com/api/organizations/
```

## Maintenance

### Regular Tasks
```bash
# Check service status
sudo systemctl status itdocs-gunicorn
sudo systemctl status itdocs-psa-sync.timer

# View sync logs
sudo journalctl -u itdocs-psa-sync -n 100

# Manual sync
cd /opt/itdocs
source venv/bin/activate
python manage.py sync_psa

# Backup database
sudo mysqldump -u itdocs -p itdocs > backup_$(date +%Y%m%d).sql

# Update code (after pulling changes)
cd /opt/itdocs
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart itdocs-gunicorn
```

### Monitoring
```bash
# Real-time logs
sudo journalctl -u itdocs-gunicorn -f
sudo tail -f /var/log/itdocs/django.log
sudo tail -f /var/log/nginx/itdocs-access.log

# Check disk space
df -h

# Check memory
free -h

# Check connections
sudo netstat -tlnp | grep gunicorn
```

### Troubleshooting

**502 Bad Gateway:**
```bash
# Check Gunicorn
sudo systemctl status itdocs-gunicorn
sudo journalctl -u itdocs-gunicorn -n 50

# Check socket
ls -la /opt/itdocs/gunicorn.sock

# Check permissions
sudo chown -R itdocs:itdocs /opt/itdocs
```

**PSA Sync Failing:**
```bash
# Check credentials in Django admin
# Manual test:
cd /opt/itdocs
source venv/bin/activate
python manage.py sync_psa --connection-id=1 -v 2
```

**Database Connection Issues:**
```bash
# Test DB connection
mysql -u itdocs -p itdocs

# Check Django can connect
cd /opt/itdocs
source venv/bin/activate
python manage.py dbshell
```

## Security Hardening

- [ ] Strong passwords for all users
- [ ] 2FA enforced (default)
- [ ] Regular security updates: `sudo apt-get update && sudo apt-get upgrade`
- [ ] Fail2ban installed (optional): `sudo apt-get install fail2ban`
- [ ] Database backups configured
- [ ] Log rotation configured
- [ ] Monitor audit logs regularly
- [ ] Review API key usage
- [ ] Keep dependencies updated

## Backup Strategy

### Daily Automated Backup
```bash
# Create backup script
sudo nano /opt/itdocs/scripts/backup.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/itdocs"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Database
mysqldump -u itdocs -p$DB_PASSWORD itdocs | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Files
tar -czf $BACKUP_DIR/uploads_$DATE.tar.gz /var/lib/itdocs/uploads

# Keep last 30 days
find $BACKUP_DIR -type f -mtime +30 -delete
```

```bash
# Make executable
sudo chmod +x /opt/itdocs/scripts/backup.sh

# Add to crontab
sudo crontab -e
# Add: 0 2 * * * /opt/itdocs/scripts/backup.sh
```

## Success Checklist

After deployment, verify:

- [ ] Platform accessible at https://yourdomain.com
- [ ] SSL certificate valid and auto-renewing
- [ ] Can login with superuser
- [ ] 2FA working
- [ ] Can create organization
- [ ] Can add users and set roles
- [ ] Can create assets
- [ ] Can create passwords (encrypted)
- [ ] Can reveal passwords
- [ ] Can create documents
- [ ] Can upload attachments
- [ ] PSA integration connects successfully
- [ ] PSA sync works (test manually)
- [ ] PSA sync timer running
- [ ] API authentication works
- [ ] Audit logs recording actions
- [ ] No errors in logs
- [ ] Services auto-start on reboot

## Support

For issues:
1. Check logs: `/var/log/itdocs/` and `journalctl -u itdocs-gunicorn`
2. Review README.md troubleshooting section
3. Verify all environment variables in .env
4. Check service status: `sudo systemctl status itdocs-gunicorn`
5. Test database connection
6. Verify file permissions

---

**Platform Status:** Production Ready ✅
**Last Updated:** 2026-01-09
