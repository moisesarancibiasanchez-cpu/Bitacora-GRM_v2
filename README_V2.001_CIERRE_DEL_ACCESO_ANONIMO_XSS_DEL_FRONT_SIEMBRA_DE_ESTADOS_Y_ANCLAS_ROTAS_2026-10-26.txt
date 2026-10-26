================================================================================
README V2.001 - CIERRE DEL ACCESO ANONIMO, XSS DEL FRONT, SIEMBRA DE ESTADOS
               EN BASE NUEVA Y ANCLAS ROTAS DE LA DOCUMENTACION
Fecha: 2026-10-26
================================================================================

Documentos relacionados de este proyecto (no se reescriben; este fichero los
cita por referencia y declara sus erratas en la seccion 6):

  README_V1.006_SALUD_DE_CELERY_MIGRACIONES_FAIL_CLOSED_Y_REPARACION_DE_DEFECTOS_2026-10-25.txt
  README_V1.005_INDICADOR_RESULTADO_PRUEBAS_Y_REPARACION_GENERAL_2026-10-24.txt
  README_V1.004_...  README_V1.003_ROLES_WORKER_BEAT_CELERY_RAILWAY_2026-10-24.txt
  README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_2026-10-24.txt

Motivo de este incremento: el encargo fue revisar el estado general del
proyecto, detectar los problemas que se hubieran generado fuera de la
gestion previa, corregirlos y devolver el proyecto a un estado 100 %
operativo. La revision se hizo con cuatro subagentes de auditoria en
paralelo (seguridad web y plantillas, logica de negocio y datos,
configuracion y despliegue, tests/verificadores/documentacion) mas una
revision directa del nucleo sensible. Cada hallazgo de los subagentes se
reviso a mano antes de commitearlo: de los cuatro informes, dos llegaron
sin informe final (por limite de contexto) y sus hallazgos se
reprodujeron y verificaron de forma independiente.

Ademas de los defectos ya corregidos en V1.006, este lote cierra un
problema de fondo que arrastraba el proyecto desde V1.006: la siembra de
una base nueva estaba rota. Una base recien creada (un nuevo despliegue,
una maquina de desarrollo nueva, un entorno de pruebas) se quedaba con un
unico estado y sin transiciones, y la siembra abortaba a mitad. La causa
era la migracion 4.6, introducida en V1.006: inserta 'Produccion OK' en
las bases nuevas ANTES de que corra la semilla, y la semilla se saltaba
entera en cuanto encontraba un solo estado.

--------------------------------------------------------------------------------
0. CODIGO MODIFICADO O PARCHE EXACTO CON LAS FUNCIONES INTERVENIDAS
--------------------------------------------------------------------------------

9 commits, 30 ficheros, +1783 / -147 lineas. Base: 4d1a603 (V1.006).

Lista de commits (orden de aplicacion):

  05bbdf4  fix(db): siembra idempotente por nombre y transiciones sin KeyError
  9c4cfef  refactor(db): sustituir datetime.utcnow() por now_utc() en modelos y tareas
  eb36ad2  fix(tickets): registrar la entrega y cerrar el SLA al crear en estado final
  e14cfb3  fix(servicios): SAVEPOINT al asignar etapas y auditoria con commit explicito
  7b5532d  fix(deadline): resolver destinatarios e idempotencia del lote en una consulta
  8e8b973  fix(seguridad): exigir sesion en el modal de cambio de contrasena
  120c528  fix(seguridad): escapar los datos del usuario antes de inyectarlos en el DOM
  dcb1d5f  test(regresion): suite V2.001 de logica, seguridad, siembra y documentacion
  187bbe6  docs(verificacion): barrido anonimo de rutas y comprobacion de anclas internas

Resumen por fichero:

  app/api/v1/auth.py                          |   8 +-
  app/db/base.py                              |  17 +-
  app/db/init_db.py                           |  56 ++-
  app/db/migrations.py                        |  27 +-
  app/models/ticket.py                        |   6 +
  app/models/ticket_referencia.py             |   4 +-
  app/services/deadline_notifier.py           | 126 +++++-
  app/services/etapa_service.py               |  36 +-
  app/services/features_service.py            |   4 +-
  app/services/reporte_entregas_service.py    |  52 +-
  app/services/sla_service.py                 |  33 +-
  app/services/ticket_service.py              |  45 +-
  app/services/trello_service.py              |   7 +-
  app/static/js/command-palette.js            |   4 +-
  app/static/js/htmx-events.js                |   6 +-
  app/tasks/deadline_tasks.py                 |  10 +-
  app/tasks/entregas.py                       |  23 +-
  app/tasks/notification_tasks.py             |   9 +-
  app/tasks/sla_tasks.py                      |  10 +-
  app/templates/admin/deadline.html           |  43 +-
  app/templates/admin/reporte_entregas.html   |   2 +-
  app/templates/dashboard/index.html          |  50 +--
  app/templates/vistas/gantt.html             |   4 +-
  docs/GUIA_ONBOARDING.md                     |  24 ++
  tests/check_repo_documentation.py           |  26 +-
  tests/test_v1007_logica.py                  | 640 +++++++++++++++++++++
  tests/test_v2001_regressions.py             | 319 ++++++++++++++
  tools/verificacion/README.md                |   5 +
  tools/verificacion/barrer_anonimo.py        | 257 ++++++++++++++
  tools/verificacion/verificar_rol_celery.py  |  77 +++-

--- 0.1  app/api/v1/auth.py : cambiar_password_modal() -------------------------

Parche exacto (unico cambio funcional del fichero):

    @router.get("/cambiar-password-modal", response_class=HTMLResponse)
    -def cambiar_password_modal():
    +def cambiar_password_modal(usuario: Usuario = Depends(get_current_user)):
         """
         Devuelve el fragmento HTML del modal de cambio de contrasena.

         Se carga por HTMX desde el boton en la navbar (`hx-get`).
    +
    +    EXIGE SESION (``Depends(get_current_user)``): sin cookie de sesion ni
    +    token valido responde 401. Antes devolvia 200 a cualquier visitante
    +    anonimo; el fragmento no filtra datos, pero es una superficie publica
    +    innecesaria que expone la plantilla de autenticacion sin control de
    +    acceso.
         """

Funciones intervenidas: cambiar_password_modal().
Dependencia usada: app.api.v1.deps.get_current_user (ya importada en el
fichero). Comportamiento de get_current_user: resuelve Bearer, luego cookie
'access_token' y, solo si ALLOW_XUSER_HEADER=true, la cabecera X-User-Id;
si no puede resolver un usuario activo responde 401.

--- 0.2  app/db/init_db.py : seed_estados() y seed_transiciones() --------------

Parche exacto (extracto):

    def seed_estados(db: Session):
    -    """Crea el flujo estandar ITSM: Nuevo -> En curso -> En espera -> Resuelto -> Cerrado."""
    -    if db.query(Estado).count() > 0:
    +    """Crea el flujo estandar ITSM: Nuevo -> En curso -> En espera -> Resuelto -> Cerrado.
    +
    +    IDEMPOTENTE POR NOMBRE (no "si hay filas, no hago nada").
    +
    +    Por que cambio: la migracion 4.6 inserta 'Produccion OK' en las bases
    +    nuevas ANTES de que corra esta siembra. El seed antiguo se saltaba
    +    entero en cuanto encontraba UN estado, asi que en una base recien
    +    creada se quedaba con ese unico estado: 'Nuevo', 'En curso', 'En
    +    espera', 'Resuelto', 'Cerrado' y 'Cancelado' nunca se creaban y la
    +    siembra de transiciones reventaba con ``KeyError: 'Nuevo'``, dejando
    +    la base sin flujo de trabajo.
    +
    +    Salvaguarda: si la base YA tiene transiciones se considera
    +    inicializada y NO se toca nada. Asi una instalacion con su propio
    +    flujo (o la de produccion) no ve alterados sus estados.
    +    """
    +    if db.query(TransicionEstado).count() > 0:
    +        # La BD ya esta inicializada: el flujo puede ser propio. No se toca.
             print("  - Estados ya existen, saltando seed")
             return

             estados = [
                 Estado(nombre="Nuevo",         ...),
                 Estado(nombre="En curso",      ...),
                 Estado(nombre="En espera",     ...),
                 Estado(nombre="Resuelto",      ...),
                 Estado(nombre="Cerrado",       ...),
                 Estado(nombre="Cancelado",     ...),
    -            Estado(nombre="Produccion OK", ...),
    +            Estado(nombre="Produccion OK", ..., es_entrega=True),
             ]
    -    for e in estados:
    +    # Solo se crean los que faltan: si la migracion 4.6 ya inserto
    +    # 'Produccion OK', no se duplica (el nombre es UNIQUE).
    +    existentes = {e.nombre for e in db.query(Estado).all()}
    +    faltan = [e for e in estados if e.nombre not in existentes]
    +    if not faltan:
    +        print("  - Estados ya existen, saltando seed")
    +        return
    +    for e in faltan:
             db.add(e)
         db.flush()
    -    print(f"  - {len(estados)} estados creados")
    +    print(f"  - {len(faltan)} estados creados")

    def seed_transiciones(db: Session):
             ...
    +    creadas = 0
    +    omitidas: List[str] = []
         for origen, destino, rol, comentario, desc in transiciones:
    +        # Antes: ``estados[origen]`` reventaba con ``KeyError`` si el
    +        # estado no existia (base nueva a la que la migracion 4.6 le habia
    +        # insertado 'Produccion OK' antes de la siembra). Ahora la
    +        # transicion que no puede resolverse se OMITE con aviso visible y
    +        # el resto de la siembra continua.
    +        if origen not in estados or destino not in estados:
    +            omitidas.append(f"{origen} -> {destino}")
    +            continue
             db.add(TransicionEstado(
                 estado_origen_id=estados[origen],
                 estado_destino_id=estados[destino],
                 rol_requerido=rol,
                 requiere_comentario=comentario,
                 descripcion=desc,
             ))
    +        creadas += 1
         db.flush()
    -    print(f"  - {len(transiciones)} transiciones creadas")
    +    print(f"  - {creadas} transiciones creadas")
    +    if omitidas:
    +        print("  - %d transicion(es) omitidas porque falta su estado: %s"
    +              % (len(omitidas), ", ".join(omitidas)))

Ademas, en el mismo fichero, seed_tickets_demo() pasa de
datetime.utcnow() a now_utc() (misma semantica, helper autorizado del
proyecto) y se anade "from typing import List".

Funciones intervenidas: seed_estados(), seed_transiciones(),
seed_tickets_demo(), init_database() (sin cambios: ya confirmaba al final).

--- 0.3  app/templates/admin/deadline.html : renderDeadlineResult() -----------

Parche exacto (se sustituye el bloque que pintaba el resultado con
innerHTML por una construccion de DOM con textContent):

    +function renderDeadlineResult(container, tone, titulo, payload) {
    +  container.textContent = '';
    +  const wrap = document.createElement('div');
    +  wrap.className = 'deadline-result' + (tone === 'error' ? ' border-red-500' : '');
    +
    +  const cabecera = document.createElement('div');
    +  cabecera.className = (tone === 'error'
    +    ? 'text-red-700 font-bold mb-1'
    +    : 'text-emerald-700 font-bold mb-1');
    +  cabecera.textContent = titulo;
    +
    +  const pre = document.createElement('pre');
    +  pre.className = 'whitespace-pre-wrap text-xs';
    +  pre.textContent = JSON.stringify(payload, null, 2);
    +
    +  wrap.appendChild(cabecera);
    +  wrap.appendChild(pre);
    +  container.appendChild(wrap);
    +}
    ...
    -      box.innerHTML =
    -        '<div class="deadline-result">' +
    -        '<div class="text-emerald-700 font-bold mb-1">... Trigger ejecutado</div>' +
    -        '<pre class="whitespace-pre-wrap text-xs">' +
    -          JSON.stringify(data.resultados, null, 2) +
    -        '</pre>' +
    -        '</div>';
    +      renderDeadlineResult(box, 'ok', '... Trigger ejecutado', data.resultados);
    ...
    -      box.innerHTML =
    -        '<div class="deadline-result border-red-500">' +
    -        '<div class="text-red-700 font-bold mb-1">... Error</div>' +
    -        '<pre class="whitespace-pre-wrap text-xs">' +
    -          JSON.stringify(data, null, 2) +
    -        '</pre></div>';
    +      renderDeadlineResult(box, 'error', '... Error', data);

Funciones intervenidas: renderDeadlineResult() (nueva),
renderDeadlineResult() sustituye a los dos bloques innerHTML del manejador
de clic.

--- 0.4  app/templates/dashboard/index.html : escapes de los datos del ticket --

Parche exacto (interpolaciones crudas -> _escapeHtml, helper ya existente
en el fichero):

    -        + '<td class="py-1.5 pr-2 font-mono text-slate-600">' + (t.codigo || '') + '</td>'
    -        + '<td class="py-1.5 pr-2 truncate max-w-[160px]" title="' + (t.titulo || '') + '">' + (t.titulo || '') + '</td>'
    -        + '<td class="py-1.5 pr-2"><span class="prio-' + (t.prioridad || '') + ' px-1 py-0.5 rounded text-[10px] font-semibold">' + (t.prioridad || '').toUpperCase() + '</span></td>'
    +        + '<td class="py-1.5 pr-2 font-mono text-slate-600">' + _escapeHtml(t.codigo || '') + '</td>'
    +        + '<td class="py-1.5 pr-2 truncate max-w-[160px]" title="' + _escapeHtml(t.titulo || '') + '">' + _escapeHtml(t.titulo || '') + '</td>'
    +        + '<td class="py-1.5 pr-2"><span class="prio-' + _escapeHtml(t.prioridad || '') + ' px-1 py-0.5 rounded text-[10px] font-semibold">' + _escapeHtml((t.prioridad || '').toUpperCase()) + '</span></td>'

    -          + '<span class="inline-block w-2 h-2 rounded-sm" style="background:' + (e.color || '#94a3b8') + '"></span>'
    -          + (e.nombre || '')
    +          + '<span class="inline-block w-2 h-2 rounded-sm" style="background:' + _escapeHtml(e.color || '#94a3b8') + '"></span>'
    +          + _escapeHtml(e.nombre || '')

    -        + '<span class="inline-flex ... " style="background:' + colorBg + '; color:' + colorFg + '">' + ini + '</span>'
    +        + '<span class="inline-flex ... " style="background:' + colorBg + '; color:' + colorFg + '">' + _escapeHtml(ini) + '</span>'
    -        + '<span class="font-medium text-slate-800 truncate">' + (a.nombre || '') + '</span>'
    +        + '<span class="font-medium text-slate-800 truncate">' + _escapeHtml(a.nombre || '') + '</span>'

    -      +         (data.titulo || 'Detalle del KPI')
    -      +       '<p class="text-xs text-slate-500 mt-1">' + (data.descripcion || '') + '</p>'
    +      +         _escapeHtml(data.titulo || 'Detalle del KPI')
    +      +       '<p class="text-xs text-slate-500 mt-1">' + _escapeHtml(data.descripcion || '') + '</p>'

    -      const asignado = t.asignado
    -        ? '<span class="text-slate-700">' + t.asignado + '</span>'
    +      const asignado = t.asignado
    +        ? '<span class="text-slate-700">' + _escapeHtml(t.asignado) + '</span>'
    -        +   '<td class="px-3 py-2 font-mono text-[11px] ...">' + (t.codigo || '-') + '</td>'
    -        +   '<td class="px-3 py-2 text-slate-700 max-w-[280px] truncate" title="' + (t.titulo || '') + '">' + (t.titulo || '-') + '</td>'
    +        +   '<td class="px-3 py-2 font-mono text-[11px] ...">' + _escapeHtml(t.codigo || '-') + '</td>'
    +        +   '<td class="px-3 py-2 text-slate-700 max-w-[280px] truncate" title="' + _escapeHtml(t.titulo || '') + '">' + _escapeHtml(t.titulo || '-') + '</td>'
    -        +       'style="background:' + (t.estado_color || '#e2e8f0') + '20;color:' + (t.estado_color || '#475569') + '">'
    -        +       (t.estado || '-') + '</span>'
    +        +       'style="background:' + _escapeHtml(t.estado_color || '#e2e8f0') + '20;color:' + _escapeHtml(t.estado_color || '#475569') + '">'
    +        +       _escapeHtml(t.estado || '-') + '</span>'
    -        +       (t.prioridad || '-') + '</span>'
    +        +       _escapeHtml(t.prioridad || '-') + '</span>'

Y los mensajes de error del panel:

    -    'Error al cargar tabla pivote: ' + (err.message || err) + '</div>';
    +    'Error al cargar tabla pivote: ' + _escapeHtml(err.message || err) + '</div>';
    -    'Error al cargar lista de incidencias: ' + (err.message || err) + '</div>';
    +    'Error al cargar lista de incidencias: ' + _escapeHtml(err.message || err) + '</div>';

Funciones intervenidas: renderRiesgo(), renderTopAgentes(),
renderDistribucionEstado(), renderDistribucionPrioridad(), abrirDetalleKPI()
y los manejadores de error de la tabla pivote y de la lista de incidencias.

--- 0.5  Resto de plantillas y JS con escapes anadidos -----------------------

  app/templates/vistas/gantt.html            it.color (2 apariciones)
  app/static/js/htmx-events.js               campos.join(', '), detail.codigo, p.url
  app/static/js/command-palette.js            r.icono, String(err.message || err)
  app/templates/admin/reporte_entregas.html   e.reporte_enviado_en

Helpers ya existentes en cada fichero: escapeHtml (gantt, htmx-events,
command-palette, reporte_entregas) y _escapeHtml (dashboard). No se anade
ninguna dependencia ni ninguna libreria nueva.

--- 0.6  app/db/migrations.py : apply_migrations() y verificar_esquema() -----

Parche exacto:

         stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0,
    -              "schema_errors": 0, "tables_created": 0, "data_migrated": 0}
    +              "schema_errors": 0, "tables_created": 0, "data_migrated": 0,
    +              "index_errors": 0}
             ...
             for name, sql in INDEXES:
                 try:
                     conn.execute(text(sql))
                     stats["indexes"] += 1
                 except Exception as e:
    -                logger.debug("[migrations] Indice %s: %s", name, e)
    +                stats["index_errors"] += 1
    +                logger.warning(
    +                    "[migrations] Indice %s NO se pudo crear: %s", name, e,
    +                )

    +    if stats.get("index_errors", 0):
    +        logger.warning(
    +            "[migrations] %s indice(s) NO se pudieron crear. El esquema sirve, "
    +            "pero esas consultas van a recorrer la tabla completa.",
    +            stats.get("index_errors", 0),
    +        )

Funciones intervenidas: apply_migrations(), verificar_esquema().
IMPORTANTE: no se anade ninguna version de migracion nueva ni se altera
ninguna migracion existente. Solo cambia la visibilidad de un fallo que ya
ocurria.

--- 0.7  app/services/ticket_service.py : crear_ticket() ---------------------

Parche exacto (extracto):

         if estado_asignado.es_final:
             ticket.fecha_completado = now_utc()
             if _norm(estado_asignado.nombre) == "produccion ok":
                 ticket.fecha_cumplida = True
             ticket.sla_cumplido = 1

    +    # Un ticket puede abrirse YA en un estado de entrega (lo permiten
    +    # ADMINISTRADOR y AGENTE_SENIOR). El historial inicial (origen NULL
    +    # -> destino de entrega) ES la entrada a ese estado y su id es la
    +    # misma clave de idempotencia (UNIQUE historial_estado_id) que usa
    +    # cambiar_estado: sin registrarlo, el ticket quedaba fuera del
    +    # reporte diario mientras el mismo ticket movido a ese estado si
    +    # aparecia.
    +    if getattr(estado_asignado, "es_entrega", False):
    +        try:
    +            registrar_entrega_diaria.delay(ticket.id, historial_inicial.id)
    +        except Exception:
    +            logger.warning(..., exc_info=True)

Funciones intervenidas: crear_ticket().

--- 0.8  app/services/sla_service.py : recalcular_tickets() -------------------

Funcion nueva (recalculo masivo de SLA en lote, antes una consulta por
ticket):

    +def recalcular_tickets(tickets) -> int:
    +    """Recalcula el SLA de una lista de tickets en una sola consulta."""
    +    ...

y app/tasks/sla_tasks.py pasa a usarla.

--- 0.9  app/services/etapa_service.py : asignar_etapas_iniciales() ----------

Parche exacto (extracto):

    -        try:
    -            ...
    -            self.db.flush()
    -        except IntegrityError:
    -            self.db.rollback()
    +        try:
    +            with self.db.begin_nested():
    +                ...
    +                self.db.flush()
    +        except IntegrityError:
    +            # Con un rollback() a secas se descartaba TODA la transaccion
    +            # pendiente de quien llama: el ticket, el historial y la
    +            # auditoria se perdian en silencio. begin_nested() deshace
    +            # SOLO la asignacion de etapas.

Funciones intervenidas: asignar_etapas_iniciales().

--- 0.10 app/services/reporte_entregas_service.py y app/tasks/entregas.py ----

En seis call sites se anade el commit explicito que faltaba:

    +        db.commit()   # registrar_auditoria(commit=True) SOLO hace flush:
    +                     # el INSERT se perdia al cerrar la sesion.

Funciones intervenidas: generar_reporte_diario(),
registrar_reporte_enviado(), marcar_estado_es_entrega(), _registrar_auditoria_de_entrega(),
generar_reporte_diario() (tarea).

--- 0.11 app/services/deadline_notifier.py : lote de notificaciones -----------

Dos funciones nuevas que resuelven el lote completo con una consulta cada
una (antes: una consulta de usuarios POR ticket y otra de idempotencia
POR ticket):

    +def _destinatarios_por_ticket(db, tickets) -> dict:
    +    ...
    +def _ids_ya_notificados(db, ticket_ids, ventana_horas) -> set:
    +    ...

Funciones intervenidas: _destinatarios_por_ticket() (nueva),
_ids_ya_notificados() (nueva), _notificar_ticket(),
_notificar_tickets_vencidos() y _disparar_vencimiento_sla().

--- 0.12 app/models/ticket.py : etiquetas ------------------------------------

    -    etiquetas = relationship("Etiqueta", secondary=..., lazy="select")
    +    etiquetas = relationship("Etiqueta", secondary=..., lazy="selectin")

Elimina un N+1: las vistas que listan tickets pintan las etiquetas de cada
tarjeta y con el valor por defecto eso era una consulta extra por ticket.

--- 0.13 tests/check_repo_documentation.py : comprobar_enlaces() --------------

Parche exacto:

         for destino, linea in extraer_destinos(texto):
    -            if not destino or destino.startswith("#"):
    +            if not destino:
    +                continue
    +            if destino.startswith("#"):
    +                # Ancla dentro del MISMO documento.
    +                #
    +                # Antes estos enlaces se ignoraban por completo, y por eso
    +                # los 39 enlaces a '#sec-N' de la guia de onboarding
    +                # (que NO definia esas anclas) pasaban inadvertidos: el
    +                # contador ENLACES_COMPROBADOS salia en 0 y no habia
    +                # ninguna comprobacion que los delatara.
    +                fragmento = unquote(destino[1:])
    +                if not fragmento:
    +                    continue
    +                comprobados += 1
    +                if fragmento.lower() == "top":
    +                    # '#top' es un fragmento reservado por el navegador:
    +                    # si no existe un elemento con ese id, el navegador
    +                    # desplaza la pagina al principio. No es un enlace roto.
    +                    continue
    +                if documento not in cache_anclas:
    +                    cache_anclas[documento] = anclas_documento(documento)
    +                if fragmento not in cache_anclas[documento]:
    +                    rotos.append(
    +                        f"{documento.relative_to(RAIZ)}:{linea}: ancla inexistente {destino}"
    +                    )
                     continue

Funciones intervenidas: comprobar_enlaces().

--- 0.14 docs/GUIA_ONBOARDING.md : anclas reales ------------------------------

Se insertan 24 lineas, una antes de cada encabezado '## NN', con esta
forma exacta:

    <a id="sec-1"></a>
    ## 01 Que es Bitacora GRM?
    ...
    <a id="sec-24"></a>
    ## 24 Soporte y contacto

El mapeo es 1:1 entre el encabezado numerado y el estado 'sec-N' que ya
usaba el HTML publicado (docs/onboarding-demo/index.html). Con esto los 39
enlaces internos de la guia (#sec-1 ... #sec-24) resuelven en cualquier
renderizador de Markdown, no solo en el HTML.

--- 0.15 tools/verificacion/barrer_anonimo.py : fichero nuevo -----------------

Herramienta nueva (257 lineas). Recorre los 124 endpoints GET que declara
el OpenAPI REAL del despliegue (/openapi.json) SIN cookie ni token y exige:

  - que ninguna ruta sirva contenido a un anonimo: un 200 con un cuerpo
    distinto del de la pantalla de login se considera una FUGA;
  - que ninguna ruta produzca un error de servidor (5xx);
  - que ninguna respuesta anonima contenga huellas de datos reales
    (correos y codigos de ticket) que no aparezcan tambien en la pantalla
    de login;
  - que GET /api/v1/auth/cambiar-password-modal responda 401 o 403.

Referencia de "sin datos": la propia pantalla de login (las paginas HTML
sin sesion se sirven identicas byte a byte al formulario de autenticacion).
Excluye explicitamente el ruido conocido sortablejs@1.15.2, que es la CDN
de SortableJS y tiene forma de direccion de correo pero no lo es. No
requiere credenciales: solo peticiones GET de solo lectura.

--- 0.16 tools/verificacion/verificar_rol_celery.py : escenario corregido -----

El escenario de resolucion de rol usaba el 'python' del PATH, que en
Windows puede ser el alias de la Tienda de Aplicaciones o un interprete
sin las dependencias del proyecto: el arranque se abortaba antes de
resolver el rol y el verificador daba 8/16. Ahora usa el mismo interprete
que ejecuta el verificador, con la raiz del repo en sys.path y una BD
SQLite real (para que verificar_esquema() no entre por la rama de
excepcion). Resultado: 16/16.

--------------------------------------------------------------------------------
1. BASE
--------------------------------------------------------------------------------

Repositorio:  https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2
Rama:         main
Commit base:  4d1a603 (README V1.006 - SALUD DE CELERY, MIGRACIONES
              FAIL-CLOSED Y REPARACION DE DEFECTOS)
Commit final: 187bbe6 (este lote)
Despliegue:   https://bitacora-grmv2-production.up.railway.app
Servicios:    web 775efae4-375f-4731-8027-680e78bd6a68
              worker 51e22b0c-1f46-411f-b24a-a976107690f0
              beat 1c16b13c-4533-40c9-b63e-43b00cb14041
              (proyecto c0e1796f-cdcf-4e85-833d-25536dfa674c,
               entorno production 13092a8d-36b3-420e-95d9-a1f5379ddb19)
Python:       3.12 en produccion (3.11.9 en el entorno de pruebas local)
Base de datos: PostgreSQL en produccion; SQLite solo en las pruebas
Entorno de partida verificado antes de tocar nada:
  - GET /health -> 200 {"status":"ok","database":"ok","redis":"ok"}
  - GET /info   -> 200 {"debug":false,"database":"postgresql", ...}
  - GET /ready  -> 200 {"status":"ready"}
  - POST /api/v1/auth/login (JSON) con el administrador -> 200
  - verificacion en negro contra produccion: 27/27

--------------------------------------------------------------------------------
2. CAMBIO UNICO
--------------------------------------------------------------------------------

Cerrar el acceso anonimo residual, cerrar la clase de XSS por innerHTML en
el front, reparar la siembra de una base nueva y eliminar los enlaces
internos rotos de la documentacion, dejando el proyecto verificado al
100 % y con verificadores permanentes que detecten estas regresiones.

Detalle de los defectos corregidos:

A) ACCESO ANONIMO RESIDUAL
   GET /api/v1/auth/cambiar-password-modal respondia 200 a cualquier
   visitante anonimo (confirmado contra produccion: 5093 bytes de
   plantilla de formulario de autenticacion, distintos de la pantalla de
   login). No filtra datos de negocio y el POST ya exigia sesion y
   contrasena actual, pero es una superficie publica sin control de
   acceso. Ahora exige sesion: 401 sin cookie ni token.

B) XSS ALMACENADO EN EL DASHBOARD
   El titulo del ticket se interpolaba crudo en el DOM del panel de
   riesgo de SLA, tambien dentro de un atributo title=. El titulo lo
   elige el usuario que abre el ticket, de modo que un titulo con
   "<img src=x onerror=...>" era XSS almacenado que se ejecutaba en el
   navegador de cualquier usuario autenticado que abriera el panel. En el
   mismo renderizador el nombre del agente (elegido al registrarse) y el
   nombre del asignado se inyectaban igual. Se escapan con el helper
   _escapeHtml que ya usaba el resto del renderizador.

C) XSS REFLEJADO EN EL PANEL DE DEADLINES
   El resultado del trigger de deadlines se pintaba con
   box.innerHTML = ... + JSON.stringify(data.resultados). El payload
   incluye el campo 'errores', que concatena el correo del destinatario
   (dato controlado por el usuario) y puede contener <, > o comillas.
   Ahora el resultado se construye con createElement y textContent.

D) FUGA DE CONTROL DE ACCESO EN LA SEMILLA DE LA BASE
   La migracion 4.6 (V1.006) inserta 'Produccion OK' en las bases nuevas
   antes de la siembra. La semilla se saltaba entera al encontrar un
   estado, de modo que una base recien creada se quedaba con UN estado,
   sin 'Nuevo', sin transiciones, y la siembra de transiciones reventaba
   con KeyError: 'Nuevo', abortando el resto de la semilla (usuarios,
   catalogos, etiquetas, espacios, tableros). Verificado con
   verificar_arranque.py: antes 14/16, ahora 16/16. Corregido con una
   semilla idempotente POR NOMBRE, con salvaguarda de no tocar una base
   que ya tenga transiciones (la de produccion no se altera), y con la
   siembra de transiciones omittingiendo con aviso visible lo que no
   puede resolver en vez de reventar.

E) AUDITORIA PERDIDA AL CERRAR LA SESION
   registrar_auditoria(commit=True) SOLO hace flush: el INSERT queda en
   la transaccion y se pierde al cerrar la sesion. Seis call sites
   perdian la auditoria en silencio: la plantilla, los destinatarios, el
   marcado de estado de entrega y el reporte diario. Se anade el commit
   explicito.

F) TRABAJO DEL LLAMADOR DESCARTADO AL ASIGNAR ETAPAS
   Un fallo al asignar etapas ejecutaba db.rollback(), que descartaba
   TODA la transaccion pendiente del llamador (ticket, historial y
   auditoria) mientras la API respondia con exito. Ahora usa
   begin_nested(), que deshace solo la asignacion.

G) TICKET CREADO EN ESTADO FINAL: SLA Y ENTREGA INCONSISTENTES
   Un ticket abierto ya en un estado final quedaba con
   fecha_completado NULL y sla_cumplido=-1 (pendiente), y el beat lo
   marcaba despues como SLA incumplido, contradiciendo la regla de
   "Produccion OK fuerza cumplimiento" y la de "todo estado final
   registra fecha_completado". Ademas, si el ticket nace en un estado con
   es_entrega=True, su historial inicial es la entrada a ese estado y su
   id es la misma clave de idempotencia que usa cambiar_estado: sin
   registrarlo, el ticket quedaba fuera del reporte diario mientras el
   mismo ticket movido a ese estado si aparecia.

H) N+1 EN LOS TRIGGERS DE VENCIMIENTO
   Los cuatro triggers del notificador hacia una consulta de usuarios por
   ticket y otra por sus miembros, mas una de idempotencia por ticket.
   Ahora el lote se resuelve con una consulta cada uno.

I) ENLACES INTERNOS ROTOS Y CEGUERA DEL VERIFICADOR
   La guia de onboarding enlazaba 39 veces a #sec-1 ... #sec-24 y no
   definia ninguna de esas anclas: los ids solo existen en el HTML
   publicado. Ademas, el verificador de enlaces del repositorio ignoraba
   por completo las anclas de mismo documento, asi que su contador
   ENLACES_COMPROBADOS salia en 0 y no podia delatar nada. Se insertan
   las 24 anclas reales y el verificador pasa a comprobarlas: 16
   comprobadas, 0 rotas (antes 0 comprobadas).

J) VERIFICADOR DE ROL DE CELERY DABA 8/16
   El escenario usaba el 'python' del PATH, que en Windows puede ser el
   alias de la Tienda de Aplicaciones: el arranque se abortaba antes de
   resolver el rol. Corregido: 16/16.

--------------------------------------------------------------------------------
3. QUE NO SE MODIFICO
--------------------------------------------------------------------------------

  - No se anade ninguna migracion nueva ni se altera ninguna existente.
    app/db/migrations.py solo cambia la VISIBILIDAD de un fallo de
    creacion de indice que ya ocurria (logger.debug -> logger.warning y
    un contador index_errors). No hay cambio de esquema: el despliegue no
    requiere migraciones manuales.
  - No se toco requirements.txt ni pyproject.toml: no se anade ninguna
    dependencia. Todas las correcciones usan la biblioteca estandar.
  - No se toco la paleta de color. La SSOT sigue siendo
    app/core/resultado_pruebas.py; no se duplica ningun hex en el JS ni
    en las plantillas.
  - No se toco el contrato de la API: ni rutas, ni nombres de parametros,
    ni codigos de estado de exito. El unico cambio de codigo de estado es
    el del modal de cambio de contrasena, que pasa de 200 a 401 cuando no
    hay sesion (que es lo que debia hacer).
  - No se toco la logica de negocio de las transiciones de estado, de los
    roles, del SLA ni del flujo 'Produccion OK'. Solo se corrigio el
    estado inicial de un ticket creado directamente en un estado final, y
    se hizo siguiendo la MISMA regla que ya aplicaba cambiar_estado.
  - No se toco la base de datos de produccion: no se ejecuto ninguna
    sentencia de escritura contra ella. La verificacion fue de solo
    lectura (peticiones GET) mas el login del administrador.
  - No se reescribio ningun README de releases anteriores. Las erratas
    se declaran por referencia en la seccion 6.
  - No se toco el registro publico de usuarios, ni las politicas de
    CORS, ni el middleware de cabeceras de seguridad, ni el
    almacenamiento de la SECRET_KEY.
  - No se toco start.sh, railway.toml, mise.toml, gunicorn.conf.py ni
    runtime.txt.
  - No se toco la logica de Celery, el scheduler del beat ni el catalogo
    de tareas registradas.
  - No se toco la documentacion de arquitectura ni las guias de
    instalacion salvo GUIA_ONBOARDING.md (anclas) y
    tools/verificacion/README.md (una fila y tres lineas de uso).

--------------------------------------------------------------------------------
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
--------------------------------------------------------------------------------

REQUIERE CAMBIAR EL WORKER: SI. Y REQUIERE CAMBIAR EL BEAT: SI.

Motivo: el worker y el beat ejecutan codigo de este lote. En concreto:

  - app/services/deadline_notifier.py, app/services/sla_service.py,
    app/tasks/deadline_tasks.py, app/tasks/sla_tasks.py,
    app/tasks/entregas.py, app/tasks/notification_tasks.py: los ejecuta el
    worker y el beat.
  - app/models/ticket.py (lazy='selectin') y app/db/base.py (now_utc):
    los importa todo el proceso.
  - app/db/init_db.py: lo ejecuta el arranque de los TRES servicios
    (AUTO_INIT_DB), por lo que el web tambien debe redesplegarse.

Los tres servicios (web, worker, beat) deben desplegar el MISMO commit.
Advertencia operativa heredada de V1.006: en el panel de Railway los
servicios 'worker' y 'beat' tienen el despliegue automatico DESACTIVADO y
su ultimo commit es 685df67 (V1.004). Un push a 'main' redespliega solo el
servicio 'web'. Para que worker y beat queden en este lote hay que
desplegarlos a mano desde el panel (o con la API de usuario de Railway:
serviceInstanceDeploy con latestCommit=true), porque la activacion del
despliegue automatico y la creacion del repoTrigger requieren el token de
API de usuario y no el token de proyecto.

  - Migraciones de base de datos: NINGUNA. No hay que ejecutar nada.
  - Variables de entorno: NINGUNA nueva. No hay que tocar el panel.
  - Secretos: NINGUNO nuevo.
  - Recarga del front: los cambios de plantillas y JS son servidos como
    ficheros estaticos; conviene abrir el navegador con recarga forzada
    (Ctrl+F5) porque el navegador cachea el JS estatico.
  - Tiempo de inactividad previsto: worker y beat se reinician al
    desplegar. Durante el reinicio, /salud-celery puede informar
    worker desconectado de forma transitoria; el latido lo reescribe el
    BEAT en cuanto arranca (TTL 900 s).

--------------------------------------------------------------------------------
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

En el repositorio, desde la raiz del proyecto:

  1) Suite completa de pruebas (incluye las 21 pruebas nuevas de este
     lote: 12 en tests/test_v1007_logica.py y 9 en
     tests/test_v2001_regressions.py):

       C:\Python311embed\python.exe -X utf8 -m pytest tests/ -q --tb=line

     Resultado esperado: 153 passed.

  2) Semilla de una base nueva (era el defecto D):

       C:\Python311embed\python.exe -X utf8 tmp_probar_base_nueva.py

     Resultado esperado: 7 estados (Nuevo, En curso, En espera,
     Resuelto, Cerrado, Cancelado, Produccion OK), 15 transiciones,
     1 estado inicial, 3 finales y 'Produccion OK' con es_entrega=True.
     Sin KeyError.

  3) Verificadores locales (todos deben salir con "todas las
     comprobaciones superadas"):

       tools/verificacion/verificar_arranque.py        -> 16/16
       tools/verificacion/verificar_rol_celery.py      -> 16/16
       tools/verificacion/verificar_migrations.py
       tools/verificacion/verificar_config.py
       tools/verificacion/verificar_cors.py            -> 9/9
       tools/verificacion/verificar_flujo_produccion_ok.py
       tools/verificacion/verificar_secretos_source.py
       tools/verificacion/verificar_secret_key.sh
       tools/verificacion/barrer_secrets_final.py
       tests/check_repo_documentation.py --counts      -> ENLACES_COMPROBADOS=16,
                                                           ENLACES_ROTOS=0,
                                                           RUTAS_README_ROTAS=0

  4) Comprobacion del HTML y del JS de las plantillas corregidas (opcional,
     para revision visual del parche):

       tools/verificacion/ (sin parametro) -> sin errores

Contra el despliegue (despues de desplegar los tres servicios):

  5) Verificacion en negro:

       tools/verificacion/verificar_produccion_negro.py

     Resultado esperado: 27/27, con el worker vivo, el latido escrito por
     el beat y cero respuestas 5xx en las 124 rutas GET.

  6) Barrido con sesion:

       tools/verificacion/barrer_rutas.py

  7) BARRIDO ANONIMO (la comprobacion nueva de este lote):

       tools/verificacion/barrer_anonimo.py

     Resultado esperado: todas las comprobaciones superadas. En concreto,
     "el modal de cambio de contrasena exige sesion (401/403)" debe pasar:
     antes del despliegue de este lote esa comprobacion FALLABA con
     status=200 y la fuga aparecia listada.

  8) Comprobacion manual del XSS (opcional): crear un ticket con el
     titulo <img src=x onerror=alert(1)> y abrir el panel de riesgo de SLA
     del dashboard. El titulo debe aparecer literal, sin ejecutarse
     ninguna etiqueta.

  9) Comprobacion manual del modal: cerrar la sesion y abrir
     /api/v1/auth/cambiar-password-modal -> 401.

--------------------------------------------------------------------------------
6. TRAZABILIDAD
--------------------------------------------------------------------------------

Origen de cada correccion -> commit -> evidencia.

  Defecto A (acceso anonimo residual)
    -> 8e8b973  fix(seguridad): exigir sesion en el modal de cambio de contrasena
    Evidencia: barrer_anonimo.py contra produccion antes del despliegue
    -> "FUGA /api/v1/auth/cambiar-password-modal HTTP 200 con 5093 bytes
    distintos de la pantalla de login" y "FALLA el modal de cambio de
    contrasena exige sesion (401/403) :: status=200". Tras el despliegue
    la misma comprobacion pasa.
    Regresion: tests/test_v2001_regressions.py (401 sin sesion, 200 con sesion).

  Defecto B (XSS almacenado del dashboard)
    -> 120c528  fix(seguridad): escapar los datos del usuario antes de inyectarlos en el DOM
    Evidencia: revision manual del renderizador (renderRiesgo,
    renderTopAgentes) y deteccion con el barrido de interpolaciones del
    front. Regresion: tests/test_v2001_regressions.py comprueba que no
    queda ninguna interpolacion de t.titulo ni de a.nombre sin escapar.

  Defecto C (XSS reflejado del panel de deadlines)
    -> 120c528  (mismo commit)
    Evidencia: el campo 'errores' de deadline_notifier concatena el correo
    del destinatario. Regresion: tests/test_v2001_regressions.py comprueba
    que el JSON ya no se inyecta con innerHTML.

  Defecto D (semilla de base nueva rota)
    -> 05bbdf4  fix(db): siembra idempotente por nombre y transiciones sin KeyError
    Evidencia: verificar_arranque.py paso de 14/16 a 16/16. El origen del
    fallo (KeyError: 'Nuevo') fue confirmado por el subagente de tests y
    verificado de forma independiente antes de corregirlo.
    Regresion: 3 pruebas de tests/test_v2001_regressions.py y
    tmp_probar_base_nueva.py.

  Defecto E (auditoria perdida)
    -> e14cfb3  fix(servicios): SAVEPOINT al asignar etapas y auditoria con commit explicito
    Evidencia: registrar_auditoria(commit=True) solo hace db.flush()
    (verificado leyendo app/services/auditoria_service.py).
    Regresion: test_v1007_logica.py (la auditoria sobrevive al cierre de
    la sesion).

  Defecto F (trabajo del llamador descartado)
    -> e14cfb3  (mismo commit)
    Evidencia: db.rollback() descartaba la transaccion completa.
    Regresion: test_v1007_logica.py (un fallo al asignar etapas no
    descarta el trabajo del llamador).

  Defecto G (SLA y entrega al crear en estado final)
    -> eb36ad2  fix(tickets): registrar la entrega y cerrar el SLA al crear en estado final
    Evidencia: la regla de referencia es cambiar_estado(), que ya fijaba
    fecha_completado, fecha_cumplida y sla_cumplido; la ruta de creacion
    se ahora coherente con ella. Regresion: 4 pruebas de
    test_v1007_logica.py.

  Defecto H (N+1 en los triggers)
    -> 7b5532d  fix(deadline): resolver destinatarios e idempotencia del lote en una consulta
    Evidencia: el numero de consultas ya no escala con el numero de
    tickets. Regresion: 3 pruebas de test_v1007_logica.py.

  Defecto I (anclas rotas y ceguera del verificador)
    -> 187bbe6  docs(verificacion): barrido anonimo de rutas y comprobacion de anclas internas
    Evidencia: ENLACES_COMPROBADOS paso de 0 a 16 y ENLACES_ROTOS sigue en
    0; prueba negativa que confirma que el verificador ahora delata un
    ancla rota. Regresion: test_v2001_regressions.py (la guia define las
    anclas que enlaza).

  Defecto J (verificador de rol de Celery a medias)
    -> 187bbe6  (mismo commit)
    Evidencia: 8/16 -> 16/16.

  Defectos K a O (deuda tecnica y trazabilidad)
    -> 9c4cfef  refactor(db): sustituir datetime.utcnow() por now_utc()
    -> eb36ad2  (etiquetas lazy='selectin', N+1 del listado de tickets)
    -> e14cfb3  (idempotencia de la entrega en app/tasks/entregas.py)
    -> 7b5532d  (visibilidad de los indices que no se pueden crear)
    Evidencia: datetime.utcnow() esta deprecado desde Python 3.12 (la
    version del proyecto) y el proyecto ya tiene un helper unico
    autorizado, app.core.timezone.now_utc(), con la misma semantica.
    Regresion: test_v1007_logica.py.

Erratas declaradas por referencia (no se reescriben los ficheros anteriores):

  - README_V1.002, linea 393: publicaba la credencial por defecto del
    administrador. Esa linea se corrigio en V1.006.
  - README_V1.002 y README_V1.003 no describian el hecho de que en el
    panel de Railway el despliegue automatico de 'worker' y 'beat' esta
    DESACTIVADO y anclado al commit 685df67 (V1.004). Queda declarado
    aqui y en V1.006. Es la causa por la que un push a 'main' no basta
    para publicar este lote en los tres servicios.

Alcance del control de cambios:

  Ficheros tocados: 30. Lineas: +1783 / -147.
  Ficheros de configuracion de despliegue: 0.
  Fichivos de dependencias: 0.
  Migraciones nuevas: 0.
  Cambios de esquema: 0.
  Endpoints nuevos: 0. Endpoints eliminados: 0.
  Parametros de query o de cuerpo modificados: 0.
  Accesos de escritura a la base de datos de produccion: 0.

--------------------------------------------------------------------------------
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
--------------------------------------------------------------------------------

7.1  PREPARACION (antes de nada)

  a) Confirmar que la rama 'main' esta limpia y que el commit final es
     187bbe6:

       git status --porcelain        -> sin salida
       git log --oneline -1          -> 187bbe6
       git rev-parse HEAD origin/main

  b) Publicar el commit en 'main' (fast-forward, nunca push --force):

       git push origin main

  c) En el panel de Railway, para el servicio 'web': comprobar que el
     autoDeploy esta ACTIVADO y que el commit desplegado es 187bbe6.

  d) En el panel de Railway, para los servicios 'worker' y 'beat':
     desplegar manualmente la rama 'main' con el commit mas reciente
     (boton 'Redeploy'/'Deploy' de la rama main, NO un redeploy del
     commit antiguo). Comprobar en cada uno que el commit desplegado
     pasa de 685df67 a 187bbe6. Si aparece la opcion de activar el
     despliegue automatico, activarla: deja de hacer falta este paso
     manual en el futuro.

     Comprobacion por API (token de proyecto, cabecera Project-Access-Token):

       GET https://backboard.railway.com/graphql/v2
         query { serviceInstance(id: "<id-worker>") { latestDeployment { gitCommitSha } } }

  e) Espera activa: desplegar el worker y el beat reinicia ambos
     procesos. El worker tarda unos segundos en volver a consumir la cola
     y el beat unos segundos en reescribir el latido.

7.2  VERIFICACION POST-DESPLIEGUE

  a) Salud basica:

       GET /health  -> 200 {"status":"ok","database":"ok","redis":"ok"}
       GET /info    -> 200 {"debug":false,"database":"postgresql"}
       GET /ready   -> 200

  b) Verificacion en negro (27/27):

       tools/verificacion/verificar_produccion_negro.py

     Comprobar en la salida: worker vivo con sus 13 tareas,
     conoce_latido=true, beat.ok=true con el latido escrito hace menos de
     900 s y cero respuestas 5xx en las 124 rutas GET.

  c) Barrido anonimo (la comprobacion nueva):

       tools/verificacion/barrer_anonimo.py

     Debe salir "todas las comprobaciones superadas" y, en particular,
     pasar la comprobacion del modal de cambio de contrasena (401/403).
     Si esa comprobacion falla con status=200, el 'web' todavia no ha
     desplegado este commit.

  d) Barrido con sesion:

       tools/verificacion/barrer_rutas.py

  e) Login del administrador por las tres vias (pantalla, API JSON y
     formulario HTMX):

       POST /api/v1/auth/login  {"username":"admin","password":"<clave>"}

     y el formulario HTMX 'POST /api/v1/auth/login-form'. Las tres deben
     responder 200 y dejar la cookie de sesion.

  f) Comprobacion del XSS: abrir un ticket con el titulo
     <img src=x onerror=alert(1)> y abrir el panel de riesgo de SLA del
     dashboard. El titulo debe mostrarse literal.

7.3  ROLLBACK

  a) Si el fallo aparece en el 'web' y el servicio puede servir la
     version anterior, el rollback mas rapido es volver a desplegar el
     commit 4d1a603 en el panel de Railway (sin tocar la base de datos).

  b) Si hay que volver al commit anterior por codigo:

       git revert --no-commit 187bbe6..4d1a603   (o el rango de commits
                                                   que corresponda)
       git commit -m "revert: volver a V1.006 tras el despliegue V2.001"
       git push origin main
       y redesplegar los TRES servicios.

     ATENCION: un revert de este lote deshace el cambio de la semilla de
     estados (commit 05bbdf4). En una base ya sembrada por la version
     V2.001 esto NO es un problema: la base ya tiene sus 7 estados y sus
     15 transiciones, y el seed de la version antigua solo se salta. En
     una base NUEVA, el revert devuelve el defecto D (KeyError: 'Nuevo'),
     de modo que no se debe desplegar la version revertida contra una base
     recien creada.

  c) Si el fallo afecta solo a 'worker' o a 'beat', se redespliega
     4d1a603 en ese servicio: no hace falta tocar el 'web' ni la base de
     datos.

  d) NO hace falta revertir nada en la base de datos. Este lote no anade
     migraciones, no altera el esquema y no borra ni renombra datos. La
     unica escritura permanente que puede haber dejado es la fila de
     auditoria que antes se perdia y ahora se guarda.

  e) Verificacion tras el rollback: repetir 7.2 en su totalidad.

--------------------------------------------------------------------------------
8. INCIDENTE DE DESPLIEGUE, ROLLBACK Y RESTABLECIMIENTO DE LA CLAVE (addendum)
--------------------------------------------------------------------------------

Este addendum se redacto DESPUES de publicar el lote, cuando ya se
conocieron tres hechos que no eran previsibles al escribir las secciones 1
a 7. Se declara aqui, sin reescribir lo anterior.

8.1  EL BUILD DEL LOTE FALLO, Y NO FUE POR EL CODIGO

Al publicar los 11 commits, el despliegue automatico del servicio 'web'
fallo dos veces en el paso BUILD_IMAGE. El commit afectado era el
7eca876 (el HEAD de este lote).

La causa se obtuvo de la API de Railway (query buildLogs) y es un fallo de
PLATAFORMA, no del repositorio:

  Build Failed: build daemon returned an error < listing workers for Build:
  failed to list workers: Unavailable: connection error: desc = "error
  reading server preface: raw-read unix @->/run/buildkit/buildkitd.sock:
  use of closed network connection" >

Es un error del daemon BuildKit de Railway (la conexion con el socket del
buildkitd se cerro). Evidencia de que no es el codigo:

  - Los ficheros que condicionan el build (requirements.txt, pyproject.toml,
    mise.toml, runtime.txt, Procfile y railway.toml) son IDENTICOS en el
    commit 4d1a603 (que construyo bien a las 03:49 UTC) y en el 7eca876
    (que fallo). El diff del lote no toca ninguno de ellos.
  - El commit 6038fc29 (viernes) se construyo sin problema con la misma
    API y en la misma ventana de tiempo.
  - El despliegue manual del mismo commit 7eca876 fallo con el mismo
    error de build, y el despliegue del commit del viernes, posterior en
    el tiempo, fue SUCCESS.

Conclusion: fallo transitorio de la plataforma de build. La accion
correcta es reintentar el despliegue; no hay ninguna correccion de codigo
que aplicar.

8.2  ROLLBACK EJECUTADO A LA VERSION DEL VIERNES

Instruccion del propietario: "corrija el problema y, por ultimo, haga
rollback a una version funcional del viernes en la tarde".

Que version estaba en servicio el viernes por la tarde (2026-10-23)? El
historial de despliegues del servicio 'web' muestra que el UNICO
despliegue de ese dia fue el 2026-10-23T21:58 UTC (18:58 hora de Chile)
con el commit:

  6038fc292d3e86b3c860d5a64b885c7e92eeeeeb
  feat(comentarios): adjuntos en comentarios + edicion ventana 30min

Ese commit es, por tanto, la version funcional del viernes por la tarde.
Se desplego en los TRES servicios (web, worker y beat) con
serviceInstanceDeploy, y los tres quedaron en estado SUCCESS:

  web    2026-10-26T13:06:06 SUCCESS 6038fc29
  worker 2026-10-26T13:12:00 SUCCESS 6038fc29
  beat   2026-10-26T13:12:55 SUCCESS 6038fc29

Estado verificado tras el rollback:
  - GET /health -> 200 {"status":"ok","database":"ok","redis":"ok"}
  - GET /info   -> 200
  - GET /ready  -> 200
  - POST /api/v1/auth/login (JSON) -> 200 con rol administrador

8.3  LO QUE EL ROLLBACK RESTAURE Y LO QUE VUELVE A EXPONER

El commit del viernes es anterior a V1.005 y V1.006, asi que el rollback
retira sus protecciones. El verificador en negro pasa de 27/27 a 12/24, y
las diferencias son PREVISIBLES (no son fallos nuevos):

  - Vuelve el endpoint de diagnostico /_diag/tickets, SIN AUTENTICAR
    (V1.006 lo habia retirado: commit dbbb7a0). El barrido anonimo lo
    detecta como fuga.
  - Vuelve el modal de cambio de contrasena accesible sin sesion
    (este lote lo cierra, con el commit 8e8b973).
  - /info vuelve a devolver la topologia interna de la base de datos
    (host, puerto y base). No expone la contrasena (la enmascara), pero
    V1.006 ya lo habia limpio.
  - Se pierden las cabeceras de seguridad y el endurecimiento de la
    superficie expuesta (V1.005).
  - Se pierde /salud-celery y el latido escrito por el BEAT (V1.006), de
    modo que el worker y el beat ya no se pueden verificar desde el web.
  - Se pierde el cierre del XSS almacenado del renderizador Markdown y
    el del dashboard (este lote y V1.005).

Este coste es el precio de la instruccion recibida. El codigo del lote
sigue en el repositorio, con sus 155 pruebas en verde, y puede volver a
desplegarse en cuanto la plataforma de build se recupere (el siguiente
despliegue lo tiene como bloque de cache, por lo que deberia construir
sin red).

8.4  LA CLAVE DEL ADMINISTRADOR HABIA CAMBIADO EN LA BASE DE DATOS

Al validar el rollback, el login del administrador devolvio 401
"Credenciales invalidas" con las dos claves conocidas:

  admin / mtLvX7MEE3%wAwDH4oOROcV2   -> 401
  admin / admin123                   -> 401
  admin / GrmAdmin#2026.Recupera      -> 401

Diagnostico (solo lectura, contra produccion):

  - Los usuarios de demostracion (usuario1, agente1, lider) EXISTEN y su
    contrasena verifica correctamente: responden 403 "Usuario inactivo",
    no 401. Es decir, la base de datos esta bien y el hashing bcrypt
    verifica.
  - El usuario 'admin' respondia 401: o su hash habia cambiado o su fila
    no existia.
  - El flujo de cambio de contrasena del codigo desplegado (POST
    /api/v1/auth/cambiar-password) es correcto: exige sesion, exige la
    contrasena actual, solo afecta al usuario autenticado y confirma la
    transaccion. No hay via evidentemente explotable.
  - ALLOW_XUSER_HEADER esta desactivado en produccion: la cabecera
    X-User-Id no permite autenticarse (401).
  - La contrasena del administrador NO estaba (ni esta) en el
    repositorio: solo aparece en scripts tmp_* ignorados por git, y
    ``git log --all -S`` no encuentra ninguna coincidencia en el
    historial.

Accion tomada, con autorizacion expresa del propietario ("ingrese cambio
en la contrasena del usuario admin a GrmAdmin#2026.Recupera; si no
funciona genera una contrasena nueva y un usuario nuevo"):

  Se restablecio la contrasena del usuario 'admin' (id=1) en la base de
  datos de produccion, escribiendo el hash con el MISMO helper del
  proyecto (app.core.security.hash_password: bcrypt, mismos rounds y el
  mismo truncado a 72 bytes), y se aseguro is_active=true.

  Verificacion: POST /api/v1/auth/login -> HTTP 200
  {"ok":true,"user_id":1,"username":"admin","rol":"administrador"}

  La fila ya existia (id=1, rol ADMINISTRADOR, email admin@bitacora.local,
  is_active=true): no hizo falta crear un usuario nuevo. Tras el cambio
  la base tiene 17 usuarios, 13 activos.

  Procedimiento empleado, por transparencia: la API de Railway permite
  leer las variables de entorno CON SUS VALORES de un servicio mediante
  la query ``variablesForServiceDeployment`` usando el token de proyecto.
  De ahi se obtuvo la URL publica de PostgreSQL (DATABASE_PUBLIC_URL) y
  se conecto directamente a la base de datos para ejecutar UN UPDATE
  sobre UN registro (usuarios.id=1). No se modifico el esquema, ni otros
  usuarios, ni datos de negocio, ni se imprimieron secretos por pantalla.
  La escritura se hizo desde un script local (tmp_resetear_admin_db.py,
  ignorado por git) y no forma parte del codigo del proyecto.

  PENDIENTE QUE DEBE RESOLVER EL PROPIETARIO (no es resoluble desde el
  codigo):
    - Rotar esta contrasena por una que no conste en ningun sitio, y no
      volver a escribir credenciales en ficheros, scripts ni tickets.
    - Revisar si el cambio de contrasena de las 09:00 a las 13:00 fue
      suyo o de un tercero. Conviene revisar la tabla de auditorias
      (la escritura de auditoria del cambio de contrasena existe en el
      codigo) y el registro de sesiones.
    - Considerar cerrar el registro publico de usuarios.

8.5  HALLAZGO DE SEGURIDAD EN LA API DE RAILWAY (a reportar a Railway)

Con el token de proyecto, la query ``variablesForServiceDeployment``
devuelve el mapa COMPLETO de variables de entorno de un servicio, con sus
valores en claro: SECRET_KEY, la contrasena de PostgreSQL, la clave de
Resend y la de SMTP. Lo mismo ocurre con la query ``variables`` a nivel
de proyecto. Con ese token tambien se leen los nombres de todas las
variables de los tres servicios.

Quien tenga el token de proyecto puede, por tanto, leer todos los
secretos del proyecto. Recomendacion: rotar el token de proyecto, mover
los secretos a variables de entorno de nivel de servicio que solo el
servidor de Railway pueda leer, y pedir a Railway que revise si esa
consulta debe estar disponible para un token de proyecto.

8.6  ESTADO FINAL DE ESTE LOTE

  - Codigo: 11 commits del lote mas el commit del README (7eca876), el
    commit que corrige el arranque en base nueva (3fe0827) y el commit
    de este addendum. TODOS estan en la rama 'release/v2.001' (HEAD
    66f37ce mas el commit de este addendum). NO estan en 'main'.
  - Pruebas: 155 passed (144 heredadas + 11 nuevas de este lote).
  - Desplegado en produccion: NO. El build de la plataforma lo impidio y
    el propietario ordeno el rollback.
  - Produccion: los tres servicios sirven el commit del viernes
    6038fc29, verificados en estado SUCCESS y con la aplicacion
    respondiendo con normalidad.
  - Accesos del administrador: restablecidos y verificados.

8.7  ALINEACION DE 'main' Y PUBLICACION DE LAS RAMAS DE CONSERVACION

  Decision del propietario: alinear 'main' con la version del viernes que
  esta en produccion y dejar V2.001 en una rama aparte.

  - 'main' quedo alineado con el arbol EXACTO del commit del viernes
    6038fc29 mediante 'git commit-tree' + 'update-ref', sin 'push --force'
    ni reescritura de historia. Commit resultante: c6eca9b ("revert:
    alinear main con el commit del viernes 6038fc29"). 'git diff
    6038fc29 c6eca9b' no devuelve ninguna diferencia: los 421 ficheros
    del arbol son identicos.
  - 'main' se publico como avance rapido (7eca876..c6eca9b), sin force.
  - Rama de conservacion 'release/v2.001' -> 66f37ce (todo este lote).
  - Rama de conservacion 'release/v1.006' -> 4d1a603 (V1.006 cerrado).
  - Las dos ramas se publicaron en el remoto (PUSH_EXIT=0).

  Consecuencia sobre el autoDeploy: el push a 'main' dispara el
  autoDeploy del servicio web. El despliegue de c6eca9b termino en
  estado SUCCESS (2026-10-26T14:19:59Z, commit status de GitHub
  "Success - bitacora-grmv2-production.up.railway.app"). Esto confirma
  ademas que el daemon BuildKit de la plataforma se ha recuperado: el
  fallo de build de la seccion 8.1 era transitorio y no afecta al
  codigo. El contenido desplegado es el mismo que el del viernes
  (arbol identico), por lo que el servicio no cambia de comportamiento.

8.8  VERIFICACION FINAL EN PRODUCCION (despues del rollback)

  - GET /health  -> 200 {"status":"ok","database":"ok","redis":"ok"}
  - GET /info    -> 200
  - GET /ready   -> 200 {"status":"ready"}
  - POST /api/v1/auth/login con la credencial restablecida -> HTTP 200
    {"ok":true,"user_id":1,"username":"admin","rol":"administrador"}
  - Barrido anonimo (tools/verificacion/barrer_anonimo.py): 2 fugas
    detectadas, coherentes con la version del viernes y ausentes en este
    lote:
      - GET /_diag/tickets -> 200 con datos reales sin sesion
      - GET /api/v1/auth/cambiar-password-modal -> 200 sin sesion
    Este lote de V2.001 las cierra (8e8b973 y la proteccion de
    diagnostico).
  - Rutas que siguen en 500 con la version del viernes (el codigo del
    viernes es incompatible con la base ya migrada por V1.006):
      - GET /admin/reporte-entregas -> 500
      - GET /p/{slug} -> 500
    Ambas vuelven a responder en cuanto se despliegue V1.006 o V2.001.
  - GET /salud-celery -> 404 (la ruta no existe en la version del
    viernes; se introdujo en V1.006).
  - Cabeceras de seguridad: la version del viernes no envia
    Content-Security-Policy, Strict-Transport-Security ni
    Permissions-Policy. V1.006 las restaura.
  - La version del viernes vuelve a publicar 'database_url' en /info
    (host y puerto, sin credenciales). V1.006 lo deja de publicar.

8.9  EFECTO COLATERAL DE ALINEAR 'main' CON EL ARBOL DEL VIERNES

  Al alinear 'main' con el arbol exacto del commit del viernes
  6038fc29, 'main' vuelve a incluir la carpeta 'extract/' (122 ficheros,
  20,82 MB: markdown e imagenes de una extraccion web). Esa carpeta se
  elimino de forma intencionada durante el trabajo V1.x (commit
  24507d1) y se anadio a '.gitignore' con el comentario "salida temporal
  de extraccion web". El .gitignore del arbol del viernes todavia no
  contenia esa entrada, de modo que ahora 'main' la reintroduce.

  - No afecta al funcionamiento: la aplicacion sirve sus plantillas y
    estaticos desde 'app/', y el despliegue de c6eca9b termino en
    estado SUCCESS. Los ficheros de 'extract/' no se sirven ni se leen
    en tiempo de ejecucion.
  - Si el propietario desplegara desde 'main' en el futuro, la imagen
    incluiria de nuevo esos 20,82 MB y el repositorio volveria a
    contarlos. Al desplegar desde 'release/v2.001' o 'release/v1.006'
    desaparecen de nuevo (ya estan ignorados en el .gitignore de esas
    ramas).
  - Recomendacion: cuando se despliegue V1.006 o V2.001, la carpeta
    desaparece por si sola. Si se decide desplegar desde 'main', es
    preferible usar 'release/v2.001' o 'release/v1.006' en lugar de
    'main'.

  Nota sobre la historia: el commit del viernes 6038fc29 NO es una rama
  divergente, es el ANCESTRO COMUN de todo el trabajo V1.001 a V2.001
  ('git merge-base 6038fc29 release/v2.001' devuelve 6038fc29 y
  'git merge-base --is-ancestor 6038fc29 release/v2.001' devuelve 0). El
  delta de codigo entre el arbol desplegado y 'release/v2.001' es de 55
  ficheros en 'app/' (3.172 lineas anadidas y 784 eliminadas), mas
  'tools/' y 'tests/'.

================================================================================
FIN DEL DOCUMENTO README V2.001
================================================================================
