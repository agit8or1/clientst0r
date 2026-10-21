"""
Mobile API knowledge-base endpoints (v3.17.350).

KB articles are stored in `docs.Document`. Visibility rules:
- `is_global=True` and `is_published=True` → visible to all logged-in users.
- Org-scoped (`organization_id` set) → visible to members of that org.
- `is_archived=True` → hidden.
- Org-scoped docs additionally need `docs_view` in that customer.
- Global (MSP-wide) articles follow the web rule (`global_kb_list` /
  `global_kb_detail` are staff-only): visible only with every-customer
  `docs_view` reach — superusers and MSP staff whose global role grants it
  (or who have none). Customer users never see them.
"""
from __future__ import annotations

from django.db.models import Q
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import orgs_with_perm

from .scoping import accessible_org_ids, perm_org_ids


def _kb_queryset(user):
    """Articles the user is allowed to see."""
    from docs.models import Document
    org_ids = perm_org_ids(user, 'docs_view')
    visible = Q(organization_id__in=org_ids)
    if orgs_with_perm(user, 'docs_view') is None:
        visible |= Q(is_global=True)
    # published(): live only — not a draft, pending review or archived.
    return Document.objects.published().filter(visible)


def _serialize_kb(doc, *, detail=False):
    out = {
        'id': doc.id,
        'title': doc.title,
        'slug': doc.slug,
        'is_global': doc.is_global,
        'organization_id': doc.organization_id,
        'content_type': doc.content_type,
        'updated_at': doc.updated_at.isoformat() if doc.updated_at else None,
    }
    if detail:
        out['body'] = doc.body
        try:
            out['body_html'] = doc.render_content()
        except Exception:
            out['body_html'] = doc.body
    return out


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def kb_list_view(request):
    """GET /api/mobile/v1/kb/?search=&organization_id=&page=

    v3.17.474 — added optional `organization_id` filter so the mobile
    KB screen can scope to a single client. `organization_id=global`
    (or any non-integer that resolves to 'global') filters to
    `is_global=True` docs only.
    """
    qs = _kb_queryset(request.user)

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search) | Q(body__icontains=search) | Q(slug__icontains=search)
        )

    org_filter = (request.query_params.get('organization_id') or '').strip()
    if org_filter == 'global':
        qs = qs.filter(is_global=True)
    elif org_filter:
        try:
            org_id = int(org_filter)
            org_ids = list(accessible_org_ids(request.user))
            if org_id in org_ids:
                qs = qs.filter(organization_id=org_id)
            else:
                qs = qs.none()
        except ValueError:
            pass

    qs = qs.order_by('-updated_at')

    try:
        page = max(int(request.query_params.get('page', 1)), 1)
    except ValueError:
        page = 1
    page_size = 50
    start = (page - 1) * page_size
    total = qs.count()
    rows = qs[start:start + page_size]

    return Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': [_serialize_kb(d) for d in rows],
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def kb_detail_view(request, pk: int):
    """GET /api/mobile/v1/kb/<id>/ — detail with raw markdown + rendered HTML."""
    try:
        doc = _kb_queryset(request.user).get(pk=pk)
    except Exception:
        return Response({'detail': 'Not found'}, status=404)
    return Response(_serialize_kb(doc, detail=True))
