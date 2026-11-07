"""
Import / update the hardware catalog from the community devicetype-library.

    # Preview what a run would change (no catalog writes):
    python manage.py import_hardware_catalog --preview

    # Import the pinned revision this release was tested with:
    python manage.py import_hardware_catalog

    # Move to a newer upstream commit (preview first, then apply):
    python manage.py import_hardware_catalog --revision latest --preview
    python manage.py import_hardware_catalog --revision <commit-sha>

    # Continue an interrupted run:
    python manage.py import_hardware_catalog --resume <job id>

Re-running is safe: unchanged files are recorded as "unchanged" and nothing
is duplicated. Models staff edited locally are reported as conflicts and left
alone unless --overwrite-local is given.
"""
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from hardware import catalog_import as ci
from hardware.models import CatalogImportJob, CatalogImportRecord, HardwareModel


class Command(BaseCommand):
    help = 'Import or update the hardware catalog from netbox-community/devicetype-library (CC0).'

    def add_arguments(self, parser):
        parser.add_argument('--revision', default=ci.DEFAULT_REVISION,
                            help=f'Upstream commit to import, or "latest" (default: pinned {ci.DEFAULT_REVISION[:10]})')
        parser.add_argument('--source-dir', help='Use an existing checkout instead of the managed one')
        parser.add_argument('--no-fetch', action='store_true', help='Do not contact GitHub; use the checkout as-is')
        parser.add_argument('--preview', action='store_true', help='Report what would change; write nothing to the catalog')
        parser.add_argument('--resume', type=int, metavar='JOB', help='Continue an interrupted job')
        parser.add_argument('--batch-size', type=int, default=250)
        parser.add_argument('--limit', type=int, help='Process at most N files (testing)')
        parser.add_argument('--manufacturer', action='append', help='Only this manufacturer directory (repeatable)')
        parser.add_argument('--kind', action='append', choices=['device', 'module', 'rack'])
        parser.add_argument('--overwrite-local', action='store_true',
                            help='Replace locally modified models with upstream data')
        parser.add_argument('--recategorize', action='store_true',
                            help='Only recompute inferred categories from stored data (after rule changes), then exit')

    def handle(self, *args, **o):
        if o['recategorize']:
            moves = ci.recategorize()
            for k, v in sorted(moves.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f'  {k:40} {v}')
            self.stdout.write(self.style.SUCCESS(f'Recategorized {sum(moves.values())} model(s).'))
            return
        if o['resume']:
            try:
                job = CatalogImportJob.objects.get(pk=o['resume'])
            except CatalogImportJob.DoesNotExist:
                raise CommandError(f'No import job {o["resume"]}.')
            if job.status in ('completed', 'completed_with_errors'):
                raise CommandError(f'Job {job.pk} already finished ({job.status}).')
            revision = job.revision
        else:
            revision = o['revision']

        if o['source_dir']:
            root = Path(o['source_dir'])
            if not (root / 'device-types').is_dir():
                raise CommandError(f'{root} is not a devicetype-library checkout.')
        else:
            self.stdout.write(f'Fetching {ci.SOURCE_URL} @ {revision} …')
            try:
                root = ci.ensure_checkout(revision, fetch=not o['no_fetch'])
            except Exception as e:  # noqa: BLE001
                raise CommandError(f'Could not prepare the source checkout: {e}')
        actual, actual_date = ci.checkout_revision(root) if (root / '.git').exists() else (revision, '')
        if revision not in ('latest',) and not actual.startswith(revision) and not o['source_dir']:
            raise CommandError(f'Checkout is at {actual}, expected {revision}.')
        revision = actual

        if not o['resume']:
            job = ci.start_job(revision, preview=o['preview'], overwrite_local=o['overwrite_local'])
        self.stdout.write(f'Job {job.pk}: revision {revision} ({actual_date}){" — PREVIEW" if job.is_preview else ""}')

        kinds = set(o['kind']) if o['kind'] else None
        mfrs = {m.lower() for m in o['manufacturer']} if o['manufacturer'] else None
        files = ci.list_files(root, kinds=kinds, manufacturers=mfrs)
        self.stdout.write(f'{len(files)} definition files')
        importer = ci.Importer(root, job, stdout=self.stdout)
        complete = True
        try:
            importer.run(files, batch_size=o['batch_size'], limit=o['limit'])
            if o['limit'] and job.records.count() < len(files):
                complete = False
        except KeyboardInterrupt:
            complete = False
            self.stdout.write(self.style.WARNING(f'Interrupted. Resume with --resume {job.pk}'))
        finally:
            ci.finish_job(job, revision_date=actual_date, complete=complete and not mfrs and not kinds)
        if not job.is_preview:
            # Locally maintained models (documented models the library lacks,
            # and the generic templates). Idempotent; never touches edits.
            from hardware.local_models import ensure_local_models
            created = ensure_local_models()
            if created:
                self.stdout.write(f'Added {len(created)} local catalog model(s).')
        self.report(job)

    def report(self, job):
        counts = Counter(job.counts)
        self.stdout.write(self.style.SUCCESS(f'\nJob {job.pk} {job.status}: {job.processed_files}/{job.total_files} files'))
        for k in ('created', 'updated', 'unchanged', 'conflict', 'skipped', 'failed', 'would_create',
                  'would_update', 'with_unsupported_fields'):
            if counts.get(k):
                self.stdout.write(f'  {k:24} {counts[k]}')
        fails = CatalogImportRecord.objects.filter(job=job, status='failed')[:15]
        for r in fails:
            self.stdout.write(self.style.WARNING(f'  FAILED {r.path}: {r.message}'))
        by_kind = HardwareModel.objects.filter(source=job.source).values('kind').annotate(n=Count('id'))
        self.stdout.write('Catalog now holds (from this source): ' +
                          ', '.join(f'{r["kind"]}={r["n"]}' for r in by_kind))
