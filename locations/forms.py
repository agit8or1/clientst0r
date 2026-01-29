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
            'property_diagram',
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
            'property_diagram': forms.ClearableFileInput(attrs={'class': 'form-control'}),
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


class SendNavigationLinkForm(forms.Form):
    """Form for sending location navigation links via email or SMS."""

    METHOD_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('both', 'Both Email and SMS'),
    ]

    MAP_SERVICE_CHOICES = [
        ('google_maps', 'Google Maps'),
        ('google_maps_navigate', 'Google Maps (Navigation)'),
        ('apple_maps', 'Apple Maps'),
        ('waze', 'Waze'),
        ('all', 'All Services'),
    ]

    method = forms.ChoiceField(
        choices=METHOD_CHOICES,
        initial='email',
        widget=forms.RadioSelect,
        label='Send via'
    )

    map_service = forms.ChoiceField(
        choices=MAP_SERVICE_CHOICES,
        initial='google_maps_navigate',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Map Service'
    )

    recipient_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'recipient@example.com'
        }),
        label='Email Address'
    )

    recipient_phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+15551234567',
            'pattern': r'\+[0-9]{1,15}'
        }),
        label='Phone Number (E.164 format)',
        help_text='Must start with + and country code (e.g., +15551234567 for US)'
    )

    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional custom message...'
        }),
        label='Custom Message (Optional)'
    )

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        recipient_email = cleaned_data.get('recipient_email')
        recipient_phone = cleaned_data.get('recipient_phone')

        # Validate that appropriate fields are filled based on method
        if method in ['email', 'both']:
            if not recipient_email:
                self.add_error('recipient_email', 'Email address is required for email delivery')

        if method in ['sms', 'both']:
            if not recipient_phone:
                self.add_error('recipient_phone', 'Phone number is required for SMS delivery')
            elif not recipient_phone.startswith('+'):
                self.add_error('recipient_phone', 'Phone number must start with + and include country code')

        return cleaned_data

