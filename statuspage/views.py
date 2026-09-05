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

from .models import MaintenanceWindow, StatusPage, StatusPageService


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def public(request, token):
    """The status page itself. No authentication — that is the point.

    A disabled or unknown token 404s identically. Distinguishing them would
    confirm to anyone probing that a page exists at that address.
    """
    page = StatusPage.objects.filter(token=token, is_enabled=True).first()
    if page is None:
        raise Http404('No status page here')

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

    response = render(request, 'statuspage/public.html', {
        'page': page,
        'rows': rows,
        'overall': page.overall_status(),
        'active_maintenance': active,
        'upcoming_maintenance': upcoming,
        'recent_maintenance': recent,
        'generated_at': timezone.now(),
    })
    # An unauthenticated page naming a client's services has no business in a
    # shared cache or a search index.
    response['Cache-Control'] = 'no-store, private'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


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
        page.show_uptime = request.POST.get('show_uptime') == 'on'
        page.show_response_time = request.POST.get('show_response_time') == 'on'
        try:
            page.refresh_seconds = int(request.POST.get('refresh_seconds') or 120)
        except (TypeError, ValueError):
            page.refresh_seconds = 120
        page.save()

        if page.is_enabled:
            messages.success(
                request,
                'Status page is live. Anyone with the link can read it without '
                'signing in.')
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
