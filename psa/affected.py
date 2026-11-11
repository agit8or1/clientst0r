"""
The devices a ticket is about (ClientSt0r ↔ RMM Phase 4).

    ticket_assets(ticket)  primary asset first (`Ticket.related_asset`), then
                           the extra affected devices, in the order added.
                           Only assets of the ticket's own customer, ever:
                           a foreign asset is skipped, not shown.
    add / remove           technician changes, audited, with a system note.

Everything that reaches a device from a ticket (psa_ai.services.rmm_actions
.targets) starts from this list, so a device is reachable from a ticket only
when a technician put it there and it belongs to the same customer.
"""
from __future__ import annotations

from typing import List

MAX_AFFECTED = 25


def ticket_assets(ticket) -> List:
    from .models import TicketAffectedAsset
    out, seen = [], set()
    primary = ticket.related_asset
    if primary is not None and primary.organization_id == ticket.organization_id:
        out.append(primary)
        seen.add(primary.pk)
    links = (TicketAffectedAsset.objects.filter(ticket=ticket, organization_id=ticket.organization_id,
                                                asset__organization_id=ticket.organization_id)
             .select_related('asset').order_by('added_at', 'pk'))
    for link in links:
        if link.asset_id not in seen:
            out.append(link.asset)
            seen.add(link.asset_id)
    return out


def is_affected(ticket, asset) -> bool:
    return asset is not None and any(a.pk == asset.pk for a in ticket_assets(ticket))


def tickets_for_asset(asset):
    """Tickets whose primary or affected devices include this asset, same customer only."""
    from django.db.models import Q
    from .models import Ticket
    return (Ticket.objects.filter(organization_id=asset.organization_id)
            .filter(Q(related_asset=asset) | Q(affected_asset_links__asset=asset))
            .distinct())


class AffectedRefused(Exception):
    pass


def _audit(user, ticket, description, asset, request=None):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='update', organization=ticket.organization, object_type='psa.Ticket',
                 object_id=ticket.pk, object_repr=ticket.ticket_number, description=description[:1000],
                 path=getattr(request, 'path', '') or '', extra_data={'affected_asset': asset.pk})


def add(ticket, asset_id, user, request=None):
    from django.db import IntegrityError, transaction
    from assets.models import Asset
    from .models import TicketAffectedAsset, TicketComment
    try:
        asset = Asset.objects.get(pk=int(asset_id), organization_id=ticket.organization_id)
    except (Asset.DoesNotExist, TypeError, ValueError):
        raise AffectedRefused('That device belongs to a different customer, or no longer exists.')
    if is_affected(ticket, asset):
        return asset, False
    if TicketAffectedAsset.objects.filter(ticket=ticket).count() >= MAX_AFFECTED:
        raise AffectedRefused(f'A ticket can list at most {MAX_AFFECTED} affected devices.')
    try:
        with transaction.atomic():
            TicketAffectedAsset.objects.create(ticket=ticket, asset=asset, added_by=user)
    except IntegrityError:
        return asset, False
    TicketComment.objects.create(ticket=ticket, author=user, body=f'Affected device added: {asset.name}.',
                                 is_internal=True, is_system=True)
    _audit(user, ticket, f'Affected device {asset.name} added to {ticket.ticket_number}', asset, request)
    return asset, True


def remove(ticket, asset_id, user, request=None):
    from .models import TicketAffectedAsset, TicketComment
    link = (TicketAffectedAsset.objects.filter(ticket=ticket, asset_id=asset_id if str(asset_id).isdigit() else -1)
            .select_related('asset').first())
    if link is None:
        raise AffectedRefused('That device is not listed on this ticket (the primary asset is changed with Set).')
    asset = link.asset
    link.delete()
    TicketComment.objects.create(ticket=ticket, author=user, body=f'Affected device removed: {asset.name}.',
                                 is_internal=True, is_system=True)
    _audit(user, ticket, f'Affected device {asset.name} removed from {ticket.ticket_number}', asset, request)
    return asset
