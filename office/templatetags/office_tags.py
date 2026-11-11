"""Office buttons for pages that list or show files.

    {% load office_tags %}
    {% office_file_actions document %}            toolbar (document page, file page)
    {% office_attachment_menu attachment %}       compact dropdown for one attachment row
    {% office_new_menu %}                         New → Word / Excel / PowerPoint (documents list)
    {% office_new_attachment_menu 'asset' asset.pk %}
    {{ name|is_office_file }}

Buttons are only rendered as enabled when they will work: Edit needs a
configured, healthy instance with an installed connector that supports the
format, plus edit permission. Otherwise Edit is shown disabled with the
reason. Export PDF and Convert only appear when the provider advertises them.
"""
from django import template

from office import creation, formats, policy, targets

register = template.Library()


@register.filter
def is_office_file(name):
    return formats.is_office(str(name or ''))


def _ctx(context, obj, compact):
    request = context.get('request')
    user = getattr(request, 'user', None)
    try:
        target = targets.target_for(obj)
    except TypeError:
        return {'show': False}
    if user is None or not formats.is_office(target.filename) or not target.can_view(user):
        return {'show': False}
    if target.kind == 'document' and (obj.content_type != 'file' or obj.organization_id is None):
        return {'show': False}
    av = policy.availability(user, target)
    return {
        'show': True, 'target': target, 'av': av, 'compact': compact,
        'can_copy': creation.can_copy(target, user), 'can_edit_file': target.can_edit(user),
        'request': request, 'csrf_token': context.get('csrf_token'),
        'next': request.get_full_path() if request else '',
    }


@register.inclusion_tag('office/_file_actions.html', takes_context=True)
def office_file_actions(context, obj):
    return _ctx(context, obj, compact=False)


@register.inclusion_tag('office/_file_actions.html', takes_context=True)
def office_attachment_menu(context, obj):
    return _ctx(context, obj, compact=True)


@register.inclusion_tag('office/_new_menu.html', takes_context=True)
def office_new_menu(context):
    request = context.get('request')
    from core.middleware import get_request_organization
    org = get_request_organization(request) if request else None
    user = getattr(request, 'user', None)
    return {
        'show': bool(org and user and creation.can_create_document(user, org)),
        'formats': [(f, creation.FORMAT_LABELS[f]) for f in creation.NEW_FORMATS],
        'csrf_token': context.get('csrf_token'), 'entity_type': '', 'entity_id': '',
    }


@register.inclusion_tag('office/_new_menu.html', takes_context=True)
def office_new_attachment_menu(context, entity_type, entity_id):
    request = context.get('request')
    from core.middleware import get_request_organization
    org = get_request_organization(request) if request else None
    user = getattr(request, 'user', None)
    return {
        'show': bool(org and user and creation.can_create_attachment(user, org)),
        'formats': [(f, creation.FORMAT_LABELS[f]) for f in creation.NEW_FORMATS],
        'csrf_token': context.get('csrf_token'), 'entity_type': entity_type,
        'entity_id': entity_id, 'next': request.get_full_path() if request else '',
    }


@register.simple_tag(takes_context=True)
def office_attachments(context, entity_type, entity_id, organization_id=None):
    """Office files (files.Attachment) on one entity that the viewer may see.
    Usage: {% office_attachments 'asset' asset.pk asset.organization_id as office_files %}"""
    request = context.get('request')
    user = getattr(request, 'user', None)
    org = organization_id
    if org is None and request is not None:
        from core.middleware import get_request_organization
        org = getattr(get_request_organization(request), 'pk', None)
    if user is None or org is None:
        return []
    from files.models import Attachment
    rows = Attachment.objects.filter(organization=org, entity_type=entity_type,
                                     entity_id=entity_id).order_by('-created_at')[:100]
    out = []
    for a in rows:
        if formats.is_office(a.original_filename) and targets.AttachmentTarget(a).can_view(user):
            out.append(a)
    return out
