/*
 * Collabora Online glue for the Office editor page (templates/office/collabora/editor.html).
 * Loaded after office-editor.js; drives window.ClientstorOffice.
 *
 * 1. Submits the hidden form (access_token + access_token_ttl) to the discovery
 *    urlsrc, targeting the named iframe. The token never goes into a URL.
 * 2. Speaks Collabora's postMessage protocol (browser/src/map/handler/Map.WOPI.js,
 *    26.04): messages are JSON strings {MessageId, SendTime, Values}.
 *      in:  App_LoadingStatus {Status: 'Frame_Ready' | 'Document_Loaded' | 'Failed'*}
 *           Doc_ModifiedStatus {Modified: bool}
 *           Action_Save_Resp {success: bool, result?}
 *           Get_Views_Resp [...], View_Added, View_Removed  (* unverified names/shape)
 *      out: Host_PostmessageReady (first), Action_Save, Get_Views*
 *    Every incoming message is ignored unless event.origin is the instance origin
 *    AND event.source is our iframe. Outgoing messages name that origin.
 * 3. "Saved to clientst0r" is shown only by ClientstorOffice.watchServer(), i.e.
 *    after clientst0r reports a stored revision. Collabora saying "not modified"
 *    only moves the indicator to "Saving…".
 * 4. Renews the session and its WOPI tokens while the page is open.
 */
(function () {
    'use strict';
    var office = window.ClientstorOffice;
    if (!office) return;
    var cfg = office.providerConfig || {};
    var origin = cfg.editorOrigin;
    var form = document.getElementById(cfg.formId);
    var frame = document.getElementById('collabora-frame');
    if (!origin || !form || !frame) return;

    var hostReadySent = false;
    var loaded = false;
    var confirmTimer = null;

    function send(id, values) {
        if (!frame.contentWindow) return;
        frame.contentWindow.postMessage(JSON.stringify({
            MessageId: id, SendTime: Date.now(), Values: values || {}
        }), origin);
    }

    function post(url, fields) {
        var body = new FormData();
        body.append('csrfmiddlewaretoken', office.config.csrfToken || '');
        Object.keys(fields || {}).forEach(function (k) { body.append(k, fields[k]); });
        return fetch(url, {method: 'POST', body: body, credentials: 'same-origin',
                           headers: {'Accept': 'application/json'}});
    }

    function report(eventName) {
        if (cfg.eventUrl) post(cfg.eventUrl, {event: eventName}).catch(function () {});
    }

    function saveNow() {
        office.saving();
        send('Action_Save', {DontTerminateEdit: true, DontSaveIfUnmodified: false, Notify: true});
    }

    // Toolbar (CODE badge, Save now) moves into the page header.
    var toolbar = document.getElementById('collabora-toolbar');
    var actions = document.querySelector('.office-save-actions');
    var saveBtn = document.getElementById('collabora-save-now');
    if (toolbar && actions) {
        while (toolbar.firstElementChild) actions.insertBefore(toolbar.firstElementChild, actions.firstChild);
    }
    if (saveBtn) saveBtn.addEventListener('click', saveNow);
    if (!cfg.readOnly) office.onRetry(saveNow);

    function awaitServerConfirmation() {
        // Collabora reports the document unmodified after it stored it through
        // WOPI; clientst0r's status poll turns this into "Saved". If no new
        // revision appears (an unchanged document is not stored twice), go
        // back to "No unsaved changes" rather than claiming a save.
        clearTimeout(confirmTimer);
        if (office.state === 'dirty') office.saving();
        confirmTimer = setTimeout(function () {
            if (office.state === 'saving') office.setState('clean');
        }, 45000);
    }

    function setCollaborators(views) {
        if (!Array.isArray(views)) return;
        office.setCollaborators(views.map(function (v) {
            return {id: v.UserId || v.ViewId, name: v.UserName || ''};
        }));
    }

    window.addEventListener('message', function (ev) {
        if (ev.origin !== origin || ev.source !== frame.contentWindow) return;
        var msg = ev.data;
        if (typeof msg === 'string') {
            try { msg = JSON.parse(msg); } catch (e) { return; }
        }
        if (!msg || typeof msg.MessageId !== 'string') return;
        var v = msg.Values || {};
        switch (msg.MessageId) {
            case 'App_LoadingStatus':
                if (v.Status === 'Frame_Ready' && !hostReadySent) {
                    hostReadySent = true;
                    send('Host_PostmessageReady', {});
                    report('frame_ready');
                } else if (v.Status === 'Document_Loaded' && !loaded) {
                    loaded = true;
                    if (saveBtn) saveBtn.disabled = false;
                    office.setState(cfg.readOnly ? 'readonly' : 'clean');
                    report('document_loaded');
                    send('Get_Views', {});
                } else if (v.Status === 'Failed') {
                    office.saveFailed('the editor could not load the document');
                    report('load_failed');
                }
                break;
            case 'Doc_ModifiedStatus':
                if (v.Modified) {
                    clearTimeout(confirmTimer);
                    office.changesInEditor();
                } else {
                    awaitServerConfirmation();
                }
                break;
            case 'Action_Save_Resp':
                if (v.success === false) {
                    clearTimeout(confirmTimer);
                    office.saveFailed(String(v.result || v.errorMsg || 'the editor could not save').slice(0, 120));
                } else {
                    awaitServerConfirmation();
                }
                break;
            case 'Get_Views_Resp':
                setCollaborators(v);
                break;
            case 'View_Added':
            case 'View_Removed':
                send('Get_Views', {});
                break;
        }
    });

    // Session + WOPI token renewal for long editing sessions.
    function renew() {
        post(cfg.renewUrl).then(function (r) {
            return r.json().catch(function () { return {ok: false}; });
        }).then(function (j) {
            if (!j.ok) office.saveFailed(j.error || 'the editing session ended');
        }).catch(function () { /* offline: the next attempt retries */ });
    }
    if (cfg.renewUrl) setInterval(renew, cfg.renewIntervalMs || 600000);

    office.watchServer({interval: 4000});
    form.submit();
})();
