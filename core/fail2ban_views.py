"""
Fail2ban integration views
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
import subprocess
import re
import logging

logger = logging.getLogger('core')


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


def run_fail2ban_command(command):
    """
    Run fail2ban-client command safely.

    Returns:
        tuple: (success: bool, output: str, error: str)
    """
    try:
        result = subprocess.run(
            ['sudo', '/usr/bin/fail2ban-client'] + command,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, '', 'Command timed out'
    except FileNotFoundError:
        return False, '', 'fail2ban-client not found - is fail2ban installed?'
    except Exception as e:
        return False, '', str(e)


def is_fail2ban_installed():
    """
    Check if fail2ban is installed and accessible.

    Returns:
        tuple: (installed: bool, running: bool, sudo_configured: bool, error_message: str)
    """
    # Check if fail2ban package is installed
    try:
        result = subprocess.run(
            ['dpkg', '-l', 'fail2ban'],
            capture_output=True,
            text=True,
            timeout=5
        )
        package_installed = result.returncode == 0 and 'ii' in result.stdout
    except Exception:
        package_installed = False

    if not package_installed:
        return False, False, False, 'fail2ban package not installed'

    # Check if fail2ban service exists and is running
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'fail2ban'],
            capture_output=True,
            text=True,
            timeout=5
        )
        service_running = result.returncode == 0 and result.stdout.strip() == 'active'
    except Exception:
        service_running = False

    # Check if sudo permissions are configured
    success, output, error = run_fail2ban_command(['ping'])
    sudo_configured = success

    return package_installed, service_running, sudo_configured, ''


@login_required
@user_passes_test(is_superuser)
def fail2ban_status(request):
    """Fail2ban status and management page."""

    # Get sudoers paths for installation instructions
    install_sudoers_path = settings.BASE_DIR / 'deploy' / 'huduglue-install-sudoers'
    fail2ban_sudoers_path = settings.BASE_DIR / 'deploy' / 'huduglue-fail2ban-sudoers'

    # Check if fail2ban is installed
    package_installed, service_running, sudo_configured, error_msg = is_fail2ban_installed()

    if not package_installed:
        context = {
            'fail2ban_installed': False,
            'fail2ban_running': False,
            'sudo_configured': False,
            'install_sudoers_path': install_sudoers_path,
            'fail2ban_sudoers_path': fail2ban_sudoers_path,
        }
        return render(request, 'core/fail2ban_status.html', context)

    # If installed but sudo not configured, show configuration instructions
    if not sudo_configured:
        context = {
            'fail2ban_installed': True,
            'fail2ban_running': service_running,
            'sudo_configured': False,
            'install_sudoers_path': install_sudoers_path,
            'fail2ban_sudoers_path': fail2ban_sudoers_path,
        }
        messages.warning(
            request,
            f'Fail2ban is installed but sudo access not configured. Run: sudo cp {fail2ban_sudoers_path} /etc/sudoers.d/huduglue-fail2ban && sudo chmod 0440 /etc/sudoers.d/huduglue-fail2ban'
        )
        return render(request, 'core/fail2ban_status.html', context)

    # If not running, show warning
    if not service_running:
        context = {
            'fail2ban_installed': True,
            'fail2ban_running': False,
            'sudo_configured': True,
            'install_sudoers_path': install_sudoers_path,
            'fail2ban_sudoers_path': fail2ban_sudoers_path,
        }
        messages.warning(
            request,
            'Fail2ban is installed but not running. Start it with: sudo systemctl start fail2ban'
        )
        return render(request, 'core/fail2ban_status.html', context)

    # Get fail2ban status
    success, output, error = run_fail2ban_command(['status'])

    if not success:
        messages.error(request, f'Failed to get fail2ban status: {error}')
        context = {
            'fail2ban_installed': True,
            'fail2ban_running': False,
            'sudo_configured': True,
            'install_sudoers_path': install_sudoers_path,
            'fail2ban_sudoers_path': fail2ban_sudoers_path,
        }
        return render(request, 'core/fail2ban_status.html', context)

    # Parse jails from status output
    jails = []
    lines = output.split('\n')
    for line in lines:
        if 'Jail list:' in line:
            # Extract jail names
            jail_line = line.split('Jail list:')[1].strip()
            jail_names = [j.strip() for j in jail_line.split(',') if j.strip()]

            # Get detailed status for each jail
            for jail_name in jail_names:
                jail_success, jail_output, jail_error = run_fail2ban_command(['status', jail_name])
                if jail_success:
                    # Parse jail details
                    currently_banned = 0
                    total_banned = 0
                    banned_ips = []

                    for jail_line in jail_output.split('\n'):
                        if 'Currently banned:' in jail_line:
                            try:
                                currently_banned = int(jail_line.split(':')[1].strip())
                            except (ValueError, IndexError):
                                pass
                        elif 'Total banned:' in jail_line:
                            try:
                                total_banned = int(jail_line.split(':')[1].strip())
                            except (ValueError, IndexError):
                                pass
                        elif 'Banned IP list:' in jail_line:
                            ip_list = jail_line.split(':')[1].strip()
                            if ip_list:
                                banned_ips = [ip.strip() for ip in ip_list.split() if ip.strip()]

                    jails.append({
                        'name': jail_name,
                        'currently_banned': currently_banned,
                        'total_banned': total_banned,
                        'banned_ips': banned_ips,
                    })

    # Calculate totals
    total_currently_banned = sum(j['currently_banned'] for j in jails)
    total_all_time_banned = sum(j['total_banned'] for j in jails)

    context = {
        'fail2ban_installed': True,
        'fail2ban_running': True,
        'sudo_configured': True,
        'jails': jails,
        'total_currently_banned': total_currently_banned,
        'total_all_time_banned': total_all_time_banned,
        'install_sudoers_path': install_sudoers_path,
        'fail2ban_sudoers_path': fail2ban_sudoers_path,
    }

    return render(request, 'core/fail2ban_status.html', context)


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_unban_ip(request):
    """Unban an IP address from a jail."""
    ip_address = request.POST.get('ip_address', '').strip()
    jail_name = request.POST.get('jail_name', '').strip()

    if not ip_address or not jail_name:
        messages.error(request, 'IP address and jail name are required.')
        return redirect('core:fail2ban_status')

    # Validate IP address format
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(ip_pattern, ip_address):
        messages.error(request, 'Invalid IP address format.')
        return redirect('core:fail2ban_status')

    # Unban the IP
    success, output, error = run_fail2ban_command(['set', jail_name, 'unbanip', ip_address])

    if success:
        messages.success(request, f'Successfully unbanned {ip_address} from {jail_name} jail.')
        logger.info(f"User {request.user.username} unbanned IP {ip_address} from {jail_name}")
    else:
        messages.error(request, f'Failed to unban {ip_address}: {error}')

    return redirect('core:fail2ban_status')


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_unban_all(request):
    """Unban all IPs from a specific jail."""
    jail_name = request.POST.get('jail_name', '').strip()

    if not jail_name:
        messages.error(request, 'Jail name is required.')
        return redirect('core:fail2ban_status')

    # Get list of banned IPs
    success, output, error = run_fail2ban_command(['status', jail_name])
    if not success:
        messages.error(request, f'Failed to get jail status: {error}')
        return redirect('core:fail2ban_status')

    # Parse banned IPs
    banned_ips = []
    for line in output.split('\n'):
        if 'Banned IP list:' in line:
            ip_list = line.split(':')[1].strip()
            if ip_list:
                banned_ips = [ip.strip() for ip in ip_list.split() if ip.strip()]
            break

    # Unban each IP
    unbanned_count = 0
    for ip in banned_ips:
        success, output, error = run_fail2ban_command(['set', jail_name, 'unbanip', ip])
        if success:
            unbanned_count += 1

    if unbanned_count > 0:
        messages.success(request, f'Unbanned {unbanned_count} IP(s) from {jail_name} jail.')
        logger.info(f"User {request.user.username} unbanned {unbanned_count} IPs from {jail_name}")
    else:
        messages.info(request, f'No IPs to unban from {jail_name} jail.')

    return redirect('core:fail2ban_status')


@login_required
@user_passes_test(is_superuser)
def fail2ban_check_ip(request):
    """Check if an IP is banned (AJAX endpoint)."""
    ip_address = request.GET.get('ip', '').strip()

    if not ip_address:
        return JsonResponse({'error': 'IP address required'}, status=400)

    # Check all jails for this IP
    success, status_output, error = run_fail2ban_command(['status'])
    if not success:
        return JsonResponse({'error': 'Failed to get fail2ban status'}, status=500)

    # Parse jail names
    jail_names = []
    for line in status_output.split('\n'):
        if 'Jail list:' in line:
            jail_line = line.split('Jail list:')[1].strip()
            jail_names = [j.strip() for j in jail_line.split(',') if j.strip()]
            break

    # Check each jail
    banned_in_jails = []
    for jail_name in jail_names:
        success, output, error = run_fail2ban_command(['status', jail_name])
        if success and ip_address in output:
            banned_in_jails.append(jail_name)

    return JsonResponse({
        'ip_address': ip_address,
        'is_banned': len(banned_in_jails) > 0,
        'jails': banned_in_jails,
    })


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_start(request):
    """Start fail2ban service."""
    import os

    try:
        # Set up environment with system paths
        env = os.environ.copy()
        system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        env['PATH'] = system_paths

        # Enable fail2ban
        result = subprocess.run(
            ['/usr/bin/sudo', '/bin/systemctl', 'enable', 'fail2ban'],
            capture_output=True,
            text=True,
            timeout=10,
            env=env
        )

        # Start fail2ban
        result = subprocess.run(
            ['/usr/bin/sudo', '/bin/systemctl', 'start', 'fail2ban'],
            capture_output=True,
            text=True,
            timeout=10,
            env=env
        )

        if result.returncode == 0:
            messages.success(request, 'Fail2ban started successfully!')
            logger.info(f"User {request.user.username} started fail2ban service")
        else:
            messages.error(request, f'Failed to start fail2ban: {result.stderr[:200]}')
            logger.error(f"Failed to start fail2ban: {result.stderr}")

    except subprocess.TimeoutExpired:
        messages.error(request, 'Start command timed out.')
        logger.error("Fail2ban start timed out")
    except FileNotFoundError as e:
        messages.error(request, f'Required system commands not found: {str(e)}')
        logger.error(f"System commands not found: {e}")
    except Exception as e:
        messages.error(request, f'Failed to start fail2ban: {str(e)[:200]}')
        logger.error(f"Fail2ban start failed: {e}")

    return redirect('core:fail2ban_status')


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_install_sudoers(request):
    """Automatically install fail2ban sudoers configuration."""
    import os
    import pwd
    import tempfile

    try:
        # Set up environment with system paths
        env = os.environ.copy()
        system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        env['PATH'] = system_paths

        # Generate sudoers content with actual username
        username = pwd.getpwuid(os.getuid()).pw_name

        sudoers_content = f"""# Sudoers configuration for HuduGlue fail2ban integration
# Generated automatically during installation

# Allow {username} user to run fail2ban-client and systemctl commands without password
{username} ALL=(ALL) NOPASSWD: /usr/bin/fail2ban-client
{username} ALL=(ALL) NOPASSWD: /bin/systemctl is-active fail2ban
{username} ALL=(ALL) NOPASSWD: /bin/systemctl status fail2ban
"""

        # Write to temp file first
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='-fail2ban-sudoers') as tmp:
            tmp.write(sudoers_content)
            temp_path = tmp.name

        try:
            dest_path = '/etc/sudoers.d/huduglue-fail2ban'

            # Try to install the sudoers file
            result = subprocess.run(
                ['/usr/bin/sudo', '/bin/cp', temp_path, dest_path],
                capture_output=True,
                text=True,
                timeout=10,
                env=env
            )

            if result.returncode != 0:
                messages.error(
                    request,
                    f'Failed to install fail2ban sudoers. Make sure base install sudoers is configured: sudo cp {settings.BASE_DIR}/deploy/huduglue-install-sudoers /etc/sudoers.d/huduglue-install && sudo chmod 0440 /etc/sudoers.d/huduglue-install'
                )
                logger.error(f"Failed to copy fail2ban sudoers: {result.stderr}")
                return redirect('core:fail2ban_status')

            # Set correct permissions
            result = subprocess.run(
                ['/usr/bin/sudo', '/bin/chmod', '0440', dest_path],
                capture_output=True,
                text=True,
                timeout=10,
                env=env
            )

            if result.returncode != 0:
                messages.error(request, f'Failed to set fail2ban sudoers permissions: {result.stderr[:200]}')
                logger.error(f"Failed to chmod fail2ban sudoers: {result.stderr}")
                return redirect('core:fail2ban_status')

            messages.success(request, f'Fail2ban sudoers configuration installed successfully for user {username}! Refresh the page.')
            logger.info(f"User {request.user.username} successfully installed fail2ban sudoers configuration")

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

    except subprocess.TimeoutExpired:
        messages.error(request, 'Installation timed out.')
        logger.error("Fail2ban sudoers installation timed out")
    except FileNotFoundError as e:
        messages.error(request, f'Required system commands not found: {str(e)}')
        logger.error(f"System commands not found: {e}")
    except Exception as e:
        messages.error(request, f'Installation failed: {str(e)[:200]}')
        logger.error(f"Fail2ban sudoers installation failed: {e}")

    return redirect('core:fail2ban_status')


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_install(request):
    """Automatically install and configure fail2ban."""
    import os

    try:
        # Set up environment with system paths for utilities
        env = os.environ.copy()
        system_paths = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
        env['PATH'] = system_paths

        # Get sudo password if provided
        sudo_password = request.POST.get('sudo_password', '').strip()

        # Check if passwordless sudo is already configured
        test_result = subprocess.run(
            ['/usr/bin/sudo', '-n', '/usr/bin/apt-get', '--version'],
            capture_output=True,
            text=True,
            timeout=5,
            env=env
        )

        # If passwordless sudo doesn't work and no password provided, show password form
        if test_result.returncode != 0 and not sudo_password:
            messages.warning(
                request,
                'First-time setup requires your sudo password. Enter it below to complete automatic installation.'
            )
            # Set a flag to show password form
            request.session['show_sudo_password_form'] = True
            return redirect('core:fail2ban_status')

        # If passwordless sudo doesn't work but password was provided, set up sudoers first
        if test_result.returncode != 0 and sudo_password:
            logger.info("Setting up sudoers with provided password...")

            # Step 0: Install sudoers files using password
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            install_sudoers_src = os.path.join(base_dir, 'deploy', 'huduglue-install-sudoers')
            fail2ban_sudoers_src = os.path.join(base_dir, 'deploy', 'huduglue-fail2ban-sudoers')

            # Install huduglue-install-sudoers
            result = subprocess.run(
                ['/usr/bin/sudo', '-S', '/bin/cp', install_sudoers_src, '/etc/sudoers.d/huduglue-install'],
                input=f"{sudo_password}\n",
                capture_output=True,
                text=True,
                timeout=10,
                env=env
            )

            if result.returncode != 0:
                messages.error(request, f'Failed to configure sudo access. Check your password and try again. Error: {result.stderr[:200]}')
                logger.error(f"Failed to install sudoers: {result.stderr}")
                request.session['show_sudo_password_form'] = True
                return redirect('core:fail2ban_status')

            # Set permissions on install sudoers
            subprocess.run(
                ['/usr/bin/sudo', '-S', '/bin/chmod', '0440', '/etc/sudoers.d/huduglue-install'],
                input=f"{sudo_password}\n",
                capture_output=True,
                text=True,
                timeout=10,
                env=env
            )

            logger.info("Sudoers configuration installed successfully")
            # Clear the password form flag
            request.session.pop('show_sudo_password_form', None)

        # Step 1: Update package list
        logger.info("Updating apt package list...")
        if sudo_password:
            # Use password if we have it (first-time setup)
            result = subprocess.run(
                ['/usr/bin/sudo', '-S', '/usr/bin/apt-get', 'update'],
                input=f"{sudo_password}\n",
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )
        else:
            # Use passwordless sudo (subsequent runs)
            result = subprocess.run(
                ['/usr/bin/sudo', '/usr/bin/apt-get', 'update'],
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )

        # Step 2: Install fail2ban
        logger.info("Installing fail2ban package...")
        if sudo_password:
            # Use password if we have it (first-time setup)
            result = subprocess.run(
                ['/usr/bin/sudo', '-S', '/usr/bin/apt-get', 'install', '-y', 'fail2ban'],
                input=f"{sudo_password}\n",
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
        else:
            # Use passwordless sudo (subsequent runs)
            result = subprocess.run(
                ['/usr/bin/sudo', '/usr/bin/apt-get', 'install', '-y', 'fail2ban'],
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )

        if result.returncode != 0:
            messages.error(request, f'Failed to install fail2ban: {result.stderr[:200]}')
            logger.error(f"fail2ban installation failed: {result.stderr}")
            return redirect('core:fail2ban_status')

        # Step 3: Enable and start service
        logger.info("Enabling and starting fail2ban service...")
        if sudo_password:
            subprocess.run(['/usr/bin/sudo', '-S', '/bin/systemctl', 'enable', 'fail2ban'],
                         input=f"{sudo_password}\n", capture_output=True, text=True, timeout=10, check=False, env=env)
            subprocess.run(['/usr/bin/sudo', '-S', '/bin/systemctl', 'start', 'fail2ban'],
                         input=f"{sudo_password}\n", capture_output=True, text=True, timeout=10, check=False, env=env)
        else:
            subprocess.run(['/usr/bin/sudo', '/bin/systemctl', 'enable', 'fail2ban'], timeout=10, check=False, env=env)
            subprocess.run(['/usr/bin/sudo', '/bin/systemctl', 'start', 'fail2ban'], timeout=10, check=False, env=env)

        # Step 4: Configure sudoers for fail2ban-client access
        # Generate sudoers content with actual username
        import pwd
        username = pwd.getpwuid(os.getuid()).pw_name

        sudoers_content = f"""# Sudoers configuration for HuduGlue fail2ban integration
# Generated automatically during installation

# Allow {username} user to run fail2ban-client and systemctl commands without password
{username} ALL=(ALL) NOPASSWD: /usr/bin/fail2ban-client
{username} ALL=(ALL) NOPASSWD: /bin/systemctl is-active fail2ban
{username} ALL=(ALL) NOPASSWD: /bin/systemctl status fail2ban
"""

        # Write to temp file first
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='-fail2ban-sudoers') as tmp:
            tmp.write(sudoers_content)
            temp_path = tmp.name

        try:
            logger.info("Installing fail2ban sudoers configuration...")
            dest_path = '/etc/sudoers.d/huduglue-fail2ban'

            if sudo_password:
                subprocess.run(['/usr/bin/sudo', '-S', '/bin/cp', temp_path, dest_path],
                             input=f"{sudo_password}\n", capture_output=True, text=True, timeout=10, check=True, env=env)
                subprocess.run(['/usr/bin/sudo', '-S', '/bin/chmod', '0440', dest_path],
                             input=f"{sudo_password}\n", capture_output=True, text=True, timeout=10, check=True, env=env)
            else:
                subprocess.run(['/usr/bin/sudo', '/bin/cp', temp_path, dest_path], timeout=10, check=True, env=env)
                subprocess.run(['/usr/bin/sudo', '/bin/chmod', '0440', dest_path], timeout=10, check=True, env=env)

            logger.info(f"Sudoers configured for user: {username}")
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

        messages.success(request, 'Fail2ban installed and configured successfully! Refresh the page to see the status.')
        logger.info(f"User {request.user.username} successfully installed fail2ban automatically")

    except subprocess.TimeoutExpired:
        messages.error(request, 'Installation timed out. The package manager may be locked by another process.')
        logger.error("Fail2ban installation timed out")
    except FileNotFoundError as e:
        messages.error(request, f'Required system commands not found: {str(e)}. Please ensure sudo and apt-get are available.')
        logger.error(f"sudo or apt-get not found: {e}")
    except Exception as e:
        messages.error(request, f'Installation failed: {str(e)[:200]}')
        logger.error(f"Fail2ban installation failed with exception: {e}")

    return redirect('core:fail2ban_status')
