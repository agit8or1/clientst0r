"""Which artwork a rack, cabinet or board placement shows.

One resolution order serves the asset page, the hardware rack elevation and
the monitoring rack/closet/board layouts, so a placement shows exactly the
drawing a technician sees on the device or asset page, and an artwork update
appears everywhere:

1. the asset is in the hardware inventory → that device's own artwork
   (``hardware:device_art``, tenant-scoped);
2. the placement's equipment model, then the asset's, mapped to the catalog;
3. the asset's recorded manufacturer and model, matched by name.

A generic catalog template is never chosen by matching: its ports are a
template's, not this device's. When nothing matches, callers draw a plain,
clearly generic face with the saved label and nothing else.
"""
from __future__ import annotations

import logging

from django.urls import reverse

logger = logging.getLogger(__name__)

FACES = ('front', 'rear', 'top', 'bottom', 'left', 'right')


def resolve(asset=None, equipment_model=None):
    """``(hardware_device, hardware_model)`` for an asset and/or an equipment model.

    ``hardware_device`` is set only when the asset is in the hardware
    inventory; ``hardware_model`` is then that device's model. Either may be
    None.
    """
    from .matching import match_equipment_model, match_names
    from .models import HardwareDevice
    if asset is not None:
        try:
            hw = asset.hardware
        except HardwareDevice.DoesNotExist:
            hw = None
        if hw is not None:
            return hw, hw.hardware_model
    for em in (equipment_model, getattr(asset, 'equipment_model', None) if asset is not None else None):
        if em is not None:
            hm = match_equipment_model(em)
            if hm is not None:
                return None, hm
    if asset is not None and asset.manufacturer and asset.model:
        return None, match_names(asset.manufacturer, asset.model)
    return None, None


def recorded_model(asset=None, equipment_model=None, manufacturer='', model=''):
    """The model as the records state it, for a placement with no artwork."""
    if equipment_model is not None:
        return f'{equipment_model.vendor.name} {equipment_model.model_name or equipment_model.model_number}'.strip()
    if asset is not None and (asset.manufacturer or asset.model):
        return f'{asset.manufacturer} {asset.model}'.strip()
    return f'{manufacturer} {model}'.strip()


def placement_art(placement):
    """Artwork description for a ``RackDevice`` or ``RackResource``.

    ``source`` is ``device``, ``model`` or ``none``. ``faces`` maps face name
    to the URL of the existing access-controlled artwork route; ``rack_faces``
    lists the faces drawn as rack panels (full 19" width).
    """
    asset = placement.asset if placement.asset_id else None
    em = placement.equipment_model if getattr(placement, 'equipment_model_id', None) else None
    out = {'source': 'none', 'faces': {}, 'rack_faces': [], 'model': '', 'model_url': None, 'device_url': None,
           'asset_url': reverse('assets:asset_detail', args=[asset.pk]) if asset else None}
    try:
        hw, hm = resolve(asset, em)
        if hm is not None and hw is None and hm.is_generic:
            hm = None
        if hm is not None:
            from .layout import get_layout
            layout = get_layout(hm)
            faces = [f for f in FACES if f in layout.faces]
            if hw is not None:
                out['source'] = 'device'
                out['faces'] = {f: reverse('hardware:device_art', args=[hw.pk, f]) for f in faces}
                out['device_url'] = reverse('hardware:device_detail', args=[hw.pk])
            else:
                out['source'] = 'model'
                out['faces'] = {f: reverse('hardware:model_art', args=[hm.pk, f]) for f in faces}
            out['rack_faces'] = [f for f in faces if layout.faces[f].get('rack')]
            out['model'] = f'{hm.manufacturer.name} {hm.model}'
            out['model_url'] = reverse('hardware:model_detail', args=[hm.pk])
    except Exception:  # noqa: BLE001 — artwork must never break a rack page
        logger.exception('Rack artwork lookup failed for %s %s', type(placement).__name__, placement.pk)
        out.update(source='none', faces={}, rack_faces=[], model_url=None, device_url=None)
    if not out['model']:
        out['model'] = recorded_model(asset, em, getattr(placement, 'manufacturer', ''),
                                      getattr(placement, 'model', ''))
    return out
