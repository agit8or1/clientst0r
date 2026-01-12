"""
Auto-update service for HuduGlue.

Checks GitHub for new releases and performs automated updates.
"""
import requests
import subprocess
import os
import logging
from django.conf import settings
from django.utils import timezone
from packaging import version
from audit.models import AuditLog

logger = logging.getLogger('core')


class UpdateService:
    """Service for checking and applying updates from GitHub."""

    def __init__(self):
        self.github_api = 'https://api.github.com/repos'
        self.repo_owner = getattr(settings, 'GITHUB_REPO_OWNER', 'agit8or1')
        self.repo_name = getattr(settings, 'GITHUB_REPO_NAME', 'huduglue')
        self.current_version = self.get_current_version()
        self.base_dir = settings.BASE_DIR

    def get_current_version(self):
        """Get current installed version."""
        try:
            from config.version import VERSION
            return VERSION
        except ImportError:
            return '0.0.0'

    def check_for_updates(self):
        """
        Check GitHub for new releases.

        Returns:
            dict with 'update_available', 'latest_version', 'current_version',
            'release_url', 'release_notes'
        """
        try:
            # Get latest release from GitHub API
            url = f'{self.github_api}/{self.repo_owner}/{self.repo_name}/releases/latest'
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            latest_version = data['tag_name'].lstrip('v')
            release_notes = data.get('body', 'No release notes available')
            release_url = data.get('html_url', '')
            published_at = data.get('published_at', '')

            # Compare versions
            update_available = version.parse(latest_version) > version.parse(self.current_version)

            return {
                'update_available': update_available,
                'latest_version': latest_version,
                'current_version': self.current_version,
                'release_url': release_url,
                'release_notes': release_notes,
                'published_at': published_at,
                'checked_at': timezone.now().isoformat(),
            }

        except requests.RequestException as e:
            logger.error(f"Failed to check for updates: {e}")
            return {
                'update_available': False,
                'latest_version': None,
                'current_version': self.current_version,
                'error': str(e),
                'checked_at': timezone.now().isoformat(),
            }

    def perform_update(self, user=None):
        """
        Perform full system update.

        Steps:
        1. Git pull from main branch
        2. Install Python dependencies
        3. Run database migrations
        4. Collect static files
        5. Restart service

        Returns:
            dict with 'success', 'steps_completed', 'output', 'error'
        """
        result = {
            'success': False,
            'steps_completed': [],
            'output': [],
            'error': None,
        }

        try:
            # Step 1: Git pull
            logger.info("Starting update: Git pull")
            git_output = self._run_command(['/usr/bin/git', 'pull', 'origin', 'main'])
            result['steps_completed'].append('git_pull')
            result['output'].append(f"Git pull: {git_output}")

            # Check if there were any changes
            if 'Already up to date' in git_output:
                logger.info("No updates available in git repository")
                result['output'].append("Repository already up to date")

            # Step 2: Install requirements
            logger.info("Installing Python dependencies")
            pip_output = self._run_command([
                'pip', 'install', '-r',
                os.path.join(self.base_dir, 'requirements.txt'),
                '--upgrade'
            ])
            result['steps_completed'].append('install_requirements')
            result['output'].append(f"Pip install: {pip_output[:500]}")  # Truncate output

            # Step 3: Run migrations
            logger.info("Running database migrations")
            migrate_output = self._run_command([
                'python', os.path.join(self.base_dir, 'manage.py'),
                'migrate', '--noinput'
            ])
            result['steps_completed'].append('migrate')
            result['output'].append(f"Migrations: {migrate_output}")

            # Step 4: Collect static files
            logger.info("Collecting static files")
            static_output = self._run_command([
                'python', os.path.join(self.base_dir, 'manage.py'),
                'collectstatic', '--noinput'
            ])
            result['steps_completed'].append('collectstatic')
            result['output'].append(f"Static files: {static_output[:500]}")

            # Step 5: Restart service (if running under systemd)
            if self._is_systemd_service():
                logger.info("Restarting systemd service")
                restart_output = self._run_command([
                    'sudo', 'systemctl', 'restart', 'huduglue'
                ])
                result['steps_completed'].append('restart_service')
                result['output'].append(f"Service restart: {restart_output}")

            result['success'] = True

            # Log to audit trail
            AuditLog.objects.create(
                action='system_update',
                description=f'System updated from {self.current_version} by {user.username if user else "system"}',
                user=user,
                username=user.username if user else 'system',
                success=True,
                extra_data={
                    'previous_version': self.current_version,
                    'steps_completed': result['steps_completed'],
                }
            )

            logger.info("Update completed successfully")

        except Exception as e:
            logger.error(f"Update failed: {e}")
            result['error'] = str(e)
            result['output'].append(f"ERROR: {str(e)}")

            # Log failure to audit trail
            AuditLog.objects.create(
                action='system_update_failed',
                description=f'System update failed: {str(e)}',
                user=user,
                username=user.username if user else 'system',
                success=False,
                extra_data={
                    'current_version': self.current_version,
                    'steps_completed': result['steps_completed'],
                    'error': str(e),
                }
            )

        return result

    def _run_command(self, command):
        """
        Run a shell command and return output.

        Args:
            command: List of command arguments

        Returns:
            str: Command output
        """
        try:
            result = subprocess.run(
                command,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                raise Exception(f"Command failed: {result.stderr}")

            return result.stdout

        except subprocess.TimeoutExpired:
            raise Exception(f"Command timed out: {' '.join(command)}")

    def _is_systemd_service(self):
        """Check if running as a systemd service."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'huduglue'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False

    def get_git_status(self):
        """
        Get current git branch and status.

        Returns:
            dict with 'branch', 'commit', 'clean'
        """
        git_cmd = '/usr/bin/git'  # Use full path to git

        try:
            # Get current branch
            branch_output = subprocess.run(
                [git_cmd, 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )

            if branch_output.returncode != 0:
                logger.error(f"Git branch command failed: {branch_output.stderr}")
                branch = 'unknown'
            else:
                branch = branch_output.stdout.strip()

            # Get current commit
            commit_output = subprocess.run(
                [git_cmd, 'rev-parse', '--short', 'HEAD'],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )

            if commit_output.returncode != 0:
                logger.error(f"Git commit command failed: {commit_output.stderr}")
                commit = 'unknown'
            else:
                commit = commit_output.stdout.strip()

            # Check if working tree is clean
            status_output = subprocess.run(
                [git_cmd, 'status', '--porcelain'],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )

            if status_output.returncode != 0:
                logger.error(f"Git status command failed: {status_output.stderr}")
                clean = None
            else:
                clean = len(status_output.stdout.strip()) == 0

            return {
                'branch': branch,
                'commit': commit,
                'clean': clean,
            }

        except Exception as e:
            logger.error(f"Failed to get git status: {e}")
            return {
                'branch': 'unknown',
                'commit': 'unknown',
                'clean': None,
                'error': str(e),
            }
