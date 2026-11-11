/*
 * AI Troubleshoot session page: progressive status while models run.
 *
 * Polls the session's status endpoint (GET .../status/, JSON, same access
 * checks as the page) and updates the session badge and each model's
 * status in place. When the session is finished it reloads once so the
 * server renders the results. Backs off from 2s to 10s and gives up after
 * about ten minutes, leaving the manual refresh link. Without JavaScript the
 * page shows that link and nothing polls.
 *
 * Only text is written (textContent); nothing from the server becomes HTML.
 */
(function () {
    'use strict';
    var root = document.querySelector('[data-ai-troubleshoot-session][data-status-url]');
    if (!root || root.dataset.terminal === '1' || !window.fetch) { return; }
    var url = root.dataset.statusUrl;
    var delay = 2000;
    var started = Date.now();
    var LIMIT_MS = 10 * 60 * 1000;
    var progress = root.querySelector('[data-ts-progress]');
    var badge = root.querySelector('[data-session-status]');

    function setText(node, text) {
        if (node && node.textContent !== text) { node.textContent = text; }
    }

    function render(d) {
        setText(badge, d.status_label || d.status || '');
        var runs = d.runs || [];
        var done = 0;
        runs.forEach(function (r) {
            setText(root.querySelector('[data-run-status="' + String(r.id).replace(/[^0-9]/g, '') + '"]'),
                r.status_label || r.status || '');
            if (r.finished) { done += 1; }
        });
        if (runs.length) {
            setText(progress, done + ' of ' + runs.length + ' model' + (runs.length === 1 ? '' : 's') + ' finished.');
        }
    }

    function tick() {
        if (Date.now() - started > LIMIT_MS) {
            setText(progress, 'Still running. Use the refresh link to check again.');
            return;
        }
        fetch(url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .then(function (d) {
                render(d);
                if (d.terminal) {
                    setText(progress, 'Finished. Loading the results…');
                    window.location.reload();
                    return;
                }
                delay = Math.min(10000, Math.round(delay * 1.5));
                window.setTimeout(tick, delay);
            })
            .catch(function () {
                delay = Math.min(10000, delay * 2);
                window.setTimeout(tick, delay);
            });
    }

    window.setTimeout(tick, delay);
}());
