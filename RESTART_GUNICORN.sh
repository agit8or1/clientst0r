#!/bin/bash
###############################################################################
# Restart Gunicorn on Systems Not Using Systemd
###############################################################################

echo "Checking for gunicorn processes..."
PIDS=$(ps aux | grep '[g]unicorn.*master' | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo "No gunicorn processes found!"
    echo "You may need to start gunicorn manually."
    exit 1
fi

echo "Found gunicorn master process(es): $PIDS"
echo ""
echo "Sending HUP signal to reload workers..."

for PID in $PIDS; do
    kill -HUP $PID
    echo "✓ Sent HUP to PID $PID"
done

echo ""
echo "✓ Gunicorn workers reloaded!"
echo ""
echo "New workers will now serve the updated code."
