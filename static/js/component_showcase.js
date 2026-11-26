/* Interface components showcase (113.11).
 * Previews a theme and density on this tab only: it sets the same attributes
 * base.html renders on <html> (data-theme, data-bs-theme, data-density) and
 * never saves them or calls the server. Demo forms never submit. */
(function () {
    'use strict';
    var root = document.documentElement;
    var initial = {
        theme: root.getAttribute('data-theme'),
        bs: root.getAttribute('data-bs-theme'),
        density: root.getAttribute('data-density') || 'compact'
    };
    var themeSel = document.getElementById('csTheme');
    var state = document.getElementById('csState');
    var DARK = { professional: 1, dark: 1, dracula: 1, monokai: 1 };

    function apply(theme, density) {
        root.setAttribute('data-theme', theme);
        root.setAttribute('data-bs-theme', DARK[theme] ? 'dark' : 'light');
        root.setAttribute('data-density', density);
        if (themeSel) themeSel.value = theme;
        var c = document.getElementById('csCompact'), f = document.getElementById('csComfortable');
        if (c) c.setAttribute('aria-pressed', density === 'compact' ? 'true' : 'false');
        if (f) f.setAttribute('aria-pressed', density === 'comfortable' ? 'true' : 'false');
        if (c) c.classList.toggle('active', density === 'compact');
        if (f) f.classList.toggle('active', density === 'comfortable');
        var l = document.getElementById('csLight'), d = document.getElementById('csDark');
        if (l) l.classList.toggle('active', !DARK[theme]);
        if (d) d.classList.toggle('active', !!DARK[theme]);
        if (state) state.textContent = 'Previewing ' + theme + ', ' + density + ' (not saved).';
    }
    function cur() { return [root.getAttribute('data-theme'), root.getAttribute('data-density') || 'compact']; }

    if (themeSel) themeSel.addEventListener('change', function () { apply(themeSel.value, cur()[1]); });
    function on(id, fn) { var e = document.getElementById(id); if (e) e.addEventListener('click', fn); }
    on('csLight', function () { apply('default', cur()[1]); });
    on('csDark', function () { apply('professional', cur()[1]); });
    on('csCompact', function () { apply(cur()[0], 'compact'); });
    on('csComfortable', function () { apply(cur()[0], 'comfortable'); });
    on('csReset', function () {
        apply(initial.theme, initial.density);
        root.setAttribute('data-bs-theme', initial.bs);
        if (state) state.textContent = 'Back to your own settings.';
    });
    apply(initial.theme, initial.density);
    if (state) state.textContent = '';

    // Demo forms and their buttons do nothing.
    document.querySelectorAll('[data-demo-form]').forEach(function (f) {
        f.addEventListener('submit', function (e) { e.preventDefault(); });
    });
    document.querySelectorAll('.cs-demo a[href^="#"]').forEach(function (a) {
        a.addEventListener('click', function (e) {
            if (a.getAttribute('href') === '#cmp-' + a.closest('section').id.slice(4)) e.preventDefault();
        });
    });

    document.querySelectorAll('[data-cs-toast]').forEach(function (b) {
        b.addEventListener('click', function () {
            var kind = b.getAttribute('data-cs-toast');
            if (window.appToast && document.getElementById('appToasts')) {
                window.appToast('Sample ' + kind + ' message (nothing was saved).', kind);
            } else if (state) {
                state.textContent = 'This page has no toast region; see the static samples.';
            }
        });
    });
})();
