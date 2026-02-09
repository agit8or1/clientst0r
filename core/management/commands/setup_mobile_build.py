"""
Management command to setup mobile app building with automatic dependency installation
"""
import os
import subprocess
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Setup mobile app building with automatic Node.js/npm installation'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up mobile app building...'))

        deploy_dir = os.path.join(settings.BASE_DIR, 'deploy')
        setup_script = os.path.join(deploy_dir, 'setup_mobile_build.sh')

        if not os.path.exists(setup_script):
            self.stdout.write(self.style.ERROR(f'Setup script not found: {setup_script}'))
            return

        try:
            # Run the setup script
            result = subprocess.run(
                ['bash', setup_script],
                cwd=deploy_dir,
                capture_output=True,
                text=True
            )

            # Print output
            if result.stdout:
                self.stdout.write(result.stdout)

            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS('Mobile app build setup complete!'))
                self.stdout.write('')
                self.stdout.write('Mobile apps will now build automatically when users click download.')
            else:
                self.stdout.write(self.style.ERROR(f'Setup failed: {result.stderr}'))
                return

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error running setup: {e}'))
            raise
