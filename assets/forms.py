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
                  'os_name', 'os_version',
                  'cpu', 'ram_gb', 'storage',
                  'is_rackmount', 'rack_units',
                  'port_count',
                  'purchase_date', 'lifespan_years', 'lifespan_reminder_enabled', 'lifespan_reminder_months',
                  'firmware_version', 'warranty_expiry', 'warranty_status',
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
            'os_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Windows Server 2022, Ubuntu 22.04, Cisco IOS 15.x'}),
            'os_version': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 22.04.3 LTS, Build 20348'}),
            'cpu': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Intel Xeon E5-2680 v4 @ 2.40GHz'}),
            'ram_gb': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'e.g., 32'}),
            'storage': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 2× 1TB SSD RAID-1'}),
            'is_rackmount': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_rackmount'}),
            'rack_units': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '42', 'id': 'id_rack_units'}),
            'port_count': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '256', 'id': 'id_port_count', 'placeholder': 'e.g., 24, 48'}),
            'purchase_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'lifespan_years': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '20', 'placeholder': 'e.g., 3, 5, 7'}),
            'lifespan_reminder_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_lifespan_reminder_enabled'}),
            'lifespan_reminder_months': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '24', 'placeholder': 'e.g., 3, 6, 12'}),
            'firmware_version': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 6.5.55, v8.4.59'}),
            'warranty_expiry': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'warranty_status': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., ProSupport Plus, Basic Warranty'}),
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
        else:
            # No organization assigned - set empty querysets to prevent errors
            from core.models import Tag
            self.fields['tags'].queryset = Tag.objects.none()
            self.fields['primary_contact'].queryset = Contact.objects.none()

        # Built-in plus custom asset types (v3.17.621).
        from .custom_types import FIELD_PREFIX, active_custom_fields, asset_type_choices, form_field_for
        self.fields['asset_type'].choices = asset_type_choices(
            include=self.instance.asset_type if self.instance and self.instance.pk else None)

        # Custom fields, filled from / saved to `custom_fields` (v3.17.621).
        self.custom_field_defs = active_custom_fields()
        stored = (self.instance.custom_fields or {}) if self.instance else {}
        for defn in self.custom_field_defs:
            name = FIELD_PREFIX + defn.key
            field = form_field_for(defn)
            field.widget.attrs['data-asset-types'] = ' '.join(defn.asset_types or [])
            if defn.is_required:
                field.widget.attrs['data-required'] = '1'
            self.fields[name] = field
            if defn.key in stored and not self.is_bound:
                self.initial[name] = stored[defn.key]

        # The equipment catalog: pick a manufacturer and model to fill in the
        # Manufacturer and Model fields below. It is a list of products, not
        # the reseller you bought from (discussion #132).
        from .models import Vendor
        self.fields['equipment_vendor'].queryset = Vendor.objects.filter(is_active=True).order_by('name')
        self.fields['equipment_vendor'].label = "Catalog manufacturer"
        self.fields['equipment_vendor'].empty_label = "Pick from the equipment catalog (optional)"
        self.fields['equipment_vendor'].help_text = (
            "Optional. Choose a manufacturer from the equipment catalog, then a model, "
            "to fill in Manufacturer and Model.")

        # Equipment model dropdown handling
        # If this is a POST request (args[0] exists), allow all active models for validation
        # Otherwise, start with empty queryset (populated by JavaScript)
        if args and args[0]:  # POST data present
            self.fields['equipment_model'].queryset = EquipmentModel.objects.filter(is_active=True)
        else:
            self.fields['equipment_model'].queryset = EquipmentModel.objects.none()

        self.fields['equipment_model'].empty_label = "First choose a catalog manufacturer"
        self.fields['equipment_model'].required = False
        self.fields['equipment_model'].label = "Catalog model"
        self.fields['equipment_model'].help_text = "Fills in Manufacturer and Model"

        # If editing existing asset with equipment_model, pre-populate vendor and model dropdown
        if self.instance and self.instance.pk and self.instance.equipment_model:
            self.fields['equipment_vendor'].initial = self.instance.equipment_model.vendor
            self.fields['equipment_model'].queryset = EquipmentModel.objects.filter(
                vendor=self.instance.equipment_model.vendor,
                is_active=True
            )

        # Add help text
        self.fields['manufacturer'].help_text = "Who makes it (e.g. Cisco, Dell). Filled in from the catalog, or type it."
        self.fields['model'].help_text = "Filled in from the catalog, or type it."
        self.fields['port_count'].help_text = "Number of network ports (for switches, routers, firewalls, patch panels)"
        self.fields['port_count'].required = False

        # Lifespan tracking help text
        self.fields['purchase_date'].help_text = "Date asset was purchased or deployed"
        self.fields['lifespan_years'].help_text = "Expected lifespan (Firewall: 5-7, Server: 3-5, Workstation: 3-4, Switch: 5-7)"
        self.fields['lifespan_reminder_enabled'].help_text = "Enable reminders before asset reaches end-of-life"
        self.fields['lifespan_reminder_months'].help_text = "How many months before EOL to start reminding"

        # Make lifespan fields optional
        self.fields['purchase_date'].required = False
        self.fields['lifespan_years'].required = False
        self.fields['lifespan_reminder_months'].required = False

    def clean(self):
        """Remove equipment_vendor from cleaned_data as it's just a UI helper."""
        cleaned_data = super().clean()
        # Remove equipment_vendor - it's just for UI, not saved to model
        cleaned_data.pop('equipment_vendor', None)
        from .custom_types import FIELD_PREFIX
        asset_type = cleaned_data.get('asset_type')
        for defn in self.custom_field_defs:
            name = FIELD_PREFIX + defn.key
            if (defn.is_required and defn.field_type != 'checkbox'
                    and defn.applies_to(asset_type)
                    and cleaned_data.get(name) in (None, '')
                    and name not in self.errors):
                self.add_error(name, 'This field is required for this asset type.')
        return cleaned_data

    def custom_field_rows(self):
        """Bound custom fields, in definition order, for the template."""
        from .custom_types import FIELD_PREFIX
        return [(defn, self[FIELD_PREFIX + defn.key]) for defn in self.custom_field_defs]

    def _apply_custom_fields(self, instance):
        """Write the custom field values into `custom_fields`. Fields that
        don't apply to the asset's type are left untouched, as are keys that
        no definition owns (imports and integrations write those)."""
        from .custom_types import FIELD_PREFIX, to_storage
        data = dict(instance.custom_fields or {})
        for defn in self.custom_field_defs:
            if not defn.applies_to(instance.asset_type):
                continue
            value = to_storage(defn, self.cleaned_data.get(FIELD_PREFIX + defn.key))
            if value is None:
                data.pop(defn.key, None)
            else:
                data[defn.key] = value
        instance.custom_fields = data

    def save(self, commit=True):
        instance = super().save(commit=False)
        self._apply_custom_fields(instance)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


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
