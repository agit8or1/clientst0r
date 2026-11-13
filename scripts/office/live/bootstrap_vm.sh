#!/usr/bin/env bash
# Root bootstrap for the OPTIONAL disposable-VM profile of the Office live
# checks (docs/office/LIVE_VERIFICATION.md, "VM profile"). Not needed, and
# refused, for the default local profile on a live install.
#
#   sudo bash bootstrap_vm.sh --i-understand-this-is-disposable [options]
#
# What it does (each step idempotent, each printed before it runs):
#   1. checks the machine: Ubuntu 24.04, >= 4 vCPU, >= 8 GB RAM, >= 40 GB free
#      on /var (warnings unless --strict);
#   2. writes the root-owned marker /etc/clientst0r/livecheck-disposable
#      (DISPOSABLE=yes) that the harness's VM guard requires;
#   3. --production-pattern P (repeatable): adds P to
#      /etc/clientst0r/livecheck-production-patterns (the guard refuses names
#      that match);
#   4. --allow-untested: sets ALLOW_UNTESTED_RELEASES=yes in
#      /etc/clientst0r/office-service.conf (only if that file exists, i.e.
#      after install-editor.sh --mode managed-local);
#   5. --browser-deps PYTHON: installs Chromium's system libraries with
#      `PYTHON -m playwright install-deps chromium` (apt);
#   6. --resume-unit APP_USER APP_DIR APP_PYTHON: a oneshot systemd unit that
#      runs `run_live_checks.py resume` as APP_USER after boot, so the
#      reboot step continues by itself.
#   --remove undoes 2, 3 and 6.
#
# It never installs or reconfigures Docker, nginx or the firewall: the
# product's own installer (install-editor.sh --mode managed-local
# [--install-docker]) does that, and is part of what the run verifies.
set -euo pipefail

MARKER=/etc/clientst0r/livecheck-disposable
PATTERNS=/etc/clientst0r/livecheck-production-patterns
CONF=/etc/clientst0r/office-service.conf
UNIT=/etc/systemd/system/clientst0r-livecheck-resume.service

die() { echo "bootstrap_vm: $*" >&2; exit 1; }
say() { echo "== $*"; }

confirm=0 strict=0 allow_untested=0 remove=0 browser_py='' unit_user='' unit_dir='' unit_py=''
patterns=()
while [ $# -gt 0 ]; do
  case "$1" in
    --i-understand-this-is-disposable) confirm=1 ;;
    --strict) strict=1 ;;
    --allow-untested) allow_untested=1 ;;
    --production-pattern) [ $# -ge 2 ] || die "--production-pattern needs a value"; patterns+=("$2"); shift ;;
    --browser-deps) [ $# -ge 2 ] || die "--browser-deps needs a python"; browser_py="$2"; shift ;;
    --resume-unit) [ $# -ge 4 ] || die "--resume-unit needs APP_USER APP_DIR APP_PYTHON"
                   unit_user="$2"; unit_dir="$3"; unit_py="$4"; shift 3 ;;
    --remove) remove=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "unknown option $1" ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] || die "run as root"
[ "$confirm" = 1 ] || die "this marks the machine as disposable: pass --i-understand-this-is-disposable"

if [ "$remove" = 1 ]; then
  say "removing the disposable marker, patterns and resume unit"
  rm -f "$MARKER" "$PATTERNS"
  if [ -f "$UNIT" ]; then systemctl disable clientst0r-livecheck-resume.service >/dev/null 2>&1 || true; rm -f "$UNIT"; systemctl daemon-reload; fi
  exit 0
fi

# 1. the machine
problems=()
. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || problems+=("OS is ${PRETTY_NAME:-unknown}, expected Ubuntu 24.04")
[ "$(nproc)" -ge 4 ] || problems+=("$(nproc) vCPU, expected >= 4")
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
[ "$mem_mb" -ge 7600 ] || problems+=("${mem_mb} MB RAM, expected >= 8 GB")
free_gb=$(df -BG --output=avail /var | tail -1 | tr -dc 0-9)
[ "$free_gb" -ge 40 ] || problems+=("${free_gb} GB free on /var, expected >= 40 GB")
for p in "${problems[@]}"; do echo "warning: $p"; done
[ "$strict" = 0 ] || [ ${#problems[@]} = 0 ] || die "machine requirements not met (--strict)"

# 2. marker
say "writing $MARKER"
install -d -m 0755 /etc/clientst0r
printf '# Written by scripts/office/live/bootstrap_vm.sh on %s.\n# This VM is disposable: the Office live checks may install, restart,\n# update, roll back and uninstall the managed editor and reboot it.\nDISPOSABLE=yes\n' \
  "$(date -u +%FT%TZ)" > "$MARKER.tmp"
chown root:root "$MARKER.tmp"; chmod 0644 "$MARKER.tmp"; mv -f "$MARKER.tmp" "$MARKER"

# 3. production patterns
if [ ${#patterns[@]} -gt 0 ]; then
  say "adding production patterns to $PATTERNS"
  touch "$PATTERNS"; chown root:root "$PATTERNS"; chmod 0644 "$PATTERNS"
  for p in "${patterns[@]}"; do grep -qxF -- "$p" "$PATTERNS" || echo "$p" >> "$PATTERNS"; done
fi

# 4. untested releases on this VM only
if [ "$allow_untested" = 1 ]; then
  [ -f "$CONF" ] || die "$CONF does not exist yet: run install-editor.sh --mode managed-local first"
  say "setting ALLOW_UNTESTED_RELEASES=yes in $CONF"
  if grep -q '^ALLOW_UNTESTED_RELEASES=' "$CONF"; then
    sed -i 's/^ALLOW_UNTESTED_RELEASES=.*/ALLOW_UNTESTED_RELEASES=yes/' "$CONF"
  else
    echo 'ALLOW_UNTESTED_RELEASES=yes' >> "$CONF"
  fi
fi

# 5. Chromium system libraries
if [ -n "$browser_py" ]; then
  [ -x "$browser_py" ] || die "$browser_py is not executable"
  say "installing Chromium system libraries ($browser_py -m playwright install-deps chromium)"
  "$browser_py" -m playwright install-deps chromium
fi

# 6. resume after reboot
if [ -n "$unit_user" ]; then
  id "$unit_user" >/dev/null 2>&1 || die "no user $unit_user"
  [ -f "$unit_dir/scripts/office/live/run_live_checks.py" ] || die "$unit_dir is not a clientst0r app directory"
  [ -x "$unit_py" ] || die "$unit_py is not executable"
  say "installing $UNIT"
  cat > "$UNIT" <<EOF
[Unit]
Description=clientst0r Office live checks: resume after reboot (disposable VM only)
After=network-online.target docker.service clientst0r-gunicorn.service
Wants=network-online.target
ConditionPathExists=$MARKER

[Service]
Type=oneshot
User=$unit_user
WorkingDirectory=$unit_dir
ExecStart=$unit_py $unit_dir/scripts/office/live/run_live_checks.py resume
TimeoutStartSec=6h

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable clientst0r-livecheck-resume.service >/dev/null
fi
say "done"
