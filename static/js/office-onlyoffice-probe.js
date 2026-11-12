/*
 * Browser reachability probe for an ONLYOFFICE instance (superusers).
 * Loads <browser_url>/web-apps/apps/api/documents/api.js in this browser,
 * checks that DocsAPI.DocEditor exists and posts the outcome back; the
 * instance diagnostics show the last result.
 */
(function () {
    'use strict';
    var el = document.getElementById('oo-probe-config');
    var statusEl = document.getElementById('oo-probe-status');
    if (!el || !statusEl) return;
    var cfg;
    try { cfg = JSON.parse(el.textContent); } catch (e) { return; }
    var done = false;

    function report(outcome, version, text, cls) {
        if (done) return;
        done = true;
        statusEl.className = 'alert ' + cls;
        statusEl.textContent = text;
        var body = new FormData();
        body.append('outcome', outcome);
        body.append('version', version || '');
        body.append('csrfmiddlewaretoken', cfg.csrfToken || '');
        fetch(cfg.resultUrl, {method: 'POST', body: body, credentials: 'same-origin',
                              headers: {'Accept': 'application/json'}})
            .then(function (r) {
                if (!r.ok) statusEl.textContent += ' (the result could not be recorded)';
                else statusEl.textContent += ' Recorded for the diagnostics page.';
            });
    }

    var timer = setTimeout(function () {
        report('timeout', '', 'Timed out loading the editor script from ' + cfg.apiUrl + '.',
               'alert-danger');
    }, 20000);

    var s = document.createElement('script');
    s.src = cfg.apiUrl;
    s.addEventListener('load', function () {
        clearTimeout(timer);
        if (window.DocsAPI && window.DocsAPI.DocEditor) {
            var v = '';
            try { v = String(window.DocsAPI.DocEditor.version ? window.DocsAPI.DocEditor.version() : ''); } catch (e) { v = ''; }
            report('loaded', v, 'Your browser loaded the ONLYOFFICE editor script' +
                   (v ? ' (version ' + v + ')' : '') + '.', 'alert-success');
        } else {
            report('no_api', '', 'The script loaded but is not the ONLYOFFICE Docs API.', 'alert-danger');
        }
    });
    s.addEventListener('error', function () {
        clearTimeout(timer);
        report('error', '', 'Your browser could not load ' + cfg.apiUrl +
               ' (network, certificate or content-security policy).', 'alert-danger');
    });
    document.head.appendChild(s);
})();
