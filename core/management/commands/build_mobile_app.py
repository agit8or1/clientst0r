"""
Management command to build mobile apps
"""
import os
import subprocess
import json
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Build mobile app (Android or iOS)'

    def add_arguments(self, parser):
        parser.add_argument('app_type', type=str, help='App type: android or ios')

    def handle(self, *args, **options):
        app_type = options['app_type']
        mobile_app_dir = os.path.join(settings.BASE_DIR, 'mobile-app')
        builds_dir = os.path.join(mobile_app_dir, 'builds')
        status_file = os.path.join(builds_dir, f'{app_type}_build_status.json')

        # Ensure builds directory exists
        os.makedirs(builds_dir, exist_ok=True)

        # Update status: started
        self._update_status(status_file, 'building', 'Starting build...')
        self.stdout.write(self.style.SUCCESS(f'Building {app_type} app...'))

        try:
            # Check if npm is installed
            npm_check = subprocess.run(['which', 'npm'], capture_output=True)
            if npm_check.returncode != 0:
                raise Exception('npm is not installed. Please install Node.js and npm first.')

            # Check if dependencies are installed
            node_modules = os.path.join(mobile_app_dir, 'node_modules')
            if not os.path.exists(node_modules):
                self._update_status(status_file, 'building', 'Installing dependencies...')
                self.stdout.write('Installing npm dependencies...')
                subprocess.run(
                    ['npm', 'install'],
                    cwd=mobile_app_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )

            # Check if expo-cli is installed
            expo_check = subprocess.run(['which', 'expo'], capture_output=True)
            if expo_check.returncode != 0:
                self._update_status(status_file, 'building', 'Installing Expo CLI...')
                self.stdout.write('Installing Expo CLI...')
                subprocess.run(
                    ['npm', 'install', '-g', 'expo-cli'],
                    check=True,
                    capture_output=True,
                    text=True
                )

            # Build the app
            if app_type == 'android':
                self._update_status(status_file, 'building', 'Building Android APK (this may take 10-20 minutes)...')
                self.stdout.write('Building Android APK...')

                # Use EAS Build (modern Expo build system)
                result = subprocess.run(
                    ['npx', 'eas-cli', 'build', '--platform', 'android', '--profile', 'preview', '--non-interactive'],
                    cwd=mobile_app_dir,
                    capture_output=True,
                    text=True,
                    timeout=1800  # 30 minute timeout
                )

                if result.returncode == 0:
                    # Extract download URL from output
                    output = result.stdout
                    if 'Build URL:' in output:
                        url_line = [line for line in output.split('\n') if 'Build URL:' in line][0]
                        build_url = url_line.split('Build URL:')[1].strip()

                        self._update_status(status_file, 'complete', f'Build complete! Download from: {build_url}')
                        self.stdout.write(self.style.SUCCESS(f'APK build complete: {build_url}'))
                        self.stdout.write(self.style.WARNING('Note: Download the APK and place it at mobile-app/builds/huduglue.apk'))
                    else:
                        self._update_status(status_file, 'complete', 'Build submitted to Expo. Check https://expo.dev/accounts/[your-account]/projects/huduglue-mobile/builds')
                        self.stdout.write(self.style.SUCCESS('Build submitted to Expo!'))
                else:
                    raise Exception(f'Build failed: {result.stderr}')

            elif app_type == 'ios':
                self._update_status(status_file, 'building', 'Building iOS IPA (this may take 10-20 minutes)...')
                self.stdout.write('Building iOS IPA...')

                result = subprocess.run(
                    ['npx', 'eas-cli', 'build', '--platform', 'ios', '--profile', 'preview', '--non-interactive'],
                    cwd=mobile_app_dir,
                    capture_output=True,
                    text=True,
                    timeout=1800  # 30 minute timeout
                )

                if result.returncode == 0:
                    output = result.stdout
                    if 'Build URL:' in output:
                        url_line = [line for line in output.split('\n') if 'Build URL:' in line][0]
                        build_url = url_line.split('Build URL:')[1].strip()

                        self._update_status(status_file, 'complete', f'Build complete! Download from: {build_url}')
                        self.stdout.write(self.style.SUCCESS(f'IPA build complete: {build_url}'))
                        self.stdout.write(self.style.WARNING('Note: Download the IPA and place it at mobile-app/builds/huduglue.ipa'))
                    else:
                        self._update_status(status_file, 'complete', 'Build submitted to Expo. Check https://expo.dev')
                        self.stdout.write(self.style.SUCCESS('Build submitted to Expo!'))
                else:
                    raise Exception(f'Build failed: {result.stderr}')

        except subprocess.TimeoutExpired:
            self._update_status(status_file, 'failed', 'Build timed out after 30 minutes')
            self.stdout.write(self.style.ERROR('Build timed out'))
            raise
        except Exception as e:
            self._update_status(status_file, 'failed', str(e))
            self.stdout.write(self.style.ERROR(f'Build failed: {e}'))
            raise

    def _update_status(self, status_file, status, message):
        """Update build status file"""
        import time
        with open(status_file, 'w') as f:
            json.dump({
                'status': status,  # 'building', 'complete', 'failed'
                'message': message,
                'timestamp': time.time()
            }, f)
