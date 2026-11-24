/**
 * Clientst0r Content Script — Autofill
 *
 * Detects login forms and injects a credential suggestion bar.
 * The API key never touches this script; everything goes through
 * the service worker via chrome.runtime.sendMessage.
 */

(function () {
  'use strict';

  // Only run once per page
  if (window.__clientst0rInjected) return;
  window.__clientst0rInjected = true;

  // ── Helpers ──────────────────────────────────────────────────────────────

  function getCurrentHostname() {
    return location.hostname.replace(/^www\./, '');
  }

  function findLoginForm() {
    const pwFields = [...document.querySelectorAll('input[type="password"]')]
      .filter((el) => el.offsetParent !== null); // visible only
    if (!pwFields.length) return null;

    const pw = pwFields[0];
    // Look for adjacent username field (preceding input[type=text/email])
    const form = pw.form || pw.closest('form');
    let user = null;
    if (form) {
      user = form.querySelector('input[type="text"], input[type="email"], input[name*="user"], input[name*="email"], input[id*="user"], input[id*="email"]');
    }
    if (!user) {
      // Walk backwards in the DOM
      let el = pw.previousElementSibling;
      while (el) {
        if (el.tagName === 'INPUT' && ['text', 'email', ''].includes(el.type)) {
          user = el;
          break;
        }
        el = el.previousElementSibling;
      }
    }
    return { pwField: pw, userField: user };
  }

  // ── Suggestion bar ────────────────────────────────────────────────────────

  let barEl = null;

  function createBar(credentials, pwField, userField) {
    removeBar();

    barEl = document.createElement('div');
    barEl.id = '__clientst0r_bar';
    barEl.setAttribute('style', `
      position: fixed;
      z-index: 2147483647;
      top: 8px;
      right: 8px;
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 8px;
      width: 280px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 12px;
      color: #c9d1d9;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    `);

    const header = document.createElement('div');
    header.setAttribute('style', 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;');
    header.innerHTML = `
      <span style="font-weight:700;color:#58a6ff;font-size:11px;">Clientst0r — Select credential</span>
      <button id="__cs_close" style="background:none;border:none;color:#8b949e;cursor:pointer;font-size:14px;line-height:1;padding:0 2px;">×</button>
    `;
    barEl.appendChild(header);

    credentials.slice(0, 5).forEach((cred) => {
      const btn = document.createElement('button');
      btn.setAttribute('style', `
        display:block;width:100%;text-align:left;background:#0d1117;
        border:1px solid #30363d;border-radius:5px;padding:5px 8px;
        margin-bottom:4px;cursor:pointer;color:#c9d1d9;font-size:12px;
        transition:background 0.1s;
      `);
      btn.innerHTML = `<strong>${escHtml(cred.title)}</strong><br><span style="color:#8b949e;">${escHtml(cred.username || '')}</span>`;
      btn.addEventListener('mouseenter', () => { btn.style.background = '#21262d'; });
      btn.addEventListener('mouseleave', () => { btn.style.background = '#0d1117'; });
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        fillCredential(cred, pwField, userField);
      });
      barEl.appendChild(btn);
    });

    document.body.appendChild(barEl);

    document.getElementById('__cs_close').addEventListener('click', removeBar);
  }

  function removeBar() {
    if (barEl) { barEl.remove(); barEl = null; }
  }

  async function fillCredential(cred, pwField, userField) {
    try {
      const res = await chrome.runtime.sendMessage({ action: 'revealPassword', payload: { id: cred.id } });
      if (res.error) throw new Error(res.error);

      if (userField && cred.username) {
        setNativeValue(userField, cred.username);
      }
      setNativeValue(pwField, res.password);
      removeBar();
    } catch (err) {
      console.warn('[Clientst0r] Fill failed:', err.message);
    }
  }

  // React/Vue-safe value setter
  function setNativeValue(el, value) {
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (nativeSetter) {
      nativeSetter.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function escHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // ── Detection ─────────────────────────────────────────────────────────────

  let detected = false;

  async function detectAndInject() {
    if (detected) return;
    const fields = findLoginForm();
    if (!fields) return;
    detected = true;

    const hostname = getCurrentHostname();
    if (!hostname) return;

    try {
      const credentials = await chrome.runtime.sendMessage({
        action: 'searchPasswords',
        payload: { query: hostname },
      });
      if (!credentials || credentials.error || !credentials.length) return;

      // Show bar on focus of either field
      function onFocus() {
        createBar(credentials, fields.pwField, fields.userField);
      }

      fields.pwField.addEventListener('focus', onFocus);
      if (fields.userField) fields.userField.addEventListener('focus', onFocus);
    } catch (_) {
      // Extension not configured or no matches — silent
    }
  }

  // Run on idle + watch for dynamic form rendering
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    detectAndInject();
  } else {
    document.addEventListener('DOMContentLoaded', detectAndInject);
  }

  // MutationObserver for SPAs
  const observer = new MutationObserver(() => {
    if (!detected) detectAndInject();
  });
  observer.observe(document.body || document.documentElement, { childList: true, subtree: true });

  // Close bar on outside click
  document.addEventListener('click', (e) => {
    if (barEl && !barEl.contains(e.target)) removeBar();
  }, true);
})();
