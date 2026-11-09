/*
 * Navbar client switcher (templates/core/_client_switcher.html).
 *
 * Search box: queries core:client_switcher_search (JSON, authorized clients
 * only, bounded) and renders the matches as dropdown items. Without
 * JavaScript the form submits to the same URL and gets a results page.
 *
 * Keyboard: the menu opens with focus in the search box (on devices with a
 * fine pointer); ArrowDown moves into the list, Bootstrap handles arrows
 * between items, ArrowUp on the first item returns to the search box, Enter
 * in the box opens the first match, Escape closes the menu.
 */
(function () {
    'use strict';

    function init(menu) {
        if (menu.dataset.csReady) return;
        menu.dataset.csReady = '1';

        var input = menu.querySelector('#clientSwitcherSearch');
        var results = menu.querySelector('#clientSwitcherResults');
        var status = menu.querySelector('#clientSwitcherStatus');
        var defaults = menu.querySelector('[data-cs-default]');
        var toggle = menu.parentElement.querySelector('[data-bs-toggle="dropdown"]');
        var url = menu.getAttribute('data-search-url');
        var timer = null;
        var controller = null;
        var lastQuery = null;

        function visibleItems() {
            return Array.prototype.filter.call(
                menu.querySelectorAll('.dropdown-item'),
                function (el) { return el.offsetParent !== null; }
            );
        }

        function setStatus(text) { if (status) status.textContent = text || ''; }

        function showDefaults(show) {
            if (defaults) defaults.hidden = !show;
            if (results) results.hidden = show;
        }

        function render(data) {
            results.textContent = '';
            var rows = data.results || [];
            rows.forEach(function (r) {
                var li = document.createElement('li');
                var a = document.createElement('a');
                a.className = 'dropdown-item d-flex align-items-center gap-2' + (r.active ? ' fw-semibold' : '');
                a.href = r.url;
                a.title = r.name;
                if (r.active) a.setAttribute('aria-current', 'true');
                var icon = document.createElement('i');
                icon.className = 'fas flex-shrink-0 ' + (r.active ? 'fa-check-circle text-success' : 'fa-building text-muted');
                icon.setAttribute('aria-hidden', 'true');
                var name = document.createElement('span');
                name.className = 'text-truncate';
                name.textContent = r.name;
                a.appendChild(icon);
                a.appendChild(name);
                if (r.active) {
                    var badge = document.createElement('span');
                    badge.className = 'badge bg-warning text-dark ms-auto';
                    badge.textContent = menu.getAttribute('data-i18n-active') || 'Active';
                    a.appendChild(badge);
                }
                li.appendChild(a);
                results.appendChild(li);
            });
            if (!rows.length) {
                setStatus(menu.getAttribute('data-i18n-none'));
            } else if (data.truncated) {
                setStatus(menu.getAttribute('data-i18n-more'));
            } else {
                setStatus((menu.getAttribute('data-i18n-count') || '__N__').replace('__N__', rows.length));
            }
            showDefaults(false);
        }

        function search(q) {
            if (q === lastQuery) return;
            lastQuery = q;
            if (controller) controller.abort();
            if (!q) {
                results.textContent = '';
                setStatus('');
                showDefaults(true);
                return;
            }
            controller = window.AbortController ? new AbortController() : null;
            fetch(url + '?format=json&q=' + encodeURIComponent(q), {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                signal: controller ? controller.signal : undefined
            }).then(function (resp) {
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return resp.json();
            }).then(function (data) {
                if (data.query !== undefined && data.query !== q) return;
                render(data);
            }).catch(function (err) {
                if (err && err.name === 'AbortError') return;
                lastQuery = null;
                results.textContent = '';
                showDefaults(false);
                setStatus(menu.getAttribute('data-i18n-error'));
            });
        }

        if (input) {
            input.addEventListener('input', function () {
                clearTimeout(timer);
                var q = input.value.trim();
                timer = setTimeout(function () { search(q); }, 150);
            });
            input.addEventListener('keydown', function (ev) {
                if (ev.key === 'ArrowDown') {
                    var items = visibleItems();
                    if (items.length) {
                        ev.preventDefault();
                        items[0].focus();
                    }
                } else if (ev.key === 'Enter') {
                    // Open the first match when there is one; otherwise let
                    // the form submit to the full results page.
                    var first = results && !results.hidden && results.querySelector('.dropdown-item');
                    if (first && input.value.trim() === lastQuery) {
                        ev.preventDefault();
                        window.location.href = first.href;
                    }
                }
            });
        }

        // ArrowUp on the first item goes back to the search box. Runs before
        // Bootstrap's document-level keydown handler.
        menu.addEventListener('keydown', function (ev) {
            if (ev.key !== 'ArrowUp' || !input || ev.target === input) return;
            var items = visibleItems();
            if (items.length && items[0] === ev.target) {
                ev.preventDefault();
                ev.stopPropagation();
                input.focus();
            }
        });

        if (toggle) {
            toggle.addEventListener('shown.bs.dropdown', function () {
                if (!input) return;
                // Don't pop the on-screen keyboard on touch devices.
                var fine = window.matchMedia && window.matchMedia('(pointer: fine)').matches;
                if (fine) input.focus();
            });
            toggle.addEventListener('hidden.bs.dropdown', function () {
                if (!input || !input.value) return;
                input.value = '';
                search('');
            });
        }
    }

    function boot() {
        document.querySelectorAll('[data-client-switcher]').forEach(init);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
