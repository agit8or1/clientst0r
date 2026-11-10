"""Settings for the cross-peer end-to-end run: a real ClientSt0r on its own
throwaway SQLite database next to a real Rem0te (scripts/e2e/cross_peer/run.py).

Like scripts/demo/demo_settings.py, it never reads the deployment's .env and
holds only synthetic data. Never imported by the application. Use it
explicitly:

    E2E_DIR=/tmp/cs-e2e PYTHONPATH=scripts/e2e/cross_peer:. \
        python manage.py migrate --settings=settings_e2e
"""
import os
from pathlib import Path

# config.settings calls load_dotenv(); neutralise it so the deployment's .env
# (database, encryption key, provider keys) is never read.
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
for _name in [n for n in os.environ if n.startswith(('DB_', 'ANTHROPIC_', 'OPENAI_', 'MINIMAX_',
                                                      'MOONSHOT_', 'OLLAMA_', 'HIBP_'))]:
    del os.environ[_name]
os.environ['DEBUG'] = 'False'
# Not secrets: this instance holds only synthetic data and is never exposed.
os.environ['SECRET_KEY'] = 'cross-peer-e2e-key-not-used-anywhere-else'
os.environ['API_KEY_SECRET'] = 'cross-peer-e2e-api-key-secret-not-used-elsewhere'
os.environ['APP_MASTER_KEY'] = 'Y3Jvc3MtcGVlci1lMmUtb25seS1rZXktMzJieXRlcyE='  # 32 bytes
os.environ.pop('APP_MASTER_KEY_PREVIOUS', None)

from config.settings import *  # noqa: F401,F403,E402

E2E_DIR = Path(os.environ['E2E_DIR'])
E2E_DIR.mkdir(parents=True, exist_ok=True)

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
SECRET_KEY = 'cross-peer-e2e-key-not-used-anywhere-else'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(E2E_DIR / 'clientst0r.sqlite3'),
        'OPTIONS': {'timeout': 60},
    }
}
MEDIA_ROOT = str(E2E_DIR / 'media')
STATIC_ROOT = str(E2E_DIR / 'static')
UPLOAD_ROOT = E2E_DIR / 'uploads'
AI_GATEWAY_KEY_DIR = str(E2E_DIR / 'aigw')
AI_GATEWAY_MODE = 'in_process'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'integrations.rem0te': {'level': 'INFO'}},
}
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
WHITENOISE_USE_FINDERS = True

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

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
RATELIMIT_ENABLE = False

# Rem0te, the LLM stub and this instance all live on loopback.
ALLOW_PRIVATE_IP_INTEGRATIONS = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
