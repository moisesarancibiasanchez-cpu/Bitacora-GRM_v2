================================================================================
README V1.006 - SALUD DE CELERY, MIGRACIONES FAIL-CLOSED Y REPARACION DE
               DEFECTOS EN BITACORA GRM v2
Fecha: 2026-10-25
================================================================================

Documentos anteriores de la serie (NO se modificaron; la errata 6.3 corrige
por referencia el README V1.005):
  README_V1.001_INDICADOR_RESULTADO_PRUEBAS_Y_REPARACION_GENERAL_2026-10-24.txt
  README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_2026-10-24.txt
  README_V1.003_ROLES_WORKER_BEAT_CELERY_RAILWAY_2026-10-24.txt
  README_V1.004_WORKER_BEAT_EN_RAILWAY_2026-10-24.txt
  README_V1.005_AUDITORIA_MULTIAGENTE_Y_REPARACION_DE_DEFECTOS_2026-10-24.txt

Motivo de este incremento: el encargo fue revisar el estado general del
proyecto con varios sub-agentes en paralelo, corregir los problemas
generados FUERA de la gestion del cambio anterior, devolver el proyecto a
operativo, validarlo de forma exhaustiva y cerrar con release notes
atomicos. La revision encontro cinco capas con defectos reales: arranque
que servia con un esquema desalineado, migraciones que en una base nueva
no creaban el estado terminal, campos del esquema que el backend
ignoraba, transacciones que se perdian en silencio y un XSS almacenado en
el renderizador de Markdown. A eso se sumo que no existia ninguna forma
de COMPROBAR que el worker y el beat de Celery estuvieran vivos sin el
token de proyecto de Railway, que esta revocado. Todo ello quedo
corregido, validado contra produccion y publicado.

--------------------------------------------------------------------------------
1. BASE
--------------------------------------------------------------------------------

Repositorio:         https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
Rama:                main
Commit base:         90a2879  docs(release): README V1.005 con la auditoria
                              multiagente y la reparacion de defectos
Commits del lote:    26cf486  fix(migraciones): poblar el metadata, fail-closed
                              real y crear el estado Produccion OK
                      66a1302  feat(salud): latido de Celery y endpoint
                              /salud-celery de solo lectura
                      58e9a96  fix(tickets): respetar estado_id con guard de rol y
                              coherencia de SLA y cierre
                      3cb4476  fix(notificaciones): SAVEPOINT para no descartar la
                              transaccion del llamador
                      6e5ced1  fix(seguridad): cerrar el XSS almacenado del
                              renderizador Markdown
                      76781eb  chore(despliegue): .env.example, railway.toml,
                              mise.toml y pins de dependencias
                      1a13850  test(regresion): suite V1.005/V1.006, limpieza
                              determinista y auditoria documental
                      3b1ffab  docs(verificacion): recuentos reales de los
                              verificadores y ruta corregida
                      0583d26  fix(salud): interpretar la lista que devuelve
                              Celery control.ping()
                      04c2f2a  feat(salud): catalogo de tareas del worker en
                              /salud-celery
                      7be00c0  fix(salud): diagnosticar donde esta la rotura
                              del latido
                      2e457d8  docs(credenciales): quitar la credencial por
                              defecto de la pantalla de login
                      (este commit) docs(release): README V1.006 con el addendum
                              de la verificacion en produccion
Tipo de publicacion: fast-forward (sin --force)
Push:                90a2879..686b459  main -> main
                      (686b459 es el commit de este documento; el commit de
                      actualizacion del addendum va inmediatamente despues y
                      no cambia ningun fichero de codigo)
Fecha:               2026-10-25

Aplicacion:          https://bitacora-grmv2-production.up.railway.app
Proyecto Railway:    BitacoraGRMv2  (id c0e1796f-cdcf-4e85-833d-25536dfa674c)
Entorno:             production    (id 13092a8d-36b3-420e-95d9-a1f5379ddb19)
Servicios:           Postgres 22b35ec6, Redis 3e1ff30b, web 775efae4,
                      worker 51e22b0c, beat 1c16b13c  (ninguno recreado)

Metodo de trabajo
-----------------
Se ejecutaron en paralelo cuatro sub-agentes con propiedad EXCLUYENTE de
ficheros, y en paralelo una revision propia del nucleo sensible. Los
sub-agentes son fuente de HALLAZGOS, no de confianza: cada uno de sus
cambios se reviso antes de commitear.

  Sub-agente 1  Plantillas, JavaScript y XSS        -> app/static/js,
                                                      app/templates (revisado)
  Sub-agente 2  Logica de negocio                   -> app/services,
                                                      app/tasks (revisado)
  Sub-agente 3  Configuracion y despliegue         -> railway.toml, start.sh,
                                                      .env.example, mise.toml,
                                                      pyproject.toml,
                                                      requirements.txt (revisado)
  Sub-agente 4  Verificadores, tests y documentacion-> tests/,
                                                      tools/verificacion (revisado)
  Revision propia (no delegada)                    -> app/db/migrations.py,
                                                      app/main.py,
                                                      app/core/celery_app.py,
                                                      app/services/ticket_service.py,
                                                      app/services/notificacion_responsable_service.py,
                                                      app/static/js/htmx-events.js,
                                                      README.md, docs/

Defectos introducidos por los sub-agentes que se detectaron y corrigieron
ANTES de commitear (ninguno llego a produccion):
  1. `railway.toml` repetia la clave `PYTHONDONTWRITEBYTECODE`: el TOML
     era invalido y Railway no podia leerlo.
  2. `start.sh` hacia fail-closed con la condicion `|| deriva`, pero
     `report_schema_drift()` devuelve una linea "OK (N columnas)" por
     tabla: el arranque habria abortado SIEMPRE y los tres servicios no
     habrian levantado nunca.
  3. `apply_migrations()` se ejecutaba con `Base.metadata` vacio: 25
     errores "no such table" y una base sana rechazada.

Estado de partida (verificado, no supuesto)
-------------------------------------------
  - `python -m app.db.migrations` ejecutado FUERA de la aplicacion web
    (start.sh, scripts, subprocesos) trabalhaba con un `Base.metadata`
    VACIO: las 25 migraciones `ALTER TABLE` fallaban con "no such table".
  - `python -m app.db.migrations` terminaba SIEMPRE con codigo 0, aunque
    `apply_migrations()` registrara errores. El "fail-closed" que se
    anunciaba en `start.sh` no existia: era un `if !` sobre un comando
    que nunca podia fallar.
  - La migracion 4.6 NO creaba el estado terminal 'Produccion OK' en una
    base nueva: el INSERT crudo omitia `es_entrega`, que es NOT NULL con
    default de SQLAlchemy (lado Python), no un default del servidor.
    En PostgreSQL el error es identico.
  - `TicketCreate.estado_id` estaba declarado en el esquema y el servicio
    lo IGNORABA siempre: el campo era una promesa que el backend no
    cumplia.
  - Reordenar una tarjeta dentro de su columna reiniciaba su vencimiento
    de SLA: el reloj del SLA volvia a cero con cada arrastre.
  - `notificar_responsable_columna()` hacia `db.rollback()` a secas si
    fallaba la notificacion: se descartaba TODA la transaccion pendiente
    de quien llamaba. El cambio de estado, el historial y la auditoria se
    perdian en silencio mientras la API respondia 200.
  - `renderMarkdown()` (app/static/js/htmx-events.js) no escapaba las
    comillas ni validaba el esquema del `href`: un enlace malicioso
    rompia el atributo y colaba un manejador de evento en el DOM. Es XSS
    ALMACENADO (la descripcion la escribe un usuario y la renderiza
    cualquier otro).
  - `datetime.utcnow()` seguia usandose en el servicio de tickets:
    DeprecationWarning en Python 3.12 y, en el camino de las fechas con
    zona horaria, conversion a la HORA LOCAL del servidor en vez de a UTC.
  - No existia ninguna forma de comprobar el worker y el beat de Celery
    sin el token de proyecto de Railway (revocado): "el worker esta
    arriba" era una suposicion, no una comprobacion.
  - `tools/verificacion/README.md` declaraba recuentos que NO coincidian
    con lo que los scripts comprueban (15/12/7/22/17 frente a
    13/13/6/24/16 medidos por ejecucion).
  - `README.md` y cuatro documentos anunciaban
    `PATCH /api/v1/tickets/{id}/estado`, ruta que no existe (la real es
    `{ticket_id}`).
  - `.env.example` no existia: ninguna variable de entorno del proyecto
    estaba documentada en un unico sitio.

--------------------------------------------------------------------------------
2. CAMBIO UNICO
--------------------------------------------------------------------------------

Que Bitacora GRM v2 pueda DEMOSTRAR su propio estado de salud operativo
(worker y beat comprobables desde la propia aplicacion, sin depender de
la API de Railway) y que el arranque deje de servir con un esquema
desalineado o de perder cambios en silencio.

2.1) Latido de salud de Celery (nuevo)
--------------------------------------
`app/tasks/salud_tasks.py` (fichero nuevo):
  - `CLAVE_LATIDO = "bitacora:salud:beat"`, `TTL_LATIDO = 300` segundos.
  - `registrar_latido()`: tarea Celery que escribe la hora actual en
    Redis. Si Redis no responde NO falla: registra el aviso y el beat
    sigue planificando (la ausencia del latido se detecta desde el
    endpoint, que es donde tiene que verse).
  - `leer_latido()`: lee el latido y devuelve `ok`, `latido`,
    `antiguedad_segundos` y `detalle`. Nunca lanza: un fallo de Redis se
    reporta como detalle.

La clave vive en la base 0 (`REDIS_URL`), separada de las colas del
broker (base 1) y del backend de resultados (base 2).

2.2) Planificacion del latido en el beat
-----------------------------------------
`app/core/celery_app.py`:
  - `include` += `"app.tasks.salud_tasks"`.
  - Nueva entrada de `beat_schedule`:
        "latido-salud": {
            "task": "app.tasks.salud_tasks.registrar_latido",
            "schedule": crontab(minute="*"),
        }

Precision importante: el BEAT planifica la tarea y el WORKER la ejecuta.
Por eso la ausencia de latido no distingue por si sola entre "el beat no
planifica" y "el worker no ejecuta"; la distincion se hace cruzando las
dos senales (si el ping responde pero no hay latido, el fallo es de
planificacion; si el ping no responde, el worker esta caido). La
documentacion de los tres ficheros reflecte esta precision.

2.3) Endpoint GET /salud-celery (nuevo, solo lectura)
-----------------------------------------------------
`app/main.py`, funcion `salud_celery(request)`:
  - Control de acceso: 401 sin sesion, 403 con un rol distinto de
    administrador. No es un endpoint publico.
  - `worker`: `celery_app.control.ping(timeout=2.0)`; devuelve si
    responde, la lista de workers que contestan, el detalle y los
    segundos que tardo la consulta.
  - `beat`: el ultimo latido leido de Redis, con su antiguedad.
  - `colas`: profundidad de la cola del broker (`llen` del cliente del
    canal o `_size` si el transporte no lo expone).
  - `tareas_programadas`: las entradas del `beat_schedule` con su tarea
    y su programacion.
  - `ok`: true solo si el worker responde Y el latido es valido.
  - Nunca lanza: cada bloque va envuelto y un fallo se reporta como
    detalle, no como 500.

El endpoint existe porque verificar el worker y el beat exigia la API de
Railway, cuyo token de proyecto esta revocado: sin esta senal, "el worker
esta arriba" era una suposicion.

2.4) Migraciones: metadata poblado y fail-closed real
------------------------------------------------------
`app/db/migrations.py`:
  - `_asegurar_modelos_importados()` (nueva): importa `app.models` para
    que `Base.metadata` conozca las tablas. Sin esto, `apply_migrations()`
    ejecutado fuera de la aplicacion web trabaja con un metadata VACIO.
    Es la forma canonica de poblarlo.
  - `apply_migrations()`: llama a `_asegurar_modelos_importados()` al
    principio y distingue `schema_errors` (fallos de `create_all` o de
    `ADD COLUMN`) de `errors` (total, incluidos los fallos de las
    migraciones de datos).
  - `verificar_esquema()` (nueva): aplica las migraciones y devuelve el
    codigo de salida del arranque.

Criterio de `verificar_esquema()` (fail-closed con EVIDENCIA POSITIVA):
  - Devuelve 1 si queda deriva de esquema (alguna columna de
    `COLUMNS_TO_ADD` sin anadir) o si hubo errores de ESQUEMA.
  - Devuelve 0 si lo unico que fallo son las migraciones de DATOS: el
    esquema queda alineado y la aplicacion sirve igual. Abortar el
    arranque por eso dejaria los tres servicios caidos sin evitar ningun
    500.
  - Devuelve 0 si la propia comprobacion lanza una excepcion inesperada:
    el guard no puede ser el que tumbe el servicio. Si la base no es
    alcanzable, la aplicacion ya falla por su cuenta y Railway la
    reinicia. Se deja constancia en el log con nivel ERROR.
  - No confunde las lineas "OK (N columnas)" de `report_schema_drift()`
    con deriva: son el caso NORMAL, no un fallo.

`start.sh`: el bloque de migraciones invoca `verificar_esquema()` y, si
devuelve 1, NO arranca el proceso (antes continuaba "para no dejar el
servicio sin respuesta"). Aplica a los tres roles: web, worker y beat.

2.5) La migracion 4.6 crea el estado 'Produccion OK' en una base nueva
-----------------------------------------------------------------------
`app/db/migrations.py`, bloque 4.6: el INSERT crudo del estado terminal
omitia la columna `es_entrega` (NOT NULL, con default de SQLAlchemy, no
del servidor). En una base recien creada la insercion fallaba con
"NOT NULL constraint failed: estados.es_entrega" y el estado NO se
creaba; en PostgreSQL el fallo es identico. Se anade `es_entrega` al
INSERT (en FALSE); la migracion 4.9 lo marca despues como estado de
entrega, que es donde vive esa responsabilidad.

Verificado: sobre una SQLite nueva, tras `apply_migrations()` la tabla
`estados` contiene 'Produccion OK' con `es_entrega = 1`, y hay 10 filas
en `etapas_proyecto`.

2.6) TicketCreate.estado_id se respeta, con guard de rol
----------------------------------------------------------
`app/services/ticket_service.py::crear_ticket()`:
  - Si el payload trae `estado_id` y el usuario es ADMINISTRADOR o
    AGENTE_SENIOR, se usa ese estado (si no existe, se rechaza con
    `TransicionInvalidaError`, codigo `ESTADO_NO_ENCONTRADO`).
  - En cualquier otro rol se usa el estado inicial, que es lo que evita
    que un solicitante se salte el flujo del ITSM creando tickets ya
    cerrados.
  - Si no hay ningun estado inicial configurado, se rechaza con
    `SIN_ESTADO_INICIAL`.
  - El titulo se valida: no puede quedar vacio (`ValueError`).
  - La descripcion pasa a ser opcional (`datos.get("descripcion") or ""`).

2.7) SLA coherente y fecha de cierre en estados finales
---------------------------------------------------------
`app/services/ticket_service.py`:
  - `cambiar_estado()`: el SLA se recalcula SOLO cuando el estado cambia
    de verdad (`not mismo_estado`). Antes se recalculaba en cada
    movimiento, y reordenar una tarjeta dentro de su columna reiniciaba
    el vencimiento.
  - `sla_horas is not None` en lugar de la comprobacion de verdad: un
    SLA de 0 horas es un SLA, no "sin SLA". Verificado contra
    produccion: los estados reales tienen 24, 48, 72 o None, ninguno 0,
    de modo que el cambio no altera ningun dato existente.
  - Todo estado final registra `fecha_completado` (antes solo
    'Produccion OK'), para que las metricas y los deadlines no sigan
    contando el ticket como trabajo en curso.
  - El SLA final se calcula con la fecha de cierre: 1 si se cerro antes
    del vencimiento, 0 si se cerro despues. Es coherente con
    `SLAService.recalcular_ticket()`, que deja 1 como 1 y todo lo demas
    como 0.
  - `now_utc()` (`app/core/timezone.py`) sustituye a
    `datetime.utcnow()`: misma semantica (UTC naive), sin
    DeprecationWarning en Python 3.12.
  - Las fechas con zona horaria se convierten a UTC con
    `astimezone(timezone.utc)` y no a la hora local del servidor: con
    `astimezone(tz=None)` un valor con zona se guardaba desplazado cuatro
    horas en America/Santiago.
  - `actualizar_campos()` acepta `commit=False` para que el endpoint
    registre la auditoria y confirme campos y auditoria juntos.

2.8) SAVEPOINT en la notificacion al responsable
--------------------------------------------------
`app/services/notificacion_responsable_service.py`:
`db.flush()` pasa a ejecutarse dentro de `with db.begin_nested():` y se
retira el `db.rollback()` a secas. Con SAVEPOINT, si la notificacion
falla se deshace SOLO la notificacion; la transaccion exterior del
llamante sigue vigente.

2.9) XSS almacenado del renderizador Markdown (cerrado)
--------------------------------------------------------
`app/static/js/htmx-events.js`:
  - Nueva funcion `_urlMarkdownSegura(url)`: elimina los caracteres de
    control ANTES de validar (el parser de URL del navegador elimina
    TAB, LF y CR del interior de la URL, de modo que
    "java<TAB>script:alert(1)" se ejecuta igual que
    "javascript:alert(1)") y aplica una lista BLANCA de esquemas
    enteros: http, https, mailto. Un esquema no permitido degrada el
    enlace a texto plano.
  - `renderMarkdown()` escapa tambien `"` y `'`, de modo que un enlace no
    puede romper el atributo `href` ni colar un manejador de evento.
  - Los enlaces llevan `rel="noopener noreferrer"`.

2.11) El latido lo escribe el BEAT, no solo el worker
---------------------------------------------------
Con el latido escrito por una tarea que ejecuta el worker, la ausencia
del latido no permitia distinguir "el beat no planifica" de "el worker no
ejecuta": las dos senales terminaban en la misma clave de Redis.

`app/core/salud_scheduler.py` (nuevo) define `SaludScheduler`, que
hereda de `celery.beat.PersistentScheduler` y escribe el latido en cada
`tick()`. Asi el latido depende SOLO del beat, que es justo lo que se
quiere comprobar, y el ping del worker sigue siendo la senal
independiente del worker.

`app/core/salud.py` (nuevo) es el SSOT del latido: la clave, el TTL y las
funciones de escritura y lectura. El scheduler, la tarea del worker y el
endpoint comparten ese modulo sin duplicar ni la clave ni el TTL.

El TTL pasa de 300 a 900 s: el `maxinterval` por defecto del beat es de
300 s, de modo que un TTL de 300 s expiraria justo en el borde entre dos
ticks y produciria falsos negativos.

`start.sh` arranca el beat con
`--scheduler=app.core.salud_scheduler:SaludScheduler`, con reserva: si el
modulo no estuviera disponible, se cae al scheduler estandar de Celery
(el beat sigue funcionando; solo se pierde el latido).

Si Redis no responde, el scheduler NO se tumba: registra el aviso y el
beat sigue planificando.

2.12) Verificacion con la version de Celery de produccion
---------------------------------------------------------
El entorno de desarrollo tiene celery 5.6.3, pero `requirements.txt` fija
`celery==5.4.0` y produccion corre 5.4.0 (los logs del despliegue lo
confirman). La validacion se repitio con celery 5.4.0 instalado en un
directorio aislado: el scheduler se instancia, `tick()` funciona, la tarea
`app.tasks.salud_tasks.registrar_latido` se registra y el beat sobrevive a
un fallo de Redis. El desfase de versiones del entorno de desarrollo queda
declarado como deuda (ver 6.5).

2.13) Configuracion, dependencias y documentacion
--------------------------------------------------
  - `.env.example` (nuevo): documenta los 38 campos de `Settings` (los
    38, verificado por comparacion automatica) y las variables que se
    leen directamente fuera de `Settings`, separadas por origen: shell
    (`SECRET_KEY_FILE`, `PROC_TYPE`, `APP_ROLE`), modulo
    (`RESEND_API_KEY`, `UPLOAD_DIR`, `ALLOW_XUSER_HEADER`, ...),
    pruebas (comentadas) y Railway (no definir a mano).
  - `railway.toml`: se elimina la clave TOMB duplicada
    `PYTHONDONTWRITEBYTECODE` (la repetida hacia el fichero TOML
    invalido), se declara `numReplicas = 1` y `AUTO_INIT_DB = "false"`.
  - `mise.toml`: se fija `python = "3.12.5"`, que es la version
    declarada en `runtime.txt` y en el intervalo de `pyproject.toml`.
  - `pyproject.toml` y `requirements.txt`: el comentario sobre `a2wsgi`
    se actualiza porque `app/main.py` ya no lo importa.
  - `tools/verificacion/README.md`: recuentos corregidos con los valores
    medidos por ejecucion real.
  - `README.md` y cuatro documentos: la ruta documentada
    `PATCH /api/v1/tickets/{id}/estado` se corrige a `{ticket_id}`.

--------------------------------------------------------------------------------
3. QUE NO SE MODIFICO
--------------------------------------------------------------------------------

  - La paleta de `resultado_pruebas`: no se toco ni un hex. El SSOT
    sigue siendo `app/core/resultado_pruebas.py` y no se duplico la
    paleta en ningun JavaScript ni plantilla.
  - El modelo de datos: no se anadio, elimino ni renombro ninguna
    columna. La unica alteracion de esquema es la de datos ya existente
    (4.9 marca estados como `es_entrega`), que se mantiene.
  - La tabla `estados` de produccion: no se borro ni se renombro nada.
    Se respeto la configuracion real, incluidos los TRES estados
    marcados como `es_inicial = True` ('BackLog', 'Analisis',
    'Bloqueado!'): la creacion de tickets toma el primero, que es el
    comportamiento anterior. Cambiarlo es una decision de datos, no de
    codigo.
  - El flujo ITSM, las transiciones entre estados y las reglas de
    permisos por rol.
  - La autenticacion: ni el algoritmo del JWT, ni la duracion (8 h), ni
    el modelo de cookie, ni el registro publico (sigue abierto, con
    usuarios reales: cerrarlo es una decision del propietario).
  - El Kanban: no se toco. Sigue sin paginacion (931 tickets) y se
    declara como deuda para un lote propio.
  - Los endpoints de la API: ni uno se elimino, renombro ni cambio de
    firma, salvo anadir `GET /salud-celery`. El numero de rutas GET
    pasa de 123 a 124 y el de paths de 197 a 198.
  - `/docs`, `/redoc` y `/openapi.json` siguen publicados:
    `EXPOSE_API_DOCS` continua en `true` por defecto (las herramientas
    derivan las rutas del OpenAPI). El panel puede ponerlo en `false`.
  - La CSP: se mantiene `'unsafe-inline'` porque hay scripts inline en
    40 plantillas. No se pretendia que la CSP bloqueara `onerror=`: por
    eso el XSS se cierra en el codigo, no en la cabecera.
  - La configuracion de Railway en el panel: no se toco ninguna variable
    del panel (el token de proyecto esta revocado y no hay permisos para
    cambiarlo).
  - La base de datos de produccion: no se ejecuto NINGUNA escritura ni
    lectura directa contra ella. La validacion se hizo contra una copia
    SQLite temporal y, en produccion, solo con peticiones GET.
  - Los README de V1.001 a V1.005: no se reescribieron. La errata de
    V1.005 se declara en 6.3.

--------------------------------------------------------------------------------
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
--------------------------------------------------------------------------------

SI REQUIERE CAMBIAR EL WORKER (y el beat).

Motivo: el worker tiene que cargar el modulo nuevo `app.tasks.salud_tasks`
y el planificador del beat tiene que incluir la entrada `latido-salud`.
Un worker con la imagen anterior no ejecutaria `registrar_latido` y el
latido no apareceria nunca en Redis (el endpoint informaria "sin
latido"), aunque el worker viejo siguiera funcionando.

Detalle por servicio:
  - web:     SI tiene que reiniciarse (arranca el proceso con el codigo
             nuevo y ejecuta el fail-closed de migraciones).
  - worker:  SI tiene que reiniciarse (nuevo modulo de tarea y nuevo
             planificador).
  - beat:    SI tiene que reiniciarse (nueva entrada en `beat_schedule`).

Requisitos de configuracion:
  - Ninguna variable de entorno NUEVA es obligatoria: Redis ya esta
    configurado (`REDIS_URL`) porque el broker de Celery lo usa.
  - Ninguna migracion de datos es obligatoria: el esquema de produccion
    ya esta alineado (verificado con GET sobre `/api/v1/estados`).
  - Ninguna recreacion de servicios ni de volumenes.
  - La variable `SECRET_KEY` real y el volumen montado en `/data` siguen
    siendo acciones pendientes del propietario (ver 6.6).

Rollback: ver 7.3 y 7.4.

--------------------------------------------------------------------------------
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

5.1) Suite local (no toca ninguna base de datos real)
------------------------------------------------------
Desde la raiz del repositorio:

    C:\Python311embed\python.exe -X utf8 -m pytest tests/ -q --tb=line

Resultado esperado: 132 passed (91 de V1.005 + 6 de test_v1005_regressions
+ 35 de test_v1006_regressions). Tiempos observados: 11 min 08 s.

5.2) Arrancable y esquema (local)
---------------------------------
    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_arranque.py
    -> 16 PASA, 0 FALLA (necesita BITACORA_ADMIN_USER y
       BITACORA_ADMIN_PASSWORD en el entorno).

    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_migrations.py
    -> 13 PASA, 0 FALLA.

    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_flujo_produccion_ok.py
    -> 6 PASA, 0 FALLA.

    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_dist.py
    -> 13 PASA, 0 FALLA.

    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_config.py
    -> 11 PASA, 0 FALLA.

    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_cors.py
    -> 9 PASA, 0 FALLA.

    & 'C:\Program Files\Git\bin\bash.exe' tools/verificacion/verificar_secret_key.sh
    -> 24 PASA, 0 FALLA.

    & 'C:\Program Files\Git\bin\bash.exe' -n start.sh
    -> sin salida (sintaxis valida).

5.3) Auditoria documental (local, sin red)
-------------------------------------------
    C:\Python311embed\python.exe -X utf8 tests\check_repo_documentation.py --counts

Resultado esperado: 198 paths OpenAPI (163 API + 35 main), 124 rutas GET,
31 plantillas, 74 URL de plantilla (74 con coincidencia), 3 URL de JS (3
con coincidencia), 0 enlaces Markdown internos rotos y 0 rutas rotas en
la tabla de endpoints del README.

5.4) Produccion: verificacion en negro (solo GET)
---------------------------------------------------
    $env:BITACORA_ADMIN_USER = "<usuario-admin>"
    $env:BITACORA_ADMIN_PASSWORD = "<contrasena-admin>"
    C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_produccion_negro.py

Resultado esperado tras el despliegue: 26 comprobaciones, 0 FALLOS.
Sin credenciales: 24 comprobaciones (la seccion 8 se informa como
SALTADO).

5.5) Produccion: barrido autenticado (solo GET)
-----------------------------------------------
    C:\Python311embed\python.exe -X utf8 tools\verificacion\barrer_rutas.py

Resultado esperado: 31 paginas HTML y 124 endpoints GET del OpenAPI
real, **0 respuestas 5xx**, la paleta servida desde el servidor, el JS
sin redeclararla y `/_diag/tickets` ausente.

5.6) Prueba manual del endpoint nuevo
--------------------------------------
Con sesion de administrador:

    GET /salud-celery   -> 200 con el JSON de worker, beat, colas y
                            tareas programadas.

Sin sesion -> 401. Con un rol que no sea administrador -> 403.

Lectura esperada del campo `beat`:
  - `ok = true`  : el beat planifica y el worker ejecuta la tarea.
  - `ok = false` : o no hay latido (la cadena beat -> worker no completo
                   la tarea) o Redis no responde. El campo `detalle`
                   dice cual de las dos cosas es.

5.7) Prueba manual del flujo de tickets
----------------------------------------
  1) Crear un ticket desde la UI con el rol ADMINISTRADOR: el estado
     inicial debe respetarse.
  2) Repetir la operacion con el rol SOLICITANTE: el ticket debe
     quedar en el estado inicial aunque la peticion intente fijar otro.
  3) Mover una tarjeta dentro de su columna: el vencimiento de SLA NO
     debe cambiar.
  4) Mover una tarjeta a un estado final: la fecha de cierre debe
     quedar registrada.

--------------------------------------------------------------------------------
6. TRAZABILIDAD
--------------------------------------------------------------------------------

6.1) Commit por commit
----------------------
26cf486  fix(migraciones): poblar el metadata, fail-closed real y crear el
         estado Produccion OK
         app/db/migrations.py, start.sh

66a1302  feat(salud): latido de Celery y endpoint /salud-celery de solo
         lectura
         app/tasks/salud_tasks.py (nuevo), app/core/celery_app.py,
         app/main.py

58e9a96  fix(tickets): respetar estado_id con guard de rol y coherencia de
         SLA y cierre
         app/services/ticket_service.py

3cb4476  fix(notificaciones): SAVEPOINT para no descartar la transaccion
         del llamador
         app/services/notificacion_responsable_service.py

6e5ced1  fix(seguridad): cerrar el XSS almacenado del renderizador Markdown
         app/static/js/htmx-events.js

76781eb  chore(despliegue): .env.example, railway.toml, mise.toml y pins de
         dependencias
         .env.example (nuevo), .gitignore, railway.toml, mise.toml,
         pyproject.toml, requirements.txt

1a13850  test(regresion): suite V1.005/V1.006, limpieza determinista y
         auditoria documental
         tests/conftest.py, tests/test_v1005_regressions.py (nuevo),
         tests/test_v1006_regressions.py (nuevo),
         tests/check_repo_documentation.py (nuevo),
         tests/test_reporte_entregas.py

3b1ffab  docs(verificacion): recuentos reales de los verificadores y ruta
         corregida
         tools/verificacion/README.md,
         tools/verificacion/verificar_produccion_negro.py, README.md,
         docs/REPORTE_VALIDACION_FINAL.md, docs/TRELLO_FEATURES_ANALYSIS.md,
         docs/VALIDATION_REPORT.md, docs/demo-interactiva/README.md

0583d26  fix(salud): interpretar la lista que devuelve Celery control.ping()
         app/main.py, tests/test_v1006_regressions.py

04c2f2a  feat(salud): catalogo de tareas del worker en /salud-celery
         app/main.py

7be00c0  fix(salud): diagnosticar donde esta la rotura del latido
         app/main.py, tools/verificacion/verificar_produccion_negro.py,
         tools/verificacion/README.md, tests/test_v1006_regressions.py

2e457d8  docs(credenciales): quitar la credencial por defecto de la pantalla
         de login
         itsm_kanban_mvp/app/templates/auth/login.html,
         itsm_kanban_mvp/README.md,
         itsm_kanban_mvp/docs/DESCRIPCION_TECNICA_COMPLETA.md

Parche completo del lote:
    git diff 90a2879..2e457d8

6.2) Ficheros intervenidos por el funcional
---------------------------------------------
  app/db/migrations.py                    113 lineas modificadas
  app/main.py                              98 lineas anadidas
  app/services/ticket_service.py          210 lineas modificadas
  app/static/js/htmx-events.js            43 lineas modificadas
  app/services/notificacion_responsable_service.py  11 lineas
  app/core/celery_app.py                  12 lineas anadidas
  app/tasks/salud_tasks.py                fichero nuevo
  start.sh                                16 lineas
  railway.toml                             6 lineas
  .env.example                            54 lineas (nuevo)
  mise.toml / pyproject.toml / requirements.txt / .gitignore
  tests/                                  conftest.py + 3 ficheros nuevos
  tools/verificacion/                     README.md + verificador en negro
  README.md + 4 documentos de docs/

6.3) ERRATA del README V1.005 (por referencia; no se modifica V1.005)
----------------------------------------------------------------------
En el README V1.005, linea 985, la variable de entorno de la duracion
del JWT aparece como `JWT_EXPIRE_MINUTES`. La variable real es
`JWT_EXPIRATION_MINUTES` (definida en `app/core/config.py:148`, con
valor por defecto `60 * 8` = 8 h, y leida en `app/core/security.py:52`).
No existe ninguna variable `JWT_EXPIRE_MINUTES` en el codigo: quien
configure esa variable creera que fija la duracion y no sera cierto.

6.3.1) ERRATAS de credenciales en documentos anteriores
---------------------------------------------------------
Por el mismo motivo (no se reescriben los documentos anteriores), se
declaran aqui dos referencias que quedaron desactualizadas cuando la
credencial de `admin` se roto O el 2026-10-24:

  - `README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_2026-10-24.txt`,
    linea 393: el procedimiento de verificacio On manual en PRODUCCION dice
    "Entrar con admin / admin123". Esa combinacion esta ROTADA y
    responde 401: el login de produccion exige la credencial vigente,
    que se entrega al propietario por canal privado y NO se escribe en
    ningun fichero del repositorio.
  - `REPORTE_SEGURIDAD.md`, linea 27: la tabla registra
    "POST /api/v1/auth/login (admin/admin123) -> 200 + cookie JWT". Ese
    resultado corresponde a la base de DESARROLLO sembrada con
    `SEED_DEMO_USERS=true`, no al despliegue de produccion, donde la
    misma combinacion responde 401.

En este lote se corrigen, en el ambito del subproyecto legacy
`itsm_kanban_mvp` (que NO usa la aplicacion principal), las tres
referencias que podian inducir a error: la pantalla de login ya no
muestra "Credenciales iniciales: admin / admin123" sino el nombre de la
variable de entorno que las define, y su README y su documentacion
tecnica lo aclaran como valor SOLO de desarrollo.

6.4) Evidencia de la validacion
--------------------------------
  Suite pytest completa:            132 passed, 0 failed (11 min 08 s)
  test_v1006_regressions.py:         35 passed
  test_v1005_regressions.py:          6 passed
  verificar_arranque.py:             16 PASA / 0 FALLA
  verificar_migrations.py:            13 PASA / 0 FALLA
  verificar_dist.py:                 13 PASA / 0 FALLA
  verificar_config.py:               11 PASA / 0 FALLA
  verificar_cors.py:                  9 PASA / 0 FALLA
  verificar_secret_key.sh:           24 PASA / 0 FALLA
  verificar_flujo_produccion_ok.py:   6 PASA / 0 FALLA
  verificar_sqlite_lower.py:          demostrativo (no falla nunca)
  bash -n start.sh:                   sintaxis valida
  Fail-closed sobre base nueva:      exit 0 y 'Produccion OK' creado
  Auditoria documental:               198 paths, 124 GET, 0 rutas rotas
  Verificador en negro (pre-deploy):  24 comprobaciones, 3 FALLOS: los
                                      tres son exactamente las funciones
                                      nuevas, todavia no desplegadas
                                      (124 rutas GET, 401 y 200 de
                                      /salud-celery)
  GitHub:                             197 paths y 123 GET antes del
                                      despliegue; 198 y 124 despues
  Barrido autenticado (post-deploy):  todas las comprobaciones superadas,
                                      0 respuestas 5xx (111 respuestas 200
                                      en la API, 0 errores)
  Verificador en negro (post-deploy):  27 comprobaciones, 0 FALLOS (el worker
                                      ya conoce la tarea del latido y el
                                      beat escribe el latido cada minuto)

6.5) Hallazgos declarados que NO se corrigieron
-------------------------------------------------
  1. Sin rate-limit ni bloqueo de cuenta en el login publico.
  2. El JWT no se invalida en el servidor: `logout()` borra la cookie,
     pero el token sigue siendo valido 8 h. No hay `jti` ni lista de
     revocacion.
  3. `EXPOSE_API_DOCS` sigue en `true` por defecto: `/docs`, `/redoc` y
     `/openapi.json` son publicos.
  4. La CSP incluye `'unsafe-inline'` (scripts inline en 40 plantillas).
  5. El Kanban no tiene paginacion (931 tickets).
  6. El badge `data-resultado-pruebas` no tiene paridad en
     `vistas/{tabla,timeline,panel}.html`.
  7. `tests/test_reporte_entregas.py` y `tests/test_trello_features.py`
     conservan `admin123` como credencial de la base temporal de
     pruebas (NO son credenciales de produccion: `admin/admin123`
     responde 401 en el despliegue).
  8. `test_reporte_entregas.py` sigue usando una ruta fija de base de
     datos (`./test_reporte_entregas.db`): dos ejecuciones concurrentes
     se pisan. Se arreglara junto con la paginacion del Kanban.
  9. En una base NUEVA sin sembrar, las migraciones crean el estado
     'Produccion OK' pero NO sus 3 transiciones, porque 'Cerrado' y 'En
     curso' no existen todavia: hay que ejecutar
     `python -m app.db.init_db` (o `AUTO_INIT_DB=true`). En produccion
     no aplica: el flujo y sus transiciones ya existen.
 10. `start.sh` sigue generando la `SECRET_KEY` si no se monta un
     volumen en `/data` (ver 6.6).
 11. Railway deja de leer `railway.toml` a partir del 2026-12-01: la
     configuracion del panel debe migrarse antes de esa fecha.

6.6) Acciones pendientes del PROPIETARIO (no ejecutables desde aqui)
---------------------------------------------------------------------
  1. Revocar el token de proyecto de Railway en Project Settings ->
     Tokens. El token `9b5069e8-7035-47b1-9ba0-cc809c17cf66` responde
     "Not Authorized" y ya no permite consultar los despliegues.
  2. Rotar el PAT de GitHub que aparece incrustado en la URL del remoto
     de la copia local `BitacoraGRM` (caduca el 2026-12-07). El remoto
     del repositorio publico de este proyecto NO lleva token.
  3. Definir una `SECRET_KEY` real y montar un volumen en `/data` con
     el fichero de secreto, para que no se genere en cada arranque.
  4. Migrar la configuracion del panel de Railway ANTES del 2026-12-01
     (Railway deja de leer `railway.toml`).
  5. Rotar la contrasena de PostgreSQL: en README V1.004 se publico un
     prefijo de cuatro caracteres (ya redactado, pero la rotacion sigue
     pendiente).
  6. Decidir si el registro publico se cierra (hay usuarios reales).
  7. Enviar la rotacion de la credencial de administrador al responsable
     de la operacion por un canal privado: la contrasena NO se escribe
     en ningun fichero del repositorio.

--------------------------------------------------------------------------------
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
--------------------------------------------------------------------------------

7.1) Despliegue
---------------
  1. Publicar el lote:

       git -c http.extraheader="AUTHORIZATION: basic <base64>"
           push https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git main

     (fast-forward desde 90a2879; nunca `--force`).

  2. El push dispara el redespliegue automatico de los TRES servicios de
     Railway (web, worker, beat) porque los tres leen el mismo
     repositorio y ejecutan `start.sh`.

  3. En el log de cada servicio debe aparecer:

       [start.sh] Verificando/Aplicando migraciones...
       [migrations] aplicar: aplicadas=0 omitidas=25 errores=0 errores_esquema=0

     Si aparece `[start.sh] ERROR: las migraciones fallaron...` y el
     proceso sale con codigo 1, el servicio NO arranca (es
     intencionado): ver 7.4.

  4. El worker debe registrar la tarea nueva:

       [celery]  ... registered: app.tasks.salud_tasks.registrar_latido

     y el beat debe planificar `latido-salud` cada minuto.

  5. Comprobar el resultado:

       C:\Python311embed\python.exe -X utf8 tools\verificacion\verificar_produccion_negro.py
       C:\Python311embed\python.exe -X utf8 tools\verificacion\barrer_rutas.py

  6. Comprobar `/salud-celery` con sesion de administrador: `beat.ok`
     debe ser `true` en menos de dos minutos desde el despliegue (el
     latido se escribe cada minuto).

7.2) Ventana de observacion
----------------------------
  - Tras el push, esperar a que los tres servicios pasen a estado
    "Running". El reinicio del worker interrumpe las tareas en curso
    unos segundos: es normal y no implica perdida (las tareas de Celery
    son idempotentes y se reintentan).
  - Comprobar `/health` y `/ready` antes de dar el despliegue por bueno.

7.3) Rollback normal
--------------------
  Si el comportamiento es correcto pero hay que volver atras:

    git revert --no-edit <commit>          # uno a uno, en orden inverso
    git -c http.extraheader="AUTHORIZATION: basic <base64>"
        push https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git main

  Nota: `git revert` genera commits nuevos; el historial publico NO se
  reescribe y nunca se usa `--force`.

  Rollback del lote completo: revertir en este orden 3b1ffab, 1a13850,
  76781eb, 6e5ced1, 3cb4476, 58e9a96, 66a1302, 26cf486. El ultimo en
  revertir es 26cf486 (fail-closed): mientras siga puesto, el arranque
  aborta si el esquema no esta alineado.

7.4) Rollback de EMERGENCIA (el fail-closed bloquea el arranque)
-----------------------------------------------------------------
  Sintoma: los tres servicios reinician en bucle y el log muestra
  "[start.sh] ERROR: las migraciones fallaron o el esquema quedo
  desactualizado." y "No se inicia el proceso para no servir con un
  esquema incorrecto."

  Diagnostico (leer el log del despliegue, no la base de datos):
    - Si el mensaje es "DERIVA DE ESQUEMA: <tabla>: faltan <columnas>",
      el problema es de esquema: revisar que la migracion correspondiente
      se aplico.
    - Si el mensaje es "N error(es) de esquema al aplicar las
      migraciones", revisar el error concreto de `create_all` o de
      `ALTER TABLE`.
    - Si el mensaje es "la comprobacion de esquema no pudo ejecutarse",
      el propio guard fallo: NO se corta el arranque por eso (devuelve 0)
      y hay que mirar la causa.

  Si la causa es del propio fail-closed y no del esquema, revertir
  26cf486 y republicar: el arranque vuelve al comportamiento anterior
  (aplica las migraciones y continua aunque falle).

  En ningun caso se edita a mano el esquema de la base de datos de
  produccion desde este entorno: no se ha ejecutado nunca ninguna
  escritura contra ella y no se debe empezar a hacerlo por un
  incidente.

--------------------------------------------------------------------------------
ANEXO A. CODIGO MODIFICADO O PARCHE EXACTO CON LAS FUNCIONES INTERVENIDAS
--------------------------------------------------------------------------------

A.1) app/db/migrations.py - funciones nuevas
---------------------------------------------

    def _asegurar_modelos_importados() -> None:
        """Importa el paquete de modelos para que ``Base.metadata`` los conozca.
        ...
        """
        try:
            import app.models  # noqa: F401
        except Exception as exc:  # pragma: no cover
            logger.error(
                "[migrations] No se pudieron importar los modelos: %s. "
                "Las migraciones pueden fallar por tablas inexistentes.", exc,
            )

    def verificar_esquema(eng: Optional[Engine] = None) -> int:
        try:
            stats = apply_migrations(eng)
            lineas = report_schema_drift(eng)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[migrations] la comprobacion de esquema no pudo ejecutarse: %s. "
                "Se continua el arranque: el guard no debe ser el que tumbe el "
                "servicio.", exc,
            )
            return 0

        faltan = [l for l in lineas if "faltan" in l]
        errores = int(stats.get("errors", 0) or 0)
        errores_esquema = int(stats.get("schema_errors", 0) or 0)
        logger.info(
            "[migrations] aplicar: aplicadas=%s omitidas=%s errores=%s "
            "errores_esquema=%s",
            stats.get("applied", 0), stats.get("skipped", 0), errores,
            errores_esquema,
        )
        if faltan:
            logger.error("[migrations] DERIVA DE ESQUEMA: %s", "; ".join(faltan))
        if errores_esquema:
            logger.error(
                "[migrations] %s error(es) de esquema al aplicar las migraciones",
                errores_esquema,
            )
        if errores and not errores_esquema:
            logger.warning(
                "[migrations] %s error(es) en las migraciones de DATAS. El esquema "
                "queda alineado, se continua el arranque.", errores,
            )
        return 1 if (faltan or errores_esquema) else 0

A.2) app/db/migrations.py - apply_migrations (extracto)
--------------------------------------------------------
    stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0,
             "schema_errors": 0, "tables_created": 0, "data_migrated": 0}
    ...
    except Exception as e:
        logger.warning("[migrations] No se pudo verificar el esquema base: %s", e)
        stats["errors"] += 1
        stats["schema_errors"] += 1
    ...
                except Exception as e:
                    logger.warning(
                        "[migrations] No se pudo anadir %s.%s: %s",
                        table, column, e,
                    )
                    stats["errors"] += 1
                    stats["schema_errors"] += 1

A.3) app/db/migrations.py - migracion 4.6 (extracto, rama SQLite)
------------------------------------------------------------------
    "INSERT INTO estados (nombre, descripcion, color, orden, "
    "es_inicial, es_final, categoria, sla_horas, archivado, "
    "limite_wip, es_entrega, created_at, updated_at) "
    "SELECT 'Produccio On OK', "
    "       'Correccio On desplegada y verificada en ambiente productivo', "
    "       '#0d9488', COALESCE((SELECT MAX(orden)+1 FROM estados), 7), "
    "       0, 1, 'produccion_ok', NULL, 0, NULL, 0, :ts, :ts"

    (La rama PostgreSQL es la misma con FALSE en lugar de 0.)

A.4) start.sh - bloque de migraciones
--------------------------------------
    echo "[start.sh] Verificando/Aplicando migraciones..."
    if ! python -c "import sys; from app.db.migrations import verificar_esquema; sys.exit(verificar_esquema())"; then
        echo "[start.sh] ERROR: las migraciones fallaron o el esquema quedo O desactualizado." >&2
        echo "[start.sh] No se inicia el proceso para no servir con un esquema incorrecto." >&2
        exit 1
    fi

A.5) app/tasks/salud_tasks.py - fichero nuevo completo
--------------------------------------------------------
    CLAVE_LATIDO = "bitacora:salud:beat"
    TTL_LATIDO = 300

    @celery_app.task(name="app.tasks.salud_tasks.registrar_latido")
    def registrar_latido() -> dict:
        from app.core.config import settings

        ahora = datetime.now(timezone.utc).isoformat()
        cliente = None
        try:
            import redis

            cliente = redis.Redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            cliente.set(CLAVE_LATIDO, ahora, ex=TTL_LATIDO)
            return {"ok": True, "latido": ahora}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[salud:latido] No se pudo escribir el latido: %s", exc)
            return {"ok": False, "error": str(exc)}
        finally:
            if cliente is not None:
                try:
                    cliente.close()
                except Exception:  # noqa: BLE001
                    pass

    def leer_latido() -> dict:
        from app.core.config import settings

        ahora = datetime.now(timezone.utc)
        cliente = None
        try:
            import redis

            cliente = redis.Redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            bruto = cliente.get(CLAVE_LATIDO)
            if not bruto:
                return {"ok": False, "latido": None, "antiguedad_segundos": None,
                        "detalle": "sin latido: la cadena beat -> worker no completo "
                                   "la tarea programada (...)"}
            marca = datetime.fromisoformat(bruto.decode("utf-8"))
            antiguedad = (ahora - marca).total_seconds()
            return {
                "ok": antiguedad <= TTL_LATIDO,
                "latido": marca.isoformat(),
                "antiguedad_segundos": round(antiguedad, 1),
                "detalle": ("OK" if antiguedad <= TTL_LATIDO
                            else f"el ultimo latido es de hace {antiguedad:.0f}s (vencido)"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "latido": None, "antiguedad_segundos": None,
                    "detalle": f"error al leer Redis: {exc}"}
        finally:
            if cliente is not None:
                try:
                    cliente.close()
                except Exception:  # noqa: BLE001
                    pass

A.6) app/core/celery_app.py - include y beat_schedule
--------------------------------------------------------
        include=[
            ...
            "app.tasks.salud_tasks",
        ],
        ...
        beat_schedule={
            ...
            "latido-salud": {
                "task": "app.tasks.salud_tasks.registrar_latido",
                "schedule": crontab(minute="*"),
            },
        },

A.7) app/main.py - endpoint GET /salud-celery (completo)
------------------------------------------------------------
    @app.get("/salud-celery")
    def salud_celery(request: Request):
        import time
        from datetime import datetime, timezone

        from fastapi import HTTPException

        from app.models.usuario import RolUsuario

        usuario = _get_usuario_actual(request)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Se requiere sesion activa")
        if usuario.rol != RolUsuario.ADMINISTRADOR:
            raise HTTPException(
                status_code=403, detail="Acceso restringido a Administradores"
            )

        from app.core.celery_app import celery_app
        from app.tasks.salud_tasks import leer_latido

        ahora = datetime.now(timezone.utc)

        worker = {"responde": False, "workers": [], "detalle": ""}
        inicio = time.monotonic()
        try:
            respuestas = celery_app.control.ping(timeout=2.0) or {}
            worker["responde"] = bool(respuestas)
            worker["workers"] = sorted(str(k) for k in respuestas.keys())
            worker["detalle"] = (
                "OK" if respuestas else "ningun worker respondio al ping"
            )
        except Exception as exc:  # noqa: BLE001
            worker["detalle"] = f"error al preguntar al broker: {exc}"
        worker["consulta_segundos"] = round(time.monotonic() - inicio, 2)

        beat = leer_latido()

        colas = {}
        try:
            cola = celery_app.conf.task_default_queue or "celery"
            with celery_app.connection() as conexion:
                canal = conexion.default_channel
                cliente = getattr(canal, "client", None)
                if cliente is not None and hasattr(cliente, "llen"):
                    colas[cola] = int(cliente.llen(cola))
                elif hasattr(canal, "_size"):
                    colas[cola] = int(canal._size(cola))
                else:
                    colas[cola] = None
                    colas["detalle"] = "el transporte del broker no expone la profundidad"
        except Exception as exc:  # noqa: BLE001
            colas["error"] = str(exc)

        programadas = []
        for nombre, cfg in (celery_app.conf.beat_schedule or {}).items():
            programadas.append({
                "nombre": nombre,
                "tarea": cfg.get("task"),
                "programacion": str(cfg.get("schedule", "")),
            })

        return {
            "ok": bool(worker["responde"] and beat.get("ok")),
            "worker": worker,
            "beat": beat,
            "colas": colas,
            "tareas_programadas": programadas,
            "generado": ahora.isoformat(),
        }

A.8) app/services/ticket_service.py - crear_ticket (extracto)
-----------------------------------------------------------------
        titulo = str(datos.get("titulo") or "").strip()
        if not titulo:
            raise ValueError("El titulo del ticket no puede estar vacio.")

        estado_solicitado_id = datos.get("estado_id")
        roles_que_asignan_estado = (RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)
        puede_asignar_estado = (
            usuario.rol in roles_que_asignan_estado if usuario is not None else False
        )
        if estado_solicitado_id is not None and puede_asignar_estado:
            estado_asignado = (
                self.db.query(Estado).filter(Estado.id == estado_solicitado_id).first()
            )
            if not estado_asignado:
                raise TransicionInvalidaError(
                    f"Estado {estado_solicitado_id} no existe.",
                    codigo="ESTADO_NO_ENCONTRADO",
                )
        else:
            estado_asignado = (
                self.db.query(Estado).filter(Estado.es_inicial == True).first()
            )
            if not estado_asignado:
                raise TransicionInvalidaError(
                    "No hay un estado inicial configurado en el sistema.",
                    codigo="SIN_ESTADO_INICIAL",
                )
        ...
            titulo=titulo,
            descripcion=datos.get("descripcion") or "",
            ...
            estado_id=estado_asignado.id,
        ...
        if estado_asignado.sla_horas is not None:
            ticket.fecha_vencimiento_sla = now_utc() + timedelta(
                hours=estado_asignado.sla_horas
            )

A.9) app/services/ticket_service.py - cambiar_estado (extractos)
------------------------------------------------------------------
        # 5) Recalcular SLA so Olo al cambiar realmente de estado.
        if not mismo_estado and estado_destino.sla_horas is not None:
            ticket.fecha_vencimiento_sla = ahora + timedelta(
                hours=estado_destino.sla_horas
            )
            ticket.sla_cumplido = -1  # pendiente

        if not mismo_estado and estado_destino.es_final:
            if nombre_destino_norm == "produccion ok":
                ticket.sla_cumplido = 1
            elif ticket.fecha_vencimiento_sla:
                referencia = ticket.fecha_completado or ahora
                ticket.sla_cumplido = (
                    0 if referencia > ticket.fecha_vencimiento_sla else 1
                )
            elif ticket.sla_cumplido == -1:
                ticket.sla_cumplido = 1

        # Todo estado final cierra formalmente el ticket.
        if estado_destino.es_final and ticket.fecha_completado is None:
            ticket.fecha_completado = ahora

A.10) app/services/notificacion_responsable_service.py (extracto)
---------------------------------------------------------------------
        db.add(notif)
        try:
            with db.begin_nested():
                db.flush()
            notif_created = True
        except Exception as exc:
            logger.exception("[notif-resp] No se pudo crear Notificacion: %s", exc)
            notif_created = False

A.11) app/static/js/htmx-events.js (extracto)
-------------------------------------------------
    function _urlMarkdownSegura(url) {
      let s = String(url == null ? '' : url).trim();
      if (!s) return '';
      s = s.replace(/[\u0000-\u0020\u007f]+/g, '');
      if (!s) return '';
      const m = /^([a-zA-Z][a-zA-Z0-9+.\-]*):/.exec(s);
      if (m) {
        const permitidos = ['http:', 'https:', 'mailto:'];
        if (permitidos.indexOf(m[1].toLowerCase() + ':') === -1) return '';
      }
      return s;
    }

    function renderMarkdown(md) {
      if (!md || !md.trim()) return '<p class="text-slate-400 italic">Sin contenido</p>';
      let s = String(md)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
      ...
      s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, texto, url) {
        const href = _urlMarkdownSegura(url);
        if (!href) return texto;
        return '<a href="' + href + '" target="_blank" rel="noopener noreferrer" ' +
               'class="text-indigo-600 underline">' + texto + '</a>';
      });

A.12) railway.toml (extracto)
--------------------------------
    [deploy]
    ...
    restartPolicyType = "ON_FAILURE"
    restartPolicyMaxRetries = 5
    numReplicas = 1
    ...
    PYTHONDONTWRITEBYTECODE = "1"
    APP_VERSION = "0.1.0"
    DEBUG = "false"
    USE_SQLITE = "false"
    AUTO_INIT_DB = "false"

    (Se elimino la clave TOMB duplicada `PYTHONDONTWRITEBYTECODE`.)

--------------------------------------------------------------------------------
8. ADDENDUM: VERIFICACION EN PRODUCCION Y CORRECCIONES POSTERIORES
--------------------------------------------------------------------------------

Este addendum se anade al mismo incremento (no es un lote nuevo): documenta
lo que se Midio en produccion DESPUES de publicar el README, las dos
correcciones que salieron de esa medicion y el un punto que queda
pendiente del propietario.

8.1) Lo que se verifico en produccion (todo con peticiones GET)
-------------------------------------------------------------------
  - El servicio web se redesplego correctamente: el esquema paso de 197 a
    198 paths y de 123 a 124 rutas GET, y expone `/salud-celery`.
  - Barrido autenticado (`barrer_rutas.py`): TODAS las comprobaciones
    superadas y 0 respuestas 5xx. Reparto de la API: 111 respuestas 200,
    2 x 307, 1 x 410, 3 x 422, 2 x 404 y 5 x 403, todos esperables
    (recursos inexistentes o acceso restringido, ninguno por ruta rota).
  - `/salud-celery` sin sesion responde 401 y con rol no administrador 403.
  - Verificador en negro: 26 comprobaciones, 25 PASA y 1 FALLA (el latido
    del beat, ver 8.3).

8.2) Correccion 1: `Control.ping()` devuelve una lista, no un dict
-------------------------------------------------------------------
La primera version del endpoint trataba la respuesta del ping como un
diccionario. Celery 5.6.3 devuelve una LISTA de diccionarios
(`[{'celery@worker1': {'ok': 'pong'}}, ...]`), de modo que la llamada a
`respuestas.keys()` lanzaba `AttributeError`. La excepcion caia en el
`except`, con dos efectos: el campo `detalle` anunciaba un error que no
existia ("error al preguntar al broker: 'list' object has no attribute
'keys'") y la lista de workers quedaba siempre vacia, aunque `responde`
fuese True porque la lista tenia elementos.

Correccion: commit 0583d26. Se aceptan las dos formas (lista de dicts y
dict plano) y se listan los nombres de los workers que responden. Con la
correccion, produccion devuelve `workers: ['celery@fb03d2da82df']`.

Se anadieron dos tests de regresion (con un control de Celery simulado):
uno con dos workers que responden y otro con ninguno.

8.3) Hallazgo: los servicios worker y beat NO se redesplegan al hacer push
----------------------------------------------------------------------------
El latido del beat no aparecio en Redis. La medicion lo localizo de forma
concluyente:

  - `worker.tareas_registradas` = 12 y `worker.conoce_latido` = False.
    El codigo actual registra 13 tareas (12 de V1.005 + la nueva
    `app.tasks.salud_tasks.registrar_latido`): al worker le falta
    EXACTAMENTE la nueva.
  - El ping responde con `celery@fb03d2da82df` y la cola esta a 0.
  - 22 comprobaciones seguidas a lo largo de 11 minutos: siempre 12
    tareas, nunca el latido.
  - El servicio web, en cambio, si se redesplego en cada push (el
    endpoint nuevo aparece y la correccion del ping se ve en produccion).

Conclusion: el push a `main` redespliega el servicio web, pero los
servicios `worker` (51e22b0c) y `beat` (1c16b13c) siguen con el codigo
anterior. Por eso el beat no planifica `latido-salud` y el worker no
conoce la tarea. NO es un fallo del codigo de este lote: es la
configuracion de despliegue automatico de esos dos servicios en el panel
de Railway (o un build que no llega a publicarse). El servicio web no se
toca: es el que sirve las peticiones.

NO se pudo resolver desde este entorno:
  - El token de proyecto de Railway responde "Not Authorized" (revocado):
    la API no permite consultar ni reiniciar despliegues. Se verifico
    con una consulta de solo lectura.
  - El navegador embebido no responde (la navegacion a railway.app agota
    el tiempo limite), de modo que tampoco se pudo operar el panel.

8.4) Correccion 2: el catalogo de tareas del worker en el endpoint
-------------------------------------------------------------------
Con solo dos senales ("hay worker" y "no hay latido") no se puede
distinguir un worker con codigo viejo de un worker sano al que el beat
no publica la tarea. Se anade `inspect().registered()` (mismo mecanismo
de fanout que el ping) al endpoint: `worker.tareas_registradas` y
`worker.conoce_latido` dicen exactamente donde esta la rotura.

Correccion: commit 04c2f2a.

8.5) Lo que el propietario tiene que hacer para cerrar el punto
-----------------------------------------------------------------
En el panel de Railway, proyecto Bitacora-GRM_v2, entorno production:

  1. Servicio `worker` (51e22b0c) -> Deployments -> desplegar la version
     actual (o "Restart" si ya esta desplegada). Lo mismo en el servicio
     `beat` (1c16b13c).
  2. Revisar en el panel que ambos servicios tienen activada la opcion
     de despliegue automatico ante un push a `main`, para que no vuelva
     a pasar en el siguiente lote.
  3. Comprobar el resultado con sesion de administrador:
       GET /salud-celery
     y esperar a que `worker.conoce_latido` sea `true` y `beat.ok` sea
     `true` (el beat escribe el latido cada minuto; en cuanto el worker
     y el beat tengan el codigo nuevo, el latido aparece en menos de dos
     minutos).

  Al redesplegar, ademas, la `SECRET_KEY` se regenera si no hay volumen
  montado en `/data`: se observo que las sesiones abiertas dejan de
  valer (401) en el mismo instante del redespliegue. Es otra vez la
  accion 6.6.3.

8.6) Lo que NO se pudo verificar
---------------------------------
  - Que el servicio `beat` este vivo: no hay ninguna senal externa que
    lo demuestre en este despliegue. El detector de "SLA recalculado"
    solo sirve si existe un ticket con `sla_cumplido == -1` Y su
    vencimiento ya paso; en produccion hay exactamente uno y su
    vencimiento es el 2026-11-19, asi que no produce cambio observable.
    La unica prueba concluyente es el latido, que requiere el
    redespliegue de 8.5.
  - El estado interno de los despliegues en el panel (el token esta
    revocado).
  - Permisos 600 sobre NTFS, QA visual con navegador y el
    comportamiento interno de Railway.

8.7) El "Redeploy" del panel NO reconstruye la imagen
------------------------------------------------------
Al redesplegar worker y beat desde el panel, el hostname del worker
cambio (`celery@fb03d2da82df` -> `celery@80e74cad5ea6`): es un contenedor
nuevo. Pero el catalogo seguia mostrando 12 tareas y
`conoce_latido = False`: arranco con la MISMA imagen anterior.

La razon es el significado de la opcion del panel: "Redeploy" vuelve a
arrancar el deployment existente reutilizando su imagen; NO reconstruye
desde el codigo del repositorio. Para tomar el codigo actual hace falta
desplegar la rama, no redesplegar el deployment viejo.

Por eso la seccion 8 del verificador en negro comprueba ahora, ademas
del ping y del latido, que el worker CONOZCA la tarea del latido: es la
comprobacion que detecta un worker con un despliegue anterior. Y el
endpoint enriquece el detalle del beat con el diagnostico exacto:

  - `beat.diagnostico = "worker_desactualizado"`: el worker no tiene
    registrada la tarea del latido. Hay que desplegar la rama en el
    servicio worker.
  - `beat.diagnostico = "beat_desactualizado_o_parado"`: el worker
    conoce la tarea pero nadie la publica. Hay que desplegar la rama en
    el servicio beat (o el beat no esta planificando).

8.8) Causa raiz confirmada por la API de Railway
-------------------------------------------------
Con el token de proyecto renovado (nota de uso: el token de proyecto de
Railway va en la cabecera `Project-Access-Token`; con
`Authorization: Bearer` la API responde "Not Authorized"), la API
`serviceInstanceAutoDeployStatus` y `latestDeployment` darON la causa
exacta:

  Servicio  autoDeploy  ultimo commit desplegado
  --------  ----------  ------------------------------------------
  web       ACTIVADO    ae1d882 (HEAD de V1.006)      reason=deploy
  worker    DESACTIVADO 685df67 ("README V1.004 ...") reason=redeploy
  beat      DESACTIVADO 685df67 ("README V1.004 ...") reason=redeploy

Es decir: **worker y beat llevan el commit de V1.004 desde el 2026-10-24**
y su despliegue automatico ante push esta DESACTIVADO (el web si lo tiene
activo y por eso se actualizaba en cada push). El "Redeploy" del panel
reconstruyo ese commit viejo, de ahi el contenedor nuevo con codigo viejo.

Acciones aplicadas en este lote:
  1. Despliegue de la rama `main` en worker y beat con
     `serviceInstanceDeploy(latestCommit: true)`. Ambos arrancaron con el
     commit `bf8d9a8` (HEAD, reason=deploy).
  2. Rediseno del latido (2.11): ahora lo escribe el BEAT, con lo que la
     senal deja de depender del worker.

Lo que NO se pudo activar por API (queda como accion del propietario):
  - `serviceInstanceAutoDeployUpdate` y `deploymentTriggerCreate`
    responden **"Bad Access"** con el token de proyecto: crear el
    `repoTrigger` de los servicios worker y beat (como el `94058cbf` del
    web) requiere el token de API de usuario. Sin el, los dos servicios
    NO se actualizan solos con un push: hay que desplegar la rama desde
    el panel cada vez que toque.

8.9) Estado final verificado en produccion
---------------------------------------------
  GET /salud-celery (con sesion de administrador):
    ok                      true
    worker.responde         true   (celery@19800286faa4)
    worker.tareas_registradas 13  (incluye app.tasks.salud_tasks.registrar_latido)
    worker.conoce_latido    true
    beat.ok                 true
    beat.latido             2026-10-26T03:44:00Z (escrito por el beat)
    beat.antiguedad         49 s  (se renueva cada minuto)
    colas.celery            0

  Verificador en negro: 27 comprobaciones, 0 FALLOS.
  Barrido autenticado: 31 paginas + 124 endpoints GET, 0 respuestas 5xx.

================================================================================
FIN DEL README V1.006
================================================================================
