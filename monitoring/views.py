"""
Monitoring views - Website monitoring, Racks, IPAM
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from core.middleware import get_request_organization
from core.decorators import require_write, require_organization_context
from .models import WebsiteMonitor, Expiration, Rack, RackDevice, Subnet, IPAddress
from .forms import (
    WebsiteMonitorForm, ExpirationForm, RackForm, RackDeviceForm,
    SubnetForm, IPAddressForm
)


# ============================================================================
# Website Monitoring
# ============================================================================

@login_required
def website_monitor_list(request):
    """List all website monitors in current organization or all monitors in global view."""
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: show all monitors across all organizations
        monitors = WebsiteMonitor.objects.all().select_related('organization')
    else:
        # Organization view: show only monitors for current org
        monitors = WebsiteMonitor.objects.filter(organization=org)

    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        monitors = monitors.filter(status=status_filter)

    # Search
    query = request.GET.get('q')
    if query:
        monitors = monitors.filter(
            Q(url__icontains=query) |
            Q(description__icontains=query)
        )

    return render(request, 'monitoring/website_monitor_list.html', {
        'monitors': monitors,
        'status_filter': status_filter,
        'query': query,
        'in_global_view': in_global_view,
    })


@login_required
@require_write
@require_organization_context
def website_monitor_create(request):
    """Create website monitor."""
    org = get_request_organization(request)

    if request.method == 'POST':
        form = WebsiteMonitorForm(request.POST, organization=org)
        if form.is_valid():
            monitor = form.save(commit=False)
            monitor.organization = org
            monitor.save()
            messages.success(request, f'Website monitor "{monitor.url}" created.')
            return redirect('monitoring:website_monitor_detail', pk=monitor.pk)
    else:
        form = WebsiteMonitorForm(organization=org)

    return render(request, 'monitoring/website_monitor_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def website_monitor_detail(request, pk):
    """
    View website monitor details.
    Supports global view mode for superusers/staff users.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: access monitor from any organization
        monitor = get_object_or_404(WebsiteMonitor, pk=pk)
    else:
        # Organization view: filter by current org
        monitor = get_object_or_404(WebsiteMonitor, pk=pk, organization=org)

    return render(request, 'monitoring/website_monitor_detail.html', {
        'monitor': monitor,
        'in_global_view': in_global_view,
    })


@login_required
@require_write
def website_monitor_edit(request, pk):
    """Edit website monitor."""
    org = get_request_organization(request)
    monitor = get_object_or_404(WebsiteMonitor, pk=pk, organization=org)

    if request.method == 'POST':
        form = WebsiteMonitorForm(request.POST, instance=monitor, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Website monitor "{monitor.url}" updated.')
            return redirect('monitoring:website_monitor_detail', pk=monitor.pk)
    else:
        form = WebsiteMonitorForm(instance=monitor, organization=org)

    return render(request, 'monitoring/website_monitor_form.html', {
        'form': form,
        'monitor': monitor,
        'action': 'Edit',
    })


@login_required
@require_write
def website_monitor_delete(request, pk):
    """Delete website monitor."""
    org = get_request_organization(request)
    monitor = get_object_or_404(WebsiteMonitor, pk=pk, organization=org)

    if request.method == 'POST':
        url = monitor.url
        monitor.delete()
        messages.success(request, f'Website monitor "{url}" deleted.')
        return redirect('monitoring:website_monitor_list')

    return render(request, 'monitoring/website_monitor_confirm_delete.html', {
        'monitor': monitor,
    })


@login_required
@require_write
def website_monitor_check(request, pk):
    """Manually trigger website check."""
    org = get_request_organization(request)
    monitor = get_object_or_404(WebsiteMonitor, pk=pk, organization=org)

    try:
        monitor.check_status()
        messages.success(request, f'Website "{monitor.url}" checked successfully.')
    except Exception as e:
        messages.error(request, f'Error checking website: {str(e)}')

    return redirect('monitoring:website_monitor_detail', pk=monitor.pk)


# ============================================================================
# Expirations
# ============================================================================

@login_required
def expiration_list(request):
    """List all expirations."""
    org = get_request_organization(request)
    expirations = Expiration.objects.filter(organization=org).order_by('expires_at')

    return render(request, 'monitoring/expiration_list.html', {
        'expirations': expirations,
    })


@login_required
@require_write
def expiration_create(request):
    """Create expiration."""
    org = get_request_organization(request)

    # Require organization context for creating expirations
    if not org:
        messages.error(request, 'Organization context required to create expirations.')
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        form = ExpirationForm(request.POST, organization=org)
        if form.is_valid():
            expiration = form.save(commit=False)
            expiration.organization = org
            expiration.save()
            messages.success(request, f'Expiration "{expiration.title}" created.')
            return redirect('monitoring:expiration_list')
    else:
        form = ExpirationForm(organization=org)

    return render(request, 'monitoring/expiration_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def expiration_edit(request, pk):
    """Edit expiration."""
    org = get_request_organization(request)
    expiration = get_object_or_404(Expiration, pk=pk, organization=org)

    if request.method == 'POST':
        form = ExpirationForm(request.POST, instance=expiration, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Expiration "{expiration.title}" updated.')
            return redirect('monitoring:expiration_list')
    else:
        form = ExpirationForm(instance=expiration, organization=org)

    return render(request, 'monitoring/expiration_form.html', {
        'form': form,
        'expiration': expiration,
        'action': 'Edit',
    })


@login_required
@require_write
def expiration_delete(request, pk):
    """Delete expiration."""
    org = get_request_organization(request)
    expiration = get_object_or_404(Expiration, pk=pk, organization=org)

    if request.method == 'POST':
        title = expiration.title
        expiration.delete()
        messages.success(request, f'Expiration "{title}" deleted.')
        return redirect('monitoring:expiration_list')

    return render(request, 'monitoring/expiration_confirm_delete.html', {
        'expiration': expiration,
    })


# ============================================================================
# Rack Management
# ============================================================================

@login_required
def rack_list(request):
    """List all racks."""
    org = get_request_organization(request)
    racks = Rack.objects.filter(organization=org)

    return render(request, 'monitoring/rack_list.html', {
        'racks': racks,
    })


@login_required
@require_write
def rack_create(request):
    """Create rack."""
    org = get_request_organization(request)

    # Require organization context for creating racks
    if not org:
        messages.error(request, 'Organization context required to create racks.')
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        form = RackForm(request.POST, organization=org)
        if form.is_valid():
            rack = form.save(commit=False)
            rack.organization = org
            rack.save()
            messages.success(request, f'Rack "{rack.name}" created.')
            return redirect('monitoring:rack_detail', pk=rack.pk)
        else:
            # Log form errors for debugging
            import logging
            logger = logging.getLogger('monitoring')
            logger.error(f"Rack form validation failed: {form.errors}")
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RackForm(organization=org)

    return render(request, 'monitoring/rack_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def rack_detail(request, pk):
    """View rack details with visual layout."""
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=pk, organization=org)

    # Get devices ordered by position
    devices = rack.rack_devices.all().order_by('start_unit')

    # Create rack layout (list of units)
    rack_units = []
    for unit_num in range(rack.units, 0, -1):  # Top to bottom
        # Find device that occupies this unit (can't use database filter on property)
        device = None
        for d in devices:
            if d.start_unit <= unit_num <= d.end_unit:
                device = d
                break

        rack_units.append({
            'number': unit_num,
            'device': device,
            'is_start': device and device.start_unit == unit_num if device else False,
        })

    # Query rack images
    from files.models import Attachment
    rack_images = Attachment.objects.filter(
        organization=org,
        entity_type='rack',
        entity_id=rack.id,
        content_type__startswith='image/'
    ).order_by('-created_at')

    return render(request, 'monitoring/rack_detail.html', {
        'rack': rack,
        'devices': devices,
        'rack_units': rack_units,
        'rack_images': rack_images,
    })


@login_required
@require_write
def rack_edit(request, pk):
    """Edit rack."""
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=pk, organization=org)

    if request.method == 'POST':
        form = RackForm(request.POST, instance=rack, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Rack "{rack.name}" updated.')
            return redirect('monitoring:rack_detail', pk=rack.pk)
    else:
        form = RackForm(instance=rack, organization=org)

    return render(request, 'monitoring/rack_form.html', {
        'form': form,
        'rack': rack,
        'action': 'Edit',
    })


@login_required
@require_write
def rack_delete(request, pk):
    """Delete rack."""
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=pk, organization=org)

    if request.method == 'POST':
        name = rack.name
        rack.delete()
        messages.success(request, f'Rack "{name}" deleted.')
        return redirect('monitoring:rack_list')

    return render(request, 'monitoring/rack_confirm_delete.html', {
        'rack': rack,
    })


@login_required
@require_write
def rack_device_create(request, rack_id):
    """Add asset to rack."""
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=rack_id, organization=org)

    if request.method == 'POST':
        form = RackDeviceForm(request.POST, request.FILES, rack=rack, organization=org)
        if form.is_valid():
            device = form.save(commit=False)
            device.rack = rack
            device.save()
            messages.success(request, f'Asset "{device.name}" added to rack.')
            return redirect('monitoring:rack_detail', pk=rack.pk)
    else:
        # Pre-populate start_unit if passed via query parameter
        initial_data = {}
        start_unit = request.GET.get('start_unit')
        if start_unit:
            try:
                initial_data['start_unit'] = int(start_unit)
            except (ValueError, TypeError):
                pass

        form = RackDeviceForm(rack=rack, organization=org, initial=initial_data)

    return render(request, 'monitoring/rack_device_form.html', {
        'form': form,
        'rack': rack,
        'action': 'Add',
    })


@login_required
@require_write
def rack_device_edit(request, pk):
    """Edit rack asset."""
    device = get_object_or_404(RackDevice, pk=pk)
    org = get_request_organization(request)

    if device.rack.organization != org:
        messages.error(request, 'Asset not found.')
        return redirect('monitoring:rack_list')

    if request.method == 'POST':
        form = RackDeviceForm(request.POST, request.FILES, instance=device, rack=device.rack, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Asset "{device.name}" updated.')
            return redirect('monitoring:rack_detail', pk=device.rack.pk)
    else:
        form = RackDeviceForm(instance=device, rack=device.rack, organization=org)

    return render(request, 'monitoring/rack_device_form.html', {
        'form': form,
        'device': device,
        'rack': device.rack,
        'action': 'Edit',
    })


@login_required
@require_write
def rack_device_delete(request, pk):
    """Delete rack device."""
    device = get_object_or_404(RackDevice, pk=pk)
    org = get_request_organization(request)

    if device.rack.organization != org:
        messages.error(request, 'Device not found.')
        return redirect('monitoring:rack_list')

    rack = device.rack

    if request.method == 'POST':
        name = device.name
        device.delete()
        messages.success(request, f'Device "{name}" removed from rack.')
        return redirect('monitoring:rack_detail', pk=rack.pk)

    return render(request, 'monitoring/rack_device_confirm_delete.html', {
        'device': device,
        'rack': rack,
    })


# ============================================================================
# IPAM - IP Address Management
# ============================================================================

@login_required
def subnet_list(request):
    """List all subnets."""
    org = get_request_organization(request)
    subnets = Subnet.objects.filter(organization=org)

    return render(request, 'monitoring/subnet_list.html', {
        'subnets': subnets,
    })


@login_required
@require_write
def subnet_create(request):
    """Create subnet."""
    org = get_request_organization(request)

    # Require organization context for creating subnets
    if not org:
        messages.error(request, 'Organization context required to create subnets.')
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        form = SubnetForm(request.POST, organization=org)
        if form.is_valid():
            subnet = form.save(commit=False)
            subnet.organization = org
            subnet.save()
            messages.success(request, f'Subnet "{subnet.network}" created.')
            return redirect('monitoring:subnet_detail', pk=subnet.pk)
    else:
        form = SubnetForm(organization=org)

    return render(request, 'monitoring/subnet_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def subnet_detail(request, pk):
    """View subnet details with IP addresses."""
    org = get_request_organization(request)
    subnet = get_object_or_404(Subnet, pk=pk, organization=org)

    # Get IP addresses
    ip_addresses = subnet.ip_addresses.all().order_by('ip_address')

    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        ip_addresses = ip_addresses.filter(status=status_filter)

    return render(request, 'monitoring/subnet_detail.html', {
        'subnet': subnet,
        'ip_addresses': ip_addresses,
        'status_filter': status_filter,
    })


@login_required
@require_write
def subnet_edit(request, pk):
    """Edit subnet."""
    org = get_request_organization(request)
    subnet = get_object_or_404(Subnet, pk=pk, organization=org)

    if request.method == 'POST':
        form = SubnetForm(request.POST, instance=subnet, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Subnet "{subnet.network}" updated.')
            return redirect('monitoring:subnet_detail', pk=subnet.pk)
    else:
        form = SubnetForm(instance=subnet, organization=org)

    return render(request, 'monitoring/subnet_form.html', {
        'form': form,
        'subnet': subnet,
        'action': 'Edit',
    })


@login_required
@require_write
def subnet_delete(request, pk):
    """Delete subnet."""
    org = get_request_organization(request)
    subnet = get_object_or_404(Subnet, pk=pk, organization=org)

    if request.method == 'POST':
        network = subnet.network
        subnet.delete()
        messages.success(request, f'Subnet "{network}" deleted.')
        return redirect('monitoring:subnet_list')

    return render(request, 'monitoring/subnet_confirm_delete.html', {
        'subnet': subnet,
    })


@login_required
@require_write
def ip_address_create(request, subnet_id):
    """Add IP address to subnet."""
    org = get_request_organization(request)
    subnet = get_object_or_404(Subnet, pk=subnet_id, organization=org)

    if request.method == 'POST':
        form = IPAddressForm(request.POST, subnet=subnet, organization=org)
        if form.is_valid():
            ip = form.save(commit=False)
            ip.subnet = subnet
            ip.save()
            messages.success(request, f'IP address "{ip.ip_address}" added.')
            return redirect('monitoring:subnet_detail', pk=subnet.pk)
    else:
        form = IPAddressForm(subnet=subnet, organization=org)

    return render(request, 'monitoring/ip_address_form.html', {
        'form': form,
        'subnet': subnet,
        'action': 'Add',
    })


@login_required
@require_write
def ip_address_edit(request, pk):
    """Edit IP address."""
    ip_address = get_object_or_404(IPAddress, pk=pk)
    org = get_request_organization(request)

    if ip_address.subnet.organization != org:
        messages.error(request, 'IP address not found.')
        return redirect('monitoring:subnet_list')

    if request.method == 'POST':
        form = IPAddressForm(request.POST, instance=ip_address, subnet=ip_address.subnet, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'IP address "{ip_address.ip_address}" updated.')
            return redirect('monitoring:subnet_detail', pk=ip_address.subnet.pk)
    else:
        form = IPAddressForm(instance=ip_address, subnet=ip_address.subnet, organization=org)

    return render(request, 'monitoring/ip_address_form.html', {
        'form': form,
        'ip_address': ip_address,
        'subnet': ip_address.subnet,
        'action': 'Edit',
    })


@login_required
@require_write
def ip_address_delete(request, pk):
    """Delete IP address."""
    ip_address = get_object_or_404(IPAddress, pk=pk)
    org = get_request_organization(request)

    if ip_address.subnet.organization != org:
        messages.error(request, 'IP address not found.')
        return redirect('monitoring:subnet_list')

    subnet = ip_address.subnet

    if request.method == 'POST':
        ip = ip_address.ip_address
        ip_address.delete()
        messages.success(request, f'IP address "{ip}" deleted.')
        return redirect('monitoring:subnet_detail', pk=subnet.pk)

    return render(request, 'monitoring/ip_address_confirm_delete.html', {
        'ip_address': ip_address,
        'subnet': subnet,
    })


# ============================================================================
# Network Closets (Filtered Rack Views)
# ============================================================================

@login_required
def network_closet_list(request):
    """List all network closets and data closets."""
    org = get_request_organization(request)
    closets = Rack.objects.filter(
        organization=org,
        rack_type__in=['network_closet', 'data_closet']
    )

    # Search
    query = request.GET.get('q')
    if query:
        closets = closets.filter(
            Q(name__icontains=query) |
            Q(building__icontains=query) |
            Q(floor__icontains=query) |
            Q(room__icontains=query) |
            Q(location__icontains=query)
        )

    return render(request, 'monitoring/network_closet_list.html', {
        'closets': closets,
        'query': query,
    })


@login_required
@require_write
def network_closet_create(request):
    """Create network closet."""
    org = get_request_organization(request)

    # Require organization context for creating network closets
    if not org:
        messages.error(request, 'Organization context required to create network closets.')
        return redirect('accounts:organization_list')

    if request.method == 'POST':
        form = RackForm(request.POST, organization=org)
        if form.is_valid():
            closet = form.save(commit=False)
            closet.organization = org
            # Default to network_closet if not specified
            if closet.rack_type not in ['network_closet', 'data_closet']:
                closet.rack_type = 'network_closet'
            closet.save()
            messages.success(request, f'Network closet "{closet.name}" created.')
            return redirect('monitoring:network_closet_detail', pk=closet.pk)
        else:
            # Log form errors for debugging
            import logging
            logger = logging.getLogger('monitoring')
            logger.error(f"Network closet form validation failed: {form.errors}")
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-populate form with network_closet type
        form = RackForm(organization=org, initial={'rack_type': 'network_closet'})

    return render(request, 'monitoring/network_closet_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def network_closet_detail(request, pk):
    """View network closet details."""
    org = get_request_organization(request)
    closet = get_object_or_404(
        Rack,
        pk=pk,
        organization=org,
        rack_type__in=['network_closet', 'data_closet']
    )

    # Get devices in this closet
    devices = RackDevice.objects.filter(rack=closet).order_by('start_unit')

    # Build unit map for visual representation
    unit_map = {}
    for u in range(1, closet.units + 1):
        unit_map[u] = None

    # Map devices to their units
    for device in devices:
        for u in range(device.start_unit, device.end_unit + 1):
            unit_map[u] = device

    return render(request, 'monitoring/network_closet_detail.html', {
        'closet': closet,
        'devices': devices,
        'unit_map': unit_map,
    })


@login_required
@require_write
def network_closet_edit(request, pk):
    """Edit network closet."""
    org = get_request_organization(request)
    closet = get_object_or_404(
        Rack,
        pk=pk,
        organization=org,
        rack_type__in=['network_closet', 'data_closet']
    )

    if request.method == 'POST':
        form = RackForm(request.POST, instance=closet, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Network closet "{closet.name}" updated.')
            return redirect('monitoring:network_closet_detail', pk=closet.pk)
    else:
        form = RackForm(instance=closet, organization=org)

    return render(request, 'monitoring/network_closet_form.html', {
        'form': form,
        'closet': closet,
        'action': 'Edit',
    })


@login_required
@require_write
def network_closet_delete(request, pk):
    """Delete network closet."""
    org = get_request_organization(request)
    closet = get_object_or_404(
        Rack,
        pk=pk,
        organization=org,
        rack_type__in=['network_closet', 'data_closet']
    )

    if request.method == 'POST':
        name = closet.name
        closet.delete()
        messages.success(request, f'Network closet "{name}" deleted.')
        return redirect('monitoring:network_closet_list')

    return render(request, 'monitoring/network_closet_confirm_delete.html', {
        'closet': closet,
    })


# ============================================================================
# WAN Connection Monitoring
# ============================================================================

@login_required
def wan_monitor_list(request):
    """List all WAN connections with monitoring enabled."""
    from locations.models import WAN

    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: show all monitored WANs across all organizations
        wans = WAN.objects.filter(monitoring_enabled=True).select_related(
            'organization', 'location'
        ).order_by('organization__name', 'location__name', 'name')
    else:
        # Organization view: show only monitored WANs for current org
        wans = WAN.objects.filter(
            organization=org,
            monitoring_enabled=True
        ).select_related('location').order_by('location__name', 'name')

    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        wans = wans.filter(connection_status=status_filter)

    # Filter by location
    location_filter = request.GET.get('location')
    if location_filter:
        wans = wans.filter(location_id=location_filter)

    # Search
    query = request.GET.get('q')
    if query:
        wans = wans.filter(
            Q(name__icontains=query) |
            Q(isp_name__icontains=query) |
            Q(location__name__icontains=query)
        )

    # Get all locations for filter dropdown
    if in_global_view:
        from locations.models import Location
        locations = Location.objects.all().order_by('organization__name', 'name')
    else:
        locations = org.locations.all().order_by('name') if org else []

    return render(request, 'monitoring/wan_monitor_list.html', {
        'wans': wans,
        'query': query,
        'status_filter': status_filter,
        'location_filter': location_filter,
        'locations': locations,
        'in_global_view': in_global_view,
    })
