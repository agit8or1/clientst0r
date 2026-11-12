"""
Client switcher: who may switch to which client, recent clients, and search.

The switcher in the navbar (templates/core/_client_switcher.html) has to stay
usable with hundreds of clients, so it never lists every client inline once
there are more than INLINE_ALL_LIMIT. It shows the current context, up to
RECENT_LIMIT recently used clients, and a search box backed by
`client_switcher_search` (bounded to SEARCH_LIMIT results).

Access rules are the same ones the switch view (accounts.views.
switch_organization) and core.middleware.CurrentOrganizationMiddleware apply:
superusers and MSP staff (profile user_type=Staff) reach every active client;
everyone else only clients where they hold an active membership. Recents are
filtered through those rules on every request, so a revoked membership removes
the client from recents and search at once.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .models import Organization, RecentClient

RECENT_LIMIT = 5
# Rows kept per user; older ones are pruned when a new switch is recorded.
RECENT_KEEP = 20
# At or below this many clients the switcher lists them all, like it always
# did; above it, recents + search.
INLINE_ALL_LIMIT = 10
SEARCH_LIMIT = 20
SEARCH_PAGE_LIMIT = 50


def has_all_client_access(request):
    """Superusers and MSP staff reach every active client (and Global View),
    unless the staff member's client scope narrows it
    (accounts.permission_utils.staff_client_org_ids)."""
    user = request.user
    if user.is_superuser:
        return True
    if not getattr(request, 'is_staff_user', False):
        return False
    from accounts.permission_utils import staff_client_org_ids
    return staff_client_org_ids(user) is None


def authorized_organizations(request):
    """Active clients the requesting user may switch to right now."""
    qs = Organization.objects.filter(is_active=True)
    if has_all_client_access(request):
        return qs
    if getattr(request, 'is_staff_user', False):
        from accounts.permission_utils import staff_client_org_ids
        return qs.filter(pk__in=staff_client_org_ids(request.user) or set())
    return qs.filter(
        memberships__user=request.user,
        memberships__is_active=True,
    ).distinct()


def organization_list_queryset(user):
    """Clients shown on the organizations list page (accounts:organization_list).

    Superusers see every client; other users the clients they own.
    """
    if user.is_superuser:
        return Organization.objects.all()
    from accounts.models import Membership, Role
    owned_ids = Membership.objects.filter(
        user=user, role=Role.OWNER, is_active=True,
    ).values_list('organization_id', flat=True)
    return Organization.objects.filter(id__in=owned_ids)


def can_view_client_list(user):
    """Whether the organizations list page would show this user anything."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or organization_list_queryset(user).exists()


def record_recent_client(user, organization):
    """Note that `user` just switched to `organization`."""
    if not user.is_authenticated or organization is None:
        return
    RecentClient.objects.update_or_create(
        user=user, organization=organization,
        defaults={'switched_at': timezone.now()},
    )
    stale = list(
        RecentClient.objects.filter(user=user)
        .order_by('-switched_at')
        .values_list('id', flat=True)[RECENT_KEEP:]
    )
    if stale:
        RecentClient.objects.filter(id__in=stale).delete()


def recent_clients(request, authorized_ids=None, limit=RECENT_LIMIT):
    """The user's most recently switched-to clients they can still reach.

    `authorized_ids` (a set of org ids) avoids a second access query when the
    caller already has the authorized list; otherwise it is resolved here.
    """
    if not request.user.is_authenticated:
        return []
    rows = (
        RecentClient.objects.filter(user=request.user, organization__is_active=True)
        .select_related('organization')
        .order_by('-switched_at')
    )
    if authorized_ids is None:
        rows = rows.filter(organization__in=authorized_organizations(request))
        return [r.organization for r in rows[:limit]]
    out = []
    for r in rows[:RECENT_KEEP]:
        if r.organization_id in authorized_ids:
            out.append(r.organization)
            if len(out) >= limit:
                break
    return out


def switcher_context(request, user_organizations):
    """Template context for templates/core/_client_switcher.html.

    `user_organizations` is the authorized list the org context processor
    already built (same rules as `authorized_organizations`).
    """
    orgs = list(user_organizations or [])
    total = len(orgs)
    show_all_inline = total <= INLINE_ALL_LIMIT
    ctx = {
        'total': total,
        'show_all_inline': show_all_inline,
        'inline_orgs': orgs if show_all_inline else [],
        'recents': [],
        'search_enabled': not show_all_inline,
        'can_global_view': has_all_client_access(request),
        'can_view_list': False,
    }
    if not show_all_inline:
        ctx['recents'] = recent_clients(request, authorized_ids={o.id for o in orgs})
    try:
        ctx['can_view_list'] = can_view_client_list(request.user)
    except Exception:
        ctx['can_view_list'] = False
    return ctx


def _search(request, query, limit):
    qs = authorized_organizations(request)
    if query:
        qs = qs.filter(name__icontains=query)
    qs = qs.order_by('name')
    rows = list(qs.values('id', 'name')[:limit + 1])
    return rows[:limit], len(rows) > limit


def _wants_json(request):
    return (
        request.GET.get('format') == 'json'
        or 'application/json' in request.headers.get('Accept', '')
    )


@login_required
def client_switcher_search(request):
    """Search the clients the user may switch to.

    JSON for the navbar switcher; a plain results page otherwise (no-JS
    fallback for the switcher's search form). Only authorized clients are
    ever returned.
    """
    query = (request.GET.get('q') or '').strip()[:100]
    current = getattr(request, 'current_organization', None)
    current_id = current.id if current else None

    if _wants_json(request):
        rows, truncated = _search(request, query, SEARCH_LIMIT)
        return JsonResponse({
            'query': query,
            'results': [
                {
                    'id': r['id'],
                    'name': r['name'],
                    'url': reverse('accounts:switch_organization', args=[r['id']]),
                    'active': r['id'] == current_id,
                }
                for r in rows
            ],
            'truncated': truncated,
        })

    rows, truncated = _search(request, query, SEARCH_PAGE_LIMIT)
    return render(request, 'core/client_switcher_search.html', {
        'query': query,
        'results': rows,
        'truncated': truncated,
        'current_id': current_id,
        'can_global_view': has_all_client_access(request),
        'can_view_list': can_view_client_list(request.user),
    })
