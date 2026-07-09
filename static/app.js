/* РМКО — фронтенд */
let META = null, DATA = [];
let SPEC = {};               // имя специалиста B2B -> [его города]
const ZONE = '__zone__';     // спец-значение фильтра «зона менеджера»
let queue = 'new', page = 0, sortCol = 'amount', sortDir = -1;
const PENDING = {};          // key -> { field: value, ... } буфер несохранённых правок
const PAGE = 50;
const $ = id => document.getElementById(id);
const money = n => n == null ? '' : Math.round(n).toLocaleString('ru-RU');
const mln = n => (n / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн';
const esc = s => (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function toast(msg, err) {
  const t = $('toast');
  t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  setTimeout(() => t.className = '', 2500);
}

/* ---------- загрузка ---------- */
async function loadAll() {
  renderQueues([]);
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
    fillSelect($('fStage'), m.stages.map(s => 'Этап: ' + s).concat(['(пусто)']), localStorage.getItem('fStage') || '');
    
    if (localStorage.getItem('fPeriod')) $('fPeriod').value = localStorage.getItem('fPeriod');
    if (localStorage.getItem('fStatus')) $('fStatus').value = localStorage.getItem('fStatus');
    if (localStorage.getItem('fPayment')) $('fPayment').value = localStorage.getItem('fPayment');
    
    updateFilterVisual($('fPeriod'));
    updateFilterVisual($('fStatus'));
    updateFilterVisual($('fPayment'));
    
    applyManagerZone(false);
    refresh();
  } catch (e) {
    if (e.message === '401') location.href = '/login';
    else toast('Ошибка загрузки данных', true);
  }
}

function updateFilterVisual(sel) {
  if (sel.value && sel.value !== '') {
    sel.classList.add('filter-active');
  } else {
    sel.classList.remove('filter-active');
  }
}

function fillSelect(sel, vals, chosen) {
  const first = sel.querySelector('option');
  sel.innerHTML = ''; sel.appendChild(first);
  vals.forEach(v => {
    const o = document.createElement('option');
    // For stage filter, separate display text from value
    if (sel.id === 'fStage' && v !== '(пусто)' && v.startsWith('Этап: ')) {
      o.textContent = v;
      o.value = v.replace('Этап: ', '');
      if (o.value === chosen) o.selected = true;
    } else {
      o.textContent = v; if (v === chosen) o.selected = true;
    }
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
function applyManagerZone(save = true) {
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

function renderQueues() {
  const html = '<div class="radio-inputs">' + QUEUES.map(t => {
    const checked = t.id === queue ? 'checked' : '';
    return `<label class="radio">
              <input type="radio" name="radio-queue" data-q="${t.id}" ${checked}>
              <span class="name">${t.name}</span>
            </label>`;
  }).join('') + '</div>';
  $('queues').innerHTML = html;
  $('queues').querySelectorAll('input[type="radio"]').forEach(b =>
    b.onchange = () => { queue = b.dataset.q; page = 0; render(); });
}

function buildParams() {
  const p = new URLSearchParams();
  p.set('queue', queue);
  p.set('city', $('myCity').value);
  p.set('stage', $('fStage').value);
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

let renderController = null;

/* ---------- таблица менеджера ---------- */
const COLS = [
  { id: 'doc_date', name: 'Дата' },
  { id: 'city', name: 'Филиал' },
  { id: 'doc_num', name: 'Документ' },
  { id: 'client', name: 'Клиент' },
  { id: 'hint', name: 'Действие' },
  { id: 'stage', name: 'Этап' },
  { id: 'amount', name: 'Сумма' },
  { id: 'in_stock', name: 'Товар' },
  { id: 'plan_contact', name: 'Срок' },
  { id: 'notes', name: 'Заметка' },
  { id: 'author', name: 'Автор' },
  { id: 'hist', name: '' },
  { id: '_confirm', name: '' },
];

function selectHtml(d, field, options, allowEmpty = true, disabled = false) {
  const cur = d[field] || '';
  let extra = cur && !options.includes(cur) ? [cur] : [];
  return `<select data-k="${esc(d.key)}" data-f="${field}"${disabled ? ' disabled' : ''}>
    ${allowEmpty ? `<option value=""${cur ? '' : ' selected'}>—</option>` : ''}
    ${options.concat(extra).map(o => `<option${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('')}
  </select>`;
}

function paymentBadge(d) {
  const paid = Boolean(d.has_payment) || Number(d.payment_amount || 0) > 0 || Boolean(d.payment_date);
  if (!paid) return '';
  const amount = Number(d.amount || 0);
  const paidAmount = Number(d.payment_amount || 0);
  const label = amount && paidAmount && paidAmount < amount ? 'Частично' : 'Оплачено';
  return `<span class="payment-badge">${label}</span>`;
}

function autoStageLabel(d) {
  const paid = Boolean(d.has_payment) || Number(d.payment_amount || 0) > 0 || Boolean(d.payment_date);
  if (['Не состоялась', 'Удалён', 'Заменена', 'Сервис'].includes(d.stage)) return d.stage;
  if (d.cur_status === 'Удалён' || d.cur_status === 'Удален') return 'Удалено в 1С';
  if (d.cur_status === 'Выдан') return 'Закрыто';
  if (d.cur_status === 'Резерв' && paid) return 'Оплата есть';
  if (d.cur_status === 'Резерв') return 'Ожидаем оплату';
  return d.stage || 'В работе';
}

function stageCell(d) {
  if (['Резерв', 'Выдан', 'Удалён', 'Удален'].includes(d.cur_status)) {
    return `<span class="auto-stage">${esc(autoStageLabel(d))}</span>`;
  }
  return selectHtml(d, 'stage', META.stages);
}

function rowHtml(d) {
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
    <td>${stageCell(d)}</td>
    <td class="sum">${paymentBadge(d)}<span class="amount-text">${money(d.amount)}</span></td>
    <td>${selectHtml(d, 'in_stock', ["Ожидает проверки", "Проверено"], false, inStockDisabled)}</td>
    <td><span class="${planColorClass}">${planVal}</span></td>
    <td><input type="text" data-k="${esc(d.key)}" data-f="notes" value="${esc(d.notes || '')}" placeholder="Заметка"></td>
    <td><span class="cl full">${esc(d.author || '')}</span></td>
    <td><button class="iconbtn" data-hist="${esc(d.key)}" title="История">🕘</button></td>
    <td class="td-confirm">${PENDING[d.key] ? `<div class="row-confirm-actions"><button class="row-confirm-btn" data-commit="${esc(d.key)}" title="Сохранить изменения"><svg viewBox="0 0 14 14" fill="none"><path d="M3 7l3 3 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="row-discard-btn" data-discard="${esc(d.key)}" title="Отменить"><svg viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></div>` : ''}</td>
  </tr>`;
}

const cssKey = k => k.replace(/[^a-zA-Zа-яА-Я0-9]/g, '_');

async function render() {
  if (renderController) renderController.abort();
  renderController = new AbortController();
  
  renderQueues();
  const thead = $('tbl').querySelector('thead');
  thead.innerHTML = '<tr>' + COLS.map(c =>
    `<th data-c="${c.id}">${c.name}${c.id === sortCol ? (sortDir < 0 ? ' ▼' : ' ▲') : ''}</th>`).join('') + '</tr>';
  thead.querySelectorAll('th').forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    if (c === sortCol) sortDir *= -1; else { sortCol = c; sortDir = -1; }
    page = 0;
    render();
  });
  
  $('tbl').querySelector('tbody').innerHTML = '<tr><td colspan="13" style="text-align:center;padding:22px"><div class="loader-spinner"></div> Загрузка...</td></tr>';
  
  try {
    const r = await fetch('/api/deals?' + buildParams().toString(), { signal: renderController.signal });
    if (!r.ok) {
        if (r.status === 401) return location.href = '/login';
        throw new Error('Ошибка ' + r.status);
    }
    const res = await r.json();
    
    DATA = res.items;
    const pages = Math.max(1, Math.ceil(res.total / PAGE));
    if (page >= pages && pages > 0) { page = pages - 1; return render(); }
    
    $('tbl').querySelector('tbody').innerHTML =
      res.items.map(rowHtml).join('') || '<tr><td colspan="13" style="text-align:center;color:#888;padding:22px">Нет записей</td></tr>';
    bindRowEvents();
    $('pinfo').textContent = `стр. ${page + 1}/${pages}`;
    $('prev').disabled = page <= 0; $('next').disabled = page >= pages - 1;
    $('totals').textContent = `${res.total.toLocaleString('ru-RU')} сделок · ${mln(res.sum)}`;
  } catch (e) {
    if (e.name !== 'AbortError') {
      $('tbl').querySelector('tbody').innerHTML = '<tr><td colspan="13" style="text-align:center;color:red;padding:22px">Ошибка загрузки данных</td></tr>';
    }
  }
}

function bufferChange(key, field, value) {
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

async function commitRow(key) {
  const fields = PENDING[key];
  if (!fields) return;
  delete PENDING[key];
  await patch(key, fields);
}

function discardRow(key) {
  delete PENDING[key];
  render();
}

function bindRowEvents() {
  const tb = $('tbl').querySelector('tbody');
  // Буферизируем изменения вместо немедленного сохранения
  tb.querySelectorAll('select[data-f], input[data-f]').forEach(el => {
    el.onchange = () => {
      const f = el.dataset.f;
      const v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
      bufferChange(el.dataset.k, f, v);
    };
  });
  // Привязка кнопок подтверждения/отмены (для рендера с уже pending строками)
  tb.querySelectorAll('button[data-commit]').forEach(b => b.onclick = () => commitRow(b.dataset.commit));
  tb.querySelectorAll('button[data-discard]').forEach(b => b.onclick = () => discardRow(b.dataset.discard));
  tb.querySelectorAll('button[data-hist]').forEach(b => b.onclick = () => showHist(b.dataset.hist));
  // Copy doc_num on click
  tb.querySelectorAll('.td-copy').forEach(td => {
    td.style.cursor = 'pointer';
    td.onclick = (e) => {
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
  tb.querySelectorAll('tr[id]').forEach(row => {
    const key = row.id.replace('r-', '').replace(/_/g, match => match);
    // Находим ключ из DATA
    const dataKey = DATA.find(d => 'r-' + cssKey(d.key) === row.id)?.key;
    if (dataKey && PENDING[dataKey]) row.classList.add('row-pending');
  });
}

async function patch(key, fields) {
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

async function showHist(key) {
  const rows = await fetch('/api/history/' + encodeURIComponent(key)).then(r => r.json());
  $('histKey').textContent = key.split('|')[0];
  $('histBody').innerHTML = rows.length
    ? '<table><tr><th>Когда</th><th>Кто</th><th>Поле</th><th>Было</th><th>Стало</th></tr>' +
    rows.map(h => `<tr><td>${esc(h.ts)}</td><td>${esc(decodeURIComponent(h.user))}</td><td>${esc(h.field)}</td><td>${esc(h.old_val)}</td><td><b>${esc(h.new_val)}</b></td></tr>`).join('') + '</table>'
    : '<p>Изменений ещё не было.</p>';
  $('histDlg').showModal();
}

/* ---------- руководитель ---------- */
let charts = [];
async function renderBoss() {
  $('bossKpis').innerHTML = '<div style="padding:22px">Загрузка аналитики...</div>';
  try {
    const r = await fetch('/api/stats?' + buildParams().toString());
    const data = await r.json();
    
    const kpi = data.kpi;
    $('bossKpis').innerHTML = `
      <div class="kpi"><div class="lbl">Активные сделки</div><div class="val">${(kpi.act_count||0).toLocaleString('ru-RU')}</div><div class="det">${mln(kpi.act_sum||0)} тг</div></div>
      <div class="kpi risk"><div class="lbl">🔴 Под риском</div><div class="val">${kpi.risk_count||0}</div><div class="det">${mln(kpi.risk_sum||0)} тг</div></div>
      <div class="kpi ready"><div class="lbl">🟩 Выдать товар</div><div class="val">${kpi.ready_count||0}</div><div class="det">${mln(kpi.ready_sum||0)} тг</div></div>
      <div class="kpi warn"><div class="lbl">⏰ Просрочен контакт</div><div class="val">${kpi.over_count||0}</div><div class="det"></div></div>
      <div class="kpi err"><div class="lbl">🛑 Ошибки заполнения</div><div class="val">${kpi.err_count||0}</div><div class="det"></div></div>
      <div class="kpi"><div class="lbl">🟢 Выдано</div><div class="val">${(kpi.done_count||0).toLocaleString('ru-RU')}</div><div class="det">${mln(kpi.done_sum||0)} тг</div></div>
      <div class="kpi"><div class="lbl">⚫ Потеряно</div><div class="val">${(kpi.lost_count||0).toLocaleString('ru-RU')}</div><div class="det">${mln(kpi.lost_sum||0)} тг</div></div>`;

    charts.forEach(c => c.destroy()); charts = [];
    if (!window.Chart) return;
    const bar = (el, labels, dset, color, horizontal) => charts.push(new Chart($(el), {
      type: 'bar',
      data: { labels, datasets: [{ data: dset, backgroundColor: color }] },
      options: {
        indexAxis: horizontal ? 'y' : 'x', plugins: { legend: { display: false } },
        scales: { [horizontal ? 'x' : 'y']: { ticks: { callback: v => (v / 1e6) + ' млн' } } }
      },
    }));

    const stages = ['(нет этапа)', ...META.stages];
    bar('chFunnel', stages, stages.map(s => data.funnel[s] || 0), '#3a7ca5');

    const topR = Object.entries(data.lost).sort((a, b) => b[1] - a[1]).slice(0, 10);
    bar('chLost', topR.map(x => x[0]), topR.map(x => x[1]), '#8a939d', true);

    const wk = Object.keys(data.weeks).sort();
    bar('chWeeks', wk, wk.map(k => data.weeks[k]), '#ff6a00');

    const topC = Object.entries(data.cities).sort((a, b) => (b[1][0] + b[1][1]) - (a[1][0] + a[1][1])).slice(0, 12);
    charts.push(new Chart($('chCities'), {
      type: 'bar',
      data: {
        labels: topC.map(x => x[0]), datasets: [
          { label: 'Активные', data: topC.map(x => x[1][0]), backgroundColor: '#3a7ca5' },
          { label: 'Выдано', data: topC.map(x => x[1][1]), backgroundColor: '#2e9e5b' },
        ]
      },
      options: { scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: v => (v / 1e6) + ' млн' } } }, plugins: { legend: { position: 'bottom' } } },
    }));

    const rows = Object.entries(data.mgrs).sort((a, b) => b[1].sum - a[1].sum).slice(0, 40);
    $('tblMgr').querySelector('thead').innerHTML =
      '<tr><th>Менеджер</th><th>Сделок</th><th>Сумма</th><th>Активные</th><th>Под риском</th><th>Просрочено</th><th>Ошибки</th><th>Выдано</th></tr>';
    $('tblMgr').querySelector('tbody').innerHTML = rows.map(([a, m]) =>
      `<tr><td>${esc(a)}</td><td>${m.n}</td><td class="sum">${money(m.sum)}</td><td>${m.act}</td>
       <td style="color:${m.risk ? '#d63b3b' : '#999'};font-weight:700">${m.risk}</td>
       <td style="color:${m.over ? '#e6a700' : '#999'};font-weight:700">${m.over}</td>
       <td style="color:${m.err ? '#c2185b' : '#999'};font-weight:700">${m.err}</td><td>${m.done}</td></tr>`).join('');
  } catch (e) {
    $('bossKpis').innerHTML = '<div style="padding:22px;color:red">Ошибка загрузки аналитики</div>';
  }
};

loadAll();
