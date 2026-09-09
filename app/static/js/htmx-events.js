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

  document.body.addEventListener('ticket-error', (evt) => {
    if (window.showToast) {
      window.showToast(evt.detail.message || 'Operación no permitida', 'error');
    }
  });

  // Eventos de creación de recursos en modal de detalle
  const _evtMsgs = {
    'comentario-creado':   { msg: 'Comentario agregado correctamente',         type: 'success' },
    'checklist-creada':    { msg: 'Checklist creado correctamente',            type: 'success' },
    'checklist-item-agregado': { msg: 'Tarea agregada al checklist',           type: 'success' },
    'adjunto-subido':      { msg: 'Archivo(s) subido(s) correctamente',       type: 'success' },
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
  // Drag & drop de archivos + preview
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

  function setupAdjuntosDropzone() {
    document.querySelectorAll('.adjuntos-dropzone').forEach(function (drop) {
      if (drop.dataset.dzInit === '1') return;
      drop.dataset.dzInit = '1';
      const ticketId = drop.getAttribute('data-ticket-id');
      const fileInput = document.getElementById('adjunto-file-' + ticketId);
      const preview = document.getElementById('adjuntos-preview-' + ticketId);
      const info = document.getElementById('adjuntos-info-' + ticketId);
      if (!fileInput) return;

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
          const dt = new DataTransfer();
          for (let i = 0; i < files.length; i++) dt.items.add(files[i]);
          fileInput.files = dt.files;
        } catch (err) {
          showToast('Tu navegador no soporta multi-drop. Selecciona manualmente.', 'info');
        }
        updatePreview();
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
          '<button type="button" data-md-tab="write" class="md-tab px-2 py-0.5 text-[11px] font-medium rounded bg-white text-slate-700 border border-slate-200">Escribir</button>' +
          '<button type="button" data-md-tab="preview" class="md-tab px-2 py-0.5 text-[11px] font-medium rounded text-slate-500 hover:text-slate-700">Vista previa</button>' +
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
      setActive('write');
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
