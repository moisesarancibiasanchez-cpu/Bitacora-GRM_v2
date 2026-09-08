/**
 * Lógica de Drag & Drop con SortableJS + HTMX.
 *
 * 1. El usuario arrastra la tarjeta con SortableJS.
 * 2. Al soltarla en otra columna, SortableJS dispara `onEnd`.
 * 3. En `onEnd` hacemos una petición PATCH al backend con:
 *      - ticket_id
 *      - estado_id (destino)
 *      - orden (posición en la columna destino)
 * 4. HTMX intercepta la respuesta y reemplaza solo el fragmento HTML
 *    de la tarjeta (`outerHTML` swap). Si el backend devuelve 403/422,
 *    SortableJS revierte la posición automáticamente.
 */

(function () {
  'use strict';

  function initSortable() {
    const columns = document.querySelectorAll('.kanban-list');
    if (columns.length === 0) return;

    columns.forEach((col) => {
      // Evitar doble inicialización
      if (col.dataset.sortableInit) return;
      col.dataset.sortableInit = '1';

      new Sortable(col, {
        group: 'kanban-tickets',
        animation: 150,
        ghostClass: 'kanban-ghost',
        dragClass: 'kanban-drag',
        chosenClass: 'kanban-chosen',

        onEnd: function (evt) {
          const tarjeta = evt.item;
          const ticketId = tarjeta.dataset.ticketId;
          const nuevaColumna = evt.to;
          const estadoId = nuevaColumna.dataset.estadoId;
          const orden = evt.newIndex;

          if (!ticketId || !estadoId) {
            console.error('Falta ticket_id o estado_id en el DOM.');
            return;
          }

          // Si la tarjeta se quedó en la misma columna y misma posición, no hacer nada
          const mismaColumna = evt.from === evt.to;
          if (mismaColumna && evt.oldIndex === evt.newIndex) return;

          // PATCH al backend mediante HTMX (no recargamos la página)
          // HTMX acepta verbos arbitrarios con hx-trigger enviando por fetch.
          const url = `/api/v1/tickets/${ticketId}/estado`;

          // Guardamos la posición original por si falla la validación y hay que revertir
          const padreOriginal = evt.from;
          const indexOriginal = evt.oldIndex;

          fetch(url, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'X-User-Id': window.CURRENT_USER_ID || '1',
            },
            body: JSON.stringify({
              estado_id: parseInt(estadoId, 10),
              orden: orden,
            }),
          })
            .then(async (resp) => {
              if (resp.ok) {
                // Éxito: el backend devuelve el HTML actualizado de la tarjeta.
                const nuevoHTML = await resp.text();
                tarjeta.outerHTML = nuevoHTML;
                // Actualizar contadores
                actualizarContadores();
                // Toast de éxito
                if (window.showToast) {
                  window.showToast('Estado actualizado correctamente', 'success');
                }
              } else {
                // Fallo de validación: revertir posición y mostrar mensaje
                padreOriginal.insertBefore(tarjeta, padreOriginal.children[indexOriginal] || null);
                const txt = await resp.text();
                let mensaje = 'No se pudo cambiar el estado.';
                try {
                  // Extraer texto entre etiquetas
                  const match = txt.match(/<strong>[^<]+:<\/strong>\s*([^<]+)/);
                  if (match) mensaje = match[1].trim();
                } catch (_) {}
                if (window.showToast) {
                  window.showToast(mensaje, resp.status === 403 ? 'error' : 'warning');
                }
              }
            })
            .catch((err) => {
              // Error de red: revertir
              padreOriginal.insertBefore(tarjeta, padreOriginal.children[indexOriginal] || null);
              if (window.showToast) {
                window.showToast('Error de red al cambiar el estado', 'error');
              }
              console.error(err);
            });
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

  // Inicializar cuando cargue el DOM
  document.addEventListener('DOMContentLoaded', initSortable);

  // Re-inicializar si HTMX inyecta nuevas tarjetas (drag&drop dynamic)
  document.body.addEventListener('htmx:afterSwap', function (evt) {
    if (evt.target.id && evt.target.id.startsWith('ticket-')) {
      // La tarjeta fue reemplazada por HTMX, nada que hacer
    }
  });
  document.body.addEventListener('htmx:load', initSortable);
})();
