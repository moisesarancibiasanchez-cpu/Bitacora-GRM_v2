================================================================================
README V2.003 - DASHBOARD EN BLANCO: CORRECCION DEL ERROR DE SINTAXIS
JAVASCRIPT Y VALIDADOR DE SINTAXIS DE PLANTILLAS
Proyecto: Bitacora GRM v2
Fecha: 2026-10-26
Rama base: main y release/v2.001 (commit a175632)
Estado: CODIGO LISTO Y VERIFICADO EN LOCAL. PENDIENTE DE DESPLEGUE.
================================================================================

0. PARCHE EXACTO

  Ficheros intervenidos:
    - app/templates/dashboard/index.html
        (2 lineas de codigo corregidas; 3 lineas reindentadas dentro del
        mismo bloque; ninguna otra linea del fichero cambia)
    - tests/test_v2003_sintaxis_js_plantillas.py   (nuevo, 5 tests)

  Funcion intervenida (app/templates/dashboard/index.html):
    - _renderModalKpiDetalle()   [unico punto de cambio funcional]

  Funciones nuevas (tests/test_v2003_sintaxis_js_plantillas.py):
    - valida_js()                 [validador de sintaxis JS]
    - extrae_scripts()            [extraccion de bloques <script> de JS]
    - _lex()                      [lexico de JavaScript]
    - _puede_iniciar()            [token que puede iniciar una expresion]
    - _puede_terminar()           [token que puede terminar una expresion]
    - Problema                    [defecto detectado]

  Tests nuevos (tests/test_v2003_sintaxis_js_plantillas.py):
    - test_el_validador_detecta_el_defecto_original
    - test_ninguna_plantilla_tiene_defectos_de_sintaxis_js
    - test_los_ficheros_js_propios_no_tienen_defectos_de_sintaxis
    - test_dashboard_sin_concatenacion_rota_de_ternario
    - test_el_html_renderizado_del_dashboard_pasa_el_validador

  El diff completo esta al final de este documento, en el APENDICE A.

================================================================================
1. BASE
================================================================================

  Base de este cambio: el commit a175632, que es la punta de 'main' y de
  'release/v2.001'. Ese commit contiene el lote V2.002 (b403de6) y solo anade
  documentacion (addendum 9), por lo que el arbol de codigo es identico al de
  b403de6.

  Lo que estaba EN PRODUCCION al abrir este lote: el lote V2.002 completo.
    - web   -> commit 1900def (autoDeploy desde 'main'; arbol identico al de
               b403de6)
    - worker -> commit b403de6
    - beat  -> commit b403de6

  Contexto del defecto reportado por el propietario (2026-10-26):

    "Excelente, pero se danio el dashboard, dado que NO carga nada".

  Medicion (2026-10-26, contra produccion con el lote V2.002 desplegado):

    GET /dashboard
      -> HTTP 200, 140.724 bytes. El HTML LLEGABA al navegador.
      -> La consola del navegador registra:
             SyntaxError: Unexpected token '?'
             http://.../dashboard  linea 1452, columna 17
      -> La pagina se queda indefinidamente en "Cargando metricas...": el
         spinner sigue girando y todas las casillas de KPI se quedan en "---".

    Es decir: el fallo NO era de backend ni de plantilla renderizada, era de
    JavaScript. Y era del bloque <script> INLINE UNICO del dashboard, de modo
    que el error abortaba el script entero: no cargaban ni las tarjetas de
    KPI, ni la distribucion por estado o prioridad, ni la tabla de la "Lista
    de Incidencias Recientes", ni la tabla pivote de "Cuenta de Resultado",
    ni el modal de drill-down.

    Todos los endpoints que consume la pagina respondian correctamente
    (medidos con sesion de administrador):

      GET /api/v1/metricas/dashboard-completo?dias=30 -> 200 (0,82 s)
      GET /api/v1/metricas/resumen?dias=30            -> 200 (0,55 s)
      GET /api/v1/metricas/cuenta-resultado            -> 200 (2,70 s)
      GET /api/v1/metricas/incidencias-recientes       -> 200 (0,59 s)
      GET /api/v1/metricas/detalle-kpi                 -> 200 (0,56 s)

  CAUSA RAIZ:

    En la funcion '_renderModalKpiDetalle()' de
    'app/templates/dashboard/index.html', el ternario que muestra el aviso de
    listados truncados quedo escrito con los signos '+' de la concatenacion
    tambien en las lineas de continuacion del ternario:

        +       (data.truncado
        +         ? '<p class="text-[11px] text-amber-600 mt-1">Se muestran '
        +             + (data.total_listado || 0) + ' de ' + (data.total || 0)
        +             + ' tickets: el listado esta limitado a ' + (data.limite || 0)
        +             + ' filas. Usa "Exportar CSV" para el periodo completo.</p>'
        +         : '')

    Los signos '+' de las lineas 1, 3, 4 y 5 son correctos: son concatenacion
    de cadenas dentro de la rama verdadera del ternario. Los signos '+' de
    las lineas 2 y 6 NO lo son: dentro de un ternario no hay concatenacion,
    de modo que el parser leia

        data.truncado + ? '<p ...'

    y el navegador rechazaba el bloque completo con
    "SyntaxError: Unexpected token '?'" (la '?' de la linea 1452 es
    precisamente el caracter que el parser rechaza).

    El defecto lo introdujo el propio lote V2.002 (commit b403de6), que
    reescribio '_renderModalKpiDetalle()' para anadir el aviso de truncado.

  POR QUE LA SUITE DE V2.002 NO LO DETECTO:

    Ninguna prueba de la suite ejecuta JavaScript. Las pruebas de V2.002
    comprueban el HTML de la plantilla con expresiones regulares y el HTML
    renderizado por el cliente HTTP de pruebas. Un error de sintaxis JavaScript
    es invisible para las dos: el HTML se sirve igual (HTTP 200) y las
    pruebas pasaban mientras el dashboard estaba roto en produccion.

    La leccion: la suite tiene que poder FALLAR ante este tipo de defecto.
    De ahi el validador de sintaxis que se anade en la seccion 2.
================================================================================
2. CAMBIO UNICO
================================================================================

  QUE EL BLOQUE <script> INLINE DEL DASHBOARD VUELVA A SER JAVASCRIPT VALIDO
  PARA EL NAVEGADOR, de modo que TODO el dashboard vuelva a ejecutarse
  (tarjetas de KPI, distribuciones, tabla de incidencias recientes, tabla
  pivote de "Cuenta de Resultado" y modal de drill-down), conservando
  intacto el comportamiento funcional del lote V2.002.

  QUE SE HIZO:

  1) Correccion del ternario roto en '_renderModalKpiDetalle()'
     (app/templates/dashboard/index.html).

     ANTES (JavaScript invalido, el navegador aborta el bloque entero):

        +       (data.truncado
        +         ? '<p class="text-[11px] text-amber-600 mt-1">Se muestran '
        +             + (data.total_listado || 0) + ' de ' + (data.total || 0)
        +             + ' tickets: el listado esta limitado a ' + (data.limite || 0)
        +             + ' filas. Usa "Exportar CSV" para el periodo completo.</p>'
        +         : '')

     DESPUES (JavaScript valido; la rama verdadera sigue concatenando
     cadenas con sus propios '+'):

        +       (data.truncado
          ? '<p class="text-[11px] text-amber-600 mt-1">Se muestran '
              + (data.total_listado || 0) + ' de ' + (data.total || 0)
              + ' tickets: el listado esta limitado a ' + (data.limite || 0)
              + ' filas. Usa "Exportar CSV" para el periodo completo.</p>'
          : '')

     El cambio es de 2 lineas de codigo (mas 3 lineas reindentadas dentro
     del mismo bloque). No se altera ni la logica, ni el texto, ni los
     valores que muestra el modal: el aviso de truncamiento sigue
     apareciendo exactamente igual que en V2.002.

  2) Red de seguridad automatica: validador de sintaxis JavaScript para las
     plantillas (tests/test_v2003_sintaxis_js_plantillas.py, nuevo).

     El validador es un lexico de JavaScript escrito en Python (sin
     dependencias nuevas, porque 'requirements.txt' esta fijado y no se
     pueden anadir paquetes). Comprueba, para cada bloque <script> inline de
     'app/templates/**/*.html' y para cada fichero '.js' propio de
     'app/static/js' (excluidos los '*.min.js' de terceros):

       a) que todas las cadenas, plantillas, comentarios y expresiones
          regulares terminen correctamente;
       b) que los delimitadores '(', '[' y '{' esten balanceados y bien
          emparejados;
       c) que un operador binario no vaya seguido de un token que no pueda
          iniciar una expresion (por ejemplo '+ ?' o '+ :'), que es
          exactamente la regla que hizo fallar al dashboard;
       d) que un '?' ternario vaya seguido de un token que pueda iniciar una
          expresion.

     Ademas, la suite incluye un test de autocomprobacion
     ('test_el_validador_detecta_el_defecto_original'): si el validador
     dejara de detectar el defecto original, ese test falla. Asi el
     fichero no puede quedarse sin dientes en silencio.

  COMPROBACION DE QUE EL VALIDADOR DETECTA EL DEFECTO (medido, no supuesto):

    Se ejecuto el validador contra las tres versiones de la plantilla:

      commit c6eca9b (viernes, anterior a V2.002) -> 0 problemas
      commit b403de6 (V2.002, con el defecto)       -> 2 problemas
      commit a175632 (V2.002 + documentacion)       -> 2 problemas
      arbol de trabajo con la correccion            -> 0 problemas

    Los 2 problemas del commit con defecto son, en la linea 711 y la 715 del
    bloque (numeracion interna del bloque):

      el operador '+' va seguido de un token que no puede iniciar una
      expresion (SyntaxError: Unexpected token)

    Y se verifico que el test tiene dientes de verdad: rompiendo
    temporalmente la plantilla con el defecto original, la suite nueva pasa
    a 3 tests fallidos de 5
    ('test_ninguna_plantilla_tiene_defectos_de_sintaxis_js',
     'test_dashboard_sin_concatenacion_rota_de_ternario' y
     'test_el_html_renderizado_del_dashboard_pasa_el_validador');
     restaurando la correccion, vuelve a 5 passed.

================================================================================
3. QUE NO SE MODIFICO
================================================================================

  - NINGUN endpoint. No se toco 'app/api/v1/metricas.py' ni ningun otro
    fichero de 'app/api/'. La correccion es 100 % de plantilla.

  - NINGUNA logica de V2.002. Siguen intactos:
      * '_resolver_rango_temporal()' (backend) y su equivalente
        '_filtrosIncidenciasRecientes()' (front);
      * el rango explicito 'fecha_desde' / 'fecha_hasta' en
        '/api/v1/metricas/detalle-kpi';
      * el conteo real del KPI ('total', 'total_listado', 'truncado');
      * el 'outerjoin' con 'estados';
      * el texto del modal y el aviso de truncamiento;
      * el badge "N TICKETS" y el rango real mostrado en el modal.

  - NINGUN otro fichero de plantilla. Solo 'app/templates/dashboard/index.html'
    y, dentro de el, solo el ternario de '_renderModalKpiDetalle()'.

  - NINGUN otro fichero JavaScript. No se toco 'app/static/js/*'.

  - NINGUNA paleta. 'app/core/resultado_pruebas.py' sigue siendo la unica
    fuente de verdad de la paleta de "Cuenta de Resultado"; no se duplico
    ningun hex en el JS ni en las plantillas.

  - NINGUNA dependencia. 'requirements.txt' no se modifica. El validador de
    sintaxis esta escrito en Python puro, sin paquetes nuevos.

  - NINGUN cambio de base de datos, migraciones, seeds ni scripts.

  - NINGUN cambio de seguridad: no se tocan la autenticacion, los permisos,
    las cabeceras (CSP, HSTS, X-Frame-Options, X-Content-Type-Options,
    Permissions-Policy) ni el cierre del registro publico.

  - NINGUN cambio de configuracion de Railway, ni de variables de entorno,
    ni de cron/schedules de Celery.

  - NINGUN fichero eliminado ni renombrado.

================================================================================
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  - REQUIERE CAMBIAR WORKER: NO. El cambio afecta unicamente a la plantilla
    HTML que sirve el servicio web. El worker no lee ni renderiza esa
    plantilla.

  - REQUIERE CAMBIAR BEAT: NO. Same reasoning: el beat solo dispara tareas
    periodicas de Celery.

  - REQUIERE REINICIAR LA COLA DE CELERY: NO.

  - REQUIERE MIGRACIONES DE BASE DE DATOS: NO.

  - REQUIERE CAMBIOS DE VARIABLES DE ENTORNO: NO.

  - REQUIERE LIMPIEZA DE CACHE O CDN: NO. El HTML se genera en el servidor;
    no hay cache de assets con hash.

  - REQUIERE COMPILACION O BUILD: NO. El cambio es de un fichero de
    plantilla y de un fichero de test.

  NOTA OPERATIVA:

    Por simetria, y para no dejar los tres servicios con arboles distintos
    (que ya provoco un incidente de desalineacion en este proyecto), el
    despliegue recomendado es publicar el MISMO commit en los tres
    servicios: web, worker y beat.

    Recordatorio de operacion: el servicio 'web' tiene autoDeploy siguiendo
    la rama 'main', de modo que un push a 'main' redespliega el web por su
    cuenta. El 'worker' y el 'beat' NO tienen autoDeploy: hay que
    desplegarlos de forma explicita con el commit exacto.

================================================================================
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 PRUEBA AUTOMATICA (obligatoria, antes de publicar)

    a) Suite nueva de regresion (rapida, ~15 s):

       cd <repo>
       & 'C:\Python311embed\python.exe' -X utf8 -m pytest \
           tests/test_v2003_sintaxis_js_plantillas.py -q --tb=short -p no:logging

       Resultado esperado: 5 passed.

    b) Suite completa (tarda unos 11 minutos):

       & 'C:\Python311embed\python.exe' -X utf8 -m pytest tests/ -q --tb=line \
           -p no:logging

       Resultado esperado: 169 passed (164 heredados + 5 nuevos), 0 failed.

    c) Comprobacion de que el test NO es vacuo (opcional pero recomendado):
       deshacer temporalmente la correccion del ternario y volver a lanzar
       (a). El resultado esperado es 3 failed de 5.

  5.2 PRUEBA MANUAL EN NAVEGADOR (obligatoria tras el despliegue)

    a) Abrir https://bitacora-grmv2-production.up.railway.app/dashboard e
       iniciar sesion.

    b) Abrir la consola del navegador (F12 -> Console). NO debe aparecer
       ningun error de tipo "SyntaxError". Antes del arreglo aparecia:

         SyntaxError: Unexpected token '?'   (linea 1452)

    c) Comprobar que la pagina NO se queda en "Cargando metricas...". En la
       franja superior deben verse los valores reales:

         TOTAL 931 | NUEVAS (7D) 1 | ABIERTAS 18 | % SLA 96.2%
         CRIT. SIN ASIGNAR 0 | INCIDENCIAS ABIERTAS 3

    d) Comprobar que se pintan las secciones: "Distribucion por estado",
       "Distribucion por prioridad", "Proximos a vencer SLA", "Cuenta de
       Resultado" (tabla pivote con las columnas N/A, NOK, OK, OBS, POST,
       NOOK, S/D) y "Lista de Incidencias Recientes".

    e) Comprobar el caso original del lote V2.002, que es el que el
       propietario reporto:
         - En la seccion "Lista de Incidencias Recientes", elegir el bloque
           rapido "Ultimos 90 dias".
         - El badge de la cabecera de la seccion debe mostrar el rango
           explicito y el total, por ejemplo:
               2026-07-28 -> 2026-10-26 . 18 TICKETS
         - Hacer clic en la casilla "TOTAL PERIODO".
         - El modal debe mostrar:
               Periodo: 2026-07-28 -> 2026-10-26 . Tipo: incidencia
               . Total: 18 tickets
         - RESUMEN Y MODAL TIENEN QUE COINCIDIR (18 = 18).

  5.3 PRUEBA POR API (opcional, solo GET y POST de login)

    Tras iniciar sesion, comprobar:

      GET /api/v1/metricas/dashboard-completo?dias=30   -> 200
      GET /api/v1/metricas/incidencias-recientes        -> 200
          ?tipo=incidencia&periodo_dias=30&limite=200
      GET /api/v1/metricas/detalle-kpi                 -> 200
          ?kpi=total_periodo&periodo_dias=30&tipo=incidencia&limite=200

    y que 'metricas.total_periodo' del resumen es IGUAL a 'total' del modal.

================================================================================
6. TRAZABILIDAD
================================================================================

  Commit base:            a1756322132e557064a74d06815896db35b6d7a2
  Rama base:              main (y release/v2.001, mismo commit)
  Commit que introduce
  el defecto:            b403de6 (lote V2.002)
  Commit que lo anade
  a 'main':              1900def (commit de fusion)

  Ficheros intervenidos:
    app/templates/dashboard/index.html
      - funcion '_renderModalKpiDetalle()', bloque del aviso de truncado
        (numeracion de linea del fichero: 1233-1238 antes; 1233-1238
        despues, con la correccion en las lineas 1234 y 1238).
    tests/test_v2003_sintaxis_js_plantillas.py   (nuevo)

  Endpoints IMPLICADOS:
    (ninguno: el arreglo no toca el backend)

  Herramientas de diagnostico utilizadas (ninguna forma parte del repo):
    - harness local en 127.0.0.1:8765 que servia el HTML REAL de
      produccion y hacia de proxy de '/api/*' contra produccion, para leer
      la consola del navegador con el HTML y los datos reales;
    - lexico de JavaScript en Python (el mismo que ahora vive en los tests);
    - lectura de la consola del navegador embebido (kind=console) y de la
      red (kind=network).

  Evidencia de la correccion (medida, 2026-10-26):
    - consola del navegador tras el arreglo: sin excepciones; aparecen los
      mensajes '[dashboard] cargarMetricas: periodo=30', '[dashboard] data OK'
      y '[dashboard] cargarMetricas: finally ejecutado, spinner oculto';
    - la franja de KPI se pinta con los valores reales (931 / 19 / 96.2% / 3);
    - el badge de la seccion muestra '2026-07-28 -> 2026-10-26 . 18 TICKETS';
    - el modal muestra 'Periodo: 2026-07-28 -> 2026-10-26 . Tipo: incidencia
      . Total: 18 tickets' y lista los 18 tickets;
    - la suite nueva de regresion: 5 passed;
    - con el defecto reintroducido temporalmente: 3 failed de 5.

================================================================================
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  7.1 PUBLICACION

    a) Publicar el commit en las dos ramas, sin reescribir historia:

         git push origin <commit>:main
         git push origin <commit>:release/v2.001

       (push fast-forward; nunca usar '--force').

       Efecto: el 'web' se redespliega solo por autoDeploy desde 'main'.

    b) Desplegar explicitamente 'worker' y 'beat' con el MISMO commit
       (no tienen autoDeploy):

         python tmp_deploy_railway.py <commit> worker
         python tmp_deploy_railway.py <commit> beat

    c) Confirmar que los tres servicios quedaron en el mismo commit:

         python tmp_deploy_railway.py --estado

       Los tres deben mostrar el mismo 'commitSha' y estado SUCCESS.

    d) Verificacion de salud tras el despliegue:

         GET /health   -> 200  (db ok, redis ok)
         GET /ready    -> 200
         GET /info     -> 200
         POST /api/v1/auth/login (admin) -> 200
         GET /dashboard -> 200 y el HTML contiene '_renderModalKpiDetalle'

    e) Verificacion funcional: hacer los pasos 5.2 (b) a (e) en el
       navegador contra el servicio desplegado.

  7.2 ROLLBACK

    Si hubiera que volver atras, el commit de referencia es 'a175632' (el
    arbol con el defecto) y el arbol bueno anterior es '6038fc29' (la version
    del viernes 2026-10-23, ancestro comun de todo el trabajo V1.001 a
    V2.003).

    Rollback al arbol con el defecto (solo para diagnostico, NO recomendado:
    reproduce el dashboard en blanco):

         git revert <commit de V2.003>
         git push origin main
         y desplegar worker y beat con ese commit

    Rollback al arbol estable del viernes:

         git checkout <commit-estable>
         git push origin HEAD:main --force-with-lease   (solo con autorizacion
                                                           expresa del
                                                           propietario)

    En Railway, el rollback operativo consiste en volver a desplegar el
    commit deseado en los tres servicios:

         python tmp_deploy_railway.py <commit> web
         python tmp_deploy_railway.py <commit> worker
         python tmp_deploy_railway.py <commit> beat

    Nota: el despliegue del 'web' por autoDeploy sigue a 'main'. Si se
    cambia el arbol de 'main', hay que desplegar a mano 'worker' y 'beat'
    con el mismo commit para no volver a desalinear los tres servicios
    (incidente ya ocurrido en este proyecto).

  7.3 COMPROBACION POST-DESPLIEGUE OBLIGATORIA

    Antes de dar el lote por cerrado, comprobar que en la consola del
    navegador NO hay ninguna excepcion, que la pagina NO se queda en
    "Cargando metricas..." y que resumen y modal coinciden. El detalle
    completo esta en la seccion 5.


================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

  El diff que sigue es el EXACTO del cambio funcional (fichero de plantilla).
  Va TRANSLITERADO a ASCII: los caracteres acentuados del codigo original
  ('a' con tilde, 'i' con tilde, el punto medio, etc.) se han sustituido por
  su equivalente ASCII. ESTA TRANSLITERACION ES SOLO DOCUMENTAL: el codigo
  del proyecto NO se modifica, conserva sus caracteres originales en UTF-8.

  Diff de app/templates/dashboard/index.html:

diff --git a/app/templates/dashboard/index.html b/app/templates/dashboard/index.html
index b0e3193..8dd35fb 100644
--- a/app/templates/dashboard/index.html
+++ b/app/templates/dashboard/index.html
@@ -1231,11 +1231,11 @@
       +         '  -  Total: <span class="font-mono">' + (data.total || 0) + '</span> tickets'
       +       '</p>'
       +       (data.truncado
-      +         ? '<p class="text-[11px] text-amber-600 mt-1">Se muestran '
-      +             + (data.total_listado || 0) + ' de ' + (data.total || 0)
-      +             + ' tickets: el listado esta limitado a ' + (data.limite || 0)
-      +             + ' filas. Usa "Exportar CSV" para el periodo completo.</p>'
-      +         : '')
+        ? '<p class="text-[11px] text-amber-600 mt-1">Se muestran '
+            + (data.total_listado || 0) + ' de ' + (data.total || 0)
+            + ' tickets: el listado esta limitado a ' + (data.limite || 0)
+            + ' filas. Usa "Exportar CSV" para el periodo completo.</p>'
+        : '')
       +     '</div>'
       +     '<button type="button" data-close-modal="1" class="text-slate-400 hover:text-slate-700 p-1" aria-label="Cerrar">'
       +       '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'

  Fichero NUEVO (no aparece en el diff anterior porque no estaba
  versionado): tests/test_v2003_sintaxis_js_plantillas.py
  5 tests de regresion de sintaxis JavaScript (ver seccion 2).
