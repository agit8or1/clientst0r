"""Alert recovery → confirm the outcome of a support workflow."""
import logging

from django.dispatch import receiver

from psa.routing.alert_policy import alert_recovered

logger = logging.getLogger('psa.support_workflows')


@receiver(alert_recovered, dispatch_uid='support_workflows_alert_recovered')
def _on_recovered(sender, link=None, ticket=None, **kwargs):
    try:
        from .engine import on_alert_recovered
        on_alert_recovered(link, ticket)
    except Exception:  # noqa: BLE001 — never break alert intake
        logger.exception('support workflow verification failed for alert link %s', getattr(link, 'pk', None))
