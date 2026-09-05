"""
Phase 40.2 (v3.17.540) — status page views.

One unauthenticated view (the page) and a small set of authenticated ones for
managing them.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.decorators import require_admin
from core.models import Organization
from monitoring.models import WebsiteMonitor

from .models import (
    IncidentUpdate, MaintenanceWindow, StatusPage, StatusPageIncident,
    StatusPageService,
)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def public(request, token):
    """The status page itself. No authentication — that is the point.

    A disabled or unknown token 404s identically. Distinguishing them would
    confirm to anyone probing that a page exists at that address.
    """
    # Phase 40.5 — a portal page's token must not work anonymously. Same 404
    # as a disabled or unknown one: the response never distinguishes between
    # "wrong token", "switched off" and "needs a login".
    page = StatusPage.objects.filter(
        token=token, is_enabled=True,
        visibility=StatusPage.VISIBILITY_PUBLIC).first()
    if page is None:
        raise Http404('No status page here')

    return _render_page(request, page)


def _page_context(page):
    """Everything the status page template needs. Shared by the public view
    and the portal one so the two cannot drift apart in what they show."""
    services = page.visible_services()
    rows = [{
        'service': svc,
        'status': svc.current_status(),
        'uptime': svc.uptime_windows() if page.show_uptime else [],
    } for svc in services]

    # Phase 40.3 — planned work. Upcoming and in-progress windows are the
    # whole point (they exist to pre-empt the "is it broken?" call), so they
    # show unconditionally. Finished ones are capped: a page that lists every
    # maintenance since inception buries the one happening tonight.
    windows = page.maintenance_windows.prefetch_related('services').all()
    active, upcoming, recent = [], [], []
    for w in windows:
        state = w.state
        if state == 'in_progress':
            active.append(w)
        elif state == 'upcoming':
            upcoming.append(w)
        elif state in ('completed', 'cancelled') and len(recent) < 5:
            recent.append(w)
    upcoming.reverse()  # soonest first; the queryset is newest-first

    # Phase 40.4 — incidents. Ongoing ones show unconditionally; resolved
    # history is capped for the same reason maintenance history is.
    incidents = (page.incidents.filter(is_published=True)
                 .prefetch_related('services', 'updates'))
    ongoing = [i for i in incidents if not i.is_resolved]
    resolved = [i for i in incidents if i.is_resolved][:10]

    return {
        'page': page,
        'rows': rows,
        'overall': page.overall_status(),
        'ongoing_incidents': ongoing,
        'resolved_incidents': resolved,
        'active_maintenance': active,
        'upcoming_maintenance': upcoming,
        'recent_maintenance': recent,
        'generated_at': timezone.now(),
    }


def _render_page(request, page):
    response = render(request, 'statuspage/public.html', _page_context(page))
    # A page naming a client's services has no business in a shared cache or a
    # search index — true of the portal one as well, which is if anything more
    # sensitive for being scoped to one client.
    response['Cache-Control'] = 'no-store, private'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def portal_status(request):
    """Phase 40.5 (v3.17.543): the status page for a signed-in client user.

    Wrapped in the portal's own `portal_required`, so it inherits the portal's
    rules exactly: PSA must be on, the user must hold an active membership in a
    portal-enabled org, and superusers get nothing special — the portal is for
    clients.
    """
    page = StatusPage.for_portal_user(request.portal_membership.organization)
    if page is None:
        raise Http404('No status page is published for your organization')
    return _render_page(request, page)


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------

@login_required
@require_admin
def page_list(request):
    pages = (StatusPage.objects
             .select_related('organization')
             .prefetch_related('services')
             .order_by('-is_enabled', 'title'))
    return render(request, 'statuspage/list.html', {'pages': pages})


@login_required
@require_admin
def page_create(request):
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()[:120]
        org_id = request.POST.get('organization') or None
        organization = None
        if org_id:
            organization = Organization.objects.filter(pk=org_id).first()
            if organization is None:
                messages.error(request, 'That organization no longer exists.')
                return redirect('statuspage:list')
        page = StatusPage.objects.create(
            title=title,
            organization=organization,
            created_by=request.user,
        )
        messages.success(
            request,
            'Status page created, and disabled. Add the services it should '
            'show, then enable it — an empty page that is live says nothing '
            'useful to whoever opens it.')
        return redirect('statuspage:detail', pk=page.pk)

    return render(request, 'statuspage/create.html', {
        'organizations': Organization.objects.order_by('name'),
    })


@login_required
@require_admin
def page_detail(request, pk):
    page = get_object_or_404(
        StatusPage.objects.select_related('organization'), pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action') or 'save'

        if action == 'rotate':
            page.rotate_token()
            messages.warning(
                request,
                'Link rotated. Anyone holding the old address now gets a 404 '
                'until you send them the new one.')
            return redirect('statuspage:detail', pk=page.pk)

        if action == 'delete':
            page.delete()
            messages.success(request, 'Status page deleted.')
            return redirect('statuspage:list')

        if action == 'add_service':
            return _add_service(request, page)

        if action == 'add_incident':
            return _add_incident(request, page)

        if action == 'add_incident_update':
            return _add_incident_update(request, page)

        if action == 'resolve_incident':
            inc = page.incidents.filter(pk=request.POST.get('incident_id')).first()
            if inc and not inc.is_resolved:
                inc.resolved_at = timezone.now()
                inc.save(update_fields=['resolved_at', 'updated_at'])
                messages.success(request, 'Incident marked resolved.')
            return redirect('statuspage:detail', pk=page.pk)

        if action == 'delete_incident':
            inc = page.incidents.filter(pk=request.POST.get('incident_id')).first()
            if inc:
                inc.delete()
                messages.success(request, 'Incident deleted, updates and all.')
            return redirect('statuspage:detail', pk=page.pk)

        if action == 'add_maintenance':
            return _add_maintenance(request, page)

        if action == 'cancel_maintenance':
            win = page.maintenance_windows.filter(
                pk=request.POST.get('window_id')).first()
            if win:
                win.is_cancelled = True
                win.save(update_fields=['is_cancelled', 'updated_at'])
                messages.success(
                    request,
                    'Marked as cancelled. It stays on the page so anyone who '
                    'read the original notice can see it is off.')
            return redirect('statuspage:detail', pk=page.pk)

        if action == 'delete_maintenance':
            win = page.maintenance_windows.filter(
                pk=request.POST.get('window_id')).first()
            if win:
                win.delete()
                messages.success(request, 'Maintenance window deleted.')
            return redirect('statuspage:detail', pk=page.pk)

        if action == 'remove_service':
            svc = page.services.filter(pk=request.POST.get('service_id')).first()
            if svc:
                name = svc.display_name
                svc.delete()
                messages.success(request, f'Removed "{name}" from the page.')
            return redirect('statuspage:detail', pk=page.pk)

        # Plain save
        page.is_enabled = request.POST.get('is_enabled') == 'on'
        page.title = (request.POST.get('title') or '').strip()[:120]
        page.intro = (request.POST.get('intro') or '').strip()
        visibility = request.POST.get('visibility')
        if visibility in dict(StatusPage.VISIBILITY_CHOICES):
            page.visibility = visibility
        page.show_uptime = request.POST.get('show_uptime') == 'on'
        page.show_response_time = request.POST.get('show_response_time') == 'on'
        try:
            page.refresh_seconds = int(request.POST.get('refresh_seconds') or 120)
        except (TypeError, ValueError):
            page.refresh_seconds = 120
        page.save()

        if page.is_enabled and page.is_public:
            messages.success(
                request,
                'Status page is live. Anyone with the link can read it without '
                'signing in.')
        elif page.is_enabled:
            messages.success(
                request,
                'Status page is live in the client portal. The public link does '
                'not work while it is portal-only.')
        else:
            messages.success(request, 'Status page disabled. The link now 404s.')
        return redirect('statuspage:detail', pk=page.pk)

    # Monitors this page could still add. Scoped to the page's organization
    # when it has one, so a client page cannot accidentally publish another
    # client's service.
    already = page.services.values_list('monitor_id', flat=True)
    available = WebsiteMonitor.objects.exclude(id__in=already)
    if page.organization_id:
        available = available.filter(organization_id=page.organization_id)

    return render(request, 'statuspage/detail.html', {
        'page': page,
        'services': page.services.select_related('monitor').all(),
        'maintenance_windows': page.maintenance_windows.prefetch_related('services').all(),
        'incidents': page.incidents.prefetch_related('services', 'updates').all(),
        'flagged_tickets': _publishable_tickets(page),
        'available_monitors': available.select_related('organization').order_by('name'),
        'public_url': request.build_absolute_uri(page.get_public_url()),
    })


def _add_service(request, page):
    monitor_id = request.POST.get('monitor')
    monitor = WebsiteMonitor.objects.filter(pk=monitor_id).first()
    if monitor is None:
        messages.error(request, 'That monitor no longer exists.')
        return redirect('statuspage:detail', pk=page.pk)

    # A page scoped to one client must not publish another client's service.
    if page.organization_id and monitor.organization_id != page.organization_id:
        messages.error(
            request,
            'That monitor belongs to a different client. A client status page '
            'can only show that client\'s services.')
        return redirect('statuspage:detail', pk=page.pk)

    display_name = (request.POST.get('display_name') or '').strip()[:120]
    if not display_name:
        # Falling back to the monitor's internal name would leak exactly what
        # display_name exists to avoid, so refuse instead.
        messages.error(
            request,
            'Give the service a public name. The monitor\'s own name is '
            'internal and is never shown on a status page.')
        return redirect('statuspage:detail', pk=page.pk)

    if page.services.filter(monitor=monitor).exists():
        messages.info(request, 'That service is already on this page.')
        return redirect('statuspage:detail', pk=page.pk)

    StatusPageService.objects.create(
        page=page,
        monitor=monitor,
        display_name=display_name,
        description=(request.POST.get('description') or '').strip()[:255],
        sort_order=page.services.count(),
    )
    messages.success(request, f'Added "{display_name}".')
    return redirect('statuspage:detail', pk=page.pk)


def _add_maintenance(request, page):
    """Phase 40.3 — post a maintenance window."""
    from django.utils.dateparse import parse_datetime

    title = (request.POST.get('title') or '').strip()[:160]
    if not title:
        messages.error(request, 'Give the maintenance a title.')
        return redirect('statuspage:detail', pk=page.pk)

    starts_at = parse_datetime(request.POST.get('starts_at') or '')
    ends_at = parse_datetime(request.POST.get('ends_at') or '')
    if not starts_at or not ends_at:
        messages.error(request, 'Both a start and an end time are required.')
        return redirect('statuspage:detail', pk=page.pk)

    # datetime-local posts naive values; interpret them in the server's zone
    # rather than storing something ambiguous.
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at)
    if timezone.is_naive(ends_at):
        ends_at = timezone.make_aware(ends_at)

    if ends_at <= starts_at:
        messages.error(request, 'Maintenance must end after it starts.')
        return redirect('statuspage:detail', pk=page.pk)

    window = MaintenanceWindow.objects.create(
        page=page,
        title=title,
        body=(request.POST.get('body') or '').strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        created_by=request.user,
    )

    # Empty selection means "everything", which is left as no rows rather than
    # every row — otherwise the set goes stale the moment a service is added.
    service_ids = request.POST.getlist('services')
    if service_ids:
        window.services.set(page.services.filter(pk__in=service_ids))

    messages.success(
        request,
        'Maintenance posted. It is visible on the page now, not just when it '
        'starts — which is the point of announcing it.')
    return redirect('statuspage:detail', pk=page.pk)


# ---------------------------------------------------------------------------
# Phase 40.4 — incidents
# ---------------------------------------------------------------------------

def _publishable_tickets(page):
    """Tickets flagged `is_status_page` that this page could publish.

    Scoped to the page's client when it has one — the same rule the service
    picker follows, for the same reason.
    """
    from psa.models import Ticket

    qs = Ticket.objects.filter(is_status_page=True)
    if page.organization_id:
        qs = qs.filter(organization_id=page.organization_id)
    already = page.incidents.exclude(ticket=None).values_list('ticket_id', flat=True)
    return qs.exclude(id__in=already).order_by('-created_at')[:50]


def _add_incident(request, page):
    from django.utils.dateparse import parse_datetime
    from psa.models import Ticket

    title = (request.POST.get('title') or '').strip()[:200]
    if not title:
        # Falling back to the ticket subject is exactly the leak this model
        # exists to prevent, so refuse instead.
        messages.error(
            request,
            'Give the incident a public title. A ticket subject is written for '
            'the queue and is never published as-is.')
        return redirect('statuspage:detail', pk=page.pk)

    started_at = parse_datetime(request.POST.get('started_at') or '')
    if started_at is None:
        started_at = timezone.now()
    elif timezone.is_naive(started_at):
        started_at = timezone.make_aware(started_at)

    ticket = None
    ticket_id = request.POST.get('ticket')
    if ticket_id:
        ticket = Ticket.objects.filter(pk=ticket_id).first()
        if ticket is None:
            messages.error(request, 'That ticket no longer exists.')
            return redirect('statuspage:detail', pk=page.pk)
        if page.organization_id and ticket.organization_id != page.organization_id:
            messages.error(
                request,
                "That ticket belongs to a different client. A client status "
                "page can only publish that client's incidents.")
            return redirect('statuspage:detail', pk=page.pk)

    incident = StatusPageIncident.objects.create(
        page=page, ticket=ticket, title=title,
        started_at=started_at,
        created_by=request.user,
    )
    service_ids = request.POST.getlist('services')
    if service_ids:
        incident.services.set(page.services.filter(pk__in=service_ids))

    body = (request.POST.get('first_update') or '').strip()
    if body:
        IncidentUpdate.objects.create(
            incident=incident, stage='investigating',
            body=body, posted_by=request.user)

    messages.success(request, 'Incident published.')
    return redirect('statuspage:detail', pk=page.pk)


def _add_incident_update(request, page):
    incident = page.incidents.filter(pk=request.POST.get('incident_id')).first()
    if incident is None:
        messages.error(request, 'That incident is not on this page.')
        return redirect('statuspage:detail', pk=page.pk)

    body = (request.POST.get('body') or '').strip()
    if not body:
        messages.error(request, 'An update needs something to say.')
        return redirect('statuspage:detail', pk=page.pk)

    stage = request.POST.get('stage') or 'investigating'
    valid = dict(IncidentUpdate.STAGES)
    if stage not in valid:
        stage = 'investigating'

    IncidentUpdate.objects.create(
        incident=incident, stage=stage, body=body, posted_by=request.user)

    # Posting a "resolved" update and then having to separately mark the
    # incident resolved is a step everyone forgets, so do it here.
    if stage == 'resolved' and not incident.is_resolved:
        incident.resolved_at = timezone.now()
        incident.save(update_fields=['resolved_at', 'updated_at'])

    root_cause = (request.POST.get('root_cause') or '').strip()
    if root_cause:
        incident.root_cause = root_cause
        incident.save(update_fields=['root_cause', 'updated_at'])

    messages.success(request, 'Update posted.')
    return redirect('statuspage:detail', pk=page.pk)
