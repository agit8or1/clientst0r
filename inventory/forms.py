"""
Inventory forms
"""
from django import forms
from .models import (
    InventoryCategory, InventoryItem, InventoryLocation, InventoryTransaction, Tool,
)


class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = [
            'name', 'sku', 'manufacturer_part_number', 'item_type',
            'category', 'storage_location', 'description', 'notes',
            'quantity', 'unit', 'min_quantity', 'reorder_quantity',
            'reorder_link', 'unit_cost',
        ]

    def __init__(self, *args, **kwargs):
        org = kwargs.pop('org', None)
        super().__init__(*args, **kwargs)
        if org:
            self.fields['category'].queryset = InventoryCategory.objects.for_organization(org)
            self.fields['storage_location'].queryset = InventoryLocation.objects.for_organization(org)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class InventoryAdjustForm(forms.Form):
    transaction_type = forms.ChoiceField(choices=InventoryTransaction.TRANSACTION_TYPES)
    quantity_change = forms.IntegerField(
        help_text='Use positive number to add stock, negative to remove.'
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False
    )
    reference = forms.CharField(max_length=255, required=False, help_text='Reference number, ticket, PO, etc.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class InventoryCategoryForm(forms.ModelForm):
    class Meta:
        model = InventoryCategory
        fields = ['name', 'description', 'color']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class InventoryLocationForm(forms.ModelForm):
    class Meta:
        model = InventoryLocation
        fields = ['name', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class ToolForm(forms.ModelForm):
    """Phase 46 (v3.17.532): durable equipment catalogue."""

    class Meta:
        model = Tool
        fields = ['name', 'code', 'category', 'description', 'home_location',
                  'assigned_vehicle', 'condition', 'is_active', 'notes']

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Scope the pickers to this tenant. Left unfiltered, the dropdowns would
        # offer every other customer's categories, shelves and vans.
        if organization is not None:
            self.fields['category'].queryset = (
                InventoryCategory.objects.for_organization(organization))
            self.fields['home_location'].queryset = (
                InventoryLocation.objects.for_organization(organization))
            # ServiceVehicle has no is_active field — `status` carries it, and
            # the fleet is not per-tenant (see v3.17.477), so it is not scoped.
            from vehicles.models import ServiceVehicle
            self.fields['assigned_vehicle'].queryset = (
                ServiceVehicle.objects.filter(status='active'))

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'
