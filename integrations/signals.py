"""RMM connection lifecycle hooks.

* Whether an RMM is connected decides what the navigation, dashboards and
  workspaces show (integrations.presence). Creating or deleting a connection,
  or changing whether it is enabled or who owns it, bumps the access
  generation (accounts.authz_cache.invalidate), which drops both the presence
  answers and the navigation's kept decisions in every worker. Other saves
  (a sync writing its status every few minutes) bump nothing.
* Before a connection is deleted, the alert-to-ticket records that point at
  it get the connection's name and provider written onto them; the foreign
  key is then cleared (SET_NULL), so a ticket's alert history stays readable
  after the integration is gone (docs/ux/STANDALONE_REQUIREMENTS.md D2).
"""
from django.db.models.signals import post_delete, post_init, post_save, pre_delete
from django.dispatch import receiver

from .models import RMMConnection

_WATCHED = ('is_active', 'organization_id')


def _state(instance):
    d = instance.__dict__
    return tuple(d.get(f) for f in _WATCHED)


def _changed():
    from accounts import authz_cache
    from . import presence
    authz_cache.invalidate('rmm connection changed')
    presence.clear()


@receiver(post_init, sender=RMMConnection)
def _rmm_loaded(sender, instance, **kw):
    instance._presence_state = _state(instance)


@receiver(post_save, sender=RMMConnection)
def _rmm_saved(sender, instance, created, raw=False, update_fields=None, **kw):
    if raw:
        return
    now = _state(instance)
    if created or now != getattr(instance, '_presence_state', None):
        _changed()
    instance._presence_state = now


@receiver(pre_delete, sender=RMMConnection)
def _rmm_keep_link_history(sender, instance, **kw):
    from psa.routing.models import AlertTicketLink
    from psa_ai.models import Rem0teAlertTicket
    name = (instance.name or '')[:255]
    provider = (instance.provider_type or '')[:50]
    AlertTicketLink.objects.filter(connection=instance).update(connection_name=name, provider_type=provider)
    Rem0teAlertTicket.objects.filter(connection=instance).update(connection_name=name)


@receiver(post_delete, sender=RMMConnection)
def _rmm_deleted(sender, instance, **kw):
    _changed()
