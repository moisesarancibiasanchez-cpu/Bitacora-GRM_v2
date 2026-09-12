/**
 * image-preview.js
 *
 * Lightbox accesible y reutilizable para previsualizar imágenes.
 *
 * Activación:
 *   - Atributo data-preview-image en cualquier <img> (o contenedor <a> que lo envuelva).
 *   - Si la imagen está dentro de <a data-preview-image>, se abre el lightbox en lugar de navegar.
 *   - Cualquier <img> dentro de #modal-root se trata como previsualizable si su src termina
 *     en una extensión de imagen conocida (.png/.jpg/.jpeg/.gif/.webp/.bmp/.svg/.avif).
 *
 * API expuesta:
 *   - window.BitacoraImagePreview.open(src, { title, downloadUrl })
 *   - window.BitacoraImagePreview.close()
 *   - window.BitacoraImagePreview.attach(root)   -> procesa nuevos nodos HTMX
 */
(function () {
  'use strict';

  var IMG_EXT = /\.(png|jpe?g|gif|webp|bmp|svg|avif|ico)(\?.*)?$/i;

  function isImageSrc(src) {
    if (!src) return false;
    return IMG_EXT.test(src);
  }

  function buildOverlay(src, opts) {
    opts = opts || {};
    var overlay = document.createElement('div');
    overlay.className = 'bitacora-lightbox fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/85 backdrop-blur-sm p-4 cursor-zoom-out';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', opts.title || 'Vista previa de imagen');
    overlay.dataset.lightbox = '1';

    var box = document.createElement('div');
    box.className = 'relative max-w-[95vw] max-h-[92vh] flex flex-col items-center gap-2 cursor-default';

    var img = document.createElement('img');
    img.src = src;
    img.alt = opts.title || 'Imagen';
    img.className = 'max-w-[95vw] max-h-[85vh] object-contain rounded-md shadow-2xl bg-white';
    img.addEventListener('click', function (e) { e.stopPropagation(); });

    var bar = document.createElement('div');
    bar.className = 'flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800/70 text-white text-xs';

    var label = document.createElement('span');
    label.className = 'truncate max-w-[60vw]';
    label.textContent = opts.title || 'Imagen';

    var download = document.createElement('a');
    download.href = opts.downloadUrl || src;
    download.target = '_blank';
    download.rel = 'noopener';
    download.className = 'px-2 py-1 rounded bg-white/10 hover:bg-white/20 font-medium inline-flex items-center gap-1';
    download.innerHTML = '<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg> Descargar';

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'px-2 py-1 rounded bg-white/10 hover:bg-white/20 font-medium';
    close.textContent = 'Cerrar';
    close.addEventListener('click', function (e) {
      e.stopPropagation();
      closeOverlay();
    });

    bar.appendChild(label);
    if (opts.downloadUrl || src) bar.appendChild(download);
    bar.appendChild(close);

    box.appendChild(img);
    box.appendChild(bar);
    overlay.appendChild(box);

    overlay.addEventListener('click', function (e) {
      // Click fuera de la imagen cierra
      if (e.target === overlay) closeOverlay();
    });

    return overlay;
  }

  var activeOverlay = null;

  function open(src, opts) {
    if (!src) return;
    closeOverlay();
    activeOverlay = buildOverlay(src, opts);
    document.body.appendChild(activeOverlay);
    // Bloquear scroll del body mientras el lightbox está abierto
    document.documentElement.style.overflow = 'hidden';
    document.addEventListener('keydown', onKeydown);
  }

  function closeOverlay() {
    if (activeOverlay && activeOverlay.parentNode) {
      activeOverlay.parentNode.removeChild(activeOverlay);
    }
    activeOverlay = null;
    document.documentElement.style.overflow = '';
    document.removeEventListener('keydown', onKeydown);
  }

  function onKeydown(e) {
    if (e.key === 'Escape') closeOverlay();
  }

  function attach(root) {
    root = root || document;

    // 1) Interceptar <a data-preview-image> o <img data-preview-image>
    var explicitAnchors = root.querySelectorAll('a[data-preview-image], img[data-preview-image]');
    explicitAnchors.forEach(function (el) {
      if (el.dataset.previewBound === '1') return;
      el.dataset.previewBound = '1';
      var src = el.dataset.previewSrc || el.getAttribute('href') || el.getAttribute('src');
      var title = el.dataset.previewTitle || el.getAttribute('title') || (el.getAttribute('alt') || '');
      if (el.tagName === 'A') {
        el.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          open(src, { title: title, downloadUrl: el.getAttribute('href') });
        });
      } else {
        el.style.cursor = 'zoom-in';
        el.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          open(src, { title: title, downloadUrl: src });
        });
      }
    });

    // 2) Cualquier <img> dentro de modal-root o con data-bitacora-preview se vuelve preview-able
    var implicitImages = root.querySelectorAll('#modal-root img, [data-bitacora-preview] img');
    implicitImages.forEach(function (img) {
      if (img.dataset.previewBound === '1') return;
      if (!isImageSrc(img.getAttribute('src') || '')) return;
      img.dataset.previewBound = '1';
      img.style.cursor = 'zoom-in';
      img.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        open(img.getAttribute('src'), {
          title: img.getAttribute('alt') || img.getAttribute('title') || '',
          downloadUrl: img.getAttribute('src'),
        });
      });
    });
  }

  // API pública
  window.BitacoraImagePreview = {
    open: open,
    close: closeOverlay,
    attach: attach,
    isImageSrc: isImageSrc,
  };

  // Auto-attach cuando el DOM está listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { attach(document); });
  } else {
    attach(document);
  }

  // Re-attach cuando HTMX intercambia contenido
  document.body.addEventListener('htmx:afterSwap', function () {
    setTimeout(function () { attach(document); }, 0);
  });
  document.body.addEventListener('htmx:load', function () {
    setTimeout(function () { attach(document); }, 0);
  });
  document.body.addEventListener('htmx:afterOnLoad', function () {
    setTimeout(function () { attach(document); }, 0);
  });
})();
