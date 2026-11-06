"""Small text filters for templates."""
from django import template

register = template.Library()


@register.filter
def underscores_to_spaces(value):
    """`ip_address` -> `ip address`. Django has no built-in replace filter."""
    return str(value).replace('_', ' ')
