"""
Docs forms
"""
from django import forms
from .models import Document, DocumentCategory, Diagram


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'body', 'content_type', 'file', 'category', 'is_published', 'is_template', 'is_archived', 'tags',
                  'owner', 'review_interval_days', 'requires_approval']
        widgets = {
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'review_interval_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'requires_approval': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Document Title'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 20, 'id': 'document-body', 'data-required': 'true'}),
            'content_type': forms.Select(attrs={'class': 'form-select', 'id': 'content-type-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control', 'id': 'document-file', 'accept': '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.jpg,.jpeg,.png,.gif,.svg,.zip,.bmp,.webp'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_template': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_archived': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }
        help_texts = {
            'content_type': '📄 HTML for rich text editor | 📝 Markdown for code/text | 📎 Uploaded File for PDFs, images, Office docs',
            'file': 'Upload PDF, Word, Excel, images, or other files (max 50MB)',
            'is_template': 'Make this a reusable template',
            'is_archived': 'Archive this document (hidden from main list)',
            'owner': 'Responsible for keeping this document current; receives review reminders.',
            'review_interval_days': 'Days between reviews. 0 turns review reminders off.',
            'requires_approval': 'Every edit takes the document offline until it is submitted for review and approved.',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        # When creating a global KB article we want the category dropdown to
        # also list global (NULL-org) categories — pass include_global_categories=True.
        self.include_global_categories = kwargs.pop('include_global_categories', False)
        # Publishing controls (the Published and Requires-approval boxes) are
        # only offered to users who may publish; without them the view decides
        # the state (docs.permissions.apply_publish_rules).
        self.can_publish = kwargs.pop('can_publish', True)
        # Owner choices: MSP staff plus members of this organization. Global
        # KB articles pass global_article=True (staff only).
        owner_org = kwargs.pop('owner_organization', None)
        global_article = kwargs.pop('global_article', False)
        super().__init__(*args, **kwargs)

        if not self.can_publish:
            self.fields.pop('is_published', None)
            self.fields.pop('requires_approval', None)

        from django.db.models import Q
        from .permissions import eligible_owners
        owners = eligible_owners(owner_org if owner_org is not None else self.organization,
                                 include_org_members=not global_article)
        current_owner_id = getattr(self.instance, 'owner_id', None)
        if current_owner_id:
            # Keep a former member who still owns the document selectable so
            # unrelated edits don't fail validation.
            from django.contrib.auth.models import User
            owners = User.objects.filter(
                Q(pk__in=owners.values('pk')) | Q(pk=current_owner_id)).order_by('username')
        self.fields['owner'].queryset = owners
        self.fields['owner'].required = False
        self.fields['owner'].label_from_instance = (
            lambda u: f'{u.get_full_name()} ({u.username})' if u.get_full_name() else u.username)
        self.fields['review_interval_days'].required = False

    def clean_owner(self):
        # A document always has someone responsible: leaving the box empty
        # keeps the current owner (new documents default to their creator).
        owner = self.cleaned_data.get('owner')
        if owner is None and self.instance.pk:
            return self.instance.owner
        return owner

    def clean_review_interval_days(self):
        value = self.cleaned_data.get('review_interval_days')
        if value is None:
            return self.instance.review_interval_days if self.instance.pk else 90
        return value

        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()
            from django.db.models import Q
            cat_q = Q(organization=self.organization)
            if self.include_global_categories:
                cat_q |= Q(organization__isnull=True)
            self.fields['category'].queryset = DocumentCategory.objects.filter(cat_q).order_by('order', 'name')
            self.fields['category'].required = False


class DiagramForm(forms.ModelForm):
    class Meta:
        model = Diagram
        fields = ['title', 'description', 'diagram_type', 'is_published', 'is_template', 'tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Diagram Title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description of this diagram'}),
            'diagram_type': forms.Select(attrs={'class': 'form-select'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_template': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }
        help_texts = {
            'is_template': 'Make this a reusable template',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()


class DocumentCategoryForm(forms.ModelForm):
    class Meta:
        model = DocumentCategory
        fields = ['name', 'description', 'parent', 'icon', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'fa-folder'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
        }
        help_texts = {
            'icon': 'FontAwesome icon name (e.g., fa-folder, fa-book)',
            'order': 'Sort order (lower numbers appear first)',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            # Only show categories from same organization for parent selection
            self.fields['parent'].queryset = DocumentCategory.objects.filter(organization=self.organization)
            self.fields['parent'].required = False
