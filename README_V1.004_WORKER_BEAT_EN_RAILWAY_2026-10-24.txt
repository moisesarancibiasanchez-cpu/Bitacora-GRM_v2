================================================================================
README V1.004 - DESPLIEGUE DE LOS SERVICIOS WORKER Y BEAT DE CELERY EN RAILWAY
Bitácora GRM v2
Fecha: 2026-10-24
================================================================================

Documentos anteriores de la serie (NO se modificaron):
  README_V1.001_INDICADOR_RESULTADO_PRUEBAS_Y_REPARACION_GENERAL_2026-10-24.txt
  README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_2026-10-24.txt
  README_V1.003_ROLES_WORKER_BEAT_CELERY_RAILWAY_2026-10-24.txt

Motivo de este incremento: el README V1.003 dejó preparado el código para que
los servicios worker y beat de Celery arrancaran el proceso correcto, pero
esos servicios NO EXISTÍAN en Railway. Este lote los crea, los configura, los
despliega y verifica el flujo completo en producción. Incluye, además, una
corrección de seguridad detectada durante el despliegue.

--------------------------------------------------------------------------------
1. BASE
--------------------------------------------------------------------------------

Repositorio:         https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
Rama:                main
Commit base:         c6de861  docs(release): README V1.003 con los roles worker/beat
                                de Celery en Railway
Commit funcional:    2b03aa7c94cbb0a4e0199ee2250f6c2d19772c62
                      fix(produccion): enmascarar la contraseña de la BD en los logs
                      y añadir el verificador de worker/beat en Railway
Tipo de publicación: fast-forward (sin --force)
Fecha:               2026-10-24

Aplicación:          https://bitacora-grmv2-production.up.railway.app
Guía de Onboarding:   https://8ww9qr1jzjgp8.space.minimax.io

Proyecto Railway:    BitacoraGRMv2  (id c0e1796f-cdcf-4e85-833d-25536dfa674c)
Entorno:             production    (id 13092a8d-36b3-420e-95d9-a1f5379ddb19)

Servicios del proyecto al terminar este lote:
  Postgres              22b35ec6-3034-4f3d-ab69-5e55c1a0a3b9   (preexistente)
  Redis                 3e1ff30b-9869-4e13-a57d-82a9150904dd   (preexistente)
  Bitacora-GRM_v2 (web) 775efae4-375f-4731-8027-680e78bd6a68   (preexistente, NO tocado)
  worker                51e22b0c-1f46-411f-b24a-a976107690f0   (NUEVO)
  beat                  1c16b13c-4533-40c9-b63e-43b00cb14041   (NUEVO)

Estado de partida (verificado, no supuesto):
  - El proyecto tenía 3 servicios: Postgres, Redis y el web. NO había worker
    ni beat (captura del panel del 2026-10-24 y consulta a la API).
  - Las tareas programadas estaban DORMIDAS: el servicio web encola
    recalcular_sla / notificar_cambio_estado / registrar_entrega_diaria /
    generar_reporte_diario / backup_database_diario, pero no había nadie que
    las consumiera. Los .delay() están protegidos por try/except
    (app/services/ticket_service.py:394-404, 414-424, 650-659), así que el
    fallo era silencioso: la aplicación respondía 200 y no avisaba de nada.

--------------------------------------------------------------------------------
2. CAMBIO ÚNICO
--------------------------------------------------------------------------------

Que LAS TAREAS PROGRAMADAS DE BITÁCORA GRM SE EJECUTEN EN PRODUCCIÓN, que
hasta ahora estaban dormidas por no existir el worker ni el beat.

Para lograrlo hubo que crear y configurar dos servicios nuevos, y de paso se
corrigió una fuga de credenciales detectada durante el despliegue.

2.1) Servicios nuevos creados, configurados y desplegados
-------------------------------------------------------------------------------
  Operados por la API GraphQL de Railway (ver 4.3), no a mano:

  worker (51e22b0c-1f46-411f-b24a-a976107690f0)
    - Start Command : bash start.sh
    - Healthcheck   : (vacío) - un worker no sirve HTTP; un /health haría
                      fallar el deployment y reiniciarlo en bucle
    - Variables    : 22 (copia de las del web + PROC_TYPE=worker), con
                     DATABASE_URL y REDIS_URL como referencias
                     ${{Postgres.DATABASE_URL}} / ${{Redis.REDIS_URL}}
                     y AUTO_INIT_DB=false (solo el web aplica migraciones)
    - Despliegue   : c357af79-4713-44e6-87f3-165073c40e23  -> SUCCESS

  beat (1c16b13c-4533-40c9-b63e-43b00cb14041)
    - Start Command : bash start.sh
    - Healthcheck   : (vacío)
    - Variables    : 22 (idénticas a las del worker, con PROC_TYPE=beat)
    - Despliegue   : 14bc293d-548d-4e2a-8b03-4b9453fe696a  -> SUCCESS
                     (tras el incidente descrito en 6.3.1)

  El web NO se tocó: ni variables, ni start command, ni healthcheck, ni
  reinicio. Sigue con su despliegue d8408b2a-5a09-45bb-bb74-6d76fadae8da.

2.2) Corrección de seguridad: la contraseña de la BD en los logs
-------------------------------------------------------------------------------
  Archivo:  app/db/init_db.py:50  y  app/core/config.py (nuevo método)
  Antes:
      print(f"Inicializando BD: {settings.get_database_url()}")
  Problema:
      En producción el log de arranque del web imprimía la URL completa de
      PostgreSQL, CON LA CONTRASEÑA:
        "Inicializando BD: postgresql://postgres:ZoMm...@postgres.railway.internal
         :5432/railway"
      Cualquiera con acceso a los logs del despliegue podía leer la
      credencial de la base de datos de producción.
  Después:
      print(f"Inicializando BD: {settings.get_database_url_enmascarada()}")
      -> "Inicializando BD: postgresql://postgres:***@postgres.railway.internal
         :5432/railway"
      El método nuevo conserva esquema, usuario, host, puerto y base de
      datos, y sustituye la contraseña por "***". La URL real que se usa
      para conectar NO cambia.

--------------------------------------------------------------------------------
3. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------

- El servicio web: ni una variable, ni un cambio de start command, ni de
  healthcheck, ni un reinicio manual. Sólo lo redesplegó automáticamente
  Railway al recibir el push de este lote (despliegue 553f6ec2).
- La base de datos: 0 escrituras de esquema. En el arranque del web las
  migracionesapplied=0 skipped=25 indexes=21 errors=0 data_migrated=2
  (idempotentes, sin cambios). El worker y el beat NO ejecutan migraciones
  (AUTO_INIT_DB=false en ellos).
- El modelo de datos, las migraciones (app/db/migrations.py NO se tocó en este
  lote), los contratos de API, las plantillas y la lógica de negocio.
- El catálogo SSOT de resultado de pruebas y los tres renderizadores del badge.
- El calendario de Celery (app/core/celery_app.py NO se modificó): las 7
  tareas programadas siguen igual.
- El flujo de sesión/JWT: la SECRET_KEY se sigue gestionando en start.sh.
- La documentación previa de la serie y la guía de Onboarding publicada.
- Los 18 verificadores previos de tools/verificacion/: intactos. Se añadió
  uno nuevo (19 en total).

--------------------------------------------------------------------------------
4. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

4.1) DICTAMEN: NO QUEDA NADA PENDIENTE DE DESPLIEGAR
-------------------------------------------------------------------------------
  El worker y el beat están creados, configurados, desplegados y verificados
  en el entorno production. No hace falta ninguna acción en el panel para
  que funcione el pipeline de tareas.

4.2) ACCIONES DEL PROPIETARIO (requieren la cuenta de Railway)
-------------------------------------------------------------------------------
  a) REVOCAR EL TOKEN DE PROYECTO usado en este lote.
     Se creó hoy (2026-10-24T19:55:16Z) en Project Settings > Tokens, con
     nombre "Bitacora-GRM" (id 9b5069e8-7035-47b1-9ba0-cc809c17cf66), y da
     acceso a TODO el proyecto. Se usó desde la API, en memoria, sin
     escribirse en el repositorio ni en la URL del remoto. Revócalo en la
     pestaña Tokens.
  b) DEFINIR UNA SECRET_KEY REAL en el servicio web. La que hay en el panel
     es un placeholder del repositorio (contiene "change-me"). start.sh lo
     detecta y genera una clave aleatoria de 64 caracteres en cada arranque
     ("[start.sh] SECRET_KEY generado (len=64) y persistido en /data/secret_key"),
     de modo que el servicio arranca correctamente pero CADA despliegue
     invalida las sesiones abiertas. Dos opciones:
       - montar un volumen en /data en el servicio web (la clave se persiste),
       - o definir SECRET_KEY en el panel con un valor aleatorio fuerte
         (openssl rand -hex 32) y quitar el volumen.
  c) DEFINIR DEBUG=false y USE_SQLITE=false como variables del panel (o como
     Shared Variables del proyecto) antes del 2026-12-01: ese día Railway
     deja de leer railway.toml (Config as Code está deprecado).
  d) REVISAR AUTO_INIT_DB=true en el servicio web: hace que cada despliegue
     ejecute init_database() completo (creación de tablas + datos semilla).
     Es idempotente, pero con el esquema ya aplicado es opcional; su
     apariencia es lo que permite que las URLs de la BD se imprimieran en
     los logs (ya corregido).

4.3) CÓMO SE OPERÓ RAILWAY (para futuras replicas)
-------------------------------------------------------------------------------
  La GraphQL de Railway (https://backboard.railway.com/graphql/v2) responde
  sin necesidad de la CLI. Puntos clave que costaron tiempo y conviene
  documentar:

  a) Los tokens de PROYECTO NO van en "Authorization: Bearer". La
     documentación oficial indica que los tokens de cuenta, workspace y OAuth
     usan esa cabecera, y que los de proyecto usan "Project-Access-Token".
     Con la cabecera equivocada la API responde "Not Authorized" a TODO,
     incluso con y sin token (comprobado: respuestas idénticas). Correcto:
         headers = {
             "Content-Type": "application/json",
             "User-Agent": "railway-cli/3.0",
             "Project-Access-Token": <token de proyecto>,
         }
  b) El User-Agent importa: sin un UA reconocible, Cloudflare responde
     HTTP 403 "error code: 1010" antes de llegar a la API.
  c) Mutaciones usadas: serviceCreate (input: projectId, environmentId, name,
     source{repo}), serviceInstanceUpdate (startCommand, healthcheckPath,
     source, restartPolicy*), variableUpsert (projectId, environmentId,
     serviceId, name, value, skipDeploys), serviceInstanceDeploy
     (latestCommit). serviceInstanceUpdate y variableUpsert devuelven Boolean,
     no un objeto: no admiten selection set.
  d) Consultas útiles: project(id){ environments{edges{node}} services{...} },
     serviceInstance(serviceId, environmentId), deploymentLogs(deploymentId,
     limit){ message timestamp severity }, variablesForServiceDeployment(...).
  e) Las conexiones del esquema son "edges { node { ... } }", no listas
     planas: project { environments { id name } } es un error de validación.

4.4) LO QUE NO HIZO FALTA
-------------------------------------------------------------------------------
  - No hubo que tocar el servicio web, ni redeploy manual, ni migraciones.
  - No hubo que reconstruir la imagen ni tocar requirements.txt.
  - No hubo que montar volumen en worker ni beat (no emiten sesiones).
  - No hubo que usar "Cron Schedule" de Railway para el beat.

--------------------------------------------------------------------------------
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

5.1) Verificación automatizada del estado en Railway (nuevo)
-------------------------------------------------------------------------------
  Requiere un token de proyecto en un archivo (nunca se imprime):
      set RAILWAY_TOKEN_FILE=%TEMP%\railway_token.txt
      python tools/verificacion/verificar_railway_worker_beat.py
  Comprueba 24 puntos: existencia de los servicios, start command, ausencia
  de healthcheck, estado SUCCESS del despliegue, resolución del rol desde
  PROC_TYPE, conexión a PostgreSQL, broker en la base 1 y backend en la base
  2 de Redis, catálogo de tareas registrado y calendario de beat en ruta
  escribible.

5.2) Verificación en los logs del panel
-------------------------------------------------------------------------------
  Service -> worker -> Deployments -> deployment ACTIVE -> View logs. Debe
  aparecer:
      [start.sh] Rol detectado desde PROC_TYPE='worker' -> worker
      [start.sh] Iniciando Bitácora GRM (rol=worker)
      [start.sh]   -> postgres.railway.internal:5432 OK
      .> transport:   redis://default:***@redis.railway.internal:6379/1
      .> results:     redis://default:***@redis.railway.internal:6379/2
      celery@<host> ready.
  Y en el beat:
      [start.sh] Rol detectado desde PROC_TYPE='beat' -> beat
      celery beat v5.4.0 (opalescent) is starting.
      . scheduler -> celery.beat.PersistentScheduler
      . db -> /tmp/celerybeat-schedule

5.3) Verificación del flujo extremo a extremo (la que confirma que todo sirve)
-------------------------------------------------------------------------------
  Cada 5 minutos el beat encola "recalcular-sla-cada-5-min". En el log del
  worker debe aparecer:
      Task app.tasks.sla_tasks.recalcular_sla_masivo[...] received
      Task app.tasks.sla_tasks.recalcular_sla_masivo[...] succeeded in 0.38s:
          {'ok': True, 'procesados': 39, ...}
  y en el log del beat:
      Scheduler: Sending due task recalcular-sla-cada-5-min
          (app.tasks.sla_tasks.recalcular_sla_masivo)

5.4) Reiniciar el worker o el beat
-------------------------------------------------------------------------------
  Panel -> servicio -> Deployments -> deployment ACTIVE -> menu de tres
  puntos -> Restart. Equivalente por API: mutation deploymentRestart(id:).
  Ojo: si lo que se cambió fue una variable, hay que aplicar los staged
  changes (Deploy); un Restart no aplica variables nuevas.

5.5) Regresión de la web
-------------------------------------------------------------------------------
      python tools/verificacion/barrer_rutas.py
  Resultado esperado: 24x200, 2x307, 10x404 conocidos, 0x5xx.

--------------------------------------------------------------------------------
6. TRAZABILIDAD
--------------------------------------------------------------------------------

6.1) Commits
-------------------------------------------------------------------------------
  2b03aa7c94cbb0a4e0199ee2250f6c2d19772c62  fix(produccion): enmascarar la contraseña de la BD en los logs y
            añadir el verificador de worker/beat en Railway
  (y este README en el commit de documentación, fast-forward sobre el anterior)

6.2) Archivos modificados (2) y añadidos (1)
-------------------------------------------------------------------------------
  Modificados:
    app/core/config.py                          (+26)  get_database_url_enmascarada()
    app/db/init_db.py                           (+3/-1)  usa la URL enmascarada
  Añadido:
    tools/verificacion/verificar_railway_worker_beat.py   (nuevo, 24 comprobaciones)


6.2.1) Huellas SHA-256 de los archivos publicados
-------------------------------------------------------------------------------
  3827d51d973c186686f876a26b870690ace9700f5f8ae43ad0e6e00392097977  app/core/config.py
  0d7db3ce6ab7c82978e021b28581572cc465de961291cc06f92d256a3b66742e  app/db/init_db.py
  168e679e8c4843f97f5854061da7ed79c27dc13feff8f49448bf46a190247fe6  tools/verificacion/verificar_railway_worker_beat.py
6.3) Evidencia: logs reales de producción
-------------------------------------------------------------------------------
  worker (despliegue c357af79, SUCCESS):
    [start.sh] SECRET_KEY generado (len=64) y persistido en /data/secret_key
    [start.sh] Rol detectado desde PROC_TYPE='worker' -> worker
    [start.sh] Iniciando Bitácora GRM (rol=worker)
    [start.sh] Esperando a la base de datos PostgreSQL...
    [start.sh]   -> postgres.railway.internal:5432 OK
    [start.sh] Lanzando celery worker...
    .> transport:   redis://default:***@redis.railway.internal:6379/1
    .> results:     redis://default:***@redis.railway.internal:6379/2
    .> concurrency: 2 (prefork)
    [tasks] . app.tasks.sla_tasks.recalcular_sla_masivo
            . app.tasks.notification_tasks.notificar_sla_proximo_vencer
            . app.tasks.backup_tasks.backup_database_diario
            . app.tasks.entregas.generar_reporte_diario
            ... 12 tareas en total
    Connected to redis://default:***@redis.railway.internal:6379/1
    celery@618587578f5f ready.

  beat (despliegue 14bc293d, SUCCESS):
    [start.sh] Rol detectado desde PROC_TYPE='beat' -> beat
    [start.sh] Lanzando celery beat...
    celery beat v5.4.0 (opalescent) is starting.
      . broker -> redis://default:***@redis.railway.internal:6379/1
      . scheduler -> celery.beat.PersistentScheduler
      . db -> /tmp/celerybeat-schedule

  Flujo extremo a extremo (2026-10-24 20:15:00):
    beat:  Scheduler: Sending due task recalcular-sla-cada-5-min
    beat:  Scheduler: Sending due task notificar-sla-proximo
    worker: Task app.tasks.sla_tasks.recalcular_sla_masivo[...] received
    worker: Task ... succeeded in 0.38774017058312893s:
            {'ok': True, 'procesados': 39, ...}
    worker: Task app.tasks.notification_tasks.notificar_sla_proximo_vencer[...]
            received
    worker: Task ... succeeded in 0.1858279574662447s: {'ok': True, 'pr...}

  web (despliegue 553f6ec2, SUCCESS): redeploy automático por el push (sin
  cambios manuales de configuración en el servicio web):
    [start.sh] SECRET_KEY generado (len=64) y persistido en /data/secret_key
    [start.sh] AVISO: no se pudo determinar el rol; se asume 'web'.
    [start.sh] Verificando/Aplicando migraciones...
    [migrations] Resultado: applied=0 skipped=25 indexes=21 errors=0
                 data_migrated=2
    [start.sh] Lanzando gunicorn (web)...
    [INFO] Starting gunicorn 23.0.0 / Listening at: http://0.0.0.0:8080 (1)
    Inicializando BD: postgresql://postgres:***@postgres.railway.internal:5432/railway
      (tras el fix de este lote: la URL va enmascarada; antes mostraba la
       contraseña completa)

6.3.1) Incidente: un despliegue puede quedarse en DEPLOYING sin arrancar
-------------------------------------------------------------------------------
  Al redesplegar los tres servicios con el commit del fix, el despliegue del
  beat (78faf027) se quedó 18 minutos en estado DEPLOYING con CERO líneas de
  log. Diagnóstico: el despliegue ANTERIOR del beat (ee86d872) seguía en
  marcha y enviando tareas con normalidad (Scheduler: Sending due task a las
  20:15, 20:20, 20:25 y 20:30), es decir, Railway conserva el contenedor
  activo mientras el nuevo no arranca: NO era una caída de servicio.

  Resolución (por API):
    1) deploymentCancel(id: "78faf027-...") -> True. Tras la cancelación, el
       latestDeployment vuelve al despliegue SUCCESS anterior y el beat siguió
       encolando tareas.
    2) serviceInstanceRedeploy(environmentId, serviceId) -> nuevo despliegue
       14bc293d: BUILDING -> DEPLOYING -> SUCCESS en ~3 minutos, arrancando
       con rol=beat y /tmp/celerybeat-schedule.

  Lección operativa: si un despliegue se queda en DEPLOYING sin logs, el
  servicio anterior suele seguir sirviendo; comprobar los logs del
  despliegue ANTERIOR antes de asumir una caída, y usar deploymentCancel +
  serviceInstanceRedeploy para desbloquear.

6.4) Comprobaciones ejecutadas
-------------------------------------------------------------------------------
  tools/verificacion/verificar_railway_worker_beat.py   24/24 OK
      (ejecutado sobre los despliegues finales c357af79 / 14bc293d)
  Enmascarado de la URL de BD                             9/9 OK
  pytest tests/ -q --tb=line                              91 passed, 0 failed
  Barrido de rutas contra producción                       0x5xx, todas OK
  /health                                                  200 {"status":"ok",
      "database":"ok","redis":"ok"}
  Log de arranque del web tras el fix                     "Inicializando BD:
      postgresql://postgres:***@postgres.railway.internal:5432/railway"
      y ninguna linea del log con una contraseña real

6.5) Hallazgos NO resueltos (declarados, no ocultados)
-------------------------------------------------------------------------------
  - La SECRET_KEY del web sigue siendo un placeholder en el panel; start.sh
    la sustituye por una aleatoria en cada arranque (ver 4.2b). Hasta que se
    defina una clave fija o se monte el volumen, cada despliegue del web
    invalida las sesiones abiertas. No es una brecha (la clave efectiva es
    aleatoria), pero es una molestia operativa.
  - El token de proyecto usado en este lote sigue vigente hasta que se
    revoque (ver 4.2a).
  - El servicio web tiene AUTO_INIT_DB=true: cada despliegue vuelve a ejecutar
    init_database() completo. Es idempotente, pero innecesario con el
    esquema ya aplicado (ver 4.2d).
  - Las transiciones 'cerrado'→'produccion ok', 'produccion ok'→'cerrado' y
    'produccion ok'→'en curso' NO se insertan en producción (WARNING en los
    logs de migraciones): los estados canónicos de esas transiciones no
    existen en esta base de datos, que usa otros nombres. Es el comportamiento
    esperado y ya documentado en el README V1.002: el efecto neto de las
    migraciones sobre la base de producción es nulo.
  - Los permisos 600 del fichero de clave no son verificables en Windows
    (NTFS: chmod es no-op); en Linux sí se aplican.
  - 12 de las 36 rutas del barrido no existen como GET: 6 tienen otro nombre
    real (/login -> /auth/login, /registro -> /auth/registro, /referencias ->
    /api/v1/referencias/tipos, /roles -> /roles-funciones, /calendario ->
    /vistas/calendario, /timeline -> /vistas/timeline), /logout no existe y
    /p/demo es un tablero público sin datos. El README V1.001 dice "38 rutas"
    cuando la lista tiene 36. Corrección pendiente en un lote posterior.
  - El PAT de GitHub filtrado sigue siendo válido para quien lo obtenga:
    debe rotarse.

6.6) Fuentes consultadas
-------------------------------------------------------------------------------
  https://docs.railway.com/variables/reference          (variables del sistema)
  https://docs.railway.com/reference/api-authentication (cabecera
      Project-Access-Token para tokens de proyecto)
  https://docs.railway.com/config-as-code                (deprecación y corte
      del 2026-12-01; los servicios nuevos no optan a Config as Code)
  https://docs.railway.com/guides/cron-workers-queues    (workers = servicios
      siempre activos; el Cron Job exige que el proceso termine)
  https://docs.railway.com/deployments/healthchecks       (el healthcheck sólo
      se usa al desplegar; un worker sin HTTP no puede servir /health)

--------------------------------------------------------------------------------
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
--------------------------------------------------------------------------------

7.1) Estado actual
-------------------------------------------------------------------------------
  worker y beat están desplegados y verificados. El pipeline de tareas está
  operativo. El web no se ha tocado.

7.2) Reinicio rutinario
-------------------------------------------------------------------------------
  Panel -> servicio -> Deployments -> deployment ACTIVE -> ⋮ -> Restart.
  API: mutation deploymentRestart(id: "<deploymentId>").
  Railway reinicia el contenedor con la misma imagen y la misma configuración.

7.3) Recrear un servicio desde cero (si se borra por error)
-------------------------------------------------------------------------------
  Opción A (API, la usada en este lote):
    1) serviceCreate(input:{projectId, environmentId:"13092a8d-...",
       name:"worker", source:{repo:"moisesarancibiasanchez-cpu/Bitacora-GRM_v2"}})
    2) serviceInstanceUpdate(environmentId, serviceId,
       input:{startCommand:"bash start.sh", source:{repo:...},
       healthcheckPath:null, restartPolicyType:"ON_FAILURE",
       restartPolicyMaxRetries:5})
    3) variableUpsert por cada variable (copia del web) + PROC_TYPE
    4) serviceInstanceDeploy(serviceId, environmentId, latestCommit:true)
  Opción B (panel): "+ New" -> GitHub Repo -> mismo repo -> Start Command
    "bash start.sh" -> variable PROC_TYPE=worker|beat -> Attach de Postgres y
    Redis -> Healthcheck Path vacío -> Deploy.

7.4) Rollback
-------------------------------------------------------------------------------
  - Si el pipeline de tareas MOLESTA y se quiere volver al estado anterior:
    borrar los servicios worker y beat del panel (o por API). El web, sus
    variables y sus despliegues no se ven afectados; las tareas se volverían
    a encolar sin consumidor, que es exactamente el estado previo a este
    lote. No hay rollback de código que hacer: el único cambio de código de
    este lote es el enmascarado de la URL de la BD en los logs.
  - Si el enmascarado molestara (no debería):
        git revert 2b03aa7c94cbb0a4e0199ee2250f6c2d19772c62
        git push origin main

7.5) Reglas de seguridad operativas
-------------------------------------------------------------------------------
  - Los tokens de proyecto de Railway se revocan en Project Settings >
    Tokens. Generar uno nuevo para cada operación automatizada.
  - Un token de proyecto da acceso a TODO el proyecto: usarlo solo el tiempo
    necesario y revocarlo después.
  - No imprimir tokens ni escribirlos en ficheros del repositorio.

================================================================================
FIN DEL DOCUMENTO
================================================================================
