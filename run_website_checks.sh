#!/bin/bash
# Website monitoring cron script
# Add to crontab: */15 * * * * /home/administrator/run_website_checks.sh

cd /home/administrator
source venv/bin/activate
python manage.py check_websites >> /var/log/huduglue_monitor.log 2>&1
