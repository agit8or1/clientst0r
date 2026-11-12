/*
 * Portal request forms (portal/request_form.html) and the staff preview.
 *
 * - Conditional questions: mirrors psa/service_requests.py (visibility,
 *   sections, required_if). The server re-checks everything; hidden
 *   fields are disabled so they are not submitted at all.
 * - Contact / asset lookups: type-ahead against the server's scoped lookup.
 * - Unsaved answers: warns before leaving or switching request type.
 * - Submit: the button is disabled after the first click (the server also
 *   refuses a second ticket for the same form token).
 * - KB suggestions from what the customer types.
 */
(function () {
    'use strict';
    var form = document.getElementById('service-request-form');
    var schemaEl = document.getElementById('sr-schema');
    if (!form || !schemaEl) return;
    var schema = JSON.parse(schemaEl.textContent || '[]');
    var preview = form.getAttribute('data-preview') === '1';
    var byKey = {};
    schema.forEach(function (f) { byKey[f.key] = f; });

    function wrapper(key) { return form.querySelector('.js-sr-field[data-key="' + key + '"]'); }

    function valueOf(f) {
        var w = wrapper(f.key);
        if (!w) return null;
        var name = 'f_' + f.key;
        if (f.type === 'checkbox') {
            var cb = w.querySelector('input[name="' + name + '"]');
            return !!(cb && cb.checked);
        }
        if (f.type === 'multiselect') {
            return Array.prototype.map.call(
                w.querySelectorAll('input[name="' + name + '"]:checked'), function (i) { return i.value; });
        }
        if (f.type === 'radio') {
            var r = w.querySelector('input[name="' + name + '"]:checked');
            return r ? r.value : '';
        }
        if (f.type === 'file') {
            var fi = w.querySelector('input[type="file"]');
            return fi && fi.files && fi.files.length ? ['file'] : [];
        }
        if (f.type === 'contact' || f.type === 'asset') {
            var id = w.querySelector('input[name="' + name + '"]');
            var label = w.querySelector('.js-lookup-input');
            var txt = w.querySelector('input[name="' + name + '__text"]');
            if (id && id.value) return {id: id.value, label: label ? label.value : ''};
            return txt && txt.value ? {text: txt.value} : '';
        }
        if (f.type === 'location') {
            var sel = w.querySelector('select[name="' + name + '"]');
            if (!sel || !sel.value) return '';
            return {id: sel.value, label: sel.options[sel.selectedIndex].text};
        }
        var el = w.querySelector('[name="' + name + '"]');
        return el ? el.value : '';
    }

    function strings(value) {
        if (Array.isArray(value)) {
            var out = [];
            value.forEach(function (v) { out = out.concat(typeof v === 'object' && v ? strings(v) : [String(v)]); });
            return out;
        }
        if (typeof value === 'boolean') return value ? ['true', 'yes'] : ['false', 'no'];
        if (value && typeof value === 'object') {
            return ['id', 'value', 'label', 'text', 'name'].filter(function (k) {
                return value[k] !== undefined && value[k] !== null && value[k] !== '';
            }).map(function (k) { return String(value[k]); });
        }
        if (value === null || value === undefined || value === '') return [];
        return [String(value)];
    }

    function answered(v) {
        return !(v === null || v === undefined || v === '' || v === false ||
                 (Array.isArray(v) && !v.length));
    }

    function matches(c, value) {
        var vals = strings(value);
        var lower = vals.map(function (v) { return v.toLowerCase(); });
        if (!c.op) {
            if (c['in']) return vals.some(function (v) { return c['in'].map(String).indexOf(v) !== -1; });
            var eq = c.equals;
            if (typeof eq === 'boolean') {
                if (typeof value === 'boolean') return value === eq;
                return lower.indexOf(String(eq)) !== -1 || lower.indexOf(eq ? 'yes' : 'no') !== -1;
            }
            return vals.indexOf(String(eq)) !== -1;
        }
        var t = c.value;
        var hit;
        switch (c.op) {
            case 'is_set': return answered(value);
            case 'not_set': return !answered(value);
            case 'equals': case 'not_equals':
                if (typeof t === 'boolean') {
                    hit = (typeof value === 'boolean' || value === '' || value === null)
                        ? (!!value === t) : lower.indexOf(t ? 'yes' : 'no') !== -1;
                } else { hit = vals.indexOf(String(t)) !== -1; }
                return c.op === 'equals' ? hit : !hit;
            case 'in': case 'not_in':
                hit = vals.some(function (v) { return (t || []).map(String).indexOf(v) !== -1; });
                return c.op === 'in' ? hit : !hit;
            case 'contains':
                if (Array.isArray(value)) return vals.indexOf(String(t)) !== -1;
                return vals.join(' ').toLowerCase().indexOf(String(t).toLowerCase()) !== -1;
        }
        return false;
    }

    function holds(cond, values, isVisible) {
        if (!cond) return true;
        function one(c) { return !!c.field && isVisible(c.field) && matches(c, values[c.field]); }
        if (cond.all) return cond.all.every(one);
        if (cond.any) return cond.any.some(one);
        return one(cond);
    }

    function refresh() {
        var values = {};
        schema.forEach(function (f) {
            if (f.type !== 'heading' && f.type !== 'info') values[f.key] = valueOf(f);
        });
        var section = {}, current = null;
        schema.forEach(function (f) {
            if (f.type === 'heading') { current = f.key; section[f.key] = null; }
            else section[f.key] = current;
        });
        var memo = {};
        function vis(key) {
            if (key in memo) return memo[key];
            var f = byKey[key];
            if (!f) return false;
            memo[key] = false;
            var ok = true;
            if (section[key] && !vis(section[key])) ok = false;
            if (ok && f.show_if) ok = holds(f.show_if, values, vis);
            memo[key] = ok;
            return ok;
        }
        schema.forEach(function (f) {
            var show = vis(f.key);
            var w = wrapper(f.key);
            if (!w) return;
            w.hidden = !show;
            w.querySelectorAll('input, select, textarea').forEach(function (el) { el.disabled = !show; });
            var req = !!f.required || (f.required_if ? holds(f.required_if, values, vis) : false);
            var mark = w.querySelector('.js-req-mark');
            if (mark) mark.hidden = !req;
            w.querySelectorAll('input, select, textarea').forEach(function (el) {
                if (el.type !== 'hidden' && el.type !== 'checkbox' && el.type !== 'radio') {
                    el.setAttribute('aria-required', req && show ? 'true' : 'false');
                }
            });
        });
    }
    form.addEventListener('change', refresh);
    form.addEventListener('input', refresh);
    refresh();

    // ---- Lookups ------------------------------------------------------------
    form.querySelectorAll('.js-lookup').forEach(function (box) {
        var url = box.getAttribute('data-lookup-url');
        var input = box.querySelector('.js-lookup-input');
        var hidden = box.querySelector('.js-lookup-id');
        var list = box.querySelector('.js-lookup-results');
        var clear = box.querySelector('.js-lookup-clear');
        if (!input || !hidden || !list) return;
        var timer = null;
        function pick(id, label) {
            hidden.value = id; input.value = label; list.textContent = ''; list.hidden = true;
            input.setAttribute('readonly', 'readonly');
            if (clear) clear.hidden = false;
            refresh();
        }
        if (clear) clear.addEventListener('click', function () {
            hidden.value = ''; input.value = ''; input.removeAttribute('readonly');
            clear.hidden = true; input.focus(); refresh();
        });
        box.querySelectorAll('.js-lookup-own').forEach(function (b) {
            b.addEventListener('click', function () { pick(b.getAttribute('data-id'), b.getAttribute('data-label')); });
        });
        if (preview || !url) return;
        input.addEventListener('input', function () {
            if (input.hasAttribute('readonly')) return;
            clearTimeout(timer);
            var q = input.value.trim();
            if (q.length < 2) { list.hidden = true; return; }
            timer = setTimeout(function () {
                fetch(url + '?q=' + encodeURIComponent(q), {headers: {'X-Requested-With': 'XMLHttpRequest'}})
                    .then(function (r) { return r.ok ? r.json() : {results: []}; })
                    .then(function (data) {
                        list.textContent = '';
                        (data.results || []).forEach(function (row) {
                            var b = document.createElement('button');
                            b.type = 'button';
                            b.className = 'list-group-item list-group-item-action';
                            b.textContent = row.label;
                            b.addEventListener('click', function () { pick(String(row.id), row.label); });
                            list.appendChild(b);
                        });
                        if (!(data.results || []).length) {
                            var none = document.createElement('div');
                            none.className = 'list-group-item small text-muted';
                            none.textContent = 'No match — you can type the name in the box below instead.';
                            list.appendChild(none);
                        }
                        list.hidden = false;
                    })
                    .catch(function () { list.hidden = true; });
            }, 300);
        });
    });

    // ---- Unsaved answers --------------------------------------------------------
    var dirty = false, submitting = false;
    form.addEventListener('input', function () { dirty = true; });
    form.addEventListener('change', function () { dirty = true; });
    window.addEventListener('beforeunload', function (e) {
        if (dirty && !submitting && !preview) { e.preventDefault(); e.returnValue = ''; }
    });
    document.querySelectorAll('.js-leave-guard').forEach(function (a) {
        a.addEventListener('click', function (e) {
            if (dirty && !submitting && !window.confirm('Switching request type discards the answers you have entered. Continue?')) {
                e.preventDefault();
            } else {
                submitting = true;  // no second prompt from beforeunload
            }
        });
    });

    // ---- Submit once -------------------------------------------------------------
    form.addEventListener('submit', function (e) {
        if (preview) { e.preventDefault(); return; }
        if (submitting) { e.preventDefault(); return; }
        submitting = true;
        var btn = form.querySelector('button[type="submit"]');
        if (btn) {
            btn.disabled = true;
            var label = btn.querySelector('.js-submit-label');
            if (label) label.textContent = 'Submitting…';
        }
    });

    // ---- KB suggestions -----------------------------------------------------------
    var kbUrl = form.getAttribute('data-kb-url');
    var list = document.getElementById('kb-suggestions');
    var card = document.getElementById('kb-suggestions-card');
    if (kbUrl && list && card && !preview) {
        var kbTimer = null;
        form.addEventListener('input', function (e) {
            if (!e.target.classList.contains('js-sr-text')) return;
            clearTimeout(kbTimer);
            kbTimer = setTimeout(function () {
                var q = Array.prototype.map.call(form.querySelectorAll('.js-sr-text:not([disabled])'),
                    function (el) { return el.value; }).join(' ').trim();
                if (q.length < 4) return;
                fetch(kbUrl + '?q=' + encodeURIComponent(q.slice(0, 500)), {headers: {'X-Requested-With': 'XMLHttpRequest'}})
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (data) {
                        if (!data || !data.articles || !data.articles.length) return;
                        list.textContent = '';
                        data.articles.forEach(function (a) {
                            var li = document.createElement('li');
                            var link = document.createElement('a');
                            link.href = a.url; link.target = '_blank'; link.rel = 'noopener';
                            link.textContent = a.title;
                            li.appendChild(link);
                            list.appendChild(li);
                        });
                        card.hidden = false;
                    })
                    .catch(function () {});
            }, 600);
        });
    }
})();
