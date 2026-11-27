"""
Fail2ban integration views
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
import ipaddress
import subprocess
import logging

from core import root_helper

logger = logging.getLogger('core')


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser


def _parse_ip(value):
    """The address as an ``ipaddress`` object (IPv4 or IPv6), or None."""
    try:
        return ipaddress.ip_address((value or '').strip())
    except ValueError:
        return None


def _banned_ips(jail_output):
    """The banned addresses listed in ``fail2ban-client status JAIL`` output.

    Splits on the first colon only: an IPv6 address has colons of its own.
    """
    for line in jail_output.split('\n'):
        if 'Banned IP list:' in line:
            return [ip for ip in line.split(':', 1)[1].split() if ip.strip()]
    return []


def _audit(request, description, *, object_repr, extra=None, success=True):
    """Audit entry for a fail2ban change (unban, start, install)."""
    from audit.models import AuditLog
    from core.client_ip import get_client_ip
    try:
        AuditLog.log(
            user=request.user, action='update', object_type='core.Fail2ban',
            object_repr=object_repr[:255], description=description,
            ip_address=get_client_ip(request), path=request.path,
            extra_data=extra or {}, success=success,
        )
    except Exception:
        logger.exception('could not write the fail2ban audit entry')


def _fail2ban_client_path():
    import os
    import shutil
    return (
        shutil.which('fail2ban-client') or
        ('/usr/bin/fail2ban-client' if os.path.exists('/usr/bin/fail2ban-client') else None) or
        ('/usr/local/bin/fail2ban-client' if os.path.exists('/usr/local/bin/fail2ban-client') else None)
    )


def _helper_args(command):
    """fail2ban-client argv -> root helper argv (v3.17.597), or None if the
    helper does not offer that action."""
    if command in (['ping'], ['start'], ['status']):
        return ['fail2ban', *command]
    if len(command) == 2 and command[0] == 'status':
        return ['fail2ban', 'status', command[1]]
    if len(command) == 4 and command[0] == 'set' and command[2] == 'unbanip':
        return ['fail2ban', 'unban', command[1], command[3]]
    return None


def run_fail2ban_command(command):
    """
    Run fail2ban-client command safely.

    v3.17.597: through the root helper when it is installed. The legacy path
    needs a passwordless sudo rule for bare fail2ban-client, which can set a
    jail's ban action and so run anything as root; the helper allows only the
    actions this page uses and checks the jail name and IP.

    Returns:
        tuple: (success: bool, output: str, error: str)
    """
    if not _fail2ban_client_path():
        return False, '', 'fail2ban-client not found - is fail2ban installed?'
    try:
        if root_helper.is_installed():
            args = _helper_args(command)
            if args is None:
                return False, '', f'Unsupported fail2ban command: {command[:1]}'
            result = root_helper.run(args, timeout=30)
        else:
            result = subprocess.run(
                ['/usr/bin/sudo', '-n', _fail2ban_client_path()] + command,
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
    # Check if fail2ban is installed by looking for the client binary.
    # Use shutil.which (searches common bin dirs) with a fallback to explicit
    # paths — handles installations in /usr/bin, /usr/local/bin, etc.
    import os
    import shutil
    fail2ban_client_path = (
        shutil.which('fail2ban-client') or
        ('/usr/bin/fail2ban-client' if os.path.exists('/usr/bin/fail2ban-client') else None) or
        ('/usr/local/bin/fail2ban-client' if os.path.exists('/usr/local/bin/fail2ban-client') else None)
    )
    package_installed = bool(fail2ban_client_path)

    if not package_installed:
        return False, False, False, 'fail2ban package not installed'

    # Test sudo permission AND service status in one shot using fail2ban-client ping.
    # This is the command the sudoers file actually grants (not systemctl), so it
    # correctly reflects whether the app can operate fail2ban at runtime.
    # - RC=0 + "pong" in stdout → sudo works, service is running
    # - RC!=0, no "password" in stderr → sudo works, service is NOT running (socket error)
    # - "password is required" in stderr → sudo not configured
    sudo_configured = False
    service_running = False
    try:
        ping_result = root_helper.run(['fail2ban', 'ping'], timeout=10)
        if ping_result is None:
            ping_result = subprocess.run(
                ['/usr/bin/sudo', '-n', fail2ban_client_path, 'ping'],
                capture_output=True,
                text=True,
                timeout=5
            )
        password_required = (
            'password is required' in ping_result.stderr.lower() or
            'a password is required' in ping_result.stderr.lower()
        )
        if not password_required:
            sudo_configured = True
            service_running = (ping_result.returncode == 0 and
                               'pong' in ping_result.stdout.lower())
    except Exception:
        sudo_configured = False
        service_running = False

    return package_installed, service_running, sudo_configured, ''


@login_required
@user_passes_test(is_superuser)
def fail2ban_status(request):
    """Fail2ban status and management page."""

    # Get sudoers paths for installation instructions
    install_sudoers_path = settings.BASE_DIR / 'deploy' / 'clientst0r-install-sudoers'
    fail2ban_sudoers_path = settings.BASE_DIR / 'deploy' / 'clientst0r-fail2ban-sudoers'

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
            f'Fail2ban is installed but sudo access not configured. Run: sudo cp {fail2ban_sudoers_path} /etc/sudoers.d/clientst0r-fail2ban && sudo chmod 0440 /etc/sudoers.d/clientst0r-fail2ban'
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
                    banned_ips = _banned_ips(jail_output)

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

    # Validate the address (IPv4 or IPv6) before anything reaches the root
    # helper, and pass it on in canonical form.
    parsed = _parse_ip(ip_address)
    if parsed is None:
        messages.error(request, 'Invalid IP address format. Enter an IPv4 or IPv6 address.')
        return redirect('core:fail2ban_status')
    ip_address = str(parsed)

    # Unban the IP
    success, output, error = run_fail2ban_command(['set', jail_name, 'unbanip', ip_address])

    _audit(request,
           f'Unbanned {ip_address} from fail2ban jail {jail_name}' if success
           else f'Failed to unban {ip_address} from fail2ban jail {jail_name}',
           object_repr=f'fail2ban {jail_name}: {ip_address}',
           extra={'jail': jail_name, 'ip_address': ip_address, 'error': '' if success else error[:300]},
           success=success)
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

    # Parse banned IPs; skip anything that does not parse as an address.
    banned_ips = [str(p) for p in map(_parse_ip, _banned_ips(output)) if p is not None]

    # Unban each IP
    unbanned = []
    for ip in banned_ips:
        success, output, error = run_fail2ban_command(['set', jail_name, 'unbanip', ip])
        if success:
            unbanned.append(ip)
    unbanned_count = len(unbanned)

    if unbanned:
        _audit(request, f'Unbanned {unbanned_count} address(es) from fail2ban jail {jail_name}',
               object_repr=f'fail2ban {jail_name}: unban all',
               extra={'jail': jail_name, 'ip_addresses': unbanned,
                      'failed': [ip for ip in banned_ips if ip not in unbanned]})

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
    wanted = _parse_ip(ip_address)
    if wanted is None:
        return JsonResponse({'error': 'Not a valid IPv4 or IPv6 address'}, status=400)

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
        # Compare parsed addresses exactly: a substring test matched
        # 1.2.3.4 against a ban on 11.2.3.45.
        if success and any(_parse_ip(ip) == wanted for ip in _banned_ips(output)):
            banned_in_jails.append(jail_name)

    return JsonResponse({
        'ip_address': str(wanted),
        'is_banned': len(banned_in_jails) > 0,
        'jails': banned_in_jails,
    })


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_start(request):
    """Start fail2ban service."""
    # Use fail2ban-client start — this is in sudoers (NOPASSWD: /usr/bin/fail2ban-client).
    # systemctl start/enable are NOT in sudoers, so they will always fail with
    # "password required" when called from the web process.
    success, output, error = run_fail2ban_command(['start'])
    started = success or 'already running' in output.lower() or 'already running' in error.lower()
    _audit(request, 'Started fail2ban' if started else 'Failed to start fail2ban',
           object_repr='fail2ban service', extra={'action': 'start'}, success=started)
    if started:
        messages.success(request, 'Fail2ban started successfully!')
        logger.info(f"User {request.user.username} started fail2ban service")
    else:
        messages.error(request, f'Failed to start fail2ban: {error[:200] or output[:200]}')
        logger.error(f"Failed to start fail2ban: {error}")

    return redirect('core:fail2ban_status')


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_install_sudoers(request):
    """Give the app access to fail2ban.

    v3.17.597: this used to write a sudoers file into the app directory and
    copy it into /etc/sudoers.d with a passwordless `sudo cp` rule. The app
    user can write that source file, so the rule let it grant itself any sudo
    access. fail2ban access now comes from the root helper, which the one-time
    setup on Settings → Updates installs.
    """
    if root_helper.is_installed():
        messages.success(request, 'fail2ban access is provided by the root helper; nothing to install.')
        return redirect('core:fail2ban_status')
    messages.warning(
        request,
        'Install the root helper first (one-time): Settings → Updates → Install root helper, '
        f'or run on the server: {root_helper.bootstrap_command()}'
    )
    return redirect('core:system_updates')


@login_required
@user_passes_test(is_superuser)
@require_POST
def fail2ban_install(request):
    """Install fail2ban and enable it, through the root helper.

    If the helper is not installed yet and the operator entered their sudo
    password, the helper is installed first (the one-time setup), then used.
    """
    sudo_password = request.POST.get('sudo_password', '')

    if not root_helper.is_installed():
        if not sudo_password:
            messages.warning(
                request,
                'First-time setup requires your sudo password. Enter it below to complete automatic installation.'
            )
            request.session['show_sudo_password_form'] = True
            return redirect('core:fail2ban_status')
        ok, output = root_helper.bootstrap_with_password(sudo_password)
        if not ok:
            messages.error(request, f'One-time setup failed. Check your password and try again. {output[-300:]}')
            logger.error('Root helper bootstrap failed from fail2ban page: %s', output)
            request.session['show_sudo_password_form'] = True
            return redirect('core:fail2ban_status')
        request.session.pop('show_sudo_password_form', None)
        logger.info('User %s installed the root helper from the fail2ban page', request.user.username)

    try:
        result = root_helper.run(['fail2ban', 'install'], timeout=600)
    except subprocess.TimeoutExpired:
        messages.error(request, 'Installation timed out. The package manager may be locked by another process.')
        logger.error("Fail2ban installation timed out")
        return redirect('core:fail2ban_status')

    if result is None or result.returncode != 0:
        detail = (result.stderr or result.stdout)[-300:] if result else 'root helper unavailable'
        _audit(request, 'Failed to install fail2ban', object_repr='fail2ban service',
               extra={'action': 'install', 'error': detail}, success=False)
        messages.error(request, f'Failed to install fail2ban: {detail}')
        logger.error('fail2ban installation failed: %s', detail)
        return redirect('core:fail2ban_status')

    _audit(request, 'Installed fail2ban', object_repr='fail2ban service', extra={'action': 'install'})
    messages.success(request, 'Fail2ban installed and configured successfully! Refresh the page to see the status.')
    logger.info(f"User {request.user.username} successfully installed fail2ban automatically")
    return redirect('core:fail2ban_status')
