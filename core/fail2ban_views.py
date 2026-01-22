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
    """Check if fail2ban is installed and accessible."""
    success, output, error = run_fail2ban_command(['ping'])
    return success


@login_required
@user_passes_test(is_superuser)
def fail2ban_status(request):
    """Fail2ban status and management page."""

    # Get sudoers path for installation instructions
    sudoers_path = settings.BASE_DIR / 'deploy' / 'huduglue-install-sudoers'

    # Check if fail2ban is installed
    if not is_fail2ban_installed():
        context = {
            'fail2ban_installed': False,
            'sudoers_path': sudoers_path,
        }
        return render(request, 'core/fail2ban_status.html', context)

    # Get fail2ban status
    success, output, error = run_fail2ban_command(['status'])

    if not success:
        messages.error(request, f'Failed to get fail2ban status: {error}')
        context = {
            'fail2ban_installed': True,
            'fail2ban_running': False,
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
        'jails': jails,
        'total_currently_banned': total_currently_banned,
        'total_all_time_banned': total_all_time_banned,
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
def fail2ban_install(request):
    """Automatically install and configure fail2ban."""
    import os

    try:
        # Check sudo access first
        test_result = subprocess.run(
            ['sudo', '-n', 'apt-get', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if test_result.returncode != 0:
            sudoers_path = settings.BASE_DIR / 'deploy' / 'huduglue-install-sudoers'
            messages.error(
                request,
                f'Sudo access not configured. Please run: sudo cp {sudoers_path} /etc/sudoers.d/huduglue-install && sudo chmod 0440 /etc/sudoers.d/huduglue-install'
            )
            return redirect('core:fail2ban_status')

        # Step 1: Update package list
        logger.info("Updating apt package list...")
        result = subprocess.run(
            ['sudo', 'apt-get', 'update'],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Step 2: Install fail2ban
        logger.info("Installing fail2ban package...")
        result = subprocess.run(
            ['sudo', 'apt-get', 'install', '-y', 'fail2ban'],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            messages.error(request, f'Failed to install fail2ban: {result.stderr[:200]}')
            logger.error(f"fail2ban installation failed: {result.stderr}")
            return redirect('core:fail2ban_status')

        # Step 3: Enable and start service
        logger.info("Enabling and starting fail2ban service...")
        subprocess.run(['sudo', 'systemctl', 'enable', 'fail2ban'], timeout=10, check=False)
        subprocess.run(['sudo', 'systemctl', 'start', 'fail2ban'], timeout=10, check=False)

        # Step 4: Configure sudoers for fail2ban-client access
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source_path = os.path.join(base_dir, 'deploy', 'huduglue-fail2ban-sudoers')
        dest_path = '/etc/sudoers.d/huduglue-fail2ban'

        if os.path.exists(source_path):
            logger.info("Installing fail2ban sudoers configuration...")
            subprocess.run(['sudo', 'cp', source_path, dest_path], timeout=10, check=False)
            subprocess.run(['sudo', 'chmod', '0440', dest_path], timeout=10, check=False)
        else:
            logger.warning("fail2ban sudoers source file not found")

        messages.success(request, 'Fail2ban installed and configured successfully! Refresh the page to see the status.')
        logger.info(f"User {request.user.username} successfully installed fail2ban automatically")

    except subprocess.TimeoutExpired:
        messages.error(request, 'Installation timed out. The package manager may be locked by another process.')
        logger.error("Fail2ban installation timed out")
    except FileNotFoundError:
        messages.error(request, 'Required system commands not found. Please ensure sudo and apt-get are available.')
        logger.error("sudo or apt-get not found")
    except Exception as e:
        messages.error(request, f'Installation failed: {str(e)[:200]}')
        logger.error(f"Fail2ban installation failed with exception: {e}")

    return redirect('core:fail2ban_status')
