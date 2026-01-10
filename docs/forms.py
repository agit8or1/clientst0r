"""
Docs forms
"""
from django import forms
from .models import Document, DocumentCategory, Diagram


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'slug', 'body', 'content_type', 'category', 'is_published', 'is_template', 'is_archived', 'tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Document Title'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'document-slug'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 20, 'id': 'document-body'}),
            'content_type': forms.Select(attrs={'class': 'form-select', 'id': 'content-type-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_template': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_archived': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }
        help_texts = {
            'slug': 'URL-friendly identifier (auto-generated if empty)',
            'content_type': 'Choose HTML for WYSIWYG editor or Markdown',
            'is_template': 'Make this a reusable template',
            'is_archived': 'Archive this document (hidden from main list)',
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization:
            self.fields['tags'].queryset = self.organization.tags.all()
            self.fields['category'].queryset = DocumentCategory.objects.filter(organization=self.organization)
            self.fields['category'].required = False


class DiagramForm(forms.ModelForm):
    class Meta:
        model = Diagram
        fields = ['title', 'slug', 'description', 'diagram_type', 'is_published', 'is_template', 'tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Diagram Title'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'diagram-slug'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description of this diagram'}),
            'diagram_type': forms.Select(attrs={'class': 'form-select'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_template': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }
        help_texts = {
            'slug': 'URL-friendly identifier (auto-generated if empty)',
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
        fields = ['name', 'slug', 'description', 'parent', 'icon', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category Name'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'category-slug'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brief description'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'fa-folder'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
        }
        help_texts = {
            'slug': 'URL-friendly identifier (auto-generated if empty)',
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
