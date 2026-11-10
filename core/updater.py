"""
Auto-update service for Client St0r.

Checks GitHub for new releases and performs automated updates.
"""
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
        self.repo_name = getattr(settings, 'GITHUB_REPO_NAME', 'clientst0r')
        self.current_version = self.get_current_version()

        # Auto-detect the ACTUAL running installation directory
        # Use the location of THIS file (core/updater.py) to find the project root
        self.base_dir = self._detect_installation_directory()
        logger.info(f"UpdateService initialized with base_dir: {self.base_dir}")

        # Auto-detect gunicorn service name
        self.service_name = self._detect_gunicorn_service_name()
        if self.service_name:
            logger.info(f"Detected service name: {self.service_name}")
        else:
            logger.info("No systemd service detected - will use pkill for restarts")

    def get_current_version(self):
        """Get current installed version."""
        try:
            from config.version import VERSION
            return VERSION
        except ImportError:
            return '0.0.0'

    def _detect_installation_directory(self):
        """
        Auto-detect the ACTUAL installation directory where code is running.

        This prevents the updater from updating the wrong directory when multiple
        installations exist on the same server.

        Returns:
            Path: Absolute path to the project root directory
        """
        # Get the directory containing THIS file (core/updater.py)
        current_file = Path(__file__).resolve()

        # Go up two levels: core/updater.py -> core/ -> project_root/
        project_root = current_file.parent.parent

        # Validate it's a valid Client St0r installation
        required_files = ['manage.py', 'config/wsgi.py', 'requirements.txt']
        for req_file in required_files:
            if not (project_root / req_file).exists():
                logger.error(f"Invalid installation: {req_file} not found in {project_root}")
                # Fallback to settings.BASE_DIR if detection fails
                logger.warning(f"Falling back to settings.BASE_DIR: {settings.BASE_DIR}")
                return settings.BASE_DIR

        logger.info(f"Auto-detected installation directory: {project_root}")
        return str(project_root)

    def _find_venv_python(self):
        """
        Find the virtual environment Python executable.

        Searches multiple common locations to handle different installation patterns.

        Returns:
            str: Absolute path to venv Python executable

        Raises:
            Exception: If venv cannot be found in any common location
        """
        # Try multiple common locations
        search_paths = [
            # Primary: venv in detected base_dir
            os.path.join(self.base_dir, 'venv', 'bin', 'python'),
            os.path.join(self.base_dir, 'venv', 'bin', 'python3'),
            os.path.join(self.base_dir, 'venv', 'bin', 'python3.12'),

            # Alternative: Check if there's a subdirectory that might have the venv
            os.path.join(self.base_dir, 'clientst0r', 'venv', 'bin', 'python'),

            # Fallback: settings.BASE_DIR if different from detected base_dir
            os.path.join(settings.BASE_DIR, 'venv', 'bin', 'python') if str(settings.BASE_DIR) != self.base_dir else None,
        ]

        # Remove None values
        search_paths = [p for p in search_paths if p]

        logger.info(f"Searching for venv Python in {len(search_paths)} locations...")
        for venv_path in search_paths:
            if os.path.exists(venv_path):
                logger.info(f"✓ Found venv Python: {venv_path}")
                return venv_path
            else:
                logger.debug(f"✗ Not found: {venv_path}")

        # If we get here, venv wasn't found anywhere
        error_msg = f"Virtual environment not found. Searched locations:\n"
        for path in search_paths:
            error_msg += f"  - {path}\n"
        error_msg += "\nPlease ensure your virtual environment is properly installed."
        logger.error(error_msg)
        raise Exception(error_msg)

    def _detect_gunicorn_service_name(self):
        """
        Auto-detect the systemd gunicorn service name.

        Checks for common service names:
        - clientst0r-gunicorn.service

        Returns:
            str: Service name if found, None if not running under systemd
        """
        possible_names = [
            'clientst0r-gunicorn.service',
        ]

        for service_name in possible_names:
            try:
                result = subprocess.run(
                    ['/usr/bin/systemctl', 'is-active', service_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    logger.info(f"Detected gunicorn service: {service_name}")
                    return service_name
            except Exception:
                continue

        logger.warning("No gunicorn systemd service detected")
        return None

    def _get_github_headers(self):
        """Get headers for GitHub API requests with authentication if available."""
        headers = {'Accept': 'application/vnd.github.v3+json'}

        # Try to get GitHub token from environment or settings
        github_token = os.getenv('GITHUB_TOKEN') or getattr(settings, 'GITHUB_TOKEN', None)
        if github_token:
            headers['Authorization'] = f'token {github_token}'
            logger.debug("Using authenticated GitHub API requests")
        else:
            logger.debug("Using unauthenticated GitHub API requests (60/hour limit)")

        return headers

    @staticmethod
    def _record_latest(latest_version):
        """Persist what this check found for every process to see (the
        navbar badge reads it; see core.context_processors). .update() so
        SystemSetting.updated_at keeps meaning "an admin changed settings"."""
        try:
            from core.models import SystemSetting
            SystemSetting.get_settings()
            SystemSetting.objects.filter(pk=1).update(latest_release_version=str(latest_version or '')[:32],
                                                      latest_release_checked_at=timezone.now())
        except Exception:
            logger.exception('could not record the latest release version')

    def check_for_updates(self, *, force_refresh=False):
        """What this instance's release channel offers.

        Since the install/upgrade hardening this asks core.upgrade.channels:
        Stable is the newest *published, signed* GitHub release (it used to
        be the highest version tag, which includes every unreleased build);
        Preview is the head of main. The legacy keys below are kept for the
        callers that read them (system warnings, `manage.py check_updates`);
        `channels` carries the full picture for Settings -> Updates.

        Returns:
            dict with 'update_available', 'latest_version', 'current_version',
            'release_url', 'release_notes', 'target', 'channels', 'error'
        """
        from core.upgrade import channels
        state = channels.resolve(force_refresh=force_refresh)
        stable = state.get('stable') or {}
        target = state.get('target')
        if state['channel'] == 'preview' and state.get('preview'):
            latest = (state['preview'].get('version') or self.current_version)
        else:
            latest = stable.get('version')
        return {
            'update_available': bool(target),
            'latest_version': (target or {}).get('version') or latest,
            'current_version': self.current_version,
            'release_url': stable.get('url'),
            'release_notes': stable.get('notes') or 'No release notes available',
            'published_at': stable.get('published_at'),
            'checked_at': state.get('checked_at'),
            'error': state.get('error'),
            'stale': state.get('stale'),
            'from_cache': state.get('from_cache'),
            'target': target,
            'channel': state['channel'],
            'channels': state,
        }

    def perform_update(self, user=None, progress_tracker=None, target=None):
        """Install `target` (a core.upgrade.revision.Target) -- or, when None,
        what this instance's channel offers -- through the verified pipeline
        in core.upgrade.apply: pinned sha, signature check for releases,
        preflight checks, a verified backup before migrating, and the update
        script taken from the target revision itself.

        Returns:
            dict with 'success', 'steps_completed', 'output', 'error'
        """
        from core.upgrade import apply as upgrade_apply
        from core.upgrade.revision import Target

        result = {'success': False, 'steps_completed': [], 'output': [], 'error': None}
        try:
            if self._is_systemd_service() and not self._check_passwordless_sudo():
                # v3.17.645: root actions go through the root helper; never
                # ask for new NOPASSWD rules.
                from . import root_helper
                raise Exception(
                    "This account can't run the root helper without a password, so the "
                    "update can't reload the app. Run the one-time setup on the server, "
                    f"then try again:\n\n{root_helper.bootstrap_command()}\n\n"
                    "Or update manually via command line (see instructions below)."
                )
            if target is None:
                info = self.check_for_updates(force_refresh=True)
                t = info.get('target')
                if not t:
                    raise Exception(info.get('error') or 'Nothing newer to install on this channel.')
                target = Target(t['kind'], t['ref'], t['sha'], t.get('version') or '')
        except Exception as e:
            result['error'] = str(e)
            result['output'].append(f'ERROR: {e}')
            if progress_tracker:
                progress_tracker.finish(success=False, error=str(e))
            AuditLog.objects.create(
                action='system_update_failed', description=f'System update failed: {e}',
                user=user, username=user.username if user else 'system', success=False,
                extra_data={'current_version': self.current_version, 'error': str(e)})
            return result

        run = upgrade_apply.run(target, user=user, progress=progress_tracker)
        result.update(success=run['success'], output=run['output'], error=run['error'],
                      backup=run.get('backup'), refused=run.get('refused'))
        if run['success']:
            result['steps_completed'] = list(upgrade_apply.PRE_STEPS + upgrade_apply.SCRIPT_STEPS)
            try:
                import sys
                import importlib
                if 'config.version' in sys.modules:
                    importlib.reload(sys.modules['config.version'])
                    from config.version import VERSION
                    result['new_version'] = VERSION
            except Exception as e:
                logger.warning(f"Failed to reload version module: {e}")
        return result

    def _find_sudo(self):
        """Find sudo command dynamically."""
        import shutil
        sudo_path = shutil.which('sudo')
        if sudo_path:
            return sudo_path
        # Fallback to common paths
        for path in ['/usr/bin/sudo', '/bin/sudo', '/usr/local/bin/sudo']:
            if os.path.exists(path):
                return path
        return None

    def _run_command(self, command, use_sudo=False):
        """
        Run a shell command and return output.

        Self-healing: Tries without sudo first, falls back to sudo if permission denied.

        Args:
            command: List of command arguments
            use_sudo: Whether to try with sudo

        Returns:
            str: Command output
        """
        try:
            # Try without sudo first
            result = subprocess.run(
                command,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                # If permission denied and sudo available, retry with sudo
                if ('permission denied' in result.stderr.lower() or
                    'operation not permitted' in result.stderr.lower()) and not use_sudo:
                    sudo_path = self._find_sudo()
                    if sudo_path:
                        logger.info(f"Permission denied, retrying with sudo: {' '.join(command)}")
                        return self._run_command([sudo_path] + command, use_sudo=True)

                raise Exception(f"Command failed: {result.stderr}")

            return result.stdout

        except subprocess.TimeoutExpired:
            raise Exception(f"Command timed out: {' '.join(command)}")

    def _is_systemd_service(self):
        """Check if running as a systemd service."""
        # Return True if we detected a service name during init
        return self.service_name is not None

    def _check_passwordless_sudo(self):
        """
        Check if passwordless sudo is configured for service restart.

        v3.17.520: probe `systemctl status <service>` FIRST, and never conclude
        from a single refusal.

        This used to lead with `systemd-run --version` on the assumption that
        systemd-run was "always present in the sudoers config" — true only while
        it was granted bare. Under the least-privilege ruleset (v3.17.518)
        systemd-run is pinned to the one restart invocation the updater issues,
        so `--version` is refused, and an early `return False` meant the working
        fallback probe was never reached. The web UI then showed a "One-Time
        Setup Required" banner on a host where updates worked perfectly well.

        `systemctl status <service>` is the better probe anyway: read-only,
        harmless to run, and much closer to what the updater actually needs.

        v3.17.645: the root helper comes first. Since v3.17.597 every root
        action an update takes goes through it, so an install with the helper
        needs no other sudo rule; the systemctl probes below only matter for
        an install that hasn't had the helper's one-time setup.

        Returns:
            bool: True if passwordless sudo works, False otherwise
        """
        from . import root_helper
        if root_helper.is_usable():
            return True
        try:
            import shutil, os

            def _canonical(cmd, default):
                """
                Resolve to the real path so sudo's exact-path matching works.
                On Ubuntu 22.04+, /bin is a symlink to /usr/bin, but sudo
                checks the literal path in sudoers — so we must use /usr/bin/*.
                """
                found = shutil.which(cmd)
                if found:
                    try:
                        return os.path.realpath(found)
                    except Exception:
                        return found
                return default

            systemd_run = _canonical('systemd-run', '/usr/bin/systemd-run')

            service_name = self.service_name or 'clientst0r-gunicorn.service'
            systemctl = _canonical('systemctl', '/usr/bin/systemctl')

            # Probes in order of how closely they model what the updater needs.
            # `systemctl status` is read-only and is what a scoped ruleset will
            # realistically grant; systemd-run is kept only for older sudoers
            # files that granted it bare.
            probes = (
                [systemctl, 'status', service_name],
                [systemd_run, '--version'],
            )

            for probe in probes:
                try:
                    result = subprocess.run(
                        ['/usr/bin/sudo', '-n'] + probe,
                        capture_output=True, text=True, timeout=5,
                    )
                except Exception:
                    continue
                denied = ('password is required' in result.stderr
                          or 'a terminal is required' in result.stderr
                          or 'not allowed to execute' in result.stderr)
                if denied:
                    # This probe is not granted — that says nothing about the
                    # others, so keep going rather than concluding here.
                    continue
                # `systemctl status` exits non-zero for an inactive unit, which
                # still proves sudo let the command run.
                return True

            return False
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
