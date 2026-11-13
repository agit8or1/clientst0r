/*
 * Managed local editor settings page: the browser probe. Fetches the
 * editor's public health address from this browser without credentials
 * (mode no-cors: the answer is opaque, only "reached" vs "network error"
 * is visible), then posts the outcome to clientst0r, which audits it.
 * The page's CSP allows connect-src to the editor's origin only.
 */
(function () {
    'use strict';
    var btn = document.getElementById('managed-probe-run');
    var out = document.getElementById('managed-probe-result');
    var cfgEl = document.getElementById('managed-probe-config');
    if (!btn || !out || !cfgEl) return;
    var cfg;
    try { cfg = JSON.parse(cfgEl.textContent || '{}'); } catch (e) { return; }
    if (!cfg.url || !cfg.resultUrl) return;

    function csrf() {
        var t = document.querySelector('[name=csrfmiddlewaretoken]');
        return t ? t.value : '';
    }

    function report(outcome) {
        out.textContent = outcome === 'reached' ? 'Reached the editor from this browser.'
            : (outcome === 'timeout' ? 'No answer within 15 seconds.'
                : 'Could not reach the editor from this browser (DNS, TLS or proxy).');
        var body = new URLSearchParams();
        body.append('outcome', outcome);
        body.append('csrfmiddlewaretoken', csrf());
        fetch(cfg.resultUrl, {method: 'POST', credentials: 'same-origin', body: body})
            .catch(function () { /* the on-page result still shows */ });
        btn.disabled = false;
    }

    btn.addEventListener('click', function () {
        btn.disabled = true;
        out.textContent = 'Checking…';
        var done = false;
        var timer = window.setTimeout(function () {
            if (!done) { done = true; report('timeout'); }
        }, 15000);
        fetch(cfg.url, {mode: 'no-cors', credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer'})
            .then(function () { if (!done) { done = true; window.clearTimeout(timer); report('reached'); } })
            .catch(function () { if (!done) { done = true; window.clearTimeout(timer); report('failed'); } });
    });
}());
