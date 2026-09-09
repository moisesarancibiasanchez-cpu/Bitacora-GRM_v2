/**
 * Lógica de Drag & Drop con SortableJS + HTMX.
 *
 * 1. El usuario arrastra la tarjeta con SortableJS.
 * 2. Al soltarla en otra columna, SortableJS dispara `onEnd`.
 * 3. Antes del PATCH, consultamos `/transicion-info` para saber si
 *    la transición requiere comentario. Si lo requiere, abrimos un mini-modal.
 * 4. Enviamos PATCH al backend con ticket_id, estado_id, orden y (opcional) comentario.
 * 5. HTMX intercepta la respuesta y reemplaza solo el fragmento HTML
 *    de la tarjeta (`outerHTML` swap). Si el backend devuelve 403/422,
 *    SortableJS revierte la posición automáticamente.
 */

(function () {
  'use strict';

  // Cache de info de transición para no consultar dos veces
  const transicionCache = new Map();

  function getCurrentUserId() {
    return window.CURRENT_USER_ID || 1;
  }

  // === Consultar metadata de transición ===
  async function getTransicionInfo(ticketId, estadoId) {
    const key = `${ticketId}:${estadoId}`;
    if (transicionCache.has(key)) return transicionCache.get(key);
    try {
      const resp = await fetch(
        `/api/v1/tickets/${ticketId}/transicion-info/${estadoId}`,
        { headers: { 'X-User-Id': String(getCurrentUserId()) } }
      );
      const data = await resp.json();
      transicionCache.set(key, data);
      return data;
    } catch (_) {
      return { valida: false, motivo: 'Error consultando transición', requiere_comentario: false };
    }
  }

  // === Modal flotante para pedir comentario ===
  function pedirComentario(ticketCodigo, onSubmit, onCancel) {
    // Eliminar modal previo si existe
    const prev = document.getElementById('comentario-modal');
    if (prev) prev.remove();

    const wrap = document.createElement('div');
    wrap.id = 'comentario-modal';
    wrap.className = 'fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50';
    wrap.innerHTML = `
      <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div class="px-5 py-4 border-b border-slate-200">
          <h3 class="text-sm font-semibold text-slate-800">Comentario obligatorio</h3>
          <p class="text-xs text-slate-500 mt-1">El cambio de estado del ticket
            <span class="font-mono text-slate-700">${ticketCodigo}</span>
            requiere un motivo.</p>
        </div>
        <div class="px-5 py-4">
          <textarea id="comentario-modal-text"
                    class="w-full text-sm border border-slate-300 rounded-md p-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    rows="4" placeholder="Describe el motivo del cambio..."></textarea>
        </div>
        <div class="px-5 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-end gap-2">
          <button id="comentario-modal-cancel"
                  class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">
            Cancelar
          </button>
          <button id="comentario-modal-ok"
                  class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
            Confirmar cambio
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(wrap);

    const txt = wrap.querySelector('#comentario-modal-text');
    txt.focus();

    wrap.querySelector('#comentario-modal-cancel').addEventListener('click', () => {
      wrap.remove();
      if (onCancel) onCancel();
    });
    wrap.querySelector('#comentario-modal-ok').addEventListener('click', () => {
      const value = (txt.value || '').trim();
      if (!value) {
        txt.classList.add('ring-2', 'ring-red-400');
        return;
      }
      wrap.remove();
      if (onSubmit) onSubmit(value);
    });
    // Cerrar con ESC
    wrap.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        wrap.remove();
        if (onCancel) onCancel();
      }
    });
  }

  // === Mostrar toast (wrapper de htmx-events) ===
  function toast(msg, type) {
    if (window.showToast) window.showToast(msg, type || 'info');
  }

  // === Extraer mensaje de error desde respuesta HTML o JSON ===
  async function extractError(resp) {
    const ct = resp.headers.get('content-type') || '';
    const txt = await resp.text();
    if (ct.includes('application/json')) {
      try {
        const data = JSON.parse(txt);
        return data.detail || data.message || data.error || txt;
      } catch (_) { return txt; }
    }
    // Buscar patrón <strong>XXX:</strong> mensaje
    const m = txt.match(/<strong>[^<]+:<\/strong>\s*([^<]+)/);
    if (m) return m[1].trim();
    // Si es 401, mensaje claro
    if (resp.status === 401) return 'No autorizado. Inicia sesión o verifica el usuario.';
    if (resp.status === 403) return 'No tienes permisos para esta transición.';
    if (resp.status === 404) return 'Recurso no encontrado.';
    if (resp.status >= 500) return 'Error interno del servidor. Revisa los logs.';
    return txt.substring(0, 200) || 'Error desconocido';
  }

  // === PATCH al backend ===
  async function patchEstado(ticketId, estadoId, orden, comentario) {
    const url = `/api/v1/tickets/${ticketId}/estado`;
    const resp = await fetch(url, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': String(getCurrentUserId()),
      },
      body: JSON.stringify({
        estado_id: parseInt(estadoId, 10),
        orden: orden,
        comentario: comentario || null,
      }),
    });
    return resp;
  }

  // === Manejar drop de SortableJS ===
  function handleDrop(tarjeta, evt) {
    const ticketId = tarjeta.dataset.ticketId;
    const estadoId = evt.to.dataset.estadoId;
    const orden = evt.newIndex;
    const mismaColumna = evt.from === evt.to;
    const mismaPosicion = mismaColumna && evt.oldIndex === evt.newIndex;

    // Guardar posición original por si falla
    const padreOriginal = evt.from;
    const indexOriginal = evt.oldIndex;

    if (mismaPosicion) return;

    // Revertir visualmente mientras procesamos (optimista con rollback)
    const ejecutarCambio = async (comentario) => {
      try {
        const resp = await patchEstado(ticketId, estadoId, orden, comentario);
        if (resp.ok) {
          const nuevoHTML = await resp.text();
          tarjeta.outerHTML = nuevoHTML;
          actualizarContadores();
          toast('Estado actualizado correctamente', 'success');
          // Limpiar cache
          transicionCache.clear();
        } else {
          // Fallo: revertir
          padreOriginal.insertBefore(tarjeta, padreOriginal.children[indexOriginal] || null);
          const mensaje = await extractError(resp);
          toast(mensaje, resp.status === 403 || resp.status === 401 ? 'error' : 'warning');
        }
      } catch (err) {
        padreOriginal.insertBefore(tarjeta, padreOriginal.children[indexOriginal] || null);
        toast('Error de red al cambiar el estado', 'error');
        console.error(err);
      }
    };

    // Consultar si requiere comentario
    getTransicionInfo(ticketId, estadoId).then((info) => {
      if (!info.valida) {
        padreOriginal.insertBefore(tarjeta, padreOriginal.children[indexOriginal] || null);
        toast(info.motivo || 'Transición no válida', 'warning');
        return;
      }
      if (info.requiere_comentario) {
        const codigo = tarjeta.querySelector('.font-mono')?.textContent?.trim() || `#${ticketId}`;
        pedirComentario(codigo,
          (comentario) => ejecutarCambio(comentario),
          () => {
            padreOriginal.insertBefore(tarjeta, padreOriginal.children[indexOriginal] || null);
          }
        );
      } else {
        ejecutarCambio(null);
      }
    });
  }

  // === Inicializar SortableJS en las columnas ===
  // NOTA: Con `delay: 80`, SortableJS dispara onStart cuando el usuario
  // mantiene presionado >80ms (incluso sin mover el mouse). Si marcamos
  // dragged='1' en onStart, eso suprime el click handler para clicks
  // lentos (que es lo más común). Por eso solo marcamos dragged='1'
  // DESPUÉS de verificar que la posición realmente cambió en onEnd.
  function initSortable() {
    const columns = document.querySelectorAll('.kanban-list');
    if (columns.length === 0) return;

    columns.forEach((col) => {
      if (col.dataset.sortableInit) return;
      col.dataset.sortableInit = '1';

      new Sortable(col, {
        group: 'kanban-tickets',
        animation: 150,
        ghostClass: 'kanban-ghost',
        dragClass: 'kanban-drag',
        chosenClass: 'kanban-chosen',
        delay: 80,
        delayOnTouchOnly: true,
        // Solo registrar la posición de inicio. NO marcar como "dragged"
        // todavía porque el usuario podría estar haciendo un click largo.
        onStart: function (evt) {
          if (evt.item) {
            evt.item.dataset.dragStartX = String(evt.originalEvent?.clientX || 0);
            evt.item.dataset.dragStartY = String(evt.originalEvent?.clientY || 0);
          }
        },
        onEnd: function (evt) {
          const tarjeta = evt.item;
          // Determinar si fue un drag REAL: cambió de columna o de índice
          const mismaColumna = evt.from === evt.to;
          const mismaPosicion = mismaColumna && evt.oldIndex === evt.newIndex;
          const huboMovimiento = !mismaPosicion;
          if (tarjeta) {
            if (huboMovimiento) {
              tarjeta.dataset.dragged = '1';
            } else {
              tarjeta.dataset.dragged = '0';
            }
            // Limpiar después de un breve delay para que el click handler
            // (que usa setTimeout(0)) tenga tiempo de leer el flag.
            setTimeout(() => {
              if (tarjeta) {
                tarjeta.dataset.dragged = '0';
                delete tarjeta.dataset.dragStartX;
                delete tarjeta.dataset.dragStartY;
              }
            }, 150);
          }
          handleDrop(tarjeta, evt);
        },
        // Si se suelta sin arrastrar (mousedown + mouseup sin mover),
        // limpiar el flag para que el click handler abra el detalle.
        onUnchoose: function (evt) {
          if (evt.item) {
            // Asegurar que el flag esté limpio para que un click lento
            // (que disparó onChoose pero no generó drag real) abra el modal.
            evt.item.dataset.dragged = '0';
            setTimeout(() => {
              if (evt.item) {
                evt.item.dataset.dragged = '0';
                delete evt.item.dataset.dragStartX;
                delete evt.item.dataset.dragStartY;
              }
            }, 50);
          }
        },
      });
    });
  }

  function actualizarContadores() {
    document.querySelectorAll('.kanban-column').forEach((col) => {
      const id = col.dataset.estadoId;
      const count = col.querySelectorAll('.kanban-card').length;
      const badge = document.getElementById(`count-${id}`);
      if (badge) badge.textContent = count;
    });
  }

  // === Clic en tarjeta abre el detalle ===
  // Implementación robusta: listeners DIRECTOS en cada tarjeta (no solo
  // delegación en body), uso de fetch directo (no htmx.ajax) para evitar
  // dependencias de HTMX, y un setTimeout(0) para evitar la condición de
  // carrera con SortableJS que puede suprimir el evento click durante el
  // mousedown.
  function initCardDoubleClick() {
    attachCardClickListeners();
  }

  function attachCardClickListeners() {
    const cards = document.querySelectorAll('.kanban-card');
    cards.forEach((card) => {
      if (card.dataset.clickInit === '1') return;
      card.dataset.clickInit = '1';

      // === MOUSEDOWN: registrar posición de inicio ===
      // Esto nos permite detectar si el usuario realmente arrastró
      // midiendo la distancia entre mousedown y mouseup.
      card.addEventListener('mousedown', (e) => {
        card.dataset.mouseDownX = String(e.clientX);
        card.dataset.mouseDownY = String(e.clientY);
      });

      // === MOUSEUP: si el mouse se movió >5px, fue un drag real ===
      card.addEventListener('mouseup', (e) => {
        const startX = parseInt(card.dataset.mouseDownX || '0', 10);
        const startY = parseInt(card.dataset.mouseDownY || '0', 10);
        const dx = Math.abs(e.clientX - startX);
        const dy = Math.abs(e.clientY - startY);
        if (dx > 5 || dy > 5) {
          card.dataset.realDrag = '1';
        } else {
          card.dataset.realDrag = '0';
        }
      });

      // === CLICK handler en la tarjeta ===
      card.addEventListener('click', (e) => {
        // Si el click fue en el botón de ojo, ese botón tiene su propio handler
        if (e.target.closest('.open-detail-btn')) return;
        // Si el click fue en un input/textarea/select, no interceptar
        if (e.target.closest('input, textarea, select, label')) return;
        // Si fue en un enlace, dejar que el navegador lo maneje
        if (e.target.closest('a')) return;
        // Si fue un drag real (mouse se movió >5px), no abrir modal
        if (card.dataset.realDrag === '1') return;
        // Verificación adicional: comparar mousedown/mouseup
        const startX = parseInt(card.dataset.mouseDownX || '0', 10);
        const startY = parseInt(card.dataset.mouseDownY || '0', 10);
        const dx = Math.abs((e.clientX || 0) - startX);
        const dy = Math.abs((e.clientY || 0) - startY);
        if (dx > 5 || dy > 5) return;
        // Si la tarjeta fue arrastrada por SortableJS, no abrir
        if (card.dataset.dragged === '1') return;
        // Esperar al siguiente tick para evitar conflicto con SortableJS
        setTimeout(() => {
          if (card.dataset.dragged === '1') return;
          const ticketId = card.dataset.ticketId;
          if (ticketId) abrirDetalle(ticketId);
        }, 0);
      });

      // === CLICK handler en el botón de ojo ===
      const eyeBtn = card.querySelector('.open-detail-btn');
      if (eyeBtn) {
        eyeBtn.addEventListener('click', (e) => {
          // Usar capture para que nuestro handler corra ANTES que el de HTMX
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          const ticketId = card.dataset.ticketId;
          if (ticketId) abrirDetalle(ticketId);
        }, true); // <-- capture: true para ganar la carrera con HTMX
      }
    });
  }

  // === Activación por teclado (Enter o Space) ===
  function initKeyboardActivation() {
    document.body.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const card = e.target.closest('.kanban-card');
      if (!card) return;
      // Si el foco está en un botón/input/textarea, no interceptar
      if (e.target.closest('button, a, input, textarea, select, label')) return;
      e.preventDefault();
      const ticketId = card.dataset.ticketId;
      if (ticketId) abrirDetalle(ticketId);
    });
  }

  // === Doble clic en una tarjeta abre el detalle ===
  function initDblClick() {
    document.body.addEventListener('dblclick', (e) => {
      const card = e.target.closest('.kanban-card');
      if (!card) return;
      if (e.target.closest('button, a, input, textarea, select, label')) return;
      const ticketId = card.dataset.ticketId;
      if (!ticketId) return;
      e.preventDefault();
      abrirDetalle(ticketId);
    });
  }

  // === Abrir modal de detalle ===
  // Usa fetch directo (no htmx.ajax) para máxima robustez.
  // Funciona incluso si HTMX no se ha cargado todavía.
  function abrirDetalle(ticketId) {
    if (!ticketId) return;
    // Si ya hay un modal abierto, no abrir otro
    const existing = document.querySelector('[data-modal="detalle-ticket"]');
    if (existing) return;

    const root = document.getElementById('modal-root');
    if (!root) {
      console.error('[kanban] No se encontró #modal-root');
      return;
    }

    // Mostrar loading state
    root.innerHTML = '<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/30"><div class="bg-white rounded-xl shadow-2xl px-6 py-4 flex items-center gap-3"><div class="w-4 h-4 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin"></div><span class="text-sm text-slate-600">Cargando detalle...</span></div></div>';

    // Usar HTMX si está disponible, si no, fetch directo
    const useHtmx = typeof htmx !== 'undefined' && htmx.ajax;
    if (useHtmx) {
      try {
        htmx.ajax('GET', `/api/v1/tickets/${ticketId}/detalle-html`, {
          target: '#modal-root',
          swap: 'innerHTML',
        });
        return;
      } catch (err) {
        console.warn('[kanban] htmx.ajax falló, usando fetch directo:', err);
      }
    }

    // Fallback: fetch directo
    fetch(`/api/v1/tickets/${ticketId}/detalle-html`, {
      headers: {
        'X-User-Id': String(getCurrentUserId()),
        'Accept': 'text/html',
      },
      credentials: 'same-origin',
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((html) => {
        root.innerHTML = html;
        // Disparar evento htmx:load para que HTMX procese los nuevos elementos
        if (typeof htmx !== 'undefined') {
          try { htmx.process(root); } catch (_) {}
        }
      })
      .catch((err) => {
        console.error('[kanban] Error al cargar detalle:', err);
        root.innerHTML = '<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop"><div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 text-center"><h3 class="text-lg font-semibold text-red-700 mb-2">Error</h3><p class="text-sm text-slate-600 mb-4">No se pudo cargar el detalle del ticket.</p><button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button></div></div>';
      });
  }

  // === Cerrar cualquier modal del modal-root ===
  function initModalClose() {
    document.body.addEventListener('click', (e) => {
      // Usar closest() para capturar clicks en el SVG/path dentro del botón
      const closeBtn = e.target.closest('[data-close-modal]');
      if (closeBtn) {
        e.preventDefault();
        e.stopPropagation();
        const root = document.getElementById('modal-root');
        if (root) root.innerHTML = '';
        return;
      }
      // Click en el backdrop (fuera del modal)
      if (e.target.classList && e.target.classList.contains('modal-backdrop')) {
        const root = document.getElementById('modal-root');
        if (root) root.innerHTML = '';
      }
    });
    document.body.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const root = document.getElementById('modal-root');
        if (root) root.innerHTML = '';
        const cm = document.getElementById('comentario-modal');
        if (cm) cm.remove();
      }
    });
  }

  // Inicializar cuando cargue el DOM
  document.addEventListener('DOMContentLoaded', () => {
    initSortable();
    initCardDoubleClick();
    initKeyboardActivation();
    initDblClick();
    initModalClose();
    initDetailModal();   // <-- Inicializar listeners de tabs/duplicar/cambio
    initFilters();
    initNuevoTicketButton();
  });

  // === Fallback robusto para el botón '+ Nueva Incidencia' ===
  function initNuevoTicketButton() {
    const btn = document.getElementById('btn-nuevo-ticket');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
      // HTMX se encargará del GET, pero por si falla (CDN lento, etc.)
      // forzamos la apertura tras un breve timeout si no se insertó HTML.
      setTimeout(() => {
        const root = document.getElementById('modal-root');
        if (root && !root.innerHTML.trim()) {
          fetch('/tickets/nuevo', { headers: { 'X-User-Id': String(getCurrentUserId()) } })
            .then(r => r.text())
            .then(html => { if (root && !root.innerHTML.trim()) root.innerHTML = html; })
            .catch(() => { /* HTMX probablemente ya cargó el modal */ });
        }
      }, 250);
    });
  }

  // ====================================================================
  // MODAL DE DETALLE (con tabs, duplicar, cambio rápido)
  // ====================================================================
  // Implementado con DELEGACIÓN DE EVENTOS en document.body porque:
  //   1. El modal se inserta vía innerHTML (los <script> inline NO se ejecutan)
  //   2. El modal se reemplaza completamente tras cada hx-post (hijos nuevos)
  //   3. La delegación es robusta y funciona para cualquier modal presente
  // ====================================================================
  function initDetailModal() {
    // === TABS (click en .tab-btn) ===
    document.body.addEventListener('click', (e) => {
      const tabBtn = e.target.closest('.tab-btn');
      if (!tabBtn) return;
      // Buscar el modal raíz más cercano
      const modal = tabBtn.closest('[data-modal]');
      if (!modal) return;
      const target = tabBtn.dataset.tab;
      if (!target) return;

      // Marcar el tab activo en el propio modal (data-active-tab)
      modal.dataset.activeTab = target;

      // Actualizar todos los inputs hidden name="active_tab" en formularios
      // del modal para que, al hacer POST, el backend sepa qué tab mostrar.
      modal.querySelectorAll('input[name="active_tab"]').forEach((inp) => {
        inp.value = target;
      });

      // Alternar el estilo de los botones
      modal.querySelectorAll('.tab-btn').forEach((b) => {
        if (b === tabBtn) {
          b.classList.add('border-indigo-600', 'text-indigo-700');
          b.classList.remove('border-transparent', 'text-slate-500');
        } else {
          b.classList.remove('border-indigo-600', 'text-indigo-700');
          b.classList.add('border-transparent', 'text-slate-500');
        }
      });
      // Mostrar/ocultar paneles
      modal.querySelectorAll('.tab-panel').forEach((p) => {
        if (p.dataset.panel === target) {
          p.classList.remove('hidden');
        } else {
          p.classList.add('hidden');
        }
      });
    });

    // === DUPLICAR TICKET (click en [data-action="duplicar-ticket"]) ===
    document.body.addEventListener('click', async (e) => {
      const dupBtn = e.target.closest('[data-action="duplicar-ticket"]');
      if (!dupBtn) return;
      e.preventDefault();
      e.stopPropagation();
      const ticketId = dupBtn.dataset.ticketId;
      if (!ticketId) return;
      if (!confirm('¿Duplicar este ticket? Se creará una copia en estado inicial.')) return;
      try {
        const r = await fetch('/api/v1/tickets/' + ticketId + '/duplicar', {
          method: 'POST',
          headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
        });
        if (!r.ok) {
          const data = await r.json().catch(() => ({}));
          throw new Error(data.detail || 'Error al duplicar');
        }
        const data = await r.json();
        // Cerrar este modal y abrir el nuevo
        const root = document.getElementById('modal-root');
        if (root) root.innerHTML = '';
        if (window.showToast) window.showToast('Ticket duplicado: ' + (data.codigo || ''), 'success');
        // Reabrir el modal con el nuevo ticket
        if (typeof htmx !== 'undefined' && htmx.ajax) {
          htmx.ajax('GET', '/api/v1/tickets/' + data.id + '/detalle-html', {
            target: '#modal-root', swap: 'innerHTML',
          });
        } else {
          abrirDetalle(data.id);
        }
      } catch (err) {
        alert('Error: ' + (err.message || err));
      }
    });

    // === CAMBIO DE ESTADO RÁPIDO (botones dentro de tab Detalles) ===
    // Se detecta el onclick que ya tienen los botones (compatibilidad)
    // y se hace fallback si la función no existe.
    window.cambiarEstadoRapido = function (ticketId, estadoId) {
      const evt = new CustomEvent('quick-state-change', {
        detail: { ticketId: parseInt(ticketId, 10), estadoId: parseInt(estadoId, 10) }
      });
      document.dispatchEvent(evt);
    };
  }

  // Re-inicializar si HTMX inyecta nuevas tarjetas
  document.body.addEventListener('htmx:afterSwap', () => {
    initSortable();
    attachCardClickListeners();
  });
  document.body.addEventListener('htmx:load', () => {
    initSortable();
    attachCardClickListeners();
  });

  // ============================================================
  // FILTROS DE TABLERO (estilo Trello / Linear)
  // ============================================================
  // Carga opciones de filtro (asignados/etiquetas) y aplica filtros
  // client-side a las tarjetas Kanban (data-* attributes).
  // ============================================================
  async function loadFilterOptions() {
    try {
      // Cargar usuarios y etiquetas en paralelo
      const [rUsr, rEt] = await Promise.all([
        fetch('/api/v1/catalogos/usuarios', { headers: { 'X-User-Id': String(getCurrentUserId()) } }),
        fetch('/api/v1/catalogos/etiquetas', { headers: { 'X-User-Id': String(getCurrentUserId()) } }),
      ]);
      const usuarios = rUsr.ok ? await rUsr.json() : [];
      const etiquetas = rEt.ok ? await rEt.json() : [];

      const selAsig = document.getElementById('filtro-asignado');
      if (selAsig) {
        selAsig.innerHTML = '<option value="">Todos</option>' +
          usuarios.map(u => `<option value="${u.id}">${u.nombre_completo || u.nombre || ('Usuario ' + u.id)}</option>`).join('');
      }
      const selEti = document.getElementById('filtro-etiqueta');
      if (selEti) {
        selEti.innerHTML = '<option value="">Todas</option>' +
          etiquetas.map(e => `<option value="${e.id}">${e.nombre}</option>`).join('');
      }
    } catch (e) {
      console.warn('No se pudieron cargar las opciones de filtro', e);
    }
  }

  function getFilterState() {
    return {
      q: (document.getElementById('filtro-q')?.value || '').trim().toLowerCase(),
      prioridad: document.getElementById('filtro-prioridad')?.value || '',
      asignado: document.getElementById('filtro-asignado')?.value || '',
      etiqueta: document.getElementById('filtro-etiqueta')?.value || '',
      mios: document.getElementById('filtro-mios')?.checked || false,
      criticos: document.getElementById('filtro-criticos')?.checked || false,
    };
  }

  function countActiveFilters(s) {
    let n = 0;
    if (s.q) n++;
    if (s.prioridad) n++;
    if (s.asignado) n++;
    if (s.etiqueta) n++;
    if (s.mios) n++;
    if (s.criticos) n++;
    return n;
  }

  function applyFilters() {
    const s = getFilterState();
    const cards = document.querySelectorAll('.kanban-card');
    let visible = 0;
    cards.forEach((card) => {
      let ok = true;
      // Texto libre
      if (s.q) {
        const haystack = [
          card.dataset.codigo || '',
          card.dataset.titulo || '',
          card.dataset.descripcion || '',
        ].join(' ');
        if (!haystack.includes(s.q)) ok = false;
      }
      // Prioridad
      if (ok && s.prioridad && card.dataset.prioridad !== s.prioridad) ok = false;
      // Asignado
      if (ok && s.asignado && String(card.dataset.asignadoId) !== String(s.asignado)) ok = false;
      // Etiqueta
      if (ok && s.etiqueta) {
        const ets = (card.dataset.etiquetas || '').split(',');
        if (!ets.includes(String(s.etiqueta))) ok = false;
      }
      // Solo míos
      if (ok && s.mios) {
        if (String(card.dataset.asignadoId) !== String(getCurrentUserId())) ok = false;
      }
      // Solo críticos
      if (ok && s.criticos && card.dataset.prioridad !== 'critica') ok = false;
      card.style.display = ok ? '' : 'none';
      if (ok) visible++;
    });
    // Actualizar contadores de cada columna
    document.querySelectorAll('.kanban-column').forEach((col) => {
      const id = col.dataset.estadoId;
      const count = col.querySelectorAll('.kanban-card:not([style*="display: none"])').length;
      const badge = document.getElementById(`count-${id}`);
      if (badge) badge.textContent = count;
    });
    // Resumen
    const resumen = document.getElementById('filtros-resumen');
    if (resumen) {
      const total = cards.length;
      resumen.textContent = total > 0 ? `${visible} de ${total} tarjetas` : '';
    }
    // Badge en botón Filtros
    const active = countActiveFilters(s);
    const badgeBtn = document.getElementById('filtros-activos');
    if (badgeBtn) {
      if (active > 0) {
        badgeBtn.textContent = active;
        badgeBtn.classList.remove('hidden');
      } else {
        badgeBtn.classList.add('hidden');
      }
    }
  }

  function initFilters() {
    const btn = document.getElementById('toggle-filtros');
    const panel = document.getElementById('panel-filtros');
    if (!btn || !panel) return; // No estamos en el Kanban

    btn.addEventListener('click', () => {
      panel.classList.toggle('hidden');
      // Si se está abriendo, cargar opciones
      if (!panel.classList.contains('hidden')) {
        loadFilterOptions();
      }
    });

    // Escuchar cambios en los inputs
    const ids = ['filtro-q', 'filtro-prioridad', 'filtro-asignado', 'filtro-etiqueta', 'filtro-mios', 'filtro-criticos'];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const evt = (el.tagName === 'INPUT' && (el.type === 'text' || el.type === 'search'))
        ? 'input' : 'change';
      el.addEventListener(evt, applyFilters);
    });

    // Botón limpiar
    const limpiar = document.getElementById('filtros-limpiar');
    if (limpiar) {
      limpiar.addEventListener('click', () => {
        const q = document.getElementById('filtro-q');
        if (q) q.value = '';
        const p = document.getElementById('filtro-prioridad');
        if (p) p.value = '';
        const a = document.getElementById('filtro-asignado');
        if (a) a.value = '';
        const e = document.getElementById('filtro-etiqueta');
        if (e) e.value = '';
        const m = document.getElementById('filtro-mios');
        if (m) m.checked = false;
        const c = document.getElementById('filtro-criticos');
        if (c) c.checked = false;
        applyFilters();
      });
    }

    // Aplicar filtros iniciales (si vienen por querystring)
    const params = new URLSearchParams(window.location.search);
    const qP = params.get('q');
    if (qP) {
      const q = document.getElementById('filtro-q');
      if (q) {
        q.value = qP;
        panel.classList.remove('hidden');
        loadFilterOptions();
        setTimeout(applyFilters, 100);
      }
    }
  }
})();
