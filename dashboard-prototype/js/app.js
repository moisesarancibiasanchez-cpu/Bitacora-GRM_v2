// ============================================================
// app.js — Lógica de renderizado e interactividad del dashboard
// ============================================================

let estado = { dias: 30, dataset: null, autoTimer: null, theme: 'light' };

// ============== INIT ==============
window.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  cargar();
  renderKanbanDemo();
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
      renderAging(estado.dataset.aging);
      renderCarga(estado.dataset.carga);
      renderTickets();
      renderKanbanDemo();
    }
  });

  // Export CSV
  document.getElementById('btn-export').addEventListener('click', () => {
    if (!estado.dataset) return;
    const rows = [['codigo', 'titulo', 'estado', 'prioridad', 'asignado', 'solicitante', 'canal', 'sla_cumplido', 'creado', 'cerrado']];
    estado.dataset.tickets.forEach(t => {
      rows.push([
        t.codigo, `"${t.titulo.replace(/"/g, '""')}"`, t.estado, t.prioridad,
        t.asignado || '', t.solicitante, t.canal, t.slaCumplido,
        t.creado.toISOString(), t.cerrado ? t.cerrado.toISOString() : '',
      ]);
    });
    const csv = rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `incidencias_${estado.dias}d_${new Date().toISOString().slice(0,10)}.csv`;
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
  renderAging(ds.aging);
  renderRiesgo(ds.tickets.filter(t => !t.cerrado), 72);
  renderCarga(ds.carga);
  renderOrigen(ds.origen);
  renderCierre(ds.cierre);
  renderTickets();
  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('es-CL');
}

// ============== STATS BAR ==============
function renderStatsBar(k, deltas) {
  document.getElementById('stat-total').textContent = k.total.toLocaleString('es-CL');
  document.getElementById('stat-nuevas').textContent = k.nuevas7d.toLocaleString('es-CL');
  document.getElementById('stat-abiertas').textContent = k.abiertas.toLocaleString('es-CL');
  document.getElementById('stat-sla').textContent = k.slaPct.toFixed(1) + '%';
  document.getElementById('stat-crit').textContent = k.criticosSinAsignar;
  document.getElementById('stat-backlog').textContent = k.backlog7d;
}

// ============== KPIs + SPARKLINES ==============
function renderKPIs(k, d, series) {
  document.getElementById('kpi-levantadas').innerHTML = k.levantadas.toLocaleString('es-CL');
  document.getElementById('kpi-tme').innerHTML = k.tme.toFixed(1) + '<span class="text-base font-medium text-slate-500">h</span>';
  document.getElementById('kpi-sla').innerHTML = k.slaPct.toFixed(1) + '<span class="text-base font-medium text-slate-500">%</span>';
  document.getElementById('kpi-backlog').textContent = k.backlog.toLocaleString('es-CL');

  const fmtDelta = (v, unit) => {
    const s = v >= 0 ? '+' : '';
    return s + v.toFixed(1) + unit;
  };
  const arrow = (v) => v >= 0 ? '▲' : '▼';

  const d1 = document.getElementById('kpi-levantadas-delta');
  d1.innerHTML = `<span class="${d.levantadas >= 0 ? 'text-emerald-600' : 'text-red-600'}">${arrow(d.levantadas)} ${Math.abs(d.levantadas).toFixed(1)}%</span>`;
  const d2 = document.getElementById('kpi-tme-delta');
  d2.innerHTML = `<span class="${d.tme <= 0 ? 'text-emerald-600' : 'text-red-600'}">${arrow(d.tme)} ${Math.abs(d.tme).toFixed(1)}%</span>`;
  const d3 = document.getElementById('kpi-sla-delta');
  d3.innerHTML = `<span class="${d.sla >= 0 ? 'text-emerald-600' : 'text-red-600'}">${arrow(d.sla)} ${Math.abs(d.sla).toFixed(1)} pp</span>`;
  const d4 = document.getElementById('kpi-backlog-delta');
  d4.innerHTML = `<span class="${d.backlog <= 0 ? 'text-emerald-600' : 'text-red-600'}">${arrow(d.backlog)} ${Math.abs(d.backlog).toFixed(1)}%</span>`;

  // Sparklines
  drawSpark('spark-levantadas', series.levantadas, '#4f46e5');
  drawSpark('spark-tme', series.tme, '#f59e0b');
  drawSpark('spark-sla', series.sla, '#10b981');
  drawSpark('spark-backlog', series.backlog, '#ef4444');
}

function drawSpark(id, data, color) {
  const svg = document.getElementById(id);
  if (!svg) return;
  const w = 100, h = 30;
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

// ============== AGING ==============
function renderAging(aging) {
  const cont = document.getElementById('aging-container');
  const max = Math.max(...aging.map(a => a.count), 1);
  cont.innerHTML = aging.map(a => {
    const pct = (a.count / max) * 100;
    return `
      <div>
        <div class="flex items-center justify-between text-xs mb-1">
          <span class="text-slate-600">${a.rango}</span>
          <span class="font-bold text-slate-800">${a.count}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${pct}%; background:${a.color}"></div>
        </div>
      </div>`;
  }).join('');
}

// ============== RIESGO ==============
function renderRiesgo(abiertas, horasLimite) {
  const ahora = new Date();
  const lista = abiertas
    .map(t => ({ ...t, horasVence: (t.vence - ahora) / (1000 * 60 * 60) }))
    .filter(t => t.horasVence <= horasLimite && t.horasVence >= -48)
    .sort((a, b) => a.horasVence - b.horasVence);

  const tbody = document.getElementById('riesgo-tbody');
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

// ============== CARGA POR AGENTE ==============
function renderCarga(carga) {
  const cont = document.getElementById('carga-container');
  const max = Math.max(...carga.map(c => c.total), 1);
  cont.innerHTML = carga.map(c => {
    const pct = (c.total / max) * 100;
    const color = pct > 75 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#4f46e5';
    return `
      <div>
        <div class="flex items-center justify-between text-xs mb-1">
          <span class="text-slate-700 font-medium">${c.nombre}</span>
          <span class="font-bold text-slate-800">${c.total}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${pct}%; background:${color}"></div>
        </div>
      </div>`;
  }).join('');
}

// ============== DONUT ORIGEN ==============
function renderOrigen(origen) {
  const total = origen.reduce((acc, o) => acc + o.total, 0);
  const svg = document.getElementById('donut-origen');
  const legend = document.getElementById('origen-legend');
  if (!total) {
    svg.innerHTML = '<text x="60" y="65" text-anchor="middle" fill="#94a3b8" font-size="11">Sin datos</text>';
    legend.innerHTML = '';
    return;
  }
  let acc = 0;
  const r = 45, cx = 60, cy = 60;
  let slices = '';
  origen.forEach(o => {
    if (!o.total) return;
    const start = acc / total;
    acc += o.total;
    const end = acc / total;
    const a1 = start * Math.PI * 2 - Math.PI / 2;
    const a2 = end * Math.PI * 2 - Math.PI / 2;
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
    const big = (end - start) > 0.5 ? 1 : 0;
    slices += `<path d="M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${big} 1 ${x2},${y2} Z" fill="${o.color}" class="donut-slice"><title>${o.nombre}: ${o.total}</title></path>`;
  });
  // Hueco central
  slices += `<circle cx="${cx}" cy="${cy}" r="28" fill="white" class="dark:fill-slate-800"/>`;
  slices += `<text x="${cx}" y="${cy - 3}" text-anchor="middle" font-size="11" fill="#64748b" font-weight="600">Total</text>`;
  slices += `<text x="${cx}" y="${cy + 12}" text-anchor="middle" font-size="14" fill="#1e293b" font-weight="700">${total}</text>`;
  svg.innerHTML = slices;

  legend.innerHTML = origen.map(o => `
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-1.5 min-w-0">
        <span class="w-2 h-2 rounded-sm shrink-0" style="background:${o.color}"></span>
        <span class="text-slate-700 truncate">${o.nombre}</span>
      </div>
      <span class="font-semibold text-slate-800">${o.total} <span class="text-slate-400 font-normal">(${(o.total / total * 100).toFixed(0)}%)</span></span>
    </div>
  `).join('');
}

// ============== DONUT CIERRE ==============
function renderCierre(cierre) {
  // Re-utiliza renderOrigen pero con paleta
  renderOrigen(cierre);
  // Personalizar el título
  document.querySelector('section:has(#donut-cierre) h3, .lg\\:col-span-2 ~ div h3')?.remove?.();
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

// ============== MINI KANBAN DEMO ==============
function renderKanbanDemo() {
  if (!estado.dataset) return;
  // 6 tickets ficticios para la demo
  const demo = estado.dataset.tickets.slice(0, 9);
  const cols = document.querySelectorAll('.kanban-col');
  cols.forEach(col => {
    col.querySelector('.kanban-list').innerHTML = '';
  });
  demo.forEach((t, i) => {
    const targetEstado = i < 3 ? 'BackLog' : i < 6 ? 'En desarrollo' : 'QA';
    const col = Array.from(cols).find(c => c.dataset.estado === targetEstado);
    if (col) {
      const card = document.createElement('div');
      card.className = 'kanban-card';
      card.draggable = true;
      card.dataset.id = t.id;
      card.dataset.fromEstado = t.estado;
      card.innerHTML = `
        <div class="font-mono text-[10px] text-slate-400">${t.codigo}</div>
        <div class="truncate">${t.titulo}</div>
        <div class="flex items-center justify-between mt-1">
          <span class="px-1 py-0 rounded text-[9px] prio-${t.prioridad}" style="font-weight:600">${t.prioridad[0]}</span>
          <span class="text-[9px] text-slate-400">${(t.asignado || 'SA').split(' ').map(s => s[0]).join('')}</span>
        </div>`;
      attachDrag(card);
      col.querySelector('.kanban-list').appendChild(card);
    }
  });

  // Dragover styling
  cols.forEach(col => {
    col.addEventListener('dragover', (e) => {
      e.preventDefault();
      col.classList.add('drag-over');
    });
    col.addEventListener('dragleave', () => col.classList.remove('drag-over'));
    col.addEventListener('drop', (e) => {
      e.preventDefault();
      col.classList.remove('drag-over');
      const dragging = document.querySelector('.kanban-card.dragging');
      if (dragging) {
        col.querySelector('.kanban-list').appendChild(dragging);
        toast(`Ticket ${dragging.querySelector('.font-mono').textContent} → ${col.dataset.estado} (simulado)`);
        // Animación
        dragging.style.transform = 'scale(1.02)';
        setTimeout(() => dragging.style.transform = '', 200);
      }
    });
  });
}

function attachDrag(card) {
  card.addEventListener('dragstart', (e) => {
    card.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  card.addEventListener('dragend', () => card.classList.remove('dragging'));
}
