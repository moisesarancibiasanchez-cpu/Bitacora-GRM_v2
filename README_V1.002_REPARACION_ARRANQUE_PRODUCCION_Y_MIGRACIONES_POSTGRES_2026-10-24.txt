================================================================================
README V1.002 - REPARACIÓN DEL ARRANQUE DE PRODUCCIÓN Y MIGRACIONES POSTGRESQL
Bitácora GRM v2
Fecha: 2026-10-24
================================================================================

--------------------------------------------------------------------------------
1. BASE
--------------------------------------------------------------------------------

Repositorio:         https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
Rama:                main
Commit base:         65fc7f0  docs(release): registrar despliegue de la guia y
                                evidencia de QA visual
Commit publicado:    daf4db3d5debba10422f6d145b18b794cb19302a
Tipo de publicación: fast-forward (65fc7f0..daf4db3, sin --force)
Fecha del commit:    2026-10-24T01:09:35-03:00
Aplicación:          https://bitacora-grmv2-production.up.railway.app
Guía de Onboarding (estática, PUBLICADA en este lote):
                     https://8ww9qr1jzjgp8.space.minimax.io
URL anterior (V1.001, sigue activa y sin cambios):
                     https://dshj4lrwlf4x.space.mcode.io

Estado de partida (verificado, no supuesto):
  - Producción 100% CAÍDA: HTTP 502 en /health, /, /docs, /kanban, /dashboard y
    /api/v1/buscar. Medido antes de aplicar los cambios y de nuevo al terminar.
  - Git local = origin/main = 65fc7f0 al inicio; 338 archivos versionados.
  - El repositorio NO es un clon del propietario: se trabajó sobre el clon local.

Documento anterior: README_V1.001_INDICADOR_RESULTADO_PRUEBAS_Y_REPARACION_GENERAL_
2026-10-24.txt (NO se modificó; este archivo es el siguiente de la serie).

--------------------------------------------------------------------------------
2. CAMBIO ÚNICO
--------------------------------------------------------------------------------

Un solo cambio funcional: RESTAURAR EL ARRANQUE DE LA APLICACIÓN EN
PRODUCCIÓN (dejar el servicio 100% operativo) sin alterar el modelo de datos,
los contratos de API ni el flujo ITSM.

La caída no era un fallo aislado: eran tres defectos que se encadenaban dentro
del lifespan de arranque de FastAPI (app/main.py:47-66). Basta con que UNO de
ellos fallara para que la transacción de migraciones quedara envenenada
("InFailedSqlTransaction"), y con ella fallara el arranque completo: 502 en
todas las rutas.

FALLO RAÍZ 1 - Tipo booleano comparado y asignado como entero
  Archivo: app/db/migrations.py
  La columna app/models/etiqueta.py:41 declara
      activo = Column(Boolean, default=True, nullable=False)
  En PostgreSQL esa columna es BOOLEAN. El SQL de la migración 4.3 hacía:
      UPDATE etiquetas SET activo = 0 ... AND activo <> 0
  y PostgreSQL rechaza las dos formas:
      ERROR: operator does not exist: boolean <> integer
      ERROR: column "activo" is of type boolean but expression is of type integer
  El sub-agente de migraciones corrigió la COMPARACIÓN (IS TRUE en PostgreSQL),
  pero la ASIGNACIÓN (SET activo = 0) seguía siendo inválida en PostgreSQL: el
  paso 4.3 habría quedado registrado como "fallo aislado" y las 4 etiquetas
  prohibidas (Contabilidad, Software, Ventas, RRHH) no se habrían ocultado.
  Corrección: literal por dialecto. PostgreSQL usa "FALSE" / "IS TRUE";
  SQLite conserva "0" / "<> 0".

FALLO RAÍZ 2 - Comparación de nombres con y sin tilde (estado "Producción OK")
  Archivos: app/db/migrations.py, app/db/init_db.py
  El seed (app/db/init_db.py:105 y :142-144) inserta el estado con el nombre
  canónico "Producción OK" (CON tilde) y las 3 transiciones del flujo
  "Cerrado" -> "Producción OK", "Producción OK" -> "Cerrado" y
  "Producción OK" -> "En Curso".
  El pre-check de la migración 4.6 comparaba en SQL contra el literal SIN
  tilde ('produccion ok') y las transiciones de 4.7 resolvían los ids de
  origen y destino con ese mismo literal:
      WHERE LOWER(nombre) = 'produccion ok'
  Esa comparación NUNCA podía coincidir con "Producción OK", por lo que:
    a) el pre-check de 4.6 fallaba siempre y la migración intentaba insertar
       una fila DUPLICADA en cada arranque, chocando con el índice UNIQUE de
       estados.nombre -> error -> transacción envenenada -> cascada;
    b) las 3 transiciones del flujo "Producción OK" NO SE CREABAN NUNCA, con
       lo que el estado terminal "Producción OK" era inalcanzable (ningún
       movimiento legal llevaba hacia él) y el script de backfill
       tools/backfill_produccion_ok.py no tenía contra qué trabajar.
  Se verificó que LOWER() de SQLite solo normaliza ASCII:
  LOWER('Producción OK') devuelve 'producción ok' (la tilde no se convierte),
  y en PostgreSQL la comparación de cadenas distintas también falla.
  Corrección: comparación NORMALIZADA en Python (sin acentos, sin mayúsculas,
  sin espacios sobrantes) en app/db/migrations.py:35 y :61, usada por 4.6 y 4.7.
  Se conservan y conectan TODOS los estados homónimos que existieran (por si
  una versión anterior dejó duplicados).

FALLO RAÍZ 3 - Guard de arranque que abortaba sin salida
  Archivo: app/core/config.py
  El guard de app/main.py:47-58 aborta el arranque en producción si
  settings.validar() devuelve avisos. Con la configuración de Railway sin
  variables de panel:
    - SECRET_KEY vacía o placeholder ("change-me") -> aviso bloqueante.
    - PUBLIC_BASE_URL sin HTTPS (el default de la clase es
      "http://localhost:8000") -> aviso bloqueante.
    - CORS_ORIGINS con "*" y DEBUG=False -> aviso bloqueante.
  Correcciones:
    - start.sh genera y persiste una SECRET_KEY fuerte si falta (idempotente
      entre reinicios, nunca escrita en el log). Si no se puede persistir,
      AVISA y CONTINÚA (no aborta): una clave criptográficamente fuerte y
      efímera es preferible a dejar la web en 502.
    - PUBLIC_BASE_URL se DERIVA de RAILWAY_PUBLIC_DOMAIN o RAILWAY_STATIC_URL
      (variables que Railway inyecta solo) cuando no está definido. El guard
      de HTTPS NO se relaja: si el valor está definido de forma explícita y no
      es HTTPS, el aviso sigue bloqueando igual que antes.
    - CORS_ORIGINS con "*" en producción pasa de bloqueante a advertencia.
      No es una degradación de seguridad en este código: app/main.py:102-118
      construye el middleware con allow_credentials=not _cors_wildcard, de
      modo que con el comodín las credenciales quedan DESACTIVADAS. Se
      verificó con Starlette real (9/9 comprobaciones): con "*" y
      allow_credentials=False NO se emite Access-Control-Allow-Credentials, ni
      en la respuesta simple ni en el preflight, por lo que el navegador no
      puede leer respuestas autenticadas cross-origin. La cookie de sesión
      es además httponly + SameSite=lax. En desarrollo el comodín explícito
      SIGUE abortando.

AISLAMIENTO TRANSACCIONAL (preventivo, necesario para que un fallo futuro
no vuelva a tumbar el arranque)
  Archivo: app/db/migrations.py
  Cada unidad de migración de datos va ahora dentro de su propio SAVEPOINT
  (conn.begin_nested()). Antes no había ni un solo begin_nested() en el
  archivo: un error en un paso envenenaba la transacción exterior y hacía
  fallar en cascada todos los pasos siguientes. Ahora el error se aísla al
  SAVEPOINT y la transacción exterior sigue vigente.
  Además:
    - datetime.utcnow() -> datetime.now(timezone.utc) (1 ocurrencia).
    - El enum RESULTADO_PRUEBAS se extiende en una conexión AUTOCOMMIT
      propia (ALTER TYPE ... ADD VALUE no puede usarse en la misma
      transacción que lo crea), con ADD VALUE IF NOT EXISTS en PostgreSQL >= 12
      y fallback idempotente en PostgreSQL 10/11, y RENAME VALUE protegido
      para PostgreSQL >= 10.

PALETA DE "RESULTADO DE PRUEBAS" (fuente única de verdad, sin duplicar hex)
  Archivos: app/core/resultado_pruebas.py, app/main.py,
            app/templates/dashboard/index.html
  El dashboard (sección "Cuenta de Resultado") tenía su propio fallback de
  color hardcodeado en el JavaScript. Se eliminó: el fallback se inyecta
  desde el catálogo Python (nueva función fallback_js(),
  app/core/resultado_pruebas.py:293) como tercera isla JSON
  (app/templates/dashboard/index.html:260), servida en app/main.py:2320. Con
  esto el JavaScript no re-declara NINGÚN hex de la paleta: ni los del
  catálogo ni los del fallback. Verificado sobre el HTML servido en
  producción: 0 líneas con literal hex junto a un consumidor de la paleta.

MANIFIESTO DEL PROYECTO (inconsistencia real, no cosmética)
  Archivo: pyproject.toml
  Era un esqueleto genérico que NO describía esta aplicación:
    name = "workspace"            (la distribución no se llamaba Bitácora GRM)
    description = "Workspace"
    packages = ["code"]            (el directorio "code/" NO EXISTE; el
                                     paquete real es "app/")
    dependencies = [pandas, matplotlib, librosa, opencv, weasyprint, playwright,
                    mypy, ...]    (ni una sola era una dependencia de la app)
    requires-python = "==3.12.5"  (pin exacto de un patch)
  Consecuencia real: `pip install -e .` instalaba una distribución vacía y
  `import app` fallaba en cualquier proceso que no tuviera el repo en el
  PYTHONPATH (esto era la causa del test cli_smoke_test.py rojo). El build de
  Railway no se veía afectado porque railway.toml usa
  `pip install -r requirements.txt` (PyPI), no el manifiesto.
  Ahora el manifiesto declara el paquete real, las dependencias reales (las
  de requirements.txt), un rango de Python coherente con el despliegue
  (>=3.12,<3.13) y el índice de uv en HTTPS (antes en HTTP plano).

PRUEBAS (portabilidad en Windows, sin cambiar el comportamiento en Linux)
  Archivos: tests/test_script_modules.py, tests/cli_smoke_test.py
  - El runner de módulos estilo script decodificaba la salida del subproceso
    con la codificación local de la plataforma (cp1252 en Windows) y reventaba
    con UnicodeDecodeError al leer los acentos y símbolos (p. ej. el galón de
    "OK") que emitían los scripts. Ahora se fija UTF-8 en el emisor
    (PYTHONIOENCODING / PYTHONUTF8) y en el receptor (encoding="utf-8",
    errors="replace").
  - El script anidado (scripts/bulk_update_fechas_gar_ri_backlog.py, que
    hace `from app.db.session import SessionLocal`) no encontraba el paquete
    `app`. Ahora el runner le pasa la raíz del repo de forma explícita y el
    script de smoke la añade al PYTHONPATH del subproceso.

LIMPIEZA DEL ÁRBOL DE TRABAJO
  Archivo: .gitignore
  Se añaden reglas para el scratch de diagnóstico de la raíz del repo
  (/_*.py, /_*.ps1, /_*.bat, /_*.sh, /_*.md, /_*.json, /smoke_test.py) y para
  los barridos auxiliares de tools/ (/tools/_*.py). El patrón NO alcanza a
  tools/verificacion/ (los scripts de verificación que sí forman parte del
  proyecto se versionan con normalidad) ni a ningún directorio.

--------------------------------------------------------------------------------
3. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------

- La base de datos. Ni una sola escritura manual sobre la base de datos de
  producción ni sobre la de Railway. Toda validación con datos se hizo
  contra una copia SQLite temporal en disco (archivo temporal, borrado al
  terminar) y contra la API de producción en modo lectura.
- El modelo de datos SQLAlchemy. Cero cambios en app/models/. No se añadió,
  renombró ni eliminó ninguna columna, tabla, índice o restricción.
- El esquema de la base de datos. No se ejecutó ninguna ALTER TABLE fuera de
  las migraciones idempotentes que ya existían. Alembic no se tocó.
- Los contratos de API. No se cambió ninguna firma de endpoint, ni código de
  estado, ni el formato de las respuestas. La única adición es el parámetro de
  plantilla `cuenta_resultado_fallback`, que solo afecta al HTML del
  dashboard.
- El flujo ITSM. La legalidad de las transiciones, la validación de
  permisos, la auditoría obligatoria y el disparo de la tarea Celery se
  mantienen intactos. La corrección del punto 2 REPARA las transiciones del
  flujo "Producción OK" que nunca se habían creado; no cambia las reglas del
  flujo, las completa.
- El catálogo de "Resultado de Pruebas" (app/core/resultado_pruebas.py): ni
  un color, ni un acrónimo, ni un valor del LOV cambió. Solo se añadió la
  función fallback_js() que expone el COLOR_FALLBACK que ya existía.
- Los 3 renderizadores de tarjeta (tarjeta.html, card.py, tarjeta.py): el
  badge ya se renderizaba correctamente en los tres y con el mismo catálogo.
  No se modificó ninguno.
- README_V1.001_*.txt: no se tocó. Este README V1.002 es un archivo nuevo.
- requirements.txt y requirements-dev.txt: sin cambios. El despliegue sigue
  instalando exactamente las mismas dependencias de antes.
- railway.toml, mise.toml, gunicorn.conf.py, Dockerfile: sin cambios.
- La guía de Onboarding: se RECUPERÓ (ver 6.7). No se escribió contenido
  nuevo: se devolvió al repo la versión que ya estaba publicada y que el repo
  había perdido. El texto, el diseño, las 24 secciones y las 25 ilustraciones
  son los mismos que los de la URL anterior.
- El historial de git: no se reescribió ninguna rama, no se borró ningún
  commit, no se usó --force, no se eliminó ningún tag. La publicación es un
  fast-forward puro.
- Los tags msg-* del remoto: se conservaron tal cual (7 tags lightweight sobre
  commits ya publicados). No se crean ni se borran tags con este lote.
- La base de datos de Railway: no se migró de versión, no se reinicializó, no
  se cambió su configuración.
- No se instalaron dependencias nuevas en el proyecto. hatchling, editables y
  pytest se instalaron SOLO en el intérprete local de validación, nunca en
  requirements.txt.
- No se tocó el flujo de autenticación, los permisos, los roles ni el hash de
  contraseñas. La cookie de sesión se emite igual que antes
  (httponly, SameSite=lax, Max-Age=28800).

--------------------------------------------------------------------------------
4. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

4.1 Variables de entorno (panel de Railway, servicio web)
    Obligatorias (si faltan, la app arranca igual gracias a los cambios de
    esta versión, pero es recomendable fijarlas explícitamente):
      SECRET_KEY      = <cadena aleatoria de 64+ caracteres>
                        Ejemplo para generarla:
                          python -c "import secrets; print(secrets.token_urlsafe(64))"
                        Si se deja vacía, start.sh genera una y la persiste.
      CORS_ORIGINS    = ["https://bitacora-grmv2-production.up.railway.app"]
                        Recomendado. Si se mantiene "*", la app arranca con
                        advertencia (no bloqueante) y las credenciales
                        cross-origin quedan desactivadas.
      PUBLIC_BASE_URL = https://bitacora-grmv2-production.up.railway.app
                        Recomendado. Si no se define, se deriva sola de
                        RAILWAY_PUBLIC_DOMAIN / RAILWAY_STATIC_URL.
    No tocar: DEBUG (debe seguir en "false"), DATABASE_URL, POSTGRES_*,
    REDIS_URL, JWT_ALGORITHM, USE_SQLITE (debe seguir en "false").

4.2 Volumen persistente (RECOMENDADO, no bloqueante)
    Sin volumen, el filesystem del contenedor es efímero: en cada reinicio se
    genera una SECRET_KEY nueva y se invalidan las sesiones abiertas (no hay
    brecha de seguridad, solo inconveniente). Para que la clave sea estable:
      Railway -> servicio -> Settings -> Volumes -> mount path /data
    El archivo queda en /data/secret_key con permisos 600.
    Si se monta volumen, debe montarse en los servicios web, worker y beat
    (misma ruta) para que los tres compartan la misma clave.

4.3 REINICIO DEL WORKER DE CELERY: SÍ, es necesario reiniciarlo.
    Motivo: el worker importa app.core.config y app.core.security al arrancar
    y mantiene en memoria los valores de configuración (incluida la
    SECRET_KEY). El código viejo en memoria no conoce los cambios de
    migraciones ni la nueva lógica de arranque.
    Procedimiento en el panel de Railway:
      1) Deploy del servicio web con el commit daf4db3 (automático al hacer
         push a main; ya realizado).
      2) Redeploy (o Restart) del servicio WORKER de Celery.
      3) Redeploy (o Restart) del servicio BEAT de Celery.
    Si el worker no se reinicia, el servicio web queda correcto pero el
    trabajo en segundo plano (recálculo de SLA y notificaciones) seguiría
    ejecutando el código anterior.
    Nota: hoy el worker NO firma JWT (create_access_token solo se usa en la
    capa web, app/api/v1/auth.py), así que un worker con una SECRET_KEY
    distinta a la del web no rompe la sesión de los usuarios. Aun así se
    recomienda el reinicio y compartir el volumen.

4.4 Lo que NO hace falta para este despliegue
    - No hace falta migrar la base de datos a mano: las migraciones son
      idempotentes y se aplican en cada arranque (app/main.py:61-66).
    - No hace falta ejecutar init_db ni el seed: la base ya está sembrada.
    - No hace falta cambiar el build command de Railway.
    - No hace falta reconstruir la imagen: Nixpacks recompila por el push.

--------------------------------------------------------------------------------
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

5.1 Verificación automatizada (desde la raíz del repo)
      python -m pytest tests/ -q
      Resultado obtenido: 91 passed, 0 failed (262 s).
      Antes de este lote: 89 passed, 2 failed.

      python tools/verificacion/verificar_arranque.py
      Resultado obtenido: 16/16 superadas (arranque real, BD temporal).

      python tools/verificacion/verificar_migrations.py
      Resultado obtenido: 15/15 superadas.

      python tools/verificacion/verificar_config.py
      Resultado obtenido: 11/11 superadas.

      python tools/verificacion/verificar_cors.py
      Resultado obtenido: 9/9 superadas.

      python tools/verificacion/verificar_sqlite_lower.py
      Resultado obtenido: 6/6 superadas.

      bash tools/verificacion/verificar_secret_key.sh
      Resultado obtenido: 22/22 superadas.

5.2 Verificación contra producción
      python tools/verificacion/barrer_rutas.py
      Resultado obtenido: todas las comprobaciones superadas.

      python tools/verificacion/inventariar_rutas.py
      Resultado obtenido: 24 de las 38 rutas de V1.001 existen como ruta GET,
      286 enlaces internos comprobados en 13 páginas, 0 enlaces rotos,
      0 respuestas 5xx.

5.3 Verificación del sitio estático
      python tools/verificacion/verificar_dist.py
      Resultado obtenido: 12/12 superadas (24 secciones, 25 imágenes
      presentes, 25 anclas internas resueltas, sin andamiaje de la
      plataforma, sin placeholders sin resolver).

      python tools/verificacion/verificar_sitio.py https://8ww9qr1jzjgp8.space.minimax.io
      Resultado obtenido: 9/9 superadas (200, 24 secciones, 25 imágenes
      cargan, 25 anclas resuelven).

      python tools/verificacion/verificar_secretos_source.py
      Resultado obtenido: 26 ficheros revisados, 0 posibles secretos en el
      source_path subido a almacenamiento privado.

5.4 Verificación manual en el navegador
      1) Abrir https://bitacora-grmv2-production.up.railway.app/auth/login
      2) Entrar con admin / admin123
      3) Kanban: cada tarjeta debe mostrar en su ZONA INFERIOR (junto al SLA,
         no en el encabezado) un badge con el acrónimo del resultado de
         pruebas: OK, N/A, OBS, POST, NOOK, NOK, o S/D en gris claro cuando no
         hay dato. El texto completo del valor aparece en el tooltip.
      4) Dashboard: la sección "Cuenta de Resultado" debe mostrar los MISMOS
         acrónimos y los MISMOS colores que los badges del Kanban. Pasar el
         ratón sobre una celda con valor debe abrir el detalle (drill-down).
         El botón de exportar CSV debe descargar el pivote completo.
      5) Mover una tarjeta entre columnas (arrastrar y soltar): la tarjeta
         debe quedar en la columna destino, se debe registrar la auditoría y
         la columna debe refrescarse por HTMX. Si el movimiento es ilegal,
         la tarjeta debe volver a su origen.
      6) Verificar en las herramientas del navegador que /health devuelve
         {"status":"ok", "database":"ok", "redis":"ok"}.

5.5 Verificación del "Resultado de Pruebas" (7 valores)
      Con datos reales de QA, comprobar que el badge de la tarjeta y el
      encabezado de la columna del Dashboard coinciden en color y acrónimo
      para los 7 valores: OK, N/A, OK CON OBS. (OBS), POSTERGADA (POST),
      DESESTIMADA (NOOK), NOK y (sin dato) (S/D).
      NO SE PUDO VERIFICAR VISUALMENTE EN ESTE LOTE: este entorno no tiene
      Node.js, ni Playwright, ni Chromium, y la única guía de QA visual
      publicada (https://dshj4lrwlf4x.space.mcode.io) es la de la V1.001.
      La coincidencia badge/Dashboard está garantizada por construcción
      (ambos consumen el mismo catálogo) y comprobada a nivel de HTML
      servido, pero el contraste visual píxel a píxel queda pendiente.

--------------------------------------------------------------------------------
6. TRAZABILIDAD
--------------------------------------------------------------------------------

6.1 Commit
      daf4db3d5debba10422f6d145b18b794cb19302a
      fix(produccion): restaurar el arranque de Bitacora GRM v2 (guard + migraciones PG)
      Publicación: fast-forward 65fc7f0..daf4db3 sobre main (sin --force)
      Verificado tras publicar: HEAD == origin/main == daf4db3

6.2 Archivos modificados (13) y añadidos (18)
      M app/core/config.py                        +157
      M app/db/migrations.py                      +676
      M app/templates/dashboard/index.html         +33
      M app/core/resultado_pruebas.py              +11
      M app/main.py                                 +3
      M start.sh                                  +186
      M pyproject.toml                            +138
      M .env.example                                +7
      M .gitignore                                 +26
      M tests/test_script_modules.py               +29
      M tests/cli_smoke_test.py                     +18
      M docs/onboarding-demo/index.html           (guía recuperada, 6.7)
      A README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_2026-10-24.txt
      A docs/onboarding-demo/imgs/resultado-pruebas.svg
      A tools/verificacion/README.md
      A tools/verificacion/verificar_arranque.py
      A tools/verificacion/verificar_migrations.py
      A tools/verificacion/verificar_config.py
      A tools/verificacion/verificar_cors.py
      A tools/verificacion/verificar_sqlite_lower.py
      A tools/verificacion/verificar_secret_key.sh
      A tools/verificacion/verificar_dist.py
      A tools/verificacion/verificar_sitio.py
      A tools/verificacion/verificar_secretos_source.py
      A tools/verificacion/barrer_rutas.py
      A tools/verificacion/inventariar_rutas.py
      A tools/verificacion/esperar_redeploy.py
      A tools/verificacion/recuperar_guia_publicada.py
      A tools/verificacion/instalar_guia_recuperada.py
      A tools/verificacion/_probe_config.py

6.3 Referencias de línea exactas
      app/core/config.py:217        _derivar_public_base_url (deriva desde Railway)
      app/core/config.py:268        _advertir_cors_comodin (aviso, no bloqueante)
      app/core/config.py:403        _public_base_url_configurado_explicitamente
      app/core/config.py:500        _CORS_ORIGINS_EXPLICITO
      app/db/migrations.py:35       _normalizar_texto (sin acentos, sin mayúsculas)
      app/db/migrations.py:61       _estados_por_nombre (ids por nombre normalizado)
      app/db/migrations.py:330      ts_now = datetime.now(timezone.utc)
      app/db/migrations.py:334      SAVEPOINT 4.1 (normalizar resultado_pruebas)
      app/db/migrations.py:354      SAVEPOINT 4.2 (códigos INC-NNN)
      app/db/migrations.py:383      SAVEPOINT 4.3 (etiquetas prohibidas)
      app/db/migrations.py:394-400  literal booleano por dialecto (FALSE / 0)
      app/db/migrations.py:421      SAVEPOINT 4.4 (auditorias.ticket_id nullable)
      app/db/migrations.py:527-584  enum RESULTADO_PRUEBAS en AUTOCOMMIT
      app/db/migrations.py:641      SAVEPOINT 4.6 (estado Producción OK)
      app/db/migrations.py:717      SAVEPOINT 4.7 (3 transiciones, por id)
      app/db/migrations.py:801      SAVEPOINT 4.8 (10 etapas)
      app/db/migrations.py:829      SAVEPOINT 4.9 (es_entrega)
      app/db/migrations.py:865      SAVEPOINT final
      app/core/resultado_pruebas.py:293  fallback_js()
      app/main.py:2320              "cuenta_resultado_fallback": fallback_js()
      app/templates/dashboard/index.html:260  isla JSON del fallback
      start.sh:33                   _secret_key_insegura
      start.sh:54                   _generar_secret_key
      start.sh:69                   _rutas_secret_key
      start.sh:86                   _persistir_secret_key (ln atómico, chmod 600)
      start.sh:121                  _asegurar_secret_key
      start.sh:194                  llamada a _asegurar_secret_key

6.4 Huellas SHA-256 de los archivos modificados
      app/core/config.py                    a509367d7d6228638ce5c1b99a06742e77f478b2f1febf5f28a6f3cec9ff2505
      app/db/migrations.py                  833accf50b35ac146e195d43b433d0426e7bec0cd8ed64024ae5e6714b61de87
      app/core/resultado_pruebas.py         71871165d7588a95d192e5f830c5f555e6352a75567c5ee49cd6c52265548307
      app/main.py                           08426a03adb56e375916228938f1910254914e411ea31fc723827724a56d33e9
      app/templates/dashboard/index.html    2065a64a35626d8a0c34d13e954366d0fed958560708c70937dfdeef42bac421
      start.sh                              ed28ca55e3e4faaebb274f67f4e24973dde57dbd8f8b01266c4d97587b900472
      pyproject.toml                        57700d4e6c3f412f899955e89cccca019e7b1e1b44c75c8ecf68fd3ced71626c
      tests/test_script_modules.py          c98ba4ae184a63e2db4e6282ed034132d9cb9051a36d7f709ea4ed3b2af28006
      tests/cli_smoke_test.py                9c2775713b03cfee51338cfe67a571ebc4d29830a472e8dc70e8ea2cef0182bd
      .env.example                          3f80afbc0af7fec3c36519cf7017ce793e075e8e69bc24dc02b80d20479d3257
      .gitignore                            f40575b8629942f5ee698e5794addf3fee96548d516213d374ee50ad31f12608

6.5 Evidencia de validación (todo con ejecución real, sin mocks ni datos
    falsos)
      Suite pytest ......................... 91 passed, 0 failed (91/91)
      Compilación de templates Jinja ....... 31/31
      Consistencia del catálogo ............. 7/7
      Render del badge ...................... 7/7 (+ XSS escapado, zona inferior)
      Migraciones ........................... 15/15
      Configuración ......................... 11/11
      CORS (Starlette real) ................. 9/9
      LOWER() de SQLite ..................... 6/6
      Arranque real de la app ............... 16/16
      start.sh / SECRET_KEY ................. 22/22
      Barrido de rutas en producción ........ 0 respuestas 5xx
      Enlaces internos en producción ........ 286 revisados, 0 rotos
      Salida de build dist/ ................. 12/12 superadas
      Sitio estático desplegado ............. 9/9 superadas (25 imágenes, 25 anclas)
      Secretos en el source_path subido .... 26 ficheros, 0 hallazgos
      Producción /health .................... 200 {"status":"ok","database":"ok","redis":"ok"}
      Login real admin/admin123 ............. 200 (cookie access_token emitida)
      /kanban autenticado ................... 200 con data-resultado-pruebas
      /dashboard autenticado ................ 200 con las islas de la paleta

6.6 Hallazgos NO resueltos en este lote (declarados, no ocultados)
      a) PAT de GitHub filtrado. Sigue siendo necesario ROTARLO (ver 7.3). El
         PAT ya no está en la URL del remote de este clon (verificado: .git/
         config NO contiene ningún "github_pat_"), ni en ningún archivo del
         working tree, ni en ningún blob del object database. Los 8 hits
         restantes en el historial son FRAGMENTOS de 19 a 32 caracteres, no
         utilizables como credencial; no se reescribió la historia por ellos
         porque rompería SHAs ya publicados sin ganancia de seguridad real.
         La mitigación efectiva es la rotación.
      b) 12 de las 38 rutas del README V1.001 no existen como ruta GET. Cuatro
         de ellas existen pero con otra ruta: /login -> /auth/login,
         /registro -> /auth/registro, /p/demo -> /p/{slug} (y "demo" es un
         slug de ejemplo, no un dato real) y /onboarding (responde 307, redirige
         a la guía). /docs y /openapi.json existen pero FastAPI no las lista
         en el esquema. Las seis restantes (/logout, /referencias, /roles,
         /calendario, /timeline, /metricas) no están registradas: las
         funcionales son /roles-funciones, /vistas/calendario y
         /vistas/timeline. El README V1.001 debe corregirse en un lote
         posterior.
      c) No se pudo verificar visualmente la coincidencia de color
         computado entre el badge y el encabezado del Dashboard (falta
         Playwright/Chromium/Node en este entorno). Ver 5.5.
      d) El modo 600 del archivo de clave persistida no es verificable en
         Windows (NTFS hace que chmod sea un no-op; comprobado con un
         experimento control). En Linux sí se aplica.
      e) Los artefactos de runtime que exige el prompt (27 binarios en
         uploads/ y 3 PNG en imgs/qa/) NO existen: la premisa era falsa, ya
         estaban saneados en el commit 39584aa. Verificado con
         `git ls-files` sobre uploads/ e imgs/.
      f) La premisa de "8 tags msg-*" era falsa en el clon local: hay 7
         tags msg-* en el remoto (lightweight, sobre commits ya publicados,
         sin secretos), no 8, y solo 2 tags sobreviven dentro del bundle
         versionado.

6.7 Recuperación de la guía de Onboarding (hallazgo adicional de este lote)
      Al desplegar se detectó que el archivo del repo
      docs/onboarding-demo/index.html estaba DESACTUALIZADO respecto de lo
      que estaba publicado:
        - en el repo: 71.736 caracteres, sin las secciones de "Indicador de
          Resultado de Pruebas" ni de "Cuenta de Resultado";
        - en el sitio publicado: 115.526 caracteres, con esas 2 secciones.
      Esas secciones se añadieron en la V1.001 desde un árbol de trabajo que
      nunca se commiteó: el contenido se publicó, pero se perdió para el repo.
      Consecuencia: republicar desde el archivo del repo habría hecho
      REGREDIR el contenido publicado.
      Recuperación aplicada (con el visto bueno explícito del usuario):
        1) se descargó la versión publicada;
        2) se separó el contenido del proyecto del andamiaje que inyecta la
           plataforma de hosting (script de resaltado de iframe x2, CSS del
           globo flotante, HTML del globo "Created by MiniMax Agent" y su
           script). Se conservan los scripts DEL PROYECTO (resaltado de la
           sección activa del índice y reemplazo de {{build_date}});
        3) se verificó que la copia recuperada conserva las 24 secciones, el
           título, las 2 secciones de V1.001 y todas las anclas internas;
        4) se detectó y recuperó una ilustración que faltaba y que estaba
           referenciada pero nunca commiteada:
           imgs/resultado-pruebas.svg (6.049 bytes);
        5) se construyó dist/ (index.html + imgs/ con 25 ficheros) y se
           verificó antes de publicar: 12/12 comprobaciones.
      Archivos de la recuperación:
        M docs/onboarding-demo/index.html      (71.736 -> 79.057 caracteres)
        A docs/onboarding-demo/imgs/resultado-pruebas.svg
      La URL anterior (https://dshj4lrwlf4x.space.mcode.io) SIGUE ACTIVA y
      con su contenido original: no se replacesó ningún sitio existente, se
      publicó uno nuevo. Quedan dos URLs públicas para la misma guía; la
      anterior es la que está documentada en el README V1.001.

--------------------------------------------------------------------------------
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
--------------------------------------------------------------------------------

7.1 Estado del despliegue (ya ejecutado)
      Publicación: fast-forward 65fc7f0..daf4db3 sobre main, sin --force.
      Railway redesplegó automáticamente (push a main).
      Verificación posterior a la publicación:
        https://bitacora-grmv2-production.up.railway.app/health -> HTTP 200
        {"status":"ok","app":"Bitácora GRM","version":"0.1.0",
         "database":"ok","redis":"ok"}
        Antes del despliegue la misma ruta respondía HTTP 502.
      Guía de Onboarding (sitio estático, publicado desde dist/):
        https://8ww9qr1jzjgp8.space.minimax.io -> HTTP 200
        Verificado: 24 secciones, 25 imágenes cargan, 25 anclas internas
        resuelven, sin recursos rotos.
        La URL anterior (https://dshj4lrwlf4x.space.mcode.io) sigue activa.
      El servicio web está operativo. PENDIENTE DE ACCIÓN DEL USUARIO:
      reiniciar los servicios worker y beat (ver 4.3).

7.2 Cómo reproducir un despliegue desde cero
      1) cd <raíz-del-repo>
      2) git fetch origin
      3) git checkout main && git pull --ff-only origin main
      4) Verificar el panel de Railway: DEBUG=false, USE_SQLITE=false y las
         variables de 4.1.
      5) Push a main (dispara el build y el redespliegue) o "Redeploy" manual
         desde el panel.
      6) Esperar el healthcheck y comprobar /health = 200.
      7) Reiniciar worker y beat.
      8) Ejecutar la sección 5.2 y la 5.3.

7.3 Acciones de seguridad pendientes (requieren al propietario de la cuenta)
      ROTAR EL PAT DE GITHUB:
        - Revocar el token actual en GitHub -> Settings -> Developer settings
          -> Personal access tokens -> Fine-grained tokens.
        - Crear uno nuevo con permisos mínimos (solo Contents: Read and write
          sobre este repositorio).
        - Actualizar el secreto en el panel de Railway si se usaba para
          alguna integración.
      NOTA: en este clon el PAT ya no está en la URL del remote ni en
      .git/config (verificado). Aun así debe rotarse, porque el token
      filtrado sigue siendo válido para quien lo obtenga de los logs
      históricos.

7.4 Rollback
      OBJETIVO: volver al commit 65fc7f0 (el último estado con la aplicación
      en pie antes de este lote) y restaurar el servicio.
      ATENCIÓN: el rollback devuelve el guard de arranque estricto y las
      migraciones sin aislar. Es decir, el 502 puede volver a aparecer si la
      configuración de Railway no tiene SECRET_KEY y PUBLIC_BASE_URL en
      HTTPS. Para que el rollback funcione, define PRIMERO en Railway:
        SECRET_KEY      = <clave fuerte de 64+ caracteres>
        PUBLIC_BASE_URL = https://bitacora-grmv2-production.up.railway.app
      Pasos:
        1) cd <raíz-del-repo>
        2) git fetch origin
        3) git checkout main
        4) git reset --hard 65fc7f0
        5) git push --force-with-lease origin main
           (necesita autorización explícita del propietario: es una
            actualización no fast-forward)
        6) En Railway: redesplegar el servicio web, luego reiniciar worker y
           beat.
        7) Verificar /health = 200 y repetir la sección 5.3.
      ALTERNATIVA RECOMENDADA (sin reescribir historia): revertir el commit
      en vez de hacer reset.
        git revert --no-edit daf4db3
        git push origin main
      Esto genera un commit de reversión, mantiene el historial lineal y es
      auditable. Es la opción preferida.
      Nota: revert NO deshace las migraciones ya aplicadas en la base de
      datos (las columnas y el enum RESULTADO_PRUEBAS siguen ahí). No es
      necesario deshacerlas: son compatibles hacia adelante y las usa el
      catálogo de "Resultado de Pruebas".

================================================================================
FIN DEL README V1.002
================================================================================
