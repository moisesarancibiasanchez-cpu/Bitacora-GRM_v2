/**
 * Configuracion de Tailwind CSS (compilacion local, sin CDN).
 *
 * Contexto
 * --------
 * Antes, la aplicacion cargaba Tailwind desde el CDN oficial
 * (`https://cdn.tailwindcss.com`), que compila las utilidades EN EL
 * NAVEGADOR. Eso hacia que:
 *
 *   1. la UI dependia de una red externa (si el CDN tardaba o estaba
 *      bloqueado, la pagina se quedaba SIN ESTILOS: tarjetas gigantes,
 *      columna sin maquetar y el Kanban sin drag & drop), y
 *   2. el navegador pagaba el coste de compilar las clases en cada carga.
 *
 * Ahora el CSS se compila ANTES de publicar y se sirve desde
 * `/static/css/tailwind.css`, igual que ya se hacia con HTMX.
 *
 * Como regenerarlo (no hace falta en cada despliegue)
 * ---------------------------------------------------
 *   1. Descargar el CLI oficial de Tailwind v3 para Windows:
 *        https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-windows-x64.exe
 *   2. Compilar:
 *        tailwindcss-windows-x64.exe -c tailwind.config.js ^
 *          -i app/static/css/tailwind.src.css ^
 *          -o app/static/css/tailwind.css --minify
 *
 * El resultado se versiona en el repositorio: el despliegue no necesita
 * Node, npm ni ningun paso de construccion.
 */
module.exports = {
  content: [
    // Todo el codigo Python de la aplicacion: las plantillas se generan
    // desde Python (app/templates/**/*.py) y hay markup que se arma en
    // otras capas (app/core/resultado_pruebas.py, app/api/**, ...).
    './app/**/*.py',
    // Plantillas HTML.
    './app/**/*.html',
    // Clases que se aplican desde JavaScript (classList.add/remove).
    './app/static/js/**/*.js',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
