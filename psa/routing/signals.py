"""Ticket save hooks for routing.

Kept separate from psa/signals.py. Every handler is wrapped: routing problems
are logged and never stop a ticket from saving. With routing Off for the
ticket's customer the handlers do nothing beyond reading the mode.
"""
import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from psa.models import Ticket

logger = logging.getLogger('psa.routing')

_PRIOR = {}


@receiver(pre_save, sender=Ticket, dispatch_uid='ticket_routing_capture_prior')
def _capture_prior(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        row = (Ticket.objects.filter(pk=instance.pk)
               .values_list('status__is_terminal', 'assigned_to_id').first())
        if row is not None:
            _PRIOR[instance.pk] = row
    except Exception:  # noqa: BLE001
        logger.exception('routing prior-state capture failed')


@receiver(post_save, sender=Ticket, dispatch_uid='ticket_routing_after_save')
def _after_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    prior = _PRIOR.pop(instance.pk, None)
    try:
        from . import service
        from .engine import effective_mode
        from .models import MODE_OFF
        if created:
            service.on_ticket_created(instance)
            return
        if prior is None or service.is_applying():
            return
        was_terminal, prev_assignee = prior
        if effective_mode(instance.organization)[0] == MODE_OFF:
            return
        if prev_assignee != instance.assigned_to_id:
            # Attribute the change only when this save wrote updated_by;
            # otherwise the value is whoever edited the ticket last.
            fields = kwargs.get('update_fields')
            actor = (getattr(instance, 'updated_by', None)
                     if fields is None or 'updated_by' in fields else None)
            service.record_manual_override(instance, prev_assignee, actor=actor)
        if was_terminal and instance.status_id and not instance.status.is_terminal:
            service.on_reopened(instance)
    except Exception:  # noqa: BLE001
        logger.exception('ticket routing hook failed for ticket %s', instance.pk)
