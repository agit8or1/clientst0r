"""
Management command to seed Global KB articles.
These are knowledge base articles that apply to all organizations.

Usage:
    python manage.py seed_global_kb
"""

from django.core.management.base import BaseCommand
from docs.models import Document, DocumentCategory
from core.models import Organization
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Seed global document templates (IT/MSP templates for all organizations)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Seeding global document templates...'))

        # Get admin user
        admin_user = User.objects.filter(is_superuser=True).first()

        # Global KB articles
        articles = [
            {
                'title': 'Windows Server Best Practices',
                'slug': 'windows-server-best-practices',
                'body': '''# Windows Server Best Practices

## Security Hardening

### User Account Control (UAC)
- Always keep UAC enabled in production environments
- Use standard user accounts for daily operations
- Reserve Administrator accounts for system maintenance only

### Windows Updates
- Enable automatic updates for security patches
- Test updates in staging environment first
- Schedule maintenance windows for critical updates
- Document all applied patches in change log

### Active Directory Security
- Implement principle of least privilege
- Use Group Policy Objects (GPOs) for consistent security settings
- Regular review of user permissions and group memberships
- Enable auditing for sensitive operations

## Performance Optimization

### Resource Monitoring
- Monitor CPU, RAM, and disk usage regularly
- Set up performance alerts for threshold breaches
- Use Performance Monitor (perfmon) for detailed analysis
- Review Event Viewer logs for errors and warnings

### Disk Management
- Maintain at least 15% free disk space
- Defragment traditional HDDs monthly
- Use TRIM for SSDs
- Implement regular backup schedules

## Backup & Recovery

### 3-2-1 Backup Rule
- 3 copies of data
- 2 different media types
- 1 off-site backup

### Backup Schedule
- Full backups: Weekly
- Incremental backups: Daily
- Test restore procedures: Monthly
- Document recovery procedures

## Networking

### Firewall Configuration
- Enable Windows Firewall on all profiles
- Document all allowed ports and services
- Regular review of firewall rules
- Use IPSec for sensitive communications

### Remote Access
- Use RDP over VPN only
- Implement Network Level Authentication (NLA)
- Change default RDP port if exposed to internet
- Enable RDP session logging

## Documentation

### Essential Documentation
- Server inventory with specifications
- Network topology diagrams
- Service account passwords in vault
- Backup and recovery procedures
- Contact information for vendors
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': True,
                'is_published': True,
            },
            {
                'title': 'Password Security Guidelines',
                'slug': 'password-security-guidelines',
                'body': '''# Password Security Guidelines

## Password Requirements

### Minimum Standards
- **Length**: Minimum 12 characters (16+ recommended)
- **Complexity**: Mix of uppercase, lowercase, numbers, and symbols
- **Uniqueness**: Never reuse passwords across systems
- **Expiration**: 90-day rotation for privileged accounts

### Password Strength Examples
- ❌ Weak: `Password123`
- ❌ Weak: `Company2024`
- ✅ Strong: `Tr0pic@l-M0nk3y-D@nc3s!`
- ✅ Strong: `C0ff33&Cr0!ss@nts#42`

## Password Management

### Storage Best Practices
- Use encrypted password vault (like this platform)
- Never store passwords in plain text
- Avoid browser password managers for business accounts
- Use unique passwords for each service

### Multi-Factor Authentication (MFA)
- Enable MFA on all critical systems
- Preferred methods: Authenticator app > SMS > Email
- Keep backup codes in secure location
- Document MFA reset procedures

## Common Password Attacks

### Brute Force Attacks
- Automated attempts to guess passwords
- **Defense**: Account lockout after failed attempts, CAPTCHA

### Phishing
- Fake emails/websites to steal credentials
- **Defense**: Security awareness training, email filtering

### Credential Stuffing
- Using leaked passwords from other breaches
- **Defense**: Unique passwords per service, breach monitoring

### Keylogging
- Malware that records keystrokes
- **Defense**: Endpoint protection, regular scans

## Password Policies

### For System Administrators
- Use password managers for all credentials
- Rotate service account passwords quarterly
- Audit privileged account usage
- Implement least privilege access

### For End Users
- Provide password manager licenses
- Conduct security awareness training
- Enforce password complexity requirements
- Monitor for compromised credentials

## Password Recovery

### Reset Procedures
1. Verify user identity through multiple factors
2. Generate temporary password (must change on login)
3. Log password reset in audit trail
4. Notify user through secure channel

### Emergency Access
- Store break-glass passwords in physical safe
- Document emergency access procedures
- Log all emergency access usage
- Rotate emergency passwords after use

## Tools & Resources

### Password Generators
- Use cryptographically secure generators
- Minimum entropy: 60 bits
- Avoid dictionary words and patterns

### Password Strength Checkers
- zxcvbn (Dropbox's strength estimator)
- Have I Been Pwned (check for breached passwords)

### Recommended Password Managers
- This platform's built-in vault
- Bitwarden (open source)
- 1Password (business)
- KeePass (self-hosted)
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': True,
                'is_published': True,
            },
            {
                'title': 'Network Documentation Standards',
                'slug': 'network-documentation-standards',
                'body': '''# Network Documentation Standards

## Network Diagrams

### Layer 1 (Physical)
- Rack layouts with device positions
- Cable runs and patch panel mappings
- Physical security zones
- Power distribution

### Layer 2 (Data Link)
- VLAN topology
- Switch interconnections
- Spanning tree configuration
- Link aggregation (LACP)

### Layer 3 (Network)
- IP address schemes and subnets
- Routing protocols and tables
- Firewall rules and ACLs
- NAT configurations

## IP Address Management (IPAM)

### Documentation Requirements
- Network address and subnet mask
- Gateway and DNS servers
- DHCP ranges and reservations
- Purpose and owner of each subnet

### Example IPAM Table
```
Network: 10.0.0.0/24
Gateway: 10.0.0.1
DHCP Range: 10.0.0.100-10.0.0.200
DNS: 10.0.0.10, 10.0.0.11

Static Assignments:
10.0.0.1   - Gateway (Firewall)
10.0.0.10  - Primary DNS
10.0.0.11  - Secondary DNS
10.0.0.20  - Domain Controller
10.0.0.50  - File Server
```

## Device Documentation

### Required Information
- Hostname and FQDN
- Management IP address
- Hardware model and serial number
- Firmware/software version
- Purpose and services
- Contact information (vendor support)

### Configuration Backups
- Automated daily backups
- Version control for config changes
- Test restore procedures monthly
- Store off-site copies

## Change Management

### Network Change Process
1. **Plan**: Document proposed changes
2. **Review**: Technical review by team
3. **Approve**: Management approval
4. **Test**: Validate in lab environment
5. **Implement**: Execute during maintenance window
6. **Verify**: Confirm changes work as expected
7. **Document**: Update all diagrams and docs

### Rollback Plan
- Document rollback steps before changes
- Keep previous configurations accessible
- Set time limit for rollback decision
- Test rollback procedures

## Monitoring & Alerts

### Critical Metrics
- Interface utilization
- Packet loss and latency
- Device CPU and memory
- Link status changes

### Alert Thresholds
- Interface utilization > 80%
- Packet loss > 1%
- Latency > 50ms
- Any link down event

## Security Documentation

### Firewall Rules
```
Rule #  | Source      | Dest       | Port    | Action | Purpose
--------|-------------|------------|---------|--------|------------------
1       | 10.0.0.0/24 | Any        | 80/443  | Allow  | Web browsing
2       | 10.0.10.0/24| 10.0.0.20  | 3389    | Allow  | RDP to DC
3       | Any         | Any        | Any     | Deny   | Default deny
```

### Access Control Lists
- Document all ACLs with purpose
- Review quarterly for relevance
- Remove obsolete rules
- Follow least privilege principle

## Disaster Recovery

### Network Recovery Priority
1. Internet connectivity
2. Internal routing
3. DHCP and DNS services
4. Critical application access

### Documentation Location
- Primary: This documentation platform
- Secondary: Encrypted cloud storage
- Tertiary: Physical binder in safe

## Tools & Standards

### Diagramming Tools
- Draw.io (free, web-based)
- Microsoft Visio
- Lucidchart
- This platform's diagram feature

### Standards to Follow
- RFC 1918 (Private addressing)
- IEEE 802.1Q (VLANs)
- IEEE 802.3ad (Link aggregation)
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': True,
                'is_published': True,
            },
            {
                'title': 'Incident Response Procedures',
                'slug': 'incident-response-procedures',
                'body': '''# Incident Response Procedures

## Incident Severity Levels

### Critical (P1)
- Complete system outage affecting all users
- Data breach or security compromise
- Loss of critical business function
- **Response Time**: Immediate (within 15 minutes)

### High (P2)
- Partial system outage affecting multiple users
- Performance degradation of critical systems
- Security vulnerability requiring urgent patching
- **Response Time**: Within 1 hour

### Medium (P3)
- Limited system issues affecting few users
- Non-critical functionality impaired
- Planned maintenance required soon
- **Response Time**: Within 4 hours

### Low (P4)
- Minor issues with workarounds available
- Feature requests
- Cosmetic issues
- **Response Time**: Within 1 business day

## Incident Response Phases

### 1. Detection & Analysis
- Monitor alerts and user reports
- Gather initial information
- Determine incident severity
- Assign incident commander

### 2. Containment
- Isolate affected systems if security incident
- Implement temporary workarounds
- Prevent incident from spreading
- Document all actions taken

### 3. Eradication
- Identify and eliminate root cause
- Remove malware or unauthorized access
- Patch vulnerabilities
- Verify threat is removed

### 4. Recovery
- Restore systems to normal operation
- Monitor for signs of recurring issues
- Validate all services are functional
- Update documentation

### 5. Post-Incident Review
- Conduct lessons learned session
- Update incident response procedures
- Implement preventive measures
- Document timeline and actions

## Security Incident Response

### Suspected Breach Checklist
- [ ] Isolate affected systems from network
- [ ] Preserve evidence (disk images, logs)
- [ ] Identify scope of compromise
- [ ] Reset credentials for affected accounts
- [ ] Notify management and stakeholders
- [ ] Contact law enforcement if required
- [ ] Document all forensic findings

### Ransomware Response
1. **DO NOT PAY RANSOM** (generally recommended)
2. Isolate infected systems immediately
3. Identify ransomware variant
4. Check for available decryptors
5. Restore from clean backups
6. Scan all systems for persistence
7. Report to authorities (FBI IC3)

## Communication Procedures

### Internal Communication
- Status updates every 30 minutes during P1
- Use dedicated incident channel (Slack, Teams)
- Maintain incident log with timestamps
- Escalate to management as appropriate

### External Communication
- Notify affected customers/users
- Coordinate with vendors if needed
- Public statements (management approval required)
- Regulatory notifications if data breach

## Documentation Requirements

### Incident Report Template
```
Incident ID: INC-2024-001
Severity: P1 - Critical
Reported By: John Doe
Reported At: 2024-01-15 09:30 UTC

Summary:
[Brief description of the incident]

Timeline:
09:30 - Initial detection
09:35 - Incident commander assigned
09:45 - Root cause identified
10:15 - Fix implemented
10:30 - Services restored

Root Cause:
[Detailed explanation]

Resolution:
[Steps taken to resolve]

Preventive Measures:
[Actions to prevent recurrence]

Affected Systems:
- System A
- System B

Impact:
- Users affected: 150
- Downtime: 1 hour
- Data loss: None
```

## Contact Information

### Escalation Matrix
| Level | Role | Contact | Response Time |
|-------|------|---------|---------------|
| L1 | Help Desk | helpdesk@company.com | 15 min |
| L2 | System Admin | sysadmin@company.com | 1 hour |
| L3 | Senior Engineer | senioreng@company.com | 2 hours |
| L4 | IT Director | itdirector@company.com | 4 hours |

### Vendor Support
- Critical: Provide vendor with incident severity
- Include system details and error messages
- Reference support contract/agreement
- Document case numbers and contacts

## Post-Incident Activities

### Metrics to Track
- Time to detect
- Time to respond
- Time to resolve
- Number of incidents by category
- Repeat incidents

### Continuous Improvement
- Monthly review of incident trends
- Quarterly update of procedures
- Annual tabletop exercises
- Staff training on new threats
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': True,
                'is_published': True,
            },
            {
                'title': 'Backup and Disaster Recovery',
                'slug': 'backup-disaster-recovery',
                'body': '''# Backup and Disaster Recovery

## Backup Strategy

### 3-2-1 Backup Rule
- **3** copies of your data
- **2** different types of media
- **1** copy stored off-site

### Backup Types

**Full Backup**
- Complete copy of all data
- Longest backup time
- Fastest restore time
- Schedule: Weekly (Sunday night)

**Incremental Backup**
- Only changes since last backup
- Fastest backup time
- Slower restore (need all increments)
- Schedule: Daily (Monday-Saturday)

**Differential Backup**
- Changes since last full backup
- Moderate backup time
- Faster restore than incremental
- Schedule: Alternative to incremental

## Backup Schedule

### Production Servers
```
Sunday:    00:00 - Full backup
Monday:    01:00 - Incremental backup
Tuesday:   01:00 - Incremental backup
Wednesday: 01:00 - Incremental backup
Thursday:  01:00 - Incremental backup
Friday:    01:00 - Incremental backup
Saturday:  01:00 - Incremental backup
```

### Retention Policy
- Daily backups: 7 days
- Weekly backups: 4 weeks
- Monthly backups: 12 months
- Yearly backups: 7 years (compliance)

## Data Classification

### Critical (Tier 1)
- Database servers
- Email servers
- Financial systems
- **RTO**: 1 hour
- **RPO**: 15 minutes

### Important (Tier 2)
- File servers
- Application servers
- Web servers
- **RTO**: 4 hours
- **RPO**: 1 hour

### Standard (Tier 3)
- Workstations
- Development systems
- Test environments
- **RTO**: 24 hours
- **RPO**: 24 hours

## Recovery Time Objective (RTO)
Maximum acceptable time to restore a system after an incident.

## Recovery Point Objective (RPO)
Maximum acceptable data loss measured in time.

## Backup Media

### On-Site Storage
- Network Attached Storage (NAS)
- Disk-to-Disk backup
- Fast recovery times
- **Risk**: Vulnerable to local disasters

### Off-Site Storage
- Cloud storage (AWS S3, Azure Blob)
- Remote data center
- Protects against site-wide disasters
- **Risk**: Longer recovery times

### Tape Storage
- Long-term archival
- Cost-effective for large volumes
- Suitable for compliance retention
- **Risk**: Slower access times

## Testing Procedures

### Monthly Restore Tests
- Select random files from backup
- Perform test restore to isolated environment
- Verify data integrity
- Document test results

### Quarterly Full Recovery
- Complete system restore of test server
- Validate all services functional
- Time the recovery process
- Update RTO/RPO estimates

### Annual Disaster Recovery Drill
- Full-scale DR exercise
- Involve all stakeholders
- Test communication procedures
- Document lessons learned

## Disaster Recovery Plan

### Step 1: Assessment
- Determine nature and scope of disaster
- Identify affected systems and services
- Establish incident command structure
- Notify stakeholders

### Step 2: Activation
- Declare disaster recovery
- Mobilize DR team
- Secure alternate facility if needed
- Begin recovery operations

### Step 3: Recovery
- Restore infrastructure services
- Restore critical systems (Tier 1)
- Restore important systems (Tier 2)
- Restore standard systems (Tier 3)

### Step 4: Validation
- Verify system functionality
- Test network connectivity
- Validate data integrity
- User acceptance testing

### Step 5: Transition
- Cut over to recovered systems
- Monitor for issues
- Return to normal operations
- Decommission temporary resources

## Disaster Scenarios

### Hardware Failure
- Single server failure
- Storage system failure
- Network equipment failure
- **Recovery**: Restore to replacement hardware

### Natural Disaster
- Fire, flood, earthquake
- Building evacuation
- Power outage
- **Recovery**: Activate alternate site

### Cybersecurity Incident
- Ransomware attack
- Data breach
- Malware infection
- **Recovery**: Clean restore, security remediation

### Human Error
- Accidental deletion
- Configuration error
- Unauthorized changes
- **Recovery**: Point-in-time restore

## Documentation

### Essential DR Documents
- [ ] System inventory and dependencies
- [ ] Network topology diagrams
- [ ] Contact information (staff, vendors)
- [ ] Backup and restore procedures
- [ ] Vendor support contracts
- [ ] Insurance policy information

### Keep Copies in Multiple Locations
- Primary: This documentation platform
- Secondary: Encrypted cloud storage
- Tertiary: Physical binder (fireproof safe)
- Quaternary: Off-site location

## Monitoring and Alerts

### Backup Monitoring
- Verify backup completion daily
- Check backup logs for errors
- Validate backup size and duration
- Alert on failed or partial backups

### Key Metrics
- Backup success rate
- Backup window duration
- Storage utilization
- Recovery time tests

## Compliance Considerations

### HIPAA
- 6-year retention for health records
- Encryption for ePHI
- Audit log retention

### SOX
- 7-year retention for financial records
- Change management documentation
- Access control logs

### GDPR
- Right to erasure requirements
- Data breach notification (72 hours)
- Data portability

## Backup Security

### Encryption
- Encrypt backups at rest
- Encrypt backups in transit
- Use strong encryption (AES-256)
- Secure key management

### Access Control
- Limit backup administrator access
- Implement MFA for backup systems
- Audit backup access logs
- Separate backup from production credentials

### Air-Gapped Backups
- Disconnected backups for ransomware protection
- Periodic offline copies
- Immutable backup storage
- WORM (Write Once Read Many) media
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': True,
                'is_published': True,
            },
        ]

        count = 0
        for article_data in articles:
            article, created = Document.objects.get_or_create(
                slug=article_data['slug'],
                organization=None,  # Global KB articles have no organization
                defaults={
                    **article_data,
                    'created_by': admin_user,
                    'last_modified_by': admin_user,
                }
            )

            if created:
                self.stdout.write(f'  ✓ Created: {article.title}')
                count += 1
            else:
                self.stdout.write(f'  - Exists: {article.title}')

        self.stdout.write(self.style.SUCCESS(f'\nCreated {count} new global document templates'))
        self.stdout.write(self.style.SUCCESS('Global templates are now available to all organizations!'))
