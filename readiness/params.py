"""
Parameters for each requirement kind, and their validation.

  document_exists / document_fresh / document_owner
      tag             Tag name or slug on the document (case-insensitive)
      category        DocumentCategory name or slug (case-insensitive)
      title_contains  Text in the document title; "a|b" means a OR b
      (at least one of the three; all given ones must match)
      document_fresh also takes:
      max_age_days    reviewed / updated within this many days (required)
      basis           "reviewed_or_updated" (default) or "reviewed"
  asset_fields
      asset_type      Asset.asset_type (blank = the standard's asset scope, or every asset)
      fields          built-in Asset field names that must be non-empty
      custom_fields   AssetCustomField keys that must be filled in, on assets
                      of a type each field applies to (optional; v3.17.655).
                      At least one built-in or custom field is required.
  contact_role
      title_contains  Text in Contact.title; "a|b" means a OR b
      min_count       how many such contacts are needed (default 1)
  credential_reference
      title_contains  Text in the vault entry title; "a|b" means a OR b
      tag             Tag name or slug on the vault entry
      (at least one; metadata only — secrets are never read)
  relationship_present
      asset_type      as for asset_fields
      target_kinds    subset of ["document", "contact"] (default both)
"""
from django.core.exceptions import ValidationError

DOC_MATCH_KEYS = ('tag', 'category', 'title_contains')
FRESH_BASES = ('reviewed_or_updated', 'reviewed')
RELATIONSHIP_TARGET_KINDS = ('document', 'contact')

# Asset columns that can't meaningfully be "missing": bookkeeping, booleans,
# scheduler-maintained stamps, and the generated-doc links.
_ASSET_FIELD_EXCLUDE = {
    'id', 'organization', 'created_at', 'updated_at', 'created_by', 'asset_type',
    'name', 'last_warranty_alert_sent_at', 'firmware_checked_at',
    'warranty_checked_at', 'profile_document', 'ai_document', 'lifespan_reminder_months',
    'firmware_latest', 'custom_fields', 'ports', 'vlans',
}


def asset_field_choices():
    """(name, label) for built-in Asset fields an asset_fields rule may check."""
    from django.db import models
    from assets.models import Asset
    out = []
    for f in Asset._meta.get_fields():
        if not getattr(f, 'concrete', False) or f.many_to_many or f.auto_created:
            continue
        if f.name in _ASSET_FIELD_EXCLUDE or isinstance(f, models.BooleanField):
            continue
        out.append((f.name, str(f.verbose_name).capitalize()))
    return sorted(out, key=lambda x: x[1])


def asset_field_column(name):
    """The DB attribute for a field name (`primary_contact` -> `primary_contact_id`)."""
    from assets.models import Asset
    return Asset._meta.get_field(name).attname


def custom_field_choices(include=()):
    """(key, label) for custom asset fields an asset_fields rule may check:
    active, non-checkbox definitions (an unticked box is a value, not a
    gap). `include` keeps keys a requirement already names selectable even
    after their field was deactivated."""
    from assets.models import Asset, AssetCustomField
    type_labels = dict(Asset.ASSET_TYPES)
    out = []
    qs = AssetCustomField.objects.exclude(field_type='checkbox')
    for d in qs.order_by('order', 'label'):
        if not d.is_active and d.key not in include:
            continue
        label = d.label
        if d.asset_types:
            label += ' (' + ', '.join(type_labels.get(t, t) for t in d.asset_types) + ')'
        if not d.is_active:
            label += ' (inactive)'
        out.append((d.key, label))
    return out


def _clean_custom_fields(value, asset_type):
    from assets.models import Asset, AssetCustomField
    if isinstance(value, str):
        value = [k.strip() for k in value.split(',')]
    if not isinstance(value, (list, tuple)):
        raise ValidationError('custom_fields must be a list of custom field keys.')
    keys = list(dict.fromkeys(k for k in value if isinstance(k, str) and k))
    if not keys:
        return []
    defs = {d.key: d for d in AssetCustomField.objects.filter(key__in=keys)}
    bad = [k for k in keys if k not in defs or defs[k].field_type == 'checkbox']
    if bad:
        raise ValidationError(f'Not a custom asset field that can be checked: {", ".join(bad)}.')
    if asset_type:
        wrong = [defs[k].label for k in keys if not defs[k].applies_to(asset_type)]
        if wrong:
            raise ValidationError(f'These custom fields are not used on {dict(Asset.ASSET_TYPES).get(asset_type, asset_type)} assets: '
                                  f'{", ".join(wrong)}.')
    return keys


def _clean_text(value):
    return (value or '').strip() if isinstance(value, str) else ''


def split_alternatives(value):
    return [p.strip() for p in (value or '').split('|') if p.strip()]


def validate_params(kind, params):
    """Return a normalised copy of `params` for `kind`, or raise ValidationError."""
    from assets.models import Asset
    from .models import StandardRequirement as R

    if not isinstance(params, dict):
        raise ValidationError('Parameters must be an object.')
    out = {}
    if kind in R.DOCUMENT_KINDS:
        for key in DOC_MATCH_KEYS:
            v = _clean_text(params.get(key))
            if v:
                out[key] = v
        if not out:
            raise ValidationError('Give a tag, a category or a title to match documents by.')
        if kind == R.KIND_DOCUMENT_FRESH:
            try:
                days = int(params.get('max_age_days'))
            except (TypeError, ValueError):
                raise ValidationError('max_age_days must be a whole number of days.')
            if days < 1:
                raise ValidationError('max_age_days must be at least 1.')
            out['max_age_days'] = days
            basis = params.get('basis') or 'reviewed_or_updated'
            if basis not in FRESH_BASES:
                raise ValidationError(f'basis must be one of {", ".join(FRESH_BASES)}.')
            out['basis'] = basis
    elif kind in (R.KIND_ASSET_FIELDS, R.KIND_RELATIONSHIP_PRESENT):
        asset_type = _clean_text(params.get('asset_type'))
        if asset_type:
            if asset_type not in dict(Asset.ASSET_TYPES):
                raise ValidationError(f'Unknown asset type "{asset_type}".')
            out['asset_type'] = asset_type
        if kind == R.KIND_ASSET_FIELDS:
            fields = params.get('fields') or []
            if isinstance(fields, str):
                fields = [f.strip() for f in fields.split(',')]
            fields = [f for f in fields if f]
            valid = dict(asset_field_choices())
            bad = [f for f in fields if f not in valid]
            if bad:
                raise ValidationError(f'Not an asset field that can be checked: {", ".join(bad)}.')
            custom = _clean_custom_fields(params.get('custom_fields') or [], out.get('asset_type'))
            if not fields and not custom:
                raise ValidationError('Choose at least one asset field or custom field.')
            out['fields'] = list(dict.fromkeys(fields))
            # Only stored when used, so built-in-only rules keep their params.
            if custom:
                out['custom_fields'] = custom
        else:
            kinds = params.get('target_kinds') or list(RELATIONSHIP_TARGET_KINDS)
            if isinstance(kinds, str):
                kinds = [k.strip() for k in kinds.split(',')]
            bad = [k for k in kinds if k not in RELATIONSHIP_TARGET_KINDS]
            if bad or not kinds:
                raise ValidationError('target_kinds must be "document" and/or "contact".')
            out['target_kinds'] = [k for k in RELATIONSHIP_TARGET_KINDS if k in kinds]
    elif kind == R.KIND_CONTACT_ROLE:
        title = _clean_text(params.get('title_contains'))
        if not title:
            raise ValidationError('Give the contact title / role to look for.')
        out['title_contains'] = title
        try:
            n = int(params.get('min_count') or 1)
        except (TypeError, ValueError):
            raise ValidationError('min_count must be a whole number.')
        out['min_count'] = max(1, n)
    elif kind == R.KIND_CREDENTIAL_REFERENCE:
        for key in ('title_contains', 'tag'):
            v = _clean_text(params.get(key))
            if v:
                out[key] = v
        if not out:
            raise ValidationError('Give a title or tag to match vault entries by.')
    else:
        raise ValidationError(f'Unknown requirement kind "{kind}".')
    return out
