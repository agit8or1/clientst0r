"""Serial lifecycle tracking (Phase 13).

Every serial-numbered unit gets a history of SerialEvent rows:

    received               captured while receiving a purchase order
    assigned / unassigned  the serial was set on / removed from an asset
    moved_out / moved_in   the asset moved to another customer (one row each side)
    rma_*                  an RMA for the unit was opened or changed status
    replacement_received   the replacement serial recorded when an RMA is replaced
    returned / retired / disposed / note
                           recorded by a technician from the asset page

Events are written automatically from Asset and RMAReturn saves (signals
below) and from the PO receiving view. Writing an event never blocks the
save that caused it: failures are logged and swallowed.
"""
from __future__ import annotations

import logging
import re

from django.db.models.signals import post_save, pre_save
from django.utils import timezone

logger = logging.getLogger('assets')

_WS = re.compile(r'\s+')


def normalize(serial) -> str:
    """Lookup key: case-insensitive, whitespace-free."""
    return _WS.sub('', str(serial or '')).upper()[:255]


def record(organization, serial, event_type, *, asset=None, rma=None, purchase_order=None,
           receipt_line=None, actor=None, notes='', when=None):
    """Write one event. Returns it, or None when there is no serial."""
    from .models import SerialEvent
    serial = str(serial or '').strip()
    key = normalize(serial)
    if not key or organization is None:
        return None
    return SerialEvent.objects.create(
        organization=organization, serial_number=serial[:255], serial_key=key,
        event_type=event_type, occurred_at=when or timezone.now(),
        asset=asset, asset_name=(asset.name if asset is not None else '')[:255],
        rma=rma, purchase_order=purchase_order, receipt_line=receipt_line,
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        notes=str(notes or ''))


def history_for_asset(asset):
    """Events of this asset's customer for the asset's current serial, plus
    any event that names the asset itself (e.g. an earlier serial)."""
    from django.db.models import Q
    from .models import SerialEvent
    q = Q(asset=asset)
    key = normalize(asset.serial_number)
    if key:
        q |= Q(serial_key=key)
    return (SerialEvent.objects.filter(organization_id=asset.organization_id).filter(q)
            .select_related('actor', 'rma', 'purchase_order', 'asset').order_by('occurred_at', 'id'))


def search(queryset, term):
    """Events whose normalized serial contains the normalized term."""
    key = normalize(term)
    if not key:
        return queryset.none()
    return queryset.filter(serial_key__contains=key)


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def _asset_pre_save(sender, instance, raw=False, **kwargs):
    instance._serial_prev = None
    if raw or not instance.pk:
        return
    instance._serial_prev = (sender._base_manager.filter(pk=instance.pk)
                             .values('serial_number', 'organization_id').first())


def _asset_post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        actor = getattr(instance, '_serial_actor', None) or (instance.created_by if created else None)
        new_key = normalize(instance.serial_number)
        if created:
            if new_key:
                record(instance.organization, instance.serial_number, 'assigned', asset=instance,
                       actor=actor)
            return
        prev = getattr(instance, '_serial_prev', None)
        if not prev:
            return
        old_serial, old_org_id = prev['serial_number'], prev['organization_id']
        if normalize(old_serial) != new_key:
            if normalize(old_serial):
                from core.models import Organization
                old_org = Organization.objects.filter(pk=old_org_id).first()
                record(old_org, old_serial, 'unassigned', asset=instance, actor=actor)
            if new_key:
                record(instance.organization, instance.serial_number, 'assigned', asset=instance,
                       actor=actor)
        elif new_key and old_org_id != instance.organization_id:
            from core.models import Organization
            old_org = Organization.objects.filter(pk=old_org_id).first()
            record(old_org, instance.serial_number, 'moved_out', asset=instance, actor=actor,
                   notes=f'Moved to {instance.organization}')
            record(instance.organization, instance.serial_number, 'moved_in', asset=instance,
                   actor=actor, notes=f'Moved from {old_org}' if old_org else '')
    except Exception:  # noqa: BLE001 - history must never block an asset save
        logger.exception('Serial history for asset %s failed', instance.pk)


def _rma_serial(rma):
    if rma.serial_number:
        return rma.serial_number
    if rma.asset_id and rma.asset and rma.asset.serial_number:
        return rma.asset.serial_number
    return ''


def _rma_pre_save(sender, instance, raw=False, **kwargs):
    instance._serial_prev_status = None
    if raw or not instance.pk:
        return
    instance._serial_prev_status = (sender._base_manager.filter(pk=instance.pk)
                                    .values_list('status', flat=True).first())


def _rma_post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        serial = _rma_serial(instance)
        actor = getattr(instance, '_serial_actor', None)
        asset = instance.asset if instance.asset_id else None
        common = dict(asset=asset, rma=instance, purchase_order=instance.purchase_order, actor=actor)
        label = f'RMA {instance.rma_number}' if instance.rma_number else f'RMA #{instance.pk}'
        if created:
            record(instance.organization, serial, 'rma_opened',
                   notes=f'{label}: {instance.reason}'.strip(': '), **common)
            if instance.status != 'open':
                record(instance.organization, serial, f'rma_{instance.status}', notes=label, **common)
            return
        prev = getattr(instance, '_serial_prev_status', None)
        if prev is None or prev == instance.status:
            return
        record(instance.organization, serial, f'rma_{instance.status}', notes=label, **common)
        if instance.status == 'replaced' and instance.replacement_serial:
            record(instance.organization, instance.replacement_serial, 'replacement_received',
                   rma=instance, purchase_order=instance.purchase_order, actor=actor,
                   notes=f'{label}: replaces {serial}' if serial else label)
    except Exception:  # noqa: BLE001
        logger.exception('Serial history for RMA %s failed', instance.pk)


def connect():
    from .models import Asset, RMAReturn
    pre_save.connect(_asset_pre_save, sender=Asset, dispatch_uid='serial_lifecycle_asset_pre')
    post_save.connect(_asset_post_save, sender=Asset, dispatch_uid='serial_lifecycle_asset_post')
    pre_save.connect(_rma_pre_save, sender=RMAReturn, dispatch_uid='serial_lifecycle_rma_pre')
    post_save.connect(_rma_post_save, sender=RMAReturn, dispatch_uid='serial_lifecycle_rma_post')
