#!/usr/bin/env bash
# Run the AI gateway worker as its own OS user (Phase 57.3, OPTIONAL AI).
#
#   bash deploy/setup-ai-gateway-user.sh [INSTALL_DIR]
#
# Run it as the web app's user (it asks for sudo); bash install.sh runs it on
# a fresh install. Idempotent: running it again changes nothing that is
# already in place. What it does:
#
#   1. creates the system user `clientst0r-ai` (no home, no shell) and adds
#      it to the web app's group, so it can read the code and the venv;
#   2. refuses to go on if that user could read .env (APP_MASTER_KEY lives
#      there), the upgrade backups, or anything else listed below;
#   3. puts the gateway key pair in /etc/clientst0r/ai-gateway/ (directory
#      clientst0r-ai:<app group> 0750, private.key 0600 owned by
#      clientst0r-ai, public.key 0644). An existing pair from the web app's
#      key directory is moved there, so provider keys already sealed to it
#      keep working, and the web app's copy of private.key is removed;
#      otherwise a new pair is generated as clientst0r-ai;
#   4. writes /etc/clientst0r/ai-gateway.env (root:root 0600, read by
#      systemd before it drops privileges) with the DB_* settings from
#      .env and nothing else secret;
#   5. sets AI_GATEWAY_MODE=worker and AI_GATEWAY_KEY_DIR in .env, installs
#      and starts clientst0r-ai-gateway.service, and checks the result.
#
# MariaDB / MySQL only. With SQLite the worker would need write access to
# the install directory (SQLite writes its journal next to the database),
# which would let it change the web app's code, so the script stops and
# leaves AI_GATEWAY_MODE alone.
#
# The web app must be restarted afterwards to read the new .env values
# (the script says so; install.sh does it on a fresh install).
#
# Nothing here touches the vault, the database contents or any other unit.
set -euo pipefail

INSTALL_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
AI_USER=clientst0r-ai
ETC_DIR=/etc/clientst0r
KEY_DIR="$ETC_DIR/ai-gateway"
WORKER_ENV="$ETC_DIR/ai-gateway.env"
UNIT_SRC="$INSTALL_DIR/deploy/clientst0r-ai-gateway.service"
UNIT_DST=/etc/systemd/system/clientst0r-ai-gateway.service
APP_ENV="$INSTALL_DIR/.env"
PY="$INSTALL_DIR/venv/bin/python"

say()  { echo "[ai-gateway] $*"; }
fail() { echo "[ai-gateway] ERROR: $*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
    fail "run this as the web app's user, not root (it uses sudo where needed)."
fi
[ -f "$APP_ENV" ] || fail "$APP_ENV not found."
[ -x "$PY" ] || fail "$PY not found."
[ -f "$UNIT_SRC" ] || fail "$UNIT_SRC not found."

APP_USER="$(id -un)"
APP_GROUP="$(id -gn)"
[ "$(stat -c %U "$APP_ENV")" = "$APP_USER" ] || fail "$APP_ENV is not owned by $APP_USER; run as the web app's user."

env_value() {  # the last NAME=value in .env, quotes stripped
    local v
    v="$(grep -E "^$1=" "$APP_ENV" | tail -1 | cut -d= -f2-)" || true
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    printf '%s' "$v"
}

DB_ENGINE="$(env_value DB_ENGINE)"
DB_ENGINE="${DB_ENGINE:-mysql}"
if [ "$DB_ENGINE" = "sqlite3" ]; then
    fail "this install uses SQLite. A separate worker user needs MariaDB/MySQL (see the header). AI_GATEWAY_MODE was not changed."
fi

# -- 1. the user ---------------------------------------------------------------
if id -u "$AI_USER" >/dev/null 2>&1; then
    say "user $AI_USER exists"
else
    sudo useradd --system --user-group --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin --comment "Client St0r AI gateway worker" "$AI_USER"
    say "created system user $AI_USER"
fi
if ! id -nG "$AI_USER" | tr ' ' '\n' | grep -qx "$APP_GROUP"; then
    sudo usermod -aG "$APP_GROUP" "$AI_USER"
    say "added $AI_USER to group $APP_GROUP (read access to code and venv)"
fi

# sudo -u sets the target's groups from /etc/group at run time, so the group
# added just above is already in effect here.
as_ai() { sudo -u "$AI_USER" -- "$@" 2>/dev/null; }

# -- 2. what it must and must not reach ------------------------------------------
chmod 600 "$APP_ENV"
for secret in "$APP_ENV" "$APP_ENV.backup" "$INSTALL_DIR/backups" "$INSTALL_DIR/db.sqlite3" \
              "$HOME/.config/clientst0r/ai-gateway/private.key" "$HOME/.config/clientst0r/release-signing"; do
    [ -e "$secret" ] || continue
    if as_ai test -r "$secret"; then
        fail "$AI_USER can read $secret. Make it owner-only (chmod 600 / 700) and run this again."
    fi
done
as_ai test -r "$INSTALL_DIR/manage.py" \
    || fail "$AI_USER cannot read $INSTALL_DIR/manage.py. Give group $APP_GROUP read + execute on the install directory and its parents (e.g. chmod 750 \"$HOME\"), then run this again."
as_ai test -x "$PY" || fail "$AI_USER cannot run $PY (see above)."

# -- 3. keys ---------------------------------------------------------------------
OLD_KEY_DIR="$(env_value AI_GATEWAY_KEY_DIR)"
OLD_KEY_DIR="${OLD_KEY_DIR:-$HOME/.config/clientst0r/ai-gateway}"
sudo mkdir -p "$ETC_DIR"
sudo chmod 755 "$ETC_DIR"
sudo mkdir -p "$KEY_DIR"
sudo chown "$AI_USER:$APP_GROUP" "$KEY_DIR"
sudo chmod 750 "$KEY_DIR"

if sudo test -f "$KEY_DIR/private.key"; then
    say "key pair already in $KEY_DIR"
elif [ "$OLD_KEY_DIR" != "$KEY_DIR" ] && [ -f "$OLD_KEY_DIR/private.key" ]; then
    sudo install -o "$AI_USER" -g "$APP_GROUP" -m 0600 "$OLD_KEY_DIR/private.key" "$KEY_DIR/private.key"
    sudo install -o "$AI_USER" -g "$APP_GROUP" -m 0644 "$OLD_KEY_DIR/public.key" "$KEY_DIR/public.key"
    sudo cmp -s "$OLD_KEY_DIR/private.key" "$KEY_DIR/private.key" || fail "copying the private key failed; nothing removed."
    rm -f "$OLD_KEY_DIR/private.key"
    say "moved the existing key pair from $OLD_KEY_DIR to $KEY_DIR (sealed provider keys keep working)"
else
    (cd "$INSTALL_DIR" && sudo -u "$AI_USER" env -i PATH="$INSTALL_DIR/venv/bin:/usr/bin:/bin" \
        CLIENTST0R_PROCESS_ROLE=ai_gateway DJANGO_SETTINGS_MODULE=config.settings_ai_gateway \
        AI_GATEWAY_MODE=worker AI_GATEWAY_KEY_DIR="$KEY_DIR" DB_ENGINE="$DB_ENGINE" \
        "$PY" manage.py ai_gateway_keygen --group-readable >/dev/null)
    say "generated a new key pair in $KEY_DIR"
fi
sudo chown "$AI_USER:$APP_GROUP" "$KEY_DIR/private.key" "$KEY_DIR/public.key"
sudo chmod 600 "$KEY_DIR/private.key"
sudo chmod 644 "$KEY_DIR/public.key"
if test -r "$KEY_DIR/private.key"; then
    fail "$APP_USER can still read $KEY_DIR/private.key."
fi
test -r "$KEY_DIR/public.key" || fail "$APP_USER cannot read $KEY_DIR/public.key."

# -- 4. the worker's own environment ----------------------------------------------
tmp="$(mktemp)"
chmod 600 "$tmp"
{
    echo "# Written by deploy/setup-ai-gateway-user.sh. DB_* from $APP_ENV and nothing else secret."
    for name in DB_ENGINE DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT DEBUG; do
        value="$(env_value "$name")"
        [ -n "$value" ] && printf '%s=%s\n' "$name" "$value"
    done
    echo "AI_GATEWAY_MODE=worker"
    echo "AI_GATEWAY_KEY_DIR=$KEY_DIR"
} > "$tmp"
sudo install -o root -g root -m 0600 "$tmp" "$WORKER_ENV"
rm -f "$tmp"
say "wrote $WORKER_ENV (root-only)"

# -- 5. the web app's settings and the unit ------------------------------------------
set_env() {
    if grep -qE "^$1=" "$APP_ENV"; then
        sed -i "s|^$1=.*|$1=$2|" "$APP_ENV"
    else
        printf '%s=%s\n' "$1" "$2" >> "$APP_ENV"
    fi
}
set_env AI_GATEWAY_KEY_DIR "$KEY_DIR"
set_env AI_GATEWAY_MODE worker
chmod 600 "$APP_ENV"

tmp="$(mktemp)"
sed -e "s|/home/administrator|$INSTALL_DIR|g" \
    -e "s|^SupplementaryGroups=.*|SupplementaryGroups=$APP_GROUP|" \
    "$UNIT_SRC" > "$tmp"
if [ "$DB_ENGINE" != "mysql" ]; then
    sed -i "s|^After=network.target mariadb.service|After=network.target|" "$tmp"
fi
sudo install -o root -g root -m 0644 "$tmp" "$UNIT_DST"
rm -f "$tmp"
sudo systemctl daemon-reload
sudo systemctl enable clientst0r-ai-gateway.service >/dev/null 2>&1
sudo systemctl restart clientst0r-ai-gateway.service

for _ in $(seq 1 15); do
    sudo systemctl is-active --quiet clientst0r-ai-gateway.service && break
    sleep 1
done
sudo systemctl is-active --quiet clientst0r-ai-gateway.service \
    || fail "the worker did not start: sudo journalctl -u clientst0r-ai-gateway.service -n 50"
pid="$(systemctl show -p MainPID --value clientst0r-ai-gateway.service)"
if [ -n "$pid" ] && [ "$pid" != "0" ] && sudo tr '\0' '\n' < "/proc/$pid/environ" | grep -q '^APP_MASTER_KEY='; then
    fail "the worker's environment contains APP_MASTER_KEY."
fi
say "clientst0r-ai-gateway.service is running as $AI_USER"
say "restart the web app so it reads AI_GATEWAY_MODE=worker: sudo systemctl restart clientst0r-gunicorn.service"
