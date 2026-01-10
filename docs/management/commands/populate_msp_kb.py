"""
Management command to populate Global KB with MSP-related articles
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Organization, Tag
from docs.models import Document, DocumentCategory
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Populate Global KB with MSP-related knowledge base articles'

    def handle(self, *args, **options):
        # Get or create first organization (required for FK)
        org = Organization.objects.first()
        if not org:
            self.stdout.write(self.style.ERROR('No organizations found. Please create at least one organization first.'))
            return

        # Get admin user for created_by
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = User.objects.first()

        self.stdout.write('Creating Global KB categories...')

        # Create categories
        categories_data = [
            {'name': 'Networking', 'icon': 'network-wired', 'description': 'Network configuration, troubleshooting, and best practices'},
            {'name': 'Security', 'icon': 'shield-alt', 'description': 'Security procedures, incident response, and compliance'},
            {'name': 'Backup & DR', 'icon': 'database', 'description': 'Backup strategies and disaster recovery procedures'},
            {'name': 'Microsoft 365', 'icon': 'microsoft', 'description': 'Microsoft 365 administration and troubleshooting'},
            {'name': 'Active Directory', 'icon': 'users-cog', 'description': 'Active Directory management and best practices'},
            {'name': 'Procedures', 'icon': 'clipboard-list', 'description': 'Standard operating procedures and workflows'},
            {'name': 'Troubleshooting', 'icon': 'tools', 'description': 'Common issues and solutions'},
            {'name': 'Onboarding', 'icon': 'user-plus', 'description': 'Client and user onboarding procedures'},
        ]

        categories = {}
        for idx, cat_data in enumerate(categories_data):
            cat, created = DocumentCategory.objects.get_or_create(
                organization=org,
                slug=slugify(cat_data['name']),
                defaults={
                    'name': cat_data['name'],
                    'icon': cat_data['icon'],
                    'description': cat_data['description'],
                    'order': idx
                }
            )
            categories[cat_data['name']] = cat
            if created:
                self.stdout.write(self.style.SUCCESS(f'  Created category: {cat.name}'))

        self.stdout.write('Creating tags...')

        # Create tags
        tags_data = [
            {'name': 'Windows', 'color': '#0078D4'},
            {'name': 'Linux', 'color': '#FCC624'},
            {'name': 'macOS', 'color': '#000000'},
            {'name': 'Azure', 'color': '#0089D6'},
            {'name': 'AWS', 'color': '#FF9900'},
            {'name': 'Firewall', 'color': '#DC3545'},
            {'name': 'DNS', 'color': '#17A2B8'},
            {'name': 'VPN', 'color': '#6610F2'},
            {'name': 'Email', 'color': '#FD7E14'},
            {'name': 'Best Practice', 'color': '#28A745'},
        ]

        tags = {}
        for tag_data in tags_data:
            tag, created = Tag.objects.get_or_create(
                organization=org,
                name=tag_data['name'],
                defaults={'color': tag_data['color']}
            )
            tags[tag_data['name']] = tag
            if created:
                self.stdout.write(self.style.SUCCESS(f'  Created tag: {tag.name}'))

        self.stdout.write('Creating Global KB articles...')

        # KB Articles
        articles = [
            {
                'title': 'New Client Onboarding Checklist',
                'category': 'Onboarding',
                'tags': ['Best Practice'],
                'body': '''# New Client Onboarding Checklist

## Pre-Onboarding
- [ ] Collect client information (company name, contacts, locations)
- [ ] Schedule kickoff meeting
- [ ] Review existing infrastructure documentation
- [ ] Identify key stakeholders

## Technical Discovery
- [ ] Document network topology
- [ ] Inventory all devices and servers
- [ ] Review backup systems
- [ ] Assess security posture
- [ ] Document current vendor relationships

## Setup
- [ ] Create organization in PSA
- [ ] Setup monitoring tools
- [ ] Configure backup monitoring
- [ ] Create documentation structure
- [ ] Setup password vault

## Handoff
- [ ] Schedule training session
- [ ] Review SLA and response times
- [ ] Provide escalation contacts
- [ ] Document preferences and requirements
'''
            },
            {
                'title': 'Active Directory Best Practices',
                'category': 'Active Directory',
                'tags': ['Windows', 'Best Practice'],
                'body': '''# Active Directory Best Practices

## Forest and Domain Structure
- Use single forest, single domain when possible
- Implement proper OU structure for delegation
- Document AD schema changes

## Security
- Enable Advanced Threat Analytics (ATA)
- Implement LAPS for local admin passwords
- Use separate admin accounts (regular vs privileged)
- Enable audit logging
- Implement MFA for administrative access

## Group Policy
- Document all GPOs with clear naming
- Test GPOs in staging OU before production
- Review and clean up unused GPOs quarterly
- Use security filtering instead of disabling computer/user side

## Backup and Recovery
- Regular backups of System State
- Test AD restore procedures annually
- Document DSRM password location
- Maintain offline copy of AD database

## Maintenance
- Monitor replication health daily
- Review DNS health weekly
- Clean up stale computer objects (90+ days)
- Review group memberships monthly
'''
            },
            {
                'title': 'Firewall Change Request Process',
                'category': 'Networking',
                'tags': ['Firewall', 'Best Practice'],
                'body': '''# Firewall Change Request Process

## Request Information Required
- Source IP/Network
- Destination IP/Network
- Port(s) and Protocol
- Business justification
- Duration (temporary or permanent)
- Requestor name and approval

## Implementation Steps
1. Review request for security concerns
2. Verify source/destination are accurate
3. Use most restrictive rule possible
4. Document rule with description
5. Set expiration for temporary rules
6. Backup config before changes
7. Implement during maintenance window
8. Test connectivity
9. Document change in ticket

## Post-Implementation
- Verify rule is working as intended
- Update documentation
- Schedule review for temporary rules
- Monitor logs for unexpected traffic
'''
            },
            {
                'title': 'Microsoft 365 User Offboarding',
                'category': 'Microsoft 365',
                'tags': ['Email', 'Best Practice'],
                'body': '''# Microsoft 365 User Offboarding Process

## Immediate Actions (Day of Termination)
1. Disable user account in Azure AD
2. Reset password
3. Revoke all active sessions
4. Remove from all groups
5. Block access to SharePoint/OneDrive
6. Convert mailbox to shared mailbox

## Email Handling
- Setup auto-reply with alternative contact
- Forward email to manager or shared mailbox
- Set retention period (typically 30-90 days)

## Data Preservation
- Export OneDrive contents if required
- Document SharePoint permissions
- Save copies of important Teams conversations
- Export mailbox if needed for legal hold

## License Management
- Remove licenses (keep mailbox conversion in mind)
- Reassign licenses to new users
- Update license count in documentation

## Device Management
- Wipe company data from Intune-managed devices
- Remove device registrations
- Document device return

## 30-60 Days Post-Termination
- Convert shared mailbox to inactive (if no longer needed)
- Archive data per retention policy
- Remove from distribution lists
- Final cleanup of permissions
'''
            },
            {
                'title': 'VPN Troubleshooting Guide',
                'category': 'Troubleshooting',
                'tags': ['VPN', 'Networking'],
                'body': '''# VPN Troubleshooting Guide

## Cannot Connect - Authentication Failed

**Check:**
- Verify username/password are correct
- Check if account is locked out
- Verify MFA is functioning
- Check certificate expiration

## Connected But Cannot Access Resources

**Check:**
- Verify routing table on client
- Check DNS settings
- Verify firewall rules allow VPN subnet
- Test with IP address instead of hostname

## Slow VPN Performance

**Check:**
- Client internet speed
- VPN server CPU/bandwidth utilization
- Encryption overhead
- Split tunnel vs full tunnel configuration
- MTU size settings

## Frequent Disconnections

**Check:**
- Client power management settings
- Router/firewall timeout settings
- VPN server log capacity
- Network stability (packet loss)
- Keep-alive settings

## Common Solutions
- Clear VPN client cache/settings
- Update VPN client software
- Reset network stack on client
- Verify VPN server health
- Check for IP conflicts
'''
            },
            {
                'title': 'Backup Verification Procedures',
                'category': 'Backup & DR',
                'tags': ['Best Practice'],
                'body': '''# Backup Verification Procedures

## Daily Verification
- Review backup job completion status
- Check for failed backups
- Verify backup size is reasonable
- Review error logs
- Document failures in ticket

## Weekly Verification
- Test restore of random files
- Verify offsite backup sync
- Review retention policy compliance
- Check backup storage capacity
- Audit backup job schedules

## Monthly Verification
- Full restore test to alternate location
- Verify backup encryption
- Review and update backup documentation
- Test bare metal restore process
- Check backup software updates

## Quarterly Verification
- Full disaster recovery drill
- Review backup SLA compliance
- Update recovery time objectives (RTO)
- Update recovery point objectives (RPO)
- Audit backup infrastructure capacity

## Best Practices
- Follow 3-2-1 rule (3 copies, 2 different media, 1 offsite)
- Encrypt backups at rest and in transit
- Test restores regularly (if you haven't tested, you don't have a backup)
- Document all restore procedures
- Keep backup software up to date
'''
            },
            {
                'title': 'DNS Troubleshooting Steps',
                'category': 'Networking',
                'tags': ['DNS', 'Troubleshooting'],
                'body': '''# DNS Troubleshooting Steps

## Basic Checks
1. Verify network connectivity (ping 8.8.8.8)
2. Check DNS server configuration (ipconfig /all)
3. Test with alternative DNS server
4. Clear DNS cache (ipconfig /flushdns)
5. Check hosts file for overrides

## Advanced Troubleshooting

### Using nslookup
```
nslookup domain.com
nslookup domain.com 8.8.8.8
```

### Using dig (Linux/Mac)
```
dig domain.com
dig domain.com @8.8.8.8
dig +trace domain.com
```

### Common Issues

**NXDOMAIN Response**
- Domain doesn't exist
- Typo in domain name
- DNS zone not configured

**No Response / Timeout**
- Firewall blocking port 53
- DNS server down or unreachable
- Network connectivity issue

**Wrong IP Returned**
- DNS cache outdated
- Incorrect DNS record
- Split-brain DNS issue

## Server-Side Checks
- Verify DNS service is running
- Check zone file for errors
- Review DNS server logs
- Verify forwarders are functioning
- Check DNSSEC if enabled

## Resolution Steps
1. Identify scope (single user, site, or global)
2. Test from multiple locations
3. Verify DNS records at authoritative server
4. Check TTL values
5. Clear caches (client and server)
6. Document resolution in ticket
'''
            },
            {
                'title': 'Security Incident Response Plan',
                'category': 'Security',
                'tags': ['Best Practice'],
                'body': '''# Security Incident Response Plan

## Phase 1: Identification
- Confirm security incident
- Document initial findings
- Assign incident severity level
- Notify stakeholders per escalation matrix

## Phase 2: Containment

### Short-term Containment
- Isolate affected systems from network
- Disable compromised accounts
- Block malicious IP addresses
- Preserve evidence

### Long-term Containment
- Apply temporary fixes
- Improve monitoring
- Implement additional security controls

## Phase 3: Eradication
- Remove malware/backdoors
- Close security vulnerabilities
- Update passwords
- Patch systems
- Review and update security policies

## Phase 4: Recovery
- Restore systems from clean backups
- Verify system integrity
- Monitor for reinfection
- Return to normal operations gradually
- Update documentation

## Phase 5: Lessons Learned
- Conduct post-incident review
- Document what happened
- Identify improvements needed
- Update incident response procedures
- Provide training if needed

## Escalation Contacts
- Internal: [Security Team Contact]
- External: [Cyber Insurance, FBI IC3 if applicable]
- Legal: [Company Legal Contact]
- PR: [Communications Lead]

## Evidence Preservation
- Do NOT turn off systems
- Photograph screens
- Document all actions taken
- Preserve logs
- Chain of custody for forensics
'''
            },
            {
                'title': 'Azure AD Connect Troubleshooting',
                'category': 'Microsoft 365',
                'tags': ['Azure', 'Active Directory'],
                'body': '''# Azure AD Connect Troubleshooting

## Sync Not Running

**Check:**
- Azure AD Connect service status
- Sync scheduler status: `Get-ADSyncScheduler`
- Last sync time: `Get-ADSyncCSObject`
- Error logs in Event Viewer

**Common Fixes:**
- Restart Azure AD Connect Sync service
- Run manual sync: `Start-ADSyncSyncCycle -PolicyType Delta`
- Verify credentials haven't expired

## Objects Not Syncing

**Check:**
- OU filtering configuration
- Attribute filtering rules
- Sync rules in Synchronization Rules Editor
- Object in scope: `Get-ADSyncCSObject`

**Common Issues:**
- User not in synced OU
- Missing required attributes (proxyAddresses)
- Duplicate attributes causing conflicts
- Object filter excluding the item

## Password Sync Issues

**Check:**
- Password writeback enabled
- Passwords meet Azure AD password policy
- Password sync connector status
- Event logs for error 611 (password sync)

**Resolution:**
- Reset password sync: `Add-ADSyncAADServiceAccount`
- Verify firewall rules (port 443 to Azure)
- Check for clock skew

## Installation/Upgrade Issues

**Pre-requisites:**
- .NET Framework 4.6.2 or later
- PowerShell 5.0 or later
- TLS 1.2 enabled
- SQL Server 2012 LocalDB (Express) or SQL Server

**Upgrade Process:**
- Review release notes
- Backup Azure AD Connect database
- Disable sync scheduler
- Run installer
- Verify configuration post-upgrade

## Health Monitoring
- Review Azure AD Connect Health portal
- Monitor sync errors in Azure AD portal
- Setup alerts for sync failures
- Regular backup of sync configuration
'''
            },
            {
                'title': 'Patch Management Best Practices',
                'category': 'Procedures',
                'tags': ['Windows', 'Best Practice'],
                'body': '''# Patch Management Best Practices

## Patch Schedule

### Critical/Security Patches
- Review: Within 24 hours of release
- Test: Within 1 week
- Deploy: Within 2 weeks

### Standard Updates
- Review: Weekly
- Test: 2 weeks in pilot group
- Deploy: Monthly during maintenance window

## Testing Process
1. Review patch notes and known issues
2. Deploy to test environment
3. Test critical applications
4. Monitor for 3-5 days
5. Deploy to pilot group (10% of production)
6. Monitor pilot for 1 week
7. Deploy to production in phases

## Patching Categories

### Tier 1: Critical Infrastructure
- Domain Controllers
- DHCP/DNS servers
- Firewalls
- Backup servers
- Production databases

### Tier 2: Production Systems
- Application servers
- File servers
- Print servers
- Web servers

### Tier 3: End User Devices
- Workstations
- Laptops
- Non-critical systems

## Pre-Patching Checklist
- [ ] Review patch notes
- [ ] Verify backups are current
- [ ] Notify users of maintenance window
- [ ] Document current system state
- [ ] Prepare rollback plan
- [ ] Verify change approval

## Post-Patching Tasks
- [ ] Verify services started
- [ ] Test critical functionality
- [ ] Review event logs
- [ ] Update documentation
- [ ] Monitor for 24-48 hours
- [ ] Close change ticket

## Emergency Patching
- Notify management of urgency
- Expedite testing (4-8 hours max)
- Deploy to all systems immediately
- Monitor continuously for 72 hours
- Document decision and outcome
'''
            },
        ]

        for article_data in articles:
            slug = slugify(article_data['title'])

            doc, created = Document.objects.get_or_create(
                slug=slug,
                defaults={
                    'organization': org,
                    'title': article_data['title'],
                    'body': article_data['body'],
                    'content_type': 'markdown',
                    'is_published': True,
                    'is_global': True,
                    'category': categories.get(article_data['category']),
                    'created_by': admin_user,
                    'last_modified_by': admin_user,
                }
            )

            if created:
                # Add tags
                for tag_name in article_data['tags']:
                    if tag_name in tags:
                        doc.tags.add(tags[tag_name])

                self.stdout.write(self.style.SUCCESS(f'  Created: {doc.title}'))
            else:
                self.stdout.write(self.style.WARNING(f'  Already exists: {doc.title}'))

        self.stdout.write(self.style.SUCCESS('\nSuccessfully populated Global KB!'))
        self.stdout.write(f'Total articles: {Document.objects.filter(is_global=True).count()}')
