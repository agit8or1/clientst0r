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
        self.base_dir = settings.BASE_DIR

    def get_current_version(self):
        """Get current installed version."""
        try:
            from config.version import VERSION
            return VERSION
        except ImportError:
            return '0.0.0'

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

    def check_for_updates(self):
        """
        Check GitHub for new versions by comparing git tags.
        Uses caching to avoid rate limits.

        Returns:
            dict with 'update_available', 'latest_version', 'current_version',
            'release_url', 'release_notes'
        """
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
                    return {
                        'update_available': False,
                        'latest_version': None,
                        'current_version': self.current_version,
                        'error': 'GitHub API rate limit exceeded. Please try again later or set GITHUB_TOKEN environment variable for higher limits.',
                        'checked_at': timezone.now().isoformat(),
                        'rate_limit': True
                    }

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

            return {
                'update_available': update_available,
                'latest_version': latest_version,
                'current_version': self.current_version,
                'release_url': release_url,
                'release_notes': release_notes,
                'published_at': published_at,
                'checked_at': timezone.now().isoformat(),
            }

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
                        "sudo tee /etc/sudoers.d/clientst0r-auto-update > /dev/null <<SUDOERS\n"
                        f"$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart huduglue-gunicorn.service, "
                        "/usr/bin/systemctl stop huduglue-gunicorn.service, /usr/bin/systemctl start huduglue-gunicorn.service, "
                        "/usr/bin/systemctl status huduglue-gunicorn.service, /usr/bin/systemctl daemon-reload, "
                        "/usr/bin/systemd-run, /usr/bin/pkill, "
                        "/usr/bin/tee /etc/systemd/system/huduglue-gunicorn.service, "
                        "/usr/bin/cp, /usr/bin/chmod\n"
                        "SUDOERS\n\n"
                        "sudo chmod 0440 /etc/sudoers.d/clientst0r-auto-update\n\n"
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
                # Updates are available - use reset --hard for reliability
                # This avoids git pull configuration issues and works in all scenarios
                logger.info("Updates available - resetting to remote version")
                result['output'].append("Updating to latest version...")

                git_output = self._run_command(['/usr/bin/git', 'reset', '--hard', 'origin/main'])
                result['output'].append(f"Git reset: {git_output}")

                # Check if it was a force push (informational only)
                try:
                    self._run_command(['/usr/bin/git', 'merge-base', '--is-ancestor', f'{local_commit}', 'origin/main'])
                    result['output'].append("✓ Fast-forward update applied")
                except:
                    result['output'].append("⚠️ Repository history changed (force push detected)")
                    result['output'].append("✓ Reset to remote version successful")
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

            # Install main requirements
            pip_output = self._run_command([
                'pip', 'install', '-r',
                os.path.join(self.base_dir, 'requirements.txt')
                # Note: Removed --upgrade to avoid rebuilding compiled packages like python-ldap
                # Git pull already brought new code, we only need to install missing packages
            ])
            result['steps_completed'].append('install_requirements')
            result['output'].append(f"Pip install: {pip_output[:500]}")  # Truncate output

            # Install optional dependencies if they exist
            optional_requirements = [
                'requirements-graphql.txt',
                'requirements-optional.txt'
            ]
            for req_file in optional_requirements:
                req_path = os.path.join(self.base_dir, req_file)
                if os.path.exists(req_path):
                    logger.info(f"Installing optional dependencies from {req_file}")
                    try:
                        optional_pip_output = self._run_command([
                            'pip', 'install', '-r', req_path
                        ])
                        result['output'].append(f"Optional dependencies ({req_file}): Installed")
                        logger.info(f"Successfully installed {req_file}")
                    except Exception as e:
                        # Optional dependencies - log warning but continue
                        logger.warning(f"Failed to install {req_file} (non-critical): {e}")
                        result['output'].append(f"⚠️ Optional dependencies ({req_file}): Skipped - {str(e)}")

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

            # Step 3.5: Apply Gunicorn environment fix (if script exists)
            fix_script_path = os.path.join(self.base_dir, 'scripts', 'fix_gunicorn_env.sh')
            if os.path.exists(fix_script_path):
                if progress_tracker:
                    progress_tracker.step_start('Apply Gunicorn Fix')
                logger.info("Running Gunicorn environment fix script")
                try:
                    # Make script executable if it isn't already
                    os.chmod(fix_script_path, 0o755)

                    # Run the fix script (it has its own sudo commands inside)
                    fix_output = self._run_command([fix_script_path])
                    result['steps_completed'].append('gunicorn_fix')
                    result['output'].append(f"Gunicorn fix: {fix_output}")
                    logger.info("Gunicorn fix applied successfully")
                except Exception as e:
                    # Non-critical - log warning but continue
                    logger.warning(f"Gunicorn fix failed (non-critical): {e}")
                    result['output'].append(f"⚠️ Gunicorn fix skipped: {str(e)}")
                if progress_tracker:
                    progress_tracker.step_complete('Apply Gunicorn Fix')

            # Step 3.6: Setup mobile app building (if script exists)
            mobile_setup_script = os.path.join(self.base_dir, 'deploy', 'setup_mobile_build.sh')
            if os.path.exists(mobile_setup_script):
                if progress_tracker:
                    progress_tracker.step_start('Setup Mobile Build')
                logger.info("Configuring mobile app building")
                try:
                    os.chmod(mobile_setup_script, 0o755)
                    mobile_setup_output = self._run_command([mobile_setup_script])
                    result['steps_completed'].append('mobile_build_setup')
                    result['output'].append(f"Mobile build setup: Complete")
                    logger.info("Mobile app building configured")
                except Exception as e:
                    # Non-critical - log warning but continue
                    logger.warning(f"Mobile build setup failed (non-critical): {e}")
                    result['output'].append(f"⚠️ Mobile build setup skipped: {str(e)}")
                if progress_tracker:
                    progress_tracker.step_complete('Setup Mobile Build')
            else:
                logger.info("Mobile build setup script not found - skipping")

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

            # Step 5: Generate diagram previews for any diagrams without them
            if progress_tracker:
                progress_tracker.step_start('Generate Diagram Previews')
            logger.info("Generating diagram previews...")
            try:
                preview_output = self._run_command([
                    self._get_python_path(), 'manage.py', 'generate_diagram_previews', '--force'
                ], timeout=60)
                result['steps_completed'].append('generate_diagram_previews')
                result['output'].append(f"✓ Diagram previews generated")
                logger.info(f"Diagram preview generation: {preview_output[:200]}")
            except Exception as e:
                # Non-critical, continue with update
                logger.warning(f"Diagram preview generation failed (non-critical): {e}")
                result['output'].append(f"⚠ Diagram preview generation skipped: {str(e)[:100]}")
            if progress_tracker:
                progress_tracker.step_complete('Generate Diagram Previews')

            # Step 6: Generate workflow diagrams for workflows without diagrams
            if progress_tracker:
                progress_tracker.step_start('Generate Workflow Diagrams')
            logger.info("Generating workflow diagrams...")
            try:
                workflow_output = self._run_command([
                    self._get_python_path(), 'manage.py', 'generate_workflow_diagrams'
                ], timeout=60)
                result['steps_completed'].append('generate_workflow_diagrams')
                result['output'].append(f"✓ Workflow diagrams generated")
                logger.info(f"Workflow diagram generation: {workflow_output[:200]}")
            except Exception as e:
                # Non-critical, continue with update
                logger.warning(f"Workflow diagram generation failed (non-critical): {e}")
                result['output'].append(f"⚠ Workflow diagram generation skipped: {str(e)[:100]}")
            if progress_tracker:
                progress_tracker.step_complete('Generate Workflow Diagrams')

            # Step 7: Install fail2ban sudoers configuration (if needed)
            if progress_tracker:
                progress_tracker.step_start('Configure Fail2ban Integration')
            logger.info("Checking fail2ban configuration...")
            try:
                # Check if fail2ban is installed
                fail2ban_check = subprocess.run(
                    ['/usr/bin/which', 'fail2ban-client'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if fail2ban_check.returncode == 0:
                    # fail2ban is installed, check if sudoers is configured
                    sudoers_path = '/etc/sudoers.d/clientst0r-fail2ban'
                    if not os.path.exists(sudoers_path):
                        logger.info("fail2ban installed but sudoers not configured - installing...")

                        # Copy sudoers file from deploy directory
                        source_path = os.path.join(self.base_dir, 'deploy', 'clientst0r-fail2ban-sudoers')
                        if os.path.exists(source_path):
                            # Install sudoers file
                            copy_result = subprocess.run(
                                ['/usr/bin/sudo', '/usr/bin/cp', source_path, sudoers_path],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )

                            if copy_result.returncode == 0:
                                # Set correct permissions
                                chmod_result = subprocess.run(
                                    ['/usr/bin/sudo', '/usr/bin/chmod', '0440', sudoers_path],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )

                                if chmod_result.returncode == 0:
                                    result['steps_completed'].append('fail2ban_sudoers')
                                    result['output'].append("✓ Fail2ban sudoers configuration installed automatically")
                                    logger.info("Fail2ban sudoers configuration installed successfully")
                                else:
                                    logger.warning(f"Failed to set sudoers permissions: {chmod_result.stderr}")
                                    result['output'].append("⚠ Fail2ban sudoers installed but permissions not set - please run: sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban")
                            else:
                                logger.warning(f"Failed to copy sudoers file: {copy_result.stderr}")
                                result['output'].append(f"⚠ Fail2ban sudoers installation failed: {copy_result.stderr[:100]}")
                        else:
                            logger.warning("Fail2ban sudoers source file not found")
                            result['output'].append("⚠ Fail2ban sudoers source file not found in deploy/ directory")
                    else:
                        logger.info("Fail2ban sudoers already configured")
                        result['output'].append("✓ Fail2ban sudoers already configured")
                else:
                    logger.info("fail2ban not installed - skipping sudoers configuration")
                    result['output'].append("• Fail2ban not installed - sudoers configuration skipped")

            except Exception as e:
                # Non-critical - log warning but continue
                logger.warning(f"Fail2ban configuration check failed (non-critical): {e}")
                result['output'].append(f"⚠ Fail2ban configuration check skipped: {str(e)[:100]}")

            if progress_tracker:
                progress_tracker.step_complete('Configure Fail2ban Integration')

            # Step 7.5: Regenerate and install sudoers files with correct paths
            if progress_tracker:
                progress_tracker.step_start('Update Sudoers Configuration')
            logger.info("Regenerating sudoers files with correct paths...")
            try:
                import getpass
                current_user = getpass.getuser()
                install_dir = str(self.base_dir)

                # Create deploy directory if it doesn't exist
                deploy_dir = os.path.join(install_dir, 'deploy')
                os.makedirs(deploy_dir, exist_ok=True)

                # Generate clientst0r-install-sudoers
                install_sudoers_content = f"""# Sudoers configuration for Client St0r automatic fail2ban installation
# Install: sudo cp {install_dir}/deploy/clientst0r-install-sudoers /etc/sudoers.d/clientst0r-install
# Permissions: sudo chmod 0440 /etc/sudoers.d/clientst0r-install

# Allow {current_user} user to install and configure fail2ban without password
{current_user} ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
{current_user} ALL=(ALL) NOPASSWD: /usr/bin/apt-get install -y fail2ban
{current_user} ALL=(ALL) NOPASSWD: /bin/systemctl enable fail2ban
{current_user} ALL=(ALL) NOPASSWD: /bin/systemctl start fail2ban
{current_user} ALL=(ALL) NOPASSWD: /bin/systemctl status fail2ban
{current_user} ALL=(ALL) NOPASSWD: /bin/cp {install_dir}/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban
{current_user} ALL=(ALL) NOPASSWD: /bin/chmod 0440 /etc/sudoers.d/clientst0r-fail2ban
"""

                # Generate clientst0r-fail2ban-sudoers
                fb_sudoers_content = f"""# Sudoers configuration for Client St0r fail2ban integration
# Install: sudo cp {install_dir}/deploy/clientst0r-fail2ban-sudoers /etc/sudoers.d/clientst0r-fail2ban
# Permissions: sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban

# Allow {current_user} user to run fail2ban-client without password
{current_user} ALL=(ALL) NOPASSWD: /usr/bin/fail2ban-client
"""

                # Write files
                install_sudoers_path = os.path.join(deploy_dir, 'clientst0r-install-sudoers')
                fb_sudoers_path = os.path.join(deploy_dir, 'clientst0r-fail2ban-sudoers')

                with open(install_sudoers_path, 'w') as f:
                    f.write(install_sudoers_content)
                with open(fb_sudoers_path, 'w') as f:
                    f.write(fb_sudoers_content)

                logger.info("Sudoers files regenerated successfully")
                result['output'].append(f"✓ Sudoers files regenerated for user: {current_user}")

                # Now install them if needed
                install_needed = []

                # Check clientst0r-install
                install_dest = '/etc/sudoers.d/clientst0r-install'
                if not os.path.exists(install_dest):
                    install_needed.append(('clientst0r-install', install_sudoers_path, install_dest))
                else:
                    # Check if content differs
                    try:
                        with open(install_dest, 'r') as f:
                            existing_content = f.read()
                        if existing_content != install_sudoers_content:
                            install_needed.append(('clientst0r-install', install_sudoers_path, install_dest))
                    except:
                        pass

                # Check clientst0r-fail2ban
                fb_dest = '/etc/sudoers.d/clientst0r-fail2ban'
                if not os.path.exists(fb_dest):
                    install_needed.append(('clientst0r-fail2ban', fb_sudoers_path, fb_dest))
                else:
                    # Check if content differs
                    try:
                        with open(fb_dest, 'r') as f:
                            existing_content = f.read()
                        if existing_content != fb_sudoers_content:
                            install_needed.append(('clientst0r-fail2ban', fb_sudoers_path, fb_dest))
                    except:
                        pass

                # Install files that need updating
                if install_needed:
                    result['output'].append("📝 Installing sudoers files (requires passwordless sudo)...")
                    install_success_count = 0
                    install_fail_count = 0

                    for name, source, dest in install_needed:
                        try:
                            # Copy file
                            copy_result = subprocess.run(
                                ['/usr/bin/sudo', '/usr/bin/cp', source, dest],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )

                            if copy_result.returncode == 0:
                                # Set permissions
                                chmod_result = subprocess.run(
                                    ['/usr/bin/sudo', '/usr/bin/chmod', '0440', dest],
                                    capture_output=True,
                                    text=True,
                                    timeout=10
                                )

                                if chmod_result.returncode == 0:
                                    result['steps_completed'].append(f'install_{name}_sudoers')
                                    result['output'].append(f"  ✓ {name} sudoers installed successfully")
                                    logger.info(f"{name} sudoers installed successfully")
                                    install_success_count += 1
                                else:
                                    logger.warning(f"Failed to set {name} sudoers permissions: {chmod_result.stderr}")
                                    result['output'].append(f"  ⚠ {name} installed but permissions not set: {chmod_result.stderr[:50]}")
                                    install_fail_count += 1
                            else:
                                error_msg = copy_result.stderr.strip() if copy_result.stderr else 'Unknown error'
                                logger.warning(f"Failed to copy {name} sudoers: {error_msg}")
                                if 'password' in error_msg.lower() or 'sudo' in error_msg.lower():
                                    result['output'].append(f"  ✗ {name} FAILED - passwordless sudo not configured")
                                    result['output'].append(f"     Run CLI update first: cd {install_dir} && ./update.sh")
                                else:
                                    result['output'].append(f"  ✗ {name} FAILED: {error_msg[:70]}")
                                install_fail_count += 1
                        except subprocess.TimeoutExpired:
                            logger.warning(f"Timeout installing {name} sudoers - may be waiting for password")
                            result['output'].append(f"  ✗ {name} TIMED OUT - likely waiting for sudo password")
                            result['output'].append(f"     Run CLI update first: cd {install_dir} && ./update.sh")
                            install_fail_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to install {name} sudoers: {e}")
                            result['output'].append(f"  ✗ {name} ERROR: {str(e)[:60]}")
                            install_fail_count += 1

                    # Summary message
                    if install_fail_count > 0:
                        result['output'].append("")
                        result['output'].append(f"⚠ WARNING: {install_fail_count} sudoers file(s) failed to install")
                        result['output'].append("Some features may require manual sudo password entry.")
                        result['output'].append(f"Fix: Run './update.sh' from {install_dir} to configure sudoers properly")
                else:
                    result['output'].append("✓ Sudoers files already up to date")
                    logger.info("Sudoers files already up to date")

            except Exception as e:
                # Non-critical - log warning but continue
                logger.warning(f"Sudoers configuration update failed (non-critical): {e}")
                result['output'].append(f"⚠ Sudoers configuration update skipped: {str(e)[:100]}")

            if progress_tracker:
                progress_tracker.step_complete('Update Sudoers Configuration')

            # Step 8: Restart service (if running under systemd)
            is_systemd = self._is_systemd_service()
            logger.info(f"Systemd service check result: {is_systemd}")

            if is_systemd:
                if progress_tracker:
                    progress_tracker.step_start('Restart Service')
                logger.info("Restarting systemd service")

                try:
                    # Reload systemd daemon first to pick up any service file changes
                    try:
                        daemon_reload = self._run_command(['/usr/bin/sudo', '/usr/bin/systemctl', 'daemon-reload'])
                        logger.info(f"Systemd daemon reloaded: {daemon_reload}")
                        result['output'].append("✓ Systemd daemon reloaded")
                    except Exception as e:
                        logger.warning(f"Daemon reload failed (non-critical): {e}")

                    # ENHANCED RESTART: Stop service, kill processes, clear cache, start fresh
                    # This ensures Python imports are not cached in memory
                    logger.info("Performing enhanced service restart with cache cleanup")

                    # Step 1: Stop the service
                    stop_output = self._run_command([
                        '/usr/bin/sudo', '/usr/bin/systemctl', 'stop', 'huduglue-gunicorn.service'
                    ])
                    logger.info(f"Service stopped: {stop_output}")
                    result['output'].append("✓ Service stopped")

                    # Step 2: Kill any lingering gunicorn processes (ensures no cached imports)
                    try:
                        kill_output = self._run_command([
                            '/usr/bin/sudo', '/usr/bin/pkill', '-9', '-f', 'gunicorn'
                        ])
                        logger.info(f"Gunicorn processes killed: {kill_output}")
                        result['output'].append("✓ Cleared all gunicorn processes")
                    except Exception as e:
                        # This is OK if no processes found
                        logger.info(f"No gunicorn processes to kill (normal): {e}")

                    # Step 3: Clear Python bytecode cache
                    import shutil
                    cache_cleared = 0
                    try:
                        for root, dirs, files in os.walk(self.base_dir):
                            # Skip venv directory
                            if 'venv' in root or 'node_modules' in root:
                                continue
                            # Remove __pycache__ directories
                            if '__pycache__' in dirs:
                                cache_dir = os.path.join(root, '__pycache__')
                                shutil.rmtree(cache_dir, ignore_errors=True)
                                cache_cleared += 1
                            # Remove .pyc files
                            for file in files:
                                if file.endswith('.pyc'):
                                    os.remove(os.path.join(root, file))
                        logger.info(f"Cleared {cache_cleared} __pycache__ directories")
                        result['output'].append(f"✓ Cleared Python bytecode cache ({cache_cleared} directories)")
                    except Exception as e:
                        logger.warning(f"Cache cleanup warning (non-critical): {e}")

                    # Step 4: Start service fresh (delayed to allow this response to complete)
                    restart_output = self._run_command([
                        '/usr/bin/sudo', '/usr/bin/systemd-run', '--on-active=2',
                        '/usr/bin/systemctl', 'start', 'huduglue-gunicorn.service'
                    ])
                    logger.info(f"Service start scheduled: {restart_output}")
                    result['steps_completed'].append('restart_service')
                    result['output'].append(f"✓ Service restart scheduled with full cleanup (2s delay)")
                    result['output'].append("⚠️  Please wait 10 seconds, then refresh the page to see the new version")
                    if progress_tracker:
                        progress_tracker.step_complete('Restart Service')
                except Exception as e:
                    error_msg = str(e)
                    if 'password is required' in error_msg or 'terminal is required' in error_msg:
                        raise Exception(
                            "Passwordless sudo is not configured. Auto-update requires passwordless sudo "
                            "to restart the service. Please configure it by running:\n\n"
                            "sudo tee /etc/sudoers.d/clientst0r-auto-update > /dev/null <<SUDOERS\n"
                            f"$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart huduglue-gunicorn.service, "
                            "/usr/bin/systemctl stop huduglue-gunicorn.service, /usr/bin/systemctl start huduglue-gunicorn.service, "
                            "/usr/bin/systemctl status huduglue-gunicorn.service, /usr/bin/systemctl daemon-reload, "
                            "/usr/bin/systemd-run, /usr/bin/pkill, "
                            "/usr/bin/tee /etc/systemd/system/huduglue-gunicorn.service, "
                            "/usr/bin/cp, /usr/bin/chmod\n"
                            "SUDOERS\n\n"
                            "sudo chmod 0440 /etc/sudoers.d/clientst0r-auto-update\n\n"
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
                    "sudo systemctl restart clientst0r-gunicorn.service\n\n"
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
                ['/usr/bin/systemctl', 'is-active', 'clientst0r-gunicorn.service'],
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
                ['/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'status', 'clientst0r-gunicorn.service'],
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
