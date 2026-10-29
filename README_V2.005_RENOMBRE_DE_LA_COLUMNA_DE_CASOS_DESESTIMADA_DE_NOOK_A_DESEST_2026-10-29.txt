================================================================================
README V2.005 - RENOMBRE DE LA COLUMNA DE CASOS DESESTIMADA: DE "NOOK" A "DESEST"
Proyecto: Bitacora GRM v2
Fecha: 2026-10-29
Rama base: main y release/v2.001 (commit e7806da)
Estado: DESPLEGADO EN PRODUCCION Y VERIFICADO. Ver seccion 9.
================================================================================

0. PARCHE EXACTO

  Ficheros intervenidos:
    - app/core/resultado_pruebas.py            (SSOT: acronimo de la categoria)
    - app/templates/dashboard/index.html       (2 comentarios de la plantilla)
    - docs/QA_REPORT_RESULTADO_PRUEBAS.md     (ficha de la categoria)
    - docs/onboarding-demo/index.html          (demo de onboarding: 4 puntos)
    - docs/onboarding-demo/imgs/resultado-pruebas.svg (badge del demo)
    - tests/test_v2005_acronimo_desest.py      (nuevo, 11 tests)

  Cambio funcional: UNA SOLA LINEA de codigo.

    app/core/resultado_pruebas.py
        ACRONIMOS = {
            ...
            "DESESTIMADA": "NOOK",   ->   "DESESTIMADA": "DESEST",
            ...
        }

  Todo lo demas es documentacion (comentarios y fichas) y la suite nueva.

  Todo el texto de la plantilla, del catalogo y de la ficha de la categoria
  que NOMBRA el acronimo (incluido el titulo de la columna del dashboard) esta
  en un solo sitio: el catalogo. La plantilla NO redeclara el mapa de
  acronimos: lo lee del JSON que inyecta el servidor. Por eso el cambio se
  propaga por construccion a todos los sitios que muestran el titulo.

  Tests nuevos (tests/test_v2005_acronimo_desest.py, 11 tests):
    - test_el_catalogo_titula_desestimada_como_desest
    - test_ningun_valor_del_catalogo_usa_el_acronimo_heredado
    - test_la_paleta_de_desestimada_no_cambia
    - test_el_valor_del_lov_no_cambia
    - test_la_ficha_del_resultado_usa_el_acronimo_nuevo
    - test_el_badge_de_la_tarjeta_muestra_desest_y_conserva_el_color
    - test_la_plantilla_no_hardcodea_el_acronimo_heredado
    - test_la_plantilla_toma_el_titulo_del_json_inyectado
    - test_el_drilldown_conserva_el_valor_del_lov
    - test_el_dashboard_inyecta_el_acronimo_nuevo
    - test_el_dashboard_sigue_inyectando_la_paleta_y_el_lov

  El diff completo esta al final de este documento, en el APENDICE A.

================================================================================
1. BASE
================================================================================

  Base de este cambio: el commit e7806da, punta de 'main' y de
  'release/v2.001'. Contiene el lote V2.004 (34653e1 + e7806da), que
  establecio el prefijo SOL- para los tipos que no son incidencia y la
  exclusion estructural del bloque de incidencias del dashboard.

  Contexto del defecto (validado por el propietario el 2026-10-29):

    "En seccion Cuenta de Resultado del Dashboard en los titulos de la tabla
     respectiva aparece la Columna NOOK pero esta corresponde a los Casos
     DESESTIMADAS entonces ponle nombre correcto a la Columna: 'DESEST'"

  VALIDACION PREVIA (hecha antes de tocar nada, 2026-10-29, solo lectura
  contra produccion: GET y POST de login):

    a) Valores REALES de 'resultado_pruebas' en la base de datos
       (GET /api/v1/tickets -> 933 tickets):

         'OK'           716
         'N/A'          130
         'POSTERGADA'    54
         'DESESTIMADA'   21
         'NOK'            6
         'OK CON OBS.'    4
         ''               2      (NULL / vacio -> columna "(en blanco)")
         --------------------------
         valores fuera del LOV: NINGUNO

       Conclusion: en produccion NO existe ni un solo valor crudo "NOOK".
       Los 21 casos desestimados estan guardados con el valor canonico
       "DESESTIMADA". Por tanto, este lote es puramente de presentacion:
       no hay nada que reclasificar ni que migrar.

    b) Columnas del pivote (GET /api/v1/metricas/cuenta-resultado):

         columnas = ["N/A","NOK","OK","OK CON OBS.","POSTERGADA",
                     "DESESTIMADA","(en blanco)"]
         totales_por_columna = {"N/A":128,"NOK":4,"OK":701,"OK CON OBS.":4,
                                 "POSTERGADA":54,"DESESTIMADA":21,
                                 "(en blanco)":0}

       La columna de los 21 casos desestimados se titula "DESESTIMADA" (el
       valor del LOV), que es correcto: el titulo visible es su ACRONIMO.

    c) Acronimos realmente inyectados en la plantilla
       (GET /dashboard, bloque id="cuenta-resultado-acronimos"):

         {"(en blanco)":"S/D","DESESTIMADA":"NOOK","N/A":"N/A","NOK":"NOK",
          "OK":"OK","OK CON OBS.":"OBS","POSTERGADA":"POST"}

       Confirmado: el encabezado que ve el operador es "NOOK".

  CAUSA RAIZ:

    El titulo de cada columna de la tabla "Cuenta de Resultado" es el
    ACRONIMO del valor del LOV. Ese acronimo no vive en la plantilla: vive
    en el catalogo unico 'app/core/resultado_pruebas.py' (diccionario
    ACRONIMOS), que el servidor serializa e inyecta en la pagina
    (app/main.py -> acronimos_js()).

    En ese catalogo, el valor "DESESTIMADA" tenia como acronimo "NOOK",
    un nombre heredado de la hoja UAT. La plantilla lo pintaba tal cual
    porque, por construccion, hace lo que el catalogo dice:

        function acronimoResultado(c) {
          return CUENTA_RESULTADO_ACRONIMOS[c] || c;
        }

  POR QUE CONFUNDIA (motivo del pedido):

    "NOOK" era el nombre de la categoria DESESTIMADA en la hoja UAT, pero
    en el LOV conviven DOS categorias distintas:

      DESESTIMADA -> acronimo "NOOK" (antes) / "DESEST" (ahora), violeta
      NOK         -> acronimo "NOK", rojo (#dc2626)

    Con dos columnas consecutivas tituladas "NOOK" y "NOK" no se puede
    saber de un vistazo cual es la de los casos desestimados. "DESEST"
    elimina la ambiguedad sin alargar el titulo mas de lo necesario.

================================================================================
2. CAMBIO UNICO
================================================================================

  2.1 EL CAMBIO

    Se cambia el ACRONIMO de la categoria DESESTIMADA en el catalogo
    unico 'app/core/resultado_pruebas.py':

        -    "DESESTIMADA": "NOOK",
        +    "DESESTIMADA": "DESEST",

    Es el UNICO cambio de comportamiento del lote. Todo lo demas son
    comentarios, documentacion y tests.

  2.2 QUE LUGARES CAMBIAN (por construccion, no por codigo nuevo)

    El acronimo viaja desde el catalogo hasta la pantalla por un unico
    camino, de modo que estos cuatro sitios cambian a la vez y sin
    posibilidad de que se desincronicen:

    a) El ENCABEZADO de la tabla "Cuenta de Resultado" del Dashboard.
       Plantilla app/templates/dashboard/index.html, construccion del
       <thead> a partir de 'columnas.map(...)' + 'acronimoResultado(c)'.
       Antes: <th style="background:#7c3aed; color:#ffffff;">NOOK</th>
       Ahora: <th style="background:#7c3aed; color:#ffffff;">DESEST</th>
       El title (tooltip) NO cambia: sigue mostrando el valor completo
       del LOV, "Tickets con resultado_pruebas = 'DESESTIMADA'".

    b) El ENCABEZADO de la tabla secundaria del mismo bloque
       ('renderCuentaResultado'), que usa el mismo helper. Queda
       coherente por construccion.

    c) El BADGE de "Resultado de Pruebas" de las tarjetas del Kanban
       (app/core/resultado_pruebas.py -> info_resultado() ->
       render_badge_resultado()). Pasa de "NOOK" a "DESEST" mantendo el
       violeta. El atributo data-resultado-pruebas="DESESTIMADA" no cambia.

    d) El BADGE del modal de drill-down de la celda
       (app/api/v1/metricas.py, etiqueta de resultado del ticket). Cambia
       de "NOOK" a "DESEST" porque consume el mismo diccionario.

  2.3 LO QUE NO SE TOCA DENTRO DEL CAMBIO

    - El valor del LOV: sigue siendo "DESESTIMADA" (columna del pivote,
      valor en base de datos, title del encabezado, parametro del
      drill-down).
    - La paleta: clave "DESESTIMADA" con bg #7c3aed, text #ffffff y
      cellText #1f2937, sin cambios.
    - El endpoint /api/v1/metricas/cuenta-resultado: ni una linea. Su
      respuesta (columnas, filas, totales_por_columna, total_general) es
      identica antes y despues.
    - La categoria NOK: sigue llamandose "NOK", con su acronimo "NOK" y su
      color rojo.

  2.4 POR QUE NO SE TOCA LA PLANTILLA CON UN LITERAL

    Podria haberse escrito 'DESEST' a mano en la plantilla, pero eso
    duplicaria el valor en dos sitios y volveria a abrir la puerta a que
    el titulo de la columna y el badge de la tarjeta se desincronicen
    (el defecto que el modulo catalogo se creo para evitar). El titulo se
    deriva del catalogo; el catalogo se cambia en un sitio.

================================================================================
3. QUE NO SE MODIFICO
================================================================================

  - La base de datos: ni una escritura, ni una migracion, ni un renumerado.
    Los 21 tickets con resultado DESESTIMADA siguen siendo los mismos 21 y
    el valor guardado sigue siendo "DESESTIMADA".

  - La forma de la API: /api/v1/metricas/cuenta-resultado devuelve
    exactamente el mismo JSON (mismas claves, mismos valores, mismos
    totales). No hay versionado ni parametros nuevos.

  - El drill-down: el parametro 'resultado' de
    /api/v1/metricas/cuenta-resultado/detalle sigue llevando el VALOR del
    LOV ("DESESTIMADA"), no el acronimo, porque es lo que el backend sabe
    filtrar (resultado_norm.in_(["DESESTIMADA","DESESTIMADO"])). El
    acronimo es solo de presentacion.

  - El filtro de la tabla del dashboard, los KPIs, la "Lista de Incidencias
    Recientes", los rangos temporales, los modulos y los estados: nada de
    eso se ha tocado (siguen vigentes los lotes V2.002, V2.003 y V2.004).

  - La numeracion y el prefijo de los tickets (INC-/SOL-/GAR_), la regla de
    codigo SSOT 'app/core/codigo_ticket.py' y la exclusion de los tipos
    no-incidencia: sin cambios.

  - requirements.txt: no se anade ninguna dependencia. El cambio es de un
    literal en un diccionario.

  - El codigo del worker y del beat: no tienen ninguna funcion que pinte
    el titulo de la columna (el dashboard se sirve desde 'web').

  - La documentacion historica: los README de los lotes V1.001, V1.002,
    V1.005 y V2.003 mencionan "NOOK" porque describen el estado de la
    aplicacion en la fecha en que se escribieron. Se dejan intactos como
    registro historico.

  - Los ficheros de entrada 'user_input_files/*.csv': son datos de origen
    (hoja UAT) y no forman parte de la aplicacion.

  PENDIENTE DETECTADO (NO se corrige en este lote, se documenta):

    Los importadores UAT ('app/services/uat_import.py' y
    'tools/load_uat_consolidado.py') normalizan 'BLOQUEADO*' -> DESESTIMADA
    pero NO normalizan el valor heredado "NOOK" -> DESESTIMADA: si llega un
    "NOOK" de la hoja, lo guardan tal cual. Hoy no hay ningun valor crudo
    "NOOK" en produccion (verificado en el punto 1.a), por lo que no hay
    nada que reclasificar y el lote V2.005 no lo toca. PERO una reimportacion
    de la hoja UAT podria dejar filas con resultado "NOOK" que NO sumarian
    en la columna DESESTIMADA del pivote (su filtro SQL solo acepta
    "DESESTIMADA" y "DESESTIMADO"). Si el propietario decide hacer esa
    reimportacion, hay que anadir antes el alias "NOOK" -> "DESESTIMADA" en
    los dos normalizadores y en el filtro del pivote, en un lote aparte.

================================================================================
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  - Variables de entorno: NINGUNA nueva. No se toca ningun secreto, ni
    SECRET_KEY, ni la base de datos, ni Redis, ni la configuracion del
    panel.
  - Migraciones: NINGUNA. No hay cambios de esquema ni de datos.
  - Dependencias: NINGUNA. requirements.txt intacto.
  - Archivo estatico, CSS, JS externo, CDN: NINGUNO.
  - Cache/CDN: no hay que invalidar nada. El HTML se genera en cada
    peticion y el JSON de acronimos va embebido en la propia pagina.

  Servicio 'web':    SI hay que desplegarlo. Es quien sirve /dashboard y
                     quien ejecuta el codigo del catalogo.
  Servicio 'worker': NO requiere cambio funcional. Ninguna tarea en cola
                     lee ACRONIMOS ni pinta el titulo de la columna.
                     OPERATIVAMENTE, si no se despliega, el 'worker' se
                     queda en el commit anterior y los tres servicios
                     quedan desalineados (no rompe nada, pero complica la
                     trazabilidad). Por eso el procedimientorecommended
                     incluye desplegarlo con el MISMO commit.
  Servicio 'beat':   IGUAL que 'worker': sin cambio funcional, pero se
                     despliega con el mismo commit por alineacion.

  NOTA SOBRE autoDeploy: 'web' tiene autoDeploy activado sobre 'main', de
  modo que el push a 'main' lo redespliega solo. 'worker' y 'beat' NO lo
  tienen: hay que desplegarlos a mano.

================================================================================
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 COMPROBACION POR API (solo lectura, la mas objetiva)

    a) Autenticarse:
         POST /api/v1/auth/login  {"username":"...","password":"..."} -> 200

    b) Leer el HTML del dashboard y comprobar el bloque de acronimos:
         GET /dashboard
         El bloque <script id="cuenta-resultado-acronimos"
         type="application/json"> debe contener:
             "DESESTIMADA": "DESEST"
         y NO debe contener la cadena "NOOK" en ningun punto del HTML.

    c) Comprobar que la tabla no cambia de forma:
         GET /api/v1/metricas/cuenta-resultado
         -> "columnas" debe seguir siendo
            ["N/A","NOK","OK","OK CON OBS.","POSTERGADA","DESESTIMADA",
             "(en blanco)"]
         -> "totales_por_columna" debe seguir siendo
            {"N/A":128,"NOK":4,"OK":701,"OK CON OBS.":4,"POSTERGADA":54,
             "DESESTIMADA":21,"(en blanco)":0}
            (los numeros son los de produccion en la fecha del despliegue)

    d) Comprobar el drill-down:
         GET /api/v1/metricas/cuenta-resultado/detalle
             ?modulo=<uno con datos>&resultado=DESESTIMADA&ambiente=QA
         -> 200 y lista los tickets de esa celda. El parametro sigue
            siendo "DESESTIMADA" (valor del LOV), no "DESEST".

  5.2 COMPROBACION VISUAL EN EL NAVEGADOR

    a) Entrar al Dashboard con un usuario administrador.
    b) Bajar a la seccion "Cuenta de Resultado".
    c) El encabezado de columnas debe leerse, de izquierda a derecha:
           N/A | NOK | OK | OBS | POST | DESEST | S/D | Total general
       y NO debe aparecer ningun encabezado "NOOK".
    d) El encabezado "DESEST" debe conservar el fondo violeta (#7c3aed) y
       la fuente blanca, igual que antes del cambio.
    e) Pasar el raton por encima del encabezado "DESEST": el tooltip debe
       seguir mostrando el valor completo
       "Tickets con resultado_pruebas = 'DESESTIMADA'".
    f) Hacer clic en una celda con numero de la columna DESEST: debe abrir
       el modal de detalle con los tickets correspondientes y el titulo
       del modal debe identificar la categoria DESESTIMADA.
    g) Revisar una tarjeta del Kanban con resultado de pruebas desestimado:
       su badge debe decir "DESEST" en violeta (antes deia "NOOK" en
       violeta).
    h) El pie de la tabla debe seguir cuadrando: la columna DESEST suma 21
       y el total general 912 (ambiente QA).
    i) Comprobar que la columna "NOK" (roja) sigue llamandose "NOK" y que
       NO se ha confundido con la columna anterior.
    j) Revisar la consola del navegador: no debe aparecer ningun error.

  5.3 REGRESION RAPIDA (lo que este lote NO debe haber roto)

    a) Los KPIs de la franja superior (total, incidencias, % y backlog).
    b) La "Lista de Incidencias Recientes" y su modal de drill-down, que
       deben seguir cuadrando entre si (invariante del lote V2.002).
    c) El bloque de incidencias, que no debe sumar ningun ticket de tipo
       Solicitud, Problema o Cambio (invariante del lote V2.004).
    d) El alta de un ticket: el selector de "Resultado de pruebas" debe
       seguir ofreciendo "DESESTIMADA" (el VALOR del LOV no cambia) y no
       "DESEST".

================================================================================
6. TRAZABILIDAD
================================================================================

  Requisito                                  Fichero / linea          Test
  -----------------------------------------  -----------------------  ---------------------------------------------
  El titulo de la columna es "DESEST"       app/core/resultado_      test_el_catalogo_titula_desestimada_como_desest
                                             pruebas.py (ACRONIMOS)
  El acronimo heredado desaparece            app/core/resultado_      test_ningun_valor_del_catalogo_usa_el_acronimo_heredado
                                             pruebas.py (ACRONIMOS)
  El color de la categoria no cambia         app/core/resultado_      test_la_paleta_de_desestimada_no_cambia
                                             pruebas.py (COLORES)
  El valor del LOV no cambia                app/core/resultado_      test_el_valor_del_lov_no_cambia
                                             pruebas.py (RESULTADOS_LOV)
  El badge de la tarjeta dice "DESEST"      app/core/resultado_      test_el_badge_de_la_tarjeta_muestra_desest_y_conserva_el_color
                                             pruebas.py (render_badge)
  La ficha del resultado dice "DESEST"      app/core/resultado_      test_la_ficha_del_resultado_usa_el_acronimo_nuevo
                                             pruebas.py (info_resultado)
  La plantilla no lo redeclara              app/templates/dashboard/  test_la_plantilla_no_hardcodea_el_acronimo_heredado
                                             index.html
  La plantilla lo toma del servidor         app/templates/dashboard/  test_la_plantilla_toma_el_titulo_del_json_inyectado
                                             index.html
  El drill-down sigue con el valor del LOV   app/api/v1/metricas.py   test_el_drilldown_conserva_el_valor_del_lov
  El servidor sirve el acronimo nuevo        app/main.py              test_el_dashboard_inyecta_el_acronimo_nuevo
  La paleta y el LOV siguen inyectados      app/main.py              test_el_dashboard_sigue_inyectando_la_paleta_y_el_lov

  Codigo que recibe el acronimo (sin cambios de comportamiento, solo la
  fuente del valor):
    app/core/resultado_pruebas.py -> acronimos_js()  -> app/main.py
      -> <script id="cuenta-resultado-acronimos"> -> CUENTA_RESULTADO_ACRONIMOS
      -> acronimoResultado(c) -> <th> de la tabla
    app/core/resultado_pruebas.py -> info_resultado() -> render_badge_resultado()
      -> badge de la tarjeta del Kanban
    app/api/v1/metricas.py -> ACRONIMOS_RESULTADO -> badge del modal de drill-down

================================================================================
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  7.1 PUBLICACION

    a) Publicar el commit en las dos ramas, sin reescribir historia:

         git push origin <commit>:main
         git push origin <commit>:release/v2.001

       (push fast-forward; nunca usar '--force').

    b) Desplegar explicitamente 'worker' y 'beat' con el MISMO commit
       (no tienen autoDeploy):

         python tmp_deploy_railway.py <commit> worker
         python tmp_deploy_railway.py <commit> beat

    c) Confirmar que los tres servicios quedaron en el mismo commit:

         python tmp_deploy_railway.py --estado

    d) Verificacion de salud tras el despliegue:

         GET /health   -> 200  (db ok, redis ok)
         GET /ready    -> 200
         GET /info     -> 200
         POST /api/v1/auth/login (admin) -> 200
         GET /dashboard -> 200

    e) Verificacion funcional: hacer los pasos 5.1 y 5.2 contra el
       servicio desplegado.

  7.2 ROLLBACK

    Commit de referencia: el anterior (e7806da), que es el arbol del lote
    V2.004 y el arbol estable anterior a este cambio.

    Rollback en git (sin reescribir historia):

         git revert <commit de V2.005>
         git push origin main
         y desplegar worker y beat con ese commit

    Rollback en Railway (desplegar el commit anterior en los tres
    servicios):

         python tmp_deploy_railway.py <commit-anterior> web
         python tmp_deploy_railway.py <commit-anterior> worker
         python tmp_deploy_railway.py <commit-anterior> beat

    Nota: el 'web' se redespliega solo por autoDeploy al hacer push a
    'main'. Si se cambia el arbol de 'main', hay que desplegar a mano
    'worker' y 'beat' con el mismo commit para no desalinear los tres
    servicios.

    Efecto del rollback: los titulos de las columnas volverian a decir
    "NOOK" (y el badge de las tarjetas, "NOOK"). No se pierde ningun dato
    y no cambia ningun numero: el rollback solo restaura el texto
    anterior.

    ALTERNATIVA MAS SIMPLE, si solo se quiere el texto: cambiar el
    literal del catalogo a "NOOK" y volver a desplegar. Es el mismo
    efecto, pero deja un commit de correccion en la historia.

================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

  El diff que sigue es el EXACTO de los ficheros de codigo modificados.
  Va TRANSLITERADO a ASCII: los caracteres acentuados del codigo original
  ('a' con tilde, 'i' con tilde, etc.) se han sustituido por su equivalente
  ASCII. ESTA TRANSLITERACION ES SOLO DOCUMENTAL: el codigo del proyecto NO
  se modifica, conserva sus caracteres originales en UTF-8.
diff --git a/app/core/resultado_pruebas.py b/app/core/resultado_pruebas.py
index 0a65dda..6818ba9 100644
--- a/app/core/resultado_pruebas.py
+++ b/app/core/resultado_pruebas.py
@@ -35,20 +35,35 @@ Ambos caminos consumen, por construccion, la misma paleta.
 
 Acronimos (mapeo 1:1 con las 6 categorias solicitadas)
 -------------------------------------------------------
-===================  =========  =========================
-Valor del LOV        Acronimo   Categoria solicitada
-===================  =========  =========================
-``OK``               ``OK``     OK
-``N/A``              ``N/A``    N/A
-``OK CON OBS.``      ``OBS``    OBS
-``POSTERGADA``       ``POST``   POST
-``DESESTIMADA``      ``NOOK``   NOOK
-``NOK``              ``NOK``    NOK
-===================  =========  =========================
+===================  ===========  =========================
+Valor del LOV        Acronimo     Categoria solicitada
+===================  ===========  =========================
+``OK``               ``OK``       OK
+``N/A``              ``N/A``      N/A
+``OK CON OBS.``      ``OBS``      OBS
+``POSTERGADA``       ``POST``     POST
+``DESESTIMADA``      ``DESEST``   DESEST
+``NOK``              ``NOK``      NOK
+===================  ===========  =========================
 
 ``(en blanco)`` es la pseudo-columna que agrupa tickets con
 ``resultado_pruebas`` NULL o vacio en la tabla pivote del dashboard; su
 acronimo es ``S/D`` (sin dato).
+
+Por que la columna DESESTIMADA se titula ``DESEST`` (V2.005)
+------------------------------------------------------------
+La columna de casos **DESESTIMADA** se titulaba ``NOOK``, nombre heredado
+de la hoja UAT. Ese titulo se confundia con el resultado ``NOK`` (no
+conforme), que es una categoria **distinta** y sigue mostrando su propio
+acronimo ``NOK`` y su propio color (rojo). El acronimo ``DESEST`` deja
+la columna inequivoca: el titulo sigue siendo corto, pero ya no puede
+leerse como ``NOK``.
+
+El cambio es **solo de presentacion**: no se toca el valor del LOV
+(``DESESTIMADA``), ni la clave de la paleta, ni el nombre de la columna
+en el pivote, ni los parametros del drill-down. Por construccion, el
+titulo de la columna y el badge de la tarjeta del Kanban muestran el
+mismo acronimo.
 """
 
 from __future__ import annotations
@@ -114,7 +129,7 @@ ACRONIMOS: Dict[str, str] = {
     "N/A": "N/A",
     "OK CON OBS.": "OBS",
     "POSTERGADA": "POST",
-    "DESESTIMADA": "NOOK",
+    "DESESTIMADA": "DESEST",
     "NOK": "NOK",
     SIN_RESULTADO: "S/D",
 }
diff --git a/app/templates/dashboard/index.html b/app/templates/dashboard/index.html
index 8dd35fb..fd31fd4 100644
--- a/app/templates/dashboard/index.html
+++ b/app/templates/dashboard/index.html
@@ -1355,7 +1355,7 @@
   })();
 
   // Acronimos del LOV: "OK"->OK, "N/A"->N/A, "OK CON OBS."->OBS,
-  // "POSTERGADA"->POST, "DESESTIMADA"->NOOK, "NOK"->NOK, "(en blanco)"->S/D.
+  // "POSTERGADA"->POST, "DESESTIMADA"->DESEST, "NOK"->NOK, "(en blanco)"->S/D.
   const CUENTA_RESULTADO_ACRONIMOS = (function () {
     const el = document.getElementById('cuenta-resultado-acronimos');
     if (!el) return {};
@@ -1447,7 +1447,7 @@
 
     // === Encabezado ===
     // El titulo de cada columna es el ACRONIMO del valor del LOV
-    // (OBS, POST, NOOK, ...) y el color de fondo es el MISMO que el del
+    // (OBS, POST, DESEST, ...) y el color de fondo es el MISMO que el del
     // badge de la tarjeta del Kanban. El texto completo del valor queda
     // en el tooltip (title) para no perder informacion.
     thead.innerHTML = '<tr class="bg-slate-800 text-white">' +
diff --git a/docs/QA_REPORT_RESULTADO_PRUEBAS.md b/docs/QA_REPORT_RESULTADO_PRUEBAS.md
index 983b6ed..67e81da 100644
--- a/docs/QA_REPORT_RESULTADO_PRUEBAS.md
+++ b/docs/QA_REPORT_RESULTADO_PRUEBAS.md
@@ -77,10 +77,10 @@ El analisis estatico se valido ejecutando el script real del dashboard en un
 - **Fase 1 -- evaluacion del script:** OK, sin excepcion.
 - **Fase 2 -- despacho de `DOMContentLoaded`:** OK, 1 handler ejecutado sin excepcion.
 - `CUENTA_RESULTADO_COLORES` y `CUENTA_RESULTADO_ACRONIMOS` quedan **poblados** desde el JSON inyectado por el server (`vacio: false`, 7 claves cada uno).
-- `acronimoResultado()` devuelve `OK`->`OK`, `N/A`->`N/A`, `OK CON OBS.`->`OBS`, `POSTERGADA`->`POST`, `DESESTIMADA`->`NOOK`, `NOK`->`NOK`, `(en blanco)`->`S/D`, y hace *fallback* al valor crudo para entradas desconocidas.
+- `acronimoResultado()` devuelve `OK`->`OK`, `N/A`->`N/A`, `OK CON OBS.`->`OBS`, `POSTERGADA`->`POST`, `DESESTIMADA`->`DESEST`, `NOK`->`NOK`, `(en blanco)`->`S/D`, y hace *fallback* al valor crudo para entradas desconocidas.
 - `_escapeHtml()` escapa correctamente (`<script>` -> `&lt;script&gt;`, `&` -> `&amp;`).
 - `RESULTADO_COLORES` **no existe** en runtime; `renderCuentaResultado` si es funcion y no lanza.
-- El `<thead>` renderizado muestra los acronimos `N/A, NOK, OK, OBS, POST, NOOK, S/D` con los colores canonicos (`#94a3b8, #dc2626, #16a34a, #eab308, #ea580c, #7c3aed, #cbd5e1`) y los `title` con el valor largo (`'OK CON OBS.'`), confirmando que el encabezado de columnas cambio de valor largo a acronimo.
+- El `<thead>` renderizado muestra los acronimos `N/A, NOK, OK, OBS, POST, DESEST, S/D` con los colores canonicos (`#94a3b8, #dc2626, #16a34a, #eab308, #ea580c, #7c3aed, #cbd5e1`) y los `title` con el valor largo (`'OK CON OBS.'`), confirmando que el encabezado de columnas cambio de valor largo a acronimo.
 
 > **Nota (artefacto del harness, no defecto de la app):** durante la fase 2 se registra `TypeError: Cannot read properties of undefined (reading 'total')` en `render()`. Proviene del *mock* de `fetch` del harness, que devuelve `{}` para `/api/v1/metricas/dashboard-completo` (el unico endpoint mockeado es `/api/v1/metricas/cuenta-resultado`); el acceso es `d.totales.total` sobre `d = {}`. Es una limitacion del stub, ajena al codigo modificado, y la propia app lo captura en su `try/catch` alrededor de `render()`.
 
@@ -201,7 +201,7 @@ Renderizando `kanban/partials/tarjeta.html` con el entorno real y un ticket por
 | `OK` | `#16a34a` | `#ffffff` | `OK` | OK |
 | `OK CON OBS.` | `#eab308` | `#1f2937` | `OBS` | OK |
 | `POSTERGADA` | `#ea580c` | `#ffffff` | `POST` | OK |
-| `DESESTIMADA` | `#7c3aed` | `#ffffff` | `NOOK` | OK |
+| `DESESTIMADA` | `#7c3aed` | `#ffffff` | `DESEST` | OK |
 | `(en blanco)` | `#cbd5e1` | `#475569` | `S/D` | OK |
 
 Los valores vacios (`None` / `''`) caen en `(en blanco)` con acronimo `S/D`; un valor fuera del LOV se muestra en estilo neutro (`#e2e8f0`) con el texto crudo truncado; y para un tipo de ticket no aplicable (`solicitud`) con resultado vacio **no se emite badge**. La paleta del badge es identica a la inyectada al dashboard.
diff --git a/docs/onboarding-demo/imgs/resultado-pruebas.svg b/docs/onboarding-demo/imgs/resultado-pruebas.svg
index caddb38..7e1c651 100644
--- a/docs/onboarding-demo/imgs/resultado-pruebas.svg
+++ b/docs/onboarding-demo/imgs/resultado-pruebas.svg
@@ -57,7 +57,7 @@
     <!-- columna 2 -->
     <g transform="translate(506,158)">
       <rect x="0" y="-14" width="48" height="24" rx="12" fill="#7c3aed"/>
-      <text x="24" y="4" font-family="system-ui, sans-serif" font-size="12.5" font-weight="700" text-anchor="middle" fill="#ffffff">NOOK</text>
+      <text x="24" y="4" font-family="system-ui, sans-serif" font-size="10.5" font-weight="700" text-anchor="middle" fill="#ffffff">DESEST</text>
       <text x="58" y="4" font-family="system-ui, sans-serif" font-size="11.5" fill="#1e293b">Desestimada</text>
     </g>
     <g transform="translate(506,208)">
diff --git a/docs/onboarding-demo/index.html b/docs/onboarding-demo/index.html
index 588da54..efd7690 100644
--- a/docs/onboarding-demo/index.html
+++ b/docs/onboarding-demo/index.html
@@ -515,7 +515,7 @@
             </tr>
             <tr>
               <td><code>DESESTIMADA</code></td>
-              <td><strong>NOOK</strong></td>
+              <td><strong>DESEST</strong></td>
               <td><span style="display:inline-block;width:14px;height:14px;border-radius:4px;background:#7c3aed;vertical-align:-2px;"></span> <code>#7c3aed</code></td>
               <td>La prueba fue desestimada.</td>
             </tr>
@@ -1295,7 +1295,7 @@ GAR_SIN-00042    <- el caso no traia codigo: se genero uno</pre>
       </p>
       <ul>
         <li><strong>Etiqueta de fila:</strong> una por <strong>modulo</strong> (Auditoria, GAR, Validacion...). Los tickets sin modulo se agrupan bajo "(en blanco)".</li>
-        <li><strong>Columnas:</strong> una por categoria del LOV. El encabezado muestra el <strong>acronimo</strong> (OK, N/A, OBS, POST, NOOK, NOK, S/D) con el <strong>color del catalogo</strong> de fondo; al pasar el cursor aparece el valor completo.</li>
+        <li><strong>Columnas:</strong> una por categoria del LOV. El encabezado muestra el <strong>acronimo</strong> (OK, N/A, OBS, POST, DESEST, NOK, S/D) con el <strong>color del catalogo</strong> de fondo; al pasar el cursor aparece el valor completo.</li>
         <li><strong>Total general:</strong> ultima columna, con la suma de todos los resultados de esa fila.</li>
         <li><strong>Totales por columna:</strong> el pie de la tabla resume el total de cada categoria y el total general del reporte.</li>
       </ul>
@@ -1308,7 +1308,7 @@ GAR_SIN-00042    <- el caso no traia codigo: se genero uno</pre>
         <strong>Un solo catalogo, un solo color:</strong> la tabla del Dashboard y el indicador de la
         tarjeta se alimentan del mismo catalogo, de modo que <strong>un resultado nunca puede verse
         con dos colores distintos</strong>. Por ejemplo, <code>OK CON OBS.</code> es siempre
-        <strong>OBS</strong> en ambar, y <code>DESESTIMADA</code> es siempre <strong>NOOK</strong> en
+        <strong>OBS</strong> en ambar, y <code>DESESTIMADA</code> es siempre <strong>DESEST</strong> en
         violeta.
       </div>
       <div class="warn">
@@ -1509,7 +1509,7 @@ GAR_SIN-00042    <- el caso no traia codigo: se genero uno</pre>
             <tr><td><strong>Prioridad</strong></td><td>Urgencia del ticket (Critica / Alta / Media / Baja).</td></tr>
             <tr><td><strong>SLA</strong></td><td>Service Level Agreement -- tiempo objetivo de resolucion. Si vence, el indicador se pone rojo.</td></tr>
             <tr><td><strong>Resultado de pruebas</strong></td><td>Categoria de la lista de valores (LOV) registrada en un ticket: <code>OK</code>, <code>N/A</code>, <code>OK CON OBS.</code>, <code>POSTERGADA</code>, <code>DESESTIMADA</code> o <code>NOK</code>.</td></tr>
-            <tr><td><strong>Indicador de Resultado de Pruebas</strong></td><td>Etiqueta de color en la zona inferior de la tarjeta que muestra el acronimo del resultado: OK, N/A, OBS, POST, NOOK, NOK o S/D (sin dato).</td></tr>
+            <tr><td><strong>Indicador de Resultado de Pruebas</strong></td><td>Etiqueta de color en la zona inferior de la tarjeta que muestra el acronimo del resultado: OK, N/A, OBS, POST, DESEST, NOK o S/D (sin dato).</td></tr>
             <tr><td><strong>Cuenta de Resultado</strong></td><td>Tabla del Dashboard que resume los resultados de pruebas por modulo, con los mismos acronimos y colores que las tarjetas.</td></tr>
             <tr><td><strong>Asignado</strong></td><td>Agente responsable de resolver el ticket.</td></tr>
             <tr><td><strong>Solicitante</strong></td><td>Quien reporta la incidencia.</td></tr>
diff --git a/tests/test_v2005_acronimo_desest.py b/tests/test_v2005_acronimo_desest.py
new file mode 100644
index 0000000..c0afd0b
--- /dev/null
+++ b/tests/test_v2005_acronimo_desest.py
@@ -0,0 +1,298 @@
+"""
+Regresiones de V2.005: la columna de casos DESESTIMADA se titula "DESEST".
+
+Contexto del defecto
+--------------------
+En la seccion "Cuenta de Resultado" del Dashboard, el encabezado de la
+columna de casos **DESESTIMADA** se titulaba ``NOOK`` (nombre heredado de
+la hoja UAT). Ese titulo se confundia con el resultado ``NOK`` (no
+conforme), que es una categoria **distinta** del LOV y que sigue
+mostrando su propio acronimo ``NOK`` y su propio color (rojo).
+
+Causa raiz
+----------
+El titulo de cada columna de la tabla es el ACRONIMO del valor del LOV, y
+ese acronimo lo define el catalogo `app/core/resultado_pruebas.py`
+(``ACRONIMOS``), donde el valor para ``"DESESTIMADA"`` era ``"NOOK"``.
+La plantilla del dashboard NO redeclara el mapa: lo lee del JSON que
+inyecta el servidor, de modo que el titulo se corregia en un unico sitio.
+
+Alcance del lote
+----------------
+Es un cambio EXCLUSIVAMENTE de presentacion. No se modifica:
+
+  * el valor del LOV (``DESESTIMADA``),
+  * la clave de la paleta ni sus colores (violeta ``#7c3aed``),
+  * el nombre de la columna en el pivote ni en el drill-down (sigue siendo
+    el valor del LOV, que es lo que viaja en el parametro ``resultado``),
+  * ningun dato, ni la numeracion de tickets, ni el motor de busqueda.
+
+Todos los tests operan sobre la base SQLite temporal de la suite (ver
+``tests/conftest.py``): nunca leen ni escriben en la base de datos de
+produccion.
+"""
+from __future__ import annotations
+
+import json
+import re
+from pathlib import Path
+
+import pytest
+from fastapi.testclient import TestClient
+
+RAIZ = Path(__file__).resolve().parent.parent
+PLANTILLA_DASHBOARD = RAIZ / "app" / "templates" / "dashboard" / "index.html"
+FUENTE_METRICAS = RAIZ / "app" / "api" / "v1" / "metricas.py"
+
+CLAVE = "Clave-local-de-regresion-2026"
+
+#: Valor del LOV (NO cambia en este lote).
+VALOR_LOV = "DESESTIMADA"
+#: Acronimo vigente del valor del LOV.
+ACRONIMO_NUEVO = "DESEST"
+#: Acronimo heredado que ya no debe aparecer por ningun lado.
+ACRONIMO_VIEJO = "NOOK"
+
+#: Color canonico de la categoria DESESTIMADA (violeta). No debe cambiar.
+COLOR_DESESTIMADA = {
+    "bg": "#7c3aed",
+    "text": "#ffffff",
+    "cellText": "#1f2937",
+}
+
+
+# ---------------------------------------------------------------------------
+# Utilidades compartidas
+# ---------------------------------------------------------------------------
+@pytest.fixture(scope="module")
+def app_and_schema():
+    """Prepara el esquema en la SQLite temporal de la suite."""
+    from app.db.base import Base
+    from app.db.session import engine
+    from app.main import app
+
+    Base.metadata.create_all(bind=engine)
+    return app, engine
+
+
+@pytest.fixture(scope="module")
+def local_client(app_and_schema):
+    """Cliente HTTP local con sesion; no abre conexiones de red."""
+    app, _engine = app_and_schema
+    with TestClient(app) as client:
+        yield client
+
+
+@pytest.fixture
+def db_session(app_and_schema):
+    """Sesion SQLAlchemy sobre la SQLite temporal de la suite."""
+    from app.db.session import SessionLocal
+
+    session = SessionLocal()
+    try:
+        yield session
+    finally:
+        session.close()
+
+
+@pytest.fixture
+def admin_con_sesion(local_client, db_session):
+    """Administrador autenticado en el cliente HTTP local."""
+    from app.core.security import hash_password
+    from app.models.usuario import RolUsuario, Usuario
+
+    username = "v2005_admin_desest"
+    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
+    if usuario is None:
+        usuario = Usuario(
+            username=username,
+            email=f"{username}@example.test",
+            nombre_completo="Admin V2005",
+            hashed_password=hash_password(CLAVE),
+            rol=RolUsuario.ADMINISTRADOR,
+            is_active=True,
+        )
+        db_session.add(usuario)
+        db_session.commit()
+        db_session.refresh(usuario)
+
+    login = local_client.post(
+        "/api/v1/auth/login",
+        json={"username": username, "password": CLAVE},
+    )
+    assert login.status_code == 200, login.text
+    return usuario
+
+
+def _texto_plantilla():
+    return PLANTILLA_DASHBOARD.read_text(encoding="utf-8")
+
+
+def _json_inyectado(html: str, element_id: str):
+    """Extrae el JSON que el servidor inyecta en un <script> de la plantilla."""
+    patron = (
+        r'<script id="%s" type="application/json">(.*?)</script>' % re.escape(element_id)
+    )
+    m = re.search(patron, html, re.S)
+    assert m, "No se encontro el bloque <script id=%r> en la plantilla" % element_id
+    return json.loads(m.group(1).strip())
+
+
+def _acronimo_de_la_plantilla(mapa: dict, columna: str) -> str:
+    """Replica exacta de ``acronimoResultado()`` de la plantilla.
+
+    La funcion real es ``CUENTA_RESULTADO_ACRONIMOS[c] || c``: el acronimo
+    del catalogo y, si no existe, el propio texto de la columna.
+    """
+    return mapa.get(columna) or columna
+
+
+# ---------------------------------------------------------------------------
+# 1. El catalogo (fuente unica de verdad)
+# ---------------------------------------------------------------------------
+def test_el_catalogo_titula_desestimada_como_desest():
+    """``ACRONIMOS["DESESTIMADA"]`` debe ser ``"DESEST"``."""
+    from app.core.resultado_pruebas import ACRONIMOS
+
+    assert ACRONIMOS[VALOR_LOV] == ACRONIMO_NUEVO
+
+
+def test_ningun_valor_del_catalogo_usa_el_acronimo_heredado():
+    """El acronimo ``NOOK`` no debe quedar como clave ni como valor."""
+    from app.core.resultado_pruebas import ACRONIMOS
+
+    assert ACRONIMO_VIEJO not in ACRONIMOS
+    assert ACRONIMO_VIEJO not in set(ACRONIMOS.values())
+    # Y el resto de categorias conservan su acronimo (no hay colisiones).
+    assert ACRONIMOS["NOK"] == "NOK"
+    assert ACRONIMOS["OK"] == "OK"
+    assert ACRONIMOS["N/A"] == "N/A"
+    assert ACRONIMOS["OK CON OBS."] == "OBS"
+    assert ACRONIMOS["POSTERGADA"] == "POST"
+    assert ACRONIMOS["(en blanco)"] == "S/D"
+
+
+def test_la_paleta_de_desestimada_no_cambia():
+    """El cambio es de presentacion: ni la clave ni los colores cambian."""
+    from app.core.resultado_pruebas import COLORES
+
+    assert COLORES[VALOR_LOV] == COLOR_DESESTIMADA
+
+
+def test_el_valor_del_lov_no_cambia():
+    """La columna del pivote se sigue llamando ``DESESTIMADA``."""
+    from app.core.resultado_pruebas import (
+        RESULTADOS_LOV,
+        RESULTADOS_LOV_FORMULARIO,
+        lov_js,
+    )
+
+    assert VALOR_LOV in RESULTADOS_LOV
+    assert VALOR_LOV in RESULTADOS_LOV_FORMULARIO
+    assert ACRONIMO_VIEJO not in RESULTADOS_LOV
+    assert lov_js() == list(RESULTADOS_LOV) + ["(en blanco)"]
+
+
+# ---------------------------------------------------------------------------
+# 2. La ficha y el badge (lo que ve el usuario en la tarjeta del Kanban)
+# ---------------------------------------------------------------------------
+def test_la_ficha_del_resultado_usa_el_acronimo_nuevo():
+    """``info_resultado()`` devuelve el valor del LOV y el acronimo nuevo."""
+    from app.core.resultado_pruebas import info_resultado
+
+    ficha = info_resultado(VALOR_LOV)
+    assert ficha is not None
+    assert ficha["valor"] == VALOR_LOV
+    assert ficha["acronimo"] == ACRONIMO_NUEVO
+    assert ficha["bg"] == COLOR_DESESTIMADA["bg"]
+    assert ficha["text"] == COLOR_DESESTIMADA["text"]
+
+
+def test_el_badge_de_la_tarjeta_muestra_desest_y_conserva_el_color():
+    """El badge muestra ``DESEST`` y conserva el violeta y el valor LOV."""
+    from app.core.resultado_pruebas import (
+        info_resultado,
+        render_badge_resultado,
+    )
+
+    html = render_badge_resultado(info_resultado(VALOR_LOV))
+    assert "DESEST" in html
+    assert "NOOK" not in html
+    assert 'data-resultado-pruebas="DESESTIMADA"' in html
+    assert COLOR_DESESTIMADA["bg"] in html
+
+
+# ---------------------------------------------------------------------------
+# 3. La plantilla del dashboard
+# ---------------------------------------------------------------------------
+def test_la_plantilla_no_hardcodea_el_acronimo_heredado():
+    """Ni en codigo ni en comentarios debe quedar la cadena ``NOOK``."""
+    texto = _texto_plantilla()
+
+    assert ACRONIMO_VIEJO not in texto
+
+
+def test_la_plantilla_toma_el_titulo_del_json_inyectado():
+    """El JS debe leer los acronimos del JSON del servidor, no redeclararlos."""
+    texto = _texto_plantilla()
+
+    assert "CUENTA_RESULTADO_ACRONIMOS" in texto
+    assert "cuenta-resultado-acronimos" in texto
+    # El titulo de la columna se calcula con el mapa inyectado...
+    assert "acronimoResultado(c)" in texto
+    # ...y no con un literal escrito a mano en la plantilla.
+    assert '"DESESTIMADA": "NOOK"' not in texto
+    assert "'DESESTIMADA': 'NOOK'" not in texto
+
+
+def test_el_drilldown_conserva_el_valor_del_lov():
+    """El drill-down sigue filtrando por ``DESESTIMADA`` (valor del LOV).
+
+    El acronimo es solo de presentacion: el parametro ``resultado`` del
+    endpoint de detalle debe seguir llevando el valor del LOV, porque es
+    lo que el backend sabe filtrar.
+    """
+    texto = _texto_plantilla()
+    fuente = FUENTE_METRICAS.read_text(encoding="utf-8")
+
+    # El JS construye la URL con la CLAVE de la columna (``c``), no con el
+    # acronimo (``acro``).
+    assert "'&resultado=' + encodeURIComponent(c)" in texto
+    # Y el backend filtra por el valor del LOV.
+    assert 'resultado_norm.in_(["DESESTIMADA", "DESESTIMADO"])' in fuente
+
+
+# ---------------------------------------------------------------------------
+# 4. Extremo a extremo: el HTML que sirve el servidor
+# ---------------------------------------------------------------------------
+def test_el_dashboard_inyecta_el_acronimo_nuevo(local_client, admin_con_sesion):
+    """GET /dashboard sirve el JSON con ``DESESTIMADA`` -> ``DESEST``."""
+    r = local_client.get("/dashboard")
+    assert r.status_code == 200, r.text
+    html = r.text
+
+    acronimos = _json_inyectado(html, "cuenta-resultado-acronimos")
+    assert acronimos[VALOR_LOV] == ACRONIMO_NUEVO
+    assert ACRONIMO_VIEJO not in acronimos
+    assert ACRONIMO_VIEJO not in set(acronimos.values())
+    # El HTML servido no debe contener el acronimo heredado.
+    assert ACRONIMO_VIEJO not in html
+
+    # Y el titulo que el JS va a pintar para esa columna es "DESEST".
+    assert _acronimo_de_la_plantilla(acronimos, VALOR_LOV) == ACRONIMO_NUEVO
+
+
+def test_el_dashboard_sigue_inyectando_la_paleta_y_el_lov(
+    local_client, admin_con_sesion
+):
+    """La paleta y la lista de columnas no se tocan con el renombrado."""
+    r = local_client.get("/dashboard")
+    assert r.status_code == 200, r.text
+    html = r.text
+
+    colores = _json_inyectado(html, "cuenta-resultado-paleta")
+    lov = _json_inyectado(html, "cuenta-resultado-lov")
+
+    assert colores[VALOR_LOV] == COLOR_DESESTIMADA
+    assert VALOR_LOV in lov
+    assert ACRONIMO_VIEJO not in lov
================================================================================
9. ESTADO FINAL DEL DESPLIEGUE (2026-10-29)
================================================================================

  9.1 PUBLICACION

    Commit del lote:  1b49fe088dce8ad05731f7a18c38ac6032782c9e
    Commit padre:     e7806da (addendum 9 del lote V2.004)
    Rama de trabajo:  release/v2.001 (rama canonica)
    'main' alineada:  merge --ff-only (e7806da..1b49fe0), sin reescribir
                      historia y sin '--force'.
    Push (PUSH_EXIT=0):
        e7806da..1b49fe0  main            -> main
        e7806da..1b49fe0  release/v2.001  -> release/v2.001
        release/v1.006 sin cambios (ya estaba en 4d1a603).

  9.2 DESPLIEGUE EN RAILWAY

    web    -> autoDeploy desde 'main'   SUCCESS  2026-10-29T13:04:32.885Z
              id 1e64d681-670b-44ce-a810-68039bae8ccf
    worker -> serviceInstanceDeploy      SUCCESS  2026-10-29T13:04:50.963Z
              id 237fdfb7-39c4-4796-911a-98a441d0c2a1
    beat   -> serviceInstanceDeploy      SUCCESS  2026-10-29T13:04:54.999Z
              id a3942ec0-c1f5-43de-8031-1805d639f23d

    Los tres servicios declaran en su 'meta':
        commitHash   = 1b49fe088dce8ad05731f7a18c38ac6032782c9e
        branch       = main
        commitMessage= feat(dashboard): la columna de casos DESESTIMADA se
                       titula DESEST

  9.3 PRUEBAS

    Suite nueva V2.005:                 11 passed
    Suite completa:                    195 passed (184 + 11), 0 failed
                                       714,99 s
    Dientes de la suite: revirtiendo el acronimo a "NOOK" en el catalogo,
    la suite V2.005 pasa a 5 failed de 11 (catalogo, ausencia de "NOOK",
    ficha del resultado, badge de la tarjeta y dashboard extremo a extremo);
    restaurado el acronimo, vuelve a 11 passed.

  9.4 VERIFICACION EN PRODUCCION (solo GET y POST de login)

    Salud y acceso:
      GET  /health -> 200  {"status":"ok","database":"ok","redis":"ok"}
      GET  /ready  -> 200
      GET  /info   -> 200
      POST /api/v1/auth/login (administrador) -> 200
      GET  /dashboard -> 200, 140.690 caracteres


    Acronimos inyectados en la plantilla (bloque id="cuenta-resultado-acronimos"):
      {"(en blanco)":"S/D","DESESTIMADA":"DESEST","N/A":"N/A",
       "NOK":"NOK","OK":"OK","OK CON OBS.":"OBS",
       "POSTERGADA":"POST"}
      -> "DESESTIMADA" se titula "DESEST"        [OK]
      -> no queda "NOOK" en el mapa de acronimos   [OK]
      -> ningun acronimo vale "NOOK"               [OK]
      -> la categoria "NOK" conserva su acronimo   [OK]
      -> el HTML servido (140.690 caracteres) NO contiene la cadena
         "NOOK" en ningun punto                    [OK]
      -> el LOV inyectado sigue siendo
         ["N/A","NOK","OK","OK CON OBS.","POSTERGADA",
          "DESESTIMADA","(en blanco)"]            [OK]


    Pivote (GET /api/v1/metricas/cuenta-resultado, ambiente QA):
      columnas            = ["N/A","NOK","OK","OK CON OBS.",
                             "POSTERGADA","DESESTIMADA","(en blanco)"]
      totales_por_columna = {"N/A":128,"NOK":4,"OK":701,"OK CON OBS.":4,
                              "POSTERGADA":54,"DESESTIMADA":21,
                              "(en blanco)":0}
      total_general        = 912
      -> la forma y los numeros son IDENTICOS a los medidos antes del
         despliegue (misma medicion previa, 2026-10-29)   [OK]
      -> la columna DESESTIMADA sigue con sus 21 tickets   [OK]


    Drill-down (GET /api/v1/metricas/cuenta-resultado/detalle
                ?modulo=(en blanco)&resultado=DESESTIMADA&ambiente=QA):
      -> 200, 3.611 caracteres                          [OK]
      -> el modal del drill-down muestra el acronimo
         "DESEST"                                       [OK]
      -> el parametro sigue siendo el VALOR del LOV
         ("DESESTIMADA"), no el acronimo                [OK]


    Valores reales de resultado_pruebas (GET /api/v1/tickets, 933 tickets):
      'OK' 716 | 'N/A' 130 | 'POSTERGADA' 54 | 'DESESTIMADA' 21 |
      'NOK' 6 | 'OK CON OBS.' 4 | '' 2
      -> valores fuera del LOV: ninguno                 [OK]
      -> ningun ticket con resultado crudo "NOOK"       [OK]


    RESULTADO DE LA VERIFICACION: TODAS LAS COMPROBACIONES OK.
    Script de verificacion con 16 comprobaciones automaticas: 0 fallos.

  9.5 RESUMEN OPERATIVO

    El cambio estaba desplegado y verificado en los tres servicios con el
    mismo commit (1b49fe0). La columna de casos desestimados se titula
    "DESEST" en el encabezado de la tabla "Cuenta de Resultado", el badge
    de las tarjetas del Kanban dice "DESEST" en violeta y el modal de
    drill-down muestra "DESEST". No ha cambiado ningun numero del
    reporte, ningun dato, ni el nombre interno de la columna
    (DESESTIMADA), ni el parametro del drill-down.

