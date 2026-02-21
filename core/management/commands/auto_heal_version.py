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
            service_names = ['clientst0r-gunicorn.service', 'clientst0r-gunicorn.service', 'itdocs-gunicorn.service']
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

            # Restart services with full cleanup
            self.stdout.write('Stopping service...')
            subprocess.run(['sudo', 'systemctl', 'stop', gunicorn_service], check=True)

            self.stdout.write('Killing lingering processes...')
            subprocess.run(['sudo', 'pkill', '-9', '-f', 'gunicorn'], check=False)

            import time
            time.sleep(2)

            self.stdout.write('Clearing Python cache...')
            subprocess.run([
                'find', str(settings.BASE_DIR), '-type', 'd', '-name', '__pycache__',
                '-not', '-path', '*/venv/*', '-exec', 'rm', '-rf', '{}', '+'
            ], check=False)

            self.stdout.write('Starting service...')
            subprocess.run(['sudo', 'systemctl', 'start', gunicorn_service], check=True)

            time.sleep(3)

            # Verify service started
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', gunicorn_service],
                capture_output=True,
                text=True
            )

            if result.stdout.strip() == 'active':
                self.stdout.write(self.style.SUCCESS(f'✓ Auto-heal complete! Service restarted.'))
                self.stdout.write(self.style.SUCCESS(f'✓ Version {file_version} should now be running'))
            else:
                self.stdout.write(self.style.ERROR('✗ Service failed to start'))
                sys.exit(1)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Auto-heal failed: {e}'))
            sys.exit(1)
