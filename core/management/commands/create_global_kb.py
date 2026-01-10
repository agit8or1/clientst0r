"""
Management command to create Global KB articles.
These are knowledge base articles (not templates) visible to all organizations.

Usage:
    python manage.py create_global_kb
"""

from django.core.management.base import BaseCommand
from docs.models import Document
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create Global KB articles (actual KB content, not templates)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Creating Global KB articles...'))

        # Get admin user
        admin_user = User.objects.filter(is_superuser=True).first()

        # Global KB articles - practical reference content
        articles = [
            {
                'title': 'Common IT Ports Reference',
                'slug': 'common-it-ports-reference',
                'body': '''# Common IT Ports Reference

## Web Services
- **HTTP**: Port 80 (TCP)
- **HTTPS**: Port 443 (TCP)
- **HTTP Alternative**: Port 8080 (TCP)
- **HTTPS Alternative**: Port 8443 (TCP)

## Remote Access
- **SSH**: Port 22 (TCP)
- **Telnet**: Port 23 (TCP) - Insecure, use SSH instead
- **RDP**: Port 3389 (TCP)
- **VNC**: Port 5900 (TCP)

## Email Services
- **SMTP**: Port 25 (TCP) - Unencrypted
- **SMTP Submission**: Port 587 (TCP) - With STARTTLS
- **SMTPS**: Port 465 (TCP) - SSL/TLS
- **POP3**: Port 110 (TCP)
- **POP3S**: Port 995 (TCP) - SSL/TLS
- **IMAP**: Port 143 (TCP)
- **IMAPS**: Port 993 (TCP) - SSL/TLS

## File Transfer
- **FTP**: Port 21 (TCP) - Control, Port 20 (TCP) - Data
- **FTPS**: Port 989-990 (TCP)
- **SFTP**: Port 22 (TCP) - over SSH
- **TFTP**: Port 69 (UDP)
- **SMB/CIFS**: Port 445 (TCP)
- **NFS**: Port 2049 (TCP/UDP)

## Database Services
- **MySQL/MariaDB**: Port 3306 (TCP)
- **PostgreSQL**: Port 5432 (TCP)
- **Microsoft SQL Server**: Port 1433 (TCP)
- **MongoDB**: Port 27017 (TCP)
- **Redis**: Port 6379 (TCP)
- **Oracle Database**: Port 1521 (TCP)

## Directory Services
- **LDAP**: Port 389 (TCP)
- **LDAPS**: Port 636 (TCP) - SSL/TLS
- **Kerberos**: Port 88 (TCP/UDP)
- **Active Directory**: Port 389 (LDAP), 636 (LDAPS), 88 (Kerberos), 3268 (Global Catalog)

## Network Services
- **DNS**: Port 53 (TCP/UDP)
- **DHCP**: Port 67 (UDP) - Server, Port 68 (UDP) - Client
- **NTP**: Port 123 (UDP)
- **SNMP**: Port 161 (UDP) - Queries, Port 162 (UDP) - Traps
- **Syslog**: Port 514 (UDP)

## VPN & Security
- **OpenVPN**: Port 1194 (UDP)
- **IPSec**: Port 500 (UDP) - IKE, Port 4500 (UDP) - NAT-T
- **L2TP**: Port 1701 (UDP)
- **PPTP**: Port 1723 (TCP)

## Monitoring & Management
- **Ping (ICMP)**: Protocol 1 (not a port)
- **Traceroute**: Port 33434+ (UDP)
- **Zabbix Agent**: Port 10050 (TCP)
- **Nagios NRPE**: Port 5666 (TCP)

## Application Specific
- **Docker**: Port 2375 (TCP) - Unencrypted, Port 2376 (TCP) - TLS
- **Kubernetes API**: Port 6443 (TCP)
- **Elasticsearch**: Port 9200 (TCP)
- **Kibana**: Port 5601 (TCP)
- **Grafana**: Port 3000 (TCP)
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': False,
                'is_published': True,
            },
            {
                'title': 'Windows Server Licensing Guide',
                'slug': 'windows-server-licensing-guide',
                'body': '''# Windows Server Licensing Guide

## Licensing Models

### Per Core Licensing (Windows Server 2016+)
- Licenses are sold in **2-core packs**
- **Minimum**: 8 core licenses per physical processor
- **Minimum per server**: 16 core licenses (regardless of actual core count)

### Example Calculations
- **Server with 2 CPUs, 4 cores each (8 cores total)**:
  - Need: 16 core licenses minimum (8 per CPU × 2 CPUs)

- **Server with 2 CPUs, 10 cores each (20 cores total)**:
  - Need: 20 core licenses (10 per CPU × 2 CPUs)

- **Server with 1 CPU, 4 cores**:
  - Need: 16 core licenses minimum (even though only 4 cores)

## Edition Comparison

### Standard Edition
- **2 Virtual Machines (VMs)** or **1 physical server**
- Suitable for lightly virtualized environments
- Need additional licenses for more than 2 VMs

### Datacenter Edition
- **Unlimited VMs** on the licensed server
- Better for highly virtualized environments
- More cost-effective when running 13+ VMs

## CAL Requirements

### User CAL
- One CAL per **user** accessing the server
- User can access from multiple devices
- Better for environments with more devices than users

### Device CAL
- One CAL per **device** accessing the server
- Multiple users can share device
- Better for shift workers or shared workstations

### Services Requiring CALs
- File Services
- Print Services
- Active Directory Domain Services
- RDS requires additional **RDS CALs**

## Remote Desktop Services (RDS)

### RDS CAL Requirements
- **Windows Server CAL** + **RDS CAL** required
- RDS CAL types:
  - **User RDS CAL**: Per user accessing RDS
  - **Device RDS CAL**: Per device accessing RDS

### RDS Licensing Grace Period
- 120 days to configure RDS licensing
- Server becomes unlicensed after grace period

## Virtualization Rights

### Standard Edition
- Install on physical host (Hyper-V role)
- Run 2 VMs of Windows Server Standard
- Physical OS counts as one instance

### Datacenter Edition
- Install on physical host
- Run unlimited Windows Server VMs
- All VMs must be on the same physical server

## License Mobility

### Software Assurance Benefits
- **License mobility**: Move VMs between servers
- **Disaster recovery rights**: Passive fail-over replica
- **Azure Hybrid Benefit**: Use on-prem licenses in Azure

### Without Software Assurance
- Licenses tied to specific hardware
- Cannot move between servers
- No Azure Hybrid Benefit

## Downgrade Rights
- Can run earlier versions
- Windows Server 2022 license → Can run 2019, 2016, 2012 R2
- Useful for compatibility

## Common Scenarios

### Scenario 1: Small Business
- 1 physical server (16 cores)
- Running 2 VMs (DC + File Server)
- **License**: Windows Server 2022 Standard (16 cores) + CALs

### Scenario 2: Virtualized Environment
- 1 physical server (32 cores)
- Running 15 VMs
- **License**: Windows Server 2022 Datacenter (32 cores) + CALs

### Scenario 3: Multi-Site
- 3 physical servers (16 cores each)
- Each running 2 VMs
- **License**: 3× Windows Server Standard (16 cores each) + CALs
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': False,
                'is_published': True,
            },
            {
                'title': 'Active Directory Troubleshooting',
                'slug': 'active-directory-troubleshooting',
                'body': '''# Active Directory Troubleshooting

## Common Issues and Solutions

### 1. User Cannot Log In

**Symptoms**: "The trust relationship between this workstation and the primary domain failed"

**Causes**:
- Computer password out of sync with domain
- Time drift between client and DC (>5 minutes)
- DNS resolution issues

**Solutions**:
```powershell
# Reset computer account (run as admin on workstation)
Reset-ComputerMachinePassword -Server DC01.domain.com

# Or remove and rejoin domain
Remove-Computer -UnjoinDomainCredential (Get-Credential) -Force -Restart
Add-Computer -DomainName domain.com -Credential (Get-Credential) -Restart
```

### 2. Replication Failures

**Check replication status**:
```powershell
# View replication summary
repadmin /replsummary

# Show replication partners
repadmin /showrepl

# Force replication between DCs
repadmin /syncall /AdeP
```

**Common errors**:
- **Error 8524**: DNS lookup failure
- **Error 1722**: RPC server unavailable (firewall/network issue)
- **Error 1256**: Authentication failure

### 3. Group Policy Not Applying

**Troubleshooting steps**:
```powershell
# View applied GPOs
gpresult /R

# Generate detailed HTML report
gpresult /H C:\gpreport.html /F

# Force GP update
gpupdate /force

# Check if computer is in correct OU
dsquery computer -name COMPUTERNAME
```

**Common causes**:
- Computer/user in wrong OU
- GPO not linked to correct OU
- Security filtering excludes user/computer
- WMI filters blocking application

### 4. DNS Issues

**Test DNS resolution**:
```powershell
# Test forward lookup
nslookup dc01.domain.com

# Test reverse lookup
nslookup 10.0.0.10

# Test SRV records (critical for AD)
nslookup -type=srv _ldap._tcp.dc._msdcs.domain.com
```

**Fix DNS registration**:
```powershell
# On domain controller
ipconfig /registerdns

# Restart DNS Client service
Restart-Service Dnscache

# Restart Netlogon service
Restart-Service Netlogon
```

### 5. SYSVOL/NETLOGON Share Issues

**Check shares**:
```powershell
# Verify shares exist
net share

# Should see:
# NETLOGON  C:\Windows\SYSVOL\sysvol\domain.com\SCRIPTS
# SYSVOL    C:\Windows\SYSVOL\sysvol
```

**Fix SYSVOL replication**:
```powershell
# Check DFSR status
dfsrdiag replicationstate

# Force replication
dfsrdiag syncnow /partner:DC02 /rgname:"Domain System Volume"
```

### 6. Time Synchronization Issues

**Check time source**:
```powershell
# View time configuration
w32tm /query /status

# On PDC emulator (sync with external source)
w32tm /config /manualpeerlist:"time.windows.com,0x8" /syncfromflags:manual /reliable:YES /update

# On other DCs (sync with domain hierarchy)
w32tm /config /syncfromflags:domhier /update

# Force sync
w32tm /resync /force
```

### 7. Account Lockouts

**Find lockout source**:
```powershell
# Search event logs for account lockouts
Get-EventLog -LogName Security -InstanceId 4740 | Format-List

# Check all DCs for lockout events
Get-ADDomainController -Filter * | ForEach-Object {
    Get-EventLog -ComputerName $_.HostName -LogName Security -InstanceId 4740
}
```

**Common causes**:
- Saved credentials in Credential Manager
- Mapped drives with old credentials
- Services running with user account
- Mobile devices with cached passwords
- Scheduled tasks

### 8. FSMO Role Issues

**View FSMO role holders**:
```powershell
# Using netdom
netdom query fsmo

# Using PowerShell
Get-ADDomain | Select-Object PDCEmulator, RIDMaster, InfrastructureMaster
Get-ADForest | Select-Object SchemaMaster, DomainNamingMaster
```

**Transfer FSMO roles**:
```powershell
# Transfer to current DC (run on target DC)
Move-ADDirectoryServerOperationMasterRole -Identity DC02 -OperationMasterRole PDCEmulator,RIDMaster,InfrastructureMaster,SchemaMaster,DomainNamingMaster
```

**Seize FSMO roles** (if source DC is offline):
```powershell
# Only use if source DC is permanently offline
Move-ADDirectoryServerOperationMasterRole -Identity DC02 -OperationMasterRole PDCEmulator -Force
```

## Diagnostic Commands

### DCDIAG
```powershell
# Basic health check
dcdiag /v

# DNS tests
dcdiag /test:dns /v

# Replication tests
dcdiag /test:replications
```

### REPADMIN
```powershell
# Check replication queue
repadmin /showrepl

# View replication metadata
repadmin /showmeta "CN=Administrator,CN=Users,DC=domain,DC=com"

# List all DCs
repadmin /viewlist *
```

### Event Logs to Check
- **Active Directory Web Services**: Event ID 1202 (SYSVOL ready)
- **DFS Replication**: Event ID 4012 (SYSVOL replication issues)
- **Directory Service**: Event IDs 2042, 2087 (replication errors)
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': False,
                'is_published': True,
            },
            {
                'title': 'Office 365 Licensing Quick Reference',
                'slug': 'office-365-licensing-reference',
                'body': '''# Office 365 Licensing Quick Reference

## Business Plans (Up to 300 users)

### Microsoft 365 Business Basic
**$6/user/month**
- Web and mobile versions of Office apps
- 1 TB OneDrive storage
- Exchange, SharePoint, Teams
- **No desktop Office apps**

### Microsoft 365 Business Standard
**$12.50/user/month**
- **Desktop Office apps** (Word, Excel, PowerPoint, Outlook)
- Web and mobile Office apps
- 1 TB OneDrive storage
- Exchange, SharePoint, Teams
- **Most popular for small businesses**

### Microsoft 365 Business Premium
**$22/user/month**
- Everything in Business Standard
- **Advanced security**: Intune MDM, Azure AD P1
- Threat protection
- Information protection

## Enterprise Plans (Unlimited users)

### Microsoft 365 E3
**$36/user/month**
- Desktop and mobile Office apps
- Advanced compliance and security
- Windows 10/11 Enterprise
- Azure AD P1
- Intune

### Microsoft 365 E5
**$57/user/month**
- Everything in E3
- **Advanced security**: Threat protection, Cloud App Security
- **Advanced compliance**: eDiscovery, Advanced Audit
- Phone system and audio conferencing
- Power BI Pro

## Add-Ons

### Exchange Online (Email Only)
- **Plan 1**: $4/user/month - 50 GB mailbox
- **Plan 2**: $8/user/month - 100 GB mailbox

### SharePoint Online
- **Plan 1**: $5/user/month - 1 TB storage

### Teams Essentials
- **$4/user/month** - Teams only, no Office apps

## License Assignment Best Practices

### Use Groups for Assignment
```powershell
# Assign license via group-based licensing
# In Azure AD, create security group
# Assign licenses to group
# Users inherit licenses automatically
```

### Check License Usage
```powershell
# Connect to Microsoft Graph
Connect-MgGraph -Scopes "User.Read.All","Organization.Read.All"

# View licenses
Get-MgSubscribedSku | Select-Object SkuPartNumber, ConsumedUnits

# View user licenses
Get-MgUser -UserId user@domain.com | Select-Object -ExpandProperty AssignedLicenses
```

## Common Scenarios

### Scenario 1: Small Office (10 users)
**Need**: Email, Office apps, file sharing
**Recommendation**: Microsoft 365 Business Standard
**Cost**: $125/month (10 × $12.50)

### Scenario 2: Remote Team (50 users)
**Need**: Collaboration, security, device management
**Recommendation**: Microsoft 365 Business Premium
**Cost**: $1,100/month (50 × $22)

### Scenario 3: Enterprise (500 users)
**Need**: Full compliance, advanced security
**Recommendation**: Microsoft 365 E3
**Cost**: $18,000/month (500 × $36)

### Scenario 4: Email Only (100 users)
**Need**: Just email, no Office apps
**Recommendation**: Exchange Online Plan 1
**Cost**: $400/month (100 × $4)

## License Comparison

| Feature | Basic | Standard | Premium | E3 | E5 |
|---------|-------|----------|---------|----|----|
| Office Desktop Apps | ❌ | ✅ | ✅ | ✅ | ✅ |
| Exchange Online | ✅ | ✅ | ✅ | ✅ | ✅ |
| OneDrive 1TB | ✅ | ✅ | ✅ | ✅ | ✅ |
| Teams | ✅ | ✅ | ✅ | ✅ | ✅ |
| SharePoint | ✅ | ✅ | ✅ | ✅ | ✅ |
| Intune MDM | ❌ | ❌ | ✅ | ✅ | ✅ |
| Azure AD P1 | ❌ | ❌ | ✅ | ✅ | ✅ |
| Azure AD P2 | ❌ | ❌ | ❌ | ❌ | ✅ |
| Advanced Threat Protection | ❌ | ❌ | ❌ | ❌ | ✅ |
| Phone System | ❌ | ❌ | ❌ | ❌ | ✅ |

## License Troubleshooting

### User Not Receiving License
1. Check license availability
2. Verify group membership (if using group-based)
3. Check usage location (required for licensing)
4. Review license assignment errors in Azure AD

### Shared Mailbox Licensing
- Shared mailboxes **don't require a license** if under 50 GB
- Only need license if:
  - Mailbox size >50 GB
  - Require In-Place Archive
  - Need litigation hold

### Service Activation
After license assignment:
- **Exchange Online**: Available within minutes
- **SharePoint/OneDrive**: Up to 24 hours
- **Teams**: Immediate
''',
                'content_type': 'markdown',
                'is_global': True,
                'is_template': False,
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

        self.stdout.write(self.style.SUCCESS(f'\nCreated {count} new Global KB articles'))
        self.stdout.write(self.style.SUCCESS('Global KB now has practical reference content!'))
