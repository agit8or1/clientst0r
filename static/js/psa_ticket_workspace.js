/*
 * PSA ticket page — composer, drafts, presence, closeout panel, shortcuts.
 *
 * Markup contract (templates/psa/ticket_detail.html):
 *   #ticketWorkspaceConfig  json_script: {isStaff, presenceUrl, heartbeatSeconds}
 *   #composerForm           reply form; data-draft-url = autosave endpoint
 *   #composerIsInternal     hidden is_internal input (0/1)
 *   input[name=composer_mode]  Public reply / Internal note toggle (staff only)
 *   #composerBox / #composerLabel / #composerSubmit  styled per mode
 *   #comment_send_email     optional "email this reply" checkbox
 *   #emailConfirmModal      recipient confirmation before an emailed reply
 *   #draftStatus / #draftDiscard
 *   #presenceBanner / #presenceText   collision warning (staff only)
 *   #closeTicketModal       closeout panel; [data-closeout-status] openers
 *   #assignMeForm, #timeManualMinutes, #shortcutHelpModal
 *
 * Every write goes to a same-origin, CSRF-protected endpoint; drafts and
 * presence are keyed server-side on the signed-in user.
 */
(function () {
    'use strict';

    var config = {};
    try {
        var raw = document.getElementById('ticketWorkspaceConfig');
        if (raw) { config = JSON.parse(raw.textContent) || {}; }
    } catch (e) { config = {}; }

    function csrfToken() {
        var el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function post(url, data, opts) {
        var fd = new FormData();
        fd.append('csrfmiddlewaretoken', csrfToken());
        Object.keys(data).forEach(function (k) { fd.append(k, data[k]); });
        if (opts && opts.beacon && navigator.sendBeacon) {
            return navigator.sendBeacon(url, fd);
        }
        return fetch(url, {
            method: 'POST', body: fd, credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
            keepalive: !!(opts && opts.keepalive)
        });
    }

    function modal(id) {
        var el = document.getElementById(id);
        if (!el || !window.bootstrap) { return null; }
        return window.bootstrap.Modal.getOrCreateInstance(el);
    }

    /* ------------------------------------------------------------------
     * Composer: public / internal mode
     * ------------------------------------------------------------------ */
    var form = document.getElementById('composerForm');
    var body = document.getElementById('composerBody');
    var hiddenInternal = document.getElementById('composerIsInternal');
    var box = document.getElementById('composerBox');
    var label = document.getElementById('composerLabel');
    var submitBtn = document.getElementById('composerSubmit');
    var sendEmail = document.getElementById('comment_send_email');
    var draftStatus = document.getElementById('draftStatus');
    var draftDiscard = document.getElementById('draftDiscard');

    function isInternal() {
        return !!hiddenInternal && hiddenInternal.value === '1';
    }

    function setMode(internal) {
        if (!form) { return; }
        if (!config.isStaff) { internal = false; }
        hiddenInternal.value = internal ? '1' : '0';
        var radio = document.getElementById(internal ? 'modeInternal' : 'modePublic');
        if (radio) { radio.checked = true; }
        if (box) {
            box.classList.toggle('bg-warning', internal);
            box.classList.toggle('bg-opacity-25', internal);
            box.classList.toggle('border-warning', internal);
            box.classList.toggle('border-primary-subtle', !internal);
        }
        if (label) {
            label.classList.toggle('text-warning-emphasis', internal);
            label.classList.toggle('text-primary-emphasis', !internal);
            label.innerHTML = internal
                ? '<i class="fas fa-lock me-1"></i>INTERNAL NOTE — staff only, never sent to the client'
                : '<i class="fas fa-globe me-1"></i>PUBLIC REPLY — visible to the client';
        }
        if (submitBtn) {
            submitBtn.textContent = internal ? 'Add internal note' : 'Post reply';
            submitBtn.classList.toggle('btn-warning', internal);
            submitBtn.classList.toggle('btn-primary', !internal);
        }
        if (body) {
            body.placeholder = internal ? 'Internal note for the team…' : 'Write a reply to the client…';
        }
        // An internal note is never emailed — keep the UI honest about that.
        if (sendEmail) {
            sendEmail.disabled = internal;
            if (internal) { sendEmail.checked = false; }
        }
    }

    if (form) {
        document.querySelectorAll('input[name="composer_mode"]').forEach(function (r) {
            r.addEventListener('change', function () {
                setMode(r.value === 'internal');
                scheduleSave();
            });
        });
        setMode(isInternal());
    }

    /* Canned replies drop pre-rendered text into the composer. */
    (function () {
        var picker = document.getElementById('cannedPicker');
        var raw = document.getElementById('cannedReplies');
        if (!picker || !raw || !body) { return; }
        var byId = {};
        try {
            JSON.parse(raw.textContent).forEach(function (r) { byId[r.id] = r.rendered; });
        } catch (e) { return; }
        picker.addEventListener('change', function () {
            if (!picker.value) { return; }
            body.value = byId[picker.value] || '';
            body.focus();
            picker.value = '';
            scheduleSave();
        });
    })();

    /* ------------------------------------------------------------------
     * Drafts: debounced autosave, discard, beacon on leave
     * ------------------------------------------------------------------ */
    var draftUrl = form ? form.getAttribute('data-draft-url') : '';
    var saveTimer = null;
    var dirty = false;
    var submitting = false;
    var lastTyped = 0;

    function setDraftStatus(text, showDiscard) {
        if (draftStatus) { draftStatus.textContent = text; }
        if (draftDiscard) { draftDiscard.classList.toggle('d-none', !showDiscard); }
    }

    function saveDraft(opts) {
        if (!draftUrl || !body || submitting) { return; }
        clearTimeout(saveTimer);
        saveTimer = null;
        dirty = false;
        var payload = { action: 'save', body: body.value, is_internal: isInternal() ? '1' : '0' };
        if (opts && opts.beacon) {
            post(draftUrl, payload, { beacon: true });
            return;
        }
        post(draftUrl, payload).then(function (r) { return r.json(); }).then(function (d) {
            if (d && d.ok) {
                setDraftStatus(d.saved ? 'Draft saved' : '', !!d.saved);
            }
        }).catch(function () { setDraftStatus('Draft not saved — connection problem', false); });
    }

    function scheduleSave() {
        if (!draftUrl) { return; }
        dirty = true;
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveDraft, 1500);
    }

    if (body && draftUrl) {
        body.addEventListener('input', function () {
            lastTyped = Date.now();
            setDraftStatus('Saving…', false);
            scheduleSave();
        });
        window.addEventListener('pagehide', function () {
            if (dirty && !submitting) { saveDraft({ beacon: true }); }
        });
    }

    if (draftDiscard && draftUrl) {
        draftDiscard.addEventListener('click', function () {
            if (body && body.value.trim() && !window.confirm('Discard this draft?')) { return; }
            clearTimeout(saveTimer);
            dirty = false;
            if (body) { body.value = ''; }
            post(draftUrl, { action: 'discard' }).then(function () {
                setDraftStatus('Draft discarded', false);
            });
        });
    }

    /* ------------------------------------------------------------------
     * Emailed public reply → confirm recipients first
     * ------------------------------------------------------------------ */
    var emailConfirmed = false;
    if (form) {
        form.addEventListener('submit', function (ev) {
            if (sendEmail && sendEmail.checked && !isInternal() && !emailConfirmed) {
                var m = modal('emailConfirmModal');
                if (m) {
                    ev.preventDefault();
                    m.show();
                    return;
                }
            }
            submitting = true;
            clearTimeout(saveTimer);
        });
        var confirmBtn = document.getElementById('emailConfirmSend');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', function () {
                emailConfirmed = true;
                var m = modal('emailConfirmModal');
                if (m) { m.hide(); }
                if (form.requestSubmit) { form.requestSubmit(); } else { submitting = true; form.submit(); }
            });
        }
    }

    /* ------------------------------------------------------------------
     * Presence heartbeat + collision banner (MSP staff only)
     * ------------------------------------------------------------------ */
    var banner = document.getElementById('presenceBanner');
    var bannerText = document.getElementById('presenceText');

    function renderPresence(others) {
        if (!banner || !bannerText) { return; }
        bannerText.textContent = '';
        (others || []).forEach(function (o, i) {
            if (i) { bannerText.appendChild(document.createTextNode('; ')); }
            var strong = document.createElement('strong');
            strong.textContent = o.name;
            bannerText.appendChild(strong);
            bannerText.appendChild(document.createTextNode(
                o.mode === 'replying' ? ' is replying' : ' is viewing'));
        });
        banner.classList.toggle('d-none', !(others && others.length));
    }

    function currentMode() {
        if (!body) { return 'viewing'; }
        var typingRecently = Date.now() - lastTyped < 60000 && body.value.trim();
        return (document.activeElement === body || typingRecently) ? 'replying' : 'viewing';
    }

    if (config.isStaff && config.presenceUrl) {
        var beat = function () {
            post(config.presenceUrl, { mode: currentMode() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { if (d && d.ok) { renderPresence(d.others); } })
                .catch(function () { /* transient — next beat retries */ });
        };
        beat();
        setInterval(beat, (config.heartbeatSeconds || 20) * 1000);
        if (body) {
            body.addEventListener('focus', beat);
        }
        window.addEventListener('pagehide', function () {
            post(config.presenceUrl, { mode: 'left' }, { beacon: true });
        });
    }

    /* ------------------------------------------------------------------
     * Closeout panel: preselect the status that opened it
     * ------------------------------------------------------------------ */
    var closeModalEl = document.getElementById('closeTicketModal');
    if (closeModalEl) {
        var statusSelect = document.getElementById('closeoutStatus');
        closeModalEl.addEventListener('show.bs.modal', function (ev) {
            var opener = ev.relatedTarget;
            var sid = opener && opener.getAttribute('data-closeout-status');
            if (sid && statusSelect) { statusSelect.value = sid; }
        });
        // Re-open after a refused closeout so the user sees what to fix.
        if (closeModalEl.getAttribute('data-open-status')) {
            var m = modal('closeTicketModal');
            if (m) { m.show(); }
        }
    }

    /* ------------------------------------------------------------------
     * Keyboard shortcuts (ignored while typing)
     * ------------------------------------------------------------------ */
    function isTyping(el) {
        if (!el) { return false; }
        var tag = (el.tagName || '').toLowerCase();
        return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable;
    }

    function focusComposer(internal) {
        if (!body) { return; }
        setMode(internal);
        body.scrollIntoView({ behavior: 'smooth', block: 'center' });
        body.focus();
    }

    document.addEventListener('keydown', function (ev) {
        if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
        if (isTyping(ev.target)) { return; }
        if (document.querySelector('.modal.show')) { return; }
        var key = ev.key;
        if (key === '?') {
            var help = modal('shortcutHelpModal');
            if (help) { ev.preventDefault(); help.show(); }
            return;
        }
        switch (key) {
            case 'a': {
                var f = document.getElementById('assignMeForm');
                if (f && config.isStaff) {
                    ev.preventDefault();
                    if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); }
                }
                break;
            }
            case 'r':
                if (body) { ev.preventDefault(); focusComposer(false); }
                break;
            case 'n':
                if (body && config.isStaff) { ev.preventDefault(); focusComposer(true); }
                break;
            case 't': {
                var mins = document.getElementById('timeManualMinutes');
                if (mins) {
                    ev.preventDefault();
                    mins.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    mins.focus();
                }
                break;
            }
            case 'x': {
                var cm = modal('closeTicketModal');
                if (cm) { ev.preventDefault(); cm.show(); }
                break;
            }
            default:
                break;
        }
    });

    /* Esc leaves the composer so shortcuts work again. */
    if (body) {
        body.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') { body.blur(); }
        });
    }
})();
