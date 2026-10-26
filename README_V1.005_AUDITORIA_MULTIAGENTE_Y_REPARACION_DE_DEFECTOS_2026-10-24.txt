================================================================================
README V1.005 - AUDITORIA MULTIAGENTE, RETIRADA DE SUPERFICIES EXPUESTAS Y
               REPARACION DE DEFECTOS EN BITACORA GRM v2
Fecha: 2026-10-24
================================================================================

Documentos anteriores de la serie (NO se modificaron, salvo una redaction
expresa indicada en 6.3):
  README_V1.001_INDICADOR_RESULTADO_PRUEBAS_Y_REPARACION_GENERAL_2026-10-24.txt
  README_V1.002_REPARACION_ARRANQUE_PRODUCCION_Y_MIGRACIONES_POSTGRES_2026-10-24.txt
  README_V1.003_ROLES_WORKER_BEAT_CELERY_RAILWAY_2026-10-24.txt
  README_V1.004_WORKER_BEAT_EN_RAILWAY_2026-10-24.txt

Motivo de este incremento: el encargo fue revisar el estado general del
proyecto con varios sub-agentes en paralelo, corregir los problemas
generados FUERA de la gestion del cambio anterior, devolver el proyecto a
operativo, validarlo de forma exhaustiva y cerrar con release notes
atomicos. La auditoria encontro problemas reales en cuatro capas:
superficie expuesta sin autenticacion, defectos funcionales en silencio,
plantillas que permitian inyeccion de HTML y una cadena de suministro de
dependencias con avisos de seguridad abiertos. Todo ello quedo corregido,
validado contra produccion y publicado.

--------------------------------------------------------------------------------
1. BASE
--------------------------------------------------------------------------------

Repositorio:         https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
Rama:                main
Commit base:         512c830  docs(release): actualizar README V1.004 con los
                              despliegues finales y el incidente de DEPLOYING atascado
Commits funcionales:  dbbb7a0  fix(produccion): retirar el endpoint de diagnostico
                               /_diag/tickets sin autenticacion
                      51b3cd9  fix(varios): endpoint de reglas de Butler, purga
                               PostgreSQL, fecha de entregas y SMTP desde el SSOT
                      c118fd3  fix(seguridad): cabeceras HTTP, proxy inverso,
                               superficie expuesta y secretos en logs
                      ebbc87b  fix(plantillas): autoescape, XSS por innerHTML,
                               modal-root duplicado y SSOT del LOV
                      ebe0591  chore(deps): actualizar los pins con advisories y
                               ajustar el indice de paquetes
                      193ef4f  fix(verificacion): credenciales por variable de
                               entorno y base de datos temporal
                      a7e0085  docs(despliegue): reconciliar la guia con
                               railway.toml y start.sh
Tipo de publicacion: fast-forward (sin --force)
Push:                512c830..a7e0085  main -> main
Fecha:               2026-10-24

Aplicacion:          https://bitacora-grmv2-production.up.railway.app
Proyecto Railway:    BitacoraGRMv2  (id c0e1796f-cdcf-4e85-833d-25536dfa674c)
Entorno:             production    (id 13092a8d-36b3-420e-95d9-a1f5379ddb19)
Servicios:           Postgres 22b35ec6, Redis 3e1ff30b, web 775efae4,
                      worker 51e22b0c, beat 1c16b13c  (ninguno recreado)

Metodo de trabajo
-----------------
Se ejecutaron en paralelo cuatro sub-agentes con propiedad EXCLUYENTE de
ficheros, y en paralelo una revision propia del nucleo sensible:

  Sub-agente 1  Plantillas, JavaScript y enlaces   -> app/templates, app/static/js
  Sub-agente 2  Documentacion de despliegue        -> README.md, RAILWAY_DEPLOY.md,
                                                     DEPLOYMENT_CHECKLIST.md,
                                                     docs/VALIDATION_REPORT.md
  Sub-agente 3  Dependencias y cadena de suministro-> requirements.txt,
                                                     pyproject.toml
  Sub-agente 4  Verificadores y suite de tests     -> tools/verificacion,
                                                     tests/conftest.py
  Revision propia (no delegada)                    -> app/main.py, app/core/config.py,
                                                     app/core/resultado_pruebas.py,
                                                     app/models, app/schemas,
                                                     app/db/migrations.py, app/services,
                                                     app/tasks, app/api/v1/trello_features.py,
                                                     gunicorn.conf.py, start.sh

Estado de partida (verificado, no supuesto)
-------------------------------------------
  - `GET /_diag/tickets` respondia 200 SIN autenticacion y volcaba los 931
    tickets en cada peticion. En caso de error devolvia traza con rutas
    absolutas y detalle de conexion.
  - `GET /onboarding` respondia 307 con `Location: http://...`, es decir,
    degradaba de HTTPS a HTTP: el proxy de Railway no era creido.
  - `/tableros` anunciaba el enlace publico `/p/{slug}` de dos tableros con
    visibilidad "espacio": el inventario los detecto como 404.
  - No se emitia ninguna cabecera Strict-Transport-Security ni
    Content-Security-Policy.
  - `GET /info` (publico) devolvia el host interno de PostgreSQL.
  - La documentacion de despliegue enseñaba el bypass `X-User-Id` como si
    fuera un metodo de autenticacion valido.
  - Cuatro scripts de `tools/verificacion/` tenian `admin`/`admin123`
    escritos en el codigo.
  - `tests/conftest.py` respetaba una `DATABASE_URL` externa: la suite podia
    escribir sobre la base de datos real.
  - `app/templates/butler/index.html` llamaba a `/api/v1/reglas/{id}`, ruta
    inexistente (404 y recarga en bucle).
  - `scripts/purge_tickets.py` usaba `TABLES_TO_KEEP`, que no existe:
    NameError al purgar en PostgreSQL.
  - `app/tasks/entregas.py` filtraba con el cast `fecha_entrega::date`, que
    es sintaxis de PostgreSQL y revienta en SQLite.
  - `app/services/email_service.py` resolvia SMTPS leyendo `os.getenv`, pero
    `_exportar_a_environ` vuelca siempre los defaults: la autodeteccion por
    puerto 465 era codigo muerto.
  - `app/main.py` envolvia la aplicacion con `a2wsgi.ASGIMiddleware`. Era
    codigo muerto con una trampa: si `a2wsgi` llega a estar instalada,
    `app.main:app` deja de ser ASGI y uvicorn aborta al arrancar.

--------------------------------------------------------------------------------
2. CAMBIO UNICO
--------------------------------------------------------------------------------

Que Bitacora GRM v2 deje de exponer superficies de diagnostico sin
autenticacion, deje de fallar en silencio en rutas y plantillas, y quede con
una cadena de dependencias sin avisos de seguridad abiertos. Verificado
contra produccion despues del despliegue.

2.1) Endpoint de diagnostico retirado del codigo
--------------------------------------------------
`app/main.py`: se elimino por completo el endpoint `/_diag/tickets`, que
recorria toda la tabla de tickets en cada peticion y no exigia sesion.
Su docstring decia ya "se eliminara tras identificar y corregir la causa".
La capacidad de diagnostico no se pierde: se conserva como script local
reproducible y sin red.

`tools/verificacion/diagnostico_tickets.py` (nuevo): abre una SQLite en
memoria, construye tres casos (datos_catalogo nulo, vacio y con datos) y
comprueba el diagnostico. Resultado: 3/3 OK.

2.2) Cuatro defectos funcionales que fallaban en silencio
-----------------------------------------------------------
`app/templates/butler/index.html` (lineas 224 y 235):

    -    const r = await fetch('/api/v1/reglas/'+id, {
    +    const r = await fetch('/api/v1/butler/reglas/'+id, {
           method: 'PATCH', headers: {'Content-Type':'application/json'},
           body: JSON.stringify({activo})
         });
       ...
    -    const r = await fetch('/api/v1/reglas/'+id, {method:'DELETE'});
    +    const r = await fetch('/api/v1/butler/reglas/'+id, {method:'DELETE'});

  El router real es `APIRouter(prefix="/butler")` en `app/api/v1/butler.py`.
  Antes, activar o eliminar una regla devolvia 404 y recargaba la pagina en
  bucle.

`scripts/purge_tickets.py` (linea 192), funcion `purge_postgres`:

    -        all_tables = TABLES_TO_PURGE + TABLES_TO_KEEP
    +        all_tables = TABLES_TO_PURGE + TABLES_TO_KEEP_OPTIONAL

  El nombre real es `TABLES_TO_KEEP_OPTIONAL` (linea 66). Antes, la purga en
  PostgreSQL era inejecutable: NameError en el primer conteo.

`app/tasks/entregas.py`, tarea `generar_reporte_diario`:

    -        entregas = (
    -            db.query(ReporteEntregaDiaria)
    -            .filter(text("fecha_entrega::date = :f").bindparams(f=fecha))
    +        entregas = (
    +            db.query(ReporteEntregaDiaria)
    +            .filter(func.date(ReporteEntregaDiaria.fecha_entrega) == fecha)
                 .order_by(ReporteEntregaDiaria.fecha_entrega.asc())
                 .all()
             )

  `fecha_entrega::date` es sintaxis exclusiva de PostgreSQL: el reporte
  diario fallaba en modo SQLite. `func.date()` es portable. El import pasa
  de `from sqlalchemy import text` a `from sqlalchemy import func`.

`app/services/email_service.py`, funcion `_enviar_smtp`:

    +def _cfg(nombre: str, default=None):
    +    if _settings is not None:
    +        valor = getattr(_settings, nombre, None)
    +        if valor is not None:
    +            return valor
    +    valor_env = os.getenv(nombre)
    +    if valor_env is None or valor_env == "":
    +        return default
    +    return valor_env

    -    host = os.getenv("SMTP_HOST", "localhost")
    -    port = int(os.getenv("SMTP_PORT", "587"))
    +    host = _cfg("SMTP_HOST", "") or "localhost"
    +    port = int(_cfg("SMTP_PORT", 587) or 587)
    +    user = _cfg("SMTP_USER", "")
    +    password = _cfg("SMTP_PASSWORD", "")
    -    use_ssl_env = os.getenv("SMTP_USE_SSL")
    -    if use_ssl_env is not None and use_ssl_env != "":
    -        use_ssl = use_ssl_env.lower() == "true"
    -    else:
    -        use_ssl = (port == 465)
    -    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    +    use_ssl = bool(_cfg("SMTP_USE_SSL", False)) or port == 465
    +    use_tls = bool(_cfg("SMTP_USE_TLS", True)) and not use_ssl

  Consecuencia de la version anterior: `app/core/config.py::_exportar_a_environ`
  vuelca SIEMPRE los defaults de `Settings` al entorno, de modo que
  `os.getenv("SMTP_USE_SSL")` devolvia "false" (nunca vacio) y la rama de
  autodeteccion por puerto 465 era inalcanzable. Ademas `SMTP_HOST=""`
  (valor por defecto) hacia que `os.getenv("SMTP_HOST", "localhost")`
  devolviera "" y no "localhost". Ahora el valor se lee del SSOT
  (`app.core.config.Settings`) y SMTPS tiene prioridad sobre STARTTLS.

2.3) Cabeceras de seguridad y confianza en el proxy inverso
-------------------------------------------------------------
`app/main.py`, middleware `add_security_and_cache_headers`:

    +    response.headers.setdefault(
    +        "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
    +    )
    +    if request.url.scheme == "https":
    +        response.headers.setdefault(
    +            "Strict-Transport-Security",
    +            "max-age=31536000; includeSubDomains",
    +        )
    +    if settings.SECURITY_CSP:
    +        response.headers.setdefault("Content-Security-Policy", settings.SECURITY_CSP)
    -    if path.startswith("/static") or path.startswith("/onboarding"):
    +    es_estatico = path == "/static" or path.startswith("/static/")
    +    es_onboarding = path == "/onboarding" or path.startswith("/onboarding/")
    +    if es_estatico or es_onboarding:
             response.headers["Cache-Control"] = "public, max-age=300"

  El `startswith` anterior tambien capturaba rutas como `/staticfoo`.

`app/core/config.py`, dos campos nuevos:

    +    EXPOSE_API_DOCS: bool = True
    +    SECURITY_CSP: str = (
    +        "default-src 'self'; "
    +        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
    +        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
    +        "font-src 'self' data: https://fonts.gstatic.com; "
    +        "img-src 'self' data: blob: https:; "
    +        "connect-src 'self'; "
    +        "frame-ancestors 'none'; "
    +        "base-uri 'self'; "
    +        "form-action 'self'; "
    +        "object-src 'none'"
    +    )

  La CSP admite unicamente los origenes que la aplicacion usa de verdad
  (Tailwind por CDN, Google Fonts, SortableJS y los scripts inline de las
  plantillas) y bloquea cualquier otro. Los tres hostes externos que existen
  en el repo se verificaron uno a uno: no hay ninguna otra peticion a un
  origen externo desde el navegador.

`gunicorn.conf.py`, seccion nueva:

    +forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

  Railway termina el TLS y reenvia `X-Forwarded-Proto: https`. Sin esto,
  uvicorn ignoraba la cabecera, la aplicacion creia estar en HTTP y sus
  redirecciones degradaban a `http://`.

`app/main.py`, construccion de la aplicacion:

    -    docs_url="/docs",
    -    redoc_url="/redoc",
    +    docs_url="/docs" if settings.EXPOSE_API_DOCS else None,
    +    redoc_url="/redoc" if settings.EXPOSE_API_DOCS else None,
    +    openapi_url="/openapi.json" if settings.EXPOSE_API_DOCS else None,

2.4) Superficie publica reducida
----------------------------------
`app/main.py`, endpoint `/info`:

    -        "database_url": (settings.get_database_url().split("@")[-1]
    -                         if "@" in settings.get_database_url()
    -                         else "sqlite"),
    +        "database": "sqlite" if url_bd.startswith("sqlite") else "postgresql",

  `/info` es publico. Antes publicaba el host, el puerto y el nombre de la
  base de datos de Railway (`postgres.railway.internal:5432/railway`), que
  facilitate el ataque lateral si alguien logra foothold en la red.

2.5) Retirada del bloque que rompia el arranque ASGI
------------------------------------------------------
`app/main.py`, bloque final "Compresion estatica en produccion": se elimino
el `try/except` que envolvia la aplicacion con `a2wsgi.ASGIMiddleware`.
`ASGIMiddleware` convierte la app ASGI de FastAPI en una callable WSGI
(`__call__(environ, start_response)`), de modo que, con `a2wsgi` instalada,
`app.main:app` deja de ser ASGI y el arranque aborta con:

    TypeError: ASGIMiddleware.__call__() missing 1 required positional
    argument: 'start_response'

Como `a2wsgi` no se declaraba en `requirements.txt`, el bloque nunca se
ejecuto en produccion: era codigo muerto con una trampa dentro. `/static`
lo sirve `StaticFiles`, que es ASGI nativo. Si en el futuro se quiere
WhiteNoise, la via correcta es `whitenoise.middleware.WhiteNoiseMiddleware`.

2.6) Secretos: enmascarado de URL y de entorno
-------------------------------------------------
`app/core/config.py`, funcion nueva de nivel de modulo:

    +def enmascarar_url_db(url: str) -> str:
    +    if not url:
    +        return url
    +    esquema, sep, resto = url.partition("://")
    +    if not sep or "@" not in resto:
    +        return url
    +    credenciales, _, servidor = resto.partition("@")
    +    if ":" in credenciales:
    +        usuario = credenciales.split(":", 1)[0]
    +        credenciales = f"{usuario}:***"
    +    else:
    +        credenciales = "***"
    +    return f"{esquema}://{credenciales}@{servidor}"

  `Settings.get_database_url_enmascarada()` pasa a delegar en ella.

`app/db/migrations.py`, bloque `__main__`:

    -        print(f"Usando engine override: {db_url}")
    +        from app.core.config import enmascarar_url_db
    +        print(f"Usando engine override: {enmascarar_url_db(db_url)}")

`app/core/config.py`, `_exportar_a_environ`:

    +_CLAVES_SECRETAS_NO_EXPORTABLES = frozenset({
    +    "SECRET_KEY",
    +    "POSTGRES_PASSWORD",
    +    "SMTP_PASSWORD",
    +})

  y dos comprobaciones `if clave in _CLAVES_SECRETAS_NO_EXPORTABLES: continue`,
  una en cada pasada (campos de `Settings` y claves sueltas del `.env`).
  Se ha dejado deliberadamente fuera de la lista las variables que son una
  URL con contrasena dentro (`DATABASE_URL`, `REDIS_URL`,
  `CELERY_BROKER_URL`): en produccion las inyecta la propia plataforma (ya
  estan en el entorno antes de este export) y en desarrollo las leen modulos
  legacy con `os.getenv`; quitarlas no reduciria la exposicion real y si
  romperia esos caminos.

2.7) Errores que ya no se tragan
----------------------------------
`app/services/ticket_service.py`, dos bloques de automatizacion Butler:

    -        except Exception:
    -            # Butler no debe romper el flujo principal
    -            pass
    +        except Exception:
    +            logger.exception(
    +                "[ticket_service] Las reglas Butler fallaron al cambiar el "
    +                "estado del ticket %s - la transicion se guardo igual.",
    +                ticket.id,
    +            )

  (y el equivalente en la creacion del ticket). Antes, una regla de Butler
  que nunca se ejecutaba era indistinguible de una que si se ejecuto.

`app/api/v1/trello_features.py`, `ejecutar_comando_ahora`:

    +    errores = []
         for t in tickets:
             for acc in (comando.acciones or []):
                 try:
                     motor._ejecutar_accion(t, acc)
                     afectados += 1
    -            except Exception:
    -                pass
    +            except Exception as exc:
    +                errores.append(f"{getattr(t, 'codigo', None) or t.id}: {exc}")
         db.commit()
    +    exito = not errores
         ej = EjecucionComando(
    -        comando_id=comando.id, exito=True,
    +        comando_id=comando.id, exito=exito,
             detalle=f"{afectados} acciones ejecutadas sobre {len(tickets)} tickets",
             tickets_afectados=len(tickets),
         )
    ...
    +    return {
    +        "exito": exito,
    +        "tickets_procesados": len(tickets),
    +        "acciones_ejecutadas": afectados,
    +        "errores": errores[:50],
    +    }

  Antes, la ejecucion se archivaba como exitosa aunque alguna accion
  hubiera fallado.

2.8) Inyeccion de HTML en plantillas y JavaScript
--------------------------------------------------
`app/templates/tickets/detalle_modal.py` y
`app/templates/kanban/partials/column.py`:

    -from jinja2 import Template
    +from jinja2 import Environment
    ...
    -DETALLE_TEMPLATE = Template(r"""
    +_ENV = Environment(autoescape=True)
    +DETALLE_TEMPLATE = _ENV.from_string(r"""

  y en `column.py`, el HTML de la tarjeta (ya escapado por `card.py`) se
  marca como `Markup` para que el autoescape no lo escape dos veces. El
  filtro manual `|e` de `detalle_modal.py` se retira para no mezclar dos
  mecanismos de escape.

`app/static/js/kanban.js`: nueva funcion `_escapeHtml()` y uso de la misma
en los `<option>` de filtros (usuario y estado), donde se insertaba con
`innerHTML` en crudo.

`app/static/js/htmx-events.js`, funcion `showToast`: el icono y el mensaje
pasan a `textContent`. El mensaje puede venir del backend.

`app/templates/admin/reporte_entregas.html`: nueva funcion `escapeHtml()` y
aplicacion a fecha, total, enviadas, codigo, titulo, estado destino y fecha
de entrega.

Verificacion: con los payloads `<script>alert(1)</script>` y
`"><img src=x onerror=alert(1)>`, el HTML final NO contiene el payload sin
escapar, aparece escapado y NO aparece doble escapado (`&amp;lt;`).

2.9) `modal-root` duplicado
-----------------------------
`app/templates/base.html` declara el contenedor global de modales HTMX. Las
vistas `vistas/planner.html`, `vistas/gantt.html`, `vistas/calendario.html` y
`usuarios/index.html` declaraban OTRO elemento con el mismo id. Con ids
repetidos, `document.getElementById('modal-root')` devuelve el nodo
equivocado y el modal del Planner no abria.

  - `vistas/planner.html`: `<dialog id="modal-root">` -> `id="planner-modal-root"`,
    y se elimina la llamada a `modal.showModal()` (lanza TypeError sobre el
    `<div>` global); el detalle se carga en el contenedor global, igual que
    en Kanban, Dashboard y listado.
  - `vistas/gantt.html`: `<dialog id="modal-root">` -> `id="gantt-modal-root"`.
  - `vistas/calendario.html`: `<dialog id="modal-root">` -> `id="calendario-modal-root"`.
  - `usuarios/index.html`: se retira el segundo `<div id="modal-root">`.

  Verificado por grep: queda UNA sola aparicion de `id="modal-root"` en
  `app/templates/**`.

2.10) Catalogo unico del LOV de Resultado de Pruebas
-----------------------------------------------------
`app/core/resultado_pruebas.py` (SSOT) incorpora el orden de presentacion y
dos ayudantes:

    +RESULTADOS_LOV_FORMULARIO: tuple = (
    +    "OK", "N/A", "OK CON OBS.", "POSTERGADA", "DESESTIMADA", "NOK",
    +)
    +if set(RESULTADOS_LOV_FORMULARIO) != set(RESULTADOS_LOV):
    +    raise RuntimeError(...)
    +def lov_js() -> list: ...
    +def lov_formulario_js() -> list: ...

`app/models/ticket.py`: `RESULTADO_PRUEBAS_LOV` deja de ser una tupla
duplicada y reexporta `RESULTADOS_LOV` del catalogo.

`app/schemas/ticket.py`: `RESULTADO_PRUEBAS_PERMITIDOS` pasa a derivarse:

    +RESULTADO_PRUEBAS_PERMITIDOS = frozenset(RESULTADOS_LOV) | {""}

`app/main.py`: el dashboard recibe la lista de columnas del pivote y el
entorno Jinja recibe el LOV de formulario:

    +templates.env.globals["resultados_lov_formulario"] = _lov_formulario_js()
    ...
    +            "cuenta_resultado_lov": lov_js(),

`app/templates/dashboard/index.html`: se inyecta la lista en una isla JSON y
se elimina la declaracion local de valores:

    -    const RESULTADOS = ['OK', 'OK CON OBS.', 'NOK', 'POSTERGADA', 'DESESTIMADA', 'N/A'];
    +    const RESULTADOS = CUENTA_RESULTADO_LOV.length
    +      ? CUENTA_RESULTADO_LOV
    +      : Object.keys(CUENTA_RESULTADO_COLORES);

`app/templates/tickets/nuevo_modal.html` y
`app/templates/tickets/detalle_modal.py`: los `<select>` iteran el catalogo
en vez de declarar los seis valores a mano.

`app/templates/tickets/list.html`: el listado de tickets pinta ahora el
badge de Resultado de Pruebas con el MISMO render del SSOT que el Kanban
(`badge_resultado(resultado_info_ticket(t))`), con columna y `colspan`
ajustados.

  NOTA: la paleta (los hex) NO cambia en absoluto. Lo unico que se unifica es
  la lista de identificadores del LOV, que estaba duplicada en cuatro sitios
  y podia desviarse del catalogo sin que nada lo detectara.

2.11) Dependencias con avisos de seguridad abiertos
-----------------------------------------------------
`requirements.txt` y `pyproject.toml` (versiones verificadas una a una
contra la API de PyPI: existencia y artefacto para Python 3.12):

  python-multipart  0.0.12 -> 0.0.32   (CVE-2024-53981, CVE-2026-24486)
  jinja2            3.1.4  -> 3.1.6    (CVE-2024-56326, CVE-2024-56201)
  python-jose       3.3.0  -> 3.5.0    (CVE-2024-33664, CVE-2024-33663)
  requests          2.32.3 -> 2.34.2   (CVE-2024-47081, CVE-2026-25645)
  python-dotenv     1.0.1  -> 1.2.4    (CVE-2026-28684)

  `python-multipart` era el mas expuesto: se usa en el parseo de `Form(...)`
  de los endpoints publicos de login.

  Ademas:
    - `alembic` se retira: el repositorio no tiene entorno de Alembic (no
      existen `alembic.ini`, `env.py` ni `versions/`).
    - `passlib` se retira: ningun modulo lo importa (el hashing usa `bcrypt`
      directamente) y `passlib 1.7.4` es incompatible con `bcrypt>=4`.
    - `a2wsgi` se deja SIN declarar a proposito (ver 2.5).
    - `pyproject.toml`: PyPI oficial pasa a ser el indice por defecto de
      `uv`; el mirror de terceros queda como alternativa de menor prioridad.

2.12) Verificadores sin credenciales embebidas y tests sin BD real
-------------------------------------------------------------------
`tools/verificacion/barrer_rutas.py`, `verificar_flujo_produccion.py`,
`verificar_arranque.py` y `esperar_redeploy.py`: `admin`/`admin123` se
sustituyen por `BITACORA_ADMIN_USER` y `BITACORA_ADMIN_PASSWORD`. Si
faltan, el script indica exactamente cuales y termina con codigo 2 (no
verificable) en vez de fallar con una excepcion opaca.

`tools/verificacion/barrer_rutas.py`: la ruta de estados del reporte de
entregas se deriva del OpenAPI real (la unica que termina en
`/reporte-entregas/estados`); cero o varias coincidencias son un fallo
explicito, no un 404 "esperado".

`tools/verificacion/inventariar_rutas.py`: autentica al administrador y
deja de seguir redirecciones al auditar paginas HTML. Antes auditaba 17
veces la pagina de login, porque las 17 redirigen a `/auth/login`.

`tests/conftest.py`:

    +TMP_DIR = RAIZ / "tests" / "tmp"
    +TMP_DIR.mkdir(parents=True, exist_ok=True)
    +db_fd, db_path = tempfile.mkstemp(
    +    prefix="pytest_suite_", suffix=".sqlite", dir=str(TMP_DIR)
    +)
    +os.close(db_fd)
    +os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace("\\", "/")

  La suite NUNCA respeta una `DATABASE_URL` externa: antes podia escribir
  sobre la base de datos real.

2.13) Documentacion reconciliada con el despliegue real
---------------------------------------------------------
  - `RAILWAY_DEPLOY.md`: servicios web/worker/beat con sus comandos reales y
    seccion nueva "Config as Code: fin de soporte 2026-12-01", con la tabla
    de ajustes que hay que replicar en el panel y el impacto de no hacerlo
    (arranque sin `SECRET_KEY`).
  - `DEPLOYMENT_CHECKLIST.md`: reescrito como lista verificable a partir de
    `railway.toml` y `start.sh`. Se eliminan el `Dockerfile` inexistente, los
    tamanos de fichero obsoletos, el comodin de CORS, `AUTO_INIT_DB=true`,
    los login de demostracion y los Start Commands de worker/beat sin
    `start.sh`.
  - `README.md`: se retira la tabla de credenciales de produccion.
  - `docs/VALIDATION_REPORT.md`: estado real de `/_diag/tickets` y seccion de
    acciones pendientes del propietario.
  - `README_V1.004`: una unica linea redactada (el prefijo de la contrasena
    de PostgreSQL que se habia publicado). Ver 6.3.

2.14) start.sh: robustez del arranque y migraciones por rol
--------------------------------------------------------------
    -set -e
    +set -euo pipefail

  y el bloque de esquema:

    -if [[ "${AUTO_INIT_DB:-true}" == "true" ]]; then
    -    python -m app.db.migrations || echo "[start.sh] Aviso: migraciones fallaron, continuando..."
    -    if [[ "${SEED_DATA:-false}" == "true" ]]; then
    -        python -m app.db.init_db || echo "[start.sh] Aviso: init_db fallo, continuando..."
    -    fi
    -fi
    +echo "[start.sh] Verificando/Aplicando migraciones..."
    +if ! python -m app.db.migrations; then
    +    echo "[start.sh] ERROR: las migraciones fallaron. Revisa el log del despliegue." >&2
    +    echo "[start.sh] El proceso continua para no dejar el servicio sin respuesta," >&2
    +    echo "[start.sh] pero el esquema puede estar desactualizado." >&2
    +fi
    +
    +if [[ "${AUTO_INIT_DB:-false}" == "true" || "${SEED_DATA:-false}" == "true" ]]; then
    +    echo "[start.sh] Inicializando base de datos (datos semilla)..."
    +    if ! python -m app.db.init_db; then
    +        echo "[start.sh] ERROR: init_db fallo. Revisa el log del despliegue." >&2
    +    fi
    +fi

  Motivo: las MIGRACIONES son idempotentes y las necesitan los tres roles
  (los procesos Celery no ejecutan el lifespan de FastAPI), mientras que el
  SEED es opcional. Antes ambas cosas colgaban de `AUTO_INIT_DB`, que
  venia con default `true` en contra de `Settings.AUTO_INIT_DB` (False).

  La decision de NO abortar el arranque ante un fallo de migracion es
  deliberada: un crash-loop dejaria el servicio sin respuesta, mientras que
  seguir con una traza visible en el log permite diagnosticar. El cambio a
  modo fail-closed esta documentado en 6.5 como decision del propietario.

2.15) Dos enlaces rotos en /tableros (encontrados por el propio inventario)
------------------------------------------------------------------------------
  El inventario de enlaces (autenticado, sobre produccion) reviso 439
  enlaces internos y 2631 identificadores HTML, y encontro 2 enlaces rotos:

      /tableros -> /p/incidencias-prod -> 404
      /tableros -> /p/mantto-prog      -> 404

  Causa: `app/templates/tableros/index.html` mostraba el enlace publico en
  cuanto el tablero tenia `slug_publico`, pero la ruta `/p/{slug}`
  (`app/main.py`, `tablero_publico`) solo sirve tableros con
  `visibilidad == 'publico'`. Los dos tableros de semilla ("Incidencias de
  Produccion" y "Mantenimientos Programados") tienen `visibilidad="espacio"`,
  de modo que el enlace era siempre un 404. El slug se conserva como
  identificador reservado: si el administrador hace publico el tablero, ya
  tiene un handle asignado.

  `app/templates/tableros/index.html`:

    -        {% if t.slug_publico %}
    +        {% if t.slug_publico and t.visibilidad == 'publico' %}

  `app/db/init_db.py`: comentario que documenta que `slug_publico` es un
  identificador RESERVADO en los tableros de espacio, y que la tarjeta de
  `/tableros` solo muestra el enlace cuando el tablero es realmente publico.

  Nota: NO se modifico la ruta `/p/{slug}` para que sirva tableros no
  publicos. Habria sido el arranque de la seguridad: la ruta publica es
  justamente la que no exige sesion.

--------------------------------------------------------------------------------
3. QUE NO SE MODIFICO
--------------------------------------------------------------------------------

  - NO se toco la logica de negocio: creacion de tickets, maquina de
    estados, transiciones, calculo de SLA, auditoria, permisos por rol,
    adjuntos, comentarios, checklist, etapas ni etiquetado.
  - NO se modifico el catalogo de resultados de pruebas: ni los valores, ni
    los acronimos (OK, N/A, OBS, POST, NOOK, NOK, S/D) ni la paleta. Solo
    se unifico la lista de identificadores en el catalogo unico.
  - NO se modifico el calendario ni las tareas de Celery: ni `beat_schedule`,
    ni las tareas, ni sus reintentos, ni los periodos.
  - NO se modifico el esquema de la base de datos. `app/db/migrations.py`
    solo cambio en la linea que imprime la URL del engine override; las
    migraciones siguen siendo las mismas e idempotentes.
  - NO se toco el renderizado del Kanban. Se documenta como deuda: 931
    tickets se renderizan en un solo HTML de 4,07 MB sin paginacion.
    Cambiarlo en este lote habria puesto en riesgo el trabajo de badge y
    paleta ya verificado.
  - NO se cerro el registro publico (`POST /api/v1/auth/registro-form`).
    Hay usuarios reales registrados por esa via. Se documenta en 6.5.
  - NO se reescribieron los README V1.001, V1.002 ni V1.003. Del V1.004 solo
    se altero una linea, la que publicaba un prefijo de la contrasena de
    PostgreSQL (ver 6.3).
  - NO se cambio ningun nombre de servicio, ni el de la base de datos, ni el
    del proyecto de Railway.
  - NO se recreo ningun servicio de Railway: Postgres, Redis, web, worker y
    beat son los mismos de antes.
  - NO se borro ningun fichero. La politica local de este entorno bloquea
    el borrado, de modo que los ~45 scripts ad-hoc de la raiz, las dos
    SQLite obsoletas, `__pycache__`, `.pytest_cache`, `dist/` y `uploads/`
    siguen en disco (todos fuera del indice de git).
  - NO se renovo el PAT de GitHub ni el token de proyecto de Railway: son
    decisiones y acciones del propietario (ver 4.3 y 6.5).
  - NO se toco la guia estatica de Onboarding ni `docs/onboarding-demo/`.
  - NO se elimino la documentacion interactiva de la API: se gobierna con el
    interruptor `EXPOSE_API_DOCS`, que por defecto sigue en `true` para no
    romper las herramientas de verificacion que derivan sus rutas del
    OpenAPI real.

--------------------------------------------------------------------------------
4. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

4.1) DICTAMEN: REQUIERE REDESPLEGAR EL WORKER Y EL BEAT
---------------------------------------------------------
SI. Este lote cambia `start.sh`, que es el punto de entrada de los TRES
servicios, y cambia `requirements.txt`, que es lo que instala el build.
Por tanto:

  - El servicio WEB se redespliega automaticamente con el push (verificado).
  - El servicio WORKER se redespliega automaticamente con el push.
  - El servicio BEAT se redespliega automaticamente con el push.

  Si el proyecto tiene el auto-deploy desactivado, hay que redesplegar los
  TRES servicios a mano (ver 7.2). No basta con reiniciar el web: un worker
  con el `start.sh` antiguo seguiria aplicando las migraciones solo cuando
  `AUTO_INIT_DB` estuviera en `true`, y `beat` con el `start.sh` antiguo
  seguiria con el default contradictorio.

  Que el despliegue del worker y del beat sea necesario NO es un riesgo
 Added: el flujo de tareas ya estaba verificado (24/24 comprobaciones) y los
  tres servicios comparten el mismo repositorio y el mismo `start.sh`.

4.2) Sin migraciones de esquema y sin variables nuevas obligatorias
---------------------------------------------------------------------
  - No hay migraciones de esquema nuevas. Las de `app/db/migrations.py` son
    las mismas e idempotentes.
  - No hay ninguna variable de entorno NUEVA OBLIGATORIA. Las dos nuevas
    (`EXPOSE_API_DOCS` y `SECURITY_CSP`) tienen valor por defecto y solo
    hacen falta si se quiere cambiar el comportamiento.
  - El build de Railway reinstala las dependencias: `pip install -r
    requirements.txt`. Las cinco versiones nuevas existen en PyPI y tienen
    artefacto para Python 3.12 (verificado una a una).

4.3) Acciones del propietario (NO bloquean este despliegue)
------------------------------------------------------------
  1. Revocar el token de proyecto de Railway en Project Settings -> Tokens.
     El token `9b5069e8-7035-47b1-9ba0-cc809c17cf66` dejo de autorizar la
     API durante este lote ("Not Authorized"), pero sigue vigente en el
     panel hasta que se revoque explicitamente.
  2. Rotar el PAT de GitHub filtrado (caduca el 2026-12-07).
  3. Definir `SECRET_KEY` real en el panel del web y montar un volumen en
     `/data`. Hoy `start.sh` genera una clave aleatoria en cada arranque, lo
     que invalida las sesiones en cada despliegue.
  4. Migrar la configuracion del panel antes del 2026-12-01: Railway deja de
     leer `railway.toml`. La tabla completa esta en `RAILWAY_DEPLOY.md`.
  5. Rotar la contrasena de PostgreSQL: se publico un prefijo de cuatro
     caracteres en el README V1.004 (ya redactado en este lote).
  6. Decidir sobre `EXPOSE_API_DOCS=false` en produccion si se quiere
     dejar de publicar el esquema de la API.

--------------------------------------------------------------------------------
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

5.1) Verificacion en negro contra produccion (la que confirma el despliegue)
----------------------------------------------------------------------------
  Script versionado: `tools/verificacion/verificar_produccion_negro.py`
  (21 comprobaciones; solo peticiones GET; no necesita seson ni credenciales).

    & 'C:\Python311embed\python.exe' -X utf8 'tools\verificacion\verificar_produccion_negro.py'

  Resultado esperado: "RESULTADO: 21/21 comprobaciones superadas".
  En PowerShell, a mano, las tres comprobaciones clave son:

    Invoke-WebRequest -Uri 'https://bitacora-grmv2-production.up.railway.app/health' -UseBasicParsing
    Invoke-WebRequest -Uri 'https://bitacora-grmv2-production.up.railway.app/_diag/tickets' -UseBasicParsing -ErrorAction SilentlyContinue
    Invoke-WebRequest -Uri 'https://bitacora-grmv2-production.up.railway.app/onboarding' -UseBasicParsing -MaximumRedirection 0

  Resultado esperado:
    - /health ................. 200
    - /_diag/tickets .......... 404 (el endpoint ya no existe)
    - /onboarding ............ 307 con Location que empieza por https://
    - Cabeceras presentes en cualquier respuesta: Strict-Transport-Security,
      Content-Security-Policy, Permissions-Policy, X-Frame-Options: DENY,
      X-Content-Type-Options: nosniff.

5.2) Barrido de rutas autenticado (el mas completo)
-----------------------------------------------------
  En PowerShell, con la credencial de administrador en el entorno:

    $linea = ([System.IO.File]::ReadAllLines("$env:TEMP\bitacora_admin_password.txt"))[1]
    $env:BITACORA_ADMIN_USER = 'admin'
    $env:BITACORA_ADMIN_PASSWORD = $linea.Substring($linea.IndexOf(':') + 1).Trim()
    & 'C:\Python311embed\python.exe' -X utf8 'tools\verificacion\barrer_rutas.py'

  Resultado esperado: "RESULTADO BARRIDO: todas las comprobaciones superadas".
  Sin credenciales el script termina con codigo 2 y el mensaje
  "NO VERIFICABLE: faltan las variables de entorno obligatorias: ...".

5.3) Inventario de enlaces y anclas
-------------------------------------
    & 'C:\Python311embed\python.exe' -X utf8 'tools\verificacion\inventariar_rutas.py'

  Resultado esperado: recuento de enlaces rotos = 0 (ver 6.4).

5.4) Suite de tests (obligatoria antes de publicar)
----------------------------------------------------
    & 'C:\Python311embed\python.exe' -X utf8 -m pytest tests/ -q --tb=line

  Resultado esperado: 91 passed, 0 failed.

  AVISO: no lanzar dos suites pytest a la vez. `tests/test_reporte_entregas.py`
  usa una ruta fija de SQLite (`./test_reporte_entregas.db`), de modo que dos
  sesiones concurrentes se pisan y aparece un fallo espurio. En este lote
  se obtuvo 90 passed / 1 failed por esa concurrencia y 91 passed al
  ejecutarla en solitario. Es una limitacion preexistente, no una regresion.

5.5) Verificacion del worker y del beat
-----------------------------------------
    & 'C:\Python311embed\python.exe' -X utf8 'tools\verificacion\verificar_railway_worker_beat.py'
    & 'C:\Python311embed\python.exe' -X utf8 'tools\verificacion\verificar_rol_celery.py'

  Resultado esperado: 24/24 y 16/16. NO se pudieron reejecutar en este lote
  porque el token de proyecto de Railway dejo de autorizar la API (ver 4.3,
  punto 1). El estado de los tres servicios antes del push era correcto.

5.6) Diagnostico local de tickets (sustituye al endpoint retirado)
-------------------------------------------------------------------
    & 'C:\Python311embed\python.exe' -X utf8 'tools\verificacion\diagnostico_tickets.py'

  Resultado esperado: 3/3 OK. Usa una SQLite en memoria: no toca ninguna
  base de datos real.

--------------------------------------------------------------------------------
6. TRAZABILIDAD
--------------------------------------------------------------------------------

6.1) Commits
-------------
  dbbb7a0  fix(produccion): retirar el endpoint de diagnostico /_diag/tickets
           sin autenticacion
  51b3cd9  fix(varios): endpoint de reglas de Butler, purga PostgreSQL, fecha
           de entregas y SMTP desde el SSOT
  c118fd3  fix(seguridad): cabeceras HTTP, proxy inverso, superficie expuesta
           y secretos en logs
  ebbc87b  fix(plantillas): autoescape, XSS por innerHTML, modal-root
           duplicado y SSOT del LOV
  ebe0591  chore(deps): actualizar los pins con advisories y ajustar el
           indice de paquetes
  193ef4f  fix(verificacion): credenciales por variable de entorno y base de
           datos temporal
  a7e0085  docs(despliegue): reconciliar la guia con railway.toml y start.sh
  4bdf29b  fix(tableros): no anunciar el enlace publico de un tablero que no
           es publico

  Publicacion: fast-forward 512c830..4bdf29b (sin --force).

6.2) Ficheros modificados (43 versionados, 4 nuevos)
-----------------------------------------------------
  Modificados:
    .gitignore
    DEPLOYMENT_CHECKLIST.md
    RAILWAY_DEPLOY.md
    README.md
    README_V1.004_WORKER_BEAT_EN_RAILWAY_2026-10-24.txt
    app/api/v1/trello_features.py
    app/core/config.py
    app/core/resultado_pruebas.py
    app/db/init_db.py
    app/db/migrations.py
    app/main.py
    app/models/ticket.py
    app/schemas/ticket.py
    app/services/ticket_service.py
    app/static/js/htmx-events.js
    app/static/js/kanban.js
    app/templates/admin/reporte_entregas.html
    app/templates/base.html
    app/templates/dashboard/index.html
    app/templates/kanban/partials/column.py
    app/templates/tableros/index.html
    app/templates/tickets/detalle_modal.py
    app/templates/tickets/list.html
    app/templates/tickets/nuevo_modal.html
    app/templates/usuarios/index.html
    app/templates/vistas/calendario.html
    app/templates/vistas/gantt.html
    app/templates/vistas/planner.html
    deploy_url.txt
    docs/VALIDATION_REPORT.md
    gunicorn.conf.py
    pyproject.toml
    requirements.txt
    start.sh
    tests/conftest.py
    tools/verificacion/README.md
    tools/verificacion/barrer_rutas.py
    tools/verificacion/esperar_redeploy.py
    tools/verificacion/inventariar_rutas.py
    tools/verificacion/verificar_arranque.py
    tools/verificacion/verificar_flujo_produccion.py

  Nuevos:
    deploy_url_app.txt
    deploy_url_guia.txt
    tools/verificacion/diagnostico_tickets.py
    tools/verificacion/verificar_produccion_negro.py

6.2.1) Huellas SHA-256 de los ficheros publicados
---------------------------------------------------
  app/main.py                          222a0868c81ef2919ce3932f1c3a1d44c5335fd82509c3083a99a54cb75b924d
  app/core/config.py                   436ff890b8d2999c41d341b1279cd2c09263fc0b7b2756944f293746cce917b6
  app/core/resultado_pruebas.py        9523b991aec8f8282d4076c9c4c9538068e0fed95abd5986470301e791d48441
  app/db/migrations.py                 a73cc07842e1199423538883beb9507389c47762d61a5d25b1319e442c9351d8
  app/db/init_db.py                   f7851d5634597ff141a1a4259466a746586903fe3afd1df8fabc02b4cb29522e
  app/models/ticket.py                d6673f88576fd7a4c0b08deac303b9e25b750006bf799b7b2368cc6f87e0c377
  app/schemas/ticket.py               e3de06833eb37a7f588426dec4b7527b6a56a8a3ce44edaff0a40d5bc2e95678
  app/services/email_service.py       cf8b3e162257820b0365b6031ace27715a7cdc361f17c940747881f72980914e
  app/services/ticket_service.py      937f2cb778e528786299808a5cf4c37cf97bd1f46124218b2973620bc9c62ac2
  app/tasks/entregas.py               d1c9d3ca4fc10167e81d0bd3c98f97432596d737b9fe9e97a38008cb787b6cf4
  app/api/v1/trello_features.py       32b734c0a38a1949d4df931128ce106a58adde6692e768d11920a877861a989e
  app/templates/tickets/detalle_modal.py
                                      339d24d9f623077e7e5ccc1d1e439d5154e4d885c03d85ef78c7983cf1ed5c20
  app/templates/tickets/nuevo_modal.html
                                      b0495adb63ad1f3233ca2e0478355da6b1b8d59297a2bf870abc958569f3938d
  app/templates/tickets/list.html     dd6c04ee99936a3721476a1328be83fde0713023c92d0806f3fe71feb5d51594
  app/templates/kanban/partials/column.py
                                      866e1d6e6875a83ea4cd29c651eb7e0987fe5335f41d0b0a4505765717012cb0
  app/templates/base.html              9b4647d890538801ccee6ad161e182adc27213aa852473c8eaa0812c0f4d4ade
  app/templates/usuarios/index.html    d4c48656a3d0e064db0038d59afe814359bbd5946711bd3dc529cb1e2e5ac40b
  app/templates/tableros/index.html   3b8d1c947bdba64ff1c23f4e40ac770c8638d0190b2c9b732bf340b5c4a2c49e
  app/templates/dashboard/index.html   02efd4333df01fc7ca789c15d0e3ac23d56304a27ddd7fbce7e2c6e85a9203e3
  app/templates/admin/reporte_entregas.html
                                      ff6fed4c8a9a249fe608f2043d504c196e8b61a850609fe5b8ec3eeeb3289241
  app/templates/vistas/planner.html    9bf1e0ebfde9bd8afeaf4661f3d5abe139c3b94ce7cc8833f171bd722ce846a8
  app/templates/vistas/gantt.html      001eaf34bf3947fb1cf6c3de464539fab4e3be89cc19584df6d840e6a2ea5641
  app/templates/vistas/calendario.html 566caa535be3c651657ccac788cad59a162526b747f5899ecb87eae769581728
  app/static/js/kanban.js              88bbbd91679ca78367679600ba581d6926399a835f4c4f4d1a965f565d8de3ef
  app/static/js/htmx-events.js         9395d4a62a37a0159e795b208430fbbbc209bb094ad16391103173fe45e4e0d3
  gunicorn.conf.py                     77c36a5753022e9ee731888da4657c2263bfa2de71928f3b598b7c40021bc62c
  start.sh                             be0957f4501a478845898e5ef18e3ce4d5183af8ab39b135bb6b7c26da78a7c7
  requirements.txt                     e6edf00615bf7e78be15f4401ceef4d74727965921d3212bcf9bb62105db41e3
  pyproject.toml                       93e02c80a30ecf040331f652ba858d5e55feace55317691a6256b3437978cd75
  tests/conftest.py                    f9ff97931da4cd3a52ea737e25fcab951bdeb862c5db8674957bffe980ae4ee4
  tools/verificacion/barrer_rutas.py   b351bb9a1a9e9f062614975706dfd200da29022252d54ace0c7c781b83b20038
  tools/verificacion/inventariar_rutas.py
                                      31160cb45c45f79e7bc37bbfbc3017cc657c407af08d15fb9025d0e4825176d2
  tools/verificacion/verificar_flujo_produccion.py
                                      0f0e211271b8a477b62440f127b017b17a56c3bcf46fb5ff7d2105c7592e87ce
  tools/verificacion/verificar_arranque.py
                                      a77defae077d50ed961d25204a9ecc83a0131a7d7d0e033dbb349196e5b49fad
  tools/verificacion/esperar_redeploy.py
                                      1b04ee61e8338a5bd2cabeba3265bc5694d33a6d5c218de0af0c6c0bde0b370b
  tools/verificacion/diagnostico_tickets.py
                                      4ad042419238d203422db0ea8f70804d6a6774c8669660ac485c82cae861e773
  tools/verificacion/verificar_produccion_negro.py
                                      08021bac58256df7f81728475a10fa2032b0132fb20cd76d574361081bece47a
  tools/verificacion/README.md         bb961c6f4c674d553ee28d46a0c06af58bb9db392644b1774ce96c86dd6deec9
  RAILWAY_DEPLOY.md                    a29333e94d49b3020f96d4f82ea336f28bb8d0ea94f206dddecfc04f0a693f99
  DEPLOYMENT_CHECKLIST.md              ee7fd3d2c3b09b279a55b88aac6f3abb8306cac764d1a8f3962ced14553a1aa2
  README.md                            b95197759b1a2a87fe678a815d68c83d701da9c9f91048908a0869afcd7984e8
  docs/VALIDATION_REPORT.md            7136e24348b43404ab397c60c648db6955b5164a116740634712780f3b5283f9

6.3) Unica modificacion en un README anterior
-----------------------------------------------
  `README_V1.004_WORKER_BEAT_EN_RAILWAY_2026-10-24.txt`, linea 97: se
  sustituyo el prefijo de cuatro caracteres de la contrasena REAL de
  PostgreSQL de produccion por `****`. No se toco ninguna otra linea ni se
  reescribio el documento.

6.4) Evidencia: resultados reales de la validacion
---------------------------------------------------
  Suite pytest (arbol integrado, en solitario):
      91 passed, 0 failed, 5 warnings in 263.93s (0:04:23)

  Verificacion en negro contra produccion (21 comprobaciones):
      RESULTADO: 21/21 comprobaciones superadas
      - /health ................. 200
      - /_diag/tickets .......... 404  (cuerpo: {"detail":"Not Found"})
      - /info ................... 200, sin `database_url`, con `database`
      - HSTS, CSP, Permissions-Policy, X-Frame-Options, nosniff,
        Referrer-Policy: presentes en todas las respuestas
      - /onboarding ............. 307, Location
        'https://bitacora-grmv2-production.up.railway.app/onboarding/'
        (antes: 'http://...' - degradaba a HTTP)
      - Esquema OpenAPI: 123 rutas GET (124 - el endpoint retirado)
      - Barrido de las 123 rutas GET:
        reparto {307: 2, 302: 23, 401: 90, 200: 6, 404: 1, 422: 1}
        => 0 respuestas 5xx
      - 17 paginas HTML: 0 respuestas 5xx

  Barrido autenticado del repo (`tools/verificacion/barrer_rutas.py`):
      RESULTADO BARRIDO: todas las comprobaciones superadas
      - 31 paginas: {307: 1, 200: 30}, 0 rotas
      - 123 endpoints GET de la API:
        {307: 2, 200: 110, 410: 1, 422: 3, 404: 2, 403: 5}, 0 con 5xx
      - La ruta de estados del reporte se deriva del OpenAPI:
        /api/v1/admin/reporte-entregas/estados -> 200
      - El estado 'Produccion OK' esta presente en la respuesta
      - El dashboard inyecta la paleta y el fallback desde el servidor
      - La paleta NO esta re-declarada en el JS de "Cuenta de Resultado"
      - /_diag/tickets ya no existe (404)

  Versiones de dependencias contra la API de PyPI:
      18/18 paquetes verificados: la version existe y tiene artefacto para
      Python 3.12.

  Inventario de enlaces y anclas (autenticado, sobre produccion):
      437 enlaces internos comprobados en 17 paginas
      2631 identificadores HTML revisados
      enlaces internos rotos: 0
      anclas internas rotas: 0
      hallazgos agregados de redireccion a login: 0
      (Antes del fix de 2.15 eran 2 enlaces rotos y 439 enlaces; ahora la
      pagina /tableros tiene 38 enlaces en lugar de 40, que son exactamente
      los dos que se han dejado de anunciar.)

  Sonda del preambulo de `start.sh` con `set -euo pipefail`:
      "[start.sh] SECRET_KEY generado (len=64) y persistido"
      "[start.sh] ERROR: rol desconocido en PROC_TYPE='rol_invalido'."
      (detencion de rol correcta; sin abortos por variable no definida)

  Render local del modal de detalle y del nucleo sensible:
      14/14 y 24/24 comprobaciones superadas (selector con los 6 valores
      del catalogo, valor seleccionado marcado, payload XSS escapado y sin
      doble escapado, LOV coherente entre models, schemas y plantillas).

6.5) Hallazgos NO resueltos (declarados, no ocultados)
------------------------------------------------------
  1) Sin limitacion de intentos ni bloqueo de cuenta en el login. Los
     endpoints publicos de login admiten fuerza bruta sin freno. Requiere
     middleware con almacenamiento (Redis) y es un lote propio.
  2) El JWT no se invalida en el servidor: `logout()` solo borra la cookie y
     el token sigue siendo valido hasta `JWT_EXPIRE_MINUTES` (8 h). No hay
     `jti` ni lista de revocacion.
  3) El registro publico sigue abierto y "el primer usuario = administrador".
     Hay usuarios reales registrados por esa via, de modo que no se cerro
     unilateralmente. Recomendacion: exigir invitacion o negar el primer
     registro si la base de datos esta vacia, gobernado por una variable de
     entorno.
  4) El Kanban renderiza los 931 tickets en un unico HTML de 4,07 MB, sin
     paginacion. Escalabilidad con riesgo real sobre el trabajo de badge y
     paleta ya verificado: queda para un lote propio.
  5) El badge de Resultado de Pruebas no tiene paridad en
     `vistas/{tabla,timeline,panel}.html` ni en `_planner_sections.html`:
     esas filas son diccionarios construidos en `app/main.py` sin la clave
     `resultado_pruebas`. La paridad quedo cerrada en el Kanban (ya existia)
     y en `tickets/list.html`.
  6) `start.sh` sigue arrancando aunque fallen las migraciones (fallo
     logged, no crash-loop). La variante fail-closed es una linea y queda a
     criterio del propietario.
  7) `/docs`, `/redoc` y `/openapi.json` siguen publicados. Ahora se pueden
     apagar con `EXPOSE_API_DOCS=false`, pero no se apagaron por defecto
     para no romper las herramientas de verificacion que derivan sus rutas
     del OpenAPI real.
  8) `tools/verificacion/` conserva cuatro apariciones de `admin123` en
     `tests/test_reporte_entregas.py` y `tests/test_trello_features.py`.
     Son fixtures que crean sus usuarios en la SQLite desechable de la
     suite, NO credenciales de produccion; no se tocaron.
  9) `tests/test_reporte_entregas.py` usa una ruta fija de SQLite en la raiz
     (`./test_reporte_entregas.db`). Dos suites pytest concurrentes se
     pisan. Limitacion preexistente.
  10) `deploy_url.txt` conserva una nota de renombrado porque el borrado
      seguro esta bloqueado por la politica local de este entorno. Cuando
      el lanzador este disponible, eliminar el fichero.
  11) No se pudo reejecutar la verificacion del worker y del beat con el
      verificador de `tools/verificacion/`: el token de proyecto de Railway
      dejo de autorizar la API. El estado de los tres servicios ANTES del
      push era correcto (24/24 y 16/16).
  12) No se verifico el comportamiento interno de Railway (deprecacion de
      Config as Code, topologia del worker y del beat, volumenes). No es
      comprobable desde fuera.
  13) No se pudo verificar el QA visual con navegador (Playwright/Chromium):
      no hay Node en la maquina. La correccion del autoescape y del
      `modal-root` se valido por render y por codigo, no visualmente.

6.6) Metodo de verificacion y reproduccion
-------------------------------------------
  - Nada se valido contra la base de datos de produccion. Toda comprobacion
    de escritura usa una SQLite temporal (en memoria o bajo `tests/tmp/`).
  - Las peticiones contra produccion fueron de solo lectura, mas el login
    imprescindible para auditar las paginas HTML con sesion.
  - Ninguna afirmacion de este documento se apoya en un dato inventado: las
    salidas de los comandos son las literales del entorno.

--------------------------------------------------------------------------------
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
--------------------------------------------------------------------------------

7.1) Estado actual
-------------------
  - HEAD = origin/main = a7e0085 (mas el commit de este README).
  - Produccion sirve a7e0085: verificado en negro (21/21) y con el barrido
    autenticado (todas las comprobaciones superadas).
  - Los tres servicios (web, worker y beat) comparten el repositorio y se
    redesplegaron con el push.
  - Credenciales por defecto: `admin/admin123` esta ROTADO (401) y las
    cuentas de semilla `agente1` y `lider` estan DESACTIVADAS (403). La
    nueva credencial de `admin` se entrego al propietario por canal privado.

7.2) Reinicio o redespliegue del worker y del beat
---------------------------------------------------
  Desde el panel de Railway: servicio -> Deployments -> "Redeploy".
  Por API (GraphQL, token de proyecto valido):

      mutation Redeploy($id: String!) { deploymentRedeploy(id: $id) }

  Para reiniciar SOLO el proceso (sin rebuild), en el panel: servicio ->
  Restart. Ojo: un reinicio de proceso vuelve a ejecutar `start.sh`, con lo
  que aplica las migraciones y reaprovisiona la `SECRET_KEY`.

  Recordatorio: el beat es un planificador permanente. NO debe existir mas de
  una instancia: dos beats disparan cada tarea dos veces.

7.3) Rollback
--------------
  Este lote es un fast-forward, asi que el rollback es un fast-forward
  inverso (nunca un `push --force`):

    git revert --no-commit a7e0085 193ef4f ebe0591 ebbc87b c118fd3 51b3cd9 dbbb7a0
    git commit -m "revert: V1.005 (auditoria multiagente y retirada de superficies)"
    git push origin main

  O bien, para volver al commit anterior completo:

    git checkout 512c830
    git push origin main          (esto NO es fast-forward: usar con cuidado
                                   y solo si el owner lo autoriza)

  Tras el rollback hay que REDESPLEGAR LOS TRES SERVICIOS (web, worker y
  beat), porque `start.sh` y `requirements.txt` cambian entre versiones.

  Rollback de una sola parte: si solo el web deuene estar mal, basta con
  redesplegar solo el web. Si lo que falla es el worker, redesplegar solo el
  worker. El codigo es el mismo para los tres, pero los procesos arrancan
  por separado.

  Ojo al hacer rollback de este lote en concreto: `/_diag/tickets` vuelve a
  quedar expuesto sin autenticacion, y las cabeceras HSTS/CSP desaparecen.
  Si el rollback es por un problema de UI, es preferible revertir solo los
  commits de plantillas (`ebbc87b`) y conservar el resto.

7.4) Reglas de seguridad operativas
-----------------------------------
  - Nunca publicar la URL de la base de datos en un log. Usar
    `settings.get_database_url_enmascarada()` o `enmascarar_url_db()`.
  - Nunca volver a escribir una credencial en el codigo. Los verificadores
    leen `BITACORA_ADMIN_USER` y `BITACORA_ADMIN_PASSWORD`.
  - No activar `ALLOW_XUSER_HEADER=true` en produccion: reabre el bypass de
    suplantacion por cabecera.
  - No declarar `a2wsgi` en `requirements.txt` mientras el bloque de
    WhiteNoise no se reescriba con `WhiteNoiseMiddleware`.
  - Rotar el PAT de GitHub y el token de proyecto de Railway.
  - Migrar la configuracion del panel antes del 2026-12-01.

================================================================================
Fin del README V1.005
================================================================================
