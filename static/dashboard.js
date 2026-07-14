"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const COLORS = ['#007AFF', '#5856D6', '#34C759', '#FF9500', '#FF3B30',
        '#5AC8FA', '#FF2D55', '#64D2FF', '#BF5AF2', '#30D158',
        '#AC8E68', '#6366F1'];
    let charts = {};
    let filtersReady = false;
    let debounceId = null;
    /* ---- formatters ---- */
    function fmtShort(v) {
        if (Math.abs(v) >= 1e9)
            return (v / 1e9).toFixed(1) + 'B';
        if (Math.abs(v) >= 1e6)
            return (v / 1e6).toFixed(1) + 'M';
        if (Math.abs(v) >= 1e3)
            return (v / 1e3).toFixed(0) + 'K';
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
        if (allBox?.checked)
            return null;
        return [...document.querySelectorAll('#' + id + ' input:checked:not([value="__all__"])')].map(c => c.value);
    }
    /* ---- helpers ---- */
    function weekKey(ds) {
        if (!ds)
            return null;
        const d = new Date(ds);
        if (isNaN(d.getTime()))
            return null;
        const onejan = new Date(d.getFullYear(), 0, 1);
        const w = Math.ceil((((d.getTime() - onejan.getTime()) / 864e5) + onejan.getDay() + 1) / 7);
        return d.getFullYear().toString().slice(-2) + 'W' + String(w).padStart(2, '0');
    }
    function groupBy(rows, fn) {
        const g = {};
        rows.forEach(d => { const k = fn(d); if (k != null)
            (g[k] = g[k] || []).push(d); });
        return g;
    }
    function metricVal(rows) {
        const sum = rows.reduce((s, d) => s + (d.amount || 0), 0);
        const m = getMetric();
        if (m === 'count')
            return rows.length;
        if (m === 'avg')
            return rows.length ? sum / rows.length : 0;
        return sum;
    }
    /* ---- filtering ---- */
    function getFiltered() {
        let rows = typeof DATA !== 'undefined' ? DATA : [];
        const period = getPeriod();
        if (period !== 'all') {
            const days = { week: 7, month: 30, quarter: 90, year: 365 }[period] || 365;
            const cutoff = Date.now() - days * 864e5;
            rows = rows.filter(d => new Date(d.doc_date || d.created_at || 0).getTime() >= cutoff);
        }
        const cities = checkedVals('dashCityList');
        if (cities)
            rows = rows.filter(d => cities.includes(d.city || ''));
        return rows;
    }
    /* ---- populate sidebar ---- */
    function populateFilters() {
        const data = typeof DATA !== 'undefined' ? DATA : [];
        buildList('dashCityList', [...new Set(data.map(d => d.city).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru')));
        filtersReady = true;
    }
    function buildList(id, items) {
        const el = $(id);
        if (!el)
            return;
        el.innerHTML =
            '<label class="dash-check"><input type="checkbox" value="__all__" checked><span>Все</span></label>' +
                items.map(v => '<label class="dash-check"><input type="checkbox" value="' + v + '" checked><span>' + v + '</span></label>').join('');
        const allBox = el.querySelector('input[value="__all__"]');
        const others = () => [...document.querySelectorAll('#' + id + ' input:not([value="__all__"])')];
        allBox.onchange = () => { others().forEach(c => c.checked = allBox.checked); scheduleUpdate(); };
        others().forEach(c => c.onchange = () => { allBox.checked = others().every(x => x.checked); scheduleUpdate(); });
    }
    /* ---- chart lifecycle ---- */
    function destroyAll() {
        Object.keys(charts).forEach(k => {
            if (charts[k]) {
                try {
                    charts[k].destroy();
                }
                catch (_) { }
                charts[k] = null;
            }
        });
    }
    /* ---- KPIs ---- */
    function renderKPIs(rows) {
        const total = rows.reduce((s, d) => s + (d.amount || 0), 0);
        const active = rows.filter(d => !d.is_closed);
        const done = rows.filter(d => d.level === 'done');
        const risk = rows.filter(d => d.level === 'risk');
        const over = active.filter(d => d.overdue_contact);
        const kpi = (lbl, val, det, cls) => '<div class="kpi ' + cls + '"><div class="lbl">' + lbl + '</div><div class="val">' + val + '</div><div class="det">' + det + '</div></div>';
        const kpisEl = $('dashKpis');
        if (kpisEl) {
            kpisEl.innerHTML = [
                kpi('Оборот', fmtShort(total), rows.length.toLocaleString('ru-RU') + ' сделок', ''),
                kpi('Активные', active.length.toLocaleString('ru-RU'), fmtShort(active.reduce((s, d) => s + (d.amount || 0), 0)) + ' тг', ''),
                kpi('Средний чек', fmtMoney(rows.length ? total / rows.length : 0) + ' тг', '', ''),
                kpi('Выдано', done.length.toLocaleString('ru-RU'), fmtShort(done.reduce((s, d) => s + (d.amount || 0), 0)) + ' тг', 'ready'),
                kpi('Под риском', risk.length.toString(), '', 'risk'),
                kpi('Просрочен контакт', over.length.toString(), '', 'warn'),
            ].join('');
        }
    }
    /* ---- Main trend area ---- */
    function renderTrend(rows) {
        var el = $('dashTrend');
        if (!el)
            return;
        el.innerHTML = '';
        var g = groupBy(rows, function (d) { return weekKey(d.doc_date || d.created_at); });
        var weeks = Object.keys(g).sort();
        if (!weeks.length) {
            el.innerHTML = '<div class="dash-empty">Нет данных за выбранный период</div>';
            return;
        }
        var vals = weeks.map(function (w) { return Math.round(metricVal(g[w])); });
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
                formatter: function (v) { return fmtShort(v); },
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
        var el = $('dashClients');
        if (!el)
            return;
        el.innerHTML = '';
        var g = groupBy(rows, function (d) { return d.client || '(не указано)'; });
        var items = Object.entries(g).map(function (e) { return [e[0], metricVal(e[1])]; })
            .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 15);
        if (!items.length) {
            el.innerHTML = '<div class="dash-empty">Нет данных</div>';
            return;
        }
        charts.clients = new ApexCharts(el, {
            chart: { type: 'bar', height: '100%', fontFamily: 'Inter, sans-serif', toolbar: { show: false } },
            series: [{ data: items.map(function (e) { return e[1]; }) }],
            plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: '60%', distributed: true } },
            colors: COLORS,
            xaxis: {
                categories: items.map(function (e) { return e[0]; }),
                labels: { formatter: fmtAxis, style: { fontSize: '10px', colors: '#86868b' } },
            },
            yaxis: { labels: { style: { fontSize: '11px', colors: '#1C1D21' }, maxWidth: 200, trim: true } },
            dataLabels: {
                enabled: true, formatter: function (v) { return fmtShort(v); },
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
        var el = $('dashCityBars');
        if (!el)
            return;
        el.innerHTML = '';
        var g = groupBy(rows, function (d) { return d.city || '(не указано)'; });
        var items = Object.entries(g).map(function (e) { return [e[0], metricVal(e[1])]; })
            .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 12);
        if (!items.length) {
            el.innerHTML = '<div class="dash-empty">Нет данных</div>';
            return;
        }
        charts.cities = new ApexCharts(el, {
            chart: { type: 'bar', height: '100%', fontFamily: 'Inter, sans-serif', toolbar: { show: false } },
            series: [{ data: items.map(function (e) { return e[1]; }) }],
            plotOptions: { bar: { borderRadius: 4, columnWidth: '55%', distributed: true } },
            colors: COLORS,
            xaxis: {
                categories: items.map(function (e) { return e[0]; }),
                labels: { style: { fontSize: '10px', colors: '#86868b' }, rotate: -45, rotateAlways: true, trim: true, maxHeight: 80 },
            },
            yaxis: { labels: { formatter: fmtAxis, style: { fontSize: '10px', colors: '#86868b' } } },
            dataLabels: {
                enabled: true, formatter: function (v) { return fmtShort(v); },
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
        var el = $('dashCityTrend');
        if (!el)
            return;
        el.innerHTML = '';
        var cityTotals = {};
        rows.forEach(function (d) { var c = d.city || ''; cityTotals[c] = (cityTotals[c] || 0) + (d.amount || 0); });
        var top5 = Object.entries(cityTotals).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 5).map(function (e) { return e[0]; });
        var wg = {};
        rows.forEach(function (d) {
            var w = weekKey(d.doc_date || d.created_at);
            var c = d.city || '';
            if (!w || top5.indexOf(c) < 0)
                return;
            if (!wg[w])
                wg[w] = {};
            (wg[w][c] = wg[w][c] || []).push(d);
        });
        var weeks = Object.keys(wg).sort();
        if (!weeks.length) {
            el.innerHTML = '<div class="dash-empty">Нет данных</div>';
            return;
        }
        var series = top5.map(function (city) {
            return { name: city, data: weeks.map(function (w) { return Math.round(metricVal(wg[w]?.[city] || [])); }) };
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
                formatter: function (v) { return fmtShort(v); },
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
        if (debounceId)
            clearTimeout(debounceId);
        debounceId = setTimeout(update, 120);
    }
    function bindControls() {
        document.querySelectorAll('#dashPeriodCtl input, #dashMetricCtl input').forEach(function (r) { r.onchange = update; });
    }
    /* ---- public ---- */
    window.initDashboard = function () {
        if (!filtersReady) {
            populateFilters();
            bindControls();
        }
        requestAnimationFrame(update);
    };
})();
/* ============================================================
   B2B BOSS DASHBOARD (Premium UI)
   ============================================================ */
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    let bossCharts = {};
    const BOSS_COLORS = {
        primary: '#2563EB',
        purple: '#7C3AED',
        green: '#10B981',
        red: '#EF4444',
        warning: '#F59E0B',
        ink: '#1C1D21',
        inkSec: '#54545a',
        grid: 'rgba(0,0,0,0.04)'
    };
    function initBossCharts(data) {
        if (bossCharts.trend)
            bossCharts.trend.destroy();
        if (bossCharts.funnel)
            bossCharts.funnel.destroy();
        if (bossCharts.timeline)
            bossCharts.timeline.destroy();
        if (bossCharts.heatmap)
            bossCharts.heatmap.destroy();
        // 1. Pipeline Velocity Trends (Main Chart)
        const trendEl = $('bossTrendChartContainer');
        if (trendEl) {
            trendEl.innerHTML = '';
            const cats = data.charts?.trend?.categories || ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];
            const valsNet = data.charts?.trend?.net || [31, 40, 28, 51, 42, 109, 100, 115, 120, 105, 90, 130];
            const valsProf = data.charts?.trend?.prof || [11, 32, 45, 32, 34, 52, 41, 55, 60, 48, 50, 70];
            const trendOptions = {
                series: [{
                        name: 'Выручка (М)',
                        data: valsNet
                    }, {
                        name: 'Маржа (М)',
                        data: valsProf
                    }],
                chart: {
                    height: '100%',
                    type: 'area',
                    fontFamily: 'Inter, sans-serif',
                    toolbar: { show: false },
                    background: 'transparent'
                },
                colors: [BOSS_COLORS.primary, BOSS_COLORS.purple],
                fill: {
                    type: 'gradient',
                    gradient: {
                        shadeIntensity: 1,
                        opacityFrom: 0.4,
                        opacityTo: 0.05,
                        stops: [0, 90, 100]
                    }
                },
                dataLabels: { enabled: false },
                stroke: { curve: 'smooth', width: 3 },
                xaxis: {
                    categories: cats,
                    axisBorder: { show: false },
                    axisTicks: { show: false },
                    labels: { style: { colors: BOSS_COLORS.inkSec, fontSize: '12px' } }
                },
                yaxis: {
                    labels: {
                        style: { colors: BOSS_COLORS.inkSec, fontSize: '12px' },
                        formatter: (val) => val + 'M'
                    }
                },
                grid: {
                    borderColor: BOSS_COLORS.grid,
                    strokeDashArray: 4,
                    yaxis: { lines: { show: true } }
                },
                legend: { position: 'top', horizontalAlign: 'right' }
            };
            bossCharts.trend = new ApexCharts(trendEl, trendOptions);
            bossCharts.trend.render();
        }
        // 2. Stage Conversion Funnel (Funnel Chart)
        const funnelEl = $('bossFunnelChartContainer');
        if (funnelEl) {
            funnelEl.innerHTML = '';
            const funnelOptions = {
                series: [{
                        name: 'Сделок',
                        data: [
                            data.charts?.funnel?.vyp || 1380,
                            data.charts?.funnel?.vyd || 1100,
                            (data.charts?.funnel?.vyd || 1100) * 0.8,
                            data.charts?.funnel?.rez || 600,
                            data.charts?.funnel?.pure || 420
                        ]
                    }],
                chart: {
                    type: 'bar',
                    height: '100%',
                    fontFamily: 'Inter, sans-serif',
                    toolbar: { show: false },
                    background: 'transparent'
                },
                plotOptions: {
                    bar: {
                        borderRadius: 6,
                        horizontal: true,
                        barHeight: '60%',
                        isFunnel: true
                    },
                },
                dataLabels: {
                    enabled: true,
                    formatter: function (val, opt) {
                        const labels = opt.w.globals.labels;
                        const currentIdx = opt.dataPointIndex;
                        let dropoff = '';
                        if (currentIdx > 0) {
                            const prevVal = opt.w.config.series[0].data[currentIdx - 1];
                            const pct = prevVal ? Math.round((prevVal - val) / prevVal * 100) : 0;
                            dropoff = ` (-${pct}%)`;
                        }
                        return labels[currentIdx] + ': ' + val + dropoff;
                    },
                    dropShadow: { enabled: true }
                },
                colors: [BOSS_COLORS.primary],
                xaxis: {
                    categories: ['Квалификация', 'Встреча', 'КП', 'Договор', 'Выдано'],
                    labels: { show: false },
                    axisBorder: { show: false },
                    axisTicks: { show: false }
                },
                yaxis: { show: false },
                grid: { show: false },
                legend: { show: false }
            };
            bossCharts.funnel = new ApexCharts(funnelEl, funnelOptions);
            bossCharts.funnel.render();
        }
        // 3. Drill-Down Trace Timeline (Gantt Chart)
        const traceEl = $('bossTraceTimelineContainer');
        if (traceEl) {
            traceEl.innerHTML = '';
            const traceOptions = {
                series: [
                    {
                        name: 'Ожидаемый период',
                        data: data.charts?.timeline?.expected || [
                            { x: 'Квалификация', y: [new Date('2023-10-01').getTime(), new Date('2023-10-03').getTime()] },
                            { x: 'КП', y: [new Date('2023-10-03').getTime(), new Date('2023-10-08').getTime()] },
                            { x: 'Переговоры', y: [new Date('2023-10-08').getTime(), new Date('2023-10-15').getTime()] },
                            { x: 'Договор', y: [new Date('2023-10-15').getTime(), new Date('2023-10-20').getTime()] }
                        ]
                    },
                    {
                        name: 'Фактическая трассировка (Сделка #10294)',
                        data: data.charts?.timeline?.actual || [
                            { x: 'Квалификация', y: [new Date('2023-10-01').getTime(), new Date('2023-10-04').getTime()] },
                            { x: 'КП', y: [new Date('2023-10-04').getTime(), new Date('2023-10-12').getTime()] },
                            { x: 'Переговоры', y: [new Date('2023-10-12').getTime(), new Date('2023-10-22').getTime()] },
                            { x: 'Договор', y: [new Date('2023-10-22').getTime(), new Date('2023-10-28').getTime()] }
                        ]
                    }
                ],
                chart: {
                    height: '100%',
                    type: 'rangeBar',
                    fontFamily: 'Inter, sans-serif',
                    toolbar: { show: false }
                },
                plotOptions: {
                    bar: { horizontal: true, barHeight: '80%', borderRadius: 4 }
                },
                xaxis: { type: 'datetime' },
                colors: [BOSS_COLORS.grid, BOSS_COLORS.warning],
                fill: { type: 'solid', opacity: [0.5, 1] },
                legend: { position: 'top', horizontalAlign: 'right' }
            };
            bossCharts.timeline = new ApexCharts(traceEl, traceOptions);
            bossCharts.timeline.render();
        }
        // 4. Stage Duration Heatmap
        const heatEl = $('bossStageHeatmapContainer');
        if (heatEl) {
            heatEl.innerHTML = '';
            const heatOptions = {
                series: data.charts?.heatmap || [
                    { name: 'Крупный бизнес', data: [{ x: 'Квал', y: 4 }, { x: 'Встреча', y: 7 }, { x: 'КП', y: 14 }, { x: 'Договор', y: 21 }] },
                    { name: 'Средний бизнес', data: [{ x: 'Квал', y: 2 }, { x: 'Встреча', y: 4 }, { x: 'КП', y: 8 }, { x: 'Договор', y: 12 }] },
                    { name: 'Малый бизнес', data: [{ x: 'Квал', y: 1 }, { x: 'Встреча', y: 2 }, { x: 'КП', y: 3 }, { x: 'Договор', y: 5 }] }
                ],
                chart: {
                    height: '100%',
                    type: 'heatmap',
                    fontFamily: 'Inter, sans-serif',
                    toolbar: { show: false }
                },
                plotOptions: {
                    heatmap: {
                        shadeIntensity: 0.5,
                        radius: 8,
                        colorScale: {
                            ranges: [
                                { from: 0, to: 5, color: BOSS_COLORS.green, name: 'Быстро (<5д)' },
                                { from: 6, to: 14, color: BOSS_COLORS.warning, name: 'Средне (6-14д)' },
                                { from: 15, to: 30, color: BOSS_COLORS.red, name: 'Медленно (>14д)' }
                            ]
                        }
                    }
                },
                dataLabels: { enabled: true, style: { colors: ['#fff'] } },
            };
            bossCharts.heatmap = new ApexCharts(heatEl, heatOptions);
            bossCharts.heatmap.render();
        }
    }
    function mockBossData(data) {
        const degradedBadge = $('degradedBadge');
        if (degradedBadge) {
            if (data.meta && data.meta.degraded) {
                degradedBadge.style.display = 'inline-block';
            }
            else {
                degradedBadge.style.display = 'none';
            }
        }
        const aiInsightText = $('aiInsightText');
        if (data.alerts && aiInsightText) {
            aiInsightText.innerText = Array.isArray(data.alerts) ? data.alerts.join(' ') : data.alerts;
        }
        const kpiPipelineValue = $('kpiPipelineValue');
        const kpiMRR = $('kpiMRR');
        const kpiForecast = $('kpiForecast');
        const kpiRiskValue = $('kpiRiskValue');
        if (data.kpi) {
            if (kpiPipelineValue)
                kpiPipelineValue.innerText = data.kpi.tot_net || '--';
            if (kpiMRR)
                kpiMRR.innerText = data.kpi.margin_norm || '--';
            if (kpiForecast)
                kpiForecast.innerText = data.kpi.forecast || '--';
            if (kpiRiskValue)
                kpiRiskValue.innerText = data.kpi.risk_value || '--';
        }
        else {
            if (kpiPipelineValue)
                kpiPipelineValue.innerText = '145.2M ₸';
            if (kpiMRR)
                kpiMRR.innerText = '12.4M ₸';
            if (kpiForecast)
                kpiForecast.innerText = '104%';
            if (kpiRiskValue)
                kpiRiskValue.innerText = '8.5M ₸';
        }
        // Populate Real-Time Alerts
        const alertsEl = $('bossAlertsList');
        if (alertsEl) {
            alertsEl.innerHTML = `
        <div class="alert-item">
          <div class="alert-icon critical"><svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg></div>
          <div class="alert-content">
            <div class="alert-title">Нарушение времени отклика на лид: Сделка #10932 (ТОО "Альфа")</div>
            <div class="alert-desc">Зависла на этапе "Согласование договора" >14 дней. Trace ID: tr_8f92a1. Ожидаемое закрытие было 3 дня назад.</div>
            <div class="alert-meta">Ответственный: Тимур Ж. • 4.2M ₸</div>
          </div>
        </div>
        <div class="alert-item">
          <div class="alert-icon warning"><svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg></div>
          <div class="alert-content">
            <div class="alert-title">Сделки без активности (зомби): Сделка #10844</div>
            <div class="alert-desc">Нет активности 15 дней. Последнее событие: "КП Отправлено".</div>
            <div class="alert-meta">Ответственный: Елена М. • 1.8M ₸</div>
          </div>
        </div>
        <div class="alert-item">
          <div class="alert-icon info"><svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg></div>
          <div class="alert-content">
            <div class="alert-title">Обнаружена аномалия: Падение скорости</div>
            <div class="alert-desc">Общая скорость воронки для малого бизнеса упала на 22% на этой неделе.</div>
            <div class="alert-meta">Системное уведомление • Корреляционный ID: evt_992x</div>
          </div>
        </div>
      `;
        }
        const tbody = document.querySelector('#tblMgr tbody');
        if (tbody) {
            let html = '';
            if (data.managers && data.managers.length > 0) {
                html = data.managers.slice(0, 10).map(m => {
                    const turnover = m.net ? (m.net / 1e6).toFixed(1) + 'M' : '0M';
                    const margin = m.margin ? m.margin.toFixed(1) : '0.0';
                    const prof = m.prof || 0;
                    const cost = (m.net || 0) - prof;
                    const markup = cost > 0 ? (prof / cost * 100).toFixed(0) : '0';
                    const rSum = m.funnel?.raw_sum ? m.funnel.raw_sum.toFixed(0) : '0';
                    const fSum = m.funnel?.fair_sum ? m.funnel.fair_sum.toFixed(0) : '0';
                    return `
          <tr>
            <td>
              <div style="display:flex; align-items:center; gap:10px;">
                <div style="width:32px; height:32px; border-radius:50%; background:var(--color-bg); display:flex; align-items:center; justify-content:center; font-weight:600; color:var(--color-ink-secondary);">${m.short[0]}</div>
                <span style="font-weight:500;">${m.short}</span>
              </div>
            </td>
            <td style="font-family:'JetBrains Mono', monospace; font-weight:600; color:var(--color-ink);">${turnover}</td>
            <td>${(m.margin || 0) >= 12 ? `<span style="color:var(--c-done); font-weight:600;">${margin}%</span>` : `<span style="color:var(--c-risk); font-weight:600;">${margin}%</span>`}</td>
            <td>${markup}%</td>
            <td>${m.docs || 0}</td>
            <td>${m.clis || 0}</td>
            <td><span style="color:var(--color-ink-secondary)">${rSum}%</span> / <span style="font-weight:600; color:var(--color-ink)">${fSum}%</span></td>
          </tr>`;
                }).join('');
            }
            else {
                const mockManagers = [
                    { name: 'Алина В.', turnover: '12.1M', margin: 18.2, markup: 24, deals: 45, clients: 12, buyoutRaw: 88, buyoutFair: 94 },
                    { name: 'Тимур Ж.', turnover: '8.4M', margin: 11.5, markup: 15, deals: 32, clients: 8, buyoutRaw: 76, buyoutFair: 82 },
                    { name: 'Елена М.', turnover: '9.0M', margin: 14.0, markup: 18, deals: 28, clients: 9, buyoutRaw: 80, buyoutFair: 85 },
                    { name: 'Данияр К.', turnover: '14.5M', margin: 21.0, markup: 28, deals: 52, clients: 15, buyoutRaw: 92, buyoutFair: 96 },
                ];
                html = mockManagers.map(m => `
          <tr>
            <td>
              <div style="display:flex; align-items:center; gap:10px;">
                <div style="width:32px; height:32px; border-radius:50%; background:var(--color-bg); display:flex; align-items:center; justify-content:center; font-weight:600; color:var(--color-ink-secondary);">${m.name[0]}</div>
                <span style="font-weight:500;">${m.name}</span>
              </div>
            </td>
            <td style="font-family:'JetBrains Mono', monospace; font-weight:600; color:var(--color-ink);">${m.turnover}</td>
            <td>${m.margin >= 12 ? `<span style="color:var(--c-done); font-weight:600;">${m.margin}%</span>` : `<span style="color:var(--c-risk); font-weight:600;">${m.margin}%</span>`}</td>
            <td>${m.markup}%</td>
            <td>${m.deals}</td>
            <td>${m.clients}</td>
            <td><span style="color:var(--color-ink-secondary)">${m.buyoutRaw}%</span> / <span style="font-weight:600; color:var(--color-ink)">${m.buyoutFair}%</span></td>
          </tr>
        `).join('');
            }
            tbody.innerHTML = html;
        }
    }
    window.initBossDashboard = async function () {
        try {
            const res = await fetch('/api/boss/observability');
            if (!res.ok)
                throw new Error('Data fetch failed');
            const data = await res.json();
            mockBossData(data);
            initBossCharts(data);
        }
        catch (e) {
            console.error('Failed to load boss data:', e);
            mockBossData({});
            initBossCharts({});
        }
    };
    // Add event listener to refresh button
    document.addEventListener('DOMContentLoaded', () => {
        const btn = $('bossRefreshBtn');
        if (btn) {
            btn.addEventListener('click', () => {
                btn.innerHTML = 'Обновление...';
                setTimeout(() => {
                    btn.innerHTML = '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg> Обновить';
                    window.initBossDashboard();
                }, 500);
            });
        }
    });
})();
