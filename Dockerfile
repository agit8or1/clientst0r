# Client St0r — production Dockerfile
#
# Multi-stage Python 3.12 build. Stage 1 compiles wheels with a full
# toolchain into a venv. Stage 2 copies the venv into a slim runtime
# image, runs the app as a non-root user.
#
# Build:  docker build -t clientst0r .
# Run:    docker compose up -d   (see docker-compose.yml)

# ─── Stage 1 — builder ────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Toolchain for mysqlclient and any wheel that compiles natively.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libmariadb-dev \
        libmariadb-dev-compat \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt


# ─── Stage 2 — runtime ────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings

# Runtime libs only: mariadb client, curl (used by HEALTHCHECK) and ping
# (scheduled WAN connection checks; Docker's default ping_group_range lets the
# non-root user send ICMP echo).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmariadb3 \
        curl \
        iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Copy the prebuilt venv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Non-root runtime user. uid 1000 is the common host-default — matches
# typical bind-mount ownership without extra chown gymnastics.
RUN useradd -m -u 1000 clientst0r \
    && mkdir -p /app /app/logs /app/media /app/static_collected /var/lib/itdocs/uploads \
    && chown -R clientst0r:clientst0r /app /var/lib/itdocs

WORKDIR /app

# Copy source. .dockerignore keeps node_modules, venvs, db files,
# .git, mobile/, local_apps/, etc. out of the context.
COPY --chown=clientst0r:clientst0r . /app/

USER clientst0r

# collectstatic is intentionally NOT run during build. It needs
# SECRET_KEY / ALLOWED_HOSTS / DB settings which only exist at run
# time. The entrypoint runs it after env is wired up.

EXPOSE 8000

# Healthcheck hits the dedicated /health/ endpoint added in v3.17.490.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/ || exit 1

# Entrypoint waits for DB + runs migrations + collectstatic, then
# execs CMD.
COPY --chown=clientst0r:clientst0r docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# --timeout 300: AI documentation generation (especially local Ollama models
# on CPU) legitimately runs for several minutes. A shorter worker timeout gets
# the worker SIGKILLed mid-request, so the browser receives gunicorn's HTML 500
# page instead of our JSON error ("Server returned HTML instead of JSON" — #138).
# Provider HTTP timeouts are capped below this so a genuinely stuck model
# returns a clean JSON error before the worker is reaped.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
