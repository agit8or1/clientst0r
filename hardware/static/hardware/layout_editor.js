/* Layout editor: place catalog components on faces (millimetre geometry). */
(function () {
  'use strict';
  const D = JSON.parse(document.getElementById('ed-data').textContent);
  const NS = 'http://www.w3.org/2000/svg';
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  const comps = new Map(D.components.map(c => [c.key, c]));
  let faces = JSON.parse(JSON.stringify(D.faces || {}));
  if (!Object.keys(faces).length) faces.front = {width: 482.6, height: 44.45, rack: true, elements: [], decor: [{type: 'ears'}], accuracy: 'approximate'};
  let face = Object.keys(faces)[0], scale = 2.2, sel = new Set(), drag = null;
  const svg = $('#ed-canvas');
  $('#ed-src').value = D.source_url || '';
  $('#ed-notes').value = D.source_notes || '';
  const r2 = v => Math.round(v * 100) / 100;

  function cur() { return faces[face]; }
  function faceOptions() {
    $('#ed-face').innerHTML = Object.keys(faces).map(f => `<option value="${f}" ${f === face ? 'selected' : ''}>${f}</option>`).join('');
    $('#ed-fw').value = cur().width; $('#ed-fh').value = cur().height;
    $('#ed-facc').value = D.generic ? 'generic' : (cur().accuracy || D.accuracy || 'approximate');
    $('#ed-facc').disabled = D.generic;
  }
  function el(tag, a, p) { const e = document.createElementNS(NS, tag); Object.entries(a).forEach(([k, v]) => e.setAttribute(k, v)); if (p) p.appendChild(e); return e; }

  function draw() {
    const F = cur();
    svg.setAttribute('viewBox', `-4 -6 ${F.width + 8} ${F.height + 12}`);
    svg.setAttribute('width', (F.width + 8) * scale);
    svg.setAttribute('height', (F.height + 12) * scale);
    svg.innerHTML = '';
    el('rect', {x: 0, y: 0, width: F.width, height: F.height, rx: 1.2, fill: '#4a5058', stroke: '#9aa3ab', 'stroke-width': 0.3}, svg);
    if (F.rack) { el('rect', {x: 0, y: 0, width: 21.3, height: F.height, fill: '#3a3f45'}, svg); el('rect', {x: F.width - 21.3, y: 0, width: 21.3, height: F.height, fill: '#3a3f45'}, svg); }
    for (let x = 0; x <= F.width; x += 10) el('line', {x1: x, y1: 0, x2: x, y2: F.height, stroke: '#ffffff', 'stroke-opacity': x % 50 ? 0.05 : 0.12, 'stroke-width': 0.15}, svg);
    for (let y = 0; y <= F.height; y += 10) el('line', {x1: 0, y1: y, x2: F.width, y2: y, stroke: '#ffffff', 'stroke-opacity': 0.06, 'stroke-width': 0.15}, svg);
    (F.elements || []).forEach((e, i) => {
      const c = comps.get(e.key);
      const g = el('g', {class: 'ed-el' + (sel.has(i) ? ' sel' : ''), 'data-i': i}, svg);
      el('rect', {class: 'ed-box', x: e.x, y: e.y, width: e.w, height: e.h, rx: 0.6, fill: e.kind === 'bay' ? '#1b1e22' : (c && c.connector === 'sfp' ? '#9aa1a8' : '#c8ced4'), stroke: '#111', 'stroke-width': 0.25}, g);
      const t = el('text', {x: e.x + e.w / 2, y: e.y + e.h / 2 + 1, 'font-size': Math.min(3, e.h * 0.45), 'text-anchor': 'middle', fill: e.kind === 'bay' ? '#ddd' : '#111', 'font-family': 'sans-serif'}, g);
      t.textContent = e.label || (c ? c.name : '?');
      if (!c) el('title', {}, g).textContent = 'Component no longer on this model';
    });
    unplaced();
  }

  function placedKeys() { const s = new Set(); Object.values(faces).forEach(F => (F.elements || []).forEach(e => s.add(e.key))); return s; }
  function unplaced() {
    const placed = placedKeys();
    const list = D.components.filter(c => !placed.has(c.key));
    $('#ed-unplaced').innerHTML = list.length ? list.map(c => `<div class="d-flex justify-content-between border-bottom py-1"><span>${esc(c.name)} <span class="text-muted">${esc(c.class_label)}</span></span><button class="btn btn-sm btn-link p-0" data-add="${c.key}">place</button></div>`).join('')
      : '<span class="text-muted">Everything is placed.</span>';
  }
  function props() {
    const F = cur(), box = $('#ed-props');
    if (!sel.size) { box.innerHTML = '<strong>Selection</strong><div class="text-muted">Click an element; Shift-click to add to the selection.</div>'; return; }
    const items = [...sel].map(i => F.elements[i]);
    const one = items.length === 1 ? items[0] : null;
    const c = one && comps.get(one.key);
    box.innerHTML = `<strong>${one ? esc(c ? c.name : one.key) : items.length + ' elements'}</strong>` + (one ? `
      <div class="row g-1 mt-1">${['x', 'y', 'w', 'h'].map(k => `<div class="col-6"><label>${k}<input class="form-control form-control-sm" data-p="${k}" value="${one[k]}"></label></div>`).join('')}
      <div class="col-6"><label>Rotation<select class="form-select form-select-sm" data-p="rot">${[0, 90, 180, 270].map(r => `<option ${(one.rot || 0) == r ? 'selected' : ''}>${r}</option>`).join('')}</select></label></div>
      <div class="col-6"><label>Printed number<input class="form-control form-control-sm" data-p="label" value="${esc(one.label || '')}"></label></div>
      <div class="col-12"><label>Label position<select class="form-select form-select-sm" data-p="label_pos">${['above', 'below', 'inside', 'none'].map(v => `<option ${one.label_pos === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label></div>
      ${one.kind !== 'bay' ? `<div class="col-12"><label>Connector drawing<input class="form-control form-control-sm" data-p="connector" value="${esc(one.connector || '')}"></label></div>` : ''}</div>` : '') +
      `<div class="d-flex gap-1 mt-2 flex-wrap"><select class="form-select form-select-sm" id="ed-move-face" style="width:auto">${Object.keys(faces).filter(f => f !== face).map(f => `<option>${f}</option>`).join('')}</select>
       <button class="btn btn-sm btn-outline-secondary" id="ed-move">Move to face</button>
       <button class="btn btn-sm btn-outline-danger" id="ed-remove">Unplace</button></div>`;
    box.querySelectorAll('[data-p]').forEach(inp => inp.addEventListener('change', () => {
      const k = inp.dataset.p;
      one[k] = ['x', 'y', 'w', 'h', 'rot'].includes(k) ? r2(parseFloat(inp.value) || 0) : inp.value;
      draw();
    }));
    const mv = $('#ed-move');
    if (mv) mv.addEventListener('click', () => {
      const to = $('#ed-move-face').value;
      if (!to) return;
      const moving = [...sel].sort((a, b) => b - a).map(i => F.elements.splice(i, 1)[0]);
      faces[to].elements = (faces[to].elements || []).concat(moving.map(e => Object.assign(e, {x: Math.min(e.x, faces[to].width - e.w), y: Math.min(e.y, faces[to].height - e.h)})));
      sel.clear(); draw(); props();
    });
    $('#ed-remove').addEventListener('click', () => { [...sel].sort((a, b) => b - a).forEach(i => F.elements.splice(i, 1)); sel.clear(); draw(); props(); });
  }

  function svgPoint(evt) { const pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY; return pt.matrixTransform(svg.getScreenCTM().inverse()); }
  svg.addEventListener('pointerdown', e => {
    const g = e.target.closest('.ed-el');
    if (!g) { sel.clear(); draw(); props(); return; }
    const i = +g.dataset.i;
    if (e.shiftKey) { sel.has(i) ? sel.delete(i) : sel.add(i); } else if (!sel.has(i)) { sel = new Set([i]); }
    const p = svgPoint(e);
    drag = {start: p, orig: [...sel].map(j => ({j, x: cur().elements[j].x, y: cur().elements[j].y})), alt: e.altKey};
    svg.setPointerCapture(e.pointerId);
    draw(); props();
  });
  svg.addEventListener('pointermove', e => {
    if (!drag) return;
    const p = svgPoint(e), step = e.altKey ? 0.1 : 0.5;
    const dx = Math.round((p.x - drag.start.x) / step) * step, dy = Math.round((p.y - drag.start.y) / step) * step;
    drag.orig.forEach(o => { const E = cur().elements[o.j]; E.x = r2(o.x + dx); E.y = r2(o.y + dy); });
    draw();
  });
  svg.addEventListener('pointerup', () => { if (drag) { drag = null; props(); } });
  document.addEventListener('keydown', e => {
    if (!sel.size || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    const d = e.shiftKey ? 5 : 0.5;
    const mv = {ArrowLeft: [-d, 0], ArrowRight: [d, 0], ArrowUp: [0, -d], ArrowDown: [0, d]}[e.key];
    if (!mv) return;
    e.preventDefault();
    sel.forEach(i => { const E = cur().elements[i]; E.x = r2(E.x + mv[0]); E.y = r2(E.y + mv[1]); });
    draw(); props();
  });

  $('#ed-unplaced').addEventListener('click', e => {
    const k = e.target.dataset.add;
    if (!k) return;
    const c = comps.get(k), F = cur();
    F.elements = F.elements || [];
    F.elements.push({key: k, kind: c.bay ? 'bay' : 'port', connector: c.connector, x: F.rack ? 25 : 4, y: 4,
      w: c.bay ? 40 : c.w, h: c.bay ? Math.min(30, F.height - 8) : c.h, label: c.label || c.name.replace(/^.*?(\d+)$/, '$1'), label_pos: 'above', name: c.name});
    sel = new Set([F.elements.length - 1]);
    draw(); props();
  });
  $('#ar-apply').addEventListener('click', () => {
    const idx = [...sel];
    if (!idx.length) return;
    const F = cur(), first = F.elements[idx[0]];
    const cols = +$('#ar-cols').value || 1, rows = +$('#ar-rows').value || 1, px = parseFloat($('#ar-px').value), py = parseFloat($('#ar-py').value);
    const block = +$('#ar-block').value || 0, bgap = parseFloat($('#ar-bgap').value) || 0, order = $('#ar-order').value, lab = $('#ar-lab').value;
    idx.forEach((j, n) => {
      const col = order === 'col' ? Math.floor(n / rows) : n % cols, row = order === 'col' ? n % rows : Math.floor(n / cols);
      const E = F.elements[j];
      E.x = r2(first.x + col * px + (block ? Math.floor(col / block) * bgap : 0));
      E.y = r2(first.y + row * py);
      E.label_pos = lab === 'auto' ? (row === 0 ? 'above' : 'below') : lab;
    });
    draw();
  });
  $('#ed-face').addEventListener('change', e => { face = e.target.value; sel.clear(); faceOptions(); draw(); props(); });
  $('#ed-add-face').addEventListener('click', () => {
    const n = prompt('Face name (front, rear, top, bottom, left, right)');
    if (!n || faces[n] || !['front', 'rear', 'top', 'bottom', 'left', 'right'].includes(n)) return;
    faces[n] = {width: cur().width, height: cur().height, rack: cur().rack, elements: [], decor: [], accuracy: 'approximate'};
    face = n; faceOptions(); draw();
  });
  $('#ed-fw').addEventListener('change', e => { cur().width = r2(parseFloat(e.target.value) || cur().width); draw(); });
  $('#ed-fh').addEventListener('change', e => { cur().height = r2(parseFloat(e.target.value) || cur().height); draw(); });
  $('#ed-facc').addEventListener('change', e => { cur().accuracy = e.target.value; });
  $('#ed-zin').addEventListener('click', () => { scale *= 1.25; draw(); });
  $('#ed-zout').addEventListener('click', () => { scale /= 1.25; draw(); });

  function post(u, body) {
    return fetch(u, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()}, body: JSON.stringify(body)})
      .then(r => r.json().then(j => ({ok: r.ok, j})));
  }
  function showErrors(list) {
    const b = $('#ed-errors');
    if (!list || !list.length) { b.classList.add('d-none'); return; }
    b.innerHTML = '<ul class="mb-0">' + list.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>';
    b.classList.remove('d-none');
  }
  $('#ed-preview').addEventListener('click', () => post(D.preview_url, {faces}).then(({j}) => {
    showErrors(j.errors);
    $('#ed-preview-box').innerHTML = Object.entries(j.svg || {}).map(([f, s]) => `<div class="small text-uppercase text-muted">${esc(f)} preview</div><div class="hw-art-wrap mb-2">${s}</div>`).join('');
    document.querySelectorAll('#ed-preview-box svg').forEach(s => s.classList.add('hw-art'));
  }));
  $('#ed-auto').addEventListener('click', () => {
    if (!confirm('Replace the current geometry with the automatic layout? (Nothing is saved until you click Save.)')) return;
    post(D.save_url, {action: 'auto'}).then(({j}) => { faces = j.faces; face = Object.keys(faces)[0]; sel.clear(); faceOptions(); draw(); props(); });
  });
  $('#ed-save').addEventListener('click', () => {
    Object.values(faces).forEach(F => { if (D.generic) F.accuracy = 'generic'; });
    post(D.save_url, {faces, accuracy: D.generic ? 'generic' : (cur().accuracy || 'approximate'), source_url: $('#ed-src').value, source_notes: $('#ed-notes').value})
      .then(({ok, j}) => {
        if (!ok) return showErrors(j.errors || [j.error]);
        showErrors([]);
        location.href = location.pathname.replace(/layout\/$/, '');
      });
  });

  faceOptions();
  draw();
})();
