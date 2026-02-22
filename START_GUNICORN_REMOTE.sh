#!/bin/bash
echo "=== Starting Gunicorn on Remote System ==="
echo ""

cd /home/administrator/huduglue

# Check if systemd service exists
if systemctl list-units --all | grep -q "clientst0r-gunicorn"; then
    echo "Found systemd service, starting..."
    sudo systemctl start clientst0r-gunicorn.service
    sudo systemctl status clientst0r-gunicorn.service
else
    echo "No systemd service, starting gunicorn manually..."
    
    # Activate venv
    if [ -d "venv" ]; then
        source venv/bin/activate
    elif [ -d "ENV" ]; then
        source ENV/bin/activate
    else
        echo "ERROR: No venv found!"
        exit 1
    fi
    
    # Start gunicorn
    gunicorn --workers 4 \
        --bind 0.0.0.0:8000 \
        --timeout 120 \
        --access-logfile /var/log/itdocs/gunicorn-access.log \
        --error-logfile /var/log/itdocs/gunicorn-error.log \
        --log-level info \
        --daemon \
        config.wsgi:application
    
    sleep 2
    
    # Verify it started
    if ps aux | grep -q '[g]unicorn.*master'; then
        echo "✓ Gunicorn started successfully!"
        ps aux | grep '[g]unicorn' | head -3
    else
        echo "✗ Failed to start gunicorn"
        exit 1
    fi
fi

echo ""
echo "=== SUCCESS ==="
echo ""
echo "Gunicorn is now running."
echo "Access the web interface and check Settings → System Updates"
echo ""
