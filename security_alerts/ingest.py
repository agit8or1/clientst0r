"""Storing alerts from vendor webhooks, adapter polls and SIEM endpoints.

SR-09: a later delivery with the same external id updates the alert but
never lowers its severity; the attempt is recorded in the audit log, and
the alert's status is left alone.
"""
from django.db import IntegrityError, transaction

SEVERITY_RANK = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}


def upsert_alert(lookup, values):
    """(alert, created). ``lookup`` names the source and external id."""
    from .models import SecurityAlert
    alert = SecurityAlert.objects.filter(**lookup).first()
    if alert is None:
        try:
            with transaction.atomic():
                return SecurityAlert.objects.create(**lookup, **values), True
        except IntegrityError:
            alert = SecurityAlert.objects.filter(**lookup).first()
            if alert is None:
                raise
    values = dict(values)
    new_sev = values.get('severity')
    if SEVERITY_RANK.get(new_sev, 2) < SEVERITY_RANK.get(alert.severity, 2):
        values.pop('severity')
        _record_downgrade(alert, new_sev)
    changed = [k for k, v in values.items() if getattr(alert, k) != v]
    for k in changed:
        setattr(alert, k, values[k])
    if changed:
        alert.save(update_fields=changed)
    return alert, False


def _record_downgrade(alert, refused):
    from audit.models import AuditLog
    AuditLog.log(
        user=None, action='update', organization=alert.organization,
        object_type='security_alerts.SecurityAlert', object_id=alert.pk,
        object_repr=alert.title[:200],
        description=(f'A later delivery of alert {alert.external_id} said severity "{refused}"; '
                     f'kept "{alert.severity}" (severity is never lowered by a re-delivery)'),
        extra_data={'event': 'security_alert_severity_downgrade_refused', 'kept': alert.severity,
                    'refused': refused},
    )
