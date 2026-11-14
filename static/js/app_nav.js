/*
 * Technician shell behaviour (loaded by base.html, deferred, CSP-safe).
 *
 *  - Sidebar (#appNav, core/_primary_nav.html): filter-as-you-type (sidebar
 *    links plus the filter-only pages in .app-nav__extra), section
 *    expand/collapse buttons that never navigate (only the current section
 *    starts open), the icon rail (remembered; the default from 768px to
 *    1199px) whose section buttons open accessible flyout menus with
 *    tooltips, the current page scrolled into view, and a drawer below
 *    768px with focus moved in and restored on close.
 *  - Section tab strip (core/_section_tabs.html): pills that do not fit move
 *    into its "More" menu, so the row never wraps.
 *  - Keyboard shortcuts with a ? help overlay (#shortcutHelp). Ignored while
 *    typing in a field, in a contenteditable, or with Ctrl/Alt/Meta held.
 *  - window.appToast(message, kind): visible feedback for actions that used
 *    to fail with only a console message.
 *  - Sidebar height: the part of the window below the top bar, so a short
 *    page fits without scrolling (a plain 100vh sidebar under the 71px bar
 *    made every page at least that much taller than the window).
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
    // Phones get the drawer; tablets default to the icon rail.
    var DRAWER_MQ = window.matchMedia('(max-width: 767.98px)');
    var TABLET_MQ = window.matchMedia('(min-width: 768px) and (max-width: 1199.98px)');

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
    var navBody = nav && nav.querySelector('.app-nav__body');
    var lastFocus = null;
    var flyout = null;   // {group, btn, list} while a rail flyout is open
    var tip = null;

    function each(list, fn) { Array.prototype.forEach.call(list, fn); }
    function isRail() { return body.classList.contains('appnav-rail') && !DRAWER_MQ.matches; }

    // Rail preference: '1' rail, '0' expanded, nothing = the default for
    // the width (rail on a tablet, expanded on a desktop).
    function railPref() {
        var v = store(STORE_RAIL);
        return v === '1' ? true : (v === '0' ? false : null);
    }
    function railDefault() {
        var p = railPref();
        return p === null ? TABLET_MQ.matches : p;
    }

    function sectionGroups() {
        return nav ? Array.prototype.filter.call(nav.querySelectorAll('.app-nav__group'), function (g) {
            return !!g.querySelector('.app-nav__group-btn');
        }) : [];
    }
    function parts(group) {
        return { btn: group.querySelector('.app-nav__group-btn'), list: group.querySelector('.app-nav__entries') };
    }

    // Expanded sidebar: a section's button shows / hides its pages in place.
    function setOpen(group, open) {
        var p = parts(group);
        if (!p.list) return;
        group.setAttribute('data-open', open ? '1' : '0');
        p.list.hidden = !open;
        if (!isRail()) p.btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    function syncButtons() {
        sectionGroups().forEach(function (g) {
            var p = parts(g);
            var open = !isRail() && g.getAttribute('data-open') === '1';
            p.btn.setAttribute('aria-expanded', open || (flyout && flyout.group === g) ? 'true' : 'false');
        });
    }

    function setRail(on, remember) {
        closeFlyout(false);
        body.classList.toggle('appnav-rail', on);
        if (railBtn) {
            railBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            var label = railBtn.getAttribute(on ? 'data-label-expand' : 'data-label-collapse');
            railBtn.setAttribute('aria-label', label);
            railBtn.setAttribute('title', label + ' ( [ )');
        }
        if (remember) store(STORE_RAIL, on ? '1' : '0');
        syncButtons();
        hideTip();
    }

    // ---- icon-rail flyouts: a section's pages beside the rail ----------
    function flyoutLinks() {
        return flyout ? Array.prototype.slice.call(flyout.list.querySelectorAll('a[href]')).filter(function (a) {
            return a.offsetParent !== null;
        }) : [];
    }
    function placeFlyout() {
        if (!flyout) return;
        var r = flyout.btn.getBoundingClientRect();
        var edge = nav.getBoundingClientRect().right;
        var list = flyout.list;
        list.style.left = Math.round(edge + 4) + 'px';
        list.style.maxHeight = (window.innerHeight - 16) + 'px';
        var top = r.top;
        var h = list.offsetHeight;
        if (top + h > window.innerHeight - 8) top = Math.max(8, window.innerHeight - 8 - h);
        list.style.top = Math.round(top) + 'px';
    }
    function openFlyout(group, focus) {
        closeFlyout(false);
        hideTip();
        var p = parts(group);
        if (!p.list) return;
        flyout = { group: group, btn: p.btn, list: p.list };
        p.list.classList.add('is-flyout');
        p.list.hidden = false;
        p.btn.setAttribute('aria-expanded', 'true');
        placeFlyout();
        if (focus) {
            var links = flyoutLinks();
            var target = focus === 'last' ? links[links.length - 1] : links[0];
            if (target) target.focus();
        }
    }
    function closeFlyout(returnFocus) {
        if (!flyout) return;
        var f = flyout;
        flyout = null;
        f.list.classList.remove('is-flyout');
        f.list.style.top = f.list.style.left = f.list.style.maxHeight = '';
        f.list.hidden = f.group.getAttribute('data-open') !== '1';
        f.btn.setAttribute('aria-expanded', 'false');
        if (returnFocus) f.btn.focus();
    }

    // ---- tooltips for the rail's icons (hover and keyboard focus) ------
    function showTip(el) {
        if (!isRail() || !el || (flyout && flyout.btn === el)) return;
        var text = el.getAttribute('data-tip');
        if (!text) return;
        if (!tip) {
            tip = doc.createElement('div');
            tip.className = 'app-nav__tip';
            tip.setAttribute('aria-hidden', 'true');  // the control's own name is its accessible name
            body.appendChild(tip);
        }
        tip.textContent = text;
        tip.hidden = false;
        var r = el.getBoundingClientRect();
        tip.style.left = Math.round(nav.getBoundingClientRect().right + 6) + 'px';
        tip.style.top = Math.round(r.top + r.height / 2 - tip.offsetHeight / 2) + 'px';
    }
    function hideTip() { if (tip) tip.hidden = true; }

    // ---- drawer (phones) -----------------------------------------------
    function drawerOpen() { return body.classList.contains('appnav-open'); }

    function openDrawer() {
        if (!nav) return;
        lastFocus = doc.activeElement;
        body.classList.add('appnav-open');
        if (backdrop) backdrop.hidden = false;
        if (openBtn) openBtn.setAttribute('aria-expanded', 'true');
        // Focus once the drawer is laid out (it is visibility:hidden until the
        // class applies), and again after the slide-in in case a late click
        // or transition stole it.
        var target = filter || nav;
        target.focus();
        window.requestAnimationFrame(function () { if (drawerOpen()) target.focus(); });
        window.setTimeout(function () {
            if (drawerOpen() && !nav.contains(doc.activeElement)) target.focus();
        }, 250);
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
            nav.querySelectorAll('.app-nav__group-btn, .app-nav__link, .app-nav__sublink, .app-nav__xlink, .app-nav__pinlink'),
            function (a) { return a.offsetParent !== null; });
    }

    // ---- filter ----------------------------------------------------------
    function norm(s) { return (s || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
    function hits(el, tokens) {
        var text = norm(el.getAttribute('data-filter'));
        return tokens.every(function (t) { return text.indexOf(t) !== -1; });
    }

    function applyFilter() {
        if (!nav || !filter) return;
        var q = norm(filter.value);
        var tokens = q ? q.split(' ') : [];
        var matches = 0;
        nav.classList.toggle('is-filtering', tokens.length > 0);
        sectionGroups().forEach(function (group) {
            var groupHit = false;
            each(group.querySelectorAll('.app-nav__entry'), function (entry) {
                var entryHit = tokens.length > 0 && hits(entry, tokens);
                var sub = entry.querySelector('.app-nav__sub');
                var subHit = false;
                if (sub) {
                    each(sub.children, function (li) {
                        var hit = tokens.length > 0 && hits(li, tokens);
                        li.hidden = tokens.length > 0 && !hit && !entryHit;
                        var subLink = li.querySelector('a');
                        if (subLink) subLink.classList.toggle('is-match', hit);
                        if (hit) { subHit = true; matches++; }
                    });
                    sub.hidden = tokens.length ? !(subHit || entryHit) : !entry.querySelector('.app-nav__link.active');
                }
                var show = !tokens.length || entryHit || subHit;
                entry.hidden = !show;
                var link = entry.querySelector('.app-nav__link, .app-nav__pinlink');
                if (link) link.classList.toggle('is-match', entryHit);
                if (entryHit) matches++;
                if (show && tokens.length) groupHit = true;
            });
            var list = parts(group).list;
            if (tokens.length) {
                group.hidden = !groupHit;
                if (list) list.hidden = !groupHit;
            } else {
                group.hidden = false;
                if (list) list.hidden = group.getAttribute('data-open') !== '1';
            }
        });
        // Pages that are not sidebar links: tabs, Configure pages, settings.
        var extra = nav.querySelector('.app-nav__extra');
        if (extra) {
            var extraHits = 0;
            each(extra.children, function (li) {
                var hit = tokens.length > 0 && hits(li, tokens);
                li.hidden = !hit;
                var a = li.querySelector('a');
                if (a) a.classList.toggle('is-match', hit);
                if (hit && extraHits < 12) { extraHits++; } else if (hit) { li.hidden = true; }
            });
            extra.hidden = !extraHits;
            matches += extraHits;
        }
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

    function revealCurrent() {
        // The current page's link, scrolled into view inside the sidebar
        // (never the window): its sub-link, its entry, or in the rail its
        // section's button.
        if (!navBody) return;
        var cur = isRail()
            ? navBody.querySelector('.app-nav__group.is-active .app-nav__group-btn')
            : navBody.querySelector('.app-nav__sublink.active') || navBody.querySelector('.app-nav__link.active');
        if (!cur || cur.offsetParent === null) return;
        var br = navBody.getBoundingClientRect();
        var cr = cur.getBoundingClientRect();
        if (cr.top < br.top || cr.bottom > br.bottom) {
            navBody.scrollTop += cr.top - br.top - Math.max(0, (br.height - cr.height) / 3);
        }
    }

    if (nav) {
        // The server opens only the current section; mark it for the
        // filter and the rail. Older builds remembered several open
        // sections; that list is dropped.
        store(STORE_OPEN, null);
        sectionGroups().forEach(function (g) {
            g.setAttribute('data-open', parts(g).list && !parts(g).list.hidden ? '1' : '0');
        });
        if (!DRAWER_MQ.matches) setRail(railDefault(), false);
        syncButtons();
        revealCurrent();

        nav.addEventListener('click', function (e) {
            var btn = e.target.closest('.app-nav__group-btn');
            if (btn) {
                var group = btn.closest('.app-nav__group');
                if (isRail()) {
                    if (flyout && flyout.group === group) closeFlyout(false);
                    else openFlyout(group, e.detail === 0 ? 'first' : null);  // keyboard click: focus in
                } else {
                    setOpen(group, group.getAttribute('data-open') !== '1');
                }
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
                        return a.tagName === 'A';
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

        nav.addEventListener('keydown', function (e) {
            if (e.target === filter) return;
            // Inside an open rail flyout: arrows move, Escape closes.
            if (flyout && flyout.list.contains(e.target)) {
                var fl = flyoutLinks();
                var fi = fl.indexOf(e.target);
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    var n = fl[(fi + (e.key === 'ArrowDown' ? 1 : -1) + fl.length) % fl.length];
                    if (n) n.focus();
                } else if (e.key === 'Home' || e.key === 'End') {
                    e.preventDefault();
                    (e.key === 'Home' ? fl[0] : fl[fl.length - 1]).focus();
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    closeFlyout(true);
                }
                return;
            }
            var btn = e.target.closest && e.target.closest('.app-nav__group-btn');
            if (btn && isRail() && (e.key === 'ArrowRight' || e.key === 'ArrowDown' && e.altKey)) {
                e.preventDefault();
                openFlyout(btn.closest('.app-nav__group'), 'first');
                return;
            }
            if (btn && e.key === 'Escape' && flyout && flyout.btn === btn) {
                e.preventDefault();
                closeFlyout(true);
                return;
            }
            // Arrow keys move between visible links and section buttons.
            if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
            var links = visibleLinks();
            var i = links.indexOf(e.target);
            if (i === -1) return;
            e.preventDefault();
            var next = links[i + (e.key === 'ArrowDown' ? 1 : -1)];
            if (next) next.focus();
            else if (e.key === 'ArrowUp' && filter && filter.offsetParent !== null) filter.focus();
        });

        // A flyout closes when focus or a click leaves it, and on scroll /
        // resize (it is positioned against the rail).
        nav.addEventListener('focusout', function (e) {
            if (!flyout) return;
            var to = e.relatedTarget;
            if (to && (flyout.list.contains(to) || to === flyout.btn)) return;
            if (!to) return;  // focus went to the page itself (e.g. a click elsewhere)
            closeFlyout(false);
        });
        doc.addEventListener('click', function (e) {
            if (flyout && !flyout.list.contains(e.target) && !flyout.btn.contains(e.target)) closeFlyout(false);
        });
        if (navBody) navBody.addEventListener('scroll', function () { closeFlyout(false); hideTip(); }, { passive: true });
        window.addEventListener('resize', function () { closeFlyout(false); hideTip(); });

        nav.addEventListener('mouseover', function (e) {
            var el = e.target.closest && e.target.closest('[data-tip]');
            if (el && nav.contains(el)) showTip(el); else hideTip();
        });
        nav.addEventListener('mouseleave', hideTip);
        nav.addEventListener('focusin', function (e) {
            var el = e.target.closest && e.target.closest('[data-tip]');
            if (el) showTip(el); else hideTip();
        });

        if (railBtn) railBtn.addEventListener('click', function () {
            setRail(!body.classList.contains('appnav-rail'), true);
        });
        if (openBtn) openBtn.addEventListener('click', function () {
            if (drawerOpen()) closeDrawer(); else openDrawer();
        });
        if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
        if (backdrop) backdrop.addEventListener('click', closeDrawer);
        var onWidth = function () {
            if (!DRAWER_MQ.matches) closeDrawer();
            if (DRAWER_MQ.matches) { closeFlyout(false); body.classList.remove('appnav-rail'); syncButtons(); }
            else setRail(railDefault(), false);
        };
        if (DRAWER_MQ.addEventListener) {
            DRAWER_MQ.addEventListener('change', onWidth);
            TABLET_MQ.addEventListener('change', onWidth);
        }
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

    // ------------------------------------------------- section tab strip
    // The pills never wrap: when the row is too narrow, the last pills (never
    // the current page's) move into the strip's "More" menu, and come back
    // when there is room again.
    function fitStrip(strip) {
        var list = strip.querySelector('.section-tabs__list');
        var moreLi = list && list.querySelector('.section-tabs__more');
        var menu = moreLi && moreLi.querySelector('.dropdown-menu');
        if (!menu) return;
        each(menu.querySelectorAll('li[data-moved]'), function (li) {
            li.removeAttribute('data-moved');
            li.classList.add('nav-item');
            var a = li.querySelector('a');
            if (a) { a.classList.remove('dropdown-item'); a.classList.add('nav-link'); }
            list.insertBefore(li, moreLi);
        });
        moreLi.hidden = !menu.children.length;
        var guard = 40;
        while (list.scrollWidth > list.clientWidth + 1 && guard--) {
            var pills = Array.prototype.filter.call(list.children, function (li) {
                return li !== moreLi && !li.querySelector('.active');
            });
            var last = pills[pills.length - 1];
            if (!last) break;
            last.setAttribute('data-moved', '1');
            last.classList.remove('nav-item');
            var link = last.querySelector('a');
            if (link) { link.classList.remove('nav-link'); link.classList.add('dropdown-item'); }
            menu.insertBefore(last, menu.firstChild);
            moreLi.hidden = false;
        }
    }
    var strips = doc.querySelectorAll('[data-section-tabs]');
    if (strips.length) {
        var fitAll = function () { each(strips, fitStrip); };
        fitAll();
        var fitQueued = false;
        window.addEventListener('resize', function () {
            if (!fitQueued) {
                fitQueued = true;
                window.requestAnimationFrame(function () { fitQueued = false; fitAll(); });
            }
        });
        if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(fitAll);
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
        // A group ("g s") or an entry ("g w", "g a": the first visible one).
        var holder = nav.querySelector('[data-shortcut-key="' + key + '"]');
        if (!holder) return false;
        var link = holder.querySelector('.app-nav__link');
        var href = holder.getAttribute('data-href') || (link && link.href);
        if (href) { window.location.href = href; return true; }
        return false;
    }

    var pendingG = 0;
    doc.addEventListener('keydown', function (e) {
        if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
        if (e.key === 'Escape' && flyout) { closeFlyout(true); return; }
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
            else if (body.classList.contains('appnav-rail')) setRail(false, false);
            filter.focus();
            filter.select();
        } else if (k === '[' && nav && !DRAWER_MQ.matches) {
            e.preventDefault();
            setRail(!body.classList.contains('appnav-rail'), true);
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

    // ------------------------------------------------------ sidebar height
    var nav = doc.getElementById('appNav');
    var topBar = doc.querySelector('body > nav.navbar, nav.navbar');
    if (nav && topBar) {
        var queued = false;
        var sizeNav = function () {
            queued = false;
            var below = Math.max(0, topBar.getBoundingClientRect().bottom);
            doc.documentElement.style.setProperty('--app-nav-h', (window.innerHeight - below) + 'px');
        };
        var queue = function () {
            if (!queued) { queued = true; window.requestAnimationFrame(sizeNav); }
        };
        sizeNav();
        window.addEventListener('scroll', queue, { passive: true });
        window.addEventListener('resize', queue);
    }
})();
