/* "What do you need help with?" — filter request types as the customer types. */
(function () {
    'use strict';
    var input = document.getElementById('request-type-search');
    if (!input) return;
    var cards = Array.prototype.slice.call(document.querySelectorAll('.js-request-type'));
    var groups = Array.prototype.slice.call(document.querySelectorAll('.js-request-group'));
    var empty = document.getElementById('request-type-empty');
    var status = document.getElementById('request-type-status');
    input.hidden = false;
    var wrap = document.getElementById('request-type-search-wrap');
    if (wrap) wrap.hidden = false;

    function apply() {
        var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
        var shown = 0;
        cards.forEach(function (c) {
            var hay = (c.getAttribute('data-search') || '').toLowerCase();
            var ok = words.every(function (w) { return hay.indexOf(w) !== -1; });
            c.hidden = !ok;
            if (ok && !c.classList.contains('js-always')) shown++;
        });
        groups.forEach(function (g) {
            g.hidden = !g.querySelector('.js-request-type:not([hidden])');
        });
        if (empty) empty.hidden = !(words.length && shown === 0);
        if (status) status.textContent = words.length ? shown + ' matching request type' + (shown === 1 ? '' : 's') : '';
    }
    input.addEventListener('input', apply);
})();
