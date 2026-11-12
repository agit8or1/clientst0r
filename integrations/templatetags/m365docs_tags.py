"""Microsoft 365 document hooks for documents, assets, tickets and Office files.

    {% load m365docs_tags %}
    {% m365_source_tabs 'local' %}          clientst0r | Microsoft 365 tabs (documents list)
    {% m365_linked_documents obj %}         linked files on a Document / Asset / Ticket
    {% m365_export_button target %}         "Export a copy to Microsoft 365" (Office file page)

Each renders nothing unless the organization has a documents-enabled
Microsoft 365 connection the viewer may use, so no button is shown that
cannot work.
"""
from django import template

from integrations.m365docs import access

register = template.Library()


def _user_org(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    org = None
    if request is not None:
        from core.middleware import get_request_organization
        org = get_request_organization(request)
    return request, user, org


@register.inclusion_tag('integrations/m365docs/_source_tabs.html', takes_context=True)
def m365_source_tabs(context, active='local'):
    request, user, org = _user_org(context)
    return {'show': bool(user and org and access.connections_for(user, org)),
            'active': active, 'request': request}


def _parent_for(obj):
    label = obj._meta.label
    if label == 'docs.Document':
        return 'doc', obj.organization_id
    if label == 'assets.Asset':
        return 'asset', obj.organization_id
    if label == 'psa.Ticket':
        return 'ticket', obj.organization_id
    return None, None


@register.inclusion_tag('integrations/m365docs/_linked.html', takes_context=True)
def m365_linked_documents(context, obj):
    request, user, _org = _user_org(context)
    kind, org_id = _parent_for(obj)
    if kind is None or org_id is None or user is None:
        return {'show': False}
    from integrations.models import LinkedCloudDocument
    conns = access.connections_for(user, org_id)
    if not conns:
        return {'show': False}
    parent = access.Parent(kind, org_id, obj)
    if not parent.can_view(user):
        return {'show': False}
    field = {'doc': 'document', 'asset': 'asset', 'ticket': 'ticket'}[kind]
    links = list(LinkedCloudDocument.objects.filter(
        organization_id=org_id, connection__in=conns, **{field: obj}).select_related('connection'))
    return {'show': True, 'links': links, 'connections': conns, 'parent_param': parent.param,
            'can_link': parent.can_link(user),
            'can_import': any(access.can_import(user, c) for c in conns),
            'request': request, 'csrf_token': context.get('csrf_token')}


@register.inclusion_tag('integrations/m365docs/_export_button.html', takes_context=True)
def m365_export_button(context, target):
    request, user, _org = _user_org(context)
    if user is None or target is None:
        return {'show': False}
    conns = access.connections_for(user, target.organization_id)
    show = any(access.can_export(user, c, target) for c in conns)
    return {'show': show, 'export_param': f'{target.code}:{target.pk}'}
