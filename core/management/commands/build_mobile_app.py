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
            # Check if npm is installed, install automatically if not
            import shutil
            if not shutil.which('npm'):
                self._update_status(status_file, 'building', 'Installing Node.js and npm (first time setup)...')
                self.stdout.write('Node.js/npm not found. Installing automatically...')

                try:
                    # Install Node.js 20.x
                    self.stdout.write('Downloading Node.js repository setup...')
                    subprocess.run(
                        ['curl', '-fsSL', 'https://deb.nodesource.com/setup_20.x', '-o', '/tmp/nodesource_setup.sh'],
                        check=True,
                        capture_output=True
                    )

                    self.stdout.write('Installing Node.js repository...')
                    subprocess.run(
                        ['sudo', 'bash', '/tmp/nodesource_setup.sh'],
                        check=True,
                        capture_output=True
                    )

                    self.stdout.write('Installing Node.js and npm...')
                    subprocess.run(
                        ['sudo', 'apt-get', 'install', '-y', 'nodejs'],
                        check=True,
                        capture_output=True
                    )

                    # Verify installation
                    if not shutil.which('npm'):
                        raise Exception('Node.js installation completed but npm not found in PATH')

                    self.stdout.write(self.style.SUCCESS('Node.js and npm installed successfully!'))

                except subprocess.CalledProcessError as e:
                    error_details = f'Command: {e.cmd}\nReturn code: {e.returncode}'
                    if e.stderr:
                        error_details += f'\nError output: {e.stderr}'
                    raise Exception(
                        f'Failed to install Node.js/npm automatically.\n\n'
                        f'{error_details}\n\n'
                        f'Manual installation:\n'
                        f'  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -\n'
                        f'  sudo apt-get install -y nodejs\n\n'
                        f'Then click Retry Build.'
                    )
                except Exception as e:
                    raise Exception(
                        f'Error during Node.js/npm installation: {str(e)}\n\n'
                        f'Manual installation:\n'
                        f'  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -\n'
                        f'  sudo apt-get install -y nodejs\n\n'
                        f'Then click Retry Build.'
                    )

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
            if not shutil.which('expo'):
                self._update_status(status_file, 'building', 'Installing Expo CLI...')
                self.stdout.write('Installing Expo CLI...')
                subprocess.run(
                    ['npm', 'install', '-g', 'expo-cli'],
                    check=True,
                    capture_output=True,
                    text=True
                )

            # Auto-configure API URLs with server's FQDN
            self._update_status(status_file, 'building', 'Configuring API URLs...')
            self._configure_api_urls(mobile_app_dir)

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

    def _configure_api_urls(self, mobile_app_dir):
        """Auto-configure app.json with server's FQDN"""
        import os

        app_json_path = os.path.join(mobile_app_dir, 'app.json')

        # Detect server's FQDN
        server_url = self._get_server_url()
        graphql_url = f"{server_url}/api/v2/graphql/"

        self.stdout.write(f'Configuring API URLs: {server_url}')

        # Read app.json
        with open(app_json_path, 'r') as f:
            app_config = json.load(f)

        # Update API URLs
        if 'expo' not in app_config:
            app_config['expo'] = {}
        if 'extra' not in app_config['expo']:
            app_config['expo']['extra'] = {}

        app_config['expo']['extra']['apiUrl'] = server_url
        app_config['expo']['extra']['graphqlUrl'] = graphql_url

        # Write updated app.json
        with open(app_json_path, 'w') as f:
            json.dump(app_config, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f'Configured API URLs: {server_url}'))

    def _get_server_url(self):
        """Get the server's FQDN from environment or settings"""
        import os
        from django.conf import settings

        # Try environment variable first (for production)
        env_url = os.getenv('SERVER_URL') or os.getenv('ALLOWED_HOSTS')
        if env_url:
            # Clean up and format
            url = env_url.split(',')[0].strip()
            if not url.startswith('http'):
                # Assume HTTPS for production
                url = f'https://{url}'
            return url

        # Try Django ALLOWED_HOSTS setting
        if hasattr(settings, 'ALLOWED_HOSTS') and settings.ALLOWED_HOSTS:
            allowed_hosts = [h for h in settings.ALLOWED_HOSTS if h not in ['localhost', '127.0.0.1', '*']]
            if allowed_hosts:
                host = allowed_hosts[0]
                # Assume HTTPS for production
                return f'https://{host}'

        # Fall back to reading from .env file
        env_file = os.path.join(settings.BASE_DIR, '.env')
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                for line in f:
                    if line.startswith('ALLOWED_HOSTS='):
                        hosts = line.split('=')[1].strip().strip('"').strip("'")
                        host = hosts.split(',')[0].strip()
                        if host and host not in ['localhost', '127.0.0.1', '*']:
                            return f'https://{host}'

        # Last resort: use localhost for development
        self.stdout.write(self.style.WARNING(
            'Could not detect server URL. Using localhost. '
            'Set SERVER_URL or ALLOWED_HOSTS environment variable for production.'
        ))
        return 'http://localhost:8000'
