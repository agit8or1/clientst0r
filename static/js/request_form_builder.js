/*
 * Staff form builder for portal request types (psa/request_types/builder.html).
 *
 * Edits a list of field definitions (psa/service_requests.py describes the
 * shape) and keeps the hidden `schema_json` input in step. The server
 * re-validates everything on save; the checks here are only early hints.
 *
 * Reordering: drag a field by its handle, or use the Move up / Move down
 * buttons (keyboard and screen-reader friendly). Field IDs are stable: they
 * are generated once from the first label and do not follow later label
 * edits; IDs already in the published form are locked.
 */
(function () {
    'use strict';
    var root = document.getElementById('rb-builder');
    if (!root) return;
    var out = document.getElementById('rb-schema-json');
    var list = document.getElementById('rb-fields');
    var hint = document.getElementById('rb-hints');
    var live = document.getElementById('rb-live');
    var types = JSON.parse(document.getElementById('rb-types').textContent);
    var ops = JSON.parse(document.getElementById('rb-ops').textContent);
    var locked = JSON.parse(document.getElementById('rb-locked').textContent || '[]');
    var fields;
    try { fields = JSON.parse(out.value || '[]'); } catch (e) { fields = []; }
    if (!Array.isArray(fields)) fields = [];
    var typeLabel = {};
    types.forEach(function (t) { typeLabel[t[0]] = t[1]; });
    var open = {};
    var KEY_RE = /^[a-z][a-z0-9_]{0,49}$/;
    var CHOICE = ['select', 'multiselect', 'radio'];
    var DISPLAY = ['heading', 'info'];
    var dirty = false;

    function el(tag, attrs, text) {
        var e = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === 'class') e.className = attrs[k];
            else if (attrs[k] !== false && attrs[k] !== undefined) e.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
        });
        if (text !== undefined) e.textContent = text;
        return e;
    }
    function announce(msg) { if (live) live.textContent = msg; }

    function slugKey(label) {
        var k = (label || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
        if (!/^[a-z]/.test(k)) k = 'field_' + k;
        k = k.slice(0, 40) || 'field';
        var base = k, n = 2;
        while (fields.some(function (f) { return f.key === k; })) { k = base + '_' + n; n++; }
        return k;
    }

    function optionsText(f) {
        return (f.options || []).map(function (o) {
            if (typeof o === 'object') return o.value === o.label ? o.value : o.value + ' | ' + o.label;
            return String(o);
        }).join('\n');
    }
    function parseOptions(text) {
        var lines = text.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
        var asPairs = lines.some(function (l) { return l.indexOf('|') !== -1; });
        return lines.map(function (l) {
            if (!asPairs) return l;
            var i = l.indexOf('|');
            if (i === -1) return {value: l, label: l};
            var v = l.slice(0, i).trim(), lab = l.slice(i + 1).trim();
            return {value: v || lab, label: lab || v};
        });
    }
    function optionPairs(f) {
        return (f.options || []).map(function (o) {
            return typeof o === 'object' ? [String(o.value), String(o.label)] : [String(o), String(o)];
        });
    }

    function sync() {
        out.value = JSON.stringify(fields);
        var raw = document.getElementById('rb-raw');
        if (raw && document.activeElement !== raw) raw.value = JSON.stringify(fields, null, 1);
        var hints = [], seen = {}, before = {};
        fields.forEach(function (f, i) {
            if (!KEY_RE.test(f.key || '')) hints.push('Question ' + (i + 1) + ': the ID must start with a letter and use lowercase letters, digits and _.');
            if (seen[f.key]) hints.push('ID "' + f.key + '" is used twice.');
            seen[f.key] = true;
            if (!f.label && f.type !== 'info') hints.push('Question ' + (i + 1) + ' needs a label.');
            if (CHOICE.indexOf(f.type) !== -1 && !(f.options || []).length) hints.push('"' + (f.label || f.key) + '" needs options.');
            ['show_if', 'required_if'].forEach(function (attr) {
                condParts(f[attr]).forEach(function (c) {
                    if (c.field && !before[c.field]) hints.push('"' + (f.label || f.key) + '" depends on "' + c.field + '", which must come earlier in the form.');
                });
            });
            before[f.key] = true;
        });
        hint.textContent = '';
        hints.forEach(function (h) { hint.appendChild(el('li', {}, h)); });
        hint.parentNode.hidden = !hints.length;
    }

    function condParts(c) {
        if (!c) return [];
        if (c.all) return c.all;
        if (c.any) return c.any;
        return [c];
    }
    function toNew(c) {   // legacy {field, equals|in} → {field, op, value}
        if (c.op) return c;
        if (c['in']) return {field: c.field, op: 'in', value: c['in']};
        return {field: c.field, op: 'equals', value: c.equals};
    }

    function move(i, j) {
        if (j < 0 || j >= fields.length) return;
        var f = fields.splice(i, 1)[0];
        fields.splice(j, 0, f);
        dirty = true;
        sync(); render();
        announce('Moved "' + (f.label || f.key) + '" to position ' + (j + 1) + ' of ' + fields.length + '.');
        var btn = list.querySelector('[data-index="' + j + '"] .rb-move-' + (j > i ? 'down' : 'up'));
        if (btn && !btn.disabled) btn.focus();
    }

    function conditionEditor(f, i, attr, title) {
        var box = el('div', {'class': 'border rounded p-2 mt-2'});
        var parts = condParts(f[attr]).map(toNew);
        var combo = f[attr] && f[attr].any ? 'any' : 'all';
        var head = el('div', {'class': 'd-flex flex-wrap align-items-center gap-2'});
        head.appendChild(el('span', {'class': 'small fw-semibold'}, title));
        var earlier = fields.slice(0, i).filter(function (p) { return DISPLAY.indexOf(p.type) === -1 && p.type !== 'file'; });
        if (parts.length > 1) {
            var comboSel = el('select', {'class': 'form-select form-select-sm w-auto', 'aria-label': 'Combine conditions'});
            [['all', 'all of these are true'], ['any', 'any of these is true']].forEach(function (o) {
                var op = el('option', {value: o[0]}, o[1]); if (o[0] === combo) op.selected = true; comboSel.appendChild(op);
            });
            comboSel.addEventListener('change', function () { combo = comboSel.value; save(); });
            head.appendChild(comboSel);
        }
        box.appendChild(head);
        function save() {
            var clean = parts.filter(function (c) { return c.field; });
            if (!clean.length) delete f[attr];
            else if (clean.length === 1) f[attr] = clean[0];
            else { f[attr] = {}; f[attr][combo] = clean; }
            dirty = true; sync();
        }
        parts.forEach(function (c, ci) {
            var row = el('div', {'class': 'row g-1 mt-1 align-items-center'});
            var fs = el('select', {'class': 'form-select form-select-sm', 'aria-label': 'Question'});
            fs.appendChild(el('option', {value: ''}, '— question —'));
            earlier.forEach(function (p) {
                var o = el('option', {value: p.key}, (p.label || p.key)); if (p.key === c.field) o.selected = true; fs.appendChild(o);
            });
            var os = el('select', {'class': 'form-select form-select-sm', 'aria-label': 'Comparison'});
            ops.forEach(function (o) { var op = el('option', {value: o[0]}, o[1]); if (o[0] === (c.op || 'equals')) op.selected = true; os.appendChild(op); });
            var ctrl = fields.filter(function (p) { return p.key === c.field; })[0];
            var vcol = el('div', {'class': 'col-md-4'});
            var needsValue = ['is_set', 'not_set'].indexOf(c.op) === -1;
            var vin;
            if (ctrl && ctrl.type === 'checkbox') {
                vin = el('select', {'class': 'form-select form-select-sm', 'aria-label': 'Value'});
                [['true', 'ticked'], ['false', 'not ticked']].forEach(function (o) {
                    var op = el('option', {value: o[0]}, o[1]); if (String(c.value) === o[0]) op.selected = true; vin.appendChild(op);
                });
            } else if (ctrl && CHOICE.indexOf(ctrl.type) !== -1 && ['in', 'not_in'].indexOf(c.op) === -1) {
                vin = el('select', {'class': 'form-select form-select-sm', 'aria-label': 'Value'});
                optionPairs(ctrl).forEach(function (p) { var op = el('option', {value: p[0]}, p[1]); if (String(c.value) === p[0]) op.selected = true; vin.appendChild(op); });
            } else {
                vin = el('input', {'class': 'form-control form-control-sm', type: 'text', 'aria-label': 'Value',
                                   placeholder: ['in', 'not_in'].indexOf(c.op) !== -1 ? 'values, comma-separated' : 'value'});
                vin.value = Array.isArray(c.value) ? c.value.join(', ') : (c.value === undefined ? '' : String(c.value));
            }
            vin.hidden = !needsValue;
            function update() {
                c.field = fs.value; c.op = os.value;
                if (['is_set', 'not_set'].indexOf(c.op) !== -1) delete c.value;
                else if (ctrl && ctrl.type === 'checkbox') c.value = vin.value === 'true';
                else if (['in', 'not_in'].indexOf(c.op) !== -1) c.value = String(vin.value).split(',').map(function (s) { return s.trim(); }).filter(Boolean);
                else c.value = vin.value;
                save();
            }
            fs.addEventListener('change', function () { update(); render(); });
            os.addEventListener('change', function () { update(); render(); });
            vin.addEventListener('change', update);
            vin.addEventListener('input', update);
            var c1 = el('div', {'class': 'col-md-4'}); c1.appendChild(fs);
            var c2 = el('div', {'class': 'col-md-3'}); c2.appendChild(os);
            vcol.appendChild(vin);
            var c4 = el('div', {'class': 'col-md-1 text-end'});
            var rm = el('button', {type: 'button', 'class': 'btn btn-sm btn-outline-danger', 'aria-label': 'Remove condition'}, '✕');
            rm.addEventListener('click', function () { parts.splice(ci, 1); save(); render(); });
            c4.appendChild(rm);
            [c1, c2, vcol, c4].forEach(function (c_) { row.appendChild(c_); });
            box.appendChild(row);
        });
        if (parts.length < 5) {
            var add = el('button', {type: 'button', 'class': 'btn btn-sm btn-link px-0 mt-1'}, parts.length ? '+ another condition' : '+ add a condition');
            if (!earlier.length) { add.disabled = true; add.textContent = 'Conditions can use questions above this one'; }
            add.addEventListener('click', function () {
                parts.push({field: earlier.length ? earlier[earlier.length - 1].key : '', op: 'equals', value: ''});
                save(); render();
            });
            box.appendChild(add);
        }
        return box;
    }

    function input(labelText, value, onInput, attrs) {
        var wrap = el('div', {'class': (attrs && attrs.col) || 'col-md-6'});
        var id = 'rb-' + Math.random().toString(36).slice(2);
        wrap.appendChild(el('label', {'class': 'form-label small mb-0', 'for': id}, labelText));
        var tag = attrs && attrs.textarea ? 'textarea' : 'input';
        var inp = el(tag, {'class': 'form-control form-control-sm', id: id, type: tag === 'input' ? ((attrs && attrs.type) || 'text') : false,
                           rows: attrs && attrs.textarea ? (attrs.rows || 3) : false, readonly: attrs && attrs.readonly,
                           placeholder: (attrs && attrs.placeholder) || false});
        inp.value = value === undefined || value === null ? '' : value;
        inp.addEventListener('input', function () { onInput(inp.value); dirty = true; sync(); });
        if (attrs && attrs.onBlur) inp.addEventListener('change', attrs.onBlur);
        wrap.appendChild(inp);
        if (attrs && attrs.help) wrap.appendChild(el('div', {'class': 'form-text'}, attrs.help));
        return wrap;
    }
    function check(labelText, on, onChange, col) {
        var wrap = el('div', {'class': (col || 'col-md-6') + ' form-check ms-2'});
        var id = 'rb-' + Math.random().toString(36).slice(2);
        var cb = el('input', {'class': 'form-check-input', type: 'checkbox', id: id});
        cb.checked = !!on;
        cb.addEventListener('change', function () { onChange(cb.checked); dirty = true; sync(); });
        wrap.appendChild(cb);
        wrap.appendChild(el('label', {'class': 'form-check-label small', 'for': id}, labelText));
        return wrap;
    }
    function setOrDelete(f, k, v) { if (v === '' || v === false || v === null || v === undefined) delete f[k]; else f[k] = v; }

    function editor(f, i) {
        var body = el('div', {'class': 'card-body pt-2'});
        var row = el('div', {'class': 'row g-2'});
        var isLocked = locked.indexOf(f.key) !== -1;
        row.appendChild(input(f.type === 'heading' ? 'Section title' : (f.type === 'info' ? 'Title (optional)' : 'Question'), f.label, function (v) {
            f.label = v;
            var t = list.querySelector('[data-index="' + i + '"] .rb-title'); if (t) t.textContent = v || '(no label)';
        }, {col: 'col-md-7'}));
        row.appendChild(input('ID', f.key, function (v) { f.key = v.trim(); }, {
            col: 'col-md-5', readonly: isLocked,
            help: isLocked ? 'Locked: used by the published form, tickets and routing rules.' : 'Stable ID used in routing rules and the subject pattern; it does not change when you edit the label.'}));
        if (DISPLAY.indexOf(f.type) === -1) {
            row.appendChild(check('Required', f.required, function (v) { f.required = v; }, 'col-md-3'));
            row.appendChild(check('Personal / sensitive', f.sensitive, function (v) { setOrDelete(f, 'sensitive', v); }, 'col-md-4'));
        }
        row.appendChild(input(f.type === 'info' ? 'Text' : 'Help text', f.help, function (v) { setOrDelete(f, 'help', v); },
            {col: 'col-12', textarea: f.type === 'info', rows: 2}));
        if (['text', 'textarea', 'email', 'tel', 'number', 'user'].indexOf(f.type) !== -1) {
            row.appendChild(input('Placeholder', f.placeholder, function (v) { setOrDelete(f, 'placeholder', v); }));
        }
        if (CHOICE.indexOf(f.type) !== -1) {
            row.appendChild(input('Options — one per line; "value | label" to keep a stable value', optionsText(f), function (v) {
                f.options = parseOptions(v);
            }, {col: 'col-12', textarea: true, rows: 4, onBlur: function () { render(); }}));
        }
        if (['text', 'textarea', 'email', 'tel', 'number', 'select', 'radio', 'date', 'user'].indexOf(f.type) !== -1) {
            row.appendChild(input('Default answer', f['default'], function (v) { setOrDelete(f, 'default', v); }, {col: 'col-md-6'}));
        }
        if (f.type === 'checkbox') row.appendChild(check('Ticked by default', f['default'], function (v) { setOrDelete(f, 'default', v); }));
        if (f.type === 'text' || f.type === 'textarea') {
            row.appendChild(input('Max length', f.max_length, function (v) { setOrDelete(f, 'max_length', v ? parseInt(v, 10) : ''); }, {type: 'number', col: 'col-md-3'}));
        }
        if (f.type === 'number') {
            row.appendChild(input('Minimum', f.min, function (v) { setOrDelete(f, 'min', v === '' ? '' : Number(v)); }, {type: 'number', col: 'col-md-3'}));
            row.appendChild(input('Maximum', f.max, function (v) { setOrDelete(f, 'max', v === '' ? '' : Number(v)); }, {type: 'number', col: 'col-md-3'}));
            row.appendChild(check('Whole numbers only', f.integer, function (v) { setOrDelete(f, 'integer', v); }, 'col-md-4'));
        }
        if (f.type === 'date' || f.type === 'datetime') {
            row.appendChild(check('No dates in the past', f.not_in_past, function (v) { setOrDelete(f, 'not_in_past', v); }));
            row.appendChild(check('Requested date (show "not a guaranteed commitment")', f.requested_date, function (v) { setOrDelete(f, 'requested_date', v); }));
        }
        if (f.type === 'file') {
            row.appendChild(input('Max files (1–5)', f.max_files || 1, function (v) { setOrDelete(f, 'max_files', v ? parseInt(v, 10) : ''); }, {type: 'number', col: 'col-md-3'}));
        }
        if (f.type === 'contact' || f.type === 'asset') {
            row.appendChild(check('Allow typing a name if not listed', f.allow_text !== false, function (v) { f.allow_text = v; }));
        }
        if (f.type === 'select' || f.type === 'radio') {
            row.appendChild(check('Records the customer\'s urgency (values low / medium / high / critical; never changes priority)',
                f.maps_to === 'urgency', function (v) { setOrDelete(f, 'maps_to', v ? 'urgency' : ''); }, 'col-12'));
        }
        body.appendChild(row);
        if (f.type !== 'info') body.appendChild(conditionEditor(f, i, 'show_if', f.type === 'heading' ? 'Show this section only when' : 'Show only when'));
        if (DISPLAY.indexOf(f.type) === -1) body.appendChild(conditionEditor(f, i, 'required_if', 'Required when'));
        return body;
    }

    var dragFrom = null;
    function render() {
        list.textContent = '';
        fields.forEach(function (f, i) {
            var card = el('div', {'class': 'card mb-2 rb-field' + (f.type === 'heading' ? ' border-primary' : ''), 'data-index': i});
            var head = el('div', {'class': 'card-header d-flex align-items-center gap-2 py-1 flex-wrap'});
            var handle = el('span', {'class': 'rb-handle text-muted', draggable: 'true', title: 'Drag to reorder', 'aria-hidden': 'true'});
            handle.appendChild(el('i', {'class': 'fas fa-grip-vertical'}));
            handle.addEventListener('dragstart', function (e) { dragFrom = i; card.classList.add('opacity-50'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); });
            handle.addEventListener('dragend', function () { card.classList.remove('opacity-50'); });
            card.addEventListener('dragover', function (e) { if (dragFrom !== null) { e.preventDefault(); card.classList.add('border-info'); } });
            card.addEventListener('dragleave', function () { card.classList.remove('border-info'); });
            card.addEventListener('drop', function (e) { e.preventDefault(); card.classList.remove('border-info'); if (dragFrom !== null && dragFrom !== i) move(dragFrom, i); dragFrom = null; });
            head.appendChild(handle);
            head.appendChild(el('span', {'class': 'badge text-bg-light border'}, typeLabel[f.type] || f.type));
            var title = el('strong', {'class': 'rb-title flex-grow-1 text-truncate'}, f.label || (f.type === 'info' ? (f.help || '').slice(0, 60) : '(no label)'));
            head.appendChild(title);
            if (f.required) head.appendChild(el('span', {'class': 'badge bg-danger-subtle text-danger-emphasis'}, 'required'));
            if (f.show_if) head.appendChild(el('span', {'class': 'badge bg-info-subtle text-info-emphasis'}, 'conditional'));
            if (f.required_if) head.appendChild(el('span', {'class': 'badge bg-warning-subtle text-warning-emphasis'}, 'required when'));
            head.appendChild(el('code', {'class': 'small'}, f.key));
            var up = el('button', {type: 'button', 'class': 'btn btn-sm btn-outline-secondary rb-move-up', 'aria-label': 'Move "' + (f.label || f.key) + '" up', title: 'Move up', disabled: i === 0}, '↑');
            up.addEventListener('click', function () { move(i, i - 1); });
            var dn = el('button', {type: 'button', 'class': 'btn btn-sm btn-outline-secondary rb-move-down', 'aria-label': 'Move "' + (f.label || f.key) + '" down', title: 'Move down', disabled: i === fields.length - 1}, '↓');
            dn.addEventListener('click', function () { move(i, i + 1); });
            var ed = el('button', {type: 'button', 'class': 'btn btn-sm btn-outline-primary', 'aria-expanded': open[i] ? 'true' : 'false'}, open[i] ? 'Close' : 'Edit');
            ed.addEventListener('click', function () { open[i] = !open[i]; render(); });
            var dup = el('button', {type: 'button', 'class': 'btn btn-sm btn-outline-secondary', 'aria-label': 'Duplicate "' + (f.label || f.key) + '"', title: 'Duplicate'}, '⧉');
            dup.addEventListener('click', function () {
                var c = JSON.parse(JSON.stringify(f)); c.key = slugKey(f.label || f.key); c.label = (f.label || '') + ' (copy)';
                fields.splice(i + 1, 0, c); open[i + 1] = true; dirty = true; sync(); render();
            });
            var del = el('button', {type: 'button', 'class': 'btn btn-sm btn-outline-danger', 'aria-label': 'Remove "' + (f.label || f.key) + '"', title: 'Remove'}, '✕');
            del.addEventListener('click', function () {
                if (!window.confirm('Remove "' + (f.label || f.key) + '"? Tickets already submitted keep their answers.')) return;
                fields.splice(i, 1); dirty = true; sync(); render(); announce('Removed.');
            });
            [up, dn, ed, dup, del].forEach(function (b) { head.appendChild(b); });
            card.appendChild(head);
            if (open[i]) card.appendChild(editor(f, i));
            list.appendChild(card);
        });
        if (!fields.length) list.appendChild(el('p', {'class': 'text-muted small'}, 'No questions yet — the customer just submits the request. Add questions below.'));
    }

    document.getElementById('rb-add').addEventListener('click', function () {
        var t = document.getElementById('rb-add-type').value;
        var label = t === 'heading' ? 'New section' : (t === 'info' ? '' : 'New question');
        var f = {key: slugKey(t === 'heading' ? 'section' : (t === 'info' ? 'note' : 'question')), label: label, type: t};
        if (DISPLAY.indexOf(t) === -1) f.required = false;
        if (CHOICE.indexOf(t) !== -1) f.options = ['Option 1', 'Option 2'];
        if (t === 'info') f.help = 'Text shown to the customer.';
        if (t === 'file') f.max_files = 1;
        fields.push(f);
        open[fields.length - 1] = true;
        dirty = true; sync(); render();
        announce('Added a ' + (typeLabel[t] || t) + ' at the end.');
    });

    var raw = document.getElementById('rb-raw');
    var applyRaw = document.getElementById('rb-raw-apply');
    if (raw && applyRaw) {
        applyRaw.addEventListener('click', function () {
            try {
                var parsed = JSON.parse(raw.value || '[]');
                if (!Array.isArray(parsed)) throw new Error('the form must be a list');
                fields = parsed; open = {}; dirty = true; sync(); render(); announce('JSON applied.');
            } catch (e) { window.alert('JSON error: ' + e.message); }
        });
    }

    var form = document.getElementById('rb-form');
    form.addEventListener('submit', function () { sync(); dirty = false; });
    window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
    sync();
    render();
})();
