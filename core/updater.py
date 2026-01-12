"""
Auto-update service for HuduGlue.

Checks GitHub for new releases and performs automated updates.
"""
import requests
import subprocess
import os
import logging
import re
from pathlib import Path
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

    def perform_update(self, user=None, progress_tracker=None):
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
            if progress_tracker:
                progress_tracker.step_start('Git Pull')
            logger.info("Starting update: Git pull")
            git_output = self._run_command(['/usr/bin/git', 'pull', 'origin', 'main'])
            result['steps_completed'].append('git_pull')
            result['output'].append(f"Git pull: {git_output}")
            if progress_tracker:
                progress_tracker.step_complete('Git Pull')

            # Check if there were any changes
            if 'Already up to date' in git_output:
                logger.info("No updates available in git repository")
                result['output'].append("Repository already up to date")

            # Step 2: Install requirements
            if progress_tracker:
                progress_tracker.step_start('Install Dependencies')
            logger.info("Installing Python dependencies")
            pip_output = self._run_command([
                'pip', 'install', '-r',
                os.path.join(self.base_dir, 'requirements.txt')
                # Note: Removed --upgrade to avoid rebuilding compiled packages like python-ldap
                # Git pull already brought new code, we only need to install missing packages
            ])
            result['steps_completed'].append('install_requirements')
            result['output'].append(f"Pip install: {pip_output[:500]}")  # Truncate output
            if progress_tracker:
                progress_tracker.step_complete('Install Dependencies')

            # Step 3: Run migrations
            if progress_tracker:
                progress_tracker.step_start('Run Migrations')
            logger.info("Running database migrations")
            migrate_output = self._run_command([
                'python', os.path.join(self.base_dir, 'manage.py'),
                'migrate', '--noinput'
            ])
            result['steps_completed'].append('migrate')
            result['output'].append(f"Migrations: {migrate_output}")
            if progress_tracker:
                progress_tracker.step_complete('Run Migrations')

            # Step 4: Collect static files
            if progress_tracker:
                progress_tracker.step_start('Collect Static Files')
            logger.info("Collecting static files")
            static_output = self._run_command([
                'python', os.path.join(self.base_dir, 'manage.py'),
                'collectstatic', '--noinput'
            ])
            result['steps_completed'].append('collectstatic')
            result['output'].append(f"Static files: {static_output[:500]}")
            if progress_tracker:
                progress_tracker.step_complete('Collect Static Files')

            # Step 5: Restart service (if running under systemd)
            if self._is_systemd_service():
                if progress_tracker:
                    progress_tracker.step_start('Restart Service')
                logger.info("Restarting systemd service")

                # Schedule restart to happen after response is sent
                # Using systemd-run to avoid killing ourselves mid-update
                import time
                restart_output = self._run_command([
                    'sudo', 'systemd-run', '--on-active=3',
                    'systemctl', 'restart', 'huduglue-gunicorn.service'
                ])
                logger.info(f"Service restart scheduled: {restart_output}")
                result['steps_completed'].append('restart_service')
                result['output'].append(f"Service restart scheduled (3s delay): {restart_output}")
                if progress_tracker:
                    progress_tracker.step_complete('Restart Service')

            result['success'] = True

            if progress_tracker:
                progress_tracker.finish(success=True)

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

            if progress_tracker:
                progress_tracker.finish(success=False, error=str(e))

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
                ['systemctl', 'is-active', 'huduglue-gunicorn.service'],
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

    def get_changelog_for_version(self, version_str):
        """
        Extract changelog content for a specific version from CHANGELOG.md.

        Args:
            version_str: Version string like "2.13.0"

        Returns:
            str: Changelog content for the version, or empty string if not found
        """
        changelog_path = Path(self.base_dir) / 'CHANGELOG.md'

        if not changelog_path.exists():
            logger.warning("CHANGELOG.md not found")
            return ""

        try:
            with open(changelog_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Pattern to match version section: ## [2.13.0] - date
            version_pattern = rf'## \[{re.escape(version_str)}\].*?\n(.*?)(?=\n## \[|\Z)'
            match = re.search(version_pattern, content, re.DOTALL)

            if match:
                return match.group(1).strip()
            else:
                logger.warning(f"Version {version_str} not found in CHANGELOG.md")
                return ""

        except Exception as e:
            logger.error(f"Failed to read CHANGELOG.md: {e}")
            return ""

    def get_all_versions_from_changelog(self):
        """
        Parse CHANGELOG.md and extract all version numbers.

        Returns:
            list: List of version strings in order (newest first)
        """
        changelog_path = Path(self.base_dir) / 'CHANGELOG.md'

        if not changelog_path.exists():
            return []

        try:
            with open(changelog_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find all version headers: ## [2.13.0] - date
            version_pattern = r'## \[(\d+\.\d+\.\d+)\]'
            matches = re.findall(version_pattern, content)

            return matches

        except Exception as e:
            logger.error(f"Failed to parse CHANGELOG.md: {e}")
            return []

    def get_changelog_between_versions(self, from_version, to_version):
        """
        Get combined changelog for all versions between from_version and to_version.

        Args:
            from_version: Starting version (exclusive) e.g., "2.12.0"
            to_version: Ending version (inclusive) e.g., "2.13.0"

        Returns:
            dict: {version: changelog_content} for each version in range
        """
        all_versions = self.get_all_versions_from_changelog()
        changelogs = {}

        try:
            from_ver = version.parse(from_version)
            to_ver = version.parse(to_version)

            for ver_str in all_versions:
                ver = version.parse(ver_str)
                # Include versions greater than from_version and up to to_version
                if from_ver < ver <= to_ver:
                    changelog = self.get_changelog_for_version(ver_str)
                    if changelog:
                        changelogs[ver_str] = changelog

        except Exception as e:
            logger.error(f"Failed to get changelog between versions: {e}")

        return changelogs
