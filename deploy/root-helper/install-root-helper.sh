#!/bin/bash
# One-time setup of the Client St0r root helper (v3.17.597). Run as root:
#
#     sudo bash <app dir>/deploy/root-helper/install-root-helper.sh
#
# or use Settings → Updates → "Install root helper", which runs this with the
# sudo password you enter. After this, every root-level action and every later
# change to root-owned config goes through the helper automatically; nothing
# here needs running again.
#
# What it does:
#   1. installs /usr/local/sbin/clientst0r-root-helper (root-owned)
#   2. writes /etc/clientst0r/root-helper.conf and allowed_signers
#   3. adds the single sudoers rule that lets the app user run the helper
#   4. runs `apply-system-config`, which comments out the old passwordless
#      sudo rules that allowed a way to root
#   5. replaces the helper with the copy from this release's signed tag
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
APP_DIR="$(cd "$SRC_DIR/../.." && pwd)"
APP_USER="${CLIENTST0R_APP_USER:-${SUDO_USER:-$(stat -c %U "$APP_DIR")}}"
SERVICE="${CLIENTST0R_SERVICE_NAME:-clientst0r-gunicorn.service}"
REPO_URL="${CLIENTST0R_REPO_URL:-https://github.com/agit8or1/clientst0r.git}"
HELPER=/usr/local/sbin/clientst0r-root-helper

if [ "$APP_USER" = "root" ] || ! id "$APP_USER" >/dev/null 2>&1; then
    echo "Could not work out the app user (got '$APP_USER')." >&2
    echo "Set it explicitly: sudo CLIENTST0R_APP_USER=<user> bash $0" >&2
    exit 1
fi
for f in "$SRC_DIR/clientst0r-root-helper" "$SRC_DIR/allowed_signers"; do
    [ -f "$f" ] || { echo "Missing $f" >&2; exit 1; }
done

echo "Installing the Client St0r root helper for user '$APP_USER' ($APP_DIR)"

install -d -m 0755 -o root -g root /etc/clientst0r
umask 022
cat > /etc/clientst0r/root-helper.conf <<EOF
# Read by $HELPER. Root-owned on purpose: the app user must not be able
# to change which directory, user or repository the helper trusts.
APP_USER=$APP_USER
APP_DIR=$APP_DIR
SERVICE=$SERVICE
REPO_URL=$REPO_URL
EOF
chown root:root /etc/clientst0r/root-helper.conf
chmod 0644 /etc/clientst0r/root-helper.conf
install -m 0644 -o root -g root "$SRC_DIR/allowed_signers" /etc/clientst0r/allowed_signers

python3 -I -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$SRC_DIR/clientst0r-root-helper"
install -m 0755 -o root -g root "$SRC_DIR/clientst0r-root-helper" "$HELPER"

# apply-system-config writes the helper's own sudoers rule (validated with
# visudo) and disables the unsafe old ones.
"$HELPER" apply-system-config

VERSION="$(sed -n "s/^VERSION = '\(.*\)'/\1/p" "$APP_DIR/config/version.py")"
if "$HELPER" self-update "v$VERSION"; then
    :
else
    echo "Note: could not verify a signed v$VERSION tag. The helper installed from" >&2
    echo "this directory stays in place and updates itself at the next signed release." >&2
fi

echo
echo "Done. The app now runs root actions only through $HELPER."
