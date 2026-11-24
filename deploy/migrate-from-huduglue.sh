#!/bin/bash
# Migrate a running Clientst0r install to the canonical `clientst0r-*`
# systemd unit names.
#
# WHAT THIS DOES:
#   1. Installs all clientst0r-* unit files from deploy/
#   2. Stops + disables + removes legacy huduglue-* units
#   3. Stops + disables + removes obsolete itdocs-* units (gunicorn,
#      scheduler, monitor, psa-sync) — replaced by clientst0r-*
#      equivalents (scheduler was renamed; monitor/psa-sync were
#      duplicates; gunicorn is now clientst0r-gunicorn)
#   4. Enables + starts the new clientst0r-* equivalents
#   5. Reloads systemd
#   6. Reports the new active state
#
# This is a ONE-SHOT migration. Safe to re-run (idempotent).
#
# Run from the project root:
#   sudo bash deploy/migrate-from-huduglue.sh

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Must run as root (sudo)."
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$PROJECT_DIR/deploy"
SYSTEMD_DIR="/etc/systemd/system"

echo "═══════════════════════════════════════════════════════════"
echo " Clientst0r — legacy → clientst0r systemd unit migration"
echo "═══════════════════════════════════════════════════════════"
echo "Project:  $PROJECT_DIR"
echo ""

# Every clientst0r-* unit we ship in deploy/. Installed unconditionally.
NEW_UNITS=(
    clientst0r-gunicorn.service
    clientst0r-auto-update.service
    clientst0r-auto-update.timer
    clientst0r-breach-scan.service
    clientst0r-breach-scan.timer
    clientst0r-monitor.service
    clientst0r-monitor.timer
    clientst0r-psa-sync.service
    clientst0r-psa-sync.timer
    clientst0r-rmm-sync.service
    clientst0r-rmm-sync.timer
    clientst0r-scheduler.service
    clientst0r-scheduler.timer
)

# Legacy units to stop / disable / remove. Two eras:
#   - huduglue-*  → predecessor of clientst0r-* (renamed in v3.17.492)
#   - itdocs-*    → older install lane; gunicorn redundant; scheduler
#                   renamed to clientst0r-scheduler; monitor/psa-sync
#                   were duplicates of clientst0r-* (v3.17.494)
LEGACY_UNITS=(
    huduglue-gunicorn.service
    huduglue-auto-update.service
    huduglue-auto-update.timer
    huduglue-breach-scan.service
    huduglue-breach-scan.timer
    huduglue-monitor.service
    huduglue-monitor.timer
    huduglue-psa-sync.service
    huduglue-psa-sync.timer
    huduglue-rmm-sync.service
    huduglue-rmm-sync.timer
    itdocs-gunicorn.service
    itdocs-scheduler.service
    itdocs-scheduler.timer
    itdocs-monitor.service
    itdocs-monitor.timer
    itdocs-psa-sync.service
    itdocs-psa-sync.timer
)

# Timers to enable + start after install
ENABLE_ORDER=(
    clientst0r-gunicorn.service
    clientst0r-auto-update.timer
    clientst0r-breach-scan.timer
    clientst0r-monitor.timer
    clientst0r-psa-sync.timer
    clientst0r-rmm-sync.timer
    clientst0r-scheduler.timer
)

echo "→ Installing new clientst0r-* unit files..."
for unit in "${NEW_UNITS[@]}"; do
    src="$DEPLOY/$unit"
    dst="$SYSTEMD_DIR/$unit"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        chmod 0644 "$dst"
        echo "    installed $unit"
    else
        echo "    (skip) $unit not found in $DEPLOY"
    fi
done

systemctl daemon-reload

echo ""
echo "→ Stopping + disabling + removing legacy units..."
for unit in "${LEGACY_UNITS[@]}"; do
    if [ -f "$SYSTEMD_DIR/$unit" ] || \
       systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q .; then
        echo "    handling $unit"
        systemctl stop "$unit" 2>/dev/null || true
        systemctl disable "$unit" 2>/dev/null || true
        rm -f "$SYSTEMD_DIR/$unit"
    fi
done
# Clean up any *.backup file that lingers (huduglue-gunicorn.service.backup
# has been observed in the wild)
rm -f "$SYSTEMD_DIR/huduglue-gunicorn.service.backup"
# Clear cached failure state for any of the legacy unit names
systemctl reset-failed 2>/dev/null || true

systemctl daemon-reload

echo ""
echo "→ Enabling + starting clientst0r-* units..."
for unit in "${ENABLE_ORDER[@]}"; do
    if [ -f "$SYSTEMD_DIR/$unit" ]; then
        systemctl enable "$unit" 2>&1 | sed 's/^/    /'
        systemctl restart "$unit" 2>&1 | sed 's/^/    /' || true
    fi
done

systemctl daemon-reload

echo ""
echo "→ Active units after migration:"
systemctl list-units --type=service,timer --no-legend --no-pager 'clientst0r-*' 2>&1 | sed 's/^/    /'

echo ""
echo "✓ Migration complete."
echo "  Smoke test:  curl -fsSL http://localhost:8000/health/"
