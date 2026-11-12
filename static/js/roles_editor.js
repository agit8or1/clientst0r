/*
 * Role editor: filter the permission list as you type. No inline script, so
 * the Content-Security-Policy keeps blocking inline code. Filtering is a
 * convenience only; the server checks every permission on save.
 */
(function () {
    'use strict';
    function filter(term) {
        var q = (term || '').trim().toLowerCase();
        document.querySelectorAll('.perm-group').forEach(function (group) {
            var shown = 0;
            group.querySelectorAll('.perm-item').forEach(function (item) {
                var hit = !q || (item.getAttribute('data-search') || '').indexOf(q) !== -1;
                item.classList.toggle('d-none', !hit);
                if (hit) { shown += 1; }
            });
            group.classList.toggle('d-none', shown === 0);
        });
    }
    document.addEventListener('DOMContentLoaded', function () {
        var box = document.getElementById('perm-search');
        if (!box) { return; }
        box.addEventListener('input', function () { filter(box.value); });
        filter(box.value);
    });
}());
