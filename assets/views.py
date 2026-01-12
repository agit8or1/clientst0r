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
    List all assets in current organization.
    """
    org = get_request_organization(request)
    assets = Asset.objects.for_organization(org).prefetch_related('tags').select_related('primary_contact')

    return render(request, 'assets/asset_list.html', {
        'assets': assets,
    })


@login_required
def asset_detail(request, pk):
    """
    View asset details with relationships.
    """
    org = get_request_organization(request)
    asset = get_object_or_404(Asset, pk=pk, organization=org)

    # Get relationships
    relationships = Relationship.objects.filter(
        organization=org,
        source_type='asset',
        source_id=asset.id
    )

    # Get asset images
    from files.models import Attachment
    asset_images = Attachment.objects.filter(
        organization=org,
        entity_type='asset',
        entity_id=asset.id,
        content_type__startswith='image/'
    ).order_by('-created_at')

    # Get port configurations for network equipment
    port_configs = None
    if asset.asset_type in ['switch', 'router', 'firewall', 'wireless_controller', 'load_balancer']:
        from .models import NetworkPortConfiguration
        port_configs = NetworkPortConfiguration.objects.filter(
            organization=org,
            asset=asset
        ).order_by('-created_at')

    # Get patch panel info if this is a patch panel asset
    patch_panel = None
    if asset.asset_type in ['patch_panel', 'fiber_panel']:
        from monitoring.models import RackResource
        patch_panel = RackResource.objects.filter(
            asset=asset,
            resource_type='patch_panel'
        ).first()

    return render(request, 'assets/asset_detail.html', {
        'asset': asset,
        'relationships': relationships,
        'asset_images': asset_images,
        'port_configs': port_configs,
        'patch_panel': patch_panel,
    })


@login_required
@require_write
def asset_create(request):
    """
    Create new asset.
    """
    org = get_request_organization(request)

    # Check for redirect parameter (e.g., from rack page)
    redirect_to = request.GET.get('redirect') or request.POST.get('redirect')

    if request.method == 'POST':
        form = AssetForm(request.POST, organization=org)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.organization = org
            asset.created_by = request.user
            asset.save()
            form.save_m2m()
            messages.success(request, f"Asset '{asset.name}' created successfully. Now add it to the rack.")

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
            asset = form.save()
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
    List all contacts.
    """
    org = get_request_organization(request)
    contacts = Contact.objects.for_organization(org)

    return render(request, 'assets/contact_list.html', {
        'contacts': contacts,
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
