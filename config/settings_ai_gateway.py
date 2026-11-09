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
from .env. Vault entries, integration credentials and backup secrets are
ciphertext to it.
"""
import os

os.environ['CLIENTST0R_PROCESS_ROLE'] = 'ai_gateway'

from .settings import *  # noqa: E402,F401,F403

APP_MASTER_KEY = ''
APP_MASTER_KEY_PREVIOUS = ''
AI_GATEWAY_ROLE = 'worker'
# No web traffic is served from this process.
ALLOWED_HOSTS = []
