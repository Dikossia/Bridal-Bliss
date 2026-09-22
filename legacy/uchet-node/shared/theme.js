// ============================================================
// theme.js — переключатель светлой/тёмной темы «Учёт», общий для всех
// модулей. Применяет атрибут data-theme на <html> (CSS-переопределения
// лежат в /shared/theme.css) и сохраняет выбор в localStorage — общий
// для всех модулей, так как все они на одном origin за Nginx.
//
// Подключение в каждом модуле:
//     import { Theme } from '/shared/theme.js';
//     Theme.init();                          // применить сохранённую тему как можно раньше
//     Theme.mountToggle('#theme-toggle-slot'); // отрисовать кнопку-переключатель
// ============================================================

const STORE_KEY = 'uchet.theme.v1';

function getStoredTheme() {
  try {
    const v = localStorage.getItem(STORE_KEY);
    return v === 'dark' || v === 'light' ? v : null;
  } catch {
    return null; // localStorage недоступен (приватный режим и т.п.) — не падаем
  }
}

function storeTheme(theme) {
  try { localStorage.setItem(STORE_KEY, theme); } catch { /* недоступно — не критично */ }
}

function prefersDark() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
}

const SUN_SVG = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>`;
const MOON_SVG = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;

class Theme {
  // Применяет тему максимально рано (до первой отрисовки), чтобы не было
  // мигания светлой темой перед переключением на тёмную.
  static init() {
    const theme = getStoredTheme() || (prefersDark() ? 'dark' : 'light');
    applyTheme(theme);
    return theme;
  }

  static current() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  static toggle() {
    const next = Theme.current() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    storeTheme(next);
    document.querySelectorAll('[data-theme-toggle-btn]').forEach(syncButton);
    return next;
  }

  // Рисует кнопку-переключатель (иконка солнце/луна) в указанный контейнер.
  static mountToggle(target) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) { console.warn('[theme] контейнер для переключателя не найден:', target); return; }

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-toggle-btn';
    btn.setAttribute('data-theme-toggle-btn', '');
    btn.setAttribute('aria-label', 'Переключить тему');
    btn.title = 'Переключить тему';
    btn.addEventListener('click', () => Theme.toggle());

    el.appendChild(btn);
    syncButton(btn);
  }
}

function syncButton(btn) {
  const isDark = Theme.current() === 'dark';
  btn.innerHTML = isDark ? SUN_SVG : MOON_SVG;
  btn.title = isDark ? 'Включить светлую тему' : 'Включить тёмную тему';
}

export { Theme };
