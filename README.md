# HuduGlue 🐕

[![Production Ready](https://img.shields.io/badge/status-production%20ready-green)](https://github.com/agit8or1/huduglue)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Django 6.0](https://img.shields.io/badge/django-6.0-blue)](https://www.djangoproject.com/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)

A complete, self-hosted IT documentation platform designed for Managed Service Providers (MSPs) and IT departments. Built with Django 6, HuduGlue provides secure asset management, encrypted password vault, knowledge base, PSA integrations, and comprehensive monitoring tools.

## 🐕 About Luna

This project was developed with the assistance of **Luna**, a brilliant German Shepherd Dog with exceptional problem-solving abilities and a keen eye for security best practices. Luna's contributions to code review, architecture decisions, and bug hunting have been invaluable.

## ✨ Key Features

### 🔐 Security First
- **Enforced TOTP 2FA** - Two-factor authentication required for all users
- **AES-GCM Encryption** - Military-grade encryption for all sensitive data
- **Argon2 Password Hashing** - Industry-standard password security
- **Brute-Force Protection** - Account lockout after failed attempts
- **Rate Limiting** - All endpoints protected
- **Security Headers** - CSP, HSTS, X-Frame-Options, and more
- **SQL Injection Prevention** - Parameterized queries throughout
- **SSRF Protection** - URL validation for external connections
- **Path Traversal Prevention** - Strict file validation
- **IDOR Protection** - Object access validation

### 🏢 Multi-Tenancy & RBAC
- **Organization Isolation** - Complete data separation
- **42 Granular Permissions** - Across 10 categories
- **MSP User Types** - Staff users (global) and Organization users (scoped)
- **Role Templates** - Reusable permission sets
- **Four-Tier Access** - Owner, Admin, Editor, Read-Only

### 📦 Core Features
- **Asset Management** - Track devices with custom fields, rackmount tracking, and relationships
- **Password Vault** - AES-GCM encrypted secrets with folder organization
- **Personal Vault** - Private password storage per user
- **Documentation** - Per-org docs with categories, tags, and versioning
- **Global Knowledge Base** - Staff-only internal KB
- **Website Monitoring** - Uptime checks with SSL certificate tracking
- **Infrastructure** - NetBox-style rack visualization with rackmount assets + IPAM
- **Processes** - Sequential workflow/runbook system with entity linking
- **Diagrams** - Draw.io integration for network/system diagrams (PNG/SVG/XML export)
- **Secure Notes** - Encrypted ephemeral messaging
- **Contact Management** - Organization-specific contacts
- **Audit Logging** - Complete activity tracking

### 🔌 PSA Integrations
Full implementations for:
- **ConnectWise Manage** - Companies, Contacts, Tickets, Projects, Agreements
- **Autotask PSA** - Companies, Contacts, Tickets, Projects, Agreements
- **HaloPSA** - Companies, Contacts, Tickets, OAuth2
- **Kaseya BMS** - Companies, Contacts, Tickets, Projects, Agreements
- **Syncro** - Customers, Contacts, Tickets
- **Freshservice** - Departments, Requesters, Tickets
- **Zendesk** - Organizations, Users, Tickets

## 🚀 Quick Start

### One-Line Installation (Recommended)

The easiest way to install HuduGlue:

```bash
git clone https://github.com/agit8or1/huduglue.git && cd huduglue && bash install.sh
```

This automated installer will:
- ✅ Install all prerequisites (Python 3.12, pip, venv, MariaDB server & client)
- ✅ Create virtual environment and install dependencies
- ✅ Generate secure encryption keys automatically
- ✅ Create `.env` configuration file
- ✅ Setup database and user
- ✅ Create log directory
- ✅ Run migrations
- ✅ Create superuser account
- ✅ Collect static files
- ✅ **Start production server automatically** (Gunicorn with systemd)

**When the installer finishes, your server is RUNNING and ready to use!**

### Smart Detection

The installer automatically detects existing installations and offers:

1. **Upgrade/Update** - Pull latest code, run migrations, restart service (zero downtime)
2. **System Check** - Verify all components are working properly
3. **Clean Install** - Remove everything and reinstall from scratch
4. **Exit** - Leave existing installation untouched

No manual cleanup needed! The installer handles everything.

**System Requirements:**
- Ubuntu 20.04+ or Debian 11+
- 2GB RAM minimum (4GB recommended)
- Internet connection for package installation

### Manual Installation

If you prefer to install manually or need more control:

<details>
<summary>Click to expand manual installation steps</summary>

#### Prerequisites
- Python 3.12+
- MariaDB 10.5+ or MySQL 8.0+
- Nginx (production only)

```bash
# 1. Clone repository
git clone https://github.com/agit8or1/huduglue.git
cd huduglue

# 2. Install system dependencies
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip mariadb-client mariadb-server

# 3. Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Generate secrets
python3 -c "from cryptography.fernet import Fernet; print('APP_MASTER_KEY=' + Fernet.generate_key().decode())"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(50))"
python3 -c "import secrets; print('API_KEY_SECRET=' + secrets.token_urlsafe(50))"

# 6. Create .env file
# Copy the generated secrets from step 5 into this file
cat > .env << 'EOF'
DEBUG=True
SECRET_KEY=<paste_secret_key_here>
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=huduglue
DB_USER=huduglue
DB_PASSWORD=your_secure_password
DB_HOST=localhost
DB_PORT=3306

APP_MASTER_KEY=<paste_master_key_here>
API_KEY_SECRET=<paste_api_key_secret_here>

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
SITE_NAME=HuduGlue
SITE_URL=http://localhost:8000
EOF

# 7. Start MariaDB and create database
sudo systemctl start mariadb
sudo mysql << 'EOSQL'
CREATE DATABASE huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'huduglue'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue'@'localhost';
FLUSH PRIVILEGES;
EOSQL

# 8. Run migrations
python3 manage.py migrate

# 9. Create superuser
python3 manage.py createsuperuser

# 10. Collect static files
python3 manage.py collectstatic --noinput

# 11. Run development server
python3 manage.py runserver 0.0.0.0:8000
```

Visit `http://localhost:8000` and log in with the credentials you created in step 9.

</details>

## 📚 Documentation

**Installation:**
- **[INSTALL.md](INSTALL.md)** - Complete installation guide (quick start, upgrade, troubleshooting)

**Core Documentation:**
- **[ORGANIZATIONS.md](ORGANIZATIONS.md)** - Complete guide to organizations, user types, roles, and permissions
- **[SECURITY.md](SECURITY.md)** - Security best practices and vulnerability disclosure
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Development and contribution guidelines
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and release notes
- **[deploy/](deploy/)** - Production deployment configs (Nginx, Gunicorn, systemd services)

## 🏗️ Architecture

### Technology Stack
- **Framework**: Django 6.0
- **API**: Django REST Framework 3.15
- **Database**: MariaDB 10.5+ (MySQL 8.0+ supported)
- **Web Server**: Nginx + Gunicorn
- **Authentication**: django-two-factor-auth (TOTP)
- **Encryption**: Python cryptography (AES-GCM)
- **Password Hashing**: Argon2
- **Frontend**: Bootstrap 5, vanilla JavaScript

### Design Philosophy
- ✅ **No Docker** - Pure systemd deployment
- ✅ **No Redis** - systemd timers for scheduling
- ✅ **Minimal Dependencies** - Only essential packages
- ✅ **Security First** - Built with security in mind
- ✅ **Self-Hosted** - Complete data control

## 🔒 Security

HuduGlue has undergone comprehensive security auditing:

### Fixed Vulnerabilities
- ✅ SQL Injection - Parameterized queries and identifier quoting
- ✅ SSRF - URL validation with IP blacklisting
- ✅ Path Traversal - Strict file path validation
- ✅ IDOR - Object access verification
- ✅ Insecure File Uploads - Type, size, and extension validation
- ✅ Hardcoded Secrets - Environment variable enforcement
- ✅ Weak Encryption - AES-GCM with validated keys
- ✅ CSRF Protection - Multi-domain support

### Security Features
- All passwords encrypted with AES-GCM
- API keys hashed with HMAC-SHA256
- Rate limiting on all endpoints
- Brute-force protection
- Security headers (CSP, HSTS)
- Private file serving
- Audit logging

**Security Disclosure**: If you discover a vulnerability, please email agit8or@agit8or.net. See [SECURITY.md](SECURITY.md) for details.

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/agit8or1/huduglue.git
cd huduglue

# 2. Create feature branch
git checkout -b feature/amazing-feature

# 3. Make changes and test
python3 manage.py test

# 4. Commit and push
git commit -m 'Add amazing feature'
git push origin feature/amazing-feature

# 5. Open Pull Request
```

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Luna the GSD** - Development assistance, security review, and bug hunting
- **Django & DRF** - Excellent web framework
- **Bootstrap 5** - Beautiful, responsive UI
- **Font Awesome** - Icon library
- **Community** - All contributors and users

## 📊 Project Status

- **Version**: 2.2.0
- **Release Date**: January 2026
- **Status**: Production Ready
- **Maintained**: Yes

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/agit8or1/huduglue/issues)
- **Discussions**: [GitHub Discussions](https://github.com/agit8or1/huduglue/discussions)
- **Security**: See [SECURITY.md](SECURITY.md) for vulnerability disclosure

## 💝 Supporting This Project

If you find HuduGlue useful for your MSP or IT department, please consider supporting the developer's business: **[MSP Reboot](https://www.mspreboot.com)** - Professional MSP services and consulting.

Your support allows me to continue developing open-source tools like HuduGlue and contribute to the MSP community. Thank you!

## 🗺️ Roadmap

- [ ] Mobile-responsive UI improvements
- [ ] Advanced reporting and analytics
- [ ] Backup/restore functionality
- [ ] Docker deployment option (optional)
- [ ] Additional PSA integrations
- [ ] API v2 with GraphQL
- [ ] Real-time collaboration
- [ ] Mobile app

## ⚡ Performance

- Handles 1000+ assets per organization
- Sub-second page load times
- Efficient database queries
- Optimized for low-resource environments
- Horizontal scaling support

## 📸 Screenshots

**[View Full Screenshot Gallery →](SCREENSHOTS.md)**

<table>
  <tr>
    <td><img src="screenshots/01-dashboard.png" width="300" alt="Dashboard"/><br/><sub><b>Dashboard</b></sub></td>
    <td><img src="screenshots/05-passwords-list.png" width="300" alt="Password Vault"/><br/><sub><b>Password Vault</b></sub></td>
    <td><img src="screenshots/03-assets-list.png" width="300" alt="Assets"/><br/><sub><b>Asset Management</b></sub></td>
  </tr>
  <tr>
    <td><img src="screenshots/08-documents-list.png" width="300" alt="Documents"/><br/><sub><b>Knowledge Base</b></sub></td>
    <td><img src="screenshots/13-website-monitors.png" width="300" alt="Monitoring"/><br/><sub><b>Website Monitoring</b></sub></td>
    <td><img src="screenshots/25-system-status.png" width="300" alt="System Status"/><br/><sub><b>System Status</b></sub></td>
  </tr>
</table>

**[See all 31 screenshots →](SCREENSHOTS.md)**

---

**Made with ❤️ and 🐕 by the HuduGlue Team and Luna the German Shepherd**
