"""Configure the existing provider for the managed container.

After an install/start/update/rollback/engine switch/layout switch succeeded
on the server, the job calls ``configure(status)``. Which provider is
configured follows the engine the helper reports as installed
(``status["engine"]``):

* ONLYOFFICE -> one EditorInstance(provider='onlyoffice', mode='managed_local');
* Collabora (CODE) -> one EditorInstance(provider='collabora',
  mode='managed_local').

Each is created once, then updated in place, so sessions, policy defaults
and organization choices keep pointing at it. Addresses come from the
helper's root-owned configuration only:

* browser URL ``https://<host>/``: the dedicated office host name, or, for
  Collabora's same-host layout, clientst0r's own host name;
* internal URL ``http://127.0.0.1:<port>/`` (clientst0r -> container,
  loopback);
* callback URL = CLIENTSTOR_URL (the container -> clientst0r, through the
  callback route the helper's firewall allows).

Secrets: ONLYOFFICE's JWT secret comes from the helper (op ``secret``)
straight into the encrypted field; it is never logged, rendered or
returned. Collabora signs WOPI requests with its proof key (published in
discovery), not with a shared secret; the instance's secret field is
filled with a random value generated here only because the generic
instance checks expect one. The Collabora admin password stays in the
helper's root-only files.

TLS verification stays on; no CA bundle is set. The engine's provider is
added to the enabled providers, and the instance becomes the platform
default only when no default exists (or when the default was the other
managed instance, i.e. an engine switch). The instance of the engine that is
*not* installed is closed to users.

Then the normal health check runs (office.diagnostics.run_health_check).
"""
from __future__ import annotations

import secrets as _secrets
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from office import audit, diagnostics
from office.models import EditorInstance, ManagedOfficeService, OfficeSettings, secret_problem

from . import ipc

DEFAULT_NAMES = {'onlyoffice': 'Managed ONLYOFFICE (this server)',
                 'collabora': 'Managed Collabora CODE (this server)'}
DEFAULT_NAME = DEFAULT_NAMES['onlyoffice']
ENGINE_LABELS = {'onlyoffice': 'ONLYOFFICE', 'collabora': 'Collabora (CODE)'}


class ProvisionError(Exception):
    pass


def _url(value, *, scheme, loopback=False):
    parts = urlsplit(value or '')
    if parts.scheme != scheme or not parts.hostname or parts.username or parts.query:
        raise ProvisionError(f'The helper reported an unexpected address: {value!r}')
    if loopback and parts.hostname != '127.0.0.1':
        raise ProvisionError('The internal address must be 127.0.0.1')
    if not loopback and parts.hostname in ('localhost', '127.0.0.1', '::1'):
        raise ProvisionError('The browser and callback addresses must be host names')
    return value.rstrip('/') + '/'


def status_engine(status):
    """The engine the helper runs (or will run): 'onlyoffice' | 'collabora'."""
    status = status or {}
    engine = (status.get('installed') or {}).get('engine') or status.get('engine') \
        or (status.get('config') or {}).get('engine') or 'onlyoffice'
    if engine not in DEFAULT_NAMES:
        raise ProvisionError(f'The helper reported an unknown engine: {engine!r}')
    return engine


def urls_from_status(status):
    conf = (status or {}).get('config') or {}
    urls = {
        'browser_url': _url(conf.get('browser_url'), scheme='https'),
        'internal_url': _url(conf.get('internal_url'), scheme='http', loopback=True),
        'callback_base_url': _url(conf.get('clientstor_url'), scheme='https'),
    }
    layout = conf.get('layout') or 'dedicated'
    same_origin = urlsplit(urls['browser_url']).hostname == urlsplit(urls['callback_base_url']).hostname
    if same_origin and not (layout == 'same-host' and status_engine(status) == 'collabora'):
        raise ProvisionError('The editor shares clientst0r\'s host name, which only Collabora\'s '
                             'same-host layout allows.')
    if layout == 'same-host' and not same_origin:
        raise ProvisionError('The same-host layout must use clientst0r\'s own host name.')
    return urls


def managed_instance(engine=None):
    """The managed EditorInstance of `engine` (default: the one the service
    points at, i.e. the engine installed last)."""
    service = ManagedOfficeService.get()
    if engine is None:
        if service.instance_id:
            return service.instance
        return EditorInstance.objects.filter(mode='managed_local').order_by('pk').first()
    if service.instance_id and service.instance and service.instance.provider == engine:
        return service.instance
    return EditorInstance.objects.filter(mode='managed_local', provider=engine).order_by('pk').first()


def configure(status, *, user=None, enable=False):
    """Write the managed EditorInstance; returns (instance, HealthResult)."""
    engine = status_engine(status)
    urls = urls_from_status(status)
    if engine == 'onlyoffice':
        secret = (ipc.call('secret') or {}).get('jwt_secret', '')
        problem = secret_problem(secret)
        if problem:
            raise ProvisionError(f'The helper returned an unusable JWT secret: {problem}')
    else:
        secret = None       # generated below once, only for an empty field
    with transaction.atomic():
        service = ManagedOfficeService.objects.select_for_update().get_or_create(pk=1)[0]
        instance = managed_instance(engine)
        created = instance is None
        if created:
            name = DEFAULT_NAMES[engine]
            if EditorInstance.objects.filter(name=name).exists():
                name = f'{DEFAULT_NAMES[engine]} {timezone.now():%Y%m%d%H%M}'
            instance = EditorInstance(name=name, created_by=user, shared=True)
        changed = []
        for field, value in dict(urls, provider=engine, mode='managed_local').items():
            if getattr(instance, field) != value:
                setattr(instance, field, value)
                changed.append(field)
        if secret is not None and instance.shared_secret != secret:
            instance.shared_secret = secret
            changed.append('shared_secret (value not logged)')
        if secret is None and secret_problem(instance.shared_secret or ''):
            instance.shared_secret = _secrets.token_urlsafe(48)
            changed.append('shared_secret (random placeholder; Collabora uses proof keys)')
        if instance.ca_bundle:
            instance.ca_bundle = ''
            changed.append('ca_bundle')
        if engine == 'collabora':
            opts = dict(instance.provider_options or {})
            if opts.get('require_proof') is not True:
                opts['require_proof'] = True
                instance.provider_options = opts
                changed.append('provider_options.require_proof')
        if changed:
            instance.health_status, instance.health_detail, instance.last_check_at = 'unknown', '', None
        instance.save()
        previous = service.instance
        service.instance = instance
        service.engine = engine
        service.save(update_fields=['instance', 'engine'])
        # The managed instance of the other engine is not running any more.
        others = EditorInstance.objects.filter(mode='managed_local').exclude(pk=instance.pk)
        closed = list(others.filter(enabled=True).values_list('name', flat=True))
        others.update(enabled=False, health_status='down',
                      health_detail='Not running: the managed service runs the other engine.')
        settings_obj = OfficeSettings.get()
        policy_changed = []
        if engine not in (settings_obj.enabled_providers or []):
            settings_obj.enabled_providers = list(settings_obj.enabled_providers or []) + [engine]
            policy_changed.append('enabled_providers')
        default_is_other_managed = (settings_obj.default_instance_id is not None
                                    and previous is not None and previous.pk != instance.pk
                                    and settings_obj.default_instance_id == previous.pk)
        if settings_obj.default_instance_id is None or default_is_other_managed:
            settings_obj.default_instance = instance
            policy_changed.append('default_instance')
        if policy_changed:
            settings_obj.save()
    audit.log('settings_change', user=user, object_type='office.instance', object_id=instance.pk,
              object_repr=instance.name,
              description=(f'{"Created" if created else "Updated"} the managed {ENGINE_LABELS[engine]} '
                           f'instance {instance.name}: {", ".join(changed) or "no changes"}'
                           + (f'; Office policy: {", ".join(policy_changed)}' if policy_changed else '')
                           + (f'; closed: {", ".join(closed)}' if closed else '')),
              extra={'changed': changed, 'policy_changed': policy_changed, 'managed': True,
                     'engine': engine})
    result = diagnostics.run_health_check(instance, user=user)
    instance.refresh_from_db()
    if enable and result.status == 'ok' and not instance.enabled:
        EditorInstance.objects.filter(pk=instance.pk).update(enabled=True)
        instance.enabled = True
    return instance, result
