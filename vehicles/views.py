"""
Views for Service Vehicles
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum, Avg, Max
from django.utils import timezone
from datetime import timedelta

from .models import (
    ServiceVehicle, VehicleInventoryItem, VehicleDamageReport,
    VehicleMaintenanceRecord, VehicleFuelLog, VehicleAssignment
)
from .forms import (
    ServiceVehicleForm, VehicleInventoryItemForm, VehicleDamageReportForm,
    VehicleMaintenanceRecordForm, VehicleFuelLogForm, VehicleAssignmentForm
)


@login_required
def vehicles_dashboard(request):
    """Dashboard overview of fleet"""
    # Base queryset
    vehicles = ServiceVehicle.objects.all()

    # Statistics
    total_vehicles = vehicles.count()
    active_vehicles = vehicles.filter(status='active').count()
    in_maintenance = vehicles.filter(status='maintenance').count()

    # Alerts
    today = timezone.now().date()
    alerts = []

    # Insurance expiring soon
    insurance_expiring = vehicles.filter(
        insurance_expires_at__lte=today + timedelta(days=30),
        insurance_expires_at__gte=today,
        status='active'
    )
    if insurance_expiring.exists():
        alerts.append({
            'type': 'warning',
            'icon': 'fas fa-file-contract',
            'title': 'Insurance Expiring Soon',
            'message': f'{insurance_expiring.count()} vehicle(s) have insurance expiring within 30 days'
        })

    # Registration expiring soon
    registration_expiring = vehicles.filter(
        registration_expires_at__lte=today + timedelta(days=30),
        registration_expires_at__gte=today,
        status='active'
    )
    if registration_expiring.exists():
        alerts.append({
            'type': 'warning',
            'icon': 'fas fa-id-card',
            'title': 'Registration Expiring Soon',
            'message': f'{registration_expiring.count()} vehicle(s) have registration expiring within 30 days'
        })

    # Overdue maintenance
    maintenance_records = VehicleMaintenanceRecord.objects.all()

    overdue_maintenance = [m for m in maintenance_records if m.is_overdue]
    if overdue_maintenance:
        alerts.append({
            'type': 'danger',
            'icon': 'fas fa-wrench',
            'title': 'Overdue Maintenance',
            'message': f'{len(overdue_maintenance)} maintenance task(s) are overdue'
        })

    # Low inventory items
    inventory_items = VehicleInventoryItem.objects.all()

    low_stock = [item for item in inventory_items if item.is_low_stock]
    if low_stock:
        alerts.append({
            'type': 'info',
            'icon': 'fas fa-boxes',
            'title': 'Low Inventory Stock',
            'message': f'{len(low_stock)} item(s) are below minimum quantity'
        })

    # Recent activity
    recent_fuel = VehicleFuelLog.objects.all().order_by('-date')[:5]
    recent_maintenance = VehicleMaintenanceRecord.objects.all().order_by('-service_date')[:5]
    recent_damage = VehicleDamageReport.objects.all().order_by('-incident_date')[:5]

    # Fleet statistics
    total_mileage = vehicles.aggregate(total=Sum('current_mileage'))['total'] or 0
    avg_mileage = vehicles.aggregate(avg=Avg('current_mileage'))['avg'] or 0

    # Fuel statistics (last 30 days)
    thirty_days_ago = today - timedelta(days=30)
    recent_fuel_logs = VehicleFuelLog.objects.filter(date__gte=thirty_days_ago)


    total_fuel_cost = recent_fuel_logs.aggregate(total=Sum('total_cost'))['total'] or 0
    avg_mpg = recent_fuel_logs.aggregate(avg=Avg('mpg'))['avg'] or 0

    # Get list of active vehicles for grid
    active_vehicles_list = vehicles.filter(status='active').select_related('assigned_to').order_by('name')

    context = {
        'total_vehicles': total_vehicles,
        'active_vehicles': active_vehicles,
        'in_maintenance': in_maintenance,
        'alerts': alerts,
        'recent_fuel': recent_fuel,
        'recent_maintenance': recent_maintenance,
        'recent_damage': recent_damage,
        'total_mileage': total_mileage,
        'avg_mileage': avg_mileage,
        'total_fuel_cost': total_fuel_cost,
        'avg_mpg': avg_mpg,
        'active_vehicles_list': active_vehicles_list,
    }

    return render(request, 'vehicles/vehicles_dashboard.html', context)


@login_required
def vehicle_list(request):
    """List all vehicles"""
    # Base queryset
    vehicles = ServiceVehicle.objects.all()

    # Filters
    status_filter = request.GET.get('status')
    if status_filter:
        vehicles = vehicles.filter(status=status_filter)

    condition_filter = request.GET.get('condition')
    if condition_filter:
        vehicles = vehicles.filter(condition=condition_filter)

    assigned_to_filter = request.GET.get('assigned_to')
    if assigned_to_filter:
        vehicles = vehicles.filter(assigned_to_id=assigned_to_filter)

    search = request.GET.get('search')
    if search:
        vehicles = vehicles.filter(
            Q(name__icontains=search) |
            Q(make__icontains=search) |
            Q(model__icontains=search) |
            Q(license_plate__icontains=search) |
            Q(vin__icontains=search)
        )

    vehicles = vehicles.select_related('assigned_to').order_by('name')

    context = {
        'vehicles': vehicles,
        'status_filter': status_filter,
        'condition_filter': condition_filter,
        'assigned_to_filter': assigned_to_filter,
        'search': search    }

    return render(request, 'vehicles/vehicle_list.html', context)


@login_required
def vehicle_detail(request, pk):
    """Vehicle detail view with tabs"""
    vehicle = get_object_or_404(ServiceVehicle, pk=pk)

    # Get related data
    inventory_items = vehicle.inventory_items.all().order_by('category', 'name')
    damage_reports = vehicle.damage_reports.all().order_by('-incident_date')
    maintenance_records = vehicle.maintenance_records.all().order_by('-service_date')
    fuel_logs = vehicle.fuel_logs.all().order_by('-date')
    assignments = vehicle.assignments.all().order_by('-start_date')

    # Statistics
    total_inventory_value = sum([item.total_value for item in inventory_items if item.total_value])
    low_stock_count = sum([1 for item in inventory_items if item.is_low_stock])

    pending_damage = sum([1 for report in damage_reports if report.is_pending_repair])
    total_damage_cost = damage_reports.aggregate(total=Sum('actual_cost'))['total'] or 0

    total_maintenance_cost = maintenance_records.aggregate(total=Sum('total_cost'))['total'] or 0
    overdue_maintenance = sum([1 for record in maintenance_records if record.is_overdue])

    total_fuel_cost = fuel_logs.aggregate(total=Sum('total_cost'))['total'] or 0
    avg_mpg = vehicle.get_recent_fuel_mpg() or 0

    context = {
        'vehicle': vehicle,
        'inventory_items': inventory_items,
        'damage_reports': damage_reports,
        'maintenance_records': maintenance_records,
        'fuel_logs': fuel_logs,
        'assignments': assignments,
        'total_inventory_value': total_inventory_value,
        'low_stock_count': low_stock_count,
        'pending_damage': pending_damage,
        'total_damage_cost': total_damage_cost,
        'total_maintenance_cost': total_maintenance_cost,
        'overdue_maintenance': overdue_maintenance,
        'total_fuel_cost': total_fuel_cost,
        'avg_mpg': avg_mpg
    }

    return render(request, 'vehicles/vehicle_detail.html', context)


@login_required
def vehicle_create(request):
    """Create new vehicle"""
    if request.method == 'POST':
        form = ServiceVehicleForm(request.POST)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.save()

            messages.success(request, f'Vehicle "{vehicle.display_name}" created successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = ServiceVehicleForm()

    return render(request, 'vehicles/vehicle_form.html', {
        'form': form,
        'title': 'Add Vehicle',
        'button_text': 'Create Vehicle'
    })


@login_required
def vehicle_edit(request, pk):
    """Edit vehicle"""
    vehicle = get_object_or_404(ServiceVehicle, pk=pk)

    if request.method == 'POST':
        form = ServiceVehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, f'Vehicle "{vehicle.display_name}" updated successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = ServiceVehicleForm(instance=vehicle)

    return render(request, 'vehicles/vehicle_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': f'Edit {vehicle.display_name}',
        'button_text': 'Save Changes'
    })


@login_required
def vehicle_delete(request, pk):
    """Delete vehicle"""
    vehicle = get_object_or_404(ServiceVehicle, pk=pk)

    if request.method == 'POST':
        vehicle_name = vehicle.display_name
        vehicle.delete()
        messages.success(request, f'Vehicle "{vehicle_name}" deleted successfully.')
        return redirect('vehicles:vehicle_list')

    return render(request, 'vehicles/vehicle_confirm_delete.html', {
        'vehicle': vehicle
    })


# Inventory Item Views

@login_required
def inventory_item_create(request, vehicle_id):
    """Create inventory item for vehicle"""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    if request.method == 'POST':
        form = VehicleInventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.vehicle = vehicle
            item.save()

            messages.success(request, f'Inventory item "{item.name}" added successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleInventoryItemForm()

    return render(request, 'vehicles/inventory_item_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Add Inventory Item',
        'button_text': 'Add Item'
    })


@login_required
def inventory_item_edit(request, pk):
    """Edit inventory item"""
    item = get_object_or_404(VehicleInventoryItem, pk=pk)

    if request.method == 'POST':
        form = VehicleInventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Inventory item "{item.name}" updated successfully.')
            return redirect('vehicles:vehicle_detail', pk=item.vehicle.pk)
    else:
        form = VehicleInventoryItemForm(instance=item)

    return render(request, 'vehicles/inventory_item_form.html', {
        'form': form,
        'vehicle': item.vehicle,
        'item': item,
        'title': f'Edit {item.name}',
        'button_text': 'Save Changes'
    })


@login_required
def inventory_item_delete(request, pk):
    """Delete inventory item"""
    item = get_object_or_404(VehicleInventoryItem, pk=pk)

    vehicle = item.vehicle

    if request.method == 'POST':
        item_name = item.name
        item.delete()
        messages.success(request, f'Inventory item "{item_name}" deleted successfully.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)

    return render(request, 'vehicles/inventory_item_confirm_delete.html', {
        'item': item,
        'vehicle': vehicle
    })


# Damage Report Views

@login_required
def damage_report_create(request, vehicle_id):
    """Create damage report"""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    if request.method == 'POST':
        form = VehicleDamageReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.vehicle = vehicle
            report.save()

            messages.success(request, 'Damage report created successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleDamageReportForm(initial={
            'reported_by': request.user,
            'incident_date': timezone.now().date()
        })

    return render(request, 'vehicles/damage_report_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Report Damage',
        'button_text': 'Create Report'
    })


@login_required
def damage_report_edit(request, pk):
    """Edit damage report"""
    report = get_object_or_404(VehicleDamageReport, pk=pk)

    if request.method == 'POST':
        form = VehicleDamageReportForm(request.POST, instance=report)
        if form.is_valid():
            form.save()
            messages.success(request, 'Damage report updated successfully.')
            return redirect('vehicles:vehicle_detail', pk=report.vehicle.pk)
    else:
        form = VehicleDamageReportForm(instance=report)

    return render(request, 'vehicles/damage_report_form.html', {
        'form': form,
        'vehicle': report.vehicle,
        'report': report,
        'title': 'Edit Damage Report',
        'button_text': 'Save Changes'
    })


@login_required
def damage_report_delete(request, pk):
    """Delete damage report"""
    report = get_object_or_404(VehicleDamageReport, pk=pk)

    vehicle = report.vehicle

    if request.method == 'POST':
        report.delete()
        messages.success(request, 'Damage report deleted successfully.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)

    return render(request, 'vehicles/damage_report_confirm_delete.html', {
        'report': report,
        'vehicle': vehicle
    })


# Maintenance Record Views

@login_required
def maintenance_record_create(request, vehicle_id):
    """Create maintenance record"""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    if request.method == 'POST':
        form = VehicleMaintenanceRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.vehicle = vehicle
            record.save()

            messages.success(request, 'Maintenance record created successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleMaintenanceRecordForm(initial={
            'service_date': timezone.now().date(),
            'mileage_at_service': vehicle.current_mileage
        })

    return render(request, 'vehicles/maintenance_record_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Log Maintenance',
        'button_text': 'Create Record'
    })


@login_required
def maintenance_record_edit(request, pk):
    """Edit maintenance record"""
    record = get_object_or_404(VehicleMaintenanceRecord, pk=pk)

    if request.method == 'POST':
        form = VehicleMaintenanceRecordForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            messages.success(request, 'Maintenance record updated successfully.')
            return redirect('vehicles:vehicle_detail', pk=record.vehicle.pk)
    else:
        form = VehicleMaintenanceRecordForm(instance=record)

    return render(request, 'vehicles/maintenance_record_form.html', {
        'form': form,
        'vehicle': record.vehicle,
        'record': record,
        'title': 'Edit Maintenance Record',
        'button_text': 'Save Changes'
    })


@login_required
def maintenance_record_delete(request, pk):
    """Delete maintenance record"""
    record = get_object_or_404(VehicleMaintenanceRecord, pk=pk)

    vehicle = record.vehicle

    if request.method == 'POST':
        record.delete()
        messages.success(request, 'Maintenance record deleted successfully.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)

    return render(request, 'vehicles/maintenance_record_confirm_delete.html', {
        'record': record,
        'vehicle': vehicle
    })


# Fuel Log Views

@login_required
def fuel_log_create(request, vehicle_id):
    """Create fuel log"""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    if request.method == 'POST':
        form = VehicleFuelLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.vehicle = vehicle
            log.save()

            messages.success(request, 'Fuel log created successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleFuelLogForm(initial={
            'date': timezone.now().date(),
            'mileage': vehicle.current_mileage
        })

    return render(request, 'vehicles/fuel_log_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Log Fuel Purchase',
        'button_text': 'Create Log'
    })


@login_required
def fuel_log_edit(request, pk):
    """Edit fuel log"""
    log = get_object_or_404(VehicleFuelLog, pk=pk)

    if request.method == 'POST':
        form = VehicleFuelLogForm(request.POST, instance=log)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fuel log updated successfully.')
            return redirect('vehicles:vehicle_detail', pk=log.vehicle.pk)
    else:
        form = VehicleFuelLogForm(instance=log)

    return render(request, 'vehicles/fuel_log_form.html', {
        'form': form,
        'vehicle': log.vehicle,
        'log': log,
        'title': 'Edit Fuel Log',
        'button_text': 'Save Changes'
    })


@login_required
def fuel_log_delete(request, pk):
    """Delete fuel log"""
    log = get_object_or_404(VehicleFuelLog, pk=pk)

    vehicle = log.vehicle

    if request.method == 'POST':
        log.delete()
        messages.success(request, 'Fuel log deleted successfully.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)

    return render(request, 'vehicles/fuel_log_confirm_delete.html', {
        'log': log,
        'vehicle': vehicle
    })


# Assignment Views

@login_required
def assignment_create(request, vehicle_id):
    """Create vehicle assignment"""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    if request.method == 'POST':
        form = VehicleAssignmentForm(request.POST, vehicle=vehicle)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.vehicle = vehicle
            assignment.save()

            # Update vehicle's assigned_to field
            vehicle.assigned_to = assignment.user
            vehicle.save()

            messages.success(request, f'Vehicle assigned to {assignment.user.get_full_name()} successfully.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleAssignmentForm(vehicle=vehicle, initial={
            'start_date': timezone.now().date(),
            'starting_mileage': vehicle.current_mileage
        })

    return render(request, 'vehicles/assignment_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Assign Vehicle',
        'button_text': 'Create Assignment'
    })


@login_required
def assignment_end(request, pk):
    """End vehicle assignment"""
    assignment = get_object_or_404(VehicleAssignment, pk=pk)

    if request.method == 'POST':
        ending_mileage = request.POST.get('ending_mileage')

        assignment.end_date = timezone.now().date()
        assignment.ending_mileage = ending_mileage
        assignment.save()

        # Clear vehicle's assigned_to field
        vehicle = assignment.vehicle
        vehicle.assigned_to = None
        vehicle.save()

        messages.success(request, f'Assignment ended successfully.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)

    return render(request, 'vehicles/assignment_end.html', {
        'assignment': assignment,
        'vehicle': assignment.vehicle
    })


# ============================================================================
# QR Code & Mobile Scanner Views
# ============================================================================

@login_required
def inventory_qr_image(request, pk):
    """
    Generate QR code image for inventory item.
    Returns PNG image.
    """
    item = get_object_or_404(VehicleInventoryItem, pk=pk)

    # Check permissions
    if not request.user.is_staff and item.vehicle.organization != request.user.current_organization:
        raise PermissionDenied

    # Generate QR code
    import qrcode
    from io import BytesIO
    from django.http import HttpResponse

    # Generate QR code data (URL to scan page)
    qr_url = request.build_absolute_uri(item.get_qr_code_url())

    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)

    # Create image
    img = qr.make_image(fill_color="black", back_color="white")

    # Save to bytes
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    # Return image
    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    response['Content-Disposition'] = f'inline; filename="inventory-{item.qr_code}.png"'
    return response


@login_required
def inventory_print_qr_codes(request, vehicle_id):
    """
    Print page for all inventory item QR codes.
    Shows grid of QR codes with labels for printing.
    """
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    # Check permissions
    if not request.user.is_staff and vehicle.organization != request.user.current_organization:
        raise PermissionDenied

    # Get all inventory items for this vehicle
    items = vehicle.inventory_items.all().order_by('category', 'name')

    return render(request, 'vehicles/inventory_print_qr.html', {
        'vehicle': vehicle,
        'items': items
    })


@login_required
def inventory_scan(request, qr_code):
    """
    Mobile scanner interface - scan QR code to update quantity.
    Optimized for phone/tablet use.
    """
    item = get_object_or_404(VehicleInventoryItem, qr_code=qr_code)

    # Check permissions
    if not request.user.is_staff and item.vehicle.organization != request.user.current_organization:
        raise PermissionDenied

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'increment':
            item.quantity += 1
            item.save()
            messages.success(request, f'Increased {item.name} to {item.quantity}')

        elif action == 'decrement':
            if item.quantity > 0:
                item.quantity -= 1
                item.save()
                messages.success(request, f'Decreased {item.name} to {item.quantity}')
            else:
                messages.error(request, 'Quantity cannot be negative')

        elif action == 'set':
            try:
                new_quantity = int(request.POST.get('quantity', 0))
                if new_quantity >= 0:
                    item.quantity = new_quantity
                    item.save()
                    messages.success(request, f'Set {item.name} to {item.quantity}')
                else:
                    messages.error(request, 'Quantity cannot be negative')
            except ValueError:
                messages.error(request, 'Invalid quantity')

        # Return JSON for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({
                'success': True,
                'quantity': item.quantity,
                'is_low_stock': item.is_low_stock,
                'needs_restock': item.needs_restock
            })

        return redirect('vehicles:inventory_scan', qr_code=qr_code)

    return render(request, 'vehicles/inventory_scan.html', {
        'item': item,
        'vehicle': item.vehicle
    })


@login_required
@require_http_methods(["POST"])
def inventory_quick_update(request, pk):
    """
    API endpoint for quick quantity updates.
    Used by mobile scanner interface.
    """
    from django.http import JsonResponse

    item = get_object_or_404(VehicleInventoryItem, pk=pk)

    # Check permissions
    if not request.user.is_staff and item.vehicle.organization != request.user.current_organization:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        import json
        data = json.loads(request.body)
        action = data.get('action')

        if action == 'increment':
            item.quantity += 1
        elif action == 'decrement':
            if item.quantity > 0:
                item.quantity -= 1
            else:
                return JsonResponse({'error': 'Quantity cannot be negative'}, status=400)
        elif action == 'set':
            quantity = int(data.get('quantity', 0))
            if quantity >= 0:
                item.quantity = quantity
            else:
                return JsonResponse({'error': 'Quantity cannot be negative'}, status=400)
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)

        item.save()

        return JsonResponse({
            'success': True,
            'quantity': item.quantity,
            'is_low_stock': item.is_low_stock,
            'needs_restock': item.needs_restock,
            'message': f'Updated {item.name} to {item.quantity} {item.unit}'
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
