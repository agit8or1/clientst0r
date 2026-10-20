"""
WAN connection views for locations
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import WAN, Location
from .forms import WANForm


@login_required
def wan_list(request, location_id):
    """List all WAN connections for a location."""
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = hasattr(request, 'is_staff_user') and request.is_staff_user
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        location = get_object_or_404(Location, id=location_id)
    else:
        location = get_object_or_404(
            Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)),
            id=location_id
        )

    wan_connections = location.wan_connections.all().order_by('-is_primary', 'name')

    return render(request, 'locations/wan_list.html', {
        'location': location,
        'wan_connections': wan_connections,
        'current_organization': org,
        'in_global_view': in_global_view,
    })


@login_required
def wan_detail(request, location_id, wan_id):
    """View WAN connection details."""
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = hasattr(request, 'is_staff_user') and request.is_staff_user
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        location = get_object_or_404(Location, id=location_id)
        wan = get_object_or_404(WAN, id=wan_id, location=location)
    else:
        location = get_object_or_404(
            Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)),
            id=location_id
        )
        wan = get_object_or_404(WAN, id=wan_id, location=location, organization=org)

    return render(request, 'locations/wan_detail.html', {
        'location': location,
        'wan': wan,
        'current_organization': org,
        'in_global_view': in_global_view,
    })


@login_required
@require_write
def wan_create(request, location_id):
    """Create a new WAN connection for a location."""
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = hasattr(request, 'is_staff_user') and request.is_staff_user
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        location = get_object_or_404(Location, id=location_id)
        effective_org = location.organization
    else:
        location = get_object_or_404(
            Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)),
            id=location_id
        )
        effective_org = org

    if request.method == 'POST':
        form = WANForm(request.POST, organization=effective_org, location=location)
        if form.is_valid():
            wan = form.save(commit=False)
            wan.location = location
            wan.organization = effective_org
            wan.created_by = request.user
            wan.save()

            messages.success(request, f"WAN connection '{wan.name}' created successfully.")
            return redirect('locations:location_detail', location_id=location.id)
    else:
        form = WANForm(organization=effective_org, location=location)

    return render(request, 'locations/wan_form.html', {
        'form': form,
        'location': location,
        'current_organization': org,
        'action': 'Create',
    })


@login_required
@require_write
def wan_edit(request, location_id, wan_id):
    """Edit a WAN connection."""
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = hasattr(request, 'is_staff_user') and request.is_staff_user
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        location = get_object_or_404(Location, id=location_id)
        wan = get_object_or_404(WAN, id=wan_id, location=location)
    else:
        location = get_object_or_404(
            Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)),
            id=location_id
        )
        wan = get_object_or_404(WAN, id=wan_id, location=location, organization=org)

    if request.method == 'POST':
        form = WANForm(request.POST, instance=wan, organization=org, location=location)
        if form.is_valid():
            wan = form.save()
            messages.success(request, f"WAN connection '{wan.name}' updated successfully.")
            return redirect('locations:wan_detail', location_id=location.id, wan_id=wan.id)
    else:
        form = WANForm(instance=wan, organization=org, location=location)

    return render(request, 'locations/wan_form.html', {
        'form': form,
        'location': location,
        'wan': wan,
        'current_organization': org,
        'action': 'Edit',
    })


@login_required
@require_write
def wan_delete(request, location_id, wan_id):
    """Delete a WAN connection."""
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = hasattr(request, 'is_staff_user') and request.is_staff_user
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        location = get_object_or_404(Location, id=location_id)
        wan = get_object_or_404(WAN, id=wan_id, location=location)
    else:
        location = get_object_or_404(
            Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)),
            id=location_id
        )
        wan = get_object_or_404(WAN, id=wan_id, location=location, organization=org)

    if request.method == 'POST':
        wan_name = wan.name
        wan.delete()
        messages.success(request, f"WAN connection '{wan_name}' deleted successfully.")
        return redirect('locations:location_detail', location_id=location.id)

    return render(request, 'locations/wan_confirm_delete.html', {
        'location': location,
        'wan': wan,
        'current_organization': org,
    })


@login_required
def wan_check_status(request, location_id, wan_id):
    """Manually check WAN status."""
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = hasattr(request, 'is_staff_user') and request.is_staff_user
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        location = get_object_or_404(Location, id=location_id)
        wan = get_object_or_404(WAN, id=wan_id, location=location)
    else:
        location = get_object_or_404(
            Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)),
            id=location_id
        )
        wan = get_object_or_404(WAN, id=wan_id, location=location, organization=org)

    if not wan.monitoring_enabled:
        messages.warning(request, "Monitoring is not enabled for this WAN connection.")
    elif not wan.monitor_target:
        messages.warning(request, "No monitor target configured for this WAN connection.")
    else:
        try:
            result = wan.check_status()
        except ValueError:
            messages.error(request, "The monitor target is not a valid IP address or hostname.")
            return redirect('locations:wan_detail', location_id=location.id, wan_id=wan.id)
        if result.result == 'up':
            rtt = f" Response time: {result.response_time_ms} ms." if result.response_time_ms is not None else ''
            messages.success(request, f"The monitor target answered.{rtt}")
        elif result.result == 'down':
            if wan.alert_state == 'down':
                messages.error(request, "No answer. The connection is marked down.")
            elif wan.status in wan.MANUAL_STATUSES:
                messages.warning(request, f"No answer. The status stays {wan.get_status_display()} "
                                          "because it was set by hand.")
            else:
                messages.warning(request, f"No answer ({wan.consecutive_failures} failed check(s) in a row). "
                                          "The connection is marked down after repeated failures.")
        else:
            messages.error(request, f"The check could not run: {result.error}")

    return redirect('locations:wan_detail', location_id=location.id, wan_id=wan.id)
