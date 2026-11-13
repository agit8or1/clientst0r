/*
 * Compact dashboard (Phase 67): viewport fit, lazy widgets, refresh, expand,
 * location map and the customize panel. Every widget body comes from
 * /core/dashboard/widget/<key>/, which re-runs the widget's permission
 * check on the server; nothing here decides what a user may see.
 */
(function () {
    'use strict';

    var root = document.getElementById('dash');
    if (!root) return;

    var widgetUrl = root.getAttribute('data-widget-url');
    var saveUrl = root.getAttribute('data-save-url');
    var roleUrl = root.getAttribute('data-role-url');
    var maps = new WeakMap();

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) return meta.content;
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function esc(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
        });
    }

    function urlFor(key) {
        return widgetUrl.replace('WIDGET_KEY', encodeURIComponent(key));
    }

    // ------------------------------------------------------------------
    // Viewport fit: on a desktop-sized window the dashboard takes exactly
    // the height left under the top bar (less the footer), and the grid's
    // panels scroll inside themselves. Smaller windows scroll the page.
    // ------------------------------------------------------------------
    var FIT_MIN_W = 1200, FIT_MIN_H = 700;

    function fit() {
        var wide = window.innerWidth >= FIT_MIN_W && window.innerHeight >= FIT_MIN_H;
        root.classList.toggle('dash-fit', wide);
        if (!wide) {
            root.style.height = '';
            return;
        }
        var top = root.getBoundingClientRect().top + window.scrollY;
        var footer = document.querySelector('.app-main > footer') || document.querySelector('footer');
        var footerH = footer ? footer.getBoundingClientRect().height : 0;
        var h = Math.floor(window.innerHeight - top - footerH - 8);
        root.style.height = Math.max(360, h) + 'px';
        // Whatever the shell adds below (margins, padding) comes off too.
        var over = document.documentElement.scrollHeight - window.innerHeight;
        if (over > 0) root.style.height = Math.max(360, h - over) + 'px';
        invalidateMaps();
    }

    var fitTimer = null;
    function scheduleFit() {
        clearTimeout(fitTimer);
        fitTimer = setTimeout(fit, 120);
    }
    window.addEventListener('resize', scheduleFit);
    document.addEventListener('closed.bs.alert', scheduleFit);
    fit();
    window.addEventListener('load', fit);

    // ------------------------------------------------------------------
    // Widget bodies
    // ------------------------------------------------------------------
    function setState(body, html) {
        body.innerHTML = '<div class="dash-w-state">' + html + '</div>';
    }

    function destroyMaps(scope) {
        scope.querySelectorAll('[data-dash-map]').forEach(function (el) {
            var m = maps.get(el);
            if (m && m.map) m.map.remove();
            maps.delete(el);
        });
    }

    function loadBody(article) {
        var key = article.getAttribute('data-key');
        var body = article.querySelector('.dash-w-body');
        if (!key || !body) return Promise.resolve();
        body.setAttribute('aria-busy', 'true');
        return fetch(urlFor(key), {
            credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (resp) {
            if (resp.status === 404) {
                // The server's check refused it (or there is nothing to show).
                article.remove();
                return null;
            }
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.text();
        }).then(function (html) {
            if (html == null) return;
            destroyMaps(body);
            body.innerHTML = html;
            initWidget(body);
        }).catch(function () {
            setState(body, '<i class="fas fa-triangle-exclamation text-danger" aria-hidden="true"></i> ' +
                'This panel could not be loaded. <button type="button" class="btn btn-link btn-sm p-0" data-dash-retry>Try again</button>');
        }).finally(function () {
            body.removeAttribute('aria-busy');
        });
    }

    function loadKpi(card) {
        var key = card.getAttribute('data-kpi');
        return fetch(urlFor(key), {
            credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (resp) {
            if (resp.status === 404) { card.remove(); return null; }
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.text();
        }).then(function (html) {
            if (html == null) return;
            var tmp = document.createElement('div');
            tmp.innerHTML = html.trim();
            if (tmp.firstElementChild) card.replaceWith(tmp.firstElementChild);
        }).catch(function () { /* keep the old figure */ });
    }

    document.addEventListener('click', function (e) {
        var retry = e.target.closest('[data-dash-retry]');
        if (retry) {
            var art = retry.closest('.dash-w');
            if (art) loadBody(art);
        }
    });

    function initWidget(scope) {
        scope.querySelectorAll('[data-dash-map]').forEach(initMap);
    }

    document.querySelectorAll('.dash-w-body[data-dash-lazy]').forEach(function (body) {
        loadBody(body.closest('.dash-w'));
    });
    initWidget(root);

    var refreshBtn = document.getElementById('dash-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function () {
            var icon = refreshBtn.querySelector('i');
            if (icon) icon.classList.add('fa-spin');
            refreshBtn.disabled = true;
            var jobs = [];
            document.querySelectorAll('.dash-w[data-key]').forEach(function (a) { jobs.push(loadBody(a)); });
            root.querySelectorAll('[data-kpi]').forEach(function (k) { jobs.push(loadKpi(k)); });
            Promise.all(jobs).finally(function () {
                if (icon) icon.classList.remove('fa-spin');
                refreshBtn.disabled = false;
            });
        });
    }

    // ------------------------------------------------------------------
    // Expand a widget to a large overlay (Esc or the backdrop closes it)
    // ------------------------------------------------------------------
    // The shell's main column is its own stacking context, so the overlay,
    // its backdrop and the customize panel live directly under <body>. An
    // expanded widget leaves a placeholder in the grid and goes back to it.
    var backdrop = document.getElementById('dash-backdrop');
    if (backdrop) document.body.appendChild(backdrop);
    var customizePanel = document.getElementById('dash-customize');
    if (customizePanel) document.body.appendChild(customizePanel);
    var expanded = null;
    var placeholder = null;

    function collapse() {
        if (!expanded) return;
        var btn = expanded.querySelector('[data-dash-expand]');
        expanded.classList.remove('is-expanded');
        if (btn) {
            btn.setAttribute('aria-expanded', 'false');
            btn.title = 'Expand';
            btn.querySelector('i').className = 'fas fa-up-right-and-down-left-from-center';
            btn.focus();
        }
        expanded.removeAttribute('role');
        expanded.removeAttribute('aria-modal');
        if (placeholder && placeholder.parentNode) {
            placeholder.parentNode.replaceChild(expanded, placeholder);
        }
        placeholder = null;
        if (btn) btn.focus();
        expanded = null;
        if (backdrop) backdrop.hidden = true;
        document.body.classList.remove('dash-has-expanded');
        invalidateMaps();
    }

    function expand(article) {
        if (expanded) collapse();
        expanded = article;
        var btn = article.querySelector('[data-dash-expand]');
        placeholder = document.createElement('div');
        placeholder.className = 'dash-w dash-w-placeholder';
        placeholder.setAttribute('data-size', article.getAttribute('data-size') || '1');
        placeholder.setAttribute('aria-hidden', 'true');
        article.parentNode.replaceChild(placeholder, article);
        document.body.appendChild(article);
        article.classList.add('is-expanded');
        article.setAttribute('role', 'dialog');
        article.setAttribute('aria-modal', 'true');
        if (btn) {
            btn.setAttribute('aria-expanded', 'true');
            btn.title = 'Collapse';
            btn.querySelector('i').className = 'fas fa-down-left-and-up-right-to-center';
            btn.focus();
        }
        if (backdrop) backdrop.hidden = false;
        document.body.classList.add('dash-has-expanded');
        invalidateMaps();
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-dash-expand]');
        if (!btn) return;
        var art = btn.closest('.dash-w');
        if (art === expanded) collapse(); else expand(art);
    });
    if (backdrop) backdrop.addEventListener('click', collapse);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && expanded) collapse();
    });

    // ------------------------------------------------------------------
    // Location map (same endpoints as the classic dashboard). Its height
    // follows its grid cell; Leaflet is told whenever the cell changes.
    // ------------------------------------------------------------------
    function invalidateMaps() {
        document.querySelectorAll('.dash [data-dash-map], .dash-w.is-expanded [data-dash-map]').forEach(function (el) {
            var m = maps.get(el);
            if (m && m.map) setTimeout(function () { m.map.invalidateSize(); }, 60);
        });
    }

    if (window.ResizeObserver) {
        var ro = new ResizeObserver(function () { invalidateMaps(); });
        root.querySelectorAll('.dash-w').forEach(function (a) { ro.observe(a); });
    }

    function locationColor(status, primary) {
        if (primary) return '#ffc107';
        return {active: '#28a745', inactive: '#6c757d', planned: '#17a2b8', closed: '#dc3545'}[status] || '#007bff';
    }

    function locationIcon(color) {
        return L.divIcon({
            className: 'custom-map-marker',
            html: '<div style="background-color:' + color + ';width:25px;height:25px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid #fff;box-shadow:0 2px 5px rgba(0,0,0,.3);"><div style="transform:rotate(45deg);margin-top:4px;margin-left:7px;"><i class="fas fa-building" style="font-size:10px;color:#fff;"></i></div></div>',
            iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34]
        });
    }

    function deviceIcon(online) {
        var color = online ? '#28a745' : '#dc3545';
        return L.divIcon({
            className: 'custom-map-marker-device',
            html: '<div style="background-color:' + color + ';width:20px;height:20px;border-radius:50%;border:2px solid #fff;box-shadow:0 2px 5px rgba(0,0,0,.3);display:flex;align-items:center;justify-content:center;"><i class="fas fa-laptop" style="font-size:8px;color:#fff;"></i></div>',
            iconSize: [20, 20], iconAnchor: [10, 10], popupAnchor: [0, -10]
        });
    }

    function safeUrl(u) {
        // Popups link only to paths on this site.
        return (typeof u === 'string' && u.charAt(0) === '/' && u.charAt(1) !== '/') ? u : '#';
    }

    function initMap(el) {
        if (maps.has(el) || typeof L === 'undefined') return;
        var canvas = el.querySelector('[data-map-canvas]');
        var message = el.querySelector('[data-map-message]');
        var devBtn = el.querySelector('[data-map-devices]');
        var dragBtn = el.querySelector('[data-map-drag]');
        var satBtn = el.querySelector('[data-map-satellite]');
        var zoom = parseInt(el.getAttribute('data-zoom'), 10) || 4;
        var state = {map: null, deviceMarkers: []};
        maps.set(el, state);

        function showMessage(text) {
            canvas.hidden = true;
            var tools = el.querySelector('.dash-map-tools');
            if (tools) tools.hidden = true;
            message.hidden = false;
            message.querySelector('span').textContent = text;
            if (devBtn) devBtn.hidden = true;
        }

        fetch(el.getAttribute('data-locations-url'), {credentials: 'same-origin'})
            .then(function (r) {
                if (!r.ok) throw new Error(String(r.status));
                return r.json();
            })
            .then(function (data) {
                if (!data.features || !data.features.length) {
                    showMessage('No locations with coordinates. Add locations with addresses to see them on the map.');
                    return;
                }
                var map = state.map = L.map(canvas, {
                    dragging: el.getAttribute('data-dragging') === 'true',
                    scrollWheelZoom: true, touchZoom: true, doubleClickZoom: true,
                    boxZoom: true, zoomControl: true
                }).setView([39.8283, -98.5795], zoom);
                var street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                    maxZoom: 19
                });
                var satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                    attribution: '&copy; <a href="https://www.esri.com/">Esri</a>', maxZoom: 19
                });
                street.addTo(map);
                var markers = [];
                data.features.forEach(function (f) {
                    var c = f.geometry.coordinates, p = f.properties || {};
                    var mk = L.marker([c[1], c[0]], {icon: locationIcon(locationColor(p.status, p.is_primary))}).addTo(map);
                    mk.bindPopup(
                        '<div class="dash-popup"><h6 class="mb-1">' + (p.is_primary ? '<i class="fas fa-star text-warning"></i> ' : '') +
                        '<strong>' + esc(p.name) + '</strong></h6>' +
                        '<p class="mb-1 small">' + esc(p.address) + '</p>' +
                        '<p class="mb-1"><span class="badge bg-secondary">' + esc(p.location_type) + '</span> ' +
                        '<span class="badge bg-' + (p.status === 'active' ? 'success' : 'secondary') + '">' + esc(p.status) + '</span></p>' +
                        '<a href="' + esc(safeUrl(p.url)) + '" class="btn btn-sm btn-primary text-white"><i class="fas fa-eye"></i> View details</a></div>');
                    markers.push(mk);
                });
                var bounds = L.featureGroup(markers).getBounds();
                if (markers.length === 1) map.setView(bounds.getCenter(), zoom);
                else map.fitBounds(bounds.pad(0.1));
                setTimeout(function () { map.invalidateSize(); }, 50);

                if (dragBtn) {
                    dragBtn.hidden = false;
                    var syncDrag = function () {
                        var on = map.dragging.enabled();
                        dragBtn.className = 'btn btn-sm ' + (on ? 'btn-success' : 'btn-outline-secondary');
                        dragBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
                        dragBtn.title = on ? 'Dragging enabled' : 'Dragging disabled';
                        dragBtn.innerHTML = '<i class="fas ' + (on ? 'fa-unlock' : 'fa-lock') + '" aria-hidden="true"></i> <span>' +
                            (on ? 'Dragging enabled' : 'Dragging disabled') + '</span>';
                        canvas.style.cursor = on ? 'grab' : 'default';
                    };
                    syncDrag();
                    dragBtn.addEventListener('click', function () {
                        if (map.dragging.enabled()) map.dragging.disable(); else map.dragging.enable();
                        syncDrag();
                    });
                }
                if (satBtn) {
                    satBtn.hidden = false;
                    var sat = false;
                    satBtn.addEventListener('click', function () {
                        sat = !sat;
                        map.removeLayer(sat ? street : satellite);
                        map.addLayer(sat ? satellite : street);
                        satBtn.className = 'btn btn-sm ' + (sat ? 'btn-info' : 'btn-outline-info');
                        satBtn.setAttribute('aria-pressed', sat ? 'true' : 'false');
                        satBtn.title = sat ? 'Street view' : 'Satellite view';
                        satBtn.innerHTML = '<i class="fas ' + (sat ? 'fa-map' : 'fa-satellite') + '" aria-hidden="true"></i> <span>' +
                            (sat ? 'Street view' : 'Satellite view') + '</span>';
                    });
                }
                if (devBtn) {
                    var showing = false;
                    devBtn.addEventListener('click', function () {
                        showing = !showing;
                        devBtn.className = 'btn btn-sm ' + (showing ? 'btn-primary' : 'btn-outline-primary');
                        devBtn.setAttribute('aria-pressed', showing ? 'true' : 'false');
                        devBtn.querySelector('span').textContent = showing ? 'Hide devices' : 'Show devices';
                        state.deviceMarkers.forEach(function (m) { map.removeLayer(m); });
                        state.deviceMarkers = [];
                        if (!showing) return;
                        fetch(el.getAttribute('data-devices-url'), {credentials: 'same-origin'})
                            .then(function (r) {
                                if (!r.ok) throw new Error(String(r.status));
                                return r.json();
                            })
                            .then(function (d) {
                                (d.features || []).forEach(function (f) {
                                    var c = f.geometry.coordinates, p = f.properties || {};
                                    var last = p.last_seen ? new Date(p.last_seen).toLocaleString() : 'Never';
                                    var mk = L.marker([c[1], c[0]], {icon: deviceIcon(p.is_online)}).addTo(map);
                                    mk.bindPopup(
                                        '<div class="dash-popup"><h6 class="mb-1"><i class="fas fa-laptop text-primary"></i> <strong>' + esc(p.name) + '</strong></h6>' +
                                        '<p class="mb-1 small"><strong>Type:</strong> ' + esc(p.type) + '<br>' +
                                        (p.manufacturer ? '<strong>Manufacturer:</strong> ' + esc(p.manufacturer) + '<br>' : '') +
                                        (p.model ? '<strong>Model:</strong> ' + esc(p.model) + '<br>' : '') +
                                        '<strong>Status:</strong> ' + (p.is_online ? '<span class="badge bg-success">Online</span>' : '<span class="badge bg-danger">Offline</span>') + '<br>' +
                                        '<strong>Last seen:</strong> ' + esc(last) + '</p>' +
                                        '<a href="' + esc(safeUrl(p.url)) + '" class="btn btn-sm btn-primary text-white"><i class="fas fa-eye"></i> View device</a></div>');
                                    state.deviceMarkers.push(mk);
                                });
                            })
                            .catch(function () {
                                if (window.appToast) window.appToast('RMM devices could not be loaded for the map.', 'error');
                            });
                    });
                }
            })
            .catch(function (err) {
                showMessage(String(err && err.message) === '400'
                    ? 'Select an organization to view location map.'
                    : 'Unable to load map. Ensure you have locations with addresses and coordinates.');
            });
    }

    // ------------------------------------------------------------------
    // Customize panel: show/hide, order (drag or arrow buttons), size,
    // density, reset, role defaults. Saved through one JSON endpoint.
    // ------------------------------------------------------------------
    var panel = document.getElementById('dash-customize');
    if (!panel) return;
    var errBox = document.getElementById('dash-c-error');
    var okBox = document.getElementById('dash-c-ok');

    function say(box, text) {
        [errBox, okBox].forEach(function (b) { if (b) b.hidden = true; });
        if (!box) return;
        box.textContent = text;
        box.hidden = false;
    }

    var dragged = null;
    panel.querySelectorAll('[data-dash-list]').forEach(function (list) {
        list.addEventListener('dragstart', function (e) {
            var row = e.target.closest('.dash-c-row');
            if (!row || row.parentNode !== list) return;
            dragged = row;
            row.classList.add('is-dragging');
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', row.getAttribute('data-key')); } catch (x) { /* IE */ }
        });
        list.addEventListener('dragover', function (e) {
            if (!dragged || dragged.parentNode !== list) return;
            e.preventDefault();
            var over = e.target.closest('.dash-c-row');
            if (!over || over === dragged || over.parentNode !== list) return;
            var r = over.getBoundingClientRect();
            list.insertBefore(dragged, (e.clientY - r.top) > r.height / 2 ? over.nextSibling : over);
        });
        list.addEventListener('drop', function (e) { e.preventDefault(); });
        list.addEventListener('dragend', function () {
            if (dragged) dragged.classList.remove('is-dragging');
            dragged = null;
        });
        list.addEventListener('click', function (e) {
            var up = e.target.closest('[data-dash-up]');
            var down = e.target.closest('[data-dash-down]');
            if (!up && !down) return;
            var row = e.target.closest('.dash-c-row');
            if (up && row.previousElementSibling) {
                list.insertBefore(row, row.previousElementSibling);
            } else if (down && row.nextElementSibling) {
                list.insertBefore(row.nextElementSibling, row);
            }
            (up || down).focus();
        });
    });

    panel.querySelectorAll('input[name="dash-density"]').forEach(function (r) {
        r.addEventListener('change', function () {
            root.setAttribute('data-dash-density', r.value);
            document.documentElement.setAttribute('data-density', r.value);
            scheduleFit();
        });
    });

    function keysOf(name) {
        var list = panel.querySelector('[data-dash-list="' + name + '"]');
        return list ? Array.prototype.map.call(list.querySelectorAll('.dash-c-row'), function (r) { return r; }) : [];
    }

    function collectLayout() {
        var order = [], hidden = [], sizes = {};
        ['kpi', 'toolbar', 'grid'].forEach(function (name) {
            keysOf(name).forEach(function (row) {
                var key = row.getAttribute('data-key');
                order.push(key);
                var show = row.querySelector('[data-dash-show]');
                if (show && !show.checked) hidden.push(key);
                var size = row.querySelector('[data-dash-size]');
                if (size) sizes[key] = parseInt(size.value, 10);
            });
        });
        // The 2FA warning isn't customizable; its slot is kept.
        order.unshift('security_2fa');
        return {order: order, hidden: hidden, sizes: sizes};
    }

    function collectQuickActions() {
        return keysOf('qa').filter(function (row) {
            var show = row.querySelector('[data-dash-show]');
            return show && show.checked;
        }).map(function (row) { return row.getAttribute('data-key'); });
    }

    function post(url, payload) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken(),
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json'
            },
            body: JSON.stringify(payload)
        }).then(function (resp) {
            return resp.json().catch(function () { return {}; }).then(function (data) {
                if (!resp.ok || !data.ok) {
                    var msg = (data.errors && data.errors.join(' ')) || data.error ||
                        ('The server refused the change (HTTP ' + resp.status + ').');
                    throw new Error(msg);
                }
                return data;
            });
        });
    }

    function density() {
        var r = panel.querySelector('input[name="dash-density"]:checked');
        return r ? r.value : 'compact';
    }

    var saveBtn = document.getElementById('dash-c-save');
    if (saveBtn) saveBtn.addEventListener('click', function () {
        saveBtn.disabled = true;
        var payload = {layout: collectLayout(), density: density()};
        if (panel.querySelector('[data-dash-list="qa"]')) payload.quick_actions = collectQuickActions();
        post(saveUrl, payload).then(function () {
            say(okBox, 'Saved. Reloading…');
            window.location.reload();
        }).catch(function (err) {
            say(errBox, 'Not saved: ' + err.message);
            saveBtn.disabled = false;
        });
    });

    var resetBtn = document.getElementById('dash-c-reset');
    if (resetBtn) resetBtn.addEventListener('click', function () {
        resetBtn.disabled = true;
        post(saveUrl, {action: 'reset'}).then(function () {
            say(okBox, 'Layout reset. Reloading…');
            window.location.reload();
        }).catch(function (err) {
            say(errBox, 'Not reset: ' + err.message);
            resetBtn.disabled = false;
        });
    });

    var presetSel = document.getElementById('dash-c-preset');
    var roleSave = document.getElementById('dash-c-role-save');
    var roleClear = document.getElementById('dash-c-role-clear');
    if (roleUrl && roleSave) roleSave.addEventListener('click', function () {
        var label = presetSel.options[presetSel.selectedIndex].text;
        post(roleUrl, {preset: presetSel.value, layout: collectLayout()}).then(function () {
            say(okBox, 'Saved as the default for ' + label + '.');
        }).catch(function (err) { say(errBox, 'Not saved: ' + err.message); });
    });
    if (roleUrl && roleClear) roleClear.addEventListener('click', function () {
        var label = presetSel.options[presetSel.selectedIndex].text;
        post(roleUrl, {preset: presetSel.value, action: 'clear'}).then(function () {
            say(okBox, 'Default for ' + label + ' cleared; the built-in layout applies.');
        }).catch(function (err) { say(errBox, 'Not cleared: ' + err.message); });
    });
})();
