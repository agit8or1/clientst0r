/*
 * Managed Local ONLYOFFICE settings page: refresh the operation progress
 * panel while an operation is queued or running, then reload the page once
 * it has finished so status, buttons and history are current.
 * The page only includes the panel fields when an operation is active.
 */
(function () {
    'use strict';
    var panel = document.getElementById('managed-progress');
    if (!panel) return;
    var url = panel.getAttribute('data-progress-url');
    var stateEl = panel.querySelector('[data-progress-state]');
    var msgEl = panel.querySelector('[data-progress-message]');
    var stepsEl = panel.querySelector('[data-progress-steps]');
    if (!url || !stateEl) return;
    var failures = 0;

    function render(op) {
        stateEl.textContent = op.state_label;
        if (msgEl) msgEl.textContent = op.error || op.message || '';
        if (stepsEl) {
            while (stepsEl.firstChild) stepsEl.removeChild(stepsEl.firstChild);
            (op.steps || []).forEach(function (s) {
                var li = document.createElement('li');
                li.textContent = s.message || '';
                stepsEl.appendChild(li);
            });
        }
    }

    function poll() {
        fetch(url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                failures = 0;
                var op = data.operation;
                if (!op || !op.active) {
                    window.location.reload();
                    return;
                }
                render(op);
                window.setTimeout(poll, 4000);
            })
            .catch(function () {
                failures += 1;
                if (failures < 10) window.setTimeout(poll, 8000);
                else if (msgEl) msgEl.textContent = 'Progress is no longer updating; reload the page.';
            });
    }
    window.setTimeout(poll, 3000);
}());
