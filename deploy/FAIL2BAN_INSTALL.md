# Automatic Fail2ban Installation

Clientst0r can automatically install and configure fail2ban with one click!

## Quick Setup

1. **Grant Installation Permission (One-Time Setup)**

   Run this command to allow Clientst0r to install packages:
   ```bash
   sudo cp ~/deploy/clientst0r-install-sudoers /etc/sudoers.d/clientst0r-install
   sudo chmod 0440 /etc/sudoers.d/clientst0r-install
   ```

2. **Install Fail2ban**

   Navigate to: **Settings → Fail2ban** in Clientst0r

   Click the **"Install Fail2ban Now"** button

   Wait 1-2 minutes for the installation to complete

3. **Done!**

   Refresh the page to see your fail2ban status and manage banned IPs

## What Gets Installed

- fail2ban package (via apt-get)
- Systemd service (enabled and started)
- Sudoers configuration for fail2ban-client access
- Clientst0r integration for viewing and managing bans

## Manual Installation (Alternative)

If you prefer to install manually:

```bash
sudo apt-get update
sudo apt-get install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Configure Clientst0r access
sudo cp ~/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban
sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban
```

## Security

The sudoers configurations grant specific, limited permissions:
- Package installation (only fail2ban)
- Service management (enable/start fail2ban)
- Fail2ban client commands (status, unban)

No root shell access or unrestricted sudo is granted.
