"""What Clientst0r can really do for each security vendor.

Every vendor connection receives alerts through its signed webhook, posted in
Clientst0r's alert format (``external_id``, ``title``, ``severity``,
``description``, ``asset_hint``). Polling the vendor's own API needs an adapter
that is actually implemented; an adapter that is only a reference stub
(``supports_polling = False``) does not count. Pages, the connection test, the
sync button and the scheduled poller all ask here, so none of them claims more
than exists.
"""
from integrations.sdk.registry import get as _get

WEBHOOK_FIELDS = 'external_id, title, severity, description, asset_hint'


def api_adapter(provider):
    """The adapter that polls ``provider``'s API, or None."""
    adapter = _get(f'security_{provider}') or _get(provider)
    if adapter is None or not getattr(adapter, 'supports_polling', True):
        return None
    return adapter


def polls_api(provider):
    return api_adapter(provider) is not None


def not_implemented_message(label):
    return (f'Clientst0r has no API integration for {label} yet, so there is nothing to test or poll. '
            f'Alerts arrive only through this connection\'s webhook, as JSON with {WEBHOOK_FIELDS}.')
