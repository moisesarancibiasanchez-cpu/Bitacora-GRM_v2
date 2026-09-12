/**
 * Command Palette: Búsqueda global (Ctrl/Cmd + K) estilo Trello/Linear/Notion.
 * - Atajo: Ctrl+K (Win/Linux) o Cmd+K (Mac) abre/cierra.
 * - Escape cierra.
 * - Click fuera cierra.
 * - Carga resultados de /api/v1/buscar?q=...
 * - Teclado: ↑/↓ navega, Enter abre.
 */
(function () {
  'use strict';

  const ROOT_ID = 'command-palette-root';
  const TRIGGER_ID = 'command-palette-trigger';

  function getRoot() {
    return document.getElementById(ROOT_ID);
  }

  function open() {
    const root = getRoot();
    if (!root) return;
    root.classList.remove('hidden');
    root.innerHTML = renderShell('');
    setTimeout(() => {
      const inp = document.getElementById('cp-input');
      if (inp) inp.focus();
    }, 30);
    document.addEventListener('keydown', onKeydown);
  }

  function close() {
    const root = getRoot();
    if (!root) return;
    root.classList.add('hidden');
    root.innerHTML = '';
    document.removeEventListener('keydown', onKeydown);
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }

  function renderShell(query) {
    return `
      <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" data-cp-backdrop></div>
      <div class="relative mx-auto mt-20 w-full max-w-2xl px-4">
        <div class="bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
          <div class="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
            <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-4.35-4.35M11 19a8 8 0 100-16 8 8 0 000 16z"/>
            </svg>
            <input id="cp-input" type="text" autocomplete="off" spellcheck="false"
                   placeholder="Buscar tickets, tableros, usuarios, etiquetas…"
                   class="flex-1 outline-none bg-transparent text-sm text-slate-700 placeholder-slate-400"
                   value="${escapeHtml(query)}" />
            <kbd class="text-[10px] font-mono px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-slate-500">ESC</kbd>
          </div>
          <div id="cp-results" class="max-h-96 overflow-y-auto">
            <div class="p-6 text-center text-sm text-slate-400">
              Escribe para buscar globalmente
            </div>
          </div>
          <div class="flex items-center justify-between px-3 py-2 border-t border-slate-100 bg-slate-50 text-[11px] text-slate-500">
            <div class="flex items-center gap-3">
              <span><kbd class="font-mono">↑</kbd>/<kbd class="font-mono">↓</kbd> navegar</span>
              <span><kbd class="font-mono">⏎</kbd> abrir</span>
              <span><kbd class="font-mono">Esc</kbd> cerrar</span>
            </div>
            <span>Bitácora GRM</span>
          </div>
        </div>
      </div>
    `;
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  let currentResults = [];
  let selectedIndex = 0;

  async function search(q) {
    if (!q || q.length < 1) {
      document.getElementById('cp-results').innerHTML =
        '<div class="p-6 text-center text-sm text-slate-400">Escribe para buscar globalmente</div>';
      currentResults = [];
      return;
    }
    try {
      const r = await fetch(`/api/v1/buscar?q=${encodeURIComponent(q)}&limite=8`, {
        headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
      });
      if (!r.ok) throw new Error('Error en búsqueda');
      const data = await r.json();
      currentResults = collectResults(data);
      selectedIndex = 0;
      renderResults(currentResults);
    } catch (e) {
      document.getElementById('cp-results').innerHTML =
        `<div class="p-6 text-center text-sm text-red-500">Error: ${escapeHtml(e.message)}</div>`;
    }
  }

  function collectResults(data) {
    const out = [];
    const tipos = [
      ['tickets', 'Ticket', '🎫', '/tickets'],
      ['espacios', 'Espacio', '🏢', '/espacios'],
      ['tableros', 'Tablero', '📋', '/tableros'],
      ['usuarios', 'Usuario', '👤', null],
      ['etiquetas', 'Etiqueta', '🏷️', null],
    ];
    for (const [key, label, icon, fallbackUrl] of tipos) {
      const arr = data[key] || [];
      for (const r of arr) {
        out.push({
          tipo: label,
          icono: icon,
          titulo: r.titulo || '(sin título)',
          subtitulo: r.subtitulo || '',
          url: r.url || fallbackUrl || '#',
        });
      }
    }
    return out;
  }

  function renderResults(results) {
    const cont = document.getElementById('cp-results');
    if (!cont) return;
    if (results.length === 0) {
      cont.innerHTML = '<div class="p-6 text-center text-sm text-slate-400">Sin resultados</div>';
      return;
    }
    cont.innerHTML = results.map((r, i) => `
      <a href="${escapeHtml(r.url)}" data-idx="${i}"
         class="cp-item flex items-center gap-3 px-4 py-2 text-sm ${i === selectedIndex ? 'bg-indigo-50' : 'hover:bg-slate-50'}">
        <span class="w-7 text-center">${r.icono}</span>
        <span class="flex-1 min-w-0">
          <span class="block text-slate-800 truncate">${escapeHtml(r.titulo)}</span>
          <span class="block text-[11px] text-slate-500 truncate">${escapeHtml(r.subtitulo)}</span>
        </span>
        <span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">${escapeHtml(r.tipo)}</span>
      </a>
    `).join('');
    // Scroll selected into view
    const sel = cont.querySelector(`[data-idx="${selectedIndex}"]`);
    if (sel) sel.scrollIntoView({ block: 'nearest' });
  }

  function onInputKey(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (currentResults.length === 0) return;
      selectedIndex = (selectedIndex + 1) % currentResults.length;
      renderResults(currentResults);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (currentResults.length === 0) return;
      selectedIndex = (selectedIndex - 1 + currentResults.length) % currentResults.length;
      renderResults(currentResults);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const sel = currentResults[selectedIndex];
      if (sel && sel.url) {
        window.location.href = sel.url;
      }
    }
  }

  // === Wire up ===
  document.addEventListener('DOMContentLoaded', () => {
    const trigger = document.getElementById(TRIGGER_ID);
    if (trigger) {
      trigger.addEventListener('click', open);
    }
    // Atajo global Ctrl/Cmd + K
    document.addEventListener('keydown', (e) => {
      const isK = e.key === 'k' || e.key === 'K';
      if (isK && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        const root = getRoot();
        if (root && !root.classList.contains('hidden')) {
          close();
        } else {
          open();
        }
      }
    });
    // Delegated events
    document.addEventListener('click', (e) => {
      if (e.target && e.target.hasAttribute && e.target.hasAttribute('data-cp-backdrop')) {
        close();
      }
    });
    document.addEventListener('input', (e) => {
      if (e.target && e.target.id === 'cp-input') {
        clearTimeout(window._cpDebounce);
        window._cpDebounce = setTimeout(() => search(e.target.value), 180);
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.target && e.target.id === 'cp-input') {
        onInputKey(e);
      }
    });
  });
})();
