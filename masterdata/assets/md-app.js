// ============================================================
// md-app.js — интерфейс модуля «Мастер-данные» (ТЗ §7).
// Одностраничное приложение без сборки и внешних зависимостей:
// hash-маршруты, всё общение с сервером — через REST API /api/md/*.
// Тексты интерфейса собраны в объекте T (задел под казахскую локализацию).
// ============================================================

const T = {
  save: 'Сохранить', saveNew: 'Сохранить и создать ещё', copy: 'Копировать', create: 'Создать',
  archive: 'В архив', restore: 'Восстановить', cancel: 'Отмена', close: 'Закрыть', del: 'Удалить',
  showArchive: 'Показать архив', filters: 'Фильтры', reset: 'Сбросить', columns: 'Колонки',
  exportXlsx: 'Экспорт XLSX', exportCsv: 'Экспорт CSV', import: 'Импорт', nothing: 'Ничего не найдено',
  saved: 'Сохранено', required: 'Обязательное поле', any: 'Любое', yes: 'да', no: 'нет',
  loading: 'Загрузка…', history: 'История', photos: 'Фото', items: 'Экземпляры', kits: 'Комплекты',
};
const GROUPS = [
  ['product', 'Товар'], ['counterparty', 'Контрагенты'], ['finance', 'Финансы'], ['common', 'Общие'],
  ['custom', 'Пользовательские справочники'],
];
const ROLE_CATEGORY = { base: 'База', kamzol: 'Қамзол', takiya: 'Тақия', saukele: 'Сәукеле', corset: 'Корсет',
  shapan: 'Шапан', veil: 'Фата', dress: 'Свадебные платья' };

// ---------------- утилиты ----------------
const S = { token: null, me: null, meta: {}, opts: {}, listState: {} };
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const isEmpty = (v) => v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length);
function fmtMoney(v) {
  if (isEmpty(v)) return '';
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' ₸' : String(v);
}
function fmtNum(v) { return isEmpty(v) ? '' : Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 3 }); }
function fmtDate(v) { if (!v) return ''; const [y, m, d] = String(v).slice(0, 10).split('-'); return d ? `${d}.${m}.${y}` : v; }
function fmtDateTime(v) { if (!v) return ''; const d = new Date(v); return isNaN(d) ? v : d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }
function parseQuery(qs) { const o = {}; new URLSearchParams(qs || '').forEach((v, k) => { o[k] = v; }); return o; }
function toQuery(o) {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => { if (!isEmpty(v) && v !== false) p.set(k, Array.isArray(v) ? v.join(',') : v); });
  return p.toString();
}

// ---------------- API ----------------
async function refreshToken() {
  try {
    const r = await fetch('/api/refresh', { method: 'POST' });
    if (r.ok) { S.token = (await r.json()).accessToken; return true; }
  } catch { /* сеть */ }
  location.href = '/login';
  return false;
}

async function api(path, { method = 'GET', body, form, raw, query } = {}) {
  const url = '/api/md' + path + (query ? (path.includes('?') ? '&' : '?') + toQuery(query) : '');
  const run = () => {
    const headers = { Authorization: 'Bearer ' + S.token, 'X-Client': 'md-ui' };
    const init = { method, headers };
    if (form) init.body = form;
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(url, init);
  };
  let r = await run();
  if (r.status === 401 && await refreshToken()) r = await run();
  if (raw) return r;
  let data;
  try { data = await r.json(); } catch { data = { ok: false, error: `Ошибка сервера (${r.status})` }; }
  if (!r.ok || data.ok === false) {
    const e = new Error(data.error || 'Ошибка');
    e.status = r.status; e.data = data;
    throw e;
  }
  return data;
}

async function download(path, opts = {}, open = false) {
  const r = await api(path, { ...opts, raw: true });
  if (!r.ok) {
    let msg = `Ошибка (${r.status})`;
    try { msg = (await r.json()).error || msg; } catch { /* не JSON */ }
    toast(msg, true);
    return;
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  if (open) { window.open(url, '_blank'); setTimeout(() => URL.revokeObjectURL(url), 60000); return; }
  const cd = r.headers.get('Content-Disposition') || '';
  let name = 'file';
  const m1 = cd.match(/filename\*=UTF-8''([^;]+)/i); const m2 = cd.match(/filename="?([^";]+)"?/i);
  if (m1) name = decodeURIComponent(m1[1]); else if (m2) name = m2[1];
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function getMeta(code, force = false) {
  if (!S.meta[code] || force) S.meta[code] = (await api(`/d/${code}/meta/`)).data;
  return S.meta[code];
}
async function getOptions(code, params = {}) {
  const key = code + '?' + toQuery(params);
  if (!S.opts[key]) S.opts[key] = api(`/d/${code}/options/`, { query: { limit: 300, ...params } }).then((r) => r.data);
  try { return await S.opts[key]; } catch (e) { delete S.opts[key]; throw e; }
}
function dropCaches(code) {
  if (code) delete S.meta[code]; else S.meta = {};
  S.opts = {};
}

// ---------------- UI-примитивы ----------------
function toast(msg, isError = false) {
  const t = el(`<div class="md-toast ${isError ? 'is-error' : ''}">${esc(msg)}</div>`);
  $('#md-toasts').appendChild(t);
  setTimeout(() => t.remove(), isError ? 6000 : 3000);
}
function errToast(e) { toast(e.message || 'Ошибка', true); }

function modal({ title, body, foot, wide = false, onClose }) {
  const back = el(`<div class="md-modal-back"><div class="md-modal ${wide ? 'is-wide' : ''}" role="dialog" aria-modal="true">
    <div class="md-modal-head"><h3>${esc(title)}</h3><button class="md-btn md-btn-ghost md-btn-sm" data-close aria-label="${T.close}">✕</button></div>
    <div class="md-modal-body"></div><div class="md-modal-foot"></div></div></div>`);
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  back.addEventListener('mousedown', (e) => { if (e.target === back) close(); });
  $('[data-close]', back).onclick = close;
  const b = $('.md-modal-body', back);
  if (typeof body === 'string') b.innerHTML = body; else if (body) b.appendChild(body);
  const f = $('.md-modal-foot', back);
  (foot || []).forEach((btn) => f.appendChild(btn));
  if (!foot || !foot.length) f.remove();
  $('#md-modal-root').appendChild(back);
  return { el: back, body: b, close };
}
function btn(label, cls = '', onClick) {
  const b = el(`<button type="button" class="md-btn ${cls}">${label}</button>`);
  if (onClick) b.onclick = onClick;
  return b;
}
function confirmDialog(text, okLabel = 'Да', danger = false) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({
      title: 'Подтверждение', body: `<p>${esc(text)}</p>`,
      foot: [btn(T.cancel, '', () => m.close()),
        btn(esc(okLabel), danger ? 'md-btn-danger' : 'md-btn-primary', () => { done = true; m.close(); })],
      onClose: () => resolve(done),
    });
  });
}
function menuButton(label, items) {
  const wrap = el(`<div class="md-menu"><button type="button" class="md-btn">${label} ▾</button></div>`);
  const list = el('<div class="md-menu-list" hidden></div>');
  items.forEach(([text, fn]) => { const b = el(`<button type="button">${esc(text)}</button>`); b.onclick = () => { list.hidden = true; fn(); }; list.appendChild(b); });
  wrap.appendChild(list);
  wrap.firstElementChild.onclick = (e) => { e.stopPropagation(); list.hidden = !list.hidden; };
  document.addEventListener('click', () => { list.hidden = true; });
  return wrap;
}

// ---------------- Виджеты полей ----------------
// widget(field, value, ctx) → { el, input, get(), set(v), error(msgs), warn(msgs) }
function widget(f, value, ctx = {}) {
  const readonly = ctx.readonly || f.readonly;
  const wide = ['text'].includes(f.type) || f.code === 'components' || (f.multiple && f.type !== 'choice');
  const wrap = el(`<div class="md-field ${f.required ? 'is-required' : ''} ${wide ? 'is-wide' : ''}" data-field="${esc(f.code)}">
    <label>${esc(f.name)}</label></div>`);
  const hint = el(`<div class="md-hint">${esc(f.hint || '')}</div>`);
  const errEl = el('<div class="md-error" hidden></div>');
  const warnEl = el('<div class="md-warning" hidden></div>');
  let api_ = null;
  const id = 'f_' + f.code + '_' + Math.random().toString(36).slice(2, 7);
  $('label', wrap).setAttribute('for', id);
  const t = f.type;
  if (t === 'bool') {
    const cb = el(`<label class="md-check"><input type="checkbox" id="${id}" ${value ? 'checked' : ''} ${readonly ? 'disabled' : ''}> <span>${T.yes}</span></label>`);
    wrap.appendChild(cb);
    const inp = $('input', cb);
    api_ = { input: inp, get: () => inp.checked, set: (v) => { inp.checked = !!v; } };
  } else if (t === 'text') {
    const ta = el(`<textarea class="md-textarea" id="${id}" ${readonly ? 'readonly' : ''}></textarea>`);
    ta.value = value ?? '';
    wrap.appendChild(ta);
    api_ = { input: ta, get: () => ta.value, set: (v) => { ta.value = v ?? ''; } };
  } else if (t === 'choice' && !f.multiple) {
    const sel = el(`<select class="md-select" id="${id}" ${readonly ? 'disabled' : ''}><option value="">—</option>${
      (f.options || []).map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select>`);
    sel.value = value ?? '';
    wrap.appendChild(sel);
    api_ = { input: sel, get: () => sel.value || null, set: (v) => { sel.value = v ?? ''; } };
  } else if (t === 'choice' && f.multiple) {
    api_ = chipsWidget(id, value || [], readonly, async (q) => (f.options || [])
      .filter((o) => !q || o.label.toLowerCase().includes(q.toLowerCase())).map((o) => ({ id: o.value, label: o.label })),
    (f.options || []).reduce((a, o) => { a[o.value] = o.label; return a; }, {}));
    wrap.appendChild(api_.el);
  } else if (t === 'string' && f.multiple) {
    api_ = chipsWidget(id, value || [], readonly, null, {});
    wrap.appendChild(api_.el);
  } else if (t === 'ref' && f.multiple) {
    const labels = {};
    (ctx.record?.[f.code + '__display'] || []).forEach((lbl, i) => { labels[(value || [])[i]] = lbl; });
    api_ = chipsWidget(id, value || [], readonly,
      async (q) => (await getOptions(f.ref_directory, { q, ...(ctx.refParams?.(f) || {}) })).map((o) => ({ id: o.id, label: o.label })),
      labels);
    wrap.appendChild(api_.el);
  } else if (t === 'ref') {
    api_ = refWidget(id, f, value, ctx.record?.[f.code + '__display'] || '', readonly, ctx);
    wrap.appendChild(api_.el);
  } else if (t === 'computed') {
    const disp = ctx.record ? (ctx.record[f.code + '__display'] ?? ctx.record[f.code] ?? '') : '';
    const inp = el(`<input class="md-input" id="${id}" readonly value="${esc(disp || (ctx.isNew ? 'сформируется автоматически' : ''))}">`);
    wrap.appendChild(inp);
    api_ = { input: inp, get: () => undefined, set: () => {} };
  } else if (t === 'file') {
    const box = el(`<div class="md-row"><span class="md-file-name md-muted">${value?.name ? esc(value.name) : 'Файл не выбран'}</span>
      ${readonly ? '' : '<label class="md-btn md-btn-sm">Выбрать…<input type="file" hidden></label>'}
      ${value?.path ? '<button type="button" class="md-btn md-btn-sm" data-dl>Скачать</button>' : ''}</div>`);
    let cur = value || null;
    const inp = $('input', box);
    if (inp) {
      inp.onchange = async () => {
        const fd = new FormData(); fd.append('file', inp.files[0]);
        try { cur = (await api('/files/', { method: 'POST', form: fd })).data; $('.md-file-name', box).textContent = cur.name; } catch (e) { errToast(e); }
      };
    }
    const dl = $('[data-dl]', box);
    if (dl) dl.onclick = () => download('/files/', { query: { path: cur.path } });
    wrap.appendChild(box);
    api_ = { input: inp, get: () => cur, set: (v) => { cur = v; } };
  } else {
    const typeAttr = t === 'date' ? 'date' : t === 'datetime' ? 'datetime-local' : 'text';
    const mode = ['integer'].includes(t) ? 'numeric' : ['decimal', 'money', 'percent'].includes(t) ? 'decimal'
      : t === 'phone' ? 'tel' : t === 'iin_bin' ? 'numeric' : t === 'email' ? 'email' : 'text';
    const inp = el(`<input class="md-input" id="${id}" type="${typeAttr}" inputmode="${mode}" ${readonly ? 'readonly' : ''}
      ${t === 'iin_bin' ? 'maxlength="12"' : ''} ${f.validation?.max_len ? `maxlength="${f.validation.max_len}"` : ''}>`);
    const show = (v) => {
      if (isEmpty(v)) return '';
      if (t === 'datetime') return String(v).slice(0, 16);
      if (t === 'date') return String(v).slice(0, 10);
      if (t === 'phone' && ctx.record?.[f.code + '__display'] && v === ctx.record[f.code]) return ctx.record[f.code + '__display'];
      return v;
    };
    inp.value = show(value);
    if (t === 'money' && !readonly) inp.placeholder = '0 ₸';
    if (f.code === 'hex') {
      const sw = el(`<span class="md-swatch" style="background:${esc(value || 'transparent')}"></span>`);
      const row = el('<div class="md-row" style="flex-wrap:nowrap"></div>');
      row.append(sw, inp);
      inp.addEventListener('input', () => { sw.style.background = inp.value; });
      wrap.appendChild(row);
    } else wrap.appendChild(inp);
    const num = ['integer', 'decimal', 'money', 'percent'].includes(t);
    api_ = {
      input: inp,
      get: () => {
        const v = inp.value.trim();
        if (v === '') return null;
        if (num) { const n = Number(v.replace(/\s/g, '').replace(',', '.')); return Number.isFinite(n) ? n : v; }
        return v;
      },
      set: (v) => { inp.value = show(v); },
    };
  }
  wrap.append(errEl, warnEl);
  if (f.hint) wrap.appendChild(hint);
  return {
    ...api_, el: wrap, control: api_.el, f,
    error(msgs) { errEl.hidden = !msgs?.length; errEl.textContent = (msgs || []).join('; '); wrap.classList.toggle('has-error', !!msgs?.length); },
    warn(msgs) { warnEl.hidden = !msgs?.length; warnEl.innerHTML = (msgs || []).join('<br>'); },
  };
}

function refWidget(id, f, value, label, readonly, ctx) {
  const box = el(`<div class="md-ref"><input class="md-input" id="${id}" autocomplete="off" ${readonly ? 'readonly' : ''} placeholder="${readonly ? '' : 'Начните вводить…'}">
    ${readonly ? '' : '<button type="button" class="md-ref-clear" title="Очистить">✕</button>'}</div>`);
  const inp = $('input', box);
  let cur = value || null; let curLabel = label || '';
  inp.value = curLabel;
  let ac = null;
  const listeners = [];
  const closeAc = () => { if (ac) { ac.remove(); ac = null; } };
  const choose = (o) => {
    cur = o ? o.id : null; curLabel = o ? o.label : ''; inp.value = curLabel; closeAc();
    listeners.forEach((fn) => fn(cur, o));
  };
  const open = debounce(async () => {
    if (readonly) return;
    const q = inp.value === curLabel ? '' : inp.value;
    let items = [];
    try { items = await getOptions(f.ref_directory, { q, ...(ctx.refParams?.(f) || {}) }); } catch (e) { errToast(e); }
    closeAc();
    ac = el('<div class="md-ac"></div>');
    if (!items.length) ac.appendChild(el(`<div class="is-muted">${T.nothing}</div>`));
    items.slice(0, 100).forEach((o) => {
      const d = el(`<div style="padding-left:${12 + ((o.depth || 1) - 1) * 14}px">${esc(o.label)}${o.free === false ? ' <span class="md-badge">в комплекте</span>' : ''}</div>`);
      if (o.leaf === false && f.validation?.ref_filter === 'leaf_selectable') { d.className = 'is-muted'; }
      else d.onmousedown = (e) => { e.preventDefault(); choose(o); };
      ac.appendChild(d);
    });
    box.appendChild(ac);
  }, 200);
  inp.addEventListener('focus', open);
  inp.addEventListener('input', open);
  inp.addEventListener('blur', () => setTimeout(() => { closeAc(); if (inp.value !== curLabel) inp.value = curLabel; }, 150));
  const clr = $('.md-ref-clear', box);
  if (clr) clr.onclick = () => choose(null);
  return { el: box, input: inp, get: () => cur, set: (v, lbl) => { cur = v; curLabel = lbl || ''; inp.value = curLabel; },
    onChange: (fn) => listeners.push(fn), label: () => curLabel };
}

function chipsWidget(id, values, readonly, search, labels) {
  const box = el(`<div class="md-chips"></div>`);
  let cur = [...values];
  const inp = el(`<input id="${id}" autocomplete="off" ${readonly ? 'hidden' : ''} placeholder="${search ? 'Добавить…' : 'Введите и нажмите Enter'}">`);
  let ac = null;
  const listeners = [];
  const render = () => {
    $$('.md-chip', box).forEach((c) => c.remove());
    cur.forEach((v) => {
      const c = el(`<span class="md-chip">${esc(labels[v] ?? v)}${readonly ? '' : '<button type="button" aria-label="Убрать">×</button>'}</span>`);
      const b = $('button', c);
      if (b) b.onclick = () => { cur = cur.filter((x) => x !== v); render(); listeners.forEach((fn) => fn(cur)); };
      box.insertBefore(c, inp);
    });
  };
  const closeAc = () => { if (ac) { ac.remove(); ac = null; } };
  const open = debounce(async () => {
    if (!search) return;
    const items = (await search(inp.value)).filter((o) => !cur.includes(o.id));
    closeAc();
    ac = el('<div class="md-ac"></div>');
    if (!items.length) ac.appendChild(el(`<div class="is-muted">${T.nothing}</div>`));
    items.slice(0, 100).forEach((o) => {
      const d = el(`<div>${esc(o.label)}</div>`);
      d.onmousedown = (e) => { e.preventDefault(); labels[o.id] = o.label; cur.push(o.id); inp.value = ''; render(); closeAc(); listeners.forEach((fn) => fn(cur)); };
      ac.appendChild(d);
    });
    box.appendChild(ac);
  }, 180);
  inp.addEventListener('focus', open);
  inp.addEventListener('input', open);
  inp.addEventListener('blur', () => setTimeout(closeAc, 150));
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (!search && inp.value.trim()) { cur.push(inp.value.trim()); inp.value = ''; render(); }
    } else if (e.key === 'Backspace' && !inp.value && cur.length) { cur.pop(); render(); }
  });
  box.appendChild(inp);
  box.addEventListener('click', () => inp.focus());
  render();
  return { el: box, input: inp, get: () => [...cur], set: (v) => { cur = [...(v || [])]; render(); }, onChange: (fn) => listeners.push(fn) };
}

// Отображение значения в ячейке списка
function cellValue(f, row) {
  const v = row[f.code];
  const disp = row[f.code + '__display'];
  if (f.code === 'hex' && v) return `<span class="md-swatch" style="background:${esc(v)}"></span> ${esc(v)}`;
  if (Array.isArray(disp)) return disp.map((x) => `<span class="md-chip">${esc(x)}</span>`).join(' ');
  if (disp !== undefined && disp !== null && disp !== '' && typeof disp !== 'object') return esc(disp);
  if (f.type === 'bool') return v ? '✓' : '';
  if (f.type === 'money') return esc(fmtMoney(v));
  if (['integer', 'decimal', 'percent'].includes(f.type)) return esc(fmtNum(v));
  if (f.type === 'date') return esc(fmtDate(v));
  if (f.type === 'datetime') return esc(fmtDateTime(v));
  if (Array.isArray(v)) return v.map((x) => `<span class="md-chip">${esc(x)}</span>`).join(' ');
  if (v && typeof v === 'object') return esc(v.name || '');
  return esc(v ?? '');
}

// ============================================================
// Каркас: меню, поиск в шапке, маршруты
// ============================================================
function renderNav() {
  const nav = $('#md-nav');
  const route = location.hash;
  const dirs = (S.me.menu || []).filter((d) => d.menu_enabled);
  let html = '<a href="#/"><span class="md-ico">🏠</span>Обзор</a>';
  GROUPS.forEach(([g, title]) => {
    const list = dirs.filter((d) => d.menu_group === g);
    if (!list.length) return;
    html += `<h4>${esc(title)}</h4>` + list.map((d) =>
      `<a href="#/d/${d.code}" data-code="${d.code}"><span class="md-ico">${esc(d.icon || '📁')}</span>${esc(d.name)}</a>`).join('');
  });
  html += '<h4>Настройки</h4>';
  if (S.me.is_manager) html += '<a href="#/builder"><span class="md-ico">🛠️</span>Конструктор справочников</a>';
  html += '<a href="#/import"><span class="md-ico">📥</span>Импорт</a><a href="#/import/jobs"><span class="md-ico">🧾</span>Журнал импорта</a>';
  if (S.me.is_manager) html += '<a href="#/settings"><span class="md-ico">⚙️</span>Организация и права</a>';
  nav.innerHTML = html;
  $$('a', nav).forEach((a) => {
    const href = a.getAttribute('href');
    const active = href === '#/' ? (route === '' || route === '#/' || route === '#')
      : (route === href || route.startsWith(href + '/') || route.startsWith(href + '?'));
    a.classList.toggle('is-active', active);
    a.addEventListener('click', () => toggleNav(false));
  });
}
function toggleNav(open) {
  $('#md-nav').classList.toggle('is-open', open);
  $('#md-nav-backdrop').classList.toggle('is-open', open);
}

function setupSearch() {
  const inp = $('#md-search');
  const box = $('#md-search-results');
  let last = null;
  const show = (res) => {
    last = res;
    if (!res) { box.hidden = true; return; }
    box.innerHTML = res.results.length ? res.results.map((r, i) =>
      `<a href="#/d/${r.dict}/${r.id}" class="${i === 0 ? 'is-active' : ''}"><span class="md-sr-dict">${esc(r.dict_name)}</span>
        <b>${esc(r.title)}</b><small>${esc(r.subtitle || '')}</small></a>`).join('')
      : `<div class="md-loading">${T.nothing}</div>`;
    box.hidden = false;
  };
  const run = debounce(async () => {
    const q = inp.value.trim();
    if (q.length < 2 || document.activeElement !== inp) { show(null); return; }
    try { show((await api('/search/', { query: { q } })).data); } catch (e) { errToast(e); }
  }, 250);
  inp.addEventListener('input', run);
  inp.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const q = inp.value.trim();
      if (q.length < 2) return;
      const res = (await api('/search/', { query: { q } })).data;
      // Найдена одна запись — открываем сразу (снижает риск выбрать не то платье)
      if (res.single) { location.hash = `#/d/${res.single.dict}/${res.single.id}`; inp.value = ''; last = null; show(null); inp.blur(); }
      else show(res);
    } else if (e.key === 'Escape') { show(null); inp.blur(); }
  });
  box.addEventListener('click', () => { setTimeout(() => show(null), 0); inp.value = ''; });
  document.addEventListener('click', (e) => { if (!e.target.closest('.md-search')) box.hidden = true; });
  inp.addEventListener('focus', () => { if (last) box.hidden = false; });
}

const ROUTES = [
  [/^\/?$/, viewHome],
  [/^\/d\/(\w+)$/, viewList],
  [/^\/d\/(\w+)\/(new|[0-9a-f-]{36})$/, viewCard],
  [/^\/builder$/, viewBuilder],
  [/^\/builder\/(\w+)$/, viewBuilderDir],
  [/^\/import$/, viewImport],
  [/^\/import\/jobs$/, viewImportJobs],
  [/^\/settings$/, viewSettings],
];

async function router() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = raw.split('?');
  const main = $('#md-main');
  renderNav();
  for (const [re, fn] of ROUTES) {
    const mt = path.match(re);
    if (mt) {
      main.innerHTML = `<div class="md-loading">${T.loading}</div>`;
      try { await fn(main, mt.slice(1), parseQuery(qs)); } catch (e) {
        main.innerHTML = `<div class="md-errbox">${esc(e.message || 'Ошибка')}</div>`;
        if (e.status !== 403 && e.status !== 404) console.error(e);
      }
      window.scrollTo(0, 0);
      return;
    }
  }
  main.innerHTML = '<div class="md-errbox">Страница не найдена</div>';
}

// ============================================================
// Обзор
// ============================================================
async function viewHome(main) {
  const dirs = (S.me.menu || []).filter((d) => d.menu_enabled);
  let html = `<div class="md-page-head"><h1>Мастер-данные</h1><span class="md-spacer"></span>
    <span class="md-muted">${esc(S.me.organization.name)} · ${esc(S.me.role__display)}</span></div>`;
  GROUPS.forEach(([g, title]) => {
    const list = dirs.filter((d) => d.menu_group === g);
    if (!list.length) return;
    html += `<h3 style="margin:22px 0 10px;font-size:15px">${esc(title)}</h3><div class="md-grid-cards">` + list.map((d) =>
      `<a class="md-dcard" href="#/d/${d.code}"><span class="md-ico">${esc(d.icon || '📁')}</span><b>${esc(d.name)}</b>
       <small>${esc(d.description || '')}</small></a>`).join('') + '</div>';
  });
  main.innerHTML = html;
}

// ============================================================
// Список (МД-13, МД-14, МД-23, МД-24)
// ============================================================
async function viewList(main, [code], query) {
  const meta = await getMeta(code);
  const st = S.listState[code] = S.listState[code] || {
    q: '', filters: {}, ordering: '', page: 1, page_size: 50, archived: false, selected: new Set(),
    view: meta.tile_view ? 'tiles' : 'table',
  };
  // фильтры из адресной строки (ссылки «найти по виду» и т.п.)
  Object.entries(query).forEach(([k, v]) => {
    if (k === 'q') st.q = v; else if (k === 'archived') st.archived = v === '1'; else st.filters[k] = v;
  });
  const P = meta.permissions;
  const fieldsBy = Object.fromEntries(meta.fields.map((f) => [f.code, f]));
  const allCols = meta.fields.filter((f) => !['text', 'file', 'photo'].includes(f.type) && f.code !== 'components');
  const colCodes = () => (meta.columns_pref?.columns || meta.fields.filter((f) => f.show_in_list).map((f) => f.code))
    .filter((c) => fieldsBy[c]);

  main.innerHTML = `
    <div class="md-page-head"><h1><span>${esc(meta.icon)}</span>${esc(meta.name)}</h1><span class="md-spacer"></span>
      <div class="md-row" id="ls-actions"></div></div>
    <div class="md-list-layout">
      <aside class="md-filters" id="ls-filters"></aside>
      <section class="md-list-main">
        <div class="md-toolbar">
          <button type="button" class="md-btn md-filters-btn" id="ls-filters-btn">⚲ ${T.filters}</button>
          <input class="md-input" type="search" id="ls-q" placeholder="Поиск…" value="${esc(st.q)}">
          <label class="md-check"><input type="checkbox" id="ls-arch" ${st.archived ? 'checked' : ''}> ${T.showArchive}</label>
          <span class="md-spacer" style="flex:1"></span>
          <span id="ls-viewsw"></span>
          <button type="button" class="md-btn" id="ls-cols">☰ ${T.columns}</button>
        </div>
        <div id="ls-bulk"></div>
        <div id="ls-body"></div>
        <div class="md-pager" id="ls-pager"></div>
      </section>
    </div>`;

  // ---- кнопки шапки
  const acts = $('#ls-actions', main);
  if (P.create) acts.appendChild(btn('+ ' + T.create, 'md-btn-primary', () => { location.hash = `#/d/${code}/new`; }));
  if (P.import) acts.appendChild(btn('📥 ' + T.import, '', () => { location.hash = `#/import?d=${code}`; }));
  if (P.export) {
    acts.appendChild(menuButton('Экспорт', [
      [T.exportXlsx, () => download(`/d/${code}/export/`, { query: { ...listParams(), format: 'xlsx', page: '', page_size: '' } })],
      [T.exportCsv, () => download(`/d/${code}/export/`, { query: { ...listParams(), format: 'csv', page: '', page_size: '' } })],
    ]));
  }
  if (meta.tile_view) {
    const sw = el(`<span class="md-btn-group"><button type="button" class="md-btn md-btn-sm" data-v="tiles" title="Плитка">▦</button>
      <button type="button" class="md-btn md-btn-sm" data-v="table" title="Таблица">☰</button></span>`);
    $$('button', sw).forEach((b) => { b.classList.toggle('is-on', b.dataset.v === st.view); b.onclick = () => { st.view = b.dataset.v; viewList(main, [code], {}); }; });
    $('#ls-viewsw', main).appendChild(sw);
  }

  function listParams() {
    return { q: st.q, ordering: st.ordering, page: st.page, page_size: st.page_size, archived: st.archived ? '1' : '', ...st.filters };
  }
  function syncHash() {
    const q = toQuery({ q: st.q, archived: st.archived ? '1' : '', ...st.filters });
    history.replaceState(null, '', `#/d/${code}` + (q ? '?' + q : ''));
  }

  // ---- панель фильтров
  const fbox = $('#ls-filters', main);
  async function renderFilters() {
    fbox.innerHTML = `<div class="md-row" style="justify-content:space-between;margin-bottom:6px"><b>${T.filters}</b>
      <span><button type="button" class="md-btn md-btn-sm md-btn-ghost" id="flt-reset">${T.reset}</button>
      <button type="button" class="md-btn md-btn-sm md-filters-close" id="flt-close">✕</button></span></div>`;
    if (!meta.filters.length) fbox.appendChild(el('<div class="md-muted">Нет полей для фильтра</div>'));
    for (const f of meta.filters) {
      const block = el(`<div><h4>${esc(f.name)}</h4></div>`);
      if (f.type === 'ref' || f.type === 'choice') {
        let opts = f.type === 'choice' ? (f.options || []).map((o) => ({ id: o.value, label: o.label })) : [];
        if (f.type === 'ref') {
          try { opts = await getOptions(f.ref_directory, f.ref_directory === 'categories' ? {} : {}); } catch { opts = []; }
        }
        const sel = new Set((st.filters[f.code] || '').split(',').filter(Boolean));
        const box = el('<div class="md-filter-opts"></div>');
        if (opts.length > 12) {
          const fs = el('<input class="md-input md-filter-search" type="search" placeholder="Найти…">');
          fs.oninput = () => { const q = fs.value.toLowerCase(); $$('label', box).forEach((l) => { l.hidden = q && !l.textContent.toLowerCase().includes(q); }); };
          block.appendChild(fs);
        }
        opts.forEach((o) => {
          const lbl = f.ref_directory === 'categories' ? o.label.split(' / ').pop() : o.label;
          const pad = f.ref_directory === 'categories' ? `style="padding-left:${((o.depth || 1) - 1) * 14}px"` : '';
          const row = el(`<label ${pad}><input type="checkbox" value="${esc(o.id)}" ${sel.has(String(o.id)) ? 'checked' : ''}> ${esc(lbl)}</label>`);
          $('input', row).onchange = (e) => {
            if (e.target.checked) sel.add(String(o.id)); else sel.delete(String(o.id));
            st.filters[f.code] = [...sel].join(','); if (!st.filters[f.code]) delete st.filters[f.code];
            st.page = 1; load();
          };
          box.appendChild(row);
        });
        block.appendChild(box);
      } else if (f.type === 'bool') {
        const s = el(`<select class="md-select"><option value="">${T.any}</option><option value="true">${T.yes}</option><option value="false">${T.no}</option></select>`);
        s.value = st.filters[f.code] || '';
        s.onchange = () => { if (s.value) st.filters[f.code] = s.value; else delete st.filters[f.code]; st.page = 1; load(); };
        block.appendChild(s);
      } else if (['money', 'integer', 'decimal', 'percent'].includes(f.type)) {
        const r = el(`<div class="md-range"><input class="md-input" placeholder="от" inputmode="decimal" value="${esc(st.filters[f.code + '__min'] || '')}">
          <input class="md-input" placeholder="до" inputmode="decimal" value="${esc(st.filters[f.code + '__max'] || '')}"></div>`);
        const [a, b] = $$('input', r);
        const upd = debounce(() => {
          if (a.value) st.filters[f.code + '__min'] = a.value; else delete st.filters[f.code + '__min'];
          if (b.value) st.filters[f.code + '__max'] = b.value; else delete st.filters[f.code + '__max'];
          st.page = 1; load();
        }, 400);
        a.oninput = upd; b.oninput = upd;
        block.appendChild(r);
      } else {
        const i = el(`<input class="md-input" value="${esc(st.filters[f.code] || '')}">`);
        i.oninput = debounce(() => { if (i.value) st.filters[f.code] = i.value; else delete st.filters[f.code]; st.page = 1; load(); }, 400);
        block.appendChild(i);
      }
      fbox.appendChild(block);
    }
    $('#flt-reset', fbox).onclick = () => { st.filters = {}; st.q = ''; $('#ls-q', main).value = ''; st.page = 1; renderFilters(); load(); };
    $('#flt-close', fbox).onclick = () => fbox.classList.remove('is-open');
  }
  $('#ls-filters-btn', main).onclick = () => fbox.classList.add('is-open');
  renderFilters();

  $('#ls-q', main).oninput = debounce((e) => { st.q = e.target.value; st.page = 1; load(); }, 300);
  $('#ls-arch', main).onchange = (e) => { st.archived = e.target.checked; st.page = 1; load(); };
  $('#ls-cols', main).onclick = () => columnsDialog(code, meta, allCols, colCodes(), () => viewList(main, [code], {}));

  // ---- массовые действия
  function renderBulk(rows) {
    const bar = $('#ls-bulk', main);
    const n = st.selected.size;
    if (!n) { bar.innerHTML = ''; return; }
    bar.innerHTML = `<div class="md-bulkbar"><b>Выбрано: ${n}</b></div>`;
    const b = $('.md-bulkbar', bar);
    const ids = [...st.selected];
    const run = async (body) => {
      try {
        const r = (await api(`/d/${code}/bulk/`, { method: 'POST', body: { ids, ...body } })).data;
        toast(`Готово: ${r.done}` + (r.errors.length ? `, ошибок: ${r.errors.length}` : ''), !!r.errors.length);
        if (r.errors.length) modal({ title: 'Не удалось изменить', body: '<ul>' + r.errors.map((e) => `<li><b>${esc(e.title)}</b>: ${esc(e.message)}</li>`).join('') + '</ul>' });
        st.selected.clear(); load();
      } catch (e) { errToast(e); }
    };
    if (P.update) b.appendChild(btn('Изменить поле…', 'md-btn-sm', () => bulkEditDialog(meta, (field, value) => run({ action: 'update', field, value }))));
    if (P.archive) {
      b.appendChild(btn(T.archive, 'md-btn-sm', async () => { if (await confirmDialog(`Перенести в архив записей: ${n}?`)) run({ action: 'archive' }); }));
      b.appendChild(btn(T.restore, 'md-btn-sm', () => run({ action: 'restore' })));
    }
    if (P.export) b.appendChild(btn('Экспорт', 'md-btn-sm', () => download(`/d/${code}/bulk/`, { method: 'POST', body: { ids, action: 'export' } })));
    if (code === 'items') b.appendChild(btn('🏷️ Печать бирок', 'md-btn-sm', () => download(`/labels/?ids=${ids.join(',')}`, {}, true)));
    b.appendChild(btn('Снять выбор', 'md-btn-sm md-btn-ghost', () => { st.selected.clear(); load(); }));
    void rows;
  }

  // ---- загрузка и отрисовка
  const body = $('#ls-body', main);
  let seq = 0;
  async function load() {
    syncHash();
    const my = ++seq;
    let res;
    try { res = await api(`/d/${code}/`, { query: listParams() }); } catch (e) { errToast(e); return; }
    if (my !== seq) return;
    const rows = res.data;
    if (st.view === 'tiles' && meta.tile_view) renderTiles(rows); else renderTable(rows);
    renderBulk(rows);
    const pages = Math.max(1, Math.ceil(res.total / st.page_size));
    const pg = $('#ls-pager', main);
    pg.innerHTML = `<span>Всего: ${res.total}</span><select class="md-select" style="width:auto">${[25, 50, 100, 200].map((n) =>
      `<option ${n === st.page_size ? 'selected' : ''}>${n}</option>`).join('')}</select>
      <button type="button" class="md-btn md-btn-sm" ${st.page <= 1 ? 'disabled' : ''} data-p="-1">‹</button>
      <span>${st.page} / ${pages}</span>
      <button type="button" class="md-btn md-btn-sm" ${st.page >= pages ? 'disabled' : ''} data-p="1">›</button>`;
    $('select', pg).onchange = (e) => { st.page_size = Number(e.target.value); st.page = 1; load(); };
    $$('[data-p]', pg).forEach((b) => { b.onclick = () => { st.page += Number(b.dataset.p); load(); }; });
  }

  function renderTable(rows) {
    const cols = colCodes().map((c) => fieldsBy[c]);
    const withPhoto = meta.supports_photo;
    const sortIcon = (c) => st.ordering === c ? ' ▲' : st.ordering === '-' + c ? ' ▼' : '';
    body.innerHTML = `<div class="md-table-wrap"><table class="md-table"><thead><tr>
      <th class="md-cb"><input type="checkbox" id="ls-all" aria-label="Выбрать все"></th>
      ${withPhoto ? '<th></th>' : ''}
      ${cols.map((f) => `<th class="${f.type === 'ref' && f.multiple ? '' : 'is-sortable'}" data-sort="${f.code}">${esc(f.name)}${sortIcon(f.code)}</th>`).join('')}
      </tr></thead><tbody>${rows.length ? rows.map((r) => `
      <tr data-id="${r.id}" class="${r.is_active ? '' : 'is-archived'} ${st.selected.has(r.id) ? 'is-selected' : ''}">
        <td class="md-cb"><input type="checkbox" ${st.selected.has(r.id) ? 'checked' : ''} aria-label="Выбрать"></td>
        ${withPhoto ? `<td>${r.main_photo ? `<img class="md-thumb" loading="lazy" src="${esc(r.main_photo.thumb_300)}" alt="">` : '<div class="md-thumb"></div>'}</td>` : ''}
        ${cols.map((f, i) => `<td class="${['money', 'integer', 'decimal'].includes(f.type) ? 'md-num' : ''}">${cellValue(f, r)}${
          i === 0 && !r.is_active ? ' <span class="md-badge">архив</span>' : ''}</td>`).join('')}
      </tr>`).join('') : `<tr><td class="md-empty" colspan="${cols.length + 2}">${T.nothing}</td></tr>`}</tbody></table></div>`;
    $$('th[data-sort].is-sortable', body).forEach((th) => {
      th.onclick = () => { const c = th.dataset.sort; st.ordering = st.ordering === c ? '-' + c : c; load(); };
    });
    $('#ls-all', body).onchange = (e) => { rows.forEach((r) => (e.target.checked ? st.selected.add(r.id) : st.selected.delete(r.id))); load(); };
    $$('tbody tr[data-id]', body).forEach((tr) => {
      const cb = $('input', tr);
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = () => { if (cb.checked) st.selected.add(tr.dataset.id); else st.selected.delete(tr.dataset.id); tr.classList.toggle('is-selected', cb.checked); renderBulk(rows); };
      tr.onclick = () => { location.hash = `#/d/${code}/${tr.dataset.id}`; };
    });
  }

  function renderTiles(rows) {
    body.innerHTML = rows.length ? `<div class="md-tiles">${rows.map((r) => `
      <div class="md-tile ${st.selected.has(r.id) ? 'is-selected' : ''}" data-id="${r.id}">
        <input type="checkbox" class="md-tile-cb" ${st.selected.has(r.id) ? 'checked' : ''} aria-label="Выбрать">
        <div class="md-tile-img">${r.main_photo ? `<img loading="lazy" src="${esc(r.main_photo.thumb_300)}" alt="">` : '👗'}</div>
        <div class="md-tile-body">
          <span class="md-tile-art">${esc(r.article)}${r.is_active ? '' : ' <span class="md-badge">архив</span>'}</span>
          <span class="md-tile-name">${esc(r.name)}</span>
          <span class="md-tile-price">${r.rent_price !== undefined && r.rent_price !== null ? esc(fmtMoney(r.rent_price)) : r.sale_price ? esc(fmtMoney(r.sale_price)) : ''}</span>
          <span class="md-tile-chips">${(r.styles__display || []).map((s) => `<span class="md-chip">${esc(s)}</span>`).join('')}</span>
        </div></div>`).join('')}</div>` : `<div class="md-panel md-muted">${T.nothing}</div>`;
    $$('.md-tile', body).forEach((t) => {
      const cb = $('input', t);
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = () => { if (cb.checked) st.selected.add(t.dataset.id); else st.selected.delete(t.dataset.id); t.classList.toggle('is-selected', cb.checked); renderBulk(rows); };
      t.onclick = () => { location.hash = `#/d/${code}/${t.dataset.id}`; };
    });
  }
  load();
}

function columnsDialog(code, meta, allCols, current, done) {
  let order = [...current, ...allCols.map((f) => f.code).filter((c) => !current.includes(c))];
  const on = new Set(current);
  const body = el('<div></div>');
  const render = () => {
    body.innerHTML = '<p class="md-muted" style="margin-top:0">Отметьте колонки и задайте порядок. Настройка сохраняется для вас.</p>';
    order.forEach((c, i) => {
      const f = allCols.find((x) => x.code === c);
      if (!f) return;
      const row = el(`<div class="md-row" style="padding:4px 0;border-bottom:1px solid var(--line)">
        <label class="md-check" style="flex:1"><input type="checkbox" ${on.has(c) ? 'checked' : ''}> ${esc(f.name)}</label>
        <button type="button" class="md-btn md-btn-sm" ${i === 0 ? 'disabled' : ''} data-u>↑</button>
        <button type="button" class="md-btn md-btn-sm" ${i === order.length - 1 ? 'disabled' : ''} data-d>↓</button></div>`);
      $('input', row).onchange = (e) => { if (e.target.checked) on.add(c); else on.delete(c); };
      $('[data-u]', row).onclick = () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; render(); };
      $('[data-d]', row).onclick = () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; render(); };
      body.appendChild(row);
    });
  };
  render();
  const m = modal({
    title: T.columns, body,
    foot: [btn('По умолчанию', '', async () => { await api(`/prefs/columns:${code}/`, { method: 'PUT', body: { value: null } }); dropCaches(code); m.close(); done(); }),
      btn(T.save, 'md-btn-primary', async () => {
        const cols = order.filter((c) => on.has(c));
        await api(`/prefs/columns:${code}/`, { method: 'PUT', body: { value: { columns: cols } } });
        dropCaches(code); m.close(); done();
      })],
  });
}

function bulkEditDialog(meta, apply) {
  const editable = meta.fields.filter((f) => !f.readonly && f.type !== 'computed' && !f.unique && f.code !== 'code'
    && !['article', 'tag', 'iin', 'bin_iin', 'barcode'].includes(f.code));
  const body = el(`<div><div class="md-field"><label>Поле</label><select class="md-select">${editable.map((f) =>
    `<option value="${f.code}">${esc(f.name)}</option>`).join('')}</select></div><div id="bv" style="margin-top:12px"></div></div>`);
  const sel = $('select', body);
  let w;
  const draw = () => {
    const f = editable.find((x) => x.code === sel.value);
    w = widget({ ...f, required: false, hint: '' }, f.multiple ? [] : null, {});
    $('#bv', body).innerHTML = ''; $('#bv', body).appendChild(w.el);
  };
  sel.onchange = draw; draw();
  const m = modal({ title: 'Изменить значение поля', body, foot: [btn(T.cancel, '', () => m.close()),
    btn('Применить', 'md-btn-primary', () => { apply(sel.value, w.get()); m.close(); })] });
}

// ============================================================
// Карточка (МД-15…22)
// ============================================================
async function viewCard(main, [code, id], query) {
  const meta = await getMeta(code);
  const isNew = id === 'new';
  const P = meta.permissions;
  let rec = {};
  if (!isNew) rec = (await api(`/d/${code}/${id}/`)).data;
  else {
    meta.fields.forEach((f) => { if (f.default !== null && f.default !== undefined) rec[f.code] = f.default; });
    if (query.copy) {
      // «Копировать»: новая запись по образцу, без уникальных полей
      const src = (await api(`/d/${code}/${query.copy}/`)).data;
      rec = { ...src };
      ['id', 'article', 'tag', 'code', 'barcode', 'iin', 'bin_iin', 'is_active'].forEach((k) => delete rec[k]);
      if (rec.name) rec.name += ' (копия)';
      if (rec.full_name) rec.full_name += ' (копия)';
      if (code === 'kits') rec.components = [];
    }
    if (code === 'items' && query.model) {
      const mm = (await api(`/d/models/${query.model}/`)).data;
      rec.model = mm.id; rec.model__display = `${mm.article} · ${mm.name}`;
    }
    if (code === 'kits' && query.item) {
      const it = (await api(`/d/items/${query.item}/`)).data;
      rec.main_item = it.id; rec.main_item__display = `${it.tag} · ${it.article}`;
      rec.components = [{ item: it.id, role: 'base', tag: it.tag, article: it.article, name: it.model__name }];
    }
  }
  const canEdit = isNew ? P.create : P.update;
  const title = isNew ? `Новая запись — ${meta.name}` : (rec._title || meta.name);

  main.innerHTML = `
    <div class="md-crumbs"><a href="#/d/${code}">${esc(meta.icon)} ${esc(meta.name)}</a></div>
    <div class="md-card-head" id="cd-head"><div><h1>${esc(title)}</h1>
      <div class="md-muted" style="font-size:12.5px;margin-top:4px">${isNew ? '' :
        `Создано ${fmtDateTime(rec.created_at)}${rec.created_by__display ? ' · ' + esc(rec.created_by__display) : ''}
         · изменено ${fmtDateTime(rec.updated_at)}${rec.updated_by__display ? ' · ' + esc(rec.updated_by__display) : ''}`}
        ${!isNew && !rec.is_active ? ' <span class="md-badge md-badge-warn">в архиве</span>' : ''}</div></div>
      <div class="md-card-actions" id="cd-actions"></div></div>
    <div id="cd-hero"></div>
    <div id="cd-msg"></div>
    <div class="md-tabs" id="cd-tabs" role="tablist"></div>
    <div id="cd-panes"></div>`;

  // ---- вкладки: группы полей + спец. вкладки
  const groups = [];
  meta.fields.forEach((f) => { const g = f.group || 'Основное'; if (!groups.includes(g)) groups.push(g); });
  const extraTabs = isNew ? [] : meta.tabs.filter((t) => t !== 'history' || P.history !== 'none');
  const tabNames = { photos: T.photos, items: T.items, kits: T.kits, history: T.history };
  const tabs = $('#cd-tabs', main); const panes = $('#cd-panes', main);
  const widgets = {};
  const ctx = { record: rec, isNew, readonly: !canEdit, refParams: (f) => refParams(f) };
  function refParams(f) {
    const p = {};
    if (f.validation?.ref_filter === 'leaf_selectable') p.leaf = '1';
    if (f.validation?.ref_filter === 'styles_for_category' && widgets.category) {
      const c = widgets.category.get(); if (c) p.category = c;
    }
    return p;
  }
  const paneByGroup = {};
  [...groups, ...extraTabs].forEach((g, i) => {
    const tb = el(`<button type="button" class="md-tab ${i === 0 ? 'is-active' : ''}" role="tab" data-tab="${esc(g)}">${esc(tabNames[g] || g)}</button>`);
    const pane = el(`<div class="md-panel" data-pane="${esc(g)}" ${i === 0 ? '' : 'hidden'}></div>`);
    tb.onclick = () => {
      $$('.md-tab', tabs).forEach((x) => x.classList.toggle('is-active', x === tb));
      $$('[data-pane]', panes).forEach((x) => { x.hidden = x !== pane; });
      if (pane.dataset.lazy && !pane.dataset.loaded) { pane.dataset.loaded = '1'; LAZY[pane.dataset.lazy](pane); }
    };
    tabs.appendChild(tb); panes.appendChild(pane);
    if (groups.includes(g)) { pane.appendChild(el('<div class="md-form"></div>')); paneByGroup[g] = $('.md-form', pane); } else pane.dataset.lazy = g;
  });
  if (tabs.children.length < 2) tabs.hidden = true;

  // ---- поля
  meta.fields.forEach((f) => {
    if (code === 'kits' && f.code === 'components') { widgets.components = kitComponentsWidget(rec, !canEdit, id); paneByGroup[f.group || 'Основное'].appendChild(widgets.components.el); return; }
    if (isNew && f.readonly && f.type !== 'computed' && !['tag'].includes(f.code)) return;
    const w = widget(f, rec[f.code], { ...ctx, readonly: ctx.readonly || (f.readonly) });
    widgets[f.code] = w;
    paneByGroup[f.group || 'Основное'].appendChild(w.el);
  });
  if (meta.hierarchical && code !== 'categories' && code !== 'accounts') {
    const f = { code: 'parent', name: 'Родитель', type: 'ref', ref_directory: code };
    widgets.parent = widget(f, rec.parent, ctx);
    paneByGroup[groups[0]].appendChild(widgets.parent.el);
  }
  if (!meta.is_system && !meta.fields.some((f) => f.code === 'code')) {
    widgets.code = widget({ code: 'code', name: 'Код', type: 'string', hint: 'Необязательный, уникальный' }, rec.code, ctx);
    paneByGroup[groups[0]].appendChild(widgets.code.el);
  }

  // ---- поведение полей
  if (code === 'models') wireModelCard(widgets, rec, isNew);
  if (code === 'clients') wireClientCard(widgets, rec);
  if (code === 'items' && !isNew) renderItemHero($('#cd-hero', main), rec);
  if (code === 'items' && isNew && widgets.model) {
    widgets.model.onChange?.(async (val, o) => { if (o && widgets.size) widgets.size.el.classList.toggle('is-required', !!o.size_required); });
  }

  // ---- действия
  const actions = $('#cd-actions', main);
  async function save(mode) {
    const payload = {};
    Object.entries(widgets).forEach(([k, w]) => {
      if (!w || w.get === undefined) return;
      const f = w.f || {};
      if (f.readonly || f.type === 'computed') return;
      const v = w.get();
      if (v === undefined) return;
      if (isNew) { if (!isEmpty(v) || f.type === 'bool') payload[k] = v; } else {
        const old = rec[k];
        const same = JSON.stringify(Array.isArray(v) ? [...v].sort() : v ?? null) === JSON.stringify(Array.isArray(old) ? [...old].sort() : (old === '' ? null : old ?? null));
        const numSame = typeof v === 'number' && old !== null && old !== undefined && Number(old) === v;
        if (!same && !numSame) payload[k] = v;
      }
    });
    Object.values(widgets).forEach((w) => w?.error?.([]));
    $('#cd-msg', main).innerHTML = '';
    if (!isNew && !Object.keys(payload).length) { toast('Нет изменений'); return; }
    try {
      const res = isNew ? await api(`/d/${code}/`, { method: 'POST', body: payload })
        : await api(`/d/${code}/${id}/`, { method: 'PATCH', body: payload });
      toast(T.saved);
      S.opts = {};
      if (res.warnings?.length) sessionStorageSafe('md.warn', JSON.stringify(res.warnings));
      if (mode === 'new') { location.hash = `#/d/${code}/new?_=${Date.now()}`; }
      else if (isNew) location.hash = `#/d/${code}/${res.data.id}`;
      else router();
    } catch (e) {
      const fe = e.data?.fields || {};
      let firstTab = null;
      Object.entries(fe).forEach(([k, msgs]) => {
        const w = widgets[k];
        if (w?.error) { w.error(msgs); const pane = w.el.closest('[data-pane]'); if (pane && !firstTab) firstTab = pane.dataset.pane; }
      });
      const unknown = Object.entries(fe).filter(([k]) => !widgets[k]).map(([k, v]) => `${k}: ${v.join('; ')}`);
      $('#cd-msg', main).innerHTML = `<div class="md-errbox">${esc(e.message)}${unknown.length ? '<br>' + unknown.map(esc).join('<br>') : ''}</div>`;
      if (firstTab) $(`.md-tab[data-tab="${CSS.escape(firstTab)}"]`, tabs)?.click();
    }
  }
  if (canEdit && (isNew || rec.is_active)) {
    actions.appendChild(btn(T.save, 'md-btn-primary', () => save()));
    if (P.create) actions.appendChild(btn(T.saveNew, '', () => save('new')));
  }
  if (!isNew && P.create) actions.appendChild(btn(T.copy, '', () => { location.hash = `#/d/${code}/new?copy=${id}`; }));
  if (!isNew && code === 'items') {
    actions.appendChild(btn('🏷️ Печать бирки', '', () => download(`/labels/?ids=${id}`, {}, true)));
    if (rec.kit) actions.appendChild(btn('Комплект ' + esc(rec.kit__display.split(' ')[0]), '', () => { location.hash = `#/d/kits/${rec.kit}`; }));
    else actions.appendChild(btn('В комплект', '', () => { location.hash = `#/d/kits/new?item=${id}`; }));
  }
  if (!isNew && P.archive) {
    if (rec.is_active) actions.appendChild(btn(T.archive, '', async () => {
      if (!(await confirmDialog('Перенести запись в архив? Она будет скрыта из выбора, но сохранится для истории и отчётов.', T.archive))) return;
      try { await api(`/d/${code}/${id}/archive/`, { method: 'POST' }); toast('Запись в архиве'); S.opts = {}; router(); } catch (e) { errToast(e); }
    }));
    else actions.appendChild(btn(T.restore, 'md-btn-primary', async () => {
      try { await api(`/d/${code}/${id}/restore/`, { method: 'POST' }); toast('Запись восстановлена'); S.opts = {}; router(); } catch (e) { errToast(e); }
    }));
    actions.appendChild(btn(T.del, 'md-btn-danger', async () => {
      if (!(await confirmDialog('Удалить запись? Если на неё есть ссылки, она будет перенесена в архив.', T.del, true))) return;
      try { const r = await api(`/d/${code}/${id}/`, { method: 'DELETE' }); toast(r.message); S.opts = {}; location.hash = `#/d/${code}`; } catch (e) { errToast(e); }
    }));
  }
  const warn = sessionStorageGet('md.warn');
  if (warn) {
    sessionStorageSafe('md.warn', '');
    try { showWarnings($('#cd-msg', main), JSON.parse(warn)); } catch { /* пусто */ }
  }

  // ---- ленивые вкладки
  const LAZY = {
    photos: (pane) => photosTab(pane, code, id, P.update),
    items: (pane) => modelItemsTab(pane, rec),
    kits: (pane) => modelKitsTab(pane, rec),
    history: (pane) => historyTab(pane, code, id),
  };
}

function sessionStorageSafe(k, v) { try { sessionStorage.setItem(k, v); } catch { /* недоступно */ } }
function sessionStorageGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function showWarnings(box, list) {
  if (!list?.length) return;
  box.innerHTML = `<div class="md-warnbox">⚠️ ${list.map((w) => esc(w.message) + (w.id ? ` — <a href="#/d/clients/${w.id}">открыть</a>` : '')).join('<br>')}</div>`;
}

function wireModelCard(w, rec, isNew) {
  if (!w.category) return;
  w.category.onChange?.((val, o) => {
    if (o && w.operations && (isNew || !w.operations.get())) w.operations.set(o.operations);
    if (o && w.operations) {
      const allowed = o.operations;
      w.operations.warn(allowed !== 'both' ? [`Категория допускает только: ${allowed === 'sale' ? 'продажа' : 'аренда'}`] : []);
    }
  });
  w.manufacturer?.onChange?.(async (val, o) => {
    if (o?.country && w.country && !w.country.get()) {
      const c = (await getOptions('countries', { ids: o.country }))[0];
      if (c) w.country.set(c.id, c.label);
    }
  });
  const togglePrices = () => {
    const ops = w.operations?.get();
    if (w.rent_price) w.rent_price.el.classList.toggle('is-required', ops === 'rent' || ops === 'both');
    if (w.sale_price) w.sale_price.el.classList.toggle('is-required', ops === 'sale' || ops === 'both');
  };
  w.operations?.input?.addEventListener('change', togglePrices);
  togglePrices();
  void rec;
}

function wireClientCard(w, rec) {
  const check = debounce(async () => {
    const phone = w.phone?.get(); const name = w.full_name?.get();
    if (!phone && !name) return;
    try {
      const res = (await api('/clients/check-duplicates/', { query: { phone: phone || '', full_name: name || '', exclude: rec.id || '' } })).data;
      w.phone?.warn(res.filter((x) => x.field === 'phone').map((x) => `${esc(x.message)} — <a href="#/d/clients/${x.id}">открыть</a>`));
      w.full_name?.warn(res.filter((x) => x.field === 'full_name').map((x) => `${esc(x.message)} — <a href="#/d/clients/${x.id}">открыть</a>`));
    } catch { /* без предупреждений */ }
  }, 400);
  w.phone?.input?.addEventListener('blur', check);
  w.full_name?.input?.addEventListener('blur', check);
}

function renderItemHero(box, r) {
  box.innerHTML = `<div class="md-panel" style="margin-bottom:14px"><div class="md-item-hero">
    ${r.main_photo ? `<img src="${esc(r.main_photo.thumb_300)}" alt="">` : '<img alt="">'}
    <div style="flex:1;min-width:0"><div class="md-item-tag">${esc(r.tag)}</div>
      <div style="font-size:16px;font-weight:600">${esc(r.article)}</div>
      <div class="md-muted"><a href="#/d/models/${r.model}">${esc(r.model__name)}</a></div></div>
    <dl class="md-kv"><dt>Стадия</dt><dd>${esc(r.stage__display)}</dd><dt>Салон</dt><dd>${esc(r.salon__display)}</dd>
      <dt>Статус</dt><dd>${esc(r.status__display)}</dd>
      ${r.effective_prices ? `<dt>Аренда</dt><dd>${esc(fmtMoney(r.effective_prices.rent_price))}${r.effective_prices.min_rent_price ? ` <span class="md-muted">(мин. ${esc(fmtMoney(r.effective_prices.min_rent_price))})</span>` : ''}</dd>` : ''}
      <dt>Ресурс</dt><dd>${r.rent_count} аренд, осталось ${r.resource_left ?? '—'}</dd>
      ${r.kit ? `<dt>Комплект</dt><dd><a href="#/d/kits/${r.kit}">${esc(r.kit__display)}</a></dd>` : ''}</dl>
  </div></div>`;
}

// Состав комплекта: роль + экземпляр с подсказкой по категории роли (МД-18)
function kitComponentsWidget(rec, readonly, kitId) {
  const wrap = el('<div class="md-field is-wide is-required" data-field="components"><label>Состав комплекта</label></div>');
  const table = el(`<div class="md-table-wrap"><table class="md-table"><thead><tr><th style="width:170px">Роль</th><th>Экземпляр</th>
    <th style="width:140px">Цена аренды</th><th style="width:40px"></th></tr></thead><tbody></tbody></table></div>`);
  const errEl = el('<div class="md-error" hidden></div>');
  wrap.append(table, errEl);
  let rows = (rec.components || []).map((c) => ({ ...c }));
  const roles = [['base', 'База'], ['dress', 'Платье'], ['kamzol', 'Қамзол'], ['takiya', 'Тақия'], ['saukele', 'Сәукеле'],
    ['corset', 'Корсет'], ['shapan', 'Шапан'], ['veil', 'Фата'], ['bolero', 'Болеро'], ['other', 'Прочее']];
  let catIds = null;
  async function catFor(role) {
    if (!catIds) { catIds = {}; (await getOptions('categories')).forEach((c) => { catIds[c.label.split(' / ').pop()] = c.id; }); }
    return catIds[ROLE_CATEGORY[role]] || '';
  }
  const tbody = $('tbody', table);
  function render() {
    tbody.innerHTML = '';
    rows.forEach((r, i) => {
      const tr = el(`<tr style="cursor:default"><td><select class="md-select" ${readonly ? 'disabled' : ''}>${roles.map(([v, l]) =>
        `<option value="${v}" ${r.role === v ? 'selected' : ''}>${l}</option>`).join('')}</select></td><td></td>
        <td class="md-num">${esc(fmtMoney(r.rent_price))}</td>
        <td>${readonly ? '' : '<button type="button" class="md-btn md-btn-sm md-btn-ghost" title="Убрать">✕</button>'}</td></tr>`);
      const f = { code: 'item', type: 'ref', ref_directory: 'items', name: '' };
      const ref = refWidget('kc' + i, f, r.item, r.tag ? `${r.tag} · ${r.article} · ${r.name || ''}` : '', readonly, {
        refParams: () => ({ free: '1', ...(kitId && kitId !== 'new' ? { kit: kitId } : {}), ...(r._cat ? { category: r._cat } : {}) }),
      });
      ref.onChange((v, o) => { r.item = v; if (o) { const p = o.label.split(' · '); r.tag = p[0]; r.article = p[1]; r.name = p[2]; } });
      $$('td', tr)[1].appendChild(ref.el);
      $('select', tr).onchange = async (e) => { r.role = e.target.value; r._cat = await catFor(r.role); };
      catFor(r.role).then((c) => { r._cat = c; });
      const rm = $('button', tr);
      if (rm) rm.onclick = () => { rows.splice(i, 1); render(); };
      tbody.appendChild(tr);
    });
    if (!rows.length) tbody.appendChild(el('<tr><td class="md-empty" colspan="4">Добавьте экземпляры в состав</td></tr>'));
  }
  render();
  if (!readonly) {
    const add = btn('+ Добавить экземпляр', 'md-btn-sm', () => { rows.push({ role: rows.length ? 'other' : 'base', item: null }); render(); });
    add.style.marginTop = '8px'; add.style.alignSelf = 'flex-start';
    wrap.insertBefore(add, errEl);
  }
  return {
    el: wrap, f: { code: 'components' },
    get: () => rows.filter((r) => r.item).map((r) => ({ item: r.item, role: r.role })),
    error(msgs) { errEl.hidden = !msgs?.length; errEl.textContent = (msgs || []).join('; '); },
    warn() {},
  };
}

// ---- Фото (МД-19): перетаскивание, тип, порядок, главное, превью
async function photosTab(pane, code, id, canEdit) {
  const types = await getOptions('photo_types').catch(() => []);
  pane.innerHTML = `${canEdit ? `<label class="md-drop" id="ph-drop"><input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.heic,.heif,image/*" hidden>
    Перетащите фото сюда или нажмите, чтобы выбрать. JPG, PNG, WEBP, HEIC — до 15 МБ на файл.</label>` : ''}<div class="md-photos" id="ph-grid"></div>`;
  const grid = $('#ph-grid', pane);
  async function load() {
    const list = (await api(`/d/${code}/${id}/photos/`)).data;
    grid.innerHTML = list.length ? '' : `<div class="md-muted">Фото пока нет</div>`;
    list.forEach((p) => {
      const card = el(`<div class="md-photo ${p.is_main ? 'is-main' : ''}" draggable="${canEdit}" data-id="${p.id}">
        <a href="${esc(p.url)}" target="_blank" rel="noopener"><img src="${esc(p.thumb_300)}" alt="${esc(p.name)}" loading="lazy"></a>
        <div class="md-photo-bar">${canEdit ? `<select class="md-select"><option value="">Тип фото…</option>${types.map((t) =>
          `<option value="${t.id}" ${t.id === p.photo_type ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}</select>
          <div class="md-row" style="gap:4px"><button type="button" class="md-btn md-btn-sm" data-main ${p.is_main ? 'disabled' : ''}>${p.is_main ? '★ Главное' : '☆ Сделать главным'}</button>
          <button type="button" class="md-btn md-btn-sm md-btn-danger" data-del title="Удалить">✕</button></div>`
          : `<span class="md-muted">${esc(p.photo_type__display || '')}${p.is_main ? ' ★' : ''}</span>`}</div></div>`);
      if (canEdit) {
        $('select', card).onchange = (e) => api(`/photos/${p.id}/`, { method: 'PATCH', body: { photo_type: e.target.value || null } }).catch(errToast);
        $('[data-main]', card).onclick = async () => { await api(`/photos/${p.id}/`, { method: 'PATCH', body: { is_main: true } }); load(); };
        $('[data-del]', card).onclick = async () => { if (await confirmDialog('Удалить фото?', T.del, true)) { await api(`/photos/${p.id}/`, { method: 'DELETE' }); load(); } };
        card.addEventListener('dragstart', (e) => { card.classList.add('is-dragging'); e.dataTransfer.setData('text/plain', p.id); });
        card.addEventListener('dragend', () => card.classList.remove('is-dragging'));
        card.addEventListener('dragover', (e) => e.preventDefault());
        card.addEventListener('drop', async (e) => {
          e.preventDefault();
          const from = e.dataTransfer.getData('text/plain');
          if (!from || from === p.id) return;
          const ids = $$('.md-photo', grid).map((x) => x.dataset.id).filter((x) => x !== from);
          ids.splice(ids.indexOf(p.id), 0, from);
          await api('/photos/reorder/', { method: 'POST', body: { ids } });
          load();
        });
      }
      grid.appendChild(card);
    });
  }
  async function upload(files) {
    if (!files.length) return;
    const fd = new FormData();
    [...files].forEach((f) => fd.append('files', f));
    toast(`Загрузка: ${files.length} шт.…`);
    try { await api(`/d/${code}/${id}/photos/`, { method: 'POST', form: fd }); toast('Фото загружены'); load(); } catch (e) { errToast(e); }
  }
  const drop = $('#ph-drop', pane);
  if (drop) {
    const inp = $('input', drop);
    inp.onchange = () => upload(inp.files);
    drop.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); drop.classList.add('is-over'); } });
    drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('is-over'); upload(e.dataTransfer.files); });
  }
  load();
}

// ---- Экземпляры модели (МД-16)
async function modelItemsTab(pane, model) {
  const imeta = await getMeta('items');
  pane.innerHTML = `<div class="md-row" style="margin-bottom:10px">${imeta.permissions.create ? '<button type="button" class="md-btn md-btn-primary" id="mi-add">+ Добавить экземпляры</button>' : ''}
    <button type="button" class="md-btn" id="mi-labels">🏷️ Печать бирок</button></div><div id="mi-list"></div>`;
  let rows = [];
  async function load() {
    rows = (await api('/d/items/', { query: { model: model.id, page_size: 200, archived: '1' } })).data;
    $('#mi-list', pane).innerHTML = `<div class="md-table-wrap"><table class="md-table"><thead><tr><th>Бирка</th><th>Артикул</th><th>Размер</th>
      <th>Салон</th><th>Стадия</th><th>Статус</th><th>Аренд</th></tr></thead><tbody>${rows.length ? rows.map((r) => `
      <tr data-id="${r.id}" class="${r.is_active ? '' : 'is-archived'}"><td><b>${esc(r.tag)}</b></td><td>${esc(r.article)}</td>
      <td>${esc(r.size__display)}</td><td>${esc(r.salon__display)}</td><td>${esc(r.stage__display)}</td><td>${esc(r.status__display)}</td>
      <td class="md-num">${r.rent_count}</td></tr>`).join('') : `<tr><td class="md-empty" colspan="7">Экземпляров пока нет</td></tr>`}</tbody></table></div>`;
    $$('tr[data-id]', pane).forEach((tr) => { tr.onclick = () => { location.hash = `#/d/items/${tr.dataset.id}`; }; });
  }
  $('#mi-labels', pane).onclick = () => { const ids = rows.filter((r) => r.is_active).map((r) => r.id); if (ids.length) download(`/labels/?ids=${ids.join(',')}`, {}, true); else toast('Нет экземпляров'); };
  const add = $('#mi-add', pane);
  if (add) add.onclick = () => addItemsDialog(model, imeta, load);
  load();
}

async function addItemsDialog(model, imeta, done) {
  const sizes = await getOptions('sizes');
  const salons = await getOptions('salons');
  const sizeReq = model.effective?.size_required;
  const fieldCodes = imeta.fields.map((f) => f.code);
  const body = el(`<div>
    <p class="md-muted" style="margin-top:0">Укажите количество по каждому размеру. Общие поля заполняются один раз для всех экземпляров.</p>
    <div class="md-form" id="ai-sizes" style="grid-template-columns:repeat(auto-fill,minmax(110px,1fr))">
      ${sizes.map((s) => `<div class="md-field"><label>Размер ${esc(s.label)}</label><input class="md-input" inputmode="numeric" data-size="${s.id}" placeholder="0"></div>`).join('')}
      ${sizeReq ? '' : '<div class="md-field"><label>Без размера</label><input class="md-input" inputmode="numeric" data-size="" placeholder="0"></div>'}
    </div>
    <div class="md-form" style="margin-top:16px" id="ai-common"></div></div>`);
  const common = $('#ai-common', body);
  const w = {};
  const add = (f, v) => { w[f.code] = widget(f, v, {}); common.appendChild(w[f.code].el); };
  add({ code: 'salon', name: 'Салон', type: 'choice', required: true, options: salons.map((s) => ({ value: s.id, label: s.label })) }, salons[0]?.id);
  if (fieldCodes.includes('supplier')) add({ code: 'supplier', name: 'Поставщик', type: 'ref', ref_directory: 'counterparties', required: model.acquisition === 'purchase' }, null);
  add({ code: 'received_at', name: 'Дата поступления', type: 'date', required: true }, new Date().toISOString().slice(0, 10));
  if (fieldCodes.includes('cost')) add({ code: 'cost', name: 'Стоимость поступления (за 1 шт.), ₸', type: 'money' }, null);
  add({ code: 'condition', name: 'Состояние', type: 'choice', required: true, options: [{ value: 'new', label: 'Новое' }, { value: 'used', label: 'Б/у' }] }, 'new');
  const err = el('<div class="md-errbox" hidden></div>');
  body.prepend(err);
  const m = modal({
    title: `Добавить экземпляры — ${model.article}`, body, wide: true,
    foot: [btn(T.cancel, '', () => m.close()), btn('Создать экземпляры', 'md-btn-primary', async () => {
      const lines = $$('[data-size]', body).map((i) => ({ size: i.dataset.size || null, qty: Number(i.value || 0) })).filter((l) => l.qty > 0);
      const payload = { sizes: lines };
      Object.entries(w).forEach(([k, x]) => { const v = x.get(); if (!isEmpty(v)) payload[k] = v; });
      try {
        const created = (await api(`/d/models/${model.id}/add-items/`, { method: 'POST', body: payload })).data;
        m.close();
        toast(`Создано экземпляров: ${created.length}`);
        done();
        if (await confirmDialog(`Создано ${created.length} шт.: ${created.map((c) => c.tag).join(', ')}. Напечатать бирки?`, 'Печать')) {
          download(`/labels/?ids=${created.map((c) => c.id).join(',')}`, {}, true);
        }
      } catch (e) {
        err.hidden = false;
        err.textContent = e.message + (e.data?.fields ? ': ' + Object.entries(e.data.fields).map(([k, v]) => `${k} — ${v.join('; ')}`).join('; ') : '');
      }
    })],
  });
}

async function modelKitsTab(pane, model) {
  const rows = (await api('/d/kits/', { query: { model: model.id, page_size: 100, archived: '1' } })).data;
  pane.innerHTML = rows.length ? `<div class="md-table-wrap"><table class="md-table"><thead><tr><th>Код</th><th>Наименование</th><th>Состав</th></tr></thead>
    <tbody>${rows.map((r) => `<tr data-id="${r.id}" class="${r.is_active ? '' : 'is-archived'}"><td><b>${esc(r.code)}</b></td><td>${esc(r.name)}</td>
    <td>${(r.components || []).map((c) => `<span class="md-chip">${esc(c.role__display)}: ${esc(c.tag)}</span>`).join(' ')}</td></tr>`).join('')}</tbody></table></div>`
    : '<div class="md-muted">Экземпляры этой модели не входят в комплекты</div>';
  $$('tr[data-id]', pane).forEach((tr) => { tr.onclick = () => { location.hash = `#/d/kits/${tr.dataset.id}`; }; });
}

// ---- История (МД-22)
async function historyTab(pane, code, id) {
  try {
    const rows = (await api(`/d/${code}/${id}/history/`)).data;
    pane.innerHTML = rows.length ? `<div class="md-table-wrap"><table class="md-table"><thead><tr><th>Дата</th><th>Пользователь</th>
      <th>Действие</th><th>Поле</th><th>Было</th><th>Стало</th></tr></thead><tbody>${rows.map((r) => {
      const ch = r.changes.length ? r.changes : [{ label: '', old: '', new: '' }];
      return ch.map((c, i) => `<tr style="cursor:default">${i === 0 ? `<td rowspan="${ch.length}">${esc(fmtDateTime(r.at))}</td>
        <td rowspan="${ch.length}">${esc(r.user)}</td><td rowspan="${ch.length}">${esc(r.action__display)}${r.source === 'import' ? ' <span class="md-badge">импорт</span>' : ''}</td>` : ''}
        <td>${esc(c.label)}</td><td class="md-muted">${esc(c.old)}</td><td>${esc(c.new)}</td></tr>`).join('');
    }).join('')}</tbody></table></div>` : '<div class="md-muted">Изменений нет</div>';
  } catch (e) { pane.innerHTML = `<div class="md-errbox">${esc(e.message)}</div>`; }
}

// ============================================================
// Конструктор справочников (МД-1…12)
// ============================================================
async function viewBuilder(main, _a, query) {
  const showArch = query.archived === '1';
  const dirs = (await api('/directories/', { query: { archived: showArch ? '1' : '' } })).data;
  main.innerHTML = `<div class="md-page-head"><h1>🛠️ Конструктор справочников</h1><span class="md-spacer"></span>
    <label class="md-check"><input type="checkbox" id="b-arch" ${showArch ? 'checked' : ''}> Показать архивные</label>
    <button type="button" class="md-btn" id="b-log">Журнал изменений структуры</button>
    <button type="button" class="md-btn md-btn-primary" id="b-new">+ Создать справочник</button></div><div id="b-list"></div>`;
  const list = $('#b-list', main);
  GROUPS.forEach(([g, title]) => {
    const items = dirs.filter((d) => d.menu_group === g);
    if (!items.length) return;
    const p = el(`<div class="md-panel"><h3>${esc(title)}</h3><div class="md-table-wrap"><table class="md-table"><thead><tr><th>Справочник</th><th>Код</th>
      <th>Тип</th><th>В меню</th></tr></thead><tbody></tbody></table></div></div>`);
    items.forEach((d) => {
      const tr = el(`<tr class="${d.is_active ? '' : 'is-archived'}"><td>${esc(d.icon)} <b>${esc(d.name)}</b>${d.is_active ? '' : ' <span class="md-badge">архив</span>'}</td>
        <td><code>${esc(d.code)}</code></td><td>${d.is_system ? '<span class="md-badge">системный</span>' : '<span class="md-badge md-badge-ok">пользовательский</span>'}</td>
        <td><input type="checkbox" ${d.menu_enabled ? 'checked' : ''} aria-label="Показывать в меню"></td></tr>`);
      const cb = $('input', tr);
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = async () => { try { await api(`/directories/${d.code}/`, { method: 'PATCH', body: { menu_enabled: cb.checked } }); await reloadMe(); renderNav(); } catch (e) { errToast(e); } };
      tr.onclick = () => { location.hash = `#/builder/${d.code}`; };
      $('tbody', p).appendChild(tr);
    });
    list.appendChild(p);
  });
  $('#b-arch', main).onchange = (e) => { location.hash = e.target.checked ? '#/builder?archived=1' : '#/builder'; };
  $('#b-new', main).onclick = () => newDirectoryDialog();
  $('#b-log', main).onclick = () => structureLogDialog();
}

function newDirectoryDialog(copyFrom) {
  const body = el(`<div class="md-form">
    <div class="md-field is-required"><label>Название</label><input class="md-input" data-k="name" value="${copyFrom ? esc(copyFrom.name + ' (копия)') : ''}"></div>
    <div class="md-field is-required"><label>Код (латиница)</label><input class="md-input" data-k="code" placeholder="fabrics"></div>
    ${copyFrom ? '' : `<div class="md-field"><label>Группа меню</label><select class="md-select" data-k="menu_group">${GROUPS.map(([v, l]) =>
      `<option value="${v}" ${v === 'custom' ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
    <div class="md-field"><label>Иконка</label><input class="md-input" data-k="icon" value="📁" maxlength="4"></div>
    <div class="md-field is-wide"><label>Описание</label><input class="md-input" data-k="description"></div>
    <div class="md-field"><label class="md-check"><input type="checkbox" data-k="is_hierarchical"> Иерархический (записи образуют дерево)</label></div>
    <div class="md-field"><label class="md-check"><input type="checkbox" data-k="supports_photo"> Поддержка фото</label></div>`}
    <div class="md-errbox is-wide" hidden style="grid-column:1/-1"></div></div>`);
  const name = $('[data-k=name]', body); const codeI = $('[data-k=code]', body);
  const translit = (s) => s.toLowerCase().replace(/[а-яёәғқңөұүһі]/g, (c) => ({ а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya', ә: 'a', ғ: 'g', қ: 'q', ң: 'n', ө: 'o', ұ: 'u', ү: 'u', һ: 'h', і: 'i' }[c])).replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, 'd$1').slice(0, 40);
  let touched = false;
  codeI.oninput = () => { touched = true; };
  name.oninput = () => { if (!touched) codeI.value = translit(name.value); };
  if (copyFrom) codeI.value = translit(name.value);
  const m = modal({
    title: copyFrom ? `Копия справочника «${copyFrom.name}» (структура без данных)` : 'Новый справочник', body,
    foot: [btn(T.cancel, '', () => m.close()), btn(copyFrom ? 'Скопировать' : T.create, 'md-btn-primary', async () => {
      const data = {};
      $$('[data-k]', body).forEach((i) => { data[i.dataset.k] = i.type === 'checkbox' ? i.checked : i.value; });
      try {
        const d = copyFrom ? (await api(`/directories/${copyFrom.code}/copy/`, { method: 'POST', body: data })).data
          : (await api('/directories/', { method: 'POST', body: data })).data;
        m.close(); await reloadMe(); location.hash = `#/builder/${d.code}`;
      } catch (e) {
        const box = $('.md-errbox', body); box.hidden = false;
        box.textContent = e.message + (e.data?.fields ? ': ' + Object.values(e.data.fields).flat().join('; ') : '');
      }
    })],
  });
}

async function structureLogDialog(code) {
  const rows = (await api(code ? `/directories/${code}/log/` : '/structure-log/')).data;
  const names = { directory_create: 'Создан справочник', directory_update: 'Изменены свойства', directory_archive: 'Справочник в архиве',
    directory_delete: 'Справочник удалён', directory_restore: 'Справочник восстановлен', directory_copy: 'Копия справочника',
    field_add: 'Добавлено поле', field_update: 'Изменено поле', field_archive: 'Поле удалено (значения в архиве)',
    field_delete: 'Поле удалено', field_restore: 'Поле восстановлено', fields_reorder: 'Изменён порядок полей',
    settings_update: 'Настройки организации', policies_update: 'Права ролей', member_set: 'Участник организации' };
  modal({ title: 'Журнал изменений структуры', wide: true, body: rows.length ? `<div class="md-table-wrap"><table class="md-table"><thead><tr><th>Дата</th><th>Пользователь</th>
    <th>Справочник</th><th>Действие</th><th>Подробности</th></tr></thead><tbody>${rows.map((r) => `<tr style="cursor:default"><td>${esc(fmtDateTime(r.at))}</td>
    <td>${esc(r.user)}</td><td><code>${esc(r.directory)}</code></td><td>${esc(names[r.action] || r.action)}</td>
    <td class="md-muted" style="font-size:12px">${esc(JSON.stringify(r.details)).slice(0, 300)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="md-muted">Записей нет</div>' });
}

const FIELD_TYPES = [['string', 'Строка'], ['text', 'Многострочный текст'], ['integer', 'Целое'], ['decimal', 'Дробное'],
  ['money', 'Деньги (₸)'], ['percent', 'Процент'], ['date', 'Дата'], ['datetime', 'Дата и время'], ['bool', 'Да/нет'],
  ['choice', 'Список значений'], ['ref', 'Ссылка на справочник'], ['phone', 'Телефон'], ['email', 'Email'],
  ['iin_bin', 'ИИН/БИН'], ['file', 'Файл']];

async function viewBuilderDir(main, [code]) {
  const dir = (await api(`/directories/${code}/`)).data;
  let fields = (await api(`/directories/${code}/fields/`, { query: { archived: '1' } })).data;
  const allDirs = (await api('/directories/')).data;
  let selected = fields.find((f) => !f.is_archived)?.id || null;
  let draft = null;
  main.innerHTML = `<div class="md-crumbs"><a href="#/builder">🛠️ Конструктор справочников</a></div>
    <div class="md-page-head"><h1>${esc(dir.icon)} ${esc(dir.name)}</h1>${dir.is_system ? '<span class="md-badge">системный</span>' : ''}
      ${dir.is_active ? '' : '<span class="md-badge md-badge-warn">в архиве</span>'}<span class="md-spacer"></span>
      <a class="md-btn" href="#/d/${code}">Открыть справочник</a>
      <button type="button" class="md-btn" id="bd-log">Журнал</button>
      <button type="button" class="md-btn" id="bd-copy">Копировать</button>
      ${dir.is_system ? '' : (dir.is_active ? '<button type="button" class="md-btn md-btn-danger" id="bd-del">Удалить</button>'
    : '<button type="button" class="md-btn md-btn-primary" id="bd-restore">Восстановить</button>')}</div>
    <div class="md-panel" id="bd-props"></div>
    <div class="md-builder" style="margin-top:16px">
      <div class="md-panel"><div class="md-row" style="justify-content:space-between;margin-bottom:10px"><h3 style="margin:0">Поля</h3>
        <button type="button" class="md-btn md-btn-sm md-btn-primary" id="bd-add">+ Поле</button></div>
        <div class="md-flist" id="bd-fields"></div>
        <p class="md-muted" style="font-size:12px;margin-bottom:0">Порядок — перетаскиванием. Системные поля нельзя удалить или сменить тип.</p></div>
      <div><div class="md-panel" id="bd-field"></div><div class="md-panel" id="bd-preview"><h3>Предпросмотр карточки</h3><div></div></div></div>
    </div>`;

  // ---- свойства справочника (МД-1, МД-2)
  const props = $('#bd-props', main);
  const dirFields = dir.is_system ? ['name', 'icon', 'description'] : ['name', 'icon', 'description', 'menu_group', 'display_field', 'is_hierarchical', 'supports_photo', 'supports_archive'];
  props.innerHTML = `<h3>Свойства справочника</h3><div class="md-form">
    <div class="md-field"><label>Название</label><input class="md-input" data-k="name" value="${esc(dir.name)}"></div>
    <div class="md-field"><label>Иконка</label><input class="md-input" data-k="icon" value="${esc(dir.icon)}" maxlength="4"></div>
    <div class="md-field is-wide"><label>Описание</label><input class="md-input" data-k="description" value="${esc(dir.description)}"></div>
    ${dir.is_system ? '' : `<div class="md-field"><label>Группа меню</label><select class="md-select" data-k="menu_group">${GROUPS.map(([v, l]) =>
      `<option value="${v}" ${v === dir.menu_group ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
    <div class="md-field"><label>Поле-представление (в выпадающих списках)</label><select class="md-select" data-k="display_field">${fields.filter((f) => !f.is_archived).map((f) =>
      `<option value="${f.code}" ${f.code === dir.display_field ? 'selected' : ''}>${esc(f.name)}</option>`).join('')}</select></div>
    <div class="md-field"><label class="md-check"><input type="checkbox" data-k="is_hierarchical" ${dir.is_hierarchical ? 'checked' : ''}> Иерархический</label></div>
    <div class="md-field"><label class="md-check"><input type="checkbox" data-k="supports_photo" ${dir.supports_photo ? 'checked' : ''}> Поддержка фото</label></div>
    <div class="md-field"><label class="md-check"><input type="checkbox" data-k="supports_archive" ${dir.supports_archive ? 'checked' : ''}> Поддержка архива</label></div>`}
    <div class="md-field"><label class="md-check"><input type="checkbox" data-k="menu_enabled" ${dir.menu_enabled ? 'checked' : ''}> Показывать в меню</label></div>
  </div><div class="md-row" style="margin-top:12px"><button type="button" class="md-btn md-btn-primary" id="bd-save-dir">Сохранить свойства</button></div>`;
  $('#bd-save-dir', props).onclick = async () => {
    const data = {};
    $$('[data-k]', props).forEach((i) => { if (dirFields.includes(i.dataset.k) || i.dataset.k === 'menu_enabled') data[i.dataset.k] = i.type === 'checkbox' ? i.checked : i.value; });
    try { await api(`/directories/${code}/`, { method: 'PATCH', body: data }); toast(T.saved); dropCaches(code); await reloadMe(); renderNav(); } catch (e) { errToast(e); }
  };
  $('#bd-log', main).onclick = () => structureLogDialog(code);
  $('#bd-copy', main).onclick = () => newDirectoryDialog(dir);
  const del = $('#bd-del', main);
  if (del) del.onclick = async () => {
    if (!(await confirmDialog('Удалить справочник? Если в нём есть записи или на него ссылаются другие справочники, он будет перенесён в архив.', T.del, true))) return;
    try { const r = await api(`/directories/${code}/`, { method: 'DELETE' }); toast(r.message); await reloadMe(); location.hash = '#/builder'; } catch (e) { errToast(e); }
  };
  const rs = $('#bd-restore', main);
  if (rs) rs.onclick = async () => { await api(`/directories/${code}/restore/`, { method: 'POST' }); await reloadMe(); router(); };

  const flist = $('#bd-fields', main);
  function renderList() {
    flist.innerHTML = '';
    const items = draft ? [...fields, draft] : fields;
    items.forEach((f) => {
      const it = el(`<div class="md-fitem ${f.id === selected ? 'is-active' : ''} ${f.is_archived ? 'is-archived' : ''}" draggable="${!f.is_archived && !f._draft}" data-id="${f.id}">
        <span class="md-drag">⋮⋮</span><div style="flex:1;min-width:0"><b>${esc(f.name || 'Новое поле')}</b>${f.required ? ' <span style="color:var(--neg)">*</span>' : ''}
        <br><small>${esc(f.type__display || f.type)} · ${esc(f.code || '—')}${f.is_system ? ' · системное' : ''}${f.is_archived ? ' · удалено' : ''}</small></div></div>`);
      it.onclick = () => { selected = f.id; renderList(); renderField(); };
      it.addEventListener('dragstart', (e) => e.dataTransfer.setData('text/plain', f.id));
      it.addEventListener('dragover', (e) => { e.preventDefault(); it.classList.add('is-over'); });
      it.addEventListener('dragleave', () => it.classList.remove('is-over'));
      it.addEventListener('drop', async (e) => {
        e.preventDefault(); it.classList.remove('is-over');
        const from = e.dataTransfer.getData('text/plain');
        if (!from || from === f.id) return;
        const ids = fields.map((x) => x.id).filter((x) => x !== from);
        ids.splice(ids.indexOf(f.id), 0, from);
        await api(`/directories/${code}/fields/reorder/`, { method: 'POST', body: { ids } });
        fields = ids.map((i) => fields.find((x) => x.id === i));
        dropCaches(code); renderList(); renderPreview();
      });
      flist.appendChild(it);
    });
  }
  function renderPreview() {
    const box = $('#bd-preview > div', main);
    box.innerHTML = '';
    const groups = {};
    fields.filter((f) => !f.is_archived).forEach((f) => { (groups[f.group || 'Основное'] = groups[f.group || 'Основное'] || []).push(f); });
    Object.entries(groups).forEach(([g, list]) => {
      box.appendChild(el(`<div class="md-muted" style="margin:10px 0 6px;font-weight:600">${esc(g)}</div>`));
      const form = el('<div class="md-form"></div>');
      list.forEach((f) => { if (f.code !== 'components') form.appendChild(widget({ ...f, readonly: true }, f.multiple ? [] : f.default, { readonly: true }).el); });
      box.appendChild(form);
    });
  }
  function renderField() {
    const box = $('#bd-field', main);
    const f = draft && selected === draft.id ? draft : fields.find((x) => x.id === selected);
    if (!f) { box.innerHTML = '<div class="md-muted">Выберите поле слева или добавьте новое</div>'; return; }
    const sys = f.is_system;
    const dis = (k) => (sys && !['name', 'group', 'hint', 'show_in_list', 'searchable', 'filterable'].includes(k)) || f.is_archived ? 'disabled' : '';
    const v = f.validation || {};
    box.innerHTML = `<h3>${f._draft ? 'Новое поле' : 'Свойства поля'}</h3><div class="md-form">
      <div class="md-field is-required"><label>Название</label><input class="md-input" data-k="name" value="${esc(f.name)}" ${dis('name')}></div>
      <div class="md-field is-required"><label>Код (латиница)</label><input class="md-input" data-k="code" value="${esc(f.code)}" ${f._draft ? '' : 'disabled'}></div>
      <div class="md-field"><label>Тип</label><select class="md-select" data-k="type" ${dis('type')}>${(sys ? [[f.type, f.type__display]] : FIELD_TYPES).map(([t, l]) =>
        `<option value="${t}" ${t === f.type ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
      <div class="md-field"><label>Группа (вкладка карточки)</label><input class="md-input" data-k="group" value="${esc(f.group || 'Основное')}" ${dis('group')}></div>
      <div class="md-field is-wide"><label>Подсказка</label><input class="md-input" data-k="hint" value="${esc(f.hint || '')}" ${dis('hint')}></div>
      <div class="md-field" data-show="choice ref string"><label class="md-check"><input type="checkbox" data-k="multiple" ${f.multiple ? 'checked' : ''} ${dis('multiple')}> Несколько значений</label></div>
      <div class="md-field" data-show="ref"><label>Справочник для ссылки</label><select class="md-select" data-k="ref_directory" ${dis('ref_directory')}><option value="">—</option>${allDirs.map((d) =>
        `<option value="${d.code}" ${d.code === f.ref_directory ? 'selected' : ''}>${esc(d.name)}</option>`).join('')}</select></div>
      <div class="md-field is-wide" data-show="choice"><label>Значения списка (по одному в строке)</label><textarea class="md-textarea" data-k="options" ${dis('options')}>${esc((f.options || []).map((o) => o.label).join('\n'))}</textarea></div>
      <div class="md-field" data-show="string text phone email"><label>Мин. длина</label><input class="md-input" data-v="min_len" value="${esc(v.min_len ?? '')}" ${dis('validation')}></div>
      <div class="md-field" data-show="string text phone email"><label>Макс. длина</label><input class="md-input" data-v="max_len" value="${esc(v.max_len ?? '')}" ${dis('validation')}></div>
      <div class="md-field is-wide" data-show="string"><label>Маска (регулярное выражение)</label><input class="md-input" data-v="mask" value="${esc(v.mask ?? '')}" ${dis('validation')} placeholder="^[A-Z]{2}-\\d{3}$"></div>
      <div class="md-field" data-show="integer decimal money percent"><label>Минимум</label><input class="md-input" data-v="min" value="${esc(v.min ?? '')}" ${dis('validation')}></div>
      <div class="md-field" data-show="integer decimal money percent"><label>Максимум</label><input class="md-input" data-v="max" value="${esc(v.max ?? '')}" ${dis('validation')}></div>
      <div class="md-field" data-show="string text integer decimal money percent date choice"><label>Значение по умолчанию</label><input class="md-input" data-k="default" value="${esc(f.default ?? '')}" ${dis('default')}></div>
      <div class="md-row">
        <label class="md-check"><input type="checkbox" data-k="required" ${f.required ? 'checked' : ''} ${dis('required')}> Обязательное</label>
        <label class="md-check"><input type="checkbox" data-k="unique" ${f.unique ? 'checked' : ''} ${dis('unique')}> Уникальное</label>
        <label class="md-check"><input type="checkbox" data-k="show_in_list" ${f.show_in_list ? 'checked' : ''} ${dis('show_in_list')}> В списке</label>
        <label class="md-check"><input type="checkbox" data-k="searchable" ${f.searchable ? 'checked' : ''} ${dis('searchable')}> В поиске</label>
        <label class="md-check"><input type="checkbox" data-k="filterable" ${f.filterable ? 'checked' : ''} ${dis('filterable')}> В фильтре</label>
      </div></div>
      <div class="md-row" style="margin-top:14px">${f.is_archived ? '<button type="button" class="md-btn md-btn-primary" data-act="restore">Восстановить поле</button>'
      : `<button type="button" class="md-btn md-btn-primary" data-act="save">${f._draft ? 'Добавить поле' : T.save}</button>
         ${!sys && !f._draft ? '<button type="button" class="md-btn md-btn-danger" data-act="delete">Удалить поле</button>' : ''}
         ${f._draft ? `<button type="button" class="md-btn" data-act="cancel">${T.cancel}</button>` : ''}`}</div>`;
    const typeSel = $('[data-k=type]', box);
    const nameI = $('[data-k=name]', box); const codeI = $('[data-k=code]', box);
    if (f._draft) nameI.oninput = () => { codeI.value = nameI.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || codeI.value; };
    const toggle = () => { $$('[data-show]', box).forEach((x) => { x.hidden = !x.dataset.show.split(' ').includes(typeSel.value); }); };
    typeSel.onchange = toggle; toggle();
    const collect = () => {
      const d = {};
      $$('[data-k]', box).forEach((i) => {
        if (i.disabled || i.closest('[hidden]')) return;
        const k = i.dataset.k;
        if (k === 'options') d.options = i.value.split('\n').map((s) => s.trim()).filter(Boolean).map((s) => ({ value: s, label: s }));
        else if (i.type === 'checkbox') d[k] = i.checked;
        else if (k === 'default') d.default = i.value === '' ? null : i.value;
        else d[k] = i.value;
      });
      const val = {};
      $$('[data-v]', box).forEach((i) => { if (!i.disabled && !i.closest('[hidden]') && i.value !== '') val[i.dataset.v] = i.value; });
      if (!sys) d.validation = val;
      if (!f._draft) delete d.code;
      return d;
    };
    $$('[data-act]', box).forEach((b) => {
      b.onclick = async () => {
        try {
          if (b.dataset.act === 'cancel') { draft = null; selected = fields[0]?.id; }
          else if (b.dataset.act === 'save') {
            const d = collect();
            if (f._draft) { const nf = (await api(`/directories/${code}/fields/`, { method: 'POST', body: d })).data; fields.push(nf); draft = null; selected = nf.id; }
            else { const nf = (await api(`/directories/${code}/fields/${f.id}/`, { method: 'PATCH', body: d })).data; fields = fields.map((x) => (x.id === nf.id ? nf : x)); }
            toast(T.saved); dropCaches(code);
          } else if (b.dataset.act === 'delete') {
            if (!(await confirmDialog(`Удалить поле «${f.name}»?`, T.del, true))) return;
            try { await api(`/directories/${code}/fields/${f.id}/`, { method: 'DELETE' }); } catch (e) {
              if (e.data?.requires_confirm) {
                if (!(await confirmDialog(e.message, 'Удалить и архивировать значения', true))) return;
                await api(`/directories/${code}/fields/${f.id}/?confirm=1`, { method: 'DELETE' });
              } else throw e;
            }
            fields = (await api(`/directories/${code}/fields/`, { query: { archived: '1' } })).data;
            selected = fields.find((x) => !x.is_archived)?.id; dropCaches(code); toast('Поле удалено');
          } else if (b.dataset.act === 'restore') {
            const nf = (await api(`/directories/${code}/fields/${f.id}/restore/`, { method: 'POST' })).data;
            fields = fields.map((x) => (x.id === nf.id ? nf : x)); dropCaches(code);
          }
          renderList(); renderField(); renderPreview();
        } catch (e) {
          errToast(e);
          Object.entries(e.data?.fields || {}).forEach(([k, msgs]) => { const i = $(`[data-k=${k}]`, box); if (i) { i.closest('.md-field')?.classList.add('has-error'); i.title = msgs.join('; '); } });
        }
      };
    });
  }
  $('#bd-add', main).onclick = () => {
    draft = { id: '_new', _draft: true, name: '', code: '', type: 'string', group: 'Основное', show_in_list: true, options: [], validation: {} };
    selected = '_new'; renderList(); renderField();
  };
  renderList(); renderField(); renderPreview();
}

// ============================================================
// Импорт — мастер из 4 шагов (МД-25…35)
// ============================================================
async function viewImport(main, _a, query) {
  const dirs = (S.me.menu || []).filter((d) => d.permissions?.import);
  const st = { dir: query.d && dirs.some((d) => d.code === query.d) ? query.d : (dirs[0]?.code || ''), step: 1, up: null, job: null };
  main.innerHTML = `<div class="md-page-head"><h1>📥 Импорт данных</h1><span class="md-spacer"></span><a class="md-btn" href="#/import/jobs">Журнал загрузок</a></div>
    <div class="md-steps" id="im-steps"></div><div id="im-body"></div>
    ${dirs.some((d) => d.code === 'models') ? `<div class="md-panel" style="margin-top:16px"><h3>Фото из ZIP-архива</h3>
      <p class="md-muted" style="margin-top:0">Имя файла — артикул модели или бирка экземпляра с порядковым номером: <code>СВ-117_1.jpg</code>, <code>СВ-117_2.jpg</code>. Фото №1 станет главным.</p>
      <label class="md-btn">Выбрать ZIP…<input type="file" accept=".zip" id="im-zip" hidden></label><div id="im-zip-res" style="margin-top:10px"></div></div>` : ''}`;
  if (!dirs.length) { $('#im-body', main).innerHTML = '<div class="md-panel md-muted">Нет справочников, доступных вам для импорта</div>'; return; }
  const steps = ['Файл', 'Сопоставление колонок', 'Предпросмотр и ошибки', 'Результат'];
  const body = $('#im-body', main);
  const drawSteps = () => { $('#im-steps', main).innerHTML = steps.map((s, i) => `<span class="md-step ${i + 1 === st.step ? 'is-active' : ''} ${i + 1 < st.step ? 'is-done' : ''}"><b>${i + 1}</b>${s}</span>`).join(''); };

  function step1() {
    st.step = 1; drawSteps();
    body.innerHTML = `<div class="md-panel"><div class="md-form">
      <div class="md-field"><label>Справочник</label><select class="md-select" id="im-dir">${dirs.map((d) => `<option value="${d.code}" ${d.code === st.dir ? 'selected' : ''}>${esc(d.icon)} ${esc(d.name)}</option>`).join('')}</select></div>
      <div class="md-field"><label>Шаблон</label><button type="button" class="md-btn" id="im-tpl">⬇ Скачать XLSX-шаблон</button></div>
      <div class="md-field is-wide"><label>Файл (XLSX или CSV в UTF-8, разделитель «;» или «,», до 10 000 строк)</label>
        <label class="md-drop" id="im-drop"><input type="file" accept=".xlsx,.csv" hidden>Перетащите файл сюда или нажмите, чтобы выбрать</label></div>
    </div>${st.dir === 'items' ? '<p class="md-muted">Экземпляры: одна строка — один экземпляр; модель находится по колонке «Модель: артикул» или создаётся из колонок «Модель: …». Так переносится весь каталог (СВ-117, СВ-128…) одной загрузкой.</p>' : ''}</div>`;
    $('#im-dir', body).onchange = (e) => { st.dir = e.target.value; history.replaceState(null, '', `#/import?d=${st.dir}`); step1(); };
    $('#im-tpl', body).onclick = () => download(`/d/${st.dir}/template/`);
    const drop = $('#im-drop', body); const inp = $('input', drop);
    const send = async (file) => {
      if (!file) return;
      const fd = new FormData(); fd.append('directory', st.dir); fd.append('file', file);
      drop.textContent = 'Чтение файла…';
      try { st.up = (await api('/import/upload/', { method: 'POST', form: fd })).data; step2(); } catch (e) { errToast(e); step1(); }
    };
    inp.onchange = () => send(inp.files[0]);
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('is-over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); send(e.dataTransfer.files[0]); });
  }

  function step2() {
    st.step = 2; drawSteps();
    const up = st.up;
    const mapping = { ...up.mapping };
    body.innerHTML = `<div class="md-panel"><div class="md-row" style="margin-bottom:12px"><b>${esc(up.job.file)}</b>
      <span class="md-muted">строк: ${up.job.total_rows}</span><span class="md-spacer" style="flex:1"></span>
      ${up.profiles.length ? `<select class="md-select" id="im-prof" style="width:auto"><option value="">Профиль сопоставления…</option>${up.profiles.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>` : ''}</div>
      <div class="md-table-wrap"><table class="md-table"><thead><tr><th>Колонка файла</th><th>Пример значений</th><th>Поле справочника</th></tr></thead><tbody id="im-map"></tbody></table></div>
      <div class="md-form" style="margin-top:16px">
        <div class="md-field"><label>Режим</label><select class="md-select" id="im-mode"><option value="create">Только создание</option><option value="update">Только обновление</option><option value="upsert">Создание и обновление</option></select></div>
        <div class="md-field"><label>Ключ сопоставления</label><select class="md-select" id="im-key">${up.keys.map((k) => `<option value="${k.value}">${esc(k.label)}</option>`).join('')}</select></div>
        <div class="md-field"><label class="md-check"><input type="checkbox" id="im-missing"> Создавать недостающие значения справочников</label>
          <span class="md-hint">Для простых справочников (мероприятия, виды, цвета, производители…). По умолчанию выключено.</span></div>
        <div class="md-field"><label>Сохранить сопоставление как профиль</label><input class="md-input" id="im-pname" placeholder="Название профиля (необязательно)"></div>
      </div><div class="md-row" style="margin-top:14px"><button type="button" class="md-btn" id="im-back">← Другой файл</button>
      <button type="button" class="md-btn md-btn-primary" id="im-check">Проверить →</button></div></div>`;
    const tbody = $('#im-map', body);
    const draw = () => {
      tbody.innerHTML = up.headers.map((h, i) => `<tr style="cursor:default"><td><b>${esc(h || '(без названия)')}</b></td>
        <td class="md-muted" style="font-size:12.5px">${up.sample.map((r) => esc(r[i])).filter(Boolean).slice(0, 3).join(' · ')}</td>
        <td><select class="md-select" data-h="${esc(h)}"><option value="">— не загружать —</option>${up.columns.map((c) =>
          `<option value="${c.key}" ${mapping[h] === c.key ? 'selected' : ''}>${esc(c.label)}${c.required ? ' *' : ''}</option>`).join('')}</select></td></tr>`).join('');
      $$('select', tbody).forEach((s) => { s.onchange = () => { if (s.value) mapping[s.dataset.h] = s.value; else delete mapping[s.dataset.h]; }; });
    };
    draw();
    const prof = $('#im-prof', body);
    if (prof) prof.onchange = () => { const p = up.profiles.find((x) => String(x.id) === prof.value); if (p) { Object.keys(mapping).forEach((k) => delete mapping[k]); Object.assign(mapping, p.mapping); draw(); } };
    $('#im-back', body).onclick = step1;
    $('#im-check', body).onclick = async () => {
      const missing = up.columns.filter((c) => c.required && !Object.values(mapping).includes(c.key));
      if (missing.length && !(await confirmDialog(`Не сопоставлены обязательные поля: ${missing.map((c) => c.label).join(', ')}. Продолжить проверку?`, 'Проверить'))) return;
      try {
        const r = await api(`/import/${up.job.id}/preview/`, { method: 'POST', body: {
          mapping, mode: $('#im-mode', body).value, key_field: $('#im-key', body).value,
          create_missing_refs: $('#im-missing', body).checked, profile_name: $('#im-pname', body).value } });
        st.job = r.data; step3(r.background);
      } catch (e) { errToast(e); }
    };
  }

  async function poll(done) {
    body.innerHTML = '<div class="md-panel"><p>Обработка в фоне…</p><div class="md-progress"><div style="width:0%"></div></div><p class="md-muted" id="im-pr"></p></div>';
    for (;;) {
      await new Promise((r) => setTimeout(r, 1200));
      const j = (await api(`/import/${st.job.id}/`)).data;
      const pct = j.total_rows ? Math.round(100 * j.processed_rows / j.total_rows) : 0;
      $('.md-progress div', body).style.width = pct + '%';
      $('#im-pr', body).textContent = `${j.processed_rows} из ${j.total_rows}`;
      if (!['previewing', 'running'].includes(j.status)) { st.job = j; done(); return; }
    }
  }

  function stats(j) {
    const c = j.counts || {};
    return `<div class="md-stats"><div class="md-stat is-ok"><span>Будет создано</span><b>${c.create ?? 0}</b></div>
      <div class="md-stat is-ok"><span>Будет обновлено</span><b>${c.update ?? 0}</b></div>
      <div class="md-stat"><span>Пропущено</span><b>${c.skip ?? 0}</b></div>
      <div class="md-stat ${c.error ? 'is-error' : ''}"><span>Строк с ошибками</span><b>${c.error ?? 0}</b></div></div>`;
  }
  function errorsTable(j) {
    if (!j.errors?.length) return '';
    return `<h3>Ошибки</h3><div class="md-table-wrap" style="max-height:420px;overflow:auto"><table class="md-table"><thead><tr><th>Строка</th><th>Колонка</th><th>Причина</th></tr></thead>
      <tbody>${j.errors.map((e) => `<tr style="cursor:default"><td>${e.row}</td><td>${esc(e.column || '—')}</td><td>${esc(e.message)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function step3(background) {
    if (background) { poll(() => step3(false)); return; }
    st.step = 3; drawSteps();
    const j = st.job;
    const c = j.counts || {};
    body.innerHTML = `<div class="md-panel">${stats(j)}
      ${j.skipped?.length ? `<details style="margin-bottom:12px"><summary>Пропущенные строки (${j.skipped.length})</summary><ul>${j.skipped.slice(0, 100).map((s) => `<li>Строка ${s.row}: ${esc(s.reason)}</li>`).join('')}</ul></details>` : ''}
      ${errorsTable(j)}
      <div class="md-row" style="margin-top:14px"><button type="button" class="md-btn" id="im-back">← Сопоставление</button>
      ${j.has_error_file ? '<button type="button" class="md-btn" id="im-errf">⬇ Файл ошибок</button>' : ''}
      <span class="md-spacer" style="flex:1"></span>
      ${c.error ? `<button type="button" class="md-btn" id="im-valid" ${(c.create + c.update) ? '' : 'disabled'}>Загрузить только корректные строки</button>` : ''}
      <button type="button" class="md-btn md-btn-primary" id="im-run" ${c.error ? 'title="Есть ошибки — загрузка целиком будет отклонена"' : ''}>Загрузить${c.error ? ' целиком' : ''}</button></div></div>`;
    $('#im-back', body).onclick = step2;
    const ef = $('#im-errf', body); if (ef) ef.onclick = () => download(`/import/${j.id}/errors-file/`);
    const run = async (onlyValid) => {
      try { const r = await api(`/import/${j.id}/run/`, { method: 'POST', body: { only_valid: onlyValid } }); st.job = r.data; if (r.background) poll(step4); else step4(); } catch (e) { errToast(e); }
    };
    $('#im-run', body).onclick = () => run(false);
    const v = $('#im-valid', body); if (v) v.onclick = () => run(true);
  }

  function step4() {
    st.step = 4; drawSteps();
    const j = st.job;
    const okRun = j.status === 'done';
    body.innerHTML = `<div class="md-panel"><div class="${okRun ? 'md-warnbox' : 'md-errbox'}" style="${okRun ? 'background:var(--md-ok-bg);color:var(--md-ok)' : ''}">${esc(j.message)}</div>
      ${okRun ? stats(j).replace('Будет создано', 'Создано').replace('Будет обновлено', 'Обновлено') : ''}${errorsTable(j)}
      <div class="md-row" style="margin-top:14px">${j.has_error_file ? '<button type="button" class="md-btn" id="im-errf">⬇ Файл ошибок для исправления</button>' : ''}
      <a class="md-btn" href="#/d/${st.dir}">Открыть справочник</a><button type="button" class="md-btn md-btn-primary" id="im-again">Загрузить ещё файл</button></div></div>`;
    const ef = $('#im-errf', body); if (ef) ef.onclick = () => download(`/import/${j.id}/errors-file/`);
    $('#im-again', body).onclick = step1;
    S.opts = {};
  }
  step1();

  const zip = $('#im-zip', main);
  if (zip) zip.onchange = async () => {
    const fd = new FormData(); fd.append('file', zip.files[0]);
    const res = $('#im-zip-res', main); res.textContent = 'Загрузка…';
    try {
      const r = (await api('/import/photos-zip/', { method: 'POST', form: fd })).data;
      res.innerHTML = `<div class="md-warnbox" style="background:var(--md-ok-bg);color:var(--md-ok)">Добавлено фото: ${r.added}. Модели: ${Object.entries(r.models).map(([k, v]) => `${esc(k)} (${v})`).join(', ') || '—'}</div>
        ${r.skipped.length ? `<div class="md-errbox">Пропущено: ${r.skipped.map((s) => `${esc(s.file)} — ${esc(s.reason)}`).join('<br>')}</div>` : ''}`;
    } catch (e) { res.innerHTML = `<div class="md-errbox">${esc(e.message)}</div>`; }
    zip.value = '';
  };
}

async function viewImportJobs(main) {
  const rows = (await api('/import/jobs/')).data;
  const names = Object.fromEntries((S.me.menu || []).map((d) => [d.code, d.name]));
  main.innerHTML = `<div class="md-page-head"><h1>🧾 Журнал загрузок</h1><span class="md-spacer"></span><a class="md-btn md-btn-primary" href="#/import">Новый импорт</a></div>
    <div class="md-table-wrap"><table class="md-table"><thead><tr><th>Время</th><th>Справочник</th><th>Файл</th><th>Пользователь</th><th>Статус</th>
    <th>Создано</th><th>Обновлено</th><th>Пропущено</th><th>Ошибок</th><th></th></tr></thead><tbody>${rows.length ? rows.map((j) => `<tr style="cursor:default">
      <td>${esc(fmtDateTime(j.created_at))}</td><td>${esc(names[j.directory] || j.directory)}</td><td>${esc(j.file)}</td><td>${esc(j.user)}</td>
      <td><span class="md-badge ${j.status === 'done' ? 'md-badge-ok' : j.status === 'failed' ? 'md-badge-warn' : ''}">${esc(j.status__display)}</span></td>
      <td class="md-num">${j.counts?.create ?? ''}</td><td class="md-num">${j.counts?.update ?? ''}</td><td class="md-num">${j.counts?.skip ?? ''}</td>
      <td class="md-num">${j.counts?.error ?? ''}</td><td>${j.has_error_file ? `<button type="button" class="md-btn md-btn-sm" data-ef="${j.id}">Файл ошибок</button>` : ''}</td></tr>`).join('')
    : `<tr><td class="md-empty" colspan="10">Загрузок пока не было</td></tr>`}</tbody></table></div>`;
  $$('[data-ef]', main).forEach((b) => { b.onclick = () => download(`/import/${b.dataset.ef}/errors-file/`); });
}

// ============================================================
// Организация: разделы, участники, матрица прав (§6, МД-6)
// ============================================================
async function viewSettings(main) {
  const org = S.me.organization;
  const policies = (await api('/role-policies/')).data;
  const members = (await api('/members/')).data;
  const dirs = (await api('/directories/')).data;
  const roles = [['admin', 'Администратор'], ['seller', 'Продавец'], ['accountant', 'Бухгалтер'], ['owner', 'Владелец']];
  main.innerHTML = `<div class="md-page-head"><h1>⚙️ Организация и права</h1></div>
    <div class="md-panel"><h3>Организация</h3><div class="md-form">
      <div class="md-field"><label>Название</label><input class="md-input" id="st-name" value="${esc(org.name)}"></div>
      <div class="md-field"><label>Разделы</label><div class="md-row">
        <label class="md-check"><input type="checkbox" data-sec="uzatu" ${org.sections.uzatu ? 'checked' : ''}> Ұзату</label>
        <label class="md-check"><input type="checkbox" data-sec="shoes" ${org.sections.shoes ? 'checked' : ''}> Обувь</label></div>
        <span class="md-hint">Выключенный раздел скрывает свои категории и связанные виды из выбора. Существующие модели сохраняются.</span></div>
    </div><div class="md-row" style="margin-top:12px"><button type="button" class="md-btn md-btn-primary" id="st-save">${T.save}</button></div></div>
    <div class="md-panel"><h3>Участники</h3><div class="md-table-wrap"><table class="md-table"><thead><tr><th>Пользователь</th><th>Email</th><th>Роль</th></tr></thead>
      <tbody>${members.map((x) => `<tr style="cursor:default"><td>${esc(x.user)}</td><td>${esc(x.email)}</td><td>${esc((roles.find((r) => r[0] === x.role) || [])[1] || x.role)}</td></tr>`).join('')}</tbody></table></div>
      <div class="md-row" style="margin-top:10px"><input class="md-input" id="st-email" placeholder="Email зарегистрированного пользователя" style="max-width:300px">
      <select class="md-select" id="st-role" style="width:auto">${roles.map(([v, l]) => `<option value="${v}" ${v === 'seller' ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button type="button" class="md-btn" id="st-add">Добавить / изменить роль</button></div></div>
    <div class="md-panel"><h3>Права ролей</h3><p class="md-muted" style="margin-top:0">Матрица «роль × справочник × действие». Владелец всегда имеет полные права.</p>
      <div class="md-btn-group" id="st-roles">${roles.filter((r) => r[0] !== 'owner').map(([v, l], i) => `<button type="button" class="md-btn md-btn-sm ${i === 0 ? 'is-on' : ''}" data-r="${v}">${l}</button>`).join('')}</div>
      <div class="md-table-wrap" style="margin-top:10px"><table class="md-table md-matrix"><thead><tr><th>Справочник</th><th>Просмотр</th><th>Создание</th><th>Изменение</th>
        <th>Архив</th><th>Импорт</th><th>Экспорт</th><th>История</th><th>Поля</th></tr></thead><tbody id="st-matrix"></tbody></table></div>
      <div class="md-row" style="margin-top:12px"><button type="button" class="md-btn md-btn-primary" id="st-psave">Сохранить права</button></div></div>`;
  $('#st-save', main).onclick = async () => {
    const sections = {}; $$('[data-sec]', main).forEach((c) => { sections[c.dataset.sec] = c.checked; });
    try { await api('/org/', { method: 'PATCH', body: { name: $('#st-name', main).value, sections } }); toast(T.saved); dropCaches(); await reloadMe(); } catch (e) { errToast(e); }
  };
  $('#st-add', main).onclick = async () => {
    try { await api('/members/', { method: 'POST', body: { email: $('#st-email', main).value, role: $('#st-role', main).value } }); toast(T.saved); viewSettings(main); } catch (e) { errToast(e); }
  };
  let role = 'admin';
  const keys = ['can_view', 'can_create', 'can_update', 'can_archive', 'can_import', 'can_export'];
  const byKey = {}; policies.forEach((p) => { byKey[p.role + ':' + p.directory_code] = p; });
  const changed = new Set();
  const drawMatrix = () => {
    const tb = $('#st-matrix', main);
    tb.innerHTML = '';
    dirs.forEach((d) => {
      const p = byKey[role + ':' + d.code];
      if (!p) return;
      const tr = el(`<tr><td>${esc(d.icon)} ${esc(d.name)}</td>${keys.map((k) => `<td><input type="checkbox" data-k="${k}" ${p[k] ? 'checked' : ''}></td>`).join('')}
        <td><select class="md-select" style="min-height:28px;padding:2px 4px">${[['all', 'все'], ['own', 'свои'], ['none', 'нет']].map(([v, l]) => `<option value="${v}" ${p.history === v ? 'selected' : ''}>${l}</option>`).join('')}</select></td>
        <td><button type="button" class="md-btn md-btn-sm">${(p.hidden_fields.length || p.readonly_fields.length) ? `скрыто ${p.hidden_fields.length}, только чтение ${p.readonly_fields.length}` : 'настроить'}</button></td></tr>`);
      $$('input', tr).forEach((i) => { i.onchange = () => { p[i.dataset.k] = i.checked; changed.add(p); }; });
      $('select', tr).onchange = (e) => { p.history = e.target.value; changed.add(p); };
      $('button', tr).onclick = () => fieldRightsDialog(d, p, () => { changed.add(p); drawMatrix(); });
      tb.appendChild(tr);
    });
  };
  $$('#st-roles button', main).forEach((b) => { b.onclick = () => { role = b.dataset.r; $$('#st-roles button', main).forEach((x) => x.classList.toggle('is-on', x === b)); drawMatrix(); }; });
  drawMatrix();
  $('#st-psave', main).onclick = async () => {
    try { const r = await api('/role-policies/', { method: 'PUT', body: { rows: [...changed] } }); toast(`Сохранено: ${r.data.changed}`); changed.clear(); dropCaches(); } catch (e) { errToast(e); }
  };
}

async function fieldRightsDialog(d, p, done) {
  const fields = (await api(`/directories/${d.code}/fields/`)).data;
  const hidden = new Set(p.hidden_fields); const ro = new Set(p.readonly_fields);
  const body = el(`<div class="md-table-wrap"><table class="md-table md-matrix"><thead><tr><th>Поле</th><th>Скрыто</th><th>Только чтение</th></tr></thead><tbody>${fields.map((f) =>
    `<tr><td>${esc(f.name)}</td><td><input type="checkbox" data-h="${f.code}" ${hidden.has(f.code) ? 'checked' : ''}></td>
     <td><input type="checkbox" data-r="${f.code}" ${ro.has(f.code) ? 'checked' : ''}></td></tr>`).join('')}</tbody></table></div>`);
  const m = modal({ title: `Поля: ${d.name}`, body, foot: [btn(T.cancel, '', () => m.close()), btn('Готово', 'md-btn-primary', () => {
    p.hidden_fields = $$('[data-h]', body).filter((i) => i.checked).map((i) => i.dataset.h);
    p.readonly_fields = $$('[data-r]', body).filter((i) => i.checked).map((i) => i.dataset.r);
    m.close(); done();
  })] });
}

// ============================================================
// Старт
// ============================================================
async function reloadMe() {
  S.me = (await api('/org/')).data;
  $('#md-user').innerHTML = `<b>${esc(S.me.user.name)}</b> · ${esc(S.me.role__display)}`;
}

async function noOrganization(main) {
  main.innerHTML = `<div class="md-panel" style="max-width:520px;margin:40px auto"><h3>Нет организации</h3>
    <p class="md-muted">Вы не состоите ни в одной организации. Создайте свою — вы станете её владельцем, а системные справочники
    будут заполнены автоматически. Или попросите владельца салона добавить вас.</p>
    <div class="md-field"><label>Название организации</label><input class="md-input" id="no-name" placeholder="Например, Bridal Bliss"></div>
    <div class="md-row" style="margin-top:12px"><button type="button" class="md-btn md-btn-primary" id="no-create">Создать организацию</button></div></div>`;
  $('#no-create', main).onclick = async () => {
    try { await api('/organizations/', { method: 'POST', body: { name: $('#no-name', main).value } }); location.reload(); } catch (e) { errToast(e); }
  };
}

async function start() {
  if (!(await refreshToken())) return;
  $('#md-logout').onclick = async () => { try { await fetch('/api/logout', { method: 'POST' }); } catch { /* сеть */ } location.href = '/login'; };
  $('#md-nav-toggle').onclick = () => toggleNav(!$('#md-nav').classList.contains('is-open'));
  $('#md-nav-backdrop').onclick = () => toggleNav(false);
  try { await reloadMe(); } catch (e) {
    if (e.status === 403) { $('#md-nav').innerHTML = ''; noOrganization($('#md-main')); return; }
    $('#md-main').innerHTML = `<div class="md-errbox">${esc(e.message)}</div>`;
    return;
  }
  setupSearch();
  window.addEventListener('hashchange', router);
  router();
}
start();
