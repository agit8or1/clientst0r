/*
 * Settings workspace (templates/core/_settings_menu.html).
 *
 *  - Search: filters the settings pages this user may open (the hidden
 *    .settings-ws__index list, already gated on the server) by label and
 *    keywords. Arrow keys move through the matches, Enter opens the first,
 *    Escape clears.
 *  - Unsaved changes: once a POST form in the page content has been edited,
 *    leaving the page asks first (beforeunload). Submitting the form, or a
 *    form marked data-no-dirty-check, does not ask.
 *
 * CSP-safe (no inline handlers), no storage.
 */
(function () {
    'use strict';
    var doc = document;
    var ws = doc.querySelector('[data-settings-ws]');
    if (!ws) return;

    // ---------------------------------------------------------- search
    var input = doc.getElementById('settingsSearch');
    var results = doc.getElementById('settingsSearchResults');
    var status = doc.getElementById('settingsSearchStatus');
    var index = Array.prototype.map.call(ws.querySelectorAll('.settings-ws__index li'), function (li) {
        return {
            href: li.getAttribute('data-href'),
            label: li.getAttribute('data-label'),
            where: li.getAttribute('data-where'),
            text: (li.getAttribute('data-filter') || '').toLowerCase()
        };
    });

    function render() {
        var q = (input.value || '').toLowerCase().replace(/\s+/g, ' ').trim();
        results.textContent = '';
        if (!q) { results.hidden = true; status.textContent = ''; return; }
        var words = q.split(' ');
        var hits = index.filter(function (p) {
            return words.every(function (w) { return p.text.indexOf(w) !== -1; });
        }).slice(0, 12);
        hits.forEach(function (p) {
            var li = doc.createElement('li');
            var a = doc.createElement('a');
            a.href = p.href;
            a.className = 'settings-ws__result';
            var label = doc.createElement('span');
            label.textContent = p.label;
            var where = doc.createElement('span');
            where.className = 'settings-ws__result-where';
            where.textContent = p.where;
            a.appendChild(label);
            a.appendChild(where);
            li.appendChild(a);
            results.appendChild(li);
        });
        if (!hits.length) {
            var none = doc.createElement('li');
            none.className = 'settings-ws__none';
            none.textContent = input.getAttribute('data-i18n-none');
            results.appendChild(none);
        }
        results.hidden = false;
        status.textContent = hits.length
            ? input.getAttribute('data-i18n-count').replace('__N__', hits.length)
            : input.getAttribute('data-i18n-none');
    }

    function links() { return Array.prototype.slice.call(results.querySelectorAll('a')); }

    if (input && results) {
        input.addEventListener('input', render);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                var first = links()[0];
                if (first) { e.preventDefault(); window.location.href = first.href; }
            } else if (e.key === 'Escape') {
                input.value = '';
                render();
            } else if (e.key === 'ArrowDown') {
                var l = links();
                if (l.length) { e.preventDefault(); l[0].focus(); }
            }
        });
        results.addEventListener('keydown', function (e) {
            var l = links();
            var i = l.indexOf(doc.activeElement);
            if (i === -1) return;
            if (e.key === 'ArrowDown' && l[i + 1]) { e.preventDefault(); l[i + 1].focus(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); (l[i - 1] || input).focus(); }
            else if (e.key === 'Escape') { input.focus(); input.value = ''; render(); }
        });
        doc.addEventListener('click', function (e) {
            if (!results.hidden && !e.target.closest('.settings-ws__search')) results.hidden = true;
        });
        input.addEventListener('focus', function () { if (input.value) render(); });
    }

    // ------------------------------------------------- unsaved changes
    var main = doc.getElementById('main-content');
    var dirty = null;  // the form with unsaved edits
    function watched(form) {
        return form && (form.getAttribute('method') || 'get').toLowerCase() === 'post'
            && !form.hasAttribute('data-no-dirty-check') && main && main.contains(form)
            && !ws.contains(form);
    }
    function mark(e) {
        var el = e.target;
        if (!el || !el.form || !watched(el.form)) return;
        if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;
        dirty = el.form;
    }
    if (main) {
        main.addEventListener('input', mark, true);
        main.addEventListener('change', mark, true);
        main.addEventListener('submit', function () { dirty = null; }, true);
    }
    window.addEventListener('beforeunload', function (e) {
        if (!dirty || !doc.body.contains(dirty)) return undefined;
        e.preventDefault();
        e.returnValue = '';
        return '';
    });
})();
