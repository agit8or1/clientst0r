#!/bin/bash
# Fix log file permissions for Clientst0r

LOG_DIR="/var/log/itdocs"
LOG_FILES=("vault.log" "django.log" "gunicorn-access.log" "gunicorn-error.log")

echo "Fixing log file permissions in ${LOG_DIR}..."

# Create log directory if it doesn't exist
if [ ! -d "$LOG_DIR" ]; then
    echo "Creating log directory..."
    sudo mkdir -p "$LOG_DIR"
fi

# Fix permissions for each log file
for log_file in "${LOG_FILES[@]}"; do
    log_path="${LOG_DIR}/${log_file}"

    # Create file if it doesn't exist
    if [ ! -f "$log_path" ]; then
        echo "Creating ${log_file}..."
        sudo touch "$log_path"
    fi

    # Set ownership to application user (pi or www-data)
    if id "pi" &>/dev/null; then
        echo "Setting ownership of ${log_file} to pi:pi..."
        sudo chown pi:pi "$log_path"
    elif id "www-data" &>/dev/null; then
        echo "Setting ownership of ${log_file} to www-data:www-data..."
        sudo chown www-data:www-data "$log_path"
    else
        echo "Warning: Could not determine application user"
    fi

    # Set permissions to allow writing
    echo "Setting permissions of ${log_file} to 664..."
    sudo chmod 664 "$log_path"
done

echo ""
echo "Log file permissions fixed!"
echo ""
echo "Current permissions:"
ls -la "$LOG_DIR"

echo ""
echo "You can now run: sudo tail -f ${LOG_DIR}/vault.log"
