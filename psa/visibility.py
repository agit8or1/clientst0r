"""
What a customer user may see of a ticket, wherever they see it.

MSP staff see everything. Customer users (people who log in for one of the
MSP's customers) get the same rule as the portal: only tickets shared with the
client (`client_can_view`), no internal comments, and no internal attachments
or attachments on internal comments.
"""


def is_msp_staff(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile is not None and profile.is_staff_user())


def msp_staff_q(prefix=''):
    """Q matching MSP technicians on a User queryset (or via `prefix`, e.g.
    'assigned_to__'). Same rule as `is_msp_staff`."""
    from django.db.models import Q
    return (Q(**{f'{prefix}is_superuser': True}) | Q(**{f'{prefix}is_staff': True})
            | Q(**{f'{prefix}profile__user_type': 'staff'}))


def msp_technicians():
    """Active MSP technicians: the people tickets and dispatch work go to."""
    from django.contrib.auth.models import User
    return (User.objects.filter(is_active=True).filter(msp_staff_q())
            .distinct().order_by('username'))


def customer_visible_tickets(qs, user):
    """Narrow a Ticket queryset to what this user may see."""
    if is_msp_staff(user):
        return qs
    return qs.filter(client_can_view=True)


def visible_comments(ticket, user):
    qs = ticket.comments.all()
    if is_msp_staff(user):
        return qs
    return qs.filter(is_internal=False)


def visible_attachments(ticket, user):
    qs = ticket.attachments.all()
    if is_msp_staff(user):
        return qs
    return qs.filter(is_internal=False).exclude(comment__is_internal=True)
