"""
Setup passwordless sudo for package scanner.
This allows the web interface to update apt cache automatically.
"""
from django.core.management.base import BaseCommand
from pathlib import Path
import os
import subprocess


class Command(BaseCommand):
    help = 'Configure passwordless sudo for OS Package Scanner'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up Package Scanner sudo permissions'))
        self.stdout.write('=' * 70)

        # Get current user
        username = os.getenv('USER', 'administrator')

        # Create sudoers file content
        sudoers_content = f"""# Clientst0r - OS Package Scanner
# Allow web user to update apt cache for security scanning
{username} ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
{username} ALL=(ALL) NOPASSWD: /usr/bin/apt-get upgrade -y
{username} ALL=(ALL) NOPASSWD: /usr/bin/apt-get dist-upgrade -y
"""

        # Sudoers file path
        sudoers_file = Path('/etc/sudoers.d/clientst0r-package-scanner')

        self.stdout.write('')
        self.stdout.write('Creating sudoers configuration:')
        self.stdout.write(f'  File: {sudoers_file}')
        self.stdout.write('')
        self.stdout.write('Configuration:')
        self.stdout.write(sudoers_content)
        self.stdout.write('')

        # Write to temporary file first
        temp_file = Path('/tmp/clientst0r-package-scanner-sudoers')
        temp_file.write_text(sudoers_content)

        try:
            # Validate syntax
            self.stdout.write('Validating sudoers syntax...')
            result = subprocess.run(
                ['visudo', '-c', '-f', str(temp_file)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                self.stdout.write(self.style.ERROR(f'Invalid sudoers syntax: {result.stderr}'))
                temp_file.unlink()
                return

            self.stdout.write(self.style.SUCCESS('✓ Syntax valid'))

            # Move to sudoers.d
            self.stdout.write('')
            self.stdout.write('Installing sudoers file...')
            result = subprocess.run(
                ['sudo', 'cp', str(temp_file), str(sudoers_file)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                self.stdout.write(self.style.ERROR(f'Failed to install: {result.stderr}'))
                temp_file.unlink()
                return

            # Set permissions
            subprocess.run(['sudo', 'chmod', '0440', str(sudoers_file)])
            subprocess.run(['sudo', 'chown', 'root:root', str(sudoers_file)])

            # Clean up temp file
            temp_file.unlink()

            self.stdout.write(self.style.SUCCESS('✓ Sudoers file installed'))
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✓ Package Scanner sudo permissions configured!'))
            self.stdout.write('')
            self.stdout.write('The web interface can now automatically:')
            self.stdout.write('  • Update apt cache before scanning')
            self.stdout.write('  • Install security updates')
            self.stdout.write('  • Perform system upgrades')
            self.stdout.write('')
            self.stdout.write('Test it by running:')
            self.stdout.write('  sudo -n apt-get update')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
            if temp_file.exists():
                temp_file.unlink()
