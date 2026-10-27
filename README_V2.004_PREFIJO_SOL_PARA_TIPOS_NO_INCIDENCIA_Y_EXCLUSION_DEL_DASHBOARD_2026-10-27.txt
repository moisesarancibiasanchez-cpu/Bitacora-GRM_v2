================================================================================
README V2.004 - PREFIJO SOL PARA LOS TIPOS QUE NO SON INCIDENCIAS Y EXCLUSION
ESTRUCTURAL DEL BLOQUE DE INCIDENCIAS DEL DASHBOARD
Proyecto: Bitacora GRM v2
Fecha: 2026-10-27
Rama base: main y release/v2.001 (commit 46da79a)
Estado: CODIGO LISTO Y VERIFICADO EN LOCAL. PENDIENTE DE DESPLEGUE.
================================================================================

0. PARCHE EXACTO

  Ficheros intervenidos:
    - app/core/codigo_ticket.py                (nuevo: SSOT de la regla)
    - app/main.py                              (creacion desde el modal)
    - app/api/v1/tickets.py                    (duplicar tarjeta)
    - app/services/ticket_service.py           (servicio de creacion)
    - app/api/v1/import_export.py              (importacion de tickets)
    - app/api/v1/metricas.py                   (filtro del dashboard)
    - tests/test_v2004_prefijo_sol_y_exclusion_dashboard.py  (nuevo, 15 tests)
    - tests/test_v2002_consistencia_kpi.py     (conteo independiente actualizado)

  Funciones nuevas (app/core/codigo_ticket.py):
    - generar_codigo_ticket()      [unica puerta de entrada del codigo]
    - tipos_no_incidencia()
    - es_tipo_no_incidencia()
    - _normalizar_tipo()
    - _generar_codigo_inc()
    - _generar_codigo_sol()
    - _generar_codigo_gar()
    - HuRequeridaError
    - ConflictoNumeracionError

  Constantes nuevas (app/core/codigo_ticket.py):
    - PREFIJO_INCIDENCIA            = "INC-"
    - PREFIJO_SOLICITUD             = "SOL-"
    - PREFIJO_RESULTADO_PRUEBAS     = "GAR_"
    - NOMBRES_TIPOS_NO_INCIDENCIA   = ("SOLICITUD", "PROBLEMA", "CAMBIO",
                                        "RESULTADO_PRUEBAS")

  Funcion intervenida (app/api/v1/metricas.py):
    - _build_tipo_filter()   [caso "incidencia": exclusion estructural]

  Funciones intervenidas (regla de codigo):
    - app/main.py            -> ticket_crear()          (POST /tickets/crear)
    - app/api/v1/tickets.py  -> duplicar_ticket()       (POST /{id}/duplicar)
    - app/services/ticket_service.py
                           -> TicketService._generar_codigo_ticket()
                           -> TicketService.crear_ticket()
    - app/api/v1/import_export.py
                           -> importar()               (POST /tickets-ie/importar)

  Tests nuevos (tests/test_v2004_prefijo_sol_y_exclusion_dashboard.py):
    - test_los_tipos_no_incidencia_se_crean_con_prefijo_sol[solicitud]
    - test_los_tipos_no_incidencia_se_crean_con_prefijo_sol[problema]
    - test_los_tipos_no_incidencia_se_crean_con_prefijo_sol[cambio]
    - test_una_incidencia_sigue_llevando_prefijo_inc
    - test_resultado_de_pruebas_sigue_llevando_prefijo_gar
    - test_la_familia_sol_tiene_correlativo_propio
    - test_los_tipos_no_incidencia_no_aparecen_en_la_lista_de_incidencias
    - test_crear_tickets_no_incidencia_no_mueve_los_indicadores
    - test_un_no_incidencia_con_codigo_inc_tampoco_entra
    - test_un_resultado_de_pruebas_no_entra_en_la_lista_de_incidencias
    - test_los_no_incidencia_siguen_siendo_visibles_en_todos_los_tipos
    - test_duplicar_un_ticket_no_incidencia_conserva_la_regla
    - test_duplicar_un_ticket_de_resultado_de_pruebas_conserva_gar
    - test_el_servicio_de_tickets_usa_la_misma_regla
    - test_la_importacion_usa_la_misma_regla

  El diff completo esta al final de este documento, en el APENDICE A.

================================================================================
1. BASE
================================================================================

  Base de este cambio: el commit 46da79a, punta de 'main' y de
  'release/v2.001'. Contiene el lote V2.003 (b403de6 + 46da79a), que corrigio
  el dashboard en blanco por un error de sintaxis JavaScript.

  Contexto del defecto (validado por el propietario el 2026-10-27):

    "Valida que cuando se crea una nueva incidencia que sea distinto a
     Tipo = Incidencia (Solicitud, Problema, Cambio) entonces NO la crea
     como Incidencia, No la crea con prefijo INC-XXX sino como GAR_XXXXX y
     No la suma en Dashboard como parte del contenido de 'Lista de
     Incidencias Recientes', ni como parte de los indicadores respectivos."

  VALIDACION PREVIA (hecha antes de tocar nada, 2026-10-27):

    Se creo un ticket de cada tipo por el endpoint real POST /tickets/crear
    y se leyo lo que quedo en la base de datos:

      tipo enviado      tipo guardado     codigo            en la lista?
      incidencia        INCIDENCIA        INC-001           si (correcto)
      solicitud        SOLICITUD         INC-002           SI (mal)
      problema          PROBLEMA          INC-003           SI (mal)
      cambio            CAMBIO            INC-004           SI (mal)
      resultado_pruebas RESULTADO_PRUEBAS GAR_SC_VAL_1_001  no (correcto)

    Y con cinco tickets en la base, los indicadores decia:

      /resumen  totales.total          = 5   (todos los tickets)
      /resumen  incidencias.total      = 4   (solo deberia ser 1)
      /resumen  incidencias.activas    = 4
      /resumen  incidencias.nuevas_7d  = 4
      /resumen  incidencias.backlog_7d = 4

    Es decir, cuatro de cinco tickets se contaban como incidencias siendo
    solo uno de ellos una incidencia.

  CAUSA RAIZ (dos capas, la misma raiz):

    (a) La regla de codigo no tenia en cuenta el tipo. Vivia duplicada en
        cuatro rutas de creacion y tres de ellas generaban SIEMPRE
        "INC-NNN", ignorando el tipo:

          app/main.py                    -> solo "resultado_pruebas" tenia
                                            prefijo propio ("GAR_<HU>_<NNN>");
                                            el resto, "INC-NNN".
          app/api/v1/tickets.py          -> duplicar: siempre "INC-NNN".
          app/services/ticket_service.py -> siempre "INC-NNN".
          app/api/v1/import_export.py    -> importar: siempre "INC-NNN".

        Documentado en el propio codigo, app/main.py:661-669:
        "Cualquier otro tipo -> se usa el formato correlativo INC-NNN."

    (b) El filtro de incidencias del dashboard (app/api/v1/metricas.py,
        _build_tipo_filter) incluia el PREFIJO del codigo:

          or_(tipo == 'INCIDENCIA', codigo ILIKE 'INC-%', codigo ILIKE 'INC\_%')

        Por eso una Solicitud/Problema/Cambio con codigo "INC-..." entraba en
        la "Lista de Incidencias Recientes" y en todos los indicadores de
        incidencias aunque su tipo no fuese incidencia. El filtro dependia
        de un dato DERIVADO (el prefijo) en vez de del dato de negocio (el
        tipo).

  IMPACTO MEDIDO EN PRODUCCION (2026-10-27, solo GET):

    - Ya no existe ningun ticket de tipo solicitud, cambio o problema
      (0 de cada uno), asi que el defecto estaba LATENTE, no activo.
    - Si habia un conteo DOBLE activo: la lista "Incidencias" devolvia 20
      tickets y la lista "Resultados de pruebas" 915, mientras que "Todos
      los tipos" devolvia 932 (20 + 915 = 935 > 932). Los 3 sobrantes son
      tickets de tipo resultado_pruebas con codigo historico "INC_" que
      contaban en las dos listas:
          INC_012  modulo de documentacion ELIMINAR columnas DEBUG
          INC_013  informes de validacion Repetidos en Etapas
          INC_11   Problema de Cache al Guardar Form Uso
      Este lote elimina tambien ese doble conteo.

================================================================================
2. CAMBIO UNICO
================================================================================

  QUE EL CODIGO DE UN TICKET DEPENDA DE SU TIPO, Y QUE UN TICKET QUE NO ES
  UNA INCIDENCIA NO APAREZCA NUNCA EN EL BLOQUE DE INCIDENCIAS DEL DASHBOARD
  ("Lista de Incidencias Recientes" y sus indicadores).

  2.1 REGLA DE CODIGO POR TIPO (nueva SSOT: app/core/codigo_ticket.py)

      tipo                   codigo            familia
      ---------------------  ----------------  ---------------------------
      incidencia             INC-NNN           correlativo por id maximo
      solicitud              SOL-NNN           correlativo propio de la
      problema               SOL-NNN           familia, compartido entre los
      cambio                 SOL-NNN           tres tipos
      resultado_pruebas      GAR_<HU>_<NNN>    correlativo por HU

      El correlativo SOL es independiente del de INC: crear tickets SOL- no
      consume numeracion de los INC- ni al reves.

  2.2 UNA SOLA PUERTA DE ENTRADA

      Todo el codigo nuevo del proyecto sale de
      app/core/codigo_ticket.py::generar_codigo_ticket(). Las cuatro rutas
      de creacion la consumen:

        POST /tickets/crear            -> app/main.py
        POST /api/v1/tickets/{id}/duplicar
                                     -> app/api/v1/tickets.py
        TicketService.crear_ticket()  -> app/services/ticket_service.py
        POST /api/v1/tickets-ie/importar/{formato}
                                     -> app/api/v1/import_export.py

      Antes cada una reimplementaba la regla y tres de ellas la
      implementaban MAL (siempre INC-). Con la SSOT es imposible que el
      prefijo dependa del camino por el que se crea el ticket.

  2.3 EXCLUSION ESTRUCTURAL EN EL DASHBOARD

      app/api/v1/metricas.py::_build_tipo_filter("incidencia") pasa a ser:

          _tipo_txt = func.upper(Ticket.tipo.cast(String))
          _no_es_no_incidencia = or_(
              _tipo_txt.is_(None),
              _tipo_txt.notin_(NOMBRES_TIPOS_NO_INCIDENCIA),
          )
          return and_(
              _no_es_no_incidencia,
              or_(
                  _tipo_txt == "INCIDENCIA",
                  Ticket.codigo.ilike("INC-%"),
                  Ticket.codigo.ilike("INC\\_%", escape="\\"),
              ),
          )

      Es decir: un ticket cuenta como incidencia si su TIPO lo es, o si su
      codigo lleva el prefijo historico INC-/INC_ Y su tipo no dice que no es
      una incidencia. El tipo manda siempre.

      La exclusion aplica a los cuatro tipos que no son incidencia
      (Solicitud, Problema, Cambio y Resultado de Pruebas), de modo que:

        - un SOL- nunca aparece en la "Lista de Incidencias Recientes" ni en
          sus indicadores;
        - aunque por lo que sea un ticket de tipo no-incidencia tuviera un
          codigo "INC-...", sigue SIN aparecer (garantia estructural, no
          accidental);
        - los tres tickets historicos "INC_" de tipo resultado_pruebas
          dejan de contar dos veces.

      La lista "Todos los tipos" NO cambia: sigue incluyendo los cinco
      tipos, asi que ningun ticket se pierde, solo deja de sumar donde no
      toca.

  2.4 INDICADORES QUE DEJAN DE CONTAR LOS TIPOS NO-INCIDENCIA

      Todos ellos usaban el mismo helper, asi que quedan corregidos a la vez:

        incidencias.total        -> "INCIDENCIAS LEVANTADAS"
        incidencias.activas      -> "ABIERTAS" (franja superior)
        incidencias.nuevas_7d    -> "NUEVAS (7D)"
        incidencias.backlog_7d   -> "INCIDENCIAS ABIERTAS"
        riesgo_sla               -> "PROXIMOS A VENCER SLA"
        cuenta_resultado         -> "CUENTA DE RESULTADO" (pivote)
        incidencias_recientes    -> "LISTA DE INCIDENCIAS RECIENTES"
        detalle_kpi              -> modal de drill-down

      NO cambian (son totales, no de incidencias): "TICKETS TOTALES",
      "ACTIVOS", "CRIT. SIN ASIGNAR" y "Top agentes".

================================================================================
3. QUE NO SE MODIFICO
================================================================================

  - NINGUNA migracion, NINGUN seed, NINGUN cambio de esquema. La columna
    'codigo' sigue siendo VARCHAR(20) y el enum 'tipo' sigue igual.

  - NINGUN dato existente. No se renumera ni se reescribe ningun ticket ya
    creado: los codigos historicos (INC-, INC_, GAR_) se quedan como estan.
    El unico efecto sobre los datos es que 3 tickets historicos dejan de
    contar dos veces en el dashboard.

  - NINGUN endpoint nuevo, NINGUN endpoint eliminado, NINGUN cambio de
    ruta ni de metodo HTTP.

  - NINGUN cambio en el tipo enum 'TipoIncidencia'. Sigue Having los mismos
    cinco valores: incidencia, solicitud, cambio, problema, resultado_pruebas.

  - NINGUN cambio en la UI. El formulario de nueva incidencia sigue
    ofreciendo los mismos tipos y el dashboard sigue offering los mismos
    selectores ('Incidencias', 'Resultados de pruebas', 'Todos los tipos').

  - NINGUN cambio en la logica de negocio del dashboard mas alla del filtro
    de tipo: no se toca el calculo de rangos, ni el modal, ni el pivote, ni
    la exportacion CSV.

  - NINGUN cambio en el formato GAR_<HU>_<NNN>: sigue igual, incluida la
    truncacion de la HU a 12 caracteres y el bucle de reintentos.

  - NINGUN cambio en el prefijo INC- de las incidencias.

  - NINGUNA dependencia nueva. 'requirements.txt' no se modifica. El modulo
    nuevo es Python puro.

  - NINGUN cambio de autenticacion, de permisos, de cabeceras de seguridad
    ni de la configuracion de Railway.

  - NINGUN fichero eliminado ni renombrado.

================================================================================
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  - REQUIERE CAMBIAR WORKER: NO. El cambio afecta al codigo de generacion
    de tickets y al filtro de metricas. El worker de Celery no genera
    tickets ni calcula metricas del dashboard.

  - REQUIERE CAMBIAR BEAT: NO. Same reasoning: el beat solo dispara tareas
    periodicas.

  - REQUIERE REINICIAR LA COLA DE CELERY: NO.

  - REQUIERE MIGRACIONES DE BASE DE DATOS: NO.

  - REQUIERE CAMBIOS DE VARIABLES DE ENTORNO: NO.

  - REQUIERE LIMPIEZA DE CACHE O CDN: NO.

  - REQUIERE COMPILACION O BUILD: NO.

  NOTA OPERATIVA:

    Por simetria, y para no dejar los tres servicios con arboles distintos
    (que ya provoco un incidente de desalineacion en este proyecto), el
    despliegue recomendado es publicar el MISMO commit en los tres
    servicios: web, worker y beat.

    El servicio 'web' tiene autoDeploy siguiendo la rama 'main', de modo que
    un push a 'main' redespliega el web por su cuenta. El 'worker' y el
    'beat' NO tienen autoDeploy: hay que desplegarlos de forma explicita.

================================================================================
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 PRUEBA AUTOMATICA (obligatoria, antes de publicar)

    a) Suite nueva de regresion (rapida, ~25 s):

       cd <repo>
       & 'C:\Python311embed\python.exe' -X utf8 -m pytest \
           tests/test_v2004_prefijo_sol_y_exclusion_dashboard.py \
           -q --tb=short -p no:logging

       Resultado esperado: 15 passed.

    b) Suite de V2.002 (la del modal de KPI, que comparte el filtro):

       & 'C:\Python311embed\python.exe' -X utf8 -m pytest \
           tests/test_v2002_consistencia_kpi.py -q --tb=short -p no:logging

       Resultado esperado: 9 passed.

    c) Suite completa (tarda unos 12 minutos):

       & 'C:\Python311embed\python.exe' -X utf8 -m pytest tests/ -q --tb=line \
           -p no:logging

       Resultado esperado: 184 passed (169 heredadas + 15 nuevas), 0 failed.

  5.2 PRUEBA MANUAL (obligatoria tras el despliegue)

    a) Crear un ticket de tipo SOLICITUD desde "Nueva Incidencia".
       Comprobar:
         - el tipo se guarda como Solicitud (no como Incidencia);
         - el codigo empieza por SOL- (no por INC-);
         - el ticket NO aparece en la "Lista de Incidencias Recientes" del
           dashboard, ni al cambiar el selector a "Incidencias";
         - el ticket SI aparece en el selector "Todos los tipos";
         - los indicadores de incidencias del dashboard NO se mueven.

    b) Repetir con PROBLEMA y con CAMBIO.

    c) Crear un ticket de tipo RESULTADO DE PRUEBAS:
         - el codigo sigue siendo GAR_<HU>_<NNN>;
         - NO aparece en la lista de Incidencias;
         - SI aparece en la lista de Resultados de pruebas.

    d) Crear un ticket de tipo INCIDENCIA:
         - el codigo sigue siendo INC-;
         - SI aparece en la lista de Incidencias.

    e) Duplicar un ticket SOL-:
         - la copia tambien es SOL-;
         - la copia NO aparece en la lista de Incidencias.

    f) Comprobar el dashboard con los datos reales: la "Lista de Incidencias
       Recientes" y los indicadores de incidencias deben seguir cuadrando
       entre si (resumen == modal), y el numero de tickets de la lista de
       Incidencias debe bajar en 3 respecto a antes del despliegue (los tres
       tickets historicos INC_ de tipo resultado_pruebas dejan de contar dos
       veces).

  5.3 PRUEBA POR API (opcional, solo GET y POST de login)

      GET /api/v1/metricas/incidencias-recientes?tipo=incidencia
          &periodo_dias=365&limite=200
      GET /api/v1/metricas/incidencias-recientes?tipo=solicitud
          &periodo_dias=365&limite=200
      GET /api/v1/metricas/incidencias-recientes?tipo=todos
          &periodo_dias=365&limite=200
      GET /api/v1/metricas/resumen?dias=365

    Comprobaciones:
      - la lista 'incidencia' y la lista 'resultado_pruebas' NO deben
        solaparse (antes se solapaban en 3 tickets);
      - 'incidencias.total' del resumen debe coincidir con el numero de
        tickets de tipo INCIDENCIA.

================================================================================
6. TRAZABILIDAD
================================================================================

  Commit base:            46da79a357436e11d9d43a659f0a4a68072eded7
  Rama base:              main (y release/v2.001, mismo commit)

  Ficheros intervenidos:
    app/core/codigo_ticket.py                (nuevo)
    app/main.py
    app/api/v1/tickets.py
    app/services/ticket_service.py
    app/api/v1/import_export.py
    app/api/v1/metricas.py
    tests/test_v2004_prefijo_sol_y_exclusion_dashboard.py  (nuevo)
    tests/test_v2002_consistencia_kpi.py

  Endpoints IMPLICADOS:
    POST /tickets/crear                      (creacion desde el modal)
    POST /api/v1/tickets/{id}/duplicar       (duplicar tarjeta)
    POST /api/v1/tickets-ie/importar/{fmt}   (importacion)
    GET  /api/v1/metricas/resumen
    GET  /api/v1/metricas/dashboard-completo
    GET  /api/v1/metricas/incidencias-recientes
    GET  /api/v1/metricas/detalle-kpi

  Evidencia (medida, 2026-10-27):
    - suite nueva V2.004: 15 passed;
    - suite V2.002: 9 passed;
    - revertiendo temporalmente el filtro del dashboard, la suite V2.004
      pasa a 2 failed de 15 (los dos tests de garantia estructural):
        test_un_no_incidencia_con_codigo_inc_tampoco_entra
        test_un_resultado_de_pruebas_no_entra_en_la_lista_de_incidencias
      restaurando el filtro, vuelve a 15 passed.

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

    e) Verificacion funcional: hacer los pasos 5.2 (a) a (f) en el
       navegador contra el servicio desplegado.

  7.2 ROLLBACK

    Commit de referencia: el anterior (46da79a), que es el arbol del lote
    V2.003 y el arbol estable anterior a este cambio.

    Rollback en git (sin reescribir historia):

         git revert <commit de V2.004>
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

    Efecto del rollback: los tickets de tipo Solicitud/Problema/Cambio
    volverian a crearse con prefijo INC- y volverian a sumar en el bloque
    de incidencias del dashboard. No se pierde ningun dato: el rollback solo
    restaura la regla anterior.

================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

  El diff que sigue es el EXACTO de los ficheros de codigo modificados.
  Va TRANSLITERADO a ASCII: los caracteres acentuados del codigo original
  ('a' con tilde, 'i' con tilde, etc.) se han sustituido por su equivalente
  ASCII. ESTA TRANSLITERACION ES SOLO DOCUMENTAL: el codigo del proyecto NO
  se modifica, conserva sus caracteres originales en UTF-8.

diff --git a/app/api/v1/import_export.py b/app/api/v1/import_export.py
index 45bd0d4..1015a27 100644
--- a/app/api/v1/import_export.py
+++ b/app/api/v1/import_export.py
@@ -26,6 +26,7 @@ from sqlalchemy import func
 from sqlalchemy.orm import Session
 
 from app.api.v1.deps import get_current_user
+from app.core.codigo_ticket import generar_codigo_ticket
 from app.db.session import get_db
 from app.models.estado import Estado
 from app.models.ticket import Ticket, TipoIncidencia, Prioridad
@@ -250,11 +251,11 @@ async def importar(
         for e in db.query(Etiqueta).filter(Etiqueta.activo == True).all()  # noqa: E712
     }
 
-    # Generador de codigo correlativo (mismo formato que el resto del proyecto: INC-XXX).
-    # La numeracion se basa en el ID maximo actual de la tabla para no
-    # colisionar con codigos generados por el servicio estandar ni por
-    # imports previos.
-    ultimo = db.query(func.max(Ticket.id)).scalar() or 0
+    # El codigo de cada ticket importado se genera con la regla unica del
+    # proyecto (``app/core/codigo_ticket.py``, SSOT): INC-NNN para
+    # incidencias, SOL-NNN para Solicitud/Problema/Cambio y
+    # GAR_<HU>_<NNN> para Resultado de Pruebas. Por eso el TIPO de la fila
+    # se resuelve antes que el codigo.
 
     creados = 0
     errores: List[str] = []
@@ -265,16 +266,18 @@ async def importar(
             if not titulo:
                 errores.append(f"Fila {idx}: falta 'titulo'")
                 continue
-            ultimo += 1
-            codigo = f"INC-{ultimo:03d}"
-
-            # Mapear tipo
+            # Mapear tipo (antes del codigo: el prefijo depende del tipo)
             tipo_str = (fila.get("tipo") or "incidencia").strip().lower()
             try:
                 tipo_enum = TipoIncidencia(tipo_str)
             except ValueError:
                 tipo_enum = TipoIncidencia.INCIDENCIA
 
+            # Codigo con la regla unica del proyecto (SSOT).
+            codigo = generar_codigo_ticket(
+                db, tipo_enum, fila.get("hu_o_caso_prueba")
+            )
+
             # Mapear prioridad
             prio_str = (fila.get("prioridad") or "media").strip().lower()
             try:
diff --git a/app/api/v1/metricas.py b/app/api/v1/metricas.py
index 96cc796..d13c744 100644
--- a/app/api/v1/metricas.py
+++ b/app/api/v1/metricas.py
@@ -14,6 +14,7 @@ from sqlalchemy import String, func, case, and_, or_
 from sqlalchemy.orm import Session
 
 from app.api.v1.deps import get_current_user
+from app.core.codigo_ticket import NOMBRES_TIPOS_NO_INCIDENCIA
 from app.core.resultado_pruebas import (
     ACRONIMOS as ACRONIMOS_RESULTADO,
     COLORES as COLORES_RESULTADO,
@@ -74,10 +75,31 @@ def _build_tipo_filter(tipo: str):
         Expresion SQLAlchemy combinable con .filter() / .where().
     """
     if tipo == "incidencia":
-        return or_(
-            func.upper(Ticket.tipo.cast(String)) == _TIPOS_VALIDOS["incidencia"],
-            Ticket.codigo.ilike("INC-%"),
-            Ticket.codigo.ilike("INC\\_%", escape="\\"),
+        # Garantia estructural (V2.004): un ticket cuyo tipo NO es incidencia
+        # (Solicitud, Problema, Cambio o Resultado de Pruebas) NUNCA entra en
+        # el bloque de incidencias del dashboard, aunque su codigo empiece por
+        # "INC-" o "INC_".
+        #
+        # Antes el filtro era solo "tipo = INCIDENCIA OR prefijo INC-". Como el
+        # prefijo lo genera el codigo y el codigo se asignaba por tipo, una
+        # Solicitud/Problema/Cambio creado con prefijo "INC-" entraba en la
+        # "Lista de Incidencias Recientes" y en los indicadores de incidencias.
+        #
+        # La clausula de prefijo se conserva para los tickets historicos cuyo
+        # tipo es NULL (no se puede saber si son incidencia), pero se descarta
+        # siempre que el tipo diga que no es una incidencia.
+        _tipo_txt = func.upper(Ticket.tipo.cast(String))
+        _no_es_no_incidencia = or_(
+            _tipo_txt.is_(None),
+            _tipo_txt.notin_(NOMBRES_TIPOS_NO_INCIDENCIA),
+        )
+        return and_(
+            _no_es_no_incidencia,
+            or_(
+                _tipo_txt == _TIPOS_VALIDOS["incidencia"],
+                Ticket.codigo.ilike("INC-%"),
+                Ticket.codigo.ilike("INC\\_%", escape="\\"),
+            ),
         )
     if tipo in _TIPOS_VALIDOS:
         return func.upper(Ticket.tipo.cast(String)) == _TIPOS_VALIDOS[tipo]
diff --git a/app/api/v1/tickets.py b/app/api/v1/tickets.py
index 64a3325..8457711 100644
--- a/app/api/v1/tickets.py
+++ b/app/api/v1/tickets.py
@@ -1269,8 +1269,8 @@ def duplicar_ticket(
     from app.models.estado import Estado
     from app.models.auditoria import Auditoria
     from app.models.ticket import TipoIncidencia, Prioridad
+    from app.core.codigo_ticket import generar_codigo_ticket
     from datetime import timedelta
-    from sqlalchemy import func as sqlfunc
 
     original = db.query(Ticket).filter(Ticket.id == ticket_id).first()
     if not original:
@@ -1282,9 +1282,11 @@ def duplicar_ticket(
         or db.query(Estado).order_by(Estado.orden).first()
     )
 
-    # Generar nuevo codigo correlativo (formato compacto INC-NNN)
-    ultimo = db.query(sqlfunc.max(Ticket.id)).scalar() or 0
-    codigo = f"INC-{(ultimo + 1):03d}"
+    # Generar el nuevo codigo con la MISMA regla que usa la creacion normal
+    # (SSOT en app/core/codigo_ticket.py): la copia conserva el tipo del
+    # original, asi que una copia de una Solicitud/Problema/Cambio recibe
+    # prefijo SOL- y una de Resultado de Pruebas recibe GAR_<HU>_<NNN>.
+    codigo = generar_codigo_ticket(db, original.tipo, original.hu_o_caso_prueba)
 
     # Calcular nueva fecha de SLA
     fecha_sla = None
diff --git a/app/core/codigo_ticket.py b/app/core/codigo_ticket.py
new file mode 100644
index 0000000..d29d3e4
--- /dev/null
+++ b/app/core/codigo_ticket.py
@@ -0,0 +1,260 @@
+"""
+Regla unica de generacion del codigo de un ticket (SSOT).
+
+Este modulo es la **unica fuente de verdad** del prefijo y del correlativo
+del codigo de un ticket, y de que tipos son considered "incidencia" a efectos
+de negocio.
+
+Reglas
+------
+=====================  =========================  ==============================
+Tipo                   Codigo                     Observaciones
+=====================  =========================  ==============================
+``incidencia``         ``INC-NNN``                Correlativo por id maximo.
+                                                 Es el unico tipo que cuenta
+                                                 como incidencia en el
+                                                 dashboard.
+``solicitud``          ``SOL-NNN``                Familia propia, correlativo
+``problema``           ``SOL-NNN``                compartido entre los tres
+``cambio``             ``SOL-NNN``                tipos no-incidencia.
+``resultado_pruebas``  ``GAR_<HU>_<NNN>``         Correlativo 3 digitos por
+                                                 HU (truncada a 12 caracteres
+                                                 por el VARCHAR(20) del modelo).
+=====================  =========================  ==============================
+
+Por que centralizarlo
+---------------------
+Antes de este modulo la regla estaba repartida en cuatro sitios que la
+reimplementaban cada uno a su manera:
+
+  * ``app/main.py`` (``POST /tickets/crear``),
+  * ``app/api/v1/tickets.py`` (duplicar ticket),
+  * ``app/services/ticket_service.py`` (``_generar_codigo_ticket``),
+  * ``app/api/v1/import_export.py`` (importacion).
+
+Los tres ultimos generaban SIEMPRE ``INC-NNN``, ignorando el tipo. Eso
+significaba que una Solicitud, un Problema o un Cambio se creaban con
+codigo ``INC-...``, y como el filtro de incidencias del dashboard
+(``app/api/v1/metricas.py::_build_tipo_filter``) tambien acepta el
+prefijo ``INC-``/``INC_``, esos tickets entraban en la "Lista de Incidencias
+Recientes" y en los indicadores de incidencias del dashboard aunque su tipo
+no fuese incidencia.
+
+Con este modulo, los cuatro caminos consumen la misma regla y el prefijo
+deja de depender del sitio por el que se crea el ticket.
+
+Ademas el modulo publica ``TIPOS_NO_INCIDENCIA`` y ``es_tipo_no_incidencia``,
+que son los que usa el filtro del dashboard para garantizar
+estructuralmente que un ticket de tipo Solicitud/Problema/Cambio (o de
+tipo Resultado de Pruebas) NUNCA aparece en el bloque de incidencias.
+"""
+
+from __future__ import annotations
+
+from typing import Optional
+
+# --------------------------------------------------------------------------
+# Prefijos
+# --------------------------------------------------------------------------
+
+#: Prefijo de las incidencias (tipo ``incidencia``).
+PREFIJO_INCIDENCIA = "INC-"
+
+#: Prefijo de la familia de tickets que NO son incidencias
+#: (tipo ``solicitud``, ``problema`` o ``cambio``).
+PREFIJO_SOLICITUD = "SOL-"
+
+#: Prefijo de los tickets de tipo ``resultado_pruebas``.
+PREFIJO_RESULTADO_PRUEBAS = "GAR_"
+
+#: Separador entre la HU y el correlativo en el formato ``GAR_<HU>_<NNN>``.
+SEPARADOR_GAR = "_"
+
+#: Longitud maxima de la HU dentro del codigo ``GAR_`` (VARCHAR(20) del modelo:
+#: ``GAR_`` = 4 + ``_NNN`` = 4 ? quedan 12 caracteres para la HU).
+MAX_HU_EN_CODIGO = 12
+
+#: Intentos de asignar un correlativo libre antes de declarar conflicto.
+MAX_INTENTOS_NUMERACION = 5
+
+#: Nombres de los tipos (valores realmente almacenados en la columna
+#: ``tickets.tipo``) que NO son incidencias. Es la lista que usa el filtro del
+#: dashboard (``app/api/v1/metricas.py``) para garantizar estructuralmente
+#: que un ticket de estos tipos nunca aparece en el bloque de incidencias.
+NOMBRES_TIPOS_NO_INCIDENCIA = (
+    "SOLICITUD",
+    "PROBLEMA",
+    "CAMBIO",
+    "RESULTADO_PRUEBAS",
+)
+
+
+# --------------------------------------------------------------------------
+# Excepciones
+# --------------------------------------------------------------------------
+
+class HuRequeridaError(ValueError):
+    """El tipo ``resultado_pruebas`` exige el campo HU o Caso de Prueba."""
+
+    def __init__(self, mensaje: str = "Falta HU o Caso de Prueba"):
+        super().__init__(mensaje)
+        self.mensaje = mensaje
+
+
+class ConflictoNumeracionError(RuntimeError):
+    """No se pudo asignar un correlativo libre tras varios intentos."""
+
+    def __init__(self, mensaje: str = "Conflicto de numeracion"):
+        super().__init__(mensaje)
+        self.mensaje = mensaje
+
+
+# --------------------------------------------------------------------------
+# Tipos
+# --------------------------------------------------------------------------
+
+def _normalizar_tipo(tipo):
+    """Devuelve el ``TipoIncidencia`` correspondiente, o ``None`` si no existe."""
+    from app.models.ticket import TipoIncidencia
+
+    if tipo is None:
+        return None
+    if isinstance(tipo, TipoIncidencia):
+        return tipo
+    try:
+        return TipoIncidencia(str(tipo).strip().lower())
+    except ValueError:
+        return None
+
+
+def tipos_no_incidencia() -> tuple:
+    """Tipos de ticket que NUNCA deben contar como incidencia."""
+    from app.models.ticket import TipoIncidencia
+
+    return (
+        TipoIncidencia.SOLICITUD,
+        TipoIncidencia.PROBLEMA,
+        TipoIncidencia.CAMBIO,
+        TipoIncidencia.RESULTADO_PRUEBAS,
+    )
+
+
+def es_tipo_no_incidencia(tipo) -> bool:
+    """True si el tipo NO es una incidencia a efectos del dashboard."""
+    enum = _normalizar_tipo(tipo)
+    if enum is None:
+        return False
+    return enum in tipos_no_incidencia()
+
+
+# --------------------------------------------------------------------------
+# Generacion
+# --------------------------------------------------------------------------
+
+def _generar_codigo_inc(db) -> str:
+    """``INC-NNN``: correlativo basado en el id maximo de la tabla."""
+    from sqlalchemy import func
+
+    from app.models.ticket import Ticket
+
+    ultimo = db.query(func.max(Ticket.id)).scalar() or 0
+    return f"{PREFIJO_INCIDENCIA}{(ultimo + 1):03d}"
+
+
+def _generar_codigo_sol(db) -> str:
+    """``SOL-NNN``: correlativo propio de la familia no-incidencia.
+
+    El correlativo es compartido por los tres tipos de la familia
+    (Solicitud, Problema y Cambio) y cuenta los tickets ya existentes de
+    esa familia, de modo que la numeracion no se solapa con la de
+    ``INC-`` ni depende del id de la fila.
+    """
+    from sqlalchemy import func
+
+    from app.models.ticket import Ticket
+
+    count_prev = (
+        db.query(func.count(Ticket.id))
+        .filter(Ticket.tipo.in_(tipos_no_incidencia()[:3]))
+        .scalar()
+        or 0
+    )
+    for offset in range(MAX_INTENTOS_NUMERACION):
+        numero = count_prev + 1 + offset
+        candidato = f"{PREFIJO_SOLICITUD}{numero:03d}"
+        existe = (
+            db.query(Ticket).filter(Ticket.codigo == candidato).first()
+        )
+        if not existe:
+            return candidato
+    raise ConflictoNumeracionError(
+        "No se pudo asignar un correlativo libre para la familia %s"
+        % PREFIJO_SOLICITUD
+    )
+
+
+def _generar_codigo_gar(db, hu_o_caso_prueba: str) -> str:
+    """``GAR_<HU>_<NNN>``: correlativo 3 digitos por HU."""
+    from sqlalchemy import func
+
+    from app.models.ticket import Ticket, TipoIncidencia
+
+    count_prev = (
+        db.query(func.count(Ticket.id))
+        .filter(
+            Ticket.tipo == TipoIncidencia.RESULTADO_PRUEBAS,
+            Ticket.hu_o_caso_prueba == hu_o_caso_prueba,
+        )
+        .scalar()
+        or 0
+    )
+    hu_trunc = (hu_o_caso_prueba or "")[:MAX_HU_EN_CODIGO]
+    for offset in range(MAX_INTENTOS_NUMERACION):
+        numero = count_prev + 1 + offset
+        candidato = "%s%s%s%03d" % (
+            PREFIJO_RESULTADO_PRUEBAS, hu_trunc, SEPARADOR_GAR, numero
+        )
+        existe = (
+            db.query(Ticket).filter(Ticket.codigo == candidato).first()
+        )
+        if not existe:
+            return candidato
+    raise ConflictoNumeracionError(
+        "No se pudo asignar un correlativo libre para la HU %s" % hu_o_caso_prueba
+    )
+
+
+def generar_codigo_ticket(db, tipo, hu_o_caso_prueba: Optional[str] = None) -> str:
+    """Genera el codigo de un ticket segun su tipo.
+
+    Es la unica puerta de entrada: todas las rutas de creacion deben pasar
+    por aqui para que el prefijo no dependa del camino usado.
+
+    Args:
+        db: sesion de SQLAlchemy.
+        tipo: ``TipoIncidencia`` o su valor de texto (``"incidencia"``,
+            ``"solicitud"``, ``"problema"``, ``"cambio"``,
+            ``"resultado_pruebas"``).
+        hu_o_caso_prueba: HU o caso de prueba. Obligatorio (y solo usado)
+            cuando el tipo es ``resultado_pruebas``.
+
+    Returns:
+        El codigo generado.
+
+    Raises:
+        HuRequeridaError: si el tipo es ``resultado_pruebas`` y falta la HU.
+        ConflictoNumeracionError: si no se encuentra un correlativo libre.
+    """
+    enum = _normalizar_tipo(tipo)
+    from app.models.ticket import TipoIncidencia
+
+    if enum == TipoIncidencia.RESULTADO_PRUEBAS:
+        if not hu_o_caso_prueba:
+            raise HuRequeridaError()
+        return _generar_codigo_gar(db, hu_o_caso_prueba)
+
+    if enum in (TipoIncidencia.SOLICITUD, TipoIncidencia.PROBLEMA,
+                TipoIncidencia.CAMBIO):
+        return _generar_codigo_sol(db)
+
+    return _generar_codigo_inc(db)
diff --git a/app/main.py b/app/main.py
index 31bd269..586dd86 100644
--- a/app/main.py
+++ b/app/main.py
@@ -659,21 +659,25 @@ async def ticket_crear(request: Request):
             prioridad_enum = Prioridad.MEDIA
 
         # === Generacion del codigo del ticket ===
-        # Regla:
-        #   - Tipo "resultado_pruebas" ? el codigo sigue el formato
-        #     ``GAR_<HU>_<NNN>`` donde ``<HU>`` es el contenido del campo
-        #     "HU o Caso de Prueba Asociado" y ``<NNN>`` es un correlativo
-        #     3-digitos POR HU (cuenta cuantos tickets de tipo
-        #     resultado_pruebas existen ya con esa misma HU).
-        #     Ejemplo: 1er ticket para la HU "SC_5.4" ? "GAR_SC_5.4_001".
-        #   - Cualquier otro tipo ? se usa el formato correlativo INC-NNN.
+        # La regla vive UNICAMENTE en ``app/core/codigo_ticket.py`` (SSOT):
+        #   - tipo "resultado_pruebas" ? ``GAR_<HU>_<NNN>`` (correlativo por HU)
+        #   - tipo "solicitud" / "problema" / "cambio" ? ``SOL-NNN``
+        #     (familia propia: NO son incidencias y nunca se suman en el
+        #     bloque de incidencias del dashboard)
+        #   - tipo "incidencia" ? ``INC-NNN`` (correlativo por id maximo)
         # Se valida que cuando tipo == resultado_pruebas venga el campo
         # hu_o_caso_prueba (es obligatorio en ese caso).
-        from sqlalchemy import func
-        if tipo_enum == TipoIncidencia.RESULTADO_PRUEBAS:
-            if not hu_o_caso_prueba:
-                return HTMLResponse(
-                    '''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">
+        from app.core.codigo_ticket import (
+            ConflictoNumeracionError,
+            HuRequeridaError,
+            generar_codigo_ticket,
+        )
+
+        try:
+            codigo = generar_codigo_ticket(db, tipo_enum, hu_o_caso_prueba)
+        except HuRequeridaError:
+            return HTMLResponse(
+                '''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">
                       <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
                         <h3 class="text-lg font-semibold text-red-700 mb-2">Falta HU o Caso de Prueba</h3>
                         <p class="text-sm text-slate-600 mb-4">
@@ -685,50 +689,28 @@ async def ticket_crear(request: Request):
                         <button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>
                       </div>
                     </div>''',
-                    status_code=400,
-                )
-            # Contar tickets previos con la misma HU y tipo=resultado_pruebas
-            # para determinar el siguiente correlativo (001, 002, 003...).
-            count_prev = db.query(func.count(Ticket.id)).filter(
-                Ticket.tipo == TipoIncidencia.RESULTADO_PRUEBAS,
-                Ticket.hu_o_caso_prueba == hu_o_caso_prueba,
-            ).scalar() or 0
-            # Limitar el codigo al VARCHAR(20) del modelo.
-            #   "GAR_"   = 4 chars fijos
-            #   "_NNN"   = 4 chars fijos
-            #   ? quedan 12 chars para la HU; el resto se trunca.
-            hu_trunc = hu_o_caso_prueba[:12]
-            codigo = None
-            # Bucle de reintentos por si hay condicion de carrera entre dos
-            # peticiones simultaneas para la misma HU.
-            for offset in range(5):
-                candidato_num = count_prev + 1 + offset
-                candidato = f"GAR_{hu_trunc}_{candidato_num:03d}"
-                existe = db.query(Ticket).filter(
-                    Ticket.codigo == candidato
-                ).first()
-                if not existe:
-                    codigo = candidato
-                    break
-            if not codigo:
-                return HTMLResponse(
-                    f'''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">
+                status_code=400,
+            )
+        except ConflictoNumeracionError:
+            detalle_hu = (
+                '<span class="font-mono px-1 py-0.5 rounded bg-slate-100">%s</span>'
+                % hu_o_caso_prueba
+                if hu_o_caso_prueba else ""
+            )
+            return HTMLResponse(
+                f'''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nuevo-ticket-error">
                       <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">
                         <h3 class="text-lg font-semibold text-red-700 mb-2">Conflicto de numeracion</h3>
                         <p class="text-sm text-slate-600 mb-4">
-                          No se pudo asignar un correlativo libre para la HU
-                          <span class="font-mono px-1 py-0.5 rounded bg-slate-100">{hu_o_caso_prueba}</span>
+                          No se pudo asignar un correlativo libre
+                          {detalle_hu}
                           tras varios intentos. Refresque la pagina e intente nuevamente.
                         </p>
                         <button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>
                       </div>
                     </div>''',
-                    status_code=400,
-                )
-        else:
-            # Formato compacto INC-NNN correlativo por id (igual que antes).
-            ultimo = db.query(func.max(Ticket.id)).scalar() or 0
-            codigo = f"INC-{(ultimo + 1):03d}"
+                status_code=400,
+            )
 
         # Parsear fecha de vencimiento (input type="date" => "YYYY-MM-DD")
         fecha_vencimiento_dt = None
diff --git a/app/services/ticket_service.py b/app/services/ticket_service.py
index 472fd23..7b34d6a 100644
--- a/app/services/ticket_service.py
+++ b/app/services/ticket_service.py
@@ -529,14 +529,16 @@ class TicketService:
                     codigo="SIN_ESTADO_INICIAL",
                 )
 
-        # Generar codigo unico
-        codigo = self._generar_codigo_ticket()
+        # Generar codigo unico. El codigo depende del TIPO (INC-, SOL- o
+        # GAR_<HU>_<NNN>), asi que el tipo se resuelve antes.
+        tipo_ticket = datos.get("tipo", "incidencia")
+        codigo = self._generar_codigo_ticket(tipo_ticket, datos.get("hu_o_caso_prueba"))
 
         ticket = Ticket(
             codigo=codigo,
             titulo=titulo,
             descripcion=datos.get("descripcion") or "",
-            tipo=datos.get("tipo", "incidencia"),
+            tipo=tipo_ticket,
             prioridad=datos.get("prioridad", "media"),
             estado_id=estado_asignado.id,
             creador_id=usuario.id,
@@ -661,16 +663,21 @@ class TicketService:
 
         return ticket
 
-    def _generar_codigo_ticket(self) -> str:
-        """Genera un codigo legible tipo ``INC-123`` (sin prefijo GRM ni ano).
+    def _generar_codigo_ticket(self, tipo="incidencia", hu_o_caso_prueba=None) -> str:
+        """Genera el codigo del ticket con la regla unica del proyecto.
 
-        Formato: ``INC-{N:03d}`` donde N es el siguiente correlativo basado
-        en el ID maximo actual de la tabla. Esto reemplaza al antiguo
-        ``GRM-INC-YYYY-NNNNNN`` y alinea con el formato compacto pedido.
+        Delegacion en ``app/core/codigo_ticket.py`` (SSOT):
+
+          * ``incidencia``          ? ``INC-NNN``
+          * ``solicitud``/``problema``/``cambio`` ? ``SOL-NNN``
+          * ``resultado_pruebas``   ? ``GAR_<HU>_<NNN>``
+
+        Antes este metodo generaba SIEMPRE ``INC-NNN`` ignorando el tipo,
+        de modo que una Solicitud, un Problema o un Cambio se creaban con
+        codigo de incidencia.
         """
-        from sqlalchemy import func
-        max_id = self.db.query(func.max(Ticket.id)).scalar() or 0
-        return f"INC-{(max_id + 1):03d}"
+        from app.core.codigo_ticket import generar_codigo_ticket
+        return generar_codigo_ticket(self.db, tipo, hu_o_caso_prueba)
 
     # ----------------------------------------------------------------------
     #  Listar y obtener
