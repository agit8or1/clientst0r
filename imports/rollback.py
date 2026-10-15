"""
Rollback of an import job.

Rules (all applied inside one database transaction, so a crash half-way leaves
everything as it was):

* Only records this job created (its ImportMapping rows) are candidates.
* A record whose ``updated_at`` is later than the snapshot taken at import time
  was edited afterwards - it is KEPT and listed in the report.
* A record that other, later data now hangs off (a cascade delete would take it
  with it) is KEPT and listed in the report.
* Organizations are removed only if this job created them
  (``OrganizationMapping.was_created``), they were not edited after the import,
  and nothing else references them once the job's own records are gone.
  Matched (pre-existing) organizations are never touched.
* A mapping whose target model is unknown is reported, never silently dropped.
* The job is marked ``rolled_back`` only when every mapping was handled. If
  anything was kept or could not be handled it becomes
  ``partially_rolled_back``; the mappings for what was kept stay in place so the
  report remains accurate and a later rollback can retry.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import ProtectedError, RestrictedError
from django.db.models.deletion import Collector
from django.utils import timezone

from imports.models import ImportMapping, OrganizationMapping, resolve_target_model

logger = logging.getLogger('imports')

# Mappings written before ImportMapping.target_updated_at existed have no
# snapshot; their own created_at (written right after the target) plus this
# slack stands in for it.
LEGACY_SNAPSHOT_TOLERANCE = timedelta(seconds=2)

# Children first, so a parent is only considered once its imported children
# have been dealt with. Organizations are always handled last, separately.
DELETE_ORDER = [
    'LocationFloorPlan', 'FloorPlan', 'VehicleInventoryItem', 'ShopInventoryItem',
    'Password', 'Document', 'Contact', 'Asset', 'Location',
]

# Rows that point at a record/organization but are not "data" that should keep
# it alive: the audit trail (SET_NULL - history survives deletion, unlinked).
IGNORED_REFERENCE_MODELS = {('audit', 'auditlog')}


def _label(model):
    return (model._meta.app_label, model._meta.model_name)


def _timestamp(obj):
    for attr in ('updated_at', 'created_at'):
        value = getattr(obj, attr, None)
        if value is not None:
            return value
    return None


def _snapshot(mapping):
    if mapping.target_updated_at:
        return mapping.target_updated_at
    return mapping.created_at + LEGACY_SNAPSHOT_TOLERANCE


def _describe(obj):
    for attr in ('title', 'name', 'floor_name'):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return f'#{obj.pk}'


class _Dependents:
    """Find what deleting ``objs`` would also take (or unlink) that is not ours."""

    def __init__(self, job, own_keys):
        self.job = job
        # {(app_label, model_name, pk)} of records this rollback may delete.
        self.own_keys = own_keys

    def _is_ours(self, model, obj):
        label = _label(model)
        if label in (('imports', 'importmapping'), ('imports', 'organizationmapping')):
            return getattr(obj, 'import_job_id', None) == self.job.pk
        return (label[0], label[1], obj.pk) in self.own_keys

    def find(self, objs, since=None, strict=False):
        """Return a list of human-readable descriptions of foreign dependents.

        ``since``: dependents last touched at/before this instant are treated
        as created together with the record (e.g. by the importer).
        ``strict``: count auto-created M2M link rows too (used for orgs).
        """
        # The objects being deleted are, by definition, not foreign.
        roots = {(*_label(type(o)), o.pk) for o in objs}
        collector = Collector(using='default')
        try:
            collector.collect(objs)
        except (ProtectedError, RestrictedError) as exc:
            return [f'protected by {len(getattr(exc, "protected_objects", None) or getattr(exc, "restricted_objects", None) or [])} record(s)']

        found = []

        def consider_instance(model, inst):
            if (*_label(model), inst.pk) in roots:
                return
            if _label(model) in IGNORED_REFERENCE_MODELS:
                return
            if self._is_ours(model, inst):
                return
            if not strict and model._meta.auto_created:
                return
            if since is not None and not strict:
                ts = _timestamp(inst)
                if ts is not None and ts <= since:
                    return
            found.append(f'{model._meta.verbose_name} {_describe(inst)}')

        def consider_queryset(qs):
            model = qs.model
            if _label(model) in IGNORED_REFERENCE_MODELS:
                return
            if not strict and model._meta.auto_created:
                return
            if _label(model) in (('imports', 'importmapping'), ('imports', 'organizationmapping')):
                qs = qs.exclude(import_job_id=self.job.pk)
            if since is not None and not strict:
                field_names = {f.name for f in model._meta.concrete_fields}
                for attr in ('updated_at', 'created_at'):
                    if attr in field_names:
                        qs = qs.filter(**{f'{attr}__gt': since})
                        break
            for inst in qs[:50]:
                if not self._is_ours(model, inst):
                    found.append(f'{model._meta.verbose_name} {_describe(inst)}')

        for model, instances in collector.data.items():
            for inst in instances:
                consider_instance(model, inst)
        for qs in collector.fast_deletes:
            consider_queryset(qs)
        for (_field, _value), batches in collector.field_updates.items():
            for batch in batches:
                if hasattr(batch, 'model') and hasattr(batch, 'filter'):
                    consider_queryset(batch)
                else:
                    for inst in batch:
                        consider_instance(type(inst), inst)
        return found


def rollback_import(job, user):
    report = {
        'total_deleted': 0,
        'by_type': {},
        'kept_modified': [],       # edited after the import
        'kept_referenced': [],     # other data depends on it
        'kept_organizations': [],  # created orgs that could not be removed
        'already_missing': 0,
        'errors': [],              # could not be handled at all
        'complete': False,
    }
    log_lines = []

    with transaction.atomic():
        mappings = list(job.mappings.all())
        log_lines.append(f'Starting rollback - {len(mappings)} mapped object(s)')

        created_org_maps = {
            m.organization_id: m
            for m in OrganizationMapping.objects.filter(import_job=job, was_created=True)
        }
        matched_org_ids = set(
            OrganizationMapping.objects.filter(import_job=job, was_created=False)
            .values_list('organization_id', flat=True)
        )

        # ---- resolve every mapping to its object, decide modified-or-not ----
        record_maps = {}   # model name -> list[(mapping, obj)]
        org_import_maps = {}
        own_keys = set()
        for m in mappings:
            if m.target_model == 'Organization':
                org_import_maps[m.target_id] = m
                continue
            Model = resolve_target_model(m.target_model)
            if Model is None:
                msg = f'Unknown model type: {m.target_model} (id {m.target_id}) - not rolled back'
                report['errors'].append(msg)
                continue
            record_maps.setdefault(m.target_model, []).append((m, Model))

        resolved = {}  # model name -> list[(mapping, obj or None)]
        for name, pairs in record_maps.items():
            Model = pairs[0][1]
            objs = Model._base_manager.in_bulk([m.target_id for m, _ in pairs])
            resolved[name] = []
            for m, _ in pairs:
                obj = objs.get(m.target_id)
                resolved[name].append((m, obj))
                if obj is None:
                    continue
                ts = _timestamp(obj)
                if ts is not None and ts > _snapshot(m):
                    report['kept_modified'].append(
                        f'{m.target_model} "{_describe(obj)}" (id {obj.pk}) - edited {timezone.localtime(ts):%Y-%m-%d %H:%M}')
                    m._rb_keep = True
                else:
                    own_keys.add((*_label(Model), obj.pk))

        deps = _Dependents(job, own_keys)

        # ---- delete records, children first ----
        order = DELETE_ORDER + [n for n in resolved if n not in DELETE_ORDER]
        for name in order:
            entries = resolved.get(name)
            if not entries:
                continue
            deletable = []
            for m, obj in entries:
                if obj is None:
                    report['already_missing'] += 1
                    m.delete()
                    continue
                if getattr(m, '_rb_keep', False):
                    continue
                deletable.append((m, obj))
            if not deletable:
                continue

            # Fast path: check the whole batch at once; fall back per object.
            since = min(_snapshot(m) for m, _ in deletable)
            if deps.find([o for _, o in deletable], since=since):
                ok = []
                for m, obj in deletable:
                    found = deps.find([obj], since=_snapshot(m))
                    if found:
                        report['kept_referenced'].append(
                            f'{name} "{_describe(obj)}" (id {obj.pk}) - still used by: '
                            + ', '.join(found[:5]) + (' ...' if len(found) > 5 else ''))
                        own_keys.discard((*_label(type(obj)), obj.pk))
                    else:
                        ok.append((m, obj))
                deletable = ok
            if not deletable:
                continue

            Model = type(deletable[0][1])
            ids = [obj.pk for _, obj in deletable]
            Model._base_manager.filter(pk__in=ids).delete()
            ImportMapping.objects.filter(pk__in=[m.pk for m, _ in deletable]).delete()
            report['by_type'][name] = report['by_type'].get(name, 0) + len(ids)
            report['total_deleted'] += len(ids)
            log_lines.append(f'Deleted {len(ids)} {name} object(s)')

        # ---- organizations ----
        from core.models import Organization
        candidate_org_ids = set(created_org_maps)
        org_ids = candidate_org_ids | set(org_import_maps)
        orgs = Organization.objects.in_bulk(list(org_ids))
        deleted_orgs = skipped_orgs = 0
        for org_id in sorted(org_ids):
            org = orgs.get(org_id)
            imap = org_import_maps.get(org_id)
            if org_id not in candidate_org_ids:
                # Matched an organization that already existed: never delete.
                skipped_orgs += 1
                if imap is not None:
                    imap.delete()
                continue
            if org is None:
                report['already_missing'] += 1
                if imap is not None:
                    imap.delete()
                continue
            omap = created_org_maps[org_id]
            if org_id in matched_org_ids:
                # Same job also mapped another source org onto it - leave it.
                report['kept_organizations'].append(f'"{org.name}" - also matched by this import')
                continue
            snap = imap.target_updated_at if (imap and imap.target_updated_at) else (
                omap.created_at + LEGACY_SNAPSHOT_TOLERANCE)
            if org.updated_at and org.updated_at > snap:
                report['kept_organizations'].append(
                    f'"{org.name}" - edited after the import')
                continue
            found = deps.find([org], strict=True)
            if found:
                report['kept_organizations'].append(
                    f'"{org.name}" - still referenced by: ' + ', '.join(found[:5])
                    + (' ...' if len(found) > 5 else ''))
                continue
            # This job's OrganizationMapping row cascades away with the org;
            # the job log keeps the record of what was removed.
            org.delete()
            deleted_orgs += 1
        if deleted_orgs:
            report['by_type']['Organization (created)'] = deleted_orgs
            report['total_deleted'] += deleted_orgs
            log_lines.append(f'Deleted {deleted_orgs} Organization(s) created by this import')
        if skipped_orgs:
            report['by_type']['Organization (skipped)'] = skipped_orgs
            log_lines.append(f'Skipped {skipped_orgs} Organization(s) that existed before the import')

        # ---- outcome ----
        kept = (report['kept_modified'] + report['kept_referenced']
                + report['kept_organizations'])
        report['complete'] = not kept and not report['errors']
        for line in report['kept_modified']:
            log_lines.append(f'KEPT (modified after import): {line}')
        for line in report['kept_referenced']:
            log_lines.append(f'KEPT (in use): {line}')
        for line in report['kept_organizations']:
            log_lines.append(f'KEPT organization: {line}')
        for line in report['errors']:
            log_lines.append(f'ERROR: {line}')
        if report['already_missing']:
            log_lines.append(f"{report['already_missing']} mapped object(s) were already deleted")

        if report['complete']:
            job.status = 'rolled_back'
            job.rolled_back_at = timezone.now()
            log_lines.append(f"Rollback complete: {report['total_deleted']} object(s) deleted")
        else:
            job.status = 'partially_rolled_back'
            log_lines.append(
                f"Rollback PARTIAL: {report['total_deleted']} object(s) deleted, "
                f"{len(kept)} kept, {len(report['errors'])} could not be handled")
        job.rolled_back_by = user
        job.save(update_fields=['status', 'rolled_back_at', 'rolled_back_by'])
        for line in log_lines:
            job.add_log(line)

    logger.info('Rollback of import %s: %s', job.pk, log_lines[-1])
    return report
