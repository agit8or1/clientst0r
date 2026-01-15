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
        Check GitHub for new versions by comparing git tags.

        Returns:
            dict with 'update_available', 'latest_version', 'current_version',
            'release_url', 'release_notes'
        """
        logger.info(f"Starting update check. Current version: {self.current_version}")

        try:
            # Get all tags from GitHub API (sorted by date, most recent first)
            url = f'{self.github_api}/{self.repo_owner}/{self.repo_name}/tags'
            logger.info(f"Fetching tags from: {url}")

            response = requests.get(url, timeout=10)
            logger.info(f"GitHub API response status: {response.status_code}")
            response.raise_for_status()

            tags = response.json()
            if not tags:
                logger.warning("No tags found in repository")
                return {
                    'update_available': False,
                    'latest_version': None,
                    'current_version': self.current_version,
                    'error': 'No tags found',
                    'checked_at': timezone.now().isoformat(),
                }

            # Find the latest semantic version tag
            latest_tag = None
            latest_version_parsed = None

            for tag in tags:
                tag_name = tag['name'].lstrip('v')
                try:
                    # Parse as semantic version
                    tag_version = version.parse(tag_name)
                    if latest_version_parsed is None or tag_version > latest_version_parsed:
                        latest_version_parsed = tag_version
                        latest_tag = tag
                except:
                    # Skip non-semantic version tags
                    continue

            if not latest_tag:
                logger.warning("No valid semantic version tags found")
                return {
                    'update_available': False,
                    'latest_version': None,
                    'current_version': self.current_version,
                    'error': 'No valid version tags found',
                    'checked_at': timezone.now().isoformat(),
                }

            latest_version = latest_tag['name'].lstrip('v')
            logger.info(f"Latest tag from GitHub: {latest_version}")

            # Compare versions
            update_available = version.parse(latest_version) > version.parse(self.current_version)
            logger.info(f"Version comparison: {latest_version} > {self.current_version} = {update_available}")

            # Try to get release notes if a release exists for this tag
            release_notes = 'No release notes available'
            release_url = f'https://github.com/{self.repo_owner}/{self.repo_name}/releases/tag/v{latest_version}'
            published_at = None

            try:
                release_response = requests.get(
                    f'{self.github_api}/{self.repo_owner}/{self.repo_name}/releases/tags/v{latest_version}',
                    timeout=5
                )
                if release_response.status_code == 200:
                    release_data = release_response.json()
                    release_notes = release_data.get('body', 'No release notes available')
                    published_at = release_data.get('published_at')
            except:
                pass  # Release doesn't exist, that's ok

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
            # Pre-check: Verify passwordless sudo is configured (if running under systemd)
            if self._is_systemd_service():
                if not self._check_passwordless_sudo():
                    raise Exception(
                        "Passwordless sudo is not configured for auto-updates. "
                        "Please configure it by running these commands:\n\n"
                        "sudo tee /etc/sudoers.d/huduglue-auto-update > /dev/null <<'SUDOERS'\n"
                        f"$(whoami) ALL=(ALL) NOPASSWD: /bin/systemctl restart huduglue-gunicorn.service, "
                        "/bin/systemctl status huduglue-gunicorn.service, /usr/bin/systemd-run\n"
                        "SUDOERS\n\n"
                        "sudo chmod 0440 /etc/sudoers.d/huduglue-auto-update\n\n"
                        "After configuring, refresh this page and try again. "
                        "Or update manually via command line (see instructions below)."
                    )

            # Step 1: Git fetch and intelligent update
            if progress_tracker:
                progress_tracker.step_start('Git Pull')
            logger.info("Starting update: Git fetch")

            # First, fetch from remote
            fetch_output = self._run_command(['/usr/bin/git', 'fetch', 'origin'])
            result['output'].append(f"Git fetch: {fetch_output}")

            # Check if branches are divergent (happens after force push)
            local_commit = self._run_command(['/usr/bin/git', 'rev-parse', 'HEAD']).strip()
            remote_commit = self._run_command(['/usr/bin/git', 'rev-parse', 'origin/main']).strip()

            git_output = ""
            if local_commit != remote_commit:
                # Check if it's a simple fast-forward or divergent
                try:
                    self._run_command(['/usr/bin/git', 'merge-base', '--is-ancestor', 'HEAD', 'origin/main'])
                    is_ancestor = True
                except:
                    is_ancestor = False

                if not is_ancestor:
                    # Branches are divergent (remote was force-pushed)
                    logger.warning("Remote repository history has changed (force push detected)")
                    result['output'].append("⚠️ Remote repository history has changed (force push detected)")
                    result['output'].append("Resetting to remote version...")

                    git_output = self._run_command(['/usr/bin/git', 'reset', '--hard', 'origin/main'])
                    result['output'].append(f"Git reset: {git_output}")
                else:
                    # Simple fast-forward update
                    logger.info("Pulling updates (fast-forward)")
                    try:
                        git_output = self._run_command(['/usr/bin/git', 'pull', 'origin', 'main'])
                        result['output'].append(f"Git pull: {git_output}")
                    except Exception as e:
                        # SELF-HEALING: If pull fails with divergent branches, auto-fix with reset
                        if 'divergent branches' in str(e).lower():
                            logger.warning("Git pull failed with divergent branches - auto-healing with reset")
                            result['output'].append("⚠️ Git pull failed (divergent branches detected)")
                            result['output'].append("🔧 Auto-healing: Resetting to remote version...")
                            git_output = self._run_command(['/usr/bin/git', 'reset', '--hard', 'origin/main'])
                            result['output'].append(f"Git reset: {git_output}")
                            result['output'].append("✅ Auto-heal successful")
                        else:
                            raise  # Re-raise if it's a different error
            else:
                logger.info("Repository already up to date")
                result['output'].append("Repository already up to date")
                git_output = "Already up to date"

            result['steps_completed'].append('git_pull')
            if progress_tracker:
                progress_tracker.step_complete('Git Pull')

            # Check if there were any changes
            if 'Already up to date' in git_output:
                logger.info("No updates available in git repository")

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
            is_systemd = self._is_systemd_service()
            logger.info(f"Systemd service check result: {is_systemd}")

            if is_systemd:
                if progress_tracker:
                    progress_tracker.step_start('Restart Service')
                logger.info("Restarting systemd service")

                # Schedule restart to happen after response is sent
                # Using systemd-run to avoid killing ourselves mid-update
                import time
                try:
                    restart_output = self._run_command([
                        '/usr/bin/sudo', '/usr/bin/systemd-run', '--on-active=3',
                        '/usr/bin/systemctl', 'restart', 'huduglue-gunicorn.service'
                    ])
                    logger.info(f"Service restart scheduled: {restart_output}")
                    result['steps_completed'].append('restart_service')
                    result['output'].append(f"Service restart scheduled (3s delay): {restart_output}")
                    if progress_tracker:
                        progress_tracker.step_complete('Restart Service')
                except Exception as e:
                    error_msg = str(e)
                    if 'password is required' in error_msg or 'terminal is required' in error_msg:
                        raise Exception(
                            "Passwordless sudo is not configured. Auto-update requires passwordless sudo "
                            "to restart the service. Please configure it by running:\n\n"
                            "sudo tee /etc/sudoers.d/huduglue-auto-update > /dev/null <<'SUDOERS'\n"
                            f"$(whoami) ALL=(ALL) NOPASSWD: /bin/systemctl restart huduglue-gunicorn.service, "
                            "/bin/systemctl status huduglue-gunicorn.service, /usr/bin/systemd-run\n"
                            "SUDOERS\n\n"
                            "sudo chmod 0440 /etc/sudoers.d/huduglue-auto-update\n\n"
                            "Or update manually via command line. See the system updates page for instructions."
                        )
                    else:
                        raise
            else:
                logger.warning("Not running as systemd service - skipping restart")

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
            error_msg = str(e)

            # Special handling for divergent branches error with helpful instructions
            if 'divergent branches' in error_msg.lower():
                error_msg = (
                    "Update failed due to repository history changes (force push).\n\n"
                    "This happens when you're on an older version that doesn't have the auto-fix.\n\n"
                    "Quick fix - run these commands in terminal:\n\n"
                    f"cd {self.base_dir}\n"
                    "git fetch origin\n"
                    "git reset --hard origin/main\n"
                    "sudo systemctl restart huduglue-gunicorn.service\n\n"
                    "After this one-time fix, future updates will handle this automatically.\n\n"
                    "See Issue #24 on GitHub for more details."
                )
                logger.error(f"Divergent branches detected. Manual fix required. See error message for instructions.")

            result['error'] = error_msg
            result['output'].append(f"ERROR: {error_msg}")

            if progress_tracker:
                progress_tracker.finish(success=False, error=error_msg)

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
                ['/usr/bin/systemctl', 'is-active', 'huduglue-gunicorn.service'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"Failed to check systemd service status: {e}")
            return False

    def _check_passwordless_sudo(self):
        """
        Check if passwordless sudo is configured for service restart.

        Returns:
            bool: True if passwordless sudo works, False otherwise
        """
        try:
            # Test if we can run sudo without password using -n (non-interactive)
            result = subprocess.run(
                ['/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'status', 'huduglue-gunicorn.service'],
                capture_output=True,
                text=True,
                timeout=5
            )
            # If returncode is 0, passwordless sudo is working
            # If it's 1 but no password error in stderr, sudo works but service might not exist
            if result.returncode == 0:
                return True
            # Check if the error is specifically about needing a password
            if 'password is required' in result.stderr or 'a terminal is required' in result.stderr:
                return False
            # Other errors (like service not found) still mean sudo itself works
            return True
        except Exception as e:
            logger.warning(f"Failed to check passwordless sudo: {e}")
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
