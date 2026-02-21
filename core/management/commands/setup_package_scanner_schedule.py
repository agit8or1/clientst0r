"""
Management command to setup automated package scanning schedule
"""
from django.core.management.base import BaseCommand
import subprocess
import os
from pathlib import Path


class Command(BaseCommand):
    help = 'Setup systemd timer for automated package scanning'

    def add_arguments(self, parser):
        parser.add_argument(
            '--disable',
            action='store_true',
            help='Disable the scheduled scanning',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Show current timer status',
        )
        parser.add_argument(
            '--interval',
            type=str,
            default='daily',
            help='Scan interval: daily (default), weekly, hourly, or cron expression',
        )

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        service_file = base_dir / 'systemd' / 'package-scanner.service'
        timer_file = base_dir / 'systemd' / 'package-scanner.timer'

        # Show status
        if options['status']:
            self.show_status()
            return

        # Disable timer
        if options['disable']:
            self.disable_timer()
            return

        # Enable timer
        self.enable_timer(service_file, timer_file, options['interval'])

    def show_status(self):
        """Show current timer status"""
        self.stdout.write(self.style.SUCCESS('=== Package Scanner Schedule Status ===\n'))

        try:
            # Check if timer is active
            result = subprocess.run(
                ['systemctl', '--user', 'is-active', 'package-scanner.timer'],
                capture_output=True,
                text=True
            )
            is_active = result.returncode == 0

            if is_active:
                self.stdout.write(self.style.SUCCESS('✓ Timer is ACTIVE\n'))
            else:
                self.stdout.write(self.style.WARNING('✗ Timer is INACTIVE\n'))

            # Show timer details
            result = subprocess.run(
                ['systemctl', '--user', 'status', 'package-scanner.timer'],
                capture_output=True,
                text=True
            )
            self.stdout.write(result.stdout)

            # Show next run time
            result = subprocess.run(
                ['systemctl', '--user', 'list-timers', 'package-scanner.timer'],
                capture_output=True,
                text=True
            )
            self.stdout.write('\n' + result.stdout)

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR('✗ systemctl not found. Is systemd available?'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error checking status: {e}'))

    def disable_timer(self):
        """Disable and stop the timer"""
        self.stdout.write(self.style.WARNING('Disabling package scanner schedule...'))

        try:
            # Stop timer
            subprocess.run(['systemctl', '--user', 'stop', 'package-scanner.timer'], check=True)
            self.stdout.write(self.style.SUCCESS('✓ Timer stopped'))

            # Disable timer
            subprocess.run(['systemctl', '--user', 'disable', 'package-scanner.timer'], check=True)
            self.stdout.write(self.style.SUCCESS('✓ Timer disabled'))

            self.stdout.write(self.style.SUCCESS('\n✓ Package scanner schedule disabled successfully'))

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed to disable timer: {e}'))
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR('✗ systemctl not found. Is systemd available?'))

    def enable_timer(self, service_file, timer_file, interval):
        """Enable and start the timer"""
        self.stdout.write(self.style.SUCCESS('Setting up package scanner schedule...\n'))

        # Check if systemd is available
        try:
            subprocess.run(['systemctl', '--version'], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.stdout.write(self.style.ERROR('✗ systemd is not available on this system'))
            self.stdout.write(self.style.WARNING('\nAlternative: Use cron instead:'))
            self.stdout.write('  crontab -e')
            self.stdout.write('  Add: 0 2 * * * cd /home/administrator && venv/bin/python manage.py scan_system_packages --save')
            return

        # Ensure systemd user directory exists
        systemd_dir = Path.home() / '.config' / 'systemd' / 'user'
        systemd_dir.mkdir(parents=True, exist_ok=True)

        # Update timer interval if not daily
        if interval != 'daily':
            self.update_timer_interval(timer_file, interval)

        # Copy service and timer files
        try:
            import shutil
            shutil.copy(service_file, systemd_dir / 'package-scanner.service')
            shutil.copy(timer_file, systemd_dir / 'package-scanner.timer')
            self.stdout.write(self.style.SUCCESS('✓ Service and timer files copied'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed to copy files: {e}'))
            return

        # Reload systemd
        try:
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            self.stdout.write(self.style.SUCCESS('✓ Systemd daemon reloaded'))
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed to reload daemon: {e}'))
            return

        # Enable timer
        try:
            subprocess.run(['systemctl', '--user', 'enable', 'package-scanner.timer'], check=True)
            self.stdout.write(self.style.SUCCESS('✓ Timer enabled'))
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed to enable timer: {e}'))
            return

        # Start timer
        try:
            subprocess.run(['systemctl', '--user', 'start', 'package-scanner.timer'], check=True)
            self.stdout.write(self.style.SUCCESS('✓ Timer started'))
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'✗ Failed to start timer: {e}'))
            return

        # Enable lingering (allows user services to run when not logged in)
        try:
            username = os.getenv('USER', 'administrator')
            subprocess.run(['loginctl', 'enable-linger', username], check=False)
            self.stdout.write(self.style.SUCCESS(f'✓ Enabled lingering for user {username}'))
        except Exception:
            self.stdout.write(self.style.WARNING('⚠ Could not enable lingering (may require sudo)'))

        self.stdout.write(self.style.SUCCESS('\n✓ Package scanner schedule setup complete!'))
        self.stdout.write(f'\nInterval: {interval}')
        self.stdout.write('\nView status: python manage.py setup_package_scanner_schedule --status')
        self.stdout.write('Disable: python manage.py setup_package_scanner_schedule --disable')

        # Show next run time
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'list-timers', 'package-scanner.timer'],
                capture_output=True,
                text=True
            )
            self.stdout.write('\n' + result.stdout)
        except Exception:
            pass

    def update_timer_interval(self, timer_file, interval):
        """Update the OnCalendar setting in timer file"""
        # Map common intervals to systemd OnCalendar format
        interval_map = {
            'hourly': 'hourly',
            'daily': 'daily',
            'weekly': 'weekly',
            'monthly': 'monthly',
        }

        calendar_value = interval_map.get(interval, interval)

        # Read and update timer file
        try:
            with open(timer_file, 'r') as f:
                content = f.read()

            # Replace OnCalendar line
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('OnCalendar='):
                    lines[i] = f'OnCalendar={calendar_value}'
                    break

            with open(timer_file, 'w') as f:
                f.write('\n'.join(lines))

            self.stdout.write(self.style.SUCCESS(f'✓ Updated interval to: {calendar_value}'))

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'⚠ Could not update interval: {e}'))
