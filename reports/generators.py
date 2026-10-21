"""
Report Generators for different report types
"""

from datetime import timedelta
from django.db.models import Count, Q, Avg, Sum
from django.utils import timezone

from assets.models import Asset
from vault.models import Password
from docs.models import Document
from monitoring.models import WebsiteMonitor, Expiration


class ReportGenerator:
    """Base report generator class"""

    def __init__(self, organization, parameters=None):
        self.organization = organization
        self.parameters = parameters or {}

    def generate(self):
        """Override in subclasses"""
        raise NotImplementedError


class AssetSummaryReport(ReportGenerator):
    """Asset summary report"""

    def generate(self):
        assets = Asset.objects.filter(organization=self.organization)

        # Asset counts by type. Asset.asset_type is a CharField with
        # choices, NOT an FK to AssetType — so we group by the raw code
        # and translate to display labels via the choices dict.
        from assets.custom_types import asset_type_choices
        type_choices = dict(asset_type_choices())
        by_type_raw = assets.values('asset_type').annotate(
            count=Count('id')
        ).order_by('-count')
        by_type = [
            {
                'asset_type': row['asset_type'],
                'asset_type__name': type_choices.get(row['asset_type'], row['asset_type']),
                'count': row['count'],
            }
            for row in by_type_raw
        ]

        # Recently added
        days = self.parameters.get('recent_days', 30)
        recent_date = timezone.now() - timedelta(days=days)

        # Assets have no active/inactive flag; the report counted
        # `is_active` and failed on every run until v3.17.618.
        counts = assets.aggregate(
            total=Count('id'),
            needs_reorder=Count('id', filter=Q(needs_reorder=True)),
            warranty_expired=Count('id', filter=Q(warranty_expiry__lt=timezone.now().date())),
            recent=Count('id', filter=Q(created_at__gte=recent_date)),
        )

        return {
            'total_assets': counts['total'],
            'needs_reorder': counts['needs_reorder'],
            'warranty_expired': counts['warranty_expired'],
            'recent_assets': counts['recent'],
            'by_type': list(by_type),
            'generated_at': timezone.now().isoformat(),
        }


class AssetLifecycleReport(ReportGenerator):
    """Asset lifecycle and age analysis"""

    def generate(self):
        assets = Asset.objects.filter(organization=self.organization)

        # Age distribution
        now = timezone.now()
        age_ranges = {
            '0-1 years': 0,
            '1-3 years': 0,
            '3-5 years': 0,
            '5+ years': 0,
        }

        for asset in assets:
            if asset.created_at:
                age_days = (now - asset.created_at).days
                age_years = age_days / 365

                if age_years < 1:
                    age_ranges['0-1 years'] += 1
                elif age_years < 3:
                    age_ranges['1-3 years'] += 1
                elif age_years < 5:
                    age_ranges['3-5 years'] += 1
                else:
                    age_ranges['5+ years'] += 1

        return {
            'total_assets': assets.count(),
            'age_distribution': age_ranges,
            'generated_at': timezone.now().isoformat(),
        }


class PasswordAuditReport(ReportGenerator):
    """Shared vault entries of the organization (personal My Vault entries
    are left out). Until v3.17.618 it queried fields that don't exist
    (`totp_secret`, `category`) and failed on every run."""

    def generate(self):
        passwords = Password.objects.filter(organization=self.organization, is_personal=False)
        total = passwords.count()
        now = timezone.now()

        totp_enabled = passwords.exclude(otp_secret='').exclude(otp_secret__isnull=True).count()

        days = self.parameters.get('recent_days', 90)
        recently_updated = passwords.filter(updated_at__gte=now - timedelta(days=days)).count()

        by_folder = [
            {'folder': row['folder__name'] or '(no folder)', 'count': row['count']}
            for row in passwords.values('folder__name').annotate(count=Count('id')).order_by('-count')
        ]
        by_type = list(passwords.values('password_type').annotate(count=Count('id')).order_by('-count'))

        return {
            'total_passwords': total,
            'totp_enabled': totp_enabled,
            'totp_percentage': round(totp_enabled * 100.0 / total, 2) if total else 0,
            'recently_updated': recently_updated,
            'recent_days': days,
            'expired': passwords.filter(expires_at__lt=now).count(),
            'expiring_30_days': passwords.filter(expires_at__gte=now,
                                                 expires_at__lt=now + timedelta(days=30)).count(),
            'requires_reveal_approval': passwords.filter(requires_reveal_approval=True).count(),
            'by_type': by_type,
            'by_folder': by_folder,
            'generated_at': now.isoformat(),
        }


class DocumentUsageReport(ReportGenerator):
    """Document usage and access patterns"""

    def generate(self):
        documents = Document.objects.filter(organization=self.organization)

        # Document counts
        total = documents.count()
        archived = documents.filter(is_archived=True).count()
        active = total - archived

        # By category
        by_category = documents.values('category__name').annotate(
            count=Count('id')
        ).order_by('-count')

        # By content type
        by_type = documents.values('content_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # Recently created
        days = self.parameters.get('recent_days', 30)
        recent_date = timezone.now() - timedelta(days=days)
        recent_docs = documents.filter(created_at__gte=recent_date).count()

        return {
            'total_documents': total,
            'active_documents': active,
            'archived_documents': archived,
            'recent_documents': recent_docs,
            'by_category': list(by_category),
            'by_type': list(by_type),
            'generated_at': timezone.now().isoformat(),
        }


class MonitorUptimeReport(ReportGenerator):
    """Website monitor uptime over the last 30 days, from the check history.

    Uptime is computed the way status pages compute it
    (`WebsiteMonitor.uptime`): a check counts as up unless its status is
    `down`. A monitor with no checks in the window has no uptime (None), not
    0% or 100%. `up` / `down` / `warning` count monitors by current status;
    `active` is the status a healthy monitor has.
    """

    WINDOW_DAYS = 30

    def generate(self):
        from monitoring.models import MonitorCheck

        monitors = WebsiteMonitor.objects.filter(organization=self.organization)
        since = timezone.now() - timedelta(days=self.WINDOW_DAYS)
        checks = MonitorCheck.objects.filter(monitor__in=monitors, checked_at__gte=since)
        total_checks = checks.count()
        down_checks = checks.filter(status='down').count()

        rows = []
        for m in monitors.order_by('name'):
            u = m.uptime(self.WINDOW_DAYS)
            rows.append({
                'name': m.name,
                'url': m.url,
                'status': m.status,
                'uptime_percent': u['percent'],
                'checks': u['checks'],
                'down_checks': u['down'],
            })

        by_status = monitors.values('status').annotate(
            count=Count('id')
        ).order_by('-count')

        return {
            'total_monitors': monitors.count(),
            'up': monitors.filter(status='active').count(),
            'down': monitors.filter(status='down').count(),
            'warning': monitors.filter(status='warning').count(),
            'window_days': self.WINDOW_DAYS,
            'uptime_percentage': (round((total_checks - down_checks) * 100.0 / total_checks, 2)
                                  if total_checks else None),
            'monitors': rows,
            'by_status': list(by_status),
            'wan_connections': self._wan_rows(),
            'generated_at': timezone.now().isoformat(),
        }

    def _wan_rows(self):
        """WAN connections with monitoring on, uptime from their checks
        (v3.17.617); None when a connection has no checks in the window."""
        from locations.models import WAN

        rows = []
        wans = (WAN.objects.filter(organization=self.organization, monitoring_enabled=True)
                .select_related('location').order_by('location__name', 'name'))
        for w in wans:
            u = w.uptime(self.WINDOW_DAYS)
            rows.append({
                'location': w.location.name,
                'name': w.name,
                'target': w.monitor_target,
                'status': w.status,
                'uptime_percent': u['percent'],
                'checks': u['checks'],
                'down_checks': u['down'],
            })
        return rows


class UserActivityReport(ReportGenerator):
    """Audit-log activity for the organization over the last `days` (default
    30): totals by action and by user, and failed sign-ins. The built-in
    "User Activity Report" template had no generator until v3.17.618, so it
    produced a file holding only an error message."""

    def generate(self):
        from audit.models import AuditLog

        try:
            days = max(1, min(int(self.parameters.get('days', 30)), 366))
        except (TypeError, ValueError):
            days = 30
        since = timezone.now() - timedelta(days=days)
        events = AuditLog.objects.filter(organization=self.organization, timestamp__gte=since)
        by_action = events.values('action').annotate(count=Count('id')).order_by('-count')
        # Many rows are written with `user` set and `username` blank, others
        # (deleted users) with only `username`.
        grouped = (events.values('user_id', 'user__username', 'username')
                   .annotate(count=Count('id'),
                             logins=Count('id', filter=Q(action='login')),
                             changes=Count('id', filter=Q(action__in=['create', 'update', 'delete']))))
        totals = {}
        for row in grouped:
            name = row['user__username'] or row['username']
            if not name:
                continue
            t = totals.setdefault(name, {'username': name, 'count': 0, 'logins': 0, 'changes': 0})
            for k in ('count', 'logins', 'changes'):
                t[k] += row[k]
        by_user = sorted(totals.values(), key=lambda r: (-r['count'], r['username']))[:50]
        return {
            'window_days': days,
            'total_events': events.count(),
            'active_users': len(totals),
            'failed_logins': events.filter(action='login_failed').count(),
            'by_action': list(by_action),
            'by_user': by_user,
            'generated_at': timezone.now().isoformat(),
        }


class ExpirationForecastReport(ReportGenerator):
    """Expiration forecast report"""

    def generate(self):
        expirations = Expiration.objects.filter(organization=self.organization)

        now = timezone.now().date()

        # Expiring in different time frames
        forecast = {
            'expired': 0,
            'expiring_7_days': 0,
            'expiring_30_days': 0,
            'expiring_90_days': 0,
            'future': 0,
        }

        # The report read `expiration_date` and grouped by `type`; the fields
        # are `expires_at` and `expiration_type` (it failed on every run until
        # v3.17.618).
        for exp in expirations:
            if exp.expires_at:
                days_until = (exp.expires_at.date() - now).days

                if days_until < 0:
                    forecast['expired'] += 1
                elif days_until <= 7:
                    forecast['expiring_7_days'] += 1
                elif days_until <= 30:
                    forecast['expiring_30_days'] += 1
                elif days_until <= 90:
                    forecast['expiring_90_days'] += 1
                else:
                    forecast['future'] += 1

        # By type
        by_type = expirations.values('expiration_type').annotate(
            count=Count('id')
        ).order_by('-count')

        return {
            'total_expirations': expirations.count(),
            'forecast': forecast,
            'by_type': list(by_type),
            'generated_at': timezone.now().isoformat(),
        }


class OrganizationMetricsReport(ReportGenerator):
    """Overall organization metrics"""

    def generate(self):
        from accounts.models import Membership

        # Member counts (the report imported a model that doesn't exist and
        # failed on every run until v3.17.618).
        members = Membership.objects.filter(organization=self.organization)
        member_count = members.count()
        active_members = members.filter(is_active=True, user__is_active=True).count()

        assets = Asset.objects.filter(organization=self.organization)
        asset_count = assets.count()

        # Password metrics
        password_count = Password.objects.filter(organization=self.organization, is_personal=False).count()

        # Document metrics
        document_count = Document.objects.filter(organization=self.organization).count()

        # Monitor metrics
        monitor_count = WebsiteMonitor.objects.filter(organization=self.organization).count()

        return {
            'organization': {
                'name': self.organization.name,
                'member_count': member_count,
                'active_members': active_members,
            },
            'metrics': {
                'assets': {
                    'total': asset_count,
                },
                'passwords': password_count,
                'documents': document_count,
                'monitors': monitor_count,
            },
            'generated_at': timezone.now().isoformat(),
        }


# ---------------------------------------------------------------------------
# PSA reports (Workstream 6)
# ---------------------------------------------------------------------------

def _psa_imports():
    """Lazy import so reports/ doesn't fail when psa/ isn't installed."""
    try:
        from psa.models import Ticket, TicketTimeEntry
        return Ticket, TicketTimeEntry
    except Exception:
        return None, None


def _psa_window(parameters):
    """Common 'last N days' window helper."""
    days = int(parameters.get('days', 30) or 30)
    cutoff = timezone.now() - timedelta(days=days)
    return days, cutoff


class PSAOpenTicketsByClientReport(ReportGenerator):
    """Open (non-terminal) tickets grouped by client. Single ORM call."""

    def generate(self):
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        qs = Ticket.objects.filter(status__is_terminal=False)
        if self.organization is not None:
            qs = qs.filter(organization=self.organization)
        rows = list(
            qs.values('organization__name')
              .annotate(count=Count('id'))
              .order_by('-count')
        )
        return {
            'rows': rows,
            'total_open': sum(r['count'] for r in rows),
            'generated_at': timezone.now().isoformat(),
            'scope': 'this client' if self.organization else 'all clients',
        }


class PSASLABreachesReport(ReportGenerator):
    """Tickets with SLA breaches in the last N days."""

    def generate(self):
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        qs = Ticket.objects.filter(
            created_at__gte=cutoff,
        ).filter(Q(sla_breached_response=True) | Q(sla_breached_resolution=True))
        if self.organization is not None:
            qs = qs.filter(organization=self.organization)
        rows = []
        for t in qs.select_related('organization', 'priority', 'status', 'assigned_to')[:500]:
            rows.append({
                'ticket_number': t.ticket_number,
                'client': t.organization.name if t.organization_id else '',
                'priority': t.priority.code if t.priority_id else '',
                'status': t.status.name if t.status_id else '',
                'subject': t.subject[:120],
                'response_breached': t.sla_breached_response,
                'resolution_breached': t.sla_breached_resolution,
                'assigned_to': t.assigned_to.username if t.assigned_to_id else '',
                'created_at': t.created_at.isoformat() if t.created_at else '',
            })
        return {
            'rows': rows,
            'window_days': days,
            'total': len(rows),
            'generated_at': timezone.now().isoformat(),
        }


class PSAResponseTimeByTechReport(ReportGenerator):
    """Avg minutes from ticket-create to first-response, grouped by assignee."""

    def generate(self):
        from django.db.models import F, ExpressionWrapper, FloatField
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        qs = Ticket.objects.filter(
            created_at__gte=cutoff,
            first_response_at__isnull=False,
            assigned_to__isnull=False,
        )
        if self.organization is not None:
            qs = qs.filter(organization=self.organization)
        rows = list(
            qs.annotate(
                resp_seconds=ExpressionWrapper(
                    F('first_response_at') - F('created_at'),
                    output_field=FloatField(),
                ),
            ).values('assigned_to__username').annotate(
                avg_seconds=Avg('resp_seconds'),
                ticket_count=Count('id'),
            ).order_by('avg_seconds')
        )
        # Convert timedelta avg → minutes for display.
        for r in rows:
            secs = r.pop('avg_seconds') or 0
            try:
                r['avg_minutes'] = round(float(secs.total_seconds()) / 60, 1)
            except AttributeError:
                # On some DBs the avg comes back as a number of seconds already.
                r['avg_minutes'] = round(float(secs) / 60, 1) if secs else 0
        return {
            'rows': rows,
            'window_days': days,
            'generated_at': timezone.now().isoformat(),
        }


class PSAResolutionTimeByClientReport(ReportGenerator):
    """Avg hours from create to resolved, grouped by client."""

    def generate(self):
        from django.db.models import F, ExpressionWrapper, FloatField
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        qs = Ticket.objects.filter(
            created_at__gte=cutoff, resolved_at__isnull=False,
        )
        if self.organization is not None:
            qs = qs.filter(organization=self.organization)
        rows = list(
            qs.annotate(
                res_seconds=ExpressionWrapper(
                    F('resolved_at') - F('created_at'),
                    output_field=FloatField(),
                ),
            ).values('organization__name').annotate(
                avg_seconds=Avg('res_seconds'),
                ticket_count=Count('id'),
            ).order_by('avg_seconds')
        )
        for r in rows:
            secs = r.pop('avg_seconds') or 0
            try:
                r['avg_hours'] = round(float(secs.total_seconds()) / 3600, 1)
            except AttributeError:
                r['avg_hours'] = round(float(secs) / 3600, 1) if secs else 0
        return {
            'rows': rows,
            'window_days': days,
            'generated_at': timezone.now().isoformat(),
        }


class PSATicketsByDimensionReport(ReportGenerator):
    """Ticket counts grouped by queue, type, priority. Three rollups in one report."""

    def generate(self):
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        qs = Ticket.objects.filter(created_at__gte=cutoff)
        if self.organization is not None:
            qs = qs.filter(organization=self.organization)
        return {
            'by_queue': list(qs.values('queue__name').annotate(count=Count('id')).order_by('-count')),
            'by_type': list(qs.values('ticket_type__name').annotate(count=Count('id')).order_by('-count')),
            'by_priority': list(qs.values('priority__code', 'priority__name').annotate(count=Count('id')).order_by('priority__sort_order')),
            'window_days': days,
            'total': qs.count(),
            'generated_at': timezone.now().isoformat(),
        }


class PSABillableHoursByClientReport(ReportGenerator):
    """Sum of billable TicketTimeEntry minutes grouped by client."""

    def generate(self):
        Ticket, TimeEntry = _psa_imports()
        if TimeEntry is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        qs = TimeEntry.objects.filter(
            started_at__gte=cutoff, ended_at__isnull=False,
        )
        if self.organization is not None:
            qs = qs.filter(ticket__organization=self.organization)
        rows = list(
            qs.values('ticket__organization__name').annotate(
                total_minutes=Sum('duration_minutes', filter=Q(is_billable=True)),
                non_billable_minutes=Sum('duration_minutes', filter=Q(is_billable=False)),
            ).order_by('-total_minutes')
        )
        for r in rows:
            r['total_hours'] = round((r.pop('total_minutes') or 0) / 60.0, 2)
            r['non_billable_hours'] = round((r.pop('non_billable_minutes') or 0) / 60.0, 2)
        return {
            'rows': rows,
            'window_days': days,
            'grand_total_hours': round(sum(r['total_hours'] for r in rows), 2),
            'generated_at': timezone.now().isoformat(),
        }


class PSARecurringIssuesReport(ReportGenerator):
    """Assets with multiple tickets — likely "noisy" assets needing attention."""

    def generate(self):
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        qs = Ticket.objects.filter(
            created_at__gte=cutoff, related_asset__isnull=False,
        )
        if self.organization is not None:
            qs = qs.filter(organization=self.organization)
        rows = list(
            qs.values('related_asset__name', 'organization__name')
              .annotate(count=Count('id'))
              .filter(count__gte=2)
              .order_by('-count')
        )
        return {
            'rows': rows,
            'window_days': days,
            'noisy_count': len(rows),
            'generated_at': timezone.now().isoformat(),
        }


class PSATicketsByAssigneeReport(ReportGenerator):
    """Open ticket count + total tickets last N days, grouped by assignee."""

    def generate(self):
        Ticket, _ = _psa_imports()
        if Ticket is None:
            return {'error': 'PSA app not installed'}
        days, cutoff = _psa_window(self.parameters)
        base = Ticket.objects
        if self.organization is not None:
            base = base.filter(organization=self.organization)

        # Open tickets per assignee (right now)
        open_rows = list(
            base.filter(status__is_terminal=False, assigned_to__isnull=False)
                .values('assigned_to__username')
                .annotate(open_count=Count('id'))
                .order_by('-open_count')
        )
        # Closed tickets in the window per assignee
        closed_rows = {
            r['assigned_to__username']: r['closed_count']
            for r in base.filter(
                resolved_at__gte=cutoff, assigned_to__isnull=False,
            ).values('assigned_to__username').annotate(closed_count=Count('id'))
        }
        for r in open_rows:
            r['closed_in_window'] = closed_rows.get(r['assigned_to__username'], 0)
        return {
            'rows': open_rows,
            'window_days': days,
            'generated_at': timezone.now().isoformat(),
        }


# Report generator registry
REPORT_GENERATORS = {
    'asset_summary': AssetSummaryReport,
    'asset_lifecycle': AssetLifecycleReport,
    'password_audit': PasswordAuditReport,
    'document_usage': DocumentUsageReport,
    'monitor_uptime': MonitorUptimeReport,
    'expiration_forecast': ExpirationForecastReport,
    'organization_metrics': OrganizationMetricsReport,
    'user_activity': UserActivityReport,
    # PSA — Workstream 6
    'psa_open_tickets_by_client': PSAOpenTicketsByClientReport,
    'psa_sla_breaches': PSASLABreachesReport,
    'psa_response_time_by_tech': PSAResponseTimeByTechReport,
    'psa_resolution_time_by_client': PSAResolutionTimeByClientReport,
    'psa_tickets_by_dimension': PSATicketsByDimensionReport,
    'psa_billable_hours_by_client': PSABillableHoursByClientReport,
    'psa_recurring_issues': PSARecurringIssuesReport,
    'psa_tickets_by_assignee': PSATicketsByAssigneeReport,
}


PSA_REPORT_DEFINITIONS = [
    {
        'type': 'psa_open_tickets_by_client',
        'name': 'Open Tickets by Client',
        'icon': 'fas fa-list',
        'description': 'Currently-open ticket count grouped by client.',
    },
    {
        'type': 'psa_sla_breaches',
        'name': 'SLA Breaches',
        'icon': 'fas fa-triangle-exclamation',
        'description': 'Tickets that breached response or resolution SLA in the last N days.',
        'param_help': 'days (default 30)',
    },
    {
        'type': 'psa_response_time_by_tech',
        'name': 'Response Time by Tech',
        'icon': 'fas fa-stopwatch',
        'description': 'Average first-response time per assignee, last N days.',
        'param_help': 'days (default 30)',
    },
    {
        'type': 'psa_resolution_time_by_client',
        'name': 'Resolution Time by Client',
        'icon': 'fas fa-clock',
        'description': 'Average resolution hours per client, last N days.',
        'param_help': 'days (default 30)',
    },
    {
        'type': 'psa_tickets_by_dimension',
        'name': 'Tickets by Queue / Type / Priority',
        'icon': 'fas fa-th-large',
        'description': 'Three breakdowns of ticket volume in one report.',
        'param_help': 'days (default 30)',
    },
    {
        'type': 'psa_billable_hours_by_client',
        'name': 'Billable Hours by Client',
        'icon': 'fas fa-dollar-sign',
        'description': 'Sum of billable + non-billable hours from time entries, by client.',
        'param_help': 'days (default 30)',
    },
    {
        'type': 'psa_recurring_issues',
        'name': 'Noisy Assets / Recurring Issues',
        'icon': 'fas fa-redo',
        'description': 'Assets with 2+ tickets in the window — likely candidates for proactive work.',
        'param_help': 'days (default 30)',
    },
    {
        'type': 'psa_tickets_by_assignee',
        'name': 'Tickets by Assignee',
        'icon': 'fas fa-users',
        'description': 'Open ticket load + closed-in-window per technician.',
        'param_help': 'days (default 30)',
    },
]


def get_report_generator(report_type):
    """Get report generator class by type"""
    return REPORT_GENERATORS.get(report_type)


# ---------------------------------------------------------------------------
# v3.17.147 — Phase 3.6 wave B: artifact wrapper for the cron runner
# ---------------------------------------------------------------------------

# Formats generate_report can write. GeneratedReport.FORMAT_CHOICES also
# lists Excel, which was offered on the forms but written as a PDF.
OUTPUT_FORMATS = ('pdf', 'csv', 'json')
FORMAT_CHOICES = [('pdf', 'PDF'), ('csv', 'CSV'), ('json', 'JSON')]


def generate_report(template, output_format='pdf', organization=None, parameters=None):
    """
    Run the generator for ``template`` and serialize the result to the
    requested output format. Returns ``(filename, bytes)``.

    Used by the ``run_scheduled_reports`` management command. PDF is
    rendered as a minimal text-PDF (no external deps) — sufficient for
    email attachment delivery; rich PDF rendering can come later via
    reportlab/weasyprint when those libs are required.
    """
    import csv
    import io
    import json as _json

    cls = REPORT_GENERATORS.get(template.report_type)
    if cls is None:
        # Used to write a "successful" file holding only an error message.
        raise ValueError(f'There is no generator for the report type "{template.report_type}".')
    org = organization or getattr(template, 'organization', None)
    data = cls(org, parameters or {}).generate()

    fmt = (output_format or 'pdf').lower()
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(f'Unsupported report format "{output_format}".')
    safe_name = (template.name or 'report').replace(' ', '_')
    stamp = timezone.now().strftime('%Y%m%d-%H%M%S')

    if fmt == 'csv':
        buf = io.StringIO()
        writer = csv.writer(buf)
        # Flatten one level of dict → key/value rows for the simple cases;
        # nested dicts/lists are written as JSON strings.
        if isinstance(data, dict):
            writer.writerow(['key', 'value'])
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    writer.writerow([k, _json.dumps(v, default=str)])
                else:
                    writer.writerow([k, v])
        else:
            writer.writerow(['data'])
            writer.writerow([_json.dumps(data, default=str)])
        return f'{safe_name}-{stamp}.csv', buf.getvalue().encode('utf-8')

    if fmt in ('json',):
        return (f'{safe_name}-{stamp}.json',
                _json.dumps(data, indent=2, default=str).encode('utf-8'))

    # Default: PDF — minimal hand-rolled PDF so we don't need reportlab in
    # the cron runner. The body is a single text-stream containing a JSON
    # dump of the report data; readers like Adobe Reader render the text.
    body = _json.dumps(data, indent=2, default=str)
    pdf_bytes = _minimal_text_pdf(f'{template.name}\n\n{body}')
    return f'{safe_name}-{stamp}.pdf', pdf_bytes


def _minimal_text_pdf(text: str) -> bytes:
    """Return a tiny standalone PDF containing the supplied text.

    Hand-rolled PDF 1.4 with a single page of Helvetica text. Avoids
    pulling reportlab/weasyprint into the cron path. Lines are wrapped
    at ~90 chars and split across pages of 50 lines max — good enough for
    audit-trail attachments.
    """
    # Sanitize: PDF text strings can't have unescaped parens or backslashes.
    def esc(s):
        return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    # Wrap long lines — keep things simple, don't word-wrap.
    raw_lines = []
    for line in text.split('\n'):
        if not line:
            raw_lines.append('')
            continue
        while len(line) > 90:
            raw_lines.append(line[:90])
            line = line[90:]
        raw_lines.append(line)

    # Build content stream
    stream_lines = ['BT', '/F1 10 Tf', '12 TL', '40 760 Td']
    for line in raw_lines[:600]:  # cap at ~12 pages worth
        stream_lines.append(f'({esc(line)}) Tj T*')
    stream_lines.append('ET')
    stream = '\n'.join(stream_lines).encode('latin-1', errors='replace')

    # Assemble a minimal PDF with xref table
    objects = []

    def add_obj(body_bytes: bytes):
        objects.append(body_bytes)
        return len(objects)  # 1-based object number

    add_obj(b'<< /Type /Catalog /Pages 2 0 R >>')
    add_obj(b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
    add_obj(
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
        b'/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>'
    )
    add_obj(
        f'<< /Length {len(stream)} >>\nstream\n'.encode('latin-1') +
        stream + b'\nendstream'
    )
    add_obj(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')

    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode('latin-1') + body + b'\nendobj\n'

    xref_offset = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode('latin-1')
    out += b'0000000000 65535 f \n'
    for off in offsets:
        out += f'{off:010d} 00000 n \n'.encode('latin-1')
    out += (
        f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'
        f'startxref\n{xref_offset}\n%%EOF\n'
    ).encode('latin-1')
    return bytes(out)
