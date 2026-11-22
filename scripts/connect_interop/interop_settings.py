"""Settings for ONE throwaway installation of the Connect interoperability
harness (scripts/connect_interop/run.py). Never imported by the application.

Everything lives under INTEROP_DIR (a per-run temp directory): its own SQLite
database, media, static, logs, key and runtime directories. The deployment's
.env is never read (load_dotenv is neutralised before config.settings is
imported, like scripts/demo/demo_settings.py) and the secrets are per-run
values passed by the harness.

Differences from production settings, and why:
  * 2FA enforcement on sign-in, the lockout backend and the site IP/GeoIP
    firewall are dropped (as in the demo instance): the harness signs in
    with a password and drives pages with requests sessions. Administrator
    RE-AUTHENTICATION (password + authenticator code) for Connect approvals
    stays: each administrator has a confirmed TOTP device.
  * TRUSTED_PROXY_CIDRS is empty: no peer may supply X-Forwarded-For.
  * netshim.install(): simulated private addresses on 127.0.0.1 (see netshim).
"""
import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
for _name in [n for n in os.environ if n.startswith(('DB_', 'ANTHROPIC_', 'OPENAI_', 'MINIMAX_', 'MOONSHOT_',
                                                      'OLLAMA_', 'HIBP_', 'AGIT8OR_', 'TRUSTED_PROXY'))]:
    del os.environ[_name]
INTEROP_DIR = Path(os.environ['INTEROP_DIR'])
for _sub in ('logs', 'media', 'static', 'uploads', 'runtime', 'ai-gateway', 'backups'):
    (INTEROP_DIR / _sub).mkdir(parents=True, exist_ok=True)
os.environ['DEBUG'] = 'False'
os.environ['SECRET_KEY'] = os.environ['INTEROP_SECRET_KEY']
os.environ['API_KEY_SECRET'] = os.environ['INTEROP_SECRET_KEY'] + '-api'
os.environ['APP_MASTER_KEY'] = os.environ['INTEROP_MASTER_KEY']
os.environ.pop('APP_MASTER_KEY_PREVIOUS', None)
os.environ['ITDOCS_LOG_DIR'] = str(INTEROP_DIR / 'logs')
os.environ['CLIENTST0R_BACKUP_DIR'] = str(INTEROP_DIR / 'backups')
os.environ['DB_ENGINE'] = 'sqlite3'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netshim  # noqa: E402

netshim.install()

from config.settings import *  # noqa: F401,F403,E402

DEBUG = False
SECRET_KEY = os.environ['INTEROP_SECRET_KEY']
_PUBLIC = os.environ['INTEROP_PUBLIC_URL']          # https://a.interop.test:PORT
_HOST = _PUBLIC.split('://', 1)[1].split(':')[0]
ALLOWED_HOSTS = [_HOST, '127.0.0.1']
CSRF_TRUSTED_ORIGINS = [_PUBLIC]

AGIT8OR_CONNECT_ENABLED = os.environ.get('INTEROP_CONNECT_ENABLED', 'false') == 'true'
AGIT8OR_CONNECT_PUBLIC_URL = _PUBLIC
AGIT8OR_CONNECT_RUNTIME_DIR = str(INTEROP_DIR / 'runtime')
TRUSTED_PROXY_CIDRS = []

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(INTEROP_DIR / 'db.sqlite3'),
                         'OPTIONS': {'timeout': 30}}}
AI_GATEWAY_KEY_DIR = str(INTEROP_DIR / 'ai-gateway')
MEDIA_ROOT = str(INTEROP_DIR / 'media')
STATIC_ROOT = str(INTEROP_DIR / 'static')
UPLOAD_ROOT = INTEROP_DIR / 'uploads'
UPGRADE_BACKUP_DIR = INTEROP_DIR / 'backups'
LOG_DIR = INTEROP_DIR / 'logs'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(asctime)s %(process)d %(name)s %(levelname)s %(message)s'}},
    'handlers': {'file': {'class': 'logging.FileHandler', 'filename': str(INTEROP_DIR / 'logs' / 'app.log'),
                          'formatter': 'plain'}},
    'root': {'handlers': ['file'], 'level': 'WARNING'},
    'loggers': {'connect': {'handlers': ['file'], 'level': 'INFO', 'propagate': False}},
}
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
WHITENOISE_USE_FINDERS = True

# Served directly over HTTPS by gunicorn (certfile/keyfile): no proxy header.
SECURE_PROXY_SSL_HEADER = None
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

_DROP_MIDDLEWARE = {
    'accounts.middleware.Enforce2FAMiddleware',
    'axes.middleware.AxesMiddleware',
    'core.firewall_middleware.FirewallMiddleware',
}
MIDDLEWARE = [m for m in MIDDLEWARE if m not in _DROP_MIDDLEWARE]  # noqa: F405
AUTHENTICATION_BACKENDS = [b for b in AUTHENTICATION_BACKENDS if 'axes' not in b.lower()  # noqa: F405
                           ] or ['django.contrib.auth.backends.ModelBackend']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
