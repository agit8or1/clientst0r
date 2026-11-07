"""Shared hardware catalog: browse, coverage, import history, add/edit models, layout editor."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import connectors as C
from .access import can_manage_catalog, catalog_admin, catalog_view
from .catalog_import import ensure_revision_snapshot
from .layout import auto_layout, get_layout, save_layout, unplaced_components, validate_faces
from .models import (
    CatalogImportJob, CatalogImportRecord, CatalogSource, ComponentTemplate, HardwareModel, LayoutTemplate,
    Manufacturer, ModelRequest, PortMappingTemplate,
)
from .renderer import cached_face_svg

PRIORITY_MANUFACTURERS = ['Dell', 'HPE', 'Cisco', 'Juniper', 'Ubiquiti', 'MikroTik', 'Fortinet', 'SonicWall',
                          'Sophos', 'Netgate', 'WatchGuard', 'Ruckus', 'TP-Link', 'Extreme Networks', 'Supermicro',
                          'Lenovo', 'Synology', 'QNAP', 'APC', 'Eaton', 'Generic']


def _filtered(request):
    qs = HardwareModel.objects.select_related('manufacturer')
    q = request.GET.get('q', '').strip()
    for term in q.split()[:5]:
        qs = qs.filter(Q(model__icontains=term) | Q(manufacturer__name__icontains=term)
                       | Q(part_number__icontains=term))
    for f in ('kind', 'category'):
        if request.GET.get(f):
            qs = qs.filter(**{f: request.GET[f]})
    if request.GET.get('manufacturer'):
        qs = qs.filter(manufacturer__slug=request.GET['manufacturer'])
    acc = request.GET.get('accuracy')
    if acc == 'verified':
        qs = qs.filter(layouts__is_current=True, layouts__faces__front__accuracy='verified')
    elif acc == 'generic':
        qs = qs.filter(is_generic=True)
    elif acc == 'approximate':
        qs = qs.filter(is_generic=False).exclude(layouts__is_current=True, layouts__faces__front__accuracy='verified')
    prov = request.GET.get('provenance')
    if prov:
        qs = qs.filter(spec_provenance=prov)
    return qs, q


@catalog_view
def catalog(request):
    qs, q = _filtered(request)
    if not any(request.GET.get(k) for k in ('q', 'kind', 'category', 'manufacturer', 'accuracy', 'provenance')):
        # Unfiltered: start with the manufacturers MSPs meet most, devices first.
        from django.db.models import Case, IntegerField, Value, When
        prio = Case(*[When(manufacturer__name=m, then=Value(i)) for i, m in enumerate(PRIORITY_MANUFACTURERS)],
                    default=Value(len(PRIORITY_MANUFACTURERS)), output_field=IntegerField())
        kind_order = Case(When(kind='device', then=Value(0)), default=Value(1), output_field=IntegerField())
        qs = qs.annotate(_prio=prio, _kind=kind_order).order_by('_prio', '_kind', 'manufacturer__name', 'model')
    else:
        qs = qs.order_by('manufacturer__name', 'model')
    page = Paginator(qs, 48).get_page(request.GET.get('page'))
    accuracy = dict(LayoutTemplate.objects.filter(hardware_model__in=list(page.object_list), is_current=True)
                    .values_list('hardware_model_id', 'accuracy'))
    return render(request, 'hardware/catalog.html', {
        'page': page, 'q': q, 'params': request.GET, 'accuracy': accuracy,
        'kinds': HardwareModel.KIND_CHOICES, 'categories': HardwareModel.CATEGORY_CHOICES,
        'manufacturers': Manufacturer.objects.annotate(n=Count('models')).filter(n__gt=0).order_by('name'),
        'provenances': HardwareModel.PROVENANCE_CHOICES,
        'total': HardwareModel.objects.count(), 'source': CatalogSource.objects.filter(key='devicetype-library').first(),
        'can_admin': can_manage_catalog(request.user),
        'open_requests': ModelRequest.objects.filter(status='open').count() if can_manage_catalog(request.user) else 0,
    })


@catalog_view
def model_detail(request, pk):
    hm = get_object_or_404(HardwareModel.objects.select_related('manufacturer', 'source'), pk=pk)
    layout = get_layout(hm) if hm.kind != HardwareModel.KIND_RACK else None
    faces = list(layout.faces) if layout else []
    comps = hm.components.order_by('sort_order', 'id')
    by_class = {}
    for c in comps:
        by_class.setdefault(c.get_component_class_display(), []).append(c)
    return render(request, 'hardware/model_detail.html', {
        'hm': hm, 'layout': layout, 'faces': faces, 'by_class': by_class,
        'art': {f: cached_face_svg(hm, layout, f) for f in faces},
        'face_accuracy': {f: layout.face_accuracy(f) for f in faces} if layout else {},
        'unplaced': unplaced_components(hm, layout) if layout else [],
        'mappings': hm.port_mappings.select_related('front_port', 'rear_port')[:200],
        'device_count': hm.devices.count(), 'revisions': hm.revisions.all()[:10],
        'layout_history': hm.layouts.order_by('-version')[:10],
        'can_admin': can_manage_catalog(request.user),
        'upstream_json': json.dumps(hm.upstream_data, indent=2, default=str)[:20000] if hm.upstream_data else '',
    })


@catalog_view
def model_art(request, pk, face):
    hm = get_object_or_404(HardwareModel, pk=pk)
    if hm.kind == HardwareModel.KIND_RACK:
        raise Http404
    layout = get_layout(hm)
    variant = 'thumb' if request.GET.get('v') == 'thumb' else 'full'
    if face not in layout.faces:
        face = next(iter(layout.faces), None)
        if face is None:
            raise Http404
    svg = cached_face_svg(hm, layout, face, variant=variant)
    resp = HttpResponse(svg, content_type='image/svg+xml')
    # Catalog artwork holds no client data and is keyed by layout version.
    resp['Cache-Control'] = 'private, max-age=86400'
    resp['ETag'] = f'"{hm.pk}-{layout.version}-{face}-{variant}"'
    return resp


@catalog_view
def coverage(request):
    """Searchable coverage report: what the catalog holds, by manufacturer and category."""
    base = HardwareModel.objects.all()
    q = request.GET.get('q', '').strip()
    rows = (base.values('manufacturer__name', 'manufacturer__slug')
            .annotate(total=Count('id'), devices=Count('id', filter=Q(kind='device')),
                      modules=Count('id', filter=Q(kind='module')), racks=Count('id', filter=Q(kind='rack')),
                      generic=Count('id', filter=Q(is_generic=True)),
                      documented=Count('id', filter=Q(spec_provenance='manufacturer')),
                      verified=Count('id', filter=Q(layouts__is_current=True,
                                                    layouts__faces__front__accuracy='verified')))
            .order_by('-total'))
    if q:
        rows = rows.filter(manufacturer__name__icontains=q)
    cats = (base.values('kind', 'category').annotate(n=Count('id'),
                                                    inferred=Count('id', filter=Q(category_source='inferred')))
            .order_by('kind', '-n'))
    names = dict(HardwareModel.CATEGORY_CHOICES)
    priority = {r['manufacturer__name']: r for r in base.values('manufacturer__name').annotate(
        total=Count('id'), devices=Count('id', filter=Q(kind='device')))}
    job = CatalogImportJob.objects.filter(is_preview=False).first()
    unsupported = {}
    if job:
        for rec in job.records.exclude(unsupported_fields=[]).values_list('unsupported_fields', flat=True)[:20000]:
            for f in rec:
                unsupported[f] = unsupported.get(f, 0) + 1
    verified_total = LayoutTemplate.objects.filter(is_current=True, faces__front__accuracy='verified').count()
    generic_total = base.filter(is_generic=True).count()
    return render(request, 'hardware/coverage.html', {
        'rows': rows, 'q': q, 'cats': [dict(c, label=names.get(c['category'], c['category'])) for c in cats],
        'priority': [(m, priority.get(m, {'total': 0, 'devices': 0})) for m in PRIORITY_MANUFACTURERS],
        'job': job, 'unsupported': sorted(unsupported.items(), key=lambda x: -x[1]),
        'totals': {
            'all': base.count(), 'device': base.filter(kind='device').count(),
            'module': base.filter(kind='module').count(), 'rack': base.filter(kind='rack').count(),
            'generic': generic_total,
            'approximate': base.exclude(kind='rack').count() - verified_total - generic_total,
            'manufacturer_documented': base.filter(spec_provenance='manufacturer').count(),
            'local': base.filter(upstream_path='').count(),
            'verified_layouts': verified_total,
            'layouts_materialized': LayoutTemplate.objects.filter(is_current=True).count(),
        },
        'source': CatalogSource.objects.filter(key='devicetype-library').first(),
    })


@catalog_view
def import_jobs(request):
    return render(request, 'hardware/import_jobs.html', {
        'jobs': CatalogImportJob.objects.select_related('source')[:50],
        'source': CatalogSource.objects.filter(key='devicetype-library').first(),
        'can_admin': can_manage_catalog(request.user)})


@catalog_view
def import_job_detail(request, pk):
    job = get_object_or_404(CatalogImportJob, pk=pk)
    recs = job.records.select_related('hardware_model').order_by('status', 'path')
    status = request.GET.get('status')
    if status:
        recs = recs.filter(status=status)
    q = request.GET.get('q', '').strip()
    if q:
        recs = recs.filter(Q(path__icontains=q) | Q(message__icontains=q))
    page = Paginator(recs, 200).get_page(request.GET.get('page'))
    return render(request, 'hardware/import_job.html', {
        'job': job, 'page': page, 'status': status, 'q': q,
        'status_counts': job.records.values('status').annotate(n=Count('id')).order_by('status')})


# --------------------------------------------------------------------------- editing

def _mark_local(hm, *fields):
    lf = set(hm.local_fields or [])
    lf.update(fields)
    hm.local_fields = sorted(lf)
    if hm.upstream_path:
        hm.locally_modified = True


@catalog_admin
def model_add(request):
    """Add a model the catalog lacks: start blank, from a generic template, or copy an existing model."""
    src = None
    if request.GET.get('from') and str(request.GET['from']).isdigit():
        src = HardwareModel.objects.filter(pk=request.GET['from']).first()
    req = None
    if request.GET.get('request'):
        req = ModelRequest.objects.filter(pk=request.GET['request']).first()
    if request.method == 'POST':
        P = request.POST
        errors = []
        mname = P.get('manufacturer', '').strip()
        model = P.get('model', '').strip()
        if not mname or not model:
            errors.append('Manufacturer and model are required.')
        try:
            u = Decimal(P.get('u_height') or '0')
        except InvalidOperation:
            errors.append('U height must be a number.')
            u = Decimal(0)
        if not errors:
            with transaction.atomic():
                m = Manufacturer.objects.filter(name__iexact=mname).first()
                if m is None:
                    base = slugify(mname) or 'manufacturer'
                    slug, n = base, 2
                    while Manufacturer.objects.filter(slug=slug).exists():
                        slug, n = f'{base}-{n}', n + 1
                    m = Manufacturer.objects.create(name=mname, slug=slug)
                kind = P.get('kind') if P.get('kind') in dict(HardwareModel.KIND_CHOICES) else 'device'
                slug = 'local-' + slugify(f'{model}')[:200]
                if HardwareModel.objects.filter(manufacturer=m, kind=kind, slug=slug).exists():
                    errors.append(f'{m} {model} already exists in the catalog.')
                else:
                    hm = HardwareModel.objects.create(
                        manufacturer=m, model=model, slug=slug, kind=kind, part_number=P.get('part_number', '')[:200],
                        category=P.get('category') if P.get('category') in HardwareModel.CATEGORY_KEYS else 'other',
                        category_source='manual', u_height=u, is_full_depth=P.get('is_full_depth') == '1',
                        description=P.get('description', ''), spec_provenance=P.get('spec_provenance') or 'local',
                        spec_source_url=P.get('spec_source_url', '')[:500], spec_notes=P.get('spec_notes', ''),
                        is_generic=P.get('is_generic') == '1', created_by=request.user)
                    copy_from = HardwareModel.objects.filter(pk=P.get('copy_from')).first() if P.get('copy_from') else None
                    if copy_from:
                        _copy_components(copy_from, hm)
                    if req:
                        req.status, req.created_model = 'created', hm
                        req.save()
                    from .services import record
                    record(request.user, 'create', hm, {'model': [None, str(hm)]}, hardware_model=hm)
                    messages.success(request, f'{hm} created. Add its ports, then arrange the layout.')
                    return redirect('hardware:model_edit', pk=hm.pk)
        return render(request, 'hardware/model_add.html', {
            'errors': errors, 'form': P, 'categories': HardwareModel.CATEGORY_CHOICES, 'src': src,
            'provenances': HardwareModel.PROVENANCE_CHOICES, 'kinds': HardwareModel.KIND_CHOICES})
    initial = {}
    if req:
        initial = {'manufacturer': req.manufacturer, 'model': req.model, 'part_number': req.part_number,
                   'category': req.category, 'spec_source_url': req.datasheet_url}
    return render(request, 'hardware/model_add.html', {
        'form': initial, 'categories': HardwareModel.CATEGORY_CHOICES, 'src': src, 'req': req,
        'provenances': HardwareModel.PROVENANCE_CHOICES, 'kinds': HardwareModel.KIND_CHOICES,
        'generics': HardwareModel.objects.filter(is_generic=True, upstream_path='').select_related('manufacturer')})


def _copy_components(src, dst):
    comps = []
    for c in src.components.all():
        comps.append(ComponentTemplate(
            hardware_model=dst, origin='local', **{f: getattr(c, f) for f in (
                'component_class', 'name', 'label', 'type', 'connector', 'description', 'mgmt_only', 'enabled',
                'poe_mode', 'poe_type', 'rf_role', 'positions', 'color', 'maximum_draw', 'allocated_draw',
                'feed_leg', 'power_port_name', 'bay_position', 'part_id', 'item_manufacturer', 'combo_group',
                'sort_order', 'extra')}))
    ComponentTemplate.objects.bulk_create(comps)
    by = {(c.component_class, c.name): c for c in dst.components.all()}
    for m in src.port_mappings.select_related('front_port', 'rear_port'):
        PortMappingTemplate.objects.create(hardware_model=dst, front_port=by[(C.CLASS_FRONT_PORT, m.front_port.name)],
                                           front_position=m.front_position,
                                           rear_port=by[(C.CLASS_REAR_PORT, m.rear_port.name)],
                                           rear_position=m.rear_position)


@catalog_admin
def model_edit(request, pk):
    """Edit model fields and component templates. Changes bump the model revision;
    installed devices pick them up only through "preview template update"."""
    hm = get_object_or_404(HardwareModel.objects.select_related('manufacturer'), pk=pk)
    if request.method == 'POST':
        P = request.POST
        action = P.get('action')
        try:
            with transaction.atomic():
                if action == 'fields':
                    changed = []
                    for f in ('part_number', 'description', 'spec_source_url', 'spec_notes'):
                        if f in P and getattr(hm, f) != P[f]:
                            setattr(hm, f, P[f])
                            changed.append(f)
                    if P.get('category') in HardwareModel.CATEGORY_KEYS and P['category'] != hm.category:
                        hm.category, hm.category_source = P['category'], 'manual'
                        changed.append('category')
                    if P.get('spec_provenance') in dict(HardwareModel.PROVENANCE_CHOICES):
                        if hm.spec_provenance != P['spec_provenance']:
                            hm.spec_provenance = P['spec_provenance']
                            changed.append('spec_provenance')
                    if P.get('u_height') not in (None, ''):
                        u = Decimal(P['u_height'])
                        if u != hm.u_height:
                            hm.u_height = u
                            changed.append('u_height')
                    _mark_local(hm, *[c for c in changed if c not in ('category',)])
                    hm.save()
                    messages.success(request, 'Model saved.' if changed else 'No changes.')
                elif action == 'add_component':
                    cls = P.get('component_class')
                    if cls not in dict(C.TEMPLATE_CLASSES):
                        raise ValidationError('Unknown component kind.')
                    names = _expand_names(P.get('name', ''), int(P.get('count') or 1))
                    t = P.get('type', '').strip()
                    ensure_revision_snapshot(hm, user=request.user, reason='Before component change')
                    base = hm.components.count()
                    for i, n in enumerate(names, 1):
                        eff, conn = C.classify(cls, t)
                        ComponentTemplate.objects.create(
                            hardware_model=hm, component_class=eff, name=n, type=t,
                            connector=P.get('connector') or conn, label=_label_for(n, P.get('label', ''), i),
                            mgmt_only=P.get('mgmt_only') == '1', poe_mode=P.get('poe_mode', ''),
                            positions=int(P.get('positions') or 1), combo_group=P.get('combo_group', '')[:40],
                            bay_position=P.get('bay_position', '')[:30], origin='local', sort_order=base + i)
                    hm.revision += 1
                    _mark_local(hm, 'components')
                    hm.save()
                    messages.success(request, f'Added {len(names)} component(s). Revision {hm.revision}.')
                elif action == 'delete_component':
                    c = get_object_or_404(ComponentTemplate, hardware_model=hm, pk=P.get('component'))
                    ensure_revision_snapshot(hm, user=request.user, reason='Before component change')
                    c.delete()
                    hm.revision += 1
                    _mark_local(hm, 'components')
                    hm.save()
                    messages.success(request, f'Removed {c.name}. Devices keep their existing port until '
                                              f'a technician reviews the template update.')
                elif action == 'combo':
                    ids = P.getlist('components')
                    group = P.get('combo_group', '').strip()[:40]
                    ensure_revision_snapshot(hm, user=request.user, reason='Before combo change')
                    hm.components.filter(pk__in=ids).update(combo_group=group)
                    hm.revision += 1
                    _mark_local(hm, 'components')
                    hm.save()
                    messages.success(request, 'Combo group updated.')
                elif action == 'mapping':
                    f = get_object_or_404(ComponentTemplate, hardware_model=hm, pk=P.get('front'),
                                          component_class=C.CLASS_FRONT_PORT)
                    r = get_object_or_404(ComponentTemplate, hardware_model=hm, pk=P.get('rear'),
                                          component_class=C.CLASS_REAR_PORT)
                    PortMappingTemplate.objects.update_or_create(
                        hardware_model=hm, front_port=f, front_position=int(P.get('front_position') or 1),
                        defaults={'rear_port': r, 'rear_position': int(P.get('rear_position') or 1)})
                    hm.revision += 1
                    _mark_local(hm, 'port_mappings')
                    hm.save()
                    messages.success(request, 'Mapping saved.')
                if action in ('add_component', 'delete_component'):
                    lay = hm.layouts.filter(is_current=True).first()
                    if lay and lay.auto_generated:
                        from .layout import refresh_auto_layout
                        refresh_auto_layout(hm)
        except (ValidationError, ValueError, InvalidOperation, IntegrityError) as e:
            messages.error(request, ' '.join(getattr(e, 'messages', [str(e) or 'Invalid value.'])))
        return redirect('hardware:model_edit', pk=hm.pk)
    return render(request, 'hardware/model_edit.html', {
        'hm': hm, 'components': hm.components.order_by('sort_order', 'id'),
        'classes': C.TEMPLATE_CLASSES, 'connectors': C.CONNECTOR_CHOICES,
        'categories': HardwareModel.CATEGORY_CHOICES, 'provenances': HardwareModel.PROVENANCE_CHOICES,
        'fronts': hm.components.filter(component_class=C.CLASS_FRONT_PORT),
        'rears': hm.components.filter(component_class=C.CLASS_REAR_PORT),
        'mappings': hm.port_mappings.select_related('front_port', 'rear_port'),
        'device_count': hm.devices.count()})


def _expand_names(pattern, count):
    """"Port {n}" with count 24 → Port 1..Port 24; "eth0" with count 1 → eth0."""
    pattern = pattern.strip()
    if not pattern:
        raise ValidationError('Give the component a name.')
    if count > 1 or '{n' in pattern:
        if '{n' not in pattern:
            pattern += ' {n}'
        try:
            return [pattern.format(n=i)[:100] for i in range(1, max(1, min(count, 512)) + 1)]
        except (KeyError, ValueError, IndexError):
            raise ValidationError('Use {n} in the name pattern.')
    return [pattern[:100]]


def _label_for(name, label_pattern, i):
    if label_pattern and '{n' in label_pattern:
        try:
            return label_pattern.format(n=i)[:100]
        except (KeyError, ValueError, IndexError):
            return ''
    return label_pattern[:100]


@catalog_admin
def layout_editor(request, pk):
    hm = get_object_or_404(HardwareModel.objects.select_related('manufacturer'), pk=pk)
    layout = get_layout(hm)
    if request.method == 'POST':
        try:
            data = json.loads(request.body or b'{}')
        except ValueError:
            return JsonResponse({'error': 'Malformed JSON.'}, status=400)
        if data.get('action') == 'auto':
            return JsonResponse({'faces': auto_layout(hm)['faces']})
        faces = data.get('faces') or {}
        errors = validate_faces(hm, faces)
        accuracy = data.get('accuracy') or LayoutTemplate.ACCURACY_APPROXIMATE
        if accuracy not in dict(LayoutTemplate.ACCURACY_CHOICES):
            errors.append('Unknown accuracy state.')
        face_accs = {f.get('accuracy', accuracy) for f in faces.values()}
        if 'verified' in face_accs and not (data.get('source_url') or '').strip():
            errors.append('A verified face needs the document it was checked against (source URL).')
        if hm.is_generic and 'verified' in face_accs:
            errors.append('A generic template cannot be marked verified.')
        if errors:
            return JsonResponse({'errors': errors}, status=400)
        # Overall accuracy is the weakest face.
        order = ['generic', 'approximate', 'verified']
        overall = min(face_accs or {accuracy}, key=order.index)
        lay = save_layout(hm, faces, accuracy=overall, user=request.user, auto_generated=False,
                          source_url=(data.get('source_url') or '')[:500], source_notes=data.get('source_notes') or '')
        hm.refresh_from_db()
        _mark_local(hm, 'layout')
        hm.save(update_fields=['local_fields', 'locally_modified'])
        from .services import record
        record(request.user, 'layout', hm, {'layout_version': [layout.version, lay.version],
                                            'accuracy': [layout.accuracy, overall]}, hardware_model=hm)
        return JsonResponse({'ok': True, 'version': lay.version, 'revision': hm.revision})
    comps = [{'key': str(c.key), 'name': c.name, 'label': c.label, 'class': c.component_class,
              'class_label': c.get_component_class_display(), 'connector': c.connector or 'generic',
              'w': C.CONNECTORS.get(c.connector or 'generic', C.CONNECTORS['generic'])['w'],
              'h': C.CONNECTORS.get(c.connector or 'generic', C.CONNECTORS['generic'])['h'],
              'bay': c.component_class in (C.CLASS_MODULE_BAY, C.CLASS_DEVICE_BAY)}
             for c in hm.components.order_by('sort_order', 'id')
             if c.component_class not in (C.CLASS_LOGICAL, C.CLASS_WIRELESS, C.CLASS_INVENTORY_ITEM)]
    return render(request, 'hardware/layout_editor.html', {
        'hm': hm, 'layout': layout, 'editor_data': {
            'faces': layout.faces, 'components': comps, 'accuracy': layout.accuracy,
            'source_url': layout.source_url, 'source_notes': layout.source_notes, 'version': layout.version,
            'generic': hm.is_generic,
            'preview_url': reverse('hardware:layout_preview', args=[hm.pk]),
            'save_url': reverse('hardware:layout_editor', args=[hm.pk])}})


@catalog_admin
@require_POST
def layout_preview(request, pk):
    """Render submitted (unsaved) geometry exactly as it would be cached."""
    from .renderer import render_face
    hm = get_object_or_404(HardwareModel, pk=pk)
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'Malformed JSON.'}, status=400)
    faces = data.get('faces') or {}
    errors = validate_faces(hm, faces)
    out = {}
    for name, face in faces.items():
        try:
            out[name] = render_face(hm, name, face, px_per_mm=2.0)
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f'{name}: {e}')
    return JsonResponse({'svg': out, 'errors': errors})


@catalog_admin
def model_requests(request):
    if request.method == 'POST':
        r = get_object_or_404(ModelRequest, pk=request.POST.get('request'))
        if request.POST.get('action') == 'decline':
            r.status = 'declined'
            r.save(update_fields=['status', 'updated_at'])
            messages.info(request, 'Request declined.')
        return redirect('hardware:model_requests')
    return render(request, 'hardware/model_requests.html', {
        'requests': ModelRequest.objects.select_related('organization', 'requested_by', 'created_model')[:200]})
