"""Template helpers for the hardware module."""
from django import template
from django.utils.html import format_html

register = template.Library()

ACCURACY = {
    'verified': ('success', 'fa-check-circle', 'Verified layout',
                 'Placement checked against reliable manufacturer documentation.'),
    'approximate': ('warning', 'fa-ruler-combined', 'Approximate layout',
                    'The components are known, but their physical placement is not verified.'),
    'generic': ('secondary', 'fa-shapes', 'Generic layout',
                'A user-configurable representation, not a specific product.'),
}
PROVENANCE = {
    'manufacturer': ('success', 'Manufacturer documentation'),
    'upstream': ('info', 'Community library'),
    'local': ('primary', 'Entered locally'),
    'generic': ('secondary', 'Generic template'),
}


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.simple_tag
def accuracy_badge(state, face=''):
    color, icon, label, help_text = ACCURACY.get(state or 'approximate', ACCURACY['approximate'])
    text_cls = ' text-dark' if color == 'warning' else ''
    suffix = f' · {face}' if face else ''
    return format_html('<span class="badge bg-{}{} hw-acc" title="{}"><i class="fas {}"></i> {}{}</span>',
                       color, text_cls, help_text, icon, label, suffix)


@register.simple_tag
def provenance_badge(state):
    color, label = PROVENANCE.get(state or 'upstream', PROVENANCE['upstream'])
    return format_html('<span class="badge bg-{} bg-opacity-75" title="Where the component list comes from">'
                       '<i class="fas fa-book"></i> Spec: {}</span>', color, label)
