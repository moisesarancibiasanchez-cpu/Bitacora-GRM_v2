// ============================================================
// app.js — Lógica de renderizado e interactividad del dashboard
// ============================================================

let estado = { dias: 30, dataset: null, autoTimer: null, theme: 'light' };

// ============== INIT ==============
window.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  cargar();
});

// ============== EVENTOS ==============
function bindEvents() {
  // Periodo
  document.querySelectorAll('.period-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const dias = parseInt(btn.dataset.dias);
      document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active', 'bg-indigo-600', 'text-white'));
      btn.classList.add('active');
      estado.dias = dias;
      cargar();
    });
  });

  // Refresh
  document.getElementById('btn-refresh').addEventListener('click', () => {
    const icon = document.getElementById('icon-refresh');
    icon.classList.add('spin');
    cargar();
    setTimeout(() => icon.classList.remove('spin'), 600);
  });

  // Auto-refresh
  document.getElementById('btn-autorefresh').addEventListener('click', () => {
    const btn = document.getElementById('btn-autorefresh');
    const state = document.getElementById('auto-state');
    if (estado.autoTimer) {
      clearInterval(estado.autoTimer);
      estado.autoTimer = null;
      state.textContent = 'OFF';
      btn.classList.remove('bg-emerald-50', 'border-emerald-300', 'text-emerald-700');
      toast('Auto-refresh desactivado');
    } else {
      estado.autoTimer = setInterval(cargar, 60000);
      state.textContent = 'ON';
      btn.classList.add('bg-emerald-50', 'border-emerald-300', 'text-emerald-700');
      toast('Auto-refresh activado · 60s');
    }
  });

  // Theme
  document.getElementById('btn-theme').addEventListener('click', () => {
    document.documentElement.classList.toggle('dark');
    estado.theme = estado.theme === 'light' ? 'dark' : 'light';
    if (estado.dataset) {
      // re-render charts to pick up new colors
      renderCharts(estado.dataset);
      renderFunnel(estado.dataset.funnel);
      renderDistEstado(estado.dataset.distEstado);
      renderDistPrioridad(estado.dataset.distPrioridad);
      renderCuentaResultado(estado.dataset.cuentaResultado);
      renderTickets();
    }
  });

  // Export CSV
  document.getElementById('btn-export').addEventListener('click', () => {
    if (!estado.dataset) return;
    const rows = [['codigo', 'tipo', 'titulo', 'estado', 'prioridad', 'asignado', 'solicitante', 'canal', 'sla_cumplido', 'creado', 'cerrado']];
    estado.dataset.tickets.forEach(t => {
      rows.push([
        t.codigo, t.tipo, `"${t.titulo.replace(/"/g, '""')}"`, t.estado, t.prioridad,
        t.asignado || '', t.solicitante, t.canal, t.slaCumplido,
        t.creado.toISOString(), t.cerrado ? t.cerrado.toISOString() : '',
      ]);
    });
    const csv = rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `incidencias_${estado.dias}d_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast(`Exportadas ${rows.length - 1} filas a CSV`);
  });

  // Riesgo horas
  document.getElementById('riesgo-horas').addEventListener('change', (e) => {
    const horas = parseInt(e.target.value);
    if (estado.dataset) renderRiesgo(estado.dataset.tickets.filter(t => !t.cerrado), horas);
  });

  // Tickets filter & priority
  document.getElementById('tickets-filter').addEventListener('input', renderTickets);
  document.getElementById('tickets-prio').addEventListener('change', renderTickets);

  // Modal close
  document.getElementById('modal-close').addEventListener('click', () => document.getElementById('modal-backdrop').classList.add('hidden'));
  document.getElementById('modal-backdrop').addEventListener('click', (e) => {
    if (e.target.id === 'modal-backdrop') document.getElementById('modal-backdrop').classList.add('hidden');
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.getElementById('modal-backdrop').classList.add('hidden');
  });
}

// ============== TOAST ==============
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add('hidden'), 2500);
}

// ============== CARGAR ==============
function cargar() {
  const ds = getDataset(estado.dias);
  estado.dataset = ds;
  renderStatsBar(ds.kpis, ds.deltas);
  renderKPIs(ds.kpis, ds.deltas, ds.series);
  renderCharts(ds);
  renderFunnel(ds.funnel);
  renderDistEstado(ds.distEstado);
  renderDistPrioridad(ds.distPrioridad);
  renderRiesgo(ds.tickets.filter(t => !t.cerrado), 72);
  renderCuentaResultado(ds.cuentaResultado);
  renderTickets();
  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('es-CL');
}

// ============== STATS BAR ==============
function renderStatsBar(k, deltas) {
  document.getElementById('stat-total').textContent = k.total.toLocaleString('es-CL');
  document.getElementById('stat-nuevas').textContent = k.incidenciasNuevas7d.toLocaleString('es-CL');
  document.getElementById('stat-abiertas').textContent = k.incidenciasAbiertas.toLocaleString('es-CL');
  document.getElementById('stat-sla').textContent = k.slaPct.toFixed(1) + '%';
  document.getElementById('stat-crit').textContent = k.criticosSinAsignar;
  document.getElementById('stat-backlog').textContent = k.backlog7d;
}

// ============== KPIs + SPARKLINES ==============
function renderKPIs(k, d, series) {
  // KPI 1: Tickets totales
  document.getElementById('kpi-totales').textContent = k.total.toLocaleString('es-CL');
  const d1 = document.getElementById('kpi-totales-delta');
  d1.innerHTML = deltaHtml(d.levantadas, '%', 'inverse');

  // KPI 2: Incidencias (filtradas por tipo)
  document.getElementById('kpi-incidencias').textContent = k.incidenciasLevantadas.toLocaleString('es-CL');
  document.getElementById('kpi-incidencias-nuevas').textContent = k.incidenciasNuevas7d;
  const d2 = document.getElementById('kpi-incidencias-delta');
  d2.innerHTML = deltaHtml(d.incidencias, '%', 'inverse');

  // KPI 3: % SLA
  document.getElementById('kpi-sla').innerHTML = k.slaPct.toFixed(1) + '<span class="text-base font-medium text-slate-500">%</span>';
  const d3 = document.getElementById('kpi-sla-delta');
  d3.innerHTML = deltaHtml(d.sla, ' pp', 'direct');

  // KPI 4: Backlog Incidencias
  document.getElementById('kpi-backlog').textContent = k.incidenciasAbiertas.toLocaleString('es-CL');
  const d4 = document.getElementById('kpi-backlog-delta');
  d4.innerHTML = deltaHtml(d.backlog, '%', 'inverse');

  // Sparklines (4)
  drawSpark('spark-totales', series.levantadas, '#4f46e5');
  drawSpark('spark-incidencias', series.incidencias, '#dc2626');
  drawSpark('spark-sla', series.sla, '#10b981');
  drawSpark('spark-backlog', series.backlog, '#ef4444');
}

// deltaHtml(value, unit, direction):
//   direction = 'direct'  → valor positivo es verde (ej. SLA subiendo)
//   direction = 'inverse' → valor positivo es rojo (ej. más tickets/incidencias/backlog)
function deltaHtml(value, unit, direction) {
  if (value === undefined || isNaN(value)) return '—';
  const arrow = value >= 0 ? '▲' : '▼';
  const good = direction === 'direct' ? value >= 0 : value <= 0;
  const cls = good ? 'text-emerald-600' : 'text-red-600';
  return `<span class="${cls}">${arrow} ${Math.abs(value).toFixed(1)}${unit}</span>`;
}

function drawSpark(id, data, color) {
  const svg = document.getElementById(id);
  if (!svg) return;
  const w = 100, h = 30;
  if (!data || data.length === 0) return;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  }).join(' ');
  svg.innerHTML = `
    <defs>
      <linearGradient id="grad-${id}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <polygon points="0,${h} ${points} ${w},${h}" fill="url(#grad-${id})"/>
    <polyline points="${points}" stroke="${color}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    <circle cx="${data.length - 1}" cy="${(h - ((data[data.length - 1] - min) / range) * (h - 4) - 2)}" r="2" fill="${color}"/>
  `;
}

// ============== ACTIVIDAD DIARIA ==============
function renderCharts(ds) {
  const svg = document.getElementById('chart-activity');
  if (!svg) return;
  const W = 600, H = 180, padding = { t: 20, r: 20, b: 30, l: 30 };
  const serie = ds.serie;
  const max = Math.max(...serie.map(s => Math.max(s.levantadas, s.cerradas)), 1);

  // Eje Y
  let yGrid = '';
  for (let i = 0; i <= 4; i++) {
    const y = padding.t + (H - padding.t - padding.b) * (i / 4);
    const val = Math.round(max * (1 - i / 4));
    yGrid += `<line x1="${padding.l}" x2="${W - padding.r}" y1="${y}" y2="${y}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="${i === 0 ? '' : '3 3'}"/>`;
    yGrid += `<text x="${padding.l - 5}" y="${y + 3}" text-anchor="end" font-size="10" fill="#94a3b8">${val}</text>`;
  }

  // Barras + líneas
  const innerW = W - padding.l - padding.r;
  const innerH = H - padding.t - padding.b;
  const slot = innerW / serie.length;
  const barW = Math.max(2, slot * 0.35);
  let bars = '', lines = '', media7 = [], gridText = '';

  // Calcular media móvil 7d de cerradas
  for (let i = 0; i < serie.length; i++) {
    const ini = Math.max(0, i - 6);
    const slice = serie.slice(ini, i + 1).map(s => s.cerradas);
    media7.push(slice.reduce((a, b) => a + b, 0) / slice.length);
  }

  serie.forEach((s, i) => {
    const x = padding.l + slot * i + slot / 2;
    const hL = (s.levantadas / max) * innerH;
    const hC = (s.cerradas / max) * innerH;
    bars += `<rect x="${x - barW}" y="${padding.t + innerH - hL}" width="${barW}" height="${hL}" fill="#4f46e5" rx="1"><title>${s.fecha}: ${s.levantadas} levantadas</title></rect>`;
    bars += `<rect x="${x}" y="${padding.t + innerH - hC}" width="${barW}" height="${hC}" fill="#10b981" rx="1"><title>${s.fecha}: ${s.cerradas} cerradas</title></rect>`;
    if (i === serie.length - 1 || i === Math.floor(serie.length / 2) || i === 0) {
      gridText += `<text x="${x}" y="${H - 10}" text-anchor="middle" font-size="9" fill="#94a3b8">${s.fecha.slice(5)}</text>`;
    }
  });

  // Línea media móvil
  const pointsM = media7.map((v, i) => {
    const x = padding.l + slot * i + slot / 2;
    const y = padding.t + innerH - (v / max) * innerH;
    return `${x},${y}`;
  }).join(' ');
  lines = `<polyline points="${pointsM}" stroke="#f59e0b" stroke-width="2" fill="none" stroke-linecap="round" stroke-dasharray="4 2" opacity="0.85"/>`;

  svg.innerHTML = yGrid + bars + lines + gridText;
}

// ============== FUNNEL ==============
function renderFunnel(funnel) {
  const cont = document.getElementById('funnel-container');
  if (!cont) return;
  const max = Math.max(...funnel.map(f => f.total), 1);
  cont.innerHTML = funnel.map(f => {
    const pct = (f.total / max) * 100;
    return `
      <div class="funnel-item" data-estado="${f.estado}">
        <div class="funnel-label" style="color:${f.color}">${f.estado}</div>
        <div class="funnel-bar"><div class="funnel-fill" style="width:${pct}%; background:${f.color}"></div></div>
        <div class="funnel-pct">${f.total}</div>
      </div>`;
  }).join('');
  cont.querySelectorAll('.funnel-item').forEach(item => {
    item.addEventListener('click', () => {
      const est = item.dataset.estado;
      document.getElementById('tickets-filter').value = est;
      renderTickets();
      document.getElementById('tickets-filter').scrollIntoView({ behavior: 'smooth', block: 'center' });
      toast(`Filtrando por estado: ${est}`);
    });
  });
}

// ============== DISTRIBUCIÓN POR ESTADO ==============
function renderDistEstado(distEstado) {
  const cont = document.getElementById('dist-estado-container');
  if (!cont) return;
  if (!distEstado || distEstado.length === 0) {
    cont.innerHTML = '<p class="text-xs text-slate-400 py-4 text-center">Sin datos</p>';
    return;
  }
  const max = Math.max(...distEstado.map(d => d.total), 1);
  cont.innerHTML = distEstado.map(d => {
    const pct = (d.total / max) * 100;
    return `
      <div>
        <div class="flex items-center justify-between text-xs mb-1">
          <span class="text-slate-700 font-medium inline-flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-sm shrink-0" style="background:${d.color}"></span>
            ${d.nombre}
          </span>
          <span class="font-bold text-slate-800">${d.total}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${pct}%; background:${d.color}"></div>
        </div>
      </div>`;
  }).join('');
}

// ============== DISTRIBUCIÓN POR PRIORIDAD ==============
function renderDistPrioridad(distPrioridad) {
  const cont = document.getElementById('dist-prioridad-container');
  if (!cont) return;
  const total = distPrioridad.reduce((acc, p) => acc + p.total, 0) || 1;
  cont.innerHTML = distPrioridad.map(p => {
    const pct = (p.total / total) * 100;
    return `
      <div>
        <div class="flex items-center justify-between text-xs mb-1">
          <span class="px-2 py-0.5 rounded text-[10px] font-semibold prio-${p.nombre}">${p.nombre}</span>
          <span class="font-bold text-slate-800">${p.total} <span class="text-slate-400 font-normal">(${pct.toFixed(0)}%)</span></span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${pct}%; background:${p.color}"></div>
        </div>
      </div>`;
  }).join('');
}

// ============== RIESGO (próximos a vencer SLA) ==============
function renderRiesgo(abiertas, horasLimite) {
  const ahora = new Date();
  const lista = abiertas
    .filter(t => t.tipo === 'Incidencia')
    .map(t => ({ ...t, horasVence: (t.vence - ahora) / (1000 * 60 * 60) }))
    .filter(t => t.horasVence <= horasLimite && t.horasVence >= -48)
    .sort((a, b) => a.horasVence - b.horasVence);

  const tbody = document.getElementById('riesgo-tbody');
  if (!tbody) return;
  if (!lista.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center py-6 text-slate-400">Sin tickets próximos a vencer SLA · :)</td></tr>';
    return;
  }
  tbody.innerHTML = lista.slice(0, 20).map(t => {
    const hrs = t.horasVence;
    const statusColor = hrs < 0 ? 'text-red-600 font-bold' : hrs < 12 ? 'text-orange-600 font-semibold' : hrs < 48 ? 'text-amber-600' : 'text-slate-600';
    const venceTxt = hrs < 0 ? `vencido hace ${Math.abs(hrs).toFixed(0)}h` : `en ${hrs.toFixed(0)}h`;
    return `
      <tr class="riesgo-row hover:bg-slate-50 cursor-pointer" data-id="${t.id}">
        <td class="py-2 px-2 font-mono text-slate-600">${t.codigo}</td>
        <td class="max-w-[180px] truncate" title="${t.titulo}">${t.titulo}</td>
        <td><span class="px-1.5 py-0.5 rounded text-[10px] font-semibold prio-${t.prioridad}">${t.prioridad}</span></td>
        <td><span class="status-dot" style="background:${(ESTADOS.find(e => e.nombre === t.estado) || {}).color || '#94a3b8'}"></span>${t.estado}</td>
        <td class="text-right ${statusColor}">${venceTxt}</td>
        <td>${t.asignado || '<em class="text-slate-400">sin asignar</em>'}</td>
      </tr>`;
  }).join('');
  tbody.querySelectorAll('.riesgo-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = parseInt(row.dataset.id);
      const t = estado.dataset.tickets.find(x => x.id === id);
      if (t) abrirModal(t);
    });
  });
}

// ============== CUENTA DE RESULTADO (pivot Incidencias × QA) ==============
function renderCuentaResultado(cuentaResultado) {
  const cont = document.getElementById('cuenta-resultado-container');
  if (!cont) return;
  if (!cuentaResultado || cuentaResultado.length === 0) {
    cont.innerHTML = '<p class="text-xs text-slate-400 py-6 text-center">Sin incidencias cerradas con resultado de QA en el periodo</p>';
    return;
  }

  const RESULTADOS_ORDER = ['Aprobado', 'Rechazado', 'Pendiente', 'En revisión'];
  const RESULTADO_COLORS = { 'Aprobado': '#10b981', 'Rechazado': '#ef4444', 'Pendiente': '#eab308', 'En revisión': '#3b82f6' };
  const maxFila = Math.max(...cuentaResultado.map(f => f.total), 1);

  cont.innerHTML = `
    <table class="w-full text-xs">
      <thead class="text-[10px] uppercase text-slate-500 border-b border-slate-200">
        <tr>
          <th class="text-left py-2 px-3 font-semibold">Módulo</th>
          ${RESULTADOS_ORDER.map(r => `<th class="text-right py-2 px-2 font-semibold">${r}</th>`).join('')}
          <th class="text-right py-2 px-3 font-semibold border-l border-slate-200">Total</th>
          <th class="text-left py-2 px-3 font-semibold w-1/3">Distribución</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${cuentaResultado.map(f => {
          const widthPct = (f.total / maxFila) * 100;
          const segmentos = RESULTADOS_ORDER.map(r => {
            const val = f[r] || 0;
            const segPct = f.total ? (val / f.total) * 100 : 0;
            return `<div title="${r}: ${val}" style="width:${segPct}%; background:${RESULTADO_COLORS[r]}"></div>`;
          }).join('');
          return `
            <tr class="hover:bg-slate-50">
              <td class="py-2 px-3 font-medium text-slate-800">${f.modulo}</td>
              ${RESULTADOS_ORDER.map(r => `<td class="py-1.5 px-2 text-right text-slate-700 font-mono">${f[r] || 0}</td>`).join('')}
              <td class="py-2 px-3 text-right font-bold text-slate-800 border-l border-slate-100">${f.total}</td>
              <td class="py-1.5 px-3">
                <div class="flex w-full h-3 rounded overflow-hidden bg-slate-100" style="width:${widthPct}%; min-width:60px">
                  ${segmentos}
                </div>
              </td>
            </tr>`;
        }).join('')}
      </tbody>
      <tfoot class="border-t-2 border-slate-200 bg-slate-50/50">
        ${(() => {
          const totales = { total: 0 };
          RESULTADOS_ORDER.forEach(r => totales[r] = 0);
          cuentaResultado.forEach(f => {
            totales.total += f.total;
            RESULTADOS_ORDER.forEach(r => totales[r] += (f[r] || 0));
          });
          return `
            <tr class="font-bold text-slate-800">
              <td class="py-2 px-3">TOTAL</td>
              ${RESULTADOS_ORDER.map(r => `<td class="py-2 px-2 text-right">${totales[r]}</td>`).join('')}
              <td class="py-2 px-3 text-right border-l border-slate-200">${totales.total}</td>
              <td class="py-2 px-3 text-[10px] text-slate-500 font-normal">
                ${totales.total ? ((totales['Aprobado'] / totales.total) * 100).toFixed(1) + '% aprobado' : '—'}
              </td>
            </tr>`;
        })()}
      </tfoot>
    </table>
  `;
}

// ============== TABLA DE TICKETS ==============
function renderTickets() {
  const ds = estado.dataset;
  if (!ds) return;
  const filter = (document.getElementById('tickets-filter').value || '').toLowerCase();
  const prio = document.getElementById('tickets-prio').value;

  const filtrados = ds.tickets
    .filter(t => (!filter || t.codigo.toLowerCase().includes(filter) || t.titulo.toLowerCase().includes(filter)))
    .filter(t => (!prio || t.prioridad === prio))
    .sort((a, b) => b.creado - a.creado)
    .slice(0, 30);

  const tbody = document.getElementById('tickets-tbody');
  tbody.innerHTML = filtrados.map(t => {
    const estadoColor = (ESTADOS.find(e => e.nombre === t.estado) || {}).color || '#94a3b8';
    const slaTxt = t.slaCumplido === 1 ? '<span class="text-emerald-600 font-semibold">Cumple</span>' :
                   t.slaCumplido === 0 ? '<span class="text-red-600 font-semibold">Vencido</span>' :
                   '<span class="text-slate-500">Pendiente</span>';
    return `
      <tr class="ticket-row" data-id="${t.id}">
        <td class="py-2 px-3 font-mono text-slate-700">${t.codigo}</td>
        <td class="max-w-[260px] truncate" title="${t.titulo}">${t.titulo}</td>
        <td><span class="status-dot" style="background:${estadoColor}"></span>${t.estado}</td>
        <td><span class="px-1.5 py-0.5 rounded text-[10px] font-semibold prio-${t.prioridad}">${t.prioridad}</span></td>
        <td>${t.asignado || '<em class="text-slate-400">—</em>'}</td>
        <td>${t.solicitante}</td>
        <td>${slaTxt}</td>
        <td class="text-slate-500">${t.creado.toLocaleString('es-CL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</td>
      </tr>`;
  }).join('');
  document.getElementById('tickets-count').textContent = `Mostrando ${filtrados.length} de ${ds.tickets.length} tickets`;

  tbody.querySelectorAll('.ticket-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = parseInt(row.dataset.id);
      const t = ds.tickets.find(x => x.id === id);
      if (t) abrirModal(t);
    });
  });
}

// ============== MODAL DETALLE ==============
function abrirModal(t) {
  document.getElementById('modal-codigo').textContent = t.codigo;
  document.getElementById('modal-titulo').textContent = t.titulo;
  document.getElementById('modal-estado').innerHTML = `<span class="status-dot" style="background:${(ESTADOS.find(e => e.nombre === t.estado) || {}).color || '#94a3b8'}"></span>${t.estado}`;
  document.getElementById('modal-prioridad').innerHTML = `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold prio-${t.prioridad}">${t.prioridad}</span>`;
  document.getElementById('modal-asignado').textContent = t.asignado || 'Sin asignar';
  document.getElementById('modal-solicitante').textContent = t.solicitante;
  const venceTxt = t.vence.toLocaleString('es-CL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  document.getElementById('modal-vence').innerHTML = `${venceTxt} <span class="text-[10px] text-slate-400 block">(${formatHorasRestantes(t.vence)})</span>`;
  document.getElementById('modal-creado').textContent = t.creado.toLocaleString('es-CL');
  document.getElementById('modal-desc').textContent = t.descripcion;
  document.getElementById('modal-etiquetas').innerHTML = t.etiquetas.map(e =>
    `<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold" style="background:${e.color}1a; color:${e.color}">${e.nombre}</span>`
  ).join('');
  document.getElementById('modal-backdrop').classList.remove('hidden');
}

function formatHorasRestantes(vence) {
  const diff = (vence - new Date()) / (1000 * 60 * 60);
  if (diff < 0) return `vencido hace ${Math.abs(diff).toFixed(1)}h`;
  return `en ${diff.toFixed(1)}h`;
}