from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from assets.models import Asset
from core.models import Organization

from .models import DocumentationStandard, StandardException, StandardRequirement as R
from .params import FRESH_BASES, RELATIONSHIP_TARGET_KINDS, asset_field_choices, validate_params


class StandardForm(forms.ModelForm):
    org_type = forms.ChoiceField(
        label='Customer type', required=False,
        choices=[c for c in Organization.ORGANIZATION_TYPE_CHOICES if c[0]])
    asset_type = forms.ChoiceField(
        label='Asset type', required=False, choices=[('', '---------')] + list(Asset.ASSET_TYPES))

    class Meta:
        model = DocumentationStandard
        fields = ['name', 'description', 'scope', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst.pk:
            if inst.scope == DocumentationStandard.SCOPE_ORG_TYPE:
                self.fields['org_type'].initial = inst.scope_value
            elif inst.scope == DocumentationStandard.SCOPE_ASSET_TYPE:
                self.fields['asset_type'].initial = inst.scope_value

    def clean(self):
        data = super().clean()
        scope = data.get('scope')
        if scope == DocumentationStandard.SCOPE_ORG_TYPE:
            if not data.get('org_type'):
                self.add_error('org_type', 'Choose a customer type.')
            self.instance.scope_value = data.get('org_type') or ''
        elif scope == DocumentationStandard.SCOPE_ASSET_TYPE:
            if not data.get('asset_type'):
                self.add_error('asset_type', 'Choose an asset type.')
            self.instance.scope_value = data.get('asset_type') or ''
        else:
            self.instance.scope_value = ''
        return data


DOC_KINDS = ' '.join(R.DOCUMENT_KINDS)
ASSET_KINDS = f'{R.KIND_ASSET_FIELDS} {R.KIND_RELATIONSHIP_PRESENT}'

# param field name -> (kinds it applies to, params key)
PARAM_FIELDS = {
    'p_tag': (f'{DOC_KINDS} {R.KIND_CREDENTIAL_REFERENCE}', 'tag'),
    'p_category': (DOC_KINDS, 'category'),
    'p_title_contains': (f'{DOC_KINDS} {R.KIND_CONTACT_ROLE} {R.KIND_CREDENTIAL_REFERENCE}', 'title_contains'),
    'p_max_age_days': (R.KIND_DOCUMENT_FRESH, 'max_age_days'),
    'p_basis': (R.KIND_DOCUMENT_FRESH, 'basis'),
    'p_asset_type': (ASSET_KINDS, 'asset_type'),
    'p_fields': (R.KIND_ASSET_FIELDS, 'fields'),
    'p_min_count': (R.KIND_CONTACT_ROLE, 'min_count'),
    'p_target_kinds': (R.KIND_RELATIONSHIP_PRESENT, 'target_kinds'),
}


class RequirementForm(forms.ModelForm):
    p_tag = forms.CharField(label='Tag', required=False, max_length=100)
    p_category = forms.CharField(label='Document category', required=False, max_length=255)
    p_title_contains = forms.CharField(
        label='Title contains', required=False, max_length=255,
        help_text='Use | for alternatives, e.g. "recovery|disaster".')
    p_max_age_days = forms.IntegerField(label='Within days', required=False, min_value=1)
    p_basis = forms.ChoiceField(
        label='Counts as fresh', required=False,
        choices=[('reviewed_or_updated', 'Reviewed or updated'), ('reviewed', 'Marked reviewed only')])
    p_asset_type = forms.ChoiceField(
        label='Asset type', required=False,
        choices=[('', "Standard's asset type / all assets")] + list(Asset.ASSET_TYPES))
    p_fields = forms.MultipleChoiceField(
        label='Fields that must be filled in', required=False,
        widget=forms.SelectMultiple(attrs={'size': 6}))
    p_min_count = forms.IntegerField(label='At least', required=False, min_value=1)
    p_target_kinds = forms.MultipleChoiceField(
        label='Linked to', required=False,
        choices=[(k, k.capitalize()) for k in RELATIONSHIP_TARGET_KINDS],
        widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = R
        fields = ['title', 'kind', 'weight', 'description', 'order']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['p_fields'].choices = asset_field_choices()
        for name, (kinds, _) in PARAM_FIELDS.items():
            self.fields[name].widget.attrs['data-kinds'] = kinds
        params = self.instance.params or {}
        for name, (_, key) in PARAM_FIELDS.items():
            if key in params:
                self.fields[name].initial = params[key]
        if not self.instance.pk:
            self.fields['p_basis'].initial = FRESH_BASES[0]

    def param_fields(self):
        return [(self[name], kinds) for name, (kinds, _) in PARAM_FIELDS.items()]

    def clean(self):
        data = super().clean()
        kind = data.get('kind')
        if not kind or data.get('DELETE'):
            return data
        raw = {key: data.get(name) for name, (_, key) in PARAM_FIELDS.items()
               if data.get(name) not in (None, '', [])}
        try:
            self.instance.params = validate_params(kind, raw)
        except ValidationError as e:
            raise ValidationError(e.messages)
        return data


RequirementFormSet = inlineformset_factory(
    DocumentationStandard, R, form=RequirementForm, extra=1, can_delete=True)


class ExceptionForm(forms.ModelForm):
    expires_at = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='Leave blank for no expiry.')

    class Meta:
        model = StandardException
        fields = ['standard', 'requirement', 'reason', 'expires_at']
        widgets = {'reason': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['standard'].queryset = DocumentationStandard.objects.filter(is_active=True)
        self.fields['requirement'].queryset = R.objects.select_related('standard')
        self.fields['requirement'].required = False
        self.fields['requirement'].empty_label = 'Whole standard'
        self.fields['requirement'].label_from_instance = lambda r: f'{r.standard.name}: {r.title}'

    def clean(self):
        data = super().clean()
        std, req = data.get('standard'), data.get('requirement')
        if std and req and req.standard_id != std.pk:
            self.add_error('requirement', 'That requirement belongs to another standard.')
        if not (data.get('reason') or '').strip():
            self.add_error('reason', 'Say why this gap is accepted.')
        return data
