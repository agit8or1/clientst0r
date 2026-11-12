"""
Global search views - Search across all content
"""
import logging

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from accounts.permission_utils import filter_by_org_perm, orgs_with_perm
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
        'tickets': [],
        'rmm_devices': [],
        'clients': [],
        'total_count': 0,
        # Real match counts per category, before the RESULT_LIMIT slice, so
        # the page can say "showing 10 of 37" instead of implying 10 is all.
        'counts': {},
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

    user = request.user

    def permitted(model, perm):
        """`scoped()` narrowed to the customers whose role grants `perm`.

        Role flags vault_view / docs_view / assets_view / integrations_view
        are enforced here the same way the section middleware enforces them
        on /vault/, /docs/, /assets/ and /integrations/ — search must not
        list titles a user can't open.
        """
        return filter_by_org_perm(scoped(model), user, perm)

    def take(key, qs):
        """Record the real count, then keep the first RESULT_LIMIT rows."""
        results['counts'][key] = qs.count()
        results[key] = list(qs[:RESULT_LIMIT])

    if query and len(query) >= 2:
        # Search Assets
        take('assets', permitted(Asset, 'assets_view').filter(
            Q(name__icontains=query) |
            Q(asset_tag__icontains=query) |
            Q(serial_number__icontains=query) |
            Q(manufacturer__icontains=query) |
            Q(model__icontains=query) |
            Q(notes__icontains=query)
        ).select_related('organization'))

        # Search Contacts (they live under /assets/contacts/ — assets_view)
        take('contacts', permitted(Contact, 'assets_view').filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query) |
            Q(title__icontains=query)
        ).select_related('organization'))

        # Search Documents (org-specific only)
        # `.published()` is the one definition of live: published, not a
        # pending draft, not archived.
        take('documents', permitted(Document, 'docs_view').published().filter(
            is_global=False,
        ).filter(
            Q(title__icontains=query) |
            Q(body__icontains=query)
        ).select_related('organization'))

        # Search Global KB. Not org-scoped by definition — a global article
        # belongs to no client — so it needs docs_view across every customer,
        # which only superusers and MSP staff can hold (same reach as the old
        # staff-only rule, minus staff whose global role drops docs_view).
        if orgs_with_perm(user, 'docs_view') is None:
            take('global_kb', Document.objects.published().filter(
                is_global=True,
            ).filter(
                Q(title__icontains=query) |
                Q(body__icontains=query)
            ))

        # Search Passwords (title and username only, not actual passwords)
        take('passwords', permitted(Password, 'vault_view').filter(
            is_personal=False,
        ).filter(
            Q(title__icontains=query) |
            Q(username__icontains=query) |
            Q(url__icontains=query) |
            Q(notes__icontains=query)
        ).select_related('organization'))

        # Search PSA Companies / Contacts. Scoped by their own organization
        # the way `integrations.views` does, not via the connection — same
        # rows, and it picks up descendants like everything else here. They
        # open under /integrations/, so integrations_view governs them.
        # Rows a platform-owned connection has not assigned to a customer
        # yet (organization empty) are platform data: only platform staff
        # see them, and only in global view.
        def psa_rows(model):
            qs = permitted(model, 'integrations_view')
            from integrations.ownership import can_view_platform
            if not (in_global_view and can_view_platform(user)):
                qs = qs.exclude(organization__isnull=True)
            return qs

        try:
            take('psa_companies', psa_rows(PSACompany).filter(
                Q(name__icontains=query)
            ))

            take('psa_contacts', psa_rows(PSAContact).filter(
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query)
            ))
        except Exception:
            # The PSA tables are optional on an install that has never had an
            # integration configured; a search must not 500 over that.
            logger.debug('PSA search skipped', exc_info=True)

        # Tickets (PSA on): the ticket list's own scoping — every ticket for
        # MSP staff, shared tickets of their customers for customer users. A
        # ticket number typed exactly is listed first.
        from core.models import SystemSetting
        from psa.visibility import is_msp_staff
        staff_user = is_msp_staff(user)
        if getattr(SystemSetting.get_settings(), 'psa_enabled', False):
            try:
                from django.db.models import Case, IntegerField, Value, When
                from psa.views import _scoped_ticket_qs
                from psa.visibility import customer_ticket_q
                tickets = filter_by_org_perm(_scoped_ticket_qs(request), user, 'tickets_view')
                if not staff_user:
                    # A customer user finds the tickets they could open: their
                    # own, or the whole organization's when their role allows.
                    tickets = tickets.filter(customer_ticket_q(
                        user, user.memberships.filter(is_active=True,
                                                      organization__is_active=True)
                        .select_related('role_template')))
                tickets = tickets.filter(
                    Q(ticket_number__icontains=query) | Q(subject__icontains=query)
                ).annotate(_exact=Case(When(ticket_number__iexact=query, then=Value(0)),
                                       default=Value(1), output_field=IntegerField())
                           ).order_by('_exact', '-created_at')
                take('tickets', tickets)
            except Exception:
                logger.debug('ticket search skipped', exc_info=True)

        # RMM devices (MSP staff): the same customer scoping as assets above,
        # settled customers only. Results open through core:open_device, so a
        # device of another customer switches context instead of 404ing.
        if staff_user:
            try:
                from integrations.models import RMMDevice
                take('rmm_devices', permitted(RMMDevice, 'assets_view').filter(
                    ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
                ).filter(
                    Q(device_name__icontains=query) | Q(hostname__icontains=query)
                    | Q(serial_number__icontains=query) | Q(ip_address__icontains=query)
                ).select_related('organization'))
            except Exception:
                logger.debug('RMM device search skipped', exc_info=True)

        # Clients the technician may switch to (the client switcher's rule).
        # Staff only: a customer user's only "client" is their own company, and
        # the results link to the staff Customer Operations page.
        if staff_user:
            from core.client_switcher import authorized_organizations
            take('clients', authorized_organizations(request).filter(
                name__icontains=query).order_by('name'))

        # Real total across categories, not the sum of the sliced lists.
        results['total_count'] = sum(results['counts'].values())

        # Zero-result searches feed KB analytics. The total includes password
        # matches, so a query that found anything in the vault is never zero
        # and its text is never stored.
        if results['total_count'] == 0:
            from docs.models import SearchQueryLog
            SearchQueryLog.record(query, result_count=0, source='global',
                                  user=user, organization=org)

    return render(request, 'core/search_results.html', results)
