"""
Auto-heal version mismatch by restarting services if needed.
This command detects the bootstrap problem (git ahead of running version)
and automatically restarts services to load new code.

Usage:
  python manage.py auto_heal_version

Can be run via cron every 5 minutes:
  */5 * * * * cd /home/administrator && venv/bin/python manage.py auto_heal_version >> /var/log/clientst0r/auto-heal.log 2>&1
"""
import subprocess
import sys
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from config.version import VERSION


class Command(BaseCommand):
    help = 'Auto-heal version mismatch by restarting services when git is ahead'

    def handle(self, *args, **options):
        try:
            # Get git commit version from version.py file on disk
            version_file = Path(settings.BASE_DIR) / 'config' / 'version.py'
            with open(version_file, 'r') as f:
                file_content = f.read()
                for line in file_content.split('\n'):
                    if line.strip().startswith('VERSION ='):
                        file_version = line.split("'")[1]
                        break

            # Get currently running version
            running_version = VERSION

            self.stdout.write(f"File version: {file_version}")
            self.stdout.write(f"Running version: {running_version}")

            # If versions match, everything is fine
            if file_version == running_version:
                self.stdout.write(self.style.SUCCESS('✓ Versions match - no action needed'))
                return

            # MISMATCH DETECTED - Bootstrap problem!
            self.stdout.write(self.style.WARNING(f'⚠ Version mismatch detected!'))
            self.stdout.write(self.style.WARNING(f'  File: {file_version}'))
            self.stdout.write(self.style.WARNING(f'  Running: {running_version}'))
            self.stdout.write('Starting auto-heal process...')

            # Detect which service is running
            service_names = ['clientst0r-gunicorn.service']
            gunicorn_service = None

            for service in service_names:
                result = subprocess.run(
                    ['systemctl', 'list-unit-files', service],
                    capture_output=True,
                    text=True
                )
                if service in result.stdout:
                    gunicorn_service = service
                    break

            if not gunicorn_service:
                self.stdout.write(self.style.ERROR('✗ No gunicorn service found'))
                sys.exit(1)

            self.stdout.write(f'Using service: {gunicorn_service}')

            # Schedule restart via systemd-run --system so the timer lives in
            # the system D-Bus scope and fires even if the launching process
            # (gunicorn worker) exits first.  This avoids the suicide problem
            # where stop+pkill kills the process running this command.
            import shutil
            systemd_run = shutil.which('systemd-run')
            systemctl = shutil.which('systemctl') or 'systemctl'

            if systemd_run:
                self.stdout.write('Scheduling restart via systemd-run --system (3-second delay)...')
                result = subprocess.run(
                    ['sudo', systemd_run, '--on-active=3', '--system',
                     systemctl, 'restart', gunicorn_service],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    self.stdout.write(self.style.SUCCESS(
                        f'✓ Restart of {gunicorn_service} scheduled. '
                        f'Service will reload version {file_version} in ~2 seconds.'
                    ))
                    return
                else:
                    self.stdout.write(self.style.WARNING(
                        f'systemd-run failed ({result.stderr.strip()}), falling back to nohup...'
                    ))

            # Fallback: nohup detached restart (survives parent process death)
            self.stdout.write('Scheduling restart via nohup (3-second delay)...')
            import os
            subprocess.Popen(
                ['sudo', systemctl, 'restart', gunicorn_service],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True,
                preexec_fn=lambda: __import__('time').sleep(3)
            )
            self.stdout.write(self.style.SUCCESS(
                f'✓ Restart of {gunicorn_service} scheduled via nohup. '
                f'Service will reload version {file_version} in ~3 seconds.'
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Auto-heal failed: {e}'))
            sys.exit(1)
