# Security Policy

## 🔒 Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | ✅ Yes            |
| 1.2.x   | ✅ Yes            |
| 1.1.x   | ⚠️ Critical only   |
| < 1.1   | ❌ No              |

## 🐕 Security Auditing

HuduGlue has been thoroughly audited for security vulnerabilities with assistance from Luna the GSD. We take security seriously and have implemented comprehensive protections.

## ✅ Security Measures

### Fixed Vulnerabilities
- **SQL Injection** - All queries use parameterized statements and proper identifier quoting
- **SSRF (Server-Side Request Forgery)** - URL validation with private IP blocking
- **Path Traversal** - Strict file path validation and sanitization
- **IDOR (Insecure Direct Object References)** - Object access verification
- **Insecure File Uploads** - Type, size, and extension whitelisting
- **Hardcoded Secrets** - Environment variable enforcement
- **Weak Encryption** - AES-GCM with validated key management
- **CSRF** - Multi-domain CSRF protection

### Security Features
- ✅ Enforced TOTP 2FA for all users
- ✅ AES-GCM encryption for all sensitive data
- ✅ Argon2 password hashing
- ✅ HMAC-SHA256 API key hashing
- ✅ Brute-force protection (django-axes)
- ✅ Rate limiting on all endpoints
- ✅ Security headers (CSP, HSTS, X-Frame-Options)
- ✅ Private file serving (X-Accel-Redirect)
- ✅ SQL injection prevention
- ✅ XSS protection (Django auto-escaping)
- ✅ Comprehensive audit logging

## 🚨 Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please follow responsible disclosure:

### DO:
1. **Email us first** at agit8or@agit8or.net
2. Provide detailed information about the vulnerability
3. Give us reasonable time to address the issue (90 days)
4. Work with us to verify the fix

### DON'T:
- Publicly disclose the vulnerability before we've had time to fix it
- Exploit the vulnerability beyond what's necessary to demonstrate it
- Access or modify other users' data
- Perform DoS attacks or resource exhaustion tests

### What to Include:

```
Subject: [SECURITY] Brief description of vulnerability

- Type of vulnerability (e.g., SQL injection, XSS, etc.)
- Steps to reproduce
- Impact assessment
- Affected versions
- Proof of concept (if applicable)
- Suggested fix (optional)
```

## 🎯 Scope

### In Scope:
- SQL Injection
- Cross-Site Scripting (XSS)
- Cross-Site Request Forgery (CSRF)
- Server-Side Request Forgery (SSRF)
- Path Traversal
- Authentication/Authorization bypass
- Insecure Direct Object References (IDOR)
- Remote Code Execution (RCE)
- Cryptographic vulnerabilities
- Information disclosure
- File upload vulnerabilities

### Out of Scope:
- Social engineering attacks
- Physical security
- Denial of Service (DoS/DDoS)
- Issues in third-party dependencies (report to upstream)
- Self-XSS or clickjacking without demonstrated impact
- Missing security headers without demonstrated impact
- Rate limiting bypasses without demonstrated impact

## 🏆 Recognition

We appreciate security researchers who follow responsible disclosure. Contributors will be:
- Acknowledged in our security advisories (if desired)
- Credited in CHANGELOG.md
- Given priority support and feedback

## 📋 Security Checklist for Deployment

Before deploying to production, ensure:

- [ ] `DEBUG=False` in production
- [ ] Strong `SECRET_KEY`, `API_KEY_SECRET`, and `APP_MASTER_KEY` set
- [ ] `ALLOWED_HOSTS` properly configured (no wildcards in production)
- [ ] SSL/TLS enabled with valid certificate
- [ ] `SECURE_SSL_REDIRECT=True`
- [ ] `SECURE_HSTS_SECONDS=31536000`
- [ ] Firewall configured (only 80/443 open)
- [ ] Database backups enabled
- [ ] Log rotation configured
- [ ] File permissions restricted (700 for sensitive files)
- [ ] 2FA enforced for all users
- [ ] Regular dependency updates
- [ ] Audit logs monitored

## 🔐 Secrets Management

### Never Commit:
- `.env` files
- Private keys
- API credentials
- Database passwords
- Encryption keys

### Use Instead:
- Environment variables
- Secret management systems (HashiCorp Vault, AWS Secrets Manager)
- Encrypted configuration files (with keys stored separately)

## 📝 Security Updates

Security updates are released as:
- **Critical**: Within 24-48 hours
- **High**: Within 1 week
- **Medium**: Within 2 weeks
- **Low**: Next minor release

Subscribe to our GitHub releases or security advisories to stay informed.

## 🔍 Security Testing

We encourage security testing but please:
- Test on your own deployment, not our demo instances
- Don't test on production systems
- Follow responsible disclosure practices
- Respect user privacy and data

## 📞 Contact

- **Security Email**: agit8or@agit8or.net
- **Response Time**: Within 48 hours
- **PGP Key**: Available upon request

## 🐾 Luna's Security Tips

1. **Always use HTTPS** - No excuses in production
2. **Keep secrets secret** - Never commit credentials
3. **Update regularly** - Patch known vulnerabilities
4. **Monitor logs** - Watch for suspicious activity
5. **Backup everything** - Have a recovery plan
6. **Test your setup** - Verify security measures work
7. **Principle of least privilege** - Give minimum necessary permissions
8. **Defense in depth** - Multiple layers of security

---

**Last Updated**: January 2026
**Reviewed By**: Luna the GSD 🐕
