/*
 * Contract builder, template editor and clause editor.
 *
 * The forms work without this script (plain textareas, Save buttons). This
 * adds: the rich-text editor (Quill, vendored) with tables and page breaks,
 * adding / removing / reordering sections, lines and signers, inserting
 * clauses and merge fields, and autosave with a visible saved state.
 * No inline handlers (CSP): everything is wired here.
 */
(function () {
    'use strict';

    var form = document.getElementById('cd-builder');
    if (!form) return;

    var autosaveUrl = form.getAttribute('data-autosave-url') || '';
    var stateEl = document.getElementById('cd-save-state');
    var errorsEl = document.getElementById('cd-save-errors');
    var revisionEl = document.getElementById('cd-revision');
    var editors = [];
    var lastFocus = null;   // {quill} or {field}
    var dirty = false, saving = false, conflict = false, timer = null, pendingSubmit = null, afterSave = [];

    // --- Quill setup ---------------------------------------------------------
    var hasQuill = typeof window.Quill !== 'undefined';
    if (hasQuill) {
        var BlockEmbed = Quill.import('blots/block/embed');
        class PageBreak extends BlockEmbed {}
        PageBreak.blotName = 'pagebreak';
        PageBreak.tagName = 'HR';
        PageBreak.className = 'page-break';
        Quill.register(PageBreak, true);
    }

    var TOOLBAR = [
        [{ header: [2, 3, false] }],
        ['bold', 'italic', 'underline'],
        [{ list: 'ordered' }, { list: 'bullet' }, { indent: '-1' }, { indent: '+1' }],
        ['link', 'blockquote'],
        ['table-insert', 'pagebreak'],
        ['clean']
    ];

    function tableMenu(quill) {
        var t = quill.getModule('table');
        var choice = window.prompt('Table: type "new 3x4" for a new table, or one of: row, column, delete row, delete column, delete table', 'new 3x3');
        if (!choice) return;
        choice = choice.trim().toLowerCase();
        var m = /^new\s+(\d{1,2})\s*x\s*(\d{1,2})$/.exec(choice);
        quill.focus();
        if (m) { t.insertTable(Math.max(1, +m[1]), Math.max(1, +m[2])); return; }
        if (choice === 'row') t.insertRowBelow();
        else if (choice === 'column') t.insertColumnRight();
        else if (choice === 'delete row') t.deleteRow();
        else if (choice === 'delete column') t.deleteColumn();
        else if (choice === 'delete table') t.deleteTable();
    }

    function initEditor(section) {
        var ta = section.querySelector('textarea.cd-body');
        var holder = section.querySelector('.cd-editor');
        if (!hasQuill || !ta || !holder || holder.getAttribute('data-ready')) return;
        holder.setAttribute('data-ready', '1');
        holder.innerHTML = ta.value || '<p></p>';   // server-sanitised HTML
        holder.hidden = false;
        var quill = new Quill(holder, {
            theme: 'snow',
            modules: {
                table: true,
                toolbar: {
                    container: TOOLBAR,
                    handlers: {
                        'pagebreak': function () {
                            var r = quill.getSelection(true);
                            quill.insertEmbed(r.index, 'pagebreak', true, 'user');
                            quill.setSelection(r.index + 1, 0, 'silent');
                        },
                        'table-insert': function () { tableMenu(quill); }
                    }
                }
            }
        });
        var tb = holder.previousElementSibling;
        if (tb && tb.classList.contains('ql-toolbar')) {
            var pb = tb.querySelector('.ql-pagebreak');
            if (pb) { pb.setAttribute('title', 'Insert page break'); pb.setAttribute('aria-label', 'Insert page break'); }
            var tbl = tb.querySelector('.ql-table-insert');
            if (tbl) { tbl.setAttribute('title', 'Table'); tbl.setAttribute('aria-label', 'Table'); }
        }
        ta.hidden = true;
        var sync = function () { ta.value = semantic(quill); };
        sync();
        quill.on('text-change', function (d, o, source) { sync(); if (source === 'user') changed(); });
        quill.on('selection-change', function (r) { if (r) lastFocus = { quill: quill }; });
        editors.push({ quill: quill, ta: ta });
        section._quill = quill;
    }

    // Quill 2.0.3's getSemanticHTML() writes every space as &nbsp;, which
    // would stop lines wrapping in the document and the PDF.
    function semantic(quill) {
        return quill.getSemanticHTML().replace(/&nbsp;/g, ' ').replace(/\u00a0/g, ' ');
    }

    function syncAll() {
        editors.forEach(function (e) { e.ta.value = semantic(e.quill); });
    }

    // --- index helpers ---------------------------------------------------------
    function nextIndex(prefix) {
        var max = -1;
        form.querySelectorAll('[name^="' + prefix + '-"]').forEach(function (el) {
            var m = new RegExp('^' + prefix + '-(\\d+)-').exec(el.name);
            if (m) max = Math.max(max, +m[1]);
        });
        return max + 1;
    }

    function fromTemplate(id, prefix) {
        var tpl = document.getElementById(id);
        if (!tpl) return null;
        var i = nextIndex(prefix);
        var html = tpl.innerHTML.replace(/__i__/g, String(i));
        var box = document.createElement(/^\s*<tr/i.test(html) ? 'tbody' : 'div');
        box.innerHTML = html;
        return box.firstElementChild;
    }

    // --- sections -----------------------------------------------------------------
    var sectionsBox = form.querySelector('[data-sections]');

    function liveSections() {
        return sectionsBox ? Array.prototype.filter.call(sectionsBox.querySelectorAll('[data-section]'), function (s) {
            return !s.hidden;
        }) : [];
    }

    function renumber() {
        liveSections().forEach(function (s, n) {
            var o = s.querySelector('[data-order]');
            if (o) o.value = n + 1;
        });
    }

    function addSection(title, body) {
        var el = fromTemplate('tpl-section', 'section');
        if (!el || !sectionsBox) return null;
        var sig = Array.prototype.filter.call(liveSections(), function (s) {
            var t = s.querySelector('select[name$="-type"]');
            return t && t.value === 'signatures';
        })[0];
        if (sig) sectionsBox.insertBefore(el, sig); else sectionsBox.appendChild(el);
        if (title) el.querySelector('input[name$="-title"]').value = title;
        if (body) el.querySelector('textarea.cd-body').value = body;
        var inc = el.querySelector('input[name$="-include"]');
        if (inc) inc.checked = true;
        initEditor(el);
        renumber();
        changed();
        var t = el.querySelector('input[name$="-title"]');
        if (t && !title) t.focus();
        return el;
    }

    // --- events ---------------------------------------------------------------------
    form.addEventListener('click', function (ev) {
        var b = ev.target.closest('button, a');
        if (!b || !form.contains(b)) return;
        var card;
        if (b.hasAttribute('data-add-section')) { addSection('', ''); return; }
        if (b.hasAttribute('data-add-clause')) {
            var pick = document.getElementById('cd-clause-pick');
            var data = JSON.parse((document.getElementById('cd-clause-data') || {}).textContent || '{}');
            var cl = pick && data[pick.value];
            if (cl) addSection(cl.title, cl.body);
            return;
        }
        if (b.hasAttribute('data-remove-section')) {
            card = b.closest('[data-section]');
            var title = (card.querySelector('input[name$="-title"]') || {}).value || 'this section';
            if (!window.confirm('Remove "' + title + '" from the document?')) return;
            card.querySelector('[data-deleted]').value = '1';
            card.hidden = true;
            renumber(); changed();
            return;
        }
        if (b.hasAttribute('data-move')) {
            card = b.closest('[data-section]');
            var live = liveSections(), at = live.indexOf(card);
            if (b.getAttribute('data-move') === 'up' && at > 0) sectionsBox.insertBefore(card, live[at - 1]);
            if (b.getAttribute('data-move') === 'down' && at < live.length - 1) sectionsBox.insertBefore(live[at + 1], card);
            renumber(); changed(); b.focus();
            return;
        }
        if (b.hasAttribute('data-add-line')) {
            var row = fromTemplate('tpl-line', 'item');
            var body = form.querySelector('[data-lines]');
            if (row && body) { body.appendChild(row); row.querySelector('input').focus(); changed(); }
            return;
        }
        if (b.hasAttribute('data-remove-row')) {
            var tr = b.closest('[data-line]');
            tr.querySelector('[data-deleted]').value = '1';
            tr.hidden = true; changed();
            return;
        }
        if (b.hasAttribute('data-add-signer')) {
            var s = fromTemplate('tpl-signer', 'signer');
            var box = form.querySelector('[data-signers]');
            if (s && box) {
                var orders = box.querySelectorAll('[data-signer]:not([hidden]) input[name$="-order"]');
                s.querySelector('input[name$="-order"]').value = orders.length + 1;
                box.appendChild(s); s.querySelector('input[name$="-name"]').focus(); changed();
            }
            return;
        }
        if (b.hasAttribute('data-remove-signer')) {
            var sg = b.closest('[data-signer]');
            sg.querySelector('[data-deleted]').value = '1';
            sg.hidden = true; changed();
            return;
        }
        if (b.hasAttribute('data-merge')) {
            insertMerge('{{' + b.getAttribute('data-merge') + '}}');
            return;
        }
        if (b.hasAttribute('data-save-first')) {
            ev.preventDefault();
            var href = b.getAttribute('href');
            var win = window.open('about:blank', '_blank');
            saveNow(function () { if (win) { win.opener = null; win.location = href; } else { window.location = href; } });
        }
    });

    // Merge-field buttons live outside some forms' click area on the template
    // page; listen on the document too (deduplicated by the form check above).
    document.addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-merge]');
        if (!b || form.contains(b)) return;
        insertMerge('{{' + b.getAttribute('data-merge') + '}}');
    });

    function insertMerge(text) {
        if (lastFocus && lastFocus.quill) {
            var q = lastFocus.quill, r = q.getSelection(true);
            q.insertText(r.index, text, 'user');
            q.setSelection(r.index + text.length, 0, 'silent');
            return;
        }
        var f = lastFocus && lastFocus.field;
        if (f && document.body.contains(f)) {
            var a = f.selectionStart || 0, z = f.selectionEnd || a;
            f.value = f.value.slice(0, a) + text + f.value.slice(z);
            f.focus(); f.setSelectionRange(a + text.length, a + text.length);
            changed();
            return;
        }
        if (editors.length) { lastFocus = { quill: editors[0].quill }; insertMerge(text); }
    }

    form.addEventListener('focusin', function (ev) {
        var t = ev.target;
        if ((t.tagName === 'TEXTAREA' || (t.tagName === 'INPUT' && /^(text|search|)$/.test(t.type))) && !t.closest('.ql-container')) {
            lastFocus = { field: t };
        }
    });

    form.addEventListener('change', function (ev) {
        var t = ev.target;
        if (t.matches('[data-signer-role]')) {
            var box = t.closest('[data-signer]').querySelector('[data-internal-only]');
            if (box) box.hidden = t.value !== 'internal';
        }
        if (t.name && /-include$/.test(t.name)) {
            t.closest('[data-section]').classList.toggle('cd-excluded', !t.checked);
        }
        if (t.name && /^section-\d+-type$/.test(t.name)) {
            var note = t.closest('[data-section]').querySelector('.cd-type-note');
            if (note) note.textContent = t.value === 'pricing' ? 'The pricing table from the line items is added after this text.'
                : t.value === 'signatures' ? 'Signature blocks for every signer are added after this text.' : '';
        }
        if (t.closest('.ql-container')) return;
        if (t.type !== 'file') changed();
    });
    form.addEventListener('input', function (ev) {
        if (ev.target.closest('.ql-container')) return;
        changed();
    });

    // --- autosave ----------------------------------------------------------------------
    function setState(text, cls) {
        if (!stateEl) return;
        stateEl.textContent = text;
        stateEl.className = 'small ' + (cls || 'text-body-secondary');
    }

    function changed() {
        dirty = true;
        if (!autosaveUrl || conflict) return;
        setState('Unsaved changes…');
        clearTimeout(timer);
        timer = setTimeout(function () { saveNow(); }, 2000);
    }

    function csrf() {
        var el = form.querySelector('input[name="csrfmiddlewaretoken"]');
        return el ? el.value : '';
    }

    function saveNow(done) {
        if (done) afterSave.push(done);
        if (!autosaveUrl) { flush(); return; }
        if (conflict) { flush(); return; }
        if (saving) return;
        clearTimeout(timer);
        if (!dirty) { flush(); return; }
        syncAll();
        saving = true; dirty = false;
        setState('Saving…');
        var body = new FormData(form);
        fetch(autosaveUrl, {
            method: 'POST', body: body, credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (r) {
            return r.json().catch(function () { return { ok: false, errors: ['The server answered ' + r.status + '.'] }; })
                .then(function (j) { j._status = r.status; return j; });
        }).then(function (j) {
            saving = false;
            if (j.ok) {
                if (revisionEl && j.revision !== undefined) revisionEl.value = j.revision;
                setState('Saved ' + j.saved_at, 'text-success');
                if (errorsEl) errorsEl.hidden = true;
            } else if (j._status === 409) {
                conflict = true;
                setState('Not saved — changed elsewhere', 'text-danger');
                showErrors(['This draft was changed in another window or by someone else. Copy anything you need, then reload the page.']);
            } else {
                dirty = true;
                setState('Not saved — check the fields', 'text-danger');
                showErrors(j.errors || ['Could not save.']);
            }
            if (dirty && !conflict && !pendingSubmit && j.ok) changed();
            flush();
        }).catch(function () {
            saving = false; dirty = true;
            setState('Not saved — offline? Retrying…', 'text-danger');
            timer = setTimeout(function () { saveNow(); }, 10000);
            flush();
        });
    }

    function flush() {
        var list = afterSave; afterSave = [];
        list.forEach(function (f) { try { f(); } catch (e) { /* ignore */ } });
        if (pendingSubmit && !saving) {
            var s = pendingSubmit; pendingSubmit = null;
            dirty = false;
            if (form.requestSubmit) form.requestSubmit(s === true ? undefined : s); else form.submit();
        }
    }

    function showErrors(list) {
        if (!errorsEl) return;
        errorsEl.textContent = '';
        var ul = document.createElement('ul'); ul.className = 'mb-0';
        list.forEach(function (e) { var li = document.createElement('li'); li.textContent = e; ul.appendChild(li); });
        errorsEl.appendChild(ul);
        errorsEl.hidden = false;
    }

    form.addEventListener('submit', function (ev) {
        syncAll();
        if (saving) {   // let the running autosave finish so the revision is current
            ev.preventDefault();
            pendingSubmit = ev.submitter || true;
            return;
        }
        clearTimeout(timer);
        dirty = false;
    });

    window.addEventListener('beforeunload', function (ev) {
        if ((dirty || saving) && autosaveUrl && !conflict) {
            ev.preventDefault();
            ev.returnValue = '';
        }
    });

    // --- start ----------------------------------------------------------------------------
    form.querySelectorAll('[data-section]').forEach(initEditor);
    form.querySelectorAll('input[name$="-include"]').forEach(function (c) {
        var card = c.closest('[data-section]');
        if (card) card.classList.toggle('cd-excluded', !c.checked);
    });
    dirty = false;
})();
