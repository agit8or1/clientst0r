"""
Django management command for auto-updating Client St0r.
Usage: python manage.py auto_update [--check-only]
"""
import subprocess
import sys
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from core.models import SystemSetting


class Command(BaseCommand):
    help = 'Automatically update Client St0r from GitHub (pull, migrate, restart)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='Only check if updates are available, do not apply',
        )
        parser.add_argument(
            '--no-restart',
            action='store_true',
            help='Do not restart services after update',
        )

    def handle(self, *args, **options):
        check_only = options['check_only']
        no_restart = options['no_restart']

        project_dir = settings.BASE_DIR
        update_script = project_dir / 'scripts' / 'auto_update.sh'

        self.stdout.write(self.style.HTTP_INFO('Client St0r Auto-Update'))
        self.stdout.write(self.style.HTTP_INFO('=' * 50))

        # Check if auto_update.sh exists
        if not update_script.exists():
            raise CommandError(
                f'Auto-update script not found: {update_script}\n'
                'Run: scripts/install_auto_update.sh to install'
            )

        if check_only:
            self.stdout.write('Checking for updates...')
            try:
                result = subprocess.run(
                    ['git', 'fetch', 'origin', 'main'],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                # Check if local is behind remote
                result = subprocess.run(
                    ['git', 'rev-list', '--count', 'HEAD..origin/main'],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                commits_behind = int(result.stdout.strip())

                if commits_behind == 0:
                    self.stdout.write(self.style.SUCCESS('✓ Already up to date'))
                    return
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Updates available: {commits_behind} commit(s) behind'
                        )
                    )

                    # Show what commits are available
                    result = subprocess.run(
                        ['git', 'log', '--oneline', 'HEAD..origin/main'],
                        cwd=project_dir,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    self.stdout.write('\nAvailable updates:')
                    self.stdout.write(result.stdout)
                    self.stdout.write('\nRun without --check-only to apply updates')
                    sys.exit(1)  # Exit with code 1 to indicate updates available

            except subprocess.TimeoutExpired:
                raise CommandError('Git command timed out')
            except Exception as e:
                raise CommandError(f'Error checking for updates: {e}')

        else:
            # Run full update
            self.stdout.write('Running auto-update script...')
            self.stdout.write(f'Script: {update_script}')
            self.stdout.write('')

            try:
                # Run the update script
                result = subprocess.run(
                    [str(update_script)],
                    cwd=project_dir,
                    text=True,
                    timeout=300  # 5 minute timeout
                )

                if result.returncode == 0:
                    self.stdout.write(self.style.SUCCESS('\n✓ Update completed successfully'))
                    self.stdout.write('Check /var/log/clientst0r/auto-update.log for details')
                else:
                    raise CommandError(f'Update script failed with exit code {result.returncode}')

            except subprocess.TimeoutExpired:
                raise CommandError('Update script timed out (>5 minutes)')
            except Exception as e:
                raise CommandError(f'Error running update: {e}')
