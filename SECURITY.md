# HuduGlue Security Documentation

## Overview

HuduGlue implements defense-in-depth security with multiple layers of protection based on OWASP best practices, Django security guidelines, and enterprise SaaS security requirements.

**Version:** 2.20.0
**Last Updated:** 2026-01-14
**Architecture:** Django 6.0.1 + DRF + Gunicorn + MariaDB + Anthropic AI

---

## Table of Contents

1. [Security Features](#security-features)
2. [Production Security Checklist](#production-security-checklist)
3. [Environment Configuration](#environment-configuration)
4. [Tenant Isolation](#tenant-isolation)
5. [API Security](#api-security)
6. [AI Endpoint Protection](#ai-endpoint-protection)
7. [Secrets Management](#secrets-management)
8. [Security Headers](#security-headers)
9. [Rate Limiting & Throttling](#rate-limiting--throttling)
10. [Authentication & Authorization](#authentication--authorization)
11. [Monitoring & Auditing](#monitoring--auditing)
12. [Incident Response](#incident-response)
13. [Phase 2: Advanced Security](#phase-2-advanced-security)

---

## Security Features

### ✅ Implemented Security Controls (v2.20.0)

#### Authentication & Authorization
- **Password Hashing**: Argon2 (OWASP recommended, resists GPU attacks)
- **2FA**: Mandatory TOTP via django-otp (Google Authenticator, Authy, etc.)
- **SSO**: Azure AD / Microsoft Entra ID OAuth integration
- **Brute Force Protection**: django-axes (5 attempts, 1-hour lockout)
- **Multi-Tenancy**: Organization-based with automated isolation tests
- **Session Management**: Secure cookies with HttpOnly, Secure, SameSite=Lax

#### Data Protection
- **Encryption**: AES-256-GCM via Fernet for all secrets
- **Key Derivation**: PBKDF2-SHA256 with 100,000 iterations
- **Encrypted Fields**: Passwords, API keys, OAuth tokens, credentials
- **Key Rotation**: Automated utilities for re-encrypting all secrets
- **Separate Keys**: Different keys per environment (dev/staging/prod)

#### API Security (DRF)
- **Production Mode**: Browsable API disabled, JSON-only renderers
- **Throttling**: 6 granular scopes (anon, user, login, password_reset, token, AI)
- **Authentication**: API key + session-based
- **Permissions**: IsAuthenticated by default
- **Schema/Docs**: Require authentication

#### Web Security
- **CSP**: Strict Content Security Policy with 10+ directives
- **HSTS**: 1-year max-age (31536000 seconds) in production
- **Clickjacking**: X-Frame-Options: DENY
- **MIME Sniffing**: X-Content-Type-Options: nosniff
- **Referrer Policy**: strict-origin-when-cross-origin
- **Permissions-Policy**: Disables geolocation, camera, microphone, payment, USB, FLoC
- **CSRF**: Multi-domain support with trusted origins
- **XSS Protection**: CSP + secure cookies + template escaping

#### AI Protection (Anthropic)
- **Request Limits**: Per-user (100/day) and per-org (1000/day)
- **Spend Caps**: Per-user ($10/day) and per-org ($100/day)
- **Burst Protection**: 10 requests/minute
- **Size Limits**: 10,000 characters per prompt
- **PII Redaction**: Emails, phones, SSNs, credit cards, API keys
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
REQUIRE_2FA=True

# ===== ALLOWED HOSTS =====
ALLOWED_HOSTS=huduglue.example.com,www.huduglue.example.com
CSRF_TRUSTED_ORIGINS=https://huduglue.example.com,https://www.huduglue.example.com

# ===== AI LIMITS =====
AI_MAX_DAILY_REQUESTS_PER_USER=100
AI_MAX_DAILY_REQUESTS_PER_ORG=1000
AI_MAX_DAILY_SPEND_PER_USER=10.00
AI_MAX_DAILY_SPEND_PER_ORG=100.00

# ===== BRUTE FORCE PROTECTION =====
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_TIME=1
```

#### 2. Generate Secrets
```bash
# SECRET_KEY (Django)
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# APP_MASTER_KEY (encryption)
python manage.py secrets generate-key

# API_KEY_SECRET (must differ from SECRET_KEY)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### 3. Validate Configuration
```bash
# Check all secrets are configured correctly
python manage.py secrets validate

# Expected output: "All secrets configured correctly"
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
- [ ] All users have 2FA enabled (enforce via REQUIRE_2FA=True)
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
- `Content-Security-Policy: default-src 'self'; ...`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=(), ...`

#### 2. CSP Validation
- Open browser DevTools → Console
- No CSP violations should appear
- If violations occur, adjust CSP in settings.py

#### 3. SSL/TLS Configuration
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
ALLOWED_HOSTS=huduglue.example.com
CSRF_TRUSTED_ORIGINS=https://huduglue.example.com

# ========================================
# DATABASE (MariaDB)
# ========================================
DB_ENGINE=mysql
DB_NAME=huduglue
DB_USER=huduglue_user
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
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_TIME=1  # hours

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

HuduGlue uses **single-database multi-tenancy** with `organization_id` filtering:

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

✅ **Enforced By**:
- Database-level filtering (OrganizationManager)
- View-level permissions (organization check)
- API-level filtering (DRF permissions)
- Automated test suite (11 test cases)

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

api_key = APIKey.objects.create(
    user=request.user,
    name='My API Key',
    organization=request.organization
)
print(f'Key: {api_key.key}')  # Only shown once

# Use API key
curl -H "Authorization: Api-Key YOUR_KEY_HERE" https://api.example.com/passwords/
```

**Security Notes:**
- API keys signed with `API_KEY_SECRET` (separate from `SECRET_KEY`)
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
Environment Variable
    ↓
APP_MASTER_KEY (plaintext in env)
    ↓
PBKDF2-SHA256 (100,000 iterations)
    ↓
Derived 32-byte Key
    ↓
Fernet Cipher (AES-256-GCM)
    ↓
Encrypted Secrets (database)
```

### What Gets Encrypted

- ✅ Vault passwords (vault.Password.encrypted_password)
- ✅ PSA connection credentials (integrations.PSAConnection.encrypted_credentials)
- ✅ RMM connection credentials (integrations.RMMConnection.encrypted_credentials)
- ✅ OAuth tokens (stored in credentials JSON)
- ✅ API keys from external services (stored in credentials JSON)
- ✅ Webhook secrets (if configured)

### Key Generation

```bash
# Generate new master key
python manage.py secrets generate-key

# Output: Base64-encoded 256-bit key
# Example: gAAAAABhkj3KLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz123456=

# Set as environment variable
export APP_MASTER_KEY='gAAAAABhkj3...'
```

### Key Rotation

**When to Rotate:**
- Annually (scheduled maintenance)
- After suspected key compromise
- When employee with key access leaves
- After security incident

**How to Rotate:**

```bash
# Step 1: Generate new key
NEW_KEY=$(python manage.py secrets generate-key)
echo "New key: $NEW_KEY"

# Step 2: Rotate all secrets (re-encrypt with new key)
python manage.py secrets rotate \
    --old-key "$APP_MASTER_KEY" \
    --new-key "$NEW_KEY"

# Output:
# Rotating secrets...
# Rotation complete: 156 secrets updated
# PSAConnections: 12 updated
# RMMConnections: 8 updated
# Passwords: 136 updated

# Step 3: Update environment variable
export APP_MASTER_KEY="$NEW_KEY"

# Step 4: Update .env file or secret manager
echo "APP_MASTER_KEY=$NEW_KEY" >> .env.prod

# Step 5: Restart application
systemctl restart huduglue-gunicorn

# Step 6: Verify
python manage.py secrets validate
# Output: All secrets configured correctly
```

### Validation

```bash
# Check configuration
python manage.py secrets validate

# Checks:
# ✓ APP_MASTER_KEY is set
# ✓ APP_MASTER_KEY can encrypt/decrypt
# ✓ API_KEY_SECRET is set and differs from SECRET_KEY
# ✓ SECRET_KEY is not using insecure default
# ✓ ANTHROPIC_API_KEY is set (if using AI)

# Example output (healthy):
All secrets configured correctly

# Example output (errors):
Validation failed:
  - APP_MASTER_KEY not set in production
  - SECRET_KEY and API_KEY_SECRET must be different
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

**Configuration:**
```python
# config/settings.py
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net")
CSP_FONT_SRC = ("'self'", "data:", "cdn.jsdelivr.net")
CSP_FRAME_SRC = ("'self'", "https://embed.diagrams.net")
CSP_FRAME_ANCESTORS = ("'none'",)  # Clickjacking protection
CSP_CONNECT_SRC = ("'self'", "https://embed.diagrams.net")
CSP_IMG_SRC = ("'self'", "data:", "https://api.qrserver.com")
CSP_OBJECT_SRC = ("'none'",)  # Block plugins
CSP_BASE_URI = ("'self'",)
CSP_FORM_ACTION = ("'self'",)
CSP_UPGRADE_INSECURE_REQUESTS = True  # Upgrade HTTP → HTTPS
```

**Response Header:**
```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; ...
```

**Future Improvement (Remove unsafe-inline):**
```python
# Use nonces for inline scripts
CSP_SCRIPT_SRC = ("'self'", "'nonce-{nonce}'", "cdn.jsdelivr.net")

# In template:
<script nonce="{{ request.csp_nonce }}">
    // Inline JS
</script>
```

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

```python
# config/settings.py
AXES_FAILURE_LIMIT = 5  # Lock after 5 failed attempts
AXES_COOLOFF_TIME = 1   # Lock for 1 hour
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_RESET_ON_SUCCESS = True
```

**How It Works:**
- Tracks failed login attempts per username + IP combo
- Locks account for 1 hour after 5 failures
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
- ✅ Minimum 12 characters
- ✅ Not similar to username/email/first name/last name
- ✅ Not in common password list (10,000+ passwords)
- ✅ Not entirely numeric
- ✅ Argon2 hashing (OWASP recommended)

### 2FA (Two-Factor Authentication)

**Configuration:**
```python
REQUIRE_2FA = True  # Enforce for all users
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
- Rate-limited via DRF throttles
- Audit logged
- Named (e.g., "Mobile App", "CI/CD")

**Generate:**
```python
from api.models import APIKey

api_key = APIKey.objects.create(
    user=request.user,
    name='My App',
    organization=request.organization
)
print(f'Key: {api_key.key}')  # Only shown once, hash stored
```

**Use:**
```bash
curl -H "Authorization: Api-Key YOUR_KEY_HERE" \
    https://api.example.com/passwords/
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
AZURE_AD_REDIRECT_URI=https://huduglue.example.com/accounts/azure/callback/
AZURE_AD_AUTO_CREATE_USERS=True  # Auto-create on first login
```

**Flow:**
1. User clicks "Login with Microsoft"
2. Redirects to Azure AD
3. User authenticates with Microsoft
4. Callback to HuduGlue with OAuth code
5. Exchange code for access token
6. Fetch user info from Microsoft Graph API
7. Create/update user in HuduGlue
8. Log in user

**Security:**
- OAuth 2.0 / OpenID Connect
- No passwords stored in HuduGlue
- Updates user info on each login
- Audit logged

---

## Monitoring & Auditing

### Audit Logging

**What Gets Logged:**
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
# Django admin → Settings → Snyk
SNYK_API_TOKEN=<your-snyk-token>
SNYK_ENABLED=True
SNYK_SCAN_SCHEDULE='daily'
```

**What Gets Scanned:**
- Python dependencies (requirements.txt)
- JavaScript dependencies (package.json)
- Docker images (if using Docker)

**Scan Process:**
1. Runs `snyk test` on codebase
2. Parses JSON output
3. Stores results in database
4. Shows in Security Dashboard
5. Tracks trends over time

**Dashboard:**
- Total vulnerabilities
- By severity (critical, high, medium, low)
- Trend analysis (up/down/stable)
- Recent scan history
- Remediation advice

**Run Scan:**
```bash
# Manual scan
python manage.py run_snyk_scan

# Or via UI
# Admin → Settings → Snyk → Run Scan
```

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
# /etc/logrotate.d/huduglue
/var/log/itdocs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 www-data www-data
    sharedscripts
    postrotate
        systemctl reload huduglue-gunicorn
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
fail2ban-client set huduglue banip <attacker-ip>
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
# Rotate encryption key
python manage.py secrets rotate --old-key $OLD --new-key $NEW

# Update environment variable
export APP_MASTER_KEY=$NEW_KEY

# Restart
systemctl restart huduglue-gunicorn
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
mysql -u root -p huduglue < backup_2026-01-14.sql

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
- [DRF Security](https://www.django-rest-framework.org/topics/security/)
- [CSP Reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- [HSTS Preload](https://hstspreload.org/)
- [Security Headers](https://securityheaders.com/)
- [SSL Labs](https://www.ssllabs.com/ssltest/)

---

**Last Updated:** 2026-01-14
**Version:** 2.20.0
**Maintainer:** HuduGlue Security Team

---

## Implemented Controls (v2.20.0)

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
- CSP hardening: frame-ancestors 'none', object-src 'none', base-uri 'self', form-action 'self'
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
- Centralized encryption/decryption utilities: `core/secrets_management.py`
- Key derivation: PBKDF2-SHA256
- Rotation command re-encrypts all encrypted fields:
  - vault passwords, PSA/RMM credentials, encrypted fields
- Log sanitization utilities included

### Tier 5 — AI Endpoint Abuse Controls
- Per-user and per-org request limits + burst control
- Per-user and per-org spend caps (budget protection)
- Prompt size limits
- PII redaction (email/phone/SSN/card/key patterns)
- Standard 429 response payload includes reset window info

---

## Operational Runbook

### Secrets
- Validate: `python manage.py secrets validate`
- Generate key: `python manage.py secrets generate-key`
- Rotate: `python manage.py secrets rotate --old-key ... --new-key ...`

### Tenant Boundary Verification
- Run isolation tests: `python manage.py test core.tests.test_tenant_isolation -v 2`

### Header Verification
- Validate response headers and CSP after deployment (CSP changes require careful rollout)

---

## Phase 2 Roadmap (Configuration Committed, Requires Activation)

**See:** `docs/PHASE2_SECURITY.md` for full implementation guide

### CI Security Pipeline
- ✅ Semgrep (SAST with OWASP Top 10 + Python rules)
- ✅ Gitleaks (secrets scanning)
- ✅ CodeQL (deep static analysis)
- ✅ SBOM generation (CycloneDX format)
- ✅ pip-audit (PyPI vulnerability checks)

### Supply Chain Hardening
- ✅ Dependabot configured (weekly Python + Actions updates)
- ✅ Pre-commit hooks (Ruff + Bandit + Gitleaks)
- ⏳ Pin GitHub Actions to commit SHAs (optional, manual)

### Database Hardening
- ⏳ Least-privilege DB users (requires manual SQL)
- ⏳ TLS to database (if remote, requires CA cert)
- ⏳ Encrypted backups + restore tests (ops task)

### Attack Surface Polish
- ⏳ CSP reporting endpoint (Report-Only rollout)
- ⏳ Per-endpoint request body limits
- ⏳ Upload validation (MIME + magic bytes)
- ⏳ API key hashing (store only hashed keys)

**Activation:** Most Phase 2 features activate automatically on next push. See Phase 2 docs for manual steps.

