/* Catalog typeahead for "Add device". */
(function () {
  'use strict';
  const cfg = window.HW_ADD;
  const q = document.getElementById('hw-model-q');
  const results = document.getElementById('hw-model-results');
  const idInput = document.getElementById('hw-model-id');
  const chosen = document.getElementById('hw-model-chosen');
  const box = document.getElementById('hw-model-search-box');
  let timer = null, seq = 0, active = -1, rows = [];

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const accBadge = a => a === 'verified' ? '<span class="badge bg-success">Verified layout</span>'
    : a === 'generic' ? '<span class="badge bg-secondary">Generic layout</span>'
    : '<span class="badge bg-warning text-dark">Approximate layout</span>';

  function search() {
    const my = ++seq;
    fetch(cfg.api + '?q=' + encodeURIComponent(q.value.trim()), {credentials: 'same-origin'})
      .then(r => r.json()).then(data => {
        if (my !== seq) return;
        rows = data.results || [];
        active = -1;
        if (!rows.length) {
          results.innerHTML = '<div class="list-group-item text-muted">No catalog model matches. Try fewer words, the part number, or a Generic template.</div>';
          return;
        }
        results.innerHTML = rows.map((m, i) =>
          `<button type="button" class="list-group-item list-group-item-action hw-model-result d-flex gap-3 align-items-center" data-i="${i}" role="option">
             <img loading="lazy" src="${esc(m.thumb)}" alt="">
             <div class="flex-grow-1"><div><strong>${esc(m.manufacturer)}</strong> ${esc(m.model)}
               ${m.generic ? '<span class="badge bg-secondary">generic</span>' : ''}</div>
               <div class="small text-muted">${esc(m.category)}${m.category_inferred ? ' (inferred)' : ''}
                 ${m.part_number ? ' · ' + esc(m.part_number) : ''} · ${m.u_height ? m.u_height + 'U' : 'non-rack'}
                 · ${esc(m.provenance)}</div></div>
             <div>${accBadge(m.accuracy)}</div></button>`).join('');
      }).catch(() => { results.innerHTML = '<div class="list-group-item text-danger">Search failed. Check your connection.</div>'; });
  }
  function choose(m) {
    idInput.value = m.id;
    document.getElementById('hw-model-name').textContent = m.manufacturer + ' ' + m.model;
    document.getElementById('hw-model-meta').innerHTML = esc(m.category) + ' · ' + (m.u_height ? m.u_height + 'U' : 'non-rack') + ' · ' + accBadge(m.accuracy);
    document.getElementById('hw-model-thumb').src = m.thumb;
    chosen.classList.remove('d-none');
    box.classList.add('d-none');
    const name = document.querySelector('input[name=name]');
    if (name && !name.value) name.focus();
  }
  if (q) {
    q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 200); });
    q.addEventListener('keydown', e => {
      const items = results.querySelectorAll('.hw-model-result');
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = Math.max(0, Math.min(items.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)));
        items.forEach((el, i) => el.classList.toggle('active', i === active));
      } else if (e.key === 'Enter' && active >= 0) {
        e.preventDefault();
        choose(rows[active]);
      }
    });
    results.addEventListener('click', e => {
      const b = e.target.closest('.hw-model-result');
      if (b) choose(rows[+b.dataset.i]);
    });
    if (!idInput.value) { search(); q.focus(); }
  }
  document.getElementById('hw-model-change').addEventListener('click', () => {
    chosen.classList.add('d-none'); box.classList.remove('d-none'); q.focus(); search();
  });
  document.getElementById('hw-add-form').addEventListener('submit', e => {
    if (!idInput.value) { e.preventDefault(); q.focus(); q.classList.add('is-invalid'); }
  });
})();
