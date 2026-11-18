"""Which requests the policy covers, and how they are grouped.

Every inbound API and webhook route is listed here. A request whose path
matches none of these is web traffic and is left to the site firewall.
Longer prefixes are listed first; the first match wins.
"""
from .models import SURFACE_API, SURFACE_WEBHOOK

# key -> (label, surface)
ENDPOINT_GROUPS = {
    'rest_api': ('REST API (/api/)', SURFACE_API),
    'graphql': ('GraphQL API', SURFACE_API),
    'mobile_api': ('Mobile app API', SURFACE_API),
    'integration_api': ('Rem0te integration API', SURFACE_API),
    'connect_api': ('Agit8or Connect API', SURFACE_API),
    'security_webhook': ('Security vendor webhooks', SURFACE_WEBHOOK),
    'siem_webhook': ('SIEM webhooks', SURFACE_WEBHOOK),
    'distributor_webhook': ('Distributor webhooks', SURFACE_WEBHOOK),
    'payment_webhook': ('Payment provider webhooks', SURFACE_WEBHOOK),
    'partner_webhook': ('Ticket partner webhooks', SURFACE_WEBHOOK),
    'emergency_restart': ('Emergency restart webhook', SURFACE_WEBHOOK),
}

INTEGRATIONS = {
    'rem0te': 'Rem0te',
    'agit8or_connect': 'Agit8or Connect',
    'security_vendor': 'Security vendor connections',
    'siem': 'SIEM endpoints',
    'distributor': 'Distributors',
    'stripe': 'Stripe',
    'gocardless': 'GoCardless',
    'ticket_partner': 'Ticket partners',
}

# (path prefix, endpoint group, integration)
_ROUTES = (
    ('/security/siem/webhook/', 'siem_webhook', 'siem'),
    ('/security/webhook/', 'security_webhook', 'security_vendor'),
    ('/integrations/distributors/webhooks/', 'distributor_webhook', 'distributor'),
    ('/payments/webhooks/stripe/', 'payment_webhook', 'stripe'),
    ('/payments/webhooks/gocardless/', 'payment_webhook', 'gocardless'),
    ('/psa/partners/webhook/', 'partner_webhook', 'ticket_partner'),
    ('/core/emergency-restart/', 'emergency_restart', ''),
    ('/api/integration/v1/', 'integration_api', 'rem0te'),
    ('/api/mobile/v1/', 'mobile_api', ''),
    ('/api/v2/graphql/', 'graphql', ''),
    ('/api/', 'rest_api', ''),
    ('/connect/v1/', 'connect_api', 'agit8or_connect'),
    ('/.well-known/agit8or-connect', 'connect_api', 'agit8or_connect'),
)


class Route:
    __slots__ = ('group', 'integration', 'surface')

    def __init__(self, group, integration):
        self.group = group
        self.integration = integration
        self.surface = ENDPOINT_GROUPS[group][1]

    def __repr__(self):
        return f'Route({self.group!r}, {self.integration!r})'


def classify(path):
    """The Route for an API or webhook path, or None for web pages."""
    path = path or ''
    for prefix, group, integration in _ROUTES:
        if path.startswith(prefix):
            return Route(group, integration)
    return None
