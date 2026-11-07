"""Client inventory views (pages + session JSON API)."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from monitoring.models import Rack, VLAN, VLANGroup

from . import connectors as C
from . import services as S
from .access import can, can_manage_catalog, current_org, org_filter_ids, org_get, org_view
from .device_art import device_face_svg, device_faces
from .layout import get_layout
from .models import (
    Cable, CableTermination, DevicePort, HardwareChange, HardwareDevice, HardwareModel, InstalledModule, LayoutTemplate,
    LinkAggregationGroup, ModelRequest, ModuleBay, PortMapping,
)
from .payloads import device_ports_json, device_summary, port_json, port_queryset, vlan_color, vlan_json


def _err(e, status=400):
    if isinstance(e, ValidationError):
        if hasattr(e, 'message_dict'):
            msgs = [m for v in e.message_dict.values() for m in v]
        else:
            msgs = e.messages
        return JsonResponse({'error': ' '.join(msgs)}, status=status)
    return JsonResponse({'error': str(e)}, status=status)


def _body(request):
    if request.content_type == 'application/json':
        try:
            return json.loads(request.body or b'{}')
        except ValueError:
            raise ValidationError('Malformed JSON.')
    return request.POST.dict()


def _vlan(org, value):
    if value in (None, '', 0, '0'):
        return None
    try:
        return VLAN.objects.select_related('vlan_group').get(organization=org, pk=int(value))
    except (VLAN.DoesNotExist, ValueError, TypeError):
        raise ValidationError('VLAN not found for this client.')


def _vlans(org, values):
    ids = [int(v) for v in (values or []) if str(v).strip().isdigit()]
    found = list(VLAN.objects.select_related('vlan_group').filter(organization=org, pk__in=ids))
    if len(found) != len(set(ids)):
        raise ValidationError('One or more tagged VLANs are not defined for this client.')
    return found


def _org_vlans(org):
    return [vlan_json(v) for v in VLAN.objects.filter(organization=org).select_related('vlan_group')
            .order_by('vlan_group__name', 'vlan_id')]


# =============================================================================
# Pages
# =============================================================================

@org_view()
def device_list(request, org):
    qs = (HardwareDevice.objects.filter(organization=org)
          .select_related('asset', 'hardware_model__manufacturer', 'site')
          .annotate(n_ports=Count('ports', distinct=True),
                    n_cabled=Count('ports', filter=Q(ports__cable_termination__isnull=False), distinct=True)))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(asset__name__icontains=q) | Q(asset__hostname__icontains=q)
                       | Q(asset__serial_number__icontains=q) | Q(asset__asset_tag__icontains=q)
                       | Q(hardware_model__model__icontains=q) | Q(hardware_model__manufacturer__name__icontains=q))
    cat = request.GET.get('category', '')
    if cat:
        qs = qs.filter(hardware_model__category=cat)
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs.order_by('asset__name'), 60).get_page(request.GET.get('page'))
    cats = (HardwareDevice.objects.filter(organization=org).values_list('hardware_model__category', flat=True)
            .distinct())
    return render(request, 'hardware/device_list.html', {
        'org': org, 'page': page, 'q': q, 'category': cat, 'status': status,
        'categories': [(c, dict(HardwareModel.CATEGORY_CHOICES).get(c, c)) for c in sorted(set(cats))],
        'statuses': HardwareDevice.STATUS_CHOICES,
        'can_create': can(request, 'assets_create', org), 'can_edit': can(request, 'assets_edit', org),
        'racks': Rack.objects.filter(organization=org).order_by('name'),
        'cable_count': Cable.objects.filter(organization=org).count(),
    })


def _site_choices(org):
    from locations.models import Location
    return Location.objects.filter(Q(organization=org) | Q(associated_organizations=org)).distinct().order_by('name')


@org_view('assets_create')
def device_add(request, org):
    sites = _site_choices(org)
    racks = Rack.objects.filter(organization=org).order_by('name')
    ctx = {'org': org, 'sites': sites, 'racks': racks, 'statuses': HardwareDevice.STATUS_CHOICES,
           'form': request.POST, 'model': None}
    model_id = request.POST.get('hardware_model') or request.GET.get('model')
    if model_id and str(model_id).isdigit():
        ctx['model'] = HardwareModel.objects.filter(pk=model_id, kind=HardwareModel.KIND_DEVICE).select_related(
            'manufacturer').first()
    if request.method == 'POST':
        errors = []
        hm = ctx['model']
        name = request.POST.get('name', '').strip()
        if hm is None:
            errors.append('Choose a manufacturer and model (or a generic template).')
        if not name:
            errors.append('Give the device a name (hostname or label, e.g. XYZ-SW-01).')
        site = None
        if request.POST.get('site'):
            site = sites.filter(pk=request.POST['site']).first()
            if site is None:
                errors.append('That site is not available for this client.')
        rack = None
        if request.POST.get('rack'):
            rack = racks.filter(pk=request.POST['rack']).first()
            if rack is None:
                errors.append('That rack is not available for this client.')
        if not errors:
            try:
                with transaction.atomic():
                    device = S.create_device(
                        org, hm, name, user=request.user, site=site, room=request.POST.get('room', '').strip()[:100],
                        location_detail=request.POST.get('location_detail', '').strip()[:200],
                        status=request.POST.get('status') or 'active',
                        platform=request.POST.get('platform', '').strip()[:100],
                        hostname=request.POST.get('hostname', '').strip()[:255] or name,
                        serial_number=request.POST.get('serial_number', '').strip()[:255],
                        asset_tag=request.POST.get('asset_tag', '').strip()[:100],
                        ip_address=request.POST.get('ip_address', '').strip() or None)
                    if rack and request.POST.get('position'):
                        S.place_in_rack(device, rack, int(request.POST['position']),
                                        request.POST.get('face') or 'front', user=request.user)
            except (ValidationError, ValueError) as e:
                errors.extend(getattr(e, 'messages', [str(e)]))
            else:
                messages.success(request, f'{name} added. Click any port to document it.')
                return redirect('hardware:device_detail', pk=device.pk)
        ctx['errors'] = errors
    return render(request, 'hardware/device_add.html', ctx)


@org_view()
def device_detail(request, pk, org):
    device = get_object_or_404(HardwareDevice.objects.select_related(
        'asset', 'hardware_model__manufacturer', 'site', 'parent_device__asset'), organization=org, pk=pk)
    layout, faces = device_faces(device)
    art = {f: device_face_svg(device, f) for f in faces}
    bays = list(device.module_bays.select_related('installed_module__hardware_model__manufacturer')
                .order_by('sort_order', 'id'))
    diff = S.template_diff(device) if device.template_outdated else None
    placement = device.rack_placement
    ctx = {
        'org': org, 'device': device, 'asset': device.asset, 'hm': device.hardware_model, 'layout': layout,
        'faces': faces, 'art': art, 'bays': bays, 'placement': placement,
        'face_accuracy': {f: layout.face_accuracy(f) for f in faces},
        'diff': diff,
        'logical': device.logical_interfaces.select_related('vlan').all(),
        'radios': device.radios.prefetch_related('ssids').all(),
        'lags': device.lags.annotate(n=Count('members')),
        'changes': HardwareChange.objects.filter(device=device).select_related('user')[:40],
        'can_edit': can(request, 'assets_edit', org), 'can_create': can(request, 'assets_create', org),
        'can_admin_catalog': can_manage_catalog(request.user),
        'cable_types': C.CABLE_TYPES, 'modes': DevicePort.MODE_CHOICES, 'speeds': DevicePort.SPEED_CHOICES,
        'admin_states': DevicePort.ADMIN_CHOICES, 'poe_settings': DevicePort.POE_SETTING_CHOICES,
        'page_data': {
            'device': device_summary(device),
            'ports': device_ports_json(device),
            'vlans': _org_vlans(org),
            'lags': [{'id': l.pk, 'name': l.name} for l in device.lags.all()],
            'panels': [{'id': d.pk, 'name': d.asset.name, 'model': str(d.hardware_model)} for d in
                       HardwareDevice.objects.filter(organization=org, hardware_model__category__in=(
                           'patch_panel', 'fiber_panel', 'wall_jack')).exclude(pk=device.pk)
                       .select_related('asset', 'hardware_model__manufacturer').order_by('asset__name')],
            'can_edit': can(request, 'assets_edit', org),
            'urls': {
                'port': reverse('hardware:api_port', args=[0]),
                'bulk': reverse('hardware:api_ports_bulk'),
                'ports': reverse('hardware:api_device_ports', args=[device.pk]),
                'trace': reverse('hardware:api_trace', args=[0]),
                'connect': reverse('hardware:api_connect'),
                'disconnect': reverse('hardware:api_disconnect', args=[0]),
                'search': reverse('hardware:api_port_search'),
                'patch': reverse('hardware:api_patch_assign'),
                'labels': reverse('hardware:labels'),
                'trace_page': reverse('hardware:trace_page', args=[0]),
            },
        },
    }
    return render(request, 'hardware/device_detail.html', ctx)


@org_view()
def device_art(request, pk, face, org):
    device = org_get(HardwareDevice, org, pk=pk)
    svg = device_face_svg(device, face)
    if not svg:
        raise Http404
    return HttpResponse(svg, content_type='image/svg+xml')


@org_view('assets_edit')
def device_edit(request, pk, org):
    device = get_object_or_404(HardwareDevice.objects.select_related('asset'), organization=org, pk=pk)
    a = device.asset
    sites = _site_choices(org)
    racks = Rack.objects.filter(organization=org).order_by('name')
    errors = []
    if request.method == 'POST':
        P = request.POST
        before = {'name': a.name, 'hostname': a.hostname, 'serial': a.serial_number, 'asset_tag': a.asset_tag,
                  'ip': a.ip_address, 'status': device.status, 'platform': device.platform}
        a.name = P.get('name', a.name).strip()[:255] or a.name
        a.hostname = P.get('hostname', '').strip()[:255]
        a.serial_number = P.get('serial_number', '').strip()[:255]
        a.asset_tag = P.get('asset_tag', '').strip()[:100]
        a.ip_address = P.get('ip_address', '').strip() or None
        a.firmware_version = P.get('firmware_version', '').strip()[:100]
        a.notes = P.get('notes', '')
        device.status = P.get('status') or device.status
        device.platform = P.get('platform', '').strip()[:100]
        device.room = P.get('room', '').strip()[:100]
        device.location_detail = P.get('location_detail', '').strip()[:200]
        device.site = sites.filter(pk=P.get('site')).first() if P.get('site') else None
        for f in ('install_date', 'warranty_start'):
            setattr(device, f, P.get(f) or None)
        a.warranty_expiry = P.get('warranty_expiry') or None
        try:
            with transaction.atomic():
                a.full_clean(exclude=['profile_document', 'ai_document', 'primary_contact', 'equipment_model'])
                a.save()
                device.updated_by = request.user
                device.save()
                rack_id = P.get('rack')
                if rack_id and P.get('position'):
                    S.place_in_rack(device, racks.get(pk=rack_id), int(P['position']), P.get('face') or 'front',
                                    user=request.user)
                elif P.get('rack') == '' and device.rack_placement:
                    device.rack_placement.delete()
                after = {'name': a.name, 'hostname': a.hostname, 'serial': a.serial_number,
                         'asset_tag': a.asset_tag, 'ip': a.ip_address, 'status': device.status,
                         'platform': device.platform}
                S.record(request.user, 'update', device,
                         {k: [str(before[k]), str(after[k])] for k in before if before[k] != after[k]}, device=device)
        except (ValidationError, ValueError, Rack.DoesNotExist) as e:
            errors.extend(getattr(e, 'messages', [str(e)]))
        else:
            messages.success(request, 'Device saved.')
            return redirect('hardware:device_detail', pk=device.pk)
    return render(request, 'hardware/device_edit.html', {
        'org': org, 'device': device, 'asset': a, 'sites': sites, 'racks': racks, 'errors': errors,
        'statuses': HardwareDevice.STATUS_CHOICES, 'placement': device.rack_placement})


@org_view('assets_create')
@require_POST
def device_clone(request, pk, org):
    device = org_get(HardwareDevice, org, pk=pk)
    name = request.POST.get('name', '').strip() or f'{device.asset.name}-copy'
    new = S.clone_device(device, name, user=request.user, copy_port_config=request.POST.get('copy_ports') == '1')
    messages.success(request, f'Cloned as {new.asset.name}. Serial number, asset tag, management IP and cables '
                              f'were not copied.')
    return redirect('hardware:device_detail', pk=new.pk)


@org_view('assets_delete')
@require_POST
def device_delete(request, pk, org):
    device = org_get(HardwareDevice, org, pk=pk)
    cabled = device.ports.filter(cable_termination__isnull=False).count()
    if cabled and request.POST.get('confirm_cables') != '1':
        messages.error(request, f'{device} has {cabled} documented cable(s). Confirm to remove them too.')
        return redirect('hardware:device_detail', pk=pk)
    with transaction.atomic():
        for cable in Cable.objects.filter(terminations__port__device=device).distinct():
            S.disconnect(cable, user=request.user)
        name = device.asset.name
        S.record(request.user, 'delete', device, {'name': [name, None]})
        device.asset.delete()
    messages.success(request, f'{name} deleted.')
    return redirect('hardware:device_list')


@org_view('assets_edit')
def template_update(request, pk, org):
    device = org_get(HardwareDevice, org, pk=pk)
    diff = S.template_diff(device)
    if request.method == 'POST':
        try:
            S.apply_template_update(device, user=request.user)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            messages.success(request, f'Applied catalog revision {device.hardware_model.revision}. Port IDs, '
                                      f'cables and documented settings were kept.')
        return redirect('hardware:device_detail', pk=pk)
    return render(request, 'hardware/template_update.html', {'org': org, 'device': device, 'diff': diff})


@org_view('assets_edit')
@require_POST
def module_install(request, pk, org):
    device = org_get(HardwareDevice, org, pk=pk)
    bay = get_object_or_404(ModuleBay, device=device, pk=request.POST.get('bay'))
    hm = get_object_or_404(HardwareModel, pk=request.POST.get('hardware_model'), kind=HardwareModel.KIND_MODULE)
    try:
        S.install_module(device, bay, hm, user=request.user, serial_number=request.POST.get('serial_number', '')[:120])
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    else:
        messages.success(request, f'{hm} installed in {bay.name}.')
    return redirect(reverse('hardware:device_detail', args=[pk]) + '#modules')


@org_view('assets_edit')
@require_POST
def module_remove(request, pk, org):
    mod = org_get(InstalledModule, org, pk=pk)
    device_pk = mod.device_id
    try:
        S.remove_module(mod, user=request.user)
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    else:
        messages.success(request, 'Module removed.')
    return redirect(reverse('hardware:device_detail', args=[device_pk]) + '#modules')


@org_view('assets_edit')
@require_POST
def port_add(request, pk, org):
    """A custom port on this one device (e.g. an add-in NIC the catalog doesn't list)."""
    device = org_get(HardwareDevice, org, pk=pk)
    cls = request.POST.get('component_class', C.CLASS_INTERFACE)
    if cls not in dict(C.PHYSICAL_PORT_CLASSES):
        messages.error(request, 'Unknown port kind.')
        return redirect('hardware:device_detail', pk=pk)
    name = request.POST.get('name', '').strip()[:100]
    t = request.POST.get('type', '').strip()[:50]
    eff, conn = C.classify(cls, t)
    if eff != cls:
        messages.error(request, 'Wireless and virtual interfaces are not cable ports; add them as logical interfaces.')
        return redirect('hardware:device_detail', pk=pk)
    conn = request.POST.get('connector') or conn
    try:
        p = DevicePort.objects.create(organization=org, device=device, component_class=cls, name=name,
                                      label=request.POST.get('label', '')[:100], type=t, connector=conn,
                                      is_custom=True, speed_capability=C.speed_capability(cls, t),
                                      sort_order=10000 + device.ports.count(), updated_by=request.user)
    except IntegrityError:
        messages.error(request, f'{device} already has a port named {name}.')
    else:
        S.record(request.user, 'create', p, {'custom_port': [None, name]}, device=device)
        messages.success(request, f'Added {name}. Custom ports are listed under the drawing.')
    return redirect('hardware:device_detail', pk=pk)


@org_view()
def trace_page(request, pk, org):
    port = get_object_or_404(DevicePort.objects.select_related('device__asset'), organization=org, pk=pk)
    result = S.trace(port)
    return render(request, 'hardware/trace.html', {'org': org, 'port': port, 'result': result,
                                                   'trace': S.trace_json(result)})


@org_view()
def patch_panel_view(request, pk, org):
    device = get_object_or_404(HardwareDevice.objects.select_related('asset', 'hardware_model'),
                               organization=org, pk=pk)
    rows = []
    maps = (PortMapping.objects.filter(device=device)
            .select_related('front_port__cable_termination__cable', 'rear_port__cable_termination__cable')
            .order_by('front_port__sort_order', 'front_position'))
    for m in maps:
        fr = S.trace(m.front_port)
        ports = fr.ports
        front_cable = getattr(m.front_port, 'cable_termination', None)
        # "Patched from" is the other end of the front patch cable; the trace can
        # run through this panel's own rear port first, so its order is no guide.
        near = None
        if front_cable:
            other = (CableTermination.objects.filter(cable_id=front_cable.cable_id).exclude(pk=front_cable.pk)
                     .select_related('port__device__asset').first())
            near = other.port if other else None
        # "Far end" is whichever end of the path is neither that nor this panel.
        ends = [p for p in (ports[:1] + ports[-1:]) if p.device_id != device.pk and p != near] if ports else []
        rows.append({'m': m, 'front_cable': front_cable,
                     'rear_cable': getattr(m.rear_port, 'cable_termination', None), 'near': near,
                     'far': ends[0] if ends else None, 'status': fr.status, 'trace': fr})
    total = len(rows)
    used_only = request.GET.get('used') == '1'
    if used_only:
        rows = [r for r in rows if r['front_cable'] or r['rear_cable']]
    return render(request, 'hardware/patch_panel.html', {'org': org, 'device': device, 'rows': rows,
                                                         'used_only': used_only, 'total': total})


@org_view()
def cable_list(request, org):
    qs = (Cable.objects.filter(organization=org)
          .prefetch_related('terminations__port__device__asset').order_by('label', 'id'))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(label__icontains=q) | Q(description__icontains=q)
                       | Q(terminations__port__device__asset__name__icontains=q)).distinct()
    page = Paginator(qs, 100).get_page(request.GET.get('page'))
    return render(request, 'hardware/cable_list.html', {'org': org, 'page': page, 'q': q,
                                                        'can_edit': can(request, 'assets_edit', org)})


@org_view()
def cable_detail(request, pk, org):
    cable = org_get(Cable, org, pk=pk)
    if request.method == 'POST':
        if not can(request, 'assets_edit', org):
            raise Http404
        P = request.POST
        before = {f: getattr(cable, f) for f in ('label', 'cable_type', 'color', 'color_name', 'length',
                                                   'length_unit', 'label_a', 'label_b', 'status', 'description')}
        cable.label = P.get('label', '').strip()[:60]
        cable.cable_type = P.get('cable_type', '') if P.get('cable_type', '') in C.CABLE_TYPE_KEYS else ''
        cable.color = P.get('color', '')[:7]
        cable.color_name = P.get('color_name', '')[:30]
        try:
            cable.length = Decimal(P['length']) if P.get('length') else None
        except InvalidOperation:
            messages.error(request, 'Length must be a number.')
            return redirect('hardware:cable_detail', pk=pk)
        cable.length_unit = P.get('length_unit', '')[:2]
        cable.label_a = P.get('label_a', '')[:100]
        cable.label_b = P.get('label_b', '')[:100]
        cable.status = P.get('status') or cable.status
        cable.description = P.get('description', '')[:250]
        cable.notes = P.get('notes', '')
        for t in cable.terminations.select_related('port'):
            if not C.cable_fits(cable.cable_type, t.port.connector):
                messages.error(request, f'A {cable.get_cable_type_display()} cable does not fit {t.port.name}.')
                return redirect('hardware:cable_detail', pk=pk)
        try:
            cable.updated_by = request.user
            cable.save()
        except IntegrityError:
            messages.error(request, f'Cable ID {cable.label} is already used at this client.')
            return redirect('hardware:cable_detail', pk=pk)
        S.record(request.user, 'update', cable, {k: [str(v), str(getattr(cable, k))] for k, v in before.items()
                                                 if v != getattr(cable, k)})
        messages.success(request, 'Cable saved.')
        return redirect('hardware:cable_detail', pk=pk)
    ends = cable.ends()
    a_default, b_default = S.default_cable_end_labels(cable)
    return render(request, 'hardware/cable_detail.html', {
        'org': org, 'cable': cable, 'ends': ends, 'cable_types': C.CABLE_TYPES,
        'statuses': Cable.STATUS_CHOICES, 'units': Cable.LENGTH_UNITS, 'a_default': a_default,
        'b_default': b_default, 'can_edit': can(request, 'assets_edit', org),
        'trace': S.trace_json(S.trace(ends['A'][0].port)) if ends['A'] else None})


@org_view()
def search(request, org):
    q = request.GET.get('q', '').strip()
    results = {}
    if len(q) >= 2:
        results['devices'] = (HardwareDevice.objects.filter(organization=org).filter(
            Q(asset__name__icontains=q) | Q(asset__hostname__icontains=q) | Q(asset__serial_number__icontains=q)
            | Q(asset__asset_tag__icontains=q) | Q(asset__ip_address__icontains=q)
            | Q(hardware_model__model__icontains=q) | Q(hardware_model__part_number__icontains=q)
            | Q(platform__icontains=q)).select_related('asset', 'hardware_model__manufacturer')[:50])
        results['ports'] = (DevicePort.objects.filter(organization=org).filter(
            Q(description__icontains=q) | Q(tech_label__icontains=q) | Q(notes__icontains=q)
            | Q(mac_address__icontains=q)).select_related('device__asset')[:50])
        results['cables'] = (Cable.objects.filter(organization=org).filter(
            Q(label__icontains=q) | Q(label_a__icontains=q) | Q(label_b__icontains=q)
            | Q(description__icontains=q)).prefetch_related('terminations__port__device__asset')[:50])
        results['models'] = (HardwareModel.objects.filter(is_active=True).filter(
            Q(model__icontains=q) | Q(part_number__icontains=q))
            .select_related('manufacturer').order_by('manufacturer__name', 'model')[:30])
    return render(request, 'hardware/search.html', {'org': org, 'q': q, 'results': results})


@org_view()
def vlan_list(request, org):
    if request.method == 'POST':
        if not can(request, 'assets_edit', org):
            raise Http404
        P = request.POST
        try:
            if P.get('action') == 'group':
                from locations.models import Location
                site = _site_choices(org).filter(pk=P.get('site')).first() if P.get('site') else None
                VLANGroup.objects.create(organization=org, name=P['name'].strip()[:100], site=site,
                                         description=P.get('description', ''))
                messages.success(request, 'VLAN group added.')
            else:
                group = VLANGroup.objects.filter(organization=org, pk=P.get('vlan_group')).first() \
                    if P.get('vlan_group') else None
                v = VLAN(organization=org, vlan_id=int(P['vlan_id']), name=P['name'].strip()[:100],
                         color=P.get('color', '')[:7], description=P.get('description', ''), vlan_group=group)
                v.full_clean()
                v.save()
                messages.success(request, f'VLAN {v.vlan_id} added.')
        except (ValidationError, ValueError, KeyError, IntegrityError) as e:
            messages.error(request, ' '.join(getattr(e, 'messages', [str(e) or 'Check the values.'])))
        return redirect('hardware:vlan_list')
    vlans = (VLAN.objects.filter(organization=org).select_related('vlan_group')
             .annotate(n_untagged=Count('untagged_ports', distinct=True), n_tagged=Count('tagged_ports', distinct=True))
             .order_by('vlan_group__name', 'vlan_id'))
    return render(request, 'hardware/vlan_list.html', {
        'org': org, 'vlans': vlans, 'groups': VLANGroup.objects.filter(organization=org),
        'sites': _site_choices(org), 'can_edit': can(request, 'assets_edit', org),
        'colors': {v.pk: vlan_color(v) for v in vlans}})


@login_required
def qr_resolve(request, kind, uid):
    """QR destination: an opaque id, resolved only for a signed-in user with
    access to that client. Never carries credentials or configuration."""
    model = {'d': HardwareDevice, 'p': DevicePort, 'c': Cable}.get(kind)
    if model is None:
        raise Http404
    obj = model.objects.filter(public_id=uid).first()
    if obj is None:
        raise Http404
    org = current_org(request)
    if org is None or obj.organization_id != org.pk:
        from accounts.permission_utils import user_has_org_perm
        from core.tenancy import accessible_org_ids
        allowed = accessible_org_ids(request)
        if (allowed is not None and obj.organization_id not in allowed) or \
                not user_has_org_perm(request.user, obj.organization, 'assets_view'):
            raise Http404
        request.session['current_organization_id'] = obj.organization_id
        messages.info(request, f'Switched to {obj.organization}.')
    if kind == 'd':
        return redirect('hardware:device_detail', pk=obj.pk)
    if kind == 'p':
        return redirect(reverse('hardware:device_detail', args=[obj.device_id]) + f'#port-{obj.pk}')
    return redirect('hardware:cable_detail', pk=obj.pk)


@org_view('assets_create')
def model_request(request, org):
    if request.method == 'POST':
        P = request.POST
        if not P.get('manufacturer') or not P.get('model'):
            messages.error(request, 'Manufacturer and model are required.')
        else:
            ModelRequest.objects.create(
                organization=org, requested_by=request.user, manufacturer=P['manufacturer'][:200],
                model=P['model'][:200], part_number=P.get('part_number', '')[:200],
                category=P.get('category') if P.get('category') in HardwareModel.CATEGORY_KEYS else 'other',
                datasheet_url=P.get('datasheet_url', '')[:500], notes=P.get('notes', ''))
            messages.success(request, 'Request sent to the catalog administrators. Meanwhile you can use a '
                                      'Generic template and switch the model later.')
            return redirect('hardware:device_add')
    return render(request, 'hardware/model_request.html', {
        'org': org, 'categories': HardwareModel.CATEGORY_CHOICES, 'initial': request.GET})


# =============================================================================
# JSON API (session)
# =============================================================================

@org_view()
@require_GET
def api_models(request, org):
    """Typeahead: catalog models by manufacturer/model/part number."""
    q = request.GET.get('q', '').strip()
    kind = request.GET.get('kind', HardwareModel.KIND_DEVICE)
    qs = HardwareModel.objects.filter(is_active=True, kind=kind).select_related('manufacturer')
    if request.GET.get('category'):
        qs = qs.filter(category=request.GET['category'])
    for term in q.split()[:5]:
        qs = qs.filter(Q(model__icontains=term) | Q(manufacturer__name__icontains=term)
                       | Q(part_number__icontains=term) | Q(slug__icontains=term))
    if not q and not request.GET.get('category'):
        qs = qs.filter(is_generic=True, upstream_path='')
    rows = list(qs.order_by('-is_generic', 'manufacturer__name', 'model')[:40]) if not q else \
        sorted(qs[:400], key=lambda m: (not m.model.lower().startswith(q.lower().split()[-1]) and
                                        q.lower() not in m.model.lower(), m.manufacturer.name, m.model))[:40]
    layouts = dict(LayoutTemplate.objects.filter(hardware_model__in=rows, is_current=True)
                   .values_list('hardware_model_id', 'accuracy'))
    return JsonResponse({'results': [{
        'id': m.pk, 'manufacturer': m.manufacturer.name, 'model': m.model, 'part_number': m.part_number,
        'category': m.get_category_display(), 'category_inferred': m.category_source == 'inferred',
        'u_height': float(m.u_height), 'generic': m.is_generic, 'provenance': m.get_spec_provenance_display(),
        'accuracy': layouts.get(m.pk, 'generic' if m.is_generic else 'approximate'),
        'thumb': reverse('hardware:model_art', args=[m.pk, 'front']) + '?v=thumb'} for m in rows]})


@org_view()
@require_GET
def api_device_ports(request, pk, org):
    device = org_get(HardwareDevice, org, pk=pk)
    return JsonResponse({'ports': device_ports_json(device), 'vlans': _org_vlans(org)})


def _port_data_from_request(org, port, data):
    out = {}
    for f in ('description', 'tech_label', 'poe_notes', 'notes', 'mac_address'):
        if f in data:
            out[f] = str(data[f] or '').strip()[:250 if f != 'notes' else 10000]
    choice_fields = {'configured_speed': DevicePort.SPEED_CHOICES, 'admin_state': DevicePort.ADMIN_CHOICES,
                     'mode': DevicePort.MODE_CHOICES, 'poe_setting': DevicePort.POE_SETTING_CHOICES}
    for f, choices in choice_fields.items():
        if f in data:
            v = data[f] or ''
            if v not in dict(choices):
                raise ValidationError({f: 'Invalid choice.'})
            out[f] = v
    for f in ('untagged_vlan', 'voice_vlan'):
        if f in data:
            out[f] = _vlan(org, data[f])
    if 'lag' in data:
        out['lag'] = (LinkAggregationGroup.objects.filter(device=port.device, pk=data['lag']).first()
                      if data['lag'] else None)
        if data['lag'] and out['lag'] is None:
            raise ValidationError({'lag': 'LAG not found on this device.'})
    if 'is_populated' in data:
        out['is_populated'] = bool(data['is_populated'])
    if 'breakout_mode' in data:
        out['breakout_mode'] = str(data['breakout_mode'] or '')[:20]
    return out


@org_view()
def api_port(request, pk, org):
    port = get_object_or_404(port_queryset_org(org), pk=pk)
    if request.method == 'GET':
        trace = S.trace_json(S.trace(port)) if hasattr(port, 'cable_termination') or port.is_passive else None
        return JsonResponse({'port': port_json(port, {port.pk: _peers(port)}), 'trace': trace})
    if request.method != 'POST':
        return JsonResponse({'error': 'GET or POST'}, status=405)
    if not can(request, 'assets_edit', org):
        return JsonResponse({'error': 'You need the assets edit permission to change ports.'}, status=403)
    try:
        data = _body(request)
        fields = _port_data_from_request(org, port, data)
        tagged = _vlans(org, data.get('tagged_vlans')) if 'tagged_vlans' in data else None
        port, changes = S.update_port(port, fields, tagged=tagged, user=request.user,
                                      set_tagged='tagged_vlans' in data)
        cable_fields = data.get('cable')
        term = getattr(port, 'cable_termination', None)
        if cable_fields and term:
            _update_cable(term.cable, cable_fields, request.user)
    except ValidationError as e:
        return _err(e)
    port = get_object_or_404(port_queryset_org(org), pk=pk)
    return JsonResponse({'ok': True, 'changed': list(changes), 'port': port_json(port, {port.pk: _peers(port)})})


def port_queryset_org(org):
    return (DevicePort.objects.filter(organization=org)
            .select_related('untagged_vlan__vlan_group', 'voice_vlan', 'lag', 'module__bay', 'device__asset',
                            'cable_termination__cable', 'updated_by')
            .prefetch_related('tagged_memberships__vlan'))


def _peers(port):
    term = getattr(port, 'cable_termination', None) if hasattr(port, 'cable_termination') else None
    if not term:
        return []
    return [t.port for t in term.cable.terminations.select_related('port__device__asset').exclude(end=term.end)]


def _update_cable(cable, data, user):
    before = {}
    for f, n in (('label', 60), ('color', 7), ('color_name', 30), ('label_a', 100), ('label_b', 100)):
        if f in data:
            before[f] = getattr(cable, f)
            setattr(cable, f, str(data[f] or '').strip()[:n])
    if 'cable_type' in data:
        ct = data['cable_type'] or ''
        if ct and ct not in C.CABLE_TYPE_KEYS:
            raise ValidationError('Unknown cable type.')
        for t in cable.terminations.select_related('port'):
            if not C.cable_fits(ct, t.port.connector):
                raise ValidationError(f'A {dict(C.CABLE_TYPES).get(ct)} cable does not fit {t.port.name}.')
        before['cable_type'] = cable.cable_type
        cable.cable_type = ct
    if 'length' in data:
        before['length'] = cable.length
        try:
            cable.length = Decimal(str(data['length'])) if data['length'] not in (None, '') else None
        except InvalidOperation:
            raise ValidationError('Cable length must be a number.')
    if 'length_unit' in data:
        cable.length_unit = data['length_unit'] if data['length_unit'] in dict(Cable.LENGTH_UNITS) else ''
    try:
        with transaction.atomic():
            cable.updated_by = user
            cable.save()
    except IntegrityError:
        raise ValidationError(f'Cable ID {cable.label} is already used at this client.')
    S.record(user, 'update', cable, {k: [str(v), str(getattr(cable, k))] for k, v in before.items()
                                     if v != getattr(cable, k)})


@org_view('assets_edit')
@require_POST
def api_ports_bulk(request, org):
    try:
        data = _body(request)
        ports = org_filter_ids(DevicePort, org, data.get('ports', []))
        if not ports:
            raise ValidationError('Select at least one port.')
        changes = data.get('changes', {})
        fields = {}
        for p in ports[:1]:
            fields = _port_data_from_request(org, p, changes)
        add = _vlans(org, data.get('tagged_add'))
        remove = _vlans(org, data.get('tagged_remove'))
        start = int(data.get('label_start') or 1)
        S.bulk_update_ports(ports, fields, user=request.user, tagged_add=add, tagged_remove=remove,
                            label_pattern=(data.get('label_pattern') or '').strip(), label_start=start)
    except (ValidationError, ValueError) as e:
        return _err(e if isinstance(e, ValidationError) else ValidationError(str(e)))
    return JsonResponse({'ok': True, 'updated': len(ports)})


@org_view()
@require_GET
def api_port_search(request, org):
    """Endpoint picker: free ports at this client matching device/port text."""
    q = request.GET.get('q', '').strip()
    qs = (DevicePort.objects.filter(organization=org, is_populated=True, breakout_parent__isnull=True)
          .select_related('device__asset', 'cable_termination__cable'))
    if request.GET.get('device'):
        qs = qs.filter(device_id=request.GET['device'])
    if request.GET.get('free') == '1':
        qs = qs.filter(cable_termination__isnull=True)
    if request.GET.get('exclude'):
        qs = qs.exclude(pk=request.GET['exclude'])
    for term in q.split()[:4]:
        qs = qs.filter(Q(device__asset__name__icontains=term) | Q(name__icontains=term)
                       | Q(label__iexact=term) | Q(tech_label__icontains=term) | Q(description__icontains=term))
    rows = qs.order_by('device__asset__name', 'sort_order')[:60]
    return JsonResponse({'results': [{
        'id': p.pk, 'device_id': p.device_id, 'device': p.device.asset.name, 'name': p.name,
        'label': p.tech_label or p.label, 'class': p.get_component_class_display(), 'connector': p.connector,
        'description': p.description,
        'cable': (p.cable_termination.cable.label or f'#{p.cable_termination.cable_id}')
        if hasattr(p, 'cable_termination') else ''} for p in rows]})


def _cable_fields(data):
    out = {}
    for f, n in (('label', 60), ('color', 7), ('color_name', 30), ('label_a', 100), ('label_b', 100),
                 ('description', 250)):
        if data.get(f):
            out[f] = str(data[f]).strip()[:n]
    ct = data.get('cable_type') or ''
    if ct and ct not in C.CABLE_TYPE_KEYS:
        raise ValidationError('Unknown cable type.')
    out['cable_type'] = ct
    if data.get('length') not in (None, ''):
        try:
            out['length'] = Decimal(str(data['length']))
        except InvalidOperation:
            raise ValidationError('Cable length must be a number.')
        out['length_unit'] = data.get('length_unit') if data.get('length_unit') in dict(Cable.LENGTH_UNITS) else 'm'
    if data.get('status') in dict(Cable.STATUS_CHOICES):
        out['status'] = data['status']
    return out


@org_view('assets_edit')
@require_POST
def api_connect(request, org):
    try:
        data = _body(request)
        a = org_filter_ids(DevicePort, org, data.get('a', []))
        b = org_filter_ids(DevicePort, org, data.get('b', []))
        cable = S.connect(org, a, b, user=request.user, **_cable_fields(data))
    except Http404:
        return JsonResponse({'error': 'One or more ports were not found for this client.'}, status=404)
    except ValidationError as e:
        return _err(e)
    return JsonResponse({'ok': True, 'cable': {'id': cable.pk, 'label': str(cable)}})


@org_view('assets_edit')
@require_POST
def api_disconnect(request, pk, org):
    cable = org_get(Cable, org, pk=pk)
    S.disconnect(cable, user=request.user)
    return JsonResponse({'ok': True})


@org_view()
@require_GET
def api_trace(request, pk, org):
    port = org_get(DevicePort, org, pk=pk)
    return JsonResponse(S.trace_json(S.trace(port)))


@org_view('assets_edit')
@require_POST
def api_patch_assign(request, org):
    """Cable selected ports one-to-one onto a panel's front ports, in order.

    Each pair is validated like a single connect; the batch is all-or-nothing.
    """
    try:
        data = _body(request)
        ports = org_filter_ids(DevicePort, org, data.get('ports', []))
        panel = org_get(HardwareDevice, org, pk=data.get('panel'))
        fronts = list(panel.ports.filter(component_class=C.CLASS_FRONT_PORT).order_by('sort_order', 'id'))
        start = int(data.get('start') or 1)
        if start < 1 or start - 1 + len(ports) > len(fronts):
            raise ValidationError(f'{panel} has {len(fronts)} front ports; {len(ports)} from port {start} '
                                  f'do not fit.')
        targets = fronts[start - 1:start - 1 + len(ports)]
        pattern = (data.get('label_pattern') or '').strip()
        n0 = int(data.get('label_start') or 1)
        base = _cable_fields({k: v for k, v in data.items() if k not in ('label',)})
        made = []
        with transaction.atomic():
            for i, (p, f) in enumerate(zip(ports, targets)):
                fields = dict(base)
                if pattern:
                    try:
                        fields['label'] = pattern.format(n=n0 + i, port=p.name, panel_port=f.name)[:60]
                    except (KeyError, ValueError, IndexError):
                        raise ValidationError('Use {n}, {n:03}, {port} or {panel_port} in the cable ID pattern.')
                made.append(S.connect(org, [p], [f], user=request.user, **fields))
    except Http404:
        return JsonResponse({'error': 'Port or panel not found for this client.'}, status=404)
    except (ValidationError, ValueError) as e:
        return _err(e if isinstance(e, ValidationError) else ValidationError(str(e)))
    return JsonResponse({'ok': True, 'cables': len(made)})
