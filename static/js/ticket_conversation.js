/*
 * Ticket conversation — "Reply" buttons on messages (technician page and
 * customer portal; markup in templates/psa/_conversation.html).
 *
 * Markup contract:
 *   .js-reply-btn[data-parent-id][data-parent-name][data-parent-internal?]
 *   form[data-reply-form]          the composer; holds input[name=parent_id]
 *                                  and textarea[name=body]
 *   [data-reply-context]           "Replying to …" strip (hidden until used)
 *   [data-reply-label]             gets the parent's sender name
 *   [data-reply-private]           optional hint shown when replying to an
 *                                  internal note (staff page)
 *   [data-reply-clear]             clears the parent
 *
 * The server re-validates parent_id (same ticket, visible to the poster), and
 * only quotes a parent the reader is allowed to see.
 */
(function () {
    'use strict';

    var form = document.querySelector('form[data-reply-form]');
    if (!form) { return; }
    var parentInput = form.querySelector('input[name="parent_id"]');
    var body = form.querySelector('textarea[name="body"]');
    var ctx = form.querySelector('[data-reply-context]');
    var label = form.querySelector('[data-reply-label]');
    var priv = form.querySelector('[data-reply-private]');
    var clear = form.querySelector('[data-reply-clear]');
    if (!parentInput) { return; }

    function setParent(id, name, internal) {
        parentInput.value = id || '';
        if (label) { label.textContent = name || ''; }
        if (priv) { priv.hidden = !internal; }
        if (ctx) { ctx.hidden = !id; }
    }

    document.addEventListener('click', function (ev) {
        var btn = ev.target.closest ? ev.target.closest('.js-reply-btn') : null;
        if (!btn) { return; }
        ev.preventDefault();
        setParent(btn.getAttribute('data-parent-id'),
                  btn.getAttribute('data-parent-name'),
                  btn.getAttribute('data-parent-internal') === '1');
        if (body) {
            body.scrollIntoView({ behavior: 'smooth', block: 'center' });
            body.focus();
        }
    });

    if (clear) {
        clear.addEventListener('click', function () { setParent('', '', false); });
    }
})();
