"""
Django settings for HuduGlue
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from .version import get_version

# Load environment variables
load_dotenv()

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
        SECRET_KEY = 'django-insecure-dev-key-not-for-production'
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
    'files.apps.FilesConfig',
    'audit.apps.AuditConfig',
    'api.apps.ApiConfig',
    'integrations.apps.IntegrationsConfig',
    'monitoring.apps.MonitoringConfig',
    'processes.apps.ProcessesConfig',
    'locations.apps.LocationsConfig',
    'imports.apps.ImportsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.security_headers_middleware.SecurityHeadersMiddleware',  # Enhanced security headers
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'core.csrf_middleware.MultiDomainCsrfViewMiddleware',  # Custom CSRF for multi-domain support
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
    'core.middleware.CurrentOrganizationMiddleware',
    'accounts.middleware.Enforce2FAMiddleware',
    'core.ai_abuse_control.AIAbuseControlMiddleware',  # AI endpoint protection
    'audit.middleware.AuditLoggingMiddleware',
]

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
        }
    }

# Password validation & hashing
AUTH_PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'accounts.azure_auth.AzureADBackend',  # Azure AD SSO
    'django.contrib.auth.backends.ModelBackend',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'  # Eastern Time (handles EST/EDT automatically)
USE_I18N = True
USE_TZ = True

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

# Media files (private, served via X-Accel-Redirect)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
UPLOAD_ROOT = Path(os.getenv('UPLOAD_ROOT', '/var/lib/itdocs/uploads'))

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

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

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
    except:
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
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'False').lower() == 'true'  # Only enable after 1 year+ HSTS

# Proxy SSL Header (for Gunicorn behind nginx/caddy)
# Set this if you're behind a reverse proxy that terminates SSL
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if not DEBUG else None

# Referrer Policy - Don't leak URLs to external sites
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Content Security Policy - Stricter (use django-csp for full control)
# NOTE: unsafe-inline is required for some Django admin and DRF browsable API features
# In production with JSON-only API, you can remove unsafe-inline
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "https://cdn.jsdelivr.net")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "https://cdn.jsdelivr.net")
CSP_FONT_SRC = ("'self'", "data:", "cdn.jsdelivr.net", "https://cdn.jsdelivr.net")
CSP_FRAME_SRC = ("'self'", "https://embed.diagrams.net", "https://*.diagrams.net")
CSP_FRAME_ANCESTORS = ("'none'",)  # Clickjacking protection
CSP_CONNECT_SRC = ("'self'", "https://embed.diagrams.net", "https://*.diagrams.net")
CSP_IMG_SRC = ("'self'", "data:", "https://embed.diagrams.net", "https://*.diagrams.net", "https://api.qrserver.com")
CSP_OBJECT_SRC = ("'none'",)  # Block plugins
CSP_BASE_URI = ("'self'",)  # Restrict base tag
CSP_FORM_ACTION = ("'self'",)  # Restrict form submissions
CSP_UPGRADE_INSECURE_REQUESTS = not DEBUG  # Upgrade HTTP to HTTPS in production

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
AXES_FAILURE_LIMIT = int(os.getenv('AXES_FAILURE_LIMIT', '5'))
AXES_COOLOFF_TIME = int(os.getenv('AXES_COOLOFF_TIME', '1'))  # hours
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_RESET_ON_SUCCESS = True

# Django Two-Factor Auth
TWO_FACTOR_PATCH_ADMIN = False
LOGIN_URL = 'two_factor:login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'two_factor:login'

# Custom 2FA enforcement
REQUIRE_2FA = os.getenv('REQUIRE_2FA', 'True').lower() == 'true'

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

# AI and External API Configuration
# Claude AI (Anthropic) for floor plan generation
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929')

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
    # Disable schema generation in production (not needed without browsable API)
    # In dev, use OpenAPI schema (modern, no coreapi dependency)
    'DEFAULT_SCHEMA_CLASS': None if not DEBUG else 'rest_framework.schemas.openapi.AutoSchema',
}

# Encryption settings
APP_MASTER_KEY = os.getenv('APP_MASTER_KEY', '')
if not APP_MASTER_KEY and not DEBUG:
    raise ValueError("APP_MASTER_KEY must be set in production")

# API Key settings - must be separate from SECRET_KEY for security
API_KEY_SECRET = os.getenv('API_KEY_SECRET')
if not API_KEY_SECRET:
    if DEBUG:
        # In development, generate a separate key from SECRET_KEY
        import hashlib
        API_KEY_SECRET = hashlib.sha256(f"{SECRET_KEY}-api-keys".encode()).hexdigest()
    else:
        raise ValueError("API_KEY_SECRET environment variable must be set in production (must differ from SECRET_KEY)")

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
    },
}

# Create log directory if it doesn't exist
if not DEBUG:
    log_dir = Path('/var/log/itdocs')
    log_dir.mkdir(parents=True, exist_ok=True)

# Auto-Update Settings
GITHUB_REPO_OWNER = os.getenv('GITHUB_REPO_OWNER', 'agit8or1')
GITHUB_REPO_NAME = os.getenv('GITHUB_REPO_NAME', 'huduglue')
AUTO_UPDATE_ENABLED = os.getenv('AUTO_UPDATE_ENABLED', 'True').lower() == 'true'
AUTO_UPDATE_CHECK_INTERVAL = int(os.getenv('AUTO_UPDATE_CHECK_INTERVAL', '3600'))  # 1 hour in seconds
