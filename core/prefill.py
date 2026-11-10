"""
Initial values for create forms from GET params (v3.17.656).

Readiness "Create it" links put `?title=…&category=…&tags=…` on create URLs.
These helpers turn them into form `initial` values only — nothing is saved —
and resolve names to rows of the given organization only, so a link can
never pre-select another customer's category or tags.
"""
from django.db.models import Q

MAX_PARAM_LENGTH = 255
MAX_TAGS = 10


def text_param(request, key, max_length=MAX_PARAM_LENGTH):
    """GET[key] stripped of control characters, trimmed and length-limited.
    Form widgets escape it on output."""
    value = request.GET.get(key)
    if not isinstance(value, str):
        return ''
    value = ''.join(ch for ch in value[:max_length * 2] if ch.isprintable()).strip()
    return value[:max_length]


def _names(raw):
    return list(dict.fromkeys(
        n.strip() for n in (raw or '').split(',') if n.strip()))[:MAX_TAGS]


def match_name_or_slug(queryset, raw):
    """Rows of `queryset` whose name or slug equals one of the comma-separated
    values in `raw` (case-insensitive)."""
    names = _names(raw)
    if not names:
        return queryset.none()
    q = Q()
    for n in names:
        q |= Q(name__iexact=n) | Q(slug__iexact=n)
    return queryset.filter(q)


def org_tags(request, org, key='tags'):
    """Tags of `org` named in GET[key]; [] when none match or no org."""
    if org is None:
        return []
    from core.models import Tag
    return list(match_name_or_slug(Tag.objects.filter(organization=org),
                                   text_param(request, key, 1000)))
