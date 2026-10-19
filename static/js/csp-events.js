/*
 * Event wiring without inline handlers, so the Content-Security-Policy can
 * block inline event-handler attributes (script-src-attr 'none'). Loaded once from every base template.
 * All listeners are delegated from `document`, so they also cover HTML that
 * scripts insert later.
 *
 *   data-confirm="Message"       click on a link/button, or submit of a <form>:
 *                                ask first; cancelling stops the action.
 *   data-autosubmit              change on a field submits its form.
 *   data-click="#id"             click forwards a click to that element.
 *   data-copy-from="#id"         click copies that field's value; with
 *                                data-copied-text="Copied!" the button's
 *                                text changes after copying.
 *   data-open-url="url"          click opens the URL in a new tab.
 *   data-check-all="selector"    click on a checkbox sets every matching
 *                                checkbox to its state.
 *   data-toggle-hidden="sel"     click toggles .d-none on matching elements.
 *   data-on-enter="fnName"       Enter key in a field calls window.fnName.
 *   data-print / data-reload     click prints / reloads the page.
 *   data-select-on-click         click selects the field's text.
 *   data-action="fnName"         click calls window.fnName(...args);
 *                                add data-prevent to also cancel the click
 *                                (like `fn(); return false;` inline).
 *   data-on-change="fnName"      same, on change.
 *   data-on-input="fnName"       same, on input.
 *   data-on-submit="fnName"      same, on submit of a <form>.
 *   data-on-keyup="fnName"       same, on keyup.
 *   data-on-keypress="fnName"    same, on keypress.
 *   data-on-dragover / data-on-drop="fnName"
 *
 * Arguments for the called function:
 *   data-args='["a", 1, true]'   a JSON array, or
 *   data-arg="text"              a single string.
 * Inside data-args the strings "$this", "$value", "$checked", "$files" and
 * "$event" become the element, its value, its checked state, its selected
 * files and the event.
 * The function runs with `this` set to the element. If it returns false the
 * event's default action is cancelled (like `return fn()` inline).
 */
(function () {
    'use strict';

    function resolveArgs(el, ev) {
        var raw = el.getAttribute('data-args');
        var args;
        if (raw !== null) {
            try {
                args = JSON.parse(raw);
            } catch (e) {
                console.error('csp-events: bad data-args on', el, e);
                return [];
            }
            if (!Array.isArray(args)) args = [args];
        } else if (el.hasAttribute('data-arg')) {
            args = [el.getAttribute('data-arg')];
        } else {
            args = [];
        }
        return args.map(function (a) {
            if (a === '$this') return el;
            if (a === '$value') return el.value;
            if (a === '$checked') return el.checked;
            if (a === '$files') return el.files;
            if (a === '$event') return ev;
            return a;
        });
    }

    function callNamed(el, attr, ev) {
        var name = el.getAttribute(attr);
        var fn = name && name.split('.').reduce(function (o, k) {
            return o == null ? undefined : o[k];
        }, window);
        if (typeof fn !== 'function') {
            console.error('csp-events: no function "' + name + '" for', el);
            return;
        }
        var result = fn.apply(el, resolveArgs(el, ev));
        if (result === false) {
            ev.preventDefault();
        }
    }

    function closest(ev, selector) {
        var t = ev.target;
        if (t && t.nodeType !== 1) t = t.parentElement;
        return t && t.closest ? t.closest(selector) : null;
    }

    // Confirmations run in the capture phase, ahead of every other listener,
    // so cancelling one also stops data-action and page-level handlers.
    document.addEventListener('click', function (ev) {
        var el = closest(ev, '[data-confirm]');
        if (!el || el.tagName === 'FORM') return;
        if (!window.confirm(el.getAttribute('data-confirm'))) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (!form || form.tagName !== 'FORM') return;
        if (form.hasAttribute('data-confirm')
                && !window.confirm(form.getAttribute('data-confirm'))) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener('click', function (ev) {
        var el;
        if ((el = closest(ev, '[data-click]'))) {
            var target = document.querySelector(el.getAttribute('data-click'));
            if (target) target.click();
        }
        if ((el = closest(ev, '[data-copy-from]'))) {
            var src = document.querySelector(el.getAttribute('data-copy-from'));
            if (src && navigator.clipboard) {
                navigator.clipboard.writeText(src.value !== undefined ? src.value : src.textContent);
                if (el.hasAttribute('data-copied-text')) {
                    el.textContent = el.getAttribute('data-copied-text');
                }
            }
        }
        if ((el = closest(ev, '[data-open-url]'))) {
            ev.preventDefault();
            window.open(el.getAttribute('data-open-url'), '_blank', 'noopener');
        }
        if ((el = closest(ev, '[data-check-all]'))) {
            var on = el.checked;
            document.querySelectorAll(el.getAttribute('data-check-all')).forEach(function (cb) {
                cb.checked = on;
            });
        }
        if ((el = closest(ev, '[data-toggle-hidden]'))) {
            ev.preventDefault();
            document.querySelectorAll(el.getAttribute('data-toggle-hidden')).forEach(function (t) {
                t.classList.toggle('d-none');
            });
        }
        if (closest(ev, '[data-print]')) {
            ev.preventDefault();
            window.print();
        }
        if (closest(ev, '[data-reload]')) {
            ev.preventDefault();
            window.location.reload();
        }
        if ((el = closest(ev, '[data-select-on-click]')) && el.select) {
            el.select();
        }
        if ((el = closest(ev, '[data-action]'))) {
            if (el.hasAttribute('data-prevent')) ev.preventDefault();
            callNamed(el, 'data-action', ev);
        }
    });

    document.addEventListener('change', function (ev) {
        var el = ev.target;
        if (!el || el.nodeType !== 1) return;
        if (el.hasAttribute('data-autosubmit') && el.form) {
            el.form.submit();
        }
        if (el.hasAttribute('data-on-change')) {
            callNamed(el, 'data-on-change', ev);
        }
    });

    // Events whose handler is on the element itself (or an ancestor).
    ['input', 'keyup', 'keypress', 'dragover', 'drop'].forEach(function (type) {
        var attr = 'data-on-' + type;
        document.addEventListener(type, function (ev) {
            var el = closest(ev, '[' + attr + ']');
            if (el) callNamed(el, attr, ev);
        });
    });

    document.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter') return;
        var el = closest(ev, '[data-on-enter]');
        if (el) {
            ev.preventDefault();
            callNamed(el, 'data-on-enter', ev);
        }
    });

    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (form && form.tagName === 'FORM' && form.hasAttribute('data-on-submit')) {
            callNamed(form, 'data-on-submit', ev);
        }
    });
})();
