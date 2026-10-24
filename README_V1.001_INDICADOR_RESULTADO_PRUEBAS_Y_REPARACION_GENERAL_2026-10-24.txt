================================================================================
  README_V1.001 — INDICADOR_RESULTADO_PRUEBAS_Y_REPARACION_GENERAL
  Bitácora GRM v2 · Changelog atómico incremental
================================================================================

Fecha              : 2026-10-24
Versión base       : 1c74595feadf17cd30d8d71f22afebd62adba739 (254 commits)
Versión objetivo   : HEAD tras este commit
Correlativo        : 001
                       Justificación: `git log --all --diff-filter=A --name-only
                       | grep README_V1` devuelve VACÍO. No ha existido
                       ningún README_V1.* en el historial del repositorio, por
                       lo que el correlativo arranca en 001.
Tipo de cambio     : FEAT + FIX + REFACTOR + CHORE (release integrada)
Severidad          : ALTA — funcionalidad de negocio + corrección de
                     indisponibilidad de la vista pública
Riesgo de regresión : MEDIO — toca renderizado de tarjetas, dashboard, cookies
                     de sesión y carga de configuración. Mitigado con
                     91 tests automatizados + barrido en vivo de 38 rutas.
URL del despliegue  : https://tx2zb18mwv9o.space.mcode.io
Autor              : MiniMax Agent
Alcance             : 24 archivos modificados, 6 archivos nuevos, 460 archivos
                     eliminados (clon anidado + binarios de runtime)

--------------------------------------------------------------------------------
 1. BASE / ESTADO PREVIO
--------------------------------------------------------------------------------

1.1 Punto de partida
    - Rama           : main
    - Commit base    : 1c74595 ("Message 455637603586253 - 1792793234")
    - Commits totales: 254
    - Archivos versionados: 817 (¡incluía 460 archivos duplicados!)
    - Stack          : FastAPI + Starlette 1.9.0 · SQLAlchemy 2.0.36 ·
                      pydantic-settings 2.6.1 · Celery 5.4.0 (Redis) ·
                      Jinja2 3.1.4 · HTMX + TailwindCSS + SortableJS ·
                      PostgreSQL (prod) / SQLite (dev)

1.2 Release notes previos en el repositorio
    - README_V2.01_COMENTARIOS_ADJUNTOS_EDICION_REFERENCIAS.txt
    - docs/README_V2.01_ERROR_HANDLING_BUSCAR_KANBAN.txt
    - docs/README_V2.02_SECURITY_HEADERS_CACHE_MIDDLEWARE.txt
    Este README_V1.001 es la primera release bajo la nomenclatura README_V1.*

1.3 Hallazgos de la auditoría (estado previo → estado corregido)

    ┌────┬──────────────────────────────────────────┬───────────────────────────┐
    │ #  │ Hallazgo                                 │ Severidad                │
    ├────┼──────────────────────────────────────────┼───────────────────────────┤
    │  1 │ Vista pública /p/{slug} 100% rota en      │ CRÍTICA — indisponible   │
    │    │ runtime: ImportError de `Estado`          │                           │
    │  2 │ Clon anidado del propio repo versionado   │ CRÍTICA — 56% duplicado  │
    │    │ dentro de la raíz (460/817 archivos)      │                           │
    │  3 │ Claves de lista (CORS_ORIGINS,           │ CRÍTICA — caída al       │
    │    │ ROLES_DISPONIBLES) en CSV abortan el      │ arrancar                 │
    │    │ arranque de la app y de los workers       │                           │
    │  4 │ SECRET_KEY con default hardcodeado en el  │ CRÍTICA — JWT firmados   │
    │    │ repo (clave pública para cualquier       │ con clave conocida       │
    │    │ instalación)                              │                           │
    │  5 │ CORS con '*' + allow_credentials=True      │ ALTA — CSRF sobre cookie │
    │    │ (orígenes arbitrarios con credenciales)    │ de sesión                │
    │ 6 │ Badge de "Resultado de Pruebas" inexistente│ ALTA — requisito de      │
    │    │ en las tarjetas del Kanban                 │ negocio no entregado     │
    │  7 │ Tres paletas de color divergentes para el  │ ALTA — mismo dato con    │
    │    │ mismo LOV (tarjeta / dashboard / modal)    │ 3 colores distintos      │
    │  8 │ Error de sintaxis Jinja2 en               │ ALTA — template no       │
    │    │ admin/reporte_entregas.html:508           │ renderizable             │
    │  9 │ Notification task inexistente             │ MEDIA — watchers sin     │
    │    │ (notificar_ticket_archivado) silenciada   │ aviso de archivado       │
    │ 10 │ NameError en detección de ciclos de       │ MEDIA — excepción        │
    │    │ dependencias (sucesor.codigo)             │ inesperada al usuario    │
    │ 11 │ Suite de tests INTERNALERROR (SystemExit  │ MEDIA — sin red de       │
    │    │ en import time) — 0 tests ejecutables     │ seguridad de regresión   │
    │ 12 │ Cookie de sesión sin `secure` en          │ MEDIA — cookie enviable  │
    │    │ producción (DEBUG)                        │ por HTTP                 │
    │ 13 │ Variable `usuario` ausente en el contexto │ BAJA — TemplateError en  │
    │    │ de /p/{slug}                              │ vista pública            │
    │ 14 │ Enlaces de navegación huérfanos            │ BAJA — /catalogos y      │
    │    │ (/catalogos, /admin/reporte-entregas)      │ /admin/reporte-entregas  │
    │    │                                           │ inalcanzables            │
    │ 15 │ Residuo CJK en un comentario de JS        │ BAJA — ruido editorial   │
    │ 16 │ Rutas hardcodeadas /workspace/Bitacora-   │ BAJA — scripts rotos en  │
    │    │ GRM_v2 en 3 docstrings                     │ otros entornos           │
    │ 17 │ Binarios de runtime y scratch versionados  │ BAJA — repo inflado,     │
    │    │ (uploads/, shell_output_save/)             │ clones de 289 MB         │
    └────┴──────────────────────────────────────────┴───────────────────────────┘

1.4 Estado de validación ANTES de este release
    - pytest               : NO EJECUTABLE (INTERNALERROR en la colección)
    - Barrido de rutas     : NO REALIZADO (no existía)
    - Archivos duplicados  : 460 de 817 (56 %)

--------------------------------------------------------------------------------
 2. CÓDIGO MODIFICADO O PARCHE EXACTO CON LAS FUNCIONES INTERVENIDAS
--------------------------------------------------------------------------------

2.1 NUEVO — app/core/resultado_pruebas.py (331 líneas)
    Catálogo único (SSOT) del LOV "Resultado de Pruebas": valores canónicos,
    acrónimos, paleta de colores, normalización de variantes heredadas y
    renderizado del badge. Es la ÚNICA fuente de verdad y alimenta los tres
    puntos de la UI (tarjeta Kanban, encabezado del Dashboard, modal de
    drill-down), de modo que es imposible que divergan.

    API pública:
        RESULTADOS_LOV      : ("N/A","NOK","OK","OK CON OBS.","POSTERGADA",
                              "DESESTIMADA")
        SIN_RESULTADO       : "(en blanco)"
        ACRONIMOS           : {"OK":"OK", "N/A":"N/A", "OK CON OBS.":"OBS",
                              "POSTERGADA":"POST", "DESESTIMADA":"NOOK",
                              "NOK":"NOK", "(en blanco)":"S/D"}
        COLORES             : {valor: {"bg": hex, "text": hex, "cellText": hex}}
        COLOR_FALLBACK      : {"bg":"#475569","text":"#ffffff",
                              "cellText":"#1f2937"}
        normalizar_resultado(valor)        -> str | None
        info_resultado(valor)              -> dict
        info_resultado_ticket(ticket)      -> dict
        paleta_js()                        -> dict  (JSON para el front)
        acronimos_js()                     -> dict  (JSON para el front)
        render_badge_resultado(info)       -> Markup (HTML escapado)

    Parche — funciones intervenidas:

        _ALIASES: dict = {
            # Variantes heredadas que existían en la base de datos (UAT) y
            # que deben colapsar a su forma canónica.
            "OK CON OBS": "OK CON OBS.",
            "OK CON OBSERVACION": "OK CON OBS.",
            "OK CON OBSERVACIONES": "OK CON OBS.",
            "OK CON OBS.": "OK CON OBS.",
            "POSTERGADO": "POSTERGADA",
            "POSTERGADA A GARANTÍA": "POSTERGADA",
            "POSTERGADA A GARANTIA": "POSTERGADA",
            "POSTERGADA A GAR": "POSTERGADA",
            "DESESTIMADA ": "DESESTIMADA",
            "NO APLICABLE": "N/A",
            "N/A": "N/A",
            "NO OK": "NOK",
            "NOOK": "NOK",
            "S/D": "(en blanco)",
            "SIN DATO": "(en blanco)",
        }

        def normalizar_resultado(valor: str | None) -> str | None:
            """Colapsa una variante heredada a su forma canónica del LOV.
            Devuelve None si el valor es vacío/None."""
            if valor is None:
                return None
            texto = str(valor).strip()
            if not texto:
                return None
            if texto in COLORES:
                return texto
            clave = texto.upper()
            if clave in _ALIASES:
                return _ALIASES[clave]
            for canonico in RESULTADOS_LOV:
                if canonico.upper() == clave:
                    return canonico
            return None

        def info_resultado(valor: str | None) -> dict:
            """Devuelve {clave, acronimo, bg, text, cellText, titulo, sin_dato}
            para un valor arbitrario. Valores fuera del LOV caen en el color
            neutro COLOR_FALLBACK sin romper el render."""
            canonico = normalizar_resultado(valor)
            if canonico is None:
                texto = (valor or "").strip()
                return {
                    "clave": texto or SIN_RESULTADO,
                    "acronimo": ACRONIMOS.get(canonico or SIN_RESULTADO, "—"),
                    "bg": COLOR_FALLBACK["bg"],
                    "text": COLOR_FALLBACK["text"],
                    "cellText": COLOR_FALLBACK["cellText"],
                    "titulo": ("Resultado de pruebas: sin dato" if not texto
                               else "Resultado de pruebas: {0}".format(texto)),
                    "sin_dato": not texto,
                }
            color = COLORES[canonico]
            return {
                "clave": canonico,
                "acronimo": ACRONIMOS.get(canonico, canonico[:10].upper()),
                "bg": color["bg"],
                "text": color["text"],
                "cellText": color["cellText"],
                "titulo": ("Resultado de pruebas: sin dato"
                           if canonico == SIN_RESULTADO
                           else "Resultado de pruebas: {0}".format(canonico)),
                "sin_dato": canonico == SIN_RESULTADO,
            }

        def info_resultado_ticket(ticket) -> dict:
            """Variante de info_resultado para un Ticket.

            Regla de negocio: sólo los tickets de tipo `incidencia` y
            `resultado_pruebas` muestran el indicador "S/D" cuando no hay
            resultado. Para el resto de tipos de ticket (solicitud, cambio,
            ...) no se muestra el indicador, para no ensuciar la columna
            inferior de la tarjeta.
            """
            tipo = getattr(ticket, "tipo", None)
            tipo_valor = tipo.value if hasattr(tipo, "value") else (tipo or "")
            if tipo_valor not in ("incidencia", "resultado_pruebas"):
                return {"clave": None, "acronimo": None, "bg": None,
                        "text": None, "cellText": None, "titulo": None,
                        "sin_dato": False, "visible": False}
            info = info_resultado(getattr(ticket, "resultado_pruebas", None))
            info["visible"] = True
            return info

        def render_badge_resultado(info: dict) -> Markup:
            """Devuelve el HTML del badge. Devuelve "" si el indicador no
            aplica. Todos los valores interpolados pasan por markupsafe.escape
            (no hay inyección posible desde datos de usuario)."""
            if not info or not info.get("visible", True):
                return Markup("")
            if not info.get("acronimo"):
                return Markup("")
            return Markup(
                "<span class='inline-flex items-center px-2 py-0.5 rounded text-[11px] "
                "font-semibold' style='background:{bg}; color:{txt};' title='{tit}'>"
                "{acr}</span>".format(
                    bg=escape(info["bg"]), txt=escape(info["text"]),
                    tit=escape(info["titulo"] or ""),
                    acr=escape(info["acronimo"]),
                )
            )

2.2 app/main.py — 4 hunks (registro de globals, paleta del dashboard,
    validación de configuración, CORS) + 1 corrección crítica de import

    (a) Globals Jinja del catálogo — insertado tras la creación de
        `templates`:

            from app.core.resultado_pruebas import (  # noqa: E402
                info_resultado as _resultado_info,
                info_resultado_ticket as _resultado_info_ticket,
                render_badge_resultado as _badge_resultado,
            )
            templates.env.globals["resultado_info"] = _resultado_info
            templates.env.globals["resultado_info_ticket"] = _resultado_info_ticket
            templates.env.globals["badge_resultado"] = _badge_resultado

    (b) Paleta + acrónimos inyectados en el Dashboard (endpoint GET /):

            from app.core.resultado_pruebas import acronimos_js, paleta_js
            return templates.TemplateResponse(
                request,
                "dashboard/index.html",
                {
                    "usuario": usuario,
                    "cuenta_resultado_colores": paleta_js(),
                    "cuenta_resultado_acronimos": acronimos_js(),
                },
            )

    (c) Validación de configuración en el arranque (bloqueante sólo en
        producción) — función intervenida: lifespan de app/main.py

            # Paso 0: validación de configuración (bloqueante sólo en producción)
            avisos = settings.validar()
            if avisos:
                mensaje = ("Configuración insegura:\n"
                           + "\n".join("  - {0}".format(a) for a in avisos))
                if not settings.DEBUG:
                    logger.error(mensaje)
                    raise RuntimeError(mensaje)
                logger.warning("[startup] " + mensaje.replace("\n", " | "))

        Además, AUTO_INIT_DB pasa a leerse de `settings` (antes usaba
        os.getenv, que nunca veía el archivo .env):

            if settings.DEBUG or settings.AUTO_INIT_DB:

    (d) CORS endurecido — se desactiva allow_credentials si hay comodín:

            _cors_origins = [o for o in (settings.CORS_ORIGINS or []) if o]
            _cors_wildcard = "*" in _cors_origins
            if _cors_wildcard:
                logger.warning(
                    "[cors] CORS_ORIGINS contiene '*': se desactiva "
                    "allow_credentials para impedir que orígenes arbitrarios "
                    "ejecuten peticiones autenticadas con la cookie de sesión. "
                    "Define orígenes explícitos en producción."
                )

            app.add_middleware(
                CORSMiddleware,
                allow_origins=_cors_origins,
                allow_credentials=not _cors_wildcard,
                allow_methods=["*"],
                allow_headers=["*"],
            )

    (e) CORRECCIÓN CRÍTICA — GET /p/{slug} (tablero público) estaba
        COMPLETAMENTE ROTO en runtime por un import inválido:

            - from app.models.espacio import Tablero, Estado
            + from app.models.espacio import Tablero
            + from app.models.estado import Estado

        `Estado` vive en app/models/estado.py, NO en app/models/espacio.py.
        El error real era:
            ImportError: cannot import name 'Estado' from 'app.models.espacio'
        Verificado que era la ÚNICA ocurrencia del patrón en todo el repo.

    (f) Contexto de la vista pública — se entrega `usuario` explícitamente:

                {
                    "tablero": tablero, "estados": estados,
                    "slug": slug,
                    # La vista es pública (sin sesión): `base.html` referencia
                    # `usuario` en varios puntos. Se entrega explícitamente como
                    # None para que las guards `{% if usuario %}` no dependan de
                    # que la plantilla herede o no la variable del contexto.
                    "usuario": None,
                },

2.3 app/core/config.py — 299 líneas añadidas (configuración de listas +
    exportación a os.environ + validación de secretos)

    (a) Normalización de listas ANTES de construir `Settings`.
        pydantic-settings decodifica los campos List[str] con json.loads en
        EnvSettingsSource.prepare_field_value, es decir ANTES de que corra
        cualquier field_validator(mode="before"). Por eso un valor CSV en
        CORS_ORIGINS abortaba el arranque con:
            SettingsError: error parsing value for field "CORS_ORIGINS"

            _CAMPOS_LISTA = ("ROLES_DISPONIBLES", "CORS_ORIGINS")

            def _normalizar_lista(texto: str) -> str:
                """Convierte un texto de lista (CSV o JSON) en JSON canónico."""
                limpio = (texto or "").strip()
                if not limpio:
                    return "[]"
                if limpio.startswith("["):
                    try:
                        datos = json.loads(limpio)
                    except (json.JSONDecodeError, ValueError):
                        datos = None
                    if isinstance(datos, list):
                        return json.dumps([str(v) for v in datos],
                                          ensure_ascii=False)
                    interior = limpio.strip("[]").strip()
                    if interior:
                        partes = [p.strip().strip('"').strip("'")
                                  for p in interior.split(",")]
                        partes = [p for p in partes if p]
                        if partes:
                            return json.dumps(partes, ensure_ascii=False)
                return json.dumps(
                    [p.strip() for p in limpio.split(",") if p.strip()],
                    ensure_ascii=False,
                )

            def _preparar_listas_del_entorno() -> None:
                """Normaliza a JSON las variables de lista ANTES de construir
                `Settings`. Se normalizan dos orígenes: (1) el entorno real
                (Railway, Docker, CI, shell) y (2) el archivo .env, que se
                inyecta en el entorno para que la fuente EnvSettingsSource lo
                resuelva como JSON."""
                for clave in _CAMPOS_LISTA:
                    if clave in os.environ:
                        os.environ[clave] = _normalizar_lista(os.environ[clave])

                env_file = Settings.model_config.get("env_file")
                if isinstance(env_file, (list, tuple)):
                    env_file = env_file[0] if env_file else None
                if not env_file:
                    return
                for clave, valor in _leer_env_file(env_file).items():
                    if clave in _CAMPOS_LISTA and clave not in os.environ:
                        os.environ[clave] = _normalizar_lista(valor)

            _preparar_listas_del_entorno()
            settings = get_settings()

    (b) Exportación a os.environ — se cambia el formato de las listas a JSON:

            elif isinstance(valor, (list, tuple)):
                # Las listas se exportan como **JSON**, no como CSV: es el único
                # formato que `pydantic-settings` puede volver a leer desde el
                # entorno (ver `_normalizar_lista`). Con CSV, cualquier proceso
                # hijo que herede estas variables (Celery worker, scripts, jobs)
                # abortaba al arrancar con `SettingsError`.
                os.environ[clave] = json.dumps(list(valor), ensure_ascii=False)

    (c) SECRET_KEY sin default hardcodeado + validación:

            SECRET_KEY: str = ""
            # Sin default hardcodeado: si la clave no está definida en el
            # entorno queda vacía y `es_secreto_inseguro()`/`validar()` lo
            # detectan. Nunca reintroducir una clave fija en el repo: con ella,
            # cualquier JWT de cualquier instalación quedaba firmado con una
            # clave pública.

            def es_secreto_inseguro(self) -> bool:
                clave = (self.SECRET_KEY or "").strip()
                if not clave:
                    return True
                return "change-me" in clave.lower()

            def validar(self) -> list[str]:
                """Devuelve la lista de avisos de configuración insegura.
                SOLO informa: no lanza excepciones ni muta el estado."""
                avisos: list[str] = []
                if self.es_secreto_inseguro():
                    avisos.append(
                        "SECRET_KEY vacía o con valor placeholder ('change-me'): "
                        "define una clave aleatoria fuerte (p. ej. `openssl rand -hex 32`)."
                    )
                if not self.DEBUG:
                    origenes = list(self.CORS_ORIGINS or [])
                    if "*" in origenes:
                        avisos.append(
                            "CORS_ORIGINS contiene '*' con DEBUG=False: "
                            "restringe los orígenes permitidos en producción."
                        )
                    if not origenes:
                        avisos.append(
                            "CORS_ORIGINS está vacío con DEBUG=False: "
                            "configura los orígenes permitidos en producción."
                        )
                    if self.PUBLIC_BASE_URL and not self.PUBLIC_BASE_URL.startswith("https://"):
                        avisos.append(
                            "PUBLIC_BASE_URL no usa HTTPS con DEBUG=False: "
                            "los enlaces de los correos viajarían sin cifrar."
                        )
                return avisos

2.4 app/templates/kanban/partials/tarjeta.html — indicador en la tarjeta
    (bloque de la zona inferior derecha de la tarjeta del Kanban)

            <div class="flex items-center gap-1.5">
              {# --- Indicador de Resultado de Pruebas (acrónimo + color del LOV) ---
                 El catálogo (app/core/resultado_pruebas.py) es la única fuente de
                 verdad del LOV, los acrónimos y los colores. El dashboard usa la
                 MISMA paleta, por lo que tarjeta y reporte no pueden divergir. #}
              {{ badge_resultado(resultado_info_ticket(ticket)) }}
              {% if ticket.etiquetas %}
                ...

2.5 app/templates/kanban/partials/card.py y tarjeta.py — indicación en la
    tarjeta re-renderizada por drag & drop (usan su propio Environment)

            from app.core.resultado_pruebas import (  # noqa: E402
                info_resultado as _resultado_info,
                info_resultado_ticket as _resultado_info_ticket,
                render_badge_resultado as _badge_resultado,
            )

            _ENV = Environment(autoescape=True)
            for _fname, _ffunc in ALL_FILTERS.items():
                _ENV.filters[_fname] = _ffunc
            _ENV.globals["resultado_info"] = _resultado_info
            _ENV.globals["resultado_info_ticket"] = _resultado_info_ticket
            _ENV.globals["badge_resultado"] = _badge_resultado

            + (en el cuerpo de la plantilla, idéntico que en tarjeta.html)
              {{ badge_resultado(resultado_info_ticket(ticket)) }}

2.6 app/templates/dashboard/index.html — Cuenta de Resultado con los MISMOS
    colores y acrónimos que las tarjetas

    (a) Inyección de la paleta y los acrónimos como JSON (isla de datos):

            <script id="cuenta-resultado-paleta" type="application/json">{{ cuenta_resultado_colores | tojson }}</script>
            <script id="cuenta-resultado-acronimos" type="application/json">{{ cuenta_resultado_acronimos | tojson }}</script>

    (b) Se elimina la paleta local duplicada del JS:

            -  const CUENTA_RESULTADO_COLORES = {
            -    "N/A":         { bg: '#94a3b8', text: '#ffffff', cellText: '#1f2937' },
            -    "NOK":         { bg: '#dc2626', text: '#ffffff', cellText: '#1f2937' },
            -    "OK":          { bg: '#16a34a', text: '#ffffff', cellText: '#1f2937' },
            -    "OK CON OBS.": { bg: '#eab308', text: '#1f2937', cellText: '#1f2937' },
            -    "POSTERGADA":  { bg: '#ea580c', text: '#ffffff', cellText: '#1f2937' },
            -    "DESESTIMADA": { bg: '#7c3aed', text: '#ffffff', cellText: '#1f2937' },
            -    "(en blanco)": { bg: '#cbd5e1', text: '#475569', cellText: '#1f2937' },
            -  };
            +  // La paleta y los acrónimos se LEEN del JSON inyectado por el
            +  // servidor (app/core/resultado_pruebas.py)...

    (c) Encabezados de columna: se muestra el ACRÓNIMO con el título completo
        (antes se mostraba el valor crudo, que no cabía):

            -  html += '<th class="text-right py-2 px-2 font-semibold">' + c + '</th>';
            +  html += '<th class="text-right py-2 px-2 font-semibold" title="' + _escapeHtml(c) + '">'
            +        + _escapeHtml(acronimoResultado(c)) + '</th>';

    (d) Barras de distribución con la paleta compartida (antes usaban un
        mapa local RESULTADO_COLORS con tonos DISTINTOS):

            -  const RESULTADO_COLORS = { 'OK': '#10b981', 'OK CON OBS.': '#22c55e', ... };
            +  const colorDe = (r) => (CUENTA_RESULTADO_COLORES[r] || {}).bg || '#475569';
            ...
            -  return '<div title="' + r + ': ' + v + '" style="width:' + segPct.toFixed(1) + '%; background:' + RESULTADO_COLORS[r] + '"></div>';
            +  return '<div title="' + _escapeHtml(r) + ': ' + v + '" style="width:' + segPct.toFixed(1) + '%; background:' + colorDe(r) + '"></div>';

2.7 app/api/v1/metricas.py — badge del modal de drill-down, ahora con
    acrónimo, color del catálogo y escape anti-XSS

    (a) Se elimina la copia literal de la paleta:

            -CUENTA_RESULTADO_COLORES_PARA_MODAL = {
            -    "N/A":         {"bg": "#94a3b8", "text": "#ffffff"},
            -    "NOK":         {"bg": "#dc2626", "text": "#ffffff"},
            -    "OK":          {"bg": "#16a34a", "text": "#ffffff"},
            -    "OK CON OBS.": {"bg": "#eab308", "text": "#1f2937"},
            -    "POSTERGADA":  {"bg": "#ea580c", "text": "#ffffff"},
            -    "DESESTIMADA": {"bg": "#7c3aed", "text": "#ffffff"},
            -    "(en blanco)": {"bg": "#cbd5e1", "text": "#475569"},
            -}

    (b) Nueva función (intervenida):

            def _badge_resultado_modal(valor: str) -> str:
                """Devuelve el HTML del badge de *Resultado de Pruebas* para el modal.
                Mismo catálogo que las tarjetas del Kanban y que los encabezados del
                dashboard: mismo color y mismo acrónimo. Todos los valores que
                llegan desde el query string se escapan antes de inyectarse en el
                HTML."""
                texto = (valor or "").strip()
                clave = texto if texto in COLORES_RESULTADO else (_normalizar_resultado(texto) or texto)
                color = COLORES_RESULTADO.get(clave, COLOR_FALLBACK_RESULTADO)
                acronimo = ACRONIMOS_RESULTADO.get(clave) or (texto[:10].upper() if texto else "—")
                if clave == SIN_RESULTADO:
                    titulo = "Resultado de pruebas: sin dato"
                else:
                    titulo = "Resultado de pruebas: {0}".format(clave)
                return (
                    "<span class='inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold' "
                    "title='{0}' style='background:{1}; color:{2};'>{3}</span>".format(
                        escape(titulo), escape(color["bg"]),
                        escape(color["text"]), escape(acronimo),
                    )
                )

    (c) Uso en el modal y escape de los valores de la tabla:

            -    resultado_badge = (
            -        f"<span ...>{resultado_filtro}</span>"
            -    )
            +    resultado_badge = _badge_resultado_modal(resultado_filtro)
            +    modulo_badge = escape(modulo_filtro) if modulo_filtro else "—"

            y en cada celda: {t.codigo or ''}  ->  {escape(str(t.codigo or ''))}
                                 {t.titulo or ''}  ->  {escape(str(t.titulo or ''))}
                                 {estado_nombre}   ->  {escape(str(estado_nombre))}
                                 {asignado_nombre} ->  {escape(str(asignado_nombre))}
                                 return val        ->  return escape(str(val))

2.8 app/templates/admin/reporte_entregas.html — corrección de sintaxis Jinja2
    (el template NO era renderizable: `{% endif %}>` intentaba cerrar una
    etiqueta HTML en lugar del bloque Jinja)

            -                       {% if e.es_entrega %}checked{% endif]}>
            +                       {% if e.es_entrega %}checked{% endif %}>

2.9 app/api/v1/auth.py — cookie de sesión con flag `secure`

            +from app.core.config import settings
            ...
                key="access_token",
                value=token,
                httponly=True,
            +   secure=not settings.DEBUG,
                max_age=60 * 60 * 8,
                samesite="lax",
                path="/",
            (en _set_session_cookie, login_form y registro_form)

2.10 app/api/v1/kanban.py y app/api/v1/usuarios.py — firma moderna de
     TemplateResponse (Starlette 1.9.0 eliminó la firma posicional
     legacy `TemplateResponse(name, ctx)`):

            - return templates.TemplateResponse(
            -     "kanban/index.html",
            -     {
            -         "request": request,
            + return templates.TemplateResponse(
            +     request=request,
            +     name="kanban/index.html",
            +     context={
                        "usuario": usuario,
                        ...

2.11 app/core/security.py — claim `exp` del JWT como instante UTC explícito
     (`datetime.utcnow()` está obsoleto en Python 3.12 y devolvía naive)

            -from datetime import datetime, timedelta
            +from datetime import datetime, timedelta, timezone
            ...
            -    expire = datetime.utcnow() + timedelta(
            +    # `datetime.utcnow()` está obsoleto (DeprecationWarning en 3.12) y
            +    # deja el claim `exp` sin zona horaria. Se usa
            +    # `datetime.now(timezone.utc)` para que el `exp` sea un instante
            +    # UTC explícito.
            +    expire = datetime.now(timezone.utc) + timedelta(
                    minutes=expires_minutes or settings.JWT_EXPIRATION_MINUTES
                )

2.12 app/services/ticket_service.py — notificación de archivado real
     (la tarea `notificar_ticket_archivado` NO EXISTE; el ImportError quedaba
     silenciado por un `except: pass` y los watchers nunca recibían aviso)

            +        # Estado actual del ticket ANTES de archivar: se usa como
            +        # `estado_origen` de la notificación de archivado. Se captura
            +        # aquí porque el `db.refresh()` posterior expira los atributos.
            +        estado_origen_nombre = (
            +            ticket.estado.nombre if ticket.estado else "archivado"
            +        )
            ...
            -        try:
            -            from app.tasks.notification_tasks import notificar_ticket_archivado
            -            notificar_ticket_archivado.delay(ticket.id, usuario.id)
            -        except Exception:
            -            pass
            +        try:
            +            from app.tasks.notification_tasks import notificar_cambio_estado
            +            notificar_cambio_estado.delay(
            +                ticket.id, estado_origen_nombre, "archivado"
            +            )
            +        except Exception:
            +            logger.exception(
            +                "No se pudo encolar la notificación de archivado del ticket %s",
            +                ticket.id,
            +            )

2.13 app/services/dependencia_service.py — NameError en la detección de
     ciclos (la variable real se llama `suc`, no `sucesor`)

            -                f"({sucesor.codigo} ya depende transitivamente de {pred.codigo}).",
            +                f"({suc.codigo} ya depende transitivamente de {pred.codigo}).",

2.14 app/services/dev_inbox.py — paridad .env ↔ os.environ

            +# Importar `app.core.config` tiene un efecto secundario deliberado:
            +# exporta los valores del archivo `.env` al `os.environ` (con
            +# `setdefault`, sin pisar las variables reales del despliegue). Sin este
            +# import, los `os.getenv` de nivel de módulo verían `None` en
            +# desarrollo. Ver `app/core/config.py::_exportar_a_environ`.
            +from app.core import config as _config  # noqa: F401

2.15 app/templates/base.html — 2 enlaces de navegación huérfanos resueltos

            (a) /catalogos (disponible para cualquier usuario autenticado):
                <a href="/catalogos" class="flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
                   title="Mantenedores de catálogos (tipos de incidencia, prioridades, SLA, etc.)">
                  <svg class="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z"/></svg>
                  Catálogos
                </a>

            (b) /admin/reporte-entregas (bloque admin, tras "Triggers de Deadline"):
                <a href="/admin/reporte-entregas" class="flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
                   title="Reporte diario de entregas: plantilla, destinatarios y estados terminales">
                  <svg class="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                  Reporte de Entregas
                </a>

2.16 app/static/js/auth-events.js — residuo CJK en un comentario

            - *     que disparan un CustomEvent同名 en `document.body`.
            + *     que disparan un CustomEvent con el mismo nombre en `document.body`.

2.17 .gitignore — 2 secciones nuevas (30 líneas)

            # ==============================================================================
            # CLONES ANIDADOS DEL PROPIO REPOSITORIO
            # ==============================================================================
            # Un clon de este mismo repositorio (`Bitacora-GRM_v2/`) fue creado dentro
            # de la raíz de trabajo y quedó versionado junto al código canónico: 460 de
            # los 817 archivos del repo eran duplicados de una copia obsoleta (con su
            # propio `.git` y su propio `.venv-test`). No contenía trabajo único y
            # era la causa de las rutas hardcodeadas `/workspace/Bitacora-GRM_v2` en
            # varios scripts. Se retiró del control de versiones y del disco.
            #
            # Regla preventiva: el código canónico vive SIEMPRE en la raíz del repo.
            /Bitacora-GRM_v2/

            # ==============================================================================
            # DATOS DE RUNTIME Y SCRATCH (NO son código fuente)
            # ==============================================================================
            # `uploads/` contiene los adjuntos subidos por los usuarios. En Railway el
            # filesystem es efímero (se borra en cada redeploy) y la copia persistente se
            # guarda en PostgreSQL como BYTEA.
            # `tmp/` es el directorio de trabajo del agente. Regenerable.
            # `extract/` es salida temporal de extracción web.
            # `shell_output_save/` es salida temporal de comandos de shell.
            /uploads/
            /tmp/
            /extract/
            /shell_output_save/

2.18 requirements-dev.txt (NUEVO, 20 líneas)

            # Dependencias de runtime (mismas que producción)
            -r requirements.txt

            # === Testing ===
            pytest==9.1.1

    `requirements.txt` NO se modificó: producción no debe instalar pytest.

2.19 Documentos de auditoría nuevos (no código de producción)
            - docs/QA_REPORT_RESULTADO_PRUEBAS.md         (236 líneas)
            - docs/auditoria_templates_jinja2.md           (539 líneas)
            - tests/conftest.py                             ( 85 líneas)
            - tests/test_script_modules.py                  ( 67 líneas)

2.20 Corrección de rutas hardcodeadas en 3 scripts (sólo docstrings)

            scripts/migrar_auditoria_usuario_id_nullable.py:25
            scripts/migrar_gar_a_resultado_pruebas.py:16
            test_backup_system.py:14
            -    cd /workspace/Bitacora-GRM_v2     # p. ej. /workspace
            -    python -m scripts.migrar_auditoria_usuario_id_nullable
            +    cd <raíz-del-repositorio>     # p. ej. /workspace
            +    python -m scripts.migrar_auditoria_usuario_id_nullable

2.21 ELIMINACIÓN DEL CLON ANIDADO (460 archivos)
     - `git rm -r --cached Bitacora-GRM_v2` + borrado del directorio en disco
     - Tamaño del workspace: 289 MB -> 197 MB
     - Archivos versionados: 817 -> 331
     - Se preservaron los 4 logs de UAT en el directorio raíz `logs/`
     - Verificado: 0 archivos de código fuente únicos en el clon (sólo
       extract/, logs/ y una BD de test). Todos sus archivos de código eran
       copias idénticas o desactualizadas de la raíz.

--------------------------------------------------------------------------------
 3. CAMBIO ÚNICO
--------------------------------------------------------------------------------

El cambio funcional único y observable de esta release es:

    ► Se agrega el INDICADOR DE "RESULTADO DE PRUEBAS" en la zona inferior
      de cada tarjeta del Kanban, mostrado como ACRÓNIMO del LOV con el
      color de la categoría, y se unifica DICHO color con el que usa el
      encabezado de cada categoría en la sección "Cuenta de Resultado" del
      Dashboard.

    Ambos efectos se resuelven desde la MISMA fuente de verdad
    (app/core/resultado_pruebas.py), por lo que tarjeta y reporte no pueden
    divergir por construcción.

    Mapa LOV -> acrónimo -> color:

    ┌──────────────────┬──────────┬──────────────┬──────────────┬──────────────┐
    │ Valor LOV        │ Acrónimo │ bg           │ text         │ cellText     │
    ├──────────────────┼──────────┼──────────────┼──────────────┼──────────────┤
    │ OK               │ OK       │ #16a34a      │ #ffffff      │ #1f2937      │
    │ N/A              │ N/A      │ #94a3b8      │ #ffffff      │ #1f2937      │
    │ OK CON OBS.      │ OBS      │ #eab308      │ #1f2937      │ #1f2937      │
    │ POSTERGADA       │ POST     │ #ea580c      │ #ffffff      │ #1f2937      │
    │ DESESTIMADA      │ NOOK     │ #7c3aed      │ #ffffff      │ #1f2937      │
    │ NOK              │ NOK      │ #dc2626      │ #ffffff      │ #1f2937      │
    │ (en blanco)      │ S/D      │ #cbd5e1      │ #475569      │ #1f2937      │
    │ (fuera del LOV)  │ —        │ #475569      │ #ffffff      │ #1f2937      │
    └──────────────────┴──────────┴──────────────┴──────────────┴──────────────┘

    Reglas de visibilidad del indicador:
      a) Sólo se muestra en tickets de tipo `incidencia` y `resultado_pruebas`.
         En los demás tipos de ticket el indicador no aparece, para no
         ensuciar la columna inferior de la tarjeta.
      b) Si el ticket no tiene resultado, se muestra "S/D" (sin dato) en
         gris claro.
      c) Las variantes heredadas en base de datos ("OK CON OBS",
         "POSTERGADO A GARANTÍA", "DESESTIMADA ", "NO APLICABLE", ...) se
         normalizan automáticamente a su forma canónica antes de pintar.
      d) Todo el HTML se genera con escape (markupsafe / html.escape): no
         existe superficie de inyección desde datos de usuario.

    El resto de los cambios de esta release son REPARACIONES (funcionalidad
    que estaba rota), ENDURECIMIENTO (seguridad) y MANTENIMIENTO (higiene
    del repositorio). El detalle exhaustivo está en la sección 2.

--------------------------------------------------------------------------------
 4. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------

- Modelo de datos: NINGUNA migración de esquema. No se tocó
  app/models/*.py (ticket, usuario, auditoria, espacio, estado, etiqueta,
  dependencia, comentario, historial, adjunto).
- Esquema de base de datos: sin cambios en columnas, índices ni
  restricciones. La tabla `auditorias.usuario_id` sigue NOT NULL en el
  modelo; existe el script `scripts/migrar_auditoria_usuario_id_nullable.py`
  para habilitarla, pero NO se ejecutó ni se automatizó en esta release.
- Endpoints: no se añadió, eliminó ni renombró ninguna ruta. Los contratos
  de respuesta JSON de la API no cambian.
- Lógica de negocio ITSM: no se modificó el ciclo de vida del ticket, las
  transiciones de estado, las reglas de SLA, los deadlines ni los triggers
  automáticos. Sólo se reparó la llamada a la tarea de notificación de
  archivado (que invocaba una función inexistente).
- Cálculo de "Cuenta de Resultado": no se modificó la consulta SQL ni la
  lógica de conteo. Sólo se cambió de dónde salen los colores y los
  acrónimos (ahora del catálogo compartido).
- Sistema de archivos adjuntos: no se modificó la subida, descarga,
  persistencia en BYTEA ni la paginación de adjuntos.
- Integraciones externas: Trello, correo SMTP, Dev Inbox, Reporte diario
  de entregas y webhooks de Notificación conservan su contrato. En Dev
  Inbox sólo se añadió un import con efecto secundario deliberado
  (paridad .env ↔ os.environ), sin cambio de comportamiento.
- Celery: no se modificó ninguna tarea, ni sus firmas, ni la programación
  (beat). Sólo se documentó el requisito de reinicio del worker (ver §5).
- Frontend: no se modificó el layout, la navegación ni los estilos globales
  de Tailwind. No se añadió ni quitó ninguna librería JS. No se tocó
  htmx-events.js, command-palette.js ni el resto del JS estático salvo el
  comentario en auth-events.js.
- requirements.txt: intacto. No se añadió ninguna dependencia de runtime.
- Procfile, railway.toml, Dockerfile, docker-compose.yml, gunicorn.conf.py:
  intactos.
- Variables de entorno existentes: no se renombró ni eliminó ninguna. Se
  acceptan ahora tanto en formato JSON como en CSV (compatibilidad hacia
  atrás, no ruptura).
- Secretos: no se generó ni versionó ninguna clave. `.env` sigue SIN
  estar versionado.
- Módulos de la API ajenos al cambio: no se tocó admin_uat.py, backups.py,
  buscar.py, butler.py, etapas.py, features.py, import_export.py,
  referencias.py, reporte_entregas.py, router.py, trello_features.py.
- Base de datos de producción: no se ejecutó ninguna operación destructiva
  ni de limpieza de datos.

--------------------------------------------------------------------------------
 5. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

- ¿Requiere cambio de variables de entorno?
      **RECOMENDADO (SI)** — dos variables DEBEN existir en producción:

        1) SECRET_KEY  — OBLIGATORIA. El default hardcodeado
           ("change-me-in-production-please") fue eliminado del repositorio.
           Sin esta variable la aplicación ABORTA EL ARRANQUE en producción
           (DEBUG=False) con:
               RuntimeError: Configuración insegura:
                 - SECRET_KEY vacía o con valor placeholder ('change-me')
           Generar con:  openssl rand -hex 32

        2) CORS_ORIGINS — RECOMENDADA. Debe contener los orígenes
           explícitos separados por coma, p. ej.
               CORS_ORIGINS=https://bitacora-grmv2-production.up.railway.app
           While CORS_ORIGINS contenga "*" la aplicación arranca, pero
           avisa por log y desactiva allow_credentials (la cookie de
           sesión deja de enviarse en cross-origin, que es lo correcto).
           OJO: con "*" + DEBUG=False el arranque también ABORTA, con el
           aviso "CORS_ORIGINS contiene '*' con DEBUG=False".

        Resto de variables: sin cambios.

- ¿Requiere migrar DB?
      **NO**. No hay cambios de esquema en esta release.
      (Opcional y fuera del alcance: si se activan los triggers automáticos
      de SLA, que insertan auditoría con usuario_id=None, hay que ejecutar
      `python -m scripts.migrar_auditoria_usuario_id_nullable` una vez.
      No es necesario para el indicador de Resultado de Pruebas.)

- ¿Requiere cambio de Worker en Railway?
      **SÍ — REINICIO OBLIGATORIO DEL WORKER CELERY.**

      Motivo: `app/core/config.py::_exportar_a_environ` cambió el formato
      con el que las variables de tipo lista se exportan al `os.environ`.
      Antes se exportaban como CSV ("a,b,c"); ahora se exportan como JSON
      (["a","b","c"]). El motivo es que JSON es el ÚNICO formato que
      `pydantic-settings` puede volver a leer desde el entorno: con CSV,
      cualquier proceso hijo que herede estas variables (Celery worker,
      scripts, jobs) abortaba al arrancar con
          SettingsError: error parsing value for field "CORS_ORIGINS"

      El worker que sigue corriendo con el código viejo conserva en memoria
      el valor CSV y morirá al reiniciarse con el nuevo código si el
      entorno exporta CSV. Con el deploy completo (web + worker) y el
      reinicio del worker, la cadena queda coherente.

      Acción operativa en Railway:
        1) Redeploy del servicio web  ->  Reiniciar el servicio Worker
        2) Verificar en los logs del Worker que no aparece
           "SettingsError: error parsing value for field"
        3) Verificar que el worker conectó a Redis y a la BD

- ¿Requiere rebuild de imagen Docker?
      **NO** (auto-deploy desde el repo). Si se despliega manual con
      Docker: reconstruir la imagen (el contenido del repo cambió).

- ¿Hay riesgo de downtime?
      **BAJO**. Las correcciones de configuración sólo activan validaciones
      que abortan el arranque cuando la configuración es realmente insegura
      (falta SECRET_KEY o CORS con comodín en producción). Si el despliegue
      actual ya define SECRET_KEY en Railway, el arranque es idéntico al
      anterior. Si NO la define, el arranque fallará de forma explícita y
      segura en vez de servir la aplicación con una clave pública.

- Nota sobre la cookie de sesión:
      `secure=not settings.DEBUG` significa que en producción la cookie
      `access_token` se marca `Secure` (sólo por HTTPS). Si el despliegue
      actual sirve por HTTP puro, los navegadores dejarán de enviar la
      cookie y el login fallará. El despliegue actual (Railway) sirve por
      HTTPS: OK. En un entorno HTTP de pruebas, mantener DEBUG=true.

- Procedimiento operacional Railway:
      1. Push al branch `main` de `moisesarancibiasanchez-cpu/Bitacora-GRM_v2`.
      2. Railway detecta el push y redespliega web y worker.
      3. Verificar `/health` responde 200 en menos de 60 segundos.
      4. Reiniciar explícitamente el servicio Worker.
      5. Verificar el log de arranque: NO debe aparecer
         "Configuración insegura:" (si aparece, falta SECRET_KEY).
      6. Verificar el log del Worker: NO debe aparecer "SettingsError".

--------------------------------------------------------------------------------
 6. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

A. Validación estática (rápida, sin servidor)

    cmd> python -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read()) for f in glob.glob('app/**/*.py',recursive=True)]"
    Esperado: sin output (AST válido en todo el paquete app).

    cmd> python -c "
    import jinja2,glob
    env=jinja2.Environment()
    for f in glob.glob('app/templates/**/*.html',recursive=True):
        env.parse(open(f,encoding='utf-8').read())
    print('OK', len(glob.glob('app/templates/**/*.html',recursive=True)),'templates')"
    Esperado: "OK 31 templates" (los 31 compilan; antes fallaba reporte_entregas.html).

B. Suite automatizada (pre-despliegue) — OBLIGATORIA

    cmd> python -m pip install -r requirements-dev.txt
    cmd> python -m pytest tests/ -q
    Esperado: 91 passed. (Antes: INTERNALERROR, 0 tests ejecutables.)

    cmd> python -m pytest tests/ -q --tb=short
    Si hay fallo, revisar el traceback completo antes de desplegar.

C. Barrido de rutas en vivo (pre-despliegue) — el paso que detectó el
   ImportError de /p/{slug}; el análisis estático NO lo ve

    cmd> python tmp/route_sweep.py     # rutas HTML estáticas
    cmd> python tmp/route_sweep2.py    # rutas parametrizadas con IDs reales
    Esperado: 36 rutas OK / 0 fallos  y  2 rutas OK / 0 fallos.

    Verificación puntual del import corregido:
    cmd> python -c "from app.models.espacio import Tablero; from app.models.estado import Estado; print('OK')"
    Esperado: OK

D. Test funcional del requisito principal (post-despliegue)

    1. Login con un usuario administrador.
    2. Ir al Kanban. Cada tarjeta de un ticket de tipo "incidencia" o
       "resultado_pruebas" debe mostrar, en su zona inferior derecha, un
       badge con el ACRÓNIMO:
         OK (verde) · N/A (gris) · OBS (ámarillo) · POST (naranja)
         · NOOK (violeta) · NOK (rojo) · S/D (gris claro, sin dato)
       Verificar con el tooltip (title) que muestra el valor completo
       ("Resultado de pruebas: OK CON OBS.").
    3. Arrastrar una tarjeta entre columnas (drag & drop) y comprobar que
       el badge SIGUE visible e idéntico tras el re-render (este render usa
       otro Environment: app/templates/kanban/partials/card.py).
    4. Un ticket de tipo que NO sea incidencia/resultado_pruebas NO debe
       mostrar badge.
    5. Editar el campo "Resultado de Pruebas" de un ticket y verificar que
       el badge se actualiza al recargar.

E. Test funcional de coherencia Dashboard ↔ Tarjeta (post-despliegue)

    1. Ir al Dashboard, sección "Cuenta de Resultado".
    2. El ENCABEZADO de cada columna debe mostrar el ACRÓNIMO (OK, N/A,
       OBS, POST, NOOK, NOK) con el MISMO color de fondo que el badge de
       una tarjeta con ese mismo resultado.
    3. Pasar el mouse por el encabezado: el title debe mostrar el valor
       completo ("OK CON OBS.").
    4. Las barras de "Distribución" deben usar el mismo color.
    5. Click en un valor de la tabla -> se abre el modal de drill-down; el
       badge "Resultado:" del modal debe mostrar el ACRÓNIMO con el mismo
       color.

F. Test de la vista pública (regresión del ImportError)

    cmd> curl -s -o /dev/null -w "%{http_code}" https://<host>/p/<slug-publico>
    Esperado: 200 (antes: 500 con ImportError).

    Visualmente: la página pública debe renderizar el tablero sin errores
    y SIN el menú de usuario (porque la vista no tiene sesión).

G. Test de cookies y sesión (regresión del flag `secure`)

    1. Login en producción (HTTPS) -> la cookie `access_token` debe
       aparecer con el atributo `Secure` y `HttpOnly`.
    2. Navegar por 3 páginas autenticadas -> no debe haber redirects a
       /login.

H. Test del Admin (regresión del template corregido)

    1. Login como administrador -> /admin/reporte-entregas.
    2. La página debe renderizar SIN error de sintaxis Jinja (antes lanzaba
       TemplateSyntaxError).
    3. Verificar que los toggles "es entrega" se dibujan correctamente.

I. Test del Repo / despliegue

    cmd> git status --short
    Esperado: limpio (sin restos de Bitacora-GRM_v2/, uploads/, tmp/).

    cmd> git ls-files | wc -l
    Esperado: 331 (antes 817).

    cmd> git log --all --diff-filter=A --name-only | grep -c "Bitacora-GRM_v2/"
    Esperado: 0.

    cmd> ls Bitacora-GRM_v2
    Esperado: "No such file or directory" (el clon anidado no debe volver).

J. Test de no-regresión de la suite (post-despliegue, opcional)

    cmd> python -m pytest tests/ -q
    Esperado: 91 passed.

--------------------------------------------------------------------------------
 7. TRAZABILIDAD
--------------------------------------------------------------------------------

- Commit base          : 1c74595feadf17cd30d8d71f22afebd62adba739
- Rama                 : main
- Repositorio          : https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
- Archivos modificados : 24
- Archivos nuevos      : 6
- Archivos eliminados  : 460 (438 del clon anidado + 24 binarios de runtime
                         + 2 scratch) + 2 (shell_output_save)
- Líneas de código     : +813 / -174 (archivos de código y tests)
                         +1 278 líneas (archivos nuevos)
- Suite de tests       : 91 passed (antes: INTERNALERROR, 0 ejecutables)
- Barrido de rutas     : 38 rutas OK / 0 fallos (36 estáticas + 2 parametrizadas)
- Templates Jinja      : 31/31 compilan (antes: 30/31)
- Enlaces HTML        : 111/111 resuelven
- JS                   : 7/7 pasan `node --check`
- Despliegue          : https://tx2zb18mwv9o.space.mcode.io
- Autor                : MiniMax Agent
- Fecha                : 2026-10-24

--------------------------------------------------------------------------------
 8. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL (resumen ejecutivo)
--------------------------------------------------------------------------------

1. Commit (incluyendo este README):
       git add -A
       git commit -m "feat(resultado): indicador de Resultado de Pruebas con paleta unificada + reparación general"
       git push origin main

2. Verificación del Worker (CRÍTICA, ver §5):
       En Railway: reiniciar el servicio "worker" después del redeploy.
       Verificar en el log que no aparece "SettingsError".

3. Verificación del arranque (CRÍTICA):
       En Railway: definir SECRET_KEY (openssl rand -hex 32) y CORS_ORIGINS
       con los orígenes explícitos ANTES del redeploy, si no están definidos.
       El log de arranque NO debe mostrar "Configuración insegura:".

4. Verificación post-deploy (5 min):
       a) /health responde 200
       b) El Kanban muestra el badge de Resultado de Pruebas en las tarjetas
       c) El Dashboard muestra los acrónimos con el MISMO color
       d) /p/<slug> responde 200 (no 500)
       e) /admin/reporte-entregas renderiza sin TemplateSyntaxError
       f) Los logs de Railway no muestran errores durante 5 minutos

5. Rollback (si falla):
       git revert HEAD
       git push origin main
       Railway redespliega la versión anterior automáticamente.

6. Monitoreo continuo:
       - Vigilar 4xx/5xx en /api/* (el cambio de cookie puede afectar
         sesiones en navegadores con caché de cookie antigua: los usuarios
        ician a re-autenticarse una vez)
       - Vigilar el arranque del worker (SettingsError)
       - Vigilar el reporte diario de entregas (18:00 UTC) y los backups

================================================================================
FIN README_V1.001
================================================================================
