/*
 * ONLYOFFICE Docs glue for the Office editor page.
 *
 * Reads ClientstorOffice.providerConfig (built by
 * office/providers/onlyoffice editor_page_context):
 *   {docConfig, placeholder, statusUrl, forcesaveUrl, saveAsUrl}
 * and starts DocsAPI.DocEditor (api.js is loaded from the editor's own origin
 * just before this file; the page CSP allows only that origin).
 *
 * Status mapping (window.ClientstorOffice):
 *   onDocumentStateChange(true)   -> changesInEditor()
 *   "Save now" / editor Save      -> saving(); the server-side forcesave
 *   saved to clientst0r           -> only via watchServer() (clientst0r's
 *                                    revision list), never from an editor event
 *   onError, provider status poll -> saveFailed(message)
 *   collaborators                 -> setCollaborators() from the users Docs
 *                                    reports in its callbacks
 *   onRequestSaveAs               -> stored as a copy by clientst0r
 *   onRequestClose                -> the Back link
 *   onRequestRefreshFile / onOutdatedVersion -> reload (new key)
 */
(function () {
    'use strict';

    var office = window.ClientstorOffice;
    if (!office) return;
    var cfg = office.providerConfig || {};
    var docConfig = cfg.docConfig;
    var placeholder = cfg.placeholder || 'onlyoffice-editor';
    var editor = null;
    var lastErrorAt = null;
    var firstStatus = true;

    function showLoadError() {
        var el = document.getElementById('onlyoffice-load-error');
        if (el) el.classList.remove('d-none');
        var ph = document.getElementById(placeholder);
        if (ph) ph.classList.add('d-none');
    }

    function post(url, data) {
        var body = new FormData();
        body.append('csrfmiddlewaretoken', (office.config && office.config.csrfToken) || '');
        Object.keys(data || {}).forEach(function (k) { body.append(k, data[k]); });
        return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
                           headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json().catch(function () { return {ok: false}; }); });
    }

    function saveNow() {
        if (!cfg.forcesaveUrl) return;
        office.saving();
        post(cfg.forcesaveUrl).then(function (j) {
            if (!j.ok) {
                office.saveFailed(j.error || 'the editor refused the save');
            } else if (j.noChanges && office.state === 'saving') {
                office.setState('clean');
            }
        }).catch(function () { office.saveFailed('clientst0r is unreachable'); });
    }

    function pollProvider() {
        if (!cfg.statusUrl) return;
        fetch(cfg.statusUrl, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (s) {
                if (!s) return;
                if (s.editorError && s.editorError.at !== lastErrorAt) {
                    var initial = firstStatus;
                    lastErrorAt = s.editorError.at;
                    if (!initial) office.saveFailed(s.editorError.message);
                }
                firstStatus = false;
                office.setCollaborators(s.collaborators || []);
            })
            .catch(function () { /* next poll retries */ });
    }

    function addSaveButton() {
        if (!cfg.forcesaveUrl) return;
        var actions = document.querySelector('.office-save-actions');
        if (!actions) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-outline-primary';
        btn.id = 'onlyoffice-save-now';
        btn.textContent = 'Save now';
        btn.title = 'Store the current state of the document in clientst0r';
        btn.addEventListener('click', saveNow);
        actions.insertBefore(btn, actions.firstChild);
        office.onRetry(saveNow);
    }

    if (!docConfig) return;
    if (typeof window.DocsAPI === 'undefined' || !window.DocsAPI.DocEditor) {
        showLoadError();
        office.saveFailed('the editor could not be loaded');
        return;
    }

    var events = {
        onAppReady: function () { pollProvider(); },
        onDocumentStateChange: function (ev) {
            if (ev && ev.data === true) office.changesInEditor();
        },
        onError: function (ev) {
            var d = (ev && ev.data) || {};
            office.saveFailed('editor error' + (d.errorCode ? ' ' + d.errorCode : '') +
                              (d.errorDescription ? ': ' + String(d.errorDescription).slice(0, 200) : ''));
        },
        onWarning: function () { /* informational */ },
        onRequestClose: function () {
            var back = document.querySelector('[data-office-back]');
            if (back) back.click();
        },
        onRequestRefreshFile: function () { window.location.reload(); },
        onOutdatedVersion: function () { window.location.reload(); }
    };
    if (cfg.saveAsUrl) {
        events.onRequestSaveAs = function (ev) {
            var d = (ev && ev.data) || {};
            post(cfg.saveAsUrl, {url: d.url || '', fileType: d.fileType || '', title: d.title || ''})
                .then(function (j) {
                    if (j.ok && editor && editor.showMessage) {
                        editor.showMessage('Saved a copy in clientst0r: ' + j.name);
                    } else if (!j.ok) {
                        window.alert('The copy was not saved: ' + (j.error || 'unknown error'));
                    }
                });
        };
    }
    docConfig.events = events;

    try {
        editor = new window.DocsAPI.DocEditor(placeholder, docConfig);
    } catch (e) {
        showLoadError();
        office.saveFailed('the editor could not start');
        return;
    }

    addSaveButton();
    if (!office.config.readOnly) {
        office.watchServer({interval: 4000});
    }
    pollProvider();
    setInterval(pollProvider, 15000);
    // Keep long sessions alive (the session TTL is renewed, never past its maximum).
    setInterval(function () { office.renew(); }, 10 * 60 * 1000);
})();
