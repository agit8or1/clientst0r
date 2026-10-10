"""
Security-related views - Package scanning, vulnerability monitoring
"""
import io
import json
import logging

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.management import CommandError, call_command
from django.utils import timezone

from .models import SystemPackageScan, PythonPackageScan


logger = logging.getLogger(__name__)


def _is_staff_or_superuser(user):
    """Gate for system-admin views: Django superuser OR staff flag."""
    return user.is_authenticated and (user.is_superuser or user.is_staff)


def _staff_or_superuser_api(view_fn):
    """
    Decorator for JSON endpoints: return 403 JSON if the user isn't a
    Django superuser or staff. Mirrors the inline check that used to be
    duplicated at the top of every package-scanner API view.
    """
    from functools import wraps

    @wraps(view_fn)
    def wrapped(request, *args, **kwargs):
        if not _is_staff_or_superuser(request.user):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        return view_fn(request, *args, **kwargs)
    return wrapped


def _staff_or_superuser_view(view_fn):
    """
    Decorator for HTML pages: flash a denial message and redirect to
    the dashboard when the user lacks staff/superuser rights. Mirrors
    the inline `messages.error + redirect` block that used to appear at
    the top of every package-scanner page view.
    """
    from functools import wraps

    @wraps(view_fn)
    def wrapped(request, *args, **kwargs):
        if not _is_staff_or_superuser(request.user):
            messages.error(request, "You don't have permission to access this feature.")
            return redirect('core:dashboard')
        return view_fn(request, *args, **kwargs)
    return wrapped


@login_required
@_staff_or_superuser_view
def package_scanner_dashboard(request):
    """
    Package scanner dashboard showing scan history and security status.
    Staff/superuser only.
    """

    # Get latest scan
    latest_scan = SystemPackageScan.objects.first()

    # Get scan history (last 30 scans)
    scan_history = SystemPackageScan.objects.all()[:30]

    # Calculate statistics
    stats = {
        'latest_scan_date': latest_scan.scan_date if latest_scan else None,
        'security_updates': latest_scan.security_updates if latest_scan else 0,
        'total_updates': latest_scan.upgradeable_packages if latest_scan else 0,
        'total_packages': latest_scan.total_packages if latest_scan else 0,
        'security_status': latest_scan.security_status if latest_scan else ('secondary', 'No scans yet'),
        'scan_count': scan_history.count(),
    }

    # Get trend data (last 7 scans)
    trend_scans = list(scan_history[:7])
    trend_scans.reverse()  # Oldest to newest

    trend_data = {
        'dates': [scan.scan_date.strftime('%m/%d') for scan in trend_scans],
        'security_updates': [scan.security_updates for scan in trend_scans],
        'total_updates': [scan.upgradeable_packages for scan in trend_scans],
    }

    return render(request, 'core/package_scanner_dashboard.html', {
        'latest_scan': latest_scan,
        'scan_history': scan_history,
        'stats': stats,
        'trend_data': trend_data,
    })


@login_required
@_staff_or_superuser_api
@require_http_methods(["POST"])
def run_package_scan(request):
    """Run a package scan manually via web interface"""
    try:
        # First, try to update the apt cache for latest data
        import subprocess
        cache_updated = False
        try:
            result = subprocess.run(
                ['sudo', '-n', 'apt-get', 'update'],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                cache_updated = True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError) as exc:
            # apt-get update can legitimately fail (no sudo, no network,
            # nothing to update) — that's not an error for the scan itself,
            # just continue with cached data. Log so ops can see *why*.
            logger.info('apt-get update skipped before scan: %s', exc)

        # Run scan command
        out = io.StringIO()
        call_command('scan_system_packages', '--save', '--json', stdout=out)

        # Parse output
        output = out.getvalue()
        scan_data = {}

        try:
            # Try direct JSON parse first
            scan_data = json.loads(output)
        except json.JSONDecodeError as e:
            # Command might have printed non-JSON info, find the JSON part
            lines = output.strip().split('\n')
            json_found = False

            for line in lines:
                line = line.strip()
                if line.startswith('{'):
                    try:
                        scan_data = json.loads(line)
                        json_found = True
                        break
                    except json.JSONDecodeError:
                        # Try to find JSON in multi-line output
                        try:
                            json_start_idx = output.index('{')
                            json_end_idx = output.rindex('}') + 1
                            json_str = output[json_start_idx:json_end_idx]
                            scan_data = json.loads(json_str)
                            json_found = True
                            break
                        except (ValueError, json.JSONDecodeError):
                            continue

            if not json_found:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to parse scan output',
                }, status=500)

        # Add cache update status to scan data
        scan_data['cache_updated'] = cache_updated

        return JsonResponse({
            'success': True,
            'message': 'Scan completed successfully' + (' (cache updated)' if cache_updated else ' (using cached data)'),
            'cache_updated': cache_updated,
            'scan_data': scan_data
        })

    except Exception:
        # Log the real exception so ops can triage what actually broke —
        # before this fix the response just said "Scan failed" with no
        # signal of the underlying cause (CalledProcessError vs.
        # JSONDecodeError vs. permissions vs. OOM all looked identical).
        logger.exception('Manual package scan failed')
        return JsonResponse({
            'success': False,
            'error': 'Scan failed'
        }, status=500)


@login_required
@_staff_or_superuser_api
@require_http_methods(["POST"])
def update_packages(request):
    """Update system packages via web interface (OPTIONAL)"""
    try:
        security_only = request.POST.get('security_only') == 'true'
        packages = request.POST.get('packages', '')
        dry_run = request.POST.get('dry_run') == 'true'

        # Build command arguments
        args = ['--auto-approve']

        if security_only:
            args.append('--security-only')

        if packages:
            from core.management.commands.update_system_packages import parse_package_list
            try:
                parse_package_list(packages)
            except CommandError as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            args.extend(['--package', packages])

        if dry_run:
            args.append('--dry-run')

        # Run update command
        out = io.StringIO()
        err = io.StringIO()
        call_command('update_system_packages', *args, stdout=out, stderr=err)

        output = out.getvalue() + err.getvalue()

        # Detect failure from output text (command doesn't raise on subprocess errors)
        output_lower = output.lower()
        failed = 'update failed' in output_lower or '✗' in output

        return JsonResponse({
            'success': not failed,
            'message': 'Update completed successfully' if not dry_run else 'Dry run completed',
            'output': output,
            'error': 'Update failed — see output above' if failed else None,
        })

    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'output': traceback.format_exc(),
        }, status=500)


@login_required
@_staff_or_superuser_view
def scan_detail(request, pk):
    """View details of a specific scan"""
    from django.shortcuts import get_object_or_404
    scan = get_object_or_404(SystemPackageScan, pk=pk)

    return render(request, 'core/package_scan_detail.html', {
        'scan': scan,
    })


@login_required
@_staff_or_superuser_api
def get_dashboard_widget_data(request):
    """
    API endpoint to get package scanner data for dashboard widget.
    Returns JSON with security status.
    """
    latest_scan = SystemPackageScan.objects.first()

    if not latest_scan:
        return JsonResponse({
            'status': 'no_data',
            'message': 'No scans available',
            'security_updates': 0,
            'total_updates': 0,
        })

    status_class, status_label = latest_scan.security_status

    return JsonResponse({
        'status': status_class,
        'status_label': status_label,
        'security_updates': latest_scan.security_updates,
        'total_updates': latest_scan.upgradeable_packages,
        'total_packages': latest_scan.total_packages,
        'scan_date': latest_scan.scan_date.isoformat(),
        'package_manager': latest_scan.package_manager,
    })


# ---------------------------------------------------------------------------
# Python dependency scanner (pip-audit)
# ---------------------------------------------------------------------------

@login_required
@_staff_or_superuser_view
def python_scanner_dashboard(request):
    """Dashboard for Python dependency vulnerability scans (pip-audit)."""
    latest_scan = PythonPackageScan.objects.first()
    scan_history = PythonPackageScan.objects.all()[:30]

    stats = {
        'latest_scan_date': latest_scan.scan_date if latest_scan else None,
        'total_packages': latest_scan.total_packages if latest_scan else 0,
        'vulnerable_packages': latest_scan.vulnerable_packages if latest_scan else 0,
        'total_vulnerabilities': latest_scan.total_vulnerabilities if latest_scan else 0,
        'critical_count': latest_scan.critical_count if latest_scan else 0,
        'high_count': latest_scan.high_count if latest_scan else 0,
        'medium_count': latest_scan.medium_count if latest_scan else 0,
        'low_count': latest_scan.low_count if latest_scan else 0,
        'unknown_count': latest_scan.unknown_count if latest_scan else 0,
        'security_status': latest_scan.security_status if latest_scan else ('secondary', 'No scans yet'),
        'scan_count': PythonPackageScan.objects.count(),
    }

    trend_scans = list(scan_history[:7])
    trend_scans.reverse()
    trend_data = {
        'dates': [s.scan_date.strftime('%m/%d') for s in trend_scans],
        'total_vulnerabilities': [s.total_vulnerabilities for s in trend_scans],
        'critical_high': [s.critical_count + s.high_count for s in trend_scans],
    }

    # Vulnerable packages from the latest scan, surfaced for the table
    vulnerable_pkgs = []
    if latest_scan and latest_scan.scan_data:
        for pkg in latest_scan.scan_data.get('packages', []):
            if pkg.get('vulns'):
                vulnerable_pkgs.append(pkg)

    return render(request, 'core/python_scanner_dashboard.html', {
        'latest_scan': latest_scan,
        'scan_history': scan_history,
        'stats': stats,
        'trend_data': trend_data,
        'vulnerable_packages': vulnerable_pkgs,
    })


@login_required
@_staff_or_superuser_api
@require_http_methods(["POST"])
def run_python_scan(request):
    """Run a pip-audit scan via the web interface."""
    try:
        out = io.StringIO()
        call_command('scan_python_packages', '--save', '--json', stdout=out)
        try:
            scan_data = json.loads(out.getvalue())
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Failed to parse scan output',
            }, status=500)

        return JsonResponse({
            'success': scan_data.get('succeeded', True),
            'message': 'Scan completed' if scan_data.get('succeeded') else scan_data.get('error', 'Scan failed'),
            'scan_data': {
                'total_packages': scan_data.get('total_packages', 0),
                'vulnerable_packages': scan_data.get('vulnerable_packages', 0),
                'total_vulnerabilities': scan_data.get('total_vulnerabilities', 0),
                'severity_counts': scan_data.get('severity_counts', {}),
            },
        })
    except Exception:
        # Same fix as run_package_scan in v3.17.180 — log the real
        # exception so ops can triage past the generic "Scan failed".
        logger.exception('Manual Python package scan failed')
        return JsonResponse({'success': False, 'error': 'Scan failed'}, status=500)


@login_required
@_staff_or_superuser_view
def python_scan_detail(request, pk):
    """View details of a specific Python scan."""
    from django.shortcuts import get_object_or_404
    scan = get_object_or_404(PythonPackageScan, pk=pk)
    vulnerable_pkgs = [p for p in scan.scan_data.get('packages', []) if p.get('vulns')]
    return render(request, 'core/python_scan_detail.html', {
        'scan': scan,
        'vulnerable_packages': vulnerable_pkgs,
    })


@login_required
@_staff_or_superuser_api
def get_python_scanner_widget_data(request):
    """JSON widget feed for the Python scanner."""
    latest_scan = PythonPackageScan.objects.first()
    if not latest_scan:
        return JsonResponse({
            'status': 'no_data',
            'message': 'No scans available',
            'total_vulnerabilities': 0,
            'vulnerable_packages': 0,
        })

    status_class, status_label = latest_scan.security_status
    return JsonResponse({
        'status': status_class,
        'status_label': status_label,
        'total_packages': latest_scan.total_packages,
        'vulnerable_packages': latest_scan.vulnerable_packages,
        'total_vulnerabilities': latest_scan.total_vulnerabilities,
        'critical': latest_scan.critical_count,
        'high': latest_scan.high_count,
        'medium': latest_scan.medium_count,
        'low': latest_scan.low_count,
        'unknown': latest_scan.unknown_count,
        'scan_date': latest_scan.scan_date.isoformat(),
        'scan_succeeded': latest_scan.scan_succeeded,
    })


# ---------------------------------------------------------------------------
# Python dependency remediation (pip-audit findings → pip install upgrade)
# ---------------------------------------------------------------------------

import re as _re_remediate
import subprocess as _subprocess
import sys as _sys


_PACKAGE_NAME_RE = _re_remediate.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_VERSION_RE = _re_remediate.compile(r'^\d+(\.\d+)*([a-z0-9.+-]*)?$')


def _safe_package_and_version(name: str, version: str):
    """Validate that name + version are safe to pass to subprocess.

    Returns (clean_name, clean_version) or raises ValueError. We do NOT
    shell-quote and pass through `shell=True` — instead we hand the args
    list to subprocess and double-check both fields match strict regex
    so an attacker who somehow controls the POST can't inject flags.
    """
    if not name or not _PACKAGE_NAME_RE.match(name):
        raise ValueError('Invalid package name')
    if not version or not _VERSION_RE.match(version):
        raise ValueError('Invalid version string')
    return name, version


def _vulnerable_pkg_index(latest_scan):
    """Return a {package_name: set(fix_versions)} index from the latest scan."""
    out = {}
    if not latest_scan or not latest_scan.scan_data:
        return out
    for pkg in latest_scan.scan_data.get('packages', []):
        if not pkg.get('vulns'):
            continue
        fix_versions = set()
        for v in pkg['vulns']:
            for fv in (v.get('fix_versions') or []):
                fix_versions.add(fv)
        out[pkg['name']] = fix_versions
    return out


@login_required
@require_http_methods(['POST'])
def remediate_python_package(request):
    """
    Run `pip install --upgrade <name>==<version>` for a single vulnerable
    package, where <version> MUST be one of the pip-audit fix_versions
    from the most recent scan. Superuser only.

    Returns JSON with stdout/stderr/exit code. Audit-logged either way.
    On success, the admin is reminded to (a) update requirements.txt and
    (b) restart gunicorn manually — we don't auto-restart because the
    request is in-process and a restart would kill it.
    """
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Superuser required'}, status=403)

    name = (request.POST.get('package') or '').strip()
    version = (request.POST.get('version') or '').strip()

    try:
        name, version = _safe_package_and_version(name, version)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    # Verify the requested version is a published fix from the latest scan.
    # This prevents a privileged user from being tricked into upgrading to
    # an attacker-chosen version via a stale dashboard.
    latest_scan = PythonPackageScan.objects.first()
    index = _vulnerable_pkg_index(latest_scan)
    valid_versions = index.get(name, set())
    if version not in valid_versions:
        return JsonResponse({
            'error': f'{version} is not in the published fix list for {name}.',
            'valid_versions': sorted(valid_versions),
        }, status=400)

    cmd = [_sys.executable, '-m', 'pip', 'install', '--upgrade',
           f'{name}=={version}']
    try:
        result = _subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
    except _subprocess.TimeoutExpired:
        return JsonResponse({'error': 'pip install timed out'}, status=504)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    success = result.returncode == 0

    # Audit log every attempt (success and failure)
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=request.user,
            action='update',
            object_type='core.PythonPackageScan',
            object_id=latest_scan.pk if latest_scan else 0,
            object_repr=f'pip upgrade {name}=={version}',
            description=(
                f'pip install --upgrade {name}=={version} '
                f'{"succeeded" if success else "FAILED rc=" + str(result.returncode)}'
            ),
            path=request.path,
            extra_data={
                'package': name,
                'target_version': version,
                'returncode': result.returncode,
                'stdout_tail': (result.stdout or '')[-500:],
                'stderr_tail': (result.stderr or '')[-500:],
            },
        )
    except Exception:
        pass  # never fail the response on logging

    return JsonResponse({
        'success': success,
        'package': name,
        'version': version,
        'returncode': result.returncode,
        'stdout': (result.stdout or '')[-2000:],
        'stderr': (result.stderr or '')[-2000:],
        'next_steps': [
            f'Update requirements.txt: pin {name}=={version}',
            'Restart gunicorn: sudo systemctl restart clientst0r-gunicorn.service',
            'Re-run the scan to confirm the vulnerability is gone',
        ] if success else [],
    })
