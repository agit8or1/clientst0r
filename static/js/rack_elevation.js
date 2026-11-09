/*
 * Rack / cabinet elevation and board equipment artwork, shared by the rack
 * and network-closet pages. Styles: static/css/rack_elevation.css.
 *
 * Each placement from /monitoring/api/racks/<id>/devices/ carries `art`
 * (hardware/rack_art.py): the URLs of the same tenant-scoped artwork routes
 * the device and asset pages use. A device is one element spanning its whole
 * U range. Nothing here draws ports, lights or connectors of its own: with no
 * artwork the face is plain, with the saved label.
 */
(function () {
    'use strict';

    function esc(v) {
        return String(v == null ? '' : v).replace(/[&<>"']/g, c => (
            {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    }

    function span(d) {
        const end = d.end_unit || (d.start_unit + (d.units || 1) - 1);
        return d.units > 1 ? `U${d.start_unit}–U${end}` : `U${d.start_unit}`;
    }

    function mounting(d) {
        const face = (d.face || 'front') === 'rear' ? 'Rear' : 'Front';
        return `${face} mounted · ${d.is_full_depth === false ? 'half depth' : 'full depth'}`;
    }

    /* What a placement looks like from one face of the rack. */
    function faceView(d, face) {
        const own = (d.face || 'front') === face;
        if (!own && d.is_full_depth === false) return {kind: 'ghost'};
        const show = own ? 'front' : 'rear';
        const art = d.art || {};
        const url = art.faces && art.faces[show];
        if (url) {
            return {kind: 'art', url, show, rack: (art.rack_faces || []).indexOf(show) !== -1};
        }
        let note = 'No artwork recorded';
        if (art.source && art.source !== 'none') note = show === 'rear' ? 'Rear panel not drawn' : 'Front panel not drawn';
        return {kind: 'generic', show, note};
    }

    function genericFace(name, note) {
        return `<div class="rk-generic"><span class="rk-generic-name">${esc(name)}</span>` +
               `<span class="rk-generic-note">${esc(note)}</span></div>`;
    }

    function describe(d, view) {
        const model = d.art && d.art.model ? `${d.art.model}, ` : '';
        const extra = view.kind === 'ghost' ? ', mounted on the other face' : '';
        return `${d.name}, ${model}${span(d)}, ${mounting(d)}${extra}`;
    }

    /*
     * render(host, {units, face, devices, editable, onSelect, onEmptyClick})
     * Returns {frame, devicesLayer, unitAt(clientY)}.
     */
    function render(host, opts) {
        const units = opts.units;
        const face = opts.face || 'front';
        host.classList.add('rk');
        host.dataset.face = face;
        host.innerHTML = '';

        const stage = document.createElement('div');
        stage.className = 'rk-stage';
        const frame = document.createElement('div');
        frame.className = 'rk-frame';
        frame.setAttribute('role', 'group');
        frame.setAttribute('aria-label', `${units}U rack, ${face} view`);

        for (let u = units; u >= 1; u--) {
            const row = document.createElement('div');
            row.className = 'rk-row';
            row.dataset.unit = u;
            row.innerHTML = `<span class="rk-num">${u}</span><div class="rk-slot" data-unit="${u}"></div>` +
                            `<span class="rk-num">${u}</span>`;
            frame.appendChild(row);
        }

        const layer = document.createElement('div');
        layer.className = 'rk-devices';
        frame.appendChild(layer);
        const labels = document.createElement('div');
        labels.className = 'rk-labels';

        const taken = new Set();
        (opts.devices || []).forEach(d => {
            const end = d.end_unit || (d.start_unit + (d.units || 1) - 1);
            if (d.start_unit < 1 || end > units) return;
            const view = faceView(d, face);
            if (view.kind !== 'ghost') for (let u = d.start_unit; u <= end; u++) taken.add(u);
            const top = `calc(var(--rk-u) * ${units - end})`;
            const height = `calc(var(--rk-u) * ${end - d.start_unit + 1})`;

            const el = document.createElement('div');
            el.className = 'rk-dev';
            el.style.top = top;
            el.style.height = height;
            el.dataset.deviceId = d.id;
            el.dataset.startUnit = d.start_unit;
            el.dataset.units = d.units;
            if (view.kind === 'art') {
                if (!view.rack) el.classList.add('rk-shelf');
                el.innerHTML = `<img class="rk-art" src="${esc(view.url)}" alt="" loading="lazy" draggable="false">`;
            } else if (view.kind === 'ghost') {
                el.classList.add('rk-ghost');
                el.innerHTML = genericFace(d.name, `mounted ${d.face}, half depth`);
            } else {
                el.innerHTML = genericFace(d.name, view.note);
            }
            el.title = describe(d, view);
            if (view.kind !== 'ghost') {
                el.tabIndex = 0;
                el.setAttribute('role', 'button');
                el.setAttribute('aria-label', describe(d, view));
                if (opts.editable) {
                    el.setAttribute('draggable', 'true');
                    el.insertAdjacentHTML('beforeend', '<div class="rk-resize" title="Drag to change height"></div>');
                }
                const select = () => opts.onSelect && opts.onSelect(d, el);
                el.addEventListener('click', e => {
                    if (e.target.classList.contains('rk-resize')) return;
                    select();
                });
                el.addEventListener('keydown', e => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); }
                });
            }
            layer.appendChild(el);

            const lab = document.createElement('div');
            lab.className = 'rk-label' + (view.kind === 'ghost' ? ' rk-ghost-label' : '');
            lab.style.top = top;
            lab.style.height = height;
            const model = d.art && d.art.model ? d.art.model : '';
            const meta = view.kind === 'ghost' ? `${span(d)} · ${d.face} mounted, half depth`
                                               : [model, span(d)].filter(Boolean).join(' · ');
            lab.innerHTML = `<span class="rk-label-name">${esc(d.name)}</span>` +
                            `<span class="rk-label-meta">${esc(meta)}</span>`;
            if (view.kind !== 'ghost') lab.addEventListener('click', () => opts.onSelect && opts.onSelect(d, el));
            labels.appendChild(lab);
        });

        if (opts.onEmptyClick) {
            frame.querySelectorAll('.rk-slot').forEach(slot => {
                const u = parseInt(slot.dataset.unit, 10);
                if (taken.has(u)) return;
                slot.classList.add('rk-empty-action');
                slot.title = `Add a device at U${u}`;
                slot.addEventListener('click', () => opts.onEmptyClick(u));
            });
        }

        stage.appendChild(frame);
        stage.appendChild(labels);
        host.appendChild(stage);
        host.insertAdjacentHTML('beforeend',
            '<div class="rk-legend" aria-hidden="true"><span><i class="rk-key-art"></i>Catalog artwork</span>' +
            '<span><i class="rk-key-generic"></i>No artwork recorded</span>' +
            '<span><i class="rk-key-ghost"></i>Half-depth device on the other face</span></div>');

        function unitAt(clientY) {
            const first = frame.querySelector('.rk-row');
            const r = first.getBoundingClientRect();
            const scale = r.height / first.offsetHeight || 1;   // the page may zoom the rack
            const idx = Math.floor((clientY - r.top) / (first.offsetHeight * scale));
            return Math.max(1, Math.min(units, units - idx));
        }
        return {frame, devicesLayer: layer, unitAt};
    }

    /* Front artwork for a free-position board tile, or null. */
    function boardArt(item) {
        const faces = item.art && item.art.faces;
        if (!faces) return null;
        return faces.front || faces.top || Object.values(faces)[0] || null;
    }

    /*
     * Fill and open the shared detail panel (templates/monitoring/_rack_device_panel.html).
     * Focus returns to `trigger` when it closes; zoom and scroll are untouched.
     */
    function showDetail(d, {onEdit, trigger} = {}) {
        const modalEl = document.getElementById('deviceDetailModal');
        if (!modalEl) return;
        const art = d.art || {};
        document.getElementById('deviceDetailModalTitle').textContent = d.name;

        const rows = [];
        const row = (label, val, mono) => {
            if (val == null || val === '') return;
            rows.push(`<tr><th scope="row" class="text-muted fw-normal" style="width:35%">${esc(label)}</th>` +
                      `<td>${mono ? `<code>${esc(val)}</code>` : esc(val)}</td></tr>`);
        };
        row('Model', art.model || '—');
        row('Position', d.board_position_x != null && d.start_unit == null ? 'On the board' : `${span(d)} (${d.units || 1}U)`);
        if (d.face) row('Mounting', mounting(d));
        row('Asset', d.asset_name);
        row('Type', d.asset_type_display || d.resource_type_display);
        row('IP address', d.ip_address, true);
        row('Hostname', d.hostname, true);
        row('Serial no.', d.serial_number, true);
        row('Power draw', d.power_draw_watts ? `${d.power_draw_watts} W` : null);
        row('Notes', d.notes);

        const front = boardArt(d);
        const picture = front
            ? `<div class="rk-detail-art"><img src="${esc(front)}" alt="${esc(art.model || d.name)} front panel"></div>`
            : `<p class="small text-muted">No artwork recorded for this model. The rack shows a plain face with the saved name.</p>`;
        const source = art.source === 'device' ? 'Drawn from the documented device.'
                     : art.source === 'model' ? 'Drawn from the catalog model; not yet documented as a device.' : '';
        document.getElementById('deviceDetailModalBody').innerHTML = picture +
            (source ? `<p class="small text-muted mb-2">${esc(source)}</p>` : '') +
            `<table class="table table-sm table-borderless mb-0"><tbody>${rows.join('')}</tbody></table>`;

        const devLink = document.getElementById('deviceDetailDeviceLink');
        if (devLink) {
            devLink.href = art.device_url || '#';
            devLink.classList.toggle('d-none', !art.device_url);
        }
        const assetLink = document.getElementById('deviceDetailAssetLink');
        if (assetLink) {
            const href = art.asset_url || (d.asset_id ? `/assets/${d.asset_id}/` : null);
            assetLink.href = href || '#';
            assetLink.classList.toggle('d-none', !href);
        }
        const editBtn = document.getElementById('deviceDetailEditLink');
        if (editBtn) {
            editBtn.classList.toggle('d-none', !onEdit);
            editBtn.onclick = onEdit ? () => {
                const open = bootstrap.Modal.getInstance(modalEl);
                if (open) open.hide();
                onEdit(d);
            } : null;
        }

        document.querySelectorAll('.rk-dev.rk-selected').forEach(x => x.classList.remove('rk-selected'));
        if (trigger) trigger.classList.add('rk-selected');
        modalEl.addEventListener('hidden.bs.modal', () => {
            if (trigger) {
                trigger.classList.remove('rk-selected');
                if (document.body.contains(trigger)) trigger.focus({preventScroll: true});
            }
        }, {once: true});
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    window.RackElevation = {esc, span, mounting, faceView, render, boardArt, showDetail};
})();
