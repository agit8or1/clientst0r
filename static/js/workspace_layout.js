/* 113.9 Workspace layout: presentation only. <html data-workspace> is
   essentials | standard | advanced. Essentials folds secondary panels behind
   a "More" toggle (content stays in the page and in tab order once opened);
   Standard changes nothing; Advanced also opens the optional <details>
   sections. Nothing here decides what the user may do; the server checks
   every action regardless. */
(function () {
  'use strict';
  var level = document.documentElement.getAttribute('data-workspace') || 'standard';
  if (level === 'standard') return;
  var FOLD = {
    ticket: ['ticketFollowup', 'ticketReminders', 'ticketCc', 'closeout-checklist', 'ticket-site-card', 'time-charges'],
    mywork: ['mw-waiting', 'mw-recent-devices', 'mw-maintenance', 'mw-remote', 'mw-ai']
  };
  var page = document.getElementById('mw-open') ? 'mywork' : (document.getElementById('conversation') ? 'ticket' : '');
  if (!page) return;

  function fold(card) {
    var header = card.querySelector(':scope > .card-header');
    if (!header) return;
    var rest = Array.prototype.filter.call(card.children, function (c) { return c !== header; });
    if (!rest.length) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-link ms-auto py-0';
    btn.setAttribute('aria-expanded', 'false');
    btn.textContent = 'More';
    function set(open) {
      rest.forEach(function (c) { c.hidden = !open; if (open) c.style.removeProperty('display'); else c.style.setProperty('display', 'none', 'important'); });  // utility classes with !important would defeat [hidden] alone
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.textContent = open ? 'Less' : 'More';
    }
    btn.addEventListener('click', function () { set(btn.getAttribute('aria-expanded') !== 'true'); });
    header.appendChild(btn);
    // A link to something inside (#hash) or an error inside keeps it open.
    var open = !!card.querySelector('.is-invalid, .alert-danger') ||
      (location.hash && card.querySelector(location.hash.replace(/[^#\w-]/g, '')) !== null);
    set(open);
  }

  function apply() {
    if (level === 'essentials') {
      FOLD[page].forEach(function (id) { var c = document.getElementById(id); if (c) fold(c); });
    } else if (level === 'advanced') {
      document.querySelectorAll('main details, .container-fluid details').forEach(function (d) { d.open = true; });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply); else apply();
})();
