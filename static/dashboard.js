/* РМКО — Аналитический дашборд (multi-panel, client-side aggregation) */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const COLORS = ['#007AFF','#5856D6','#34C759','#FF9500','#FF3B30',
                   '#5AC8FA','#FF2D55','#64D2FF','#BF5AF2','#30D158',
                   '#AC8E68','#6366F1'];

  let charts = {};
  let filtersReady = false;
  let debounceId = null;

  /* ---- formatters ---- */
  function fmtShort(v) {
    if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(0) + 'K';
    return Math.round(v).toString();
  }
  function fmtMoney(v) { return Math.round(v).toLocaleString('ru-RU'); }
  function fmtTip(v) {
    return getMetric() === 'count'
      ? Math.round(v).toLocaleString('ru-RU') + ' сделок'
      : fmtMoney(v) + ' тг';
  }
  function fmtAxis(v) { return getMetric() === 'count' ? Math.round(v) : fmtShort(v); }

  /* ---- state readers ---- */
  function getPeriod() { return document.querySelector('#dashPeriodCtl input:checked')?.value || 'year'; }
  function getMetric() { return document.querySelector('#dashMetricCtl input:checked')?.value || 'sum'; }
  function checkedVals(id) {
    const allBox = document.querySelector('#' + id + ' input[value="__all__"]');
    if (allBox?.checked) return null;
    return [...document.querySelectorAll('#' + id + ' input:checked:not([value="__all__"])')].map(c => c.value);
  }

  /* ---- helpers ---- */
  function weekKey(ds) {
    if (!ds) return null;
    const d = new Date(ds);
    if (isNaN(d)) return null;
    const onejan = new Date(d.getFullYear(), 0, 1);
    const w = Math.ceil((((d - onejan) / 864e5) + onejan.getDay() + 1) / 7);
    return d.getFullYear().toString().slice(-2) + 'W' + String(w).padStart(2, '0');
  }
  function groupBy(rows, fn) {
    const g = {};
    rows.forEach(d => { const k = fn(d); if (k != null) (g[k] = g[k] || []).push(d); });
    return g;
  }
  function metricVal(rows) {
    const sum = rows.reduce((s, d) => s + (d.amount || 0), 0);
    const m = getMetric();
    if (m === 'count') return rows.length;
    if (m === 'avg') return rows.length ? sum / rows.length : 0;
    return sum;
  }

  /* ---- filtering ---- */
  function getFiltered() {
    let rows = typeof DATA !== 'undefined' ? DATA : [];
    const period = getPeriod();
    if (period !== 'all') {
      const days = { week: 7, month: 30, quarter: 90, year: 365 }[period] || 365;
      const cutoff = Date.now() - days * 864e5;
      rows = rows.filter(d => new Date(d.doc_date || d.created_at) >= cutoff);
    }
    const cities = checkedVals('dashCityList');
    if (cities) rows = rows.filter(d => cities.includes(d.city || ''));

    return rows;
  }

  /* ---- populate sidebar ---- */
  function populateFilters() {
    const data = typeof DATA !== 'undefined' ? DATA : [];
    buildList('dashCityList',
      [...new Set(data.map(d => d.city).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru')));

    filtersReady = true;
  }
  function buildList(id, items) {
    const el = $(id);
    el.innerHTML =
      '<label class="dash-check"><input type="checkbox" value="__all__" checked><span>Все</span></label>' +
      items.map(v => '<label class="dash-check"><input type="checkbox" value="' + v + '" checked><span>' + v + '</span></label>').join('');
    const allBox = el.querySelector('input[value="__all__"]');
    const others = () => [...el.querySelectorAll('input:not([value="__all__"])')];
    allBox.onchange = () => { others().forEach(c => c.checked = allBox.checked); scheduleUpdate(); };
    others().forEach(c => c.onchange = () => { allBox.checked = others().every(x => x.checked); scheduleUpdate(); });
  }

  /* ---- chart lifecycle ---- */
  function destroyAll() {
    Object.keys(charts).forEach(k => {
      if (charts[k]) { try { charts[k].destroy(); } catch (_) {} charts[k] = null; }
    });
  }

  /* ---- KPIs ---- */
  function renderKPIs(rows) {
    const total = rows.reduce((s, d) => s + (d.amount || 0), 0);
    const active = rows.filter(d => !d.is_closed);
    const done = rows.filter(d => d.level === 'done');
    const risk = rows.filter(d => d.level === 'risk');
    const over = active.filter(d => d.overdue_contact);
    const kpi = (lbl, val, det, cls) =>
      '<div class="kpi ' + cls + '"><div class="lbl">' + lbl + '</div><div class="val">' + val + '</div><div class="det">' + det + '</div></div>';
    $('dashKpis').innerHTML = [
      kpi('Оборот', fmtShort(total), rows.length.toLocaleString('ru-RU') + ' сделок', ''),
      kpi('Активные', active.length.toLocaleString('ru-RU'), fmtShort(active.reduce((s, d) => s + (d.amount || 0), 0)) + ' тг', ''),
      kpi('Средний чек', fmtMoney(rows.length ? total / rows.length : 0) + ' тг', '', ''),
      kpi('Выдано', done.length.toLocaleString('ru-RU'), fmtShort(done.reduce((s, d) => s + (d.amount || 0), 0)) + ' тг', 'ready'),
      kpi('Под риском', risk.length.toString(), '', 'risk'),
      kpi('Просрочен контакт', over.length.toString(), '', 'warn'),
    ].join('');
  }

  /* ---- Main trend area ---- */
  function renderTrend(rows) {
    var el = $('dashTrend'); el.innerHTML = '';
    var g = groupBy(rows, function(d) { return weekKey(d.doc_date || d.created_at); });
    var weeks = Object.keys(g).sort();
    if (!weeks.length) { el.innerHTML = '<div class="dash-empty">Нет данных за выбранный период</div>'; return; }
    var vals = weeks.map(function(w) { return Math.round(metricVal(g[w])); });
    charts.trend = new ApexCharts(el, {
      chart: { type: 'area', height: '100%', fontFamily: 'Inter, sans-serif', toolbar: { show: false },
               animations: { enabled: true, speed: 500 }, background: 'transparent' },
      series: [{ name: getMetric() === 'count' ? 'Кол-во сделок' : 'Оборот', data: vals }],
      xaxis: {
        categories: weeks,
        labels: { style: { fontSize: '10px', colors: '#86868b', fontFamily: 'JetBrains Mono' },
                  rotate: -45, rotateAlways: weeks.length > 16 },
        axisBorder: { color: 'rgba(0,0,0,0.08)' }, axisTicks: { color: 'rgba(0,0,0,0.08)' },
      },
      yaxis: { labels: { formatter: fmtAxis, style: { fontSize: '11px', colors: '#86868b' } } },
      dataLabels: {
        enabled: weeks.length <= 26,
        formatter: function(v) { return fmtShort(v); },
        style: { fontSize: '10px', fontWeight: 600, colors: ['#1C1D21'], fontFamily: 'Inter' },
        background: { enabled: false }, offsetY: -8,
      },
      colors: ['#007AFF'],
      fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.45, opacityTo: 0.05, stops: [0, 100] } },
      stroke: { curve: 'smooth', width: 2.5 },
      grid: { borderColor: 'rgba(0,0,0,0.05)', strokeDashArray: 3 },
      tooltip: { y: { formatter: fmtTip }, style: { fontSize: '13px', fontFamily: 'Inter' } },
      markers: { size: weeks.length <= 20 ? 4 : 0, colors: ['#007AFF'], strokeColors: '#fff', strokeWidth: 2 },
    });
    charts.trend.render();
  }

  /* ---- Top clients horizontal bar ---- */
  function renderClients(rows) {
    var el = $('dashClients'); el.innerHTML = '';
    var g = groupBy(rows, function(d) { return d.client || '(не указано)'; });
    var items = Object.entries(g).map(function(e) { return [e[0], metricVal(e[1])]; })
      .sort(function(a, b) { return b[1] - a[1]; }).slice(0, 15);
    if (!items.length) { el.innerHTML = '<div class="dash-empty">Нет данных</div>'; return; }
    charts.clients = new ApexCharts(el, {
      chart: { type: 'bar', height: '100%', fontFamily: 'Inter, sans-serif', toolbar: { show: false } },
      series: [{ data: items.map(function(e) { return e[1]; }) }],
      plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: '60%', distributed: true } },
      colors: COLORS,
      xaxis: {
        categories: items.map(function(e) { return e[0]; }),
        labels: { formatter: fmtAxis, style: { fontSize: '10px', colors: '#86868b' } },
      },
      yaxis: { labels: { style: { fontSize: '11px', colors: '#1C1D21' }, maxWidth: 200, trim: true } },
      dataLabels: {
        enabled: true, formatter: function(v) { return fmtShort(v); },
        style: { fontSize: '10px', fontWeight: 600, fontFamily: 'JetBrains Mono' }, offsetX: 6,
      },
      grid: { borderColor: 'rgba(0,0,0,0.04)' },
      legend: { show: false },
      tooltip: { y: { formatter: fmtTip } },
    });
    charts.clients.render();
  }

  /* ---- Cities vertical bar ---- */
  function renderCityBars(rows) {
    var el = $('dashCityBars'); el.innerHTML = '';
    var g = groupBy(rows, function(d) { return d.city || '(не указано)'; });
    var items = Object.entries(g).map(function(e) { return [e[0], metricVal(e[1])]; })
      .sort(function(a, b) { return b[1] - a[1]; }).slice(0, 12);
    if (!items.length) { el.innerHTML = '<div class="dash-empty">Нет данных</div>'; return; }
    charts.cities = new ApexCharts(el, {
      chart: { type: 'bar', height: '100%', fontFamily: 'Inter, sans-serif', toolbar: { show: false } },
      series: [{ data: items.map(function(e) { return e[1]; }) }],
      plotOptions: { bar: { borderRadius: 4, columnWidth: '55%', distributed: true } },
      colors: COLORS,
      xaxis: {
        categories: items.map(function(e) { return e[0]; }),
        labels: { style: { fontSize: '10px', colors: '#86868b' }, rotate: -45, rotateAlways: true, trim: true, maxHeight: 80 },
      },
      yaxis: { labels: { formatter: fmtAxis, style: { fontSize: '10px', colors: '#86868b' } } },
      dataLabels: {
        enabled: true, formatter: function(v) { return fmtShort(v); },
        style: { fontSize: '9px', fontWeight: 600, fontFamily: 'JetBrains Mono' }, offsetY: -4,
      },
      grid: { borderColor: 'rgba(0,0,0,0.04)' },
      legend: { show: false },
      tooltip: { y: { formatter: fmtTip } },
    });
    charts.cities.render();
  }

  /* ---- City trend multi-line ---- */
  function renderCityTrend(rows) {
    var el = $('dashCityTrend'); el.innerHTML = '';
    var cityTotals = {};
    rows.forEach(function(d) { var c = d.city || ''; cityTotals[c] = (cityTotals[c] || 0) + (d.amount || 0); });
    var top5 = Object.entries(cityTotals).sort(function(a, b) { return b[1] - a[1]; }).slice(0, 5).map(function(e) { return e[0]; });
    var wg = {};
    rows.forEach(function(d) {
      var w = weekKey(d.doc_date || d.created_at);
      var c = d.city || '';
      if (!w || top5.indexOf(c) < 0) return;
      if (!wg[w]) wg[w] = {};
      (wg[w][c] = wg[w][c] || []).push(d);
    });
    var weeks = Object.keys(wg).sort();
    if (!weeks.length) { el.innerHTML = '<div class="dash-empty">Нет данных</div>'; return; }
    var series = top5.map(function(city) {
      return { name: city, data: weeks.map(function(w) { return Math.round(metricVal(wg[w]?.[city] || [])); }) };
    });
    charts.cityTrend = new ApexCharts(el, {
      chart: { type: 'line', height: '100%', fontFamily: 'Inter, sans-serif', toolbar: { show: false } },
      series: series,
      xaxis: {
        categories: weeks,
        labels: { style: { fontSize: '9px', colors: '#86868b', fontFamily: 'JetBrains Mono' },
                  rotate: -45, rotateAlways: weeks.length > 12 },
      },
      yaxis: { labels: { formatter: fmtAxis, style: { fontSize: '10px', colors: '#86868b' } } },
      colors: COLORS.slice(0, 5),
      stroke: { curve: 'smooth', width: 2.5 },
      markers: { size: weeks.length <= 15 ? 3 : 0 },
      dataLabels: {
        enabled: weeks.length <= 15,
        formatter: function(v) { return fmtShort(v); },
        style: { fontSize: '9px', fontWeight: 600, fontFamily: 'JetBrains Mono' },
        background: { enabled: false },
      },
      grid: { borderColor: 'rgba(0,0,0,0.04)' },
      legend: { position: 'top', fontSize: '11px', fontFamily: 'Inter',
                labels: { colors: '#54545a' }, markers: { size: 6, offsetX: -3 } },
      tooltip: { y: { formatter: fmtTip } },
    });
    charts.cityTrend.render();
  }

  /* ---- orchestration ---- */
  function update() {
    destroyAll();
    var rows = getFiltered();
    renderKPIs(rows);
    renderTrend(rows);
    renderClients(rows);
    renderCityBars(rows);
    renderCityTrend(rows);
  }
  function scheduleUpdate() {
    if (debounceId) clearTimeout(debounceId);
    debounceId = setTimeout(update, 120);
  }
  function bindControls() {
    document.querySelectorAll('#dashPeriodCtl input, #dashMetricCtl input').forEach(function(r) { r.onchange = update; });
  }

  /* ---- public ---- */
  window.initDashboard = function () {
    if (!filtersReady) { populateFilters(); bindControls(); }
    requestAnimationFrame(update);
  };
})();
