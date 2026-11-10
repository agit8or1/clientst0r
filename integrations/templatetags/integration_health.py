"""`{% sync_health connection %}` — the standard sync-health card.

    {% load integration_health %}
    {% sync_health connection %}            {# full card #}
    {% sync_health connection compact=True %}  {# one-line summary for lists #}

Accepts a connection, or a precomputed `health_for()` dict as `health=`.
"""
from django import template

from integrations.health import health_for

register = template.Library()


@register.inclusion_tag('integrations/_sync_health.html')
def sync_health(connection=None, compact=False, health=None):
    if health is None:
        health = health_for(connection) if connection is not None else None
    return {'health': health, 'compact': compact, 'connection': connection}


@register.filter
def redacted(text, connection=None):
    """`{{ connection.last_error|redacted:connection }}` — credentials → ***."""
    from integrations.health import redact, redact_for
    if connection is not None:
        return redact_for(connection, text)
    return redact(text)
