"""Customer operations: one view of what needs attention for one customer.

Five sections, each built from data that already exists elsewhere:

  sla       open PSA tickets whose SLA is breached or close to it
            (psa.sla.status_chip, the same rule as the ticket badge)
  uptime    website monitors that are down or warning, monitors with
            outages in the last 7 days (MonitorCheck history), WAN
            connections that are down or failed checks in that window
            (WANCheck history), active RMM alerts on the customer's
            devices (users holding integrations_view for the customer),
            SSL certificates and domains that have expired or fall inside
            their warning window (website monitors and manual SSL / domain
            expirations), and status-page incidents that are ongoing or
            recent
  renewals  PSA contracts ending within RENEWAL_WINDOW_DAYS, or already
            ended / expired and not renewed (no successor contract)
  invoices  PSA invoices past their due date with a balance left
  assets    warranty expired or expiring, vendor end of support / end of
            life reached or close, and (when asset age warnings are on)
            assets older than the configured critical age

Access is decided per section, per customer, before anything is counted:

  * the customer itself must be one the user may open
    (core.tenancy.accessible_org_ids: MSP staff and superusers reach every
    customer, everyone else their memberships and those customers'
    subsidiaries). Anything else is a 404 in the views;
  * each section needs its module switched on and a role flag *for this
    customer* (accounts.permission_utils.has_perm_for_org), see GATES.
    A section the user may not see is not computed at all, so neither its
    rows nor its totals can leak;
  * customer users (not MSP staff) see only tickets shared with the client
    (psa.visibility.customer_visible_tickets), only published incidents on
    enabled status pages, and no links into staff-only pages (contracts,
    invoice management, status page admin).

Nothing here writes. Every action is a link to an existing page, except
"Send reminder" on an overdue invoice: a POST (core.customer_ops_views.
invoice_reminder) that needs `billing_send_invoices` for the customer, emails
the existing invoice PDF (psa.pdf.email_invoice) to the customer's contact
address and is audit-logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils import timezone

SECTION_ORDER = ('sla', 'uptime', 'renewals', 'invoices', 'assets')

# Role flags. A section is shown when the user holds ANY of its flags for
# the customer (and the module is on).
GATES = {
    'sla': ('tickets_view',),
    'uptime': ('monitoring_view',),
    'renewals': ('billing_view_invoices', 'reports_view_financial'),
    'invoices': ('billing_view_invoices',),
    'assets': ('assets_view',),
}

TITLES = {
    'sla': 'SLA risks',
    'uptime': 'Uptime and expirations',
    'renewals': 'Contract renewals',
    'invoices': 'Overdue invoices',
    'assets': 'Aging assets',
}

ICONS = {
    'sla': 'fa-stopwatch',
    'uptime': 'fa-heart-pulse',
    'renewals': 'fa-file-contract',
    'invoices': 'fa-file-invoice-dollar',
    'assets': 'fa-hourglass-half',
}

RENEWAL_WINDOW_DAYS = 60
RECENTLY_ENDED_DAYS = 90
WARRANTY_WINDOW_DAYS = 90
EOL_WINDOW_DAYS = 180
INCIDENT_LOOKBACK_DAYS = 7
# An SSL certificate or domain this close to expiry is "act now".
EXPIRY_DANGER_DAYS = 7
# A second reminder for the same invoice inside this window is refused.
REMINDER_COOLDOWN_MINUTES = 10

_RMM_SEVERITY = {'critical': 'danger', 'error': 'danger', 'warning': 'warning', 'info': 'info'}

# Rows read per section. The summary shows SUMMARY_LIMIT of them; the
# section page shows them all. A section that hit the cap says so.
SCAN_LIMIT = 500
ASSET_SCAN_LIMIT = 2000
SUMMARY_LIMIT = 10

_SEVERITY_RANK = {'danger': 0, 'warning': 1, 'info': 2}


@dataclass
class Action:
    label: str
    url: str
    icon: str = ''
    method: str = 'get'            # 'post' renders a one-button form


@dataclass
class Item:
    title: str
    detail: str
    severity: str = 'warning'      # danger | warning | info
    when: object = None            # a date/datetime to sort by and show
    actions: list = field(default_factory=list)


@dataclass
class Section:
    key: str
    title: str
    icon: str
    items: list = field(default_factory=list)
    truncated: bool = False
    list_url: str = ''
    list_label: str = ''
    note: str = ''
    amounts: list = field(default_factory=list)   # [(currency, Decimal)]

    @property
    def total(self):
        return len(self.items)

    @property
    def danger_count(self):
        return sum(1 for i in self.items if i.severity == 'danger')

    @property
    def warning_count(self):
        return sum(1 for i in self.items if i.severity == 'warning')

    @property
    def summary_items(self):
        return self.items[:SUMMARY_LIMIT]

    @property
    def more_count(self):
        return max(0, len(self.items) - SUMMARY_LIMIT)


# -- access ------------------------------------------------------------------

def is_msp_staff(user):
    from psa.visibility import is_msp_staff as _is_msp_staff
    return _is_msp_staff(user)


def can_open_customer(request, org):
    """True when the user may open this customer at all."""
    if org is None or not org.is_active:
        return False
    from core.tenancy import accessible_org_ids
    allowed = accessible_org_ids(request)
    return allowed is None or org.pk in allowed


def _has(user, org, *flags):
    from accounts.permission_utils import has_perm_for_org
    return any(has_perm_for_org(user, org, f) for f in flags)


def _settings():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def module_on(key, settings=None):
    """Whether the module behind a section is switched on."""
    settings = settings or _settings()
    if key in ('sla', 'renewals', 'invoices'):
        return bool(settings.psa_enabled)
    if key == 'uptime':
        return bool(settings.monitoring_enabled)
    return True  # assets are core


def visible_sections(user, org, settings=None):
    """Section keys this user may see for this customer, in display order."""
    settings = settings or _settings()
    return [k for k in SECTION_ORDER
            if module_on(k, settings) and _has(user, org, *GATES[k])]


def _url(name, *args, query=''):
    try:
        url = reverse(name, args=args)
    except Exception:
        return ''
    return url + (('?' + query) if query else '')


def _ticket_create_url(user, org, **params):
    """A prefilled new-ticket link, or '' when the user can't file one here."""
    from urllib.parse import urlencode
    from psa.feature_flags import is_psa_enabled_for_client
    if not (is_psa_enabled_for_client(org) and _has(user, org, 'tickets_create')):
        return ''
    return _url('psa:ticket_create', query=urlencode({'client': org.pk, **params}))


def _sorted(items):
    def key(i):
        when = i.when
        if when is None:
            stamp = float('inf')
        elif isinstance(when, datetime):
            stamp = when.timestamp()
        elif isinstance(when, date):
            stamp = datetime.combine(when, time.min).timestamp()
        else:
            stamp = float('inf')
        return (_SEVERITY_RANK.get(i.severity, 9), stamp)
    return sorted(items, key=key)


# -- sections ----------------------------------------------------------------

def sla_section(request, org, now=None):
    from psa import sla
    from psa.models import Ticket
    from psa.visibility import customer_visible_tickets

    now = now or timezone.now()
    user = request.user
    qs = (Ticket.objects
          .filter(organization=org, resolved_at__isnull=True, status__is_terminal=False)
          .filter(Q(resolution_due_at__isnull=False) | Q(first_response_due_at__isnull=False))
          .select_related('status', 'priority', 'assigned_to')
          .order_by('resolution_due_at'))
    qs = customer_visible_tickets(qs, user)
    rows = list(qs[:SCAN_LIMIT + 1])
    section = Section('sla', TITLES['sla'], ICONS['sla'],
                      truncated=len(rows) > SCAN_LIMIT,
                      list_url=_url('psa:ticket_list'), list_label='All tickets')
    for t in rows[:SCAN_LIMIT]:
        chip = sla.status_chip(t, now=now)
        if chip['kind'] not in ('breached', 'warning'):
            continue
        assignee = t.assigned_to.get_username() if t.assigned_to_id else 'Unassigned'
        section.items.append(Item(
            title=f'{t.ticket_number} {t.subject}',
            detail=f"{chip['label']} · {t.priority.name} · {assignee}",
            severity='danger' if chip['kind'] == 'breached' else 'warning',
            when=t.resolution_due_at or t.first_response_due_at,
            actions=[Action('Open ticket', _url('psa:ticket_detail', t.ticket_number),
                            'fa-ticket-alt')],
        ))
    section.items = _sorted(section.items)
    return section


def uptime_section(request, org, now=None):
    from monitoring.models import MonitorCheck, WebsiteMonitor
    from statuspage.models import StatusPageIncident

    now = now or timezone.now()
    user = request.user
    staff = is_msp_staff(user)
    since = now - timedelta(days=INCIDENT_LOOKBACK_DAYS)
    section = Section('uptime', TITLES['uptime'], ICONS['uptime'],
                      list_url=_url('monitoring:website_monitor_list'),
                      list_label='All monitors')

    current = list(WebsiteMonitor.objects
                   .filter(organization=org, is_enabled=True, status__in=('down', 'warning'))
                   .order_by('name')[:SCAN_LIMIT])
    current_ids = {m.pk for m in current}
    for m in current:
        actions = [Action('Open monitor', _url('monitoring:website_monitor_detail', m.pk), 'fa-globe')]
        ticket_url = _ticket_create_url(user, org, subject=f'Monitor {m.status}: {m.name}'[:200])
        if ticket_url:
            actions.append(Action('Open ticket', ticket_url, 'fa-plus'))
        code = f' (HTTP {m.last_status_code})' if m.last_status_code else ''
        section.items.append(Item(
            title=m.name,
            detail=f'{m.get_status_display()} now{code} · {m.url}',
            severity='danger' if m.status == 'down' else 'warning',
            when=m.last_checked_at,
            actions=actions,
        ))

    # Monitors that are fine now but went down in the lookback window.
    recent = (MonitorCheck.objects
              .filter(monitor__organization=org, monitor__is_enabled=True,
                      status='down', checked_at__gte=since)
              .exclude(monitor_id__in=current_ids)
              .values('monitor_id', 'monitor__name')
              .annotate(n=Count('id'), last=Max('checked_at'))
              .order_by('-last')[:SCAN_LIMIT])
    for row in recent:
        section.items.append(Item(
            title=row['monitor__name'],
            detail=f"Recovered · {row['n']} failed check(s) in the last {INCIDENT_LOOKBACK_DAYS} days",
            severity='info',
            when=row['last'],
            actions=[Action('Open monitor', _url('monitoring:website_monitor_detail', row['monitor_id']),
                            'fa-globe')],
        ))

    _wan_items(section, user, org, staff, since)
    if staff or _has(user, org, 'integrations_view'):
        _rmm_alert_items(section, user, org, staff)
    _expiry_items(section, org, staff, now)

    incidents = (StatusPageIncident.objects
                 .filter(page__organization=org)
                 .filter(Q(resolved_at__isnull=True) | Q(started_at__gte=since))
                 .select_related('page', 'ticket')
                 .order_by('-started_at'))
    if not staff:
        incidents = incidents.filter(is_published=True, page__is_enabled=True)
    for inc in incidents[:SCAN_LIMIT]:
        actions = []
        if staff:
            actions.append(Action('Open status page', _url('statuspage:detail', inc.page_id), 'fa-heart-pulse'))
        if inc.ticket_id and inc.ticket.organization_id == org.pk and _has(user, org, 'tickets_view'):
            from psa.visibility import customer_visible_tickets
            if customer_visible_tickets(type(inc.ticket).objects.filter(pk=inc.ticket_id), user).exists():
                actions.append(Action('Open ticket', _url('psa:ticket_detail', inc.ticket.ticket_number),
                                      'fa-ticket-alt'))
        section.items.append(Item(
            title=inc.title,
            detail=('Ongoing' if not inc.is_resolved else 'Resolved') + f' · {inc.page.title}',
            severity='danger' if not inc.is_resolved else 'info',
            when=inc.started_at,
            actions=actions,
        ))
    section.items = _sorted(section.items)
    return section


def _wan_items(section, user, org, staff, since):
    """WAN connections down now (status or the check's alert state), and
    monitored ones that answered again after failed checks in the window."""
    from locations.models import WAN, WANCheck

    down = list(WAN.objects
                .filter(organization=org)
                .filter(Q(status='down') | Q(monitoring_enabled=True, alert_state='down'))
                .select_related('location')
                .order_by('name')[:SCAN_LIMIT])
    down_ids = {w.pk for w in down}
    for w in down:
        actions = [Action('Open WAN', _url('locations:wan_detail', w.location_id, w.pk), 'fa-network-wired')]
        ticket_url = _ticket_create_url(user, org, subject=f'WAN down: {w.name}'[:200])
        if ticket_url:
            actions.append(Action('Open ticket', ticket_url, 'fa-plus'))
        bits = ['Down now', w.isp_name, getattr(w.location, 'name', '')]
        section.items.append(Item(
            title=f'WAN {w.name}',
            detail=' · '.join(b for b in bits if b),
            severity='danger', when=w.last_down_at or w.last_checked_at, actions=actions))

    recent = (WANCheck.objects
              .filter(wan__organization=org, wan__monitoring_enabled=True,
                      result='down', checked_at__gte=since)
              .exclude(wan_id__in=down_ids)
              .values('wan_id', 'wan__name', 'wan__location_id')
              .annotate(n=Count('id'), last=Max('checked_at'))
              .order_by('-last')[:SCAN_LIMIT])
    for row in recent:
        section.items.append(Item(
            title=f"WAN {row['wan__name']}",
            detail=f"Recovered · {row['n']} failed check(s) in the last {INCIDENT_LOOKBACK_DAYS} days",
            severity='info', when=row['last'],
            actions=[Action('Open WAN', _url('locations:wan_detail', row['wan__location_id'], row['wan_id']),
                            'fa-network-wired')]))


def _rmm_alert_items(section, user, org, staff):
    """Active RMM alerts on this customer's devices. Scoped the way the RMM
    alerts page scopes them: by the device's customer, resolved devices
    only (an unowned device's alerts belong to no one)."""
    from integrations.models import RMMAlert, RMMDevice

    alerts = (RMMAlert.objects
              .filter(device__organization=org, device__ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
                      status='active')
              .select_related('device')
              .order_by('-triggered_at')[:SCAN_LIMIT])
    for a in alerts:
        actions = []
        if staff:
            actions.append(Action('RMM alerts', _url('integrations:rmm_alerts'), 'fa-bell'))
        ticket_url = _ticket_create_url(user, org, subject=f'RMM alert: {a.device.device_name} {a.alert_type}'[:200])
        if ticket_url:
            actions.append(Action('Open ticket', ticket_url, 'fa-plus'))
        message = (a.message or '').strip().splitlines()[0][:160] if a.message else ''
        section.items.append(Item(
            title=f'{a.device.device_name}: {a.alert_type}'[:200],
            detail=' · '.join(b for b in (f'RMM {a.get_severity_display()}', message) if b),
            severity=_RMM_SEVERITY.get(a.severity, 'info'), when=a.triggered_at, actions=actions))


def _expiry_severity(days):
    return 'danger' if days < 0 or days <= EXPIRY_DANGER_DAYS else 'warning'


def _expiry_detail(label, when, days):
    if days < 0:
        return f'{label} expired {when:%Y-%m-%d}'
    return f'{label} expires in {days} day(s) ({when:%Y-%m-%d})'


def _expiry_items(section, org, staff, now):
    """SSL certificates and domains past expiry or inside their warning
    window: from website monitors (checked automatically) and from manual
    SSL / domain expirations (Monitoring → Expirations)."""
    from monitoring.models import Expiration, WebsiteMonitor

    monitors = (WebsiteMonitor.objects
                .filter(organization=org, is_enabled=True)
                .filter(Q(ssl_expires_at__isnull=False) | Q(domain_expires_at__isnull=False))
                .order_by('name')[:SCAN_LIMIT])
    for m in monitors:
        for label, when, warn in (('SSL certificate', m.ssl_expires_at, m.ssl_warning_days),
                                  ('Domain', m.domain_expires_at, m.domain_warning_days)):
            if when is None or when > now + timedelta(days=warn or 0):
                continue
            days = (when - now).days
            section.items.append(Item(
                title=m.name, detail=f'{_expiry_detail(label, when, days)} · {m.url}',
                severity=_expiry_severity(days), when=when,
                actions=[Action('Open monitor', _url('monitoring:website_monitor_detail', m.pk), 'fa-globe')]))

    labels = dict(Expiration.EXPIRATION_TYPES)
    for e in (Expiration.objects
              .filter(organization=org, expiration_type__in=('ssl_cert', 'domain'))
              .order_by('expires_at')[:SCAN_LIMIT]):
        if e.expires_at > now + timedelta(days=e.warning_days or 0):
            continue
        days = (e.expires_at - now).days
        detail = _expiry_detail(labels.get(e.expiration_type, 'Item'), e.expires_at, days)
        if e.auto_renew:
            detail += ' · auto-renews'
        actions = []
        if staff:
            actions.append(Action('Edit expiration', _url('monitoring:expiration_edit', e.pk), 'fa-calendar'))
        section.items.append(Item(
            title=e.name, detail=detail,
            severity='info' if (e.auto_renew and days >= 0) else _expiry_severity(days),
            when=e.expires_at, actions=actions))


def renewals_section(request, org, today=None):
    from psa.models import Contract

    today = today or timezone.localdate()
    staff = is_msp_staff(request.user)
    horizon = today + timedelta(days=RENEWAL_WINDOW_DAYS)
    ended_since = today - timedelta(days=RECENTLY_ENDED_DAYS)
    qs = (Contract.objects
          .filter(client_org=org, end_date__isnull=False)
          .filter(Q(status='active', end_date__lte=horizon)
                  | Q(status='expired', end_date__gte=ended_since))
          .annotate(n_renewals=Count('renewals'))
          .filter(n_renewals=0)
          .order_by('end_date'))
    rows = list(qs[:SCAN_LIMIT + 1])
    section = Section('renewals', TITLES['renewals'], ICONS['renewals'],
                      truncated=len(rows) > SCAN_LIMIT,
                      list_url=_url('psa:contract_list') if staff else '',
                      list_label='All contracts')
    for c in rows[:SCAN_LIMIT]:
        days = (c.end_date - today).days
        if days < 0:
            detail, severity = f'Ended {-days} day(s) ago ({c.end_date:%Y-%m-%d}), not renewed', 'danger'
        else:
            detail = f'Ends in {days} day(s) ({c.end_date:%Y-%m-%d})'
            severity = 'warning' if days <= 30 else 'info'
        if c.auto_renew and c.status == 'active':
            detail += ' · auto-renews'
            severity = 'info'
        actions = []
        if staff:
            actions = [Action('Open contract', _url('psa:contract_detail', c.pk), 'fa-file-contract'),
                       Action('Renew / edit', _url('psa:contract_edit', c.pk), 'fa-rotate')]
        section.items.append(Item(
            title=c.name, detail=f'{c.get_contract_type_display()} · {detail}',
            severity=severity, when=c.end_date, actions=actions))
    section.items = _sorted(section.items)
    return section


def overdue_invoices(org, today=None):
    """This customer's invoices that are past due (or marked overdue) and
    not draft, paid or void. A balance check is left to the caller."""
    from psa.models import Invoice
    today = today or timezone.localdate()
    return (Invoice.objects
            .filter(client_org=org)
            .exclude(status__in=('draft', 'paid', 'void'))
            .filter(Q(status='overdue') | Q(due_date__lt=today)))


def can_send_reminders(user, org):
    return is_msp_staff(user) and _has(user, org, 'billing_send_invoices')


def invoices_section(request, org, today=None):
    today = today or timezone.localdate()
    user = request.user
    staff = is_msp_staff(user)
    can_send = can_send_reminders(user, org)
    qs = overdue_invoices(org, today).order_by('due_date', 'pk')
    rows = list(qs[:SCAN_LIMIT + 1])
    section = Section('invoices', TITLES['invoices'], ICONS['invoices'],
                      truncated=len(rows) > SCAN_LIMIT,
                      list_url=_url('psa:invoice_list', query='status=overdue') if staff else '',
                      list_label='Overdue invoices')
    totals = {}
    for inv in rows[:SCAN_LIMIT]:
        balance = (inv.total or Decimal('0')) - (inv.amount_paid or Decimal('0'))
        if balance <= 0:
            continue
        totals[inv.currency] = totals.get(inv.currency, Decimal('0')) + balance
        days = (today - inv.due_date).days if inv.due_date else None
        overdue = f'{days} day(s) overdue' if days is not None and days > 0 else 'Overdue'
        actions = []
        if staff:
            actions.append(Action('Open invoice', _url('psa:invoice_detail', inv.pk), 'fa-file-invoice'))
            if can_send:
                actions.append(Action('Send reminder', _url('core:customer_ops_invoice_reminder', org.pk, inv.pk),
                                      'fa-envelope', method='post'))
        section.items.append(Item(
            title=f'{inv.invoice_number} {inv.title}',
            detail=f'{overdue} · balance {inv.currency} {balance:,.2f}',
            severity='danger' if days is not None and days > 30 else 'warning',
            when=inv.due_date, actions=actions))
    section.items = _sorted(section.items)
    section.amounts = sorted(totals.items())
    return section


def assets_section(request, org, today=None, settings=None):
    from assets.models import Asset

    today = today or timezone.localdate()
    settings = settings or _settings()
    user = request.user
    age_on = bool(settings.asset_age_warnings_enabled)
    critical_years = settings.asset_age_critical_years or 5
    q = (Q(warranty_expiry__isnull=False) | Q(vendor_end_of_life__isnull=False)
         | Q(vendor_end_of_support__isnull=False)
         | Q(purchase_date__isnull=False, lifespan_years__isnull=False))
    if age_on:
        q |= Q(purchase_date__isnull=False)
    rows = list(Asset.objects.filter(organization=org).filter(q).order_by('name')[:ASSET_SCAN_LIMIT + 1])
    section = Section('assets', TITLES['assets'], ICONS['assets'],
                      truncated=len(rows) > ASSET_SCAN_LIMIT,
                      list_url=_url('assets:asset_list'), list_label='All assets')
    if not age_on:
        section.note = 'Age-based warnings are off (Settings → Optional modules → Asset age warnings).'
    for a in rows[:ASSET_SCAN_LIMIT]:
        reasons, severity, when = [], None, None

        def flag(text, sev, date):
            nonlocal severity, when
            reasons.append(text)
            if severity is None or _SEVERITY_RANK[sev] < _SEVERITY_RANK[severity]:
                severity = sev
            if date is not None and (when is None or date < when):
                when = date

        if a.warranty_expiry:
            days = (a.warranty_expiry - today).days
            if days < 0:
                flag(f'Warranty expired {a.warranty_expiry:%Y-%m-%d}', 'danger', a.warranty_expiry)
            elif days <= WARRANTY_WINDOW_DAYS:
                flag(f'Warranty ends in {days} day(s)', 'warning', a.warranty_expiry)
        if a.vendor_end_of_support and a.vendor_end_of_support < today:
            flag(f'Out of vendor support since {a.vendor_end_of_support:%Y-%m-%d}', 'danger',
                 a.vendor_end_of_support)
        eol = a.get_end_of_life_date()
        if eol:
            days = (eol - today).days
            label = 'End of life' if a.vendor_end_of_life else 'Estimated end of life'
            if days < 0:
                flag(f'{label} {eol:%Y-%m-%d} (passed)', 'danger', eol)
            elif days <= EOL_WINDOW_DAYS:
                flag(f'{label} in {days} day(s)', 'warning', eol)
        elif age_on and a.purchase_date:
            age = a.get_age_years()
            if age is not None and age >= critical_years:
                flag(f'{age:.1f} years old (critical age {critical_years})', 'warning', a.purchase_date)
        if not reasons:
            continue
        actions = [Action('Open asset', _url('assets:asset_detail', a.pk), 'fa-box')]
        ticket_url = _ticket_create_url(user, org, asset=a.pk,
                                        subject=f'Plan replacement: {a.name}'[:200])
        if ticket_url:
            actions.append(Action('Plan replacement', ticket_url, 'fa-clipboard-list'))
        section.items.append(Item(
            title=a.name, detail=' · '.join(reasons), severity=severity, when=when, actions=actions))
    section.items = _sorted(section.items)
    return section


BUILDERS = {
    'sla': sla_section,
    'uptime': uptime_section,
    'renewals': renewals_section,
    'invoices': invoices_section,
    'assets': assets_section,
}


def build_section(request, org, key):
    """One section, or None when this user may not see it for this customer."""
    if key not in BUILDERS or key not in visible_sections(request.user, org):
        return None
    return BUILDERS[key](request, org)


def build(request, org):
    """Every section the user may see for this customer, in display order."""
    return [BUILDERS[k](request, org) for k in visible_sections(request.user, org)]
