"""
Match the procurement equipment catalog (``assets.EquipmentModel``) to the
hardware catalog, so its pages can show generated artwork.

Matching is exact on normalized text — vendor name (with common aliases) plus
model name or part number, case and punctuation ignored. No fuzzy matching:
a wrong picture is worse than none. Where nothing matches, callers get a
clearly labelled generic template for the equipment type instead.
"""
from __future__ import annotations

import re

from django.core.cache import cache

from .models import HardwareModel

VENDOR_ALIASES = {
    'hp': 'hpe', 'hphpe': 'hpe', 'hparuba': 'hpe', 'aruba': 'hpe', 'arubanetworks': 'hpe',
    'hewlettpackardenterprise': 'hpe', 'hewlettpackard': 'hpe',
    'junipernetworks': 'juniper', 'ciscomeraki': 'cisco', 'meraki': 'cisco', 'paloaltonetworks': 'paloalto',
    'aristanetworks': 'arista', 'dellemc': 'dell', 'delltechnologies': 'dell', 'force10': 'dell',
    'extreme': 'extremenetworks', 'ubiquitinetworks': 'ubiquiti', 'poly': 'polycom', 'plantronics': 'polycom',
    'tplink': 'tplink', 'apcbyschneiderelectric': 'apc', 'schneiderelectric': 'apc',
}

GENERIC_FOR_TYPE = {
    'switch': 'local-generic-48-port-switch-4-sfp-1u', 'router': 'local-generic-firewall-router-1u-8-rj45',
    'firewall': 'local-generic-firewall-router-1u-8-rj45', 'access_point': 'local-generic-access-point-1-poe-uplink',
    'server': 'local-generic-1u-server', 'storage': 'local-generic-2u-server', 'ups': 'local-generic-ups-2u-8-c13',
    'pdu': 'local-generic-pdu-1u-8-c13', 'patch_panel': 'generic-48-port-copper-patch-panel',
    'workstation': 'local-generic-workstation-1-rj45-nic', 'laptop': 'local-generic-laptop-docking-station',
}


def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def vendor_key(name: str) -> str:
    k = norm(name)
    return VENDOR_ALIASES.get(k, k)


def _forms(text):
    """[(normalized form, dropped brand word or None)] for a model string.

    "Meraki MS390-48UX2-HW" gives ("meraki ms390…hw", None), ("ms39048ux2hw", "meraki")
    and the same without Meraki's "-HW" SKU suffix.
    """
    out = []
    words = (text or '').split()
    pairs = [(text or '', None)]
    if len(words) > 1 and not any(ch.isdigit() for ch in words[0]):
        pairs.append((' '.join(words[1:]), norm(words[0])))
    for f, dropped in pairs:
        n = norm(f)
        if len(n) >= 4 and any(ch.isdigit() for ch in n):
            out.append((n, dropped))
            if n.endswith('hw') and len(n) > 6:
                out.append((n[:-2], dropped))
    return out


def _index():
    """{vendor_key: {'full': {form: {pk}}, 'stripped': {form: {dropped word: {pk}}}}} — cached."""
    stamp = HardwareModel.objects.filter(kind=HardwareModel.KIND_DEVICE).order_by('-updated_at').values_list(
        'updated_at', flat=True).first()
    key = f'hw-match-index-v2-{stamp.timestamp() if stamp else 0}'
    idx = cache.get(key)
    if idx is not None:
        return idx
    idx = {}
    for pk, mfr, model, part in HardwareModel.objects.filter(kind=HardwareModel.KIND_DEVICE, is_active=True) \
            .values_list('pk', 'manufacturer__name', 'model', 'part_number'):
        bucket = idx.setdefault(vendor_key(mfr), {'full': {}, 'stripped': {}})
        for text in (model, part):
            for form, dropped in _forms(text):
                if dropped is None:
                    bucket['full'].setdefault(form, set()).add(pk)
                else:
                    bucket['stripped'].setdefault(form, {}).setdefault(dropped, set()).add(pk)
    cache.set(key, idx, 3600)
    return idx


def _letters(s):
    return sum(ch.isalpha() for ch in s)


def match_names(vendor_name, *texts):
    """Unique exact match for a vendor + any of `texts` (part number first, then model name).

    A form with a brand word dropped only matches when the same word was
    dropped on both sides ("FortiGate 2000E" never matches "FortiWeb 2000E"),
    or when the query is a bare SKU with at least two letters ("MS390-48UX2").
    """
    bucket = _index().get(vendor_key(vendor_name), {})
    if not bucket:
        return None
    vtok = norm(vendor_name)
    for text in texts:
        for form, dropped in _forms(text):
            cands = set(bucket['full'].get(form, ()))
            by_word = bucket['stripped'].get(form, {})
            if dropped is None:
                if _letters(form) >= 2:
                    for pks in by_word.values():
                        cands |= pks
            else:
                cands |= by_word.get(dropped, set())
                if dropped == vtok or dropped in VENDOR_ALIASES:
                    cands |= set(bucket['full'].get(form, ()))
            if len(cands) == 1:
                return HardwareModel.objects.select_related('manufacturer').get(pk=cands.pop())
    return None


def match_equipment_model(em):
    """The hardware model for an EquipmentModel, or None when no unique exact match exists."""
    try:
        linked = em.hardware_model
    except HardwareModel.DoesNotExist:
        linked = None
    if linked is not None:
        return linked
    return match_names(em.vendor.name, em.model_number, em.model_name)


def generic_for_type(equipment_type):
    slug = GENERIC_FOR_TYPE.get(equipment_type)
    if not slug:
        return None
    return HardwareModel.objects.filter(slug=slug, is_generic=True).select_related('manufacturer').first()


def artwork_context(hm, generic=False):
    """Faces + cached SVG + accuracy for templates. Never raises into the caller's page."""
    from .layout import get_layout
    from .renderer import cached_face_svg
    try:
        layout = get_layout(hm)
        faces = [f for f in ('front', 'rear', 'top', 'bottom') if f in layout.faces]
        return {'hm': hm, 'generic': generic, 'layout': layout,
                'faces': [{'name': f, 'svg': cached_face_svg(hm, layout, f), 'accuracy': layout.face_accuracy(f)}
                          for f in faces]}
    except Exception:  # noqa: BLE001 — artwork is decoration on these pages
        import logging
        logging.getLogger(__name__).exception('Artwork for %s failed', hm)
        return None
