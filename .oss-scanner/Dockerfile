# Client St0r — build environment for Anthropic's OSS Scanner
# (https://github.com/anthropics/oss-scanner).
#
# This is NOT the production image (that's ./Dockerfile). It builds an
# analysis image: the checkout at /src, every Python dependency installed,
# a migrated SQLite database, and the test suite already run once — so an
# agent with no network can read, run and test the app.
#
# The build has network access; everything after it runs offline.
# No real secrets are used: the keys in /src/.env are generated at build
# time and exist only inside this throwaway image.

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Toolchain for mysqlclient + python-ldap, plus git (the updater code
# shells out to it) and openssh-client (netconfig's SSH collector).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config git curl ca-certificates \
        libmariadb-dev libmariadb-dev-compat \
        libldap2-dev libsasl2-dev \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so they cache across source changes. Optional
# requirements (LDAP / AD auth) are installed too so that code path is
# importable and testable.
COPY requirements.txt requirements-optional.txt /tmp/req/
RUN pip install --upgrade pip \
    && pip install -r /tmp/req/requirements.txt \
    && (pip install -r /tmp/req/requirements-optional.txt \
        || echo "WARNING: optional requirements (LDAP) failed to install")

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Throwaway, per-image configuration. config/settings.py loads /src/.env
# with override=True. Production-like security settings (DEBUG off, 2FA
# required) except HTTPS redirect, since there is no TLS in the sandbox.
RUN python - <<'EOF'
import base64, os, secrets
env = {
    "DEBUG": "False",
    "SECRET_KEY": secrets.token_urlsafe(64),
    "API_KEY_SECRET": secrets.token_urlsafe(64),
    "APP_MASTER_KEY": base64.b64encode(os.urandom(32)).decode(),
    "DB_ENGINE": "sqlite3",
    "ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
    "SECURE_SSL_REDIRECT": "False",
    "SESSION_COOKIE_SECURE": "False",
    "CSRF_COOKIE_SECURE": "False",
    "REQUIRE_2FA": "True",
    "HIBP_ENABLED": "False",
    "UPLOAD_ROOT": "/src/uploads",
    "BASE_URL": "http://localhost:8000",
}
with open("/src/.env", "w") as f:
    f.writelines(f"{k}={v}\n" for k, v in env.items())
EOF

RUN mkdir -p /src/logs /src/media /src/uploads /src/static_collected \
    && python manage.py check \
    && python manage.py migrate --noinput \
    && python manage.py collectstatic --noinput >/dev/null

# Smoke-test the security core so we know the image works, but never fail
# the build on a test failure. The full suite takes longer than the
# scanner's build budget (each run rebuilds the test DB from migrations),
# so run it on demand instead:  python manage.py test --noinput
RUN timeout 900 python manage.py test --noinput vault accounts api \
    || echo "WARNING: smoke tests reported failures (or timed out)"
RUN timeout 300 python -m unittest discover -s security_tests \
    || echo "WARNING: security_tests reported failures (or timed out)"

# To exercise the running app:
#   python manage.py createsuperuser
#   python manage.py runserver 127.0.0.1:8000
