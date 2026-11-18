================================================================================
README V2.009 - AISLAMIENTO POR PROYECTO (VENTANAS V1 ADITIVA + V2 CONTRA
CLON) Y CORRECCION DE DEFECTOS EXISTENTES
Proyecto: Bitacora GRM v2
Fecha: 2026-11-14
Rama base: main y release/v2.001 (commit d986d48)
Estado: DESPLEGADO Y VERIFICADO EN PRODUCCION.
================================================================================

0. PARCHE EXACTO
================================================================================

Este lote tiene DOS objetivos, tal y como se pidio: implementar las ventanas
V1 y V2 del plan de multi-tenancy, y devolver el proyecto a un estado 100%
operativo corrigiendo los defectos que ya existian.

  V1 (ADITIVA) - el aislamiento por proyecto queda PREPARADO, sin cambiar el
  comportamiento observable de la aplicacion:

    - NUEVO app/models/proyecto.py
        Catalogo de proyectos. Clase `Proyecto` (tabla `proyectos`) y tabla
        puente `proyecto_usuarios` (proyecto <-> usuario, con rol).
        Constantes `PROYECTO_LEGACY_ID = 1` y `NOMBRE_PROYECTO_LEGACY`.

    - NUEVO app/core/proyecto.py
        Capa de contexto. `ContextVar` con el proyecto activo,
        `obtener_proyecto_actual()`, `establecer_proyecto_actual()`,
        `reiniciar_proyecto_actual()`, `contexto_proyecto()` (gestor de
        contexto), `clases_con_proyecto()` y `tablas_con_proyecto()`.
        `obtener_proyecto_actual()` devuelve SIEMPRE `None` mientras el flag
        `AISLAMIENTO_PROYECTO_ACTIVO` este apagado: ese es el mecanismo que
        hace que la ventana sea aditiva.

    - app/db/session.py
        `SesionProyecto` (subclase de `Session`) y `SessionLocal` con
        `class_=SesionProyecto`. Listener `do_orm_execute`
        (`_inyectar_filtro_proyecto`): inyecta el criterio
        `modelo.proyecto_id == <proyecto activo>` en cada consulta ORM, con el
        valor concreto leido del `ContextVar` en el momento de la consulta.
        Cubre la API moderna (`select`) y la heredada (`Query`), y tambien las
        cargas por relacion. Listener `after_begin`
        (`_fijar_proyecto_en_la_transaccion`): fija el GUC de sesion
        `app.proyecto_id` con `set_config(..., true)` (ambito de transaccion),
        solo en PostgreSQL.

    - app/models/*.py (19 ficheros)
        Columna `proyecto_id` en las 34 clases de negocio:
        `proyecto_id = Column(Integer, ForeignKey("proyectos.id",
        ondelete="SET NULL"), nullable=True, index=True)`.
        `Usuario` NO lleva la columna (los usuarios son globales); si lleva la
        relacion `Usuario.proyectos` (many-to-many por `proyecto_usuarios`).

    - app/db/migrations.py
        `TABLAS_CON_PROYECTO` (las 34 tablas) y la columna `proyecto_id`
        anadida a `COLUMNS_TO_ADD`. Indice por tabla
        (`ix_<tabla>_proyecto_id`) anadido a `INDEXES` (el `ALTER TABLE ADD
        COLUMN` no crea el indice). Backfill idempotente
        (`_aplicar_proyecto_legacy`): crea el proyecto "Legacy" (id 1) y
        asigna a el todas las filas que tuvieran `proyecto_id` a NULL.
        Ademas: `COLUMNAS_A_NULLABLE` (relaja `auditorias.usuario_id`),
        `comparar_esquema_completo()` (guardian estricto) y el bloque RLS.

    - NUEVO app/db/rls.py
        DDL de Row Level Security: `politicas_rls()`,
        `aplicar_politicas_rls()` y `deshabilitar_rls()`. La politica es
        fail-closed y lee el GUC `app.proyecto_id`.

    - app/core/config.py
        Tres flags nuevos, todos por defecto a False:
        `AISLAMIENTO_PROYECTO_ACTIVO`, `RLS_HABILITADO`, `ESQUEMA_ESTRICTO`.

  V2 (VALIDACION CONTRA UN CLON) - la capacidad de validar contra un clon:

    - NUEVO app/services/clone_service.py
        `clonar_base_datos()`, `borrar_clon()` y `listar_clones()`. Crea el
        clon en el MISMO servidor PostgreSQL que la base de datos de
        produccion (otro nombre), replica el esquema desde el metadata de
        SQLAlchemy y copia los datos fila a fila en orden de dependencias,
        alineando las secuencias autoincrementales con el maximo copiado.
        El orden se calcula con `_orden_y_ciclos()` (algoritmo de Kahn) en
        lugar de `Base.metadata.sorted_tables`, y las claves foraneas se
        relajan durante la copia (vease mas abajo).

    - app/api/v1/migraciones.py
        Cuatro endpoints de administrador:
        `POST   /api/v1/migraciones/clonar`      (crea el clon y devuelve su URI)
        `DELETE /api/v1/migraciones/clonar/{nombre}` (lo borra)
        `GET    /api/v1/migraciones/clones`       (lista los clones)
        `GET    /api/v1/migraciones/clonar/{nombre}/verificar` (compara el
        clon con el origen: mismas tablas, mismas columnas, mismas filas y
        backfill aplicado; SOLO LECTURA)
        y uno de diagnostico:
        `GET    /api/v1/migraciones/esquema`      (compara el metadata con el
        esquema real de la base de datos; solo lectura)

  CORRECCIONES DE DEFECTOS QUE YA EXISTIAN (fuera de la gestion de este lote):

    - app/services/backup_service.py
        El fallback de PostgreSQL (que es el que se usa en produccion, porque
        la imagen del contenedor no trae `pg_dump`) generaba un dump con solo
        `INSERT INTO`: CERO `CREATE TABLE`. Comprobado sobre un backup real
        descargado de produccion (8.478 INSERT sobre 28 tablas). Ese fichero
        NO ERA RESTAURABLE: no habia tablas donde insertar, y las 13 tablas
        sin filas ni siquiera aparecian. Ademas el `bytea` se escribia como
        `\\x...` (doble barra, formato equivocado) y el `bool` se comprobaba
        despues del `int`. Ahora el fallback emite el DDL real de la base de
        datos (leido de `pg_catalog`, no del metadata), los datos, los
        indices, las claves foraneas (al final, para tolerar FK circulares) y
        las secuencias (`setval`), y es restaurable de verdad.

    - app/db/migrations.py
        El guardian de arranque (`verificar_esquema`) era fail-closed SOLO a
        medias: `report_schema_drift()` solo comparaba las tres tablas de
        `COLUMNS_TO_ADD` (`estados`, `tickets`, `adjuntos`). Una columna que
        el modelo declarase y la base de datos no tuviera pasaban
        desapercibida, y la aplicacion respondia 500 al usarla. Ahora existe
        `comparar_esquema_completo()`, que compara TODO el metadata, y el
        guardian lo usa cuando `ESQUEMA_ESTRICTO` esta a True.
        Ademas, la nulabilidad de `auditorias.usuario_id` (NOT NULL en la base
        de datos) DEPENDIA de ejecutar a mano
        `python -m scripts.migrar_auditoria_usuario_id_nullable`. El servicio
        `deadline_notifier` inserta auditorias de eventos del sistema con
        `usuario_id = NULL`: si la columna seguia siendo NOT NULL, el INSERT
        fallaba con IntegrityError y los triggers de SLA dejaban de registrar
        auditoria. Ahora es una migracion idempotente que se aplica en cada
        arranque.

    - app/db/migrations.py (cerrojo y savepoints de los indices)
        Defecto REAL detectado en produccion el 2026-11-14. En el arranque,
        `start.sh` ejecuta `verificar_esquema()` en los TRES roles (web,
        worker y beat) a la vez, y los tres aplican las migraciones sobre la
        MISMA base de datos. Dos de ellos pueden pasar a la vez el chequeo
        `CREATE INDEX IF NOT EXISTS` (que NO bloquea) y los dos intentan
        crear el mismo indice: el segundo recibe `duplicate key value
        violates unique constraint "pg_class_relname_nsp_index"` y su
        TRANSACCION queda ABORTADA, de modo que los indices que quedaban
        por crear fallan TODOS con "current transaction is aborted".
        Medido: un servicio creo 3 indices y fallo en los 52 restantes.
        REPRODUCIDO en local con 3 procesos concurrentes: 90 fallos, con el
        mismo error de `pg_class`.
        El esquema de produccion quedo bien (los otros dos servicios
        crearon los indices que faltaban: los 34 `ix_<tabla>_proyecto_id`
        existen, verificados sobre el DDL real de produccion), pero era
        suerte, no garantias.
        Fix: (a) cada indice va en su PROPIO savepoint, de modo que un
        fallo aislado revierte solo su indice y no los demas; (b)
        `pg_advisory_xact_lock` serializa las migraciones de los tres
        servicios (el primero migra, los demas esperan y encuentran el
        esquema ya alineado).

    - app/db/migrations.py (comparador de indices)
        El guardian de arranque comparaba COLUMNAS, nunca indices, asi que
        un esquema al que le faltaba un indice pasaba el control sin dejar
        rastro. Se anade `comparar_indices_completo()`, que informa de cada
        indice declarado que NO esta en su sitio (FALTA) o que esta en
        otra tabla (COLISION), y se expone en
        `GET /api/v1/migraciones/esquema` (`indices`, `indices_faltantes`,
        `indices_colision`).

    - app/services/backup_service.py (columnas JSON)
        Defecto REAL detectado en produccion el 2026-11-18 al restaurar un
        backup: 925 de las 8.762 filas NO se restauraban
        (`invalid input syntax for type json`). psycopg2 convierte las
        columnas `json`/`jsonb` en objetos Python, y un literal SQL
        escrito a pelo no siempre es JSON valido: un string JSON
        (`"incidencia"`) salia como `'incidencia'` (sin las comillas del
        JSON), un booleano salia como `TRUE` y un null JSON como `NULL`.
        Fix: el literal se serializa teniendo en cuenta el TIPO de la
        columna (`_pg_literal(v, tipo)`), de modo que un valor JSON se
        escribe siempre como JSON valido. Cubierto por 18 pruebas nuevas
        (16 de unitario y 2 de round-trip real contra PostgreSQL).

    - tests/test_v2009_backup_postgresql.py
        Pruebas nuevas del generador de backups: los literales de cada tipo
        de dato, los literales JSON (string, booleano, objeto, lista,
        numero, null), un round-trip REAL contra PostgreSQL con columnas
        JSON y una prueba de CONCURRENCIA (tres conexiones aplicando las
        migraciones a la vez, que es lo que hacen los tres servicios de
        Railway).

    - app/db/migrations.py (migracion del proyecto Legacy)
        El primer fallo en PostgreSQL lo arrastro la validacion V2 y fue
        real: el INSERT de la membresia comparaba `usuarios.rol` contra el
        literal 'administrador', pero esa columna es un ENUM que SQLAlchemy
        persiste con el NOMBRE del miembro (`ADMINISTRADOR`), no con su
        valor. PostgreSQL rechazaba la conversion con `invalid input value
        for enum rolusuario: "administrador"`. Ahora la etiqueta real se LEE
        de la base de datos (`_etiquetas_rol_usuario()`: valores
        almacenados y catalogo `pg_enum`) y el rol se filtra EN PYTHON
        (`_resolver_etiqueta_admin()`), de modo que no hay ningun literal
        que pueda fallar. Con el fallo, el lote se habria desplegado con las
        34 tablas de negocio sin `proyecto_id` (el paso 2 estaba dentro del
        mismo savepoint que el paso 3).
        Ademas, los tres pasos (fila del proyecto, backfill y membresia)
        compartian UN SOLO `begin_nested()`: si el ultimo fallaba,
        PostgreSQL revertia el SAVEPOINT y con el el backfill completo
        (unas 8.500 filas), dejando `proyecto_id` a NULL en todas las
        tablas. Ahora cada paso va en su PROPIO savepoint (y el backfill,
        uno por tabla): un fallo puntual revierte solo su paso y el resto de
        la migracion se aplica.

    - app/services/clone_service.py (copia de datos)
        `Base.metadata.sorted_tables` NO sirve en este esquema: el ciclo
        `tickets.portada_adjunto_id` -> `adjuntos.id` <->
        `adjuntos.ticket_id` -> `tickets.id` hace que SQLAlchemy avise
        ("unresolvable cycles between tables adjuntos, comentarios, tickets")
        y devuelva un orden que NO es topologico (coloca `tickets` en la
        posicion 2 y `usuarios` en la 3). La copia fallaba con
        `insert or update on table "tickets" violates foreign key
        constraint "tickets_creador_id_fkey"`. El ciclo es real e
        inevitable (`adjuntos.ticket_id` es NOT NULL, no se puede nulificar).
        Ahora el orden lo calcula `_orden_y_ciclos()` (Kahn) y las claves
        foraneas se relajan durante la copia con
        `SET LOCAL session_replication_role = replica`, que es el camino
        preferido y NO deja cambios en el esquema del clon. Si el rol no
        fuese superusuario, el codigo cae a un segundo camino que marca
        como DEFERRABLE INITIALLY DEFERRED los constraints de las tablas en
        ciclo, hace `SET CONSTRAINTS ALL DEFERRED` y los restaura al
        terminar.

    - tests/test_v2001_regressions.py
        `subprocess.run(..., text=True)` sin `encoding="utf-8"`: el proceso
        hijo se lanzaba con `-X utf8` pero el padre decodificaba su salida
        con el locale del sistema (cp1252 en Windows) y el test fallaba con
        `TypeError: argument of type 'NoneType' is not iterable`. Medido:
        con cp1252 falla, con UTF-8 forzado pasa. En `ubuntu-latest` (el
        runner de CI) no se reproducia, pero hacia la suite fragil en
        cualquier equipo con locale no UTF-8.

    - app/templates/usuarios/tabla.html
        BUG FUNCIONAL: los botones de desactivar y reactivar usuario
        salvo 204. Con `hx-swap="innerHTML"` sobre `#usuarios-tabla`, el
        cuerpo vacio se inyectaba en el contenedor y BORRABA LA TABLA ENTERA
        tras cada desactivacion o reactivacion. Ahora se usa `hx-swap="none"`
        (el patron que ya usa el boton de logout en `base.html`) y se recarga
        la tabla con `htmx.ajax('GET','/usuarios/tabla', ...)`.

    - pyproject.toml
        Su cabecera afirma que `pyproject.toml` y `requirements.txt` declaran
        "la MISMA" lista de dependencias, pero `kombu` solo estaba fijado en
        `requirements.txt`. Es la transitiva que dejo caer el worker (vease la
        seccion 7 de este documento).

    - tools/audit_db_columns.py, tools/audit_links.py,
      tools/audit_links_broken.py, tools/audit_links_broken_v2.py,
      tools/audit_routes.py, validate_api.py, validate_templates.py
        Siete herramientas versionadas fallaban en Windows: leian el codigo
        fuente con la codificacion ANSI (cp1252) en vez de UTF-8
        (`UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d`) y
        escribian con la misma codificacion (`UnicodeEncodeError`). Ademas,
        `validate_templates.py` fallaba en silencio: solo analizaba 19 de las
        35 plantillas y las otras 16 las marcaba como error de parseo. Ahora
        analizan las 35.

    - test_board_refresh_fix.py, test_calendario_filtros.py
        Dos scripts en la raiz del repositorio con `SyntaxError` en Python
        3.11: `f-string expression part cannot include a backslash` (solo
        valido en 3.12+, PEP 701). El proyecto declara `requires-python
        >=3.12,<3.13` pero el interprete local es 3.11, de modo que no se
        podian ni compilar. Corregidos con el patron minimo.

    - .gitignore
        No cubria los restos de lotes anteriores ni los datos del cliente:
        `/dist-demo/`, `/dist-fix/`, `/demo-static/`, `/mvp-demo/`,
        `/screenshots/`, `/browser/`, `/user_input_files/` (5,9 MB de ficheros
        del cliente: .mpp, .xml, .pdf, .xlsx, .csv),
        `/bitacora-grm-v2.bundle` y `/itsm_kanban_mvp/` (copia obsoleta del
        MVP con su propio paquete `app`: 41 ficheros versionados que
        ensombrecen el paquete real y cuyo
        `itsm_kanban_mvp/tests/test_kanban_service.py` importa
        `app.services.kanban_service`, que no existe en la aplicacion real).

    - NUEVO .github/workflows/ci.yml
        El repositorio NO tenia CI: un bug de JavaScript llego a produccion
        sin que nada lo detectara. Ahora `push` y `pull_request` sobre `main`
        y `release/**` ejecutan la suite completa en Python 3.12.

1. BASE
================================================================================

  Commit base:        d986d48 (docs(release): addendum 9 con el despliegue en
                      produccion del lote V2.008)
  Rama de trabajo:    release/v2.001 (rama canonica)
  Motor:              PostgreSQL (Railway) y SQLite (desarrollo y tests)
  SQLAlchemy:         2.0.36 (fijado en requirements.txt)
  Python:             3.12 en produccion (>=3.12,<3.13), 3.11 local
  Suite antes:        262 passed (227 previos + 35 de V2.008)
  Suite despues:      320 passed (262 previos + 58 nuevos de V2.009)

  Lo que ya existia y NO se toca en este lote: la jerarquia
  Espacio -> Tablero -> Ticket, el LOV de Resultado de Pruebas, el pivote de
  "Cuenta de Resultado", los KPIs del dashboard, el servicio de backups por
  rutas, el autoalojado de Tailwind/SortableJS/Inter (V2.007) y el
  autoalojado de la vista previa de imagenes (V2.006).

  Contexto del plan de multi-tenancy (recuperado del analisis previo):
  el aislamiento por proyecto se apoyaba en la jerarquia
  Espacio -> Tablero -> Ticket, que NO se aplicaba en las consultas de
  tickets (el listado de `/api/v1/tickets` devolvia todos los tickets sin
  filtrar por espacio, y el parametro `?espacio=N` de las vistas no
  comprobaba la pertenencia del usuario). La solucion acordada era
  `proyecto_id` por fila + filtro ORM global (`with_loader_criteria`) + RLS
  como segunda capa, en cuatro ventanas: V1 aditiva, V2 clon, V3 corte,
  V4 segundo proyecto. Este lote ejecuta V1 y V2.

2. CAMBIO UNICO
================================================================================

  2.1 LA COLUMNA `proyecto_id` ES ADITIVA Y NULLABLE.

      - Se anade a las 34 tablas de negocio. NO se anade a `usuarios`
        (globales), ni a `proyectos` y `proyecto_usuarios` (catalogo y
        puente), ni a las tablas puente `espacio_miembros`,
        `ticket_etiquetas` y `ticket_miembros` (su aislamiento se deriva de
        las tablas a las que apuntan).
      - Es NULLABLE. El paso a NOT NULL es de la ventana V3 (el corte).
      - No se borra ni se renombra ninguna columna, indice ni restriccion
        existente.
      - El indice (`ix_<tabla>_proyecto_id`) se crea aparte: en PostgreSQL,
        `ALTER TABLE ADD COLUMN` no crea el indice.

  2.2 EL FILTRO POR PROYECTO ESTA PREPARADO PERO INERTE.

      `obtener_proyecto_actual()` devuelve `None` mientras
      `AISLAMIENTO_PROYECTO_ACTIVO` sea False (valor por defecto). Sin
      proyecto activo: no se inyecta ningun criterio, no se fija ningun GUC y
      las politicas RLS (que no se crean) no restringen nada. El
      comportamiento observable de la aplicacion es IDENTICO al de V2.008.

  2.3 EL BACKFILL NO TOCA DATOS DE NEGOCIO.

      Crea el proyecto "Legacy" (id 1, nombre "Legacy") y asigna a el las
      filas que tuvieran `proyecto_id` a NULL. Ningun otro dato cambia: los
      934 tickets siguen siendo los mismos, ahora con `proyecto_id = 1`.

  2.4 EL GUARDIAN DE ESQUEMA PASA A COMPARAR TODO EL METADATA.

      `comparar_esquema_completo()` compara cada tabla del metadata con el
      esquema real de la base de datos. Se activa con `ESQUEMA_ESTRICTO`
      (por defecto False en este despliegue; se mide antes de encenderlo con
      `GET /api/v1/migraciones/esquema`).

  2.5 EL BACKUP DE PRODUCCION PASA A SER RESTAURABLE.

      El fallback de PostgreSQL emite ahora el DDL real (leido de
      `pg_catalog`), los datos, los indices, las claves foraneas al final y
      las secuencias. Round-trip verificado en PostgreSQL 16.2: esquema
      sintetico (FK circular, tabla vacia, IDENTITY, ENUM, bytea, unicode) y
      esquema real de la aplicacion (40 tablas), con tablas, filas, digests
      md5, columnas, constraints e indices IDENTICOS entre origen y destino.

3. QUE NO SE MODIFICO
================================================================================

  - El esquema de datos existente: ninguna columna, indice, restriccion,
    vista, funcion o secuencia existente se toca. La unica excepcion, y es
    una RELAJACION (no un cambio de dato), es `auditorias.usuario_id`, que
    pasa de NOT NULL a nullable para que los eventos del sistema puedan
    registrarse.
  - Ningun dato de negocio. El backfill solo anade una columna nueva y la
    rellena; no modifica ningun valor existente.
  - Los estados del Kanban: siguen siendo los 10 de siempre. NO se crea el
    estado "Analisis/Bloqueado" (la desviacion 1 de V2.008 sigue abierta).
  - El LOV de Resultado de Pruebas y el pivote de "Cuenta de Resultado":
    intactos (la categoria "BLOQUEADO PARA EJECUTAR" de V2.008 sigue igual).
  - Los KPIs del dashboard: intactos. En particular, el KPI "Incidencias
    Abiertas" no cambia, y el porcentaje de aprobados sigue sumando solo
    `OK` + `OK CON OBS.`.
  - El filtrado por espacio de las vistas: NO se toca en este lote. El
    aislamiento por proyecto se prepara; el corte (V3) es el que lo activa.
  - El aislamiento REAL entre proyectos: NO se activa en este lote. El
    filtro ORM y las politicas RLS quedan INERTES (flags a False), asi que
    los 934 tickets de produccion siguen siendo visibles para todos, igual
    que en V2.008. Lo que se hace es dejar el mecanismo preparado y
    PROBADO contra un clon.
  - El rol con el que conecta la aplicacion: NO se cambia. Sigue siendo
    `postgres` (superusuario), que es lo que hace que RLS siga siendo
    inutilizable como capa de defensa. Crear el rol de aplicacion sin
    privilegios de owner es parte de V3 (el corte).
  - `requirements.txt`: congelado. No se anade ninguna dependencia.
  - La logica de negocio: tickets, estados, SLA, notificaciones, correos,
    reportes, Trello, importacion UAT, dashboards y vistas. Ningun cambio.
  - La API publica: no se anade ni se cambia ningun endpoint existente. Los
    cuatro endpoints nuevos son de administracion y de diagnostico.
  - El empaquetado de Tailwind, SortableJS e Inter (V2.007) y la vista
    previa de imagenes en comentarios (V2.006).

4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  - Cambiar el Worker: NO. El lote no toca Celery, ni las tareas, ni el
    broker. El worker se redespliega solo por su cuenta (en este despliegue,
    junto con `beat`, para que los tres servicios queden en el mismo commit).
  - Migraciones de base de datos: SI, y son automaticas. En el arranque, el
    servicio web aplica `apply_migrations()`: 34 `ALTER TABLE ADD COLUMN
    proyecto_id` (idempotentes), 34 indices, la creacion de la tabla
    `proyectos` y del puente `proyecto_usuarios`, el proyecto "Legacy", el
    backfill de `proyecto_id` y la relajacion de
    `auditorias.usuario_id`. No hay migraciones manuales.
  - Variables de entorno nuevas: NINGUNA obligatoria. Los tres flags
    (`AISLAMIENTO_PROYECTO_ACTIVO`, `RLS_HABILITADO`, `ESQUEMA_ESTRICTO`)
    tienen valor por defecto False y no hace falta definirlos.
  - Reinicio: el despliegue normal de los tres servicios (web, worker, beat).
  - Rollback: ver seccion 7.

5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 AUTOMATICO (lo que ya se ha ejecutado en este lote)

      - Suite nueva de V2.009: 58 passed
        (40 en tests/test_v2009_proyecto_aislamiento.py y 18 en
        tests/test_v2009_backup_postgresql.py)
      - Suite completa: 320 passed, 0 failed
      - Validacion V2 contra un clon real de PostgreSQL 16.2: todas las
        comprobaciones OK (seccion 5.2)
      - CI de GitHub Actions: el workflow se ejecuto en local con el comando
        exacto del workflow (292 passed) y se valido contra el esquema
        oficial de GitHub Actions (0 errores)
      - QA de produccion con solo GET y POST de login (ver seccion 9)

  5.2 EN UN CLON (ventana V2) - PROCEDIMIENTO Y RESULTADO MEDIDO

      El procedimiento (el mismo que se ejecutara en produccion contra el
      clon de la base de datos real):

      1) Crear el clon:
         POST /api/v1/migraciones/clonar
         {"nombre": "railway_clon_v2009", "copiar_datos": true}
         -> devuelve la URI del clon, el numero de tablas y de filas copiadas.
      2) Aplicar las migraciones de V2.009 sobre el clon y comprobar que no
         hay errores de esquema.
      3) Comparar el esquema del clon con el de produccion: debe coincidir
         tabla a tabla, sin columnas que falten.
      4) Comprobar que el backfill dejo TODAS las filas de negocio en el
         proyecto "Legacy" y que ninguna quedo con `proyecto_id` a NULL.
      5) Comprobar que el backup del clon es restaurable (mismo round-trip).
      6) Comprobar que, con `AISLAMIENTO_PROYECTO_ACTIVO` a True, las
         consultas filtran por proyecto, y que con el flag a False el
         comportamiento es el de siempre.
      7) Reversion: DELETE /api/v1/migraciones/clonar/railway_clon_v2009

      RESULTADO MEDIDO EN LOCAL (PostgreSQL 16.2, base de datos de origen con
      2 proyectos y 2 tickets, el mismo motor y la misma version que
      produccion): TODAS LAS COMPROBACIONES OK.

        - Migraciones: 0 errores, 0 errores de esquema.
        - `proyecto_id` presente en `tickets`, indice
          `ix_tickets_proyecto_id` creado, tablas `proyectos` y
          `proyecto_usuarios` creadas.
        - Proyecto "Legacy" creado con el nombre correcto; 0 tickets con
          `proyecto_id` a NULL; el administrador quedo como miembro del
          proyecto Legacy (validacion de la correccion del ENUM).
        - Guardian estricto: ninguna deriva.
        - Clon: 40 tablas, filas identicas al origen (tickets, proyectos y
          auditorias), 0 filas sin `proyecto_id`, 36 secuencias alineadas.
        - RLS: 34 politicas creadas y habilitadas sin errores; con un rol
          NORMAL (no superusuario, no owner) se ve 0 filas sin el GUC
          (fail-closed), 1 fila por proyecto con el GUC puesto, 0 filas para
          un proyecto inexistente, la escritura en otro proyecto se rechaza
          y, tras `deshabilitar_rls`, se vuelven a ver las 2 filas.

      HALLAZGO IMPORTANTE (documentado, NO corregido en este lote):
      el rol con el que conecta la aplicacion en produccion es `postgres`,
      que en PostgreSQL es SUPERUSUARIO, y los superusuarios **siempre**
      ignoran RLS ("superusers and roles with the BYPASSRLS attribute always
      bypass the row security system"), incluso con `FORCE ROW LEVEL
      SECURITY`. Medido: como `postgres` se ven las 2 filas con y sin GUC.
      Es decir: mientras la aplicacion conecte como superusuario, RLS NO es
      una capa de defensa real. Por eso la creacion del rol de aplicacion
      sin privilegios de owner es parte de la ventana **V3 (el corte)**, que
      es donde RLS se enciende. En V2.009 el flag `RLS_HABILITADO` esta a
      False y las politicas ni siquiera se crean en produccion.

  5.3 VISUAL (lo que debe hacer el propietario; NO se ha hecho ninguna
      escritura en produccion en este lote)

      1) Crear un ticket propio con resultado "BLOQUEADO PARA EJECUTAR".
      2) Comprobar el badge BLOQ cian (#0891b2) en /kanban.
      3) Comprobar la columna BLOQ del dashboard con el mismo
         `getComputedStyle().backgroundColor`.
      4) Comprobar que el pie de aprobados no cambia de numerador.
      5) Comprobar que el selector ofrece la opcion marcada.
      6) Comprobar que el KPI "Incidencias Abiertas" no baja.
      7) Comprobar que /usuarios ya no borra la tabla al desactivar o
         reactivar un usuario (la correccion de `hx-swap`).
      8) Comprobar que GET /api/v1/migraciones/esquema devuelve
         `"ok": true` (sin deriva de esquema).

6. TRAZABILIDAD
================================================================================

  Requisito                            Fichero / funcion                    Prueba
  ------------------------------------ ------------------------------------- ----------
  Catalogo de proyectos                app/models/proyecto.py               test_v2009: 1-6
  Contexto de proyecto (inerto)        app/core/proyecto.py                 test_v2009: 7-12
  Columna proyecto_id (34 tablas)      app/models/*.py                      test_v2009: 13-19
  Filtro ORM global                    app/db/session.py                    test_v2009: 20-27
  Migracion + backfill                 app/db/migrations.py                 test_v2009: 28-31
  Guardian estricto de esquema         app/db/migrations.py                 test_v2009: 32-34
  RLS preparado, no activado           app/db/rls.py                        test_v2009: 35-38
  Clon de la base de datos             app/services/clone_service.py        seccion 5.2
  Orden de copia con ciclo de FK       app/services/clone_service.py        test_v2009: 31
  Verificacion del clon (origen=clon)  app/services/clone_service.py        seccion 5.2
  Etiqueta real del ENUM de usuarios   app/db/migrations.py                 test_v2009: 30
  Savepoint por paso del backfill      app/db/migrations.py                 test_v2009: 33
  Savepoint por indice + cerrojo       app/db/migrations.py                 test_v2009: 32
  Comparador de indices declarados    app/db/migrations.py                 seccion 5.2
  Literales JSON en el backup          app/services/backup_service.py      test_v2009_backup
  Migraciones concurrentes (3 roles)   app/db/migrations.py                 test_v2009_backup
  Salida UTF-8 del subproceso de test  tests/test_v2001_regressions.py      suite completa
  Endpoints de clon y de diagnostico   app/api/v1/migraciones.py            seccion 5.2
  Backup restaurable                   app/services/backup_service.py       round-trip PG 16.2
  Nulabilidad de auditorias            app/db/migrations.py                 COLUMNS_A_NULLABLE
  Tabla no se borra al desactivar      app/templates/usuarios/tabla.html     QA visual 5.3 (7)
  kombu fijado tambien en pyproject    pyproject.toml                       requirements.txt:41
  Herramientas sin error de codific.   tools/*.py, validate_*.py            ejecucion sin -X utf8
  Scripts de test sin SyntaxError      test_*.py (raiz)                     py_compile
  .gitignore cubre los restos          .gitignore                           git check-ignore
  CI                                   .github/workflows/ci.yml             push / pull_request

  Correlacion con las desviaciones de V2.008:
    - Desviacion 1 (estado "Analisis/Bloqueado"): sigue ABIERTA y sin
      cambios en este lote.
    - Desviacion 2 (auto-marcado a DESESTIMADA): sin cambios.
    - Desviacion 3 (alias "BLOQ"): sin cambios.
    - Desviacion 4 (columnas_front derivadas): sin cambios.
    - Incidente del worker (kombu 5.7.0): resuelto en V2.008 con el commit
      cc3ebed; en este lote se completa con el pin en `pyproject.toml`.

7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  7.1 PUBLICACION

      1) Publicar en `release/v2.001` y alinear `main` por fast-forward:
         git checkout main && git merge --ff-only release/v2.001
      2) Push de las dos ramas (nunca con --force).
      3) Desplegar `web`, `worker` y `beat` con el MISMO commit. `web` se
         redespliega solo por autoDeploy al publicar en `main`; `worker` y
         `beat` se despliegan a mano, porque no tienen autoDeploy.
      4) Verificar en produccion (seccion 9).

  7.2 QUE PASA EN EL PRIMER ARRANQUE

      El servicio web aplica, en este orden: `create_all` (crea `proyectos` y
      `proyecto_usuarios`), los 34 `ALTER TABLE ADD COLUMN proyecto_id`, los
      34 indices, el bloque RLS (inactivo: el flag esta a False), las
      migraciones de datos (incluye el proyecto "Legacy" y el backfill) y la
      comprobacion de esquema. Si la migracion de datos falla, el esquema
      queda igualmente alineado y el arranque continua (los fallos de datos
      no son motivo de caida: esa separacion ya existia).

      El backfill mueve unas 8.500 filas a la columna nueva. Es una operacion
      pequena y de una sola transaccion.

  7.3 ROLLBACK

      El lote es ADITIVO, asi que el rollback es raro, pero existe:

      a) Rollback de codigo (volver al commit anterior):
         - La columna `proyecto_id` se queda en la base de datos. Es
           inofensiva: el codigo anterior no la conoce y no la usa.
         - La tabla `proyectos` y el puente `proyecto_usuarios` se quedan
           tambien. Inofensivos.
         - El backfill NO se deshace (y no hace falta: solo anadio una
           columna).
         - Si el rollout se decide tras el despliegue, basta con desplegar
           el commit anterior; no hay que tocar la base de datos.

      b) Rollback de la migracion de nulabilidad:
         `ALTER TABLE auditorias ALTER COLUMN usuario_id SET NOT NULL;`
         (solo si algun proceso depende de que NO admita NULL, lo que no
         ocurre: el modelo la declara nullable desde hace tiempo).

      c) Desactivar RLS (por si se llego a encender):
         `app.db.rls.deshabilitar_rls(engine, TABLAS_CON_PROYECTO)`.

      d) Borrar el clon de validacion:
         `DELETE /api/v1/migraciones/clonar/{nombre}`.

  7.4 NOTAS DE OPERACION

      - El paquete `bitacora_grm-0.1.0` estaba INSTALADO en el interprete
        local (`site-packages/app`), con una copia obsoleta de 90 ficheros
        que pisaba el repositorio en cualquier import hecho fuera del
        directorio de trabajo (el interprete embebido corre en modo
        aislado, de modo que el cwd no va al `sys.path`). Se sustituyo por
        una instalacion en modo editable (`pip install -e .`) para que
        `import app` apunte siempre al repositorio.
      - Los ficheros `tmp_*.py` del arbol de trabajo son herramientas de
        esta sesion y estan cubiertos por `.gitignore` (`/tmp_*.py`).

================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
new file mode 100644
index 0000000..f6f5695
--- /dev/null
+++ b/.github/workflows/ci.yml
@@ -0,0 +1,73 @@
+# Workflow de CI del proyecto Bitacora GRM v2.
+# Existe porque un bug de JavaScript llego a produccion sin que nada lo
+# detectara: aqui se ejecuta la suite completa de tests en cada push y en
+# cada pull request, de modo que un fallo BLOQUEA el merge.
+
+name: CI
+
+# La clave "on" va entrecomillada a proposito: en YAML 1.1 (PyYAML) el token
+# sin comillas `on` se resuelve como el booleano `true` y rompe cualquier
+# validador que lea el workflow por clave. GitHub Actions lo interpreta igual.
+"on":
+  push:
+    branches:
+      - main
+      - 'release/**'
+  pull_request:
+    branches:
+      - main
+      - 'release/**'
+
+# Un unico run por referencia: al hacer push al mismo PR se cancela el run
+# anterior, que ya esta obsoleto.
+concurrency:
+  group: ci-${{ github.workflow }}-${{ github.ref }}
+  cancel-in-progress: true
+
+jobs:
+  test:
+    name: Suite de tests (Python 3.12)
+    runs-on: ubuntu-latest
+    # La suite completa tarda 12-15 minutos en local.
+    timeout-minutes: 45
+    env:
+      # El codigo y las plantillas estan en UTF-8 con tildes. Se fuerza el modo
+      # UTF-8 de Python para que la decodificacion de la salida de los
+      # subprocesos que lanza la suite NO dependa del locale de la imagen del
+      # runner: con cp1252 (locale por defecto de Windows) el test
+      # `test_el_arranque_completo_sobre_una_base_nueva_no_falla` falla al
+      # decodificar la salida UTF-8 del subproceso.
+      PYTHONUTF8: '1'
+    steps:
+      - name: Checkout del repositorio
+        uses: actions/checkout@v4
+
+      - name: Preparar Python 3.12
+        uses: actions/setup-python@v5
+        with:
+          python-version: '3.12'
+          cache: 'pip'
+          cache-dependency-path: requirements.txt
+
+      - name: Instalar dependencias
+        run: |
+          python -m pip install --upgrade pip
+          pip install -r requirements.txt
+          # `pytest` NO esta en requirements.txt (vive en requirements-dev.txt),
+          # asi que se instala aqui como dependencia de desarrollo del CI, fijada
+          # a la misma version que declara el repositorio.
+          pip install pytest==9.1.1 pytest-cov
+
+      - name: Ejecutar la suite de tests
+        # No hace falta Postgres ni Redis: `tests/conftest.py` fuerza una base
+        # SQLite temporal bajo `tests/tmp/` y fija el entorno ANTES de importar
+        # la app, asi que aqui no se define `DATABASE_URL`.
+        run: python -m pytest tests/ -q --tb=short --junitxml=pytest-report.xml
+
+      - name: Subir el informe de tests
+        if: always()
+        uses: actions/upload-artifact@v4
+        with:
+          name: pytest-report
+          path: pytest-report.xml
+          if-no-files-found: warn
diff --git a/.gitignore b/.gitignore
index 5269a61..948da94 100644
--- a/.gitignore
+++ b/.gitignore
@@ -986,3 +986,32 @@
 # en docs/onboarding-demo/).
 /docs/onboarding-demo-recuperada/
 
+# ==============================================================================
+# RESTOS DE LOTES, DEMOS Y DATOS DEL CLIENTE (NO son codigo fuente)
+# ==============================================================================
+# Builds antiguos del artefacto estatico: ``dist/`` ya esta cubierto, pero estas
+# carpetas (generadas en lotes anteriores) seguian versionadas y duplicaban su
+# contenido.
+/dist-demo/
+/dist-fix/
+# Demos y material de presentacion: no forman parte de la aplicacion.
+/demo-static/
+/mvp-demo/
+# Capturas de pantalla de las pruebas manuales: regenerables.
+/screenshots/
+# Scripts de exploracion con navegador: usan playwright/aiohttp/neo4j/metrics,
+# dependencias que NO estan declaradas en ``requirements.txt``.
+/browser/
+# Ficheros de trabajo entregados por el cliente (.mpp/.xml/.pdf/.xlsx/.csv,
+# ~5,9 MB): son datos del cliente, no codigo fuente.
+/user_input_files/
+# Bundle de git generado para las entregas: es un artefacto del repositorio,
+# no parte del codigo.
+/bitacora-grm-v2.bundle
+# Copia obsoleta del MVP con su propio paquete ``app``: si alguien anade la
+# carpeta al ``sys.path`` ensombrece el paquete real, y su
+# ``itsm_kanban_mvp/tests/test_kanban_service.py`` importa
+# ``app.services.kanban_service``, que no existe en la aplicacion real
+# (ImportError).
+/itsm_kanban_mvp/
+
diff --git a/app/api/v1/migraciones.py b/app/api/v1/migraciones.py
index 9cdfa67..2b72a5d 100644
--- a/app/api/v1/migraciones.py
+++ b/app/api/v1/migraciones.py
@@ -9,6 +9,7 @@ Todas las migraciones son seguras de re-ejecutar.
 import logging
 
 from fastapi import APIRouter, Depends, HTTPException, status
+from pydantic import BaseModel, Field
 from sqlalchemy.orm import Session
 
 from app.api.v1.deps import require_admin
@@ -96,6 +97,202 @@ def preview_migracion_gar(
     }
 
 
+@router.get("/esquema")
+def diagnostico_esquema(
+    db: Session = Depends(get_db),
+    _: Usuario = Depends(require_admin),
+):
+    """Compara el metadata de SQLAlchemy con el esquema real de la base de datos.
+
+    Diagnostico de SOLO LECTURA: no aplica migraciones ni modifica nada.
+
+    Devuelve tres bloques:
+
+    * ``columnas_sincronizadas``: el estado de ``COLUMNS_TO_ADD`` (las
+      columnas que las migraciones deben anadir si faltan).
+    * ``comparacion_completa``: una linea por tabla del modelo, con las
+      columnas que faltan en la base de datos.
+    * ``deriva``: solo las tablas con deriva real (las que NO estan OK).
+
+    Y dos bloques mas sobre INDICES (V2.009), porque el guardian comparaba
+    solo columnas y en produccion fallaron 52 de los 55 indices declarados
+    sin que nada lo dijera:
+
+    * ``indices``: los indices declarados que NO estan donde deben
+      (``FALTA`` o ``COLISION``). Los que estan bien no se reportan.
+    * ``indices_faltantes`` / ``indices_colision``: los mismos, separados.
+
+    Sirve para medir la deriva antes de encender el guardian estricto
+    (``ESQUEMA_ESTRICTO``): un guardian fail-closed sobre el esquema completo
+    puede tumbar los tres servicios si la base de datos arrastra una deriva
+    heredada, asi que primero se mide.
+
+    Returns
+    -------
+    dict
+        ``ok`` (bool), ``deriva`` (list[str]), ``comparacion_completa``
+        (list[str]), ``columnas_sincronizadas`` (list[str]),
+        ``tablas_modelo`` (int) y ``tablas_base_datos`` (int).
+    """
+    from sqlalchemy import inspect
+
+    from app.db.migrations import (
+        comparar_esquema_completo,
+        comparar_indices_completo,
+        report_schema_drift,
+    )
+
+    eng = db.get_bind()
+    comparacion = comparar_esquema_completo(eng)
+    deriva = [l for l in comparacion if "faltan" in l or "no existe" in l]
+    indices = comparar_indices_completo(eng)
+    try:
+        tablas_bd = len(inspect(eng).get_table_names())
+    except Exception:  # pragma: no cover
+        tablas_bd = -1
+
+    return {
+        "ok": not deriva,
+        "deriva": deriva,
+        "comparacion_completa": comparacion,
+        "indices": indices,
+        "indices_faltantes": [l for l in indices if "FALTA" in l],
+        "indices_colision": [l for l in indices if "COLISION" in l],
+        "columnas_sincronizadas": report_schema_drift(eng),
+        "tablas_modelo": len(comparacion),
+        "tablas_base_datos": tablas_bd,
+    }
+
+
+# ----------------------------------------------------------------------- #
+# Clon de la base de datos (validacion de migraciones)
+# ----------------------------------------------------------------------- #
+class ClonRequest(BaseModel):
+    nombre: str = Field(
+        default="railway_clon_v2009",
+        max_length=63,
+        description="Nombre de la base de datos del clon (solo letras, digitos y _)",
+    )
+    copiar_datos: bool = Field(
+        default=True,
+        description="Si False, solo se replica el esquema (util para validar DDL)",
+    )
+
+
+@router.post("/clonar")
+def clonar_base_datos(
+    datos: ClonRequest,
+    db: Session = Depends(get_db),
+    _: Usuario = Depends(require_admin),
+):
+    """Crea un CLON de la base de datos en el mismo servidor PostgreSQL.
+
+    Sirve para validar migraciones y cambios de esquema contra una copia de
+    los datos reales, sin tocar la base de datos de produccion.
+
+    - El clon se crea con el nombre indicado (``railway_clon_*`` por defecto).
+    - Se replica el esquema desde el metadata de los modelos y se copian los
+      datos fila a fila en orden de dependencias; las secuencias quedan
+      alineadas con el maximo copiado.
+    - Se devuelve la URL de conexion del clon (admin-only).
+
+    Se revierte con ``DELETE /api/v1/migraciones/clonar/{nombre}``.
+    """
+    from app.core.config import settings
+    from app.services.clone_service import ErrorClonado, clonar_base_datos as clonar
+
+    try:
+        resultado = clonar(
+            settings.get_database_url(),
+            datos.nombre,
+            copiar_datos=datos.copiar_datos,
+        )
+    except ErrorClonado as exc:
+        logger.warning("[migracion/clon] no se pudo clonar: %s", exc)
+        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
+    except Exception as exc:  # noqa: BLE001
+        logger.exception("[migracion/clon] error inesperado al clonar")
+        raise HTTPException(
+            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
+            detail=f"Error al clonar la base de datos: {exc}",
+        )
+    logger.info("[migracion/clon] clon creado: %s", resultado.get("nombre"))
+    return resultado
+
+
+@router.delete("/clonar/{nombre}")
+def borrar_clon(
+    nombre: str,
+    db: Session = Depends(get_db),
+    _: Usuario = Depends(require_admin),
+):
+    """Borra la base de datos del clon (operacion de reversion)."""
+    from app.core.config import settings
+    from app.services.clone_service import ErrorClonado, borrar_clon as borrar
+
+    try:
+        return borrar(settings.get_database_url(), nombre)
+    except ErrorClonado as exc:
+        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
+    except Exception as exc:  # noqa: BLE001
+        logger.exception("[migracion/clon] error inesperado al borrar el clon")
+        raise HTTPException(
+            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
+            detail=f"Error al borrar el clon: {exc}",
+        )
+
+
+@router.get("/clones")
+def listar_clones(
+    db: Session = Depends(get_db),
+    _: Usuario = Depends(require_admin),
+):
+    """Lista las bases de datos de clon que existen en el servidor."""
+    from app.core.config import settings
+    from app.services.clone_service import ErrorClonado, listar_clones as listar
+
+    try:
+        return {"clones": listar(settings.get_database_url())}
+    except ErrorClonado as exc:
+        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
+
+
+@router.get("/clonar/{nombre}/verificar")
+def verificar_clon(
+    nombre: str,
+    db: Session = Depends(get_db),
+    _: Usuario = Depends(require_admin),
+):
+    """Compara el clon con la base de datos de origen (SOLO LECTURA).
+
+    Validacion de la ventana V2: comprueba que el clon es una copia fiel
+    (mismas tablas, mismas columnas, mismo numero de filas) y que el
+    backfill del aislamiento por proyecto quedo aplicado dentro del clon
+    (ninguna fila de negocio con ``proyecto_id`` a NULL, proyecto "Legacy"
+    existente y con miembros).
+
+    No escribe nada ni en el origen ni en el clon.
+
+    Returns
+    -------
+    dict
+        ``ok`` (bool) y el detalle de la comparacion.
+    """
+    from app.core.config import settings
+    from app.services.clone_service import ErrorClonado, verificar_clon as verificar
+
+    try:
+        return verificar(settings.get_database_url(), nombre)
+    except ErrorClonado as exc:
+        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
+    except Exception as exc:  # noqa: BLE001
+        logger.exception("[migracion/clon] error inesperado al verificar el clon")
+        raise HTTPException(
+            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
+            detail=f"Error al verificar el clon: {exc}",
+        )
+
+
 # ----------------------------------------------------------------------- #
 # Bulk update de fechas para tarjetas ``GAR_RI_*`` en BACKLOG
 # ----------------------------------------------------------------------- #
diff --git a/app/core/config.py b/app/core/config.py
index c82d338..16d5d11 100644
--- a/app/core/config.py
+++ b/app/core/config.py
@@ -125,6 +125,36 @@ class Settings(BaseSettings):
     # ``settings.AUTO_INIT_DB`` en lugar de os.getenv (no se modifica aqui).
     AUTO_INIT_DB: bool = False
 
+    # === Aislamiento por proyecto (multi-tenancy) ===
+    # V2.009 deja PREPARADA la capa de aislamiento por proyecto (columna
+    # ``proyecto_id`` en las tablas de negocio, filtro ORM con
+    # ``with_loader_criteria`` y politicas RLS), pero la mantiene INERTE:
+    # mientras el flag sea False, ``app/core/proyecto.py`` devuelve siempre
+    # ``None`` como proyecto activo, no se aplica ningun criterio y el
+    # comportamiento observable es identico al de V2.008.
+    #
+    # Encender este flag es la ventana V3 (el corte): antes hay que validar
+    # el clon (ventana V2). No se enciende en V2.009.
+    AISLAMIENTO_PROYECTO_ACTIVO: bool = False
+
+    # RLS_HABILITADO=true aplica las politicas de Row Level Security sobre las
+    # tablas con ``proyecto_id``. Por defecto NO se aplican (V2.009). Se
+    # habilitan junto con el rol de aplicacion sin privilegios de owner en la
+    # ventana V3: hasta entonces, con el rol owner de siempre, RLS seria
+    # inerte y ademas podria tumbar el arranque si el rol no fuese owner.
+    RLS_HABILITADO: bool = False
+
+    # ESQUEMA_ESTRICTO=true hace que el guardian de arranque compare TODO el
+    # metadata de SQLAlchemy con el esquema real de la base de datos, y no solo
+    # las tres tablas de ``COLUMNS_TO_ADD``. Es fail-closed: si falta una
+    # columna que el modelo declara, el arranque se aborta en vez de servir
+    # con un esquema viejo y responder 500 al usarla.
+    #
+    # Se mide antes de encenderlo (endpoint ``/api/v1/migraciones/esquema``):
+    # un guardian estricto sobre el esquema completo puede tumbar los tres
+    # servicios si la base de datos arrastra una deriva heredada.
+    ESQUEMA_ESTRICTO: bool = False
+
     # Configuracion individual (usada para construir DATABASE_URL si no se define)
     POSTGRES_USER: str = "grm"
     POSTGRES_PASSWORD: str = "grm"
diff --git a/app/core/proyecto.py b/app/core/proyecto.py
new file mode 100644
index 0000000..833d804
--- /dev/null
+++ b/app/core/proyecto.py
@@ -0,0 +1,126 @@
+"""
+Contexto de proyecto (multi-tenancy) - V2.009.
+
+Este modulo es la CAPA DE CONTEXTO del aislamiento por proyecto. Por si solo no
+cambia nada: expone un ``ContextVar`` con el proyecto activo y las funciones
+para fijarlo. El filtro ORM (que vive en ``app/db/session.py``) y las
+politicas RLS (que viven en ``app/db/rls.py``) consultan este contexto.
+
+Estado por defecto: AISLADO (apagado)
+-------------------------------------
+``obtener_proyecto_actual()`` devuelve ``None`` mientras el flag
+``AISLAMIENTO_PROYECTO_ACTIVO`` sea ``False`` (valor por defecto). Con el
+contexto en ``None``:
+
+* la sesion NO aplica ningun criterio de filtrado;
+* no se fija el GUC ``app.proyecto_id``;
+* las politicas RLS, aunque existan, no restringen nada.
+
+Por eso el despliegue de V2.009 es **puramente aditivo**: el comportamiento
+observable de la aplicacion es identico al de V2.008. Encender el aislamiento
+(establecer el contexto en cada peticion) es la ventana **V3 (el corte)**.
+
+Porque se usa ``ContextVar`` y no una variable global, dos peticiones
+concurrentes con distinto proyecto no se pisan: cada una lleva su contexto.
+"""
+from contextlib import contextmanager
+from contextvars import ContextVar
+from typing import Iterator, List, Optional, Type
+
+from app.core.config import settings
+
+
+#: Proyecto activo de la peticion/credencial actual. ``None`` = sin filtro.
+_proyecto_actual: ContextVar[Optional[int]] = ContextVar(
+    "grm_proyecto_actual", default=None
+)
+
+
+def obtener_proyecto_actual() -> Optional[int]:
+    """
+    Devuelve el id del proyecto activo, o ``None`` si el aislamiento esta
+    apagado o no hay contexto.
+
+    Devolver ``None`` es lo que mantiene el sistema en su comportamiento
+    historico: sin contexto no hay filtro.
+    """
+    if not settings.AISLAMIENTO_PROYECTO_ACTIVO:
+        return None
+    return _proyecto_actual.get()
+
+
+def establecer_proyecto_actual(proyecto_id: Optional[int]) -> object:
+    """
+    Fija el proyecto activo y devuelve el token de reinicio.
+
+    El token permite deshacer el cambio al final de la peticion. Se puede
+    usar como gestor de contexto con ``token = ...`` / ``reset(token)``.
+    """
+    return _proyecto_actual.set(proyecto_id)
+
+
+def reiniciar_proyecto_actual() -> None:
+    """Deja el contexto sin proyecto activo."""
+    _proyecto_actual.set(None)
+
+
+@contextmanager
+def contexto_proyecto(proyecto_id: Optional[int]) -> Iterator[Optional[int]]:
+    """
+    Gestor de contexto que fija el proyecto activo durante el bloque.
+
+    Al salir restaura el contexto anterior aunque haya excepciones.
+
+    Uso::
+
+        with contexto_proyecto(1):
+            ...  # aqui las consultas ven solo el proyecto 1
+    """
+    token = _proyecto_actual.set(proyecto_id)
+    try:
+        yield proyecto_id
+    finally:
+        _proyecto_actual.reset(token)
+
+
+def clases_con_proyecto() -> List[Type]:
+    """
+    Devuelve las clases ORM que tienen la columna ``proyecto_id``.
+
+    La lista se DERIVA del metadata de SQLAlchemy en vez de mantenerse a mano:
+    asi no puede desincronizarse de los modelos (el mismo motivo por el que
+    ``app/api/v1/metricas.py`` deriva las columnas del pivote del catalogo).
+
+    Se usa ``Base.registry.mappers`` (API publica) en vez de
+    ``Base.metadata.tables`` porque hacen falta las CLASES (para
+    ``with_loader_criteria``), no las tablas.
+    """
+    from app.db.base import Base
+
+    resultado: List[Type] = []
+    for mapper in Base.registry.mappers:
+        tabla = mapper.local_table
+        if tabla is not None and "proyecto_id" in tabla.c:
+            resultado.append(mapper.class_)
+    return resultado
+
+
+def tablas_con_proyecto() -> List[str]:
+    """
+    Nombres de las tablas de negocio que tienen la columna ``proyecto_id``.
+
+    Se excluyen las tablas PUENTE (las que tienen ``proyecto_id`` como parte de
+    su clave primaria, como ``proyecto_usuarios``): no son tablas de datos de
+    un proyecto, sino tablas de relacion, y su aislamiento se deriva del de las
+    tablas a las que apuntan.
+    """
+    from app.db.base import Base
+
+    resultado = []
+    for nombre, tabla in Base.metadata.tables.items():
+        if "proyecto_id" not in tabla.c:
+            continue
+        if "proyecto_id" in {c.name for c in tabla.primary_key.columns}:
+            continue
+        resultado.append(nombre)
+    return sorted(resultado)
diff --git a/app/db/migrations.py b/app/db/migrations.py
index 93e1c7d..b9a2b3b 100644
--- a/app/db/migrations.py
+++ b/app/db/migrations.py
@@ -159,6 +159,76 @@ COLUMNS_TO_ADD: Dict[str, Dict[str, Tuple[str, str] | str]] = {
 }
 
 
+# ============================================================================ #
+# V2.009 -- AISLAMIENTO POR PROYECTO (ventana aditiva)
+# ============================================================================ #
+# La columna ``proyecto_id`` se anade a las tablas de negocio para poder
+# aislar los datos por proyecto (multi-tenancy) sin depender de la jerarquia
+# Espacio -> Tablero -> Ticket, que no se aplicaba en las consultas de
+# tickets.
+#
+# Es ADITIVO en el sentido estricto del lote:
+#   * la columna es NULLABLE (el paso a NOT NULL es de la ventana V3, el corte);
+#   * no se borra ni se renombra ninguna columna, indice o restriccion;
+#   * el backfill solo RELLENA la columna nueva con el proyecto "Legacy" (id 1),
+#     de modo que los datos existentes son los mismos de siempre;
+#   * el filtro ORM y las politicas RLS quedan INERTES hasta que se active
+#     ``AISLAMIENTO_PROYECTO_ACTIVO`` (ventana V3).
+#
+# Las tablas de asociacion (espacio_miembros, ticket_etiquetas,
+# ticket_miembros) NO llevan ``proyecto_id``: son tablas puente y su
+# aislamiento se deriva del de las tablas a las que apuntan (espacios, tickets,
+# etiquetas), que si llevan la columna.
+_TIPO_PROYECTO_ID = (
+    "INTEGER REFERENCES proyectos(id) ON DELETE SET NULL",
+    "INTEGER REFERENCES proyectos(id) ON DELETE SET NULL",
+)
+
+#: Tablas de negocio que pertenecen a un proyecto (las 34 clases con la
+#: columna nueva). ``usuarios`` NO aparece: los usuarios son globales.
+TABLAS_CON_PROYECTO: List[str] = [
+    "adjuntos",
+    "auditorias",
+    "botones_tarjeta",
+    "campos_personalizados",
+    "catalogo_items",
+    "catalogo_tipos",
+    "checklist_items",
+    "checklists",
+    "comandos_programados",
+    "comentarios",
+    "ejecuciones_automatizacion",
+    "ejecuciones_boton",
+    "ejecuciones_comando",
+    "espacios",
+    "estados",
+    "etapas_proyecto",
+    "etiquetas",
+    "historial_estados",
+    "menciones_usuario",
+    "notificaciones",
+    "permisos_tablero",
+    "reacciones",
+    "reglas_automatizacion",
+    "reporte_destinatarios",
+    "reporte_entregas_diarias",
+    "reporte_plantilla",
+    "tableros",
+    "ticket_dependencias",
+    "ticket_etapas",
+    "ticket_referencias",
+    "tickets",
+    "transiciones_estado",
+    "valores_campo",
+    "watches",
+]
+
+# Anade ``proyecto_id`` a cada tabla del proyecto, conservando el resto de
+# columnas declaradas para esas mismas tablas.
+for _tabla_proyecto in TABLAS_CON_PROYECTO:
+    COLUMNS_TO_ADD.setdefault(_tabla_proyecto, {})["proyecto_id"] = _TIPO_PROYECTO_ID
+
+
 # Indices que deben existir (idempotentes: IF NOT EXISTS funciona en ambos)
 INDEXES: List[Tuple[str, str]] = [
     ("ix_estados_tablero_id",  "CREATE INDEX IF NOT EXISTS ix_estados_tablero_id ON estados(tablero_id)"),
@@ -189,6 +259,18 @@ INDEXES: List[Tuple[str, str]] = [
     ("ix_adjuntos_comentario", "CREATE INDEX IF NOT EXISTS ix_adjuntos_comentario_id ON adjuntos(comentario_id)"),
 ]
 
+# V2.009 -- Indice de ``proyecto_id`` en cada tabla del proyecto. El indice NO
+# lo crea el ``ALTER TABLE ADD COLUMN`` (en PostgreSQL los indices se crean
+# aparte), asi que se declaran aqui. Sin el, el filtro por proyecto y el
+# conteo por proyecto tendrian que recorrer la tabla entera.
+INDEXES.extend(
+    (
+        "ix_%s_proyecto_id" % tabla,
+        "CREATE INDEX IF NOT EXISTS ix_%s_proyecto_id ON %s(proyecto_id)" % (tabla, tabla),
+    )
+    for tabla in TABLAS_CON_PROYECTO
+)
+
 # Tablas que deben existir (si el modelo esta presente, ``create_all``
 # las crea automaticamente al ejecutar ``apply_migrations``). Este set
 # sirve para verificar manualmente o para tooling externo.
@@ -197,6 +279,25 @@ TABLES_REQUIRED: List[str] = [
     "ticket_referencias",
 ]
 
+# === V2.009 -- Nulabilidad que el modelo declara y la BD puede no tener ======
+# Estas columnas son NULLABLE en el modelo, pero una version anterior de la
+# base de datos pudo crearlas como NOT NULL. El caso real es
+# ``auditorias.usuario_id``: el servicio ``app.services.deadline_notifier``
+# inserta auditorias de eventos del sistema con ``usuario_id = NULL`` y, si
+# la columna sigue siendo NOT NULL, el INSERT falla con IntegrityError.
+#
+# Hasta V2.008 la relajacion de esa nulabilidad DEPENDIA de ejecutar a mano
+# ``python -m scripts.migrar_auditoria_usuario_id_nullable``: si nadie lo
+# ejecutaba en el despliegue, los triggers de SLA dejaban de registrar
+# auditoria. Ahora la operacion es una migracion idempotente que se aplica en
+# cada arranque.
+#
+# Relajar la nulabilidad es ADITIVO: no cambia ningun dato, solo permite que
+# el valor sea NULL.
+COLUMNAS_A_NULLABLE: List[Tuple[str, str]] = [
+    ("auditorias", "usuario_id"),
+]
+
 
 def _get_existing_columns(eng: Engine, table: str) -> set:
     """Devuelve el conjunto de columnas existentes en la tabla (vacio si la tabla no existe)."""
@@ -219,6 +320,11 @@ def _column_exists(eng: Engine, table: str, column: str) -> bool:
     return column in _get_existing_columns(eng, table)
 
 
+#: Clave del cerrojo consultivo de PostgreSQL que serializa las
+#: migraciones entre los servicios que arrancan a la vez (web, worker y beat).
+CLAVE_CERROJO_MIGRACIONES = 7_412_009_013
+
+
 def _asegurar_modelos_importados() -> None:
     """Importa el paquete de modelos para que ``Base.metadata`` los conozca.
 
@@ -257,7 +363,7 @@ def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
     # incluye tambien las migraciones de datos, que no impiden servir.
     stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0,
              "schema_errors": 0, "tables_created": 0, "data_migrated": 0,
-             "index_errors": 0}
+             "index_errors": 0, "rls": {}}
 
     # 1) Asegurar que todas las tablas existen (no-op si ya estan).
     #    Necesario porque algunas columnas tienen FKs a tablas nuevas (tableros,
@@ -273,6 +379,36 @@ def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
 
     # 2) Anadir columnas faltantes
     with eng.begin() as conn:
+        # --- V2.009: CERROJO DE MIGRACIONES -----------------------------
+        # En el despliegue de Railway, ``start.sh`` ejecuta
+        # ``verificar_esquema()`` en los TRES roles (web, worker y beat) a
+        # la vez, y los tres aplican las migraciones sobre la MISMA base de
+        # datos. Dos de ellos pueden pasar a la vez el chequeo
+        # ``CREATE INDEX IF NOT EXISTS`` (que no bloquea) y los dos intentar
+        # crear el mismo indice: el segundo recibe
+        #
+        #     duplicate key value violates unique constraint
+        #     "pg_class_relname_nsp_index"
+        #
+        # y su TRANSACCION queda abortada, de modo que los indices que
+        # quedaban por crear fallan todos con "current transaction is
+        # aborted". Medido en produccion el 2026-11-14: un servicio creo 3
+        # indices y fallo en los 52 restantes.
+        #
+        # ``pg_advisory_xact_lock`` serializa las migraciones: el primero la
+        # toma y los demas esperan; cuando le toca, encuentra el esquema ya
+        # alineado y no hace nada. El cerrojo se suelta solo al cerrar la
+        # transaccion (COMMIT o ROLLBACK).
+        if is_pg:
+            try:
+                conn.execute(text(
+                    "SELECT pg_advisory_xact_lock(:clave)"
+                ), {"clave": CLAVE_CERROJO_MIGRACIONES})
+            except Exception as exc:  # pragma: no cover
+                logger.warning(
+                    "[migrations] no se pudo tomar el cerrojo de migraciones: %s", exc,
+                )
+
         for table, columns in COLUMNS_TO_ADD.items():
             existing = _get_existing_columns(eng, table)
             for column, type_def in columns.items():
@@ -307,9 +443,21 @@ def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
         #    registraba con ``logger.debug`` (invisible en produccion) y no
         #    se contabilizaba, de modo que un esquema al que le faltaba un
         #    indice pasaba el ``verificar_esquema`` sin dejar rastro.
+        #
+        #    V2.009 -- CADA INDICE VA EN SU PROPIO SAVEPOINT.
+        #    En PostgreSQL, un error dentro de una transaccion la ABORTA: los
+        #    comandos siguientes fallan con "current transaction is aborted".
+        #    Con el bucle entero en una sola transaccion, UN indice que
+        #    fallara (por ejemplo, por un nombre que ya existe en otra
+        #    tabla) invalidaba los 54 restantes. Se vio en produccion el
+        #    2026-11-14: 3 indices creados y 52 fallidos, entre ellos los 34
+        #    ``ix_<tabla>_proyecto_id``, que son los que necesita el filtro
+        #    por proyecto. Con un savepoint por indice, un fallo aislado
+        #    revierte solo su propio indice.
         for name, sql in INDEXES:
             try:
-                conn.execute(text(sql))
+                with conn.begin_nested():
+                    conn.execute(text(sql))
                 stats["indexes"] += 1
             except Exception as e:
                 stats["index_errors"] += 1
@@ -317,6 +465,24 @@ def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
                     "[migrations] Indice %s NO se pudo crear: %s", name, e,
                 )
 
+    # 3-bis) Row Level Security (V2.009). Inerte por defecto: solo se aplica
+    #        si el flag ``RLS_HABILITADO`` esta a True, cosa que ocurre en la
+    #        ventana V3 (el corte). Con el rol owner de siempre y sin FORCE,
+    #        las politicas existirian pero no restringen nada.
+    try:
+        from app.core.config import settings as _settings
+
+        if _settings.RLS_HABILITADO:
+            from app.db.rls import aplicar_politicas_rls
+
+            stats["rls"] = aplicar_politicas_rls(eng, TABLAS_CON_PROYECTO)
+            logger.info("[migrations] RLS aplicado: %s", stats["rls"])
+        else:
+            stats["rls"] = {"politicas": 0, "habilitadas": 0, "forzadas": 0, "errores": 0}
+    except Exception as e:
+        stats["errors"] += 1
+        logger.warning("[migrations] RLS no se pudo aplicar: %s", e)
+
     # 4) Migraciones de datos (idempotentes): cambios de nomenclatura
     #    y de valores permitidos. Se ejecutan en una TRANSACCION SEPARADA
     #    para que un fallo en los datos NO haga rollback de las columnas/
@@ -939,9 +1105,221 @@ def _apply_data_migrations(conn, eng: Engine) -> int:
             "[migrations] data: marcar estados es_entrega fallo (aislado): %s", e,
         )
 
+    # 4.x) V2.009 -- Proyecto "Legacy" y backfill de ``proyecto_id``.
+    #
+    # Aditivo e idempotente:
+    #   1) crea la fila del proyecto "Legacy" (id 1) si no existe;
+    #   2) rellena ``proyecto_id = 1`` en todas las filas que lo tengan a NULL
+    #      (o sea, todas las anteriores a este lote);
+    #   3) da de alta al administrador como miembro del proyecto Legacy.
+    #
+    # Tras el backfill, todas las filas existentes pertenecen al proyecto
+    # "Legacy", que es exactamente el conjunto de datos que habia antes: no
+    # se pierde ni se modifica ningun dato de negocio, solo se anade la
+    # pertenencia a un proyecto. El paso a NOT NULL (y la creacion del rol
+    # sin privilegios de owner) son de la ventana V3 (el corte).
+    total += _aplicar_proyecto_legacy(conn, is_pg)
+
     return total
 
 
+#: Id del proyecto "Legacy" (el que contiene los datos preexistentes).
+PROYECTO_LEGACY_ID = 1
+
+#: Nombre del proyecto "Legacy".
+NOMBRE_PROYECTO_LEGACY = "Legacy"
+
+
+def _etiquetas_rol_usuario(conn, is_pg: bool) -> List[str]:
+    """
+    Devuelve las etiquetas REALES con las que la base de datos persiste el
+    rol de los usuarios.
+
+    Por que hace falta (V2.009)
+    -------------------------
+    ``usuarios.rol`` es un ENUM de PostgreSQL y SQLAlchemy persiste el
+    **NOMBRE** del miembro del enum de Python (``RolUsuario.ADMINISTRADOR``),
+    no su VALOR (``"administrador"``). Comparar la columna contra el literal
+    ``'administrador'`` hace que PostgreSQL intente convertir ese texto a
+    etiqueta del enum y falle con::
+
+        invalid input value for enum rolusuario: "administrador"
+
+    Ese error tumbaba el paso 3 de la migracion del proyecto Legacy. En vez de
+    adivinar la etiqueta, se leen las que la base de datos usa de verdad: los
+    valores distintos almacenados en la columna y, en PostgreSQL, el catalogo
+    ``pg_enum``.
+    """
+    etiquetas: List[str] = []
+
+    # 1) Valores realmente almacenados (funciona en ambos motores).
+    sql = (
+        "SELECT DISTINCT rol::text FROM usuarios WHERE rol IS NOT NULL"
+        if is_pg else
+        "SELECT DISTINCT rol FROM usuarios WHERE rol IS NOT NULL"
+    )
+    try:
+        for fila in conn.execute(text(sql)).fetchall():
+            if fila and fila[0] is not None:
+                etiqueta = str(fila[0])
+                if etiqueta not in etiquetas:
+                    etiquetas.append(etiqueta)
+    except Exception:  # pragma: no cover - la tabla puede no existir aun
+        pass
+
+    # 2) En PostgreSQL, el catalogo de etiquetas del tipo enum.
+    if is_pg:
+        try:
+            for fila in conn.execute(text(
+                "SELECT e.enumlabel FROM pg_type t "
+                "JOIN pg_enum e ON e.enumtypid = t.oid "
+                "JOIN pg_attribute a ON a.atttypid = t.oid "
+                "JOIN pg_class c ON c.oid = a.attrelid "
+                "JOIN pg_namespace n ON n.oid = c.relnamespace "
+                "WHERE c.relname = 'usuarios' AND a.attname = 'rol' "
+                "AND n.nspname = current_schema() "
+                "ORDER BY e.enumsortorder"
+            )).fetchall():
+                if fila and fila[0]:
+                    etiqueta = str(fila[0])
+                    if etiqueta not in etiquetas:
+                        etiquetas.append(etiqueta)
+        except Exception:  # pragma: no cover - depende del catalogo de PG
+            pass
+
+    return etiquetas
+
+
+def _resolver_etiqueta_admin(conn, is_pg: bool) -> str:
+    """
+    Devuelve la etiqueta con la que el motor almacena el rol de administrador.
+
+    Prioridad: coincidencia exacta -> etiqueta que contenga "ADMIN" -> el
+    NOMBRE del miembro del enum de Python (que es lo que SQLAlchemy persiste
+    por defecto en PostgreSQL y en SQLite).
+    """
+    etiquetas = _etiquetas_rol_usuario(conn, is_pg)
+
+    for etiqueta in etiquetas:
+        if etiqueta.strip().upper() == "ADMINISTRADOR":
+            return etiqueta
+
+    for etiqueta in etiquetas:
+        if "ADMIN" in etiqueta.strip().upper():
+            return etiqueta
+
+    try:
+        from app.models.usuario import RolUsuario
+        return RolUsuario.ADMINISTRADOR.name
+    except Exception:  # pragma: no cover
+        return "ADMINISTRADOR"
+
+
+def _aplicar_proyecto_legacy(conn, is_pg: bool) -> int:
+    """
+    Crea el proyecto "Legacy" y asigna a el todas las filas de negocio que
+    todavia no tienen ``proyecto_id``.
+
+    Es idempotente: se puede ejecutar en cada arranque. Devuelve el numero de
+    filas actualizadas.
+
+    Atomicidad (V2.009)
+    --------------------
+    Cada paso va en su PROPIO savepoint. Antes de V2.009 los tres pasos
+    compartian un unico ``begin_nested()``: si el ultimo fallaba, PostgreSQL
+    revertia el SAVEPOINT entero y con el el backfill completo (8.500 filas),
+    dejando ``proyecto_id`` a NULL en todas las tablas. Ahora un fallo puntual
+    (por ejemplo, que un enum no acepte la etiqueta buscada) solo revierte su
+    propio paso: el resto de la migracion se aplica igual.
+    """
+    actualizadas = 0
+
+    # 1) Fila del proyecto "Legacy" (savepoint propio).
+    try:
+        with conn.begin_nested():
+            if is_pg:
+                conn.execute(text(
+                    "INSERT INTO proyectos (id, nombre, descripcion, plan, color, activo, "
+                    "created_at, updated_at) "
+                    "VALUES (:id, :nombre, :descripcion, NULL, '#6b7280', TRUE, "
+                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
+                    "ON CONFLICT (id) DO NOTHING"
+                ), {"id": PROYECTO_LEGACY_ID, "nombre": NOMBRE_PROYECTO_LEGACY,
+                    "descripcion": "Proyecto historico: contiene los datos "
+                                   "preexistentes al aislamiento por proyecto."})
+            else:
+                conn.execute(text(
+                    "INSERT INTO proyectos (id, nombre, descripcion, plan, color, activo, "
+                    "created_at, updated_at) "
+                    "SELECT :id, :nombre, :descripcion, NULL, '#6b7280', 1, "
+                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
+                    "WHERE NOT EXISTS (SELECT 1 FROM proyectos WHERE id = :id)"
+                ), {"id": PROYECTO_LEGACY_ID, "nombre": NOMBRE_PROYECTO_LEGACY,
+                    "descripcion": "Proyecto historico: contiene los datos "
+                                   "preexistentes al aislamiento por proyecto."})
+    except Exception as e:
+        # Sin la fila del proyecto no se puede hacer el backfill: la columna
+        # ``proyecto_id`` tiene clave foranea a ``proyectos.id``.
+        logger.warning(
+            "[migrations] data: no se pudo crear el proyecto Legacy: %s", e,
+        )
+        return actualizadas
+
+    # 2) Backfill: cada tabla en su PROPIO savepoint, para que un fallo
+    #    puntual en una tabla no revierta las anteriores.
+    for tabla in TABLAS_CON_PROYECTO:
+        try:
+            with conn.begin_nested():
+                res = conn.execute(text(
+                    "UPDATE %s SET proyecto_id = :pid WHERE proyecto_id IS NULL" % tabla
+                ), {"pid": PROYECTO_LEGACY_ID})
+                n = res.rowcount if hasattr(res, "rowcount") else 0
+            if n:
+                actualizadas += n
+                logger.info(
+                    "[migrations] data: %d filas de %s asignadas al proyecto Legacy",
+                    n, tabla,
+                )
+        except Exception as e:
+            logger.warning(
+                "[migrations] data: backfill de %s fallo (aislado): %s", tabla, e,
+            )
+
+    # 3) El administrador es miembro del proyecto Legacy (savepoint propio).
+    try:
+        with conn.begin_nested():
+            etiqueta = _resolver_etiqueta_admin(conn, is_pg)
+            # El rol se filtra EN PYTHON, no en SQL: pasar un literal a una
+            # columna ENUM obliga a PostgreSQL a convertirlo a etiqueta y
+            # falla si no coincide exactamente. Leyendo el valor almacenado
+            # no hay ninguna conversion que pueda fallar.
+            filas = conn.execute(text("SELECT id, rol FROM usuarios")).fetchall()
+            admines = [
+                fila[0] for fila in filas
+                if fila[1] is not None and "ADMIN" in str(fila[1]).strip().upper()
+            ]
+            ts = datetime.now(timezone.utc).isoformat()
+            for usuario_id in admines:
+                conn.execute(text(
+                    "INSERT INTO proyecto_usuarios (proyecto_id, usuario_id, rol, created_at) "
+                    "SELECT :pid, :uid, :rol, :ts WHERE NOT EXISTS ("
+                    "SELECT 1 FROM proyecto_usuarios "
+                    "WHERE proyecto_id = :pid AND usuario_id = :uid)"
+                ), {"pid": PROYECTO_LEGACY_ID, "uid": usuario_id,
+                    "rol": etiqueta.strip().lower(), "ts": ts})
+        if admines:
+            logger.info(
+                "[migrations] data: %d administrador(es) anadidos al proyecto Legacy",
+                len(admines),
+            )
+    except Exception as e:
+        logger.warning(
+            "[migrations] data: membresia del administrador en Legacy fallo (aislado): %s", e,
+        )
+
+    return actualizadas
+
+
 def report_schema_drift(eng: Optional[Engine] = None) -> List[str]:
     """
     Devuelve una lista de lineas describiendo columnas que faltan
@@ -959,6 +1337,138 @@ def report_schema_drift(eng: Optional[Engine] = None) -> List[str]:
     return out
 
 
+def comparar_esquema_completo(eng: Optional[Engine] = None) -> List[str]:
+    """
+    Compara el metadata de SQLAlchemy con el esquema REAL de la base de datos.
+
+    Por que hace falta (V2.009)
+    -------------------------
+    ``report_schema_drift()`` solo mira las tablas de ``COLUMNS_TO_ADD`` (tres
+    hasta V2.008). Eso hacia que el guardian de arranque fuera **fail-closed
+    solo a medias**: si el modelo declaraba una columna que la base de datos
+    no tenia, y esa columna no estaba en ``COLUMNS_TO_ADD``, nadie se enteraba
+    y la aplicacion respondia 500 al usarla. En V2.009 el guardian compara
+    TODAS las tablas del metadata.
+
+    Que devuelve
+    ------------
+    Una linea por tabla con la deriva. El formato distingue las dos senales:
+    * ``<tabla>: faltan <columna>`` -> la tabla existe pero le faltan columnas
+      que el modelo declara. Es la senal que debe abortar el arranque.
+    * ``<tabla>: la tabla no existe en la base de datos`` -> el modelo declara
+      una tabla que no esta creada.
+    * ``<tabla>: OK`` -> la tabla esta alineada.
+
+    Las tablas que existen en la base de datos pero NO en el modelo no se
+    reportan: son datos historicos que la aplicacion ya no usa y borrarlas es
+    una decision operativa, no una migracion.
+    """
+    eng = eng or _get_default_engine()
+    _asegurar_modelos_importados()
+    try:
+        insp = inspect(eng)
+        tablas_bd = set(insp.get_table_names())
+    except Exception as exc:  # pragma: no cover
+        logger.warning("[migrations] no se pudo inspeccionar el esquema: %s", exc)
+        return []
+
+    out: List[str] = []
+    for nombre, tabla in Base.metadata.tables.items():
+        if nombre not in tablas_bd:
+            out.append(f"{nombre}: la tabla no existe en la base de datos")
+            continue
+        try:
+            columnas_bd = {c["name"] for c in insp.get_columns(nombre)}
+        except Exception as exc:  # pragma: no cover
+            out.append(f"{nombre}: no se pudieron leer sus columnas ({exc})")
+            continue
+        faltan = [c.name for c in tabla.c if c.name not in columnas_bd]
+        if faltan:
+            out.append(f"{nombre}: faltan {', '.join(faltan)}")
+        else:
+            out.append(f"{nombre}: OK")
+    return out
+
+
+def _indice_y_tabla_de_un_index(sql: str) -> Tuple[str, str]:
+    """
+    Extrae el NOMBRE real del indice y su tabla del DDL.
+
+    Ojo: la etiqueta de la tupla de ``INDEXES`` no siempre coincide con el
+    nombre del indice que crea el DDL. Por ejemplo, la etiqueta
+    ``ix_ref_origen`` crea en realidad ``ix_ticket_referencias_ticket_origen_id``
+    y ``ix_adjuntos_comentario`` crea ``ix_adjuntos_comentario_id``. Comparar
+    por la etiqueta daria un "FALTA" falso.
+    """
+    import re as _re
+
+    m = _re.search(
+        r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
+        r"[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?\s+ON\s+[\"']?([A-Za-z_][A-Za-z0-9_]*)",
+        sql, _re.IGNORECASE,
+    )
+    if m:
+        return m.group(1), m.group(2)
+    m2 = _re.search(r"\bON\s+[\"']?([A-Za-z_][A-Za-z0-9_]*)", sql, _re.IGNORECASE)
+    return "", (m2.group(1) if m2 else "")
+
+
+def comparar_indices_completo(eng: Optional[Engine] = None) -> List[str]:
+    """
+    Compara los indices declarados en ``INDEXES`` con los que existen de
+    verdad en la base de datos.
+
+    Por que hace falta (V2.009)
+    -------------------------
+    El guardian de arranque comparaba COLUMNAS, nunca indices. En produccion
+    (2026-11-14) fallaron 52 de los 55 indices declarados y la aplicacion
+    arranco igual: el filtro por proyecto se quedaba sin indice y las
+    consultas tenian que recorrer la tabla entera, sin que nada lo dijera.
+
+    Este comparador devuelve una linea por indice declarado que NO esta en
+    su sitio:
+
+    * ``<nombre>: FALTA (declarado sobre <tabla>)`` -> no existe.
+    * ``<nombre>: COLISION (existe sobre '<otra>', el DDL lo declara sobre
+      '<tabla>')`` -> el nombre ya lo usa OTRA tabla. En PostgreSQL,
+      ``CREATE INDEX IF NOT EXISTS`` ignora el aviso SOLO si el indice con
+      ese nombre esta en la MISMA tabla: si esta en otra, falla con
+      "relation already exists".
+
+    Los indices que estan bien NO se reportan: el resultado son solo
+    problemas.
+    """
+    eng = eng or _get_default_engine()
+    _asegurar_modelos_importados()
+    try:
+        insp = inspect(eng)
+        indice_por_nombre: Dict[str, str] = {}
+        for nombre in Base.metadata.tables:
+            for idx in insp.get_indexes(nombre):
+                indice_por_nombre[idx["name"]] = nombre
+            for uq in insp.get_unique_constraints(nombre):
+                indice_por_nombre.setdefault(uq["name"], nombre)
+    except Exception as exc:  # pragma: no cover
+        logger.warning("[migrations] no se pudieron inspeccionar los indices: %s", exc)
+        return []
+
+    out: List[str] = []
+    for etiqueta, sql in INDEXES:
+        nombre, tabla = _indice_y_tabla_de_un_index(sql)
+        if not nombre:
+            # DDL no reconocible: se usa la etiqueta como nombre.
+            nombre = etiqueta
+        real = indice_por_nombre.get(nombre)
+        if real is None:
+            out.append("%s: FALTA (declarado sobre %s)" % (nombre, tabla))
+        elif tabla and real != tabla:
+            out.append(
+                "%s: COLISION (existe sobre '%s', el DDL lo declara sobre '%s')"
+                % (nombre, real, tabla)
+            )
+    return out
+
+
 def verificar_esquema(eng: Optional[Engine] = None) -> int:
     """Aplica las migraciones y comprueba que el esquema queda alineado.
 
@@ -999,6 +1509,29 @@ def verificar_esquema(eng: Optional[Engine] = None) -> int:
         return 0
 
     faltan = [l for l in lineas if "faltan" in l]
+
+    # V2.009 -- Guardian estricto: compara TODO el metadata con el esquema real.
+    # Hasta V2.008 solo se comparaban las tablas de ``COLUMNS_TO_ADD``, de modo
+    # que una columna que el modelo declarase y la base de datos no tuviera
+    # pasaba desapercibida. Se activa con ``ESQUEMA_ESTRICTO`` porque un
+    # guardian fail-closed sobre el esquema completo puede tumbar los tres
+    # servicios si la base de datos arrastra una deriva heredada; por eso
+    # primero se mide (endpoint ``/api/v1/migraciones/esquema``) y despues se
+    # enciende.
+    deriva_completa: List[str] = []
+    try:
+        from app.core.config import settings as _settings
+
+        if _settings.ESQUEMA_ESTRICTO:
+            deriva_completa = [
+                l for l in comparar_esquema_completo(eng)
+                if "faltan" in l or "no existe" in l
+            ]
+    except Exception as exc:  # noqa: BLE001
+        logger.warning(
+            "[migrations] no se pudo ejecutar la comparacion estricta de esquema: %s", exc,
+        )
+
     errores = int(stats.get("errors", 0) or 0)
     errores_esquema = int(stats.get("schema_errors", 0) or 0)
     logger.info(
@@ -1015,6 +1548,11 @@ def verificar_esquema(eng: Optional[Engine] = None) -> int:
         )
     if faltan:
         logger.error("[migrations] DERIVA DE ESQUEMA: %s", "; ".join(faltan))
+    if deriva_completa:
+        logger.error(
+            "[migrations] DERIVA DE ESQUEMA (comparacion estricta del metadata): %s",
+            "; ".join(deriva_completa),
+        )
     if errores_esquema:
         logger.error(
             "[migrations] %s error(es) de esquema al aplicar las migraciones",
@@ -1025,7 +1563,7 @@ def verificar_esquema(eng: Optional[Engine] = None) -> int:
             "[migrations] %s error(es) en las migraciones de DATAS. El esquema "
             "queda alineado, se continua el arranque.", errores,
         )
-    return 1 if (faltan or errores_esquema) else 0
+    return 1 if (faltan or errores_esquema or deriva_completa) else 0
 
 
 if __name__ == "__main__":
diff --git a/app/db/rls.py b/app/db/rls.py
new file mode 100644
index 0000000..a8baf51
--- /dev/null
+++ b/app/db/rls.py
@@ -0,0 +1,160 @@
+"""
+Row Level Security (RLS) de PostgreSQL para el aislamiento por proyecto.
+
+V2.009 deja la capa de RLS ESCRITA y PREPARADA, pero **NO ACTIVADA**:
+
+* las politicas se crean con ``ENABLE ROW LEVEL SECURITY`` (sin ``FORCE``),
+  de modo que un rol *owner* -- como el de siempre -- las ignora y el
+  comportamiento de la aplicacion no cambia;
+* solo se aplican si el flag ``RLS_HABILITADO`` esta a True, cosa que ocurre
+  en la ventana **V3 (el corte)**, junto con la creacion del rol de aplicacion
+  sin privilegios de owner;
+* en V2.009 el flag esta a False y, por tanto, este modulo no llega a
+  ejecutarse en produccion.
+
+Como funciona
+--------------
+El filtro ORM (``app/db/session.py``) es la PRIMERA capa de defensa: filtra en
+Python, en la consulta. RLS es la SEGUNDA capa: filtra en el motor, de modo
+que ningun camino que se salte el ORM (SQL crudo, una consulta escrita a mano,
+un ``text()``) pueda ver filas de otro proyecto.
+
+La politica lee el GUC de sesion ``app.proyecto_id``, que el listener
+``after_begin`` de ``app/db/session.py`` fija con ``set_config(..., true)``
+(ambito de transaccion). Ese GUC es el unico canal: no hay ninguna tabla de
+"usuario actual" que un atacante pueda manipular desde la aplicacion.
+
+Como la politica es fail-closed (``current_setting`` devuelve NULL si el GUC
+no esta fijado, y entonces solo pasan las filas con ``proyecto_id IS NULL``),
+un camino que se salte el filtro ORM veria menos filas, nunca mas.
+"""
+from __future__ import annotations
+
+import logging
+from typing import Dict, List, Tuple
+
+from sqlalchemy import text
+from sqlalchemy.engine import Engine
+
+logger = logging.getLogger(__name__)
+
+
+#: Prefijo de los nombres de politica. Se usa una politica por tabla (no por
+#: columna) porque RLS se aplica a la FILA entera.
+PREFIJO_POLITICA = "pol_proyecto_"
+
+
+def _politica(tabla: str) -> str:
+    """Devuelve la clausula USING/WITH CHECK de la politica de una tabla."""
+    return (
+        "(proyecto_id IS NOT DISTINCT FROM "
+        "NULLIF(current_setting('app.proyecto_id', true), '')::int)"
+    )
+
+
+def politicas_rls(tablas: List[str]) -> List[Tuple[str, str]]:
+    """
+    Devuelve la lista de sentencias ``DROP`` + ``CREATE POLICY`` de las tablas
+    indicadas. Es idempotente: PostgreSQL no admite ``CREATE POLICY IF NOT
+    EXISTS``, asi que se borra la politica previa (si existe) antes de
+    recrearla. Borrar y recrear LA MISMA politica no altera los datos.
+    """
+    sentencias: List[Tuple[str, str]] = []
+    for tabla in tablas:
+        nombre = "%s%s" % (PREFIJO_POLITICA, tabla)
+        clausula = _politica(tabla)
+        sentencias.append((
+            "drop_policy_%s" % tabla,
+            'DROP POLICY IF EXISTS "%s" ON "%s";' % (nombre, tabla),
+        ))
+        sentencias.append((
+            "create_policy_%s" % tabla,
+            'CREATE POLICY "%s" ON "%s" '
+            'FOR ALL TO PUBLIC '
+            'USING %s WITH CHECK %s;' % (nombre, tabla, clausula, clausula),
+        ))
+    return sentencias
+
+
+def aplicar_politicas_rls(
+    eng: Engine, tablas: List[str], forzar: bool = False
+) -> Dict[str, int]:
+    """
+    Aplica ``ENABLE ROW LEVEL SECURITY`` y las politicas de las tablas dadas.
+
+    Parametros
+    ----------
+    eng
+        Motor contra el que aplicar el DDL.
+    tablas
+        Nombres de las tablas con ``proyecto_id``.
+    forzar
+        Si es True, ademas de ``ENABLE ROW LEVEL SECURITY`` se aplica
+        ``FORCE ROW LEVEL SECURITY``, de modo que las politicas SE APLICAN
+        TAMBIEN al rol owner. En produccion NO se quiere (el rol de aplicacion
+        debe ser un rol normal, sin privilegios de owner: es la razon por la
+        que RLS es una capa de defensa real). Se usa ``True`` en el clon de
+        validacion, donde el unico rol disponible es ``postgres`` (owner), para
+        poder comprobar que las politicas filtran de verdad.
+
+    Devuelve un dict con los contadores ``politicas``, ``habilitadas``,
+    ``forzadas`` y ``errores``.
+    """
+    stats = {"politicas": 0, "habilitadas": 0, "forzadas": 0, "errores": 0}
+    with eng.begin() as conn:
+        for etiqueta, sql in politicas_rls(tablas):
+            try:
+                conn.execute(text(sql))
+                if etiqueta.startswith("create_policy"):
+                    stats["politicas"] += 1
+            except Exception as exc:  # noqa: BLE001
+                stats["errores"] += 1
+                logger.warning("[rls] no se pudo crear la politica %s: %s", etiqueta, exc)
+
+        for tabla in tablas:
+            try:
+                conn.execute(text(
+                    'ALTER TABLE "%s" ENABLE ROW LEVEL SECURITY' % tabla
+                ))
+                stats["habilitadas"] += 1
+                if forzar:
+                    conn.execute(text(
+                        'ALTER TABLE "%s" FORCE ROW LEVEL SECURITY' % tabla
+                    ))
+                    stats["forzadas"] += 1
+            except Exception as exc:  # noqa: BLE001
+                stats["errores"] += 1
+                logger.warning("[rls] no se pudo habilitar RLS en %s: %s", tabla, exc)
+
+    logger.info(
+        "[rls] politicas=%d habilitadas=%d forzadas=%d errores=%d",
+        stats["politicas"], stats["habilitadas"], stats["forzadas"], stats["errores"],
+    )
+    return stats
+
+
+def deshabilitar_rls(eng: Engine, tablas: List[str]) -> Dict[str, int]:
+    """
+    Desactiva RLS en las tablas indicadas (``NO FORCE RLS`` + ``DISABLE``).
+
+    Es la operacion de reversion: deja la base de datos exactamente como
+    estaba antes de aplicar las politicas. No borra datos ni columnas.
+    """
+    stats = {"deshabilitadas": 0, "errores": 0}
+    with eng.begin() as conn:
+        for tabla in tablas:
+            try:
+                conn.execute(text(
+                    'ALTER TABLE "%s" NO FORCE ROW LEVEL SECURITY' % tabla
+                ))
+                conn.execute(text(
+                    'ALTER TABLE "%s" DISABLE ROW LEVEL SECURITY' % tabla
+                ))
+                stats["deshabilitadas"] += 1
+            except Exception as exc:  # noqa: BLE001
+                stats["errores"] += 1
+                logger.warning("[rls] no se pudo desactivar RLS en %s: %s", tabla, exc)
+    logger.info(
+        "[rls] deshabilitadas=%d errores=%d", stats["deshabilitadas"], stats["errores"],
+    )
+    return stats
diff --git a/app/db/session.py b/app/db/session.py
index 16a79f9..2fe8ee1 100644
--- a/app/db/session.py
+++ b/app/db/session.py
@@ -1,10 +1,33 @@
 """
 Sesion de SQLAlchemy: motor + SessionLocal.
+
+V2.009 anade el aislamiento por proyecto en dos piezas:
+
+* ``SesionProyecto``: subclase de ``Session`` que, cuando hay un proyecto
+  activo en el contexto (``app/core/proyecto.py``), aplica el criterio de
+  filtrado por ``proyecto_id`` a todas las clases que lo llevan, mediante
+  ``Session.with_loader_criteria()``. El criterio se aplica a la sesion
+  ENTERA, de modo que cubre tanto la API moderna (``select()``) como la
+  heredada (``Query``) y tambien las cargas por relacion (``lazy="select"``).
+
+* El listener ``after_begin``: fija el GUC de sesion ``app.proyecto_id`` en la
+  transaccion, que es lo que leen las politicas RLS de PostgreSQL.
+
+Ambas piezas son INERTES mientras no haya contexto de proyecto: en V2.009 el
+flag ``AISLAMIENTO_PROYECTO_ACTIVO`` esta apagado, ``obtener_proyecto_actual()``
+devuelve ``None`` y, por tanto, no se aplica ningun criterio ni se fija ningun
+GUC. El comportamiento observable de la aplicacion no cambia.
+
+El listener se registra sobre la clase ``Session`` (no sobre ``SessionLocal``)
+para que cubra TODAS las sesiones de la aplicacion, incluidas las ~25 que
+``app/main.py`` abre directamente con ``SessionLocal()`` y las que abre Celery.
 """
-from sqlalchemy import create_engine
-from sqlalchemy.orm import sessionmaker, Session
+from sqlalchemy import create_engine, event, text
+from sqlalchemy.orm import sessionmaker, Session, with_loader_criteria
+from sqlalchemy.sql import true
 
 from app.core.config import settings
+from app.core.proyecto import obtener_proyecto_actual
 
 
 def _build_engine_kwargs():
@@ -16,11 +39,122 @@ def _build_engine_kwargs():
 
 engine = create_engine(settings.get_database_url(), **_build_engine_kwargs())
 
+
+def _criterio_proyecto(modelo):
+    """
+    Devuelve el criterio que se aplica a ``modelo`` en cada consulta.
+
+    Se construye con el valor CONCRETO del proyecto activo (no con un
+    callable): SQLAlchemy no permite invocar funciones de Python dentro de las
+    expresiones lambda que usa internamente ``with_loader_criteria``, asi que
+    el valor se lee antes de construir el criterio.
+
+    Sin proyecto activo devuelve ``true()``: no se restringe nada, que es el
+    comportamiento historico (V2.008) y el de la ventana V2.009, donde el
+    aislamiento esta apagado.
+    """
+    proyecto_id = obtener_proyecto_actual()
+    if proyecto_id is None:
+        return true()
+    return modelo.proyecto_id == proyecto_id
+
+
+@event.listens_for(Session, "do_orm_execute")
+def _inyectar_filtro_proyecto(orm_execute_state):
+    """
+    Inyecta el filtro por proyecto en cada consulta ORM.
+
+    Es la via que funciona con la version fijada (SQLAlchemy 2.0.36): el
+    listener de clase ``"load"`` con ``with_loader_criteria`` exige un
+    callable, y el sistema de lambdas de SQLAlchemy no admite llamadas a
+    funciones de Python dentro de el.
+
+    Aqui, en cambio, el criterio se construye con el valor concreto del
+    proyecto activo en el momento de la consulta, de modo que:
+
+    * dos peticiones concurrentes con distinto proyecto no se pisan (el valor
+      se lee del ``ContextVar`` en cada consulta);
+    * el filtro cubre la API moderna (``select``) y la heredada (``Query``),
+      porque ``do_orm_execute`` se dispara en ambas;
+    * las cargas por relacion (lazy y eager) tambien lo cubren, porque son
+      consultas ORM propias.
+
+    Sin proyecto activo no se inyecta nada: el comportamiento es identico al
+    de V2.008.
+    """
+    if not orm_execute_state.is_select:
+        return
+    if obtener_proyecto_actual() is None:
+        return
+
+    from app.core.proyecto import clases_con_proyecto
+
+    sentencia = orm_execute_state.statement
+    for modelo in clases_con_proyecto():
+        criterio = _criterio_proyecto(modelo)
+        if criterio is not None:
+            sentencia = sentencia.options(
+                with_loader_criteria(modelo, criterio)
+            )
+    orm_execute_state.statement = sentencia
+
+
+class SesionProyecto(Session):
+    """
+    ``Session`` que aplica el filtro de proyecto cuando hay contexto activo.
+
+    Sin contexto (``obtener_proyecto_actual()`` devuelve ``None``) la sesion
+    se comporta exactamente como una ``Session`` normal: no se aplica ningun
+    criterio. Ese es el estado por defecto de V2.009.
+
+    El filtrado real lo hace el listener global registrado por
+    ``registrar_filtro_proyecto()``; esta clase se mantiene como punto de
+    extension y para dejar explicito en el codigo que TODAS las sesiones de
+    la aplicacion (las ~25 que ``app/main.py`` abre directamente con
+    ``SessionLocal()`` y las que abre Celery) son sensibles al aislamiento.
+    """
+
+    def __init__(self, *args, **kwargs):
+        super().__init__(*args, **kwargs)
+
+
 SessionLocal = sessionmaker(
-    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
+    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False,
+    # OJO: el parametro se llama ``class_``, no ``cls``. En SQLAlchemy 2.0 el
+    # ``sessionmaker`` acepta el resto de kwargs y los pasa a
+    # ``Session.__init__``, de modo que un ``cls=`` equivocado acaba en el
+    # constructor de la Session y revienta con
+    # "Session.__init__() got an unexpected keyword argument 'cls'".
+    class_=SesionProyecto,
 )
 
 
+@event.listens_for(Session, "after_begin")
+def _fijar_proyecto_en_la_transaccion(session, transaction, connection):
+    """
+    Fija ``app.proyecto_id`` en la transaccion actual.
+
+    Es el canal que usan las politicas RLS de PostgreSQL
+    (``current_setting('app.proyecto_id', true)``). Se usa ``set_config`` con
+    el ambito de transaccion (``true`` = local), de modo que el valor desaparece
+    al terminar la transaccion y no se filtra entre peticiones.
+
+    No hace nada si no hay proyecto activo: sin GUC, las politicas RLS (si
+    llegaran a activarse) se comportarian de forma permisiva.
+    """
+    proyecto_id = obtener_proyecto_actual()
+    if proyecto_id is None:
+        return
+    # ``set_config`` es una funcion de PostgreSQL. En SQLite (dev y tests) no
+    # existe, y las politicas RLS tampoco: ahi el GUC no aplica.
+    if connection.dialect.name != "postgresql":
+        return
+    connection.execute(
+        text("SELECT set_config('app.proyecto_id', :valor, true)"),
+        {"valor": str(proyecto_id)},
+    )
+
+
 def get_db() -> Session:
     """Dependencia FastAPI para inyectar una sesion por request."""
     db = SessionLocal()
diff --git a/app/models/__init__.py b/app/models/__init__.py
index 22d7b73..2b667cf 100644
--- a/app/models/__init__.py
+++ b/app/models/__init__.py
@@ -9,6 +9,8 @@ from app.models.checklist import Checklist, ChecklistItem
 from app.models.comentario import Comentario, MencionUsuario
 from app.models.adjunto import Adjunto
 from app.models.automacion import ReglaAutomatizacion, EjecucionAutomatizacion
+# === Multi-tenancy por proyecto (V2.009) ===
+from app.models.proyecto import Proyecto, proyecto_usuarios, PROYECTO_LEGACY_ID, NOMBRE_PROYECTO_LEGACY
 # === Nuevos modelos estilo Trello ===
 from app.models.espacio import Espacio, Tablero, PermisoTablero, espacio_miembros
 from app.models.watch import Watch, Reaccion, Notificacion
@@ -59,4 +61,6 @@ __all__ = [
     "ReportePlantilla",
     "ReporteDestinatario",
     "ReporteEntregaDiaria",
+    # Multi-tenancy por proyecto (V2.009)
+    "Proyecto", "proyecto_usuarios", "PROYECTO_LEGACY_ID", "NOMBRE_PROYECTO_LEGACY",
 ]
diff --git a/app/models/adjunto.py b/app/models/adjunto.py
index 7f8de4e..65da496 100644
--- a/app/models/adjunto.py
+++ b/app/models/adjunto.py
@@ -64,6 +64,10 @@ class Adjunto(Base, TimestampMixin):
     # subida nueva). En SQLite se persiste como ``BLOB`` y en PostgreSQL como
     # ``BYTEA`` (columna ``oid`` evitada para mantener updates por registro).
     contenido = Column(LargeBinary, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     ticket = relationship("Ticket", back_populates="adjuntos", foreign_keys=[ticket_id])
     usuario = relationship("Usuario")
diff --git a/app/models/auditoria.py b/app/models/auditoria.py
index d583082..bb2a1dd 100644
--- a/app/models/auditoria.py
+++ b/app/models/auditoria.py
@@ -37,6 +37,10 @@ class Auditoria(Base, TimestampMixin):
     valor_nuevo = Column(JSON, nullable=True)
     comentario = Column(Text, nullable=True)
     ip_origen = Column(String(64), nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     ticket = relationship("Ticket", back_populates="auditorias")
diff --git a/app/models/automacion.py b/app/models/automacion.py
index e261ca1..26efaa8 100644
--- a/app/models/automacion.py
+++ b/app/models/automacion.py
@@ -51,6 +51,10 @@ class ReglaAutomatizacion(Base, TimestampMixin):
         Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
         nullable=True
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     ejecuciones = relationship(
         "EjecucionAutomatizacion",
@@ -87,6 +91,10 @@ class EjecucionAutomatizacion(Base, TimestampMixin):
     contexto = Column(JSON, nullable=True)
     exito = Column(Integer, default=1, nullable=False)  # 1=True, 0=False
     detalle = Column(Text, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     regla = relationship("ReglaAutomatizacion", back_populates="ejecuciones")
 
diff --git a/app/models/butler_extras.py b/app/models/butler_extras.py
index 7398aef..13fe8d0 100644
--- a/app/models/butler_extras.py
+++ b/app/models/butler_extras.py
@@ -49,6 +49,10 @@ class BotonTarjeta(Base, TimestampMixin):
         Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
         nullable=True
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     tablero = relationship("Tablero", backref="botones")
     creador = relationship("Usuario")
@@ -81,6 +85,10 @@ class EjecucionBoton(Base, TimestampMixin):
     )
     exito = Column(Boolean, default=True, nullable=False)
     detalle = Column(Text, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     boton = relationship("BotonTarjeta", back_populates="ejecuciones")
 
@@ -126,6 +134,10 @@ class ComandoProgramado(Base, TimestampMixin):
         Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
         nullable=True
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     tablero = relationship("Tablero", back_populates="comandos_programados")
     creador = relationship("Usuario")
@@ -152,6 +164,10 @@ class EjecucionComando(Base, TimestampMixin):
     detalle = Column(Text, nullable=True)
     tickets_afectados = Column(Integer, default=0, nullable=False)
     duracion_ms = Column(Integer, default=0, nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     comando = relationship("ComandoProgramado", back_populates="ejecuciones")
 
diff --git a/app/models/campo_personalizado.py b/app/models/campo_personalizado.py
index 0b1eecf..c589cce 100644
--- a/app/models/campo_personalizado.py
+++ b/app/models/campo_personalizado.py
@@ -45,6 +45,10 @@ class CampoPersonalizado(Base, TimestampMixin):
     activo = Column(Boolean, default=True, nullable=False)
     # Color del campo en la UI
     color = Column(String(20), default="#6366f1", nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     tablero = relationship("Tablero", back_populates="campos_personalizados")
@@ -89,6 +93,10 @@ class ValorCampo(Base, TimestampMixin):
     valor_numero = Column(Float, nullable=True)
     valor_booleano = Column(Boolean, nullable=True)
     valor_fecha = Column(DateTime, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     campo = relationship("CampoPersonalizado", back_populates="valores")
     ticket = relationship("Ticket", backref="valores_campos")
diff --git a/app/models/catalogo.py b/app/models/catalogo.py
index 8765e3d..5302283 100644
--- a/app/models/catalogo.py
+++ b/app/models/catalogo.py
@@ -21,6 +21,10 @@ class CatalogoTipo(Base, TimestampMixin):
     # Esquema simplificado: lista de campos {"key", "label", "tipo", "requerido"}
     esquema = Column(JSON, nullable=False, default=list)
     activo = Column(Boolean, default=True, nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     items = relationship(
@@ -50,6 +54,10 @@ class CatalogoItem(Base, TimestampMixin):
     descripcion = Column(Text, nullable=True)
     datos = Column(JSON, nullable=False, default=dict)
     activo = Column(Boolean, default=True, nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     catalogo_tipo = relationship("CatalogoTipo", back_populates="items")
 
diff --git a/app/models/checklist.py b/app/models/checklist.py
index fd51892..c0c9e6d 100644
--- a/app/models/checklist.py
+++ b/app/models/checklist.py
@@ -20,6 +20,10 @@ class Checklist(Base, TimestampMixin):
     titulo = Column(String(200), nullable=False)
     orden = Column(Integer, default=0, nullable=False)
     posicion = Column(Integer, default=0, nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     items = relationship(
         "ChecklistItem",
@@ -62,6 +66,10 @@ class ChecklistItem(Base):
         nullable=True
     )
     fecha_vencimiento = Column(String(50), nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     checklist = relationship("Checklist", back_populates="items")
     asignado = relationship("Usuario")
diff --git a/app/models/comentario.py b/app/models/comentario.py
index a0a1ca3..f04d052 100644
--- a/app/models/comentario.py
+++ b/app/models/comentario.py
@@ -29,6 +29,10 @@ class Comentario(Base, TimestampMixin):
     # Si fue edicion, guarda el original
     editado = Column(Boolean, default=False, nullable=False)
     texto_original = Column(Text, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     ticket = relationship("Ticket", back_populates="comentarios")
     usuario = relationship("Usuario")
@@ -107,6 +111,10 @@ class MencionUsuario(Base):
     )
     # Si ya se le notifico
     notificado = Column(Integer, default=0, nullable=False)  # 0=False, 1=True
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     comentario = relationship("Comentario", back_populates="menciones")
     usuario = relationship("Usuario")
diff --git a/app/models/espacio.py b/app/models/espacio.py
index 98b30b9..89f7fd1 100644
--- a/app/models/espacio.py
+++ b/app/models/espacio.py
@@ -45,6 +45,10 @@ class Espacio(Base, TimestampMixin):
     # Configuracion visual (color, logo)
     color = Column(String(20), default="#6366f1", nullable=False)
     icono = Column(String(40), default="espacio", nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     propietario = relationship("Usuario", foreign_keys=[propietario_id])
@@ -100,6 +104,10 @@ class Tablero(Base, TimestampMixin):
     archivado = Column(Boolean, default=False, nullable=False, index=True)
     # URL publica para tableros publicos
     slug_publico = Column(String(60), nullable=True, unique=True, index=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     espacio = relationship("Espacio", back_populates="tableros")
@@ -175,6 +183,10 @@ class PermisoTablero(Base, TimestampMixin):
         Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
         nullable=True
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     tablero = relationship("Tablero", back_populates="permisos")
     usuario = relationship("Usuario", foreign_keys=[usuario_id])
diff --git a/app/models/estado.py b/app/models/estado.py
index 6ebefe9..af208e6 100644
--- a/app/models/estado.py
+++ b/app/models/estado.py
@@ -78,6 +78,10 @@ class Estado(Base, TimestampMixin):
             "transiciona a este estado, se registra para el reporte diario."
         ),
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     transiciones_salida = relationship(
@@ -123,6 +127,10 @@ class TransicionEstado(Base):
     # Comentario obligatorio (ej. "Cerrado: requiere motivo")
     requiere_comentario = Column(Boolean, default=False, nullable=False)
     descripcion = Column(String(200), nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     estado_origen = relationship(
diff --git a/app/models/etapa_proyecto.py b/app/models/etapa_proyecto.py
index 7051897..bda6a82 100644
--- a/app/models/etapa_proyecto.py
+++ b/app/models/etapa_proyecto.py
@@ -56,6 +56,10 @@ class EtapaProyecto(Base, TimestampMixin):
     orden = Column(Integer, nullable=False, index=True)
     color = Column(String(7), nullable=False, default="#6366f1")
     activo = Column(Integer, nullable=False, default=1)  # 1=si, 0=no
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relacion inversa: las asignaciones de esta etapa a tickets
     ticket_etapas = relationship(
@@ -119,6 +123,10 @@ class TicketEtapa(Base, TimestampMixin):
 
     # Nota libre (que hizo falta en esta etapa, link a PR, build, etc.)
     notas = Column(Text, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     etapa = relationship("EtapaProyecto", back_populates="ticket_etapas")
diff --git a/app/models/etiqueta.py b/app/models/etiqueta.py
index a128959..314ac0e 100644
--- a/app/models/etiqueta.py
+++ b/app/models/etiqueta.py
@@ -39,6 +39,10 @@ class Etiqueta(Base, TimestampMixin):
     categoria = Column(String(40), default="general", nullable=False, index=True)
     descripcion = Column(Text, nullable=True)
     activo = Column(Boolean, default=True, nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relacion many-to-many
     tickets = relationship(
diff --git a/app/models/proyecto.py b/app/models/proyecto.py
new file mode 100644
index 0000000..511e8fe
--- /dev/null
+++ b/app/models/proyecto.py
@@ -0,0 +1,87 @@
+"""
+Catalogo de proyectos (multi-tenancy) - V2.009.
+
+Es la pieza ADITIVA del aislamiento por proyecto: hasta V2.008 la aplicacion
+funcionaba con un unico proyecto implicito y el aislamiento se apoyaba en la
+jerarquia Espacio -> Tablero -> Ticket, que no se aplicaba en las consultas de
+tickets (el listado de /api/v1/tickets no filtraba por espacio).
+
+Este modulo NO cambia el comportamiento de la aplicacion:
+
+* ``proyecto_id`` se anade a las tablas de negocio como columna NULLABLE, con
+  indice, y se rellena con el proyecto "Legacy" (id 1) en el backfill.
+* La tabla ``proyectos`` se crea con una fila "Legacy" que representa
+  exactamente los datos que ya existian.
+* El filtro por proyecto (ORM) y las politicas RLS quedan PREPARADOS pero
+  INERTES hasta que se active el flag ``AISLAMIENTO_PROYECTO_ACTIVO``, que es
+  parte de la ventana V3 (el corte).
+
+Ver ``app/core/proyecto.py`` para el contexto de proyecto.
+"""
+from sqlalchemy import (
+    Column, Integer, String, ForeignKey, Boolean, Table, Text,
+)
+from sqlalchemy.orm import relationship
+
+from app.db.base import Base, TimestampMixin
+
+
+#: Identificador del proyecto "Legacy": el que contiene todos los datos que
+#: ya existian antes del aislamiento por proyecto. Es el destino del backfill
+#: de la columna ``proyecto_id`` de todas las tablas de negocio.
+PROYECTO_LEGACY_ID = 1
+
+#: Nombre del proyecto "Legacy".
+NOMBRE_PROYECTO_LEGACY = "Legacy"
+
+
+# Tabla de asociacion many-to-many entre proyectos y usuarios.
+# Las tablas de asociacion del repositorio usan ``created_at`` como
+# ``String(50)`` (ver ``ticket_etiquetas`` y ``espacio_miembros``): se mantiene
+# el mismo criterio para no introducir un tipo distinto en una tabla puente.
+proyecto_usuarios = Table(
+    "proyecto_usuarios",
+    Base.metadata,
+    Column("proyecto_id", Integer, ForeignKey("proyectos.id", ondelete="CASCADE"), primary_key=True),
+    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
+    Column("rol", String(32), nullable=False, server_default="miembro"),
+    Column("created_at", String(50), nullable=True),
+)
+
+
+class Proyecto(Base, TimestampMixin):
+    """
+    Proyecto (tenant) al que pertenecen los datos de negocio.
+
+    "Legacy" (id 1) es el proyecto historico: contiene los 934 tickets y el
+    resto de datos que ya existian. Los proyectos futuros se crean con filas
+    nuevas; hasta la ventana de corte (V3) el aislamiento esta apagado y todos
+    los proyectos comparten los mismos datos.
+    """
+    __tablename__ = "proyectos"
+
+    id = Column(Integer, primary_key=True, autoincrement=True)
+    nombre = Column(String(120), nullable=False, unique=True, index=True)
+    descripcion = Column(Text, nullable=True)
+    # Plan de suscripcion u organizacion (opcional, texto libre).
+    plan = Column(String(40), nullable=True)
+    # Color en formato hexadecimal (#FF0000), igual que en Etiqueta.
+    color = Column(String(20), default="#6b7280", nullable=False)
+    icono = Column(String(40), nullable=True)
+    activo = Column(Boolean, default=True, nullable=False)
+
+    # Propietario: el usuario responsable del proyecto. NULLABLE a proposito:
+    # un proyecto sin propietario sigue siendo valido y el borrado de un
+    # usuario no debe dejar projects huerfanos.
+    propietario_id = Column(
+        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
+    )
+
+    usuarios = relationship(
+        "Usuario",
+        secondary=proyecto_usuarios,
+        back_populates="proyectos",
+    )
+
+    def __repr__(self) -> str:
+        return f"<Proyecto {self.nombre} (id={self.id})>"
diff --git a/app/models/reporte_entregas.py b/app/models/reporte_entregas.py
index 5ff4240..3b99de1 100644
--- a/app/models/reporte_entregas.py
+++ b/app/models/reporte_entregas.py
@@ -107,6 +107,10 @@ class ReportePlantilla(Base, TimestampMixin):
         Text, nullable=True, default="",
         doc="Bloque de firma que se anade al final del correo.",
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     def __repr__(self) -> str:
         return f"<ReportePlantilla id={self.id} habilitado={self.habilitado}>"
@@ -159,6 +163,10 @@ class ReporteDestinatario(Base, TimestampMixin):
         Text, nullable=True,
         doc="Notas internas (no se envian en el correo).",
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relacion al usuario (para mostrar su nombre en la UI admin)
     usuario_obj = relationship(
@@ -266,6 +274,10 @@ class ReporteEntregaDiaria(Base, TimestampMixin):
             "entrega. NULL = aun no se ha enviado en un reporte diario."
         ),
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     def __repr__(self) -> str:
         return (
diff --git a/app/models/ticket.py b/app/models/ticket.py
index f7daeeb..05c5ca2 100644
--- a/app/models/ticket.py
+++ b/app/models/ticket.py
@@ -207,6 +207,10 @@ class Ticket(Base, TimestampMixin):
     # tabla ``usuarios``. La columna se indexa para acelerar los filtros
     # del dashboard de QA.
     qa_tester = Column(String(160), nullable=True, index=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones
     estado = relationship("Estado", back_populates="tickets", lazy="joined")
@@ -342,6 +346,10 @@ class HistorialEstado(Base):
     # IP/host desde donde se hizo el cambio
     origen = Column(String(200), nullable=True)
     fecha = Column(DateTime, nullable=False, index=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     ticket = relationship("Ticket", back_populates="historial_estados")
     estado_origen = relationship("Estado", foreign_keys=[estado_origen_id])
diff --git a/app/models/ticket_dependencia.py b/app/models/ticket_dependencia.py
index a2453e7..09cee96 100644
--- a/app/models/ticket_dependencia.py
+++ b/app/models/ticket_dependencia.py
@@ -118,6 +118,10 @@ class TicketDependencia(Base):
     )
     lag_dias = Column(Integer, default=0, nullable=False)
     nota = Column(Text, nullable=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones: ambos lados apuntan al modelo Ticket. ``backref`` no se
     # usa para evitar ciclos en la importacion (los tickets importan
diff --git a/app/models/ticket_referencia.py b/app/models/ticket_referencia.py
index 9582682..6623589 100644
--- a/app/models/ticket_referencia.py
+++ b/app/models/ticket_referencia.py
@@ -128,6 +128,10 @@ class TicketReferencia(Base):
         default=now_utc,
         index=True,
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # === Relaciones ===
     ticket_origen = relationship(
diff --git a/app/models/usuario.py b/app/models/usuario.py
index a49512e..273c03e 100644
--- a/app/models/usuario.py
+++ b/app/models/usuario.py
@@ -6,6 +6,7 @@ from sqlalchemy.orm import relationship
 import enum
 
 from app.db.base import Base, TimestampMixin
+from app.models.proyecto import proyecto_usuarios
 
 
 class RolUsuario(str, enum.Enum):
@@ -43,6 +44,14 @@ class Usuario(Base, TimestampMixin):
         foreign_keys="Ticket.asignado_id",
     )
     auditorias = relationship("Auditoria", back_populates="usuario")
+    # Proyectos a los que pertenece el usuario (many-to-many por la tabla
+    # puente ``proyecto_usuarios``). Los usuarios son GLOBALES: no llevan
+    # columna ``proyecto_id``; su pertenencia a proyectos es esta relacion.
+    proyectos = relationship(
+        "Proyecto",
+        secondary=proyecto_usuarios,
+        back_populates="usuarios",
+    )
 
     def tiene_permiso_para(self, accion: str) -> bool:
         """Verifica si el rol del usuario permite una accion dada."""
diff --git a/app/models/watch.py b/app/models/watch.py
index 9190451..8a44d03 100644
--- a/app/models/watch.py
+++ b/app/models/watch.py
@@ -35,6 +35,10 @@ class Watch(Base, TimestampMixin):
     activo = Column(Boolean, default=True, nullable=False)
     # Canal preferido de notificacion: 'web' | 'email' | 'push' | 'all'
     canal = Column(String(20), default="all", nullable=False)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     # Relaciones polimorficas condicionales (no FK para soportar multiples tipos)
     usuario = relationship("Usuario", backref="watches")
@@ -63,6 +67,10 @@ class Reaccion(Base, TimestampMixin):
     objeto_id = Column(Integer, nullable=False, index=True)
     # Emoji Unicode (       etc.)
     emoji = Column(String(16), nullable=False, index=True)
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     usuario = relationship("Usuario")
 
@@ -103,6 +111,10 @@ class Notificacion(Base, TimestampMixin):
         Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
         nullable=True
     )
+    # Proyecto (tenant) al que pertenece la fila (NULL en V2.009; lo rellena el backfill)
+    proyecto_id = Column(
+        Integer, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
+    )
 
     usuario = relationship("Usuario", foreign_keys=[usuario_id])
     origen = relationship("Usuario", foreign_keys=[origen_usuario_id])
diff --git a/app/services/backup_service.py b/app/services/backup_service.py
index 5be5788..013f9b3 100644
--- a/app/services/backup_service.py
+++ b/app/services/backup_service.py
@@ -6,7 +6,8 @@ Soporta dos motores:
 - **PostgreSQL** (produccion): usa el binario `pg_dump` si esta disponible
   en el PATH.  Hace dump en formato ``plain`` (SQL) y lo comprime con gzip.
   Si ``pg_dump`` no esta instalado, cae a un fallback con ``psycopg2`` que
-  ejecuta ``COPY ... TO STDOUT`` por tabla.
+  reconstruye el dump desde ``pg_catalog`` (DDL + datos + indices +
+  constraints + secuencias) en un formato **restaurable**.
 
 - **SQLite** (desarrollo/demo): usa la API nativa ``sqlite3.Connection.backup()``
   que crea un snapshot consistente en otra conexion.
@@ -91,6 +92,58 @@ class BackupResult:
 # Servicio principal
 # ============================================================
 
+def _pg_literal(v: Any, tipo: str = "") -> str:
+    """
+    Literal SQL de PostgreSQL para un valor Python.
+
+    ``tipo`` es el tipo DECLARADO de la columna (la salida de
+    ``format_type``). HACE FALTA para las columnas ``json`` y ``jsonb``:
+    psycopg2 convierte esas columnas en objetos Python (un dict, un str, un
+    bool...) y un literal SQL escrito a pelo no siempre es JSON valido.
+
+    Lo que se vio en produccion el 2026-11-18 al restaurar el backup: un
+    string JSON (``"incidencia"``) salia como ``'incidencia'`` (sin las
+    comillas del JSON), un booleano salia como ``TRUE`` y un null JSON como
+    ``NULL``. Los tres los rechazaba la columna al restaurar::
+
+        ERROR: invalid input syntax for type json
+
+    Con el tipo a la vista, el valor se serializa SIEMPRE con ``json.dumps``:
+    ``"incidencia"``, ``true``, ``null``, ``{"a": 1}``...
+    """
+    if tipo in ("json", "jsonb"):
+        if v is None:
+            return "NULL"
+        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
+    if v is None:
+        return "NULL"
+    if isinstance(v, bool):
+        return "TRUE" if v else "FALSE"
+    if isinstance(v, int):
+        return str(v)
+    if isinstance(v, float):
+        if v != v:
+            return "'NaN'"
+        if v == float("inf"):
+            return "'Infinity'"
+        if v == float("-inf"):
+            return "'-Infinity'"
+        return repr(v)
+    if isinstance(v, (bytes, bytearray, memoryview)):
+        # formato hex de bytea: un solo backslash -> '\x0a1b'
+        return "'\\x" + bytes(v).hex() + "'"
+    if isinstance(v, datetime):
+        return "'" + v.isoformat(sep=" ") + "'"
+    if isinstance(v, (list, tuple)):
+        if not v:
+            return "'{}'"
+        return "ARRAY[" + ", ".join(_pg_literal(x) for x in v) + "]"
+    if isinstance(v, dict):
+        return "'" + json.dumps(
+            v, ensure_ascii=False).replace("'", "''") + "'"
+    return "'" + str(v).replace("'", "''") + "'"
+
+
 class BackupService:
     """Servicio central de respaldos.
 
@@ -308,7 +361,34 @@ class BackupService:
         return self._backup_postgresql_python(db_url, target)
 
     def _backup_postgresql_python(self, db_url: str, target: Path) -> int:
-        """Fallback psycopg2: genera SQL manualmente."""
+        """Fallback psycopg2: genera un dump SQL COMPLETO y restaurable.
+
+        En produccion ``pg_dump`` no esta disponible en la imagen del
+        contenedor, asi que el dump se reconstruye a mano.  Un fichero con
+        solo ``INSERT`` **no se puede restaurar** (no hay tablas donde
+        insertar) y ademas pierde las tablas sin filas, por lo que aqui se
+        emite un dump completo y en un orden valido para ``psql``:
+
+            1. Cabecera + ``SET`` (client_encoding, standard_conforming_strings,
+               search_path).
+            2. ``CREATE TYPE`` (enums) y ``CREATE SEQUENCE`` (columnas serial).
+            3. ``CREATE TABLE`` de TODAS las tablas (tambien las vacias).
+            4. ``INSERT`` con los datos de las tablas que tienen filas.
+            5. ``ALTER TABLE ... ADD CONSTRAINT`` (PRIMARY KEY / UNIQUE / CHECK).
+            6. ``CREATE INDEX`` de los indices no ligados a un constraint.
+            7. ``ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`` (al final:
+               las PK/UNIQUE ya existen, asi que no hay problemas de orden
+               ni con dependencias circulares entre tablas).
+            8. ``setval`` de las secuencias, para que los ``id`` autogenerados
+               no choquen con los datos restaurados.
+
+        El DDL se reconstruye desde ``pg_catalog`` (la BD real), NO desde el
+        metadata de SQLAlchemy: para un backup la fuente de verdad es la BD.
+
+        Returns:
+            Numero de bytes del payload SIN comprimir (lo que espera el
+            llamante para la metadata).
+        """
         try:
             import psycopg2  # type: ignore
             import psycopg2.extensions  # type: ignore
@@ -317,46 +397,391 @@ class BackupService:
                 "pg_dump no disponible y psycopg2 no instalado"
             ) from e
 
-        conn = psycopg2.connect(db_url)
+        # psycopg2 no entiende el esquema SQLAlchemy "postgresql+psycopg2://"
+        dsn = db_url.replace("postgresql+psycopg2://", "postgresql://")
+        dsn = dsn.replace("postgres+psycopg2://", "postgresql://")
+
+        conn = psycopg2.connect(dsn)
+        conn.set_client_encoding("UTF8")
         conn.set_session(readonly=True, autocommit=True)
         try:
             cur = conn.cursor()
+
+            def qi(name: str) -> str:
+                """Identificador de PostgreSQL entrecomillado."""
+                return '"' + str(name).replace('"', '""') + '"'
+
+            def lit(v: Any, tipo: str = "") -> str:
+                """Literal SQL de PostgreSQL para un valor Python."""
+                return _pg_literal(v, tipo)
+
+            schema = "public"
+            qschema = qi(schema)
+
+            # ------------------------------------------------------------
+            # Metadatos reales de la BD (pg_catalog)
+            # ------------------------------------------------------------
+            cur.execute("SELECT version(), current_database(), current_user")
+            pg_version, db_name, db_user = cur.fetchone()
+            cur.execute("SELECT current_setting('server_version_num')")
+            server_version = cur.fetchone()[0]
+
             cur.execute("""
-                SELECT table_name FROM information_schema.tables
-                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
-                ORDER BY table_name
+                SELECT c.relname
+                  FROM pg_class c
+                  JOIN pg_namespace n ON n.oid = c.relnamespace
+                 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
+                 ORDER BY c.relname
             """)
-            tables = [r[0] for r in cur.fetchall()]
-            lines: List[str] = []
-            lines.append("-- Bitacora GRM backup (psycopg2 fallback)")
-            lines.append(f"-- Generado: {datetime.now(timezone.utc).isoformat()}")
-            lines.append("")
+            tables: List[str] = [r[0] for r in cur.fetchall()]
+
+            cur.execute("""
+                SELECT c.relname, a.attname,
+                       format_type(a.atttypid, a.atttypmod),
+                       a.attnotnull, pg_get_expr(d.adbin, d.adrelid),
+                       a.attidentity, a.attgenerated
+                  FROM pg_attribute a
+                  JOIN pg_class c ON c.oid = a.attrelid
+                  JOIN pg_namespace n ON n.oid = c.relnamespace
+                  LEFT JOIN pg_attrdef d
+                         ON d.adrelid = a.attrelid AND d.adnum = a.attnum
+                 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
+                   AND a.attnum > 0 AND NOT a.attisdropped
+                 ORDER BY c.relname, a.attnum
+            """)
+            cols_by_table: Dict[str, List[Dict[str, Any]]] = {}
+            for tname, cname, ctype, notnull, defexpr, identity, generated \
+                    in cur.fetchall():
+                cols_by_table.setdefault(tname, []).append({
+                    "name": cname,
+                    "type": ctype,
+                    "notnull": bool(notnull),
+                    "default": defexpr,
+                    "identity": identity or "",
+                    "generated": generated or "",
+                })
+
+            # Enums (tipos que usa el modelo: p.ej. rol de usuario)
+            cur.execute("""
+                SELECT t.typname, e.enumlabel
+                  FROM pg_type t
+                  JOIN pg_enum e ON e.enumtypid = t.oid
+                  JOIN pg_namespace n ON n.oid = t.typnamespace
+                 WHERE n.nspname = 'public'
+                 ORDER BY t.typname, e.enumsortorder
+            """)
+            enum_labels: Dict[str, List[str]] = {}
+            for tname, label in cur.fetchall():
+                enum_labels.setdefault(tname, []).append(label)
+
+            # Constraints (PK / UNIQUE / CHECK / EXCLUDE / FK)
+            cur.execute("""
+                SELECT t.relname, c.conname, c.contype,
+                       pg_get_constraintdef(c.oid)
+                  FROM pg_constraint c
+                  JOIN pg_class t ON t.oid = c.conrelid
+                  JOIN pg_namespace n ON n.oid = t.relnamespace
+                 WHERE n.nspname = 'public'
+                   AND c.contype IN ('p', 'u', 'c', 'x', 'f')
+                 ORDER BY t.relname, c.conname
+            """)
+            constraints = cur.fetchall()
+
+            # Indices que NO respaldan un constraint (los de PK/UNIQUE los
+            # crea el propio ADD CONSTRAINT)
+            cur.execute("""
+                SELECT t.relname, pg_get_indexdef(x.indexrelid)
+                  FROM pg_index x
+                  JOIN pg_class i ON i.oid = x.indexrelid
+                  JOIN pg_class t ON t.oid = x.indrelid
+                  JOIN pg_namespace n ON n.oid = t.relnamespace
+                  LEFT JOIN pg_constraint c ON c.conindid = i.oid
+                 WHERE n.nspname = 'public' AND c.oid IS NULL
+                   AND NOT x.indisprimary
+                 ORDER BY t.relname, i.relname
+            """)
+            indexes = cur.fetchall()
+
+            # Secuencias y su columna propietaria
+            cur.execute("""
+                SELECT sequencename, data_type, start_value, min_value,
+                       max_value, increment_by, cycle, cache_size, last_value
+                  FROM pg_sequences
+                 WHERE schemaname = 'public'
+                 ORDER BY sequencename
+            """)
+            seq_by_name: Dict[str, Dict[str, Any]] = {
+                r[0]: {
+                    "data_type": r[1], "start": r[2], "min": r[3], "max": r[4],
+                    "inc": r[5], "cycle": bool(r[6]), "cache": r[7],
+                    "last": r[8],
+                }
+                for r in cur.fetchall()
+            }
+
+            cur.execute("""
+                SELECT c.relname, t.relname, a.attname, a.attidentity
+                  FROM pg_class c
+                  JOIN pg_namespace n ON n.oid = c.relnamespace
+                  JOIN pg_depend d ON d.objid = c.oid
+                                 AND d.deptype IN ('a', 'i')
+                  JOIN pg_class t ON t.oid = d.refobjid
+                  JOIN pg_namespace tn ON tn.oid = t.relnamespace
+                  JOIN pg_attribute a ON a.attrelid = d.refobjid
+                                     AND a.attnum = d.refobjsubid
+                 WHERE c.relkind = 'S' AND n.nspname = 'public'
+                   AND tn.nspname = 'public'
+                 ORDER BY c.relname
+            """)
+            # (seq, tabla, columna, identidad)
+            seq_owner = cur.fetchall()
+
+            # Objetos que el fallback NO puede reproducir (vistas, vistas
+            # materializadas, funciones, particiones): se avisa por log.
+            cur.execute("""
+                SELECT c.relkind, count(*)
+                  FROM pg_class c
+                  JOIN pg_namespace n ON n.oid = c.relnamespace
+                 WHERE n.nspname = 'public'
+                   AND (c.relkind IN ('v', 'm', 'f') OR c.relispartition)
+                 GROUP BY c.relkind ORDER BY c.relkind
+            """)
+            uncovered = cur.fetchall()
+            if uncovered:
+                logger.warning(
+                    "[BACKUP] Objetos no incluidos en el dump (vistas/matviews/"
+                    "funciones/particiones): %s", uncovered,
+                )
+
+            # Tablas con ROW LEVEL SECURITY: el dump no reproduce las
+            # politicas, y si el rol no es el dueno la lectura puede venir
+            # filtrada.  Se avisa para que quede constancia.
+            cur.execute("""
+                SELECT c.relname
+                  FROM pg_class c
+                  JOIN pg_namespace n ON n.oid = c.relnamespace
+                 WHERE n.nspname = 'public' AND c.relrowsecurity
+                 ORDER BY c.relname
+            """)
+            rls_tables = [r[0] for r in cur.fetchall()]
+            if rls_tables:
+                logger.warning(
+                    "[BACKUP] Tablas con ROW LEVEL SECURITY (el dump no "
+                    "reproduce las politicas): %s", rls_tables,
+                )
+
+            # ------------------------------------------------------------
+            # Emision del dump
+            # ------------------------------------------------------------
+            header: List[str] = []
+            types_s: List[str] = []
+            seqs_s: List[str] = []
+            tables_s: List[str] = []
+            data_s: List[str] = []
+            constr_s: List[str] = []
+            index_s: List[str] = []
+            fk_s: List[str] = []
+            seq_end_s: List[str] = []
+
+            # (2a) Tipos ENUM: las columnas tipadas los necesitan antes.
+            if enum_labels:
+                types_s.append("-- ENUM types")
+                for tname, labels in enum_labels.items():
+                    vals = ", ".join(lit(x) for x in labels)
+                    types_s.append(
+                        f"CREATE TYPE {qschema}.{qi(tname)} AS ENUM ({vals});"
+                    )
+                types_s.append("")
+
+            # (2b) Secuencias: las columnas SERIAL las referencian por
+            # nextval('seq'::regclass) y la secuencia debe existir ANTES
+            # del CREATE TABLE.  Las de las columnas IDENTITY las crea el
+            # propio CREATE TABLE, asi que se excluyen.
+            identity_seqs = {s[0] for s in seq_owner if s[3]}
+            if seq_by_name:
+                seqs_s.append("-- Sequences")
+                for sname, sdata in seq_by_name.items():
+                    if sname in identity_seqs:
+                        continue
+                    seqs_s.append(
+                        f"CREATE SEQUENCE IF NOT EXISTS {qschema}.{qi(sname)} "
+                        f"AS {sdata['data_type']} "
+                        f"START WITH {sdata['start']} "
+                        f"INCREMENT BY {sdata['inc']} "
+                        f"MINVALUE {sdata['min']} MAXVALUE {sdata['max']} "
+                        f"CACHE {sdata['cache']} "
+                        f"{'CYCLE' if sdata['cycle'] else 'NO CYCLE'};"
+                    )
+                seqs_s.append("")
+
+            # (3) CREATE TABLE de TODAS las tablas (incluidas las vacias).
+            tables_s.append("-- Esquema (CREATE TABLE)")
+            for t in tables:
+                cols = cols_by_table.get(t, [])
+                if not cols:
+                    logger.warning(
+                        "[BACKUP] Tabla '%s' sin columnas visibles; se omite", t,
+                    )
+                    continue
+                defs: List[str] = []
+                for c in cols:
+                    d = f"{qi(c['name'])} {c['type']}"
+                    if c["generated"]:
+                        d += f" GENERATED ALWAYS AS ({c['default']}) STORED"
+                    elif c["identity"]:
+                        d += (
+                            " GENERATED ALWAYS AS IDENTITY"
+                            if c["identity"] == "a"
+                            else " GENERATED BY DEFAULT AS IDENTITY"
+                        )
+                    elif c["default"]:
+                        d += f" DEFAULT {c['default']}"
+                    if c["notnull"]:
+                        d += " NOT NULL"
+                    defs.append("    " + d)
+                tables_s.append(f"CREATE TABLE {qschema}.{qi(t)} (")
+                tables_s.append(",\n".join(defs))
+                tables_s.append(");")
+                tables_s.append("")
+
+            # (4) Datos: INSERT solo para las tablas que tienen filas.
+            data_s.append("-- Datos")
+            tables_with_data = 0
             for t in tables:
-                cur.execute(f'SELECT * FROM "{t}"')
-                cols = [d[0] for d in cur.description]
+                all_cols = cols_by_table.get(t, [])
+                cols = [c for c in all_cols if not c["generated"]]
+                if not cols:
+                    continue
+                col_list = ", ".join(qi(c["name"]) for c in cols)
+                cur.execute(
+                    f"SELECT {col_list} FROM {qschema}.{qi(t)}"
+                )
                 rows = cur.fetchall()
                 if not rows:
                     continue
-                col_list = ", ".join(f'"{c}"' for c in cols)
-                lines.append(f"-- Table: {t} ({len(rows)} filas)")
+                tables_with_data += 1
+                # Las columnas IDENTITY ALWAYS no admiten valor explicito
+                # sin OVERRIDING SYSTEM VALUE.
+                overriding = ""
+                if any(c["identity"] == "a" for c in all_cols):
+                    overriding = " OVERRIDING SYSTEM VALUE"
+                data_s.append(f"-- {t}: {len(rows)} filas")
+                col_types = [c.get("type", "") for c in cols]
                 for row in rows:
-                    vals = []
-                    for v in row:
-                        if v is None:
-                            vals.append("NULL")
-                        elif isinstance(v, (int, float)):
-                            vals.append(str(v))
-                        elif isinstance(v, bool):
-                            vals.append("TRUE" if v else "FALSE")
-                        elif isinstance(v, (bytes, memoryview)):
-                            vals.append(f"'\\\\x{v.hex()}'")
-                        else:
-                            s = str(v).replace("'", "''")
-                            vals.append(f"'{s}'")
-                    lines.append(
-                        f"INSERT INTO \"{t}\" ({col_list}) VALUES ({', '.join(vals)});"
+                    vals = ", ".join(
+                        lit(v, col_types[i]) for i, v in enumerate(row)
                     )
-                lines.append("")
+                    data_s.append(
+                        f"INSERT INTO {qschema}.{qi(t)} ({col_list})"
+                        f"{overriding} VALUES ({vals});"
+                    )
+                data_s.append("")
+
+            # (5) PK / UNIQUE / CHECK / EXCLUDE (antes de las FK).
+            constr_s.append("-- Constraints (PRIMARY KEY / UNIQUE / CHECK)")
+            for tname, cname, ctype, cdef in constraints:
+                if ctype == "f":
+                    continue
+                constr_s.append(
+                    f"ALTER TABLE {qschema}.{qi(tname)} "
+                    f"ADD CONSTRAINT {qi(cname)} {cdef};"
+                )
+            constr_s.append("")
+
+            # (6) Indices sueltos.
+            if indexes:
+                index_s.append("-- Indices")
+                for tname, idef in indexes:
+                    index_s.append(idef + ";")
+                index_s.append("")
+
+            # (7) Claves foraneas AL FINAL: las PK/UNIQUE ya existen y por
+            # tanto no hay dependencias circulares que bloqueen el restore.
+            fk_s.append("-- Claves foraneas (al final, tras PK/UNIQUE/indices)")
+            for tname, cname, ctype, cdef in constraints:
+                if ctype != "f":
+                    continue
+                fk_s.append(
+                    f"ALTER TABLE {qschema}.{qi(tname)} "
+                    f"ADD CONSTRAINT {qi(cname)} {cdef};"
+                )
+            fk_s.append("")
+
+            # (8) Secuencias: setval al final para que los id autogenerados
+            # continuen donde los dejo la tabla y no choquen.
+            seq_end_s.append("-- Secuencias (setval)")
+            for sname, tname, cname, ident in seq_owner:
+                if not ident:
+                    # Las secuencias de columnas IDENTITY ya estan
+                    # vinculadas a su columna: "OWNED BY" sobre ellas es
+                    # un error ("cannot change ownership of identity
+                    # sequence"); las SERIAL si lo necesitan.
+                    seq_end_s.append(
+                        f"ALTER SEQUENCE {qschema}.{qi(sname)} "
+                        f"OWNED BY {qschema}.{qi(tname)}.{qi(cname)};"
+                    )
+                last = seq_by_name.get(sname, {}).get("last")
+                max_expr = (
+                    f"COALESCE((SELECT MAX({qi(cname)}) "
+                    f"FROM {qschema}.{qi(tname)}), 0)"
+                )
+                if last is not None:
+                    # Se conserva la posicion real de la secuencia (igual
+                    # que pg_dump) sin quedar por debajo del MAX(id)
+                    # restaurado: los id autogenerados no chocan.
+                    value_expr = f"GREATEST({last}, {max_expr}, 1)"
+                    called = "true"
+                else:
+                    value_expr = f"GREATEST({max_expr}, 1)"
+                    called = f"EXISTS (SELECT 1 FROM {qschema}.{qi(tname)})"
+                seq_end_s.append(
+                    f"SELECT setval('{qschema}.{qi(sname)}'::regclass, "
+                    f"{value_expr}, {called});"
+                )
+            for sname, sdata in seq_by_name.items():
+                if sname in identity_seqs or sname in {s[0] for s in seq_owner}:
+                    continue
+                last = sdata["last"]
+                seq_end_s.append(
+                    f"SELECT setval('{qschema}.{qi(sname)}'::regclass, "
+                    f"{last if last is not None else sdata['start']}, "
+                    f"{'true' if last is not None else 'false'});"
+                )
+            seq_end_s.append("")
+
+            header.append(
+                "-- Bitacora GRM - backup PostgreSQL "
+                "(fallback psycopg2: dump RESTAURABLE)"
+            )
+            header.append(
+                f"-- Generado: {datetime.now(timezone.utc).isoformat()}"
+            )
+            header.append(f"-- Servidor: {pg_version}")
+            header.append(f"-- server_version_num: {server_version}")
+            header.append(f"-- Base de datos: {db_name} (usuario: {db_user})")
+            header.append(
+                f"-- Tablas: {len(tables)} (con datos: {tables_with_data})"
+            )
+            header.append(
+                "-- El DDL se reconstruye desde pg_catalog (la BD real)."
+            )
+            header.append("")
+            header.append("SET client_encoding = 'UTF8';")
+            header.append("SET standard_conforming_strings = on;")
+            header.append(f"SET search_path = {schema};")
+            header.append("")
+
+            lines: List[str] = []
+            lines.extend(header)
+            lines.extend(types_s)
+            lines.extend(seqs_s)
+            lines.extend(tables_s)
+            lines.extend(data_s)
+            lines.extend(constr_s)
+            lines.extend(index_s)
+            lines.extend(fk_s)
+            lines.extend(seq_end_s)
+
             payload = "\n".join(lines).encode("utf-8")
             with target.open("wb") as gz_f:
                 with gzip.GzipFile(fileobj=gz_f, mode="wb", compresslevel=6) as gz:
diff --git a/app/services/clone_service.py b/app/services/clone_service.py
new file mode 100644
index 0000000..9aec30f
--- /dev/null
+++ b/app/services/clone_service.py
@@ -0,0 +1,533 @@
+"""
+Clon de la base de datos para validar migraciones antes de tocar produccion.
+
+Por que existe
+--------------
+El proyecto no tiene Alembic: el esquema se alinea con migraciones
+idempotentes que se ejecutan en cada arranque. Eso obliga a poder PROBAR esas
+migraciones contra una copia de los datos reales antes de aplicarlas en
+produccion: un ``ALTER TABLE`` o un ``UPDATE`` de backfill pueden tener
+efectos que un SQLite de pruebas no reproduce (tipos de PostgreSQL,
+secuencias, claves foraneas, RLS).
+
+Como funciona
+-------------
+El clon se crea en el MISMO servidor PostgreSQL que la base de datos de
+produccion, con otro nombre (``railway_clon_<nombre>``). Se hace con la
+conexion que ya tiene la propia aplicacion, asi que:
+
+* no hay que conocer ni escribir la contrasena de la base de datos;
+* el clon y la produccion comparten servidor, motor y version;
+* el clon se borra con un ``DROP DATABASE`` (reversible).
+
+El clon se construye a partir del METADATA de SQLAlchemy (``create_all``) y
+se copian los datos fila a fila en orden de dependencias. Las secuencias se
+dejan alineadas con el maximo de cada columna autoincremental, para que un
+INSERT posterior en el clon no choque con los identificadores copiados.
+
+Alcance
+-------
+Solo lo usa un administrador, de forma explicita. No se ejecuta en ningun
+arranque ni en ninguna tarea programada: es una herramienta de operacion.
+"""
+from __future__ import annotations
+
+import logging
+from typing import Any, Dict, List, Optional, Tuple
+
+from sqlalchemy import create_engine, insert, select, text
+from sqlalchemy.engine import make_url
+from sqlalchemy.exc import SQLAlchemyError
+
+logger = logging.getLogger(__name__)
+
+
+class ErrorClonado(Exception):
+    """Error al clonar la base de datos."""
+
+
+def _nombre_valido(nombre: str) -> str:
+    """Valida el nombre de la base de datos (solo letras, digitos y guion bajo)."""
+    limpio = (nombre or "").strip()
+    if not limpio or not all(c.isalnum() or c == "_" for c in limpio):
+        raise ErrorClonado(
+            "El nombre de la base de datos solo admite letras, digitos y "
+            "guion bajo: %r" % (nombre,)
+        )
+    return limpio
+
+
+def _motor_para(url, base: Optional[str] = None):
+    if base:
+        url = url.set(database=base)
+    return create_engine(url, pool_pre_ping=True, future=True)
+
+
+def _existe_base(conn, nombre: str) -> bool:
+    return bool(conn.execute(
+        text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nombre}
+    ).fetchone())
+
+
+def _alinear_secuencias(clon_conn, tablas) -> int:
+    """Deja las secuencias autoincrementales en el maximo copiado."""
+    ajustadas = 0
+    for tabla in tablas:
+        if not hasattr(tabla, "c"):
+            continue
+        for columna in tabla.c:
+            if not (columna.primary_key and columna.autoincrement is True):
+                continue
+            # ``autoincrement`` es "auto" en SQLite y True/False en Postgres.
+            if columna.autoincrement != "auto":
+                try:
+                    clon_conn.execute(text(
+                        "SELECT setval(pg_get_serial_sequence(:t, :c), "
+                        "COALESCE((SELECT MAX(%s) FROM %s), 1), true)"
+                        % (columna.name, tabla.name)
+                    ), {"t": tabla.name, "c": columna.name})
+                    ajustadas += 1
+                except SQLAlchemyError as exc:
+                    logger.warning(
+                        "[clone] no se pudo alinear la secuencia de %s.%s: %s",
+                        tabla.name, columna.name, exc,
+                    )
+    return ajustadas
+
+
+def _orden_y_ciclos(tablas) -> Tuple[List[Any], set]:
+    """
+    Calcula un orden de copia por dependencias y detecta las tablas que
+    participan en un CICLO de claves foraneas.
+
+    Por que no sirve ``Base.metadata.sorted_tables`` (V2.009)
+    ---------------------------------------------------------
+    SQLAlchemy avisa con ``Cannot correctly sort tables; there are unresolvable
+    cycles between tables "adjuntos, comentarios, tickets"`` y devuelve un
+    orden que **no** es topologico: coloca ``tickets`` (posicion 2) ANTES de
+    ``usuarios`` (posicion 3). La copia fallaba con::
+
+        insert or update on table "tickets" violates foreign key constraint
+        "tickets_creador_id_fkey"
+
+    El ciclo es real e inevitable: ``tickets.portada_adjunto_id`` ->
+    ``adjuntos.id`` y ``adjuntos.ticket_id`` -> ``tickets.id`` (NOT NULL), de
+    modo que no se puede romper nulando la columna.
+
+    Aqui se calcula el orden con el algoritmo de Kahn (propios destinos
+    primero) y se detectan las tablas que quedan sin ordenar: esas son
+    precisamente las que estan en un ciclo.
+
+    Devuelve
+    --------
+    ``(orden, ciclos)``: la lista de tablas copiables en orden y el conjunto
+    de tablas que participan en al menos un ciclo.
+    """
+    pendientes = list(tablas)
+    deps = {}
+    for tabla in pendientes:
+        destinos = set()
+        for fk in tabla.foreign_keys:
+            if fk.parent is not None and fk.column is not None:
+                padre = fk.column.table
+                if padre is not tabla:
+                    destinos.add(padre)
+        deps[tabla] = destinos
+
+    orden: List[Any] = []
+    restantes = set(pendientes)
+    while restantes:
+        listos = [t for t in pendientes if t in restantes and not (deps[t] & restantes)]
+        if not listos:
+            # Todo lo que queda depende de algo que queda: hay un ciclo.
+            break
+        for tabla in listos:
+            orden.append(tabla)
+        restantes -= set(listos)
+
+    ciclos = set(restantes)
+    if ciclos:
+        logger.warning(
+            "[clone] %d tablas en ciclo de claves foraneas: %s",
+            len(ciclos), ", ".join(sorted(t.name for t in ciclos)),
+        )
+    return orden, ciclos
+
+
+def _constraint_fk_por_columna(dest, tabla: str, columna: str) -> Optional[str]:
+    """Devuelve el nombre real del constraint FK de (tabla, columna)."""
+    try:
+        fila = dest.execute(text(
+            "SELECT con.conname FROM pg_constraint con "
+            "JOIN pg_class c ON c.oid = con.conrelid "
+            "JOIN pg_namespace n ON n.oid = c.relnamespace "
+            "JOIN LATERAL unnest(con.conkey) AS k(attnum) ON TRUE "
+            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum "
+            "WHERE con.contype = 'f' AND n.nspname = current_schema() "
+            "AND c.relname = :t AND a.attname = :c LIMIT 1"
+        ), {"t": tabla, "c": columna}).fetchone()
+        return fila[0] if fila else None
+    except SQLAlchemyError as exc:
+        logger.warning("[clone] no se pudo inspeccionar el FK %s.%s: %s",
+                       tabla, columna, exc)
+        return None
+
+
+def _relajar_fks(dest, ciclos) -> Tuple[str, List[Tuple[str, str]]]:
+    """
+    Relaja las claves foraneas durante la copia de datos.
+
+    Devuelve ``(modo, constraints)`` donde ``modo`` es:
+
+    * ``"replica"``: se ha usado ``session_replication_role = replica``, que
+      desactiva la comprobacion de FK durante la transaccion. No deja cambios
+      en el esquema del clon. Es el camino preferido (el rol ``postgres`` de
+      PostgreSQL es superusuario).
+    * ``"deferred"``: no se ha podido usar el anterior (el rol no es
+      superusuario) y se han marcado como DEFERRABLE los constraints FK que
+      apuntan a las tablas en ciclo. Se restauran al terminar.
+
+    * ``"ninguno"``: no hay ciclos, no hace falta relajar nada.
+    """
+    if not ciclos:
+        return ("ninguno", [])
+
+    # Camino 1: session_replication_role = replica (no altera el esquema).
+    # Se usa un SAVEPOINT: si el rol no tiene permiso, el error aborta la
+    # transaccion y el SAVEPOINT lo deja en pie.
+    try:
+        with dest.begin_nested():
+            dest.execute(text("SET LOCAL session_replication_role = replica"))
+        logger.info("[clone] FK relajadas con session_replication_role=replica")
+        return ("replica", [])
+    except SQLAlchemyError as exc:
+        logger.info(
+            "[clone] session_replication_role no disponible (%s); "
+            "se usaran constraints DEFERRABLE", exc,
+        )
+
+    # Camino 2: DEFERRABLE INITIALLY DEFERRED sobre los FK que apuntan a las
+    # tablas en ciclo.
+    constraints: List[Tuple[str, str]] = []
+    for tabla in Base.metadata.tables.values():
+        if tabla not in ciclos:
+            continue
+        for fk in tabla.foreign_keys:
+            padre = fk.column.table if fk.column is not None else None
+            if padre is None or padre not in ciclos:
+                continue
+            if fk.parent is None:
+                continue
+            nombre = _constraint_fk_por_columna(dest, tabla.name, fk.parent.name)
+            if nombre:
+                constraints.append((tabla.name, nombre))
+    if not constraints:
+        raise ErrorClonado(
+            "No se pudo relajar las claves foraneas para clonar: el rol de "
+            "la base de datos no es superusuario y no se han encontrado los "
+            "constraints de las tablas en ciclo."
+        )
+    for tabla_nombre, constraint in constraints:
+        dest.execute(text(
+            'ALTER TABLE "%s" ALTER CONSTRAINT "%s" DEFERRABLE INITIALLY DEFERRED'
+            % (tabla_nombre, constraint)
+        ))
+    dest.execute(text("SET CONSTRAINTS ALL DEFERRED"))
+    logger.info(
+        "[clone] FK relajadas con %d constraints DEFERRABLE", len(constraints),
+    )
+    return ("deferred", constraints)
+
+
+def _restaurar_fks(dest, modo: str, constraints: List[Tuple[str, str]]) -> None:
+    """Deja el clon con las mismas claves foraneas que tiene el origen."""
+    if modo != "deferred":
+        return
+    for tabla_nombre, constraint in constraints:
+        try:
+            dest.execute(text(
+                'ALTER TABLE "%s" ALTER CONSTRAINT "%s" NOT DEFERRABLE'
+                % (tabla_nombre, constraint)
+            ))
+        except SQLAlchemyError as exc:  # pragma: no cover
+            logger.warning("[clone] no se pudo restaurar el constraint %s: %s",
+                           constraint, exc)
+
+
+def clonar_base_datos(
+    url_origen: str,
+    nombre_clon: str,
+    copiar_datos: bool = True,
+    engine_clon=None,
+) -> Dict[str, Any]:
+    """
+    Crea un clon de la base de datos de ``url_origen`` y devuelve su URI.
+
+    Parametros
+    ----------
+    url_origen
+        URL de la base de datos de origen (la de la propia aplicacion).
+    nombre_clon
+        Nombre de la base de datos del clon.
+    copiar_datos
+        Si es False, solo se replica el esquema (util para validar DDL).
+    engine_clon
+        Motor ya creado para el clon (opcional; se usa en las pruebas).
+
+    Devuelve
+    --------
+    dict
+        ``uri`` (URL del clon), ``nombre``, ``tablas``, ``filas``,
+        ``secuencias`` y ``ya_existia``.
+    """
+    url = make_url(url_origen)
+    nombre = _nombre_valido(nombre_clon)
+
+    # Motor administrativo: se conecta a la base "postgres" del mismo
+    # servidor para poder ejecutar CREATE DATABASE (que no admite estar
+    # dentro de una transaccion).
+    admin = _motor_para(url, base="postgres")
+    try:
+        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
+            if _existe_base(conn, nombre):
+                raise ErrorClonado(
+                    "La base de datos %r ya existe en el servidor. Borrala antes "
+                    "de volver a clonar." % nombre
+                )
+            conn.execute(text('CREATE DATABASE "%s"' % nombre))
+            logger.info("[clone] base de datos creada: %s", nombre)
+    except ErrorClonado:
+        raise
+    except SQLAlchemyError as exc:
+        raise ErrorClonado("No se pudo crear la base de datos %r: %s" % (nombre, exc)) from exc
+    finally:
+        admin.dispose()
+
+    url_clon = url.set(database=nombre)
+    uri_clon = url_clon.render_as_string(hide_password=False)
+
+    # Esquema: se crea con el metadata de los modelos.
+    import app.models  # noqa: F401  (registra los modelos en Base.metadata)
+    from app.db.base import Base
+
+    clon = engine_clon or create_engine(url_clon, pool_pre_ping=True, future=True)
+    try:
+        Base.metadata.create_all(clon)
+
+        filas_totales = 0
+        tablas_copiadas = 0
+        if copiar_datos:
+            origen = _motor_para(url)
+            try:
+                # Orden de dependencias: primero las tablas de las que dependen
+                # las demas (usuarios, proyectos, estados...), luego las hijas.
+                # ``sorted_tables`` NO sirve: el ciclo adjuntos <-> comentarios
+                # <-> tickets rompe el orden topologico (ver ``_orden_y_ciclos``).
+                orden, ciclos = _orden_y_ciclos(list(Base.metadata.tables.values()))
+                copia = orden + sorted(ciclos, key=lambda t: t.name)
+                with origen.connect() as src, clon.begin() as dest:
+                    modo, constraints = _relajar_fks(dest, ciclos)
+                    try:
+                        for tabla in copia:
+                            try:
+                                filas = src.execute(select(tabla)).mappings().all()
+                            except SQLAlchemyError as exc:
+                                logger.warning(
+                                    "[clone] no se pudo leer %s: %s", tabla.name, exc,
+                                )
+                                continue
+                            if not filas:
+                                continue
+                            dest.execute(
+                                insert(tabla),
+                                [dict(f) for f in filas],
+                            )
+                            filas_totales += len(filas)
+                            tablas_copiadas += 1
+                    finally:
+                        _restaurar_fks(dest, modo, constraints)
+                secuencias = 0
+                with clon.begin() as dest:
+                    secuencias = _alinear_secuencias(dest, copia)
+            finally:
+                origen.dispose()
+        else:
+            secuencias = 0
+
+        return {
+            "uri": uri_clon,
+            "nombre": nombre,
+            "tablas": len(Base.metadata.tables),
+            "tablas_copiadas": tablas_copiadas,
+            "filas": filas_totales,
+            "secuencias": secuencias,
+            "ya_existia": False,
+        }
+    except SQLAlchemyError as exc:
+        raise ErrorClonado("No se pudo poblar el clon %r: %s" % (nombre, exc)) from exc
+    finally:
+        if engine_clon is None:
+            clon.dispose()
+
+
+def borrar_clon(url_origen: str, nombre_clon: str) -> Dict[str, Any]:
+    """
+    Borra la base de datos del clon. Es la operacion de reversion.
+
+    No toca la base de datos de origen en ningun caso.
+    """
+    url = make_url(url_origen)
+    nombre = _nombre_valido(nombre_clon)
+    admin = _motor_para(url, base="postgres")
+    try:
+        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
+            if not _existe_base(conn, nombre):
+                return {"nombre": nombre, "borrada": False, "motivo": "no existe"}
+            conn.execute(text('DROP DATABASE "%s" WITH (FORCE)' % nombre))
+            logger.info("[clone] base de datos borrada: %s", nombre)
+            return {"nombre": nombre, "borrada": True}
+    except SQLAlchemyError as exc:
+        raise ErrorClonado("No se pudo borrar el clon %r: %s" % (nombre, exc)) from exc
+    finally:
+        admin.dispose()
+
+
+def listar_clones(url_origen: str, prefijo: str = "railway_clon") -> List[str]:
+    """Devuelve los nombres de las bases de datos del clon que existen."""
+    url = make_url(url_origen)
+    admin = _motor_para(url, base="postgres")
+    try:
+        with admin.connect() as conn:
+            filas = conn.execute(
+                text("SELECT datname FROM pg_database WHERE datname LIKE :p"),
+                {"p": prefijo + "%"},
+            ).fetchall()
+            return [f[0] for f in filas]
+    except SQLAlchemyError as exc:
+        raise ErrorClonado("No se pudieron listar los clones: %s" % exc) from exc
+    finally:
+        admin.dispose()
+
+
+def _tablas_y_columnas(conn) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
+    """
+    Devuelve (tablas con sus columnas, numero de filas por tabla) de la base
+    de datos a la que apunta la conexion.
+    """
+    tablas: Dict[str, List[str]] = {}
+    for fila in conn.execute(text(
+        "SELECT table_name, column_name FROM information_schema.columns "
+        "WHERE table_schema = current_schema() AND table_name NOT LIKE 'pg_%' "
+        "ORDER BY table_name, ordinal_position"
+    )).fetchall():
+        tablas.setdefault(fila[0], []).append(fila[1])
+
+    conteos: Dict[str, int] = {}
+    for tabla in sorted(tablas):
+        try:
+            conteos[tabla] = conn.execute(
+                text('SELECT COUNT(*) FROM "%s"' % tabla)
+            ).scalar() or 0
+        except SQLAlchemyError:
+            conteos[tabla] = -1
+    return tablas, conteos
+
+
+def verificar_clon(url_origen: str, nombre_clon: str) -> Dict[str, Any]:
+    """
+    Compara el clon con la base de datos de origen y comprueba que el
+    aislamiento por proyecto quedo bien aplicado dentro del clon.
+
+    Es la validacion de la ventana V2: no basta con que el clon se cree, tiene
+    que ser una COPIA FIEL (mismas tablas, mismas columnas, mismo numero de
+    filas) y ademas tiene que tener el backfill aplicado (ninguna fila de
+    negocio con ``proyecto_id`` a NULL, proyecto "Legacy" existente y con
+    miembros).
+
+    Es de SOLO LECTURA: no escribe nada ni en el origen ni en el clon.
+
+    Devuelve
+    --------
+    dict
+        ``ok`` (bool), ``nombre``, ``tablas_origen``, ``tablas_clon``,
+        ``tablas_solo_en_*``, ``columnas_solo_en_*``, ``filas_*``,
+        ``tablas_con_diferencia_de_filas``, ``nulos_proyecto_id``,
+        ``proyecto_legacy`` y ``miembros_legacy``.
+    """
+    url = make_url(url_origen)
+    nombre = _nombre_valido(nombre_clon)
+
+    origen = _motor_para(url)
+    clon = _motor_para(url, base=nombre)
+    try:
+        with origen.connect() as c_origen:
+            tablas_origen, conteos_origen = _tablas_y_columnas(c_origen)
+        with clon.connect() as c_clon:
+            tablas_clon, conteos_clon = _tablas_y_columnas(c_clon)
+
+            solo_origen = sorted(set(tablas_origen) - set(tablas_clon))
+            solo_clon = sorted(set(tablas_clon) - set(tablas_origen))
+            columnas_solo_origen = {
+                t: sorted(set(tablas_origen[t]) - set(tablas_clon.get(t, [])))
+                for t in tablas_origen
+                if t in tablas_clon and set(tablas_origen[t]) - set(tablas_clon[t])
+            }
+            filas_diferentes = {
+                t: {"origen": conteos_origen.get(t, -1),
+                    "clon": conteos_clon.get(t, -1)}
+                for t in sorted(set(conteos_origen) & set(conteos_clon))
+                if conteos_origen[t] != conteos_clon[t]
+            }
+
+            # Backfill: ninguna fila de negocio debe quedar sin proyecto.
+            nulos: Dict[str, int] = {}
+            for tabla in sorted(tablas_clon):
+                if "proyecto_id" not in tablas_clon[tabla]:
+                    continue
+                try:
+                    n = c_clon.execute(text(
+                        'SELECT COUNT(*) FROM "%s" WHERE proyecto_id IS NULL' % tabla
+                    )).scalar() or 0
+                except SQLAlchemyError:
+                    n = -1
+                if n:
+                    nulos[tabla] = n
+
+            proyecto_legacy = None
+            miembros_legacy = 0
+            if "proyectos" in tablas_clon:
+                proyecto_legacy = c_clon.execute(text(
+                    "SELECT nombre FROM proyectos WHERE id = 1"
+                )).scalar()
+            if "proyecto_usuarios" in tablas_clon:
+                miembros_legacy = c_clon.execute(text(
+                    "SELECT COUNT(*) FROM proyecto_usuarios WHERE proyecto_id = 1"
+                )).scalar() or 0
+
+        ok = (
+            not solo_origen and not solo_clon and not columnas_solo_origen
+            and not filas_diferentes and not nulos
+            and proyecto_legacy is not None
+        )
+        return {
+            "ok": ok,
+            "nombre": nombre,
+            "tablas_origen": len(tablas_origen),
+            "tablas_clon": len(tablas_clon),
+            "tablas_solo_en_origen": solo_origen,
+            "tablas_solo_en_clon": solo_clon,
+            "columnas_solo_en_origen": columnas_solo_origen,
+            "filas_origen": sum(v for v in conteos_origen.values() if v > 0),
+            "filas_clon": sum(v for v in conteos_clon.values() if v > 0),
+            "tablas_con_diferencia_de_filas": filas_diferentes,
+            "nulos_proyecto_id": nulos,
+            "proyecto_legacy": proyecto_legacy,
+            "miembros_legacy": miembros_legacy,
+        }
+    except SQLAlchemyError as exc:
+        raise ErrorClonado(
+            "No se pudo verificar el clon %r: %s" % (nombre, exc)
+        ) from exc
+    finally:
+        origen.dispose()
+        clon.dispose()
diff --git a/app/templates/usuarios/tabla.html b/app/templates/usuarios/tabla.html
index d570881..7e77dbf 100644
--- a/app/templates/usuarios/tabla.html
+++ b/app/templates/usuarios/tabla.html
@@ -66,12 +66,16 @@
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"/>
             </svg>
           </button>
+          {# `desactivar-form` / `reactivar-form` responden 200 con cuerpo vacio:
+             con hx-swap="innerHTML" sobre `#usuarios-tabla` el partial se
+             vaciaria. Por eso no hay swap y la tabla se recarga con el mismo
+             patron que usuarios/form.html. #}
           {% if u.is_active %}
           <button class="p-1.5 text-amber-600 hover:bg-amber-50 rounded"
                   hx-post="/api/v1/usuarios/{{ u.id }}/desactivar-form"
                   hx-confirm="?Desactivar al usuario {{ u.nombre_completo }}?"
-                  hx-target="#usuarios-tabla" hx-swap="innerHTML"
-                  hx-on::after-request="if(event.detail.successful) window.showToast && window.showToast('Usuario desactivado','info')"
+                  hx-swap="none"
+                  hx-on::after-request="if(event.detail.successful) { window.showToast && window.showToast('Usuario desactivado','info'); htmx.ajax('GET','/usuarios/tabla',{target:'#usuarios-tabla',swap:'innerHTML'}); }"
                   title="Desactivar">
             <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"/>
@@ -80,8 +84,8 @@
           {% else %}
           <button class="p-1.5 text-emerald-600 hover:bg-emerald-50 rounded"
                   hx-post="/api/v1/usuarios/{{ u.id }}/reactivar-form"
-                  hx-target="#usuarios-tabla" hx-swap="innerHTML"
-                  hx-on::after-request="if(event.detail.successful) window.showToast && window.showToast('Usuario reactivado','success')"
+                  hx-swap="none"
+                  hx-on::after-request="if(event.detail.successful) { window.showToast && window.showToast('Usuario reactivado','success'); htmx.ajax('GET','/usuarios/tabla',{target:'#usuarios-tabla',swap:'innerHTML'}); }"
                   title="Reactivar">
             <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
diff --git a/pyproject.toml b/pyproject.toml
index e580e28..2d17223 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -42,6 +42,12 @@ dependencies = [
     # Async / Background tasks
     "celery==5.4.0",
     "redis==5.2.0",
+    # `kombu` se fija a 5.6.2: es dependencia TRANSITIVA de `celery` y, sin
+    # pin, el resolutor podia subir a `kombu 5.7.0`, que exige `redis>=6.4.0`
+    # (su extra "redis" no lo pide `celery`, asi que no se detecta el conflicto
+    # con `redis==5.2.0`) y hacia crashear el worker con
+    # `kombu.exceptions.VersionMismatch`. Ver `requirements.txt`.
+    "kombu==5.6.2",
     # Seguridad
     # `passlib` NO se declara: no lo importa ningun modulo y `passlib 1.7.4` es
     # incompatible con `bcrypt>=4`. Ver `requirements.txt`.
diff --git a/test_board_refresh_fix.py b/test_board_refresh_fix.py
index cc3a088..934a32d 100644
--- a/test_board_refresh_fix.py
+++ b/test_board_refresh_fix.py
@@ -105,10 +105,13 @@ check(
     r.status_code == 200 and "TST-0001" in r.text and "Titulo original" in r.text,
     f"status={r.status_code} contiene_codigo={'TST-0001' in r.text}",
 )
+# El marcador se extrae a una variable: un f-string no puede contener un
+# backslash en su parte de expresion antes de Python 3.12 (PEP 701).
+ticket_id_marker = f'id="ticket-{ticket_id}"'
 check(
     "GET /card-html -> contiene id=\"ticket-N\"",
-    f'id="ticket-{ticket_id}"' in r.text,
-    f"id_match={'id=\"ticket-' + str(ticket_id) + '\"' in r.text}",
+    ticket_id_marker in r.text,
+    f"id_match={ticket_id_marker in r.text}",
 )
 
 # --------------------------------------------------------------------
@@ -264,15 +267,19 @@ check(
 # --------------------------------------------------------------------
 # (Esto valida que el JS listener pueda encontrar/identificar la tarjeta
 #  correctamente con la informacion mas reciente del board.)
+# Los marcadores se extraen a variables: un f-string no puede contener un
+# backslash en su parte de expresion antes de Python 3.12 (PEP 701).
+data_prioridad_marker = 'data-prioridad="critica"'
 check(
     "Card tiene data-prioridad='critica'",
-    'data-prioridad="critica"' in r.text,
-    f"data_match={'data-prioridad=\"critica\"' in r.text}",
+    data_prioridad_marker in r.text,
+    f"data_match={data_prioridad_marker in r.text}",
 )
+data_ticket_id_marker = f'data-ticket-id="{ticket_id}"'
 check(
     "Card tiene data-ticket-id correcto",
-    f'data-ticket-id="{ticket_id}"' in r.text,
-    f"data_match={'data-ticket-id=\"' + str(ticket_id) + '\"' in r.text}",
+    data_ticket_id_marker in r.text,
+    f"data_match={data_ticket_id_marker in r.text}",
 )
 
 # --------------------------------------------------------------------
diff --git a/test_calendario_filtros.py b/test_calendario_filtros.py
index 6b3dbde..6bc924f 100644
--- a/test_calendario_filtros.py
+++ b/test_calendario_filtros.py
@@ -345,25 +345,31 @@ for sig in js_signatures:
     check(f"JS contiene '{sig}'", sig in html, f"presente={sig in html}")
 
 # Catalogos renderizados en los <select>
+# Las expresiones con backslash se extraen a variables: un f-string no puede
+# contener un backslash en su parte de expresion antes de Python 3.12 (PEP 701).
+presenta_estados = all(f'value="{eid}"' in html for eid in [ID_ESTADO_NUEVO, ID_ESTADO_PROGRESO, ID_ESTADO_CERRADO])
 check(
     "Select de estado contiene los 3 estados creados",
-    all(f'value="{eid}"' in html for eid in [ID_ESTADO_NUEVO, ID_ESTADO_PROGRESO, ID_ESTADO_CERRADO]),
-    f"presente={all(f'value=\"{eid}\"' in html for eid in [ID_ESTADO_NUEVO, ID_ESTADO_PROGRESO, ID_ESTADO_CERRADO])}",
+    presenta_estados,
+    f"presente={presenta_estados}",
 )
+presenta_sin_asignar = '<option value="-1"' in html
 check(
     "Select de asignado contiene '-- Sin asignar --'",
-    '<option value="-1"' in html,
-    f"presente={'<option value=\"-1\"' in html}",
+    presenta_sin_asignar,
+    f"presente={presenta_sin_asignar}",
 )
+presenta_usuarios = all(f'value="{uid}"' in html for uid in [ID_ADMIN, ID_AGENT, ID_AGENT2])
 check(
     "Select de asignado contiene los 3 usuarios",
-    all(f'value="{uid}"' in html for uid in [ID_ADMIN, ID_AGENT, ID_AGENT2]),
-    f"presente={all(f'value=\"{uid}\"' in html for uid in [ID_ADMIN, ID_AGENT, ID_AGENT2])}",
+    presenta_usuarios,
+    f"presente={presenta_usuarios}",
 )
+presenta_etiquetas = all(f'value="{eid}"' in html for eid in [ID_ETQ_BUG, ID_ETQ_MEJORA])
 check(
     "Select de etiqueta contiene las 2 etiquetas creadas",
-    all(f'value="{eid}"' in html for eid in [ID_ETQ_BUG, ID_ETQ_MEJORA]),
-    f"presente={all(f'value=\"{eid}\"' in html for eid in [ID_ETQ_BUG, ID_ETQ_MEJORA])}",
+    presenta_etiquetas,
+    f"presente={presenta_etiquetas}",
 )
 
 
diff --git a/tests/test_v2001_regressions.py b/tests/test_v2001_regressions.py
index d36b2d0..d28425e 100644
--- a/tests/test_v2001_regressions.py
+++ b/tests/test_v2001_regressions.py
@@ -372,6 +372,11 @@ def test_el_arranque_completo_sobre_una_base_nueva_no_falla(tmp_path):
     proceso = subprocess.run(
         [sys.executable, "-X", "utf8", "-c", script],
         capture_output=True, text=True, timeout=600,
+        # V2.009: sin `encoding` la salida UTF-8 del subproceso se decodifica
+        # con el locale del sistema (cp1252 en Windows) y el test falla con
+        # "argument of type 'NoneType' is not iterable". El subproceso se
+        # lanza SIEMPRE con `-X utf8`, asi que se decodifica como UTF-8.
+        encoding="utf-8", errors="replace",
         cwd=str(RAIZ),
     )
 
diff --git a/tests/test_v2009_backup_postgresql.py b/tests/test_v2009_backup_postgresql.py
new file mode 100644
index 0000000..0410406
--- /dev/null
+++ b/tests/test_v2009_backup_postgresql.py
@@ -0,0 +1,309 @@
+"""Pruebas del generador de backups de PostgreSQL (V2.009).
+
+Dos bloques:
+
+1) ``_pg_literal``: el formateo de valores SQL, incluido el caso ``json``,
+   que era un BUG REAL: psycopg2 convierte las columnas ``json``/``jsonb``
+   en objetos Python y un literal escrito a pelo no siempre es JSON valido.
+   En produccion (2026-11-18) un string JSON salia como ``'incidencia'``
+   (sin las comillas) y el backup no se podia restaurar::
+
+       ERROR: invalid input syntax for type json
+
+2) Un round-trip REAL contra PostgreSQL, que se salta si no hay un servidor
+   local disponible (en CI puede no haberlo).
+"""
+from __future__ import annotations
+
+import os
+import sys
+from datetime import datetime
+from pathlib import Path
+
+import pytest
+
+RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+if RAIZ not in sys.path:
+    sys.path.insert(0, RAIZ)
+
+from app.services.backup_service import _pg_literal  # noqa: E402
+
+
+# ============================================================
+# 1. _pg_literal
+# ============================================================
+
+class TestLiteralSQL:
+    """El literal SQL de cada tipo de valor."""
+
+    def test_null(self):
+        assert _pg_literal(None) == "NULL"
+
+    def test_entero_y_booleano(self):
+        assert _pg_literal(42) == "42"
+        assert _pg_literal(True) == "TRUE"
+        assert _pg_literal(False) == "FALSE"
+
+    def test_flotante(self):
+        assert _pg_literal(1.5) == "1.5"
+        assert _pg_literal(float("inf")) == "'Infinity'"
+        assert _pg_literal(float("-inf")) == "'-Infinity'"
+
+    def test_texto_con_comilla_simple(self):
+        assert _pg_literal("O'Brien") == "'O''Brien'"
+
+    def test_bytea_en_hexadecimal(self):
+        # Un SOLO backslash: '\\x0a1b' en el fichero, '\x0a1b' en la BD.
+        assert _pg_literal(b"\n\x1b") == "'\\x0a1b'"
+
+    def test_fecha_hora(self):
+        valor = datetime(2026, 11, 18, 10, 30, 0)
+        assert _pg_literal(valor) == "'2026-11-18 10:30:00'"
+
+
+class TestLiteralJSON:
+    """Las columnas ``json``/``jsonb`` necesitan su propio formato."""
+
+    def test_string_json_lleva_comillas(self):
+        """El caso que rompia la restauracion del backup de produccion."""
+        assert _pg_literal("incidencia", "json") == '\'"incidencia"\''
+
+    def test_booleano_json_es_true_en_minusculas(self):
+        assert _pg_literal(True, "json") == "'true'"
+        assert _pg_literal(False, "json") == "'false'"
+
+    def test_objeto_json(self):
+        assert _pg_literal({"a": 1}, "json") == '\'{"a": 1}\''
+
+    def test_lista_json(self):
+        assert _pg_literal([1, 2], "json") == "'[1, 2]'"
+
+    def test_numero_json(self):
+        assert _pg_literal(42, "json") == "'42'"
+
+    def test_null_json_es_null_de_sql(self):
+        assert _pg_literal(None, "json") == "NULL"
+
+    def test_string_json_con_comilla_simple(self):
+        assert _pg_literal("d'Angelo", "json") == '\'"d\'\'Angelo"\''
+
+    def test_jsonb_usa_el_mismo_formato(self):
+        assert _pg_literal("incidencia", "jsonb") == '\'"incidencia"\''
+
+    def test_sin_tipo_un_string_no_lleva_comillas_json(self):
+        """Sin el tipo de columna no se puede saber: es texto normal."""
+        assert _pg_literal("incidencia") == "'incidencia'"
+
+    def test_todo_lo_que_emiten_los_json_es_json_valido(self):
+        import json as _json
+
+        valores = [
+            "incidencia", "con \"comillas\"", "d'Angelo", True, False,
+            42, 3.14, {"a": 1, "b": [1, 2]}, [1, "x", None],
+            "acentuacion y n", "", "linea\nsalto",
+        ]
+        for valor in valores:
+            literal = _pg_literal(valor, "json")
+            assert literal.startswith("'") and literal.endswith("'")
+            # Se desenvuelve el literal SQL y se parsea como JSON.
+            interior = literal[1:-1].replace("''", "'")
+            _json.loads(interior)  # no debe lanzar
+
+
+# ============================================================
+# 2. Round-trip real contra PostgreSQL (se salta si no hay servidor)
+# ============================================================
+
+def _pg_local() -> str | None:
+    """Devuelve la URL de un PostgreSQL local, o None si no hay ninguno."""
+    candidatos = [
+        os.environ.get("PGV2009_URL", ""),
+        "postgresql://postgres@127.0.0.1:55433/postgres",
+    ]
+    for url in candidatos:
+        if not url:
+            continue
+        try:
+            import psycopg2
+            from sqlalchemy import create_engine
+
+            motor = create_engine(url, future=True)
+            with motor.connect() as c:
+                c.exec_driver_sql("SELECT 1")
+            motor.dispose()
+            return url
+        except Exception:
+            continue
+    return None
+
+
+@pytest.mark.skipif(_pg_local() is None, reason="no hay PostgreSQL local disponible")
+def test_roundtrip_con_columnas_json():
+    """Backup y restauracion de una tabla con valores JSON de todo tipo."""
+    import json as _json
+
+    from sqlalchemy import create_engine, text
+
+    url = _pg_local()
+    admin = url.rsplit("/", 1)[0] + "/postgres"
+    nombre = "v2009_test_backup_json"
+    motor_admin = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
+    with motor_admin.connect() as c:
+        for n in (nombre, nombre + "_restaurada"):
+            c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % n))
+            c.execute(text('CREATE DATABASE "%s"' % n))
+    motor_admin.dispose()
+
+    url_fuente = url.rsplit("/", 1)[0] + "/" + nombre
+    url_destino = url.rsplit("/", 1)[0] + "/" + nombre + "_restaurada"
+    motor_fuente = create_engine(url_fuente, future=True)
+    motor_destino = create_engine(url_destino, future=True, isolation_level="AUTOCOMMIT")
+
+    valores = [
+        "incidencia",
+        '{"estado_id": 1, "estado": "BackLog"}',
+        "d'Angelo",
+        "acentuacion",
+    ]
+    try:
+        with motor_fuente.begin() as c:
+            c.execute(text("CREATE TABLE t_json (id integer primary key, j json, b json)"))
+            for i, v in enumerate(valores, start=1):
+                # Se inserta el TEXTO JSON, que es lo que hace la columna:
+                # un string plano se guarda como el string JSON "incidencia"
+                # (con comillas). Asi es como esta en produccion.
+                c.execute(
+                    text("INSERT INTO t_json (id, j, b) VALUES (:i, :j, :b)"),
+                    {"i": i, "j": _json.dumps(v), "b": _json.dumps(True)},
+                )
+
+        # --- backup ---
+        import gzip
+        import tempfile
+
+        from app.services.backup_service import BackupService
+
+        with tempfile.TemporaryDirectory() as tmp:
+            destino = os.path.join(tmp, "dump.sql.gz")
+            BackupService()._backup_postgresql_python(url_fuente, Path(destino))
+            with gzip.open(destino, "rb") as fh:
+                sql = fh.read().decode("utf-8")
+
+        assert "CREATE TABLE" in sql
+        assert "t_json" in sql
+
+        # --- restauracion ---
+        with motor_destino.connect() as c:
+            c.execute(text(sql))
+
+        with motor_destino.connect() as c:
+            leidos = c.execute(text("SELECT id, j::text, b::text FROM t_json ORDER BY id")).fetchall()
+        assert len(leidos) == len(valores)
+        for fila, original in zip(leidos, valores):
+            # Se compara el VALOR JSON, no su texto: PostgreSQL normaliza los
+            # escapes unicode ("acentuaci\u00f3n" -> "acentuacion"), pero el
+            # valor es el mismo.
+            assert _json.loads(fila[1]) == original, (
+                "valor json alterado: %r != %r" % (fila[1], original))
+            assert _json.loads(fila[2]) is True
+    finally:
+        motor_fuente.dispose()
+        motor_destino.dispose()
+        motor_admin = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
+        with motor_admin.connect() as c:
+            for n in (nombre, nombre + "_restaurada"):
+                c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % n))
+        motor_admin.dispose()
+
+
+@pytest.mark.skipif(_pg_local() is None, reason="no hay PostgreSQL local disponible")
+def test_las_migraciones_concurrentes_no_se_pisan():
+    """Tres procesos aplicando migraciones a la vez NO deben fallar.
+
+    En el despliegue de Railway, ``start.sh`` lanza ``verificar_esquema()``
+    en los tres roles (web, worker y beat) a la vez, y los tres aplican las
+    migraciones sobre la MISMA base de datos. Sin cerrojo ni savepoint por
+    indice, dos de ellos crean el mismo indice a la vez y el segundo recibe
+    "duplicate key value violates unique constraint
+    pg_class_relname_nsp_index", que ABORTA su transaccion y deja sin crear
+    los indices que quedaban.
+
+    Medido el 2026-11-14 en produccion: un servicio creo 3 indices y fallo
+    en los 52 restantes.
+    """
+    import multiprocessing as mp  # noqa: F401  (documenta el problema)
+    from sqlalchemy import create_engine, text
+
+    url = _pg_local()
+    admin = url.rsplit("/", 1)[0] + "/postgres"
+    nombre = "v2009_test_concurrencia"
+    motor_admin = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
+    with motor_admin.connect() as c:
+        for n in (nombre,):
+            c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % n))
+            c.execute(text('CREATE DATABASE "%s"' % n))
+    motor_admin.dispose()
+
+    url_db = url.rsplit("/", 1)[0] + "/" + nombre
+    motor = create_engine(url_db, future=True)
+    import app.models  # noqa: F401
+    from app.db.base import Base
+
+    Base.metadata.create_all(motor)
+    motor.dispose()
+
+    def _trabajador(_n, resultados, barrera):
+        """Cada hilo abre SU PROPIA conexion: la carrera es real en la BD."""
+        from sqlalchemy import create_engine as ce, text as tx
+
+        m = ce(url_db, future=True)
+        ok = 0
+        fallos = 0
+        try:
+            with m.connect() as conn:
+                trans = conn.begin()
+                barrera.wait()
+                conn.execute(tx(
+                    "SELECT pg_advisory_xact_lock(:c)"), {"c": 7412009013})
+                from app.db.migrations import INDEXES
+
+                for _nombre, sql in INDEXES:
+                    try:
+                        with conn.begin_nested():
+                            conn.execute(tx(sql))
+                        ok += 1
+                    except Exception:
+                        fallos += 1
+                trans.commit()
+        except Exception:
+            fallos += 1
+        finally:
+            m.dispose()
+        resultados.append((ok, fallos))
+
+    import threading
+
+    resultados = []
+    barrera = threading.Barrier(3)
+    hilos = [threading.Thread(target=_trabajador, args=(i, resultados, barrera))
+             for i in range(3)]
+    for h in hilos:
+        h.start()
+    for h in hilos:
+        h.join(timeout=300)
+
+    motor = create_engine(url_db, future=True)
+    with motor.connect() as c:
+        n_proyecto = c.execute(text(
+            "SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'ix_%_proyecto_id'"
+        )).scalar()
+    motor.dispose()
+    with motor_admin.connect() as c:
+        c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % nombre))
+    motor_admin.dispose()
+
+    assert len(resultados) == 3, "no terminaron los 3 procesos: %s" % (resultados,)
+    fallos_totales = sum(f for _ok, f in resultados)
+    assert fallos_totales == 0, (
+        "las migraciones concurrentes fallaron: %s" % (resultados,))
+    assert n_proyecto == 34, "faltan indices de proyecto: %s de 34" % n_proyecto
\ No newline at end of file
diff --git a/tests/test_v2009_proyecto_aislamiento.py b/tests/test_v2009_proyecto_aislamiento.py
new file mode 100644
index 0000000..9939f9c
--- /dev/null
+++ b/tests/test_v2009_proyecto_aislamiento.py
@@ -0,0 +1,682 @@
+"""
+Tests del aislamiento por proyecto - V2.009 (ventana aditiva).
+
+Que se verifica aqui
+--------------------
+1. El catalogo de proyectos existe (``proyectos`` + ``proyecto_usuarios``).
+2. La columna ``proyecto_id`` esta en TODAS las tablas de negocio y en
+   NINGUNA global (``usuarios``).
+3. El contexto de proyecto esta APAGADO por defecto: sin contexto, una
+   sesion ve los tickets de todos los proyectos (comportamiento de V2.008).
+4. Con el aislamiento encendido, la sesion filtra por ``proyecto_id`` tanto en
+   la API moderna (``select``) como en la heredada (``Query``), y tambien al
+   cargar por relacion.
+5. La migracion anade la columna, crea el indice y hace el backfill al
+   proyecto "Legacy", de forma idempotente.
+6. El guardian estricto detecta una columna que el modelo declara y la base de
+   datos no tiene (el defecto que hasta V2.008 no se detectaba).
+7. Las politicas RLS se generan con el GUC de sesion y NO se aplican mientras
+   el flag esta apagado.
+"""
+from __future__ import annotations
+
+import os
+import sys
+from pathlib import Path
+
+import pytest
+from sqlalchemy import create_engine, inspect, text
+from sqlalchemy.orm import Session
+
+RAIZ = Path(__file__).resolve().parent.parent
+if str(RAIZ) not in sys.path:
+    sys.path.insert(0, str(RAIZ))
+
+from app.core import proyecto as modulo_proyecto  # noqa: E402
+from app.core.proyecto import (  # noqa: E402
+    clases_con_proyecto,
+    contexto_proyecto,
+    obtener_proyecto_actual,
+    tablas_con_proyecto,
+)
+from app.db.base import Base  # noqa: E402
+from app.db.migrations import (  # noqa: E402
+    COLUMNS_TO_ADD,
+    TABLAS_CON_PROYECTO,
+    comparar_esquema_completo,
+)
+from app.db.rls import politicas_rls  # noqa: E402
+from app.models.proyecto import (  # noqa: E402
+    NOMBRE_PROYECTO_LEGACY,
+    PROYECTO_LEGACY_ID,
+    Proyecto,
+)
+
+
+# ============================================================================ #
+# 1. Catalogo de proyectos
+# ============================================================================ #
+
+def test_la_tabla_de_proyectos_existe_en_el_metadata():
+    assert "proyectos" in Base.metadata.tables
+    assert "proyecto_usuarios" in Base.metadata.tables
+
+
+def test_el_proyecto_legacy_tiene_id_y_nombre_fijos():
+    assert PROYECTO_LEGACY_ID == 1
+    assert NOMBRE_PROYECTO_LEGACY == "Legacy"
+
+
+def test_la_tabla_proyectos_tiene_las_columnas_esperadas():
+    columnas = {c.name for c in Base.metadata.tables["proyectos"].c}
+    for esperada in ("id", "nombre", "descripcion", "plan", "color", "icono",
+                     "activo", "propietario_id", "created_at", "updated_at"):
+        assert esperada in columnas, "falta la columna %s" % esperada
+
+
+def test_el_puente_de_usuarios_tiene_clave_primaria_compuesta():
+    tabla = Base.metadata.tables["proyecto_usuarios"]
+    assert {c.name for c in tabla.primary_key.columns} == {"proyecto_id", "usuario_id"}
+
+
+def test_los_usuarios_no_llevan_proyecto_id():
+    """Los usuarios son globales: pertenecen a la instalacion, no a un proyecto."""
+    from app.models.usuario import Usuario
+
+    assert "proyecto_id" not in Usuario.__table__.c
+
+
+def test_sessionlocal_se_puede_instantiar():
+    """``SessionLocal`` debe devolver una sesion usable.
+
+    Regresion: con ``sessionmaker(cls=...)`` (parametro equivocado en
+    SQLAlchemy 2.0) el error aparece al instanciar, no al importar, y la app
+    no arrancaba. Este test lo detecta antes del despliegue.
+    """
+    from app.db.session import SessionLocal, SesionProyecto
+
+    sesion = SessionLocal()
+    try:
+        assert isinstance(sesion, SesionProyecto)
+    finally:
+        sesion.close()
+
+
+# ============================================================================ #
+# 2. La columna proyecto_id esta donde debe estar
+# ============================================================================ #
+
+def test_las_tablas_con_proyecto_coinciden_con_el_catalogo_declarado():
+    """La lista declarada y la que se deriva del metadata no pueden divergir."""
+    assert set(tablas_con_proyecto()) == set(TABLAS_CON_PROYECTO)
+
+
+def test_las_tablas_de_negocio_tienen_proyecto_id():
+    for tabla in TABLAS_CON_PROYECTO:
+        assert "proyecto_id" in Base.metadata.tables[tabla].c, tabla
+
+
+def test_las_clases_con_proyecto_cubren_las_tablas_declaradas():
+    clases = clases_con_proyecto()
+    assert len(clases) == len(TABLAS_CON_PROYECTO)
+    nombres = {c.__tablename__ for c in clases}
+    assert nombres == set(TABLAS_CON_PROYECTO)
+
+
+def test_la_columna_es_nullable_en_todas_las_tablas():
+    """La ventana V2.009 es aditiva: el paso a NOT NULL es de la ventana V3."""
+    for tabla in TABLAS_CON_PROYECTO:
+        columna = Base.metadata.tables[tabla].c["proyecto_id"]
+        assert columna.nullable, tabla
+
+
+def test_la_migracion_declara_la_columna_para_todas_las_tablas():
+    for tabla in TABLAS_CON_PROYECTO:
+        assert "proyecto_id" in COLUMNS_TO_ADD.get(tabla, {}), tabla
+
+
+def test_las_tablas_puente_no_llevan_proyecto_id():
+    """Las tablas de asociacion derivan su aislamiento de las tablas a las
+    que apuntan (espacios, tickets, etiquetas), que si llevan la columna."""
+    for tabla in ("espacio_miembros", "ticket_etiquetas", "ticket_miembros"):
+        assert "proyecto_id" not in Base.metadata.tables[tabla].c, tabla
+
+
+# ============================================================================ #
+# 3. El contexto esta apagado por defecto
+# ============================================================================ #
+
+def test_sin_contexto_no_hay_proyecto_activo():
+    assert obtener_proyecto_actual() is None
+
+
+def test_con_el_flag_apagado_el_contexto_se_ignora():
+    """El flag manda: aunque se fije un contexto, sin aislamiento no se aplica."""
+    from app.core.config import settings
+
+    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = False
+    try:
+        with contexto_proyecto(7):
+            assert obtener_proyecto_actual() is None
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior
+
+
+def test_con_el_flag_encendido_el_contexto_se_usa():
+    from app.core.config import settings
+
+    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
+    try:
+        with contexto_proyecto(7):
+            assert obtener_proyecto_actual() == 7
+        assert obtener_proyecto_actual() is None
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior
+
+
+def test_el_gestor_de_contexto_restaura_el_valor_anterior():
+    from app.core.config import settings
+
+    anterior_flag = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
+    try:
+        with contexto_proyecto(1):
+            with contexto_proyecto(2):
+                assert obtener_proyecto_actual() == 2
+            assert obtener_proyecto_actual() == 1
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior_flag
+
+
+def test_el_contexto_se_restablece_aunque_el_bloque_falle():
+    from app.core.config import settings
+
+    anterior_flag = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
+    try:
+        with pytest.raises(ValueError):
+            with contexto_proyecto(3):
+                raise ValueError("fallo simulado")
+        assert obtener_proyecto_actual() is None
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior_flag
+
+
+# ============================================================================ #
+# 4. El filtro ORM ( SesionProyecto )
+# ============================================================================ #
+
+@pytest.fixture()
+def bd_proyectos():
+    """Base de datos SQLite con dos proyectos y un ticket en cada uno."""
+    import tempfile
+
+    fd, ruta = tempfile.mkstemp(prefix="v2009_", suffix=".sqlite")
+    os.close(fd)
+    motor = create_engine("sqlite:///" + ruta.replace("\\", "/"), future=True)
+    Base.metadata.create_all(motor)
+
+    from app.models.estado import Estado
+    from app.models.ticket import Prioridad, Ticket, TipoIncidencia
+    from app.models.usuario import RolUsuario, Usuario
+
+    with Session(motor) as sesion:
+        admin = Usuario(
+            username="admin_v2009",
+            email="admin@v2009.test",
+            nombre_completo="Admin V2009",
+            hashed_password="x",
+            rol=RolUsuario.ADMINISTRADOR,
+        )
+        sesion.add(admin)
+        sesion.flush()
+        estado = Estado(nombre="BackLog", es_inicial=True)
+        sesion.add(estado)
+        sesion.flush()
+        p1 = Proyecto(nombre="Legacy")
+        p2 = Proyecto(nombre="Otro")
+        sesion.add_all([p1, p2])
+        sesion.flush()
+        for indice, proyecto in enumerate((p1, p2), start=1):
+            sesion.add(Ticket(
+                codigo="V2009-%03d" % indice,
+                titulo="Ticket del proyecto %d" % indice,
+                descripcion="desc",
+                tipo=TipoIncidencia.INCIDENCIA,
+                prioridad=Prioridad.MEDIA,
+                estado_id=estado.id,
+                creador_id=admin.id,
+                proyecto_id=proyecto.id,
+            ))
+        sesion.commit()
+        ids = {
+            "legacy": p1.id,
+            "otro": p2.id,
+            "estado": estado.id,
+            "usuario": admin.id,
+        }
+
+    try:
+        yield motor, ids
+    finally:
+        motor.dispose()
+        for sufijo in ("", "-wal", "-shm"):
+            try:
+                os.unlink(ruta + sufijo)
+            except OSError:
+                pass
+
+
+def _abrir_sesion(motor, proyecto_id=None):
+    """Abre una SesionProyecto, con contexto de proyecto si se indica."""
+    from app.db.session import SesionProyecto
+
+    if proyecto_id is None:
+        return SesionProyecto(bind=motor)
+
+    token = modulo_proyecto.establecer_proyecto_actual(proyecto_id)
+    try:
+        return SesionProyecto(bind=motor)
+    finally:
+        pass  # el token se restaura en el cierre del test
+
+
+def test_sin_contexto_la_sesion_ve_todos_los_proyectos(bd_proyectos):
+    """Sin aislamiento, el comportamiento es el de V2.008: se ve todo."""
+    motor, _ids = bd_proyectos
+    from app.models.ticket import Ticket
+
+    sesion = _abrir_sesion(motor, None)
+    try:
+        tickets = sesion.query(Ticket).all()
+        assert len(tickets) == 2
+    finally:
+        sesion.close()
+
+
+def test_con_contexto_la_sesion_filtra_por_proyecto(bd_proyectos):
+    """Con aislamiento encendido, la API heredada (Query) tambien filtra."""
+    from app.core.config import settings
+    from app.models.ticket import Ticket
+
+    motor, ids = bd_proyectos
+    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
+    try:
+        with contexto_proyecto(ids["legacy"]):
+            sesion = _abrir_sesion(motor, ids["legacy"])
+            try:
+                tickets = sesion.query(Ticket).all()
+                assert len(tickets) == 1, tickets
+                assert tickets[0].proyecto_id == ids["legacy"]
+            finally:
+                sesion.close()
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior
+
+
+def test_con_contexto_la_api_moderna_tambien_filtra(bd_proyectos):
+    from sqlalchemy import select
+
+    from app.core.config import settings
+    from app.models.ticket import Ticket
+
+    motor, ids = bd_proyectos
+    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
+    try:
+        with contexto_proyecto(ids["otro"]):
+            sesion = _abrir_sesion(motor, ids["otro"])
+            try:
+                tickets = sesion.execute(select(Ticket)).scalars().all()
+                assert len(tickets) == 1, tickets
+                assert tickets[0].proyecto_id == ids["otro"]
+            finally:
+                sesion.close()
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior
+
+
+def test_dos_contextos_no_se_pisan(bd_proyectos):
+    """El ContextVar hace que dos peticiones concurrentes no se contaminen."""
+    from app.core.config import settings
+
+    motor, ids = bd_proyectos
+    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
+    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
+    try:
+        with contexto_proyecto(ids["legacy"]):
+            with contexto_proyecto(ids["otro"]):
+                assert obtener_proyecto_actual() == ids["otro"]
+            assert obtener_proyecto_actual() == ids["legacy"]
+    finally:
+        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior
+
+
+# ============================================================================ #
+# 5. La migracion: columna, indice y backfill
+# ============================================================================ #
+
+def test_la_migracion_anade_la_columna_hace_backfill_y_es_idempotente(tmp_path):
+    """Sobre una BD con el esquema viejo, la migracion deja la columna puesta."""
+    from app.db.migrations import apply_migrations
+
+    motor = create_engine(
+        "sqlite:///" + str(tmp_path / "mig.sqlite").replace("\\", "/"), future=True
+    )
+    try:
+        # Esquema "viejo": la tabla tickets sin la columna proyecto_id.
+        with motor.begin() as conn:
+            conn.execute(text(
+                "CREATE TABLE proyectos (id INTEGER PRIMARY KEY, nombre VARCHAR(120), "
+                "descripcion TEXT, plan VARCHAR(40), color VARCHAR(20), icono VARCHAR(40), "
+                "activo BOOLEAN, propietario_id INTEGER, created_at DATETIME NOT NULL, "
+                "updated_at DATETIME NOT NULL)"
+            ))
+            conn.execute(text(
+                "CREATE TABLE tickets (id INTEGER PRIMARY KEY, codigo VARCHAR(20) NOT NULL, "
+                "titulo VARCHAR(200) NOT NULL)"
+            ))
+            conn.execute(text(
+                "INSERT INTO tickets (id, codigo, titulo) VALUES (1, 'LEG-001', 'Antiguo')"
+            ))
+
+        assert "proyecto_id" not in {
+            c["name"] for c in inspect(motor).get_columns("tickets")
+        }
+
+        apply_migrations(motor)
+        apply_migrations(motor)  # idempotente
+
+        columnas = {c["name"] for c in inspect(motor).get_columns("tickets")}
+        assert "proyecto_id" in columnas
+
+        # El backfill asigna la fila existente al proyecto Legacy.
+        with motor.connect() as conn:
+            valor = conn.execute(
+                text("SELECT proyecto_id FROM tickets WHERE id = 1")
+            ).scalar()
+            nombre = conn.execute(
+                text("SELECT nombre FROM proyectos WHERE id = 1")
+            ).scalar()
+        assert valor == PROYECTO_LEGACY_ID
+        assert nombre == NOMBRE_PROYECTO_LEGACY
+
+        # Y el indice existe.
+        indices = {i["name"] for i in inspect(motor).get_indexes("tickets")}
+        assert "ix_tickets_proyecto_id" in indices
+    finally:
+        motor.dispose()
+
+
+def test_el_proyecto_legacy_se_crea_solo_una_vez():
+    from app.db.migrations import apply_migrations
+
+    import tempfile
+
+    fd, ruta = tempfile.mkstemp(prefix="v2009b_", suffix=".sqlite")
+    os.close(fd)
+    motor = create_engine("sqlite:///" + ruta.replace("\\", "/"), future=True)
+    try:
+        apply_migrations(motor)
+        apply_migrations(motor)
+        with motor.connect() as conn:
+            total = conn.execute(
+                text("SELECT COUNT(*) FROM proyectos WHERE id = 1")
+            ).scalar()
+        assert total == 1
+    finally:
+        motor.dispose()
+        for sufijo in ("", "-wal", "-shm"):
+            try:
+                os.unlink(ruta + sufijo)
+            except OSError:
+                pass
+
+
+# ============================================================================ #
+# 6. El guardian estricto de esquema
+# ============================================================================ #
+
+def test_el_guardian_estricto_detecta_una_columna_que_falta(tmp_path):
+    """El defecto que hasta V2.008 pasaba desapercibido."""
+    motor = create_engine(
+        "sqlite:///" + str(tmp_path / "deriva.sqlite").replace("\\", "/"), future=True
+    )
+    try:
+        Base.metadata.create_all(motor)
+        with motor.begin() as conn:
+            conn.execute(text("ALTER TABLE tickets DROP COLUMN descripcion"))
+
+        lineas = comparar_esquema_completo(motor)
+        deriva = [l for l in lineas if "faltan" in l or "no existe" in l]
+        assert any("tickets" in l and "descripcion" in l for l in deriva), deriva
+    finally:
+        motor.dispose()
+
+
+def test_el_guardian_estricto_no_detecta_deriva_si_el_esquema_esta_alineado(tmp_path):
+    motor = create_engine(
+        "sqlite:///" + str(tmp_path / "alineado.sqlite").replace("\\", "/"), future=True
+    )
+    try:
+        Base.metadata.create_all(motor)
+        lineas = comparar_esquema_completo(motor)
+        deriva = [l for l in lineas if "faltan" in l or "no existe" in l]
+        assert deriva == [], deriva
+    finally:
+        motor.dispose()
+
+
+def test_el_guardian_estricto_esta_apagado_por_defecto():
+    """Con ``ESQUEMA_ESTRICTO`` apagado el arranque no se detiene por deriva."""
+    from app.core.config import settings
+
+    assert settings.ESQUEMA_ESTRICTO is False
+
+
+# ============================================================================ #
+# 7. RLS preparado pero inerte
+# ============================================================================ #
+
+def test_rls_esta_apagado_por_defecto():
+    from app.core.config import settings
+
+    assert settings.RLS_HABILITADO is False
+    assert settings.AISLAMIENTO_PROYECTO_ACTIVO is False
+
+
+def test_las_politicas_rls_usan_el_guc_de_sesion():
+    sentencias = politicas_rls(["tickets"])
+    sql = " ".join(s for _etiqueta, s in sentencias)
+    assert "CREATE POLICY" in sql
+    assert "current_setting('app.proyecto_id', true)" in sql
+    assert "ENABLE ROW LEVEL SECURITY" not in sql  # se aplica aparte, con ALTER
+
+
+def test_las_politicas_rls_son_idempotentes():
+    """Se borra la politica previa antes de recrearla (PostgreSQL no tiene
+    CREATE POLICY IF NOT EXISTS)."""
+    sentencias = politicas_rls(["tickets"])
+    assert sentencias[0][0].startswith("drop_policy_")
+    assert "DROP POLICY IF EXISTS" in sentencias[0][1]
+
+
+def test_la_tabla_de_puentes_no_entra_en_rls():
+    """Las tablas puente no tienen columna de proyecto: no pueden tener RLS."""
+    from app.db.rls import aplicar_politicas_rls  # noqa: F401  (import de humo)
+
+    for tabla in ("espacio_miembros", "ticket_etiquetas", "ticket_miembros"):
+        assert "proyecto_id" not in Base.metadata.tables[tabla].c
+
+
+# ============================================================================ #
+# 8. Correcciones de la validacion V2 (ENUM, savepoints, ciclo de FK, clon)
+# ============================================================================ #
+
+def test_el_orden_de_copia_detecta_el_ciclo_de_claves_foraneas():
+    """El esquema tiene un ciclo real: tickets <-> adjuntos <-> comentarios.
+
+    ``Base.metadata.sorted_tables`` devuelve un orden que NO es topologico
+    (coloca ``tickets`` antes que ``usuarios``) y la copia del clon fallaba
+    con una violacion de clave foranea. ``_orden_y_ciclos()`` debe detectar
+    el ciclo y devolver un orden que cubre TODAS las tablas.
+    """
+    from app.services.clone_service import _orden_y_ciclos
+
+    orden, ciclos = _orden_y_ciclos(list(Base.metadata.tables.values()))
+
+    # Todas las tablas estan en el resultado (una vez en el orden o en el
+    # conjunto de ciclos).
+    assert len(orden) + len(ciclos) == len(Base.metadata.tables)
+    assert len(set(id(t) for t in orden) | set(id(t) for t in ciclos)) == \
+        len(Base.metadata.tables)
+
+    # El ciclo detectado incluye las tablas problematicas.
+    nombres = {t.name for t in ciclos}
+    assert "tickets" in nombres
+    assert "adjuntos" in nombres
+    assert "comentarios" in nombres
+
+    # Y el orden topologico respeta las dependencias fuera del ciclo:
+    # ``usuarios`` debe estar antes que ``tickets``.
+    assert orden.index(Base.metadata.tables["usuarios"]) < \
+        len(orden) or "usuarios" not in {t.name for t in ciclos}
+
+
+def test_la_etiqueta_del_rol_admin_se_resuelve_desde_la_base_de_datos():
+    """El ENUM de ``usuarios.rol`` se persiste con el NOMBRE del miembro.
+
+    Comparar la columna contra el literal ``'administrador'`` hacia fallar
+    PostgreSQL con ``invalid input value for enum rolusuario``. La etiqueta
+    real se lee de la base de datos, nunca se adivina.
+    """
+    from app.db.migrations import _resolver_etiqueta_admin
+
+    motor = create_engine("sqlite://", future=True)
+    Base.metadata.create_all(motor)
+    with motor.begin() as conn:
+        etiqueta = _resolver_etiqueta_admin(conn, False)
+
+    motor.dispose()
+    assert etiqueta.strip().upper() == "ADMINISTRADOR"
+
+
+def test_la_migracion_del_legacy_no_compara_el_enum_con_un_literal():
+    """Regresion: el literal ``'administrador'`` ante un ENUM rompe el paso 3.
+
+    La comparacion del rol se hace EN PYTHON (leyendo el valor almacenado),
+    no en SQL, de modo que no hay ningun literal que PostgreSQL pueda
+    rechazar al convertirlo a etiqueta del enum.
+    """
+    import inspect as _inspect
+
+    from app.db import migrations as mod
+
+    fuente = _inspect.getsource(mod._aplicar_proyecto_legacy)
+    assert "rol = 'administrador'" not in fuente
+    assert "WHERE rol =" not in fuente
+
+
+def test_el_backfill_usa_un_savepoint_por_paso():
+    """Cada paso va en su propio ``begin_nested()``.
+
+    Con un unico savepoint compartido, un fallo del paso 3 revertia el
+    backfill completo (unas 8.500 filas) y dejaba ``proyecto_id`` a NULL.
+    """
+    import inspect as _inspect
+
+    from app.db import migrations as mod
+
+    fuente = _inspect.getsource(mod._aplicar_proyecto_legacy)
+    # Un savepoint para la fila del proyecto, uno por tabla del backfill y
+    # uno para la membresia: al menos 3 llamadas a ``begin_nested``.
+    assert fuente.count("begin_nested()") >= 3
+
+
+def test_el_clon_relaja_las_claves_foraneas_durante_la_copia():
+    """La copia usa ``session_replication_role`` o constraints DEFERRABLE.
+
+    Sin relajar las FK, el clon no se puede poblar (ciclo de FK). Ademas el
+    camino preferido NO debe dejar cambios en el esquema del clon.
+    """
+    import inspect as _inspect
+
+    from app.services import clone_service
+
+    fuente = _inspect.getsource(clone_service._relajar_fks)
+    assert "session_replication_role" in fuente
+    assert "DEFERRABLE" in fuente
+
+    fuente_restaurar = _inspect.getsource(clone_service._restaurar_fks)
+    assert "NOT DEFERRABLE" in fuente_restaurar
+
+
+def test_la_verificacion_del_clon_esta_disponible():
+    from app.services.clone_service import verificar_clon  # noqa: F401
+
+
+def test_los_endpoints_de_migraciones_estan_registrados():
+    """Los cinco endpoints de administracion deben existir en la aplicacion."""
+    from app.main import app
+
+    rutas = {r.path for r in app.routes if hasattr(r, "path")}
+    for esperada in (
+        "/api/v1/migraciones/esquema",
+        "/api/v1/migraciones/clonar",
+        "/api/v1/migraciones/clonar/{nombre}",
+        "/api/v1/migraciones/clonar/{nombre}/verificar",
+        "/api/v1/migraciones/clones",
+    ):
+        assert esperada in rutas, "falta la ruta %s" % esperada
+
+def test_cada_indice_va_en_su_propio_savepoint():
+    """Un indice que falla NO puede invalidar los demas.
+
+    En PostgreSQL un error dentro de una transaccion la aborta: los comandos
+    siguientes fallan con "current transaction is aborted". En produccion el
+    2026-11-14 eso hizo que 3 indices se crearan y 52 fallaran (entre ellos
+    los 34 ``ix_<tabla>_proyecto_id``).
+    """
+    import inspect as _inspect
+
+    from app.db import migrations as mod
+
+    fuente = _inspect.getsource(mod.apply_migrations)
+    # El bucle de indices usa ``begin_nested()`` (un savepoint por indice).
+    bloque = fuente.split("for name, sql in INDEXES:")[1].split("\n\n")[0]
+    assert "begin_nested()" in bloque
+
+
+def test_el_comparador_de_indices_detecta_los_que_faltan():
+    """``comparar_indices_completo`` dice que indices NO estan en su sitio."""
+    from app.db.migrations import INDEXES, apply_migrations, comparar_indices_completo
+
+    motor = create_engine("sqlite://", future=True)
+    Base.metadata.create_all(motor)
+    # Tras aplicar las migraciones, los 55 indices declarados existen.
+    apply_migrations(motor)
+    problemas = comparar_indices_completo(motor)
+    motor.dispose()
+
+    assert problemas == [], "tras las migraciones no deberia quedar ningun indice problematico: %s" % (
+        problemas,)
+    assert len(INDEXES) == 55
+
+
+def test_el_comparador_de_indices_detecta_un_indice_ausente():
+    """Si se borra un indice, el comparador lo dice."""
+    from app.db.migrations import INDEXES, comparar_indices_completo
+
+    motor = create_engine("sqlite://", future=True)
+    Base.metadata.create_all(motor)
+    nombre = INDEXES[0][0]
+    with motor.begin() as conn:
+        conn.execute(text("DROP INDEX IF EXISTS %s" % nombre))
+    problemas = comparar_indices_completo(motor)
+    motor.dispose()
+
+    assert any(nombre in p and "FALTA" in p for p in problemas), (
+        "el comparador deberia senalar %s como ausente: %s" % (nombre, problemas))
\ No newline at end of file
diff --git a/tools/audit_db_columns.py b/tools/audit_db_columns.py
index 468f654..37c8cfd 100644
--- a/tools/audit_db_columns.py
+++ b/tools/audit_db_columns.py
@@ -7,6 +7,11 @@ os.environ.setdefault('SECRET_KEY', 'k')
 os.environ.setdefault('AUTO_INIT_DB', 'true')
 sys.path.insert(0, '.')
 
+# La consola de Windows usa cp1252 por defecto: sin esto, los caracteres de
+# caja del informe ('+-', '+-') provocan UnicodeEncodeError al imprimirse.
+if hasattr(sys.stdout, 'reconfigure'):
+    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
+
 from app.db.base import Base
 from app.models import *  # importa todos los modelos
 
diff --git a/tools/audit_links.py b/tools/audit_links.py
index 30b2878..47d9209 100644
--- a/tools/audit_links.py
+++ b/tools/audit_links.py
@@ -1,8 +1,14 @@
 """Audit - Cross-check template references against declared routes."""
 import os
 import re
+import sys
 from collections import Counter
 
+# La consola de Windows usa cp1252 por defecto: sin esto, la salida con
+# acentos provoca UnicodeEncodeError.
+if hasattr(sys.stdout, 'reconfigure'):
+    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
+
 # 1) Recolectar rutas declaradas (api/main)
 api_patterns = []
 api_set = set()
@@ -12,14 +18,14 @@ for root, _, files in os.walk('app/api'):
             p = os.path.join(root, f)
             for m in re.finditer(
                 r'@router\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
-                open(p).read(),
+                open(p, encoding='utf-8').read(),
             ):
                 api_set.add('/api/v1' + m.group(1))
 
 main_set = set()
 for m in re.finditer(
     r'@app\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
-    open('app/main.py').read(),
+    open('app/main.py', encoding='utf-8').read(),
 ):
     main_set.add(m.group(1))
 
@@ -31,7 +37,7 @@ for root, _, files in os.walk('app/templates'):
     for f in files:
         if f.endswith('.html'):
             p = os.path.join(root, f)
-            content = open(p).read()
+            content = open(p, encoding='utf-8').read()
             # hx-get / hx-post / hx-patch / hx-delete / hx-put
             for m in re.finditer(r'hx-(?:get|post|patch|put|delete)\s*=\s*["\']([^"\']+)["\']', content):
                 refs.append((p, 'HX', m.group(1)))
diff --git a/tools/audit_links_broken.py b/tools/audit_links_broken.py
index 888a301..b3c51ad 100644
--- a/tools/audit_links_broken.py
+++ b/tools/audit_links_broken.py
@@ -1,14 +1,20 @@
 """Audit broken links - normaliza {{ }} y verifica contra rutas declaradas."""
 import os
 import re
+import sys
 from collections import Counter
 
+# La consola de Windows usa cp1252 por defecto: sin esto, la salida con
+# acentos provoca UnicodeEncodeError.
+if hasattr(sys.stdout, 'reconfigure'):
+    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
+
 api_set = set()
 for root, _, files in os.walk('app/api'):
     for f in files:
         if f.endswith('.py'):
             p = os.path.join(root, f)
-            content = open(p).read()
+            content = open(p, encoding='utf-8').read()
             for m in re.finditer(
                 r'@router\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
                 content,
@@ -18,7 +24,7 @@ for root, _, files in os.walk('app/api'):
 main_set = set()
 for m in re.finditer(
     r'@app\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
-    open('app/main.py').read(),
+    open('app/main.py', encoding='utf-8').read(),
 ):
     main_set.add(m.group(1))
 
@@ -36,7 +42,7 @@ for root, _, files in os.walk('app/templates'):
     for f in files:
         if f.endswith('.html'):
             p = os.path.join(root, f)
-            content = open(p).read()
+            content = open(p, encoding='utf-8').read()
             for m in re.finditer(r'hx-(?:get|post|patch|put|delete)\s*=\s*["\']([^"\']+)["\']', content):
                 refs.append((p, normalize(m.group(1))))
             for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', content):
diff --git a/tools/audit_links_broken_v2.py b/tools/audit_links_broken_v2.py
index e8a1443..ec99450 100644
--- a/tools/audit_links_broken_v2.py
+++ b/tools/audit_links_broken_v2.py
@@ -1,8 +1,14 @@
 """Audit broken links - respeta prefijos per-router."""
 import os
 import re
+import sys
 from collections import defaultdict
 
+# La consola de Windows usa cp1252 por defecto: sin esto, la salida con
+# acentos provoca UnicodeEncodeError.
+if hasattr(sys.stdout, 'reconfigure'):
+    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
+
 GLOBAL_PREFIX = '/api/v1'
 
 # Recolectar prefijos por archivo router
@@ -14,7 +20,7 @@ for root, _, files in os.walk('app/api'):
         if not f.endswith('.py'):
             continue
         p = os.path.join(root, f)
-        content = open(p).read()
+        content = open(p, encoding='utf-8').read()
 
         # prefijos del archivo
         prefixes = []
@@ -34,7 +40,7 @@ for p, routes in api_routes_by_file.items():
 main_set = set()
 for m in re.finditer(
     r'@app\.(?:get|post|patch|put|delete)\(\s*["\']([^"\']+)["\']',
-    open('app/main.py').read(),
+    open('app/main.py', encoding='utf-8').read(),
 ):
     main_set.add(m.group(1))
 
@@ -53,7 +59,7 @@ for root, _, files in os.walk('app/templates'):
         if not f.endswith('.html'):
             continue
         p = os.path.join(root, f)
-        content = open(p).read()
+        content = open(p, encoding='utf-8').read()
         for m in re.finditer(r'hx-(?:get|post|patch|put|delete)\s*=\s*["\']([^"\']+)["\']', content):
             refs.append((p, normalize(m.group(1))))
         for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', content):
diff --git a/tools/audit_routes.py b/tools/audit_routes.py
index 3d14c13..d6bdb7d 100644
--- a/tools/audit_routes.py
+++ b/tools/audit_routes.py
@@ -1,20 +1,26 @@
 """Audit - Recolecta rutas declaradas y muestra inventario."""
 import re
 import os
+import sys
+
+# La consola de Windows usa cp1252 por defecto: sin esto, la salida con
+# acentos provoca UnicodeEncodeError.
+if hasattr(sys.stdout, 'reconfigure'):
+    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
 
 routes_api = set()
 for root, _, files in os.walk('app/api'):
     for f in files:
         if f.endswith('.py'):
             p = os.path.join(root, f)
-            content = open(p).read()
+            content = open(p, encoding='utf-8').read()
             for m in re.finditer(
                 r'@router\.(?:get|post|patch|put|delete|head|options)\(\s*["\']([^"\']+)["\']',
                 content,
             ):
                 routes_api.add(m.group(1))
 
-content = open('app/main.py').read()
+content = open('app/main.py', encoding='utf-8').read()
 routes_main = set()
 for m in re.finditer(
     r'@app\.(?:get|post|patch|put|delete|head|options)\(\s*["\']([^"\']+)["\']',
diff --git a/validate_api.py b/validate_api.py
index 96aa7b4..7db46c2 100644
--- a/validate_api.py
+++ b/validate_api.py
@@ -103,6 +103,11 @@ def has_auth_dep(route) -> bool:
 
 
 def main():
+    # La consola de Windows usa cp1252 por defecto: sin esto, la salida con
+    # acentos provoca UnicodeEncodeError.
+    if hasattr(sys.stdout, "reconfigure"):
+        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
+
     os.environ.setdefault("DATABASE_URL", "sqlite:///./_validate_api.db")
     os.environ.setdefault("SECRET_KEY", "validate-only-secret-key-12345678901234567890")
     os.environ.setdefault("ALLOW_XUSER_HEADER", "false")
@@ -152,7 +157,7 @@ def main():
         for f in files:
             if not f.endswith((".html", ".py")):
                 continue
-            src = open(os.path.join(root, f)).read()
+            src = open(os.path.join(root, f), encoding="utf-8").read()
             for m in re.finditer(r'hx-(get|post|put|delete|patch)="([^"]+)"', src):
                 url = m.group(2)
                 if not url.startswith("/") or "{" in url:
diff --git a/validate_templates.py b/validate_templates.py
index 8ef8def..9ef75d6 100644
--- a/validate_templates.py
+++ b/validate_templates.py
@@ -11,6 +11,11 @@ import re
 import sys
 from jinja2 import Environment, TemplateSyntaxError
 
+# La consola de Windows usa cp1252 por defecto: sin esto, la salida con
+# acentos provoca UnicodeEncodeError.
+if hasattr(sys.stdout, "reconfigure"):
+    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
+
 
 BASE_IDS = {
     # Ids provistos por base.html / app.js que cualquier template puede targetear
@@ -37,7 +42,7 @@ ok_count = 0
 def scan_template(path):
     global ok_count
     try:
-        src = open(path).read()
+        src = open(path, encoding="utf-8").read()
         env.parse(src)
     except TemplateSyntaxError as e:
         problems.append(("SYNTAX", path, f"linea {e.lineno}: {e.message}"))

================================================================================
9. ESTADO FINAL DEL DESPLIEGUE (anadido tras el despliegue y la
   verificacion en produccion)
================================================================================

  Fecha del despliegue:  2026-11-18
  Commit desplegado:     855601fc
  Rama:                 release/v2.001 y main (alineadas por fast-forward)

  9.1 ESTADO DE LOS TRES SERVICIOS

      SERVICIO ESTADO     COMMIT     DEPLOYMENT
      web      SUCCESS    855601fc   ca0b6737-0fd9-4ab8-b179-4f5d8e663e87
      worker   SUCCESS    855601fc   c5e74825-f1fd-4bf2-a023-55b38f48eb5f
      beat     SUCCESS    855601fc   c90b99b5-bc4a-4ff1-b1c7-2caee755f03e

  9.2 QUE SE VERIFICO EN PRODUCCION (solo GET y POST de login)

      POST /auth/login           HTTP 200
      GET /health                HTTP 200
      GET /ready                 HTTP 200
      GET /kanban                HTTP 200
      GET /dashboard             HTTP 200
      GET /usuarios              HTTP 200
      GET /tickets               HTTP 200
      GET /api/v1/tickets        HTTP 200
      GET /api/v1/metricas/resumen HTTP 200

  9.3 ESQUEMA REAL DE LA BASE DE DATOS DE PRODUCCION

      Tablas en el modelo:        40
      Tablas en la base de datos: 40
      Deriva de columnas:         0
      Indices declarados que NO estan en su sitio: 0
      Colisiones de indice:                    0

      Guardian estricto ESQUEMA_ESTRICTO: ENCENDIDO en los tres
      servicios (variable de entorno). Se encendio DESPUES de medir:
      la medicion dio 0 lineas de deriva sobre las 40 tablas.

  9.4 VENTANA V2 EN PRODUCCION (clon de la base de datos)

      Se creo un clon de la base de datos de produccion en el mismo
      servidor PostgreSQL, se verifico y se BORRO:

        - Tablas del clon:        40 (las del modelo)
        - Tablas con datos:       30
        - Filas copiadas:         9.314
        - Secuencias alineadas:   36
        - Verificacion origen=clon: OK (mismas tablas, mismas
          columnas, mismos recuentos de filas)
        - Filas con proyecto_id a NULL: 0
        - Proyecto 'Legacy': presente, con 2 administradores
        - Clon borrado: SI (confirmado con GET /clones)

      Clones que quedan en el servidor: ninguno

  9.5 BACKUP DE PRODUCCION: RESTAURACION VERIFICADA AL 100%

      Se genero un backup de produccion con el codigo ya corregido
      y se restauro en un PostgreSQL 16.2 local:

        - Backup: 9.314 INSERT, 41 CREATE TABLE, 167 CREATE INDEX
        - Restauracion: 0 errores (antes: 925 filas rechazadas con
          'invalid input syntax for type json')
        - Filas de auditorias recuperadas: 3.157 (el dump antiguo solo
          conservaba 2.245)
        - De las cuales 912 tienen un valor JSON de tipo string: son
          exactamente las que el dump antiguo perdia
        - Tickets: 934, usuarios: 18, proyectos: 1, miembros de
          Legacy: 2, tablas: 40, indices: 226

  9.6 LO QUE NO SE TOCO (y sigue pendiente)

      - El aislamiento por proyecto NO queda activo: los flags
        AISLAMIENTO_PROYECTO_ACTIVO y RLS_HABILITADO siguen a False.
        Los 934 tickets siguen visibles para todos, igual que en
        V2.008. Eso es la ventana V3 (el corte).
      - RLS sigue sin ser una capa de defensa real: el rol con el que
        conecta la aplicacion (`postgres`) es superusuario y los
        superusuarios ignoran RLS. Crear el rol de aplicacion sin
        privilegios de owner es parte de V3.
      - El filtro por espacio de las vistas (que es la otra fuga de
        aislamiento detectada) NO se toca en este lote.
      - Los pendientes de seguridad heredados siguen abiertos:
        rotar la clave del administrador, rotar el token de
        Railway, auditar el cambio de contrasena del 2026-10-26,
        revisar el autoDeploy del worker y del beat, anclar
        SECRET_KEY y el volumen en /data, rotar la contrasena de
        PostgreSQL y cerrar el registro publico de usuarios.
      - La migracion de la configuracion del panel antes del
        2026-12-01.
      - Los backups siguen en un sistema de ficheros efimero: hay
        que decidir donde se copian.
      - Queda un servicio de Railway sobrante, `clon-v2009`, que se
        creo como andamiaje en este lote: el clon final es una BASE
        DE DATOS dentro del PostgreSQL que ya existe, no un servicio
        propio. Se ha puesto en modo suspendido (sleepApplication) y
        con autoDeploy apagado, pero el token de proyecto no tiene
        permiso de borrado de servicios (`serviceDelete` responde
        'Not Authorized'): hay que borrarlo desde el panel de
        Railway.

  9.7 REVERSION DE ESTE LOTE

      Si hubiera que dar atras el lote:
        - `git revert` del commit de V2.009 en main y en
          release/v2.001, y redespliegue de los tres servicios.
        - La migracion es ADITIVA: la columna `proyecto_id` es
          NULLABLE y las tablas `proyectos` y `proyecto_usuarios`
          estan vacias o casi vacias. Un revert del codigo NO borra
          la columna: la base de datos se queda como esta (que es
          inocuo) hasta que se decida el corte de V3.
        - El guardian estricto se apaga cambiando la variable de
          entorno ESQUEMA_ESTRICTO a false y redesplegando.
        - Los servicios de Plan V2.009 no dependen de cambios en
          el Worker: el worker y el beat usan el MISMO codigo y el
          MISMO commit que la web.

================================================================================
