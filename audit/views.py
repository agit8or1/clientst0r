"""
Audit views - View audit logs
"""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Count, Q
from datetime import datetime, timedelta
import csv
import json
from core.middleware import get_request_organization
from core.decorators import require_admin
from .models import AuditLog


@login_required
@require_admin
def audit_log_list(request):
    """
    List audit logs for current organization with filtering.
    Only admins can view audit logs.
    """
    org = get_request_organization(request)

    # Start with all logs for this organization
    logs = AuditLog.objects.filter(organization=org).select_related('user')

    # Calculate stats before filtering
    all_logs = AuditLog.objects.filter(organization=org)
    today = timezone.now().date()

    total_count = all_logs.count()
    today_count = all_logs.filter(timestamp__date=today).count()
    unique_users = all_logs.values('username').distinct().count()
    failed_count = all_logs.filter(success=False).count()

    # Apply filters
    action_filter = request.GET.get('action')
    user_filter = request.GET.get('user')
    object_type_filter = request.GET.get('object_type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if action_filter:
        logs = logs.filter(action=action_filter)

    if user_filter:
        logs = logs.filter(username__icontains=user_filter)

    if object_type_filter:
        logs = logs.filter(object_type=object_type_filter)

    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            logs = logs.filter(timestamp__date__gte=from_date.date())
        except ValueError:
            pass

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            logs = logs.filter(timestamp__date__lte=to_date.date())
        except ValueError:
            pass

    # Order by timestamp descending
    logs = logs.order_by('-timestamp')

    # Handle export
    export_format = request.GET.get('export')
    if export_format in ['csv', 'json']:
        return export_audit_logs(logs, export_format)

    # Limit to 1000 most recent for performance with DataTables
    logs = logs[:1000]

    # Get distinct values for filters
    actions = AuditLog.objects.filter(organization=org).values_list('action', flat=True).distinct()
    object_types = AuditLog.objects.filter(organization=org).values_list('object_type', flat=True).distinct()

    return render(request, 'audit/audit_log_list.html', {
        'logs': logs,
        'total_count': total_count,
        'today_count': today_count,
        'unique_users': unique_users,
        'failed_count': failed_count,
        'actions': sorted(set(actions)),
        'object_types': sorted(set(filter(None, object_types))),
        'current_action': action_filter,
        'current_user': user_filter,
        'current_object_type': object_type_filter,
        'date_from': date_from,
        'date_to': date_to,
    })


def export_audit_logs(logs, format_type):
    """Export audit logs as CSV or JSON."""
    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="audit_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow(['Timestamp', 'User', 'Action', 'Object Type', 'Object ID', 'Object', 'IP Address', 'Success', 'Details'])

        for log in logs[:5000]:  # Limit export to 5000 rows
            writer.writerow([
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                log.username or 'System',
                log.action,
                log.object_type or '',
                log.object_id or '',
                log.object_repr or '',
                log.ip_address or '',
                'Yes' if log.success else 'No',
                log.description or '',
            ])

        return response

    elif format_type == 'json':
        data = []
        for log in logs[:5000]:  # Limit export to 5000 rows
            data.append({
                'timestamp': log.timestamp.isoformat(),
                'user': log.username or 'System',
                'action': log.action,
                'object_type': log.object_type or '',
                'object_id': log.object_id,
                'object_repr': log.object_repr or '',
                'ip_address': log.ip_address or '',
                'success': log.success,
                'description': log.description or '',
                'user_agent': log.user_agent or '',
            })

        response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="audit_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'
        return response


@login_required
@require_admin
def audit_log_detail(request, pk):
    """
    View detailed audit log entry.
    Only admins can view audit logs.
    """
    org = get_request_organization(request)
    log = get_object_or_404(AuditLog, pk=pk, organization=org)

    return render(request, 'audit/audit_log_detail.html', {
        'log': log,
    })
