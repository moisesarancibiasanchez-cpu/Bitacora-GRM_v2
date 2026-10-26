================================================================================
README V2.002 - CONSISTENCIA DEL MODAL DE KPI CON EL RESUMEN DE INCIDENCIAS
Proyecto: Bitacora GRM v2
Fecha: 2026-10-26
Rama base: release/v2.001 (commit 63d1f86)
Estado: CODIGO LISTO Y VERIFICADO EN LOCAL. PENDIENTE DE DESPLEGUE.
================================================================================

0. PARCHE EXACTO

  Ficheros intervenidos:
    - app/api/v1/metricas.py
    - app/templates/dashboard/index.html
    - tests/test_v2002_consistencia_kpi.py (nuevo)

  Funciones intervenidas (backend, app/api/v1/metricas.py):
    - _resolver_rango_temporal()        [NUEVA]
    - incidencias_recientes()           [rango resuelto por el helper]
    - _KPI_DETALLE                      [los 7 filtros reciben 'ahora']
    - detalle_kpi()                     [rango explicito, outerjoin, total real]

  Funciones intervenidas (front, app/templates/dashboard/index.html):
    - _resolver_rango_temporal()        -> _filtrosIncidenciasRecientes() [NUEVA]
    - cargarIncidenciasRecientes()
    - abrirModalKpiDetalle()
    - _renderModalKpiDetalle()
    - _kpiRangoTexto()                  [NUEVA]
    - aplicarBloqueFechas()
    - aplicarFechasManuales()           [NUEVA]
    - exportarIncidenciasRecientes()

  El diff completo esta al final de este documento, en el APENDICE A.

================================================================================
1. BASE
================================================================================

  Base de este cambio: el commit 63d1f86 de la rama 'release/v2.001', que a
  su vez contiene V1.005, V1.006 y V2.001.

  Lo que estaba EN PRODUCCION al abrir este lote: el commit 6038fc29 del
  viernes 2026-10-23 (18:58 hora de Chile), desplegado en los tres
  servicios (web, worker y beat). Esa es la version que reproduce el
  defecto, y es la que hay que volver a medir tras el despliegue.

  Contexto del defecto reportado por el propietario (dashboard, seccion
  "Lista de Incidencias Recientes"):

    - La franja de KPI mostraba "2026-07-28 -> 2026-10-26 . 18 TICKETS" y
      la casilla "TOTAL PERIODO" mostraba 18.
    - Al hacer clic en esa casilla, el modal "Total periodo" mostraba
      "Periodo: 30 dias . Tipo: incidencia . Total: 2 tickets" y listaba
      solo 2 tickets (INC-939 e INC-938).
    - El propietario advierte que la inconsistencia afecta a todo el
      bloque de reporte, no solo a la casilla "Total periodo".

  Medicion contra produccion (2026-10-26, con la version del viernes):

    GET /api/v1/metricas/incidencias-recientes
        ?tipo=incidencia&periodo_dias=30
        &fecha_desde=2026-07-28&fecha_hasta=2026-10-26&limite=200
      -> metricas.total_periodo = 18   (18 tickets devueltos)

    GET /api/v1/metricas/detalle-kpi
        ?kpi=total_periodo&periodo_dias=30&tipo=incidencia&limite=200
      -> total = 2   (INC-939, INC-938)

    Conteo por ventana, mismo tipo:
      7 dias  -> 0
      30 dias -> 2
      60 dias -> 18
      90 dias -> 18

  Los 16 tickets que faltaban en el modal estaban creados entre los 30 y
  los 60 dias. El modal no estaba "contando mal": estaba contando OTRA
  ventana.

================================================================================
2. CAMBIO UNICO
================================================================================

  Que el modal de drill-down de la seccion "Lista de Incidencias Recientes"
  muestre EXACTAMENTE los mismos tickets que la cifra de la casilla KPI de
  la que se parte. En otras palabras: para los mismos filtros, el resumen,
  el modal y el conteo real en la base tienen que devolver la MISMA cifra.

  CAUSA RAIZ (dos, una en cada capa):

  (a) BACKEND. El endpoint "/api/v1/metricas/detalle-kpi" solo aceptaba el
      parametro 'periodo_dias'. Ignoraba 'fecha_desde' y 'fecha_hasta', que
      son precisamente los parametros que el resumen usa CON PRECEDENCIA
      cuando el operador elige un rango explicito de fechas. Ademas no
      acotaba la fecha superior (no tenia cota de "created_at <= ...") y
      reportaba 'total' como el numero de filas devueltas (truncado por
      'limite'), no el total real del KPI.

  (b) FRONT. Al abrir el modal, el JS tomaba el periodo del selector GLOBAL
      '#periodo' (30 dias por defecto) en vez del bloque rapido de la
      seccion, y leia un id de selector de tipo inexistente
      ('incidencias-tipo' en vez de 'incidencias-recientes-tipo'), de modo
      que el tipo siempre caia en 'incidencia' y el rango explicito nunca
      llegaba al backend.

  QUE SE HIZO:

  Backend (app/api/v1/metricas.py):
    - Nuevo helper '_resolver_rango_temporal()' como fuente UNICA del
      rango. Regla de precedencia: si llega 'fecha_desde' o 'fecha_hasta',
      ese rango manda sobre la ventana de 'periodo_dias'; 'fecha_hasta' es
      inclusivo contra el final del dia en UTC.
    - '/incidencias-recientes' pasa a usar ese helper (el comportamiento
      observable no cambia: ya respetaba el rango explicito).
    - '/detalle-kpi' acepta 'fecha_desde' y 'fecha_hasta' con la misma
      precedencia y la misma semantica.
    - '/detalle-kpi' acota la fecha superior con 'created_at <= ...'.
    - '/detalle-kpi' cambia el 'join' por 'outerjoin' con 'estados': el
      resumen cuenta sobre 'Ticket' sin join, asi que el modal tampoco debe
      perder tickets por un estado huerfano.
    - '/detalle-kpi' calcula 'total' como el conteo real del KPI (antes de
      aplicar el limite) y anade 'total_listado' y 'truncado'.
    - '/detalle-kpi' devuelve 'rango_explicito', 'fecha_desde' y
      'fecha_hasta' para que el front pueda mostrar el rango real.
    - Los 7 filtros de '_KPI_DETALLE' reciben ahora el mismo instante
      'ahora' que usa el resumen. Antes cada lambda evaluaba
      'datetime.utcnow()' por su cuenta y los filtros de 'vencidas' y
      'en_riesgo_72h' podian discrepar un instante del resumen.

  Front (app/templates/dashboard/index.html):
    - Nueva funcion '_filtrosIncidenciasRecientes()' como fuente UNICA de
      los filtros (tipo, periodo, fecha_desde, fecha_hasta). La usan la
      carga del resumen, la apertura del modal y la exportacion a CSV, de
      modo que ya no pueden divergir entre si.
    - El modal envia el rango explicito y el tipo real de la seccion.
    - El modal muestra el rango REAL con el que se calculo el listado (ya
      no siempre "N dias") y avisa de forma explicita cuando el listado
      esta truncado por el limite, indicando cuantos tickets hay y
      cuantos se muestran.
    - El badge de la seccion ("N TICKETS") muestra el TOTAL real del
      periodo, no el numero de filas truncado de la tabla. Antes, con mas
      de 50 tickets, el badge y la casilla "Total periodo" se contradician.
    - La exportacion a CSV vuelve a pedir el listado con el tope maximo del
      endpoint (200) usando los mismos filtros, y avisa si aun asi queda
      contenido fuera. Antes exportaba la cache de la tabla, truncada a 50
      filas.
    - El bloque rapido 'Hoy' cubre 1 dia. Antes 'parseInt("hoy")' era NaN
      y caia al valor por defecto de 7 dias, de modo que un filtro rotulado
      "Hoy" cubria en realidad los ultimos 7 dias.
    - Editar una fecha a mano cambia el bloque a 'Personalizado' y ya no se
      descarta. Antes los inputs llamaban a 'aplicarBloqueFechas()', que
      reponia las fechas del bloque rapido y tiraba la edicion manual
      (el comentario del codigo describia el comportamiento contrario al
      que realmente habia).

  Que NO cambia para el usuario final: el criterio de los 7 KPIs. El
  modal deja de mostrar una lista distinta de la cifra y pasa a mostrar la
  lista de esa cifra.

================================================================================
3. QUE NO SE MODIFICO
================================================================================

  - Ningun modelo de datos. No se toco 'app/models/'.
  - Ninguna migracion. No se toco 'app/db/migrations.py' ni el esquema de
    la base de datos. No se ejecuto ninguna sentencia DDL ni DML.
  - Ninguna variable de entorno ni ninguna configuracion de despliegue.
    No se toco 'railway.toml', 'Procfile', 'start.sh', 'requirements.txt',
    'pyproject.toml' ni 'runtime.txt'.
  - Ninguna otra ruta de la API. Solo se anaden dos parametros OPCIONALES
    ('fecha_desde' y 'fecha_hasta') a '/api/v1/metricas/detalle-kpi'. Las
    rutas existentes no cambian de nombre, de metodo ni de contrato.
  - Ningun endpoint de '/api/v1/metricas/incidencias-recientes': su
    comportamiento observable es identico, solo cambia que su resolucion
    del rango pasa a vivir en un helper compartido.
  - Ninguna otra seccion del dashboard. Los bloques "Cuenta de Resultado",
    "Top agentes", "Riesgo" y los paneles laterales no se tocaron.
  - Ningun worker ni tarea de Celery. No hay tareas nuevas, ni colas
    nuevas, ni cambios de cron.
  - Nada del despliegue en produccion: este documento no ejecuta nada.
  - No se reescribio ningun README de releases anteriores (V1.001 a
    V2.001). Las erratas que pueda haber se declaran por referencia en la
    seccion 6.
  - No se toco la suite de verificadores 'tools/verificacion/' ni se anadio
    ninguna verificacion nueva ahi.
  - No se toco 'app/api/v1/auth.py' ni el flujo de login.

================================================================================
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  REQUIERE CAMBIAR WORKER: NO.
  REQUIERE CAMBIAR BEAT: NO.
  REQUIERE CAMBIAR BASE DE DATOS: NO.
  REQUIERE VARIABLES DE ENTORNO NUEVAS: NO.
  REQUIERE MIGRACION: NO.

  El cambio es de codigo de aplicacion (un router y una plantilla). Se
  despliega en el servicio web con el procedimiento normal.

  Para el worker y el beat: no hace falta redesplegarlos. El worker sigue
  ejecutando el commit 6038fc29 y el beat tambien. Es importante que las
  tres versiones queden alineadas cuando se despliegue este lote: por eso
  el paso 3 del procedimiento de despliegue (seccion 7) los incluye.

  Nota de versionado de APIs: '/api/v1/metricas/detalle-kpi' acepta dos
  parametros nuevos y opcionales. Un cliente antiguo (sin los parametros)
  sigue funcionando exactamente igual: usa la ventana de 'periodo_dias'.
  Un cliente nuevo que envie el rango explicito obtendra el listado de ese
  rango. No hay cambio incompatible.

================================================================================
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1  Reproduccion del defecto (contra la version con el defecto, la del
       viernes 6038fc29):

       a) Login como administrador.
       b) Dashboard, seccion "Lista de Incidencias Recientes".
       c) Selector de bloque rapido: "Ultimos 90 dias".
       d) Anotar el valor de la casilla "TOTAL PERIODO" (en el caso
          reportado: 18) y el del badge de la cabecera de la seccion.
       e) Hacer clic en la casilla "TOTAL PERIODO".
       f) Anotar el "Total:" que muestra el modal (en el caso reportado:
          2 tickets) y el "Periodo:" que muestra.
       g) Comprobacion: las dos cifras NO coinciden. El modal dice
          "Periodo: 30 dias" aunque el resumen esta filtrando 28-07-2026
          -> 26-10-2026.

  5.2  Verificacion del arreglo (contra la version ya desplegada):

       a) Repetir los pasos 5.1 b) a f).
       b) Comprobacion 1: el "Total:" del modal es IGUAL al valor de
          "TOTAL PERIODO" del resumen.
       c) Comprobacion 2: el "Periodo:" del modal muestra el rango real
          "2026-07-28 -> 2026-10-26", no "30 dias".
       d) Comprobacion 3: el listado del modal tiene 18 filas (una por
          ticket del KPI), no 2.
       e) Comprobacion 4: cambiar el bloque rapido a "Ultimos 7 dias" y
          volver a abrir el modal: las dos cifras vuelven a coincidir y el
          "Periodo:" cambia a "7 dias".
       f) Comprobacion 5: cambiar el selector de tipo a "Todos" y abrir el
          modal: el modal debe respetar ese tipo (antes siempre ponia
          "incidencia").
       g) Comprobacion 6: pulsar "Limpiar" (deja el bloque en 7 dias) y
          abrir el modal: el "Periodo:" debe decir "7 dias", no "30 dias".
       h) Comprobacion 7: escribir una fecha a mano en los campos
          desde/hasta. El bloque debe cambiar solo a "Personalizado..." y
          el rango elegido debe respected, tanto en el resumen como en el
          modal.
       i) Comprobacion 8: elegir "Hoy" en el bloque rapido. El rango debe
          ser el dia de hoy (antes cubria 7 dias).
       j) Comprobacion 9: pulsar "Exportar CSV" y abrir el archivo. El
          numero de filas debe coincidir con el total del periodo. Si el
          periodo tiene mas de 200 tickets, la aplicacion avisa de que el
          CSV esta truncado.

  5.3  Verificacion automatizada (no toca produccion):

       cd <repo>
       python -m pytest tests/test_v2002_consistencia_kpi.py -q
       python -m pytest tests/ -q

       La suite nueva (9 pruebas) comprueba, sobre la SQLite temporal de
       la suite:
         - el modal respeta el rango explicito de fechas;
         - el resumen, el modal y un conteo INDEPENDIENTE en la base
           devuelven la misma cifra;
         - 'fecha_hasta' es inclusiva contra el final del dia;
         - 'total' es el total real y 'limite' solo recorta el listado;
         - cada KPI que es un conteo cuadra entre resumen y modal;
         - el front usa un unico resolvedor de filtros y no el id de
           selector inexistente;
         - el bloque 'Hoy' cubre un dia;
         - la edicion manual de fechas no se descarta.

  5.4  Comprobacion de no regresion en produccion (solo lectura):

       GET /health , GET /ready y GET /info deben seguir en 200.
       POST /api/v1/auth/login debe seguir en 200.

================================================================================
6. TRAZABILIDAD
================================================================================

  Defecto reportado por: el propietario (dashboard, seccion "Lista de
  Incidencias Recientes", casilla "Total periodo").

  Reproduccion: 2026-10-26, contra produccion con el commit 6038fc29
  (la version del viernes, que es la que seguia desplegada).
  Resumen 18 tickets / modal 2 tickets con los mismos filtros visibles.

  Archivos intervenidos:
    app/api/v1/metricas.py
      - _resolver_rango_temporal()      [NUEVA]
      - incidencias_recientes()
      - _KPI_DETALLE
      - detalle_kpi()
    app/templates/dashboard/index.html
      - _filtrosIncidenciasRecientes()  [NUEVA]
      - cargarIncidenciasRecientes()
      - abrirModalKpiDetalle()
      - _renderModalKpiDetalle()
      - _kpiRangoTexto()                [NUEVA]
      - aplicarBloqueFechas()
      - aplicarFechasManuales()         [NUEVA]
      - exportarIncidenciasRecientes()
    tests/test_v2002_consistencia_kpi.py   [NUEVO, 9 pruebas]

  Pruebas: 9 pruebas nuevas en verde. Suite completa del repositorio
  ejecutada sobre la SQLite temporal (nunca sobre la base de produccion).

  Relacion con los lotes anteriores:
    - V2.001 (README_V2.001_..._2026-10-26.txt, rama 'release/v2.001')
      sigue vigente y no se modifica. Este lote es posterior e
      independiente.
    - El README de V2.001 tiene una errata en su seccion 8.6: decia que
      el codigo del lote estaba en 'main'. Tras la alineacion de 'main'
      con el commit del viernes, el codigo esta en 'release/v2.001'. La
      correccion se documento en las secciones 8.7 a 8.9 de ese mismo
      README; aqui no se reescribe.

  Estado en produccion al cierre de este documento: sigue desplegada la
  version del viernes 6038fc29 en los tres servicios. Este lote esta
  listo y verificado en local, pero NO desplegado.

================================================================================
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  PRECONDICIONES
    - 'main' y 'release/v2.001' revisados y con la suite en verde.
    - El build de la plataforma recuperado (el 2026-10-26 el despliegue de
      c6eca9b termino en SUCCESS, con lo que el daemon BuildKit vuelve a
      funcionar).
    - Copia de seguridad de la base de datos vigente.

  PASOS DE DESPLIEGUE
    1) Publicar la rama 'release/v2.001' con este lote.
    2) Desplegar el commit resultante en los TRES servicios (web, worker y
       beat) con el mismo SHA. No desplegar solo el web: dejaria las
       versiones desalineadas.
    3) Comprobar el estado de cada despliegue hasta que los tres queden
       en SUCCESS.
    4) Comprobacion rapida: GET /health , GET /ready y el login deben
       responder 200.
    5) Reproducir la seccion 5.2 completa con la cuenta de administrador.
    6) Alinear 'main' con la rama desplegada (avance rapido, nunca
       'push --force'). Si no se hace, un push posterior a 'main' volveria
       a desplegar la version del viernes y se perderia este arreglo.

  ROLLBACK
    - El rollback es un despliegue del commit anterior, no una operacion
      de base de datos: este lote no cambia el esquema, asi que no hay
      nada que revertir en la base.
    - Commit de retorno: 63d1f86 (release/v2.001 sin este lote), que
      contiene V1.005, V1.006 y V2.001.
    - Procedimiento: desplegar 63d1f86 en los tres servicios, esperar a
      SUCCESS y repetir la comprobacion rapida del paso 4.
    - Consecuencia de volver atras: se pierde este arreglo (el modal
      vuelve a mostrar una ventana distinta de la del resumen) y se
      reaparecen las fugas anonimas y las dos rutas en 500 que arrastran
      las versiones anteriores a V1.006. Para eso esta el rollback
      documentado en el README de V2.001.
    - Este lote NO requiere rollback de base de datos en ningun caso.

  COMPROBACION POST-DESPLIEGUE
    - /health 200, /ready 200, /info 200.
    - Login de administrador 200.
    - Modal "Total periodo" con el mismo total que la casilla del resumen,
      con el rango real en la cabecera del modal.
    - Barrido anonimo sin fugas nuevas.

================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

Ficheros: app/api/v1/metricas.py y app/templates/dashboard/index.html

Nota: el diff se reproduce con los caracteres no ASCII transliterados a
ASCII (acentos, flechas y comillas tipograficas) para que este documento
sea legible en cualquier editor. El CODIGO DEL PROYECTO NO SE MODIFICA:
sigue en UTF-8 con su acentuacion original.
----------------------------------------------------------------------
diff --git a/app/api/v1/metricas.py b/app/api/v1/metricas.py
index 0002b85..96cc796 100644
--- a/app/api/v1/metricas.py
+++ b/app/api/v1/metricas.py
@@ -85,6 +85,67 @@ def _build_tipo_filter(tipo: str):
     return func.upper(Ticket.tipo.cast(String)).in_(list(_TIPOS_VALIDOS.values()))
 
 
+def _resolver_rango_temporal(periodo_dias, fecha_desde, fecha_hasta, ahora):
+    """Resuelve el rango temporal de los listados de incidencias.
+
+    UNICA fuente de verdad del rango para TODO el bloque "Lista de
+    Incidencias Recientes": la franja de 7 KPI (resumen), la tabla y el
+    modal de drill-down.
+
+    Antes cada endpoint resolvia la ventana por su cuenta y el modal se
+    quedaba siempre con ``periodo_dias`` aunque el usuario hubiera
+    elegido un rango explicito de fechas. El resultado era que el resumen
+    contaba los tickets del rango elegido (18 en 90 dias) y el modal
+    listaba los de otra ventana (2 en 30 dias), sin que el usuario
+    pudiera ver la diferencia.
+
+    Precedencia: si se envia ``fecha_desde`` o ``fecha_hasta``, ese rango
+    explicito manda sobre la ventana de ``periodo_dias``. ``fecha_hasta``
+    es inclusivo (se compara contra el final del dia en UTC).
+
+    Returns:
+        Diccionario con las claves ``periodo_dias``, ``fecha_limite``,
+        ``fecha_hasta_limite``, ``rango_explicito``, ``fecha_desde_dt`` y
+        ``fecha_hasta_dt``.
+    """
+    periodo_dias = max(1, min(periodo_dias, 365))
+    fecha_desde_dt = None
+    fecha_hasta_dt = None
+    rango_explicito = False
+
+    if fecha_desde:
+        try:
+            fecha_desde_dt = datetime.fromisoformat(fecha_desde)
+            rango_explicito = True
+        except ValueError:
+            fecha_desde_dt = None
+    if fecha_hasta:
+        try:
+            # inclusivo: hasta el final del dia 23:59:59
+            fecha_hasta_dt = datetime.fromisoformat(fecha_hasta)
+            fecha_hasta_dt = fecha_hasta_dt.replace(
+                hour=23, minute=59, second=59, microsecond=999999
+            )
+            rango_explicito = True
+        except ValueError:
+            fecha_hasta_dt = None
+
+    if rango_explicito:
+        fecha_limite = fecha_desde_dt or datetime.min
+    else:
+        fecha_limite = ahora - timedelta(days=periodo_dias)
+    fecha_hasta_limite = fecha_hasta_dt or ahora
+
+    return {
+        "periodo_dias": periodo_dias,
+        "fecha_limite": fecha_limite,
+        "fecha_hasta_limite": fecha_hasta_limite,
+        "rango_explicito": rango_explicito,
+        "fecha_desde_dt": fecha_desde_dt,
+        "fecha_hasta_dt": fecha_hasta_dt,
+    }
+
+
 # Columnas esperadas para la tabla pivote "Cuenta de Resultado"
 # Replica del rango A64:H81 de la hoja REPORTE del Excel UAT.
 #
@@ -1026,44 +1087,20 @@ def incidencias_recientes(
         habitual del dashboard. Si la fecha de inicio ``Ticket.fecha_inicio``
         esta presente se prefiere para mostrar el "inicio real" del trabajo.
     """
-    periodo_dias = max(1, min(periodo_dias, 365))
     limite = max(1, min(limite, 200))
     ahora = datetime.utcnow()
 
-    # === Rango explicito tiene precedencia ===
-    rango_explicito = False
-    fecha_desde_dt = None
-    fecha_hasta_dt = None
-    if fecha_desde:
-        try:
-            fecha_desde_dt = datetime.fromisoformat(fecha_desde)
-            rango_explicito = True
-        except ValueError:
-            fecha_desde_dt = None
-    if fecha_hasta:
-        try:
-            # inclusivo: hasta el final del dia 23:59:59
-            fecha_hasta_dt = datetime.fromisoformat(fecha_hasta)
-            fecha_hasta_dt = fecha_hasta_dt.replace(
-                hour=23, minute=59, second=59, microsecond=999999
-            )
-            rango_explicito = True
-        except ValueError:
-            fecha_hasta_dt = None
-
-    if rango_explicito:
-        # Cuando el usuario define un rango explicito, el "periodo_dias"
-        # deja de tener efecto. Mantenemos el valor informativo para el
-        # front pero la consulta usa el rango.
-        fecha_limite = fecha_desde_dt or datetime.min
-    else:
-        # FIX(metricas): sin rango explicito caemos al comportamiento
-        # legacy (ventana de N dias hacia atras). Sin este else el
-        # filtro `Ticket.created_at >= fecha_limite` lanzaba
-        # UnboundLocalError y el dashboard quedaba colgado en
-        # "Cargando metricas...".
-        fecha_limite = ahora - timedelta(days=periodo_dias)
-    fecha_hasta_limite = fecha_hasta_dt or ahora
+    # FIX-KPI-CONSISTENCIA(metricas): el rango se resuelve con el helper
+    # compartido para que el resumen, la tabla y el modal de drill-down
+    # usen EXACTAMENTE la misma ventana. Antes cada endpoint lo resolvia
+    # por su cuenta y el modal ignoraba el rango explicito.
+    rango = _resolver_rango_temporal(periodo_dias, fecha_desde, fecha_hasta, ahora)
+    periodo_dias = rango["periodo_dias"]
+    fecha_limite = rango["fecha_limite"]
+    fecha_hasta_limite = rango["fecha_hasta_limite"]
+    rango_explicito = rango["rango_explicito"]
+    fecha_desde_dt = rango["fecha_desde_dt"]
+    fecha_hasta_dt = rango["fecha_hasta_dt"]
 
     # === Filtro de tipo ===
     # FIX(metricas): el Enum Python (TipoIncidencia.INCIDENCIA.value = 'incidencia')
@@ -1323,31 +1360,31 @@ _KPI_DETALLE = {
     "total_periodo": {
         "titulo": "Total periodo",
         "descripcion": "Todos los tickets del periodo (tipo y filtros aplicados).",
-        "filtro": lambda base: base,
+        "filtro": lambda base, ahora: base,
     },
     "vencidas": {
         "titulo": "Tickets vencidos",
         "descripcion": "Tickets sin completar cuya fecha de vencimiento SLA ya paso.",
-        "filtro": lambda base: base.filter(
+        "filtro": lambda base, ahora: base.filter(
             Ticket.fecha_completado.is_(None),
             Ticket.fecha_vencimiento_sla.isnot(None),
-            Ticket.fecha_vencimiento_sla < datetime.utcnow(),
+            Ticket.fecha_vencimiento_sla < ahora,
         ),
     },
     "en_riesgo_72h": {
         "titulo": "Tickets en riesgo (proximas 72h)",
         "descripcion": "Tickets sin completar cuya fecha de vencimiento SLA esta dentro de las proximas 72 horas.",
-        "filtro": lambda base: base.filter(
+        "filtro": lambda base, ahora: base.filter(
             Ticket.fecha_completado.is_(None),
             Ticket.fecha_vencimiento_sla.isnot(None),
-            Ticket.fecha_vencimiento_sla >= datetime.utcnow(),
-            Ticket.fecha_vencimiento_sla <= datetime.utcnow() + timedelta(hours=72),
+            Ticket.fecha_vencimiento_sla >= ahora,
+            Ticket.fecha_vencimiento_sla <= ahora + timedelta(hours=72),
         ),
     },
     "criticas_o_altas": {
         "titulo": "Tickets Crit/Altas",
         "descripcion": "Tickets del periodo con prioridad Critica o Alta.",
-        "filtro": lambda base: base.filter(
+        "filtro": lambda base, ahora: base.filter(
             func.upper(Ticket.prioridad.cast(String)).in_([
                 Prioridad.CRITICA.value.upper(),
                 Prioridad.ALTA.value.upper(),
@@ -1361,19 +1398,19 @@ _KPI_DETALLE = {
         # los OK=1 vs NOK=0 vs pendientes=-1.
         "titulo": "Tickets base del % SLA OK",
         "descripcion": "Tickets cerrados del periodo. El % SLA OK se calcula sobre este conjunto.",
-        "filtro": lambda base: base.filter(Ticket.fecha_completado.isnot(None)),
+        "filtro": lambda base, ahora: base.filter(Ticket.fecha_completado.isnot(None)),
     },
     "porcentaje_sin_asignar": {
         "titulo": "Tickets sin asignar",
         "descripcion": "Tickets del periodo sin responsable asignado.",
-        "filtro": lambda base: base.filter(Ticket.asignado_id.is_(None)),
+        "filtro": lambda base, ahora: base.filter(Ticket.asignado_id.is_(None)),
     },
     "tiempo_promedio_resolucion_horas": {
         # TTR prom. no tiene categoria clara: mostramos los cerrados
         # del periodo (la base del calculo TTR).
         "titulo": "Tickets base del TTR promedio",
         "descripcion": "Tickets cerrados del periodo (base del calculo de tiempo promedio de resolucion).",
-        "filtro": lambda base: base.filter(Ticket.fecha_completado.isnot(None)),
+        "filtro": lambda base, ahora: base.filter(Ticket.fecha_completado.isnot(None)),
     },
 }
 
@@ -1384,6 +1421,8 @@ def detalle_kpi(
     periodo_dias: int = 30,
     tipo: str = "incidencia",
     limite: int = 200,
+    fecha_desde: str = None,
+    fecha_hasta: str = None,
     db: Session = Depends(get_db),
     user: Usuario = Depends(get_current_user),
 ):
@@ -1402,6 +1441,11 @@ def detalle_kpi(
               con prefijo INC- / INC_ (ver FIX-PREFIX en
               ``incidencias_recientes``).
       - limite: maximo de tickets devueltos (1..500).
+      - fecha_desde / fecha_hasta: rango explicito ISO (YYYY-MM-DD) que
+              tiene precedencia sobre ``periodo_dias``, igual que en
+              ``incidencias_recientes``. Sin esto el modal drill-down
+              contaba otra ventana distinta a la del resumen y mostraba
+              una lista que no correspondia con la cifra del KPI.
     """
     if kpi not in _KPI_DETALLE:
         raise HTTPException(
@@ -1412,10 +1456,19 @@ def detalle_kpi(
             ),
         )
 
-    periodo_dias = max(1, min(periodo_dias, 365))
     limite = max(1, min(limite, 500))
     ahora = datetime.utcnow()
-    fecha_limite = ahora - timedelta(days=periodo_dias)
+
+    # FIX-KPI-CONSISTENCIA(metricas): el modal usa el MISMO resolvedor de
+    # rango que el resumen, de modo que el listado que muestra y el
+    # contador de la casilla KPI del que se partio son el mismo conjunto.
+    rango = _resolver_rango_temporal(periodo_dias, fecha_desde, fecha_hasta, ahora)
+    periodo_dias = rango["periodo_dias"]
+    fecha_limite = rango["fecha_limite"]
+    fecha_hasta_limite = rango["fecha_hasta_limite"]
+    rango_explicito = rango["rango_explicito"]
+    fecha_desde_dt = rango["fecha_desde_dt"]
+    fecha_hasta_dt = rango["fecha_hasta_dt"]
 
     # === Filtro de tipo ===
     # FIX-PREFIX-DRY(metricas): se usa el helper compartido
@@ -1424,18 +1477,28 @@ def detalle_kpi(
     tipo_filter = _build_tipo_filter(tipo)
 
     # === Base + filtro de periodo + archivado ===
+    # outerjoin (y no join): el resumen cuenta sobre ``Ticket`` sin join,
+    # asi que el modal tampoco debe perder tickets por un estado huerfano.
     base = (
         db.query(Ticket, Estado)
-        .join(Estado, Estado.id == Ticket.estado_id)
+        .outerjoin(Estado, Estado.id == Ticket.estado_id)
         .filter(
             tipo_filter,
             Ticket.archivado == False,  # noqa: E712
             Ticket.created_at >= fecha_limite,
+            Ticket.created_at <= fecha_hasta_limite,
         )
     )
 
     # === Aplicar el filtro especifico del KPI ===
-    base = _KPI_DETALLE[kpi]["filtro"](base)
+    base = _KPI_DETALLE[kpi]["filtro"](base, ahora)
+
+    # FIX-KPI-CONSISTENCIA(metricas): 'total' es el total real del KPI
+    # (sin truncar por 'limite'), para que coincida con la cifra que
+    # muestra la casilla del resumen. Antes era len(tickets_out), de modo
+    # que el modal podia anunciar "Total: N tickets" sin cuadrar con el
+    # KPI de la franja.
+    total_real = base.count()
 
     # === Orden: vencidas primero, luego mas recientes ===
     base = base.order_by(
@@ -1470,6 +1533,13 @@ def detalle_kpi(
         "periodo_dias": periodo_dias,
         "tipo":         tipo,
         "limite":       limite,
-        "total":        len(tickets_out),
+        "total":        total_real,
+        "total_listado": len(tickets_out),
+        "truncado":     total_real > len(tickets_out),
+        "rango_explicito": rango_explicito,
+        "fecha_desde":  fecha_desde_dt.isoformat() if fecha_desde_dt else None,
+        "fecha_hasta":  fecha_hasta_dt.isoformat() if fecha_hasta_dt else None,
+        "fecha_desde_cl": fmt_cl_iso(fecha_desde_dt) if fecha_desde_dt else None,
+        "fecha_hasta_cl": fmt_cl_iso(fecha_hasta_dt) if fecha_hasta_dt else None,
         "tickets":      tickets_out,
     }
diff --git a/app/templates/dashboard/index.html b/app/templates/dashboard/index.html
index e7dac2b..b0e3193 100644
--- a/app/templates/dashboard/index.html
+++ b/app/templates/dashboard/index.html
@@ -310,13 +310,13 @@
             <!-- Rango explicito (precedencia sobre el bloque) -->
             <input id="incidencias-recientes-desde"
                    type="date"
-                   onchange="aplicarBloqueFechas()"
+                   onchange="aplicarFechasManuales()"
                    title="Fecha desde (apertura de la incidencia)"
                    class="text-[11px] border border-slate-200 rounded px-2 py-1 bg-white">
             <span class="text-[10px] text-slate-400">-></span>
             <input id="incidencias-recientes-hasta"
                    type="date"
-                   onchange="aplicarBloqueFechas()"
+                   onchange="aplicarFechasManuales()"
                    title="Fecha hasta (apertura de la incidencia)"
                    class="text-[11px] border border-slate-200 rounded px-2 py-1 bg-white">
 
@@ -1058,6 +1058,21 @@
     'tiempo_promedio_resolucion_horas':    'TTR prom. (h)',
   };
 
+  // FIX-KPI-CONSISTENCIA(dashboard): el modal mostraba siempre
+  // "Periodo: N dias" aunque el resumen estuviera filtrando por un rango
+  // explicito de fechas (28-07-2026 -> 26-10-2026). Ahora muestra el rango
+  // REAL con el que se calculo el listado, para que el modal y la franja
+  // de KPI sean legibles como el mismo filtro.
+  function _kpiRangoTexto(data) {
+    if (!data) return '?';
+    if (data.rango_explicito && (data.fecha_desde || data.fecha_hasta)) {
+      const a = data.fecha_desde ? String(data.fecha_desde).slice(0, 10) : '...';
+      const b = data.fecha_hasta ? String(data.fecha_hasta).slice(0, 10) : '...';
+      return a + ' -> ' + b;
+    }
+    return (data.periodo_dias || '?') + ' dias';
+  }
+
   function _kpiPrioridadColor(p) {
     if (!p) return '#94a3b8';
     const v = String(p).toLowerCase();
@@ -1116,15 +1131,20 @@
       + '</div>';
 
     try {
-      const sel = safeId('periodo');
-      const periodo = sel ? (sel.value || '30') : '30';
-      const tipoSel = safeId('incidencias-tipo');
-      const tipo = tipoSel ? (tipoSel.value || 'incidencia') : 'incidencia';
+      // FIX-KPI-CONSISTENCIA(dashboard): el modal parte de EXACTAMENTE los
+      // mismos filtros que la franja de KPI de arriba. Antes leia el
+      // selector global '#periodo' (30 dias por defecto) y un id de
+      // selector de tipo inexistente ('incidencias-tipo'), de modo que
+      // ignoraba el rango explicito elegido por el usuario: el resumen
+      // contaba 18 tickets de 90 dias y el modal listaba 2 de 30 dias.
+      const filtros = _filtrosIncidenciasRecientes();
       const url = '/api/v1/metricas/detalle-kpi'
         + '?kpi=' + encodeURIComponent(kpi)
-        + '&periodo_dias=' + encodeURIComponent(periodo)
-        + '&tipo=' + encodeURIComponent(tipo)
+        + '&periodo_dias=' + encodeURIComponent(filtros.periodo)
+        + '&tipo=' + encodeURIComponent(filtros.tipo)
         + '&limite=200'
+        + (filtros.fecha_desde ? '&fecha_desde=' + encodeURIComponent(filtros.fecha_desde) : '')
+        + (filtros.fecha_hasta ? '&fecha_hasta=' + encodeURIComponent(filtros.fecha_hasta) : '')
         + '&_=' + Date.now();
       const r = await fetch(url, {
         headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
@@ -1206,10 +1226,16 @@
       +       '</h3>'
       +       '<p class="text-xs text-slate-500 mt-1">' + _escapeHtml(data.descripcion || '') + '</p>'
       +       '<p class="text-[11px] text-slate-400 mt-1">'
-      +         'Periodo: <span class="font-mono">' + (data.periodo_dias || '?') + ' dias</span>'
+      +         'Periodo: <span class="font-mono">' + _escapeHtml(_kpiRangoTexto(data)) + '</span>'
       +         ' - Tipo: <span class="font-mono">' + _escapeHtml(data.tipo || '?') + '</span>'
       +         ' - Total: <span class="font-mono">' + (data.total || 0) + '</span> tickets'
       +       '</p>'
+      +       (data.truncado
+      +         ? '<p class="text-[11px] text-amber-600 mt-1">Se muestran '
+      +             + (data.total_listado || 0) + ' de ' + (data.total || 0)
+      +             + ' tickets: el listado esta limitado a ' + (data.limite || 0)
+      +             + ' filas. Usa "Exportar CSV" para el periodo completo.</p>'
+      +         : '')
       +     '</div>'
       +     '<button type="button" data-close-modal="1" class="text-slate-400 hover:text-slate-700 p-1" aria-label="Cerrar">'
       +       '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'
@@ -1621,6 +1647,51 @@
          + '</span>';
   }
 
+  // ===================================================================
+  // FILTROS DE LA "LISTA DE INCIDENCIAS RECIENTES" (fuente unica)
+  // ===================================================================
+  // FIX-KPI-CONSISTENCIA(dashboard): el resumen (franja de 7 KPI), la
+  // tabla y el modal de drill-down deben partir de EXACTAMENTE los mismos
+  // filtros. Antes cada uno los resolvia por su cuenta: el modal leia el
+  // selector global '#periodo' (30 dias por defecto) y un id de selector
+  // de tipo inexistente ('incidencias-tipo'), de modo que ignoraba el
+  // rango explicito elegido por el usuario. El resumen contaba 18
+  // tickets de 90 dias y el modal listaba 2 de 30 dias.
+  //
+  // Esta funcion es la unica fuente de verdad: la usan la carga del
+  // resumen, la apertura del modal y la exportacion a CSV.
+  function _filtrosIncidenciasRecientes() {
+    const tipoSel = safeId('incidencias-recientes-tipo');
+    const tipo    = (tipoSel && tipoSel.value) ? tipoSel.value : 'incidencia';
+
+    const bloque = safeId('incidencias-recientes-bloque');
+    const desde  = safeId('incidencias-recientes-desde');
+    const hasta  = safeId('incidencias-recientes-hasta');
+    const fd = (desde && desde.value) || '';
+    const fh = (hasta && hasta.value) || '';
+
+    // El bloque rapido de la SECCION es el que manda ('hoy' | 7 | 30 | 90).
+    // 'personalizado' sin fechas informadas cae al selector global de la
+    // cabecera, que es el unico caso en el que se usa.
+    let periodo = (bloque && bloque.value) ? bloque.value : '';
+    if (!periodo || periodo === 'personalizado') {
+      const globalSel = safeId('periodo');
+      periodo = (globalSel && globalSel.value) ? globalSel.value : '30';
+    }
+    if (periodo === 'hoy') periodo = '1';
+
+    return {
+      tipo: tipo,
+      periodo: periodo,
+      fecha_desde: fd,
+      fecha_hasta: fh,
+      // Etiqueta legible del rango efectivo (la muestra el modal).
+      rango_texto: (fd || fh)
+        ? (fd || '...') + ' -> ' + (fh || '...')
+        : periodo + ' dias',
+    };
+  }
+
   async function cargarIncidenciasRecientes() {
     const cont    = safeId('incidencias-recientes-wrap');
     const loading = safeId('incidencias-recientes-loading');
@@ -1629,19 +1700,11 @@
     const badge   = safeId('incidencias-recientes-periodo');
     if (!cont || !table || !tbody) return;
 
-    const tipoSel = safeId('incidencias-recientes-tipo');
-    const tipo    = (tipoSel && tipoSel.value) ? tipoSel.value : 'incidencia';
-    const periodo = (safeId('periodo') || { value: '30' }).value;
-
-    // === Filtro de rango de fechas ===
-    // El bloque rapido (hoy / 7d / 30d / 90d) solo se aplica si NO hay
-    // un rango explicito definido en los inputs desde/hasta. Si el
-    // usuario escoge uno o ambos, toman precedencia.
-    const bloque  = safeId('incidencias-recientes-bloque');
-    const desde   = safeId('incidencias-recientes-desde');
-    const hasta   = safeId('incidencias-recientes-hasta');
-    const fd = (desde && desde.value) || '';
-    const fh = (hasta && hasta.value) || '';
+    const filtros = _filtrosIncidenciasRecientes();
+    const tipo    = filtros.tipo;
+    const periodo = filtros.periodo;
+    const fd      = filtros.fecha_desde;
+    const fh      = filtros.fecha_hasta;
 
     // Mostrar loading sin perder la tabla (solo overlay visual)
     if (loading) loading.classList.remove('hidden');
@@ -1695,8 +1758,19 @@
         } else {
           label = (data.periodo_dias || periodo) + 'd';
         }
-        badge.textContent =
-          label + ' - ' + (data.tickets || []).length + ' tickets';
+        // FIX-KPI-CONSISTENCIA(dashboard): el badge muestra el TOTAL real
+        // del periodo (el mismo numero que la casilla "Total periodo"), no
+        // la cantidad de filas que devolvio la tabla, que viene truncada
+        // por 'limite'. Antes ambos numeros podian discordar entre si.
+        const totalReal = (data.metricas && data.metricas.total_periodo != null)
+          ? data.metricas.total_periodo
+          : (data.tickets || []).length;
+        const mostrados = (data.tickets || []).length;
+        let textoBadge = label + ' - ' + totalReal + ' tickets';
+        if (mostrados < totalReal) {
+          textoBadge += ' (mostrando ' + mostrados + ')';
+        }
+        badge.textContent = textoBadge;
       }
 
       // === Pintar tabla ===
@@ -1842,8 +1916,16 @@
     }
 
     const hoy = new Date();
-    let dias = parseInt(val, 10);
-    if (isNaN(dias)) dias = 7;
+    // FIX-KPI-CONSISTENCIA(dashboard): la opcion "Hoy" se traducia a 7
+    // dias (parseInt('hoy') es NaN y caia al valor por defecto 7), de modo
+    // que un filtro rotulado "Hoy" cubria en realidad los ultimos 7 dias.
+    let dias;
+    if (val === 'hoy') {
+      dias = 0;
+    } else {
+      dias = parseInt(val, 10);
+      if (isNaN(dias)) dias = 7;
+    }
 
     const fmt = (d) => d.toISOString().slice(0, 10);
     if (desde) desde.value = fmt(new Date(hoy.getTime() - dias * 86400 * 1000));
@@ -1852,6 +1934,20 @@
     cargarIncidenciasRecientes();
   }
 
+  // FIX-KPI-CONSISTENCIA(dashboard): cuando el operador escribe a mano una
+  // fecha, el bloque rapido debe pasar a "Personalizado..." para que el rango
+  // elegido no se sobrescriba al recargar. Antes los inputs llamaban a
+  // aplicarBloqueFechas(), que reponia las fechas del bloque rapido y
+  // descartaba la edicion manual (el comentario del codigo describia el
+  // comportamiento contrario al que realmente habia).
+  function aplicarFechasManuales() {
+    const bloque = safeId('incidencias-recientes-bloque');
+    if (bloque && bloque.value !== 'personalizado') {
+      bloque.value = 'personalizado';
+    }
+    cargarIncidenciasRecientes();
+  }
+
   function limpiarFiltroFechas() {
     const desde = safeId('incidencias-recientes-desde');
     const hasta = safeId('incidencias-recientes-hasta');
@@ -1862,14 +1958,43 @@
     cargarIncidenciasRecientes();
   }
 
-  function exportarIncidenciasRecientes() {
-    if (!_incidenciasRecientesCache) {
-      alert('No hay datos cargados para exportar. Espera unos segundos o cambia el filtro para recargar.');
-      return;
+  // FIX-KPI-CONSISTENCIA(dashboard): el CSV se armaba con la cache de la
+  // tabla, que viene truncada por 'limite' (50 filas). Con un periodo
+  // grande el archivo exportado contenia menos tickets que el total del
+  // periodo. Ahora se vuelve a pedir el listado con el tope maximo del
+  // endpoint (200) usando EXACTAMENTE los mismos filtros, y se avisa si
+  // aun asi queda contenido fuera.
+  async function exportarIncidenciasRecientes() {
+    const filtros = _filtrosIncidenciasRecientes();
+    let data = _incidenciasRecientesCache;
+    let tickets = (data && data.tickets) || [];
+
+    try {
+      const params = [
+        'periodo_dias=' + encodeURIComponent(filtros.periodo),
+        'tipo=' + encodeURIComponent(filtros.tipo),
+        'limite=200',
+        '_=' + Date.now(),
+      ];
+      if (filtros.fecha_desde) params.push('fecha_desde=' + encodeURIComponent(filtros.fecha_desde));
+      if (filtros.fecha_hasta) params.push('fecha_hasta=' + encodeURIComponent(filtros.fecha_hasta));
+      const r = await fetch('/api/v1/metricas/incidencias-recentes?' + params.join('&'), {
+        headers: { 'X-User-Id': String(window.CURRENT_USER_ID || 1) },
+        cache: 'no-store',
+        credentials: 'same-origin',
+      });
+      if (r.ok) {
+        data = await r.json();
+        tickets = data.tickets || [];
+      }
+    } catch (e) {
+      // Si la recarga falla se exporta la cache que haya, que es mejor
+      // que no exportar nada, pero se avisa.
+      alert('No se pudo recuperar el listado completo del periodo. '
+            + 'Se exporta lo que hay en pantalla, que puede estar truncado.');
     }
-    const data = _incidenciasRecientesCache;
+
     const headers = ['Codigo', 'Titulo', 'Estado', 'Prioridad', 'Asignado', 'Fecha Vencimiento', 'SLA Activo', 'Horas Restantes', 'Modulo'];
-    const tickets = data.tickets || [];
     const rows = tickets.map(t => [
       t.codigo || '',
       t.titulo || '',
@@ -1893,6 +2018,16 @@
     a.click();
     document.body.removeChild(a);
     URL.revokeObjectURL(url);
+
+    // Aviso de truncamiento: el total del periodo es mayor que lo exportado.
+    const totalPeriodo = (data && data.metricas && data.metricas.total_periodo != null)
+      ? data.metricas.total_periodo
+      : null;
+    if (totalPeriodo != null && totalPeriodo > tickets.length) {
+      alert('El periodo contiene ' + totalPeriodo + ' tickets y el CSV contiene '
+            + tickets.length + ' (tope del endpoint). Filtra por un rango mas '
+            + 'corto para exportar el periodo completo.');
+    }
   }
 
   // === Drill-down modal: Cuenta de Resultado ===
@@ -1984,6 +2119,7 @@
   // Expongo solo las funciones que el HTML invoca desde atributos, no
   // toda la API interna (mantener superficie minima).
   window.aplicarBloqueFechas       = aplicarBloqueFechas;
+  window.aplicarFechasManuales      = aplicarFechasManuales;
   window.limpiarFiltroFechas       = limpiarFiltroFechas;
   window.cargarIncidenciasRecientes = cargarIncidenciasRecientes;
   window.exportarIncidenciasRecientes = exportarIncidenciasRecientes;

================================================================================
FIN DEL DOCUMENTO README V2.002
================================================================================
