// @ts-nocheck
/* РМКО — фронтенд */

declare global {
    interface Window {}
}

interface Meta {
    last_import?: string;
    user?: { needs_password_change?: boolean };
    specialists?: { name: string; city?: string }[];
    cities: string[];
}

let META: any = null, DATA: any[] = [];
let SPEC: Record<string, string[]> = {};               // имя специалиста B2B -> [его города]
const ZONE = '__zone__';     // спец-значение фильтра «зона менеджера»
let queue = 'new', page = 0, sortCol = 'amount', sortDir = -1;
const PENDING = {};          // key -> { field: value, ... } буфер несохранённых правок
const PAGE = 50;
const $ = (id: string): any => document.getElementById(id) as any;

/* ---------- abort & stale-response infra ---------- */
let _reqId = 0;              // monotonic request counter — stale guard
let _globalAC = null;        // single AbortController for ALL list/stats fetches

function freshSignal() {
  if (_globalAC) _globalAC.abort();
  _globalAC = new AbortController();
  return _globalAC.signal;
}

/* ---------- debounce helpers ---------- */
let _searchTimer = null;
function debouncedSearch() {
  if (_searchTimer) clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => { _searchTimer = null; render(); }, 300);
}
const money = (n: any) => n == null ? '' : Math.round(n).toLocaleString('ru-RU');
const mln = (n: any) => (n / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн';
const esc = (s: any) => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDate = (d: any) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function toast(msg: string, err?: boolean) {
  const t = $('toast');
  t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  setTimeout(() => t.className = '', 2500);
}

/* ---------- загрузка ---------- */
async function loadAll() {
  renderQueues();
  try {
    const m = await fetch('/api/meta').then(r => { if (r.status === 401) throw new Error('401'); return r.json() });
    META = m;
    $('lastImport').textContent = m.last_import ? 'выгрузка: ' + m.last_import : '';

    if (m.user && m.user.needs_password_change) {
      $('pwDlg').showModal();
    }

    SPEC = {};
    (m.specialists || []).forEach(s => {
      if (!SPEC[s.name]) SPEC[s.name] = [];
      if (s.city && !SPEC[s.name].includes(s.city)) SPEC[s.name].push(s.city);
    });
    fillUserSelect();
    fillCitySelect();
    

    if (localStorage.getItem('fPeriod')) $('fPeriod').value = localStorage.getItem('fPeriod');
    if (localStorage.getItem('fStatus')) $('fStatus').value = localStorage.getItem('fStatus');
    if (localStorage.getItem('fPayment')) $('fPayment').value = localStorage.getItem('fPayment');
    
    updateFilterVisual($('fPeriod'));
    updateFilterVisual($('fStatus'));
    updateFilterVisual($('fPayment'));
    
    applyManagerZone(false);
    render();
  } catch (e) {
    if (e.message === '401') location.href = '/login';
    else toast('Ошибка загрузки данных', true);
  }
}

function updateFilterVisual(sel: any) {
  if (sel.value && sel.value !== '') {
    sel.classList.add('filter-active');
  } else {
    sel.classList.remove('filter-active');
  }
}

function fillSelect(sel: any, vals: any[], chosen?: string) {
  const first = sel.querySelector('option');
  sel.innerHTML = ''; sel.appendChild(first);
  vals.forEach(v => {
    const o = document.createElement('option');
    o.textContent = v; if (v === chosen) o.selected = true;
    sel.appendChild(o);
  });
  updateFilterVisual(sel);
}

function fillUserSelect() {
  const names = Object.keys(SPEC).sort((a, b) => a.localeCompare(b, 'ru'));
  fillSelect($('user'), names, localStorage.getItem('user') || '');
  updateFilterVisual($('user'));
}

function fillCitySelect() {
  const saved = localStorage.getItem('myCity') || '';
  const cities = new Set(META.cities);
  Object.values(SPEC).flat().forEach(c => cities.add(c));
  fillSelect($('myCity'), [...cities].sort((a, b) => a.localeCompare(b, 'ru')));
  ensureZoneOption();
  $('myCity').value = saved;
  if ($('myCity').selectedIndex < 0) $('myCity').value = '';
  updateFilterVisual($('myCity'));
}

function ensureZoneOption() {
  const name = $('user').value;
  const sel = $('myCity');
  let opt = sel.querySelector(`option[value="${ZONE}"]`);
  const cities = SPEC[name] || [];
  if (cities.length > 1) {
    if (!opt) {
      opt = document.createElement('option');
      opt.value = ZONE;
      sel.insertBefore(opt, sel.options[1]);
    }
    opt.textContent = `Зона менеджера (${cities.length} гор.)`;
  } else if (opt) {
    if (sel.value === ZONE) sel.value = '';
    opt.remove();
  }
}

/* автовыбор города по зоне ответственности выбранного менеджера */
function applyManagerZone(save: boolean = true) {
  ensureZoneOption();
  const cities = SPEC[$('user').value] || [];
  if (cities.length === 1) $('myCity').value = cities[0];
  else if (cities.length > 1) $('myCity').value = ZONE;
  if (save) localStorage.setItem('myCity', $('myCity').value);
}


/* ---------- очереди ---------- */
const QUEUES = [
  { id: 'new', name: 'Новые' },
  { id: 'action', name: 'Требует действия' },
  { id: 'done', name: 'Закрытые' },
  { id: 'lost', name: 'Без продажи' },
  { id: 'all', name: 'Все' },
];

let _renderTimer = null;
function debouncedRender() {
  if (_renderTimer) clearTimeout(_renderTimer);
  _renderTimer = setTimeout(() => { _renderTimer = null; render(); }, 120);
}

function renderQueues() {
  const html = '<div class="radio-inputs">' + QUEUES.map(t => {
    const checked = t.id === queue ? 'checked' : '';
    return `<label class="radio">
              <input type="radio" name="radio-queue" data-q="${t.id}" ${checked}>
              <span class="name">${t.name}</span>
            </label>`;
  }).join('') + '</div>';
  $('queues').innerHTML = html;
  $('queues').querySelectorAll('input[type="radio"]').forEach((b: any) =>
    b.onchange = () => { queue = b.dataset.q; page = 0; debouncedRender(); });
}

function buildParams() {
  const p = new URLSearchParams();
  p.set('queue', queue);
  p.set('city', $('myCity').value);
  p.set('status', $('fStatus').value);
  p.set('payment', $('fPayment').value);
  p.set('mine', $('fMine').checked);
  p.set('me', $('user').value);
  p.set('q', $('q').value);
  p.set('period', $('fPeriod').value);
  if ($('fPeriod').value === 'manual') {
      p.set('fFrom', $('fFrom').value);
      p.set('fTo', $('fTo').value);
  }
  p.set('sortCol', sortCol);
  p.set('sortDir', sortDir);
  p.set('page', page);
  return p;
}

/* renderController removed — replaced by global freshSignal() */

/* ---------- таблица менеджера ---------- */
const COLS = [
  { id: 'doc_date', name: 'Дата' },
  { id: 'city', name: 'Филиал' },
  { id: 'doc_num', name: 'Документ' },
  { id: 'client', name: 'Клиент' },
  { id: 'hint', name: 'Действие' },
  { id: 'amount', name: 'Сумма' },
  { id: 'in_stock', name: 'Товар' },
  { id: 'plan_contact', name: 'Срок' },
  { id: 'notes', name: 'Заметка' },
  { id: 'author', name: 'Автор' },
  { id: 'hist', name: '' },
  { id: '_confirm', name: '' },
];

function selectHtml(d: any, field: string, options: string[], allowEmpty: boolean = true, disabled: boolean = false) {
  const cur = d[field] || '';
  let extra = cur && !options.includes(cur) ? [cur] : [];
  return `<select data-k="${esc(d.key)}" data-f="${field}"${disabled ? ' disabled' : ''}>
    ${allowEmpty ? `<option value=""${cur ? '' : ' selected'}>—</option>` : ''}
    ${options.concat(extra).map(o => `<option${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('')}
  </select>`;
}

function paymentBadge(d: any) {
  if (d.has_payment == 1) {
    return `<span class="payment-badge">Оплачено</span>`;
  }
  const amount = Number(d.amount || 0);
  const paidAmount = Number(d.payment_amount || 0);
  if (paidAmount > 0 && paidAmount < amount) {
    return `<span class="payment-badge">Частично</span>`;
  }
  return '';
}



function rowHtml(d: any) {
  const stClass = d.cur_status === 'Выдан' ? 'st-issued' : d.cur_status === 'Удален' ? 'st-deleted' : 'st-reserve';
  const flag = d.flag ? `<span class="flag ${d.flag}">${d.flag === 'NEW' ? 'NEW' : 'UPD'}</span>` : '';
  const docStatus = `<span class="doc-status ${stClass}">${esc(d.cur_status)}</span>`;
  const wa = (d.phones || []).map(p => '<a class="wa" target="_blank" href="https://wa.me/' + p + '" title="WhatsApp">💬' + p.slice(-4) + '</a>').join('');
  const dateStr = d.doc_date ? d.doc_date.slice(0, 10).split('-').reverse().join('.') : '';
  const planVal = d.plan_contact ? d.plan_contact.slice(0, 10).split('-').reverse().join('.') : '';
  const planColorClass = d.plan_color === 'green' ? 'plan-green' : d.plan_color === 'yellow' ? 'plan-yellow' : 'plan-red';
  const errTip = d.errors && d.errors.length ? ` title="${esc(d.errors.join('; '))}"` : '';
  const actionMark = d.overdue_contact ? '<span class="late-mark" title="Срок прошел">Просрочено</span>' : '';
  const inStockDisabled = (d.cur_status === 'Удален' || d.cur_status === 'Удалён' || d.cur_status === 'Выдан');
  return `<tr class="r-${d.level}" id="r-${cssKey(d.key)}">
    <td>${flag}${dateStr}<span class="cl">${d.workdays} раб.дн.</span></td>
    <td>${esc(d.branch || '')}</td>
    <td class="td-copy doc-cell" title="${esc(d.doc)}"><span class="doc-meta">${docStatus}</span><span class="copy-text" data-copy="${esc(d.doc_num)}">${esc(d.doc_num)}</span><svg class="copy-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></td>
    <td><b>${esc(d.client || '')}</b><br>${wa}<span class="cl" title="${esc(d.comment_1c || '')}">${esc(d.comment_1c || '')}</span></td>
    <td>${actionMark}<span class="hint ${d.level === 'error' ? 'err' : ''}"${errTip}>${esc(d.hint)}</span></td>
    <td class="sum">${paymentBadge(d)}<span class="amount-text">${money(d.amount)}</span></td>
    <td>${selectHtml(d, 'in_stock', ["Ожидает проверки", "Проверено"], false, inStockDisabled)}</td>
    <td><span class="${planColorClass}">${planVal}</span></td>
    <td><input type="text" data-k="${esc(d.key)}" data-f="notes" value="${esc(d.notes || '')}" placeholder="Заметка"></td>
    <td><span class="cl full">${esc(d.author || '')}</span></td>
    <td><button class="iconbtn" data-hist="${esc(d.key)}" title="История">🕘</button></td>
    <td class="td-confirm">${PENDING[d.key] ? `<div class="row-confirm-actions"><button class="row-confirm-btn" data-commit="${esc(d.key)}" title="Сохранить изменения"><svg viewBox="0 0 14 14" fill="none"><path d="M3 7l3 3 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="row-discard-btn" data-discard="${esc(d.key)}" title="Отменить"><svg viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></div>` : ''}</td>
  </tr>`;
}

const cssKey = (k: string) => k.replace(/[^a-zA-Zа-яА-Я0-9]/g, '_');

async function render() {
  const signal = freshSignal();
  const myId = ++_reqId;
  
  renderQueues();
  const thead = $('tbl').querySelector('thead');
  thead.innerHTML = '<tr>' + COLS.map(c =>
    `<th data-c="${c.id}">${c.name}${c.id === sortCol ? (sortDir < 0 ? ' ▼' : ' ▲') : ''}</th>`).join('') + '</tr>';
  thead.querySelectorAll('th').forEach((th: any) => th.onclick = () => {
    const c = th.dataset.c;
    if (c === sortCol) sortDir *= -1; else { sortCol = c; sortDir = -1; }
    page = 0;
    render();
  });
  
  $('tbl').querySelector('tbody').innerHTML = '<tr><td colspan="13" style="text-align:center;padding:22px"><div class="loader-spinner"></div> Загрузка...</td></tr>';
  
  try {
    const paramsStr = buildParams().toString();
    const [rDeals, rSummary] = await Promise.all([
      fetch('/api/deals?' + paramsStr, { signal }),
      fetch('/api/deals/summary?' + paramsStr, { signal })
    ]);

    // stale guard — a newer request was already fired
    if (myId !== _reqId) return;

    if (!rDeals.ok || !rSummary.ok) {
        if (rDeals.status === 401 || rSummary.status === 401) return location.href = '/login';
        throw new Error('Ошибка ' + (rDeals.status !== 200 ? rDeals.status : rSummary.status));
    }
    const res = await rDeals.json();
    const summary = await rSummary.json();
    
    // second stale check after JSON parsing
    if (myId !== _reqId) return;

    DATA = res.items;
    const pages = Math.max(1, Math.ceil(summary.total / PAGE));
    if (page >= pages && pages > 0) { page = pages - 1; return render(); }
    
    $('tbl').querySelector('tbody').innerHTML =
      res.items.map(rowHtml).join('') || '<tr><td colspan="13" style="text-align:center;color:#888;padding:22px">Нет записей</td></tr>';
    bindRowEvents();
    $('pinfo').textContent = `стр. ${page + 1}/${pages}`;
    $('prev').disabled = page <= 0; $('next').disabled = page >= pages - 1;
    $('totals').textContent = `${(summary.total || 0).toLocaleString('ru-RU')} сделок · ${mln(summary.sum || 0)}`;
  } catch (e) {
    if (e.name !== 'AbortError') {
      $('tbl').querySelector('tbody').innerHTML = '<tr><td colspan="13" style="text-align:center;color:red;padding:22px">Ошибка загрузки данных</td></tr>';
    }
  }
}

function bufferChange(key: string, field: string, value: any) {
  if (!PENDING[key]) PENDING[key] = {};
  PENDING[key][field] = value;
  // подсветить строку и показать кнопки
  const row = document.getElementById('r-' + cssKey(key));
  if (row) {
    row.classList.add('row-pending');
    const cell = row.querySelector('.td-confirm');
    if (cell && !cell.querySelector('.row-confirm-btn')) {
      cell.innerHTML = `<div class="row-confirm-actions"><button class="row-confirm-btn" data-commit="${esc(key)}" title="Сохранить изменения"><svg viewBox="0 0 14 14" fill="none"><path d="M3 7l3 3 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="row-discard-btn" data-discard="${esc(key)}" title="Отменить"><svg viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></div>`;
      cell.querySelector('.row-confirm-btn').onclick = () => commitRow(key);
      cell.querySelector('.row-discard-btn').onclick = () => discardRow(key);
    }
  }
}

async function commitRow(key: string) {
  const fields = PENDING[key];
  if (!fields) return;
  delete PENDING[key];
  await patch(key, fields);
}

function discardRow(key: string) {
  delete PENDING[key];
  render();
}

function bindRowEvents() {
  const tb = $('tbl').querySelector('tbody');
  // Буферизируем изменения вместо немедленного сохранения
  tb.querySelectorAll('select[data-f], input[data-f]').forEach((el: any) => {
    el.onchange = () => {
      const f = el.dataset.f;
      const v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
      bufferChange(el.dataset.k, f, v);
    };
  });
  // Привязка кнопок подтверждения/отмены (для рендера с уже pending строками)
  tb.querySelectorAll('button[data-commit]').forEach((b: any) => b.onclick = () => commitRow(b.dataset.commit));
  tb.querySelectorAll('button[data-discard]').forEach((b: any) => b.onclick = () => discardRow(b.dataset.discard));
  tb.querySelectorAll('button[data-hist]').forEach((b: any) => b.onclick = () => showHist(b.dataset.hist));
  // Copy doc_num on click
  tb.querySelectorAll('.td-copy').forEach((td: any) => {
    td.style.cursor = 'pointer';
    td.onclick = (e: any) => {
      if (e.target.closest('a')) return;
      const text = td.querySelector('.copy-text')?.dataset.copy;
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        const tip = document.createElement('span');
        tip.className = 'copy-tip';
        tip.textContent = 'Скопировано!';
        td.appendChild(tip);
        setTimeout(() => tip.remove(), 1200);
      });
    };
  });
  // Подсветим строки с pending
  tb.querySelectorAll('tr[id]').forEach((row: any) => {
    const key = row.id.replace('r-', '').replace(/_/g, match => match);
    // Находим ключ из DATA
    const dataKey = DATA.find(d => 'r-' + cssKey(d.key) === row.id)?.key;
    if (dataKey && PENDING[dataKey]) row.classList.add('row-pending');
  });
}

async function patch(key: string, fields: any) {
  const user = $('user').value.trim();
  if (!user) { toast('Сначала выберите менеджера в шапке — без этого правки не сохраняются', true); render(); return; }

  const chk = $('saveCheckbox');
  const txt = $('saveStatusText');

  if (chk) {
    chk.checked = false; // toggle to red cross
    txt.textContent = 'Сохранение...';
    txt.style.color = '#2d79f3';
  }

  try {
    const r = await fetch('/api/deal/' + encodeURIComponent(key), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-User': encodeURIComponent(user) },
      body: JSON.stringify(fields),
    });
    if (!r.ok) {
      if (r.status === 401) return location.href = '/login';
      throw new Error((await r.json()).error || r.status);
    }
    const fresh = await r.json();
    const i = DATA.findIndex(d => d.key === key);
    if (i >= 0) DATA[i] = fresh;

    if (chk) {
      chk.checked = true; // toggle to green tick
      txt.textContent = 'Сохранено';
      txt.style.color = '#4caf50';
      setTimeout(() => {
        if (txt.textContent === 'Сохранено') {
          txt.textContent = 'Сохранено';
          txt.style.color = '#757575';
        }
      }, 2000);
    }

    render();
    if (fresh.errors && fresh.errors.length) toast('Сохранено, но: ' + fresh.errors[0], true);
  } catch (e) {
    if (chk) {
      chk.checked = false; // keep red cross
      txt.textContent = 'Ошибка';
      txt.style.color = '#d32f2f';
    }
    toast(e.message, true);
  }
}

async function showHist(key: string) {
  const rows = await fetch('/api/history/' + encodeURIComponent(key)).then(r => r.json());
  $('histKey').textContent = key.split('|')[0];
  $('histBody').innerHTML = rows.length
    ? '<table><tr><th>Когда</th><th>Кто</th><th>Поле</th><th>Было</th><th>Стало</th></tr>' +
    rows.map(h => `<tr><td>${esc(h.ts)}</td><td>${esc(decodeURIComponent(h.user))}</td><td>${esc(h.field)}</td><td>${esc(h.old_val)}</td><td><b>${esc(h.new_val)}</b></td></tr>`).join('') + '</table>'
    : '<p>Изменений ещё не было.</p>';
  $('histDlg').showModal();
}


/* ---------- переключение вкладок ---------- */
let currentMode = 'mgr';
function switchMode(mode: string) {
  // abort any in-flight requests from the previous tab
  if (_globalAC) _globalAC.abort();
  _globalAC = null;

  currentMode = mode;
  document.querySelectorAll('.mode-tab').forEach((t: any) => t.classList.remove('act'));
  document.querySelector(`.mode-tab[data-m="${mode}"]`).classList.add('act');
  
  document.querySelectorAll('#v-mgr, #v-settings').forEach((s: any) => s.classList.add('hidden'));
  document.getElementById('v-' + mode).classList.remove('hidden');
  
  if (mode === 'mgr') {
    render();
  } else if (mode === 'settings') {
    renderSettings();
  }
}

document.querySelectorAll('.mode-tab').forEach((tab: any) => {
  tab.onclick = () => switchMode(tab.dataset.m);
});

/* ---------- обработчики фильтров ---------- */
$('user').onchange = () => {
  applyManagerZone(true);
  page = 0;
  debouncedRender();
};

$('myCity').onchange = () => {
  localStorage.setItem('myCity', $('myCity').value);
  page = 0;
  debouncedRender();
};

$('fPeriod').onchange = () => {
  localStorage.setItem('fPeriod', $('fPeriod').value);
  updateFilterVisual($('fPeriod'));
  page = 0;
  debouncedRender();
};

$('fStatus').onchange = () => {
  localStorage.setItem('fStatus', $('fStatus').value);
  updateFilterVisual($('fStatus'));
  page = 0;
  debouncedRender();
};

$('fPayment').onchange = () => {
  localStorage.setItem('fPayment', $('fPayment').value);
  updateFilterVisual($('fPayment'));
  page = 0;
  debouncedRender();
};

$('fMine').onchange = () => {
  page = 0;
  debouncedRender();
};

$('fFrom').onchange = () => { page = 0; debouncedRender(); };
$('fTo').onchange = () => { page = 0; debouncedRender(); };

$('q').oninput = () => {
  page = 0;
  debouncedSearch();
};

/* ---------- пагинация ---------- */
$('prev').onclick = () => {
  if (page > 0) { page--; render(); }
};

$('next').onclick = () => {
  page++;
  render();
};

/* ---------- импорт и выход ---------- */
$('btnLogout').onclick = async () => {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
    location.href = '/login';
  } catch (e) {
    toast('Ошибка выхода', true);
  }
};

/* ---------- настройки ---------- */
async function renderSettings() {
  const signal = freshSignal();
  const tbody = $('tblSpec').querySelector('tbody');
  tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;padding:22px"><div class="loader-spinner"></div></td></tr>';
  try {
    const specialists = await fetch('/api/meta', { signal }).then(r => r.json()).then(m => m.specialists || []);
    tbody.innerHTML = specialists.map(s => 
      `<tr><td>${esc(s.name)}</td><td>${esc(s.city)}</td></tr>`
    ).join('') || '<tr><td colspan="2" style="text-align:center;color:#888;padding:22px">Нет специалистов</td></tr>';
  } catch (e) {
    if (e.name !== 'AbortError') {
      tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:red;padding:22px">Ошибка загрузки</td></tr>';
    }
  }
}

loadAll();
