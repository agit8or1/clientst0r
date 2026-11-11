"""Alert policy signals.

  alert_recovered      → confirm the outcome of a support workflow.
  alert_ticket_opened  → a Rem0te alert that got its ticket after intake is
                         recorded on its Rem0te alert row and linked back
                         (integrations/rem0te/alerts.py). Routing itself
                         never calls an RMM.
"""
import logging

from django.dispatch import receiver

from psa.routing.alert_policy import alert_recovered, alert_ticket_opened

logger = logging.getLogger('psa.support_workflows')


@receiver(alert_recovered, dispatch_uid='support_workflows_alert_recovered')
def _on_recovered(sender, link=None, ticket=None, **kwargs):
    try:
        from .engine import on_alert_recovered
        on_alert_recovered(link, ticket)
    except Exception:  # noqa: BLE001 — never break alert intake
        logger.exception('support workflow verification failed for alert link %s', getattr(link, 'pk', None))


@receiver(alert_ticket_opened, dispatch_uid='support_workflows_alert_ticket_opened')
def _on_ticket_opened(sender, link=None, ticket=None, **kwargs):
    if link is None or link.source != 'rem0te':
        return
    from integrations.rem0te.alerts import bind_policy_ticket
    bind_policy_ticket(link)
