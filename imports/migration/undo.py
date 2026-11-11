"""Roll back an applied plan without undoing later local edits.

Works from the PlanChange rows, newest first, inside one transaction:

* created record: deleted only if every field the import wrote still holds
  the value the import wrote AND nothing that is not part of this import
  refers to it (FK dependents, relationships, password links, attachments).
  Otherwise kept and reported.
* updated record: each field is restored to its before-value only where the
  current value still equals what the import wrote; other fields are kept
  and reported.
* mapped existing record (link): only the mapping is undone.
* SourceMapping rows are restored to their state before the plan (or
  removed) for everything that was undone; a record that is kept keeps its
  mapping, so a later rerun still recognises it.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.deletion import Collector
from django.utils import timezone

from imports.models import ImportMapping, PlanChange, SourceMapping, resolve_target_model
from .targets import MODEL_TO_KIND, RELATIONSHIP_TYPES, SPECS, _field, current

logger = logging.getLogger('imports')

ROLLBACK_STATUSES = ('applied', 'partially_applied', 'applying', 'partially_rolled_back')
# Serial lifecycle events are history: they keep the asset's name when the
# asset goes, so they never hold an imported asset back.
IGNORED_DEPENDENTS = {('audit', 'auditlog'), ('imports', 'importmapping'), ('imports', 'sourcemapping'),
                      ('imports', 'planchange'), ('assets', 'serialevent')}


def _label(model):
    return (model._meta.app_label, model._meta.model_name)


def _foreign_dependents(obj, own):
    """Descriptions of records outside this import that deleting ``obj``
    would delete or modify."""
    found = []
    collector = Collector(using='default')
    try:
        collector.collect([obj])
    except Exception as exc:  # ProtectedError / RestrictedError
        return [f'protected ({type(exc).__name__})']
    root = (*_label(type(obj)), obj.pk)

    def consider(model, inst):
        key = (*_label(model), inst.pk)
        if key == root or _label(model) in IGNORED_DEPENDENTS or model._meta.auto_created:
            return
        if key in own:
            return
        found.append(f'{model._meta.verbose_name} #{inst.pk}')

    for model, instances in collector.data.items():
        for inst in instances:
            consider(model, inst)
    for qs in collector.fast_deletes:
        if _label(qs.model) in IGNORED_DEPENDENTS or qs.model._meta.auto_created:
            continue
        for inst in qs[:20]:
            consider(qs.model, inst)
    for _key, batches in collector.field_updates.items():
        for batch in batches:
            insts = batch if not hasattr(batch, 'model') else batch[:20]
            for inst in insts:
                consider(type(inst), inst)

    # Generic references the collector cannot see.
    kind = MODEL_TO_KIND.get(type(obj).__name__)
    rel_type = RELATIONSHIP_TYPES.get(kind)
    if rel_type:
        from assets.models import Relationship
        for r in Relationship.objects.filter(source_type=rel_type, source_id=obj.pk) | \
                Relationship.objects.filter(target_type=rel_type, target_id=obj.pk):
            if ('assets', 'relationship', r.pk) not in own:
                found.append(f'relationship #{r.pk}')
    if kind in ('asset', 'document', 'contact'):
        from vault.models import PasswordRelation
        for r in PasswordRelation.objects.filter(relation_type=kind, relation_id=obj.pk):
            if ('vault', 'passwordrelation', r.pk) not in own:
                found.append(f'password link #{r.pk}')
    if kind in ('asset', 'document', 'contact', 'password'):
        from files.models import Attachment
        for a in Attachment.objects.filter(organization_id=getattr(obj, 'organization_id', None),
                                           entity_type=kind, entity_id=obj.pk):
            if ('files', 'attachment', a.pk) not in own:
                found.append(f'attachment #{a.pk}')
    return found


def _restore_mapping(plan, change):
    item = change.item
    if item is None or change.target_model != SPECS[item.target_kind].model_name:
        return  # a side row (relationship / password link), not the item's record
    mapping = SourceMapping.objects.filter(
        organization=plan.organization, source_system=plan.source_system,
        source_account=plan.source_account, source_type=item.source_type,
        source_id=item.source_id).first()
    before = change.mapping_before or {}
    if not before:
        if mapping is not None and mapping.target_id == change.target_id:
            mapping.delete()
        return
    if mapping is None:
        mapping = SourceMapping(organization=plan.organization, source_system=plan.source_system,
                                source_account=plan.source_account, source_type=item.source_type,
                                source_id=item.source_id)
    mapping.target_model = before['target_model']
    mapping.target_id = before['target_id']
    mapping.written = before.get('written') or {}
    mapping.plan_id = before.get('plan_id')
    mapping.save()


def rollback_plan(plan, user):
    if plan.status not in ROLLBACK_STATUSES:
        raise ValueError(f'a plan in status "{plan.get_status_display()}" cannot be rolled back')
    report = {'deleted': [], 'restored': [], 'kept': [], 'already_missing': [], 'unlinked': [],
              'complete': False}
    with transaction.atomic():
        changes = list(plan.changes.filter(rolled_back=False).select_related('item').order_by('-id'))
        own = set()
        for c in changes:
            Model = resolve_target_model(c.target_model)
            if Model is not None and c.op == 'create':
                own.add((*_label(Model), c.target_id))

        for c in changes:
            Model = resolve_target_model(c.target_model)
            label = f'{c.target_model} #{c.target_id}'
            if c.item is not None:
                label += f' (source {c.item.source_type} {c.item.source_id})'
            obj = Model._base_manager.filter(pk=c.target_id).first() if Model else None

            if c.op == 'link':
                _restore_mapping(plan, c)
                c.rolled_back, c.rollback_note = True, 'mapping removed'
                report['unlinked'].append(label)
            elif obj is None:
                _restore_mapping(plan, c)
                c.rolled_back, c.rollback_note = True, 'already deleted'
                report['already_missing'].append(label)
            elif c.op == 'create':
                edited = [n for n, v in (c.after or {}).items() if current(obj, n) != v]
                deps = [] if edited else _foreign_dependents(obj, own)
                if edited or deps:
                    reason = (f'edited after the import ({", ".join(edited)})' if edited
                              else 'in use by ' + ', '.join(deps[:5]) + (' ...' if len(deps) > 5 else ''))
                    c.rollback_note = f'kept: {reason}'
                    report['kept'].append(f'{label}: {reason}')
                    own.discard((*_label(Model), obj.pk))
                else:
                    if hasattr(obj, 'file') and getattr(obj, 'file', None) and Model.__name__ == 'Attachment':
                        obj.file.delete(save=False)
                    obj.delete()
                    ImportMapping.objects.filter(import_job=plan.import_job, target_model=c.target_model,
                                                 target_id=c.target_id).delete()
                    _restore_mapping(plan, c)
                    c.rolled_back, c.rollback_note = True, 'deleted'
                    report['deleted'].append(label)
            elif c.op == 'update':
                restored, kept = [], []
                for name, wrote in (c.after or {}).items():
                    if current(obj, name) == wrote:
                        setattr(obj, _field(type(obj), name).attname, c.before.get(name))
                        restored.append(name)
                    else:
                        kept.append(name)
                if restored:
                    obj.save()
                    _restore_mapping(plan, c)
                    report['restored'].append(f'{label}: {", ".join(restored)}')
                if kept:
                    c.after = {n: c.after[n] for n in kept}
                    c.rollback_note = f'kept edited fields: {", ".join(kept)}'
                    report['kept'].append(f'{label}: edited after the import ({", ".join(kept)})')
                else:
                    c.rolled_back, c.rollback_note = True, 'restored'
            c.save(update_fields=['rolled_back', 'rollback_note', 'after'])

        report['complete'] = not report['kept']
        plan.status = 'rolled_back' if report['complete'] else 'partially_rolled_back'
        plan.save(update_fields=['status'])
        job = plan.import_job
        job.status = plan.status
        job.rolled_back_by = user
        if report['complete']:
            job.rolled_back_at = timezone.now()
        job.save(update_fields=['status', 'rolled_back_by', 'rolled_back_at'])
        job.add_log(f"Rollback: {len(report['deleted'])} deleted, {len(report['restored'])} restored, "
                    f"{len(report['unlinked'])} unmapped, {len(report['kept'])} kept")
        for line in report['kept']:
            job.add_log(f'KEPT {line}')
    return report


def legacy_report(report):
    """Shape the report like imports.rollback for the existing job views."""
    by_type = {}
    for line in report['deleted']:
        name = line.split(' #', 1)[0]
        by_type[name] = by_type.get(name, 0) + 1
    return {
        'total_deleted': len(report['deleted']),
        'by_type': by_type,
        'kept_modified': [l for l in report['kept'] if 'edited' in l],
        'kept_referenced': [l for l in report['kept'] if 'in use' in l],
        'kept_organizations': [],
        'already_missing': len(report['already_missing']),
        'errors': [],
        'complete': report['complete'],
        'restored': report['restored'],
    }
