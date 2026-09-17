"""
Global search views - Search across all content
"""
import logging

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from core.middleware import get_request_organization
from assets.models import Asset, Contact
from vault.models import Password
from docs.models import Document
from integrations.models import PSACompany, PSAContact

logger = logging.getLogger('core')

# Per content type, matching what the list pages already show.
RESULT_LIMIT = 10


@login_required
def global_search(request):
    """
    Global search across all content types.

    Scoping follows the list pages exactly (`assets.views.asset_list` is the
    reference): a staff user or superuser with no organization selected is in
    global view and searches everything; anyone else searches their current
    organization *and its descendants*, via `OrganizationManager`.

    Both halves of that were wrong before v3.17.570. Every branch filtered a
    bare `organization=org`, so:

      * Phase 18's organization hierarchy was ignored. A user at a parent org
        sees a subsidiary's assets, contacts, documents and passwords on every
        list page, and got no hits for any of them here.
      * In global view `org` is None, so `organization=None` matched nothing
        and search came back empty across all six content types — while every
        list page showed the whole install.

    Both are under-returns, which is why neither was ever reported: search
    saying "no results" is indistinguishable from the thing not existing.
    """
    org = get_request_organization(request)
    query = request.GET.get('q', '').strip()

    is_staff = getattr(request, 'is_staff_user', False)
    in_global_view = not org and (request.user.is_superuser or is_staff)

    results = {
        'query': query,
        'assets': [],
        'contacts': [],
        'documents': [],
        'global_kb': [],
        'passwords': [],
        'psa_companies': [],
        'psa_contacts': [],
        'total_count': 0,
        'in_global_view': in_global_view,
        # A result set can now span organizations — the whole install in
        # global view, or an org plus its subsidiaries — so each row says
        # whose it is. When it cannot span, the badge would be noise.
        'show_org_badge': in_global_view or (
            org is not None and org.children.exists()
        ),
    }

    def scoped(model):
        """The rows this search may look at, before the query is applied."""
        if in_global_view:
            return model.objects.all()
        if org is None:
            # Not staff and no organization — nothing to search.
            return model.objects.none()
        return model.objects.for_organization(org)

    if query and len(query) >= 2:
        # Search Assets
        results['assets'] = scoped(Asset).filter(
            Q(name__icontains=query) |
            Q(asset_tag__icontains=query) |
            Q(serial_number__icontains=query) |
            Q(manufacturer__icontains=query) |
            Q(model__icontains=query) |
            Q(notes__icontains=query)
        ).select_related('organization')[:RESULT_LIMIT]

        # Search Contacts
        results['contacts'] = scoped(Contact).filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query) |
            Q(title__icontains=query)
        ).select_related('organization')[:RESULT_LIMIT]

        # Search Documents (org-specific only)
        results['documents'] = scoped(Document).filter(
            is_published=True,
            is_archived=False,
            is_global=False,
        ).filter(
            Q(title__icontains=query) |
            Q(body__icontains=query)
        ).select_related('organization')[:RESULT_LIMIT]

        # Search Global KB (staff users and superusers only). Not org-scoped
        # by definition — a global article belongs to no client.
        if is_staff or request.user.is_superuser:
            results['global_kb'] = Document.objects.filter(
                is_global=True,
                is_published=True,
                is_archived=False
            ).filter(
                Q(title__icontains=query) |
                Q(body__icontains=query)
            )[:RESULT_LIMIT]

        # Search Passwords (title and username only, not actual passwords)
        results['passwords'] = scoped(Password).filter(
            is_personal=False,
        ).filter(
            Q(title__icontains=query) |
            Q(username__icontains=query) |
            Q(url__icontains=query) |
            Q(notes__icontains=query)
        ).select_related('organization')[:RESULT_LIMIT]

        # Search PSA Companies / Contacts. Scoped by their own organization
        # the way `integrations.views` does, not via the connection — same
        # rows, and it picks up descendants like everything else here.
        try:
            results['psa_companies'] = scoped(PSACompany).filter(
                Q(name__icontains=query)
            )[:RESULT_LIMIT]

            results['psa_contacts'] = scoped(PSAContact).filter(
                Q(name__icontains=query) |
                Q(email__icontains=query)
            )[:RESULT_LIMIT]
        except Exception:
            # The PSA tables are optional on an install that has never had an
            # integration configured; a search must not 500 over that.
            logger.debug('PSA search skipped', exc_info=True)

        # Calculate total
        results['total_count'] = (
            len(results['assets']) +
            len(results['contacts']) +
            len(results['documents']) +
            len(results['global_kb']) +
            len(results['passwords']) +
            len(results['psa_companies']) +
            len(results['psa_contacts'])
        )

    return render(request, 'core/search_results.html', results)
