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


# ---------------------------------------------------------------------------
# Customer ticket audience: own tickets vs the whole customer organization.
#
# The spec's Customer Standard User sees only their own tickets; a customer
# role that allows it (`portal_tickets_view_org`, with record scope
# "organization": accounts.scope.portal_sees_org_tickets) sees every shared
# ticket of the organization. accounts 0046 switched it on for every role
# and simple role that existed before, so nobody lost the org-wide view; new
# roles start without it (Customer Standard User sees only their own).
# ---------------------------------------------------------------------------

CUSTOMER_ORG_TICKETS_FLAG = 'portal_tickets_view_org'


def membership_flag(membership, flag, default=False):
    """A role flag on one membership; `default` when the role doesn't define it."""
    if membership is None:
        return False
    return bool(getattr(membership.get_permissions(), flag, default))


def own_tickets_q(user, prefix=''):
    """Q for tickets that belong to `user` as a customer: they filed it, or it
    names them as the requester (by e-mail on the ticket or its contact)."""
    from django.db.models import Q
    q = Q(**{f'{prefix}created_by': user})
    email = (getattr(user, 'email', '') or '').strip()
    if email:
        q |= Q(**{f'{prefix}requester_email__iexact': email})
        q |= Q(**{f'{prefix}contact__email__iexact': email})
    return q


def portal_sees_org_tickets(membership):
    from accounts.scope import portal_sees_org_tickets as _rule
    return _rule(membership)


def customer_ticket_q(user, memberships, prefix=''):
    """Q matching the tickets a customer user may see through `memberships`:
    shared with the client, in one of those organizations, and either any
    ticket there (role allows org-wide) or only their own."""
    from django.db.models import Q
    org_wide, own_only = [], []
    for m in memberships:
        (org_wide if portal_sees_org_tickets(m) else own_only).append(m.organization_id)
    q = Q(pk__in=[])
    if org_wide:
        q |= Q(**{f'{prefix}organization_id__in': org_wide})
    if own_only:
        q |= Q(**{f'{prefix}organization_id__in': own_only}) & own_tickets_q(user, prefix)
    return q & Q(**{f'{prefix}client_can_view': True})


def user_can_view_ticket(user, ticket):
    """Whether `user` may see `ticket` right now — the same rule as the
    ticket pages (psa.views._scoped_ticket_qs), for one user and one ticket.
    Used where something is sent to a user later (watcher and @mention
    e-mails), so revoked access or a customer role never receives what the
    pages would hide."""
    if not user or not user.is_active:
        return False
    from accounts.permission_utils import has_perm_for_org
    profile = getattr(user, 'profile', None)
    if user.is_superuser or (profile is not None and profile.is_staff_user()):
        return has_perm_for_org(user, ticket.organization_id, 'tickets_view')
    memberships = [m for m in user.memberships.filter(is_active=True).select_related('role_template')
                   if membership_flag(m, 'tickets_view', True)]
    from psa.models import Ticket
    return Ticket.objects.filter(pk=ticket.pk).filter(customer_ticket_q(user, memberships)).exists()


def user_can_see_comment(user, ticket, comment):
    """`user_can_view_ticket`, and internal notes only for MSP staff."""
    if comment.is_internal and not is_msp_staff(user):
        return False
    return user_can_view_ticket(user, ticket)
