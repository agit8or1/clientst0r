# OS Package Security Scanner

The OS Package Security Scanner monitors your system for outdated packages and security updates across Debian/Ubuntu (apt), Red Hat/CentOS (yum/dnf), and Arch Linux (pacman).

## Features

- **Security Update Detection**: Identifies packages with available security patches
- **Multi-Package Manager Support**: Works with apt, yum, dnf, and pacman
- **Web Dashboard**: View scan history and security status via web interface
- **API Access**: RESTful API for integration with monitoring tools
- **Automated Scheduling**: Run scans automatically using systemd timers
- **Dashboard Widget**: Security overview on main security dashboard

## Manual Scanning

### Command Line

Run a scan and display results:
```bash
python manage.py scan_system_packages
```

Run a scan and save to database:
```bash
python manage.py scan_system_packages --save
```

Get JSON output:
```bash
python manage.py scan_system_packages --json
```

### Web Interface

1. Navigate to **Security** → **Package Scanner**
2. Click **Run Scan Now**
3. View results in the dashboard

## Automated Scheduling

### Setup (Systemd)

Enable daily automated scanning:
```bash
python manage.py setup_package_scanner_schedule
```

Custom interval (hourly, daily, weekly, monthly):
```bash
python manage.py setup_package_scanner_schedule --interval weekly
```

Check status:
```bash
python manage.py setup_package_scanner_schedule --status
```

Disable scheduled scanning:
```bash
python manage.py setup_package_scanner_schedule --disable
```

### Setup (Cron - Alternative)

If systemd is not available, use cron:

```bash
crontab -e
```

Add for daily scans at 2 AM:
```
0 2 * * * cd /home/administrator && venv/bin/python manage.py scan_system_packages --save
```

## API Endpoints

### Get Widget Data
```http
GET /api/security/package-scanner/widget/
```

Response:
```json
{
    "status": "danger",
    "status_label": "High Risk",
    "security_updates": 23,
    "total_updates": 45,
    "total_packages": 1234,
    "scan_date": "2026-02-21T10:30:00Z",
    "package_manager": "apt"
}
```

### Trigger Scan
```http
POST /security/package-scanner/run/
```

Response:
```json
{
    "success": true,
    "message": "Scan completed successfully",
    "scan_data": { ... }
}
```

## Security Status Levels

| Security Updates | Status | Risk Level |
|-----------------|--------|------------|
| 0 | Success (Green) | Secure |
| 1-4 | Warning (Yellow) | Low Risk |
| 5-19 | Warning (Yellow) | Medium Risk |
| 20+ | Danger (Red) | High Risk |

## Dashboard Access

### Main Dashboard
`/security/package-scanner/`

Shows:
- Security status cards
- Latest scan details with security package list
- Full scan history table
- Manual scan trigger

### Individual Scan Details
`/security/package-scanner/scan/<id>/`

Shows:
- Complete scan overview
- All security updates available
- Other upgradeable packages
- Full installed package list

### Security Dashboard Widget
Integrated into `/security/` main security dashboard sidebar.

## Troubleshooting

### Permission Denied Errors

If you see permission denied for system logs:
```bash
sudo chmod +r /var/log/unattended-upgrades/unattended-upgrades.log
```

Or run scan with sudo (not recommended):
```bash
sudo venv/bin/python manage.py scan_system_packages --save
```

### Systemd Timer Not Running

Check timer status:
```bash
systemctl --user status package-scanner.timer
```

View logs:
```bash
journalctl --user -u package-scanner.service -f
```

Ensure lingering is enabled (allows services to run when not logged in):
```bash
loginctl enable-linger $USER
```

### No Scans Appearing

1. Check database connection
2. Verify scan command runs successfully: `python manage.py scan_system_packages --save`
3. Check Django logs for errors
4. Verify user permissions (staff or superuser required)

## Package Manager Support

### Debian/Ubuntu (apt)
- Detects security updates from Ubuntu Security or Debian Security repositories
- Uses `apt list --upgradeable` and `/var/log/unattended-upgrades/`
- Identifies packages from `-security` repositories

### Red Hat/CentOS/Fedora (yum/dnf)
- Uses `yum updateinfo list updates` or `dnf updateinfo list updates`
- Identifies security advisories (RHSA)
- Parses update metadata for security classification

### Arch Linux (pacman)
- Uses `pacman -Qu` for upgradeable packages
- Checks Arch Security Tracker (https://security.archlinux.org/)
- Limited security-specific detection (Arch doesn't separate security updates)

## Best Practices

1. **Run scans daily**: Enable automated scheduling for daily security checks
2. **Review regularly**: Check the dashboard at least weekly
3. **Apply updates promptly**: Security updates should be applied within 24-48 hours
4. **Test before production**: Test updates in staging environment first
5. **Monitor trends**: Watch for increasing security update counts

## Integration Examples

### Webhook Notifications

Create a webhook to notify on high-risk scans:

1. Go to **Webhooks** → **Create Webhook**
2. Set event: `security.package_scan_completed`
3. Add filter: `security_updates > 10`
4. Configure notification endpoint (Slack, Discord, email, etc.)

### Monitoring Dashboard

Add widget to custom monitoring dashboard:

```javascript
fetch('/api/security/package-scanner/widget/')
    .then(r => r.json())
    .then(data => {
        console.log(`Security Updates: ${data.security_updates}`);
        console.log(`Status: ${data.status_label}`);
    });
```

### Prometheus Metrics (Future)

Export metrics for Prometheus monitoring:
```
package_security_updates{status="danger"} 23
package_total_updates{} 45
package_last_scan_timestamp{} 1708513800
```

## Limitations

- Requires appropriate package manager (apt, yum/dnf, or pacman)
- Security update detection accuracy depends on package manager metadata
- Large package lists (5000+ packages) may take 30-60 seconds to scan
- Arch Linux security detection is limited (no official security repository)
- Cannot automatically apply updates (manual or external automation required)

## Future Enhancements

Planned features:
- [ ] Email/webhook alerts for critical security updates
- [ ] Update application integration (apply updates from web UI)
- [ ] Prometheus metrics export
- [ ] CVE database integration for vulnerability details
- [ ] Package dependency graph visualization
- [ ] Comparison between scans (diff view)
- [ ] Export scan results (PDF, CSV, JSON)

## Support

For issues or questions:
- GitHub Issues: https://github.com/agit8or1/clientst0r/issues
- Documentation: https://github.com/agit8or1/clientst0r
- Version: 3.9.1+
