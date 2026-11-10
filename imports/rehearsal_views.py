"""Views for the one-customer IT Glue / Hudu migration rehearsal and the
per-customer inventory export.

Rehearsal views are staff/superuser only (like every import view) and only
reach plans whose target customer the request may access. Apply and
rollback are POST-only and audit-logged.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Organization
from core.tenancy import accessible_org_ids
from .models import ImportJob, MigrationPlan, PlanItem
from .migration import planner
from .migration.applier import apply_plan
from .migration.planner import PlanChanged, PlanError
from .migration.redact import redact_text
from .migration.targets import SPECS, current

logger = logging.getLogger('imports')


def is_msp_staff(user):
    """Superusers and MSP staff (profile user type Staff). Customer
    (portal) users never reach the migration tools."""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile is not None and getattr(profile, 'is_staff_user', lambda: False)())


staff_required = user_passes_test(is_msp_staff)


def _orgs(request):
    allowed = accessible_org_ids(request)
    qs = Organization.objects.filter(is_active=True).order_by('name')
    return qs if allowed is None else qs.filter(pk__in=allowed)


def _plans(request):
    allowed = accessible_org_ids(request)
    qs = MigrationPlan.objects.select_related('import_job', 'import_job__target_organization')
    return qs if allowed is None else qs.filter(import_job__target_organization_id__in=allowed)


def _plan(request, pk):
    return get_object_or_404(_plans(request), pk=pk)


def _audit(request, action, plan_or_org, description, extra=None, success=True):
    from audit.models import AuditLog
    from core.client_ip import get_client_ip
    if isinstance(plan_or_org, MigrationPlan):
        org, obj_type, obj_id, rep = (plan_or_org.organization, 'migration_rehearsal', plan_or_org.pk,
                                      str(plan_or_org)[:255])
    else:
        org, obj_type, obj_id, rep = plan_or_org, 'organization', plan_or_org.pk, plan_or_org.name[:255]
    AuditLog.log(user=request.user, action=action, organization=org, object_type=obj_type,
                 object_id=obj_id, object_repr=rep, description=description,
                 ip_address=get_client_ip(request), user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                 path=request.path, extra_data=extra or {}, success=success)


class RehearsalForm(forms.Form):
    source_type = forms.ChoiceField(choices=[('itglue', 'IT Glue'), ('hudu', 'Hudu')],
                                    widget=forms.Select(attrs={'class': 'form-select'}))
    source_url = forms.URLField(widget=forms.URLInput(attrs={
        'class': 'form-control', 'placeholder': 'https://api.itglue.com or https://yourco.huducloud.com'}))
    source_api_key = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    source_account = forms.CharField(
        required=False, max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Optional. Distinguishes two accounts on the same host; defaults to the API host.')
    source_organization_id = forms.CharField(
        max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='IT Glue organization ID or Hudu company ID of the ONE customer to rehearse.')
    target_organization = forms.ModelChoiceField(
        queryset=Organization.objects.none(), widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='The ClientSt0r customer the records go to.')

    def __init__(self, *args, orgs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['target_organization'].queryset = orgs


@login_required
@staff_required
def rehearsal_list(request):
    return render(request, 'imports/rehearsal_list.html', {'plans': _plans(request)})


@login_required
@staff_required
def rehearsal_create(request):
    form = RehearsalForm(request.POST or None, orgs=_orgs(request))
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        account = (d['source_account'] or urlparse(d['source_url']).hostname or '').strip().lower()
        job = ImportJob.objects.create(
            source_type=d['source_type'], source_url=d['source_url'], source_api_key=d['source_api_key'],
            target_organization=d['target_organization'], started_by=request.user, dry_run=True,
            use_fuzzy_matching=False, skip_duplicates=True,
            import_contacts=True, import_locations=True, import_networks=True)
        plan = MigrationPlan.objects.create(import_job=job, source_account=account,
                                            source_organization_id=d['source_organization_id'].strip())
        job.add_log(f'Migration rehearsal created for source organization {plan.source_organization_id}')
        messages.success(request, 'Rehearsal created. Fetch the source data to build the plan.')
        return redirect('imports:rehearsal_detail', pk=plan.pk)
    return render(request, 'imports/rehearsal_form.html', {'form': form})


def _type_choices(plan):
    """Source layouts / flexible asset types seen in the staging, for the
    type-mapping corrections."""
    from .migration.normalize import hudu_layout_kind, itglue_flexible_kind
    out = []
    overrides = plan.type_overrides or {}
    if plan.source_system == 'hudu':
        seen = sorted({(r.raw.get('asset_layout_name') or r.raw.get('asset_type') or '')
                       for r in plan.staged.filter(source_type='asset')})
        for name in seen:
            out.append({'group': 'hudu_layouts', 'name': name, 'kind': hudu_layout_kind(name, overrides),
                        'choices': ['asset', 'contact', 'location', 'skip']})
    else:
        seen = sorted({r.raw.get('_type_name') or '' for r in plan.staged.filter(source_type='flexible_asset')})
        for name in seen:
            out.append({'group': 'itglue_flexible_types', 'name': name,
                        'kind': itglue_flexible_kind(name, overrides), 'choices': ['network', 'skip']})
    return out


@login_required
@staff_required
def rehearsal_detail(request, pk):
    plan = _plan(request, pk)
    summary = planner.summary(plan) if plan.planned_at else None
    report = None
    if plan.status in ('applied', 'partially_applied', 'applying', 'rolled_back', 'partially_rolled_back'):
        from .migration.report import build_report
        report = build_report(plan)
    return render(request, 'imports/rehearsal_detail.html', {
        'plan': plan, 'job': plan.import_job, 'summary': summary, 'report': report,
        'type_choices': _type_choices(plan) if plan.staged_at else [],
        'can_edit': plan.status in plan.EDITABLE_STATUSES,
        'categories': planner.CATEGORIES,
    })


@login_required
@staff_required
@require_POST
def rehearsal_stage(request, pk):
    plan = _plan(request, pk)
    if plan.status not in plan.EDITABLE_STATUSES:
        messages.error(request, 'This rehearsal has been applied; start a new one to fetch again.')
        return redirect('imports:rehearsal_detail', pk=pk)
    from .migration.sources import stager_for
    from .migration.transport import SourceUnavailable
    try:
        stager_for(plan).stage()
        planner.build_plan(plan)
        plan.import_job.add_log(f'Staged {plan.staged.count()} source record(s) and built the plan')
        messages.success(request, f'Fetched {plan.staged.count()} source record(s) and built the plan. '
                                  'Nothing has been written to the customer yet.')
    except SourceUnavailable as exc:
        messages.error(request, f'Could not read the source organization ({exc.kind}): {exc}')
    except PlanError as exc:
        messages.error(request, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception('Rehearsal %s staging failed', plan.pk)
        messages.error(request, f'Fetching failed: {redact_text(type(exc).__name__ + ": " + str(exc))}')
    return redirect('imports:rehearsal_detail', pk=pk)


@login_required
@staff_required
@require_POST
def rehearsal_build(request, pk):
    plan = _plan(request, pk)
    try:
        planner.build_plan(plan)
        messages.success(request, 'Plan rebuilt from the staged data (corrections kept where they still apply).')
    except PlanError as exc:
        messages.error(request, str(exc))
    return redirect('imports:rehearsal_detail', pk=pk)


@login_required
@staff_required
@require_POST
def rehearsal_type_override(request, pk):
    plan = _plan(request, pk)
    try:
        planner.set_type_override(plan, request.POST.get('group', ''), request.POST.get('name', ''),
                                  request.POST.get('kind', ''))
        planner.build_plan(plan)
        messages.success(request, 'Type mapping changed and plan rebuilt.')
    except PlanError as exc:
        messages.error(request, str(exc))
    return redirect('imports:rehearsal_detail', pk=pk)


@login_required
@staff_required
def rehearsal_items(request, pk):
    plan = _plan(request, pk)
    kind = request.GET.get('kind') or ''
    category = request.GET.get('category') or ''
    show_all = request.GET.get('all') == '1'
    if show_all:
        qs = plan.items.all()
        if kind:
            qs = qs.filter(target_kind=kind)
        if category:
            qs = qs.filter(category=category)
        page = Paginator(qs, 100).get_page(request.GET.get('page'))
        items = list(page.object_list)
    else:
        page = None
        items = planner.samples(plan, kind=kind or None, category=category or None)
    return render(request, 'imports/rehearsal_items.html', {
        'plan': plan, 'items': items, 'page': page, 'kind': kind, 'category': category,
        'show_all': show_all, 'kinds': list(SPECS), 'categories': planner.CATEGORIES,
    })


@login_required
@staff_required
def rehearsal_item(request, pk, item_id):
    plan = _plan(request, pk)
    item = get_object_or_404(PlanItem, plan=plan, pk=item_id)
    spec = SPECS[item.target_kind]
    if request.method == 'POST':
        overrides = {name: request.POST.get(f'field_{name}') for name in spec.editable
                     if request.POST.get(f'field_{name}') not in (None, '')
                     and request.POST.get(f'field_{name}') != str(item.proposed.get(name, ''))}
        target_id = request.POST.get('target_id') or None
        try:
            planner.apply_correction(item, request.POST.get('action', ''),
                                     int(target_id) if target_id else None, overrides,
                                     request.POST.get('note', ''), request.user)
            messages.success(request, 'Correction saved on the plan. Review again before applying.')
        except (PlanError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect('imports:rehearsal_item', pk=pk, item_id=item.pk)
    target = spec.get(plan.organization, item.target_id) if item.target_id else None
    target_values = {}
    if target is not None:
        for name in spec.fields:
            if name in ('password',):
                continue
            target_values[name] = current(target, name)
    rows = []
    hidden = {'notes'} if item.target_kind == 'password' else set()
    for name in sorted(set(item.proposed) | set(target_values)):
        if name in hidden:
            rows.append({'name': name, 'proposed': '[hidden]' if item.proposed.get(name) else '',
                         'current': '[hidden]' if target_values.get(name) else '', 'override': '',
                         'editable': False, 'changed': name in (item.changed_fields or [])})
            continue
        rows.append({'name': name, 'proposed': item.proposed.get(name, ''),
                     'current': target_values.get(name, ''),
                     'override': (item.field_overrides or {}).get(name, ''),
                     'editable': name in spec.editable,
                     'changed': name in (item.changed_fields or [])})
    return render(request, 'imports/rehearsal_item.html', {
        'plan': plan, 'item': item, 'spec': spec, 'rows': rows,
        'source_json': json.dumps(planner.source_view(item), indent=2, sort_keys=True, default=str),
        'target': target, 'actions': PlanItem.ACTION_CHOICES,
        'can_edit': plan.status in plan.EDITABLE_STATUSES,
    })


@login_required
@staff_required
@require_POST
def rehearsal_freeze(request, pk):
    plan = _plan(request, pk)
    try:
        planner.freeze(plan, request.user)
        plan.import_job.add_log(f'Plan reviewed and frozen by {request.user.username} '
                                f'(plan {plan.reviewed_plan_hash[:12]}, staging {plan.reviewed_staging_hash[:12]})')
        messages.success(request, 'Plan frozen. Apply writes exactly this plan.')
    except PlanError as exc:
        messages.error(request, str(exc))
    return redirect('imports:rehearsal_detail', pk=pk)


def _check_apply_permissions(request, plan):
    from accounts.permission_utils import user_has_org_perm
    org = plan.organization
    needs = {'password': 'vault_create', 'document': 'docs_create', 'attachment': 'files_upload'}
    for kind, perm in needs.items():
        if plan.items.filter(target_kind=kind).exclude(action='skip').exists() and not (
                request.user.is_superuser or user_has_org_perm(request.user, org, perm)):
            raise PermissionDenied(f'You need the "{perm}" permission in {org.name} to apply this plan.')


@login_required
@staff_required
@require_POST
def rehearsal_apply(request, pk):
    plan = _plan(request, pk)
    _check_apply_permissions(request, plan)
    try:
        counts = apply_plan(plan, request.user)
    except PlanChanged as exc:
        _audit(request, 'import', plan, f'Apply refused: {exc}', success=False)
        messages.error(request, f'Apply refused: {exc}')
        return redirect('imports:rehearsal_detail', pk=pk)
    except PlanError as exc:
        messages.error(request, str(exc))
        return redirect('imports:rehearsal_detail', pk=pk)
    _audit(request, 'import', plan, f"Applied migration rehearsal: {counts['applied']} applied, "
                                    f"{counts['skipped']} skipped, {counts['failed']} failed",
           extra={'counts': counts, 'plan_hash': plan.reviewed_plan_hash})
    if counts['failed']:
        messages.warning(request, f"{counts['failed']} record(s) failed; everything else was applied. "
                                  'Fix the cause and click Apply again to resume.')
    else:
        messages.success(request, f"Applied: {counts['applied']} record(s), {counts['skipped']} skipped.")
    return redirect('imports:rehearsal_detail', pk=pk)


@login_required
@staff_required
@require_POST
def rehearsal_rollback(request, pk):
    plan = _plan(request, pk)
    from .migration.undo import rollback_plan
    try:
        report = rollback_plan(plan, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('imports:rehearsal_detail', pk=pk)
    _audit(request, 'delete', plan, 'Rolled back migration rehearsal'
           + ('' if report['complete'] else ' (partial - later edits kept)'),
           extra={k: len(v) for k, v in report.items() if isinstance(v, list)})
    msg = (f"Rollback: {len(report['deleted'])} deleted, {len(report['restored'])} restored, "
           f"{len(report['unlinked'])} unmapped, {len(report['kept'])} kept because they were edited "
           'or are in use after the import.')
    (messages.success if report['complete'] else messages.warning)(request, msg)
    for line in report['kept'][:10]:
        messages.info(request, f'Kept: {line}')
    return redirect('imports:rehearsal_detail', pk=pk)


@login_required
@staff_required
def rehearsal_report(request, pk):
    plan = _plan(request, pk)
    from .migration.report import build_report, records_csv, summary_csv
    fmt = request.GET.get('format', 'json')
    report = build_report(plan)
    _audit(request, 'export', plan, f'Downloaded reconciliation report ({fmt})')
    name = f'rehearsal-{plan.pk}-reconciliation'
    if fmt == 'csv':
        resp = HttpResponse(records_csv(report), content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="{name}.csv"'
    elif fmt == 'summary.csv':
        resp = HttpResponse(summary_csv(report), content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="{name}-summary.csv"'
    else:
        resp = HttpResponse(json.dumps(report, indent=2, default=str), content_type='application/json')
        resp['Content-Disposition'] = f'attachment; filename="{name}.json"'
    resp['Cache-Control'] = 'no-store'
    return resp


@login_required
@staff_required
def inventory_export(request, org_id):
    """Per-customer inventory (metadata only), sections gated by permission."""
    from .migration.inventory import export_inventory, inventory_csv
    allowed = accessible_org_ids(request)
    if allowed is not None and org_id not in allowed:
        raise Http404
    org = get_object_or_404(Organization, pk=org_id)
    export = export_inventory(request.user, org)
    if not export['sections']:
        _audit(request, 'export', org, 'Inventory export refused: no view permission', success=False)
        raise PermissionDenied('You have no view permission for this customer.')
    fmt = request.GET.get('format', 'csv')
    _audit(request, 'export', org, f'Exported customer inventory ({fmt}): ' + ', '.join(export['sections']),
           extra={'counts': export['counts'], 'omitted': export['omitted_sections']})
    if fmt == 'json':
        resp = HttpResponse(json.dumps(export, indent=2, default=str), content_type='application/json')
        resp['Content-Disposition'] = f'attachment; filename="inventory-{org.pk}.json"'
    else:
        resp = HttpResponse(inventory_csv(export), content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="inventory-{org.pk}.csv"'
    resp['Cache-Control'] = 'no-store'
    return resp
