================================================================================
README V2.01 — COMENTARIOS: ADJUNTOS + EDICIÓN CON VENTANA 30m + REFERENCIAS #ID
================================================================================

CÓDIGO IDENTIFICATIVO DE LA ENTREGA
  Versión mayor:        2.x  (Bitácora GRM v2 — FastAPI/SQLAlchemy/Jinja2/HTMX)
  Versión de release:   2.01
  Tag / alias:          feature/comentarios-adjuntos-edic-refer
  Fecha de cierre:      2026-10-21
  Branch destino:       main (producción)
  URL de producción:    https://412y86mx2nh5.space.mcode.io
  Autor técnico:        MiniMax Agent (asistido por MiniMax M3)
  Tipo de entrega:      Feature (compatible hacia atrás)


--------------------------------------------------------------------------------
1. BASE (versión de partida)
--------------------------------------------------------------------------------
  Commit base (HEAD previo): 9bfb9f9 "Message 454432039538765 - 1792499903"
  Arquitectura heredada:
    • FastAPI + SQLAlchemy 2.x (declarativo) + Jinja2 + HTMX 1.9.12 + TailwindCSS
    • PostgreSQL 14+ en Railway (fs efímero → respaldo binario en BYTEA)
    • Idempotent migrations ejecutadas en startup
    • Modal de detalle de ticket con 7 tabs renderizado vía
      app/templates/tickets/detalle_modal.py + re-render completo en cada POST.


--------------------------------------------------------------------------------
2. CAMBIO ÚNICO (resumen ejecutivo)
--------------------------------------------------------------------------------
  Extender la pestaña "Comentarios" del modal de detalle de un ticket para que
  soporte TRES capacidades nuevas, sin romper la pestaña "Adjuntos" existente:

    A) Adjuntos dentro de comentarios
       * Subida de archivos al MISMO POST de crear comentario (paste Ctrl+V
         o selector de archivos), vinculados por FK a la fila del comentario.
       * La pestaña "Adjuntos" del ticket queda intacta y SÓLO lista archivos
         de nivel TICKET (`comentario_id IS NULL`).

    B) Edición de comentarios
       * Botón "Editar" inline en cada tarjeta de comentario.
       * Permiso:  ADMINISTRADOR (siempre) o AUTOR (dentro de ventana 30 min).
       * Cronómetro mm:ss visible para el autor; expira y oculta el botón
         silenciosamente. La ventana se RENUEVA en cada edición
         (usa `updated_at` con `onupdate=datetime.utcnow` del TimestampMixin).
       * Auditoría de trazabilidad (entidad auditada: comentario_editado).

    C) Referencias entre comentarios con sintaxis #ID
       * En el texto del comentario, escribir "#123" genera un chip clickable
         hacia el comentario #123.
       * Parser con lookbehind `(?<![\w@/])#(\d+)` que evita falsos positivos:
           - correos:      `tickets#12@x.com`  → NO captura
           - issues GH:    `ORG/repo#12`       → NO captura
           - hex con prefijo: `0x#...`         → NO captura
       * Cada comentario muestra "Refiere a:" (forward) y/o "Citado por:" (inverse)
         calculados en una sola query (mapa pre-cargado, sin N+1).


--------------------------------------------------------------------------------
3. CÓDIGO MODIFICADO (inventario por archivo)
--------------------------------------------------------------------------------

  3.1) app/models/adjunto.py
       ---------------------------------------------------------------------
       • Se agrega la columna `comentario_id` (nullable, FK a comentarios.id
         ON DELETE CASCADE, indexada).
       • `ticket_id` PERMANECE NOT NULL y se rellena con el ticket dueño del
         comentario (decisión de diseño documentada inline).
       • Se agrega la relación bidireccional `comentario = relationship(
         "Comentario", back_populates="adjuntos")`.
       • Se agrega la propiedad `es_de_comentario` (bool).

  3.2) app/models/comentario.py
       ---------------------------------------------------------------------
       • Se agrega el relationship `adjuntos` con
         `cascade="all, delete-orphan", order_by="Adjanto.created_at.asc()"`.
       • Se define la constante `PATRON_REFERENCIA = r'(?<![\w@/])#(\d+)'`.
       • Se agrega el método `extraer_referencias()` que devuelve IDs únicos
         ordenados, excluyendo la autorreferencia.

  3.3) app/db/migrations.py
       ---------------------------------------------------------------------
       • En `COLUMNS_TO_ADD["adjuntos"]` se añade la entrada
         `comentario_id` (FK a comentarios ON DELETE CASCADE, portable PG/SQLite).
       • En `INDEXES` se añade la entrada
         `ix_adjuntos_comentario` → `CREATE INDEX IF NOT EXISTS
          ix_adjuntos_comentario_id ON adjuntos(comentario_id)`.

  3.4) app/services/features_service.py
       ---------------------------------------------------------------------
       • `ComentarioService`:
           - Constante `EDIT_WINDOW_MINUTES = 30`.
           - Método `minutos_restantes(com) -> Optional[int]`.
           - Método `puede_editar(com, usuario) -> Tuple[bool, str]`
             (admin siempre; autor dentro de ventana; otros denegados).
           - Métodos `mapa_referencias(comentarios)` y `referencias_hacia(...)`.
       • `AdjuntoService.guardar_archivo(...)`:
           - Acepta `comentario_id: Optional[int] = None`.
           - Si viene `comentario_id`, valida que el comentario exista
             y pertenezca al MISMO ticket. Persiste la FK en el INSERT.
           - `ticket_id` siempre se rellena con el ticket.
       • `AdjuntoService.listar_de_ticket(...)`: filtrado `comentario_id IS NULL`
         para que la pestaña "Adjuntos" sólo muestre los del TICKET.
       • Se agrega `AdjuntoService.listar_de_comentario(comentario_id)`.

  3.5) app/api/v1/features.py
       ---------------------------------------------------------------------
       • `_render_detalle_modal_response(...)`:
           - Filtra comentarios `es_interno == False` para el rol SOLICITANTE
             (FIX de seguridad — antes se filtraba sólo en JSON).
           - Filtra adjuntos a nivel ticket (`comentario_id IS NULL`).
           - Pre-carga `adjuntos_por_comentario` en UNA query (N+1 fix).
           - Calcula `mapa_referencias_fwd` e `mapa_referencias_inv`.
           - Pasa los 3 mapas como nuevos parámetros a `render_detalle_modal`.
       • `POST /tickets/{id}/comentarios`:
           - Acepta archivos vía `form.getlist("archivos")` y `form.get("archivo")`
             (compatibilidad con ambos formatos).
           - Valida longitud máxima de texto (5000) — antes era letra muerta.
           - Si hay archivos, los guarda con `comentario_id=<nuevo_id>`.
           - En error, responde con `HX-Trigger` JSON para feedback inline.
       • `PATCH /comentarios/{id}`:
           - Aplica `ComentarioService.puede_editar()` antes de modificar.
           - Devuelve 403 con motivo si la edición no está permitida.
           - Registra auditoría (`comentario_editado`) y `db.commit()`.
       • Nuevos endpoints:
           - POST /comentarios/{id}/editar     (HTMX form para el botón Editar).
           - POST /comentarios/{id}/adjuntos   (subir adjuntos a un comentario
                                               ya creado).

  3.6) app/templates/tickets/detalle_modal.py
       ---------------------------------------------------------------------
       • `render_detalle_modal(...)` firma extendida con 3 parámetros nuevos:
           `adjuntos_por_comentario`, `mapa_referencias_fwd`, `mapa_referencias_inv`.
       • Pestaña "Comentarios" completamente reescrita:
           - Card por comentario con data-attrs (id, is-admin, is-author,
             updated-at, edit-window).
           - Cálculo inline de `_is_admin`, `_is_autor`, `_can_edit`,
             `_min_left`, `_edit_reason`.
           - Botón "Copiar #ID" (ancla a `navigator.clipboard.writeText`).
           - Botón "Editar" con cronómetro "mm:ss" (texto vacío ⇒ expirado).
           - Adjuntos inline (imágenes vs no-imágenes con icono + tamaño).
           - Bloques "Refiere a:" y "Citado por:" (chips clickables).
           - Form de edición inline (initial `hidden`).
           - Form de subida INLINE dentro de la tarjeta con
             `enctype="multipart/form-data"`,
             `data-dropzone-comentario="1"`, soporte múltiples archivos y paste.
           - Hint "Pega una imagen con Ctrl+V" en el textarea.

  3.7) app/static/js/htmx-events.js
       ---------------------------------------------------------------------
       • Se agrega `setupComentariosDropzone(cont, form)`:
           - WeakMap `_comentarioFilesState` con archivos pendientes por form.
           - `_comentarioFilePreview(f)` con `URL.createObjectURL` para thumbs.
           - Handler paste en el textarea (`clipboardData.items` kind === "file").
           - Handler change en `<input type=file>`.
           - Handler drag&drop sobre el form.
           - `_comentarioRefreshPendientes(form)` que sincroniza archivos
             pegados con `<input>.files` vía DataTransfer API.
       • Se agrega `mountComentariosFeatures(cont)`:
           - Click delegado para .btn-edit-comment, .btn-cancel-edit,
             .btn-copy-ref, .ref-chip.
           - Cronómetro con `setInterval(1000)` que actualiza `mm:ss` y
             remueve el botón al expirar.
       • `_comentarioRenderRefs(cont)`: sustituye `#ID` por `<a>` chips en
         cada `.comentario-texto`.
       • `_comentarioRefChipClick(e)`: scroll + highlight al destino.
       • `reinitModalExtras()` invoca los nuevos montajes tras el swap HTMX.


--------------------------------------------------------------------------------
4. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------
  • La pestaña "Adjuntos" del ticket sigue funcionando exactamente igual
    (sigue listando `comentario_id IS NULL`). No se removió ni reemplazó.
  • El endpoint `DELETE /adjuntos/{id}` conserva su auditoría y permisos.
  • El contrato JSON de los GET endpoints públicos permanece idéntico.
  • El modelo `Ticket.comentarios` y su `cascade="all, delete-orphan"` siguen
    igual: borrar un ticket borra TODOS sus comentarios y, por la nueva
    cascada, también todos los adjuntos (los del ticket y los de comentario).
  • El flujo del modal (re-render completo tras cada acción) sigue siendo el
    patrón canónico del proyecto; no se introdujo client-side routing.
  • La ventana de 30 min NO aplica para administradores.
  • No se introdujeron dependencias nuevas: el pegado usa `clipboardData` y
    `DataTransfer`, nativos del navegador.


--------------------------------------------------------------------------------
5. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------
  5.1) Migración de esquema (idempotente, ejecutada en startup)
       Comando:       (ninguno — se ejecuta automáticamente con la app)
       Tiempo:        < 1 segundo en BD con <100k adjuntos.
       Bloqueos:      ninguno (ADD COLUMN sin default = metadata-only en PG).
       Rollback:      `ALTER TABLE adjuntos DROP COLUMN comentario_id;`
                       `DROP INDEX IF EXISTS ix_adjuntos_comentario_id;`
       Riesgo:        cero. Si la columna ya existe, se omite.

  5.2) Backend (FastAPI)
       • No requiere reinstalar dependencias (requirements.txt intacto).
       • El startup ejecuta `apply_migrations(engine)` antes de aceptar
         requests → la nueva columna queda disponible en el PRIMER arranque
         posterior al deploy.

  5.3) Frontend (HTMX + Tailwind + JS estático)
       • `htmx-events.js` cambia; debe servirse desde el mismo proxy
         (no se usan CDNs nuevos ni se rompieron CDNs viejos).

  5.4) Almacenamiento
       • No se migra el filesystem; los adjuntos pre-existentes del ticket
         siguen en `/app/uploads/ticket_<id>/<uuid>.<ext>` con respaldo BYTEA.
       • El respaldo binario es la fuente de verdad: aunque el fs se borre,
         las descargas siguen sirviendo el contenido por la copia BYTEA.

  5.5) Configuración de Railway
       • Variables de entorno: sin cambios.
       • Volumen persistente: no requerido (la columna BYTEA es el backup).


--------------------------------------------------------------------------------
6. PROCEDIMIENTO DE PRUEBA RECOMENDADO (smoke + regresión)
--------------------------------------------------------------------------------
  Smoke (5 minutos, 6 escenarios críticos):

    [T1] Pegar imagen en un comentario
         1) Abrir un ticket → tab "Comentarios".
         2) En el textarea escribir "captura:" y pegar (Ctrl+V) un PNG.
         3) Debe aparecer un chip con thumbnail + botón ×.
         4) Click "Comentar".
         5) Esperar: la tarjeta nueva muestra el texto + el thumbnail inline.

    [T2] Subir archivo en un comentario existente
         1) En una tarjeta ya existente, usar el form inferior "Adjuntar".
         2) Seleccionar 1 archivo .txt + 1 .png.
         3) Esperar: aparece el chip "Subidos: 2" y luego se muestra
            el thumbnail/icono en la tarjeta.

    [T3] Editar como autor dentro de la ventana (30 min)
         1) Como autor del último comentario, click "Editar".
         2) Modificar texto + guardar.
         3) Esperar: badge "(editado)" + texto_original visible al hover.
         4) El cronómetro debe renovar a 30:00.

    [T4] Bloqueo de edición fuera de ventana
         1) Adelantar el reloj del servidor o esperar 31 minutos.
         2) Intentar editar como AUTOR.
         3) Esperar: HTTP 403 con mensaje "La ventana de edición expiró".
         4) Como ADMINISTRADOR, la edición debe seguir funcionando.

    [T5] Referencias entre comentarios
         1) Crear comentario #1 con texto "base".
         2) Crear comentario #2 con texto "ver #1 para contexto".
         3) Esperar: "#1" se renderiza como chip clickeable de color azul.
         4) Click en el chip → scroll al comentario #1 + borde amarillo.
         5) En la tarjeta del comentario #1 debe aparecer "Citado por: #2".

    [T6] Comentario interno NO visible para SOLICITANTE
         1) Como Agente, crear comentario con checkbox "interno".
         2) Como Solicitante (o con su sesión), recargar el ticket.
         3) Esperar: NO ve ese comentario; Agente/Admin SÍ lo ven.

  Regresión (3 minutos):

    [R1] Tab "Adjuntos" del ticket sigue listando adjuntos viejos y nuevos
         a nivel ticket. Confirmar que ningún adjunto de comentario se filtra
         allí.
    [R2] Descargar un adjunto existente: el endpoint `GET /adjuntos/<id>/descargar`
         debe seguir sirviendo el archivo (con respaldo BYTEA).
    [R3] Eliminar un comentario con adjuntos: los adjuntos deben
         desaparecer del listado (cascada ON DELETE CASCADE).
    [R4] Como OBSERVADOR: el botón "Editar" NO debe aparecer
         ni para sus propios comentarios.


--------------------------------------------------------------------------------
7. SEÑALES DE SALUD (validación automática)
--------------------------------------------------------------------------------
  En producción, después del deploy:
    GET https://<host>/health                                → 200 OK
    GET /api/v1/tickets/<id>/detalle-html                    → 200 OK y contiene
                                                                "comentarios-lista"
    POST /api/v1/tickets/<id>/comentarios (con archivo)      → 201 Created y
                                                                respuesta con hx-trigger
    PATCH /api/v1/comentarios/<id>  con cookie SOLICITANTE   → 403 si no es suyo
    PATCH /api/v1/comentarios/<id>  con cookie ADMIN         → 200 OK


--------------------------------------------------------------------------------
8. AUDITORÍA Y TRAZABILIDAD
--------------------------------------------------------------------------------
  • Cada edición de comentario genera un registro en `auditorias`
    con `accion='comentario_editado'` y `detalle` con el id del comentario.
  • Cada upload a un comentario queda en `auditorias` con la acción del
    adjunto (legado).
  • La creación/eliminación de comentarios no introdujo cambios (ya
    auditaba antes).


--------------------------------------------------------------------------------
9. NOTAS DE DISEÑO Y PORQUÉ
--------------------------------------------------------------------------------
  • `ticket_id` se mantiene NOT NULL en `Adjunto` para no romper
    `Ticket.adjuntos`, `listar_de_ticket(...)` y el cascade-delete del ticket.
  • La FK de `Adjunto.comentario_id` lleva `ON DELETE CASCADE` para que
    al borrar un comentario, sus adjuntos queden limpios automáticamente.
  • La ventana de edición usa `updated_at` (no `created_at`) para que CADA
    edición RENUEVE los 30 minutos. Eso da un patrón natural: "edita
    libremente los primeros 30 minutos tras tu último cambio".
  • El parser `#ID` usa lookbehind negativo para NO confundir con
    correos electrónicos y referencias estilo GitHub Issues (las más
    comunes en comentarios reales).
  • El "pre-carga en una sola query" (N+1 fix) evita disparar hasta N
    SELECTs adicionales al renderizar un ticket con muchos comentarios.


--------------------------------------------------------------------------------
10. CONTACTO Y RESPONSABLES
--------------------------------------------------------------------------------
  Diseño, implementación y validación: MiniMax Agent / MiniMax M3
  Mantenedor del producto:             usuario moisesarancibiasanchez-cpu
  Stack de producción:                 Railway (PostgreSQL 14) + Python 3.11
  Cambio único de release:             features A + B + C (ver §2).
================================================================================
FIN del README_V2.01
================================================================================
