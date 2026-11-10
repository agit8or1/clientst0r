#!/bin/bash
# Check for update trigger file and run update if it exists
# This runs via cron every minute
#
# The trigger lives inside this install (not in /tmp, where any local user
# could create it) and must belong to the user the install runs as. The
# update itself is the verified pipeline (scripts/auto_update.sh ->
# manage.py upgrade_apply --auto).

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRIGGER_FILE="$BASE_DIR/.update-trigger"
UPDATE_SCRIPT="$BASE_DIR/scripts/auto_update.sh"
LOG_FILE="/var/log/clientst0r/triggered-update.log"

# Check if trigger file exists
if [ -f "$TRIGGER_FILE" ] && [ -O "$TRIGGER_FILE" ]; then
    echo "[$(date)] Trigger file found, starting update..." >> "$LOG_FILE"

    # Remove trigger file first
    rm -f "$TRIGGER_FILE"

    # Run the update script
    cd "$BASE_DIR" || exit 1
    bash "$UPDATE_SCRIPT" >> "$LOG_FILE" 2>&1

    echo "[$(date)] Update completed" >> "$LOG_FILE"
fi
