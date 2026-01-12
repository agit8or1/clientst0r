"""
Assets forms
"""
from django import forms
from .models import Asset, Contact, EquipmentModel, Vendor


class AssetForm(forms.ModelForm):
    # Add vendor selection field (not saved to model, just for UI)
    equipment_vendor = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="Select vendor (optional)",
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_equipment_vendor'}),
        label="Vendor"
    )

    class Meta:
        model = Asset
        fields = ['name', 'asset_type', 'asset_tag', 'serial_number',
                  'equipment_model', 'manufacturer', 'model',
                  'hostname', 'ip_address', 'mac_address',
                  'is_rackmount', 'rack_units',
                  'port_count',
                  'primary_contact', 'tags', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'asset_type': forms.Select(attrs={'class': 'form-control'}),
            'asset_tag': forms.TextInput(attrs={'class': 'form-control'}),
            'serial_number': forms.TextInput(attrs={'class': 'form-control'}),
            'equipment_model': forms.Select(attrs={'class': 'form-control', 'id': 'id_equipment_model'}),
            'manufacturer': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_manufacturer'}),
            'model': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_model'}),
            'hostname': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'server01.example.com'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '192.168.1.100'}),
            'mac_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '00:11:22:33:44:55'}),
            'is_rackmount': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_rackmount'}),
            'rack_units': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '42', 'id': 'id_rack_units'}),
            'port_count': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '256', 'id': 'id_port_count', 'placeholder': 'e.g., 24, 48'}),
            'primary_contact': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()
            self.fields['primary_contact'].queryset = Contact.objects.for_organization(self.organization)

        # Populate vendor dropdown
        from .models import Vendor
        self.fields['equipment_vendor'].queryset = Vendor.objects.filter(is_active=True).order_by('name')
        self.fields['equipment_vendor'].help_text = "Select vendor to see available models"

        # Equipment model dropdown handling
        # If this is a POST request (args[0] exists), allow all active models for validation
        # Otherwise, start with empty queryset (populated by JavaScript)
        if args and args[0]:  # POST data present
            self.fields['equipment_model'].queryset = EquipmentModel.objects.filter(is_active=True)
        else:
            self.fields['equipment_model'].queryset = EquipmentModel.objects.none()

        self.fields['equipment_model'].empty_label = "First select a vendor"
        self.fields['equipment_model'].required = False
        self.fields['equipment_model'].help_text = "Select model to auto-fill manufacturer/model fields"

        # If editing existing asset with equipment_model, pre-populate vendor and model dropdown
        if self.instance and self.instance.pk and self.instance.equipment_model:
            self.fields['equipment_vendor'].initial = self.instance.equipment_model.vendor
            self.fields['equipment_model'].queryset = EquipmentModel.objects.filter(
                vendor=self.instance.equipment_model.vendor,
                is_active=True
            )

        # Add help text
        self.fields['manufacturer'].help_text = "Auto-filled when model is selected, or enter manually"
        self.fields['model'].help_text = "Auto-filled when model is selected, or enter manually"
        self.fields['port_count'].help_text = "Number of network ports (for switches, routers, firewalls, patch panels)"
        self.fields['port_count'].required = False

    def clean(self):
        """Remove equipment_vendor from cleaned_data as it's just a UI helper."""
        cleaned_data = super().clean()
        # Remove equipment_vendor - it's just for UI, not saved to model
        cleaned_data.pop('equipment_vendor', None)
        return cleaned_data


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
        fields = ['name', 'asset_type', 'equipment_model', 'serial_number', 'manufacturer', 'model',
                  'hostname', 'ip_address', 'primary_contact', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'User Name - PC Model (e.g., John Doe - Dell Latitude)'
            }),
            'asset_type': forms.Select(attrs={'class': 'form-select'}),
            'equipment_model': forms.Select(attrs={'class': 'form-control', 'id': 'id_equipment_model'}),
            'serial_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Serial number or service tag'
            }),
            'manufacturer': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Dell, HP, Lenovo, etc.',
                'id': 'id_manufacturer'
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Latitude 7420, ThinkPad X1, etc.',
                'id': 'id_model'
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

        # Populate equipment model dropdown (filter to workstation/laptop types)
        equipment_models = EquipmentModel.objects.select_related('vendor').filter(
            is_active=True,
            equipment_type__in=['workstation', 'laptop']
        )
        self.fields['equipment_model'].queryset = equipment_models
        self.fields['equipment_model'].label_from_instance = lambda obj: f"{obj.vendor.name} {obj.model_name}"
        self.fields['equipment_model'].empty_label = "Select from catalog (optional)"
        self.fields['equipment_model'].required = False

        # Set default asset_type to desktop or laptop
        self.fields['asset_type'].initial = 'desktop'

        # Make some fields optional for quick entry
        self.fields['serial_number'].required = False
        self.fields['manufacturer'].required = False
        self.fields['model'].required = False
        self.fields['hostname'].required = False
        self.fields['ip_address'].required = False


class QuickServerForm(forms.ModelForm):
    """
    Quick form for creating a new server asset with essential fields only.
    """
    class Meta:
        model = Asset
        fields = ['name', 'asset_type', 'equipment_model', 'serial_number', 'manufacturer', 'model',
                  'hostname', 'ip_address', 'primary_contact', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., prod-web-01, dc-sql-server-01'
            }),
            'asset_type': forms.Select(attrs={'class': 'form-select'}),
            'equipment_model': forms.Select(attrs={'class': 'form-control', 'id': 'id_equipment_model'}),
            'serial_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Serial number or service tag'
            }),
            'manufacturer': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Dell, HPE, Lenovo, etc.',
                'id': 'id_manufacturer'
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'PowerEdge R740, ProLiant DL380, etc.',
                'id': 'id_model'
            }),
            'hostname': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'prod-web-01.company.com'
            }),
            'ip_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '10.0.1.10'
            }),
            'primary_contact': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Purpose, location, warranty info, etc.'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['primary_contact'].queryset = Contact.objects.for_organization(self.organization)

        # Populate equipment model dropdown (filter to server types)
        equipment_models = EquipmentModel.objects.select_related('vendor').filter(
            is_active=True,
            equipment_type='server'
        )
        self.fields['equipment_model'].queryset = equipment_models
        self.fields['equipment_model'].label_from_instance = lambda obj: f"{obj.vendor.name} {obj.model_name}"
        self.fields['equipment_model'].empty_label = "Select from catalog (optional)"
        self.fields['equipment_model'].required = False

        # Set default asset_type to server
        self.fields['asset_type'].initial = 'server'

        # Make some fields optional for quick entry
        self.fields['serial_number'].required = False
        self.fields['manufacturer'].required = False
        self.fields['model'].required = False
        self.fields['hostname'].required = False
        self.fields['ip_address'].required = False
        self.fields['primary_contact'].required = False
        self.fields['notes'].required = False


class VendorForm(forms.ModelForm):
    """
    Form for creating/editing hardware vendors.
    """
    class Meta:
        model = Vendor
        fields = ['name', 'slug', 'website', 'support_url', 'support_phone', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Dell, HP, Cisco, etc.'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'dell, hp, cisco (auto-generated)'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.vendor.com'}),
            'support_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://support.vendor.com'}),
            'support_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '1-800-555-1234'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description of vendor...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Auto-generate slug from name if not provided
        if not self.instance.pk:
            self.fields['slug'].required = False
            self.fields['slug'].help_text = "Leave blank to auto-generate from name"

    def clean_slug(self):
        """Auto-generate slug if not provided."""
        slug = self.cleaned_data.get('slug')
        if not slug:
            from django.utils.text import slugify
            name = self.cleaned_data.get('name', '')
            slug = slugify(name)
        return slug


class EquipmentModelForm(forms.ModelForm):
    """
    Form for creating/editing equipment models.
    """
    class Meta:
        model = EquipmentModel
        fields = [
            'vendor', 'model_name', 'model_number', 'slug', 'equipment_type', 'description',
            'is_rackmount', 'rack_units', 'datasheet_url', 'documentation_url',
            'release_date', 'eol_date', 'eos_date', 'is_active'
        ]
        widgets = {
            'vendor': forms.Select(attrs={'class': 'form-select'}),
            'model_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ProLiant DL380 Gen10'}),
            'model_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'P02462-B21'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'proliant-dl380-gen10 (auto-generated)'}),
            'equipment_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description...'}),
            'is_rackmount': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'rack_units': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1, 2, 4, etc.', 'min': 1}),
            'datasheet_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'documentation_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'release_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'eol_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'eos_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make optional fields
        self.fields['model_number'].required = False
        self.fields['slug'].required = False
        self.fields['slug'].help_text = "Leave blank to auto-generate from model name"
        self.fields['description'].required = False
        self.fields['rack_units'].required = False
        self.fields['datasheet_url'].required = False
        self.fields['documentation_url'].required = False
        self.fields['release_date'].required = False
        self.fields['eol_date'].required = False
        self.fields['eos_date'].required = False

    def clean_slug(self):
        """Auto-generate slug if not provided."""
        slug = self.cleaned_data.get('slug')
        if not slug:
            from django.utils.text import slugify
            model_name = self.cleaned_data.get('model_name', '')
            slug = slugify(model_name)
        return slug

    def clean(self):
        """Validate rack unit requirements."""
        cleaned_data = super().clean()
        is_rackmount = cleaned_data.get('is_rackmount')
        rack_units = cleaned_data.get('rack_units')

        if is_rackmount and not rack_units:
            self.add_error('rack_units', 'Rack units required for rackmount equipment')

        return cleaned_data
