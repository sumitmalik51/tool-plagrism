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
