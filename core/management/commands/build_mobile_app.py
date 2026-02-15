"""
Management command to build mobile apps
"""
import os
import subprocess
import json
import shutil
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Build mobile app (Android or iOS)'

    def add_arguments(self, parser):
        parser.add_argument('app_type', type=str, help='App type: android or ios')

    def handle(self, *args, **options):
        # Set up proper PATH environment first
        path_additions = [
            '/usr/bin',
            '/usr/local/bin',
            '/home/administrator/.nvm/versions/node/v22.21.1/bin',
        ]
        current_path = os.environ.get('PATH', '')
        os.environ['PATH'] = ':'.join(path_additions) + ':' + current_path

        app_type = options['app_type']

        # FIX: Validate app_type to prevent command injection
        VALID_APP_TYPES = ['android', 'ios']
        if app_type not in VALID_APP_TYPES:
            raise ValueError(f"Invalid app_type: {app_type}. Must be one of: {', '.join(VALID_APP_TYPES)}")

        mobile_app_dir = os.path.join(settings.BASE_DIR, 'mobile-app')
        builds_dir = os.path.join(mobile_app_dir, 'builds')
        status_file = os.path.join(builds_dir, f'{app_type}_build_status.json')
        self.log_file = os.path.join(builds_dir, f'{app_type}_build.log')

        # Ensure builds directory exists
        os.makedirs(builds_dir, exist_ok=True)

        # Clear previous log
        with open(self.log_file, 'w') as f:
            f.write(f'=== Building {app_type.upper()} App ===\n')
            f.write(f'Started at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n')

        # Update status: started
        self._update_status(status_file, 'building', 'Starting build...')
        self.stdout.write(self.style.SUCCESS(f'Building {app_type} app...'))

        try:
            # Check if Java is installed (required for Gradle/Android builds)
            if not shutil.which('java'):
                self._update_status(status_file, 'failed', 'Java/JDK is not installed. Please install: sudo apt-get install openjdk-17-jdk')
                raise Exception('Java/JDK is required for Android builds. Install with: sudo apt-get install openjdk-17-jdk')

            # Ensure basic utilities are installed first
            # Determine if we need sudo (check if running as root)
            use_sudo = os.geteuid() != 0 and shutil.which('sudo')
            sudo_prefix = ['sudo'] if use_sudo else []

            # Install curl if missing (needed for Node.js installation)
            if not shutil.which('curl'):
                self._update_status(status_file, 'building', 'Installing curl...')
                self.stdout.write('Installing curl (required for Node.js setup)...')
                try:
                    subprocess.run(sudo_prefix + ['/usr/bin/apt-get', 'update'], check=True, capture_output=True)
                    subprocess.run(sudo_prefix + ['/usr/bin/apt-get', 'install', '-y', 'curl'], check=True, capture_output=True)
                except Exception as e:
                    raise Exception(f'Failed to install curl: {e}\nPlease install manually: apt-get install -y curl')

            # Check if npm is installed, install automatically if not
            if not shutil.which('npm'):
                self._update_status(status_file, 'building', 'Installing Node.js and npm (first time setup)...')
                self.stdout.write('Node.js/npm not found. Installing automatically...')

                try:
                    # Install Node.js 20.x
                    self.stdout.write('Downloading Node.js repository setup...')
                    subprocess.run(
                        ['/usr/bin/curl', '-fsSL', 'https://deb.nodesource.com/setup_20.x', '-o', '/tmp/nodesource_setup.sh'],
                        check=True,
                        capture_output=True
                    )

                    self.stdout.write('Installing Node.js repository...')
                    subprocess.run(
                        sudo_prefix + ['/usr/bin/bash', '/tmp/nodesource_setup.sh'],
                        check=True,
                        capture_output=True
                    )

                    self.stdout.write('Installing Node.js and npm...')
                    subprocess.run(
                        sudo_prefix + ['/usr/bin/apt-get', 'install', '-y', 'nodejs'],
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
                self._update_status(status_file, 'building', 'Installing dependencies (this may take 5-10 minutes)...')
                self.stdout.write('Installing npm dependencies...\n')
                self._log('\n=== Installing npm dependencies ===\n')
                self._log('This will take several minutes. Progress updates below:\n\n')
                self._run_command_with_logging(
                    ['npm', 'install', '--progress=true'],
                    cwd=mobile_app_dir,
                    timeout=600  # 10 minute timeout for npm install
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
                self._update_status(status_file, 'building', 'Generating native Android project...')
                self.stdout.write('Building Android APK...\n')
                self._log('\n=== Building Android APK with Native Tools ===\n')
                self._log('Step 1: Generating native Android project (no Expo account needed)...\n\n')

                # Generate native Android project (no Expo account required)
                try:
                    # Run expo prebuild to generate android/ folder
                    self._run_command_with_logging(
                        ['npx', 'expo', 'prebuild', '--platform', 'android', '--clean'],
                        cwd=mobile_app_dir,
                        timeout=600  # 10 minute timeout
                    )

                    self._update_status(status_file, 'building', 'Building APK with Gradle (10-20 minutes)...')
                    self._log('\n=== Building APK with Gradle ===\n')

                    # Build APK using Gradle
                    android_dir = os.path.join(mobile_app_dir, 'android')
                    self._run_command_with_logging(
                        ['./gradlew', 'assembleRelease'],
                        cwd=android_dir,
                        timeout=1800  # 30 minute timeout
                    )

                    # Find the generated APK
                    apk_path = os.path.join(android_dir, 'app', 'build', 'outputs', 'apk', 'release', 'app-release.apk')
                    if os.path.exists(apk_path):
                        # Copy to builds directory
                        dest_path = os.path.join(builds_dir, 'clientst0r.apk')
                        import shutil as sh
                        sh.copy2(apk_path, dest_path)
                        self._update_status(status_file, 'complete', 'APK built successfully!')
                        self._log(f'\n✓ APK ready at: {dest_path}\n')
                        self.stdout.write(self.style.SUCCESS('APK build complete!\n'))
                    else:
                        raise Exception('APK file not found after build')

                except subprocess.CalledProcessError as e:
                    raise Exception(f'Build command failed with exit code {e.returncode}')

            elif app_type == 'ios':
                self._update_status(status_file, 'building', 'Building iOS IPA locally (this may take 10-20 minutes)...')
                self.stdout.write('Building iOS IPA...\n')
                self._log('\n=== Building iOS IPA Locally ===\n')
                self._log('Building locally without Expo cloud services...\n\n')

                try:
                    self._run_command_with_logging(
                        ['npx', 'eas-cli', 'build', '--platform', 'ios', '--profile', 'preview', '--local', '--non-interactive'],
                        cwd=mobile_app_dir,
                        timeout=1800  # 30 minute timeout
                    )

                    # Read log to extract build URL
                    with open(self.log_file, 'r') as f:
                        log_content = f.read()

                    if 'Build URL:' in log_content or 'https://expo.dev' in log_content:
                        # Extract URL from log
                        for line in log_content.split('\n'):
                            if 'Build URL:' in line or ('https://expo.dev' in line and 'builds' in line):
                                build_url = line.split()[-1]
                                self._update_status(status_file, 'complete', f'Build complete! Download from: {build_url}')
                                self.stdout.write(self.style.SUCCESS(f'IPA build complete: {build_url}\n'))
                                break
                    else:
                        self._update_status(status_file, 'complete', 'Build submitted to Expo. Check log for details.')
                        self.stdout.write(self.style.SUCCESS('Build submitted to Expo!\n'))

                except subprocess.CalledProcessError as e:
                    raise Exception(f'Build command failed with exit code {e.returncode}')

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

    def _run_command_with_logging(self, cmd, cwd=None, timeout=None, env=None):
        """Run command and stream output to log file in real-time"""
        import select
        self._log(f'\n> {" ".join(cmd)}\n')

        # Set up environment with necessary paths
        if env is None:
            env = os.environ.copy()
            # Add common binary locations to PATH
            path_additions = [
                '/usr/bin',
                '/usr/local/bin',
                '/home/administrator/.nvm/versions/node/v22.21.1/bin',
            ]
            current_path = env.get('PATH', '')
            env['PATH'] = ':'.join(path_additions) + ':' + current_path

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        # Stream output line by line
        for line in iter(process.stdout.readline, ''):
            if line:
                self._log(line)
                self.stdout.write(line.rstrip())

        process.wait(timeout=timeout)

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

        return process

    def _log(self, message):
        """Append message to log file"""
        with open(self.log_file, 'a') as f:
            f.write(message)
            if not message.endswith('\n'):
                f.write('\n')

    def _configure_api_urls(self, mobile_app_dir):
        """Auto-configure app.json with server's FQDN"""
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
