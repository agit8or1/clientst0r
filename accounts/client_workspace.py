"""Client workspace: the customer page (accounts:organization_detail) as one
place to work on a client — Overview plus Tickets, Assets, RMM, Contacts,
Documents, Passwords, Contracts, Billing, Projects, Activity and Members tabs.

Nothing here decides access on its own. The rules, in order:

* Opening the workspace is the page's existing rule (core.tenancy.
  accessible_org_ids, or an active membership); anyone else is bounced to the
  client list exactly as before.
* Opening it makes the client the session's current client, through the
  same code path and access rule as the client switcher
  (core.client_switcher.authorized_organizations +
  core.org_handoff.switch_session_org, which also records RecentClient).
  Being the current client grants nothing: every list below is the queryset
  the module's own list page builds for the current client, and every gate is
  the server's own check for that list page.
* The data tabs and Overview panels need the client to *be* the current
  client (``Workspace.in_context``). A user who may read the customer record
  but not switch to it (a parent customer's member looking at a subsidiary,
  an inactive client) gets the record itself — information, sites, ratings,
  members — and no tabs, so no list is ever scoped by one customer while the
  section gates were evaluated for another.
* A tab shows only when its module is on and the server would open the
  module's list page for this user right now: core.navigation._PermProbe
  (SectionPermissionMiddleware's prefix rule, MSP-staff-only prefixes and the
  role decorators on the view) plus the checks those list views make in
  their body (PSA on, MSP staff for RMM, billing_view_invoices for invoices).
  Every row links to the module's own detail page, which applies its own
  checks again (vault access rules, reveal approval, and so on).
* Passwords: titles and metadata only, from vault.permissions.
  visible_passwords. The queryset is limited with ``.only()`` to non-secret
  columns, so no encrypted value is even loaded.

Each list is a small slice (TAB_LIMIT rows) plus a count, with a link to the
module's full list page; Overview panels are counts and a few rows each.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

TAB_LIMIT = 50
PANEL_LIMIT = 5
ACTIVITY_LIMIT = 25
RENEWAL_WINDOW_DAYS = 60

OPEN_INVOICE_STATUSES = ('sent', 'partial', 'overdue')
ACTIVE_PROJECT_STATUSES = ('planning', 'active', 'on_hold')

# key, label, icon. Display order; "More" takes whatever does not fit.
TABS = (
    ('overview', 'Overview', 'fa-gauge'),
    ('tickets', 'Tickets', 'fa-ticket-alt'),
    ('assets', 'Assets', 'fa-box'),
    ('rmm', 'RMM', 'fa-desktop'),
    ('contacts', 'Contacts', 'fa-address-book'),
    ('documents', 'Documents', 'fa-file-alt'),
    ('passwords', 'Passwords', 'fa-key'),
    ('contracts', 'Contracts', 'fa-file-contract'),
    ('billing', 'Billing', 'fa-file-invoice-dollar'),
    ('projects', 'Projects', 'fa-diagram-project'),
    ('activity', 'Activity', 'fa-clock-rotate-left'),
    ('members', 'Members', 'fa-users'),
)
TAB_KEYS = tuple(k for k, _l, _i in TABS)

# Columns of vault.Password that carry no secret. The Passwords tab reads
# these and nothing else.
PASSWORD_SAFE_FIELDS = ('id', 'title', 'password_type', 'url', 'updated_at', 'expires_at',
                        'organization_id', 'is_personal', 'requires_reveal_approval')


def _url(name, *args, query=''):
    try:
        url = reverse(name, args=args)
    except NoReverseMatch:
        return ''
    return url + (('?' + query) if query else '')


def _settings():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def _is_msp_staff(user):
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user))


def passes_require_write(request):
    """core.decorators.require_write for a view without an org_id kwarg (the
    create forms), without raising."""
    user = request.user
    if user.is_superuser or user.is_staff:
        return True
    from core.decorators import get_user_membership
    membership = get_user_membership(request)
    return bool(membership and membership.can_write())


# -- context -------------------------------------------------------------------

def follow_client(request, org):
    """Make `org` the session's current client, as the client switcher does.

    Only when the user may switch there (core.client_switcher.
    authorized_organizations — the switcher's and
    accounts.views.switch_organization's rule); otherwise nothing changes.
    Returns True when `org` is the current client afterwards."""
    if org is None or not org.is_active:
        return False
    current = getattr(request, 'current_organization', None)
    from core.client_switcher import authorized_organizations, record_recent_client
    if not authorized_organizations(request).filter(pk=org.pk).exists():
        return False
    if current is not None and current.pk == org.pk:
        record_recent_client(request.user, org)
        return True
    from core.org_handoff import switch_session_org
    switch_session_org(request, org)
    # The per-request authorization context (accounts.authz_cache) was bound
    # to the previous customer by CurrentOrganizationMiddleware; rebind it so
    # user_has_perm and the section probe judge this request for `org`.
    try:
        from accounts import authz_cache
        authz_cache.bind_request(request)
    except Exception:
        pass
    return True


# -- the workspace ---------------------------------------------------------------

@dataclass
class Workspace:
    request: object
    org: object
    in_context: bool = False
    visible: dict = field(default_factory=dict)

    def __post_init__(self):
        self.user = self.request.user
        self.settings = _settings()
        self.staff = _is_msp_staff(self.user)
        self._probe = None
        self.visible = {k: self._gate(k) for k in TAB_KEYS}

    # -- gates ---------------------------------------------------------------

    def allows(self, url_name, *args):
        """Would the server open this page for this user now? The same probe
        the sidebar uses; fails closed."""
        href = _url(url_name, *args)
        if not href:
            return False
        try:
            if self._probe is None:
                from core.navigation import _PermProbe
                self._probe = _PermProbe({
                    'request': self.request, 'user': self.user,
                    'is_staff_user': getattr(self.request, 'is_staff_user', False),
                })
            return bool(self._probe.allows(href))
        except Exception:
            return False

    def has(self, flag):
        from accounts.permission_utils import has_perm_for_org
        return bool(has_perm_for_org(self.user, self.org, flag))

    @property
    def psa_on(self):
        return bool(self.settings.psa_enabled)

    def contract_documents_visible(self):
        """contracts_tags.org_contracts' rule, plus /contracts/ being MSP staff
        only (accounts.middleware.SectionPermissionMiddleware)."""
        if not self.staff:
            return False
        try:
            from contracts import permissions as contract_perms
            return bool(contract_perms.has(self.user, contract_perms.VIEW, self.org.pk))
        except Exception:
            return False

    def _gate(self, key):
        if key in ('overview', 'members'):
            return True
        if not self.in_context:
            return False
        if key == 'tickets':
            # The list page itself only needs PSA on and shows a user without
            # tickets_view nothing; the tab is offered with the flag only
            # (core.customer_ops does the same).
            return self.psa_on and self.allows('psa:ticket_list') and self.has('tickets_view')
        if key == 'assets':
            return self.allows('assets:asset_list')
        if key == 'rmm':
            # integrations.views.rmm_staff_only + the /integrations/rmm/ gates.
            return self.staff and self.allows('integrations:rmm_devices')
        if key == 'contacts':
            return self.allows('assets:contact_list')
        if key == 'documents':
            return self.allows('docs:document_list')
        if key == 'passwords':
            return self.allows('vault:password_list')
        if key == 'contracts':
            return (self.psa_on and self.allows('psa:contract_list')) or self.contract_documents_visible()
        if key == 'billing':
            return self.psa_on and self.allows('psa:invoice_list') and self.has('billing_view_invoices')
        if key == 'projects':
            return self.psa_on and self.allows('psa:project_list')
        if key == 'activity':
            return True
        return False

    def tabs(self, active):
        base = _url('accounts:organization_detail', self.org.pk)
        out = []
        for key, label, icon in TABS:
            if not self.visible.get(key):
                continue
            out.append({
                'key': key, 'label': label, 'icon': icon,
                'href': base if key == 'overview' else f'{base}?tab={key}',
                'active': key == active,
            })
        return out

    # -- querysets: the module list pages' own, for this client ---------------

    def tickets_qs(self):
        """psa.views.ticket_list with ?client=<this client>."""
        from psa.views import _scoped_ticket_qs
        return _scoped_ticket_qs(self.request).filter(organization=self.org)

    def open_tickets_qs(self):
        return self.tickets_qs().filter(resolved_at__isnull=True, status__is_terminal=False)

    def assets_qs(self):
        """assets.views.asset_list for the current client."""
        from assets.models import Asset
        return Asset.objects.for_organization(self.org)

    def rmm_qs(self):
        """integrations.views.rmm_devices for the current client."""
        from integrations.models import RMMDevice
        return RMMDevice.objects.for_organization(self.org)

    def contacts_qs(self):
        """assets.views.contact_list for the current client."""
        from assets.models import Contact
        return Contact.objects.for_organization(self.org)

    def documents_qs(self):
        """docs.views.document_list for the current client."""
        from docs.models import Document
        from docs.permissions import visible_documents
        qs = Document.objects.for_organization(self.org).published().filter(is_global=False, is_template=False)
        return visible_documents(qs, self.user)

    def passwords_qs(self):
        """vault.views.password_list_datatables for the current client,
        reading only non-secret columns. Personal (My Vault) entries are
        never listed here."""
        from vault.models import Password
        from vault.permissions import visible_passwords
        qs = visible_passwords(self.user, Password.objects.for_organization(self.org))
        return qs.filter(is_personal=False).only(*PASSWORD_SAFE_FIELDS)

    def contracts_qs(self):
        """PSA contracts booked under or held with this client, narrowed by
        psa.views._for_customer (the contract pages' own rule)."""
        from psa.models import Contract
        from psa.views import _for_customer
        qs = Contract.objects.filter(Q(organization=self.org) | Q(client_org=self.org))
        return _for_customer(self.request, qs)

    def invoices_qs(self):
        """psa.views.invoice_list's rule: billing_view_invoices for the billed
        (or booking) customer, and a customer user only their own."""
        from accounts.permission_utils import orgs_with_perm
        from psa.models import Invoice
        from psa.views import _invoices_for_customer
        qs = Invoice.objects.filter(Q(organization=self.org) | Q(client_org=self.org))
        allowed = orgs_with_perm(self.user, 'billing_view_invoices')
        if allowed is not None:
            qs = qs.filter(Q(client_org_id__in=allowed) | Q(organization_id__in=allowed))
        return _invoices_for_customer(self.request, qs)

    def projects_qs(self):
        from psa.models import Project
        from psa.views import _for_customer
        qs = Project.objects.filter(Q(organization=self.org) | Q(client_org=self.org))
        return _for_customer(self.request, qs)

    def audit_visible(self):
        """audit.views.audit_log_list (require_admin, current client)."""
        return self.in_context and self.allows('audit:audit_log_list')

    # -- tab bodies ------------------------------------------------------------

    def tab_data(self, key):
        return getattr(self, f'_tab_{key}')()

    def _tab_tickets(self):
        qs = self.tickets_qs()
        open_qs = qs.filter(resolved_at__isnull=True, status__is_terminal=False)
        return {
            'rows': list(open_qs.order_by('-updated_at')[:TAB_LIMIT]),
            'open_count': open_qs.count(),
            'total': qs.count(),
            'list_url': _url('psa:ticket_list', query=f'client={self.org.pk}'),
        }

    def _tab_assets(self):
        qs = self.assets_qs().select_related('organization')
        return {'rows': list(qs.order_by('name')[:TAB_LIMIT]), 'total': qs.count(),
                'list_url': _url('assets:asset_list')}

    def _tab_rmm(self):
        qs = self.rmm_qs()
        counts = qs.aggregate(total=Count('id'), online=Count('id', filter=Q(is_online=True)))
        return {
            'rows': list(qs.select_related('linked_asset').order_by('-is_online', 'device_name')[:TAB_LIMIT]),
            'total': counts['total'], 'online': counts['online'],
            'offline': counts['total'] - counts['online'],
            'list_url': _url('integrations:rmm_devices'),
            'offline_url': _url('integrations:rmm_devices', query='status=offline'),
        }

    def _tab_contacts(self):
        qs = self.contacts_qs()
        return {'rows': list(qs.order_by('last_name', 'first_name')[:TAB_LIMIT]), 'total': qs.count(),
                'list_url': _url('assets:contact_list')}

    def _tab_documents(self):
        qs = self.documents_qs().select_related('category')
        return {'rows': list(qs.order_by('-updated_at')[:TAB_LIMIT]), 'total': qs.count(),
                'list_url': _url('docs:document_list')}

    def _tab_passwords(self):
        qs = self.passwords_qs()
        return {'rows': list(qs.order_by('title')[:TAB_LIMIT]), 'total': qs.count(),
                'list_url': _url('vault:password_list')}

    def _tab_contracts(self):
        data = {'psa': None, 'documents': self.contract_documents_visible()}
        if self.psa_on and self.allows('psa:contract_list'):
            qs = self.contracts_qs()
            data['psa'] = {
                'rows': list(qs.select_related('client_org').order_by('-start_date')[:TAB_LIMIT]),
                'total': qs.count(),
                'list_url': _url('psa:contract_list'),
            }
        return data

    def _tab_billing(self):
        qs = self.invoices_qs()
        open_qs = qs.filter(status__in=OPEN_INVOICE_STATUSES)
        data = {
            'rows': list(qs.order_by('-invoice_date', '-created_at')[:TAB_LIMIT]),
            'total': qs.count(),
            'open_count': open_qs.count(),
            'open_amounts': _balances(open_qs),
            'list_url': _url('psa:invoice_list', query=f'client={self.org.pk}'),
            'account_url': '',
        }
        # psa.views.client_account: a customer the user may act for, and
        # billing_view_invoices there (already part of this tab's gate).
        from psa.views import _customer_orgs
        if _customer_orgs(self.request).filter(pk=self.org.pk).exists():
            data['account_url'] = _url('psa:client_account', self.org.pk)
        return data

    def _tab_projects(self):
        qs = self.projects_qs().select_related('owner')
        return {'rows': list(qs.order_by('-created_at')[:TAB_LIMIT]), 'total': qs.count(),
                'list_url': _url('psa:project_list')}

    def _tab_activity(self):
        return {
            'items': self.activity(ACTIVITY_LIMIT),
            'audit': self.audit_rows(ACTIVITY_LIMIT) if self.audit_visible() else None,
            'audit_url': _url('audit:audit_log_list') if self.audit_visible() else '',
        }

    def _tab_members(self):
        return {}

    # -- activity ----------------------------------------------------------------

    def activity(self, limit):
        """Recently changed records across the tabs this user may open,
        newest first. Each source is a small ordered slice."""
        if not self.in_context:
            return []
        per = max(limit // 2, PANEL_LIMIT)
        items = []

        def add(rows, kind, icon, title, url, detail=lambda r: ''):
            for r in rows:
                items.append({'kind': kind, 'icon': icon, 'title': title(r), 'url': url(r),
                              'detail': detail(r), 'when': r.updated_at})

        v = self.visible
        if v.get('tickets'):
            add(self.tickets_qs().order_by('-updated_at')[:per], 'Ticket', 'fa-ticket-alt',
                lambda t: f'{t.ticket_number} {t.subject}',
                lambda t: _url('psa:ticket_detail', t.ticket_number),
                lambda t: t.status.name if t.status_id else '')
        if v.get('assets'):
            add(self.assets_qs().order_by('-updated_at')[:per], 'Asset', 'fa-box',
                lambda a: a.name, lambda a: _url('assets:asset_detail', a.pk))
        if v.get('documents'):
            add(self.documents_qs().order_by('-updated_at')[:per], 'Document', 'fa-file-alt',
                lambda d: d.title, lambda d: _url('docs:document_detail', d.slug))
        if v.get('contacts'):
            add(self.contacts_qs().order_by('-updated_at')[:per], 'Contact', 'fa-address-book',
                lambda c: f'{c.first_name} {c.last_name}'.strip(), lambda c: _url('assets:contact_detail', c.pk))
        if v.get('projects'):
            add(self.projects_qs().order_by('-updated_at')[:per], 'Project', 'fa-diagram-project',
                lambda p: p.name, lambda p: _url('psa:project_detail', p.pk),
                lambda p: p.get_status_display())
        if v.get('contracts') and self.psa_on and self.allows('psa:contract_list'):
            add(self.contracts_qs().order_by('-updated_at')[:per], 'Contract', 'fa-file-contract',
                lambda c: c.name, lambda c: _url('psa:contract_detail', c.pk),
                lambda c: c.get_status_display())
        if v.get('billing'):
            add(self.invoices_qs().order_by('-updated_at')[:per], 'Invoice', 'fa-file-invoice',
                lambda i: f'{i.invoice_number} {i.title}', lambda i: _url('psa:invoice_detail', i.pk),
                lambda i: i.get_status_display())
        items.sort(key=lambda i: i['when'] or timezone.now(), reverse=True)
        return items[:limit]

    def audit_rows(self, limit):
        from audit.models import AuditLog
        return list(AuditLog.objects.filter(organization=self.org).order_by('-timestamp')[:limit])

    # -- overview --------------------------------------------------------------

    def overview(self):
        """Counts and a few rows per permitted panel."""
        v = self.visible
        today = timezone.localdate()
        out = {'kpis': []}
        if v['tickets']:
            open_qs = self.open_tickets_qs()
            out['tickets'] = {
                'open_count': open_qs.count(),
                'rows': list(open_qs.order_by('-updated_at')[:PANEL_LIMIT]),
                'unassigned': open_qs.filter(assigned_to__isnull=True).count(),
            }
            out['kpis'].append(('Open tickets', out['tickets']['open_count'], 'tickets', ''))
            out['sla'] = self._sla()
            if out['sla'] is not None:
                out['kpis'].append(('SLA at risk', out['sla']['breached'] + out['sla']['warning'], 'tickets',
                                    'danger' if out['sla']['breached'] else ''))
        if v['assets']:
            out['assets'] = {'count': self.assets_qs().count()}
            out['kpis'].append(('Managed assets', out['assets']['count'], 'assets', ''))
        if v['rmm']:
            counts = self.rmm_qs().aggregate(total=Count('id'), online=Count('id', filter=Q(is_online=True)))
            out['rmm'] = {'total': counts['total'], 'online': counts['online'],
                          'offline': counts['total'] - counts['online']}
            out['kpis'].append(('RMM offline', out['rmm']['offline'], 'rmm',
                                'warn' if out['rmm']['offline'] else ''))
        if v['contacts']:
            qs = self.contacts_qs()
            out['contacts'] = {'count': qs.count(), 'rows': list(qs.order_by('last_name', 'first_name')[:PANEL_LIMIT])}
        if v['documents']:
            out['documents'] = {'count': self.documents_qs().count()}
        if v['passwords']:
            out['passwords'] = {'count': self.passwords_qs().count()}
        if v['contracts'] and self.psa_on and self.allows('psa:contract_list'):
            qs = self.contracts_qs()
            active = qs.filter(status='active')
            out['contracts'] = {
                'active_count': active.count(),
                'renewals': list(active.filter(end_date__isnull=False, end_date__gte=today,
                                               end_date__lte=today + timedelta(days=RENEWAL_WINDOW_DAYS))
                                 .order_by('end_date')[:PANEL_LIMIT]),
                'window': RENEWAL_WINDOW_DAYS,
            }
            out['kpis'].append(('Active contracts', out['contracts']['active_count'], 'contracts', ''))
        if v['billing']:
            open_qs = self.invoices_qs().filter(status__in=OPEN_INVOICE_STATUSES)
            out['invoices'] = {
                'open_count': open_qs.count(),
                'amounts': _balances(open_qs),
                'rows': list(open_qs.order_by('due_date', 'pk')[:PANEL_LIMIT]),
                'today': today,
            }
            out['kpis'].append(('Open invoices', out['invoices']['open_count'], 'billing', ''))
        if v['projects']:
            active = self.projects_qs().filter(status__in=ACTIVE_PROJECT_STATUSES)
            out['projects'] = {'active_count': active.count(),
                               'rows': list(active.select_related('owner').order_by('due_date', '-created_at')[:PANEL_LIMIT])}
            out['kpis'].append(('Active projects', out['projects']['active_count'], 'projects', ''))
        if self.in_context:
            out['activity'] = self.activity(6)
        return out

    def _sla(self):
        """SLA counts from core.customer_ops (its own gate: PSA on and
        tickets_view for this client)."""
        try:
            from core import customer_ops as ops
            section = ops.build_section(self.request, self.org, 'sla')
        except Exception:
            return None
        if section is None:
            return None
        return {'breached': section.danger_count, 'warning': section.warning_count,
                'url': _url('core:customer_ops_section', self.org.pk, 'sla')}

    # -- quick actions -------------------------------------------------------

    def quick_actions(self):
        """Links to the existing create pages, shown only where the page
        would let this user in. The pages check everything again; approval
        steps (quote and invoice approval, document review) stay theirs."""
        if not self.in_context:
            return []
        org, out = self.org, []
        from core.org_handoff import with_org

        try:
            from core.customer_ops import _ticket_create_url
            url = _ticket_create_url(self.user, org) if self.psa_on else ''
        except Exception:
            url = ''
        if url:
            out.append(('Create ticket', url, 'fa-plus'))
        can_write = passes_require_write(self.request)
        if can_write and self.has('assets_create') and self.allows('assets:contact_create'):
            out.append(('Add contact', with_org(_url('assets:contact_create'), org), 'fa-user-plus'))
        if can_write and self.has('assets_create') and self.allows('assets:asset_create'):
            out.append(('Add asset', _url('assets:asset_create'), 'fa-box'))
        if self.visible.get('rmm'):
            out.append(('Open RMM', _url('integrations:rmm_devices'), 'fa-desktop'))
        if self.psa_on and can_write and self.allows('psa:project_create'):
            out.append(('Create project', _url('psa:project_create'), 'fa-diagram-project'))
        if can_write and self.allows('docs:document_create'):
            from docs.permissions import can_create_in_org
            if can_create_in_org(self.user, org):
                out.append(('Add document', with_org(_url('docs:document_create'), org), 'fa-file-circle-plus'))
        if self.psa_on and self.staff and can_write and self.allows('psa:quote_create'):
            from psa.views import _org_perm
            if _org_perm(self.request, org, 'crm_manage_pipeline'):
                out.append(('Create quote', _url('psa:quote_create'), 'fa-file-invoice-dollar'))
        if self.visible.get('contracts'):
            out.append(('View contracts', _url('accounts:organization_detail', org.pk, query='tab=contracts'),
                        'fa-file-contract'))
        return [{'label': label, 'url': url, 'icon': icon} for label, url, icon in out if url]


def _balances(invoice_qs):
    """[(currency, balance)] of the invoices in `invoice_qs`."""
    rows = invoice_qs.values('currency').annotate(total=Sum('total'), paid=Sum('amount_paid')).order_by('currency')
    out = []
    for r in rows:
        bal = (r['total'] or 0) - (r['paid'] or 0)
        if bal:
            out.append((r['currency'], bal))
    return out
