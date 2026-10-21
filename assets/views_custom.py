"""
Custom asset fields and custom asset types (v3.17.621).

Both apply to every customer, like the equipment catalog, so only MSP staff
who may edit assets everywhere manage them (`can_manage_asset_catalog`).
"""
from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from audit.models import AuditLog

from .custom_types import builtin_type_codes
from .models import Asset, AssetCustomField, AssetType


def can_manage_asset_catalog(user):
    """Superusers, and MSP staff with `assets_edit` for every customer."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from accounts.permission_utils import orgs_with_perm
    from docs.permissions import _django_staff_without_role
    from psa.visibility import is_msp_staff
    if not is_msp_staff(user):
        return False
    return _django_staff_without_role(user) or orgs_with_perm(user, 'assets_edit') is None


def require_catalog_manager(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not can_manage_asset_catalog(request.user):
            raise PermissionDenied('Only MSP staff who can edit assets for every customer may change this.')
        return view(request, *args, **kwargs)
    return wrapper


def _audit(request, action, obj, description):
    AuditLog.log(
        user=request.user, action=action, object_type=obj.__class__.__name__,
        object_id=obj.pk, object_repr=str(obj), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', ''), path=request.path,
    )


# ----- forms -------------------------------------------------------------------

class AssetCustomFieldForm(forms.ModelForm):
    asset_types = forms.MultipleChoiceField(
        required=False, label='Asset types',
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '10'}),
        help_text='Leave empty to show the field on every asset type.')

    class Meta:
        model = AssetCustomField
        fields = ['label', 'key', 'field_type', 'choices', 'help_text', 'is_required',
                  'asset_types', 'order', 'is_active']
        widgets = {
            'label': forms.TextInput(attrs={'class': 'form-control'}),
            'key': forms.TextInput(attrs={'class': 'form-control'}),
            'field_type': forms.Select(attrs={'class': 'form-select'}),
            'choices': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'help_text': forms.TextInput(attrs={'class': 'form-control'}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .custom_types import asset_type_choices
        self.fields['asset_types'].choices = asset_type_choices()
        self.fields['key'].required = False
        self.fields['key'].help_text = ('Stored name of the value, e.g. "budget_code". Leave empty to '
                                        'make one from the label. Changing it later hides values '
                                        'saved under the old key.')
        if self.instance.pk:
            self.initial['asset_types'] = self.instance.asset_types

    def clean_key(self):
        key = slugify(self.cleaned_data.get('key') or self.cleaned_data.get('label') or '').replace('-', '_')
        if not key:
            raise forms.ValidationError('Enter a key or a label.')
        if AssetCustomField.objects.filter(key=key).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Another custom field already uses this key.')
        return key

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('field_type') == 'dropdown' and not [
                line for line in (cleaned.get('choices') or '').splitlines() if line.strip()]:
            self.add_error('choices', 'A dropdown needs at least one option.')
        return cleaned


class AssetTypeForm(forms.ModelForm):
    class Meta:
        model = AssetType
        fields = ['name', 'slug', 'icon', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'slug': forms.TextInput(attrs={'class': 'form-control'}),
            'icon': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].label = 'Code'
        if self.instance.pk:
            # Assets store the code; changing it would orphan them.
            self.fields['slug'].disabled = True
            self.fields['slug'].help_text = 'Assets store this code, so it cannot change.'
        else:
            self.fields['slug'].help_text = 'Stored on each asset. Leave empty to make one from the name.'

    def clean_slug(self):
        if self.instance.pk:
            return self.instance.slug
        slug = slugify(self.cleaned_data.get('slug') or self.cleaned_data.get('name') or '').replace('-', '_')[:50]
        if not slug:
            raise forms.ValidationError('Enter a code or a name.')
        if slug in builtin_type_codes():
            raise forms.ValidationError('That code belongs to a built-in asset type.')
        if AssetType.objects.filter(organization__isnull=True, slug=slug).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Another custom asset type already uses this code.')
        return slug


# ----- custom fields -----------------------------------------------------------

@login_required
@require_catalog_manager
def custom_field_list(request):
    from .custom_types import asset_type_label
    fields = list(AssetCustomField.objects.all())
    for f in fields:
        f.type_labels = [asset_type_label(code) for code in f.asset_types]
    return render(request, 'assets/custom_field_list.html', {
        'fields': fields,
        'custom_types': AssetType.objects.filter(organization__isnull=True).order_by('name'),
    })


@login_required
@require_catalog_manager
def custom_field_form(request, pk=None):
    instance = get_object_or_404(AssetCustomField, pk=pk) if pk else None
    form = AssetCustomFieldForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.asset_types = form.cleaned_data['asset_types']
        if not instance:
            obj.created_by = request.user
        obj.save()
        _audit(request, 'update' if instance else 'create', obj,
               f"{'Updated' if instance else 'Created'} asset custom field '{obj.label}'")
        messages.success(request, f"Custom field '{obj.label}' saved.")
        return redirect('assets:custom_field_list')
    return render(request, 'assets/custom_field_form.html', {'form': form, 'instance': instance})


@login_required
@require_catalog_manager
@require_POST
def custom_field_delete(request, pk):
    obj = get_object_or_404(AssetCustomField, pk=pk)
    _audit(request, 'delete', obj, f"Deleted asset custom field '{obj.label}' (stored values kept)")
    obj.delete()
    messages.success(request, f"Custom field '{obj.label}' deleted. Values already saved on assets are kept.")
    return redirect('assets:custom_field_list')


# ----- custom asset types ------------------------------------------------------

@login_required
@require_catalog_manager
def asset_type_form(request, pk=None):
    instance = get_object_or_404(AssetType, pk=pk, organization__isnull=True) if pk else None
    form = AssetTypeForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if not instance:
            obj.organization = None
            obj.created_by = request.user
        obj.save()
        cache.delete('asset_custom_type_icons')
        _audit(request, 'update' if instance else 'create', obj,
               f"{'Updated' if instance else 'Created'} custom asset type '{obj.name}'")
        messages.success(request, f"Asset type '{obj.name}' saved.")
        return redirect('assets:custom_field_list')
    in_use = Asset.objects.filter(asset_type=instance.slug).count() if instance else 0
    return render(request, 'assets/asset_type_form.html', {
        'form': form, 'instance': instance, 'in_use': in_use})


@login_required
@require_catalog_manager
@require_POST
def asset_type_delete(request, pk):
    obj = get_object_or_404(AssetType, pk=pk, organization__isnull=True)
    in_use = Asset.objects.filter(asset_type=obj.slug).count()
    if in_use:
        messages.error(request, f"'{obj.name}' is used by {in_use} asset(s). "
                                "Mark it inactive instead, or change those assets' type first.")
        return redirect('assets:asset_type_edit', pk=obj.pk)
    _audit(request, 'delete', obj, f"Deleted custom asset type '{obj.name}'")
    obj.delete()
    cache.delete('asset_custom_type_icons')
    messages.success(request, f"Asset type '{obj.name}' deleted.")
    return redirect('assets:custom_field_list')
