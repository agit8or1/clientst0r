"""Build, correct and freeze a migration plan.

Categories (one per item):

    create       nothing mapped, nothing matching in the customer -> new record
    update       mapped earlier; the source changed, the record was not edited
                 locally in those fields -> update just those fields
    unchanged    mapped earlier; nothing changed in the source -> nothing to do
    duplicate    not mapped, exactly one record of this customer matches the
                 natural key -> map to it without changes (default)
    conflict     mapped and edited locally where the source also changed, or
                 several records match -> skip until the operator decides
    unavailable  cannot be imported (permissions, API gap, not supported,
                 invalid data, a required link missing)

Broken links (a reference to a source record that is neither in this
customer's staging nor mapped earlier) are counted per item; the record is
still imported, without that link.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db import transaction
from django.utils import timezone

from .normalize import APPLY_ORDER, KINDS, canonical_for
from .redact import SECRET_PLACEHOLDER, fingerprint, sha256_json
from .targets import (ATTACHMENT_ENTITY_TYPES, MODEL_TO_KIND, RELATIONSHIP_TYPES, SECRET_COLUMNS,
                      SPECS, current, norm)

CATEGORIES = ('create', 'update', 'unchanged', 'duplicate', 'conflict', 'unavailable')


class PlanError(Exception):
    pass


class PlanChanged(PlanError):
    """The plan or the staging changed after review."""


def mapping_for(plan, source_type, source_id):
    """The ONLY way to look a source record up: customer + source system +
    source account + source type + source ID."""
    from imports.models import SourceMapping
    return SourceMapping.objects.filter(
        organization=plan.organization, source_system=plan.source_system,
        source_account=plan.source_account, source_type=source_type,
        source_id=str(source_id)).first()


def mapped_target(plan, mapping):
    """(kind, obj) for a mapping, only if the record exists in this customer."""
    if mapping is None:
        return None, None
    kind = MODEL_TO_KIND.get(mapping.target_model)
    if kind is None:
        return None, None
    return kind, SPECS[kind].get(plan.organization, mapping.target_id)


def canonical(plan, staged):
    return canonical_for(plan.source_system, staged.source_type, staged.raw, staged.secret_data,
                         plan.type_overrides or {})


def display_proposed(proposed, secrets):
    out = {k: v for k, v in proposed.items() if not k.startswith('_')}
    for name in secrets:
        out[name] = SECRET_PLACEHOLDER
    return out


def secret_fingerprints(secrets):
    return {k: fingerprint(v) for k, v in secrets.items()}


def written_values(spec, obj, names, secrets):
    """What the import leaves in the record, in comparable form."""
    out = {n: current(obj, n) for n in names}
    for name in secrets:
        col = SECRET_COLUMNS[name][0]
        out[col] = current(obj, col)
    return out


def _compare(plan, item, spec, target, mapping, proposed, secrets):
    """Fill category / changed fields for a record that is mapped."""
    written = mapping.written or {}
    fps = written.get('__fp__') or {}
    plain = [n for n in proposed if not n.startswith('_')]
    src_changed = [n for n in plain if proposed[n] != written.get(n)]
    src_changed += [s for s in secrets if fingerprint(secrets[s]) != fps.get(s)]
    if not src_changed:
        item.category, item.default_action = 'unchanged', 'skip'
        item.reason = 'already imported; nothing changed in the source'
        return
    local = []
    for n in src_changed:
        if n in SECRET_COLUMNS:
            col = SECRET_COLUMNS[n][0]
            if current(target, col) != written.get(col):
                local.append(n)
        elif current(target, n) != written.get(n):
            local.append(n)
    item.changed_fields = src_changed
    item.before = {n: (SECRET_PLACEHOLDER if n in SECRET_COLUMNS else current(target, n)) for n in src_changed}
    if local:
        item.category, item.default_action = 'conflict', 'skip'
        item.reason = ('changed in the source and edited in ClientSt0r since the import: '
                       + ', '.join(local))
    else:
        item.category, item.default_action = 'update', 'update'
        item.reason = 'changed in the source: ' + ', '.join(src_changed)


def _diff_existing(item, target, proposed, secrets):
    """Fields an 'update' of a not-yet-mapped existing record would change."""
    plain = [n for n in proposed if not n.startswith('_')]
    changed = [n for n in plain if current(target, n) != proposed[n]]
    changed += list(secrets)  # cannot compare plaintext to ciphertext: always rewritten
    item.changed_fields = changed
    item.before = {n: (SECRET_PLACEHOLDER if n in SECRET_COLUMNS else current(target, n)) for n in changed}


def _classify(plan, item, staged):
    canon = canonical(plan, staged)
    spec = SPECS[canon.kind]
    item.target_kind = canon.kind
    item.display_name = (canon.name or staged.display_name or '')[:255]
    item.links = [dict(l) for l in canon.links]
    item.skipped_fields = list(canon.skipped_fields)
    item.order = APPLY_ORDER[canon.kind] * 1_000_000 + (item.order or 0)
    if canon.unavailable:
        item.category, item.default_action = 'unavailable', 'skip'
        item.reason = canon.unavailable
        item.proposed = {}
        return
    mapping = mapping_for(plan, staged.source_type, staged.source_id)
    kind, target = mapped_target(plan, mapping)
    proposed, notes = spec.prepare(plan.organization, canon.fields,
                                   target_pk=target.pk if target is not None and kind == canon.kind else None)
    item.skipped_fields += [f'{n} (not set)' for n in notes]
    if proposed.get('_vlan_missing'):
        item.links.append({'role': 'vlan', 'source_type': 'vlan', 'source_id': proposed['_vlan_missing'],
                           'status': 'broken',
                           'reason': f"VLAN {proposed['_vlan_missing']} does not exist in this customer"})
    item.proposed = display_proposed(proposed, canon.secrets)
    if target is not None and kind == canon.kind:
        item.target_id = target.pk
        _compare(plan, item, spec, target, mapping, {k: v for k, v in proposed.items()
                                                     if not k.startswith('_')}, canon.secrets)
        return
    if mapping is not None and target is not None:
        item.category, item.default_action = 'conflict', 'skip'
        item.reason = (f'previously imported as {mapping.target_model} #{mapping.target_id}; '
                       f'now maps to {canon.kind}')
        return
    if mapping is not None:
        item.category, item.default_action = 'create', 'create'
        item.reason = 'previously imported record no longer exists'
        return
    # Natural-key matches that need resolved links are evaluated in refresh_links.
    if canon.kind in ('ip_address', 'relation', 'attachment'):
        item.category, item.default_action = 'create', 'create'
        return
    matches = spec.matches(plan.organization, proposed)
    _apply_matches(item, spec, matches)


def _apply_matches(item, spec, matches):
    if len(matches) == 1:
        item.category, item.default_action = 'duplicate', 'link'
        item.target_id = matches[0].pk
        item.candidates = [{'id': matches[0].pk, 'label': spec.label(matches[0])}]
        item.reason = f'matches existing {spec.model_name} "{spec.label(matches[0])}"'
    elif len(matches) > 1:
        item.category, item.default_action = 'conflict', 'skip'
        item.candidates = [{'id': m.pk, 'label': spec.label(m)} for m in matches]
        item.reason = f'{len(matches)} existing records match; choose one or create new'
    else:
        item.category, item.default_action = 'create', 'create'


def build_plan(plan):
    """(Re)build all plan items from staging, keeping operator corrections."""
    from imports.models import PlanItem
    if plan.status not in plan.EDITABLE_STATUSES or not plan.staged_at:
        raise PlanError('stage the source data before building a plan')
    if plan.organization is None:
        raise PlanError('a rehearsal needs a target customer')
    keep = {(i.source_type, i.source_id): i for i in plan.items.filter(corrected=True)}
    with transaction.atomic():
        plan.items.all().delete()
        items = []
        for n, staged in enumerate(plan.staged.order_by('source_type', 'id')):
            item = PlanItem(plan=plan, staged=staged, source_type=staged.source_type,
                            source_id=staged.source_id, order=n)
            _classify(plan, item, staged)
            item.action = item.default_action
            items.append(item)
        PlanItem.objects.bulk_create(items)
        for item in plan.items.all():
            old = keep.get((item.source_type, item.source_id))
            if old is not None:
                try:
                    apply_correction(item, old.action, old.target_id, old.field_overrides,
                                     old.correction_note, old.corrected_by, refresh=False, at=old.corrected_at)
                except PlanError:
                    pass  # no longer applicable; the item keeps its default
        refresh_links(plan)
        plan.status = 'planned'
        plan.planned_at = timezone.now()
        plan.reviewed_at = None
        plan.reviewed_plan_hash = plan.reviewed_staging_hash = ''
        plan.save()
    return plan


def _resolve(plan, index, link):
    """Where a link points: ('staged'|'mapped', kind, target_id) or ('broken', reason)."""
    other = index.get((link['source_type'], str(link['source_id'])))
    if other is not None:
        if other.action == 'skip':
            # Skipped now, but imported earlier: the link goes to that record.
            kind, target = mapped_target(plan, mapping_for(plan, link['source_type'], link['source_id']))
            if target is not None:
                return 'mapped', kind, target.pk
            return 'broken', other.target_kind, f'linked {other.target_kind} is skipped ({other.category})'
        return 'staged', other.target_kind, other.target_id if other.action in ('update', 'link') else None
    mapping = mapping_for(plan, link['source_type'], link['source_id'])
    kind, target = mapped_target(plan, mapping)
    if target is not None:
        return 'mapped', kind, target.pk
    return 'broken', None, "not in this customer's source data and not imported earlier"


def refresh_links(plan):
    """Recompute link status, broken-link counts and link-dependent fields
    for every item. Called after building and after each correction."""
    items = list(plan.items.all())
    index = {(i.source_type, i.source_id): i for i in items}
    names = {(i.source_type, i.source_id): (i.proposed or {}).get('name') or i.display_name for i in items}
    for item in items:
        spec = SPECS[item.target_kind]
        links, broken = [], 0
        resolved = {}
        for link in item.links:
            link = dict(link)
            if link.get('role') == 'vlan':
                links.append(link)
                broken += 1
                continue
            status, kind, info = _resolve(plan, index, link)
            allowed = spec.role_kinds.get(link['role'])
            if status != 'broken' and allowed is not None and kind not in allowed:
                status, info = 'broken', f'a {kind} cannot be linked as {link["role"]}'
            link['status'] = status
            link['target_kind'] = kind
            if status == 'broken':
                link['reason'] = info
                link.pop('target_id', None)
                broken += 1
            else:
                link.pop('reason', None)
                link['target_id'] = info
                resolved[link['role']] = (kind, info, link)
            links.append(link)
        item.links = links
        item.broken_links = broken
        if item.category != 'unavailable':
            missing = [r for r in spec.required_roles if r not in resolved]
            if missing and item.action != 'skip':
                item.action = 'skip'
                item.category = 'unavailable'
                item.reason = f'required link missing: {", ".join(missing)}'
            elif not missing and item.category == 'create' and not item.corrected and not item.target_id:
                _late_match(plan, item, spec, resolved)
        if item.target_kind == 'network' and item.category != 'unavailable':
            loc = resolved.get('location')
            name = ''
            if loc:
                kind, target_id, link = loc
                if target_id:
                    obj = SPECS['location'].get(plan.organization, target_id)
                    name = obj.name if obj else ''
                if not name:
                    name = names.get((link['source_type'], str(link['source_id']))) or ''
            item.proposed = dict(item.proposed, location=norm(spec.model, 'location', name))
        item.save(update_fields=['links', 'broken_links', 'action', 'category', 'reason', 'proposed',
                                 'target_id', 'candidates', 'default_action'])


def _late_match(plan, item, spec, resolved):
    """Natural-key matching for kinds whose key includes a link target."""
    if item.target_kind == 'ip_address':
        _, subnet_id, _ = resolved['subnet']
        matches = spec.matches(plan.organization, item.proposed, subnet_id=subnet_id) if subnet_id else []
    elif item.target_kind == 'relation':
        (fk, fid, _), (tk, tid, _) = resolved['from'], resolved['to']
        matches = spec.matches(plan.organization, item.proposed, ends=((fk, fid), (tk, tid))) \
            if fid and tid else []
    elif item.target_kind == 'attachment':
        pk_kind, pid, _ = resolved['parent']
        size = ((item.staged.raw.get('_file') or {}).get('size')) if item.staged_id else 0
        matches = spec.matches(plan.organization, item.proposed, parent=(pk_kind, pid), size=size) \
            if pid else []
    else:
        return
    _apply_matches(item, spec, matches)
    item.action = item.default_action


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------

def apply_correction(item, action, target_id=None, field_overrides=None, note='', user=None,
                     refresh=True, at=None):
    """Store an operator decision on an item. Target records are looked up in
    the plan's customer only."""
    plan = item.plan
    if plan.status not in plan.EDITABLE_STATUSES:
        raise PlanError('this plan can no longer be changed')
    spec = SPECS[item.target_kind]
    if action not in dict(item.ACTION_CHOICES):
        raise PlanError('unknown action')
    if item.category == 'unavailable' and action != 'skip' and not item.proposed:
        raise PlanError('this record cannot be imported')
    overrides = {}
    for name, value in (field_overrides or {}).items():
        if name not in spec.editable:
            raise PlanError(f'{name} cannot be changed here')
        overrides[name] = norm(spec.model, name, value)
    target = None
    if action in ('update', 'link'):
        target_id = target_id or item.target_id
        target = spec.get(plan.organization, target_id)
        if target is None:
            raise PlanError(f'no {spec.model_name} #{target_id} in this customer')
    staged = item.staged
    proposed = dict(item.proposed)
    proposed.update(overrides)
    canon = canonical(plan, staged) if staged is not None else None
    secrets = canon.secrets if canon is not None else {}
    item.action = action
    item.field_overrides = overrides
    item.target_id = target.pk if target is not None else (None if action == 'create' else item.target_id)
    if action == 'update':
        mapping = mapping_for(plan, item.source_type, item.source_id)
        plain = {k: v for k, v in proposed.items() if k not in SECRET_COLUMNS and not k.startswith('_')}
        if mapping is not None and mapping.target_id == target.pk:
            _compare(plan, item, spec, target, mapping, plain, secrets)
            item.changed_fields = sorted(set(item.changed_fields) | set(overrides))
            item.before = {n: (SECRET_PLACEHOLDER if n in SECRET_COLUMNS else current(target, n))
                           for n in item.changed_fields}
        else:
            _diff_existing(item, target, plain, secrets)
    elif action == 'create':
        item.changed_fields, item.before = [], {}
    item.corrected = True
    item.correction_note = (note or '')[:2000]
    item.corrected_by = user
    item.corrected_at = at or timezone.now()
    item.save()
    if refresh:
        refresh_links(plan)
        _unfreeze(plan)
    return item


def _unfreeze(plan):
    if plan.status == 'reviewed':
        plan.status = 'planned'
        plan.reviewed_at = None
        plan.reviewed_plan_hash = plan.reviewed_staging_hash = ''
        plan.save(update_fields=['status', 'reviewed_at', 'reviewed_plan_hash', 'reviewed_staging_hash'])


def set_type_override(plan, group, source_value, target_kind):
    """Type-level mapping change (Hudu layout / IT Glue flexible asset type).
    Takes effect when the plan is rebuilt."""
    from .normalize import FLEXIBLE_KINDS, PROCEDURE_KINDS
    allowed = {'hudu_layouts': ('asset', 'contact', 'location', 'skip'),
               'itglue_flexible_types': FLEXIBLE_KINDS,
               'hudu_procedures': PROCEDURE_KINDS}
    if group not in allowed or target_kind not in allowed[group]:
        raise PlanError('unsupported type mapping')
    if plan.status not in plan.EDITABLE_STATUSES:
        raise PlanError('this plan can no longer be changed')
    overrides = dict(plan.type_overrides or {})
    overrides.setdefault(group, {})[str(source_value)[:255]] = target_kind
    plan.type_overrides = overrides
    plan.save(update_fields=['type_overrides'])


# ---------------------------------------------------------------------------
# Summary / freeze
# ---------------------------------------------------------------------------

def plan_hash(plan):
    rows = []
    for i in plan.items.order_by('source_type', 'source_id'):
        rows.append([i.source_type, i.source_id, i.staged.content_hash if i.staged_id else '',
                     i.target_kind, i.category, i.action, i.target_id, i.proposed, i.field_overrides,
                     i.changed_fields, i.before, i.links])
    return sha256_json({
        'organization': plan.organization.pk if plan.organization else None,
        'source': [plan.source_system, plan.source_account, plan.source_organization_id],
        'type_overrides': plan.type_overrides,
        'items': rows,
    })


def freeze(plan, user):
    from .sources import compute_staging_hash
    if plan.status not in ('planned', 'reviewed'):
        raise PlanError('build the plan before reviewing it')
    refresh_links(plan)
    plan.reviewed_staging_hash = compute_staging_hash(plan)
    if plan.staging_hash and plan.reviewed_staging_hash != plan.staging_hash:
        raise PlanChanged('the staged source data changed since it was fetched; stage it again')
    plan.reviewed_plan_hash = plan_hash(plan)
    plan.reviewed_at = timezone.now()
    plan.reviewed_by = user
    plan.status = 'reviewed'
    plan.save()
    return plan


def summary(plan):
    """Counts per target kind x category, plus broken links and transfer/skip reasons."""
    counts = defaultdict(Counter)
    reasons = defaultdict(Counter)
    for i in plan.items.all().only('target_kind', 'category', 'action', 'broken_links', 'reason'):
        counts[i.target_kind][i.category] += 1
        counts[i.target_kind]['broken_links'] += 1 if i.broken_links else 0
        counts[i.target_kind]['transfer' if i.action != 'skip' else 'skip'] += 1
        if i.action == 'skip':
            reasons[i.target_kind][f'{i.category}: {i.reason}' if i.reason else i.category] += 1
    rows = []
    for kind in KINDS:
        if kind in counts:
            c = counts[kind]
            rows.append({'kind': kind, **{k: c.get(k, 0) for k in CATEGORIES},
                         'broken_links': c.get('broken_links', 0),
                         'transfer': c.get('transfer', 0), 'skip': c.get('skip', 0),
                         'total': sum(c.get(k, 0) for k in CATEGORIES),
                         'skip_reasons': reasons[kind].most_common(10)})
    totals = {k: sum(r[k] for r in rows) for k in CATEGORIES + ('broken_links', 'transfer', 'skip', 'total')}
    return {'rows': rows, 'totals': totals, 'unavailable_endpoints': plan.unavailable or []}


def samples(plan, kind=None, category=None, limit=5):
    """Representative records per (kind, category) for the review page."""
    qs = plan.items.all()
    if kind:
        qs = qs.filter(target_kind=kind)
    if category:
        qs = qs.filter(category=category)
    seen = Counter()
    out = []
    for item in qs.select_related('staged'):
        key = (item.target_kind, item.category)
        if seen[key] >= limit:
            continue
        seen[key] += 1
        out.append(item)
    return out


def source_view(item):
    """The staged source record, already scrubbed of secrets."""
    if item.staged_id is None:
        return {}
    raw = dict(item.staged.raw)
    raw.pop('_skip_attachments', None)
    if item.target_kind == 'password':
        # Credential notes often hold secrets: shown only in the vault.
        if isinstance(raw.get('attributes'), dict):
            raw['attributes'] = {k: ('[hidden]' if k == 'notes' and v else v)
                                 for k, v in raw['attributes'].items()}
        if raw.get('description'):
            raw['description'] = '[hidden]'
    return raw


__all__ = ['build_plan', 'refresh_links', 'apply_correction', 'set_type_override', 'freeze',
           'plan_hash', 'summary', 'samples', 'source_view', 'PlanError', 'PlanChanged',
           'mapping_for', 'ATTACHMENT_ENTITY_TYPES', 'RELATIONSHIP_TYPES']
