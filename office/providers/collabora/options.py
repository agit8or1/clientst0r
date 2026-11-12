"""Administrator options for one Collabora instance.

Stored in ``EditorInstance.provider_options`` (JSON, never secrets) and set
with ``manage.py office_collabora --instance <id> ...``:

    require_proof   (default True)  When discovery publishes a proof key,
                                    every WOPI request must carry a valid
                                    X-WOPI-Proof signature. Has no effect
                                    while no key is published (diagnostics
                                    warn about that).
    disable_print   (default False) CheckFileInfo DisablePrint / HidePrintOption.
    hide_export     (default False) CheckFileInfo HideExportOption / DisableExport.
    discovery_ttl_s (default 3600)  How long parsed discovery stays cached.
"""
from __future__ import annotations

DEFAULTS = {
    'require_proof': True,
    'disable_print': False,
    'hide_export': False,
    'discovery_ttl_s': 3600,
}
BOOLEAN = ('require_proof', 'disable_print', 'hide_export')


def get(instance) -> dict:
    out = dict(DEFAULTS)
    raw = getattr(instance, 'provider_options', None) or {}
    for key in BOOLEAN:
        if key in raw:
            out[key] = bool(raw[key])
    try:
        ttl = int(raw.get('discovery_ttl_s', DEFAULTS['discovery_ttl_s']))
    except (TypeError, ValueError):
        ttl = DEFAULTS['discovery_ttl_s']
    out['discovery_ttl_s'] = min(max(ttl, 60), 86400)
    return out


def set_options(instance, **changes) -> dict:
    current = dict(getattr(instance, 'provider_options', None) or {})
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise ValueError(f'unknown Collabora option {key!r}')
        current[key] = bool(value) if key in BOOLEAN else int(value)
    instance.provider_options = current
    instance.save(update_fields=['provider_options', 'updated_at'])
    return get(instance)
