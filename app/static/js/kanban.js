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
        // Marcar la tarjeta como "realmente arrastrada" cuando SortableJS
        // confirma el inicio del drag (después del delay). Si nunca llega,
        // el click handler puede abrir el detalle sin chocar con drag.
        onStart: function (evt) {
          if (evt.item) evt.item.dataset.dragged = '1';
        },
        onEnd: function (evt) {
          const tarjeta = evt.item;
          // Limpiar flag de drag al terminar
          if (tarjeta) tarjeta.dataset.dragged = '0';
          handleDrop(tarjeta, evt);
        },
        // Si se suelta sin arrastrar (mousedown + mouseup sin mover),
        // limpiar el flag para que el click handler abra el detalle.
        onUnchoose: function (evt) {
          if (evt.item) {
            setTimeout(() => { if (evt.item) evt.item.dataset.dragged = '0'; }, 50);
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

  // === Doble clic en una tarjeta abre el detalle ===
  function initCardDoubleClick() {
    document.body.addEventListener('dblclick', (e) => {
      const card = e.target.closest('.kanban-card');
      if (!card) return;
      const ticketId = card.dataset.ticketId;
      if (!ticketId) return;
      e.preventDefault();
      abrirDetalle(ticketId);
    });

    // También soportar click en el cuerpo de la tarjeta (no solo dblclick).
    // Solo se abre el detalle si NO se está arrastrando (SortableJS pone
    // data-dragged='1' durante un drag real y lo limpia al soltarlo).
    document.body.addEventListener('click', (e) => {
      // Si es un click en un enlace o botón dentro de la tarjeta, no hacer nada
      if (e.target.closest('button, a, input, textarea, select, label')) return;
      const card = e.target.closest('.kanban-card');
      if (!card) return;
      const ticketId = card.dataset.ticketId;
      if (!ticketId) return;
      // Si la tarjeta está siendo arrastrada, no abrir el detalle
      if (card.dataset.dragged === '1') return;
      // Evitar que el click abra el modal cuando el dblclick ya lo abrió
      if (e.detail >= 2) return; // segundo click de un dblclick
      abrirDetalle(ticketId);
    });
  }

  // === Abrir modal de detalle (HTMX) ===
  function abrirDetalle(ticketId) {
    // Si ya hay un modal abierto, no abrir otro
    const existing = document.querySelector('[data-modal="detalle-ticket"]');
    if (existing) return;
    htmx.ajax('GET', `/api/v1/tickets/${ticketId}/detalle-html`, {
      target: '#modal-root',
      swap: 'innerHTML',
    });
  }

  // === Cerrar cualquier modal del modal-root ===
  function initModalClose() {
    document.body.addEventListener('click', (e) => {
      if (e.target.matches('[data-close-modal]')) {
        const root = document.getElementById('modal-root');
        if (root) root.innerHTML = '';
      }
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
    initModalClose();
  });

  // Re-inicializar si HTMX inyecta nuevas tarjetas
  document.body.addEventListener('htmx:afterSwap', () => {
    initSortable();
  });
  document.body.addEventListener('htmx:load', initSortable);
})();
