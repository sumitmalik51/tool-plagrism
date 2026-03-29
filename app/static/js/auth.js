/* ═══════════════════════════════════════════════════════════
   PlagiarismGuard — Auth & Fetch Interceptor
   Shared across all pages that need authentication
   ═══════════════════════════════════════════════════════════ */

/** Shorthand DOM helper (also in common.js but duplicated here for independence) */
const $ = (id) => document.getElementById(id);

/** Get authorization headers for API calls */
function _authHeaders() {
  const token = localStorage.getItem('pg_token');
  return token ? { Authorization: 'Bearer ' + token } : {};
}

/** Check if user is currently authenticated */
function isLoggedIn() {
  return !!localStorage.getItem('pg_token');
}

/** Get the stored user object, or null */
function getUser() {
  return safeParse(localStorage.getItem('pg_user'), ['id', 'email']);
}

/** Log out — clear storage and redirect to landing */
function handleLogout() {
  localStorage.removeItem('pg_token');
  localStorage.removeItem('pg_refresh_token');
  localStorage.removeItem('pg_user');
  window.location.href = '/';
}

/** Redirect to login if not authenticated (for protected pages) */
function requireAuth() {
  if (!isLoggedIn()) {
    window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
    return false;
  }
  return true;
}

/* --- Fetch interceptor: auto-attach Bearer token + auto-refresh on 401 --- */
const _origFetch = window.fetch;
let _refreshing = null; // singleton refresh promise

async function _refreshAccessToken() {
  const rt = localStorage.getItem('pg_refresh_token');
  if (!rt) return false;
  try {
    const res = await _origFetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (res.ok) {
      const d = await res.json();
      if (d.token) { localStorage.setItem('pg_token', d.token); return true; }
    }
  } catch(_) {}
  // Refresh failed — clear everything
  localStorage.removeItem('pg_token');
  localStorage.removeItem('pg_refresh_token');
  localStorage.removeItem('pg_user');
  return false;
}

window.fetch = async function (input, init) {
  const url = typeof input === 'string' ? input : input.url;
  if (url.startsWith('/api/')) {
    init = init || {};
    init.headers = init.headers || {};
    const token = localStorage.getItem('pg_token');
    if (token) {
      if (init.headers instanceof Headers) {
        if (!init.headers.has('Authorization')) {
          init.headers.set('Authorization', 'Bearer ' + token);
        }
      } else {
        if (!init.headers['Authorization']) {
          init.headers['Authorization'] = 'Bearer ' + token;
        }
      }
    }

    let res = await _origFetch.call(this, input, init);

    // Auto-refresh on 401 (not for auth endpoints themselves)
    if (res.status === 401 && !url.includes('/auth/refresh') && !url.includes('/auth/login')) {
      if (!_refreshing) _refreshing = _refreshAccessToken().finally(() => { _refreshing = null; });
      const ok = await _refreshing;
      if (ok) {
        // Retry with new token
        const newToken = localStorage.getItem('pg_token');
        if (init.headers instanceof Headers) {
          init.headers.set('Authorization', 'Bearer ' + newToken);
        } else {
          init.headers['Authorization'] = 'Bearer ' + newToken;
        }
        res = await _origFetch.call(this, input, init);
      }
    }
    return res;
  }
  return _origFetch.call(this, input, init);
};
