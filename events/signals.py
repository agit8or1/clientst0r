"""Queue source rows when they are saved. Bulk ``.update()`` calls bypass
these; the scheduler's backstop scan and recheck pass cover them."""
from django.apps import apps
from django.db.models.signals import m2m_changed, post_save

from . import models as M
from .queue import enqueue

_SENDERS = (
    ('security_alerts', 'SecurityAlert', M.SOURCE_SECURITY),
    ('integrations', 'RMMAlert', M.SOURCE_RMM),
    ('psa_ai', 'Rem0teAlertTicket', M.SOURCE_REM0TE),
    ('backup_monitoring', 'BackupAlert', M.SOURCE_BACKUP),
    ('monitoring', 'WebsiteMonitor', M.SOURCE_MONITOR),
    ('connect', 'ConnectIncident', M.SOURCE_CONNECT),
)


def _connect():
    for app_label, model_name, source in _SENDERS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue

        def handler(sender, instance, raw=False, _source=source, **kwargs):
            if raw:
                return
            if _source == M.SOURCE_MONITOR:
                fields = kwargs.get('update_fields')
                # Only the declared up/down state matters for monitors; a
                # check that changes nothing else is not queued.
                if fields is not None and 'alert_state' not in fields:
                    return
            enqueue(_source, instance.pk)

        post_save.connect(handler, sender=model, weak=False, dispatch_uid=f'events-{source}')
    try:
        incident = apps.get_model('security_alerts', 'SecurityIncident')
    except LookupError:
        return

    def incident_alerts(sender, instance, action, pk_set=None, reverse=False, **kwargs):
        if action not in ('post_add', 'post_remove', 'pre_clear'):
            return
        if reverse:      # instance is the alert
            enqueue(M.SOURCE_SECURITY, instance.pk)
        elif action == 'pre_clear':
            for pk in instance.alerts.values_list('pk', flat=True):
                enqueue(M.SOURCE_SECURITY, pk)
        else:
            for pk in pk_set or ():
                enqueue(M.SOURCE_SECURITY, pk)

    m2m_changed.connect(incident_alerts, sender=incident.alerts.through, weak=False,
                        dispatch_uid='events-incident-alerts')


_connect()
