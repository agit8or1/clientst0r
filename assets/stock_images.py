"""Stock drawings for assets with no photo or artwork (v3.17.657).

Line-art SVGs in static/images/asset-stock/<key>.svg, drawn with
``currentColor``. Pages show them as a CSS mask filled with the text colour,
so they follow the light / dark theme. Display only: nothing is stored on
the asset, so a later photo or artwork simply takes over.
"""
from django.templatetags.static import static

STOCK_KEYS = ('server', 'desktop', 'laptop', 'switch', 'router', 'firewall', 'access-point', 'printer',
              'phone', 'storage', 'ups', 'monitor', 'mobile', 'vm', 'device')

# Built-in asset types (Asset.ASSET_TYPES) -> drawing.
TYPE_MAP = {
    'server': 'server', 'appliance': 'server',
    'workstation': 'desktop', 'desktop': 'desktop', 'thin_client': 'desktop', 'terminal': 'desktop',
    'laptop': 'laptop',
    'switch': 'switch', 'patch_panel': 'switch', 'fiber_panel': 'switch', 'kvm': 'switch',
    'console_server': 'switch',
    'router': 'router', 'gateway': 'router', 'modem': 'router', 'load_balancer': 'router',
    'bridge': 'router', 'voip_gateway': 'router',
    'firewall': 'firewall',
    'wireless_ap': 'access-point', 'wireless_controller': 'access-point',
    'printer': 'printer', 'copier': 'printer', 'label_printer': 'printer', 'badge_printer': 'printer',
    'plotter': 'printer', 'scanner': 'printer',
    'phone': 'phone', 'conference_phone': 'phone', 'pbx': 'phone', 'paging_system': 'phone',
    'nas': 'storage', 'san': 'storage', 'backup_appliance': 'storage', 'tape_drive': 'storage',
    'dvr': 'storage', 'nvr': 'storage',
    'ups': 'ups', 'pdu': 'ups', 'generator': 'ups',
    'display': 'monitor', 'digital_signage': 'monitor', 'projector': 'monitor',
    'video_conferencing': 'monitor',
    'tablet': 'mobile', 'mobile': 'mobile', 'handheld': 'mobile', 'pda': 'mobile',
}

# Custom asset types (and anything else) are matched on words in their key.
_HINTS = (
    ('virtual', 'vm'), ('vm', 'vm'), ('server', 'server'), ('laptop', 'laptop'), ('notebook', 'laptop'),
    ('desktop', 'desktop'), ('workstation', 'desktop'), ('pc', 'desktop'), ('switch', 'switch'),
    ('router', 'router'), ('firewall', 'firewall'), ('wifi', 'access-point'), ('wireless', 'access-point'),
    ('access_point', 'access-point'), ('printer', 'printer'), ('phone', 'phone'), ('storage', 'storage'),
    ('nas', 'storage'), ('ups', 'ups'), ('power', 'ups'), ('monitor', 'monitor'), ('display', 'monitor'),
    ('screen', 'monitor'), ('tablet', 'mobile'), ('mobile', 'mobile'),
)


def stock_key(asset_type):
    key = (asset_type or '').strip().lower()
    if key in TYPE_MAP:
        return TYPE_MAP[key]
    words = key.replace('-', '_').split('_')
    for hint, stock in _HINTS:
        if hint in words or (len(hint) > 3 and hint in key):
            return stock
    return 'device'


def stock_url(asset_type):
    return static(f'images/asset-stock/{stock_key(asset_type)}.svg')
