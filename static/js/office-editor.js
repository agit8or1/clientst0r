/*
 * Office editor page: save-status indicator and unsaved-changes guard.
 * Loaded by templates/office/editor.html before the provider's own scripts.
 *
 * JS API (window.ClientstorOffice), for provider glue code:
 *
 *   ClientstorOffice.config          parsed #office-editor-config
 *       {sessionId, mode, readOnly, statusUrl, renewUrl, closeUrl,
 *        downloadUrl, baseRevision, editorOrigin, failed, csrfToken}
 *   ClientstorOffice.providerConfig  parsed #office-provider-config (whatever
 *                                    the provider's editor_page_context put in
 *                                    EditorPage.config)
 *
 *   .changesInEditor()        the user changed something; not yet stored
 *   .saving()                 the editor started sending a save
 *   .savedToServer({revision, savedAt})
 *                             clientst0r confirmed the save. Only call this
 *                             with data from clientst0r (status poll), never
 *                             because the editor said it saved. watchServer()
 *                             does this for you.
 *   .saveFailed(message)      the save did not reach clientst0r
 *   .setState(state, detail)  low level; state is one of
 *                             'clean' | 'dirty' | 'saving' | 'saved' | 'failed' | 'readonly'
 *   .setCollaborators([{id, name}])   fill the collaborators slot
 *   .onRetry(fn)              show "Retry save" in the failed state; fn runs on click
 *   .watchServer({interval})  poll statusUrl (default 4 s while dirty/saving,
 *                             30 s otherwise): a newer lastSavedRevision ->
 *                             savedToServer; a newer lastFailure -> saveFailed;
 *                             a session that is no longer open -> saveFailed
 *   .renew()                  extend the session (Promise -> expiresAt); call
 *                             before the provider renews its own token
 *   .isUnsaved()              true while dirty / saving / failed
 *
 * The same can be driven without the global by dispatching on document:
 *   document.dispatchEvent(new CustomEvent('clientstor-office:set-state',
 *       {detail: {state: 'saving'}}));
 * Every change is announced as 'clientstor-office:statechange' with
 * detail {state, previous, detail}.
 *
 * Messages shown:
 *   dirty   "Changes in editor"
 *   saving  "Saving…"
 *   saved   "Saved to clientst0r at HH:MM"
 *   failed  "Save failed — your changes are kept in the editor; retry or download"
 *
 * While unsaved, leaving the page asks first (beforeunload and the Back
 * link). On pagehide the session is told to close (sendBeacon); an edit
 * session moves to "closing" so the editor's final save is still accepted.
 */
(function () {
    'use strict';

    function readJSON(id) {
        var el = document.getElementById(id);
        if (!el) return {};
        try { return JSON.parse(el.textContent) || {}; } catch (e) { return {}; }
    }

    var config = readJSON('office-editor-config');
    var providerConfig = readJSON('office-provider-config');
    var statusEl = document.getElementById('office-save-status');
    var textEl = statusEl ? statusEl.querySelector('.office-save-text') : null;
    var retryBtn = document.getElementById('office-retry');
    var downloadBtn = document.getElementById('office-download-fallback');
    var collabEl = document.getElementById('office-collaborators');
    var state = statusEl ? statusEl.getAttribute('data-state') : 'clean';
    var lastSavedRevision = null;
    var lastFailureAt = null;
    var retryFn = null;
    var pollTimer = null;
    var pollInterval = null;
    var closed = false;

    var UNSAVED = {dirty: true, saving: true, failed: true};

    function hhmm(iso) {
        var d = iso ? new Date(iso) : new Date();
        if (isNaN(d.getTime())) d = new Date();
        return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    }

    function render(detail) {
        if (!statusEl) return;
        statusEl.setAttribute('data-state', state);
        var text;
        switch (state) {
            case 'dirty': text = 'Changes in editor'; break;
            case 'saving': text = 'Saving…'; break;
            case 'saved': text = 'Saved to clientst0r at ' + hhmm(detail && detail.savedAt); break;
            case 'failed':
                text = 'Save failed — your changes are kept in the editor; retry or download';
                if (detail && detail.message) text += ' (' + detail.message + ')';
                break;
            case 'readonly': text = 'Viewing (read-only)'; break;
            default: text = 'No unsaved changes';
        }
        if (textEl) textEl.textContent = text;
        if (retryBtn) retryBtn.classList.toggle('d-none', !(state === 'failed' && retryFn));
        if (downloadBtn) downloadBtn.classList.toggle('d-none', state !== 'failed');
    }

    function setState(next, detail) {
        if (config.readOnly && next !== 'failed') next = 'readonly';
        var previous = state;
        state = next;
        render(detail || {});
        document.dispatchEvent(new CustomEvent('clientstor-office:statechange', {
            detail: {state: state, previous: previous, detail: detail || {}}
        }));
        schedulePoll();
    }

    function poll() {
        if (!config.statusUrl || closed) return;
        fetch(config.statusUrl, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function (s) {
                if (s.lastSavedRevision && s.lastSavedRevision !== lastSavedRevision) {
                    var first = lastSavedRevision === null && state !== 'saving' && state !== 'dirty';
                    lastSavedRevision = s.lastSavedRevision;
                    if (!first) setState('saved', {revision: s.lastSavedRevision, savedAt: s.lastSavedAt});
                }
                if (s.lastFailure && s.lastFailure.at !== lastFailureAt) {
                    var initial = lastFailureAt === null && state === 'clean';
                    lastFailureAt = s.lastFailure.at;
                    if (!initial) setState('failed', {message: s.lastFailure.label});
                }
                if (s.state !== 'open' && s.state !== 'closing' && !closed) {
                    setState('failed', {message: 'the editing session ended'});
                }
            })
            .catch(function () { /* transient; next poll retries */ })
            .then(schedulePoll);
    }

    function schedulePoll() {
        if (pollInterval === null || closed) return;
        clearTimeout(pollTimer);
        var wait = UNSAVED[state] ? Math.min(pollInterval, 4000) : Math.max(pollInterval, 30000);
        pollTimer = setTimeout(poll, wait);
    }

    function post(url, extra) {
        var body = new FormData();
        body.append('csrfmiddlewaretoken', config.csrfToken || '');
        Object.keys(extra || {}).forEach(function (k) { body.append(k, extra[k]); });
        return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
                           headers: {'Accept': 'application/json'}});
    }

    var api = {
        config: config,
        providerConfig: providerConfig,
        get state() { return state; },
        setState: setState,
        changesInEditor: function () { setState('dirty'); },
        saving: function () { setState('saving'); },
        savedToServer: function (d) { setState('saved', d || {}); },
        saveFailed: function (message) { setState('failed', {message: message || ''}); },
        isUnsaved: function () { return !!UNSAVED[state]; },
        onRetry: function (fn) { retryFn = typeof fn === 'function' ? fn : null; render({}); },
        setCollaborators: function (people) {
            if (!collabEl) return;
            collabEl.textContent = '';
            (people || []).slice(0, 8).forEach(function (p) {
                var b = document.createElement('span');
                b.className = 'badge rounded-pill text-bg-light border';
                b.textContent = String(p && p.name || '').slice(0, 40);
                collabEl.appendChild(b);
            });
        },
        watchServer: function (opts) {
            pollInterval = (opts && opts.interval) || 4000;
            poll();
        },
        renew: function () {
            return post(config.renewUrl).then(function (r) { return r.json(); })
                .then(function (j) {
                    if (!j.ok) { setState('failed', {message: j.error || 'session ended'}); }
                    return j.expiresAt;
                });
        }
    };
    window.ClientstorOffice = api;

    document.addEventListener('clientstor-office:set-state', function (ev) {
        var d = ev.detail || {};
        if (d.state) setState(d.state, d);
    });

    if (retryBtn) {
        retryBtn.addEventListener('click', function () {
            if (retryFn) { setState('saving'); retryFn(); }
        });
    }

    window.addEventListener('beforeunload', function (ev) {
        if (api.isUnsaved()) {
            ev.preventDefault();
            ev.returnValue = '';
            return '';
        }
    });

    var back = document.querySelector('[data-office-back]');
    if (back) {
        back.addEventListener('click', function (ev) {
            if (api.isUnsaved() && !window.confirm(
                    'Your latest changes have not been saved to clientst0r yet. Leave anyway?')) {
                ev.preventDefault();
            }
        });
    }

    window.addEventListener('pagehide', function () {
        if (closed || !config.closeUrl || config.failed) return;
        closed = true;
        var body = new FormData();
        body.append('csrfmiddlewaretoken', config.csrfToken || '');
        body.append('beacon', '1');
        if (navigator.sendBeacon) navigator.sendBeacon(config.closeUrl, body);
    });

    render({});
})();
