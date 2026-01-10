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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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
    'django.contrib.auth.backends.ModelBackend',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
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
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True').lower() == 'true'
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# CSRF Trusted Origins - Multi-domain support for HTTPS
# Required for POST requests when using HTTPS
csrf_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if csrf_origins_env:
    # Use explicit env var if provided (comma-separated full URLs)
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_origins_env.split(',') if origin.strip()]
elif DEBUG:
    # In DEBUG mode with wildcard ALLOWED_HOSTS, we need a workaround
    # Get the actual request origin dynamically in middleware
    # For now, add common development origins
    CSRF_TRUSTED_ORIGINS = [
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'https://localhost:8000',
        'https://127.0.0.1:8000',
    ]
    # Add wildcard support for any HTTPS origin in DEBUG mode
    # Django doesn't support wildcards, so we'll need to handle this dynamically
else:
    # In production, auto-generate from ALLOWED_HOSTS
    CSRF_TRUSTED_ORIGINS = []
    for host in ALLOWED_HOSTS:
        if host and host != '*':
            # Add both http and https for each host
            CSRF_TRUSTED_ORIGINS.append(f'https://{host}')
            CSRF_TRUSTED_ORIGINS.append(f'http://{host}')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'False').lower() == 'true'
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

# Content Security Policy (basic)
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net")

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
        'anon': '100/hour',
        'user': '1000/hour',
    },
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
