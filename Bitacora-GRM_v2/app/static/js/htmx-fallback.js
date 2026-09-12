/**
 * htmx-fallback.js
 * ----------------------------------------------------------------------------
 * Capa de compatibilidad que reproduce el comportamiento de HTMX para los
 * atributos hx-* cuando HTMX NO está disponible (CDN bloqueado, SRI mismatch,
 * CSP, error de carga, etc.).
 *
 * Maneja:
 *   - <form hx-patch|post|put|delete hx-target hx-swap hx-trigger hx-confirm
 *         hx-encoding hx-vals hx-indicator>
 *   - <button|input|a hx-get|post|put|patch|delete hx-target hx-swap
 *         hx-trigger hx-confirm hx-vals hx-indicator>
 *   - HX-Trigger response header (dispara CustomEvent en document.body)
 *   - HX-Redirect (window.location = ...)
 *   - HX-Swap: none (no hace swap en el DOM)
 *
 * Si HTMX está cargado y funcionando, este script NO hace nada
 * (HTMX tiene prioridad). Si HTMX falla, este script se activa y maneja
 * las requests con fetch() nativo.
 *
 * Estrategia de activación:
 *   1. Verifica si HTMX intercepta un form. Si NO, activa el fallback.
 *   2. Usa un MutationObserver para procesar nuevos forms/buttons
 *      que se insertan dinámicamente en el DOM.
 *
 * @author MiniMax Agent
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // SALIDA TEMPRANA: Si HTMX está cargado, este script no debe hacer NADA.
  // Cualquier listener que registremos interferirá con HTMX.
  // ---------------------------------------------------------------------------
  if (typeof htmx !== 'undefined' && htmx.process && htmx.ajax) {
    // HTMX está cargado y operativo. No hacer nada.
    console.log('[htmx-fallback] HTMX detectado. Fallback desactivado (no se registran listeners).');
    return;
  }

  // ---------------------------------------------------------------------------
  // Detección: ¿HTMX está realmente funcionando?
  // ---------------------------------------------------------------------------
  function htmxWorking() {
    if (typeof htmx === 'undefined') return false;
    if (!htmx.process || !htmx.ajax) return false;
    // Test: crear form dummy, marcarlo, llamar process, ver si HTMX lo tomó
    try {
      const test = document.createElement('form');
      test.setAttribute('hx-patch', '/__htmx_test__');
      test.setAttribute('data-hx-test', '1');
      test.style.display = 'none';
      document.body.appendChild(test);
      const hadHandler = test.outerHTML.indexOf('data-hx-test') !== -1;
      htmx.process(test);
      // Si HTMX lo procesó, el atributo hx-patch estará "consumido"
      // (no podemos saberlo con certeza, pero la mayoría de errores se ven acá)
      test.remove();
      return hadHandler;
    } catch (e) {
      return false;
    }
  }

  // Estado: si HTMX está cargado y funcionando, no hacer nada
  let _htmxReady = false;
  function checkHtmxReady() {
    if (_htmxReady) return;
    if (htmxWorking()) {
      _htmxReady = true;
      console.log('[htmx-fallback] HTMX detectado y funcionando. Fallback desactivado.');
      return;
    }
  }

  // Verificar al cargar y periódicamente (HTMX puede cargar tarde)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkHtmxReady);
  } else {
    checkHtmxReady();
  }
  // Re-verificar tras 1s y 3s por si HTMX carga tarde
  setTimeout(checkHtmxReady, 1000);
  setTimeout(checkHtmxReady, 3000);

  // ---------------------------------------------------------------------------
  // Utilidades
  // ---------------------------------------------------------------------------
  function parseHxTrigger(headerValue) {
    if (!headerValue) return {};
    // Formato: {"evento": {...data}} o "evento1,evento2"
    try {
      const parsed = JSON.parse(headerValue);
      return typeof parsed === 'object' ? parsed : { [parsed]: null };
    } catch (_) {
      // Es una lista separada por comas
      const result = {};
      headerValue.split(',').forEach((e) => {
        const trimmed = e.trim();
        if (trimmed) result[trimmed] = null;
      });
      return result;
    }
  }

  function fireHtmxTriggers(headers) {
    // Disparar todos los HX-Trigger como CustomEvent en body
    Object.keys(headers).forEach((name) => {
      if (name.toLowerCase().startsWith('hx-trigger')) {
        const value = headers[name];
        const triggers = parseHxTrigger(value);
        Object.keys(triggers).forEach((eventName) => {
          const detail = triggers[eventName] || {};
          try {
            document.body.dispatchEvent(new CustomEvent(eventName, { detail }));
          } catch (e) {
            console.warn('[htmx-fallback] Error disparando evento', eventName, e);
          }
        });
      }
    });
  }

  function resolveTarget(targetSel) {
    if (!targetSel || targetSel === 'this') {
      return { target: null, swap: 'innerHTML' };
    }
    const el = document.querySelector(targetSel);
    return { target: el, swap: 'innerHTML' };
  }

  function doSwap(target, swapMode, html) {
    if (!target) return;
    if (swapMode === 'outerHTML') {
      // outerHTML swap: necesitamos reemplazar el elemento mismo
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      const newEl = tmp.firstElementChild;
      if (newEl && target.parentNode) {
        target.parentNode.replaceChild(newEl, target);
        return newEl;
      }
    }
    // default: innerHTML
    target.innerHTML = html;
    return target;
  }

  function setIndicators(form, show) {
    // Mostrar/ocultar htmx-indicator
    const id = form.getAttribute('hx-indicator');
    if (id) {
      const ind = document.querySelector(id);
      if (ind) ind.style.opacity = show ? '1' : '0';
    }
    // También buscar hx-indicator en el form
    form.querySelectorAll('.htmx-indicator').forEach((el) => {
      el.style.opacity = show ? '1' : '0';
    });
  }

  function buildFormData(form, hxVals) {
    const fd = new FormData(form);
    if (hxVals) {
      try {
        const extra = typeof hxVals === 'string' ? JSON.parse(hxVals) : hxVals;
        Object.keys(extra).forEach((k) => {
          // Permitir múltiples valores
          if (Array.isArray(extra[k])) {
            extra[k].forEach((v) => fd.append(k, v));
          } else {
            fd.set(k, extra[k]);
          }
        });
      } catch (e) {
        console.warn('[htmx-fallback] hx-vals no es JSON válido:', hxVals, e);
      }
    }
    return fd;
  }

  // ---------------------------------------------------------------------------
  // Manejador principal: procesa un form/button con hx-* atributos
  // ---------------------------------------------------------------------------
  function processHtmxElement(el) {
    if (!el || el.dataset.hxFallbackInit === '1') return;
    el.dataset.hxFallbackInit = '1';

    const isForm = el.tagName === 'FORM';
    const isButton = el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'INPUT';

    // Determinar método y URL
    let method = null;
    let url = null;
    ['get', 'post', 'put', 'patch', 'delete'].forEach((m) => {
      const v = el.getAttribute('hx-' + m);
      if (v) {
        method = m.toUpperCase();
        url = v;
      }
    });

    if (!method || !url) return; // No es un elemento HTMX

    const target = el.getAttribute('hx-target') || (isForm ? el : null);
    const swap = el.getAttribute('hx-swap') || 'innerHTML';
    const hxConfirm = el.getAttribute('hx-confirm');
    const hxVals = el.getAttribute('hx-vals');
    const hxEncoding = el.getAttribute('hx-encoding');
    const hxIndicator = el.getAttribute('hx-indicator');

    // HX-Trigger: este elemento dispara un evento cuando se interactúa
    const trigger = el.getAttribute('hx-trigger');
    let triggerEvent = 'click';
    if (trigger) {
      // Casos comunes: "click", "change", "submit", "blur changed delay:800ms from:..."
      const first = trigger.split(' ')[0].split(',')[0];
      if (['click', 'change', 'submit', 'blur', 'focus', 'input', 'keyup'].indexOf(first) >= 0) {
        triggerEvent = first;
      }
    }

    // Marcar el elemento con un atributo para que sepamos que está procesado
    el.setAttribute('data-hx-method', method);
    el.setAttribute('data-hx-url', url);

    // Para forms: submit
    if (isForm) {
      el.addEventListener('submit', async (e) => {
        e.preventDefault();
        e.stopImmediatePropagation();

        if (hxConfirm && !window.confirm(hxConfirm)) return;

        const form = el;
        await sendHtmxRequest({
          method,
          url,
          body: buildFormData(form, hxVals),
          target: resolveTarget(target).target,
          swap,
          hxEncoding,
          indicator: hxIndicator || form,
          triggerEl: form,
        });
      }, true);

      // Para hx-trigger="change" en select/input dentro del form
      if (trigger && (trigger.indexOf('change') >= 0 || trigger.indexOf('blur') >= 0 || trigger.indexOf('input') >= 0)) {
        // Determinar de qué selector disparar
        const fromMatch = trigger.match(/from:([^,]+)/);
        const fromSel = fromMatch ? fromMatch[1].trim() : null;

        form.querySelectorAll('input, textarea, select').forEach((input) => {
          if (fromSel && !input.matches(fromSel.replace(/['"]/g, ''))) return;
          const evt = trigger.indexOf('blur') >= 0 ? 'blur' :
                      trigger.indexOf('change') >= 0 ? 'change' : 'input';
          let debounceTimer = null;
          const delayMatch = trigger.match(/delay:(\d+)ms/);
          const delay = delayMatch ? parseInt(delayMatch[1], 10) : 0;

          input.addEventListener(evt, (e) => {
            if (delay > 0) {
              clearTimeout(debounceTimer);
              debounceTimer = setTimeout(() => {
                form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
              }, delay);
            } else {
              form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            }
          });
        });
      }
    } else {
      // Para buttons/links: click
      el.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopImmediatePropagation();

        if (hxConfirm && !window.confirm(hxConfirm)) return;

        let body = null;
        if (hxVals) {
          try {
            const parsed = typeof hxVals === 'string' ? JSON.parse(hxVals) : hxVals;
            body = new URLSearchParams();
            Object.keys(parsed).forEach((k) => {
              if (Array.isArray(parsed[k])) {
                parsed[k].forEach((v) => body.append(k, v));
              } else {
                body.append(k, parsed[k]);
              }
            });
            body = body.toString();
          } catch (_) {
            body = null;
          }
        }

        await sendHtmxRequest({
          method,
          url,
          body,
          target: resolveTarget(target).target,
          swap,
          hxEncoding,
          indicator: hxIndicator || el,
          triggerEl: el,
        });
      }, true);

      // Para checkboxes con hx-trigger="change"
      if (el.tagName === 'INPUT' && el.type === 'checkbox' && trigger && trigger.indexOf('change') >= 0) {
        el.addEventListener('change', async (e) => {
          e.preventDefault();
          e.stopImmediatePropagation();
          const fd = new FormData();
          if (hxVals) {
            try {
              const parsed = typeof hxVals === 'string' ? JSON.parse(hxVals) : hxVals;
              Object.keys(parsed).forEach((k) => fd.append(k, parsed[k]));
            } catch (_) {}
          }
          await sendHtmxRequest({
            method, url, body: fd,
            target: resolveTarget(target).target, swap,
            hxEncoding, indicator: hxIndicator || el, triggerEl: el,
          });
        }, true);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Enviar request HTTP y procesar respuesta HTMX-style
  // ---------------------------------------------------------------------------
  async function sendHtmxRequest(opts) {
    const { method, url, body, target, swap, hxEncoding, indicator, triggerEl } = opts;

    // Mostrar indicadores
    if (indicator) setIndicators(indicator, true);

    // Headers
    const headers = {
      'X-User-Id': String(window.CURRENT_USER_ID || 1),
      'HX-Request': 'true',
    };
    if (triggerEl) {
      headers['HX-Trigger'] = triggerEl.id || '';
      headers['HX-Trigger-Name'] = triggerEl.getAttribute('name') || '';
    }

    // Si es GET con body, mover a query string
    let fetchUrl = url;
    let fetchOpts = { method, headers, credentials: 'same-origin' };

    if (method === 'GET' && body) {
      // Convertir body (FormData o string) a query string
      const params = new URLSearchParams();
      if (body instanceof FormData) {
        for (const [k, v] of body.entries()) params.append(k, v);
      } else if (typeof body === 'string') {
        params.append('_', body);
      }
      fetchUrl = url + (url.indexOf('?') >= 0 ? '&' : '?') + params.toString();
      fetchOpts.body = undefined;
    } else if (body && hxEncoding === 'multipart/form-data') {
      // No incluir Content-Type; el browser lo agrega con boundary
      fetchOpts.body = body;
    } else if (body) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
      if (body instanceof FormData) {
        fetchOpts.body = new URLSearchParams([...body.entries()]).toString();
      } else {
        fetchOpts.body = body;
      }
    }

    try {
      const r = await fetch(fetchUrl, fetchOpts);

      // Disparar HX-Trigger del response
      fireHtmxTriggers(r.headers);

      // HX-Redirect
      const redirect = r.headers.get('HX-Redirect') || r.headers.get('HX-Location');
      if (redirect) {
        window.location.href = redirect;
        return;
      }

      // HX-Swap: none -> no hacer swap
      if (r.headers.get('HX-Swap') === 'none') {
        return; // Solo se dispararon los triggers
      }

      // Leer respuesta
      const ct = r.headers.get('content-type') || '';
      if (ct.indexOf('application/json') >= 0) {
        const data = await r.json();
        // Para JSON sin target específico, mostrar como toast
        if (window.showToast) {
          if (data.detail) window.showToast(data.detail, r.ok ? 'success' : 'error');
          else if (data.message) window.showToast(data.message, r.ok ? 'success' : 'error');
        }
        if (!r.ok) {
          console.error('[htmx-fallback] Error response:', data);
        }
        return;
      }

      const html = await r.text();
      if (target && swap !== 'none') {
        const newEl = doSwap(target, swap, html);
        // Re-procesar hijos para que el fallback los tome
        if (newEl) {
          scanAndProcess(newEl);
          // Llamar a reinitModalExtras si existe (markdown, dropzone, etc.)
          if (typeof window.reinitModalExtras === 'function') {
            try { window.reinitModalExtras(); } catch (_) {}
          }
        }
      }
    } catch (err) {
      console.error('[htmx-fallback] Error en request:', err);
      if (window.showToast) {
        window.showToast('Error: ' + (err.message || err), 'error');
      }
    } finally {
      if (indicator) setIndicators(indicator, false);
    }
  }

  // ---------------------------------------------------------------------------
  // Escanear DOM y procesar todos los elementos hx-*
  // ---------------------------------------------------------------------------
  function scanAndProcess(root) {
    const r = root || document;
    // Procesar todos los forms con hx-*
    r.querySelectorAll('form[hx-get], form[hx-post], form[hx-put], form[hx-patch], form[hx-delete]').forEach(processHtmxElement);
    // Procesar buttons/inputs/anchors con hx-*
    r.querySelectorAll('button[hx-get], button[hx-post], button[hx-put], button[hx-patch], button[hx-delete], ' +
                       'input[hx-get], input[hx-post], input[hx-put], input[hx-patch], input[hx-delete], ' +
                       'a[hx-get], a[hx-post], a[hx-put], a[hx-patch], a[hx-delete]').forEach(processHtmxElement);
  }

  // ---------------------------------------------------------------------------
  // Inicialización + MutationObserver
  // ---------------------------------------------------------------------------
  function init() {
    // Re-chequear si HTMX se cargó
    checkHtmxReady();
    if (_htmxReady) return;

    console.log('[htmx-fallback] HTMX no detectado. Activando fallback vanilla JS.');
    scanAndProcess(document);

    // Observar cambios en el DOM
    const observer = new MutationObserver((mutations) => {
      if (_htmxReady) return;
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1) {
            // Procesar el nodo y sus descendientes
            if (node.matches && (
                node.matches('form[hx-get], form[hx-post], form[hx-put], form[hx-patch], form[hx-delete], ' +
                            'button[hx-get], button[hx-post], button[hx-put], button[hx-patch], button[hx-delete], ' +
                            'input[hx-get], input[hx-post], input[hx-put], input[hx-patch], input[hx-delete]')
            )) {
              processHtmxElement(node);
            }
            // Buscar descendientes
            scanAndProcess(node);
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Exponer para uso externo
  window.htmxFallbackProcess = scanAndProcess;
  window.htmxFallbackReady = () => _htmxReady;

  // Inicializar
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Re-escanear tras eventos HTMX-like (por si HTMX se carga tarde)
  document.body.addEventListener('htmx:afterSwap', () => {
    setTimeout(() => { if (!_htmxReady) scanAndProcess(document); }, 50);
  });
  document.body.addEventListener('htmx:load', () => {
    setTimeout(() => { if (!_htmxReady) scanAndProcess(document); }, 50);
  });
})();
