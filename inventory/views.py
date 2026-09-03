"""
Inventory views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from core.middleware import get_request_organization
from core.decorators import require_admin, require_write
from .models import (
    InventoryCategory, InventoryItem, InventoryLocation, InventoryTransaction, Tool,
)
from .forms import (
    InventoryAdjustForm, InventoryCategoryForm, InventoryItemForm,
    InventoryLocationForm, ToolForm,
)


@login_required
def inventory_dashboard(request):
    """Dashboard with summary stats and recent transactions."""
    org = get_request_organization(request)
    total_items = InventoryItem.objects.for_organization(org).count() if org else 0
    low_stock_count = sum(
        1 for item in InventoryItem.objects.for_organization(org)
        if item.is_low_stock
    ) if org else 0
    total_categories = InventoryCategory.objects.for_organization(org).count() if org else 0
    total_locations = InventoryLocation.objects.for_organization(org).count() if org else 0

    recent_transactions = []
    if org:
        item_ids = InventoryItem.objects.for_organization(org).values_list('id', flat=True)
        recent_transactions = InventoryTransaction.objects.filter(
            item_id__in=item_ids
        ).select_related('item', 'performed_by').order_by('-created_at')[:10]

    return render(request, 'inventory/dashboard.html', {
        'total_items': total_items,
        'low_stock_count': low_stock_count,
        'total_categories': total_categories,
        'total_locations': total_locations,
        'recent_transactions': recent_transactions,
    })


@login_required
def item_list(request):
    """List inventory items with search and filters."""
    org = get_request_organization(request)
    items = InventoryItem.objects.for_organization(org).select_related(
        'category', 'storage_location'
    ) if org else InventoryItem.objects.none()

    q = request.GET.get('q', '').strip()
    if q:
        items = items.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(description__icontains=q)
        )

    filter_type = request.GET.get('type', '')
    if filter_type:
        items = items.filter(item_type=filter_type)

    filter_category = request.GET.get('category', '')
    if filter_category:
        items = items.filter(category_id=filter_category)

    if request.GET.get('low_stock'):
        items = [item for item in items if item.is_low_stock]

    categories = InventoryCategory.objects.for_organization(org) if org else InventoryCategory.objects.none()

    return render(request, 'inventory/item_list.html', {
        'items': items,
        'categories': categories,
        'item_types': InventoryItem.ITEM_TYPES,
        'q': q,
        'filter_type': filter_type,
        'filter_category': filter_category,
        'show_low_stock': bool(request.GET.get('low_stock')),
    })


@login_required
def item_detail(request, pk):
    """Show item details and transaction history."""
    org = get_request_organization(request)
    item = get_object_or_404(InventoryItem, pk=pk, organization=org)
    transactions = item.transactions.select_related('performed_by').order_by('-created_at')

    return render(request, 'inventory/item_detail.html', {
        'item': item,
        'transactions': transactions,
    })


@login_required
@require_write
def item_create(request):
    """Create a new inventory item."""
    org = get_request_organization(request)
    if request.method == 'POST':
        form = InventoryItemForm(request.POST, org=org)
        if form.is_valid():
            item = form.save(commit=False)
            item.organization = org
            item.save()
            form.save_m2m()
            messages.success(request, f'Item "{item.name}" created successfully.')
            return redirect('inventory:item_detail', pk=item.pk)
    else:
        form = InventoryItemForm(org=org)

    return render(request, 'inventory/item_form.html', {
        'form': form,
        'title': 'Add Inventory Item',
    })


@login_required
@require_write
def item_edit(request, pk):
    """Edit an existing inventory item."""
    org = get_request_organization(request)
    item = get_object_or_404(InventoryItem, pk=pk, organization=org)

    if request.method == 'POST':
        form = InventoryItemForm(request.POST, instance=item, org=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Item "{item.name}" updated successfully.')
            return redirect('inventory:item_detail', pk=item.pk)
    else:
        form = InventoryItemForm(instance=item, org=org)

    return render(request, 'inventory/item_form.html', {
        'form': form,
        'item': item,
        'title': f'Edit: {item.name}',
    })


@login_required
@require_admin
def item_delete(request, pk):
    """Delete an inventory item."""
    org = get_request_organization(request)
    item = get_object_or_404(InventoryItem, pk=pk, organization=org)

    if request.method == 'POST':
        name = item.name
        item.delete()
        messages.success(request, f'Item "{name}" deleted.')
        return redirect('inventory:item_list')

    return render(request, 'inventory/item_confirm_delete.html', {'item': item})


@login_required
@require_write
def item_adjust(request, pk):
    """Adjust stock quantity for an item."""
    org = get_request_organization(request)
    item = get_object_or_404(InventoryItem, pk=pk, organization=org)

    if request.method == 'POST':
        form = InventoryAdjustForm(request.POST)
        if form.is_valid():
            qty_change = form.cleaned_data['quantity_change']
            new_qty = item.quantity + qty_change
            if new_qty < 0:
                messages.error(request, 'Cannot reduce stock below zero.')
            else:
                InventoryTransaction.objects.create(
                    item=item,
                    transaction_type=form.cleaned_data['transaction_type'],
                    quantity_change=qty_change,
                    quantity_after=new_qty,
                    notes=form.cleaned_data['notes'],
                    reference=form.cleaned_data['reference'],
                    performed_by=request.user,
                )
                item.quantity = new_qty
                item.save()
                messages.success(request, f'Stock adjusted. New quantity: {new_qty}.')
                return redirect('inventory:item_detail', pk=item.pk)
    else:
        form = InventoryAdjustForm()

    return render(request, 'inventory/item_adjust.html', {
        'form': form,
        'item': item,
    })


@login_required
def item_scan(request, qr_code):
    """Look up an item by QR code and redirect to its detail page."""
    org = get_request_organization(request)
    item = get_object_or_404(InventoryItem, qr_code=qr_code, organization=org)
    return redirect('inventory:item_detail', pk=item.pk)


@login_required
def category_list(request):
    """List all inventory categories."""
    org = get_request_organization(request)
    categories = InventoryCategory.objects.for_organization(org).prefetch_related('items') if org else InventoryCategory.objects.none()

    return render(request, 'inventory/category_list.html', {
        'categories': categories,
    })


@login_required
@require_write
def category_create(request):
    """Create a new inventory category."""
    org = get_request_organization(request)
    if request.method == 'POST':
        form = InventoryCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.organization = org
            category.save()
            messages.success(request, f'Category "{category.name}" created.')
            return redirect('inventory:category_list')
    else:
        form = InventoryCategoryForm()

    return render(request, 'inventory/category_form.html', {
        'form': form,
        'title': 'Add Category',
    })


@login_required
@require_write
def category_edit(request, pk):
    """Edit an existing category."""
    org = get_request_organization(request)
    category = get_object_or_404(InventoryCategory, pk=pk, organization=org)

    if request.method == 'POST':
        form = InventoryCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f'Category "{category.name}" updated.')
            return redirect('inventory:category_list')
    else:
        form = InventoryCategoryForm(instance=category)

    return render(request, 'inventory/category_form.html', {
        'form': form,
        'category': category,
        'title': f'Edit: {category.name}',
    })


@login_required
@require_admin
def category_delete(request, pk):
    """Delete a category."""
    org = get_request_organization(request)
    category = get_object_or_404(InventoryCategory, pk=pk, organization=org)

    if request.method == 'POST':
        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted.')
        return redirect('inventory:category_list')

    return render(request, 'inventory/category_confirm_delete.html', {'category': category})


@login_required
def location_list(request):
    """List all inventory locations."""
    org = get_request_organization(request)
    locations = InventoryLocation.objects.for_organization(org).prefetch_related('items') if org else InventoryLocation.objects.none()

    return render(request, 'inventory/location_list.html', {
        'locations': locations,
    })


@login_required
@require_write
def location_create(request):
    """Create a new inventory location."""
    org = get_request_organization(request)
    if request.method == 'POST':
        form = InventoryLocationForm(request.POST)
        if form.is_valid():
            location = form.save(commit=False)
            location.organization = org
            location.save()
            messages.success(request, f'Location "{location.name}" created.')
            return redirect('inventory:location_list')
    else:
        form = InventoryLocationForm()

    return render(request, 'inventory/location_form.html', {
        'form': form,
        'title': 'Add Location',
    })


@login_required
@require_write
def location_edit(request, pk):
    """Edit an existing location."""
    org = get_request_organization(request)
    location = get_object_or_404(InventoryLocation, pk=pk, organization=org)

    if request.method == 'POST':
        form = InventoryLocationForm(request.POST, instance=location)
        if form.is_valid():
            form.save()
            messages.success(request, f'Location "{location.name}" updated.')
            return redirect('inventory:location_list')
    else:
        form = InventoryLocationForm(instance=location)

    return render(request, 'inventory/location_form.html', {
        'form': form,
        'location': location,
        'title': f'Edit: {location.name}',
    })


@login_required
@require_admin
def location_delete(request, pk):
    """Delete a location."""
    org = get_request_organization(request)
    location = get_object_or_404(InventoryLocation, pk=pk, organization=org)

    if request.method == 'POST':
        name = location.name
        location.delete()
        messages.success(request, f'Location "{name}" deleted.')
        return redirect('inventory:location_list')

    return render(request, 'inventory/location_confirm_delete.html', {'location': location})


@login_required
def transaction_list(request):
    """List all transactions for this organization, paginated."""
    org = get_request_organization(request)
    item_ids = InventoryItem.objects.for_organization(org).values_list('id', flat=True) if org else []
    transactions = InventoryTransaction.objects.filter(
        item_id__in=item_ids
    ).select_related('item', 'performed_by').order_by('-created_at')

    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'inventory/transaction_list.html', {
        'page_obj': page_obj,
        'transactions': page_obj,
    })


@login_required
def low_stock_report(request):
    """Report of items at or below minimum quantity."""
    org = get_request_organization(request)
    all_items = InventoryItem.objects.for_organization(org).select_related(
        'category', 'storage_location'
    ) if org else InventoryItem.objects.none()
    low_stock_items = [item for item in all_items if item.is_low_stock]

    return render(request, 'inventory/low_stock.html', {
        'items': low_stock_items,
    })


# ---------------------------------------------------------------------------
# Phase 46 (v3.17.532) — tool catalogue
# ---------------------------------------------------------------------------

@login_required
def tool_list(request):
    """Durable equipment, separate from consumable stock."""
    org = get_request_organization(request)
    tools = (Tool.objects.for_organization(org)
             .select_related('category', 'home_location', 'assigned_vehicle')
             if org else Tool.objects.none())

    query = (request.GET.get('q') or '').strip()
    if query:
        tools = tools.filter(Q(name__icontains=query) | Q(code__icontains=query))
    if request.GET.get('show') != 'all':
        tools = tools.filter(is_active=True)

    return render(request, 'inventory/tool_list.html', {
        'tools': tools,
        'query': query,
        'showing_all': request.GET.get('show') == 'all',
    })


@login_required
@require_write
def tool_create(request):
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Select an organization first.')
        return redirect('inventory:tool_list')

    if request.method == 'POST':
        form = ToolForm(request.POST, organization=org)
        if form.is_valid():
            tool = form.save(commit=False)
            tool.organization = org
            tool.save()
            messages.success(request, f'Added {tool}.')
            return redirect('inventory:tool_list')
    else:
        form = ToolForm(organization=org)

    return render(request, 'inventory/tool_form.html',
                  {'form': form, 'title': 'Add tool'})


@login_required
@require_write
def tool_edit(request, pk):
    org = get_request_organization(request)
    tool = get_object_or_404(Tool.objects.for_organization(org), pk=pk)

    if request.method == 'POST':
        form = ToolForm(request.POST, instance=tool, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'Updated {tool}.')
            return redirect('inventory:tool_list')
    else:
        form = ToolForm(instance=tool, organization=org)

    return render(request, 'inventory/tool_form.html',
                  {'form': form, 'title': f'Edit {tool}', 'tool': tool})


@login_required
@require_admin
def tool_delete(request, pk):
    """Delete a tool outright.

    Retiring (is_active=False) is usually what is wanted — it keeps the tool off
    pick-lists without breaking the kit lines that reference it, which are
    SET_NULL and carry their own copy of the label.
    """
    org = get_request_organization(request)
    tool = get_object_or_404(Tool.objects.for_organization(org), pk=pk)
    if request.method == 'POST':
        name = str(tool)
        tool.delete()
        messages.success(request, f'Deleted {name}.')
        return redirect('inventory:tool_list')
    return render(request, 'inventory/tool_confirm_delete.html', {'tool': tool})
