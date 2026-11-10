"""
Relationship views - Create and manage relationships between objects
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import models
from django.urls import reverse
from core.middleware import get_request_organization
from core.decorators import require_write, require_organization_context
from core.org_handoff import org_handoff
from .models import Asset, Relationship
from docs.models import Document
from vault.models import Password
from vault.permissions import visible_passwords


@login_required
def relationship_map(request):
    """
    Visual relationship map showing connections between objects.
    """
    org = get_request_organization(request)

    # Get filter parameters
    object_type = request.GET.get('type', 'asset')
    object_id = request.GET.get('id')

    # Security: Validate object_type against whitelist to prevent IDOR
    VALID_OBJECT_TYPES = ['asset', 'document', 'password', 'contact']
    if object_type not in VALID_OBJECT_TYPES:
        messages.error(request, f"Invalid object type: {object_type}")
        return redirect('assets:relationship_map')

    relationships = []
    nodes = []
    edges = []

    if object_id:
        # Get relationships for specific object
        relationships = Relationship.objects.filter(
            organization=org
        ).filter(
            models.Q(source_type=object_type, source_id=object_id) |
            models.Q(target_type=object_type, target_id=object_id)
        )

        # Build nodes and edges for visualization
        processed_nodes = set()

        for rel in relationships:
            # Add source node
            if f"{rel.source_type}-{rel.source_id}" not in processed_nodes:
                node = get_node_data(org, rel.source_type, rel.source_id, request.user)
                if node:
                    nodes.append(node)
                    processed_nodes.add(f"{rel.source_type}-{rel.source_id}")

            # Add target node
            if f"{rel.target_type}-{rel.target_id}" not in processed_nodes:
                node = get_node_data(org, rel.target_type, rel.target_id, request.user)
                if node:
                    nodes.append(node)
                    processed_nodes.add(f"{rel.target_type}-{rel.target_id}")

            # Add edge
            edges.append({
                'id': rel.id,
                'source': f"{rel.source_type}-{rel.source_id}",
                'target': f"{rel.target_type}-{rel.target_id}",
                'label': rel.get_relation_type_display(),
                'type': rel.relation_type
            })
    else:
        # Show all assets with relationships
        assets = Asset.objects.for_organization(org)[:20]  # Limit to 20 for performance

    return render(request, 'assets/relationship_map.html', {
        'nodes': nodes,
        'edges': edges,
        'object_type': object_type,
        'object_id': object_id,
    })


def _split_ref(data, prefix):
    """`<prefix>_type` + `<prefix>_id`, or the form pickers' combined
    `<prefix>` value "type:id"."""
    obj_type = data.get(f'{prefix}_type')
    obj_id = data.get(f'{prefix}_id')
    combined = data.get(prefix) or ''
    if (not obj_type or not obj_id) and ':' in combined:
        obj_type, _, obj_id = combined.partition(':')
    return obj_type, obj_id


@login_required
@org_handoff
@require_write
@require_organization_context
def relationship_create(request):
    """
    Create a new relationship between two objects.

    GET shows the form. `?source_type=&source_id=&target_type=` (readiness
    "Link it") preselect the source object and the kind of target; only this
    customer's objects the user may see are offered or preselected, and
    nothing is saved until the form is submitted.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        source_type, source_id = _split_ref(request.POST, 'source')
        target_type, target_id = _split_ref(request.POST, 'target')
        relation_type = request.POST.get('relation_type', 'related')
        if relation_type not in dict(Relationship.RELATION_TYPES):
            relation_type = 'related'
        notes = request.POST.get('notes', '')

        try:
            # Security: Validate object types against whitelist to prevent IDOR
            VALID_OBJECT_TYPES = ['asset', 'document', 'password', 'contact']
            if source_type not in VALID_OBJECT_TYPES or target_type not in VALID_OBJECT_TYPES:
                messages.error(request, "Invalid object type.")
                return redirect('assets:relationship_map')

            # Validate object IDs are integers
            try:
                source_id = int(source_id)
                target_id = int(target_id)
            except (ValueError, TypeError):
                messages.error(request, "Invalid object ID.")
                return redirect('assets:relationship_map')

            # Validate objects exist and belong to organization
            if not validate_object(org, source_type, source_id, request.user):
                messages.error(request, "Source object not found.")
                return redirect('assets:relationship_map')

            if not validate_object(org, target_type, target_id, request.user):
                messages.error(request, "Target object not found.")
                return redirect('assets:relationship_map')

            # Create relationship
            relationship = Relationship.objects.create(
                organization=org,
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
                relation_type=relation_type,
                notes=notes
            )

            messages.success(request, "Relationship created successfully.")
            if source_type == 'asset':
                return redirect('assets:asset_detail', pk=source_id)
            return redirect(f"{reverse('assets:relationship_map')}?type={source_type}&id={source_id}")

        except Exception as e:
            messages.error(request, f"Error creating relationship: {str(e)}")
            return redirect('assets:relationship_map')

    # GET request - show form. Objects of this customer only (exact org, as
    # validate_object checks on save), vault entries the user may see.
    from .models import Contact
    choices = {
        'asset': [(a.pk, a.name) for a in
                  Asset.objects.filter(organization=org).only('id', 'name').order_by('name')],
        'document': [(d.pk, d.title) for d in
                     Document.objects.filter(organization=org, is_archived=False)
                     .only('id', 'title').order_by('title')],
        'contact': [(c.pk, f'{c.first_name} {c.last_name}'.strip() or c.email) for c in
                    Contact.objects.filter(organization=org).order_by('first_name', 'last_name')],
        'password': [(p.pk, p.title) for p in
                     visible_passwords(request.user, Password.objects.filter(organization=org))
                     .only('id', 'title').order_by('title')],
    }
    labels = {'asset': 'Assets', 'document': 'Documents', 'contact': 'Contacts',
              'password': 'Vault entries'}
    source_type, source_id = _split_ref(request.GET, 'source')
    selected_source = ''
    if source_type in choices and str(source_id or '').isdigit() and \
            int(source_id) in {pk for pk, _ in choices[source_type]}:
        selected_source = f'{source_type}:{int(source_id)}'
    target_type = request.GET.get('target_type')
    if target_type not in choices:
        target_type = ''
    groups = [{'type': t, 'label': labels[t], 'items': [(f'{t}:{pk}', label) for pk, label in choices[t]]}
              for t in choices]

    return render(request, 'assets/relationship_form.html', {
        'groups': groups,
        'target_groups': [g for g in groups if not target_type or g['type'] == target_type],
        'selected_source': selected_source,
        'target_type': target_type,
        'target_type_label': labels.get(target_type, ''),
        'relation_types': Relationship.RELATION_TYPES,
    })


@login_required
@require_write
def relationship_delete(request, pk):
    """
    Delete a relationship.
    """
    org = get_request_organization(request)
    relationship = get_object_or_404(Relationship, pk=pk, organization=org)

    if request.method == 'POST':
        relationship.delete()
        messages.success(request, "Relationship deleted successfully.")
        return redirect(request.META.get('HTTP_REFERER', 'assets:relationship_map'))

    return render(request, 'assets/relationship_confirm_delete.html', {
        'relationship': relationship,
    })


@login_required
def topology_json(request):
    """
    Phase 16 v3 (v3.17.303): JSON topology endpoint. Returns nodes +
    edges for the active org's full asset/service relationship graph,
    suitable for external visualization tools (Cytoscape, vis-network,
    D3 force layout). Capped at 1000 nodes / 2000 edges to keep
    payload manageable.

    Response shape:
      {nodes: [{id, label, type, asset_type|status}, ...],
       edges: [{source, target, type}, ...],
       counts: {assets, services, edges}}
    """
    from .models import Service
    org = get_request_organization(request)
    if org is None:
        return JsonResponse({'nodes': [], 'edges': [],
                              'counts': {'assets': 0, 'services': 0,
                                         'edges': 0}})
    nodes = []
    for a in Asset.objects.for_organization(org)[:800]:
        nodes.append({
            'id': f'asset-{a.pk}',
            'label': a.name,
            'type': 'asset',
            'asset_type': a.asset_type,
        })
    for s in Service.objects.for_organization(org)[:200]:
        nodes.append({
            'id': f'service-{s.pk}',
            'label': s.name,
            'type': 'service',
            'status': s.status,
            'criticality': s.criticality,
        })
    edges = []
    rels = Relationship.objects.filter(
        organization=org,
        source_type__in=['asset', 'service'],
        target_type__in=['asset', 'service'],
    )[:2000]
    for r in rels:
        edges.append({
            'source': f'{r.source_type}-{r.source_id}',
            'target': f'{r.target_type}-{r.target_id}',
            'type': r.relation_type,
        })
    return JsonResponse({
        'nodes': nodes,
        'edges': edges,
        'counts': {
            'assets': sum(1 for n in nodes if n['type'] == 'asset'),
            'services': sum(1 for n in nodes if n['type'] == 'service'),
            'edges': len(edges),
        },
    })


def get_node_data(org, object_type, object_id, user=None):
    """
    Get node data for visualization.
    """
    try:
        if object_type == 'asset':
            obj = Asset.objects.get(id=object_id, organization=org)
            return {
                'id': f"asset-{obj.id}",
                'label': obj.name,
                'type': 'asset',
                'url': f"/assets/{obj.id}/",
                'icon': 'server'
            }
        elif object_type == 'document':
            obj = Document.objects.get(id=object_id, organization=org)
            return {
                'id': f"document-{obj.id}",
                'label': obj.title,
                'type': 'document',
                'url': f"/docs/{obj.slug}/",
                'icon': 'book'
            }
        elif object_type == 'password':
            obj = visible_passwords(user, Password.objects.filter(organization=org)).get(id=object_id)
            return {
                'id': f"password-{obj.id}",
                'label': obj.title,
                'type': 'password',
                'url': f"/vault/{obj.id}/",
                'icon': 'key'
            }
    except Exception:
        return None


def validate_object(org, object_type, object_id, user=None):
    """
    Validate that an object exists in the organization.
    """
    # Security: Validate object_type against whitelist to prevent IDOR
    VALID_OBJECT_TYPES = ['asset', 'document', 'password', 'contact']
    if object_type not in VALID_OBJECT_TYPES:
        return False

    try:
        if object_type == 'asset':
            Asset.objects.get(id=object_id, organization=org)
            return True
        elif object_type == 'document':
            Document.objects.get(id=object_id, organization=org)
            return True
        elif object_type == 'password':
            visible_passwords(user, Password.objects.filter(organization=org)).get(id=object_id)
            return True
        elif object_type == 'contact':
            # Contact lives in assets (there is no `contacts` app; the old
            # import made every contact link fail as "not found").
            from .models import Contact
            Contact.objects.get(id=object_id, organization=org)
            return True
    except Exception:
        return False
