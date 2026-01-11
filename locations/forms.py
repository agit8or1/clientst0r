"""
Forms for locations app
"""
from django import forms
from .models import Location, LocationFloorPlan
from core.models import Organization


class LocationForm(forms.ModelForm):
    """Form for creating/editing locations."""

    auto_geocode = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Automatically geocode address to get GPS coordinates"
    )
    fetch_property_data = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Fetch building information from property records"
    )
    fetch_satellite_image = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Download satellite imagery of the building"
    )

    class Meta:
        model = Location
        fields = [
            'name', 'location_type', 'is_shared', 'associated_organizations', 'is_primary', 'status',
            'street_address', 'street_address_2', 'city', 'state', 'postal_code', 'country',
            'phone', 'email', 'website',
            'building_sqft', 'floors_count', 'year_built', 'property_type',
            'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'location_type': forms.Select(attrs={'class': 'form-control'}),
            'is_shared': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'associated_organizations': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'street_address': forms.TextInput(attrs={'class': 'form-control'}),
            'street_address_2': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'building_sqft': forms.NumberInput(attrs={'class': 'form-control'}),
            'floors_count': forms.NumberInput(attrs={'class': 'form-control'}),
            'year_built': forms.NumberInput(attrs={'class': 'form-control'}),
            'property_type': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        help_texts = {
            'is_shared': 'Check if this is a shared location (e.g., data center, co-location) that multiple organizations can use',
            'associated_organizations': 'Organizations that have access to this shared location (only if shared)',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes to extra fields
        self.fields['auto_geocode'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['fetch_property_data'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['fetch_satellite_image'].widget.attrs.update({'class': 'form-check-input'})


class LocationFloorPlanForm(forms.ModelForm):
    """Form for creating/editing floor plans."""

    class Meta:
        model = LocationFloorPlan
        fields = [
            'floor_number', 'floor_name',
            'width_feet', 'length_feet', 'ceiling_height_feet',
            'source', 'include_network', 'include_furniture'
        ]
        widgets = {
            'floor_number': forms.NumberInput(attrs={'class': 'form-control'}),
            'floor_name': forms.TextInput(attrs={'class': 'form-control'}),
            'width_feet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'length_feet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'ceiling_height_feet': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'source': forms.Select(attrs={'class': 'form-control'}),
            'include_network': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'include_furniture': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
