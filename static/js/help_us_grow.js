/*
 * "Help Us Grow" support modal — sharing and clipboard behaviour.
 *
 * The modal itself is Bootstrap's, which already gives us the focus trap,
 * Escape to close and focus restoration to the navbar heart. This file only
 * adds the two things Bootstrap does not: the native share sheet and copying
 * to the clipboard, both with a working fallback and both announced to screen
 * readers through the one live region in the modal body.
 *
 * Nothing here posts anything anywhere. `navigator.share` hands off to the OS
 * share sheet and the network buttons are plain links to each site's own
 * compose screen, so the user reviews and sends everything themselves.
 *
 * Markup contract (see templates/core/_help_us_grow_modal.html):
 *   [data-hug-copy="<text>"]   copy that text
 *   [data-hug-share]           share data-hug-title / -text / -url
 *   [data-hug-copied="..."]    what the live region says on success
 *                              (default: "Link copied!")
 */
(function () {
    'use strict';

    var modal = document.getElementById('supportProjectModal');
    if (!modal) { return; }

    var status = document.getElementById('hugStatus');
    var statusTimer = null;

    /* Announce a result. The live region is `role="status"`, so assigning
       textContent is enough for it to be read; clearing it after a few
       seconds keeps a stale "copied!" off the screen. */
    function announce(message, isError) {
        if (!status) { return; }
        status.textContent = message;
        status.classList.toggle('hug-status--error', !!isError);
        status.classList.add('hug-status--visible');
        if (statusTimer) { window.clearTimeout(statusTimer); }
        statusTimer = window.setTimeout(function () {
            status.textContent = '';
            status.classList.remove('hug-status--visible', 'hug-status--error');
        }, 4000);
    }

    /* Momentary confirmation on the button itself, for anyone who is looking
       at their pointer rather than at the top of the dialog. */
    function flash(button) {
        if (!button || button.dataset.hugFlashing === '1') { return; }
        var original = button.innerHTML;
        button.dataset.hugFlashing = '1';
        button.classList.add('hug-copied');
        button.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i> '
            + (button.dataset.hugCopied || 'Copied!');
        window.setTimeout(function () {
            button.innerHTML = original;
            button.classList.remove('hug-copied');
            delete button.dataset.hugFlashing;
        }, 2000);
    }

    /* Last resort when the Clipboard API is unavailable or refused: a
       hidden textarea plus the legacy execCommand. Returns true on success. */
    function legacyCopy(text) {
        var scratch = document.createElement('textarea');
        scratch.value = text;
        scratch.setAttribute('readonly', '');
        /* Off-screen but still selectable, and never zero-sized — iOS will
           not select a zero-sized field. */
        scratch.style.position = 'fixed';
        scratch.style.top = '-1000px';
        scratch.style.opacity = '0';
        document.body.appendChild(scratch);
        var ok = false;
        try {
            scratch.select();
            scratch.setSelectionRange(0, text.length);
            ok = document.execCommand('copy');
        } catch (err) {
            ok = false;
        }
        document.body.removeChild(scratch);
        return ok;
    }

    /* If even that fails, select the visible textarea holding the same text
       so the user can finish the job with their own keyboard. Returns the
       element it selected, or null. */
    function offerManualCopy(text) {
        var fields = modal.querySelectorAll('.hug-message');
        for (var i = 0; i < fields.length; i++) {
            if (fields[i].value.trim() === String(text).trim()) {
                fields[i].focus();
                fields[i].select();
                return fields[i];
            }
        }
        return null;
    }

    function copyText(text, button) {
        var copied = button && button.dataset.hugCopied;
        var successMessage = copied || 'Link copied!';

        function succeed() {
            announce(successMessage);
            flash(button);
        }

        function fail() {
            if (legacyCopy(text)) { succeed(); return; }
            if (offerManualCopy(text)) {
                announce('Copying was blocked by the browser. The text is '
                    + 'selected — press Ctrl+C (⌘C on a Mac) to copy it.', true);
            } else {
                announce('Copying was blocked by the browser. Select the text '
                    + 'and copy it by hand.', true);
            }
        }

        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(succeed, fail);
        } else {
            /* Plain HTTP, or an old browser: skip straight to the fallback
               rather than throwing. */
            fail();
        }
    }

    function share(button) {
        var title = button.dataset.hugTitle || document.title;
        var text = button.dataset.hugText || '';
        var url = button.dataset.hugUrl || '';

        if (!navigator.share) {
            /* No share sheet. Put the message on the clipboard instead and
               point at the per-network buttons, which are always rendered. */
            copyText(text || url, button);
            return;
        }

        var payload = { title: title, text: text };
        if (url) { payload.url = url; }

        navigator.share(payload).then(function () {
            announce('Thanks for sharing!');
        }, function (err) {
            /* A cancelled share sheet is not a failure and must not be
               reported as one. */
            if (err && (err.name === 'AbortError' || err.name === 'NotAllowedError')) {
                return;
            }
            copyText(text || url, button);
        });
    }

    modal.addEventListener('click', function (event) {
        var copier = event.target.closest('[data-hug-copy]');
        if (copier) {
            event.preventDefault();
            copyText(copier.dataset.hugCopy, copier);
            return;
        }
        var sharer = event.target.closest('[data-hug-share]');
        if (sharer) {
            event.preventDefault();
            share(sharer);
        }
    });

    /* A stale "copied!" from the last visit should not greet the next one. */
    modal.addEventListener('hidden.bs.modal', function () {
        if (statusTimer) { window.clearTimeout(statusTimer); }
        if (status) {
            status.textContent = '';
            status.classList.remove('hug-status--visible', 'hug-status--error');
        }
    });
}());
