"""Configure the existing ONLYOFFICE provider for the managed container.

After an install/start/update/rollback succeeded on the server, the job
calls ``configure(status)``:

* one EditorInstance with ``mode='managed_local'`` (created once, then
  updated in place, so sessions, policy defaults and organization choices
  keep pointing at it);
* browser URL ``https://<OFFICE_HOSTNAME>/`` (users' browsers, through the
  host's reverse proxy), internal URL ``http://127.0.0.1:<BIND_PORT>/``
  (clientst0r -> container, loopback), callback URL = CLIENTSTOR_URL (the
  container -> clientst0r, through the bridge gateway and the same proxy).
  All three come from the helper's root-owned configuration;
* the JWT secret comes from the helper (op ``secret``) straight into the
  encrypted field; it is never logged, rendered or returned;
* TLS verification stays on; no CA bundle is set (the browser URL is the
  host's own certificate, the internal URL is plain loopback http);
* ``onlyoffice`` is added to the enabled providers, and the instance
  becomes the platform default only when no default exists.

Then the normal health check runs (office.diagnostics.run_health_check):
/healthcheck, signed ``version`` command, edition, and a conversion that
makes the container download a file from clientst0r.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from office import audit, diagnostics
from office.models import EditorInstance, ManagedOfficeService, OfficeSettings, secret_problem

from . import ipc

DEFAULT_NAME = 'Managed ONLYOFFICE (this server)'


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


def urls_from_status(status):
    conf = (status or {}).get('config') or {}
    return {
        'browser_url': _url(conf.get('browser_url'), scheme='https'),
        'internal_url': _url(conf.get('internal_url'), scheme='http', loopback=True),
        'callback_base_url': _url(conf.get('clientstor_url'), scheme='https'),
    }


def managed_instance():
    service = ManagedOfficeService.get()
    if service.instance_id:
        return service.instance
    return EditorInstance.objects.filter(mode='managed_local').order_by('pk').first()


def configure(status, *, user=None, enable=False):
    """Write the managed EditorInstance; returns (instance, HealthResult)."""
    urls = urls_from_status(status)
    secret = (ipc.call('secret') or {}).get('jwt_secret', '')
    problem = secret_problem(secret)
    if problem:
        raise ProvisionError(f'The helper returned an unusable JWT secret: {problem}')
    with transaction.atomic():
        service = ManagedOfficeService.objects.select_for_update().get_or_create(pk=1)[0]
        instance = managed_instance()
        created = instance is None
        if created:
            name = DEFAULT_NAME
            if EditorInstance.objects.filter(name=name).exists():
                name = f'{DEFAULT_NAME} {timezone.now():%Y%m%d%H%M}'
            instance = EditorInstance(name=name, created_by=user, shared=True)
        changed = []
        for field, value in dict(urls, provider='onlyoffice', mode='managed_local').items():
            if getattr(instance, field) != value:
                setattr(instance, field, value)
                changed.append(field)
        if instance.shared_secret != secret:
            instance.shared_secret = secret
            changed.append('shared_secret (value not logged)')
        if instance.ca_bundle:
            instance.ca_bundle = ''
            changed.append('ca_bundle')
        if changed:
            instance.health_status, instance.health_detail, instance.last_check_at = 'unknown', '', None
        instance.save()
        service.instance = instance
        service.save(update_fields=['instance'])
        settings_obj = OfficeSettings.get()
        policy_changed = []
        if 'onlyoffice' not in (settings_obj.enabled_providers or []):
            settings_obj.enabled_providers = list(settings_obj.enabled_providers or []) + ['onlyoffice']
            policy_changed.append('enabled_providers')
        if settings_obj.default_instance_id is None:
            settings_obj.default_instance = instance
            policy_changed.append('default_instance')
        if policy_changed:
            settings_obj.save()
    audit.log('settings_change', user=user, object_type='office.instance', object_id=instance.pk,
              object_repr=instance.name,
              description=(f'{"Created" if created else "Updated"} the managed ONLYOFFICE instance '
                           f'{instance.name}: {", ".join(changed) or "no changes"}'
                           + (f'; Office policy: {", ".join(policy_changed)}' if policy_changed else '')),
              extra={'changed': changed, 'policy_changed': policy_changed, 'managed': True})
    result = diagnostics.run_health_check(instance, user=user)
    instance.refresh_from_db()
    if enable and result.status == 'ok' and not instance.enabled:
        EditorInstance.objects.filter(pk=instance.pk).update(enabled=True)
        instance.enabled = True
    return instance, result
