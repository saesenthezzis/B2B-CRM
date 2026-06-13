/* РМКО — фронтенд */
let META = null, DATA = [];
let SPEC = {};               // имя специалиста B2B -> [его города]
const ZONE = '__zone__';     // спец-значение фильтра «зона менеджера»
let queue = 'new', page = 0, sortCol = 'amount', sortDir = -1;
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
  // Покажем пустые счетчики (все по 0) во время загрузки данных
  renderQueues([]);
  try {
    const [m, d] = await Promise.all([
      fetch('/api/meta').then(r => { if (r.status === 401) throw new Error('401'); return r.json() }),
      fetch('/api/deals').then(r => { if (r.status === 401) throw new Error('401'); return r.json() }),
    ]);
    META = m; DATA = d;
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
    fillSelect($('fStage'), m.stages.concat(['(пусто)']));
    applyManagerZone(false);
    render();
  } catch (e) {
    if (e.message === '401') location.href = '/login';
    else toast('Ошибка загрузки данных', true);
  }
}

function fillSelect(sel, vals, chosen) {
  const first = sel.querySelector('option');
  sel.innerHTML = ''; sel.appendChild(first);
  vals.forEach(v => {
    const o = document.createElement('option');
    o.textContent = v; if (v === chosen) o.selected = true;
    sel.appendChild(o);
  });
}

function fillUserSelect() {
  const names = Object.keys(SPEC).sort((a, b) => a.localeCompare(b, 'ru'));
  fillSelect($('user'), names, localStorage.getItem('user') || '');
}

function fillCitySelect() {
  const saved = localStorage.getItem('myCity') || '';
  const cities = new Set(META.cities);
  Object.values(SPEC).flat().forEach(c => cities.add(c));
  fillSelect($('myCity'), [...cities].sort((a, b) => a.localeCompare(b, 'ru')));
  ensureZoneOption();
  $('myCity').value = saved;
  if ($('myCity').selectedIndex < 0) $('myCity').value = '';
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
  { id: 'new', name: 'Новые', f: d => d.flag === 'NEW' || d.level === 'new' },
  { id: 'action', name: 'Требуют действия', f: d => ['risk', 'warn', 'ready', 'paid', 'error'].includes(d.level) || d.overdue_contact },
  { id: 'done', name: 'Закрытые', f: d => d.is_closed && d.level === 'done' },
  { id: 'lost', name: 'Без продажи', f: d => d.is_closed && d.level !== 'done' },
  { id: 'all', name: 'Все', f: () => true },
];

/* ---------- фильтр периода ---------- */
function periodRange() {
  const p = $('fPeriod').value;
  if (!p) return null;
  const today = new Date();
  const t = fmtDate(today);
  const back = days => { const d = new Date(); d.setDate(d.getDate() - days); return fmtDate(d); };
  switch (p) {
    case 'today': return [t, t];
    case 'day': return [back(1), t];
    case 'week': return [back(7), t];
    case 'month': return [back(30), t];
    case 'year': return [back(365), t];
    case 'manual': {
      const from = $('fFrom').value || null, to = $('fTo').value || null;
      return (from || to) ? [from, to] : null;
    }
  }
  return null;
}

function baseFiltered() {
  const city = $('myCity').value, stage = $('fStage').value, status = $('fStatus').value;
  const q = $('q').value.toLowerCase(), mine = $('fMine').checked;
  const me = ($('user').value || '').toLowerCase();
  const zoneCities = SPEC[$('user').value] || [];
  const range = periodRange();
  return DATA.filter(d => {
    if (city === ZONE) { if (!zoneCities.includes(d.city)) return false; }
    else if (city && d.city !== city) return false;
    if (stage && (stage === '(пусто)' ? d.stage : d.stage !== stage)) return false;
    if (status && d.cur_status !== status) return false;
    if (mine && me && !(d.author || '').toLowerCase().includes(me)) return false;
    if (range) {
      const dd = (d.doc_date || d.created_at || '').slice(0, 10);
      if (!dd) return false;
      if (range[0] && dd < range[0]) return false;
      if (range[1] && dd > range[1]) return false;
    }
    if (q && !((d.client || '') + ' ' + (d.doc_num || '') + ' ' + (d.comment_1c || '') + ' ' +
      (d.notes || '') + ' ' + (d.contacts || '')).toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderQueues(rows) {
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

/* ---------- таблица менеджера ---------- */
const COLS = [
  { id: 'status', name: 'Статус' },
  { id: 'hint', name: 'Подсказка' },
  { id: 'doc_num', name: '№' },
  { id: 'doc_date', name: 'Дата' },
  { id: 'city', name: 'Город' },
  { id: 'client', name: 'Контрагент' },
  { id: 'amount', name: 'Сумма' },
  { id: 'stage', name: 'Этап сделки' },
  { id: 'in_stock', name: 'Товар' },
  { id: 'next_step', name: 'След. шаг' },
  { id: 'plan_contact', name: 'План конт.' },
  { id: 'reason', name: 'Причина' },
  { id: 'check_status', name: 'Проверка' },
  { id: 'notes', name: 'Примечания' },
  { id: 'author', name: 'Автор' },
  { id: 'hist', name: '' },
];

function selectHtml(d, field, options, allowEmpty = true) {
  const cur = d[field] || '';
  let extra = cur && !options.includes(cur) ? [cur] : [];
  return `<select data-k="${esc(d.key)}" data-f="${field}">
    ${allowEmpty ? `<option value=""${cur ? '' : ' selected'}>—</option>` : ''}
    ${options.concat(extra).map(o => `<option${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('')}
  </select>`;
}

function rowHtml(d) {
  const stClass = d.cur_status === 'Выдан' ? 'st-issued' : d.cur_status === 'Удален' ? 'st-deleted' : 'st-reserve';
  const flag = d.flag ? `<span class="flag ${d.flag}">${d.flag === 'NEW' ? 'NEW' : 'UPD'}</span>` : '';
  const wa = (d.phones || []).map(p => `<a class="wa" target="_blank" href="https://wa.me/${p}" title="WhatsApp">💬 ${p.slice(-4)}</a>`).join('');
  const dateStr = d.doc_date ? d.doc_date.slice(0, 10).split('-').reverse().join('.') : '';
  const planVal = d.plan_contact ? d.plan_contact.slice(0, 10) : '';
  const reason = d.stage === 'Не состоялась'
    ? selectHtml(d, 'reject_reason', META.reject_reasons)
    : (d.stage === 'Удалён' || d.cur_status === 'Удалён')
      ? selectHtml(d, 'delete_reason', META.delete_reasons)
      : '<span class="cl">—</span>';
  const errTip = d.errors && d.errors.length ? ` title="${esc(d.errors.join('; '))}"` : '';
  return `<tr class="r-${d.level}" id="r-${cssKey(d.key)}">
    <td><span class="badge ${stClass}">${esc(d.cur_status)}</span>${flag}</td>
    <td><span class="hint ${d.level === 'error' ? 'err' : ''}"${errTip}>${esc(d.hint)}${d.overdue_contact ? ' · ⚠️' : ''}</span></td>
    <td class="td-copy" title="${esc(d.doc)}"><span class="copy-text" data-copy="${esc(d.doc_num)}">${esc(d.doc_num)}</span><svg class="copy-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></td>
    <td>${dateStr}<span class="cl">${d.workdays} раб.дн.</span></td>
    <td>${esc(d.city || '')}</td>
    <td><b>${esc(d.client || '')}</b><br>${wa}<span class="cl" title="${esc(d.comment_1c || '')}">${esc(d.comment_1c || '')}</span></td>
    <td class="sum">${money(d.amount)}</td>
    <td>${selectHtml(d, 'stage', META.stages)}</td>
    <td style="text-align:center"><label class="aether-check"><input type="checkbox" data-k="${esc(d.key)}" data-f="in_stock" ${d.in_stock ? 'checked' : ''}><span class="aether-check__box"><svg viewBox="0 0 14 14" fill="none"><path d="M3 7l3 3 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></label></td>
    <td>${selectHtml(d, 'next_step', META.next_steps)}</td>
    <td><input type="date" data-k="${esc(d.key)}" data-f="plan_contact" value="${planVal}" class="${d.overdue_contact ? 'late' : ''}"></td>
    <td>${reason}</td>
    <td class="td-narrow">${selectHtml(d, 'check_status', META.check_statuses, false)}</td>
    <td><input type="text" data-k="${esc(d.key)}" data-f="notes" value="${esc(d.notes || '')}" placeholder="..."></td>
    <td><span class="cl full">${esc(d.author || '')}</span></td>
    <td><button class="iconbtn" data-hist="${esc(d.key)}" title="История">🕘</button></td>
  </tr>`;
}

const cssKey = k => k.replace(/[^a-zA-Zа-яА-Я0-9]/g, '_');

function render() {
  const base = baseFiltered();
  renderQueues(base);
  let rows = base.filter(QUEUES.find(t => t.id === queue).f);
  rows.sort((a, b) => {
    let x = a[sortCol], y = b[sortCol];
    if (sortCol === 'status') { x = a.level; y = b.level; }
    if (typeof x === 'number' || typeof y === 'number') { x = x ?? -1e18; y = y ?? -1e18; return (x - y) * sortDir; }
    return String(x ?? '').localeCompare(String(y ?? ''), 'ru') * sortDir;
  });
  const thead = $('tbl').querySelector('thead');
  thead.innerHTML = '<tr>' + COLS.map(c =>
    `<th data-c="${c.id}">${c.name}${c.id === sortCol ? (sortDir < 0 ? ' ▼' : ' ▲') : ''}</th>`).join('') + '</tr>';
  thead.querySelectorAll('th').forEach(th => th.onclick = () => {
    const c = th.dataset.c;
    if (c === sortCol) sortDir *= -1; else { sortCol = c; sortDir = -1; }
    render();
  });
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  if (page >= pages) page = pages - 1;
  const pg = rows.slice(page * PAGE, (page + 1) * PAGE);
  $('tbl').querySelector('tbody').innerHTML =
    pg.map(rowHtml).join('') || '<tr><td colspan="16" style="text-align:center;color:#888;padding:22px">Нет записей 🎉</td></tr>';
  bindRowEvents();
  $('pinfo').textContent = `стр. ${page + 1}/${pages}`;
  $('prev').disabled = page <= 0; $('next').disabled = page >= pages - 1;
  $('totals').textContent = `${rows.length.toLocaleString('ru-RU')} сделок · ${mln(rows.reduce((s, d) => s + (d.amount || 0), 0))} тг`;
}

function bindRowEvents() {
  const tb = $('tbl').querySelector('tbody');
  tb.querySelectorAll('select[data-f], input[data-f]').forEach(el => {
    el.onchange = async () => {
      const f = el.dataset.f;
      const v = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
      await patch(el.dataset.k, { [f]: v });
    };
  });
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
function renderBoss() {
  const base = baseFiltered();
  const act = base.filter(d => !d.is_closed);
  const sum = a => a.reduce((s, d) => s + (d.amount || 0), 0);
  const risk = act.filter(d => d.level === 'risk'), ready = act.filter(d => d.level === 'ready');
  const errs = base.filter(d => d.level === 'error'), over = act.filter(d => d.overdue_contact);
  const lost = base.filter(d => d.is_closed && d.level !== 'done');
  const done = base.filter(d => d.level === 'done');
  $('bossKpis').innerHTML = `
    <div class="kpi"><div class="lbl">Активные сделки</div><div class="val">${act.length.toLocaleString('ru-RU')}</div><div class="det">${mln(sum(act))} тг</div></div>
    <div class="kpi risk"><div class="lbl">🔴 Под риском</div><div class="val">${risk.length}</div><div class="det">${mln(sum(risk))} тг</div></div>
    <div class="kpi ready"><div class="lbl">🟩 Выдать товар</div><div class="val">${ready.length}</div><div class="det">${mln(sum(ready))} тг</div></div>
    <div class="kpi warn"><div class="lbl">⏰ Просрочен контакт</div><div class="val">${over.length}</div><div class="det"></div></div>
    <div class="kpi err"><div class="lbl">🛑 Ошибки заполнения</div><div class="val">${errs.length}</div><div class="det"></div></div>
    <div class="kpi"><div class="lbl">🟢 Выдано</div><div class="val">${done.length.toLocaleString('ru-RU')}</div><div class="det">${mln(sum(done))} тг</div></div>
    <div class="kpi"><div class="lbl">⚫ Потеряно</div><div class="val">${lost.length.toLocaleString('ru-RU')}</div><div class="det">${mln(sum(lost))} тг</div></div>`;

  charts.forEach(c => c.destroy()); charts = [];
  if (!window.Chart) return;
  const bar = (el, labels, data, color, horizontal) => charts.push(new Chart($(el), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color }] },
    options: {
      indexAxis: horizontal ? 'y' : 'x', plugins: { legend: { display: false } },
      scales: { [horizontal ? 'x' : 'y']: { ticks: { callback: v => (v / 1e6) + ' млн' } } }
    },
  }));

  const stages = ['(нет этапа)', ...META.stages];
  bar('chFunnel', stages, stages.map(s => sum(base.filter(d => (d.stage || '(нет этапа)') === s))), '#3a7ca5');

  const reasons = {};
  lost.forEach(d => { const r = (d.reject_reason || d.delete_reason || '(без причины)').toLowerCase(); reasons[r] = (reasons[r] || 0) + (d.amount || 0); });
  const topR = Object.entries(reasons).sort((a, b) => b[1] - a[1]).slice(0, 10);
  bar('chLost', topR.map(x => x[0]), topR.map(x => x[1]), '#8a939d', true);

  const weeks = {};
  base.forEach(d => {
    if (!d.doc_date) return;
    const dt = new Date(d.doc_date);
    const onejan = new Date(dt.getFullYear(), 0, 1);
    const w = Math.ceil((((dt - onejan) / 864e5) + onejan.getDay() + 1) / 7);
    const k = `${dt.getFullYear()}-W${String(w).padStart(2, '0')}`;
    weeks[k] = (weeks[k] || 0) + (d.amount || 0);
  });
  const wk = Object.keys(weeks).sort();
  bar('chWeeks', wk, wk.map(k => weeks[k]), '#ff6a00');

  const cities = {};
  base.forEach(d => { const c = d.city || '(пусто)'; (cities[c] = cities[c] || [0, 0])[d.is_closed && d.level === 'done' ? 1 : 0] += d.amount || 0; });
  const topC = Object.entries(cities).sort((a, b) => (b[1][0] + b[1][1]) - (a[1][0] + a[1][1])).slice(0, 12);
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

  // менеджеры
  const mgr = {};
  base.forEach(d => {
    const a = d.author || '(пусто)';
    const m = mgr[a] = mgr[a] || { n: 0, sum: 0, act: 0, risk: 0, err: 0, over: 0, done: 0 };
    m.n++; m.sum += d.amount || 0;
    if (!d.is_closed) m.act++;
    if (d.level === 'risk') m.risk++;
    if (d.level === 'error') m.err++;
    if (d.overdue_contact && !d.is_closed) m.over++;
    if (d.level === 'done') m.done++;
  });
  const rows = Object.entries(mgr).sort((a, b) => b[1].sum - a[1].sum).slice(0, 40);
  $('tblMgr').querySelector('thead').innerHTML =
    '<tr><th>Менеджер</th><th>Сделок</th><th>Сумма</th><th>Активные</th><th>Под риском</th><th>Просрочено</th><th>Ошибки</th><th>Выдано</th></tr>';
  $('tblMgr').querySelector('tbody').innerHTML = rows.map(([a, m]) =>
    `<tr><td>${esc(a)}</td><td>${m.n}</td><td class="sum">${money(m.sum)}</td><td>${m.act}</td>
     <td style="color:${m.risk ? '#d63b3b' : '#999'};font-weight:700">${m.risk}</td>
     <td style="color:${m.over ? '#e6a700' : '#999'};font-weight:700">${m.over}</td>
     <td style="color:${m.err ? '#c2185b' : '#999'};font-weight:700">${m.err}</td><td>${m.done}</td></tr>`).join('');
}

/* ---------- режимы и события ---------- */
let mode = 'mgr';
document.querySelectorAll('.mode-tab').forEach(b => b.onclick = () => {
  mode = b.dataset.m;
  document.querySelectorAll('.mode-tab').forEach(x => x.classList.toggle('act', x === b));
  $('v-mgr').classList.toggle('hidden', mode !== 'mgr');
  $('v-boss').classList.toggle('hidden', mode !== 'boss');
  $('v-settings').classList.toggle('hidden', mode !== 'settings');
  refresh();
});

function refresh() {
  if (mode === 'mgr') render();
  else if (mode === 'boss') renderBoss();
  else renderSettings();
}

function renderSettings() {
  const tbody = $('tblSpec').querySelector('tbody');
  const rows = (META.specialists || []).sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  tbody.innerHTML = rows.map(s =>
    `<tr>
      <td>${esc(s.name)}</td>
      <td>${esc(s.city)}</td>
      <td><button class="iconbtn" onclick="delSpec(${s.id})" title="Удалить">❌</button></td>
    </tr>`
  ).join('') || '<tr><td colspan="3">Нет данных</td></tr>';
}

async function delSpec(id) {
  if (!confirm('Удалить эту зону ответственности?')) return;
  try {
    const r = await fetch('/api/specialists/' + id, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    toast('Удалено ✓');
    await loadAll();
  } catch (e) { toast('Ошибка: ' + e.message, true); }
}

$('btnAddSpec').onclick = async () => {
  const name = $('newSpecName').value.trim(), city = $('newSpecCity').value.trim();
  if (!name || !city) return toast('Введите имя и город', true);
  try {
    const r = await fetch('/api/specialists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, city })
    });
    if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    toast('Добавлено ✓');
    $('newSpecName').value = ''; $('newSpecCity').value = '';
    await loadAll();
  } catch (e) { toast('Ошибка: ' + e.message, true); }
};

$('fStage').onchange = () => { page = 0; refresh(); };
$('fStatus').onchange = () => { page = 0; refresh(); };
$('fMine').onchange = () => { page = 0; refresh(); };
$('q').oninput = () => { page = 0; render(); };
$('fPeriod').onchange = () => {
  const manual = $('fPeriod').value === 'manual';
  const el = $('manualDates');
  if (manual) { el.classList.remove('hidden'); el.style.display = 'flex'; }
  else { el.classList.add('hidden'); el.style.display = 'none'; }
  page = 0; refresh();
};
$('fFrom').onchange = $('fTo').onchange = () => { page = 0; refresh(); };
$('myCity').onchange = () => { localStorage.setItem('myCity', $('myCity').value); page = 0; refresh(); };
$('user').onchange = () => {
  localStorage.setItem('user', $('user').value);
  applyManagerZone();
  page = 0; refresh();
};
$('prev').onclick = () => { page--; render(); };
$('next').onclick = () => { page++; render(); };

$('btnImport').onclick = async () => {
  const b = $('btnImport');
  b.disabled = true; b.textContent = '⏳ Импорт...';
  // Покажем лоадер в таблице
  $('tbl').querySelector('tbody').innerHTML = '<tr><td colspan="16" style="padding: 100px 0;"><div class="loader-spinner"></div></td></tr>';
  try {
    const r = await fetch('/api/import', { method: 'POST' });
    if (r.status === 401) return location.href = '/login';
    const s = await r.json();
    if (s.error) throw new Error(s.error);
    toast(`Импорт: новых ${s.new}, обновлено ${s.updated}`);
    await loadAll(); refresh();
  } catch (e) { toast('Импорт не удался: ' + e.message, true); }
  b.disabled = false; b.textContent = '⟳ Обновить из 1С';
};

$('btnLogout').onclick = async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  location.href = '/login';
};

$('btnChangePw').onclick = async () => {
  const np = $('newPw').value;
  if (np.length < 4) return toast('Пароль слишком короткий', true);
  try {
    const r = await fetch('/api/auth/change-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: np })
    });
    if (!r.ok) throw new Error((await r.json()).error);
    toast('Пароль изменен!');
    $('pwDlg').close();
  } catch (e) { toast(e.message, true); }
};

loadAll();
