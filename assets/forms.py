"""
Assets forms
"""
from django import forms
from .models import Asset, Contact


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = ['name', 'asset_type', 'asset_tag', 'serial_number', 'manufacturer', 'model',
                  'hostname', 'ip_address', 'mac_address',
                  'primary_contact', 'tags', 'notes', 'custom_fields']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'asset_type': forms.Select(attrs={'class': 'form-control'}),
            'asset_tag': forms.TextInput(attrs={'class': 'form-control'}),
            'serial_number': forms.TextInput(attrs={'class': 'form-control'}),
            'manufacturer': forms.TextInput(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control'}),
            'hostname': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'server01.example.com'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.100'}),
            'mac_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '00:11:22:33:44:55'}),
            'primary_contact': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'custom_fields': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '{"key": "value"}'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()
            self.fields['primary_contact'].queryset = Contact.objects.for_organization(self.organization)


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['first_name', 'last_name', 'email', 'phone', 'title', 'notes']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class QuickPCForm(forms.ModelForm):
    """
    Quick form for creating a new PC/laptop asset with essential fields only.
    """
    class Meta:
        model = Asset
        fields = ['name', 'asset_type', 'serial_number', 'manufacturer', 'model',
                  'hostname', 'ip_address', 'primary_contact', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'User Name - PC Model (e.g., John Doe - Dell Latitude)'
            }),
            'asset_type': forms.Select(attrs={'class': 'form-select'}),
            'serial_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Serial number or service tag'
            }),
            'manufacturer': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Dell, HP, Lenovo, etc.'
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Latitude 7420, ThinkPad X1, etc.'
            }),
            'hostname': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'PC-JOHNDOE-01'
            }),
            'ip_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '192.168.1.100 (optional)'
            }),
            'primary_contact': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes (warranty info, purchase date, etc.)'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['primary_contact'].queryset = Contact.objects.for_organization(self.organization)

        # Set default asset_type to desktop or laptop
        self.fields['asset_type'].initial = 'desktop'

        # Make some fields optional for quick entry
        self.fields['serial_number'].required = False
        self.fields['manufacturer'].required = False
        self.fields['model'].required = False
        self.fields['hostname'].required = False
        self.fields['ip_address'].required = False
        self.fields['primary_contact'].required = False
        self.fields['notes'].required = False
