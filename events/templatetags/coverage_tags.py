"""Template helpers for monitoring coverage (roadmap 82.15–82.20)."""
from django import template

from events import coverage

register = template.Library()


@register.filter
def delay(seconds):
    """Delivery delay as text: '45 s', '12 min', '3 h 5 min', '2 d 4 h'."""
    return coverage.format_delay(seconds)


@register.simple_tag
def coverage_badge(key, recovered=None):
    return coverage.coverage_display(key, recovered=recovered)
