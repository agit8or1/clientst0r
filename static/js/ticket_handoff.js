/* Handoff summary panel on the staff ticket page (roadmap 52.22): reveal
 * and copy the plain-text summary. No inline script (site CSP). */
(function () {
    'use strict';
    var root = document.querySelector('[data-handoff]');
    if (!root) { return; }
    var body = root.querySelector('#handoffBody');
    var toggle = root.querySelector('[data-handoff-toggle]');
    var copy = root.querySelector('[data-handoff-copy]');
    var text = root.querySelector('[data-handoff-text]');
    var status = root.querySelector('[data-handoff-status]');
    toggle.addEventListener('click', function () {
        var show = body.hidden;
        body.hidden = !show;
        toggle.setAttribute('aria-expanded', show ? 'true' : 'false');
        toggle.textContent = show ? 'Hide' : 'Show';
    });
    function say(msg) { status.textContent = msg; }
    function fallback() {
        var range = document.createRange();
        range.selectNodeContents(text);
        var sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(range);
        try { say(document.execCommand('copy') ? 'Copied.' : 'Press Ctrl+C to copy.'); }
        catch (e) { say('Press Ctrl+C to copy.'); }
    }
    copy.addEventListener('click', function () {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text.textContent).then(function () { say('Copied.'); }, fallback);
        } else { fallback(); }
    });
})();
