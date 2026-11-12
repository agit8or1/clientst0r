"""
Request types: published form versions, drafts, copies and archiving.

`ServiceCatalogItem.form_schema` stays the live (published) form that the
portal and the staff ticket form read. Every change to it, whichever editor
made it (the form builder, the classic catalog editor, an approved
governance proposal, a seed command), becomes a numbered, immutable
`ServiceRequestFormVersion` the next time the form is served or submitted
(`ensure_version`). A customer's submission is validated against, and
records, the version they were served.

The form builder edits `draft_schema` instead; customers never see a draft
until it is published.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from .service_requests import SchemaError, legacy_fields_from_schema, normalize_schema


def latest_version(item):
    from .models import ServiceRequestFormVersion
    if item is None or item.pk is None:
        return None
    if item.published_version_id:
        v = ServiceRequestFormVersion.objects.filter(pk=item.published_version_id).first()
        if v is not None:
            return v
    return item.form_versions.order_by('-number').first()


def ensure_version(item, user=None, note=''):
    """The published version matching the item's live form, creating the
    next version number when the live form has changed. Returns None for an
    unsaved item."""
    from .models import ServiceCatalogItem, ServiceRequestFormVersion
    if item is None or item.pk is None:
        return None
    schema = item.get_form_schema()
    pattern = item.default_subject or ''
    current = latest_version(item)
    if current is not None and current.schema == schema and current.subject_pattern == pattern:
        if item.published_version_id != current.pk:
            ServiceCatalogItem.objects.filter(pk=item.pk).update(published_version=current)
            item.published_version = current
        return current
    for _ in range(3):
        number = (item.form_versions.order_by('-number')
                  .values_list('number', flat=True).first() or 0) + 1
        try:
            with transaction.atomic():
                v = ServiceRequestFormVersion.objects.create(
                    catalog_item=item, number=number, schema=schema,
                    subject_pattern=pattern[:300], note=note[:300],
                    published_by=user or item.last_published_by,
                )
        except IntegrityError:
            continue  # another request published the same number; re-read
        ServiceCatalogItem.objects.filter(pk=item.pk).update(published_version=v)
        item.published_version = v
        return v
    return latest_version(item)


def draft_or_live_schema(item):
    if item.draft_schema is not None:
        return list(item.draft_schema)
    return item.get_form_schema()


def has_unpublished_changes(item):
    return item.draft_schema is not None and item.draft_schema != item.get_form_schema()


def save_draft(item, schema, user):
    """Validate and store a builder draft. Raises SchemaError."""
    schema = normalize_schema(schema, allow_legacy_types=False)
    item.draft_schema = schema
    item.draft_updated_at = timezone.now()
    item.draft_updated_by = user
    item.save(update_fields=['draft_schema', 'draft_updated_at', 'draft_updated_by', 'updated_at'])
    return schema


def publish(item, user, schema=None, note=''):
    """Make the draft (or `schema`) the live form, as a new version.
    Raises SchemaError. Governance is the caller's job."""
    schema = normalize_schema(draft_or_live_schema(item) if schema is None else schema,
                              allow_legacy_types=False)
    item.form_schema = schema
    item.fields_json = legacy_fields_from_schema(schema)
    item.draft_schema = None
    if item.lifecycle == item.LIFECYCLE_DRAFT:
        item.lifecycle = item.LIFECYCLE_PUBLISHED
    item.last_published_at = timezone.now()
    item.last_published_by = user
    item.save()
    return ensure_version(item, user=user, note=note)


def name_taken(name, organization, exclude_pk=None):
    from .models import ServiceCatalogItem
    qs = ServiceCatalogItem.objects.filter(name__iexact=name.strip(),
                                           organization=organization)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def unique_slug(base):
    from .models import ServiceCatalogItem
    base = (slugify(base) or 'request')[:100]
    slug, n = base, 1
    while ServiceCatalogItem.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    return slug


COPY_FIELDS = (
    'description', 'default_subject', 'default_body', 'default_priority', 'default_queue',
    'default_type', 'icon', 'category', 'sort_order', 'approval_policy',
    'expected_turnaround_text', 'expected_turnaround_hours', 'process_template',
    'portal_audience', 'confirmation_message', 'default_assignee', 'default_team',
    'approval_allow_self', 'starter_key',
)


def duplicate(item, user, *, organization=None, name=None):
    """Copy a request type as a new draft. With `organization`, the copy is
    that customer's own version: offered only to them, and (once published)
    shown to them instead of the MSP-wide original. Editing the copy never
    changes the original or any other customer's copy."""
    from .models import ServiceCatalogItem
    if organization is not None and item.organization_id and item.organization_id != organization.pk:
        raise ValueError('That request type belongs to a different customer.')
    if name is None:
        name = item.name if organization is not None else f'{item.name} (copy)'
    base_name, n = name[:110], 1
    while name_taken(name, organization):
        n += 1
        name = f'{base_name} ({n})'
    copy = ServiceCatalogItem(
        name=name[:120],
        slug=unique_slug(f'{item.slug}-{organization.slug}' if organization is not None
                         else f'{item.slug}-copy'),
        organization=organization,
        based_on=(item if organization is not None and item.organization_id is None
                  else item.based_on if organization is not None else None),
        lifecycle=ServiceCatalogItem.LIFECYCLE_DRAFT,
        is_active=True, portal_visible=item.portal_visible,
        form_schema=item.get_form_schema(),
        fields_json=legacy_fields_from_schema(item.get_form_schema()),
        draft_schema=draft_or_live_schema(item),
        draft_updated_at=timezone.now(), draft_updated_by=user,
    )
    for f in COPY_FIELDS:
        setattr(copy, f, getattr(item, f))
    copy.save()
    if organization is None:
        copy.include_organizations.set(item.include_organizations.all())
        copy.exclude_organizations.set(item.exclude_organizations.all())
    return copy


def archive(item, user):
    """Hide a request type everywhere except existing tickets, which keep
    their stored request details."""
    item.lifecycle = item.LIFECYCLE_ARCHIVED
    item.archived_at = timezone.now()
    item.archived_by = user
    item.save(update_fields=['lifecycle', 'archived_at', 'archived_by', 'updated_at'])


def restore(item, user):
    item.lifecycle = item.LIFECYCLE_PUBLISHED if item.form_versions.exists() \
        else item.LIFECYCLE_DRAFT
    item.archived_at = None
    item.archived_by = None
    item.save(update_fields=['lifecycle', 'archived_at', 'archived_by', 'updated_at'])


def staff_may_manage(user, item=None, organization=None):
    """MSP admins manage request types. A customer-specific request type
    also needs ticket access at that customer."""
    from accounts.permission_utils import orgs_with_perm
    org_id = getattr(organization, 'pk', None) or (item.organization_id if item is not None else None)
    if not org_id:
        return True
    allowed = orgs_with_perm(user, 'tickets_view')
    return allowed is None or org_id in allowed


__all__ = [
    'SchemaError', 'archive', 'draft_or_live_schema', 'duplicate', 'ensure_version',
    'has_unpublished_changes', 'latest_version', 'name_taken', 'publish', 'restore',
    'save_draft', 'staff_may_manage', 'unique_slug',
]
