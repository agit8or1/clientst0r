/*
 * Access group page: per-feature permission matrix. Picking a level ticks
 * the permissions that level gives; ticking a permission by hand switches the
 * module to "Custom". Convenience only - the server maps levels to
 * permissions itself and checks every permission on save. No inline script.
 */
(function () {
    'use strict';
    function keysFor(select, level) {
        var raw = select.getAttribute('data-level-' + level);
        return raw ? raw.split(' ') : [];
    }
    function apply(select) {
        var level = select.value;
        if (level === 'custom') { return; }
        var on = keysFor(select, level);
        var row = select.closest('.feat-row');
        row.querySelectorAll('input[name="feat_key"]').forEach(function (box) {
            box.checked = on.indexOf(box.value) !== -1;
        });
    }
    function count(row) {
        var n = row.querySelectorAll('input[name="feat_key"]:checked').length;
        var badge = row.querySelector('.feat-count');
        if (badge) { badge.textContent = n ? n + ' granted here' : ''; }
    }
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.feat-row').forEach(function (row) {
            var select = row.querySelector('select.feat-level');
            if (!select) { return; }
            select.addEventListener('change', function () { apply(select); count(row); });
            row.querySelectorAll('input[name="feat_key"]').forEach(function (box) {
                box.addEventListener('change', function () { select.value = 'custom'; count(row); });
            });
            count(row);
        });
    });
}());
