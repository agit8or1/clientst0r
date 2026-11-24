/**
 * Clientst0r Popup — Passwords | Assets | Notifications
 */

// ─── Utilities ────────────────────────────────────────────────────────────────

function msg(action, payload = {}) {
  return chrome.runtime.sendMessage({ action, payload });
}

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const original = btn.textContent;
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = original;
      btn.classList.remove('copied');
    }, 1500);
  } catch (_) {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

function openInTab(url) {
  chrome.tabs.create({ url });
}

function getCurrentTabHostname() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      try {
        const u = new URL(tabs[0].url);
        resolve(u.hostname.replace(/^www\./, ''));
      } catch (_) {
        resolve('');
      }
    });
  });
}

function getServerUrl() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['serverUrl'], ({ serverUrl }) => resolve(serverUrl || ''));
  });
}

// ─── Drag-to-reorder ─────────────────────────────────────────────────────────

function enableDragReorder(listEl, storageKey) {
  let dragged = null;

  listEl.addEventListener('dragstart', (e) => {
    dragged = e.target.closest('[data-id]');
    if (dragged) dragged.classList.add('dragging');
  });

  listEl.addEventListener('dragend', (e) => {
    const el = e.target.closest('[data-id]');
    if (el) el.classList.remove('dragging');
    dragged = null;
    saveOrder(listEl, storageKey);
  });

  listEl.addEventListener('dragover', (e) => {
    e.preventDefault();
    const target = e.target.closest('[data-id]');
    if (target && dragged && target !== dragged) {
      const rect = target.getBoundingClientRect();
      const mid = rect.top + rect.height / 2;
      if (e.clientY < mid) {
        listEl.insertBefore(dragged, target);
      } else {
        listEl.insertBefore(dragged, target.nextSibling);
      }
    }
  });
}

function saveOrder(listEl, storageKey) {
  const ids = [...listEl.querySelectorAll('[data-id]')].map((el) => el.dataset.id);
  chrome.storage.sync.set({ [storageKey]: ids });
}

async function applySavedOrder(listEl, storageKey) {
  return new Promise((resolve) => {
    chrome.storage.sync.get([storageKey], (result) => {
      const order = result[storageKey];
      if (!order || !order.length) { resolve(); return; }
      const rows = {};
      listEl.querySelectorAll('[data-id]').forEach((el) => { rows[el.dataset.id] = el; });
      order.forEach((id) => {
        if (rows[id]) listEl.appendChild(rows[id]);
      });
      resolve();
    });
  });
}

// ─── Tab switching ────────────────────────────────────────────────────────────

const tabs = document.querySelectorAll('.tab');
const panes = document.querySelectorAll('.pane');
let activeTab = 'passwords';

tabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    tabs.forEach((t) => t.classList.remove('active'));
    panes.forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    const name = tab.dataset.tab;
    document.getElementById(`pane-${name}`).classList.add('active');
    activeTab = name;
  });
});

document.getElementById('openOptionsBtn').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

// ─── Passwords tab ────────────────────────────────────────────────────────────

const pwSearch  = document.getElementById('pwSearch');
const pwListEl  = document.getElementById('pwList');
let pwDebounce  = null;
let allPasswords = [];

async function loadPasswords(query) {
  pwListEl.innerHTML = '<div class="loading"><span class="spinner"></span>Searching…</div>';
  try {
    const result = await msg('searchPasswords', { query });
    if (result.error) throw new Error(result.error);
    allPasswords = result;
    renderPasswords(result);
  } catch (err) {
    pwListEl.innerHTML = `<div class="empty">Error: ${escHtml(err.message)}</div>`;
  }
}

function renderPasswords(list) {
  if (!list.length) {
    pwListEl.innerHTML = '<div class="empty">No passwords found.</div>';
    return;
  }

  pwListEl.innerHTML = '';
  list.forEach((pw) => {
    const row = document.createElement('div');
    row.className = 'pw-row';
    row.dataset.id = pw.id;
    row.draggable = true;

    const isOtp     = pw.password_type === 'otp';
    const isBreach  = pw.is_breached;
    const isExpired = pw.is_expired;
    const isExpiring = pw.expires_at && !isExpired && (new Date(pw.expires_at) - new Date()) < 30 * 86400000;

    const badges = [
      isBreach  ? `<span class="badge badge-breach">Breached</span>` : '',
      isExpired ? `<span class="badge badge-expired">Expired</span>` : '',
      isExpiring? `<span class="badge badge-expiring">Expiring</span>` : '',
      isOtp     ? `<span class="badge badge-otp">OTP</span>` : '',
    ].filter(Boolean).join('');

    row.innerHTML = `
      <span class="pw-drag-handle" title="Drag to reorder">⠿</span>
      <div class="pw-info">
        <div class="pw-title">${escHtml(pw.title)}</div>
        <div class="pw-username">${escHtml(pw.username || '')}</div>
        ${badges ? `<div class="pw-badges">${badges}</div>` : ''}
      </div>
      <div class="pw-actions">
        ${pw.username ? `<button class="icon-btn" data-action="copy-user">User</button>` : ''}
        <button class="icon-btn" data-action="copy-pw">Pass</button>
        ${isOtp ? `<button class="icon-btn" data-action="copy-otp">OTP</button>` : ''}
      </div>
    `;

    // Copy username
    const userBtn = row.querySelector('[data-action="copy-user"]');
    if (userBtn) {
      userBtn.addEventListener('click', () => copyToClipboard(pw.username, userBtn));
    }

    // Copy password
    const pwBtn = row.querySelector('[data-action="copy-pw"]');
    pwBtn.addEventListener('click', async () => {
      pwBtn.disabled = true;
      try {
        const res = await msg('revealPassword', { id: pw.id });
        if (res.error) throw new Error(res.error);
        await copyToClipboard(res.password, pwBtn);
      } catch (err) {
        pwBtn.textContent = 'Error';
        setTimeout(() => { pwBtn.textContent = 'Pass'; }, 1500);
      } finally {
        pwBtn.disabled = false;
      }
    });

    // Copy OTP
    const otpBtn = row.querySelector('[data-action="copy-otp"]');
    if (otpBtn) {
      otpBtn.addEventListener('click', async () => {
        otpBtn.disabled = true;
        try {
          const res = await msg('getOtp', { id: pw.id });
          if (res.error) throw new Error(res.error);
          await copyToClipboard(res.otp, otpBtn);
        } catch (err) {
          otpBtn.textContent = 'Error';
          setTimeout(() => { otpBtn.textContent = 'OTP'; }, 1500);
        } finally {
          otpBtn.disabled = false;
        }
      });
    }

    pwListEl.appendChild(row);
  });

  enableDragReorder(pwListEl, 'pwOrder');
  applySavedOrder(pwListEl, 'pwOrder');
}

pwSearch.addEventListener('input', () => {
  clearTimeout(pwDebounce);
  pwDebounce = setTimeout(() => loadPasswords(pwSearch.value.trim()), 300);
});

document.getElementById('pwAddNew').addEventListener('click', async (e) => {
  e.preventDefault();
  const url = await getServerUrl();
  if (url) openInTab(`${url}/vault/create/`);
});

// ─── Assets tab ───────────────────────────────────────────────────────────────

const assetSearch  = document.getElementById('assetSearch');
const assetListEl  = document.getElementById('assetList');
let assetDebounce  = null;

async function loadAssets(query) {
  assetListEl.innerHTML = '<div class="loading"><span class="spinner"></span>Searching…</div>';
  try {
    const result = await msg('searchAssets', { query });
    if (result.error) throw new Error(result.error);
    renderAssets(result);
  } catch (err) {
    assetListEl.innerHTML = `<div class="empty">Error: ${escHtml(err.message)}</div>`;
  }
}

function renderAssets(list) {
  if (!list.length) {
    assetListEl.innerHTML = '<div class="empty">No assets found.</div>';
    return;
  }

  assetListEl.innerHTML = '';
  list.forEach((asset) => {
    const row = document.createElement('div');
    row.className = 'asset-row';
    row.dataset.id = asset.id;
    row.draggable = true;

    const meta = [asset.asset_type, asset.ip_address || asset.hostname].filter(Boolean).join(' · ');
    const reorder = asset.needs_reorder;

    row.innerHTML = `
      <span class="asset-drag-handle" title="Drag to reorder">⠿</span>
      <div class="asset-info">
        <div class="asset-name">
          ${escHtml(asset.name)}
          ${reorder ? `<span class="badge badge-reorder">↩ Reorder</span>` : ''}
        </div>
        <div class="asset-meta">${escHtml(meta)}</div>
      </div>
      <div class="pw-actions">
        <button class="icon-btn${reorder ? ' active' : ''}" data-action="toggle-reorder" title="${reorder ? 'Clear reorder flag' : 'Mark for reorder'}">
          ${reorder ? '↩ Flagged' : '↩ Reorder'}
        </button>
      </div>
    `;

    const reorderBtn = row.querySelector('[data-action="toggle-reorder"]');
    reorderBtn.addEventListener('click', async () => {
      reorderBtn.disabled = true;
      const newVal = !asset.needs_reorder;
      try {
        const res = await msg('setNeedsReorder', { id: asset.id, value: newVal });
        if (res.error) throw new Error(res.error);
        asset.needs_reorder = newVal;
        reorderBtn.textContent = newVal ? '↩ Flagged' : '↩ Reorder';
        reorderBtn.classList.toggle('active', newVal);
        // Update badge in name
        const namEl = row.querySelector('.asset-name');
        const existing = namEl.querySelector('.badge-reorder');
        if (newVal && !existing) {
          namEl.insertAdjacentHTML('beforeend', '<span class="badge badge-reorder">↩ Reorder</span>');
        } else if (!newVal && existing) {
          existing.remove();
        }
      } catch (err) {
        reorderBtn.textContent = 'Error';
        setTimeout(() => { reorderBtn.textContent = asset.needs_reorder ? '↩ Flagged' : '↩ Reorder'; }, 1500);
      } finally {
        reorderBtn.disabled = false;
      }
    });

    assetListEl.appendChild(row);
  });

  enableDragReorder(assetListEl, 'assetOrder');
  applySavedOrder(assetListEl, 'assetOrder');
}

assetSearch.addEventListener('input', () => {
  clearTimeout(assetDebounce);
  assetDebounce = setTimeout(() => loadAssets(assetSearch.value.trim()), 300);
});

document.getElementById('assetAddNew').addEventListener('click', async (e) => {
  e.preventDefault();
  const url = await getServerUrl();
  if (url) openInTab(`${url}/assets/create/`);
});

// ─── Notifications tab ────────────────────────────────────────────────────────

const notifListEl = document.getElementById('notifList');
const notifBadge  = document.getElementById('notifBadge');

async function loadNotifications() {
  notifListEl.innerHTML = '<div class="loading"><span class="spinner"></span>Loading…</div>';
  try {
    const result = await msg('getNotifications');
    if (result.error) throw new Error(result.error);
    renderNotifications(result);
  } catch (err) {
    notifListEl.innerHTML = `<div class="empty">Error: ${escHtml(err.message)}</div>`;
  }
}

function renderNotifications({ breached = [], expiring = [], expired = [] }) {
  const total = breached.length + expired.length;
  if (total > 0) {
    notifBadge.textContent = total;
    notifBadge.style.display = '';
  } else {
    notifBadge.style.display = 'none';
  }

  if (!breached.length && !expiring.length && !expired.length) {
    notifListEl.innerHTML = '<div class="empty">No alerts. All passwords look good!</div>';
    return;
  }

  notifListEl.innerHTML = '';

  function section(title, items, cls) {
    if (!items.length) return;
    const h = document.createElement('div');
    h.className = 'notif-section';
    h.innerHTML = `<h4>${title}</h4>`;
    notifListEl.appendChild(h);
    items.forEach((p) => {
      const item = document.createElement('div');
      item.className = `notif-item ${cls}`;
      item.innerHTML = `<span class="dot"></span><span>${escHtml(p.title)}</span>`;
      notifListEl.appendChild(item);
    });
  }

  section('Breached Passwords', breached, 'breach');
  section('Expired Passwords', expired, 'expired');
  section('Expiring Within 30 Days', expiring, 'expiring');
}

document.getElementById('notifRefresh').addEventListener('click', (e) => {
  e.preventDefault();
  loadNotifications();
});

// ─── Init ─────────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function init() {
  // Auto-search passwords for current tab hostname
  const hostname = await getCurrentTabHostname();
  if (hostname) pwSearch.value = hostname;
  loadPasswords(hostname);
  loadAssets('');
  loadNotifications();
}

init();
