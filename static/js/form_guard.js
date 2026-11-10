/*
 * Unsaved edits and the client switcher.
 *
 * Two things, for POST forms inside <main id="main-content">:
 *
 * 1. Each form is stamped with a hidden `_org_context` field holding the
 *    client the page was rendered for (body[data-org-context]). If the
 *    session has switched client since — in another tab, say — the server
 *    (core.org_context_guard) refuses the save instead of writing it under
 *    the other client.
 *
 * 2. Switching client (any link to accounts:switch_organization or Global
 *    View) while a form on the page has edits asks first. Forms that also
 *    carry `data-unsaved-guard` warn on any other navigation away
 *    (beforeunload). `data-unsaved-guard="off"` opts a form out of both.
 *
 * A form counts as edited when the user has typed or changed something in it
 * and its fields no longer match what was loaded; submitting it clears that.
 */
(function () {
    'use strict';

    var body = document.body;
    var main = document.getElementById('main-content');
    if (!body || !main) return;

    var orgContext = body.getAttribute('data-org-context');  // null when signed out
    // data-switch-url is the switch URL for client 0; the prefix before it
    // matches every client.
    var switchPrefix = (body.getAttribute('data-switch-url') || '/accounts/switch/0/').replace(/0\/?$/, '');
    var globalUrl = body.getAttribute('data-global-view-url') || '/accounts/switch-global/';
    var leaving = false;

    function isPostForm(form) {
        if ((form.getAttribute('method') || '').toLowerCase() !== 'post') return false;
        if (form.getAttribute('data-unsaved-guard') === 'off') return false;
        try {
            return new URL(form.action || location.href, location.href).origin === location.origin;
        } catch (e) {
            return false;
        }
    }

    function forms() {
        return Array.prototype.filter.call(main.querySelectorAll('form'), isPostForm);
    }

    function snapshot(form) {
        var parts = [];
        try {
            new FormData(form).forEach(function (value, key) {
                if (key === 'csrfmiddlewaretoken' || key === '_org_context') return;
                if (typeof value !== 'string') value = value && value.name ? 'file:' + value.name + ':' + value.size : '';
                parts.push(key + '=' + value);
            });
        } catch (e) { /* a form FormData cannot read is never "dirty" */ }
        return parts.join('&');
    }

    var state = new WeakMap();

    function track(form) {
        if (state.has(form)) return;
        state.set(form, { initial: snapshot(form), touched: false, submitted: false });
        if (orgContext !== null && !form.querySelector('input[name="_org_context"]')) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = '_org_context';
            input.value = orgContext;
            form.appendChild(input);
        }
    }

    function isDirty(form) {
        var s = state.get(form);
        return !!(s && s.touched && !s.submitted && snapshot(form) !== s.initial);
    }

    function dirtyForms(onlyGuarded) {
        return forms().filter(function (form) {
            if (onlyGuarded && !form.hasAttribute('data-unsaved-guard')) return false;
            return isDirty(form);
        });
    }

    function onEdit(ev) {
        if (!ev.isTrusted) return;
        var form = ev.target && ev.target.form ? ev.target.form : (ev.target.closest && ev.target.closest('form'));
        if (!form || !isPostForm(form)) return;
        track(form);
        state.get(form).touched = true;
    }

    // Forms added after load (and any the first pass missed) are picked up
    // on first interaction; a click is enough, since "remove row" buttons
    // change a form without an input event.
    main.addEventListener('input', onEdit, true);
    main.addEventListener('change', onEdit, true);
    main.addEventListener('click', function (ev) {
        var form = ev.target.closest && ev.target.closest('form');
        if (form && isPostForm(form) && ev.isTrusted && ev.target.closest('button[type="button"]')) {
            track(form);
            state.get(form).touched = true;
        }
    }, true);
    // On window, in the bubble phase: runs after the form's own submit
    // handlers, so a submission one of them cancelled stays "edited".
    window.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (!form || !main.contains(form) || !isPostForm(form)) return;
        track(form);
        if (!ev.defaultPrevented) state.get(form).submitted = true;
    });

    function stampAll() { forms().forEach(track); }
    function refreshUntouched() {
        forms().forEach(function (form) {
            track(form);
            var s = state.get(form);
            if (!s.touched) s.initial = snapshot(form);
        });
    }
    // Stamp the org field as early as possible, so a fast submit carries it;
    // take the baseline again once the page's own scripts have run.
    if (document.readyState !== 'loading') stampAll();
    else document.addEventListener('DOMContentLoaded', stampAll);
    if (document.readyState === 'complete') refreshUntouched();
    else window.addEventListener('load', function () { setTimeout(refreshUntouched, 0); });

    function isSwitchLink(a) {
        var url;
        try { url = new URL(a.href, location.href); } catch (e) { return false; }
        if (url.origin !== location.origin) return false;
        return url.pathname.indexOf(switchPrefix) === 0 || url.pathname === globalUrl;
    }

    function confirmLeave(targetName) {
        var dirty = dirtyForms(false);
        if (!dirty.length) return true;
        var where = targetName ? ' to ' + targetName : '';
        var ok = window.confirm('You have unsaved changes on this page.\n\nSwitching client' + where +
                                ' discards them. Switch anyway?');
        if (ok) leaving = true;
        return ok;
    }

    document.addEventListener('click', function (ev) {
        var a = ev.target.closest && ev.target.closest('a[href]');
        if (!a || !isSwitchLink(a)) return;
        var name = (a.getAttribute('title') || a.textContent || '').trim().replace(/\s+/g, ' ');
        if (!confirmLeave(name)) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
        }
    }, true);

    window.addEventListener('beforeunload', function (ev) {
        if (leaving) return;
        if (dirtyForms(true).length) {
            ev.preventDefault();
            ev.returnValue = '';
        }
    });

    window.ClientSt0rUnsaved = { confirmLeave: confirmLeave, dirtyForms: dirtyForms };
})();
