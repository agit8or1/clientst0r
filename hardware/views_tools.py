"""Diagram, label and CSV views."""
from __future__ import annotations

import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from monitoring.models import Rack

from . import csv_io, diagrams as D, labels as L
from .access import can, org_get, org_view
from .export import export
from .models import Cable, DevicePort, DiagramLayout, HardwareDevice, LabelPrintLog, LabelTemplate

KINDS = {'connectivity': D.connectivity_data, 'vlan': D.vlan_data}


def _site(request, org):
    sid = request.GET.get('site') or request.POST.get('site')
    if sid and str(sid).isdigit():
        from locations.models import Location
        return Location.objects.filter(pk=sid).filter(organization=org).first()
    return None


def _saved_positions(org, kind, scope, user):
    mine = DiagramLayout.objects.filter(organization=org, kind=kind, scope=scope, user=user).first()
    shared = DiagramLayout.objects.filter(organization=org, kind=kind, scope=scope, user__isnull=True).first()
    pos = dict(shared.positions) if shared else {}
    if mine:
        pos.update(mine.positions)
    return pos


# --------------------------------------------------------------------------- racks

@org_view()
def rack_view(request, pk, org):
    rack = org_get(Rack, org, pk=pk)
    from monitoring.models import RackDevice
    placements = (RackDevice.objects.filter(rack=rack).select_related('asset__hardware__hardware_model')
                  .order_by('-start_unit'))
    used = sum(p.units for p in placements if p.board_position_x is None)
    return render(request, 'hardware/rack.html', {
        'org': org, 'rack': rack, 'front': D.rack_svg(rack, 'front'), 'rear': D.rack_svg(rack, 'rear'),
        'placements': placements, 'used': used, 'racks': Rack.objects.filter(organization=org).order_by('name')})


@org_view()
def rack_export(request, pk, face, fmt, org):
    rack = org_get(Rack, org, pk=pk)
    if face not in ('front', 'rear'):
        raise Http404
    svg = D.rack_svg(rack, face, for_export=True)
    return export(svg, fmt, f'rack-{rack.name}-{face}'.replace(' ', '_'))


# --------------------------------------------------------------------------- graph diagrams

@org_view()
def diagram(request, kind, org):
    if kind not in KINDS:
        raise Http404
    from locations.models import Location
    site = _site(request, org)
    return render(request, 'hardware/diagram.html', {
        'org': org, 'kind': kind, 'site': site,
        'sites': Location.objects.filter(organization=org).order_by('name'),
        'title': 'Physical connectivity' if kind == 'connectivity' else 'VLAN view',
        'page_data': {'kind': kind, 'data_url': reverse('hardware:api_diagram', args=[kind]) +
                      (f'?site={site.pk}' if site else ''),
                      'export_url': reverse('hardware:diagram_export', args=[kind]),
                      'site': site.pk if site else None}})


@org_view()
def api_diagram(request, kind, org):
    if kind not in KINDS:
        raise Http404
    site = _site(request, org)
    scope = f'site:{site.pk}' if site else 'all'
    if request.method == 'POST':
        try:
            body = json.loads(request.body or b'{}')
        except ValueError:
            return JsonResponse({'error': 'Malformed JSON.'}, status=400)
        positions = {k: {'x': round(float(v['x']), 1), 'y': round(float(v['y']), 1)}
                     for k, v in (body.get('positions') or {}).items()
                     if isinstance(v, dict) and str(k).startswith(('device:', 'vlan:'))}
        shared = body.get('shared') and can(request, 'assets_edit', org)
        lay, _ = DiagramLayout.objects.get_or_create(organization=org, kind=kind, scope=scope,
                                                     user=None if shared else request.user)
        # Merge: positions for nodes not sent (filtered out of view) are kept.
        merged = dict(lay.positions)
        merged.update(positions)
        lay.positions = merged
        lay.save()
        return JsonResponse({'ok': True, 'saved': len(positions), 'shared': bool(shared)})
    data = KINDS[kind](org, site.pk if site else None)
    saved = _saved_positions(org, kind, scope, request.user)
    data['positions'] = D.auto_positions(data['nodes'], saved, data['edges'])
    data['saved_keys'] = sorted(k for k in saved if k in data['positions'])
    return JsonResponse(data)


@org_view()
def diagram_export(request, kind, org):
    if kind not in KINDS:
        raise Http404
    site = _site(request, org)
    scope = f'site:{site.pk}' if site else 'all'
    fmt = request.POST.get('format') or request.GET.get('format') or 'svg'
    data = KINDS[kind](org, site.pk if site else None)
    saved = _saved_positions(org, kind, scope, request.user)
    if request.method == 'POST' and request.POST.get('positions'):
        try:
            saved.update(json.loads(request.POST['positions']))
        except ValueError:
            pass
    keep = request.POST.get('keys') or request.GET.get('keys')
    if keep:
        wanted = set(keep.split(','))
        data['nodes'] = [n for n in data['nodes'] if n['key'] in wanted]
    pos = D.auto_positions(data['nodes'], saved, data['edges'])
    title = 'Physical connectivity' if kind == 'connectivity' else 'VLAN view'
    sub = org.name + (f' · {site.name}' if site else '')
    svg = D.graph_svg(data, pos, title, sub, kind=kind)
    return export(svg, fmt, f'{kind}-{org.slug}')


# --------------------------------------------------------------------------- labels

def _templates(org):
    from django.db.models import Q
    L.ensure_default_templates()
    return LabelTemplate.objects.filter(Q(organization=org) | Q(organization__isnull=True)).order_by('kind', 'name')


def _ids(request, name):
    raw = request.POST.get(name) or request.GET.get(name) or ''
    return [int(x) for x in raw.replace(' ', '').split(',') if x.isdigit()]


@org_view()
def labels(request, org):
    tpls = _templates(org)
    kind = request.GET.get('kind') or request.POST.get('kind') or 'cable'
    tpl_id = request.GET.get('template') or request.POST.get('template')
    tpl = tpls.filter(pk=tpl_id).first() if tpl_id else tpls.filter(kind=kind).first()
    sel = {'devices': _ids(request, 'devices'), 'ports': _ids(request, 'ports'), 'cables': _ids(request, 'cables'),
           'racks': _ids(request, 'racks')}
    concise = (request.GET.get('concise') or request.POST.get('concise')) == '1'
    seq = None
    if request.GET.get('seq_pattern'):
        try:
            seq = (request.GET['seq_pattern'], int(request.GET.get('seq_start') or 1),
                   int(request.GET.get('seq_count') or 10))
        except ValueError:
            seq = None
    items, error, preview = [], '', ''
    if tpl is not None:
        try:
            items = L.apply_format(tpl, L.build_items(org, kind, request, concise=concise, sequence=seq,
                                                      include_qr=tpl.include_qr, **sel))
            if items:
                preview = L.preview_svg(tpl, items)
        except ValidationError as e:
            error = ' '.join(e.messages)
    # Helpful pickers
    devices = HardwareDevice.objects.filter(organization=org).select_related('asset', 'hardware_model').order_by(
        'asset__name')
    return render(request, 'hardware/labels.html', {
        'org': org, 'templates': tpls, 'tpl': tpl, 'kind': kind, 'kinds': LabelTemplate.KIND_CHOICES,
        'items': items, 'preview': preview, 'error': error, 'sel': sel, 'concise': concise,
        'sel_str': {k: ','.join(map(str, v)) for k, v in sel.items()}, 'seq': request.GET,
        'devices': devices, 'panels': [d for d in devices if d.hardware_model.category in (
            'patch_panel', 'fiber_panel')],
        'racks': Rack.objects.filter(organization=org).order_by('name'),
        'cables': Cable.objects.filter(organization=org).order_by('label')[:500],
        'can_edit': can(request, 'assets_edit', org), 'pages_pt': L.PAGE_SIZES})


@org_view()
def labels_pdf(request, org):
    tpls = _templates(org)
    tpl = get_object_or_404(tpls, pk=request.GET.get('template') or request.POST.get('template'))
    if request.GET.get('calibration') == '1':
        resp = HttpResponse(L.calibration_pdf(tpl), content_type='application/pdf')
        resp['Content-Disposition'] = f'inline; filename="calibration-{tpl.pk}.pdf"'
        return resp
    kind = request.GET.get('kind') or tpl.kind
    seq = None
    if request.GET.get('seq_pattern'):
        seq = (request.GET['seq_pattern'], int(request.GET.get('seq_start') or 1), int(request.GET.get('seq_count') or 10))
    try:
        items = L.apply_format(tpl, L.build_items(
            org, kind, request, devices=_ids(request, 'devices'), ports=_ids(request, 'ports'),
            cables=_ids(request, 'cables'), racks=_ids(request, 'racks'), concise=request.GET.get('concise') == '1',
            sequence=seq, include_qr=tpl.include_qr))
        pdf = L.render_pdf(tpl, items, start_slot=int(request.GET.get('skip') or 0))
    except (ValidationError, ValueError) as e:
        messages.error(request, ' '.join(getattr(e, 'messages', [str(e)])))
        return redirect(reverse('hardware:labels') + '?' + request.GET.urlencode())
    LabelPrintLog.objects.create(organization=org, template=tpl, kind=kind, label_count=len(items),
                                 items=[it.ref for it in items][:2000], created_by=request.user)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="labels-{kind}.pdf"'
    return resp


@org_view('assets_edit')
@require_POST
def label_template_save(request, org):
    P = request.POST
    tpl = None
    if P.get('id'):
        tpl = get_object_or_404(LabelTemplate, pk=P['id'], organization=org)
    else:
        tpl = LabelTemplate(organization=org)
    try:
        tpl.name = P['name'].strip()[:100] or 'Label'
        tpl.kind = P['kind'] if P['kind'] in dict(LabelTemplate.KIND_CHOICES) else 'port'
        for f in ('width_mm', 'height_mm', 'margin_mm', 'font_size_pt', 'page_margin_left_mm', 'page_margin_top_mm',
                  'gap_x_mm', 'gap_y_mm', 'offset_x_mm', 'offset_y_mm'):
            if P.get(f) not in (None, ''):
                setattr(tpl, f, P[f])
        for f in ('columns', 'rows', 'strip_cells'):
            if P.get(f) not in (None, ''):
                setattr(tpl, f, int(P[f]))
        tpl.page_size = P.get('page_size') if P.get('page_size') in dict(LabelTemplate.PAGE_CHOICES) else 'label'
        tpl.include_qr = P.get('include_qr') == '1'
        tpl.show_border = P.get('show_border') == '1'
        tpl.text_format = P.get('text_format', '')[:200]
        tpl.full_clean()
        L.page_geometry(tpl)
        tpl.save()
    except (ValidationError, ValueError, KeyError) as e:
        messages.error(request, ' '.join(getattr(e, 'messages', [str(e)])))
        return redirect('hardware:labels')
    messages.success(request, f'Label template "{tpl.name}" saved for {org}.')
    return redirect(reverse('hardware:labels') + f'?kind={tpl.kind}&template={tpl.pk}')


# --------------------------------------------------------------------------- CSV

@org_view()
def export_csv(request, what, org):
    if what == 'devices':
        content = csv_io.export_devices(org)
    elif what == 'cables':
        content = csv_io.export_cables(org)
    else:
        raise Http404
    resp = HttpResponse(content, content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="{org.slug}-{what}.csv"'
    return resp


@org_view('assets_create')
def import_csv(request, org):
    ctx = {'org': org}
    key = 'hw_csv_import'
    if request.method == 'POST' and request.POST.get('step') == 'confirm':
        staged = request.session.get(key)
        if not staged or staged.get('org') != org.pk:
            messages.error(request, 'Nothing to import (the preview expired). Upload the file again.')
            return redirect('hardware:import_csv')
        try:
            result = csv_io.apply(org, staged['what'], staged['rows'], request.user)
        except ValidationError as e:
            messages.error(request, 'Import failed and nothing was saved: ' + ' '.join(e.messages))
            return redirect('hardware:import_csv')
        del request.session[key]
        messages.success(request, f'Imported {result} {staged["what"]}.')
        return redirect('hardware:device_list' if staged['what'] == 'devices' else 'hardware:cable_list')
    if request.method == 'POST' and request.FILES.get('file'):
        what = request.POST.get('what') if request.POST.get('what') in ('devices', 'cables') else 'devices'
        f = request.FILES['file']
        if f.size > 2 * 1024 * 1024:
            messages.error(request, 'CSV files are limited to 2 MB.')
            return redirect('hardware:import_csv')
        try:
            text = f.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            messages.error(request, 'The file is not UTF-8 text.')
            return redirect('hardware:import_csv')
        rows = csv_io.validate(org, what, text)
        ctx.update(what=what, rows=rows, ok=[r for r in rows if not r['errors']],
                   bad=[r for r in rows if r['errors']])
        if rows and not ctx['bad']:
            request.session[key] = {'org': org.pk, 'what': what, 'rows': [r['data'] for r in rows]}
        else:
            request.session.pop(key, None)
    ctx['templates'] = {'devices': csv_io.DEVICE_COLUMNS, 'cables': csv_io.CABLE_COLUMNS}
    return render(request, 'hardware/import_csv.html', ctx)
