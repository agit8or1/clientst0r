"""
Processes forms
"""
from django import forms
from django.forms import inlineformset_factory
from .models import Process, ProcessStage, ProcessExecution, ProcessStageCompletion


class ProcessForm(forms.ModelForm):
    class Meta:
        model = Process
        fields = ['title', 'description', 'category', 'tags', 'is_published', 'is_template', 'linked_diagram']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Process Title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Describe this process...'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_template': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'linked_diagram': forms.Select(attrs={'class': 'form-select'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }
        help_texts = {
            'is_published': 'Make this process visible to users',
            'is_template': 'Make this a reusable template that can be cloned',
            'linked_diagram': 'Optional: Link to a diagram for visual representation',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()
            # Filter diagrams by organization
            from docs.models import Diagram
            self.fields['linked_diagram'].queryset = Diagram.objects.filter(
                organization=self.organization
            ).order_by('title')
            self.fields['linked_diagram'].required = False


class ProcessStageForm(forms.ModelForm):
    class Meta:
        model = ProcessStage
        fields = [
            'order', 'title', 'description', 'requires_confirmation',
            'estimated_duration_minutes', 'linked_document', 'linked_password',
            'linked_secure_note', 'linked_asset'
        ]
        widgets = {
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Stage title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Detailed instructions for this stage...'}),
            'requires_confirmation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'estimated_duration_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Minutes'}),
            'linked_document': forms.Select(attrs={'class': 'form-select entity-link'}),
            'linked_password': forms.Select(attrs={'class': 'form-select entity-link'}),
            'linked_secure_note': forms.Select(attrs={'class': 'form-select entity-link'}),
            'linked_asset': forms.Select(attrs={'class': 'form-select entity-link'}),
        }
        help_texts = {
            'order': 'Stage order (lower numbers appear first)',
            'requires_confirmation': 'Users must confirm completion of this stage',
            'estimated_duration_minutes': 'Estimated time to complete this stage',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            # Filter linked entities by organization
            from docs.models import Document
            from vault.models import Password
            from core.models import SecureNote
            from assets.models import Asset

            self.fields['linked_document'].queryset = Document.objects.filter(
                organization=self.organization,
                is_published=True
            ).order_by('title')
            self.fields['linked_document'].required = False

            self.fields['linked_password'].queryset = Password.objects.filter(
                organization=self.organization
            ).order_by('title')
            self.fields['linked_password'].required = False

            self.fields['linked_secure_note'].queryset = SecureNote.objects.filter(
                organization=self.organization
            ).order_by('title')
            self.fields['linked_secure_note'].required = False

            self.fields['linked_asset'].queryset = Asset.objects.filter(
                organization=self.organization
            ).order_by('name')
            self.fields['linked_asset'].required = False

    def clean(self):
        cleaned_data = super().clean()

        # Validate that only ONE entity is linked
        linked_count = sum([
            bool(cleaned_data.get('linked_document')),
            bool(cleaned_data.get('linked_password')),
            bool(cleaned_data.get('linked_secure_note')),
            bool(cleaned_data.get('linked_asset')),
        ])

        if linked_count > 1:
            raise forms.ValidationError(
                "A stage can only link to ONE entity at a time. "
                "Please select only one of: Document, Password, Secure Note, or Asset."
            )

        return cleaned_data


# Inline formset for managing stages within a process
ProcessStageFormSet = inlineformset_factory(
    Process,
    ProcessStage,
    form=ProcessStageForm,
    extra=1,
    can_delete=True,
    can_order=False,
)


class ProcessExecutionForm(forms.ModelForm):
    class Meta:
        model = ProcessExecution
        fields = ['due_date', 'notes', 'psa_ticket', 'psa_note_internal']
        widgets = {
            'due_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Execution notes...'}),
            'psa_ticket': forms.Select(attrs={'class': 'form-select'}),
            'psa_note_internal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'due_date': 'Optional deadline for completion',
            'psa_ticket': 'Optional: Link to PSA ticket (updates ticket when workflow completes)',
            'psa_note_internal': 'Make PSA ticket note internal/private (not visible to customer)',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            # Filter PSA tickets by organization and open status
            from integrations.models import PSATicket
            self.fields['psa_ticket'].queryset = PSATicket.objects.filter(
                connection__organization=self.organization,
                status__in=['open', 'in_progress']
            ).select_related('connection').order_by('-created_at')[:100]  # Limit to 100 recent tickets
            self.fields['psa_ticket'].label_from_instance = lambda obj: f"[{obj.connection.provider}] {obj.ticket_number} - {obj.subject[:50]}"
            self.fields['psa_ticket'].required = False


class ProcessStageCompletionForm(forms.ModelForm):
    class Meta:
        model = ProcessStageCompletion
        fields = ['is_completed', 'notes']
        widgets = {
            'is_completed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Notes about this stage...'}),
        }
