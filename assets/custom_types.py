"""
Custom asset types and custom fields (v3.17.621).

Built-in types are `Asset.ASSET_TYPES`. Custom types are active, MSP-wide
`AssetType` rows; an asset stores the type's slug in `asset_type`. Custom
fields are `AssetCustomField` rows whose values live in
`Asset.custom_fields[key]`.
"""
from django import forms


def builtin_type_codes():
    from assets.models import Asset
    return {code for code, _ in Asset.ASSET_TYPES}


def custom_asset_types():
    from assets.models import AssetType
    return AssetType.objects.filter(organization__isnull=True, is_active=True).order_by('name')


def is_custom_asset_type(code):
    if not code or code in builtin_type_codes():
        return False
    return custom_asset_types().filter(slug=code).exists()


def asset_type_choices(include=None):
    """Built-in and active custom types, sorted by label. `include` keeps an
    asset's current (possibly deactivated) custom type selectable."""
    from assets.models import Asset
    choices = dict(Asset.ASSET_TYPES)
    for t in custom_asset_types():
        choices.setdefault(t.slug, t.name)
    if include and include not in choices:
        choices[include] = asset_type_label(include)
    return sorted(choices.items(), key=lambda c: c[1].lower())


def asset_type_label(code):
    from assets.models import Asset, AssetType
    label = dict(Asset.ASSET_TYPES).get(code)
    if label:
        return label
    row = AssetType.objects.filter(organization__isnull=True, slug=code).only('name').first()
    return row.name if row else (code or '')


def is_valid_asset_type(code):
    return code in builtin_type_codes() or is_custom_asset_type(code)


# ----- custom fields ---------------------------------------------------------

FIELD_PREFIX = 'cf__'


def active_custom_fields():
    from assets.models import AssetCustomField
    return list(AssetCustomField.objects.filter(is_active=True))


def form_field_for(defn):
    """A Django form field for one custom field definition. `required` is
    left off here: it depends on the asset type, checked in the form's clean."""
    attrs = {'class': 'form-control'}
    common = {'label': defn.label, 'help_text': defn.help_text, 'required': False}
    t = defn.field_type
    if t == 'textarea':
        return forms.CharField(widget=forms.Textarea(attrs={**attrs, 'rows': 3}), **common)
    if t == 'number':
        return forms.DecimalField(widget=forms.NumberInput(attrs=attrs), **common)
    if t == 'date':
        return forms.DateField(widget=forms.DateInput(attrs={**attrs, 'type': 'date'}), **common)
    if t == 'checkbox':
        return forms.BooleanField(widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}), **common)
    if t == 'dropdown':
        opts = [('', '---------')] + [(o, o) for o in defn.choice_list()]
        return forms.ChoiceField(choices=opts, widget=forms.Select(attrs={'class': 'form-select'}), **common)
    if t == 'url':
        return forms.URLField(widget=forms.URLInput(attrs=attrs), **common)
    if t == 'email':
        return forms.EmailField(widget=forms.EmailInput(attrs=attrs), **common)
    return forms.CharField(max_length=500, widget=forms.TextInput(attrs=attrs), **common)


def to_storage(defn, value):
    """JSON-safe value for `Asset.custom_fields`; None means remove the key."""
    if defn.field_type == 'checkbox':
        return bool(value)
    if value in (None, ''):
        return None
    if defn.field_type == 'number':
        return int(value) if value == value.to_integral_value() else float(value)
    if defn.field_type == 'date':
        return value.isoformat()
    return value


def display_rows(asset):
    """(label, value) for the asset's defined fields that apply to its type,
    then the remaining stored keys (from imports and integrations) as-is."""
    data = asset.custom_fields or {}
    rows, used = [], set()
    for defn in active_custom_fields():
        if not defn.applies_to(asset.asset_type):
            continue
        used.add(defn.key)
        value = data.get(defn.key)
        if defn.field_type == 'checkbox':
            value = 'Yes' if value else 'No'
        rows.append({'label': defn.label, 'value': value, 'defined': True})
    for key, value in data.items():
        if key not in used:
            rows.append({'label': key, 'value': value, 'defined': False})
    return rows
