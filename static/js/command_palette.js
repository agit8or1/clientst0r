/*
 * Command palette (Ctrl+K / Cmd+K) and the top bar's Favorites / Recent
 * menus. Loaded by base.html (deferred, CSP-safe); markup in
 * templates/core/_topbar_quick.html, rules in core/palette.py.
 *
 *  - Ctrl/Cmd+K opens the palette from anywhere, including text fields,
 *    except inside rich-text editors (contenteditable: Quill uses Ctrl+K
 *    for links). The single-key shortcuts in app_nav.js are untouched.
 *  - Empty input: favorites, recent items, quick commands. Typing filters
 *    the server-provided list of pages this user may open, and (2+ chars,
 *    150 ms debounce, previous request aborted) asks core:palette_search
 *    for records. The query goes in a request header, not the URL.
 *  - Every row is built with textContent; nothing from the server is ever
 *    parsed as HTML. Nothing is written to browser storage.
 */
(function () {
    'use strict';

    var doc = document;
    var root = doc.getElementById('topbarQuick');
    var tpl = doc.getElementById('cmdkTemplate');
    if (!root || !tpl) return;

    var cfg = root.dataset;
    var isMac = /Mac|iPhone|iPad|iPod/.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '');
    var DEBOUNCE = 150, MIN = 2;

    function t(key) { return cfg['i18n' + key.charAt(0).toUpperCase() + key.slice(1)] || ''; }

    // ------------------------------------------------------------ markup
    doc.body.appendChild(tpl.content.cloneNode(true));
    var dialog = doc.getElementById('cmdkDialog');
    var input = doc.getElementById('cmdkInput');
    var list = doc.getElementById('cmdkList');
    var status = dialog.querySelector('[data-cmdk-status]');
    var openBtn = doc.getElementById('cmdkOpen');

    Array.prototype.forEach.call(doc.querySelectorAll('[data-cmdk-kbd]'), function (k) {
        k.textContent = isMac ? '⌘K' : 'Ctrl K';
    });
    if (openBtn) openBtn.setAttribute('title', t('open') + (isMac ? ' (⌘K)' : ' (Ctrl K)'));

    // Phones and tablets: the top bar's controls sit in a collapsed menu, so
    // the palette also gets a button beside the menu toggler.
    var toggler = doc.querySelector('.app-topbar .navbar-toggler');
    if (toggler) {
        var mob = doc.createElement('button');
        mob.type = 'button';
        mob.className = 'cmdk-mobile-btn d-lg-none';
        mob.id = 'cmdkOpenMobile';
        mob.setAttribute('aria-haspopup', 'dialog');
        mob.setAttribute('aria-controls', 'cmdkDialog');
        mob.setAttribute('aria-label', t('open'));
        var mi = doc.createElement('i');
        mi.className = 'fas fa-magnifying-glass';
        mi.setAttribute('aria-hidden', 'true');
        mob.appendChild(mi);
        toggler.parentNode.insertBefore(mob, toggler);
        mob.addEventListener('click', function () { open(); });
    }

    // List it in the ? shortcut help.
    var help = doc.querySelector('#shortcutHelp .shortcut-list');
    if (help) {
        var row = doc.createElement('div');
        var dt = doc.createElement('dt');
        var kb = doc.createElement('kbd');
        kb.textContent = isMac ? '⌘ K' : 'Ctrl K';
        dt.appendChild(kb);
        var dd = doc.createElement('dd');
        dd.textContent = t('open');
        row.appendChild(dt);
        row.appendChild(dd);
        help.insertBefore(row, help.firstChild);
    }

    // ------------------------------------------------------------- data
    var home = null, homeReq = null;

    function getJSON(url, opts) {
        opts = opts || {};
        opts.credentials = 'same-origin';
        opts.headers = Object.assign({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}, opts.headers || {});
        return fetch(url, opts).then(function (r) {
            if (r.status === 429) { var e = new Error('limited'); e.limited = true; throw e; }
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    function loadHome(force) {
        if (home && !force) return Promise.resolve(home);
        if (homeReq && !force) return homeReq;
        homeReq = getJSON(cfg.homeUrl).then(function (d) { home = d; homeReq = null; return d; },
            function (e) { homeReq = null; throw e; });
        return homeReq;
    }

    // ------------------------------------------------------------ render
    var options = [], active = -1, seq = 0;

    function icon(cls) {
        var i = doc.createElement('i');
        i.className = (cls || 'fas fa-circle') + ' fa-fw';
        i.setAttribute('aria-hidden', 'true');
        return i;
    }

    function option(item) {
        var a = doc.createElement('a');
        a.className = 'cmdk__opt';
        a.setAttribute('role', 'option');
        a.setAttribute('aria-selected', 'false');
        a.tabIndex = -1;
        a.id = 'cmdk-opt-' + options.length;
        a.href = item.href;
        a.appendChild(icon(item.icon));
        var text = doc.createElement('span');
        text.className = 'cmdk__opt-text';
        var label = doc.createElement('span');
        label.className = 'cmdk__opt-label';
        label.textContent = item.label;
        text.appendChild(label);
        var detail = item.detail || item.where || '';
        if (detail) {
            var d = doc.createElement('span');
            d.className = 'cmdk__opt-detail';
            d.textContent = detail;
            text.appendChild(d);
        }
        a.appendChild(text);
        if (item.type) {
            var k = doc.createElement('span');
            k.className = 'cmdk__opt-type';
            k.textContent = item.type;
            a.appendChild(k);
        }
        a.addEventListener('mousemove', function () { setActive(options.indexOf(a), false); });
        options.push(a);
        return a;
    }

    function group(label, items, key) {
        if (!items || !items.length) return null;
        var g = doc.createElement('div');
        g.className = 'cmdk__group';
        g.setAttribute('role', 'group');
        var h = doc.createElement('div');
        h.className = 'cmdk__group-label';
        h.id = 'cmdk-g-' + key;
        h.setAttribute('role', 'presentation');
        h.textContent = label;
        g.setAttribute('aria-labelledby', h.id);
        g.appendChild(h);
        items.forEach(function (it) { g.appendChild(option(it)); });
        return g;
    }

    function message(text) {
        var p = doc.createElement('div');
        p.className = 'cmdk__msg';
        p.textContent = text;
        list.appendChild(p);
    }

    function setActive(i, scroll) {
        if (active >= 0 && options[active]) options[active].setAttribute('aria-selected', 'false');
        active = options.length ? Math.max(0, Math.min(i, options.length - 1)) : -1;
        if (active >= 0) {
            options[active].setAttribute('aria-selected', 'true');
            input.setAttribute('aria-activedescendant', options[active].id);
            if (scroll !== false) options[active].scrollIntoView({block: 'nearest'});
        } else {
            input.removeAttribute('aria-activedescendant');
        }
    }

    function reset() {
        list.textContent = '';
        options = [];
        active = -1;
        input.removeAttribute('aria-activedescendant');
    }

    function renderGroups(groups, emptyText) {
        var keep = active;
        reset();
        var any = false;
        groups.forEach(function (g) {
            var el = group(g.label, g.items, g.key);
            if (el) { list.appendChild(el); any = true; }
        });
        if (!any && emptyText) message(emptyText);
        setActive(keep < 0 ? 0 : keep, false);
        if (status) status.textContent = any ? t('count').replace('__N__', options.length) : (emptyText || '');
    }

    // ------------------------------------------------------------ filter
    function norm(s) { return String(s || '').toLowerCase(); }

    function localMatches(q) {
        var words = norm(q).split(/\s+/).filter(Boolean);
        if (!words.length || !home) return {commands: [], pages: []};
        function hit(text) { text = norm(text); return words.every(function (w) { return text.indexOf(w) !== -1; }); }
        var cmds = (home.commands || []).filter(function (c) { return hit(c.label + ' ' + c.keywords); });
        var pages = (home.destinations || []).filter(function (d) {
            return hit(d.label + ' ' + d.section + ' ' + d.group + ' ' + d.keywords);
        }).sort(function (a, b) {
            // Label hits first, then shorter labels.
            var al = hit(a.label) ? 0 : 1, bl = hit(b.label) ? 0 : 1;
            return al - bl || a.label.length - b.label.length;
        }).slice(0, 8).map(function (d) {
            var where = d.section && d.section !== d.label ? d.group + ' › ' + d.section : d.group;
            return {label: d.label, href: d.href, icon: d.icon, where: where};
        });
        return {commands: cmds, pages: pages};
    }

    function everything(q) {
        return {key: 'all', label: '', items: [{
            label: t('everything').replace('__Q__', q),
            href: cfg.allSearchUrl + '?q=' + encodeURIComponent(q),
            icon: 'fas fa-magnifying-glass'
        }]};
    }

    var timer = null, ctrl = null, lastServer = [];

    function renderEmpty() {
        if (!home) { reset(); message(t('loading')); return; }
        renderGroups([
            {key: 'fav', label: t('favorites'), items: home.favorites || []},
            {key: 'recent', label: t('recent'), items: home.recent || []},
            {key: 'cmd', label: t('commands'), items: home.commands || []}
        ], t('noFavorites'));
    }

    function renderQuery(q, server, pending) {
        var local = localMatches(q);
        var groups = [
            {key: 'cmd', label: t('commands'), items: local.commands},
            {key: 'pages', label: t('pages'), items: local.pages}
        ].concat(server || []);
        if (q.length >= MIN) groups.push(everything(q));
        renderGroups(groups, pending ? t('loading') : t('none'));
    }

    function onInput() {
        var q = input.value.trim();
        var my = ++seq;
        if (timer) clearTimeout(timer);
        if (ctrl) { ctrl.abort(); ctrl = null; }
        active = -1;
        if (!q) { lastServer = []; renderEmpty(); return; }
        renderQuery(q, [], q.length >= MIN);
        if (q.length < MIN) return;
        timer = setTimeout(function () {
            ctrl = window.AbortController ? new AbortController() : null;
            getJSON(cfg.searchUrl, {headers: {'X-Palette-Query': encodeURIComponent(q)},
                                    signal: ctrl ? ctrl.signal : undefined})
                .then(function (d) {
                    if (my !== seq) return;
                    lastServer = d.groups || [];
                    renderQuery(q, lastServer, false);
                }, function (e) {
                    if (my !== seq || (e && e.name === 'AbortError')) return;
                    renderQuery(q, [], false);
                    message(e && e.limited ? t('limited') : t('error'));
                });
        }, DEBOUNCE);
    }

    // -------------------------------------------------------- open/close
    var lastFocus = null;

    function isOpen() { return !dialog.hidden; }

    function open() {
        if (isOpen()) { input.focus(); input.select(); return; }
        lastFocus = doc.activeElement;
        dialog.hidden = false;
        doc.documentElement.classList.add('cmdk-open');
        input.value = '';
        renderEmpty();
        input.focus();
        loadHome().then(function () { if (isOpen() && !input.value.trim()) renderEmpty(); },
            function () { if (isOpen() && !input.value.trim()) { reset(); message(t('error')); } });
    }

    function close() {
        if (!isOpen()) return;
        if (timer) clearTimeout(timer);
        if (ctrl) { ctrl.abort(); ctrl = null; }
        seq++;
        dialog.hidden = true;
        doc.documentElement.classList.remove('cmdk-open');
        if (lastFocus && lastFocus.focus && doc.contains(lastFocus)) lastFocus.focus();
        else if (openBtn) openBtn.focus();
    }

    function go(a, newTab) {
        if (!a) return;
        if (newTab) { window.open(a.href, '_blank', 'noopener'); return; }
        window.location.href = a.href;
    }

    if (openBtn) openBtn.addEventListener('click', function () { open(); });
    dialog.addEventListener('click', function (e) {
        if (e.target.closest('[data-cmdk-close]')) close();
    });
    input.addEventListener('input', onInput);
    input.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setActive(active + (e.key === 'ArrowDown' ? 1 : -1));
        } else if (e.key === 'Home' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault(); setActive(0);
        } else if (e.key === 'End' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault(); setActive(options.length - 1);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            go(options[active], e.ctrlKey || e.metaKey);
        }
    });
    dialog.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            close();
        } else if (e.key === 'Tab') {
            // Focus stays in the dialog: the field and the close button.
            var f = [input, dialog.querySelector('.cmdk__close')];
            var i = f.indexOf(doc.activeElement);
            e.preventDefault();
            f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus();
        }
    });

    function inRichEditor(el) {
        if (!el || el.nodeType !== 1) return false;
        return el.isContentEditable || !!el.closest('[contenteditable], .ql-editor, .tox, .CodeMirror, .cm-editor, [data-cmdk-ignore]');
    }

    doc.addEventListener('keydown', function (e) {
        if (e.defaultPrevented || e.altKey || e.shiftKey) return;
        if (!(e.ctrlKey || e.metaKey) || (e.key !== 'k' && e.key !== 'K')) return;
        if (inRichEditor(e.target)) return;
        e.preventDefault();
        if (isOpen()) close(); else open();
    });

    // ----------------------------------------------- Favorites / Recent
    function menuItem(item) {
        var li = doc.createElement('li');
        var a = doc.createElement('a');
        a.className = 'dropdown-item quick-menu__item';
        a.href = item.href;
        a.appendChild(icon(item.icon));
        var text = doc.createElement('span');
        text.className = 'quick-menu__text';
        var l = doc.createElement('span');
        l.className = 'quick-menu__label';
        l.textContent = item.label;
        text.appendChild(l);
        var detail = [item.type, item.detail].filter(Boolean).join(' · ');
        if (detail) {
            var d = doc.createElement('span');
            d.className = 'quick-menu__detail';
            d.textContent = detail;
            text.appendChild(d);
        }
        a.appendChild(text);
        li.appendChild(a);
        return li;
    }

    function fillMenu(ul, items, emptyText) {
        ul.textContent = '';
        ul.removeAttribute('aria-busy');
        if (!items.length) {
            var li = doc.createElement('li');
            li.className = 'quick-menu__empty';
            li.textContent = emptyText;
            ul.appendChild(li);
            return;
        }
        items.forEach(function (it) { ul.appendChild(menuItem(it)); });
    }

    function starButton(btn, state) {
        if (!btn) return;
        btn.hidden = !(state && state.favoritable);
        if (btn.hidden) return;
        btn.setAttribute('aria-pressed', state.favorited ? 'true' : 'false');
        var i = btn.querySelector('i');
        if (i) i.className = (state.favorited ? 'fas' : 'far') + ' fa-star';
        var label = btn.querySelector('[data-star-label]');
        if (label) label.textContent = state.favorited ? t('unstar') : t('star');
    }

    Array.prototype.forEach.call(doc.querySelectorAll('[data-quick-menu]'), function (holder) {
        var kind = holder.getAttribute('data-quick-menu');
        var ul = holder.querySelector('[data-quick-list]');
        var star = holder.querySelector('[data-star-current]');
        function load() {
            ul.setAttribute('aria-busy', 'true');
            if (!ul.children.length) {
                var li = doc.createElement('li');
                li.className = 'quick-menu__empty';
                li.textContent = t('loading');
                ul.appendChild(li);
            }
            var url = cfg.homeUrl + '?parts=' + (kind === 'favorites' ? 'favorites' : 'recent');
            if (kind === 'favorites') url += '&path=' + encodeURIComponent(window.location.pathname);
            getJSON(url).then(function (d) {
                if (kind === 'favorites') {
                    fillMenu(ul, d.favorites || [], t('noFavorites'));
                    starButton(star, d.current);
                } else {
                    fillMenu(ul, d.recent || [], t('noRecent'));
                }
            }, function () { fillMenu(ul, [], t('error')); });
        }
        holder.addEventListener('show.bs.dropdown', load);
        if (star) star.addEventListener('click', function () {
            var body = new FormData();
            body.append('path', window.location.pathname);
            star.disabled = true;
            getJSON(cfg.favoriteUrl, {method: 'POST', body: body, headers: {'X-CSRFToken': cfg.csrf}})
                .then(function (d) {
                    starButton(star, d.current);
                    home = null;  // the palette's favorites are stale now
                    load();
                    if (window.appToast) window.appToast(d.current && d.current.favorited ? t('starred') : t('unstarred'), 'success');
                }, function () { if (window.appToast) window.appToast(t('error'), 'error'); })
                .then(function () { star.disabled = false; });
        });
    });
})();
