================================================================================
README V2.008 - NUEVA CATEGORIA "BLOQUEADO PARA EJECUTAR" EN EL LOV DE
RESULTADO DE PRUEBAS (FIN DEL COLAPSO A "DESESTIMADA")
Proyecto: Bitacora GRM v2
Fecha: 2026-11-12
Rama base: main y release/v2.001 (commit 68478c5)
Estado: DESPLEGADO Y VERIFICADO EN PRODUCCION (2026-11-12). Commits 63d3d99 y cc3ebed.
================================================================================

0. PARCHE EXACTO
================================================================================

  0.1 FICHEROS MODIFICADOS (9) Y FICHERO NUEVO (1)

  app/core/resultado_pruebas.py   SSOT del catalogo. Es el UNICO sitio donde
                                   se declaran los valores, los acronimos y
                                   los colores del LOV de Resultado de Pruebas.
  app/api/v1/metricas.py          Pivote "Cuenta de Resultado" (columnas,
                                   SQL del pivot y drill-down por celda).
  app/models/ticket.py            Comentario del campo (el LOV real ya se
                                   reexportaba desde el catalogo).
  app/schemas/ticket.py           Descripcion del campo en el esquema/OpenAPI
                                   (el conjunto permitido ya se derivaba del
                                   catalogo).
  app/services/ticket_service.py  Comentario que documenta la regla de
                                   auto-marcado a DESESTIMADA (sin cambios de
                                   comportamiento).
  app/services/uat_import.py      Normalizador del importador UAT y mapa
                                   resultado_pruebas -> estado.
  app/templates/dashboard/index.html  Comentarios del pie y de los acronimos.
  tools/load_uat_consolidado.py   Normalizador del script de carga masiva.
  tools/uat_mapping.py            Documentacion de la regla y de los totales.
  tests/test_v2008_lov_bloqueado_para_ejecutar.py   NUEVO (35 tests).

  0.2 app/core/resultado_pruebas.py (SSOT)

  (a) RESULTADOS_LOV: se agrega el valor canonico.

      RESULTADOS_LOV: tuple = (
          "N/A",
          "NOK",
          "OK",
          "OK CON OBS.",
          "POSTERGADA",
          "DESESTIMADA",
          "BLOQUEADO PARA EJECUTAR",     <-- NUEVO
      )

  (b) RESULTADOS_LOV_FORMULARIO: se agrega el valor (selector de alta y de
      edicion). Los dos ordenes siguen describiendo el mismo conjunto
      (invariante comprobado por el propio modulo en el arranque).

  (c) ACRONIMOS: se agrega la entrada.

      "BLOQUEADO PARA EJECUTAR": "BLOQ",

  (d) COLORES: se agrega la entrada con color PROPIO.

      "BLOQUEADO PARA EJECUTAR": {"bg": "#0891b2", "text": "#ffffff",
                                   "cellText": "#1f2937"},

      El fondo #0891b2 (cian 600) no reutiliza ninguno de los otros siete
      fondos del catalogo (#94a3b8, #dc2626, #16a34a, #eab308, #ea580c,
      #7c3aed, #cbd5e1). Hay un test que lo comprueba.

  (e) _ALIASES: se agregan las variantes de entrada, en minusculas (la
      clave de busqueda es el valor en minusculas):

          "bloqueado para ejecutar":  "BLOQUEADO PARA EJECUTAR",
          "bloqueado para ejecucion": "BLOQUEADO PARA EJECUTAR",
          "bloqueado para ejecutar.": "BLOQUEADO PARA EJECUTAR",
          "bloqueado":                "BLOQUEADO PARA EJECUTAR",
          "bloq":                     "BLOQUEADO PARA EJECUTAR",

      Se declaran de forma EXPLICITA y no solo por el paso 3 de
      ``normalizar_resultado`` (comparacion compacta sin espacios ni
      puntos), para que el comportamiento sea legible y no dependa del
      fallback ni del orden de insercion del diccionario.

  (f) Docstring: la tabla valor/acronimo/categoria se re-ensancha para
      admitir el valor nuevo, pasa de "6 categorias" a "7 categorias", y se
      agrega una seccion que explica el porque de la categoria (V2.008).

  0.3 app/api/v1/metricas.py (pivote "Cuenta de Resultado")

  (a) Se importa RESULTADOS_CONOCIDOS del catalogo.

  (b) ``columnas_front`` deja de ser una lista literal y pasa a derivarse
      del catalogo:

          columnas_front = list(RESULTADOS_CONOCIDOS_RESULTADO)

      Antes era una lista escrita a mano con los mismos 7 valores. El
      cambio NO altera la respuesta (los valores y el orden son identicos);
      lo que hace es que el pivote y el front (que consume
      CUENTA_RESULTADO_LOV, inyectada desde el mismo catalogo) NO PUEDAN
      desalinearse al crecer el LOV. La especificacion exigia que "la
      columna debe ubicarse en el mismo orden en los tres lugares donde se
      declara el orden de columnas"; con esta derivacion el orden es igual
      por construccion y no por tres ediciones manuales.

  (c) ``sql_columnas`` (el SUM(CASE WHEN ...) del pivot) agrega la columna:

          ("BLOQUEADO PARA EJECUTAR", _eq_ci(
              "BLOQUEADO PARA EJECUTAR", "BLOQUEADO PARA EJECUCION",
              "BLOQUEADO PARA EJECUTAR.", "BLOQUEADO",
          )),

      Sin esta entrada los tickets con el valor nuevo caian en NINGUNA
      columna (ni siquiera en "(en blanco)", que solo agrupa NULL/vacio) y
      desaparecian del reporte EN SILENCIO. Hay un test que vigila que todo
      valor del catalogo tenga columna.

  (d) El drill-down por celda (endpoint cuenta-resultado/detalle) agrega la
      rama propia, para que acepte las mismas variantes:

          elif resultado_filtro.upper() == "BLOQUEADO PARA EJECUTAR":
              resultado_cond = resultado_norm.in_([
                  "BLOQUEADO PARA EJECUTAR", "BLOQUEADO PARA EJECUCION",
                  "BLOQUEADO PARA EJECUTAR.", "BLOQUEADO",
              ])

  (e) ``_RESULTADOS_PIVOTE`` (constante, linea 180) y los comentarios de las
      lineas 174-179 y 707 se actualizan para reflejar el valor nuevo.
      NOTA: ``_RESULTADOS_PIVOTE`` esta MUERTA (un grep de todo el repo
      solo devuelve su definicion; el codigo vivo usa ``columnas_front``).
      Se actualiza igualmente para no dejar una constante que contradiga al
      catalogo.

  0.4 app/services/uat_import.py (importador UAT)

  (a) ``normalize_resultado``: deja de colapsar el valor.

      ANTES:
          if "BLOQUEADO" in s_up or "BLOQ" in s_up:
              return "DESESTIMADA"

      AHORA:
          if s_up in (
              "BLOQUEADO PARA EJECUTAR",
              "BLOQUEADO PARA EJECUCION",
              "BLOQUEADO PARA EJECUTAR.",
              "BLOQUEADO",
              "BLOQ",
          ):
              return "BLOQUEADO PARA EJECUTAR"

      El reconocimiento pasa a ser con lista EXPLICITA de variantes y no con
      un "in" difuso, para que una abreviatura como "BLOQ" no capture
      valores ajenos. El mapa ``mapping`` tambien suma la entrada canonica.

  (b) ``RESULTADO_A_ESTADO_NOMBRE`` suma el destino:

          "BLOQUEADO PARA EJECUTAR": "Bloqueado!",

      Ver seccion 3.2: la especificacion original pedia "Analisis/Bloqueado"
      y ese estado NO existe en el despliegue.

  0.5 tools/load_uat_consolidado.py

  Misma regla que 0.4(a) en el script de carga masiva. Sin este cambio, la
  siguiente carga UAT volveria a colapsar el valor a DESESTIMADA.

  0.6 tools/uat_mapping.py

  La documentacion de las reglas de normalizacion pasa de

      "BLOQUEADO PARA EJECUTAR"-> "DESESTIMADA"   (~ mismo significado)

  a

      "BLOQUEADO PARA EJECUTAR"-> "BLOQUEADO PARA EJECUTAR"  (V2.008: ya no
                                 se colapsa a "DESESTIMADA"; es una categoria
                                 propia del LOV con acronimo "BLOQ")

  Y se documenta, en TOTALES_ESPERADOS, por que NO se agrega un conteo para
  la categoria nueva: el consolidado de referencia NO trae filas con ese
  valor (la suma de "por_columna" = 130 + 10 + 635 + 18 + 84 + 0 = 877 ya
  es igual a "total_general" = 877, y no hay columna DESESTIMADA ni
  BLOQUEADO en los totales por modulo).

  0.7 app/models/ticket.py y app/schemas/ticket.py

  Solo comentarios. El conjunto de valores permitidos ya se derivaba del
  catalogo (``RESULTADO_PRUEBAS_LOV = RESULTADOS_LOV`` y
  ``RESULTADO_PRUEBAS_PERMITIDOS = frozenset(RESULTADOS_LOV) | {""}``), por
  lo que el validador de la API acepta el valor nuevo sin tocarlo.

  0.8 app/templates/dashboard/index.html

  Solo comentarios (el pie de la tabla y la lista de acronimos). NO se
  declara ninguna lista de valores ni de colores: el JS los lee del JSON
  que el servidor inyecta desde el catalogo (CUENTA_RESULTADO_LOV,
  CUENTA_RESULTADO_COLORES, CUENTA_RESULTADO_ACRONIMOS).

  0.9 app/services/ticket_service.py

  Solo un comentario. NO hay cambio de comportamiento (ver seccion 3.3).


1. BASE
================================================================================

  1.1 Punto de partida

  El LOV de Resultado de Pruebas tenia 6 valores canonicos mas la
  pseudo-columna derivada "(en blanco)":

      N/A, NOK, OK, OK CON OBS., POSTERGADA, DESESTIMADA

  El valor "BLOQUEADO PARA EJECUTAR" NO existia en el catalogo: era un
  valor de ORIGEN del Excel de UAT (hoja CONSOLIDADO UAT, columna L
  "Resultado") que se colapsaba a DESESTIMADA antes de tocar la base, en
  ``tools/uat_mapping.py`` y en ``app/services/uat_import.py``, con la
  justificacion "(~ mismo significado operativo)".

  1.2 Estado verificado del repositorio antes de tocar nada

  * Rama: main y release/v2.001 en 68478c5 (addendum 9 del lote V2.007).
  * Working tree limpio, sin cambios sin commitear.
  * Suite completa antes del lote: 227 passed, 0 failed (726,80 s).
  * Produccion: 3 servicios Railway en SUCCESS sobre 68478c5.
  * Catalogo: 6 valores + "(en blanco)", 7 colores distintos, 6 acronimos
    + "(en blanco)".

  1.3 Re-verificacion de la especificacion contra el codigo actual

  La especificacion de origen esta escrita contra el codigo de la era
  V1.002 (2026-10-24) y sus numeros de linea quedaron desfasados por los
  lotes V2.005, V2.006 y V2.007. Se re-verifico una por una:

  Ubicacion de la spec                En la spec   Real hoy   Estado
  ----------------------------------  -----------  ---------  -------------
  resultado_pruebas.py RESULTADOS_LOV   66-73      81-88      reubicado
  resultado_pruebas.py ACRONIMOS        86-94      127-135    reubicado
  resultado_pruebas.py COLORES         108-116     149-157    reubicado
  resultado_pruebas.py _ALIASES        130-154     171-195    reubicado
  resultado_pruebas.py normalizar()    157-190     198-231    reubicado
  ticket.py RESULTADO_PRUEBAS_LOV       71-78      70-74      YA DERIVADO
  schemas/ticket.py PERMITIDOS          43-52      44-47      YA DERIVADO
  metricas.py _RESULTADOS_PIVOTE        97-106     180-188    reubicado
  metricas.py columnas_front            619-621    721-724    reubicado
  dashboard/index.html const RESULTADOS  903        912-914    YA INYECTADO
  nuevo_modal.html select               ~199       199-201    YA INYECTADO
  detalle_modal.py select               ~350       361-363    YA INYECTADO

  Cuatro puntos de la lista cerrada de ficheros YA NO ERAN NECESARIOS porque
  el refactor del SSOT (commit ebbc87b, lote V1.001) los habia resuelto:
  el valor permitido, el valor del modelo, el selector de alta y el selector
  de edicion ya se derivan del catalogo. Se tocan solo los comentarios.


2. CAMBIO UNICO
================================================================================

  2.1 Que cambia

  "BLOQUEADO PARA EJECUTAR" deja de ser un valor de origen que se
  colapsaba a DESESTIMADA y pasa a ser una CATEGORIA PROPIA DEL LOV:

      valor canonico  BLOQUEADO PARA EJECUTAR
      acronimo        BLOQ
      color de fondo  #0891b2   (cian 600, propio: no reutiliza ninguno)
      color de texto  #ffffff
      color de celda  #1f2937
      tooltip         Resultado de pruebas: BLOQUEADO PARA EJECUTAR

  2.2 Que se ve

  * Dashboard, seccion "Cuenta de Resultado": aparece una columna nueva con
    el titulo BLOQ y el fondo cian, con su drill-down por celda.
  * Kanban: el badge de la tarjeta de un ticket con ese resultado muestra
    BLOQ sobre fondo cian (mismo color y mismo acronimo que la columna del
    dashboard, por construccion: ambos leen el mismo catalogo).
  * Selector de resultado de pruebas (alta y edicion de ticket): aparece la
    opcion BLOQUEADO PARA EJECUTAR.
  * La columna SOLO se dibuja si tiene al menos un ticket. Es el
    comportamiento vigente para todas las columnas y no se cambia.

  2.3 Lo que deja de pasar

  La proxima carga UAT ya no colapsa "BLOQUEADO PARA EJECUTAR" a
  "DESESTIMADA": el ticket queda con el valor canonico y con su columna
  propia en el pivote.


3. QUE NO SE MODIFICO
================================================================================

  3.1 Ni datos, ni esquema, ni logica

  * NO hay migracion de base de datos. ``tickets.resultado_pruebas`` es
    ``String(40)`` sin CHECK y "BLOQUEADO PARA EJECUTAR" tiene 23
    caracteres: entra sin tocar el esquema. NO se modifico
    ``app/db/migrations.py``.
  * NO hay backfill. Los tickets ya cargados con resultado_pruebas =
    'DESESTIMADA' que en realidad venian de "BLOQUEADO PARA EJECUTAR" son
    INDISTINGUIBLES: el dato original se perdio al colapsar. No se
    reprocesa nada y no se toca ningun dato existente.
  * NO se renombra ni se elimina DESESTIMADA, POSTERGADA ni ninguna
    categoria existente. Sus acronimos y sus colores no cambian
    (DESESTIMADA sigue siendo DESEST / #7c3aed).
  * NO se agregan ni se modifican estados del flujo.
  * NO cambia el porcentaje de aprobados del pie del dashboard: sigue
    siendo OK + OK CON OBS. La categoria nueva no cuenta como aprobacion.
  * NO cambia el calculo de fecha_cumplida / fecha_completado. En el flujo
    vivo las dispara el ESTADO del ticket (TicketService.cambiar_estado
    marca "produccion ok" -> fecha_completado / fecha_cumplida), no el
    valor del LOV; en el importador UAT las dispara resultado_pruebas ==
    'OK'. Ninguno de los dos caminos se toca.
  * NO cambia el KPI "Incidencias Abiertas" (incidencias.backlog_7d): sigue
    excluyendo solo los tickets con resultado DESESTIMADA. Una prueba
    bloqueada sigue en gestion y sigue contando como abierta. Es
    intencionado: no se agrega la categoria nueva a esa exclusion.
  * NO se toca el calculo de porcentaje_con_resultado (cualquier valor no
    vacio cuenta).
  * NO se tocan email_service.py ni
    notificacion_admin_resultado_pruebas_service.py: interpolan el valor
    tal cual y no filtran por el LOV. Auditados.
  * NO se redeclara la paleta ni el mapa de acronimos fuera del SSOT. Las
    plantillas siguen leyendo el JSON inyectado por el servidor.
  * NO se tocan requirements.txt ni el despliegue (no hay dependencias
    nuevas).
  * NO se edita ningun README anterior (V1.001, V1.002, V2.001..V2.007).

  3.2 Desviacion 1: el estado destino del valor nuevo

  La especificacion pedia mapear "BLOQUEADO PARA EJECUTAR" al estado
  "Analisis/Bloqueado" (el mismo que NOK) y, si ese estado no existia,
  insertarlo en app/db/migrations.py como "unica excepcion que si requiere
  cambio de esquema".

  Se verifico por GET /api/v1/estados en produccion (2026-11-12) que ese
  estado NO EXISTE. Los estados reales del despliegue son:

      BackLog (id=1, inicial)      Analisis (id=9, inicial)
      Bloqueado! (id=10, inicial)   En desarrollo (id=2)
      Entregado (id=3)              UAT-QA (id=8)
      APROBADO QA (id=4)            Despliegue PROD (id=7)
      produccion ok (id=5, final)   DESESTIMADA (id=6, final)

  Insertar un estado "Analisis/Bloqueado" habria creado en el Kanban una
  columna casi duplicada al lado de "Bloqueado!", que ya significa
  exactamente lo mismo, y habria exigido tocar el esquema y el tablero de
  un sistema en produccion. Por eso el valor nuevo se mapea al estado
  EXISTENTE:

      "BLOQUEADO PARA EJECUTAR": "Bloqueado!"

  Efecto practico identico al pedido (el ticket no cae en el estado
  inicial), sin cambiar el esquema ni el tablero. Si el negocio prefiere
  crear el estado "Analisis/Bloqueado", es una linea de este fichero y una
  entrada en migrations.py.

  HALLAZGO PREEXISTENTE, NO CORREGIDO EN ESTE LOTE: el mapeo de NOK apunta
  a "Analisis/Bloqueado", que tampoco existe, asi que
  lookup_estado_id_por_resultado cae silenciosamente al estado inicial
  (BackLog). Es un defecto anterior a V2.008 y queda documentado aqui
  para decision de negocio; no se modifica para no cambiar el
  comportamiento de la carga UAT existente.

  3.3 Desviacion 2: el auto-marcado a DESESTIMADA

  TicketService.cambiar_estado marca resultado_pruebas='DESESTIMADA' cuando
  el ticket cae en una columna "Cancelado"/"Desestimada" (salvo que ya
  fuera DESESTIMADA). Esa regla pisa TAMBIEN la categoria nueva.

  Se deja SIN CAMBIOS a proposito: si la prueba estaba bloqueada y el
  ticket se cancela o se desestima, el resultado pasa a DESESTIMADA porque
  la prueba no se ejecuto. Es la misma regla que aplica a cualquier valor
  distinto de DESESTIMADA. Se agrego un comentario en el codigo para que
  la decision quede explicita y no se lea como un defecto.

  3.4 Desviacion 3: un alias extra

  La especificacion enumeraba 5 entradas admitidas. Se agrego tambien
  "BLOQ" (el acronimo) como alias, porque el importador UAT ya lo aceptaba
  (por el "in" difuso que se elimino) y, al quitarlo, un "BLOQ" suelto
  habria quedado como valor fuera del LOV escrito en la base. Con el alias
  explicito, el catalogo y los importadores comparten una sola lista.

  3.5 Desviacion 4: numeracion del release

  La especificacion pedia "README_V1.002_<DESCRIPCION>_<FECHA>.txt". Ese
  correlativo YA ESTA OCUPADO por un release anterior y de otro tema
  (README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_
  2026-10-24.txt), y la serie viva del repositorio es la V2 (V1.006 fue el
  ultimo de V1). Este lote se publica como V2.008.


4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  4.1 Migracion de base de datos

  NINGUNA. No hay cambios de esquema ni de datos. ``app/db/migrations.py``
  no se toca.

  4.2 Cambiar el Worker

  NO requiere cambios de configuracion ni de codigo en el worker. El worker
  y el beat ejecutan el mismo codigo de la aplicacion, asi que se
  redespliegan con el mismo commit que el web para que los tres servicios
  queden alineados (es el procedimiento de los lotes anteriores).

  4.3 Variables de entorno

  NINGUNA nueva ni modificada.

  4.4 Orden de despliegue

  1) web    (autoDeploy desde 'main'; o despliegue manual con el commit)
  2) worker (mismo commit)
  3) beat   (mismo commit)

  4.5 Rollback

  Revertir el commit y redesplegar los tres servicios. No hay nada que
  deshacer en la base de datos.


5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 Verificacion automatizada (local, sin red)

      python -m pytest tests/test_v2008_lov_bloqueado_para_ejecutar.py -q
      python -m pytest tests/ -q

  Los 35 tests nuevos cubren: la presencia del valor en el catalogo, el
  acronimo, los colores (y que el color no reutiliza ninguno de los
  otros), las 7 variantes de entrada, la ficha completa (incluido el
  tooltip), el invariante de los dos ordenes, la derivacion del modelo y
  del esquema, las columnas del pivote, la clave en los totales, el
  guard que impide que un valor del catalogo se quede sin columna en el
  SQL del pivot, la creacion por API (201 y no 422), la aparicion del
  ticket en SU columna, el drill-down, el KPI de incidencias, el pie de
  aprobados, que la plantilla no redeclara el LOV y que los dos
  importadores UAT ya no colapsan el valor.

  5.2 Verificacion en produccion (solo GET y POST de login)

   #  Accion                                              Resultado esperado
   1  GET /api/v1/metricas/cuenta-resultado               "columnas" incluye
                                                          "BLOQUEADO PARA EJECUTAR"
                                                          justo antes de "(en blanco)"
   2  GET /api/v1/metricas/cuenta-resultado               "totales_por_columna"
                                                          incluye la clave nueva
                                                          en 0 (sin KeyError)
   3  GET /dashboard                                      el HTML no contiene
                                                          ninguna lista de valores
                                                          del LOV redeclarada
   4  GET /static/css/tailwind.css                        200 (sin cambios en
                                                          este lote)

  5.3 Verificacion visual (procedimiento del propietario)

   1) Crear (en un ticket propio) un ticket de tipo "Resultado Pruebas" con
      resultado "BLOQUEADO PARA EJECUTAR".
   2) Abrir /kanban: el badge de la tarjeta debe mostrar BLOQ con fondo
      rgb(8,145,178) y el tooltip "Resultado de pruebas: BLOQUEADO PARA
      EJECUTAR".
   3) Abrir /dashboard -> "Cuenta de Resultado": el encabezado de la
      columna debe mostrar BLOQ y el MISMO fondo que el badge de la
      tarjeta (comparar con getComputedStyle().backgroundColor).
   4) El pie de la tabla debe mostrar el mismo porcentaje de aprobados que
      antes de crear el ticket nuevo (la categoria nueva no cuenta como
      aprobacion; el total si crece, luego el porcentaje baja: es lo
      correcto).
   5) Abrir el detalle del ticket y cambiar el resultado: el selector debe
      ofrecer la opcion y quedar marcada.
   6) Comprobar que el KPI "Incidencias Abiertas" NO baja al crear el
      ticket: una prueba bloqueada sigue en gestion.


6. TRAZABILIDAD
================================================================================

  6.1 Origen de la especificacion

  Especificacion recibida el 2026-11-12 (pegada por el propietario), escrita
  contra el codigo de la era V1.002 (2026-10-24). Los 12 puntos de su
  procedimiento de prueba se verificaron uno a uno contra el codigo actual
  (ver seccion 5 y el informe de QA).

  6.2 Ficheros y su correspondencia con la especificacion

    Spec #  Fichero                                       Estado
    ------  --------------------------------------------  -----------------
      1     app/core/resultado_pruebas.py                 HECHO (5 bloques)
      2     app/models/ticket.py                          HECHO (solo comentario:
                                                         el LOV ya se derivaba)
      3     app/schemas/ticket.py                         HECHO (solo comentario:
                                                         el conjunto ya se derivaba)
      4     app/api/v1/metricas.py                        HECHO (columnas,
                                                         sql_columnas, drill-down)
      5     app/templates/dashboard/index.html            HECHO (solo comentarios:
                                                         la lista ya se inyectaba)
      6     app/templates/tickets/nuevo_modal.html        NO REQUERIDO (ya itera
                                                         el catalogo)
      7     app/templates/tickets/detalle_modal.py        NO REQUERIDO (ya itera
                                                         el catalogo)
      8     app/services/uat_import.py                    HECHO (normalizador +
                                                         mapa de estados)
      9     tools/load_uat_consolidado.py                 HECHO (normalizador)
     10     tools/uat_mapping.py                          HECHO (documentacion +
                                                         nota sobre totales)
     11     email_service.py /                            AUDITADO, sin cambios
            notificacion_admin_resultado_pruebas_         (interpolan el valor
            service.py / ticket_service.py                tal cual; en
                                                         ticket_service solo
                                                         un comentario)
     12     tests/                                        HECHO (fichero nuevo)

  6.3 Commit

  Se documenta en la seccion 9 (addendum de despliegue).

  6.4 Pruebas

  Suite completa: 227 passed antes del lote (726,80 s); despues del lote,
  **262 passed, 0 failed** (799,47 s / 13:19), es decir 227 + 35 tests
  nuevos. El detalle del despliegue queda en la seccion 9.


7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  7.1 Publicacion

      git checkout release/v2.001
      git add -A
      git commit -m "feat(resultado): nueva categoria BLOQUEADO PARA EJECUTAR en el LOV"
      git checkout main
      git merge --ff-only release/v2.001
      push de main y release/v2.001 (nunca --force)

  7.2 Despliegue

      python tmp_deploy_railway.py <commit> worker beat
      (el servicio 'web' se redespliega solo por autoDeploy desde 'main')

  7.3 Verificacion posterior

      GET /health
      GET /api/v1/metricas/cuenta-resultado   (columnas + totales)
      GET /dashboard
      revision de los 3 servicios en SUCCESS y alineados en el mismo commit

  7.4 Rollback

      Revertir el commit y redesplegar los tres servicios con el commit
      anterior (68478c5). No hay migracion que deshacer: el esquema y los
      datos no cambian en este lote.

      Si un ticket creado con el valor nuevo debe dejar de aceptarse, el
      rollback del codigo lo vuelve a rechazar (el validador deriva del
      catalogo), pero el dato ya guardado permanece: la columna nueva
      desaparece del pivote y sus tickets quedan fuera de las columnas
      (comportamiento silencioso, no destructivo).


================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================
diff --git a/app/api/v1/metricas.py b/app/api/v1/metricas.py
index 59b2385..cc25404 100644
--- a/app/api/v1/metricas.py
+++ b/app/api/v1/metricas.py
@@ -19,6 +19,7 @@ from app.core.resultado_pruebas import (
     ACRONIMOS as ACRONIMOS_RESULTADO,
     COLORES as COLORES_RESULTADO,
     COLOR_FALLBACK as COLOR_FALLBACK_RESULTADO,
+    RESULTADOS_CONOCIDOS as RESULTADOS_CONOCIDOS_RESULTADO,
     SIN_RESULTADO as SIN_RESULTADO,
     normalizar_resultado as _normalizar_resultado,
 )
@@ -172,11 +173,12 @@ def _resolver_rango_temporal(periodo_dias, fecha_desde, fecha_hasta, ahora):
 # Replica del rango A64:H81 de la hoja REPORTE del Excel UAT.
 #
 # NOTA: Incluye TODOS los valores del LOV de ``resultado_pruebas``
-# (N/A, NOK, OK, OK CON OBS., POSTERGADA, DESESTIMADA) mas la
-# categoria derivada "(en blanco)" para valores NULL/vacios. Si
-# el LOV crece en el futuro, basta con agregar el nuevo valor aqui
-# y darlo de alta en ``sql_columnas`` mas abajo para que el pivot
-# lo refleje sin perder tickets.
+# (N/A, NOK, OK, OK CON OBS., POSTERGADA, DESESTIMADA, BLOQUEADO PARA
+# EJECUTAR) mas la categoria derivada "(en blanco)" para valores
+# NULL/vacios. Si el LOV crece en el futuro, basta con agregar el nuevo
+# valor en ``app/core/resultado_pruebas.py`` (SSOT) y darlo de alta en
+# ``sql_columnas`` mas abajo para que el pivot lo refleje sin perder
+# tickets.
 _RESULTADOS_PIVOTE = (
     "N/A",
     "NOK",
@@ -184,6 +186,7 @@ _RESULTADOS_PIVOTE = (
     "OK CON OBS.",
     "POSTERGADA",
     "DESESTIMADA",
+    "BLOQUEADO PARA EJECUTAR",
     "",  # (en blanco) -- sin resultado
 )
 
@@ -704,7 +707,7 @@ def cuenta_resultado(
     con la forma exacta esperada por el componente del dashboard:
       {
         "ambiente": "QA",
-        "columnas": ["N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA", "(en blanco)"],
+        "columnas": ["N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA", "BLOQUEADO PARA EJECUTAR", "(en blanco)"],
         "filas": [
           {"modulo": "Auditoria", "valores": {"N/A": 1, "NOK": 0, ...}, "total": 9},
           ...
@@ -718,10 +721,12 @@ def cuenta_resultado(
     # Columnas dinamicas: mismas que el front (incluye "(en blanco)" para
     # agrupar NULL/vacios en resultado_pruebas). DESESTIMADA se incluye
     # explicitamente para que esos tickets NO queden excluidos del pivot.
-    columnas_front = [
-        "N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA",
-        "(en blanco)",
-    ]
+    #
+    # La lista se DERIVA del catalogo (app/core/resultado_pruebas.py), que es
+    # la unica fuente de verdad del LOV, y no se redeclara aqui: asi el pivote
+    # y el front (que consume CUENTA_RESULTADO_LOV, inyectada desde el mismo
+    # catalogo) no pueden desalinearse al crecer el LOV (V2.008).
+    columnas_front = list(RESULTADOS_CONOCIDOS_RESULTADO)
 
     def _eq_ci(*literales):
         """SQL case-insensitive y tolerante a espacios."""
@@ -742,6 +747,13 @@ def cuenta_resultado(
             "POSTERGADA A GARANTIA", "POSTERGADO",
         )),
         ("DESESTIMADA", _eq_ci("DESESTIMADA", "DESESTIMADO")),
+        # Categoria propia (V2.008). Acepta las variantes de entrada que
+        # normaliza el catalogo: la canonica, la variante sin tilde, la
+        # variante con punto final y la forma abreviada.
+        ("BLOQUEADO PARA EJECUTAR", _eq_ci(
+            "BLOQUEADO PARA EJECUTAR", "BLOQUEADO PARA EJECUCION",
+            "BLOQUEADO PARA EJECUTAR.", "BLOQUEADO",
+        )),
         ("(en blanco)", Ticket.resultado_pruebas.is_(None) | (func.trim(Ticket.resultado_pruebas) == "")),
     ]
 
@@ -925,6 +937,13 @@ def cuenta_resultado_detalle(
         ])
     elif resultado_filtro.upper() == "DESESTIMADA":
         resultado_cond = resultado_norm.in_(["DESESTIMADA", "DESESTIMADO"])
+    elif resultado_filtro.upper() == "BLOQUEADO PARA EJECUTAR":
+        # Categoria propia (V2.008): se aceptan las mismas variantes que
+        # normaliza el catalogo (app/core/resultado_pruebas.py).
+        resultado_cond = resultado_norm.in_([
+            "BLOQUEADO PARA EJECUTAR", "BLOQUEADO PARA EJECUCION",
+            "BLOQUEADO PARA EJECUTAR.", "BLOQUEADO",
+        ])
     else:
         resultado_cond = func.upper(func.trim(Ticket.resultado_pruebas)) == resultado_filtro.upper()
 
diff --git a/app/core/resultado_pruebas.py b/app/core/resultado_pruebas.py
index 6818ba9..81616db 100644
--- a/app/core/resultado_pruebas.py
+++ b/app/core/resultado_pruebas.py
@@ -33,18 +33,19 @@ Resultado* deben usar los mismos colores". Con este modulo:
 
 Ambos caminos consumen, por construccion, la misma paleta.
 
-Acronimos (mapeo 1:1 con las 6 categorias solicitadas)
--------------------------------------------------------
-===================  ===========  =========================
-Valor del LOV        Acronimo     Categoria solicitada
-===================  ===========  =========================
-``OK``               ``OK``       OK
-``N/A``              ``N/A``      N/A
-``OK CON OBS.``      ``OBS``      OBS
-``POSTERGADA``       ``POST``     POST
-``DESESTIMADA``      ``DESEST``   DESEST
-``NOK``              ``NOK``      NOK
-===================  ===========  =========================
+Acronimos (mapeo 1:1 con las 7 categorias solicitadas)
+---------------------------------------------------------
+=============================  ===========  =========================
+Valor del LOV                 Acronimo     Categoria solicitada
+=============================  ===========  =========================
+``OK``                        ``OK``       OK
+``N/A``                       ``N/A``      N/A
+``OK CON OBS.``               ``OBS``      OBS
+``POSTERGADA``                ``POST``     POST
+``DESESTIMADA``               ``DESEST``   DESEST
+``NOK``                       ``NOK``      NOK
+``BLOQUEADO PARA EJECUTAR``   ``BLOQ``     BLOQ
+=============================  ===========  =========================
 
 ``(en blanco)`` es la pseudo-columna que agrupa tickets con
 ``resultado_pruebas`` NULL o vacio en la tabla pivote del dashboard; su
@@ -64,6 +65,38 @@ El cambio es **solo de presentacion**: no se toca el valor del LOV
 en el pivote, ni los parametros del drill-down. Por construccion, el
 titulo de la columna y el badge de la tarjeta del Kanban muestran el
 mismo acronimo.
+
+Por que existe la categoria BLOQUEADO PARA EJECUTAR (V2.008)
+-------------------------------------------------------------
+El consolidado UAT traia el valor de origen ``BLOQUEADO PARA EJECUTAR``
+(hoja CONSOLIDADO UAT, columna L "Resultado"), que **no** era un valor del
+LOV: hasta V2.007 se colapsaba a ``DESESTIMADA`` antes de tocar la base
+(``tools/uat_mapping.py`` y ``app/services/uat_import.py``), por considerarlo
+"~ mismo significado operativo".
+
+A partir de V2.008 es una **categoria de primer nivel** del LOV:
+
+* ``BLOQUEADO PARA EJECUTAR`` -> acronimo ``BLOQ``, color propio
+  (``#0891b2``, cian 600) que no reutiliza ninguno de los otros siete.
+* **No** cuenta como aprobacion: el porcentaje de aprobados del pie del
+  dashboard (OK + OK CON OBS.) no cambia y **no** se toca la logica de
+  ``fecha_cumplida`` / ``fecha_completado``.
+  Ojo con el alcance real de esa logica: en el flujo vivo de la aplicacion
+  esas fechas las dispara el **estado** del ticket (``TicketService.
+  cambiar_estado`` marca ``produccion ok`` -> ``fecha_completado`` /
+  ``fecha_cumplida``), no el valor del LOV. El unico punto donde
+  ``resultado_pruebas == 'OK'`` gobierna esas fechas es el importador UAT
+  (``app/services/uat_import.py``). Ninguno de los dos caminos se modifica
+  en V2.008: la categoria nueva no dispara ninguna fecha.
+* No se renombra ni se elimina ``DESESTIMADA``: siguen siendo categorias
+  distintas.
+* Entra al pivote "Cuenta de Resultado" como columna propia, con el mismo
+  orden en el pivote y en el front (la columna solo se dibuja si tiene al
+  menos un ticket, como todas las demas).
+
+Los alias de entrada (``_ALIASES``) aceptan la forma canonica, la variante
+sin tilde (``BLOQUEADO PARA EJECUCION``), la variante con punto final y la
+forma abreviada ``BLOQUEADO``.
 """
 
 from __future__ import annotations
@@ -85,6 +118,7 @@ RESULTADOS_LOV: tuple = (
     "OK CON OBS.",
     "POSTERGADA",
     "DESESTIMADA",
+    "BLOQUEADO PARA EJECUTAR",
 )
 
 #: Pseudo-columna del dashboard que agrupa NULL / vacio / desconocidos.
@@ -107,6 +141,7 @@ RESULTADOS_LOV_FORMULARIO: tuple = (
     "POSTERGADA",
     "DESESTIMADA",
     "NOK",
+    "BLOQUEADO PARA EJECUTAR",
 )
 
 #: Invariante del catalogo: los dos ordenes deben describir exactamente el
@@ -131,6 +166,7 @@ ACRONIMOS: Dict[str, str] = {
     "POSTERGADA": "POST",
     "DESESTIMADA": "DESEST",
     "NOK": "NOK",
+    "BLOQUEADO PARA EJECUTAR": "BLOQ",
     SIN_RESULTADO: "S/D",
 }
 
@@ -153,6 +189,10 @@ COLORES: Dict[str, Dict[str, str]] = {
     "OK CON OBS.": {"bg": "#eab308", "text": "#1f2937", "cellText": "#1f2937"},
     "POSTERGADA":  {"bg": "#ea580c", "text": "#ffffff", "cellText": "#1f2937"},
     "DESESTIMADA": {"bg": "#7c3aed", "text": "#ffffff", "cellText": "#1f2937"},
+    # Cian 600. Color propio de la categoria: no reutiliza ninguno de los
+    # otros seis (V2.008).
+    "BLOQUEADO PARA EJECUTAR": {"bg": "#0891b2", "text": "#ffffff",
+                                 "cellText": "#1f2937"},
     SIN_RESULTADO: {"bg": "#cbd5e1", "text": "#475569", "cellText": "#1f2937"},
 }
 
@@ -190,6 +230,19 @@ _ALIASES: Dict[str, str] = {
     "postergado": "POSTERGADA",
     "desestimada": "DESESTIMADA",
     "desestimado": "DESESTIMADA",
+    # Categoria BLOQUEADO PARA EJECUTAR (V2.008). Se declaran de forma
+    # explicita (y no solo por el fallback "compacto" de
+    # ``normalizar_resultado``) para que el comportamiento sea legible y no
+    # dependa del orden de insercion de este diccionario.
+    "bloqueado para ejecutar": "BLOQUEADO PARA EJECUTAR",
+    "bloqueado para ejecucion": "BLOQUEADO PARA EJECUTAR",
+    "bloqueado para ejecutar.": "BLOQUEADO PARA EJECUTAR",
+    "bloqueado": "BLOQUEADO PARA EJECUTAR",
+    # El acronimo que se muestra en el badge tambien se acepta como entrada
+    # (venia haciendolo el importador UAT, que resolvia "BLOQ" por
+    # similitud). Se declara aqui para que el catalogo y los importadores
+    # UAT compartan una sola lista de alias.
+    "bloq": "BLOQUEADO PARA EJECUTAR",
     "(en blanco)": SIN_RESULTADO,
     "": SIN_RESULTADO,
 }
diff --git a/app/models/ticket.py b/app/models/ticket.py
index b8a4e5a..f7daeeb 100644
--- a/app/models/ticket.py
+++ b/app/models/ticket.py
@@ -196,7 +196,8 @@ class Ticket(Base, TimestampMixin):
     # Nota u observacion libre del agente o solicitante
     nota_observacion = Column(Text, nullable=True)
     # Resultado de pruebas
-    # (LOV: OK, N/A, OK CON OBS., POSTERGADA, DESESTIMADA, NOK)
+    # (LOV: OK, N/A, OK CON OBS., POSTERGADA, DESESTIMADA, NOK,
+    #       BLOQUEADO PARA EJECUTAR)
     resultado_pruebas = Column(String(40), nullable=True, index=True)
 
     # === QA Tester asignado ===
diff --git a/app/schemas/ticket.py b/app/schemas/ticket.py
index b64663a..05bff12 100644
--- a/app/schemas/ticket.py
+++ b/app/schemas/ticket.py
@@ -191,7 +191,10 @@ class TicketBase(BaseModel):
     )
     resultado_pruebas: Optional[str] = Field(
         default=None, max_length=40,
-        description="Resultado de pruebas (LOV: OK, N/A, OK CON OBS., POSTERGADA, DESESTIMADA, NOK)",
+        description=(
+            "Resultado de pruebas (LOV: OK, N/A, OK CON OBS., POSTERGADA, "
+            "DESESTIMADA, NOK, BLOQUEADO PARA EJECUTAR)"
+        ),
     )
     # QA Tester asignado al ticket. Se almacena como texto canonico
     # ``"Nombre <email>"`` para garantizar trazabilidad.
diff --git a/app/services/ticket_service.py b/app/services/ticket_service.py
index 7b34d6a..ebf5227 100644
--- a/app/services/ticket_service.py
+++ b/app/services/ticket_service.py
@@ -267,6 +267,13 @@ class TicketService:
             #      Solo se aplica cuando REALMENTE hubo cambio de estado
             #      para no pisar valores editados manualmente cuando el
             #      usuario reordena dentro de la misma columna.
+            #
+            #      V2.008: esta regla pisa TAMBIEN la categoria "BLOQUEADO
+            #      PARA EJECUTAR" (y a cualquier otro valor distinto de
+            #      DESESTIMADA). Es intencionado: si la prueba estaba
+            #      bloqueada y el ticket se cancela o se desestima, el
+            #      resultado pasa a DESESTIMADA, porque la prueba no se
+            #      ejecuto. No se exceptua la categoria nueva.
             nombre_destino_norm = _norm(estado_destino.nombre)
             if nombre_destino_norm in ("cancelado", "desestimada", "desestimado"):
                 if ticket.resultado_pruebas != "DESESTIMADA":
diff --git a/app/services/uat_import.py b/app/services/uat_import.py
index 57bf4fb..d9f51cb 100644
--- a/app/services/uat_import.py
+++ b/app/services/uat_import.py
@@ -142,8 +142,19 @@ def normalize_resultado(v: Any) -> Optional[str]:
     s_up = s.upper()
     if "POSTERGADA" in s_up or "POSTERG" in s_up:
         return "POSTERGADA"
-    if "BLOQUEADO" in s_up or "BLOQ" in s_up:
-        return "DESESTIMADA"
+    # "BLOQUEADO PARA EJECUTAR" es una categoria PROPIA del LOV desde
+    # V2.008: antes se colapsaba a DESESTIMADA por considerarlo "~ mismo
+    # significado operativo". El reconocimiento se hace con una lista
+    # EXPLICITA de variantes y no con un "in" difuso, para que una
+    # abreviatura como "BLOQ" no capture valores ajenos.
+    if s_up in (
+        "BLOQUEADO PARA EJECUTAR",
+        "BLOQUEADO PARA EJECUCION",
+        "BLOQUEADO PARA EJECUTAR.",
+        "BLOQUEADO",
+        "BLOQ",
+    ):
+        return "BLOQUEADO PARA EJECUTAR"
     mapping = {
         "OK": "OK",
         "NOK": "NOK",
@@ -152,6 +163,7 @@ def normalize_resultado(v: Any) -> Optional[str]:
         "OK CON OBS": "OK CON OBS.",
         "OK CON OBSERVACIONES": "OK CON OBS.",
         "DESESTIMADA": "DESESTIMADA",
+        "BLOQUEADO PARA EJECUTAR": "BLOQUEADO PARA EJECUTAR",
     }
     return mapping.get(s_up) or mapping.get(s) or s
 
@@ -272,13 +284,27 @@ def lookup_tablero_default(db: Session) -> Optional[int]:
 #   OK CON OBS.  -> APROBADO QA
 #   POSTERGADA   -> BackLog
 #   NOK          -> Analisis/Bloqueado
+#   BLOQUEADO PARA EJECUTAR -> Bloqueado!   (V2.008)
 #   (en blanco)  -> BackLog   (default = estado inicial)
+#
+# NOTA (V2.008) sobre "BLOQUEADO PARA EJECUTAR": la especificacion original
+# pedia mapearlo a "Analisis/Bloqueado", pero ese estado **no existe** en el
+# despliegue (verificado por GET /api/v1/estados en produccion: los estados
+# reales son BackLog, Analisis, Bloqueado!, En desarrollo, Entregado, UAT-QA,
+# APROBADO QA, Despliegue PROD, produccion ok y DESESTIMADA). Insertar un
+# estado nuevo habria creado una columna casi duplicada del Kanban al lado
+# de "Bloqueado!", que ya significa exactamente lo mismo. Se mapea al estado
+# EXISTENTE "Bloqueado!" para no alterar el esquema ni el tablero en
+# produccion. La discrepancia preexistente de "NOK" -> "Analisis/Bloqueado"
+# (que cae silenciosamente al estado inicial) NO se modifica en este lote:
+# queda documentada como pendiente de decision de negocio.
 RESULTADO_A_ESTADO_NOMBRE = {
     "N/A":         "Cancelado",
     "OK":          "produccion ok",
     "OK CON OBS.": "APROBADO QA",
     "POSTERGADA":  "BackLog",
     "NOK":         "Analisis/Bloqueado",
+    "BLOQUEADO PARA EJECUTAR": "Bloqueado!",
 }
 
 
diff --git a/app/templates/dashboard/index.html b/app/templates/dashboard/index.html
index fd31fd4..f22b08c 100644
--- a/app/templates/dashboard/index.html
+++ b/app/templates/dashboard/index.html
@@ -247,6 +247,7 @@
         <p id="cuenta-resultado-footer"
            class="hidden mt-2 text-[10px] text-slate-400 italic">
           POSTERGADA = normalizacion del valor original "POSTERGADA A GARANTIA" (migracion UAT).
+          BLOQUEADO PARA EJECUTAR = categoria propia del LOV (V2.008, acronimo BLOQ); ya no se colapsa a DESESTIMADA.
         </p>
         {# ------------------------------------------------------------
            Paleta y acronimos de "Resultado de Pruebas" inyectados desde
@@ -1355,7 +1356,8 @@
   })();
 
   // Acronimos del LOV: "OK"->OK, "N/A"->N/A, "OK CON OBS."->OBS,
-  // "POSTERGADA"->POST, "DESESTIMADA"->DESEST, "NOK"->NOK, "(en blanco)"->S/D.
+  // "POSTERGADA"->POST, "DESESTIMADA"->DESEST, "NOK"->NOK,
+  // "BLOQUEADO PARA EJECUTAR"->BLOQ, "(en blanco)"->S/D.
   const CUENTA_RESULTADO_ACRONIMOS = (function () {
     const el = document.getElementById('cuenta-resultado-acronimos');
     if (!el) return {};
diff --git a/tests/test_v2008_lov_bloqueado_para_ejecutar.py b/tests/test_v2008_lov_bloqueado_para_ejecutar.py
new file mode 100644
index 0000000..0390f7f
--- /dev/null
+++ b/tests/test_v2008_lov_bloqueado_para_ejecutar.py
@@ -0,0 +1,524 @@
+"""
+Regresiones de V2.008: "BLOQUEADO PARA EJECUTAR" pasa a ser una categoria
+propia del LOV de Resultado de Pruebas.
+
+Contexto del cambio
+-------------------
+El consolidado UAT traia el valor de origen ``BLOQUEADO PARA EJECUTAR``
+(hoja CONSOLIDADO UAT, columna L "Resultado"), que **no** era un valor del
+LOV: hasta V2.007 se colapsaba a ``DESESTIMADA`` antes de tocar la base
+(``tools/uat_mapping.py`` y ``app/services/uat_import.py``), por
+considerarlo "~ mismo significado operativo".
+
+A partir de V2.008 es una categoria de primer nivel:
+
+  * valor canonico: ``BLOQUEADO PARA EJECUTAR``
+  * acronimo:       ``BLOQ``
+  * color propio:   ``#0891b2`` (cian 600), que no reutiliza ninguno de los
+    otros siete colores del catalogo
+  * tooltip:        ``Resultado de pruebas: BLOQUEADO PARA EJECUTAR``
+
+Reglas de negocio que el lote NO cambia:
+
+  * NO cuenta como aprobacion: el porcentaje de aprobados del pie del
+    dashboard (OK + OK CON OBS.) no cambia.
+  * NO se renombra ni se elimina ``DESESTIMADA``.
+  * NO se agregan ni modifican estados del flujo.
+  * NO se cambia el calculo de ``fecha_cumplida`` / ``fecha_completado``.
+  * NO se hace backfill: los tickets ya cargados con ``DESESTIMADA`` que
+    venian de "BLOQUEADO PARA EJECUTAR" son indistinguibles.
+
+Todos los tests operan sobre la base SQLite temporal de la suite (ver
+``tests/conftest.py``): nunca leen ni escriben en la base de datos de
+produccion.
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
+PLANTILLA_DASHBOARD = RAIZ / "app" / "templates" / "dashboard" / "index.html"
+FUENTE_METRICAS = RAIZ / "app" / "api" / "v1" / "metricas.py"
+FUENTE_UAT_IMPORT = RAIZ / "app" / "services" / "uat_import.py"
+FUENTE_UAT_MAPPING = RAIZ / "tools" / "uat_mapping.py"
+FUENTE_LOAD_UAT = RAIZ / "tools" / "load_uat_consolidado.py"
+
+CLAVE = "Clave-local-de-regresion-2026"
+
+#: Valor canonico de la categoria nueva.
+VALOR = "BLOQUEADO PARA EJECUTAR"
+#: Acronimo que se muestra en el badge de la tarjeta y en el titulo de la
+#: columna del pivote.
+ACRONIMO = "BLOQ"
+#: Color propio de la categoria (cian 600).
+COLOR = {"bg": "#0891b2", "text": "#ffffff", "cellText": "#1f2937"}
+
+#: Valores del LOV que EXISTIAN antes de este lote y no deben cambiar.
+LOV_PREVIO = ("N/A", "NOK", "OK", "OK CON OBS.", "POSTERGADA", "DESESTIMADA")
+#: Acronimos vigentes de esos valores (no deben cambiar).
+ACRONIMOS_PREVIOS = {
+    "OK": "OK",
+    "N/A": "N/A",
+    "OK CON OBS.": "OBS",
+    "POSTERGADA": "POST",
+    "DESESTIMADA": "DESEST",
+    "NOK": "NOK",
+}
+#: Colores vigentes de esos valores (no deben cambiar).
+COLORES_PREVIOS = {
+    "N/A": "#94a3b8",
+    "NOK": "#dc2626",
+    "OK": "#16a34a",
+    "OK CON OBS.": "#eab308",
+    "POSTERGADA": "#ea580c",
+    "DESESTIMADA": "#7c3aed",
+    "(en blanco)": "#cbd5e1",
+}
+
+#: Variantes de entrada que deben normalizarse al valor canonico.
+VARIANTES = (
+    "BLOQUEADO PARA EJECUTAR",
+    "bloqueado para ejecutar",
+    "BLOQUEADO PARA EJECUCION",
+    "BLOQUEADO PARA EJECUTAR.",
+    "BLOQUEADO",
+    "bloqueado",
+    "  Bloqueado Para Ejecutar  ",
+)
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
+    username = "v2008_admin_bloq"
+    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
+    if usuario is None:
+        usuario = Usuario(
+            username=username,
+            email=f"{username}@example.test",
+            nombre_completo="Admin V2008",
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
+@pytest.fixture
+def estado_inicial(db_session, admin_con_sesion):
+    """Un estado inicial valido para poder crear tickets."""
+    from app.models.estado import Estado
+
+    estado = (
+        db_session.query(Estado)
+        .filter(Estado.es_inicial == True)  # noqa: E712
+        .first()
+    )
+    if estado is None:
+        estado = Estado(
+            nombre="V2008 Inicial", color="#3b82f6", orden=1, es_inicial=True
+        )
+        db_session.add(estado)
+        db_session.commit()
+        db_session.refresh(estado)
+    return estado
+
+
+def _crear_ticket_con_resultado(local_client, resultado, titulo, modulo="Incidencias"):
+    """Crea un ticket real por la API JSON y devuelve el cuerpo de respuesta."""
+    datos = {
+        "titulo": titulo,
+        "descripcion": "Ticket creado por la suite de regresion de V2.008.",
+        "tipo": "resultado_pruebas",
+        "prioridad": "media",
+        "modulo": modulo,
+        "ambiente": "QA",
+        "resultado_pruebas": resultado,
+        "hu_o_caso_prueba": "V2008_SC_1",
+    }
+    return local_client.post("/api/v1/tickets", json=datos)
+
+
+# ---------------------------------------------------------------------------
+# 1. El catalogo (SSOT)
+# ---------------------------------------------------------------------------
+def test_el_lov_incluye_la_categoria_nueva():
+    """``RESULTADOS_LOV`` contiene el valor canonico."""
+    from app.core.resultado_pruebas import RESULTADOS_LOV
+
+    assert VALOR in RESULTADOS_LOV
+
+
+def test_la_categoria_nueva_vale_23_caracteres_y_cabe_en_la_columna():
+    """``resultado_pruebas`` es ``VARCHAR(40)``: no hace falta migracion."""
+    from app.models.ticket import Ticket
+
+    assert len(VALOR) == 23
+    assert Ticket.resultado_pruebas.type.length >= len(VALOR)
+
+
+def test_el_lov_de_formulario_incluye_la_categoria_nueva():
+    """``RESULTADOS_LOV_FORMULARIO`` (selector de alta/edicion) la incluye."""
+    from app.core.resultado_pruebas import RESULTADOS_LOV_FORMULARIO
+
+    assert VALOR in RESULTADOS_LOV_FORMULARIO
+
+
+def test_los_dos_ordenes_describen_el_mismo_conjunto():
+    """Invariante del catalogo: los dos ordenes son el mismo conjunto."""
+    from app.core.resultado_pruebas import (
+        RESULTADOS_LOV,
+        RESULTADOS_LOV_FORMULARIO,
+    )
+
+    assert set(RESULTADOS_LOV_FORMULARIO) == set(RESULTADOS_LOV)
+
+
+def test_el_acronimo_de_la_categoria_nueva_es_bloq():
+    """``ACRONIMOS["BLOQUEADO PARA EJECUTAR"]`` debe ser ``"BLOQ"``."""
+    from app.core.resultado_pruebas import ACRONIMOS
+
+    assert ACRONIMOS[VALOR] == ACRONIMO
+
+
+def test_los_colores_de_la_categoria_nueva_son_los_especificados():
+    """La paleta de la categoria nueva es la de la especificacion."""
+    from app.core.resultado_pruebas import COLORES
+
+    assert COLORES[VALOR] == COLOR
+
+
+def test_el_color_propio_no_reutiliza_ninguno_de_los_existentes():
+    """El cian 600 no puede ser el fondo de otra categoria."""
+    from app.core.resultado_pruebas import COLORES
+
+    fondos = [c["bg"] for c in COLORES.values()]
+    assert len(fondos) == len(set(fondos)), "hay colores de fondo repetidos"
+    assert COLOR["bg"] not in COLORES_PREVIOS.values()
+
+
+def test_el_resto_del_lov_no_cambia():
+    """Los seis valores previos conservan valor, acronimo y color."""
+    from app.core.resultado_pruebas import ACRONIMOS, COLORES
+
+    for valor, acronimo in ACRONIMOS_PREVIOS.items():
+        assert ACRONIMOS[valor] == acronimo, valor
+    for valor, bg in COLORES_PREVIOS.items():
+        assert COLORES[valor]["bg"] == bg, valor
+
+
+@pytest.mark.parametrize("variante", VARIANTES)
+def test_normalizar_resultado_acepta_las_variantes_de_entrada(variante):
+    """``normalizar_resultado`` canonicaliza todas las variantes de entrada."""
+    from app.core.resultado_pruebas import normalizar_resultado
+
+    assert normalizar_resultado(variante) == VALOR
+
+
+def test_normalizar_resultado_ya_no_colapsa_a_desestimada():
+    """Punto 9 de la especificacion: el valor ya no se colapsa."""
+    from app.core.resultado_pruebas import normalizar_resultado
+
+    assert normalizar_resultado(VALOR) == VALOR
+    assert normalizar_resultado(VALOR) != "DESESTIMADA"
+
+
+def test_info_resultado_devuelve_la_ficha_de_la_categoria_nueva():
+    """Punto 8: acronimo, colores y tooltip de la categoria nueva."""
+    from app.core.resultado_pruebas import info_resultado
+
+    ficha = info_resultado(VALOR)
+    assert ficha is not None
+    assert ficha["valor"] == VALOR
+    assert ficha["acronimo"] == ACRONIMO
+    assert ficha["bg"] == COLOR["bg"]
+    assert ficha["text"] == COLOR["text"]
+    assert ficha["cellText"] == COLOR["cellText"]
+    assert ficha["titulo"] == "Resultado de pruebas: BLOQUEADO PARA EJECUTAR"
+
+
+def test_lov_js_incluye_la_categoria_antes_del_en_blanco():
+    """El JS del dashboard consume esta lista: la categoria va antes de la
+    pseudo-columna ``(en blanco)``."""
+    from app.core.resultado_pruebas import RESULTADOS_CONOCIDOS, lov_js
+
+    columnas = lov_js()
+    assert VALOR in columnas
+    assert columnas.index(VALOR) < columnas.index("(en blanco)")
+    assert columnas == list(RESULTADOS_CONOCIDOS)
+
+
+def test_el_modelo_reexporta_el_lov_del_catalogo():
+    """``app.models.ticket.RESULTADO_PRUEBAS_LOV`` no redeclara la lista."""
+    from app.core.resultado_pruebas import RESULTADOS_LOV
+    from app.models.ticket import RESULTADO_PRUEBAS_LOV
+
+    assert RESULTADO_PRUEBAS_LOV == RESULTADOS_LOV
+    assert VALOR in RESULTADO_PRUEBAS_LOV
+
+
+def test_el_schema_permite_el_valor_nuevo():
+    """El validador de la API acepta el valor (si no, responderia 422)."""
+    from app.schemas.ticket import RESULTADO_PRUEBAS_PERMITIDOS
+
+    assert VALOR in RESULTADO_PRUEBAS_PERMITIDOS
+
+
+# ---------------------------------------------------------------------------
+# 2. El pivote "Cuenta de Resultado"
+# ---------------------------------------------------------------------------
+def test_las_columnas_del_pivote_incluyen_la_categoria_antes_del_en_blanco(
+    local_client, admin_con_sesion
+):
+    """Punto 1: la columna existe en la respuesta del pivote."""
+    respuesta = local_client.get("/api/v1/metricas/cuenta-resultado")
+    assert respuesta.status_code == 200, respuesta.text
+
+    columnas = respuesta.json()["columnas"]
+    assert VALOR in columnas
+    assert columnas.index(VALOR) < columnas.index("(en blanco)")
+
+
+def test_totales_por_columna_incluye_la_clave_nueva(local_client, admin_con_sesion):
+    """Punto 2: la clave existe en los totales (si no, habria KeyError)."""
+    respuesta = local_client.get("/api/v1/metricas/cuenta-resultado")
+    assert respuesta.status_code == 200, respuesta.text
+
+    cuerpo = respuesta.json()
+    assert VALOR in cuerpo["totales_por_columna"]
+    assert cuerpo["totales_por_columna"][VALOR] >= 0
+
+
+def test_las_columnas_del_pivote_coinciden_con_el_catalogo(
+    local_client, admin_con_sesion
+):
+    """El pivote y el front no pueden desalinearse: misma lista y orden."""
+    from app.core.resultado_pruebas import RESULTADOS_CONOCIDOS
+
+    respuesta = local_client.get("/api/v1/metricas/cuenta-resultado")
+    assert respuesta.status_code == 200, respuesta.text
+
+    assert respuesta.json()["columnas"] == list(RESULTADOS_CONOCIDOS)
+
+
+def test_cada_valor_del_lov_tiene_columna_en_el_sql_del_pivote():
+    """Guarda contra la perdida silenciosa de tickets en el pivote.
+
+    Si un valor esta en el catalogo pero no en ``sql_columnas``, sus tickets
+    no caen en ninguna columna (ni siquiera en "(en blanco)", que solo
+    agrupa NULL/vacio) y desaparecen del reporte sin error.
+    """
+    fuente = FUENTE_METRICAS.read_text(encoding="utf-8")
+    from app.core.resultado_pruebas import RESULTADOS_LOV
+
+    bloque = re.search(
+        r"sql_columnas\s*=\s*\[(.*?)\n    \]", fuente, re.S
+    )
+    assert bloque, "no se encontro el bloque sql_columnas"
+    cuerpo = bloque.group(1)
+    for valor in RESULTADOS_LOV:
+        assert '("%s"' % valor in cuerpo, (
+            "el valor %r del LOV no tiene columna en sql_columnas: sus "
+            "tickets se perderian en silencio del pivote" % valor
+        )
+
+
+# ---------------------------------------------------------------------------
+# 3. La API
+# ---------------------------------------------------------------------------
+def test_la_api_acepta_el_valor_nuevo(local_client, admin_con_sesion, estado_inicial):
+    """Punto 3: crear un ticket con el valor nuevo NO devuelve 422."""
+    respuesta = _crear_ticket_con_resultado(
+        local_client, VALOR, "V2008 API acepta BLOQUEADO PARA EJECUTAR"
+    )
+    assert respuesta.status_code in (200, 201), respuesta.text
+    assert respuesta.json()["resultado_pruebas"] == VALOR
+
+
+def test_la_api_rechaza_un_valor_inexistente(local_client, admin_con_sesion):
+    """El validador sigue rechazando lo que no esta en el LOV."""
+    respuesta = _crear_ticket_con_resultado(
+        local_client, "VALOR INVENTADO", "V2008 API rechaza valor inventado"
+    )
+    assert respuesta.status_code == 422, respuesta.text
+
+
+def test_el_ticket_con_el_valor_nuevo_aparece_en_su_columna_del_pivote(
+    local_client, admin_con_sesion, estado_inicial
+):
+    """El ticket con el valor nuevo se cuenta en SU columna, no se pierde."""
+    titulo = "V2008 pivot columna propia"
+    respuesta = _crear_ticket_con_resultado(local_client, VALOR, titulo)
+    assert respuesta.status_code in (200, 201), respuesta.text
+
+    cuerpo = local_client.get("/api/v1/metricas/cuenta-resultado").json()
+    filas = [f for f in cuerpo["filas"] if f["modulo"] == "Incidencias"]
+    assert filas, "no se encontro la fila del modulo Incidencias en el pivote"
+    assert filas[0]["valores"][VALOR] >= 1, (
+        "el ticket con el valor nuevo no aparece en su columna del pivote"
+    )
+
+
+def test_el_drill_down_filtra_por_la_categoria_nueva(
+    local_client, admin_con_sesion, estado_inicial
+):
+    """El drill-down por celda acepta el valor nuevo y sus variantes."""
+    titulo = "V2008 drill down BLOQ"
+    respuesta = _crear_ticket_con_resultado(local_client, VALOR, titulo)
+    assert respuesta.status_code in (200, 201), respuesta.text
+
+    detalle = local_client.get(
+        "/api/v1/metricas/cuenta-resultado/detalle",
+        params={"modulo": "Incidencias", "resultado": VALOR},
+    )
+    assert detalle.status_code == 200, detalle.text
+    assert titulo in detalle.text
+
+
+def test_el_kpi_de_incidencias_abiertas_no_excluye_la_categoria_nueva():
+    """Una prueba bloqueada sigue en gestion: cuenta como incidencia abierta.
+
+    El KPI "Incidencias Abiertas" (``incidencias.backlog_7d``) excluye solo
+    los tickets con resultado ``DESESTIMADA``; la categoria nueva NO debe
+    entrar en esa exclusion.
+    """
+    fuente = FUENTE_METRICAS.read_text(encoding="utf-8")
+    bloque = re.search(
+        r"_resultado_no_desestimada\s*=\s*or_\((.*?)\n    \)", fuente, re.S
+    )
+    assert bloque, "no se encontro el filtro _resultado_no_desestimada"
+    cuerpo = bloque.group(1)
+    assert "DESESTIMADA" in cuerpo
+    assert VALOR not in cuerpo, (
+        "la categoria nueva no debe excluirse del KPI de incidencias abiertas"
+    )
+    assert "_resultado_no_desestimada" in fuente
+
+
+def test_el_porcentaje_de_aprobados_no_cuenta_la_categoria_nueva():
+    """El pie del dashboard suma OK + OK CON OBS. y nada mas."""
+    texto = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")
+    m = re.search(r"const aprobados\s*=\s*\((.*?)\);", texto, re.S)
+    assert m, "no se encontro el calculo de aprobados del pie del dashboard"
+    cuerpo = m.group(1)
+    assert "'OK'" in cuerpo
+    assert "'OK CON OBS.'" in cuerpo
+    assert VALOR not in cuerpo
+
+
+def test_la_plantilla_del_dashboard_no_redeclara_el_lov():
+    """La plantilla consume el catalogo; no puede hardcodear la lista."""
+    texto = PLANTILLA_DASHBOARD.read_text(encoding="utf-8")
+    assert "CUENTA_RESULTADO_LOV" in texto
+    assert "CUENTA_RESULTADO_COLORES" in texto
+    assert "CUENTA_RESULTADO_ACRONIMOS" in texto
+    for valor in LOV_PREVIO:
+        assert '<option value="%s"' % valor not in texto
+    assert 'value="%s"' % VALOR not in texto
+
+
+# ---------------------------------------------------------------------------
+# 4. La carga UAT
+# ---------------------------------------------------------------------------
+def test_el_importador_uat_no_colapsa_el_valor_a_desestimada():
+    """``normalize_resultado`` del importador UAT devuelve el valor canonico."""
+    import importlib.util
+
+    spec = importlib.util.spec_from_file_location(
+        "v2008_uat_import", FUENTE_UAT_IMPORT
+    )
+    modulo = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(modulo)
+
+    assert modulo.normalize_resultado("BLOQUEADO PARA EJECUTAR") == VALOR
+    assert modulo.normalize_resultado("bloqueado para ejecutar") == VALOR
+    assert modulo.normalize_resultado(VALOR) != "DESESTIMADA"
+
+
+def test_el_cargador_consolidado_no_colapsa_el_valor_a_desestimada():
+    """El script de carga masiva tampoco puede seguir colapsando el valor."""
+    import importlib.util
+
+    spec = importlib.util.spec_from_file_location(
+        "v2008_load_uat", FUENTE_LOAD_UAT
+    )
+    modulo = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(modulo)
+
+    assert modulo.normalize_resultado("BLOQUEADO PARA EJECUTAR") == VALOR
+    assert modulo.normalize_resultado(VALOR) != "DESESTIMADA"
+
+
+def test_el_importador_uat_tiene_estado_destino_para_la_categoria_nueva():
+    """El valor nuevo debe tener un estado destino.
+
+    La especificacion original pedia mapearlo a "Analisis/Bloqueado", pero
+    ese estado NO existe en el despliegue (verificado por GET
+    /api/v1/estados en produccion: el estado real que significa lo mismo es
+    "Bloqueado!"). Se mapea al estado existente para no crear una columna
+    casi duplicada del Kanban ni tocar el esquema.
+    """
+    from app.services.uat_import import RESULTADO_A_ESTADO_NOMBRE
+
+    assert VALOR in RESULTADO_A_ESTADO_NOMBRE
+    assert RESULTADO_A_ESTADO_NOMBRE[VALOR] == "Bloqueado!"
+    # El mapeo de NOK no se modifica en este lote (queda documentado como
+    # pendiente de decision de negocio).
+    assert RESULTADO_A_ESTADO_NOMBRE["NOK"] == "Analisis/Bloqueado"
+
+
+def test_la_documentacion_de_uat_mapping_refleja_la_regla_nueva():
+    """``tools/uat_mapping.py`` ya no documenta el colapso a DESESTIMADA."""
+    fuente = FUENTE_UAT_MAPPING.read_text(encoding="utf-8")
+    assert '"BLOQUEADO PARA EJECUTAR"-> "DESESTIMADA"' not in fuente
+    assert "ya no" in fuente and "DESESTIMADA" in fuente
diff --git a/tools/load_uat_consolidado.py b/tools/load_uat_consolidado.py
index 0216070..1426424 100644
--- a/tools/load_uat_consolidado.py
+++ b/tools/load_uat_consolidado.py
@@ -141,8 +141,19 @@ def normalize_resultado(v: Any) -> Optional[str]:
     s_up = s.upper()
     if "POSTERGADA" in s_up or "POSTERG" in s_up:
         return "POSTERGADA"
-    if "BLOQUEADO" in s_up or "BLOQ" in s_up:
-        return "DESESTIMADA"
+    # "BLOQUEADO PARA EJECUTAR" es una categoria PROPIA del LOV desde
+    # V2.008: antes se colapsaba a DESESTIMADA. Se reconoce con una lista
+    # EXPLICITA de variantes (no con un "in" difuso) para que una
+    # abreviatura como "BLOQ" no capture valores ajenos. Sin este cambio, la
+    # siguiente carga UAT volveria a colapsar el valor.
+    if s_up in (
+        "BLOQUEADO PARA EJECUTAR",
+        "BLOQUEADO PARA EJECUCION",
+        "BLOQUEADO PARA EJECUTAR.",
+        "BLOQUEADO",
+        "BLOQ",
+    ):
+        return "BLOQUEADO PARA EJECUTAR"
     mapping = {
         "OK": "OK",
         "NOK": "NOK",
@@ -151,6 +162,7 @@ def normalize_resultado(v: Any) -> Optional[str]:
         "OK CON OBS": "OK CON OBS.",
         "OK CON OBSERVACIONES": "OK CON OBS.",
         "DESESTIMADA": "DESESTIMADA",
+        "BLOQUEADO PARA EJECUTAR": "BLOQUEADO PARA EJECUTAR",
     }
     return mapping.get(s_up) or mapping.get(s) or s
 
diff --git a/tools/uat_mapping.py b/tools/uat_mapping.py
index 1bcd9d7..e356d03 100644
--- a/tools/uat_mapping.py
+++ b/tools/uat_mapping.py
@@ -129,7 +129,9 @@ derivado funcione.
 Reglas de normalizacion de `resultado_pruebas`:
    "POSTERGADA A GARANTIA"   -> "POSTERGADA"
    "OK CON OBS."            -> "OK CON OBS."   (sin cambios)
-   "BLOQUEADO PARA EJECUTAR"-> "DESESTIMADA"   (~ mismo significado operativo)
+   "BLOQUEADO PARA EJECUTAR"-> "BLOQUEADO PARA EJECUTAR"  (V2.008: ya no
+                              se colapsa a "DESESTIMADA"; es una categoria
+                              propia del LOV con acronimo "BLOQ")
    "OK" / "NOK" / "N/A"     -> sin cambios
    "" o None                -> None
 
@@ -142,6 +144,15 @@ esta presente.
 # ============================================================================
 # 5. CARDINALIDADES Y TOTALES ESPERADOS
 # ============================================================================
+# V2.008 -- "BLOQUEADO PARA EJECUTAR" es ahora categoria propia del LOV, pero
+# el consolidado de referencia NO trae filas con ese valor: la suma de
+# "por_columna" (130 + 10 + 635 + 18 + 84 + 0 = 877) ya es igual a
+# "total_general" (877), y no hay columna DESESTIMADA ni BLOQUEADO en los
+# totales por modulo. Es decir, en el archivo de origen esos valores ya
+# venirian colapsados o no existirian, y el conteo real por modulo/columna
+# solo podria obtenerse reprocesando el Excel origen. Si una carga futura
+# trae filas con ese valor, la clave correspondiente debe anadirse aqui con
+# el conteo real (no con ceros), junto con la tupla del modulo afectado.
 TOTALES_ESPERADOS = {
     "total_general":     877,
     "por_columna": {
================================================================================
9. ESTADO FINAL DEL DESPLIEGUE (2026-11-12)
================================================================================

  9.1 PUBLICACION

    Commit del lote:  63d3d99708d1e758b5535ab2d4a5af880fdbebdf
    Commit del fix:   cc3ebed065e27ec4dd84f24244fc053f63d6a642
    Rama de trabajo:  release/v2.001 (rama canonica)
    'main' alineada:  merge --ff-only (68478c5..63d3d99 y 63d3d99..cc3ebed),
                      sin reescribir historia y sin '--force'.
    Push (PUSH_EXIT=0):
        68478c5..63d3d99  main            -> main
        68478c5..63d3d99  release/v2.001  -> release/v2.001
        63d3d99..cc3ebed  main            -> main
        63d3d99..cc3ebed  release/v2.001  -> release/v2.001

    El 'working tree' quedo LIMPIO tras los commits. El apendice A de este
    documento recoge el diff del commit 63d3d99 (10 ficheros del lote). El
    commit cc3ebed es el pin de dependencias y se describe en 9.2.

    Este propio commit de DOCUMENTACION no cambia el codigo: solo anade
    estas lineas al README. Por eso el commit con el CODIGO desplegado del
    lote sigue siendo cc3ebed en los tres servicios. Al publicarlo, 'web'
    se vuelve a desplegar solo por autoDeploy (mismo codigo, otro SHA) y
    'worker' y 'beat' siguen en cc3ebed porque no tienen autoDeploy (ver
    seccion 4). Ningun servicio queda desalineado en CODIGO.

  9.2 INCIDENTE EN EL DESPLIEGUE: EL WORKER NO ARRANCABA

    Al desplegar el worker con el commit del lote (63d3d99) el despliegue
    quedo en estado CRASHED (deployment 962e9f41-1549-4d13-a3b2-38f18a04a9cf,
    createdAt 2026-11-12T18:11:53.746Z). Logs:

        [2026-11-12 18:13:05,378: CRITICAL/MainProcess] Unrecoverable error:
            VersionMismatch('Redis transport requires redis-py versions 6.1.0
            or later. You have 5.2.0')
        kombu.exceptions.VersionMismatch: Redis transport requires redis-py
            versions 6.1.0 or later. You have 5.2.0

    CAUSA RAIZ (NO es un defecto del lote V2.008):

    V2.008 no toca 'requirements.txt', ni el arranque del worker, ni Celery.
    El fallo es una DEPENDENCIA TRANSITIVA SIN FIJAR:

      * 'celery==5.4.0' esta fijado, pero 'kombu' NO estaba en
        'requirements.txt': es una transitiva de celery y pip resolvia
        cualquier 5.x en cada reconstruccion de la imagen.
      * El 2026-11-02 (build del despliegue V2.007) pip resolvio
        'kombu 5.6.2', cuyo pin de redis es
        'redis!=4.5.5,!=5.0.2,<6.5,>=4.5.2': compatible con el
        'redis==5.2.0' fijado. El worker arranco bien.
      * El 2026-11-03 se publico 'kombu 5.7.0', que exige 'redis>=6.4.0'.
        Su pin de redis va en el EXTRA 'redis', que 'celery' no pide, asi
        que el resolutor de pip NO detecta el conflicto con el
        'redis==5.2.0' fijado e instala kombu 5.7.0 sin avisar.
      * Al reconstruir la imagen hoy, el worker arranca con
        'kombu 5.7.0' + 'redis 5.2.0' y kombu aborta en tiempo de ejecucion
        con el VersionMismatch de arriba.

    CONFIRMACION EXPERIMENTAL (resolucion real de pip en seco, sin instalar):

        sin el pin:  celery 5.4.0 | redis 5.2.0 | kombu 5.7.0  -> INCOMPATIBLE
        con el pin:  celery 5.4.0 | redis 5.2.0 | kombu 5.6.2  -> compatible

    El despliegue del 2026-11-02 figuraba en SUCCESS, de modo que el worker
    estaba vivo antes. Este incidente NO lo introdujo el lote V2.008 (que no
    toca requirements.txt ni Celery): lo ha expuesto el redespliegue, que es
    cuando se reconstruye la imagen y se resuelve 'kombu' por ultima vez.

    CORRECCION (commit cc3ebed, unica linea en 'requirements.txt'):

        kombu==5.6.2

    Se fija la transitiva que ya estaba instalada: no se ANADE ninguna
    dependencia nueva al conjunto, solo se deja de flotar. 'kombu 5.6.2' es
    la version que resolvia el despliegue del 2026-11-02 (la que arrancaba),
    su pin de redis acepta el 'redis==5.2.0' fijado y cumple el requisito de
    'celery==5.4.0' ('kombu>=5.3.4,<6.0').

    ALCANCE DEL CAMBIO: 1 linea en 'requirements.txt' (mas su comentario
    explicativo). No toca el codigo de la aplicacion, ni la base de datos,
    ni los estados, ni los KPIs. Reversible con un solo commit. No se anade
    ninguna dependencia y no se sube ninguna version.

  9.3 DESPLIEGUE FINAL EN RAILWAY

    Servicio 'web'    (id 775efae4-375f-4731-8027-680e78bd6a68)
        deployment id = cdda419f-5c97-46ee-827e-900d00fb32bd
        status       = SUCCESS
        createdAt    = 2026-11-12T18:26:10.681Z
        commitHash   = cc3ebed065e27ec4dd84f24244fc053f63d6a642
        branch       = main   (autoDeploy: se redespliego solo al hacer
                               el push a 'main')

    Servicio 'worker' (id 51e22b0c-1f46-411f-b24a-a976107690f0)
        deployment id = 645bc9d7-5137-4123-90c1-1729b3a68df9
        status       = SUCCESS
        createdAt    = 2026-11-12T18:26:51.365Z
        commitHash   = cc3ebed065e27ec4dd84f24244fc053f63d6a642

    Servicio 'beat'   (id 1c16b13c-4533-40c9-b63e-43b00cb14041)
        deployment id = 4285e5a4-8ff3-4328-9e67-1aeb297dc9cb
        status       = SUCCESS
        createdAt    = 2026-11-12T18:26:55.360Z
        commitHash   = cc3ebed065e27ec4dd84f24244fc053f63d6a642

    Los TRES servicios quedaron en el MISMO commit (cc3ebed). 'web' se
    redespliego solo por autoDeploy al publicar en 'main'; 'worker' y 'beat'
    se desplegaron a mano con ese mismo commit, para no dejar los servicios
    desalineados (los dos no tienen autoDeploy: ver seccion 4).

    ARRANQUE REAL DEL WORKER (logs del despliegue 645bc9d7):
        [2026-11-12 18:27:44,622: INFO/MainProcess] Connected to
            redis://default:**@redis.railway.internal:6379/1
        [2026-11-12 18:27:45,656: INFO/MainProcess] celery@789373c4ebf3 ready.
    El worker NO solo se desplego: conecto con Redis y quedo 'ready'.

  9.4 PRUEBAS

    Suite nueva V2.008:                   35 passed
    Suite V2.008 + V2.005 + V2.004:       61 passed (70,43 s)
    Suite completa:                       262 passed (227 + 35), 0 failed
                                          799,47 s (13:19)

  9.5 VERIFICACION EN PRODUCCION (solo GET y POST de login)

    Comprobaciones automatizadas (solo GET y POST de login): 44, 0 fallos.

    1) SALUD Y LOGIN
         GET  /health .................... 200  {"status":"ok",...}
         GET  /ready ..................... 200  {"status":"ready",...}
         POST /api/v1/auth/login ......... 200

    2) EL PIVOTE EXPONE LA CATEGORIA NUEVA
         GET /api/v1/metricas/cuenta-resultado?ambiente=QA -> 200
         columnas:
             ['N/A', 'NOK', 'OK', 'OK CON OBS.', 'POSTERGADA', 'DESESTIMADA',
              'BLOQUEADO PARA EJECUTAR', '(en blanco)']
         totales_por_columna:
             {'N/A': 128, 'NOK': 4, 'OK': 714, 'OK CON OBS.': 3,
              'POSTERGADA': 41, 'DESESTIMADA': 22,
              'BLOQUEADO PARA EJECUTAR': 0, '(en blanco)': 0}
         total_general: 912
         - la columna 'BLOQUEADO PARA EJECUTAR' existe ................ OK
         - 'totales_por_columna' trae la clave nueva .................. OK
         - hay una clave por columna (8) .............................. OK
         - la suma de los totales cuadra con total_general (912) ........ OK
         - el total de cada fila cuadra con sus valores ................. OK

    3) EL DASHBOARD USA EL CATALOGO (PALETA Y ACRONIMO)
         GET /dashboard -> 200
         el LOV inyectado coincide con el del pivote ................... OK
         paleta['BLOQUEADO PARA EJECUTAR']:
             {'bg': '#0891b2', 'cellText': '#1f2937', 'text': '#ffffff'} OK
         el acronimo inyectado es 'BLOQ' ............................... OK
         sin regresion: DESESTIMADA -> 'DESEST' ....................... OK
         sin regresion: NOK conserva su propio acronimo 'NOK' ......... OK
         el pie de aprobados sigue siendo
             (totales['OK'] || 0) + (totales['OK CON OBS.'] || 0) ...... OK
             (la categoria nueva NO entra en el numerador de aprobados)
         listas del LOV en el HTML: 1 (solo la inyectada por el
             servidor; ninguna redeclarada a mano en la plantilla) ..... OK

    4) EL DRILL-DOWN DE LA CATEGORIA NUEVA NO FALLA
         GET /api/v1/metricas/cuenta-resultado/detalle
             ?modulo=Auditoria&resultado=BLOQUEADO PARA EJECUTAR
             -> 200 (3.626 B) ......................................... OK

    5) ESTADOS: SIN CAMBIOS EN EL ESQUEMA
         GET /api/v1/estados -> 200, siguen siendo 10:
             ['BackLog', 'Analisis', 'Bloqueado!', 'En desarrollo',
              'Entregado', 'UAT-QA', 'APROBADO QA', 'Despliegue PROD',
              'produccion ok', 'DESESTIMADA'] ......................... OK
         el estado existente 'Bloqueado!' sigue disponible ............. OK
         NO se creo el estado 'Analisis/Bloqueado' (desviacion 1) ...... OK

    6) SIN REGRESIONES DE V2.007 (RECURSOS AUTOALOJADOS)
         GET /static/css/tailwind.css ........... 200   56.063 B
         GET /static/js/sortable.min.js ........... 200   44.581 B
         GET /static/css/fonts.css .............. 200    1.123 B
         GET /static/fonts/inter-latin.woff2 ..... 200   48.256 B
         GET /static/css/styles.css .............. 200    2.324 B
         GET /static/js/htmx.min.js .............. 200   48.101 B
         /auth/login, /dashboard, /kanban y /tickets: 0 peticiones a un
             CDN externo .............................................. OK

    7) KPIs SIN REGRESION
         GET /api/v1/metricas/dashboard-completo -> 200
         bloque incidencias:
             {'total': 18, 'activas': 18, 'nuevas_7d': 0, 'backlog_7d': 6}
         el KPI 'Incidencias Abiertas' (incidencias.backlog_7d) es 6 ... OK
         NOTA: en la verificacion del lote V2.007 (2026-10-30) ese bloque
         era total 17 / activas 17 / backlog_7d 5. El +1 es el movimiento
         normal de tickets de estos 13 dias, NO una regresion: el KPI no
         filtra por el valor del LOV (una prueba bloqueada sigue contando
         como incidencia abierta) y este lote no toca esa logica.

    8) RESTO DE ENDPOINTS (todos 200)
         GET /kanban .............................. 200  4.280.290 B
         GET /tickets ............................. 200    641.249 B
         GET /api/v1/tickets ...................... 200  2.058.026 B
         GET /api/v1/metricas/resumen ............. 200      1.401 B

  9.6 RESUMEN OPERATIVO

    - La categoria 'BLOQUEADO PARA EJECUTAR' esta DESPLEGADA y es una
      columna real del pivote 'Cuenta de Resultado', con su color propio
      (#0891b2) y su acronimo (BLOQ) servidos por el MISMO catalogo que
      alimenta el badge de las tarjetas del Kanban.
    - En produccion la columna sale todavia a 0 porque ningun ticket tiene
      ese valor: hasta V2.007 el importador UAT lo colapsaba a
      'DESESTIMADA' antes de tocar la base. Los tickets ya cargados son
      indistinguibles de un DESESTIMADA y NO se han retroalimentado: no se
      ha escrito nada en la base de datos de produccion.
    - El numero de aprobados NO cambia: el pie sigue sumando OK + OK CON
      OBS. y la categoria nueva no entra en el numerador.
    - Se ha corregido ademas un incidente colateral (el worker con kombu
      5.7.0) que queda VERIFICADO: el worker vuelve a estar 'ready' y
      conectado a Redis. Ese incidente era de dependencias sin fijar, NO del
      lote, y se evita en el futuro fijando la transitiva.
    - Sin migraciones de base de datos, sin backfill, sin estados nuevos,
      sin dependencias nuevas y sin escrituras en produccion.
    - PENDIENTE DE QA VISUAL DEL PROPIETARIO (procedimiento 5.3 de este
      documento): crear un ticket propio con resultado 'BLOQUEADO PARA
      EJECUTAR' y comprobar el badge BLOQ cian en /kanban, la columna BLOQ
      del dashboard con el mismo 'getComputedStyle().backgroundColor', que
      el pie de aprobados no cambia de numerador, que el selector ofrece la
      opcion marcada y que el KPI 'Incidencias Abiertas' no baja. No se ha
      hecho ninguna escritura en produccion: el lote es de catalogo.

  9.7 PENDIENTES

    - Cerrar la desviacion 1 con negocio: hoy la categoria nueva usa el
      estado existente 'Bloqueado!'. Si negocio prefiere el estado
      'Analisis/Bloqueado' (que NO existe en produccion), hay que darlo de
      alta en la tabla de estados; es un cambio de una linea y una
      migracion idempotente.
    - Decidir el NOK roto: 'RESULTADO_A_ESTADO_NOMBRE["NOK"] =
      "Analisis/Bloqueado"' no resuelve en el despliegue y cae de forma
      silenciosa al estado inicial (BackLog). Queda DOCUMENTADO, no
      corregido: no lo ha corregido ningun lote.
    - Fijar tambien 'amqp' y 'vine' en 'requirements.txt' si se quiere
      cerrar del todo la clase de problemas de transitivas sin fijar (las
      tres estan hoy en amqp 5.4.2 y vine 5.1.0, compatibles).
    - Pendientes de seguridad que ningun lote cierra: rotar la clave del
      administrador y el token de proyecto de Railway, auditar el cambio de
      contrasena del 2026-10-26, cerrar el registro publico de usuarios,
      poner un volumen real en /data con un SECRET_KEY persistente, rotar la
      contrasena de PostgreSQL y borrar los ~50 ficheros 'tmp_*' del
      arbol de trabajo.
