"""
Assets views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import Asset, Contact, Relationship
from .forms import AssetForm, ContactForm


@login_required
def asset_list(request):
    """
    List all assets in current organization with filtering.
    In global view mode, shows all assets across all organizations.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: show all assets across all organizations
        assets = Asset.objects.all().select_related('organization').prefetch_related('tags').select_related('primary_contact', 'equipment_model__vendor')
        all_assets = Asset.objects.all()
    else:
        # Organization view: show only assets for current org
        assets = Asset.objects.for_organization(org).prefetch_related('tags').select_related('primary_contact', 'equipment_model__vendor')
        all_assets = Asset.objects.for_organization(org)

    # Apply filters
    filter_type = request.GET.get('type', '')
    filter_manufacturer = request.GET.get('manufacturer', '')
    filter_status = request.GET.get('status', '')
    filter_location = request.GET.get('location', '')

    if filter_type:
        assets = assets.filter(asset_type=filter_type)

    if filter_manufacturer:
        assets = assets.filter(manufacturer__icontains=filter_manufacturer)

    if filter_status:
        # Status is typically stored in custom_fields
        assets = assets.filter(custom_fields__status=filter_status)

    if filter_location:
        # Location is typically stored in custom_fields
        assets = assets.filter(custom_fields__location__icontains=filter_location)

    # Get unique values for filter dropdowns
    manufacturers = all_assets.exclude(manufacturer='').values_list('manufacturer', flat=True).distinct().order_by('manufacturer')
    asset_types = Asset.ASSET_TYPES

    # Get unique statuses and locations from custom_fields
    statuses = set()
    locations = set()
    for asset in all_assets:
        if asset.custom_fields.get('status'):
            statuses.add(asset.custom_fields['status'])
        if asset.custom_fields.get('location'):
            locations.add(asset.custom_fields['location'])

    return render(request, 'assets/asset_list.html', {
        'assets': assets,
        'manufacturers': manufacturers,
        'asset_types': asset_types,
        'statuses': sorted(statuses),
        'locations': sorted(locations),
        'filter_type': filter_type,
        'filter_manufacturer': filter_manufacturer,
        'filter_status': filter_status,
        'filter_location': filter_location,
        'in_global_view': in_global_view,
    })


@login_required
def asset_detail(request, pk):
    """
    View asset details with relationships.
    Supports global view mode for superusers/staff users.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: access asset from any organization
        asset = get_object_or_404(Asset, pk=pk)
        asset_org = asset.organization
    else:
        # Organization view: filter by current org
        asset = get_object_or_404(Asset, pk=pk, organization=org)
        asset_org = org

    # Get relationships for this asset's organization
    relationships = Relationship.objects.filter(
        organization=asset_org,
        source_type='asset',
        source_id=asset.id
    )

    # Get asset images
    from files.models import Attachment
    asset_images = Attachment.objects.filter(
        organization=asset_org,
        entity_type='asset',
        entity_id=asset.id,
        content_type__startswith='image/'
    ).order_by('-created_at')

    return render(request, 'assets/asset_detail.html', {
        'asset': asset,
        'relationships': relationships,
        'asset_images': asset_images,
        'in_global_view': in_global_view,
    })


@login_required
@require_write
def asset_create(request):
    """
    Create new asset.
    """
    org = get_request_organization(request)

    # Check if user has an organization assigned
    if not org:
        messages.error(
            request,
            "You must be assigned to an organization before creating assets. "
            "Please contact your administrator to be added to an organization."
        )
        return redirect('core:dashboard')

    # Check for redirect parameter (e.g., from rack page)
    redirect_to = request.GET.get('redirect') or request.POST.get('redirect')

    if request.method == 'POST':
        form = AssetForm(request.POST, organization=org)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.organization = org
            asset.created_by = request.user

            # Initialize ports if port_count is specified
            port_count = form.cleaned_data.get('port_count')
            if port_count and asset.has_ports():
                # Determine port type based on asset type
                port_type = 'patch_panel' if asset.asset_type in ['patch_panel', 'fiber_panel'] else 'switch'
                asset.initialize_ports(port_count, port_type)

            asset.save()
            form.save_m2m()

            if port_count and asset.has_ports():
                messages.success(request, f"Asset '{asset.name}' created successfully with {port_count} ports.")
            else:
                messages.success(request, f"Asset '{asset.name}' created successfully.")

            # Handle redirect
            if redirect_to and redirect_to.startswith('rack_'):
                # Extract rack ID from "rack_123" format
                try:
                    rack_id = redirect_to.split('_')[1]
                    return redirect('monitoring:rack_device_create', rack_id=rack_id)
                except (IndexError, ValueError):
                    pass

            return redirect('assets:asset_detail', pk=asset.pk)
    else:
        form = AssetForm(organization=org)

    return render(request, 'assets/asset_form.html', {
        'form': form,
        'action': 'Create',
        'redirect_to': redirect_to,  # Pass to template for hidden field
    })


@login_required
@require_write
def asset_edit(request, pk):
    """
    Edit asset.
    """
    org = get_request_organization(request)
    asset = get_object_or_404(Asset, pk=pk, organization=org)

    if request.method == 'POST':
        form = AssetForm(request.POST, instance=asset, organization=org)
        if form.is_valid():
            # Track if port count changed
            old_port_count = asset.get_port_count()
            new_port_count = form.cleaned_data.get('port_count')

            asset = form.save(commit=False)

            # Re-initialize ports if count changed
            if new_port_count and asset.has_ports() and new_port_count != old_port_count:
                port_type = 'patch_panel' if asset.asset_type in ['patch_panel', 'fiber_panel'] else 'switch'
                asset.initialize_ports(new_port_count, port_type)
                messages.info(request, f"Port configuration updated to {new_port_count} ports.")

            asset.save()
            form.save_m2m()

            messages.success(request, f"Asset '{asset.name}' updated successfully.")
            return redirect('assets:asset_detail', pk=asset.pk)
    else:
        form = AssetForm(instance=asset, organization=org)

    return render(request, 'assets/asset_form.html', {
        'form': form,
        'asset': asset,
        'action': 'Edit',
    })


@login_required
def contact_list(request):
    """
    List all contacts in current organization or all contacts in global view.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: show all contacts across all organizations
        contacts = Contact.objects.all().select_related('organization')
    else:
        # Organization view: show only contacts for current org
        contacts = Contact.objects.for_organization(org)

    return render(request, 'assets/contact_list.html', {
        'contacts': contacts,
        'in_global_view': in_global_view,
    })


@login_required
def contact_detail(request, pk):
    """
    View contact details.
    """
    org = get_request_organization(request)
    contact = get_object_or_404(Contact, pk=pk, organization=org)

    # Get assets associated with this contact
    assets = Asset.objects.filter(
        organization=org,
        primary_contact=contact
    )

    return render(request, 'assets/contact_detail.html', {
        'contact': contact,
        'assets': assets,
    })


@login_required
@require_write
def contact_create(request):
    """
    Create new contact.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        form = ContactForm(request.POST, organization=org)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.organization = org
            contact.save()
            messages.success(request, f"Contact '{contact.name}' created successfully.")
            return redirect('assets:contact_detail', pk=contact.pk)
    else:
        form = ContactForm(organization=org)

    return render(request, 'assets/contact_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def contact_edit(request, pk):
    """
    Edit contact.
    """
    org = get_request_organization(request)
    contact = get_object_or_404(Contact, pk=pk, organization=org)

    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact, organization=org)
        if form.is_valid():
            contact = form.save()
            messages.success(request, f"Contact '{contact.name}' updated successfully.")
            return redirect('assets:contact_detail', pk=contact.pk)
    else:
        form = ContactForm(instance=contact, organization=org)

    return render(request, 'assets/contact_form.html', {
        'form': form,
        'contact': contact,
        'action': 'Edit',
    })


@login_required
@require_write
def contact_delete(request, pk):
    """
    Delete contact.
    """
    org = get_request_organization(request)
    contact = get_object_or_404(Contact, pk=pk, organization=org)

    if request.method == 'POST':
        name = contact.name
        contact.delete()
        messages.success(request, f"Contact '{name}' deleted successfully.")
        return redirect('assets:contact_list')

    return render(request, 'assets/contact_confirm_delete.html', {
        'contact': contact,
    })


@login_required
def equipment_model_api(request, pk):
    """
    API endpoint to return equipment model data as JSON.
    Used for auto-populating asset forms.
    """
    from django.http import JsonResponse
    from .models import EquipmentModel

    try:
        equipment = EquipmentModel.objects.select_related('vendor').get(pk=pk)

        data = {
            'vendor_name': equipment.vendor.name,
            'model_name': equipment.model_name,
            'is_rackmount': equipment.is_rackmount,
            'rack_units': equipment.rack_units,
            'equipment_type': equipment.equipment_type,
        }

        return JsonResponse(data)
    except EquipmentModel.DoesNotExist:
        return JsonResponse({'error': 'Equipment model not found'}, status=404)


@login_required
def equipment_models_by_vendor_api(request, vendor_id):
    """
    API endpoint to return equipment models for a specific vendor.
    Used for cascading dropdown functionality.
    """
    from django.http import JsonResponse
    from .models import EquipmentModel

    models = EquipmentModel.objects.filter(
        vendor_id=vendor_id,
        is_active=True
    ).values('id', 'model_name', 'equipment_type').order_by('model_name')

    return JsonResponse(list(models), safe=False)


# ========================================
# Equipment Catalog Management Views
# ========================================

@login_required
def vendor_list(request):
    """List all hardware vendors."""
    from .models import Vendor
    vendors = Vendor.objects.filter(is_active=True).order_by('name')

    return render(request, 'assets/vendor_list.html', {
        'vendors': vendors,
    })


@login_required
def vendor_detail(request, pk):
    """View vendor details with equipment models."""
    from .models import Vendor, EquipmentModel
    vendor = get_object_or_404(Vendor, pk=pk)

    equipment_models = EquipmentModel.objects.filter(
        vendor=vendor,
        is_active=True
    ).order_by('equipment_type', 'model_name')

    # Group by equipment type
    models_by_type = {}
    for model in equipment_models:
        if model.equipment_type not in models_by_type:
            models_by_type[model.equipment_type] = []
        models_by_type[model.equipment_type].append(model)

    return render(request, 'assets/vendor_detail.html', {
        'vendor': vendor,
        'equipment_models': equipment_models,
        'models_by_type': models_by_type,
    })


@login_required
@require_write
def vendor_create(request):
    """Create new hardware vendor."""
    from .forms import VendorForm

    if request.method == 'POST':
        form = VendorForm(request.POST)
        if form.is_valid():
            vendor = form.save()
            messages.success(request, f"Vendor '{vendor.name}' created successfully.")
            return redirect('assets:vendor_detail', pk=vendor.pk)
    else:
        form = VendorForm()

    return render(request, 'assets/vendor_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def vendor_edit(request, pk):
    """Edit existing vendor."""
    from .forms import VendorForm
    vendor = get_object_or_404(Vendor, pk=pk)

    if request.method == 'POST':
        form = VendorForm(request.POST, instance=vendor)
        if form.is_valid():
            vendor = form.save()
            messages.success(request, f"Vendor '{vendor.name}' updated successfully.")
            return redirect('assets:vendor_detail', pk=vendor.pk)
    else:
        form = VendorForm(instance=vendor)

    return render(request, 'assets/vendor_form.html', {
        'form': form,
        'vendor': vendor,
        'action': 'Edit',
    })


@login_required
def equipment_model_list(request):
    """List all equipment models with filtering."""
    from .models import EquipmentModel, Vendor

    # Get filter parameters
    vendor_id = request.GET.get('vendor')
    equipment_type = request.GET.get('type')
    search = request.GET.get('search')

    models = EquipmentModel.objects.filter(is_active=True).select_related('vendor')

    if vendor_id:
        models = models.filter(vendor_id=vendor_id)
    if equipment_type:
        models = models.filter(equipment_type=equipment_type)
    if search:
        models = models.filter(model_name__icontains=search)

    models = models.order_by('vendor__name', 'equipment_type', 'model_name')

    # Get filter options
    vendors = Vendor.objects.filter(is_active=True).order_by('name')
    equipment_types = EquipmentModel.EQUIPMENT_TYPES

    return render(request, 'assets/equipment_model_list.html', {
        'models': models,
        'vendors': vendors,
        'equipment_types': equipment_types,
        'selected_vendor': vendor_id,
        'selected_type': equipment_type,
        'search_query': search,
    })


@login_required
def equipment_model_detail(request, pk):
    """View equipment model details."""
    from .models import EquipmentModel, Asset
    model = get_object_or_404(EquipmentModel.objects.select_related('vendor'), pk=pk)

    # Get assets using this model
    org = get_request_organization(request)
    assets = Asset.objects.filter(
        organization=org,
        equipment_model=model
    ).select_related('primary_contact')

    return render(request, 'assets/equipment_model_detail.html', {
        'model': model,
        'assets': assets,
    })


@login_required
@require_write
def equipment_model_create(request):
    """Create new equipment model."""
    from .forms import EquipmentModelForm

    if request.method == 'POST':
        form = EquipmentModelForm(request.POST)
        if form.is_valid():
            model = form.save()
            messages.success(request, f"Equipment model '{model.model_name}' created successfully.")
            return redirect('assets:equipment_model_detail', pk=model.pk)
    else:
        form = EquipmentModelForm()

    return render(request, 'assets/equipment_model_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def equipment_model_edit(request, pk):
    """Edit existing equipment model."""
    from .forms import EquipmentModelForm
    model = get_object_or_404(EquipmentModel, pk=pk)

    if request.method == 'POST':
        form = EquipmentModelForm(request.POST, instance=model)
        if form.is_valid():
            model = form.save()
            messages.success(request, f"Equipment model '{model.model_name}' updated successfully.")
            return redirect('assets:equipment_model_detail', pk=model.pk)
    else:
        form = EquipmentModelForm(instance=model)

    return render(request, 'assets/equipment_model_form.html', {
        'form': form,
        'model': model,
        'action': 'Edit',
    })
