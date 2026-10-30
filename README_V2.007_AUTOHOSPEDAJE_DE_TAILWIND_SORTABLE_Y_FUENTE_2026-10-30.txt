================================================================================
README V2.007 - AUTOHOSPEDAJE DE LOS RECURSOS: TAILWIND CSS COMPILADO, SORTABLE
Y FUENTE INTER (LA APLICACION DEJA DE DEPENDER DE CUALQUIER CDN)
Proyecto: Bitacora GRM v2
Fecha: 2026-10-30
Rama base: main y release/v2.001 (commit adfb1c1)
Estado: CODIGO LISTO Y VERIFICADO EN LOCAL. PENDIENTE DE DESPLEGUE.
================================================================================

  NOTA SOBRE LA NUMERACION: este documento continua la serie V2 del
  repositorio (V2.002 a V2.006), de modo que el correlativo incremental de
  3 cifras es V2.007. El resto del formato (7 secciones, seccion 0 con el
  parche exacto, apendice A con el diff y seccion 9 con el addendum de
  despliegue) es identico al de los lotes anteriores.

================================================================================
0. PARCHE EXACTO
================================================================================

  0.1 FICHEROS INTERVENIDOS

    Nuevos:
      tailwind.config.js                              (configuracion de compilacion)
      app/static/css/tailwind.src.css                 (entrada de la compilacion)
      app/static/css/tailwind.css                     (CSS compilado, 56 KB)
      app/static/css/fonts.css                       (@font-face local de Inter)
      app/static/fonts/inter-latin.woff2              (fuente variable, 48 KB)
      app/static/fonts/inter-latin-ext.woff2          (fuente variable, 85 KB)
      app/static/js/sortable.min.js                   (SortableJS 1.15.2, 44 KB)
      tests/test_v2007_autohospedaje_recursos.py      (nuevo, 12 tests)

    Modificados:
      app/templates/base.html                          (cabecera: recursos locales)

  0.2 app/templates/base.html

        -  <script src="https://cdn.tailwindcss.com"></script>
        -  ...
        -  <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
        +  <!-- Tailwind CSS COMPILADO Y AUTOALOJADO. ... -->
        +  <link rel="stylesheet" href="/static/css/tailwind.css">
        +  ...
        +  <!-- SortableJS autoalojado (v1.15.2) ... -->
        +  <script src="/static/js/sortable.min.js"></script>

        Ademas se elimina el bloque que configuraba Tailwind EN EL
        NAVEGADOR (su equivalente ahora esta en tailwind.config.js):

        -  <script>
        -    tailwind.config = {
        -      theme: {
        -        extend: {
        -          fontFamily: {
        -            sans: ['Inter', 'system-ui', 'sans-serif'],
        -          }
        -        }
        -      }
        -    }
        -  </script>

        y se sustituye la fuente externa por la local:

        -  <link rel="preconnect" href="https://fonts.googleapis.com">
        -  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        +  <link rel="stylesheet" href="/static/css/fonts.css">

  0.3 tailwind.config.js (nuevo)

        +  module.exports = {
        +    content: [
        +      // Todo el codigo Python de la aplicacion: las plantillas se
        +      // generan desde Python y hay markup que se arma en otras capas
        +      // (app/core/resultado_pruebas.py, app/api/**, ...).
        +      './app/**/*.py',
        +      './app/**/*.html',
        +      './app/static/js/**/*.js',
        +    ],
        +    theme: {
        +      extend: {
        +        fontFamily: {
        +          sans: ['Inter', 'system-ui', 'sans-serif'],
        +        },
        +      },
        +    },
        +    plugins: [],
        +  };

        El escaneo cubre TODO el codigo de Python a proposito: el badge de
        "Resultado de Pruebas" (app/core/resultado_pruebas.py) usa la clase
        arbitraria 'py-[1px]', que vive fuera de app/templates/ y se perdia
        con un escaneo mas estrecho.

  0.4 app/static/css/tailwind.src.css (nuevo, entrada de la compilacion)

        +  @tailwind base;
        +  @tailwind components;
        +  @tailwind utilities;

  0.5 COMO SE REGENERA EL CSS (no hace falta en cada despliegue)

        1. Descargar el CLI oficial de Tailwind v3 para Windows:
             https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-windows-x64.exe
        2. Compilar:
             tailwindcss-windows-x64.exe -c tailwind.config.js ^
               -i app/static/css/tailwind.src.css ^
               -o app/static/css/tailwind.css --minify

        El CSS compilado SE VERSIONA en el repositorio: el despliegue no
        necesita Node, npm ni ningun paso de construccion, igual que ya
        ocurria con HTMX.

  0.6 app/static/css/fonts.css y app/static/fonts/*.woff2 (nuevos)

        La fuente Inter se autoaloja en dos ficheros (subconjuntos latin y
        latin-ext). Son la fuente VARIABLE, asi que con dos ficheros cubren
        todos los pesos (400/500/600/700):

        +  @font-face {
        +    font-family: 'Inter';
        +    font-style: normal;
        +    font-weight: 100 900;
        +    font-display: swap;
        +    src: url(/static/fonts/inter-latin.woff2) format('woff2');
        +    unicode-range: U+0000-00FF, ...;
        +  }

  0.7 app/static/js/sortable.min.js (nuevo)

        SortableJS 1.15.2 (MIT), byte a byte el mismo fichero que servia
        cdn.jsdelivr.net:

        /*! Sortable 1.15.2 - MIT | git://github.com/SortableJS/Sortable.git */

  0.8 TESTS NUEVOS (tests/test_v2007_autohospedaje_recursos.py, 12 tests)

        - test_las_plantillas_no_referencian_ningun_cdn_externo
        - test_el_javascript_propio_no_referencia_ningun_cdn_externo
        - test_la_plantilla_base_carga_los_recursos_locales
        - test_el_css_de_tailwind_esta_compilado_y_versionado
        - test_la_entrada_y_la_configuracion_de_tailwind_estan
        - test_sortable_esta_autohospedado
        - test_la_fuente_esta_autohospedada
        - test_los_recursos_autohospedados_se_sirven[/static/css/tailwind.css]
        - test_los_recursos_autohospedados_se_sirven[/static/css/fonts.css]
        - test_los_recursos_autohospedados_se_sirven[/static/js/sortable.min.js]
        - test_los_recursos_autohospedados_se_sirven[/static/fonts/inter-latin.woff2]
        - test_el_html_servido_no_pide_recursos_externos

================================================================================
1. BASE
================================================================================

  Base: commit adfb1c1 (punta de 'main' y de 'release/v2.001'), que contiene
  los lotes V2.005 (1b49fe0 + 354bf20) y V2.006 (9c2ae23 + adfb1c1).

  1.1 EL HECHO REPORTADO (2026-10-30)

    El propietario envio una captura de la pestana Network del navegador con
    la pagina /kanban de produccion abierta. Lo que se ve:

      * la pagina se servia SIN ESTILOS: el logo aparecia enorme, la
        maquetacion estaba rota y la columna del tablero no se veia;
      * en la pestana Network, la peticion a
        ``https://cdn.tailwindcss.com`` figuraba con 0 B y 40,52 s;
      * lo mismo con ``htmx.min.js`` y ``Sortable.min.js``, que aparecian
        a 0 B.

    Es decir: la aplicacion seguia funcionando, pero SIN CSS, porque el
    CDN de Tailwind no respondio.

  1.2 CAUSA RAIZ

    El proyecto cargaba dos recursos de CDN externos, mas la fuente:

      app/templates/base.html:7
        <script src="https://cdn.tailwindcss.com"></script>
      app/templates/base.html:11
        <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
      app/templates/base.html:24-25
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Inter:...">

    El script de ``cdn.tailwindcss.com`` es la version "Play" de Tailwind
    v3, que NO es una hoja de estilos: es un COMPILADOR que se ejecuta en el
    navegador (407 KB) y genera el CSS despues de leer el DOM. Por eso:

      a) la pagina depende de una red externa para tener estilos;
      b) si el CDN tarda, se bloquea o esta en la cache de un proxy, la
         pagina queda sin maquetar (lo que se ve en la captura);
      c) el Kanban pierde el drag & drop, porque SortableJS tampoco
         cargaba.

    Este era el riesgo que el lote V2.006 dejo documentado ("Tailwind y
    SortableJS se cargan solo de CDN... si el CDN falla, toda la UI pierde
    estilos y el Kanban pierde el drag & drop"). Se materializo.

    HTMX ya se autoalojaba desde un lote anterior (``/static/js/htmx.min.js``,
    con el mismo patron que se aplica aqui).

  1.3 MEDICION PREVIA (antes de tocar nada)

    Desde este equipo, los tres recursos externos responden bien y rapido
    (Play CDN 407.279 B en 1,25 s; SortableJS 44.581 B en 0,74 s; Google
    Fonts 916 B en 0,31 s). Es decir, el problema no era el CDN en si, sino
    la dependencia: cualquier red degradada, proxy corporativo, bloqueador
    de anuncios o corte deajar el producto sin interfaz.

  1.4 DECISION TECNICA

    Se compila Tailwind POR DELANTE y se sirve el CSS estatico, igual que
    ya se hacia con HTMX:

      * el navegador descarga 56 KB de CSS en vez de ejecutar un
        compilador de 407 KB;
      * la pagina no hace NINGUNA peticion a un CDN externo;
      * el resultado se versiona en el repositorio, asi que el despliegue
        no necesita Node, npm ni ningun paso de construccion (requisito
        del proyecto: requirements.txt esta fijado y no se anaden
        dependencias).

    Para compilarlo sin Node se usa el CLI BINARIO oficial de Tailwind
    v3.4.17 para Windows (el mismo release que sirve el CDN), de modo que
    las utilidades generadas son las mismas que el CDN producia.

================================================================================
2. CAMBIO UNICO
================================================================================

  OBJETIVO UNICO: que la aplicacion se vea y funcione correctamente SIN
  depender de ninguna red externa.

  2.1 QUE SE PERCIBE AHORA

    a) /kanban, /dashboard, /tickets y el resto de vistas se maquetan
       igual que antes, pero SIN esperar a ningun CDN: los estilos llegan
       con la propia pagina.
    b) El Kanban vuelve a tener drag & drop aunque SortableJS no llegue
       (ahora llega siempre, desde el propio servidor).
    c) La fuente Inter se carga desde el propio servidor.
    d) Si un dia el servidor pierde la conexion con internet, la interfaz
       sigue siendo completamente utilizable.

  2.2 LO QUE NO CAMBIA VISUALMENTE

    El CSS generado es el mismo: se usa el CLI oficial de Tailwind v3.4.17,
    la misma version mayor que servia el CDN, con la misma configuracion de
    tema (familia Inter) y el mismo preflight.

    Se verifico de forma objetiva: se extrajeron las 503 clases DISTINTAS
    que usan las paginas REALES de produccion (/dashboard, /kanban,
    /tickets, calendario, Gantt, timeline, notificaciones y el modal de
    detalle) y se comprobo que el CSS compilado tiene una regla para cada
    una. Las 20 que no aparecen son:

      * 18 clases PROPIAS del proyecto (notif-card, timeline-row,
        comentario-*, empty-column, day-num...), que no tienen CSS ni
        antes ni ahora: son "hooks" para el JavaScript, y su maquetacion
        viene de las utilidades de Tailwind de su mismo atributo class;
      * 'w-4.5' y 'h-4.5', que NO son utilidades validas en Tailwind v3
        (la escala de espaciado no incluye 4.5). El CDN tampoco las
        generaba, asi que el resultado es IDENTICO al actual.

  2.3 PESO NETO

    Antes (por carga de pagina):
      407 KB de compilador de Tailwind (ejecutado en el navegador)
      +  44 KB de SortableJS (CDN)
      +  ~90 KB de fuente Inter (CDN, subconjunto latin)

    Ahora:
       56 KB de CSS compilado
      +  44 KB de SortableJS (local)
      + 133 KB de fuente Inter (local, 2 ficheros variables)
      + 0 peticiones a CDNs

================================================================================
3. QUE NO SE MODIFICO
================================================================================

  - El HTML, la logica y el JavaScript de la aplicacion: no se toca ni una
    linea. El cambio es de la cabecera y de los recursos que se cargan.

  - El resultado visual: el CSS es el mismo que generaba el CDN (mismo CLI,
    misma version, mismo tema). Verificado sobre las clases reales de las
    paginas de produccion.

  - Las clases propias del proyecto (notif-card, timeline-row, comentario-*,
    etc.): siguen sin tener CSS propio, igual que antes. No se ha tocado
    styles.css.

  - Las clases invalidas 'w-4.5' y 'h-4.5' del dashboard: se dejan tal
    cual, para no cambiar el tamano de los iconos (hoy se renderizan al
    tamano por defecto del SVG, y corregirlas los encogeria).

  - requirements.txt: no se anade ninguna dependencia. El CSS compilado se
    versiona, asi que el despliegue no necesita Node ni npm.

  - El resto de los bundles estaticos: htmx.min.js ya estaba autoalojado
    y sigue igual.

  - La demo de onboarding (docs/onboarding-demo, servida en /onboarding):
    tiene su propio CSS en linea y no usaba Tailwind, asi que no le afecta.

  - El historial de releases (README de V1.001 a V2.006): intacto.

  - La migracion 4.9 y el resto de migraciones: sin cambios.

  - NOTA: el script de compilacion de Tailwind NO se versiona (es un binario
    de 40 MB). Se documenta en tailwind.config.js el comando exacto para
    regenerar el CSS. El fichero compilado SI se versiona.

================================================================================
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  - Variables de entorno: NINGUNA nueva.
  - Migraciones: NINGUNA. No hay cambios de esquema ni de datos.
  - Dependencias de Python: NINGUNA. requirements.txt intacto.
  - Node / npm: NINGUNO. El CSS ya viene compilado en el repositorio.
  - Ficheros nuevos que se publican: 6 (CSS compilado, CSS de la fuente,
    2 woff2, SortableJS y el JS de configuracion de Tailwind, que es
    solo para recompilar).
  - Tamano adicional del repositorio: ~280 KB.

  Servicio 'web':    SI hay que desplegarlo. Es quien sirve /static.
  Servicio 'worker': NO requiere cambio funcional (no sirve HTML ni CSS).
                     OPERATIVAMENTE se despliega con el MISMO commit para
                     no dejar los tres servicios desalineados.
  Servicio 'beat':   IGUAL que 'worker'.

  NOTA SOBRE autoDeploy: 'web' tiene autoDeploy sobre 'main' (cada push lo
  redespliega). 'worker' y 'beat' NO lo tienen: hay que desplegarlos a
  mano.

  NOTA SOBRE LA CACHE DEL NAVEGADOR: los ficheros servidos desde /static no
  llevan version en la URL. Si el navegador tiene cacheada una version
  anterior de /static/css/tailwind.css, seguira sirviendo esa copia desde su
  cache hasta que la revalide. La
  aplicacion NO sirve cabeceras Cache-Control propias en /static (las pone
  StaticFiles), por lo que la recarga se resuelve sola al revalidar; si un
  usuario ve estilos viejos, la solucion es una recarga forzada (Ctrl+F5).

================================================================================
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 COMPROBACION POR API (solo lectura)

    a) Autenticarse:
         POST /api/v1/auth/login  {"username":"...","password":"..."} -> 200

    b) Los recursos autoalojados:
         GET /static/css/tailwind.css   -> 200, Content-Type text/css
         GET /static/js/sortable.min.js  -> 200, Content-Type application/javascript
         GET /static/css/fonts.css      -> 200
         GET /static/fonts/inter-latin.woff2 -> 200, Content-Type font/woff2

    c) Que el HTML ya NO pida nada externo:
         GET /auth/login
         -> el HTML no debe contener cdn.tailwindcss.com,
            cdn.jsdelivr.net ni fonts.googleapis.com en ninguna etiqueta
            src/href.
         -> debe contener /static/css/tailwind.css,
            /static/js/sortable.min.js y /static/css/fonts.css.

    d) El resto de endpoints clave (todos 200): /dashboard, /kanban,
       /tickets, /api/v1/metricas/dashboard-completo,
       /api/v1/metricas/cuenta-resultado?ambiente=QA.

  5.2 COMPROBACION VISUAL (la importante: era el sintoma reportado)

    a) Abrir https://bitacora-grmv2-production.up.railway.app/kanban con la
       pestana Network abierta.
    b) La pestana Network NO debe mostrar ninguna peticion a un CDN
       externo: ni cdn.tailwindcss.com, ni cdn.jsdelivr.net, ni
       fonts.googleapis.com. Solo peticiones al propio dominio.
    c) La pagina debe verse maquetada: el header con el logotipo pequeno a
       la izquierda, las columnas del tablero con su ancho, las tarjetas
       con su tamano y sus colores.
    d) Comprobar el drag & drop: arrastrar una tarjeta entre columnas (el
       Kanban usa SortableJS).
    e) Recorrer el dashboard, la lista de tickets, el calendario, el Gantt,
       el timeline, las notificaciones y el modal de detalle de un ticket:
       todos deben verse con estilos.
    f) Comprobar la fuente: el texto debe verse en Inter (no en la fuente
       por defecto del sistema).

  5.3 REGRESION

    a) Los KPIs del dashboard y la tabla "Cuenta de Resultado" (columna
       DESEST) deben ser los mismos.
    b) La previsualizacion de imagenes en los comentarios (lote V2.006)
       debe seguir funcionando.
    c) El listado JSON de comentarios del ticket 6 debe seguir en 200.

================================================================================
6. TRAZABILIDAD
================================================================================

  Requisito                                  Fichero / linea            Test
  -----------------------------------------  -------------------------  ------------------------------------------------
  Ninguna plantilla pide un CDN externo      app/templates/**            test_las_plantillas_no_referencian_ningun_cdn_externo
  El JS propio tampoco                       app/static/js/**           test_el_javascript_propio_no_referencia_ningun_cdn_externo
  base.html usa los 3 recursos locales       app/templates/base.html    test_la_plantilla_base_carga_los_recursos_locales
  El CSS compilado esta versionado           app/static/css/            test_el_css_de_tailwind_esta_compilado_y_versionado
                                             tailwind.css
  Se puede recompilar sin Node               tailwind.config.js         test_la_entrada_y_la_configuracion_de_tailwind_estan
                                             app/static/css/
                                             tailwind.src.css
  SortableJS autoalojado                     app/static/js/             test_sortable_esta_autohospedado
                                             sortable.min.js
  La fuente Inter autoalojada                app/static/css/fonts.css   test_la_fuente_esta_autohospedada
                                             app/static/fonts/
  Los recursos se sirven de verdad           app/main.py (mount         test_los_recursos_autohospedados_se_sirven
                                             /static)
  El HTML servido no pide externos           app/main.py                test_el_html_servido_no_pide_recursos_externos

================================================================================
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  7.1 PUBLICACION

    a) Publicar en las dos ramas, sin reescribir historia:

         git push origin <commit>:main
         git push origin <commit>:release/v2.001

    b) Desplegar explicitamente 'worker' y 'beat' con el MISMO commit:

         python tmp_deploy_railway.py <commit> worker
         python tmp_deploy_railway.py <commit> beat

    c) Confirmar que los tres servicios quedaron en el mismo commit:

         python tmp_deploy_railway.py --estado

    d) Verificacion de salud tras el despliegue:

         GET /health   -> 200
         GET /ready    -> 200
         GET /info     -> 200
         POST /api/v1/auth/login (admin) -> 200
         GET /dashboard -> 200

    e) Verificacion funcional: los pasos 5.1 y 5.2.

  7.2 ROLLBACK

    Commit de referencia: el anterior (adfb1c1).

    Rollback en git:

         git revert <commit de V2.007>
         git push origin main
         y desplegar worker y beat con ese commit

    Rollback en Railway:

         python tmp_deploy_railway.py <commit-anterior> web
         python tmp_deploy_railway.py <commit-anterior> worker
         python tmp_deploy_railway.py <commit-anterior> beat

    Efecto del rollback: la aplicacion vuelve a depender de los CDNs
    externos. No se pierde ningun dato ni cambia ninguna funcionalidad:
    es un cambio exclusivamente de presentacion.

    ALTERNATIVA (sin tocar Git): volver a poner en base.html las tres
    etiquetas externas y redesplegar. Es el mismo efecto, pero deja un
    commit de correccion en la historia.

================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

  El diff que sigue es el EXACTO de los ficheros de codigo modificados.
  Va TRANSLITERADO a ASCII: los caracteres acentuados del codigo original
  ('a' con tilde, 'i' con tilde, etc.) se han sustituido por su equivalente
  ASCII. ESTA TRANSLITERACION ES SOLO DOCUMENTAL: el codigo del proyecto NO
  se modifica, conserva sus caracteres originales en UTF-8.

  Los ficheros binarios (los .woff2 de la fuente) no aparecen en el diff:
  se versionan tal cual, sin transformar.
diff --git a/app/static/css/fonts.css b/app/static/css/fonts.css
new file mode 100644
index 0000000..87949a7
--- /dev/null
+++ b/app/static/css/fonts.css
@@ -0,0 +1,27 @@
+/*
+ * Fuente Inter autoalojada (subconjuntos latin y latin-ext).
+ *
+ * Antes se pedia a fonts.googleapis.com: una peticion externa mas que
+ * podia fallar o tardar. Con la fuente en el propio servidor, la pagina
+ * no depende de ningun CDN.
+ *
+ * Los ficheros son la fuente VARIABLE de Inter (una por subconjunto), de
+ * modo que con dos ficheros cubren todos los pesos (400/500/600/700).
+ */
+@font-face {
+  font-family: 'Inter';
+  font-style: normal;
+  font-weight: 100 900;
+  font-display: swap;
+  src: url(/static/fonts/inter-latin.woff2) format('woff2');
+  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
+}
+
+@font-face {
+  font-family: 'Inter';
+  font-style: normal;
+  font-weight: 100 900;
+  font-display: swap;
+  src: url(/static/fonts/inter-latin-ext.woff2) format('woff2');
+  unicode-range: U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF;
+}
diff --git a/app/static/css/tailwind.css b/app/static/css/tailwind.css
new file mode 100644
index 0000000..8fe9216
--- /dev/null
+++ b/app/static/css/tailwind.css
@@ -0,0 +1,2 @@
+*,:after,:before{--tw-border-spacing-x:0;--tw-border-spacing-y:0;--tw-translate-x:0;--tw-translate-y:0;--tw-rotate:0;--tw-skew-x:0;--tw-skew-y:0;--tw-scale-x:1;--tw-scale-y:1;--tw-pan-x: ;--tw-pan-y: ;--tw-pinch-zoom: ;--tw-scroll-snap-strictness:proximity;--tw-gradient-from-position: ;--tw-gradient-via-position: ;--tw-gradient-to-position: ;--tw-ordinal: ;--tw-slashed-zero: ;--tw-numeric-figure: ;--tw-numeric-spacing: ;--tw-numeric-fraction: ;--tw-ring-inset: ;--tw-ring-offset-width:0px;--tw-ring-offset-color:#fff;--tw-ring-color:rgba(59,130,246,.5);--tw-ring-offset-shadow:0 0 #0000;--tw-ring-shadow:0 0 #0000;--tw-shadow:0 0 #0000;--tw-shadow-colored:0 0 #0000;--tw-blur: ;--tw-brightness: ;--tw-contrast: ;--tw-grayscale: ;--tw-hue-rotate: ;--tw-invert: ;--tw-saturate: ;--tw-sepia: ;--tw-drop-shadow: ;--tw-backdrop-blur: ;--tw-backdrop-brightness: ;--tw-backdrop-contrast: ;--tw-backdrop-grayscale: ;--tw-backdrop-hue-rotate: ;--tw-backdrop-invert: ;--tw-backdrop-opacity: ;--tw-backdrop-saturate: ;--tw-backdrop-sepia: ;--tw-contain-size: ;--tw-contain-layout: ;--tw-contain-paint: ;--tw-contain-style: }::backdrop{--tw-border-spacing-x:0;--tw-border-spacing-y:0;--tw-translate-x:0;--tw-translate-y:0;--tw-rotate:0;--tw-skew-x:0;--tw-skew-y:0;--tw-scale-x:1;--tw-scale-y:1;--tw-pan-x: ;--tw-pan-y: ;--tw-pinch-zoom: ;--tw-scroll-snap-strictness:proximity;--tw-gradient-from-position: ;--tw-gradient-via-position: ;--tw-gradient-to-position: ;--tw-ordinal: ;--tw-slashed-zero: ;--tw-numeric-figure: ;--tw-numeric-spacing: ;--tw-numeric-fraction: ;--tw-ring-inset: ;--tw-ring-offset-width:0px;--tw-ring-offset-color:#fff;--tw-ring-color:rgba(59,130,246,.5);--tw-ring-offset-shadow:0 0 #0000;--tw-ring-shadow:0 0 #0000;--tw-shadow:0 0 #0000;--tw-shadow-colored:0 0 #0000;--tw-blur: ;--tw-brightness: ;--tw-contrast: ;--tw-grayscale: ;--tw-hue-rotate: ;--tw-invert: ;--tw-saturate: ;--tw-sepia: ;--tw-drop-shadow: ;--tw-backdrop-blur: ;--tw-backdrop-brightness: ;--tw-backdrop-contrast: ;--tw-backdrop-grayscale: ;--tw-backdrop-hue-rotate: ;--tw-backdrop-invert: ;--tw-backdrop-opacity: ;--tw-backdrop-saturate: ;--tw-backdrop-sepia: ;--tw-contain-size: ;--tw-contain-layout: ;--tw-contain-paint: ;--tw-contain-style: }
+/*! tailwindcss v3.4.17 | MIT License | https://tailwindcss.com*/*,:after,:before{border:0 solid #e5e7eb;box-sizing:border-box}:after,:before{--tw-content:""}:host,html{line-height:1.5;-webkit-text-size-adjust:100%;font-family:Inter,system-ui,sans-serif;font-feature-settings:normal;font-variation-settings:normal;-moz-tab-size:4;-o-tab-size:4;tab-size:4;-webkit-tap-highlight-color:transparent}body{line-height:inherit;margin:0}hr{border-top-width:1px;color:inherit;height:0}abbr:where([title]){-webkit-text-decoration:underline dotted;text-decoration:underline dotted}h1,h2,h3,h4,h5,h6{font-size:inherit;font-weight:inherit}a{color:inherit;text-decoration:inherit}b,strong{font-weight:bolder}code,kbd,pre,samp{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,Liberation Mono,Courier New,monospace;font-feature-settings:normal;font-size:1em;font-variation-settings:normal}small{font-size:80%}sub,sup{font-size:75%;line-height:0;position:relative;vertical-align:baseline}sub{bottom:-.25em}sup{top:-.5em}table{border-collapse:collapse;border-color:inherit;text-indent:0}button,input,optgroup,select,textarea{color:inherit;font-family:inherit;font-feature-settings:inherit;font-size:100%;font-variation-settings:inherit;font-weight:inherit;letter-spacing:inherit;line-height:inherit;margin:0;padding:0}button,select{text-transform:none}button,input:where([type=button]),input:where([type=reset]),input:where([type=submit]){-webkit-appearance:button;background-color:transparent;background-image:none}:-moz-focusring{outline:auto}:-moz-ui-invalid{box-shadow:none}progress{vertical-align:baseline}::-webkit-inner-spin-button,::-webkit-outer-spin-button{height:auto}[type=search]{-webkit-appearance:textfield;outline-offset:-2px}::-webkit-search-decoration{-webkit-appearance:none}::-webkit-file-upload-button{-webkit-appearance:button;font:inherit}summary{display:list-item}blockquote,dd,dl,figure,h1,h2,h3,h4,h5,h6,hr,p,pre{margin:0}fieldset{margin:0}fieldset,legend{padding:0}menu,ol,ul{list-style:none;margin:0;padding:0}dialog{padding:0}textarea{resize:vertical}input::-moz-placeholder,textarea::-moz-placeholder{color:#9ca3af;opacity:1}input::placeholder,textarea::placeholder{color:#9ca3af;opacity:1}[role=button],button{cursor:pointer}:disabled{cursor:default}audio,canvas,embed,iframe,img,object,svg,video{display:block;vertical-align:middle}img,video{height:auto;max-width:100%}[hidden]:where(:not([hidden=until-found])){display:none}.\!container{width:100%!important}.container{width:100%}@media (min-width:640px){.\!container{max-width:640px!important}.container{max-width:640px}}@media (min-width:768px){.\!container{max-width:768px!important}.container{max-width:768px}}@media (min-width:1024px){.\!container{max-width:1024px!important}.container{max-width:1024px}}@media (min-width:1280px){.\!container{max-width:1280px!important}.container{max-width:1280px}}@media (min-width:1536px){.\!container{max-width:1536px!important}.container{max-width:1536px}}.sr-only{height:1px;margin:-1px;overflow:hidden;padding:0;position:absolute;width:1px;clip:rect(0,0,0,0);border-width:0;white-space:nowrap}.pointer-events-none{pointer-events:none}.pointer-events-auto{pointer-events:auto}.visible{visibility:visible}.invisible{visibility:hidden}.static{position:static}.fixed{position:fixed}.absolute{position:absolute}.relative{position:relative}.sticky{position:sticky}.inset-0{inset:0}.inset-x-0{left:0;right:0}.-left-\[1\.45rem\]{left:-1.45rem}.bottom-0{bottom:0}.bottom-2{bottom:.5rem}.bottom-4{bottom:1rem}.left-0{left:0}.left-1\/2{left:50%}.left-2{left:.5rem}.left-3{left:.75rem}.right-0{right:0}.right-2{right:.5rem}.right-3{right:.75rem}.right-4{right:1rem}.top-0{top:0}.top-0\.5{top:.125rem}.top-2{top:.5rem}.top-3{top:.75rem}.top-4{top:1rem}.top-5{top:1.25rem}.top-7{top:1.75rem}.top-full{top:100%}.z-10{z-index:10}.z-20{z-index:20}.z-50{z-index:50}.z-\[1000\]{z-index:1000}.z-\[1100\]{z-index:1100}.z-\[60\]{z-index:60}.z-\[70\]{z-index:70}.z-\[80\]{z-index:80}.col-span-2{grid-column:span 2/span 2}.col-span-3{grid-column:span 3/span 3}.col-span-4{grid-column:span 4/span 4}.col-span-6{grid-column:span 6/span 6}.col-span-full{grid-column:1/-1}.m-0{margin:0}.-my-1{margin-bottom:-.25rem;margin-top:-.25rem}.mx-1{margin-left:.25rem;margin-right:.25rem}.mx-4{margin-left:1rem;margin-right:1rem}.mx-5{margin-left:1.25rem;margin-right:1.25rem}.mx-auto{margin-left:auto;margin-right:auto}.my-1{margin-bottom:.25rem;margin-top:.25rem}.-mt-0\.5{margin-top:-.125rem}.mb-0\.5{margin-bottom:.125rem}.mb-1{margin-bottom:.25rem}.mb-1\.5{margin-bottom:.375rem}.mb-2{margin-bottom:.5rem}.mb-3{margin-bottom:.75rem}.mb-4{margin-bottom:1rem}.mb-5{margin-bottom:1.25rem}.mb-6{margin-bottom:1.5rem}.ml-0\.5{margin-left:.125rem}.ml-1{margin-left:.25rem}.ml-2{margin-left:.5rem}.ml-4{margin-left:1rem}.ml-auto{margin-left:auto}.mr-1{margin-right:.25rem}.mt-0\.5{margin-top:.125rem}.mt-1{margin-top:.25rem}.mt-1\.5{margin-top:.375rem}.mt-2{margin-top:.5rem}.mt-20{margin-top:5rem}.mt-3{margin-top:.75rem}.mt-4{margin-top:1rem}.mt-5{margin-top:1.25rem}.mt-6{margin-top:1.5rem}.mt-8{margin-top:2rem}.line-clamp-2{-webkit-line-clamp:2}.line-clamp-2,.line-clamp-3{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical}.line-clamp-3{-webkit-line-clamp:3}.block{display:block}.inline-block{display:inline-block}.inline{display:inline}.flex{display:flex}.inline-flex{display:inline-flex}.\!table{display:table!important}.table{display:table}.grid{display:grid}.contents{display:contents}.\!hidden{display:none!important}.hidden{display:none}.h-0\.5{height:.125rem}.h-1{height:.25rem}.h-1\.5{height:.375rem}.h-10{height:2.5rem}.h-12{height:3rem}.h-14{height:3.5rem}.h-2{height:.5rem}.h-2\.5{height:.625rem}.h-24{height:6rem}.h-28{height:7rem}.h-3{height:.75rem}.h-3\.5{height:.875rem}.h-4{height:1rem}.h-5{height:1.25rem}.h-6{height:1.5rem}.h-7{height:1.75rem}.h-8{height:2rem}.h-9{height:2.25rem}.h-\[18px\]{height:18px}.h-\[420px\]{height:420px}.h-\[calc\(100vh-57px\)\]{height:calc(100vh - 57px)}.h-full{height:100%}.max-h-32{max-height:8rem}.max-h-40{max-height:10rem}.max-h-48{max-height:12rem}.max-h-72{max-height:18rem}.max-h-96{max-height:24rem}.max-h-\[28rem\]{max-height:28rem}.max-h-\[55vh\]{max-height:55vh}.max-h-\[60vh\]{max-height:60vh}.max-h-\[85vh\]{max-height:85vh}.max-h-\[90vh\]{max-height:90vh}.max-h-\[92vh\]{max-height:92vh}.max-h-\[calc\(100vh-220px\)\]{max-height:calc(100vh - 220px)}.min-h-\[110px\]{min-height:110px}.min-h-\[120px\]{min-height:120px}.min-h-\[200px\]{min-height:200px}.min-h-\[24px\]{min-height:24px}.min-h-\[40px\]{min-height:40px}.min-h-full{min-height:100%}.w-1\.5{width:.375rem}.w-1\/3{width:33.333333%}.w-10{width:2.5rem}.w-12{width:3rem}.w-14{width:3.5rem}.w-2{width:.5rem}.w-2\.5{width:.625rem}.w-3{width:.75rem}.w-3\.5{width:.875rem}.w-4{width:1rem}.w-5{width:1.25rem}.w-56{width:14rem}.w-6{width:1.5rem}.w-60{width:15rem}.w-64{width:16rem}.w-7{width:1.75rem}.w-72{width:18rem}.w-8{width:2rem}.w-80{width:20rem}.w-9{width:2.25rem}.w-\[480px\]{width:480px}.w-\[640px\]{width:640px}.w-\[760px\]{width:760px}.w-full{width:100%}.w-px{width:1px}.min-w-0{min-width:0}.min-w-\[10rem\]{min-width:10rem}.min-w-\[110px\]{min-width:110px}.min-w-\[120px\]{min-width:120px}.min-w-\[180px\]{min-width:180px}.min-w-\[18px\]{min-width:18px}.min-w-\[200px\]{min-width:200px}.min-w-\[20px\]{min-width:20px}.min-w-\[260px\]{min-width:260px}.min-w-\[280px\]{min-width:280px}.min-w-full{min-width:100%}.min-w-max{min-width:-moz-max-content;min-width:max-content}.max-w-2xl{max-width:42rem}.max-w-3xl{max-width:48rem}.max-w-4xl{max-width:56rem}.max-w-5xl{max-width:64rem}.max-w-6xl{max-width:72rem}.max-w-7xl{max-width:80rem}.max-w-\[10rem\]{max-width:10rem}.max-w-\[1200px\]{max-width:1200px}.max-w-\[1400px\]{max-width:1400px}.max-w-\[140px\]{max-width:140px}.max-w-\[14rem\]{max-width:14rem}.max-w-\[1600px\]{max-width:1600px}.max-w-\[160px\]{max-width:160px}.max-w-\[260px\]{max-width:260px}.max-w-\[280px\]{max-width:280px}.max-w-\[60vw\]{max-width:60vw}.max-w-\[7rem\]{max-width:7rem}.max-w-\[8rem\]{max-width:8rem}.max-w-\[95vw\]{max-width:95vw}.max-w-full{max-width:100%}.max-w-lg{max-width:32rem}.max-w-md{max-width:28rem}.max-w-sm{max-width:24rem}.max-w-xs{max-width:20rem}.flex-1{flex:1 1 0%}.flex-shrink{flex-shrink:1}.flex-shrink-0,.shrink-0{flex-shrink:0}.border-collapse{border-collapse:collapse}.-translate-x-1\/2{--tw-translate-x:-50%}.-translate-x-1\/2,.rotate-180{transform:translate(var(--tw-translate-x),var(--tw-translate-y)) rotate(var(--tw-rotate)) skewX(var(--tw-skew-x)) skewY(var(--tw-skew-y)) scaleX(var(--tw-scale-x)) scaleY(var(--tw-scale-y))}.rotate-180{--tw-rotate:180deg}.transform{transform:translate(var(--tw-translate-x),var(--tw-translate-y)) rotate(var(--tw-rotate)) skewX(var(--tw-skew-x)) skewY(var(--tw-skew-y)) scaleX(var(--tw-scale-x)) scaleY(var(--tw-scale-y))}@keyframes pulse{50%{opacity:.5}}.animate-pulse{animation:pulse 2s cubic-bezier(.4,0,.6,1) infinite}@keyframes spin{to{transform:rotate(1turn)}}.animate-spin{animation:spin 1s linear infinite}.cursor-default{cursor:default}.cursor-grab{cursor:grab}.cursor-help{cursor:help}.cursor-pointer{cursor:pointer}.cursor-zoom-in{cursor:zoom-in}.cursor-zoom-out{cursor:zoom-out}.resize-none{resize:none}.resize-y{resize:vertical}.resize{resize:both}.list-inside{list-style-position:inside}.list-decimal{list-style-type:decimal}.list-disc{list-style-type:disc}.list-none{list-style-type:none}.grid-cols-1{grid-template-columns:repeat(1,minmax(0,1fr))}.grid-cols-12{grid-template-columns:repeat(12,minmax(0,1fr))}.grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.grid-cols-3{grid-template-columns:repeat(3,minmax(0,1fr))}.grid-cols-7{grid-template-columns:repeat(7,minmax(0,1fr))}.flex-col{flex-direction:column}.flex-wrap{flex-wrap:wrap}.items-start{align-items:flex-start}.items-end{align-items:flex-end}.items-center{align-items:center}.items-stretch{align-items:stretch}.justify-start{justify-content:flex-start}.justify-end{justify-content:flex-end}.justify-center{justify-content:center}.justify-between{justify-content:space-between}.gap-0\.5{gap:.125rem}.gap-1{gap:.25rem}.gap-1\.5{gap:.375rem}.gap-2{gap:.5rem}.gap-2\.5{gap:.625rem}.gap-3{gap:.75rem}.gap-4{gap:1rem}.gap-5{gap:1.25rem}.gap-x-3{-moz-column-gap:.75rem;column-gap:.75rem}.gap-x-4{-moz-column-gap:1rem;column-gap:1rem}.gap-x-5{-moz-column-gap:1.25rem;column-gap:1.25rem}.gap-y-1{row-gap:.25rem}.gap-y-2{row-gap:.5rem}.space-y-0\.5>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(.125rem*var(--tw-space-y-reverse));margin-top:calc(.125rem*(1 - var(--tw-space-y-reverse)))}.space-y-1>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(.25rem*var(--tw-space-y-reverse));margin-top:calc(.25rem*(1 - var(--tw-space-y-reverse)))}.space-y-1\.5>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(.375rem*var(--tw-space-y-reverse));margin-top:calc(.375rem*(1 - var(--tw-space-y-reverse)))}.space-y-2>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(.5rem*var(--tw-space-y-reverse));margin-top:calc(.5rem*(1 - var(--tw-space-y-reverse)))}.space-y-2\.5>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(.625rem*var(--tw-space-y-reverse));margin-top:calc(.625rem*(1 - var(--tw-space-y-reverse)))}.space-y-3>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(.75rem*var(--tw-space-y-reverse));margin-top:calc(.75rem*(1 - var(--tw-space-y-reverse)))}.space-y-4>:not([hidden])~:not([hidden]){--tw-space-y-reverse:0;margin-bottom:calc(1rem*var(--tw-space-y-reverse));margin-top:calc(1rem*(1 - var(--tw-space-y-reverse)))}.divide-y>:not([hidden])~:not([hidden]){--tw-divide-y-reverse:0;border-bottom-width:calc(1px*var(--tw-divide-y-reverse));border-top-width:calc(1px*(1 - var(--tw-divide-y-reverse)))}.divide-slate-100>:not([hidden])~:not([hidden]){--tw-divide-opacity:1;border-color:rgb(241 245 249/var(--tw-divide-opacity,1))}.overflow-auto{overflow:auto}.overflow-hidden{overflow:hidden}.overflow-x-auto{overflow-x:auto}.overflow-y-auto{overflow-y:auto}.overflow-y-hidden{overflow-y:hidden}.overflow-x-clip{overflow-x:clip}.truncate{overflow:hidden;text-overflow:ellipsis}.truncate,.whitespace-nowrap{white-space:nowrap}.whitespace-pre-wrap{white-space:pre-wrap}.break-words{overflow-wrap:break-word}.break-all{word-break:break-all}.rounded{border-radius:.25rem}.rounded-full{border-radius:9999px}.rounded-lg{border-radius:.5rem}.rounded-md{border-radius:.375rem}.rounded-sm{border-radius:.125rem}.rounded-xl{border-radius:.75rem}.rounded-b-lg{border-bottom-left-radius:.5rem;border-bottom-right-radius:.5rem}.rounded-l-md{border-bottom-left-radius:.375rem;border-top-left-radius:.375rem}.rounded-r-md{border-bottom-right-radius:.375rem;border-top-right-radius:.375rem}.rounded-t-lg{border-top-left-radius:.5rem;border-top-right-radius:.5rem}.border{border-width:1px}.border-0{border-width:0}.border-2{border-width:2px}.border-b{border-bottom-width:1px}.border-b-2{border-bottom-width:2px}.border-l{border-left-width:1px}.border-l-2{border-left-width:2px}.border-l-4{border-left-width:4px}.border-r{border-right-width:1px}.border-t{border-top-width:1px}.border-t-2{border-top-width:2px}.border-dashed{border-style:dashed}.border-amber-100{--tw-border-opacity:1;border-color:rgb(254 243 199/var(--tw-border-opacity,1))}.border-amber-200{--tw-border-opacity:1;border-color:rgb(253 230 138/var(--tw-border-opacity,1))}.border-amber-300{--tw-border-opacity:1;border-color:rgb(252 211 77/var(--tw-border-opacity,1))}.border-amber-400{--tw-border-opacity:1;border-color:rgb(251 191 36/var(--tw-border-opacity,1))}.border-blue-300{--tw-border-opacity:1;border-color:rgb(147 197 253/var(--tw-border-opacity,1))}.border-emerald-100{--tw-border-opacity:1;border-color:rgb(209 250 229/var(--tw-border-opacity,1))}.border-emerald-200{--tw-border-opacity:1;border-color:rgb(167 243 208/var(--tw-border-opacity,1))}.border-emerald-300{--tw-border-opacity:1;border-color:rgb(110 231 183/var(--tw-border-opacity,1))}.border-indigo-100{--tw-border-opacity:1;border-color:rgb(224 231 255/var(--tw-border-opacity,1))}.border-indigo-200{--tw-border-opacity:1;border-color:rgb(199 210 254/var(--tw-border-opacity,1))}.border-indigo-500{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.border-indigo-600{--tw-border-opacity:1;border-color:rgb(79 70 229/var(--tw-border-opacity,1))}.border-indigo-700{--tw-border-opacity:1;border-color:rgb(67 56 202/var(--tw-border-opacity,1))}.border-purple-300{--tw-border-opacity:1;border-color:rgb(216 180 254/var(--tw-border-opacity,1))}.border-red-100{--tw-border-opacity:1;border-color:rgb(254 226 226/var(--tw-border-opacity,1))}.border-red-200{--tw-border-opacity:1;border-color:rgb(254 202 202/var(--tw-border-opacity,1))}.border-red-300{--tw-border-opacity:1;border-color:rgb(252 165 165/var(--tw-border-opacity,1))}.border-red-400{--tw-border-opacity:1;border-color:rgb(248 113 113/var(--tw-border-opacity,1))}.border-red-500{--tw-border-opacity:1;border-color:rgb(239 68 68/var(--tw-border-opacity,1))}.border-rose-100{--tw-border-opacity:1;border-color:rgb(255 228 230/var(--tw-border-opacity,1))}.border-rose-200{--tw-border-opacity:1;border-color:rgb(254 205 211/var(--tw-border-opacity,1))}.border-sky-200{--tw-border-opacity:1;border-color:rgb(186 230 253/var(--tw-border-opacity,1))}.border-sky-300{--tw-border-opacity:1;border-color:rgb(125 211 252/var(--tw-border-opacity,1))}.border-sky-500{--tw-border-opacity:1;border-color:rgb(14 165 233/var(--tw-border-opacity,1))}.border-slate-100{--tw-border-opacity:1;border-color:rgb(241 245 249/var(--tw-border-opacity,1))}.border-slate-200{--tw-border-opacity:1;border-color:rgb(226 232 240/var(--tw-border-opacity,1))}.border-slate-300{--tw-border-opacity:1;border-color:rgb(203 213 225/var(--tw-border-opacity,1))}.border-slate-400{--tw-border-opacity:1;border-color:rgb(148 163 184/var(--tw-border-opacity,1))}.border-slate-700{--tw-border-opacity:1;border-color:rgb(51 65 85/var(--tw-border-opacity,1))}.border-transparent{border-color:transparent}.border-white{--tw-border-opacity:1;border-color:rgb(255 255 255/var(--tw-border-opacity,1))}.border-yellow-200{--tw-border-opacity:1;border-color:rgb(254 240 138/var(--tw-border-opacity,1))}.border-l-indigo-500{--tw-border-opacity:1;border-left-color:rgb(99 102 241/var(--tw-border-opacity,1))}.border-t-indigo-600{--tw-border-opacity:1;border-top-color:rgb(79 70 229/var(--tw-border-opacity,1))}.border-t-transparent{border-top-color:transparent}.bg-amber-100{--tw-bg-opacity:1;background-color:rgb(254 243 199/var(--tw-bg-opacity,1))}.bg-amber-200{--tw-bg-opacity:1;background-color:rgb(253 230 138/var(--tw-bg-opacity,1))}.bg-amber-50{--tw-bg-opacity:1;background-color:rgb(255 251 235/var(--tw-bg-opacity,1))}.bg-amber-50\/40{background-color:rgba(255,251,235,.4)}.bg-amber-500{--tw-bg-opacity:1;background-color:rgb(245 158 11/var(--tw-bg-opacity,1))}.bg-amber-600{--tw-bg-opacity:1;background-color:rgb(217 119 6/var(--tw-bg-opacity,1))}.bg-black\/40{background-color:rgba(0,0,0,.4)}.bg-blue-100{--tw-bg-opacity:1;background-color:rgb(219 234 254/var(--tw-bg-opacity,1))}.bg-blue-50{--tw-bg-opacity:1;background-color:rgb(239 246 255/var(--tw-bg-opacity,1))}.bg-blue-500{--tw-bg-opacity:1;background-color:rgb(59 130 246/var(--tw-bg-opacity,1))}.bg-emerald-100{--tw-bg-opacity:1;background-color:rgb(209 250 229/var(--tw-bg-opacity,1))}.bg-emerald-50{--tw-bg-opacity:1;background-color:rgb(236 253 245/var(--tw-bg-opacity,1))}.bg-emerald-50\/40{background-color:rgba(236,253,245,.4)}.bg-emerald-500{--tw-bg-opacity:1;background-color:rgb(16 185 129/var(--tw-bg-opacity,1))}.bg-emerald-600{--tw-bg-opacity:1;background-color:rgb(5 150 105/var(--tw-bg-opacity,1))}.bg-indigo-100{--tw-bg-opacity:1;background-color:rgb(224 231 255/var(--tw-bg-opacity,1))}.bg-indigo-50{--tw-bg-opacity:1;background-color:rgb(238 242 255/var(--tw-bg-opacity,1))}.bg-indigo-50\/30{background-color:rgba(238,242,255,.3)}.bg-indigo-50\/50{background-color:rgba(238,242,255,.5)}.bg-indigo-500{--tw-bg-opacity:1;background-color:rgb(99 102 241/var(--tw-bg-opacity,1))}.bg-indigo-600{--tw-bg-opacity:1;background-color:rgb(79 70 229/var(--tw-bg-opacity,1))}.bg-orange-100{--tw-bg-opacity:1;background-color:rgb(255 237 213/var(--tw-bg-opacity,1))}.bg-orange-500{--tw-bg-opacity:1;background-color:rgb(249 115 22/var(--tw-bg-opacity,1))}.bg-pink-100{--tw-bg-opacity:1;background-color:rgb(252 231 243/var(--tw-bg-opacity,1))}.bg-purple-100{--tw-bg-opacity:1;background-color:rgb(243 232 255/var(--tw-bg-opacity,1))}.bg-purple-50{--tw-bg-opacity:1;background-color:rgb(250 245 255/var(--tw-bg-opacity,1))}.bg-purple-500{--tw-bg-opacity:1;background-color:rgb(168 85 247/var(--tw-bg-opacity,1))}.bg-purple-600{--tw-bg-opacity:1;background-color:rgb(147 51 234/var(--tw-bg-opacity,1))}.bg-red-100{--tw-bg-opacity:1;background-color:rgb(254 226 226/var(--tw-bg-opacity,1))}.bg-red-50{--tw-bg-opacity:1;background-color:rgb(254 242 242/var(--tw-bg-opacity,1))}.bg-red-500{--tw-bg-opacity:1;background-color:rgb(239 68 68/var(--tw-bg-opacity,1))}.bg-red-600{--tw-bg-opacity:1;background-color:rgb(220 38 38/var(--tw-bg-opacity,1))}.bg-rose-100{--tw-bg-opacity:1;background-color:rgb(255 228 230/var(--tw-bg-opacity,1))}.bg-rose-50{--tw-bg-opacity:1;background-color:rgb(255 241 242/var(--tw-bg-opacity,1))}.bg-rose-600{--tw-bg-opacity:1;background-color:rgb(225 29 72/var(--tw-bg-opacity,1))}.bg-sky-100{--tw-bg-opacity:1;background-color:rgb(224 242 254/var(--tw-bg-opacity,1))}.bg-sky-50{--tw-bg-opacity:1;background-color:rgb(240 249 255/var(--tw-bg-opacity,1))}.bg-sky-600{--tw-bg-opacity:1;background-color:rgb(2 132 199/var(--tw-bg-opacity,1))}.bg-slate-100{--tw-bg-opacity:1;background-color:rgb(241 245 249/var(--tw-bg-opacity,1))}.bg-slate-100\/70{background-color:rgba(241,245,249,.7)}.bg-slate-200{--tw-bg-opacity:1;background-color:rgb(226 232 240/var(--tw-bg-opacity,1))}.bg-slate-300{--tw-bg-opacity:1;background-color:rgb(203 213 225/var(--tw-bg-opacity,1))}.bg-slate-400{--tw-bg-opacity:1;background-color:rgb(148 163 184/var(--tw-bg-opacity,1))}.bg-slate-50{--tw-bg-opacity:1;background-color:rgb(248 250 252/var(--tw-bg-opacity,1))}.bg-slate-50\/30{background-color:rgba(248,250,252,.3)}.bg-slate-50\/40{background-color:rgba(248,250,252,.4)}.bg-slate-50\/50{background-color:rgba(248,250,252,.5)}.bg-slate-50\/60{background-color:rgba(248,250,252,.6)}.bg-slate-500{--tw-bg-opacity:1;background-color:rgb(100 116 139/var(--tw-bg-opacity,1))}.bg-slate-700{--tw-bg-opacity:1;background-color:rgb(51 65 85/var(--tw-bg-opacity,1))}.bg-slate-800{--tw-bg-opacity:1;background-color:rgb(30 41 59/var(--tw-bg-opacity,1))}.bg-slate-800\/70{background-color:rgba(30,41,59,.7)}.bg-slate-900{--tw-bg-opacity:1;background-color:rgb(15 23 42/var(--tw-bg-opacity,1))}.bg-slate-900\/30{background-color:rgba(15,23,42,.3)}.bg-slate-900\/40{background-color:rgba(15,23,42,.4)}.bg-slate-900\/50{background-color:rgba(15,23,42,.5)}.bg-slate-900\/85{background-color:rgba(15,23,42,.85)}.bg-transparent{background-color:transparent}.bg-violet-100{--tw-bg-opacity:1;background-color:rgb(237 233 254/var(--tw-bg-opacity,1))}.bg-white{--tw-bg-opacity:1;background-color:rgb(255 255 255/var(--tw-bg-opacity,1))}.bg-white\/10{background-color:hsla(0,0%,100%,.1)}.bg-white\/80{background-color:hsla(0,0%,100%,.8)}.bg-yellow-100{--tw-bg-opacity:1;background-color:rgb(254 249 195/var(--tw-bg-opacity,1))}.bg-yellow-50{--tw-bg-opacity:1;background-color:rgb(254 252 232/var(--tw-bg-opacity,1))}.bg-gradient-to-br{background-image:linear-gradient(to bottom right,var(--tw-gradient-stops))}.bg-gradient-to-r{background-image:linear-gradient(to right,var(--tw-gradient-stops))}.from-amber-50{--tw-gradient-from:#fffbeb var(--tw-gradient-from-position);--tw-gradient-to:rgba(255,251,235,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-amber-500{--tw-gradient-from:#f59e0b var(--tw-gradient-from-position);--tw-gradient-to:rgba(245,158,11,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-amber-600{--tw-gradient-from:#d97706 var(--tw-gradient-from-position);--tw-gradient-to:rgba(217,119,6,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-indigo-50{--tw-gradient-from:#eef2ff var(--tw-gradient-from-position);--tw-gradient-to:rgba(238,242,255,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-indigo-500{--tw-gradient-from:#6366f1 var(--tw-gradient-from-position);--tw-gradient-to:rgba(99,102,241,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-indigo-600{--tw-gradient-from:#4f46e5 var(--tw-gradient-from-position);--tw-gradient-to:rgba(79,70,229,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-purple-500{--tw-gradient-from:#a855f7 var(--tw-gradient-from-position);--tw-gradient-to:rgba(168,85,247,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-purple-600{--tw-gradient-from:#9333ea var(--tw-gradient-from-position);--tw-gradient-to:rgba(147,51,234,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-slate-100{--tw-gradient-from:#f1f5f9 var(--tw-gradient-from-position);--tw-gradient-to:rgba(241,245,249,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-slate-50{--tw-gradient-from:#f8fafc var(--tw-gradient-from-position);--tw-gradient-to:rgba(248,250,252,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.from-transparent{--tw-gradient-from:transparent var(--tw-gradient-from-position);--tw-gradient-to:transparent var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.via-indigo-500{--tw-gradient-to:rgba(99,102,241,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),#6366f1 var(--tw-gradient-via-position),var(--tw-gradient-to)}.to-black\/30{--tw-gradient-to:rgba(0,0,0,.3) var(--tw-gradient-to-position)}.to-indigo-50{--tw-gradient-to:#eef2ff var(--tw-gradient-to-position)}.to-pink-500{--tw-gradient-to:#ec4899 var(--tw-gradient-to-position)}.to-pink-600{--tw-gradient-to:#db2777 var(--tw-gradient-to-position)}.to-purple-50{--tw-gradient-to:#faf5ff var(--tw-gradient-to-position)}.to-purple-600{--tw-gradient-to:#9333ea var(--tw-gradient-to-position)}.to-rose-50{--tw-gradient-to:#fff1f2 var(--tw-gradient-to-position)}.to-rose-600{--tw-gradient-to:#e11d48 var(--tw-gradient-to-position)}.to-slate-100{--tw-gradient-to:#f1f5f9 var(--tw-gradient-to-position)}.to-transparent{--tw-gradient-to:transparent var(--tw-gradient-to-position)}.object-contain{-o-object-fit:contain;object-fit:contain}.object-cover{-o-object-fit:cover;object-fit:cover}.p-0{padding:0}.p-0\.5{padding:.125rem}.p-1{padding:.25rem}.p-1\.5{padding:.375rem}.p-10{padding:2.5rem}.p-12{padding:3rem}.p-16{padding:4rem}.p-2{padding:.5rem}.p-2\.5{padding:.625rem}.p-3{padding:.75rem}.p-4{padding:1rem}.p-5{padding:1.25rem}.p-6{padding:1.5rem}.p-8{padding:2rem}.px-0{padding-left:0;padding-right:0}.px-1{padding-left:.25rem;padding-right:.25rem}.px-1\.5{padding-left:.375rem;padding-right:.375rem}.px-2{padding-left:.5rem;padding-right:.5rem}.px-2\.5{padding-left:.625rem;padding-right:.625rem}.px-3{padding-left:.75rem;padding-right:.75rem}.px-4{padding-left:1rem;padding-right:1rem}.px-5{padding-left:1.25rem;padding-right:1.25rem}.px-6{padding-left:1.5rem;padding-right:1.5rem}.py-0\.5{padding-bottom:.125rem;padding-top:.125rem}.py-1{padding-bottom:.25rem;padding-top:.25rem}.py-1\.5{padding-bottom:.375rem;padding-top:.375rem}.py-10{padding-bottom:2.5rem;padding-top:2.5rem}.py-12{padding-bottom:3rem;padding-top:3rem}.py-16{padding-bottom:4rem;padding-top:4rem}.py-2{padding-bottom:.5rem;padding-top:.5rem}.py-2\.5{padding-bottom:.625rem;padding-top:.625rem}.py-3{padding-bottom:.75rem;padding-top:.75rem}.py-4{padding-bottom:1rem;padding-top:1rem}.py-5{padding-bottom:1.25rem;padding-top:1.25rem}.py-6{padding-bottom:1.5rem;padding-top:1.5rem}.py-8{padding-bottom:2rem;padding-top:2rem}.py-\[1px\]{padding-bottom:1px;padding-top:1px}.pb-1\.5{padding-bottom:.375rem}.pb-2{padding-bottom:.5rem}.pb-3{padding-bottom:.75rem}.pb-4{padding-bottom:1rem}.pl-8{padding-left:2rem}.pr-1{padding-right:.25rem}.pr-2{padding-right:.5rem}.pt-1{padding-top:.25rem}.pt-1\.5{padding-top:.375rem}.pt-2{padding-top:.5rem}.pt-3{padding-top:.75rem}.pt-4{padding-top:1rem}.text-left{text-align:left}.text-center{text-align:center}.text-right{text-align:right}.align-middle{vertical-align:middle}.font-mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,Liberation Mono,Courier New,monospace}.font-sans{font-family:Inter,system-ui,sans-serif}.text-2xl{font-size:1.5rem;line-height:2rem}.text-3xl{font-size:1.875rem;line-height:2.25rem}.text-4xl{font-size:2.25rem;line-height:2.5rem}.text-5xl{font-size:3rem;line-height:1}.text-\[\.7rem\]{font-size:.7rem}.text-\[10px\]{font-size:10px}.text-\[11px\]{font-size:11px}.text-\[12px\]{font-size:12px}.text-\[13px\]{font-size:13px}.text-\[8px\]{font-size:8px}.text-\[9px\]{font-size:9px}.text-base{font-size:1rem;line-height:1.5rem}.text-lg{font-size:1.125rem;line-height:1.75rem}.text-sm{font-size:.875rem;line-height:1.25rem}.text-xl{font-size:1.25rem;line-height:1.75rem}.text-xs{font-size:.75rem;line-height:1rem}.font-bold{font-weight:700}.font-medium{font-weight:500}.font-normal{font-weight:400}.font-semibold{font-weight:600}.uppercase{text-transform:uppercase}.lowercase{text-transform:lowercase}.capitalize{text-transform:capitalize}.normal-case{text-transform:none}.italic{font-style:italic}.leading-none{line-height:1}.leading-snug{line-height:1.375}.leading-tight{line-height:1.25}.tracking-tight{letter-spacing:-.025em}.tracking-wide{letter-spacing:.025em}.tracking-wider{letter-spacing:.05em}.text-amber-300{--tw-text-opacity:1;color:rgb(252 211 77/var(--tw-text-opacity,1))}.text-amber-400{--tw-text-opacity:1;color:rgb(251 191 36/var(--tw-text-opacity,1))}.text-amber-500{--tw-text-opacity:1;color:rgb(245 158 11/var(--tw-text-opacity,1))}.text-amber-600{--tw-text-opacity:1;color:rgb(217 119 6/var(--tw-text-opacity,1))}.text-amber-700{--tw-text-opacity:1;color:rgb(180 83 9/var(--tw-text-opacity,1))}.text-amber-800{--tw-text-opacity:1;color:rgb(146 64 14/var(--tw-text-opacity,1))}.text-amber-900{--tw-text-opacity:1;color:rgb(120 53 15/var(--tw-text-opacity,1))}.text-blue-600{--tw-text-opacity:1;color:rgb(37 99 235/var(--tw-text-opacity,1))}.text-blue-700{--tw-text-opacity:1;color:rgb(29 78 216/var(--tw-text-opacity,1))}.text-blue-800{--tw-text-opacity:1;color:rgb(30 64 175/var(--tw-text-opacity,1))}.text-emerald-400{--tw-text-opacity:1;color:rgb(52 211 153/var(--tw-text-opacity,1))}.text-emerald-500{--tw-text-opacity:1;color:rgb(16 185 129/var(--tw-text-opacity,1))}.text-emerald-600{--tw-text-opacity:1;color:rgb(5 150 105/var(--tw-text-opacity,1))}.text-emerald-700{--tw-text-opacity:1;color:rgb(4 120 87/var(--tw-text-opacity,1))}.text-emerald-700\/80{color:rgba(4,120,87,.8)}.text-emerald-800{--tw-text-opacity:1;color:rgb(6 95 70/var(--tw-text-opacity,1))}.text-emerald-900{--tw-text-opacity:1;color:rgb(6 78 59/var(--tw-text-opacity,1))}.text-indigo-400{--tw-text-opacity:1;color:rgb(129 140 248/var(--tw-text-opacity,1))}.text-indigo-500{--tw-text-opacity:1;color:rgb(99 102 241/var(--tw-text-opacity,1))}.text-indigo-600{--tw-text-opacity:1;color:rgb(79 70 229/var(--tw-text-opacity,1))}.text-indigo-700{--tw-text-opacity:1;color:rgb(67 56 202/var(--tw-text-opacity,1))}.text-indigo-800{--tw-text-opacity:1;color:rgb(55 48 163/var(--tw-text-opacity,1))}.text-indigo-900{--tw-text-opacity:1;color:rgb(49 46 129/var(--tw-text-opacity,1))}.text-orange-600{--tw-text-opacity:1;color:rgb(234 88 12/var(--tw-text-opacity,1))}.text-orange-700{--tw-text-opacity:1;color:rgb(194 65 12/var(--tw-text-opacity,1))}.text-pink-600{--tw-text-opacity:1;color:rgb(219 39 119/var(--tw-text-opacity,1))}.text-pink-800{--tw-text-opacity:1;color:rgb(157 23 77/var(--tw-text-opacity,1))}.text-purple-600{--tw-text-opacity:1;color:rgb(147 51 234/var(--tw-text-opacity,1))}.text-purple-700{--tw-text-opacity:1;color:rgb(126 34 206/var(--tw-text-opacity,1))}.text-purple-800{--tw-text-opacity:1;color:rgb(107 33 168/var(--tw-text-opacity,1))}.text-red-400{--tw-text-opacity:1;color:rgb(248 113 113/var(--tw-text-opacity,1))}.text-red-500{--tw-text-opacity:1;color:rgb(239 68 68/var(--tw-text-opacity,1))}.text-red-600{--tw-text-opacity:1;color:rgb(220 38 38/var(--tw-text-opacity,1))}.text-red-700{--tw-text-opacity:1;color:rgb(185 28 28/var(--tw-text-opacity,1))}.text-red-800{--tw-text-opacity:1;color:rgb(153 27 27/var(--tw-text-opacity,1))}.text-rose-400{--tw-text-opacity:1;color:rgb(251 113 133/var(--tw-text-opacity,1))}.text-rose-500{--tw-text-opacity:1;color:rgb(244 63 94/var(--tw-text-opacity,1))}.text-rose-600{--tw-text-opacity:1;color:rgb(225 29 72/var(--tw-text-opacity,1))}.text-rose-700{--tw-text-opacity:1;color:rgb(190 18 60/var(--tw-text-opacity,1))}.text-rose-800{--tw-text-opacity:1;color:rgb(159 18 57/var(--tw-text-opacity,1))}.text-rose-900{--tw-text-opacity:1;color:rgb(136 19 55/var(--tw-text-opacity,1))}.text-sky-600{--tw-text-opacity:1;color:rgb(2 132 199/var(--tw-text-opacity,1))}.text-sky-700{--tw-text-opacity:1;color:rgb(3 105 161/var(--tw-text-opacity,1))}.text-sky-800{--tw-text-opacity:1;color:rgb(7 89 133/var(--tw-text-opacity,1))}.text-sky-900{--tw-text-opacity:1;color:rgb(12 74 110/var(--tw-text-opacity,1))}.text-slate-100{--tw-text-opacity:1;color:rgb(241 245 249/var(--tw-text-opacity,1))}.text-slate-300{--tw-text-opacity:1;color:rgb(203 213 225/var(--tw-text-opacity,1))}.text-slate-400{--tw-text-opacity:1;color:rgb(148 163 184/var(--tw-text-opacity,1))}.text-slate-500{--tw-text-opacity:1;color:rgb(100 116 139/var(--tw-text-opacity,1))}.text-slate-600{--tw-text-opacity:1;color:rgb(71 85 105/var(--tw-text-opacity,1))}.text-slate-700{--tw-text-opacity:1;color:rgb(51 65 85/var(--tw-text-opacity,1))}.text-slate-800{--tw-text-opacity:1;color:rgb(30 41 59/var(--tw-text-opacity,1))}.text-slate-900{--tw-text-opacity:1;color:rgb(15 23 42/var(--tw-text-opacity,1))}.text-violet-700{--tw-text-opacity:1;color:rgb(109 40 217/var(--tw-text-opacity,1))}.text-violet-800{--tw-text-opacity:1;color:rgb(91 33 182/var(--tw-text-opacity,1))}.text-white{--tw-text-opacity:1;color:rgb(255 255 255/var(--tw-text-opacity,1))}.text-white\/90{color:hsla(0,0%,100%,.9)}.text-yellow-700{--tw-text-opacity:1;color:rgb(161 98 7/var(--tw-text-opacity,1))}.text-yellow-800{--tw-text-opacity:1;color:rgb(133 77 14/var(--tw-text-opacity,1))}.underline{text-decoration-line:underline}.line-through{text-decoration-line:line-through}.placeholder-slate-400::-moz-placeholder{--tw-placeholder-opacity:1;color:rgb(148 163 184/var(--tw-placeholder-opacity,1))}.placeholder-slate-400::placeholder{--tw-placeholder-opacity:1;color:rgb(148 163 184/var(--tw-placeholder-opacity,1))}.opacity-0{opacity:0}.opacity-25{opacity:.25}.opacity-50{opacity:.5}.opacity-60{opacity:.6}.opacity-75{opacity:.75}.opacity-80{opacity:.8}.shadow{--tw-shadow:0 1px 3px 0 rgba(0,0,0,.1),0 1px 2px -1px rgba(0,0,0,.1);--tw-shadow-colored:0 1px 3px 0 var(--tw-shadow-color),0 1px 2px -1px var(--tw-shadow-color)}.shadow,.shadow-2xl{box-shadow:var(--tw-ring-offset-shadow,0 0 #0000),var(--tw-ring-shadow,0 0 #0000),var(--tw-shadow)}.shadow-2xl{--tw-shadow:0 25px 50px -12px rgba(0,0,0,.25);--tw-shadow-colored:0 25px 50px -12px var(--tw-shadow-color)}.shadow-lg{--tw-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1);--tw-shadow-colored:0 10px 15px -3px var(--tw-shadow-color),0 4px 6px -4px var(--tw-shadow-color)}.shadow-lg,.shadow-md{box-shadow:var(--tw-ring-offset-shadow,0 0 #0000),var(--tw-ring-shadow,0 0 #0000),var(--tw-shadow)}.shadow-md{--tw-shadow:0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -2px rgba(0,0,0,.1);--tw-shadow-colored:0 4px 6px -1px var(--tw-shadow-color),0 2px 4px -2px var(--tw-shadow-color)}.shadow-sm{--tw-shadow:0 1px 2px 0 rgba(0,0,0,.05);--tw-shadow-colored:0 1px 2px 0 var(--tw-shadow-color)}.shadow-sm,.shadow-xl{box-shadow:var(--tw-ring-offset-shadow,0 0 #0000),var(--tw-ring-shadow,0 0 #0000),var(--tw-shadow)}.shadow-xl{--tw-shadow:0 20px 25px -5px rgba(0,0,0,.1),0 8px 10px -6px rgba(0,0,0,.1);--tw-shadow-colored:0 20px 25px -5px var(--tw-shadow-color),0 8px 10px -6px var(--tw-shadow-color)}.outline-none{outline:2px solid transparent;outline-offset:2px}.outline{outline-style:solid}.ring-1{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(1px + var(--tw-ring-offset-width)) var(--tw-ring-color)}.ring-1,.ring-2{box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.ring-2{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(2px + var(--tw-ring-offset-width)) var(--tw-ring-color)}.ring-emerald-300{--tw-ring-opacity:1;--tw-ring-color:rgb(110 231 183/var(--tw-ring-opacity,1))}.ring-indigo-300{--tw-ring-opacity:1;--tw-ring-color:rgb(165 180 252/var(--tw-ring-opacity,1))}.ring-red-100{--tw-ring-opacity:1;--tw-ring-color:rgb(254 226 226/var(--tw-ring-opacity,1))}.ring-red-400{--tw-ring-opacity:1;--tw-ring-color:rgb(248 113 113/var(--tw-ring-opacity,1))}.ring-rose-400{--tw-ring-opacity:1;--tw-ring-color:rgb(251 113 133/var(--tw-ring-opacity,1))}.blur{--tw-blur:blur(8px)}.blur,.filter{filter:var(--tw-blur) var(--tw-brightness) var(--tw-contrast) var(--tw-grayscale) var(--tw-hue-rotate) var(--tw-invert) var(--tw-saturate) var(--tw-sepia) var(--tw-drop-shadow)}.backdrop-blur-sm{--tw-backdrop-blur:blur(4px);-webkit-backdrop-filter:var(--tw-backdrop-blur) var(--tw-backdrop-brightness) var(--tw-backdrop-contrast) var(--tw-backdrop-grayscale) var(--tw-backdrop-hue-rotate) var(--tw-backdrop-invert) var(--tw-backdrop-opacity) var(--tw-backdrop-saturate) var(--tw-backdrop-sepia);backdrop-filter:var(--tw-backdrop-blur) var(--tw-backdrop-brightness) var(--tw-backdrop-contrast) var(--tw-backdrop-grayscale) var(--tw-backdrop-hue-rotate) var(--tw-backdrop-invert) var(--tw-backdrop-opacity) var(--tw-backdrop-saturate) var(--tw-backdrop-sepia)}.transition{transition-duration:.15s;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,-webkit-backdrop-filter;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,backdrop-filter;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,opacity,box-shadow,transform,filter,backdrop-filter,-webkit-backdrop-filter;transition-timing-function:cubic-bezier(.4,0,.2,1)}.transition-all{transition-duration:.15s;transition-property:all;transition-timing-function:cubic-bezier(.4,0,.2,1)}.transition-colors{transition-duration:.15s;transition-property:color,background-color,border-color,text-decoration-color,fill,stroke;transition-timing-function:cubic-bezier(.4,0,.2,1)}.transition-opacity{transition-duration:.15s;transition-property:opacity;transition-timing-function:cubic-bezier(.4,0,.2,1)}.transition-shadow{transition-duration:.15s;transition-property:box-shadow;transition-timing-function:cubic-bezier(.4,0,.2,1)}.transition-transform{transition-property:transform;transition-timing-function:cubic-bezier(.4,0,.2,1)}.duration-150,.transition-transform{transition-duration:.15s}.duration-300{transition-duration:.3s}.ease-out{transition-timing-function:cubic-bezier(0,0,.2,1)}.\[-\:T\]{-:T}.\[a-zA-Z\:\\-\\\.\]{a-z-a--z:\-\.}.\[deadline\:\%s\]{deadline:%s}.\[deadline_task\:diario\]{deadline_task:diario}.\[deadline_task\:horario\]{deadline_task:horario}.\[email\:log\]{email:log}.\[email\:resend-api\]{email:resend-api}.\[email\:smtp\]{email:smtp}.\[entregas\:registrar\]{entregas:registrar}.\[entregas\:reporte\]{entregas:reporte}.\[salud\:latido\]{salud:latido}.\[salud\:scheduler\]{salud:scheduler}.\[tickets\:guardar\]{tickets:guardar}.file\:mr-2::file-selector-button{margin-right:.5rem}.file\:rounded-md::file-selector-button{border-radius:.375rem}.file\:border-0::file-selector-button{border-width:0}.file\:bg-indigo-50::file-selector-button{--tw-bg-opacity:1;background-color:rgb(238 242 255/var(--tw-bg-opacity,1))}.file\:px-3::file-selector-button{padding-left:.75rem;padding-right:.75rem}.file\:py-1\.5::file-selector-button{padding-bottom:.375rem;padding-top:.375rem}.file\:text-xs::file-selector-button{font-size:.75rem;line-height:1rem}.file\:font-semibold::file-selector-button{font-weight:600}.file\:text-indigo-700::file-selector-button{--tw-text-opacity:1;color:rgb(67 56 202/var(--tw-text-opacity,1))}.backdrop\:bg-black\/40::backdrop{background-color:rgba(0,0,0,.4)}.after\:absolute:after{content:var(--tw-content);position:absolute}.after\:left-0\.5:after{content:var(--tw-content);left:.125rem}.after\:top-0\.5:after{content:var(--tw-content);top:.125rem}.after\:h-4:after{content:var(--tw-content);height:1rem}.after\:w-4:after{content:var(--tw-content);width:1rem}.after\:rounded-full:after{border-radius:9999px;content:var(--tw-content)}.after\:bg-white:after{content:var(--tw-content);--tw-bg-opacity:1;background-color:rgb(255 255 255/var(--tw-bg-opacity,1))}.after\:transition-all:after{content:var(--tw-content);transition-duration:.15s;transition-property:all;transition-timing-function:cubic-bezier(.4,0,.2,1)}.after\:content-\[\'\'\]:after{--tw-content:"";content:var(--tw-content)}.first\:border-0:first-child,.last\:border-0:last-child{border-width:0}.focus-within\:border-indigo-500:focus-within{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.focus-within\:ring-2:focus-within{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(2px + var(--tw-ring-offset-width)) var(--tw-ring-color);box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.focus-within\:ring-indigo-500:focus-within{--tw-ring-opacity:1;--tw-ring-color:rgb(99 102 241/var(--tw-ring-opacity,1))}.hover\:border-amber-300:hover{--tw-border-opacity:1;border-color:rgb(252 211 77/var(--tw-border-opacity,1))}.hover\:border-emerald-300:hover{--tw-border-opacity:1;border-color:rgb(110 231 183/var(--tw-border-opacity,1))}.hover\:border-emerald-400:hover{--tw-border-opacity:1;border-color:rgb(52 211 153/var(--tw-border-opacity,1))}.hover\:border-indigo-300:hover{--tw-border-opacity:1;border-color:rgb(165 180 252/var(--tw-border-opacity,1))}.hover\:border-indigo-400:hover{--tw-border-opacity:1;border-color:rgb(129 140 248/var(--tw-border-opacity,1))}.hover\:border-red-300:hover{--tw-border-opacity:1;border-color:rgb(252 165 165/var(--tw-border-opacity,1))}.hover\:border-rose-200:hover{--tw-border-opacity:1;border-color:rgb(254 205 211/var(--tw-border-opacity,1))}.hover\:border-rose-300:hover{--tw-border-opacity:1;border-color:rgb(253 164 175/var(--tw-border-opacity,1))}.hover\:border-slate-200:hover{--tw-border-opacity:1;border-color:rgb(226 232 240/var(--tw-border-opacity,1))}.hover\:border-slate-300:hover{--tw-border-opacity:1;border-color:rgb(203 213 225/var(--tw-border-opacity,1))}.hover\:bg-amber-100:hover{--tw-bg-opacity:1;background-color:rgb(254 243 199/var(--tw-bg-opacity,1))}.hover\:bg-amber-200:hover{--tw-bg-opacity:1;background-color:rgb(253 230 138/var(--tw-bg-opacity,1))}.hover\:bg-amber-50:hover{--tw-bg-opacity:1;background-color:rgb(255 251 235/var(--tw-bg-opacity,1))}.hover\:bg-blue-200:hover{--tw-bg-opacity:1;background-color:rgb(191 219 254/var(--tw-bg-opacity,1))}.hover\:bg-emerald-100:hover{--tw-bg-opacity:1;background-color:rgb(209 250 229/var(--tw-bg-opacity,1))}.hover\:bg-emerald-50:hover{--tw-bg-opacity:1;background-color:rgb(236 253 245/var(--tw-bg-opacity,1))}.hover\:bg-emerald-700:hover{--tw-bg-opacity:1;background-color:rgb(4 120 87/var(--tw-bg-opacity,1))}.hover\:bg-indigo-100:hover{--tw-bg-opacity:1;background-color:rgb(224 231 255/var(--tw-bg-opacity,1))}.hover\:bg-indigo-50:hover{--tw-bg-opacity:1;background-color:rgb(238 242 255/var(--tw-bg-opacity,1))}.hover\:bg-indigo-50\/30:hover{background-color:rgba(238,242,255,.3)}.hover\:bg-indigo-50\/50:hover{background-color:rgba(238,242,255,.5)}.hover\:bg-indigo-700:hover{--tw-bg-opacity:1;background-color:rgb(67 56 202/var(--tw-bg-opacity,1))}.hover\:bg-purple-200:hover{--tw-bg-opacity:1;background-color:rgb(233 213 255/var(--tw-bg-opacity,1))}.hover\:bg-red-100:hover{--tw-bg-opacity:1;background-color:rgb(254 226 226/var(--tw-bg-opacity,1))}.hover\:bg-red-200:hover{--tw-bg-opacity:1;background-color:rgb(254 202 202/var(--tw-bg-opacity,1))}.hover\:bg-red-50:hover{--tw-bg-opacity:1;background-color:rgb(254 242 242/var(--tw-bg-opacity,1))}.hover\:bg-red-700:hover{--tw-bg-opacity:1;background-color:rgb(185 28 28/var(--tw-bg-opacity,1))}.hover\:bg-rose-100:hover{--tw-bg-opacity:1;background-color:rgb(255 228 230/var(--tw-bg-opacity,1))}.hover\:bg-rose-50:hover{--tw-bg-opacity:1;background-color:rgb(255 241 242/var(--tw-bg-opacity,1))}.hover\:bg-sky-50:hover{--tw-bg-opacity:1;background-color:rgb(240 249 255/var(--tw-bg-opacity,1))}.hover\:bg-sky-700:hover{--tw-bg-opacity:1;background-color:rgb(3 105 161/var(--tw-bg-opacity,1))}.hover\:bg-slate-100:hover{--tw-bg-opacity:1;background-color:rgb(241 245 249/var(--tw-bg-opacity,1))}.hover\:bg-slate-200:hover{--tw-bg-opacity:1;background-color:rgb(226 232 240/var(--tw-bg-opacity,1))}.hover\:bg-slate-300:hover{--tw-bg-opacity:1;background-color:rgb(203 213 225/var(--tw-bg-opacity,1))}.hover\:bg-slate-50:hover{--tw-bg-opacity:1;background-color:rgb(248 250 252/var(--tw-bg-opacity,1))}.hover\:bg-slate-50\/50:hover{background-color:rgba(248,250,252,.5)}.hover\:bg-slate-800:hover{--tw-bg-opacity:1;background-color:rgb(30 41 59/var(--tw-bg-opacity,1))}.hover\:bg-white:hover{--tw-bg-opacity:1;background-color:rgb(255 255 255/var(--tw-bg-opacity,1))}.hover\:bg-white\/20:hover{background-color:hsla(0,0%,100%,.2)}.hover\:bg-white\/60:hover{background-color:hsla(0,0%,100%,.6)}.hover\:from-amber-700:hover{--tw-gradient-from:#b45309 var(--tw-gradient-from-position);--tw-gradient-to:rgba(180,83,9,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.hover\:from-indigo-700:hover{--tw-gradient-from:#4338ca var(--tw-gradient-from-position);--tw-gradient-to:rgba(67,56,202,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.hover\:from-purple-700:hover{--tw-gradient-from:#7e22ce var(--tw-gradient-from-position);--tw-gradient-to:rgba(126,34,206,0) var(--tw-gradient-to-position);--tw-gradient-stops:var(--tw-gradient-from),var(--tw-gradient-to)}.hover\:to-pink-700:hover{--tw-gradient-to:#be185d var(--tw-gradient-to-position)}.hover\:to-purple-700:hover{--tw-gradient-to:#7e22ce var(--tw-gradient-to-position)}.hover\:to-rose-700:hover{--tw-gradient-to:#be123c var(--tw-gradient-to-position)}.hover\:text-amber-900:hover{--tw-text-opacity:1;color:rgb(120 53 15/var(--tw-text-opacity,1))}.hover\:text-emerald-800:hover{--tw-text-opacity:1;color:rgb(6 95 70/var(--tw-text-opacity,1))}.hover\:text-indigo-600:hover{--tw-text-opacity:1;color:rgb(79 70 229/var(--tw-text-opacity,1))}.hover\:text-indigo-700:hover{--tw-text-opacity:1;color:rgb(67 56 202/var(--tw-text-opacity,1))}.hover\:text-indigo-800:hover{--tw-text-opacity:1;color:rgb(55 48 163/var(--tw-text-opacity,1))}.hover\:text-red-500:hover{--tw-text-opacity:1;color:rgb(239 68 68/var(--tw-text-opacity,1))}.hover\:text-red-600:hover{--tw-text-opacity:1;color:rgb(220 38 38/var(--tw-text-opacity,1))}.hover\:text-red-700:hover{--tw-text-opacity:1;color:rgb(185 28 28/var(--tw-text-opacity,1))}.hover\:text-red-800:hover{--tw-text-opacity:1;color:rgb(153 27 27/var(--tw-text-opacity,1))}.hover\:text-rose-600:hover{--tw-text-opacity:1;color:rgb(225 29 72/var(--tw-text-opacity,1))}.hover\:text-rose-700:hover{--tw-text-opacity:1;color:rgb(190 18 60/var(--tw-text-opacity,1))}.hover\:text-rose-800:hover{--tw-text-opacity:1;color:rgb(159 18 57/var(--tw-text-opacity,1))}.hover\:text-slate-600:hover{--tw-text-opacity:1;color:rgb(71 85 105/var(--tw-text-opacity,1))}.hover\:text-slate-700:hover{--tw-text-opacity:1;color:rgb(51 65 85/var(--tw-text-opacity,1))}.hover\:text-slate-800:hover{--tw-text-opacity:1;color:rgb(30 41 59/var(--tw-text-opacity,1))}.hover\:text-slate-900:hover{--tw-text-opacity:1;color:rgb(15 23 42/var(--tw-text-opacity,1))}.hover\:underline:hover{text-decoration-line:underline}.hover\:opacity-90:hover{opacity:.9}.hover\:shadow-lg:hover{--tw-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1);--tw-shadow-colored:0 10px 15px -3px var(--tw-shadow-color),0 4px 6px -4px var(--tw-shadow-color)}.hover\:shadow-lg:hover,.hover\:shadow-md:hover{box-shadow:var(--tw-ring-offset-shadow,0 0 #0000),var(--tw-ring-shadow,0 0 #0000),var(--tw-shadow)}.hover\:shadow-md:hover{--tw-shadow:0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -2px rgba(0,0,0,.1);--tw-shadow-colored:0 4px 6px -1px var(--tw-shadow-color),0 2px 4px -2px var(--tw-shadow-color)}.hover\:shadow-sm:hover{--tw-shadow:0 1px 2px 0 rgba(0,0,0,.05);--tw-shadow-colored:0 1px 2px 0 var(--tw-shadow-color);box-shadow:var(--tw-ring-offset-shadow,0 0 #0000),var(--tw-ring-shadow,0 0 #0000),var(--tw-shadow)}.hover\:ring-2:hover{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(2px + var(--tw-ring-offset-width)) var(--tw-ring-color);box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.hover\:ring-inset:hover{--tw-ring-inset:inset}.hover\:ring-indigo-400:hover{--tw-ring-opacity:1;--tw-ring-color:rgb(129 140 248/var(--tw-ring-opacity,1))}.hover\:brightness-95:hover{--tw-brightness:brightness(.95);filter:var(--tw-blur) var(--tw-brightness) var(--tw-contrast) var(--tw-grayscale) var(--tw-hue-rotate) var(--tw-invert) var(--tw-saturate) var(--tw-sepia) var(--tw-drop-shadow)}.hover\:file\:bg-indigo-100::file-selector-button:hover{--tw-bg-opacity:1;background-color:rgb(224 231 255/var(--tw-bg-opacity,1))}.focus\:border-amber-500:focus{--tw-border-opacity:1;border-color:rgb(245 158 11/var(--tw-border-opacity,1))}.focus\:border-indigo-400:focus{--tw-border-opacity:1;border-color:rgb(129 140 248/var(--tw-border-opacity,1))}.focus\:border-indigo-500:focus{--tw-border-opacity:1;border-color:rgb(99 102 241/var(--tw-border-opacity,1))}.focus\:bg-indigo-50\/30:focus{background-color:rgba(238,242,255,.3)}.focus\:outline-none:focus{outline:2px solid transparent;outline-offset:2px}.focus\:ring-0:focus{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(var(--tw-ring-offset-width)) var(--tw-ring-color)}.focus\:ring-0:focus,.focus\:ring-1:focus{box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.focus\:ring-1:focus{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(1px + var(--tw-ring-offset-width)) var(--tw-ring-color)}.focus\:ring-2:focus{--tw-ring-offset-shadow:var(--tw-ring-inset) 0 0 0 var(--tw-ring-offset-width) var(--tw-ring-offset-color);--tw-ring-shadow:var(--tw-ring-inset) 0 0 0 calc(2px + var(--tw-ring-offset-width)) var(--tw-ring-color);box-shadow:var(--tw-ring-offset-shadow),var(--tw-ring-shadow),var(--tw-shadow,0 0 #0000)}.focus\:ring-amber-300:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(252 211 77/var(--tw-ring-opacity,1))}.focus\:ring-amber-500:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(245 158 11/var(--tw-ring-opacity,1))}.focus\:ring-emerald-300:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(110 231 183/var(--tw-ring-opacity,1))}.focus\:ring-emerald-500:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(16 185 129/var(--tw-ring-opacity,1))}.focus\:ring-indigo-300:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(165 180 252/var(--tw-ring-opacity,1))}.focus\:ring-indigo-500:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(99 102 241/var(--tw-ring-opacity,1))}.focus\:ring-red-300:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(252 165 165/var(--tw-ring-opacity,1))}.focus\:ring-rose-300:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(253 164 175/var(--tw-ring-opacity,1))}.focus\:ring-sky-500:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(14 165 233/var(--tw-ring-opacity,1))}.focus\:ring-slate-300:focus{--tw-ring-opacity:1;--tw-ring-color:rgb(203 213 225/var(--tw-ring-opacity,1))}.active\:cursor-grabbing:active{cursor:grabbing}.disabled\:opacity-50:disabled{opacity:.5}.group[open] .group-open\:rotate-90{--tw-rotate:90deg;transform:translate(var(--tw-translate-x),var(--tw-translate-y)) rotate(var(--tw-rotate)) skewX(var(--tw-skew-x)) skewY(var(--tw-skew-y)) scaleX(var(--tw-scale-x)) scaleY(var(--tw-scale-y))}.group[open] .group-open\:bg-indigo-100{--tw-bg-opacity:1;background-color:rgb(224 231 255/var(--tw-bg-opacity,1))}.group[open] .group-open\:text-indigo-700{--tw-text-opacity:1;color:rgb(67 56 202/var(--tw-text-opacity,1))}.group:hover .group-hover\:visible{visibility:visible}.group:hover .group-hover\:bg-amber-600{--tw-bg-opacity:1;background-color:rgb(217 119 6/var(--tw-bg-opacity,1))}.group:hover .group-hover\:bg-blue-600{--tw-bg-opacity:1;background-color:rgb(37 99 235/var(--tw-bg-opacity,1))}.group:hover .group-hover\:bg-emerald-600{--tw-bg-opacity:1;background-color:rgb(5 150 105/var(--tw-bg-opacity,1))}.group:hover .group-hover\:bg-indigo-600{--tw-bg-opacity:1;background-color:rgb(79 70 229/var(--tw-bg-opacity,1))}.group:hover .group-hover\:text-indigo-700{--tw-text-opacity:1;color:rgb(67 56 202/var(--tw-text-opacity,1))}.group:hover .group-hover\:text-white{--tw-text-opacity:1;color:rgb(255 255 255/var(--tw-text-opacity,1))}.group:hover .group-hover\:opacity-100{opacity:1}.peer:checked~.peer-checked\:bg-indigo-600{--tw-bg-opacity:1;background-color:rgb(79 70 229/var(--tw-bg-opacity,1))}.peer:checked~.peer-checked\:after\:translate-x-4:after{content:var(--tw-content);--tw-translate-x:1rem;transform:translate(var(--tw-translate-x),var(--tw-translate-y)) rotate(var(--tw-rotate)) skewX(var(--tw-skew-x)) skewY(var(--tw-skew-y)) scaleX(var(--tw-scale-x)) scaleY(var(--tw-scale-y))}@media (min-width:640px){.sm\:block{display:block}.sm\:inline-block{display:inline-block}.sm\:grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.sm\:grid-cols-3{grid-template-columns:repeat(3,minmax(0,1fr))}.sm\:grid-cols-5{grid-template-columns:repeat(5,minmax(0,1fr))}}@media (min-width:768px){.md\:block{display:block}.md\:inline-block{display:inline-block}.md\:inline{display:inline}.md\:grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.md\:grid-cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}.md\:grid-cols-5{grid-template-columns:repeat(5,minmax(0,1fr))}}@media (min-width:1024px){.lg\:inline{display:inline}.lg\:grid-cols-2{grid-template-columns:repeat(2,minmax(0,1fr))}.lg\:grid-cols-3{grid-template-columns:repeat(3,minmax(0,1fr))}.lg\:grid-cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}.lg\:grid-cols-5{grid-template-columns:repeat(5,minmax(0,1fr))}.lg\:grid-cols-7{grid-template-columns:repeat(7,minmax(0,1fr))}}@media (min-width:1280px){.xl\:inline-flex{display:inline-flex}.xl\:grid-cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}}
\ No newline at end of file
diff --git a/app/static/css/tailwind.src.css b/app/static/css/tailwind.src.css
new file mode 100644
index 0000000..a611f86
--- /dev/null
+++ b/app/static/css/tailwind.src.css
@@ -0,0 +1,10 @@
+/*
+ * Fuente de Tailwind CSS.
+ *
+ * Este fichero NO se sirve: es la entrada de la compilacion que produce
+ * `app/static/css/tailwind.css` (el que se sirve). Ver tailwind.config.js
+ * para el comando exacto de compilacion.
+ */
+@tailwind base;
+@tailwind components;
+@tailwind utilities;
diff --git a/app/static/fonts/inter-latin-ext.woff2 b/app/static/fonts/inter-latin-ext.woff2
new file mode 100644
index 0000000..479d010
Binary files /dev/null and b/app/static/fonts/inter-latin-ext.woff2 differ
diff --git a/app/static/fonts/inter-latin.woff2 b/app/static/fonts/inter-latin.woff2
new file mode 100644
index 0000000..d15208d
Binary files /dev/null and b/app/static/fonts/inter-latin.woff2 differ
diff --git a/app/static/js/sortable.min.js b/app/static/js/sortable.min.js
new file mode 100644
index 0000000..bb99533
--- /dev/null
+++ b/app/static/js/sortable.min.js
@@ -0,0 +1,2 @@
+/*! Sortable 1.15.2 - MIT | git://github.com/SortableJS/Sortable.git */
+!function(t,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):(t=t||self).Sortable=e()}(this,function(){"use strict";function e(e,t){var n,o=Object.keys(e);return Object.getOwnPropertySymbols&&(n=Object.getOwnPropertySymbols(e),t&&(n=n.filter(function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable})),o.push.apply(o,n)),o}function I(o){for(var t=1;t<arguments.length;t++){var i=null!=arguments[t]?arguments[t]:{};t%2?e(Object(i),!0).forEach(function(t){var e,n;e=o,t=i[n=t],n in e?Object.defineProperty(e,n,{value:t,enumerable:!0,configurable:!0,writable:!0}):e[n]=t}):Object.getOwnPropertyDescriptors?Object.defineProperties(o,Object.getOwnPropertyDescriptors(i)):e(Object(i)).forEach(function(t){Object.defineProperty(o,t,Object.getOwnPropertyDescriptor(i,t))})}return o}function o(t){return(o="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(t){return typeof t}:function(t){return t&&"function"==typeof Symbol&&t.constructor===Symbol&&t!==Symbol.prototype?"symbol":typeof t})(t)}function a(){return(a=Object.assign||function(t){for(var e=1;e<arguments.length;e++){var n,o=arguments[e];for(n in o)Object.prototype.hasOwnProperty.call(o,n)&&(t[n]=o[n])}return t}).apply(this,arguments)}function i(t,e){if(null==t)return{};var n,o=function(t,e){if(null==t)return{};for(var n,o={},i=Object.keys(t),r=0;r<i.length;r++)n=i[r],0<=e.indexOf(n)||(o[n]=t[n]);return o}(t,e);if(Object.getOwnPropertySymbols)for(var i=Object.getOwnPropertySymbols(t),r=0;r<i.length;r++)n=i[r],0<=e.indexOf(n)||Object.prototype.propertyIsEnumerable.call(t,n)&&(o[n]=t[n]);return o}function r(t){return function(t){if(Array.isArray(t))return l(t)}(t)||function(t){if("undefined"!=typeof Symbol&&null!=t[Symbol.iterator]||null!=t["@@iterator"])return Array.from(t)}(t)||function(t,e){if(t){if("string"==typeof t)return l(t,e);var n=Object.prototype.toString.call(t).slice(8,-1);return"Map"===(n="Object"===n&&t.constructor?t.constructor.name:n)||"Set"===n?Array.from(t):"Arguments"===n||/^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n)?l(t,e):void 0}}(t)||function(){throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.")}()}function l(t,e){(null==e||e>t.length)&&(e=t.length);for(var n=0,o=new Array(e);n<e;n++)o[n]=t[n];return o}function t(t){if("undefined"!=typeof window&&window.navigator)return!!navigator.userAgent.match(t)}var y=t(/(?:Trident.*rv[ :]?11\.|msie|iemobile|Windows Phone)/i),w=t(/Edge/i),s=t(/firefox/i),u=t(/safari/i)&&!t(/chrome/i)&&!t(/android/i),n=t(/iP(ad|od|hone)/i),c=t(/chrome/i)&&t(/android/i),d={capture:!1,passive:!1};function h(t,e,n){t.addEventListener(e,n,!y&&d)}function f(t,e,n){t.removeEventListener(e,n,!y&&d)}function p(t,e){if(e&&(">"===e[0]&&(e=e.substring(1)),t))try{if(t.matches)return t.matches(e);if(t.msMatchesSelector)return t.msMatchesSelector(e);if(t.webkitMatchesSelector)return t.webkitMatchesSelector(e)}catch(t){return}}function P(t,e,n,o){if(t){n=n||document;do{if(null!=e&&(">"!==e[0]||t.parentNode===n)&&p(t,e)||o&&t===n)return t}while(t!==n&&(t=(i=t).host&&i!==document&&i.host.nodeType?i.host:i.parentNode))}var i;return null}var g,m=/\s+/g;function k(t,e,n){var o;t&&e&&(t.classList?t.classList[n?"add":"remove"](e):(o=(" "+t.className+" ").replace(m," ").replace(" "+e+" "," "),t.className=(o+(n?" "+e:"")).replace(m," ")))}function R(t,e,n){var o=t&&t.style;if(o){if(void 0===n)return document.defaultView&&document.defaultView.getComputedStyle?n=document.defaultView.getComputedStyle(t,""):t.currentStyle&&(n=t.currentStyle),void 0===e?n:n[e];o[e=!(e in o||-1!==e.indexOf("webkit"))?"-webkit-"+e:e]=n+("string"==typeof n?"":"px")}}function v(t,e){var n="";if("string"==typeof t)n=t;else do{var o=R(t,"transform")}while(o&&"none"!==o&&(n=o+" "+n),!e&&(t=t.parentNode));var i=window.DOMMatrix||window.WebKitCSSMatrix||window.CSSMatrix||window.MSCSSMatrix;return i&&new i(n)}function b(t,e,n){if(t){var o=t.getElementsByTagName(e),i=0,r=o.length;if(n)for(;i<r;i++)n(o[i],i);return o}return[]}function O(){var t=document.scrollingElement;return t||document.documentElement}function X(t,e,n,o,i){if(t.getBoundingClientRect||t===window){var r,a,l,s,c,u,d=t!==window&&t.parentNode&&t!==O()?(a=(r=t.getBoundingClientRect()).top,l=r.left,s=r.bottom,c=r.right,u=r.height,r.width):(l=a=0,s=window.innerHeight,c=window.innerWidth,u=window.innerHeight,window.innerWidth);if((e||n)&&t!==window&&(i=i||t.parentNode,!y))do{if(i&&i.getBoundingClientRect&&("none"!==R(i,"transform")||n&&"static"!==R(i,"position"))){var h=i.getBoundingClientRect();a-=h.top+parseInt(R(i,"border-top-width")),l-=h.left+parseInt(R(i,"border-left-width")),s=a+r.height,c=l+r.width;break}}while(i=i.parentNode);return o&&t!==window&&(o=(e=v(i||t))&&e.a,t=e&&e.d,e&&(s=(a/=t)+(u/=t),c=(l/=o)+(d/=o))),{top:a,left:l,bottom:s,right:c,width:d,height:u}}}function Y(t,e,n){for(var o=M(t,!0),i=X(t)[e];o;){var r=X(o)[n];if(!("top"===n||"left"===n?r<=i:i<=r))return o;if(o===O())break;o=M(o,!1)}return!1}function B(t,e,n,o){for(var i=0,r=0,a=t.children;r<a.length;){if("none"!==a[r].style.display&&a[r]!==Ft.ghost&&(o||a[r]!==Ft.dragged)&&P(a[r],n.draggable,t,!1)){if(i===e)return a[r];i++}r++}return null}function F(t,e){for(var n=t.lastElementChild;n&&(n===Ft.ghost||"none"===R(n,"display")||e&&!p(n,e));)n=n.previousElementSibling;return n||null}function j(t,e){var n=0;if(!t||!t.parentNode)return-1;for(;t=t.previousElementSibling;)"TEMPLATE"===t.nodeName.toUpperCase()||t===Ft.clone||e&&!p(t,e)||n++;return n}function E(t){var e=0,n=0,o=O();if(t)do{var i=v(t),r=i.a,i=i.d}while(e+=t.scrollLeft*r,n+=t.scrollTop*i,t!==o&&(t=t.parentNode));return[e,n]}function M(t,e){if(!t||!t.getBoundingClientRect)return O();var n=t,o=!1;do{if(n.clientWidth<n.scrollWidth||n.clientHeight<n.scrollHeight){var i=R(n);if(n.clientWidth<n.scrollWidth&&("auto"==i.overflowX||"scroll"==i.overflowX)||n.clientHeight<n.scrollHeight&&("auto"==i.overflowY||"scroll"==i.overflowY)){if(!n.getBoundingClientRect||n===document.body)return O();if(o||e)return n;o=!0}}}while(n=n.parentNode);return O()}function D(t,e){return Math.round(t.top)===Math.round(e.top)&&Math.round(t.left)===Math.round(e.left)&&Math.round(t.height)===Math.round(e.height)&&Math.round(t.width)===Math.round(e.width)}function S(e,n){return function(){var t;g||(1===(t=arguments).length?e.call(this,t[0]):e.apply(this,t),g=setTimeout(function(){g=void 0},n))}}function H(t,e,n){t.scrollLeft+=e,t.scrollTop+=n}function _(t){var e=window.Polymer,n=window.jQuery||window.Zepto;return e&&e.dom?e.dom(t).cloneNode(!0):n?n(t).clone(!0)[0]:t.cloneNode(!0)}function C(t,e){R(t,"position","absolute"),R(t,"top",e.top),R(t,"left",e.left),R(t,"width",e.width),R(t,"height",e.height)}function T(t){R(t,"position",""),R(t,"top",""),R(t,"left",""),R(t,"width",""),R(t,"height","")}function L(n,o,i){var r={};return Array.from(n.children).forEach(function(t){var e;P(t,o.draggable,n,!1)&&!t.animated&&t!==i&&(e=X(t),r.left=Math.min(null!==(t=r.left)&&void 0!==t?t:1/0,e.left),r.top=Math.min(null!==(t=r.top)&&void 0!==t?t:1/0,e.top),r.right=Math.max(null!==(t=r.right)&&void 0!==t?t:-1/0,e.right),r.bottom=Math.max(null!==(t=r.bottom)&&void 0!==t?t:-1/0,e.bottom))}),r.width=r.right-r.left,r.height=r.bottom-r.top,r.x=r.left,r.y=r.top,r}var K="Sortable"+(new Date).getTime();function x(){var e,o=[];return{captureAnimationState:function(){o=[],this.options.animation&&[].slice.call(this.el.children).forEach(function(t){var e,n;"none"!==R(t,"display")&&t!==Ft.ghost&&(o.push({target:t,rect:X(t)}),e=I({},o[o.length-1].rect),!t.thisAnimationDuration||(n=v(t,!0))&&(e.top-=n.f,e.left-=n.e),t.fromRect=e)})},addAnimationState:function(t){o.push(t)},removeAnimationState:function(t){o.splice(function(t,e){for(var n in t)if(t.hasOwnProperty(n))for(var o in e)if(e.hasOwnProperty(o)&&e[o]===t[n][o])return Number(n);return-1}(o,{target:t}),1)},animateAll:function(t){var c=this;if(!this.options.animation)return clearTimeout(e),void("function"==typeof t&&t());var u=!1,d=0;o.forEach(function(t){var e=0,n=t.target,o=n.fromRect,i=X(n),r=n.prevFromRect,a=n.prevToRect,l=t.rect,s=v(n,!0);s&&(i.top-=s.f,i.left-=s.e),n.toRect=i,n.thisAnimationDuration&&D(r,i)&&!D(o,i)&&(l.top-i.top)/(l.left-i.left)==(o.top-i.top)/(o.left-i.left)&&(t=l,s=r,r=a,a=c.options,e=Math.sqrt(Math.pow(s.top-t.top,2)+Math.pow(s.left-t.left,2))/Math.sqrt(Math.pow(s.top-r.top,2)+Math.pow(s.left-r.left,2))*a.animation),D(i,o)||(n.prevFromRect=o,n.prevToRect=i,e=e||c.options.animation,c.animate(n,l,i,e)),e&&(u=!0,d=Math.max(d,e),clearTimeout(n.animationResetTimer),n.animationResetTimer=setTimeout(function(){n.animationTime=0,n.prevFromRect=null,n.fromRect=null,n.prevToRect=null,n.thisAnimationDuration=null},e),n.thisAnimationDuration=e)}),clearTimeout(e),u?e=setTimeout(function(){"function"==typeof t&&t()},d):"function"==typeof t&&t(),o=[]},animate:function(t,e,n,o){var i,r;o&&(R(t,"transition",""),R(t,"transform",""),i=(r=v(this.el))&&r.a,r=r&&r.d,i=(e.left-n.left)/(i||1),r=(e.top-n.top)/(r||1),t.animatingX=!!i,t.animatingY=!!r,R(t,"transform","translate3d("+i+"px,"+r+"px,0)"),this.forRepaintDummy=t.offsetWidth,R(t,"transition","transform "+o+"ms"+(this.options.easing?" "+this.options.easing:"")),R(t,"transform","translate3d(0,0,0)"),"number"==typeof t.animated&&clearTimeout(t.animated),t.animated=setTimeout(function(){R(t,"transition",""),R(t,"transform",""),t.animated=!1,t.animatingX=!1,t.animatingY=!1},o))}}}var A=[],N={initializeByDefault:!0},W={mount:function(e){for(var t in N)!N.hasOwnProperty(t)||t in e||(e[t]=N[t]);A.forEach(function(t){if(t.pluginName===e.pluginName)throw"Sortable: Cannot mount plugin ".concat(e.pluginName," more than once")}),A.push(e)},pluginEvent:function(e,n,o){var t=this;this.eventCanceled=!1,o.cancel=function(){t.eventCanceled=!0};var i=e+"Global";A.forEach(function(t){n[t.pluginName]&&(n[t.pluginName][i]&&n[t.pluginName][i](I({sortable:n},o)),n.options[t.pluginName]&&n[t.pluginName][e]&&n[t.pluginName][e](I({sortable:n},o)))})},initializePlugins:function(n,o,i,t){for(var e in A.forEach(function(t){var e=t.pluginName;(n.options[e]||t.initializeByDefault)&&((t=new t(n,o,n.options)).sortable=n,t.options=n.options,n[e]=t,a(i,t.defaults))}),n.options){var r;n.options.hasOwnProperty(e)&&(void 0!==(r=this.modifyOption(n,e,n.options[e]))&&(n.options[e]=r))}},getEventProperties:function(e,n){var o={};return A.forEach(function(t){"function"==typeof t.eventProperties&&a(o,t.eventProperties.call(n[t.pluginName],e))}),o},modifyOption:function(e,n,o){var i;return A.forEach(function(t){e[t.pluginName]&&t.optionListeners&&"function"==typeof t.optionListeners[n]&&(i=t.optionListeners[n].call(e[t.pluginName],o))}),i}};function z(t){var e=t.sortable,n=t.rootEl,o=t.name,i=t.targetEl,r=t.cloneEl,a=t.toEl,l=t.fromEl,s=t.oldIndex,c=t.newIndex,u=t.oldDraggableIndex,d=t.newDraggableIndex,h=t.originalEvent,f=t.putSortable,p=t.extraEventProperties;if(e=e||n&&n[K]){var g,m=e.options,t="on"+o.charAt(0).toUpperCase()+o.substr(1);!window.CustomEvent||y||w?(g=document.createEvent("Event")).initEvent(o,!0,!0):g=new CustomEvent(o,{bubbles:!0,cancelable:!0}),g.to=a||n,g.from=l||n,g.item=i||n,g.clone=r,g.oldIndex=s,g.newIndex=c,g.oldDraggableIndex=u,g.newDraggableIndex=d,g.originalEvent=h,g.pullMode=f?f.lastPutMode:void 0;var v,b=I(I({},p),W.getEventProperties(o,e));for(v in b)g[v]=b[v];n&&n.dispatchEvent(g),m[t]&&m[t].call(e,g)}}function G(t,e){var n=(o=2<arguments.length&&void 0!==arguments[2]?arguments[2]:{}).evt,o=i(o,U);W.pluginEvent.bind(Ft)(t,e,I({dragEl:V,parentEl:Z,ghostEl:$,rootEl:Q,nextEl:J,lastDownEl:tt,cloneEl:et,cloneHidden:nt,dragStarted:gt,putSortable:st,activeSortable:Ft.active,originalEvent:n,oldIndex:ot,oldDraggableIndex:rt,newIndex:it,newDraggableIndex:at,hideGhostForTarget:Rt,unhideGhostForTarget:Xt,cloneNowHidden:function(){nt=!0},cloneNowShown:function(){nt=!1},dispatchSortableEvent:function(t){q({sortable:e,name:t,originalEvent:n})}},o))}var U=["evt"];function q(t){z(I({putSortable:st,cloneEl:et,targetEl:V,rootEl:Q,oldIndex:ot,oldDraggableIndex:rt,newIndex:it,newDraggableIndex:at},t))}var V,Z,$,Q,J,tt,et,nt,ot,it,rt,at,lt,st,ct,ut,dt,ht,ft,pt,gt,mt,vt,bt,yt,wt=!1,Et=!1,Dt=[],St=!1,_t=!1,Ct=[],Tt=!1,xt=[],Ot="undefined"!=typeof document,Mt=n,At=w||y?"cssFloat":"float",Nt=Ot&&!c&&!n&&"draggable"in document.createElement("div"),It=function(){if(Ot){if(y)return!1;var t=document.createElement("x");return t.style.cssText="pointer-events:auto","auto"===t.style.pointerEvents}}(),Pt=function(t,e){var n=R(t),o=parseInt(n.width)-parseInt(n.paddingLeft)-parseInt(n.paddingRight)-parseInt(n.borderLeftWidth)-parseInt(n.borderRightWidth),i=B(t,0,e),r=B(t,1,e),a=i&&R(i),l=r&&R(r),s=a&&parseInt(a.marginLeft)+parseInt(a.marginRight)+X(i).width,t=l&&parseInt(l.marginLeft)+parseInt(l.marginRight)+X(r).width;if("flex"===n.display)return"column"===n.flexDirection||"column-reverse"===n.flexDirection?"vertical":"horizontal";if("grid"===n.display)return n.gridTemplateColumns.split(" ").length<=1?"vertical":"horizontal";if(i&&a.float&&"none"!==a.float){e="left"===a.float?"left":"right";return!r||"both"!==l.clear&&l.clear!==e?"horizontal":"vertical"}return i&&("block"===a.display||"flex"===a.display||"table"===a.display||"grid"===a.display||o<=s&&"none"===n[At]||r&&"none"===n[At]&&o<s+t)?"vertical":"horizontal"},kt=function(t){function l(r,a){return function(t,e,n,o){var i=t.options.group.name&&e.options.group.name&&t.options.group.name===e.options.group.name;if(null==r&&(a||i))return!0;if(null==r||!1===r)return!1;if(a&&"clone"===r)return r;if("function"==typeof r)return l(r(t,e,n,o),a)(t,e,n,o);e=(a?t:e).options.group.name;return!0===r||"string"==typeof r&&r===e||r.join&&-1<r.indexOf(e)}}var e={},n=t.group;n&&"object"==o(n)||(n={name:n}),e.name=n.name,e.checkPull=l(n.pull,!0),e.checkPut=l(n.put),e.revertClone=n.revertClone,t.group=e},Rt=function(){!It&&$&&R($,"display","none")},Xt=function(){!It&&$&&R($,"display","")};Ot&&!c&&document.addEventListener("click",function(t){if(Et)return t.preventDefault(),t.stopPropagation&&t.stopPropagation(),t.stopImmediatePropagation&&t.stopImmediatePropagation(),Et=!1},!0);function Yt(t){if(V){t=t.touches?t.touches[0]:t;var e=(i=t.clientX,r=t.clientY,Dt.some(function(t){var e=t[K].options.emptyInsertThreshold;if(e&&!F(t)){var n=X(t),o=i>=n.left-e&&i<=n.right+e,e=r>=n.top-e&&r<=n.bottom+e;return o&&e?a=t:void 0}}),a);if(e){var n,o={};for(n in t)t.hasOwnProperty(n)&&(o[n]=t[n]);o.target=o.rootEl=e,o.preventDefault=void 0,o.stopPropagation=void 0,e[K]._onDragOver(o)}}var i,r,a}function Bt(t){V&&V.parentNode[K]._isOutsideThisEl(t.target)}function Ft(t,e){if(!t||!t.nodeType||1!==t.nodeType)throw"Sortable: `el` must be an HTMLElement, not ".concat({}.toString.call(t));this.el=t,this.options=e=a({},e),t[K]=this;var n,o,i={group:null,sort:!0,disabled:!1,store:null,handle:null,draggable:/^[uo]l$/i.test(t.nodeName)?">li":">*",swapThreshold:1,invertSwap:!1,invertedSwapThreshold:null,removeCloneOnHide:!0,direction:function(){return Pt(t,this.options)},ghostClass:"sortable-ghost",chosenClass:"sortable-chosen",dragClass:"sortable-drag",ignore:"a, img",filter:null,preventOnFilter:!0,animation:0,easing:null,setData:function(t,e){t.setData("Text",e.textContent)},dropBubble:!1,dragoverBubble:!1,dataIdAttr:"data-id",delay:0,delayOnTouchOnly:!1,touchStartThreshold:(Number.parseInt?Number:window).parseInt(window.devicePixelRatio,10)||1,forceFallback:!1,fallbackClass:"sortable-fallback",fallbackOnBody:!1,fallbackTolerance:0,fallbackOffset:{x:0,y:0},supportPointer:!1!==Ft.supportPointer&&"PointerEvent"in window&&!u,emptyInsertThreshold:5};for(n in W.initializePlugins(this,t,i),i)n in e||(e[n]=i[n]);for(o in kt(e),this)"_"===o.charAt(0)&&"function"==typeof this[o]&&(this[o]=this[o].bind(this));this.nativeDraggable=!e.forceFallback&&Nt,this.nativeDraggable&&(this.options.touchStartThreshold=1),e.supportPointer?h(t,"pointerdown",this._onTapStart):(h(t,"mousedown",this._onTapStart),h(t,"touchstart",this._onTapStart)),this.nativeDraggable&&(h(t,"dragover",this),h(t,"dragenter",this)),Dt.push(this.el),e.store&&e.store.get&&this.sort(e.store.get(this)||[]),a(this,x())}function jt(t,e,n,o,i,r,a,l){var s,c,u=t[K],d=u.options.onMove;return!window.CustomEvent||y||w?(s=document.createEvent("Event")).initEvent("move",!0,!0):s=new CustomEvent("move",{bubbles:!0,cancelable:!0}),s.to=e,s.from=t,s.dragged=n,s.draggedRect=o,s.related=i||e,s.relatedRect=r||X(e),s.willInsertAfter=l,s.originalEvent=a,t.dispatchEvent(s),c=d?d.call(u,s,a):c}function Ht(t){t.draggable=!1}function Lt(){Tt=!1}function Kt(t){return setTimeout(t,0)}function Wt(t){return clearTimeout(t)}Ft.prototype={constructor:Ft,_isOutsideThisEl:function(t){this.el.contains(t)||t===this.el||(mt=null)},_getDirection:function(t,e){return"function"==typeof this.options.direction?this.options.direction.call(this,t,e,V):this.options.direction},_onTapStart:function(e){if(e.cancelable){var n=this,o=this.el,t=this.options,i=t.preventOnFilter,r=e.type,a=e.touches&&e.touches[0]||e.pointerType&&"touch"===e.pointerType&&e,l=(a||e).target,s=e.target.shadowRoot&&(e.path&&e.path[0]||e.composedPath&&e.composedPath()[0])||l,c=t.filter;if(!function(t){xt.length=0;var e=t.getElementsByTagName("input"),n=e.length;for(;n--;){var o=e[n];o.checked&&xt.push(o)}}(o),!V&&!(/mousedown|pointerdown/.test(r)&&0!==e.button||t.disabled)&&!s.isContentEditable&&(this.nativeDraggable||!u||!l||"SELECT"!==l.tagName.toUpperCase())&&!((l=P(l,t.draggable,o,!1))&&l.animated||tt===l)){if(ot=j(l),rt=j(l,t.draggable),"function"==typeof c){if(c.call(this,e,l,this))return q({sortable:n,rootEl:s,name:"filter",targetEl:l,toEl:o,fromEl:o}),G("filter",n,{evt:e}),void(i&&e.cancelable&&e.preventDefault())}else if(c=c&&c.split(",").some(function(t){if(t=P(s,t.trim(),o,!1))return q({sortable:n,rootEl:t,name:"filter",targetEl:l,fromEl:o,toEl:o}),G("filter",n,{evt:e}),!0}))return void(i&&e.cancelable&&e.preventDefault());t.handle&&!P(s,t.handle,o,!1)||this._prepareDragStart(e,a,l)}}},_prepareDragStart:function(t,e,n){var o,i=this,r=i.el,a=i.options,l=r.ownerDocument;n&&!V&&n.parentNode===r&&(o=X(n),Q=r,Z=(V=n).parentNode,J=V.nextSibling,tt=n,lt=a.group,ct={target:Ft.dragged=V,clientX:(e||t).clientX,clientY:(e||t).clientY},ft=ct.clientX-o.left,pt=ct.clientY-o.top,this._lastX=(e||t).clientX,this._lastY=(e||t).clientY,V.style["will-change"]="all",o=function(){G("delayEnded",i,{evt:t}),Ft.eventCanceled?i._onDrop():(i._disableDelayedDragEvents(),!s&&i.nativeDraggable&&(V.draggable=!0),i._triggerDragStart(t,e),q({sortable:i,name:"choose",originalEvent:t}),k(V,a.chosenClass,!0))},a.ignore.split(",").forEach(function(t){b(V,t.trim(),Ht)}),h(l,"dragover",Yt),h(l,"mousemove",Yt),h(l,"touchmove",Yt),h(l,"mouseup",i._onDrop),h(l,"touchend",i._onDrop),h(l,"touchcancel",i._onDrop),s&&this.nativeDraggable&&(this.options.touchStartThreshold=4,V.draggable=!0),G("delayStart",this,{evt:t}),!a.delay||a.delayOnTouchOnly&&!e||this.nativeDraggable&&(w||y)?o():Ft.eventCanceled?this._onDrop():(h(l,"mouseup",i._disableDelayedDrag),h(l,"touchend",i._disableDelayedDrag),h(l,"touchcancel",i._disableDelayedDrag),h(l,"mousemove",i._delayedDragTouchMoveHandler),h(l,"touchmove",i._delayedDragTouchMoveHandler),a.supportPointer&&h(l,"pointermove",i._delayedDragTouchMoveHandler),i._dragStartTimer=setTimeout(o,a.delay)))},_delayedDragTouchMoveHandler:function(t){t=t.touches?t.touches[0]:t;Math.max(Math.abs(t.clientX-this._lastX),Math.abs(t.clientY-this._lastY))>=Math.floor(this.options.touchStartThreshold/(this.nativeDraggable&&window.devicePixelRatio||1))&&this._disableDelayedDrag()},_disableDelayedDrag:function(){V&&Ht(V),clearTimeout(this._dragStartTimer),this._disableDelayedDragEvents()},_disableDelayedDragEvents:function(){var t=this.el.ownerDocument;f(t,"mouseup",this._disableDelayedDrag),f(t,"touchend",this._disableDelayedDrag),f(t,"touchcancel",this._disableDelayedDrag),f(t,"mousemove",this._delayedDragTouchMoveHandler),f(t,"touchmove",this._delayedDragTouchMoveHandler),f(t,"pointermove",this._delayedDragTouchMoveHandler)},_triggerDragStart:function(t,e){e=e||"touch"==t.pointerType&&t,!this.nativeDraggable||e?this.options.supportPointer?h(document,"pointermove",this._onTouchMove):h(document,e?"touchmove":"mousemove",this._onTouchMove):(h(V,"dragend",this),h(Q,"dragstart",this._onDragStart));try{document.selection?Kt(function(){document.selection.empty()}):window.getSelection().removeAllRanges()}catch(t){}},_dragStarted:function(t,e){var n;wt=!1,Q&&V?(G("dragStarted",this,{evt:e}),this.nativeDraggable&&h(document,"dragover",Bt),n=this.options,t||k(V,n.dragClass,!1),k(V,n.ghostClass,!0),Ft.active=this,t&&this._appendGhost(),q({sortable:this,name:"start",originalEvent:e})):this._nulling()},_emulateDragOver:function(){if(ut){this._lastX=ut.clientX,this._lastY=ut.clientY,Rt();for(var t=document.elementFromPoint(ut.clientX,ut.clientY),e=t;t&&t.shadowRoot&&(t=t.shadowRoot.elementFromPoint(ut.clientX,ut.clientY))!==e;)e=t;if(V.parentNode[K]._isOutsideThisEl(t),e)do{if(e[K])if(e[K]._onDragOver({clientX:ut.clientX,clientY:ut.clientY,target:t,rootEl:e})&&!this.options.dragoverBubble)break}while(e=(t=e).parentNode);Xt()}},_onTouchMove:function(t){if(ct){var e=this.options,n=e.fallbackTolerance,o=e.fallbackOffset,i=t.touches?t.touches[0]:t,r=$&&v($,!0),a=$&&r&&r.a,l=$&&r&&r.d,e=Mt&&yt&&E(yt),a=(i.clientX-ct.clientX+o.x)/(a||1)+(e?e[0]-Ct[0]:0)/(a||1),l=(i.clientY-ct.clientY+o.y)/(l||1)+(e?e[1]-Ct[1]:0)/(l||1);if(!Ft.active&&!wt){if(n&&Math.max(Math.abs(i.clientX-this._lastX),Math.abs(i.clientY-this._lastY))<n)return;this._onDragStart(t,!0)}$&&(r?(r.e+=a-(dt||0),r.f+=l-(ht||0)):r={a:1,b:0,c:0,d:1,e:a,f:l},r="matrix(".concat(r.a,",").concat(r.b,",").concat(r.c,",").concat(r.d,",").concat(r.e,",").concat(r.f,")"),R($,"webkitTransform",r),R($,"mozTransform",r),R($,"msTransform",r),R($,"transform",r),dt=a,ht=l,ut=i),t.cancelable&&t.preventDefault()}},_appendGhost:function(){if(!$){var t=this.options.fallbackOnBody?document.body:Q,e=X(V,!0,Mt,!0,t),n=this.options;if(Mt){for(yt=t;"static"===R(yt,"position")&&"none"===R(yt,"transform")&&yt!==document;)yt=yt.parentNode;yt!==document.body&&yt!==document.documentElement?(yt===document&&(yt=O()),e.top+=yt.scrollTop,e.left+=yt.scrollLeft):yt=O(),Ct=E(yt)}k($=V.cloneNode(!0),n.ghostClass,!1),k($,n.fallbackClass,!0),k($,n.dragClass,!0),R($,"transition",""),R($,"transform",""),R($,"box-sizing","border-box"),R($,"margin",0),R($,"top",e.top),R($,"left",e.left),R($,"width",e.width),R($,"height",e.height),R($,"opacity","0.8"),R($,"position",Mt?"absolute":"fixed"),R($,"zIndex","100000"),R($,"pointerEvents","none"),Ft.ghost=$,t.appendChild($),R($,"transform-origin",ft/parseInt($.style.width)*100+"% "+pt/parseInt($.style.height)*100+"%")}},_onDragStart:function(t,e){var n=this,o=t.dataTransfer,i=n.options;G("dragStart",this,{evt:t}),Ft.eventCanceled?this._onDrop():(G("setupClone",this),Ft.eventCanceled||((et=_(V)).removeAttribute("id"),et.draggable=!1,et.style["will-change"]="",this._hideClone(),k(et,this.options.chosenClass,!1),Ft.clone=et),n.cloneId=Kt(function(){G("clone",n),Ft.eventCanceled||(n.options.removeCloneOnHide||Q.insertBefore(et,V),n._hideClone(),q({sortable:n,name:"clone"}))}),e||k(V,i.dragClass,!0),e?(Et=!0,n._loopId=setInterval(n._emulateDragOver,50)):(f(document,"mouseup",n._onDrop),f(document,"touchend",n._onDrop),f(document,"touchcancel",n._onDrop),o&&(o.effectAllowed="move",i.setData&&i.setData.call(n,o,V)),h(document,"drop",n),R(V,"transform","translateZ(0)")),wt=!0,n._dragStartId=Kt(n._dragStarted.bind(n,e,t)),h(document,"selectstart",n),gt=!0,u&&R(document.body,"user-select","none"))},_onDragOver:function(n){var o,i,r,t,e,a=this.el,l=n.target,s=this.options,c=s.group,u=Ft.active,d=lt===c,h=s.sort,f=st||u,p=this,g=!1;if(!Tt){if(void 0!==n.preventDefault&&n.cancelable&&n.preventDefault(),l=P(l,s.draggable,a,!0),O("dragOver"),Ft.eventCanceled)return g;if(V.contains(n.target)||l.animated&&l.animatingX&&l.animatingY||p._ignoreWhileAnimating===l)return A(!1);if(Et=!1,u&&!s.disabled&&(d?h||(i=Z!==Q):st===this||(this.lastPutMode=lt.checkPull(this,u,V,n))&&c.checkPut(this,u,V,n))){if(r="vertical"===this._getDirection(n,l),o=X(V),O("dragOverValid"),Ft.eventCanceled)return g;if(i)return Z=Q,M(),this._hideClone(),O("revert"),Ft.eventCanceled||(J?Q.insertBefore(V,J):Q.appendChild(V)),A(!0);var m=F(a,s.draggable);if(m&&(S=n,c=r,x=X(F((D=this).el,D.options.draggable)),D=L(D.el,D.options,$),!(c?S.clientX>D.right+10||S.clientY>x.bottom&&S.clientX>x.left:S.clientY>D.bottom+10||S.clientX>x.right&&S.clientY>x.top)||m.animated)){if(m&&(t=n,e=r,C=X(B((_=this).el,0,_.options,!0)),_=L(_.el,_.options,$),e?t.clientX<_.left-10||t.clientY<C.top&&t.clientX<C.right:t.clientY<_.top-10||t.clientY<C.bottom&&t.clientX<C.left)){var v=B(a,0,s,!0);if(v===V)return A(!1);if(E=X(l=v),!1!==jt(Q,a,V,o,l,E,n,!1))return M(),a.insertBefore(V,v),Z=a,N(),A(!0)}else if(l.parentNode===a){var b,y,w,E=X(l),D=V.parentNode!==a,S=(S=V.animated&&V.toRect||o,x=l.animated&&l.toRect||E,_=(e=r)?S.left:S.top,t=e?S.right:S.bottom,C=e?S.width:S.height,v=e?x.left:x.top,S=e?x.right:x.bottom,x=e?x.width:x.height,!(_===v||t===S||_+C/2===v+x/2)),_=r?"top":"left",C=Y(l,"top","top")||Y(V,"top","top"),v=C?C.scrollTop:void 0;if(mt!==l&&(y=E[_],St=!1,_t=!S&&s.invertSwap||D),0!==(b=function(t,e,n,o,i,r,a,l){var s=o?t.clientY:t.clientX,c=o?n.height:n.width,t=o?n.top:n.left,o=o?n.bottom:n.right,n=!1;if(!a)if(l&&bt<c*i){if(St=!St&&(1===vt?t+c*r/2<s:s<o-c*r/2)?!0:St)n=!0;else if(1===vt?s<t+bt:o-bt<s)return-vt}else if(t+c*(1-i)/2<s&&s<o-c*(1-i)/2)return function(t){return j(V)<j(t)?1:-1}(e);if((n=n||a)&&(s<t+c*r/2||o-c*r/2<s))return t+c/2<s?1:-1;return 0}(n,l,E,r,S?1:s.swapThreshold,null==s.invertedSwapThreshold?s.swapThreshold:s.invertedSwapThreshold,_t,mt===l)))for(var T=j(V);(w=Z.children[T-=b])&&("none"===R(w,"display")||w===$););if(0===b||w===l)return A(!1);vt=b;var x=(mt=l).nextElementSibling,D=!1,S=jt(Q,a,V,o,l,E,n,D=1===b);if(!1!==S)return 1!==S&&-1!==S||(D=1===S),Tt=!0,setTimeout(Lt,30),M(),D&&!x?a.appendChild(V):l.parentNode.insertBefore(V,D?x:l),C&&H(C,0,v-C.scrollTop),Z=V.parentNode,void 0===y||_t||(bt=Math.abs(y-X(l)[_])),N(),A(!0)}}else{if(m===V)return A(!1);if((l=m&&a===n.target?m:l)&&(E=X(l)),!1!==jt(Q,a,V,o,l,E,n,!!l))return M(),m&&m.nextSibling?a.insertBefore(V,m.nextSibling):a.appendChild(V),Z=a,N(),A(!0)}if(a.contains(V))return A(!1)}return!1}function O(t,e){G(t,p,I({evt:n,isOwner:d,axis:r?"vertical":"horizontal",revert:i,dragRect:o,targetRect:E,canSort:h,fromSortable:f,target:l,completed:A,onMove:function(t,e){return jt(Q,a,V,o,t,X(t),n,e)},changed:N},e))}function M(){O("dragOverAnimationCapture"),p.captureAnimationState(),p!==f&&f.captureAnimationState()}function A(t){return O("dragOverCompleted",{insertion:t}),t&&(d?u._hideClone():u._showClone(p),p!==f&&(k(V,(st||u).options.ghostClass,!1),k(V,s.ghostClass,!0)),st!==p&&p!==Ft.active?st=p:p===Ft.active&&st&&(st=null),f===p&&(p._ignoreWhileAnimating=l),p.animateAll(function(){O("dragOverAnimationComplete"),p._ignoreWhileAnimating=null}),p!==f&&(f.animateAll(),f._ignoreWhileAnimating=null)),(l===V&&!V.animated||l===a&&!l.animated)&&(mt=null),s.dragoverBubble||n.rootEl||l===document||(V.parentNode[K]._isOutsideThisEl(n.target),t||Yt(n)),!s.dragoverBubble&&n.stopPropagation&&n.stopPropagation(),g=!0}function N(){it=j(V),at=j(V,s.draggable),q({sortable:p,name:"change",toEl:a,newIndex:it,newDraggableIndex:at,originalEvent:n})}},_ignoreWhileAnimating:null,_offMoveEvents:function(){f(document,"mousemove",this._onTouchMove),f(document,"touchmove",this._onTouchMove),f(document,"pointermove",this._onTouchMove),f(document,"dragover",Yt),f(document,"mousemove",Yt),f(document,"touchmove",Yt)},_offUpEvents:function(){var t=this.el.ownerDocument;f(t,"mouseup",this._onDrop),f(t,"touchend",this._onDrop),f(t,"pointerup",this._onDrop),f(t,"touchcancel",this._onDrop),f(document,"selectstart",this)},_onDrop:function(t){var e=this.el,n=this.options;it=j(V),at=j(V,n.draggable),G("drop",this,{evt:t}),Z=V&&V.parentNode,it=j(V),at=j(V,n.draggable),Ft.eventCanceled||(St=_t=wt=!1,clearInterval(this._loopId),clearTimeout(this._dragStartTimer),Wt(this.cloneId),Wt(this._dragStartId),this.nativeDraggable&&(f(document,"drop",this),f(e,"dragstart",this._onDragStart)),this._offMoveEvents(),this._offUpEvents(),u&&R(document.body,"user-select",""),R(V,"transform",""),t&&(gt&&(t.cancelable&&t.preventDefault(),n.dropBubble||t.stopPropagation()),$&&$.parentNode&&$.parentNode.removeChild($),(Q===Z||st&&"clone"!==st.lastPutMode)&&et&&et.parentNode&&et.parentNode.removeChild(et),V&&(this.nativeDraggable&&f(V,"dragend",this),Ht(V),V.style["will-change"]="",gt&&!wt&&k(V,(st||this).options.ghostClass,!1),k(V,this.options.chosenClass,!1),q({sortable:this,name:"unchoose",toEl:Z,newIndex:null,newDraggableIndex:null,originalEvent:t}),Q!==Z?(0<=it&&(q({rootEl:Z,name:"add",toEl:Z,fromEl:Q,originalEvent:t}),q({sortable:this,name:"remove",toEl:Z,originalEvent:t}),q({rootEl:Z,name:"sort",toEl:Z,fromEl:Q,originalEvent:t}),q({sortable:this,name:"sort",toEl:Z,originalEvent:t})),st&&st.save()):it!==ot&&0<=it&&(q({sortable:this,name:"update",toEl:Z,originalEvent:t}),q({sortable:this,name:"sort",toEl:Z,originalEvent:t})),Ft.active&&(null!=it&&-1!==it||(it=ot,at=rt),q({sortable:this,name:"end",toEl:Z,originalEvent:t}),this.save())))),this._nulling()},_nulling:function(){G("nulling",this),Q=V=Z=$=J=et=tt=nt=ct=ut=gt=it=at=ot=rt=mt=vt=st=lt=Ft.dragged=Ft.ghost=Ft.clone=Ft.active=null,xt.forEach(function(t){t.checked=!0}),xt.length=dt=ht=0},handleEvent:function(t){switch(t.type){case"drop":case"dragend":this._onDrop(t);break;case"dragenter":case"dragover":V&&(this._onDragOver(t),function(t){t.dataTransfer&&(t.dataTransfer.dropEffect="move");t.cancelable&&t.preventDefault()}(t));break;case"selectstart":t.preventDefault()}},toArray:function(){for(var t,e=[],n=this.el.children,o=0,i=n.length,r=this.options;o<i;o++)P(t=n[o],r.draggable,this.el,!1)&&e.push(t.getAttribute(r.dataIdAttr)||function(t){var e=t.tagName+t.className+t.src+t.href+t.textContent,n=e.length,o=0;for(;n--;)o+=e.charCodeAt(n);return o.toString(36)}(t));return e},sort:function(t,e){var n={},o=this.el;this.toArray().forEach(function(t,e){e=o.children[e];P(e,this.options.draggable,o,!1)&&(n[t]=e)},this),e&&this.captureAnimationState(),t.forEach(function(t){n[t]&&(o.removeChild(n[t]),o.appendChild(n[t]))}),e&&this.animateAll()},save:function(){var t=this.options.store;t&&t.set&&t.set(this)},closest:function(t,e){return P(t,e||this.options.draggable,this.el,!1)},option:function(t,e){var n=this.options;if(void 0===e)return n[t];var o=W.modifyOption(this,t,e);n[t]=void 0!==o?o:e,"group"===t&&kt(n)},destroy:function(){G("destroy",this);var t=this.el;t[K]=null,f(t,"mousedown",this._onTapStart),f(t,"touchstart",this._onTapStart),f(t,"pointerdown",this._onTapStart),this.nativeDraggable&&(f(t,"dragover",this),f(t,"dragenter",this)),Array.prototype.forEach.call(t.querySelectorAll("[draggable]"),function(t){t.removeAttribute("draggable")}),this._onDrop(),this._disableDelayedDragEvents(),Dt.splice(Dt.indexOf(this.el),1),this.el=t=null},_hideClone:function(){nt||(G("hideClone",this),Ft.eventCanceled||(R(et,"display","none"),this.options.removeCloneOnHide&&et.parentNode&&et.parentNode.removeChild(et),nt=!0))},_showClone:function(t){"clone"===t.lastPutMode?nt&&(G("showClone",this),Ft.eventCanceled||(V.parentNode!=Q||this.options.group.revertClone?J?Q.insertBefore(et,J):Q.appendChild(et):Q.insertBefore(et,V),this.options.group.revertClone&&this.animate(V,et),R(et,"display",""),nt=!1)):this._hideClone()}},Ot&&h(document,"touchmove",function(t){(Ft.active||wt)&&t.cancelable&&t.preventDefault()}),Ft.utils={on:h,off:f,css:R,find:b,is:function(t,e){return!!P(t,e,t,!1)},extend:function(t,e){if(t&&e)for(var n in e)e.hasOwnProperty(n)&&(t[n]=e[n]);return t},throttle:S,closest:P,toggleClass:k,clone:_,index:j,nextTick:Kt,cancelNextTick:Wt,detectDirection:Pt,getChild:B},Ft.get=function(t){return t[K]},Ft.mount=function(){for(var t=arguments.length,e=new Array(t),n=0;n<t;n++)e[n]=arguments[n];(e=e[0].constructor===Array?e[0]:e).forEach(function(t){if(!t.prototype||!t.prototype.constructor)throw"Sortable: Mounted plugin must be a constructor function, not ".concat({}.toString.call(t));t.utils&&(Ft.utils=I(I({},Ft.utils),t.utils)),W.mount(t)})},Ft.create=function(t,e){return new Ft(t,e)};var zt,Gt,Ut,qt,Vt,Zt,$t=[],Qt=!(Ft.version="1.15.2");function Jt(){$t.forEach(function(t){clearInterval(t.pid)}),$t=[]}function te(){clearInterval(Zt)}var ee,ne=S(function(n,t,e,o){if(t.scroll){var i,r=(n.touches?n.touches[0]:n).clientX,a=(n.touches?n.touches[0]:n).clientY,l=t.scrollSensitivity,s=t.scrollSpeed,c=O(),u=!1;Gt!==e&&(Gt=e,Jt(),zt=t.scroll,i=t.scrollFn,!0===zt&&(zt=M(e,!0)));var d=0,h=zt;do{var f=h,p=X(f),g=p.top,m=p.bottom,v=p.left,b=p.right,y=p.width,w=p.height,E=void 0,D=void 0,S=f.scrollWidth,_=f.scrollHeight,C=R(f),T=f.scrollLeft,p=f.scrollTop,D=f===c?(E=y<S&&("auto"===C.overflowX||"scroll"===C.overflowX||"visible"===C.overflowX),w<_&&("auto"===C.overflowY||"scroll"===C.overflowY||"visible"===C.overflowY)):(E=y<S&&("auto"===C.overflowX||"scroll"===C.overflowX),w<_&&("auto"===C.overflowY||"scroll"===C.overflowY)),T=E&&(Math.abs(b-r)<=l&&T+y<S)-(Math.abs(v-r)<=l&&!!T),p=D&&(Math.abs(m-a)<=l&&p+w<_)-(Math.abs(g-a)<=l&&!!p);if(!$t[d])for(var x=0;x<=d;x++)$t[x]||($t[x]={});$t[d].vx==T&&$t[d].vy==p&&$t[d].el===f||($t[d].el=f,$t[d].vx=T,$t[d].vy=p,clearInterval($t[d].pid),0==T&&0==p||(u=!0,$t[d].pid=setInterval(function(){o&&0===this.layer&&Ft.active._onTouchMove(Vt);var t=$t[this.layer].vy?$t[this.layer].vy*s:0,e=$t[this.layer].vx?$t[this.layer].vx*s:0;"function"==typeof i&&"continue"!==i.call(Ft.dragged.parentNode[K],e,t,n,Vt,$t[this.layer].el)||H($t[this.layer].el,e,t)}.bind({layer:d}),24))),d++}while(t.bubbleScroll&&h!==c&&(h=M(h,!1)));Qt=u}},30),c=function(t){var e=t.originalEvent,n=t.putSortable,o=t.dragEl,i=t.activeSortable,r=t.dispatchSortableEvent,a=t.hideGhostForTarget,t=t.unhideGhostForTarget;e&&(i=n||i,a(),e=e.changedTouches&&e.changedTouches.length?e.changedTouches[0]:e,e=document.elementFromPoint(e.clientX,e.clientY),t(),i&&!i.el.contains(e)&&(r("spill"),this.onSpill({dragEl:o,putSortable:n})))};function oe(){}function ie(){}oe.prototype={startIndex:null,dragStart:function(t){t=t.oldDraggableIndex;this.startIndex=t},onSpill:function(t){var e=t.dragEl,n=t.putSortable;this.sortable.captureAnimationState(),n&&n.captureAnimationState();t=B(this.sortable.el,this.startIndex,this.options);t?this.sortable.el.insertBefore(e,t):this.sortable.el.appendChild(e),this.sortable.animateAll(),n&&n.animateAll()},drop:c},a(oe,{pluginName:"revertOnSpill"}),ie.prototype={onSpill:function(t){var e=t.dragEl,t=t.putSortable||this.sortable;t.captureAnimationState(),e.parentNode&&e.parentNode.removeChild(e),t.animateAll()},drop:c},a(ie,{pluginName:"removeOnSpill"});var re,ae,le,se,ce,ue=[],de=[],he=!1,fe=!1,pe=!1;function ge(n,o){de.forEach(function(t,e){e=o.children[t.sortableIndex+(n?Number(e):0)];e?o.insertBefore(t,e):o.appendChild(t)})}function me(){ue.forEach(function(t){t!==le&&t.parentNode&&t.parentNode.removeChild(t)})}return Ft.mount(new function(){function t(){for(var t in this.defaults={scroll:!0,forceAutoScrollFallback:!1,scrollSensitivity:30,scrollSpeed:10,bubbleScroll:!0},this)"_"===t.charAt(0)&&"function"==typeof this[t]&&(this[t]=this[t].bind(this))}return t.prototype={dragStarted:function(t){t=t.originalEvent;this.sortable.nativeDraggable?h(document,"dragover",this._handleAutoScroll):this.options.supportPointer?h(document,"pointermove",this._handleFallbackAutoScroll):t.touches?h(document,"touchmove",this._handleFallbackAutoScroll):h(document,"mousemove",this._handleFallbackAutoScroll)},dragOverCompleted:function(t){t=t.originalEvent;this.options.dragOverBubble||t.rootEl||this._handleAutoScroll(t)},drop:function(){this.sortable.nativeDraggable?f(document,"dragover",this._handleAutoScroll):(f(document,"pointermove",this._handleFallbackAutoScroll),f(document,"touchmove",this._handleFallbackAutoScroll),f(document,"mousemove",this._handleFallbackAutoScroll)),te(),Jt(),clearTimeout(g),g=void 0},nulling:function(){Vt=Gt=zt=Qt=Zt=Ut=qt=null,$t.length=0},_handleFallbackAutoScroll:function(t){this._handleAutoScroll(t,!0)},_handleAutoScroll:function(e,n){var o,i=this,r=(e.touches?e.touches[0]:e).clientX,a=(e.touches?e.touches[0]:e).clientY,t=document.elementFromPoint(r,a);Vt=e,n||this.options.forceAutoScrollFallback||w||y||u?(ne(e,this.options,t,n),o=M(t,!0),!Qt||Zt&&r===Ut&&a===qt||(Zt&&te(),Zt=setInterval(function(){var t=M(document.elementFromPoint(r,a),!0);t!==o&&(o=t,Jt()),ne(e,i.options,t,n)},10),Ut=r,qt=a)):this.options.bubbleScroll&&M(t,!0)!==O()?ne(e,this.options,M(t,!1),!1):Jt()}},a(t,{pluginName:"scroll",initializeByDefault:!0})}),Ft.mount(ie,oe),Ft.mount(new function(){function t(){this.defaults={swapClass:"sortable-swap-highlight"}}return t.prototype={dragStart:function(t){t=t.dragEl;ee=t},dragOverValid:function(t){var e=t.completed,n=t.target,o=t.onMove,i=t.activeSortable,r=t.changed,a=t.cancel;i.options.swap&&(t=this.sortable.el,i=this.options,n&&n!==t&&(t=ee,ee=!1!==o(n)?(k(n,i.swapClass,!0),n):null,t&&t!==ee&&k(t,i.swapClass,!1)),r(),e(!0),a())},drop:function(t){var e,n,o=t.activeSortable,i=t.putSortable,r=t.dragEl,a=i||this.sortable,l=this.options;ee&&k(ee,l.swapClass,!1),ee&&(l.swap||i&&i.options.swap)&&r!==ee&&(a.captureAnimationState(),a!==o&&o.captureAnimationState(),n=ee,t=(e=r).parentNode,l=n.parentNode,t&&l&&!t.isEqualNode(n)&&!l.isEqualNode(e)&&(i=j(e),r=j(n),t.isEqualNode(l)&&i<r&&r++,t.insertBefore(n,t.children[i]),l.insertBefore(e,l.children[r])),a.animateAll(),a!==o&&o.animateAll())},nulling:function(){ee=null}},a(t,{pluginName:"swap",eventProperties:function(){return{swapItem:ee}}})}),Ft.mount(new function(){function t(o){for(var t in this)"_"===t.charAt(0)&&"function"==typeof this[t]&&(this[t]=this[t].bind(this));o.options.avoidImplicitDeselect||(o.options.supportPointer?h(document,"pointerup",this._deselectMultiDrag):(h(document,"mouseup",this._deselectMultiDrag),h(document,"touchend",this._deselectMultiDrag))),h(document,"keydown",this._checkKeyDown),h(document,"keyup",this._checkKeyUp),this.defaults={selectedClass:"sortable-selected",multiDragKey:null,avoidImplicitDeselect:!1,setData:function(t,e){var n="";ue.length&&ae===o?ue.forEach(function(t,e){n+=(e?", ":"")+t.textContent}):n=e.textContent,t.setData("Text",n)}}}return t.prototype={multiDragKeyDown:!1,isMultiDrag:!1,delayStartGlobal:function(t){t=t.dragEl;le=t},delayEnded:function(){this.isMultiDrag=~ue.indexOf(le)},setupClone:function(t){var e=t.sortable,t=t.cancel;if(this.isMultiDrag){for(var n=0;n<ue.length;n++)de.push(_(ue[n])),de[n].sortableIndex=ue[n].sortableIndex,de[n].draggable=!1,de[n].style["will-change"]="",k(de[n],this.options.selectedClass,!1),ue[n]===le&&k(de[n],this.options.chosenClass,!1);e._hideClone(),t()}},clone:function(t){var e=t.sortable,n=t.rootEl,o=t.dispatchSortableEvent,t=t.cancel;this.isMultiDrag&&(this.options.removeCloneOnHide||ue.length&&ae===e&&(ge(!0,n),o("clone"),t()))},showClone:function(t){var e=t.cloneNowShown,n=t.rootEl,t=t.cancel;this.isMultiDrag&&(ge(!1,n),de.forEach(function(t){R(t,"display","")}),e(),ce=!1,t())},hideClone:function(t){var e=this,n=(t.sortable,t.cloneNowHidden),t=t.cancel;this.isMultiDrag&&(de.forEach(function(t){R(t,"display","none"),e.options.removeCloneOnHide&&t.parentNode&&t.parentNode.removeChild(t)}),n(),ce=!0,t())},dragStartGlobal:function(t){t.sortable;!this.isMultiDrag&&ae&&ae.multiDrag._deselectMultiDrag(),ue.forEach(function(t){t.sortableIndex=j(t)}),ue=ue.sort(function(t,e){return t.sortableIndex-e.sortableIndex}),pe=!0},dragStarted:function(t){var e,n=this,t=t.sortable;this.isMultiDrag&&(this.options.sort&&(t.captureAnimationState(),this.options.animation&&(ue.forEach(function(t){t!==le&&R(t,"position","absolute")}),e=X(le,!1,!0,!0),ue.forEach(function(t){t!==le&&C(t,e)}),he=fe=!0)),t.animateAll(function(){he=fe=!1,n.options.animation&&ue.forEach(function(t){T(t)}),n.options.sort&&me()}))},dragOver:function(t){var e=t.target,n=t.completed,t=t.cancel;fe&&~ue.indexOf(e)&&(n(!1),t())},revert:function(t){var n,o,e=t.fromSortable,i=t.rootEl,r=t.sortable,a=t.dragRect;1<ue.length&&(ue.forEach(function(t){r.addAnimationState({target:t,rect:fe?X(t):a}),T(t),t.fromRect=a,e.removeAnimationState(t)}),fe=!1,n=!this.options.removeCloneOnHide,o=i,ue.forEach(function(t,e){e=o.children[t.sortableIndex+(n?Number(e):0)];e?o.insertBefore(t,e):o.appendChild(t)}))},dragOverCompleted:function(t){var e,n=t.sortable,o=t.isOwner,i=t.insertion,r=t.activeSortable,a=t.parentEl,l=t.putSortable,t=this.options;i&&(o&&r._hideClone(),he=!1,t.animation&&1<ue.length&&(fe||!o&&!r.options.sort&&!l)&&(e=X(le,!1,!0,!0),ue.forEach(function(t){t!==le&&(C(t,e),a.appendChild(t))}),fe=!0),o||(fe||me(),1<ue.length?(o=ce,r._showClone(n),r.options.animation&&!ce&&o&&de.forEach(function(t){r.addAnimationState({target:t,rect:se}),t.fromRect=se,t.thisAnimationDuration=null})):r._showClone(n)))},dragOverAnimationCapture:function(t){var e=t.dragRect,n=t.isOwner,t=t.activeSortable;ue.forEach(function(t){t.thisAnimationDuration=null}),t.options.animation&&!n&&t.multiDrag.isMultiDrag&&(se=a({},e),e=v(le,!0),se.top-=e.f,se.left-=e.e)},dragOverAnimationComplete:function(){fe&&(fe=!1,me())},drop:function(t){var e=t.originalEvent,n=t.rootEl,o=t.parentEl,i=t.sortable,r=t.dispatchSortableEvent,a=t.oldIndex,l=t.putSortable,s=l||this.sortable;if(e){var c,u,d,h=this.options,f=o.children;if(!pe)if(h.multiDragKey&&!this.multiDragKeyDown&&this._deselectMultiDrag(),k(le,h.selectedClass,!~ue.indexOf(le)),~ue.indexOf(le))ue.splice(ue.indexOf(le),1),re=null,z({sortable:i,rootEl:n,name:"deselect",targetEl:le,originalEvent:e});else{if(ue.push(le),z({sortable:i,rootEl:n,name:"select",targetEl:le,originalEvent:e}),e.shiftKey&&re&&i.el.contains(re)){var p=j(re),t=j(le);if(~p&&~t&&p!==t)for(var g,m=p<t?(g=p,t):(g=t,p+1);g<m;g++)~ue.indexOf(f[g])||(k(f[g],h.selectedClass,!0),ue.push(f[g]),z({sortable:i,rootEl:n,name:"select",targetEl:f[g],originalEvent:e}))}else re=le;ae=s}pe&&this.isMultiDrag&&(fe=!1,(o[K].options.sort||o!==n)&&1<ue.length&&(c=X(le),u=j(le,":not(."+this.options.selectedClass+")"),!he&&h.animation&&(le.thisAnimationDuration=null),s.captureAnimationState(),he||(h.animation&&(le.fromRect=c,ue.forEach(function(t){var e;t.thisAnimationDuration=null,t!==le&&(e=fe?X(t):c,t.fromRect=e,s.addAnimationState({target:t,rect:e}))})),me(),ue.forEach(function(t){f[u]?o.insertBefore(t,f[u]):o.appendChild(t),u++}),a===j(le)&&(d=!1,ue.forEach(function(t){t.sortableIndex!==j(t)&&(d=!0)}),d&&(r("update"),r("sort")))),ue.forEach(function(t){T(t)}),s.animateAll()),ae=s),(n===o||l&&"clone"!==l.lastPutMode)&&de.forEach(function(t){t.parentNode&&t.parentNode.removeChild(t)})}},nullingGlobal:function(){this.isMultiDrag=pe=!1,de.length=0},destroyGlobal:function(){this._deselectMultiDrag(),f(document,"pointerup",this._deselectMultiDrag),f(document,"mouseup",this._deselectMultiDrag),f(document,"touchend",this._deselectMultiDrag),f(document,"keydown",this._checkKeyDown),f(document,"keyup",this._checkKeyUp)},_deselectMultiDrag:function(t){if(!(void 0!==pe&&pe||ae!==this.sortable||t&&P(t.target,this.options.draggable,this.sortable.el,!1)||t&&0!==t.button))for(;ue.length;){var e=ue[0];k(e,this.options.selectedClass,!1),ue.shift(),z({sortable:this.sortable,rootEl:this.sortable.el,name:"deselect",targetEl:e,originalEvent:t})}},_checkKeyDown:function(t){t.key===this.options.multiDragKey&&(this.multiDragKeyDown=!0)},_checkKeyUp:function(t){t.key===this.options.multiDragKey&&(this.multiDragKeyDown=!1)}},a(t,{pluginName:"multiDrag",utils:{select:function(t){var e=t.parentNode[K];e&&e.options.multiDrag&&!~ue.indexOf(t)&&(ae&&ae!==e&&(ae.multiDrag._deselectMultiDrag(),ae=e),k(t,e.options.selectedClass,!0),ue.push(t))},deselect:function(t){var e=t.parentNode[K],n=ue.indexOf(t);e&&e.options.multiDrag&&~n&&(k(t,e.options.selectedClass,!1),ue.splice(n,1))}},eventProperties:function(){var n=this,o=[],i=[];return ue.forEach(function(t){var e;o.push({multiDragElement:t,index:t.sortableIndex}),e=fe&&t!==le?-1:fe?j(t,":not(."+n.options.selectedClass+")"):j(t),i.push({multiDragElement:t,index:e})}),{items:r(ue),clones:[].concat(de),oldIndicies:o,newIndicies:i}},optionListeners:{multiDragKey:function(t){return"ctrl"===(t=t.toLowerCase())?t="Control":1<t.length&&(t=t.charAt(0).toUpperCase()+t.substr(1)),t}}})}),Ft});
\ No newline at end of file
diff --git a/app/templates/base.html b/app/templates/base.html
index 31ee612..40bb893 100644
--- a/app/templates/base.html
+++ b/app/templates/base.html
@@ -4,25 +4,23 @@
   <meta charset="UTF-8">
   <meta name="viewport" content="width=device-width, initial-scale=1.0">
   <title>{% block title %}Bitacora GRM{% endblock %}</title>
-  <script src="https://cdn.tailwindcss.com"></script>
+  <!-- Tailwind CSS COMPILADO Y AUTOALOJADO.
+       Antes se cargaba desde https://cdn.tailwindcss.com (la version "Play",
+       que compila las clases EN EL NAVEGADOR). Eso hacia depender de una red
+       externa: si el CDN tardaba o estaba bloqueado, la pagina se quedaba
+       sin estilos (tarjetas gigantes, maquetacion rota y Kanban sin
+       drag & drop). Ahora el CSS se compila antes de publicar y se sirve
+       desde el propio servidor, como ya se hacia con HTMX.
+       Ver tailwind.config.js para el comando de recompilacion. -->
+  <link rel="stylesheet" href="/static/css/tailwind.css">
   <!-- HTMX autoalojado: elimina dependencia de unpkg.com y de SRI hash que
        puede fallar en Railway por CSP o bloqueos de CDN. -->
   <script src="/static/js/htmx.min.js"></script>
-  <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
+  <!-- SortableJS autoalojado (v1.15.2): lo usa el Kanban para el arrastre de
+       tarjetas. Antes venia de cdn.jsdelivr.net. -->
+  <script src="/static/js/sortable.min.js"></script>
   <link rel="stylesheet" href="/static/css/styles.css">
-  <script>
-    tailwind.config = {
-      theme: {
-        extend: {
-          fontFamily: {
-            sans: ['Inter', 'system-ui', 'sans-serif'],
-          }
-        }
-      }
-    }
-  </script>
-  <link rel="preconnect" href="https://fonts.googleapis.com">
-  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
+  <link rel="stylesheet" href="/static/css/fonts.css">
   {# Bloque para que las paginas hijas inyecten CSS adicional sin
      tener que duplicar el <head>. Necesario para que el scroll del
      Planner (y de cualquier vista con CSS propio) se renderice. #}
diff --git a/tailwind.config.js b/tailwind.config.js
new file mode 100644
index 0000000..9743de5
--- /dev/null
+++ b/tailwind.config.js
@@ -0,0 +1,49 @@
+/**
+ * Configuracion de Tailwind CSS (compilacion local, sin CDN).
+ *
+ * Contexto
+ * --------
+ * Antes, la aplicacion cargaba Tailwind desde el CDN oficial
+ * (`https://cdn.tailwindcss.com`), que compila las utilidades EN EL
+ * NAVEGADOR. Eso hacia que:
+ *
+ *   1. la UI dependia de una red externa (si el CDN tardaba o estaba
+ *      bloqueado, la pagina se quedaba SIN ESTILOS: tarjetas gigantes,
+ *      columna sin maquetar y el Kanban sin drag & drop), y
+ *   2. el navegador pagaba el coste de compilar las clases en cada carga.
+ *
+ * Ahora el CSS se compila ANTES de publicar y se sirve desde
+ * `/static/css/tailwind.css`, igual que ya se hacia con HTMX.
+ *
+ * Como regenerarlo (no hace falta en cada despliegue)
+ * ---------------------------------------------------
+ *   1. Descargar el CLI oficial de Tailwind v3 para Windows:
+ *        https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-windows-x64.exe
+ *   2. Compilar:
+ *        tailwindcss-windows-x64.exe -c tailwind.config.js ^
+ *          -i app/static/css/tailwind.src.css ^
+ *          -o app/static/css/tailwind.css --minify
+ *
+ * El resultado se versiona en el repositorio: el despliegue no necesita
+ * Node, npm ni ningun paso de construccion.
+ */
+module.exports = {
+  content: [
+    // Todo el codigo Python de la aplicacion: las plantillas se generan
+    // desde Python (app/templates/**/*.py) y hay markup que se arma en
+    // otras capas (app/core/resultado_pruebas.py, app/api/**, ...).
+    './app/**/*.py',
+    // Plantillas HTML.
+    './app/**/*.html',
+    // Clases que se aplican desde JavaScript (classList.add/remove).
+    './app/static/js/**/*.js',
+  ],
+  theme: {
+    extend: {
+      fontFamily: {
+        sans: ['Inter', 'system-ui', 'sans-serif'],
+      },
+    },
+  },
+  plugins: [],
+};
diff --git a/tests/test_v2007_autohospedaje_recursos.py b/tests/test_v2007_autohospedaje_recursos.py
new file mode 100644
index 0000000..50e7073
--- /dev/null
+++ b/tests/test_v2007_autohospedaje_recursos.py
@@ -0,0 +1,219 @@
+"""
+Regresiones de V2.007: la aplicacion NO depende de ningun CDN externo.
+
+Contexto del defecto
+--------------------
+El 2026-10-30 el propietario reporto, con captura de la pestana Network del
+navegador, que la pagina /kanban se servia SIN ESTILOS: el logo aparecia
+enorme, la maquetacion estaba rota y el Kanban no tenia drag & drop. La
+pestana Network mostraba la peticion a ``cdn.tailwindcss.com`` con 0 bytes
+tras 40 segundos.
+
+Causa raiz
+----------
+El proyecto cargaba dos recursos de CDN externos:
+
+  * ``https://cdn.tailwindcss.com`` (la version "Play" de Tailwind, que
+    compila las clases EN EL NAVEGADOR),
+  * ``https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js``
+
+mas la fuente Inter desde ``fonts.googleapis.com``. Si cualquiera de esas
+redes tarda, falla o esta bloqueada, la pagina se queda sin estilos (y el
+Kanban se queda sin arrastre). HTMX ya se autoalojaba desde el lote
+anterior; faltaba el resto.
+
+Este lote
+---------
+  * compila Tailwind por adelantado y sirve ``/static/css/tailwind.css``
+    (55 KB) en lugar del compilador de 407 KB que se ejecutaba en el
+    navegador;
+  * autoaloja SortableJS 1.15.2 en ``/static/js/sortable.min.js``;
+  * autoaloja la fuente Inter (subconjuntos latin y latin-ext) en
+    ``/static/fonts/``.
+
+Que fija esta suite
+-------------------
+  * que las plantillas no referencien ningun CDN externo,
+  * que el CSS compilado, Sortable y la fuente esten versionados,
+  * que la configuracion de Tailwind siga cubriendo todo el codigo,
+  * y que los tres recursos se sirvan de verdad (200) desde /static.
+"""
+from __future__ import annotations
+
+import re
+from pathlib import Path
+
+import pytest
+from fastapi.testclient import TestClient
+
+RAIZ = Path(__file__).resolve().parent.parent
+DIR_PLANTILLAS = RAIZ / "app" / "templates"
+DIR_JS = RAIZ / "app" / "static" / "js"
+DIR_CSS = RAIZ / "app" / "static" / "css"
+DIR_FUENTES = RAIZ / "app" / "static" / "fonts"
+
+CSS_TAILWIND = DIR_CSS / "tailwind.css"
+CSS_FUENTES = DIR_CSS / "fonts.css"
+JS_SORTABLE = DIR_JS / "sortable.min.js"
+CONFIG = RAIZ / "tailwind.config.js"
+ENTRADA = DIR_CSS / "tailwind.src.css"
+
+#: Dominios externos que la aplicacion no debe pedir.
+CDN_PROHIBIDOS = (
+    "cdn.tailwindcss.com",
+    "cdn.jsdelivr.net",
+    "unpkg.com",
+    "fonts.googleapis.com",
+    "fonts.gstatic.com",
+    "cdnjs.cloudflare.com",
+    "ajax.googleapis.com",
+)
+
+#: Etiquetas que cargan un recurso externo.
+RE_RECURSO = re.compile(
+    r"""<(script|link|img|iframe)\b[^>]*?\b(?:src|href)\s*=\s*["'](https?://[^"']+)["']""",
+    re.I | re.S,
+)
+
+
+def _ficheros_plantillas():
+    return [p for p in DIR_PLANTILLAS.rglob("*")
+            if p.is_file() and p.suffix in (".html", ".py")]
+
+
+# ---------------------------------------------------------------------------
+# 1. Ninguna dependencia externa
+# ---------------------------------------------------------------------------
+def test_las_plantillas_no_referencian_ningun_cdn_externo():
+    """Ninguna plantilla puede pedir un recurso a un CDN externo."""
+    ofensas = []
+    for ruta in _ficheros_plantillas():
+        texto = ruta.read_text(encoding="utf-8", errors="replace")
+        for url in RE_RECURSO.findall(texto):
+            if any(dominio in url for dominio in CDN_PROHIBIDOS):
+                ofensas.append("%s -> %s" % (ruta.name, url))
+    assert not ofensas, "referencias a CDN externos en las plantillas: %s" % ofensas
+
+
+def test_el_javascript_propio_no_referencia_ningun_cdn_externo():
+    """Los .js del proyecto tampoco deben pedir recursos externos."""
+    ofensas = []
+    for ruta in DIR_JS.rglob("*.js"):
+        texto = ruta.read_text(encoding="utf-8", errors="replace")
+        for url in RE_RECURSO.findall(texto):
+            if any(dominio in url for dominio in CDN_PROHIBIDOS):
+                ofensas.append("%s -> %s" % (ruta.name, url))
+    assert not ofensas, "referencias a CDN externos en el JS: %s" % ofensas
+
+
+def test_la_plantilla_base_carga_los_recursos_locales():
+    """base.html debe apuntar a los tres recursos autoalojados."""
+    html = (DIR_PLANTILLAS / "base.html").read_text(encoding="utf-8")
+
+    assert '/static/css/tailwind.css' in html
+    assert '/static/js/sortable.min.js' in html
+    assert '/static/css/fonts.css' in html
+    # Y no debe quedar el compilador en el navegador ni el config en linea.
+    # (Los COMENTARIOS de la plantilla si los mencionan: lo que no puede
+    # aparecer es una peticion real a un CDN.)
+    assert "tailwind.config =" not in html
+    urls = RE_RECURSO.findall(html)
+    externas = [u for u in urls
+                if any(d in u for d in CDN_PROHIBIDOS)]
+    assert not externas, "base.html todavia pide recursos externos: %s" % externas
+
+
+# ---------------------------------------------------------------------------
+# 2. Los recursos estan versionados y completos
+# ---------------------------------------------------------------------------
+def test_el_css_de_tailwind_esta_compilado_y_versionado():
+    """El CSS compilado existe y tiene las utilidades basicas."""
+    assert CSS_TAILWIND.exists(), "falta el CSS compilado de Tailwind"
+    css = CSS_TAILWIND.read_text(encoding="utf-8")
+    assert len(css) > 20000, "el CSS compilado es sospechosamente pequeno"
+    for utilidad in (".flex{", ".hidden{", ".grid{", ".rounded-lg{", ".w-10{"):
+        assert utilidad in css, "falta la utilidad %s en el CSS" % utilidad
+
+
+def test_la_entrada_y_la_configuracion_de_tailwind_estan():
+    """Debe poder recompilarse el CSS sin herramientas de Python."""
+    assert ENTRADA.exists(), "falta la entrada de la compilacion"
+    entrada = ENTRADA.read_text(encoding="utf-8")
+    assert "@tailwind base;" in entrada
+    assert "@tailwind utilities;" in entrada
+
+    assert CONFIG.exists(), "falta tailwind.config.js"
+    config = CONFIG.read_text(encoding="utf-8")
+    # El escaneo debe cubrir TODO el codigo de la aplicacion: hay markup
+    # que se arma en app/core (el badge de Resultado de Pruebas, que usa
+    # 'py-[1px]') y no solo en las plantillas.
+    assert "./app/**/*.py" in config
+    assert "./app/**/*.html" in config
+    assert "./app/static/js/**/*.js" in config
+    # La fuente del tema se mantiene (la usaba el config en linea).
+    assert "Inter" in config
+
+
+def test_sortable_esta_autohospedado():
+    """SortableJS debe estar en el repositorio, con su version."""
+    assert JS_SORTABLE.exists(), "falta SortableJS autoalojado"
+    texto = JS_SORTABLE.read_text(encoding="utf-8", errors="replace")
+    assert "Sortable" in texto
+    assert "1.15.2" in texto
+    assert len(texto) > 10000
+
+
+def test_la_fuente_esta_autohospedada():
+    """La fuente Inter se sirve desde /static, no desde Google."""
+    assert CSS_FUENTES.exists(), "falta el CSS de la fuente autoalojada"
+    css = CSS_FUENTES.read_text(encoding="utf-8")
+    assert "@font-face" in css
+    assert "Inter" in css
+    assert "/static/fonts/" in css
+    # Ninguna URL externa: ni en las reglas ni en los comentarios.
+    externas = RE_RECURSO.findall(css) + re.findall(r"url\(\s*['\"]?(https?://[^)'\"]+)", css)
+    assert not externas, "la fuente sigue apuntando a un servidor externo: %s" % externas
+
+    woff2 = list(DIR_FUENTES.glob("*.woff2"))
+    assert woff2, "no hay ficheros de fuente"
+    for f in woff2:
+        assert f.stat().st_size > 1000, "%s esta vacio" % f.name
+        assert f.read_bytes()[:4] == b"wOF2", "%s no es un woff2" % f.name
+
+
+# ---------------------------------------------------------------------------
+# 3. Los recursos se sirven de verdad
+# ---------------------------------------------------------------------------
+@pytest.fixture(scope="module")
+def local_client():
+    from app.db.base import Base
+    from app.db.session import engine
+    from app.main import app
+
+    Base.metadata.create_all(bind=engine)
+    with TestClient(app) as client:
+        yield client
+
+
+@pytest.mark.parametrize("ruta", [
+    "/static/css/tailwind.css",
+    "/static/css/fonts.css",
+    "/static/js/sortable.min.js",
+    "/static/fonts/inter-latin.woff2",
+])
+def test_los_recursos_autohospedados_se_sirven(local_client, ruta):
+    """Los tres recursos responden 200 desde /static."""
+    r = local_client.get(ruta)
+    assert r.status_code == 200, "%s -> %s" % (ruta, r.status_code)
+    assert len(r.content) > 500, "%s devuelve un cuerpo vacio" % ruta
+
+
+def test_el_html_servido_no_pide_recursos_externos(local_client):
+    """La pagina de acceso no debe cargar ningun recurso de un CDN."""
+    r = local_client.get("/auth/login")
+    assert r.status_code == 200, r.text
+    html = r.text
+    externas = [u for u in RE_RECURSO.findall(html)
+                if any(d in u for d in CDN_PROHIBIDOS)]
+    assert not externas, "la pagina servida pide recursos externos: %s" % externas
+    assert '/static/css/tailwind.css' in html
