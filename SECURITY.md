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
- ✅ **Password Breach Detection** - HaveIBeenPwned integration with k-anonymity

## 🔍 Password Breach Detection

### Overview

HuduGlue includes automatic password breach detection powered by the [HaveIBeenPwned (HIBP)](https://haveibeenpwned.com/) database. This feature checks passwords against a database of over 600 million compromised passwords from real-world data breaches.

### Privacy Protection: k-Anonymity Model

**Your passwords are NEVER sent to any third party.** We use HIBP's k-anonymity API, which ensures complete privacy:

#### How It Works:

1. **Hash Generation**: Your password is hashed locally using SHA-1
   ```
   Example: "MyPassword123" → SHA-1 → "5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8"
   ```

2. **Hash Prefix Extraction**: Only the **first 5 characters** of the hash are extracted
   ```
   "5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8" → "5BAA6"
   ```

3. **API Query**: This 5-character prefix is sent to the HIBP API
   ```
   Request: GET https://api.pwnedpasswords.com/range/5BAA6
   ```

4. **Response Processing**: The API returns **all hash suffixes** that match this prefix (typically 400-600 matches)
   ```
   Response:
   1E4C9B93F3F0682250B6CF8331B7EE68FD8:247
   2F1D4E8C7B6A5F4E3D2C1B0A9F8E7D6C5:12
   ...
   ```

5. **Local Verification**: Your system checks if your full hash suffix appears in the response
   - If found → Password is breached
   - If not found → Password is safe

#### Why This Is Secure:

- **No password transmitted**: Only a 5-character hash prefix is sent
- **No way to reverse**: SHA-1 hashes cannot be reversed to obtain the original password
- **Plausible deniability**: The 5-character prefix matches 400-600 different passwords
- **Zero knowledge**: The HIBP service never learns your actual password or even your full hash

This is the same k-anonymity approach used by:
- Google Chrome password check
- Mozilla Firefox Monitor
- 1Password Watchtower
- Bitwarden

### Features

#### Automatic Scanning
- **On Save**: Passwords are checked when created or updated
- **Scheduled Scanning**: Automatic periodic checks at configurable intervals
- **Manual Testing**: "Test Now" button for on-demand verification

#### Configurable Scan Frequencies
You can set individual scan frequencies for each password:
- Every 2 hours (high-security credentials)
- Every 4 hours
- Every 8 hours
- Every 16 hours
- Every 24 hours (default)

#### Visual Indicators
Passwords are marked with clear security status:
- 🟢 **Green checkmark**: Safe (not found in breach database)
- 🔴 **Red X**: Compromised (found in data breaches)
- ⚪ **Gray question mark**: Unchecked (never scanned)

#### Breach Information
When a password is compromised, you'll see:
- Total number of times the password appears in breach databases
- Last time the password was checked
- Prominent warning banner on password detail pages
- "Change Password Now" button for immediate action

### Configuration

Configure breach checking in your `.env` file:

```bash
# Enable/disable breach checking (default: True)
HIBP_ENABLED=True

# Check passwords on save (default: True)
HIBP_CHECK_ON_SAVE=True

# Block breached passwords from being saved (default: False)
# When True, users cannot save passwords found in breaches
# When False, users receive a warning but can still save
HIBP_BLOCK_BREACHED=False

# Default scan frequency in hours (default: 24)
HIBP_SCAN_FREQUENCY=24

# Optional: HIBP API key for increased rate limits
# Free tier: 100 requests per 15 minutes
# With API key: 5000 requests per 15 minutes
HIBP_API_KEY=your_api_key_here
```

### Performance & Caching

- **Response caching**: API responses are cached for 24 hours
- **Reduced API calls**: Caching ensures the same hash prefix isn't checked multiple times
- **Rate limiting compliance**: Built-in rate limiting respects HIBP API limits
- **Graceful degradation**: If the API is unavailable, passwords can still be saved (fail-open)

### Scheduled Scanning

Set up automatic breach scanning with a scheduled task:

```bash
# Add to crontab
0 2 * * * cd /path/to/huduglue && source venv/bin/activate && python manage.py check_password_breaches
```

Or use the built-in scheduled task system:
1. Go to System → Scheduled Tasks
2. Create new task: "Password Breach Scanning"
3. Task Type: `password_breach_scan`
4. Interval: Configure as needed

### Management Commands

```bash
# Check all passwords
python manage.py check_password_breaches

# Force check (ignore last check time)
python manage.py check_password_breaches --force

# Check specific password by ID
python manage.py check_password_breaches --password-id 123

# Check all passwords for specific organization
python manage.py check_password_breaches --organization-id 5
```

### Audit Logging

All breach checks are logged for security auditing:
- When: Timestamp of check
- Who: User who initiated the check (for manual tests)
- What: Password checked and result (breached/safe)
- Where: IP address and user agent

View audit logs at: **System → Audit Logs**

### Best Practices

1. **Enable scheduled scanning**: Set up daily or hourly automated scans
2. **Review breached passwords immediately**: Address compromised passwords as soon as detected
3. **Consider blocking breached passwords**: Set `HIBP_BLOCK_BREACHED=True` to prevent users from saving compromised passwords
4. **Educate users**: Explain why breached passwords are dangerous, even if the user hasn't personally been breached
5. **Use scan frequency wisely**: High-value credentials should be checked more frequently

### Why Breached Passwords Matter

Even if you've never been breached personally, using a password that appears in breach databases is dangerous because:

1. **Credential Stuffing**: Attackers use lists of breached passwords to try automated login attempts across thousands of sites
2. **Password Spraying**: Common breached passwords are tested against many accounts
3. **Dictionary Attacks**: Breached passwords are added to attack dictionaries
4. **Social Engineering**: Knowledge of breached passwords can be used in phishing attempts

### About HaveIBeenPwned

HaveIBeenPwned is a free service created by security researcher Troy Hunt. The database contains:
- 600+ million real passwords from actual data breaches
- 11+ billion compromised accounts
- Regular updates as new breaches are discovered
- Used by millions of people and organizations worldwide

Learn more: [https://haveibeenpwned.com/Passwords](https://haveibeenpwned.com/Passwords)

### Privacy Guarantee

HuduGlue's implementation ensures:
- ✅ Passwords never leave your server in plaintext
- ✅ Full password hashes never leave your server
- ✅ Only 5-character hash prefixes are transmitted
- ✅ The HIBP service cannot determine your password
- ✅ No personally identifiable information is sent to HIBP
- ✅ All passwords remain encrypted in your database

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
- [ ] Password breach checking enabled (`HIBP_ENABLED=True`)
- [ ] Scheduled password breach scans configured

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
