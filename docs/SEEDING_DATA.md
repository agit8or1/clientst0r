# Seeding Data for New Installations

Client St0r includes comprehensive seed data to help you get started immediately:

- **Equipment Catalog**: 3,000+ models across Dell, HP, Lenovo, Cisco, and other major vendors
- **Knowledge Base Articles**: 1,000+ professional IT documentation articles across 20+ categories

## Quick Start

### Seed Everything (Recommended for New Installations)

```bash
cd /path/to/clientst0r
source venv/bin/activate
python manage.py seed_all --from-github
```

This will:
- Create 3,000+ equipment models with specs
- Fetch 1,000+ KB articles from GitHub
- Take approximately 2-5 minutes

### Seed Specific Data

#### Equipment Catalog Only
```bash
python manage.py seed_equipment_catalog
```

#### KB Articles from GitHub (Recommended)
```bash
python manage.py fetch_kb_from_github
```

This fetches curated KB articles from the Client St0r GitHub repository.

#### KB Articles Locally Generated
```bash
python manage.py seed_kb_articles
```

Generates articles locally (slower, use GitHub fetch instead).

### Quick Seed (For Testing)
```bash
python manage.py seed_all --quick
```

Creates limited data for testing (5 articles per category).

## Deleting Existing Data

To replace existing seed data:

```bash
# Delete and re-seed everything
python manage.py seed_all --delete

# Delete and re-seed equipment only
python manage.py seed_equipment_catalog --delete

# Delete and re-seed KB articles only
python manage.py seed_kb_articles --delete
```

## What Gets Seeded

### Equipment Catalog (3,000+ Models)

**Vendors:**
- Dell (servers, workstations, networking)
- HP/HPE (servers, workstations, printers)
- Lenovo (ThinkPad, ThinkStation, ThinkCentre)
- Cisco (switches, routers, firewalls, wireless)
- And 20+ other major vendors

**Categories:**
- Servers (rack, tower, blade)
- Workstations & Desktops
- Laptops & Mobile
- Network Equipment
- Storage Devices
- Printers & Peripherals
- And more...

**Each Model Includes:**
- Full specifications
- Form factor & dimensions
- Processor, RAM, storage options
- Network interfaces
- Power requirements
- Part numbers
- End-of-life dates where applicable

### Knowledge Base Articles (1,000+)

**Categories (20):**

1. **Windows (100+ articles)**
   - Windows updates and troubleshooting
   - Group Policy configuration
   - Active Directory integration
   - Security hardening
   - Performance optimization

2. **Linux (100+ articles)**
   - System administration essentials
   - Package management (apt, yum, dnf)
   - Service management with systemd
   - Shell scripting and automation
   - Security and permissions

3. **macOS (60+ articles)**
   - Enterprise deployment
   - MDM configuration
   - Troubleshooting common issues
   - System preferences
   - Command line tools

4. **Networking (80+ articles)**
   - VLAN configuration
   - Routing protocols
   - Switch configuration
   - Wireless setup
   - Network troubleshooting

5. **Security (60+ articles)**
   - Best practices
   - Compliance (HIPAA, PCI-DSS, etc.)
   - Encryption standards
   - Incident response
   - Vulnerability management

6. **Cloud (50+ articles)**
   - AWS basics and common tasks
   - Azure administration
   - Google Cloud Platform
   - Cost optimization
   - Migration strategies

7. **Virtualization (40+ articles)**
   - VMware vSphere/ESXi
   - Microsoft Hyper-V
   - Docker containers
   - Kubernetes basics
   - VM optimization

8. **Storage (40+ articles)**
   - NAS configuration
   - SAN architecture
   - RAID levels explained
   - Backup strategies
   - Disaster recovery

9. **Email (50+ articles)**
   - Exchange Server administration
   - Gmail/Google Workspace
   - Outlook troubleshooting
   - SPF/DKIM/DMARC setup
   - Mail flow issues

10. **Active Directory (60+ articles)**
    - User and group management
    - Group Policy Objects (GPO)
    - Domain trusts
    - Replication troubleshooting
    - FSMO roles

11. **Office 365 (50+ articles)**
    - Admin center tasks
    - User provisioning
    - License management
    - Teams administration
    - Migration guides

12. **Google Workspace (40+ articles)**
    - Admin console
    - Policies and settings
    - User management
    - Drive administration
    - Troubleshooting

13. **Hardware (50+ articles)**
    - Server setup and configuration
    - Workstation builds
    - Hardware troubleshooting
    - Component compatibility
    - Maintenance procedures

14. **Printers (40+ articles)**
    - Network printer setup
    - Driver installation
    - Print queue management
    - Common printer issues
    - Security considerations

15. **VoIP (30+ articles)**
    - IP phone systems
    - SIP configuration
    - Call routing
    - Quality of service
    - Troubleshooting

16. **VPN (40+ articles)**
    - VPN protocols explained
    - Setup guides (OpenVPN, IPsec, WireGuard)
    - Client configuration
    - Troubleshooting connections
    - Security best practices

17. **Backup (40+ articles)**
    - Backup strategies (3-2-1 rule)
    - Tool comparisons
    - Disaster recovery planning
    - Testing backups
    - Cloud backup solutions

18. **Monitoring (30+ articles)**
    - Monitoring tools overview
    - Alert configuration
    - Dashboard creation
    - Performance metrics
    - Log management

19. **Scripting (50+ articles)**
    - PowerShell automation
    - Bash scripting
    - Python for sysadmins
    - API integration
    - Scheduled tasks

20. **Mobile (30+ articles)**
    - Mobile Device Management (MDM)
    - BYOD policies
    - iOS troubleshooting
    - Android enterprise
    - App deployment

## Managing Seed Data

### Users Can Delete Unwanted Data

All seed data can be safely deleted by users:

**Equipment Models:**
- Navigate to Assets > Equipment Catalog
- Delete vendors or individual models not needed

**KB Articles:**
- Navigate to Knowledge Base
- Archive or delete articles not relevant

**Note:** Deleting seed data does NOT affect user-created content.

### Customizing Seed Data

To customize what gets seeded, edit:
- `/home/administrator/assets/management/commands/seed_vendor_data.py` (equipment)
- `/home/administrator/docs/management/commands/seed_kb_articles.py` (KB articles)

## Best Practices

1. **New Installations**: Run `seed_all` immediately after initial setup
2. **Testing**: Use `--quick` flag for faster testing environments
3. **Production**: Keep seed data - it's valuable reference material
4. **Updates**: Re-run seeding with `--delete` to refresh data
5. **Backups**: Seed data can always be regenerated

## Troubleshooting

### "Command not found"
Make sure you're in the correct directory and virtual environment is activated.

### Seeding Takes Too Long
- Use `--quick` for testing
- Run during off-hours for production
- Equipment catalog: ~2-3 minutes
- KB articles: ~3-5 minutes
- Total: ~5-10 minutes

### Out of Memory
Increase available RAM or use `--quick` mode.

### Database Errors
- Ensure migrations are up to date: `python manage.py migrate`
- Check database connections
- Verify disk space

## Support

For issues with seed data:
1. Check logs: `tail -f /var/log/itdocs/gunicorn-error.log`
2. Report issues: https://github.com/anthropics/clientst0r/issues
3. Community support: Check documentation wiki

## Version Information

Seed data is updated regularly. Check `CHANGELOG.md` for what's new in each release.

Current seed data versions:
- Equipment Catalog: v1.5 (3,000+ models)
- KB Articles: v1.0 (1,000+ articles)
