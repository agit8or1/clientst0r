/**
 * Clientst0r Browser Extension — Service Worker
 *
 * Handles all API communication so:
 *  - Content scripts never touch the API key
 *  - CORS is bypassed (host_permissions covers all URLs)
 */

// ─── Config helpers ──────────────────────────────────────────────────────────

async function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['serverUrl', 'apiKey'], (result) => {
      resolve({
        serverUrl: (result.serverUrl || '').replace(/\/$/, ''),
        apiKey: result.apiKey || '',
      });
    });
  });
}

// ─── API client ──────────────────────────────────────────────────────────────

async function apiRequest(path, options = {}) {
  const { serverUrl, apiKey } = await getConfig();
  if (!serverUrl || !apiKey) {
    throw new Error('Clientst0r not configured. Open the options page to set your server URL and API key.');
  }

  const url = `${serverUrl}${path}`;
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${apiKey}`,
  };

  const response = await fetch(url, { ...options, headers: { ...headers, ...(options.headers || {}) } });

  if (!response.ok) {
    let msg = `API error ${response.status}`;
    try {
      const data = await response.json();
      msg = data.detail || data.error || msg;
    } catch (_) { /* ignore */ }
    throw new Error(msg);
  }

  // Some PATCH responses may be 204 No Content
  if (response.status === 204) return {};
  return response.json();
}

// ─── Message router ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message).then(sendResponse).catch((err) => {
    sendResponse({ error: err.message });
  });
  return true; // keep channel open for async response
});

async function handleMessage(message) {
  const { action, payload } = message;

  switch (action) {
    // ── Options ────────────────────────────────────────────────────────────
    case 'testConnection': {
      const { serverUrl, apiKey } = payload;
      // temporarily use the provided creds without saving
      const response = await fetch(`${serverUrl.replace(/\/$/, '')}/api/organizations/`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      // data may be paginated {results:[…]} or raw array
      const orgs = data.results || data;
      return { ok: true, orgs };
    }

    // ── Passwords ──────────────────────────────────────────────────────────
    case 'searchPasswords': {
      const q = encodeURIComponent(payload.query || '');
      const data = await apiRequest(`/api/passwords/?search=${q}&ordering=title`);
      return data.results || data;
    }

    case 'revealPassword': {
      const data = await apiRequest(`/api/passwords/${payload.id}/?reveal=true`);
      return { password: data.password };
    }

    case 'getOtp': {
      const data = await apiRequest(`/api/passwords/${payload.id}/otp/`);
      return { otp: data.otp };
    }

    // ── Assets ─────────────────────────────────────────────────────────────
    case 'searchAssets': {
      const q = encodeURIComponent(payload.query || '');
      const data = await apiRequest(`/api/assets/?search=${q}&ordering=name`);
      return data.results || data;
    }

    case 'setNeedsReorder': {
      const data = await apiRequest(`/api/assets/${payload.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ needs_reorder: payload.value }),
      });
      return data;
    }

    // ── Notifications ──────────────────────────────────────────────────────
    case 'getNotifications': {
      return await fetchNotifications();
    }

    default:
      throw new Error(`Unknown action: ${action}`);
  }
}

// ─── Notifications ───────────────────────────────────────────────────────────

async function fetchNotifications() {
  const data = await apiRequest('/api/passwords/?ordering=title');
  const passwords = data.results || data;

  const now = new Date();
  const in30Days = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);

  const breached = passwords.filter((p) => p.is_breached);
  const expiring = passwords.filter((p) => {
    if (!p.expires_at) return false;
    const exp = new Date(p.expires_at);
    return exp <= in30Days && exp >= now;
  });
  const expired = passwords.filter((p) => p.is_expired);

  const count = breached.length + expired.length;

  // Update badge
  chrome.action.setBadgeText({ text: count > 0 ? String(count) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#dc3545' });

  return { breached, expiring, expired };
}

// ─── Alarms ──────────────────────────────────────────────────────────────────

chrome.alarms.create('refreshNotifications', { periodInMinutes: 360 }); // 6 h

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'refreshNotifications') {
    getConfig().then(({ apiKey }) => {
      if (apiKey) fetchNotifications().catch(() => {});
    });
  }
});

// Run once on install / startup
chrome.runtime.onInstalled.addListener(() => {
  getConfig().then(({ apiKey }) => {
    if (apiKey) fetchNotifications().catch(() => {});
  });
});
