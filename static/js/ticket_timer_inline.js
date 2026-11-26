/* 113.9 inline ticket timer. The server is the source of truth: every
   start/stop response and every focus refresh replaces local state. */
(function () {
  'use strict';
  var root = document.querySelector('[data-ticket-timer]');
  if (!root) return;
  var form = root.querySelector('[data-timer-form]');
  var btn = root.querySelector('[data-timer-button]');
  var icon = root.querySelector('[data-timer-icon]');
  var label = root.querySelector('[data-timer-label]');
  var clock = root.querySelector('[data-timer-elapsed]');
  var status = root.querySelector('[data-timer-status]');
  var live = root.querySelector('[data-timer-live]');
  var base = 0;       // elapsed seconds at syncedAt
  var syncedAt = Date.now();
  var running = root.getAttribute('data-running') === '1';
  var tick = null;
  var busy = false;

  function csrf() {
    var i = form.querySelector('input[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }
  function fmt(s) {
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (x < 10 ? '0' : '') + x;
  }
  function paint() {
    var s = running ? base + Math.floor((Date.now() - syncedAt) / 1000) : 0;
    clock.textContent = fmt(Math.max(0, s));
  }
  function render(data, announce) {
    running = !!data.running;
    base = data.elapsed_seconds || 0;
    syncedAt = Date.now();
    root.setAttribute('data-running', running ? '1' : '0');
    form.action = root.getAttribute(running ? 'data-stop-url' : 'data-start-url');
    btn.setAttribute('aria-pressed', running ? 'true' : 'false');
    btn.className = 'btn btn-sm ' + (running ? 'btn-success' : 'btn-outline-primary');
    icon.className = 'fas me-1 ' + (running ? 'fa-stop' : 'fa-play');
    label.textContent = running ? 'Stop & log' : 'Start timer';
    status.textContent = running ? 'Timer running' : 'No timer running';
    if (announce && data.message) live.textContent = data.message;
    paint();
    if (tick) { clearInterval(tick); tick = null; }
    if (running) tick = setInterval(paint, 1000);
    // The Time & Charges card's own Start / Stop controls follow the same state.
    var cs = document.querySelector('[data-card-timer-stop]');
    var cb = document.querySelector('[data-card-timer-start]');
    if (cs) { cs.hidden = !running; if (running) cs.style.removeProperty('display'); else cs.style.setProperty('display', 'none', 'important'); }  // d-flex !important beats [hidden]
    if (cb) cb.hidden = running;
  }
  function request(url, opts) {
    opts = opts || {};
    opts.credentials = 'same-origin';
    opts.headers = Object.assign({ 'Accept': 'application/json', 'X-Requested-With': 'fetch' }, opts.headers || {});
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error(r.status === 403 ? 'You are not allowed to time this ticket.' : 'The timer could not be changed (' + r.status + ').');
      return r.json();
    });
  }
  function refresh() {
    if (busy) return;
    request(root.getAttribute('data-state-url')).then(function (d) { render(d, false); }).catch(function () {});
  }
  form.addEventListener('submit', function (e) {
    if (!window.fetch) return;           // no fetch: ordinary form POST
    e.preventDefault();
    if (busy) return;
    busy = true; btn.disabled = true;
    var body = new URLSearchParams(new FormData(form));
    request(form.action, { method: 'POST', body: body, headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded' } })
      .then(function (d) { render(d, true); })
      .catch(function (err) { live.textContent = err.message; status.textContent = err.message; })
      .then(function () { busy = false; btn.disabled = false; });
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(); });
  window.addEventListener('focus', refresh);
  refresh();   // also corrects the elapsed time for clock skew
})();
