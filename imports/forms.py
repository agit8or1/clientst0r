"""
Forms for IT Glue/Hudu import
"""
from django import forms
from .models import ImportJob


class ImportJobForm(forms.ModelForm):
    """Form for creating import jobs."""

    class Meta:
        model = ImportJob
        fields = [
            'source_type', 'source_url', 'source_api_key', 'source_file', 'target_organization',
            'target_location',
            'use_fuzzy_matching', 'fuzzy_match_threshold',
            'import_assets', 'import_passwords', 'import_documents',
            'import_contacts', 'import_locations', 'import_networks', 'import_floor_plans',
            'dry_run', 'skip_duplicates'
        ]
        widgets = {
            'source_type': forms.Select(attrs={'class': 'form-control'}),
            'source_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://api.itglue.com or https://your-hudu.com'}),
            'source_api_key': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Your API key'}),
            'source_file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.json,.csv,.tsv,.xlsx,.xlsm'}),
            'target_organization': forms.Select(attrs={'class': 'form-control', 'id': 'id_target_organization'}),
            'target_location': forms.Select(attrs={'class': 'form-control', 'id': 'id_target_location'}),
            'use_fuzzy_matching': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'fuzzy_match_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '100'}),
            'import_assets': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'import_passwords': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'import_documents': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'import_contacts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'import_locations': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'import_networks': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'import_floor_plans': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'dry_run': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'skip_duplicates': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'source_url': 'Full API URL (not needed for MagicPlan)',
            'source_api_key': 'API key for authentication (not needed for MagicPlan)',
            'source_file': 'Upload a MagicPlan JSON export, a CSV, or an .xlsx spreadsheet',
            'target_organization': 'Required for MagicPlan. Optional for IT Glue/Hudu (leave blank to import all organizations).',
            'target_location': 'Optional: Link floor plans to existing location. Leave blank to create new location from MagicPlan data.',
            'use_fuzzy_matching': 'Match existing organizations with similar names (e.g., "ABC LLC" matches "ABC Corporation")',
            'fuzzy_match_threshold': 'Similarity threshold (0-100, default 85). Higher = stricter matching.',
            'import_floor_plans': 'Import floor plans (MagicPlan only)',
            'dry_run': 'Preview import without saving data (recommended for first run)',
            'skip_duplicates': 'Skip items already imported in any previous completed job for this organization',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        # Make target_organization and target_location optional
        self.fields['target_organization'].required = False
        self.fields['target_location'].required = False

        # Filter organizations based on user permissions
        if user:
            if user.is_superuser or hasattr(user, 'is_staff_user') and user.is_staff_user:
                # Staff can see all organizations
                pass
            else:
                # Regular users only see their organizations
                self.fields['target_organization'].queryset = user.organizations.all()

        # Filter locations by organization
        from locations.models import Location
        if organization:
            self.fields['target_location'].queryset = Location.objects.filter(organization=organization)
        elif self.instance and self.instance.target_organization:
            self.fields['target_location'].queryset = Location.objects.filter(organization=self.instance.target_organization)
        else:
            # Show empty queryset until organization is selected
            self.fields['target_location'].queryset = Location.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        source_type = cleaned_data.get('source_type')
        source_url = cleaned_data.get('source_url', '')
        source_api_key = cleaned_data.get('source_api_key', '')
        source_file = cleaned_data.get('source_file')
        target_organization = cleaned_data.get('target_organization')

        # MagicPlan validation
        if source_type == 'magicplan':
            if not source_file:
                self.add_error('source_file', 'MagicPlan JSON file is required')
            if not target_organization:
                self.add_error('target_organization', 'Target organization is required for MagicPlan imports')

        # CSV validation
        elif source_type == 'csv':
            if not source_file:
                self.add_error('source_file', 'CSV file is required')
            if not target_organization:
                self.add_error('target_organization', 'Target organization is required for CSV imports')

        # IT Glue/Hudu validation
        elif source_type in ['itglue', 'hudu']:
            if not source_url:
                self.add_error('source_url', 'API URL is required')
            if not source_api_key:
                self.add_error('source_api_key', 'API key is required')

            # Validate URL matches source type
            if source_type == 'itglue' and 'itglue' not in source_url.lower():
                self.add_error('source_url', 'URL should contain "itglue" for IT Glue imports')
            elif source_type == 'hudu' and 'itglue' in source_url.lower():
                self.add_error('source_url', 'URL should not contain "itglue" for Hudu imports')

        return cleaned_data
