"""Set up this server for the managed editor from Settings.

The pieces that need root (Docker, the Office service helper and its
firewall unit, the helper's Nginx files and, for the same-host layout, the
include line in clientst0r's own site) are installed by the root helper's
``office-setup`` and ``office-site-include`` actions. The root helper runs
the installer from the signed release it was installed from, never from the
app directory, and checks every argument again.

A deployment administrator requests the setup on the Managed page. The web
process only records the request; the scheduler's ``office_managed
--run-pending`` starts ``office_managed --host-setup-run`` in its own
process, which calls the root helper and stores the output here.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core import root_helper

from .. import audit
from ..models import ManagedOfficeService
from .ipc import HOST_RE

DEPLOYMENT_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,40}$')
ENGINES = ('collabora', 'onlyoffice')
LAYOUTS = ('same-host', 'dedicated')
SETUP_TIMEOUT = 45 * 60
INCLUDE_TIMEOUT = 3 * 60
STALE_AFTER = timezone.timedelta(minutes=60)
OUTPUT_LIMIT = 20000


class SetupError(Exception):
    pass


def available() -> bool:
    """The root helper is installed and this account may run it."""
    return root_helper.is_usable()


def default_deployment_id(host: str) -> str:
    slug = re.sub(r'[^a-z0-9-]+', '-', (host or '').lower()).strip('-')[:41].strip('-')
    return slug if DEPLOYMENT_RE.match(slug) else 'clientst0r'


def validate(*, engine, layout, app_host, deployment_id, office_host=''):
    """The same checks the root helper makes, so the page can say what is
    wrong before anything is queued."""
    app_host = (app_host or '').strip().lower()
    office_host = (office_host or '').strip().lower()
    if engine not in ENGINES:
        raise SetupError('Pick an engine.')
    if layout not in LAYOUTS:
        raise SetupError('Pick an address layout.')
    if engine == 'onlyoffice' and layout != 'dedicated':
        raise SetupError('ONLYOFFICE runs only on a dedicated host name.')
    if not HOST_RE.match(app_host) or '.' not in app_host:
        raise SetupError('clientst0r\'s host name is not a valid DNS name.')
    if not DEPLOYMENT_RE.match(deployment_id or ''):
        raise SetupError('The deployment id may use lowercase letters, digits and hyphens (2-41).')
    if layout == 'dedicated':
        if not HOST_RE.match(office_host) or '.' not in office_host or office_host == app_host:
            raise SetupError('A dedicated layout needs its own editor host name, different from clientst0r\'s.')
    else:
        office_host = ''
    return {'engine': engine, 'layout': layout, 'app_host': app_host,
            'deployment_id': deployment_id, 'office_host': office_host}


def request_setup(user, *, allow_untested, request=None, **fields):
    data = validate(**fields)
    data['allow_untested'] = bool(allow_untested)
    with transaction.atomic():
        service = ManagedOfficeService.objects.select_for_update().get_or_create(pk=1)[0]
        if service.host_setup_state in ('queued', 'running'):
            raise SetupError('A server setup is already queued or running.')
        service.host_setup_state = 'queued'
        service.host_setup_request = data
        service.host_setup_output = ''
        service.host_setup_requested_by = user
        service.host_setup_requested_at = timezone.now()
        service.host_setup_started_at = service.host_setup_finished_at = None
        service.engine = data['engine']
        if data['layout'] == 'same-host':
            service.same_host_acknowledged_at = timezone.now()
            service.same_host_acknowledged_by = user
        service.save()
    audit.log('settings_change', user=user, request=request, object_type='office.managed',
              object_id=1, object_repr='Managed Office editor',
              description=(f'Server setup queued: {data["engine"]}, {data["layout"]} layout'
                           + (', same-host warning accepted' if data['layout'] == 'same-host' else '')
                           + (', untested releases allowed' if data['allow_untested'] else '')),
              extra={'changed': ['host_setup'], **data})
    return service


def helper_args(data):
    layouts = data['layout']
    return ['office-setup', data['engine'], layouts, data['app_host'], data['deployment_id'],
            data['office_host'] or '-', 'untested' if data.get('allow_untested') else 'tested']


def maybe_start():
    """Called by the scheduler. Starts a queued setup in its own process and
    fails one whose process has not reported for an hour."""
    now = timezone.now()
    service = ManagedOfficeService.get()
    if service.host_setup_state == 'running' and service.host_setup_started_at \
            and now - service.host_setup_started_at > STALE_AFTER:
        ManagedOfficeService.objects.filter(pk=1, host_setup_state='running').update(
            host_setup_state='failed', host_setup_finished_at=now,
            host_setup_output=(service.host_setup_output + '\n\nThe setup process stopped reporting; '
                               'see the root helper log (journalctl -t clientst0r-root-helper).')[-OUTPUT_LIMIT:])
        return None
    if service.host_setup_state != 'queued':
        return None
    lease = uuid.uuid4().hex
    claimed = ManagedOfficeService.objects.filter(pk=1, host_setup_state='queued').update(
        host_setup_state='running', host_setup_started_at=now,
        host_setup_request={**service.host_setup_request, 'lease': lease})
    if not claimed:
        return None
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(settings.BASE_DIR, 'manage.py'), 'office_managed',
             '--host-setup-run', lease],
            cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        _finish(False, f'Could not start the setup process: {e}')
        return None
    return lease


def _finish(ok, output):
    ManagedOfficeService.objects.filter(pk=1).update(
        host_setup_state='succeeded' if ok else 'failed', host_setup_finished_at=timezone.now(),
        host_setup_output=output[-OUTPUT_LIMIT:])


def _output(result):
    return ((result.stdout or '') + ('\n' + result.stderr if result.stderr else '')).strip()


def run(lease):
    """The setup itself, in the process maybe_start() started."""
    service = ManagedOfficeService.get()
    data = service.host_setup_request or {}
    if service.host_setup_state != 'running' or data.get('lease') != lease:
        return False
    try:
        validate(**{k: data.get(k, '') for k in ('engine', 'layout', 'app_host', 'deployment_id',
                                                'office_host')})
    except SetupError as e:
        _finish(False, str(e))
        return False
    parts, ok = [], False
    try:
        result = root_helper.run(helper_args(data), timeout=SETUP_TIMEOUT)
        if result is None:
            parts.append('The root helper is not installed on this server.')
        else:
            parts.append(_output(result))
            ok = result.returncode == 0
            if ok and data['layout'] == 'same-host':
                inc = root_helper.run(['office-site-include', 'on'], timeout=INCLUDE_TIMEOUT)
                parts.append(_output(inc))
                ok = inc.returncode == 0
    except subprocess.TimeoutExpired:
        parts.append(f'The setup did not finish within {SETUP_TIMEOUT // 60} minutes.')
        ok = False
    output = '\n\n'.join(p for p in parts if p)
    _finish(ok, output)
    if ok:
        ManagedOfficeService.objects.filter(pk=1).update(enabled=True)
        from . import jobs
        jobs.refresh_status(timeout=15)
    audit.log('settings_change', user=service.host_setup_requested_by, object_type='office.managed',
              object_id=1, object_repr='Managed Office editor', success=ok,
              description=f'Server setup {"finished" if ok else "failed"}: {data["engine"]}, '
                          f'{data["layout"]} layout',
              extra={'changed': ['host_setup'], 'engine': data['engine'], 'layout': data['layout']})
    return ok
