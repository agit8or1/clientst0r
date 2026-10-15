"""
Views for Service Vehicles
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum, Avg, Max
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied
from datetime import timedelta

from core.ai_gate import require_ai_enabled_json
from files.models import Attachment
from .models import (
    ServiceVehicle, VehicleInventoryItem, VehicleDamageReport,
    VehicleMaintenanceRecord, VehicleFuelLog, VehicleAssignment,
    VehicleServiceSchedule, VehicleServiceAlert, VehicleServiceProvider,
    ShopInventoryItem, VehicleReceipt
)
from .forms import (
    ServiceVehicleForm, VehicleInventoryItemForm, VehicleDamageReportForm,
    VehicleMaintenanceRecordForm, VehicleFuelLogForm, VehicleAssignmentForm,
    VehicleServiceScheduleForm, VehicleServiceAlertAcknowledgeForm, VehicleServiceProviderForm,
    ShopInventoryItemForm, VehicleReceiptForm
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

    # Service schedule alerts
    pending_service_alerts = VehicleServiceAlert.objects.filter(status='pending').select_related('vehicle', 'schedule')
    if pending_service_alerts.exists():
        overdue_count = sum(1 for a in pending_service_alerts if a.is_overdue)
        due_count = pending_service_alerts.count() - overdue_count
        if overdue_count:
            alerts.append({
                'type': 'danger',
                'icon': 'fas fa-bell',
                'title': 'Service Overdue',
                'message': f'{overdue_count} service(s) are overdue — schedule service now'
            })
        if due_count:
            alerts.append({
                'type': 'warning',
                'icon': 'fas fa-bell',
                'title': 'Service Due Soon',
                'message': f'{due_count} service(s) are coming due'
            })

    # Low inventory items
    inventory_items = VehicleInventoryItem.objects.all()

    low_stock = [item for item in inventory_items if item.is_low_stock]
    if low_stock:
        alerts.append({
            'type': 'warning',
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
        'pending_service_alerts': pending_service_alerts,
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

    # Receipts
    receipts = vehicle.receipts.all().order_by('-receipt_date')
    receipt_totals = {}
    for cat, _ in VehicleReceipt.CATEGORY_CHOICES:
        agg = receipts.filter(category=cat).aggregate(total=Sum('amount'))['total'] or 0
        receipt_totals[cat] = agg
    receipt_grand_total = receipts.aggregate(total=Sum('amount'))['total'] or 0

    # Generate service alerts for this vehicle
    _generate_vehicle_service_alerts(vehicle)

    # Service data
    service_schedules = vehicle.service_schedules.all().order_by('name')
    service_alerts = vehicle.service_alerts.filter(status='pending').order_by('-created_at')
    service_providers = vehicle.service_providers.all().order_by('-is_preferred', 'name')

    # Compute vehicle health score (0-100)
    condition_scores = {'excellent': 100, 'good': 80, 'fair': 60, 'poor': 40, 'needs_repair': 20}
    health_score = condition_scores.get(vehicle.condition, 60)
    health_score -= (pending_damage * 10)
    health_score -= (overdue_maintenance * 15)
    health_score -= (service_alerts.count() * 5)
    health_score = max(0, min(100, health_score))
    if health_score >= 80:
        vehicle_health_label = 'Excellent'
        vehicle_health_color = 'success'
    elif health_score >= 60:
        vehicle_health_label = 'Good'
        vehicle_health_color = 'primary'
    elif health_score >= 40:
        vehicle_health_label = 'Fair'
        vehicle_health_color = 'warning'
    else:
        vehicle_health_label = 'Poor'
        vehicle_health_color = 'danger'

    # Vehicle photos
    vehicle_photos = Attachment.objects.filter(
        entity_type='vehicle',
        entity_id=vehicle.pk,
        content_type__startswith='image/'
    ).order_by('-created_at')

    # Damage report photos keyed by report ID
    import json as _json
    damage_report_ids = list(damage_reports.values_list('id', flat=True))
    damage_photos_qs = Attachment.objects.filter(
        entity_type='vehicle_damage',
        entity_id__in=damage_report_ids,
        content_type__startswith='image/'
    ).values('entity_id', 'id')
    damage_photos_map = {}
    for p in damage_photos_qs:
        damage_photos_map.setdefault(p['entity_id'], []).append(p['id'])
    damage_photos_json = _json.dumps({str(k): v for k, v in damage_photos_map.items()})

    context = {
        'vehicle': vehicle,
        'vehicle_photos': vehicle_photos,
        'damage_photos_json': damage_photos_json,
        'inventory_items': inventory_items,
        'damage_reports': damage_reports,
        'maintenance_records': maintenance_records,
        'fuel_logs': fuel_logs,
        'assignments': assignments,
        'service_schedules': service_schedules,
        'service_alerts': service_alerts,
        'service_providers': service_providers,
        'total_inventory_value': total_inventory_value,
        'low_stock_count': low_stock_count,
        'pending_damage': pending_damage,
        'total_damage_cost': total_damage_cost,
        'total_maintenance_cost': total_maintenance_cost,
        'overdue_maintenance': overdue_maintenance,
        'total_fuel_cost': total_fuel_cost,
        'avg_mpg': avg_mpg,
        'vehicle_health_score': health_score,
        'vehicle_health_remainder': 100 - health_score,
        'vehicle_health_label': vehicle_health_label,
        'vehicle_health_color': vehicle_health_color,
        'receipts': receipts,
        'receipt_totals': receipt_totals,
        'receipt_grand_total': receipt_grand_total,
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


# Global / Cross-Vehicle Inventory Views

@login_required
def inventory_list(request):
    """
    Unified inventory page with filter tabs:
    - view=all (default): vehicle items + shop items
    - view=vehicles: all vehicle items flat list
    - view=by_vehicle: grouped by vehicle
    - view=shop: shop items only
    - vehicle=<id>: items for a specific vehicle
    """
    view = request.GET.get('view', 'all')
    vehicle_id = request.GET.get('vehicle', '').strip()
    search = request.GET.get('search', '').strip()

    all_vehicles = ServiceVehicle.objects.order_by('name')
    selected_vehicle = None
    if vehicle_id:
        selected_vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
        view = 'by_vehicle'

    # Build querysets
    vehicle_items = VehicleInventoryItem.objects.select_related('vehicle').order_by('vehicle__name', 'category', 'name')
    shop_items = ShopInventoryItem.objects.order_by('category', 'name')

    if selected_vehicle:
        vehicle_items = vehicle_items.filter(vehicle=selected_vehicle)

    if search:
        vehicle_items = vehicle_items.filter(Q(name__icontains=search) | Q(category__icontains=search))
        shop_items = shop_items.filter(Q(name__icontains=search) | Q(category__icontains=search))

    # Build grouped-by-vehicle data when needed
    vehicle_data = None
    if view in ('by_vehicle', 'all') or selected_vehicle:
        vqs = [selected_vehicle] if selected_vehicle else list(all_vehicles)
        vehicle_data = []
        for v in vqs:
            items = v.inventory_items.all().order_by('category', 'name')
            if search:
                items = items.filter(Q(name__icontains=search) | Q(category__icontains=search))
            low_stock = [i for i in items if i.is_low_stock]
            vehicle_data.append({
                'vehicle': v,
                'items': items,
                'low_stock_count': len(low_stock),
                'total_value': sum(i.total_value for i in items if i.total_value),
            })

    low_stock_all = [i for i in vehicle_items if i.is_low_stock] + [i for i in shop_items if i.is_low_stock]

    return render(request, 'vehicles/inventory_list.html', {
        'view': view,
        'search': search,
        'vehicle_items': vehicle_items,
        'shop_items': shop_items,
        'vehicle_data': vehicle_data,
        'all_vehicles': all_vehicles,
        'selected_vehicle': selected_vehicle,
        'low_stock_all': low_stock_all,
    })


# Keep legacy aliases so old bookmarks/links still work
@login_required
def inventory_global_list(request):
    return redirect('vehicles:inventory_list')


@login_required
def inventory_by_vehicle(request):
    from django.urls import reverse as _reverse
    return redirect(_reverse('vehicles:inventory_list') + '?view=by_vehicle')


# Shop Inventory Views

@login_required
def shop_inventory_list(request):
    from django.urls import reverse as _reverse
    return redirect(_reverse('vehicles:inventory_list') + '?view=shop')


@login_required
def shop_inventory_create(request):
    """Add item to shop inventory"""
    if request.method == 'POST':
        form = ShopInventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'Shop item "{item.name}" added successfully.')
            return redirect('vehicles:shop_inventory_list')
    else:
        form = ShopInventoryItemForm()

    return render(request, 'vehicles/shop_inventory_form.html', {
        'form': form,
        'title': 'Add Shop Inventory Item',
        'button_text': 'Add Item',
    })


@login_required
def shop_inventory_edit(request, pk):
    """Edit shop inventory item"""
    item = get_object_or_404(ShopInventoryItem, pk=pk)

    if request.method == 'POST':
        form = ShopInventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Shop item "{item.name}" updated successfully.')
            return redirect('vehicles:shop_inventory_list')
    else:
        form = ShopInventoryItemForm(instance=item)

    return render(request, 'vehicles/shop_inventory_form.html', {
        'form': form,
        'item': item,
        'title': f'Edit {item.name}',
        'button_text': 'Save Changes',
    })


@login_required
def shop_inventory_delete(request, pk):
    """Delete shop inventory item"""
    item = get_object_or_404(ShopInventoryItem, pk=pk)

    if request.method == 'POST':
        item_name = item.name
        item.delete()
        messages.success(request, f'Shop item "{item_name}" deleted successfully.')
        return redirect('vehicles:shop_inventory_list')

    return render(request, 'vehicles/shop_inventory_confirm_delete.html', {'item': item})


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
        initial = {
            'reported_by': request.user,
            'incident_date': timezone.now().date()
        }
        location = request.GET.get('location', '').strip()
        if location:
            initial['damage_location'] = location
        form = VehicleDamageReportForm(initial=initial)

    vehicle_photos = Attachment.objects.filter(
        entity_type='vehicle', entity_id=vehicle.pk,
        content_type__startswith='image/'
    ).order_by('-created_at')

    return render(request, 'vehicles/damage_report_form.html', {
        'form': form,
        'vehicle': vehicle,
        'vehicle_photos': vehicle_photos,
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

    vehicle_photos = Attachment.objects.filter(
        entity_type='vehicle', entity_id=report.vehicle.pk,
        content_type__startswith='image/'
    ).order_by('-created_at')

    return render(request, 'vehicles/damage_report_form.html', {
        'form': form,
        'vehicle': report.vehicle,
        'vehicle_photos': vehicle_photos,
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

def _qr_base_url(request):
    """Return the site URL from SystemSetting, falling back to request host."""
    try:
        from core.models import SystemSetting
        settings_obj = SystemSetting.objects.first()
        if settings_obj and settings_obj.site_url:
            return settings_obj.site_url.rstrip('/')
    except Exception:
        pass
    return request.build_absolute_uri('/').rstrip('/')


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
    qr_url = _qr_base_url(request) + item.get_qr_code_url()

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

    except Exception:
        return JsonResponse({'error': 'Failed to update inventory item'}, status=400)


@login_required
def take_inventory(request, vehicle_id):
    """
    Take Inventory mode - scan multiple QR codes to update quantities.
    Mobile-optimized for quick inventory counts.
    """
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
    
    # Get or initialize session data
    session_key = f'inventory_session_{vehicle_id}'
    if session_key not in request.session:
        request.session[session_key] = {
            'started_at': timezone.now().isoformat(),
            'scanned_items': [],
            'total_scanned': 0
        }
    
    session_data = request.session[session_key]
    
    # Get all inventory items for this vehicle
    inventory_items = vehicle.inventory_items.all().order_by('category', 'name')
    
    # Get recently scanned items from session
    scanned_qr_codes = [item['qr_code'] for item in session_data['scanned_items']]
    recently_scanned = VehicleInventoryItem.objects.filter(
        qr_code__in=scanned_qr_codes
    )
    
    context = {
        'vehicle': vehicle,
        'inventory_items': inventory_items,
        'session_data': session_data,
        'recently_scanned': recently_scanned,
    }
    
    return render(request, 'vehicles/take_inventory.html', context)


@login_required  
@require_http_methods(["POST"])
def inventory_scan_update(request, qr_code):
    """
    Quick scan and update - called from take inventory mode.
    Updates quantity and adds to session tracking.
    """
    item = get_object_or_404(VehicleInventoryItem, qr_code=qr_code)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'set_quantity':
            new_quantity = int(request.POST.get('quantity', item.quantity))
            old_quantity = item.quantity
            item.quantity = new_quantity
            item.save()
            
            # Update session data
            session_key = f'inventory_session_{item.vehicle.id}'
            if session_key in request.session:
                session_data = request.session[session_key]
                session_data['scanned_items'].append({
                    'qr_code': qr_code,
                    'name': item.name,
                    'old_quantity': old_quantity,
                    'new_quantity': new_quantity,
                    'timestamp': timezone.now().isoformat()
                })
                session_data['total_scanned'] += 1
                request.session[session_key] = session_data
                request.session.modified = True
            
            messages.success(request, f'Updated {item.name}: {old_quantity} → {new_quantity}')
            
        elif action == 'increment':
            item.quantity += 1
            item.save()
            messages.success(request, f'{item.name}: {item.quantity}')
            
        elif action == 'decrement' and item.quantity > 0:
            item.quantity -= 1
            item.save()
            messages.success(request, f'{item.name}: {item.quantity}')
    
    # Return to take inventory mode
    return redirect('vehicles:take_inventory', vehicle_id=item.vehicle.id)


@login_required
def end_inventory_session(request, vehicle_id):
    """End inventory session and show summary."""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
    
    session_key = f'inventory_session_{vehicle_id}'
    session_data = request.session.get(session_key, {})
    
    # Clear session
    if session_key in request.session:
        del request.session[session_key]
        request.session.modified = True
    
    context = {
        'vehicle': vehicle,
        'session_data': session_data,
    }
    
    messages.success(request, f'Inventory session completed! Scanned {session_data.get("total_scanned", 0)} items.')

    return render(request, 'vehicles/inventory_summary.html', context)


# ============================================================================
# Service Alerts & Schedules
# ============================================================================

def _generate_vehicle_service_alerts(vehicle):
    """Check all active service schedules and create pending alerts if needed."""
    from datetime import timedelta
    today = timezone.now().date()

    for schedule in vehicle.service_schedules.filter(is_active=True):
        # Skip if a pending alert already exists for this schedule
        if schedule.alerts.filter(status='pending').exists():
            continue

        triggered = False
        due_mileage = None
        due_date = None

        if schedule.interval_miles and schedule.last_service_mileage is not None:
            next_mi = schedule.last_service_mileage + schedule.interval_miles
            if vehicle.current_mileage >= next_mi - schedule.warning_miles:
                triggered = True
                due_mileage = next_mi

        if schedule.interval_days and schedule.last_service_date:
            next_dt = schedule.last_service_date + timedelta(days=schedule.interval_days)
            if today >= next_dt - timedelta(days=schedule.warning_days):
                triggered = True
                due_date = next_dt

        if triggered:
            VehicleServiceAlert.objects.create(
                vehicle=vehicle,
                schedule=schedule,
                title=f'{schedule.name} due',
                due_mileage=due_mileage,
                due_date=due_date,
                status='pending',
            )


@login_required
def service_alert_list(request):
    """Fleet-wide view of all pending and recent service alerts."""
    pending = VehicleServiceAlert.objects.filter(
        status='pending'
    ).select_related('vehicle', 'schedule').order_by('-created_at')

    recent_completed = VehicleServiceAlert.objects.filter(
        status='completed'
    ).select_related('vehicle', 'schedule', 'acknowledged_by').order_by('-acknowledged_at')[:20]

    return render(request, 'vehicles/service_alert_list.html', {
        'pending_alerts': pending,
        'recent_completed': recent_completed,
    })


@login_required
def service_alert_acknowledge(request, pk):
    """Acknowledge a service alert, optionally recording service as done."""
    alert = get_object_or_404(VehicleServiceAlert, pk=pk)

    if request.method == 'POST':
        form = VehicleServiceAlertAcknowledgeForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            alert.acknowledgement_notes = cd.get('acknowledgement_notes', '')
            alert.acknowledged_by = request.user
            alert.acknowledged_at = timezone.now()

            if cd.get('record_service_done'):
                # Create a maintenance record
                record = VehicleMaintenanceRecord.objects.create(
                    vehicle=alert.vehicle,
                    maintenance_type=alert.schedule.service_type if alert.schedule else 'other',
                    description=cd.get('service_notes') or f'{alert.title} — completed',
                    service_date=cd['service_date'],
                    mileage_at_service=cd['service_mileage'],
                    performed_by=cd.get('performed_by', ''),
                    is_scheduled=True,
                )
                alert.service_record = record
                alert.status = 'completed'

                # Update the schedule's last service info
                if alert.schedule:
                    alert.schedule.last_service_date = cd['service_date']
                    alert.schedule.last_service_mileage = cd['service_mileage']
                    alert.schedule.save(update_fields=['last_service_date', 'last_service_mileage'])
            else:
                alert.status = 'acknowledged'

            alert.save()
            messages.success(request, f'Alert acknowledged for {alert.vehicle.display_name}.')
            return redirect('vehicles:vehicle_detail', pk=alert.vehicle.pk)
    else:
        initial = {'record_service_done': True}
        if alert.schedule and alert.schedule.last_service_mileage:
            initial['service_mileage'] = alert.vehicle.current_mileage
        initial['service_date'] = timezone.now().date()
        form = VehicleServiceAlertAcknowledgeForm(initial=initial)

    return render(request, 'vehicles/service_alert_acknowledge.html', {
        'alert': alert,
        'form': form,
    })


@login_required
def service_schedule_create(request, vehicle_id):
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
    if request.method == 'POST':
        form = VehicleServiceScheduleForm(request.POST)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.vehicle = vehicle
            schedule.save()
            messages.success(request, f'Service schedule "{schedule.name}" created.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        initial = {'last_service_mileage': vehicle.current_mileage}
        form = VehicleServiceScheduleForm(initial=initial)

    return render(request, 'vehicles/service_schedule_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Add Service Schedule',
        'button_text': 'Create Schedule',
    })


@login_required
def service_schedule_edit(request, pk):
    schedule = get_object_or_404(VehicleServiceSchedule, pk=pk)
    if request.method == 'POST':
        form = VehicleServiceScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
            messages.success(request, f'Service schedule "{schedule.name}" updated.')
            return redirect('vehicles:vehicle_detail', pk=schedule.vehicle.pk)
    else:
        form = VehicleServiceScheduleForm(instance=schedule)

    return render(request, 'vehicles/service_schedule_form.html', {
        'form': form,
        'vehicle': schedule.vehicle,
        'schedule': schedule,
        'title': 'Edit Service Schedule',
        'button_text': 'Save Changes',
    })


@login_required
def service_schedule_delete(request, pk):
    schedule = get_object_or_404(VehicleServiceSchedule, pk=pk)
    vehicle = schedule.vehicle
    if request.method == 'POST':
        schedule.delete()
        messages.success(request, 'Service schedule deleted.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    return render(request, 'vehicles/service_schedule_confirm_delete.html', {
        'schedule': schedule, 'vehicle': vehicle
    })


@login_required
def service_provider_create(request, vehicle_id):
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
    if request.method == 'POST':
        form = VehicleServiceProviderForm(request.POST)
        if form.is_valid():
            provider = form.save(commit=False)
            provider.vehicle = vehicle
            provider.save()
            messages.success(request, f'Service provider "{provider.name}" added.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleServiceProviderForm()

    return render(request, 'vehicles/service_provider_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Add Service Provider',
        'button_text': 'Add Provider',
    })


@login_required
def service_provider_edit(request, pk):
    provider = get_object_or_404(VehicleServiceProvider, pk=pk)
    if request.method == 'POST':
        form = VehicleServiceProviderForm(request.POST, instance=provider)
        if form.is_valid():
            form.save()
            messages.success(request, f'Service provider "{provider.name}" updated.')
            return redirect('vehicles:vehicle_detail', pk=provider.vehicle.pk)
    else:
        form = VehicleServiceProviderForm(instance=provider)

    return render(request, 'vehicles/service_provider_form.html', {
        'form': form,
        'vehicle': provider.vehicle,
        'provider': provider,
        'title': 'Edit Service Provider',
        'button_text': 'Save Changes',
    })


@login_required
def service_provider_delete(request, pk):
    provider = get_object_or_404(VehicleServiceProvider, pk=pk)
    vehicle = provider.vehicle
    if request.method == 'POST':
        provider.delete()
        messages.success(request, 'Service provider removed.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    return render(request, 'vehicles/service_provider_confirm_delete.html', {
        'provider': provider, 'vehicle': vehicle
    })


# ============================================================================
# Shop Inventory QR & Scan Views
# ============================================================================

@login_required
def shop_inventory_qr_image(request, pk):
    """Generate QR code PNG for a shop inventory item."""
    item = get_object_or_404(ShopInventoryItem, pk=pk)

    import qrcode
    from io import BytesIO
    from django.http import HttpResponse

    qr_url = _qr_base_url(request) + item.get_qr_code_url()

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    response['Content-Disposition'] = f'inline; filename="shop-{item.qr_code}.png"'
    return response


@login_required
def shop_item_scan(request, qr_code):
    """Mobile scan interface for shop inventory item."""
    item = get_object_or_404(ShopInventoryItem, qr_code=qr_code)

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
        elif action == 'set':
            try:
                new_qty = int(request.POST.get('quantity', 0))
                if new_qty >= 0:
                    item.quantity = new_qty
                    item.save()
                    messages.success(request, f'Set {item.name} quantity to {item.quantity}')
            except (ValueError, TypeError):
                messages.error(request, 'Invalid quantity.')
        return redirect('vehicles:shop_item_scan', qr_code=qr_code)

    return render(request, 'vehicles/shop_inventory_scan.html', {
        'item': item,
    })


@login_required
def inventory_qr_print_all(request):
    """
    Printable QR code sheet for all inventory (vehicle items + shop items).
    Filter by vehicle or show all.
    """
    vehicle_id = request.GET.get('vehicle')
    selected_vehicle = None

    if vehicle_id:
        selected_vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
        vehicle_items = selected_vehicle.inventory_items.all().order_by('category', 'name')
    else:
        vehicle_items = VehicleInventoryItem.objects.select_related('vehicle').order_by('vehicle__name', 'category', 'name')

    shop_items = ShopInventoryItem.objects.order_by('category', 'name')
    vehicles = ServiceVehicle.objects.order_by('name')

    return render(request, 'vehicles/inventory_qr_print_all.html', {
        'vehicle_items': vehicle_items,
        'shop_items': shop_items,
        'vehicles': vehicles,
        'selected_vehicle': selected_vehicle,
    })


# ── Receipt views ────────────────────────────────────────────────────────────

def _save_receipt_image(image, receipt, request):
    """Store an uploaded image file as an Attachment for a receipt."""
    from core.middleware import get_request_organization
    org = get_request_organization(request)
    if not org:
        return
    Attachment.objects.create(
        organization=org,
        entity_type='vehicle_receipt',
        entity_id=receipt.pk,
        file=image,
        original_filename=image.name,
        file_size=image.size,
        content_type=getattr(image, 'content_type', None) or 'image/jpeg',
        uploaded_by=request.user,
    )


@login_required
def receipt_create(request, vehicle_id):
    """Create a receipt for a vehicle, optionally with an uploaded image."""
    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)

    if request.method == 'POST':
        form = VehicleReceiptForm(request.POST, request.FILES)
        if form.is_valid():
            receipt = form.save(commit=False)
            receipt.vehicle = vehicle
            receipt.created_by = request.user
            receipt.save()

            image = form.cleaned_data.get('receipt_image')
            if image:
                # Use hash already computed by OCR endpoint if present, else compute now
                img_hash = request.POST.get('ocr_image_hash') or _receipt_image_hash(image)
                receipt.image_hash = img_hash
                receipt.save(update_fields=['image_hash'])
                _save_receipt_image(image, receipt, request)

            messages.success(request, 'Receipt saved.')
            return redirect('vehicles:vehicle_detail', pk=vehicle.pk)
    else:
        form = VehicleReceiptForm(initial={'receipt_date': timezone.now().date()})

    return render(request, 'vehicles/receipt_form.html', {
        'form': form,
        'vehicle': vehicle,
        'title': 'Add Receipt',
        'button_text': 'Save Receipt',
    })


@login_required
def receipt_edit(request, pk):
    """Edit an existing receipt."""
    receipt = get_object_or_404(VehicleReceipt, pk=pk)

    if request.method == 'POST':
        form = VehicleReceiptForm(request.POST, request.FILES, instance=receipt)
        if form.is_valid():
            receipt = form.save()

            image = form.cleaned_data.get('receipt_image')
            if image:
                new_hash = _receipt_image_hash(image)
                # Allow replacing the image on the SAME receipt but block if
                # the new image matches a DIFFERENT receipt
                duplicate = VehicleReceipt.objects.filter(
                    image_hash=new_hash
                ).exclude(pk=receipt.pk).select_related('vehicle').first()
                if duplicate:
                    messages.error(
                        request,
                        f'That receipt image was already imported on {duplicate.receipt_date} '
                        f'({duplicate.get_category_display()}, ${duplicate.amount}) '
                        f'for {duplicate.vehicle.display_name}. Upload a different image.'
                    )
                    return render(request, 'vehicles/receipt_form.html', {
                        'form': form, 'vehicle': receipt.vehicle, 'receipt': receipt,
                        'title': 'Edit Receipt', 'button_text': 'Save Changes',
                    })
                receipt.image_hash = new_hash
                receipt.save(update_fields=['image_hash'])
                # Delete old attachment files then records
                old_attachments = Attachment.objects.filter(
                    entity_type='vehicle_receipt', entity_id=receipt.pk
                )
                for att in old_attachments:
                    att.file.delete(save=False)
                old_attachments.delete()
                _save_receipt_image(image, receipt, request)

            messages.success(request, 'Receipt updated.')
            return redirect('vehicles:vehicle_detail', pk=receipt.vehicle.pk)
    else:
        form = VehicleReceiptForm(instance=receipt)

    return render(request, 'vehicles/receipt_form.html', {
        'form': form,
        'vehicle': receipt.vehicle,
        'receipt': receipt,
        'title': 'Edit Receipt',
        'button_text': 'Save Changes',
    })


@login_required
def receipt_delete(request, pk):
    """Delete a receipt."""
    receipt = get_object_or_404(VehicleReceipt, pk=pk)
    vehicle = receipt.vehicle

    if request.method == 'POST':
        for att in Attachment.objects.filter(entity_type='vehicle_receipt', entity_id=receipt.pk):
            att.file.delete(save=False)
        Attachment.objects.filter(entity_type='vehicle_receipt', entity_id=receipt.pk).delete()
        receipt.delete()
        messages.success(request, 'Receipt deleted.')
        return redirect('vehicles:vehicle_detail', pk=vehicle.pk)

    return render(request, 'vehicles/receipt_confirm_delete.html', {
        'receipt': receipt,
        'vehicle': vehicle,
    })


@login_required
@require_http_methods(['POST'])
@require_ai_enabled_json
def receipt_ocr_extract(request, vehicle_id):
    """AJAX: Extract receipt data from uploaded image using Claude vision.
    Returns duplicate warning if the same image has already been OCR-imported.
    """
    import hashlib
    from .services.receipt_ocr import extract_receipt_data
    from django.http import JsonResponse

    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'success': False, 'error': 'No image provided.'}, status=400)

    # Compute SHA-256 of the image bytes for duplicate detection
    image.seek(0)
    img_bytes = image.read()
    image_hash = hashlib.sha256(img_bytes).hexdigest()
    image.seek(0)

    # Check for existing receipt with same image hash
    existing = VehicleReceipt.objects.filter(image_hash=image_hash).select_related('vehicle').first()
    if existing:
        return JsonResponse({
            'success': False,
            'duplicate': True,
            'error': (
                f'This receipt image was already imported on {existing.receipt_date} '
                f'({existing.get_category_display()}, ${existing.amount}) '
                f'for {existing.vehicle.display_name}. '
                f'Duplicate receipts are not allowed.'
            ),
        })

    result = extract_receipt_data(image)
    if result.get('success'):
        result['image_hash'] = image_hash  # pass back so the form can embed it
    return JsonResponse(result)


def _receipt_image_hash(image_file):
    """Return SHA-256 hex digest of an uploaded image file."""
    import hashlib
    image_file.seek(0)
    digest = hashlib.sha256(image_file.read()).hexdigest()
    image_file.seek(0)
    return digest


@login_required
def receipt_quick(request):
    """
    Mobile-optimised landing page for the 'Scan Receipt' PWA shortcut.
    If the user only has one vehicle, redirect straight to receipt_create.
    Otherwise show a vehicle picker.
    """
    # QR codes embed ?v=<pk> so they land on the right vehicle immediately
    vehicle_pk = request.GET.get('v')
    if vehicle_pk:
        vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_pk)
        return redirect('vehicles:receipt_create', vehicle_id=vehicle.pk)

    vehicles = ServiceVehicle.objects.filter(status__in=['active', 'maintenance']).order_by('name')
    if vehicles.count() == 1:
        return redirect('vehicles:receipt_create', vehicle_id=vehicles.first().pk)
    return render(request, 'vehicles/receipt_quick.html', {'vehicles': vehicles})


@login_required
def receipt_qr_image(request, vehicle_id):
    """Return a PNG QR code that links to the Add Receipt page for this vehicle."""
    import qrcode
    from io import BytesIO
    from django.http import HttpResponse

    vehicle = get_object_or_404(ServiceVehicle, pk=vehicle_id)
    url = _qr_base_url(request) + f'/vehicles/receipts/quick/?v={vehicle.pk}'

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    response = HttpResponse(buf.getvalue(), content_type='image/png')
    response['Content-Disposition'] = f'inline; filename="receipt-qr-{vehicle.pk}.png"'
    return response
