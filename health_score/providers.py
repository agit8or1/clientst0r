"""Built-in signal providers. Each answers for one client organization and
only reads rows belonging to it. A dimension whose source is not installed or
not configured answers `unknown` (never ok)."""
from __future__ import annotations

from datetime import timedelta

from django.apps import apps
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from .registry import Context, ref, result, signal, unknown

MIN_SAMPLE = 3          # tickets / responses needed before a rate means anything
MAX_LIST = 25


def _url(name, *args, **kwargs):
    try:
        return reverse(name, args=args, kwargs=kwargs or None)
    except NoReverseMatch:
        return ''


def _latest(*values):
    values = [v for v in values if v is not None]
    return max(values) if values else None


def _installed(app_label):
    return apps.is_installed(app_label)


# ---------------------------------------------------------------- technical

def _rmm_devices(ctx):
    from integrations.models import RMMDevice
    return list(RMMDevice.objects.filter(organization=ctx.client,
                                         ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
                .select_related('connection'))


def _device_states(ctx):
    from integrations.rmm_association import device_status
    devices = _rmm_devices(ctx)
    return devices, [(d, device_status(d, ctx.now)['state']) for d in devices]


def _device_ref(d, note=''):
    label = d.device_name + (f' ({note})' if note else '')
    return ref(d, label, _url('integrations:rmm_device_detail', d.pk))


@signal('technical', 'rmm_online', 'Devices online', weight=2,
        description='Share of RMM devices reporting online, counting only devices with a fresh check-in.')
def rmm_online(ctx: Context):
    devices, states = _device_states(ctx)
    src = 'RMM sync'
    if not devices:
        return unknown('No RMM devices are synced for this client, so device health is not measured.', src)
    fresh = [(d, s) for d, s in states if s in ('online', 'offline')]
    stale = [d for d, s in states if s == 'stale']
    as_of = _latest(*[d.data_refreshed_at for d in devices])
    if not fresh:
        if stale:
            return unknown(f'All {len(stale)} RMM device(s) are past their stale threshold; their '
                           'status cannot be trusted.', src, status='stale', as_of=as_of,
                           refs=[_device_ref(d, 'stale') for d in stale[:MAX_LIST]])
        return unknown('No RMM device has been refreshed yet.', src, as_of=as_of)
    online = sum(1 for _d, s in fresh if s == 'online')
    value = 100.0 * online / len(fresh)
    offline = [d for d, s in fresh if s == 'offline']
    text = f'{online} of {len(fresh)} devices with a fresh check-in are online.'
    if stale:
        text += f' {len(stale)} stale device(s) are not counted.'
    return result(value, ctx.grade(value), as_of, src, [_device_ref(d, 'offline') for d in offline[:MAX_LIST]], text)


@signal('technical', 'rmm_checkin', 'Fresh check-ins', weight=1,
        description='Share of RMM devices that checked in within their connection stale threshold.')
def rmm_checkin(ctx: Context):
    devices, states = _device_states(ctx)
    src = 'RMM sync'
    if not devices:
        return unknown('No RMM devices are synced for this client.', src)
    fresh = [d for d, s in states if s in ('online', 'offline')]
    behind = [d for d, s in states if s in ('stale', 'unknown')]
    as_of = _latest(*[d.data_refreshed_at for d in devices])
    if not fresh:
        return unknown('No device has a fresh check-in.', src, status='stale' if any(
            s == 'stale' for _d, s in states) else 'unknown', as_of=as_of,
            refs=[_device_ref(d, 'no fresh check-in') for d in behind[:MAX_LIST]])
    value = 100.0 * len(fresh) / len(devices)
    return result(value, ctx.grade(value), as_of, src, [_device_ref(d, 'no fresh check-in') for d in behind[:MAX_LIST]],
                  f'{len(fresh)} of {len(devices)} devices checked in recently.')


@signal('technical', 'rmm_alerts', 'Disk / patch / health warnings', weight=1,
        description='Open RMM alerts (disk space, patching, health) weighted by severity.')
def rmm_alerts(ctx: Context):
    from integrations.models import RMMAlert
    devices, states = _device_states(ctx)
    src = 'RMM alerts'
    if not devices:
        return unknown('No RMM devices are synced for this client.', src)
    if not any(s in ('online', 'offline') for _d, s in states):
        return unknown('Every RMM device is stale, so open alerts cannot be trusted.', src, status='stale')
    alerts = list(RMMAlert.objects.filter(organization=ctx.client, status__in=('active', 'acknowledged'))
                  .select_related('device').order_by('-triggered_at'))
    penalty = {'critical': 30, 'error': 15, 'warning': 5}
    total = sum(penalty.get(a.severity, 0) for a in alerts)
    value = max(0.0, 100.0 - total)
    refs = [ref(a, f'{a.device.device_name}: {a.alert_type}', _url('integrations:rmm_device_detail', a.device_id))
            for a in alerts if penalty.get(a.severity)][:MAX_LIST]
    text = (f'{len(alerts)} open RMM alert(s).' if alerts else 'No open RMM alerts.')
    return result(value, ctx.grade(value), _latest(*[a.last_synced_at for a in alerts]) or _latest(
        *[d.data_refreshed_at for d in devices]), src, refs, text)


# ----------------------------------------------------------------- security

def _alert_q(client):
    return Q(client_org=client) | Q(organization=client, client_org__isnull=True)


@signal('security', 'security_alerts', 'Open security alerts', weight=2,
        description='Unresolved EDR / AV / firewall alerts by severity.')
def security_alerts(ctx: Context):
    from security_alerts.models import SecurityAlert, SecurityVendorConnection
    src = 'Security alerts'
    conns = list(SecurityVendorConnection.objects.filter(
        Q(client_org=ctx.client) | Q(organization=ctx.client), is_active=True))
    alerts_all = SecurityAlert.objects.filter(_alert_q(ctx.client))
    if not conns and not alerts_all.exists():
        return unknown('No security vendor connection or alert exists for this client, so security is not measured.', src)
    polled = [c for c in conns if c.sync_enabled]
    if conns and len(polled) == len(conns) and not alerts_all.exists():
        newest = _latest(*[c.last_sync_at for c in polled])
        if newest is None or ctx.now - newest > timedelta(days=2):
            return unknown('The security vendor connection(s) have not synced recently.', src,
                           status='stale', as_of=newest)
    open_alerts = list(alerts_all.filter(status__in=('new', 'acknowledged'))
                       .exclude(severity='info').order_by('-seen_at'))
    penalty = {'critical': 30, 'high': 18, 'medium': 6, 'low': 2}
    value = max(0.0, 100.0 - sum(penalty.get(a.severity, 0) for a in open_alerts))
    refs = [ref(a, f'{a.get_severity_display()}: {a.title}', _url('security_alerts:alert_detail', a.pk))
            for a in sorted(open_alerts, key=lambda a: -penalty.get(a.severity, 0))][:MAX_LIST]
    text = (f'{len(open_alerts)} unresolved alert(s), worst severity {open_alerts[0].severity}.'
            if open_alerts else 'No unresolved security alerts.')
    if open_alerts:
        worst = max(open_alerts, key=lambda a: penalty.get(a.severity, 0))
        text = f'{len(open_alerts)} unresolved alert(s), worst severity {worst.severity}.'
    return result(value, ctx.grade(value), _latest(*[a.seen_at for a in alerts_all.order_by('-seen_at')[:1]]),
                  src, refs, text)


@signal('security', 'security_incidents', 'Open security incidents', weight=2,
        description='Security incidents that are not resolved or closed, by severity.')
def security_incidents(ctx: Context):
    from security_alerts.models import SecurityAlert, SecurityIncident, SecurityVendorConnection
    src = 'Security incidents'
    qs = SecurityIncident.objects.filter(Q(client_org=ctx.client) | Q(organization=ctx.client, client_org__isnull=True))
    configured = (qs.exists() or SecurityAlert.objects.filter(_alert_q(ctx.client)).exists()
                  or SecurityVendorConnection.objects.filter(
                      Q(client_org=ctx.client) | Q(organization=ctx.client), is_active=True).exists())
    if not configured:
        return unknown('No security monitoring is configured for this client.', src)
    open_inc = list(qs.exclude(status__in=('resolved', 'closed')).order_by('-opened_at'))
    penalty = {'critical': 40, 'high': 25, 'medium': 10, 'low': 3}
    value = max(0.0, 100.0 - sum(penalty.get(i.severity, 0) for i in open_inc))
    refs = [ref(i, f'{i.get_severity_display()}: {i.title}', _url('security_alerts:incident_detail', i.pk))
            for i in open_inc][:MAX_LIST]
    return result(value, ctx.grade(value), _latest(*[i.opened_at for i in qs.order_by('-opened_at')[:1]]), src, refs,
                  f'{len(open_inc)} open incident(s).' if open_inc else 'No open security incidents.')


# ------------------------------------------------------------------- backup

def _backup_models():
    if not _installed('backup_monitoring'):
        return None
    try:
        return (apps.get_model('backup_monitoring', 'BackupJob'),
                apps.get_model('backup_monitoring', 'RestoreTest'))
    except LookupError:
        return None


BACKUP_STALE_POLL = timedelta(minutes=120)


def evaluate_backup(jobs, now, missed_hours=26):
    """Pure scoring of backup jobs. `jobs`: iterables of objects with name,
    last_run_at, last_status, last_success_at, expected_interval_hours and
    `fresh` (bool: the connection reported recently). Returns
    (value or None, status, issues[(job, why)])."""
    jobs = list(jobs)
    if not jobs:
        return None, 'unknown', []
    scored, issues, stale = [], [], 0
    for j in jobs:
        if not getattr(j, 'fresh', True):
            stale += 1
            issues.append((j, 'stale: its connection has not reported recently'))
            continue
        if j.last_run_at is None:
            issues.append((j, 'never reported'))
            continue
        limit = timedelta(hours=j.expected_interval_hours or missed_hours)
        if j.last_status == 'failed':
            scored.append(0.0)
            issues.append((j, 'last run failed'))
        elif j.last_success_at is None or now - j.last_success_at > limit:
            scored.append(10.0)
            issues.append((j, 'no successful run within the expected interval'))
        elif j.last_status == 'warning':
            scored.append(75.0)
            issues.append((j, 'last run finished with warnings'))
        else:
            scored.append(100.0)
    if not scored:
        return None, ('stale' if stale else 'unknown'), issues
    return sum(scored) / len(scored), 'scored', issues


@signal('backup', 'backup_jobs', 'Backup jobs', weight=3,
        description='Last successful backup age and failures per protected job (needs Backup monitoring).')
def backup_jobs(ctx: Context):
    models = _backup_models()
    src = 'Backup monitoring'
    if models is None:
        return unknown('Backup monitoring is not installed, so backup health is not measured.', src)
    BackupJob, _RestoreTest = models
    jobs = list(BackupJob.objects.filter(organization=ctx.client).select_related('connection'))
    if not jobs:
        return unknown('No backup jobs are monitored for this client.', src)
    for j in jobs:
        c = j.connection
        j.fresh = bool(c.active and c.last_poll_at and (
            getattr(c, 'is_push', False) or (c.last_poll_status != 'error' and ctx.now - c.last_poll_at <= BACKUP_STALE_POLL)))
    value, state, issues = evaluate_backup(jobs, ctx.now)
    as_of = _latest(*[j.last_run_at for j in jobs])
    refs = [ref(j, f'{j.name}: {why}') for j, why in issues][:MAX_LIST]
    if state != 'scored':
        return unknown('Backup data is stale or has not reported yet.', src, status=state, as_of=as_of, refs=refs)
    return result(value, ctx.grade(value), as_of, src, refs,
                  f'{len(issues)} of {len(jobs)} backup job(s) need attention.' if issues
                  else f'All {len(jobs)} backup job(s) succeeded on schedule.')


RESTORE_OK_DAYS = 180


@signal('backup', 'restore_tests', 'Restore tests', weight=1,
        description='Recency and result of the latest restore test (needs Backup monitoring).')
def restore_tests(ctx: Context):
    models = _backup_models()
    src = 'Restore tests'
    if models is None:
        return unknown('Backup monitoring is not installed, so restore tests are not measured.', src)
    _Job, RestoreTest = models
    last = RestoreTest.objects.filter(organization=ctx.client).order_by('-tested_on').first()
    if last is None:
        return unknown('No restore test has been recorded for this client.', src)
    age = (ctx.today - last.tested_on).days
    if last.result == 'failed':
        value = 10.0
    else:
        value = 100.0 if last.result == 'passed' else 70.0
        if age > RESTORE_OK_DAYS:
            value = max(0.0, value - min(60.0, (age - RESTORE_OK_DAYS) / 3.0))
    return result(value, ctx.grade(value), last.tested_on, src,
                  [ref(last, f'{last.system_name or "restore test"} on {last.tested_on}: {last.result}')],
                  f'Last restore test {age} day(s) ago: {last.result}.')


# --------------------------------------------------------- service delivery

def _ticket_url(t):
    return _url('psa:ticket_detail', ticket_number=t.ticket_number)


def _tickets(ctx):
    from psa.models import Ticket
    return Ticket.objects.filter(organization=ctx.client)


@signal('service_delivery', 'sla_attainment', 'SLA attainment (90 days)', weight=3,
        description='Share of tickets closed in the last 90 days that met their resolution SLA.')
def sla_attainment(ctx: Context):
    src = 'Tickets'
    since = ctx.now - timedelta(days=90)
    closed = list(_tickets(ctx).filter(closed_at__gte=since, resolution_due_at__isnull=False))
    if len(closed) < MIN_SAMPLE:
        return unknown(f'Only {len(closed)} SLA-tracked ticket(s) were closed in 90 days; at least '
                       f'{MIN_SAMPLE} are needed.', src)
    missed = [t for t in closed if t.sla_breached_resolution]
    value = 100.0 * (len(closed) - len(missed)) / len(closed)
    return result(value, ctx.grade(value), _latest(*[t.closed_at for t in closed]), src,
                  [ref(t, f'{t.ticket_number} {t.subject}', _ticket_url(t)) for t in missed][:MAX_LIST],
                  f'{len(closed) - len(missed)} of {len(closed)} tickets met their resolution SLA.')


@signal('service_delivery', 'ticket_volume', 'Ticket volume vs baseline', weight=1,
        description='Tickets opened in the last 30 days compared with the monthly average of the 90 days before.')
def ticket_volume(ctx: Context):
    src = 'Tickets'
    now = ctx.now
    recent = _tickets(ctx).filter(created_at__gte=now - timedelta(days=30))
    base_n = _tickets(ctx).filter(created_at__gte=now - timedelta(days=120),
                                  created_at__lt=now - timedelta(days=30)).count()
    if base_n < MIN_SAMPLE:
        return unknown(f'Only {base_n} ticket(s) in the 90-day baseline; at least {MIN_SAMPLE} are needed '
                       'for a trend.', src)
    baseline = base_n / 3.0
    n = recent.count()
    ratio = n / baseline
    value = 100.0 if ratio <= 1.25 else max(0.0, 100.0 - (ratio - 1.25) * 100.0 / 1.75)
    newest = list(recent.order_by('-created_at')[:MAX_LIST])
    return result(value, ctx.grade(value), _latest(*[t.created_at for t in newest]), src,
                  [ref(t, f'{t.ticket_number} {t.subject}', _ticket_url(t)) for t in newest] if ratio > 1.25 else [],
                  f'{n} ticket(s) in the last 30 days against a baseline of {baseline:.1f} per 30 days.')


@signal('service_delivery', 'reopen_rate', 'Reopen rate (90 days)', weight=1,
        description='Closed tickets that were reopened in the last 90 days.')
def reopen_rate(ctx: Context):
    from psa.models import TicketComment
    src = 'Tickets'
    since = ctx.now - timedelta(days=90)
    closed_n = _tickets(ctx).filter(closed_at__gte=since).count()
    reopened = list(TicketComment.objects.filter(ticket__organization=ctx.client, is_system=True,
                                                 body__startswith='Reopened', created_at__gte=since)
                    .select_related('ticket').order_by('-created_at'))
    # A ticket reopened and since closed again counts in closed_n too; guard the denominator.
    denom = max(closed_n, len({c.ticket_id for c in reopened}))
    if denom < MIN_SAMPLE:
        return unknown(f'Only {denom} closed ticket(s) in 90 days; at least {MIN_SAMPLE} are needed.', src)
    tickets = {}
    for c in reopened:
        tickets.setdefault(c.ticket_id, c.ticket)
    rate = len(tickets) / denom
    value = max(0.0, 100.0 - rate * 400.0)     # 25% reopened scores 0
    return result(value, ctx.grade(value), _latest(*[c.created_at for c in reopened[:1]]) , src,
                  [ref(t, f'{t.ticket_number} {t.subject}', _ticket_url(t)) for t in tickets.values()][:MAX_LIST],
                  f'{len(tickets)} of {denom} closed ticket(s) were reopened ({rate:.0%}).')


# --------------------------------------------------------------- commercial

OPEN_INVOICE = ('sent', 'partial', 'overdue')
RENEWAL_WINDOW_DAYS = 60


@signal('commercial', 'overdue_invoices', 'Overdue invoices', weight=2,
        description='Unpaid invoices past their due date, weighted by days late and amount.')
def overdue_invoices(ctx: Context):
    from psa.models import Invoice
    src = 'Invoices'
    qs = Invoice.objects.filter(Q(organization=ctx.client) | Q(client_org=ctx.client)).exclude(status__in=('draft', 'void'))
    if not qs.exists():
        return unknown('No invoices exist for this client.', src)
    today = ctx.today
    late = []
    for inv in qs.filter(status__in=OPEN_INVOICE, due_date__lt=today).order_by('due_date'):
        due = (inv.total or 0) - (inv.amount_paid or 0)
        if due > 0:
            late.append((inv, (today - inv.due_date).days, due))
    penalty = sum(10 if d <= 30 else 25 if d <= 60 else 40 for _i, d, _a in late)
    value = max(0.0, 100.0 - penalty)
    refs = [ref(i, f'{i.invoice_number}: {a:.2f} {i.currency}, {d} days late', _url('psa:invoice_detail', i.pk))
            for i, d, a in late][:MAX_LIST]
    return result(value, ctx.grade(value), _latest(*[i.updated_at for i in qs.order_by('-updated_at')[:1]]), src, refs,
                  f'{len(late)} overdue invoice(s).' if late else 'No overdue invoices.')


@signal('commercial', 'contract_renewals', 'Contract renewals', weight=1,
        description='Active contracts ending within 60 days that have no renewal draft.')
def contract_renewals(ctx: Context):
    from psa.models import Contract
    src = 'Contracts'
    active = list(Contract.objects.filter(Q(organization=ctx.client) | Q(client_org=ctx.client),
                                          status='active'))
    if not active:
        return unknown('No active contract exists for this client.', src)
    today = ctx.today
    horizon = today + timedelta(days=RENEWAL_WINDOW_DAYS)
    risky = []
    for c in active:
        if c.end_date and today <= c.end_date <= horizon and not c.auto_renew \
                and not c.renewals.exclude(status__in=('cancelled', 'expired')).exists():
            risky.append(c)
    value = max(0.0, 100.0 - 40.0 * len(risky))
    return result(value, ctx.grade(value), _latest(*[c.updated_at for c in active]), src,
                  [ref(c, f'{c.name} ends {c.end_date}', _url('psa:contract_detail', c.pk)) for c in risky][:MAX_LIST],
                  (f'{len(risky)} contract(s) end within {RENEWAL_WINDOW_DAYS} days with no renewal draft.'
                   if risky else f'No contract ends within {RENEWAL_WINDOW_DAYS} days without a renewal.'))


@signal('commercial', 'profitability', 'Profitability margin', weight=2,
        description='Client margin from the profitability report (needs Profitability and complete cost data).')
def profitability(ctx: Context):
    """Feature-detected: `reports.costing.client_margin_summary(client, today)`
    returning {margin_pct, complete, as_of, detail?, url?}. Absent or incomplete
    is unknown, never healthy."""
    src = 'Profitability'
    try:
        from reports import costing
        fn = getattr(costing, 'client_margin_summary', None)
    except ImportError:
        fn = None
    if fn is None:
        return unknown('Profitability reporting is not available, so margin is not measured.', src)
    data = fn(ctx.client, ctx.today) or {}
    if not data.get('complete') or data.get('margin_pct') is None:
        return unknown('Cost data for this client is incomplete, so margin is not scored.', src,
                       as_of=data.get('as_of'))
    margin = float(data['margin_pct'])
    value = max(0.0, min(100.0, margin * 100.0 / 40.0))     # a 40% margin is full marks
    return result(value, ctx.grade(value), data.get('as_of'), src,
                  [{'model': 'reports.profitability', 'pk': ctx.client.pk, 'label': 'Client profitability',
                    'url': data.get('url', '')}],
                  f'Margin {margin:.1f}%.')


# ------------------------------------------------------------- satisfaction

PULSE_WINDOW_DAYS = 180
PULSE_STALE_DAYS = 365


def _pulse_scores(ctx, start, end):
    """(avg 0-100 or None, responses) from answered pulse responses between."""
    from pulse.models import PulseQuestion, PulseResponse
    rows = list(PulseResponse.objects.filter(organization=ctx.client, responded_at__gte=start,
                                             responded_at__lt=end).select_related('send'))
    ratings, nps = [], []
    for r in rows:
        for q in r.send.questions:
            v = (r.answers or {}).get(str(q.get('id')))
            if not isinstance(v, int) or isinstance(v, bool):
                continue
            if q.get('kind') == PulseQuestion.KIND_RATING:
                ratings.append((v - 1) * 25.0)
            elif q.get('kind') == PulseQuestion.KIND_NPS:
                nps.append(v * 10.0)
    values = ratings or nps
    return (sum(values) / len(values) if values else None), rows


@signal('satisfaction', 'pulse_score', 'Pulse check score', weight=2,
        description='Average of 1-5 pulse check ratings (0-10 scores when there are none) over 180 days.')
def pulse_score(ctx: Context):
    src = 'Pulse checks'
    if not _installed('pulse'):
        return unknown('Pulse checks are not installed.', src)
    from pulse.models import PulseResponse
    newest = (PulseResponse.objects.filter(organization=ctx.client, responded_at__isnull=False)
              .order_by('-responded_at').first())
    if newest is None:
        return unknown('This client has not answered a pulse check yet.', src)
    if ctx.now - newest.responded_at > timedelta(days=PULSE_STALE_DAYS):
        return unknown('The latest pulse answer is over a year old.', src, status='stale', as_of=newest.responded_at)
    avg, rows = _pulse_scores(ctx, ctx.now - timedelta(days=PULSE_WINDOW_DAYS), ctx.now + timedelta(days=1))
    if avg is None:
        return unknown(f'No rating or 0-10 answer in the last {PULSE_WINDOW_DAYS} days.', src,
                       status='stale', as_of=newest.responded_at)
    sends = {}
    for r in rows:
        sends.setdefault(r.send_id, r.send)
    return result(avg, ctx.grade(avg), newest.responded_at, src,
                  [ref(s, f'{s.pulse_check.name} ({s.created_at:%Y-%m-%d})', _url('pulse:send_detail', s.pk))
                   for s in sends.values()][:MAX_LIST],
                  f'Average pulse score {avg:.0f} from {len(rows)} answer(s) in {PULSE_WINDOW_DAYS} days.')


@signal('satisfaction', 'pulse_trend', 'Pulse trend', weight=1,
        description='Pulse score for the last 90 days against the 90 days before.')
def pulse_trend(ctx: Context):
    src = 'Pulse checks'
    if not _installed('pulse'):
        return unknown('Pulse checks are not installed.', src)
    now = ctx.now
    recent, r_rows = _pulse_scores(ctx, now - timedelta(days=90), now + timedelta(days=1))
    previous, _p = _pulse_scores(ctx, now - timedelta(days=180), now - timedelta(days=90))
    if recent is None or previous is None:
        return unknown('A trend needs pulse answers in both of the last two 90-day periods.', src)
    delta = recent - previous
    value = max(0.0, min(100.0, 75.0 + delta * 1.25))      # flat = 75, +20 points = 100, -60 = 0
    return result(value, ctx.grade(value), _latest(*[r.responded_at for r in r_rows]), src, [],
                  f'Pulse score moved {delta:+.0f} points ({previous:.0f} to {recent:.0f}).')
