"""
Docs forms
"""
from django import forms
from .models import Document, DocumentCategory


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
            'tags': forms.CheckboxSelectMultiple(),
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
