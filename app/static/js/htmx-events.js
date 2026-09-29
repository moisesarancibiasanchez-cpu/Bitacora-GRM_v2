/**
 * Manejador de eventos HTMX: muestra toasts y notifica al usuario.
 * También maneja drag-and-drop de adjuntos, preview de archivos, y
 * editor Markdown ligero para Descripción.
 */
(function () {
  'use strict';

  function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const colors = {
      success: 'bg-emerald-50 border-emerald-300 text-emerald-800',
      error: 'bg-red-50 border-red-300 text-red-800',
      warning: 'bg-amber-50 border-amber-300 text-amber-800',
      info: 'bg-blue-50 border-blue-300 text-blue-800',
    };
    const icons = {
      success: '✓',
      error: '✕',
      warning: '!',
      info: 'i',
    };

    const div = document.createElement('div');
    div.className = `toast border-l-4 ${colors[type] || colors.info} bg-white shadow-lg rounded-r-md px-4 py-3 text-sm flex items-start gap-2 min-w-[260px] animate-fade-in`;
    div.innerHTML = `
      <span class="font-bold w-4 inline-block text-center">${icons[type] || 'i'}</span>
      <span class="flex-1">${message}</span>
      <button class="text-slate-400 hover:text-slate-600" onclick="this.parentElement.remove()">×</button>
    `;
    container.appendChild(div);
    setTimeout(() => div.remove(), duration);
  }
  window.showToast = showToast;

  // HTMX eventos globales
  document.body.addEventListener('ticket-updated', () => {
    // El ticket se actualizó correctamente (el toast ya se muestra desde kanban.js)
  });

  // Toast de confirmación al editar un campo desde el modal de detalle
  document.body.addEventListener('ticket-campo-editado', (evt) => {
    if (!window.showToast) return;
    const campo = (evt.detail && evt.detail.campo) || 'campo';
    const labels = {
      'titulo': 'Título',
      'descripcion': 'Descripción',
      'prioridad': 'Prioridad',
      'asignado_id': 'Asignado',
      'fecha_vencimiento': 'Fecha de vencimiento',
    };
    const nombre = labels[campo] || campo;
    window.showToast(nombre + ' guardado correctamente', 'success');
  });

  // ===========================================================================
  // EVENTO: ticket-guardado
  // Se dispara desde el backend (HX-Trigger) cuando el usuario pulsa el
  // botón "Guardar cambios" en el modal de detalle (POST /tickets/{id}/guardar).
  // Refresca la tarjeta correspondiente en el tablero Kanban para que
  // muestre los nuevos valores (prioridad, asignado, título, descripción, etc.)
  // sin necesidad de recargar la página completa.
  // ===========================================================================
  document.body.addEventListener('ticket-guardado', async (evt) => {
    const detail = (evt && evt.detail) || {};
    const ticketId = detail.ticket_id;
    const estadoId = detail.estado_id;
    if (!ticketId) {
      console.warn('[htmx-events] ticket-guardado sin ticket_id');
      return;
    }

    try {
      // 1) Obtener el HTML actualizado de la tarjeta
      const r = await fetch(`/api/v1/tickets/${ticketId}/card-html`, {
        headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
        credentials: 'same-origin',
      });
      if (!r.ok) {
        if (window.showToast) {
          window.showToast('Cambios guardados. Recarga el tablero para verlos.', 'info', 4000);
        }
        return;
      }
      const html = await r.text();

      // 2) Localizar la tarjeta actual en el DOM
      const currentCard = document.getElementById(`ticket-${ticketId}`);
      if (currentCard) {
        // Construir el nuevo nodo desde el HTML recibido
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const newCard = wrapper.firstElementChild;
        if (newCard && newCard.id === `ticket-${ticketId}`) {
          // Determinar la columna destino: la del estado actual del ticket
          const targetList = estadoId != null
            ? document.querySelector(`.kanban-list[data-estado-id="${estadoId}"]`)
            : null;

          if (targetList && currentCard.parentElement !== targetList) {
            // El ticket cambió de columna (poco probable desde /guardar, pero
            // se contempla por si el form incluye estado en el futuro).
            // Quitar placeholder "Arrastra una tarjeta aquí" si existe
            const emptyPlaceholder = targetList.querySelector('.empty-column');
            if (emptyPlaceholder) emptyPlaceholder.remove();
            targetList.insertBefore(newCard, targetList.firstChild);
            currentCard.remove();
            // Actualizar contadores
            if (typeof window.actualizarContadores === 'function') {
              try { window.actualizarContadores(); } catch (_) {}
            }
          } else {
            // Misma columna: reemplazo in-place con animación sutil
            try {
              newCard.style.opacity = '0';
              newCard.style.transition = 'opacity 250ms ease';
            } catch (_) {}
            currentCard.parentNode.replaceChild(newCard, currentCard);
            // Fade-in
            requestAnimationFrame(() => {
              try { newCard.style.opacity = '1'; } catch (_) {}
            });
          }

          // Procesar hx-* del nodo nuevo (HTMX + fallback)
          if (typeof window.htmxFallbackProcess === 'function' && !window.htmxFallbackReady()) {
            try { window.htmxFallbackProcess(newCard); } catch (_) {}
          }
          if (typeof htmx !== 'undefined' && htmx.process) {
            try { htmx.process(newCard); } catch (_) {}
          }
        } else {
          // Fallback: si el HTML no contiene un nodo con el id esperado,
          // intentar reemplazo por outerHTML directo
          const parent = currentCard.parentNode;
          if (parent) {
            parent.outerHTML = html;
          }
        }
      } else {
        // La tarjeta no está en el DOM (p.ej. estamos en una vista distinta
        // al Kanban). Mostrar un toast informativo.
        if (window.showToast) {
          const campos = detail.campos || [];
          const lista = campos.length ? ` (${campos.join(', ')})` : '';
          window.showToast('Cambios guardados' + lista, 'success', 2500);
        }
      }
    } catch (err) {
      console.error('[htmx-events] Error al refrescar tarjeta:', err);
      if (window.showToast) {
        window.showToast('Cambios guardados. Recarga para verlos en el tablero.', 'info', 4000);
      }
    }
  });

  document.body.addEventListener('ticket-error', (evt) => {
    if (window.showToast) {
      window.showToast(evt.detail.message || 'Operación no permitida', 'error');
    }
  });

  // ===========================================================================
  // EVENTO: ticket-created
  // Se dispara desde el backend (HX-Trigger) cuando se crea un nuevo ticket.
  // Inserta la tarjeta en la columna correspondiente del tablero Kanban
  // sin necesidad de recargar la página completa.
  // ===========================================================================
  document.body.addEventListener('ticket-created', async (evt) => {
    const detail = (evt && evt.detail) || {};
    const ticketId = detail.ticket_id;
    if (!ticketId) {
      console.warn('[htmx-events] ticket-created sin ticket_id');
      return;
    }

    // 1) Cerrar el modal de éxito
    const modalRoot = document.getElementById('modal-root');
    if (modalRoot) modalRoot.innerHTML = '';

    try {
      // 2) Obtener el estado del ticket (necesitamos estado_id para la columna)
      let estadoId = null;
      try {
        const r2 = await fetch(`/api/v1/tickets/${ticketId}`, {
          headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
          credentials: 'same-origin',
        });
        if (r2.ok) {
          const ticketData = await r2.json();
          estadoId = ticketData.estado_id;
        }
      } catch (_) { /* fallback */ }

      // 3) Obtener el HTML de la nueva tarjeta
      const r = await fetch(`/api/v1/tickets/${ticketId}/card-html`, {
        headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
        credentials: 'same-origin',
      });
      if (!r.ok) {
        if (window.showToast) {
          window.showToast('Incidencia creada. Recarga el tablero para verla.', 'info', 5000);
        }
        return;
      }
      const html = await r.text();

      // 4) Buscar la columna destino
      let targetList = null;
      if (estadoId != null) {
        targetList = document.querySelector(`.kanban-list[data-estado-id="${estadoId}"]`);
      }
      // Fallback: si no se pudo determinar el estado, insertar en la primera columna
      if (!targetList) {
        targetList = document.querySelector('.kanban-list');
      }
      if (!targetList) {
        if (window.showToast) {
          window.showToast('Incidencia creada. Recarga el tablero para verla.', 'info', 5000);
        }
        return;
      }

      // 5) Quitar el placeholder "Arrastra una tarjeta aquí" si existe
      const emptyPlaceholder = targetList.querySelector('.empty-column');
      if (emptyPlaceholder) emptyPlaceholder.remove();

      // 6) Insertar la nueva tarjeta AL INICIO de la lista
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html.trim();
      const newCard = wrapper.firstElementChild;
      if (newCard) {
        newCard.style.animation = 'fade-in 0.6s ease-out';
        targetList.insertBefore(newCard, targetList.firstChild);
      }

      // 7) Actualizar el contador de la columna
      if (estadoId != null) {
        const counter = document.getElementById(`count-${estadoId}`);
        if (counter) {
          const current = parseInt(counter.textContent || '0', 10) || 0;
          counter.textContent = String(current + 1);
        }
      }

      // 8) Notificar al usuario
      if (window.showToast) {
        const archivos = detail.archivos_subidos || 0;
        const items = detail.items_creados || 0;
        let msg = `Incidencia ${detail.codigo || ''} creada correctamente`;
        if (archivos) msg += ` · ${archivos} archivo(s)`;
        if (items) msg += ` · ${items} item(s) de checklist`;
        window.showToast(msg, 'success');
      }

      // 9) Procesar hx-* en la nueva tarjeta
      if (typeof window.htmxFallbackProcess === 'function' && !window.htmxFallbackReady()) {
        try { window.htmxFallbackProcess(newCard); } catch (_) {}
      }
      if (typeof htmx !== 'undefined' && htmx.process && newCard) {
        try { htmx.process(newCard); } catch (_) {}
      }
    } catch (err) {
      console.error('[htmx-events] Error al insertar nueva tarjeta:', err);
      if (window.showToast) {
        window.showToast('Incidencia creada. Recarga el tablero para verla.', 'info', 5000);
      }
    }
  });

  // Eventos de creación de recursos en modal de detalle
  const _evtMsgs = {
    'comentario-creado':   { msg: 'Comentario agregado correctamente',         type: 'success' },
    'comentario-eliminado':{ msg: 'Comentario eliminado',                      type: 'info' },
    'checklist-creada':    { msg: 'Checklist creado correctamente',            type: 'success' },
    'checklist-eliminada': { msg: 'Checklist eliminado',                       type: 'info' },
    'checklist-item-agregado': { msg: 'Tarea agregada al checklist',           type: 'success' },
    'checklist-item-eliminado': { msg: 'Tarea eliminada del checklist',        type: 'info' },
    'checklist-item-toggle': { msg: 'Tarea actualizada',                       type: 'info' },
    'adjunto-subido':      { msg: 'Archivo(s) subido(s) correctamente',       type: 'success' },
    'adjunto-eliminado':   { msg: 'Adjunto eliminado',                         type: 'info' },
    'etiqueta-asignada':   { msg: 'Etiqueta agregada al ticket',               type: 'success' },
    'etiqueta-removida':   { msg: 'Etiqueta quitada del ticket',               type: 'info' },
  };
  Object.keys(_evtMsgs).forEach((evt) => {
    document.body.addEventListener(evt, (e) => {
      if (!window.showToast) return;
      let msg = _evtMsgs[evt].msg;
      // Personalizar mensaje para adjunto con conteo
      if (evt === 'adjunto-subido' && e.detail && e.detail.count) {
        msg = e.detail.count + ' archivo(s) subido(s) correctamente';
      }
      window.showToast(msg, _evtMsgs[evt].type);
    });
  });

  // ============================================================================
  // Drag & drop de archivos + preview + COPY-PASTE de imágenes (Ctrl+V)
  // ============================================================================
  function formatBytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  // -------------------------------------------------------------------------
  // COPY-PASTE: estado y handlers globales (instalados UNA sola vez)
  // -------------------------------------------------------------------------
  // Mapa ticketId -> [{id, file, url}]  (object URLs hay que revocarlos)
  const _pastedFiles = new Map();
  const MAX_PASTE_BYTES = 25 * 1024 * 1024; // mismo límite que backend (AdjuntoService)

  function _getPastedFiles(ticketId) {
    if (!_pastedFiles.has(ticketId)) _pastedFiles.set(ticketId, []);
    return _pastedFiles.get(ticketId);
  }

  // Detecta qué dropzone está visible (tab "Adjuntos" activo del modal abierto)
  function _activeAdjuntosTicketId() {
    const drops = document.querySelectorAll('.adjuntos-dropzone');
    for (const d of drops) {
      const panel = d.closest('.tab-panel');
      if (panel && !panel.classList.contains('hidden')) {
        return d.getAttribute('data-ticket-id');
      }
    }
    return null;
  }

  function _revokeAllPastedUrls(ticketId) {
    const arr = _pastedFiles.get(ticketId);
    if (!arr) return;
    arr.forEach(p => { try { URL.revokeObjectURL(p.url); } catch (e) {} });
    _pastedFiles.set(ticketId, []);
  }

  // Listener global de paste (se instala UNA vez por carga de la página)
  let _pasteGlobalInstalled = false;
  function _installGlobalPasteHandler() {
    if (_pasteGlobalInstalled) return;
    _pasteGlobalInstalled = true;
    document.addEventListener('paste', function (e) {
      // No interceptar paste dentro de inputs de texto o textareas: dejar
      // que el navegador haga su trabajo normal (pegar texto donde el usuario
      // está escribiendo).
      const t = e.target;
      if (t) {
        const tag = (t.tagName || '').toUpperCase();
        if (tag === 'TEXTAREA') return;
        if (tag === 'INPUT') {
          const type = ((t.type || '') + '').toLowerCase();
          const texty = ['text','password','email','search','tel','url','number',
                         'date','datetime-local','month','week','time'].includes(type);
          if (texty) return;
        }
        if (t.isContentEditable) return;
      }
      const items = e.clipboardData && e.clipboardData.items;
      if (!items || items.length === 0) return;

      const ticketId = _activeAdjuntosTicketId();
      if (!ticketId) return; // no hay tab de adjuntos activo

      let added = 0;
      let rejectedSize = 0;
      const arr = _getPastedFiles(ticketId);
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind !== 'file' || !item.type || !item.type.startsWith('image/')) continue;
        const blob = item.getAsFile();
        if (!blob) continue;
        if (blob.size > MAX_PASTE_BYTES) {
          rejectedSize++;
          continue;
        }
        const ext = (item.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace('svg+xml', 'svg');
        const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15);
        const fname = 'paste-' + ts + '-' + (arr.length + added + 1) + '.' + ext;
        const file = new File([blob], fname, { type: item.type });
        const url = URL.createObjectURL(blob);
        const id = 'p' + Date.now().toString(36) + added;
        arr.push({ id: id, file: file, url: url });
        added++;
      }
      if (added === 0) {
        if (rejectedSize > 0 && typeof showToast === 'function') {
          showToast(rejectedSize + ' imagen(es) rechazada(s): exceden 25 MB', 'error');
        }
        return;
      }
      // Solo prevenimos default si consumimos imágenes (no rompemos
      // paste de texto en otros lugares).
      e.preventDefault();
      _renderPasteList(ticketId);
      _refreshCombinedFiles(ticketId);
      if (typeof showToast === 'function') {
        const msg = added === 1
          ? '1 imagen pegada — descripción opcional antes de subir'
          : added + ' imágenes pegadas — descripción opcional antes de subir';
        showToast(msg, 'success');
      }
    });
  }

  function _renderPasteList(ticketId) {
    const list = document.getElementById('adjuntos-paste-list-' + ticketId);
    if (!list) return;
    // Solo renderizamos los archivos NO marcados como removed.
    const all = _getPastedFiles(ticketId);
    const items = all.filter(function (p) { return !p.removed; });
    if (items.length === 0) {
      list.classList.add('hidden');
      list.innerHTML = '';
      return;
    }
    list.classList.remove('hidden');
    const rows = items.map(function (p) {
      return (
        '<div class="flex items-center gap-2 p-1.5 bg-indigo-50 border border-indigo-200 rounded">' +
          '<img src="' + p.url + '" alt="preview" class="w-10 h-10 object-cover rounded border border-slate-200 flex-shrink-0" />' +
          '<span class="text-[11px] text-slate-700 truncate flex-1" title="' + escapeHtml(p.file.name) + '">' + escapeHtml(p.file.name) + '</span>' +
          '<span class="text-[10px] text-slate-400 flex-shrink-0">' + formatBytes(p.file.size) + '</span>' +
          '<button type="button" data-remove-paste="' + p.id + '" class="text-rose-500 hover:text-rose-700 flex-shrink-0 inline-flex items-center justify-center w-5 h-5 rounded hover:bg-rose-100" title="Quitar">' +
            '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' +
          '</button>' +
        '</div>'
      );
    });
    list.innerHTML = rows.join('');
    list.querySelectorAll('[data-remove-paste]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const id = btn.getAttribute('data-remove-paste');
        const arr = _getPastedFiles(ticketId);
        const p = arr.find(function (x) { return x.id === id; });
        if (p) {
          // Marcar como removed en vez de splice: necesitamos mantener la
          // referencia al File object para que _refreshCombinedFiles pueda
          // distinguir "original" de "pegado" (los pegados removidos NO deben
          // volver a la sección de originales en el próximo merge).
          p.removed = true;
        }
        _renderPasteList(ticketId);
        _refreshCombinedFiles(ticketId);
      });
    });
  }

  // Mezcla archivos de fileInput (drag/click) + pastedFiles y re-asigna
  // fileInput.files. Como el form ya tiene name="archivos" multiple, el submit
  // envía todo en una sola request multipart.
  function _refreshCombinedFiles(ticketId) {
    const fileInput = document.getElementById('adjunto-file-' + ticketId);
    if (!fileInput) return;
    // fileInput.files puede contener (en cualquier orden):
    //   a) archivos drag/drop/click originales
    //   b) archivos pegados (que YA inyectamos previamente), incluyendo los
    //      marcados como removed (porque siguen referenciados en _pastedFiles)
    // Para distinguir, filtramos por referencia (===) contra TODOS los Files
    // que alguna vez fueron pegados (activos o removidos). Los removed no
    // deben volver a la lista de originales.
    const currentFiles = fileInput.files ? Array.from(fileInput.files) : [];
    const allPasted = _getPastedFiles(ticketId);
    const activePasted = allPasted.filter(function (p) { return !p.removed; });
    const allPastedFileSet = new Set(allPasted.map(function (p) { return p.file; }));
    const originalFiles = currentFiles.filter(function (f) { return !allPastedFileSet.has(f); });
    try {
      const dt = new DataTransfer();
      originalFiles.forEach(function (f) { dt.items.add(f); });
      activePasted.forEach(function (p) { dt.items.add(p.file); });
      fileInput.files = dt.files;
    } catch (err) {
      // Navegadores antiguos sin DataTransfer ctor: no se puede combinar.
      if (typeof showToast === 'function') {
        showToast('Tu navegador no soporta combinar archivos pegados con seleccionados.', 'info');
      }
    }
    // Disparar 'change' para que updatePreview() existente re-pinte.
    fileInput.dispatchEvent(new Event('change'));

    // Mostrar/ocultar textarea de descripción según haya archivos pegados
    const desc = document.getElementById('adjuntos-paste-desc-' + ticketId);
    if (desc) {
      if (activePasted.length > 0) {
        desc.classList.remove('hidden');
      } else if (originalFiles.length === 0) {
        desc.classList.add('hidden');
      }
    }
  }

  // Tras submit OK, limpiamos estado del ticket (lo llama el listener
  // global de htmx:afterRequest del form, ver abajo).
  function _clearPastedAfterUpload(ticketId) {
    _revokeAllPastedUrls(ticketId);
    const list = document.getElementById('adjuntos-paste-list-' + ticketId);
    if (list) { list.classList.add('hidden'); list.innerHTML = ''; }
    const desc = document.getElementById('adjuntos-paste-desc-' + ticketId);
    if (desc) { desc.value = ''; desc.classList.add('hidden'); }
  }

  function setupAdjuntosDropzone() {
    // El listener de paste se instala UNA sola vez por página, no por dropzone.
    _installGlobalPasteHandler();

    document.querySelectorAll('.adjuntos-dropzone').forEach(function (drop) {
      if (drop.dataset.dzInit === '1') return;
      drop.dataset.dzInit = '1';
      const ticketId = drop.getAttribute('data-ticket-id');
      const fileInput = document.getElementById('adjunto-file-' + ticketId);
      const preview = document.getElementById('adjuntos-preview-' + ticketId);
      const info = document.getElementById('adjuntos-info-' + ticketId);
      const form = document.getElementById('adjuntos-form-' + ticketId);
      if (!fileInput) return;

      // Si el modal se re-renderiza con archivos pegados en estado (raro,
      // pero defensivo), los repintamos.
      _renderPasteList(ticketId);
      _refreshCombinedFiles(ticketId);

      // Limpieza al cerrar el modal (vía htmx:beforeSwap o evento de cierre)
      document.body.addEventListener('modal-cerrado', function (ev) {
        if (!ticketId || (ev && ev.detail && String(ev.detail.ticketId) === String(ticketId))) {
          _clearPastedAfterUpload(ticketId);
        }
      });

      // Tras submit exitoso del form, limpiar estado de pegados.
      if (form) {
        form.addEventListener('htmx:afterRequest', function (ev) {
          if (ev.detail && ev.detail.successful) {
            _clearPastedAfterUpload(ticketId);
          }
        });
      }

      // Click en el dropzone abre el file picker (pero no si ya se hizo click en el input)
      drop.addEventListener('click', function (e) {
        if (e.target === fileInput) return;
        fileInput.click();
      });

      // Drag visual feedback
      ['dragenter', 'dragover'].forEach(function (ev) {
        drop.addEventListener(ev, function (e) {
          e.preventDefault();
          e.stopPropagation();
          drop.classList.add('border-indigo-500', 'bg-indigo-50/50');
        });
      });
      ['dragleave', 'drop'].forEach(function (ev) {
        drop.addEventListener(ev, function (e) {
          e.preventDefault();
          e.stopPropagation();
          drop.classList.remove('border-indigo-500', 'bg-indigo-50/50');
        });
      });

      // Soltar archivos
      drop.addEventListener('drop', function (e) {
        const files = e.dataTransfer && e.dataTransfer.files;
        if (!files || !files.length) return;
        try {
          // Mezclar con lo que ya haya en fileInput (caso normal: vacío)
          const dt = new DataTransfer();
          for (let i = 0; i < files.length; i++) dt.items.add(files[i]);
          fileInput.files = dt.files;
        } catch (err) {
          showToast('Tu navegador no soporta multi-drop. Selecciona manualmente.', 'info');
        }
        // Re-aplicar merge con pegados (no pierden)
        _refreshCombinedFiles(ticketId);
      });

      fileInput.addEventListener('change', updatePreview);

      function updatePreview() {
        const files = fileInput.files;
        if (!files || files.length === 0) {
          if (preview) { preview.classList.add('hidden'); preview.innerHTML = ''; }
          if (info) info.textContent = '';
          return;
        }
        if (preview) {
          preview.classList.remove('hidden');
          const items = [];
          let total = 0;
          for (let i = 0; i < files.length; i++) {
            const f = files[i];
            total += f.size;
            items.push(
              '<span class="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-100 border border-slate-200">' +
              '<svg class="w-3 h-3 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
              '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>' +
              '</svg>' + escapeHtml(f.name) + ' <span class="text-[10px] text-slate-400">(' + formatBytes(f.size) + ')</span></span>'
            );
          }
          preview.innerHTML = items.join('');
          if (info) {
            info.textContent = files.length + ' archivo(s) listo(s) para subir (' + formatBytes(total) + ')';
          }
        }
      }
    });
  }

  // ============================================================================
  // Editor Markdown ligero con tabs Escribir/Vista previa
  // ============================================================================
  function renderMarkdown(md) {
    if (!md || !md.trim()) return '<p class="text-slate-400 italic">Sin contenido</p>';
    let s = String(md)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    // Código en línea
    s = s.replace(/`([^`\n]+)`/g, '<code class="px-1 py-0.5 rounded bg-slate-100 text-pink-600 font-mono text-[12px]">$1</code>');
    // Negrita
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    // Itálica
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>');
    // Encabezados
    s = s.replace(/^###\s+(.+)$/gm, '<h3 class="text-sm font-semibold mt-2 mb-1">$1</h3>');
    s = s.replace(/^##\s+(.+)$/gm, '<h2 class="text-base font-semibold mt-2 mb-1">$1</h2>');
    s = s.replace(/^#\s+(.+)$/gm, '<h1 class="text-lg font-bold mt-2 mb-1">$1</h1>');
    // Links
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-600 underline">$1</a>');
    // Listas no ordenadas
    s = s.replace(/(^|\n)((?:- [^\n]+\n?)+)/g, function (m, pre, block) {
      const items = block.trim().split('\n').map(function (l) { return l.replace(/^- /, ''); }).map(function (t) { return '<li>' + t + '</li>'; }).join('');
      return pre + '<ul class="list-disc list-inside my-1 space-y-0.5">' + items + '</ul>';
    });
    // Listas ordenadas
    s = s.replace(/(^|\n)((?:\d+\. [^\n]+\n?)+)/g, function (m, pre, block) {
      const items = block.trim().split('\n').map(function (l) { return l.replace(/^\d+\. /, ''); }).map(function (t) { return '<li>' + t + '</li>'; }).join('');
      return pre + '<ol class="list-decimal list-inside my-1 space-y-0.5">' + items + '</ol>';
    });
    // Saltos de línea
    s = s.replace(/\n/g, '<br>');
    return s;
  }

  function setupMarkdownEditors() {
    document.querySelectorAll('textarea[data-markdown="true"]').forEach(function (ta) {
      if (ta.dataset.mdInit === '1') return;
      ta.dataset.mdInit = '1';

      const wrap = document.createElement('div');
      wrap.className = 'rounded-md border border-slate-300 overflow-hidden focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-indigo-500';
      ta.parentNode.insertBefore(wrap, ta);

      const tabs = document.createElement('div');
      tabs.className = 'flex items-center justify-between bg-slate-50 border-b border-slate-200 px-2 py-1';
      tabs.innerHTML =
        '<div class="flex items-center gap-1">' +
          '<button type="button" data-md-tab="preview" class="md-tab px-2 py-0.5 text-[11px] font-medium rounded bg-white text-slate-700 border border-slate-200">Vista previa</button>' +
          '<button type="button" data-md-tab="write" class="md-tab px-2 py-0.5 text-[11px] font-medium rounded text-slate-500 hover:text-slate-700">Escribir</button>' +
        '</div>' +
        '<span class="text-[10px] text-slate-400">Markdown: **negrita** *itálica* `código` [link](url)</span>';
      wrap.appendChild(tabs);

      const editor = document.createElement('div');
      editor.className = 'bg-white';
      wrap.appendChild(editor);
      editor.appendChild(ta);

      // Quitar el border del textarea porque ya lo tiene el wrap
      ta.className = (ta.className || '').replace(/border\s+border-slate-300\s+rounded-md/g, '').trim() + ' w-full text-sm px-3 py-2 focus:outline-none';
      if (!ta.rows) ta.rows = 5;
      ta.style.minHeight = '120px';
      ta.style.resize = 'vertical';

      const preview = document.createElement('div');
      preview.className = 'hidden px-3 py-2 text-sm text-slate-700 min-h-[120px]';
      wrap.appendChild(preview);

      function setActive(tab) {
        tabs.querySelectorAll('.md-tab').forEach(function (b) {
          if (b.getAttribute('data-md-tab') === tab) {
            b.classList.add('bg-white', 'text-slate-700', 'border', 'border-slate-200');
            b.classList.remove('text-slate-500');
          } else {
            b.classList.remove('bg-white', 'text-slate-700', 'border', 'border-slate-200');
            b.classList.add('text-slate-500');
          }
        });
        if (tab === 'preview') {
          editor.classList.add('hidden');
          preview.classList.remove('hidden');
          preview.innerHTML = renderMarkdown(ta.value || '');
        } else {
          editor.classList.remove('hidden');
          preview.classList.add('hidden');
        }
      }
      tabs.addEventListener('click', function (e) {
        const b = e.target.closest('[data-md-tab]');
        if (!b) return;
        setActive(b.getAttribute('data-md-tab'));
      });
      ta.addEventListener('input', function () {
        if (!preview.classList.contains('hidden')) {
          preview.innerHTML = renderMarkdown(ta.value || '');
        }
      });
      // Por defecto arrancamos en "Vista previa" para que el usuario vea
      // la descripción ya formateada al abrir el modal. Cambiar a "Escribir"
      // sólo cuando quiera editar.
      setActive('preview');
    });
  }

  function reinitModalExtras() {
    setupAdjuntosDropzone();
    setupMarkdownEditors();
  }

  // Re-aplicar handlers cuando HTMX inserta HTML nuevo en el DOM
  document.body.addEventListener('htmx:afterSwap', function () {
    setTimeout(reinitModalExtras, 0);
  });
  document.body.addEventListener('htmx:load', function () {
    setTimeout(reinitModalExtras, 0);
  });
  document.body.addEventListener('htmx:afterOnLoad', function () {
    setTimeout(reinitModalExtras, 0);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', reinitModalExtras);
  } else {
    reinitModalExtras();
  }

  // Exponer para uso externo
  window.renderMarkdown = renderMarkdown;
  window.reinitModalExtras = reinitModalExtras;
})();
