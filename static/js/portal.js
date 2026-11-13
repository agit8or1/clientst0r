/*
 * Customer portal page behaviour (templates/portal/base.html and the portal
 * sign-in pages). No inline handlers: everything is wired here.
 *
 *  - Bootstrap components follow the portal's light/dark choice: pinned by
 *    data-portal-theme on <html>, otherwise the visitor's system preference.
 *  - [data-portal-menu-toggle] opens and closes the navigation on small screens.
 *  - form[data-portal-once] is submitted once (signing in replaces the CSRF
 *    token, so a second submit would be refused).
 */
(function () {
    'use strict';
    var root = document.documentElement;

    function applyScheme() {
        var pinned = root.getAttribute('data-portal-theme');
        var dark = pinned === 'dark' ||
            (pinned !== 'light' && window.matchMedia &&
             window.matchMedia('(prefers-color-scheme: dark)').matches);
        root.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
    }
    applyScheme();
    if (window.matchMedia) {
        var mq = window.matchMedia('(prefers-color-scheme: dark)');
        if (mq.addEventListener) mq.addEventListener('change', applyScheme);
    }

    document.addEventListener('click', function (ev) {
        var toggle = ev.target.closest && ev.target.closest('[data-portal-menu-toggle]');
        if (!toggle) return;
        var nav = document.getElementById(toggle.getAttribute('aria-controls'));
        if (!nav) return;
        var open = nav.classList.toggle('show');
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (!form.hasAttribute || !form.hasAttribute('data-portal-once')) return;
        if (form.dataset.submitted) { ev.preventDefault(); return; }
        form.dataset.submitted = '1';
        setTimeout(function () { delete form.dataset.submitted; }, 10000);
    });
    window.addEventListener('pageshow', function () {
        document.querySelectorAll('form[data-submitted]').forEach(function (f) {
            delete f.dataset.submitted;
        });
    });
})();
