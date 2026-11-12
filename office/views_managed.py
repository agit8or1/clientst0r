"""Settings → Integrations → Office Documents → Managed Local ONLYOFFICE.

Deployment administrators (superusers) only, like every other Office
endpoint/installation setting. Ordinary users and customer-portal users get
the login redirect / 403 from the same decorators the rest of the Office
settings use. Every POST is CSRF-protected (no csrf_exempt here) and
audited; lifecycle actions only *queue* a background operation
(office.managed.jobs), which the scheduler runs.

Docker details (container, image digest, logs) are shown on these pages
only; document users see the editor as before.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import audit, diagnostics, drain, install_guidance
from .managed import checks as managed_checks
from .managed import ipc, jobs
from .managed.provision import managed_instance
from .models import EditSession, ManagedOfficeOperation, ManagedOfficeService, QuarantinedSave
from .views_admin import superuser_required

WEEKDAYS = list(enumerate(('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
                           'Sunday')))
LIFECYCLE = ('install', 'start', 'stop', 'restart', 'update', 'rollback', 'uninstall')


def _sessions_summary(instance):
    if instance is None:
        return {'live': 0, 'stale': 0, 'edit': 0, 'errors': 0, 'quarantined': 0}
    now = timezone.now()
    live = list(drain.live_any_expiry(instance))
    since = now - timezone.timedelta(days=30)
    return {
        'live': sum(1 for s in live if s.expires_at > now),
        # Expired but never closed: the editor may still hold changes; a
        # drain asks the editor about each of them.
        'stale': sum(1 for s in live if s.expires_at <= now),
        'edit': sum(1 for s in live if s.mode == 'edit'),
        'errors': sum(1 for s in live if (s.provider_state or {}).get('oo_last_error')),
        'quarantined': QuarantinedSave.objects.filter(session__instance=instance,
                                                      received_at__gte=since).count(),
    }


def _context(service, *, status=None, preflight=None):
    instance = managed_instance()
    status = status if status is not None else (service.status or {})
    op = jobs.active()
    conf = status.get('config') or {}
    return {
        'setup_commands': install_guidance.managed_commands(
            app_url=conf.get('clientstor_url') or getattr(settings, 'SITE_URL', ''),
            office_host=conf.get('office_hostname', ''), deployment_id=conf.get('deployment_id', '')),
        'service': service, 'status': status, 'instance': instance,
        'operation': op, 'history': ManagedOfficeOperation.objects.select_related('requested_by')[:10],
        'sessions': _sessions_summary(instance), 'checks': preflight,
        'installed_state': ((status.get('installed') or {}).get('state') or 'not installed'),
        'container': status.get('container') or {},
        'updates': status.get('update_available') or [],
        'backups': status.get('backups') or [],
        'weekdays': WEEKDAYS,
        'active_page': 'office_documents',
    }


@login_required
@superuser_required
@require_GET
def managed_page(request):
    service = ManagedOfficeService.get()
    status = jobs.refresh_status(timeout=10) if service.enabled else None
    return render(request, 'office/settings/managed.html',
                  _context(ManagedOfficeService.get(), status=status))


@login_required
@superuser_required
@require_POST
def managed_toggle(request):
    service = ManagedOfficeService.get()
    turn_on = request.POST.get('enabled') == '1'
    if not turn_on and jobs.active() is not None:
        messages.error(request, 'Wait for the running operation to finish first.')
        return redirect('office:managed')
    service.enabled = turn_on
    service.updated_by = request.user
    service.save()
    audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed ONLYOFFICE',
              description=f'Managed Local ONLYOFFICE turned {"on" if turn_on else "off"}',
              extra={'changed': ['enabled']})
    messages.success(request, 'Managed Local ONLYOFFICE is on. Run the setup checks next.' if turn_on else
                     'Managed Local ONLYOFFICE is off. The editor container is left as it is; '
                     'stop or uninstall it first if you want it gone.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_POST
def managed_action(request):
    service = ManagedOfficeService.get()
    action = request.POST.get('action', '')
    if not service.enabled:
        messages.error(request, 'Turn Managed Local ONLYOFFICE on first.')
        return redirect('office:managed')
    if action not in LIFECYCLE:
        messages.error(request, 'Unknown action.')
        return redirect('office:managed')
    release = ''
    if action == 'update':
        release = request.POST.get('release', '')
        offered = {u.get('id') for u in (service.status or {}).get('update_available') or []
                   if u.get('installable')}
        if release not in offered:
            messages.error(request, 'Pick one of the offered releases.')
            return redirect('office:managed')
    if action == 'uninstall' and request.POST.get('confirm', '').strip().lower() != 'uninstall':
        messages.error(request, 'Type "uninstall" to confirm.')
        return redirect('office:managed')
    try:
        op = jobs.enqueue(action, user=request.user, release=release, request=request)
    except jobs.AlreadyActive as e:
        messages.error(request, str(e))
        return redirect('office:managed')
    messages.success(request, f'{op.get_action_display()} queued. Editing sessions are drained first '
                              f'where needed; progress is shown below.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_POST
def managed_cancel(request, pk):
    op = ManagedOfficeOperation.objects.filter(pk=pk).first()
    if op is None or not jobs.cancel(op, user=request.user, request=request):
        messages.error(request, 'Only a queued operation that has not started can be cancelled.')
    else:
        messages.success(request, 'Cancelled.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_POST
def managed_checks_view(request):
    service = ManagedOfficeService.get()
    checks = managed_checks.run(service)
    audit.log('diagnostics_run', user=request.user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed ONLYOFFICE',
              description='Ran Managed Local ONLYOFFICE setup checks',
              extra={'results': {c.key: c.status for c in checks}})
    return render(request, 'office/settings/managed.html',
                  _context(ManagedOfficeService.get(), preflight=checks))


@login_required
@superuser_required
@require_POST
def managed_test(request):
    """Test Connection: helper status, then the provider health check
    (healthcheck, JWT, version/edition, ONLYOFFICE -> clientst0r download)."""
    status = jobs.refresh_status()
    instance = managed_instance()
    if status is None or instance is None:
        messages.error(request, 'Not installed yet, or the helper is unreachable: '
                       + (ManagedOfficeService.get().status_error or 'install first'))
        return redirect('office:managed')
    result = diagnostics.run_health_check(instance, user=request.user, request=request)
    if result.status == 'ok':
        ManagedOfficeService.objects.filter(pk=1).update(last_connection_ok_at=timezone.now(),
                                                        last_connection_detail=result.detail[:2000])
        messages.success(request, f'Connection OK. {result.detail}'[:500])
    else:
        messages.warning(request, f'Connection check: {result.status}. {result.detail}'[:500])
    return redirect('office:managed')


@login_required
@superuser_required
@require_http_methods(['GET', 'POST'])
def managed_diagnostics(request):
    """Redacted diagnostics: helper status (no secrets) and the bounded,
    redacted container log. ?download=1 returns them as a text file."""
    lines = 200
    if request.GET.get('lines', '').isdigit():
        lines = max(1, min(500, int(request.GET['lines'])))
    status = jobs.refresh_status()
    try:
        log_text = ipc.call('logs', {'lines': lines}).get('log', '')
        log_error = ''
    except ipc.HelperError as e:
        log_text, log_error = '', str(e)
    audit.log('diagnostics_run', user=request.user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed ONLYOFFICE',
              description=f'Viewed Managed ONLYOFFICE diagnostics ({lines} log lines)')
    if request.GET.get('download') == '1':
        import json
        body = ('# Managed ONLYOFFICE diagnostics (redacted by the Office service helper)\n'
                f'# generated {timezone.now().isoformat()}\n\n## status\n'
                + json.dumps(status or {'error': ManagedOfficeService.get().status_error},
                             indent=1, default=str)
                + '\n\n## container log (last %d lines)\n' % lines + (log_text or log_error))
        response = HttpResponse(body, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="managed-onlyoffice-diagnostics.txt"'
        return response
    return render(request, 'office/settings/managed_diagnostics.html', {
        'status': status, 'log_text': log_text, 'log_error': log_error, 'lines': lines,
        'active_page': 'office_documents',
    })


@login_required
@superuser_required
@require_POST
def managed_maintenance(request):
    service = ManagedOfficeService.get()
    try:
        hour = int(request.POST.get('maintenance_hour', service.maintenance_hour))
        hours = int(request.POST.get('maintenance_hours', service.maintenance_hours))
        weekday = request.POST.get('maintenance_weekday', '')
        weekday = None if weekday == '' else int(weekday)
    except ValueError:
        messages.error(request, 'Enter whole numbers.')
        return redirect('office:managed')
    if not (0 <= hour <= 23 and 1 <= hours <= 6 and (weekday is None or 0 <= weekday <= 6)):
        messages.error(request, 'Hour 0-23, length 1-6 hours, weekday 0-6 or every day.')
        return redirect('office:managed')
    service.maintenance_updates = request.POST.get('maintenance_updates') == '1'
    service.maintenance_hour, service.maintenance_hours = hour, hours
    service.maintenance_weekday = weekday
    service.updated_by = request.user
    service.save()
    audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed ONLYOFFICE',
              description=f'Maintenance-window updates {"on" if service.maintenance_updates else "off"} '
                          f'(weekday {weekday if weekday is not None else "any"}, {hour:02d}:00, {hours} h)',
              extra={'changed': ['maintenance']})
    messages.success(request, 'Saved.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_GET
def managed_progress(request):
    """JSON for the progress panel (polled by static/js/office-managed.js)."""
    op = jobs.active() or ManagedOfficeOperation.objects.first()
    if op is None:
        return JsonResponse({'operation': None})
    return JsonResponse({'operation': {
        'id': op.pk, 'action': op.get_action_display(), 'state': op.state,
        'state_label': op.get_state_display(), 'active': op.is_active,
        'message': (op.progress or {}).get('message', ''),
        'steps': (op.progress or {}).get('steps', [])[-15:], 'error': op.error[:2000],
    }})
