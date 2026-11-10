#!/bin/bash
# Print a disposable .env for the Docker CI jobs (fresh secrets every run).
set -euo pipefail
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
cat <<EOF
SECRET_KEY=$(rand 50)
APP_MASTER_KEY=$(python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())")
API_KEY_SECRET=$(rand 50)
DB_PASSWORD=$(rand 24)
DB_ROOT_PASSWORD=$(rand 24)
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
REQUIRE_2FA=True
HIBP_ENABLED=False
HIBP_CHECK_ON_SAVE=False
COMPOSE_PROJECT_NAME=clientst0r
EOF
