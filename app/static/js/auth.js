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
  try {
    return JSON.parse(localStorage.getItem('pg_user'));
  } catch {
    return null;
  }
}

/** Log out — clear storage and redirect to landing */
function handleLogout() {
  localStorage.removeItem('pg_token');
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

/* --- Fetch interceptor: auto-attach Bearer token to /api/ calls --- */
const _origFetch = window.fetch;
window.fetch = function (input, init) {
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
  }
  return _origFetch.call(this, input, init);
};
