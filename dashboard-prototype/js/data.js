// ============================================================
// data.js — Generador de datos mock realistas para el prototipo
// ============================================================

const ESTADOS = [
  { nombre: 'BackLog', color: '#64748b', orden: 1, es_final: false },
  { nombre: 'En desarrollo', color: '#3b82f6', orden: 2, es_final: false },
  { nombre: 'Entregado', color: '#f59e0b', orden: 3, es_final: false },
  { nombre: 'UAT-QA', color: '#6366f1', orden: 4, es_final: false },
  { nombre: 'APROBADO QA', color: '#10b981', orden: 5, es_final: false },
  { nombre: 'Despliegue PROD', color: '#6366f1', orden: 6, es_final: false },
  { nombre: 'produccion ok', color: '#475569', orden: 7, es_final: true },
  { nombre: 'DESESTIMADA', color: '#9ca3af', orden: 8, es_final: true },
  { nombre: 'Cancelado', color: '#dc2626', orden: 9, es_final: true },
];

const PRIORIDADES = ['CRITICA', 'ALTA', 'MEDIA', 'BAJA'];
const PRIO_DIST = [0.10, 0.25, 0.45, 0.20];

const AGENTES = [
  'Juan Pérez', 'María López', 'Carlos Ruiz', 'Ana Soto', 'Roberto Díaz',
  'Lucía Vargas', 'Pedro Ramírez', 'Sofía Castro', 'Diego Torres',
];

const CANALES = [
  { nombre: 'Portal Web', color: '#6366f1' },
  { nombre: 'Email', color: '#10b981' },
  { nombre: 'Teléfono', color: '#f59e0b' },
  { nombre: 'API', color: '#ec4899' },
  { nombre: 'Monitoreo', color: '#ef4444' },
];

const CANAL_DIST = [0.32, 0.28, 0.18, 0.10, 0.12];

const ETIQUETAS = [
  { nombre: 'Login', color: '#3b82f6' },
  { nombre: 'Rendimiento', color: '#f59e0b' },
  { nombre: 'Bug UI', color: '#ef4444' },
  { nombre: 'Datos', color: '#8b5cf6' },
  { nombre: 'Integración', color: '#10b981' },
  { nombre: 'Seguridad', color: '#dc2626' },
  { nombre: 'Reportes', color: '#06b6d4' },
];

const MODULOS = ['Autenticación', 'Inventario', 'Facturación', 'Reportes', 'Notificaciones', 'Catálogo', 'API pública'];
const VERBOS = ['Error en', 'Caída de', 'Latencia alta en', 'Login fallido en', 'Timeout en', 'Sincronización rota en', 'Visualización rota en', 'Endpoint caído en'];

// ====================== RNG con semilla ======================
function seededRNG(seed) {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

function pick(rng, arr) { return arr[Math.floor(rng() * arr.length)]; }
function pickW(rng, arr, weights) {
  const r = rng();
  let acc = 0;
  for (let i = 0; i < arr.length; i++) {
    acc += weights[i];
    if (r <= acc) return arr[i];
  }
  return arr[arr.length - 1];
}
function randInt(rng, min, max) { return Math.floor(rng() * (max - min + 1)) + min; }

// ====================== Generador principal ======================
function generarDataset(dias = 30, seed = Date.now()) {
  const rng = seededRNG(seed + dias * 13);
  const total = randInt(rng, 240, 520); // tickets creados en el periodo
  const tickets = [];
  const ahora = new Date();

  for (let i = 0; i < total; i++) {
    const diasAtras = Math.floor(rng() * dias);
    const creado = new Date(ahora);
    creado.setDate(creado.getDate() - diasAtras);
    creado.setHours(randInt(rng, 8, 19), randInt(rng, 0, 59));

    const prioridad = pickW(rng, PRIORIDADES, PRIO_DIST);
    const canal = pickW(rng, CANALES.map(c => c.nombre), CANAL_DIST);
    const modulo = pick(rng, MODULOS);
    const verbo = pick(rng, VERBOS);

    // 60% cerrados, 40% abiertos
    const cerrado = rng() < 0.62;
    let estado;
    let fechaCierre = null;
    let tme = null;
    if (cerrado) {
      estado = pickW(rng, ['produccion ok', 'DESESTIMADA', 'Cancelado', 'produccion ok', 'produccion ok'], [0.55, 0.18, 0.10, 0.55, 0.55]).normalize();
      // Simplificación: estado final
      const r = rng();
      if (r < 0.55) estado = 'produccion ok';
      else if (r < 0.73) estado = 'DESESTIMADA';
      else if (r < 0.83) estado = 'Cancelado';
      else estado = 'BackLog'; // realmente es final pero con nombre BackLog (poco común)

      const horasResol = randInt(rng, 2, 240);
      fechaCierre = new Date(creado.getTime() + horasResol * 3600 * 1000);
      tme = horasResol;
    } else {
      // estado intermedio con peso mayor en "En desarrollo"
      const r = rng();
      if (r < 0.35) estado = 'En desarrollo';
      else if (r < 0.65) estado = 'BackLog';
      else if (r < 0.80) estado = 'UAT-QA';
      else if (r < 0.90) estado = 'Entregado';
      else if (r < 0.96) estado = 'APROBADO QA';
      else estado = 'Despliegue PROD';
    }

    // Asignación: críticos siempre asignados; resto 30% sin asignar
    const sinAsignar = prioridad !== 'CRITICA' && rng() < 0.30;
    const asignado = sinAsignar ? null : pick(rng, AGENTES);

    // SLA: cumple si cerrado y tme <= prioridadSLA
    const prioridadSLA = { CRITICA: 8, ALTA: 24, MEDIA: 72, BAJA: 168 }[prioridad];
    let slaCumplido;
    if (cerrado) {
      slaCumplido = tme <= prioridadSLA ? 1 : 0;
    } else {
      // pendiente o vencido según tiempo desde creación
      const horasTranscurridas = (ahora - creado) / 3600000;
      if (horasTranscurridas > prioridadSLA) slaCumplido = 0;
      else slaCumplido = -1; // pendiente
    }

    // Fecha vencimiento SLA
    const vence = new Date(creado.getTime() + prioridadSLA * 3600 * 1000);

    // Etiquetas (1-3)
    const numEtiquetas = randInt(rng, 1, 3);
    const etiquetasSet = new Set();
    while (etiquetasSet.size < numEtiquetas) {
      etiquetasSet.add(pick(rng, ETIQUETAS));
    }
    const etiquetas = Array.from(etiquetasSet);

    tickets.push({
      id: i + 1,
      codigo: `INC-${String(1000 + i).padStart(4, '0')}`,
      titulo: `${verbo} ${modulo}`,
      descripcion: `Incidencia detectada en el módulo de ${modulo.toLowerCase()} durante pruebas funcionales. Se requiere investigación y resolución según SLA de prioridad ${prioridad}.`,
      estado,
      prioridad,
      asignado,
      solicitante: pick(rng, ['Cliente Norte', 'Cliente Sur', 'Operaciones', 'Comercial', 'Soporte', 'Auditoría']),
      canal,
      etiquetas,
      creado,
      cerrado: fechaCierre,
      vence,
      tme,
      slaCumplido,
      modulo,
    });
  }
  return tickets;
}

// ====================== Agregaciones ======================
function agregar(tickets, dias) {
  const cerradas = tickets.filter(t => t.cerrado);
  const abiertas = tickets.filter(t => !t.cerrado);

  // KPIs
  const tmePromedio = cerradas.length
    ? cerradas.reduce((acc, t) => acc + t.tme, 0) / cerradas.length
    : 0;
  const slaTotal = tickets.filter(t => t.slaCumplido === 0 || t.slaCumplido === 1);
  const slaCumplidos = slaTotal.filter(t => t.slaCumplido === 1).length;
  const slaPct = slaTotal.length ? (slaCumplidos / slaTotal.length) * 100 : 0;
  const criticosSinAsignar = tickets.filter(t => t.prioridad === 'CRITICA' && !t.asignado && !t.cerrado).length;
  const nuevas7d = tickets.filter(t => {
    const diff = (new Date() - t.creado) / (1000 * 60 * 60 * 24);
    return diff <= 7;
  }).length;
  const backlog = abiertas.length;

  // Actividad diaria
  const serie = [];
  for (let i = dias - 1; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    d.setHours(0, 0, 0, 0);
    const dFin = new Date(d);
    dFin.setHours(23, 59, 59, 999);
    const levantadas = tickets.filter(t => t.creado >= d && t.creado <= dFin).length;
    const cerradas = tickets.filter(t => t.cerrado && t.cerrado >= d && t.cerrado <= dFin).length;
    serie.push({ fecha: d.toISOString().slice(0, 10), levantadas, cerradas });
  }

  // Funnel
  const funnel = ESTADOS
    .filter(e => !e.es_final)
    .sort((a, b) => a.orden - b.orden)
    .map(estado => ({
      estado: estado.nombre,
      color: estado.color,
      total: abiertas.filter(t => t.estado === estado.nombre).length +
             cerradas.filter(t => t.estado === estado.nombre).length,
    }));

  // Aging del backlog
  const ahora = new Date();
  const aging = [
    { rango: '0-2 días', count: 0, color: '#10b981' },
    { rango: '3-7 días', count: 0, color: '#84cc16' },
    { rango: '8-15 días', count: 0, color: '#eab308' },
    { rango: '16-30 días', count: 0, color: '#f97316' },
    { rango: '> 30 días', count: 0, color: '#ef4444' },
  ];
  abiertas.forEach(t => {
    const diasApert = (ahora - t.creado) / (1000 * 60 * 60 * 24);
    if (diasApert <= 2) aging[0].count++;
    else if (diasApert <= 7) aging[1].count++;
    else if (diasApert <= 15) aging[2].count++;
    else if (diasApert <= 30) aging[3].count++;
    else aging[4].count++;
  });

  // Próximos a vencer SLA (en las próximas N horas, abiertas)
  function proximasVencer(horas = 72) {
    return abiertas
      .filter(t => {
        const horasVence = (t.vence - ahora) / (1000 * 60 * 60);
        return horasVence >= -12 && horasVence <= horas; // incluye vencidos recientes
      })
      .sort((a, b) => a.vence - b.vence)
      .slice(0, 20);
  }

  // Carga por agente (abiertas + cerradas del periodo)
  const cargaMap = {};
  AGENTES.forEach(a => { cargaMap[a] = 0; });
  tickets.forEach(t => {
    if (t.asignado) cargaMap[t.asignado] = (cargaMap[t.asignado] || 0) + 1;
  });
  const carga = Object.entries(cargaMap)
    .filter(([_, v]) => v > 0)
    .map(([nombre, total]) => ({ nombre, total }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);

  // Por origen
  const origenMap = {};
  CANALES.forEach(c => { origenMap[c.nombre] = 0; });
  tickets.forEach(t => {
    if (origenMap[t.canal] !== undefined) origenMap[t.canal] = (origenMap[t.canal] || 0) + 1;
  });
  const origen = Object.entries(origenMap).map(([nombre, total]) => {
    const c = CANALES.find(x => x.nombre === nombre);
    return { nombre, total, color: c.color };
  });

  // Cierre (distribución final)
  const cierreMap = {};
  ESTADOS.filter(e => e.es_final).forEach(e => { cierreMap[e.nombre] = 0; });
  cerradas.forEach(t => {
    if (cierreMap[t.estado] !== undefined) cierreMap[t.estado] = (cierreMap[t.estado] || 0) + 1;
  });
  const cierre = Object.entries(cierreMap)
    .filter(([_, v]) => v > 0)
    .map(([nombre, total]) => {
      const e = ESTADOS.find(x => x.nombre === nombre);
      return { nombre, total, color: e ? e.color : '#94a3b8' };
    });

  // Series para sparklines (30 puntos)
  function sparkline(field) {
    const pts = [];
    for (let i = dias - 1; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      if (field === 'levantadas') {
        pts.push(serie[serie.length - 1 - i].levantadas);
      } else if (field === 'cerradas') {
        pts.push(serie[serie.length - 1 - i].cerradas);
      } else if (field === 'tme') {
        const dFin = new Date(d); dFin.setHours(23, 59, 59);
        const cs = cerradas.filter(t => t.cerrado <= dFin);
        pts.push(cs.length ? cs.reduce((acc, t) => acc + t.tme, 0) / cs.length : 0);
      } else if (field === 'sla') {
        const dFin = new Date(d); dFin.setHours(23, 59, 59);
        const hasta = tickets.filter(t => t.creado <= dFin && (t.slaCumplido === 0 || t.slaCumplido === 1));
        const cum = hasta.filter(t => t.slaCumplido === 1).length;
        pts.push(hasta.length ? (cum / hasta.length) * 100 : 0);
      } else if (field === 'backlog') {
        const dFin = new Date(d); dFin.setHours(23, 59, 59);
        pts.push(tickets.filter(t => t.creado <= dFin && !t.cerrado).length);
      }
    }
    return pts;
  }

  const nuevas7dPrev = Math.max(1, Math.floor(nuevas7d * (0.7 + Math.random() * 0.5)));
  const tmePrev = Math.max(1, tmePromedio * (0.85 + Math.random() * 0.3));
  const slaPrev = Math.max(0, Math.min(100, slaPct + (Math.random() - 0.5) * 8));
  const backlogPrev = Math.max(1, backlog * (0.85 + Math.random() * 0.3));

  return {
    tickets,
    kpis: {
      total: tickets.length,
      nuevas7d,
      abiertas: abiertas.length,
      criticosSinAsignar,
      backlog,
      backlog7d: aging.slice(1).reduce((acc, a) => acc + a.count, 0),
      tme: tmePromedio,
      slaPct,
      levantadas: tickets.length,
      cerradas: cerradas.length,
    },
    deltas: {
      nuevas: ((nuevas7d - nuevas7dPrev) / nuevas7dPrev * 100),
      tme: ((tme - tmePrev) / tmePrev * 100),
      sla: slaPct - slaPrev,
      backlog: ((backlog - backlogPrev) / backlogPrev * 100),
      levantadas: ((tickets.length - Math.floor(tickets.length * 0.85)) / (tickets.length * 0.85) * 100),
    },
    serie,
    funnel,
    aging,
    carga,
    origen,
    cierre,
    riesgos: proximasVencer(72),
    series: {
      levantadas: sparkline('levantadas'),
      tme: sparkline('tme'),
      sla: sparkline('sla'),
      backlog: sparkline('backlog'),
      cerradas: sparkline('cerradas'),
    },
  };
}

window.__SEED_BASE = 12345;
function getDataset(dias) {
  return agregar(generarDataset(dias, window.__SEED_BASE + dias), dias);
}
