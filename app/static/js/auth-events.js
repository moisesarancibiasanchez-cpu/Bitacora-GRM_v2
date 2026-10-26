/**
 * auth-events.js
 * Listeners globales para eventos emitidos por el backend tras acciones
 * de autenticación / cambio de contraseña. Se incluye UNA SOLA VEZ desde
 * base.html, de modo que los handlers quedan registrados al cargar la
 * página (en lugar de cada vez que HTMX inyecta un modal vía innerHTML,
 * caso en el cual los <script> inline NO se ejecutan).
 *
 * Convenciones:
 *   - El backend emite cabeceras `HX-Trigger: <nombre-evento>` (HTMX 1.x)
 *     que disparan un CustomEvent同名 en `document.body`.
 *   - `window.showToast(msg, type, ms)` está definido en htmx-events.js
 *     y se reutiliza aquí si está disponible.
 */
(function () {
  'use strict';

  /* Pequeño helper local de toast por si showToast aún no estuviera
     registrado (orden de carga de <script>). */
  function _fallbackToast(message, type) {
    try {
      var container = document.getElementById('toast-container');
      if (!container) return;
      var colors = {
        success: 'bg-emerald-600 text-white',
        error:   'bg-red-600 text-white',
        warning: 'bg-amber-600 text-white',
        info:    'bg-indigo-600 text-white'
      };
      var cls = colors[type] || colors.info;
      var el = document.createElement('div');
      el.className = 'pointer-events-auto ' + cls + ' text-xs font-semibold px-4 py-2 rounded-md shadow-lg animate-fade-in';
      el.textContent = message;
      container.appendChild(el);
      setTimeout(function () { el.remove(); }, 4000);
    } catch (_) { /* noop */ }
  }

  function _toast(msg, type) {
    if (window.showToast) {
      try { window.showToast(msg, type || 'success', 4000); return; } catch (_) {}
    }
    _fallbackToast(msg, type);
  }

  function _closeModal(delayMs) {
    setTimeout(function () {
      var root = document.getElementById('modal-root');
      if (root) root.innerHTML = '';
    }, delayMs || 400);
  }

  /* =========================================================================
     EVENTO: cambio-password-ok
     Disparado por POST /api/v1/auth/cambiar-password-form (auto-servicio).
     El backend envía `HX-Trigger-Detalle: {"message": "..."}` con el
     mensaje a mostrar.
     ========================================================================= */
  document.body.addEventListener('cambio-password-ok', function (evt) {
    var msg = 'Contraseña actualizada correctamente.';
    try {
      var detail = (evt && evt.detail) || {};
      // HTMX 1.x expone el payload vía detail o en xhr.getResponseHeader
      if (detail.message) {
        msg = detail.message;
      } else if (detail.xhr && detail.xhr.getResponseHeader) {
        var raw = detail.xhr.getResponseHeader('HX-Trigger-Detalle') ||
                  detail.xhr.getResponseHeader('HX-Trigger-detalle');
        if (raw) {
          try { var parsed = JSON.parse(raw); if (parsed && parsed.message) msg = parsed.message; } catch (_) {}
        }
      }
    } catch (_) { /* noop */ }
    _toast(msg, 'success');
    _closeModal(500);
  });

  /* =========================================================================
     EVENTO: cambio-password-admin-ok
     Disparado por POST /api/v1/usuarios/{id}/reset-password-form
     cuando un Administrador resetea la contraseña de otro usuario.
     ========================================================================= */
  document.body.addEventListener('cambio-password-admin-ok', function (evt) {
    var msg = 'Contraseña actualizada correctamente.';
    try {
      var detail = (evt && evt.detail) || {};
      if (detail.message) msg = detail.message;
    } catch (_) {}
    _toast(msg, 'success');
    _closeModal(500);
  });

  /* =========================================================================
     EVENTO: cambio-password-admin-error
     Disparado por el endpoint admin cuando falla (4xx) — además del
     fragmento HTML de error que HTMX pinta en el target.
     ========================================================================= */
  document.body.addEventListener('cambio-password-admin-error', function (evt) {
    var msg = 'No se pudo cambiar la contraseña.';
    try {
      var detail = (evt && evt.detail) || {};
      if (detail.message) msg = detail.message;
    } catch (_) {}
    _toast(msg, 'error', 5000);
  });
})();
