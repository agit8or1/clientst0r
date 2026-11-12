#!/usr/bin/env bash
# clientst0r Managed Local ONLYOFFICE: one-time root setup on the clientst0r
# server itself (docs/office/MANAGED_LOCAL.md). Usually started as
#
#   install-editor.sh --mode managed-local ...      (same options)
#
#   install-managed-local.sh --hostname office.example.com
#                            --clientstor-url https://clientstor.example.com
#                            --deployment-id acme-prod
#                            [--edition community|enterprise] [--license-file F]
#                            [--bind-port 8090] [--cpus N] [--memory-mb N]
#                            [--reserve-mb N] [--subnet 172.31.250.0/28]
#                            [--tls existing-cert --cert-file F --key-file F]
#                            [--tls certbot --certbot-email E]
#                            [--ca-file F] [--install-docker] [--app-user U]
#                            [--dry-run] [--preflight-only]
#   install-managed-local.sh --remove-units [--dry-run]
#
# What it does, and nothing else:
#   1. Checks the host: OS, architecture, Nginx (clientst0r's reverse proxy),
#      the dedicated office host name, Docker + Compose v2, nftables.
#   2. Docker: if it is installed it is used as it is (never replaced,
#      reconfigured or restarted; other containers are not touched). If it is
#      absent and --install-docker is given, installs docker.io and
#      docker-compose-v2 from the Ubuntu archive. Debian: install Docker
#      yourself first.
#   3. Writes /etc/clientst0r/office-service.conf (root-owned; the web app
#      cannot change it) and, if given, the enterprise license and a private
#      CA into /etc/clientst0r/office/ (0600).
#   4. Installs /usr/local/sbin/clientst0r-office-helper and its systemd
#      socket + firewall units, and starts the socket. The container itself is
#      installed later from Settings -> Office Documents -> Managed Local
#      ONLYOFFICE (Install), which runs the helper's fixed `install` verb.
#   5. Stops unattended-upgrades from upgrading the container engine (it
#      would restart the editor without saving open documents first).
#   6. Writes a dedicated Nginx server block for the office host name that
#      proxies to 127.0.0.1:BIND_PORT (WebSockets included), after nginx -t.
#      clientst0r's own site is never edited.
#   7. Runs the helper's preflight and prints it.
#
# It never prints or accepts secrets; the helper generates the JWT secret
# when the editor is installed. It never pulls or starts a container.
#
# Testing hook: OFFICE_INSTALL_ROOT=/dir prefixes every path and skips the
# root check (office/test_managed_installer.py). Never set it on a real host.
set -euo pipefail
umask 077

ROOT="${OFFICE_INSTALL_ROOT:-}"
SRC_DIR="$(cd "$(dirname "$(realpath "$0")")/../.." && pwd)"
HELPER_SRC="$SRC_DIR/deploy/office-helper"
MARKER='# Managed by clientst0r scripts/office/install-managed-local.sh'

CONF=/etc/clientst0r/office-service.conf
SECRETS=/etc/clientst0r/office
HELPER=/usr/local/sbin/clientst0r-office-helper
UNIT_DIR=/etc/systemd/system
APT_HOLD=/etc/apt/apt.conf.d/51clientst0r-office-engine
SITE=/etc/nginx/sites-available/clientst0r-office-managed
SITE_LINK=/etc/nginx/sites-enabled/clientst0r-office-managed
ACME_DIR=/var/www/clientst0r-office-acme
ROOT_HELPER_CONF=/etc/clientst0r/root-helper.conf

ACTION=install
OFFICE_HOST=""; CLIENTSTOR_URL=""; DEPLOYMENT_ID=""; EDITION=community; LICENSE_FILE=""
BIND_PORT=8090; CPUS=""; MEMORY_MB=4096; RESERVE_MB=2048; SUBNET=172.31.250.0/28
TLS=existing-cert; CERT_FILE=""; KEY_FILE=""; CERTBOT_EMAIL=""; CA_FILE=""
INSTALL_DOCKER=0; APP_USER=""; DRY_RUN=0; PREFLIGHT_ONLY=0

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
p() { printf '%s%s' "$ROOT" "$1"; }
dry() { [ "$DRY_RUN" -eq 1 ]; }
run() { printf '+'; printf ' %q' "$@"; printf '\n'; if dry; then return 0; fi; "$@"; }

owned_path() {
    case "$1" in
        "$CONF"|"$SECRETS"|"$SECRETS"/*|"$HELPER"|"$APT_HOLD"|"$SITE"|"$SITE_LINK") return 0 ;;
        "$UNIT_DIR"/clientst0r-office-helper.socket|"$UNIT_DIR"/clientst0r-office-helper@.service) return 0 ;;
        "$UNIT_DIR"/clientst0r-office-firewall.service) return 0 ;;
    esac
    return 1
}

# write_file PATH MODE < content
write_file() {
    local rel="$1" mode="$2" dest dir tmp
    owned_path "$rel" || die "internal: $rel is not a path this script owns"
    dest="$(p "$rel")"
    if dry; then cat >/dev/null; say "+ write $rel (mode $mode)"; return 0; fi
    dir="$(dirname "$dest")"; mkdir -p "$dir"
    tmp="$(mktemp "$dir/.clientst0r-office.XXXXXX")"
    cat >"$tmp"; chmod "$mode" "$tmp"
    if [ -z "$ROOT" ]; then chown root:root "$tmp"; fi
    mv -f "$tmp" "$dest"
    say "+ wrote $rel (mode $mode)"
}

remove_path() {
    local rel="$1"
    owned_path "$rel" || die "internal: refusing to remove $rel"
    if [ -e "$(p "$rel")" ] || [ -L "$(p "$rel")" ]; then run rm -f -- "$(p "$rel")"; fi
}

need_val() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"; }

parse_args() {
    [ $# -gt 0 ] || usage
    while [ $# -gt 0 ]; do
        case "$1" in
            --mode) need_val "$@"; [ "$2" = managed-local ] || die "this script only does --mode managed-local"; shift ;;
            --provider) need_val "$@"; [ "$2" = onlyoffice ] || die "Managed Local supports --provider onlyoffice only"; shift ;;
            --hostname) need_val "$@"; OFFICE_HOST="$2"; shift ;;
            --clientstor-url) need_val "$@"; CLIENTSTOR_URL="$2"; shift ;;
            --deployment-id) need_val "$@"; DEPLOYMENT_ID="$2"; shift ;;
            --edition) need_val "$@"; EDITION="$2"; shift ;;
            --license-file) need_val "$@"; LICENSE_FILE="$2"; shift ;;
            --bind-port) need_val "$@"; BIND_PORT="$2"; shift ;;
            --cpus) need_val "$@"; CPUS="$2"; shift ;;
            --memory-mb) need_val "$@"; MEMORY_MB="$2"; shift ;;
            --reserve-mb) need_val "$@"; RESERVE_MB="$2"; shift ;;
            --subnet) need_val "$@"; SUBNET="$2"; shift ;;
            --tls) need_val "$@"; TLS="$2"; shift ;;
            --cert-file) need_val "$@"; CERT_FILE="$2"; shift ;;
            --key-file) need_val "$@"; KEY_FILE="$2"; shift ;;
            --certbot-email) need_val "$@"; CERTBOT_EMAIL="$2"; shift ;;
            --ca-file) need_val "$@"; CA_FILE="$2"; shift ;;
            --install-docker) INSTALL_DOCKER=1 ;;
            --app-user) need_val "$@"; APP_USER="$2"; shift ;;
            --dry-run) DRY_RUN=1 ;;
            --preflight-only) PREFLIGHT_ONLY=1 ;;
            --remove-units) ACTION=remove ;;
            --secret|--jwt-secret|--secret=*|--jwt-secret=*)
                die "Secrets are never accepted on the command line; the helper generates the JWT secret." ;;
            -h|--help) usage ;;
            *) die "Unknown option for --mode managed-local: $1" ;;
        esac
        shift
    done
}

HOST_RE='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$'

url_host() { local r="${1#https://}"; r="${r%%/*}"; printf '%s' "${r%%:*}" | tr '[:upper:]' '[:lower:]'; }

validate() {
    OFFICE_HOST="$(printf '%s' "$OFFICE_HOST" | tr '[:upper:]' '[:lower:]')"
    [[ "$OFFICE_HOST" =~ $HOST_RE ]] || die "--hostname must be a DNS name (a dedicated one, e.g. office.example.com)"
    [[ "$CLIENTSTOR_URL" =~ ^https://[A-Za-z0-9.-]+/?$ ]] || \
        die "--clientstor-url must be https://<clientst0r host name>/ (port 443, no path)"
    local cs_host; cs_host="$(url_host "$CLIENTSTOR_URL")"
    [[ "$cs_host" =~ $HOST_RE ]] || die "--clientstor-url must use a host name, not an IP address"
    [ "$cs_host" != "$OFFICE_HOST" ] || \
        die "The office host name must differ from clientst0r's: the editor must not share clientst0r's origin"
    [[ "$DEPLOYMENT_ID" =~ ^[a-z0-9][a-z0-9-]{1,40}$ ]] || die "--deployment-id: 2-41 of a-z 0-9 -"
    case "$EDITION" in community|enterprise) ;; *) die "--edition community or enterprise" ;; esac
    if [ "$EDITION" = enterprise ]; then
        [ -n "$LICENSE_FILE" ] && [ -f "$LICENSE_FILE" ] || die "--edition enterprise needs --license-file (license.lic from ONLYOFFICE)"
    fi
    [[ "$BIND_PORT" =~ ^[0-9]{4,5}$ ]] && [ "$BIND_PORT" -ge 1024 ] && [ "$BIND_PORT" -le 65535 ] || die "--bind-port 1024-65535"
    [[ "$MEMORY_MB" =~ ^[0-9]+$ ]] && [[ "$RESERVE_MB" =~ ^[0-9]+$ ]] || die "--memory-mb/--reserve-mb are whole numbers"
    if [ -z "$CPUS" ]; then
        local n; n="$(nproc)"; CPUS=$(( n > 2 ? n - 1 : 1 )); [ "$CPUS" -le 4 ] || CPUS=4
    fi
    [[ "$CPUS" =~ ^[0-9]+(\.[0-9])?$ ]] || die "--cpus is a number such as 2 or 1.5"
    [[ "$SUBNET" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/(2[4-9])$ ]] || die "--subnet is a private IPv4 /24-/29"
    case "$TLS" in
        existing-cert) [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ] || die "--tls existing-cert needs --cert-file and --key-file" ;;
        certbot) [ -n "$CERTBOT_EMAIL" ] || die "--tls certbot needs --certbot-email" ;;
        *) die "--tls existing-cert or certbot (the editor is always served over HTTPS by this server's Nginx)" ;;
    esac
    [ -z "$CA_FILE" ] || [ -f "$CA_FILE" ] || die "--ca-file $CA_FILE does not exist"
    if [ -z "$APP_USER" ] && [ -f "$(p "$ROOT_HELPER_CONF")" ]; then
        APP_USER="$(sed -n 's/^APP_USER=\([a-z_][a-z0-9_-]*\)$/\1/p' "$(p "$ROOT_HELPER_CONF")" | head -1)"
    fi
    [[ "$APP_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] && [ "$APP_USER" != root ] || \
        die "Could not work out the clientst0r app user: pass --app-user (the account gunicorn runs as)"
    for f in clientst0r-office-helper clientst0r-office-helper.socket clientst0r-office-helper@.service \
             clientst0r-office-firewall.service; do
        [ -f "$HELPER_SRC/$f" ] || die "missing $HELPER_SRC/$f"
    done
}

# --- host checks ---------------------------------------------------------------
FAILS=0
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
note() { printf '  WARN  %s\n' "$1"; }

os_id() { sed -n 's/^ID="\{0,1\}\([a-z]*\)"\{0,1\}$/\1/p' "$(p /etc/os-release)" 2>/dev/null | head -1; }

DOCKER_STATE=""
host_checks() {
    say "Host checks"
    local id; id="$(os_id)"
    case "$id" in ubuntu|debian) ok "OS $id" ;; *) bad "OS ${id:-unknown}: Ubuntu 22.04/24.04 or Debian 12" ;; esac
    case "$(uname -m)" in x86_64) ok "architecture x86_64" ;; aarch64) note "architecture aarch64 (untested)" ;;
        *) bad "architecture $(uname -m): the image is published for amd64 and arm64 only" ;; esac
    if command -v nginx >/dev/null 2>&1 && [ -d "$(p /etc/nginx/sites-available)" ]; then ok "Nginx present"
    else bad "Nginx with sites-available/ not found: clientst0r's reverse proxy is required"; fi
    if command -v docker >/dev/null 2>&1; then
        if docker compose version >/dev/null 2>&1; then
            DOCKER_STATE=present; ok "Docker and Compose v2 present: used as they are, not changed"
        else
            DOCKER_STATE=nocompose
            bad "Docker is installed but 'docker compose' (v2) is not. Install the Compose v2 plugin for your Docker (docker-compose-v2 from Ubuntu, or docker-compose-plugin from Docker's repository) and rerun; this script does not change an existing Docker install."
        fi
    elif [ "$INSTALL_DOCKER" -eq 1 ] && [ "$id" = ubuntu ]; then
        DOCKER_STATE=install; ok "Docker absent: docker.io and docker-compose-v2 will be installed from the Ubuntu archive"
    elif [ "$INSTALL_DOCKER" -eq 1 ]; then
        DOCKER_STATE=absent; bad "Docker absent: --install-docker supports Ubuntu only; install Docker Engine and Compose v2 first"
    else
        DOCKER_STATE=absent; bad "Docker absent: rerun with --install-docker (Ubuntu archive packages), or install Docker Engine + Compose v2 yourself"
    fi
    if command -v nft >/dev/null 2>&1; then ok "nftables present"; else note "nftables missing: the nftables package will be installed"; fi
    local site
    for site in "$(p /etc/nginx/sites-enabled)"/*; do
        [ -e "$site" ] || continue
        [ "$(basename "$site")" = clientst0r-office-managed ] && continue
        if grep -qE "server_name[^;]*[[:space:]]$OFFICE_HOST([[:space:];]|$)" "$site" 2>/dev/null; then
            bad "$OFFICE_HOST is already served by $(basename "$site")"
        fi
    done
    if getent hosts "$OFFICE_HOST" >/dev/null 2>&1; then ok "$OFFICE_HOST resolves"
    else note "$OFFICE_HOST does not resolve yet: create its DNS record (browsers need it; certbot needs it now)"; fi
}

# --- actions -------------------------------------------------------------------
install_docker() {
    [ "$DOCKER_STATE" = install ] || return 0
    run apt-get -q update
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends docker.io docker-compose-v2
    run systemctl enable --now docker.service
}

install_nft() {
    command -v nft >/dev/null 2>&1 && return 0
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y -q nftables
}

write_conf() {
    {
        printf '%s\n# See deploy/office-helper/office-service.conf.example for every key.\n' "$MARKER"
        printf 'DEPLOYMENT_ID=%s\nAPP_USER=%s\nOFFICE_HOSTNAME=%s\nCLIENTSTOR_URL=%s\n' \
            "$DEPLOYMENT_ID" "$APP_USER" "$OFFICE_HOST" "https://$(url_host "$CLIENTSTOR_URL")/"
        printf 'BIND_PORT=%s\nEDITION=%s\nCPUS=%s\nMEMORY_MB=%s\nRESERVE_MB=%s\nNETWORK_SUBNET=%s\n' \
            "$BIND_PORT" "$EDITION" "$CPUS" "$MEMORY_MB" "$RESERVE_MB" "$SUBNET"
        printf 'ALLOW_UNTESTED_RELEASES=no\nPRIVATE_CA=%s\nMAINTENANCE_UPDATES=no\n' \
            "$([ -n "$CA_FILE" ] && echo yes || echo no)"
    } | write_file "$CONF" 0644
    run install -d -m 0700 "$(p "$SECRETS")"
    if [ -n "$LICENSE_FILE" ]; then write_file "$SECRETS/license.lic" 0600 < "$LICENSE_FILE"; fi
    if [ -n "$CA_FILE" ]; then
        if ! dry; then grep -q 'BEGIN CERTIFICATE' "$CA_FILE" || die "--ca-file is not a PEM certificate"; fi
        write_file "$SECRETS/extra-ca-certs.pem" 0600 < "$CA_FILE"
    fi
}

install_helper() {
    python3 -I -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" \
        "$HELPER_SRC/clientst0r-office-helper"
    write_file "$HELPER" 0755 < "$HELPER_SRC/clientst0r-office-helper"
    sed "s/@APP_USER@/$APP_USER/g" "$HELPER_SRC/clientst0r-office-helper.socket" \
        | write_file "$UNIT_DIR/clientst0r-office-helper.socket" 0644
    write_file "$UNIT_DIR/clientst0r-office-helper@.service" 0644 < "$HELPER_SRC/clientst0r-office-helper@.service"
    write_file "$UNIT_DIR/clientst0r-office-firewall.service" 0644 < "$HELPER_SRC/clientst0r-office-firewall.service"
    run systemctl daemon-reload
    run systemctl enable --now clientst0r-office-helper.socket
    run systemctl enable clientst0r-office-firewall.service
    run systemctl restart clientst0r-office-firewall.service
}

hold_engine() {
    # Unattended-upgrades would restart dockerd, and with it the editor,
    # without saving open documents first. Upgrade the engine by hand after
    # stopping the editor from Office settings.
    {
        printf '%s\n' "$MARKER"
        printf 'Unattended-Upgrade::Package-Blacklist {\n'
        printf '    "docker.io"; "docker-ce"; "docker-ce-cli"; "containerd"; "containerd.io"; "runc";\n'
        printf '    "docker-compose-v2"; "docker-compose-plugin";\n};\n'
    } | write_file "$APT_HOLD" 0644
}

nginx_site() {
    local tls="$1"
    printf '%s\n# Managed Local ONLYOFFICE: %s -> 127.0.0.1:%s (loopback only).\n' "$MARKER" "$OFFICE_HOST" "$BIND_PORT"
    printf '# clientst0r'"'"'s own server block is not edited.\n\n'
    printf 'map $http_upgrade $clientst0r_office_managed_upgrade {\n    default upgrade;\n    %s close;\n}\n\n' "''"
    printf 'server {\n    listen 80;\n    listen [::]:80;\n    server_name %s;\n' "$OFFICE_HOST"
    printf '    location /.well-known/acme-challenge/ { root %s; }\n' "$ACME_DIR"
    if [ "$tls" = acme-only ]; then printf '    location / { return 404; }\n}\n'; return 0; fi
    printf '    location / { return 301 https://$host$request_uri; }\n}\n\n'
    printf 'server {\n    listen 443 ssl;\n    listen [::]:443 ssl;\n    server_name %s;\n' "$OFFICE_HOST"
    printf '    ssl_certificate %s;\n    ssl_certificate_key %s;\n    ssl_protocols TLSv1.2 TLSv1.3;\n' \
        "$CERT_FILE" "$KEY_FILE"
    printf '    client_max_body_size 200m;\n    server_tokens off;\n'
    printf '    add_header X-Content-Type-Options nosniff always;\n'
    printf '    add_header Strict-Transport-Security "max-age=31536000" always;\n'
    printf '    access_log /var/log/nginx/clientst0r-office-managed-access.log;\n'
    printf '    error_log /var/log/nginx/clientst0r-office-managed-error.log;\n\n'
    printf '    # The editor'"'"'s welcome, example and admin pages are disabled in the container.\n'
    printf '    location / {\n        proxy_pass http://127.0.0.1:%s;\n' "$BIND_PORT"
    printf '        proxy_http_version 1.1;\n'
    printf '        proxy_set_header Upgrade $http_upgrade;\n'
    printf '        proxy_set_header Connection $clientst0r_office_managed_upgrade;\n'
    printf '        proxy_set_header Host $host;\n'
    printf '        proxy_set_header X-Forwarded-Host $host;\n'
    printf '        proxy_set_header X-Forwarded-Proto https;\n'
    printf '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
    printf '        proxy_set_header X-Real-IP $remote_addr;\n'
    printf '        proxy_buffering off;\n'
    printf '        proxy_connect_timeout 10s;\n'
    printf '        proxy_read_timeout 3600s;\n        proxy_send_timeout 3600s;\n    }\n}\n'
}

apply_site() {
    local content="$1" backup=""
    if [ -e "$(p "$SITE")" ] && ! dry; then backup="$(mktemp)"; cp "$(p "$SITE")" "$backup"; fi
    printf '%s\n' "$content" | write_file "$SITE" 0644
    run ln -sfn "$SITE" "$(p "$SITE_LINK")"
    run install -d -m 0755 "$(p "$ACME_DIR")"
    if dry; then say "+ nginx -t && systemctl reload nginx"; return 0; fi
    if ! nginx -t >/dev/null 2>&1; then
        if [ -n "$backup" ]; then cp "$backup" "$(p "$SITE")"; else rm -f -- "$(p "$SITE")" "$(p "$SITE_LINK")"; fi
        die "nginx -t rejected the office server block; it was removed again and Nginx was not reloaded."
    fi
    [ -z "$backup" ] || rm -f -- "$backup"
    run systemctl reload nginx
}

setup_site() {
    if [ "$TLS" = certbot ]; then
        command -v certbot >/dev/null 2>&1 || run apt-get install -y -q certbot
        apply_site "$(nginx_site acme-only)"
        run certbot certonly --webroot -w "$(p "$ACME_DIR")" -d "$OFFICE_HOST" --non-interactive \
            --agree-tos -m "$CERTBOT_EMAIL" --deploy-hook 'systemctl reload nginx'
        CERT_FILE="/etc/letsencrypt/live/$OFFICE_HOST/fullchain.pem"
        KEY_FILE="/etc/letsencrypt/live/$OFFICE_HOST/privkey.pem"
    fi
    apply_site "$(nginx_site tls)"
}

helper_preflight() {
    say ""; say "Helper preflight (the same checks as Settings -> Setup checks)"
    if dry; then say "+ $HELPER cli preflight"; return 0; fi
    "$(p "$HELPER")" cli preflight || warn "The helper preflight did not run; see the error above."
}

do_install() {
    validate
    if [ -z "$ROOT" ] && ! dry && [ "$PREFLIGHT_ONLY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
        die "Run as root (sudo). Use --dry-run or --preflight-only to look first."
    fi
    host_checks
    [ "$FAILS" -eq 0 ] || die "$FAILS check(s) failed; nothing was changed."
    [ "$PREFLIGHT_ONLY" -eq 0 ] || exit 0
    dry && say "" && say "DRY RUN: the actions below are printed only; nothing is changed."
    install_docker
    install_nft
    write_conf
    install_helper
    hold_engine
    setup_site
    helper_preflight
    say ""
    say "Done. Next, as a clientst0r superuser: Settings -> Office Documents -> Managed Local ONLYOFFICE,"
    say "turn it on, run Setup checks, then Install. No container was pulled or started by this script."
}

do_remove() {
    # Units, helper, firewall table and the Nginx block only. The container
    # must be uninstalled from Office settings first, and a purge
    # (clientst0r-office-helper cli purge) must run before this if wanted,
    # since it needs the helper and its config. Data, secrets and backups under
    # /var/lib/clientst0r-office and /etc/clientst0r/office are kept.
    if [ -z "$ROOT" ] && ! dry && [ "$(id -u)" -ne 0 ]; then die "Run as root (sudo)."; fi
    if ! dry && [ -x "$(p "$HELPER")" ] && [ -z "$ROOT" ]; then
        if "$HELPER" cli status 2>/dev/null | grep -q '"running": true'; then
            die "The editor container is still running: uninstall it from Office settings first (that saves open documents)."
        fi
    fi
    run systemctl disable --now clientst0r-office-helper.socket || true
    run systemctl disable clientst0r-office-firewall.service || true
    remove_path "$UNIT_DIR/clientst0r-office-helper.socket"
    remove_path "$UNIT_DIR/clientst0r-office-helper@.service"
    remove_path "$UNIT_DIR/clientst0r-office-firewall.service"
    remove_path "$HELPER"
    remove_path "$SITE_LINK"
    remove_path "$SITE"
    remove_path "$APT_HOLD"
    remove_path "$CONF"
    if ! dry && command -v nft >/dev/null 2>&1 && nft list table inet clientst0r_office >/dev/null 2>&1; then
        run nft delete table inet clientst0r_office
    fi
    run systemctl daemon-reload
    if ! dry; then nginx -t >/dev/null 2>&1 && run systemctl reload nginx; fi
    say "Removed the helper, its units and the Nginx block. Kept: /var/lib/clientst0r-office (editor data, backups), $SECRETS (secrets)."
}

parse_args "$@"
case "$ACTION" in
    install) do_install ;;
    remove) do_remove ;;
esac
