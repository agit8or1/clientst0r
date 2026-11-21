/*
 * "Viewed" beacon for quotes and invoices sent to a customer (psa/doc_views.py).
 *
 * The element with data-doc-view-url holds the beacon URL, a signed one-use
 * nonce for this page load and the CSRF token. The beacon is sent once, only
 * after a person interacts with the visible page (scroll, pointer, key or
 * touch, at least 1.5 s after load). Scanners and prefetchers that fetch the
 * page without running it, or run it without interacting, never send it.
 */
(function () {
    'use strict';
    var root = document.querySelector('[data-doc-view-url]');
    if (!root || !window.fetch) return;
    var url = root.getAttribute('data-doc-view-url');
    var nonce = root.getAttribute('data-doc-view-nonce');
    var csrf = root.getAttribute('data-doc-view-csrf');
    var sent = false, armed = false;
    setTimeout(function () { armed = true; }, 1500);
    var EVENTS = ['scroll', 'pointerdown', 'keydown', 'touchstart', 'wheel'];

    function beacon() {
        if (sent || !armed || document.visibilityState !== 'visible' || !url || !nonce) return;
        sent = true;
        EVENTS.forEach(function (e) { window.removeEventListener(e, beacon, true); });
        var body = new URLSearchParams();
        body.set('nonce', nonce);
        body.set('interacted', '1');
        body.set('csrfmiddlewaretoken', csrf || '');
        fetch(url, { method: 'POST', body: body, credentials: 'same-origin',
                     headers: { 'X-CSRFToken': csrf || '' } }).catch(function () { /* best effort */ });
    }
    EVENTS.forEach(function (e) { window.addEventListener(e, beacon, { capture: true, passive: true }); });
}());
