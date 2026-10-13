"""
System warnings aggregator — produces a unified, severity-ranked list of
admin-actionable issues across:
- OS package security updates (SystemPackageScan)
- Python dependency vulnerabilities (PythonPackageScan / pip-audit)
- App version behind GitHub release (config.version)
- Expiring/expired SSL certificates (monitoring.WebsiteMonitor)
- Expiring/expired domains/licenses/warranties (monitoring.Expiration)

Each warning is a dict:
{
    'id':            stable string for de-duplication / digest tracking,
    'severity':      'critical' | 'high' | 'medium' | 'low' | 'info',
    'category':      short tag (e.g. 'os_package', 'python_dep', 'app_version'),
    'title':         one-line headline (no secrets, safe to email),
    'detail':        one-line detail (counts, dates, etc.),
    'action_url':    relative URL to dig in,
    'action_label':  text for the action button,
    'source_date':   datetime of the underlying signal (or None),
}

Severity rank: lower is more severe.
"""
from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone


SEVERITY_RANK = {
    'critical': 0,
    'high': 1,
    'medium': 2,
    'low': 3,
    'info': 4,
}


def _safe_reverse(name):
    """Reverse a URL name; return '' if it doesn't resolve so the aggregator
    keeps working when an optional URL is unwired."""
    try:
        return reverse(name)
    except Exception:
        return ''


def collect_system_warnings(min_severity='low'):
    """
    Build the full list of warnings, sorted most-severe first.
    `min_severity`: drop anything below this rank ('critical' < 'high' < ...).
    """
    threshold = SEVERITY_RANK.get(min_severity, SEVERITY_RANK['low'])
    warnings = []

    warnings.extend(_warnings_from_os_packages())
    warnings.extend(_warnings_from_python_packages())
    warnings.extend(_warnings_from_app_version())
    warnings.extend(_warnings_from_root_helper())
    warnings.extend(_warnings_from_ssl_expiry())
    warnings.extend(_warnings_from_domain_expiry())

    # Filter by min severity, then sort.
    filtered = [w for w in warnings if SEVERITY_RANK.get(w['severity'], 9) <= threshold]
    filtered.sort(key=lambda w: (SEVERITY_RANK.get(w['severity'], 9), w.get('source_date') or timezone.now()))
    return filtered


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _warnings_from_os_packages():
    from core.models import SystemPackageScan
    out = []
    latest = SystemPackageScan.objects.first()
    if not latest:
        return out
    if latest.security_updates > 0:
        # >= 5 security updates we treat as high; >= 20 critical (matches
        # the existing security_status thresholds on the model).
        if latest.security_updates >= 20:
            sev = 'critical'
        elif latest.security_updates >= 5:
            sev = 'high'
        else:
            sev = 'medium'
        out.append({
            'id': f'os_pkg:{latest.pk}',
            'severity': sev,
            'category': 'os_package',
            'title': f'{latest.security_updates} OS security update{"s" if latest.security_updates != 1 else ""} pending',
            'detail': f'Detected via {latest.package_manager}. {latest.upgradeable_packages} total upgradeable.',
            'action_url': _safe_reverse('core:package_scanner_dashboard'),
            'action_label': 'Review OS updates',
            'source_date': latest.scan_date,
        })
    return out


def _warnings_from_python_packages():
    from core.models import PythonPackageScan
    out = []
    latest = PythonPackageScan.objects.first()
    if not latest:
        return out
    if not latest.scan_succeeded:
        out.append({
            'id': f'py_pkg_scan_failed:{latest.pk}',
            'severity': 'medium',
            'category': 'python_dep',
            'title': 'Python dependency scan failed',
            'detail': (latest.scan_error or 'unknown error')[:200],
            'action_url': _safe_reverse('core:python_scanner_dashboard'),
            'action_label': 'View scanner',
            'source_date': latest.scan_date,
        })
        return out
    if latest.total_vulnerabilities == 0:
        return out

    # Map worst severity present → warning severity.
    if latest.critical_count > 0:
        sev = 'critical'
    elif latest.high_count > 0:
        sev = 'high'
    elif latest.medium_count > 0:
        sev = 'medium'
    else:
        # low_count or unknown_count only
        sev = 'low'

    pieces = []
    if latest.critical_count: pieces.append(f'{latest.critical_count} critical')
    if latest.high_count:     pieces.append(f'{latest.high_count} high')
    if latest.medium_count:   pieces.append(f'{latest.medium_count} medium')
    if latest.low_count:      pieces.append(f'{latest.low_count} low')
    if latest.unknown_count:  pieces.append(f'{latest.unknown_count} unrated')

    out.append({
        'id': f'py_pkg:{latest.pk}',
        'severity': sev,
        'category': 'python_dep',
        'title': f'{latest.total_vulnerabilities} Python dependency '
                 f'vulnerabilit{"ies" if latest.total_vulnerabilities != 1 else "y"} '
                 f'across {latest.vulnerable_packages} package{"s" if latest.vulnerable_packages != 1 else ""}',
        'detail': ', '.join(pieces) or 'see scanner for breakdown',
        'action_url': _safe_reverse('core:python_scanner_dashboard'),
        'action_label': 'Review Python deps',
        'source_date': latest.scan_date,
    })
    return out


def _warnings_from_root_helper():
    """v3.17.597: a native install without the root helper still has the old
    passwordless sudo rules, some of which can be used to gain root."""
    try:
        from core import root_helper
        needed = root_helper.needs_bootstrap()
    except Exception:
        return []
    if not needed:
        return []
    return [{
        'id': 'root_helper:missing',
        'severity': 'high',
        'category': 'security',
        'title': 'One-time security setup needed: install the root helper',
        'detail': 'Older passwordless sudo rules on this server can be used to gain root. '
                  'Install the root helper from Settings → Updates.',
        'action_url': _safe_reverse('core:system_updates'),
        'action_label': 'Open Updates',
        'source_date': timezone.now(),
    }]


def _warnings_from_app_version():
    """If a newer app version is available, surface it as 'info' (low priority,
    but admins should know). Reuses the existing UpdateService check.
    """
    out = []
    try:
        from core.updater import UpdateService
    except Exception:
        return out

    try:
        svc = UpdateService()
        info = svc.check_for_updates()
    except Exception:
        return out

    if not info or not info.get('update_available'):
        return out

    current = info.get('current_version', '?')
    latest = info.get('latest_version', '?')
    out.append({
        'id': f'app_version:{latest}',
        'severity': 'info',
        'category': 'app_version',
        'title': f'Client St0r update available: {current} → {latest}',
        'detail': 'Apply via Settings → Updates.',
        'action_url': _safe_reverse('core:system_updates'),
        'action_label': 'Open Updates',
        'source_date': timezone.now(),
    })
    return out


def _warnings_from_ssl_expiry():
    """Surface SSL certs expiring within the configured warning window."""
    out = []
    try:
        from monitoring.models import WebsiteMonitor
        from core.models import SystemSetting
    except Exception:
        return out

    try:
        settings = SystemSetting.get_settings()
    except Exception:
        return out

    if not getattr(settings, 'notify_on_ssl_expiry', False):
        return out

    now = timezone.now()
    warning_days = int(getattr(settings, 'ssl_expiry_warning_days', 30) or 30)
    threshold = now + timedelta(days=warning_days)

    qs = WebsiteMonitor.objects.filter(
        ssl_enabled=True,
        ssl_expires_at__isnull=False,
        ssl_expires_at__lte=threshold,
    )
    expired = qs.filter(ssl_expires_at__lt=now).count()
    expiring = qs.filter(ssl_expires_at__gte=now).count()

    if expired:
        out.append({
            'id': 'ssl_expired',
            'severity': 'high',
            'category': 'ssl',
            'title': f'{expired} SSL certificate{"s" if expired != 1 else ""} expired',
            'detail': 'Renew immediately — services may be unreachable.',
            'action_url': '/monitoring/',
            'action_label': 'Open Monitoring',
            'source_date': now,
        })
    if expiring:
        out.append({
            'id': 'ssl_expiring',
            'severity': 'medium' if expiring > 1 else 'low',
            'category': 'ssl',
            'title': f'{expiring} SSL certificate{"s" if expiring != 1 else ""} expiring within {warning_days} days',
            'detail': 'Plan renewal before expiry.',
            'action_url': '/monitoring/',
            'action_label': 'Open Monitoring',
            'source_date': now,
        })
    return out


def _warnings_from_domain_expiry():
    out = []
    try:
        from monitoring.models import Expiration
        from core.models import SystemSetting
    except Exception:
        return out

    try:
        settings = SystemSetting.get_settings()
    except Exception:
        return out

    if not getattr(settings, 'notify_on_domain_expiry', False):
        return out

    now = timezone.now()
    warning_days = int(getattr(settings, 'domain_expiry_warning_days', 30) or 30)
    threshold = now + timedelta(days=warning_days)

    qs = Expiration.objects.filter(
        expiration_type='domain',
        expires_at__isnull=False,
        expires_at__lte=threshold,
    )
    expired = qs.filter(expires_at__lt=now).count()
    expiring = qs.filter(expires_at__gte=now).count()

    if expired:
        out.append({
            'id': 'domain_expired',
            'severity': 'high',
            'category': 'domain',
            'title': f'{expired} domain{"s" if expired != 1 else ""} expired',
            'detail': 'Renew immediately — sites may go offline.',
            'action_url': '/monitoring/',
            'action_label': 'Open Monitoring',
            'source_date': now,
        })
    if expiring:
        out.append({
            'id': 'domain_expiring',
            'severity': 'medium' if expiring > 1 else 'low',
            'category': 'domain',
            'title': f'{expiring} domain{"s" if expiring != 1 else ""} expiring within {warning_days} days',
            'detail': 'Plan renewal before expiry.',
            'action_url': '/monitoring/',
            'action_label': 'Open Monitoring',
            'source_date': now,
        })
    return out


def severity_summary(warnings):
    """Return a {severity: count} dict for the supplied warnings list."""
    counts = {s: 0 for s in SEVERITY_RANK}
    for w in warnings:
        counts[w['severity']] = counts.get(w['severity'], 0) + 1
    return counts


def worst_severity(warnings):
    """Return the most severe severity in `warnings`, or None."""
    best = None
    for w in warnings:
        rank = SEVERITY_RANK.get(w['severity'], 9)
        if best is None or rank < best[0]:
            best = (rank, w['severity'])
    return best[1] if best else None
