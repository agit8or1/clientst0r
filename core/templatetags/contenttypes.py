"""
Custom template tags for ContentType functionality
"""
from django import template
from django.contrib.contenttypes.models import ContentType

register = template.Library()


@register.simple_tag
def get_content_type(obj):
    """
    Returns the ContentType for a given object.
    Usage: {% get_content_type object as content_type %}
    """
    return ContentType.objects.get_for_model(obj)
