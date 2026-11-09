"""Fixtures for tests that need technician access. Not used at runtime."""
from django.contrib.auth.models import User

from .models import AccessAssignment
from .services import builtin


def make_tech(username, superuser=False, **kw):
    from psa.tests._base import _make_msp_tech
    kw.setdefault('email', f'{username}@msp.test')
    maker = User.objects.create_superuser if superuser else User.objects.create_user
    return _make_msp_tech(maker(username, password='pw-' + username, **kw))


def grant(user, organization, key='l2', expires_at=None, group=None):
    """Assign a built-in preset directly — the fixture equivalent of an
    approved protected change."""
    return AccessAssignment.objects.create(preset=builtin(key), organization=organization,
                                           user=None if group else user, group=group, expires_at=expires_at)


def make_ticket(organization, assigned_to=None, subject='Printer offline', **kw):
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    return Ticket.objects.create(organization=organization, subject=subject, assigned_to=assigned_to,
                                 queue=Queue.objects.first(), status=TicketStatus.objects.first(),
                                 priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
                                 **kw)
