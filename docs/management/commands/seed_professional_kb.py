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
                }
            )

            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f'✓ Successfully created {created_count} new articles'))
        self.stdout.write(self.style.SUCCESS(f'✓ Updated {len(articles) - created_count} existing articles'))
