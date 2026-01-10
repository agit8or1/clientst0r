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
- **Asset Management** - Track devices with custom fields and relationships
- **Password Vault** - AES-GCM encrypted secrets with folder organization
- **Personal Vault** - Private password storage per user
- **Documentation** - Per-org docs with categories, tags, and versioning
- **Global Knowledge Base** - Staff-only internal KB
- **Website Monitoring** - Uptime checks with SSL certificate tracking
- **Infrastructure** - NetBox-style rack visualization + IPAM
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

### Prerequisites

- Ubuntu 20.04+ or Debian 11+
- Python 3.12+
- MariaDB 10.5+ or MySQL 8.0+
- Nginx (production)
- 2GB RAM minimum (4GB recommended)

### Installation

```bash
# 1. Clone repository
git clone https://github.com/agit8or1/huduglue.git
cd huduglue

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template
cp .env.example .env

# 5. Generate secrets
python3 -c "from cryptography.fernet import Fernet; print('APP_MASTER_KEY=' + Fernet.generate_key().decode())"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(50))"
python3 -c "import secrets; print('API_KEY_SECRET=' + secrets.token_urlsafe(50))"

# Edit .env and paste the generated values

# 6. Create database
mysql -u root -p
CREATE DATABASE huduglue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'huduglue'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 7. Run migrations
python3 manage.py migrate

# 8. Create superuser
python3 manage.py createsuperuser

# 9. Collect static files
python3 manage.py collectstatic --noinput

# 10. Run development server
python3 manage.py runserver 0.0.0.0:8000
```

Visit `http://localhost:8000` and log in with your superuser credentials.

## 📖 Documentation

Comprehensive documentation is available:

- **[Installation Guide](docs/INSTALLATION.md)** - Detailed setup instructions
- **[Configuration](docs/CONFIGURATION.md)** - Environment variables
- **[Production Deployment](docs/DEPLOYMENT.md)** - Nginx, Gunicorn, systemd
- **[API Documentation](docs/API.md)** - REST API reference
- **[Security Guide](docs/SECURITY.md)** - Best practices
- **[PSA Integration](docs/PSA_INTEGRATION.md)** - Configure PSA providers
- **[User Guide](docs/USER_GUIDE.md)** - End-user documentation
- **[Development](docs/DEVELOPMENT.md)** - Contributing guide

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

- **Version**: 2.0.0
- **Release Date**: January 2026
- **Status**: Production Ready
- **Maintained**: Yes

## 💬 Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/agit8or1/huduglue/issues)
- **Discussions**: [GitHub Discussions](https://github.com/agit8or1/huduglue/discussions)

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

Screenshots coming soon! Check the [docs/screenshots/](docs/screenshots/) directory.

---

**Made with ❤️ and 🐕 by the HuduGlue Team and Luna the German Shepherd**
