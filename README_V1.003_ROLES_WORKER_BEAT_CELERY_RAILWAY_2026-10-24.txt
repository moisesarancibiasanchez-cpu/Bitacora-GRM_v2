================================================================================
README V1.003 - ROLES WORKER Y BEAT DE CELERY EN RAILWAY
Bitácora GRM v2
Fecha: 2026-10-24
================================================================================

Documento anterior: README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_
POSTGRES_2026-10-24.txt (NO se modificó; este archivo es el siguiente de la
serie).

Motivo de este incremento: se pidió el procedimiento para reiniciar el Worker
y el Beat de Celery en Railway. Al revisar el panel de Railway y el código del
repositorio se comprobó que los servicios NO EXISTEN y que, aunque se
crearan tal cual, arrancarían el proceso equivocado. Este lote corrige los
dos defectos encontrados y deja el procedimiento real documentado.

--------------------------------------------------------------------------------
1. BASE
--------------------------------------------------------------------------------

Repositorio:         https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
Rama:                main
Commit base:         ca33dac  test(verificacion): verificar el flujo de Produccion OK
                                sobre una base sembrada
Commit funcional:    415a8fa9170ba794557eb3ab8d12e529490734eb
                      fix(railway): resolver el rol web/worker/beat y derivar las URLs
                      de Celery desde REDIS_URL
Tipo de publicación: fast-forward (ca33dac..415a8fa, sin --force)
Fecha:               2026-10-24
Aplicación:          https://bitacora-grmv2-production.up.railway.app
Guía de Onboarding:   https://8ww9qr1jzjgp8.space.minimax.io
URL anterior (V1.001, sigue activa): https://dshj4lrwlf4x.space.mcode.io

Estado de partida (verificado, no supuesto):
  - El servicio web está 100% operativo: /health responde 200 con
    {"status":"ok","database":"ok","redis":"ok"} y /info responde 200 con
    {"debug":false,"redis_configured":true,"celery_broker_configured":true}.
  - El proyecto de Railway contiene TRES recursos y UN solo servicio de
    aplicación (captura del panel del 2026-10-24):
        Postgres  -> Online
        Redis     -> Online
        Bitacora-GRM_v2 (bitacora-grmv2-production.up.railway.app) -> Online
    NO existen servicios "worker" ni "beat". Por tanto NO hay nada que
    reiniciar: hay que CREARLOS.
  - El historial de deployments del panel muestra entradas "REMOVED": son
    despliegues antiguos del mismo servicio web (Railway los marca así al
    rotar imágenes), no servicios eliminados.

Documentos anteriores de la serie: NO se modificaron.

--------------------------------------------------------------------------------
2. CAMBIO ÚNICO
--------------------------------------------------------------------------------

Un solo cambio funcional: QUE LOS SERVICIOS WORKER Y BEAT DE CELERY
ARRANQUEN EL PROCESO CORRECTO Y PUEDAN OPERAR CONTRA EL REDIS DE RAILWAY.

Para conseguirlo hubo que corregir dos defectos reales, ambos presentes en el
repositorio en el momento de partida:

2.1) El rol del proceso se resolvía con una variable que Railway no inyecta
-------------------------------------------------------------------------------
  Archivo:  start.sh (antes: línea 197)
  Antes:
      ROLE="${RAILWAY_SERVICE_ROLE:-${PROC_TYPE:-web}}"
  Problema:
      Railway NO define RAILWAY_SERVICE_ROLE ni RAILWAY_SERVICE_TYPE. La
      lista oficial de variables del sistema es exhaustiva y no incluye
      ninguna de las dos
      (https://docs.railway.com/variables/reference).
      Con el código anterior, $RAILWAY_SERVICE_ROLE y $PROC_TYPE llegaban
      vacíos y TODOS los servicios caían en el rol "web": un servicio
      "worker" o "beat" arrancaba gunicorn. El servicio quedaba ACTIVO en el
      panel (gunicorn responde HTTP) pero NUNCA consumía ninguna tarea, sin
      ningún error visible. Es el fallo más difícil de detectar: el panel
      dice "healthy".
  Después (start.sh:217-262):
      $PROC_TYPE > $APP_ROLE > $RAILWAY_SERVICE_ROLE > $RAILWAY_SERVICE_NAME
      - RAILWAY_SERVICE_NAME sí la inyecta Railway siempre (es el nombre del
        servicio): si el servicio se llama "celery-worker" o "celery-beat",
        el rol se deduce solo, sin configurar nada.
      - Un rol explícito e inválido ABORTA con código de error (antes
        caía silenciosamente en gunicorn).
      - "cron" NO se mapea a "beat" a propósito: el Cron Job de Railway exige
        que el proceso termine y celery beat es un planificador permanente.

2.2) El broker de Celery no se derivaba de la única variable que Railway
     inyecta
-------------------------------------------------------------------------------
  Archivo:  app/core/config.py
  Antes:
      REDIS_URL: str = "redis://localhost:6379/0"
      CELERY_BROKER_URL: str = "redis://localhost:6379/1"
      CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
  Problema:
      Railway solo inyecta REDIS_URL al adjuntar el plugin de Redis. Los
      campos CELERY_BROKER_URL / CELERY_RESULT_BACKEND se quedaban en el
      default local, de modo que un worker o beat recien creado publicaba
      contra redis://localhost:6379 y fallaba con ConnectionError nada más
      arrancar (y el fallo quedaba silenciado por los try/except de los
      llamadores, ver 6.6).
  Después (app/core/config.py:22-48 y 212-236):
      - Si CELERY_BROKER_URL / CELERY_RESULT_BACKEND no vienen del entorno,
        se derivan de REDIS_URL usando las bases 1 y 2 (conservando
        esquema, credenciales, host, puerto y query).
      - Si vienen del entorno (panel de Railway o .env), mandan sobre el
        valor derivado: nunca se sobrescribe una configuración explícita.
      - Sin REDIS_URL se conservan los defaults de desarrollo
        (redis://localhost:6379/1 y /2): comportamiento local idéntico.

2.3) Cambios de apoyo (no alteran el comportamiento funcional del producto)
-------------------------------------------------------------------------------
  - celery beat escribe su fichero de calendario en
    /tmp/celerybeat-schedule (start.sh:322), ruta escribible: el directorio
    de trabajo del contenedor puede ser de solo lectura. Se puede cambiar con
    CELERY_BEAT_SCHEDULE_FILE.
  - .gitattributes (nuevo): fuerza LF en *.sh, *.bash y Procfile. Con CRLF,
    bash falla ANTES de arrancar (/usr/bin/env bash^M, "set: -e\r: invalid
    option"). Verificado: el blob publicado de start.sh tiene CR=0, LF=330.
  - RAILWAY_DEPLOY.md y railway.toml: procedimiento real de creación y
    reinicio de worker y beat, tabla de síntomas/ causas / soluciones, alcance
    real de railway.toml y aviso de deprecación de Config as Code.

--------------------------------------------------------------------------------
3. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------

- El modelo de datos: ni una migración, ni una columna, ni un índice.
  app/db/migrations.py NO se tocó.
- Los contratos de API: ni una ruta, ni un parámetro, ni un código de
  estado. El OpenAPI es idéntico.
- La lógica de negocio ITSM (estados, transiciones, roles, Butler,
  deadlines, SLA, reportes, backups): intacta.
- El catálogo SSOT de resultado de pruebas (app/core/resultado_pruebas.py) y
  los tres renderizadores del badge: intactos. 0 hex duplicados.
- Las plantillas (app/templates/**): intactas.
- El servicio web: su start command, su healthcheck, su dominio y sus
  variables de entorno NO se modifican. Sigue arrancando gunicorn.
- La lógica de arranque de la web (guard de configuración, derivación de
  PUBLIC_BASE_URL, degradación de CORS, SECRET_KEY de start.sh): intacta.
  app/core/config.py solo suma el validador _derivar_urls_celery.
- La cola, el broker, el backend de resultados y el calendario de Celery:
  el CALENDARIO no se tocó. app/core/celery_app.py NO se modificó: las
  7 tareas programadas (recalcular SLA cada 5 min, notificar SLA cada
  15 min, limpiar notificaciones a las 02:00, deadlines cada hora, triggers
  a las 08:00, backup diario, reporte de entregas a las 18:00 UTC) siguen
  igual.
- La base de datos de producción: cero escrituras. No se ejecutó ningún
  comando contra la base de datos de Railway en este lote (verificado: los
  verificadores usan copia SQLite temporal o lectura HTTP).
- Los 17 verificadores previos de tools/verificacion/: intactos. Se añadió
  uno nuevo (18 en total).
- La guía de Onboarding publicada: intacta.
- La documentación README_V1.001 y README_V1.002: intactas.

--------------------------------------------------------------------------------
4. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

4.1) DICTAMEN SOBRE EL REINICIO DEL WORKER Y DEL BEAT
-------------------------------------------------------------------------------
  - Servicio WEB: NO requiere reinicio manual. El push a main provoca el
    redeploy automático del servicio (Railway está conectado al repositorio
    por GitHub). El único efecto funcional en la web es que el broker de
    Celery pasa a derivarse de REDIS_URL.
  - Servicio WORKER: NO EXISTE. No hay nada que reiniciar: hay que CREARLO.
  - Servicio BEAT:   NO EXISTE. No hay nada que reiniciar: hay que CREARLO.
  - Una vez creados y con las variables correctas, "reiniciar" un worker o un
    beat es: panel -> servicio -> Deployments -> deployment ACTIVE -> menu de
    tres puntos -> Restart (o `railway redeploy --service <svc>
    --environment production`). En Railway, cambiar una variable deja los
    cambios en "staged changes": hay que pulsarlos (Deploy) para que se
    apliquen; un Restart sin ese Deploy no aplica la variable nueva.

4.2) Variables obligatorias (idénticas para worker y beat)
-------------------------------------------------------------------------------
  PROC_TYPE=worker        (en el servicio worker)
  PROC_TYPE=beat          (en el servicio beat)
  DATABASE_URL=${{Postgres.DATABASE_URL}}
  REDIS_URL=${{Redis.REDIS_URL}}
  SECRET_KEY=<la misma que la del servicio web>
  DEBUG=false
  USE_SQLITE=false
  PUBLIC_BASE_URL=https://bitacora-grmv2-production.up.railway.app
  CORS_ORIGINS=["https://bitacora-grmv2-production.up.railway.app"]
  Opcional: CELERY_BROKER_URL / CELERY_RESULT_BACKEND si se quieren fijar
  las bases 1 y 2 de forma explícita (si no, se derivan de REDIS_URL).

  Recomendación: definir SECRET_KEY, DEBUG, USE_SQLITE y PUBLIC_BASE_URL como
  Shared Variables del proyecto, para que los tres servicios las compartan y
  no haya que repetirlas.

4.3) Start Command de los servicios nuevos
-------------------------------------------------------------------------------
  bash start.sh
  (el rol se decide por PROC_TYPE, no por el Start Command: funciona igual
  si el servicio hereda railway.toml, cuyo startCommand es "bash start.sh", o
  si usa el Start Command del panel)

  Alternativa válida si se prefiere no usar start.sh:
      celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=2
      celery -A app.core.celery_app:celery_app beat --loglevel=info
  En ese caso se pierde la espera a la base de datos y la garantia de
  SECRET_KEY del propio start.sh (el worker y el beat no la necesitan para
  arrancar, pero es preferible la via unica).

4.4) Healthcheck de los servicios nuevos
-------------------------------------------------------------------------------
  El servicio worker/beat NO tiene servidor HTTP. Si el panel le asigna un
  "Healthcheck Path" (/health), el healthcheck fallara, el deployment se
  marcara como fallido y Railway lo reiniciara en bucle. Dejar el campo
  "Healthcheck Path" VACIO en worker y beat. Solo el servicio web lo necesita.

4.5) NO usar "Cron Schedule" de Railway para el beat
-------------------------------------------------------------------------------
  El Cron Job de Railway exige que el proceso termine al acabar (si no, se
  saltan las ejecuciones siguientes) y celery beat es un planificador
  permanente. El calendario ya lo lleva celery (app/core/celery_app.py).
  Ademas, debe existir UN SOLO servicio beat: dos instancias dispararian
  cada tarea programada dos veces.

4.6) Aviso: Config as Code esta deprecado
-------------------------------------------------------------------------------
  Railway ha deprecado los archivos railway.toml / railway.json:
    - Los servicios NUEVOS no pueden optar a Config as Code (un worker o un
      beat creados desde este repo NO heredan el railway.toml; usan su
      Start Command del panel).
    - El 2026-12-01 Railway deja de leer estos archivos. Ese dia, el
      startCommand, el healthcheckPath y las variables [env] del
      railway.toml (DEBUG, USE_SQLITE, APP_VERSION, PYTHONUNBUFFERED)
      dejan de aplicarse al servicio web existente.
  ACCION PREVENTIVA (panel): definir DEBUG=false, USE_SQLITE=false y
  SECRET_KEY como variables del servicio web (o Shared Variables del
  proyecto). El arranque de la web en DEBUG=True no es bloqueante, pero
  expone /docs y el detalle de errores, y el wildcard de CORS solo se
  degrada a advertencia en DEBUG=False.

4.7) Lo que NO hace falta para este despliegue
-------------------------------------------------------------------------------
  - No hace falta tocar la base de datos ni ejecutar migraciones.
  - No hace falta cambiar el servicio web.
  - No hace falta reconstruir la imagen ni tocar requirements.txt.
  - No hace falta montar volumen en worker/beat: el volumen en /data solo
    afecta a la persistencia de la SECRET_KEY, que para el worker y el beat
    es irrelevante (no emiten sesiones).

--------------------------------------------------------------------------------
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

5.1) Verificación automatizada (desde la raíz del repositorio)
-------------------------------------------------------------------------------
  Ejecuta el verificador nuevo (16/16 comprobaciones; ejecuta el start.sh real
  con ejecutables stub para observar qué proceso se lanzaría):
      python tools/verificacion/verificar_rol_celery.py
  Verifica además que no se ha roto nada:
      python -m pytest tests/ -q --tb=line
      python tools/verificacion/verificar_config.py
      bash  tools/verificacion/verificar_secret_key.sh

5.2) Verificación en el panel de Railway (tras crear los servicios)
-------------------------------------------------------------------------------
  En los logs de cada servicio nuevo debe aparecer, en este orden:
      [start.sh] Rol detectado desde PROC_TYPE='worker' -> worker
      [start.sh] Iniciando Bitácora GRM (rol=worker)
      ... celery@<host> ready
  y para el beat:
      [start.sh] Rol detectado desde PROC_TYPE='beat' -> beat
      [start.sh] Iniciando Bitácora GRM (rol=beat)
      ... celery beat v5.x starting
  Si en los logs aparece "rol=web", la variable PROC_TYPE no está llegando al
  contenedor (o tiene otro valor).

5.3) Verificación funcional de que el worker consume tareas
-------------------------------------------------------------------------------
  - Mover un ticket entre estados: el servicio web encola recalcular_sla y
    notificar_cambio_estado. Con el worker activo, en los logs del worker
    aparecen las tareas recibidas ("Task app.tasks.sla_tasks.recalcular_sla
    ... received"). Sin worker, esas tareas se acumulan en la cola y la
    aplicación no falla (los .delay() están protegidos por try/except), pero
    el SLA no se recalcula y no se envían notificaciones.
  - Revisar el estado del SLA de un ticket en la interfaz antes y después de
    un cambio de estado, con el worker en marcha.
  - Revisar el backup diario: la tarea backup_database_diario escribe en
    BACKUP_DIR (volumen o disco del contenedor).

5.4) Verificación del calendario (beat)
-------------------------------------------------------------------------------
  - Tras el arranque del beat, el fichero /tmp/celerybeat-schedule debe
    existir en el contenedor.
  - La tarea recalcular-sla-cada-5-min (cada 5 minutos) es la más rápida para
    confirmar que el beat está encolando: en los logs del worker deben
    aparecer tareas de app.tasks.sla_tasks.recalcular_sla_masivo con una
    cadencia de 5 minutos.

5.5) Verificación de que NO se rompió la web
-------------------------------------------------------------------------------
      curl -s -o /dev/null -w '%{http_code}' https://bitacora-grmv2-production.up.railway.app/health
      (debe devolver 200)
  Login, /kanban y /dashboard deben seguir respondiendo 200. El barrido de
  rutas y el de enlaces internos se pueden volver a ejecutar con:
      python tools/verificacion/barrer_rutas.py

--------------------------------------------------------------------------------
6. TRAZABILIDAD
--------------------------------------------------------------------------------

6.1) Commit
-------------------------------------------------------------------------------
  415a8fa9170ba794557eb3ab8d12e529490734eb
  fix(railway): resolver el rol web/worker/beat y derivar las URLs de Celery
  Publicación: fast-forward sobre ca33dac. Sin --force.

6.2) Archivos modificados (4) y añadidos (2) respecto de ca33dac
-------------------------------------------------------------------------------
  Modificados:
    app/core/config.py                        (+61 / -3)
    start.sh                                 (+82 / -6)
    railway.toml                             (+33 / -6)
    RAILWAY_DEPLOY.md                         (+113 / -25)
  Añadidos:
    .gitattributes                            (9 lineas)
    tools/verificacion/verificar_rol_celery.py   (nuevo, 16 comprobaciones)

6.3) Referencias de línea exactas
-------------------------------------------------------------------------------
  app/core/config.py:18      _CELERY_BROKER_DEFAULT / _CELERY_BACKEND_DEFAULT
  app/core/config.py:22      _redis_url_con_db(url, db)
  app/core/config.py:88-92   comentario de REDIS_URL/CELERY_* y defaults
  app/core/config.py:212     def _derivar_urls_celery(self)
  app/core/config.py:233     self.CELERY_BROKER_URL = _redis_url_con_db(REDIS_URL, 1)
  app/core/config.py:235     self.CELERY_RESULT_BACKEND = _redis_url_con_db(REDIS_URL, 2)
  start.sh:217               _normalizar_rol()
  start.sh:230               _detectar_rol()
  start.sh:244               log "Rol detectado desde $fuente"
  start.sh:253-255           inferencia por RAILWAY_SERVICE_NAME
  start.sh:322               --schedule="${CELERY_BEAT_SCHEDULE_FILE:-/tmp/celerybeat-schedule}"
  app/services/ticket_service.py:394-404   .delay() protegidos (try/except)
  app/services/ticket_service.py:414-424   .delay() de entregas (try/except)
  app/services/ticket_service.py:650-659   .delay() de archivado (try/except)

6.4) Huellas SHA-256 de los archivos publicados
-------------------------------------------------------------------------------
  2577b26a98a92eccc6bca988cd10bb069765bc0bc10ac1e12126bdf275f1876d  app/core/config.py
  b1317ae4ac8c23af9b64b5f42f626579857b1315bee3ada6f91286fa7c926b6d  start.sh
  8de5b851f6b920d2918d2aacd3eac86f8bd05a8da7b8faa112879b5d275142b5  railway.toml
  84db0f46f6c31831e371bd16bd5d09fd34a7faf414fe8eefd26e7e179b6e041a  RAILWAY_DEPLOY.md
  69e7f300a855b80347d638a78b4d63e1e35dae0ddd2016229665c911ba7e8cf2  .gitattributes
  771841d7a2833046b1c5d0d543c87defb6c132b2356c208f2e5387e965d7123e  tools/verificacion/verificar_rol_celery.py

6.5) Evidencia de validación (todo con ejecución real, sin mocks ni datos
    falsos)
-------------------------------------------------------------------------------
  tools/verificacion/verificar_rol_celery.py   16/16 comprobaciones OK
      [1] Derivacion de CELERY_BROKER_URL / CELERY_RESULT_BACKEND   6/6
      [2] Resolucion de rol ejecutando el start.sh real              10/10
          (web por nombre de servicio; PROC_TYPE=worker; PROC_TYPE=beat;
           APP_ROLE=worker; RAILWAY_SERVICE_NAME=celery-worker;
           RAILWAY_SERVICE_NAME=celery-beat; RAILWAY_SERVICE_ROLE=worker;
           rol invalido -> aborta; "cron" -> aborta; beat con --schedule)
  pytest tests/ -q --tb=line                   91 passed, 0 failed (290,85 s)
  tools/verificacion/verificar_config.py       todas las comprobaciones OK
  tools/verificacion/verificar_secret_key.sh    todas las comprobaciones OK
  Produccion: /health 200, /info 200 (debug=false, redis_configured=true)
  Blob publicado de start.sh: CR=0, LF=330 (LF, sin CRLF)
  El servicio web se redeploya solo al hacer push (Railway + GitHub).

6.6) Hallazgos NO resueltos en este lote (declarados, no ocultados)
-------------------------------------------------------------------------------
  - Los servicios worker y beat SIGUEN SIN EXISTIR en Railway: crearlos
    requiere acceso al panel, que no es ejecutable desde este entorno. Todo
    el código necesario ya está corregido y verificado.
  - HOY, en producción, no se recalcula el SLA ni se envían notificaciones al
    cambiar un ticket, ni se disparan los triggers de deadline, ni el backup
    diario, ni el reporte diario de entregas. Motivo: no hay worker ni beat,
    y los .delay() del servicio web están protegidos por try/except (ver
    6.3), así que el fallo es silencioso. No es una regresión de este lote:
    es el estado previo, que este lote deja preparado para resolverse
    creando los dos servicios.
  - No se puede verificar desde aquí el comportamiento real de los servicios
    worker/beat en Railway (requiere crear los servicios y leer sus logs).
  - El SECRET_KEY del servicio web se regenera en cada reinicio si no hay un
    volumen montado en /data (las sesiones abiertas se invalidan, sin brecha
    de seguridad). Sigue pendiente montar el volumen o definir SECRET_KEY en
    el panel.
  - Los permisos 600 del fichero de clave no son verificables en Windows
    (NTFS: chmod es no-op). En Linux (Railway) sí se aplican.
  - El PAT de GitHub filtrado sigue siendo válido para quien lo obtenga:
    debe rotarse. No se ha vuelto a imprimir ni a incrustar en ningún
    fichero.
  - 12 de las 38 rutas del README V1.001 no existen como ruta GET (6 de ellas
    tienen otro nombre: /roles-funciones, /vistas/calendario,
    /vistas/timeline). Corrección pendiente en un lote posterior.

6.7) Fuentes consultadas para los hechos de Railway
-------------------------------------------------------------------------------
  https://docs.railway.com/variables/reference   (lista exhaustiva de variables:
      NO incluye RAILWAY_SERVICE_ROLE ni RAILWAY_SERVICE_TYPE; sí incluye
      RAILWAY_SERVICE_NAME)
  https://docs.railway.com/config-as-code         ("Configuration defined in
      code will always override values from the dashboard"; deprecado; los
      servicios nuevos no pueden optar; corte el 2026-12-01)
  https://docs.railway.com/guides/cron-workers-queues  (los workers son
      servicios siempre activos; el Cron Job exige que el proceso termine)
  https://docs.railway.com/deployments/healthchecks  (el healthcheck solo se
      usa al desplegar; un worker sin HTTP no puede servir /health)
  https://docs.railway.com/deployments/start-command  (Railpack: el start
      command se ejecuta en un shell, admite variables de entorno)

--------------------------------------------------------------------------------
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
--------------------------------------------------------------------------------

7.1) Qué ocurre al hacer push
-------------------------------------------------------------------------------
  Railway está conectado al repositorio por GitHub: el push a main dispara
  un deployment nuevo del servicio web. Ese redeploy es automatico y no
  requiere accion manual. El unico cambio efectivo para la web es que el
  broker de Celery pasa a derivarse de REDIS_URL (antes apuntaba a
  localhost y fallaba en silencio).

7.2) Crear el servicio worker (pasos exactos en el panel)
-------------------------------------------------------------------------------
  1) Proyecto Bitacora-GRM_v2 -> entorno production -> "+ New" -> "GitHub
     Repo" -> moisesarancibiasanchez-cpu/Bitacora-GRM_v2 -> Deploy.
  2) Renombrar el servicio a "worker" (Settings -> General -> Service name).
  3) Settings -> Variables -> New Variable:
         PROC_TYPE=worker
  4) Adjuntar las bases de datos: botón "Attach" del panel del proyecto o
     variables de referencia:
         DATABASE_URL=${{Postgres.DATABASE_URL}}
         REDIS_URL=${{Redis.REDIS_URL}}
  5) Copiar el resto de variables del servicio web (SECRET_KEY, DEBUG,
     USE_SQLITE, PUBLIC_BASE_URL, CORS_ORIGINS) o definirlas como Shared
     Variables del proyecto.
  6) Settings -> Deploy -> Start Command: bash start.sh
  7) Settings -> Deploy -> Healthcheck Path: VACIO (el worker no sirve HTTP)
  8) Variables -> Deploy (aplicar los staged changes).
  9) Verificar los logs: debe aparecer "rol=worker" y "celery ready".

7.3) Crear el servicio beat (pasos exactos en el panel)
-------------------------------------------------------------------------------
  Igual que el worker, con dos diferencias:
     - Service name: "beat"
     - Variable: PROC_TYPE=beat
     - NO configurar "Cron Schedule" (ver 4.5)
  Verificar los logs: debe aparecer "rol=beat" y "celery beat starting".

7.4) Reiniciar worker o beat una vez creados
-------------------------------------------------------------------------------
  Panel: servicio -> Deployments -> deployment ACTIVE -> menu de tres
  puntos -> Restart.
  CLI:   railway redeploy --service worker --environment production
  Ojo: si lo que se cambio fue una variable, hay que pulsar Deploy en los
  staged changes; Restart solo no aplica variables nuevas.

7.5) Rollback
-------------------------------------------------------------------------------
  - Del cambio de codigo (415a8fa):
        git revert 415a8fa
        git push origin main
    (revert, no reset: no se reescribe historia ni se fuerza el remoto)
  - Efecto del rollback: los servicios worker/beat volverian al fallo
    anterior (arrancarian gunicorn y publicarian contra localhost). La web
    NO se ve afectada: volveria a encolar tareas contra el broker por defecto.
    Por eso el rollback solo tiene sentido si se retiran del panel los
    servicios worker y beat.
  - Si solo se han creado servicios nuevos en el panel y no se quiere el
    cambio de codigo: basta con eliminar esos dos servicios del proyecto
    (no afecta al web, a Postgres ni a Redis).

7.6) Acciones de seguridad pendientes (requieren al propietario de la cuenta)
-------------------------------------------------------------------------------
  - Rotar el PAT de GitHub (el filtrado sigue siendo valido hasta su
    expiracion).
  - Definir SECRET_KEY y PUBLIC_BASE_URL de forma explicita en el panel.
  - Montar un volumen en /data en el servicio web para que la SECRET_KEY sea
    estable entre reinicios.
  - Definir DEBUG=false y USE_SQLITE=false como variables del panel (o
    Shared Variables) antes del 2026-12-01, por la deprecacion de Config as
    Code (ver 4.6).

================================================================================
FIN DEL DOCUMENTO
================================================================================
