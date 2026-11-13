/*
 * Public signing page: signature pad, typed/drawn switch, and the
 * interaction beacon that tells the sender the page was really looked at.
 *
 * The beacon fires once, only after a person interacts with the page
 * (scroll, pointer, key or touch) while it is visible. Link scanners and
 * previewers that fetch the page without running it, or run it without
 * interacting, never send it. The server also requires a one-use nonce.
 */
(function () {
    'use strict';
    var root = document.getElementById('cs-root');
    if (!root) return;

    // --- interaction beacon -------------------------------------------------
    var seenUrl = root.getAttribute('data-seen-url');
    var nonce = root.getAttribute('data-nonce');
    var csrf = root.getAttribute('data-csrf');
    var sent = false, armed = false;
    setTimeout(function () { armed = true; }, 1500);   // ignore events fired during load

    function beacon() {
        if (sent || !armed || document.visibilityState !== 'visible' || !seenUrl || !nonce) return;
        sent = true;
        EVENTS.forEach(function (e) { window.removeEventListener(e, beacon, true); });
        var body = new URLSearchParams();
        body.set('nonce', nonce);
        body.set('interacted', '1');
        body.set('csrfmiddlewaretoken', csrf || '');
        fetch(seenUrl, {
            method: 'POST', body: body, credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf || '' }
        }).catch(function () { /* best effort */ });
    }
    var EVENTS = ['scroll', 'pointerdown', 'keydown', 'touchstart', 'wheel'];
    EVENTS.forEach(function (e) { window.addEventListener(e, beacon, { capture: true, passive: true }); });

    // --- typed / drawn ---------------------------------------------------------
    var form = document.getElementById('cs-sign-form');
    if (!form) return;
    var panes = form.querySelectorAll('[data-pane]');
    var typed = document.getElementById('cs-typed-sig');
    var nameField = document.getElementById('cs-name');

    function method() {
        var r = form.querySelector('input[name="method"]:checked');
        return r ? r.value : 'typed';
    }
    function showPane() {
        var m = method();
        panes.forEach(function (p) { p.hidden = p.getAttribute('data-pane') !== m; });
        if (typed) typed.required = m === 'typed';
        if (m === 'drawn') sizePad();
    }
    form.querySelectorAll('[data-sign-method]').forEach(function (r) { r.addEventListener('change', showPane); });
    if (typed && nameField && !typed.value) typed.placeholder = nameField.value || 'Type your name';

    // --- signature pad -------------------------------------------------------------
    var pad = form.querySelector('.cs-pad');
    var data = document.getElementById('cs-sig-data');
    var ctx = pad ? pad.getContext('2d') : null;
    var drawing = false, inked = false, last = null;

    function sizePad() {
        if (!pad) return;
        var ratio = Math.max(window.devicePixelRatio || 1, 1);
        var w = pad.clientWidth || 600, h = pad.clientHeight || 180;
        if (pad.width === Math.round(w * ratio) && pad.height === Math.round(h * ratio)) return;
        var keep = inked ? pad.toDataURL('image/png') : null;
        pad.width = Math.round(w * ratio); pad.height = Math.round(h * ratio);
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#111';
        if (keep) { var img = new Image(); img.onload = function () { ctx.drawImage(img, 0, 0, w, h); }; img.src = keep; }
    }
    function pos(ev) {
        var r = pad.getBoundingClientRect();
        return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }
    if (pad) {
        pad.addEventListener('pointerdown', function (ev) {
            ev.preventDefault(); sizePad();
            drawing = true; last = pos(ev);
            pad.setPointerCapture(ev.pointerId);
            ctx.beginPath(); ctx.arc(last.x, last.y, 1.1, 0, Math.PI * 2); ctx.fillStyle = '#111'; ctx.fill();
            inked = true;
        });
        pad.addEventListener('pointermove', function (ev) {
            if (!drawing) return;
            var p = pos(ev);
            ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke();
            last = p;
        });
        var end = function () { if (drawing) { drawing = false; data.value = pad.toDataURL('image/png'); } };
        pad.addEventListener('pointerup', end);
        pad.addEventListener('pointercancel', end);
        window.addEventListener('resize', function () { if (method() === 'drawn') sizePad(); });
        var clear = form.querySelector('[data-clear-pad]');
        if (clear) clear.addEventListener('click', function () {
            ctx.clearRect(0, 0, pad.width, pad.height); inked = false; data.value = '';
        });
    }

    form.addEventListener('submit', function (ev) {
        var m = method();
        if (m === 'drawn' && !inked) {
            ev.preventDefault();
            window.alert('Draw your signature in the box, or choose "Type".');
            return;
        }
        if (m === 'drawn' && pad) data.value = pad.toDataURL('image/png');
        if (m === 'typed' && data) data.value = '';
        var btn = form.querySelector('button[type="submit"], button:not([type])');
        if (btn) { btn.disabled = true; btn.textContent = 'Signing…'; }
    });
    showPane();
})();
