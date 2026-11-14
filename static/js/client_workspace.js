/* Client workspace tab strip: keep the tabs on one row and move the ones that
   do not fit into a "More" dropdown (the active tab always stays visible).
   Without this script the row scrolls sideways inside itself. */
(function () {
    'use strict';

    function setup(list) {
        var more = list.querySelector('[data-cw-more]');
        var menu = list.querySelector('[data-cw-more-menu]');
        if (!more || !menu) return;
        var items = Array.prototype.slice.call(list.querySelectorAll('.cw-tabs__item:not([data-cw-more])'));
        list.classList.add('is-measured');

        function fits() {
            return list.scrollWidth <= list.clientWidth + 1;
        }

        function layout() {
            items.forEach(function (li) { li.hidden = false; });
            more.hidden = true;
            menu.textContent = '';
            if (fits()) return;
            more.hidden = false;
            var hidden = [];
            for (var i = items.length - 1; i >= 0 && !fits(); i--) {
                if (items[i].hasAttribute('data-active')) continue;
                items[i].hidden = true;
                hidden.unshift(items[i]);
            }
            hidden.forEach(function (li) {
                var src = li.querySelector('a');
                var row = document.createElement('li');
                var a = document.createElement('a');
                a.className = 'dropdown-item';
                a.href = src.getAttribute('href');
                var icon = src.querySelector('i');
                if (icon) a.appendChild(icon.cloneNode(true));
                a.appendChild(document.createTextNode(' ' + (src.querySelector('span') || src).textContent.trim()));
                row.appendChild(a);
                menu.appendChild(row);
            });
        }

        var timer = null;
        window.addEventListener('resize', function () {
            clearTimeout(timer);
            timer = setTimeout(layout, 80);
        });
        layout();
        // Icon and web fonts change the tab widths once they arrive.
        window.addEventListener('load', layout);
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
    }

    function init() {
        document.querySelectorAll('[data-cw-tabs]').forEach(setup);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
