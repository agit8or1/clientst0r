"""
Relationship views - Create and manage relationships between objects
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import models
from core.middleware import get_request_organization
from core.decorators import require_write
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


@login_required
@require_write
def relationship_create(request):
    """
    Create a new relationship between two objects.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        source_type = request.POST.get('source_type')
        source_id = request.POST.get('source_id')
        target_type = request.POST.get('target_type')
        target_id = request.POST.get('target_id')
        relation_type = request.POST.get('relation_type', 'related')
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

            messages.success(request, f"Relationship created successfully.")
            return redirect(f"{request.META.get('HTTP_REFERER', 'assets:relationship_map')}")

        except Exception as e:
            messages.error(request, f"Error creating relationship: {str(e)}")
            return redirect('assets:relationship_map')

    # GET request - show form
    source_type = request.GET.get('source_type')
    source_id = request.GET.get('source_id')

    # Get available objects for selection
    assets = Asset.objects.for_organization(org)
    documents = Document.objects.for_organization(org).filter(is_published=True)
    passwords = visible_passwords(request.user, Password.objects.for_organization(org))

    return render(request, 'assets/relationship_form.html', {
        'source_type': source_type,
        'source_id': source_id,
        'assets': assets,
        'documents': documents,
        'passwords': passwords,
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
            # Note: Contact model needs to be imported if not already
            from contacts.models import Contact
            Contact.objects.get(id=object_id, organization=org)
            return True
    except Exception:
        return False
