"""Documentation readiness views.

Standards, exceptions, the repair queue and the broken-relationship report are
MSP-staff only. A customer's readiness page is readable by anyone holding
docs_view in that customer; customer users get it read-only.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.models import Organization

from . import scoring
from .forms import ExceptionForm, RequirementFormSet, StandardForm
from .models import DocumentationStandard, StandardException
from .permissions import LinkPerms, can_view_org, is_msp_staff, readable_org_ids, require_staff
from .relationships import REASON_LABELS, deletable, find_broken_relationships


def _audit(request, action, obj, description, organization=None, extra=None):
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=request.user, action=action, organization=organization,
            object_type=obj._meta.model_name, object_id=obj.pk, object_repr=str(obj)[:255],
            description=description, ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500], path=request.path,
            extra_data=extra or {})
    except Exception:  # auditing must never break the action itself
        pass


def _readable_orgs(user):
    qs = Organization.objects.filter(is_active=True).order_by('name')
    allowed = readable_org_ids(user)
    if allowed is not None:
        qs = qs.filter(pk__in=allowed)
    return qs


def _get_viewable_org(request, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    if not can_view_org(request.user, org):
        raise Http404
    return org


def _redact(result, perms):
    """Hide record names/links the viewer may not follow."""
    shown = []
    for rec in result.records:
        if rec.kind in perms:
            shown.append(rec)
        else:
            shown.append(scoring.Record(rec.kind, rec.id, f'(hidden {rec.kind})', '', ''))
    result.records = shown
    return result


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

@login_required
def overview(request):
    orgs = list(_readable_orgs(request.user))
    standards = scoring.active_standards()
    std_filter = request.GET.get('standard')
    if std_filter:
        standards = [s for s in standards if str(s.pk) == std_filter]
    results = scoring.evaluate_many(orgs, standards=standards)
    rows = []
    for org in orgs:
        r = results[org.pk]
        rows.append({'org': org, 'score': r.score, 'standards': len(r.standards),
                     'unmet': len(r.unmet)})
    rows.sort(key=lambda x: (x['score'] is None, x['score'] if x['score'] is not None else 0,
                             x['org'].name))
    return render(request, 'readiness/overview.html', {
        'rows': rows, 'standards': scoring.active_standards(), 'std_filter': std_filter,
        'is_staff': is_msp_staff(request.user),
    })


@login_required
def org_readiness(request, org_id):
    org = _get_viewable_org(request, org_id)
    staff = is_msp_staff(request.user)
    readiness = scoring.evaluate(org)
    perms = LinkPerms(request.user).kinds_for(org)
    for s in readiness.standards:
        for r in s.results:
            _redact(r, perms)
            if not staff:
                r.fix = None
    current = getattr(request, 'current_organization', None)
    ctx = {
        'org': org, 'readiness': readiness, 'is_staff': staff,
        'exceptions': (StandardException.objects.filter(organization=org)
                       .select_related('standard', 'requirement', 'created_by')
                       if staff else []),
        'exception_form': ExceptionForm() if staff else None,
        'needs_switch': staff and (current is None or current.pk != org.pk),
    }
    return render(request, 'readiness/org_readiness.html', ctx)


@login_required
def repair_queue(request):
    require_staff(request.user)
    orgs = list(_readable_orgs(request.user))
    org_filter = request.GET.get('customer') or ''
    std_filter = request.GET.get('standard') or ''
    if org_filter:
        orgs = [o for o in orgs if str(o.pk) == org_filter]
    all_standards = scoring.active_standards()
    standards = [s for s in all_standards if not std_filter or str(s.pk) == std_filter]
    results = scoring.evaluate_many(orgs, standards=standards)
    link_perms = LinkPerms(request.user)
    items = []
    for org in orgs:
        perms = link_perms.kinds_for(org)
        for sres, res in results[org.pk].unmet:
            _redact(res, perms)
            items.append({'org': org, 'standard': sres.standard, 'result': res})
    owners = sorted({i['result'].owner for i in items if i['result'].owner is not None},
                    key=lambda u: (u.get_full_name() or u.username).lower())
    owner_filter = request.GET.get('owner') or ''
    if owner_filter == 'unassigned':
        items = [i for i in items if i['result'].owner is None]
    elif owner_filter:
        items = [i for i in items if i['result'].owner is not None
                 and str(i['result'].owner.pk) == owner_filter]
    return render(request, 'readiness/repair_queue.html', {
        'items': items, 'customers': list(_readable_orgs(request.user)),
        'standards': all_standards, 'org_filter': org_filter, 'std_filter': std_filter,
        'owner_filter': owner_filter, 'owners': owners,
    })


# ---------------------------------------------------------------------------
# Standards
# ---------------------------------------------------------------------------

@login_required
def standard_list(request):
    require_staff(request.user)
    standards = DocumentationStandard.objects.prefetch_related('requirements').order_by('name')
    return render(request, 'readiness/standard_list.html', {'standards': standards})


def _signature(standard):
    if not standard.pk:
        return None
    standard = DocumentationStandard.objects.get(pk=standard.pk)
    return (
        standard.name, standard.description, standard.scope, standard.scope_value,
        standard.is_active,
        tuple(standard.requirements.order_by('pk').values_list(
            'pk', 'title', 'kind', 'params', 'weight', 'description', 'order')),
    )


@login_required
def standard_edit(request, pk=None):
    require_staff(request.user)
    standard = get_object_or_404(DocumentationStandard, pk=pk) if pk else DocumentationStandard()
    if request.method == 'POST':
        form = StandardForm(request.POST, instance=standard)
        formset = RequirementFormSet(request.POST, instance=standard, prefix='req')
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                before = _signature(standard)
                created = standard.pk is None
                obj = form.save(commit=False)
                if created:
                    obj.created_by = request.user
                obj.save()
                formset.instance = obj
                formset.save()
                if not created and _signature(obj) != before:
                    DocumentationStandard.objects.filter(pk=obj.pk).update(version=obj.version + 1)
                    obj.refresh_from_db()
            _audit(request, 'create' if created else 'update', obj,
                   f'{"Created" if created else "Edited"} documentation standard "{obj.name}" '
                   f'(version {obj.version})')
            messages.success(request, f'Saved "{obj.name}" (version {obj.version}).')
            return redirect('readiness:standard_list')
    else:
        form = StandardForm(instance=standard)
        formset = RequirementFormSet(instance=standard, prefix='req')
    return render(request, 'readiness/standard_form.html', {
        'form': form, 'formset': formset, 'standard': standard,
    })


@login_required
@require_POST
def standard_delete(request, pk):
    require_staff(request.user)
    standard = get_object_or_404(DocumentationStandard, pk=pk)
    _audit(request, 'delete', standard, f'Deleted documentation standard "{standard.name}"')
    standard.delete()
    messages.success(request, 'Standard deleted.')
    return redirect('readiness:standard_list')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

@login_required
@require_POST
def exception_add(request, org_id):
    require_staff(request.user)
    org = _get_viewable_org(request, org_id)
    form = ExceptionForm(request.POST)
    if form.is_valid():
        exc = form.save(commit=False)
        exc.organization = org
        exc.created_by = request.user
        exc.save()
        target = exc.requirement.title if exc.requirement_id else 'whole standard'
        _audit(request, 'create', exc,
               f'Accepted readiness exception for {org.name}: {exc.standard.name} / {target}',
               organization=org, extra={'reason': exc.reason,
                                        'expires_at': exc.expires_at.isoformat() if exc.expires_at else None})
        messages.success(request, 'Exception recorded.')
    else:
        for field, errs in form.errors.items():
            for e in errs:
                messages.error(request, f'{field}: {e}' if field != '__all__' else e)
    return redirect('readiness:org_readiness', org_id=org.pk)


@login_required
@require_POST
def exception_delete(request, pk):
    require_staff(request.user)
    exc = get_object_or_404(StandardException.objects.select_related('organization', 'standard'), pk=pk)
    org = exc.organization
    if not can_view_org(request.user, org):
        raise Http404
    _audit(request, 'delete', exc, f'Removed readiness exception for {org.name}: {exc}',
           organization=org, extra={'reason': exc.reason})
    exc.delete()
    messages.success(request, 'Exception removed.')
    return redirect('readiness:org_readiness', org_id=org.pk)


# ---------------------------------------------------------------------------
# Broken relationships
# ---------------------------------------------------------------------------

@login_required
def broken_relationships(request):
    require_staff(request.user)
    allowed = readable_org_ids(request.user)
    if request.method == 'POST':
        ids = {int(i) for i in request.POST.getlist('ids') if i.isdigit()}
        # Only rows that are still broken (re-checked now) and deletable.
        broken = deletable(find_broken_relationships(allowed), include_other_customer=True)
        targets = [b.relationship for b in broken if b.relationship.pk in ids]
        for rel in targets:
            _audit(request, 'delete', rel, f'Deleted broken relationship {rel}',
                   organization=rel.organization)
            rel.delete()
        messages.success(request, f'Deleted {len(targets)} broken relationship(s).')
        return redirect('readiness:broken_relationships')
    broken = find_broken_relationships(allowed)
    ok_ids = {b.relationship.pk for b in deletable(broken, include_other_customer=True)}
    groups = {}
    for b in broken:
        groups.setdefault(b.relationship.organization, []).append(
            {'b': b, 'deletable': b.relationship.pk in ok_ids})
    return render(request, 'readiness/broken_relationships.html', {
        'groups': sorted(groups.items(), key=lambda kv: kv[0].name),
        'total': len(broken), 'reason_labels': REASON_LABELS,
    })
