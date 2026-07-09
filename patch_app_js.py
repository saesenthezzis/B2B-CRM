import os
import re

APP_JS = "static/app.js"

with open(APP_JS, "r", encoding="utf-8") as f:
    content = f.read()

# Replace loadAll
load_all_pattern = re.compile(r'async function loadAll\(\) \{[\s\S]*?render\(\);\n  \} catch \(e\) \{[\s\S]*?\}\n\}')
new_load_all = """async function loadAll() {
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
}"""
content = load_all_pattern.sub(new_load_all, content)

# Remove QUEUES, periodRange, baseFiltered, renderQueues
queues_pattern = re.compile(r'/\* ---------- очереди ---------- \*/[\s\S]*?function renderQueues\(rows\) \{[\s\S]*?\}\n')
content = queues_pattern.sub("", content)

# Add buildParams, renderQueues (new), and new render
new_render_logic = """/* ---------- очереди ---------- */
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
"""
# Find "const COLS = [" to insert this before
content = content.replace("/* ---------- таблица менеджера ---------- */", new_render_logic + "\n/* ---------- таблица менеджера ---------- */")

# Replace render()
render_pattern = re.compile(r'function render\(\) \{[\s\S]*?totals\'\)\.textContent =.*?;[\s\S]*?\}')
new_render = """async function render() {
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
}"""
content = render_pattern.sub(new_render, content)

# Replace renderBoss()
render_boss_pattern = re.compile(r'let charts = \[\];\nfunction renderBoss\(\) \{[\s\S]*?\}\n\}')
new_render_boss = """let charts = [];
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
}"""
content = render_boss_pattern.sub(new_render_boss, content)

with open(APP_JS, "w", encoding="utf-8") as f:
    f.write(content)
