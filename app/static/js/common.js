/* ═══════════════════════════════════════════════════════════
   PlagiarismGuard — Common Utilities
   Shared helpers used on every page
   ═══════════════════════════════════════════════════════════ */

/** Tailwind config — must be called before Tailwind CDN initialises */
if (typeof tailwind !== 'undefined') {
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          bg:       '#0f1117',
          surface:  '#1a1d27',
          surface2: '#242836',
          border:   '#2e3348',
          txt:      '#e1e4ed',
          muted:    '#8b8fa3',
          accent:   '#6c5ce7',
          'accent-l':'#a29bfe',
          ok:       '#00b894',
          warn:     '#fdcb6e',
          danger:   '#e17055',
        }
      }
    }
  };
}

/** HTML-escape a string to prevent XSS */
function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

/** Score → colour mapping */
function scoreColor(s) {
  if (s < 30) return '#00b894';
  if (s < 60) return '#fdcb6e';
  return '#e17055';
}

/** Format bytes to human readable */
function fmtBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(1) + ' MB';
}

/* --- Toast notification --- */
function showToast(msg, type) {
  let t = document.getElementById('toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'toast';
    t.className = 'fixed bottom-6 right-6 px-5 py-3 rounded-lg text-sm font-medium shadow-lg transition-all duration-300 z-50 max-w-sm translate-y-20 opacity-0 pointer-events-none';
    document.body.appendChild(t);
  }
  t.textContent = msg || 'Done!';
  t.className = 'fixed bottom-6 right-6 px-5 py-3 rounded-lg text-sm font-medium shadow-lg transition-all duration-300 z-50 max-w-sm';
  if (type === 'error')        t.classList.add('bg-danger', 'text-white');
  else if (type === 'warning') t.classList.add('bg-warn', 'text-gray-900');
  else if (type === 'success') t.classList.add('bg-ok', 'text-white');
  else                         t.classList.add('bg-accent', 'text-white');
  t.classList.remove('translate-y-20', 'opacity-0', 'pointer-events-none');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add('translate-y-20', 'opacity-0', 'pointer-events-none'), 3000);
}

/* --- Theme toggle (dark / light) --- */
function initTheme() {
  const saved = localStorage.getItem('pg_theme');
  let isLight;
  if (saved) {
    isLight = saved === 'light';
  } else {
    isLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  }
  if (isLight) {
    document.documentElement.classList.add('light');
  }
  updateThemeIcons(isLight);
}

function toggleTheme() {
  const isLight = document.documentElement.classList.toggle('light');
  localStorage.setItem('pg_theme', isLight ? 'light' : 'dark');
  updateThemeIcons(isLight);
}

function updateThemeIcons(isLight) {
  document.querySelectorAll('.theme-icon-moon').forEach(el => el.classList.toggle('hidden', isLight));
  document.querySelectorAll('.theme-icon-sun').forEach(el => el.classList.toggle('hidden', !isLight));
}

// Auto-init theme on load
initTheme();

/* --- Authenticated API helper with auto-refresh --- */
async function apiFetch(url, options = {}) {
  const token = localStorage.getItem('pg_token');
  if (!options.headers) options.headers = {};
  if (token) options.headers['Authorization'] = 'Bearer ' + token;

  let res = await fetch(url, options);

  // If 401, try refreshing the token
  if (res.status === 401) {
    const refreshToken = localStorage.getItem('pg_refresh_token');
    if (refreshToken) {
      try {
        const rr = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (rr.ok) {
          const rd = await rr.json();
          if (rd.token) {
            localStorage.setItem('pg_token', rd.token);
            options.headers['Authorization'] = 'Bearer ' + rd.token;
            res = await fetch(url, options);
          }
        } else {
          // Refresh failed — clear tokens and redirect to login
          localStorage.removeItem('pg_token');
          localStorage.removeItem('pg_refresh_token');
          localStorage.removeItem('pg_user');
          window.location.href = '/login';
          return res;
        }
      } catch (_) {
        // Network error on refresh — surface the original 401
      }
    }
  }
  return res;
}

/** Safely parse a JSON string with basic shape validation.
 *  Returns null if parsing fails or required keys are missing.
 */
function safeParse(jsonStr, requiredKeys = []) {
  try {
    const obj = JSON.parse(jsonStr);
    if (typeof obj !== 'object' || obj === null) return null;
    for (const k of requiredKeys) {
      if (!(k in obj)) return null;
    }
    return obj;
  } catch(_) {
    return null;
  }
}

/* ═══════════════════════════════════════════════════════════
   Onboarding Tour System
   ═══════════════════════════════════════════════════════════ */
var PG_TOUR_KEY = 'pg_tour_completed';

function startOnboardingTour(steps) {
  if (localStorage.getItem(PG_TOUR_KEY)) return;
  if (!steps || !steps.length) return;
  var idx = 0;

  var overlay = document.createElement('div');
  overlay.className = 'tour-overlay';
  overlay.id = 'tourOverlay';
  document.body.appendChild(overlay);

  var spotlight = document.createElement('div');
  spotlight.className = 'tour-spotlight';
  document.body.appendChild(spotlight);

  var card = document.createElement('div');
  card.className = 'tour-card';
  document.body.appendChild(card);

  function show(i) {
    var step = steps[i];
    var target = document.querySelector(step.target);
    if (!target) { finish(); return; }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });

    setTimeout(function() {
      var rect = target.getBoundingClientRect();
      var pad = 8;
      spotlight.style.top = (rect.top - pad + window.scrollY) + 'px';
      spotlight.style.left = (rect.left - pad) + 'px';
      spotlight.style.width = (rect.width + pad * 2) + 'px';
      spotlight.style.height = (rect.height + pad * 2) + 'px';
      card.style.top = (rect.bottom + window.scrollY + 16) + 'px';
      card.style.left = Math.max(16, Math.min(rect.left, window.innerWidth - 360)) + 'px';

      var dots = steps.map(function(_, di) {
        return '<span class="tour-dot' + (di === i ? ' active' : '') + '"></span>';
      }).join('');

      card.innerHTML =
        '<h3>' + step.title + '</h3><p>' + step.text + '</p>' +
        '<div class="flex items-center justify-between mt-3"><div class="tour-dots">' + dots + '</div>' +
        '<div class="flex gap-2">' +
        (i > 0 ? '<button onclick="window._tourPrev()" class="text-xs text-muted hover:text-txt px-2 py-1">Back</button>' : '') +
        '<button onclick="window._tourNext()" class="text-xs px-4 py-1.5 bg-accent text-white rounded-lg font-semibold hover:bg-[#5a4bd1]">' +
        (i === steps.length - 1 ? 'Get Started!' : 'Next &rarr;') + '</button>' +
        '<button onclick="window._tourSkip()" class="text-xs text-muted hover:text-danger px-2 py-1">Skip</button>' +
        '</div></div>';
    }, 300);
  }

  function finish() {
    localStorage.setItem(PG_TOUR_KEY, '1');
    overlay.remove(); spotlight.remove(); card.remove();
  }

  window._tourNext = function() { idx++; if (idx >= steps.length) finish(); else show(idx); };
  window._tourPrev = function() { if (idx > 0) { idx--; show(idx); } };
  window._tourSkip = finish;

  show(0);
}

/* ═══════════════════════════════════════════════════════════
   Success Celebration (confetti burst)
   ═══════════════════════════════════════════════════════════ */
function celebrate(cx, cy) {
  var colors = ['#6c5ce7','#00b894','#fdcb6e','#e17055','#a29bfe','#4ECDC4','#fd79a8'];
  for (var i = 0; i < 18; i++) {
    var p = document.createElement('div');
    p.className = 'celebration-particle';
    p.style.left = cx + 'px';
    p.style.top = cy + 'px';
    p.style.background = colors[i % colors.length];
    var sz = (6 + Math.random() * 8) + 'px';
    p.style.width = sz; p.style.height = sz;
    var angle = (Math.PI * 2 / 18) * i;
    var dist = 60 + Math.random() * 80;
    var tx = Math.cos(angle) * dist, ty = Math.sin(angle) * dist - 40;
    p.animate([
      { transform: 'scale(0) translate(0,0)', opacity: 1 },
      { transform: 'scale(1.2) translate(' + (tx*.6) + 'px,' + (ty*.6) + 'px)', opacity: .8, offset: .5 },
      { transform: 'scale(0) translate(' + tx + 'px,' + ty + 'px)', opacity: 0 }
    ], { duration: 600 + Math.random() * 400, easing: 'cubic-bezier(.16,1,.3,1)' });
    document.body.appendChild(p);
    setTimeout(function() { p.remove(); }, 1200);
  }
}

/* ═══════════════════════════════════════════════════════════
   Keyboard Shortcuts Manager
   ═══════════════════════════════════════════════════════════ */
var _shortcuts = [];
function registerShortcut(key, ctrl, description, handler) {
  _shortcuts.push({ key: key.toLowerCase(), ctrl: ctrl, description: description, handler: handler });
}

document.addEventListener('keydown', function(e) {
  var tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;
  var ctrl = e.ctrlKey || e.metaKey;
  for (var i = 0; i < _shortcuts.length; i++) {
    var s = _shortcuts[i];
    if (s.key === e.key.toLowerCase() && s.ctrl === ctrl) {
      e.preventDefault(); s.handler(); return;
    }
  }
});

function showShortcutsHelp() {
  var modal = document.getElementById('shortcutsModal');
  if (modal) { modal.remove(); return; }
  modal = document.createElement('div');
  modal.id = 'shortcutsModal';
  modal.className = 'fixed inset-0 z-[10001] flex items-center justify-center bg-black/50 backdrop-blur-sm';
  modal.onclick = function(e) { if (e.target === modal) modal.remove(); };
  var rows = _shortcuts.map(function(s) {
    return '<div class="flex items-center justify-between py-2 border-b border-border/30">' +
      '<span class="text-sm">' + s.description + '</span>' +
      '<span class="kbd text-xs">' + (s.ctrl ? 'Ctrl+' : '') + s.key.toUpperCase() + '</span></div>';
  }).join('');
  modal.innerHTML = '<div class="bg-surface border border-border rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl">' +
    '<div class="flex items-center justify-between mb-4"><h3 class="text-lg font-bold">Keyboard Shortcuts</h3>' +
    '<button onclick="this.closest(\'#shortcutsModal\').remove()" class="text-muted hover:text-txt text-xl">&times;</button></div>' +
    rows + '<p class="text-xs text-muted mt-3 text-center">Press <span class="kbd">?</span> to toggle</p></div>';
  document.body.appendChild(modal);
}

/* ═══════════════════════════════════════════════════════════
   Error with Retry Button Helper
   ═══════════════════════════════════════════════════════════ */
function showErrorWithRetry(containerId, message, retryFnName) {
  var el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = '<div class="flex items-center justify-between gap-3">' +
    '<span>\u26A0 ' + esc(message) + '</span>' +
    (retryFnName ? '<button onclick="document.getElementById(\'' + containerId + '\').classList.add(\'hidden\');' + retryFnName + '()" class="shrink-0 px-3 py-1.5 bg-danger/20 hover:bg-danger/30 text-danger border border-danger/30 rounded-lg text-xs font-semibold transition-colors">Retry</button>' : '') +
    '</div>';
  el.classList.remove('hidden');
}
