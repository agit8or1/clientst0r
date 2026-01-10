# Cron Job Setup for HuduGlue

This document explains how to set up automated tasks for HuduGlue using cron.

## Website Monitoring

To automatically check website monitors every 5 minutes:

```bash
# Edit crontab
crontab -e

# Add this line:
*/5 * * * * cd /home/administrator && /usr/bin/python3 manage.py check_websites >> /var/log/hudglue_cron.log 2>&1
```

### Alternative: System-wide Cron

Create a file `/etc/cron.d/huduglue`:

```bash
# Website monitoring - every 5 minutes
*/5 * * * * administrator cd /home/administrator && /usr/bin/python3 manage.py check_websites >> /var/log/huduglue_cron.log 2>&1

# Daily cleanup tasks - every day at 2am
0 2 * * * administrator cd /home/administrator && /usr/bin/python3 manage.py cleanup_old_logs >> /var/log/huduglue_cron.log 2>&1
```

### Manual Check

To manually check all websites immediately:

```bash
python manage.py check_websites --force
```

## Recommended Schedule

| Task | Frequency | Command |
|------|-----------|---------|
| Website Monitoring | Every 5 minutes | `python manage.py check_websites` |
| Password Expiration Alerts | Daily at 8am | `python manage.py check_expirations` |
| SSL Certificate Alerts | Daily at 9am | `python manage.py check_ssl_expiry` |
| Audit Log Cleanup | Weekly (Sunday 3am) | `python manage.py cleanup_old_logs --days=90` |
| Database Backup | Daily at 1am | Custom backup script |

## Example Full Crontab

```cron
# HuduGlue Automated Tasks

# Website monitoring - every 5 minutes
*/5 * * * * cd /home/administrator && python3 manage.py check_websites

# Password expiration alerts - daily at 8am
0 8 * * * cd /home/administrator && python3 manage.py check_expirations

# SSL expiration alerts - daily at 9am
0 9 * * * cd /home/administrator && python3 manage.py check_ssl_expiry

# Audit log cleanup - weekly on Sunday at 3am
0 3 * * 0 cd /home/administrator && python3 manage.py cleanup_old_logs --days=90

# Database backup - daily at 1am
0 1 * * * /path/to/backup_script.sh
```

## Troubleshooting

### Cron not running?

1. Check cron service is running:
```bash
sudo systemctl status cron
```

2. Check cron logs:
```bash
tail -f /var/log/huduglue_cron.log
sudo tail -f /var/log/syslog | grep CRON
```

3. Ensure Python environment is correct:
```bash
which python3
# Use the full path in crontab
```

### Permission Issues

Make sure the user running cron has permission to:
- Execute manage.py
- Write to log files
- Access the database

```bash
chmod +x manage.py
sudo touch /var/log/huduglue_cron.log
sudo chown administrator:administrator /var/log/huduglue_cron.log
```
