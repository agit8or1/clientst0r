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
            {'name': 'Linux Administration', 'order': 9},
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

        # ============================================================
        # MICROSOFT 365 (6 articles)
        # ============================================================

        articles.append({
            'category': 'Microsoft 365',
            'title': 'Microsoft 365 User License Management with PowerShell',
            'body': r'''# Microsoft 365 User License Management with PowerShell

## Overview
Comprehensive guide to managing Microsoft 365 licenses using PowerShell, including assignment, removal, bulk operations, and reporting.

## Prerequisites

```powershell
# Install Microsoft Online Services Module
Install-Module MSOnline -Force

# OR install newer Microsoft Graph PowerShell (recommended)
Install-Module Microsoft.Graph -Force

# Connect to Microsoft 365
Connect-MsolService

# OR with Microsoft Graph
Connect-MgGraph -Scopes "User.ReadWrite.All", "Directory.ReadWrite.All"
```

---

## Understanding License SKUs

### List All Available Licenses

```powershell
# Using MSOnline
Get-MsolAccountSku

# Output shows:
# AccountSkuId                    ActiveUnits  WarningUnits  ConsumedUnits
# contoso:ENTERPRISEPACK         500          0             342
# contoso:POWER_BI_STANDARD      25           0             18
# contoso:EMS                    500          0             298
```

**Common SKU Names:**
- `ENTERPRISEPACK` = Office 365 E3
- `ENTERPRISEPREMIUM` = Office 365 E5
- `SPE_E3` = Microsoft 365 E3
- `SPE_E5` = Microsoft 365 E5
- `EXCHANGESTANDARD` = Exchange Online Plan 1
- `EXCHANGEENTERPRISE` = Exchange Online Plan 2
- `SHAREPOINTSTANDARD` = SharePoint Online Plan 1
- `POWER_BI_STANDARD` = Power BI (free)
- `POWER_BI_PRO` = Power BI Pro

### View License Details

```powershell
# Get detailed service plans in a license
Get-MsolAccountSku | Where-Object {$_.AccountSkuId -like "*ENTERPRISEPACK*"} |
    Select-Object -ExpandProperty ServiceStatus

# Shows individual services:
# ServicePlan           ProvisioningStatus
# EXCHANGE_S_ENTERPRISE Success
# SHAREPOINTWAC         Success
# TEAMS1                Success
# MCOSTANDARD           Success
```

---

## Assign Licenses to Users

### Assign Single License

```powershell
# Set usage location (required before assigning licenses)
Set-MsolUser -UserPrincipalName john@contoso.com -UsageLocation US

# Assign license
Set-MsolUserLicense -UserPrincipalName john@contoso.com `
    -AddLicenses "contoso:ENTERPRISEPACK"

# Verify assignment
Get-MsolUser -UserPrincipalName john@contoso.com |
    Select-Object DisplayName, Licenses
```

### Assign Multiple Licenses

```powershell
# Assign Office 365 E3 + Power BI Pro
Set-MsolUserLicense -UserPrincipalName jane@contoso.com `
    -AddLicenses "contoso:ENTERPRISEPACK","contoso:POWER_BI_PRO"
```

### Assign with Disabled Services

```powershell
# Create license options (disable Yammer and Sway)
$LicenseOptions = New-MsolLicenseOptions -AccountSkuId "contoso:ENTERPRISEPACK" `
    -DisabledPlans "YAMMER_ENTERPRISE","SWAY"

# Assign license with disabled services
Set-MsolUserLicense -UserPrincipalName bob@contoso.com `
    -AddLicenses "contoso:ENTERPRISEPACK" `
    -LicenseOptions $LicenseOptions
```

**Common Services to Disable:**
- `YAMMER_ENTERPRISE` - Yammer
- `SWAY` - Sway
- `FORMS_PLAN_E3` - Microsoft Forms
- `STREAM_O365_E3` - Microsoft Stream
- `KAIZALA_O365_P3` - Kaizala Pro (retired)

---

## Remove Licenses

### Remove Single License

```powershell
Set-MsolUserLicense -UserPrincipalName john@contoso.com `
    -RemoveLicenses "contoso:ENTERPRISEPACK"
```

### Remove All Licenses

```powershell
# Get all licenses for user
$UserLicenses = (Get-MsolUser -UserPrincipalName john@contoso.com).Licenses.AccountSkuId

# Remove all licenses
foreach ($License in $UserLicenses) {
    Set-MsolUserLicense -UserPrincipalName john@contoso.com `
        -RemoveLicenses $License
}
```

### Replace License (Upgrade/Downgrade)

```powershell
# Upgrade from E3 to E5
Set-MsolUserLicense -UserPrincipalName jane@contoso.com `
    -RemoveLicenses "contoso:ENTERPRISEPACK" `
    -AddLicenses "contoso:ENTERPRISEPREMIUM"
```

---

## Bulk License Operations

### Assign Licenses to Multiple Users (CSV)

**Create CSV file:** `users.csv`
```csv
UserPrincipalName,License
john@contoso.com,contoso:ENTERPRISEPACK
jane@contoso.com,contoso:ENTERPRISEPACK
bob@contoso.com,contoso:POWER_BI_PRO
```

**Script:**
```powershell
# Import CSV
$Users = Import-Csv "C:\Temp\users.csv"

# Assign licenses
foreach ($User in $Users) {
    # Set usage location if not set
    $MsolUser = Get-MsolUser -UserPrincipalName $User.UserPrincipalName
    if (!$MsolUser.UsageLocation) {
        Set-MsolUser -UserPrincipalName $User.UserPrincipalName -UsageLocation US
    }

    # Assign license
    Set-MsolUserLicense -UserPrincipalName $User.UserPrincipalName `
        -AddLicenses $User.License

    Write-Host "Assigned $($User.License) to $($User.UserPrincipalName)" -ForegroundColor Green
}
```

### Assign License to All Users in Group

```powershell
# Get all members of a group
$GroupMembers = Get-MsolGroupMember -GroupObjectId "12345678-1234-1234-1234-123456789012"

# Assign E3 license to all members
foreach ($Member in $GroupMembers) {
    if ($Member.EmailAddress) {
        Set-MsolUser -UserPrincipalName $Member.EmailAddress -UsageLocation US
        Set-MsolUserLicense -UserPrincipalName $Member.EmailAddress `
            -AddLicenses "contoso:ENTERPRISEPACK"

        Write-Host "Licensed: $($Member.EmailAddress)"
    }
}
```

### Assign License to All Unlicensed Users

```powershell
# Get all unlicensed users
$UnlicensedUsers = Get-MsolUser -All -UnlicensedUsersOnly

# Assign license
foreach ($User in $UnlicensedUsers) {
    if (!$User.UsageLocation) {
        Set-MsolUser -UserPrincipalName $User.UserPrincipalName -UsageLocation US
    }

    Set-MsolUserLicense -UserPrincipalName $User.UserPrincipalName `
        -AddLicenses "contoso:ENTERPRISEPACK"

    Write-Host "Licensed: $($User.UserPrincipalName)"
}
```

---

## License Reporting

### List All Licensed Users

```powershell
# Get all licensed users
Get-MsolUser -All | Where-Object {$_.IsLicensed -eq $true} |
    Select-Object DisplayName, UserPrincipalName, Licenses

# Export to CSV
Get-MsolUser -All | Where-Object {$_.IsLicensed -eq $true} |
    Select-Object DisplayName, UserPrincipalName,
        @{Name="Licenses";Expression={$_.Licenses.AccountSkuId -join ", "}} |
    Export-Csv "C:\Reports\LicensedUsers.csv" -NoTypeInformation
```

### License Usage Report

```powershell
# Get license summary
Get-MsolAccountSku | Select-Object `
    AccountSkuId,
    ActiveUnits,
    ConsumedUnits,
    @{Name="Available";Expression={$_.ActiveUnits - $_.ConsumedUnits}},
    @{Name="PercentUsed";Expression={[math]::Round(($_.ConsumedUnits / $_.ActiveUnits) * 100, 2)}}

# Export to CSV
Get-MsolAccountSku | Select-Object AccountSkuId, ActiveUnits, ConsumedUnits,
    @{Name="Available";Expression={$_.ActiveUnits - $_.ConsumedUnits}} |
    Export-Csv "C:\Reports\LicenseUsage.csv" -NoTypeInformation
```

### Users by License Type

```powershell
# Count users per license
$LicenseSummary = @{}

Get-MsolUser -All | Where-Object {$_.IsLicensed -eq $true} | ForEach-Object {
    foreach ($License in $_.Licenses) {
        $SKU = $License.AccountSkuId
        if ($LicenseSummary.ContainsKey($SKU)) {
            $LicenseSummary[$SKU]++
        } else {
            $LicenseSummary[$SKU] = 1
        }
    }
}

# Display results
$LicenseSummary.GetEnumerator() | Sort-Object Name |
    Format-Table Name, Value -AutoSize
```

### Users with Specific Service Disabled

```powershell
# Find users with Yammer disabled
Get-MsolUser -All | Where-Object {
    $_.Licenses.ServiceStatus |
    Where-Object {$_.ServicePlan.ServiceName -eq "YAMMER_ENTERPRISE" -and $_.ProvisioningStatus -eq "Disabled"}
} | Select-Object DisplayName, UserPrincipalName
```

### Unlicensed Users Report

```powershell
# Get all unlicensed users (excluding guests)
Get-MsolUser -All -UnlicensedUsersOnly |
    Where-Object {$_.UserType -ne "Guest"} |
    Select-Object DisplayName, UserPrincipalName, Department, WhenCreated |
    Export-Csv "C:\Reports\UnlicensedUsers.csv" -NoTypeInformation
```

---

## Microsoft Graph PowerShell (Modern Approach)

### Connect and Authenticate

```powershell
# Connect with required permissions
Connect-MgGraph -Scopes "User.ReadWrite.All", "Organization.Read.All"

# Verify connection
Get-MgContext
```

### Assign License with Graph

```powershell
# Get license SKU ID
$E3License = Get-MgSubscribedSku -All |
    Where-Object {$_.SkuPartNumber -eq "ENTERPRISEPACK"}

# Assign license
Set-MgUserLicense -UserId "john@contoso.com" `
    -AddLicenses @{SkuId = $E3License.SkuId} `
    -RemoveLicenses @()
```

### Remove License with Graph

```powershell
Set-MgUserLicense -UserId "john@contoso.com" `
    -AddLicenses @() `
    -RemoveLicenses @($E3License.SkuId)
```

---

## Automated License Management

### Auto-Assign Licenses to New Users

```powershell
# Schedule this script to run daily

# Get users created in last 24 hours without licenses
$NewUsers = Get-MsolUser -All | Where-Object {
    $_.WhenCreated -gt (Get-Date).AddDays(-1) -and
    $_.IsLicensed -eq $false -and
    $_.UserType -ne "Guest"
}

foreach ($User in $NewUsers) {
    # Set usage location
    Set-MsolUser -UserPrincipalName $User.UserPrincipalName -UsageLocation US

    # Assign default license (E3)
    Set-MsolUserLicense -UserPrincipalName $User.UserPrincipalName `
        -AddLicenses "contoso:ENTERPRISEPACK"

    Write-Host "Auto-assigned license to: $($User.UserPrincipalName)" -ForegroundColor Green

    # Send notification email
    Send-MailMessage -To "admin@contoso.com" `
        -From "licensing@contoso.com" `
        -Subject "License Auto-Assigned" `
        -Body "License assigned to $($User.UserPrincipalName)" `
        -SmtpServer "smtp.office365.com" -UseSSL
}
```

### Remove Licenses from Disabled Users

```powershell
# Find disabled users with licenses
$DisabledUsers = Get-MsolUser -All | Where-Object {
    $_.BlockCredential -eq $true -and
    $_.IsLicensed -eq $true
}

foreach ($User in $DisabledUsers) {
    # Get all licenses
    $Licenses = $User.Licenses.AccountSkuId

    # Remove all licenses
    foreach ($License in $Licenses) {
        Set-MsolUserLicense -UserPrincipalName $User.UserPrincipalName `
            -RemoveLicenses $License
    }

    Write-Host "Removed licenses from disabled user: $($User.UserPrincipalName)"
}
```

---

## Troubleshooting

### Problem: "User is not eligible to have a license assigned"

**Cause:** Usage location not set

**Fix:**
```powershell
Set-MsolUser -UserPrincipalName john@contoso.com -UsageLocation US
```

### Problem: "Not enough licenses available"

**Check available licenses:**
```powershell
Get-MsolAccountSku | Select-Object AccountSkuId, ActiveUnits, ConsumedUnits,
    @{Name="Available";Expression={$_.ActiveUnits - $_.ConsumedUnits}}
```

**Solution:** Purchase more licenses or remove from inactive users

### Problem: "License assignment failed"

**Check error details:**
```powershell
Get-MsolUser -UserPrincipalName john@contoso.com |
    Select-Object -ExpandProperty Licenses |
    Select-Object -ExpandProperty ServiceStatus
```

**Common fixes:**
- Verify account is not disabled
- Check usage location is set
- Ensure license is available
- Wait 15 minutes for replication

---

## Best Practices

### Do:
- ✅ **Always set UsageLocation** before assigning licenses
- ✅ **Use groups for license assignment** (Azure AD Group-Based Licensing)
- ✅ **Document license assignments** (who gets what and why)
- ✅ **Regular license audits** (monthly review of usage)
- ✅ **Remove licenses from disabled users** (cost savings)
- ✅ **Test scripts on small batch first**
- ✅ **Log all license changes**

### Don't:
- ❌ **Don't over-provision licenses** (waste of budget)
- ❌ **Don't assign all services if not needed** (disable unused services)
- ❌ **Don't forget to monitor license usage**
- ❌ **Don't assign licenses to service accounts** (use shared mailboxes instead)

---

## Quick Reference

```powershell
# Connect
Connect-MsolService

# List licenses
Get-MsolAccountSku

# Set usage location
Set-MsolUser -UserPrincipalName user@domain.com -UsageLocation US

# Assign license
Set-MsolUserLicense -UserPrincipalName user@domain.com -AddLicenses "contoso:ENTERPRISEPACK"

# Remove license
Set-MsolUserLicense -UserPrincipalName user@domain.com -RemoveLicenses "contoso:ENTERPRISEPACK"

# List licensed users
Get-MsolUser -All | Where-Object {$_.IsLicensed -eq $true}

# List unlicensed users
Get-MsolUser -All -UnlicensedUsersOnly

# Export license report
Get-MsolAccountSku | Export-Csv "licenses.csv" -NoTypeInformation
```

---

## Cost Optimization

**Monthly Review Checklist:**
- [ ] Identify disabled accounts with licenses
- [ ] Find inactive users (no sign-in >90 days)
- [ ] Review guest accounts with licenses
- [ ] Check for duplicate licenses
- [ ] Analyze unused services (disable or downgrade)
- [ ] Verify departmental license allocation
- [ ] Compare actual usage vs purchased licenses

**Cost Savings Example:**
- 500 E3 licenses @ $20/month = $10,000/month
- Remove 50 unused licenses = $1,000/month savings = $12,000/year
'''
        })

        articles.append({
            'category': 'Microsoft 365',
            'title': 'Exchange Online Mailbox Management',
            'body': r'''# Exchange Online Mailbox Management

## Overview
Complete guide to managing Exchange Online mailboxes including creation, migration, permissions, and troubleshooting.

## Prerequisites

```powershell
# Install Exchange Online Management Module
Install-Module ExchangeOnlineManagement -Force

# Connect to Exchange Online
Connect-ExchangeOnline -UserPrincipalName admin@contoso.com

# OR use modern authentication
Connect-ExchangeOnline
```

---

## Creating Mailboxes

### Create User Mailbox

```powershell
# Mailbox is automatically created when assigning Exchange license
Set-MsolUser -UserPrincipalName john@contoso.com -UsageLocation US
Set-MsolUserLicense -UserPrincipalName john@contoso.com -AddLicenses "contoso:ENTERPRISEPACK"

# Verify mailbox creation
Get-Mailbox -Identity john@contoso.com
```

### Create Shared Mailbox

```powershell
# Create shared mailbox (free, no license required)
New-Mailbox -Shared -Name "Support Team" `
    -DisplayName "Support Team" `
    -Alias support `
    -PrimarySmtpAddress support@contoso.com

# Grant Full Access permission
Add-MailboxPermission -Identity support@contoso.com `
    -User john@contoso.com `
    -AccessRights FullAccess `
    -InheritanceType All

# Grant Send As permission
Add-RecipientPermission -Identity support@contoso.com `
    -Trustee john@contoso.com `
    -AccessRights SendAs `
    -Confirm:$false
```

### Create Room Mailbox

```powershell
# Create conference room mailbox
New-Mailbox -Room -Name "Conference Room A" `
    -DisplayName "Conference Room A" `
    -Alias conferenceroom-a `
    -PrimarySmtpAddress conferenceroom-a@contoso.com

# Configure room settings
Set-CalendarProcessing -Identity conferenceroom-a@contoso.com `
    -AutomateProcessing AutoAccept `
    -AddOrganizerToSubject $false `
    -DeleteSubject $false `
    -RemovePrivateProperty $false `
    -BookingWindowInDays 180

# Set capacity
Set-Mailbox -Identity conferenceroom-a@contoso.com `
    -ResourceCapacity 10
```

### Create Equipment Mailbox

```powershell
# Create equipment mailbox (projector, vehicle, etc.)
New-Mailbox -Equipment -Name "Projector 1" `
    -DisplayName "Conference Room Projector" `
    -Alias projector1 `
    -PrimarySmtpAddress projector1@contoso.com

# Auto-accept bookings
Set-CalendarProcessing -Identity projector1@contoso.com `
    -AutomateProcessing AutoAccept
```

---

## Mailbox Permissions

### Full Access Permission

```powershell
# Grant full access (user can open mailbox)
Add-MailboxPermission -Identity manager@contoso.com `
    -User assistant@contoso.com `
    -AccessRights FullAccess `
    -InheritanceType All

# Grant full access without automapping
Add-MailboxPermission -Identity manager@contoso.com `
    -User assistant@contoso.com `
    -AccessRights FullAccess `
    -AutoMapping $false

# Remove full access
Remove-MailboxPermission -Identity manager@contoso.com `
    -User assistant@contoso.com `
    -AccessRights FullAccess `
    -Confirm:$false
```

### Send As Permission

```powershell
# Grant Send As (send emails appearing from mailbox)
Add-RecipientPermission -Identity manager@contoso.com `
    -Trustee assistant@contoso.com `
    -AccessRights SendAs `
    -Confirm:$false

# Remove Send As
Remove-RecipientPermission -Identity manager@contoso.com `
    -Trustee assistant@contoso.com `
    -AccessRights SendAs `
    -Confirm:$false
```

### Send on Behalf Permission

```powershell
# Grant Send on Behalf (shows "on behalf of")
Set-Mailbox -Identity manager@contoso.com `
    -GrantSendOnBehalfTo @{Add="assistant@contoso.com"}

# Remove Send on Behalf
Set-Mailbox -Identity manager@contoso.com `
    -GrantSendOnBehalfTo @{Remove="assistant@contoso.com"}
```

### Folder Permissions

```powershell
# Grant calendar permissions
Add-MailboxFolderPermission -Identity "john@contoso.com:\Calendar" `
    -User jane@contoso.com `
    -AccessRights Editor

# Common access rights:
# - Owner: Full control
# - Editor: Read, create, modify, delete all items
# - Reviewer: Read only
# - Contributor: Create items
# - Author: Read, create, modify own items
```

---

## Mailbox Configuration

### Set Mailbox Quota

```powershell
# Set mailbox size limits
Set-Mailbox -Identity john@contoso.com `
    -ProhibitSendQuota 49GB `
    -ProhibitSendReceiveQuota 50GB `
    -IssueWarningQuota 48GB

# Set archive quota
Set-Mailbox -Identity john@contoso.com `
    -ArchiveQuota 100GB `
    -ArchiveWarningQuota 90GB
```

### Enable Archive Mailbox

```powershell
# Enable online archive
Enable-Mailbox -Identity john@contoso.com -Archive

# Verify archive enabled
Get-Mailbox -Identity john@contoso.com |
    Select-Object DisplayName, ArchiveStatus, ArchiveGuid
```

### Configure Litigation Hold

```powershell
# Enable litigation hold (preserves all items)
Set-Mailbox -Identity john@contoso.com `
    -LitigationHoldEnabled $true `
    -LitigationHoldDuration 2555  # Days (7 years)

# Verify hold
Get-Mailbox -Identity john@contoso.com |
    Select-Object DisplayName, LitigationHoldEnabled, LitigationHoldDuration
```

### Email Forwarding

```powershell
# Forward emails to another address
Set-Mailbox -Identity john@contoso.com `
    -ForwardingSmtpAddress "external@example.com" `
    -DeliverToMailboxAndForward $true

# Forward to internal user
Set-Mailbox -Identity john@contoso.com `
    -ForwardingAddress "jane@contoso.com" `
    -DeliverToMailboxAndForward $true

# Disable forwarding
Set-Mailbox -Identity john@contoso.com `
    -ForwardingSmtpAddress $null `
    -ForwardingAddress $null
```

### Out of Office (Automatic Replies)

```powershell
# Set automatic reply
Set-MailboxAutoReplyConfiguration -Identity john@contoso.com `
    -AutoReplyState Enabled `
    -InternalMessage "I'm out of office until Monday." `
    -ExternalMessage "I'm currently away. For urgent matters, contact support@contoso.com"

# Set with date range
Set-MailboxAutoReplyConfiguration -Identity john@contoso.com `
    -AutoReplyState Scheduled `
    -StartTime "12/20/2024 5:00 PM" `
    -EndTime "01/02/2025 8:00 AM" `
    -InternalMessage "Out for holidays" `
    -ExternalMessage "Out for holidays"

# Disable automatic reply
Set-MailboxAutoReplyConfiguration -Identity john@contoso.com `
    -AutoReplyState Disabled
```

---

## Mailbox Migration

### Migrate from On-Premises Exchange

```powershell
# Create migration endpoint
New-MigrationEndpoint -ExchangeRemoteMove `
    -Name "OnPrem-Endpoint" `
    -Autodiscover `
    -EmailAddress admin@contoso.com `
    -Credentials (Get-Credential)

# Create migration batch
New-MigrationBatch -Name "Batch1-Users" `
    -SourceEndpoint "OnPrem-Endpoint" `
    -TargetDeliveryDomain "contoso.mail.onmicrosoft.com" `
    -CSVData ([System.IO.File]::ReadAllBytes("C:\migration-users.csv")) `
    -AutoStart

# Monitor migration
Get-MigrationBatch | Get-MigrationUser |
    Select-Object Identity, Status, PercentageComplete

# Complete migration
Complete-MigrationBatch -Identity "Batch1-Users"
```

### Migrate from Gmail (IMAP)

```powershell
# Create IMAP endpoint
$Endpoint = New-MigrationEndpoint -IMAP `
    -Name "Gmail" `
    -RemoteServer "imap.gmail.com" `
    -Port 993 `
    -Security SSL

# Create CSV: EmailAddress,UserName,Password
# john@contoso.com,john@gmail.com,app-specific-password

# Create migration batch
New-MigrationBatch -Name "Gmail-Migration" `
    -SourceEndpoint "Gmail" `
    -TargetDeliveryDomain "contoso.mail.onmicrosoft.com" `
    -CSVData ([System.IO.File]::ReadAllBytes("C:\gmail-users.csv")) `
    -AutoStart
```

---

## Mailbox Reports

### Mailbox Size Report

```powershell
# Get mailbox sizes
Get-Mailbox -ResultSize Unlimited | Get-MailboxStatistics |
    Select-Object DisplayName,
        @{Name="MailboxSize(GB)";Expression={[math]::Round(($_.TotalItemSize.Value.ToBytes() / 1GB), 2)}},
        ItemCount,
        LastLogonTime |
    Sort-Object "MailboxSize(GB)" -Descending |
    Export-Csv "C:\Reports\MailboxSizes.csv" -NoTypeInformation
```

### Inactive Mailboxes Report

```powershell
# Find mailboxes not accessed in 90 days
Get-Mailbox -ResultSize Unlimited | Get-MailboxStatistics |
    Where-Object {$_.LastLogonTime -lt (Get-Date).AddDays(-90)} |
    Select-Object DisplayName, LastLogonTime,
        @{Name="DaysSinceLastLogon";Expression={(New-TimeSpan -Start $_.LastLogonTime -End (Get-Date)).Days}} |
    Sort-Object LastLogonTime |
    Export-Csv "C:\Reports\InactiveMailboxes.csv" -NoTypeInformation
```

### Shared Mailbox Report

```powershell
# List all shared mailboxes with permissions
Get-Mailbox -RecipientTypeDetails SharedMailbox -ResultSize Unlimited |
    ForEach-Object {
        $Mailbox = $_
        $Permissions = Get-MailboxPermission -Identity $Mailbox.Identity |
            Where-Object {$_.User -notlike "NT AUTHORITY\*" -and $_.IsInherited -eq $false}

        foreach ($Perm in $Permissions) {
            [PSCustomObject]@{
                SharedMailbox = $Mailbox.DisplayName
                User = $Perm.User
                AccessRights = $Perm.AccessRights -join ","
            }
        }
    } | Export-Csv "C:\Reports\SharedMailboxPermissions.csv" -NoTypeInformation
```

### Forwarding Report

```powershell
# Find mailboxes with forwarding enabled
Get-Mailbox -ResultSize Unlimited |
    Where-Object {$_.ForwardingSmtpAddress -ne $null -or $_.ForwardingAddress -ne $null} |
    Select-Object DisplayName, PrimarySmtpAddress, ForwardingSmtpAddress, ForwardingAddress, DeliverToMailboxAndForward |
    Export-Csv "C:\Reports\Forwarding.csv" -NoTypeInformation
```

---

## Troubleshooting

### Problem: Mailbox not appearing in address list

```powershell
# Check hidden from address lists
Get-Mailbox -Identity john@contoso.com |
    Select-Object DisplayName, HiddenFromAddressListsEnabled

# Unhide
Set-Mailbox -Identity john@contoso.com -HiddenFromAddressListsEnabled $false
```

### Problem: Cannot send emails

```powershell
# Check send limits
Get-Mailbox -Identity john@contoso.com |
    Select-Object RecipientLimits, MaxSendSize, MaxReceiveSize

# Increase send limit
Set-Mailbox -Identity john@contoso.com -MaxSendSize 35MB
```

### Problem: Mailbox full

```powershell
# Check mailbox size
Get-MailboxStatistics -Identity john@contoso.com |
    Select-Object DisplayName, TotalItemSize, ItemCount, DatabaseName

# Enable archive
Enable-Mailbox -Identity john@contoso.com -Archive

# Increase quota (if allowed by license)
Set-Mailbox -Identity john@contoso.com -ProhibitSendReceiveQuota 100GB
```

### Problem: Delayed mailbox creation

```powershell
# Force mailbox creation (usually takes 15-30 minutes)
# Verify license assigned
Get-MsolUser -UserPrincipalName john@contoso.com |
    Select-Object DisplayName, IsLicensed, Licenses

# Wait and check again
Start-Sleep -Seconds 300
Get-Mailbox -Identity john@contoso.com
```

---

## Best Practices

### Do:
- ✅ **Use shared mailboxes** for team accounts (free, no license)
- ✅ **Enable archive mailboxes** before users hit quota
- ✅ **Set litigation hold** for compliance/legal requirements
- ✅ **Regular permission audits** (who has access to what)
- ✅ **Monitor mailbox sizes** (prevent quota issues)
- ✅ **Document delegated access** (maintain security)
- ✅ **Use distribution groups** instead of individual forwarding

### Don't:
- ❌ **Don't share mailbox passwords** (use delegation instead)
- ❌ **Don't exceed 50GB for shared mailboxes** (convert to licensed mailbox)
- ❌ **Don't forward to personal email** (data loss risk)
- ❌ **Don't grant unnecessary Full Access** (use specific folders)
- ❌ **Don't delete mailboxes immediately** (convert to shared or inactive)

---

## Quick Reference

```powershell
# Connect
Connect-ExchangeOnline

# Create shared mailbox
New-Mailbox -Shared -Name "Support" -PrimarySmtpAddress support@contoso.com

# Grant permissions
Add-MailboxPermission -Identity mailbox@contoso.com -User user@contoso.com -AccessRights FullAccess

# Enable archive
Enable-Mailbox -Identity user@contoso.com -Archive

# Set forwarding
Set-Mailbox -Identity user@contoso.com -ForwardingAddress forward@contoso.com

# Get mailbox size
Get-MailboxStatistics -Identity user@contoso.com

# List all mailboxes
Get-Mailbox -ResultSize Unlimited

# Export mailbox list
Get-Mailbox -ResultSize Unlimited | Export-Csv "mailboxes.csv" -NoTypeInformation
```
'''
        })

        articles.append({
            'category': 'Active Directory',
            'title': 'Active Directory Backup and Disaster Recovery',
            'body': r'''# Active Directory Backup and Disaster Recovery

## Overview
Comprehensive guide to backing up and recovering Active Directory Domain Controllers including System State backups, authoritative restores, and disaster recovery procedures.

## Backup Types

### System State Backup
**Includes:**
- Active Directory database (NTDS.DIT)
- SYSVOL folder
- Registry
- Boot files
- System files
- COM+ registration database

### Types of AD Restores:
1. **Non-Authoritative Restore**: DC restored, then replicates latest changes from other DCs
2. **Authoritative Restore**: Marks restored objects as authoritative, replicates to other DCs
3. **Primary Restore**: First DC restored in forest (all DCs offline)

---

## Windows Server Backup

### Install Windows Server Backup

```powershell
# Install feature
Install-WindowsFeature Windows-Server-Backup -IncludeManagementTools

# Verify installation
Get-WindowsFeature Windows-Server-Backup
```

### Perform System State Backup

```powershell
# Backup System State to local disk
wbadmin start systemstatebackup -backupTarget:E: -quiet

# Backup to network share
wbadmin start systemstatebackup `
    -backupTarget:\\backup-server\DCBackups\DC01 `
    -quiet

# Backup with verbose output
wbadmin start systemstatebackup -backupTarget:E: -quiet
```

### Schedule Daily System State Backups

```powershell
# Create scheduled task for daily backup at 11 PM
$Action = New-ScheduledTaskAction -Execute "wbadmin.exe" `
    -Argument "start systemstatebackup -backupTarget:E: -quiet"

$Trigger = New-ScheduledTaskTrigger -Daily -At "11:00PM"

$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
    -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "Daily AD Backup" `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Description "Daily System State backup of Domain Controller"
```

### View Backup History

```powershell
# List all backups
wbadmin get versions

# Get details of specific backup
wbadmin get versions -backupTarget:E:

# Sample output:
# Backup time: 1/14/2024 11:00 PM
# Backup location: Disk labeled Backup(E:)
# Version identifier: 01/14/2024-23:00
```

---

## Non-Authoritative Restore

Use when DC fails but other DCs are healthy. Restored DC will replicate latest changes from partners.

### Steps:

**1. Boot into Directory Services Restore Mode (DSRM)**

```
1. Restart DC
2. Press F8 during boot
3. Select "Directory Services Restore Mode"
4. Login with DSRM password
```

**2. Identify Backup to Restore**

```cmd
wbadmin get versions -backupTarget:E:
```

**3. Perform Non-Authoritative Restore**

```cmd
# Restore System State
wbadmin start systemstaterecovery `
    -version:01/14/2024-23:00 `
    -backupTarget:E: `
    -quiet

# Restart in normal mode
shutdown /r /t 0
```

**4. Verify Replication**

```powershell
# After reboot, check replication
repadmin /showrepl
repadmin /replsummary
```

---

## Authoritative Restore

Use when recovering deleted objects (users, groups, OUs) that should override changes on other DCs.

### Restore Deleted User

**1. Boot into DSRM and perform non-authoritative restore first**

```cmd
wbadmin start systemstaterecovery -version:01/14/2024-23:00 -backupTarget:E: -quiet
```

**2. Before rebooting, mark object as authoritative**

```cmd
# Start ntdsutil
ntdsutil

# Activate instance
activate instance ntds

# Enter authoritative restore mode
authoritative restore

# Restore specific user
restore object "CN=John Doe,OU=Users,OU=Employees,DC=contoso,DC=local"

# OR restore entire OU
restore subtree "OU=Employees,DC=contoso,DC=local"

# Exit ntdsutil
quit
quit
```

**3. Reboot normally**

```cmd
shutdown /r /t 0
```

**Object will replicate with higher version number to all DCs**

### Restore Deleted Group

```cmd
ntdsutil
activate instance ntds
authoritative restore
restore object "CN=IT Admins,OU=Groups,DC=contoso,DC=local"
quit
quit
```

### Restore Entire Organizational Unit

```cmd
ntdsutil
activate instance ntds
authoritative restore
restore subtree "OU=Finance,DC=contoso,DC=local"
quit
quit
```

---

## Active Directory Recycle Bin (Preferred Method)

**Requirements:**
- Forest functional level: Windows Server 2008 R2 or higher
- Must be enabled before objects are deleted

### Enable AD Recycle Bin

```powershell
# Enable Recycle Bin (one-way operation - cannot be disabled!)
Enable-ADOptionalFeature -Identity 'Recycle Bin Feature' `
    -Scope ForestOrConfigurationSet `
    -Target 'contoso.local' `
    -Confirm:$false

# Verify enabled
Get-ADOptionalFeature -Filter {Name -like "Recycle Bin*"}
```

### Restore Deleted Objects with Recycle Bin

```powershell
# View recently deleted objects
Get-ADObject -Filter {IsDeleted -eq $true} -IncludeDeletedObjects |
    Select-Object Name, ObjectClass, WhenChanged, DistinguishedName

# Restore specific user
Get-ADObject -Filter {DisplayName -eq "John Doe"} `
    -IncludeDeletedObjects |
    Restore-ADObject

# Restore by distinguished name
Get-ADObject -Identity "CN=John Doe\0ADEL:12345678-1234-1234-1234-123456789012,CN=Deleted Objects,DC=contoso,DC=local" `
    -IncludeDeletedObjects |
    Restore-ADObject

# Restore entire OU
Get-ADObject -Filter {lastKnownParent -eq "OU=Finance,DC=contoso,DC=local"} `
    -IncludeDeletedObjects |
    Restore-ADObject

# Restore all objects deleted in last 24 hours
$Yesterday = (Get-Date).AddDays(-1)
Get-ADObject -Filter {IsDeleted -eq $true -and WhenChanged -gt $Yesterday} `
    -IncludeDeletedObjects |
    Restore-ADObject
```

---

## Full Forest Recovery

Use when all DCs are offline/corrupted. Rebuild entire forest from backups.

### Recovery Steps:

**1. Restore First DC (PDC Emulator)**

```
1. Disconnect network
2. Boot into DSRM
3. Perform non-authoritative restore
4. Mark database as primary restore:
```

```cmd
ntdsutil
activate instance ntds
files
authoritative restore
restore database verifynow
quit
quit
```

**2. Mark FSMO Roles**

```powershell
# After reboot, seize all FSMO roles
Move-ADDirectoryServerOperationMasterRole -Identity "DC01" `
    -OperationMasterRole PDCEmulator,RIDMaster,InfrastructureMaster,SchemaMaster,DomainNamingMaster `
    -Force
```

**3. Clean Metadata of Failed DCs**

```powershell
# Remove old DC metadata
ntdsutil
metadata cleanup
connections
connect to server DC01
quit
select operation target
list domains
select domain 0
list sites
select site 0
list servers in site
select server 1  # (Old DC to remove)
quit
remove selected server
quit
quit
```

**4. Build Additional DCs**

```powershell
# Promote new DCs after first DC is operational
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools

Install-ADDSDomainController `
    -DomainName "contoso.local" `
    -Credential (Get-Credential "CONTOSO\Administrator") `
    -InstallDns:$true `
    -Force
```

---

## Backup Best Practices

### Backup Schedule

**Recommended:**
- **Daily**: System State backup
- **Weekly**: Full server backup
- **Monthly**: Offsite backup copy
- **Retention**: 180 days minimum (AD tombstone lifetime)

```powershell
# Example: Daily at 11 PM, keep 7 backups
wbadmin start backup `
    -backupTarget:E: `
    -include:C:,D: `
    -systemState `
    -quiet

# Delete backups older than 7 days
wbadmin delete systemstatebackup -keepVersions:7 -backupTarget:E: -quiet
```

### Multiple DC Backups

**Golden Rule:** Backup at least 2 DCs in each domain
- Primary: PDC Emulator
- Secondary: Any other DC

**Why?** Redundancy if one backup is corrupted

### Verify Backups

```powershell
# Test backup integrity monthly
wbadmin start sysrecovery `
    -version:01/14/2024-23:00 `
    -backupTarget:E: `
    -recreateDisks `
    -quiet

# Document restore procedures
# Perform test restore quarterly
```

---

## DSRM Password Management

### Set DSRM Password

```powershell
# Set DSRM password on local DC
ntdsutil
set dsrm password
reset password on server null
# Enter new password twice
quit
quit
```

### Sync DSRM Password with Domain Admin

```powershell
# Sync DSRM password with current user account password
ntdsutil
set dsrm password
sync from domain account administrator
quit
quit
```

### Best Practices:
- ✅ Document DSRM password securely (password vault)
- ✅ Change DSRM password annually
- ✅ Use complex password (20+ characters)
- ✅ Store in secure location separate from DCs

---

## Disaster Recovery Checklist

### Before Disaster:
- [ ] Multiple DCs per domain (minimum 2)
- [ ] Daily System State backups
- [ ] Offsite backup copies
- [ ] Document FSMO role holders
- [ ] Document DSRM passwords
- [ ] Test restore procedures quarterly
- [ ] Maintain AD documentation

### During Recovery:
- [ ] Assess scope of failure
- [ ] Isolate network if needed
- [ ] Identify backup to restore
- [ ] Boot into DSRM
- [ ] Perform appropriate restore type
- [ ] Verify replication after restore
- [ ] Update documentation

### After Recovery:
- [ ] Run dcdiag on all DCs
- [ ] Verify FSMO roles
- [ ] Check replication health
- [ ] Review event logs
- [ ] Update disaster recovery plan
- [ ] Document lessons learned

---

## Common Scenarios

### Scenario 1: Accidentally Deleted 50 Users

**Solution:** AD Recycle Bin (if enabled)
```powershell
Get-ADObject -Filter {IsDeleted -eq $true -and ObjectClass -eq "user"} `
    -IncludeDeletedObjects |
    Restore-ADObject
```

**Alternative:** Authoritative restore from backup

### Scenario 2: DC Hardware Failure

**Solution:** Non-authoritative restore on new hardware
1. Install Windows Server on new hardware
2. Restore System State from backup
3. DC will replicate latest changes from partners

### Scenario 3: All DCs Offline (Ransomware)

**Solution:** Full forest recovery
1. Isolate network
2. Restore first DC (PDC Emulator) from clean backup
3. Seize FSMO roles
4. Clean metadata of failed DCs
5. Build replacement DCs

---

## Quick Reference

```cmd
# Backup System State
wbadmin start systemstatebackup -backupTarget:E: -quiet

# List backups
wbadmin get versions

# Non-authoritative restore (in DSRM)
wbadmin start systemstaterecovery -version:01/14/2024-23:00 -backupTarget:E: -quiet

# Authoritative restore (in DSRM, before reboot)
ntdsutil
activate instance ntds
authoritative restore
restore object "CN=User,OU=Users,DC=contoso,DC=local"
quit
quit

# Restore with AD Recycle Bin
Get-ADObject -Filter {DisplayName -eq "John Doe"} -IncludeDeletedObjects | Restore-ADObject

# Set DSRM password
ntdsutil
set dsrm password
reset password on server null
quit
quit
```

---

## Additional Tools

### Veeam Backup for Microsoft 365
- Application-aware AD backups
- Granular object restore
- No DSRM required

### Quest Recovery Manager for Active Directory
- GUI-based restore
- Object-level recovery
- Compare and rollback

### Semperis Directory Services Protector
- Real-time AD monitoring
- Automated threat detection
- Rapid recovery
'''
        })

        articles.append({
            'category': 'Active Directory',
            'title': 'Active Directory Replication Troubleshooting',
            'body': r'''# Active Directory Replication Troubleshooting

## Overview
Comprehensive guide to diagnosing and resolving Active Directory replication issues including tools, common problems, and step-by-step solutions.

## Replication Basics

### What Replicates:
- Directory database (NTDS.DIT)
- SYSVOL (Group Policies, login scripts)
- Schema changes
- Configuration partition
- Application partitions (DNS)

### Replication Topology:
- **Intrasite**: Fast, automatic every 15 seconds
- **Intersite**: Scheduled, configurable (default: every 180 minutes)
- **Knowledge Consistency Checker (KCC)**: Auto-creates replication topology

---

## Replication Monitoring Tools

### repadmin - Primary Diagnostic Tool

```cmd
# Show replication status for all DCs
repadmin /replsummary

# Show detailed replication partners
repadmin /showrepl

# Show replication status for specific DC
repadmin /showrepl DC01

# Check replication health
repadmin /replicate DC02 DC01 "DC=contoso,DC=local"

# Force replication between two DCs
repadmin /syncall /AeD

# Show replication queue
repadmin /queue
```

### dcdiag - Health Diagnostics

```cmd
# Run all tests on local DC
dcdiag

# Run all tests on specific DC
dcdiag /s:DC01

# Test replication specifically
dcdiag /test:replications

# Comprehensive test including DNS
dcdiag /v /c /d /e /s:DC01

# Test specific domain controller
dcdiag /test:replications /s:DC01 /v
```

---

## Check Replication Status

### Quick Health Check

```powershell
# PowerShell: Check all DCs
Get-ADReplicationPartnerMetadata -Target * -Scope Server |
    Select-Object Server, Partner, LastReplicationSuccess, LastReplicationResult |
    Sort-Object LastReplicationSuccess

# Show replication failures
Get-ADReplicationFailure -Target * -Scope Server
```

### View Replication Summary

```cmd
repadmin /replsum

# Output shows:
# Source DSA: DC01
# Largest Delta: 2h:35m
# Fails/Total: 0/12 (0%)
```

### Check Specific Partition

```cmd
# Check domain partition
repadmin /showrepl DC01 "DC=contoso,DC=local"

# Check configuration partition
repadmin /showrepl DC01 "CN=Configuration,DC=contoso,DC=local"

# Check schema partition
repadmin /showrepl DC01 "CN=Schema,CN=Configuration,DC=contoso,DC=local"
```

---

## Common Replication Errors

### Error 8524: "The DSA operation is unable to proceed"

**Cause:** DNS resolution failure

**Fix:**
```cmd
# Verify DNS resolution
nslookup DC01.contoso.local

# Register DC in DNS
ipconfig /registerdns

# Restart Netlogon service
net stop netlogon && net start netlogon

# Force DC to re-register
nltest /dsregdns
```

### Error 8453: "Replication access was denied"

**Cause:** Permissions or security settings

**Fix:**
```powershell
# Check if DC computer account is in Domain Controllers group
Get-ADGroupMember "Domain Controllers" | Select Name

# Reset secure channel
nltest /sc_reset:contoso.local

# Reset DC password
netdom resetpwd /server:DC01 /userd:administrator /passwordd:*
```

### Error 1722: "The RPC server is unavailable"

**Cause:** Network connectivity, firewall, or RPC service issues

**Fix:**
```cmd
# Test network connectivity
ping DC01
ping -a DC01

# Test RPC connectivity
portqry -n DC01 -e 135

# Verify required firewall ports open:
# - RPC: 135
# - RPC Dynamic: 49152-65535
# - LDAP: 389
# - LDAPS: 636
# - SMB: 445
# - Kerberos: 88
# - DNS: 53

# Restart RPC service
net stop rpcss && net start rpcss
```

### Error 8606: "Insufficient attributes were given to create an object"

**Cause:** Corrupted metadata or schema mismatch

**Fix:**
```cmd
# Clean up metadata
ntdsutil
metadata cleanup
connections
connect to server DC01
quit
select operation target
list domains
select domain 0
list sites
select site 0
list servers in site
select server 1 (old/failed DC)
quit
remove selected server
quit
quit

# Force replication
repadmin /syncall /AeD
```

### Error 8614: "The directory service cannot replicate with this server"

**Cause:** Incompatible functional levels or schema versions

**Fix:**
```powershell
# Check functional levels
Get-ADForest | Select ForestMode
Get-ADDomain | Select DomainMode

# Check schema version
Get-ADObject (Get-ADRootDSE).schemaNamingContext -Property objectVersion

# Upgrade functional level if needed
Set-ADDomainMode -Identity contoso.local -DomainMode Windows2016Domain
Set-ADForestMode -Identity contoso.local -ForestMode Windows2016Forest
```

---

## SYSVOL Replication Issues

### Check SYSVOL State

```cmd
# Verify SYSVOL shared
net share

# Check FRS replication (older)
ntfrsutl ds

# Check DFSR replication (newer)
dfsrdiag replicationstate

# Get DFSR health report
dfsrdiag /testdfsrhealth /member:DC01 /rgname:"Domain System Volume"
```

### DFSR Not Replicating

**Check DFSR service:**
```cmd
# Verify DFSR service running
sc query DFSR

# Start if stopped
net start DFSR

# Check DFSR backlog
dfsrdiag backlog /rgname:"Domain System Volume" /rfname:"SYSVOL Share" /sendingmember:DC01 /receivingmember:DC02
```

### Authoritative SYSVOL Restore

```cmd
# On authoritative DC
net stop dfsr
net start dfsr

# Set authoritative flag
repadmin /syncall DC01 /d /e /P

# On non-authoritative DCs
net stop dfsr
# Delete SYSVOL contents (backup first!)
# Start DFSR
net start dfsr
```

---

## Force Replication

### Force All Partitions

```cmd
# Force inbound replication from all partners
repadmin /syncall DC01 /AeD

# Flags explained:
# /A = All partitions
# /e = Enterprise (all DCs in forest)
# /D = Identify servers by DN (not GUID)
```

### Force Specific Partition

```cmd
# Force replication of domain partition
repadmin /replicate DC02 DC01 "DC=contoso,DC=local"

# Force configuration partition
repadmin /replicate DC02 DC01 "CN=Configuration,DC=contoso,DC=local"

# Force schema partition
repadmin /replicate DC02 DC01 "CN=Schema,CN=Configuration,DC=contoso,DC=local"
```

---

## Replication Topology Issues

### View Replication Topology

```cmd
# Show connection objects
repadmin /showconn DC01

# Show bridgehead servers
repadmin /bridgeheads

# Show sites and site links
repadmin /siteoptions
```

### Rebuild Replication Topology

```cmd
# Force KCC to recalculate topology
repadmin /kcc DC01

# Rebuild entire topology
repadmin /kcc * /async
```

### Check for Lingering Objects

```cmd
# Scan for lingering objects
repadmin /removelingeringobjects DC01 12345678-1234-1234-1234-123456789012 "DC=contoso,DC=local" /advisory_mode

# Remove lingering objects
repadmin /removelingeringobjects DC01 12345678-1234-1234-1234-123456789012 "DC=contoso,DC=local"
```

---

## Performance Optimization

### Check Replication Performance

```cmd
# Show replication latency
repadmin /showrepl /csv > replication-status.csv

# Analyze in PowerShell
Import-Csv replication-status.csv |
    Where-Object {$_."Last Success" -lt (Get-Date).AddHours(-24)} |
    Select-Object "Source DSA", "Naming Context", "Last Success"
```

### Optimize Site Links

```powershell
# Reduce replication interval (default: 180 minutes)
Get-ADReplicationSiteLink -Filter * |
    Set-ADReplicationSiteLink -ReplicationFrequencyInMinutes 60

# Enable change notification for intersite replication
Get-ADReplicationSiteLink -Filter * |
    Set-ADReplicationSiteLink -Options "USE_NOTIFY"
```

---

## Event Log Analysis

### Key Event IDs

**Success:**
- **1126**: NTFRS successfully joined the replica set
- **13516**: DFSR successfully established connection

**Errors:**
- **13508**: DFSR couldn't communicate with partner
- **5805**: Session setup failed (authentication)
- **1864**: Replication link failed
- **2042**: Too much time since last replication

### View Replication Events

```powershell
# Get recent replication errors (last 24 hours)
Get-EventLog -LogName "Directory Service" -After (Get-Date).AddDays(-1) |
    Where-Object {$_.EventID -in @(1864,2042,5805)} |
    Select-Object TimeGenerated, EntryType, Message |
    Format-List

# Get DFSR replication events
Get-EventLog -LogName "DFS Replication" -After (Get-Date).AddDays(-1) |
    Where-Object {$_.EventID -in @(13508,13516)} |
    Format-List
```

---

## Disaster Recovery Scenarios

### Scenario 1: New DC Not Replicating

**Steps:**
1. Verify DNS resolution
2. Check network connectivity
3. Verify firewall ports
4. Force replication
5. Check event logs

```cmd
# Test DNS
nslookup DC02.contoso.local

# Test connectivity
ping DC02
Test-NetConnection DC02 -Port 389

# Force replication
repadmin /replicate DC01 DC02 "DC=contoso,DC=local"

# Check status
repadmin /showrepl DC02
```

### Scenario 2: Replication Stopped Hours Ago

**Steps:**
1. Check network
2. Verify services running
3. Check event logs
4. Force replication
5. Monitor

```cmd
# Check AD services
sc query NTDS
sc query DFSR
sc query DNS

# Restart services if needed
net stop NTDS && net start NTDS

# Force full sync
repadmin /syncall /AeD
```

### Scenario 3: SYSVOL Not Replicating

**Steps:**
1. Check DFSR/FRS service
2. Verify SYSVOL share
3. Check backlog
4. Force SYSVOL sync

```cmd
# Check SYSVOL
net share

# Check DFSR
sc query DFSR

# Check backlog
dfsrdiag backlog /rgname:"Domain System Volume" /rfname:"SYSVOL Share" /sendingmember:DC01 /receivingmember:DC02

# Force sync
dfsrdiag syncnow /partner:DC01 /rgname:"Domain System Volume" /time:1
```

---

## Monitoring & Reporting

### Daily Health Check Script

```powershell
# Check replication health across all DCs
$DCs = Get-ADDomainController -Filter *

foreach ($DC in $DCs) {
    Write-Host "Checking $($DC.Name)..." -ForegroundColor Yellow

    # Run replication test
    $Result = dcdiag /test:replications /s:$DC.Name

    if ($Result -match "failed") {
        Write-Host "FAILED on $($DC.Name)" -ForegroundColor Red
        Send-MailMessage -To "admin@contoso.com" `
            -From "monitoring@contoso.com" `
            -Subject "AD Replication Failure" `
            -Body "Replication failed on $($DC.Name)" `
            -SmtpServer "smtp.contoso.com"
    } else {
        Write-Host "OK on $($DC.Name)" -ForegroundColor Green
    }
}
```

### Generate Replication Report

```powershell
# Comprehensive replication report
$Report = @()

Get-ADReplicationPartnerMetadata -Target * -Scope Server | ForEach-Object {
    $Report += [PSCustomObject]@{
        Server = $_.Server
        Partner = $_.Partner
        LastSuccess = $_.LastReplicationSuccess
        LastAttempt = $_.LastReplicationAttempt
        Consecutive Failures = $_.ConsecutiveReplicationFailures
        LastResult = $_.LastReplicationResult
    }
}

$Report | Export-Csv "C:\Reports\AD-Replication-$(Get-Date -Format 'yyyy-MM-dd').csv" -NoTypeInformation
```

---

## Best Practices

### Do:
- ✅ **Monitor replication daily** (automated health checks)
- ✅ **Multiple DCs per site** (minimum 2)
- ✅ **Document topology** (site links, costs)
- ✅ **Regular dcdiag tests** (weekly minimum)
- ✅ **Maintain time sync** (critical for Kerberos/replication)
- ✅ **Firewall exceptions** for all required ports
- ✅ **Fast network links** between sites (>512 Kbps)

### Don't:
- ❌ **Don't ignore replication errors** (investigate immediately)
- ❌ **Don't force seize FSMO** unless absolutely necessary
- ❌ **Don't manually edit replication topology** (let KCC manage)
- ❌ **Don't have only one DC** (single point of failure)
- ❌ **Don't disable replication compression** (wastes bandwidth)

---

## Quick Reference

```cmd
# Check replication status
repadmin /replsummary
repadmin /showrepl

# Run diagnostics
dcdiag /test:replications

# Force replication
repadmin /syncall /AeD

# Check replication queue
repadmin /queue

# View partners
repadmin /showconn

# Check SYSVOL
net share
dfsrdiag replicationstate

# Remove lingering objects
repadmin /removelingeringobjects DC01 <GUID> "DC=contoso,DC=local" /advisory_mode

# View events
Get-EventLog -LogName "Directory Service" -Newest 50
```

---

## Required Firewall Ports

| Protocol | Port | Service |
|----------|------|---------|
| TCP/UDP | 53 | DNS |
| TCP | 88 | Kerberos |
| TCP/UDP | 389 | LDAP |
| TCP | 636 | LDAPS |
| TCP/UDP | 445 | SMB |
| TCP | 135 | RPC Endpoint Mapper |
| TCP | 49152-65535 | RPC Dynamic Ports |
| TCP/UDP | 464 | Kerberos Password |
| TCP | 3268 | Global Catalog |
| TCP | 3269 | Global Catalog SSL |
'''
        })

        articles.append({
            'category': 'Active Directory',
            'title': 'Active Directory Password Policies and Fine-Grained Password Policies',
            'body': r'''# Active Directory Password Policies and Fine-Grained Password Policies

## Overview
Complete guide to managing password policies in Active Directory including domain-wide policies and Fine-Grained Password Policies (FGPP) for specific users/groups.

## Domain Password Policy (Default)

### View Current Policy

```powershell
# View default domain policy
Get-ADDefaultDomainPasswordPolicy

# Output shows:
# ComplexityEnabled: True
# LockoutDuration: 00:30:00
# LockoutObservationWindow: 00:30:00
# LockoutThreshold: 5
# MaxPasswordAge: 42.00:00:00 (42 days)
# MinPasswordAge: 1.00:00:00 (1 day)
# MinPasswordLength: 7
# PasswordHistoryCount: 24
# ReversibleEncryptionEnabled: False
```

### Modify Default Policy

```powershell
# Set password requirements
Set-ADDefaultDomainPasswordPolicy -Identity contoso.local `
    -MinPasswordLength 12 `
    -ComplexityEnabled $true `
    -MaxPasswordAge "90.00:00:00" `
    -MinPasswordAge "1.00:00:00" `
    -PasswordHistoryCount 24

# Set account lockout
Set-ADDefaultDomainPasswordPolicy -Identity contoso.local `
    -LockoutThreshold 5 `
    -LockoutDuration "00:30:00" `
    -LockoutObservationWindow "00:30:00"
```

### Password Policy Settings Explained

**MinPasswordLength:**
- Minimum characters required
- Recommended: 12-14 characters
- Industry standard: 14+

**ComplexityEnabled:**
- Requires 3 of 4: uppercase, lowercase, numbers, special characters
- Cannot contain username
- Recommended: $true

**MaxPasswordAge:**
- How long until password must be changed
- Recommended: 90-180 days (or never with MFA)
- NIST recommends: No expiration if using long passphrases + MFA

**MinPasswordAge:**
- Prevents immediate password changes
- Prevents bypassing password history
- Recommended: 1 day

**PasswordHistoryCount:**
- Number of old passwords remembered
- Cannot reuse passwords in history
- Recommended: 24

**LockoutThreshold:**
- Failed login attempts before lockout
- 0 = never lock (not recommended)
- Recommended: 5-10

**LockoutDuration:**
- How long account stays locked
- 0 = administrator must unlock
- Recommended: 30 minutes

**Lockout ObservationWindow:**
- Time window for failed attempts counter
- Resets after this time
- Recommended: 30 minutes

---

## Fine-Grained Password Policies (FGPP)

**Requirements:**
- Domain functional level: Windows Server 2008 or higher
- Applied to users or global security groups
- Can have multiple policies with different precedence

### Create FGPP

```powershell
# Create policy for executives (stricter)
New-ADFineGrainedPasswordPolicy `
    -Name "Executive-Policy" `
    -Precedence 10 `
    -ComplexityEnabled $true `
    -Description "Password policy for executives" `
    -DisplayName "Executive Password Policy" `
    -LockoutDuration "01:00:00" `
    -LockoutObservationWindow "01:00:00" `
    -LockoutThreshold 3 `
    -MaxPasswordAge "60.00:00:00" `
    -MinPasswordAge "1.00:00:00" `
    -MinPasswordLength 16 `
    -PasswordHistoryCount 24 `
    -ReversibleEncryptionEnabled $false
```

### Apply FGPP to Group

```powershell
# Apply to security group
Add-ADFineGrainedPasswordPolicySubject `
    -Identity "Executive-Policy" `
    -Subjects "CN=Executives,OU=Groups,DC=contoso,DC=local"
```

### Apply FGPP to Individual User

```powershell
# Apply to specific user
Add-ADFineGrainedPasswordPolicySubject `
    -Identity "Executive-Policy" `
    -Subjects "CN=John CEO,OU=Users,DC=contoso,DC=local"
```

---

## Common FGPP Scenarios

### Policy for Service Accounts

```powershell
# Create lenient policy for service accounts
New-ADFineGrainedPasswordPolicy `
    -Name "Service-Accounts-Policy" `
    -Precedence 100 `
    -ComplexityEnabled $true `
    -MinPasswordLength 32 `
    -MaxPasswordAge "0" `
    -MinPasswordAge "0" `
    -PasswordHistoryCount 5 `
    -LockoutThreshold 0 `
    -ReversibleEncryptionEnabled $false

# Apply to service accounts group
Add-ADFineGrainedPasswordPolicySubject `
    -Identity "Service-Accounts-Policy" `
    -Subjects "CN=Service Accounts,OU=Groups,DC=contoso,DC=local"
```

### Policy for Privileged Users (IT Admins)

```powershell
# Strict policy for IT administrators
New-ADFineGrainedPasswordPolicy `
    -Name "IT-Admin-Policy" `
    -Precedence 1 `
    -ComplexityEnabled $true `
    -MinPasswordLength 20 `
    -MaxPasswordAge "30.00:00:00" `
    -MinPasswordAge "1.00:00:00" `
    -PasswordHistoryCount 50 `
    -LockoutThreshold 3 `
    -LockoutDuration "02:00:00" `
    -LockoutObservationWindow "02:00:00"

# Apply to Domain Admins
Add-ADFineGrainedPasswordPolicySubject `
    -Identity "IT-Admin-Policy" `
    -Subjects "CN=Domain Admins,CN=Users,DC=contoso,DC=local"
```

### Policy for Standard Users

```powershell
# Balanced policy for regular employees
New-ADFineGrainedPasswordPolicy `
    -Name "Standard-User-Policy" `
    -Precedence 50 `
    -ComplexityEnabled $true `
    -MinPasswordLength 14 `
    -MaxPasswordAge "90.00:00:00" `
    -MinPasswordAge "1.00:00:00" `
    -PasswordHistoryCount 24 `
    -LockoutThreshold 5 `
    -LockoutDuration "00:30:00" `
    -LockoutObservationWindow "00:30:00"

# Apply to all users group
Add-ADFineGrainedPasswordPolicySubject `
    -Identity "Standard-User-Policy" `
    -Subjects "CN=Domain Users,CN=Users,DC=contoso,DC=local"
```

---

## Managing FGPPs

### View All FGPPs

```powershell
# List all fine-grained policies
Get-ADFineGrainedPasswordPolicy -Filter *

# View specific policy details
Get-ADFineGrainedPasswordPolicy -Identity "Executive-Policy" |
    Format-List
```

### Check Which Policy Applies to User

```powershell
# See resultant policy for user
Get-ADUserResultantPasswordPolicy -Identity john.doe

# Output shows which policy applies (if any)
# If null, default domain policy applies
```

### View Users Affected by Policy

```powershell
# Get subjects (users/groups) for policy
Get-ADFineGrainedPasswordPolicySubject -Identity "Executive-Policy"

# Get all users who inherit policy
$Policy = Get-ADFineGrainedPasswordPolicy -Identity "Executive-Policy"
$Policy | Get-ADFineGrainedPasswordPolicySubject |
    ForEach-Object {
        if ($_.ObjectClass -eq "group") {
            Get-ADGroupMember $_.Name -Recursive
        } else {
            $_
        }
    } | Select-Object Name, SamAccountName
```

### Modify Existing FGPP

```powershell
# Update policy settings
Set-ADFineGrainedPasswordPolicy -Identity "Executive-Policy" `
    -MinPasswordLength 18 `
    -MaxPasswordAge "45.00:00:00"

# Change precedence
Set-ADFineGrainedPasswordPolicy -Identity "Executive-Policy" `
    -Precedence 5
```

### Remove FGPP

```powershell
# Remove subject from policy
Remove-ADFineGrainedPasswordPolicySubject `
    -Identity "Executive-Policy" `
    -Subjects "CN=John CEO,OU=Users,DC=contoso,DC=local"

# Delete policy entirely
Remove-ADFineGrainedPasswordPolicy -Identity "Executive-Policy" -Confirm:$false
```

---

## Precedence and Conflicts

### How Precedence Works:
1. **Lower number = higher priority** (Precedence 1 > Precedence 100)
2. User directly assigned FGPP always wins over group-inherited
3. If user in multiple groups with FGPPs, lowest precedence wins
4. If no FGPP applies, default domain policy applies

### Example Scenario:
```
User: John Doe
Groups: Domain Users, Executives, IT Admins

Policies Applied:
- IT-Admin-Policy (Precedence 1) → via IT Admins group
- Executive-Policy (Precedence 10) → via Executives group
- Standard-User-Policy (Precedence 50) → via Domain Users group

Resultant Policy: IT-Admin-Policy (lowest precedence number)
```

### Check Effective Policy

```powershell
# Determine which policy applies
Get-ADUserResultantPasswordPolicy -Identity john.doe

# If output shows "IT-Admin-Policy", that's the effective policy
```

---

## Password Policy Best Practices

### Modern Recommendations (NIST 800-63B):

**Do:**
- ✅ **Minimum 12-14 characters** (longer is better)
- ✅ **No forced expiration** (if using MFA + long passphrases)
- ✅ **Check against breach databases** (HaveIBeenPwned)
- ✅ **Allow all special characters** (including spaces)
- ✅ **Enable MFA** for all accounts
- ✅ **Use passphrases** instead of complex passwords

**Don't:**
- ❌ **Don't require frequent changes** (leads to weak passwords)
- ❌ **Don't ban common patterns** that reduce usability
- ❌ **Don't require complex rules** (P@ssw0rd! is still weak)
- ❌ **Don't limit password length** (allow 64+ characters)

### Recommended Policy Templates

**Standard Enterprise:**
```
Minimum Length: 14 characters
Complexity: Enabled
Max Age: 180 days (or never with MFA)
Min Age: 1 day
History: 24 passwords
Lockout: 5 attempts, 30 minute duration
```

**High Security (Admins):**
```
Minimum Length: 20 characters
Complexity: Enabled
Max Age: 30 days
Min Age: 1 day
History: 50 passwords
Lockout: 3 attempts, 2 hour duration
```

**Service Accounts:**
```
Minimum Length: 32 characters (generated)
Complexity: Enabled
Max Age: Never (0)
Min Age: 0
History: 5 passwords
Lockout: Disabled (0)
```

---

## Reporting & Auditing

### Users with Expiring Passwords

```powershell
# Find users with passwords expiring in next 7 days
Search-ADAccount -UsersOnly -PasswordExpiring -TimeSpan "7.00:00:00" |
    Select-Object Name, SamAccountName, PasswordExpired, PasswordLastSet |
    Export-Csv "C:\Reports\Expiring-Passwords.csv" -NoTypeInformation
```

### Users with Passwords That Never Expire

```powershell
# Find users with non-expiring passwords
Get-ADUser -Filter {PasswordNeverExpires -eq $true -and Enabled -eq $true} |
    Select-Object Name, SamAccountName, PasswordLastSet, PasswordNeverExpires |
    Export-Csv "C:\Reports\Never-Expire-Passwords.csv" -NoTypeInformation
```

### Users with Expired Passwords

```powershell
# Find users with expired passwords
Search-ADAccount -UsersOnly -PasswordExpired |
    Select-Object Name, SamAccountName, PasswordExpired, PasswordLastSet |
    Export-Csv "C:\Reports\Expired-Passwords.csv" -NoTypeInformation
```

### Locked Out Users

```powershell
# Find currently locked out users
Search-ADAccount -LockedOut |
    Select-Object Name, SamAccountName, LockedOut, LastBadPasswordAttempt |
    Export-Csv "C:\Reports\Locked-Out-Users.csv" -NoTypeInformation
```

---

## Troubleshooting

### Problem: FGPP not applying to user

**Check:**
```powershell
# Verify policy exists
Get-ADFineGrainedPasswordPolicy -Identity "Policy-Name"

# Check if user/group is in policy
Get-ADFineGrainedPasswordPolicySubject -Identity "Policy-Name"

# Check user's resultant policy
Get-ADUserResultantPasswordPolicy -Identity john.doe

# Verify domain functional level
Get-ADDomain | Select DomainMode
# Must be Windows2008Domain or higher
```

### Problem: User passwords expiring too quickly

**Check:**
```powershell
# Check user's password policy
$User = Get-ADUser john.doe -Properties msDS-ResultantPSO
if ($User.'msDS-ResultantPSO') {
    Get-ADFineGrainedPasswordPolicy -Identity $User.'msDS-ResultantPSO'
} else {
    Get-ADDefaultDomainPasswordPolicy
}

# Check password last set date
Get-ADUser john.doe -Properties PasswordLastSet |
    Select Name, PasswordLastSet
```

### Problem: Cannot create FGPP

**Check domain functional level:**
```powershell
Get-ADDomain | Select DomainMode

# Raise if needed (irreversible!)
Set-ADDomainMode -Identity contoso.local -DomainMode Windows2016Domain
```

---

## Quick Reference

```powershell
# View default domain policy
Get-ADDefaultDomainPasswordPolicy

# Create FGPP
New-ADFineGrainedPasswordPolicy -Name "Policy-Name" -Precedence 10 -MinPasswordLength 14

# Apply to group
Add-ADFineGrainedPasswordPolicySubject -Identity "Policy-Name" -Subjects "GroupName"

# Check user's effective policy
Get-ADUserResultantPasswordPolicy -Identity username

# List all FGPPs
Get-ADFineGrainedPasswordPolicy -Filter *

# Find expiring passwords
Search-ADAccount -PasswordExpiring -TimeSpan "7.00:00:00"

# Find locked accounts
Search-ADAccount -LockedOut

# Unlock user
Unlock-ADAccount -Identity john.doe
```
'''
        })

        # Article 27: SharePoint Online Site Management
        articles.append({
            'category': 'Microsoft 365',
            'title': 'SharePoint Online Site Management',
            'body': r'''# SharePoint Online Site Management

## Overview
Comprehensive guide to creating and managing SharePoint Online sites, including site collections, permissions, and content management.

## Prerequisites
```powershell
# Install SharePoint Online Management Shell
Install-Module -Name Microsoft.Online.SharePoint.PowerShell -Force

# Connect to SharePoint Online
$adminUrl = "https://contoso-admin.sharepoint.com"
Connect-SPOSite -Url $adminUrl
```

## Creating Sites

### Create Communication Site
```powershell
# Modern communication site
New-SPOSite -Url "https://contoso.sharepoint.com/sites/CompanyNews" `
    -Owner admin@contoso.com `
    -StorageQuota 1024 `
    -Title "Company News" `
    -Template SITEPAGEPUBLISHING#0

# Communication site with design
New-SPOSite -Url "https://contoso.sharepoint.com/sites/IT" `
    -Owner admin@contoso.com `
    -StorageQuota 2048 `
    -Title "IT Department" `
    -Template SITEPAGEPUBLISHING#0 `
    -WebTemplate SITEPAGEPUBLISHING
```

### Create Team Site
```powershell
# Modern team site (connected to Microsoft 365 Group)
New-SPOSite -Url "https://contoso.sharepoint.com/sites/ProjectAlpha" `
    -Owner admin@contoso.com `
    -StorageQuota 5120 `
    -Title "Project Alpha" `
    -Template STS#3

# Classic team site
New-SPOSite -Url "https://contoso.sharepoint.com/sites/Archive" `
    -Owner admin@contoso.com `
    -StorageQuota 10240 `
    -Title "Archive Site" `
    -Template STS#0 `
    -LocaleId 1033
```

## Site Collection Management

### List All Sites
```powershell
# Get all site collections
Get-SPOSite -Limit All

# Filter by template
Get-SPOSite -Limit All -Template "STS#3"

# Get sites with specific criteria
Get-SPOSite -Limit All -Filter {Url -like "*project*"}

# Get detailed site information
Get-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" -Detailed
```

### Modify Site Properties
```powershell
# Change site title and storage
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" `
    -Title "IT Services" `
    -StorageQuota 5120

# Change site owner
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" `
    -Owner newowner@contoso.com

# Enable/disable sharing
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" `
    -SharingCapability ExternalUserAndGuestSharing

# Disable external sharing
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/Confidential" `
    -SharingCapability Disabled
```

### Delete Sites
```powershell
# Move to recycle bin
Remove-SPOSite -Identity "https://contoso.sharepoint.com/sites/OldProject"

# Permanently delete from recycle bin
Remove-SPODeletedSite -Identity "https://contoso.sharepoint.com/sites/OldProject"

# Restore from recycle bin
Restore-SPODeletedSite -Identity "https://contoso.sharepoint.com/sites/OldProject"
```

## Permission Management

### Site Collection Administrators
```powershell
# Add site collection admin
Set-SPOUser -Site "https://contoso.sharepoint.com/sites/IT" `
    -LoginName john@contoso.com `
    -IsSiteCollectionAdmin $true

# Remove site collection admin
Set-SPOUser -Site "https://contoso.sharepoint.com/sites/IT" `
    -LoginName john@contoso.com `
    -IsSiteCollectionAdmin $false

# List all site collection admins
Get-SPOUser -Site "https://contoso.sharepoint.com/sites/IT" `
    -Limit All | Where-Object {$_.IsSiteAdmin -eq $true}
```

### External Sharing
```powershell
# Allow external sharing for specific site
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/Partners" `
    -SharingCapability ExternalUserAndGuestSharing `
    -DefaultSharingLinkType AnonymousAccess

# Block external sharing
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/HR" `
    -SharingCapability Disabled

# Get external users
Get-SPOExternalUser -SiteUrl "https://contoso.sharepoint.com/sites/Partners"

# Remove external user
Remove-SPOExternalUser -UniqueIds @("user1@external.com", "user2@external.com")
```

## Storage Management

### Check Storage Usage
```powershell
# Get storage usage for all sites
Get-SPOSite -Limit All | Select-Object Url, StorageUsageCurrent, StorageQuota | `
    Sort-Object -Property StorageUsageCurrent -Descending

# Sites exceeding 80% storage
Get-SPOSite -Limit All | Where-Object {
    ($_.StorageUsageCurrent / $_.StorageQuota) -gt 0.8
} | Select-Object Url, StorageUsageCurrent, StorageQuota
```

### Modify Storage Quotas
```powershell
# Increase storage quota
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" `
    -StorageQuota 10240

# Set warning level
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" `
    -StorageQuota 10240 `
    -StorageQuotaWarningLevel 8192

# Bulk update storage for multiple sites
Get-SPOSite -Limit All -Filter {Template -eq "STS#3"} | ForEach-Object {
    Set-SPOSite -Identity $_.Url -StorageQuota 5120
}
```

## Hub Sites

### Create Hub Site
```powershell
# Register site as hub
Register-SPOHubSite -Site "https://contoso.sharepoint.com/sites/IntranetHub" `
    -DisplayName "Corporate Intranet"

# Get hub site info
Get-SPOHubSite -Identity "https://contoso.sharepoint.com/sites/IntranetHub"

# Associate site with hub
Add-SPOHubSiteAssociation -Site "https://contoso.sharepoint.com/sites/IT" `
    -HubSite "https://contoso.sharepoint.com/sites/IntranetHub"

# Remove hub site association
Remove-SPOHubSiteAssociation -Site "https://contoso.sharepoint.com/sites/IT"
```

### Hub Site Permissions
```powershell
# Grant hub site join permissions to group
Grant-SPOHubSiteRights -Identity "https://contoso.sharepoint.com/sites/IntranetHub" `
    -Principals "IT-Admins@contoso.com" `
    -Rights Join

# Revoke hub site permissions
Revoke-SPOHubSiteRights -Identity "https://contoso.sharepoint.com/sites/IntranetHub" `
    -Principals "IT-Admins@contoso.com"
```

## Content Management

### Document Library Management
```powershell
# Using PnP PowerShell (more features)
Install-Module PnP.PowerShell -Force

# Connect to site
Connect-PnPOnline -Url "https://contoso.sharepoint.com/sites/IT" -Interactive

# Create document library
New-PnPList -Title "Project Documents" -Template DocumentLibrary

# Upload file
Add-PnPFile -Path "C:\Docs\Policy.pdf" -Folder "Shared Documents"

# Download file
Get-PnPFile -Url "/sites/IT/Shared Documents/Policy.pdf" `
    -Path "C:\Downloads\Policy.pdf" -AsFile

# Set file properties
Set-PnPListItem -List "Documents" -Identity 1 -Values @{
    "Title" = "IT Policy Document"
    "Department" = "IT"
}
```

### Version Control
```powershell
# Enable versioning
Set-PnPList -Identity "Documents" -EnableVersioning $true `
    -MajorVersions 50 -MinorVersions 10

# Get file versions
Get-PnPFileVersion -Url "/sites/IT/Shared Documents/Policy.pdf"

# Restore file version
Restore-PnPFileVersion -Url "/sites/IT/Shared Documents/Policy.pdf" `
    -Identity 3
```

## Site Templates

### Save Site as Template
```powershell
# Using PnP PowerShell
Connect-PnPOnline -Url "https://contoso.sharepoint.com/sites/Template" -Interactive

# Extract template
Get-PnPSiteTemplate -Out "C:\Templates\ITTemplate.pnp" `
    -Handlers Lists, Fields, ContentTypes, Files

# Apply template to new site
Connect-PnPOnline -Url "https://contoso.sharepoint.com/sites/NewSite" -Interactive
Invoke-PnPSiteTemplate -Path "C:\Templates\ITTemplate.pnp"
```

## Search Configuration

### Configure Search
```powershell
# Get search configuration
$searchConfig = Get-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" | `
    Select-Object -ExpandProperty SearchBoxInNavBar

# Enable/disable search
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" `
    -SearchBoxInNavBar $true
```

## Compliance and Retention

### Apply Retention Label
```powershell
# Using Security & Compliance PowerShell
Connect-IPPSSession

# Create retention label
New-ComplianceTag -Name "Financial-7Years" `
    -RetentionAction Keep `
    -RetentionDuration 2555 `
    -Comment "Financial records retention"

# Publish retention label
New-RetentionCompliancePolicy -Name "FinancialPolicy" `
    -SharePointLocation "https://contoso.sharepoint.com/sites/Finance"
```

## Troubleshooting

### Site Access Issues
```powershell
# Check if site exists
Get-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" -ErrorAction SilentlyContinue

# Check user permissions
Get-SPOUser -Site "https://contoso.sharepoint.com/sites/IT" `
    -LoginName john@contoso.com

# Check site lock state
Get-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" | Select-Object LockState

# Unlock site
Set-SPOSite -Identity "https://contoso.sharepoint.com/sites/IT" -LockState Unlock
```

### Storage Issues
```powershell
# Find large files
Connect-PnPOnline -Url "https://contoso.sharepoint.com/sites/IT" -Interactive

Get-PnPFolder -Url "/sites/IT/Shared Documents" -Recursive | ForEach-Object {
    Get-PnPFolderItem -FolderSiteRelativeUrl $_.ServerRelativeUrl -ItemType File
} | Where-Object {$_.Length -gt 100MB} | Sort-Object -Property Length -Descending
```

### Sync Issues
```powershell
# Check if sync is blocked
Get-SPOTenantSyncClientRestriction

# Enable sync for specific domain
Set-SPOTenantSyncClientRestriction -Enable -DomainGuids "12345678-1234-1234-1234-123456789012"
```

## Best Practices

1. **Site Structure:**
   - Use hub sites for related site collections
   - Limit site collection depth to 3 levels
   - Use descriptive URLs (avoid spaces)

2. **Permissions:**
   - Use Microsoft 365 Groups for team sites
   - Minimize unique permissions
   - Regularly audit external sharing

3. **Storage:**
   - Set appropriate quotas per site purpose
   - Enable versioning with limits
   - Use retention policies to manage old content

4. **Governance:**
   - Document site creation policies
   - Use site templates for consistency
   - Implement naming conventions

5. **Performance:**
   - Avoid large lists (>5000 items without indexing)
   - Use metadata navigation
   - Enable content approval for libraries

---

## Quick Reference

```powershell
# Create site
New-SPOSite -Url "URL" -Owner "email" -StorageQuota 1024 -Title "Name"

# List all sites
Get-SPOSite -Limit All

# Modify site
Set-SPOSite -Identity "URL" -StorageQuota 5120

# Delete site
Remove-SPOSite -Identity "URL"

# Add site admin
Set-SPOUser -Site "URL" -LoginName "email" -IsSiteCollectionAdmin $true

# Create hub site
Register-SPOHubSite -Site "URL"

# Check storage
Get-SPOSite -Limit All | Select-Object Url, StorageUsageCurrent, StorageQuota

# Connect with PnP
Connect-PnPOnline -Url "URL" -Interactive

# Upload file
Add-PnPFile -Path "C:\file.pdf" -Folder "Documents"
```
'''
        })

        # Article 28: Microsoft Teams Administration
        articles.append({
            'category': 'Microsoft 365',
            'title': 'Microsoft Teams Administration',
            'body': r'''# Microsoft Teams Administration

## Overview
Comprehensive guide to managing Microsoft Teams, including team creation, policies, channels, and governance.

## Prerequisites
```powershell
# Install Microsoft Teams PowerShell module
Install-Module -Name MicrosoftTeams -Force

# Connect to Microsoft Teams
Connect-MicrosoftTeams
```

## Creating and Managing Teams

### Create Team
```powershell
# Create team from scratch
$team = New-Team -DisplayName "IT Department" `
    -Description "IT team collaboration space" `
    -Visibility Private `
    -Owner admin@contoso.com

# Create team from existing Microsoft 365 Group
New-Team -GroupId "12345678-1234-1234-1234-123456789012"

# Create team with template
New-Team -DisplayName "Project Alpha" `
    -Template "com.microsoft.teams.template.ManageAProject" `
    -Visibility Private
```

### List Teams
```powershell
# Get all teams in organization
Get-Team

# Get teams for specific user
Get-Team -User john@contoso.com

# Get team details
Get-Team -GroupId "12345678-1234-1234-1234-123456789012"

# Get team with members
$team = Get-Team -DisplayName "IT Department"
Get-TeamUser -GroupId $team.GroupId
```

### Modify Team Settings
```powershell
# Update team properties
Set-Team -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "IT Services Department" `
    -Description "Updated description" `
    -Visibility Public

# Enable/disable features
Set-Team -GroupId "12345678-1234-1234-1234-123456789012" `
    -AllowGiphy $true `
    -GiphyContentRating Moderate `
    -AllowCustomMemes $true `
    -AllowUserEditMessages $true `
    -AllowUserDeleteMessages $false

# Guest settings
Set-Team -GroupId "12345678-1234-1234-1234-123456789012" `
    -AllowGuestCreateUpdateChannels $false `
    -AllowGuestDeleteChannels $false
```

### Archive and Delete Teams
```powershell
# Archive team (read-only)
Set-TeamArchiveState -GroupId "12345678-1234-1234-1234-123456789012" -Archived $true

# Unarchive team
Set-TeamArchiveState -GroupId "12345678-1234-1234-1234-123456789012" -Archived $false

# Delete team (soft delete)
Remove-Team -GroupId "12345678-1234-1234-1234-123456789012"
```

## Member Management

### Add Members
```powershell
# Add member
Add-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -User john@contoso.com `
    -Role Member

# Add owner
Add-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -User sarah@contoso.com `
    -Role Owner

# Bulk add members
$users = @("user1@contoso.com", "user2@contoso.com", "user3@contoso.com")
foreach ($user in $users) {
    Add-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" `
        -User $user -Role Member
}
```

### Remove Members
```powershell
# Remove user
Remove-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -User john@contoso.com

# List members
Get-TeamUser -GroupId "12345678-1234-1234-1234-123456789012"

# List owners only
Get-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" -Role Owner
```

## Channel Management

### Create Channels
```powershell
# Create standard channel
New-TeamChannel -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "Projects" `
    -Description "Project discussions"

# Create private channel
New-TeamChannel -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "HR Confidential" `
    -Description "HR discussions" `
    -MembershipType Private

# Create shared channel (external collaboration)
New-TeamChannel -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "Partner Collaboration" `
    -Description "Partner discussions" `
    -MembershipType Shared
```

### Manage Channels
```powershell
# List channels
Get-TeamChannel -GroupId "12345678-1234-1234-1234-123456789012"

# Update channel
Set-TeamChannel -GroupId "12345678-1234-1234-1234-123456789012" `
    -CurrentDisplayName "Projects" `
    -NewDisplayName "Active Projects"

# Delete channel
Remove-TeamChannel -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "Old Projects"
```

### Private Channel Membership
```powershell
# Add user to private channel
Add-TeamChannelUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "HR Confidential" `
    -User john@contoso.com `
    -Role Owner

# Remove user from private channel
Remove-TeamChannelUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "HR Confidential" `
    -User john@contoso.com

# List channel members
Get-TeamChannelUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -DisplayName "HR Confidential"
```

## Teams Policies

### Messaging Policies
```powershell
# Create messaging policy
New-CsTeamsMessagingPolicy -Identity "RestrictedMessaging" `
    -AllowUserEditMessage $false `
    -AllowUserDeleteMessage $false `
    -AllowUserChat $true `
    -AllowRemoveUser $false `
    -AllowGiphy $false

# Apply policy to user
Grant-CsTeamsMessagingPolicy -Identity john@contoso.com `
    -PolicyName "RestrictedMessaging"

# List messaging policies
Get-CsTeamsMessagingPolicy
```

### Meeting Policies
```powershell
# Create meeting policy
New-CsTeamsMeetingPolicy -Identity "SecureMeetings" `
    -AllowAnonymousUsersToStartMeeting $false `
    -AutoAdmittedUsers "EveryoneInCompany" `
    -AllowCloudRecording $true `
    -AllowTranscription $true `
    -AllowScreenSharing "EntireScreen"

# Apply policy
Grant-CsTeamsMeetingPolicy -Identity john@contoso.com `
    -PolicyName "SecureMeetings"

# List meeting policies
Get-CsTeamsMeetingPolicy
```

### Calling Policies
```powershell
# Create calling policy
New-CsTeamsCallingPolicy -Identity "InternalOnly" `
    -AllowPrivateCalling $true `
    -AllowVoicemail "AlwaysEnabled" `
    -AllowCallForwardingToUser $true `
    -AllowCallForwardingToPhone $false

# Apply policy
Grant-CsTeamsCallingPolicy -Identity john@contoso.com `
    -PolicyName "InternalOnly"
```

### App Policies
```powershell
# Create app setup policy
New-CsTeamsAppSetupPolicy -Identity "StandardApps" `
    -AllowUserPinning $true `
    -AllowSideLoading $false

# Pin apps for users
$apps = @("com.microsoft.teamspace.tab.planner", "com.microsoft.teamspace.tab.wiki")
Set-CsTeamsAppSetupPolicy -Identity "StandardApps" `
    -PinnedAppBarApps $apps

# Apply policy
Grant-CsTeamsAppSetupPolicy -Identity john@contoso.com `
    -PolicyName "StandardApps"
```

## External Access and Guest Settings

### Configure External Access
```powershell
# Allow external domains
Set-CsExternalAccessPolicy -Identity Global `
    -EnableFederationAccess $true `
    -EnablePublicCloudAccess $true

# Allow specific domains
New-CsAllowedDomain -Identity "partner.com"

# Block specific domains
New-CsBlockedDomain -Identity "competitor.com"

# List allowed domains
Get-CsAllowedDomain
```

### Guest Access Configuration
```powershell
# Enable guest access
Set-CsTeamsClientConfiguration -Identity Global `
    -AllowGuestUser $true

# Configure guest permissions
Set-CsTeamsGuestMessagingConfiguration -Identity Global `
    -AllowUserEditMessage $true `
    -AllowUserDeleteMessage $false `
    -AllowUserChat $true `
    -AllowGiphy $false

# Guest calling settings
Set-CsTeamsGuestCallingConfiguration -Identity Global `
    -AllowPrivateCalling $true `
    -AllowScreenSharing "EntireScreen"

# Guest meeting settings
Set-CsTeamsGuestMeetingConfiguration -Identity Global `
    -AllowMeetNow $true `
    -AllowIPVideo $true
```

## Compliance and Security

### Data Loss Prevention (DLP)
```powershell
# Using Security & Compliance PowerShell
Connect-IPPSSession

# Create DLP policy for Teams
New-DlpCompliancePolicy -Name "Teams-SSN-Policy" `
    -Mode Enable `
    -TeamsLocation All

# Create DLP rule
New-DlpComplianceRule -Name "Block-SSN" `
    -Policy "Teams-SSN-Policy" `
    -ContentContainsSensitiveInformation @{Name="U.S. Social Security Number"} `
    -BlockAccess $true
```

### Retention Policies
```powershell
# Create Teams retention policy
New-RetentionCompliancePolicy -Name "TeamsRetention-7Years" `
    -TeamsChannelLocation All `
    -TeamsChatLocation All

# Create retention rule
New-RetentionComplianceRule -Name "Keep7Years" `
    -Policy "TeamsRetention-7Years" `
    -RetentionDuration 2555 `
    -RetentionComplianceAction Keep
```

### eDiscovery
```powershell
# Create eDiscovery case
New-ComplianceCase -Name "Investigation-2024" `
    -Description "Internal investigation"

# Add Teams locations to case hold
New-CaseHoldPolicy -Name "HoldTeams" `
    -Case "Investigation-2024" `
    -TeamsChannelLocation "IT Department" `
    -TeamsChatLocation "john@contoso.com"
```

## Reporting and Analytics

### Teams Usage Reports
```powershell
# Get team activity report
Get-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" | Measure-Object

# Check inactive teams (requires Graph API)
Connect-MgGraph -Scopes "Group.Read.All"

$teams = Get-MgGroup -Filter "resourceProvisioningOptions/Any(x:x eq 'Team')" -All
foreach ($team in $teams) {
    $lastActivity = Get-MgReportTeamActivityDetail -Period D30
    # Process activity data
}
```

### User Activity Reports
```powershell
# Teams user activity (via Admin Center or Graph API)
# Example: Get user activity for past 30 days
$report = Get-MgReportTeamUserActivityUserDetail -Period D30
$report | Where-Object {$_.LastActivityDate -lt (Get-Date).AddDays(-30)}
```

## Troubleshooting

### Common Issues

**Issue: User can't see team**
```powershell
# Check team membership
Get-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" | `
    Where-Object {$_.User -eq "john@contoso.com"}

# Add user if missing
Add-TeamUser -GroupId "12345678-1234-1234-1234-123456789012" `
    -User john@contoso.com -Role Member
```

**Issue: External access not working**
```powershell
# Check external access policy
Get-CsExternalAccessPolicy

# Check if domain is blocked
Get-CsBlockedDomain | Where-Object {$_.Domain -eq "partner.com"}

# Check tenant federation configuration
Get-CsTenantFederationConfiguration
```

**Issue: Meeting policy not applying**
```powershell
# Check user's effective policy
Get-CsOnlineUser -Identity john@contoso.com | `
    Select-Object DisplayName, TeamsMeetingPolicy

# Force policy application
Grant-CsTeamsMeetingPolicy -Identity john@contoso.com `
    -PolicyName "SecureMeetings"
```

## Best Practices

1. **Team Structure:**
   - Use clear naming conventions
   - Limit teams per user (recommended: <100)
   - Archive inactive teams after 6 months

2. **Permissions:**
   - Minimum 2 owners per team
   - Use private channels for sensitive discussions
   - Review guest access quarterly

3. **Governance:**
   - Implement team creation policy
   - Use expiration policies for project teams
   - Document team purpose and lifecycle

4. **Performance:**
   - Limit channels per team (<50)
   - Use tags instead of @mentions for large teams
   - Archive old teams instead of deleting

5. **Security:**
   - Enable MFA for all users
   - Use conditional access policies
   - Implement DLP policies
   - Regular security audits

---

## Quick Reference

```powershell
# Connect
Connect-MicrosoftTeams

# Create team
New-Team -DisplayName "Name" -Visibility Private

# Add member
Add-TeamUser -GroupId "ID" -User "email" -Role Member

# Create channel
New-TeamChannel -GroupId "ID" -DisplayName "Channel"

# Apply policy
Grant-CsTeamsMessagingPolicy -Identity "email" -PolicyName "PolicyName"

# List teams
Get-Team

# Archive team
Set-TeamArchiveState -GroupId "ID" -Archived $true

# Get team details
Get-Team -GroupId "ID"
Get-TeamUser -GroupId "ID"
Get-TeamChannel -GroupId "ID"
```
'''
        })

        # Article 29: OneDrive for Business Management
        articles.append({
            'category': 'Microsoft 365',
            'title': 'OneDrive for Business Management and Administration',
            'body': r'''# OneDrive for Business Management and Administration

## Overview
Comprehensive guide to managing OneDrive for Business, including user provisioning, storage management, sharing policies, and sync configuration.

## Prerequisites
```powershell
# Install SharePoint Online Management Shell
Install-Module -Name Microsoft.Online.SharePoint.PowerShell -Force

# Install Microsoft Graph PowerShell
Install-Module Microsoft.Graph -Force

# Connect to SharePoint Online
$adminUrl = "https://contoso-admin.sharepoint.com"
Connect-SPOService -Url $adminUrl
```

## User Provisioning and Configuration

### Create OneDrive for User
```powershell
# Provision OneDrive for single user
Request-SPOPersonalSite -UserEmails @("john@contoso.com")

# Bulk provision OneDrive for multiple users
$users = Get-MsolUser -All | Where-Object {$_.isLicensed -eq $true}
$emails = $users.UserPrincipalName
Request-SPOPersonalSite -UserEmails $emails

# Check provisioning status
Get-SPOSite -IncludePersonalSite $true -Limit All | `
    Where-Object {$_.Url -like "*-my.sharepoint.com/personal/*"}
```

### Get User's OneDrive URL
```powershell
# Get OneDrive URL for user
$user = "john@contoso.com"
$OneDriveUrl = "https://contoso-my.sharepoint.com/personal/" + `
    $user.Replace("@","_").Replace(".","_")

Write-Host "OneDrive URL: $OneDriveUrl"

# List user's OneDrive site
Get-SPOSite -Identity $OneDriveUrl -Detailed
```

## Storage Management

### Check Storage Usage
```powershell
# Get all OneDrive sites with storage details
Get-SPOSite -IncludePersonalSite $true -Limit All | `
    Where-Object {$_.Url -like "*-my.sharepoint.com/personal/*"} | `
    Select-Object Owner, Url, StorageUsageCurrent, StorageQuota | `
    Sort-Object -Property StorageUsageCurrent -Descending

# Find OneDrive sites exceeding 80% storage
Get-SPOSite -IncludePersonalSite $true -Limit All | `
    Where-Object {$_.Url -like "*-my.sharepoint.com/personal/*"} | `
    Where-Object {($_.StorageUsageCurrent / $_.StorageQuota) -gt 0.8} | `
    Select-Object Owner, Url, StorageUsageCurrent, StorageQuota
```

### Modify Storage Quotas
```powershell
# Set default storage quota for all new OneDrive sites
Set-SPOTenant -OneDriveStorageQuota 5120

# Increase storage for specific user
Set-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -StorageQuota 10240

# Bulk update storage for all OneDrive sites
Get-SPOSite -IncludePersonalSite $true -Limit All | `
    Where-Object {$_.Url -like "*-my.sharepoint.com/personal/*"} | ForEach-Object {
        Set-SPOSite -Identity $_.Url -StorageQuota 5120
    }

# Set warning level
Set-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -StorageQuotaWarningLevel 4096
```

## Sharing and External Access

### Configure Sharing Settings
```powershell
# Get tenant-wide sharing settings
Get-SPOTenant | Select-Object SharingCapability, OneDriveSharingCapability

# Set OneDrive sharing capability
Set-SPOTenant -OneDriveSharingCapability ExternalUserAndGuestSharing

# Options:
# - Disabled: No external sharing
# - ExistingExternalUserSharingOnly: Only existing external users
# - ExternalUserSharingOnly: New and existing external users
# - ExternalUserAndGuestSharing: Anyone with link

# Disable external sharing for specific user
Set-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -SharingCapability Disabled
```

### Manage Sharing Links
```powershell
# Set default link type
Set-SPOTenant -DefaultSharingLinkType Internal

# Options:
# - None: Most permissive link (default)
# - Direct: Specific people
# - Internal: People in organization
# - AnonymousAccess: Anyone with the link

# Set default link permission
Set-SPOTenant -DefaultLinkPermission View

# Prevent anonymous links
Set-SPOTenant -RequireAnonymousLinksExpireInDays 30

# Require sign-in for shared files
Set-SPOTenant -RequireAcceptingAccountMatchInvitedAccount $true
```

### Audit External Sharing
```powershell
# List externally shared files (requires Microsoft Graph)
Connect-MgGraph -Scopes "Sites.Read.All"

$oneDriveUrl = "https://contoso-my.sharepoint.com/personal/john_contoso_com"
$site = Get-MgSite -Search $oneDriveUrl

# Get shared items
$sharedItems = Get-MgSiteListItemActivity -SiteId $site.Id
$sharedItems | Where-Object {$_.Access.ExternalShared -eq $true}

# Revoke external access for specific file
# Use SharePoint UI or PnP PowerShell for granular control
```

## Sync Client Management

### Configure Sync Restrictions
```powershell
# Allow sync only from domain-joined PCs
Set-SPOTenantSyncClientRestriction -Enable -DomainGuids "12345678-1234-1234-1234-123456789012"

# Get current sync restrictions
Get-SPOTenantSyncClientRestriction

# Disable sync restrictions
Set-SPOTenantSyncClientRestriction -Disable

# Block sync from specific file types
Set-SPOTenant -ExcludedFileExtensionsForSyncClient "exe;dll;vbs"

# Configure Files On-Demand (Windows 10+)
# Enabled by default - no PowerShell command needed
# Users can control via OneDrive settings

# Block personal OneDrive sync on corporate devices
# Requires Intune or Group Policy
```

### Known Folder Move (KFM)
```powershell
# Enable Known Folder Move via Group Policy or Intune
# This PowerShell checks KFM status for user

# Using PnP PowerShell to check KFM status
Connect-PnPOnline -Url "https://contoso-my.sharepoint.com/personal/john_contoso_com" -Interactive

# Check if Documents/Desktop/Pictures are in OneDrive
$folders = Get-PnPFolder -Identity "/"
$folders | Where-Object {$_.Name -in @("Documents","Desktop","Pictures")}

# Users enable KFM through OneDrive client settings
# Admins deploy via:
# - Group Policy: Computer Config > Admin Templates > OneDrive
# - Intune: Devices > Configuration profiles > OneDrive settings
```

## Access Delegation

### Grant Site Collection Admin Access
```powershell
# Add secondary admin to user's OneDrive
Set-SPOUser -Site "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -LoginName admin@contoso.com `
    -IsSiteCollectionAdmin $true

# Remove admin access
Set-SPOUser -Site "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -LoginName admin@contoso.com `
    -IsSiteCollectionAdmin $false

# List all admins
Get-SPOUser -Site "https://contoso-my.sharepoint.com/personal/john_contoso_com" | `
    Where-Object {$_.IsSiteAdmin -eq $true}
```

### Access OneDrive When User Leaves
```powershell
# Option 1: Add secondary admin before user leaves
Set-SPOUser -Site "https://contoso-my.sharepoint.com/personal/former_employee_contoso_com" `
    -LoginName manager@contoso.com `
    -IsSiteCollectionAdmin $true

# Option 2: Transfer ownership of shared folders
# Requires connecting as admin and manually transferring files

# Option 3: Use retention policy to preserve data
# Security & Compliance Center > Retention policies
```

## Compliance and Security

### Apply Retention Policies
```powershell
# Using Security & Compliance PowerShell
Connect-IPPSSession

# Create retention policy for OneDrive
New-RetentionCompliancePolicy -Name "OneDrive-7Years" `
    -OneDriveLocation All

# Create retention rule
New-RetentionComplianceRule -Name "Keep7Years" `
    -Policy "OneDrive-7Years" `
    -RetentionDuration 2555 `
    -RetentionComplianceAction Keep

# Apply policy to specific users
New-RetentionCompliancePolicy -Name "Executives-Permanent" `
    -OneDriveLocation "ceo@contoso.com","cfo@contoso.com"
```

### Data Loss Prevention (DLP)
```powershell
# Create DLP policy for OneDrive
New-DlpCompliancePolicy -Name "OneDrive-PII-Protection" `
    -Mode Enable `
    -OneDriveLocation All

# Create DLP rule to detect credit card numbers
New-DlpComplianceRule -Name "Block-CreditCards" `
    -Policy "OneDrive-PII-Protection" `
    -ContentContainsSensitiveInformation @{Name="Credit Card Number"} `
    -BlockAccess $true `
    -NotifyUser Owner

# Apply DLP policy to specific users
New-DlpCompliancePolicy -Name "Finance-DLP" `
    -Mode Enable `
    -OneDriveLocation "finance@contoso.com","accounting@contoso.com"
```

### Sensitivity Labels
```powershell
# Create sensitivity label
New-Label -DisplayName "Confidential" `
    -Name "Confidential" `
    -Tooltip "Confidential company data" `
    -SiteAndGroupProtectionEnabled $true

# Publish label policy
New-LabelPolicy -Name "ConfidentialPolicy" `
    -Labels "Confidential" `
    -ModernGroupLocation All `
    -OneDriveLocation All
```

## Backup and Recovery

### Restore Deleted Files
```powershell
# Using PnP PowerShell
Connect-PnPOnline -Url "https://contoso-my.sharepoint.com/personal/john_contoso_com" -Interactive

# List deleted files in recycle bin
Get-PnPRecycleBinItem

# Restore specific file
Get-PnPRecycleBinItem | Where-Object {$_.Title -eq "Important.docx"} | `
    Restore-PnPRecycleBinItem -Force

# Restore all files from recycle bin
Get-PnPRecycleBinItem | Restore-PnPRecycleBinItem -Force

# Empty recycle bin
Clear-PnPRecycleBinItem -All -Force
```

### Version History
```powershell
# Using PnP PowerShell
Connect-PnPOnline -Url "https://contoso-my.sharepoint.com/personal/john_contoso_com" -Interactive

# Get file versions
Get-PnPFileVersion -Url "/personal/john_contoso_com/Documents/Report.docx"

# Restore previous version
Restore-PnPFileVersion -Url "/personal/john_contoso_com/Documents/Report.docx" `
    -Identity 5

# Configure version limits
Set-PnPList -Identity "Documents" `
    -EnableVersioning $true `
    -MajorVersions 500 `
    -EnableMinorVersions $false
```

## Migration to OneDrive

### Migrate from File Shares
```powershell
# Using SharePoint Migration Tool (SPMT)
# Download from: https://aka.ms/spmt

# PowerShell example using SPMT API
Install-Module -Name Microsoft.SharePoint.MigrationTool.PowerShell

# Register migration job
Register-SPMTMigration `
    -MigrationType File `
    -SourcePath "\\fileserver\users\john" `
    -TargetSiteUrl "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -TargetList "Documents"

# Start migration
Start-SPMTMigration

# Check migration status
Get-SPMTMigration
```

## Reporting and Analytics

### OneDrive Usage Reports
```powershell
# Using Microsoft Graph
Connect-MgGraph -Scopes "Reports.Read.All"

# Get OneDrive usage report for past 30 days
$report = Get-MgReportOneDriveUsageAccountDetail -Period D30
$report | Select-Object UserPrincipalName, StorageUsedInBytes, LastActivityDate | `
    Format-Table

# Get inactive OneDrive sites
$report | Where-Object {
    $_.LastActivityDate -lt (Get-Date).AddDays(-90)
} | Select-Object UserPrincipalName, LastActivityDate

# Export report to CSV
$report | Export-Csv -Path "C:\Reports\OneDrive-Usage.csv" -NoTypeInformation
```

### File Activity Reports
```powershell
# Get file activity for past 7 days
$activity = Get-MgReportOneDriveActivityUserDetail -Period D7

# Users who haven't synced recently
$activity | Where-Object {$_.SyncedFileCount -eq 0} | `
    Select-Object UserPrincipalName, LastActivityDate
```

## Troubleshooting

### Common Sync Issues

**Issue: Sync client not working**
```powershell
# Check if sync is blocked
Get-SPOTenantSyncClientRestriction

# Verify user has OneDrive license
Get-MsolUser -UserPrincipalName john@contoso.com | Select-Object Licenses

# Check OneDrive provisioning
Get-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com"
```

**Issue: Files not syncing**
- Check file name (no special characters: \ / : * ? " < > |)
- Check file path length (<400 characters)
- Check file size (<250 GB per file)
- Check if file type is blocked

```powershell
# Check blocked file types
Get-SPOTenant | Select-Object ExcludedFileExtensionsForSyncClient
```

**Issue: Storage quota exceeded**
```powershell
# Check user's storage usage
Get-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com" | `
    Select-Object StorageUsageCurrent, StorageQuota, StorageQuotaWarningLevel

# Increase quota
Set-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -StorageQuota 10240
```

### Access Denied Issues
```powershell
# Check if site exists and is accessible
Get-SPOSite -Identity "https://contoso-my.sharepoint.com/personal/john_contoso_com"

# Check user permissions
Get-SPOUser -Site "https://contoso-my.sharepoint.com/personal/john_contoso_com" | `
    Where-Object {$_.LoginName -eq "john@contoso.com"}

# Grant access as secondary admin
Set-SPOUser -Site "https://contoso-my.sharepoint.com/personal/john_contoso_com" `
    -LoginName admin@contoso.com `
    -IsSiteCollectionAdmin $true
```

## Best Practices

1. **Storage Management:**
   - Set appropriate default quotas (1-5 TB)
   - Monitor usage monthly
   - Use retention policies to manage old files
   - Enable versioning with limits (500 versions)

2. **Security:**
   - Require MFA for all users
   - Use conditional access policies
   - Implement DLP policies for sensitive data
   - Limit external sharing
   - Set expiration on anonymous links

3. **Sync:**
   - Deploy Known Folder Move (Desktop/Documents/Pictures)
   - Enable Files On-Demand to save local storage
   - Block personal OneDrive on corporate devices
   - Restrict sync to domain-joined PCs

4. **Governance:**
   - Document sharing policies
   - Train users on proper file naming
   - Regular access reviews
   - Audit external sharing quarterly

5. **Performance:**
   - Keep file paths under 400 characters
   - Avoid special characters in file names
   - Use sync selectively (not entire OneDrive)
   - Enable Files On-Demand

---

## Quick Reference

```powershell
# Connect
Connect-SPOService -Url "https://contoso-admin.sharepoint.com"

# Provision OneDrive
Request-SPOPersonalSite -UserEmails @("user@contoso.com")

# Get OneDrive URL
# https://contoso-my.sharepoint.com/personal/user_contoso_com

# Check storage
Get-SPOSite -Identity "OneDriveURL" | Select StorageUsageCurrent, StorageQuota

# Increase quota
Set-SPOSite -Identity "OneDriveURL" -StorageQuota 10240

# Add admin
Set-SPOUser -Site "OneDriveURL" -LoginName "admin@contoso.com" -IsSiteCollectionAdmin $true

# Configure sharing
Set-SPOTenant -OneDriveSharingCapability ExternalUserSharingOnly

# Set default storage
Set-SPOTenant -OneDriveStorageQuota 5120

# Block file types from sync
Set-SPOTenant -ExcludedFileExtensionsForSyncClient "exe;dll"

# Get usage report
Get-MgReportOneDriveUsageAccountDetail -Period D30
```
'''
        })

        # Article 30: Printer Configuration and Troubleshooting
        articles.append({
            'category': 'Hardware Setup',
            'title': 'Network Printer Configuration and Troubleshooting',
            'body': r'''# Network Printer Configuration and Troubleshooting

## Overview
Comprehensive guide to installing, configuring, and troubleshooting network printers in Windows environments, including print server setup and driver management.

## Prerequisites
- Administrative access to Windows Server or workstation
- Printer IP address or hostname
- Printer drivers (downloadable from manufacturer)
- Network connectivity to printer

## Installing Network Printers

### Method 1: Add via IP Address (TCP/IP Port)
```powershell
# Add printer port
Add-PrinterPort -Name "IP_192.168.1.100" `
    -PrinterHostAddress "192.168.1.100"

# Install printer driver
Add-PrinterDriver -Name "HP Universal Printing PCL 6"

# Add printer
Add-Printer -Name "Finance HP LaserJet" `
    -DriverName "HP Universal Printing PCL 6" `
    -PortName "IP_192.168.1.100"
```

### Method 2: Add via Hostname
```powershell
# Add printer using hostname
Add-PrinterPort -Name "PRINTER01" `
    -PrinterHostAddress "printer01.contoso.local"

Add-Printer -Name "IT Department Printer" `
    -DriverName "Lexmark Universal v2 PS3" `
    -PortName "PRINTER01"
```

### Method 3: Add via GUI
```cmd
Control Panel > Devices and Printers > Add a printer
- Select "Add a network, wireless or Bluetooth printer"
- Choose "The printer that I want isn't listed"
- Select "Add a printer using a TCP/IP address or hostname"
- Enter IP address: 192.168.1.100
- Install driver when prompted
```

## Windows Print Server Setup

### Install Print Services Role
```powershell
# Install Print Server role
Install-WindowsFeature -Name Print-Server -IncludeManagementTools

# Verify installation
Get-WindowsFeature -Name Print-*
```

### Add Shared Network Printers
```powershell
# Add printer to print server
Add-Printer -Name "Sales Color Printer" `
    -DriverName "Xerox Global Print Driver PS" `
    -PortName "IP_192.168.1.101" `
    -Shared `
    -ShareName "Sales-Color" `
    -Location "Building A, Floor 2" `
    -Comment "Sales department color printer"

# Set printer permissions
$printer = Get-Printer -Name "Sales Color Printer"
Set-PrinterPermission -PrinterName $printer.Name `
    -UserName "CONTOSO\Sales-Users" `
    -PermissionType Print

# List all shared printers
Get-Printer | Where-Object {$_.Shared -eq $true}
```

### Deploy Printers via Group Policy
```powershell
# On print server: Share printer
Set-Printer -Name "Finance HP LaserJet" -Shared $true -ShareName "Finance-HP"

# In Group Policy Management Console (GPMC):
# 1. Create/Edit GPO: User Configuration > Preferences > Control Panel Settings > Printers
# 2. Right-click Printers > New > Shared Printer
# 3. Action: Create
# 4. Share path: \\printserver\Finance-HP
# 5. Link GPO to OU containing user accounts

# Verify deployed printers on client
gpupdate /force
Get-Printer | Where-Object {$_.Type -eq "Connection"}
```

## Driver Management

### Install Printer Drivers
```powershell
# Download driver from manufacturer first, then install

# Install driver using INF file
pnputil /add-driver "C:\Drivers\HP\hpcu225u.inf" /install

# Add driver to print server driver store
Add-PrinterDriver -Name "HP Universal Printing PCL 6" `
    -InfPath "C:\Drivers\HP\hpcu225u.inf"

# List installed printer drivers
Get-PrinterDriver | Select-Object Name, Manufacturer, DriverVersion | Format-Table

# Remove old driver
Remove-PrinterDriver -Name "Old HP Driver"
```

### Update Printer Drivers
```powershell
# Export list of current drivers
Get-PrinterDriver | Export-Csv -Path "C:\Temp\PrinterDrivers.csv"

# Remove old driver
Remove-PrinterDriver -Name "HP LaserJet 4250 PCL 5"

# Add new driver
Add-PrinterDriver -Name "HP Universal Printing PCL 6" `
    -InfPath "C:\Drivers\HP_Universal\hpcu225u.inf"

# Update printer to use new driver
$printers = Get-Printer | Where-Object {$_.DriverName -eq "HP LaserJet 4250 PCL 5"}
foreach ($printer in $printers) {
    Set-Printer -Name $printer.Name -DriverName "HP Universal Printing PCL 6"
}
```

## Printer Configuration

### Set Printer Defaults
```powershell
# Set default printer for current user
Set-Printer -Name "Finance HP LaserJet" -DefaultPrinter

# Configure printer properties
Set-PrintConfiguration -PrinterName "Finance HP LaserJet" `
    -Color $false `
    -DuplexingMode TwoSidedLongEdge `
    -PaperSize A4

# Get current printer configuration
Get-PrintConfiguration -PrinterName "Finance HP LaserJet"
```

### Configure Printer Pooling
```powershell
# Add multiple ports to single printer (load balancing)
Add-PrinterPort -Name "IP_192.168.1.101"
Add-PrinterPort -Name "IP_192.168.1.102"
Add-PrinterPort -Name "IP_192.168.1.103"

# Enable printer pooling (via Print Management Console)
# Print Management > Print Servers > [Server] > Printers
# Right-click printer > Properties > Ports tab
# Check "Enable printer pooling"
# Select all ports for the pool
```

### Set Printer Security
```powershell
# Get current permissions
Get-Printer -Name "Finance HP LaserJet" -Full | Select-Object PermissionSDDL

# Grant print permission to group
$printer = Get-Printer -Name "Finance HP LaserJet"
$acl = Get-Acl -Path "Microsoft.PowerShell.Core\Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Print\Printers\$($printer.Name)"

$rule = New-Object System.Security.AccessControl.RegistryAccessRule(
    "CONTOSO\Finance-Users",
    "Print",
    "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl -Path "Microsoft.PowerShell.Core\Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Print\Printers\$($printer.Name)" -AclObject $acl

# Or via Print Management Console:
# Right-click printer > Properties > Security tab
# Add users/groups and assign permissions
```

## Print Queue Management

### View and Manage Print Jobs
```powershell
# List all print jobs
Get-PrintJob -PrinterName "Finance HP LaserJet"

# Cancel specific print job
Remove-PrintJob -PrinterName "Finance HP LaserJet" -ID 15

# Cancel all print jobs
Get-PrintJob -PrinterName "Finance HP LaserJet" | Remove-PrintJob

# Pause printer
Suspend-Printer -Name "Finance HP LaserJet"

# Resume printer
Resume-Printer -Name "Finance HP LaserJet"

# Restart Print Spooler service
Restart-Service -Name Spooler
```

### Clear Stuck Print Queue
```cmd
# Stop Print Spooler
net stop spooler

# Delete spooler files
del /Q /F %systemroot%\System32\spool\PRINTERS\*.*

# Start Print Spooler
net start spooler
```

## Troubleshooting

### Printer Offline Issues

**Check 1: Network connectivity**
```powershell
# Ping printer
Test-Connection -ComputerName 192.168.1.100 -Count 4

# Test printer port
Test-NetConnection -ComputerName 192.168.1.100 -Port 9100

# Check if printer responds to SNMP (port 161)
Test-NetConnection -ComputerName 192.168.1.100 -Port 161
```

**Check 2: Printer status**
```powershell
# Get printer status
Get-Printer -Name "Finance HP LaserJet" | Select-Object Name, PrinterStatus, JobCount

# Check if printer is paused
Get-Printer | Where-Object {$_.PrinterStatus -eq "Paused"}

# Resume printer
Resume-Printer -Name "Finance HP LaserJet"
```

**Check 3: Print Spooler service**
```powershell
# Check spooler status
Get-Service -Name Spooler

# Restart spooler
Restart-Service -Name Spooler

# Set spooler to automatic startup
Set-Service -Name Spooler -StartupType Automatic
```

### Driver Issues

**Issue: Driver not compatible**
```powershell
# Check current driver version
Get-PrinterDriver -Name "HP Universal Printing PCL 6" | `
    Select-Object Name, Manufacturer, DriverVersion

# Download correct driver for OS version
# Windows 10/11: Use Type 4 (v4) drivers
# Windows Server: Use Type 3 (v3) drivers if v4 not available

# Remove incompatible driver
Remove-PrinterDriver -Name "Old Driver Name"

# Install compatible driver
Add-PrinterDriver -Name "HP Universal Printing PCL 6" `
    -InfPath "C:\Drivers\HP\hpcu225u.inf"
```

**Issue: Corrupt printer driver**
```powershell
# Remove all printers using the driver
Get-Printer | Where-Object {$_.DriverName -eq "Problem Driver"} | Remove-Printer

# Remove driver
Remove-PrinterDriver -Name "Problem Driver"

# Clean driver store
pnputil /delete-driver oem##.inf /uninstall

# Reinstall driver
Add-PrinterDriver -Name "New Driver" -InfPath "C:\Drivers\Driver.inf"
```

### Print Job Stuck

**Solution 1: Cancel job via PowerShell**
```powershell
# List stuck jobs
Get-PrintJob -PrinterName "Finance HP LaserJet"

# Cancel job
Remove-PrintJob -PrinterName "Finance HP LaserJet" -ID 20
```

**Solution 2: Restart Print Spooler**
```powershell
Stop-Service -Name Spooler -Force
Start-Service -Name Spooler
```

**Solution 3: Clear print queue manually**
```cmd
net stop spooler
del /Q /F %systemroot%\System32\spool\PRINTERS\*.*
net start spooler
```

### Slow Printing

**Check 1: Network speed**
```powershell
# Check network adapter speed
Get-NetAdapter | Select-Object Name, LinkSpeed, Status

# Test bandwidth to printer (large test print)
# If slow, check for:
# - Network congestion
# - 100Mbps vs 1Gbps link
# - WiFi vs wired connection
```

**Check 2: Print server resources**
```powershell
# Check CPU usage
Get-Counter -Counter "\Processor(_Total)\% Processor Time"

# Check memory
Get-Counter -Counter "\Memory\Available MBytes"

# Check disk I/O
Get-Counter -Counter "\PhysicalDisk(_Total)\Avg. Disk Queue Length"
```

**Check 3: Driver settings**
- Use PCL instead of PostScript
- Disable advanced printing features
- Use printer's built-in fonts
- Reduce print quality for drafts

### Access Denied

**Issue: User can't print**
```powershell
# Check printer permissions
$printer = Get-Printer -Name "Finance HP LaserJet"

# Add user to printer permissions (via GUI)
# Print Management > Printers > Right-click > Properties > Security
# Add user/group with "Print" permission

# Or use ICACLS (advanced)
icacls "\\printserver\Finance-HP" /grant "CONTOSO\User:(OI)(CI)RX"
```

## Monitoring and Reporting

### Print Auditing
```powershell
# Enable print auditing via Group Policy
# Computer Config > Windows Settings > Security Settings > Advanced Audit Policy
# Enable: Audit Object Access

# View print jobs in Event Viewer
Get-WinEvent -LogName "Microsoft-Windows-PrintService/Operational" | `
    Where-Object {$_.Id -eq 307} | `
    Select-Object TimeCreated, Message | Format-List

# Export print job history
Get-WinEvent -LogName "Microsoft-Windows-PrintService/Operational" | `
    Where-Object {$_.Id -eq 307} | `
    Select-Object TimeCreated, @{N='User';E={$_.Properties[2].Value}}, `
        @{N='Document';E={$_.Properties[3].Value}}, `
        @{N='Printer';E={$_.Properties[4].Value}}, `
        @{N='Pages';E={$_.Properties[7].Value}} | `
    Export-Csv -Path "C:\Reports\PrintJobs.csv" -NoTypeInformation
```

## Best Practices

1. **Standardization:**
   - Use universal printer drivers when possible
   - Standardize on PCL or PostScript
   - Use consistent naming convention

2. **Security:**
   - Require PIN/password for sensitive documents (Follow-Me printing)
   - Implement user authentication at device
   - Audit print jobs regularly
   - Limit color printing to authorized users

3. **Management:**
   - Deploy printers via Group Policy
   - Use print server for centralized management
   - Monitor toner/ink levels via SNMP
   - Schedule regular maintenance

4. **Performance:**
   - Use direct IP printing for large print jobs
   - Enable printer pooling for high-volume printers
   - Place print server close to printers (network-wise)

5. **Troubleshooting:**
   - Keep drivers updated
   - Document printer configurations
   - Monitor Event Viewer for errors
   - Test after Windows updates

---

## Quick Reference

```powershell
# Add network printer
Add-PrinterPort -Name "IP_192.168.1.100" -PrinterHostAddress "192.168.1.100"
Add-Printer -Name "PrinterName" -DriverName "DriverName" -PortName "IP_192.168.1.100"

# List printers
Get-Printer

# View print jobs
Get-PrintJob -PrinterName "PrinterName"

# Cancel print job
Remove-PrintJob -PrinterName "PrinterName" -ID 15

# Restart Print Spooler
Restart-Service -Name Spooler

# Clear print queue
net stop spooler && del /Q /F %systemroot%\System32\spool\PRINTERS\*.* && net start spooler

# Test printer connectivity
Test-Connection -ComputerName 192.168.1.100
Test-NetConnection -ComputerName 192.168.1.100 -Port 9100

# Install driver
Add-PrinterDriver -Name "DriverName" -InfPath "C:\Drivers\driver.inf"

# Share printer
Set-Printer -Name "PrinterName" -Shared $true -ShareName "SharedName"
```
'''
        })

        # Article 31: VLAN Configuration
        articles.append({
            'category': 'Network Troubleshooting',
            'title': 'VLAN Configuration and Inter-VLAN Routing',
            'body': r'''# VLAN Configuration and Inter-VLAN Routing

## Overview
Comprehensive guide to configuring VLANs (Virtual Local Area Networks) on network switches and implementing inter-VLAN routing for network segmentation and security.

## VLAN Basics

### What are VLANs?
- Logical separation of broadcast domains within a physical network
- Improve network performance by reducing broadcast traffic
- Enhance security by isolating sensitive systems
- Simplify network management

### VLAN Types:
1. **Data VLAN** - User data traffic
2. **Voice VLAN** - VoIP phone traffic
3. **Management VLAN** - Switch/router management
4. **Native VLAN** - Untagged traffic on trunk ports (default VLAN 1)

### Common VLAN Assignments:
- VLAN 1: Default/Native (avoid using for production)
- VLAN 10: Management
- VLAN 20: Users/Workstations
- VLAN 30: Servers
- VLAN 40: Guests
- VLAN 50: Voice/VoIP
- VLAN 99: Unused ports (black hole)

## Cisco Switch VLAN Configuration

### Create VLANs
```cisco
! Enter global configuration mode
Switch> enable
Switch# configure terminal

! Create VLAN 10 for Management
Switch(config)# vlan 10
Switch(config-vlan)# name Management
Switch(config-vlan)# exit

! Create VLAN 20 for Users
Switch(config)# vlan 20
Switch(config-vlan)# name Users
Switch(config-vlan)# exit

! Create VLAN 30 for Servers
Switch(config)# vlan 30
Switch(config-vlan)# name Servers
Switch(config-vlan)# exit

! Create VLAN 40 for Guests
Switch(config)# vlan 40
Switch(config-vlan)# name Guests
Switch(config-vlan)# exit

! Verify VLANs
Switch# show vlan brief
```

### Assign Ports to VLANs (Access Ports)
```cisco
! Configure port as access port in VLAN 20
Switch(config)# interface FastEthernet0/1
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 20
Switch(config-if)# description User Workstation
Switch(config-if)# exit

! Configure multiple ports at once
Switch(config)# interface range FastEthernet0/2-10
Switch(config-if-range)# switchport mode access
Switch(config-if-range)# switchport access vlan 20
Switch(config-if-range)# exit

! Configure server ports
Switch(config)# interface range GigabitEthernet0/1-4
Switch(config-if-range)# switchport mode access
Switch(config-if-range)# switchport access vlan 30
Switch(config-if-range)# description Servers
Switch(config-if-range)# exit
```

### Configure Trunk Ports
```cisco
! Configure trunk port to another switch
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 10,20,30,40
Switch(config-if)# switchport trunk native vlan 99
Switch(config-if)# description Trunk to Core Switch
Switch(config-if)# exit

! Verify trunk configuration
Switch# show interfaces trunk
```

### Voice VLAN Configuration
```cisco
! Configure port for IP phone + PC (access + voice VLAN)
Switch(config)# interface FastEthernet0/5
Switch(config-if)# switchport mode access
Switch(config-if)# switchport access vlan 20
Switch(config-if)# switchport voice vlan 50
Switch(config-if)# description IP Phone + PC
Switch(config-if)# exit
```

### Secure Unused Ports
```cisco
! Put unused ports in black hole VLAN
Switch(config)# vlan 99
Switch(config-vlan)# name Unused
Switch(config-vlan)# exit

Switch(config)# interface range FastEthernet0/11-23
Switch(config-if-range)# switchport mode access
Switch(config-if-range)# switchport access vlan 99
Switch(config-if-range)# shutdown
Switch(config-if-range)# exit
```

## Inter-VLAN Routing

### Method 1: Router on a Stick
```cisco
! On Router - configure subinterfaces for each VLAN
Router(config)# interface GigabitEthernet0/0
Router(config-if)# no shutdown
Router(config-if)# exit

! Subinterface for VLAN 20 (Users)
Router(config)# interface GigabitEthernet0/0.20
Router(config-subif)# encapsulation dot1Q 20
Router(config-subif)# ip address 192.168.20.1 255.255.255.0
Router(config-subif)# description Users VLAN
Router(config-subif)# exit

! Subinterface for VLAN 30 (Servers)
Router(config)# interface GigabitEthernet0/0.30
Router(config-subif)# encapsulation dot1Q 30
Router(config-subif)# ip address 192.168.30.1 255.255.255.0
Router(config-subif)# description Servers VLAN
Router(config-subif)# exit

! Subinterface for VLAN 40 (Guests)
Router(config)# interface GigabitEthernet0/0.40
Router(config-subif)# encapsulation dot1Q 40
Router(config-subif)# ip address 192.168.40.1 255.255.255.0
Router(config-subif)# description Guests VLAN
Router(config-subif)# exit

! On Switch - configure trunk to router
Switch(config)# interface GigabitEthernet0/1
Switch(config-if)# switchport mode trunk
Switch(config-if)# switchport trunk allowed vlan 20,30,40
Switch(config-if)# description Trunk to Router
Switch(config-if)# exit
```

### Method 2: Layer 3 Switch (SVI)
```cisco
! Enable IP routing on Layer 3 switch
Switch(config)# ip routing

! Create SVIs (Switch Virtual Interfaces) for each VLAN
Switch(config)# interface vlan 20
Switch(config-if)# ip address 192.168.20.1 255.255.255.0
Switch(config-if)# description Users Gateway
Switch(config-if)# no shutdown
Switch(config-if)# exit

Switch(config)# interface vlan 30
Switch(config-if)# ip address 192.168.30.1 255.255.255.0
Switch(config-if)# description Servers Gateway
Switch(config-if)# no shutdown
Switch(config-if)# exit

Switch(config)# interface vlan 40
Switch(config-if)# ip address 192.168.40.1 255.255.255.0
Switch(config-if)# description Guests Gateway
Switch(config-if)# no shutdown
Switch(config-if)# exit

! Verify routing
Switch# show ip route
Switch# show ip interface brief
```

## DHCP for VLANs

### Configure DHCP on Router
```cisco
! DHCP pool for VLAN 20 (Users)
Router(config)# ip dhcp excluded-address 192.168.20.1 192.168.20.10
Router(config)# ip dhcp pool VLAN20
Router(dhcp-config)# network 192.168.20.0 255.255.255.0
Router(dhcp-config)# default-router 192.168.20.1
Router(dhcp-config)# dns-server 8.8.8.8 8.8.4.4
Router(dhcp-config)# exit

! DHCP pool for VLAN 30 (Servers)
Router(config)# ip dhcp excluded-address 192.168.30.1 192.168.30.50
Router(config)# ip dhcp pool VLAN30
Router(dhcp-config)# network 192.168.30.0 255.255.255.0
Router(dhcp-config)# default-router 192.168.30.1
Router(dhcp-config)# dns-server 192.168.30.10
Router(dhcp-config)# exit
```

### DHCP Relay (IP Helper)
```cisco
! If DHCP server is in VLAN 30, configure relay on SVIs
Switch(config)# interface vlan 20
Switch(config-if)# ip helper-address 192.168.30.10
Switch(config-if)# exit

Switch(config)# interface vlan 40
Switch(config-if)# ip helper-address 192.168.30.10
Switch(config-if)# exit
```

## Access Control Between VLANs

### ACL to Restrict Traffic
```cisco
! Deny Guest VLAN from accessing Server VLAN
Router(config)# access-list 100 deny ip 192.168.40.0 0.0.0.255 192.168.30.0 0.0.0.255
Router(config)# access-list 100 permit ip any any

! Apply ACL to VLAN 40 interface
Router(config)# interface GigabitEthernet0/0.40
Router(config-subif)# ip access-group 100 in
Router(config-subif)# exit
```

## Verification Commands

### Show VLAN Information
```cisco
! List all VLANs
Switch# show vlan brief

! Show detailed VLAN info
Switch# show vlan id 20

! Show VLAN assignments by interface
Switch# show vlan

! Show interface VLAN membership
Switch# show interfaces FastEthernet0/1 switchport
```

### Show Trunk Information
```cisco
! Show trunk ports
Switch# show interfaces trunk

! Show allowed VLANs on trunk
Switch# show interfaces GigabitEthernet0/24 trunk
```

### Show Routing (Layer 3 Switch)
```cisco
! Show routing table
Switch# show ip route

! Show SVI status
Switch# show ip interface brief

! Show specific VLAN interface
Switch# show interface vlan 20
```

## Troubleshooting VLANs

### Issue: Devices in same VLAN can't communicate

**Check 1: Verify VLAN exists**
```cisco
Switch# show vlan brief
! Ensure VLAN is created
```

**Check 2: Verify port assignments**
```cisco
Switch# show interfaces FastEthernet0/1 switchport
! Check "Access Mode VLAN" line
```

**Check 3: Check trunk ports**
```cisco
Switch# show interfaces trunk
! Ensure VLAN is allowed on trunk
```

### Issue: Devices in different VLANs can't communicate

**Check 1: Verify inter-VLAN routing is configured**
```cisco
! On router - check subinterfaces
Router# show ip interface brief

! On Layer 3 switch - check SVIs
Switch# show ip interface brief
Switch# show ip route
```

**Check 2: Verify trunking**
```cisco
Switch# show interfaces trunk
! Ensure all VLANs are allowed
```

**Check 3: Check for ACLs blocking traffic**
```cisco
Router# show access-lists
Router# show ip interface GigabitEthernet0/0.20 | include access list
```

### Issue: VLAN not passing through trunk

**Solution: Add VLAN to trunk allowed list**
```cisco
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport trunk allowed vlan add 50
Switch(config-if)# exit
```

### Issue: Native VLAN mismatch
```cisco
! Check native VLAN on both ends
Switch# show interfaces GigabitEthernet0/24 switchport | include Native

! Change native VLAN if mismatched
Switch(config)# interface GigabitEthernet0/24
Switch(config-if)# switchport trunk native vlan 99
Switch(config-if)# exit
```

## Best Practices

1. **VLAN Design:**
   - Use VLAN ranges consistently across network
   - Document VLAN assignments
   - Use descriptive VLAN names
   - Don't use VLAN 1 for production

2. **Security:**
   - Shutdown unused ports and assign to black hole VLAN
   - Change native VLAN from default (VLAN 1)
   - Use separate management VLAN
   - Implement ACLs between sensitive VLANs
   - Disable DTP (Dynamic Trunking Protocol)

3. **Trunking:**
   - Manually configure trunk mode (don't rely on DTP)
   - Explicitly allow only necessary VLANs on trunks
   - Set native VLAN to unused VLAN (e.g., 99)
   - Use 802.1Q encapsulation (industry standard)

4. **Inter-VLAN Routing:**
   - Use Layer 3 switches for better performance
   - Implement proper subnetting
   - Consider routing capacity and bottlenecks
   - Use HSRP/VRRP for gateway redundancy

5. **Documentation:**
   - Maintain VLAN database spreadsheet
   - Document port assignments
   - Label physical ports
   - Keep network diagrams updated

---

## Quick Reference

```cisco
! Create VLAN
vlan 20
name Users

! Assign access port
interface FastEthernet0/1
switchport mode access
switchport access vlan 20

! Configure trunk
interface GigabitEthernet0/24
switchport mode trunk
switchport trunk allowed vlan 10,20,30,40
switchport trunk native vlan 99

! Inter-VLAN routing (Router on Stick)
interface GigabitEthernet0/0.20
encapsulation dot1Q 20
ip address 192.168.20.1 255.255.255.0

! Inter-VLAN routing (Layer 3 Switch)
ip routing
interface vlan 20
ip address 192.168.20.1 255.255.255.0
no shutdown

! Verification
show vlan brief
show interfaces trunk
show ip interface brief
show ip route

! DHCP relay
interface vlan 20
ip helper-address 192.168.30.10
```

### Example Network Design

**Small Office (50-100 users):**
- VLAN 10: Management (192.168.10.0/24)
- VLAN 20: Users (192.168.20.0/24)
- VLAN 30: Servers (192.168.30.0/24)
- VLAN 40: Guests (192.168.40.0/24)
- VLAN 50: VoIP (192.168.50.0/24)
- VLAN 99: Unused/Native (192.168.99.0/24)

**Routing:** Layer 3 switch with SVIs for each VLAN

**Security:**
- Guests can't access internal VLANs (ACL)
- Management VLAN only accessible from IT subnet
- Servers VLAN restricted to necessary services
'''
        })

        # Article 32: Wireless Network Setup
        articles.append({
            'category': 'Network Troubleshooting',
            'title': 'Enterprise Wireless Network Setup and Troubleshooting',
            'body': r'''# Enterprise Wireless Network Setup and Troubleshooting

## Overview
Comprehensive guide to deploying and managing enterprise wireless networks, including access point configuration, security, and troubleshooting.

## Wireless Network Planning

### Site Survey
**Before deployment:**
1. **Physical Survey:**
   - Walk the facility with WiFi analyzer app
   - Identify dead zones and weak signal areas
   - Note sources of interference (microwaves, Bluetooth devices)
   - Check building materials (concrete, metal studs affect signal)

2. **Channel Survey:**
   - Scan for existing SSIDs and channels
   - Identify congested channels
   - Check for rogue access points

3. **Capacity Planning:**
   - Expected number of devices per AP
   - Bandwidth requirements per user
   - Application requirements (video, VoIP need more bandwidth)
   - Coverage vs capacity (overlap APs for high-density areas)

### Access Point Placement

**Coverage Guidelines:**
- **Office environments:** 1 AP per 2,500-5,000 sq ft
- **High-density areas:** 1 AP per 20-50 users
- **Ceiling height:** Optimal at 10-12 feet
- **Avoid:** Metal obstacles, elevator shafts, HVAC equipment

**Channel Planning (2.4 GHz):**
- Use only channels 1, 6, and 11 (non-overlapping)
- Neighboring APs should use different channels
- Avoid DFS channels if possible

**Channel Planning (5 GHz):**
- Many non-overlapping channels available
- 20 MHz channel width for higher density
- 40/80 MHz for higher throughput (fewer channels)

## Cisco Wireless Controller Configuration

### Initial Setup Wizard
```cisco
! Connect to WLC via console
(Cisco Controller) > ?

! Initial setup
System Name: WLC-01
Admin Username: admin
Admin Password: ********
Management Interface IP: 192.168.10.10
Management Interface Netmask: 255.255.255.0
Management Interface Default Router: 192.168.10.1
Management Interface VLAN: 10
Management Interface Port: 1
Management Interface DHCP Server: 192.168.10.1

Virtual Gateway IP Address: 1.1.1.1
Mobility/RF Group Name: HQ-Wireless

SSID: CorpWiFi
```

### Create WLANs (SSIDs)
```cisco
! Login via web interface or CLI

! Create Corporate WLAN
(Cisco Controller) > config wlan create 1 CorpWiFi CorpWiFi
(Cisco Controller) > config wlan security wpa enable 1
(Cisco Controller) > config wlan security wpa akm 802.1x enable 1
(Cisco Controller) > config wlan radius auth add 1 192.168.10.20 1812 ascii SecretKey123
(Cisco Controller) > config wlan interface 1 management
(Cisco Controller) > config wlan enable 1

! Create Guest WLAN
(Cisco Controller) > config wlan create 2 GuestWiFi GuestWiFi
(Cisco Controller) > config wlan security wpa enable 2
(Cisco Controller) > config wlan security wpa akm psk enable 2
(Cisco Controller) > config wlan security wpa akm psk set-psk ascii GuestPass2024 2
(Cisco Controller) > config wlan interface 2 guest-vlan
(Cisco Controller) > config wlan enable 2
```

### VLAN Configuration
```cisco
! Create interface for Corporate WiFi (VLAN 20)
(Cisco Controller) > config interface create corporate-wifi 20
(Cisco Controller) > config interface address management-vlan 192.168.20.1 255.255.255.0 192.168.20.254
(Cisco Controller) > config interface vlan corporate-wifi 20
(Cisco Controller) > config interface dhcp corporate-wifi primary 192.168.20.1

! Create interface for Guest WiFi (VLAN 40)
(Cisco Controller) > config interface create guest-wifi 40
(Cisco Controller) > config interface address guest-vlan 192.168.40.1 255.255.255.0 192.168.40.254
(Cisco Controller) > config interface vlan guest-wifi 40
(Cisco Controller) > config interface dhcp guest-wifi primary 192.168.40.1
```

## Standalone Access Point Configuration (Cisco)

### Basic Setup
```cisco
! Connect to AP via console or Telnet (default IP: 10.0.0.1)
AP> enable
AP# configure terminal

! Set hostname
AP(config)# hostname AP-Floor2-01

! Configure management interface
AP(config)# interface BVI1
AP(config-if)# ip address 192.168.10.50 255.255.255.0
AP(config-if)# exit
AP(config)# ip default-gateway 192.168.10.1

! Set management VLAN
AP(config)# dot11 vlan-name management vlan 10
```

### Configure SSIDs
```cisco
! Create Corporate SSID (2.4 GHz)
AP(config)# dot11 ssid CorpWiFi
AP(config-ssid)# vlan 20
AP(config-ssid)# authentication open
AP(config-ssid)# authentication key-management wpa version 2
AP(config-ssid)# wpa-psk ascii SecurePassword123
AP(config-ssid)# exit

! Apply to radio interface
AP(config)# interface Dot11Radio0
AP(config-if)# encryption mode ciphers aes-ccm
AP(config-if)# ssid CorpWiFi
AP(config-if)# no shutdown
AP(config-if)# exit

! Create Corporate SSID (5 GHz)
AP(config)# interface Dot11Radio1
AP(config-if)# encryption mode ciphers aes-ccm
AP(config-if)# ssid CorpWiFi
AP(config-if)# no shutdown
AP(config-if)# exit
```

## UniFi Access Point Setup

### Controller Setup
1. Install UniFi Controller on Windows/Linux server
2. Access web interface: https://controller-ip:8443
3. Run setup wizard:
   - Create admin account
   - Configure site name
   - Adopt access points

### Adopt Access Points
```bash
# SSH to UniFi AP
ssh ubnt@<AP-IP>
# Default password: ubnt

# Set controller address
set-inform http://<controller-ip>:8080/inform

# Exit and wait for adoption
exit

# From controller, click "Adopt" on discovered AP
```

### Create WiFi Networks
1. Settings > Wireless Networks > Create New
2. **Corporate Network:**
   - Name: CorpWiFi
   - Security: WPA2 Enterprise
   - RADIUS Profile: Select configured RADIUS server
   - VLAN: 20
3. **Guest Network:**
   - Name: GuestWiFi
   - Security: WPA2 Personal
   - Password: GuestPass2024
   - Guest Policy: Enable
   - VLAN: 40

## Wireless Security

### WPA2-Enterprise (802.1X)
**Components:**
- RADIUS server (FreeRADIUS, Microsoft NPS, Cisco ISE)
- Certificate authority for server certs
- Supplicant on client devices

**Windows NPS Setup:**
```powershell
# Install NPS role
Install-WindowsFeature -Name NPAS -IncludeManagementTools

# Configure RADIUS client (AP or WLC)
# Open NPS console
# RADIUS Clients and Servers > New
# Friendly name: Wireless-Controller
# Address: 192.168.10.10
# Shared secret: SecretKey123

# Configure Network Policy
# Network Policies > New
# Policy name: Wireless-Corporate
# Conditions: Windows Groups = Domain Users
# Constraints: Authentication Methods = PEAP (EAP-MSCHAP v2)
# Settings: RADIUS Attributes = Tunnel-Type = VLAN, Tunnel-Medium-Type = 802, Tunnel-Pvt-Group-ID = 20
```

### WPA2-Personal (PSK)
```cisco
! On Cisco WLC
config wlan security wpa akm psk enable 2
config wlan security wpa akm psk set-psk ascii SecurePassword123! 2

! Best practices for PSK:
! - Minimum 20 characters
! - Mix of upper, lower, numbers, symbols
! - Change every 90 days
! - Don't share with guests (use separate network)
```

### WPA3
```cisco
! Enable WPA3 on Cisco WLC (version 8.5+)
config wlan security wpa enable 1
config wlan security wpa wpa3 enable 1
config wlan security wpa wpa3 sae enable 1

! Allow WPA2 for transition period
config wlan security wpa wpa2 enable 1
```

### Guest Network Isolation
```cisco
! On Cisco WLC - prevent guests from seeing each other
config wlan peer-blocking enable 2

! On UniFi - enable Guest Policies
# Settings > Wireless Networks > GuestWiFi
# Guest Policy: Enabled
# [ ] Allow access to local network resources
```

## Troubleshooting

### Issue: Users can't connect to WiFi

**Check 1: SSID broadcast**
```cisco
! Verify SSID is enabled
show wlan summary

! Enable if disabled
config wlan enable 1
```

**Check 2: Authentication**
```cisco
! Check RADIUS server reachability
ping 192.168.10.20

! Test RADIUS authentication
test aaa radius auth 192.168.10.20 username password

! Check RADIUS logs
debug aaa all enable
```

**Check 3: DHCP**
```cisco
! Verify DHCP server is configured
show interface detailed management

! Test DHCP from client perspective
# On Windows client
ipconfig /release
ipconfig /renew
```

### Issue: Slow WiFi performance

**Check 1: Channel utilization**
```cisco
! On Cisco WLC
show ap auto-rf 802.11b summary
show ap auto-rf 802.11a summary

! Look for high channel utilization (>50%)
! Change channels if needed
config 802.11b channel ap <AP-Name> <channel>
```

**Check 2: Client count per AP**
```cisco
! Check clients per AP
show client summary

! Ideal: <30 clients per AP (2.4GHz), <50 per AP (5GHz)
```

**Check 3: RF interference**
- Use WiFi analyzer (Ekahau, inSSIDer, WiFi Analyzer app)
- Check for non-WiFi interference (microwave, Bluetooth)
- Adjust AP power levels if too high (causes co-channel interference)

### Issue: Intermittent disconnections

**Check 1: Roaming issues**
```cisco
! Check roaming settings
show client detail <MAC-address>

! Verify client transitions between APs
debug client <MAC-address>

! Adjust roaming parameters
config wlan mobility anchor add 1 <controller-IP>
```

**Check 2: Power save mode**
```cisco
! Disable power save on client
# Windows: Network adapter properties > Power Management > Uncheck "Allow computer to turn off device"
# macOS: System Preferences > Battery > Turn off "Power Nap"
```

**Check 3: Client compatibility**
```cisco
! Check data rates
show wlan 1

! Disable low data rates to improve performance
config 802.11b rate disabled 1Mbps 2Mbps 5.5Mbps
```

### Issue: Can't reach network resources after connecting

**Check 1: VLAN assignment**
```cisco
! Verify WLAN is mapped to correct VLAN
show wlan 1

! Check VLAN interface
show interface detailed corporate-wifi
```

**Check 2: Default gateway**
```cisco
! On client, verify gateway
ipconfig /all  # Windows
ifconfig       # Linux/Mac

! Verify gateway is reachable
ping 192.168.20.1
```

**Check 3: DNS**
```powershell
# Test DNS resolution
nslookup google.com

# If fails, manually set DNS
# Windows: Network adapter properties > IPv4 > DNS Servers
```

## Monitoring and Reporting

### Real-Time Monitoring
```cisco
! On Cisco WLC
show client summary
show ap summary
show wlan summary
show network summary

! Monitor specific client
show client detail <MAC-address>

! View RF coverage
show ap auto-rf 802.11b <AP-Name>
```

### Client Statistics
```bash
# UniFi Controller
# Insights > WiFi > WiFi Experience
# - Connection success rate
# - Signal strength heatmap
# - Client distribution

# Cisco WLC
show client stats <MAC-address>
```

## Best Practices

1. **Coverage:**
   - Perform site survey before deployment
   - Plan for 20-30% cell overlap
   - Use 5 GHz for capacity, 2.4 GHz for coverage

2. **Security:**
   - Always use WPA2 or WPA3
   - Use WPA2-Enterprise for corporate
   - Separate guest network with isolation
   - Disable WPS, WEP, open networks
   - Hidden SSIDs don't improve security

3. **Performance:**
   - Use 5 GHz band when possible
   - Disable low data rates (1, 2, 5.5 Mbps)
   - Set transmit power appropriately (not max)
   - Use 20 MHz channels in high-density areas

4. **Management:**
   - Use centralized controller
   - Enable automatic RF optimization
   - Regular firmware updates
   - Monitor client experience metrics

5. **Capacity:**
   - 20-30 devices per AP (light usage)
   - 10-15 devices per AP (heavy usage)
   - Plan for device growth (IoT, BYOD)

---

## Quick Reference

```cisco
# Cisco WLC Commands
show wlan summary
show ap summary
show client summary
config wlan enable 1
config wlan disable 1
config 802.11b channel ap AP-Name 11
show ap auto-rf 802.11b summary

# Client Troubleshooting
show client detail <MAC>
debug client <MAC>
show client stats <MAC>
test aaa radius auth <server-ip> username password

# UniFi Controller
# Insights > WiFi > WiFi Experience
# Devices > Access Points > [AP] > RF Environment
# Clients > [Client] > Experience Score
```

### Common WiFi Issues Quick Fixes
- **Can't connect:** Check SSID broadcast, password, RADIUS
- **Slow speed:** Check channel utilization, reduce power, enable 5GHz
- **Dropping:** Adjust roaming, disable power save, update drivers
- **No DHCP:** Check VLAN assignment, verify DHCP server
- **No internet:** Check gateway, DNS, firewall rules
'''
        })

        # Article 33: Server Performance Troubleshooting
        articles.append({
            'category': 'Common Issues',
            'title': 'Windows Server Performance Troubleshooting',
            'body': r'''# Windows Server Performance Troubleshooting

## Overview
Comprehensive guide to diagnosing and resolving Windows Server performance issues, including CPU, memory, disk, and network bottlenecks.

## Performance Monitoring Tools

### Performance Monitor (perfmon)
```powershell
# Launch Performance Monitor
perfmon

# Create Data Collector Set
# Performance Monitor > Data Collector Sets > User Defined > New
# Select counters: Processor, Memory, Disk, Network
# Set sample interval: 15 seconds
# Duration: 5-10 minutes during issue
```

### Resource Monitor (resmon)
```powershell
# Launch Resource Monitor
resmon

# Real-time monitoring of:
# - CPU usage per process
# - Memory consumption
# - Disk activity (read/write per process)
# - Network activity per process
```

### Task Manager
```powershell
# Launch Task Manager
taskmgr

# Performance tab shows:
# - CPU utilization
# - Memory usage
# - Disk activity
# - Network throughput
```

## CPU Performance Issues

### Identify High CPU Usage
```powershell
# Get top CPU consuming processes
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name, CPU, Id

# Monitor CPU usage in real-time
Get-Counter '\Processor(_Total)\% Processor Time' -Continuous

# Check per-core utilization
Get-Counter '\Processor(*)\% Processor Time'

# Identify threads causing high CPU
Get-Process -Id <PID> | Select-Object Threads | Format-List
```

### Common CPU Issues

**Issue 1: Single process consuming 100% CPU**
```powershell
# Identify the process
Get-Process | Sort-Object CPU -Descending | Select-Object -First 5

# Check if process is legitimate
Get-Process -Name <ProcessName> | Select-Object Path, Company, Product

# If malware suspected, scan with Windows Defender
Start-MpScan -ScanType FullScan

# Stop runaway process (use caution)
Stop-Process -Name <ProcessName> -Force
```

**Issue 2: System process high CPU**
```powershell
# Check Windows Update activity
Get-WindowsUpdateLog

# Check Windows Search indexing
Get-Service -Name WSearch

# Rebuild search index if needed
Stop-Service WSearch
Remove-Item -Path "C:\ProgramData\Microsoft\Search\Data\Applications\Windows\*" -Recurse -Force
Start-Service WSearch

# Check for failed updates
Get-WindowsUpdate -NotInstalled

# Check event logs for errors
Get-EventLog -LogName System -Newest 50 -EntryType Error
```

**Issue 3: Antivirus scanning causing high CPU**
```powershell
# Check Windows Defender status
Get-MpComputerStatus

# Exclude specific folders from scanning (use caution)
Add-MpPreference -ExclusionPath "C:\TempData"

# Schedule scans during off-hours
Set-MpPreference -ScanScheduleDay 0  # Sunday
Set-MpPreference -ScanScheduleTime 02:00:00
```

## Memory Performance Issues

### Check Memory Usage
```powershell
# Get total and available memory
Get-Counter '\Memory\Available MBytes'
Get-Counter '\Memory\% Committed Bytes In Use'

# Check for memory leaks
Get-Counter '\Memory\Pool Nonpaged Bytes'
Get-Counter '\Memory\Pool Paged Bytes'

# Identify processes using most memory
Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 10 Name, @{N='Memory(MB)';E={[math]::Round($_.WorkingSet/1MB,2)}}, Id
```

### Common Memory Issues

**Issue 1: High memory usage / Low available memory**
```powershell
# Check committed memory
Get-Counter '\Memory\% Committed Bytes In Use'
# If >80%, server needs more RAM or process optimization

# Check paging activity
Get-Counter '\Memory\Pages/sec'
# If >1000 consistently, add more RAM

# Identify memory hogs
Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 10

# Check for memory leaks (monitor over time)
$process = Get-Process -Name <ProcessName>
while ($true) {
    Write-Host "$($process.Name): $([math]::Round($process.WorkingSet/1MB,2)) MB"
    Start-Sleep -Seconds 60
    $process.Refresh()
}
```

**Issue 2: SQL Server consuming all memory**
```powershell
# SQL Server by design uses all available RAM
# Set max server memory in SQL Server

# Connect to SQL Server
sqlcmd -S localhost -E

# Set max memory (e.g., 16GB on 24GB server)
sp_configure 'show advanced options', 1;
RECONFIGURE;
sp_configure 'max server memory', 16384;
RECONFIGURE;
GO
```

**Issue 3: Memory leak in application**
```powershell
# Monitor process memory over time
$processName = "ApplicationName"
$logFile = "C:\Temp\MemoryLog.csv"
"Time,Memory(MB)" | Out-File $logFile

while ($true) {
    $process = Get-Process -Name $processName -ErrorAction SilentlyContinue
    if ($process) {
        $memory = [math]::Round($process.WorkingSet/1MB,2)
        "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')),$memory" | Out-File $logFile -Append
    }
    Start-Sleep -Seconds 300  # Log every 5 minutes
}

# If memory consistently increases, restart service/application
Restart-Service -Name <ServiceName>
```

## Disk Performance Issues

### Check Disk Performance
```powershell
# Check disk queue length (should be <2 per disk)
Get-Counter '\PhysicalDisk(*)\Avg. Disk Queue Length'

# Check disk response time (should be <15ms for SSD, <20ms for HDD)
Get-Counter '\PhysicalDisk(*)\Avg. Disk sec/Read'
Get-Counter '\PhysicalDisk(*)\Avg. Disk sec/Write'

# Check disk utilization
Get-Counter '\PhysicalDisk(*)\% Disk Time'

# Identify processes causing disk I/O
# Use Resource Monitor (resmon) > Disk tab
```

### Common Disk Issues

**Issue 1: High disk queue length / Slow disk response**
```powershell
# Check disk queue
Get-Counter '\PhysicalDisk(_Total)\Avg. Disk Queue Length'
# If >2 consistently, disk is bottleneck

# Identify top disk users (use Resource Monitor or)
# Process Explorer from Sysinternals

# Check for disk errors
Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object DeviceId, Wear, Temperature, ReadErrorsTotal, WriteErrorsTotal

# Run CHKDSK if errors found
chkdsk C: /F /R
# Requires reboot

# Defragment if HDD (NOT for SSD)
Optimize-Volume -DriveLetter C -Analyze
Optimize-Volume -DriveLetter C -Defrag
```

**Issue 2: Disk space running low**
```powershell
# Check disk space
Get-PSDrive -PSProvider FileSystem

# Find large files
Get-ChildItem C:\ -Recurse -ErrorAction SilentlyContinue |
    Where-Object {$_.Length -gt 1GB} |
    Sort-Object Length -Descending |
    Select-Object FullName, @{N='Size(GB)';E={[math]::Round($_.Length/1GB,2)}}

# Clear temp files
Remove-Item -Path "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "C:\Windows\Temp\*" -Recurse -Force -ErrorAction SilentlyContinue

# Clean Windows Update cache
Stop-Service wuauserv
Remove-Item -Path "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force
Start-Service wuauserv

# Run Disk Cleanup
cleanmgr /sagerun:1
```

**Issue 3: SQL Server database files growing**
```powershell
# Check SQL database sizes
sqlcmd -S localhost -E -Q "EXEC sp_MSforeachdb 'USE [?]; EXEC sp_spaceused'"

# Shrink database (use caution, can cause fragmentation)
sqlcmd -S localhost -E -Q "DBCC SHRINKDATABASE (DatabaseName, 10)"

# Shrink transaction log
sqlcmd -S localhost -E -Q "USE DatabaseName; DBCC SHRINKFILE (LogFileName, 1024)"
```

## Network Performance Issues

### Check Network Performance
```powershell
# Check network utilization
Get-Counter '\Network Interface(*)\Bytes Total/sec'

# Check current bandwidth usage
Get-NetAdapterStatistics | Select-Object Name, ReceivedBytes, SentBytes

# Test network speed to remote host
Test-Connection -ComputerName 192.168.1.100 -Count 10

# Check for packet loss
Test-Connection -ComputerName 192.168.1.100 -Count 100 | Measure-Object -Property ResponseTime -Average -Maximum -Minimum
```

### Common Network Issues

**Issue 1: High network latency**
```powershell
# Trace route to destination
tracert google.com

# Check DNS resolution time
Measure-Command {Resolve-DnsName google.com}

# Flush DNS cache
Clear-DnsClientCache

# Check for network adapter errors
Get-NetAdapterStatistics | Select-Object Name, ReceivedErrors, SentErrors

# Reset network adapter
Restart-NetAdapter -Name "Ethernet"
```

**Issue 2: Slow file transfer to network share**
```powershell
# Check SMB version
Get-SmbConnection

# Enable SMB3 compression (Windows Server 2022+)
Set-SmbClientConfiguration -EnableCompression $true

# Check SMB bandwidth throttling
Get-SmbBandwidthLimit

# Test file copy speed
Measure-Command {Copy-Item -Path "C:\TestFile.zip" -Destination "\\server\share\"}
```

## Application-Specific Issues

### IIS Performance Issues
```powershell
# Check IIS application pool status
Import-Module WebAdministration
Get-IISAppPool

# Check worker process memory
Get-Process w3wp | Select-Object Id, @{N='Memory(MB)';E={[math]::Round($_.WorkingSet/1MB,2)}}

# Restart application pool
Restart-WebAppPool -Name "DefaultAppPool"

# Check IIS logs for errors
Get-Content "C:\inetpub\logs\LogFiles\W3SVC1\*.log" | Select-String "500"
```

### SQL Server Performance Issues
```powershell
# Check SQL Server CPU usage
Get-Counter '\SQLServer:SQL Statistics\Batch Requests/sec'

# Check for blocking
sqlcmd -S localhost -E -Q "EXEC sp_who2"

# Check for slow queries (requires Query Store enabled)
sqlcmd -S localhost -E -Q "SELECT TOP 10 * FROM sys.dm_exec_query_stats ORDER BY total_elapsed_time DESC"

# Update statistics
sqlcmd -S localhost -E -Q "USE DatabaseName; EXEC sp_updatestats"

# Rebuild indexes
sqlcmd -S localhost -E -Q "USE DatabaseName; EXEC sp_MSforeachtable @command1='DBCC DBREINDEX(''?'')'"
```

## Event Log Analysis

### Check for Errors
```powershell
# System errors in last 24 hours
Get-EventLog -LogName System -After (Get-Date).AddDays(-1) -EntryType Error |
    Group-Object -Property Source |
    Sort-Object Count -Descending

# Application errors
Get-EventLog -LogName Application -After (Get-Date).AddDays(-1) -EntryType Error |
    Group-Object -Property Source |
    Sort-Object Count -Descending

# Check specific error ID
Get-EventLog -LogName System -InstanceId 7031  # Service crash
```

## Performance Baselines

### Create Performance Baseline
```powershell
# Collect baseline data during normal operation
$counters = @(
    '\Processor(_Total)\% Processor Time',
    '\Memory\Available MBytes',
    '\PhysicalDisk(_Total)\Avg. Disk Queue Length',
    '\PhysicalDisk(_Total)\Avg. Disk sec/Read',
    '\Network Interface(*)\Bytes Total/sec'
)

Get-Counter -Counter $counters -SampleInterval 60 -MaxSamples 60 |
    Export-Counter -Path "C:\Baseline.blg"

# Import and analyze baseline
$baseline = Import-Counter -Path "C:\Baseline.blg"
$baseline.CounterSamples | Group-Object Path | ForEach-Object {
    [PSCustomObject]@{
        Counter = $_.Name
        Average = ($_.Group | Measure-Object -Property CookedValue -Average).Average
        Max = ($_.Group | Measure-Object -Property CookedValue -Maximum).Maximum
    }
}
```

## Best Practices

1. **Monitoring:**
   - Establish performance baselines during normal operation
   - Set up alerts for CPU >80%, Memory <10% free, Disk Queue >2
   - Monitor trends over time, not just point-in-time
   - Use Performance Monitor for detailed analysis

2. **Proactive Maintenance:**
   - Regular Windows Updates
   - Defragment HDDs monthly (not SSDs)
   - Clean temp files weekly
   - Check disk health monthly
   - Review Event Viewer for warnings

3. **Resource Allocation:**
   - Right-size VMs (not too large or small)
   - Allocate appropriate memory to applications
   - Use separate disks for OS, apps, and data
   - Plan for 20-30% headroom

4. **Application Optimization:**
   - Keep applications updated
   - Configure appropriate caching
   - Optimize database queries
   - Use connection pooling

5. **Documentation:**
   - Document normal performance metrics
   - Track changes that affect performance
   - Maintain runbook for common issues

---

## Quick Reference

```powershell
# CPU
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10
Get-Counter '\Processor(_Total)\% Processor Time'

# Memory
Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 10
Get-Counter '\Memory\Available MBytes'

# Disk
Get-Counter '\PhysicalDisk(_Total)\Avg. Disk Queue Length'
Get-Counter '\PhysicalDisk(_Total)\% Disk Time'

# Network
Get-Counter '\Network Interface(*)\Bytes Total/sec'
Test-Connection -ComputerName server -Count 10

# Services
Get-Service | Where-Object {$_.Status -eq 'Stopped' -and $_.StartType -eq 'Automatic'}
Restart-Service -Name ServiceName

# Event Logs
Get-EventLog -LogName System -EntryType Error -Newest 50
Get-EventLog -LogName Application -EntryType Error -Newest 50

# Resource Monitor
resmon

# Performance Monitor
perfmon
```

### Performance Thresholds
- **CPU:** >80% sustained = issue
- **Memory:** <10% available = issue
- **Disk Queue:** >2 = bottleneck
- **Disk Response:** >20ms = slow
- **Network:** Packet loss >1% = issue
'''
        })

        # Article 34: VMware vSphere Basics
        articles.append({
            'category': 'Common Issues',
            'title': 'VMware vSphere Administration Basics',
            'body': r'''# VMware vSphere Administration Basics

## Overview
Comprehensive guide to VMware vSphere administration, including ESXi host management, virtual machine operations, and common troubleshooting tasks.

## vSphere Architecture

### Components
- **ESXi:** Hypervisor installed on physical servers
- **vCenter Server:** Centralized management platform
- **vSphere Client:** Web-based management interface
- **Datastores:** Storage repositories for VMs
- **Virtual Switches:** Network infrastructure for VMs

### Accessing vSphere

**vCenter Web Client:**
```
URL: https://vcenter.contoso.local/ui
Username: administrator@vsphere.local
Password: ********
```

**ESXi Host Direct:**
```
URL: https://esxi01.contoso.local/ui
Username: root
Password: ********
```

## Virtual Machine Management

### Create Virtual Machine

**Via vSphere Client:**
1. Right-click datacenter/cluster > New Virtual Machine
2. Select creation type: "New virtual machine"
3. Configure:
   - Name: SERVER01
   - Folder: Production
   - Compute resource: Select host/cluster
   - Storage: Select datastore
   - Compatibility: ESXi 7.0 and later
   - Guest OS: Windows Server 2022
   - Customize hardware:
     - CPU: 4 vCPUs
     - Memory: 16 GB
     - Hard disk: 100 GB (Thin provisioned)
     - Network: VM Network (VLAN 20)
     - CD/DVD: Datastore ISO file
4. Finish and power on

**Via PowerCLI:**
```powershell
# Connect to vCenter
Connect-VIServer -Server vcenter.contoso.local -User administrator@vsphere.local

# Create new VM
New-VM -Name "SERVER01" `
    -VMHost "esxi01.contoso.local" `
    -Datastore "Datastore01" `
    -DiskGB 100 `
    -DiskStorageFormat Thin `
    -MemoryGB 16 `
    -NumCpu 4 `
    -GuestId windows2019srv_64Guest `
    -NetworkName "VM Network"

# Mount ISO
Get-VM "SERVER01" | Get-CDDrive | Set-CDDrive -IsoPath "[Datastore01] ISO/Windows2022.iso" -Connected $true -Confirm:$false

# Power on VM
Start-VM -VM "SERVER01"
```

### Manage Virtual Machine

**Power Operations:**
```powershell
# Power on VM
Start-VM -VM "SERVER01"

# Graceful shutdown (requires VMware Tools)
Shutdown-VMGuest -VM "SERVER01" -Confirm:$false

# Power off VM (hard power off)
Stop-VM -VM "SERVER01" -Confirm:$false

# Restart VM
Restart-VMGuest -VM "SERVER01" -Confirm:$false

# Suspend VM
Suspend-VM -VM "SERVER01" -Confirm:$false
```

**Modify VM Resources:**
```powershell
# Increase CPU (VM must be powered off)
Set-VM -VM "SERVER01" -NumCpu 8 -Confirm:$false

# Increase memory (hot-add if enabled)
Set-VM -VM "SERVER01" -MemoryGB 32 -Confirm:$false

# Add hard disk
New-HardDisk -VM "SERVER01" -CapacityGB 200 -StorageFormat Thin

# Expand existing hard disk (VM must be powered off)
Get-HardDisk -VM "SERVER01" | Where-Object {$_.Name -eq "Hard disk 1"} | Set-HardDisk -CapacityGB 150 -Confirm:$false

# Add network adapter
New-NetworkAdapter -VM "SERVER01" -NetworkName "VM Network VLAN30" -Type Vmxnet3 -StartConnected
```

**Snapshots:**
```powershell
# Create snapshot
New-Snapshot -VM "SERVER01" -Name "Before Windows Update" -Description "Pre-patch baseline" -Memory

# List snapshots
Get-Snapshot -VM "SERVER01"

# Revert to snapshot
Set-VM -VM "SERVER01" -Snapshot "Before Windows Update" -Confirm:$false

# Remove snapshot (consolidate)
Get-Snapshot -VM "SERVER01" -Name "Before Windows Update" | Remove-Snapshot -Confirm:$false

# Remove all snapshots
Get-Snapshot -VM "SERVER01" | Remove-Snapshot -Confirm:$false
```

## ESXi Host Management

### Host Configuration

**Check ESXi version:**
```powershell
# Via PowerCLI
Get-VMHost | Select-Object Name, Version, Build

# Via ESXi shell
vmware -vl
```

**Configure NTP:**
```powershell
# Add NTP servers
Get-VMHost | Add-VmHostNtpServer -NtpServer "pool.ntp.org"

# Start NTP service
Get-VMHost | Get-VMHostService | Where-Object {$_.Key -eq "ntpd"} | Start-VMHostService

# Set NTP to start automatically
Get-VMHost | Get-VMHostService | Where-Object {$_.Key -eq "ntpd"} | Set-VMHostService -Policy "on"
```

**Configure DNS:**
```powershell
Get-VMHost | Get-VMHostNetwork | Set-VMHostNetwork -DnsAddress 192.168.1.10, 192.168.1.11 -DomainName "contoso.local" -SearchDomain "contoso.local"
```

**Enable SSH:**
```powershell
Get-VMHost | Get-VMHostService | Where-Object {$_.Key -eq "TSM-SSH"} | Start-VMHostService
Get-VMHost | Get-VMHostService | Where-Object {$_.Key -eq "TSM-SSH"} | Set-VMHostService -Policy "on"
```

### Maintenance Mode

**Enter maintenance mode:**
```powershell
# Migrate or shut down VMs before entering maintenance mode
Set-VMHost -VMHost "esxi01.contoso.local" -State Maintenance
```

**Exit maintenance mode:**
```powershell
Set-VMHost -VMHost "esxi01.contoso.local" -State Connected
```

### Patching ESXi

**Via vSphere Update Manager (VUM):**
1. Home > Lifecycle Manager
2. Import patches
3. Create baseline
4. Attach baseline to hosts
5. Remediate (applies patches)

**Manual patching:**
```bash
# Upload patch bundle to datastore via SCP

# SSH to ESXi host
esxcli software vib install -d /vmfs/volumes/Datastore01/patches/VMware-ESXi-7.0U3-update.zip

# Reboot host
reboot
```

## Storage Management

### Datastores

**Add NFS datastore:**
```powershell
New-Datastore -Nfs -VMHost "esxi01.contoso.local" `
    -Name "NFS-Datastore01" `
    -Path "/export/vmware" `
    -NfsHost "nas01.contoso.local"
```

**Add iSCSI datastore:**
```powershell
# Add iSCSI adapter
Get-VMHost "esxi01.contoso.local" | Get-VMHostStorage | Set-VMHostStorage -SoftwareIScsiEnabled $true

# Add iSCSI target
Get-VMHost "esxi01.contoso.local" | Get-VMHostHba -Type iSCSI | New-IScsiHbaTarget -Address "192.168.1.50"

# Rescan storage
Get-VMHost "esxi01.contoso.local" | Get-VMHostStorage -RescanAllHba
```

**Increase datastore size:**
```powershell
# Expand underlying LUN first (on storage array)

# Rescan storage
Get-VMHost | Get-VMHostStorage -RescanAllHba

# Expand datastore
Get-Datastore "Datastore01" | Set-Datastore -CapacityGB 500
```

### Storage vMotion

**Migrate VM to different datastore:**
```powershell
# Storage vMotion (VM stays powered on)
Get-VM "SERVER01" | Move-VM -Datastore "Datastore02"

# Check storage vMotion progress
Get-Task | Where-Object {$_.Name -eq "RelocateVM_Task"}
```

## Networking

### Virtual Switches

**Create standard switch:**
```powershell
# Create vSwitch
New-VirtualSwitch -VMHost "esxi01.contoso.local" -Name "vSwitch1" -Nic vmnic2

# Create port group
New-VirtualPortGroup -VirtualSwitch "vSwitch1" -Name "VM Network VLAN30" -VLanId 30
```

**Configure distributed switch (vDS):**
```powershell
# Create distributed switch
New-VDSwitch -Name "DSwitch01" -Location (Get-Datacenter "DC01") -NumUplinkPorts 4

# Add hosts to vDS
$vds = Get-VDSwitch "DSwitch01"
Add-VDSwitchVMHost -VDSwitch $vds -VMHost "esxi01.contoso.local"

# Create distributed port group
New-VDPortgroup -VDSwitch $vds -Name "Production-VLAN20" -NumPorts 128 -VlanId 20
```

## vMotion

### Live Migration

**Migrate VM to different host:**
```powershell
# vMotion (migrate compute)
Move-VM -VM "SERVER01" -Destination "esxi02.contoso.local"

# Combined vMotion and Storage vMotion
Move-VM -VM "SERVER01" -Destination "esxi02.contoso.local" -Datastore "Datastore02"
```

**Requirements for vMotion:**
- Shared storage (or vSAN)
- vMotion network configured on all hosts
- Same CPU vendor (Intel/AMD) or EVC enabled
- Compatible virtual hardware version

## High Availability (HA)

### Configure HA Cluster
```powershell
# Create cluster
New-Cluster -Name "Production-Cluster" -Location (Get-Datacenter "DC01") -HAEnabled

# Add hosts to cluster
Add-VMHost -Name "esxi01.contoso.local" -Location (Get-Cluster "Production-Cluster") -User root -Password ******

# Configure HA settings
Get-Cluster "Production-Cluster" | Set-Cluster -HAAdmissionControlEnabled $true -HARestartPriority High -Confirm:$false
```

### HA Behavior
- Automatically restarts VMs if host fails
- Monitors VM health
- Requires shared storage
- Admission control prevents resource over-commitment

## Distributed Resource Scheduler (DRS)

### Configure DRS
```powershell
# Enable DRS on cluster
Get-Cluster "Production-Cluster" | Set-Cluster -DrsEnabled $true -DrsAutomationLevel FullyAutomated -Confirm:$false

# Set DRS rules
# VM-to-host affinity rule: Keep VM on specific host
New-DrsVMHostRule -Cluster "Production-Cluster" -Name "SQL-to-Host1" -VM (Get-VM "SQL-SERVER") -VMHost (Get-VMHost "esxi01.contoso.local") -Type ShouldRunOn

# VM-to-VM anti-affinity: Keep VMs on separate hosts
New-DrsVMAffinityRule -Cluster "Production-Cluster" -Name "Separate-DCs" -VM (Get-VM "DC01","DC02") -KeepTogether $false
```

## Troubleshooting

### VM Performance Issues

**Check VM resource usage:**
```powershell
# CPU usage
Get-VM | Select-Object Name, NumCpu, @{N='CPU Usage (%)';E={[math]::Round($_.ExtensionData.Summary.QuickStats.OverallCpuUsage / ($_.NumCpu * 1000) * 100, 2)}}

# Memory usage
Get-VM | Select-Object Name, MemoryGB, @{N='Memory Usage (GB)';E={[math]::Round($_.ExtensionData.Summary.QuickStats.GuestMemoryUsage/1KB,2)}}

# Check for CPU ready time (indicates contention)
# High CPU ready (>5%) = host is overcommitted
```

**VMware Tools issues:**
```powershell
# Check VMware Tools status
Get-VM | Select-Object Name, @{N='Tools Status';E={$_.ExtensionData.Guest.ToolsStatus}}

# Update VMware Tools
Get-VM "SERVER01" | Update-Tools

# Mount VMware Tools installer
Get-VM "SERVER01" | Get-CDDrive | Set-CDDrive -IsoPath ([Environment]::GetFolderPath("ProgramFiles") + "\VMware\VMware Tools\windows.iso") -Connected $true
```

### Host Issues

**Check host health:**
```powershell
# Check host connection state
Get-VMHost | Select-Object Name, ConnectionState, PowerState

# Check host alarms
Get-VMHost | Get-AlarmDefinition

# Check host hardware status
Get-VMHost | Get-VMHostHardware
```

**ESXi not responding:**
```bash
# Connect via console/iLO/iDRAC

# Check management network
esxcli network ip interface list
esxcli network ip interface ipv4 get

# Restart management agents
/etc/init.d/hostd restart
/etc/init.d/vpxa restart

# Check logs
tail -f /var/log/vmkernel.log
tail -f /var/log/hostd.log
```

### Storage Issues

**VM won't power on - file locked:**
```powershell
# Find which host has the lock
Get-VM "SERVER01" | Get-HardDisk | Select-Object Filename

# SSH to each host and check
vmkfstools -D /vmfs/volumes/Datastore01/SERVER01/SERVER01.vmdk

# If host is down, force remove lock (use caution!)
vmkfstools -B /vmfs/volumes/Datastore01/SERVER01/SERVER01.vmdk
```

**Datastore low on space:**
```powershell
# Check datastore usage
Get-Datastore | Select-Object Name, @{N='Capacity(GB)';E={[math]::Round($_.CapacityGB,2)}}, @{N='Free(GB)';E={[math]::Round($_.FreeSpaceGB,2)}}, @{N='Used%';E={[math]::Round(($_.CapacityGB - $_.FreeSpaceGB) / $_.CapacityGB * 100, 2)}}

# Find large VM files
Get-Datastore | ForEach-Object {
    Get-ChildItem -Path "vmstores:\$($_.Name)" -Recurse |
    Sort-Object Length -Descending |
    Select-Object -First 10 FullName, @{N='Size(GB)';E={[math]::Round($_.Length/1GB,2)}}
}

# Remove old snapshots
Get-VM | Get-Snapshot | Where-Object {$_.Created -lt (Get-Date).AddDays(-7)} | Remove-Snapshot -Confirm:$false
```

## Best Practices

1. **Virtual Machine:**
   - Install VMware Tools on all VMs
   - Use VMXNET3 network adapters for best performance
   - Use paravirtual SCSI controllers
   - Thin provision disks when possible
   - Regular snapshot management (don't keep long-term)

2. **ESXi Host:**
   - Keep ESXi patched and updated
   - Configure NTP for time sync
   - Enable HA and DRS in clusters
   - Use separate physical NICs for management, vMotion, and VM traffic
   - Document host configuration

3. **Storage:**
   - Monitor datastore capacity (alert at 80%)
   - Use Storage vMotion to balance datastores
   - Don't fill datastores beyond 80%
   - Use separate datastores for production and test

4. **Networking:**
   - Use distributed switches for easier management
   - Configure network redundancy (NIC teaming)
   - Separate VLANs for management, vMotion, storage, and VMs
   - Enable jumbo frames for vMotion and storage networks

5. **Backup:**
   - Use image-based backups (Veeam, Commvault, etc.)
   - Test restores regularly
   - Backup vCenter database
   - Document vCenter configuration

---

## Quick Reference

```powershell
# Connect to vCenter
Connect-VIServer -Server vcenter.contoso.local

# VM operations
Get-VM
Start-VM -VM "SERVER01"
Stop-VM -VM "SERVER01"
Restart-VMGuest -VM "SERVER01"
New-Snapshot -VM "SERVER01" -Name "Snapshot1"

# Host operations
Get-VMHost
Get-VMHost | Select Name, ConnectionState, PowerState
Set-VMHost -State Maintenance

# Storage
Get-Datastore
Get-VM "SERVER01" | Move-VM -Datastore "Datastore02"

# Networking
Get-VirtualSwitch
Get-VirtualPortGroup
New-VirtualPortGroup -Name "VLAN30" -VLanId 30

# vMotion
Move-VM -VM "SERVER01" -Destination "esxi02.contoso.local"

# Cluster
Get-Cluster
Get-Cluster | Set-Cluster -HAEnabled $true -DrsEnabled $true
```
'''
        })

        # Article 35: Linux Server Administration
        articles.append({
            'category': 'Linux Administration',
            'title': 'Linux Server Administration Essentials',
            'body': r'''# Linux Server Administration Essentials

## Overview
Comprehensive guide to Linux server administration covering user management, package management, system monitoring, and common troubleshooting tasks for Ubuntu/Debian and Red Hat/CentOS systems.

## User and Permission Management

### User Management
```bash
# Create user
sudo adduser john
sudo useradd -m -s /bin/bash john  # Alternative method

# Set password
sudo passwd john

# Delete user
sudo deluser john --remove-home
sudo userdel -r john  # Alternative

# Modify user
sudo usermod -aG sudo john  # Add to sudo group
sudo usermod -s /bin/zsh john  # Change shell

# List users
cat /etc/passwd
getent passwd

# Check user info
id john
groups john
```

### Group Management
```bash
# Create group
sudo groupadd developers

# Add user to group
sudo usermod -aG developers john

# Remove user from group
sudo gpasswd -d john developers

# List groups
cat /etc/group
getent group

# List users in group
getent group developers
```

### File Permissions
```bash
# Change permissions (numeric)
chmod 755 /path/to/file  # rwxr-xr-x
chmod 644 /path/to/file  # rw-r--r--
chmod 600 /path/to/file  # rw-------

# Change permissions (symbolic)
chmod u+x /path/to/file  # Add execute for user
chmod go-w /path/to/file  # Remove write for group/others
chmod a+r /path/to/file  # Add read for all

# Change ownership
sudo chown john:developers /path/to/file
sudo chown -R john:developers /path/to/directory  # Recursive

# Set SUID/SGID
chmod u+s /path/to/binary  # SUID (4755)
chmod g+s /path/to/directory  # SGID (2755)

# Sticky bit (only owner can delete)
chmod +t /shared/directory  # Sticky bit (1777)
```

### sudo Configuration
```bash
# Edit sudoers file (ALWAYS use visudo)
sudo visudo

# Grant full sudo access
john ALL=(ALL:ALL) ALL

# Allow specific commands without password
john ALL=(ALL) NOPASSWD: /usr/bin/apt update, /usr/bin/apt upgrade

# Allow group sudo access
%developers ALL=(ALL:ALL) ALL

# View sudo privileges
sudo -l
```

## Package Management

### Ubuntu/Debian (apt)
```bash
# Update package lists
sudo apt update

# Upgrade installed packages
sudo apt upgrade
sudo apt full-upgrade  # More aggressive, handles dependencies better

# Install package
sudo apt install nginx

# Remove package
sudo apt remove nginx  # Keeps config files
sudo apt purge nginx  # Removes config files
sudo apt autoremove  # Remove unused dependencies

# Search for package
apt search nginx
apt-cache search nginx

# Show package info
apt show nginx

# List installed packages
apt list --installed
dpkg -l

# Check if package is installed
dpkg -l | grep nginx

# Install from .deb file
sudo dpkg -i package.deb
sudo apt install -f  # Fix dependencies
```

### Red Hat/CentOS (yum/dnf)
```bash
# Update package lists
sudo yum check-update
sudo dnf check-update  # RHEL 8+

# Upgrade packages
sudo yum update
sudo dnf upgrade  # RHEL 8+

# Install package
sudo yum install httpd
sudo dnf install httpd  # RHEL 8+

# Remove package
sudo yum remove httpd
sudo dnf remove httpd  # RHEL 8+

# Search for package
yum search nginx
dnf search nginx  # RHEL 8+

# Show package info
yum info nginx
dnf info nginx  # RHEL 8+

# List installed packages
yum list installed
dnf list installed  # RHEL 8+

# Clean cache
sudo yum clean all
sudo dnf clean all  # RHEL 8+
```

## Service Management (systemd)

### Service Control
```bash
# Start service
sudo systemctl start nginx

# Stop service
sudo systemctl stop nginx

# Restart service
sudo systemctl restart nginx

# Reload configuration
sudo systemctl reload nginx

# Enable service (start at boot)
sudo systemctl enable nginx

# Disable service
sudo systemctl disable nginx

# Check service status
systemctl status nginx
systemctl is-active nginx
systemctl is-enabled nginx

# View service logs
sudo journalctl -u nginx
sudo journalctl -u nginx -f  # Follow logs
sudo journalctl -u nginx --since "1 hour ago"
```

### List and Manage Services
```bash
# List all services
systemctl list-units --type=service
systemctl list-units --type=service --state=running

# List failed services
systemctl --failed

# View service file
systemctl cat nginx

# Edit service file
sudo systemctl edit nginx  # Creates override
sudo systemctl edit --full nginx  # Edit original

# Reload systemd after editing
sudo systemctl daemon-reload
```

## System Monitoring

### Process Management
```bash
# View processes
ps aux
ps aux | grep nginx
pgrep nginx

# Interactive process viewer
top
htop  # More user-friendly (install: sudo apt install htop)

# Kill process
kill <PID>
kill -9 <PID>  # Force kill
pkill nginx  # Kill by name
killall nginx  # Kill all instances
```

### Resource Monitoring
```bash
# CPU and memory usage
top
htop

# Memory usage
free -h
cat /proc/meminfo

# Disk usage
df -h  # Disk space
du -sh /path/to/directory  # Directory size
du -sh /*  # Size of root directories

# Disk I/O
iostat
iotop  # Interactive (install: sudo apt install iotop)

# Network usage
iftop  # Install: sudo apt install iftop
nethogs  # Install: sudo apt install nethogs

# System load
uptime
cat /proc/loadavg
```

### System Information
```bash
# OS information
cat /etc/os-release
lsb_release -a

# Kernel version
uname -r
uname -a

# CPU information
lscpu
cat /proc/cpuinfo

# Memory information
cat /proc/meminfo

# Disk information
lsblk
fdisk -l

# Hardware information
lshw
lspci  # PCI devices
lsusb  # USB devices
```

## Networking

### Network Configuration
```bash
# View network interfaces
ip addr show
ip a
ifconfig  # Older command

# View routing table
ip route show
route -n

# View DNS servers
cat /etc/resolv.conf

# Test connectivity
ping google.com
ping -c 4 8.8.8.8  # Send 4 packets

# Trace route
traceroute google.com
mtr google.com  # Better traceroute

# Check open ports
sudo netstat -tulpn
sudo ss -tulpn  # Newer alternative
sudo lsof -i  # List open files (network)

# Test port connectivity
telnet 192.168.1.100 80
nc -zv 192.168.1.100 80  # netcat
```

### Firewall (ufw - Ubuntu)
```bash
# Enable firewall
sudo ufw enable

# Disable firewall
sudo ufw disable

# Check status
sudo ufw status
sudo ufw status verbose

# Allow port
sudo ufw allow 22/tcp
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Deny port
sudo ufw deny 23/tcp

# Delete rule
sudo ufw delete allow 80/tcp

# Allow from specific IP
sudo ufw allow from 192.168.1.100

# Reset firewall
sudo ufw reset
```

### Firewall (firewalld - RHEL/CentOS)
```bash
# Check status
sudo firewall-cmd --state
sudo firewall-cmd --list-all

# Open port
sudo firewall-cmd --zone=public --add-port=80/tcp --permanent
sudo firewall-cmd --zone=public --add-service=http --permanent

# Remove port
sudo firewall-cmd --zone=public --remove-port=80/tcp --permanent

# Reload firewall
sudo firewall-cmd --reload

# List open ports
sudo firewall-cmd --list-ports

# List allowed services
sudo firewall-cmd --list-services
```

## Disk Management

### Partitioning
```bash
# List disks and partitions
lsblk
sudo fdisk -l

# Create partition (interactive)
sudo fdisk /dev/sdb
# Commands: n (new), p (primary), w (write)

# Create filesystem
sudo mkfs.ext4 /dev/sdb1  # ext4
sudo mkfs.xfs /dev/sdb1  # xfs

# Mount filesystem
sudo mkdir /mnt/data
sudo mount /dev/sdb1 /mnt/data

# Unmount
sudo umount /mnt/data

# Add to fstab for permanent mount
echo "/dev/sdb1 /mnt/data ext4 defaults 0 2" | sudo tee -a /etc/fstab

# Check filesystem
sudo fsck /dev/sdb1
```

### LVM (Logical Volume Manager)
```bash
# Create physical volume
sudo pvcreate /dev/sdb

# Create volume group
sudo vgcreate vg_data /dev/sdb

# Create logical volume
sudo lvcreate -L 50G -n lv_data vg_data

# Format logical volume
sudo mkfs.ext4 /dev/vg_data/lv_data

# Mount logical volume
sudo mkdir /mnt/lv_data
sudo mount /dev/vg_data/lv_data /mnt/lv_data

# Extend logical volume
sudo lvextend -L +10G /dev/vg_data/lv_data
sudo resize2fs /dev/vg_data/lv_data  # ext4
```

## Log Management

### View Logs
```bash
# System logs
sudo tail -f /var/log/syslog  # Ubuntu/Debian
sudo tail -f /var/log/messages  # RHEL/CentOS

# Authentication logs
sudo tail -f /var/log/auth.log  # Ubuntu/Debian
sudo tail -f /var/log/secure  # RHEL/CentOS

# Kernel logs
dmesg
dmesg -w  # Follow mode
sudo tail -f /var/log/kern.log

# Journalctl (systemd logs)
sudo journalctl -xe  # Recent logs with explanations
sudo journalctl -f  # Follow logs
sudo journalctl --since "1 hour ago"
sudo journalctl --since "2024-01-01"
sudo journalctl -u nginx  # Service-specific logs
sudo journalctl -p err  # Error-level logs only
```

### Log Rotation
```bash
# Configure logrotate
sudo nano /etc/logrotate.d/myapp

# Example configuration:
/var/log/myapp/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data www-data
}

# Test logrotate
sudo logrotate -d /etc/logrotate.d/myapp  # Dry run
sudo logrotate -f /etc/logrotate.d/myapp  # Force rotation
```

## SSH Configuration

### SSH Server
```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Recommended settings:
Port 2222  # Change from default 22
PermitRootLogin no
PasswordAuthentication no  # Use key-based auth only
PubkeyAuthentication yes

# Restart SSH service
sudo systemctl restart sshd
```

### SSH Keys
```bash
# Generate SSH key pair
ssh-keygen -t rsa -b 4096 -C "john@contoso.com"
ssh-keygen -t ed25519 -C "john@contoso.com"  # Modern, recommended

# Copy public key to remote server
ssh-copy-id user@server.com

# Manual method
cat ~/.ssh/id_rsa.pub | ssh user@server.com "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

# Set correct permissions
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

## Cron Jobs (Scheduled Tasks)

### Crontab Management
```bash
# Edit crontab for current user
crontab -e

# Crontab syntax: minute hour day month weekday command
# Examples:
0 2 * * * /path/to/backup.sh  # Daily at 2 AM
*/15 * * * * /path/to/check.sh  # Every 15 minutes
0 0 * * 0 /path/to/weekly.sh  # Weekly on Sunday at midnight
0 3 1 * * /path/to/monthly.sh  # Monthly on 1st at 3 AM

# List crontabs
crontab -l

# Remove crontab
crontab -r

# Edit crontab for specific user
sudo crontab -u john -e

# System-wide cron jobs
# Place scripts in:
/etc/cron.daily/
/etc/cron.weekly/
/etc/cron.monthly/
```

## Troubleshooting

### Common Issues

**Issue: Disk full**
```bash
# Check disk usage
df -h

# Find large files
sudo du -sh /* | sort -h
sudo find / -type f -size +100M

# Clear old logs
sudo journalctl --vacuum-time=7d
sudo rm /var/log/*.gz
```

**Issue: High CPU/Memory usage**
```bash
# Find CPU-intensive processes
top
ps aux --sort=-%cpu | head -10

# Find memory-intensive processes
ps aux --sort=-%mem | head -10

# Kill process
sudo kill -9 <PID>
```

**Issue: Service won't start**
```bash
# Check service status
systemctl status servicename

# Check logs
journalctl -u servicename -n 50

# Check configuration syntax
nginx -t  # For nginx
apachectl configtest  # For Apache

# Check file permissions
ls -l /path/to/service/files
```

**Issue: Can't connect via SSH**
```bash
# Check if SSH service is running
systemctl status sshd

# Check firewall
sudo ufw status
sudo firewall-cmd --list-all

# Check SSH logs
sudo tail -f /var/log/auth.log

# Verify SSH is listening
sudo netstat -tulpn | grep :22
```

## Best Practices

1. **Security:**
   - Keep system updated: sudo apt update && sudo apt upgrade
   - Use SSH keys instead of passwords
   - Disable root SSH login
   - Configure firewall (ufw/firewalld)
   - Regular security audits

2. **User Management:**
   - Use sudo instead of root
   - Least privilege principle
   - Remove unused accounts
   - Strong password policies

3. **System Maintenance:**
   - Monitor disk space
   - Rotate logs
   - Review failed services
   - Schedule backups
   - Document changes

4. **Monitoring:**
   - Set up monitoring (Nagios, Zabbix, Prometheus)
   - Configure alerts
   - Regular log reviews
   - Performance baselines

5. **Backup:**
   - Regular backups
   - Test restores
   - Off-site backups
   - Document recovery procedures

---

## Quick Reference

```bash
# User management
sudo adduser username
sudo usermod -aG sudo username
sudo deluser username

# Package management
sudo apt update && sudo apt upgrade  # Ubuntu/Debian
sudo yum update  # RHEL/CentOS

# Service management
sudo systemctl start/stop/restart servicename
sudo systemctl enable/disable servicename
systemctl status servicename

# System monitoring
top / htop
free -h
df -h
ps aux

# Networking
ip addr show
ip route show
sudo ufw allow 80/tcp  # Ubuntu
sudo firewall-cmd --add-port=80/tcp --permanent  # RHEL

# Logs
sudo journalctl -u servicename -f
sudo tail -f /var/log/syslog

# Permissions
chmod 755 file
sudo chown user:group file

# SSH
ssh-keygen -t ed25519
ssh-copy-id user@server
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
