"""Shared event layer pages: the event list, one event with its links, and
ingestion health. Staff only (the /security/ prefix) and scoped to the
customers where the user holds security_alerts_view."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from accounts.permission_utils import has_perm_for_org, orgs_with_perm, require_perm, user_has_perm

from . import models as M
from . import projection
from .queue import QUEUE_CAP

VIEW_PERM = 'security_alerts_view'
ACT_PERM = 'security_alerts_acknowledge'
ADMIN_PERM = 'security_alerts_manage_connections'


def scoped_events(user):
    """Events of the customers this user may see. MSP-wide events (no
    customer) only for users who see every customer."""
    allowed = orgs_with_perm(user, VIEW_PERM)
    qs = M.OperationalEvent.objects.all()
    if allowed is None:
        return qs
    return qs.filter(organization_id__in=allowed)


def _may_act(user, event):
    if event.organization_id is None:
        return orgs_with_perm(user, ACT_PERM) is None
    return has_perm_for_org(user, event.organization, ACT_PERM)


@login_required
@require_perm(VIEW_PERM)
def event_list(request):
    qs = scoped_events(request.user).select_related('organization')
    f = {k: request.GET.get(k, '') for k in ('source', 'severity', 'status', 'customer', 'q')}
    if f['source'] in dict(M.SOURCES):
        qs = qs.filter(source=f['source'])
    if f['severity'] in M.SEVERITY_RANK:
        qs = qs.filter(severity=f['severity'])
    if f['status'] == 'all':
        pass
    elif f['status'] in dict(M.STATUSES):
        qs = qs.filter(status=f['status'])
    else:
        f['status'] = ''
        qs = qs.filter(status__in=(M.STATUS_OPEN, M.STATUS_ACK))
    if f['customer'].isdigit():
        qs = qs.filter(organization_id=int(f['customer']))
    if f['q']:
        qs = qs.filter(Q(title__icontains=f['q']) | Q(asset_hint__icontains=f['q'])
                       | Q(vendor_event_id__icontains=f['q']))
    page = Paginator(qs.order_by('-last_seen_at'), 100).get_page(request.GET.get('page'))
    live = scoped_events(request.user).filter(status__in=(M.STATUS_OPEN, M.STATUS_ACK))
    counts = {r['source']: r['n'] for r in live.values('source').annotate(n=Count('pk'))}
    customers = (scoped_events(request.user).filter(organization__isnull=False)
                 .values_list('organization_id', 'organization__name').distinct().order_by('organization__name'))
    return render(request, 'events/event_list.html', {
        'page': page, 'filters': f, 'sources': [(k, v, counts.get(k, 0)) for k, v in M.SOURCES],
        'severities': M.SEVERITIES, 'statuses': M.STATUSES, 'customers': list(customers)[:500],
        'health_problems': M.SourceHealth.objects.filter(consecutive_failures__gt=0).count(),
    })


def source_url(event):
    try:
        if event.source == M.SOURCE_SECURITY:
            return reverse('security_alerts:alert_detail', args=[event.source_id])
        if event.source == M.SOURCE_MONITOR:
            return reverse('monitoring:website_monitor_detail', args=[event.source_id])
        if event.source == M.SOURCE_BACKUP:
            return reverse('backup_monitoring:alert_list')
        if event.source == M.SOURCE_RMM:
            return reverse('integrations:rmm_alerts')
    except NoReverseMatch:
        return ''
    return ''


@login_required
@require_perm(VIEW_PERM)
def event_detail(request, pk):
    event = get_object_or_404(scoped_events(request.user).select_related('organization', 'asset'), pk=pk)
    links = event.links.select_related('ticket', 'incident', 'created_by').order_by('created_at')
    return render(request, 'events/event_detail.html', {
        'event': event, 'links': links, 'source_url': source_url(event), 'can_act': _may_act(request.user, event),
        'related': (scoped_events(request.user).filter(correlation_group=event.correlation_group)
                    .exclude(pk=event.pk).order_by('-last_seen_at')[:20] if event.correlation_group else []),
    })


@login_required
@require_POST
@require_perm(VIEW_PERM)
def event_link(request, pk):
    """Link a ticket or incident by hand. Both must belong to the event's
    customer; lifecycles stay separate."""
    from psa.models import Ticket
    from security_alerts.models import SecurityIncident
    event = get_object_or_404(scoped_events(request.user), pk=pk)
    if not _may_act(request.user, event):
        raise PermissionDenied('You may not change links for this customer.')
    number = (request.POST.get('ticket') or '').strip()
    incident_id = (request.POST.get('incident') or '').strip()
    link = None
    if number:
        tickets = Ticket.objects.filter(organization_id=event.organization_id) if event.organization_id else Ticket.objects.all()
        ticket = tickets.filter(ticket_number__iexact=number).first()
        if ticket is None:
            messages.error(request, f'No ticket {number} for this customer.')
            return redirect('events:detail', pk=pk)
        link = M.EventLink(event=event, ticket=ticket)
    elif incident_id.isdigit():
        incidents = SecurityIncident.objects.all()
        if event.organization_id:
            incidents = incidents.filter(Q(client_org_id=event.organization_id)
                                         | Q(client_org__isnull=True, organization_id=event.organization_id))
        incident = incidents.filter(pk=int(incident_id)).first()
        if incident is None:
            messages.error(request, f'No incident #{incident_id} for this customer.')
            return redirect('events:detail', pk=pk)
        link = M.EventLink(event=event, incident=incident)
    else:
        messages.error(request, 'Enter a ticket number or an incident number.')
        return redirect('events:detail', pk=pk)
    if event.links.filter(ticket_id=link.ticket_id, incident_id=link.incident_id).exists():
        messages.info(request, 'Already linked.')
        return redirect('events:detail', pk=pk)
    link.origin, link.created_by = M.EventLink.ORIGIN_MANUAL, request.user
    link.save()
    _audit(request, event, f'Linked {"ticket " + number if number else "incident #" + incident_id}')
    messages.success(request, 'Linked.')
    return redirect('events:detail', pk=pk)


@login_required
@require_POST
@require_perm(VIEW_PERM)
def event_unlink(request, pk, link_pk):
    event = get_object_or_404(scoped_events(request.user), pk=pk)
    if not _may_act(request.user, event):
        raise PermissionDenied('You may not change links for this customer.')
    link = get_object_or_404(event.links, pk=link_pk, origin=M.EventLink.ORIGIN_MANUAL)
    link.delete()
    _audit(request, event, 'Removed a link')
    messages.success(request, 'Link removed. Links recorded by the source follow the source.')
    return redirect('events:detail', pk=pk)


@login_required
@require_perm(VIEW_PERM)
def ingestion_health(request):
    settings = M.EventSettings.get()
    can_admin = user_has_perm(request.user, ADMIN_PERM) and orgs_with_perm(request.user, ADMIN_PERM) is None
    if request.method == 'POST':
        if not can_admin:
            raise PermissionDenied('Changing event ingestion needs the connection management permission.')
        action = request.POST.get('action')
        if action == 'retry':
            n = projection.retry_dead_letters()
            messages.success(request, f'{n} failed item(s) queued again.')
            _audit(request, None, f'Retried {n} failed event projections')
        elif action == 'settings':
            try:
                values = {k: int(request.POST.get(k) or 0)
                          for k in ('retention_days', 'raw_retention_days', 'max_events')}
            except ValueError:
                messages.error(request, 'Retention and quota must be whole numbers.')
                return redirect('events:health')
            if values['retention_days'] and values['retention_days'] < 7:
                messages.error(request, 'Keep closed events for at least 7 days (0 keeps them forever).')
                return redirect('events:health')
            settings.ingestion_enabled = request.POST.get('ingestion_enabled') == '1'
            for k, v in values.items():
                setattr(settings, k, v)
            settings.save()
            _audit(request, None, 'Changed event ingestion settings', extra={
                'ingestion_enabled': settings.ingestion_enabled, **values})
            messages.success(request, 'Saved.')
        return redirect('events:health')
    health = {h.source: h for h in M.SourceHealth.objects.all()}
    queue = M.ProjectionQueueItem.objects
    rows = [(key, label, health.get(key)) for key, label in M.SOURCES]
    return render(request, 'events/ingestion_health.html', {
        'rows': rows, 'settings': settings, 'can_admin': can_admin,
        'queued': queue.filter(dead=False).count(), 'dead': queue.filter(dead=True).order_by('-queued_at')[:50],
        'dead_count': queue.filter(dead=True).count(), 'event_count': M.OperationalEvent.objects.count(),
        'live_count': M.OperationalEvent.objects.filter(status__in=(M.STATUS_OPEN, M.STATUS_ACK)).count(),
        'queue_cap': QUEUE_CAP,
    })


def _audit(request, event, description, extra=None):
    from audit.models import AuditLog
    AuditLog.log(user=request.user, action='update', organization=event.organization if event else None,
                 object_type='OperationalEvent' if event else 'EventSettings',
                 object_id=event.pk if event else 1, object_repr=(str(event) if event else 'Event ingestion')[:200],
                 description=description, extra_data=extra or {})
