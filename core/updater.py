"""
Auto-update service for Client St0r.

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

    # v3.17.482 — cache TTL for /tags polls. GitHub's anonymous limit
    # is 60/hour; with TTL=300 we touch GitHub at most 12 times/hour
    # even if Settings → Updates is open in 10 browser tabs.
    _CACHE_KEY_SUCCESS = 'system_update_check'
    _CACHE_KEY_LAST_GOOD = 'system_update_check_last_good'
    _CACHE_TTL_SUCCESS = 300       # 5 min — successful result
    _CACHE_TTL_RATELIMITED = 600   # 10 min — back off harder on 403

    def check_for_updates(self, *, force_refresh=False):
        """
        Check GitHub for new versions by comparing git tags.

        v3.17.482 — short-TTL cache stops the GitHub /tags endpoint from
        being hammered on every Settings → Updates page load. The
        previous "Uses caching" docstring was aspirational; this is the
        first version that actually does it.

        Returns:
            dict with 'update_available', 'latest_version', 'current_version',
            'release_url', 'release_notes'
        """
        from django.core.cache import cache

        if not force_refresh:
            cached = cache.get(self._CACHE_KEY_SUCCESS)
            if cached is not None:
                cached = dict(cached)
                cached['from_cache'] = True
                return cached

        logger.info(f"Starting update check. Current version: {self.current_version}")

        try:
            # Get all tags from GitHub API (sorted by date, most recent first)
            url = f'{self.github_api}/{self.repo_owner}/{self.repo_name}/tags'
            logger.info(f"Fetching tags from: {url}")

            response = requests.get(url, headers=self._get_github_headers(), timeout=30)
            logger.info(f"GitHub API response status: {response.status_code}")

            # Check for rate limit before raising
            if response.status_code == 403:
                rate_limit_remaining = response.headers.get('X-RateLimit-Remaining', '0')
                if rate_limit_remaining == '0':
                    reset_time = response.headers.get('X-RateLimit-Reset', 'unknown')
                    logger.error(f"GitHub API rate limit exceeded. Resets at: {reset_time}")
                    # If we have a recent good result cached, return that
                    # with a stale flag so the UI keeps working through
                    # the rate-limit window.
                    last_good = cache.get(self._CACHE_KEY_LAST_GOOD)
                    if last_good is not None:
                        out = dict(last_good)
                        out['from_cache'] = True
                        out['stale'] = True
                        out['rate_limit'] = True
                        return out
                    # Cache the rate-limit response too so we don't
                    # immediately retry and burn another request.
                    payload = {
                        'update_available': False,
                        'latest_version': None,
                        'current_version': self.current_version,
                        'error': 'GitHub API rate limit exceeded. Please try again later or set GITHUB_TOKEN environment variable for higher limits.',
                        'checked_at': timezone.now().isoformat(),
                        'rate_limit': True,
                    }
                    cache.set(self._CACHE_KEY_SUCCESS, payload,
                              self._CACHE_TTL_RATELIMITED)
                    return payload

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
                except Exception:
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
                    headers=self._get_github_headers(),
                    timeout=15
                )
                if release_response.status_code == 200:
                    release_data = release_response.json()
                    release_notes = release_data.get('body', 'No release notes available')
                    published_at = release_data.get('published_at')
            except Exception as e:
                logger.debug(f"Could not fetch release notes: {e}")
                pass  # Release doesn't exist or network issue, that's ok

            result = {
                'update_available': update_available,
                'latest_version': latest_version,
                'current_version': self.current_version,
                'release_url': release_url,
                'release_notes': release_notes,
                'published_at': published_at,
                'checked_at': timezone.now().isoformat(),
            }
            # v3.17.482 — cache the success so subsequent polls within
            # 5 min are answered from memory; ALSO cache as the
            # "last good" so a future 403 can return stale-but-useful.
            cache.set(self._CACHE_KEY_SUCCESS, result, self._CACHE_TTL_SUCCESS)
            cache.set(self._CACHE_KEY_LAST_GOOD, result, 24 * 3600)
            return result

        except requests.Timeout as e:
            logger.warning(f"GitHub API timeout while checking for updates: {e}")
            return {
                'update_available': False,
                'latest_version': None,
                'current_version': self.current_version,
                'error': 'Unable to reach GitHub API (connection timeout). Please check your internet connection or try again later.',
                'error_type': 'timeout',
                'checked_at': timezone.now().isoformat(),
            }
        except requests.ConnectionError as e:
            logger.warning(f"GitHub API connection error while checking for updates: {e}")
            return {
                'update_available': False,
                'latest_version': None,
                'current_version': self.current_version,
                'error': 'Unable to connect to GitHub. Please check your internet connection or firewall settings.',
                'error_type': 'connection',
                'checked_at': timezone.now().isoformat(),
            }
        except requests.RequestException as e:
            logger.error(f"Failed to check for updates: {e}")
            return {
                'update_available': False,
                'latest_version': None,
                'current_version': self.current_version,
                'error': f'Error checking for updates: {str(e)}',
                'error_type': 'general',
                'checked_at': timezone.now().isoformat(),
            }

    def perform_update(self, user=None, progress_tracker=None):
        """
        Perform full system update.

        Downloads update_instructions.sh from GitHub and executes it, streaming
        output line-by-line.  If the script has a bug, push a fix to GitHub —
        the next update attempt downloads the fixed script automatically without
        needing a code-version bump.

        Returns:
            dict with 'success', 'steps_completed', 'output', 'error'
        """
        result = {
            'success': False,
            'steps_completed': [],
            'output': [],
            'error': None,
        }

        script_path = None

        try:
            # Pre-check: Verify passwordless sudo is configured (if running under systemd)
            if self._is_systemd_service():
                if not self._check_passwordless_sudo():
                    service_name = self.service_name or 'clientst0r-gunicorn.service'
                    raise Exception(
                        "Passwordless sudo is not configured for auto-updates. "
                        "Please configure it by running these commands:\n\n"
                        "sudo tee /etc/sudoers.d/clientst0r-auto-update > /dev/null <<SUDOERS\n"
                        f"$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload {service_name}, "
                        f"/usr/bin/systemctl restart {service_name}, "
                        f"/usr/bin/systemctl stop {service_name}, /usr/bin/systemctl start {service_name}, "
                        f"/usr/bin/systemctl status {service_name}, /usr/bin/systemctl daemon-reload, "
                        # v3.17.520: `systemd-run`, `pkill`, `tee`, `cp` and `chmod`
                        # were all listed bare. Any one of them granted without
                        # arguments is root in all but name — systemd-run runs any
                        # command as root, tee/cp write any file. Pinned to the exact
                        # invocations the updater issues.
                        f"/usr/bin/systemd-run --on-active=3 --system /usr/bin/systemctl restart {service_name}\n"
                        "SUDOERS\n\n"
                        "sudo chmod 0440 /etc/sudoers.d/clientst0r-auto-update\n\n"
                        "After configuring, refresh this page and try again. "
                        "Or update manually via command line (see instructions below)."
                    )

            # Step 1: Download update instructions from GitHub
            script_url = (
                f'https://raw.githubusercontent.com/'
                f'{self.repo_owner}/{self.repo_name}/main/deploy/update_instructions.sh'
            )
            logger.info(f"Downloading update instructions from: {script_url}")
            result['output'].append(f"Downloading update instructions from GitHub...")

            response = requests.get(script_url, headers=self._get_github_headers(), timeout=30)
            response.raise_for_status()
            script_content = response.text

            if not script_content.startswith('#!/'):
                raise Exception('Downloaded content is not a valid shell script')

            result['output'].append("Update instructions downloaded successfully")
            result['steps_completed'].append('download_script')

            # Step 2: Write to temp file and make executable
            script_path = f'/tmp/clientst0r_update_{os.getpid()}.sh'
            with open(script_path, 'w') as f:
                f.write(script_content)
            os.chmod(script_path, 0o700)
            logger.info(f"Update script written to: {script_path}")

            # Step 3: Execute — pass context via environment variables

            # Clear cache NOW — before the subprocess runs and restarts the service.
            # The service restart (scheduled inside the script) kills this process,
            # so any cache.delete placed after process.wait() would never run.
            from django.core.cache import cache
            cache.delete('system_update_check')
            logger.info("Cleared system_update_check cache (pre-execution)")

            env = os.environ.copy()
            env['CLIENTST0R_BASE_DIR'] = str(self.base_dir)
            env['CLIENTST0R_SERVICE_NAME'] = self.service_name or ''

            logger.info(
                f"Executing update script with BASE_DIR={self.base_dir}, "
                f"SERVICE={self.service_name}"
            )
            result['output'].append(f"Base directory: {self.base_dir}")

            # Map shell script log markers to the step names the UI progress bar expects.
            # Each tuple: (substring to match, 'start'|'complete', step_name)
            step_triggers = [
                ('Step 1/5: Fetching',               'start',    'Git Pull'),
                ('Step 1/5: Code updated',           'complete', 'Git Pull'),
                ('Step 2/5: Installing',             'start',    'Install Dependencies'),
                ('Step 2/5: Core dependencies',      'complete', 'Install Dependencies'),
                ('Step 3/5: Running database',       'start',    'Run Migrations'),
                ('Step 3/5: Migrations completed',   'complete', 'Run Migrations'),
                ('Step 4/5: Collecting static',      'start',    'Collect Static Files'),
                ('Step 4/5: Static files collected', 'complete', 'Collect Static Files'),
                # v3.17.421 — bash script now writes status=completed to
                # the progress JSON directly before the reload, so the
                # front-end is safe even if `systemctl reload` SIGHUPs
                # this Python reader before it processes the final lines.
                # These triggers are still useful for the live progress
                # log as long as the reader survives.
                ('Step 5/5: Scheduling',             'start',    'Restart Service'),
                ('Step 5/5: Marked progress',        'complete', 'Restart Service'),
                ('Step 5/5: Graceful reload',        'complete', 'Restart Service'),
                ('Update complete!',                 'complete', 'Restart Service'),
            ]

            process = subprocess.Popen(
                ['/bin/bash', script_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,  # line-buffered: emit each line as it arrives
                env=env, cwd=str(self.base_dir)
            )
            for line in iter(process.stdout.readline, ''):
                stripped = line.rstrip()
                if stripped:
                    if progress_tracker:
                        # Single read+write per line: log + step change atomically
                        progress_tracker.process_log_line(stripped, step_triggers)
                    result['output'].append(stripped)
            process.wait()

            if process.returncode != 0:
                raise Exception(
                    f"Update script exited with code {process.returncode}"
                )

            result['steps_completed'].append('execute_script')

            result['success'] = True

        except Exception as e:
            logger.error(f"Update failed: {e}")
            error_msg = str(e)

            result['error'] = error_msg
            result['output'].append(f"ERROR: {error_msg}")

            if progress_tracker:
                progress_tracker.finish(success=False, error=error_msg)

            # v3.17.284 (issue #128): persist the script's recent output
            # into AuditLog.extra_data so superusers can see WHICH migration
            # / step failed without SSHing in. Cap at last 200 lines + 50KB
            # to keep the audit row reasonable.
            recent_output = (result.get('output') or [])[-200:]
            output_blob = '\n'.join(recent_output)
            if len(output_blob) > 50_000:
                output_blob = output_blob[-50_000:]

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
                    'output_tail': output_blob,
                }
            )

        finally:
            # Always clean up the temp script
            if script_path and os.path.exists(script_path):
                try:
                    os.unlink(script_path)
                    logger.info(f"Cleaned up temp script: {script_path}")
                except Exception as cleanup_err:
                    logger.warning(f"Failed to clean up temp script: {cleanup_err}")

        if result['success']:
            # Cache was already cleared before the subprocess ran (see above)

            # Force reload version module to display new version immediately
            try:
                import sys
                import importlib
                if 'config.version' in sys.modules:
                    importlib.reload(sys.modules['config.version'])
                    from config.version import VERSION
                    self.current_version = VERSION
                    logger.info(f"Reloaded version module: {VERSION}")
                    result['output'].append("")
                    result['output'].append("UPDATE SUCCESSFUL!")
                    result['output'].append(f"New version: {VERSION}")
                    result['output'].append(f"Location: {self.base_dir}")
                    result['output'].append("")
                    result['new_version'] = VERSION
            except Exception as e:
                logger.warning(f"Failed to reload version module: {e}")

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

        Returns:
            bool: True if passwordless sudo works, False otherwise
        """
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
