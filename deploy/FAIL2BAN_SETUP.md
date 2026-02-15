# Fail2Ban Setup for Client St0r

This guide explains how to set up Fail2Ban to protect your Client St0r installation from brute-force attacks.

## What is Fail2Ban?

Fail2Ban monitors log files for suspicious activity (like repeated failed login attempts) and automatically blocks offending IP addresses using firewall rules.

## Quick Setup

### Option 1: Automatic Setup (via Web Interface - Recommended)

1. Log into Client St0r as an admin
2. Go to **Settings → Security → Fail2Ban**
3. Click **"Auto-Install Fail2Ban"**
4. The system will automatically:
   - Install fail2ban package
   - Configure the filter and jail
   - Start the service
   - Set up passwordless sudo access

### Option 2: Manual Setup

If you prefer manual installation or the automatic setup fails:

#### Step 1: Install Fail2Ban

```bash
sudo apt-get update
sudo apt-get install -y fail2ban
```

#### Step 2: Copy Filter Configuration

```bash
sudo cp /path/to/clientst0r/deploy/clientst0r-fail2ban-filter.conf /etc/fail2ban/filter.d/clientst0r.conf
```

#### Step 3: Add Jail Configuration

```bash
sudo bash -c 'cat /path/to/clientst0r/deploy/clientst0r-fail2ban-jail.conf >> /etc/fail2ban/jail.local'
```

Or manually add the jail configuration to `/etc/fail2ban/jail.local`

#### Step 4: Restart Fail2Ban

```bash
sudo systemctl restart fail2ban
sudo systemctl enable fail2ban
```

#### Step 5: Verify Setup

```bash
sudo fail2ban-client status clientst0r
```

You should see output showing the jail is active with 0 current bans.

## Configuration Details

### Filter Rules

The filter (`/etc/fail2ban/filter.d/clientst0r.conf`) detects:
- Django-axes blocked login attempts
- Django-axes account lockouts
- Invalid HTTP_HOST header attempts (potential host header injection)

### Jail Settings

- **Port:** HTTP (80) and HTTPS (443)
- **Max Retries:** 5 failed attempts
- **Find Time:** 600 seconds (10 minutes)
- **Ban Time:** 3600 seconds (1 hour)
- **Log Paths:**
  - `/var/log/itdocs/gunicorn-access.log`
  - `/var/log/itdocs/gunicorn-error.log`

### Customization

Edit `/etc/fail2ban/jail.local` to customize:

```ini
[clientst0r]
maxretry = 3          # Fewer attempts before ban
findtime = 300        # Shorter detection window (5 minutes)
bantime  = 7200       # Longer ban time (2 hours)
```

After changes: `sudo systemctl restart fail2ban`

## Monitoring

### Check Jail Status

```bash
sudo fail2ban-client status clientst0r
```

### View Banned IPs

```bash
sudo fail2ban-client get clientst0r banned
```

### Unban an IP

```bash
sudo fail2ban-client set clientst0r unbanip 192.168.1.100
```

### View Fail2Ban Logs

```bash
sudo tail -f /var/log/fail2ban.log
```

## Testing

### Trigger a Ban (for testing)

1. Try logging in with wrong password 5 times
2. Check jail status: `sudo fail2ban-client status clientst0r`
3. Your IP should be in the banned list
4. Unban yourself: `sudo fail2ban-client set clientst0r unbanip YOUR_IP`

### Whitelist Your IP

To prevent accidentally banning yourself, add your IP to `/etc/fail2ban/jail.local`:

```ini
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 192.168.1.100
```

## Troubleshooting

### Jail Not Starting

Check configuration syntax:
```bash
sudo fail2ban-client -t
```

### No Bans Happening

1. Verify log files exist and are readable:
   ```bash
   ls -la /var/log/itdocs/
   ```

2. Test filter manually:
   ```bash
   sudo fail2ban-regex /var/log/itdocs/gunicorn-error.log /etc/fail2ban/filter.d/clientst0r.conf
   ```

3. Check fail2ban logs:
   ```bash
   sudo tail -100 /var/log/fail2ban.log
   ```

### Permissions Issues

Ensure fail2ban can read log files:
```bash
sudo chmod 644 /var/log/itdocs/*.log
```

## Integration with Client St0r

Client St0r's built-in Fail2Ban management (Settings → Security) provides:
- Real-time ban statistics
- One-click IP unbanning
- Ban history and analytics
- Automatic jail status monitoring

This requires sudoers configuration to work passwordlessly. The installer sets this up automatically.

## Security Best Practices

1. **Monitor Regularly:** Check banned IPs weekly
2. **Adjust Thresholds:** Fine-tune maxretry based on your environment
3. **Whitelist Known IPs:** Add your office/home IPs to ignoreip
4. **Enable Email Alerts:** Configure fail2ban to email on bans
5. **Review Logs:** Regularly check for attack patterns

## Support

For issues or questions:
- GitHub Issues: https://github.com/agit8or1/clientst0r/issues
- Documentation: See main README.md

## Files Reference

- **Filter:** `/etc/fail2ban/filter.d/clientst0r.conf`
- **Jail:** `/etc/fail2ban/jail.local` (add clientst0r section)
- **Logs:** `/var/log/fail2ban.log`
- **Source Files:** `/path/to/clientst0r/deploy/`
  - `clientst0r-fail2ban-filter.conf`
  - `clientst0r-fail2ban-jail.conf`
  - `clientst0r-fail2ban-sudoers`
