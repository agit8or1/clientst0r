"""Apply exactly the reviewed plan.

* Refuses unless the plan was frozen, and refuses if the staged source data
  or the plan items changed since (both hashes are recomputed from content).
* Reads only the staging - it never calls the source API.
* Each item is written in its own savepoint together with its PlanChange,
  SourceMapping and outcome, so a failure (or a crash) leaves every item
  either fully applied or untouched. Running apply again resumes: applied
  items are not touched again.
* An update re-checks that every field it changes still holds the value seen
  at review; if a technician changed it in the meantime the item fails
  instead of overwriting their edit.
"""
from __future__ import annotations

import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .planner import PlanChanged, PlanError, canonical, mapped_target, mapping_for, plan_hash
from .redact import fingerprint, redact_text
from .targets import (PASSWORD_RELATION_TYPES, RELATIONSHIP_TYPES, SECRET_COLUMNS, SPECS, _field,
                      current)

logger = logging.getLogger('imports')

APPLY_STATUSES = ('reviewed', 'applying', 'partially_applied')


class ApplyError(Exception):
    pass


def verify_frozen(plan):
    from .sources import compute_staging_hash
    if not plan.reviewed_plan_hash or not plan.reviewed_staging_hash:
        raise PlanError('the plan has not been reviewed')
    if compute_staging_hash(plan) != plan.reviewed_staging_hash:
        raise PlanChanged('the staged source data changed after review - review the plan again')
    if plan_hash(plan) != plan.reviewed_plan_hash:
        raise PlanChanged('the plan changed after review - review it again')


def _snapshot_mapping(mapping):
    if mapping is None:
        return {}
    return {'target_model': mapping.target_model, 'target_id': mapping.target_id,
            'written': mapping.written, 'plan_id': mapping.plan_id}


def _resolve_links(plan, item):
    """role -> (kind, obj) for links that resolve now, inside this customer."""
    spec = SPECS[item.target_kind]
    out, missing = {}, []
    for link in item.links:
        if link.get('status') == 'broken' or link.get('role') == 'vlan':
            continue
        kind, obj = mapped_target(plan, mapping_for(plan, link['source_type'], link['source_id']))
        allowed = spec.role_kinds.get(link['role'])
        if obj is None or (allowed is not None and kind not in allowed):
            missing.append(link['role'])
            continue
        out.setdefault(link['role'], (kind, obj))
    for role in spec.required_roles:
        if role not in out:
            raise ApplyError(f'required link "{role}" could not be resolved')
    return out, missing


def _set(obj, name, value):
    setattr(obj, _field(type(obj), name).attname, value)


def _upsert_mapping(plan, item, obj, written):
    from imports.models import SourceMapping
    mapping, created = SourceMapping.objects.get_or_create(
        organization=plan.organization, source_system=plan.source_system,
        source_account=plan.source_account, source_type=item.source_type,
        source_id=item.source_id,
        defaults={'target_model': SPECS[item.target_kind].model_name, 'target_id': obj.pk,
                  'written': written, 'plan': plan})
    if not created:
        mapping.target_model = SPECS[item.target_kind].model_name
        mapping.target_id = obj.pk
        mapping.written = written
        mapping.plan = plan
        mapping.save()
    return mapping


def _side_links(plan, item, obj, links, user):
    """Relationship / PasswordRelation rows for non-FK links."""
    from assets.models import Relationship
    from imports.models import PlanChange
    from vault.models import PasswordRelation
    spec = SPECS[item.target_kind]
    if item.target_kind in ('relation', 'attachment', 'network'):
        return
    for role, (kind, target) in links.items():
        if role in spec.fk_roles:
            continue
        if item.target_kind == 'password' and kind in PASSWORD_RELATION_TYPES:
            row, created = PasswordRelation.objects.get_or_create(
                password=obj, relation_type=kind, relation_id=target.pk)
            model = 'PasswordRelation'
        elif item.target_kind in RELATIONSHIP_TYPES and kind in RELATIONSHIP_TYPES:
            row, created = Relationship.objects.get_or_create(
                source_type=RELATIONSHIP_TYPES[item.target_kind], source_id=obj.pk,
                target_type=RELATIONSHIP_TYPES[kind], target_id=target.pk, relation_type='related',
                defaults={'organization': plan.organization})
            model = 'Relationship'
        else:
            continue
        if created:
            PlanChange.objects.create(plan=plan, item=item, op='create', target_model=model,
                                      target_id=row.pk, after={})


def _apply_item(plan, item, user):
    from imports.models import ImportMapping, PlanChange
    spec = SPECS[item.target_kind]
    org = plan.organization
    canon = canonical(plan, item.staged)
    secrets = canon.secrets
    plain = {k: v for k, v in (item.proposed or {}).items()
             if k not in SECRET_COLUMNS and not k.startswith('_')}
    plain.update(item.field_overrides or {})
    links, missing = _resolve_links(plan, item)
    mapping = mapping_for(plan, item.source_type, item.source_id)
    mapping_before = _snapshot_mapping(mapping)
    fps = {k: fingerprint(v) for k, v in secrets.items()}
    notes = [f'link "{r}" not resolved' for r in missing]

    if item.action == 'create':
        obj = spec.new(org, user)
        names = list(plain)
        for name, value in plain.items():
            _set(obj, name, value)
        for role, attname in spec.fk_roles.items():
            if role in links:
                setattr(obj, attname, links[role][1].pk)
                names.append(attname)
        if item.target_kind == 'relation':
            (fk, f_obj), (tk, t_obj) = links['from'], links['to']
            obj.source_type, obj.source_id = RELATIONSHIP_TYPES[fk], f_obj.pk
            obj.target_type, obj.target_id = RELATIONSHIP_TYPES[tk], t_obj.pk
            names += ['source_type', 'source_id', 'target_type', 'target_id']
        if item.target_kind == 'attachment':
            kind, parent = links['parent']
            meta = item.staged.raw.get('_file') or {}
            if not item.staged.blob:
                raise ApplyError('staged file is missing')
            with item.staged.blob.open('rb') as fh:
                content = fh.read()
            obj.entity_type, obj.entity_id = kind, parent.pk
            obj.file_size = len(content)
            obj.content_type = meta.get('content_type') or 'application/octet-stream'
            obj.file.save(obj.original_filename or 'attachment', ContentFile(content), save=False)
            names += ['entity_type', 'entity_id', 'file_size', 'content_type']
        for name, value in secrets.items():
            getattr(obj, SECRET_COLUMNS[name][1])(value)
        spec.save_new(obj, item.staged, user)
        after = {n: current(obj, n) for n in names}
        for name in secrets:
            after[SECRET_COLUMNS[name][0]] = current(obj, SECRET_COLUMNS[name][0])
        PlanChange.objects.create(plan=plan, item=item, op='create', target_model=spec.model_name,
                                  target_id=obj.pk, after=after, mapping_before=mapping_before)
        written = dict(after, __fp__=fps)
        ImportMapping.objects.get_or_create(
            import_job=plan.import_job, source_type=item.source_type, source_id=item.source_id,
            defaults={'target_model': spec.model_name, 'target_id': obj.pk,
                      'target_organization': org, 'target_updated_at': getattr(obj, 'updated_at', None),
                      'source_organization_id': plan.source_organization_id})

    elif item.action == 'update':
        obj = spec.get(org, item.target_id)
        if obj is None:
            raise ApplyError(f'{spec.model_name} #{item.target_id} no longer exists in this customer')
        before, after = {}, {}
        for name in item.changed_fields:
            if name in SECRET_COLUMNS:
                continue
            if current(obj, name) != item.before.get(name):
                raise ApplyError(f'"{name}" was changed in ClientSt0r after review; not overwritten')
        for name in item.changed_fields:
            if name in SECRET_COLUMNS:
                if name in secrets:
                    col, setter = SECRET_COLUMNS[name]
                    before[col] = current(obj, col)
                    getattr(obj, setter)(secrets[name])
                continue
            before[name] = current(obj, name)
            _set(obj, name, plain.get(name))
        obj.save()
        for name in before:
            after[name] = current(obj, name)
        PlanChange.objects.create(plan=plan, item=item, op='update', target_model=spec.model_name,
                                  target_id=obj.pk, before=before, after=after,
                                  mapping_before=mapping_before)
        if mapping is not None and mapping.target_id == obj.pk:
            written = dict(mapping.written or {})
            written.update(after)
            written['__fp__'] = dict(written.get('__fp__') or {}, **{k: fps[k] for k in fps
                                                                     if k in item.changed_fields})
        else:
            written = {n: current(obj, n) for n in plain}
            for name in secrets:
                written[SECRET_COLUMNS[name][0]] = current(obj, SECRET_COLUMNS[name][0])
            written['__fp__'] = fps

    elif item.action == 'link':
        obj = spec.get(org, item.target_id)
        if obj is None:
            raise ApplyError(f'{spec.model_name} #{item.target_id} no longer exists in this customer')
        PlanChange.objects.create(plan=plan, item=item, op='link', target_model=spec.model_name,
                                  target_id=obj.pk, mapping_before=mapping_before)
        # "In sync as of this source state": a rerun with the same source is a no-op.
        written = dict(plain)
        for name in secrets:
            written[SECRET_COLUMNS[name][0]] = current(obj, SECRET_COLUMNS[name][0])
        written['__fp__'] = fps
    else:
        raise ApplyError(f'unknown action {item.action}')

    _side_links(plan, item, obj, links, user)
    _upsert_mapping(plan, item, obj, written)
    item.outcome = 'applied'
    item.result_target_id = obj.pk
    item.outcome_message = '; '.join(notes)
    item.applied_at = timezone.now()
    item.save(update_fields=['outcome', 'result_target_id', 'outcome_message', 'applied_at'])


def apply_plan(plan, user):
    """Apply (or resume applying) a reviewed plan. Returns a counts dict."""
    if plan.status not in APPLY_STATUSES:
        raise PlanError(f'a plan in status "{plan.get_status_display()}" cannot be applied')
    if plan.organization is None:
        raise PlanError('a rehearsal needs a target customer')
    verify_frozen(plan)

    job = plan.import_job
    plan.status = 'applying'
    plan.apply_attempts += 1
    plan.save(update_fields=['status', 'apply_attempts'])
    job.dry_run = False
    job.status = 'running'
    job.started_at = job.started_at or timezone.now()
    job.save(update_fields=['dry_run', 'status', 'started_at'])
    job.add_log(f'Applying reviewed plan (attempt {plan.apply_attempts})')

    pending = plan.items.exclude(outcome__in=('applied', 'skipped')).select_related('staged')
    for item in pending.order_by('order', 'id'):
        if item.action == 'skip':
            item.outcome = 'skipped'
            item.outcome_message = item.reason
            item.save(update_fields=['outcome', 'outcome_message'])
            continue
        try:
            with transaction.atomic():
                _apply_item(plan, item, user)
        except Exception as exc:  # noqa: BLE001 - recorded per item, run continues
            secrets = list((item.staged.secret_data or {}).values()) if item.staged_id else []
            item.outcome = 'failed'
            item.outcome_message = redact_text(f'{type(exc).__name__}: {exc}', secrets)[:1000]
            item.save(update_fields=['outcome', 'outcome_message'])
            logger.warning('Rehearsal %s: item %s %s failed: %s', plan.pk, item.source_type,
                           item.source_id, type(exc).__name__)
    return finish_apply(plan, user)


def finish_apply(plan, user):
    job = plan.import_job
    items = plan.items.all()
    counts = {
        'applied': items.filter(outcome='applied').count(),
        'skipped': items.filter(outcome='skipped').count(),
        'failed': items.filter(outcome='failed').count(),
        'pending': items.filter(outcome='pending').count(),
    }
    plan.status = 'partially_applied' if counts['failed'] or counts['pending'] else 'applied'
    plan.applied_at = timezone.now()
    plan.applied_by = user
    plan.save(update_fields=['status', 'applied_at', 'applied_by'])
    job.items_imported = counts['applied']
    job.items_skipped = counts['skipped']
    job.items_failed = counts['failed']
    job.save(update_fields=['items_imported', 'items_skipped', 'items_failed'])
    job.finish()
    job.add_log(f"Plan applied: {counts['applied']} applied, {counts['skipped']} skipped, "
                f"{counts['failed']} failed")
    return counts
