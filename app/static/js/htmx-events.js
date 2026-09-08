/**
 * Manejador de eventos HTMX: muestra toasts y notifica al usuario.
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

  document.body.addEventListener('ticket-error', (evt) => {
    if (window.showToast) {
      window.showToast(evt.detail.message || 'Operación no permitida', 'error');
    }
  });
})();
