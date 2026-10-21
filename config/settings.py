"""
Django settings for Client St0r
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from django.utils.translation import gettext_lazy as _
from .version import get_version

# Load environment variables.
# override=True so the .env file is authoritative over any stale variables
# already present in the process environment. This matters for the in-app
# Settings → AI & LLM page, which writes keys to .env and reloads gunicorn:
# under Docker Compose, `env_file: .env` injects the (often empty) keys into
# the container environment at startup, and a plain load_dotenv() would NOT
# overwrite them — so a key saved via the UI would never take effect (#137).
load_dotenv(override=True)

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Version
VERSION = get_version()

# Security settings
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# SECRET_KEY must be set in production
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        # FIX: Generate unique development key instead of hardcoded value
        # This prevents accidental use of predictable key if DEBUG left True in production
        import socket
        import hashlib
        hostname = socket.gethostname()
        # Generate unique key based on hostname + base directory path
        unique_seed = f"{hostname}-{BASE_DIR}-django-dev-key"
        SECRET_KEY = 'django-insecure-' + hashlib.sha256(unique_seed.encode()).hexdigest()
    else:
        raise ValueError("SECRET_KEY environment variable must be set in production")

# ALLOWED_HOSTS - Support for multiple domains
# In DEBUG mode, allow all hosts for flexibility
# In production, use environment variable with wildcard support
if DEBUG:
    ALLOWED_HOSTS = ['*']  # Allow all hosts in development
else:
    # Production: Use env var with support for wildcards like *.example.com
    allowed_hosts_env = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1')
    ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(',') if host.strip()]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Third party
    'rest_framework',
    # Kept only for migration history (field_ops 0002 and api_mobile
    # 0001/0002 reference it; its rows are hashed into
    # api_mobile.MobileAuthToken and deleted). Nothing authenticates with it.
    'rest_framework.authtoken',
    'django_filters',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'two_factor',
    'axes',

    # Local apps
    'core.apps.CoreConfig',
    'accounts.apps.AccountsConfig',
    'vault.apps.VaultConfig',
    'assets.apps.AssetsConfig',
    'docs.apps.DocsConfig',
    'readiness.apps.ReadinessConfig',
    'files.apps.FilesConfig',
    'audit.apps.AuditConfig',
    'api.apps.ApiConfig',
    'api_mobile.apps.ApiMobileConfig',
    'integrations.apps.IntegrationsConfig',
    'monitoring.apps.MonitoringConfig',
    'processes.apps.ProcessesConfig',
    'locations.apps.LocationsConfig',
    'imports.apps.ImportsConfig',
    'reports.apps.ReportsConfig',
    'vehicles.apps.VehiclesConfig',
    'inventory.apps.InventoryConfig',
    'scheduling.apps.SchedulingConfig',
    'psa.apps.PsaConfig',
    'psa_ai.apps.PsaAiConfig',
    'portal.apps.PortalConfig',
    'resourcing.apps.ResourcingConfig',
    'crm.apps.CrmConfig',
    'security_alerts.apps.SecurityAlertsConfig',
    'compliance.apps.ComplianceConfig',
    'field_ops.apps.FieldOpsConfig',
    'statuspage.apps.StatusPageConfig',
    'netconfig.apps.NetConfigConfig',
    'network_discovery.apps.NetworkDiscoveryConfig',
]

# Optional apps - only add if installed (allows updates without dependencies).
# find_spec, not import: importing graphene_django here reads Django settings
# while this module is half-loaded, so graphene cached an empty GRAPHENE
# config and every GraphQL request failed with "A Schema is required".
from importlib.util import find_spec as _find_spec
for _optional_app in ('graphene_django', 'corsheaders'):
    if _find_spec(_optional_app) is not None:
        INSTALLED_APPS.append(_optional_app)

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.security_headers_middleware.SecurityHeadersMiddleware',  # Enhanced security headers
    'core.csp_middleware.ContentSecurityPolicyMiddleware',  # CSP header + per-request nonce
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.gzip.GZipMiddleware',  # Compress responses
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'core.csrf_middleware.MultiDomainCsrfViewMiddleware',  # Custom CSRF for multi-domain support
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.firewall_middleware.FirewallMiddleware',  # IP and GeoIP firewall (after auth for request.user)
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
    'core.middleware.CurrentOrganizationMiddleware',
    'accounts.middleware.SectionPermissionMiddleware',  # vault_view / docs_view / assets_view by URL prefix
    'accounts.middleware.SessionIdleTimeoutMiddleware',
    'accounts.middleware.Enforce2FAMiddleware',
    'accounts.middleware.UserLanguageMiddleware',
    'core.ai_abuse_control.AIAbuseControlMiddleware',  # AI endpoint protection
    'audit.middleware.AuditLoggingMiddleware',
]

# Optional middleware - only add if dependencies are installed
try:
    import corsheaders
    # Insert CORS middleware early in the stack (after WhiteNoise, before sessions)
    MIDDLEWARE.insert(2, 'corsheaders.middleware.CorsMiddleware')
except ImportError:
    pass

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.organization_context',
                'accounts.context_processors.user_theme',
                # "Help Us Grow" destinations — the support modal is in
                # base.html on every page, so no view can supply them.
                'core.context_processors.support_links',
                'core.context_processors.csp_nonce',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
# Supports both MariaDB (production) and SQLite (local testing)
DB_ENGINE = os.getenv('DB_ENGINE', 'mysql')

if DB_ENGINE == 'sqlite3':
    # SQLite for local development/testing
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    # MariaDB for production
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DB_NAME', 'itdocs'),
            'USER': os.getenv('DB_USER', 'itdocs'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '3306'),
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
                'charset': 'utf8mb4',
            },
            'CONN_MAX_AGE': 600,  # Keep connections open for 10 minutes (connection pooling)
        }
    }

# Caching - Use locmem cache (in-memory) for better compatibility
# Database cache requires running createcachetable which may not be done on all systems
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'client-st0r-cache',
        'TIMEOUT': 300,  # 5 minutes default timeout
        'OPTIONS': {
            'MAX_ENTRIES': 10000,  # Maximum number of cache entries
        }
    }
}

# Password validation & hashing
AUTH_PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    # Minimum length + special-character rule come from Settings → Security
    # (or PASSWORD_MIN_LENGTH / PASSWORD_REQUIRE_SPECIAL in the environment).
    {'NAME': 'core.security_policy.SystemPasswordPolicyValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'accounts.azure_auth.AzureADBackend',  # Azure AD SSO
    'django.contrib.auth.backends.ModelBackend',
    # LDAP / Active Directory sign-in. Optional and off by default; configured
    # in Settings -> Directory Services (core.SystemSetting), re-read on every
    # attempt. Stays after ModelBackend so local accounts (incl. a break-glass
    # superuser) never depend on the directory. Axes stays first so lockouts
    # apply to LDAP attempts too. Needs python-ldap + django-auth-ldap
    # (requirements-optional.txt); without them it is a no-op.
    'accounts.ldap_backend.ClientSt0rLDAPBackend',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'  # Eastern Time (handles EST/EDT automatically)
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('en-us', _('English (US)')),
    ('es',    _('Spanish')),
    ('fr',    _('French')),
    ('de',    _('German')),
    ('pt-br', _('Portuguese (Brazil)')),
]

LOCALE_PATHS = [BASE_DIR / 'locale']

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static_collected'
STATICFILES_DIRS = [BASE_DIR / 'static']

# WhiteNoise configuration for static file serving
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Under `manage.py test`, resolve {% static %} without the manifest.
#
# CompressedManifestStaticFilesStorage looks every static reference up in
# staticfiles.json, which is a build artefact produced by collectstatic. View
# tests render real templates, so the moment a new stylesheet is added to
# base.html the whole view suite errors with "Missing staticfiles manifest
# entry" until somebody runs collectstatic — a failure about the build state of
# the checkout, not about the code under test.
#
# Deployment is unaffected: update.sh runs collectstatic (step 4/5) and so does
# docker-entrypoint.sh, so the manifest is always regenerated before the app
# serves a request.
import sys as _sys_static
if 'test' in _sys_static.argv:
    STORAGES['staticfiles']['BACKEND'] = (
        'django.contrib.staticfiles.storage.StaticFilesStorage'
    )

# Media files (private, served via X-Accel-Redirect)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
UPLOAD_ROOT = Path(os.getenv('UPLOAD_ROOT', '/var/lib/itdocs/uploads'))

# Upload size limits (match nginx client_max_body_size)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB in memory
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB in memory
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # Allow large forms (e.g., bulk imports)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security settings
# In DEBUG mode, allow HTTP cookies (for development/testing)
# In production, enforce HTTPS
if DEBUG:
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'False').lower() == 'true'
else:
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'
    CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True').lower() == 'true'

# Security policy precedence (core/security_policy.py): an environment
# variable that is explicitly set is an operator override and wins (the UI
# shows it read-only); otherwise the value saved in Settings → Security
# applies; otherwise the built-in default. The *_ENV-derived settings below
# are None when the variable is unset.
def _env_set(name):
    return os.getenv(name, '').strip() != ''


def _env_int(name):
    return int(os.getenv(name)) if _env_set(name) else None


def _env_bool(name):
    return os.getenv(name).strip().lower() in ('1', 'true', 'yes', 'on') if _env_set(name) else None


# Maximum session length (absolute, from sign-in), enforced by
# accounts.middleware.SessionIdleTimeoutMiddleware. Default 8 h (saved setting).
SESSION_ABSOLUTE_TIMEOUT = _env_int('SESSION_COOKIE_AGE')  # seconds, or None
# Session-store lifetime: the env value when set, else a 7-day backstop (the
# UI maximum) so the store never cuts a session shorter than the policy; the
# middleware applies the real limits.
SESSION_COOKIE_AGE = SESSION_ABSOLUTE_TIMEOUT or 7 * 24 * 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = os.getenv('SESSION_EXPIRE_AT_BROWSER_CLOSE', 'True').lower() == 'true'
SESSION_IDLE_TIMEOUT = _env_int('SESSION_IDLE_TIMEOUT')  # seconds, or None → saved setting (default 60 min)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False  # Must be False so JS can read csrftoken cookie for AJAX POST requests
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_FAILURE_VIEW = 'core.csrf_failure.csrf_failure'  # friendly page; already-signed-in login resubmits continue (v3.17.624)

# CSRF Trusted Origins - Multi-domain support for HTTPS
# Required for POST requests when using HTTPS
csrf_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if csrf_origins_env:
    # Use explicit env var if provided (comma-separated full URLs)
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_origins_env.split(',') if origin.strip()]
elif DEBUG:
    # In DEBUG mode with wildcard ALLOWED_HOSTS, we need to be permissive
    # Add common development origins
    CSRF_TRUSTED_ORIGINS = [
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'https://localhost:8000',
        'https://127.0.0.1:8000',
    ]

    # Auto-detect all local IP addresses and add them to trusted origins
    import socket
    try:
        # Get hostname and primary IP
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip and local_ip != '127.0.0.1':
            CSRF_TRUSTED_ORIGINS.extend([
                f'http://{local_ip}:8000',
                f'https://{local_ip}:8000',
            ])

        # Also try to get all network interfaces
        import socket
        addrs = socket.getaddrinfo(hostname, None)
        for addr in addrs:
            ip = addr[4][0]
            if ip and ip not in ['127.0.0.1', '::1'] and ':' not in ip:  # Skip loopback and IPv6
                CSRF_TRUSTED_ORIGINS.extend([
                    f'http://{ip}:8000',
                    f'https://{ip}:8000',
                ])
    except Exception:
        pass
else:
    # In production, auto-generate from ALLOWED_HOSTS
    CSRF_TRUSTED_ORIGINS = []
    for host in ALLOWED_HOSTS:
        if host and host != '*':
            # Add both http and https for each host
            CSRF_TRUSTED_ORIGINS.append(f'https://{host}')
            CSRF_TRUSTED_ORIGINS.append(f'http://{host}')

# Security Headers - Enhanced for Production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False' if DEBUG else 'True').lower() == 'true'

# HSTS - Strict Transport Security (31536000 = 1 year in production)
# Start with shorter duration, increase to 1 year after testing
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0' if DEBUG else '31536000'))
# includeSubDomains is OPT-IN — auto-cascading would force HTTPS on every
# sibling subdomain (e.g. mail.example.com), which is rarely what an admin
# wants on first enable. Set SECURE_HSTS_INCLUDE_SUBDOMAINS=True only after
# verifying every public subdomain has a valid TLS cert.
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    SECURE_HSTS_SECONDS > 0
    and os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False').lower() == 'true'
)
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'False').lower() == 'true'  # Only enable after 1 year+ HSTS

# Proxy SSL Header (for Gunicorn behind nginx/caddy)
# Set this if you're behind a reverse proxy that terminates SSL
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if not DEBUG else None

# Referrer Policy - Don't leak URLs to external sites
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Cross-Origin-Opener-Policy (COOP) - Only enable for HTTPS
# Browsers reject this header on HTTP (non-localhost), so only set it when using HTTPS
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin' if SECURE_SSL_REDIRECT else None

# Content Security Policy — sent on every HTML response by
# core.csp_middleware.ContentSecurityPolicyMiddleware (uses Django's built-in
# nonce support; templates put nonce="{{ csp_nonce }}" on inline <script>).
#
# CSP_REPORT_ONLY (default True): send Content-Security-Policy-Report-Only so
# violations are reported/logged but nothing is blocked. Check the
# `security.csp` log, then set CSP_REPORT_ONLY=False to enforce.
# CSP_REPORT_URI: where browsers POST violation reports (logged, rate
# limited). Set to an empty string to send no report directive.
# CSP_ENABLED=False turns the header off entirely (emergency escape hatch).
from django.utils.csp import CSP as _CSP
CSP_ENABLED = os.getenv('CSP_ENABLED', 'True').lower() == 'true'
CSP_REPORT_ONLY = os.getenv('CSP_REPORT_ONLY', 'True').lower() == 'true'
CSP_REPORT_URI = os.getenv('CSP_REPORT_URI', '/csp-report/')
CSP_REPORT_RATE_LIMIT = int(os.getenv('CSP_REPORT_RATE_LIMIT', '30'))  # reports / minute / client IP
_CSP_CDNS = [
    'https://cdn.jsdelivr.net',
    'https://cdnjs.cloudflare.com',
    'https://unpkg.com',
    'https://code.jquery.com',
    'https://cdn.datatables.net',
]
CSP_POLICY = {
    'default-src': [_CSP.SELF],
    # Inline <script> blocks carry the per-request nonce; no 'unsafe-inline'.
    'script-src': [_CSP.SELF, _CSP.NONCE, *_CSP_CDNS],
    # No inline event-handler attributes: templates wire events through
    # static/js/csp-events.js (data-action, data-confirm, ...). A test fails
    # if one is added back (core/tests/test_csp.py).
    'script-src-attr': [_CSP.NONE],
    # ~90 <style> blocks, ~780 style="" attributes and library-injected styles.
    'style-src': [_CSP.SELF, _CSP.UNSAFE_INLINE, *_CSP_CDNS],
    'font-src': [_CSP.SELF, 'data:', 'https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com'],
    # https: — user-authored KB/document content and map tiles (OSM/ArcGIS)
    # embed images from arbitrary hosts.
    'img-src': [_CSP.SELF, 'data:', 'blob:', 'https:'],
    'connect-src': [_CSP.SELF, 'https://api.pwnedpasswords.com', 'https://embed.diagrams.net'],
    'frame-src': [_CSP.SELF, 'https://embed.diagrams.net'],
    'worker-src': [_CSP.SELF],
    'manifest-src': [_CSP.SELF],
    'object-src': [_CSP.NONE],
    'base-uri': [_CSP.SELF],
    'form-action': [_CSP.SELF],
    # Becomes 'self' on responses marked X-Frame-Options: SAMEORIGIN.
    'frame-ancestors': [_CSP.NONE],
}

# Additional Security Headers via Middleware
# Permissions-Policy (formerly Feature-Policy)
PERMISSIONS_POLICY = {
    'geolocation': [],  # Disable geolocation
    'microphone': [],   # Disable microphone
    'camera': [],       # Disable camera
    'payment': [],      # Disable payment API
    'usb': [],          # Disable USB
    'interest-cohort': [],  # Disable FLoC (privacy)
}

# Django Axes (brute force protection)
# Lockout values resolve per request (env override > Settings → Security >
# default) through these callables. Env: AXES_FAILURE_LIMIT (attempts),
# AXES_COOLOFF_TIME (hours, may be fractional).
LOCKOUT_FAILURE_LIMIT = _env_int('AXES_FAILURE_LIMIT')
LOCKOUT_COOLOFF_HOURS = float(os.getenv('AXES_COOLOFF_TIME')) if _env_set('AXES_COOLOFF_TIME') else None
AXES_FAILURE_LIMIT = 'core.security_policy.axes_failure_limit'
AXES_COOLOFF_TIME = 'core.security_policy.axes_cool_off'
# Replaces deprecated AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP — same behavior
# (lock out on the username+IP pair).
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_URL = '/accounts/locked/'

# Django Two-Factor Auth
TWO_FACTOR_PATCH_ADMIN = False
LOGIN_URL = 'two_factor:login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'two_factor:login'

# Custom 2FA enforcement
# None unless REQUIRE_2FA is set in the environment; then Settings → Security
# decides (default: required). See core/security_policy.py.
REQUIRE_2FA = _env_bool('REQUIRE_2FA')
PASSWORD_MIN_LENGTH = _env_int('PASSWORD_MIN_LENGTH')
PASSWORD_REQUIRE_SPECIAL = _env_bool('PASSWORD_REQUIRE_SPECIAL')

# HaveIBeenPwned Breach Checking
HIBP_ENABLED = os.getenv('HIBP_ENABLED', 'True').lower() == 'true'
HIBP_API_KEY = os.getenv('HIBP_API_KEY', '')  # Optional - increases rate limit
HIBP_CHECK_ON_SAVE = os.getenv('HIBP_CHECK_ON_SAVE', 'True').lower() == 'true'
HIBP_BLOCK_BREACHED = os.getenv('HIBP_BLOCK_BREACHED', 'False').lower() == 'true'

# Scan frequency options (in hours)
HIBP_SCAN_FREQUENCIES = [2, 4, 8, 16, 24]
HIBP_DEFAULT_SCAN_FREQUENCY = int(os.getenv('HIBP_SCAN_FREQUENCY', '24'))

# Integration Security (SSRF Protection)
# WARNING: Enabling this setting disables SSRF protection for integrations and monitoring
# Only enable if you need to connect to self-hosted services on private networks (RFC1918)
# Private IP ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
ALLOW_PRIVATE_IP_INTEGRATIONS = os.getenv('ALLOW_PRIVATE_IP_INTEGRATIONS', 'False').lower() == 'true'

# Failed checks in a row before a down alert (monitoring.down_notifications,
# locations.wan_checks). Invalid values fall back to 2 where they are read.
WEBSITE_DOWN_ALERT_THRESHOLD = os.getenv('WEBSITE_DOWN_ALERT_THRESHOLD', '2')
WAN_DOWN_ALERT_THRESHOLD = os.getenv('WAN_DOWN_ALERT_THRESHOLD', '2')

# AI and External API Configuration
# Multi-LLM Provider Support
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'anthropic')  # anthropic, moonshot, minimax, minimax_coding, openai, ollama

# Anthropic Claude
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929')

# Moonshot AI (Kimi)
MOONSHOT_API_KEY = os.getenv('MOONSHOT_API_KEY', '')
MOONSHOT_MODEL = os.getenv('MOONSHOT_MODEL', 'moonshot-v1-8k')  # moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k

# MiniMax Chat API
MINIMAX_API_KEY = os.getenv('MINIMAX_API_KEY', '')
MINIMAX_GROUP_ID = os.getenv('MINIMAX_GROUP_ID', '')
MINIMAX_MODEL = os.getenv('MINIMAX_MODEL', 'abab6.5-chat')  # abab6.5-chat, abab6.5s-chat, abab5.5-chat

# MiniMax Coding Plan API (M2.5)
MINIMAX_CODING_API_KEY = os.getenv('MINIMAX_CODING_API_KEY', '')
MINIMAX_CODING_MODEL = os.getenv('MINIMAX_CODING_MODEL', 'MiniMax-M2.5')

# OpenAI (future support)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')  # gpt-4o, gpt-4-turbo, gpt-3.5-turbo

# Ollama (on-premises, no API key required)
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')

# AI Abuse Controls (cost protection and PII redaction)
AI_MAX_PROMPT_LENGTH = int(os.getenv('AI_MAX_PROMPT_LENGTH', '10000'))  # characters
AI_MAX_DAILY_REQUESTS_PER_USER = int(os.getenv('AI_MAX_DAILY_REQUESTS_PER_USER', '100'))
AI_MAX_DAILY_REQUESTS_PER_ORG = int(os.getenv('AI_MAX_DAILY_REQUESTS_PER_ORG', '1000'))
AI_MAX_DAILY_SPEND_PER_USER = float(os.getenv('AI_MAX_DAILY_SPEND_PER_USER', '10.00'))  # USD
AI_MAX_DAILY_SPEND_PER_ORG = float(os.getenv('AI_MAX_DAILY_SPEND_PER_ORG', '100.00'))  # USD
AI_PII_REDACTION_ENABLED = os.getenv('AI_PII_REDACTION_ENABLED', 'True').lower() == 'true'

# Google Maps API for geocoding and satellite imagery
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Mapbox API (alternative to Google Maps)
MAPBOX_ACCESS_TOKEN = os.getenv('MAPBOX_ACCESS_TOKEN', '')

# Bing Maps API (alternative mapping provider)
BING_MAPS_API_KEY = os.getenv('BING_MAPS_API_KEY', '')

# Map display settings
MAP_DEFAULT_ZOOM = int(os.getenv('MAP_DEFAULT_ZOOM', '4'))  # Default zoom level for dashboard maps
MAP_DRAGGING_ENABLED = os.getenv('MAP_DRAGGING_ENABLED', 'true').lower() == 'true'  # Enable map dragging

# Property data APIs
REGRID_API_KEY = os.getenv('REGRID_API_KEY', '')  # Regrid (formerly Loveland) parcel data
ATTOM_API_KEY = os.getenv('ATTOM_API_KEY', '')    # AttomData property records

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api.authentication.APIKeyAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Anonymous (per-IP) - strict limits
        'anon': '50/hour',
        # Authenticated users - reasonable limits
        'user': '1000/hour',
        # Sensitive endpoints - much stricter
        'login': '10/hour',
        'password_reset': '5/hour',
        'token': '20/hour',
        # Mobile vault reveals — mirror the web vault's 30/hour rate.
        'vault_reveal': '30/hour',
        # AI endpoints - cost protection
        'ai_request': '100/day',
        'ai_burst': '10/minute',
    },
    # Production: Disable browsable API, use JSON-only
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ] if not DEBUG else [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    # Strict parsers
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    # Use the modern OpenAPI schema in both DEBUG and production. Setting
    # this to None makes DRF's coreapi import path call issubclass(None, ...)
    # which raises TypeError; setting to coreapi.AutoSchema would re-introduce
    # the deprecated coreapi dependency.
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.openapi.AutoSchema',
}

# Encryption settings
APP_MASTER_KEY = os.getenv('APP_MASTER_KEY', '')
if not APP_MASTER_KEY and not DEBUG:
    raise ValueError("APP_MASTER_KEY must be set in production")
# Key rotation: previous master key(s), comma-separated. Decryption tries
# APP_MASTER_KEY first, then these; new ciphertext always uses APP_MASTER_KEY.
# Set this to the old key while `manage.py rotate_encryption_key` re-encrypts,
# then remove it.
APP_MASTER_KEY_PREVIOUS = os.getenv('APP_MASTER_KEY_PREVIOUS', '')

# API Key settings - must be separate from SECRET_KEY for security
API_KEY_SECRET = os.getenv('API_KEY_SECRET')
if not API_KEY_SECRET:
    if DEBUG:
        # FIX: Generate completely independent key using different seed
        # Do NOT derive from SECRET_KEY - use separate entropy source
        import hashlib
        import socket
        hostname = socket.gethostname()
        # Use different seed than SECRET_KEY for key separation
        unique_seed = f"api-key-secret-{hostname}-{BASE_DIR}"
        API_KEY_SECRET = hashlib.sha256(unique_seed.encode()).hexdigest()
    else:
        raise ValueError("API_KEY_SECRET environment variable must be set in production (must differ from SECRET_KEY)")

# Emergency restart webhook (POST /emergency-restart/). Disabled unless set.
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
EMERGENCY_RESTART_SECRET = os.getenv('EMERGENCY_RESTART_SECRET', '')

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': '/var/log/itdocs/django.log',
            'formatter': 'verbose',
        },
        'vault_file': {
            'class': 'logging.FileHandler',
            'filename': '/var/log/itdocs/vault.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'integrations': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'vault': {
            'handlers': ['console', 'vault_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'security.csp': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Create log directory if it doesn't exist
if not DEBUG:
    log_dir = Path('/var/log/itdocs')
    log_dir.mkdir(parents=True, exist_ok=True)

# Auto-Update Settings
GITHUB_REPO_OWNER = os.getenv('GITHUB_REPO_OWNER', 'agit8or1')
GITHUB_REPO_NAME = os.getenv('GITHUB_REPO_NAME', 'clientst0r')
AUTO_UPDATE_ENABLED = os.getenv('AUTO_UPDATE_ENABLED', 'True').lower() == 'true'
AUTO_UPDATE_CHECK_INTERVAL = int(os.getenv('AUTO_UPDATE_CHECK_INTERVAL', '21600'))  # 6 hours in seconds (reduced API calls)

# GraphQL Configuration
GRAPHENE = {
    'SCHEMA': 'api.graphql.schema.schema',
    # DjangoDebugMiddleware records every SQL query for the response; only
    # useful (and only safe) in development.
    'MIDDLEWARE': [
        'graphene_django.debug.DjangoDebugMiddleware',
    ] if DEBUG else [],
}

# CORS Configuration for GraphQL API
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:19006",  # Expo default
    "http://localhost:8081",   # React Native default
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# ---------------------------------------------------------------------------
# PSA email-to-ticket — Phase 10.2 attachment ingestion limits.
# Override per-deployment via env or local settings if needed.
# ---------------------------------------------------------------------------
PSA_EMAIL_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024  # 25 MB
PSA_EMAIL_ATTACHMENT_MIME_ALLOWLIST = [
    # Images
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml',
    # PDFs
    'application/pdf',
    # Plain text + structured text
    'text/plain', 'text/csv', 'text/html', 'text/markdown',
    # Office documents
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    # Archives commonly seen with logs / screenshots
    'application/zip',
]


# ---------------------------------------------------------------------------
# Local-only app loader (v3.17.432).
# Auto-discovers Django apps in `<BASE_DIR>/local_apps/<name>/` and adds
# them to INSTALLED_APPS. Used for environment-specific extensions that
# don't belong in the public repo (custom auth backends, internal-only
# dashboards, etc.).
#
# Drop a Django app at `local_apps/<name>/` with the standard layout
# (apps.py, urls.py, etc.) and it will be picked up automatically on
# next gunicorn restart. The directory itself is gitignored via
# `.git/info/exclude`. Nothing here is loaded if the directory doesn't
# exist — safe default for fresh clones.
# ---------------------------------------------------------------------------
import sys as _sys
_LOCAL_APPS_DIR = BASE_DIR / 'local_apps'
if _LOCAL_APPS_DIR.is_dir():
    _local_apps_path = str(_LOCAL_APPS_DIR)
    if _local_apps_path not in _sys.path:
        _sys.path.insert(0, _local_apps_path)
    for _entry in sorted(_LOCAL_APPS_DIR.iterdir()):
        if _entry.is_dir() and (_entry / 'apps.py').exists() \
                and not _entry.name.startswith(('_', '.')):
            INSTALLED_APPS.append(_entry.name)


# ---------------------------------------------------------------------------
# Mobile beta-tester signup wiring (v3.17.485 / locked v3.17.488)
# ---------------------------------------------------------------------------
# BETA_ADMIN_EMAIL — where signup notifications go. Env-overridable so
# a fork can route to its own ops address, but the default is the
# canonical Client St0r maintainer so any unconfigured install still
# delivers signups to a person who can act on them.
BETA_ADMIN_EMAIL = os.getenv('BETA_ADMIN_EMAIL', 'agit8or@agit8or.net')

# Play Console listing URLs — HARD-CODED to the canonical agit8or1
# Client St0r Android listing. There is exactly one Android app to
# beta-test, regardless of how many self-hosted Client St0r servers
# point users at it. Forks should not change these — a user on any
# install signs up here for THIS Play app.
PLAY_OPEN_TEST_URL = 'https://play.google.com/apps/testing/com.clientstor.mspreboot'
PLAY_INTERNAL_TEST_URL = 'https://play.google.com/apps/internaltest/4701536670067601320'

# v3.17.488 — upstream forwarding.
# When a user submits the beta-signup form on a remote install of
# Client St0r, the view (a) saves a local row for the operator's
# records, and (b) best-effort POSTs the same payload to this URL so
# the signup also lands on the canonical agit8or1 server (the one
# whose Play Console listing is being signed up for).
# The canonical install MUST set BETA_UPSTREAM_URL='' in its .env to
# avoid forwarding to itself — see /home/administrator/.env for the
# operator setting.
BETA_UPSTREAM_URL = os.getenv(
    'BETA_UPSTREAM_URL',
    'https://huduglue.agit8or.net/core/beta-test/upstream/',
)

# Only these reverse-proxy peers may supply a forwarding chain. Add the exact
# proxy CIDR when running behind a separate container or load balancer.
TRUSTED_PROXY_CIDRS = [value.strip() for value in os.getenv(
    'TRUSTED_PROXY_CIDRS', '127.0.0.1/32,::1/128').split(',') if value.strip()]
