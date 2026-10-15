"""
Views for IT Glue/Hudu import
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from .models import ImportJob
from .forms import ImportJobForm
from .services import get_import_service
import logging

logger = logging.getLogger('imports')


def is_staff_or_superuser(user):
    """Check if user is staff or superuser."""
    return user.is_superuser or (hasattr(user, 'is_staff_user') and user.is_staff_user)


def report_import_outcome(request, job):
    """Flash a message that says what actually happened - never an
    unqualified success when records failed."""
    counts = (f'Imported: {job.items_imported}, Skipped: {job.items_skipped}, '
              f'Failed: {job.items_failed} (of {job.total_items})')
    prefix = 'Dry run ' if job.dry_run else 'Import '
    if job.status == 'completed':
        messages.success(request, f'{prefix}completed. {counts}')
    elif job.status == 'completed_with_errors':
        messages.warning(
            request,
            f'{prefix}completed with errors - {job.items_failed} record(s) failed. '
            f'{counts}. See the log for details.')
    else:
        messages.error(
            request,
            f'{prefix}failed - nothing was imported. {counts}. See the log for details.')


def report_rollback_outcome(request, stats):
    deleted_summary = ', '.join(
        f"{count} {model_name}" for model_name, count in stats['by_type'].items()) or 'nothing'
    if stats.get('complete'):
        messages.success(
            request,
            f"Rolled back the import. Deleted: {deleted_summary}. "
            f"Total: {stats['total_deleted']} objects removed.")
        return
    kept = (stats.get('kept_modified', []) + stats.get('kept_referenced', [])
            + stats.get('kept_organizations', []))
    messages.warning(
        request,
        f"Partial rollback: {stats['total_deleted']} objects removed ({deleted_summary}); "
        f"{len(kept)} kept and {len(stats['errors'])} could not be handled. "
        f"The import log lists every record that was kept and why.")
    for line in kept[:10]:
        messages.info(request, f"Kept: {line}")
    for error in stats['errors'][:10]:
        messages.error(request, f"Not rolled back: {error}")


@login_required
@user_passes_test(is_staff_or_superuser)
def import_list(request):
    """List all import jobs."""
    jobs = ImportJob.objects.all().select_related('target_organization', 'started_by').order_by('-created_at')

    return render(request, 'imports/import_list.html', {
        'jobs': jobs,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_create(request):
    """Create new import job."""
    if request.method == 'POST':
        form = ImportJobForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            job = form.save(commit=False)
            job.started_by = request.user
            job.save()

            if job.source_type == 'csv':
                messages.success(request, 'CSV file uploaded. Now map your columns to the target fields.')
                return redirect('imports:import_map_fields', pk=job.pk)

            messages.success(request, 'Import job created. Review settings and click "Start Import" to begin.')
            return redirect('imports:import_detail', pk=job.pk)
    else:
        form = ImportJobForm(user=request.user)

    return render(request, 'imports/import_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_detail(request, pk):
    """View import job details."""
    job = get_object_or_404(ImportJob.objects.select_related('target_organization', 'started_by'), pk=pk)

    return render(request, 'imports/import_detail.html', {
        'job': job,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_edit(request, pk):
    """Edit import job (only if not started)."""
    job = get_object_or_404(ImportJob, pk=pk)

    if job.status != 'pending':
        messages.error(request, 'Cannot edit import job that has already started.')
        return redirect('imports:import_detail', pk=job.pk)

    if request.method == 'POST':
        form = ImportJobForm(request.POST, request.FILES, instance=job, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Import job updated successfully.')
            return redirect('imports:import_detail', pk=job.pk)
    else:
        form = ImportJobForm(instance=job, user=request.user)

    return render(request, 'imports/import_form.html', {
        'form': form,
        'action': 'Edit',
        'job': job,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_delete(request, pk):
    """Delete import job."""
    job = get_object_or_404(ImportJob, pk=pk)

    if request.method == 'POST':
        job.delete()
        messages.success(request, 'Import job deleted.')
        return redirect('imports:import_list')

    return render(request, 'imports/import_confirm_delete.html', {
        'job': job,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_rollback(request, pk):
    """
    Rollback import job - delete all imported objects.

    This allows users to undo an import for testing/debugging purposes.
    All objects created during the import (tracked via ImportMapping) will be deleted.
    """
    job = get_object_or_404(
        ImportJob.objects.select_related('target_organization', 'started_by', 'rolled_back_by'),
        pk=pk
    )

    # Check if rollback is allowed
    if not job.can_rollback():
        if job.rolled_back_at:
            messages.error(request, f'Import already rolled back on {job.rolled_back_at} by {job.rolled_back_by}.')
        elif job.dry_run:
            messages.error(request, 'Cannot rollback a dry-run import (no data was created).')
        elif job.status not in ImportJob.ROLLBACK_STATUSES:
            messages.error(request, f'Cannot roll back an import with status: {job.get_status_display()}')
        else:
            messages.error(request, 'Cannot rollback this import.')
        return redirect('imports:import_detail', pk=job.pk)

    # Get statistics for confirmation
    mapping_count = job.mappings.count()
    org_count = job.organization_mappings.count()

    if request.method == 'POST':
        try:
            # Perform rollback (atomic; partial outcomes are reported)
            stats = job.rollback(request.user)
            report_rollback_outcome(request, stats)
            return redirect('imports:import_detail', pk=job.pk)

        except Exception as e:
            import logging
            logger = logging.getLogger('imports')
            logger.error(f"Rollback failed for import {job.id}: {str(e)}", exc_info=True)
            messages.error(request, f'Rollback failed: {str(e)}')
            return redirect('imports:import_detail', pk=job.pk)

    return render(request, 'imports/import_confirm_rollback.html', {
        'job': job,
        'mapping_count': mapping_count,
        'org_count': org_count,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_start(request, pk):
    """Start an import job."""
    job = get_object_or_404(ImportJob, pk=pk)

    if job.status not in ['pending', 'failed']:
        messages.error(request, f'Cannot start import job with status: {job.get_status_display()}')
        return redirect('imports:import_detail', pk=job.pk)

    if request.method == 'POST':
        try:
            # Run import in the background (or could use Celery/background task)
            service = get_import_service(job)
            service.run_import()
            job.refresh_from_db()
            report_import_outcome(request, job)

        except Exception as e:
            messages.error(request, f'Import failed: {str(e)}')
            logger.exception(f'Import job {job.id} failed')

        return redirect('imports:import_detail', pk=job.pk)

    return render(request, 'imports/import_start.html', {
        'job': job,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_promote(request, pk):
    """Promote a completed dry-run job to an actual import.

    Resets the job to 'pending' with dry_run=False, clears prior results,
    then redirects to the start page so the user can confirm and run it.
    """
    job = get_object_or_404(ImportJob, pk=pk)

    if not (job.status in ImportJob.SUCCESS_STATUSES and job.dry_run):
        messages.error(request, 'Only completed dry-run jobs can be promoted to an actual import.')
        return redirect('imports:import_detail', pk=job.pk)

    if request.method == 'POST':
        job.dry_run = False
        job.status = 'pending'
        job.started_at = None
        job.completed_at = None
        job.items_imported = 0
        job.items_skipped = 0
        job.items_failed = 0
        job.total_items = 0
        job.error_message = ''
        job.import_log = ''
        job.save()
        messages.info(request, 'Job converted to actual import. Review settings and click Start Import.')
        return redirect('imports:import_start', pk=job.pk)

    return render(request, 'imports/import_promote.html', {'job': job})


@login_required
@user_passes_test(is_staff_or_superuser)
def import_log(request, pk):
    """View import job log."""
    job = get_object_or_404(ImportJob, pk=pk)

    return render(request, 'imports/import_log.html', {
        'job': job,
    })


@login_required
@user_passes_test(is_staff_or_superuser)
def import_map_fields(request, pk):
    """
    CSV field mapper: let user map source columns to target model fields.
    On GET: shows columns from uploaded CSV with dropdowns for each.
    On POST: saves field_mappings and csv_target_model to the job.
    """
    from .services.csv_importer import TARGET_FIELDS, read_csv_preview

    job = get_object_or_404(ImportJob, pk=pk)

    if job.source_type != 'csv':
        messages.error(request, 'Field mapping is only available for CSV imports.')
        return redirect('imports:import_detail', pk=job.pk)

    if not job.source_file:
        messages.error(request, 'No file attached to this import job.')
        return redirect('imports:import_edit', pk=job.pk)

    try:
        headers, preview_rows = read_csv_preview(job.source_file)
    except Exception as e:
        messages.error(request, f'Could not read CSV file: {e}')
        return redirect('imports:import_detail', pk=job.pk)

    if request.method == 'POST':
        target_model = request.POST.get('csv_target_model', '')
        if not target_model or target_model not in TARGET_FIELDS:
            messages.error(request, 'Please select a target data type.')
            return redirect('imports:import_map_fields', pk=job.pk)

        # Build field_mappings from POST: mapping_{col_index} = target_field
        mappings = {}
        for i, header in enumerate(headers):
            tgt = request.POST.get(f'mapping_{i}', '__skip__')
            if tgt and tgt != '__skip__':
                mappings[header] = tgt
            else:
                mappings[header] = '__skip__'

        job.csv_target_model = target_model
        job.field_mappings = mappings
        job.save(update_fields=['csv_target_model', 'field_mappings'])

        messages.success(request, 'Field mappings saved. Review and click "Start Import" when ready.')
        return redirect('imports:import_detail', pk=job.pk)

    # Precompute preview as list of lists for easy template iteration (no custom filter needed)
    preview_table = [[row.get(h, '') for h in headers] for row in preview_rows]

    return render(request, 'imports/import_map_fields.html', {
        'job': job,
        'headers': headers,
        'preview_table': preview_table,
        'target_fields': TARGET_FIELDS,
        'current_target_model': job.csv_target_model or 'asset',
        'current_mappings': job.field_mappings or {},
    })
