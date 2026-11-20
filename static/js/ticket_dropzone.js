/* Drag-and-drop files onto the ticket composer (roadmap 52.20).
 *
 * Dropped files are added to the existing, labelled file input of the
 * Attachments form via DataTransfer, so the normal form post and the
 * server-side attachment rules handle them. The file input stays usable
 * on its own for keyboard and screen-reader users. */
(function () {
    'use strict';
    var zone = document.querySelector('[data-dropzone]');
    if (!zone) { return; }
    var input = document.getElementById(zone.getAttribute('data-target-input'));
    if (!input || typeof DataTransfer === 'undefined') { return; }
    var internalBox = document.getElementById(zone.getAttribute('data-target-internal'));
    var modeField = document.getElementById('composerIsInternal');
    var list = zone.querySelector('[data-dropzone-list]');
    var actions = zone.querySelector('[data-dropzone-actions]');
    var countEl = zone.querySelector('[data-dropzone-count]');
    var uploadBtn = zone.querySelector('[data-dropzone-upload]');
    var depth = 0;

    function hasFiles(e) {
        var t = e.dataTransfer && e.dataTransfer.types;
        return !!t && Array.prototype.indexOf.call(t, 'Files') !== -1;
    }
    function currentFiles() { return Array.prototype.slice.call(input.files || []); }
    function setFiles(files) {
        var dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
        render();
    }
    function render() {
        var files = currentFiles();
        list.textContent = '';
        files.forEach(function (f, i) {
            var li = document.createElement('li');
            var name = document.createElement('span');
            name.textContent = f.name + ' (' + Math.max(1, Math.round(f.size / 1024)) + ' KB)';
            var rm = document.createElement('button');
            rm.type = 'button';
            rm.className = 'btn btn-sm btn-link text-danger p-0';
            rm.setAttribute('aria-label', 'Remove ' + f.name);
            rm.textContent = '×';
            rm.addEventListener('click', function () {
                var rest = currentFiles();
                rest.splice(i, 1);
                setFiles(rest);
            });
            li.appendChild(name);
            li.appendChild(rm);
            list.appendChild(li);
        });
        actions.hidden = files.length === 0;
        countEl.textContent = files.length ? String(files.length) : '';
    }

    zone.addEventListener('dragenter', function (e) {
        if (!hasFiles(e)) { return; }
        e.preventDefault();
        depth += 1;
        zone.classList.add('is-dragover');
    });
    zone.addEventListener('dragover', function (e) {
        if (!hasFiles(e)) { return; }
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    });
    zone.addEventListener('dragleave', function (e) {
        if (!hasFiles(e)) { return; }
        depth = Math.max(0, depth - 1);
        if (depth === 0) { zone.classList.remove('is-dragover'); }
    });
    zone.addEventListener('drop', function (e) {
        if (!hasFiles(e)) { return; }
        e.preventDefault();
        depth = 0;
        zone.classList.remove('is-dragover');
        var merged = currentFiles().concat(Array.prototype.slice.call(e.dataTransfer.files));
        setFiles(merged);
    });
    input.addEventListener('change', render);

    if (uploadBtn) {
        uploadBtn.addEventListener('click', function () {
            if (internalBox && modeField) { internalBox.checked = modeField.value === '1'; }
            if (input.form) {
                if (input.form.requestSubmit) { input.form.requestSubmit(); } else { input.form.submit(); }
            }
        });
    }
    render();
})();
