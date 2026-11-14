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


class SearchScope:
    """The rows one search may look at, per content type — shared by the
    search page (`global_search`) and the command palette
    (`core.palette_views`), so the two can never disagree about scoping.

    Each method returns a queryset already narrowed to what this user may
    open (customer scoping, role flag, feature flag), or None when the
    content type is not searchable for them at all. `query` narrows by text;
    None returns the scoped rows unfiltered (used to re-check stored
    favorites and recent items). `fields` overrides the text fields matched.
    See `global_search` for why the scoping is what it is.
    """

    def __init__(self, request):
        self.request = request
        self.user = request.user
        self.org = get_request_organization(request)
        is_staff = getattr(request, 'is_staff_user', False)
        self.in_global_view = not self.org and (self.user.is_superuser or is_staff)
        self._staff_user = None

    @property
    def staff_user(self):
        if self._staff_user is None:
            from psa.visibility import is_msp_staff
            self._staff_user = bool(is_msp_staff(self.user))
        return self._staff_user

    def scoped(self, model):
        """The rows this search may look at, before the query is applied."""
        if self.in_global_view:
            return model.objects.all()
        if self.org is None:
            # Not staff and no organization — nothing to search.
            return model.objects.none()
        return model.objects.for_organization(self.org)

    def permitted(self, model, perm):
        """`scoped()` narrowed to the customers whose role grants `perm`.

        Role flags vault_view / docs_view / assets_view / integrations_view
        are enforced here the same way the section middleware enforces them
        on /vault/, /docs/, /assets/ and /integrations/ — search must not
        list titles a user can't open.
        """
        return filter_by_org_perm(self.scoped(model), self.user, perm)

    @staticmethod
    def _text(qs, query, fields):
        if query is None:
            return qs
        cond = Q()
        for f in fields:
            cond |= Q(**{f'{f}__icontains': query})
        return qs.filter(cond)

    def assets(self, query, fields=('name', 'asset_tag', 'serial_number', 'manufacturer',
                                    'model', 'notes')):
        return self._text(self.permitted(Asset, 'assets_view'), query, fields
                          ).select_related('organization')

    def contacts(self, query):
        # They live under /assets/contacts/ — assets_view.
        return self._text(self.permitted(Contact, 'assets_view'), query,
                          ('first_name', 'last_name', 'email', 'phone', 'title')
                          ).select_related('organization')

    def documents(self, query, fields=('title', 'body')):
        """Org-specific documents. `.published()` is the one definition of
        live: published, not a pending draft, not archived. A customer user
        additionally sees only what the document list shows them
        (docs.permissions.visible_documents: no internal-only articles)."""
        from docs.permissions import visible_documents
        qs = visible_documents(self.permitted(Document, 'docs_view').published().filter(
            is_global=False), self.user)
        return self._text(qs, query, fields).select_related('organization')

    def global_kb(self, query, fields=('title', 'body')):
        """Global KB. Not org-scoped by definition — a global article belongs
        to no client — so it needs docs_view across every customer, which
        only superusers and MSP staff can hold (same reach as the old
        staff-only rule, minus staff whose global role drops docs_view)."""
        if orgs_with_perm(self.user, 'docs_view') is not None:
            return None
        return self._text(Document.objects.published().filter(is_global=True), query, fields)

    def passwords(self, query):
        """Title, username, URL and notes only — never the secret."""
        return self._text(self.permitted(Password, 'vault_view').filter(is_personal=False), query,
                          ('title', 'username', 'url', 'notes')).select_related('organization')

    def _psa_rows(self, model):
        """PSA companies / contacts, scoped by their own organization the way
        `integrations.views` does, not via the connection — same rows, and
        it picks up descendants like everything else here. They open under
        /integrations/, so integrations_view governs them. Rows a
        platform-owned connection has not assigned to a customer yet
        (organization empty) are platform data: only platform staff see
        them, and only in global view."""
        qs = self.permitted(model, 'integrations_view')
        from integrations.ownership import can_view_platform
        if not (self.in_global_view and can_view_platform(self.user)):
            qs = qs.exclude(organization__isnull=True)
        return qs

    def psa_companies(self, query):
        return self._text(self._psa_rows(PSACompany), query, ('name',))

    def psa_contacts(self, query):
        return self._text(self._psa_rows(PSAContact), query, ('first_name', 'last_name', 'email'))

    def tickets(self, query):
        """Tickets (PSA on): the ticket list's own scoping — every ticket for
        MSP staff, shared tickets of their customers for customer users. A
        ticket number typed exactly is listed first."""
        from core.models import SystemSetting
        if not getattr(SystemSetting.get_settings(), 'psa_enabled', False):
            return None
        from django.db.models import Case, IntegerField, Value, When
        from psa.views import _scoped_ticket_qs
        from psa.visibility import customer_ticket_q
        user = self.user
        tickets = filter_by_org_perm(_scoped_ticket_qs(self.request), user, 'tickets_view')
        if not self.staff_user:
            # A customer user finds the tickets they could open: their
            # own, or the whole organization's when their role allows.
            tickets = tickets.filter(customer_ticket_q(
                user, user.memberships.filter(is_active=True,
                                              organization__is_active=True)
                .select_related('role_template')))
        if query is None:
            return tickets
        return tickets.filter(
            Q(ticket_number__icontains=query) | Q(subject__icontains=query)
        ).annotate(_exact=Case(When(ticket_number__iexact=query, then=Value(0)),
                               default=Value(1), output_field=IntegerField())
                   ).order_by('_exact', '-created_at')

    def rmm_devices(self, query):
        """RMM devices (MSP staff): the same customer scoping as assets,
        settled customers only. Results open through core:open_device, so a
        device of another customer switches context instead of 404ing."""
        if not self.staff_user:
            return None
        from integrations.models import RMMDevice
        qs = self.permitted(RMMDevice, 'assets_view').filter(
            ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
        return self._text(qs, query, ('device_name', 'hostname', 'serial_number', 'ip_address')
                          ).select_related('organization')

    def clients(self, query):
        """Clients the technician may switch to (the client switcher's rule).
        Staff only: a customer user's only "client" is their own company, and
        the results link to the staff Customer Operations page."""
        if not self.staff_user:
            return None
        from core.client_switcher import authorized_organizations
        return self._text(authorized_organizations(self.request), query, ('name',)).order_by('name')


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
    scope = SearchScope(request)
    org = scope.org
    query = request.GET.get('q', '').strip()
    in_global_view = scope.in_global_view

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
    user = request.user

    def take(key, qs):
        """Record the real count, then keep the first RESULT_LIMIT rows."""
        if qs is None:
            return
        results['counts'][key] = qs.count()
        results[key] = list(qs[:RESULT_LIMIT])

    if query and len(query) >= 2:
        take('assets', scope.assets(query))
        take('contacts', scope.contacts(query))
        take('documents', scope.documents(query))
        take('global_kb', scope.global_kb(query))
        # Title and username only, not actual passwords.
        take('passwords', scope.passwords(query))
        try:
            take('psa_companies', scope.psa_companies(query))
            take('psa_contacts', scope.psa_contacts(query))
        except Exception:
            # The PSA tables are optional on an install that has never had an
            # integration configured; a search must not 500 over that.
            logger.debug('PSA search skipped', exc_info=True)
        try:
            take('tickets', scope.tickets(query))
        except Exception:
            logger.debug('ticket search skipped', exc_info=True)
        try:
            take('rmm_devices', scope.rmm_devices(query))
        except Exception:
            logger.debug('RMM device search skipped', exc_info=True)
        take('clients', scope.clients(query))

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
