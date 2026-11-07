/*
 * Device page: clickable artwork, overlays, port editor, multi-select bulk
 * edits, connect/disconnect, trace highlighting.
 *
 * Every drawn connector is <g class="hw-port" data-key="<template key>">, and
 * module ports sit inside <g class="hw-module" data-module="<id>">. A port
 * record matches an element by (module id, template key) — the same stable
 * key the server uses — so artwork, hit targets and records cannot drift.
 * Overlays describe *documented* configuration only; nothing here infers
 * link state from a cable.
 */
(function () {
  'use strict';
  const D = JSON.parse(document.getElementById('hw-page-data').textContent);
  // <main> is its own stacking context (z-index: 1), which would keep these
  // panels under the navbar whatever their z-index. Move them to <body>.
  ['hwPort', 'hwBulk', 'hwConnect', 'hwClone'].forEach(id => {
    const el = document.getElementById(id);
    if (el) document.body.appendChild(el);
  });
  const SVGNS = 'http://www.w3.org/2000/svg';
  const state = {ports: D.ports, vlans: D.vlans, sel: new Set(), active: null, last: null, overlay: 'vlan', traced: new Set()};
  let byId = new Map(), byKey = new Map();

  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  const url = (name, id) => D.urls[name].replace('/0/', '/' + id + '/');

  function api(u, body) {
    const opts = {credentials: 'same-origin', headers: {'X-CSRFToken': csrf(), 'Accept': 'application/json'}};
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(u, opts).then(r => r.json().catch(() => ({error: 'Unexpected server response (' + r.status + ').'}))
      .then(j => { if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status)); return j; }));
  }

  function index() {
    byId = new Map(state.ports.map(p => [p.id, p]));
    byKey = new Map();
    state.ports.forEach(p => { if (p.key) byKey.set((p.module || '') + '|' + p.key, p); });
  }

  // ------------------------------------------------------------------ artwork
  function elementsFor() {
    return $$('svg.hw-art .hw-port').map(el => {
      const mod = el.closest('.hw-module');
      const p = byKey.get((mod ? mod.dataset.module : '') + '|' + el.dataset.key);
      return {el, p};
    });
  }

  function vlanColor(v) { return v ? v.color : '#868e96'; }

  function overlayFor(p) {
    const m = state.overlay;
    if (m === 'none') return null;
    if (!p.populated) return {fill: '#495057', text: '—', title: 'Not fitted'};
    if (m === 'vlan') {
      if (!p.vlan_capable) return null;
      if (p.mode === 'trunk' || p.mode === 'hybrid') {
        return {fill: vlanColor(p.untagged_vlan), text: 'T' + (p.untagged_vlan ? p.untagged_vlan.vid : ''), stripe: true};
      }
      if (p.mode === 'routed') return {fill: '#495057', text: 'L3'};
      if (p.mode === 'none') return {fill: '#343a40', text: 'off'};
      if (p.untagged_vlan) return {fill: vlanColor(p.untagged_vlan), text: String(p.untagged_vlan.vid), voice: !!p.voice_vlan};
      return null;
    }
    if (m === 'connected') {
      if (p.cable) return {fill: '#2f9e44', text: '⇄', title: 'Documented cable'};
      return {outline: '#adb5bd'};
    }
    if (m === 'poe') {
      if (p.poe_mode === 'pse') {
        if (p.poe_setting === 'auto' || p.poe_setting === 'static') return {fill: '#f08c00', text: 'PoE'};
        if (p.poe_setting === 'disabled') return {fill: '#868e96', text: 'off'};
        return {outline: '#f08c00', text: '?', textColor: '#f08c00'};
      }
      if (p.poe_mode === 'pd' || p.poe_setting === 'pd') return {fill: '#1c7ed6', text: 'PD'};
      return null;
    }
    if (m === 'usage') {
      if (p.tech_label || p.description) return {fill: '#0ca678', text: (p.tech_label || '✎').slice(0, 4)};
      return {outline: '#adb5bd'};
    }
    return null;
  }

  function drawOverlay(el, p) {
    el.querySelectorAll('.hw-ov').forEach(n => n.remove());
    const hit = el.querySelector('.hw-hit');
    if (!hit || !p) return;
    const o = overlayFor(p);
    if (!o) return;
    const x = +hit.getAttribute('x'), y = +hit.getAttribute('y'), w = +hit.getAttribute('width'), h = +hit.getAttribute('height');
    const g = document.createElementNS(SVGNS, 'g');
    g.setAttribute('class', 'hw-ov');
    if (o.fill) {
      const r = document.createElementNS(SVGNS, 'rect');
      Object.entries({x: x + 0.3, y: y + 0.3, width: w - 0.6, height: h - 0.6, rx: 0.8, fill: o.fill, 'fill-opacity': 0.72}).forEach(([k, v]) => r.setAttribute(k, v));
      g.appendChild(r);
      if (o.stripe) {
        const s = document.createElementNS(SVGNS, 'path');
        s.setAttribute('d', `M${x + 0.3} ${y + h - 0.3} L${x + w - 0.3} ${y + 0.3}`);
        s.setAttribute('stroke', '#fff'); s.setAttribute('stroke-width', 0.5); s.setAttribute('stroke-opacity', 0.8);
        g.appendChild(s);
      }
    }
    if (o.outline) {
      const r = document.createElementNS(SVGNS, 'rect');
      Object.entries({x: x + 0.4, y: y + 0.4, width: w - 0.8, height: h - 0.8, rx: 0.8, fill: 'none', stroke: o.outline, 'stroke-width': 0.45, 'stroke-dasharray': '1 0.7'}).forEach(([k, v]) => r.setAttribute(k, v));
      g.appendChild(r);
    }
    if (o.text) {
      const t = document.createElementNS(SVGNS, 'text');
      const size = Math.max(1.6, Math.min(h * 0.42, w * 0.34, 3.4));
      Object.entries({x: x + w / 2, y: y + h / 2 + size * 0.36, 'font-size': size, 'text-anchor': 'middle', fill: o.textColor || '#fff',
        stroke: o.textColor ? 'none' : '#000', 'stroke-width': 0.25, 'paint-order': 'stroke'}).forEach(([k, v]) => t.setAttribute(k, v));
      t.textContent = o.text;
      g.appendChild(t);
    }
    if (o.voice) {
      const c = document.createElementNS(SVGNS, 'circle');
      Object.entries({cx: x + w - 1.4, cy: y + 1.4, r: 1.1, fill: vlanColor(p.voice_vlan), stroke: '#fff', 'stroke-width': 0.3}).forEach(([k, v]) => c.setAttribute(k, v));
      g.appendChild(c);
    }
    el.insertBefore(g, hit);
  }

  function renderArt() {
    elementsFor().forEach(({el, p}) => {
      el.classList.toggle('hw-unknown', !p);
      if (!p) { el.setAttribute('aria-label', 'Not on this device'); return; }
      el.dataset.portId = p.id;
      el.classList.toggle('hw-selected', state.sel.has(p.id));
      el.classList.toggle('hw-active', state.active === p.id);
      el.classList.toggle('hw-traced', state.traced.has(p.id));
      el.classList.toggle('hw-unpopulated', !p.populated);
      const t = el.querySelector('title');
      if (t) t.textContent = tooltip(p);
      el.setAttribute('role', 'button');
      el.setAttribute('tabindex', '0');
      el.setAttribute('aria-label', tooltip(p));
      drawOverlay(el, p);
    });
    renderLegend();
  }

  function tooltip(p) {
    const parts = [p.name + (p.label && p.label !== p.name ? ' (' + p.label + ')' : '')];
    if (p.description) parts.push(p.description);
    if (p.mode) parts.push(p.mode + (p.untagged_vlan ? ' ' + p.untagged_vlan.vid : '') + (p.tagged_vlans.length ? ' +' + p.tagged_vlans.map(v => v.vid).join(',') : ''));
    if (p.peers.length) parts.push('→ ' + p.peers.map(f => f.device + ' ' + (f.label || f.name)).join(', '));
    return parts.join(' · ');
  }

  function renderLegend() {
    const L = $('#hw-legend');
    const sw = (color, text, label, outline) => `<span><span class="sw" style="background:${outline ? 'transparent' : color};${outline ? 'border:1px dashed ' + color : ''}">${esc(text || '')}</span>${esc(label)}</span>`;
    let html = '';
    const m = state.overlay;
    if (m === 'vlan') {
      const used = new Map();
      state.ports.forEach(p => [p.untagged_vlan, p.voice_vlan, ...p.tagged_vlans].forEach(v => { if (v) used.set(v.id, v); }));
      html = [...used.values()].sort((a, b) => a.vid - b.vid).map(v => sw(v.color, v.vid, `VLAN ${v.vid} ${v.name}${v.group ? ' (' + v.group + ')' : ''}`)).join('');
      html += sw('#868e96', 'T', 'Trunk — native VLAN shown, diagonal mark') + sw('#495057', 'L3', 'Routed') + '<span>● corner: voice VLAN</span>';
      if (!used.size) html = '<span class="text-muted">No VLANs documented on this device yet.</span>' + html;
    } else if (m === 'connected') {
      html = sw('#2f9e44', '⇄', 'Documented cable') + sw('#adb5bd', '', 'No cable documented', true) +
        '<span class="text-muted">Documentation only — not a link-status indicator.</span>';
    } else if (m === 'poe') {
      html = sw('#f08c00', 'PoE', 'PoE enabled (documented)') + sw('#868e96', 'off', 'PoE disabled') + sw('#f08c00', '?', 'PoE-capable, setting not documented', true) + sw('#1c7ed6', 'PD', 'Powered device');
    } else if (m === 'usage') {
      html = sw('#0ca678', '✎', 'Has description or technician label') + sw('#adb5bd', '', 'Undocumented', true);
    }
    const cabled = state.ports.filter(p => p.cable).length, total = state.ports.length;
    L.innerHTML = html + `<span class="ms-auto text-muted">${cabled}/${total} ports with a documented cable</span>`;
  }

  // ------------------------------------------------------------------ table
  function vlanChips(p) {
    const chip = (v, suffix) => `<span class="hw-vchip" style="background:${v.color}">${v.vid}${suffix || ''}</span>`;
    let s = p.mode ? `<span class="small text-muted">${esc(p.mode)}</span> ` : '';
    if (p.untagged_vlan) s += chip(p.untagged_vlan, p.mode === 'trunk' ? 'n' : '');
    p.tagged_vlans.forEach(v => { s += chip(v, 't'); });
    if (p.voice_vlan) s += chip(p.voice_vlan, 'v');
    return s;
  }

  function renderTable() {
    const f = ($('#hw-port-filter').value || '').toLowerCase();
    const cls = $('#hw-class-filter').value;
    const rows = state.ports.filter(p => (!cls || p.class === cls) && (!f || [p.name, p.label, p.description, p.tech_label,
      p.untagged_vlan && p.untagged_vlan.vid, ...p.tagged_vlans.map(v => v.vid), ...p.peers.map(x => x.device + ' ' + x.name),
      p.cable && p.cable.label].join(' ').toLowerCase().includes(f)));
    $('#hw-port-table tbody').innerHTML = rows.map(p => `
      <tr data-id="${p.id}" id="port-${p.id}" class="${state.sel.has(p.id) ? 'selected' : ''}">
        <td><input type="checkbox" class="hw-row-check" ${state.sel.has(p.id) ? 'checked' : ''} aria-label="Select ${esc(p.name)}"></td>
        <td><a href="#port-${p.id}" class="hw-open fw-semibold">${esc(p.name)}</a>${p.label && p.label !== p.name ? ' <span class="text-muted small">#' + esc(p.label) + '</span>' : ''}
          ${p.module_bay ? '<span class="badge bg-light text-dark">' + esc(p.module_bay) + '</span>' : ''}${p.is_custom ? ' <span class="badge bg-info text-dark">custom</span>' : ''}
          ${!p.key && !p.is_custom ? '' : ''}${p.combo_group ? ' <span class="badge bg-warning text-dark" title="Combo: only one of this group can be used">combo</span>' : ''}
          ${!p.populated ? ' <span class="badge bg-secondary">not fitted</span>' : ''}</td>
        <td class="small">${esc(p.connector_label)}<div class="text-muted">${esc(p.speed_capability || p.type)}</div></td>
        <td class="small">${esc(p.description)}${p.tech_label ? '<div><span class="badge text-bg-light border">' + esc(p.tech_label) + '</span></div>' : ''}</td>
        <td>${p.vlan_capable ? vlanChips(p) : '<span class="text-muted small">n/a</span>'}</td>
        <td class="small">${p.poe_mode ? esc(p.poe_mode.toUpperCase()) + (p.poe_setting ? ' · ' + esc(p.poe_setting) : '') : ''}</td>
        <td class="small">${p.peers.map(x => `<a href="/hardware/devices/${x.device_id}/#port-${x.id}">${esc(x.device)} / ${esc(x.label || x.name)}</a>`).join('<br>')}</td>
        <td class="small">${p.cable ? `<a href="/hardware/cables/${p.cable.id}/">${esc(p.cable.label)}</a>${p.cable.color ? ` <span class="sw" style="display:inline-block;width:.9em;height:.9em;border-radius:2px;background:${esc(p.cable.color)}"></span>` : ''}` : ''}</td>
      </tr>`).join('') || '<tr><td colspan="8" class="text-muted">No ports match.</td></tr>';
    $('#hw-port-table').dataset.visible = rows.map(p => p.id).join(',');
  }

  // ------------------------------------------------------------------ selection
  function updateSelectionUI() {
    const n = state.sel.size;
    $('#hw-sel-count').textContent = n;
    $$('.hw-sel-n').forEach(e => { e.textContent = n; });
    $('#hw-bulk-btn').classList.toggle('d-none', n === 0);
    $('#hw-sel-clear').classList.toggle('d-none', n === 0);
    $('#hw-bulk-list').textContent = [...state.sel].map(id => (byId.get(id) || {}).name).join(', ');
    const ids = [...state.sel];
    $('#hw-print-port-labels').href = D.urls.labels + '?kind=port&ports=' + ids.join(',');
    const cables = [...new Set(ids.map(id => byId.get(id)).filter(p => p && p.cable).map(p => p.cable.id))];
    $('#hw-print-cable-labels').href = D.urls.labels + '?kind=cable&cables=' + cables.join(',');
    renderArt(); renderTable();
  }

  function toggleSel(id, rangeFrom) {
    if (rangeFrom != null) {
      const order = state.ports.map(p => p.id);
      const a = order.indexOf(rangeFrom), b = order.indexOf(id);
      if (a >= 0 && b >= 0) {
        for (let i = Math.min(a, b); i <= Math.max(a, b); i++) state.sel.add(order[i]);
        return updateSelectionUI();
      }
    }
    state.sel.has(id) ? state.sel.delete(id) : state.sel.add(id);
    updateSelectionUI();
  }

  // ------------------------------------------------------------------ editor
  const offPort = new bootstrap.Offcanvas('#hwPort');
  function fillVlanSelects() {
    const opts = '<option value="">— none —</option>' + state.vlans.map(v => `<option value="${v.id}">${v.vid} — ${esc(v.name)}${v.group ? ' (' + esc(v.group) + ')' : ''}</option>`).join('');
    $$('.hw-vlan-select').forEach(s => { s.innerHTML = (s.dataset.keep ? '<option value="__keep">(unchanged)</option>' : '') + opts; });
    $$('.hw-vlan-multi').forEach(s => { s.innerHTML = state.vlans.map(v => `<option value="${v.id}">${v.vid} — ${esc(v.name)}</option>`).join(''); });
    $('#pf-lag').innerHTML = '<option value="">— none —</option>' + D.lags.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join('');
    const pp = $('#pp-panel');
    if (pp) pp.innerHTML = (D.panels || []).map(d => `<option value="${d.id}">${esc(d.name)} (${esc(d.model)})</option>`).join('') || '<option value="">No patch panels at this client</option>';
  }

  function openPort(id) {
    const p = byId.get(id);
    if (!p) return;
    state.active = id;
    state.last = id;
    $('#hwPortTitle').textContent = p.name + (p.label && p.label !== p.name ? '  ·  ' + p.label : '');
    $('#hwPortSub').textContent = D.device.name + ' — ' + p.class_label + (p.module_bay ? ' (module in ' + p.module_bay + ')' : '');
    const fact = (k, v) => v ? `<div class="col-6"><div class="form-label">${k}</div><div>${esc(v)}</div></div>` : '';
    $('#hwPortFacts').innerHTML = fact('Physical port', p.name) + fact('Printed number', p.label) + fact('Connector', p.connector_label) +
      fact('Speed capability', p.speed_capability) + fact('Type (catalog)', p.type) + fact('Combo group', p.combo_group ? p.combo_group + ' — only one member usable' : '') +
      fact('Positions', p.positions > 1 ? p.positions : '') + fact('Breakout', p.breakout_mode);
    ['description', 'tech_label', 'admin_state', 'configured_speed', 'mode', 'poe_setting', 'poe_notes', 'notes'].forEach(f => { const e = $('#pf-' + f); if (e) e.value = p[f] || ''; });
    $('#pf-untagged_vlan').value = p.untagged_vlan ? p.untagged_vlan.id : '';
    $('#pf-voice_vlan').value = p.voice_vlan ? p.voice_vlan.id : '';
    $('#pf-lag').value = p.lag ? p.lag.id : '';
    const tagged = new Set(p.tagged_vlans.map(v => String(v.id)));
    Array.from($('#pf-tagged').options).forEach(o => { o.selected = tagged.has(o.value); });
    $('#pf-populated').checked = p.populated;
    $('#pf-oper').textContent = p.oper_state === 'unknown' ? 'Not observed' : `${p.oper_state} (${p.oper_source}${p.oper_observed_at ? ', ' + p.oper_observed_at.slice(0, 16).replace('T', ' ') : ''})`;
    $$('.hw-if').forEach(e => e.classList.toggle('d-none', !p.vlan_capable));
    $$('.hw-poe').forEach(e => e.classList.toggle('d-none', !(p.poe_mode || p.poe_setting)));
    $('#pf-poe-cap').textContent = p.poe_mode === 'pse' ? 'PoE source' + (p.poe_type ? ' · ' + p.poe_type : ' (standard not documented)') : (p.poe_mode === 'pd' ? 'Powered device' : 'None in catalog');
    syncModeUI();
    renderConnection(p);
    $('#pf-modified').textContent = p.updated_at ? 'Last modified ' + p.updated_at.slice(0, 16).replace('T', ' ') + (p.updated_by ? ' by ' + p.updated_by : '') : '';
    $('#pf-error').classList.add('d-none');
    $('#pf-trace-link').href = url('trace_page', p.id);
    history.replaceState(null, '', '#port-' + p.id);
    offPort.show();
    renderArt();
    loadTrace(p);
  }

  function syncModeUI() {
    const m = $('#pf-mode').value;
    $$('.hw-trunk').forEach(e => e.classList.toggle('d-none', !(m === 'trunk' || m === 'hybrid')));
  }

  function renderConnection(p) {
    const c = p.cable;
    $('#pf-disconnect').classList.toggle('d-none', !c);
    $('#pf-connect').classList.toggle('d-none', !!c);
    $('#pf-cable-fields').classList.toggle('d-none', !c);
    if (!c) {
      $('#pf-conn').innerHTML = p.populated ? '<span class="text-muted">No cable documented on this port.</span>' : '<span class="text-muted">Not fitted.</span>';
      return;
    }
    $('#pf-conn').innerHTML = `Cable <a href="/hardware/cables/${c.id}/">${esc(c.label)}</a> (${esc(c.type_label || 'type not set')}${c.status !== 'connected' ? ', ' + esc(c.status) : ''}) to ` +
      p.peers.map(x => `<a href="/hardware/devices/${x.device_id}/#port-${x.id}">${esc(x.device)} / ${esc(x.label || x.name)}</a>`).join(', ');
    $('#pc-label').value = c.label.startsWith('#') ? '' : c.label;
    $('#pc-type').value = c.type || '';
    $('#pc-color').value = /^#[0-9a-f]{6}$/i.test(c.color) ? c.color : '#1f77b4';
    $('#pc-color_name').value = c.color_name || '';
    $('#pc-length').value = c.length || '';
    $('#pc-length_unit').value = c.length_unit || 'm';
    $('#pc-label_a').value = c.label_a || '';
    $('#pc-label_b').value = c.label_b || '';
  }

  function loadTrace(p) {
    state.traced = new Set();
    const box = $('#pf-trace');
    if (!p.cable && !p.passive) { box.innerHTML = ''; renderArt(); return; }
    box.innerHTML = '<span class="small text-muted">Tracing…</span>';
    api(url('trace', p.id)).then(t => {
      t.steps.filter(s => s.kind === 'port' && s.device_id === D.device.id).forEach(s => state.traced.add(s.id));
      renderArt();
      box.innerHTML = traceHtml(t);
    }).catch(e => { box.innerHTML = `<span class="text-danger small">${esc(e.message)}</span>`; });
  }

  function traceHtml(t) {
    const label = {complete: ['success', 'Complete path'], incomplete: ['warning text-dark', 'Incomplete documentation'],
      loop: ['danger', 'Loop detected'], split: ['info text-dark', 'Breakout / split'], ambiguous: ['secondary', 'Ambiguous']}[t.status] || ['secondary', t.status];
    let h = `<div class="mb-1"><span class="badge bg-${label[0]}">${label[1]}</span></div><div class="hw-trace">`;
    t.steps.forEach((s, i) => {
      if (i) h += '<span class="arrow">→</span>';
      if (s.kind === 'port') h += `<div class="step port ${s['class'] === 'front_port' || s['class'] === 'rear_port' ? 'passive' : ''}"><a href="/hardware/devices/${s.device_id}/#port-${s.id}">${esc(s.device)}</a><div class="small">${esc(s.label || s.name)}${s['class'] === 'rear_port' ? ' (rear)' : s['class'] === 'front_port' ? ' (front)' : ''}${s.position ? ' pos ' + s.position : ''}</div></div>`;
      else if (s.kind === 'cable') h += `<div class="step cable"><i class="fas fa-ethernet"></i> ${esc(s.label)}<div class="small text-muted">${esc(s.type || '')} ${esc(s.length || '')}</div></div>`;
      else h += `<div class="step internal">${esc(s.note)}</div>`;
    });
    h += '</div>';
    if (t.problems.length) h += '<ul class="small text-warning-emphasis mt-1 mb-0">' + t.problems.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>';
    return h;
  }

  function collect() {
    const v = id => $('#pf-' + id).value;
    const data = {description: v('description'), tech_label: v('tech_label'), admin_state: v('admin_state'), notes: v('notes'),
      is_populated: $('#pf-populated').checked};
    const p = byId.get(state.active);
    if (p.vlan_capable) {
      Object.assign(data, {configured_speed: v('configured_speed'), mode: v('mode'), untagged_vlan: v('untagged_vlan') || null,
        voice_vlan: v('voice_vlan') || null, lag: v('lag') || null,
        tagged_vlans: (v('mode') === 'trunk' || v('mode') === 'hybrid') ? Array.from($('#pf-tagged').selectedOptions).map(o => +o.value) : []});
    }
    if (p.poe_mode || p.poe_setting) Object.assign(data, {poe_setting: v('poe_setting'), poe_notes: v('poe_notes')});
    if (p.cable) {
      data.cable = {label: $('#pc-label').value, cable_type: $('#pc-type').value, color: $('#pc-color').value,
        color_name: $('#pc-color_name').value, length: $('#pc-length').value, length_unit: $('#pc-length_unit').value,
        label_a: $('#pc-label_a').value, label_b: $('#pc-label_b').value};
    }
    return data;
  }

  function save(next) {
    const p = byId.get(state.active);
    if (!p) return;
    const btn = $('#pf-save');
    btn.disabled = true;
    api(url('port', p.id), collect()).then(j => {
      return refreshPorts().then(() => {
        flash(p.id);
        if (next) {
          const order = state.ports.map(x => x.id);
          const n = order[order.indexOf(p.id) + 1];
          if (n) openPort(n);
        } else openPort(p.id);
      });
    }).catch(e => { const box = $('#pf-error'); box.textContent = e.message; box.classList.remove('d-none'); })
      .finally(() => { btn.disabled = false; });
  }

  function flash(id) {
    const row = document.getElementById('port-' + id);
    if (row) { row.classList.remove('hw-flash'); void row.offsetWidth; row.classList.add('hw-flash'); }
  }

  function refreshPorts() {
    return api(D.urls.ports).then(j => { state.ports = j.ports; state.vlans = j.vlans; index(); renderArt(); renderTable(); updateSelectionUI(); });
  }

  // ------------------------------------------------------------------ connect
  const modal = new bootstrap.Modal('#hwConnect');
  let far = null, cxTimer = null;
  function openConnect() {
    const p = byId.get(state.active);
    far = null;
    $('#cx-from').textContent = D.device.name + ' / ' + (p.label || p.name);
    $('#cx-q').value = '';
    $('#cx-results').innerHTML = '';
    $('#cx-chosen').textContent = '';
    $('#cx-save').disabled = true;
    $('#cx-error').classList.add('d-none');
    $('#cx-type').value = p.connector === 'rj45' ? 'cat6' : (p.connector === 'lc' ? 'mmf' : '');
    modal.show();
    setTimeout(() => $('#cx-q').focus(), 300);
    cxSearch();
  }
  function cxSearch() {
    const p = byId.get(state.active);
    api(D.urls.search + '?free=1&exclude=' + p.id + '&q=' + encodeURIComponent($('#cx-q').value.trim())).then(j => {
      $('#cx-results').innerHTML = j.results.map(r => `<button type="button" class="list-group-item list-group-item-action py-1" data-id="${r.id}" data-text="${esc(r.device + ' / ' + (r.label || r.name))}">
        <strong>${esc(r.device)}</strong> / ${esc(r.name)}${r.label && r.label !== r.name ? ' <span class="text-muted">(' + esc(r.label) + ')</span>' : ''}
        <span class="small text-muted ms-2">${esc(r['class'])}${r.description ? ' · ' + esc(r.description) : ''}</span></button>`).join('') ||
        '<div class="list-group-item text-muted">No free ports match.</div>';
    }).catch(e => { $('#cx-results').innerHTML = `<div class="list-group-item text-danger">${esc(e.message)}</div>`; });
  }
  function doConnect() {
    const p = byId.get(state.active);
    const body = {a: [p.id], b: [far], label: $('#cx-label').value, cable_type: $('#cx-type').value, color: $('#cx-color').value,
      color_name: $('#cx-color_name').value, length: $('#cx-length').value, length_unit: 'm', status: $('#cx-status').value};
    $('#cx-save').disabled = true;
    api(D.urls.connect, body).then(() => { modal.hide(); return refreshPorts(); }).then(() => openPort(p.id))
      .catch(e => { const b = $('#cx-error'); b.textContent = e.message; b.classList.remove('d-none'); $('#cx-save').disabled = false; });
  }

  // ------------------------------------------------------------------ bulk
  function bulkApply() {
    const changes = {};
    const val = id => $(id).value;
    if (val('#bk-description')) changes.description = val('#bk-description');
    if (val('#bk-mode') !== '__keep') changes.mode = val('#bk-mode');
    if (val('#bk-untagged') !== '__keep') changes.untagged_vlan = val('#bk-untagged') || null;
    if (val('#bk-voice') !== '__keep') changes.voice_vlan = val('#bk-voice') || null;
    if (val('#bk-admin') !== '__keep') changes.admin_state = val('#bk-admin');
    if (val('#bk-poe') !== '__keep') changes.poe_setting = val('#bk-poe');
    const body = {ports: [...state.sel], changes, label_pattern: val('#bk-label-pattern'), label_start: val('#bk-label-start'),
      tagged_add: Array.from($('#bk-tag-add').selectedOptions).map(o => +o.value),
      tagged_remove: Array.from($('#bk-tag-remove').selectedOptions).map(o => +o.value)};
    bulkCall(D.urls.bulk, body);
  }
  function patchApply() {
    bulkCall(D.urls.patch, {ports: [...state.sel], panel: $('#pp-panel').value, start: $('#pp-start').value,
      label_pattern: $('#pp-pattern').value, label_start: $('#pp-n').value, cable_type: $('#pp-type').value,
      color_name: $('#pp-color-name').value});
  }
  function bulkCall(u, body) {
    const err = $('#bk-error');
    err.classList.add('d-none');
    api(u, body).then(() => refreshPorts()).then(() => { [...state.sel].forEach(flash); })
      .catch(e => { err.textContent = e.message; err.classList.remove('d-none'); });
  }

  // ------------------------------------------------------------------ zoom
  let zoom = 1;
  function applyZoom() {
    $$('.hw-art-wrap').forEach(w => {
      const svg = w.querySelector('svg.hw-art');
      if (!svg) return;
      if (zoom === 1) { w.classList.remove('zoomed'); svg.style.width = ''; }
      else { w.classList.add('zoomed'); svg.style.width = (zoom * 100) + '%'; }
    });
  }

  // ------------------------------------------------------------------ wiring
  index();
  fillVlanSelects();
  renderArt();
  renderTable();
  updateSelectionUI();

  document.addEventListener('click', e => {
    const el = e.target.closest('svg.hw-art .hw-port');
    if (!el || !el.dataset.portId) return;
    const id = +el.dataset.portId;
    if (e.shiftKey && state.last != null) { toggleSel(id, state.last); state.last = id; }
    else if (e.ctrlKey || e.metaKey) { toggleSel(id); state.last = id; }
    else openPort(id);
  });
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('svg.hw-art .hw-port');
    if (el && el.dataset.portId && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openPort(+el.dataset.portId); }
  });
  $('#hw-port-table').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    const id = +tr.dataset.id;
    if (e.target.classList.contains('hw-row-check')) { e.shiftKey && state.last != null ? toggleSel(id, state.last) : toggleSel(id); state.last = id; return; }
    if (e.target.closest('.hw-open')) { e.preventDefault(); openPort(id); }
  });
  $('#hw-check-all').addEventListener('change', e => {
    const ids = ($('#hw-port-table').dataset.visible || '').split(',').filter(Boolean).map(Number);
    ids.forEach(id => e.target.checked ? state.sel.add(id) : state.sel.delete(id));
    updateSelectionUI();
  });
  $('#hw-select-visible').addEventListener('click', () => {
    ($('#hw-port-table').dataset.visible || '').split(',').filter(Boolean).map(Number).forEach(id => state.sel.add(id));
    updateSelectionUI();
  });
  $('#hw-sel-clear').addEventListener('click', () => { state.sel.clear(); updateSelectionUI(); });
  $('#hw-port-filter').addEventListener('input', renderTable);
  $('#hw-class-filter').addEventListener('change', renderTable);
  $('#hw-overlay').addEventListener('change', e => { state.overlay = e.target.value; try { localStorage.setItem('hw-overlay', state.overlay); } catch (_) {} renderArt(); });
  try { const o = localStorage.getItem('hw-overlay'); if (o) { state.overlay = o; $('#hw-overlay').value = o; renderArt(); } } catch (_) {}
  $('#pf-mode').addEventListener('change', syncModeUI);
  $('#hw-port-form').addEventListener('submit', e => { e.preventDefault(); save(false); });
  const nextBtn = $('#pf-next');
  if (nextBtn) nextBtn.addEventListener('click', () => save(true));
  $('#pf-connect').addEventListener('click', openConnect);
  $('#pf-disconnect').addEventListener('click', () => {
    const p = byId.get(state.active);
    if (!p.cable || !confirm(`Remove cable ${p.cable.label} between ${p.name} and ${p.peers.map(x => x.device + ' ' + x.name).join(', ')}?`)) return;
    api(url('disconnect', p.cable.id), {}).then(refreshPorts).then(() => openPort(p.id)).catch(e => alert(e.message));
  });
  $('#cx-q').addEventListener('input', () => { clearTimeout(cxTimer); cxTimer = setTimeout(cxSearch, 200); });
  $('#cx-results').addEventListener('click', e => {
    const b = e.target.closest('[data-id]');
    if (!b) return;
    far = +b.dataset.id;
    $$('#cx-results .active').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    $('#cx-chosen').innerHTML = 'Far end: <strong>' + b.dataset.text + '</strong>';
    $('#cx-save').disabled = false;
  });
  $('#cx-save').addEventListener('click', doConnect);
  $('#bk-apply').addEventListener('click', bulkApply);
  $('#pp-apply').addEventListener('click', patchApply);
  $('#hw-zoom-in').addEventListener('click', () => { zoom = Math.min(4, zoom * 1.5); applyZoom(); });
  $('#hw-zoom-out').addEventListener('click', () => { zoom = Math.max(1, zoom / 1.5); applyZoom(); });
  $('#hw-zoom-fit').addEventListener('click', () => { zoom = 1; applyZoom(); });
  document.getElementById('hwPort').addEventListener('hidden.bs.offcanvas', () => { state.active = null; state.traced = new Set(); renderArt(); });
  const del = $('#hw-delete-btn');
  if (del) del.addEventListener('click', e => { if (!confirm('Delete this device, its ports and any cables attached to it?')) e.preventDefault(); });

  // Module typeahead (module bays tab)
  $$('.hw-module-form').forEach(form => {
    const q = form.querySelector('.hw-module-q'), dl = form.querySelector('datalist'), hid = form.querySelector('.hw-module-id');
    let map = {}, t = null;
    q.addEventListener('input', () => {
      if (map[q.value]) { hid.value = map[q.value]; return; }
      hid.value = '';
      clearTimeout(t);
      t = setTimeout(() => api('/hardware/api/models/?kind=module&q=' + encodeURIComponent(q.value)).then(j => {
        map = {};
        dl.innerHTML = j.results.map(m => { const k = m.manufacturer + ' ' + m.model; map[k] = m.id; return `<option value="${esc(k)}">`; }).join('');
      }), 200);
    });
    form.addEventListener('submit', e => { if (!hid.value) { e.preventDefault(); q.classList.add('is-invalid'); } });
  });

  const m = location.hash.match(/^#port-(\d+)$/);
  if (m && byId.has(+m[1])) openPort(+m[1]);
})();
