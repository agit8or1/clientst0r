/*
 * Technician shell behaviour (loaded by base.html, deferred, CSP-safe).
 *
 *  - Sidebar (#appNav, core/_primary_nav.html): filter-as-you-type, group
 *    expand/collapse (remembered), icon-rail collapse (remembered), and a
 *    drawer below 992px with focus moved in and restored on close.
 *  - Keyboard shortcuts with a ? help overlay (#shortcutHelp). Ignored while
 *    typing in a field, in a contenteditable, or with Ctrl/Alt/Meta held.
 *  - window.appToast(message, kind): visible feedback for actions that used
 *    to fail with only a console message.
 *  - Busy state on POST form submit (spinner, aria-busy, double-submit
 *    guard); a form or button with data-no-busy opts out.
 *
 * Storage is per browser (localStorage) and only holds UI preferences.
 */
(function () {
    'use strict';

    var doc = document;
    var body = doc.body;
    var STORE_RAIL = 'appnav.rail';
    var STORE_OPEN = 'appnav.open';
    var DRAWER_MQ = window.matchMedia('(max-width: 991.98px)');

    function store(key, value) {
        try {
            if (value === undefined) return window.localStorage.getItem(key);
            if (value === null) window.localStorage.removeItem(key);
            else window.localStorage.setItem(key, value);
        } catch (e) { /* private mode: preferences just don't stick */ }
        return null;
    }

    // ------------------------------------------------------------- toasts
    function appToast(message, kind) {
        var region = doc.getElementById('appToasts');
        if (!region) { window.alert(message); return; }
        var el = doc.createElement('div');
        el.className = 'app-toast app-toast--' + (kind || 'info');
        el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        var text = doc.createElement('span');
        text.textContent = message;
        var close = doc.createElement('button');
        close.type = 'button';
        close.className = 'btn-close btn-close-white ms-2';
        close.setAttribute('aria-label', 'Dismiss');
        close.addEventListener('click', function () { el.remove(); });
        el.appendChild(text);
        el.appendChild(close);
        region.appendChild(el);
        setTimeout(function () { el.classList.add('is-leaving'); }, kind === 'error' ? 9000 : 4000);
        setTimeout(function () { el.remove(); }, kind === 'error' ? 9600 : 4600);
    }
    window.appToast = appToast;

    // ------------------------------------------------------------ sidebar
    var nav = doc.getElementById('appNav');
    var filter = doc.getElementById('appNavFilter');
    var status = doc.getElementById('appNavFilterStatus');
    var openBtn = doc.getElementById('appNavOpen');
    var closeBtn = doc.getElementById('appNavClose');
    var railBtn = doc.getElementById('appNavCollapse');
    var backdrop = doc.getElementById('appNavBackdrop');
    var lastFocus = null;

    function openGroups() {
        try { return JSON.parse(store(STORE_OPEN) || '[]'); } catch (e) { return []; }
    }

    function setGroupOpen(group, open, remember) {
        var list = group.querySelector('.app-nav__entries');
        var toggle = group.querySelector('.app-nav__toggle');
        if (!list) return;
        list.hidden = !open;
        if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (remember) {
            var key = group.getAttribute('data-group');
            var keys = openGroups().filter(function (k) { return k !== key; });
            if (open) keys.push(key);
            store(STORE_OPEN, JSON.stringify(keys));
        }
    }

    function setRail(on) {
        body.classList.toggle('appnav-rail', on);
        if (railBtn) {
            railBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            var label = railBtn.getAttribute(on ? 'data-label-expand' : 'data-label-collapse');
            railBtn.setAttribute('aria-label', label);
            railBtn.setAttribute('title', label + ' ( [ )');
        }
        store(STORE_RAIL, on ? '1' : null);
    }

    function drawerOpen() { return body.classList.contains('appnav-open'); }

    function openDrawer() {
        if (!nav) return;
        lastFocus = doc.activeElement;
        body.classList.add('appnav-open');
        if (backdrop) backdrop.hidden = false;
        if (openBtn) openBtn.setAttribute('aria-expanded', 'true');
        (filter || nav).focus();
    }

    function closeDrawer() {
        if (!drawerOpen()) return;
        body.classList.remove('appnav-open');
        if (backdrop) backdrop.hidden = true;
        if (openBtn) openBtn.setAttribute('aria-expanded', 'false');
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    function visibleLinks() {
        if (!nav) return [];
        return Array.prototype.filter.call(
            nav.querySelectorAll('.app-nav__link, .app-nav__sublink, .app-nav__group-link'),
            function (a) { return a.offsetParent !== null; });
    }

    function norm(s) { return (s || '').toLowerCase().replace(/\s+/g, ' ').trim(); }

    function applyFilter() {
        if (!nav || !filter) return;
        var q = norm(filter.value);
        var tokens = q ? q.split(' ') : [];
        var groups = nav.querySelectorAll('.app-nav__group');
        var matches = 0;
        nav.classList.toggle('is-filtering', tokens.length > 0);
        Array.prototype.forEach.call(groups, function (group) {
            var groupHit = false;
            Array.prototype.forEach.call(group.querySelectorAll('.app-nav__entry'), function (entry) {
                var own = norm(entry.getAttribute('data-filter'));
                var entryHit = tokens.every(function (t) { return own.indexOf(t) !== -1; });
                var sub = entry.querySelector('.app-nav__sub');
                var subHit = false;
                if (sub) {
                    Array.prototype.forEach.call(sub.children, function (li) {
                        var hit = tokens.length > 0 && tokens.every(function (t) {
                            return norm(li.getAttribute('data-filter')).indexOf(t) !== -1;
                        });
                        li.hidden = tokens.length > 0 && !hit && !entryHit;
                        var subLink = li.querySelector('a');
                        if (subLink) subLink.classList.toggle('is-match', hit);
                        if (hit) { subHit = true; matches++; }
                    });
                    sub.hidden = tokens.length ? !(subHit || entryHit) : !entry.querySelector('.app-nav__link.active');
                }
                var show = !tokens.length || entryHit || subHit;
                entry.hidden = !show;
                var link = entry.querySelector('.app-nav__link');
                if (link) link.classList.toggle('is-match', tokens.length > 0 && entryHit);
                if (tokens.length && entryHit) matches++;
                if (show && tokens.length) groupHit = true;
            });
            if (tokens.length) {
                group.hidden = !groupHit;
                var list = group.querySelector('.app-nav__entries');
                if (list) list.hidden = !groupHit;
            } else {
                group.hidden = false;
                var key = group.getAttribute('data-group');
                setGroupOpen(group, group.classList.contains('is-active') || openGroups().indexOf(key) !== -1, false);
            }
        });
        var empty = nav.querySelector('.app-nav__empty');
        if (empty) empty.hidden = !(tokens.length && matches === 0);
        if (status) {
            status.textContent = !tokens.length ? '' : matches
                ? status.getAttribute('data-i18n-count').replace('__N__', matches)
                : status.getAttribute('data-i18n-none');
        }
    }

    function searchEverything(q) {
        var url = nav && nav.getAttribute('data-search-url');
        if (url && q) window.location.href = url + '?q=' + encodeURIComponent(q);
    }

    if (nav) {
        // Restore remembered state before first paint settles.
        if (store(STORE_RAIL) === '1' && !DRAWER_MQ.matches) setRail(true);
        var remembered = openGroups();
        Array.prototype.forEach.call(nav.querySelectorAll('.app-nav__group'), function (g) {
            if (remembered.indexOf(g.getAttribute('data-group')) !== -1) setGroupOpen(g, true, false);
        });

        nav.addEventListener('click', function (e) {
            var toggle = e.target.closest('.app-nav__toggle');
            if (toggle) {
                var group = toggle.closest('.app-nav__group');
                setGroupOpen(group, toggle.getAttribute('aria-expanded') !== 'true', true);
                return;
            }
            if (e.target.closest('[data-app-nav-search]')) {
                searchEverything(filter ? filter.value.trim() : '');
                return;
            }
            if (e.target.closest('[data-shortcut-help]')) {
                showHelp();
                return;
            }
        });

        if (filter) {
            filter.addEventListener('input', applyFilter);
            filter.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    // The first link that matched itself, not a parent shown for context.
                    var links = visibleLinks().filter(function (a) {
                        return !a.classList.contains('app-nav__group-link');
                    });
                    var first = links.filter(function (a) {
                        return a.classList.contains('is-match');
                    })[0] || links[0];
                    if (filter.value.trim() && first && !nav.querySelector('.app-nav__empty:not([hidden])')) {
                        window.location.href = first.href;
                    } else {
                        searchEverything(filter.value.trim());
                    }
                } else if (e.key === 'Escape') {
                    if (filter.value) { filter.value = ''; applyFilter(); }
                    else if (drawerOpen()) closeDrawer();
                    else filter.blur();
                } else if (e.key === 'ArrowDown') {
                    var links = visibleLinks();
                    if (links.length) { e.preventDefault(); links[0].focus(); }
                }
            });
        }

        // Arrow keys move between visible links inside the sidebar.
        nav.addEventListener('keydown', function (e) {
            if (e.target === filter || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
            var links = visibleLinks();
            var i = links.indexOf(e.target);
            if (i === -1) return;
            e.preventDefault();
            var next = links[i + (e.key === 'ArrowDown' ? 1 : -1)];
            if (next) next.focus();
            else if (e.key === 'ArrowUp' && filter) filter.focus();
        });

        if (railBtn) railBtn.addEventListener('click', function () {
            setRail(!body.classList.contains('appnav-rail'));
        });
        if (openBtn) openBtn.addEventListener('click', function () {
            if (drawerOpen()) closeDrawer(); else openDrawer();
        });
        if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
        if (backdrop) backdrop.addEventListener('click', closeDrawer);
        DRAWER_MQ.addEventListener && DRAWER_MQ.addEventListener('change', function (m) {
            if (!m.matches) closeDrawer();
            if (m.matches) body.classList.remove('appnav-rail');
            else if (store(STORE_RAIL) === '1') body.classList.add('appnav-rail');
        });
        // Keep Tab inside the open drawer.
        nav.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab' || !drawerOpen()) return;
            var focusables = Array.prototype.filter.call(
                nav.querySelectorAll('a[href], button:not([disabled]), input'),
                function (el) { return el.offsetParent !== null; });
            if (!focusables.length) return;
            var first = focusables[0], last = focusables[focusables.length - 1];
            if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
        });
    }

    // ---------------------------------------------------------- shortcuts
    var helpModal = null;
    function showHelp() {
        var el = doc.getElementById('shortcutHelp');
        if (!el) return;
        if (window.bootstrap && window.bootstrap.Modal) {
            helpModal = helpModal || new window.bootstrap.Modal(el);
            helpModal.show();
        } else {
            el.classList.add('show');
            el.style.display = 'block';
        }
    }

    function typing(el) {
        if (!el) return false;
        var tag = el.tagName;
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
    }

    function goGroup(key) {
        if (!nav) return false;
        var g = nav.querySelector('.app-nav__group[data-shortcut-key="' + key + '"] .app-nav__group-link');
        if (g) { window.location.href = g.href; return true; }
        return false;
    }

    var pendingG = 0;
    doc.addEventListener('keydown', function (e) {
        if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
        if (e.key === 'Escape' && drawerOpen()) { closeDrawer(); return; }
        if (typing(e.target)) return;
        if (doc.querySelector('.modal.show') && e.key !== '?') return;
        var k = e.key;
        if (pendingG && Date.now() - pendingG < 1500) {
            pendingG = 0;
            if (goGroup(k.toLowerCase())) e.preventDefault();
            return;
        }
        pendingG = 0;
        if (k === '?') { e.preventDefault(); showHelp(); }
        else if (k === '/') {
            var search = doc.querySelector('.nav-search input[name="q"]');
            if (search) {
                e.preventDefault();
                var collapse = doc.getElementById('navbarNav');
                if (collapse && !collapse.classList.contains('show') && search.offsetParent === null
                        && window.bootstrap && window.bootstrap.Collapse) {
                    window.bootstrap.Collapse.getOrCreateInstance(collapse).show();
                    setTimeout(function () { search.focus(); }, 250);
                } else {
                    search.focus();
                }
            }
        } else if (k === 'j' && filter) {
            e.preventDefault();
            if (DRAWER_MQ.matches) openDrawer();
            else if (body.classList.contains('appnav-rail')) setRail(false);
            filter.focus();
            filter.select();
        } else if (k === '[' && nav && !DRAWER_MQ.matches) {
            e.preventDefault();
            setRail(!body.classList.contains('appnav-rail'));
        } else if (k === 'g') {
            pendingG = Date.now();
        }
    });

    // ---------------------------------------------------- busy on submit
    // Runs on window (bubble), i.e. after csp-events' data-confirm handler on
    // document, so a cancelled confirmation never leaves a spinner behind.
    window.addEventListener('submit', function (e) {
        var form = e.target;
        if (e.defaultPrevented || !form || form.hasAttribute('data-no-busy')) return;
        if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
        if (form.getAttribute('target') === '_blank') return;
        var btn = e.submitter || form.querySelector('button[type="submit"], button:not([type])');
        if (form.getAttribute('aria-busy') === 'true') { e.preventDefault(); return; }
        form.setAttribute('aria-busy', 'true');
        if (btn && !btn.hasAttribute('data-no-busy')) {
            // Disable after the browser has captured the submitter's value.
            setTimeout(function () {
                btn.disabled = true;
                btn.classList.add('is-busy');
                if (!btn.querySelector('.app-spinner')) {
                    var s = doc.createElement('span');
                    s.className = 'app-spinner spinner-border spinner-border-sm ms-1';
                    s.setAttribute('aria-hidden', 'true');
                    btn.appendChild(s);
                }
            }, 0);
        }
        // A POST that answers with a download leaves the page in place;
        // give the controls back rather than leaving them stuck.
        setTimeout(clearBusy, 12000);
    }, false);
    function clearBusy() {
        Array.prototype.forEach.call(doc.querySelectorAll('form[aria-busy="true"]'), function (f) {
            f.removeAttribute('aria-busy');
        });
        Array.prototype.forEach.call(doc.querySelectorAll('.is-busy'), function (b) {
            b.disabled = false;
            b.classList.remove('is-busy');
            var s = b.querySelector('.app-spinner');
            if (s) s.remove();
        });
    }
    // Back/forward cache: a restored page must not keep disabled buttons.
    window.addEventListener('pageshow', function (e) { if (e.persisted) clearBusy(); });
})();
