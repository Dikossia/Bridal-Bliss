// ============================================================
// sidebar.js — ОБЩИЙ левый сайдбар приложения «Учёт».
// Один класс на все модули. Каждый модуль подключает этот файл и вызывает:
//     import { Sidebar } from '/shared/sidebar.js';
//     Sidebar.mount('#uchet-sidebar', { active: 'report' });
// Отличается между модулями только ключ active. Наследование не нужно —
// поведение одно, структура меню берётся из общего nav-config.js.
//
// Возможности:
//   • Сворачивание/разворачивание по кнопке на границе сайдбара.
//   • Изменение ширины перетаскиванием (между MIN и MAX), с сохранением.
//   • Иерархия: разделы с детьми раскрываются/сворачиваются.
//   • Подсветка активного пункта; группа активного пункта раскрывается сама.
//   • Состояние (ширина, свёрнутость, открытые группы) хранится в localStorage
//     и общее для всех модулей (один origin за Nginx).
// ============================================================

import { NAV, HOME_HREF } from './nav-config.js';

// --- Константы оформления (НЕ пользовательские) ---
const MIN_WIDTH = 200;   // минимальная ширина развёрнутого сайдбара, px
const MAX_WIDTH = 480;   // максимальная ширина, px
const DEFAULT_WIDTH = 260;
const COLLAPSED_WIDTH = 64;
const STORE_KEY = 'uchet.sidebar.v1';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

class Sidebar {
  static mount(target, opts = {}) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) { console.warn('[sidebar] контейнер не найден:', target); return null; }
    return new Sidebar(el, opts);
  }

  constructor(el, { active = '' } = {}) {
    this.el = el;
    this.active = active;
    this.state = this.loadState();

    // Если активный пункт — ребёнок группы, эта группа должна быть открыта.
    const parent = this.parentGroupOf(active);
    if (parent) this.state.open.add(parent);

    this.render();
    this.applyState();
    this.bind();
  }

  // ---------- Состояние / хранилище ----------
  loadState() {
    const def = { width: DEFAULT_WIDTH, collapsed: false, open: new Set() };
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return def;
      const s = JSON.parse(raw);
      return {
        width: Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Number(s.width) || DEFAULT_WIDTH)),
        collapsed: !!s.collapsed,
        open: new Set(Array.isArray(s.open) ? s.open : []),
      };
    } catch { return def; }
  }

  saveState() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        width: this.state.width,
        collapsed: this.state.collapsed,
        open: Array.from(this.state.open),
      }));
    } catch { /* приватный режим и т.п. — не критично */ }
  }

  parentGroupOf(key) {
    for (const node of NAV) {
      if (node.children && node.children.some((c) => c.key === key)) return node.key;
    }
    return null;
  }

  // ---------- Разметка ----------
  render() {
    this.el.classList.add('uchet-sidebar');
    this.el.innerHTML = `
      <div class="us-brand">
        <a href="${esc(HOME_HREF)}" class="us-logo" title="На главную">Учёт</a>
      </div>
      <nav class="us-nav">${NAV.map((n) => this.renderNode(n)).join('')}</nav>
      <div class="us-resizer" title="Потяните, чтобы изменить ширину"></div>
      <button class="us-toggle" type="button" aria-label="Свернуть меню" title="Свернуть/развернуть">
        <span class="us-chevron"></span>
      </button>
    `;
  }

  renderNode(node) {
    const activeCls = node.key === this.active ? ' is-active' : '';
    if (node.children && node.children.length) {
      const childActive = node.children.some((c) => c.key === this.active);
      const selfActive = node.key === this.active;
      const items = node.children.map((c) => `
        <a class="us-subitem${c.key === this.active ? ' is-active' : ''}"
           href="${esc(c.href)}" data-key="${esc(c.key)}">
          <span class="us-sublabel">${esc(c.label)}</span>
        </a>`).join('');
      const caretBtn = `
            <button class="us-caret-btn" type="button" data-toggle="${esc(node.key)}"
                    aria-label="Развернуть список">
              <span class="us-caret"></span>
            </button>`;
      if (node.href) {
        return `
        <div class="us-group" data-group="${esc(node.key)}">
          <div class="us-ghead-row${childActive || selfActive ? ' has-active' : ''}">
            <a class="us-group-link${selfActive ? ' is-active' : ''}"
               href="${esc(node.href)}" data-key="${esc(node.key)}">
              <span class="us-icon">${esc(node.icon || '•')}</span>
              <span class="us-label">${esc(node.label)}</span>
            </a>${caretBtn}
          </div>
          <div class="us-group-items">${items}</div>
        </div>`;
      }
      return `
        <div class="us-group" data-group="${esc(node.key)}">
          <button class="us-group-head${childActive ? ' has-active' : ''}" type="button" data-toggle="${esc(node.key)}">
            <span class="us-icon">${esc(node.icon || '•')}</span>
            <span class="us-label">${esc(node.label)}</span>
            <span class="us-caret"></span>
          </button>
          <div class="us-group-items">${items}</div>
        </div>`;
    }
    return `
      <a class="us-item${activeCls}" href="${esc(node.href || '#')}" data-key="${esc(node.key)}">
        <span class="us-icon">${esc(node.icon || '•')}</span>
        <span class="us-label">${esc(node.label)}</span>
      </a>`;
  }

  // ---------- Применение состояния к DOM ----------
  applyState() {
    this.el.classList.toggle('is-collapsed', this.state.collapsed);
    this.el.style.width = (this.state.collapsed ? COLLAPSED_WIDTH : this.state.width) + 'px';
    this.el.querySelectorAll('.us-group').forEach((g) => {
      g.classList.toggle('is-open', this.state.open.has(g.dataset.group));
    });
  }

  // ---------- События ----------
  bind() {
    // Раскрытие/сворачивание групп.
    this.el.querySelectorAll('.us-group-head, .us-caret-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const key = btn.dataset.toggle;
        // В свёрнутом виде сперва разворачиваем сам сайдбар.
        if (this.state.collapsed) { this.setCollapsed(false); this.state.open.add(key); }
        else if (this.state.open.has(key)) this.state.open.delete(key);
        else this.state.open.add(key);
        this.applyState();
        this.saveState();
      });
    });

    // Кнопка сворачивания.
    const toggle = this.el.querySelector('.us-toggle');
    toggle.addEventListener('click', (e) => {
      e.preventDefault(); e.stopPropagation();
      this.setCollapsed(!this.state.collapsed);
    });
    // Клик по кнопке не должен запускать ресайз.
    toggle.addEventListener('mousedown', (e) => e.stopPropagation());

    // Перетаскивание границы (ресайз).
    const resizer = this.el.querySelector('.us-resizer');
    resizer.addEventListener('mousedown', (e) => this.startResize(e));
  }

  setCollapsed(v) {
    this.state.collapsed = v;
    this.applyState();
    this.saveState();
  }

  startResize(e) {
    if (this.state.collapsed) return; // в свёрнутом виде ширина фиксирована
    e.preventDefault();
    const left = this.el.getBoundingClientRect().left;
    this.el.classList.add('is-resizing');
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    const onMove = (ev) => {
      let w = ev.clientX - left;
      w = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w));
      this.state.width = w;
      this.el.style.width = w + 'px';
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      this.el.classList.remove('is-resizing');
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      this.saveState();
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
}

export { Sidebar };
