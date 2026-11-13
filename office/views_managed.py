"""Settings → Integrations → Office Documents → Managed local editor
(ONLYOFFICE Docs or Collabora CODE, one engine at a time).

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
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import audit, diagnostics, drain, install_guidance
from .managed import checks as managed_checks
from .managed import host_setup
from .managed import ipc, jobs
from .managed import probe as managed_probe
from .managed.provision import ProvisionError, managed_instance, status_engine
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


ENGINE_LABELS = {'onlyoffice': 'ONLYOFFICE Docs', 'collabora': 'Collabora Online Development Edition (CODE)'}
LAYOUT_LABELS = {'dedicated': 'Dedicated host name (recommended)',
                 'same-host': 'Same host as clientst0r (Collabora only; shares clientst0r\'s origin)'}


def _engine_choices(status):
    conf = (status or {}).get('config') or {}
    caps = (status or {}).get('capacity') or {}
    return [{'id': e, 'label': ENGINE_LABELS.get(e, e), 'capacity': caps.get(e) or {},
             'layouts': [{'id': x, 'label': LAYOUT_LABELS.get(x, x)}
                         for x in (conf.get('engine_layouts') or {}).get(e, [])]}
            for e in conf.get('engines') or [] if e in ENGINE_LABELS]


def _proxy_status(service):
    if not (service.enabled and service.helper_reachable):
        return None
    try:
        return ipc.call('proxy-status', timeout=15)
    except ipc.HelperError as e:
        return {'error': str(e)}


def _context(service, *, status=None, preflight=None, proxy=None):
    instance = managed_instance()
    status = status if status is not None else (service.status or {})
    op = jobs.active()
    conf = status.get('config') or {}
    try:
        engine = status_engine(status) if status else service.engine
    except ProvisionError:
        engine = service.engine
    installed = status.get('installed') or {}
    present = bool(installed.get('release')) and installed.get('state') != 'uninstalled'
    browser_url = conf.get('browser_url') or ''
    return {
        'engine': engine, 'engine_label': ENGINE_LABELS.get(engine, engine),
        'engine_installed': present, 'engines': _engine_choices(status),
        'layout': conf.get('layout') or 'dedicated',
        'layout_label': LAYOUT_LABELS.get(conf.get('layout') or 'dedicated', ''),
        'proxy': proxy, 'is_code': engine == 'collabora',
        'probe_config': {'url': managed_probe.probe_url(browser_url, engine) if browser_url else '',
                         'resultUrl': reverse('office:managed_probe_result')},
        'last_probe': managed_probe.last_probe(),
        'setup_commands': install_guidance.managed_commands(
            app_url=conf.get('clientstor_url') or getattr(settings, 'SITE_URL', ''),
            office_host=conf.get('office_hostname', ''), deployment_id=conf.get('deployment_id', ''),
            engine=engine,
            layouts=(conf.get('layouts') or ('same-host',)) if engine == 'collabora' else ('dedicated',),
            tls={'local-cert': 'existing-cert', 'letsencrypt': 'certbot', 'upstream': 'upstream'}.get(
                conf.get('proxy_tls') or '', 'existing-cert' if engine == 'onlyoffice' else 'upstream')),
        'service': service, 'status': status, 'instance': instance,
        'operation': op, 'history': ManagedOfficeOperation.objects.select_related('requested_by')[:10],
        'sessions': _sessions_summary(instance), 'checks': preflight,
        'installed_state': ((status.get('installed') or {}).get('state') or 'not installed'),
        'container': status.get('container') or {},
        'updates': status.get('update_available') or [],
        'backups': status.get('backups') or [],
        'weekdays': WEEKDAYS,
        'active_page': 'office_documents',
        'host_setup_available': host_setup.available(),
        'host_setup_busy': service.host_setup_state in ('queued', 'running'),
    }


def _render(request, context):
    """The Managed page, with the editor's origin added to connect-src for
    the browser probe (nothing else)."""
    from types import SimpleNamespace
    from .views import _origin_str, editor_csp
    response = render(request, 'office/settings/managed.html', context)
    url = (context.get('status') or {}).get('config', {}).get('browser_url') or ''
    if url.startswith('https://'):
        origin = _origin_str(url)
        response = editor_csp(request, response, SimpleNamespace(browser_url=url),
                              {'connect-src': [origin]})
    return response


@login_required
@superuser_required
@require_GET
def managed_page(request):
    service = ManagedOfficeService.get()
    status = jobs.refresh_status(timeout=10) if service.enabled else None
    service = ManagedOfficeService.get()
    context = _context(service, status=status, proxy=_proxy_status(service))
    app_host = request.get_host().split(':')[0].lower()
    context['setup_defaults'] = {'app_host': app_host,
                                 'deployment_id': host_setup.default_deployment_id(app_host)}
    return _render(request, context)


@login_required
@superuser_required
@require_POST
def managed_host_setup(request):
    """Queue the one-time server setup (Docker, the Office service helper,
    its Nginx files). The scheduler runs it through the root helper; this
    view only records the request. clientst0r's host name is the one this
    request came in on (Django has already checked it against
    ALLOWED_HOSTS)."""
    if not host_setup.available():
        messages.error(request, 'The root helper is not available on this server; use the commands below.')
        return redirect('office:managed')
    layout = request.POST.get('layout', '')
    if layout == 'same-host' and request.POST.get('accept_same_host') != '1':
        messages.error(request, 'Confirm that you understand the same-host risk first.')
        return redirect('office:managed')
    try:
        host_setup.request_setup(
            request.user, request=request, engine=request.POST.get('engine', ''), layout=layout,
            app_host=request.get_host().split(':')[0], office_host=request.POST.get('office_host', ''),
            deployment_id=request.POST.get('deployment_id', '').strip().lower(),
            allow_untested=request.POST.get('allow_untested') == '1')
    except host_setup.SetupError as e:
        messages.error(request, str(e))
        return redirect('office:managed')
    messages.success(request, 'Server setup queued. The scheduler starts it within a minute; it can take '
                              'several minutes (Docker is downloaded on first setup). Refresh this page '
                              'to see the output.')
    return redirect('office:managed')


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
              object_id=1, object_repr='Managed Office editor',
              description=f'Managed local editor turned {"on" if turn_on else "off"}',
              extra={'changed': ['enabled']})
    messages.success(request, 'Managed local editing is on. Run the setup checks next.' if turn_on else
                     'Managed local editing is off. The editor container is left as it is; '
                     'stop or uninstall it first if you want it gone.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_POST
def managed_action(request):
    service = ManagedOfficeService.get()
    action = request.POST.get('action', '')
    if not service.enabled:
        messages.error(request, 'Turn managed local editing on first.')
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
              object_id=1, object_repr='Managed Office editor',
              description='Ran managed local editor setup checks',
              extra={'results': {c.key: c.status for c in checks}})
    service = ManagedOfficeService.get()
    return _render(request, _context(service, preflight=checks, proxy=_proxy_status(service)))


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
              object_id=1, object_repr='Managed Office editor',
              description=f'Viewed managed editor diagnostics ({lines} log lines)')
    if request.GET.get('download') == '1':
        import json
        body = ('# Managed local editor diagnostics (redacted by the Office service helper)\n'
                f'# generated {timezone.now().isoformat()}\n\n## status\n'
                + json.dumps(status or {'error': ManagedOfficeService.get().status_error},
                             indent=1, default=str)
                + '\n\n## container log (last %d lines)\n' % lines + (log_text or log_error))
        response = HttpResponse(body, content_type='text/plain; charset=utf-8')
        try:
            engine = status_engine(status or {})
        except ProvisionError:
            engine = 'office'
        response['Content-Disposition'] = f'attachment; filename="managed-{engine}-diagnostics.txt"'
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
              object_id=1, object_repr='Managed Office editor',
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


def _installed(service):
    st = service.status or {}
    inst = st.get('installed') or {}
    return bool(inst.get('release')) and inst.get('state') != 'uninstalled'


@login_required
@superuser_required
@require_POST
def managed_engine(request):
    """Choose the engine. Nothing installed yet: the choice is saved and
    Install installs it. An engine is installed: queue Switch engine (drain,
    uninstall it with its data kept, install the other, verify)."""
    service = ManagedOfficeService.get()
    if not service.enabled:
        messages.error(request, 'Turn managed local editing on first.')
        return redirect('office:managed')
    engine = request.POST.get('engine', '')
    allowed = ((service.status or {}).get('config') or {}).get('engines') or []
    if engine not in ENGINE_LABELS or engine not in allowed:
        messages.error(request, 'That engine is not enabled for this server (ENGINES in the root '
                                'configuration).')
        return redirect('office:managed')
    try:
        current = status_engine(service.status or {})
    except ProvisionError:
        current = service.engine
    if not _installed(service) or engine == current:
        service.engine = engine
        service.updated_by = request.user
        service.save()
        audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
                  object_id=1, object_repr='Managed Office editor',
                  description=f'Managed editor engine set to {ENGINE_LABELS[engine]}',
                  extra={'changed': ['engine'], 'engine': engine})
        messages.success(request, f'{ENGINE_LABELS[engine]} selected. Run the setup checks, then Install.')
        return redirect('office:managed')
    if request.POST.get('confirm', '').strip().lower() != 'switch':
        messages.error(request, 'Type "switch" to confirm switching engines.')
        return redirect('office:managed')
    try:
        op = jobs.enqueue('switch_engine', user=request.user, engine=engine, request=request)
    except jobs.AlreadyActive as e:
        messages.error(request, str(e))
        return redirect('office:managed')
    messages.success(request, f'{op.get_action_display()} to {ENGINE_LABELS[engine]} queued. Editing '
                              'sessions are drained first; documents stay in clientst0r.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_POST
def managed_layout(request):
    """Switch between a dedicated editor host name and Collabora's same-host
    layout. Same-host needs an explicit acknowledgement of the origin-sharing
    risk; it is recorded and audited."""
    service = ManagedOfficeService.get()
    if not service.enabled:
        messages.error(request, 'Turn managed local editing on first.')
        return redirect('office:managed')
    layout = request.POST.get('layout', '')
    conf = (service.status or {}).get('config') or {}
    try:
        engine = status_engine(service.status or {})
    except ProvisionError:
        engine = service.engine
    allowed = (conf.get('engine_layouts') or {}).get(engine) or []
    if layout not in LAYOUT_LABELS or layout not in allowed:
        messages.error(request, 'That address layout is not available for this engine here '
                                '(PROXY_LAYOUTS in the root configuration).')
        return redirect('office:managed')
    if layout == 'same-host':
        if request.POST.get('accept_same_host') != '1':
            messages.error(request, 'Confirm that you understand the same-host risk first.')
            return redirect('office:managed')
        service.same_host_acknowledged_at = timezone.now()
        service.same_host_acknowledged_by = request.user
        service.save(update_fields=['same_host_acknowledged_at', 'same_host_acknowledged_by'])
        audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
                  object_id=1, object_repr='Managed Office editor',
                  description='Accepted the same-host layout warning: the Collabora front-end will run '
                              'on clientst0r\'s own origin',
                  extra={'changed': ['same_host_acknowledged'], 'layout': layout})
    try:
        op = jobs.enqueue('set_layout', user=request.user, layout=layout, request=request)
    except jobs.AlreadyActive as e:
        messages.error(request, str(e))
        return redirect('office:managed')
    messages.success(request, f'{op.get_action_display()} to "{LAYOUT_LABELS[layout]}" queued. Sessions '
                              'are drained, the proxy files are rewritten and the editor is re-created; '
                              'nothing is reinstalled.')
    return redirect('office:managed')


def _expected_host(service):
    conf = (service.status or {}).get('config') or {}
    url = conf.get('browser_url') or ''
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or '') if url.startswith('https://') else '', conf


@login_required
@superuser_required
@require_POST
def managed_proxy(request):
    """Install or remove the helper's own Nginx files for the editor host
    name. The host name is the one the root configuration assigns to the
    current layout; it is checked here (format, Django's ALLOWED_HOSTS for
    the same-host layout, a distinct origin for a dedicated one) and again
    by the helper."""
    service = ManagedOfficeService.get()
    if not service.enabled:
        messages.error(request, 'Turn managed local editing on first.')
        return redirect('office:managed')
    action = request.POST.get('action', '')
    if action not in ('install', 'remove'):
        messages.error(request, 'Unknown action.')
        return redirect('office:managed')
    if jobs.active() is not None:
        messages.error(request, 'Wait for the running operation to finish first.')
        return redirect('office:managed')
    host, conf = _expected_host(service)
    posted = request.POST.get('hostname', '').strip().lower()
    if action == 'install':
        cs_host = (conf.get('clientstor_url') or '').split('//')[-1].strip('/')
        layout = conf.get('layout') or 'dedicated'
        allowed_hosts = [h.lower() for h in getattr(settings, 'ALLOWED_HOSTS', [])]
        problem = ''
        if not host or posted != host or not ipc.HOST_RE.match(posted):
            problem = 'The host name does not match the one configured for this layout.'
        elif layout == 'same-host' and posted != cs_host:
            problem = 'The same-host layout serves clientst0r\'s own host name only.'
        elif layout == 'same-host' and not ('*' in allowed_hosts or posted in allowed_hosts
                                            or any(h.startswith('.') and posted.endswith(h)
                                                   for h in allowed_hosts)):
            problem = f'{posted} is not in clientst0r\'s ALLOWED_HOSTS.'
        elif layout == 'dedicated' and posted == cs_host:
            problem = 'A dedicated editor host name must differ from clientst0r\'s.'
        if problem:
            messages.error(request, problem)
            return redirect('office:managed')
        try:
            result = ipc.call('proxy-install', {'hostname': posted})
        except (ipc.HelperError, ValueError) as e:
            audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
                      object_id=1, object_repr='Managed Office editor', success=False,
                      description=f'Installing the editor proxy configuration for {posted} failed: {e}'[:500],
                      extra={'changed': ['proxy'], 'hostname': posted})
            messages.error(request, f'Not installed: {e}'[:600])
            return redirect('office:managed')
        audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
                  object_id=1, object_repr='Managed Office editor',
                  description=f'Installed the editor proxy configuration for {posted} '
                              f'({result.get("layout")})',
                  extra={'changed': ['proxy'], 'hostname': posted, 'layout': result.get('layout')})
        messages.success(request, ('Proxy configuration installed and Nginx reloaded. '
                                   + (result.get('note') or '')).strip()[:600])
        return redirect('office:managed')
    if request.POST.get('confirm', '').strip().lower() != 'remove':
        messages.error(request, 'Type "remove" to confirm.')
        return redirect('office:managed')
    try:
        ipc.call('proxy-remove')
    except ipc.HelperError as e:
        messages.error(request, f'Not removed: {e}'[:600])
        return redirect('office:managed')
    audit.log('settings_change', user=request.user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed Office editor',
              description='Removed the editor proxy configuration', extra={'changed': ['proxy']})
    messages.success(request, 'Proxy configuration removed; Nginx reloaded.')
    return redirect('office:managed')


@login_required
@superuser_required
@require_POST
def managed_probe_result(request):
    outcome = request.POST.get('outcome', '')
    if outcome not in managed_probe.OUTCOMES:
        return JsonResponse({'ok': False}, status=400)
    service = ManagedOfficeService.get()
    host, conf = _expected_host(service)
    try:
        engine = status_engine(service.status or {})
    except ProvisionError:
        engine = service.engine
    url = managed_probe.probe_url(conf.get('browser_url') or '', engine) if host else ''
    audit.log('browser_probe', user=request.user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed Office editor', success=outcome == 'reached',
              description=f'Browser probe of the managed editor: {outcome}',
              extra={'outcome': outcome, 'url': url,
                     'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200]})
    return JsonResponse({'ok': True})
