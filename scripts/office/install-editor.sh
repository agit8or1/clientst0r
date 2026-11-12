#!/usr/bin/env bash
# clientst0r Office editor installer: ONLYOFFICE Docs or Collabora Online.
#
# Run as root on the machine that will host the editor: a separate VM
# (recommended), or the clientst0r server itself with a dedicated host name.
# clientst0r never runs this script. Settings -> Integrations -> Office
# Documents -> Install guidance shows the exact command for your setup.
#
#   install-editor.sh --provider onlyoffice|collabora-code|collabora-online
#                     --mode same-server|separate-server
#   install-editor.sh --mode managed-local ...  (ONLYOFFICE in a pinned Docker
#                     container on the clientst0r server, run by clientst0r:
#                     see install-managed-local.sh --help)
#                     --hostname editor.example.com
#                     --clientstor-url https://clientstor.example.com
#                     [--clientstor-ip 192.0.2.10] [--ca-file /path/ca.pem]
#                     [--tls existing-cert|certbot|none-behind-proxy]
#                     [--cert-file F --key-file F] [--certbot-email E]
#                     [--version V] [--brand-version V]
#                     [--repo-url-file F]           (collabora-online only)
#                     [--accept-mscorefonts-eula]   (onlyoffice only)
#                     [--app-user U] [--no-import-file]
#                     [--accept-low-resources] [--dry-run] [--preflight-only]
#   install-editor.sh --upgrade --version V [--brand-version V] [--confirm-drained]
#   install-editor.sh --uninstall [--purge-state] [--dry-run]
#   install-editor.sh --health-check
#
# What it does (see docs/office/INSTALL.md):
#   1. Preflight: OS, CPU/RAM/disk, ports, Nginx and its sites, package
#      conflicts, other apps. Same-server needs a dedicated host name and
#      never touches clientst0r's own Nginx site, app directory or .env.
#   2. Adds the vendor's apt repository. The signing key is fetched over
#      HTTPS and trusted only when its fingerprint matches the pinned one;
#      it goes into its own keyring in /etc/apt/keyrings (signed-by).
#   3. Installs the pinned package version, pins it in apt preferences and
#      holds it, so an ordinary `apt upgrade` (or clientst0r's own package
#      updates) never upgrades the editor. Upgrades are explicit: --upgrade.
#   4. Configures the editor for clientst0r only, writes a dedicated Nginx
#      server block (WebSockets included), reloads Nginx after `nginx -t`.
#   5. Generates the shared secret into a root-only file (0600). It is never
#      printed and never put on a command line. Optionally writes a one-time
#      import file for `manage.py office_setup --import-secret FILE`, which
#      stores it in clientst0r and shreds the file.
#   6. Runs a health check and prints the values to enter in clientst0r.
#
# --dry-run prints every action and changes nothing (it does download the
# signing key into a temporary directory to check its fingerprint).
#
# Testing hook: OFFICE_INSTALL_ROOT=/some/dir prefixes every file path, skips
# the root check and chown, so the test suite can run the script against a
# fake filesystem with stubbed apt-get/systemctl/nginx/curl. Never set it on
# a real host.
set -euo pipefail
umask 077

ROOT="${OFFICE_INSTALL_ROOT:-}"
SELF="$(basename "$0")"
HEALTH_WAIT="${OFFICE_INSTALL_HEALTH_WAIT:-90}"
MARKER='# Managed by clientst0r scripts/office/install-editor.sh'

# --- Pinned vendor facts (docs/office/INSTALL.md lists the sources) ----------
OO_PKG=onlyoffice-documentserver
OO_DEFAULT_VERSION=10.0.0-169       # 10.0.0 fixes the WOPI SSRF + macro sandbox issues
OO_MIN_VERSION=10.0.0
OO_PORT=8083                        # DEB/RPM default since 10.0
OO_KEY_URL=https://download.onlyoffice.com/GPG-KEY-ONLYOFFICE
OO_KEY_FPR=E09CA29F6E178040EF22B4098320CA65CB2DE8E5
OO_REPO_URI=https://download.onlyoffice.com/repo/debian
OO_REPO_ORIGIN=download.onlyoffice.com
OO_CONFLICTS="onlyoffice-documentserver-ee onlyoffice-documentserver-de"

CO_PKG=coolwsd
CO_CODE_BRAND=code-brand
CO_ONLINE_BRAND=collabora-online-brand
CO_CODE_VERSION=26.04.6.1-1
CO_CODE_BRAND_VERSION=26.04.6-1
CO_PORT=9980
CO_KEY_URL=https://collaboraoffice.com/downloads/gpg/collaboraonline-release-keyring.gpg
CO_KEY_FPR=7EB1530818B7683284483B7BD8915E456E7C440E
CO_CODE_URI=https://www.collaboraoffice.com/repos/CollaboraOnline/CODE-deb
CO_REPO_ORIGIN=www.collaboraoffice.com
CO_CONFLICTS="loolwsd"

# --- Paths (all under $ROOT) -------------------------------------------------
STATE_DIR=/etc/clientst0r-office
STATE_FILE=$STATE_DIR/install.conf
SECRET_FILE=$STATE_DIR/secret
IMPORT_DIR=/var/lib/clientst0r-office-import
KEYRING_DIR=/etc/apt/keyrings
CA_DEST=/usr/local/share/ca-certificates/clientst0r-office-ca.crt
ACME_DIR=/var/www/clientst0r-office-acme
OO_LOCAL_JSON=/etc/onlyoffice/documentserver/local.json
CO_XML=/etc/coolwsd/coolwsd.xml
CO_PROOF_KEY=/etc/coolwsd/proof_key
HELPER_CONF=/etc/clientst0r/root-helper.conf

# --- Options -----------------------------------------------------------------
ACTION=install
PROVIDER=""
MODE=""
HOSTNAME_ARG=""
CLIENTSTOR_URL=""
CLIENTSTOR_IP=""
CA_FILE=""
TLS=""
CERT_FILE=""
KEY_FILE=""
CERTBOT_EMAIL=""
VERSION=""
BRAND_VERSION=""
REPO_URL_FILE=""
KEY_FPR_OVERRIDE=""
ACCEPT_EULA=0
APP_USER=""
APP_DIR=""
WRITE_IMPORT=1
ACCEPT_LOW=0
DRY_RUN=0
PREFLIGHT_ONLY=0
CONFIRM_DRAINED=0
PURGE_STATE=0

# --- Output helpers ----------------------------------------------------------
say()  { printf '%s\n' "$*"; }
info() { printf '  - %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

p() { printf '%s%s' "$ROOT" "$1"; }
dry() { [ "$DRY_RUN" -eq 1 ]; }

# Print, then run (unless --dry-run). Never pass a secret to this.
run() {
    printf '+'; printf ' %q' "$@"; printf '\n'
    if dry; then return 0; fi
    "$@"
}

# --- Path guard: everything this script writes or removes goes through here --
PROTECTED=()

protect() { [ -n "$1" ] && PROTECTED+=("$1"); return 0; }

guard_path() {
    local path="$1" prot
    case "$(basename "$path")" in
        .env|.env.*) die "Refusing to touch $path: an .env file is never changed by this script." ;;
    esac
    for prot in "${PROTECTED[@]+"${PROTECTED[@]}"}"; do
        case "$path" in
            "$prot"|"$prot"/*) die "Refusing to touch $path: it belongs to clientst0r ($prot)." ;;
        esac
    done
}

owned_path() {
    # The only paths this script may create or delete (without $ROOT).
    case "$1" in
        "$STATE_DIR"|"$STATE_DIR"/*|"$IMPORT_DIR"|"$IMPORT_DIR"/*) return 0 ;;
        /etc/apt/keyrings/clientst0r-office-*|/etc/apt/sources.list.d/clientst0r-office-*) return 0 ;;
        /etc/apt/preferences.d/clientst0r-office-*) return 0 ;;
        /etc/nginx/sites-available/clientst0r-office-*|/etc/nginx/sites-enabled/clientst0r-office-*) return 0 ;;
        /etc/nginx/conf.d/clientst0r-office-*) return 0 ;;
        /etc/systemd/system/*.service.d/clientst0r-office-ca.conf) return 0 ;;
        "$CA_DEST"|"$ACME_DIR"|"$ACME_DIR"/*) return 0 ;;
        "$OO_LOCAL_JSON"|"$CO_XML"|/etc/coolwsd/clientst0r-office-ca.pem) return 0 ;;
    esac
    return 1
}

# write_file PATH MODE [OWNER] < content
write_file() {
    local rel="$1" mode="$2" owner="${3:-}" dest dir tmp
    owned_path "$rel" || die "internal: $rel is not a path this script owns"
    dest="$(p "$rel")"
    guard_path "$dest"
    if dry; then
        cat >/dev/null
        say "+ write $rel (mode $mode${owner:+, owner $owner})"
        return 0
    fi
    dir="$(dirname "$dest")"
    mkdir -p "$dir"
    tmp="$(mktemp "$dir/.clientst0r-office.XXXXXX")"
    cat >"$tmp"
    chmod "$mode" "$tmp"
    if [ -n "$owner" ] && [ -z "$ROOT" ]; then chown "$owner" "$tmp"; fi
    mv -f "$tmp" "$dest"
    say "+ wrote $rel (mode $mode)"
}

remove_path() {
    local rel="$1" target
    owned_path "$rel" || die "internal: refusing to remove $rel (not created by this script)"
    target="$(p "$rel")"
    guard_path "$target"
    if [ -e "$target" ] || [ -L "$target" ]; then
        run rm -rf -- "$target"
    fi
}

# --- Argument parsing --------------------------------------------------------
need_val() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"; }

parse_args() {
    [ $# -gt 0 ] || usage
    while [ $# -gt 0 ]; do
        case "$1" in
            --provider) need_val "$@"; PROVIDER="$2"; shift ;;
            --mode) need_val "$@"; MODE="$2"; shift ;;
            --hostname) need_val "$@"; HOSTNAME_ARG="$2"; shift ;;
            --clientstor-url) need_val "$@"; CLIENTSTOR_URL="$2"; shift ;;
            --clientstor-ip) need_val "$@"; CLIENTSTOR_IP="$2"; shift ;;
            --ca-file) need_val "$@"; CA_FILE="$2"; shift ;;
            --tls) need_val "$@"; TLS="$2"; shift ;;
            --cert-file) need_val "$@"; CERT_FILE="$2"; shift ;;
            --key-file) need_val "$@"; KEY_FILE="$2"; shift ;;
            --certbot-email) need_val "$@"; CERTBOT_EMAIL="$2"; shift ;;
            --version) need_val "$@"; VERSION="$2"; shift ;;
            --brand-version) need_val "$@"; BRAND_VERSION="$2"; shift ;;
            --repo-url-file) need_val "$@"; REPO_URL_FILE="$2"; shift ;;
            --key-fingerprint) need_val "$@"; KEY_FPR_OVERRIDE="$2"; shift ;;
            --accept-mscorefonts-eula) ACCEPT_EULA=1 ;;
            --app-user) need_val "$@"; APP_USER="$2"; shift ;;
            --clientstor-dir) need_val "$@"; APP_DIR="$2"; shift ;;
            --no-import-file) WRITE_IMPORT=0 ;;
            --accept-low-resources) ACCEPT_LOW=1 ;;
            --dry-run) DRY_RUN=1 ;;
            --preflight-only) PREFLIGHT_ONLY=1 ;;
            --upgrade) ACTION=upgrade ;;
            --uninstall) ACTION=uninstall ;;
            --health-check) ACTION=health ;;
            --confirm-drained) CONFIRM_DRAINED=1 ;;
            --purge-state) PURGE_STATE=1 ;;
            --secret|--jwt-secret|--secret=*|--jwt-secret=*)
                die "Secrets are never accepted on the command line. The installer generates one into $SECRET_FILE." ;;
            -h|--help) usage ;;
            *) die "Unknown option: $1 (see --help)" ;;
        esac
        shift
    done
}

# --- Validation --------------------------------------------------------------
HOST_RE='^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$'
IPV4_RE='^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$'
IPV6_RE='^[0-9A-Fa-f:]*:[0-9A-Fa-f:.]*$'
VERSION_RE='^[0-9][A-Za-z0-9.+~-]{0,60}$'

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

url_host() {  # https://Host[:port][/...] -> host
    local rest="${1#*://}"
    rest="${rest%%/*}"
    rest="${rest%%:*}"
    lower "$rest"
}

url_port() {
    local rest="${1#*://}" scheme="${1%%://*}"
    rest="${rest%%/*}"
    if [[ "$rest" == *:* ]]; then printf '%s' "${rest##*:}"
    elif [ "$scheme" = "http" ]; then printf '80'
    else printf '443'; fi
}

is_ip() { [[ "$1" =~ $IPV4_RE ]] || [[ "$1" =~ $IPV6_RE ]]; }

validate_install_args() {
    case "$PROVIDER" in
        onlyoffice|collabora-code|collabora-online) ;;
        "") die "--provider is required (onlyoffice, collabora-code or collabora-online)" ;;
        *) die "Unknown --provider $PROVIDER" ;;
    esac
    case "$MODE" in
        same-server|separate-server) ;;
        "") die "--mode is required (same-server, separate-server or managed-local)" ;;
        *) die "Unknown --mode $MODE" ;;
    esac
    HOSTNAME_ARG="$(lower "$HOSTNAME_ARG")"
    [[ "$HOSTNAME_ARG" =~ $HOST_RE ]] || die "--hostname must be a DNS host name such as docs.example.com"
    [[ "$CLIENTSTOR_URL" =~ ^https?://[A-Za-z0-9.:-]+(/.*)?$ ]] \
        || die "--clientstor-url must be the https:// address of clientst0r"
    [[ "$CLIENTSTOR_URL" == https://* ]] || warn "--clientstor-url is not https; the editor will send saves unencrypted."
    CLIENTSTOR_URL="${CLIENTSTOR_URL%/}/"
    CLIENTSTOR_HOST="$(url_host "$CLIENTSTOR_URL")"
    CLIENTSTOR_PORT="$(url_port "$CLIENTSTOR_URL")"
    CLIENTSTOR_ORIGIN="${CLIENTSTOR_URL%%://*}://${CLIENTSTOR_HOST}"
    if [ "$CLIENTSTOR_PORT" != 443 ] && [ "$CLIENTSTOR_PORT" != 80 ]; then
        CLIENTSTOR_ORIGIN="$CLIENTSTOR_ORIGIN:$CLIENTSTOR_PORT"
    fi
    [ "$HOSTNAME_ARG" != "$CLIENTSTOR_HOST" ] \
        || die "The editor needs its own host name; $HOSTNAME_ARG is clientst0r's own host name."
    if [ -n "$CLIENTSTOR_IP" ]; then
        is_ip "$CLIENTSTOR_IP" || die "--clientstor-ip must be an IPv4 or IPv6 address"
    fi
    if [ -z "$TLS" ]; then TLS=existing-cert; fi
    case "$TLS" in
        existing-cert)
            CERT_FILE="${CERT_FILE:-/etc/ssl/clientst0r-office/$HOSTNAME_ARG.crt}"
            KEY_FILE="${KEY_FILE:-/etc/ssl/clientst0r-office/$HOSTNAME_ARG.key}" ;;
        certbot)
            [ -n "$CERTBOT_EMAIL" ] || die "--tls certbot needs --certbot-email (Let's Encrypt account e-mail)"
            CERT_FILE="/etc/letsencrypt/live/$HOSTNAME_ARG/fullchain.pem"
            KEY_FILE="/etc/letsencrypt/live/$HOSTNAME_ARG/privkey.pem" ;;
        none-behind-proxy) ;;
        *) die "--tls must be existing-cert, certbot or none-behind-proxy" ;;
    esac
    if [ -n "$CA_FILE" ]; then
        [ -f "$CA_FILE" ] || die "--ca-file $CA_FILE does not exist"
        if grep -q 'PRIVATE KEY' "$CA_FILE"; then die "--ca-file contains a private key; pass only CA certificates"; fi
        grep -q 'BEGIN CERTIFICATE' "$CA_FILE" || die "--ca-file is not a PEM certificate file"
        openssl x509 -noout -in "$CA_FILE" >/dev/null 2>&1 || die "--ca-file is not a valid PEM certificate"
    fi
    set_provider_facts
    if [ -n "$VERSION" ]; then
        [[ "$VERSION" =~ $VERSION_RE ]] || die "--version $VERSION is not a package version"
    fi
    case "$PROVIDER" in
        onlyoffice)
            VERSION="${VERSION:-$OO_DEFAULT_VERSION}"
            if dpkg --compare-versions "$VERSION" lt "$OO_MIN_VERSION"; then
                die "ONLYOFFICE Docs $VERSION is too old: clientst0r requires $OO_MIN_VERSION or later (WOPI SSRF and macro sandbox fixes)."
            fi ;;
        collabora-code)
            if [ -z "$VERSION" ]; then
                VERSION=$CO_CODE_VERSION; BRAND_VERSION="${BRAND_VERSION:-$CO_CODE_BRAND_VERSION}"
            fi
            [ -n "$BRAND_VERSION" ] || die "--brand-version is required with a non-default --version (the code-brand package version)" ;;
        collabora-online)
            [ -n "$VERSION" ] || die "--version is required for collabora-online (the coolwsd version in your subscription repository)"
            [ -n "$BRAND_VERSION" ] || die "--brand-version is required for collabora-online (the collabora-online-brand version)"
            [ -n "$REPO_URL_FILE" ] || die "--repo-url-file is required for collabora-online: a root-only file holding your subscription repository URL"
            check_secret_file_perms "$REPO_URL_FILE" ;;
    esac
    if [ -n "$BRAND_VERSION" ]; then
        [[ "$BRAND_VERSION" =~ $VERSION_RE ]] || die "--brand-version $BRAND_VERSION is not a package version"
    fi
    if [ -n "$KEY_FPR_OVERRIDE" ]; then
        [ "$PROVIDER" = collabora-online ] || die "--key-fingerprint is only accepted for collabora-online"
        KEY_FPR="$(printf '%s' "$KEY_FPR_OVERRIDE" | tr -d ' ' | tr '[:lower:]' '[:upper:]')"
        [[ "$KEY_FPR" =~ ^[0-9A-F]{40}$ ]] || die "--key-fingerprint must be a 40-hex-digit fingerprint"
    fi
}

check_secret_file_perms() {
    local f="$1" mode
    [ -f "$f" ] || die "$f does not exist"
    mode="$(stat -c '%a' "$f")"
    case "$mode" in
        600|400) ;;
        *) die "$f must be readable by its owner only (chmod 600); it is $mode" ;;
    esac
}

set_provider_facts() {
    case "$PROVIDER" in
        onlyoffice)
            PROVIDER_LABEL="ONLYOFFICE Docs"; CLIENTSTOR_PROVIDER=onlyoffice
            PKG=$OO_PKG; BRAND_PKG=""; PORT=$OO_PORT; KEY_URL=$OO_KEY_URL; KEY_FPR=$OO_KEY_FPR
            REPO_ORIGIN=$OO_REPO_ORIGIN; CONFLICTS=$OO_CONFLICTS
            MIN_CPU=2; MIN_RAM_MB=2048; MIN_DISK_GB=40; MIN_SWAP_MB=4096
            RES_SOURCE="ONLYOFFICE's published minimum" ;;
        collabora-code|collabora-online)
            PROVIDER_LABEL="Collabora Online"; CLIENTSTOR_PROVIDER=collabora
            [ "$PROVIDER" = collabora-code ] && PROVIDER_LABEL="Collabora Online Development Edition (CODE)"
            PKG=$CO_PKG; PORT=$CO_PORT; KEY_URL=$CO_KEY_URL; KEY_FPR=$CO_KEY_FPR
            REPO_ORIGIN=$CO_REPO_ORIGIN; CONFLICTS=$CO_CONFLICTS
            if [ "$PROVIDER" = collabora-code ]; then
                BRAND_PKG=$CO_CODE_BRAND; CONFLICTS="$CONFLICTS $CO_ONLINE_BRAND"
            else
                BRAND_PKG=$CO_ONLINE_BRAND; CONFLICTS="$CONFLICTS $CO_CODE_BRAND"
            fi
            # Collabora's own hardware page could not be verified; this is
            # clientst0r's conservative floor, not a vendor figure.
            MIN_CPU=2; MIN_RAM_MB=4096; MIN_DISK_GB=10; MIN_SWAP_MB=0
            RES_SOURCE="clientst0r's conservative floor (Collabora's published figures were not verified)" ;;
    esac
    SITE_NAME="clientst0r-office-$HOSTNAME_ARG.conf"
    PREF_FILE="/etc/apt/preferences.d/clientst0r-office-$PROVIDER.pref"
    KEYRING="$KEYRING_DIR/clientst0r-office-$PROVIDER.gpg"
    if [ "$PROVIDER" = onlyoffice ]; then
        SOURCE_FILE="/etc/apt/sources.list.d/clientst0r-office-$PROVIDER.list"
    else
        SOURCE_FILE="/etc/apt/sources.list.d/clientst0r-office-$PROVIDER.sources"
    fi
}

# --- Host probing ------------------------------------------------------------
FAILS=()
WARNS=()
fail_check() { FAILS+=("$1"); printf '  FAIL  %s\n' "$1"; }
warn_check() { WARNS+=("$1"); printf '  WARN  %s\n' "$1"; }
ok_check()   { printf '  ok    %s\n' "$1"; }

pkg_version() {  # installed version of $1, or empty
    local out
    out="$(dpkg-query -W -f='${Status} ${Version}' "$1" 2>/dev/null || true)"
    case "$out" in
        "install ok installed "*) printf '%s' "${out##* }" ;;
        *) printf '' ;;
    esac
}

meminfo_mb() {
    local key="$1" file
    file="$(p /proc/meminfo)"
    [ -r "$file" ] || file=/proc/meminfo
    awk -v k="$key:" '$1 == k { printf "%d", $2 / 1024 }' "$file"
}

listeners() {  # "port process" per listening TCP socket
    ss -Hltnp 2>/dev/null | awk '{
        n = split($4, a, ":"); port = a[n];
        proc = "-"; if (match($0, /users:\(\("[^"]+"/)) { proc = substr($0, RSTART + 9, RLENGTH - 10) }
        print port, proc }' || true
}

read_helper_conf() {
    local conf
    conf="$(p "$HELPER_CONF")"
    [ -r "$conf" ] || return 0
    if [ -z "$APP_USER" ]; then APP_USER="$(sed -n 's/^APP_USER=\([a-z_][a-z0-9_-]*\)$/\1/p' "$conf" | head -1)"; fi
    if [ -z "$APP_DIR" ]; then APP_DIR="$(sed -n 's|^APP_DIR=\(/[A-Za-z0-9._/-]*\)$|\1|p' "$conf" | head -1)"; fi
}

nginx_files() {
    local d
    for d in /etc/nginx/sites-enabled /etc/nginx/sites-available /etc/nginx/conf.d; do
        [ -d "$(p "$d")" ] || continue
        find "$(p "$d")" -maxdepth 1 \( -type f -o -type l \) 2>/dev/null
    done
}

detect_clientstor_sites() {
    # Any Nginx file that proxies to clientst0r, or names its host, is
    # clientst0r's own site: protected for the whole run.
    CLIENTSTOR_SITES=()
    local f real
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        case "$(basename "$f")" in clientst0r-office-*) continue ;; esac
        if grep -Eqs 'clientst0r_app|gunicorn\.sock' "$f" \
           || grep -Eqs "server_name[^;]*[[:space:]]${CLIENTSTOR_HOST//./\\.}([[:space:];]|$)" "$f"; then
            CLIENTSTOR_SITES+=("$f")
            protect "$f"
            real="$(readlink -f "$f" 2>/dev/null || true)"
            [ -n "$real" ] && protect "$real"
        fi
    done < <(nginx_files)
}

site_paths() {
    if [ -d "$(p /etc/nginx/sites-available)" ] || [ ! -d "$(p /etc/nginx/conf.d)" ]; then
        SITE_FILE="/etc/nginx/sites-available/$SITE_NAME"
        SITE_LINK="/etc/nginx/sites-enabled/$SITE_NAME"
    else
        SITE_FILE="/etc/nginx/conf.d/$SITE_NAME"
        SITE_LINK=""
    fi
}

# --- Preflight ---------------------------------------------------------------
preflight() {
    say "Preflight checks for $PROVIDER_LABEL ($MODE) on $(hostname 2>/dev/null || echo this host)"
    read_helper_conf
    if [ -n "$APP_DIR" ]; then protect "$(p "$APP_DIR")"; fi
    detect_clientstor_sites
    site_paths

    # OS
    local os_id="" os_ver="" arch
    if [ -r "$(p /etc/os-release)" ]; then
        os_id="$(sed -n 's/^ID=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p' "$(p /etc/os-release)" | head -1)"
        os_ver="$(sed -n 's/^VERSION_ID=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p' "$(p /etc/os-release)" | head -1)"
    fi
    case "$os_id $os_ver" in
        "ubuntu 22.04"|"debian 12")
            ok_check "OS $os_id $os_ver" ;;
        "ubuntu 24.04")
            if [ "$PROVIDER" = onlyoffice ]; then
                warn_check "Ubuntu 24.04 is not named on ONLYOFFICE's install page (it lists Debian 12 and Ubuntu 18.04 'or other compatible'). It is expected to work but is unverified; test before production."
            else
                ok_check "OS $os_id $os_ver"
            fi ;;
        "debian 13")
            warn_check "Debian 13 has not been tested with this installer." ;;
        *)
            fail_check "Unsupported OS '${os_id:-unknown} ${os_ver}'. Supported: Ubuntu 22.04/24.04, Debian 12." ;;
    esac
    if [[ "$PROVIDER" == collabora-* ]] && [ -n "$os_id" ]; then
        warn_check "Collabora's supported-distribution list could not be verified; check it for $os_id $os_ver."
    fi
    arch="$(dpkg --print-architecture 2>/dev/null || echo unknown)"
    case "$arch" in
        amd64) ok_check "Architecture amd64" ;;
        arm64) warn_check "arm64: vendor package availability for arm64 is unverified." ;;
        *) fail_check "Architecture $arch is not supported." ;;
    esac

    # Resources
    local cpu ram swap disk_kb disk_gb need_cpu need_ram need_disk res_fail=()
    cpu="$(nproc 2>/dev/null || echo 1)"
    ram="$(meminfo_mb MemTotal)"; ram="${ram:-0}"
    swap="$(meminfo_mb SwapTotal)"; swap="${swap:-0}"
    disk_kb="$(df -Pk "$(p /var)" 2>/dev/null | awk 'NR==2 {print $4}')"
    disk_gb=$(( ${disk_kb:-0} / 1024 / 1024 ))
    need_cpu=$MIN_CPU; need_ram=$MIN_RAM_MB; need_disk=$MIN_DISK_GB
    if [ "$MODE" = same-server ]; then
        # clientst0r, its database and Nginx keep running next to the editor.
        need_cpu=$(( need_cpu + 2 )); need_ram=$(( need_ram + 2048 )); need_disk=$(( need_disk + 10 ))
    fi
    info "CPU $cpu cores, RAM ${ram} MB, swap ${swap} MB, free disk on /var ${disk_gb} GB"
    info "Needed: $need_cpu cores, $need_ram MB RAM, $need_disk GB disk ($RES_SOURCE$([ "$MODE" = same-server ] && printf ' plus headroom for clientst0r'))"
    [ "$cpu" -ge "$need_cpu" ] || res_fail+=("CPU: $cpu cores, need $need_cpu")
    [ "$ram" -ge "$need_ram" ] || res_fail+=("RAM: $ram MB, need $need_ram MB")
    [ "$disk_gb" -ge "$need_disk" ] || res_fail+=("disk: $disk_gb GB free on /var, need $need_disk GB")
    if [ "$MIN_SWAP_MB" -gt 0 ] && [ "$swap" -lt "$MIN_SWAP_MB" ]; then
        warn_check "Swap is ${swap} MB; ONLYOFFICE recommends at least $MIN_SWAP_MB MB."
    fi
    if [ ${#res_fail[@]} -gt 0 ]; then
        local msg="Resources are short: ${res_fail[*]}."
        [ "$MODE" = same-server ] && msg="$msg Running the editor next to clientst0r on this server is not recommended: use a separate VM (--mode separate-server)."
        if [ "$ACCEPT_LOW" -eq 1 ]; then warn_check "$msg (accepted with --accept-low-resources)"; else fail_check "$msg"; fi
    else
        ok_check "Resources"
    fi

    # Ports
    local line port proc editor_installed="" reinstall=0
    editor_installed="$(pkg_version "$PKG")"
    [ -n "$editor_installed" ] && reinstall=1
    while read -r port proc; do
        [ -n "$port" ] || continue
        case "$port" in
            "$PORT")
                if [ "$reinstall" -eq 1 ]; then ok_check "Port $PORT is used by the installed $PKG"
                else fail_check "Port $PORT (the editor's port) is already in use by $proc"; fi ;;
            80|443)
                if [ "$proc" != nginx ] && [ "$TLS" != none-behind-proxy ]; then
                    fail_check "Port $port is used by '$proc', not Nginx. The editor's server block needs Nginx on 80/443."
                fi ;;
        esac
    done < <(listeners)
    if [ "$ACTION" = install ] && [ "$reinstall" -eq 1 ]; then
        fail_check "$PKG $editor_installed is already installed. Use --upgrade --version X to change versions, or --uninstall first."
    fi

    # Nginx and its sites
    local nginx_ver f
    nginx_ver="$(pkg_version nginx)"; [ -n "$nginx_ver" ] || nginx_ver="$(pkg_version nginx-extras)"
    if [ -n "$nginx_ver" ]; then
        ok_check "Nginx $nginx_ver installed"
        [ "$PROVIDER" = onlyoffice ] && info "ONLYOFFICE's package requires nginx >= 1.22; its install page says 1.30 (unverified which is right; test on this version)."
    else
        info "Nginx is not installed; it will be installed from the distribution."
    fi
    while IFS= read -r f; do
        [ -n "$f" ] && info "Existing Nginx config: ${f#"$ROOT"}"
    done < <(nginx_files)
    if [ ${#CLIENTSTOR_SITES[@]} -gt 0 ]; then
        for f in "${CLIENTSTOR_SITES[@]}"; do info "clientst0r's own site (never touched): ${f#"$ROOT"}"; done
    fi
    if [ "$MODE" = same-server ]; then
        if [ ${#CLIENTSTOR_SITES[@]} -eq 0 ] && [ -z "$APP_DIR" ]; then
            warn_check "clientst0r was not detected on this host (no root-helper.conf, no clientst0r Nginx site). Check --mode."
        fi
    fi
    local conflict=""
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        case "$(basename "$f")" in clientst0r-office-*) continue ;; esac
        if grep -Eqs "server_name[^;]*[[:space:]]${HOSTNAME_ARG//./\\.}([[:space:];]|$)" "$f"; then
            conflict="${f#"$ROOT"}"
        fi
    done < <(nginx_files)
    if [ -n "$conflict" ]; then
        local is_cs=0
        for f in "${CLIENTSTOR_SITES[@]+"${CLIENTSTOR_SITES[@]}"}"; do [ "${f#"$ROOT"}" = "$conflict" ] && is_cs=1; done
        if [ "$is_cs" -eq 1 ]; then
            fail_check "$HOSTNAME_ARG is served by clientst0r's own Nginx site ($conflict). The editor needs a dedicated host name and server block; this script never edits clientst0r's site."
        else
            fail_check "$HOSTNAME_ARG is already used by $conflict. Pick a dedicated host name for the editor."
        fi
    fi
    if [ -e "$(p "$SITE_FILE")" ] && ! grep -qF "$MARKER" "$(p "$SITE_FILE")"; then
        fail_check "$SITE_FILE exists and was not written by this script."
    fi
    if [ "$MODE" = same-server ] && [ "$TLS" = none-behind-proxy ]; then
        warn_check "same-server with --tls none-behind-proxy: make sure only your TLS proxy can reach port 80 for $HOSTNAME_ARG."
    fi

    # Package conflicts and other apps
    local c v
    for c in $CONFLICTS; do
        v="$(pkg_version "$c")"
        [ -z "$v" ] || fail_check "Conflicting package $c $v is installed."
    done
    if [ "$PROVIDER" = onlyoffice ] && [ -n "$(pkg_version "$CO_PKG")" ]; then
        warn_check "Collabora ($CO_PKG) is also installed on this host. Both can run side by side, but check resources."
    fi
    if [[ "$PROVIDER" == collabora-* ]] && [ -n "$(pkg_version "$OO_PKG")" ]; then
        warn_check "ONLYOFFICE ($OO_PKG) is also installed on this host. Both can run side by side, but check resources."
    fi
    v="$(pkg_version apache2)"
    [ -z "$v" ] || warn_check "apache2 $v is installed. It must not listen on 80/443."
    if command -v docker >/dev/null 2>&1; then
        local names
        names="$(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ' || true)"
        [ -z "$names" ] || info "Running containers: $names"
    fi

    # DNS and clientst0r address
    if getent hosts "$HOSTNAME_ARG" >/dev/null 2>&1; then
        ok_check "$HOSTNAME_ARG resolves"
    else
        warn_check "$HOSTNAME_ARG does not resolve from this host yet. Users' browsers must resolve it."
    fi
    if [ -z "$CLIENTSTOR_IP" ]; then
        CLIENTSTOR_IP="$(getent ahosts "$CLIENTSTOR_HOST" 2>/dev/null | awk '{print $1; exit}' || true)"
        if [ -n "$CLIENTSTOR_IP" ] && is_ip "$CLIENTSTOR_IP"; then
            info "clientst0r ($CLIENTSTOR_HOST) resolves to $CLIENTSTOR_IP; the editor may fetch from this address only."
        else
            CLIENTSTOR_IP=""
            fail_check "Cannot resolve $CLIENTSTOR_HOST from this host. Fix DNS or pass --clientstor-ip."
        fi
    fi

    # TLS material
    case "$TLS" in
        existing-cert)
            if [ -f "$(p "$CERT_FILE")" ] && [ -f "$(p "$KEY_FILE")" ]; then ok_check "Certificate $CERT_FILE"
            else fail_check "Certificate or key missing: put them at $CERT_FILE and $KEY_FILE (or pass --cert-file/--key-file, or use --tls certbot)."; fi ;;
        certbot) info "A Let's Encrypt certificate will be requested for $HOSTNAME_ARG (needs public DNS and port 80 reachable)." ;;
        none-behind-proxy) info "No TLS on this host: your proxy must serve https://$HOSTNAME_ARG and forward to port 80 here." ;;
    esac
    if [ "$PROVIDER" = onlyoffice ] && [ "$ACCEPT_EULA" -ne 1 ] && [ "$DRY_RUN" -eq 0 ] && [ "$PREFLIGHT_ONLY" -eq 0 ]; then
        fail_check "ONLYOFFICE needs ttf-mscorefonts-installer, which asks you to accept the Microsoft core fonts EULA. Read it, then add --accept-mscorefonts-eula."
    fi

    say ""
    if [ ${#FAILS[@]} -gt 0 ]; then
        say "Preflight FAILED (${#FAILS[@]} problem(s), ${#WARNS[@]} warning(s)). Nothing was changed."
        return 3
    fi
    say "Preflight passed with ${#WARNS[@]} warning(s)."
    return 0
}

# --- Repository and signing key ------------------------------------------------
TMPDIR_RUN=""
cleanup() { if [ -n "$TMPDIR_RUN" ]; then rm -rf -- "$TMPDIR_RUN"; fi; }
trap cleanup EXIT

fetch_and_verify_key() {
    TMPDIR_RUN="${TMPDIR_RUN:-$(mktemp -d)}"
    local raw="$TMPDIR_RUN/key.raw" bin="$TMPDIR_RUN/key.gpg" home="$TMPDIR_RUN/gnupg" colons pubs fpr
    mkdir -m 700 -p "$home"
    say "Fetching the signing key from $KEY_URL"
    curl -fsSL --proto '=https' --tlsv1.2 --max-time 60 -o "$raw" "$KEY_URL" \
        || die "Could not download the signing key from $KEY_URL"
    if grep -q -- '-----BEGIN PGP PUBLIC KEY BLOCK-----' "$raw" 2>/dev/null; then
        gpg --batch --quiet --homedir "$home" --dearmor -o "$bin" "$raw" || die "Could not read the signing key"
    else
        cp "$raw" "$bin"
    fi
    colons="$(gpg --batch --quiet --homedir "$home" --show-keys --with-colons "$bin" 2>/dev/null)" \
        || die "Could not read the signing key"
    pubs="$(printf '%s\n' "$colons" | grep -c '^pub:' || true)"
    [ "$pubs" = 1 ] || die "The downloaded keyring holds $pubs primary keys; expected exactly one. Not trusting it."
    fpr="$(printf '%s\n' "$colons" | awk -F: '/^pub:/ {want=1; next} want && /^fpr:/ {print $10; exit}')"
    if [ "$fpr" != "$KEY_FPR" ]; then
        die "Signing key fingerprint mismatch: expected $KEY_FPR, got ${fpr:-none}. Not trusting it; nothing was changed."
    fi
    say "Signing key fingerprint verified: $KEY_FPR"
    VERIFIED_KEY="$bin"
}

install_repo() {
    run install -d -m 0755 "$(p "$KEYRING_DIR")"
    write_file "$KEYRING" 0644 < "$VERIFIED_KEY"
    if [ "$PROVIDER" = onlyoffice ]; then
        printf '%s\ndeb [signed-by=%s] %s squeeze main\n' "$MARKER" "$KEYRING" "$OO_REPO_URI" \
            | write_file "$SOURCE_FILE" 0644
    elif [ "$PROVIDER" = collabora-code ]; then
        printf '%s\nTypes: deb\nURIs: %s\nSuites: ./\nSigned-By: %s\n' "$MARKER" "$CO_CODE_URI" "$KEYRING" \
            | write_file "$SOURCE_FILE" 0644
    else
        local uri
        uri="$(tr -d '[:space:]' < "$REPO_URL_FILE")"
        [[ "$uri" =~ ^https://[A-Za-z0-9./_~%+-]+$ ]] || die "$REPO_URL_FILE must hold one https:// repository URL"
        # The subscription URL embeds your customer key: keep the file root-only.
        printf '%s\nTypes: deb\nURIs: %s\nSuites: ./\nSigned-By: %s\n' "$MARKER" "$uri" "$KEYRING" \
            | write_file "$SOURCE_FILE" 0600
        REPO_ORIGIN="$(url_host "$uri")"
    fi
    write_pin
}

write_pin() {
    # Priority 1001 on the exact version: apt never picks another version of
    # the editor on its own, and `apt-mark hold` stops upgrades on top of
    # that. The vendor repository gets priority 100, so it cannot replace
    # distribution packages (nginx, curl, ...) either.
    {
        printf '%s\n# Editor upgrades are explicit only: %s --upgrade --version X\n\n' "$MARKER" "$SELF"
        printf 'Package: %s\nPin: version %s\nPin-Priority: 1001\n\n' "$PKG" "$VERSION"
        if [ -n "$BRAND_PKG" ]; then
            printf 'Package: %s\nPin: version %s\nPin-Priority: 1001\n\n' "$BRAND_PKG" "$BRAND_VERSION"
        fi
        printf 'Package: *\nPin: origin "%s"\nPin-Priority: 100\n' "$REPO_ORIGIN"
    } | write_file "$PREF_FILE" 0644
}

check_available() {
    local pkg="$1" ver="$2"
    if dry; then say "+ check that $pkg $ver is in the repository (apt-cache madison $pkg)"; return 0; fi
    apt-cache madison "$pkg" 2>/dev/null | awk -F'|' '{gsub(/ /, "", $2); print $2}' | grep -qxF "$ver" \
        || die "$pkg $ver is not available from the repository. Check --version (apt-cache madison $pkg)."
}

held_packages() {
    printf '%s\n' "$PKG"
    [ -z "$BRAND_PKG" ] || printf '%s\n' "$BRAND_PKG"
    if [[ "$PROVIDER" == collabora-* ]] && ! dry; then
        dpkg-query -W -f='${Package} ${Status}\n' 'collaboraoffice*' 2>/dev/null \
            | awk '$NF == "installed" {print $1}' || true
    fi
}

hold_packages() {
    local pkgs
    mapfile -t pkgs < <(held_packages)
    run apt-mark hold "${pkgs[@]}"
}

unhold_packages() {
    local pkgs
    mapfile -t pkgs < <(held_packages)
    run apt-mark unhold "${pkgs[@]}"
}

debconf_preseed() {
    # Values go through a pipe, never a command line. The JWT secret is
    # preseeded so the service never starts with the vendor's default secret.
    if dry; then
        say "+ preseed debconf: onlyoffice/ds-port=$OO_PORT, onlyoffice/jwt-enabled=true, onlyoffice/jwt-secret=(hidden)"
        [ "$ACCEPT_EULA" -eq 1 ] && say "+ preseed debconf: msttcorefonts/accepted-mscorefonts-eula=true"
        return 0
    fi
    {
        printf '%s onlyoffice/ds-port select %s\n' "$OO_PKG" "$OO_PORT"
        printf '%s onlyoffice/jwt-enabled boolean true\n' "$OO_PKG"
        printf '%s onlyoffice/jwt-secret password %s\n' "$OO_PKG" "$(cat "$(p "$SECRET_FILE")")"
        if [ "$ACCEPT_EULA" -eq 1 ]; then
            printf 'ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true\n'
        fi
    } | debconf-set-selections
    say "+ preseeded debconf (ds-port, jwt-enabled, jwt-secret hidden)"
}

install_packages() {
    export DEBIAN_FRONTEND=noninteractive
    run apt-get update -q
    check_available "$PKG" "$VERSION"
    [ -z "$BRAND_PKG" ] || check_available "$BRAND_PKG" "$BRAND_VERSION"
    local opts=(-y -q --no-install-recommends -o Dpkg::Options::=--force-confold)
    if [ "$PROVIDER" = onlyoffice ]; then
        debconf_preseed
        if [ -z "$(pkg_version nginx)" ] && [ -z "$(pkg_version nginx-extras)" ]; then
            run apt-get install "${opts[@]}" nginx
        fi
        run apt-get install "${opts[@]}" ttf-mscorefonts-installer
        run apt-get install "${opts[@]}" "$PKG=$VERSION"
    else
        if [ -z "$(pkg_version nginx)" ] && [ -z "$(pkg_version nginx-extras)" ]; then
            run apt-get install "${opts[@]}" nginx
        fi
        run apt-get install "${opts[@]}" "$PKG=$VERSION" "$BRAND_PKG=$BRAND_VERSION"
    fi
    hold_packages
}

# --- Secret --------------------------------------------------------------------
generate_secret() {
    if [ -s "$(p "$SECRET_FILE")" ]; then
        say "Keeping the existing secret in $SECRET_FILE"
        return 0
    fi
    if dry; then say "+ generate a 256-bit secret into $SECRET_FILE (mode 0600, root only; never printed)"; return 0; fi
    run install -d -m 0700 "$(p "$STATE_DIR")"
    # openssl prints to the pipe only; the value never reaches the terminal.
    openssl rand -hex 32 | write_file "$SECRET_FILE" 0600 root:root
}

write_state() {
    {
        printf '%s\n# Non-secret facts about this editor install; read by --upgrade/--uninstall.\n' "$MARKER"
        printf 'PROVIDER=%s\nMODE=%s\nHOSTNAME=%s\nCLIENTSTOR_URL=%s\nCLIENTSTOR_IP=%s\n' \
            "$PROVIDER" "$MODE" "$HOSTNAME_ARG" "$CLIENTSTOR_URL" "$CLIENTSTOR_IP"
        printf 'VERSION=%s\nBRAND_VERSION=%s\nTLS=%s\nSITE_FILE=%s\nSITE_LINK=%s\nCA=%s\n' \
            "$VERSION" "$BRAND_VERSION" "$TLS" "$SITE_FILE" "$SITE_LINK" "$([ -n "$CA_FILE" ] && echo 1 || echo 0)"
    } | write_file "$STATE_FILE" 0600 root:root
}

load_state() {
    local f
    f="$(p "$STATE_FILE")"
    [ -r "$f" ] || die "No install record at $STATE_FILE: this host has no editor installed by $SELF."
    local key val
    while IFS='=' read -r key val; do
        case "$key" in
            PROVIDER) PROVIDER="$val" ;;
            MODE) MODE="$val" ;;
            HOSTNAME) HOSTNAME_ARG="$val" ;;
            CLIENTSTOR_URL) CLIENTSTOR_URL="$val" ;;
            CLIENTSTOR_IP) CLIENTSTOR_IP="$val" ;;
            VERSION) INSTALLED_VERSION="$val" ;;
            BRAND_VERSION) INSTALLED_BRAND_VERSION="$val" ;;
            TLS) TLS="$val" ;;
            SITE_FILE) SITE_FILE="$val" ;;
            SITE_LINK) SITE_LINK="$val" ;;
            CA) STATE_CA="$val" ;;
        esac
    done < "$f"
    case "$PROVIDER" in onlyoffice|collabora-code|collabora-online) ;; *) die "Corrupt $STATE_FILE" ;; esac
    [[ "$HOSTNAME_ARG" =~ $HOST_RE ]] || die "Corrupt $STATE_FILE"
    CLIENTSTOR_HOST="$(url_host "$CLIENTSTOR_URL")"
    CLIENTSTOR_PORT="$(url_port "$CLIENTSTOR_URL")"
    CLIENTSTOR_ORIGIN="${CLIENTSTOR_URL%%://*}://${CLIENTSTOR_HOST}"
    if [ "$CLIENTSTOR_PORT" != 443 ] && [ "$CLIENTSTOR_PORT" != 80 ]; then
        CLIENTSTOR_ORIGIN="$CLIENTSTOR_ORIGIN:$CLIENTSTOR_PORT"
    fi
    set_provider_facts
}

write_import_file() {
    [ "$WRITE_IMPORT" -eq 1 ] || return 0
    local owner="root" name
    if [ "$MODE" = same-server ] && [ -n "$APP_USER" ]; then owner="$APP_USER"; fi
    name="import-$HOSTNAME_ARG.env"
    IMPORT_FILE="$IMPORT_DIR/$name"
    if dry; then
        say "+ write one-time import file $IMPORT_FILE (mode 0600, owner $owner; holds the secret)"
        return 0
    fi
    local dir
    dir="$(p "$IMPORT_DIR")"
    guard_path "$dir"
    if [ -L "$dir" ]; then die "$IMPORT_DIR is a symlink; refusing to write the import file."; fi
    mkdir -p "$dir"
    chmod 0700 "$dir"
    if [ "$owner" != root ] && [ -z "$ROOT" ]; then chown "$owner:" "$dir"; fi
    local tmp
    # mktemp creates the file exclusively, so nothing planted in the
    # directory can redirect the write.
    tmp="$(mktemp "$dir/.import.XXXXXX")"
    {
        printf '# clientst0r Office editor import file. CONTAINS A SECRET.\n'
        printf '# Import on the clientst0r server, as the clientst0r app user:\n'
        printf '#   manage.py office_setup --import-secret %s [--instance N]\n' "$IMPORT_FILE"
        printf '# The command stores the secret encrypted and shreds this file.\n'
        printf 'PROVIDER=%s\nEDITION=%s\nMODE=%s\nNAME=%s\n' "$CLIENTSTOR_PROVIDER" "$PROVIDER" "${MODE//-/_}" "$HOSTNAME_ARG"
        printf 'BROWSER_URL=%s\nINTERNAL_URL=%s\nCALLBACK_URL=%s\n' "$(browser_url)" "$(internal_url)" "$CLIENTSTOR_URL"
        printf 'SECRET=%s\n' "$(cat "$(p "$SECRET_FILE")")"
    } > "$tmp"
    chmod 0600 "$tmp"
    if [ "$owner" != root ] && [ -z "$ROOT" ]; then chown "$owner:" "$tmp"; fi
    mv -f "$tmp" "$dir/$name"
    say "+ wrote one-time import file $IMPORT_FILE (mode 0600, owner $owner)"
}

browser_url() {
    printf 'https://%s/' "$HOSTNAME_ARG"
}

internal_url() {
    # Same-server ONLYOFFICE: clientst0r may talk to the editor over loopback.
    # Collabora's discovery builds its URLs from the request host, so it is
    # always reached by its browser address.
    if [ "$MODE" = same-server ] && [ "$PROVIDER" = onlyoffice ]; then
        printf 'http://127.0.0.1:%s/' "$OO_PORT"
    fi
}

# --- Private CA (the CA that signed clientst0r's certificate) ------------------
install_ca() {
    [ -n "$CA_FILE" ] || return 0
    write_file "$CA_DEST" 0644 < "$CA_FILE"
    run update-ca-certificates
    if [ "$PROVIDER" = onlyoffice ]; then
        # ONLYOFFICE is Node.js; Node ignores the system store and reads
        # NODE_EXTRA_CA_CERTS (standard Node; not in ONLYOFFICE's docs, so
        # unverified for this product). The unit names after 9.4's process
        # consolidation are unverified too: every installed ds-* unit gets it.
        local unit units=()
        if dry; then units=("ds-*.service (each installed unit)"); else mapfile -t units < <(oo_units); fi
        [ ${#units[@]} -gt 0 ] || warn "No ds-* units found; set NODE_EXTRA_CA_CERTS=$CA_DEST for the ONLYOFFICE service by hand."
        for unit in "${units[@]}"; do
            if dry; then say "+ add NODE_EXTRA_CA_CERTS=$CA_DEST to $unit"; continue; fi
            printf '%s\n[Service]\nEnvironment=NODE_EXTRA_CA_CERTS=%s\n' "$MARKER" "$CA_DEST" \
                | write_file "/etc/systemd/system/$unit.d/clientst0r-office-ca.conf" 0644
        done
        run systemctl daemon-reload
    else
        write_file /etc/coolwsd/clientst0r-office-ca.pem 0644 < "$CA_FILE"
    fi
}

oo_units() {
    systemctl list-unit-files --no-legend --type=service 'ds-*' 2>/dev/null | awk '{print $1}' | grep -E '^ds-[a-z0-9-]+\.service$' || true
}

# --- Editor configuration -------------------------------------------------------
configure_onlyoffice() {
    say "Configuring $OO_LOCAL_JSON (JWT inbox/outbox/browser, request filtering, AI off)"
    if dry; then
        info "would set services.CoAuthoring.token.enable.{browser,request.inbox,request.outbox}=true"
        info "would set services.CoAuthoring.secret.{browser,inbox,outbox}.string=(the generated secret, hidden)"
        info "would set services.CoAuthoring.secret.session.string and storage.fs.secretString to new random values (hidden)"
        info "would set token.{inbox,outbox}.header=Authorization"
        info "would set request-filtering-agent: allowPrivateIPAddress=false, allowMetaIPAddress=false, allowIPAddressList=[${CLIENTSTOR_IP:-<clientst0r address>}]"
        info "would set aiSettings.enable=false"
        return 0
    fi
    local path
    path="$(p "$OO_LOCAL_JSON")"
    guard_path "$path"
    [ -f "$path" ] || die "$OO_LOCAL_JSON not found: did the package install?"
    python3 -I - "$path" "$(p "$SECRET_FILE")" "$CLIENTSTOR_IP" <<'PY'
import json, os, secrets, sys, tempfile
path, secret_file, ip = sys.argv[1:4]
with open(secret_file, encoding='ascii') as fh:
    secret = fh.read().strip()
with open(path, encoding='utf-8') as fh:
    data = json.load(fh)

def node(d, *keys):
    for k in keys:
        d = d.setdefault(k, {})
    return d

co = node(data, 'services', 'CoAuthoring')
enable = node(co, 'token', 'enable')
enable['browser'] = True
node(enable, 'request')['inbox'] = True
enable['request']['outbox'] = True
for side in ('inbox', 'outbox'):
    node(co, 'token', side)['header'] = 'Authorization'
for kind in ('browser', 'inbox', 'outbox'):
    node(co, 'secret', kind)['string'] = secret
node(co, 'secret', 'session')['string'] = secrets.token_hex(32)
rfa = node(co, 'request-filtering-agent')
rfa['allowPrivateIPAddress'] = False
rfa['allowMetaIPAddress'] = False
rfa['allowIPAddressList'] = [ip] if ip else []
node(data, 'storage', 'fs')['secretString'] = secrets.token_hex(32)
node(data, 'aiSettings')['enable'] = False
st = os.stat(path)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.clientst0r-office.')
with os.fdopen(fd, 'w', encoding='utf-8') as fh:
    json.dump(data, fh, indent=2)
    fh.write('\n')
os.chmod(tmp, st.st_mode & 0o7777)
try:
    os.chown(tmp, st.st_uid, st.st_gid)
except PermissionError:
    pass
os.replace(tmp, path)
PY
    say "+ updated $OO_LOCAL_JSON (owner and mode kept; secrets not shown)"
    info "Plugins, macros and the AI plugin are switched off per document by clientst0r's editor configuration (customization.plugins/macros/ai); local.json has no verified server-wide switch for them."
}

configure_collabora() {
    local ca=""
    if [ -n "$CA_FILE" ] || [ "${STATE_CA:-0}" = 1 ]; then ca=/etc/coolwsd/clientst0r-office-ca.pem; fi
    say "Configuring $CO_XML (WOPI host = clientst0r only, TLS at Nginx, frame-ancestors, external fetch off, macros off)"
    if dry; then
        info "would set storage.wopi.alias_groups mode=groups with one host: $CLIENTSTOR_ORIGIN:$CLIENTSTOR_PORT"
        info "would set ssl.enable=false, ssl.termination=true, net.listen=loopback"
        info "would set net.content_security_policy=\"frame-ancestors $CLIENTSTOR_ORIGIN;\""
        info "would empty net.lok_allow (no external data sources) and limit net.post_allow to loopback + ${CLIENTSTOR_IP:-<clientst0r address>}"
        info "would set security.enable_macros_execution=false, admin_console.enable=false, ai.enabled=false"
        [ -z "$ca" ] || info "would set storage.ssl.ca_file_path=$ca"
        [ -e "$(p "$CO_PROOF_KEY")" ] || say "+ coolconfig generate-proof-key"
        return 0
    fi
    local path
    path="$(p "$CO_XML")"
    guard_path "$path"
    [ -f "$path" ] || die "$CO_XML not found: did the package install?"
    python3 -I - "$path" "$CLIENTSTOR_ORIGIN:$CLIENTSTOR_PORT" "$CLIENTSTOR_ORIGIN" "${CLIENTSTOR_IP:-}" "$ca" <<'PY'
import os, sys, tempfile
import xml.etree.ElementTree as ET
path, wopi_host, origin, ip, ca = sys.argv[1:6]
tree = ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
root = tree.getroot()

def el(p):
    e = root.find(p)
    if e is None:
        parent = root
        for part in p.split('/'):
            nxt = parent.find(part)
            if nxt is None:
                nxt = ET.SubElement(parent, part)
            parent = nxt
        e = parent
    return e

def set_text(p, value):
    el(p).text = value

def clear_children(e, tag):
    for child in list(e):
        if child.tag == tag:
            e.remove(child)

set_text('ssl/enable', 'false')
set_text('ssl/termination', 'true')
set_text('net/listen', 'loopback')
set_text('net/content_security_policy', f'frame-ancestors {origin};')
lok = el('net/lok_allow')
clear_children(lok, 'host')
post = el('net/post_allow')
clear_children(post, 'host')
hosts = ['127.0.0.1/32', '::1/128']
if ip:
    hosts.append(ip + ('/128' if ':' in ip else '/32'))
for h in hosts:
    ET.SubElement(post, 'host', {'desc': 'clientst0r install-editor.sh'}).text = h
groups = el('storage/wopi/alias_groups')
groups.set('mode', 'groups')
clear_children(groups, 'group')
g = ET.SubElement(groups, 'group')
ET.SubElement(g, 'host', {'allow': 'true'}).text = wopi_host
set_text('security/enable_macros_execution', 'false')
set_text('admin_console/enable', 'false')
set_text('ai/enabled', 'false')
if ca:
    set_text('storage/ssl/ca_file_path', ca)
st = os.stat(path)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.clientst0r-office.')
os.close(fd)
tree.write(tmp, encoding='utf-8', xml_declaration=True)
os.chmod(tmp, st.st_mode & 0o7777)
try:
    os.chown(tmp, st.st_uid, st.st_gid)
except PermissionError:
    pass
os.replace(tmp, path)
PY
    say "+ updated $CO_XML (owner and mode kept)"
    if [ ! -e "$(p "$CO_PROOF_KEY")" ]; then
        run coolconfig generate-proof-key
    else
        info "Proof key already present ($CO_PROOF_KEY)"
    fi
}

# --- Nginx ---------------------------------------------------------------------
nginx_site() {
    local tls_mode="$1" var
    var="clientst0r_office_upgrade_$(printf '%s' "$HOSTNAME_ARG" | tr -c 'a-z0-9' '_')"
    printf '%s\n# Editor: %s  Host: %s\n# Only this file is managed; clientst0r'"'"'s own site is never edited.\n\n' \
        "$MARKER" "$PROVIDER_LABEL" "$HOSTNAME_ARG"
    printf 'map $http_upgrade $%s {\n    default upgrade;\n    %s close;\n}\n\n' "$var" "''"
    if [ "$tls_mode" = none-behind-proxy ]; then
        printf 'server {\n    listen 80;\n    listen [::]:80;\n    server_name %s;\n' "$HOSTNAME_ARG"
        printf '    # TLS ends at your proxy. Allow only the proxy, e.g.:\n    # allow 192.0.2.5; deny all;\n'
    elif [ "$tls_mode" = acme-only ]; then
        printf 'server {\n    listen 80;\n    listen [::]:80;\n    server_name %s;\n' "$HOSTNAME_ARG"
        printf '    location /.well-known/acme-challenge/ { root %s; }\n    location / { return 404; }\n}\n' "$ACME_DIR"
        return 0
    else
        printf 'server {\n    listen 80;\n    listen [::]:80;\n    server_name %s;\n' "$HOSTNAME_ARG"
        printf '    location /.well-known/acme-challenge/ { root %s; }\n' "$ACME_DIR"
        printf '    location / { return 301 https://$host$request_uri; }\n}\n\n'
        printf 'server {\n    listen 443 ssl;\n    listen [::]:443 ssl;\n    server_name %s;\n' "$HOSTNAME_ARG"
        printf '    ssl_certificate %s;\n    ssl_certificate_key %s;\n' "$CERT_FILE" "$KEY_FILE"
        printf '    ssl_protocols TLSv1.2 TLSv1.3;\n'
    fi
    printf '    client_max_body_size 200m;\n'
    printf '    add_header X-Content-Type-Options nosniff always;\n'
    printf '    access_log /var/log/nginx/clientst0r-office-access.log;\n'
    printf '    error_log /var/log/nginx/clientst0r-office-error.log;\n\n'
    local common
    common="$(printf '        proxy_http_version 1.1;\n        proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection $%s;\n        proxy_set_header Host $host;\n        proxy_set_header X-Forwarded-Host $host;\n        proxy_set_header X-Forwarded-Proto https;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_buffering off;\n' "$var")"
    if [ "$PROVIDER" = onlyoffice ]; then
        printf '    location / {\n        proxy_pass http://127.0.0.1:%s;\n%s\n        proxy_read_timeout 3600s;\n        proxy_send_timeout 3600s;\n    }\n' "$OO_PORT" "$common"
    else
        # Collabora 26.04 accepts /cool/ws and the legacy /cool/<doc>/ws; one
        # ^~ /cool/ block covers both. Community-reported layout: the
        # official SDK proxy page could not be read (unverified).
        local loc
        for loc in /browser /hosting/discovery /hosting/capabilities; do
            printf '    location ^~ %s {\n        proxy_pass http://127.0.0.1:%s;\n%s\n    }\n' "$loc" "$CO_PORT" "$common"
        done
        printf '    location ^~ /cool/ {\n        proxy_pass http://127.0.0.1:%s;\n%s\n        proxy_read_timeout 36000s;\n        proxy_send_timeout 36000s;\n    }\n' "$CO_PORT" "$common"
        printf '    location / { return 404; }\n'
    fi
    printf '}\n'
}

apply_nginx() {
    local content="$1" backup=""
    if [ -e "$(p "$SITE_FILE")" ] && ! dry; then
        backup="$(mktemp)"; cp "$(p "$SITE_FILE")" "$backup"
    fi
    printf '%s\n' "$content" | write_file "$SITE_FILE" 0644
    if [ -n "$SITE_LINK" ]; then
        guard_path "$(p "$SITE_LINK")"
        run ln -sfn "$SITE_FILE" "$(p "$SITE_LINK")"
    fi
    run install -d -m 0755 "$(p "$ACME_DIR")"
    if dry; then
        say "+ nginx -t && systemctl reload nginx"
        return 0
    fi
    if ! nginx -t >/dev/null 2>&1; then
        warn "nginx -t failed with the new editor site; restoring the previous state."
        if [ -n "$backup" ]; then cp "$backup" "$(p "$SITE_FILE")"; else
            rm -f -- "$(p "$SITE_FILE")"; [ -z "$SITE_LINK" ] || rm -f -- "$(p "$SITE_LINK")"; fi
        nginx -t || true
        die "Nginx rejected the configuration; nothing else was reloaded."
    fi
    [ -z "$backup" ] || rm -f -- "$backup"
    if systemctl is-active --quiet nginx; then run systemctl reload nginx; else run systemctl start nginx; fi
}

setup_tls_and_nginx() {
    site_paths
    case "$TLS" in
        certbot)
            if ! command -v certbot >/dev/null 2>&1; then run apt-get install -y -q certbot; fi
            apply_nginx "$(nginx_site acme-only)"
            run certbot certonly --webroot -w "$(p "$ACME_DIR")" -d "$HOSTNAME_ARG" --non-interactive \
                --agree-tos -m "$CERTBOT_EMAIL" --deploy-hook 'systemctl reload nginx'
            apply_nginx "$(nginx_site tls)" ;;
        existing-cert) apply_nginx "$(nginx_site tls)" ;;
        none-behind-proxy) apply_nginx "$(nginx_site none-behind-proxy)" ;;
    esac
}

restart_editor() {
    if [ "$PROVIDER" = onlyoffice ]; then
        local units=() u
        if dry; then say "+ systemctl restart ds-*.service (each installed unit)"; return 0; fi
        mapfile -t units < <(oo_units)
        [ ${#units[@]} -gt 0 ] || { warn "No ds-* units found to restart."; return 0; }
        for u in "${units[@]}"; do run systemctl restart "$u"; done
    else
        run systemctl enable coolwsd
        run systemctl restart coolwsd
    fi
}

# --- Health check ----------------------------------------------------------------
health_check() {
    say ""
    say "Health check"
    if dry; then
        if [ "$PROVIDER" = onlyoffice ]; then say "+ curl http://127.0.0.1:$OO_PORT/healthcheck (expects true)"
        else say "+ curl http://127.0.0.1:$CO_PORT/hosting/discovery (expects wopi-discovery)"; fi
        say "+ curl $(browser_url) through Nginx, and ${CLIENTSTOR_URL}health/ from this host"
        return 0
    fi
    local ok=0 waited=0 body
    while :; do
        if [ "$PROVIDER" = onlyoffice ]; then
            body="$(curl -fsS --max-time 10 "http://127.0.0.1:$OO_PORT/healthcheck" 2>/dev/null || true)"
            [ "$body" = true ] && ok=1
        else
            body="$(curl -fsS --max-time 10 "http://127.0.0.1:$CO_PORT/hosting/discovery" 2>/dev/null || true)"
            [[ "$body" == *wopi-discovery* ]] && ok=1
        fi
        [ "$ok" -eq 1 ] && break
        [ "$waited" -ge "$HEALTH_WAIT" ] && break
        sleep 5; waited=$(( waited + 5 ))
    done
    local rc=0
    if [ "$ok" -eq 1 ]; then ok_check "Editor service answers on 127.0.0.1"; else
        fail_check "Editor service did not answer within ${HEALTH_WAIT}s. Logs: $(log_hint)"; rc=1; fi
    local path=/healthcheck
    [ "$PROVIDER" = onlyoffice ] || path=/hosting/capabilities
    if [ "$TLS" = none-behind-proxy ]; then
        if curl -fsS --max-time 10 -o /dev/null -H "Host: $HOSTNAME_ARG" "http://127.0.0.1$path" 2>/dev/null; then
            ok_check "Nginx serves $HOSTNAME_ARG on port 80"
        else warn_check "Nginx did not serve $HOSTNAME_ARG on port 80"; fi
    elif curl -fsS --max-time 10 -o /dev/null --resolve "$HOSTNAME_ARG:443:127.0.0.1" "https://$HOSTNAME_ARG$path" 2>/dev/null; then
        ok_check "https://$HOSTNAME_ARG$path through Nginx (certificate verified)"
    else
        warn_check "https://$HOSTNAME_ARG$path through Nginx failed (certificate not trusted here, or Nginx not serving it)."
    fi
    local cacert=()
    [ -n "$CA_FILE" ] && cacert=(--cacert "$CA_FILE")
    if curl -fsS --max-time 10 -o /dev/null "${cacert[@]+"${cacert[@]}"}" "${CLIENTSTOR_URL}health/" 2>/dev/null; then
        ok_check "This host reaches clientst0r at ${CLIENTSTOR_URL} (editor -> clientst0r path)"
    else
        warn_check "This host could not reach ${CLIENTSTOR_URL}health/. Saves will fail until the editor can reach clientst0r (firewall, DNS, CA)."
    fi
    return "$rc"
}

log_hint() {
    if [ "$PROVIDER" = onlyoffice ]; then
        printf 'journalctl -u "ds-*" and /var/log/onlyoffice/documentserver/'
    else
        printf 'journalctl -u coolwsd'
    fi
}

print_values() {
    say ""
    say "=================================================================="
    say "$PROVIDER_LABEL is installed. Enter these in clientst0r:"
    say "Settings -> Integrations -> Office Documents -> Add instance"
    say "------------------------------------------------------------------"
    say "  Provider:      $PROVIDER_LABEL"
    say "  Mode:          $([ "$MODE" = same-server ] && echo 'Installed on this server' || echo 'Separate VM / server')"
    say "  Browser URL:   $(browser_url)"
    if [ -n "$(internal_url)" ]; then
        say "  Internal URL:  $(internal_url)   (optional: loopback, clientst0r is on this host)"
    else
        say "  Internal URL:  (leave empty)"
    fi
    say "  Callback URL:  $CLIENTSTOR_URL"
    if [ "$CLIENTSTOR_PROVIDER" = onlyoffice ]; then
        say "  Shared secret: the JWT secret in $SECRET_FILE (root only)."
    else
        say "  Shared secret: the random value in $SECRET_FILE (root only). Collabora itself"
        say "                 shares no secret with clientst0r: requests are signed with its"
        say "                 proof key (published in discovery). clientst0r's instance form"
        say "                 still requires a value for its own use."
    fi
    if [ "$TLS" = existing-cert ]; then
        say "  CA bundle:     only if $CERT_FILE is issued by a private CA: paste that CA"
        say "                 (the CA of the editor's certificate, not the --ca-file of clientst0r's)."
    fi
    say "------------------------------------------------------------------"
    if [ "$WRITE_IMPORT" -eq 1 ]; then
        say "Import the secret without pasting it (on the clientst0r server, as the app user):"
        if [ "$MODE" = separate-server ]; then
            say "  1. copy $IMPORT_FILE to the clientst0r server over SSH (scp), chmod 600,"
            say "     owned by the clientst0r app user; then delete it here: shred -u $IMPORT_FILE"
        fi
        say "  manage.py office_setup --import-secret $IMPORT_FILE"
        say "  (creates a disabled instance from the file, or add --instance N; the file is shredded)"
    else
        say "Paste the secret into the instance form: sudo cat $SECRET_FILE"
    fi
    say "Then run Health check, Diagnostics and the round-trip test, and enable the instance."
    if [ "$PROVIDER" = collabora-code ]; then
        say "NOTE: CODE is Collabora's development edition, for evaluation and testing, not production."
    fi
    say "=================================================================="
}

# --- Actions ---------------------------------------------------------------------
require_root() {
    if [ -z "$ROOT" ] && ! dry && [ "$(id -u)" -ne 0 ]; then
        die "Run as root (sudo). Use --dry-run or --preflight-only to look first."
    fi
}

do_install() {
    validate_install_args
    if [ "$PREFLIGHT_ONLY" -eq 0 ]; then require_root; fi
    local rc=0
    preflight || rc=$?
    if [ "$rc" -ne 0 ]; then exit "$rc"; fi
    [ "$PREFLIGHT_ONLY" -eq 0 ] || exit 0
    dry && say "" && say "DRY RUN: the actions below are printed only; nothing is changed."
    say ""
    fetch_and_verify_key
    install_repo
    generate_secret
    install_packages
    install_ca
    if [ "$PROVIDER" = onlyoffice ]; then configure_onlyoffice; else configure_collabora; fi
    restart_editor
    setup_tls_and_nginx
    write_state
    write_import_file
    local hrc=0
    health_check || hrc=$?
    print_values
    dry && say "DRY RUN complete: nothing was changed."
    return "$hrc"
}

do_upgrade() {
    [ -n "$VERSION" ] || die "--upgrade needs --version X (the exact package version to move to)"
    [[ "$VERSION" =~ $VERSION_RE ]] || die "--version $VERSION is not a package version"
    require_root
    load_state
    read_helper_conf
    if [ -n "$APP_DIR" ]; then protect "$(p "$APP_DIR")"; fi
    if [ "$PROVIDER" = onlyoffice ] && dpkg --compare-versions "$VERSION" lt "$OO_MIN_VERSION"; then
        die "ONLYOFFICE Docs $VERSION is too old: clientst0r requires $OO_MIN_VERSION or later."
    fi
    local cur
    cur="$(pkg_version "$PKG")"; cur="${cur:-$INSTALLED_VERSION}"
    if [ -n "$cur" ] && dpkg --compare-versions "$VERSION" le "$cur"; then
        die "$PKG $cur is installed; --upgrade only moves forward (asked for $VERSION)."
    fi
    if [ -n "$BRAND_PKG" ] && [ -z "$BRAND_VERSION" ]; then
        die "--brand-version is required to upgrade Collabora (the $BRAND_PKG version matching $VERSION)"
    fi
    say "Upgrade $PROVIDER_LABEL on $HOSTNAME_ARG: $PKG ${cur:-?} -> $VERSION"
    say ""
    say "DRAIN FIRST. Restarting the editor ends every open editing session. Before"
    say "upgrading, on the clientst0r server run:"
    say "    manage.py office_sessions --drain <instance id>"
    say "It asks the editor to save open documents, waits for sessions to close and"
    say "stops new ones on this instance. Re-enable it after the upgrade."
    say ""
    if [ "$CONFIRM_DRAINED" -ne 1 ] && ! dry; then
        if [ -t 0 ]; then
            local answer
            read -r -p "Type DRAINED once the instance is drained: " answer
            [ "$answer" = DRAINED ] || die "Not confirmed; nothing was changed."
        else
            die "Add --confirm-drained once the instance is drained; nothing was changed."
        fi
    fi
    fetch_and_verify_key
    install_repo
    export DEBIAN_FRONTEND=noninteractive
    run apt-get update -q
    check_available "$PKG" "$VERSION"
    [ -z "$BRAND_PKG" ] || check_available "$BRAND_PKG" "$BRAND_VERSION"
    unhold_packages
    local opts=(-y -q --no-install-recommends -o Dpkg::Options::=--force-confold)
    if [ -n "$BRAND_PKG" ]; then
        run apt-get install "${opts[@]}" "$PKG=$VERSION" "$BRAND_PKG=$BRAND_VERSION"
    else
        run apt-get install "${opts[@]}" "$PKG=$VERSION"
    fi
    hold_packages
    # Re-assert clientst0r's settings in case the package changed them.
    if [ "$PROVIDER" = onlyoffice ]; then configure_onlyoffice; else configure_collabora; fi
    restart_editor
    INSTALLED_VERSION=$VERSION; INSTALLED_BRAND_VERSION=$BRAND_VERSION
    write_state
    local hrc=0
    health_check || hrc=$?
    say ""
    say "Upgrade done. In clientst0r: run the instance's Health check (it records the new"
    say "version and capabilities), then: manage.py office_sessions --resume <instance id>"
    return "$hrc"
}

do_uninstall() {
    require_root
    load_state
    read_helper_conf
    if [ -n "$APP_DIR" ]; then protect "$(p "$APP_DIR")"; fi
    detect_clientstor_sites
    say "Uninstall $PROVIDER_LABEL from $HOSTNAME_ARG"
    say ""
    say "clientst0r's documents and every saved version live on the clientst0r server"
    say "(its media directory, office/revisions). No documents are stored on the editor."
    say "This uninstall removes the editor packages, its Nginx site and its apt source;"
    say "it never touches clientst0r's documents, versions, database, site or .env."
    say ""
    local pkgs
    mapfile -t pkgs < <(held_packages)
    if [ "$PROVIDER" = onlyoffice ]; then
        local units=() u
        if ! dry; then mapfile -t units < <(oo_units); fi
        for u in "${units[@]+"${units[@]}"}"; do run systemctl stop "$u"; done
    else
        run systemctl stop coolwsd
    fi
    run apt-mark unhold "${pkgs[@]}"
    run apt-get remove -y -q "${pkgs[@]}"
    [ -z "$SITE_LINK" ] || remove_path "$SITE_LINK"
    remove_path "$SITE_FILE"
    if dry; then say "+ nginx -t && systemctl reload nginx"
    elif nginx -t >/dev/null 2>&1; then
        if systemctl is-active --quiet nginx; then run systemctl reload nginx; fi
    else
        warn "nginx -t fails after removing the editor site; check the remaining Nginx configuration."
    fi
    remove_path "$PREF_FILE"
    remove_path "$SOURCE_FILE"
    remove_path "$KEYRING"
    local d
    for d in "$(p /etc/systemd/system)"/*.service.d/clientst0r-office-ca.conf; do
        [ -e "$d" ] || continue
        remove_path "${d#"$ROOT"}"
    done
    if [ "$PURGE_STATE" -eq 1 ]; then
        remove_path "$STATE_DIR"
        remove_path "$IMPORT_DIR"
        say "Removed $STATE_DIR (the secret). clientst0r's instance still holds its own encrypted copy."
    else
        say "Kept $STATE_DIR (install record and secret, root only). Remove it with --purge-state."
    fi
    say ""
    say "Uninstalled. In clientst0r, disable or remove the instance (documents stay)."
}

do_health() {
    load_state
    health_check
}

main() {
    local a
    for a in "$@"; do
        if [ "$a" = managed-local ]; then
            # A different install: no packages, a pinned container managed
            # by the Office service helper (docs/office/MANAGED_LOCAL.md).
            exec bash "$(dirname "$(realpath "$0")")/install-managed-local.sh" "$@"
        fi
    done
    parse_args "$@"
    case "$ACTION" in
        install) do_install ;;
        upgrade) do_upgrade ;;
        uninstall) do_uninstall ;;
        health) do_health ;;
    esac
}

main "$@"
