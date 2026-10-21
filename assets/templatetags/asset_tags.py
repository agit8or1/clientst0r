"""
Template tags for the assets app.
"""
from django import template
from django.utils.html import format_html

register = template.Library()

# Maps asset_type slug → (fa_icon_class, bootstrap_text_color_class)
ASSET_TYPE_ICONS = {
    'access_control':     ('fa-shield-alt',              'text-danger'),
    'appliance':          ('fa-blender',                 'text-secondary'),
    'av_receiver':        ('fa-volume-up',               'text-secondary'),
    'backup_appliance':   ('fa-database',                'text-warning'),
    'badge_printer':      ('fa-id-card',                 'text-secondary'),
    'biometric_scanner':  ('fa-fingerprint',             'text-danger'),
    'bridge':             ('fa-project-diagram',         'text-info'),
    'card_reader':        ('fa-credit-card',             'text-secondary'),
    'conference_phone':   ('fa-phone-square',            'text-info'),
    'console_server':     ('fa-terminal',                'text-secondary'),
    'copier':             ('fa-copy',                    'text-secondary'),
    'desktop':            ('fa-desktop',                 'text-primary'),
    'digital_signage':    ('fa-tv',                      'text-info'),
    'display':            ('fa-desktop',                 'text-info'),
    'door_controller':    ('fa-door-open',               'text-secondary'),
    'dvr':                ('fa-video',                   'text-secondary'),
    'environmental_monitor': ('fa-thermometer-half',     'text-warning'),
    'fiber_panel':        ('fa-ethernet',                'text-info'),
    'firewall':           ('fa-fire-alt',                'text-danger'),
    'gateway':            ('fa-exchange-alt',            'text-warning'),
    'generator':          ('fa-bolt',                    'text-warning'),
    'handheld':           ('fa-barcode',                 'text-secondary'),
    'hvac':               ('fa-wind',                    'text-info'),
    'iot_device':         ('fa-microchip',               'text-success'),
    'kvm':                ('fa-keyboard',                'text-secondary'),
    'label_printer':      ('fa-tag',                     'text-secondary'),
    'laptop':             ('fa-laptop',                  'text-primary'),
    'lighting_control':   ('fa-lightbulb',               'text-warning'),
    'load_balancer':      ('fa-balance-scale',           'text-info'),
    'mobile':             ('fa-mobile-alt',              'text-primary'),
    'modem':              ('fa-signal',                  'text-warning'),
    'nas':                ('fa-hdd',                     'text-warning'),
    'nvr':                ('fa-video',                   'text-secondary'),
    'other':              ('fa-box',                     'text-muted'),
    'paging_system':      ('fa-bullhorn',                'text-secondary'),
    'patch_panel':        ('fa-ethernet',                'text-secondary'),
    'pbx':                ('fa-phone',                   'text-secondary'),
    'pda':                ('fa-mobile-alt',              'text-secondary'),
    'pdu':                ('fa-plug',                    'text-danger'),
    'phone':              ('fa-phone',                   'text-success'),
    'plotter':            ('fa-drafting-compass',        'text-secondary'),
    'printer':            ('fa-print',                   'text-secondary'),
    'projector':          ('fa-film',                    'text-secondary'),
    'rack':               ('fa-server',                  'text-secondary'),
    'router':             ('fa-code-branch',              'text-success'),
    'san':                ('fa-database',                'text-warning'),
    'scanner':            ('fa-barcode',                 'text-secondary'),
    'security_camera':    ('fa-video',                   'text-danger'),
    'sensor':             ('fa-satellite-dish',          'text-secondary'),
    'server':             ('fa-server',                  'text-danger'),
    'switch':             ('fa-network-wired',           'text-success'),
    'tablet':             ('fa-tablet-alt',              'text-primary'),
    'tape_drive':         ('fa-tape',                    'text-secondary'),
    'terminal':           ('fa-terminal',                'text-secondary'),
    'thermostat':         ('fa-thermometer-three-quarters', 'text-warning'),
    'thin_client':        ('fa-desktop',                 'text-secondary'),
    'ups':                ('fa-battery-three-quarters',  'text-warning'),
    'video_conferencing': ('fa-video',                   'text-info'),
    'voip_gateway':       ('fa-phone-volume',            'text-info'),
    'wireless_ap':        ('fa-broadcast-tower',         'text-success'),
    'wireless_controller':('fa-broadcast-tower',         'text-info'),
    'workstation':        ('fa-desktop',                 'text-primary'),
}

_DEFAULT_ICON = ('fa-box', 'text-muted')


def _icon_for(asset_type):
    """Built-in icon, else the custom asset type's chosen icon (v3.17.621)."""
    if asset_type in ASSET_TYPE_ICONS:
        return ASSET_TYPE_ICONS[asset_type]
    from django.core.cache import cache
    custom = cache.get('asset_custom_type_icons')
    if custom is None:
        from assets.models import AssetType
        custom = dict(AssetType.objects.filter(organization__isnull=True)
                      .values_list('slug', 'icon'))
        cache.set('asset_custom_type_icons', custom, 60)
    if asset_type in custom:
        return (custom[asset_type], 'text-secondary')
    return _DEFAULT_ICON


@register.simple_tag
def asset_type_icon(asset_type, extra_classes=''):
    """
    Render a <i> FontAwesome icon for the given asset_type slug.
    Usage: {% asset_type_icon asset.asset_type %}
    """
    icon, color = _icon_for(asset_type)
    classes = f"fas {icon} {color}"
    if extra_classes:
        classes += f" {extra_classes}"
    return format_html('<i class="{}" title="{}"></i>', classes, (asset_type or '').replace('_', ' ').title())


@register.simple_tag
def asset_type_icon_class(asset_type):
    """
    Return just the icon + color CSS classes (no HTML) for use in JS/inline contexts.
    Usage: {% asset_type_icon_class asset.asset_type %}
    """
    icon, color = _icon_for(asset_type)
    return f"fas {icon} {color}"


@register.filter(name='asset_icon_fa')
def asset_icon_fa(asset_type):
    """
    Template filter — returns just the fa-xxx class name for a given asset type.
    Usage: {{ asset.asset_type|asset_icon_fa }}
    """
    icon, _ = _icon_for(asset_type)
    return icon


@register.filter(name='get_item')
def get_item(dictionary, key):
    """
    Dict lookup by key in templates.
    Usage: {{ my_dict|get_item:key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None
