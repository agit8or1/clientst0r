/* Wide tables scroll sideways inside their own container.
 *
 * Many list pages put a table straight into a card. On a narrow screen the
 * table is wider than the card and the page clips it (html/body hide
 * horizontal overflow), so columns at the right were unreachable. Any table
 * in the main content that is wider than its parent gets wrapped in a
 * scrolling div; tables already inside a scroll wrapper are left alone.
 * Re-checked after load, when DataTables initialises or redraws, and on
 * resize (a table can become too wide later).
 */
(function () {
    'use strict';
    var SKIP = '.table-responsive, .ui-table-wrap, .table-autowrap, .dataTables_scrollBody, .no-auto-scroll';

    function wrapWide() {
        var main = document.getElementById('main-content');
        if (!main) return;
        main.querySelectorAll('table').forEach(function (table) {
            var parent = table.parentElement;
            if (!parent || table.closest(SKIP) || parent.closest('table')) return;
            if (table.offsetWidth <= parent.clientWidth + 1) return;
            var box = document.createElement('div');
            box.className = 'table-autowrap';
            parent.insertBefore(box, table);
            box.appendChild(table);
        });
    }

    var timer = null;
    function later(ms) {
        clearTimeout(timer);
        timer = setTimeout(wrapWide, ms);
    }
    window.addEventListener('load', function () {
        wrapWide();
        // DataTables and late fonts can widen a table after load.
        setTimeout(wrapWide, 600);
        setTimeout(wrapWide, 1800);
    });
    window.addEventListener('resize', function () { later(200); });
    if (window.jQuery) {
        window.jQuery(document).on('init.dt draw.dt', function () { later(50); });
    }
})();
