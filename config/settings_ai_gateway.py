"""
Settings for the restricted AI gateway worker.

    CLIENTST0R_PROCESS_ROLE=ai_gateway DJANGO_SETTINGS_MODULE=config.settings_ai_gateway \
        python manage.py ai_gateway_worker

The role variable must be set before Django starts, because config.settings
scrubs secrets right after loading .env (see AI_GATEWAY_ROLE there); this
module sets it too, for launchers that only choose the settings module.

What this process can do: read and write the database rows it needs
(claimed analysis runs, budget counters), open AI provider keys with the
gateway private key, and call the approved provider destinations.

What it cannot do: it has no APP_MASTER_KEY, previous master keys,
SECRET_KEY, API_KEY_SECRET, or any other KEY/SECRET/TOKEN/PASSWORD variable
from .env except DB_PASSWORD (it works through the database). Vault entries,
integration credentials and backup secrets are ciphertext to it. Run as its
own OS user (deploy/setup-ai-gateway-user.sh, or the `ai-gateway` compose
profile) it cannot read .env at all.
"""
import os

os.environ['CLIENTST0R_PROCESS_ROLE'] = 'ai_gateway'

from .settings import *  # noqa: E402,F401,F403

APP_MASTER_KEY = ''
APP_MASTER_KEY_PREVIOUS = ''
AI_GATEWAY_ROLE = 'worker'
# No web traffic is served from this process.
ALLOWED_HOSTS = []

# Console (journald / docker logs) only. The web app's file handlers write
# /var/log/itdocs/*.log, owned by the web app's user; a worker running as
# its own user (deploy/setup-ai-gateway-user.sh) can't open them, and must
# not write the vault log anyway.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
