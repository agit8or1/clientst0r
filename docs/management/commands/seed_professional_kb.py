"""
Management command to seed professional IT knowledge base articles.
Creates 75+ high-quality, practical KB articles for MSP/IT support.
"""

from django.core.management.base import BaseCommand
from docs.models import Document, DocumentCategory
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Seeds professional KB articles with comprehensive IT documentation'

    def handle(self, *args, **kwargs):
        self.stdout.write('Creating professional KB categories...')

        # Create categories (organization=None for global KB)
        categories_data = [
            {'name': 'Windows Administration', 'order': 1},
            {'name': 'Active Directory', 'order': 2},
            {'name': 'Microsoft 365', 'order': 3},
            {'name': 'Network Troubleshooting', 'order': 4},
            {'name': 'Security & Compliance', 'order': 5},
            {'name': 'Backup & Recovery', 'order': 6},
            {'name': 'Common Issues', 'order': 7},
            {'name': 'Hardware Setup', 'order': 8},
        ]

        categories = {}
        for cat_data in categories_data:
            cat, created = DocumentCategory.objects.get_or_create(
                name=cat_data['name'],
                organization=None,
                defaults={'order': cat_data['order']}
            )
            categories[cat_data['name']] = cat

        self.stdout.write(self.style.SUCCESS(f'✓ Created {len(categories)} categories'))

        # Define all articles
        articles = []

        # ============================================================
        # WINDOWS ADMINISTRATION (12 articles)
        # ============================================================

        articles.append({
            'category': 'Windows Administration',
            'title': 'How to Reset Windows Local Administrator Password',
            'body': '''# Reset Windows Local Administrator Password

## Overview
This guide covers multiple methods to reset a local administrator password on Windows when locked out of the system.

## 🔒 Prerequisites
- Physical access to the machine
- Windows installation media (USB or DVD) OR
- Password reset disk (if previously created)

---

## Method 1: Using Windows Installation Media (Recommended)

### Step 1: Boot from Installation Media
1. Insert Windows installation USB/DVD
2. Restart computer and press boot menu key (F12, F2, Del, or Esc)
3. Select USB/DVD drive as boot device

### Step 2: Access Command Prompt
1. At "Install Now" screen, press `Shift + F10` to open Command Prompt
2. Alternatively, click "Repair your computer" → "Troubleshoot" → "Command Prompt"

### Step 3: Replace Utilman.exe
```cmd
# Identify Windows drive (usually C: or D:)
dir C:\\Windows

# Backup original Utilman.exe
copy C:\\Windows\\System32\\utilman.exe C:\\Windows\\System32\\utilman.exe.bak

# Replace Utilman with CMD
copy C:\\Windows\\System32\\cmd.exe C:\\Windows\\System32\\utilman.exe

# Restart
wpeutil reboot
```

### Step 4: Reset Password at Login Screen
1. At Windows login screen, click **Accessibility icon** (bottom right)
2. Command Prompt will open (because we replaced Utilman.exe)
3. Run these commands:

```cmd
# List all user accounts
net user

# Reset password for specific user
net user Administrator NewPassword123!

# Or reset password for specific user
net user JohnDoe NewPassword123!
```

### Step 5: Restore Utilman.exe
1. Restart computer with installation media again
2. Open Command Prompt (Shift + F10)
3. Restore original Utilman.exe:

```cmd
copy C:\\Windows\\System32\\utilman.exe.bak C:\\Windows\\System32\\utilman.exe
```

---

## Method 2: Using Safe Mode with Command Prompt

### Works If: Built-in Administrator is enabled

1. Restart PC and press `F8` repeatedly (or `Shift + F8` on newer systems)
2. Select "Safe Mode with Command Prompt"
3. Login as built-in Administrator (if enabled)
4. Open Command Prompt as Administrator
5. Reset password:

```cmd
net user Username NewPassword123!
```

---

## Method 3: Using Password Reset Disk

### If you previously created a password reset disk:

1. At login screen, click "Reset password"
2. Insert password reset USB drive
3. Follow Password Reset Wizard
4. Enter new password

---

## Method 4: Using Third-Party Tools

### Recommended Tools:
- **Offline NT Password & Registry Editor** (Free, Linux-based)
- **Kon-Boot** (Paid, bypasses password)
- **PCUnlocker** (Paid, user-friendly)

### Using Offline NT Password Editor:
1. Download from: https://pogostick.net/~pnh/ntpasswd/
2. Create bootable USB
3. Boot from USB
4. Follow menu to clear/reset password
5. Reboot and login without password (then set new one)

---

## Method 5: Using Another Admin Account

### If another admin account exists:

1. Login with another administrator account
2. Press `Win + X` → "Computer Management"
3. Expand "Local Users and Groups" → "Users"
4. Right-click target user → "Set Password"
5. Enter new password (will lose EFS-encrypted files)

---

## 📋 Post-Reset Security Steps

After resetting password:

1. **Change password immediately:**
   ```cmd
   # Press Win + R, type: control userpasswords2
   # Or use Settings → Accounts → Sign-in options
   ```

2. **Re-enable security features:**
   - Set up Windows Hello if previously used
   - Re-configure BitLocker if applicable
   - Update password in Credential Manager

3. **Document recovery method:**
   - Create password reset disk
   - Document in password manager
   - Enable Microsoft account recovery

---

## ⚠️ Important Notes

- **EFS Warning:** Resetting password loses access to EFS-encrypted files
- **Microsoft Account:** For Microsoft accounts, reset at: https://account.live.com/password/reset
- **Domain Accounts:** Must be reset by domain administrator
- **BitLocker:** May require recovery key if password is changed offline

---

## 🔐 Prevention Tips

1. **Use Microsoft Account** instead of local account
2. **Create password reset disk** immediately
3. **Enable additional admin account** for emergencies
4. **Use password manager** to securely store passwords
5. **Document passwords** in secure location (LastPass, Bitwarden, etc.)
6. **Enable PIN/Windows Hello** as alternative sign-in

---

## Troubleshooting

**Issue:** "Access Denied" when running net user
- **Solution:** Ensure Command Prompt is running as Administrator

**Issue:** Can't boot from USB
- **Solution:** Disable Secure Boot in BIOS/UEFI

**Issue:** Windows drive not found
- **Solution:** Try different drive letters (C:, D:, E:)

**Issue:** Utilman.exe replacement doesn't work
- **Solution:** Try replacing sethc.exe (Sticky Keys) instead
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'Optimize Windows 10/11 Performance - Complete Guide',
            'body': '''# Optimize Windows 10/11 Performance

## 🎯 Overview
Comprehensive guide to improve Windows performance, reduce boot time, and optimize system resources.

---

## 🚀 Quick Wins (Do These First)

### 1. Disable Startup Programs
```powershell
# View startup programs
Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location

# Disable via Task Manager
# Press Ctrl + Shift + Esc → Startup tab → Disable unnecessary items
```

**Commonly Safe to Disable:**
- Adobe Updater
- iTunes Helper
- Spotify
- Skype
- Zoom (if not used daily)
- Microsoft Teams (if not used daily)

**Keep Enabled:**
- Antivirus software
- Graphics card utilities (NVIDIA, AMD)
- Audio drivers (Realtek, etc.)

### 2. Adjust Visual Effects for Performance
```powershell
# Open System Properties
SystemPropertiesPerformance.exe

# Or navigate: Control Panel → System → Advanced → Performance Settings
# Select "Adjust for best performance" or "Custom" and disable:
# - Animate windows when minimizing/maximizing
# - Animations in taskbar
# - Fade or slide menus
# - Show shadows under windows
```

### 3. Disable Windows Search Indexing (Optional)
```powershell
# Stop and disable Windows Search service
Stop-Service -Name "WSearch" -Force
Set-Service -Name "WSearch" -StartupType Disabled

# Re-enable if search becomes too slow:
Set-Service -Name "WSearch" -StartupType Automatic
Start-Service -Name "WSearch"
```

---

## 💾 Storage Optimization

### 1. Run Disk Cleanup
```powershell
# Launch Disk Cleanup
cleanmgr.exe

# Run with elevated options
cleanmgr.exe /sageset:1

# Check items:
# - Temporary files
# - Downloads folder
# - Recycle Bin
# - Windows Update Cleanup
# - System error memory dump files
```

### 2. Enable Storage Sense
```powershell
# Enable Storage Sense (auto cleanup)
# Settings → System → Storage → Storage Sense → Turn on

# Configure to run:
# - During low free disk space
# - Every week/month
# - Delete files in Recycle Bin after 30 days
# - Delete files in Downloads after 60 days
```

### 3. Clean Windows Update Files
```powershell
# Clean Windows Update cache
Stop-Service -Name wuauserv -Force
Remove-Item C:\\Windows\\SoftwareDistribution\\* -Recurse -Force
Start-Service -Name wuauserv
```

### 4. Analyze Disk Space Usage
```powershell
# Install TreeSize or WinDirStat (free tools)
# Or use built-in:
Get-ChildItem C:\\ -Directory |
    ForEach-Object {
        $size = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue |
                 Measure-Object -Property Length -Sum).Sum / 1GB
        [PSCustomObject]@{
            Folder = $_.Name
            'Size (GB)' = [math]::Round($size, 2)
        }
    } | Sort-Object 'Size (GB)' -Descending | Format-Table
```

---

## 🔧 System Services Optimization

### Disable Unnecessary Services
```powershell
# View all running services
Get-Service | Where-Object {$_.Status -eq "Running"} |
    Select-Object DisplayName, Name, StartType

# Services safe to disable on most systems:
$servicesToDisable = @(
    "DiagTrack",              # Connected User Experiences and Telemetry
    "dmwappushservice",       # Device Management Wireless Push
    "lfsvc",                  # Geolocation Service (if not needed)
    "MapsBroker",            # Downloaded Maps Manager
    "NetTcpPortSharing",     # Net.Tcp Port Sharing (rarely used)
    "RemoteRegistry",        # Remote Registry (security risk)
    "WSearch",               # Windows Search (if not using search)
    "XblAuthManager",        # Xbox services (if not gaming)
    "XblGameSave",           # Xbox Game Save
    "XboxNetApiSvc"          # Xbox Live Networking
)

foreach ($service in $servicesToDisable) {
    Stop-Service -Name $service -Force -ErrorAction SilentlyContinue
    Set-Service -Name $service -StartupType Disabled -ErrorAction SilentlyContinue
    Write-Host "Disabled: $service"
}
```

---

## 🖥️ System Settings Optimization

### 1. Adjust Power Settings
```powershell
# Set to High Performance power plan
powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c

# Or create custom Ultimate Performance plan (Windows 10 Pro+)
powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61

# Disable hibernation to free up space
powercfg /hibernate off
```

### 2. Disable Transparency Effects
```powershell
# Settings → Personalization → Colors → Transparency effects → Off
# Or via Registry:
Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize" `
    -Name "EnableTransparency" -Value 0 -Type DWord
```

### 3. Disable Windows Tips and Suggestions
```powershell
# Disable tips and suggestions
Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\ContentDeliveryManager" `
    -Name "SubscribedContent-338389Enabled" -Value 0 -Type DWord
```

---

## 🔄 Update and Driver Optimization

### 1. Update All Drivers
```powershell
# Check for Windows Updates
Install-Module PSWindowsUpdate -Force
Get-WindowsUpdate
Install-WindowsUpdate -AcceptAll -AutoReboot

# Update drivers via Device Manager or:
# - Intel Driver Assistant
# - AMD Driver Auto-Detect
# - NVIDIA GeForce Experience
# - Dell/HP/Lenovo driver update tools
```

### 2. Update Graphics Drivers
- **NVIDIA:** Download GeForce Experience or driver from nvidia.com
- **AMD:** Download Adrenalin software or driver from amd.com
- **Intel:** Download Driver Assistant from intel.com

---

## 🧹 Advanced Optimizations

### 1. Optimize SSD (If Applicable)
```powershell
# Verify TRIM is enabled
fsutil behavior query DisableDeleteNotify
# Result should be: DisableDeleteNotify = 0 (TRIM enabled)

# Optimize drives
Optimize-Volume -DriveLetter C -ReTrim -Verbose
```

### 2. Adjust Paging File Size
```powershell
# Recommended: Let Windows manage automatically
# Or set manually:
# Control Panel → System → Advanced → Performance → Settings → Advanced → Virtual Memory
# Set custom size: Initial = 1.5x RAM, Maximum = 3x RAM
```

### 3. Disable SuperFetch/Prefetch (SSD Only)
```powershell
# Only disable on SSD systems
Stop-Service -Name "SysMain" -Force
Set-Service -Name "SysMain" -StartupType Disabled
```

### 4. Clean Registry (Use with Caution)
```powershell
# Use CCleaner or similar tool
# Or manually: Run → regedit
# Backup before cleaning: File → Export

# Recommended tool: CCleaner (free)
# Download from: https://www.ccleaner.com/
```

---

## 📊 Monitor Performance

### 1. Use Task Manager Effectively
```powershell
# Press Ctrl + Shift + Esc
# Check these tabs:
# - Processes: Sort by CPU/Memory to find resource hogs
# - Performance: Monitor real-time usage
# - Startup: Disable unnecessary startup items
```

### 2. Use Resource Monitor
```powershell
# Launch Resource Monitor
resmon.exe

# Tabs to check:
# - CPU: See which processes use most CPU
# - Memory: Identify memory leaks
# - Disk: Find programs causing high disk usage
# - Network: Monitor bandwidth usage
```

### 3. Use Performance Monitor
```powershell
# Launch Performance Monitor
perfmon.exe

# Key counters to monitor:
# - Processor: % Processor Time
# - Memory: Available MBytes
# - Physical Disk: % Idle Time, Avg. Disk Queue Length
```

---

## 🎯 Specific Issue Fixes

### Fix High Disk Usage (100%)
```powershell
# Common causes and fixes:

# 1. Disable Windows Search temporarily
Stop-Service -Name "WSearch"

# 2. Disable SuperFetch
Stop-Service -Name "SysMain"

# 3. Check for malware
# Run Windows Defender full scan

# 4. Check disk health
wmic diskdrive get status
# Should return "OK"

# 5. Run disk check
chkdsk C: /f /r
# Restart to run check
```

### Fix High Memory Usage
```powershell
# 1. Identify memory hog
Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 10

# 2. Close unnecessary applications
# 3. Restart Windows Explorer
Stop-Process -Name explorer -Force

# 4. Increase virtual memory (if RAM < 8GB)
# 5. Add more physical RAM if consistently high
```

---

## ✅ Maintenance Checklist

### Daily:
- [ ] Close unused applications
- [ ] Check Task Manager for resource hogs
- [ ] Restart if uptime > 7 days

### Weekly:
- [ ] Empty Recycle Bin
- [ ] Clear browser cache
- [ ] Check for Windows Updates
- [ ] Run Windows Defender scan

### Monthly:
- [ ] Run Disk Cleanup
- [ ] Check disk space (keep 15%+ free)
- [ ] Review and remove unused programs
- [ ] Clear temp files
- [ ] Defragment HDD (SSD auto-optimizes)

---

## 🚫 Things to AVOID

1. ❌ **Don't disable Windows Update** - Security is critical
2. ❌ **Don't use "RAM cleaner" software** - Snake oil, doesn't help
3. ❌ **Don't disable antivirus** - Major security risk
4. ❌ **Don't edit registry without backup** - Can break Windows
5. ❌ **Don't delete System32** - NEVER, will break Windows
6. ❌ **Don't use "PC optimizer" software** - Usually malware/bloatware

---

## Expected Results

After optimization:
- ⚡ **Boot time:** 30-60 seconds (from power on to desktop)
- 💻 **Memory usage:** 2-4 GB idle (depends on RAM amount)
- 🖥️ **CPU usage:** <10% idle
- 💾 **Disk usage:** <5% idle
- 📱 **Application launch:** <3 seconds for most programs
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'Create and Manage Group Policy Objects (GPO)',
            'body': '''# Create and Manage Group Policy Objects (GPO)

## 🎯 Overview
Group Policy Objects (GPOs) are used to manage and configure operating systems, applications, and user settings in Active Directory environments.

---

## 📋 Prerequisites

- Domain Administrator or equivalent rights
- Windows Server with AD DS role installed
- Group Policy Management Console (GPMC) installed
- Understanding of OU (Organizational Unit) structure

---

## 🚀 Getting Started with GPOs

### Install Group Policy Management Console
```powershell
# On Windows Server
Install-WindowsFeature GPMC

# On Windows 10/11 (RSAT)
Add-WindowsCapability -Online -Name Rsat.GroupPolicy.Management.Tools~~~~0.0.1.0
```

### Launch GPMC
```powershell
# Open GPMC
gpmc.msc

# Or from PowerShell
Start-Process gpmc.msc
```

---

## 🆕 Creating a New GPO

### Method 1: Using GPMC GUI

1. Open **Group Policy Management Console** (gpmc.msc)
2. Navigate to desired OU: `Forest → Domains → yourdomain.com → Organizational Units`
3. Right-click OU → **Create a GPO in this domain, and Link it here**
4. Name the GPO (e.g., "Company Security Policy")
5. Right-click new GPO → **Edit**

### Method 2: Using PowerShell

```powershell
# Import Group Policy module
Import-Module GroupPolicy

# Create new GPO
New-GPO -Name "Company Security Policy" -Comment "Enforces security standards"

# Link GPO to OU
New-GPLink -Name "Company Security Policy" -Target "OU=Workstations,DC=contoso,DC=com"

# Verify creation
Get-GPO -Name "Company Security Policy"
```

---

## 🛡️ Common GPO Configurations

### 1. Password Policy

```powershell
# Navigate to:
# Computer Configuration → Policies → Windows Settings → Security Settings → Account Policies → Password Policy

# Settings to configure:
# - Enforce password history: 24 passwords
# - Maximum password age: 90 days
# - Minimum password age: 1 day
# - Minimum password length: 12 characters
# - Password must meet complexity requirements: Enabled
# - Store passwords using reversible encryption: Disabled
```

**PowerShell Method:**
```powershell
# Set password policy via PowerShell
Set-ADDefaultDomainPasswordPolicy -Identity contoso.com `
    -MinPasswordLength 12 `
    -PasswordHistoryCount 24 `
    -MaxPasswordAge 90.00:00:00 `
    -MinPasswordAge 1.00:00:00 `
    -ComplexityEnabled $true
```

### 2. Account Lockout Policy

```powershell
# Navigate to:
# Computer Configuration → Policies → Windows Settings → Security Settings → Account Policies → Account Lockout Policy

# Recommended settings:
# - Account lockout duration: 30 minutes
# - Account lockout threshold: 5 invalid attempts
# - Reset account lockout counter after: 30 minutes
```

### 3. Disable USB Storage

```powershell
# Computer Configuration → Policies → Administrative Templates → System → Removable Storage Access

# Disable:
# - All Removable Storage classes: Deny all access
# - Removable Disks: Deny read access
# - Removable Disks: Deny write access
```

**Registry Method:**
```powershell
# Computer Configuration → Preferences → Windows Settings → Registry

# Create new registry item:
# Action: Update
# Hive: HKEY_LOCAL_MACHINE
# Key Path: SYSTEM\\CurrentControlSet\\Services\\USBSTOR
# Value name: Start
# Value type: REG_DWORD
# Value data: 4 (Disabled)
```

### 4. Enable Windows Firewall

```powershell
# Computer Configuration → Policies → Windows Settings → Security Settings → Windows Defender Firewall

# Configure for all profiles (Domain, Private, Public):
# - Firewall state: On
# - Inbound connections: Block (default)
# - Outbound connections: Allow (default)
```

### 5. Software Deployment

```powershell
# Computer Configuration → Policies → Software Settings → Software installation

# Right-click → New → Package
# Browse to .msi file on network share (e.g., \\\\server\\share\\software.msi)
# Select deployment method:
# - Assigned: Auto-installs on computer startup
# - Published: Available in Control Panel "Programs and Features"
```

### 6. Drive Mapping

```powershell
# User Configuration → Preferences → Windows Settings → Drive Maps

# Create new mapped drive:
# Action: Create
# Location: \\\\fileserver\\share
# Reconnect: Enabled
# Label as: Company Files
# Drive Letter: H:
# Use: User credentials
```

### 7. Desktop Background/Wallpaper

```powershell
# User Configuration → Policies → Administrative Templates → Desktop → Desktop

# Enable: Desktop Wallpaper
# Wallpaper Name: \\\\server\\share\\wallpaper.jpg
# Wallpaper Style: Fill
```

### 8. Disable Control Panel Access

```powershell
# User Configuration → Policies → Administrative Templates → Control Panel

# Enable: Prohibit access to Control Panel and PC settings
```

### 9. Configure Windows Update

```powershell
# Computer Configuration → Policies → Administrative Templates → Windows Components → Windows Update

# Configure Automatic Updates:
# - Option 4: Auto download and schedule install
# - Scheduled install day: Every day
# - Scheduled install time: 03:00

# Enable: Specify intranet Microsoft update service location
# - Update server: http://wsus.contoso.com:8530
# - Statistics server: http://wsus.contoso.com:8530
```

### 10. BitLocker Encryption Policy

```powershell
# Computer Configuration → Policies → Administrative Templates → Windows Components → BitLocker Drive Encryption

# Operating System Drives:
# - Require additional authentication at startup: Enabled
# - Allow BitLocker without a compatible TPM: Disabled
# - Configure TPM startup PIN: Require startup PIN with TPM

# Choose how BitLocker-protected operating system drives can be recovered:
# - Save BitLocker recovery information to AD DS: Enabled
# - Store recovery passwords and key packages: Enabled
```

---

## 🔧 GPO Management Tasks

### Edit Existing GPO

```powershell
# Via PowerShell
Get-GPO -Name "Company Security Policy" | Get-GPOReport -ReportType Html -Path "C:\\GPOReport.html"

# Via GUI
# Right-click GPO → Edit
```

### Link GPO to Multiple OUs

```powershell
# Link to multiple OUs
New-GPLink -Name "Company Security Policy" -Target "OU=Laptops,DC=contoso,DC=com"
New-GPLink -Name "Company Security Policy" -Target "OU=Desktops,DC=contoso,DC=com"

# Verify links
Get-GPO -Name "Company Security Policy" | Get-GPOReport -ReportType Xml | Select-String "SOMName"
```

### Set GPO Link Order

```powershell
# Higher link order = applied first
# Link order 1 = highest priority

# Set link order via PowerShell
Set-GPLink -Name "Company Security Policy" -Target "OU=Workstations,DC=contoso,DC=com" -LinkEnabled Yes -Order 1

# Via GUI: Right-click OU → Link Order → Move up/down
```

### Enable/Disable GPO Link

```powershell
# Disable GPO link
Set-GPLink -Name "Company Security Policy" -Target "OU=Workstations,DC=contoso,DC=com" -LinkEnabled No

# Enable GPO link
Set-GPLink -Name "Company Security Policy" -Target "OU=Workstations,DC=contoso,DC=com" -LinkEnabled Yes
```

### Backup GPO

```powershell
# Backup single GPO
Backup-GPO -Name "Company Security Policy" -Path "C:\\GPO Backups"

# Backup all GPOs
Backup-GPO -All -Path "C:\\GPO Backups"

# Backup with comment
Backup-GPO -Name "Company Security Policy" -Path "C:\\GPO Backups" -Comment "Pre-migration backup"
```

### Restore GPO

```powershell
# List available backups
Get-GPOBackup -Path "C:\\GPO Backups"

# Restore GPO
Restore-GPO -Name "Company Security Policy" -Path "C:\\GPO Backups"

# Restore by backup ID
Restore-GPO -BackupId "12345678-90ab-cdef-1234-567890abcdef" -Path "C:\\GPO Backups"
```

### Copy GPO

```powershell
# Copy GPO to new GPO
Copy-GPO -SourceName "Company Security Policy" -TargetName "Branch Office Security Policy"

# Copy across domains
Copy-GPO -SourceName "Company Security Policy" -SourceDomain "contoso.com" `
         -TargetName "Company Security Policy" -TargetDomain "branch.contoso.com"
```

### Delete GPO

```powershell
# Remove GPO
Remove-GPO -Name "Old Policy"

# Via GUI: Right-click GPO → Delete
# Warning: Cannot be undone without backup
```

---

## 🔍 GPO Troubleshooting

### Force GPO Update

```powershell
# On client computer
gpupdate /force

# Remote force update
Invoke-GPUpdate -Computer "WORKSTATION01" -Force

# Update specific GPO
Invoke-GPUpdate -Computer "WORKSTATION01" -Target "Computer"
```

### View Applied GPOs

```powershell
# Generate RSoP report
gpresult /h "C:\\GPReport.html"

# View in console
gpresult /r

# Detailed results
gpresult /z

# For specific user
gpresult /user USERNAME /r

# Remote computer
gpresult /s COMPUTERNAME /r
```

### GPO Processing Order

1. **Local** - Local Group Policy on computer
2. **Site** - GPOs linked to AD site
3. **Domain** - GPOs linked to domain
4. **OU** - GPOs linked to OU (top-level first, then nested)

**Remember LSDOU**: Local, Site, Domain, OU

### Check GPO Replication

```powershell
# Check AD replication
repadmin /showrepl

# Force replication
repadmin /syncall

# Check SYSVOL replication
dfsrdiag ReplicationState

# Verify GPO version
Get-GPO -Name "Company Security Policy" | Select-Object DisplayName, GpoStatus, CreationTime, ModificationTime
```

### Common GPO Issues

#### Issue: GPO Not Applying

**Troubleshooting Steps:**
```powershell
# 1. Verify GPO is linked to correct OU
Get-GPInheritance -Target "OU=Workstations,DC=contoso,DC=com"

# 2. Check if GPO link is enabled
Get-GPO -Name "Company Security Policy" | Get-GPOReport -ReportType Xml

# 3. Verify no "Block Inheritance" is set
# GPMC → Right-click OU → Properties → Check "Block Inheritance"

# 4. Check if GPO is enforced
Set-GPLink -Name "Company Security Policy" -Target "OU=Workstations,DC=contoso,DC=com" -Enforced Yes

# 5. Verify SYSVOL is accessible
Test-Path "\\\\contoso.com\\SYSVOL"

# 6. Check event logs
Get-EventLog -LogName Application -Source "Group Policy" -Newest 50
```

#### Issue: Slow Logon Due to GPO

```powershell
# Enable verbose logging
gpupdate /force /wait:0

# Analyze GPO processing time
Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Group Policy\\History"

# Check slow link detection
Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\System"
```

---

## 🎯 GPO Best Practices

### 1. Naming Convention
```
[Type]_[Category]_[Description]_[Version]

Examples:
- COMP_SEC_BitLocker_v1
- USER_APP_OfficeSettings_v2
- COMP_NET_FirewallRules_v1
```

### 2. Documentation
- Document purpose of each GPO
- List affected OUs
- Note dependencies
- Record change history
- Include contact information

### 3. Testing
1. Create test OU
2. Link GPO to test OU
3. Test with pilot users/computers
4. Monitor for 1-2 weeks
5. Deploy to production

### 4. Security Filtering
```powershell
# Apply GPO to specific security group only
Set-GPPermissions -Name "Company Security Policy" -TargetName "IT Admins" -TargetType Group -PermissionLevel GpoApply

# Remove "Authenticated Users"
Set-GPPermissions -Name "Company Security Policy" -TargetName "Authenticated Users" -TargetType Group -PermissionLevel None
```

### 5. WMI Filtering
```powershell
# Create WMI filter for Windows 10 only
# GPMC → Right-click WMI Filters → New

# Query:
# SELECT * FROM Win32_OperatingSystem WHERE Version LIKE "10.%"
```

---

## 📊 GPO Reporting

### Generate HTML Report
```powershell
Get-GPOReport -Name "Company Security Policy" -ReportType Html -Path "C:\\GPO_Report.html"
```

### Generate All GPOs Report
```powershell
Get-GPOReport -All -ReportType Html -Path "C:\\All_GPO_Report.html"
```

### Export GPO Settings
```powershell
Get-GPO -All | ForEach-Object {
    $reportPath = "C:\\GPO Reports\\$($_.DisplayName).html"
    Get-GPOReport -Guid $_.Id -ReportType Html -Path $reportPath
}
```

---

## ✅ GPO Maintenance Checklist

### Monthly:
- [ ] Review and update GPO documentation
- [ ] Check for conflicting policies
- [ ] Remove obsolete GPOs
- [ ] Backup all GPOs

### Quarterly:
- [ ] Review security settings
- [ ] Update software deployment packages
- [ ] Test GPO application on new OS versions
- [ ] Audit GPO permissions

### Annually:
- [ ] Complete GPO inventory
- [ ] Review and consolidate similar GPOs
- [ ] Update naming conventions if needed
- [ ] Provide GPO training for IT staff
'''
        })

        # Continue with more Windows Administration articles...
        articles.append({
            'category': 'Windows Administration',
            'title': 'Configure and Troubleshoot Windows Updates',
            'body': '''# Configure and Troubleshoot Windows Updates

## 🎯 Overview
Complete guide to managing Windows Update, troubleshooting update failures, and configuring update policies.

---

## 🔍 Check Windows Update Status

### Using Settings (GUI)
1. Press `Win + I` → **Windows Update**
2. Click "Check for updates"
3. View update history: **Update history** → **View update history**

### Using PowerShell
```powershell
# Check for available updates
Get-WindowsUpdate

# View update history
Get-WUHistory

# Check last update time
Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 10
```

### Using Command Prompt
```cmd
# Check Windows Update service status
sc query wuauserv

# View installed updates
wmic qfe list
```

---

## 🛠️ Configure Windows Update Settings

### Using Group Policy (Domain)

```powershell
# Navigate to:
# Computer Configuration → Administrative Templates → Windows Components → Windows Update

# Key settings:

# 1. Configure Automatic Updates
# Options:
# - 2 = Notify for download and notify for install
# - 3 = Auto download and notify for install (Recommended)
# - 4 = Auto download and schedule install
# - 5 = Allow local admin to choose

# 2. Specify intranet Microsoft update service location
# Set update server: http://wsus.company.com:8530
# Set statistics server: http://wsus.company.com:8530

# 3. Configure Automatic Updates Schedule
# Scheduled install day: 0 (Every day) or 1-7 (day of week)
# Scheduled install time: 03:00 (3 AM recommended)

# 4. No auto-restart with logged on users
# Enabled (prevents forced restarts during work hours)

# 5. Specify deadline before auto-restart for update install
# Set to: 7 days (gives users time to manually restart)
```

### Using Registry (Standalone/Workgroup)

```powershell
# Configure Windows Update behavior
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU" `
    -Name "AUOptions" -Value 3 -Type DWord

# Options:
# 2 = Notify before download
# 3 = Auto download, notify before install
# 4 = Auto download and schedule install
# 5 = Allow local admin to choose

# Set automatic update schedule (if AUOptions = 4)
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU" `
    -Name "ScheduledInstallDay" -Value 0 -Type DWord  # 0 = Every day

Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU" `
    -Name "ScheduledInstallTime" -Value 3 -Type DWord  # 3 = 3 AM
```

### Using PowerShell Module

```powershell
# Install PSWindowsUpdate module
Install-Module -Name PSWindowsUpdate -Force

# Import module
Import-Module PSWindowsUpdate

# Configure automatic updates
Set-WUSettings -AutoUpdate Enabled -ScheduledInstallDay 0 -ScheduledInstallTime 3

# Disable automatic updates (not recommended)
Set-WUSettings -AutoUpdate Disabled
```

---

## 🔄 Manual Windows Update Operations

### Check for Updates
```powershell
# Using PSWindowsUpdate module
Get-WindowsUpdate

# Check specific categories
Get-WindowsUpdate -Category "Security Updates", "Critical Updates"

# Show available updates with details
Get-WindowsUpdate -Verbose
```

### Install Updates
```powershell
# Install all available updates
Install-WindowsUpdate -AcceptAll -AutoReboot

# Install without automatic reboot
Install-WindowsUpdate -AcceptAll -IgnoreReboot

# Install specific update by KB number
Get-WindowsUpdate -KBArticleID "KB5012345" | Install-WindowsUpdate -AcceptAll

# Install only security updates
Install-WindowsUpdate -Category "Security Updates" -AcceptAll -IgnoreReboot

# Download updates without installing
Get-WindowsUpdate -Download
```

### Hide/Show Updates
```powershell
# Hide specific update
Hide-WindowsUpdate -KBArticleID "KB5012345"

# Show hidden updates
Get-WindowsUpdate -IsHidden

# Unhide update
Show-WindowsUpdate -KBArticleID "KB5012345"
```

---

## 🚨 Troubleshoot Windows Update Issues

### Fix 1: Reset Windows Update Components

```powershell
# Stop Windows Update services
Stop-Service -Name wuauserv -Force
Stop-Service -Name cryptSvc -Force
Stop-Service -Name bits -Force
Stop-Service -Name msiserver -Force

# Rename SoftwareDistribution and Catroot2 folders
Rename-Item -Path "C:\\Windows\\SoftwareDistribution" -NewName "SoftwareDistribution.old" -Force
Rename-Item -Path "C:\\Windows\\System32\\catroot2" -NewName "Catroot2.old" -Force

# Re-register DLL files
regsvr32 /s wuapi.dll
regsvr32 /s wuaueng.dll
regsvr32 /s wups.dll
regsvr32 /s wups2.dll
regsvr32 /s wuwebv.dll
regsvr32 /s wucltux.dll

# Start Windows Update services
Start-Service -Name wuauserv
Start-Service -Name cryptSvc
Start-Service -Name bits
Start-Service -Name msiserver

# Force update check
wuauclt /detectnow
```

### Fix 2: Run Windows Update Troubleshooter

```powershell
# Download and run Windows Update Troubleshooter
# Via Settings
# Settings → System → Troubleshoot → Other troubleshooters → Windows Update

# Via PowerShell
Start-Process "msdt.exe" -ArgumentList "/id WindowsUpdateDiagnostic"

# Advanced troubleshooter
Start-Process "https://aka.ms/wudiag"  # Opens browser to download tool
```

### Fix 3: DISM and SFC Scan

```powershell
# Run DISM to repair Windows image
DISM /Online /Cleanup-Image /CheckHealth
DISM /Online /Cleanup-Image /ScanHealth
DISM /Online /Cleanup-Image /RestoreHealth

# Run System File Checker
sfc /scannow

# After completion, restart and try Windows Update again
```

### Fix 4: Clear Windows Update Cache

```powershell
# Stop Windows Update service
Stop-Service -Name wuauserv

# Delete update cache files
Remove-Item -Path "C:\\Windows\\SoftwareDistribution\\Download\\*" -Recurse -Force

# Start Windows Update service
Start-Service -Name wuauserv

# Check for updates
wuauclt /detectnow
```

### Fix 5: Manual Update Installation

If Windows Update fails completely:

1. **Visit Windows Update Catalog:** https://www.catalog.update.microsoft.com/
2. Search for KB number (e.g., "KB5012345")
3. Download appropriate version (x64/x86)
4. Run .msu installer manually:
   ```cmd
   wusa.exe C:\\Downloads\\windows10.0-kb5012345-x64.msu
   ```

---

## 🔧 Common Error Codes and Solutions

### Error 0x80070002
**Cause:** Files missing or corrupted

**Solution:**
```powershell
# Reset Windows Update components (see Fix 1 above)
# Then run DISM and SFC:
DISM /Online /Cleanup-Image /RestoreHealth
sfc /scannow
```

### Error 0x8007000E
**Cause:** Insufficient disk space

**Solution:**
```powershell
# Check free space
Get-PSDrive C

# Run Disk Cleanup
cleanmgr.exe /autoclean

# Delete temp files
Remove-Item -Path "$env:TEMP\\*" -Recurse -Force -ErrorAction SilentlyContinue
```

### Error 0x80073701 / 0x800f0982
**Cause:** Component Store corruption

**Solution:**
```powershell
# Reset Component Store
DISM /Online /Cleanup-Image /StartComponentCleanup
DISM /Online /Cleanup-Image /RestoreHealth

# Restart and retry update
```

### Error 0x80070643
**Cause:** .NET Framework update failure

**Solution:**
```powershell
# Repair .NET Framework
DISM /Online /Cleanup-Image /RestoreHealth

# Download .NET Repair Tool
# https://www.microsoft.com/en-us/download/details.aspx?id=30135
```

### Error 0x800F0922
**Cause:** Reserved partition full

**Solution:**
```powershell
# Check System Reserved partition
Get-Partition | Where-Object {$_.GptType -eq "{e3c9e316-0b5c-4db8-817d-f92df00215ae}"}

# Extend partition or clear old backups
vssadmin delete shadows /for=C: /oldest

# Or disable System Restore temporarily
Disable-ComputerRestore -Drive "C:\\"
```

---

## 📊 Monitor Windows Update Status

### Check Update History
```powershell
# View recently installed updates
Get-WUHistory -MaxDate (Get-Date).AddDays(-30) |
    Select-Object Date, Title, Result | Format-Table -AutoSize

# Export update history to CSV
Get-WUHistory | Export-Csv -Path "C:\\UpdateHistory.csv" -NoTypeInformation
```

### Check Pending Reboot
```powershell
# Check if reboot is required
Test-PendingReboot

# Or check registry
Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired" -ErrorAction SilentlyContinue
```

### View Windows Update Logs
```powershell
# Windows 10/11: Generate readable log from ETL
Get-WindowsUpdateLog

# Opens WindowsUpdate.log in notepad
# Log saved to: C:\\Users\\<username>\\Desktop\\WindowsUpdate.log

# View CBS log (Component-Based Servicing)
notepad C:\\Windows\\Logs\\CBS\\CBS.log
```

---

## 🎯 Windows Update Best Practices

### 1. Create Update Schedule
- **Workstations:** Tuesday or Wednesday after Patch Tuesday
- **Servers:** Weekend or maintenance window
- **Test environment:** Immediately after Patch Tuesday
- **Production:** 1 week after testing

### 2. Use WSUS for Enterprise

**Benefits:**
- Centralized update management
- Bandwidth savings
- Approval workflow
- Reporting and compliance

**Setup:**
```powershell
# Install WSUS role on Windows Server
Install-WindowsFeature -Name UpdateServices -IncludeManagementTools

# Point clients to WSUS via GPO
# Computer Configuration → Administrative Templates → Windows Components → Windows Update
# Specify intranet Microsoft update service location:
# http://wsus.company.com:8530
```

### 3. Implement Staged Rollouts

**Groups:**
1. **Pilot/Test (10%):** IT staff, test users
2. **Ring 1 (25%):** Early adopters, power users
3. **Ring 2 (50%):** General users
4. **Ring 3 (15%):** VIPs, executives (wait for stability)

### 4. Regular Maintenance

```powershell
# Monthly Windows Update maintenance script
$tasks = @{
    "Check for updates" = {Get-WindowsUpdate}
    "Clear update cache" = {
        Stop-Service wuauserv
        Remove-Item "C:\\Windows\\SoftwareDistribution\\Download\\*" -Recurse -Force
        Start-Service wuauserv
    }
    "Clean old backups" = {DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase}
    "Check disk space" = {Get-PSDrive C}
}

foreach ($task in $tasks.GetEnumerator()) {
    Write-Host "Running: $($task.Key)"
    & $task.Value
}
```

---

## 🔒 Security Considerations

### Critical Updates to Prioritize

1. **Security Updates** - Deploy within 48 hours
2. **Critical Updates** - Deploy within 1 week
3. **Feature Updates** - Deploy quarterly after testing
4. **Optional Updates** - Deploy as needed

### Verify Update Authenticity
```powershell
# Check update signatures
Get-AuthenticodeSignature -FilePath "C:\\path\\to\\update.msu"

# Should show:
# Status: Valid
# SignerCertificate: CN=Microsoft Windows, ...
```

---

## ✅ Windows Update Checklist

### Pre-Update:
- [ ] Verify backups are current
- [ ] Document current system state
- [ ] Check disk space (15+ GB free)
- [ ] Review known issues for updates
- [ ] Schedule maintenance window
- [ ] Notify users of potential disruption

### During Update:
- [ ] Monitor update progress
- [ ] Check for errors in event logs
- [ ] Verify successful installation
- [ ] Test critical applications

### Post-Update:
- [ ] Verify system functionality
- [ ] Test user applications
- [ ] Check for pending reboots
- [ ] Review event logs for errors
- [ ] Document any issues
- [ ] Update configuration management database
'''
        })

        # ============================================================
        # WINDOWS ADMINISTRATION (6 more articles)
        # ============================================================

        articles.append({
            'category': 'Windows Administration',
            'title': 'Remote Desktop Services Configuration and Troubleshooting',
            'body': '''# Remote Desktop Services Configuration

## 🎯 Overview
Complete guide to configuring Remote Desktop Services (RDS) on Windows Server and troubleshooting common RDP connection issues.

---

## 🔒 Prerequisites

- Windows Server 2016/2019/2022 or Windows 10/11 Pro
- Administrator privileges
- Static IP address (recommended for servers)
- Open firewall ports (3389)

---

## 📝 Enable Remote Desktop

### Windows Server

```powershell
# Enable Remote Desktop via PowerShell
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name "fDenyTSConnections" -Value 0

# Enable Remote Desktop with Network Level Authentication
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "UserAuthentication" -Value 1

# Enable Remote Desktop firewall rule
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# Verify RDP service is running
Get-Service TermService | Start-Service
Set-Service -Name TermService -StartupType Automatic
```

### Windows 10/11 Pro

```powershell
# Enable RDP via PowerShell
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name "fDenyTSConnections" -Value 0

# Enable firewall rule
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# Or via GUI:
# Settings → System → Remote Desktop → Enable
```

---

## 🔧 Configure Remote Desktop Settings

### Allow Specific Users

```powershell
# Add user to Remote Desktop Users group
Add-LocalGroupMember -Group "Remote Desktop Users" -Member "DOMAIN\\username"

# Or local user
Add-LocalGroupMember -Group "Remote Desktop Users" -Member "localuser"

# Verify members
Get-LocalGroupMember -Group "Remote Desktop Users"
```

### Configure RDP Port (Security Hardening)

```powershell
# Change RDP port from default 3389 to custom (e.g., 33890)
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "PortNumber" -Value 33890

# Update firewall rule
New-NetFirewallRule -DisplayName "RDP Custom Port" -Direction Inbound -LocalPort 33890 -Protocol TCP -Action Allow

# Restart RDP service
Restart-Service TermService

# Connect using: mstsc /v:servername:33890
```

### Configure Session Timeout

```powershell
# Set idle session timeout (in milliseconds)
# 30 minutes = 1800000 ms
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "MaxIdleTime" -Value 1800000

# Set disconnected session timeout
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "MaxDisconnectionTime" -Value 1800000
```

### Configure Maximum Connections

```powershell
# Set maximum RDP connections (default: 2 for Workstation, unlimited for Server)
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name "MaxInstanceCount" -Value 5
```

---

## 🛡️ Security Best Practices

### Enable Network Level Authentication (NLA)

```powershell
# Require NLA (recommended for security)
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "UserAuthentication" -Value 1

# Disable NLA (less secure, allows older clients)
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "UserAuthentication" -Value 0
```

### Require Strong Encryption

```powershell
# Set encryption level to High
# 1=Low, 2=Client Compatible, 3=High, 4=FIPS Compliant
Set-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "MinEncryptionLevel" -Value 3
```

### Configure Account Lockout

```powershell
# Set account lockout policy
net accounts /lockoutthreshold:5 /lockoutduration:30 /lockoutwindow:30

# lockoutthreshold: 5 invalid attempts
# lockoutduration: 30 minutes locked
# lockoutwindow: 30 minutes to track attempts
```

### Use RDP Gateway (Recommended for External Access)

1. Install RDP Gateway role on Windows Server
2. Configure SSL certificate
3. Configure Connection Authorization Policies (CAP)
4. Configure Resource Authorization Policies (RAP)

---

## 🔧 Troubleshooting Common RDP Issues

### Issue 1: Cannot Connect - "Remote Desktop Can't Connect"

**Solutions:**

```powershell
# 1. Check if Remote Desktop is enabled
Get-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server' -Name "fDenyTSConnections"
# Should return: 0 (enabled)

# 2. Check RDP service status
Get-Service TermService
# Should be: Running

# 3. Verify firewall rules
Get-NetFirewallRule -DisplayGroup "Remote Desktop" | Where-Object {$_.Enabled -eq "True"}

# 4. Test network connectivity
Test-NetConnection -ComputerName servername -Port 3389

# 5. Check Windows Firewall
netsh advfirewall firewall show rule name="Remote Desktop"
```

### Issue 2: "This computer can't connect to the remote computer"

**Cause:** Network connectivity or firewall issues

```powershell
# Test RDP port connectivity
Test-NetConnection -ComputerName 192.168.1.100 -Port 3389

# If fails, check:
# - Firewall on target computer
# - Network connectivity (ping)
# - Correct IP/hostname
# - VPN connection (if remote)

# Flush DNS cache
ipconfig /flushdns

# Reset network adapter
netsh int ip reset
netsh winsock reset
```

### Issue 3: "Your credentials did not work"

```powershell
# Solutions:

# 1. Verify user is in Remote Desktop Users group
Get-LocalGroupMember -Group "Remote Desktop Users"

# 2. Add user to RDP group
Add-LocalGroupMember -Group "Remote Desktop Users" -Member "username"

# 3. Check account lockout status
net user username | findstr "Locked"

# 4. Unlock account
net user username /active:yes

# 5. Verify NLA setting matches client capability
Get-ItemProperty -Path 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name "UserAuthentication"
```

### Issue 4: "The remote session was disconnected because there are no Remote Desktop client access licenses"

```powershell
# For Windows Server:
# This means RDS licensing is not configured or expired

# Install RDS Licensing role:
Install-WindowsFeature -Name RDS-Licensing -IncludeManagementTools

# Activate license server via Server Manager → Remote Desktop Services

# For Workstation (Windows 10/11):
# Limited to 1 RDP connection at a time
# Use concurrent RDP patcher or upgrade to Server OS
```

### Issue 5: "Remote Desktop Services is currently busy"

```powershell
# Restart Terminal Services
Restart-Service TermService -Force

# If persists, reboot server
# Or kill hung RDP sessions:
qwinsta  # List sessions
logoff [session_id]  # Log off specific session
```

### Issue 6: Black Screen After RDP Connection

**Solutions:**

1. **Disable Bitmap Caching:**
   - RDP connection → Show Options → Experience → Uncheck "Persistent bitmap caching"

2. **Update Display Drivers:**
   ```powershell
   # Update all drivers
   Get-WindowsDriver -Online -All
   ```

3. **Reset RDP Session:**
   ```powershell
   # Kill explorer.exe and restart
   taskkill /f /im explorer.exe
   start explorer.exe
   ```

---

## 📊 Monitor RDP Sessions

### View Active Sessions

```powershell
# List all RDP sessions
query session

# Or using PowerShell
qwinsta

# Output example:
# SESSIONNAME       USERNAME                 ID  STATE   TYPE
# services                                    0  Disc
# console           Administrator             1  Active
# rdp-tcp#1         john.doe                  2  Active
```

### Disconnect Session

```powershell
# Disconnect specific session (keeps programs running)
tsdiscon [session_id]

# Logoff session (closes programs)
logoff [session_id]

# Force disconnect all RDP sessions
qwinsta | findstr "rdp" | ForEach-Object {
    $sessionId = ($_ -split '\\s+')[2]
    logoff $sessionId
}
```

### View RDP Connection Logs

```powershell
# Check RDP connection event logs
Get-EventLog -LogName Microsoft-Windows-TerminalServices-LocalSessionManager/Operational -Newest 50 |
    Where-Object {$_.EventID -in @(21,24,25)} |
    Select-Object TimeGenerated, EventID, Message

# Event IDs:
# 21 = Successful logon
# 24 = Session disconnected
# 25 = Session reconnected
```

---

## 🎯 RDP Performance Optimization

### Optimize RDP Settings for Slow Connections

```powershell
# In RDP client, go to: Experience tab
# Select connection speed: Modem (56 kbps)
# Uncheck:
# - Desktop background
# - Font smoothing
# - Desktop composition
# - Show window contents while dragging
```

### Enable RemoteFX (Windows Server)

```powershell
# Enables advanced graphics and USB redirection
Enable-WindowsOptionalFeature -Online -FeatureName "RemoteFX-Compression"
```

### Adjust Video Quality

```powershell
# Set visual quality mode
# 0=High, 1=Medium, 2=Low
Set-ItemProperty -Path 'HKLM:\\Software\\Policies\\Microsoft\\Windows NT\\Terminal Services' -Name "ColorDepth" -Value 2
```

---

## ✅ RDP Security Checklist

- [ ] Enable Network Level Authentication (NLA)
- [ ] Change RDP port from default 3389
- [ ] Implement account lockout policy
- [ ] Use strong encryption (High or FIPS)
- [ ] Restrict RDP access to specific users/groups
- [ ] Enable RDP connection logging
- [ ] Use RDP Gateway for external connections
- [ ] Implement multi-factor authentication
- [ ] Regular security audits of RDP logs
- [ ] Keep Windows updated with latest patches
- [ ] Use VPN for remote RDP access
- [ ] Disable RDP when not needed
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'Windows Event Viewer and Log Analysis',
            'body': '''# Windows Event Viewer and Log Analysis

## 🎯 Overview
Comprehensive guide to using Event Viewer for troubleshooting, monitoring system health, and security auditing.

---

## 📋 Understanding Event Logs

### Event Log Types

1. **Application Log** - Application events (errors, warnings, information)
2. **Security Log** - Security and audit events (logon, file access)
3. **System Log** - Windows system component events
4. **Setup Log** - Windows setup and update events
5. **Forwarded Events** - Events from remote computers

### Event Levels

- **Critical** 🔴 - Major failure (system crash, service failure)
- **Error** 🔴 - Significant problem (application error, hardware failure)
- **Warning** 🟡 - Not critical but may indicate future problem
- **Information** ⚪ - Successful operation
- **Verbose** 🔵 - Detailed diagnostic info

---

## 🚀 Access Event Viewer

### Using GUI

```powershell
# Launch Event Viewer
eventvwr.msc

# Or from Run (Win + R)
# Type: eventvwr.msc
```

### Using PowerShell

```powershell
# View recent System events
Get-EventLog -LogName System -Newest 50

# View recent Application events
Get-EventLog -LogName Application -Newest 50

# View recent Security events (requires admin)
Get-EventLog -LogName Security -Newest 50
```

---

## 🔍 Common Event IDs to Monitor

### System Critical Events

```powershell
# Event ID 1074 - System restart/shutdown
Get-EventLog -LogName System -InstanceId 1074 -Newest 20

# Event ID 6008 - Unexpected shutdown
Get-EventLog -LogName System -InstanceId 6008 -Newest 20

# Event ID 41 - System rebooted without proper shutdown
Get-WinEvent -FilterHashtable @{LogName='System'; ID=41} -MaxEvents 20

# Event ID 7001 - Service dependency failure
Get-EventLog -LogName System -InstanceId 7001 -Newest 20
```

### Security Events

```powershell
# Event ID 4624 - Successful logon
Get-WinEvent -FilterHashtable @{LogName='Security'; ID=4624} -MaxEvents 20

# Event ID 4625 - Failed logon attempt
Get-WinEvent -FilterHashtable @{LogName='Security'; ID=4625} -MaxEvents 20

# Event ID 4720 - User account created
Get-WinEvent -FilterHashtable @{LogName='Security'; ID=4720} -MaxEvents 20

# Event ID 4740 - User account locked out
Get-WinEvent -FilterHashtable @{LogName='Security'; ID=4740} -MaxEvents 20
```

### Application Events

```powershell
# Event ID 1000 - Application crash
Get-EventLog -LogName Application -InstanceId 1000 -Newest 20

# Event ID 1002 - Application hang
Get-EventLog -LogName Application -InstanceId 1002 -Newest 20
```

### Disk Events

```powershell
# Event ID 7 - Bad block on disk
Get-WinEvent -FilterHashtable @{LogName='System'; ID=7; ProviderName='Disk'} -MaxEvents 20

# Event ID 11 - Disk controller error
Get-WinEvent -FilterHashtable @{LogName='System'; ID=11} -MaxEvents 20
```

---

## 📊 Advanced Event Log Queries

### Filter by Time Range

```powershell
# Events from last 24 hours
$startTime = (Get-Date).AddHours(-24)
Get-WinEvent -FilterHashtable @{
    LogName='System'
    Level=2,3  # Error and Warning
    StartTime=$startTime
}

# Events between specific dates
$start = Get-Date "2024-01-01 00:00:00"
$end = Get-Date "2024-01-31 23:59:59"
Get-WinEvent -FilterHashtable @{
    LogName='System'
    StartTime=$start
    EndTime=$end
}
```

### Filter by Event Source

```powershell
# Events from specific provider
Get-WinEvent -FilterHashtable @{
    LogName='System'
    ProviderName='Microsoft-Windows-Kernel-Power'
}

# Disk-related events
Get-WinEvent -FilterHashtable @{
    LogName='System'
    ProviderName='Disk'
} | Select-Object TimeCreated, Id, Message
```

### Search Event Message Content

```powershell
# Search for specific text in messages
Get-WinEvent -FilterHashtable @{LogName='System'} |
    Where-Object {$_.Message -like "*error*"} |
    Select-Object TimeCreated, Id, Message |
    Format-Table -AutoSize
```

### Export Events to CSV

```powershell
# Export System errors to CSV
Get-WinEvent -FilterHashtable @{
    LogName='System'
    Level=2  # Error only
} -MaxEvents 1000 |
    Select-Object TimeCreated, Id, LevelDisplayName, Message |
    Export-Csv -Path "C:\\Logs\\SystemErrors.csv" -NoTypeInformation

# Export Security logon failures
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4625
} -MaxEvents 500 |
    Export-Csv -Path "C:\\Logs\\FailedLogons.csv" -NoTypeInformation
```

---

## 🔧 Troubleshooting Common Issues

### Investigate Blue Screen of Death (BSOD)

```powershell
# Check for system crashes (Event ID 1001)
Get-WinEvent -FilterHashtable @{
    LogName='System'
    ProviderName='Microsoft-Windows-WER-SystemErrorReporting'
    ID=1001
} | Select-Object TimeCreated, Message | Format-List

# Check minidump files
Get-ChildItem "C:\\Windows\\Minidump" | Sort-Object LastWriteTime -Descending

# Analyze with WinDbg or WhoCrashed (free tool)
```

### Investigate Application Crashes

```powershell
# Find application crashes (Event ID 1000)
Get-WinEvent -FilterHashtable @{
    LogName='Application'
    ProviderName='Application Error'
    ID=1000
} -MaxEvents 50 |
    Select-Object TimeCreated, Message |
    Format-List

# Find faulting module
Get-WinEvent -FilterHashtable @{
    LogName='Application'
    ID=1000
} | ForEach-Object {
    $xml = [xml]$_.ToXml()
    [PSCustomObject]@{
        Time = $_.TimeCreated
        Application = $xml.Event.EventData.Data[0].'#text'
        FaultingModule = $xml.Event.EventData.Data[3].'#text'
    }
} | Format-Table -AutoSize
```

### Investigate Slow Boot/Startup

```powershell
# Check boot performance
Get-WinEvent -FilterHashtable @{
    LogName='System'
    ProviderName='Microsoft-Windows-Diagnostics-Performance'
    ID=100
} -MaxEvents 10 | Select-Object TimeCreated, Message

# Startup duration (in milliseconds)
Get-WinEvent -FilterHashtable @{
    LogName='System'
    ID=100
} | ForEach-Object {
    $xml = [xml]$_.ToXml()
    [PSCustomObject]@{
        Time = $_.TimeCreated
        'Boot Duration (sec)' = [int]$xml.Event.EventData.Data[1].'#text' / 1000
    }
} | Format-Table -AutoSize
```

### Investigate Disk Errors

```powershell
# Check for disk errors
Get-WinEvent -FilterHashtable @{
    LogName='System'
    ProviderName='Disk'
} | Where-Object {$_.Level -le 3} |
    Select-Object TimeCreated, Id, LevelDisplayName, Message |
    Format-Table -Wrap

# Check SMART status
wmic diskdrive get status,model,serialnumber
```

### Track Account Lockouts

```powershell
# Find account lockout events (Event ID 4740)
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4740
} -MaxEvents 50 | ForEach-Object {
    $xml = [xml]$_.ToXml()
    [PSCustomObject]@{
        Time = $_.TimeCreated
        TargetAccount = $xml.Event.EventData.Data[0].'#text'
        CallerComputer = $xml.Event.EventData.Data[1].'#text'
    }
} | Format-Table -AutoSize

# Find where bad password attempts originated
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4625
} -MaxEvents 100 | ForEach-Object {
    $xml = [xml]$_.ToXml()
    [PSCustomObject]@{
        Time = $_.TimeCreated
        Account = $xml.Event.EventData.Data[5].'#text'
        Workstation = $xml.Event.EventData.Data[13].'#text'
        SourceIP = $xml.Event.EventData.Data[19].'#text'
    }
} | Group-Object SourceIP | Sort-Object Count -Descending
```

---

## 🛡️ Security Monitoring

### Monitor Administrative Activity

```powershell
# Track elevation of privileges (UAC prompts)
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4672  # Special privileges assigned
} -MaxEvents 50

# Track group membership changes
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4728,4729,4732,4733  # Member added/removed from groups
} -MaxEvents 50
```

### Monitor File Access (Requires Auditing Enabled)

```powershell
# Enable file auditing (requires admin)
# Computer Configuration → Windows Settings → Security Settings → Advanced Audit Policy
# → Object Access → Audit File System (Success, Failure)

# View file access events
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4663  # File accessed
} -MaxEvents 100 | Select-Object TimeCreated, Message
```

### Monitor Logon/Logoff Activity

```powershell
# Successful logons with details
Get-WinEvent -FilterHashtable @{
    LogName='Security'
    ID=4624
} -MaxEvents 50 | ForEach-Object {
    $xml = [xml]$_.ToXml()
    [PSCustomObject]@{
        Time = $_.TimeCreated
        User = $xml.Event.EventData.Data[5].'#text'
        LogonType = $xml.Event.EventData.Data[8].'#text'
        SourceIP = $xml.Event.EventData.Data[18].'#text'
    }
} | Format-Table -AutoSize

# Logon Type Codes:
# 2 = Interactive (local logon)
# 3 = Network (file share access)
# 4 = Batch (scheduled task)
# 5 = Service
# 7 = Unlock
# 10 = Remote Desktop
# 11 = Cached credentials
```

---

## 📋 Event Log Management

### Configure Event Log Size

```powershell
# Increase maximum log size (in bytes)
Limit-EventLog -LogName System -MaximumSize 512MB
Limit-EventLog -LogName Application -MaximumSize 512MB
Limit-EventLog -LogName Security -MaximumSize 1GB

# Set retention policy
# OverwriteAsNeeded, OverwriteOlder, DoNotOverwrite
Limit-EventLog -LogName System -OverflowAction OverwriteAsNeeded
```

### Clear Event Logs

```powershell
# Clear specific log
Clear-EventLog -LogName System

# Clear all logs (use with caution)
Get-EventLog -List | ForEach-Object {Clear-EventLog $_.Log}

# Backup before clearing
$backupPath = "C:\\EventLogBackups\\System_$(Get-Date -Format 'yyyyMMdd_HHmmss').evtx"
wevtutil export-log System $backupPath
Clear-EventLog -LogName System
```

### Archive Event Logs

```powershell
# Export to .evtx format
$date = Get-Date -Format "yyyyMMdd"
wevtutil export-log System "C:\\Logs\\System_$date.evtx"
wevtutil export-log Application "C:\\Logs\\Application_$date.evtx"
wevtutil export-log Security "C:\\Logs\\Security_$date.evtx"
```

---

## 🔔 Create Custom Event Log Views

### Create Filtered View in Event Viewer

1. Open Event Viewer
2. Right-click "Custom Views" → "Create Custom View"
3. Filter by:
   - Log: System, Application, Security
   - Event level: Critical, Error, Warning
   - Event IDs: Enter specific IDs
   - Time range: Last 24 hours
4. Save with descriptive name (e.g., "Critical System Errors")

### PowerShell Custom Query

```powershell
# Create reusable query for critical issues
$query = @'
<QueryList>
  <Query Id="0" Path="System">
    <Select Path="System">*[System[(Level=1 or Level=2)]]</Select>
  </Query>
  <Query Id="1" Path="Application">
    <Select Path="Application">*[System[(Level=1 or Level=2)]]</Select>
  </Query>
</QueryList>
'@

Get-WinEvent -FilterXml $query -MaxEvents 100 |
    Select-Object TimeCreated, LogName, LevelDisplayName, Id, Message |
    Format-Table -AutoSize
```

---

## ✅ Event Log Best Practices

### Daily Monitoring:
- [ ] Check for Critical and Error events
- [ ] Review Security log for failed logon attempts
- [ ] Monitor disk-related warnings
- [ ] Check for unexpected reboots

### Weekly Tasks:
- [ ] Review all Warning events
- [ ] Export logs to CSV for analysis
- [ ] Check log file sizes
- [ ] Archive old logs

### Monthly Tasks:
- [ ] Generate security audit report
- [ ] Review custom views and queries
- [ ] Update log retention policies
- [ ] Test log forwarding (if configured)

### Security Auditing:
- [ ] Enable audit policies for sensitive resources
- [ ] Monitor privilege escalation events
- [ ] Track administrative account usage
- [ ] Review account lockout patterns
- [ ] Monitor after-hours logon activity
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'Task Scheduler Advanced Usage and Automation',
            'body': '''# Task Scheduler Advanced Usage

## 🎯 Overview
Master Windows Task Scheduler for automating administrative tasks, running scripts, and scheduling maintenance activities.

---

## 📋 Task Scheduler Basics

### Launch Task Scheduler

```powershell
# Open Task Scheduler GUI
taskschd.msc

# Or via PowerShell
Start-Process taskschd.msc
```

### Task Components

- **Trigger** - When the task runs (time, event, logon, etc.)
- **Action** - What the task does (run program, send email, show message)
- **Conditions** - Additional requirements (AC power, network, idle)
- **Settings** - Task behavior options (restart on failure, stop if runs too long)

---

## 🚀 Create Scheduled Tasks

### Method 1: Using GUI

1. **Open Task Scheduler** (taskschd.msc)
2. **Right-click "Task Scheduler Library"** → Create Task
3. **General Tab:**
   - Name: "Daily Backup Script"
   - Description: "Runs backup script daily"
   - Security options: Run whether user is logged on or not
   - Run with highest privileges (if needed)
4. **Triggers Tab:** Add trigger (Daily at 2:00 AM)
5. **Actions Tab:** Start a program (C:\\Scripts\\backup.ps1)
6. **Conditions/Settings:** Configure as needed

### Method 2: Using PowerShell

```powershell
# Create simple scheduled task
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-File C:\\Scripts\\backup.ps1'
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "Daily Backup" -Action $action -Trigger $trigger -Principal $principal -Description "Runs backup script daily at 2 AM"
```

### Method 3: Using SCHTASKS Command

```cmd
REM Create task to run script daily at 2 AM
schtasks /create /tn "Daily Backup" /tr "powershell.exe -File C:\\Scripts\\backup.ps1" /sc daily /st 02:00 /ru SYSTEM /rl HIGHEST

REM Explanation:
REM /tn = Task Name
REM /tr = Task Run (program to execute)
REM /sc = Schedule type (daily, weekly, monthly, once, onstart, onlogon, onidle)
REM /st = Start Time
REM /ru = Run As user
REM /rl = Run Level (HIGHEST or LIMITED)
```

---

## 📅 Trigger Types and Examples

### 1. Time-Based Triggers

```powershell
# Daily at specific time
$trigger = New-ScheduledTaskTrigger -Daily -At "3:00 AM"

# Weekly on specific days
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Wednesday,Friday -At "6:00 PM"

# Monthly on specific day
$trigger = New-ScheduledTaskTrigger -Monthly -DayOfMonth 1 -At "12:00 AM"

# Once at specific date/time
$trigger = New-ScheduledTaskTrigger -Once -At "2024-12-31 23:59:59"

# Every 15 minutes (using repetition)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration ([TimeSpan]::MaxValue)
```

### 2. Event-Based Triggers

```powershell
# Run on system startup
$trigger = New-ScheduledTaskTrigger -AtStartup

# Run on user logon
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Run when system becomes idle
$trigger = New-ScheduledTaskTrigger -AtIdle

# Run on specific event log entry
# Example: Run when Event ID 1074 (system shutdown) occurs
$trigger = New-ScheduledTaskTrigger -AtEvent -LogName "System" -EventID 1074
```

### 3. Advanced Event Trigger (XML)

```powershell
# Create task triggered by specific Windows Event
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-File C:\\Scripts\\alert.ps1'

# Trigger on failed logon attempt (Event ID 4625)
$triggerXml = @"
<QueryList>
  <Query Id="0" Path="Security">
    <Select Path="Security">*[System[(EventID=4625)]]</Select>
  </Query>
</QueryList>
"@

$trigger = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$trigger.Subscription = $triggerXml
$trigger.Enabled = $true

Register-ScheduledTask -TaskName "Alert on Failed Logon" -Action $action -Trigger $trigger
```

---

## 🔧 Action Types

### 1. Start a Program

```powershell
# Run PowerShell script
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-ExecutionPolicy Bypass -File C:\\Scripts\\maintenance.ps1'

# Run batch file
$action = New-ScheduledTaskAction -Execute 'C:\\Scripts\\backup.bat'

# Run executable with arguments
$action = New-ScheduledTaskAction -Execute 'C:\\Program Files\\Backup\\backup.exe' -Argument '-full -log'

# Set working directory
$action = New-ScheduledTaskAction -Execute 'backup.exe' -WorkingDirectory 'C:\\Backup'
```

### 2. Send Email (Deprecated in newer Windows versions)

```powershell
# Note: Email action deprecated in Windows Server 2016+
# Alternative: Use PowerShell script to send email

# Example PowerShell email script:
$emailParams = @{
    From = 'alerts@company.com'
    To = 'admin@company.com'
    Subject = 'Backup Completed'
    Body = 'Daily backup completed successfully'
    SmtpServer = 'smtp.company.com'
}
Send-MailMessage @emailParams
```

### 3. Display Message (Deprecated)

```powershell
# Note: Message action deprecated in Windows 8+
# Alternative: Use PowerShell to show message box

# Example PowerShell message box:
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show('Backup completed!', 'Backup Status')
```

---

## ⚙️ Task Configuration Options

### Security Context

```powershell
# Run as SYSTEM account (highest privileges)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Run as specific user (interactive)
$principal = New-ScheduledTaskPrincipal -UserId "DOMAIN\\username" -LogonType Interactive

# Run as specific user (password stored)
$principal = New-ScheduledTaskPrincipal -UserId "DOMAIN\\username" -LogonType Password -RunLevel Limited

# Run as user who is currently logged on
$principal = New-ScheduledTaskPrincipal -UserId "Users" -GroupId -LogonType Interactive
```

### Task Settings

```powershell
# Configure task settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# Register task with settings
Register-ScheduledTask -TaskName "Backup Task" -Action $action -Trigger $trigger -Settings $settings
```

### Conditions

```powershell
# Create task with conditions
$settings = New-ScheduledTaskSettingsSet
$settings.IdleSettings.IdleDuration = "PT10M"  # 10 minutes idle
$settings.IdleSettings.StopOnIdleEnd = $false
$settings.RunOnlyIfNetworkAvailable = $true
$settings.WakeToRun = $true  # Wake computer to run task

Register-ScheduledTask -TaskName "Idle Maintenance" -Action $action -Trigger $trigger -Settings $settings
```

---

## 📊 Manage Scheduled Tasks

### View Tasks

```powershell
# List all scheduled tasks
Get-ScheduledTask

# View specific task
Get-ScheduledTask -TaskName "Daily Backup"

# View tasks in specific folder
Get-ScheduledTask -TaskPath "\\Microsoft\\Windows\\WindowsUpdate\\"

# Export task list to CSV
Get-ScheduledTask | Select-Object TaskName, State, TaskPath |
    Export-Csv -Path "C:\\Tasks.csv" -NoTypeInformation
```

### Run Task Manually

```powershell
# Start task immediately
Start-ScheduledTask -TaskName "Daily Backup"

# Using SCHTASKS
schtasks /run /tn "Daily Backup"
```

### Enable/Disable Task

```powershell
# Disable task
Disable-ScheduledTask -TaskName "Daily Backup"

# Enable task
Enable-ScheduledTask -TaskName "Daily Backup"

# Using SCHTASKS
schtasks /change /tn "Daily Backup" /disable
schtasks /change /tn "Daily Backup" /enable
```

### Delete Task

```powershell
# Remove task
Unregister-ScheduledTask -TaskName "Daily Backup" -Confirm:$false

# Using SCHTASKS
schtasks /delete /tn "Daily Backup" /f
```

### Export/Import Tasks

```powershell
# Export task to XML
Export-ScheduledTask -TaskName "Daily Backup" | Out-File "C:\\Backup\\DailyBackup.xml"

# Import task from XML
Register-ScheduledTask -Xml (Get-Content "C:\\Backup\\DailyBackup.xml" | Out-String) -TaskName "Daily Backup"

# Using SCHTASKS
schtasks /query /tn "Daily Backup" /xml > C:\\DailyBackup.xml
schtasks /create /tn "Daily Backup Import" /xml C:\\DailyBackup.xml
```

---

## 🎯 Real-World Task Examples

### Example 1: Daily Disk Cleanup

```powershell
# Create disk cleanup task
$action = New-ScheduledTaskAction -Execute 'cleanmgr.exe' -Argument '/sagerun:1'
$trigger = New-ScheduledTaskTrigger -Daily -At "3:00 AM"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable $false

Register-ScheduledTask -TaskName "Daily Disk Cleanup" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
```

### Example 2: Reboot Server Monthly

```powershell
# Schedule server reboot on 1st of each month at 2 AM
schtasks /create /tn "Monthly Reboot" /tr "shutdown.exe /r /f /t 60 /c \\"Scheduled monthly reboot\\"" /sc monthly /d 1 /st 02:00 /ru SYSTEM /rl HIGHEST
```

### Example 3: Monitor Disk Space

```powershell
# Create PowerShell script: C:\\Scripts\\check-diskspace.ps1
$script = @'
$threshold = 20  # 20% free space
$drive = Get-PSDrive C
$percentFree = ($drive.Free / $drive.Used) * 100

if ($percentFree -lt $threshold) {
    # Send email alert
    Send-MailMessage -To 'admin@company.com' -From 'server@company.com' -Subject "Low Disk Space Alert" -Body "Drive C: has only $([math]::Round($percentFree, 2))% free space" -SmtpServer 'smtp.company.com'
}
'@
$script | Out-File -FilePath "C:\\Scripts\\check-diskspace.ps1"

# Schedule to run every 4 hours
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-ExecutionPolicy Bypass -File C:\\Scripts\\check-diskspace.ps1'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration ([TimeSpan]::MaxValue)

Register-ScheduledTask -TaskName "Disk Space Monitor" -Action $action -Trigger $trigger -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount)
```

### Example 4: Backup Event Logs Weekly

```powershell
# Create backup script: C:\\Scripts\\backup-eventlogs.ps1
$script = @'
$date = Get-Date -Format "yyyyMMdd"
$backupPath = "C:\\EventLogBackups"

if (!(Test-Path $backupPath)) {
    New-Item -Path $backupPath -ItemType Directory
}

wevtutil export-log System "$backupPath\\System_$date.evtx"
wevtutil export-log Application "$backupPath\\Application_$date.evtx"
wevtutil export-log Security "$backupPath\\Security_$date.evtx"

# Delete backups older than 90 days
Get-ChildItem $backupPath -Filter *.evtx |
    Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-90)} |
    Remove-Item -Force
'@
$script | Out-File -FilePath "C:\\Scripts\\backup-eventlogs.ps1"

# Schedule weekly on Sunday at 1 AM
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-ExecutionPolicy Bypass -File C:\\Scripts\\backup-eventlogs.ps1'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "1:00 AM"

Register-ScheduledTask -TaskName "Weekly Event Log Backup" -Action $action -Trigger $trigger -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest)
```

---

## 🔧 Troubleshooting Scheduled Tasks

### View Task History

```powershell
# Enable task history (if disabled)
# Task Scheduler → Actions → Enable All Tasks History

# View task execution history
Get-ScheduledTaskInfo -TaskName "Daily Backup" |
    Select-Object LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns

# Check Event Viewer for task execution
Get-WinEvent -FilterHashtable @{
    LogName='Microsoft-Windows-TaskScheduler/Operational'
    ID=200,201  # 200=Action started, 201=Action completed
} -MaxEvents 50 | Select-Object TimeCreated, Id, Message
```

### Common Task Result Codes

- **0x0** - Task completed successfully
- **0x1** - Incorrect function called or unknown function called
- **0x41301** - Task is currently running
- **0x41303** - Task has not yet run
- **0x41325** - Task ready to run at next scheduled time
- **0x8004130F** - Task was terminated by user or disabled
- **0x800710E0** - No logon session (user not logged in)

### Debug Task Execution

```powershell
# Run task with logging
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-ExecutionPolicy Bypass -File C:\\Scripts\\task.ps1 *> C:\\Logs\\task.log'

# Or add logging to PowerShell script:
Start-Transcript -Path "C:\\Logs\\task_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
# ... script content ...
Stop-Transcript
```

### Fix: Task Runs But Nothing Happens

**Common causes:**
1. **Permissions** - Task needs "Run with highest privileges"
2. **Working Directory** - Specify working directory in action
3. **User Context** - Use SYSTEM account or verify user has access
4. **Hidden Scripts** - PowerShell execution policy or script hidden

```powershell
# Fix execution policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine

# Run with full path and bypass policy
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File C:\\Scripts\\script.ps1'
```

---

## ✅ Best Practices

### Security:
- [ ] Use least privilege principle (don't always use SYSTEM)
- [ ] Store credentials securely (use managed service accounts)
- [ ] Enable task history for auditing
- [ ] Review tasks regularly for unused/old tasks
- [ ] Use specific paths (don't rely on PATH variable)

### Reliability:
- [ ] Set execution time limit (prevent runaway tasks)
- [ ] Configure restart on failure
- [ ] Use StartWhenAvailable for missed runs
- [ ] Implement logging in scripts
- [ ] Test tasks manually before scheduling

### Maintenance:
- [ ] Document each task's purpose
- [ ] Use consistent naming convention
- [ ] Organize tasks in folders
- [ ] Export critical tasks as backup
- [ ] Review task results weekly
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'Windows Service Management and Troubleshooting',
            'body': '''# Windows Service Management

## 🎯 Overview
Complete guide to managing Windows services, troubleshooting service failures, and configuring service dependencies.

---

## 📋 Understanding Windows Services

### Service States

- **Running** - Service is currently active
- **Stopped** - Service is not running
- **Paused** - Service temporarily suspended (not all services support)
- **Starting/Stopping** - Service transitioning between states

### Startup Types

- **Automatic** - Starts at system boot
- **Automatic (Delayed Start)** - Starts shortly after boot (reduces boot time)
- **Manual** - Started manually or by dependent service
- **Disabled** - Cannot be started

---

## 🚀 Manage Services via GUI

### Services Console (services.msc)

```powershell
# Open Services console
services.msc

# Or from PowerShell
Start-Process services.msc
```

**Common Actions:**
1. Right-click service → **Start/Stop/Restart/Pause**
2. Double-click service → **Properties**
3. General tab → Change **Startup type**
4. Log On tab → Change service account
5. Recovery tab → Configure failure actions

---

## 🔧 Manage Services via PowerShell

### View Services

```powershell
# List all services
Get-Service

# List running services
Get-Service | Where-Object {$_.Status -eq "Running"}

# List stopped services
Get-Service | Where-Object {$_.Status -eq "Stopped"}

# Search for specific service
Get-Service | Where-Object {$_.DisplayName -like "*Windows Update*"}

# View detailed service info
Get-Service -Name wuauserv | Select-Object *

# Export service list to CSV
Get-Service | Select-Object Name, DisplayName, Status, StartType |
    Export-Csv -Path "C:\\Services.csv" -NoTypeInformation
```

### Start/Stop Services

```powershell
# Start service
Start-Service -Name "wuauserv"

# Stop service
Stop-Service -Name "wuauserv" -Force

# Restart service
Restart-Service -Name "wuauserv"

# Pause service (if supported)
Suspend-Service -Name "wuauserv"

# Resume paused service
Resume-Service -Name "wuauserv"

# Multiple services at once
Start-Service -Name "wuauserv","BITS","CryptSvc"
```

### Change Startup Type

```powershell
# Set to Automatic
Set-Service -Name "wuauserv" -StartupType Automatic

# Set to Automatic (Delayed Start)
Set-Service -Name "wuauserv" -StartupType AutomaticDelayedStart

# Set to Manual
Set-Service -Name "wuauserv" -StartupType Manual

# Disable service
Set-Service -Name "wuauserv" -StartupType Disabled
```

### Change Service Account

```powershell
# Change to Local System
Set-Service -Name "MyService" -Credential (New-Object System.Management.Automation.PSCredential("NT AUTHORITY\\SYSTEM", (New-Object System.Security.SecureString)))

# Change to specific user (prompts for password)
$cred = Get-Credential -UserName "DOMAIN\\ServiceAccount"
Set-Service -Name "MyService" -Credential $cred

# Or using SC command
sc.exe config "MyService" obj= "DOMAIN\\ServiceAccount" password= "Password123"
```

---

## 💻 Manage Services via Command Line (SC)

### View Services

```cmd
REM List all services
sc query

REM Query specific service
sc query wuauserv

REM Query service configuration
sc qc wuauserv

REM Query service failure actions
sc qfailure wuauserv
```

### Start/Stop Services

```cmd
REM Start service
sc start wuauserv

REM Stop service
sc stop wuauserv

REM Pause service
sc pause wuauserv

REM Continue service
sc continue wuauserv
```

### Configure Services

```cmd
REM Change startup type to Automatic
sc config wuauserv start= auto

REM Change to Automatic (Delayed Start)
sc config wuauserv start= delayed-auto

REM Change to Manual
sc config wuauserv start= demand

REM Disable service
sc config wuauserv start= disabled

REM Change service description
sc description wuauserv "Windows Update service manages updates"

REM Change service display name
sc config wuauserv displayname= "Windows Update Service"
```

### Create New Service

```cmd
REM Create new service
sc create "MyService" binPath= "C:\\Path\\To\\Service.exe" start= auto

REM With display name and description
sc create "MyService" binPath= "C:\\Path\\To\\Service.exe" start= auto displayname= "My Custom Service" obj= "NT AUTHORITY\\LocalService"

REM Delete service
sc delete "MyService"
```

---

## 🔍 Troubleshooting Service Issues

### Issue 1: Service Won't Start

**Error: "Windows could not start the [Service] service on Local Computer. Error 1053: The service did not respond in a timely fashion."**

**Solutions:**

```powershell
# 1. Increase service timeout
Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control" -Name "ServicesPipeTimeout" -Value 180000 -Type DWord

# 2. Check service dependencies
sc enumdepend wuauserv

# 3. Start dependent services first
$service = Get-Service -Name "wuauserv"
$service.ServicesDependedOn | ForEach-Object {
    Start-Service -Name $_.Name
}

# 4. Check Event Viewer for errors
Get-EventLog -LogName System -Source "Service Control Manager" -Newest 50 |
    Where-Object {$_.EntryType -eq "Error"} |
    Select-Object TimeGenerated, Message

# 5. Verify service account permissions
# Services → Right-click service → Properties → Log On → Verify account has permissions

# 6. Repair service registration
sc delete wuauserv
# Reinstall service or run: DISM /Online /Cleanup-Image /RestoreHealth
```

### Issue 2: Service Crashes or Stops Unexpectedly

```powershell
# Check service failure history
Get-EventLog -LogName System -Source "Service Control Manager" -EntryType Error -Newest 100

# Configure recovery actions
sc failure wuauserv reset= 86400 actions= restart/60000/restart/60000/reboot/60000

# Explanation:
# reset= 86400 (reset failure count after 24 hours)
# actions= restart/60000 (restart service after 60 seconds on first failure)
# restart/60000 (restart again after 60 seconds on second failure)
# reboot/60000 (reboot computer after 60 seconds on third failure)

# View recovery settings
sc qfailure wuauserv
```

### Issue 3: Service Disabled by Policy or Malware

```powershell
# Check if service is disabled
Get-Service -Name "wuauserv" | Select-Object StartType

# Re-enable service
Set-Service -Name "wuauserv" -StartupType Automatic

# If registry is locked, check GPO
# gpedit.msc → Computer Configuration → Windows Settings → Security Settings → System Services

# Check for registry locks
Get-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\wuauserv" -Name "Start"

# Force change registry value
Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\wuauserv" -Name "Start" -Value 2 -Force
# Start values: 0=Boot, 1=System, 2=Automatic, 3=Manual, 4=Disabled
```

### Issue 4: Service Stuck in "Starting" or "Stopping" State

```powershell
# Kill service process forcefully
$service = Get-WmiObject -Class Win32_Service -Filter "Name='wuauserv'"
$processId = $service.ProcessId

if ($processId -gt 0) {
    Stop-Process -Id $processId -Force
}

# Or find and kill by service name
taskkill /F /FI "SERVICES eq wuauserv"

# Restart service
Start-Service -Name "wuauserv"
```

---

## 🔐 Service Security Best Practices

### Use Least Privilege Accounts

```powershell
# Built-in service accounts (preferred):
# - LocalService (NT AUTHORITY\\LocalService) - Limited privileges, network identity is anonymous
# - NetworkService (NT AUTHORITY\\NetworkService) - Limited privileges, can access network
# - LocalSystem (NT AUTHORITY\\SYSTEM) - Full admin rights (use only if necessary)

# Create Managed Service Account (recommended for domain)
# On Domain Controller:
New-ADServiceAccount -Name "MyServiceMSA" -DNSHostName "server.domain.com" -PrincipalsAllowedToRetrieveManagedPassword "SERVER$"

# On server, install MSA:
Install-ADServiceAccount -Identity "MyServiceMSA"

# Configure service to use MSA:
sc.exe config "MyService" obj= "DOMAIN\\MyServiceMSA$" password= ""
```

### Configure Service Permissions

```powershell
# Grant user permission to start/stop service
# Download SubInACL tool from Microsoft
# Or use built-in sc command:

sc sdshow wuauserv  # View current security descriptor

# Grant user "Start" and "Stop" permissions
# Requires editing SDDL string (complex, use GUI instead)
# Services → Right-click → Properties → Security tab (in some Windows versions)
```

### Audit Service Changes

```powershell
# Enable service auditing
auditpol /set /subcategory:"Security System Extension" /success:enable /failure:enable

# View service-related events
Get-EventLog -LogName Security -InstanceId 4697 -Newest 50  # Service installed
Get-EventLog -LogName System -Source "Service Control Manager" -Newest 50
```

---

## 📊 Monitor Services

### Check Service Status Remotely

```powershell
# Get services from remote computer
Get-Service -ComputerName "SERVER01"

# Check specific service on remote computer
Get-Service -Name "wuauserv" -ComputerName "SERVER01"

# Start service on remote computer
Get-Service -Name "wuauserv" -ComputerName "SERVER01" | Start-Service

# Multiple computers
$computers = "SERVER01","SERVER02","SERVER03"
foreach ($computer in $computers) {
    Get-Service -Name "wuauserv" -ComputerName $computer |
        Select-Object @{N='Computer';E={$computer}}, Name, Status
}
```

### Monitor Critical Services

```powershell
# Create monitoring script
$criticalServices = @("wuauserv","BITS","EventLog","Dhcp","DNS","W32Time")

foreach ($service in $criticalServices) {
    $svc = Get-Service -Name $service -ErrorAction SilentlyContinue
    if ($svc.Status -ne "Running") {
        Write-Host "ALERT: $service is $($svc.Status)" -ForegroundColor Red
        Start-Service -Name $service

        # Send email alert
        Send-MailMessage -To 'admin@company.com' -From 'monitor@company.com' `
            -Subject "Service Alert: $service stopped" `
            -Body "$service was found stopped and has been restarted" `
            -SmtpServer 'smtp.company.com'
    }
}
```

### Create Service Monitor Task

```powershell
# Schedule service monitoring every 5 minutes
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument '-ExecutionPolicy Bypass -File C:\\Scripts\\monitor-services.ps1'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)

Register-ScheduledTask -TaskName "Service Monitor" -Action $action -Trigger $trigger -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest)
```

---

## 🔄 Service Dependencies

### View Service Dependencies

```powershell
# View services this service depends on
$service = Get-Service -Name "wuauserv"
$service.ServicesDependedOn | Select-Object Name, DisplayName, Status

# View services that depend on this service
$service.DependentServices | Select-Object Name, DisplayName, Status

# Using SC command
sc enumdepend wuauserv  # Services that depend on this
sc qc wuauserv  # View dependencies in config
```

### Add/Remove Dependencies

```cmd
REM Add dependency (service will start after dependency)
sc config MyService depend= DependencyService

REM Multiple dependencies
sc config MyService depend= Service1/Service2/Service3

REM Remove all dependencies
sc config MyService depend= /
```

---

## 🎯 Common Service Management Tasks

### Reset Windows Update Services

```powershell
# Complete Windows Update service reset
$services = @("wuauserv","cryptSvc","bits","msiserver")

# Stop services
foreach ($service in $services) {
    Stop-Service -Name $service -Force -ErrorAction SilentlyContinue
}

# Delete temp files
Remove-Item "C:\\Windows\\SoftwareDistribution" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "C:\\Windows\\System32\\catroot2" -Recurse -Force -ErrorAction SilentlyContinue

# Re-register DLLs
$dlls = @("wuapi.dll","wuaueng.dll","wups.dll","wups2.dll","wuwebv.dll","wucltux.dll")
foreach ($dll in $dlls) {
    regsvr32 /s $dll
}

# Start services
foreach ($service in $services) {
    Start-Service -Name $service -ErrorAction SilentlyContinue
}
```

### Export/Import Service Configuration

```powershell
# Export service configuration
$service = Get-WmiObject Win32_Service -Filter "Name='MyService'"
$config = @{
    Name = $service.Name
    DisplayName = $service.DisplayName
    PathName = $service.PathName
    StartMode = $service.StartMode
    ServiceType = $service.ServiceType
    ErrorControl = $service.ErrorControl
    StartName = $service.StartName
}
$config | Export-Clixml -Path "C:\\ServiceBackup\\MyService.xml"

# Import and recreate service
$config = Import-Clixml -Path "C:\\ServiceBackup\\MyService.xml"
sc.exe create $config.Name binPath= $config.PathName start= $config.StartMode obj= $config.StartName
```

---

## ✅ Service Management Checklist

### Daily Monitoring:
- [ ] Check critical service status
- [ ] Review service failure events
- [ ] Verify automatic services are running

### Weekly Tasks:
- [ ] Review service recovery configurations
- [ ] Check for new/unknown services
- [ ] Audit service account permissions

### Monthly Tasks:
- [ ] Review and optimize startup services
- [ ] Document service dependencies
- [ ] Test service recovery procedures
- [ ] Backup service configurations

### Security Auditing:
- [ ] Review services running as SYSTEM
- [ ] Check for services with weak credentials
- [ ] Verify service permissions
- [ ] Disable unnecessary services
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'Registry Management and Best Practices',
            'body': '''# Windows Registry Management

## 🎯 Overview
Complete guide to safely managing Windows Registry, including common modifications, troubleshooting, and security best practices.

---

## ⚠️ WARNING: Registry Safety

**CRITICAL:** Incorrect registry modifications can render Windows unbootable!

**Always:**
- ✅ Backup registry before changes
- ✅ Create System Restore point
- ✅ Test in non-production environment first
- ✅ Document all changes
- ❌ NEVER delete keys unless certain
- ❌ NEVER modify System hive without expertise

---

## 📋 Understanding Registry Structure

### Registry Hives

- **HKEY_LOCAL_MACHINE (HKLM)** - Computer configuration, hardware, software
- **HKEY_CURRENT_USER (HKCU)** - Current user settings and preferences
- **HKEY_USERS (HKU)** - All loaded user profiles
- **HKEY_CLASSES_ROOT (HKCR)** - File associations and COM objects
- **HKEY_CURRENT_CONFIG (HKCC)** - Current hardware profile

### Registry Data Types

- **REG_SZ** - String value
- **REG_DWORD** - 32-bit number (0-4294967295)
- **REG_QWORD** - 64-bit number
- **REG_BINARY** - Binary data
- **REG_MULTI_SZ** - Multiple strings
- **REG_EXPAND_SZ** - String with environment variables

---

## 🚀 Access Registry

### Registry Editor (GUI)

```powershell
# Open Registry Editor
regedit

# Or from Run (Win + R)
# Type: regedit
```

### PowerShell Registry Access

```powershell
# Registry is accessed like a file system via PSDrive

# List registry drives
Get-PSDrive -PSProvider Registry

# Navigate to registry key
Set-Location HKLM:\\SOFTWARE\\Microsoft\\Windows

# List subkeys
Get-ChildItem

# View properties (values)
Get-ItemProperty .
```

---

## 🔧 Backup and Restore Registry

### Backup Entire Registry

```powershell
# Create System Restore point (includes registry)
Checkpoint-Computer -Description "Before Registry Changes" -RestorePointType "MODIFY_SETTINGS"

# Export entire registry (requires admin)
regedit /e "C:\\Backup\\registry_backup_$(Get-Date -Format 'yyyyMMdd').reg"

# Backup specific hive
reg export HKLM\\SOFTWARE\\Microsoft\\Windows "C:\\Backup\\windows_key.reg" /y
```

### Backup Specific Key

```powershell
# Using PowerShell
$key = "HKLM:\\SOFTWARE\\MyApp"
$backupFile = "C:\\Backup\\MyApp.reg"
reg export $key $backupFile /y

# Using Registry Editor:
# 1. Navigate to key
# 2. File → Export
# 3. Select "Selected branch"
# 4. Save as .reg file
```

### Restore Registry

```powershell
# Restore from .reg file
regedit /s "C:\\Backup\\registry_backup.reg"

# Or double-click .reg file (prompts for confirmation)

# Using reg command
reg import "C:\\Backup\\MyApp.reg"

# Restore from System Restore point
# Control Panel → Recovery → Open System Restore
```

---

## 📝 Modify Registry Values

### Using PowerShell

```powershell
# Create new registry key
New-Item -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Force

# Create string value
New-ItemProperty -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Name "Version" -Value "1.0.0" -PropertyType String

# Create DWORD value
New-ItemProperty -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Name "Enabled" -Value 1 -PropertyType DWord

# Modify existing value
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Name "Version" -Value "2.0.0"

# Read value
Get-ItemProperty -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Name "Version"

# Delete value
Remove-ItemProperty -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Name "OldSetting"

# Delete entire key
Remove-Item -Path "HKLM:\\SOFTWARE\\MyCompany\\MyApp" -Recurse
```

### Using REG Command

```cmd
REM Add string value
reg add "HKLM\\SOFTWARE\\MyApp" /v "Version" /t REG_SZ /d "1.0.0" /f

REM Add DWORD value
reg add "HKLM\\SOFTWARE\\MyApp" /v "Enabled" /t REG_DWORD /d 1 /f

REM Query value
reg query "HKLM\\SOFTWARE\\MyApp" /v "Version"

REM Delete value
reg delete "HKLM\\SOFTWARE\\MyApp" /v "OldSetting" /f

REM Delete entire key
reg delete "HKLM\\SOFTWARE\\MyApp" /f
```

---

## 🎯 Common Registry Modifications

### 1. Disable Windows Update Automatic Restart

```powershell
# Prevent automatic restart after updates
$path = "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU"
New-Item -Path $path -Force | Out-Null
Set-ItemProperty -Path $path -Name "NoAutoRebootWithLoggedOnUsers" -Value 1 -Type DWord
Set-ItemProperty -Path $path -Name "AUOptions" -Value 3 -Type DWord  # 3=Download and notify for install
```

### 2. Enable/Disable UAC

```powershell
# Disable UAC (not recommended for security)
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" -Name "EnableLUA" -Value 0 -Type DWord

# Enable UAC
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" -Name "EnableLUA" -Value 1 -Type DWord

# Restart required for changes to take effect
```

### 3. Change Windows Product Key

```powershell
# View current product key partial
(Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion").ProductId

# Change product key (use slmgr instead)
slmgr /ipk XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
slmgr /ato  # Activate
```

### 4. Customize Desktop and UI

```powershell
# Remove Recycle Bin from desktop
$path = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\HideDesktopIcons\\NewStartPanel"
New-Item -Path $path -Force | Out-Null
Set-ItemProperty -Path $path -Name "{645FF040-5081-101B-9F08-00AA002F954E}" -Value 1 -Type DWord

# Disable Aero Shake (minimize windows when shaking one)
Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced" -Name "DisallowShaking" -Value 1 -Type DWord

# Show file extensions
Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced" -Name "HideFileExt" -Value 0 -Type DWord

# Show hidden files
Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced" -Name "Hidden" -Value 1 -Type DWord
```

### 5. Disable Telemetry and Privacy Settings

```powershell
# Disable telemetry (Windows 10 Pro/Enterprise only)
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection" -Name "AllowTelemetry" -Value 0 -Type DWord

# Disable Activity History
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\System" -Name "PublishUserActivities" -Value 0 -Type DWord

# Disable Location Services
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\LocationAndSensors" -Name "DisableLocation" -Value 1 -Type DWord
```

### 6. Increase RDP Concurrent Sessions (Use with caution - licensing!)

```powershell
# Note: This violates Windows licensing for non-Server editions
# For educational/testing purposes only

# Allow multiple RDP sessions on Windows 10/11
$path = "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server"
Set-ItemProperty -Path $path -Name "fSingleSessionPerUser" -Value 0 -Type DWord

# Increase max connections
Set-ItemProperty -Path $path -Name "MaxInstanceCount" -Value 999999 -Type DWord
```

### 7. Customize Context Menu

```powershell
# Add "Take Ownership" to context menu
$commands = @"
Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\\*\\shell\\runas]
@="Take Ownership"
"NoWorkingDirectory"=""

[HKEY_CLASSES_ROOT\\*\\shell\\runas\\command]
@="cmd.exe /c takeown /f \\"%1\\" && icacls \\"%1\\" /grant administrators:F"
"IsolatedCommand"="cmd.exe /c takeown /f \\"%1\\" && icacls \\"%1\\" /grant administrators:F"
"@

$commands | Out-File -FilePath "C:\\temp\\take_ownership.reg" -Encoding ASCII
regedit /s "C:\\temp\\take_ownership.reg"
```

---

## 🔍 Troubleshooting Registry Issues

### Corrupted Registry

```powershell
# Boot into Windows Recovery Environment (WinRE)
# Advanced Options → Command Prompt

# Replace corrupted registry with backup
copy C:\\Windows\\System32\\config\\RegBack\\* C:\\Windows\\System32\\config\\

# Or use DISM to repair
DISM /Online /Cleanup-Image /RestoreHealth

# System File Checker
sfc /scannow
```

### Registry Permissions Issues

```powershell
# Take ownership of registry key
$key = "HKLM:\\SOFTWARE\\RestrictedKey"
$acl = Get-Acl $key

# Set owner to Administrators
$adminGroup = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")
$acl.SetOwner($adminGroup)
Set-Acl -Path $key -AclObject $acl

# Grant full control to Administrators
$rule = New-Object System.Security.AccessControl.RegistryAccessRule(
    "Administrators",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl -Path $key -AclObject $acl
```

### Search Registry for Value

```powershell
# Search for registry value across all hives
function Search-Registry {
    param(
        [string]$SearchTerm,
        [string]$Path = "HKLM:\\SOFTWARE"
    )

    Get-ChildItem -Path $Path -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object {
            $properties = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue
            $properties.PSObject.Properties | Where-Object {
                $_.Value -like "*$SearchTerm*"
            } | ForEach-Object {
                [PSCustomObject]@{
                    Path = $_.PSPath
                    Name = $_.Name
                    Value = $_.Value
                }
            }
        }
}

# Usage
Search-Registry -SearchTerm "MyApp" -Path "HKLM:\\SOFTWARE"
```

---

## 🛡️ Registry Security Best Practices

### 1. Regular Backups

```powershell
# Create automated registry backup script
$backupPath = "C:\\RegistryBackups"
$date = Get-Date -Format "yyyyMMdd"

if (!(Test-Path $backupPath)) {
    New-Item -Path $backupPath -ItemType Directory
}

# Backup critical keys
reg export "HKLM\\SOFTWARE" "$backupPath\\HKLM_SOFTWARE_$date.reg" /y
reg export "HKLM\\SYSTEM" "$backupPath\\HKLM_SYSTEM_$date.reg" /y
reg export "HKCU\\Software" "$backupPath\\HKCU_SOFTWARE_$date.reg" /y

# Delete backups older than 30 days
Get-ChildItem $backupPath -Filter *.reg |
    Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-30)} |
    Remove-Item -Force
```

### 2. Audit Registry Access

```powershell
# Enable registry auditing
auditpol /set /subcategory:"Registry" /success:enable /failure:enable

# View registry audit events
Get-EventLog -LogName Security -InstanceId 4656,4657,4658,4660,4663 -Newest 100 |
    Where-Object {$_.Message -like "*Registry*"} |
    Select-Object TimeGenerated, EventID, Message
```

### 3. Restrict Registry Access

```powershell
# Remove remote registry access for non-admins
Stop-Service -Name "RemoteRegistry"
Set-Service -Name "RemoteRegistry" -StartupType Disabled

# Restrict registry editor access (not recommended for admins)
$path = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System"
New-Item -Path $path -Force | Out-Null
Set-ItemProperty -Path $path -Name "DisableRegistryTools" -Value 1 -Type DWord

# Re-enable (if locked out, use .reg file from another computer)
Set-ItemProperty -Path $path -Name "DisableRegistryTools" -Value 0 -Type DWord
```

---

## 📊 Registry Monitoring

### Monitor Registry Changes

```powershell
# Monitor specific registry key for changes
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = "HKLM:\\SOFTWARE\\MyApp"
$watcher.IncludeSubdirectories = $true
$watcher.EnableRaisingEvents = $true

# Alternative: Use Process Monitor (Sysinternals)
# Download: https://docs.microsoft.com/en-us/sysinternals/downloads/procmon
# Filter: Operation → RegSetValue, RegCreateKey, RegDeleteKey
```

### Compare Registry States

```powershell
# Export current state
reg export "HKLM\\SOFTWARE\\Microsoft\\Windows" "C:\\before.reg" /y

# Make changes...

# Export new state
reg export "HKLM\\SOFTWARE\\Microsoft\\Windows" "C:\\after.reg" /y

# Compare (use diff tool like WinMerge or PowerShell)
$before = Get-Content "C:\\before.reg"
$after = Get-Content "C:\\after.reg"
Compare-Object $before $after
```

---

## ✅ Registry Management Checklist

### Before Making Changes:
- [ ] Backup registry key(s)
- [ ] Create System Restore point
- [ ] Document changes (what, why, when)
- [ ] Test in non-production environment
- [ ] Verify you have undo plan

### After Making Changes:
- [ ] Test system functionality
- [ ] Verify change took effect
- [ ] Monitor for issues (24-48 hours)
- [ ] Update documentation
- [ ] Archive backup files

### Regular Maintenance:
- [ ] Weekly registry backups
- [ ] Monthly registry cleanup (remove obsolete keys)
- [ ] Quarterly security audit
- [ ] Annual full registry backup

### Security:
- [ ] Disable Remote Registry service if not needed
- [ ] Enable registry auditing
- [ ] Restrict registry editor access for standard users
- [ ] Monitor registry changes via event logs
'''
        })

        articles.append({
            'category': 'Windows Administration',
            'title': 'BitLocker Drive Encryption Setup and Management',
            'body': '''# BitLocker Drive Encryption

## 🎯 Overview
Complete guide to enabling, configuring, and managing BitLocker Drive Encryption on Windows for data protection.

---

## 📋 Prerequisites

### System Requirements

- **Windows Edition:** Pro, Enterprise, or Education (not Home)
- **TPM:** Trusted Platform Module 1.2 or 2.0 (recommended)
- **UEFI BIOS** with Secure Boot enabled
- **Hard Drive:** At least 2 partitions (System and OS)
- **Administrator rights**

### Check TPM Status

```powershell
# Check if TPM is present and enabled
Get-Tpm

# Should show:
# TpmPresent: True
# TpmReady: True
# TpmEnabled: True
# TpmActivated: True

# View TPM version
(Get-Tpm).ManufacturerVersion
```

### Check BitLocker Prerequisites

```powershell
# Check if BitLocker is available
Get-WindowsFeature -Name BitLocker

# Check drive encryption status
Get-BitLockerVolume

# Check if drive supports BitLocker
manage-bde -status C:
```

---

## 🔐 Enable BitLocker

### Method 1: Using Control Panel (GUI)

1. **Open BitLocker Settings:**
   - Control Panel → System and Security → BitLocker Drive Encryption

2. **Turn On BitLocker:**
   - Select drive → Turn on BitLocker

3. **Choose Unlock Method:**
   - ✅ Enter a password (recommended for data drives)
   - ✅ Insert a USB flash drive (removed USB unlocks drive)
   - ✅ TPM only (automatic, most secure)
   - ✅ TPM + PIN (balanced security)
   - ✅ TPM + USB + PIN (maximum security)

4. **Backup Recovery Key:**
   - ✅ Save to Microsoft account (recommended)
   - ✅ Save to USB flash drive
   - ✅ Save to file
   - ✅ Print the recovery key

5. **Choose Encryption Mode:**
   - **Encrypt used space only** (faster, for new drives)
   - **Encrypt entire drive** (more secure, for drives with existing data)

6. **Select Encryption Algorithm:**
   - AES 128-bit (faster)
   - AES 256-bit (more secure, recommended)
   - XTS-AES 128-bit (Windows 10 1511+, recommended)
   - XTS-AES 256-bit (highest security)

7. **Start Encryption**

### Method 2: Using PowerShell

```powershell
# Enable BitLocker with password
Enable-BitLocker -MountPoint "C:" -PasswordProtector -Password (Read-Host -AsSecureString "Enter Password")

# Enable BitLocker with TPM
Enable-BitLocker -MountPoint "C:" -TpmProtector

# Enable BitLocker with TPM + PIN
$pin = Read-Host -AsSecureString "Enter PIN"
Enable-BitLocker -MountPoint "C:" -TpmAndPinProtector -Pin $pin

# Enable BitLocker with TPM + USB
Enable-BitLocker -MountPoint "C:" -TpmAndStartupKeyProtector -StartupKeyPath "E:\\"

# Add recovery key protector (backup)
Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector

# Backup recovery key to AD (domain-joined computers)
Backup-BitLockerKeyProtector -MountPoint "C:" -KeyProtectorId (Get-BitLockerVolume -MountPoint "C:").KeyProtector[0].KeyProtectorId
```

### Method 3: Using manage-bde Command

```cmd
REM Enable BitLocker with TPM
manage-bde -on C: -TPM

REM Enable BitLocker with TPM + PIN
manage-bde -on C: -TPMandPIN

REM Enable BitLocker with password
manage-bde -on C: -Password

REM Add recovery key
manage-bde -protectors -add C: -RecoveryPassword

REM Backup recovery key to file
manage-bde -protectors -get C: > "C:\\BitLocker_Recovery_Key.txt"
```

---

## 🔧 Manage BitLocker

### View Encryption Status

```powershell
# View all BitLocker volumes
Get-BitLockerVolume

# View specific drive
Get-BitLockerVolume -MountPoint "C:"

# Check encryption percentage
$volume = Get-BitLockerVolume -MountPoint "C:"
$volume | Select-Object MountPoint, VolumeStatus, EncryptionPercentage, ProtectionStatus

# Using manage-bde
manage-bde -status C:
```

### Pause/Resume Encryption

```powershell
# Pause BitLocker encryption (useful during BIOS updates)
Suspend-BitLocker -MountPoint "C:" -RebootCount 2  # Suspends for 2 reboots

# Resume BitLocker
Resume-BitLocker -MountPoint "C:"

# Using manage-bde
manage-bde -pause C:
manage-bde -resume C:
```

### Unlock Drive

```powershell
# Unlock drive with password
$password = Read-Host -AsSecureString "Enter Password"
Unlock-BitLocker -MountPoint "C:" -Password $password

# Unlock with recovery key
Unlock-BitLocker -MountPoint "C:" -RecoveryPassword "123456-789012-345678-901234-567890-123456-789012-345678"

# Using manage-bde
manage-bde -unlock C: -RecoveryPassword 123456-789012-345678-901234-567890-123456-789012-345678
```

### Change/Add Protectors

```powershell
# Add additional recovery password
Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector

# Change PIN
$newPin = Read-Host -AsSecureString "Enter new PIN"
Change-BitLockerPin -MountPoint "C:" -NewPin $newPin

# Add password protector
$password = Read-Host -AsSecureString "Enter Password"
Add-BitLockerKeyProtector -MountPoint "C:" -PasswordProtector -Password $password

# Remove specific protector
$keyProtectorId = (Get-BitLockerVolume -MountPoint "C:").KeyProtector[0].KeyProtectorId
Remove-BitLockerKeyProtector -MountPoint "C:" -KeyProtectorId $keyProtectorId
```

---

## 📂 Manage Recovery Keys

### Backup Recovery Key

```powershell
# Backup to file
$keyProtector = (Get-BitLockerVolume -MountPoint "C:").KeyProtector | Where-Object {$_.KeyProtectorType -eq "RecoveryPassword"}
$keyProtector.RecoveryPassword | Out-File "C:\\BitLockerRecovery_C.txt"

# Backup to Active Directory (domain-joined)
$keyProtectorId = (Get-BitLockerVolume -MountPoint "C:").KeyProtector[0].KeyProtectorId
Backup-BitLockerKeyProtector -MountPoint "C:" -KeyProtectorId $keyProtectorId

# Using manage-bde
manage-bde -protectors -get C: > "C:\\BitLocker_Recovery.txt"
manage-bde -protectors -adbackup C: -id {KeyProtectorID}
```

### Retrieve Recovery Key

```powershell
# View recovery keys
$volume = Get-BitLockerVolume -MountPoint "C:"
$volume.KeyProtector | Where-Object {$_.KeyProtectorType -eq "RecoveryPassword"} |
    Select-Object KeyProtectorType, RecoveryPassword

# From Active Directory (requires AD PowerShell module)
Get-ADObject -Filter {objectClass -eq 'msFVE-RecoveryInformation'} -SearchBase "CN=Computer1,OU=Computers,DC=domain,DC=com" -Properties msFVE-RecoveryPassword |
    Select-Object Name, msFVE-RecoveryPassword
```

### Use Recovery Key

**When needed:**
- Forgot PIN or password
- TPM changes detected (BIOS update, motherboard replacement)
- Drive moved to another computer
- System files corrupted

**How to use:**
1. Boot computer → BitLocker recovery screen appears
2. Press ESC for recovery options
3. Enter 48-digit recovery key
4. System unlocks and boots

---

## 🔐 BitLocker To Go (Removable Drives)

### Encrypt USB/External Drive

```powershell
# Encrypt removable drive with password
$password = Read-Host -AsSecureString "Enter Password"
Enable-BitLocker -MountPoint "E:" -PasswordProtector -Password $password

# Add recovery key
Add-BitLockerKeyProtector -MountPoint "E:" -RecoveryPasswordProtector

# Using Control Panel:
# Right-click drive → Turn on BitLocker → Set password
```

### Auto-Unlock BitLocker To Go

```powershell
# Enable auto-unlock for removable drive (on current PC only)
Enable-BitLockerAutoUnlock -MountPoint "E:"

# Disable auto-unlock
Disable-BitLockerAutoUnlock -MountPoint "E:"

# View auto-unlock status
Get-BitLockerVolume -MountPoint "E:" | Select-Object AutoUnlockEnabled
```

---

## 🛡️ BitLocker Group Policy Settings

### Configure BitLocker via GPO

**Location:** Computer Configuration → Administrative Templates → Windows Components → BitLocker Drive Encryption

**Recommended Settings:**

```powershell
# Key GPO settings:

# 1. Operating System Drives
# Require additional authentication at startup: Enabled
# - Allow BitLocker without a compatible TPM: No (require TPM)
# - Configure TPM startup: Allow TPM
# - Configure TPM startup PIN: Require startup PIN with TPM
# - Configure TPM startup key: Do not allow startup key with TPM

# 2. Choose drive encryption method and cipher strength
# Select: XTS-AES 256-bit

# 3. Store BitLocker recovery information in Active Directory Domain Services
# Enabled
# - Require BitLocker backup to AD DS: Yes
# - Select: Store recovery passwords and key packages

# 4. Choose how users can recover BitLocker-protected drives
# Enabled
# - Allow 48-digit recovery password: Enabled
# - Allow 256-bit recovery key: Disabled
# - Omit recovery options from BitLocker setup wizard: No

# 5. Deny write access to removable drives not protected by BitLocker
# Enabled (forces encryption on all USB drives)
```

---

## 🔧 Troubleshooting BitLocker Issues

### Issue 1: BitLocker Recovery Key Required on Every Boot

**Cause:** TPM detected changes (BIOS update, hardware change)

```powershell
# Check TPM status
Get-Tpm

# If TPM is cleared, re-initialize
Initialize-Tpm

# Clear and reset BitLocker
Disable-BitLocker -MountPoint "C:"
# Wait for decryption to complete
Enable-BitLocker -MountPoint "C:" -TpmProtector

# Verify secure boot
Confirm-SecureBootUEFI  # Should return True
```

### Issue 2: Cannot Enable BitLocker - "Device Cannot Use TPM"

```powershell
# Check if TPM is enabled in BIOS
# Reboot → Enter BIOS → Security → TPM → Enable

# Verify TPM is ready
Get-Tpm

# If TPM not ready, initialize
Initialize-Tpm

# Alternative: Use BitLocker without TPM (less secure)
# Set GPO: Allow BitLocker without compatible TPM
# Or edit registry:
Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\FVE" -Name "EnableBDEWithNoTPM" -Value 1 -Type DWord

# Enable with password or USB key
Enable-BitLocker -MountPoint "C:" -PasswordProtector -Password (Read-Host -AsSecureString)
```

### Issue 3: Encryption Stuck or Very Slow

```powershell
# Check encryption status
Get-BitLockerVolume -MountPoint "C:" | Select-Object EncryptionPercentage

# Pause and resume encryption
Suspend-BitLocker -MountPoint "C:" -RebootCount 1
Resume-BitLocker -MountPoint "C:"

# Check for disk errors
chkdsk C: /f /r

# Verify disk performance (might be slow HDD)
winsat disk -drive C:
```

### Issue 4: Lost Recovery Key

**If drive is already unlocked:**
```powershell
# Retrieve recovery key from running system
$volume = Get-BitLockerVolume -MountPoint "C:"
$volume.KeyProtector | Where-Object {$_.KeyProtectorType -eq "RecoveryPassword"}
```

**If drive is locked:**
- Check Microsoft account: https://account.microsoft.com/devices/recoverykey
- Check printed backup
- Check AD (for domain computers)
- Contact IT administrator

**If truly lost:** Data is unrecoverable (by design!)

---

## 🎯 BitLocker Best Practices

### Security:
- ✅ Use TPM + PIN for maximum security
- ✅ Use XTS-AES 256-bit encryption
- ✅ Store recovery keys in Active Directory
- ✅ Backup recovery keys to multiple locations
- ✅ Enable BitLocker on all company devices
- ✅ Encrypt removable drives with BitLocker To Go

### Management:
- ✅ Document recovery key locations
- ✅ Test recovery procedures annually
- ✅ Suspend BitLocker before BIOS updates
- ✅ Monitor BitLocker status across fleet
- ✅ Use GPO for consistent deployment
- ✅ Train users on recovery procedures

### Compliance:
- ✅ Meet HIPAA encryption requirements
- ✅ Satisfy GDPR data protection mandates
- ✅ Comply with PCI DSS standards
- ✅ Fulfill SOC 2 security controls

---

## ✅ BitLocker Deployment Checklist

### Pre-Deployment:
- [ ] Verify Windows edition supports BitLocker
- [ ] Confirm TPM 1.2+ present and enabled
- [ ] Enable Secure Boot in UEFI
- [ ] Create system partitions (if needed)
- [ ] Configure Group Policy settings
- [ ] Set up AD recovery key backup

### Deployment:
- [ ] Enable BitLocker on OS drive
- [ ] Configure unlock method (TPM+PIN recommended)
- [ ] Backup recovery key to AD
- [ ] Save recovery key to user's Microsoft account
- [ ] Print recovery key for user records
- [ ] Enable auto-unlock for data drives
- [ ] Encrypt removable drives (if policy requires)

### Post-Deployment:
- [ ] Verify encryption completed successfully
- [ ] Test unlock with PIN/password
- [ ] Test recovery key retrieval process
- [ ] Document configuration
- [ ] Train users on BitLocker basics
- [ ] Monitor for encryption failures

### Ongoing:
- [ ] Monthly: Audit encryption status
- [ ] Quarterly: Test recovery procedures
- [ ] Annually: Update recovery keys
- [ ] As needed: Suspend before hardware changes
'''
        })

        # ============================================================
        # ACTIVE DIRECTORY (7 articles)
        # ============================================================

        articles.append({
            'category': 'Active Directory',
            'title': 'Create and Manage AD Users and Groups - Bulk Operations',
            'body': '''# Create and Manage AD Users and Groups - Bulk Operations

## 🎯 Overview
Comprehensive guide for creating and managing Active Directory users and groups, including bulk operations using PowerShell and CSV imports for efficient administration.

---

## 📋 Prerequisites
- Domain Admin or equivalent permissions
- Active Directory PowerShell module installed
- Remote Server Administration Tools (RSAT) for Windows 10/11
- Excel or text editor for CSV preparation

**Install AD Module (if needed):**
```powershell
# Windows 10/11 - Install RSAT
Add-WindowsCapability -Online -Name Rsat.ActiveDirectory.DS-LDS.Tools~~~~0.0.1.0

# Windows Server
Install-WindowsFeature -Name RSAT-AD-PowerShell

# Import module
Import-Module ActiveDirectory
```

---

## 👤 Creating Single AD User

### Method 1: Active Directory Users and Computers (GUI)
1. Open **Active Directory Users and Computers** (dsa.msc)
2. Navigate to desired OU
3. Right-click → **New** → **User**
4. Fill in details:
   - First name, Last name, Full name
   - User logon name (username)
5. Set password and password options
6. Click **Finish**

### Method 2: PowerShell (Recommended)
```powershell
# Create new AD user with full details
New-ADUser -Name "John Smith" `
    -GivenName "John" `
    -Surname "Smith" `
    -SamAccountName "jsmith" `
    -UserPrincipalName "jsmith@contoso.com" `
    -Path "OU=Users,OU=Sales,DC=contoso,DC=com" `
    -AccountPassword (ConvertTo-SecureString "P@ssw0rd123!" -AsPlainText -Force) `
    -Enabled $true `
    -ChangePasswordAtLogon $true `
    -EmailAddress "jsmith@contoso.com" `
    -Title "Sales Manager" `
    -Department "Sales" `
    -Company "Contoso Inc" `
    -Office "New York" `
    -OfficePhone "+1-555-1234" `
    -MobilePhone "+1-555-5678"

# Verify user creation
Get-ADUser -Identity jsmith -Properties *
```

---

## 📦 Bulk User Creation from CSV

### Step 1: Prepare CSV File
Create file: **new_users.csv**
```csv
FirstName,LastName,Username,Email,Password,Department,Title,Office,OU
John,Smith,jsmith,jsmith@contoso.com,P@ssw0rd123!,Sales,Sales Manager,New York,"OU=Users,OU=Sales,DC=contoso,DC=com"
Jane,Doe,jdoe,jdoe@contoso.com,P@ssw0rd123!,IT,IT Specialist,Boston,"OU=Users,OU=IT,DC=contoso,DC=com"
Bob,Johnson,bjohnson,bjohnson@contoso.com,P@ssw0rd123!,HR,HR Director,Chicago,"OU=Users,OU=HR,DC=contoso,DC=com"
```

### Step 2: Bulk Import Script
```powershell
# Import CSV and create users
$Users = Import-Csv -Path "C:\\Temp\\new_users.csv"

foreach ($User in $Users) {
    try {
        $Password = ConvertTo-SecureString $User.Password -AsPlainText -Force

        New-ADUser `
            -Name "$($User.FirstName) $($User.LastName)" `
            -GivenName $User.FirstName `
            -Surname $User.LastName `
            -SamAccountName $User.Username `
            -UserPrincipalName $User.Email `
            -Path $User.OU `
            -AccountPassword $Password `
            -Enabled $true `
            -ChangePasswordAtLogon $true `
            -EmailAddress $User.Email `
            -Department $User.Department `
            -Title $User.Title `
            -Office $User.Office `
            -Company "Contoso Inc"

        Write-Host "✓ Created user: $($User.Username)" -ForegroundColor Green
    }
    catch {
        Write-Host "✗ Failed to create $($User.Username): $_" -ForegroundColor Red
    }
}

Write-Host "`n✓ Bulk user creation complete!" -ForegroundColor Cyan
```

### Step 3: Advanced Bulk Import with Error Logging
```powershell
# Enhanced script with logging
$Users = Import-Csv -Path "C:\\Temp\\new_users.csv"
$LogFile = "C:\\Temp\\user_creation_log.txt"
$SuccessCount = 0
$FailCount = 0

foreach ($User in $Users) {
    try {
        # Check if user already exists
        if (Get-ADUser -Filter "SamAccountName -eq '$($User.Username)'" -ErrorAction SilentlyContinue) {
            $Message = "⚠ User $($User.Username) already exists - SKIPPED"
            Write-Host $Message -ForegroundColor Yellow
            Add-Content -Path $LogFile -Value "$Message`n"
            continue
        }

        $Password = ConvertTo-SecureString $User.Password -AsPlainText -Force

        New-ADUser `
            -Name "$($User.FirstName) $($User.LastName)" `
            -GivenName $User.FirstName `
            -Surname $User.LastName `
            -SamAccountName $User.Username `
            -UserPrincipalName $User.Email `
            -Path $User.OU `
            -AccountPassword $Password `
            -Enabled $true `
            -ChangePasswordAtLogon $true `
            -EmailAddress $User.Email `
            -Department $User.Department `
            -Title $User.Title `
            -Office $User.Office

        $Message = "✓ SUCCESS: Created user $($User.Username)"
        Write-Host $Message -ForegroundColor Green
        Add-Content -Path $LogFile -Value "$Message"
        $SuccessCount++
    }
    catch {
        $Message = "✗ FAILED: $($User.Username) - Error: $_"
        Write-Host $Message -ForegroundColor Red
        Add-Content -Path $LogFile -Value "$Message"
        $FailCount++
    }
}

# Summary
$Summary = "`n========== SUMMARY ==========`nTotal: $($Users.Count) | Success: $SuccessCount | Failed: $FailCount"
Write-Host $Summary -ForegroundColor Cyan
Add-Content -Path $LogFile -Value $Summary
```

---

## 👥 Creating and Managing AD Groups

### Create Security Group
```powershell
# Create new security group
New-ADGroup -Name "Sales_Team" `
    -GroupCategory Security `
    -GroupScope Global `
    -DisplayName "Sales Team" `
    -Path "OU=Groups,OU=Sales,DC=contoso,DC=com" `
    -Description "Members of the Sales department"

# Create distribution group
New-ADGroup -Name "Company_All" `
    -GroupCategory Distribution `
    -GroupScope Universal `
    -DisplayName "All Company Employees" `
    -Path "OU=Groups,DC=contoso,DC=com" `
    -Description "All company employees distribution list"
```

### Add Users to Groups
```powershell
# Add single user to group
Add-ADGroupMember -Identity "Sales_Team" -Members "jsmith"

# Add multiple users
Add-ADGroupMember -Identity "Sales_Team" -Members "jsmith","jdoe","bjohnson"

# Add all users from specific OU to group
Get-ADUser -Filter * -SearchBase "OU=Users,OU=Sales,DC=contoso,DC=com" |
    ForEach-Object { Add-ADGroupMember -Identity "Sales_Team" -Members $_ }

# Verify group membership
Get-ADGroupMember -Identity "Sales_Team" | Select-Object Name, SamAccountName
```

### Bulk Group Membership from CSV
Create file: **group_members.csv**
```csv
GroupName,Username
Sales_Team,jsmith
Sales_Team,jdoe
IT_Admins,bjohnson
HR_Department,alice
```

```powershell
# Import and process
$Memberships = Import-Csv -Path "C:\\Temp\\group_members.csv"

foreach ($Member in $Memberships) {
    try {
        Add-ADGroupMember -Identity $Member.GroupName -Members $Member.Username
        Write-Host "✓ Added $($Member.Username) to $($Member.GroupName)" -ForegroundColor Green
    }
    catch {
        Write-Host "✗ Failed: $_" -ForegroundColor Red
    }
}
```

---

## 🔧 Modifying Users in Bulk

### Update User Properties
```powershell
# Update single property for all users in OU
Get-ADUser -Filter * -SearchBase "OU=Users,OU=Sales,DC=contoso,DC=com" |
    Set-ADUser -Company "Contoso Inc" -Office "New York"

# Update from CSV
$Updates = Import-Csv -Path "C:\\Temp\\user_updates.csv"
# CSV: Username,Department,Title,Phone

foreach ($Update in $Updates) {
    Set-ADUser -Identity $Update.Username `
        -Department $Update.Department `
        -Title $Update.Title `
        -OfficePhone $Update.Phone
}
```

### Enable/Disable Users in Bulk
```powershell
# Disable users from list
$UsersToDisable = Get-Content "C:\\Temp\\disable_users.txt"
foreach ($User in $UsersToDisable) {
    Disable-ADAccount -Identity $User
    Write-Host "✓ Disabled: $User" -ForegroundColor Yellow
}

# Enable users
$UsersToEnable = Get-Content "C:\\Temp\\enable_users.txt"
foreach ($User in $UsersToEnable) {
    Enable-ADAccount -Identity $User
    Write-Host "✓ Enabled: $User" -ForegroundColor Green
}
```

### Reset Passwords in Bulk
```powershell
# Reset passwords from CSV
$PasswordResets = Import-Csv -Path "C:\\Temp\\password_resets.csv"
# CSV: Username,NewPassword

foreach ($Reset in $PasswordResets) {
    $Password = ConvertTo-SecureString $Reset.NewPassword -AsPlainText -Force
    Set-ADAccountPassword -Identity $Reset.Username -NewPassword $Password -Reset
    Set-ADUser -Identity $Reset.Username -ChangePasswordAtLogon $true
    Write-Host "✓ Password reset for: $($Reset.Username)" -ForegroundColor Green
}
```

---

## 🗑️ Removing Users and Groups

### Delete Single User
```powershell
# Remove user (move to Deleted Objects)
Remove-ADUser -Identity "jsmith" -Confirm:$false

# Remove user permanently (skip Recycle Bin)
Remove-ADUser -Identity "jsmith" -Confirm:$false -Permanent
```

### Bulk Delete Users
```powershell
# Delete users from CSV
$UsersToDelete = Import-Csv -Path "C:\\Temp\\users_to_delete.csv"
# CSV: Username

foreach ($User in $UsersToDelete) {
    try {
        Remove-ADUser -Identity $User.Username -Confirm:$false
        Write-Host "✓ Deleted: $($User.Username)" -ForegroundColor Yellow
    }
    catch {
        Write-Host "✗ Failed to delete $($User.Username): $_" -ForegroundColor Red
    }
}
```

---

## 📊 Reporting and Auditing

### Export All Users to CSV
```powershell
# Export all user details
Get-ADUser -Filter * -Properties * |
    Select-Object Name, SamAccountName, EmailAddress, Department, Title, Enabled, WhenCreated |
    Export-Csv -Path "C:\\Temp\\all_users.csv" -NoTypeInformation

# Export users from specific OU
Get-ADUser -Filter * -SearchBase "OU=Users,OU=Sales,DC=contoso,DC=com" -Properties * |
    Export-Csv -Path "C:\\Temp\\sales_users.csv" -NoTypeInformation
```

### Find Inactive Users
```powershell
# Find users not logged in for 90 days
$DaysInactive = 90
$InactiveDate = (Get-Date).AddDays(-$DaysInactive)

Get-ADUser -Filter {LastLogonDate -lt $InactiveDate -and Enabled -eq $true} `
    -Properties LastLogonDate |
    Select-Object Name, SamAccountName, LastLogonDate, DistinguishedName |
    Export-Csv -Path "C:\\Temp\\inactive_users.csv" -NoTypeInformation
```

### Group Membership Report
```powershell
# Export all groups and their members
$Groups = Get-ADGroup -Filter *
$Report = @()

foreach ($Group in $Groups) {
    $Members = Get-ADGroupMember -Identity $Group
    foreach ($Member in $Members) {
        $Report += [PSCustomObject]@{
            GroupName = $Group.Name
            MemberName = $Member.Name
            MemberType = $Member.objectClass
        }
    }
}

$Report | Export-Csv -Path "C:\\Temp\\group_memberships.csv" -NoTypeInformation
```

---

## 🔧 Troubleshooting

### Common Errors and Solutions

**Error: "The specified account already exists"**
```powershell
# Check if user exists
Get-ADUser -Filter "SamAccountName -eq 'jsmith'" -ErrorAction SilentlyContinue
# If exists, use different username or remove old account
```

**Error: "The object name has bad syntax"**
- Verify OU path is correct
- Use `Get-ADOrganizationalUnit -Filter *` to list OUs
- Ensure DN format: "OU=Users,OU=Department,DC=domain,DC=com"

**Error: "Unable to contact the server"**
```powershell
# Test AD connection
Test-ComputerSecureChannel -Verbose
# Or
nltest /sc_query:contoso.com
```

**CSV Import Issues**
- Ensure CSV is UTF-8 encoded (Save As → Encoding: UTF-8)
- Remove BOM (Byte Order Mark) if present
- Verify column headers match script exactly (case-sensitive)

---

## ✅ Best Practices

### Naming Conventions:
- ✅ Use consistent username format (firstname.lastname or flastname)
- ✅ Use descriptive group names with prefixes (SEC_, DL_, etc.)
- ✅ Document naming standards in your organization

### Security:
- ✅ Never store passwords in plain text files
- ✅ Use complex passwords meeting policy requirements
- ✅ Force password change at first logon
- ✅ Implement least privilege access
- ✅ Regular audit of group memberships

### Organization:
- ✅ Use OUs to organize users by department/location
- ✅ Apply Group Policy at OU level for efficiency
- ✅ Keep "Disabled Users" in separate OU
- ✅ Document OU structure

### Automation:
- ✅ Test scripts on test accounts before bulk operations
- ✅ Always use error handling (try/catch)
- ✅ Log all bulk operations
- ✅ Create rollback procedures
- ✅ Backup AD before major changes

### Maintenance:
- ✅ Review inactive accounts monthly
- ✅ Clean up disabled accounts after 90 days
- ✅ Audit group memberships quarterly
- ✅ Update user properties regularly (department changes, etc.)

---

## 📝 Bulk Operation Checklist

### Before Bulk Operations:
- [ ] Backup Active Directory
- [ ] Test script with 1-2 test accounts
- [ ] Verify CSV format and data accuracy
- [ ] Check OU paths exist
- [ ] Ensure sufficient permissions
- [ ] Prepare rollback plan

### During Operations:
- [ ] Monitor for errors in real-time
- [ ] Save detailed logs
- [ ] Take note of any failures
- [ ] Pause if error rate is high

### After Operations:
- [ ] Verify users were created correctly
- [ ] Test user logon with sample accounts
- [ ] Verify group memberships
- [ ] Review logs for any errors
- [ ] Document changes made
- [ ] Notify relevant stakeholders

---

## 🎯 Quick Reference Commands

```powershell
# List all users
Get-ADUser -Filter * | Select Name, SamAccountName, Enabled

# Find specific user
Get-ADUser -Identity username -Properties *

# List all groups
Get-ADGroup -Filter * | Select Name, GroupScope, GroupCategory

# Check group membership
Get-ADGroupMember -Identity "GroupName"

# Find user's group memberships
Get-ADPrincipalGroupMembership -Identity username | Select Name

# Count users in OU
(Get-ADUser -Filter * -SearchBase "OU=Users,DC=contoso,DC=com").Count

# Export disabled users
Get-ADUser -Filter {Enabled -eq $false} | Export-Csv disabled_users.csv
```
'''
        })

        articles.append({
            'category': 'Active Directory',
            'title': 'Active Directory Organizational Units (OU) Best Practices',
            'body': '''# Active Directory Organizational Units (OU) Best Practices

## 🎯 Overview
Comprehensive guide for designing, implementing, and managing Active Directory Organizational Units (OUs) for optimal administration, Group Policy application, and delegation of control.

---

## 📋 What are Organizational Units?

**Organizational Units (OUs)** are Active Directory containers that:
- Organize objects (users, computers, groups) hierarchically
- Enable Group Policy application
- Allow delegation of administrative permissions
- Mirror business structure or IT management needs
- Simplify object management and reporting

**Key Difference from Groups:**
- **OUs**: Used for organization and administration
- **Groups**: Used for permissions and access control

---

## 🏗️ OU Design Principles

### Design by Administrative Need (Recommended)
Design OUs based on **who manages them** and **what policies apply**, not just organizational chart.

**Good OU Structure:**
```
contoso.com
├── Workstations
│   ├── Desktops
│   ├── Laptops
│   └── Kiosks
├── Servers
│   ├── Domain Controllers
│   ├── File Servers
│   ├── Application Servers
│   └── Database Servers
├── Users
│   ├── Employees
│   ├── Contractors
│   ├── Administrators
│   └── Service Accounts
├── Groups
│   ├── Security Groups
│   └── Distribution Lists
└── Disabled Objects
    ├── Disabled Users
    └── Disabled Computers
```

### Design Considerations

**1. Keep It Simple**
- ✅ Maximum 5-7 levels deep
- ✅ Flat where possible
- ✅ Avoid mimicking entire org chart
- ❌ Don't create OUs for every department if they have same policies

**2. Plan for Group Policy**
- ✅ Create OUs where different GPOs apply
- ✅ Separate user and computer OUs
- ✅ Consider GPO inheritance and blocking

**3. Plan for Delegation**
- ✅ Create OUs for different admin levels
- ✅ Regional/site-based OUs for distributed administration
- ✅ Separate privileged accounts

**4. Consider Future Growth**
- ✅ Scalable structure
- ✅ Easy to add new sites/departments
- ✅ Flexible for mergers/acquisitions

---

## 🔧 Creating and Managing OUs

### Create OU (GUI Method)
1. Open **Active Directory Users and Computers** (dsa.msc)
2. Right-click parent container → **New** → **Organizational Unit**
3. Enter OU name
4. Optionally check **Protect container from accidental deletion**
5. Click **OK**

### Create OU (PowerShell)
```powershell
# Create single OU
New-ADOrganizationalUnit -Name "Employees" `
    -Path "OU=Users,DC=contoso,DC=com" `
    -ProtectedFromAccidentalDeletion $true `
    -Description "All employee user accounts"

# Verify creation
Get-ADOrganizationalUnit -Filter "Name -eq 'Employees'"
```

### Create Nested OU Structure
```powershell
# Create parent OU
New-ADOrganizationalUnit -Name "Users" `
    -Path "DC=contoso,DC=com" `
    -ProtectedFromAccidentalDeletion $true

# Create child OUs
$ChildOUs = @("Employees", "Contractors", "Administrators", "Service Accounts", "Disabled Users")

foreach ($OU in $ChildOUs) {
    New-ADOrganizationalUnit -Name $OU `
        -Path "OU=Users,DC=contoso,DC=com" `
        -ProtectedFromAccidentalDeletion $true `
        -Description "OU for $OU"
    Write-Host "✓ Created OU: $OU" -ForegroundColor Green
}
```

### Create Complete OU Structure from Script
```powershell
# Define OU structure
$OUStructure = @(
    @{Name="Workstations"; Path="DC=contoso,DC=com"; Description="All workstations"},
    @{Name="Desktops"; Path="OU=Workstations,DC=contoso,DC=com"; Description="Desktop computers"},
    @{Name="Laptops"; Path="OU=Workstations,DC=contoso,DC=com"; Description="Laptop computers"},
    @{Name="Servers"; Path="DC=contoso,DC=com"; Description="All servers"},
    @{Name="File Servers"; Path="OU=Servers,DC=contoso,DC=com"; Description="File and print servers"},
    @{Name="Users"; Path="DC=contoso,DC=com"; Description="All user accounts"},
    @{Name="Employees"; Path="OU=Users,DC=contoso,DC=com"; Description="Employee accounts"},
    @{Name="Groups"; Path="DC=contoso,DC=com"; Description="All groups"},
    @{Name="Security Groups"; Path="OU=Groups,DC=contoso,DC=com"; Description="Security groups"}
)

foreach ($OU in $OUStructure) {
    try {
        New-ADOrganizationalUnit -Name $OU.Name `
            -Path $OU.Path `
            -Description $OU.Description `
            -ProtectedFromAccidentalDeletion $true `
            -ErrorAction Stop
        Write-Host "✓ Created: $($OU.Name)" -ForegroundColor Green
    }
    catch {
        Write-Host "⚠ Already exists or error: $($OU.Name)" -ForegroundColor Yellow
    }
}
```

---

## 🗺️ Common OU Design Patterns

### Pattern 1: Geographic-Based Structure
```
contoso.com
├── North America
│   ├── USA
│   │   ├── New York
│   │   │   ├── Users
│   │   │   └── Computers
│   │   └── Los Angeles
│   │       ├── Users
│   │       └── Computers
│   └── Canada
│       └── Toronto
├── Europe
│   ├── UK
│   └── Germany
└── Asia Pacific
    └── Australia
```

**Use When:**
- Multi-site organization
- Different regional policies
- Delegated regional IT teams

### Pattern 2: Function-Based Structure
```
contoso.com
├── Corporate
│   ├── Sales
│   ├── Marketing
│   ├── Finance
│   ├── HR
│   └── IT
├── Production
│   ├── Manufacturing
│   └── Warehouse
└── Retail
    ├── Stores
    └── Distribution
```

**Use When:**
- Different policies per business function
- Department-based administration
- Compliance requirements by function

### Pattern 3: Hybrid Structure (Recommended)
```
contoso.com
├── Admin
│   ├── Domain Admins
│   ├── Service Accounts
│   └── Privileged Access Workstations
├── Resources
│   ├── Workstations
│   │   ├── Standard Users
│   │   ├── Power Users
│   │   └── Kiosks
│   ├── Servers
│   │   ├── Member Servers
│   │   └── Infrastructure
│   └── Groups
├── Locations
│   ├── New York
│   │   ├── Users
│   │   └── Computers
│   └── Chicago
│       ├── Users
│       └── Computers
└── Quarantine
    ├── Disabled Users
    ├── Disabled Computers
    └── Pending Deletion
```

**Use When:**
- Need both geographic and functional organization
- Complex multi-site environment
- Mix of centralized and decentralized management

---

## 🔐 Delegating OU Permissions

### Common Delegation Scenarios

**1. Delegate User Account Management**
```powershell
# Allow help desk to reset passwords in specific OU
$OU = "OU=Employees,OU=Users,DC=contoso,DC=com"
$Group = "HelpDesk_Admins"

# Using GUI:
# Right-click OU → Delegate Control → Add group →
# Select "Reset user passwords and force password change at next logon"
```

**PowerShell Delegation (Advanced):**
```powershell
# Import AD module
Import-Module ActiveDirectory

# Get OU
$OU = Get-ADOrganizationalUnit -Identity "OU=Employees,OU=Users,DC=contoso,DC=com"
$Group = Get-ADGroup -Identity "HelpDesk_Admins"

# Get ACL
$ACL = Get-Acl -Path "AD:$($OU.DistinguishedName)"

# Create new access rule for password reset
$PasswordResetGUID = [GUID]"00299570-246d-11d0-a768-00aa006e0529"
$ExtendedRight = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
    $Group.SID,
    [System.DirectoryServices.ActiveDirectoryRights]::ExtendedRight,
    [System.Security.AccessControl.AccessControlType]::Allow,
    $PasswordResetGUID,
    [DirectoryServices.ActiveDirectorySecurityInheritance]::All
)

# Apply ACL
$ACL.AddAccessRule($ExtendedRight)
Set-Acl -Path "AD:$($OU.DistinguishedName)" -AclObject $ACL

Write-Host "✓ Delegated password reset permissions to $Group" -ForegroundColor Green
```

**2. Delegate Computer Management**
```powershell
# Delegate ability to join computers to domain in specific OU
# GUI Method:
# 1. Right-click Workstations OU → Delegate Control
# 2. Add "Desktop_Admins" group
# 3. Select "Join a computer to the domain"
# 4. Select "Create, delete, and manage computer accounts"
```

**3. Delegate Group Management**
```powershell
# Allow group managers to modify group membership
# GUI Method:
# 1. Right-click Groups OU → Delegate Control
# 2. Add "Group_Managers" group
# 3. Select "Create, delete, and manage groups"
# 4. Select "Modify the membership of a group"
```

---

## 📊 OU Reporting and Auditing

### List All OUs
```powershell
# Get all OUs with details
Get-ADOrganizationalUnit -Filter * -Properties * |
    Select-Object Name, DistinguishedName, Description, ProtectedFromAccidentalDeletion |
    Export-Csv -Path "C:\\Temp\\all_ous.csv" -NoTypeInformation

# Get OU hierarchy as tree
Get-ADOrganizationalUnit -Filter * |
    Select-Object @{Name="Level";Expression={($_.DistinguishedName -split ",OU=").Count}}, Name, DistinguishedName |
    Sort-Object Level, Name |
    Format-Table
```

### Count Objects in Each OU
```powershell
# Count users per OU
Get-ADOrganizationalUnit -Filter * | ForEach-Object {
    $OU = $_.DistinguishedName
    $UserCount = (Get-ADUser -Filter * -SearchBase $OU -SearchScope OneLevel).Count
    $ComputerCount = (Get-ADComputer -Filter * -SearchBase $OU -SearchScope OneLevel).Count

    [PSCustomObject]@{
        OU = $_.Name
        Users = $UserCount
        Computers = $ComputerCount
        Path = $OU
    }
} | Export-Csv -Path "C:\\Temp\\ou_object_counts.csv" -NoTypeInformation
```

### Find Empty OUs
```powershell
# Find OUs with no direct objects
Get-ADOrganizationalUnit -Filter * | ForEach-Object {
    $OU = $_.DistinguishedName
    $ObjectCount = (Get-ADObject -Filter * -SearchBase $OU -SearchScope OneLevel).Count

    if ($ObjectCount -eq 0) {
        [PSCustomObject]@{
            EmptyOU = $_.Name
            Path = $OU
        }
    }
} | Format-Table -AutoSize
```

---

## 🔧 Troubleshooting

### Cannot Delete OU
**Error: "Access is denied" or "The object is protected"**

```powershell
# Check if OU is protected
Get-ADOrganizationalUnit -Identity "OU=TestOU,DC=contoso,DC=com" -Properties ProtectedFromAccidentalDeletion

# Remove protection
Set-ADOrganizationalUnit -Identity "OU=TestOU,DC=contoso,DC=com" -ProtectedFromAccidentalDeletion $false

# Now delete
Remove-ADOrganizationalUnit -Identity "OU=TestOU,DC=contoso,DC=com" -Confirm:$false
```

### Move Objects Between OUs
```powershell
# Move single user
Move-ADObject -Identity "CN=John Smith,OU=OldOU,DC=contoso,DC=com" `
    -TargetPath "OU=NewOU,DC=contoso,DC=com"

# Move all users from one OU to another
Get-ADUser -Filter * -SearchBase "OU=OldOU,DC=contoso,DC=com" -SearchScope OneLevel |
    Move-ADObject -TargetPath "OU=NewOU,DC=contoso,DC=com"
```

### Rename OU
```powershell
# Rename organizational unit
Rename-ADObject -Identity "OU=OldName,DC=contoso,DC=com" -NewName "NewName"

# Verify
Get-ADOrganizationalUnit -Filter "Name -eq 'NewName'"
```

---

## ✅ Best Practices Summary

### Design:
- ✅ Design for Group Policy and delegation, not org chart
- ✅ Keep structure simple (5-7 levels max)
- ✅ Separate users, computers, groups into different OUs
- ✅ Create dedicated OUs for servers, workstations, service accounts
- ✅ Use consistent naming conventions

### Security:
- ✅ Enable "Protect from accidental deletion" on all production OUs
- ✅ Separate privileged accounts into dedicated OUs
- ✅ Apply principle of least privilege when delegating
- ✅ Regular audit of delegated permissions
- ✅ Use security groups for delegation, not individual users

### Group Policy:
- ✅ Block inheritance sparingly
- ✅ Apply GPOs at highest appropriate level
- ✅ Document GPO-to-OU mappings
- ✅ Test GPOs in test OU before production

### Management:
- ✅ Document OU structure and purpose
- ✅ Use descriptive OU names
- ✅ Create "Disabled Objects" or "Quarantine" OU
- ✅ Regular cleanup of empty OUs
- ✅ Move objects, don't recreate them

### Naming Conventions:
- ✅ Use clear, descriptive names
- ✅ Avoid special characters
- ✅ Be consistent across environment
- ✅ Consider using prefixes (e.g., LOC_NewYork, FUNC_Sales)

---

## 📝 OU Implementation Checklist

### Planning Phase:
- [ ] Document current structure (if migrating)
- [ ] Identify GPO requirements
- [ ] Identify delegation requirements
- [ ] Design OU hierarchy (max 5-7 levels)
- [ ] Define naming conventions
- [ ] Get stakeholder approval

### Implementation Phase:
- [ ] Create OU structure in test environment
- [ ] Test GPO application
- [ ] Test delegation
- [ ] Document structure
- [ ] Create in production during maintenance window
- [ ] Migrate objects to new structure

### Post-Implementation:
- [ ] Verify GPO application
- [ ] Verify delegations work correctly
- [ ] Train administrators on new structure
- [ ] Update documentation
- [ ] Monitor for issues

### Ongoing Maintenance:
- [ ] Monthly: Review OU object counts
- [ ] Quarterly: Audit delegated permissions
- [ ] Quarterly: Clean up empty OUs
- [ ] Annually: Review structure for optimization
- [ ] As needed: Adjust for business changes
'''
        })

        articles.append({
            'category': 'Active Directory',
            'title': 'FSMO Roles - Transfer and Seize Operations',
            'body': '''# FSMO Roles - Transfer and Seize Operations

## 🎯 Overview
Comprehensive guide for managing Active Directory Flexible Single Master Operations (FSMO) roles, including transfer procedures, seizing roles in disaster recovery, and troubleshooting FSMO-related issues.

---

## 📋 Understanding FSMO Roles

**FSMO (Flexible Single Master Operations)** roles are special domain controller tasks that cannot be performed by multiple DCs simultaneously.

### The 5 FSMO Roles

**Forest-Wide Roles (1 per forest):**

1. **Schema Master**
   - Controls all updates to AD schema
   - Required for: Schema updates, Exchange installations
   - Location: First DC in forest (typically)

2. **Domain Naming Master**
   - Controls addition/removal of domains in forest
   - Required for: Adding/removing domains, creating application partitions
   - Location: First DC in forest (typically)

**Domain-Wide Roles (1 per domain):**

3. **PDC Emulator**
   - Time synchronization source
   - Password changes processed here first
   - Receives preferential replication of password changes
   - Group Policy central management
   - Required for: Time sync, password resets, legacy NT4 compatibility
   - **Most critical role**

4. **RID Master**
   - Allocates RID pools to domain controllers
   - RIDs used to create unique SIDs for new objects
   - Required for: Creating users, groups, computers

5. **Infrastructure Master**
   - Updates cross-domain group memberships
   - Required for: Multi-domain environments
   - **Should NOT be on Global Catalog server** (unless all DCs are GCs)

---

## 🔍 Viewing Current FSMO Role Holders

### Method 1: PowerShell (Recommended)
```powershell
# View all FSMO roles
Get-ADForest | Select-Object SchemaMaster, DomainNamingMaster
Get-ADDomain | Select-Object PDCEmulator, RIDMaster, InfrastructureMaster

# Comprehensive view
$Forest = Get-ADForest
$Domain = Get-ADDomain

Write-Host "`n========== FOREST-WIDE FSMO ROLES ==========" -ForegroundColor Cyan
Write-Host "Schema Master: $($Forest.SchemaMaster)"
Write-Host "Domain Naming Master: $($Forest.DomainNamingMaster)"

Write-Host "`n========== DOMAIN-WIDE FSMO ROLES ==========" -ForegroundColor Cyan
Write-Host "PDC Emulator: $($Domain.PDCEmulator)"
Write-Host "RID Master: $($Domain.RIDMaster)"
Write-Host "Infrastructure Master: $($Domain.InfrastructureMaster)"
```

### Method 2: Using netdom
```cmd
netdom query fsmo
```

### Method 3: GUI Methods

**View Schema Master and Domain Naming Master:**
```powershell
# Open Active Directory Domains and Trusts
domain.msc

# Right-click root → Operations Masters
```

**View PDC, RID, Infrastructure Master:**
```powershell
# Open Active Directory Users and Computers
dsa.msc

# Right-click domain → Operations Masters
# Check all three tabs: RID, PDC, Infrastructure
```

---

## 🔄 Transferring FSMO Roles (Normal Operation)

**Transfer** = Graceful move when both DCs are online and healthy.

### Transfer via PowerShell (Recommended)

```powershell
# Define target domain controller
$TargetDC = "DC02.contoso.com"

# Transfer PDC Emulator
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole PDCEmulator

# Transfer RID Master
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole RIDMaster

# Transfer Infrastructure Master
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole InfrastructureMaster

# Transfer Schema Master
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole SchemaMaster

# Transfer Domain Naming Master
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole DomainNamingMaster

# Transfer ALL roles at once
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC `
    -OperationMasterRole PDCEmulator, RIDMaster, InfrastructureMaster, SchemaMaster, DomainNamingMaster -Force
```

### Transfer via ntdsutil (Legacy Method)

```cmd
# Run as Domain Admin
ntdsutil
roles
connections
connect to server DC02.contoso.com
quit

# Transfer specific role
transfer pdc
transfer rid master
transfer infrastructure master
transfer schema master
transfer naming master

# Exit ntdsutil
quit
quit
```

### Transfer via GUI

**For PDC, RID, Infrastructure:**
1. Open **Active Directory Users and Computers**
2. Right-click domain → **Operations Masters**
3. Select tab for role to transfer
4. Click **Change**
5. Confirm transfer

**For Schema Master:**
1. Register schmmgmt.dll: `regsvr32 schmmgmt.dll`
2. Run `mmc` → Add Snap-in → Active Directory Schema
3. Right-click **Active Directory Schema** → **Operations Master**
4. Click **Change**

**For Domain Naming Master:**
1. Open **Active Directory Domains and Trusts**
2. Right-click root → **Operations Masters**
3. Click **Change**

---

## ⚡ Seizing FSMO Roles (Disaster Recovery)

**Seize** = Forced takeover when original DC is offline/dead.

### ⚠️ WARNING: Only seize roles if:
- Original role holder is permanently offline/destroyed
- Original role holder cannot be brought back online
- You've confirmed old DC won't come back (metadata cleanup required)

### Seize via PowerShell
```powershell
# Seize to target DC (use -Force for seizing)
$TargetDC = "DC02.contoso.com"

# Seize all roles
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC `
    -OperationMasterRole PDCEmulator, RIDMaster, InfrastructureMaster, SchemaMaster, DomainNamingMaster `
    -Force

# Seize individual role
Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole PDCEmulator -Force
```

### Seize via ntdsutil
```cmd
ntdsutil
roles
connections
connect to server DC02.contoso.com
quit

# Seize specific roles
seize pdc
seize rid master
seize infrastructure master
seize schema master
seize naming master

quit
quit
```

### After Seizing Roles - CRITICAL STEPS

**1. Metadata Cleanup (Remove old DC)**
```powershell
# Remove old DC from AD
Remove-ADObject -Identity "CN=DC01,OU=Domain Controllers,DC=contoso,DC=com" -Recursive -Confirm:$false

# Or use ntdsutil
ntdsutil
metadata cleanup
connections
connect to server DC02.contoso.com
quit
select operation target
list sites
select site 0
list servers in site
select server 0  # Select the failed DC
quit
remove selected server
quit
quit
```

**2. Clean DNS Records**
```powershell
# Remove old DC DNS records
# In DNS Manager, delete A, CNAME records for old DC
```

**3. Check Replication**
```powershell
repadmin /replsummary
repadmin /showrepl
```

---

## 🎯 Common FSMO Scenarios

### Scenario 1: Decommissioning a Domain Controller

```powershell
# Step 1: Check current roles
Get-ADDomain | Select PDCEmulator, RIDMaster, InfrastructureMaster
Get-ADForest | Select SchemaMaster, DomainNamingMaster

# Step 2: Transfer any roles OFF the DC being decommissioned
$TargetDC = "DC02.contoso.com"  # Healthy DC
$SourceDC = "DC01.contoso.com"  # DC being removed

# Check which roles DC01 holds
if ((Get-ADDomain).PDCEmulator -like "*DC01*") {
    Move-ADDirectoryServerOperationMasterRole -Identity $TargetDC -OperationMasterRole PDCEmulator
}

# Repeat for all 5 roles...

# Step 3: Demote the DC properly
# On DC01:
Uninstall-WindowsFeature -Name AD-Domain-Services
```

### Scenario 2: Primary DC Failed Catastrophically

```powershell
# Emergency procedure - PDC failed and cannot be recovered

# Step 1: Seize PDC role to surviving DC
$NewPDC = "DC02.contoso.com"
Move-ADDirectoryServerOperationMasterRole -Identity $NewPDC -OperationMasterRole PDCEmulator -Force

# Step 2: Seize other roles if also on failed DC
Move-ADDirectoryServerOperationMasterRole -Identity $NewPDC `
    -OperationMasterRole RIDMaster, InfrastructureMaster, SchemaMaster, DomainNamingMaster -Force

# Step 3: Metadata cleanup
ntdsutil
metadata cleanup
remove selected server
# Follow prompts...

# Step 4: Force replication
repadmin /syncall /AdeP
```

### Scenario 3: Upgrading Domain Controllers

```powershell
# Best practice: Move roles to stable DC during upgrades

# Before upgrade:
Move-ADDirectoryServerOperationMasterRole -Identity "DC02.contoso.com" `
    -OperationMasterRole PDCEmulator, RIDMaster, InfrastructureMaster, SchemaMaster, DomainNamingMaster

# Upgrade DC01 (install updates, reboot, etc.)

# After upgrade (optional - move roles back):
Move-ADDirectoryServerOperationMasterRole -Identity "DC01.contoso.com" `
    -OperationMasterRole PDCEmulator, RIDMaster, InfrastructureMaster, SchemaMaster, DomainNamingMaster
```

---

## 🔧 Troubleshooting FSMO Issues

### Problem: Cannot Create Users/Groups
**Cause:** RID Master unavailable or RID pool exhausted

```powershell
# Check RID Master availability
dcdiag /test:ridmanager /v

# Check RID pool allocation
dcdiag /test:frssysvol /v

# View current RID usage on DC
Get-ADDomainController -Identity $env:COMPUTERNAME |
    Select-Object -ExpandProperty RIDAvailablePool
```

**Solution:**
- Verify RID Master is online and replicating
- If RID Master is dead, seize role to healthy DC
- Request new RID pool if exhausted

### Problem: Time Synchronization Issues
**Cause:** PDC Emulator issues or time source misconfiguration

```powershell
# Check PDC Emulator
Get-ADDomain | Select PDCEmulator

# Check time source on PDC
w32tm /query /source

# Configure PDC to sync with external source
w32tm /config /manualpeerlist:"time.windows.com,time.nist.gov" /syncfromflags:manual /reliable:yes /update
net stop w32time
net start w32time
w32tm /resync /force

# Other DCs should sync from PDC automatically
```

### Problem: Group Policy Not Updating
**Cause:** PDC Emulator unavailable

```powershell
# Verify PDC is online
Test-Connection -ComputerName (Get-ADDomain).PDCEmulator -Count 2

# Force GPO replication
gpupdate /force

# Check GP replication from PDC
dcdiag /test:netlogons
```

### Problem: "RID Pool Unavailable" Errors

```powershell
# Request new RID pool allocation
dcdiag /test:ridmanager /v

# Check RID Master connectivity
nltest /server:RID-Master-DC /sc_query:contoso.com

# If RID Master is unreachable, consider seizing role
```

### Problem: Schema Update Fails
**Cause:** Schema Master unavailable or connectivity issues

```powershell
# Verify Schema Master
Get-ADForest | Select SchemaMaster

# Test connectivity
Test-NetConnection -ComputerName (Get-ADForest).SchemaMaster -Port 389

# Check schema version
Get-ADObject (Get-ADRootDSE).schemaNamingContext -Property objectVersion
```

---

## 📊 FSMO Health Checks

### Daily Monitoring Script
```powershell
# FSMO Health Check Script
$Forest = Get-ADForest
$Domain = Get-ADDomain

Write-Host "=== FSMO ROLE HOLDERS ===" -ForegroundColor Cyan
Write-Host "Schema Master: $($Forest.SchemaMaster)" -ForegroundColor $(if (Test-Connection $Forest.SchemaMaster -Count 1 -Quiet) {"Green"} else {"Red"})
Write-Host "Domain Naming Master: $($Forest.DomainNamingMaster)" -ForegroundColor $(if (Test-Connection $Forest.DomainNamingMaster -Count 1 -Quiet) {"Green"} else {"Red"})
Write-Host "PDC Emulator: $($Domain.PDCEmulator)" -ForegroundColor $(if (Test-Connection $Domain.PDCEmulator -Count 1 -Quiet) {"Green"} else {"Red"})
Write-Host "RID Master: $($Domain.RIDMaster)" -ForegroundColor $(if (Test-Connection $Domain.RIDMaster -Count 1 -Quiet) {"Green"} else {"Red"})
Write-Host "Infrastructure Master: $($Domain.InfrastructureMaster)" -ForegroundColor $(if (Test-Connection $Domain.InfrastructureMaster -Count 1 -Quiet) {"Green"} else {"Red"})

# Check FSMO connectivity
$FSMOServers = @($Forest.SchemaMaster, $Forest.DomainNamingMaster, $Domain.PDCEmulator, $Domain.RIDMaster, $Domain.InfrastructureMaster) | Select-Object -Unique

foreach ($Server in $FSMOServers) {
    $Result = Test-Connection -ComputerName $Server -Count 1 -Quiet
    if (-not $Result) {
        Write-Host "⚠ WARNING: Cannot reach $Server" -ForegroundColor Red
    }
}
```

### FSMO Diagnostic Commands
```powershell
# Comprehensive FSMO diagnostics
dcdiag /test:fsmocheck
dcdiag /test:knowns ofroleholders

# Replication status
repadmin /showrepl

# FSMO-specific tests
dcdiag /test:ridmanager /v
dcdiag /test:systemlog /v
```

---

## ✅ Best Practices

### Placement:
- ✅ Keep PDC Emulator on most reliable, performant DC
- ✅ PDC should have best network connectivity
- ✅ Infrastructure Master should NOT be on Global Catalog (unless all DCs are GCs)
- ✅ Consider placing all 5 roles on same DC in small environments (<5 DCs)
- ✅ Distribute roles in large environments for load balancing

### Operations:
- ✅ Always TRANSFER roles when possible (don't seize unless emergency)
- ✅ Document current role holders
- ✅ Monitor FSMO holder availability
- ✅ Transfer roles off DC before maintenance
- ✅ Perform metadata cleanup after seizing roles

### Disaster Recovery:
- ✅ Maintain at least 2 DCs per domain
- ✅ Regular AD backups (System State)
- ✅ Document FSMO transfer procedures
- ✅ Practice FSMO seizure in lab environment
- ✅ Monitor replication health daily

### Security:
- ✅ Limit who can transfer/seize FSMO roles (Domain/Enterprise Admins)
- ✅ Audit FSMO role changes
- ✅ Protect FSMO role holders with AV, patching, monitoring
- ✅ Separate FSMO roles from resource-intensive roles if possible

---

## 📝 FSMO Operations Checklist

### Before Transferring Roles:
- [ ] Verify target DC is healthy and replicating
- [ ] Check target DC has sufficient resources
- [ ] Document current role holders
- [ ] Notify team of planned change
- [ ] Schedule during maintenance window
- [ ] Ensure target DC has network connectivity

### Transfer Process:
- [ ] Verify replication is current
- [ ] Transfer roles using PowerShell or GUI
- [ ] Verify roles moved successfully
- [ ] Test affected services (time sync, GP, user creation)
- [ ] Force replication across all DCs
- [ ] Update documentation

### After Transfer:
- [ ] Run dcdiag /test:fsmocheck
- [ ] Verify replication with repadmin /showrepl
- [ ] Test user/group creation (RID Master)
- [ ] Test GPO updates (PDC Emulator)
- [ ] Monitor for 24-48 hours

### Emergency Seizure (Disaster Recovery):
- [ ] Confirm original DC is permanently offline
- [ ] Seize roles to healthy DC
- [ ] Perform metadata cleanup
- [ ] Clean DNS records
- [ ] Force AD replication
- [ ] Verify all services operational
- [ ] Document incident
- [ ] Plan for rebuilding failed DC (if applicable)

---

## 🎯 Quick Reference

```powershell
# View all roles
Get-ADForest | Select SchemaMaster, DomainNamingMaster
Get-ADDomain | Select PDCEmulator, RIDMaster, InfrastructureMaster

# Transfer all roles
Move-ADDirectoryServerOperationMasterRole -Identity "DC02" `
    -OperationMasterRole PDCEmulator,RIDMaster,InfrastructureMaster,SchemaMaster,DomainNamingMaster

# Seize all roles (emergency)
Move-ADDirectoryServerOperationMasterRole -Identity "DC02" `
    -OperationMasterRole PDCEmulator,RIDMaster,InfrastructureMaster,SchemaMaster,DomainNamingMaster -Force

# Health check
dcdiag /test:fsmocheck
repadmin /showrepl
```
'''
        })

        # ============================================================
        # NETWORKING (3 articles)
        # ============================================================

        articles.append({
            'category': 'Network Troubleshooting',
            'title': 'How to Configure VLANs on Cisco Switches',
            'body': r'''# Configure VLANs on Cisco Switches

## Overview
Virtual LANs (VLANs) segment network traffic to improve security, performance, and management. This guide covers VLAN configuration on Cisco switches.

## Prerequisites
- Console or SSH access to Cisco switch
- Enable mode password
- Basic understanding of network topology

---

## Basic VLAN Configuration

### Step 1: Create VLANs

```cisco
Switch> enable
Switch# configure terminal
Switch(config)# vlan 10
Switch(config-vlan)# name MANAGEMENT
Switch(config-vlan)# exit

Switch(config)# vlan 20
Switch(config-vlan)# name USERS
Switch(config-vlan)# exit

Switch(config)# vlan 30
Switch(config-vlan)# name SERVERS
Switch(config-vlan)# exit

Switch(config)# vlan 40
Switch(config-vlan)# name GUEST_WIFI
Switch(config-vlan)# exit
```

### Step 2: Assign Ports to VLANs

**Access Port (single VLAN):**
```cisco
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 20
Switch(config-if)# description User Workstation
Switch(config-if)# exit
```

**Trunk Port (multiple VLANs):**
```cisco
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 10,20,30,40
Switch(config-if)# description Uplink to Router
Switch(config-if)# exit
```

### Step 3: Configure Native VLAN (optional)

```cisco
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport trunk native vlan 10
Switch(config-if)# exit
```

---

## Advanced Configuration

### Voice VLAN for IP Phones

```cisco
Switch(config)# vlan 50
Switch(config-vlan)# name VOICE
Switch(config-vlan)# exit

Switch(config)# interface range GigabitEthernet0/1-12
Switch(config-if-range)# switchport mode access
Switch(config-if-range)# switchport access vlan 20
Switch(config-if-range)# switchport voice vlan 50
Switch(config-if-range)# exit
```

### Port Security on Access Ports

```cisco
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport port-security
Switch(config-if)# switchport port-security maximum 2
Switch(config-if)# switchport port-security violation restrict
Switch(config-if)# switchport port-security mac-address sticky
Switch(config-if)# exit
```

---

## Verification Commands

```cisco
# Show all VLANs
Switch# show vlan brief

# Show VLAN details
Switch# show vlan id 20

# Show trunk ports
Switch# show interfaces trunk

# Show specific interface
Switch# show interface GigabitEthernet0/1 switchport

# Show running config
Switch# show running-config
```

---

## Common VLAN Architectures

### Small Office (4 VLANs):
- **VLAN 10 (Management)**: Switch management IPs
- **VLAN 20 (Users)**: Employee workstations
- **VLAN 30 (Servers)**: Internal servers
- **VLAN 40 (Guest)**: Guest WiFi network

### Enterprise (8+ VLANs):
- **VLAN 10 (Management)**
- **VLAN 20 (Executives)**
- **VLAN 30 (Staff)**
- **VLAN 40 (Servers)**
- **VLAN 50 (Voice)**
- **VLAN 60 (Printers)**
- **VLAN 70 (Guest)**
- **VLAN 80 (IoT)**

---

## Troubleshooting

### Problem: Device can't communicate across VLANs
**Solution**: Configure inter-VLAN routing on Layer 3 switch or router.

```cisco
# On Layer 3 switch:
Switch(config)# ip routing
Switch(config)# interface vlan 20
Switch(config-if)# ip address 192.168.20.1 255.255.255.0
Switch(config-if)# no shutdown
Switch(config-if)# exit
```

### Problem: Trunk not passing traffic
**Solution**: Verify allowed VLANs and native VLAN match on both ends.

```cisco
Switch# show interfaces GigabitEthernet0/24 trunk
```

### Problem: Port shows in wrong VLAN
**Solution**: Check port assignment and mode.

```cisco
Switch# show interfaces GigabitEthernet0/1 switchport
```

---

## Best Practices

- **Document VLAN assignments** in network diagrams
- **Use consistent VLAN IDs** across all switches
- **Avoid using VLAN 1** for user traffic (security)
- **Use descriptive VLAN names**
- **Limit trunk ports** to only necessary VLANs
- **Configure native VLAN** on trunks (non-default)
- **Enable port security** on access ports
- **Backup configuration** after changes

---

## Save Configuration

```cisco
Switch# write memory
# OR
Switch# copy running-config startup-config
```
'''
        })

        articles.append({
            'category': 'Network Troubleshooting',
            'title': 'Troubleshooting Network Connectivity Issues',
            'body': r'''# Troubleshooting Network Connectivity Issues

## Overview
Systematic approach to diagnosing and resolving network connectivity problems using proven troubleshooting methodologies.

## Quick Diagnostic Flowchart

```
1. Physical Layer → 2. IP Configuration → 3. Default Gateway → 4. DNS Resolution → 5. Firewall/Security
```

---

## Step 1: Verify Physical Connectivity

### Check Cable/WiFi Connection

**Windows:**
```cmd
# Check network adapter status
ipconfig /all
netsh interface show interface

# Test cable connection
Get-NetAdapter | Select Name, Status, LinkSpeed
```

**Linux:**
```bash
# Check network interfaces
ip link show
ifconfig

# Check cable status
ethtool eth0
```

**What to look for:**
- Link light on network port (green = good, amber = issue, off = no connection)
- WiFi signal strength (should be > -70 dBm)
- Correct speed/duplex (1000 Mbps full-duplex for gigabit)

---

## Step 2: Verify IP Configuration

### Check IP Address

**Windows:**
```cmd
ipconfig /all
```

**Linux:**
```bash
ip addr show
# OR
ifconfig
```

### Common Issues:

**Problem: APIPA address (169.254.x.x)**
- Indicates DHCP server not reachable
- Solution: Check DHCP server, network cable, switch port

**Problem: Wrong subnet**
- Device on different subnet than gateway
- Solution: Renew DHCP or configure static IP correctly

**Problem: Duplicate IP**
- Another device using same IP address
- Solution: Release/renew DHCP or change static IP

### Renew IP Address

**Windows:**
```cmd
ipconfig /release
ipconfig /renew
ipconfig /flushdns
```

**Linux:**
```bash
sudo dhclient -r
sudo dhclient
# OR
sudo systemctl restart NetworkManager
```

---

## Step 3: Test Default Gateway

### Ping Default Gateway

**Windows:**
```cmd
# Find gateway
ipconfig | findstr "Default Gateway"

# Ping gateway
ping 192.168.1.1
```

**Linux:**
```bash
# Find gateway
ip route show
# OR
route -n

# Ping gateway
ping -c 4 192.168.1.1
```

### Analyze Results:

**Success (Reply from gateway):**
```
Reply from 192.168.1.1: bytes=32 time=1ms TTL=64
```
→ Gateway reachable, proceed to DNS testing

**Request Timed Out:**
```
Request timed out.
```
→ Gateway unreachable, check routing table or switch configuration

**Destination Host Unreachable:**
```
Reply from 192.168.1.50: Destination host unreachable.
```
→ No route to gateway, check IP configuration

---

## Step 4: Test DNS Resolution

### Test DNS Lookup

**Windows:**
```cmd
nslookup google.com

# Test specific DNS server
nslookup google.com 8.8.8.8
```

**Linux:**
```bash
dig google.com

# Test specific DNS server
dig @8.8.8.8 google.com

# OR
nslookup google.com
```

### Common DNS Issues:

**Problem: DNS server not responding**
```cmd
# Windows: Change DNS servers
netsh interface ip set dns "Ethernet" static 8.8.8.8
netsh interface ip add dns "Ethernet" 8.8.4.4 index=2
```

```bash
# Linux: Edit /etc/resolv.conf
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
echo "nameserver 8.8.4.4" | sudo tee -a /etc/resolv.conf
```

**Problem: DNS cache corruption**
```cmd
# Windows: Flush DNS cache
ipconfig /flushdns

# Linux: Flush DNS cache
sudo systemd-resolve --flush-caches
# OR
sudo /etc/init.d/nscd restart
```

---

## Step 5: Test Internet Connectivity

### Ping External IPs

```cmd
# Google DNS
ping 8.8.8.8

# Cloudflare DNS
ping 1.1.1.1
```

**If IP works but domain names don't:**
→ DNS issue (see Step 4)

**If neither works:**
→ Gateway/routing issue or ISP problem

### Traceroute to Find Where Traffic Stops

**Windows:**
```cmd
tracert google.com
```

**Linux:**
```bash
traceroute google.com
```

Analyze output to see where packets stop reaching.

---

## Step 6: Check Firewall/Security

### Windows Firewall

```cmd
# Check firewall status
netsh advfirewall show allprofiles

# Temporarily disable (testing only!)
netsh advfirewall set allprofiles state off

# Re-enable
netsh advfirewall set allprofiles state on
```

### Linux Firewall (iptables/firewalld)

```bash
# Check firewall status
sudo iptables -L -n
# OR
sudo firewall-cmd --list-all

# Temporarily disable (testing only!)
sudo systemctl stop firewalld
```

---

## Advanced Diagnostics

### Port Connectivity Testing

**Windows (PowerShell):**
```powershell
Test-NetConnection -ComputerName google.com -Port 443
Test-NetConnection -ComputerName 192.168.1.10 -Port 3389
```

**Linux:**
```bash
# Telnet method
telnet google.com 443

# Netcat method
nc -zv google.com 443

# Nmap method
nmap -p 443 google.com
```

### Check Routing Table

**Windows:**
```cmd
route print
```

**Linux:**
```bash
ip route show
# OR
netstat -rn
```

### Network Statistics

**Windows:**
```cmd
netstat -an
netstat -e
```

**Linux:**
```bash
netstat -tuln
ss -tuln
```

---

## Common Scenarios & Solutions

### Scenario 1: "Internet was working, now it's not"
1. Restart device
2. Renew DHCP (ipconfig /renew)
3. Restart router/modem
4. Check for ISP outage
5. Verify cables not unplugged

### Scenario 2: "Can ping IP but not domain names"
→ DNS issue
1. Flush DNS cache
2. Change DNS servers to 8.8.8.8 / 8.8.4.4
3. Restart DNS Client service (Windows)

### Scenario 3: "WiFi connected but no internet"
→ Usually DNS or gateway issue
1. Forget and reconnect to WiFi
2. Restart WiFi router
3. Check router has internet (plug in directly)
4. Renew DHCP lease

### Scenario 4: "Slow network performance"
1. Run speed test (speedtest.net)
2. Check for bandwidth-heavy applications
3. Verify full-duplex on switch (not half-duplex)
4. Check for network loops
5. Update network drivers

---

## Troubleshooting Checklist

- [ ] Physical cable/WiFi connected
- [ ] Network adapter enabled
- [ ] Valid IP address (not 169.254.x.x)
- [ ] Correct subnet mask
- [ ] Default gateway configured and reachable
- [ ] DNS servers configured
- [ ] Can ping default gateway
- [ ] Can ping external IP (8.8.8.8)
- [ ] Can resolve domain names
- [ ] Firewall not blocking traffic
- [ ] No IP conflicts
- [ ] Network drivers up to date

---

## Quick Commands Reference

| Task | Windows | Linux |
|------|---------|-------|
| Show IP | `ipconfig` | `ip addr` |
| Renew DHCP | `ipconfig /renew` | `dhclient` |
| Ping | `ping 8.8.8.8` | `ping 8.8.8.8` |
| Traceroute | `tracert google.com` | `traceroute google.com` |
| DNS lookup | `nslookup google.com` | `dig google.com` |
| Show routes | `route print` | `ip route` |
| Flush DNS | `ipconfig /flushdns` | `systemd-resolve --flush-caches` |
'''
        })

        articles.append({
            'category': 'Network Troubleshooting',
            'title': 'Setting Up DHCP Server on Windows Server',
            'body': r'''# Setting Up DHCP Server on Windows Server

## Overview
Dynamic Host Configuration Protocol (DHCP) automatically assigns IP addresses and network configuration to clients. This guide covers DHCP server installation and configuration on Windows Server.

## Prerequisites
- Windows Server 2016/2019/2022
- Administrator access
- Static IP address assigned to server
- Authorized in Active Directory (if domain environment)

---

## Step 1: Install DHCP Server Role

### Using Server Manager:

1. Open **Server Manager**
2. Click **Manage** → **Add Roles and Features**
3. Click **Next** through "Before You Begin"
4. Select **Role-based or feature-based installation**
5. Select your server from the server pool
6. Check **DHCP Server**
7. Click **Add Features** when prompted
8. Click **Next** through features
9. Click **Install**
10. Wait for installation to complete

### Using PowerShell:

```powershell
# Install DHCP Server role
Install-WindowsFeature DHCP -IncludeManagementTools

# Restart server if required
Restart-Computer -Force
```

---

## Step 2: Authorize DHCP Server (Domain Only)

**Important:** In Active Directory environments, DHCP servers must be authorized.

### Using DHCP Manager:

1. Open **DHCP** from Server Manager or Administrative Tools
2. Right-click server name → **Authorize**
3. Refresh to verify green arrow appears

### Using PowerShell:

```powershell
# Authorize DHCP server in AD
Add-DhcpServerInDC -DnsName "dhcp01.contoso.com" -IPAddress 192.168.1.10

# Verify authorization
Get-DhcpServerInDC
```

---

## Step 3: Configure DHCP Scope

### Create New Scope:

1. Open **DHCP Manager**
2. Expand server name → Right-click **IPv4** → **New Scope**
3. Click **Next** on Welcome screen

### Configure Scope:

**Name and Description:**
- Name: `Internal Network` or `VLAN 10 - Users`
- Description: `Primary user workstation DHCP scope`

**IP Address Range:**
- Start IP: `192.168.1.100`
- End IP: `192.168.1.200`
- Length: `24` (255.255.255.0)
- Subnet mask: `255.255.255.0`

**Exclusions (optional):**
- Add IP ranges reserved for static assignments
- Example: `192.168.1.1` to `192.168.1.50` (servers/printers)

**Lease Duration:**
- Default: `8 days`
- Typical: `8 hours` (offices) or `1 hour` (guest WiFi)

**Configure DHCP Options: Yes**

**Router (Default Gateway):**
- Enter: `192.168.1.1`

**DNS Servers:**
- Primary: `192.168.1.10`
- Secondary: `8.8.8.8` (optional)

**WINS Servers:**
- Usually leave blank (legacy)

**Activate Scope: Yes**

### Using PowerShell:

```powershell
# Create DHCP scope
Add-DhcpServerv4Scope `
    -Name "Internal Network" `
    -StartRange 192.168.1.100 `
    -EndRange 192.168.1.200 `
    -SubnetMask 255.255.255.0 `
    -State Active

# Add exclusion range
Add-DhcpServerv4ExclusionRange `
    -ScopeId 192.168.1.0 `
    -StartRange 192.168.1.1 `
    -EndRange 192.168.1.50

# Set default gateway
Set-DhcpServerv4OptionValue `
    -ScopeId 192.168.1.0 `
    -Router 192.168.1.1

# Set DNS servers
Set-DhcpServerv4OptionValue `
    -ScopeId 192.168.1.0 `
    -DnsServer 192.168.1.10,8.8.8.8

# Set lease duration (8 hours)
Set-DhcpServerv4Scope `
    -ScopeId 192.168.1.0 `
    -LeaseDuration 08:00:00
```

---

## Step 4: Configure Server-Level Options

These apply to ALL scopes unless overridden.

### Using DHCP Manager:

1. Right-click **Server Options** → **Configure Options**
2. Configure:
   - **003 Router**: Default gateway
   - **006 DNS Servers**: DNS server IPs
   - **015 DNS Domain Name**: `contoso.com`
   - **042 NTP Servers**: Time server IPs (optional)

### Using PowerShell:

```powershell
# Set server-wide DNS domain
Set-DhcpServerv4OptionValue `
    -DnsDomain "contoso.com"

# Set NTP servers
Set-DhcpServerv4OptionValue `
    -OptionId 042 `
    -Value 192.168.1.10
```

---

## Step 5: Configure DHCP Failover (Optional)

High availability with two DHCP servers.

### Using DHCP Manager:

1. Right-click scope → **Configure Failover**
2. Select partner server
3. Choose mode:
   - **Load Balance**: Both servers active (50/50 split)
   - **Hot Standby**: Primary active, secondary standby
4. Configure shared secret for authentication
5. Click **Finish**

### Using PowerShell:

```powershell
# Add failover relationship
Add-DhcpServerv4Failover `
    -Name "DHCP-Failover" `
    -PartnerServer "dhcp02.contoso.com" `
    -ScopeId 192.168.1.0 `
    -LoadBalancePercent 50 `
    -SharedSecret "MySecretKey123" `
    -Force
```

---

## Step 6: Configure DHCP Policies (Advanced)

Assign different settings based on MAC address, vendor class, or user class.

### Example: Give specific MAC address a reserved IP:

```powershell
Add-DhcpServerv4Reservation `
    -ScopeId 192.168.1.0 `
    -IPAddress 192.168.1.150 `
    -ClientId "00-15-5D-01-02-03" `
    -Description "Printer - Accounting Floor 2"
```

### Example: Policy for VoIP phones:

```powershell
Add-DhcpServerv4Policy `
    -Name "VoIP Phones" `
    -ScopeId 192.168.1.0 `
    -Condition OR `
    -VendorClass EQ,"Cisco*"

Set-DhcpServerv4OptionValue `
    -ScopeId 192.168.1.0 `
    -PolicyName "VoIP Phones" `
    -OptionId 150 `
    -Value 192.168.1.20  # TFTP server for phone firmware
```

---

## Management & Monitoring

### View Active Leases:

```powershell
Get-DhcpServerv4Lease -ScopeId 192.168.1.0

# Export leases to CSV
Get-DhcpServerv4Lease -ScopeId 192.168.1.0 |
    Export-Csv C:\DHCP-Leases.csv -NoTypeInformation
```

### View Scope Statistics:

```powershell
Get-DhcpServerv4ScopeStatistics

# Example output shows:
# - Total addresses in scope
# - In use
# - Available
# - Percentage used
```

### Clear Old Leases:

```powershell
# Remove expired leases older than 30 days
Remove-DhcpServerv4Lease -ScopeId 192.168.1.0 -BadLeases
```

---

## Backup & Restore

### Automatic Backup:

DHCP automatically backs up to:
```
C:\Windows\System32\dhcp\backup
```

### Manual Backup:

```powershell
Backup-DhcpServer -Path "D:\DHCP-Backup" -ComputerName dhcp01.contoso.com
```

### Restore from Backup:

```powershell
Restore-DhcpServer -Path "D:\DHCP-Backup" -ComputerName dhcp01.contoso.com
```

---

## Troubleshooting

### Problem: Clients not getting IP addresses

**Check:**
```powershell
# Verify DHCP service running
Get-Service DHCPServer

# Start if stopped
Start-Service DHCPServer

# Check firewall allows DHCP (UDP 67, 68)
Get-NetFirewallRule -DisplayName "*DHCP*"

# Verify scope is activated
Get-DhcpServerv4Scope | Where-Object {$_.State -eq "Active"}

# Check available IPs
Get-DhcpServerv4ScopeStatistics
```

### Problem: DHCP server shows red arrow in manager

→ Not authorized in Active Directory

```powershell
Add-DhcpServerInDC -DnsName "dhcp01.contoso.com"
```

### Problem: Duplicate IP addresses on network

**Enable conflict detection:**

```powershell
Set-DhcpServerv4 Setting -ConflictDetectionAttempts 2
```

DHCP will ping IP before assigning to detect conflicts.

---

## Best Practices

- **Use 80/20 rule for failover**: Primary server handles 80%, secondary 20%
- **Set appropriate lease times**:
  - Offices: 8-24 hours
  - Guest WiFi: 1-2 hours
  - Data centers: 8 days
- **Document exclusions**: Reserve ranges for servers, printers, network devices
- **Enable audit logging**: Track all DHCP transactions
- **Monitor scope utilization**: Alert when >85% full
- **Regular backups**: Automate DHCP database backups
- **Use reservations for servers**: Instead of pure static IPs
- **Configure failover**: For redundancy in production

---

## Security Considerations

### Enable DHCP Logging:

```powershell
Set-DhcpServerAuditLog -Enable $true -Path "C:\Windows\System32\dhcp"
```

### Configure NAP Integration (if used):

Network Access Protection can enforce health policies on DHCP clients.

### Limit DHCP Server Access:

Only Domain Admins and DHCP Admins groups should manage DHCP.

---

## Quick Reference

```powershell
# View all scopes
Get-DhcpServerv4Scope

# View scope details
Get-DhcpServerv4Scope -ScopeId 192.168.1.0

# View all leases
Get-DhcpServerv4Lease -ScopeId 192.168.1.0

# View reservations
Get-DhcpServerv4Reservation -ScopeId 192.168.1.0

# View server statistics
Get-DhcpServerv4Statistics

# Backup DHCP
Backup-DhcpServer -Path "D:\Backup"

# Restart DHCP service
Restart-Service DHCPServer
```
'''
        })

        # ============================================================
        # SECURITY (2 articles)
        # ============================================================

        articles.append({
            'category': 'Security & Compliance',
            'title': 'Implementing Multi-Factor Authentication (MFA)',
            'body': r'''# Implementing Multi-Factor Authentication (MFA)

## Overview
Multi-Factor Authentication (MFA) adds an additional layer of security beyond passwords by requiring users to verify their identity using a second factor such as a mobile app, SMS, or hardware token.

## Why MFA is Critical

**Statistics:**
- 99.9% of account compromise attacks can be blocked by MFA (Microsoft)
- 80% of data breaches involve stolen or weak passwords
- Average cost of data breach: $4.35 million (IBM)

**Compliance Requirements:**
- Required by: HIPAA, PCI-DSS, CMMC, Cyber Insurance
- Recommended by: NIST, CISA, FBI

---

## MFA Methods Comparison

| Method | Security | User Experience | Cost | Best For |
|--------|----------|-----------------|------|----------|
| **Authenticator App** | High | Good | Free | Most users |
| **SMS/Text** | Medium | Excellent | Low | Non-technical users |
| **Hardware Token** | Very High | Good | $20-50/user | High-security roles |
| **Biometric** | High | Excellent | Device-dependent | Modern devices |
| **Backup Codes** | Medium | Poor | Free | Recovery only |

**Recommendation:** Authenticator app as primary, SMS as backup

---

## Implementation Roadmap

### Phase 1: Planning (Week 1-2)
- [ ] Identify user groups and prioritization
- [ ] Choose MFA solution(s)
- [ ] Document enrollment process
- [ ] Plan communication strategy
- [ ] Set up test environment

### Phase 2: Pilot (Week 3-4)
- [ ] Enable MFA for IT team
- [ ] Test all authentication scenarios
- [ ] Document issues and resolutions
- [ ] Refine enrollment process
- [ ] Create user guides

### Phase 3: Rollout (Week 5-8)
- [ ] Enable for executives and high-privilege accounts
- [ ] Enable for all employees (phased)
- [ ] Provide help desk training
- [ ] Monitor adoption rates
- [ ] Address user issues promptly

### Phase 4: Enforcement (Week 9+)
- [ ] Make MFA mandatory for all users
- [ ] Disable legacy authentication protocols
- [ ] Regular compliance audits
- [ ] Update security policies

---

## Microsoft 365 / Azure AD MFA

### Enable MFA for All Users

**Method 1: Security Defaults (Simplest)**

1. Sign in to **Azure AD admin center** (aad.portal.azure.com)
2. Navigate to **Azure Active Directory** → **Properties**
3. Click **Manage Security defaults**
4. Set **Enable Security defaults** to **Yes**
5. Click **Save**

**What this enables:**
- MFA for all users (including admins)
- Blocks legacy authentication
- Requires MFA when risk detected

**Method 2: Conditional Access Policies (Recommended)**

1. Navigate to **Azure AD** → **Security** → **Conditional Access**
2. Click **New policy**
3. Configure:

**Name:** `Require MFA for All Users`

**Assignments:**
- Users: `All users` (exclude break-glass account)
- Cloud apps: `All cloud apps`
- Conditions:
  - Locations: `Any location` except trusted IPs (optional)

**Access controls:**
- Grant: `Grant access`
- Require: `Require multi-factor authentication`

4. Enable policy: **On**
5. Click **Create**

### Register MFA Methods

**Users register MFA at:**
https://aka.ms/mfasetup

**Admin-initiated registration:**
1. Go to **Azure AD** → **Users** → Select user
2. Click **Authentication methods**
3. Click **Require re-register MFA**

### Configure MFA Settings

**Available methods:**
```
Azure AD > Security > MFA > Additional cloud-based settings

Enable:
☑ Microsoft Authenticator (recommended)
☑ Authenticator app codes (TOTP)
☐ SMS (consider disabling for better security)
☑ Phone call (for backup)
```

---

## Google Workspace MFA

### Enable 2-Step Verification

1. Sign in to **Google Admin console** (admin.google.com)
2. Go to **Security** → **Authentication** → **2-Step Verification**
3. Click **Get Started**
4. Check **Allow users to turn on 2-Step Verification**
5. **Enforcement:** Select organizational unit
   - Choose: `New user enrollment period` = 1 week
   - Then: `Mandatory for all users`
6. Click **Save**

### Recommended Settings

```
Security > 2-Step Verification:

☑ Allow users to use Google Authenticator
☑ Allow users to use security keys
☑ Allow users to use Google prompts
☐ Allow users to use SMS (disable for better security)
☑ Allow users to use backup codes
☑ Enforce in 7 days (grace period)
```

---

## On-Premises Active Directory MFA

### Option 1: Azure MFA Server (Legacy)

**Note:** Azure MFA Server is deprecated. Migrate to Azure AD + Conditional Access.

### Option 2: Duo Security (Recommended)

1. **Sign up for Duo** (duo.com)
2. **Install Duo Authentication Proxy** on server:

```powershell
# Download and install Duo proxy
Invoke-WebRequest -Uri "https://dl.duosecurity.com/duoauthproxy-latest.exe" -OutFile "duo-installer.exe"
.\duo-installer.exe

# Configure authproxy.cfg
@"
[main]
debug=true

[ad_client]
host=dc01.contoso.local
service_account_username=duo_service@contoso.local
service_account_password=YourSecurePassword
search_dn=DC=contoso,DC=local

[duo-only-client]
host=127.0.0.1
port=1812
secret=YourRadiusSecret
integration_key=YourIntegrationKey
secret_key=YourSecretKey
api_host=api-XXXXX.duosecurity.com
"@ | Out-File "C:\Program Files\Duo Security Authentication Proxy\conf\authproxy.cfg"

# Start Duo service
Start-Service DuoAuthProxy
```

3. **Configure VPN/RDP to use Duo RADIUS**
4. **Test with pilot users**

---

## Hardware Token Implementation

### YubiKey Setup

1. **Purchase YubiKeys** (5-10 per user for redundancy)
2. **Enroll in Azure AD:**

```powershell
# Users register at:
https://aka.ms/mysecurityinfo

# Insert YubiKey and tap when prompted
```

3. **Enroll in Google Workspace:**
```
Admin console > Security > 2-Step Verification > Security Keys
Users: My Account > Security > 2-Step Verification > Add security key
```

4. **Best Practices:**
- Issue 2 YubiKeys per user (primary + backup)
- Store backup YubiKey securely
- Document serial numbers
- Test before distributing

---

## Help Desk Procedures

### MFA Reset Process

**Microsoft 365:**
```powershell
# Admin resets MFA for user
Connect-MsolService
Set-MsolUser -UserPrincipalName user@contoso.com -StrongAuthenticationMethods @()

# User re-registers at:
https://aka.ms/mfasetup
```

**Google Workspace:**
```
Admin console > Users > Select user > Security >
Click "2-Step Verification" > Revoke all 2SV methods
```

### Common User Issues

**"I lost my phone"**
1. Verify user identity (multi-factor verification!)
2. Reset MFA registration
3. User re-registers with new device
4. Issue backup codes

**"MFA app not working"**
1. Check time sync on device (critical for TOTP)
2. Remove and re-add account in app
3. Use backup method (SMS, phone call)

**"Authenticator app showing wrong code"**
1. Sync time on device:
   - iOS: Settings > General > Date & Time > Set Automatically
   - Android: Settings > System > Date & Time > Automatic
2. Re-generate codes in app

---

## Monitoring & Reporting

### Azure AD Sign-In Logs

```
Azure AD > Sign-in logs > Filter:

- Authentication requirement: MFA
- Status: Success / Failure
- Date range: Last 7 days
```

### MFA Adoption Report

```powershell
# Connect to Azure AD
Connect-MsolService

# Get MFA status for all users
Get-MsolUser -All | Select DisplayName, UserPrincipalName,
    @{Name="MFA Status";Expression={$_.StrongAuthenticationRequirements.State}}
```

### Google Workspace MFA Report

```
Admin console > Reports > User reports >
Accounts > 2-Step Verification enrollment
```

---

## Security Best Practices

### Do:
- ✅ **Enforce MFA for all admins immediately**
- ✅ **Use authenticator apps over SMS**
- ✅ **Maintain 2+ break-glass admin accounts** (no MFA, secured differently)
- ✅ **Provide backup authentication methods**
- ✅ **Monitor MFA bypass attempts**
- ✅ **Regular security awareness training**
- ✅ **Test MFA recovery procedures**

### Don't:
- ❌ **Don't rely solely on SMS** (SIM swapping attacks)
- ❌ **Don't skip MFA for "low-risk" accounts** (lateral movement)
- ❌ **Don't allow permanent MFA bypass**
- ❌ **Don't forget break-glass accounts** (lockout risk)
- ❌ **Don't neglect service accounts** (use managed identities)

---

## Regulatory Compliance

### NIST SP 800-63B Requirements:
- Authenticator must be "something you have" (device/token)
- SMS is NOT recommended (phishing risk)
- Biometric + PIN acceptable

### PCI-DSS 3.2 Requirements:
- MFA required for all access to cardholder data environment (CDE)
- Must use 2 of 3 factors: knowledge, possession, inherence

### HIPAA Requirements:
- MFA recommended (not explicitly required)
- Part of "access controls" safeguard
- Required by most cyber insurance policies

---

## ROI & Business Case

### Cost Savings:
- **Prevent breaches**: Average breach cost $4.35M
- **Reduce help desk calls**: 30-50% reduction in password resets
- **Cyber insurance discount**: 10-20% premium reduction
- **Compliance fines avoided**: Varies by regulation

### Implementation Costs:
- **Microsoft 365**: Included with most licenses
- **Google Workspace**: Included (free)
- **Duo Security**: $3-9/user/month
- **YubiKeys**: $25-50/user (one-time)
- **Staff time**: 40-80 hours for 100 users

### Typical ROI:
MFA pays for itself within first prevented incident.

---

## Quick Reference

| Platform | Enable MFA | User Registration | Admin Reset |
|----------|-----------|-------------------|-------------|
| **Microsoft 365** | Security defaults or Conditional Access | aka.ms/mfasetup | `Set-MsolUser -UserPrincipalName user@domain.com -StrongAuthenticationMethods @()` |
| **Google Workspace** | Admin console > Security > 2SV | myaccount.google.com > Security | Admin console > Users > Security > Revoke 2SV |
| **Duo** | Application settings > Enable Duo | First login after enablement | Duo Admin > Users > Reset |

---

## Next Steps

1. **Week 1**: Enable MFA for all admin accounts
2. **Week 2-3**: Pilot with IT team
3. **Week 4-6**: Roll out to all users (phased)
4. **Week 7**: Enforce MFA for all accounts
5. **Week 8+**: Monitor, audit, refine
'''
        })

        articles.append({
            'category': 'Security & Compliance',
            'title': 'Configuring Windows Firewall Rules',
            'body': r'''# Configuring Windows Firewall Rules

## Overview
Windows Defender Firewall (Windows Firewall) is a host-based firewall included in all modern Windows operating systems. This guide covers creating, managing, and troubleshooting firewall rules.

## Firewall Basics

### Three Network Profiles:
- **Domain**: Connected to corporate domain (Active Directory)
- **Private**: Home or work networks (trusted)
- **Public**: Coffee shops, airports (untrusted)

### Rule Types:
- **Inbound**: Controls incoming connections TO this computer
- **Outbound**: Controls outgoing connections FROM this computer

### Rule Actions:
- **Allow**: Permit the connection
- **Block**: Deny the connection
- **Allow if secure**: Require IPsec authentication

---

## Managing Firewall via GUI

### Open Windows Firewall with Advanced Security

**Windows 10/11:**
1. Press `Win + R`
2. Type: `wf.msc`
3. Press Enter

**OR:**
- Control Panel → System and Security → Windows Defender Firewall → Advanced settings

### Check Firewall Status

View all three profiles (Domain, Private, Public) and verify:
- Firewall state: **On**
- Inbound connections: **Block (default)**
- Outbound connections: **Allow (default)**

---

## Creating Firewall Rules (GUI)

### Allow Inbound Port (Example: RDP on TCP 3389)

1. Open **Windows Firewall with Advanced Security** (`wf.msc`)
2. Click **Inbound Rules** in left pane
3. Click **New Rule** in right pane
4. **Rule Type**: Select `Port` → Next
5. **Protocol**: Select `TCP`
6. **Specific local ports**: Enter `3389` → Next
7. **Action**: Select `Allow the connection` → Next
8. **Profile**: Check all three (Domain, Private, Public) → Next
9. **Name**: `Allow RDP` → Finish

### Block Outbound Application

1. Click **Outbound Rules**
2. Click **New Rule**
3. **Rule Type**: Select `Program` → Next
4. **This program path**: Browse to `C:\Windows\System32\calc.exe` → Next
5. **Action**: Select `Block the connection` → Next
6. **Profile**: Check all → Next
7. **Name**: `Block Calculator` → Finish

### Allow Specific IP Address

1. Create new rule (Port or Program)
2. After selecting action, configure **Scope**:
   - **Local IP**: `Any IP address` OR specify
   - **Remote IP**: `These IP addresses`
   - Click **Add** → Enter `192.168.1.50`

---

## Managing Firewall via PowerShell (Recommended)

### View Firewall Status

```powershell
# Check firewall state for all profiles
Get-NetFirewallProfile | Select Name, Enabled

# View detailed firewall settings
Get-NetFirewallProfile | Format-List Name, Enabled, DefaultInboundAction, DefaultOutboundAction
```

### Enable/Disable Firewall

```powershell
# Enable firewall for all profiles
Set-NetFirewallProfile -All -Enabled True

# Disable firewall (Domain profile only)
Set-NetFirewallProfile -Profile Domain -Enabled False

# Disable all profiles (NOT RECOMMENDED)
Set-NetFirewallProfile -All -Enabled False
```

---

## Creating Rules with PowerShell

### Allow Inbound Port

```powershell
# Allow TCP port 3389 (RDP)
New-NetFirewallRule -DisplayName "Allow RDP" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 3389 `
    -Action Allow `
    -Profile Any

# Allow UDP port 53 (DNS)
New-NetFirewallRule -DisplayName "Allow DNS" `
    -Direction Inbound `
    -Protocol UDP `
    -LocalPort 53 `
    -Action Allow `
    -Enabled True
```

### Allow Inbound Port Range

```powershell
# Allow TCP ports 5000-5100
New-NetFirewallRule -DisplayName "Allow Port Range 5000-5100" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 5000-5100 `
    -Action Allow
```

### Allow Specific Program

```powershell
# Allow Google Chrome
New-NetFirewallRule -DisplayName "Allow Chrome" `
    -Direction Outbound `
    -Program "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    -Action Allow `
    -Profile Any

# Block specific application
New-NetFirewallRule -DisplayName "Block Notepad" `
    -Direction Outbound `
    -Program "C:\Windows\System32\notepad.exe" `
    -Action Block
```

### Allow Specific IP Address/Subnet

```powershell
# Allow from specific IP
New-NetFirewallRule -DisplayName "Allow from Management Server" `
    -Direction Inbound `
    -RemoteAddress 192.168.1.10 `
    -Action Allow

# Allow from subnet
New-NetFirewallRule -DisplayName "Allow from Internal Subnet" `
    -Direction Inbound `
    -RemoteAddress 192.168.1.0/24 `
    -Action Allow

# Block specific IP
New-NetFirewallRule -DisplayName "Block Malicious IP" `
    -Direction Inbound `
    -RemoteAddress 10.0.0.50 `
    -Action Block `
    -Enabled True
```

### Allow ICMP (Ping)

```powershell
# Allow ICMPv4 Echo Request (ping)
New-NetFirewallRule -DisplayName "Allow Ping (ICMPv4)" `
    -Direction Inbound `
    -Protocol ICMPv4 `
    -IcmpType 8 `
    -Action Allow

# Allow ICMPv6 Echo Request
New-NetFirewallRule -DisplayName "Allow Ping (ICMPv6)" `
    -Direction Inbound `
    -Protocol ICMPv6 `
    -IcmpType 8 `
    -Action Allow
```

---

## Managing Existing Rules

### View Rules

```powershell
# List all inbound rules
Get-NetFirewallRule -Direction Inbound | Select DisplayName, Enabled, Action

# List enabled rules only
Get-NetFirewallRule -Enabled True | Select DisplayName, Direction, Action

# Find specific rule by name
Get-NetFirewallRule -DisplayName "Allow RDP"

# Find rules for specific port
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*3389*"}
```

### Enable/Disable Rules

```powershell
# Disable rule by name
Disable-NetFirewallRule -DisplayName "Allow RDP"

# Enable rule by name
Enable-NetFirewallRule -DisplayName "Allow RDP"

# Disable all rules containing "File and Printer Sharing"
Get-NetFirewallRule -DisplayGroup "File and Printer Sharing" | Disable-NetFirewallRule
```

### Modify Existing Rule

```powershell
# Change rule to block instead of allow
Set-NetFirewallRule -DisplayName "Allow RDP" -Action Block

# Add additional port to existing rule
Set-NetFirewallRule -DisplayName "My Custom Rule" -LocalPort 80,443

# Change profile
Set-NetFirewallRule -DisplayName "Allow RDP" -Profile Domain,Private
```

### Delete Rule

```powershell
# Remove rule by name
Remove-NetFirewallRule -DisplayName "Allow RDP"

# Remove multiple rules
Get-NetFirewallRule -DisplayName "Temp*" | Remove-NetFirewallRule

# Confirm before deleting
Remove-NetFirewallRule -DisplayName "Old Rule" -Confirm
```

---

## Common Firewall Scenarios

### Scenario 1: Allow Web Server (HTTP/HTTPS)

```powershell
# Allow HTTP (port 80)
New-NetFirewallRule -DisplayName "Allow HTTP" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 80 `
    -Action Allow `
    -Profile Any

# Allow HTTPS (port 443)
New-NetFirewallRule -DisplayName "Allow HTTPS" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 443 `
    -Action Allow `
    -Profile Any
```

### Scenario 2: Allow SQL Server (TCP 1433)

```powershell
New-NetFirewallRule -DisplayName "Allow SQL Server" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 1433 `
    -Action Allow `
    -Profile Domain

# Allow SQL Browser (UDP 1434)
New-NetFirewallRule -DisplayName "Allow SQL Browser" `
    -Direction Inbound `
    -Protocol UDP `
    -LocalPort 1434 `
    -Action Allow `
    -Profile Domain
```

### Scenario 3: Allow File Sharing (SMB)

```powershell
# Enable File and Printer Sharing rule group
Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing"

# OR create manual rule for SMB (port 445)
New-NetFirewallRule -DisplayName "Allow SMB" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 445 `
    -Action Allow `
    -Profile Domain,Private
```

### Scenario 4: Allow Remote Desktop (RDP)

```powershell
# Enable built-in RDP rule
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# OR create custom rule
New-NetFirewallRule -DisplayName "Allow RDP Custom" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 3389 `
    -Action Allow `
    -Profile Any
```

### Scenario 5: Block All Except Specific IPs

```powershell
# 1. Create allow rule for specific IPs first
New-NetFirewallRule -DisplayName "Allow Management Subnet" `
    -Direction Inbound `
    -RemoteAddress 192.168.1.0/24 `
    -Action Allow `
    -Priority 100

# 2. Then block all others (lower priority)
New-NetFirewallRule -DisplayName "Block All Others" `
    -Direction Inbound `
    -Action Block `
    -Priority 200
```

---

## Group Policy Firewall Management

### Deploy Firewall Rules via GPO

1. Open **Group Policy Management Console** (gpmc.msc)
2. Create or edit GPO
3. Navigate to:
   ```
   Computer Configuration > Policies > Windows Settings >
   Security Settings > Windows Defender Firewall with Advanced Security
   ```
4. Right-click **Inbound Rules** → **New Rule**
5. Configure as needed
6. Link GPO to OU containing target computers

### Export/Import Firewall Rules

```powershell
# Export all rules to file
New-NetFirewallRule | Export-Csv "C:\firewall-rules.csv"

# OR export specific rule group
Get-NetFirewallRule -DisplayGroup "Remote Desktop" |
    Export-Clixml "C:\rdp-rules.xml"

# Import rules
Import-Clixml "C:\rdp-rules.xml" | New-NetFirewallRule
```

---

## Troubleshooting Firewall Issues

### Check if Firewall is Blocking Connection

```powershell
# Test TCP port connectivity
Test-NetConnection -ComputerName server01 -Port 3389

# Expected output if allowed:
# TcpTestSucceeded : True

# View blocked connections in firewall log
Get-Content C:\Windows\System32\LogFiles\Firewall\pfirewall.log | Select-String "DROP"
```

### Enable Firewall Logging

```powershell
# Enable logging for dropped packets
Set-NetFirewallProfile -All -LogBlocked True -LogFileName "C:\Windows\System32\LogFiles\Firewall\pfirewall.log"

# View log
Get-Content C:\Windows\System32\LogFiles\Firewall\pfirewall.log -Tail 50
```

### Temporarily Disable Firewall for Testing

```powershell
# Disable firewall (PUBLIC PROFILE ONLY - for testing)
Set-NetFirewallProfile -Profile Public -Enabled False

# ALWAYS RE-ENABLE after testing!
Set-NetFirewallProfile -Profile Public -Enabled True
```

**WARNING**: Never leave firewall disabled on production systems!

### Check Which Rule is Blocking/Allowing

```powershell
# Find rule affecting specific port
Get-NetFirewallPortFilter | Where-Object {$_.LocalPort -eq 3389} |
    Get-NetFirewallRule

# Find rule affecting specific program
Get-NetFirewallApplicationFilter |
    Where-Object {$_.Program -like "*chrome.exe"} |
    Get-NetFirewallRule
```

---

## Security Best Practices

### Do:
- ✅ **Enable firewall on all profiles** (Domain, Private, Public)
- ✅ **Use most restrictive profile** (treat unknown networks as Public)
- ✅ **Document all custom rules**
- ✅ **Regular rule audits** (remove unused rules)
- ✅ **Use rule groups** for easier management
- ✅ **Test rules before deploying** via GPO
- ✅ **Enable logging** for troubleshooting
- ✅ **Use specific ports/IPs** (not "Any" when possible)

### Don't:
- ❌ **Don't disable firewall permanently**
- ❌ **Don't allow "Any" port for outbound** (too permissive)
- ❌ **Don't forget to remove test rules**
- ❌ **Don't use duplicate rules** (create clutter)
- ❌ **Don't allow all ICMP types** (security risk)

---

## Quick Reference

```powershell
# View firewall status
Get-NetFirewallProfile

# Allow inbound port
New-NetFirewallRule -DisplayName "RuleName" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow

# Block outbound program
New-NetFirewallRule -DisplayName "BlockApp" -Direction Outbound -Program "C:\path\app.exe" -Action Block

# Allow specific IP
New-NetFirewallRule -DisplayName "AllowIP" -Direction Inbound -RemoteAddress 192.168.1.50 -Action Allow

# List all rules
Get-NetFirewallRule

# Enable rule
Enable-NetFirewallRule -DisplayName "RuleName"

# Remove rule
Remove-NetFirewallRule -DisplayName "RuleName"

# Test connection
Test-NetConnection -ComputerName server -Port 80
```

---

## Common Ports Reference

| Service | Protocol | Port | Rule Name |
|---------|----------|------|-----------|
| HTTP | TCP | 80 | Allow HTTP |
| HTTPS | TCP | 443 | Allow HTTPS |
| RDP | TCP | 3389 | Allow RDP |
| SMB | TCP | 445 | Allow File Sharing |
| SQL Server | TCP | 1433 | Allow SQL |
| DNS | UDP | 53 | Allow DNS |
| SSH | TCP | 22 | Allow SSH |
| FTP | TCP | 20, 21 | Allow FTP |
| SMTP | TCP | 25, 587 | Allow Email |
'''
        })

        # ============================================================
        # LINUX ADMINISTRATION (3 articles)
        # ============================================================

        articles.append({
            'category': 'Common Issues',
            'title': 'Linux User Management and Permissions',
            'body': r'''# Linux User Management and Permissions

## Overview
Comprehensive guide to managing users, groups, and file permissions on Linux systems (Ubuntu, CentOS, RHEL, Debian).

## User Management

### Create New User

```bash
# Create user with home directory
sudo useradd -m -s /bin/bash john

# Create user and set password immediately
sudo useradd -m -s /bin/bash jane
sudo passwd jane

# Create user with specific UID and home directory
sudo useradd -m -u 1500 -d /home/bob -s /bin/bash bob

# Create system user (no home directory, no login)
sudo useradd -r -s /usr/sbin/nologin serviceaccount
```

**Flags Explained:**
- `-m`: Create home directory
- `-s /bin/bash`: Set default shell
- `-u 1500`: Specify user ID (UID)
- `-d /home/bob`: Specify home directory path
- `-r`: Create system account
- `-g groupname`: Set primary group
- `-G group1,group2`: Add to supplementary groups

### Modify Existing User

```bash
# Change user's shell
sudo usermod -s /bin/zsh john

# Change home directory
sudo usermod -d /home/newhome -m john

# Lock user account (disable login)
sudo usermod -L john

# Unlock user account
sudo usermod -U john

# Add user to sudo group
sudo usermod -aG sudo john

# Add user to multiple groups
sudo usermod -aG wheel,developers,docker john

# Change username
sudo usermod -l newname oldname

# Set account expiration date
sudo usermod -e 2024-12-31 john
```

### Delete User

```bash
# Delete user only (keep home directory)
sudo userdel john

# Delete user and home directory
sudo userdel -r john

# Delete user, home, and mail spool
sudo userdel -rf john
```

### Set/Change Password

```bash
# Set password for user
sudo passwd john

# Force password change on next login
sudo passwd -e john

# Set password to never expire
sudo passwd -x -1 john

# Lock password (disable password login, SSH keys still work)
sudo passwd -l john

# Unlock password
sudo passwd -u john
```

---

## Group Management

### Create Group

```bash
# Create new group
sudo groupadd developers

# Create group with specific GID
sudo groupadd -g 1050 marketing

# Create system group
sudo groupadd -r appservice
```

### Add User to Group

```bash
# Add user to group (replaces existing groups - DANGEROUS!)
sudo usermod -G developers john

# Add user to group (append to existing groups - SAFE)
sudo usermod -aG developers john

# Add user to multiple groups
sudo usermod -aG developers,docker,sudo john

# Alternative: using gpasswd
sudo gpasswd -a john developers
```

### Remove User from Group

```bash
# Remove user from group
sudo gpasswd -d john developers

# Remove user from all supplementary groups
sudo usermod -G "" john
```

### Delete Group

```bash
# Delete group
sudo groupdel developers
```

### View User Groups

```bash
# Show groups for current user
groups

# Show groups for specific user
groups john

# Show detailed group info
id john

# List all groups on system
cat /etc/group

# List all members of a group
getent group developers
```

---

## File Permissions

### Understanding Permissions

```
-rwxr-xr-x 1 owner group 4096 Jan 15 10:30 filename
│││││││││││
│││││││││└─ Execute permission for others
│││││││└──  Read permission for others
││││││└───  Write permission for others
││││└────  Execute permission for group
│││└─────  Read permission for group
││└──────  Write permission for group
│└───────  Execute permission for owner
└────────  File type (- = file, d = directory, l = symlink)
```

**Permission Values:**
- `r` (read) = 4
- `w` (write) = 2
- `x` (execute) = 1

**Examples:**
- `rwx` = 7 (4+2+1)
- `rw-` = 6 (4+2)
- `r-x` = 5 (4+1)
- `r--` = 4
- `---` = 0

### Change File Permissions (chmod)

```bash
# Numeric method (recommended for scripts)
chmod 755 file.txt      # rwxr-xr-x
chmod 644 file.txt      # rw-r--r--
chmod 600 file.txt      # rw-------
chmod 700 script.sh     # rwx------ (owner only)

# Symbolic method
chmod u+x file.txt      # Add execute for owner
chmod g+w file.txt      # Add write for group
chmod o-r file.txt      # Remove read for others
chmod a+r file.txt      # Add read for all (owner, group, others)

# Multiple changes
chmod u+x,g+x,o-rwx script.sh
chmod u=rwx,g=rx,o= script.sh  # Same as 750

# Recursive (all files in directory)
chmod -R 755 /var/www/html
```

### Common Permission Patterns

```bash
# Web files
sudo chmod 644 /var/www/html/*.html    # Files: rw-r--r--
sudo chmod 755 /var/www/html/          # Directory: rwxr-xr-x

# Scripts
chmod 755 script.sh                    # Executable by all
chmod 700 secure-script.sh             # Executable by owner only

# SSH keys
chmod 600 ~/.ssh/id_rsa                # Private key (owner read/write only)
chmod 644 ~/.ssh/id_rsa.pub            # Public key (readable by all)
chmod 700 ~/.ssh                       # SSH directory

# Sensitive files
chmod 600 /etc/ssl/private/server.key  # Private SSL key
chmod 400 /root/.aws/credentials       # AWS credentials (read-only, root only)
```

---

## File Ownership

### Change Owner (chown)

```bash
# Change owner only
sudo chown john file.txt

# Change owner and group
sudo chown john:developers file.txt

# Change group only
sudo chgrp developers file.txt
# OR
sudo chown :developers file.txt

# Recursive (all files in directory)
sudo chown -R john:developers /home/john/project

# Change owner to match another file
sudo chown --reference=file1.txt file2.txt
```

### Common Ownership Patterns

```bash
# Web server files (Apache/Nginx)
sudo chown -R www-data:www-data /var/www/html

# Application directory
sudo chown -R appuser:appgroup /opt/myapp

# Log files
sudo chown syslog:adm /var/log/myapp.log
```

---

## Special Permissions

### Setuid (SUID) - Run as Owner

```bash
# Set SUID bit (4000)
chmod 4755 /usr/bin/passwd   # -rwsr-xr-x

# User executes file with file owner's permissions
# Example: /usr/bin/passwd runs as root even when executed by regular user
```

### Setgid (SGID) - Run as Group / Inherit Group

**On Executable:**
```bash
# Set SGID bit (2000)
chmod 2755 /usr/bin/wall     # -rwxr-sr-x

# User executes file with file group's permissions
```

**On Directory:**
```bash
# Set SGID on directory
chmod 2775 /shared/projects  # drwxrwsr-x

# New files created in directory inherit directory's group (not user's primary group)
```

### Sticky Bit - Delete Restriction

```bash
# Set sticky bit (1000) on directory
chmod 1777 /tmp              # drwxrwxrwt

# Users can only delete their own files in this directory
# Even if others have write permission

# Common use: /tmp directory
```

### Combined Special Permissions

```bash
# SUID + SGID + Sticky
chmod 7755 file              # rwsr-sr-t (rarely used)

# Symbolic method
chmod u+s file               # Set SUID
chmod g+s directory          # Set SGID
chmod +t directory           # Set sticky bit
```

---

## Access Control Lists (ACL)

For more granular permissions than standard owner/group/other.

### View ACL

```bash
getfacl file.txt
```

### Set ACL Permissions

```bash
# Give specific user read access
setfacl -m u:john:r file.txt

# Give specific user read+write
setfacl -m u:jane:rw file.txt

# Give specific group read+execute
setfacl -m g:developers:rx /opt/project

# Remove ACL for user
setfacl -x u:john file.txt

# Remove all ACLs
setfacl -b file.txt

# Set default ACL (new files inherit this)
setfacl -d -m g:developers:rwx /shared/projects

# Recursive ACL
setfacl -R -m u:bob:rw /shared/docs
```

---

## Sudo Configuration

### Add User to Sudoers

```bash
# Method 1: Add to sudo/wheel group (recommended)
sudo usermod -aG sudo john       # Debian/Ubuntu
sudo usermod -aG wheel john      # RHEL/CentOS

# Method 2: Edit sudoers file (advanced)
sudo visudo

# Add line:
john ALL=(ALL:ALL) ALL

# Allow user to run specific command without password:
john ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nginx

# Allow group to sudo:
%developers ALL=(ALL:ALL) ALL
```

### Test Sudo Access

```bash
# Test as user
sudo -l                    # List allowed commands

# Run command as another user
sudo -u www-data ls /var/www

# Run shell as root
sudo -i                    # Login shell
sudo -s                    # Non-login shell
```

---

## User Information Commands

```bash
# View user details
id john                    # UID, GID, groups
finger john                # User info (if finger installed)
getent passwd john         # /etc/passwd entry

# List all users
cat /etc/passwd
cut -d: -f1 /etc/passwd    # Just usernames

# List logged-in users
who
w                          # Detailed (what they're doing)
last                       # Login history
lastlog                    # Last login for all users

# Check password status
sudo passwd -S john        # Password status (locked, expires, etc.)
sudo chage -l john         # Password aging info

# View user's crontab
sudo crontab -u john -l
```

---

## Security Best Practices

### User Management:
- ✅ **Use strong passwords** (12+ characters, mixed case, numbers, symbols)
- ✅ **Enforce password expiration** (90 days)
- ✅ **Lock unused accounts**
- ✅ **Use SSH keys** instead of passwords for remote access
- ✅ **Disable root login** via SSH
- ✅ **Regular audit** of user accounts
- ✅ **Remove old accounts** when employees leave

### Permission Best Practices:
- ✅ **Principle of least privilege** (give minimum required permissions)
- ✅ **Never use 777 permissions** (anyone can read/write/execute)
- ✅ **Avoid running services as root**
- ✅ **Use groups** for shared access
- ✅ **Regular permission audits**
- ✅ **Separate system and regular users**

---

## Common Permission Scenarios

### Scenario: Shared Project Directory

```bash
# Create shared directory
sudo mkdir /shared/projects
sudo chgrp developers /shared/projects
sudo chmod 2775 /shared/projects  # SGID + rwxrwxr-x

# Now all files created in /shared/projects will be owned by 'developers' group
# All group members can read/write
```

### Scenario: Web Application Directory

```bash
# Application owned by app user, readable by web server
sudo chown -R appuser:www-data /var/www/myapp
sudo chmod -R 750 /var/www/myapp          # rwxr-x---
sudo chmod -R 640 /var/www/myapp/*.conf   # rw-r-----
```

### Scenario: Log Files

```bash
# Logs writable by app, readable by sysadmins
sudo chown appuser:sysadmin /var/log/myapp.log
sudo chmod 640 /var/log/myapp.log  # rw-r-----
```

---

## Troubleshooting

### Problem: "Permission denied" error

**Check:**
```bash
ls -l file.txt             # View permissions
id                         # Check your user/groups
sudo !!                    # Re-run last command with sudo
```

**Fix:**
```bash
sudo chmod 755 file.txt    # Adjust permissions
sudo chown $USER file.txt  # Take ownership
```

### Problem: User can't login

```bash
# Check if account is locked
sudo passwd -S username

# Unlock account
sudo passwd -u username
sudo usermod -U username

# Check shell is valid
grep username /etc/passwd
# If shell is /usr/sbin/nologin, change to /bin/bash:
sudo usermod -s /bin/bash username
```

### Problem: User not in sudo group

```bash
# Verify group membership
groups username

# Add to sudo group
sudo usermod -aG sudo username

# User must log out and back in for group change to take effect!
```

---

## Quick Reference

```bash
# User management
sudo useradd -m -s /bin/bash john
sudo passwd john
sudo usermod -aG sudo john
sudo userdel -r john

# Group management
sudo groupadd developers
sudo usermod -aG developers john
sudo gpasswd -d john developers
groups john

# Permissions
chmod 755 file                # rwxr-xr-x
chmod 644 file                # rw-r--r--
chmod u+x file                # Add execute for owner
chmod -R 755 directory        # Recursive

# Ownership
sudo chown john file
sudo chown john:developers file
sudo chown -R john:developers directory

# Special permissions
chmod 4755 file               # SUID
chmod 2775 directory          # SGID
chmod 1777 directory          # Sticky bit

# ACLs
getfacl file
setfacl -m u:john:rw file
setfacl -x u:john file

# Information
id john
groups john
ls -l file
```
'''
        })

        articles.append({
            'category': 'Backup & Recovery',
            'title': 'Setting Up Automated Backups with rsync',
            'body': r'''# Setting Up Automated Backups with rsync

## Overview
rsync is a powerful file synchronization tool perfect for creating automated backups on Linux systems. This guide covers local backups, remote backups, and automated scheduling.

## Why rsync for Backups

**Advantages:**
- Fast incremental backups (only transfers changed files)
- Preserves permissions, timestamps, symlinks
- Network-efficient compression
- Built-in on most Linux distributions
- Flexible include/exclude patterns
- Can resume interrupted transfers

## Basic rsync Syntax

```bash
rsync [options] source destination
```

**Common Options:**
- `-a`: Archive mode (preserves permissions, recursive)
- `-v`: Verbose output
- `-z`: Compress during transfer
- `-h`: Human-readable sizes
- `--delete`: Delete files in destination not in source
- `--dry-run`: Test without making changes

---

## Local Backups

### Simple File Backup

```bash
# Backup single directory
sudo rsync -avh /home/user/documents /backup/

# Backup with progress display
sudo rsync -avh --progress /home/user/documents /backup/

# Backup multiple directories
sudo rsync -avh /home/user/documents /home/user/pictures /backup/
```

### Full System Backup

```bash
# Backup entire system (excluding certain directories)
sudo rsync -aAXvh --exclude={"/dev/*","/proc/*","/sys/*","/tmp/*","/run/*","/mnt/*","/media/*","/lost+found"} / /backup/system/

# Explanation:
# -a: Archive mode
# -A: Preserve ACLs
# -X: Preserve extended attributes
# -v: Verbose
# -h: Human-readable
```

### Incremental Backups with Hardlinks

Save space by creating hardlinks for unchanged files:

```bash
#!/bin/bash
# Create dated backup directory
BACKUP_DIR="/backup/$(date +%Y-%m-%d)"
LATEST_LINK="/backup/latest"

# Perform backup linking to previous backup
sudo rsync -avh --delete \
    --link-dest="$LATEST_LINK" \
    /home/user/ \
    "$BACKUP_DIR/"

# Update latest link
sudo rm -f "$LATEST_LINK"
sudo ln -s "$BACKUP_DIR" "$LATEST_LINK"
```

---

## Remote Backups (Over SSH)

### Push to Remote Server

```bash
# Backup local to remote server
sudo rsync -avz -e ssh /home/user/documents user@backup-server:/backups/

# Using specific SSH port
sudo rsync -avz -e "ssh -p 2222" /home/user/documents user@backup-server:/backups/

# With SSH key (no password prompt)
sudo rsync -avz -e "ssh -i /root/.ssh/backup_key" /home/user/documents user@backup-server:/backups/
```

### Pull from Remote Server

```bash
# Backup remote to local
sudo rsync -avz user@remote-server:/var/www/html /backup/websites/

# Backup multiple remote directories
sudo rsync -avz user@remote-server:'/var/log/apache2 /var/log/nginx' /backup/logs/
```

---

## Advanced Backup Strategies

### Exclude Files and Directories

```bash
# Exclude specific patterns
sudo rsync -avh \
    --exclude='*.log' \
    --exclude='*.tmp' \
    --exclude='cache/*' \
    --exclude='node_modules/*' \
    /home/user/project /backup/

# Use exclude file
sudo rsync -avh --exclude-from='/etc/rsync-exclude.txt' /home/user /backup/
```

**Example /etc/rsync-exclude.txt:**
```
*.log
*.tmp
*.cache
.DS_Store
Thumbs.db
node_modules/
.git/
__pycache__/
.vscode/
```

### Bandwidth Limiting

```bash
# Limit to 5000 KB/s (5 MB/s)
sudo rsync -avz --bwlimit=5000 /large-files/ user@remote:/backup/

# Useful for:
# - Production servers (avoid network saturation)
# - Remote backups over slow connections
```

### Delete Old Backups

```bash
#!/bin/bash
# Keep only last 7 daily backups
BACKUP_ROOT="/backup/daily"
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;

# Keep only 4 weekly backups
BACKUP_ROOT="/backup/weekly"
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +28 -exec rm -rf {} \;
```

---

## Complete Backup Scripts

### Daily Backup Script

```bash
#!/bin/bash
# /usr/local/bin/backup-daily.sh

# Configuration
SOURCE="/home"
DEST="/backup/daily"
LOG="/var/log/backup-daily.log"
DATE=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_DIR="$DEST/$DATE"
LATEST="$DEST/latest"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Perform backup
echo "Starting backup: $DATE" >> "$LOG"

rsync -aAXvh \
    --delete \
    --link-dest="$LATEST" \
    --exclude={'.cache/*','*.tmp','.Trash/*'} \
    --log-file="$LOG" \
    "$SOURCE/" \
    "$BACKUP_DIR/"

# Check exit status
if [ $? -eq 0 ]; then
    echo "Backup completed successfully: $DATE" >> "$LOG"

    # Update latest symlink
    rm -f "$LATEST"
    ln -s "$BACKUP_DIR" "$LATEST"

    # Delete backups older than 7 days
    find "$DEST" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
else
    echo "Backup FAILED: $DATE" >> "$LOG"
    exit 1
fi

# Send email notification (optional)
# echo "Backup completed: $DATE" | mail -s "Backup Success" admin@example.com
```

### Remote Server Backup Script

```bash
#!/bin/bash
# /usr/local/bin/backup-remote.sh

# Configuration
SOURCE="/var/www /etc /home"
REMOTE_USER="backup"
REMOTE_HOST="backup-server.example.com"
REMOTE_DIR="/backups/$(hostname)"
SSH_KEY="/root/.ssh/backup_key"
LOG="/var/log/backup-remote.log"
DATE=$(date +%Y-%m-%d)

echo "===== Starting remote backup: $DATE =====" >> "$LOG"

# Ensure remote directory exists
ssh -i "$SSH_KEY" "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_DIR"

# Perform backup
rsync -avz --delete \
    -e "ssh -i $SSH_KEY" \
    --exclude={'*.log','cache/*','tmp/*'} \
    --log-file="$LOG" \
    $SOURCE \
    "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

if [ $? -eq 0 ]; then
    echo "Remote backup completed successfully: $DATE" >> "$LOG"
else
    echo "Remote backup FAILED: $DATE" >> "$LOG"
    echo "Remote backup failed on $(hostname)" | mail -s "BACKUP FAILURE" admin@example.com
    exit 1
fi
```

### Database Backup with rsync

```bash
#!/bin/bash
# /usr/local/bin/backup-databases.sh

# Configuration
DB_BACKUP_DIR="/backup/databases"
DATE=$(date +%Y-%m-%d)
BACKUP_DIR="$DB_BACKUP_DIR/$DATE"

mkdir -p "$BACKUP_DIR"

# Backup MySQL/MariaDB databases
mysqldump --all-databases --single-transaction \
    --user=backup_user --password=SecurePassword \
    | gzip > "$BACKUP_DIR/all-databases.sql.gz"

# Backup PostgreSQL databases
sudo -u postgres pg_dumpall \
    | gzip > "$BACKUP_DIR/postgres-all.sql.gz"

# Sync to remote server
rsync -avz -e ssh "$DB_BACKUP_DIR/" backup@remote:/backups/databases/

# Delete local backups older than 3 days
find "$DB_BACKUP_DIR" -maxdepth 1 -type d -mtime +3 -exec rm -rf {} \;
```

---

## Automate with Cron

### Schedule Backups

```bash
# Edit root crontab
sudo crontab -e

# Add these lines:

# Daily backup at 2 AM
0 2 * * * /usr/local/bin/backup-daily.sh

# Weekly backup on Sunday at 3 AM
0 3 * * 0 /usr/local/bin/backup-weekly.sh

# Remote backup every 6 hours
0 */6 * * * /usr/local/bin/backup-remote.sh

# Database backup every 4 hours
0 */4 * * * /usr/local/bin/backup-databases.sh
```

### Systemd Timer (Alternative to Cron)

**Create service file:** `/etc/systemd/system/backup.service`

```ini
[Unit]
Description=Daily Backup
Wants=backup.timer

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup-daily.sh

[Install]
WantedBy=multi-user.target
```

**Create timer file:** `/etc/systemd/system/backup.timer`

```ini
[Unit]
Description=Daily Backup Timer
Requires=backup.service

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable and start:**

```bash
sudo systemctl enable backup.timer
sudo systemctl start backup.timer

# Check status
sudo systemctl status backup.timer
sudo systemctl list-timers
```

---

## Monitoring and Alerts

### Email Notifications

```bash
# Add to backup script
if [ $? -eq 0 ]; then
    echo "Backup completed successfully" | \
        mail -s "Backup Success: $(hostname)" admin@example.com
else
    echo "Backup FAILED! Check logs at /var/log/backup.log" | \
        mail -s "BACKUP FAILURE: $(hostname)" admin@example.com
fi
```

### Log Rotation

**Create /etc/logrotate.d/backup:**

```
/var/log/backup-*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
}
```

### Check Backup Age

```bash
#!/bin/bash
# Alert if backup is older than 2 days

LATEST_BACKUP=$(find /backup -type d -maxdepth 1 -mtime -2 | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "WARNING: No backup found in last 2 days!" | \
        mail -s "BACKUP WARNING" admin@example.com
fi
```

---

## Restore from Backup

### Restore Entire Directory

```bash
# Restore from latest backup
sudo rsync -avh /backup/latest/home/user/documents/ /home/user/documents/

# Restore specific file
sudo rsync -avh /backup/latest/home/user/documents/important.txt /home/user/documents/
```

### Restore to Different Location

```bash
# Restore to temporary location for review
sudo rsync -avh /backup/2024-01-15/var/www/ /tmp/restore-preview/
```

### Dry Run Before Restore

```bash
# See what would be restored without actually doing it
sudo rsync -avh --dry-run /backup/latest/home/user/ /home/user/
```

---

## Backup Best Practices

### Do:
- ✅ **Test restores regularly** (backup is only as good as restore)
- ✅ **Store backups offsite** (3-2-1 rule: 3 copies, 2 media types, 1 offsite)
- ✅ **Encrypt sensitive data** (use rsync with ssh or encrypted filesystem)
- ✅ **Monitor backup success/failure** (email alerts, monitoring dashboard)
- ✅ **Document restore procedures**
- ✅ **Keep multiple backup generations** (daily, weekly, monthly)
- ✅ **Verify backup integrity** (checksums, test restores)

### Don't:
- ❌ **Don't backup to same disk** (hardware failure will lose everything)
- ❌ **Don't store only one backup** (ransomware can encrypt backups)
- ❌ **Don't forget databases** (file backup alone may not capture DB state)
- ❌ **Don't ignore logs** (monitor for errors)
- ❌ **Don't use --delete without testing** (can accidentally delete needed files)

---

## Troubleshooting

### Problem: Permission Denied

```bash
# Run as root or with sudo
sudo rsync -avh /home/user /backup/

# OR ensure backup user has read access
sudo usermod -aG users backup_user
```

### Problem: rsync Hanging

```bash
# Use timeout command
timeout 3600 rsync -avh /source /dest  # 1 hour timeout

# Check for network issues (remote backups)
ping backup-server

# Check SSH connectivity
ssh -v user@backup-server
```

### Problem: Running Out of Space

```bash
# Check disk space
df -h /backup

# Find large files
du -sh /backup/* | sort -rh | head -10

# Delete old backups
find /backup -mtime +30 -exec rm -rf {} \;
```

---

## Quick Reference

```bash
# Basic local backup
sudo rsync -avh /source /destination

# Remote backup (push)
sudo rsync -avz -e ssh /local user@remote:/backup

# Remote backup (pull)
sudo rsync -avz user@remote:/data /local-backup

# Incremental backup with hardlinks
sudo rsync -avh --delete --link-dest=/backup/latest /source /backup/new

# Exclude patterns
sudo rsync -avh --exclude='*.log' --exclude='cache/*' /source /dest

# Dry run (test without changes)
sudo rsync -avh --dry-run /source /dest

# Bandwidth limit (5 MB/s)
sudo rsync -avz --bwlimit=5000 /source /dest

# Show progress
sudo rsync -avh --progress /source /dest
```

---

## Example Backup Strategy

**For Small Business:**
- Daily full backups (7 days retention)
- Weekly backups (4 weeks retention)
- Monthly backups (12 months retention)
- Offsite backup every 24 hours
- Test restore monthly

**Cron Schedule:**
```bash
# Daily at 2 AM
0 2 * * * /usr/local/bin/backup-daily.sh

# Weekly on Sunday at 3 AM
0 3 * * 0 /usr/local/bin/backup-weekly.sh

# Monthly on 1st at 4 AM
0 4 1 * * /usr/local/bin/backup-monthly.sh

# Remote sync every 6 hours
0 */6 * * * /usr/local/bin/backup-remote.sh
```
'''
        })

        articles.append({
            'category': 'Common Issues',
            'title': 'Monitoring Linux System Performance',
            'body': r'''# Monitoring Linux System Performance

## Overview
Comprehensive guide to monitoring CPU, memory, disk, and network performance on Linux systems using built-in tools.

## Quick System Overview

### top - Real-Time Process Monitor

```bash
# Launch top
top

# Sorted by memory usage
top -o %MEM

# Show specific user's processes
top -u username

# Batch mode (for logging)
top -b -n 1 > system-snapshot.txt
```

**Key Metrics in top:**
- `load average`: 1, 5, 15 minute averages (< number of CPUs = good)
- `%Cpu(s)`: us=user, sy=system, id=idle, wa=I/O wait
- `KiB Mem`: total, free, used, buff/cache
- `PID`: Process ID
- `%CPU`: CPU usage percentage
- `%MEM`: Memory usage percentage
- `TIME+`: Total CPU time used
- `COMMAND`: Process name

**Interactive Commands:**
- `M`: Sort by memory
- `P`: Sort by CPU
- `k`: Kill process (enter PID)
- `q`: Quit

### htop - Enhanced Process Viewer

```bash
# Install htop
sudo apt install htop      # Debian/Ubuntu
sudo yum install htop      # CentOS/RHEL

# Launch htop
htop
```

**Advantages over top:**
- Color-coded output
- Mouse support
- Tree view of processes
- Easy to kill processes
- Horizontal/vertical scrolling

---

## CPU Monitoring

### Check CPU Info

```bash
# Number of CPUs
nproc

# Detailed CPU information
lscpu

# CPU model and cores
cat /proc/cpuinfo | grep -E "model name|cpu cores"

# Current CPU frequency
cat /proc/cpuinfo | grep MHz
```

### Real-Time CPU Usage

```bash
# Overall CPU usage
mpstat 1 5  # Update every 1 second, 5 times

# Per-CPU usage
mpstat -P ALL 1
```

**Install sysstat (contains mpstat):**
```bash
sudo apt install sysstat     # Debian/Ubuntu
sudo yum install sysstat     # CentOS/RHEL
```

### Load Average

```bash
# Check load average
uptime

# Detailed load stats
w

# What load average means:
# - Load < # of CPUs: System not busy
# - Load = # of CPUs: System fully utilized
# - Load > # of CPUs: System overloaded (processes waiting)

# Example on 4-core system:
# load average: 2.0, 1.5, 1.0  ← Good (under 4.0)
# load average: 6.0, 5.5, 5.0  ← High (over 4.0)
```

### Find CPU-Hungry Processes

```bash
# Top 10 CPU consumers
ps aux --sort=-%cpu | head -10

# Continuously monitor
watch "ps aux --sort=-%cpu | head -10"
```

---

## Memory Monitoring

### Check Memory Usage

```bash
# Simple overview
free -h

# Detailed breakdown
free -h -w

# Output explanation:
# total: Total RAM
# used: Used by processes
# free: Completely unused
# shared: Used by tmpfs
# buff/cache: Used for caching (available if needed)
# available: Actually available for applications
```

### Swap Usage

```bash
# Check swap status
swapon --show

# Total swap usage
free -h | grep Swap

# Processes using swap (sorted)
for file in /proc/*/status ; do
    awk '/VmSwap|Name/{printf $2 " " $3}END{ print ""}' $file
done | sort -k 2 -n -r | head -10
```

### Memory Hogs

```bash
# Top 10 memory consumers
ps aux --sort=-%mem | head -10

# Detailed memory breakdown per process
ps aux | awk '{print $11, $6}' | sort -k2 -n -r | head -10

# Show processes using > 10% memory
ps aux | awk '$4 > 10.0 {print $0}'
```

### OOM (Out of Memory) Killer Logs

```bash
# Check if OOM killer has run
dmesg | grep -i "out of memory"

# View OOM killed processes
grep -i "killed process" /var/log/syslog
# OR
grep -i "killed process" /var/log/messages
```

---

## Disk I/O Monitoring

### Disk Usage

```bash
# Disk space by filesystem
df -h

# Disk space with inode information
df -hi

# Specific directory size
du -sh /var/log

# Find large directories
du -h /var | sort -rh | head -10

# Find large files
find / -type f -size +100M -exec ls -lh {} \; 2>/dev/null | head -10
```

### Disk I/O Performance

```bash
# Real-time disk I/O statistics
iostat -x 1

# Monitor specific disk
iostat -x /dev/sda 1

# Key metrics:
# - %util: Percentage of time disk was busy (>80% = bottleneck)
# - await: Average wait time (ms) for I/O requests
# - r/s: Read requests per second
# - w/s: Write requests per second
```

**Install sysstat:**
```bash
sudo apt install sysstat
```

### Find Processes Using Disk I/O

```bash
# Real-time disk I/O by process
sudo iotop

# Sort by I/O usage
sudo iotop -o

# Batch mode
sudo iotop -b -n 3
```

**Install iotop:**
```bash
sudo apt install iotop      # Debian/Ubuntu
sudo yum install iotop      # CentOS/RHEL
```

### Check for Disk Errors

```bash
# Check system log for disk errors
dmesg | grep -i error

# SMART disk health (requires smartmontools)
sudo smartctl -a /dev/sda

# Check filesystem errors
sudo fsck -n /dev/sda1  # -n = dry run (no changes)
```

---

## Network Monitoring

### Network Interfaces

```bash
# Show network interfaces
ip addr show

# OR
ifconfig

# Show only active interfaces
ip link show up
```

### Network Traffic

```bash
# Real-time network usage by interface
ifstat 1

# Detailed network statistics
netstat -i

# Monitor bandwidth by process
sudo nethogs

# Monitor bandwidth by interface
sudo iftop -i eth0
```

**Install network monitoring tools:**
```bash
sudo apt install ifstat nethogs iftop    # Debian/Ubuntu
sudo yum install iftop nethogs           # CentOS/RHEL
```

### Network Connections

```bash
# Active connections
netstat -tuln

# OR (newer)
ss -tuln

# Connections by state
ss -s

# Show process using port
sudo netstat -tulpn | grep :80
sudo ss -tulpn | grep :80

# Count connections per state
ss -s | grep TCP
```

### Bandwidth Usage

```bash
# Total data transferred per interface
cat /proc/net/dev

# Real-time bandwidth monitor
nload

# Per-process network usage
sudo nethogs eth0
```

---

## System Logs

### View System Logs

```bash
# Recent system messages
dmesg | tail -50

# Real-time system log
sudo tail -f /var/log/syslog     # Debian/Ubuntu
sudo tail -f /var/log/messages   # CentOS/RHEL

# Kernel messages
sudo journalctl -k

# Boot messages
sudo journalctl -b

# Follow live log
sudo journalctl -f
```

### Search Logs

```bash
# Search for errors
sudo grep -i error /var/log/syslog

# Search for specific service
sudo grep -i nginx /var/log/syslog

# Search with context (10 lines before/after)
sudo grep -i -C 10 "error" /var/log/syslog
```

---

## All-in-One Monitoring Tools

### glances - Comprehensive System Monitor

```bash
# Install glances
sudo apt install glances    # Debian/Ubuntu
sudo yum install glances    # CentOS/RHEL

# Run glances
glances

# Export to CSV
glances --export csv --export-csv-file /tmp/glances.csv

# Web interface
glances -w
# Access at: http://localhost:61208
```

**Features:**
- CPU, memory, disk, network in one view
- Process list
- Disk I/O
- Filesystem usage
- Sensors (temperature)
- Docker container monitoring

### nmon - Performance Monitor

```bash
# Install nmon
sudo apt install nmon

# Run nmon
nmon

# Interactive keys:
# c: CPU stats
# m: Memory stats
# d: Disk stats
# n: Network stats
# t: Top processes
# q: Quit
```

---

## Performance Baselines

### Create Performance Baseline

```bash
#!/bin/bash
# /usr/local/bin/performance-baseline.sh

LOGFILE="/var/log/performance-baseline-$(date +%Y%m%d).log"

echo "===== Performance Baseline: $(date) =====" > "$LOGFILE"

echo -e "\n--- CPU Info ---" >> "$LOGFILE"
lscpu >> "$LOGFILE"

echo -e "\n--- Load Average ---" >> "$LOGFILE"
uptime >> "$LOGFILE"

echo -e "\n--- Memory Usage ---" >> "$LOGFILE"
free -h >> "$LOGFILE"

echo -e "\n--- Disk Usage ---" >> "$LOGFILE"
df -h >> "$LOGFILE"

echo -e "\n--- Disk I/O ---" >> "$LOGFILE"
iostat -x >> "$LOGFILE"

echo -e "\n--- Network Stats ---" >> "$LOGFILE"
netstat -i >> "$LOGFILE"

echo -e "\n--- Top Processes (CPU) ---" >> "$LOGFILE"
ps aux --sort=-%cpu | head -10 >> "$LOGFILE"

echo -e "\n--- Top Processes (Memory) ---" >> "$LOGFILE"
ps aux --sort=-%mem | head -10 >> "$LOGFILE"
```

**Schedule daily baseline:**
```bash
sudo crontab -e

# Add:
0 6 * * * /usr/local/bin/performance-baseline.sh
```

---

## Performance Alerts

### CPU Alert Script

```bash
#!/bin/bash
# Alert if CPU usage > 80%

CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
THRESHOLD=80

if (( $(echo "$CPU_USAGE > $THRESHOLD" | bc -l) )); then
    echo "HIGH CPU USAGE: ${CPU_USAGE}% on $(hostname)" | \
        mail -s "CPU Alert" admin@example.com
fi
```

### Memory Alert Script

```bash
#!/bin/bash
# Alert if memory usage > 90%

MEMORY_USAGE=$(free | grep Mem | awk '{print ($3/$2) * 100.0}')
THRESHOLD=90

if (( $(echo "$MEMORY_USAGE > $THRESHOLD" | bc -l) )); then
    echo "HIGH MEMORY USAGE: ${MEMORY_USAGE}% on $(hostname)" | \
        mail -s "Memory Alert" admin@example.com
fi
```

### Disk Space Alert

```bash
#!/bin/bash
# Alert if disk usage > 85%

df -H | grep -vE '^Filesystem|tmpfs|cdrom' | awk '{ print $5 " " $1 }' | while read output;
do
    USAGE=$(echo $output | awk '{ print $1}' | cut -d'%' -f1)
    PARTITION=$(echo $output | awk '{ print $2 }')

    if [ $USAGE -ge 85 ]; then
        echo "DISK SPACE LOW: $PARTITION is ${USAGE}% full on $(hostname)" | \
            mail -s "Disk Alert" admin@example.com
    fi
done
```

---

## Troubleshooting Performance Issues

### High CPU Usage

**Identify culprit:**
```bash
# Find process using most CPU
top -b -n 1 | head -20

# If specific process is high:
# 1. Check if it's legitimate
ps aux | grep [process_name]

# 2. Check process logs
sudo journalctl -u [service_name]

# 3. Kill if necessary
sudo kill -15 [PID]      # Graceful
sudo kill -9 [PID]       # Force kill
```

### High Memory Usage

**Find memory leak:**
```bash
# Monitor process memory over time
watch "ps aux --sort=-%mem | head -10"

# Check for memory leaks in application logs
# Restart service if needed
sudo systemctl restart [service_name]
```

### Disk I/O Bottleneck

**Identify:**
```bash
# Check %util column (>80% = bottleneck)
iostat -x 1

# Find process causing I/O
sudo iotop -o

# Solutions:
# - Upgrade to SSD
# - Add more RAM (increase cache)
# - Optimize application queries
# - Move I/O to different disk
```

### Network Saturation

**Identify:**
```bash
# Check bandwidth usage
sudo iftop -i eth0

# Find process using bandwidth
sudo nethogs eth0

# Solutions:
# - Rate limit applications
# - Upgrade network interface
# - Implement QoS
```

---

## Quick Reference

```bash
# CPU
top                    # Real-time process monitor
htop                   # Enhanced process viewer
mpstat 1               # CPU statistics
uptime                 # Load average
nproc                  # Number of CPUs

# Memory
free -h                # Memory usage
ps aux --sort=-%mem    # Memory hogs

# Disk
df -h                  # Disk space
du -sh /var            # Directory size
iostat -x 1            # Disk I/O
sudo iotop             # I/O by process

# Network
ifconfig               # Network interfaces
ss -tuln               # Active connections
sudo nethogs           # Bandwidth by process
sudo iftop             # Bandwidth monitor

# Logs
dmesg                  # Kernel messages
sudo journalctl -f     # Follow system log
tail -f /var/log/syslog  # Follow syslog

# All-in-one
glances                # Comprehensive monitor
nmon                   # Performance monitor
```
'''
        })

        self.stdout.write(self.style.SUCCESS(f'✓ Created {len(articles)} professional KB articles'))

        # Create articles in database
        created_count = 0
        for article_data in articles:
            category = categories[article_data['category']]
            slug = slugify(article_data['title'])

            doc, created = Document.objects.update_or_create(
                slug=slug,
                organization=None,  # Global KB
                defaults={
                    'title': article_data['title'],
                    'body': article_data['body'],
                    'category': category,
                    'is_global': True,
                    'is_published': True,
                }
            )

            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f'✓ Successfully created {created_count} new articles'))
        self.stdout.write(self.style.SUCCESS(f'✓ Updated {len(articles) - created_count} existing articles'))
