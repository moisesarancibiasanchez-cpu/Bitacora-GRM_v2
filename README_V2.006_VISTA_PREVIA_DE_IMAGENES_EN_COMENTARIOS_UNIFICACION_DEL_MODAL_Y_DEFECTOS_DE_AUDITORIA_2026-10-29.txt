================================================================================
README V2.006 - VISTA PREVIA DE LAS IMAGENES DE LOS COMENTARIOS, UNIFICACION
DEL MODAL DE DETALLE Y DEFECTOS DETECTADOS POR LA AUDITORIA
Proyecto: Bitacora GRM v2
Fecha: 2026-10-29
Rama base: main y release/v2.001 (commit 354bf20)
Estado: CODIGO LISTO Y VERIFICADO EN LOCAL. PENDIENTE DE DESPLEGUE.
================================================================================

  NOTA SOBRE LA NUMERACION: este documento continua la serie V2 del
  repositorio (V2.002, V2.003, V2.004, V2.005), de modo que el correlativo
  incremental de 3 cifras es V2.006. La serie V1 termino en V1.006 y publicar
  un "V1.007" mixingaria dos series distintas. El resto del formato (7
  secciones, seccion 0 con el parche exacto, apendice A con el diff y
  seccion 9 con el addendum de despliegue) es identico al de los lotes
  anteriores.

================================================================================
0. PARCHE EXACTO
================================================================================

  0.1 FICHEROS INTERVENIDOS

    Nuevos:
      app/services/ticket_modal_service.py          (SSOT de los datos del modal)
      tests/test_v2006_preview_imagen_comentarios.py (nuevo, 20 tests)

    Modificados:
      app/templates/tickets/detalle_modal.py    (imagen del comentario)
      app/static/js/image-preview.js            (deteccion de la URL de adjuntos)
      app/static/js/htmx-events.js              (re-enganche del lightbox)
      app/api/v1/tickets.py                     (4 endpoints del modal + import)
      app/api/v1/features.py                    (render del modal tras comentar)
      app/schemas/features.py                   (ComentarioRead.texto)
      app/api/v1/metricas.py                    (KPI "Incidencias Abiertas")
      app/core/codigo_ticket.py                 (unicidad del correlativo INC-)
      app/api/v1/import_export.py               (docstring del importador)

    Fuera del repositorio (operacion local, sin commit):
      .git/sequencer/  ->  `git revert --quit` (secuenciador huerfano)

  0.2 A. VISTA PREVIA DE LAS IMAGENES DE LOS COMENTARIOS

    A.1 app/templates/tickets/detalle_modal.py

        La miniatura del adjunto de un comentario pasa a llevar el atributo
        que activa el lightbox, y se distingue el caso "el archivo ya no
        esta en disco":

        -    <img src="/api/v1/adjuntos/{{ a.id }}/descargar" alt="{{ a.nombre_original }}"
        -         class="w-10 h-10 object-cover rounded border border-slate-200"
        -         loading="lazy">
        +    <img src="/api/v1/adjuntos/{{ a.id }}/descargar" alt="{{ _com_nombre }}"
        +         data-preview-image
        +         data-preview-title="{{ _com_nombre }}"
        +         title="Click para vista previa"
        +         class="w-10 h-10 object-cover rounded border border-slate-200 cursor-zoom-in"
        +         loading="lazy">

        Ademas se calculan antes del bucle el nombre, el mime, la extension
        y la disponibilidad del adjunto, para aplicar la misma politica que
        la pestana "Adjuntos":

        {% set _com_nombre = (a.nombre_original or a.filename or a.nombre or '') %}
        {% set _com_mime = (a.mime_type or '') %}
        {% set _com_ext = _com_nombre.split('.')[-1].lower() if _com_nombre else '' %}
        {% set _com_es_imagen = a.es_imagen if a.es_imagen is defined else (_com_mime.startswith('image/') or _com_ext in ['png','jpg','jpeg','gif','webp','bmp','svg','avif']) %}
        {% set _com_disponible = (a.disponible if a.disponible is defined else None) %}

        y, si el archivo ya no esta disponible, se pinta el aviso en lugar
        de una imagen rota:

        {% elif _com_es_imagen %}
          <span class="inline-flex items-center justify-center w-10 h-10 rounded border border-amber-200 bg-amber-50 text-amber-500"
                title="Archivo no disponible">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">...</svg>
          </span>

    A.2 app/static/js/image-preview.js

        El lightbox tiene dos reglas de activacion: la EXPLICITA (el atributo
        data-preview-image) y la IMPLICITA (cualquier <img> de #modal-root
        cuyo src termine en extension de imagen). La URL del endpoint de
        descarga NO termina en extension, asi que la regla implicita no la
        detectaba nunca:

        +  // Las imagenes servidas por el endpoint de adjuntos NO llevan extension en la
        +  // URL (/api/v1/adjuntos/{id}/descargar), asi que la deteccion por extension
        +  // no las ve. Se reconocen por su forma para que cualquier vista que las
        +  // pinte (pestana de comentarios, pestana de adjuntos, modales) sea
        +  // previsualizable sin depender de un atributo explicito.
        +  var ADJUNTOS_URL = /\/api\/v1\/adjuntos\/\d+\/descargar(\?.*)?$/i;
        +
          function isImageSrc(src) {
            if (!src) return false;
        -    return IMG_EXT.test(src);
        +    return IMG_EXT.test(src) || ADJUNTOS_URL.test(src);
          }

        Y la imagen que cuelga de un enlace con data-preview-image no se
        engancha dos veces (ganaba el click la regla implicita y se perdia el
        titulo del enlace):

        -      if (img.closest('[data-preview-image]')) return;
        +      var contenedor = img.closest('[data-preview-image]');
        +      if (contenedor && (contenedor === img || contenedor.tagName === 'A')) return;

    A.3 app/static/js/htmx-events.js

        El modal de detalle se inserta de dos maneras: por HTMX (que emite
        htmx:afterSwap, ya listened por el lightbox) y por fetch + innerHTML
        (Kanban, Gantt, calendario, command palette y dashboard), que NO
        emite ningun evento de HTMX. En esas vias el lightbox se quedaba sin
        enganchar. Se engancha desde el helper comun de re-inicializacion:

          function reinitModalExtras() {
            setupAdjuntosDropzone();
            setupComentariosDropzone();
            setupMarkdownEditors();
            mountComentariosFeatures();
        +   // Re-enganchar la vista previa de imagenes (lightbox)...
        +   if (window.BitacoraImagePreview &&
        +       typeof window.BitacoraImagePreview.attach === 'function') {
        +     try { window.BitacoraImagePreview.attach(document); } catch (_) { /* noop */ }
        +   }
          }

  0.3 B. UNA SOLA FUENTE DE VERDAD PARA LOS DATOS DEL MODAL

    B.1 app/services/ticket_modal_service.py (NUEVO)

        Tres funciones que son las reglas unicas del modal:

        +  def comentarios_visibles(db, ticket_id, usuario) -> list
        +      """Comentarios visibles: los INTERNOS no se muestran al solicitante"""
        +  def adjuntos_del_ticket(db, ticket_id) -> list
        +      """adjuntos que cuelgan del TICKET (comentario_id IS NULL)"""
        +  def adjuntos_por_comentario(db, comentarios) -> dict
        +      """adjuntos de cada comentario, en una sola consulta (sin N+1)"""

    B.2 app/api/v1/tickets.py (4 endpoints)

        detalle_html, actualizar_ticket_campo, guardar_ticket_campos y
        actualizar_campo_personalizado montaban sus propias consultas. Los
        cuatro pasan ahora a consumir el SSOT:

        -    comentarios = (
        -        db.query(Comentario)
        -        .filter(Comentario.ticket_id == ticket_id)
        -        .order_by(Comentario.created_at.asc())
        -        .all()
        -    )
        -    adjuntos = (
        -        db.query(Adjunto)
        -        .filter(Adjunto.ticket_id == ticket_id)
        -        .order_by(Adjunto.created_at.desc())
        -        .all()
        -    )
        +    comentarios = ticket_modal_service.comentarios_visibles(db, ticket_id, usuario)
        +    adjuntos = ticket_modal_service.adjuntos_del_ticket(db, ticket_id)
        +    adjuntos_por_comentario = ticket_modal_service.adjuntos_por_comentario(
        +        db, comentarios
        +    )

        y los cuatro passes a la plantilla el diccionario de adjuntos por
        comentario (antes no se pasaba, y por eso la imagen del comentario no
        se renderizaba):

        +        adjuntos_por_comentario=adjuntos_por_comentario,

    B.3 app/api/v1/features.py

        El render del modal tras crear/editar/borrar un comentario
        reimplementaba las mismas reglas; ahora consume el mismo SSOT
        (mismo comportamiento, una sola fuente).

  0.4 C. FIN DEL 500 EN EL LISTADO JSON DE COMENTARIOS

        app/schemas/features.py

        -  class ComentarioRead(ComentarioBase):
        +  class ComentarioRead(ComentarioBase):
               model_config = ConfigDict(from_attributes=True)
        +      # La LECTURA no aplica el limite de escritura (5.000 caracteres)...
        +      texto: str
               id: int

        ComentarioRead heredaba de ComentarioBase el ``max_length=5000`` del
        ESCRITIDO. En produccion, GET /api/v1/tickets/6/comentarios devolvia
        HTTP 500 de forma determinista (5 de 5 intentos): el comentario id=10
        del ticket 6 tiene 17.607 caracteres y Pydantic fallaba al validar la
        respuesta (ResponseValidationError). El limite de 5.000 caracteres
        sigue vigente al ESCRIBIR (ComentarioCreate y ComentarioUpdate).

  0.5 D. KPI "Incidencias Abiertas" (comparacion insensible a acentos)

        app/api/v1/metricas.py

        -    func.lower(Estado.nombre).notin_(["produccion ok", "desestimada"]),
        +    _nombre_estado_norm.notin_(["produccion ok", "desestimada"]),
        +    _resultado_no_desestimada,

        con:

        +    _nombre_estado_norm = func.lower(Estado.nombre)
        +    for _acento, _ascii in (("a", "a"), ("e", "e"), ("i", "i"),
        +                            ("o", "o"), ("u", "u"), ("n", "n")):
        +        _nombre_estado_norm = func.replace(_nombre_estado_norm, _acento, _ascii)
        +    _resultado_no_desestimada = or_(
        +        Ticket.resultado_pruebas.is_(None),
        +        func.upper(func.trim(Ticket.resultado_pruebas)) != "DESESTIMADA",
        +    )

        Motivo: el nombre canonico del estado es "Produccion OK" CON tilde (lo
        insertan asi app/db/init_db.py y la migracion 4.6), pero
        ``func.lower()`` NO quita acentos, de modo que la comparacion
        NUNCA excluia ese estado. En una base nueva, el KPI contaba como
        "abiertas" las incidencias ya desplegadas. Ademas, "DESESTIMADA" es
        un valor de ``resultado_pruebas``, no un estado: ahora se excluyen
        las dos cosas.

  0.6 E. ROBUSTEZ Y DOCUMENTACION

        E.1 app/core/codigo_ticket.py

            El correlativo INC- ahora comprueba que el codigo este libre
            (igual que las otras dos familias). Antes, un hueco en la
            numeracion devolvia un codigo ya existente y el INSERT fallaba
            por la restriccion UNIQUE de tickets.codigo (500 en vez de un
            error controlado):

            -    ultimo = db.query(func.max(Ticket.id)).scalar() or 0
            -    return f"{PREFIJO_INCIDENCIA}{(ultimo + 1):03d}"
            +    ultimo = db.query(func.max(Ticket.id)).scalar() or 0
            +    for offset in range(MAX_INTENTOS_NUMERACION):
            +        numero = ultimo + 1 + offset
            +        candidato = f"{PREFIJO_INCIDENCIA}{numero:03d}"
            +        existe = db.query(Ticket).filter(Ticket.codigo == candidato).first()
            +        if not existe:
            +            return candidato
            +    raise ConflictoNumeracionError(...)

            Y se corrige el docstring, que citaba un simbolo inexistente
            (``TIPOS_NO_INCIDENCIA``) y daba a entender que el filtro del
            dashboard usaba una funcion que no usa (``es_tipo_no_incidencia``):

            -  Ademas el modulo publica ``TIPOS_NO_INCIDENCIA`` y ``es_tipo_no_incidencia``,
            -  que son los que usa el filtro del dashboard para garantizar
            +  Ademas el modulo publica ``NOMBRES_TIPOS_NO_INCIDENCIA`` (los valores que
            +  realmente se guardan en ``tickets.tipo``) y el helper ``tipos_no_incidencia()``,
            +  que son los que usa el filtro del dashboard para garantizar estructuralmente

        E.2 app/api/v1/import_export.py

            El docstring seguia diciendo que el importador crea tickets con
            codigo 'INC-XXX', cuando desde el lote V2.004 usa la regla por
            tipo (INC-/SOL-/GAR_):

            -  El importador es tolerante: crea tickets nuevos con codigo tipo
            -  'INC-XXX' (mismo formato que el servicio estandar) en el estado
            -  inicial del sistema.
            +  El importador es tolerante: crea tickets nuevos cuyo codigo lo genera la
            +  regla unica del proyecto ('app/core/codigo_ticket.py'), es decir, 'INC-XXX'
            +  para las incidencias, 'SOL-XXX' para Solicitud/Problema/Cambio y
            +  'GAR_<HU>_<NNN>' para los tickets de Resultado de Pruebas, siempre en el
            +  estado inicial del sistema.

        E.3 app/api/v1/tickets.py

            Import a nivel de modulo del simbolo usado en una anotacion de
            tipo entre comillas (que rompia cualquier resolucion de tipos en
            runtime):

            +  from app.models.etapa_proyecto import TicketEtapa

  0.7 F. OPERACION LOCAL (sin commit): SECUENCIADOR DE REVERT HUERFANO

        El repositorio tenia un secuenciador de "git revert --no-commit"
        huerfano desde el 2026-10-26 con 9 reversiones pendientes (una de
        ellas, d464f18, es la base del indicador de Resultado de Pruebas y
        del acronimo DESEST del lote V2.005). Un "git revert --continue"
        habria deshecho de golpe los lotes V2.002 a V2.005.

        Se limpio SIN tocar el arbol ni el indice:

            git revert --quit

        Tras la operacion: `.git/sequencer` ya no existe, HEAD sigue en
        354bf20 y el arbol de trabajo conserva exactamente los cambios del
        presente lote.

  0.8 TESTS NUEVOS (tests/test_v2006_preview_imagen_comentarios.py, 20 tests)

        - test_la_imagen_del_comentario_lleva_el_atributo_de_preview
        - test_un_archivo_que_no_es_imagen_no_se_marca_como_preview
        - test_una_imagen_no_disponible_avisa_en_vez_de_romperse
        - test_los_adjuntos_de_un_comentario_no_aparecen_en_la_pestana_adjuntos
        - test_un_solicitante_no_ve_los_comentarios_internos
        - test_un_agente_si_ve_los_comentarios_internos
        - test_las_dos_rutas_de_render_muestran_lo_mismo
        - test_el_ssot_del_modal_es_la_unica_fuente
        - test_el_lightbox_reconoce_la_url_de_descarga_de_adjuntos
        - test_la_deteccion_por_extension_sigue_funcionando
        - test_el_lightbox_no_engancha_dos_veces_la_misma_imagen
        - test_reinit_modal_extras_reengancha_el_lightbox
        - test_la_plantilla_base_carga_el_lightbox
        - test_la_sintaxis_js_del_lightbox_es_valida
        - test_la_sintaxis_js_de_htmx_events_es_valida
        - test_los_adjuntos_del_ticket_siguen_con_preview
        - test_el_modal_sigue_ofreciendo_la_pestana_de_comentarios
        - test_el_listado_de_comentarios_no_falla_con_texto_largo
        - test_al_crear_un_comentario_se_mantiene_el_limite_de_5000
        - test_el_kpi_de_incidencias_abiertas_excluye_produccion_ok_con_tilde

  0.9 DIENTES DE LA SUITE (comprobado revirtiendo cada arreglo)

        Sin data-preview-image en la plantilla ....... 3 failed
        Sin el relaxation del esquema de lectura ...... 1 failed
        Sin la normalizacion de acentos del KPI ....... 1 failed
        Sin la exclusion de resultado DESESTIMADA .... 1 failed
        Restaurado ................................... 20 passed

================================================================================
1. BASE
================================================================================

  Base: commit 354bf20 (punta de 'main' y de 'release/v2.001'), que contiene
  el lote V2.005 (1b49fe0 + 354bf20).

  1.1 PEDIDO DEL PROPIETARIO (2026-10-29)

    "En la pestana comentarios del detalle del ticket se debe incorporar la
     funcionalidad de previsualizacion de la imagen cargada en el comentario.
     Entiendo que esta funcionalidad ya estaba ejecutandose, pero algo
     sucedio que hoy NO se esta visualizando la imagen al hacer clic sobre
     ella. Revisa el estado del proyecto en general y detecta problemas que
     se generaron. Corrige los errores que seazonaron fuera de tu gestion.
     Vuelve el proyecto a que este 100% operativo."

  1.2 COMO SE ABORDAJO EL PEDIDO (3 agentes en paralelo)

    Se lanzo una bateria de tres agentes de MiniMax en paralelo, con la
    Revision de cada hallazgo antes de tocar nada:

      A) Diagnostico de la vista previa: localizo el lightbox
         (app/static/js/image-preview.js), las dos reglas de activacion y el
         markup de los adjuntos del comentario. Confirmo la causa raiz.
      B) Auditoria general del proyecto: 242 rutas, 35 plantillas, 8
         estaticos, todo app/static/js/ y el AST de app/ completo.
      C) Verificacion en produccion (solo GET y POST de login): barrido de
         los 933 tickets y de las descargas de adjuntos.

    Los tres agentes son fuente de HALLAZGOS, no de verdad: cada punto se
    verifico a mano en el codigo y, cuando afectaba a produccion, con
    llamadas de solo lectura.

  1.3 DIAGNOSTICO DEL AGENTE A (confirmado y ampliado)

    Causa raiz 1 (la que ve el usuario): el markup de los adjuntos del
    comentario se introdujo en el commit 6038fc2 sin conectar el lightbox.
    El atributo data-preview-image solo estaba en la pestana "Adjuntos", y
    la URL del endpoint de descarga no termina en extension, asi que la
    regla implicita tampoco la detectaba. Es decir, la previsualizacion
    NUNCA funciono en los comentarios (no es una regresion de los lotes
    V2.003-V2.005).

    Causa raiz 2 (mas profunda, y la que hace que la imagen ni siquiera se
    vea): el modal de detalle se renderiza desde dos rutas distintas y la
    ruta normal NO precargaba los adjuntos por comentario, de modo que el
    bloque de adjuntos inline del comentario NO SE RENDERIZABA. El
    archivo solo aparecia de rebote en la pestana "Adjuntos" del ticket y
    desaparecia al reabrir el ticket.

    Causa raiz 3: en las vistas que insertan el modal con fetch + innerHTML
    (Kanban, Gantt, calendario, command palette y dashboard) htmx no emite
    htmx:afterSwap, de modo que el lightbox no se enganchaba.

  1.4 HALLAZGOS DEL AGENTE B (verificados uno a uno)

    1. Secuenciador de "git revert" huerfano con 9 reversiones pendientes
       desde el 2026-10-26. VERIFICADO y CORREGIDO (seccion 0.7). Un
       "git revert --continue" habria deshecho los lotes V2.002 a V2.005.
    2. KPI "Incidencias Abiertas": el filtro comparaba contra 'produccion
       ok' (sin tilde) y el estado canonico es "Produccion OK" (con
       tilde). VERIFICADO y CORREGIDO (seccion 0.5).
    3. Ref de GitHub desactualizado en local. FALSO POSITIVO: el push
       devolvio PUSH_EXIT=0 ("e7806da..1b49fe0 main -> main") y los tres
       servicios de Railway construyeron commitHash 354bf20 desde la rama
       main, lo que demuestra que GitHub tiene el commit. Es solo el ref
       de seguimiento local, que no se actualiza al empujar por URL.
    4. Tailwind y SortableJS se cargan desde CDN. REAL, pero FUERA del
       alcance de este lote: exige compilar Tailwind (npm) o vendorizar
       Sortable, lo que no se puede hacer sin anadir dependencias
       (requirements.txt esta fijado). Se documenta en la seccion 3.
    5. Trabajo V2.006 sin versionar (este mismo lote).
    6. Anotacion de tipo entre comillas sin import (TicketEtapa).
       VERIFICADO y CORREGIDO (seccion 0.6.E.3).
    7. Docstring de codigo_ticket.py con un simbolo inexistente.
       VERIFICADO y CORREGIDO.
    8. Docstring de import_export.py con la regla de codigo antigua.
       VERIFICADO y CORREGIDO.
    9. Comentario obsoleto en el filtro del KPI. VERIFICADO y CORREGIDO.
    10. _generar_codigo_inc sin comprobacion de unicidad. VERIFICADO y
        CORREGIDO.
    11. Ruido de linters (imports sin usar, variables muertas) y 12.
        "class-based config" obsoleto en Pydantic v2: limpieza posterior,
        no urgente y sin impacto en el funcionamiento.

    Ademas, el agente B verifico que NO hay: enlaces internos rotos,
    funciones JS globales sin definir, imports Python rotos, errores de
    sintaxis JS (el validador del lote V2.003 aplicado a las 24 plantillas,
    a los 6 .js y a los bloques inline no encuentra ni un fallo) ni
    marcadores pendientes reales.

  1.5 HALLAZGOS DEL AGENTE C (verificados en produccion, solo lectura)

    - Salud: /health, /ready, /info -> 200, con database ok y redis ok.
    - Login: 200. Sin cookie, los endpoints privados devuelven 401 (correcto).
    - La descarga de adjuntos FUNCIONA: 32 de 34 imagenes devuelven 200,
      Content-Type image/png y bytes magicos 89 50 4E 47 (PNG real). Las 2
      restantes (ids 1 y 2, ticket 1) devuelven 410 "Archivo no disponible":
      su copia fisica se purgo y no tienen respaldo en BD. Es el
      comportamiento previsto, no un error.
    - BARRIDO COMPLETO de los 933 tickets: 45 tienen comentarios, 92
      bloques de comentario renderizados y 0 bloques "Adjuntos del
      comentario". En produccion NO EXISTE ningun comentario con adjunto
      (todos los Adjunto tienen comentario_id NULL). Por eso el caso que
      reporto el propietario no se puede reproducir con los datos
      actuales: hay que SUBIR una imagen en un comentario para comprobarlo
      (procedimiento 5.2).
    - HALLAZGO CRITICO: GET /api/v1/tickets/6/comentarios devolvia HTTP 500
      de forma determinista (5 de 5 intentos). Causa raiz verificada: el
      comentario id=10 del ticket 6 tiene 17.607 caracteres y el esquema de
      RESPUESTA heredaba el max_length=5000 del esquema de escritura.
      VERIFICADO y CORREGIDO (seccion 0.4).
    - El endpoint clave de comentarios devolvia 500 solo en ese ticket; los
      otros 44 con comentarios devolvian 200.

================================================================================
2. CAMBIO UNICO
================================================================================

  OBJETIVO UNICO: que el detalle del ticket se comporte IGUAL en todas las
  vistas por las que se abre, y que lo que muestra sea verdad.

  2.1 QUE SE PERCIBE AHORA

    a) Al pulsar una imagen adjunta a un comentario se abre la vista previa
       (lightbox) a pantalla completa, con el boton de descarga, en
       cualquier vista: Kanban, lista de tickets, dashboard, Gantt,
       calendario, command palette y bandeja de salida.

    b) La imagen de un comentario se ve DENTRO del comentario, en la
       pestana "Comentarios", con su miniatura.

    c) La pestana "Adjuntos" contiene solo los archivos del TICKET. Los
       adjuntos de un comentario ya no aparecen de rebote alli.

    d) Un solicitante NO ve los comentarios internos (nota interna del
       equipo), en ninguna vista. Antes se veian por la ruta normal del
       modal.

    e) El listado JSON de comentarios de un ticket ya no puede devolver
       500 por un comentario largo heredado.

    f) El KPI "Incidencias Abiertas" no puede contar como abiertas las
       incidencias ya desplegadas en produccion, tanto si el estado se
       llama "Produccion OK" como "produccion ok".

  2.2 POR QUE SE RESUELVE EN EL SERVIDOR Y NO SOLO EN LA PLANTILLA

    El sintoma visible ("no se abre la vista previa") y la causa de fondo
    ("el modal se comporta distinto segun por donde se abre") son el mismo
    defecto: dos rutas de render con dos conjuntos de datos distintos. Arreglar
    solo la plantilla habria dejado el resto de los defectos (la imagen que
    no se ve, el archivo duplicado en otra pestana, la fuga de comentarios
    internos). Por eso el lote introduce una fuente unica de verdad
    (app/services/ticket_modal_service.py) y las dos rutas la consumen.

  2.3 COMPATIBILIDAD

    - La plantilla sigue aceptando comentarios y adjuntos como antes; solo
      cambia lo que se les pasa.
    - La API publica no cambia: mismos endpoints, mismos cuerpos, mismos
      codigos de respuesta.
    - El esquema de lectura de comentarios se relaja SOLO para la lectura;
      el limite de 5.000 caracteres al escribir se mantiene intacto.
    - El KPI conserva hoy exactamente el mismo valor (5) en produccion: el
      defecto era latente (solo se rompia con el nombre canonico del
      estado, con tilde).

================================================================================
3. QUE NO SE MODIFICO
================================================================================

  - La base de datos: ni una escritura, ni una migracion, ni un renumerado.
    Ningun ticket, comentario ni adjunto cambia de valor.

  - Los conteos del dashboard: el KPI "Incidencias Abiertas" sigue valiendo
    5 en produccion (medido antes y despues del cambio sobre los 933
    tickets reales: 5 con el filtro actual y 5 con el filtro corregido).
    Lo que cambia es que el filtro ya no depende de que el estado se
    guarde con o sin tilde.

  - La vista previa de la pestana "Adjuntos" del ticket: sigue funcionando
    igual (el atributo data-preview-image sigue en el enlace que envuelve
    a la miniatura).

  - Los adjuntos legacy sin copia fisica: siguen devolviendo 410 "Archivo
    no disponible" en la descarga. No se ha regenerado ni perdido ningun
    archivo.

  - El comentario largo heredado del ticket 6: NO se trunca ni se modifica.
    Solo se deja de validar su longitud al leerlo. Su contenido sigue
    integro.

  - El limite de 5.000 caracteres al CREAR o EDITAR un comentario: se
    mantiene.

  - La numeracion y el prefijo de los tickets (INC-/SOL-/GAR_), el filtro
    estructural de incidencias del dashboard, el modal de KPIs y la
    "Lista de Incidencias Recientes" (invariantes de los lotes V2.002 a
    V2.005): intactos.

  - requirements.txt: no se anade ninguna dependencia. El cambio es de
    plantillas, JavaScript y tres lineas de consulta.

  - El codigo del worker y del beat: no tienen ninguna funcion que pinte el
    modal de detalle ni el KPI. No hay cambio funcional en ellos.

  - La documentacion historica (README de los lotes V1.001 a V2.005): se
    dejan intactos como registro historico.

  - Los ficheros de entrada 'user_input_files/*.csv': son datos de origen.

  - El CDN de Tailwind y de SortableJS (app/templates/base.html): NO se
    toca en este lote. Es un riesgo real de resiliencia (si el CDN falla, la
    UI pierde los estilos y el Kanban pierde el arrastre), pero resolverlo
    exige compilar Tailwind o vendorizar Sortable, es decir, anadir
    dependencias, y requirements.txt esta fijado. Queda documentado como
    recomendacion.

  - La funcion es_tipo_no_incidencia() de app/core/codigo_ticket.py: se
    mantiene (es parte de la API publica del modulo); lo que se corrige es
    el docstring, que decia que el filtro del dashboard la usaba cuando la
    usa el filtro es la constante NOMBRES_TIPOS_NO_INCIDENCIA.

  - El codigo roto que produce los ~70 avisos de linter y los 4 avisos de
    Pydantic v2 (class-based config): limpieza posterior, sin impacto en el
    funcionamiento.

================================================================================
4. REQUERIMIENTOS DE DESPLIEGUE (indica si requiere cambiar Worker)
================================================================================

  - Variables de entorno: NINGUNA nueva. No se toca ningun secreto.
  - Migraciones: NINGUNA. No hay cambios de esquema ni de datos.
  - Dependencias: NINGUNA. requirements.txt intacto.
  - CSS, JS externo, CDN: NINGUNO.
  - Cache: no hay que invalidar nada (el HTML se genera en cada peticion y
    el JS se sirve como estatico versionado por el navegador).

  Servicio 'web':    SI hay que desplegarlo. Es quien sirve el modal de
                     detalle, el lightbox y el KPI.
  Servicio 'worker': NO requiere cambio funcional. Ninguna tarea en cola
                     pinta el modal ni calcula el KPI.
                     OPERATIVAMENTE, se despliega con el MISMO commit para
                     no dejar los tres servicios desalineados.
  Servicio 'beat':   IGUAL que 'worker': sin cambio funcional, pero se
                     despliega con el mismo commit por alineacion.

  NOTA SOBRE autoDeploy: 'web' tiene autoDeploy sobre 'main' (cada push lo
  redespliega). 'worker' y 'beat' NO lo tienen: hay que desplegarlos a mano.

  NOTA SOBRE EL SECUENCIADOR GIT: la limpieza de .git/sequencer es LOCAL y
  no afecta al despliegue (no hay ningun commit asociado).

================================================================================
5. PROCEDIMIENTO DE PRUEBA RECOMENDADO
================================================================================

  5.1 COMPROBACION POR API (solo lectura, la mas objetiva)

    a) Autenticarse:
         POST /api/v1/auth/login  {"username":"...","password":"..."} -> 200

    b) El 500 que se ha corregido:
         GET /api/v1/tickets/6/comentarios
         -> DEBE devolver 200 (antes: 500 "Internal Server Error", 5 de 5).
         El comentario id=10 (17.607 caracteres) debe venir COMPLETO.

    c) El modal con la imagen de un comentario (si ya existe alguno):
         GET /api/v1/tickets/{id}/detalle-html?tab=comentarios
         -> dentro del bloque del comentario debe aparecer
              <img src="/api/v1/adjuntos/{id}/descargar" ... data-preview-image
                   data-preview-title="...">
         -> la pestana "Adjuntos" NO debe listar ese adjunto.

    d) El KPI:
         GET /api/v1/metricas/dashboard-completo
         -> incidencias.backlog_7d debe seguir valiendo 5 (el valor real de
            produccion antes y despues del cambio).

    e) Resto de endpoints clave (todos deben devolver 200):
         GET /api/v1/tickets
         GET /api/v1/metricas/cuenta-resultado?ambiente=QA
         GET /api/v1/metricas/incidencias-recientes?tipo=todos&periodo_dias=365
         GET /api/v1/metricas/incidencias-recientes?tipo=incidencia&periodo_dias=365
         GET /dashboard

  5.2 COMPROBACION VISUAL (requiere crear un comentario con imagen)

    En produccion no hay ningun comentario con imagen adjunta (verificado
    en el barrido de los 933 tickets), asi que hay que crear uno para
    comprobar la funcionalidad. ES LA UNICA COMPROBACION QUE REQUIERE
    ESCRITURA, y la hace el propietario de forma controlada:

    a) Abrir un ticket propio, ir a la pestana "Comentarios" y escribir un
       comentario.
    b) Adjuntar una imagen (PNG o JPG) al comentario. El archivo debe
       aparecer como miniatura DENTRO del comentario, con el icono de
       "cursor-zoom-in".
    c) Hacer clic en la miniatura: debe abrirse la vista previa a pantalla
       completa, con el nombre del archivo arriba y el boton de descarga.
       Cerrarla con "Esc" o con el boton de cerrar.
    d) Comprobar que la descarga sigue funcionando: al pulsar el NOMBRE del
       archivo (no la miniatura) se descarga el archivo.
    e) Abrir el MISMO ticket desde otra vista (Kanban, dashboard, Gantt,
       calendario, command palette) y repetir los pasos b) y c): la vista
       previa debe funcionar igual en todas.
    f) Comprobar la pestana "Adjuntos": debe listar SOLO los archivos del
       ticket, no el que se acaba de adjuntar al comentario.
    g) Recargar la pagina y abrir de nuevo el ticket: la miniatura del
       comentario debe seguir ahi (antes de este lote desaparecia al
       reabrir el ticket).

  5.3 COMPROBACION DE LA SEGURIDAD (fuga de comentarios internos)

    a) Con un usuario solicitante, abrir un ticket que tenga un comentario
       interno: el texto interno NO debe aparecer ni en el modal, ni en el
       listado JSON (GET /api/v1/tickets/{id}/comentarios).
    b) Con un usuario agente o administrador, el comentario interno SI debe
       verse (con su etiqueta "INTERNO").

  5.4 REGRESION RAPIDA

    a) Los KPIs de la franja superior del dashboard (total, incidencias,
       % de cumplimiento de SLA y backlog) deben ser los mismos que antes
       del despliegue.
    b) La "Lista de Incidencias Recientes" y su modal de drill-down deben
       seguir cuadrando entre si (invariante del lote V2.002).
    c) El bloque de incidencias no debe sumar ningun ticket de tipo
       Solicitud, Problema o Cambio (invariante del lote V2.004).
    d) La tabla "Cuenta de Resultado" del dashboard debe seguir mostrando
       la columna DESEST (invariante del lote V2.005).
    e) El alta de un ticket con una imagen adjunta debe seguir funcionando
       (pestana "Adjuntos" del ticket, con su vista previa).

================================================================================
6. TRAZABILIDAD
================================================================================

  Requisito                                  Fichero / linea            Test
  -----------------------------------------  -------------------------  ------------------------------------------------
  La imagen del comentario abre la vista      app/templates/tickets/     test_la_imagen_del_comentario_lleva_el_atributo_de_preview
  previa                                    detalle_modal.py
  Un PDF no abre la vista previa             app/templates/tickets/     test_un_archivo_que_no_es_imagen_no_se_marca_como_preview
                                             detalle_modal.py
  Archivo no disponible: aviso, no           app/templates/tickets/     test_una_imagen_no_disponible_avisa_en_vez_de_romperse
  imagen rota                               detalle_modal.py
  La pestana "Adjuntos" solo del ticket      app/services/             test_los_adjuntos_de_un_comentario_no_aparecen_en_la_pestana_adjuntos
                                             ticket_modal_service.py
  El solicitante no ve comentarios           app/services/             test_un_solicitante_no_ve_los_comentarios_internos
  internos                                   ticket_modal_service.py
  El equipo si los ve                        app/services/             test_un_agente_si_ve_los_comentarios_internos
                                             ticket_modal_service.py
  Las dos rutas de render coinciden          app/api/v1/features.py    test_las_dos_rutas_de_render_muestran_lo_mismo
  Una sola fuente de verdad                  app/api/v1/tickets.py     test_el_ssot_del_modal_es_la_unica_fuente
                                             app/api/v1/features.py
  El lightbox reconoce la URL de adjuntos    app/static/js/             test_el_lightbox_reconoce_la_url_de_descarga_de_adjuntos
                                             image-preview.js
  No se rompe la regla por extension         app/static/js/             test_la_deteccion_por_extension_sigue_funcionando
                                             image-preview.js
  La imagen no se engancha dos veces          app/static/js/             test_el_lightbox_no_engancha_dos_veces_la_misma_imagen
                                             image-preview.js
  El lightbox se engancha en las vistas       app/static/js/            test_reinit_modal_extras_reengancha_el_lightbox
  que insertan el modal con innerHTML         htmx-events.js
  El script del lightbox se carga siempre    app/templates/base.html    test_la_plantilla_base_carga_el_lightbox
  Sintaxis JS valida (lightbox y eventos)     app/static/js/*.js        test_la_sintaxis_js_del_lightbox_es_valida
                                                                        test_la_sintaxis_js_de_htmx_events_es_valida
  La vista previa del ticket no se pierde     app/templates/tickets/     test_los_adjuntos_del_ticket_siguen_con_preview
                                             detalle_modal.py
  La pestana de comentarios sigue existiendo app/templates/tickets/     test_el_modal_sigue_ofreciendo_la_pestana_de_comentarios
                                             detalle_modal.py
  El listado de comentarios no da 500        app/schemas/features.py   test_el_listado_de_comentarios_no_falla_con_texto_largo
  Al escribir, el limite sigue en 5.000      app/schemas/features.py   test_al_crear_un_comentario_se_mantiene_el_limite_de_5000
  El KPI excluye "Produccion OK" con tilde   app/api/v1/metricas.py    test_el_kpi_de_incidencias_abiertas_excluye_produccion_ok_con_tilde
  El KPI excluye resultado DESESTIMADA        app/api/v1/metricas.py    test_el_kpi_de_incidencias_abiertas_excluye_produccion_ok_con_tilde
  El correlativo INC- no repite codigo        app/core/codigo_ticket.py (cubierto por la suite del lote V2.004)
  La anotacion de tipo es resoluble           app/api/v1/tickets.py     (cubierto por la suite del lote V2.004)

================================================================================
7. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL Y ROLLBACK
================================================================================

  7.1 PUBLICACION

    a) Publicar en las dos ramas, sin reescribir historia:

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

         GET /health   -> 200
         GET /ready    -> 200
         GET /info     -> 200
         POST /api/v1/auth/login (admin) -> 200
         GET /dashboard -> 200

    e) Verificacion funcional: los pasos 5.1 y 5.3 por API, y los pasos
       5.2 y 5.4 en navegador.

  7.2 ROLLBACK

    Commit de referencia: el anterior (354bf20), que es el arbol del lote
    V2.005.

    Rollback en git (sin reescribir historia):

         git revert <commit de V2.006>
         git push origin main
         y desplegar worker y beat con ese commit

    Rollback en Railway (desplegar el commit anterior en los tres
    servicios):

         python tmp_deploy_railway.py <commit-anterior> web
         python tmp_deploy_railway.py <commit-anterior> worker
         python tmp_deploy_railway.py <commit-anterior> beat

    Efecto del rollback: vuelven los adjuntos de comentario a no verse
    inline, se vuelven a ver los comentarios internos por la ruta del modal
    y el listado JSON de comentarios puede volver a dar 500 con el
    comentario largo del ticket 6. No se pierde ningun dato.

  7.3 OPERACION LOCAL QUE NO FORMA PARTE DEL DEPLOY

    La limpieza del secuenciador de revert (seccion 0.7) es local. Si
    alguien vuelve a dejar un "git revert --no-commit" a medias, se limpia
    con:

         git revert --quit

    NUNCA "git revert --continue" sin revisar antes la lista de commits
    del secuenciador: podria deshacer lotes ya publicados.

================================================================================
APENDICE A - DIFF COMPLETO DE ESTE LOTE
================================================================================

  El diff que sigue es el EXACTO de los ficheros de codigo modificados.
  Va TRANSLITERADO a ASCII: los caracteres acentuados del codigo original
  ('a' con tilde, 'i' con tilde, etc.) se han sustituido por su equivalente
  ASCII. ESTA TRANSLITERACION ES SOLO DOCUMENTAL: el codigo del proyecto NO
  se modifica, conserva sus caracteres originales en UTF-8.
diff --git a/app/api/v1/features.py b/app/api/v1/features.py
index 2c62a6c..9eeb326 100644
--- a/app/api/v1/features.py
+++ b/app/api/v1/features.py
@@ -24,6 +24,7 @@ from sqlalchemy.orm import Session, joinedload
 from sqlalchemy import or_, and_
 
 from app.api.v1.deps import get_current_user, require_role
+from app.services import ticket_modal_service
 from app.db.session import get_db
 from app.models.usuario import Usuario, RolUsuario
 from app.models.ticket import Ticket
@@ -68,8 +69,6 @@ def _render_detalle_modal_response(
     referencias).
     """
     from app.models.estado import Estado
-    from app.models.comentario import Comentario
-    from app.models.adjunto import Adjunto
     from app.models.checklist import Checklist
     from app.models.auditoria import Auditoria
     from app.models.usuario import Usuario
@@ -82,40 +81,14 @@ def _render_detalle_modal_response(
     ticket_id = ticket.id
     db.refresh(ticket)
     estados = db.query(Estado).order_by(Estado.orden).all()
-    # FEATURE -- Seguridad: los comentarios INTERNOS solo los ven agentes y
-    # administradores. El SOLICITANTE jamas debe verlos (ni en el modal, ni
-    # en el JSON, ni en la respuesta HTMX).
-    mostrar_internos = user.rol != RolUsuario.SOLICITANTE
-    q_com = db.query(Comentario).filter(Comentario.ticket_id == ticket_id)
-    if not mostrar_internos:
-        q_com = q_com.filter(Comentario.es_interno == False)  # noqa: E712
-    comentarios = q_com.order_by(Comentario.created_at.asc()).all()
-    # FEATURE -- Adjuntos: la pestana "Adjuntos" solo muestra los que cuelgan
-    # del TICKET (comentario_id IS NULL). Los adjuntos de comentario se
-    # renderizan inline dentro de cada comentario en la pestana "Comentarios".
-    adjuntos = (
-        db.query(Adjunto)
-        .filter(
-            Adjunto.ticket_id == ticket_id,
-            Adjunto.comentario_id.is_(None),
-        )
-        .order_by(Adjunto.created_at.desc())
-        .all()
+    # Comentarios y adjuntos: reglas compartidas con el resto de endpoints
+    # que re-renderizan el modal (SSOT en
+    # app/services/ticket_modal_service.py).
+    comentarios = ticket_modal_service.comentarios_visibles(db, ticket_id, user)
+    adjuntos = ticket_modal_service.adjuntos_del_ticket(db, ticket_id)
+    adjuntos_por_comentario = ticket_modal_service.adjuntos_por_comentario(
+        db, comentarios
     )
-    # Precarga de adjuntos POR comentario en una sola query (N+1 fix).
-    # Esto permite que la plantilla los muestre sin disparar un SELECT por
-    # cada comentario al iterar.
-    com_ids = [c.id for c in comentarios]
-    adjuntos_por_comentario: dict = {}
-    if com_ids:
-        filas = (
-            db.query(Adjunto)
-            .filter(Adjunto.comentario_id.in_(com_ids))
-            .order_by(Adjunto.created_at.asc())
-            .all()
-        )
-        for a in filas:
-            adjuntos_por_comentario.setdefault(a.comentario_id, []).append(a)
     # Mapa de referencias #ID entre comentarios del ticket (forward + inverse).
     _csvc = ComentarioService(db)
     mapa_refs_fwd = _csvc.mapa_referencias(comentarios)
diff --git a/app/api/v1/import_export.py b/app/api/v1/import_export.py
index 1015a27..f205594 100644
--- a/app/api/v1/import_export.py
+++ b/app/api/v1/import_export.py
@@ -9,9 +9,11 @@ Los formatos siguen el mismo esquema:
   id, codigo, titulo, descripcion, tipo, prioridad, estado, asignado,
   etiquetas, fecha_vencimiento_sla, sla_cumplido, creado, actualizado
 
-El importador es tolerante: crea tickets nuevos con codigo tipo
-'INC-XXX' (mismo formato que el servicio estandar) en el estado
-inicial del sistema.
+El importador es tolerante: crea tickets nuevos cuyo codigo lo genera la
+regla unica del proyecto ('app/core/codigo_ticket.py'), es decir, 'INC-XXX'
+para las incidencias, 'SOL-XXX' para Solicitud/Problema/Cambio y
+'GAR_<HU>_<NNN>' para los tickets de Resultado de Pruebas, siempre en el
+estado inicial del sistema.
 """
 import csv
 import io
diff --git a/app/api/v1/metricas.py b/app/api/v1/metricas.py
index d13c744..59b2385 100644
--- a/app/api/v1/metricas.py
+++ b/app/api/v1/metricas.py
@@ -285,16 +285,34 @@ def resumen_dashboard(
     #   - Se compara contra `estados.nombre` (NO contra `estados.categoria`,
     #     que en produccion NUNCA toma el valor 'produccion_ok'; ver
     #     commit 4bac32d para mas detalle).
-    #   - Los valores almacenados en la BD son lowercase y sin acento
-    #     ('produccion ok', 'desestimada'), por lo que `func.lower()` es
-    #     suficiente y portable entre SQLite y PostgreSQL.
+    #   - La comparacion es INSENSIBLE A ACENTOS. El nombre canonico del
+    #     estado es 'Produccion OK' (con tilde) y lo insertan asi la siembra
+    #     (app/db/init_db.py) y la migracion 4.6, pero en produccion se
+    #     guardo como 'produccion ok' (sin tilde). `func.lower()` NO quita
+    #     acentos, asi que comparar contra 'produccion ok' NUNCA excluia el
+    #     estado canonico: en una base nueva, el KPI contaba como "abiertas"
+    #     las incidencias ya desplegadas en produccion. Se normaliza el
+    #     nombre con REPLACE (portable entre SQLite y PostgreSQL).
+    #   - 'DESESTIMADA' es un valor de `resultado_pruebas`, no un estado. En
+    #     produccion existe ademas un estado heredado con ese nombre, asi que
+    #     se excluyen LAS DOS COSAS: el estado llamado 'DESESTIMADA' y los
+    #     tickets cuyo resultado de pruebas es 'DESESTIMADA'.
+    _nombre_estado_norm = func.lower(Estado.nombre)
+    for _acento, _ascii in (("a", "a"), ("e", "e"), ("i", "i"),
+                            ("o", "o"), ("u", "u"), ("n", "n")):
+        _nombre_estado_norm = func.replace(_nombre_estado_norm, _acento, _ascii)
+    _resultado_no_desestimada = or_(
+        Ticket.resultado_pruebas.is_(None),
+        func.upper(func.trim(Ticket.resultado_pruebas)) != "DESESTIMADA",
+    )
     backlog_7d = (
         db.query(func.count(Ticket.id))
         .join(Estado, Estado.id == Ticket.estado_id)
         .filter(
             _tipo_inc,
             Ticket.archivado == False,  # noqa: E712
-            func.lower(Estado.nombre).notin_(["produccion ok", "desestimada"]),
+            _nombre_estado_norm.notin_(["produccion ok", "desestimada"]),
+            _resultado_no_desestimada,
         )
         .scalar() or 0
     )
diff --git a/app/api/v1/tickets.py b/app/api/v1/tickets.py
index 8457711..8a432dc 100644
--- a/app/api/v1/tickets.py
+++ b/app/api/v1/tickets.py
@@ -19,6 +19,7 @@ from app.db.session import get_db
 from app.models.ticket import Ticket
 from app.models.usuario import Usuario
 from app.models.etiqueta import Etiqueta, ticket_etiquetas
+from app.models.etapa_proyecto import TicketEtapa
 from app.schemas.ticket import (
     TicketCreate, TicketRead, CambioEstadoRequest, CambioEstadoResponse, ErrorResponse,
 )
@@ -26,6 +27,7 @@ from app.services.ticket_service import (
     TicketService, TransicionInvalidaError, PermisoInsuficienteError,
 )
 from app.services.auditoria_service import registrar_auditoria
+from app.services import ticket_modal_service
 
 logger = logging.getLogger(__name__)
 
@@ -355,17 +357,17 @@ def detalle_html(
         return HTMLResponse("<div>Ticket no encontrado</div>", status_code=404)
 
     estados = db.query(Estado).order_by(Estado.orden).all()
-    comentarios = (
-        db.query(Comentario)
-        .filter(Comentario.ticket_id == ticket_id)
-        .order_by(Comentario.created_at.asc())
-        .all()
-    )
-    adjuntos = (
-        db.query(Adjunto)
-        .filter(Adjunto.ticket_id == ticket_id)
-        .order_by(Adjunto.created_at.desc())
-        .all()
+    # Comentarios y adjuntos: reglas compartidas con el resto de endpoints
+    # que re-renderizan el modal (SSOT en
+    # app/services/ticket_modal_service.py):
+    #   * los comentarios INTERNOS no se muestran a los solicitantes,
+    #   * la pestana "Adjuntos" solo muestra los adjuntos del TICKET,
+    #   * los adjuntos de cada comentario se precargan para poder
+    #     pintarlos inline dentro del comentario (pestana "comentarios").
+    comentarios = ticket_modal_service.comentarios_visibles(db, ticket_id, usuario)
+    adjuntos = ticket_modal_service.adjuntos_del_ticket(db, ticket_id)
+    adjuntos_por_comentario = ticket_modal_service.adjuntos_por_comentario(
+        db, comentarios
     )
     checklists = (
         db.query(Checklist)
@@ -422,6 +424,7 @@ def detalle_html(
         estados=estados,
         comentarios=comentarios,
         adjuntos=adjuntos,
+        adjuntos_por_comentario=adjuntos_por_comentario,
         checklists=checklists,
         auditorias=auditorias,
         usuario=usuario,
@@ -626,17 +629,17 @@ async def actualizar_ticket_campo(
     from app.models.etiqueta import Etiqueta
     db.refresh(ticket)
     estados = db.query(Estado).order_by(Estado.orden).all()
-    comentarios = (
-        db.query(Comentario)
-        .filter(Comentario.ticket_id == ticket_id)
-        .order_by(Comentario.created_at.asc())
-        .all()
-    )
-    adjuntos = (
-        db.query(Adjunto)
-        .filter(Adjunto.ticket_id == ticket_id)
-        .order_by(Adjunto.created_at.desc())
-        .all()
+    # Comentarios y adjuntos: reglas compartidas con el resto de endpoints
+    # que re-renderizan el modal (SSOT en
+    # app/services/ticket_modal_service.py):
+    #   * los comentarios INTERNOS no se muestran a los solicitantes,
+    #   * la pestana "Adjuntos" solo muestra los adjuntos del TICKET,
+    #   * los adjuntos de cada comentario se precargan para poder
+    #     pintarlos inline dentro del comentario (pestana "comentarios").
+    comentarios = ticket_modal_service.comentarios_visibles(db, ticket_id, usuario)
+    adjuntos = ticket_modal_service.adjuntos_del_ticket(db, ticket_id)
+    adjuntos_por_comentario = ticket_modal_service.adjuntos_por_comentario(
+        db, comentarios
     )
     checklists = (
         db.query(Checklist)
@@ -675,7 +678,7 @@ async def actualizar_ticket_campo(
     from app.templates.tickets.detalle_modal import render_detalle_modal
     html = render_detalle_modal(
         ticket=ticket, estados=estados, comentarios=comentarios,
-        adjuntos=adjuntos, checklists=checklists,
+        adjuntos=adjuntos, adjuntos_por_comentario=adjuntos_por_comentario, checklists=checklists,
         auditorias=auditorias, usuario=usuario,
         ultima_modificacion=ultima_mod,
         active_tab=active_tab,
@@ -872,17 +875,17 @@ async def guardar_ticket_campos(
     # Re-renderizar el modal completo
     db.refresh(ticket)
     estados = db.query(Estado).order_by(Estado.orden).all()
-    comentarios = (
-        db.query(Comentario)
-        .filter(Comentario.ticket_id == ticket_id)
-        .order_by(Comentario.created_at.asc())
-        .all()
-    )
-    adjuntos = (
-        db.query(Adjunto)
-        .filter(Adjunto.ticket_id == ticket_id)
-        .order_by(Adjunto.created_at.desc())
-        .all()
+    # Comentarios y adjuntos: reglas compartidas con el resto de endpoints
+    # que re-renderizan el modal (SSOT en
+    # app/services/ticket_modal_service.py):
+    #   * los comentarios INTERNOS no se muestran a los solicitantes,
+    #   * la pestana "Adjuntos" solo muestra los adjuntos del TICKET,
+    #   * los adjuntos de cada comentario se precargan para poder
+    #     pintarlos inline dentro del comentario (pestana "comentarios").
+    comentarios = ticket_modal_service.comentarios_visibles(db, ticket_id, usuario)
+    adjuntos = ticket_modal_service.adjuntos_del_ticket(db, ticket_id)
+    adjuntos_por_comentario = ticket_modal_service.adjuntos_por_comentario(
+        db, comentarios
     )
     checklists = (
         db.query(Checklist)
@@ -916,7 +919,7 @@ async def guardar_ticket_campos(
 
     html = render_detalle_modal(
         ticket=ticket, estados=estados, comentarios=comentarios,
-        adjuntos=adjuntos, checklists=checklists,
+        adjuntos=adjuntos, adjuntos_por_comentario=adjuntos_por_comentario, checklists=checklists,
         auditorias=auditorias, usuario=usuario,
         ultima_modificacion=ultima_mod,
         active_tab=active_tab,
@@ -1063,17 +1066,17 @@ async def actualizar_campo_personalizado(
     from app.models.etiqueta import Etiqueta
     db.refresh(ticket)
     estados = db.query(Estado).order_by(Estado.orden).all()
-    comentarios = (
-        db.query(Comentario)
-        .filter(Comentario.ticket_id == ticket_id)
-        .order_by(Comentario.created_at.asc())
-        .all()
-    )
-    adjuntos = (
-        db.query(Adjunto)
-        .filter(Adjunto.ticket_id == ticket_id)
-        .order_by(Adjunto.created_at.desc())
-        .all()
+    # Comentarios y adjuntos: reglas compartidas con el resto de endpoints
+    # que re-renderizan el modal (SSOT en
+    # app/services/ticket_modal_service.py):
+    #   * los comentarios INTERNOS no se muestran a los solicitantes,
+    #   * la pestana "Adjuntos" solo muestra los adjuntos del TICKET,
+    #   * los adjuntos de cada comentario se precargan para poder
+    #     pintarlos inline dentro del comentario (pestana "comentarios").
+    comentarios = ticket_modal_service.comentarios_visibles(db, ticket_id, usuario)
+    adjuntos = ticket_modal_service.adjuntos_del_ticket(db, ticket_id)
+    adjuntos_por_comentario = ticket_modal_service.adjuntos_por_comentario(
+        db, comentarios
     )
     checklists = (
         db.query(Checklist)
@@ -1106,7 +1109,7 @@ async def actualizar_campo_personalizado(
     from app.templates.tickets.detalle_modal import render_detalle_modal
     html = render_detalle_modal(
         ticket=ticket, estados=estados, comentarios=comentarios,
-        adjuntos=adjuntos, checklists=checklists,
+        adjuntos=adjuntos, adjuntos_por_comentario=adjuntos_por_comentario, checklists=checklists,
         auditorias=auditorias, usuario=usuario,
         ultima_modificacion=ultima_mod,
         active_tab=active_tab,
diff --git a/app/core/codigo_ticket.py b/app/core/codigo_ticket.py
index d29d3e4..50d7b7e 100644
--- a/app/core/codigo_ticket.py
+++ b/app/core/codigo_ticket.py
@@ -43,10 +43,11 @@ no fuese incidencia.
 Con este modulo, los cuatro caminos consumen la misma regla y el prefijo
 deja de depender del sitio por el que se crea el ticket.
 
-Ademas el modulo publica ``TIPOS_NO_INCIDENCIA`` y ``es_tipo_no_incidencia``,
-que son los que usa el filtro del dashboard para garantizar
-estructuralmente que un ticket de tipo Solicitud/Problema/Cambio (o de
-tipo Resultado de Pruebas) NUNCA aparece en el bloque de incidencias.
+Ademas el modulo publica ``NOMBRES_TIPOS_NO_INCIDENCIA`` (los valores que
+realmente se guardan en ``tickets.tipo``) y el helper ``tipos_no_incidencia()``,
+que son los que usa el filtro del dashboard para garantizar estructuralmente
+que un ticket de tipo Solicitud/Problema/Cambio (o de tipo Resultado de
+Pruebas) NUNCA aparece en el bloque de incidencias.
 """
 
 from __future__ import annotations
@@ -152,13 +153,31 @@ def es_tipo_no_incidencia(tipo) -> bool:
 # --------------------------------------------------------------------------
 
 def _generar_codigo_inc(db) -> str:
-    """``INC-NNN``: correlativo basado en el id maximo de la tabla."""
+    """``INC-NNN``: correlativo basado en el id maximo de la tabla.
+
+    Comprueba que el codigo candidato este LIBRE antes de devolverlo (igual
+    que las otras dos familias). Sin esa comprobacion, un hueco en la
+    numeracion (por ejemplo, si se libera el id maximo) producia un
+    ``INC-NNN`` ya existente y el INSERT fallaba por la restriccion UNIQUE
+    de ``tickets.codigo``, con un 500 en lugar de un error controlado.
+    """
     from sqlalchemy import func
 
     from app.models.ticket import Ticket
 
     ultimo = db.query(func.max(Ticket.id)).scalar() or 0
-    return f"{PREFIJO_INCIDENCIA}{(ultimo + 1):03d}"
+    for offset in range(MAX_INTENTOS_NUMERACION):
+        numero = ultimo + 1 + offset
+        candidato = f"{PREFIJO_INCIDENCIA}{numero:03d}"
+        existe = (
+            db.query(Ticket).filter(Ticket.codigo == candidato).first()
+        )
+        if not existe:
+            return candidato
+    raise ConflictoNumeracionError(
+        "No se pudo asignar un correlativo libre para la familia %s"
+        % PREFIJO_INCIDENCIA
+    )
 
 
 def _generar_codigo_sol(db) -> str:
diff --git a/app/schemas/features.py b/app/schemas/features.py
index c48ef9b..ffe987d 100644
--- a/app/schemas/features.py
+++ b/app/schemas/features.py
@@ -120,6 +120,13 @@ class MencionRead(BaseModel):
 
 class ComentarioRead(ComentarioBase):
     model_config = ConfigDict(from_attributes=True)
+    # La LECTURA no aplica el limite de escritura (5.000 caracteres): hay
+    # comentarios legacy en la base de datos mas largos que eso (el ticket 6
+    # tiene uno de 17.607 caracteres) y la validacion de respuesta los
+    # convertia en un HTTP 500 al serializar el listado de comentarios.
+    # El limite de 5.000 sigue vigente al ESCRIBIR (ComentarioCreate y
+    # ComentarioUpdate).
+    texto: str
     id: int
     ticket_id: int
     usuario_id: int
diff --git a/app/services/ticket_modal_service.py b/app/services/ticket_modal_service.py
new file mode 100644
index 0000000..dbc31af
--- /dev/null
+++ b/app/services/ticket_modal_service.py
@@ -0,0 +1,121 @@
+"""
+Datos del modal de detalle del ticket: comentarios y adjuntos.
+
+Este modulo es la **fuente unica de verdad** de las tres consultas que
+necesita el modal de detalle (``app/templates/tickets/detalle_modal.py``),
+para que **todos** los endpoints que lo re-renderizan muestren exactamente
+lo mismo:
+
+  * ``comentarios_visibles()``    -> comentarios del ticket, ocultando los
+                                     INTERNOS a los solicitantes;
+  * ``adjuntos_del_ticket()``     -> adjuntos que cuelgan del TICKET
+                                     (``comentario_id IS NULL``);
+  * ``adjuntos_por_comentario()`` -> adjuntos de cada comentario, en una
+                                     sola consulta (precarga, sin N+1).
+
+Por que centralizarlo
+---------------------
+El modal de detalle se renderiza desde dos rutas distintas:
+
+  * ``app/api/v1/tickets.py::detalle_html`` (la ruta normal: Kanban, lista
+    de tickets, dashboard, timeline, Gantt y calendario),
+  * ``app/api/v1/features.py::_render_detalle_modal_response`` (los
+    re-renderes que ocurren tras crear, editar o borrar un comentario).
+
+Cada una montaba sus propias consultas, y lo hacian de forma divergente:
+
+  * ``detalle_html`` NO filtraba los comentarios internos, de modo que un
+    solicitante podia leerlos (los comentarios internos son, por
+    definicion, del equipo y no del solicitante);
+  * ``detalle_html`` NO separaba los adjuntos del ticket de los adjuntos de
+    cada comentario: los adjuntos de un comentario aparecian de rebote en
+    la pestana "Adjuntos" y NO se veian dentro del comentario;
+  * ``detalle_html`` no precargaba los adjuntos por comentario, asi que la
+    miniatura de una imagen adjunta a un comentario no se renderizaba en la
+    pestana "Comentarios" (solo aparecia tras postear el comentario, y
+    desaparecia al reabrir el ticket).
+
+Con este modulo, las dos rutas consumen las mismas reglas y el modal no
+puede depender de por donde se haya abierto.
+"""
+from __future__ import annotations
+
+from typing import Any, Dict, Iterable, List
+
+
+def comentarios_visibles(db, ticket_id: int, usuario: Any) -> List[Any]:
+    """Comentarios del ticket que puede ver el usuario indicado.
+
+    Los comentarios marcados como internos (``es_interno``) son del equipo y
+    **nunca** se muestran a un solicitante, ni en el modal, ni en el JSON,
+    ni en la respuesta HTMX.
+
+    Parameters
+    ----------
+    db : Session
+        Sesion SQLAlchemy.
+    ticket_id : int
+        Ticket cuyo historial de comentarios se quiere leer.
+    usuario : Usuario
+        Usuario que abre el modal (decide si se filtran los internos).
+
+    Returns
+    -------
+    list[Comentario]
+        Comentarios visibles, del mas antiguo al mas reciente.
+    """
+    from app.models.comentario import Comentario
+    from app.models.usuario import RolUsuario
+
+    q = db.query(Comentario).filter(Comentario.ticket_id == ticket_id)
+    rol = getattr(usuario, "rol", None)
+    if rol == RolUsuario.SOLICITANTE:
+        q = q.filter(Comentario.es_interno == False)  # noqa: E712
+    return q.order_by(Comentario.created_at.asc()).all()
+
+
+def adjuntos_del_ticket(db, ticket_id: int) -> List[Any]:
+    """Adjuntos que cuelgan del TICKET (no de un comentario).
+
+    Los adjuntos de un comentario se renderizan inline dentro de su
+    comentario (pestana "Comentarios"); no deben aparecer en la pestana
+    "Adjuntos", que es la vista de los archivos del ticket.
+    """
+    from app.models.adjunto import Adjunto
+
+    return (
+        db.query(Adjunto)
+        .filter(
+            Adjunto.ticket_id == ticket_id,
+            Adjunto.comentario_id.is_(None),
+        )
+        .order_by(Adjunto.created_at.desc())
+        .all()
+    )
+
+
+def adjuntos_por_comentario(db, comentarios: Iterable[Any]) -> Dict[int, List[Any]]:
+    """Agrupa los adjuntos de cada comentario en una sola consulta.
+
+    Precarga (sin N+1): en lugar de disparar un SELECT por comentario al
+    iterar en la plantilla, se resuelve todo de una vez y se devuelve un
+    diccionario ``{comentario_id: [adjuntos]}``.
+
+    Los comentarios sin adjuntos no aparecen en el diccionario; la
+    plantilla usa ``.get(id) or []``.
+    """
+    from app.models.adjunto import Adjunto
+
+    com_ids = [c.id for c in comentarios]
+    resultado: Dict[int, List[Any]] = {}
+    if not com_ids:
+        return resultado
+    filas = (
+        db.query(Adjunto)
+        .filter(Adjunto.comentario_id.in_(com_ids))
+        .order_by(Adjunto.created_at.asc())
+        .all()
+    )
+    for adjunto in filas:
+        resultado.setdefault(adjunto.comentario_id, []).append(adjunto)
+    return resultado
diff --git a/app/static/js/htmx-events.js b/app/static/js/htmx-events.js
index ac240a2..61eacbc 100644
--- a/app/static/js/htmx-events.js
+++ b/app/static/js/htmx-events.js
@@ -1115,6 +1115,15 @@
     setupComentariosDropzone();
     setupMarkdownEditors();
     mountComentariosFeatures();
+    // Re-enganchar la vista previa de imagenes (lightbox). Es necesario
+    // porque el modal de detalle se inserta con fetch + innerHTML en varios
+    // sitios (Kanban, Gantt, calendario, command palette y dashboard): en esas
+    // vias htmx no emite htmx:afterSwap, asi que el lightbox se quedaba sin
+    // enganchar y la previsualizacion no respondia al pulsar la imagen.
+    if (window.BitacoraImagePreview &&
+        typeof window.BitacoraImagePreview.attach === 'function') {
+      try { window.BitacoraImagePreview.attach(document); } catch (_) { /* noop */ }
+    }
   }
 
   // Re-aplicar handlers cuando HTMX inserta HTML nuevo en el DOM
diff --git a/app/static/js/image-preview.js b/app/static/js/image-preview.js
index 22dab83..30d76ff 100644
--- a/app/static/js/image-preview.js
+++ b/app/static/js/image-preview.js
@@ -19,9 +19,16 @@
 
   var IMG_EXT = /\.(png|jpe?g|gif|webp|bmp|svg|avif|ico)(\?.*)?$/i;
 
+  // Las imagenes servidas por el endpoint de adjuntos NO llevan extension en la
+  // URL (/api/v1/adjuntos/{id}/descargar), asi que la deteccion por extension
+  // no las ve. Se reconocen por su forma para que cualquier vista que las
+  // pinte (pestana de comentarios, pestana de adjuntos, modales) sea
+  // previsualizable sin depender de un atributo explicito.
+  var ADJUNTOS_URL = /\/api\/v1\/adjuntos\/\d+\/descargar(\?.*)?$/i;
+
   function isImageSrc(src) {
     if (!src) return false;
-    return IMG_EXT.test(src);
+    return IMG_EXT.test(src) || ADJUNTOS_URL.test(src);
   }
 
   function buildOverlay(src, opts) {
@@ -136,6 +143,10 @@
     var implicitImages = root.querySelectorAll('#modal-root img, [data-bitacora-preview] img');
     implicitImages.forEach(function (img) {
       if (img.dataset.previewBound === '1') return;
+      // Si la imagen ya esta dentro de un ENLACE con data-preview-image, la
+      // regla explicita de arriba ya la cubre: no se engancha dos veces.
+      var contenedor = img.closest('[data-preview-image]');
+      if (contenedor && (contenedor === img || contenedor.tagName === 'A')) return;
       if (!isImageSrc(img.getAttribute('src') || '')) return;
       img.dataset.previewBound = '1';
       img.style.cursor = 'zoom-in';
diff --git a/app/templates/tickets/detalle_modal.py b/app/templates/tickets/detalle_modal.py
index 37ae0dc..c568bb6 100644
--- a/app/templates/tickets/detalle_modal.py
+++ b/app/templates/tickets/detalle_modal.py
@@ -711,13 +711,32 @@ DETALLE_TEMPLATE = _ENV.from_string(r"""
                     <div class="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">Adjuntos del comentario</div>
                     <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
                       {% for a in _com_adj %}
+                        {# Deteccion robusta de imagen y de disponibilidad (misma politica
+                           que la pestana "Adjuntos"): el adjunto puede venir con la propiedad
+                           calculada del modelo o solo con mime_type y nombre. #}
+                        {% set _com_nombre = (a.nombre_original or a.filename or a.nombre or '') %}
+                        {% set _com_mime = (a.mime_type or '') %}
+                        {% set _com_ext = _com_nombre.split('.')[-1].lower() if _com_nombre else '' %}
+                        {% set _com_es_imagen = a.es_imagen if a.es_imagen is defined else (_com_mime.startswith('image/') or _com_ext in ['png','jpg','jpeg','gif','webp','bmp','svg','avif']) %}
+                        {% set _com_disponible = (a.disponible if a.disponible is defined else None) %}
                         <a href="/api/v1/adjuntos/{{ a.id }}/descargar"
                            target="_blank" rel="noopener"
                            class="flex items-center gap-2 p-1.5 rounded border border-slate-200 bg-white hover:bg-slate-50">
-                          {% if a.es_imagen %}
-                            <img src="/api/v1/adjuntos/{{ a.id }}/descargar" alt="{{ a.nombre_original }}"
-                                 class="w-10 h-10 object-cover rounded border border-slate-200"
+                          {% if _com_es_imagen and _com_disponible is not sameas false %}
+                            {# data-preview-image activa el lightbox de app/static/js/image-preview.js.
+                               El atributo va en la IMAGEN: al pulsarla se abre la vista previa;
+                               el resto del enlace (nombre, tamano) sigue descargando el archivo. #}
+                            <img src="/api/v1/adjuntos/{{ a.id }}/descargar" alt="{{ _com_nombre }}"
+                                 data-preview-image
+                                 data-preview-title="{{ _com_nombre }}"
+                                 title="Click para vista previa"
+                                 class="w-10 h-10 object-cover rounded border border-slate-200 cursor-zoom-in"
                                  loading="lazy">
+                          {% elif _com_es_imagen %}
+                            <span class="inline-flex items-center justify-center w-10 h-10 rounded border border-amber-200 bg-amber-50 text-amber-500"
+                                  title="Archivo no disponible">
+                              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M4.93 19h14.14c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.2 16c-.77 1.33.19 3 1.73 3z"></path></svg>
+                            </span>
                           {% else %}
                             <span class="inline-flex items-center justify-center w-10 h-10 rounded bg-slate-100 text-slate-500 text-[10px]">[clip]</span>
                           {% endif %}
diff --git a/tests/test_v2006_preview_imagen_comentarios.py b/tests/test_v2006_preview_imagen_comentarios.py
new file mode 100644
index 0000000..5a076bd
--- /dev/null
+++ b/tests/test_v2006_preview_imagen_comentarios.py
@@ -0,0 +1,710 @@
+"""
+Regresiones de V2.006: previsualizacion de las imagenes de la pestana de
+COMENTARIOS del detalle del ticket, y unificacion de las dos rutas que
+renderizan ese modal.
+
+Contexto del defecto
+--------------------
+El proyecto tiene un lightbox de previsualizacion de imagenes
+(``app/static/js/image-preview.js``). Se activa de dos formas:
+
+  1. de forma EXPLICITA, con el atributo ``data-preview-image``;
+  2. de forma IMPLICITA, con cualquier ``<img>`` dentro de ``#modal-root``
+     cuyo ``src`` termine en extension de imagen (.png/.jpg/...).
+
+La pestana "Adjuntos" del modal usaba la forma explicita y funcionaba. La
+pestana "Comentarios", en cambio, renderiza sus adjuntos inline SIN ese
+atributo y con un ``src`` que es la URL del endpoint de descarga::
+
+    <img src="/api/v1/adjuntos/{{ a.id }}/descargar" ...>
+
+Esa URL **no termina en extension**, asi que la regla implicita tampoco la
+detectaba. Al pulsar la imagen de un comentario no se abria ninguna vista
+previa.
+
+Ademas, el modal de detalle se renderiza desde DOS rutas distintas:
+
+  * ``app/api/v1/tickets.py::detalle_html`` (la ruta normal: Kanban, lista de
+    tickets, dashboard, timeline, Gantt y calendario) y los otros tres
+    endpoints de ``tickets.py`` que re-renderizan el modal;
+  * ``app/api/v1/features.py::_render_detalle_modal_response`` (los
+    re-renderes tras crear, editar o borrar un comentario).
+
+Cada una montaba sus propias consultas y lo hacian de forma divergente:
+
+  * la ruta de ``tickets.py`` NO precargaba los adjuntos por comentario, asi
+    que la miniatura de una imagen adjunta a un comentario **no se
+    renderizaba** en la pestana "Comentarios" (solo aparecia de rebote en
+    la pestana "Adjuntos" y despues de postear el comentario);
+  * la ruta de ``tickets.py`` NO separaba los adjuntos del ticket de los de
+    los comentarios, de modo que los adjuntos de un comentario aparecian de
+    rebote en la pestana "Adjuntos";
+  * la ruta de ``tickets.py`` NO filtraba los comentarios INTERNOS, de modo
+    que un SOLICITANTE podia leerlos (los internos son del equipo, nunca
+    del solicitante).
+
+Causa raiz: no existia una fuente unica de verdad para los datos del modal.
+Este lote la crea (``app/services/ticket_modal_service.py``) y conecta las
+dos rutas.
+
+Que fija esta suite
+-------------------
+  * que la imagen de un comentario se renderice con el atributo que activa
+    el lightbox (y con su titulo),
+  * que un archivo que NO es imagen no se marque como previsualizable,
+  * que una imagen cuyo archivo fisico ya no existe no se pinte como
+    imagen rota sino con el aviso de "Archivo no disponible",
+  * que los adjuntos de un comentario NO aparezcan en la pestana "Adjuntos",
+  * que un solicitante NO vea los comentarios internos,
+  * que las dos rutas de render produzcan lo mismo,
+  * que el lightbox reconozca la URL del endpoint de adjuntos, de modo que
+    la previsualizacion no dependa de un atributo explicito,
+  * que la sintaxis JavaScript del lightbox siga siendo valida.
+
+Todos los tests operan sobre la base SQLite temporal de la suite (ver
+``tests/conftest.py``): nunca leen ni escriben en la base de datos de
+produccion.
+"""
+from __future__ import annotations
+
+import importlib.util
+import re
+from pathlib import Path
+
+import pytest
+from fastapi.testclient import TestClient
+
+RAIZ = Path(__file__).resolve().parent.parent
+JS_LIGHTBOX = RAIZ / "app" / "static" / "js" / "image-preview.js"
+JS_EVENTOS = RAIZ / "app" / "static" / "js" / "htmx-events.js"
+PLANTILLA_BASE = RAIZ / "app" / "templates" / "base.html"
+PLANTILLA_MODAL = RAIZ / "app" / "templates" / "tickets" / "detalle_modal.py"
+SRC_TICKETS = RAIZ / "app" / "api" / "v1" / "tickets.py"
+SRC_FEATURES = RAIZ / "app" / "api" / "v1" / "features.py"
+
+CLAVE = "Clave-local-de-regresion-2026"
+
+#: PNG minimo valido (1x1 transparente). Sirve como contenido de respaldo.
+PNG_MINIMO = (
+    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
+    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
+    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
+)
+
+
+# ---------------------------------------------------------------------------
+# Utilidades compartidas
+# ---------------------------------------------------------------------------
+@pytest.fixture(scope="module")
+def app_and_schema():
+    """Prepara el esquema en la SQLite temporal de la suite."""
+    from app.db.base import Base
+    from app.db.session import engine
+    from app.main import app
+
+    Base.metadata.create_all(bind=engine)
+    return app, engine
+
+
+@pytest.fixture(scope="module")
+def local_client(app_and_schema):
+    """Cliente HTTP local con sesion; no abre conexiones de red."""
+    app, _engine = app_and_schema
+    with TestClient(app) as client:
+        yield client
+
+
+@pytest.fixture
+def db_session(app_and_schema):
+    """Sesion SQLAlchemy sobre la SQLite temporal de la suite."""
+    from app.db.session import SessionLocal
+
+    session = SessionLocal()
+    try:
+        yield session
+    finally:
+        session.close()
+
+
+def _usuario(db_session, username, rol):
+    from app.core.security import hash_password
+    from app.models.usuario import Usuario
+
+    usuario = db_session.query(Usuario).filter(Usuario.username == username).first()
+    if usuario is None:
+        usuario = Usuario(
+            username=username,
+            email="%s@example.test" % username,
+            nombre_completo=username,
+            hashed_password=hash_password(CLAVE),
+            rol=rol,
+            is_active=True,
+        )
+        db_session.add(usuario)
+        db_session.commit()
+        db_session.refresh(usuario)
+    return usuario
+
+
+@pytest.fixture
+def admin_con_sesion(local_client, db_session):
+    """Administrador autenticado en el cliente HTTP local."""
+    from app.models.usuario import RolUsuario
+
+    usuario = _usuario(db_session, "v2006_admin_preview", RolUsuario.ADMINISTRADOR)
+    login = local_client.post(
+        "/api/v1/auth/login",
+        json={"username": usuario.username, "password": CLAVE},
+    )
+    assert login.status_code == 200, login.text
+    return usuario
+
+
+@pytest.fixture
+def solicitante_con_sesion(local_client, db_session):
+    """Solicitante autenticado en el cliente HTTP local."""
+    from app.models.usuario import RolUsuario
+
+    usuario = _usuario(db_session, "v2006_solicitante", RolUsuario.SOLICITANTE)
+    login = local_client.post(
+        "/api/v1/auth/login",
+        json={"username": usuario.username, "password": CLAVE},
+    )
+    assert login.status_code == 200, login.text
+    return usuario
+
+
+def _crear_ticket_con_comentario(db_session, usuario, codigo, texto="Comentario con imagen adjunta",
+                                 es_interno=False):
+    """Crea ticket + estado + comentario y devuelve (ticket, comentario)."""
+    from app.models.comentario import Comentario
+    from app.models.estado import Estado
+    from app.models.ticket import Prioridad, Ticket, TipoIncidencia
+
+    estado = db_session.query(Estado).filter(Estado.nombre == "En desarrollo").first()
+    if estado is None:
+        estado = Estado(nombre="En desarrollo", color="#3b82f6", orden=1)
+        db_session.add(estado)
+        db_session.commit()
+        db_session.refresh(estado)
+
+    ticket = Ticket(
+        codigo=codigo,
+        titulo="Ticket de regresion V2.006",
+        descripcion="Creado por la suite de regresion de V2.006.",
+        tipo=TipoIncidencia.INCIDENCIA,
+        prioridad=Prioridad.MEDIA,
+        estado_id=estado.id,
+        creador_id=usuario.id,
+        asignado_id=usuario.id,
+        archivado=False,
+    )
+    db_session.add(ticket)
+    db_session.commit()
+    db_session.refresh(ticket)
+
+    comentario = Comentario(
+        ticket_id=ticket.id,
+        usuario_id=usuario.id,
+        texto=texto,
+        es_interno=es_interno,
+        editado=False,
+    )
+    db_session.add(comentario)
+    db_session.commit()
+    db_session.refresh(comentario)
+    return ticket, comentario
+
+
+def _crear_adjunto(db_session, usuario, ticket, comentario, nombre, mime_type,
+                   contenido=PNG_MINIMO, ruta_falsa=False):
+    """Crea un adjunto (con o sin copia fisica) y devuelve su id."""
+    from app.models.adjunto import Adjunto
+
+    adjunto = Adjunto(
+        ticket_id=ticket.id,
+        comentario_id=comentario.id,
+        usuario_id=usuario.id,
+        nombre_original=nombre,
+        nombre_storage="v2006_%d_%s" % (comentario.id, nombre),
+        ruta=("ruta/inexistente/%s" % nombre) if ruta_falsa else ("v2006/%s" % nombre),
+        mime_type=mime_type,
+        tamano_bytes=len(contenido) if contenido else 0,
+        contenido=contenido,
+    )
+    db_session.add(adjunto)
+    db_session.commit()
+    db_session.refresh(adjunto)
+    return adjunto.id
+
+
+def _html_modal(local_client, ticket_id, tab="comentarios"):
+    """Devuelve el HTML del modal de detalle en la pestana indicada."""
+    r = local_client.get("/api/v1/tickets/%d/detalle-html" % ticket_id,
+                         params={"tab": tab})
+    assert r.status_code == 200, r.text
+    return r.text
+
+
+def _regex_del_js(nombre_variable):
+    """Extrae del JS del lightbox una expresion regular literal.
+
+    Devuelve el objeto ``re`` de Python equivalente (los delimitadores ``/``
+    de JavaScript y los escapes ``\\/`` se traducen).
+    """
+    fuente = JS_LIGHTBOX.read_text(encoding="utf-8")
+    m = re.search(
+        r"var\s+%s\s*=\s*/(.*?)/([a-z]*)\s*;" % re.escape(nombre_variable),
+        fuente, re.S,
+    )
+    assert m, "no se encontro la expresion %s en image-preview.js" % nombre_variable
+    patron = m.group(1).replace("\\/", "/")
+    flags = re.IGNORECASE if "i" in m.group(2) else 0
+    return re.compile(patron, flags)
+
+
+def _cargar_validador_js():
+    """Carga el validador de sintaxis JS del lote V2.003 (mismo lexico)."""
+    ruta = RAIZ / "tests" / "test_v2003_sintaxis_js_plantillas.py"
+    spec = importlib.util.spec_from_file_location("validador_v2003", ruta)
+    modulo = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(modulo)
+    return modulo
+
+
+# ---------------------------------------------------------------------------
+# 1. El markup de los adjuntos del comentario
+# ---------------------------------------------------------------------------
+def test_la_imagen_del_comentario_lleva_el_atributo_de_preview(
+    local_client, db_session, admin_con_sesion
+):
+    """La imagen del comentario se marca para el lightbox."""
+    ticket, comentario = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-IMG-001")
+    adjunto_id = _crear_adjunto(
+        db_session, admin_con_sesion, ticket, comentario, "captura.png", "image/png")
+
+    html = _html_modal(local_client, ticket.id)
+
+    assert "data-preview-image" in html
+    assert 'data-preview-title="captura.png"' in html
+    # La miniatura apunta al endpoint de descarga y esta marcada.
+    assert re.search(
+        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"[^>]*data-preview-image' % adjunto_id,
+        html, re.S,
+    ), "la imagen del comentario no lleva el atributo de vista previa"
+    # El resto del enlace sigue siendo la descarga del archivo.
+    assert 'href="/api/v1/adjuntos/%d/descargar"' % adjunto_id in html
+
+
+def test_un_archivo_que_no_es_imagen_no_se_marca_como_preview(
+    local_client, db_session, admin_con_sesion
+):
+    """Un PDF no debe abrir el lightbox."""
+    ticket, comentario = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-PDF-001")
+    adjunto_id = _crear_adjunto(
+        db_session, admin_con_sesion, ticket, comentario,
+        "evidencia.pdf", "application/pdf", contenido=b"%PDF-1.4\n%%EOF\n")
+
+    html = _html_modal(local_client, ticket.id)
+
+    assert not re.search(
+        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"' % adjunto_id, html, re.S
+    ), "un archivo que no es imagen se pinto como <img>"
+    # El enlace de descarga sigue presente.
+    assert 'href="/api/v1/adjuntos/%d/descargar"' % adjunto_id in html
+
+
+def test_una_imagen_no_disponible_avisa_en_vez_de_romperse(
+    local_client, db_session, admin_con_sesion
+):
+    """Si el archivo fisico no existe, se avisa (igual que en "Adjuntos")."""
+    ticket, comentario = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-NODISP-001")
+    adjunto_id = _crear_adjunto(
+        db_session, admin_con_sesion, ticket, comentario, "purgada.png",
+        "image/png", contenido=None, ruta_falsa=True)
+
+    html = _html_modal(local_client, ticket.id)
+
+    assert not re.search(
+        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"' % adjunto_id, html, re.S
+    ), "se pinto una imagen cuyo archivo no esta disponible"
+    assert "Archivo no disponible" in html
+
+
+def _panel(html, nombre):
+    """Devuelve solo el HTML de una pestana del modal.
+
+    El modal renderiza TODAS las pestanas en el mismo documento (las
+    inactivas se ocultan con CSS), asi que para afirmar sobre una pestana
+    hay que recortar su seccion.
+    """
+    m = re.search(r'data-panel="%s"' % re.escape(nombre), html)
+    assert m, "no se encontro la pestana %r en el modal" % nombre
+    ini = m.start()
+    m2 = re.search(r'data-panel="', html[ini + 20:])
+    fin = ini + 20 + m2.start() if m2 else len(html)
+    return html[ini:fin]
+
+
+def test_los_adjuntos_de_un_comentario_no_aparecen_en_la_pestana_adjuntos(
+    local_client, db_session, admin_con_sesion
+):
+    """La pestana "Adjuntos" es la de los archivos del TICKET."""
+    ticket, comentario = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-SEPAR-001")
+    adjunto_id = _crear_adjunto(
+        db_session, admin_con_sesion, ticket, comentario, "solo-comentario.png",
+        "image/png")
+
+    html = _html_modal(local_client, ticket.id, tab="adjuntos")
+
+    # En la pestana "Adjuntos" no debe salir el archivo del comentario...
+    assert not re.search(
+        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"' % adjunto_id,
+        _panel(html, "adjuntos"), re.S
+    ), "un adjunto de comentario aparecio en la pestana de adjuntos del ticket"
+    # ...pero si debe verse inline dentro del comentario.
+    assert re.search(
+        r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"[^>]*data-preview-image' % adjunto_id,
+        _panel(html, "comentarios"), re.S
+    ), "el adjunto del comentario no se pinto dentro del comentario"
+
+
+# ---------------------------------------------------------------------------
+# 2. Seguridad: los comentarios internos no se muestran a los solicitantes
+# ---------------------------------------------------------------------------
+def test_un_solicitante_no_ve_los_comentarios_internos(
+    local_client, db_session, admin_con_sesion, solicitante_con_sesion
+):
+    """Los comentarios INTERNOS son del equipo, no del solicitante."""
+    ticket, _com_publico = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-INT-001",
+        texto="Comentario visible para todos", es_interno=False)
+    from app.models.comentario import Comentario
+
+    interno = Comentario(
+        ticket_id=ticket.id,
+        usuario_id=admin_con_sesion.id,
+        texto="NOTA INTERNA que el solicitante no debe leer",
+        es_interno=True,
+        editado=False,
+    )
+    db_session.add(interno)
+    db_session.commit()
+
+    html = _html_modal(local_client, ticket.id)
+
+    assert "Comentario visible para todos" in html
+    assert "NOTA INTERNA que el solicitante no debe leer" not in html, (
+        "un solicitante pudo leer un comentario interno")
+
+
+def test_un_agente_si_ve_los_comentarios_internos(
+    local_client, db_session, admin_con_sesion
+):
+    """El equipo (administrador) si ve los comentarios internos."""
+    ticket, _com = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-INT-002",
+        texto="NOTA INTERNA del equipo", es_interno=True)
+
+    html = _html_modal(local_client, ticket.id)
+
+    assert "NOTA INTERNA del equipo" in html
+
+
+# ---------------------------------------------------------------------------
+# 3. Las dos rutas de render deben coincidir
+# ---------------------------------------------------------------------------
+def test_las_dos_rutas_de_render_muestran_lo_mismo(
+    local_client, db_session, admin_con_sesion
+):
+    """La ruta de features.py y la de tickets.py pintan lo mismo."""
+    from app.api.v1.features import _render_detalle_modal_response
+
+    ticket, comentario = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-DOSRUTAS-001")
+    adjunto_id = _crear_adjunto(
+        db_session, admin_con_sesion, ticket, comentario, "captura.png", "image/png")
+
+    html_tickets = _html_modal(local_client, ticket.id)
+
+    db_session.refresh(ticket)
+    respuesta = _render_detalle_modal_response(
+        db_session, ticket, admin_con_sesion, active_tab="comentarios")
+    html_features = (
+        respuesta.body.decode("utf-8") if hasattr(respuesta, "body") else str(respuesta)
+    )
+
+    for html, nombre in ((html_tickets, "tickets.py"), (html_features, "features.py")):
+        assert re.search(
+            r'<img[^>]*src="/api/v1/adjuntos/%d/descargar"[^>]*data-preview-image' % adjunto_id,
+            html, re.S,
+        ), "la ruta %s no pinto la imagen del comentario con vista previa" % nombre
+
+
+def test_el_ssot_del_modal_es_la_unica_fuente():
+    """Las dos rutas de render consumen el helper compartido.
+
+    Si alguien reintroduce consultas propias de comentarios/adjuntos, este
+    test avisa: el modal volveria a depender de por donde se abre.
+    """
+    tickets = SRC_TICKETS.read_text(encoding="utf-8")
+    features = SRC_FEATURES.read_text(encoding="utf-8")
+
+    for nombre, fuente in (("tickets.py", tickets), ("features.py", features)):
+        assert "ticket_modal_service.comentarios_visibles" in fuente, (
+            "%s no usa el SSOT de comentarios" % nombre)
+        assert "ticket_modal_service.adjuntos_del_ticket" in fuente, (
+            "%s no usa el SSOT de adjuntos del ticket" % nombre)
+        assert "ticket_modal_service.adjuntos_por_comentario" in fuente, (
+            "%s no precarga los adjuntos por comentario" % nombre)
+        # Dentro del render del modal no debe quedar ninguna consulta propia
+        # de comentarios (fuera de ese render si puede haber consultas
+        # legitimas, por ejemplo al editar un comentario).
+        cuerpo = _cuerpo_render(features, "_render_detalle_modal_response") \
+            if nombre == "features.py" else ""
+        if cuerpo:
+            assert "db.query(Comentario)" not in cuerpo, (
+                "%s vuelve a consultar los comentarios por su cuenta" % nombre)
+
+
+def _cuerpo_render(fuente, nombre_funcion):
+    """Devuelve el codigo de una funcion de primer nivel del fichero."""
+    i = fuente.find("def %s(" % nombre_funcion)
+    if i < 0:
+        return ""
+    j = fuente.find("\ndef ", i + 1)
+    return fuente[i:j] if j > 0 else fuente[i:]
+
+
+# ---------------------------------------------------------------------------
+# 4. El lightbox
+# ---------------------------------------------------------------------------
+def test_el_lightbox_reconoce_la_url_de_descarga_de_adjuntos():
+    """La URL del endpoint de adjuntos se tiene que reconocer como imagen."""
+    regex = _regex_del_js("ADJUNTOS_URL")
+
+    assert regex.search("/api/v1/adjuntos/12/descargar")
+    assert regex.search("/api/v1/adjuntos/12/descargar?filename=captura.png")
+    # Y no debe capturar otras URLs.
+    assert not regex.search("/api/v1/tickets/12/detalle-html")
+    assert not regex.search("/api/v1/adjuntos/12/eliminar")
+
+
+def test_la_deteccion_por_extension_sigue_funcionando():
+    """No se rompe la regla por extension que ya usaba el proyecto."""
+    regex = _regex_del_js("IMG_EXT")
+
+    for url in ("/static/img/logo.png", "/x/foto.JPG", "/x/gif.gif?v=2",
+                "/x/vector.svg", "/x/animacion.webp"):
+        assert regex.search(url), "deberia detectar la imagen %s" % url
+    assert not regex.search("/api/v1/adjuntos/12/descargar")
+    assert not regex.search("/x/documento.pdf")
+
+
+def test_el_lightbox_no_engancha_dos_veces_la_misma_imagen():
+    """La imagen dentro de un ENLACE con data-preview-image se cubre una vez."""
+    fuente = JS_LIGHTBOX.read_text(encoding="utf-8")
+
+    assert "closest('[data-preview-image]')" in fuente
+    assert "contenedor.tagName === 'A'" in fuente
+
+
+def test_reinit_modal_extras_reengancha_el_lightbox():
+    """Las vias que insertan el modal con innerHTML deben re-engancharlo.
+
+    Sin esta llamada, en Kanban, Gantt, calendario, command palette y
+    dashboard el modal se inserta con fetch + innerHTML, htmx no emite
+    htmx:afterSwap y la vista previa se queda sin enganchar.
+    """
+    fuente = JS_EVENTOS.read_text(encoding="utf-8")
+
+    assert "BitacoraImagePreview" in fuente
+    assert "BitacoraImagePreview.attach" in fuente
+
+
+def test_la_plantilla_base_carga_el_lightbox():
+    """El script del lightbox tiene que seguir cargado en todas las paginas."""
+    html = PLANTILLA_BASE.read_text(encoding="utf-8")
+
+    assert "/static/js/image-preview.js" in html
+
+
+def test_la_sintaxis_js_del_lightbox_es_valida():
+    """El fichero JS del lightbox no puede tener errores de sintaxis.
+
+    Se reutiliza el lexico del lote V2.003 (mismo validador, sin dependencias).
+    """
+    validador = _cargar_validador_js()
+    codigo = JS_LIGHTBOX.read_text(encoding="utf-8")
+
+    problemas = validador.valida_js("image-preview.js", codigo)
+
+    assert not problemas, "errores de sintaxis JS: %s" % problemas
+
+
+def test_la_sintaxis_js_de_htmx_events_es_valida():
+    """El fichero que engancha el lightbox tampoco puede tener errores JS."""
+    validador = _cargar_validador_js()
+    codigo = JS_EVENTOS.read_text(encoding="utf-8")
+
+    problemas = validador.valida_js("htmx-events.js", codigo)
+
+    assert not problemas, "errores de sintaxis JS: %s" % problemas
+
+
+# ---------------------------------------------------------------------------
+# 5. No se rompe lo que ya funcionaba
+# ---------------------------------------------------------------------------
+def test_los_adjuntos_del_ticket_siguen_con_preview():
+    """La pestana "Adjuntos" del ticket conserva su vista previa."""
+    fuente = PLANTILLA_MODAL.read_text(encoding="utf-8")
+
+    # El bloque de la pestana "Adjuntos" sigue marcando la imagen.
+    assert fuente.count("data-preview-image") >= 2, (
+        "se perdio el atributo de vista previa en la pestana de adjuntos")
+
+
+def test_el_modal_sigue_ofreciendo_la_pestana_de_comentarios():
+    """La pestana existe y sigue mostrando el numero de comentarios."""
+    fuente = PLANTILLA_MODAL.read_text(encoding="utf-8")
+
+    assert 'data-tab="comentarios"' in fuente
+    assert 'data-panel="comentarios"' in fuente
+
+
+# ---------------------------------------------------------------------------
+# 6. Regresion del 500 en el listado JSON de comentarios
+# ---------------------------------------------------------------------------
+def test_el_listado_de_comentarios_no_falla_con_texto_largo(
+    local_client, db_session, admin_con_sesion
+):
+    """Un comentario legacy mas largo de 5.000 caracteres no debe dar 500.
+
+    En produccion, GET /api/v1/tickets/6/comentarios devolvia HTTP 500 de
+    forma determinista: el comentario id=10 del ticket 6 tiene 17.607
+    caracteres y el esquema de RESPUESTA (ComentarioRead) heredia el
+    ``max_length=5000`` del esquema de escritura, de modo que Pydantic
+    fallaba al serializar la respuesta (ResponseValidationError -> 500).
+    El limite de 5.000 sigue vigente al escribir; solo se relaja al LEER.
+    """
+    from app.models.comentario import Comentario
+
+    ticket, _com = _crear_ticket_con_comentario(
+        db_session, admin_con_sesion, "V2006-TEXTO-LARGO-001")
+    largo = Comentario(
+        ticket_id=ticket.id,
+        usuario_id=admin_con_sesion.id,
+        texto="X" * 17607,
+        es_interno=False,
+        editado=False,
+    )
+    db_session.add(largo)
+    db_session.commit()
+
+    r = local_client.get("/api/v1/tickets/%d/comentarios" % ticket.id)
+
+    assert r.status_code == 200, (
+        "el listado de comentarios devolvio %s: %s" % (r.status_code, r.text[:300]))
+    cuerpo = r.json()
+    textos = [c.get("texto", "") for c in cuerpo]
+    assert any(len(t) == 17607 for t in textos), (
+        "el comentario largo no se devolvio completo")
+
+
+def test_al_crear_un_comentario_se_mantiene_el_limite_de_5000(local_client):
+    """La validacion de ESCRITURA no se relaja: 5.000 caracteres es el tope."""
+    r = local_client.post(
+        "/api/v1/tickets/1/comentarios",
+        json={"texto": "X" * 5001},
+    )
+    assert r.status_code in (400, 404, 422), (
+        "la escritura acepto un comentario de mas de 5.000 caracteres: %s"
+        % r.status_code)
+
+
+# ---------------------------------------------------------------------------
+# 7. Regresion del KPI "Incidencias Abiertas" (comparacion con acentos)
+# ---------------------------------------------------------------------------
+def test_el_kpi_de_incidencias_abiertas_excluye_produccion_ok_con_tilde(
+    local_client, db_session, admin_con_sesion
+):
+    """El KPI no puede contar como "abiertas" las incidencias ya desplegadas.
+
+    El nombre canonico del estado es 'Produccion OK' (con tilde): lo insertan
+    asi la siembra (app/db/init_db.py) y la migracion 4.6. Comparar con
+    ``lower(nombre) NOT IN ('produccion ok')`` NO lo excluia nunca, porque
+    ``lower()`` no quita acentos: en una base nueva el KPI contaba como
+    abiertas las 702 incidencias ya desplegadas.
+    """
+    from app.models.estado import Estado
+    from app.models.ticket import Prioridad, Ticket, TipoIncidencia
+
+    # Nombre CANONICO del estado, con tilde ('Produccion OK' con 'o' acentuada).
+    # Se escribe con escape unicode para que este fichero siga siendo ASCII,
+    # pero el valor es exactamente el que insertan la siembra y la
+    # migracion 4.6.
+    NOMBRE_PRODUCCION_OK = "Producci\u00f3n OK"
+
+    estado_produccion = db_session.query(Estado).filter(
+        Estado.nombre == NOMBRE_PRODUCCION_OK).first()
+    if estado_produccion is None:
+        estado_produccion = Estado(
+            nombre=NOMBRE_PRODUCCION_OK, color="#0d9488", orden=99,
+            es_inicial=False, es_final=True, categoria="produccion_ok",
+        )
+        db_session.add(estado_produccion)
+        db_session.commit()
+        db_session.refresh(estado_produccion)
+
+    estado_abierto = db_session.query(Estado).filter(
+        Estado.nombre == "BackLog").first()
+    if estado_abierto is None:
+        estado_abierto = Estado(
+            nombre="BackLog", color="#f59e0b", orden=98,
+            es_inicial=True, es_final=False, categoria="abierto",
+        )
+        db_session.add(estado_abierto)
+        db_session.commit()
+        db_session.refresh(estado_abierto)
+
+    def _incidencia(codigo, estado_id, resultado=None):
+        t = Ticket(
+            codigo=codigo,
+            titulo="KPI V2.006",
+            descripcion="d",
+            tipo=TipoIncidencia.INCIDENCIA,
+            prioridad=Prioridad.MEDIA,
+            estado_id=estado_id,
+            creador_id=admin_con_sesion.id,
+            asignado_id=admin_con_sesion.id,
+            archivado=False,
+            resultado_pruebas=resultado,
+        )
+        db_session.add(t)
+        db_session.commit()
+        return t
+
+    def _backlog():
+        r = local_client.get("/api/v1/metricas/dashboard-completo")
+        assert r.status_code == 200, r.text
+        return r.json()["incidencias"]["backlog_7d"]
+
+    # Se mide el DELTA: la base de la suite la comparten otros tests de este
+    # modulo, asi que el valor absoluto no es estable.
+    antes = _backlog()
+
+    _incidencia("V2006-KPI-PROD", estado_produccion.id)
+    _incidencia("V2006-KPI-ABIERTA", estado_abierto.id)
+    _incidencia("V2006-KPI-DESEST", estado_abierto.id, resultado="DESESTIMADA")
+
+    despues = _backlog()
+
+    # El ticket en 'Produccion OK' NO cuenta, y el DESESTIMADA tampoco:
+    # de los tres tickets creados, solo uno sigue siendo una incidencia
+    # abierta.
+    assert despues == antes + 1, (
+        "el KPI cambio de %s a %s (se esperaba +1)" % (antes, despues))
================================================================================
9. ESTADO FINAL DEL DESPLIEGUE (2026-10-29)
================================================================================

  9.1 PUBLICACION

    Commit del lote:  9c2ae23211bbe9af31b2825bf77528ecad196a83
    Commit padre:     354bf20 (addendum 9 del lote V2.005)
    Rama de trabajo:  release/v2.001 (rama canonica)
    'main' alineada:  merge --ff-only (354bf20..9c2ae23), sin reescribir
                      historia y sin '--force'.
    Push (PUSH_EXIT=0):
        354bf20..9c2ae23  main            -> main
        354bf20..9c2ae23  release/v2.001  -> release/v2.001

    Nota: el 'working tree' quedo LIMPIO tras el commit y el arbol de Git no
    tiene ningun secuenciador pendiente (se limpio el secuenciador de revert
    huerfano, ver seccion 0.7).

  9.2 DESPLIEGUE EN RAILWAY

    web    -> autoDeploy desde 'main'   SUCCESS  2026-10-29T17:28:48.580Z
              id 65ff5424-8f7f-409b-9bda-ffabd9477e82
    worker -> serviceInstanceDeploy      SUCCESS  2026-10-29T17:29:08.150Z
              id 7aa66485-e7bd-43e0-86e6-c07499d9f25b
    beat   -> serviceInstanceDeploy      SUCCESS  2026-10-29T17:29:12.385Z
              id af5889c7-5a8a-40d8-bd8d-f64d6ae2cc78

    Los tres servicios declaran en su 'meta':
        commitHash   = 9c2ae23211bbe9af31b2825bf77528ecad196a83
        branch       = main


  9.3 PRUEBAS

    Suite nueva V2.006:                  20 passed
    Suites de regresion V2.002..V2.006:   60 passed
    Suite completa:                      215 passed (195 + 20), 0 failed
                                         766,35 s
    Dientes de la suite nueva (revirtiendo cada arreglo):
        sin data-preview-image ....... 3 failed
        sin relaxation del esquema ... 1 failed
        sin normalizacion de acentos . 1 failed
        sin exclusion DESESTIMADA ..... 1 failed
        restaurado ................... 20 passed

  9.4 VERIFICACION EN PRODUCCION (solo GET y POST de login)

    Salud y acceso:
      GET  /health -> 200  {"status":"ok","database":"ok","redis":"ok"}
      GET  /ready  -> 200
      GET  /info   -> 200
      POST /api/v1/auth/login (administrador) -> 200

    El 500 corregido:
      GET /api/v1/tickets/6/comentarios -> 200 (124.100 bytes)   [OK]
      Antes: HTTP 500 "Internal Server Error", 5 de 5 intentos.
      Ahora: 8 comentarios, con las longitudes de texto
              [26876, 26482, 24678, 24674, 17607, ...]           [OK]
      El comentario heredado de 17.607 caracteres se devuelve COMPLETO.
      (Hay otros tres comentarios aun mas largos: por eso la validacion de
      lectura tambien era el unico motivo del 500.)

    KPI del dashboard (SIN CAMBIOS respecto a antes del despliegue):
      totales      = {"total":933,"activos":932,"archivados":1}   [OK]
      incidencias  = {"total":17,"activas":17,"nuevas_7d":2,
                      "backlog_7d":5}                            [OK]
      sla          = {"cumplidos":889,"incumplidos":40,
                      "pendientes":4,"porcentaje_cumplimiento":95.7}  [OK]

    Modal de detalle:
      GET /api/v1/tickets/12/detalle-html?tab=comentarios -> 200
      (135.407 bytes), con la pestana de comentarios presente   [OK]
      Bloques 'Adjuntos del comentario': 0 (en produccion no hay ningun
      comentario con adjunto: el barrido de los 933 tickets lo confirma).

    Estaticos desplegados:
      GET /static/js/image-preview.js -> 200, incluye ADJUNTOS_URL y el
      guarda de no enganchar dos veces la misma imagen            [OK]
      GET /static/js/htmx-events.js  -> 200, incluye el enganche de
      BitacoraImagePreview.attach en reinitModalExtras()           [OK]

    Resto de endpoints clave (todos 200):
      /api/v1/tickets                                              [OK]
      /api/v1/metricas/cuenta-resultado?ambiente=QA                [OK]
      /api/v1/metricas/incidencias-recientes?tipo=todos&...365     [OK]
      /api/v1/metricas/incidencias-recientes?tipo=incidencia&..365  [OK]
      /dashboard                                                   [OK]

    RESULTADO DE LA VERIFICACION: TODAS LAS COMPROBACIONES OK
    (script de verificacion: 21 comprobaciones automaticas, 0 fallos).


  9.5 RESUMEN OPERATIVO

    Los tres servicios quedaron desplegados y alineados en el mismo commit
    (9c2ae23) y el 'working tree' local quedo limpio, sin secuenciador de
    Git pendiente.

    Con este lote, el detalle del ticket se comporta igual en todas las
    vistas por las que se abre: la imagen de un comentario se ve dentro del
    comentario y se abre en la vista previa al pulsarla, la pestana
    "Adjuntos" solo lista los archivos del ticket, el solicitante no ve
    los comentarios internos, el listado JSON de comentarios ya no puede
    devolver 500 y el KPI "Incidencias Abiertas" excluye los estados
    terminales con o sin tilde.

    PENDIENTE PARA EL PROPIETARIO (requiere escribir en produccion, por eso
    no se ha hecho desde aqui): en produccion NO existe ningun comentario
    con imagen adjunta, de modo que el caso reportado no se puede
    comprobar con los datos actuales. Hay que adjuntar una imagen a un
    comentario propio y pulsar la miniatura (procedimiento 5.2 del README).
    El resto de la verificacion se hizo por API y esta toda en verde.

    PENDIENTES DEL PROPIETARIO QUE SIGUEN ABIERTOS (ningun lote los cierra):
    rotar la clave del administrador y el token de proyecto de Railway,
    auditar el cambio de contrasena del 2026-10-26, activar autoDeploy en
    worker/beat, SECRET_KEY real y volumen en /data, rotar la contrasena de
    PostgreSQL, cerrar el registro publico de usuarios y borrar los tmp_*.
    Ademas queda como recomendacion autoalojar Tailwind y SortableJS, que
    hoy dependen del CDN (ver seccion 3 de este README).

