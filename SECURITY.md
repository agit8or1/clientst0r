# Client St0r Security Policy

## Reporting Security Vulnerabilities

**We take security seriously.** If you discover a security vulnerability in Client St0r, please report it responsibly.

### How to Report

**Preferred Method:**
- Use GitHub's Security Advisories: [Report a vulnerability](https://github.com/agit8or1/clientst0r/security/advisories/new)

**Alternative Contact:**
- Email: [agit8or@agit8or.net](mailto:agit8or@agit8or.net) — please do not report vulnerabilities in public issues

### What to Include

Please provide as much information as possible:
- Type of vulnerability (e.g., XSS, SQL injection, authentication bypass)
- Step-by-step instructions to reproduce the issue
- Affected versions
- Potential impact and severity assessment
- Proof-of-concept or exploit code (if applicable)
- Suggested fix (if you have one)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Critical issues within 30 days, others within 90 days
- **Public Disclosure**: After patch is released and users have reasonable time to update (typically 30 days)

### Supported Versions

| Version  | Supported          |
| -------- | ------------------ |
| 3.17.x   | :white_check_mark: |
| < 3.17   | :x:                |

Security updates land on the current release line only. ClientSt0r ships continuously and
upgrades in place from the web UI (**Admin → System → System Updates**), so the supported
line is always the latest one — update rather than pinning an older release.

### Disclosure Policy

- **Responsible Disclosure**: We request 90 days before public disclosure
- **Credit**: We will credit researchers in release notes (unless you prefer to remain anonymous)
- **CVE Assignment**: For critical vulnerabilities, we will request CVE assignment
- **Security Advisories**: Published on GitHub Security Advisories

---

## Security Documentation

**Applies to:** the current 3.17.x line
**Last reviewed:** 2026-10-15
**Architecture:** Django 6 + DRF + Gunicorn + MariaDB; AI providers optional

Client St0r implements defense-in-depth security with multiple layers of protection based on OWASP best practices and Django security guidelines. Where a control is partial or not yet implemented, this document says so; [FEATURES.md](FEATURES.md#security) labels each capability Available / Limited / Planned.

---

## Table of Contents

1. [Reporting Security Vulnerabilities](#reporting-security-vulnerabilities)
2. [Security Features](#security-features)
3. [Production Security Checklist](#production-security-checklist)
4. [Environment Configuration](#environment-configuration)
5. [Tenant Isolation](#tenant-isolation)
6. [API Security](#api-security)
7. [AI Endpoint Protection](#ai-endpoint-protection)
8. [Secrets Management](#secrets-management)
9. [Security Headers](#security-headers)
10. [Rate Limiting & Throttling](#rate-limiting--throttling)
11. [Authentication & Authorization](#authentication--authorization)
12. [Monitoring & Auditing](#monitoring--auditing)
13. [Incident Response](#incident-response)
14. [Phase 2: Advanced Security](#phase-2-advanced-security)

---

## Security Features

### Security Controls

#### Authentication & Authorization
- **Password Hashing**: Argon2 (OWASP recommended, resists GPU attacks)
- **2FA**: Mandatory TOTP via django-otp (Google Authenticator, Authy, etc.)
- **SSO**: Azure AD / Microsoft Entra ID OAuth integration
- **LDAP / Active Directory**: sign-in via `django-auth-ldap` (optional packages in `requirements-optional.txt`), LDAPS or StartTLS with certificate checking on by default, required group, optional MSP staff group; never creates superusers or takes over an existing local account; same 2FA and lockout rules as local users (v3.17.608)
- **Brute Force Protection**: django-axes, by username + IP (defaults: 5 attempts, 30-minute lockout, set in Settings → Security)
- **Multi-Tenancy**: Organization-based with automated isolation tests. MSP staff (superusers, or User Type = Staff) work across all organizations; customer users are limited to their own organizations, see only tickets shared with the client, and never see internal comments or attachments (v3.17.599–600)
- **Role view permissions**: View passwords / documents / assets are enforced in the web UI, search, dashboards, REST and GraphQL APIs, mobile app and browser extension (v3.17.600). View files / monitors / integrations are not enforced yet
- **Session Management**: Secure cookies with HttpOnly, Secure, SameSite=Lax; idle timeout (default 60 minutes) and a real maximum session length (default 8 hours) set in Settings → Security
- **Security settings precedence** (v3.17.610): the saved Settings → Security values (idle timeout, maximum session length, require 2FA, password minimum length and special-character rule, failed-login limit, lockout duration) take effect. An environment variable, if set, wins — `SESSION_IDLE_TIMEOUT` and `SESSION_COOKIE_AGE` (seconds), `REQUIRE_2FA`, `PASSWORD_MIN_LENGTH`, `PASSWORD_REQUIRE_SPECIAL`, `AXES_FAILURE_LIMIT`, `AXES_COOLOFF_TIME` (hours) — and the field shows "set by environment" and can't be changed in the UI. **Before updating an older install, check Settings → Security**: without `AXES_COOLOFF_TIME` the lockout becomes the saved value (default 30 minutes), and an install with "Require 2FA" unticked and no `REQUIRE_2FA` variable stops requiring 2FA

#### Data Protection
- **Vault encryption**: AES-256-GCM; per-purpose keys derived from `APP_MASTER_KEY` with HKDF-SHA256, with the record's context bound as associated data (vault passwords, TOTP secrets, personal vault)
- **Other stored secrets** (v3.17.607): every stored secret is encrypted or, for tokens the app only needs to compare, stored as a hash — integration and connection credentials, SMTP and SMS passwords, the LDAP bind password and Azure AD client secret, warranty and security-scanner API keys, partner secrets, webhook secrets and custom headers, import API keys, push-notification secrets, license keys, security-vendor and SIEM credentials, and browser-extension and inbound webhook tokens. Secrets use AES-256-GCM with an HKDF-derived key, bound to the field they belong to. A few session and share-link tokens are being moved to hashed storage
- **No secret echo**: forms never show a stored secret back; leave a secret field blank to keep it. Webhook header values show as `********`; inbound webhook URLs and tokens are shown once
- **Key rotation**: `manage.py rotate_encryption_key`, with `APP_MASTER_KEY_PREVIOUS` for old keys (see [Key Rotation](#key-rotation)); `manage.py check_secrets_storage` reports anything stored unprotected
- **API keys**: stored as HMAC-SHA256 hashes (only a prefix in plaintext); stop working when the owning user is deactivated
- **Backups**: `manage.py backup` encrypts archives with a key derived from `APP_MASTER_KEY` (Fernet)
- **Uploaded files**: every `/media/` request is permission-checked against the record the file belongs to (v3.17.600)

#### API Security (DRF)
- **Production Mode**: Browsable API disabled, JSON-only renderers
- **Throttling**: 6 granular scopes (anon, user, login, password_reset, token, AI)
- **Authentication**: API key + session-based
- **Permissions**: IsAuthenticated by default
- **Schema/Docs**: Require authentication

#### Web Security
- **CSP**: Content-Security-Policy on every page with a per-request nonce on inline scripts; report-only by default (v3.17.610) — see [CSP](#csp-content-security-policy)
- **HSTS**: 1-year max-age (31536000 seconds) in production
- **Clickjacking**: X-Frame-Options: DENY
- **MIME Sniffing**: X-Content-Type-Options: nosniff
- **Referrer Policy**: strict-origin-when-cross-origin
- **Permissions-Policy**: Disables geolocation, camera, microphone, payment, USB, FLoC
- **CSRF**: Multi-domain support with trusted origins
- **XSS Protection**: template auto-escaping, HTML sanitisation of documents, secure cookies, CSP

#### AI Protection (OPTIONAL AI)
- **Request Limits**: Per-user (100/day) and per-org (1000/day)
- **Spend Caps**: Per-user ($10/day) and per-org ($100/day)
- **Burst Protection**: 10 requests/minute
- **Size Limits**: 10,000 characters per prompt
- **PII Redaction**: implemented (`core/ai_abuse_control.py`) but not yet called by the AI features, so `AI_PII_REDACTION_ENABLED` currently has no effect — planned
- **Usage Tracking**: Redis-backed counters with 24-hour TTL
- **Audit Logging**: All AI requests logged

#### Compliance & Testing
- **Password Breach Detection**: HaveIBeenPwned k-anonymity integration
- **Vulnerability Scanning**: Snyk for Python/JS dependencies
- **Tenant Isolation Tests**: Automated test suite (11 test cases)
- **Audit Trail**: Comprehensive logging of security events

---

## Production Security Checklist

### Pre-Deployment (Required)

#### 1. Environment Variables
```bash
# ===== CRITICAL SECRETS =====
# Django secret key (unique per environment, 50+ characters)
SECRET_KEY=<generate-with-django-command>

# Encryption master key (for vault passwords, credentials)
APP_MASTER_KEY=<generate-with-secrets-command>

# API key signing secret (MUST differ from SECRET_KEY)
API_KEY_SECRET=<generate-separate-secret>

# Database password (strong, unique)
DB_PASSWORD=<strong-password>

# Anthropic API key (if using AI features)
ANTHROPIC_API_KEY=sk-ant-...

# ===== SECURITY SETTINGS =====
DEBUG=False
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
# Optional. If set, overrides Settings → Security and locks the field there.
REQUIRE_2FA=True
# Content-Security-Policy: report-only by default; set False to enforce
CSP_REPORT_ONLY=True

# ===== ALLOWED HOSTS =====
ALLOWED_HOSTS=clientst0r.example.com,www.clientst0r.example.com
CSRF_TRUSTED_ORIGINS=https://clientst0r.example.com,https://www.clientst0r.example.com

# ===== AI LIMITS =====
AI_MAX_DAILY_REQUESTS_PER_USER=100
AI_MAX_DAILY_REQUESTS_PER_ORG=1000
AI_MAX_DAILY_SPEND_PER_USER=10.00
AI_MAX_DAILY_SPEND_PER_ORG=100.00

# ===== BRUTE FORCE PROTECTION =====
# Optional. Leave unset to manage these in Settings → Security.
# If set, they win and the fields there become read-only.
# AXES_FAILURE_LIMIT=5
# AXES_COOLOFF_TIME=1   # hours
```

#### 2. Generate Secrets
```bash
# SECRET_KEY (Django)
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# APP_MASTER_KEY (encryption) — base64 of 32 random bytes
python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

# API_KEY_SECRET (must differ from SECRET_KEY)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### 3. Validate Configuration
```bash
# Django's deployment checks
python manage.py check --deploy

# Confirm APP_MASTER_KEY can encrypt and decrypt
python manage.py shell -c "from vault.encryption import encrypt, decrypt; assert decrypt(encrypt('ok')) == 'ok'; print('APP_MASTER_KEY OK')"
```

#### 4. Run Security Tests
```bash
# Tenant isolation tests (CRITICAL - must pass)
python manage.py test core.tests.test_tenant_isolation -v 2

# All 11 tests must pass before production deployment
```

#### 5. Infrastructure Checklist
- [ ] Reverse proxy (nginx/caddy) terminates SSL
- [ ] Valid SSL certificate (Let's Encrypt or commercial)
- [ ] HTTPS-only (HTTP redirects to HTTPS)
- [ ] Database requires TLS (if remote)
- [ ] Database backups enabled and tested (daily + retention)
- [ ] Firewall rules limit access (SSH, database, application ports only)
- [ ] Fail2ban or similar for SSH brute force protection
- [ ] Log rotation configured (logrotate)
- [ ] Monitoring/alerting configured (Prometheus, Grafana, etc.)

#### 6. Application Checklist
- [ ] Admin username changed from default
- [ ] All users have 2FA enabled (Settings → Security → Require 2FA, or REQUIRE_2FA=True)
- [ ] Settings → Security reviewed (session, lockout and password-policy values are live)
- [ ] `python manage.py check_secrets_storage` reports nothing unprotected
- [ ] Unnecessary endpoints disabled
- [ ] Rate limits appropriate for traffic patterns
- [ ] AI spend limits appropriate for budget
- [ ] Snyk scans running and reviewed
- [ ] Audit logs reviewed for anomalies

#### 7. HSTS Rollout (Gradual)
```bash
# Week 1: Test with short duration
SECURE_HSTS_SECONDS=300  # 5 minutes

# Week 2: Increase
SECURE_HSTS_SECONDS=86400  # 1 day

# Month 1: Increase
SECURE_HSTS_SECONDS=2592000  # 30 days

# Month 6+: Final (1 year)
SECURE_HSTS_SECONDS=31536000  # 1 year

# Optional: HSTS Preload (IRREVERSIBLE - be 100% sure)
SECURE_HSTS_PRELOAD=True
# Submit to: https://hstspreload.org/
```

### Post-Deployment Validation

#### 1. Security Headers Scan
```bash
# Verify all headers present
curl -I https://your-domain.com

# Online scanner (should score A or A+)
https://securityheaders.com/?q=your-domain.com
```

Expected headers:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=(), ...`

#### 2. SSL/TLS Configuration
```bash
# Test SSL configuration (should be A or A+)
https://www.ssllabs.com/ssltest/analyze.html?d=your-domain.com
```

#### 4. Tenant Isolation Verification
```bash
# Run automated tests
python manage.py test core.tests.test_tenant_isolation -v 2

# Manual verification:
# 1. Create two test organizations
# 2. Create user in each org
# 3. Create data (passwords, assets) for each org
# 4. Login as User A, try to access User B's data via URL manipulation
# 5. Verify 403/404 (never 200 with wrong org's data)
```

#### 5. AI Usage Monitoring
```bash
# Check AI usage stats in Django admin or via API
from core.ai_abuse_control import get_ai_usage_stats

stats = get_ai_usage_stats(user=user, organization=org)
print(stats)
```

---

## Environment Configuration

### Critical Environment Variables

```bash
# ========================================
# DJANGO CORE
# ========================================
SECRET_KEY=<unique-50+-character-string>
DEBUG=False
ALLOWED_HOSTS=clientst0r.example.com
CSRF_TRUSTED_ORIGINS=https://clientst0r.example.com

# ========================================
# DATABASE (MariaDB)
# ========================================
DB_ENGINE=mysql
DB_NAME=clientst0r
DB_USER=clientst0r_user
DB_PASSWORD=<strong-password>
DB_HOST=localhost
DB_PORT=3306

# Optional: Enable TLS for remote database
DB_TLS_ENABLED=True
DB_TLS_CA=/path/to/ca-cert.pem

# ========================================
# ENCRYPTION & SECRETS
# ========================================
# Master key for encrypting vault passwords, credentials, tokens
APP_MASTER_KEY=<unique-key-for-encryption>

# API key signing secret (MUST differ from SECRET_KEY)
API_KEY_SECRET=<unique-key-different-from-SECRET_KEY>

# ========================================
# SECURITY
# ========================================
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_PRELOAD=False  # Set to True only after 1+ year of HSTS
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
REQUIRE_2FA=True

# ========================================
# BRUTE FORCE PROTECTION (django-axes)
# ========================================
# Optional overrides of Settings → Security (the field shows "set by environment")
# AXES_FAILURE_LIMIT=5
# AXES_COOLOFF_TIME=1  # hours

# ========================================
# CONTENT-SECURITY-POLICY
# ========================================
CSP_ENABLED=True       # False turns the header off entirely
CSP_REPORT_ONLY=True   # False enforces; check the security.csp log first

# ========================================
# KEY ROTATION (only while rotating, or to restore older backups)
# ========================================
# APP_MASTER_KEY_PREVIOUS=<old key>[,<older key>]

# ========================================
# AI (Anthropic)
# ========================================
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-5-20250929

# AI Abuse Controls
AI_MAX_PROMPT_LENGTH=10000
AI_MAX_DAILY_REQUESTS_PER_USER=100
AI_MAX_DAILY_REQUESTS_PER_ORG=1000
AI_MAX_DAILY_SPEND_PER_USER=10.00
AI_MAX_DAILY_SPEND_PER_ORG=100.00
AI_PII_REDACTION_ENABLED=True

# ========================================
# PASSWORD BREACH CHECKING (HaveIBeenPwned)
# ========================================
HIBP_ENABLED=True
HIBP_API_KEY=  # Optional, increases rate limit
HIBP_CHECK_ON_SAVE=True
HIBP_BLOCK_BREACHED=False  # Set to True to block breached passwords

# ========================================
# EXTERNAL APIS (Optional)
# ========================================
GOOGLE_MAPS_API_KEY=
MAPBOX_ACCESS_TOKEN=
BING_MAPS_API_KEY=
```

### Development vs Production

```bash
# Development (.env.dev)
DEBUG=True
SECRET_KEY=dev-key-insecure
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
REQUIRE_2FA=False

# Production (.env.prod)
DEBUG=False
SECRET_KEY=<actual-secret-50+-chars>
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
REQUIRE_2FA=True
```

---

## Tenant Isolation

### Architecture

Client St0r uses **single-database multi-tenancy** with `organization_id` filtering:

```
┌─────────────────────────────────────────────┐
│           Single Database (MariaDB)         │
├─────────────────────────────────────────────┤
│  All Models:                                │
│  - organization_id (ForeignKey)             │
│  - Filtered by OrganizationManager         │
├─────────────────────────────────────────────┤
│  Org 1 Data  │  Org 2 Data  │  Org 3 Data  │
│  (filtered)  │  (filtered)  │  (filtered)  │
└─────────────────────────────────────────────┘
         ↑              ↑              ↑
         │              │              │
    User A         User B         User C
   (Org 1)        (Org 2)        (Org 3)
```

**Key Components:**
1. **BaseModel**: All models inherit, adds `organization` ForeignKey
2. **OrganizationManager**: Custom manager that auto-filters by `organization_id`
3. **CurrentOrganizationMiddleware**: Sets organization context from authenticated user
4. **Object-Level Permissions**: All views check `organization` before allowing access

### Security Guarantees

✅ **Users CANNOT**:
- Access passwords from other organizations
- Access assets from other organizations
- Access documents, tickets, contacts from other organizations
- See audit logs from other organizations
- Make API requests for other organizations' data

✅ **Customer users additionally CANNOT** (v3.17.599–600):
- Open or edit another customer's contracts, invoices, projects, quotes, recurring schedules, purchase records, email-to-ticket configs, canned replies or client account by changing an ID, or create records for another customer by changing the client in a form
- See tickets not marked as visible to the client, internal comments, or internal attachments (staff pages, portal and mobile app)
- Open the global dashboard, edit global document templates, or read the MSP's global knowledge base through the APIs
- Download an uploaded file attached to a record they cannot see

MSP staff — superusers, users with Django's staff flag, and users whose **User Type** is *Staff* — work across every organization.

✅ **Enforced By**:
- Database-level filtering (OrganizationManager)
- View-level permissions (organization check, customer-user scoping)
- Role view permissions (View passwords / documents / assets)
- API-level filtering (DRF permissions)
- A permission-checked view for every `/media/` download
- Automated test suite

⚠️ **Known gaps**: some role checks pass when a permission is set on *any* of the user's memberships rather than the record's organization; View files / monitors / integrations are not enforced; financial reports cover every organization (grant **View financial reports** to MSP staff only). These are tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

### Testing Tenant Isolation

```bash
# Run full test suite
python manage.py test core.tests.test_tenant_isolation -v 2

# Tests include:
# 1. Password isolation (can't query other org's passwords)
# 2. Asset isolation (can't query other org's assets)
# 3. Document isolation
# 4. Audit log isolation
# 5. Cross-tenant API access (403/404 on other org's data)
# 6. Bulk operations respect boundaries
# 7. OrganizationManager filtering
# 8. Foreign key relationships
# 9. API list endpoints isolation
# 10. API detail endpoints isolation
# 11. Manager enforcement
```

### Manual Verification

```python
# Create two organizations
org1 = Organization.objects.create(name='Org 1', slug='org1')
org2 = Organization.objects.create(name='Org 2', slug='org2')

# Create data for each
password1 = Password.objects.create(organization=org1, title='Org1 Secret')
password2 = Password.objects.create(organization=org2, title='Org2 Secret')

# Verify isolation
assert Password.objects.filter(organization=org1).count() == 1
assert Password.objects.filter(organization=org2).count() == 1

# Cross-org query returns empty
assert Password.objects.filter(organization=org1, id=password2.id).count() == 0
```

---

## API Security

### DRF Configuration

#### Production: JSON-Only, No Browsable API

```python
# config/settings.py
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ] if not DEBUG else [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',  # Only in dev
    ],
}
```

**Why**: DRF's browsable API has had XSS vulnerabilities (CVE fixed in 3.15.2). Disabling in production reduces attack surface.

### Throttling Configuration

| Scope | Rate Limit | Purpose | Applied To |
|-------|-----------|---------|-----------|
| `anon` | 50/hour | Per-IP limit for unauthenticated users | All API endpoints |
| `user` | 1000/hour | Per-user limit for authenticated users | All API endpoints |
| `login` | 10/hour | Brute force protection | Login endpoint |
| `password_reset` | 5/hour | Abuse prevention | Password reset endpoint |
| `token` | 20/hour | API key operation limits | Token create/refresh/revoke |
| `ai_request` | 100/day | Cost protection (daily) | AI endpoints |
| `ai_burst` | 10/minute | Cost protection (burst) | AI endpoints |

### Custom Throttle Usage

```python
# In your view
from api.throttles import LoginThrottle, AIRequestThrottle, AIBurstThrottle

class LoginView(APIView):
    throttle_classes = [LoginThrottle]

class FloorplanGenerateView(APIView):
    throttle_classes = [AIRequestThrottle, AIBurstThrottle]
```

### API Key Authentication

```python
# Generate API key for user
from api.models import APIKey

api_key, plaintext = APIKey.create_key(
    organization=organization,
    user=user,
    name='My API Key',
)
print(f'Key: {plaintext}')  # Only shown once; only the HMAC hash is stored

# Use API key
curl -H "Authorization: Bearer itdocs_live_YOUR_KEY" https://clientst0r.example.com/api/passwords/
```

**Security Notes:**
- API keys hashed with HMAC-SHA256 using `API_KEY_SECRET` (separate from `SECRET_KEY`)
- Keys can be revoked without changing user password
- Rate-limited via DRF throttles
- Audit logged

---

## AI Endpoint Protection

### Four-Layer Defense

#### 1. Request Limits (Per-User & Per-Org)
```python
AI_MAX_DAILY_REQUESTS_PER_USER=100
AI_MAX_DAILY_REQUESTS_PER_ORG=1000
```

**How It Works:**
- Redis-backed counters with 24-hour TTL
- Middleware checks before processing request
- Returns 429 with reset time when exceeded

**Error Response:**
```json
{
  "error": "Daily AI request limit exceeded",
  "limit": 100,
  "used": 100,
  "reset_in_hours": 18.5
}
```

#### 2. Spend Caps (Cost Protection)
```python
AI_MAX_DAILY_SPEND_PER_USER=10.00  # USD
AI_MAX_DAILY_SPEND_PER_ORG=100.00  # USD
```

**How It Works:**
- Track estimated cost per request
- Accumulate daily spend in Redis
- Block when cap exceeded

#### 3. Burst Protection
```python
AI_BURST_LIMIT=10  # requests per minute
```

**How It Works:**
- Prevents rapid-fire API abuse
- DRF throttle with 1-minute window
- Separate from daily limit

#### 4. PII Redaction
```python
AI_PII_REDACTION_ENABLED=True
```

**Patterns Detected:**
- Emails: `user@example.com` → `[REDACTED_EMAIL]`
- Phones: `555-123-4567` → `[REDACTED_PHONE]`
- SSNs: `123-45-6789` → `[REDACTED_SSN]`
- Credit Cards: `4111-1111-1111-1111` → `[REDACTED_CARD]`
- API Keys: Long alphanumeric → `[REDACTED_KEY]`

**Usage:**
```python
from core.ai_abuse_control import PIIRedactor

# Redact before sending to AI
prompt = "Contact John at john@example.com or call 555-123-4567"
safe_prompt = PIIRedactor.redact(prompt)
# Result: "Contact John at [REDACTED_EMAIL] or call [REDACTED_PHONE]"

# Check for PII
pii_check = PIIRedactor.check_for_pii(prompt)
# Result: {'has_email': True, 'has_phone': True, 'has_ssn': False, ...}
```

### Usage Tracking

```python
from core.ai_abuse_control import get_ai_usage_stats

# Get current usage
stats = get_ai_usage_stats(
    user=request.user,
    organization=request.organization
)

# Returns:
{
    'user': {
        'requests_used': 15,
        'requests_limit': 100,
        'spend_used': 2.50,
        'spend_limit': 10.00
    },
    'organization': {
        'requests_used': 250,
        'requests_limit': 1000,
        'spend_used': 45.00,
        'spend_limit': 100.00
    }
}
```

### Configuring AI Endpoints

```python
# core/ai_abuse_control.py
class AIAbuseControlMiddleware:
    def __init__(self, get_response):
        self.ai_endpoints = [
            '/locations/generate-floorplan/',
            '/api/ai/',
        ]
```

Add your AI endpoints to this list to enable protection.

---

## Secrets Management

### Encryption Architecture

```
APP_MASTER_KEY (environment, base64 of 32 bytes)
  [+ APP_MASTER_KEY_PREVIOUS: older keys, decrypt only]
    │
    ├── HKDF-SHA256 (per purpose) ──► AES-256-GCM + associated data
    │       vault passwords, TOTP secrets, personal vault (bound to the record)
    │
    ├── HKDF-SHA256 ("field secrets") ──► AES-256-GCM, bound to "<app>.<Model>.<field>"
    │       stored as enc2$…: integration credentials, SMTP / SMS / LDAP passwords,
    │       secure notes, API keys and client secrets, webhook secrets and headers, …
    │
    └── Fernet (derived from the master key)
            encrypted backup archives

API_KEY_SECRET ──► HMAC-SHA256 hashes (never reversible)
        REST API keys, browser-extension tokens, inbound webhook tokens
```

Older values written in earlier formats are still decrypted, and the v3.17.607 update
converted existing plaintext and older-format values in place.

### What Gets Encrypted

- ✅ Vault passwords and TOTP secrets (`vault.Password`) — AES-256-GCM with per-purpose keys
- ✅ Personal vault entries — same, bound to the owning user. Encrypted with the server's master key, not a per-user key
- ✅ PSA, RMM, accounting, distributor and network-controller connection credentials, including OAuth tokens
- ✅ SMTP password, SMS provider token, email-to-ticket mailbox passwords
- ✅ LDAP bind password, Azure AD client secret
- ✅ Warranty and security-scanner API keys, security-vendor and SIEM credentials, partner secrets, license keys, push-notification secrets, import API keys
- ✅ Webhook signing secrets and custom header values
- ✅ Hashed, not encrypted: REST API keys (only a prefix in plaintext), browser-extension tokens, inbound webhook tokens. Installed extensions and webhook URLs already configured at vendors kept working through the conversion
- A few session and share-link tokens are being moved to hashed storage

Run `python manage.py check_secrets_storage` to confirm nothing is stored unprotected. It
prints table, column and primary key only — never values — and exits non-zero on any finding
(`--strict` also fails on accepted exceptions; `--schema-only` skips the data scan, so it
works in CI on an empty database).

### Key Generation

```bash
# Generate a new master key (base64 of 32 random bytes)
python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

# Set it in .env (native) or the compose .env file (Docker)
APP_MASTER_KEY=<the generated value>
```

Back the key up somewhere other than the server. Without it, encrypted data in the database
and in backups cannot be recovered.

### Key Rotation

`python manage.py rotate_encryption_key` re-encrypts every encrypted value under a new master
key in one transaction. Each value is decrypted with the old key(s), encrypted with the new
key and decrypted again with only the new key before anything is written; any failure rolls
the whole run back and the command exits non-zero. `--dry-run` does the full round trip and
rolls back.

Zero-downtime rotation (recommended):

```bash
# 1. Generate a new key
python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

# 2. In .env: APP_MASTER_KEY=<new>, APP_MASTER_KEY_PREVIOUS=<old>; reload the app.
#    It now writes with the new key and reads with both.

# 3. Re-encrypt everything to APP_MASTER_KEY
python manage.py rotate_encryption_key

# 4. Remove APP_MASTER_KEY_PREVIOUS (or keep it while you may restore older backups) and reload.
```

Offline alternative: stop the app, run
`python manage.py rotate_encryption_key --new-key-file /root/new.key`, then set
`APP_MASTER_KEY` to the new key and start it again.

Not covered by rotation: hashed tokens (keyed by `API_KEY_SECRET`, not the master key) and
backup archives already on disk — restore reads those while the old key is listed in
`APP_MASTER_KEY_PREVIOUS`.

If the key may be compromised, rotate it as above and also rotate the credentials stored in
ClientSt0r at their source (integration API keys, vault passwords).

### Validation

```bash
python manage.py check --deploy
python manage.py shell -c "from vault.encryption import encrypt, decrypt; assert decrypt(encrypt('ok')) == 'ok'; print('APP_MASTER_KEY OK')"
python manage.py check_secrets_storage
```

### Log Sanitization

```python
from core.secrets_management import sanitize_log_data

# Remove secrets before logging
data = {
    'username': 'admin',
    'password': 'secret123',
    'api_key': 'sk-ant-...',
    'email': 'user@example.com'
}

safe_data = sanitize_log_data(data)
# Result:
# {
#     'username': 'admin',
#     'password': '[REDACTED]',
#     'api_key': '[REDACTED]',
#     'email': 'user@example.com'
# }

logger.info(f'User data: {safe_data}')
```

**Sensitive Keys (Auto-Redacted):**
- password, secret, token, key
- api_key, api_secret, client_secret
- access_token, refresh_token, private_key
- app_master_key, db_password, anthropic_api_key

---

## Security Headers

### HSTS (HTTP Strict Transport Security)

**Purpose**: Force HTTPS for all connections

**Configuration:**
```python
SECURE_HSTS_SECONDS=31536000  # 1 year (production)
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=False  # Optional, irreversible
```

**Response Header:**
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

**Rollout Plan:**
```bash
# Week 1: Test
SECURE_HSTS_SECONDS=300  # 5 minutes

# Week 2
SECURE_HSTS_SECONDS=86400  # 1 day

# Month 1
SECURE_HSTS_SECONDS=2592000  # 30 days

# Month 6+: Production
SECURE_HSTS_SECONDS=31536000  # 1 year
```

**HSTS Preload (Optional, Advanced):**
- **Irreversible**: Once in preload list, can't be removed for months
- **Requirements**: 1+ year max-age, includeSubDomains, preload directive
- **Submit**: https://hstspreload.org/
- **Only enable if 100% sure HTTPS will work forever**

### CSP (Content Security Policy)

**Purpose**: Prevent XSS, clickjacking, code injection

Since v3.17.610 a Content-Security-Policy is sent on every HTML page by
`core.csp_middleware.ContentSecurityPolicyMiddleware`, with a per-request nonce on inline
`<script>` blocks (templates use `nonce="{{ csp_nonce }}"`).

**Rollout:** it starts in **report-only** mode (`Content-Security-Policy-Report-Only`).
Violations are reported to `CSP_REPORT_URI` (default `/csp-report/`, rate limited) and logged
to the `security.csp` logger; nothing is blocked. Once the log is quiet, enforce it:

```bash
# .env
CSP_REPORT_ONLY=False   # enforce (default True = report only)
CSP_ENABLED=False       # emergency switch: send no CSP header at all
CSP_REPORT_URI=         # empty = no report directive
```

**Policy** (`CSP_POLICY` in `config/settings.py`, summarised):

```
default-src 'self'
script-src 'self' 'nonce-…' + the CDNs the templates load from
script-src-attr 'unsafe-inline'      # remaining inline event handlers
style-src 'self' 'unsafe-inline' + CDNs
img-src 'self' data: blob: https:
connect-src 'self' https://api.pwnedpasswords.com https://embed.diagrams.net
frame-src 'self' https://embed.diagrams.net
object-src 'none'; base-uri 'self'; form-action 'self'
frame-ancestors 'none'               # 'self' on views that allow same-site framing
```

Inline `<script>` blocks need the nonce; inline event handlers and inline styles are still
allowed while they are migrated. The in-app PDF preview, which allows same-site framing,
gets `frame-ancestors 'self'`.

### Permissions-Policy (formerly Feature-Policy)

**Purpose**: Disable unnecessary browser features

**Configuration:**
```python
PERMISSIONS_POLICY = {
    'geolocation': [],      # Disable geolocation
    'microphone': [],       # Disable microphone
    'camera': [],           # Disable camera
    'payment': [],          # Disable payment API
    'usb': [],              # Disable USB access
    'interest-cohort': [],  # Disable FLoC (privacy)
}
```

**Response Header:**
```
Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=(), interest-cohort=()
```

**If You Need Features:**
```python
PERMISSIONS_POLICY = {
    'geolocation': ['self'],  # Allow geolocation on same origin
    'camera': ['self', 'https://trusted-video-site.com'],  # Allow camera
}
```

### Referrer-Policy

**Purpose**: Control what URL information is leaked in Referer header

**Configuration:**
```python
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
```

**Options:**
- `no-referrer`: Never send referrer
- `same-origin`: Send only for same-origin requests
- `strict-origin`: Send only origin (no path) for HTTPS → HTTPS
- `strict-origin-when-cross-origin`: Full URL for same-origin, origin only for cross-origin (RECOMMENDED)

### X-Frame-Options

**Purpose**: Prevent clickjacking

**Configuration:**
```python
X_FRAME_OPTIONS = 'DENY'
```

**Options:**
- `DENY`: Cannot be framed (recommended)
- `SAMEORIGIN`: Can only be framed by same origin
- `ALLOW-FROM uri`: Can be framed by specific URI (deprecated, use CSP frame-ancestors)

### X-Content-Type-Options

**Purpose**: Prevent MIME sniffing

**Configuration:**
```python
SECURE_CONTENT_TYPE_NOSNIFF = True
```

**Response Header:**
```
X-Content-Type-Options: nosniff
```

---

## Rate Limiting & Throttling

### DRF Throttles

```python
# config/settings.py
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '50/hour',          # Anonymous (per-IP)
        'user': '1000/hour',        # Authenticated users
        'login': '10/hour',         # Login attempts
        'password_reset': '5/hour', # Password reset
        'token': '20/hour',         # API tokens
        'ai_request': '100/day',    # AI requests (daily)
        'ai_burst': '10/minute',    # AI requests (burst)
    }
}
```

### Custom Throttle Classes

```python
# api/throttles.py
from rest_framework.throttling import UserRateThrottle

class LoginThrottle(UserRateThrottle):
    scope = 'login'

class AIRequestThrottle(UserRateThrottle):
    scope = 'ai_request'
```

### Brute Force Protection (django-axes)

The failed-login limit (default 5) and lockout duration (default 30 minutes) are set in
**Settings → Security**. `AXES_FAILURE_LIMIT` and `AXES_COOLOFF_TIME` (hours), if set in the
environment, override them and lock the fields.

```python
# config/settings.py
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_RESET_ON_SUCCESS = True
```

**How It Works:**
- Tracks failed login attempts per username + IP combo (LDAP users included)
- Locks the account for the lockout duration after the failure limit
- Resets counter on successful login
- Stored in database (persistent across restarts)

**View Locked Accounts:**
```python
# Django admin → Axes → Access attempts
# Or command line:
python manage.py axes_reset  # Clear all locks
python manage.py axes_reset_user username  # Clear specific user
```

---

## Authentication & Authorization

### Password Requirements

**Configuration:**
```python
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
```

**Requirements:**
- ✅ Minimum length — 12 by default, set in Settings → Security (`PASSWORD_MIN_LENGTH` overrides)
- ✅ Special-character rule — Settings → Security (`PASSWORD_REQUIRE_SPECIAL` overrides)
- ✅ Not similar to username/email/first name/last name
- ✅ Not in common password list (10,000+ passwords)
- ✅ Not entirely numeric
- ✅ Argon2 hashing (OWASP recommended)

### 2FA (Two-Factor Authentication)

**Configuration:**
**Require 2FA** is set in Settings → Security (on by default). The `REQUIRE_2FA` environment
variable, if set, overrides it and locks the field. LDAP users follow the same rule.

```python
TWO_FACTOR_PATCH_ADMIN = False
LOGIN_URL = 'two_factor:login'
```

**Setup Process:**
1. User scans QR code with authenticator app (Google Authenticator, Authy, etc.)
2. Enters 6-digit code to verify
3. Backup codes generated (10 single-use codes)
4. 2FA required on every login

**Disable 2FA (Admin Action):**
```python
# In Django admin or management command
from two_factor.models import Device

# Remove user's device
Device.objects.filter(user=user).delete()

# User must re-setup 2FA on next login
```

### API Keys

**Features:**
- Separate from user passwords
- Can be revoked without changing password
- Stop working when the owning user is deactivated, or when a customer user no longer belongs to the key's organization
- No expiry date — delete keys you no longer use
- Rate-limited via DRF throttles
- Audit logged
- Named (e.g., "Mobile App", "CI/CD")
- Created from the web UI at `/api/keys/`

**Generate:**
```python
from api.models import APIKey

api_key, plaintext = APIKey.create_key(
    organization=organization,
    user=user,
    name='My App',
)
print(f'Key: {plaintext}')  # Only shown once, hash stored
```

**Use:**
```bash
curl -H "Authorization: Bearer itdocs_live_YOUR_KEY" \
    https://clientst0r.example.com/api/passwords/
```

**Revoke:**
```python
api_key.delete()  # Or mark inactive
```

### SSO (Azure AD)

**Configuration:**
```python
# Azure AD settings in Django admin
AZURE_AD_TENANT_ID=<your-tenant-id>
AZURE_AD_CLIENT_ID=<your-client-id>
AZURE_AD_CLIENT_SECRET=<your-client-secret>
AZURE_AD_REDIRECT_URI=https://clientst0r.example.com/accounts/azure/callback/
AZURE_AD_AUTO_CREATE_USERS=True  # Auto-create on first login
```

**Flow:**
1. User clicks "Login with Microsoft"
2. Redirects to Azure AD
3. User authenticates with Microsoft
4. Callback to Client St0r with OAuth code
5. Exchange code for access token
6. Fetch user info from Microsoft Graph API
7. Create/update user in Client St0r
8. Log in user

**Security:**
- OAuth 2.0 / OpenID Connect
- No passwords stored in Client St0r
- Updates user info on each login
- Audit logged

### LDAP / Active Directory

Since v3.17.608, configured at **Settings → Directory** (`/core/settings/directory/`). Off
until enabled, and it won't switch on with missing or invalid settings.

- Requires the optional packages `django-auth-ldap` and `python-ldap`
  (`pip install -r requirements-optional.txt`; `python-ldap` needs the system packages
  listed in that file). The settings page says if they're missing.
- Several servers; LDAPS or StartTLS with certificate checking (on by default, optional CA
  file).
- User search with attribute mapping; a required group (nested Active Directory groups
  included); an optional MSP staff group that decides at each sign-in whether a user is
  Staff or a customer user.
- **Test connection** checks the bind and an optional user lookup without saving anything or
  showing secrets. The bind password is stored encrypted.
- Local accounts keep working, and a local superuser can always sign in if the directory is
  down. LDAP users get the same 2FA rules and lockout as local users. LDAP never makes anyone
  a superuser and never takes over an existing local account with the same username.

---

## Monitoring & Auditing

### Audit Logging

**What Gets Logged:**

Entries come from two sources: explicit audit events, and a request log that records every
POST/PUT/DELETE and detail-page view (method, path, status, redacted form fields). Items
below may be covered by either. Most changes are stored without before/after values.

- ✅ Login/logout (success and failure)
- ✅ Password changes
- ✅ 2FA setup/changes
- ✅ API key operations (create, revoke)
- ✅ Data exports
- ✅ Permission changes
- ✅ User creation/deletion
- ✅ Organization changes
- ✅ Cross-org access attempts (should be 0)
- ✅ AI requests
- ✅ Configuration changes

**Audit Log Model:**
```python
class AuditLog(models.Model):
    # Who
    user = ForeignKey(User)
    username = CharField(max_length=150)  # Preserved even if user deleted

    # What
    action = CharField(max_length=50)  # create, read, update, delete, login, etc.
    object_type = CharField(max_length=100)
    object_id = PositiveIntegerField()
    description = TextField()

    # Where
    organization = ForeignKey(Organization)
    ip_address = GenericIPAddressField()
    user_agent = TextField()
    path = CharField(max_length=500)

    # When
    timestamp = DateTimeField(auto_now_add=True)

    # Additional
    extra_data = JSONField()
    success = BooleanField(default=True)
```

**Query Audit Logs:**
```python
# Failed login attempts
AuditLog.objects.filter(action='login', success=False)

# Recent password changes
AuditLog.objects.filter(action='update', object_type='password').order_by('-timestamp')[:10]

# User activity
AuditLog.objects.filter(user=user).order_by('-timestamp')[:100]

# Organization activity
AuditLog.objects.filter(organization=org).order_by('-timestamp')
```

### Snyk Vulnerability Scanning

**Configuration:**
```python
# Django admin → Settings → Snyk Security
SNYK_API_TOKEN=<your-snyk-token>  # Optional for enhanced features
SNYK_ENABLED=True
SNYK_SCAN_SCHEDULE='daily'  # Options: daily, weekly, monthly
SNYK_AUTO_FIX=False  # Enable automated dependency updates
SNYK_SEVERITY_THRESHOLD='low'  # Alert on: critical, high, medium, low
```

**What Gets Scanned:**
- **Python Dependencies** - All packages in requirements.txt and installed packages
- **JavaScript Dependencies** - package.json, package-lock.json, node_modules
- **Docker Images** - Container security scanning (if using Docker deployment)
- **Infrastructure as Code** - Kubernetes/Terraform configs (if present)
- **License Compliance** - Check for problematic licenses

**Scan Process:**
1. **Automatic Scans** - Runs on configured schedule via systemd timer
2. **Manual Scans** - One-click from Admin → Settings → Snyk Security → Run Scan
3. **GitHub Integration** - Automatic scans on pull requests (if GitHub Actions enabled)
4. **Result Processing**:
   - Parses JSON output from Snyk CLI
   - Categorizes by severity (critical, high, medium, low)
   - Stores in database with timestamp
   - Tracks trends and changes over time
   - Generates remediation recommendations

**Web UI Dashboard (Admin → Settings → Snyk Security):**
- **Total Vulnerability Count** - Current known vulnerabilities
- **Severity Breakdown** - Critical, high, medium, low counts with color coding
- **Trend Analysis** - Graph showing vulnerability trends (improving/worsening)
- **Recent Scan History** - List of recent scans with timestamps and results
- **Detailed Findings** - Package name, current version, vulnerable version, fixed version
- **Remediation Advice** - Specific upgrade commands and breaking change warnings
- **Severity Filters** - Filter view by severity level
- **Export Options** - Download scan results as JSON/CSV

**Features:**
- **Zero-Config Mode** - Works without API token (limited features)
- **Enhanced Mode** - With API token: deeper scans, more context, automated fixes
- **Email Alerts** - Notify admins when critical vulnerabilities found
- **Threshold Alerts** - Only alert on specified severity levels
- **Ignore List** - Mark specific vulnerabilities as accepted risk
- **Scheduled Reports** - Weekly/monthly summary emails

**Run Scan:**
```bash
# Manual scan via CLI
python manage.py run_snyk_scan

# With options
python manage.py run_snyk_scan --severity-threshold high --json

# Or via Web UI
# Admin → Settings → Snyk Security → Run Scan Now button (/core/settings/snyk/)
```

**Integration with CI/CD:**
- GitHub Actions workflow included (`.github/workflows/snyk.yml`)
- Automatic scans on push to main branch
- PR checks for new vulnerabilities
- Fail build on critical vulnerabilities (configurable)

### Log Files

```
/var/log/itdocs/
├── django.log              # Application logs
├── gunicorn-access.log     # HTTP access logs
├── gunicorn-error.log      # HTTP error logs
└── audit.log               # Security audit trail (if separate)
```

**Log Rotation:**
```bash
# /etc/logrotate.d/clientst0r
/var/log/itdocs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 www-data www-data
    sharedscripts
    postrotate
        systemctl reload clientst0r-gunicorn
    endscript
}
```

---

## Incident Response

### Detection

**Monitor For:**
- Spike in failed login attempts (check Axes logs)
- Unusual API usage patterns (check audit logs)
- AI usage spikes (check AI usage stats)
- Cross-org access attempts (should be 0, check audit logs)
- Snyk critical vulnerabilities
- Unusual IP addresses in audit logs

**Tools:**
- Django admin → Audit Logs
- Django admin → Axes → Access Attempts
- Security Dashboard → Vulnerability Scans
- Grep logs: `grep "FAILED LOGIN" /var/log/itdocs/django.log`

### Containment

**If Compromised:**

1. **Disable Affected Accounts:**
```python
user.is_active = False
user.save()
```

2. **Block Attacker IPs:**
```bash
# Firewall
iptables -A INPUT -s <attacker-ip> -j DROP

# Or fail2ban
fail2ban-client set clientst0r banip <attacker-ip>
```

3. **Revoke API Keys:**
```python
APIKey.objects.filter(user=compromised_user).delete()
```

4. **Change Passwords:**
```python
# Force password reset
user.set_unusable_password()
user.save()

# Email user with reset link
```

5. **Remove 2FA Devices (if compromised):**
```python
Device.objects.filter(user=user).delete()
```

### Eradication

1. **Patch Vulnerabilities:**
```bash
# Check Snyk dashboard for recommendations
pip install --upgrade <vulnerable-package>

# Or apply Snyk automated PR
git pull origin snyk-fix-<vuln-id>
```

2. **Rotate Secrets:**
```bash
# Rotate the affected credentials at their source and re-enter them,
# revoke API keys and browser-extension tokens, and reset user passwords.
# If APP_MASTER_KEY may be exposed, rotate it (see Key Rotation):
python manage.py rotate_encryption_key
```

3. **Reset 2FA:**
```python
# Force all users to re-setup 2FA
Device.objects.all().delete()
```

4. **Review Audit Logs:**
```python
# Check for data exfiltration
AuditLog.objects.filter(
    action='export',
    timestamp__gte=incident_start_time
)
```

### Recovery

1. **Restore from Backup (if data corruption):**
```bash
# Database restore
mysql -u root -p clientst0r < backup_2026-01-14.sql

# File restore
rsync -av /backups/media/ /var/lib/itdocs/uploads/
```

2. **Re-enable Accounts:**
```python
user.is_active = True
user.save()
```

3. **Verify Tenant Isolation:**
```bash
python manage.py test core.tests.test_tenant_isolation -v 2
```

### Lessons Learned

**Document:**
- What happened?
- When did it happen?
- How was it detected?
- What was compromised?
- How was it contained?
- What was the root cause?
- How can we prevent this in the future?

**Update:**
- Security procedures
- Monitoring/alerting rules
- Rate limits (if abuse)
- AI spend caps (if cost abuse)
- Firewall rules
- Access controls

---

## Phase 2: Advanced Security

### Next Steps for Enterprise Hardening

See separate section below for copy/paste implementation guide.

**Includes:**
1. MariaDB hardening (TLS, least-privilege, backups)
2. Gunicorn configuration review
3. Build security (Semgrep, Gitleaks, SBOM)
4. GitHub Actions pinning
5. Supply chain security

---

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Django Security](https://docs.djangoproject.com/en/5.0/topics/security/)
- [DRF Authentication](https://www.django-rest-framework.org/api-guide/authentication/)
- [CSP Reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- [HSTS Preload](https://hstspreload.org/)
- [Security Headers](https://securityheaders.com/)
- [SSL Labs](https://www.ssllabs.com/ssltest/)

---

**Last reviewed:** 2026-10-15
**Applies to:** the current 3.17.x line
**Maintainer:** Client St0r Security Team

---

## Implemented Controls

### Tier 1 — DRF Production Hardening
- Browsable API disabled automatically in production (JSON-only when DEBUG=False)
- Granular throttling scopes:
  - Anonymous: 50/hour
  - Login: 10/hour
  - Password reset: 5/hour
  - Token ops: 20/hour
  - AI requests: 100/day + 10/min burst
- Custom throttle classes in `api/throttles.py`

### Tier 2 — Security Headers & CSP
- HSTS enabled in production (max-age=31536000)
- SSL redirect enabled in production
- Proxy SSL header configured
- Referrer-Policy: strict-origin-when-cross-origin
- Content-Security-Policy with per-request script nonces, report-only by default (`CSP_REPORT_ONLY`, `CSP_ENABLED`); frame-ancestors 'none', object-src 'none', base-uri 'self', form-action 'self'
- Permissions-Policy defaults deny sensitive browser capabilities
- Custom header middleware: `core/security_headers_middleware.py`

### Tier 3 — Tenant Isolation Tests
- Automated suite: `core/tests/test_tenant_isolation.py`
- Verifies org boundary enforcement across:
  - passwords, assets, documents, audit logs
  - API endpoints (403/404 cross-org)
  - bulk operations
  - manager filtering and foreign key constraints

### Tier 4 — Secrets Management & Rotation
- Encryption utilities: `vault/encryption_v2.py` (vault, HKDF + AES-256-GCM), `vault/secret_fields.py` (encrypted model fields and token hashing for every other stored secret) and `vault/encryption.py` (key handling, older formats)
- Key rotation: `manage.py rotate_encryption_key` with `APP_MASTER_KEY_PREVIOUS`
- Storage audit: `manage.py check_secrets_storage`
- Log sanitization utilities: `core/secrets_management.py`

### Tier 5 — AI Endpoint Abuse Controls
- Per-user and per-org request limits + burst control
- Per-user and per-org spend caps (budget protection)
- Prompt size limits
- PII redaction (email/phone/SSN/card/key patterns) — implemented but not yet wired into the AI features
- Standard 429 response payload includes reset window info

---

## Operational Runbook

### Secrets
- Validate: `python manage.py check --deploy`, plus the encrypt/decrypt check under [Validation](#validation)
- Generate key: `python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"`
- Rotate: `python manage.py rotate_encryption_key` — see [Key Rotation](#key-rotation)
- Audit: `python manage.py check_secrets_storage`

### Tenant Boundary Verification
- Run isolation tests: `python manage.py test core.tests.test_tenant_isolation -v 2`

### Header Verification
- Validate response headers after deployment. CSP ships in report-only mode: watch the `security.csp` log, then set `CSP_REPORT_ONLY=False` to enforce

---

## Phase 2 Roadmap (Configuration Committed, Requires Activation)

### CI Security Pipeline
- ✅ Semgrep (SAST with OWASP Top 10 + Python rules)
- ✅ Gitleaks (secrets scanning)
- ✅ CodeQL (deep static analysis)
- ✅ SBOM generation (CycloneDX format)
- ✅ pip-audit (PyPI vulnerability checks)

### Supply Chain Hardening
- ✅ Manual dependency management (pip-audit + pip list --outdated)
- ✅ Pre-commit hooks (Ruff + Bandit + Gitleaks)
- ⏳ Pin GitHub Actions to commit SHAs (optional, manual)

### Database Hardening
- ⏳ Least-privilege DB users (requires manual SQL)
- ⏳ TLS to database (if remote, requires CA cert)
- ✅ Encrypted backups (`manage.py backup`); ⏳ scheduled backups and restore tests

### Attack Surface Polish
- ✅ CSP reporting endpoint (`/csp-report/`) and report-only rollout; ⏳ enforcing by default
- ⏳ Per-endpoint request body limits
- ⏳ Upload validation (MIME + magic bytes) — done for the files app and ticket attachments; not yet for document bulk upload
- ✅ API key hashing (HMAC-SHA256; only a prefix stored in plaintext)

**Activation:** CI checks run on push; the database items are manual operator steps.

