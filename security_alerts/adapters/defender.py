"""
Microsoft Defender for Endpoint — REFERENCE STUB ADAPTER.

Not a working Graph API integration. This module demonstrates the
SecurityProvider plug-in shape: it registers in the provider dropdown,
accepts a connection, and returns an empty alert list. It does NOT call
Microsoft Graph and will NOT surface real Defender alerts. Use it as a
template; do not enable it on a production tenant expecting live alert
flow.

To make it real, implement the two TODOs below: token acquisition + the
Graph ``/security/alerts_v2`` poll with ``lastUpdateDateTime > since``
filtering, returning normalized alert dicts.
"""
from integrations.sdk.registry import register
from .base import SecurityProvider


@register
class DefenderForEndpoint(SecurityProvider):
    slug = 'security_defender'
    # Label shown in the Connections UI provider dropdown — flag the stub
    # status here so operators don't pick it expecting working alerts.
    label = 'Microsoft Defender for Endpoint (reference stub — no live alerts)'
    category = 'security_edr'
    icon = 'fa-shield-virus'
    # A stub: it must never be treated as a working API integration (the
    # connection test, the sync button and the scheduled poller check this).
    supports_polling = False

    def test_connection(self, connection):
        # TODO: actual Microsoft Graph token + GET /alerts. Until then the
        # test must not report success.
        from security_alerts.capabilities import not_implemented_message
        return {'ok': False, 'code': 'not_implemented',
                'message': not_implemented_message('Microsoft Defender for Endpoint')}

    def poll_alerts(self, connection, since=None):
        # TODO: implement Graph API call to /security/alerts_v2 with
        # filter on lastUpdateDateTime > since. Return normalized dicts.
        # For now: return empty list so the framework runs cleanly.
        return []
