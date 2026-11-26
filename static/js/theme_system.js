/* System theme (113.5): follow the device's light/dark setting.
 *
 * Loaded synchronously in <head> (before the stylesheets paint) by base.html and
 * the other staff page shells. It acts only when <html data-theme-mode="system">:
 * the server renders the light palette (data-theme-light) and this switches
 * data-theme, data-bs-theme and the theme-color meta to the dark palette
 * (data-theme-dark) when prefers-color-scheme is dark, then follows changes
 * while the page is open. data-cs-theme="system" stays as rendered: the token
 * stylesheet follows the same media query on its own. No inline script, so it
 * needs no CSP nonce; nothing is stored or sent.
 */
(function () {
    'use strict';
    var root = document.documentElement;
    if (root.getAttribute('data-theme-mode') !== 'system' || !window.matchMedia) return;
    var light = root.getAttribute('data-theme-light') || 'default';
    var dark = root.getAttribute('data-theme-dark') || 'professional';
    var mq = window.matchMedia('(prefers-color-scheme: dark)');

    function apply() {
        var isDark = !!mq.matches;
        root.setAttribute('data-theme', isDark ? dark : light);
        root.setAttribute('data-bs-theme', isDark ? 'dark' : 'light');
        var meta = document.querySelector('meta[name="theme-color"]');
        var colour = meta && meta.getAttribute(isDark ? 'data-dark' : 'data-light');
        if (colour) meta.setAttribute('content', colour);
    }
    apply();
    if (mq.addEventListener) mq.addEventListener('change', apply);
    else if (mq.addListener) mq.addListener(apply);
})();
