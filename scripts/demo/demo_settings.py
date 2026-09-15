"""Settings for the isolated demo instance used to produce documentation media.

This module exists so screenshots and the walkthrough video can be captured
against a real, running ClientSt0r without touching anything real:

* the database is a throwaway SQLite file under ``DEMO_DIR``;
* media and static roots live under ``DEMO_DIR`` too, so ``collectstatic``
  never writes into the deployed tree;
* 2FA enforcement, the lockout backend and the IP firewall are dropped, because
  a headless browser has no second factor and no stable source address;
* templates load uncached so template edits show up without a restart.

It is never imported by the application at runtime — nothing in ``config/`` or
any app references it. Use it explicitly:

    export DEMO_DIR=/var/tmp/clientst0r-demo
    export PYTHONPATH=scripts/demo:.
    python manage.py migrate --settings=demo_settings

See scripts/demo/README.md.
"""
import os
from pathlib import Path

from config.settings import *  # noqa: F401,F403

DEMO_DIR = Path(os.environ['DEMO_DIR'])
DEMO_DIR.mkdir(parents=True, exist_ok=True)

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# Not a secret: this instance holds only invented data and is never exposed.
SECRET_KEY = 'demo-media-capture-key-not-used-anywhere-else'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(DEMO_DIR / 'demo.sqlite3'),
        'OPTIONS': {'timeout': 30},
    }
}

MEDIA_ROOT = str(DEMO_DIR / 'media')
STATIC_ROOT = str(DEMO_DIR / 'static')

# Serve static straight from the source tree: the hashed manifest is read once
# at startup, so a CSS edit would otherwise need a restart to appear.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_CROSS_ORIGIN_OPENER_POLICY = None
CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:8099', 'http://localhost:8099']

_DROP_MIDDLEWARE = {
    'accounts.middleware.Enforce2FAMiddleware',
    'axes.middleware.AxesMiddleware',
    'core.firewall_middleware.FirewallMiddleware',
}
MIDDLEWARE = [m for m in MIDDLEWARE if m not in _DROP_MIDDLEWARE]  # noqa: F405

AUTHENTICATION_BACKENDS = [
    b for b in AUTHENTICATION_BACKENDS if 'axes' not in b.lower()  # noqa: F405
] or ['django.contrib.auth.backends.ModelBackend']

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Uncached template loading, so iterating on a template does not need a restart.
for _tpl in TEMPLATES:  # noqa: F405
    if _tpl['BACKEND'].endswith('DjangoTemplates'):
        _tpl['APP_DIRS'] = False
        _tpl['OPTIONS'] = dict(_tpl.get('OPTIONS', {}))
        _tpl['OPTIONS']['loaders'] = [
            'django.template.loaders.filesystem.Loader',
            'django.template.loaders.app_directories.Loader',
        ]

# Nothing in this instance may reach the outside world.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
