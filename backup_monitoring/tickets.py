"""Backup alert -> PSA ticket. One ticket per alert, ever: `alert.ticket` is
the dedup (the alert itself is already unique per connection + dedup_key
while live)."""
from django.db import transaction

SEVERITY_PRIORITY = {'critical': 'P2', 'warning': 'P3'}


class TicketSetupError(Exception):
    """The PSA has no queue / status / priority / type to file a ticket under."""


def create_ticket_for_alert(alert, user=None):
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    with transaction.atomic():
        from .models import BackupAlert
        locked = BackupAlert.objects.select_for_update().get(pk=alert.pk)
        if locked.ticket_id:
            alert.ticket = locked.ticket
            return locked.ticket, False
        priority = (TicketPriority.objects.filter(code=SEVERITY_PRIORITY.get(alert.severity, 'P3')).first()
                    or TicketPriority.objects.first())
        queue = Queue.objects.filter(is_active=True).first()
        status = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first()
        ticket_type = TicketType.objects.first()
        if not (priority and queue and status and ticket_type):
            raise TicketSetupError('The service desk has no queue, status, priority or ticket type configured.')
        ticket = Ticket.objects.create(
            organization=alert.organization,
            subject=f'[Backup] {alert.title[:200]}',
            description=f'{alert.detail}\n\nConnection: {alert.connection.name} '
                        f'({alert.connection.get_provider_display()})',
            queue=queue, priority=priority,
            status=status,
            ticket_type=ticket_type, source='monitoring', created_by=user)
        locked.ticket = ticket
        locked.save(update_fields=['ticket'])
    alert.ticket = ticket
    return ticket, True
