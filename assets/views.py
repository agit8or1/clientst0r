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

    return render(request, 'assets/asset_detail.html', {
        'asset': asset,
        'relationships': relationships,
    })


@login_required
@require_write
def asset_create(request):
    """
    Create new asset.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        form = AssetForm(request.POST, organization=org)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.organization = org
            asset.created_by = request.user
            asset.save()
            form.save_m2m()
            messages.success(request, f"Asset '{asset.name}' created successfully.")
            return redirect('assets:asset_detail', pk=asset.pk)
    else:
        form = AssetForm(organization=org)

    return render(request, 'assets/asset_form.html', {
        'form': form,
        'action': 'Create',
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
