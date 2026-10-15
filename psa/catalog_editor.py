"""
Staff catalog editor support for guided service requests.

Kept out of psa/views.py so the direct-edit form and the governance
propose-change form share one parser. Both forms post a `_guided=1` marker
when they carry the guided-request fields; a POST without it (older form,
API-style test) leaves those fields untouched.
"""
from __future__ import annotations

import json

from .service_requests import (
    FIELD_TYPES, TYPE_LABELS, SchemaError, legacy_fields_from_schema,
    normalize_schema,
)

GUIDED_MARKER = '_guided'

# Scalar fields governed by ServiceCatalogChange snapshots. FK ids are
# carried as *_id so ServiceCatalogChange.apply can setattr them; the M2M
# availability lists travel as *_organization_ids (handled in apply()).
GUIDED_SCALAR_FIELDS = (
    'portal_visible', 'category', 'form_schema', 'fields_json',
    'approval_policy', 'expected_turnaround_text', 'expected_turnaround_hours',
    'default_queue_id', 'default_priority_id', 'default_type_id',
    'process_template_id',
)
GUIDED_M2M_FIELDS = {
    'include_organization_ids': 'include_organizations',
    'exclude_organization_ids': 'exclude_organizations',
}


def process_choices(item=None):
    from django.db.models import Q
    from processes.models import Process
    qs = Process.objects.filter(
        Q(is_global=True) | Q(is_template=True), is_archived=False,
    )
    if item is not None and item.process_template_id:
        qs = qs | Process.objects.filter(pk=item.process_template_id)
    return qs.distinct().order_by('title')


def organization_choices():
    from core.models import Organization
    return Organization.objects.filter(is_active=True).order_by('name')


def snapshot(item):
    snap = {f: getattr(item, f) for f in GUIDED_SCALAR_FIELDS}
    if item.pk:
        snap['include_organization_ids'] = sorted(
            item.include_organizations.values_list('pk', flat=True))
        snap['exclude_organization_ids'] = sorted(
            item.exclude_organizations.values_list('pk', flat=True))
    else:
        snap['include_organization_ids'] = []
        snap['exclude_organization_ids'] = []
    return snap


def _int_or_none(raw):
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def parse_guided_post(post, item=None):
    """Parse the guided-request section of a catalog form.

    Returns (values, error). `values` has every GUIDED_SCALAR_FIELDS key
    plus the two *_organization_ids lists. `error` is a message string or
    None. Returns ({}, None) when the POST doesn't carry the section.
    """
    from psa.models import Queue, ServiceCatalogItem, TicketPriority, TicketType

    if post.get(GUIDED_MARKER) != '1':
        return {}, None

    raw = (post.get('form_schema_json') or '[]').strip() or '[]'
    try:
        schema = normalize_schema(json.loads(raw))
    except json.JSONDecodeError as e:
        return {}, f'Form definition is not valid JSON: {e}'
    except SchemaError as e:
        return {}, str(e)

    policy = post.get('approval_policy') or ServiceCatalogItem.APPROVAL_NONE
    if policy not in dict(ServiceCatalogItem.APPROVAL_POLICY_CHOICES):
        return {}, 'Pick a valid approval policy.'

    hours_raw = (post.get('expected_turnaround_hours') or '').strip()
    hours = _int_or_none(hours_raw) if hours_raw else None
    if hours_raw and hours is None:
        return {}, 'Expected turnaround hours must be a whole number.'

    def _pick(model_qs, name):
        pk = _int_or_none(post.get(name))
        if not pk:
            return None
        return model_qs.filter(pk=pk).values_list('pk', flat=True).first()

    process_id = _pick(process_choices(item), 'process_template')
    if post.get('process_template') and process_id is None:
        return {}, 'Pick a valid workflow.'

    org_ids = set(organization_choices().values_list('pk', flat=True))

    def _ids(name):
        out = set()
        for v in post.getlist(name):
            pk = _int_or_none(v)
            if pk in org_ids:
                out.add(pk)
        return sorted(out)

    include_ids = _ids('include_organizations')
    exclude_ids = _ids('exclude_organizations')

    form_schema, fields_json = schema, legacy_fields_from_schema(schema)
    if item is not None:
        # Unchanged form → keep the stored values verbatim so a proposal
        # doesn't show a spurious diff (and legacy fields_json survives).
        try:
            current = normalize_schema(item.get_form_schema())
        except SchemaError:
            current = None
        if current == schema:
            form_schema, fields_json = item.form_schema, item.fields_json

    values = {
        'portal_visible': post.get('portal_visible') == 'on',
        'category': (post.get('category') or '').strip()[:80],
        'form_schema': form_schema,
        'fields_json': fields_json,
        'approval_policy': policy,
        'expected_turnaround_text': (post.get('expected_turnaround_text') or '').strip()[:120],
        'expected_turnaround_hours': hours,
        'default_queue_id': _pick(Queue.objects.filter(is_active=True), 'default_queue'),
        'default_priority_id': _pick(TicketPriority.objects.all(), 'default_priority'),
        'default_type_id': _pick(TicketType.objects.filter(is_active=True), 'default_type'),
        'process_template_id': process_id,
        'include_organization_ids': include_ids,
        'exclude_organization_ids': exclude_ids,
    }
    return values, None


def apply_values(item, values):
    """Set parsed values on `item`. Scalars before save; call
    apply_m2m(item, values) after the item has a pk."""
    for f in GUIDED_SCALAR_FIELDS:
        if f in values:
            setattr(item, f, values[f])


def apply_m2m(item, values):
    for key, rel in GUIDED_M2M_FIELDS.items():
        if key in values:
            getattr(item, rel).set(values[key])


def editor_context(item):
    """Template context for the guided-request section of the editor."""
    from core.models import SystemSetting
    from psa.models import ServiceCatalogItem
    schema = item.get_form_schema() if item is not None else []
    try:
        approvals_on = bool(SystemSetting.get_settings().psa_portal_customer_approvals_enabled)
    except Exception:
        approvals_on = False
    return {
        'guided_schema_json': json.dumps(schema, indent=2),
        'guided_type_choices': [(t, TYPE_LABELS[t]) for t in FIELD_TYPES],
        'guided_processes': process_choices(item),
        'guided_organizations': organization_choices(),
        'guided_include_ids': set(item.include_organizations.values_list('pk', flat=True)) if item and item.pk else set(),
        'guided_exclude_ids': set(item.exclude_organizations.values_list('pk', flat=True)) if item and item.pk else set(),
        'guided_approval_choices': ServiceCatalogItem.APPROVAL_POLICY_CHOICES,
        'guided_customer_approvals_enabled': approvals_on,
    }
