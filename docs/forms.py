"""
Docs forms
"""
from django import forms
from .models import CustomerGroup, Document, DocumentCategory, Diagram


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'body', 'content_type', 'file', 'category', 'is_published', 'is_template', 'is_archived', 'tags',
                  'owner', 'review_interval_days', 'requires_approval',
                  'is_client_visible', 'is_featured_in_portal']
        labels = {
            'is_client_visible': 'Visible in customer portal',
            'is_featured_in_portal': 'Featured in portal',
        }
        widgets = {
            'is_client_visible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured_in_portal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'review_interval_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'requires_approval': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Document Title'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 20, 'id': 'document-body', 'data-required': 'true'}),
            'content_type': forms.Select(attrs={'class': 'form-select', 'id': 'content-type-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control', 'id': 'document-file', 'accept': '.pdf,.doc,.docx,.xls,.xlsx,.csv,.ppt,.pptx,.txt,.jpg,.jpeg,.png,.gif,.svg,.zip,.bmp,.webp'}),
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
            'is_client_visible': 'External: customers can read it in the portal once it is live. Off = internal '
                                 'only. Keep technician-only notes inside an external article in a '
                                 '"kb-internal" block (Markdown: :::internal … :::).',
            'is_featured_in_portal': 'Pin to the top of the portal knowledge base.',
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
        # Offer "Global KB article" on customer documents to users who may
        # edit global KB articles (kb_edit_articles).
        can_make_global = kwargs.pop('can_make_global', False)
        # Global KB editor: "Global -- every customer" or one customer.
        scope_orgs = kwargs.pop('scope_orgs', None)
        super().__init__(*args, **kwargs)

        if scope_orgs is not None:
            self.fields['scope'] = forms.ChoiceField(
                label='Scope', required=False,
                initial='selected' if getattr(self.instance, 'audience', 'all') == 'selected' else 'global',
                choices=[('global', 'Global — every customer'),
                         ('selected', 'Selected customers and groups')]
                        + [(str(o.pk), f'Only {o.name}') for o in scope_orgs],
                help_text='Global articles are shared with every customer. "Selected" shares one '
                          'article with the customers and customer groups picked below. '
                          '"Only …" makes it one customer\'s own documentation.',
                widget=forms.Select(attrs={'class': 'form-select', 'id': 'kb-scope'}))
            self.fields['share_orgs'] = forms.ModelMultipleChoiceField(
                queryset=scope_orgs, required=False, label='Customers',
                initial=(self.instance.shared_with.all() if self.instance.pk else None),
                widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '6',
                                                   'data-kb-share': '1'}))
            self.fields['share_groups'] = forms.ModelMultipleChoiceField(
                queryset=CustomerGroup.objects.all(), required=False, label='Customer groups',
                initial=(self.instance.shared_with_groups.all() if self.instance.pk else None),
                widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '6',
                                                   'data-kb-share': '1'}))

        if can_make_global and not global_article and not getattr(self.instance, 'is_global', False):
            self.fields['make_global'] = forms.BooleanField(
                required=False, label='Global KB article (every customer)',
                help_text='Moves this article to the global knowledge base, shared with all customers.',
                widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

        if 'is_client_visible' in self.fields:
            if global_article or getattr(self.instance, 'is_global', False):
                self.fields['is_client_visible'].label = 'Show in every customer portal'
            else:
                self.fields['is_client_visible'].label = "Show in this customer's portal"
            self.fields['is_client_visible'].help_text = (
                'Off = staff only. Keep technician-only notes inside an external article in a '
                '"kb-internal" block (Markdown: :::internal … :::).')

        if not self.can_publish:
            self.fields.pop('is_published', None)
            self.fields.pop('requires_approval', None)
        # Customer-portal visibility is a publishing decision too. Forms that
        # do not render these boxes (no `kb_visibility_shown` marker) leave
        # the saved values alone instead of clearing them.
        if not self.can_publish or (self.is_bound and 'kb_visibility_shown' not in self.data):
            self.fields.pop('is_client_visible', None)
            self.fields.pop('is_featured_in_portal', None)

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

        # Tags and categories of this organization only. This block sat
        # unreachable after `clean_review_interval_days` since v3.17.605, which
        # left every customer's tags and categories selectable; a document
        # being edited keeps the ones it already has.
        if self.organization:
            from core.models import Tag
            tag_q = Q(organization=self.organization)
            cat_q = Q(organization=self.organization)
            if self.include_global_categories:
                cat_q |= Q(organization__isnull=True)
            if self.instance.pk:
                tag_q |= Q(pk__in=self.instance.tags.values('pk'))
                if self.instance.category_id:
                    cat_q |= Q(pk=self.instance.category_id)
            self.fields['tags'].queryset = Tag.objects.filter(tag_q).order_by('name')
            self.fields['category'].queryset = DocumentCategory.objects.filter(cat_q).order_by('order', 'name')
            self.fields['category'].required = False

    def clean_file(self):
        f = self.cleaned_data.get('file')
        # Only a newly uploaded file is checked; an existing stored file
        # (FieldFile, no content_type) is left as it is.
        if f and hasattr(f, 'content_type'):
            from .upload_check import check
            problem = check(f)
            if problem:
                raise forms.ValidationError(f'This file cannot be uploaded: {problem}.')
        return f

    def clean(self):
        data = super().clean()
        if data.get('scope') == 'selected' and not (data.get('share_orgs') or data.get('share_groups')):
            self.add_error('share_orgs', 'Pick at least one customer or customer group.')
        return data

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


class CustomerGroupForm(forms.ModelForm):
    class Meta:
        model = CustomerGroup
        fields = ['name', 'description', 'organizations']
        labels = {'organizations': 'Customers'}
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Microsoft 365 clients'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'organizations': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '12'}),
        }
