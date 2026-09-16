"""
Views for Reports and Analytics
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, FileResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q, Sum
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from accounts.permission_utils import user_has_perm, require_perm
from .models import (
    Dashboard, DashboardWidget, ReportTemplate, GeneratedReport,
    ScheduledReport, AnalyticsEvent, Wallboard, WallboardWidget,
)
from .generators import REPORT_GENERATORS
import csv as _csv
import json


def get_user_organizations(user):
    """Get all organizations the user is a member of"""
    from core.models import Organization
    if user.is_superuser:
        return Organization.objects.all()
    return Organization.objects.filter(
        memberships__user=user,
        memberships__is_active=True
    ).distinct()


def get_user_primary_organization(user):
    """Get user's primary organization (first active membership)"""
    membership = user.memberships.filter(is_active=True).select_related('organization').first()
    return membership.organization if membership else None


@login_required
@require_perm('reports_view_dashboards')
def reports_home(request):
    """Reports and Analytics home page"""
    orgs = get_user_organizations(request.user)

    perm = {
        'view_dashboards': True,  # we got past require_perm above
        'view_financial': user_has_perm(request.user, 'reports_view_financial'),
        'view_sla': user_has_perm(request.user, 'reports_view_sla'),
        'view_capacity': user_has_perm(request.user, 'reports_view_capacity'),
        'manage_dashboards': user_has_perm(request.user, 'reports_manage_dashboards'),
        'manage_scheduled': user_has_perm(request.user, 'reports_manage_scheduled'),
        'crm_view_forecast': user_has_perm(request.user, 'crm_view_forecast'),
    }

    context = {
        'recent_reports': GeneratedReport.objects.filter(
            organization__in=orgs
        ).select_related('template', 'generated_by')[:10],
        'active_schedules': ScheduledReport.objects.filter(
            organization__in=orgs,
            is_active=True
        ).count(),
        'total_dashboards': Dashboard.objects.filter(
            Q(organization__in=orgs) | Q(is_global=True)
        ).count(),
        'templates_count': ReportTemplate.objects.filter(
            Q(organization__in=orgs) | Q(is_global=True)
        ).count(),
        'perm': perm,
    }

    return render(request, 'reports/home.html', context)


@login_required
@require_perm('reports_view_dashboards')
def dashboard_list(request):
    """List all available dashboards"""
    orgs = get_user_organizations(request.user)

    dashboards = Dashboard.objects.filter(
        Q(organization__in=orgs) | Q(is_global=True)
    ).prefetch_related('widgets')

    context = {
        'dashboards': dashboards,
    }

    return render(request, 'reports/dashboard_list.html', context)


@login_required
@require_perm('reports_view_dashboards')
def dashboard_detail(request, pk):
    """View a specific dashboard.

    v3.17.142: each widget is rendered server-side via the
    `reports.widget_sources` registry so the template just emits HTML
    based on the prepared `widget.rendered` payload.
    """
    from .widget_sources import get_widget_data, viewer_for
    orgs = get_user_organizations(request.user)

    dashboard = get_object_or_404(
        Dashboard,
        Q(organization__in=orgs) | Q(organization__isnull=True),  # User's orgs or global
        pk=pk
    )

    widgets = list(dashboard.widgets.all())
    # Sort by position {x, y} when present, fall back to pk for stable order.
    def _pos_key(w):
        pos = w.position or {}
        return (pos.get('y', 0), pos.get('x', 0), w.pk)
    widgets.sort(key=_pos_key)

    # Render data for each widget. Errors are captured per-widget so a
    # single misbehaving data source can't blow up the whole page.
    has_chart = False
    # Who is looking decides both which widgets render at all and whose
    # clients they aggregate — a dashboard can be shared (or global) and is
    # not itself a statement about what its viewer may see.
    viewer = viewer_for(request.user, getattr(request, 'is_staff_user', False))
    for w in widgets:
        params = dict(w.query_params or {})
        w.rendered = get_widget_data(w.data_source, params, viewer)
        # Pre-serialize chart payload so the template can drop it into a
        # <script type="application/json"> tag without re-encoding.
        if w.widget_type in ('chart_line', 'chart_bar', 'chart_pie'):
            has_chart = True
            # Escape `</` so the payload can't break out of <script> tags.
            w.rendered_json = json.dumps(w.rendered).replace('</', '<\\/')

    can_manage = (
        dashboard.created_by_id == request.user.id
        or request.user.is_staff
    )

    context = {
        'dashboard': dashboard,
        'widgets': widgets,
        'has_chart': has_chart,
        'can_manage': can_manage,
    }

    return render(request, 'reports/dashboard_detail.html', context)


@login_required
@require_perm('reports_manage_dashboards')
def dashboard_create(request):
    """Create a new dashboard"""
    org = get_user_primary_organization(request.user)
    if not org:
        messages.error(request, 'You must be a member of an organization to create dashboards.')
        return redirect('reports:home')

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        is_default = request.POST.get('is_default') == 'on'

        dashboard = Dashboard.objects.create(
            name=name,
            description=description,
            is_default=is_default,
            organization=org,
            created_by=request.user
        )

        messages.success(request, f'Dashboard "{name}" created successfully.')
        return redirect('reports:dashboard_detail', pk=dashboard.pk)

    return render(request, 'reports/dashboard_form.html', {'action': 'Create'})


@login_required
@require_perm('reports_manage_dashboards')
def dashboard_edit(request, pk):
    """Edit an existing dashboard"""
    orgs = get_user_organizations(request.user)
    dashboard = get_object_or_404(
        Dashboard,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        dashboard.name = request.POST.get('name')
        dashboard.description = request.POST.get('description', '')
        dashboard.is_default = request.POST.get('is_default') == 'on'
        dashboard.save()

        messages.success(request, f'Dashboard "{dashboard.name}" updated successfully.')
        return redirect('reports:dashboard_detail', pk=dashboard.pk)

    context = {
        'dashboard': dashboard,
        'action': 'Edit'
    }

    return render(request, 'reports/dashboard_form.html', context)


@login_required
@require_perm('reports_manage_dashboards')
def dashboard_delete(request, pk):
    """Delete a dashboard"""
    orgs = get_user_organizations(request.user)
    dashboard = get_object_or_404(
        Dashboard,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        name = dashboard.name
        dashboard.delete()
        messages.success(request, f'Dashboard "{name}" deleted successfully.')
        return redirect('reports:dashboard_list')

    context = {'dashboard': dashboard}
    return render(request, 'reports/dashboard_confirm_delete.html', context)


# ---------------------------------------------------------------------------
# Dashboard widget CRUD (v3.17.142)
# ---------------------------------------------------------------------------

@login_required
@require_perm('reports_manage_dashboards')
def dashboard_widget_add(request, dashboard_pk):
    """Add a widget to a dashboard. Owner or staff only."""
    dashboard = get_object_or_404(Dashboard, pk=dashboard_pk)
    if dashboard.created_by_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    from .widget_sources import DATA_SOURCE_CHOICES
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        data_source = (request.POST.get('data_source') or '').strip()
        wt = next(
            (wt for k, _, wt in DATA_SOURCE_CHOICES if k == data_source),
            'metric',
        )
        DashboardWidget.objects.create(
            dashboard=dashboard, title=title or data_source,
            widget_type=wt, data_source=data_source,
            query_params={}, position={},
        )
        messages.success(request, 'Widget added.')
        return redirect('reports:dashboard_detail', pk=dashboard.pk)
    return render(request, 'reports/dashboard_widget_form.html', {
        'dashboard': dashboard,
        'data_source_choices': DATA_SOURCE_CHOICES,
        'action': 'Add',
    })


@login_required
@require_perm('reports_manage_dashboards')
def dashboard_widget_edit(request, pk):
    """Edit an existing widget. Owner or staff only."""
    widget = get_object_or_404(DashboardWidget, pk=pk)
    dashboard = widget.dashboard
    if dashboard.created_by_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    from .widget_sources import DATA_SOURCE_CHOICES
    if request.method == 'POST':
        widget.title = (request.POST.get('title') or '').strip() or widget.title
        new_ds = (request.POST.get('data_source') or '').strip()
        if new_ds:
            widget.data_source = new_ds
            widget.widget_type = next(
                (wt for k, _, wt in DATA_SOURCE_CHOICES if k == new_ds),
                widget.widget_type,
            )
        widget.save()
        messages.success(request, 'Widget updated.')
        return redirect('reports:dashboard_detail', pk=dashboard.pk)
    return render(request, 'reports/dashboard_widget_form.html', {
        'dashboard': dashboard, 'widget': widget,
        'data_source_choices': DATA_SOURCE_CHOICES,
        'action': 'Edit',
    })


@login_required
@require_perm('reports_manage_dashboards')
def dashboard_widget_delete(request, pk):
    """Delete a widget. Owner or staff only."""
    widget = get_object_or_404(DashboardWidget, pk=pk)
    dashboard = widget.dashboard
    if dashboard.created_by_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    if request.method == 'POST':
        widget.delete()
        messages.success(request, 'Widget deleted.')
        return redirect('reports:dashboard_detail', pk=dashboard.pk)
    return render(request, 'reports/dashboard_widget_confirm_delete.html', {
        'widget': widget, 'dashboard': dashboard,
    })


@login_required
@require_perm('reports_view_dashboards')
def template_list(request):
    """List all report templates"""
    orgs = get_user_organizations(request.user)

    templates = ReportTemplate.objects.filter(
        Q(organization__in=orgs) | Q(is_global=True)
    ).select_related('created_by')

    # Group by report type
    templates_by_type = {}
    for template in templates:
        report_type = template.get_report_type_display()
        if report_type not in templates_by_type:
            templates_by_type[report_type] = []
        templates_by_type[report_type].append(template)

    context = {
        'templates': templates,
        'templates_by_type': templates_by_type,
    }

    return render(request, 'reports/template_list.html', context)


@login_required
@require_perm('reports_view_dashboards')
def template_detail(request, pk):
    """View a report template"""
    orgs = get_user_organizations(request.user)

    template = get_object_or_404(
        ReportTemplate,
        Q(organization__in=orgs) | Q(organization__isnull=True),
        pk=pk
    )

    recent_reports = GeneratedReport.objects.filter(
        template=template,
        organization__in=orgs
    )[:10]

    context = {
        'template': template,
        'recent_reports': recent_reports,
    }

    return render(request, 'reports/template_detail.html', context)


@login_required
@require_perm('reports_manage_dashboards')
def template_create(request):
    """Create a new report template"""
    org = get_user_primary_organization(request.user)
    if not org and not request.user.is_staff:
        messages.error(request, 'You must be a member of an organization to create templates.')
        return redirect('reports:template_list')

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        report_type = request.POST.get('report_type')
        query_template = request.POST.get('query_template', '')
        is_global = request.POST.get('is_global') == 'on' and request.user.is_staff

        template = ReportTemplate.objects.create(
            name=name,
            description=description,
            report_type=report_type,
            query_template=query_template,
            is_global=is_global,
            organization=org if not is_global else None,
            created_by=request.user
        )

        messages.success(request, f'Report template "{name}" created successfully.')
        return redirect('reports:template_detail', pk=template.pk)

    context = {
        'action': 'Create',
        'report_types': ReportTemplate.REPORT_TYPES,
    }

    return render(request, 'reports/template_form.html', context)


@login_required
@require_perm('reports_manage_dashboards')
def template_edit(request, pk):
    """Edit a report template"""
    orgs = get_user_organizations(request.user)
    template = get_object_or_404(
        ReportTemplate,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        template.name = request.POST.get('name')
        template.description = request.POST.get('description', '')
        template.report_type = request.POST.get('report_type')
        template.query_template = request.POST.get('query_template', '')
        template.is_global = request.POST.get('is_global') == 'on' and request.user.is_staff
        template.save()

        messages.success(request, f'Report template "{template.name}" updated successfully.')
        return redirect('reports:template_detail', pk=template.pk)

    context = {
        'template': template,
        'action': 'Edit',
        'report_types': ReportTemplate.REPORT_TYPES,
    }

    return render(request, 'reports/template_form.html', context)


@login_required
@require_perm('reports_manage_dashboards')
def template_delete(request, pk):
    """Delete a report template"""
    orgs = get_user_organizations(request.user)
    template = get_object_or_404(
        ReportTemplate,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        name = template.name
        template.delete()
        messages.success(request, f'Report template "{name}" deleted successfully.')
        return redirect('reports:template_list')

    context = {'template': template}
    return render(request, 'reports/template_confirm_delete.html', context)


@login_required
def generate_report(request, pk):
    """Generate a report from a template"""
    org = get_user_primary_organization(request.user)
    if not org:
        messages.error(request, 'You must be a member of an organization to generate reports.')
        return redirect('reports:template_list')

    orgs = get_user_organizations(request.user)
    template = get_object_or_404(
        ReportTemplate,
        Q(organization__in=orgs) | Q(organization__isnull=True),
        pk=pk
    )

    if request.method == 'POST':
        report_format = request.POST.get('format', 'pdf')
        parameters = {}

        # Create the report generation task
        report = GeneratedReport.objects.create(
            template=template,
            organization=org,
            generated_by=request.user,
            format=report_format,
            parameters=parameters,
            status='pending'
        )

        # In a real implementation, this would trigger a Celery task
        # For now, we'll generate synchronously and write to the FileField.
        from django.core.files.base import ContentFile
        from .generators import generate_report as _generate_report

        try:
            filename, bytes_data = _generate_report(
                template,
                output_format=report_format,
                organization=org,
                parameters=parameters,
            )
            report.file.save(filename, ContentFile(bytes_data), save=False)
            report.file_size = len(bytes_data) if bytes_data else 0
            report.status = 'completed'
            report.completed_at = timezone.now()
            report.save()

            messages.success(request, f'Report "{template.name}" generated successfully.')
        except Exception as e:
            report.status = 'failed'
            report.error_message = str(e)
            report.save()
            messages.error(request, f'Failed to generate report: {str(e)}')

        return redirect('reports:generated_detail', pk=report.pk)

    context = {
        'template': template,
        'formats': GeneratedReport.FORMAT_CHOICES,
    }

    return render(request, 'reports/generate_form.html', context)


@login_required
@require_perm('reports_view_dashboards')
def generated_list(request):
    """List all generated reports"""
    orgs = get_user_organizations(request.user)

    reports = GeneratedReport.objects.filter(
        organization__in=orgs
    ).select_related('template', 'generated_by').order_by('-created_at')

    context = {
        'reports': reports,
    }

    return render(request, 'reports/generated_list.html', context)


@login_required
@require_perm('reports_view_dashboards')
def generated_detail(request, pk):
    """View a generated report"""
    orgs = get_user_organizations(request.user)
    report = get_object_or_404(
        GeneratedReport,
        pk=pk,
        organization__in=orgs
    )

    context = {
        'report': report,
    }

    return render(request, 'reports/generated_detail.html', context)


@login_required
@require_perm('reports_view_dashboards')
def generated_download(request, pk):
    """View / download a generated report. PDFs render inline in a new
    window (the calling template uses target=_blank); CSV / XLSX / etc.
    download as attachments."""
    orgs = get_user_organizations(request.user)
    report = get_object_or_404(
        GeneratedReport,
        pk=pk,
        organization__in=orgs
    )

    if not report.file:
        messages.error(request, 'Report file not found.')
        return redirect('reports:generated_detail', pk=pk)

    fmt = (report.format or '').lower()
    is_pdf = fmt == 'pdf' or report.file.name.lower().endswith('.pdf')
    response = FileResponse(report.file.open('rb'), as_attachment=not is_pdf)
    if is_pdf:
        # Force inline rendering in browser
        filename = report.file.name.split('/')[-1]
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Content-Type'] = 'application/pdf'
    return response


@login_required
@require_perm('reports_view_dashboards')
def generated_delete(request, pk):
    """Delete a generated report"""
    orgs = get_user_organizations(request.user)
    report = get_object_or_404(
        GeneratedReport,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        report.delete()
        messages.success(request, 'Report deleted successfully.')
        return redirect('reports:generated_list')

    context = {'report': report}
    return render(request, 'reports/generated_confirm_delete.html', context)


@login_required
@require_perm('reports_manage_scheduled')
def scheduled_list(request):
    """List all scheduled reports"""
    orgs = get_user_organizations(request.user)

    schedules = ScheduledReport.objects.filter(
        organization__in=orgs
    ).select_related('template', 'created_by').order_by('next_run')

    context = {
        'schedules': schedules,
    }

    return render(request, 'reports/scheduled_list.html', context)


@login_required
@require_perm('reports_manage_scheduled')
def scheduled_create(request):
    """Create a new scheduled report"""
    org = get_user_primary_organization(request.user)
    if not org:
        messages.error(request, 'You must be a member of an organization to create scheduled reports.')
        return redirect('reports:scheduled_list')

    orgs = get_user_organizations(request.user)

    if request.method == 'POST':
        name = request.POST.get('name')
        template_id = request.POST.get('template')
        frequency = request.POST.get('frequency')
        delivery_method = request.POST.get('delivery_method')
        recipients_str = request.POST.get('recipients', '')

        template = get_object_or_404(ReportTemplate, pk=template_id)
        recipients = [email.strip() for email in recipients_str.split(',') if email.strip()]

        # Calculate next run based on frequency
        next_run = timezone.now()
        if frequency == 'daily':
            next_run += timedelta(days=1)
        elif frequency == 'weekly':
            next_run += timedelta(weeks=1)
        elif frequency == 'monthly':
            next_run += timedelta(days=30)
        elif frequency == 'quarterly':
            next_run += timedelta(days=90)

        schedule = ScheduledReport.objects.create(
            name=name,
            template=template,
            organization=org,
            frequency=frequency,
            delivery_method=delivery_method,
            recipients=recipients,
            next_run=next_run,
            created_by=request.user
        )

        messages.success(request, f'Scheduled report "{name}" created successfully.')
        return redirect('reports:scheduled_list')

    templates = ReportTemplate.objects.filter(
        Q(organization__in=orgs) | Q(is_global=True)
    )

    context = {
        'action': 'Create',
        'templates': templates,
        'frequencies': ScheduledReport.FREQUENCY_CHOICES,
        'delivery_methods': ScheduledReport.DELIVERY_CHOICES,
    }

    return render(request, 'reports/scheduled_form.html', context)


@login_required
@require_perm('reports_manage_scheduled')
def scheduled_edit(request, pk):
    """Edit a scheduled report"""
    orgs = get_user_organizations(request.user)
    schedule = get_object_or_404(
        ScheduledReport,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        schedule.name = request.POST.get('name')
        template_id = request.POST.get('template')
        schedule.template = get_object_or_404(ReportTemplate, pk=template_id)
        schedule.frequency = request.POST.get('frequency')
        schedule.delivery_method = request.POST.get('delivery_method')
        recipients_str = request.POST.get('recipients', '')
        schedule.recipients = [email.strip() for email in recipients_str.split(',') if email.strip()]
        schedule.save()

        messages.success(request, f'Scheduled report "{schedule.name}" updated successfully.')
        return redirect('reports:scheduled_list')

    templates = ReportTemplate.objects.filter(
        Q(organization=schedule.organization) | Q(is_global=True)
    )

    context = {
        'schedule': schedule,
        'action': 'Edit',
        'templates': templates,
        'frequencies': ScheduledReport.FREQUENCY_CHOICES,
        'delivery_methods': ScheduledReport.DELIVERY_CHOICES,
        'recipients_str': ', '.join(schedule.recipients),
    }

    return render(request, 'reports/scheduled_form.html', context)


@login_required
@require_perm('reports_manage_scheduled')
def scheduled_delete(request, pk):
    """Delete a scheduled report"""
    orgs = get_user_organizations(request.user)
    schedule = get_object_or_404(
        ScheduledReport,
        pk=pk,
        organization__in=orgs
    )

    if request.method == 'POST':
        name = schedule.name
        schedule.delete()
        messages.success(request, f'Scheduled report "{name}" deleted successfully.')
        return redirect('reports:scheduled_list')

    context = {'schedule': schedule}
    return render(request, 'reports/scheduled_confirm_delete.html', context)


@login_required
@require_perm('reports_manage_scheduled')
def scheduled_toggle(request, pk):
    """Toggle a scheduled report active/inactive"""
    orgs = get_user_organizations(request.user)
    schedule = get_object_or_404(
        ScheduledReport,
        pk=pk,
        organization__in=orgs
    )

    schedule.is_active = not schedule.is_active
    schedule.save()

    status = 'enabled' if schedule.is_active else 'disabled'
    messages.success(request, f'Scheduled report "{schedule.name}" {status}.')

    return redirect('reports:scheduled_list')


@login_required
@require_perm('reports_view_dashboards')
def analytics_overview(request):
    """Analytics overview dashboard"""
    orgs = get_user_organizations(request.user)

    # Get recent events
    recent_events = AnalyticsEvent.objects.filter(
        organization__in=orgs
    ).select_related('user')[:100]

    # Event counts by category
    events_by_category = AnalyticsEvent.objects.filter(
        organization__in=orgs,
        timestamp__gte=timezone.now() - timedelta(days=30)
    ).values('event_category').annotate(count=Count('id'))

    # Most active users
    active_users = AnalyticsEvent.objects.filter(
        organization__in=orgs,
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).values('user__username').annotate(count=Count('id')).order_by('-count')[:10]

    context = {
        'recent_events': recent_events,
        'events_by_category': events_by_category,
        'active_users': active_users,
    }

    return render(request, 'reports/analytics_overview.html', context)


@login_required
@require_perm('reports_view_dashboards')
def analytics_events(request):
    """Detailed analytics events list"""
    orgs = get_user_organizations(request.user)

    events = AnalyticsEvent.objects.filter(
        organization__in=orgs
    ).select_related('user').order_by('-timestamp')

    # Apply filters
    category = request.GET.get('category')
    if category:
        events = events.filter(event_category=category)

    event_name = request.GET.get('event')
    if event_name:
        events = events.filter(event_name__icontains=event_name)

    # Pagination
    events = events[:500]  # Limit to 500 most recent

    context = {
        'events': events,
        'categories': AnalyticsEvent.CATEGORY_CHOICES,
    }

    return render(request, 'reports/analytics_events.html', context)


# ---------------------------------------------------------------------------
# PSA reports — Workstream 6
# ---------------------------------------------------------------------------

@login_required
def psa_reports_list(request):
    """Catalog of PSA reports — click one to run it ad-hoc against the
    user's accessible orgs (or a specific picked client)."""
    from .generators import PSA_REPORT_DEFINITIONS
    return render(request, 'reports/psa_list.html', {
        'definitions': PSA_REPORT_DEFINITIONS,
    })


@login_required
def psa_report_run(request, report_type):
    """Run an ad-hoc PSA report. URL params:
       ?days=<n>&client=<org_id>
    Renders the result inline. CSV export via &format=csv."""
    from .generators import get_report_generator, PSA_REPORT_DEFINITIONS
    cls = get_report_generator(report_type)
    if cls is None or not report_type.startswith('psa_'):
        messages.error(request, 'Unknown PSA report.')
        return redirect('reports:psa_reports_list')

    # Tenant scope
    from core.models import Organization
    client_id = request.GET.get('client') or ''
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        clients = Organization.objects.filter(is_active=True).order_by('name')
    else:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True).values_list('organization_id', flat=True))
        clients = Organization.objects.filter(id__in=ids, is_active=True).order_by('name')

    org = None
    if client_id:
        org = clients.filter(pk=client_id).first()
        if org is None:
            messages.error(request, "You don't have access to that client.")
            return redirect('reports:psa_reports_list')

    parameters = {'days': request.GET.get('days', 30)}
    generator = cls(organization=org, parameters=parameters)
    data = generator.generate()

    definition = next((d for d in PSA_REPORT_DEFINITIONS if d['type'] == report_type), None)

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        return _psa_report_csv(report_type, data)

    return render(request, 'reports/psa_run.html', {
        'definition': definition,
        'data': data,
        'clients': clients,
        'selected_org': org,
        'days': parameters['days'],
        'report_type': report_type,
    })


def _psa_report_csv(report_type, data):
    """Stream a CSV of the rows. Column set per report."""
    import csv as _csv
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{report_type}.csv"'
    writer = _csv.writer(response)

    if 'rows' in data and isinstance(data['rows'], list):
        rows = data['rows']
        if not rows:
            writer.writerow(['(no data)'])
            return response
        keys = list(rows[0].keys())
        writer.writerow(keys)
        for r in rows:
            writer.writerow([r.get(k, '') for k in keys])
        return response

    if 'by_queue' in data:  # PSATicketsByDimensionReport
        writer.writerow(['Dimension', 'Bucket', 'Count'])
        for r in data.get('by_queue', []):
            writer.writerow(['queue', r.get('queue__name'), r.get('count')])
        for r in data.get('by_type', []):
            writer.writerow(['type', r.get('ticket_type__name'), r.get('count')])
        for r in data.get('by_priority', []):
            writer.writerow(['priority', f"{r.get('priority__code', '')} {r.get('priority__name', '')}", r.get('count')])
        return response

    writer.writerow(['key', 'value'])
    for k, v in data.items():
        writer.writerow([k, v])
    return response


# ---------------------------------------------------------------------------
# Phase 3.1 — Profitability by Client (PSA)
# ---------------------------------------------------------------------------

def _is_staff_or_super(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff)


def _parse_date(s, fallback):
    """Parse YYYY-MM-DD safely; fall back when missing or invalid."""
    if not s:
        return fallback
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return fallback


@login_required
@require_perm('reports_view_financial')
def psa_profitability_by_client(request):
    """
    Per-client profitability report — revenue, cost, margin over a
    user-chosen window. CSV via ?format=csv. Pulls from the canonical
    `reports.queries` layer.
    """
    from .queries import (
        profitability_by_client,
        DEFAULT_LOADED_RATE,
    )

    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    # Loaded rate override
    loaded_rate_raw = (request.GET.get('loaded_rate') or '').strip()
    loaded_rate = DEFAULT_LOADED_RATE
    if loaded_rate_raw:
        try:
            loaded_rate = Decimal(loaded_rate_raw)
        except (InvalidOperation, ValueError):
            loaded_rate = DEFAULT_LOADED_RATE

    rows = profitability_by_client(start_date, end_date,
                                   default_loaded_rate=loaded_rate)

    # Aggregates
    total_revenue = sum(r['revenue'] for r in rows)
    total_cost = sum(r['cost'] for r in rows)
    total_margin = total_revenue - total_cost
    blended_margin_pct = (total_margin / total_revenue * 100) if total_revenue else 0.0

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="profitability-by-client-'
            f'{start_date.isoformat()}-{end_date.isoformat()}.csv"'
        )
        writer = _csv.writer(response)
        writer.writerow(['Client', 'Hours', 'Revenue', 'Cost', 'Margin', 'Margin %'])
        for r in rows:
            writer.writerow([
                r['client_name'],
                f"{r['hours']:.2f}",
                f"{r['revenue']:.2f}",
                f"{r['cost']:.2f}",
                f"{r['margin']:.2f}",
                f"{r['margin_pct']:.1f}",
            ])
        # Totals row
        writer.writerow([
            'TOTAL', '',
            f"{total_revenue:.2f}", f"{total_cost:.2f}",
            f"{total_margin:.2f}", f"{round(blended_margin_pct, 1):.1f}",
        ])
        return response

    context = {
        'rows': rows,
        'start_date': start_date,
        'end_date': end_date,
        'loaded_rate': loaded_rate,
        'default_loaded_rate': DEFAULT_LOADED_RATE,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_margin': total_margin,
        'blended_margin_pct': round(blended_margin_pct, 1),
    }
    return render(request, 'reports/psa_profitability_by_client.html', context)


# ---------------------------------------------------------------------------
# Phase 3.2 — Profitability by Tech / Contract / Project (PSA)
# ---------------------------------------------------------------------------

def _profitability_window(request):
    """Parse start/end/loaded_rate query params → tuple."""
    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    loaded_rate_raw = (request.GET.get('loaded_rate') or '').strip()
    from .queries import DEFAULT_LOADED_RATE
    loaded_rate = DEFAULT_LOADED_RATE
    if loaded_rate_raw:
        try:
            loaded_rate = Decimal(loaded_rate_raw)
        except (InvalidOperation, ValueError):
            loaded_rate = DEFAULT_LOADED_RATE
    return start_date, end_date, loaded_rate, DEFAULT_LOADED_RATE


def _csv_response(filename, header, rows, totals_row=None):
    """Helper: stream a CSV with a header, rows, and an optional totals row."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = _csv.writer(response)
    writer.writerow(header)
    for r in rows:
        writer.writerow(r)
    if totals_row:
        writer.writerow(totals_row)
    return response


@login_required
@require_perm('reports_view_financial')
def psa_profitability_by_tech(request):
    """Per-tech profitability — hours / cost / attributed revenue / margin /
    utilization %. CSV export via ?format=csv."""
    from .queries import profitability_by_tech

    start_date, end_date, loaded_rate, default_rate = _profitability_window(request)
    rows = profitability_by_tech(start_date, end_date,
                                 default_loaded_rate=loaded_rate)

    total_revenue = sum(r['attributed_revenue'] for r in rows)
    total_cost = sum(r['cost'] for r in rows)
    total_margin = total_revenue - total_cost
    blended_margin_pct = (total_margin / total_revenue * 100) if total_revenue else 0.0

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        return _csv_response(
            f'profitability-by-tech-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            ['Tech', 'Hours', 'Cost', 'Attributed Revenue', 'Margin', 'Margin %', 'Utilization %'],
            [[
                r['tech_username'],
                f"{r['hours']:.2f}",
                f"{r['cost']:.2f}",
                f"{r['attributed_revenue']:.2f}",
                f"{r['margin']:.2f}",
                f"{r['margin_pct']:.1f}",
                f"{r['utilization_pct']:.1f}",
            ] for r in rows],
            totals_row=[
                'TOTAL', '',
                f"{total_cost:.2f}", f"{total_revenue:.2f}",
                f"{total_margin:.2f}", f"{round(blended_margin_pct, 1):.1f}", '',
            ],
        )

    return render(request, 'reports/psa_profitability_by_tech.html', {
        'rows': rows,
        'start_date': start_date,
        'end_date': end_date,
        'loaded_rate': loaded_rate,
        'default_loaded_rate': default_rate,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_margin': total_margin,
        'blended_margin_pct': round(blended_margin_pct, 1),
    })


@login_required
@require_perm('reports_view_financial')
def psa_profitability_by_contract(request):
    """Per-contract profitability."""
    from .queries import profitability_by_contract

    start_date, end_date, loaded_rate, default_rate = _profitability_window(request)
    rows = profitability_by_contract(start_date, end_date,
                                     default_loaded_rate=loaded_rate)

    total_revenue = sum(r['revenue'] for r in rows)
    total_cost = sum(r['cost'] for r in rows)
    total_margin = total_revenue - total_cost
    blended_margin_pct = (total_margin / total_revenue * 100) if total_revenue else 0.0

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        return _csv_response(
            f'profitability-by-contract-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            ['Contract', 'Client', 'Hours', 'Revenue', 'Cost', 'Margin', 'Margin %'],
            [[
                r['contract_name'], r['client_name'],
                f"{r['hours']:.2f}", f"{r['revenue']:.2f}", f"{r['cost']:.2f}",
                f"{r['margin']:.2f}", f"{r['margin_pct']:.1f}",
            ] for r in rows],
            totals_row=[
                'TOTAL', '', '',
                f"{total_revenue:.2f}", f"{total_cost:.2f}",
                f"{total_margin:.2f}", f"{round(blended_margin_pct, 1):.1f}",
            ],
        )

    return render(request, 'reports/psa_profitability_by_contract.html', {
        'rows': rows,
        'start_date': start_date,
        'end_date': end_date,
        'loaded_rate': loaded_rate,
        'default_loaded_rate': default_rate,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_margin': total_margin,
        'blended_margin_pct': round(blended_margin_pct, 1),
    })


@login_required
@require_perm('reports_view_financial')
def psa_profitability_by_project(request):
    """Per-project profitability."""
    from .queries import profitability_by_project

    start_date, end_date, loaded_rate, default_rate = _profitability_window(request)
    rows = profitability_by_project(start_date, end_date,
                                    default_loaded_rate=loaded_rate)

    total_revenue = sum(r['revenue'] for r in rows)
    total_cost = sum(r['cost'] for r in rows)
    total_margin = total_revenue - total_cost
    blended_margin_pct = (total_margin / total_revenue * 100) if total_revenue else 0.0

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        return _csv_response(
            f'profitability-by-project-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            ['Project', 'Client', 'Hours', 'Revenue', 'Cost', 'Margin', 'Margin %'],
            [[
                r['project_name'], r['client_name'],
                f"{r['hours']:.2f}", f"{r['revenue']:.2f}", f"{r['cost']:.2f}",
                f"{r['margin']:.2f}", f"{r['margin_pct']:.1f}",
            ] for r in rows],
            totals_row=[
                'TOTAL', '', '',
                f"{total_revenue:.2f}", f"{total_cost:.2f}",
                f"{total_margin:.2f}", f"{round(blended_margin_pct, 1):.1f}",
            ],
        )

    return render(request, 'reports/psa_profitability_by_project.html', {
        'rows': rows,
        'start_date': start_date,
        'end_date': end_date,
        'loaded_rate': loaded_rate,
        'default_loaded_rate': default_rate,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_margin': total_margin,
        'blended_margin_pct': round(blended_margin_pct, 1),
    })


# ---------------------------------------------------------------------------
# Phase 3.3 — Effective hourly rate + Revenue leakage (PSA)
# ---------------------------------------------------------------------------

def _median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


@login_required
@require_perm('reports_view_financial')
def psa_effective_hourly_rate(request):
    """
    Effective hourly rate report — `revenue ÷ billable_hours` per client
    (default tab) or per tech. Two tabs share the same date-range picker.
    CSV export per tab via `?format=csv&tab=client|tech`.
    """
    from .queries import (
        effective_hourly_rate_by_client,
        effective_hourly_rate_by_tech,
    )

    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    tab = (request.GET.get('tab') or 'client').lower()
    if tab not in ('client', 'tech'):
        tab = 'client'

    client_rows = effective_hourly_rate_by_client(start_date, end_date)
    tech_rows = effective_hourly_rate_by_tech(start_date, end_date)

    # Summary stats are computed on the active tab's rates (excluding
    # zero-rates from rows with no billable hours so they don't drag
    # avg/median to zero).
    active_rows = client_rows if tab == 'client' else tech_rows
    rate_vals = [r['effective_rate'] for r in active_rows
                 if r['effective_rate'] > 0]
    avg_rate = round(sum(rate_vals) / len(rate_vals), 2) if rate_vals else 0.0
    highest = max(rate_vals) if rate_vals else 0.0
    lowest = min(rate_vals) if rate_vals else 0.0
    median = round(_median(rate_vals), 2)

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        if tab == 'tech':
            return _csv_response(
                f'effective-rate-by-tech-{start_date.isoformat()}-{end_date.isoformat()}.csv',
                ['Tech', 'Billable Hours', 'Attributed Revenue',
                 'Effective Rate ($/hr)', 'Cost Rate ($/hr)', 'Realization %'],
                [[
                    r['tech_username'],
                    f"{r['billable_hours']:.2f}",
                    f"{r['attributed_revenue']:.2f}",
                    f"{r['effective_rate']:.2f}",
                    f"{r['cost_rate']:.2f}",
                    f"{r['realization_pct']:.1f}",
                ] for r in tech_rows],
            )
        return _csv_response(
            f'effective-rate-by-client-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            ['Client', 'Revenue', 'Billable Hours', 'Non-billable Hours',
             'Effective Rate ($/hr)', 'Utilization Ratio'],
            [[
                r['client_name'],
                f"{r['revenue']:.2f}",
                f"{r['billable_hours']:.2f}",
                f"{r['nonbillable_hours']:.2f}",
                f"{r['effective_rate']:.2f}",
                f"{r['utilization_ratio']:.3f}",
            ] for r in client_rows],
        )

    return render(request, 'reports/psa_effective_hourly_rate.html', {
        'tab': tab,
        'client_rows': client_rows,
        'tech_rows': tech_rows,
        'start_date': start_date,
        'end_date': end_date,
        'avg_rate': avg_rate,
        'highest': highest,
        'lowest': lowest,
        'median': median,
    })


@login_required
@require_perm('reports_view_financial')
def psa_revenue_leakage(request):
    """
    Revenue leakage report — three categories of "money you should have
    collected but didn't" on one page. Stale-days input + CSV export
    that combines all three sections with a section column.
    """
    from .queries import revenue_leakage

    today = date.today()
    default_start = today - timedelta(days=180)
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    try:
        stale_days = max(1, int(request.GET.get('stale_days') or 30))
    except (TypeError, ValueError):
        stale_days = 30

    data = revenue_leakage(start_date, end_date, stale_days=stale_days)

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="revenue-leakage-'
            f'{start_date.isoformat()}-{end_date.isoformat()}.csv"'
        )
        writer = _csv.writer(response)
        writer.writerow([
            'Section', 'Client', 'Detail', 'Quantity', 'Amount',
        ])
        for r in data['stale_unbilled']:
            writer.writerow([
                'Stale Unbilled', r['client_name'],
                f"oldest {r['oldest_at']}, {r['entry_count']} entries",
                f"{r['hours_at_risk']:.2f} h",
                f"{r['amount_at_risk']:.2f}",
            ])
        for r in data['expired_blocks']:
            writer.writerow([
                'Expired Block', r['client_name'], r['contract_name'],
                f"{r['unused_hours']:.2f} h unused",
                f"{r['unused_value']:.2f}",
            ])
        for r in data['stuck_drafts']:
            writer.writerow([
                'Stuck Draft', r['client_name'], r['invoice_number'],
                f"{r['days_stuck']} days stuck",
                f"{r['amount']:.2f}",
            ])
        writer.writerow([
            'TOTAL', '', '', '',
            f"{data['totals']['grand_total']:.2f}",
        ])
        return response

    return render(request, 'reports/psa_revenue_leakage.html', {
        'data': data,
        'start_date': start_date,
        'end_date': end_date,
        'stale_days': stale_days,
    })


# ---------------------------------------------------------------------------
# Phase 3.4 — SLA trends + Margin analytics by service line
# ---------------------------------------------------------------------------

@login_required
@require_perm('reports_view_sla')
def psa_sla_trends(request):
    """
    SLA breach trend report — per-priority response + resolution breach %
    over a bucketed window (day / week / month). Side panel lists the
    top-N clients by ticket volume with their breach %.
    CSV via ?format=csv&tab=summary|by_client.
    """
    from .queries import sla_trend_by_priority, sla_trend_by_client

    today = date.today()
    default_start = today - timedelta(days=89)  # last 90 days inclusive
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    bucket = (request.GET.get('bucket') or 'week').lower()
    if bucket not in ('day', 'week', 'month'):
        bucket = 'week'

    trend = sla_trend_by_priority(start_date, end_date, bucket=bucket)
    top_clients = sla_trend_by_client(start_date, end_date, top_n=10)

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        tab = (request.GET.get('tab') or 'summary').lower()
        if tab == 'by_client':
            return _csv_response(
                f'sla-trend-by-client-{start_date.isoformat()}-{end_date.isoformat()}.csv',
                ['Client', 'Tickets', 'Response Breaches', 'Resolution Breaches',
                 'Response %', 'Resolution %'],
                [[
                    r['client_name'], r['tickets'],
                    r['response_breaches'], r['resolution_breaches'],
                    f"{r['response_pct']:.1f}", f"{r['resolution_pct']:.1f}",
                ] for r in top_clients],
            )
        # Default: per-priority summary
        return _csv_response(
            f'sla-trend-summary-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            ['Priority', 'Tickets', 'Response Breaches', 'Resolution Breaches',
             'Response %', 'Resolution %'],
            [[
                p,
                trend['totals_by_priority'][p]['tickets'],
                trend['totals_by_priority'][p]['response_breaches'],
                trend['totals_by_priority'][p]['resolution_breaches'],
                f"{trend['totals_by_priority'][p]['response_pct']:.1f}",
                f"{trend['totals_by_priority'][p]['resolution_pct']:.1f}",
            ] for p in trend['priorities']],
        )

    # Pre-encode chart payloads as JSON for safe embedding in <script>.
    response_chart = {
        'labels': trend['buckets'],
        'series': [
            {
                'name': p,
                'data': [row['response_pct'] for row in trend['series'][p]],
            }
            for p in trend['priorities']
        ],
    }
    resolution_chart = {
        'labels': trend['buckets'],
        'series': [
            {
                'name': p,
                'data': [row['resolution_pct'] for row in trend['series'][p]],
            }
            for p in trend['priorities']
        ],
    }
    response_chart_json = json.dumps(response_chart).replace('</', '<\\/')
    resolution_chart_json = json.dumps(resolution_chart).replace('</', '<\\/')

    # Build a totals list ordered by the priorities list for the template.
    totals_rows = [
        {
            'priority': p,
            **trend['totals_by_priority'][p],
        }
        for p in trend['priorities']
    ]

    return render(request, 'reports/psa_sla_trends.html', {
        'start_date': start_date,
        'end_date': end_date,
        'bucket': bucket,
        'priorities': trend['priorities'],
        'totals_rows': totals_rows,
        'top_clients': top_clients,
        'response_chart_json': response_chart_json,
        'resolution_chart_json': resolution_chart_json,
        'has_buckets': bool(trend['buckets']),
    })


@login_required
@require_perm('reports_view_financial')
def psa_margin_analytics(request):
    """
    Margin grouped by service-line dimension — ticket_type / closure_category
    / queue. Bar chart + sortable table + CSV export.
    """
    from .queries import margin_analytics_by_service_line

    today = date.today()
    default_start = today - timedelta(days=30)
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    dimension = (request.GET.get('dimension') or 'ticket_type').lower()
    if dimension not in ('ticket_type', 'closure_category', 'queue'):
        dimension = 'ticket_type'

    rows = margin_analytics_by_service_line(start_date, end_date,
                                            dimension=dimension)

    total_revenue = sum(r['revenue'] for r in rows)
    total_cost = sum(r['cost'] for r in rows)
    total_margin = total_revenue - total_cost
    blended_margin_pct = (total_margin / total_revenue * 100) if total_revenue else 0.0

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        return _csv_response(
            f'margin-analytics-{dimension}-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            [dimension.replace('_', ' ').title(), 'Tickets', 'Hours',
             'Revenue', 'Cost', 'Margin', 'Margin %'],
            [[
                r['label'], r['tickets'], f"{r['hours']:.2f}",
                f"{r['revenue']:.2f}", f"{r['cost']:.2f}",
                f"{r['margin']:.2f}", f"{r['margin_pct']:.1f}",
            ] for r in rows],
            totals_row=[
                'TOTAL', '', '',
                f"{total_revenue:.2f}", f"{total_cost:.2f}",
                f"{total_margin:.2f}", f"{round(blended_margin_pct, 1):.1f}",
            ],
        )

    chart_payload = {
        'labels': [r['label'] for r in rows],
        'series': [
            {'name': 'Revenue', 'data': [r['revenue'] for r in rows]},
            {'name': 'Cost', 'data': [r['cost'] for r in rows]},
        ],
    }
    chart_json = json.dumps(chart_payload).replace('</', '<\\/')

    dimension_choices = [
        ('ticket_type', 'Ticket Type'),
        ('closure_category', 'Closure Category'),
        ('queue', 'Queue'),
    ]

    return render(request, 'reports/psa_margin_analytics.html', {
        'rows': rows,
        'start_date': start_date,
        'end_date': end_date,
        'dimension': dimension,
        'dimension_choices': dimension_choices,
        'chart_json': chart_json,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'total_margin': total_margin,
        'blended_margin_pct': round(blended_margin_pct, 1),
    })


# ---------------------------------------------------------------------------
# Phase 3.6 wave A — Wallboard + Executive scorecard
# ---------------------------------------------------------------------------

@login_required
@require_perm('reports_view_dashboards')
def wallboard(request):
    """TV-ready wallboard view. Refreshes via JS poll to /reports/wallboard/data/."""
    try:
        refresh = int(request.GET.get('refresh') or 30)
    except (TypeError, ValueError):
        refresh = 30
    refresh = max(5, min(refresh, 600))
    return render(request, 'reports/wallboard.html', {
        'refresh_interval_seconds': refresh,
    })


@login_required
@require_perm('reports_view_dashboards')
def wallboard_data(request):
    """JSON endpoint polled by the wallboard page every N seconds."""
    from psa.models import Ticket
    from django.contrib.auth.models import User

    today = timezone.now().date()

    # Mega-tile counts
    open_qs = Ticket.objects.filter(status__is_terminal=False)
    sla_overdue = open_qs.filter(resolution_due_at__lt=timezone.now()).count()
    unassigned = open_qs.filter(assigned_to__isnull=True).count()
    p1 = open_qs.filter(priority__code='P1').count()
    opened_today = Ticket.objects.filter(created_at__date=today).count()
    closed_today = Ticket.objects.filter(
        closed_at__date=today, status__is_terminal=True
    ).count()
    open_total = open_qs.count()

    # Tile color logic — green/amber/red banding
    def color(n, low, high):
        if n < low:
            return 'success'
        if n < high:
            return 'warning'
        return 'danger'

    tiles = [
        {'label': 'Open Tickets', 'value': open_total,
         'color': color(open_total, 50, 100), 'icon': 'fa-ticket'},
        {'label': 'SLA Overdue', 'value': sla_overdue,
         'color': color(sla_overdue, 1, 5), 'icon': 'fa-triangle-exclamation'},
        {'label': 'Unassigned', 'value': unassigned,
         'color': color(unassigned, 5, 15), 'icon': 'fa-circle-question'},
        {'label': 'P1 Open', 'value': p1,
         'color': color(p1, 1, 3), 'icon': 'fa-fire'},
        {'label': 'Opened Today', 'value': opened_today,
         'color': 'info', 'icon': 'fa-arrow-up'},
        {'label': 'Closed Today', 'value': closed_today,
         'color': 'success', 'icon': 'fa-check'},
    ]

    # Recent tickets ticker (5 most recent)
    recent = (
        Ticket.objects
        .select_related('priority', 'organization')
        .order_by('-created_at')[:5]
    )
    recent_data = []
    for t in recent:
        pcode = t.priority.code if t.priority_id else ''
        priority_color = {
            'P1': 'danger', 'P2': 'warning', 'P3': 'info',
            'P4': 'secondary', 'P5': 'light',
        }.get(pcode, 'secondary')
        recent_data.append({
            'ticket_number': t.ticket_number,
            'subject': (t.subject or '')[:80],
            'priority': pcode,
            'priority_color': priority_color,
            'organization': t.organization.name if t.organization_id else '—',
            'created_ago_min': int(
                (timezone.now() - t.created_at).total_seconds() / 60
            ),
        })

    # On-shift techs — uses UserProfile.is_working_now()
    techs_on_shift = []
    for u in User.objects.filter(
        is_active=True, is_staff=True
    ).exclude(username='AnonymousUser'):
        profile = getattr(u, 'profile', None)
        if profile is None:
            continue
        try:
            if profile.is_working_now():
                techs_on_shift.append({'username': u.username})
        except Exception:
            # Be defensive — never let a bad profile break the wallboard.
            continue

    return JsonResponse({
        'tiles': tiles,
        'recent_tickets': recent_data,
        'techs_on_shift': techs_on_shift,
        'as_of': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


@login_required
@require_perm('reports_view_financial')
def exec_scorecard(request):
    """Rolling 30d executive scorecard for the owner.

    Single-page MSP KPI summary — hero cards + trend chart + top-clients
    / top-techs tables + service-line margin pie. Print-friendly.
    """
    from datetime import date as _date, timedelta as _td
    from psa.models import Ticket, TicketTimeEntry, Invoice
    from .queries import (
        revenue_by_client, hours_minutes_by_client, hours_minutes_by_tech,
        sla_trend_by_priority, margin_analytics_by_service_line,
    )

    today = _date.today()
    start_30 = today - _td(days=29)
    prior_start = today - _td(days=59)
    prior_end = start_30 - _td(days=1)

    # --- Hero KPIs ----------------------------------------------------------
    rev_30 = sum(r['invoiced'] for r in revenue_by_client(start_30, today))
    rev_prior = sum(r['invoiced'] for r in revenue_by_client(prior_start, prior_end))
    rev_trend_pct = ((rev_30 - rev_prior) / rev_prior * 100) if rev_prior else 0.0

    hrs_rows = hours_minutes_by_client(start_30, today)
    total_billable_min = sum(r['billable_minutes'] for r in hrs_rows)
    total_billable_hrs = total_billable_min / 60.0
    realized_rate = (rev_30 / total_billable_hrs) if total_billable_hrs else 0.0

    open_tickets = Ticket.objects.filter(status__is_terminal=False).count()

    # SLA breach %
    sla = sla_trend_by_priority(start_30, today, bucket='month')
    total_tix = sum(t['tickets'] for t in sla['totals_by_priority'].values())
    total_breach = sum(t['resolution_breaches']
                       for t in sla['totals_by_priority'].values())
    sla_breach_pct = (total_breach / total_tix * 100) if total_tix else 0.0

    # MTTR — avg close time over 30d
    closed = Ticket.objects.filter(
        closed_at__gte=timezone.now() - timedelta(days=30),
        status__is_terminal=True,
    ).exclude(closed_at__isnull=True)
    mttr_secs = 0
    cnt = 0
    for t in closed:
        mttr_secs += (t.closed_at - t.created_at).total_seconds()
        cnt += 1
    mttr_hours = (mttr_secs / cnt / 3600) if cnt else 0.0

    active_clients = (
        Ticket.objects
        .filter(created_at__date__gte=start_30)
        .values('organization').distinct().count()
    )

    # Tech utilization (avg actual hrs / target hrs across all techs with targets)
    from resourcing.models import BillableTarget
    util_pcts = []
    for bt in BillableTarget.objects.filter(is_active=True).select_related('user'):
        target_hrs = float(bt.target_hours_per_week) * 4.3  # ~30 days
        actual_min = TicketTimeEntry.objects.filter(
            user=bt.user, started_at__date__gte=start_30,
        ).aggregate(s=Sum('duration_minutes'))['s'] or 0
        actual_hrs = actual_min / 60.0
        if target_hrs:
            util_pcts.append((actual_hrs / target_hrs) * 100)
    avg_util = sum(util_pcts) / len(util_pcts) if util_pcts else 0.0

    kpis = [
        {'label': 'Revenue (30d)', 'value': f'${rev_30:,.0f}',
         'trend_pct': round(rev_trend_pct, 1), 'icon': 'fa-dollar-sign'},
        {'label': 'Billable Hours', 'value': f'{total_billable_hrs:,.0f}h',
         'trend_pct': None, 'icon': 'fa-clock'},
        {'label': 'Realized Rate', 'value': f'${realized_rate:,.0f}/hr',
         'trend_pct': None, 'icon': 'fa-tachometer-alt'},
        {'label': 'Open Tickets', 'value': str(open_tickets),
         'trend_pct': None, 'icon': 'fa-ticket'},
        {'label': 'SLA Breach %', 'value': f'{sla_breach_pct:.1f}%',
         'trend_pct': None, 'icon': 'fa-triangle-exclamation'},
        {'label': 'Avg MTTR', 'value': f'{mttr_hours:.1f}h',
         'trend_pct': None, 'icon': 'fa-stopwatch'},
        {'label': 'Active Clients', 'value': str(active_clients),
         'trend_pct': None, 'icon': 'fa-building'},
        {'label': 'Tech Utilization', 'value': f'{avg_util:.0f}%',
         'trend_pct': None, 'icon': 'fa-users-gear'},
    ]

    # Top 5 clients by revenue
    top_clients = sorted(
        revenue_by_client(start_30, today),
        key=lambda r: r['invoiced'], reverse=True,
    )[:5]
    # Top 5 techs by billable hours
    top_techs = sorted(
        hours_minutes_by_tech(start_30, today),
        key=lambda r: r['billable_minutes'], reverse=True,
    )[:5]
    for r in top_techs:
        r['billable_hours'] = round(r['billable_minutes'] / 60.0, 1)

    # Margin by service line — top 5 + Other
    margin_rows = margin_analytics_by_service_line(
        start_30, today, dimension='ticket_type'
    )
    pie_data = []
    for r in margin_rows[:5]:
        pie_data.append({'label': r['label'], 'value': r['margin']})
    if len(margin_rows) > 5:
        other_total = sum(r['margin'] for r in margin_rows[5:])
        pie_data.append({'label': 'Other', 'value': other_total})

    # 30d daily revenue + ticket counts for the dual-line chart
    days = [start_30 + timedelta(days=i) for i in range(30)]
    rev_by_day = {d: 0.0 for d in days}
    for inv in Invoice.objects.filter(
        invoice_date__gte=start_30, invoice_date__lte=today,
        status__in=['sent', 'partial', 'paid', 'overdue'],
    ):
        if inv.invoice_date in rev_by_day:
            rev_by_day[inv.invoice_date] += float(inv.total or 0)
    tix_by_day = {d: 0 for d in days}
    for t in Ticket.objects.filter(
        created_at__date__gte=start_30, created_at__date__lte=today,
    ):
        d = t.created_at.date()
        if d in tix_by_day:
            tix_by_day[d] += 1

    chart = {
        'labels': [d.strftime('%m/%d') for d in days],
        'revenue': [round(rev_by_day[d], 2) for d in days],
        'tickets': [tix_by_day[d] for d in days],
    }
    chart_json = json.dumps(chart).replace('</', '<\\/')
    pie_json = json.dumps(pie_data).replace('</', '<\\/')

    return render(request, 'reports/exec_scorecard.html', {
        'kpis': kpis,
        'top_clients': top_clients,
        'top_techs': top_techs,
        'pie_data': pie_data,
        'pie_json': pie_json,
        'chart': chart,
        'chart_json': chart_json,
        'as_of': timezone.now(),
        'window_start': start_30,
        'window_end': today,
    })


# ---------------------------------------------------------------------------
# Phase 3.6 wave B — Client-health score report (v3.17.147)
# ---------------------------------------------------------------------------

@login_required
@require_perm('reports_view_financial')
def psa_client_health(request):
    """Composite client-health score report. CSV via ?format=csv."""
    from .queries import client_health_scores_all
    rows = client_health_scores_all()
    summary = {
        'healthy': sum(1 for r in rows if r['category'] == 'healthy'),
        'at_risk': sum(1 for r in rows if r['category'] == 'at_risk'),
        'trouble': sum(1 for r in rows if r['category'] == 'trouble'),
        'total': len(rows),
    }
    if (request.GET.get('format') or '').lower() == 'csv':
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="client_health.csv"'
        w = _csv.writer(resp)
        w.writerow(['Client', 'Score', 'Category',
                    'SLA', 'Velocity', 'Aging', 'Engagement', 'NPS',
                    'Tickets 30d', 'Over 60d ($)'])
        for r in rows:
            c = r['components']
            m = r['metrics']
            w.writerow([
                r['client_name'], r['score'], r['category'],
                c['sla'], c['velocity'], c['aging'], c['engagement'], c['nps'],
                m['total_tickets_30d'], m['over_60_days'],
            ])
        return resp
    return render(request, 'reports/psa_client_health.html', {
        'rows': rows, 'summary': summary,
    })


# ---------------------------------------------------------------------------
# Phase 5.2 — CRM sales funnel report
# ---------------------------------------------------------------------------

@login_required
@require_perm('crm_view_forecast')
def crm_sales_funnel(request):
    """
    Visual funnel from Leads → Qualified → Opportunities → Proposal → Closed
    Won, with stage-to-stage conversion rates. Date-range selector via
    ?days=7|30|90|YTD; defaults to 30.
    """
    from .queries import sales_funnel
    today = date.today()
    days_raw = (request.GET.get('days') or '30').strip()
    if days_raw.upper() == 'YTD':
        days_label = 'YTD'
        start = date(today.year, 1, 1)
        days = (today - start).days + 1
    else:
        try:
            days = max(1, int(days_raw))
        except (TypeError, ValueError):
            days = 30
        days_label = str(days)
        start = today - timedelta(days=days - 1)
    funnel = sales_funnel(start, today)
    return render(request, 'reports/crm_sales_funnel.html', {
        'funnel': funnel,
        'days': days,
        'days_label': days_label,
        'start': start,
        'end': today,
    })


# ---------------------------------------------------------------------------
# Phase 9.4 — Security alert MTTA report
# ---------------------------------------------------------------------------

@login_required
@require_perm('reports_view_sla')
def security_alert_mtta_report(request):
    """
    Mean Time To Acknowledge for security alerts in a date window,
    bucketed per (client × vendor). CSV via ?format=csv.
    """
    from .queries import security_alert_mtta

    today = date.today()
    default_start = today - timedelta(days=29)
    start_date = _parse_date(request.GET.get('start'), default_start)
    end_date = _parse_date(request.GET.get('end'), today)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    rows = security_alert_mtta(start_date, end_date)

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        return _csv_response(
            f'security-alert-mtta-{start_date.isoformat()}-{end_date.isoformat()}.csv',
            ['Client', 'Vendor', 'Count', 'Avg MTTA (min)', 'Unacked'],
            [[
                r['client_name'], r['vendor'], r['count'],
                f"{r['avg_mtta_minutes']:.1f}" if r['avg_mtta_minutes'] is not None else '—',
                r['unack_count'],
            ] for r in rows],
        )

    return render(request, 'reports/security_alert_mtta.html', {
        'rows': rows,
        'start_date': start_date,
        'end_date': end_date,
    })


# ---------------------------------------------------------------------------
# v3.17.211 — Configurable wallboards
# ---------------------------------------------------------------------------

def _user_can_see_wallboards(user, organization):
    """
    Wallboards are visible to:
      - superuser / staff users — always (any org board, plus globals).
      - any other user — only their own active-membership orgs.

    `organization=None` means a v3.17.216 "global" board: visible
    only to staff/superuser. Plain org members never see globals.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_staff', False):
        return True
    if organization is None:
        return False
    return user.memberships.filter(
        organization=organization, is_active=True,
    ).exists()


@login_required
@require_perm('reports_view_dashboards')
def wallboard_list(request):
    """
    List wallboards. Org-scoped boards are filtered to the user's accessible
    orgs; global boards (organization=NULL, v3.17.216) are added for
    staff/superusers only.
    """
    orgs = get_user_organizations(request.user)
    user = request.user
    is_staff_like = user.is_superuser or getattr(user, 'is_staff', False)
    qs = Wallboard.objects.filter(
        Q(organization__in=orgs) | (Q(organization__isnull=True) if is_staff_like else Q(pk__in=[]))
    ).select_related('organization')
    return render(request, 'reports/wallboard_list.html', {
        'wallboards': qs.order_by('organization__name', 'order', 'name'),
        'can_create_global': is_staff_like,
    })


@login_required
@require_perm('reports_view_dashboards')
def wallboard_view(request, pk):
    """
    Render a single wallboard full-screen.

    The page meta-refreshes every `refresh_seconds` for whole-page updates.
    Per-widget refresh_seconds overrides aren't enforced server-side (one
    refresh applies to the whole rendered page); they're informational
    until the JS-side per-widget refresher ships in a future sub-phase.
    """
    from .widget_sources import get_widget_data, viewer_for

    board = get_object_or_404(Wallboard, pk=pk)
    if not _user_can_see_wallboards(request.user, board.organization):
        from django.http import Http404
        raise Http404('Wallboard not found')

    from .widget_sources import get_categories, default_category
    viewer = viewer_for(request.user, getattr(request, 'is_staff_user', False))
    rendered_widgets = []
    has_chart = False
    for w in board.widgets.order_by('order', 'created_at'):
        params = dict(w.query_params or {})
        cats = get_categories(w.data_source)
        active_cat = None
        if cats:
            active_cat = params.get('category') or default_category(w.data_source)
            params['category'] = active_cat
        data = get_widget_data(w.data_source, params, viewer)
        if w.widget_type in ('chart_line', 'chart_bar', 'chart_pie'):
            has_chart = True
        rendered_widgets.append({
            'widget': w,
            'data': data,
            'data_json': json.dumps(data, default=str),
            'categories': cats,
            'active_category': active_cat,
        })

    return render(request, 'reports/wallboard_view.html', {
        'wallboard': board,
        'rendered_widgets': rendered_widgets,
        'refresh_seconds': board.refresh_seconds,
        'has_chart': has_chart,
    })


@login_required
@require_perm('reports_view_dashboards')
def wallboard_rotate(request, pk):
    """
    NOC-TV mode: render the wallboard, but on the next page-refresh
    (after `rotate_seconds`) navigate to the NEXT wallboard in the org's
    rotation. Boards with rotate_seconds=0 are skipped from rotation.

    Implementation is a meta-refresh redirect chain — works on any TV
    browser, no JS or cookies required.
    """
    board = get_object_or_404(Wallboard, pk=pk)
    if not _user_can_see_wallboards(request.user, board.organization):
        from django.http import Http404
        raise Http404('Wallboard not found')

    # Compute the rotation target. If rotation isn't enabled on this
    # board, fall through and the page refreshes itself (no redirect).
    if board.rotate_seconds > 0:
        next_board = board.next_in_rotation()
        rotate_target_pk = next_board.pk
        rotate_seconds = board.rotate_seconds
    else:
        rotate_target_pk = None
        rotate_seconds = 0

    from .widget_sources import get_widget_data, viewer_for
    from .widget_sources import get_categories, default_category
    viewer = viewer_for(request.user, getattr(request, 'is_staff_user', False))
    rendered_widgets = []
    has_chart = False
    for w in board.widgets.order_by('order', 'created_at'):
        params = dict(w.query_params or {})
        cats = get_categories(w.data_source)
        active_cat = None
        if cats:
            active_cat = params.get('category') or default_category(w.data_source)
            params['category'] = active_cat
        data = get_widget_data(w.data_source, params, viewer)
        if w.widget_type in ('chart_line', 'chart_bar', 'chart_pie'):
            has_chart = True
        rendered_widgets.append({
            'widget': w,
            'data': data,
            'data_json': json.dumps(data, default=str),
            'categories': cats,
            'active_category': active_cat,
        })

    return render(request, 'reports/wallboard_view.html', {
        'wallboard': board,
        'rendered_widgets': rendered_widgets,
        'refresh_seconds': board.refresh_seconds,
        'rotate_target_pk': rotate_target_pk,
        'rotate_seconds': rotate_seconds,
        'has_chart': has_chart,
    })


@login_required
@require_perm('reports_manage_dashboards')
def wallboard_form(request, pk=None):
    """Create or edit a wallboard. Widget editing is admin-only via the
    Django admin for now; this form covers the wallboard fields only."""
    instance = None
    if pk is not None:
        instance = get_object_or_404(Wallboard, pk=pk)
        if not _user_can_see_wallboards(request.user, instance.organization):
            from django.http import Http404
            raise Http404('Wallboard not found')

    orgs = get_user_organizations(request.user)
    is_staff_like = request.user.is_superuser or getattr(request.user, 'is_staff', False)

    if request.method == 'POST':
        org_id = request.POST.get('organization')
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        try:
            refresh_seconds = max(0, int(request.POST.get('refresh_seconds') or 60))
            rotate_seconds = max(0, int(request.POST.get('rotate_seconds') or 0))
            order = max(0, int(request.POST.get('order') or 100))
        except ValueError:
            messages.error(request, 'Refresh / rotate / order must be integers.')
            return redirect(request.path)
        is_active = bool(request.POST.get('is_active'))

        if not name:
            messages.error(request, 'Name is required.')
            return redirect(request.path)

        if instance is None:
            # v3.17.216: org_id == "" or "global" + staff-like user → null org
            from core.models import Organization
            if (org_id in ('', 'global', None)) and is_staff_like:
                org = None
            else:
                try:
                    org = orgs.get(pk=org_id)
                except (Organization.DoesNotExist, ValueError, TypeError):
                    messages.error(request, 'Pick an organization you belong to.')
                    return redirect(request.path)
            instance = Wallboard.objects.create(
                organization=org, name=name, description=description,
                refresh_seconds=refresh_seconds, rotate_seconds=rotate_seconds,
                order=order, is_active=is_active,
                created_by=request.user,
            )
            # v3.17.220: optional starter-template populates initial widgets.
            template_key = (request.POST.get('template') or '').strip()
            if template_key:
                from .widget_sources import get_template
                tpl = get_template(template_key)
                if tpl and tpl['widgets']:
                    rank = 10
                    for w in tpl['widgets']:
                        WallboardWidget.objects.create(
                            wallboard=instance,
                            title=w['title'][:200],
                            widget_type=w['widget_type'],
                            data_source=w['data_source'],
                            order=rank,
                        )
                        rank += 10
            label = instance.name + (' (Global)' if org is None else '')
            messages.success(request, f'Wallboard "{label}" created.')
        else:
            instance.name = name
            instance.description = description
            instance.refresh_seconds = refresh_seconds
            instance.rotate_seconds = rotate_seconds
            instance.order = order
            instance.is_active = is_active
            instance.save()
            messages.success(request, f'Wallboard "{instance.name}" updated.')
        return redirect('reports:wallboard_list')

    from .widget_sources import (
        DATA_SOURCE_CHOICES, WALLBOARD_TEMPLATES,
    )
    return render(request, 'reports/wallboard_form.html', {
        'wallboard': instance,
        'organizations': orgs,
        'can_create_global': is_staff_like,
        'data_source_choices': DATA_SOURCE_CHOICES,
        'wallboard_templates': WALLBOARD_TEMPLATES,
    })


@login_required
@require_perm('reports_manage_dashboards')
@require_http_methods(['POST'])
def wallboard_widget_add(request, pk):
    """
    Add a widget to an existing wallboard.

    Widget type is derived from the data source's recommended type in
    `DATA_SOURCE_CHOICES` (v3.17.221) — the form no longer asks the
    user, since picking a metric source and a `table` widget_type
    produces a confusing "no rows" render. Source-implied type is
    always correct; manual override goes through Django admin.
    """
    from .widget_sources import REGISTRY, DATA_SOURCE_CHOICES
    board = get_object_or_404(Wallboard, pk=pk)
    if not _user_can_see_wallboards(request.user, board.organization):
        from django.http import Http404
        raise Http404('Wallboard not found')

    title = (request.POST.get('title') or '').strip()
    data_source = (request.POST.get('data_source') or '').strip()

    if not title or not data_source:
        messages.error(request, 'Title and data source are required.')
        return redirect('reports:wallboard_edit', pk=board.pk)
    if data_source not in REGISTRY:
        messages.error(request, f'Unknown data source "{data_source}".')
        return redirect('reports:wallboard_edit', pk=board.pk)

    widget_type = next(
        (t for k, _label, t in DATA_SOURCE_CHOICES if k == data_source),
        None,
    )
    valid_types = {t[0] for t in WallboardWidget.WIDGET_TYPES}
    if widget_type not in valid_types:
        messages.error(
            request,
            f'Data source "{data_source}" has no recommended widget type registered.',
        )
        return redirect('reports:wallboard_edit', pk=board.pk)

    last = board.widgets.order_by('-order').first()
    next_order = (last.order if last else 0) + 10
    WallboardWidget.objects.create(
        wallboard=board,
        title=title[:200],
        widget_type=widget_type,
        data_source=data_source,
        order=next_order,
    )
    messages.success(request, f'Added widget "{title}".')
    return redirect('reports:wallboard_edit', pk=board.pk)


@login_required
@require_perm('reports_manage_dashboards')
@require_http_methods(['POST'])
def wallboard_widget_delete(request, pk):
    """v3.17.220: remove a widget from its wallboard. Tenant-ACL'd."""
    widget = get_object_or_404(WallboardWidget.objects.select_related('wallboard'), pk=pk)
    board = widget.wallboard
    if not _user_can_see_wallboards(request.user, board.organization):
        from django.http import Http404
        raise Http404('Wallboard not found')
    title = widget.title
    widget.delete()
    messages.success(request, f'Removed widget "{title}".')
    return redirect('reports:wallboard_edit', pk=board.pk)


@login_required
@require_perm('reports_manage_dashboards')
def wallboard_widget_reorder(request, pk):
    """
    v3.17.215: persist a new widget order for a wallboard.

    Accepts POST with body `{"order": [<widget_pk>, <widget_pk>, ...]}`
    (JSON) or form-encoded `order=<pk>&order=<pk>&...`. Updates
    `WallboardWidget.order` to match the supplied sequence (10, 20, 30,
    … so manually-edited order values stay legible). Returns JSON
    `{ok: True, count: N}`.

    Tenant-scoped: cross-org wallboard pks 404. Rejects non-POST.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    board = get_object_or_404(Wallboard, pk=pk)
    if not _user_can_see_wallboards(request.user, board.organization):
        from django.http import Http404
        raise Http404('Wallboard not found')

    # Accept either JSON body or form-encoded list.
    ids = []
    ctype = (request.META.get('CONTENT_TYPE') or '').lower()
    if 'application/json' in ctype:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'invalid JSON'}, status=400)
        ids = payload.get('order') or []
    else:
        ids = request.POST.getlist('order')

    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': 'order must be a list of widget pks'}, status=400)

    valid_ids = set(board.widgets.values_list('pk', flat=True))
    if not set(ids).issubset(valid_ids):
        return JsonResponse(
            {'error': 'one or more widget pks do not belong to this wallboard'},
            status=400,
        )

    rank = 10
    for wid in ids:
        WallboardWidget.objects.filter(pk=wid, wallboard=board).update(order=rank)
        rank += 10
    return JsonResponse({'ok': True, 'count': len(ids)})


@login_required
@require_perm('reports_view_dashboards')
def wallboard_widget_data(request, pk):
    """
    v3.17.217: re-fetch one wallboard widget with a different category.

    Used by the per-widget category dropdown — JS posts the new category
    and we return JSON of the same shape as `widget_sources` produce.
    The wallboard template's renderer uses this to swap the tile
    contents in place (no full-page reload).

    Path: GET /reports/wallboards/widgets/<pk>/data/?category=<value>
    Tenant ACL'd via the parent wallboard.
    """
    from .widget_sources import (
        get_widget_data, get_categories, is_valid_category, default_category,
        viewer_for,
    )
    widget = get_object_or_404(WallboardWidget.objects.select_related('wallboard'), pk=pk)
    if not _user_can_see_wallboards(request.user, widget.wallboard.organization):
        from django.http import Http404
        raise Http404('Wallboard not found')

    params = dict(widget.query_params or {})
    cats = get_categories(widget.data_source)
    if cats:
        category = request.GET.get('category')
        if category and not is_valid_category(widget.data_source, category):
            return JsonResponse({'error': 'unknown category'}, status=400)
        params['category'] = category or default_category(widget.data_source)

    data = get_widget_data(
        widget.data_source, params,
        viewer_for(request.user, getattr(request, 'is_staff_user', False)),
    )
    return JsonResponse({
        'widget_type': widget.widget_type,
        'data': data,
    })


# ---------------------------------------------------------------------------
# Phase 36 v1 — Agreement Reconciliation (v3.17.225)
# ---------------------------------------------------------------------------

@login_required
def agreement_reconciliation(request):
    """
    List every active MSP contract with its included-vs-consumed hours
    and an over/under-served alert. Sourced entirely from data already
    in the system — `Contract.total_hours` (allowance), `hours_used_minutes`
    (consumption tracker incremented by `TicketTimeEntry.save()`), and
    `overage_rate` for the cost-of-overage estimate.

    URL: /reports/agreement-reconciliation/
    Tenant ACL: superuser / staff sees all; org members see only their
    org's contracts.
    Output: HTML table with `?format=csv` export.
    """
    from psa.models import Contract
    from decimal import Decimal as D

    qs = Contract.objects.filter(status='active').select_related(
        'client_org', 'organization',
    )
    if request.user.is_superuser or getattr(request, 'is_staff_user', False):
        pass  # see everything
    else:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                       .values_list('organization_id', flat=True))
        qs = qs.filter(client_org_id__in=ids)
    qs = qs.order_by('client_org__name', 'name')

    rows = []
    summary = {'under_served': 0, 'on_track': 0, 'over_served': 0, 'unlimited': 0}
    for c in qs:
        consumed_h = D(c.hours_used_minutes or 0) / D(60)
        allowance = D(c.total_hours or 0)
        if allowance <= 0:
            pct = None
            flag = 'unlimited'
        else:
            pct = round(float(consumed_h / allowance * 100), 1)
            if pct >= 110:
                flag = 'over_served'
            elif pct < 30:
                flag = 'under_served'
            else:
                flag = 'on_track'
        summary[flag] += 1

        overage_h = max(consumed_h - allowance, D(0)) if allowance > 0 else D(0)
        rate = c.overage_rate if c.overage_rate else c.hourly_rate
        overage_cost = overage_h * (rate or D(0))

        rows.append({
            'contract': c,
            'consumed_hours': float(consumed_h.quantize(D('0.01'))),
            'allowance_hours': float(allowance),
            'pct': pct,
            'flag': flag,
            'overage_hours': float(overage_h.quantize(D('0.01'))),
            'overage_cost': float(overage_cost.quantize(D('0.01'))),
        })

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv2
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = (
            'attachment; filename="agreement-reconciliation.csv"'
        )
        w = _csv2.writer(resp)
        w.writerow(['Client', 'Contract', 'Type', 'Period start', 'Period end',
                    'Allowance (h)', 'Consumed (h)', '% used', 'Status',
                    'Overage (h)', 'Overage cost'])
        for r in rows:
            c = r['contract']
            w.writerow([
                c.client_org.name, c.name, c.get_contract_type_display(),
                c.start_date.isoformat() if c.start_date else '',
                c.end_date.isoformat() if c.end_date else '',
                r['allowance_hours'], r['consumed_hours'],
                r['pct'] if r['pct'] is not None else '',
                r['flag'], r['overage_hours'], r['overage_cost'],
            ])
        return resp

    return render(request, 'reports/agreement_reconciliation.html', {
        'rows': rows,
        'summary': summary,
        'total_contracts': len(rows),
    })


# ---------------------------------------------------------------------------
# Phase 26 v1 (v3.17.246) — Saved Queries / Custom Report Writer
# ---------------------------------------------------------------------------

@login_required
def saved_query_list(request):
    """List the user's own saved queries + shared queries from their orgs."""
    from .models import SavedQuery
    from .saved_query import MODEL_CONFIG

    own = SavedQuery.objects.filter(owner=request.user)
    org_ids = []
    if hasattr(request.user, 'memberships'):
        org_ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
    shared = SavedQuery.objects.filter(
        is_shared=True, organization_id__in=org_ids,
    ).exclude(owner=request.user)
    return render(request, 'reports/saved_query_list.html', {
        'own_queries': own,
        'shared_queries': shared,
        'model_choices': [(k, v['label']) for k, v in MODEL_CONFIG.items()],
    })


@login_required
def saved_query_form(request, pk=None):
    """Create or edit a SavedQuery. Form posts back here on save."""
    import json as _json
    from .models import SavedQuery
    from .saved_query import MODEL_CONFIG, OPERATORS_BY_TYPE

    instance = None
    if pk is not None:
        instance = get_object_or_404(SavedQuery, pk=pk)
        if not instance.can_edit(request.user):
            messages.error(request, "You can't edit that saved query.")
            return redirect('reports:saved_query_list')

    org_ids = []
    if hasattr(request.user, 'memberships'):
        org_ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))

    if request.method == 'POST':
        target = request.POST.get('target_model') or ''
        if target not in MODEL_CONFIG:
            messages.error(request, 'Pick a valid target model.')
            return redirect(request.path)
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return redirect(request.path)
        # Filters arrive as parallel arrays from the dynamic form rows.
        fields = request.POST.getlist('filter_field')
        ops = request.POST.getlist('filter_op')
        values = request.POST.getlist('filter_value')
        allowed = MODEL_CONFIG[target]['filterable_fields']
        filters = []
        for f, o, v in zip(fields, ops, values):
            if not f or f not in allowed:
                continue
            if o not in OPERATORS_BY_TYPE.get(allowed[f], []):
                continue
            filters.append({'field': f, 'op': o, 'value': v})
        columns = request.POST.getlist('column')
        columns = [c for c in columns if c in MODEL_CONFIG[target]['columns']]
        sort_by = request.POST.get('sort_by') or ''
        is_shared = request.POST.get('is_shared') == 'on'

        org = None
        org_pk = request.POST.get('organization')
        if org_pk:
            try:
                from core.models import Organization
                org = Organization.objects.filter(pk=org_pk, id__in=org_ids).first()
            except Exception:
                org = None

        if instance is None:
            instance = SavedQuery.objects.create(
                owner=request.user, name=name, description=description,
                organization=org, target_model=target,
                filters=filters, columns=columns, sort_by=sort_by,
                is_shared=is_shared,
            )
            messages.success(request, f'Saved "{instance.name}".')
        else:
            instance.name = name
            instance.description = description
            instance.organization = org
            instance.target_model = target
            instance.filters = filters
            instance.columns = columns
            instance.sort_by = sort_by
            instance.is_shared = is_shared
            instance.save()
            messages.success(request, f'Updated "{instance.name}".')
        return redirect('reports:saved_query_run', pk=instance.pk)

    from core.models import Organization
    user_orgs = Organization.objects.filter(id__in=org_ids).order_by('name')
    return render(request, 'reports/saved_query_form.html', {
        'instance': instance,
        'model_config_json': _json.dumps({
            k: {
                'label': v['label'],
                'fields': [
                    {'name': fn, 'type': ft, 'ops': OPERATORS_BY_TYPE[ft]}
                    for fn, ft in v['filterable_fields'].items()
                ],
                'columns': v['columns'],
            }
            for k, v in MODEL_CONFIG.items()
        }),
        'user_orgs': user_orgs,
        'instance_filters_json': _json.dumps(instance.filters or [] if instance else []),
        'instance_columns_json': _json.dumps(instance.columns or [] if instance else []),
    })


@login_required
def saved_query_run(request, pk):
    """Execute a saved query and render the results (HTML / CSV)."""
    from .models import SavedQuery
    from .saved_query import execute, render_columns
    from django.utils import timezone as _tz
    sq = get_object_or_404(SavedQuery, pk=pk)
    if not sq.visible_to(request.user):
        from django.http import Http404
        raise Http404('Saved query not available')

    org = None
    if sq.organization_id:
        org = sq.organization
    model, qs = execute(sq, organization=org)
    if model is None:
        messages.error(request, 'Target model unavailable.')
        return redirect('reports:saved_query_list')

    columns = render_columns(sq)
    qs = qs[:1000]  # cap render set

    rows = []
    for obj in qs:
        row = []
        for col in columns:
            try:
                v = obj
                for part in col.split('__'):
                    if v is None:
                        break
                    v = getattr(v, part, None)
                row.append(v if v is not None else '')
            except Exception:
                row.append('')
        rows.append(row)

    sq.last_run_at = _tz.now()
    sq.last_run_count = len(rows)
    sq.save(update_fields=['last_run_at', 'last_run_count', 'updated_at'])

    fmt = (request.GET.get('format') or 'html').lower()
    if fmt == 'csv':
        import csv as _csv
        from django.http import HttpResponse
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = (
            f'attachment; filename="{sq.name[:40].replace(" ", "_")}.csv"'
        )
        w = _csv.writer(resp)
        w.writerow(columns)
        for r in rows:
            w.writerow([str(c) for c in r])
        return resp

    return render(request, 'reports/saved_query_run.html', {
        'sq': sq,
        'columns': columns,
        'rows': rows,
        'count': len(rows),
        'capped': len(rows) >= 1000,
        'can_edit': sq.can_edit(request.user),
    })


@login_required
@require_http_methods(['POST'])
def saved_query_delete(request, pk):
    from .models import SavedQuery
    sq = get_object_or_404(SavedQuery, pk=pk)
    if not sq.can_edit(request.user):
        messages.error(request, "You can't delete that saved query.")
        return redirect('reports:saved_query_list')
    name = sq.name
    sq.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('reports:saved_query_list')


@login_required
def agreement_reconciliation_detail(request, pk):
    """
    Phase 36 v3 (v3.17.248): drill-down view that classifies a contract's
    time entries as `covered` (fit within the allowance) vs `overage`
    (past the allowance), in chronological order. Surfaces who logged
    the overage minutes so account managers know which tech to talk to.

    URL: /reports/agreement-reconciliation/<contract_pk>/
    Tenant ACL: same as the list view — staff sees all, members see
    only their org's contracts.
    """
    from psa.models import Contract, TicketTimeEntry
    from decimal import Decimal as D

    qs = Contract.objects.select_related('client_org', 'organization')
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(client_org_id__in=ids)
    contract = get_object_or_404(qs, pk=pk)

    allowance_min = int(D(contract.total_hours or 0) * 60)
    entries = (TicketTimeEntry.objects
               .filter(ticket__organization=contract.client_org,
                       duration_minutes__gt=0,
                       ended_at__isnull=False)
               .select_related('ticket', 'user').order_by('started_at'))

    rows = []
    cumulative = 0
    covered_total = 0
    overage_total = 0
    overage_by_user = {}
    for e in entries:
        dur = int(e.duration_minutes or 0)
        if not dur:
            continue
        prev_cum = cumulative
        cumulative += dur
        if allowance_min <= 0:
            covered = dur
            overage = 0
            classification = 'unlimited'
        elif cumulative <= allowance_min:
            covered = dur
            overage = 0
            classification = 'covered'
        elif prev_cum >= allowance_min:
            covered = 0
            overage = dur
            classification = 'overage'
        else:
            covered = max(allowance_min - prev_cum, 0)
            overage = dur - covered
            classification = 'split'
        covered_total += covered
        overage_total += overage
        if overage:
            uname = (e.user.username if e.user_id else 'unknown')
            overage_by_user[uname] = overage_by_user.get(uname, 0) + overage
        rows.append({
            'entry': e,
            'cumulative_minutes': cumulative,
            'covered_minutes': covered,
            'overage_minutes': overage,
            'classification': classification,
        })

    rate = contract.overage_rate if contract.overage_rate else contract.hourly_rate
    overage_cost = float(D(overage_total) / D(60) * (rate or D(0)))

    # Limit render to most-recent 500 rows on the page; full series is
    # available via CSV.
    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = (
            f'attachment; filename="agreement-detail-{contract.pk}.csv"'
        )
        w = _csv.writer(resp)
        w.writerow(['Started', 'User', 'Ticket', 'Notes', 'Duration (min)',
                    'Cumulative (min)', 'Covered', 'Overage', 'Classification'])
        for r in rows:
            e = r['entry']
            w.writerow([
                e.started_at.isoformat(),
                e.user.username if e.user_id else '',
                e.ticket.ticket_number if e.ticket_id else '',
                (e.notes or '')[:200],
                e.duration_minutes,
                r['cumulative_minutes'],
                r['covered_minutes'],
                r['overage_minutes'],
                r['classification'],
            ])
        return resp

    return render(request, 'reports/agreement_reconciliation_detail.html', {
        'contract': contract,
        'rows': rows[-500:] if len(rows) > 500 else rows,
        'truncated': len(rows) > 500,
        'covered_total': covered_total,
        'overage_total': overage_total,
        'allowance_minutes': allowance_min,
        'cumulative_minutes': cumulative,
        'overage_cost': overage_cost,
        'overage_by_user': sorted(
            overage_by_user.items(), key=lambda x: -x[1],
        ),
    })


@login_required
def accounting_reconciliation(request):
    """
    Phase 27 v1 (v3.17.255) — accounting reconciliation report.

    Three sections:
      1. **Outstanding pushed invoices** — invoices that have been
         pushed to QBO/Xero (`pushed_to_accounting_at` is set) but
         aren't fully paid here. Useful for "did the customer pay over
         there but our copy still says unpaid?"
      2. **Push errors** — invoices where `last_push_error` is set;
         the integration couldn't write the row to the accounting
         system. These need manual intervention.
      3. **Duplicate external IDs** — multiple Invoice rows pointing at
         the same `accounting_external_id`. Catches double-pushes.

    Tenant ACL: superuser/staff sees all; org members see only their
    org's invoices.
    """
    from psa.models import Invoice
    from django.db.models import Count, F, Q

    qs = Invoice.objects.select_related('client_org', 'organization')
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(client_org_id__in=ids)

    pushed_unpaid = qs.filter(
        pushed_to_accounting_at__isnull=False,
    ).filter(
        ~Q(status='paid') & ~Q(status='void') & Q(amount_paid__lt=F('total')),
    ).order_by('-invoice_date')

    push_errors = qs.exclude(last_push_error='').order_by('-updated_at')

    # Group by external_id to find duplicates. Empty IDs are excluded
    # (an invoice with no external_id is not a duplicate of another no-id one).
    dup_ids = (
        qs.exclude(accounting_external_id='')
          .values('accounting_provider', 'accounting_external_id')
          .annotate(n=Count('id'))
          .filter(n__gt=1)
    )
    duplicate_groups = []
    for g in dup_ids:
        members = list(qs.filter(
            accounting_provider=g['accounting_provider'],
            accounting_external_id=g['accounting_external_id'],
        ).order_by('-invoice_date'))
        duplicate_groups.append({
            'provider': g['accounting_provider'],
            'external_id': g['accounting_external_id'],
            'invoices': members,
            'count': g['n'],
        })

    # Phase 27 v4 (v3.17.267): tax discrepancies — pushed invoices where
    # provider_tax_amount differs from local tax_amount by > 0.01.
    from decimal import Decimal as _D
    tax_discrepancies = []
    for inv in qs.filter(
        pushed_to_accounting_at__isnull=False,
        provider_tax_amount__isnull=False,
    ).order_by('-invoice_date')[:500]:
        local = _D(str(inv.tax_amount or 0))
        provider = _D(str(inv.provider_tax_amount or 0))
        delta = provider - local
        if abs(delta) > _D('0.01'):
            tax_discrepancies.append({
                'invoice': inv,
                'local': local,
                'provider': provider,
                'delta': delta,
            })

    summary = {
        'outstanding_count': pushed_unpaid.count(),
        'outstanding_balance': sum(
            float(inv.total) - float(inv.amount_paid) for inv in pushed_unpaid
        ),
        'error_count': push_errors.count(),
        'duplicate_groups': len(duplicate_groups),
        'tax_mismatch_count': len(tax_discrepancies),
    }

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = (
            'attachment; filename="accounting-reconciliation.csv"'
        )
        w = _csv.writer(resp)
        w.writerow(['Section', 'Invoice', 'Client', 'Status', 'Total',
                    'Paid', 'Balance', 'External ID', 'Provider', 'Error'])
        for inv in pushed_unpaid:
            w.writerow([
                'outstanding', inv.invoice_number, inv.client_org.name,
                inv.status, str(inv.total), str(inv.amount_paid),
                str(float(inv.total) - float(inv.amount_paid)),
                inv.accounting_external_id, inv.accounting_provider, '',
            ])
        for inv in push_errors:
            w.writerow([
                'push_error', inv.invoice_number, inv.client_org.name,
                inv.status, str(inv.total), str(inv.amount_paid),
                str(float(inv.total) - float(inv.amount_paid)),
                inv.accounting_external_id, inv.accounting_provider,
                (inv.last_push_error or '')[:200],
            ])
        for g in duplicate_groups:
            for inv in g['invoices']:
                w.writerow([
                    'duplicate', inv.invoice_number, inv.client_org.name,
                    inv.status, str(inv.total), str(inv.amount_paid),
                    '', g['external_id'], g['provider'], '',
                ])
        for d in tax_discrepancies:
            inv = d['invoice']
            w.writerow([
                'tax_mismatch', inv.invoice_number, inv.client_org.name,
                inv.status, str(inv.total), str(inv.amount_paid),
                f'local={d["local"]} provider={d["provider"]} delta={d["delta"]}',
                inv.accounting_external_id, inv.accounting_provider, '',
            ])
        return resp

    return render(request, 'reports/accounting_reconciliation.html', {
        'pushed_unpaid': pushed_unpaid[:200],
        'push_errors': push_errors[:200],
        'duplicate_groups': duplicate_groups,
        'tax_discrepancies': tax_discrepancies[:200],
        'summary': summary,
    })


@login_required
def ar_aging_report(request):
    """
    Phase 27 v5 (v3.17.269): AR aging tied to QBO. Buckets pushed-but-
    unpaid invoices into 0-30 / 31-60 / 61-90 / 90+ day age groups by
    client. Difference vs the existing `accounting_reconciliation`
    report: this view is per-client + bucketed for collections work,
    not invoice-by-invoice for diagnostics.

    Tenant ACL: superuser/staff sees all; org members see only their
    org's invoices.
    """
    from psa.models import Invoice
    from datetime import date as _date
    from decimal import Decimal as _D
    from collections import defaultdict
    from django.db.models import F, Q

    qs = (Invoice.objects.select_related('client_org', 'organization')
          .filter(pushed_to_accounting_at__isnull=False)
          .filter(~Q(status='paid') & ~Q(status='void')
                  & Q(amount_paid__lt=F('total'))))

    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(client_org_id__in=ids)

    today = _date.today()
    # client_pk → {bucket -> total, total: total, oldest_days: int, name: str}
    by_client = defaultdict(lambda: {
        'name': '', 'b_0_30': _D('0'), 'b_31_60': _D('0'),
        'b_61_90': _D('0'), 'b_90_plus': _D('0'),
        'total_balance': _D('0'), 'oldest_days': 0,
        'invoice_count': 0, 'provider': '',
    })

    for inv in qs.values('client_org_id', 'client_org__name',
                          'invoice_date', 'due_date',
                          'total', 'amount_paid', 'accounting_provider'):
        balance = (_D(str(inv['total'] or 0)) - _D(str(inv['amount_paid'] or 0)))
        if balance <= 0:
            continue
        # Age from due_date when set, else invoice_date.
        ref = inv['due_date'] or inv['invoice_date']
        days = (today - ref).days
        bucket = 'b_0_30'
        if days > 90:
            bucket = 'b_90_plus'
        elif days > 60:
            bucket = 'b_61_90'
        elif days > 30:
            bucket = 'b_31_60'
        b = by_client[inv['client_org_id']]
        b['name'] = inv['client_org__name']
        b[bucket] += balance
        b['total_balance'] += balance
        b['invoice_count'] += 1
        b['oldest_days'] = max(b['oldest_days'], days)
        if not b['provider'] and inv['accounting_provider']:
            b['provider'] = inv['accounting_provider']

    rows = []
    for client_id, b in by_client.items():
        rows.append({'client_id': client_id, **b})
    rows.sort(key=lambda r: -r['total_balance'])

    totals = {
        'b_0_30': sum(r['b_0_30'] for r in rows),
        'b_31_60': sum(r['b_31_60'] for r in rows),
        'b_61_90': sum(r['b_61_90'] for r in rows),
        'b_90_plus': sum(r['b_90_plus'] for r in rows),
        'total_balance': sum(r['total_balance'] for r in rows),
        'invoice_count': sum(r['invoice_count'] for r in rows),
        'client_count': len(rows),
    }

    fmt = (request.GET.get('format') or '').lower()
    if fmt == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="ar-aging.csv"'
        w = _csv.writer(resp)
        w.writerow(['Client', 'Provider', 'Invoices', '0-30', '31-60',
                    '61-90', '90+', 'Total', 'Oldest days'])
        for r in rows:
            w.writerow([r['name'], r['provider'], r['invoice_count'],
                        r['b_0_30'], r['b_31_60'], r['b_61_90'],
                        r['b_90_plus'], r['total_balance'], r['oldest_days']])
        w.writerow(['TOTAL', '', totals['invoice_count'],
                    totals['b_0_30'], totals['b_31_60'],
                    totals['b_61_90'], totals['b_90_plus'],
                    totals['total_balance'], ''])
        return resp
    if fmt == 'pdf':
        # v3.17.326 — Phase 19 v8 PDF export.
        from .pdf_export import render_pdf
        kpis = [
            {'label': 'CLIENTS', 'value': str(totals['client_count'])},
            {'label': 'INVOICES', 'value': str(totals['invoice_count'])},
            {'label': 'TOTAL OUTSTANDING', 'value': f"${float(totals['total_balance']):,.2f}"},
            {'label': '90+ DAYS', 'value': f"${float(totals['b_90_plus']):,.2f}"},
        ]
        body_rows = [[r['name'], r['provider'], str(r['invoice_count']),
                      f"${float(r['b_0_30']):,.2f}",
                      f"${float(r['b_31_60']):,.2f}",
                      f"${float(r['b_61_90']):,.2f}",
                      f"${float(r['b_90_plus']):,.2f}",
                      f"${float(r['total_balance']):,.2f}",
                      str(r['oldest_days'])]
                     for r in rows]
        body_rows.append(['TOTAL', '', str(totals['invoice_count']),
                          f"${float(totals['b_0_30']):,.2f}",
                          f"${float(totals['b_31_60']):,.2f}",
                          f"${float(totals['b_61_90']):,.2f}",
                          f"${float(totals['b_90_plus']):,.2f}",
                          f"${float(totals['total_balance']):,.2f}", ''])
        tables = [{'heading': 'AR aging by client',
                   'header_row': ['Client', 'Provider', 'Inv',
                                  '0-30', '31-60', '61-90', '90+',
                                  'Total', 'Oldest d'],
                   'body_rows': body_rows,
                   'align_right_cols': [2, 3, 4, 5, 6, 7, 8]}]
        return render_pdf(
            title='Accounts Receivable Aging',
            subtitle='Pushed-but-unpaid invoices, bucketed by age from due date.',
            kpis=kpis, tables=tables,
            filename='ar-aging.pdf')

    return render(request, 'reports/ar_aging.html', {
        'rows': rows,
        'totals': totals,
    })


@login_required
def bank_reconciliation_report(request):
    """
    Phase 27 v9 (v3.17.281): bank deposit reconciliation. Groups
    Payment rows by `bank_deposit_batch` so a buyer can confirm each
    batch against the bank statement and stamp `bank_reconciled_at`.

    Tenant ACL: superuser/staff sees all; org members see only their
    org's payments.
    """
    from psa.models import Payment
    from collections import defaultdict
    from decimal import Decimal as _D

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    qs = (Payment.objects.select_related('invoice', 'invoice__client_org',
                                          'invoice__organization')
          .order_by('-paid_on'))
    if not is_staff:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(invoice__client_org_id__in=ids)

    # Three buckets:
    #   1. Untagged payments — need a batch assigned
    #   2. Tagged but unreconciled — batches awaiting confirmation
    #   3. Reconciled — read-only history (latest 50 batches)
    untagged = list(qs.filter(bank_deposit_batch=''))

    # Group tagged-but-unreconciled by batch
    tagged_unrec = defaultdict(lambda: {
        'batch': '', 'count': 0, 'total': _D('0'),
        'oldest': None, 'newest': None, 'payments': [],
    })
    for p in qs.exclude(bank_deposit_batch='').filter(bank_reconciled_at__isnull=True):
        b = tagged_unrec[p.bank_deposit_batch]
        b['batch'] = p.bank_deposit_batch
        b['count'] += 1
        b['total'] += _D(str(p.amount or 0))
        if b['oldest'] is None or p.paid_on < b['oldest']:
            b['oldest'] = p.paid_on
        if b['newest'] is None or p.paid_on > b['newest']:
            b['newest'] = p.paid_on
        b['payments'].append(p)
    unrec_groups = list(tagged_unrec.values())
    unrec_groups.sort(key=lambda g: -g['total'])

    # Group reconciled by batch (truncated history)
    reconciled = defaultdict(lambda: {
        'batch': '', 'count': 0, 'total': _D('0'),
        'reconciled_at': None,
    })
    for p in qs.exclude(bank_deposit_batch='').filter(bank_reconciled_at__isnull=False):
        b = reconciled[p.bank_deposit_batch]
        b['batch'] = p.bank_deposit_batch
        b['count'] += 1
        b['total'] += _D(str(p.amount or 0))
        if b['reconciled_at'] is None or p.bank_reconciled_at > b['reconciled_at']:
            b['reconciled_at'] = p.bank_reconciled_at
    rec_groups = list(reconciled.values())
    rec_groups.sort(key=lambda g: -(g['reconciled_at'].timestamp()
                                     if g['reconciled_at'] else 0))

    return render(request, 'reports/bank_reconciliation.html', {
        'untagged': untagged[:200],
        'unrec_groups': unrec_groups,
        'rec_groups': rec_groups[:50],
        'totals': {
            'untagged_count': len(untagged),
            'unrec_batch_count': len(unrec_groups),
            'unrec_total': sum(g['total'] for g in unrec_groups),
            'rec_batch_count': len(rec_groups),
        },
    })


@login_required
def bank_reconciliation_mark(request):
    """Phase 27 v9 (v3.17.281): bulk-mark a deposit batch reconciled
    (or reopen it). POST `batch=NAME` + `action=reconcile|reopen`."""
    from psa.models import Payment
    from django.utils import timezone as _tz
    from django.contrib import messages as _msgs

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Bank reconciliation is staff-only')
    if request.method != 'POST':
        return redirect('reports:bank_reconciliation_report')

    batch = (request.POST.get('batch') or '').strip()
    action = (request.POST.get('action') or '').strip()
    if not batch or action not in ('reconcile', 'reopen'):
        _msgs.error(request, 'Pick a batch + action (reconcile / reopen).')
        return redirect('reports:bank_reconciliation_report')

    qs = Payment.objects.filter(bank_deposit_batch=batch)
    if action == 'reconcile':
        n = qs.update(bank_reconciled_at=_tz.now())
        _msgs.success(request, f'Reconciled {n} payment(s) in batch "{batch}".')
    else:
        n = qs.update(bank_reconciled_at=None)
        _msgs.success(request, f'Reopened {n} payment(s) in batch "{batch}".')
    return redirect('reports:bank_reconciliation_report')


@login_required
def multi_location_report(request):
    """
    Phase 18 v8/v9/v10 (v3.17.283): multi-location operational report.
    Three sections:
      1. **By region** — top-level orgs grouped by `normalized_region`.
      2. **Per-parent rollup** — for each parent org with children,
         aggregate ticket counts, invoice balances, and asset counts
         across the parent + every descendant.
      3. **Shared services mapping** — assets flagged
         `is_shared_with_descendants=True` and the descendant orgs
         that see them via inheritance.

    Tenant ACL: superuser/staff sees all; org members see their org's
    parent tree (using `for_organization` semantics).
    """
    from core.models import Organization
    from psa.models import Ticket, Invoice
    from assets.models import Asset
    from collections import defaultdict
    from decimal import Decimal as _D
    from django.db.models import Count, Q, F, Sum

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))

    # Visible org universe
    if is_staff:
        org_qs = Organization.objects.filter(is_active=True)
    else:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        # Include parents and descendants
        from core.utils import descendant_org_ids, ancestor_org_ids
        full_ids = set(ids)
        for oid in ids:
            try:
                o = Organization.objects.get(pk=oid)
            except Organization.DoesNotExist:
                continue
            full_ids.update(descendant_org_ids(o))
            full_ids.update(ancestor_org_ids(o))
        org_qs = Organization.objects.filter(pk__in=full_ids, is_active=True)

    # Section 1: by region (only for orgs that ARE top-level OR that
    # have a region tag — a child site can override its parent's region)
    by_region = defaultdict(list)
    for org in org_qs.order_by('name'):
        key = org.normalized_region or '(unassigned)'
        by_region[key].append(org)
    region_rows = sorted(by_region.items(), key=lambda kv: kv[0])

    # Section 2: per-parent rollup. Find every org with at least one child
    parents = (org_qs.filter(children__isnull=False).distinct()
               .order_by('name'))
    parent_rows = []
    for p in parents:
        from core.utils import descendant_org_ids
        tree_ids = descendant_org_ids(p)
        tickets_open = Ticket.objects.filter(
            organization_id__in=tree_ids,
        ).filter(~Q(status__is_terminal=True)).count()
        inv_balance = (Invoice.objects.filter(
            client_org_id__in=tree_ids,
        ).exclude(status='void').aggregate(
            balance=Sum(F('total') - F('amount_paid')),
        )['balance'] or _D('0'))
        asset_count = Asset.objects.filter(organization_id__in=tree_ids).count()
        parent_rows.append({
            'parent': p,
            'tree_size': len(tree_ids),
            'tickets_open': tickets_open,
            'invoice_balance': inv_balance,
            'asset_count': asset_count,
        })
    parent_rows.sort(key=lambda r: -r['tree_size'])

    # Section 3: shared services mapping
    shared_assets = (Asset.objects.filter(
        is_shared_with_descendants=True,
        organization__in=org_qs,
    ).select_related('organization').order_by('organization__name', 'name'))
    shared_rows = []
    for a in shared_assets:
        from core.utils import descendant_org_ids
        descendants = list(Organization.objects.filter(
            pk__in=descendant_org_ids(a.organization)
        ).exclude(pk=a.organization_id).order_by('name'))
        shared_rows.append({
            'asset': a,
            'owner_org': a.organization,
            'visible_to': descendants,
        })

    return render(request, 'reports/multi_location.html', {
        'region_rows': region_rows,
        'parent_rows': parent_rows,
        'shared_rows': shared_rows,
        'totals': {
            'org_count': org_qs.count(),
            'region_count': len([k for k in by_region if k != '(unassigned)']),
            'parent_count': len(parent_rows),
            'shared_asset_count': len(shared_rows),
        },
    })


@login_required
def billing_reconciliation_report(request):
    """
    Phase 15 v6 (v3.17.295): per-client invoiced-vs-paid summary for a
    window. Helps catch "we billed them $30k but only collected $22k"
    drift before it grows.

    Tenant ACL: superuser/staff sees all; org members see their own
    client_org's invoices.
    """
    from psa.models import Invoice
    from datetime import date, timedelta
    from decimal import Decimal as _D
    from collections import defaultdict

    try:
        days = max(7, int(request.GET.get('days') or 90))
    except (TypeError, ValueError):
        days = 90
    cutoff = date.today() - timedelta(days=days)

    qs = (Invoice.objects.select_related('client_org')
          .filter(invoice_date__gte=cutoff)
          .exclude(status='void'))

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(client_org_id__in=ids)

    # Per-client roll-up
    rows_by_client = defaultdict(lambda: {
        'name': '', 'invoiced': _D('0'), 'paid': _D('0'),
        'outstanding': _D('0'), 'invoice_count': 0,
    })
    for inv in qs.values('client_org_id', 'client_org__name',
                          'total', 'amount_paid'):
        b = rows_by_client[inv['client_org_id']]
        b['name'] = inv['client_org__name']
        total = _D(str(inv['total'] or 0))
        paid = _D(str(inv['amount_paid'] or 0))
        b['invoiced'] += total
        b['paid'] += paid
        b['outstanding'] += (total - paid)
        b['invoice_count'] += 1

    rows = []
    for client_id, b in rows_by_client.items():
        rows.append({
            'client_id': client_id,
            'collection_pct': (
                round(float(b['paid'] / b['invoiced'] * 100), 1)
                if b['invoiced'] > 0 else 0
            ),
            **b,
        })
    rows.sort(key=lambda r: -r['outstanding'])

    totals = {
        'invoiced': sum(r['invoiced'] for r in rows),
        'paid': sum(r['paid'] for r in rows),
        'outstanding': sum(r['outstanding'] for r in rows),
        'client_count': len(rows),
    }
    totals['collection_pct'] = (
        round(float(totals['paid'] / totals['invoiced'] * 100), 1)
        if totals['invoiced'] > 0 else 0
    )

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="billing-reconciliation.csv"'
        w = _csv.writer(resp)
        w.writerow(['Client', 'Invoices', 'Invoiced', 'Paid', 'Outstanding',
                    'Collection %'])
        for r in rows:
            w.writerow([r['name'], r['invoice_count'],
                        r['invoiced'], r['paid'], r['outstanding'],
                        r['collection_pct']])
        w.writerow(['TOTAL', '',
                    totals['invoiced'], totals['paid'],
                    totals['outstanding'], totals['collection_pct']])
        return resp

    return render(request, 'reports/billing_reconciliation.html', {
        'rows': rows,
        'totals': totals,
        'days': days,
    })


@login_required
def mrr_forecast_report(request):
    """
    Phase 15 v9 (v3.17.295): monthly recurring revenue forecast.
    Reads active contracts with billing_frequency != none, normalizes
    each to a monthly equivalent, and projects the next 12 months.

    Tenant ACL: staff/superuser only — MRR is an MSP-internal metric.
    """
    from psa.models import Contract
    from datetime import date
    from decimal import Decimal as _D
    from collections import defaultdict
    from dateutil.relativedelta import relativedelta as _rd

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('MRR forecast is staff-only')

    # Normalize each contract's recurring revenue to monthly $$.
    contracts = (Contract.objects
                 .filter(status='active')
                 .exclude(billing_frequency='none')
                 .select_related('client_org'))

    monthly_by_contract = []
    for c in contracts:
        amount = c.effective_recurring_amount
        if amount <= 0:
            continue
        if c.billing_frequency == 'monthly':
            mrr = amount
        elif c.billing_frequency == 'quarterly':
            mrr = (amount / _D('3')).quantize(_D('0.01'))
        elif c.billing_frequency == 'yearly':
            mrr = (amount / _D('12')).quantize(_D('0.01'))
        else:
            continue
        monthly_by_contract.append({
            'contract': c,
            'client': c.client_org.name,
            'mrr': mrr,
            'frequency': c.billing_frequency,
            'next_billing_date': c.next_billing_date,
        })
    monthly_by_contract.sort(key=lambda r: -r['mrr'])

    total_mrr = sum(r['mrr'] for r in monthly_by_contract)
    arr = (total_mrr * _D('12')).quantize(_D('0.01'))

    # Forecast next 12 months — assume contracts with end_date past the
    # forecast month drop out.
    today = date.today().replace(day=1)
    forecast = []
    for i in range(12):
        target = today + _rd(months=i)
        active_total = _D('0')
        for r in monthly_by_contract:
            c = r['contract']
            if c.end_date and c.end_date < target:
                continue
            if c.start_date and c.start_date > (target + _rd(months=1)):
                continue
            active_total += r['mrr']
        forecast.append({'month': target.strftime('%Y-%m'),
                          'projected_mrr': active_total})

    fmt = (request.GET.get('format') or '').lower()
    if fmt == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="mrr-forecast.csv"'
        w = _csv.writer(resp)
        w.writerow(['Month', 'Projected MRR'])
        for f in forecast:
            w.writerow([f['month'], f['projected_mrr']])
        return resp
    if fmt == 'pdf':
        # v3.17.326 — Phase 19 v8 PDF export.
        from .pdf_export import render_pdf
        kpis = [
            {'label': 'CURRENT MRR', 'value': f"${float(total_mrr):,.0f}"},
            {'label': 'CURRENT ARR', 'value': f"${float(arr):,.0f}"},
            {'label': 'CONTRACTS', 'value': str(len(monthly_by_contract))},
        ]
        contract_rows = [[r['client'], r['frequency'],
                           f"${float(r['mrr']):,.2f}",
                           r['next_billing_date'].isoformat()
                           if r['next_billing_date'] else '—']
                          for r in monthly_by_contract]
        forecast_rows = [[f['month'], f"${float(f['projected_mrr']):,.2f}"]
                          for f in forecast]
        tables = [
            {'heading': 'Active recurring contracts',
             'header_row': ['Client', 'Frequency', 'MRR equiv', 'Next billing'],
             'body_rows': contract_rows,
             'align_right_cols': [2]},
            {'heading': '12-month MRR projection',
             'header_row': ['Month', 'Projected MRR'],
             'body_rows': forecast_rows,
             'align_right_cols': [1]},
        ]
        return render_pdf(
            title='MRR Forecast',
            subtitle='Active contracts normalized to monthly recurring revenue.',
            kpis=kpis, tables=tables,
            filename='mrr-forecast.pdf')

    return render(request, 'reports/mrr_forecast.html', {
        'rows': monthly_by_contract,
        'forecast': forecast,
        'totals': {
            'mrr': total_mrr,
            'arr': arr,
            'contract_count': len(monthly_by_contract),
        },
    })


@login_required
def software_compliance_report(request):
    """
    Phase 17 v3 (v3.17.305): software compliance audit. Joins
    `assets.SoftwarePolicy` rows against `integrations.RMMSoftware`
    inventory to surface:
      - **Deny violations**: software that matches a `deny` policy.
      - **Require gaps**: devices missing software required by a
        `require` policy.

    Tenant-scoped — staff sees all; org members see only their tree.
    """
    from assets.models import SoftwarePolicy
    from integrations.models import RMMSoftware, RMMDevice
    from django.db.models import Q
    from collections import defaultdict

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    org_qs_filter = Q()
    if not is_staff:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        org_qs_filter = Q(organization_id__in=ids)

    # MSP-wide (org=None) policies + org-scoped ones
    policies = list(SoftwarePolicy.objects.filter(is_active=True))
    deny = [p for p in policies if p.action == 'deny']
    require = [p for p in policies if p.action == 'require']

    deny_violations = []
    if deny:
        sw_qs = RMMSoftware.objects.filter(org_qs_filter).select_related(
            'organization', 'device')[:5000]
        for sw in sw_qs:
            for p in deny:
                if p.organization_id and p.organization_id != sw.organization_id:
                    continue
                if p.matches(sw.name):
                    deny_violations.append({
                        'software': sw.name,
                        'version': sw.version,
                        'device': sw.device.name if sw.device else '',
                        'org': sw.organization.name,
                        'policy': p.name,
                        'severity': p.severity,
                    })

    require_gaps = []
    if require:
        # For each device, see which require-policies have no matching software
        devices = RMMDevice.objects.filter(org_qs_filter).select_related(
            'organization')[:2000]
        for d in devices:
            installed = list(RMMSoftware.objects.filter(
                device=d).values_list('name', flat=True))
            for p in require:
                if p.organization_id and p.organization_id != d.organization_id:
                    continue
                if not any(p.matches(name) for name in installed):
                    require_gaps.append({
                        'device': d.name,
                        'org': d.organization.name,
                        'policy': p.name,
                        'severity': p.severity,
                        'missing': p.pattern,
                    })

    # Summary by severity
    by_sev = defaultdict(int)
    for r in deny_violations + require_gaps:
        by_sev[r['severity']] += 1

    return render(request, 'reports/software_compliance.html', {
        'deny_violations': deny_violations[:500],
        'require_gaps': require_gaps[:500],
        'totals': {
            'deny_count': len(deny_violations),
            'require_count': len(require_gaps),
            'policy_count': len(policies),
            'by_severity': dict(by_sev),
        },
    })


@login_required
def ticket_aging_report(request):
    """
    Phase 19 v1 (v3.17.257): ticket aging analytics. Bucket open
    tickets by age (created_at) into 5 standard ranges, surface a
    per-priority breakdown so dispatchers see where the queue is
    aging out.

    Buckets: 0-24h / 24-72h / 3-7d / 7-30d / 30+d.
    Tenant ACL: superuser/staff sees all; org members see their orgs.
    """
    from psa.models import Ticket
    from datetime import timedelta as _td
    from django.utils import timezone as _tz

    qs = Ticket.objects.filter(status__is_terminal=False).select_related(
        'organization', 'priority', 'status', 'queue', 'assigned_to',
    )
    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(organization_id__in=ids)

    now = _tz.now()
    buckets = [
        ('0-24h', now - _td(hours=24), now),
        ('24-72h', now - _td(hours=72), now - _td(hours=24)),
        ('3-7d', now - _td(days=7), now - _td(hours=72)),
        ('7-30d', now - _td(days=30), now - _td(days=7)),
        ('30+d', None, now - _td(days=30)),
    ]

    rows = []
    by_priority = {}  # priority code -> bucket -> count
    bucket_totals = {b[0]: 0 for b in buckets}
    total_open = 0
    for label, ge, lt in buckets:
        bucket_qs = qs.filter(created_at__lt=lt)
        if ge is not None:
            bucket_qs = bucket_qs.filter(created_at__gte=ge)
        bucket_count = bucket_qs.count()
        bucket_totals[label] = bucket_count
        total_open += bucket_count

        # Per-priority within this bucket. values_list avoids loading
        # the full Ticket row + the select_related FK clash with .only().
        for code in bucket_qs.values_list('priority__code', flat=True):
            key = code or '—'
            by_priority.setdefault(key, {b[0]: 0 for b in buckets})
            by_priority[key][label] += 1

        rows.append({
            'bucket': label,
            'count': bucket_count,
            'pct': round(100 * bucket_count / max(qs.count(), 1), 1),
        })

    aged_tickets = qs.filter(created_at__lt=now - _td(days=7)).order_by('created_at')[:200]

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="ticket-aging.csv"'
        w = _csv.writer(resp)
        w.writerow(['Bucket'] + [b[0] for b in buckets])
        for code in sorted(by_priority):
            w.writerow([code] + [by_priority[code][b[0]] for b in buckets])
        w.writerow(['TOTAL'] + [bucket_totals[b[0]] for b in buckets])
        return resp

    return render(request, 'reports/ticket_aging.html', {
        'rows': rows,
        'by_priority': sorted(by_priority.items()),
        'bucket_labels': [b[0] for b in buckets],
        'bucket_totals': bucket_totals,
        'total_open': total_open,
        'aged_tickets': aged_tickets,
        'aged_count': aged_tickets.count() if hasattr(aged_tickets, 'count') else len(aged_tickets),
    })


@login_required
def procurement_summary(request):
    """
    Phase 13 v3 (v3.17.258): procurement summary report. Aggregates
    PurchaseOrder data already in the system into per-vendor totals
    + a 12-month spend trend chart.

    Tenant ACL: superuser/staff sees all; org members are excluded
    (procurement is an MSP-internal ops view, not a client report).
    """
    from psa.models import PurchaseOrder
    from datetime import date as _date, timedelta as _td
    from django.db.models import Count, Sum
    from collections import defaultdict

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Procurement reports are staff-only')

    # Last 12 months of PO data, status not draft/cancelled (so totals
    # reflect committed spend, not work-in-progress).
    cutoff = _date.today() - _td(days=365)
    qs = (PurchaseOrder.objects
          .filter(created_at__date__gte=cutoff)
          .exclude(status__in=['draft', 'cancelled', 'void'])
          .select_related('vendor'))

    # Per-vendor aggregates
    by_vendor = (qs.values('vendor_name')
                   .annotate(
                       po_count=Count('id'),
                       total_spend=Sum('total'),
                   )
                   .order_by('-total_spend'))

    # Per-month trend
    monthly = defaultdict(float)
    for po in qs.values('created_at', 'total'):
        key = po['created_at'].strftime('%Y-%m')
        monthly[key] += float(po['total'] or 0)
    monthly_rows = sorted(monthly.items())

    summary = {
        'po_count': qs.count(),
        'total_spend': float(qs.aggregate(s=Sum('total'))['s'] or 0),
        'vendor_count': len({v['vendor_name'] for v in by_vendor}),
        'window_days': 365,
    }

    fmt = (request.GET.get('format') or '').lower()
    if fmt == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="procurement-summary.csv"'
        w = _csv.writer(resp)
        w.writerow(['Vendor', 'PO count', 'Total spend'])
        for v in by_vendor:
            w.writerow([v['vendor_name'], v['po_count'],
                        float(v['total_spend'] or 0)])
        return resp
    if fmt == 'pdf':
        # v3.17.326 — Phase 19 v8 PDF export.
        from .pdf_export import render_pdf
        kpis = [
            {'label': 'PO COUNT', 'value': str(summary['po_count'])},
            {'label': 'TOTAL SPEND', 'value': f"${summary['total_spend']:,.2f}"},
            {'label': 'VENDORS', 'value': str(summary['vendor_count'])},
            {'label': 'WINDOW', 'value': f"{summary['window_days']}d"},
        ]
        tables = [
            {'heading': 'By vendor',
             'header_row': ['Vendor', 'PO count', 'Total spend'],
             'body_rows': [[v['vendor_name'], str(v['po_count']),
                            f"${float(v['total_spend'] or 0):,.2f}"]
                           for v in by_vendor],
             'align_right_cols': [1, 2]},
            {'heading': 'Monthly spend trend',
             'header_row': ['Month', 'Spend'],
             'body_rows': [[m, f"${a:,.2f}"] for m, a in monthly_rows],
             'align_right_cols': [1]},
        ]
        return render_pdf(
            title='Procurement Summary',
            subtitle='Last 365 days of committed POs (draft/cancelled/void excluded).',
            kpis=kpis, tables=tables,
            filename='procurement-summary.pdf')

    return render(request, 'reports/procurement_summary.html', {
        'by_vendor': by_vendor,
        'monthly_rows': monthly_rows,
        'summary': summary,
    })


@login_required
def vendor_cost_history(request):
    """
    Phase 13 v5 (v3.17.262): vendor cost history. Aggregates
    PurchaseOrderLineItem rows per (vendor_name, sku, description) over
    the last 730 days so a buyer can see price-at-time-of-PO drift —
    "this Cisco SFP cost $40 in March, $52 in October."

    Tenant ACL: staff/superuser only — same gate as procurement_summary.
    Optional ?vendor= filter narrows to one vendor; ?format=csv exports.
    """
    from psa.models import PurchaseOrderLineItem
    from datetime import date as _date, timedelta as _td
    from django.db.models import Avg, Count, Max, Min, Sum
    from collections import defaultdict

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Procurement reports are staff-only')

    cutoff = _date.today() - _td(days=730)
    qs = (PurchaseOrderLineItem.objects
          .filter(po__created_at__date__gte=cutoff)
          .exclude(po__status__in=['draft', 'cancelled', 'void'])
          .select_related('po'))

    vendor_filter = (request.GET.get('vendor') or '').strip()
    if vendor_filter:
        qs = qs.filter(po__vendor_name__iexact=vendor_filter)

    # Per (vendor_name, sku-or-desc) aggregates. Use sku when present,
    # else fall back to description so cross-PO matching still works
    # for vendors that don't supply SKUs.
    grouped = defaultdict(lambda: {
        'po_count': 0,
        'total_qty': 0.0,
        'min_price': None,
        'max_price': None,
        'sum_amount': 0.0,
        'last_price': None,
        'last_seen': None,
        'samples': 0,
    })
    for li in qs.values(
        'po__vendor_name', 'po__created_at',
        'sku', 'description', 'unit_price', 'quantity',
    ):
        vendor = li['po__vendor_name'] or '—'
        sku = li['sku'] or ''
        desc = li['description'] or ''
        key = (vendor, sku, desc)
        b = grouped[key]
        price = float(li['unit_price'] or 0)
        qty = float(li['quantity'] or 0)
        b['po_count'] += 1
        b['samples'] += 1
        b['total_qty'] += qty
        b['sum_amount'] += price * qty
        b['min_price'] = price if b['min_price'] is None else min(b['min_price'], price)
        b['max_price'] = price if b['max_price'] is None else max(b['max_price'], price)
        seen = li['po__created_at']
        if b['last_seen'] is None or seen > b['last_seen']:
            b['last_seen'] = seen
            b['last_price'] = price

    # Flatten + sort by total_amount desc.
    rows = []
    for (vendor, sku, desc), b in grouped.items():
        avg_price = (b['sum_amount'] / b['total_qty']) if b['total_qty'] else 0.0
        spread = ((b['max_price'] or 0) - (b['min_price'] or 0))
        rows.append({
            'vendor': vendor, 'sku': sku, 'description': desc,
            'po_count': b['po_count'],
            'total_qty': b['total_qty'],
            'min_price': b['min_price'] or 0,
            'max_price': b['max_price'] or 0,
            'avg_price': avg_price,
            'last_price': b['last_price'] or 0,
            'last_seen': b['last_seen'],
            'spread': spread,
        })
    rows.sort(key=lambda r: -float(r['po_count']))

    vendors = sorted({(li.get('po__vendor_name') or '') for li
                      in qs.values('po__vendor_name').distinct()
                      if li.get('po__vendor_name')})

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="vendor-cost-history.csv"'
        w = _csv.writer(resp)
        w.writerow(['Vendor', 'SKU', 'Description', 'PO count', 'Total qty',
                    'Min price', 'Max price', 'Avg price', 'Last price', 'Last seen'])
        for r in rows:
            w.writerow([
                r['vendor'], r['sku'], r['description'],
                r['po_count'], r['total_qty'],
                r['min_price'], r['max_price'], r['avg_price'],
                r['last_price'],
                r['last_seen'].isoformat() if r['last_seen'] else '',
            ])
        return resp

    return render(request, 'reports/vendor_cost_history.html', {
        'rows': rows,
        'vendor_filter': vendor_filter,
        'vendors': vendors,
        'window_days': 730,
        'total_lines': qs.count(),
    })


@login_required
def asset_lifecycle_report(request):
    """
    Phase 13 v6 (v3.17.263): asset lifecycle scoring. Computes a
    composite 0-100 replacement-priority score per asset (age × warranty
    × firmware) and lists top-scoring rows so a buyer can see what to
    refresh first.

    Tenant-scoped — `Asset.objects.for_organization(org)` for the active
    org; superuser/staff in global view sees everything.
    """
    from assets.models import Asset
    from core.middleware import get_request_organization

    threshold = int(request.GET.get('threshold') or 50)

    org = get_request_organization(request)
    if org is None:
        if request.user.is_superuser or getattr(request, 'is_staff_user', False):
            qs = Asset.objects.all()
        else:
            from django.http import Http404
            raise Http404('Pick an organization')
    else:
        qs = Asset.objects.for_organization(org)

    # Limit candidate set to assets that COULD plausibly score — must
    # have at least one of purchase_date / warranty_expiry / firmware
    # mismatch. Skips fresh imports with empty lifecycle data.
    from django.db.models import Q
    qs = qs.filter(
        Q(purchase_date__isnull=False)
        | Q(warranty_expiry__isnull=False)
        | (Q(firmware_version__gt='') & Q(firmware_latest__gt=''))
    ).select_related('organization')[:5000]

    rows = []
    for a in qs:
        score = a.lifecycle_score()
        if score['total'] < threshold:
            continue
        rows.append({
            'asset': a,
            'score': score,
            'org_name': a.organization.name if a.organization else '',
        })
    rows.sort(key=lambda r: -r['score']['total'])

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="asset-lifecycle.csv"'
        w = _csv.writer(resp)
        w.writerow(['Asset', 'Type', 'Org', 'Total', 'Age', 'Warranty', 'Firmware',
                    'Purchase date', 'Warranty expiry'])
        for r in rows:
            a = r['asset']
            s = r['score']
            w.writerow([
                a.name, a.asset_type, r['org_name'],
                s['total'], s['age'], s['warranty'], s['firmware'],
                a.purchase_date.isoformat() if a.purchase_date else '',
                a.warranty_expiry.isoformat() if a.warranty_expiry else '',
            ])
        return resp

    return render(request, 'reports/asset_lifecycle.html', {
        'rows': rows[:500],
        'threshold': threshold,
        'total_count': len(rows),
    })


@login_required
def procurement_forecasting(request):
    """
    Phase 13 v8 (v3.17.268): procurement forecasting. Reads the last
    12 months of committed POs (excluding draft / cancelled / void)
    and projects the next 3 months of per-vendor spend using a
    3-month moving average, which is roughly what a buyer would
    eyeball anyway but consistent + exportable.

    Tenant ACL: staff/superuser only — same gate as procurement_summary.
    """
    from psa.models import PurchaseOrder
    from datetime import date as _date, timedelta as _td
    from collections import defaultdict
    from dateutil.relativedelta import relativedelta as _rd

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Procurement reports are staff-only')

    # 12 months back so we have enough data for a 3-month MA per vendor.
    cutoff = _date.today() - _td(days=365)
    qs = (PurchaseOrder.objects
          .filter(created_at__date__gte=cutoff)
          .exclude(status__in=['draft', 'cancelled', 'void']))

    # vendor → {YYYY-MM: spend}
    monthly_by_vendor = defaultdict(lambda: defaultdict(float))
    overall_monthly = defaultdict(float)
    for po in qs.values('vendor_name', 'created_at', 'total'):
        vendor = po['vendor_name'] or '—'
        key = po['created_at'].strftime('%Y-%m')
        amt = float(po['total'] or 0)
        monthly_by_vendor[vendor][key] += amt
        overall_monthly[key] += amt

    # Last 6 months of keys, in chronological order
    today = _date.today().replace(day=1)
    history_keys = []
    cur = today - _rd(months=5)
    for _ in range(6):
        history_keys.append(cur.strftime('%Y-%m'))
        cur += _rd(months=1)

    # Forecast keys: next 3 months
    forecast_keys = []
    cur = today + _rd(months=1)
    for _ in range(3):
        forecast_keys.append(cur.strftime('%Y-%m'))
        cur += _rd(months=1)

    # Per-vendor forecast: 3-month MA over the last 3 months of history.
    rows = []
    for vendor, months in monthly_by_vendor.items():
        history = [round(months.get(k, 0.0), 2) for k in history_keys]
        last_three = [months.get(k, 0.0) for k in history_keys[-3:]]
        forecast_per_month = sum(last_three) / 3.0 if last_three else 0.0
        rows.append({
            'vendor': vendor,
            'history': list(zip(history_keys, history)),
            'avg_3mo': round(forecast_per_month, 2),
            'forecast_total_3mo': round(forecast_per_month * 3, 2),
            'history_total': round(sum(history), 2),
        })
    rows.sort(key=lambda r: -r['forecast_total_3mo'])

    overall_history = [round(overall_monthly.get(k, 0.0), 2) for k in history_keys]
    overall_last_three = [overall_monthly.get(k, 0.0) for k in history_keys[-3:]]
    overall_forecast = round(
        (sum(overall_last_three) / 3.0) * 3 if overall_last_three else 0, 2,
    )

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="procurement-forecasting.csv"'
        w = _csv.writer(resp)
        w.writerow(['Vendor'] + [f'Hist {k}' for k in history_keys]
                   + ['3-mo avg', f'Forecast next 3-mo ({", ".join(forecast_keys)})'])
        for r in rows:
            w.writerow([r['vendor']] + [v for _k, v in r['history']]
                       + [r['avg_3mo'], r['forecast_total_3mo']])
        return resp

    return render(request, 'reports/procurement_forecasting.html', {
        'rows': rows,
        'history_keys': history_keys,
        'forecast_keys': forecast_keys,
        'overall_history': list(zip(history_keys, overall_history)),
        'overall_forecast': overall_forecast,
        'total_vendors': len(rows),
    })


@login_required
def hardware_margin_report(request):
    """
    Phase 13 v9 (v3.17.271): hardware-resale margin analytics. For each
    quote that produced both a PurchaseOrder (cost) and an Invoice
    (revenue), compute the resale margin = invoice.total - po.total.

    Match key: shared `source_quote_id` on both rows. Quotes without
    both sides are skipped (the report only summarizes what the books
    can prove). Window defaults to last 365 days, configurable via
    `?days=`.

    Tenant ACL: staff/superuser only — same gate as procurement_summary.
    """
    from psa.models import PurchaseOrder, Invoice
    from datetime import date as _date, timedelta as _td
    from decimal import Decimal as _D
    from collections import defaultdict

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Procurement reports are staff-only')

    try:
        days = max(7, int(request.GET.get('days') or 365))
    except (TypeError, ValueError):
        days = 365
    cutoff = _date.today() - _td(days=days)

    pos = (PurchaseOrder.objects
           .filter(created_at__date__gte=cutoff,
                   source_quote__isnull=False)
           .exclude(status__in=['draft', 'cancelled', 'void']))
    invs = (Invoice.objects
            .filter(invoice_date__gte=cutoff,
                    source_quote__isnull=False)
            .exclude(status='void'))

    # Group totals by source_quote
    po_total_by_quote = defaultdict(lambda: _D('0'))
    po_count_by_quote = defaultdict(int)
    po_vendor_by_quote = {}
    for po in pos.values('source_quote_id', 'vendor_name', 'total'):
        po_total_by_quote[po['source_quote_id']] += _D(str(po['total'] or 0))
        po_count_by_quote[po['source_quote_id']] += 1
        if po['source_quote_id'] not in po_vendor_by_quote and po['vendor_name']:
            po_vendor_by_quote[po['source_quote_id']] = po['vendor_name']

    inv_total_by_quote = defaultdict(lambda: _D('0'))
    inv_client_by_quote = {}
    for inv in invs.values('source_quote_id', 'client_org__name', 'total'):
        inv_total_by_quote[inv['source_quote_id']] += _D(str(inv['total'] or 0))
        if inv['source_quote_id'] not in inv_client_by_quote and inv['client_org__name']:
            inv_client_by_quote[inv['source_quote_id']] = inv['client_org__name']

    # Match: keep only quotes that appear on BOTH sides
    matched = set(po_total_by_quote.keys()) & set(inv_total_by_quote.keys())

    rows = []
    from psa.models import Quote
    quote_meta = {q.pk: q for q in
                   Quote.objects.filter(pk__in=matched).only(
                       'pk', 'quote_number', 'title')}
    for q_id in matched:
        cost = po_total_by_quote[q_id]
        revenue = inv_total_by_quote[q_id]
        margin = revenue - cost
        margin_pct = (float(margin) / float(revenue) * 100) if revenue else 0
        q = quote_meta.get(q_id)
        rows.append({
            'quote_id': q_id,
            'quote_number': q.quote_number if q else f'#{q_id}',
            'title': q.title if q else '',
            'client': inv_client_by_quote.get(q_id, ''),
            'vendor': po_vendor_by_quote.get(q_id, ''),
            'cost': cost,
            'revenue': revenue,
            'margin': margin,
            'margin_pct': round(margin_pct, 1),
            'po_count': po_count_by_quote[q_id],
        })
    rows.sort(key=lambda r: -float(r['margin']))

    totals = {
        'cost': sum(r['cost'] for r in rows),
        'revenue': sum(r['revenue'] for r in rows),
        'margin': sum(r['margin'] for r in rows),
        'count': len(rows),
    }
    blended_pct = (float(totals['margin']) / float(totals['revenue']) * 100
                    if totals['revenue'] else 0)
    totals['margin_pct'] = round(blended_pct, 1)

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="hardware-margin.csv"'
        w = _csv.writer(resp)
        w.writerow(['Quote', 'Title', 'Client', 'Vendor',
                    'Cost', 'Revenue', 'Margin', 'Margin %', 'POs'])
        for r in rows:
            w.writerow([r['quote_number'], r['title'], r['client'], r['vendor'],
                        str(r['cost']), str(r['revenue']), str(r['margin']),
                        r['margin_pct'], r['po_count']])
        w.writerow(['TOTAL', '', '', '',
                    str(totals['cost']), str(totals['revenue']),
                    str(totals['margin']), totals['margin_pct'], ''])
        return resp

    return render(request, 'reports/hardware_margin.html', {
        'rows': rows,
        'totals': totals,
        'days': days,
    })


@login_required
def sla_forecast_report(request):
    """
    Phase 19 v2 (v3.17.320): SLA forecasting. Predicts breach risk on
    open tickets BEFORE they breach. For each open ticket with
    `resolution_due_at` set, compute % of the SLA window already
    elapsed (now - created_at) / (due - created_at), classify into:
        ok        — < 60% elapsed
        at_risk   — 60–84% elapsed
        critical  — 85–99% elapsed
        breached  — already past due (>= 100%)
    Sort by descending risk so dispatchers triage the riskiest tickets
    first.

    Tenant ACL: superuser/staff sees all; org members see only their orgs.
    Optional `?format=csv` exports.
    """
    from psa.models import Ticket
    from django.utils import timezone as _tz

    qs = (Ticket.objects
          .filter(status__is_terminal=False, resolution_due_at__isnull=False)
          .select_related('organization', 'priority', 'status', 'queue',
                          'assigned_to'))

    if not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        qs = qs.filter(organization_id__in=ids)

    now = _tz.now()
    rows = []
    bucket_counts = {'ok': 0, 'at_risk': 0, 'critical': 0, 'breached': 0}
    for t in qs:
        # Use the ticket's start time as the SLA window anchor.
        anchor = t.created_at
        due = t.resolution_due_at
        if not anchor or not due or due <= anchor:
            continue
        total_seconds = (due - anchor).total_seconds()
        elapsed_seconds = (now - anchor).total_seconds()
        pct = (elapsed_seconds / total_seconds) * 100.0
        if pct >= 100:
            risk = 'breached'
        elif pct >= 85:
            risk = 'critical'
        elif pct >= 60:
            risk = 'at_risk'
        else:
            risk = 'ok'
        bucket_counts[risk] += 1
        rows.append({
            'ticket': t,
            'ticket_id': t.id,
            'subject': t.subject,
            'org_name': t.organization.name if t.organization else '',
            'priority': getattr(t.priority, 'code', '') or '',
            'status': getattr(t.status, 'name', '') or '',
            'assigned_to': (t.assigned_to.username
                            if t.assigned_to else '—'),
            'created_at': anchor,
            'resolution_due_at': due,
            'pct_elapsed': round(pct, 1),
            'risk': risk,
        })

    # Sort: breached first (highest pct), then critical, at_risk, ok.
    risk_rank = {'breached': 0, 'critical': 1, 'at_risk': 2, 'ok': 3}
    rows.sort(key=lambda r: (risk_rank[r['risk']], -r['pct_elapsed']))

    summary = {
        'total': len(rows),
        'breached': bucket_counts['breached'],
        'critical': bucket_counts['critical'],
        'at_risk': bucket_counts['at_risk'],
        'ok': bucket_counts['ok'],
        'risk_total': (bucket_counts['breached']
                       + bucket_counts['critical']
                       + bucket_counts['at_risk']),
    }

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="sla-forecast.csv"'
        w = _csv.writer(resp)
        w.writerow(['Ticket', 'Subject', 'Client', 'Priority', 'Status',
                    'Assigned to', 'Created', 'Due', '% elapsed', 'Risk'])
        for r in rows:
            w.writerow([r['ticket_id'], r['subject'], r['org_name'],
                        r['priority'], r['status'], r['assigned_to'],
                        r['created_at'].isoformat() if r['created_at'] else '',
                        r['resolution_due_at'].isoformat() if r['resolution_due_at'] else '',
                        r['pct_elapsed'], r['risk']])
        return resp

    return render(request, 'reports/sla_forecast.html', {
        'rows': rows[:500],
        'summary': summary,
    })


@login_required
def quote_conversion_report(request):
    """
    Phase 19 v3 (v3.17.321): quote conversion tracking. For sales pipeline
    visibility — within a configurable window (default 90 days), show:
        * Total quotes created
        * Quotes accepted (status=accepted)
        * Quotes converted to invoice (linked via Invoice.source_quote)
        * Acceptance rate, conversion rate
        * Aggregated quoted-vs-invoiced dollars
        * Per-creator (sales rep / source_user_role proxy) breakdown via
          `created_by` user

    Tenant ACL: staff/superuser only — sales metric is MSP-internal.
    Window via `?days=N` (default 90, max 365). CSV export via `?format=csv`.
    """
    from psa.models import Quote, Invoice
    from datetime import timedelta as _td
    from decimal import Decimal as _D
    from django.utils import timezone as _tz
    from django.db.models import Sum
    from collections import defaultdict

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Quote conversion is staff-only')

    try:
        days = int(request.GET.get('days') or 90)
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(days, 365))
    cutoff = _tz.now() - _td(days=days)

    qs = (Quote.objects.filter(created_at__gte=cutoff)
          .select_related('client_org', 'created_by'))

    # Quotes converted = those with at least one Invoice that points back
    # via Invoice.source_quote.
    converted_quote_ids = set(Invoice.objects
                              .filter(source_quote__created_at__gte=cutoff,
                                      source_quote__isnull=False)
                              .values_list('source_quote_id', flat=True))
    invoiced_total_by_quote = defaultdict(_D)
    for inv in (Invoice.objects.filter(source_quote_id__in=converted_quote_ids)
                .values('source_quote_id', 'total')):
        invoiced_total_by_quote[inv['source_quote_id']] += _D(str(inv['total'] or 0))

    # Per-creator breakdown.
    by_creator = defaultdict(lambda: {
        'creator': '',
        'quotes': 0,
        'accepted': 0,
        'converted': 0,
        'quoted_total': _D('0'),
        'invoiced_total': _D('0'),
    })

    total_quotes = 0
    total_accepted = 0
    total_converted = 0
    total_quoted_amount = _D('0')
    total_invoiced_amount = _D('0')

    for q in qs:
        creator_key = q.created_by.username if q.created_by else '—'
        bucket = by_creator[creator_key]
        bucket['creator'] = creator_key
        bucket['quotes'] += 1
        total_quotes += 1
        bucket['quoted_total'] += _D(str(q.total or 0))
        total_quoted_amount += _D(str(q.total or 0))
        if q.status == 'accepted':
            bucket['accepted'] += 1
            total_accepted += 1
        if q.id in converted_quote_ids:
            bucket['converted'] += 1
            total_converted += 1
            invoiced = invoiced_total_by_quote.get(q.id, _D('0'))
            bucket['invoiced_total'] += invoiced
            total_invoiced_amount += invoiced

    rows = []
    for c, b in by_creator.items():
        accept_pct = (100.0 * b['accepted'] / b['quotes']) if b['quotes'] else 0
        conv_pct = (100.0 * b['converted'] / b['quotes']) if b['quotes'] else 0
        rows.append({
            **b,
            'accept_pct': round(accept_pct, 1),
            'conversion_pct': round(conv_pct, 1),
        })
    rows.sort(key=lambda r: -r['quotes'])

    summary = {
        'days': days,
        'total_quotes': total_quotes,
        'total_accepted': total_accepted,
        'total_converted': total_converted,
        'total_quoted_amount': total_quoted_amount,
        'total_invoiced_amount': total_invoiced_amount,
        'accept_pct': round(
            100.0 * total_accepted / total_quotes, 1) if total_quotes else 0,
        'conversion_pct': round(
            100.0 * total_converted / total_quotes, 1) if total_quotes else 0,
    }

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="quote-conversion.csv"'
        w = _csv.writer(resp)
        w.writerow(['Creator', 'Quotes', 'Accepted', 'Converted',
                    'Accept %', 'Conv %', 'Quoted total', 'Invoiced total'])
        for r in rows:
            w.writerow([r['creator'], r['quotes'], r['accepted'], r['converted'],
                        r['accept_pct'], r['conversion_pct'],
                        str(r['quoted_total']), str(r['invoiced_total'])])
        w.writerow(['TOTAL', summary['total_quotes'], summary['total_accepted'],
                    summary['total_converted'], summary['accept_pct'],
                    summary['conversion_pct'],
                    str(summary['total_quoted_amount']),
                    str(summary['total_invoiced_amount'])])
        return resp

    return render(request, 'reports/quote_conversion.html', {
        'rows': rows,
        'summary': summary,
    })


@login_required
def kpi_dashboard(request):
    """
    Phase 19 v4 (v3.17.322): KPI dashboard. A read-only single-page
    grid of widgets that pulls live numbers from existing model
    queries — no new model needed.

    Widgets surfaced:
        * open_ticket_count             — non-terminal ticket count
        * mean_open_ticket_age_hours    — avg(now - created_at) over open
        * weekly_closed_count           — tickets that became terminal
                                           in the last 7 days (via resolved_at)
        * sla_breach_count_30d          — tickets with sla_breached_resolution
                                           within last 30 days
        * mrr_total                     — same calc as mrr_forecast_report
        * arr_total                     — mrr * 12

    Tenant ACL: superuser/staff sees MSP-wide; org members get scoped to
    their orgs (MRR widgets are zeroed for non-staff because contracts
    are MSP-internal).
    """
    from psa.models import Ticket, Contract
    from datetime import timedelta as _td
    from decimal import Decimal as _D
    from django.utils import timezone as _tz

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    org_ids = []
    if not is_staff:
        if hasattr(request.user, 'memberships'):
            org_ids = list(request.user.memberships.filter(is_active=True)
                                       .values_list('organization_id', flat=True))

    now = _tz.now()
    week_ago = now - _td(days=7)
    month_ago = now - _td(days=30)

    # Open tickets (non-terminal)
    open_qs = Ticket.objects.filter(status__is_terminal=False)
    if not is_staff:
        open_qs = open_qs.filter(organization_id__in=org_ids)
    open_count = open_qs.count()

    # Mean open ticket age in hours
    if open_count:
        total_seconds = sum(
            (now - t).total_seconds()
            for t in open_qs.values_list('created_at', flat=True)
            if t is not None
        )
        mean_age_hours = round(total_seconds / open_count / 3600.0, 1)
    else:
        mean_age_hours = 0.0

    # Closed in the last 7 days (tickets that hit a terminal status)
    weekly_closed_qs = Ticket.objects.filter(
        status__is_terminal=True, resolved_at__gte=week_ago)
    if not is_staff:
        weekly_closed_qs = weekly_closed_qs.filter(organization_id__in=org_ids)
    weekly_closed_count = weekly_closed_qs.count()

    # SLA breach count last 30 days (resolution breach flag set on tickets
    # touched in the window)
    breach_qs = Ticket.objects.filter(
        sla_breached_resolution=True, updated_at__gte=month_ago)
    if not is_staff:
        breach_qs = breach_qs.filter(organization_id__in=org_ids)
    sla_breach_count = breach_qs.count()

    # MRR / ARR — staff only
    mrr_total = _D('0')
    arr_total = _D('0')
    contract_count = 0
    if is_staff:
        contracts = (Contract.objects.filter(status='active')
                     .exclude(billing_frequency='none'))
        for c in contracts:
            amount = c.effective_recurring_amount
            if amount <= 0:
                continue
            if c.billing_frequency == 'monthly':
                mrr_total += amount
            elif c.billing_frequency == 'quarterly':
                mrr_total += (amount / _D('3'))
            elif c.billing_frequency == 'yearly':
                mrr_total += (amount / _D('12'))
            contract_count += 1
        mrr_total = mrr_total.quantize(_D('0.01'))
        arr_total = (mrr_total * _D('12')).quantize(_D('0.01'))

    widgets = {
        'open_ticket_count': open_count,
        'mean_open_ticket_age_hours': mean_age_hours,
        'weekly_closed_count': weekly_closed_count,
        'sla_breach_count_30d': sla_breach_count,
        'mrr_total': mrr_total,
        'arr_total': arr_total,
        'contract_count': contract_count,
        'is_staff_view': is_staff,
    }

    fmt = (request.GET.get('format') or '').lower()
    if fmt == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="kpi-dashboard.csv"'
        w = _csv.writer(resp)
        w.writerow(['Metric', 'Value'])
        for k, v in widgets.items():
            w.writerow([k, v])
        return resp
    if fmt == 'pdf':
        # v3.17.326 — Phase 19 v8 PDF export.
        from .pdf_export import render_pdf
        kpis = [
            {'label': 'OPEN TICKETS', 'value': str(widgets['open_ticket_count'])},
            {'label': 'MEAN OPEN AGE',
             'value': f"{widgets['mean_open_ticket_age_hours']}h"},
            {'label': 'CLOSED LAST 7d',
             'value': str(widgets['weekly_closed_count'])},
            {'label': 'SLA BREACHES (30d)',
             'value': str(widgets['sla_breach_count_30d'])},
        ]
        if widgets['is_staff_view']:
            kpis += [
                {'label': 'MRR', 'value': f"${float(widgets['mrr_total']):,.0f}"},
                {'label': 'ARR', 'value': f"${float(widgets['arr_total']):,.0f}"},
            ]
        return render_pdf(
            title='KPI Dashboard',
            subtitle='Live operational metrics snapshot.',
            kpis=kpis, tables=[],
            filename='kpi-dashboard.pdf')

    return render(request, 'reports/kpi_dashboard.html', {
        'widgets': widgets,
    })


@login_required
def operational_metrics_report(request):
    """
    Phase 19 v5 (v3.17.323): operational metrics. Per-window aggregates
    that drive ops-team performance reviews:

      * Mean time to first response — avg of (first_response_at - created_at)
        on tickets that received their first response within the window
      * Mean time to resolution — avg of (resolved_at - created_at) on
        tickets resolved within the window
      * First-touch resolution rate — % of resolved-this-window tickets
        whose ONLY non-system comment was the resolution itself (i.e.
        no back-and-forth)
      * Queue depth distribution — current open count per queue
      * Age distribution — same buckets as ticket-aging report

    Tenant ACL: superuser/staff sees all; org members see only their orgs.
    Window via `?days=N` (default 30, capped 1–365).
    """
    from psa.models import Ticket, TicketComment, Queue
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    from collections import defaultdict
    from django.db.models import Count, Q

    try:
        days = int(request.GET.get('days') or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))

    now = _tz.now()
    cutoff = now - _td(days=days)

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    org_filter = Q()
    if not is_staff:
        ids = []
        if hasattr(request.user, 'memberships'):
            ids = list(request.user.memberships.filter(is_active=True)
                                  .values_list('organization_id', flat=True))
        org_filter = Q(organization_id__in=ids)

    # Mean time to first response
    fr_qs = Ticket.objects.filter(org_filter, first_response_at__isnull=False,
                                   first_response_at__gte=cutoff)
    total_fr_seconds = 0
    fr_count = 0
    for created, fr in fr_qs.values_list('created_at', 'first_response_at'):
        if created and fr and fr >= created:
            total_fr_seconds += (fr - created).total_seconds()
            fr_count += 1
    mttr_response_hours = round(total_fr_seconds / fr_count / 3600.0, 2) if fr_count else 0

    # Mean time to resolution
    res_qs = Ticket.objects.filter(org_filter, resolved_at__isnull=False,
                                    resolved_at__gte=cutoff)
    total_res_seconds = 0
    res_count = 0
    res_ticket_ids = []
    for tid, created, res in res_qs.values_list('id', 'created_at', 'resolved_at'):
        if created and res and res >= created:
            total_res_seconds += (res - created).total_seconds()
            res_count += 1
            res_ticket_ids.append(tid)
    mttr_resolution_hours = round(total_res_seconds / res_count / 3600.0, 2) if res_count else 0

    # First-touch resolution: of tickets resolved in the window, those that
    # had at most ONE non-system, non-internal "outbound" comment (the
    # resolution comment itself). Approximate by counting non-system
    # comments per resolved ticket — <=1 = first-touch.
    ftr_count = 0
    if res_ticket_ids:
        comment_counts = (TicketComment.objects
                          .filter(ticket_id__in=res_ticket_ids, is_system=False)
                          .values('ticket_id')
                          .annotate(c=Count('id')))
        # Map ticket_id -> count
        cmap = {row['ticket_id']: row['c'] for row in comment_counts}
        for tid in res_ticket_ids:
            # 0 or 1 non-system comments = first-touch
            if cmap.get(tid, 0) <= 1:
                ftr_count += 1
    ftr_pct = round(100.0 * ftr_count / res_count, 1) if res_count else 0

    # Queue depth distribution (current open)
    qdepth = (Ticket.objects.filter(org_filter, status__is_terminal=False)
              .values('queue__name')
              .annotate(c=Count('id')).order_by('-c'))
    queue_rows = [{'queue': r['queue__name'] or '—', 'open': r['c']}
                  for r in qdepth]

    # Age distribution buckets (current open)
    open_qs = Ticket.objects.filter(org_filter, status__is_terminal=False)
    age_buckets = {'0-24h': 0, '24-72h': 0, '3-7d': 0, '7-30d': 0, '30+d': 0}
    for ct in open_qs.values_list('created_at', flat=True):
        if not ct:
            continue
        age_h = (now - ct).total_seconds() / 3600.0
        if age_h < 24:
            age_buckets['0-24h'] += 1
        elif age_h < 72:
            age_buckets['24-72h'] += 1
        elif age_h < 24 * 7:
            age_buckets['3-7d'] += 1
        elif age_h < 24 * 30:
            age_buckets['7-30d'] += 1
        else:
            age_buckets['30+d'] += 1

    summary = {
        'days': days,
        'mttr_response_hours': mttr_response_hours,
        'mttr_resolution_hours': mttr_resolution_hours,
        'fr_count': fr_count,
        'res_count': res_count,
        'ftr_count': ftr_count,
        'ftr_pct': ftr_pct,
        'open_count': sum(age_buckets.values()),
    }

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="operational-metrics.csv"'
        w = _csv.writer(resp)
        w.writerow(['Metric', 'Value'])
        w.writerow(['Window days', days])
        w.writerow(['Mean time to first response (h)', mttr_response_hours])
        w.writerow(['Mean time to resolution (h)', mttr_resolution_hours])
        w.writerow(['First responses counted', fr_count])
        w.writerow(['Resolutions counted', res_count])
        w.writerow(['First-touch resolution count', ftr_count])
        w.writerow(['First-touch resolution %', ftr_pct])
        w.writerow([])
        w.writerow(['Queue', 'Open'])
        for q in queue_rows:
            w.writerow([q['queue'], q['open']])
        w.writerow([])
        w.writerow(['Age bucket', 'Open'])
        for k, v in age_buckets.items():
            w.writerow([k, v])
        return resp

    return render(request, 'reports/operational_metrics.html', {
        'summary': summary,
        'queue_rows': queue_rows,
        'age_buckets': age_buckets,
    })


@login_required
def workflow_performance_report(request):
    """
    Phase 19 v6 (v3.17.324): workflow performance analytics. Rolls up
    every active `WorkflowRule` with its `fire_count`, `last_fired_at`,
    `last_error` to surface:
        * Top-firing rules (potentially overactive — review for noise)
        * Rules with errors (broken / mis-configured)
        * Distribution by trigger type
        * Distribution by organization (rules can be MSP-wide or per-org)

    Tenant ACL: staff/superuser only — workflow administration is an
    MSP-internal concern. Optional `?format=csv`.
    """
    from psa.models import WorkflowRule
    from collections import defaultdict

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Workflow analytics is staff-only')

    qs = (WorkflowRule.objects.filter(is_active=True)
          .select_related('organization'))

    rows = []
    by_trigger = defaultdict(lambda: {'count': 0, 'fires': 0, 'errors': 0})
    total_fires = 0
    error_count = 0
    org_count_seen = set()

    for r in qs:
        has_error = bool(r.last_error)
        rows.append({
            'id': r.id,
            'name': r.name,
            'trigger': r.trigger,
            'trigger_display': r.get_trigger_display(),
            'organization': r.organization.name if r.organization else 'MSP-wide',
            'fire_count': r.fire_count,
            'last_fired_at': r.last_fired_at,
            'last_error': r.last_error or '',
            'has_error': has_error,
            'fire_once_per_ticket': r.fire_once_per_ticket,
        })
        total_fires += r.fire_count
        if has_error:
            error_count += 1
        bt = by_trigger[r.trigger]
        bt['count'] += 1
        bt['fires'] += r.fire_count
        if has_error:
            bt['errors'] += 1
        org_count_seen.add(r.organization_id)

    # Sort: highest fire_count first; rules with errors break ties to the top.
    rows.sort(key=lambda r: (-r['fire_count'], not r['has_error']))

    # By-trigger distribution sorted by fires descending
    trigger_rows = []
    for trig, b in by_trigger.items():
        trigger_rows.append({
            'trigger': trig,
            'count': b['count'],
            'fires': b['fires'],
            'errors': b['errors'],
        })
    trigger_rows.sort(key=lambda r: -r['fires'])

    summary = {
        'rule_count': len(rows),
        'total_fires': total_fires,
        'error_count': error_count,
        'error_pct': round(100.0 * error_count / len(rows), 1) if rows else 0,
        'org_count': len([o for o in org_count_seen if o is not None]),
        'msp_wide_count': sum(1 for r in rows if r['organization'] == 'MSP-wide'),
    }

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="workflow-performance.csv"'
        w = _csv.writer(resp)
        w.writerow(['Rule', 'Trigger', 'Organization', 'Fires',
                    'Last fired', 'Has error', 'Error message'])
        for r in rows:
            w.writerow([r['name'], r['trigger'], r['organization'],
                        r['fire_count'],
                        r['last_fired_at'].isoformat() if r['last_fired_at'] else '',
                        'yes' if r['has_error'] else 'no',
                        r['last_error']])
        return resp

    return render(request, 'reports/workflow_performance.html', {
        'rows': rows,
        'trigger_rows': trigger_rows,
        'summary': summary,
    })


@login_required
def trends_report(request):
    """
    Phase 19 v7 (v3.17.325): trend analysis + capacity forecasting.
    Combines two sub-bullets:

      Trends section — month-by-month time series for the last 12 months:
        * Tickets opened (count by created_at month)
        * Tickets resolved (count by resolved_at month)
        * MRR added (sum of new active contracts' monthly equivalent)

      Capacity section — per-tech load vs target:
        * Open ticket count assigned to each user
        * Configured `BillableTarget.target_hours_per_week`
        * Utilization proxy: open_count / target_hours (load ratio)

    Tenant ACL: staff/superuser only — capacity + MRR data is MSP-internal.
    """
    from psa.models import Ticket, Contract
    from resourcing.models import BillableTarget
    from datetime import date as _date
    from decimal import Decimal as _D
    from collections import defaultdict
    from django.db.models import Count, Q
    from django.contrib.auth.models import User
    from dateutil.relativedelta import relativedelta as _rd

    is_staff = (request.user.is_superuser
                or getattr(request, 'is_staff_user', False))
    if not is_staff:
        from django.http import Http404
        raise Http404('Trends + capacity report is staff-only')

    today = _date.today().replace(day=1)
    months = []
    for i in range(11, -1, -1):  # 12 months oldest first
        m = today - _rd(months=i)
        months.append(m)

    # Per-month opened/resolved counts
    opened_by_month = defaultdict(int)
    resolved_by_month = defaultdict(int)
    cutoff = months[0]
    cutoff_dt = cutoff
    for ct in Ticket.objects.filter(created_at__date__gte=cutoff_dt).values_list(
            'created_at', flat=True):
        if ct:
            key = ct.strftime('%Y-%m')
            opened_by_month[key] += 1
    for rt in Ticket.objects.filter(resolved_at__date__gte=cutoff_dt).values_list(
            'resolved_at', flat=True):
        if rt:
            key = rt.strftime('%Y-%m')
            resolved_by_month[key] += 1

    # MRR added per month — sum of new active contracts' monthly equiv
    mrr_added_by_month = defaultdict(lambda: _D('0'))
    contracts = (Contract.objects.filter(status='active',
                                          start_date__gte=cutoff_dt)
                 .exclude(billing_frequency='none'))
    for c in contracts:
        amount = c.effective_recurring_amount
        if amount <= 0:
            continue
        if c.billing_frequency == 'monthly':
            mrr = amount
        elif c.billing_frequency == 'quarterly':
            mrr = (amount / _D('3'))
        elif c.billing_frequency == 'yearly':
            mrr = (amount / _D('12'))
        else:
            continue
        key = c.start_date.strftime('%Y-%m')
        mrr_added_by_month[key] += mrr

    trend_rows = []
    for m in months:
        key = m.strftime('%Y-%m')
        trend_rows.append({
            'month': key,
            'opened': opened_by_month.get(key, 0),
            'resolved': resolved_by_month.get(key, 0),
            'mrr_added': mrr_added_by_month.get(key, _D('0')).quantize(_D('0.01')),
        })

    # Capacity section — per-assigned-tech open count vs BillableTarget
    open_assignments = (Ticket.objects.filter(
                            status__is_terminal=False,
                            assigned_to__isnull=False)
                        .values('assigned_to', 'assigned_to__username')
                        .annotate(open_count=Count('id'))
                        .order_by('-open_count'))

    targets_by_user = {bt.user_id: bt.target_hours_per_week
                       for bt in BillableTarget.objects.filter(is_active=True)}

    capacity_rows = []
    for row in open_assignments:
        target = targets_by_user.get(row['assigned_to'])
        load_ratio = None
        if target and target > 0:
            # rough proxy: 1 open ticket ≈ 2 hours work (industry rule of thumb)
            load_ratio = round(float(row['open_count']) * 2.0 / float(target) * 100, 1)
        capacity_rows.append({
            'username': row['assigned_to__username'],
            'open_count': row['open_count'],
            'target_hours': target,
            'load_ratio_pct': load_ratio,
            'over_target': bool(load_ratio and load_ratio > 100),
        })

    # Trend totals
    summary = {
        'total_opened_12m': sum(r['opened'] for r in trend_rows),
        'total_resolved_12m': sum(r['resolved'] for r in trend_rows),
        'total_mrr_added_12m': sum((r['mrr_added'] for r in trend_rows), _D('0')),
        'capacity_users': len(capacity_rows),
        'capacity_over_target': sum(1 for r in capacity_rows if r['over_target']),
    }

    if (request.GET.get('format') or '').lower() == 'csv':
        import csv as _csv
        from django.http import HttpResponse as _HR
        resp = _HR(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="trends-capacity.csv"'
        w = _csv.writer(resp)
        w.writerow(['# Trends'])
        w.writerow(['Month', 'Opened', 'Resolved', 'MRR added'])
        for r in trend_rows:
            w.writerow([r['month'], r['opened'], r['resolved'], str(r['mrr_added'])])
        w.writerow([])
        w.writerow(['# Capacity'])
        w.writerow(['User', 'Open tickets', 'Target h/wk', 'Load %'])
        for r in capacity_rows:
            w.writerow([r['username'], r['open_count'],
                        r['target_hours'] if r['target_hours'] is not None else '',
                        r['load_ratio_pct'] if r['load_ratio_pct'] is not None else ''])
        return resp

    return render(request, 'reports/trends.html', {
        'trend_rows': trend_rows,
        'capacity_rows': capacity_rows,
        'summary': summary,
    })
