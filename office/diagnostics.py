"""Instance diagnostics and the disposable-document round trip.

    run_diagnostics(instance) -> list[DiagnosticCheck]
    run_health_check(instance, user=None) -> HealthResult   (stores the result)
    run_round_trip(instance, user) -> RoundTripReport

Core checks (configuration, DNS + address policy, TLS / reachability from this
server, scanner status) run here; the provider's ``diagnostics()`` adds the
editor-specific ones (auth, WebSockets, callback/WOPI reachability from the
editor, browser reachability). A provider whose connector is not installed
contributes one ``not_run`` check saying so.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from django.utils import timezone

from . import net
from .providers import (FAIL, NOT_RUN, PASS, WARN, DiagnosticCheck, NotConfigured,
                        RoundTripReport, get_provider)


def _https_or_loopback(url, instance):
    parts = urlsplit(url or '')
    if parts.scheme == 'https':
        return True
    host = (parts.hostname or '').lower()
    return (parts.scheme == 'http' and instance.mode == 'same_server'
            and host in ('localhost', '127.0.0.1', '::1'))


def config_checks(instance):
    checks = []
    problems = []
    for label, url, required in (('Browser URL', instance.browser_url, True),
                                 ('Internal URL', instance.internal_url, False),
                                 ('Callback URL', instance.callback_base_url, True)):
        if not url:
            if required:
                problems.append(f'{label} is not set.')
            continue
        if not _https_or_loopback(url, instance):
            problems.append(f'{label} must use https (http only for loopback on this server).')
    checks.append(DiagnosticCheck(
        'config.urls', 'Addresses configured', FAIL if problems else PASS,
        ' '.join(problems) or 'Browser, internal and callback addresses are set and use https.',
        'Edit the instance and correct the addresses.' if problems else ''))
    from .models import secret_problem
    problem = secret_problem(instance.shared_secret)
    checks.append(DiagnosticCheck(
        'config.secret', 'Shared secret', FAIL if problem else PASS,
        problem or 'A secret is stored (encrypted).',
        'Set a new random secret on the editor and the same one here '
        '(Edit instance → Shared secret).' if problem else ''))
    if not instance.verify_tls:
        checks.append(DiagnosticCheck(
            'config.tls', 'TLS verification', FAIL,
            'Certificate verification is OFF for this instance (set outside the web UI).',
            'Add the private CA under "CA bundle" and turn verification back on '
            '(manage.py office_setup --verify-tls <instance id>).'))
    from .scanning import scanner_configured
    checks.append(DiagnosticCheck(
        'scan', 'Content scanning', PASS if scanner_configured() else WARN,
        'A scan hook is configured (OFFICE_SCAN_HOOK).' if scanner_configured() else
        'No malware scanner is configured: saved files are validated for format only.',
        '' if scanner_configured() else
        'Optional: set OFFICE_SCAN_HOOK to a scanner function (see office/scanning.py).'))
    return checks


def reachability_checks(instance):
    checks = []
    url = instance.server_url()
    if not url:
        return checks
    origin = net._origin(url)
    try:
        net.check_url(url, instance)
        addresses = net.resolve(origin[1], origin[2], instance)
    except net.DestinationNotAllowed as e:
        checks.append(DiagnosticCheck(
            'net.policy', 'Address policy', FAIL, str(e),
            'The editor must resolve to a public, private (LAN/VPN) or, for an '
            'editor on this server, loopback address. Metadata and link-local '
            'addresses are always refused.'))
        return checks
    except net.OfficeFetchError as e:
        checks.append(DiagnosticCheck('net.dns', 'DNS', FAIL, str(e),
                                      'Check the host name and this server\'s DNS settings.'))
        return checks
    checks.append(DiagnosticCheck('net.dns', 'DNS and address policy', PASS,
                                  f'{origin[1]} resolves to {", ".join(addresses)}.'))
    try:
        result = net.fetch(url, instance, 256 * 1024)
    except net.OfficeFetchError as e:
        text = str(e)
        tls = 'TLS' in text or 'certificate' in text.lower()
        checks.append(DiagnosticCheck(
            'net.tls' if tls else 'net.reach', 'TLS' if tls else 'Reachable from clientst0r', FAIL,
            text[:500],
            'Paste the private CA certificate into "CA bundle", or install a certificate '
            'from a public CA.' if tls else
            'Check the firewall between this server and the editor, and that the editor is running.'))
        return checks
    status = PASS if result.status_code < 500 else FAIL
    checks.append(DiagnosticCheck(
        'net.reach', 'Reachable from clientst0r over verified TLS'
        if url.startswith('https') else 'Reachable from clientst0r', status,
        f'HTTP {result.status_code} from {origin[1]}.',
        '' if status == PASS else 'The editor answered with a server error; check its logs.'))
    return checks


def provider_checks(instance):
    try:
        return list(get_provider(instance.provider).diagnostics(instance))
    except NotConfigured as e:
        return [DiagnosticCheck(
            'provider', f'{instance.get_provider_display()} checks', NOT_RUN, str(e),
            'Authentication, WebSocket, callback/WOPI and browser checks run once the '
            'connector is installed.')]


def run_diagnostics(instance, *, user=None, request=None):
    from . import audit
    checks = config_checks(instance) + reachability_checks(instance) + provider_checks(instance)
    audit.log('diagnostics_run', user=user, request=request, object_type='office.instance',
              object_id=instance.pk, object_repr=instance.name,
              description=f'Ran Office diagnostics for {instance.name}',
              extra={'results': {c.key: c.status for c in checks}})
    return checks


def run_health_check(instance, *, user=None, request=None):
    from . import audit
    from .providers import HealthResult
    try:
        result = get_provider(instance.provider).health_check(instance)
    except NotConfigured as e:
        result = HealthResult(status='down', detail=str(e))
    except Exception as e:  # a connector bug must not look healthy
        result = HealthResult(status='down', detail=f'Health check failed: {type(e).__name__}')
    instance.last_check_at = timezone.now()
    instance.health_status = result.status if result.status in ('ok', 'degraded', 'down') else 'down'
    instance.health_detail = (result.detail or '')[:2000]
    fields = ['last_check_at', 'health_status', 'health_detail', 'updated_at']
    if result.version:
        instance.detected_version = result.version[:50]
        fields.append('detected_version')
    if result.edition:
        instance.detected_edition = result.edition[:100]
        fields.append('detected_edition')
    if result.capabilities is not None:
        instance.capabilities = result.capabilities.to_json()
        fields.append('capabilities')
    instance.save(update_fields=fields)
    audit.log('health_check', user=user, request=request, object_type='office.instance',
              object_id=instance.pk, object_repr=instance.name,
              description=f'Health check of {instance.name}: {instance.health_status}',
              success=instance.health_status == 'ok')
    return result


def run_round_trip(instance, user, *, request=None):
    """Create a disposable document in the system scope, open an edit
    session on it, then let the provider drive the editor. Each stage is a
    step in the returned report; stages the provider cannot run are
    reported as not run, never as passed."""
    from datetime import timedelta
    from . import audit, sessions, storage
    from .models import OfficeFile
    from .targets import OfficeFileTarget
    from .creation import blank_bytes

    report = RoundTripReport()
    target = None
    session = None
    try:
        f = OfficeFile.objects.create(
            purpose='diagnostic', organization=None,
            name=f'office-round-trip-{timezone.now():%Y%m%d-%H%M%S}.docx',
            created_by=user, expires_at=timezone.now() + timedelta(days=1))
        target = OfficeFileTarget(f)
        rev = storage.store_initial(target, blank_bytes('docx'), user=user, source='create')
        report.step('create', 'Create a disposable document', PASS,
                    f'Revision {rev.revision_number}, {rev.size} bytes, sha256 {rev.sha256[:12]}…')
    except Exception as e:
        report.step('create', 'Create a disposable document', FAIL, type(e).__name__)
        return report
    try:
        session = sessions.open_session(target, user, mode='edit', instance=instance,
                                        request=request)
        report.step('session', 'Open an edit session', PASS,
                    f'Session opened on revision {session.base_revision.revision_number}.')
    except Exception as e:
        report.step('session', 'Open an edit session', FAIL, str(e)[:300] or type(e).__name__)
        return report
    try:
        get_provider(instance.provider).round_trip(instance, session, report)
    except NotConfigured as e:
        for key, label in (('open', 'Load the document in the editor'),
                           ('edit', 'Change the document'),
                           ('save', 'Save back to clientst0r'),
                           ('reopen', 'Reopen and compare')):
            report.step(key, label, NOT_RUN, str(e))
    except Exception as e:
        report.step('provider', 'Provider round trip', FAIL, type(e).__name__)
    finally:
        sessions.close(session, reason='round trip finished')
    audit.log('round_trip', user=user, request=request, object_type='office.instance',
              object_id=instance.pk, object_repr=instance.name,
              description=f'Office round trip on {instance.name}: '
                          f'{"passed" if report.passed else "not passed"}',
              extra={'steps': {s.key: s.status for s in report.steps}},
              success=report.passed)
    return report
