/* Connectivity / VLAN diagram: pan, zoom, drag, search, filter, save positions. */
(function () {
  'use strict';
  const cfg = JSON.parse(document.getElementById('dg-data').textContent);
  const svg = document.getElementById('dg');
  const NS = 'http://www.w3.org/2000/svg';
  const W = 190, H = 54;
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  let data = null, pos = {}, view = {x: 0, y: 0, w: 1200, h: 700}, dirty = false;
  const root = document.createElementNS(NS, 'g');
  const edgeLayer = document.createElementNS(NS, 'g');
  const nodeLayer = document.createElementNS(NS, 'g');
  root.append(edgeLayer, nodeLayer);
  svg.appendChild(root);

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    if (parent) parent.appendChild(e);
    return e;
  }
  function setView() { svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`); }
  function fit() {
    const keys = visibleKeys();
    if (!keys.length) { view = {x: 0, y: 0, w: 1200, h: 700}; return setView(); }
    const xs = keys.map(k => pos[k].x), ys = keys.map(k => pos[k].y);
    const minX = Math.min(...xs) - W, maxX = Math.max(...xs) + W, minY = Math.min(...ys) - H * 2, maxY = Math.max(...ys) + H * 2;
    const r = svg.clientWidth / Math.max(1, svg.clientHeight);
    let w = maxX - minX, h = maxY - minY;
    if (w / h > r) h = w / r; else w = h * r;
    view = {x: (minX + maxX - w) / 2, y: (minY + maxY - h) / 2, w, h};
    setView();
  }
  function visibleKeys() {
    const f = $('#dg-filter').value;
    return data.nodes.filter(n => !f || n.category === f || n.kind === 'vlan').map(n => n.key);
  }

  function draw() {
    edgeLayer.innerHTML = '';
    nodeLayer.innerHTML = '';
    const vis = new Set(visibleKeys());
    const q = ($('#dg-search').value || '').toLowerCase();
    data.edges.forEach(e => {
      if (!vis.has(e.source) || !vis.has(e.target)) return;
      const a = pos[e.source], b = pos[e.target];
      const g = el('g', {class: 'edge', 'data-s': e.source, 'data-t': e.target}, edgeLayer);
      if (cfg.kind === 'vlan') {
        el('line', {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: e.color, 'stroke-width': 2.2, 'stroke-dasharray': e.mode === 'untagged' ? '' : '7 5'}, g);
        label(g, (a.x + b.x) / 2, (a.y + b.y) / 2, `${e.untagged}U/${e.tagged}T${e.voice ? '/' + e.voice + 'V' : ''}`, e.ports.join(', '));
      } else {
        el('line', {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: '#4a6fa5', 'stroke-width': Math.min(7, 1.6 + e.count * 0.6), 'stroke-linecap': 'round'}, g);
        const c = e.cables[0];
        label(g, (a.x + b.x) / 2, (a.y + b.y) / 2, e.count === 1 ? `${c.a} ⇄ ${c.b}` : `${e.count} cables`,
          e.cables.map(x => `${x.label}: ${x.a} ⇄ ${x.b}`).join('\n'));
      }
    });
    data.nodes.forEach(n => {
      if (!vis.has(n.key)) return;
      const p = pos[n.key];
      const hit = q && (n.name.toLowerCase().includes(q) || (n.model || '').toLowerCase().includes(q));
      const g = el('g', {class: 'node' + (hit ? ' hit' : '') + (q && !hit ? ' dim' : ''), transform: `translate(${p.x} ${p.y})`, 'data-key': n.key, tabindex: 0, role: 'link'}, nodeLayer);
      el('title', {}, g).textContent = n.kind === 'vlan' ? n.name : `${n.name}\n${n.model}\n${n.category_label}${n.undocumented ? '\n' + n.undocumented + ' undocumented continuation(s)' : ''}`;
      if (n.kind === 'vlan') {
        el('rect', {x: -85, y: -19, width: 170, height: 38, rx: 19, fill: n.color}, g);
        const t = el('text', {y: 5, 'text-anchor': 'middle', 'font-size': 13, 'font-weight': 700, fill: '#fff'}, g);
        t.textContent = n.name.slice(0, 26);
        return;
      }
      el('rect', {x: -W / 2, y: -H / 2, width: W, height: H, rx: 7, fill: 'var(--bs-body-bg)', stroke: n.undocumented ? '#c0392b' : 'var(--bs-secondary-color)', 'stroke-width': 1.3}, g);
      if (n.thumb) el('image', {href: n.thumb, x: -W / 2 + 6, y: -H / 2 + 5, width: W - 12, height: 16, preserveAspectRatio: 'xMidYMid meet'}, g);
      const t1 = el('text', {y: 9, 'text-anchor': 'middle', 'font-size': 13, 'font-weight': 700, fill: 'var(--bs-body-color)'}, g);
      t1.textContent = clip(n.name, 22);
      const t2 = el('text', {y: 22, 'text-anchor': 'middle', 'font-size': 9.5, fill: 'var(--bs-secondary-color)'}, g);
      t2.textContent = clip(n.category_label + ' · ' + n.model, 34);
      if (n.undocumented) {
        el('line', {x1: W / 2, y1: 0, x2: W / 2 + 36, y2: 0, stroke: '#c0392b', 'stroke-width': 1.5, 'stroke-dasharray': '4 3'}, g);
        const u = el('text', {x: W / 2 + 4, y: -6, 'font-size': 9, fill: '#c0392b'}, g);
        u.textContent = n.undocumented + ' undocumented';
      }
    });
    legend();
  }
  // Node boxes are W wide: longer text is cut with an ellipsis (the full text is in the tooltip).
  function clip(text, max) { return text.length > max ? text.slice(0, max - 1) + '…' : text; }
  function label(g, x, y, text, title) {
    const w = 7 * text.length + 10;
    el('title', {}, g).textContent = title;
    el('rect', {x: x - w / 2, y: y - 9, width: w, height: 17, rx: 3, fill: 'var(--bs-body-bg)', 'fill-opacity': 0.92, stroke: 'var(--bs-border-color)'}, g);
    const t = el('text', {x, y: y + 4, 'text-anchor': 'middle', 'font-size': 10.5, fill: 'var(--bs-body-color)'}, g);
    t.textContent = text;
  }
  function legend() {
    const L = $('#dg-legend');
    if (cfg.kind === 'vlan') {
      L.innerHTML = '<span><svg width="26" height="10"><line x1="0" y1="5" x2="26" y2="5" stroke="currentColor" stroke-width="2"/></svg> native / untagged</span>' +
        '<span><svg width="26" height="10"><line x1="0" y1="5" x2="26" y2="5" stroke="currentColor" stroke-width="2" stroke-dasharray="6 4"/></svg> tagged or voice</span>' +
        '<span><strong>U/T/V</strong> port counts per device</span>';
    } else {
      L.innerHTML = '<span><svg width="26" height="10"><line x1="0" y1="5" x2="26" y2="5" stroke="#4a6fa5" stroke-width="3"/></svg> documented cable(s); width grows with count</span>' +
        '<span><svg width="26" height="10"><line x1="0" y1="5" x2="26" y2="5" stroke="#c0392b" stroke-width="1.5" stroke-dasharray="4 3"/></svg> path continues but is undocumented</span>';
    }
    L.innerHTML += `<span class="ms-auto text-muted">${data.nodes.length} nodes · ${data.edges.length} links</span>`;
  }

  // ---------------------------------------------------------------- interaction
  function toSvg(evt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }
  let drag = null;
  svg.addEventListener('pointerdown', e => {
    const n = e.target.closest('.node');
    const p = toSvg(e);
    if (n) {
      drag = {key: n.dataset.key, dx: p.x - pos[n.dataset.key].x, dy: p.y - pos[n.dataset.key].y, el: n, moved: false};
      n.classList.add('dragging');
    } else {
      drag = {pan: true, x: e.clientX, y: e.clientY, vx: view.x, vy: view.y};
    }
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener('pointermove', e => {
    if (!drag) return;
    if (drag.pan) {
      const s = view.w / svg.clientWidth;
      view.x = drag.vx - (e.clientX - drag.x) * s;
      view.y = drag.vy - (e.clientY - drag.y) * s;
      return setView();
    }
    const p = toSvg(e);
    pos[drag.key] = {x: Math.round(p.x - drag.dx), y: Math.round(p.y - drag.dy)};
    drag.moved = true;
    dirty = true;
    status('Unsaved changes');
    draw();
  });
  svg.addEventListener('pointerup', () => { drag = null; });
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const p = toSvg(e);
    const k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    view = {x: p.x - (p.x - view.x) * k, y: p.y - (p.y - view.y) * k, w: view.w * k, h: view.h * k};
    setView();
  }, {passive: false});
  svg.addEventListener('dblclick', e => {
    const n = e.target.closest('.node');
    if (!n) return;
    const node = data.nodes.find(x => x.key === n.dataset.key);
    if (node && node.url) location.href = node.url;
  });
  svg.addEventListener('keydown', e => {
    const n = e.target.closest && e.target.closest('.node');
    if (n && e.key === 'Enter') {
      const node = data.nodes.find(x => x.key === n.dataset.key);
      if (node && node.url) location.href = node.url;
    }
  });
  function zoomBy(k) {
    const cx = view.x + view.w / 2, cy = view.y + view.h / 2;
    view = {x: cx - view.w * k / 2, y: cy - view.h * k / 2, w: view.w * k, h: view.h * k};
    setView();
  }
  function status(t) { $('#dg-status').textContent = t; }

  $('#dg-zoom-in').addEventListener('click', () => zoomBy(1 / 1.3));
  $('#dg-zoom-out').addEventListener('click', () => zoomBy(1.3));
  $('#dg-fit').addEventListener('click', fit);
  $('#dg-search').addEventListener('input', () => {
    draw();
    const q = $('#dg-search').value.toLowerCase();
    const n = q && data.nodes.find(x => x.name.toLowerCase().includes(q));
    if (n) { const p = pos[n.key]; view.x = p.x - view.w / 2; view.y = p.y - view.h / 2; setView(); }
  });
  $('#dg-filter').addEventListener('change', () => { draw(); fit(); });
  $('#dg-site').addEventListener('change', e => e.target.form.submit());
  $('#dg-save').addEventListener('click', () => {
    fetch(cfg.data_url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify({positions: pos})}).then(r => r.json()).then(j => {
      if (j.error) throw new Error(j.error);
      dirty = false; status('Layout saved (' + j.saved + ' positions)');
    }).catch(err => status('Save failed: ' + err.message));
  });
  $('#dg-export').addEventListener('submit', () => {
    $('#dg-export-pos').value = JSON.stringify(pos);
    $('#dg-export-keys').value = $('#dg-filter').value ? visibleKeys().join(',') : '';
  });
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  fetch(cfg.data_url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}}).then(r => r.json()).then(j => {
    data = j;
    pos = j.positions;
    const cats = [...new Map(j.nodes.filter(n => n.category).map(n => [n.category, n.category_label])).entries()];
    $('#dg-filter').innerHTML = '<option value="">All categories</option>' + cats.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('');
    if (!j.nodes.length) {
      el('text', {x: 40, y: 80, 'font-size': 16, fill: 'var(--bs-secondary-color)'}, nodeLayer).textContent =
        cfg.kind === 'vlan' ? 'No VLAN memberships documented yet.' : 'No devices documented yet.';
      return;
    }
    draw();
    fit();
    status(j.saved_keys.length ? `Using ${j.saved_keys.length} saved position(s)` : 'Automatic layout — arrange and save');
    const target = location.hash.slice(1);
    if (target) { $('#dg-search').value = (j.nodes.find(n => n.key === 'device:' + target) || {}).name || ''; $('#dg-search').dispatchEvent(new Event('input')); }
  }).catch(err => status('Could not load the diagram: ' + err.message));
})();
