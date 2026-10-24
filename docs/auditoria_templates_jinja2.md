# Auditoría exhaustiva de plantillas Jinja2 y enlaces — `/workspace/app/templates/`

**Proyecto:** FastAPI + Jinja2 + HTMX + TailwindCSS + SortableJS
**Fecha de la auditoría:** 2026-10-24
**Autor:** MiniMax Agent
**Naturaleza:** SOLO LECTURA. Ningún archivo del proyecto fue modificado.

---

## Resumen ejecutivo

Se auditaron exhaustivamente las **31 plantillas HTML** y los **4 módulos Python** que conviven dentro de `/workspace/app/templates/`, contrastándolos contra las **242 rutas FastAPI** realmente registradas en `main.py` y `api/v1/*.py`. El resultado es Dual: la salud de los enlaces es excelente, pero existen defectos de Duplicación y un fallo Bloqueante.

La conclusión principal es que **no hay ni un solo enlace roto**: los 79 `href` internos apuntan a rutas existentes, los 35 endpoints HTMX (`hx-get`/`hx-post`/`hx-patch`) resuelven contra el router, los 4 `{% include %}` existen, los 3 filtros Jinja están registrados y 30 de 31 plantillas compilan sin error de sintaxis.

Sin embargo, se identificó **1 fallo P0** que provoca un HTTP 500: en `admin/reporte_entregas.html:508` el token `{% endif}` carece del `%` de cierre, produciendo `unexpected '}'` al compilar. Le siguen **2 hallazgos P1** de lógica duplicada y divergente: la tarjeta Kanban existe en tres implementaciones mutantes (`tarjeta.html`, `tarjeta.py`, `card.py`), y el dashboard mantiene una función `renderCuentaResultado()` muerta que conserva un mapa de colores **divergente** del vigente.

El hallazgo con mayor valor funcional para el usuario es de alcance P3: **`resultado_pruebas` no se renderiza en ninguna tarjeta Kanban**, pese a ser una columna real de la tabla `Ticket` y el eje de columnas de la «Cuenta de Resultado».

**Conteo por severidad: P0 = 1 · P1 = 2 · P2 = 5 · P3 = 4 · Total = 12.**

---

## 1. Alcance y metodología

### 1.1 Objetivo

Verificar la integridad estructural de la capa de presentación: que toda variable Jinja resuelva, que todo enlace y endpoint HTMX apunte a una ruta real, que no haya plantillas huérfanas ni código muerto, y localizar con precisión las zonas de código que el usuario señaló (tarjeta Kanban, «Cuenta de Resultado», `resultado_pruebas`, colores).

### 1.2 Método

La auditoría se ejecutó con un corpus de **31 plantillas HTML + 7 archivos JS estáticos** y se contrastó contra el código Python del servidor. Las técnicas empleadas fueron:

- **Extracción de rutas por AST de Python.** Se parseó `main.py` y los 22 módulos de `api/v1/*.py` con `ast.parse`, resolviendo decoradores `@app.get/post/...` y `@router.get/post/...`, y expandiendo el prefijo `/api/v1` que inyecta `app.include_router(api_router, prefix="/api/v1")` (`main.py:154`). Resultado: **242 rutas** como verdad de referencia.
- **Análisis Jinja2 por AST.** `Environment().parse()` + `meta.find_undeclared_variables()` para cruzar variables usadas contra el contexto provisto por cada vista.
- **Resolución de alcance de Jinja.** Las variables definidas por `{% set %}`, los objetivos de `{% for %}` y las heredadas por `{% include %}` se clasificaron por separado para no reportar como "indefinidas" lo que Jinja resuelve en tiempo de render.
- **Compilación real de cada plantilla.** Se parsearon las 31 plantillas con `jinja2.Environment()` para detectar `TemplateSyntaxError` con número de línea.
- **Detección de JS muerto en 3 iteraciones.** La v1 sólo buscaba en bloques `<script>` (37 falsos positivos); la v2 buscaba en el HTML completo pero exigía llamada `fn(` (7 candidatos, falsos positivos por referencias como callback); la v3 —definitiva— cuenta la aparición cruda del identificador en todo el corpus (HTML completo + JS estático) y descarta la línea de declaración.

### 1.3 Notas de método que evitan errores de lectura

Dos artefactos de presentación amenazaban la exactitud del informe y fueron resueltos a nivel de bytes:

1. **`Read` y `cat -A` muestran `{% endif %}>` donde los bytes son `{% endif}>`.** Un visor que "normaliza" el token hace creer que la plantilla está bien formada. La verificación autoritativa es el volcado de codepoints: `... 0x7b 0x25 0x65 0x6e 0x64 0x69 0x66 0x7d 0x3e` = `{` `%` `e` `n` `d` `i` `f` `}` `>`. **Falta el `%` final.** La tabla de abajo refleja los bytes reales.
2. **`grep "CUENTA_RESULTADO_COLORS"` devuelve 0 resultados** aunque exista un mapa de colours en ese punto. El identificador real es **`CUENTA_RESULTADO_COLORES`** (con "E" final), definido en `dashboard/index.html:1292`. No hay bug de variable indefinida.

Todos los scripts de auditoría residen en `/workspace/tmp/audit/`, **fuera del proyecto**. No se creó ni modificó ningún archivo bajo `/workspace/app/`.

---

## 2. Inventario de plantillas

### 2.1 Plantillas HTML (31)

| Plantilla | Líneas | Tipo | Extiende | Notas |
|---|---:|---|---|---|
| `base.html` | 431 | Layout raíz | — | Contenedor de bloques, sidebar, `usuario` global |
| `admin/deadline.html` | 214 | Página | `base.html` | |
| `admin/reporte_entregas.html` | 760 | Página | `base.html` | **FALLA AL COMPILAR (P0)** |
| `auth/login.html` | 55 | Página | `base.html` | htmx |
| `auth/registro.html` | 82 | Página | `base.html` | htmx |
| `auth/cambiar_password_modal.html` | 96 | Fragmento HTMX | — | Servido como lectura cruda de archivo |
| `butler/index.html` | 682 | Página | `base.html` | |
| `catalogos/index.html` | 58 | Página | `base.html` | |
| `dashboard/index.html` | 1921 | Página | `base.html` | **Contiene la «Cuenta de Resultado»** |
| `espacios/index.html` | 188 | Página | `base.html` | |
| `importar_exportar/index.html` | 184 | Página | `base.html` | htmx |
| `kanban/index.html` | 542 | Página | `base.html` | `include` de `kanban/partials/tarjeta.html` |
| `kanban/partials/tarjeta.html` | 112 | **Fragmento HTMX (tarjeta)** | — | **Tarjeta Kanban arrastrable** |
| `notificaciones/index.html` | 109 | Página | `base.html` | |
| `roles_funciones/index.html` | 199 | Página | `base.html` | |
| `tableros/index.html` | 244 | Página | `base.html` | |
| `tableros/publico.html` | 65 | Página | `base.html` | Público; no recibe `usuario` |
| `tickets/list.html` | 206 | Página | `base.html` | htmx |
| `tickets/nuevo_modal.html` | 468 | Fragmento HTMX | — | Formulario de alta |
| `usuarios/admin_reset_password_modal.html` | 84 | Fragmento HTMX | — | Servido por `.replace()` manual |
| `usuarios/credenciales_modal.html` | 244 | Fragmento | — | |
| `usuarios/form.html` | 124 | Fragmento HTMX | — | |
| `usuarios/index.html` | 93 | Página | `base.html` | htmx |
| `usuarios/tabla.html` | 104 | Fragmento HTMX | — | |
| `vistas/_planner_sections.html` | 90 | Fragmento (prefijo `_`) | — | Cuerpo HTMX del planner |
| `vistas/calendario.html` | 392 | Página | `base.html` | htmx |
| `vistas/gantt.html` | 1444 | Página | `base.html` | htmx |
| `vistas/panel.html` | 132 | Página | `base.html` | htmx |
| `vistas/planner.html` | 316 | Página | `base.html` | `include` de `vistas/_planner_sections.html` |
| `vistas/tabla.html` | 142 | Página | `base.html` | htmx |
| `vistas/timeline.html` | 257 | Página | `base.html` | htmx |

**Distribución:** 23 páginas completas, 8 fragmentos/partials. Sólo un `{% include %}` anida (dentro de `base.html` y de las dos páginas del planner) y tres plantillas son incluidos por el servidor como fragmentos de respuesta HTMX.

### 2.2 Módulos Python dentro de `templates/` (4) — **hallazgo arquitectónico**

| Módulo | Tamaño | Función pública | Importado desde |
|---|---:|---|---|
| `kanban/partials/card.py` | 4 162 B | `render_tarjeta(ticket)` | `api/v1/tickets.py:253` |
| `kanban/partials/column.py` | 1 527 B | `render_columna(...)` | `api/v1/kanban.py:78` |
| `kanban/partials/tarjeta.py` | 6 366 B | `render_tarjeta_completa(ticket)` | `api/v1/tickets.py:80,521` |
| `tickets/detalle_modal.py` | 111 383 B | `render_detalle_modal(...)` | `api/v1/tickets.py:419,675,741,1106`; `api/v1/features.py:80` |

Los cuatro están **vivos** (ninguno es código muerto) y son legibles porque `app/templates/` es un *namespace package* implícito (PEP 420) sin `__init__.py`. No es un error, pero mezcla dos capas: motor de render y presentación en el mismo directorio, lo que contribuyó a la divergencia descrita en el hallazgo P1-2.

---

## 3. Resumen de hallazgos por severidad

| Severidad | Cantidad | Naturaleza |
|---|---:|---|
| **P0 — Bloqueante** | 1 | Error de sintaxis Jinja → HTTP 500 |
| **P1 — Alto** | 2 | Lógica duplicada y divergente que produce UI inconsistente |
| **P2 — Medio** | 5 | Código muerto, acoplamiento frágil, inconsistencia de color |
| **P3 — Bajo / Informativo** | 4 | Ausencia de funcionalidad esperada, variables inexistentes |
| **Total** | **12** | |

### 3.1 Tabla de hallazgos

| Severidad | Plantilla:línea | Hallazgo | Corrección sugerida |
|---|---|---|---|
| **P0** | `admin/reporte_entregas.html:508` | Token `{% endif}` sin `%` de cierre → `TemplateSyntaxError: unexpected '}'`. La página `/admin/reporte-entregas` (`main.py:2191`) devuelve **HTTP 500**. Única plantilla de 31 que no compila. | Sustituir `{% endif}>` por `{% endif %}>`. Una sola línea. |
| **P1** | `dashboard/index.html:887-947` vs `:1292-1300` | Dos implementaciones paralelas de «Cuenta de Resultado». `renderCuentaResultado()` (L887) está **muerta** y usa un mapa de color **divergente** (`RESULTADO_COLORS`, L895) del vigente (`CUENTA_RESULTADO_COLORES`, L1292). Paletas distintas para `OK`, `NOK`, `POSTERGADA` y `DESESTIMADA`. | Eliminar L886-947 y conservar `cargarCuentaResultado()` (L1305) + `CUENTA_RESULTADO_COLORES` (L1292) como única fuente de verdad. |
| **P1** | `kanban/partials/tarjeta.html` (112 L) · `kanban/partials/tarjeta.py` (114 L) · `kanban/partials/card.py` (79 L) | **Triplicación de la tarjeta Kanban** con estilos divergentes: la insignia SLA es *dot+texto* en `.html`/`.py` pero *pastilla* en `card.py`; `tarjeta.py` carece de `data-tipo` y del bloque «Listo en Prod»; `card.py` usa 1 inicial en vez de 2. | Convertir `tarjeta.html` en el único partial y hacer que `tarjeta.py`/`card.py` lo rendericen vía `templates.get_template(...)`, o extraer un macro Jinja compartido. |
| **P2** | `static/js/kanban.js:25-39` | `getTransicionInfo()` **muerta**: única aparición en todo el proyecto. Duplica en cliente una consulta que el servidor ya expone en `api/v1/tickets.py:273` y que el modal ya consume vía HTMX (`tickets/detalle_modal.py:611`). | Eliminar la función y su caché `transicionCache`, o conectar el flujo de drag & drop a la ruta existente. |
| **P2** | `static/js/kanban.js:42-...` | `pedirComentario()` **muerta**: única aparición en todo el proyecto. El modal de comentario obligatorio nunca se invoca desde el drag & drop. | Eliminar, o integrarla en `handleDrop()` (L151) que hoy llama `patchEstado()` sin validar `requiere_comentario`. |
| **P2** | `usuarios/admin_reset_password_modal.html:20,41` + `api/v1/usuarios.py:733-809` | El modal se renderiza **fuera de Jinja**: `open(...).read()` + `.replace("{{ usuario.id }}", …)`. Frágil ante cualquier `{{ }}` nuevo. | Renderizar con `Jinja2Templates` y `context={"usuario": target}`. |
| **P2** | `auth/cambiar_password_modal.html` + `api/v1/auth.py:483-508` | Lectura cruda del archivo sin interpolación. Hoy es correcto (la plantilla no contiene `{{ }}`), pero rompe el contrato de plantillas. | Renderizar vía `Jinja2Templates` para normalizar el pipeline. |
| **P2** | `tarjeta.html:23` · `tarjeta.py:43` · `card.py:29` · `tickets/list.html:115` vs `vistas/tabla.html:90` · `vistas/timeline.html:113` · `tableros/publico.html:43` vs `dashboard/index.html:819` vs `main.py:1778` | **Inconsistencia de color para prioridad `media`**: `yellow` en Kanban y lista, `amber` en vistas y tableros, `#eab308` en el dashboard, `#f59e0b` en `main.py`. `critica` y `alta` sí coinciden en tono (rojo/naranja). | Unificar en una única constante compartida (p. ej. en `app/core/jinja_filters.py` o un `partials/_constantes.html`) y reutilizarla en los 8 sitios. |
| **P3** | `kanban/partials/tarjeta.html:77-109` | **`resultado_pruebas` no se renderiza en ninguna tarjeta Kanban.** Es una columna real de `Ticket` (usada en `api/v1/metricas.py:402`) y el eje de columnas de la «Cuenta de Resultado», pero la tarjeta no lo muestra. | Añadir una insignia de color en el footer (L89-107) usando `CUENTA_RESULTADO_COLORES[resultado]`, si es el comportamiento esperado. |
| **P3** | `tickets/nuevo_modal.html:62,192-193` · `kanban/index.html:104` | `resultado_pruebas` aparece como **valor de `<select>`/filtro**, no como dato renderizado. Es un campo de formulario, no un campo mostrado en la tarjeta. | Documentar que es un filtro de captura, no un dato de la tarjeta; o incluirlo como badge si la ficha de alta lo persiste. |
| **P3** | `roles_funciones/index.html` | La variable `conteo` aparece sólo **2 veces como texto**; no es una variable Jinja. `dashboard` y `tarjetas` **tampoco** son variables Jinja en ningún lugar del proyecto. `categoria` tiene **0 ocurrencias** en todo el repositorio. | Si se esperaba un contador `conteo` o una taxonomía `categoria`, hay que crearlos: hoy no existen. |
| **P3** | `app/templates/**/*.py` (4 módulos) | Módulos Python conviviendo con plantillas en el mismo directorio, renderizan HTML con Jinja embebido en cadenas. Contribuye a la divergencia P1. | Mover a `app/services/render/` o `app/partials/` y dejar `templates/` sólo con `.html`. |

---

## 4. Análisis en profundidad

### 4.1 El fallo P0: por qué `{% endif}>` rompe la página

El error está en `admin/reporte_entregas.html:508`, dentro del `switch` de "Entrega / No entrega". La secuencia de codepoints de esa línea es:

```
'                       {% if e.es_entrega %}checked{% endif}>'
['0x7b','0x25','0x69','0x66','0x65','0x2e','0x65','0x73','0x5f','0x65','0x6e',
 '0x74','0x72','0x65','0x67','0x61','0x25','0x7d','0x63','0x68','0x65','0x63',
 '0x6b','0x65','0x64','0x7b','0x25','0x65','0x6e','0x64','0x69','0x66','0x7d','0x3e']
```

El primer bloque `{% if e.es_entrega %}` cierra correctamente (`0x25, 0x7d` = `%}`). El segundo abre en `0x7b, 0x25` = `{%` pero cierra en `0x66, 0x7d` = `f}` — **falta el `0x25` (`%`) final**. Jinja abre un bloque `{%` que nunca se cierra, consume el `}` como texto inesperado y aborta el parseo.

El impacto es total para esa vista: la plantilla no se compila, y `GET /admin/reporte-entregas` (`main.py:2191`, que la renderiza en L2238) devuelve **HTTP 500**. La corrección es de un carácter.

> **Advertencia metodológica:** el token defectuoso se ve como `{% endif %}>` en cualquier visor que inserte un espacio al formatear. La evidencia fiable es el hexdump, no la lectura visual.

### 4.2 La divergencia de la «Cuenta de Resultado»

El dashboard implementa dos veces la misma tabla pivote. La versión **muerta** (`renderCuentaResultado`, L887-947) pinta con `RESULTADO_COLORS`, un mapa plano de seis colores; la versión **viva** (`cargarCuentaResultado`, L1305-1435) usa `CUENTA_RESULTADO_COLORES`, un mapa enriquecido con tres canales (`bg`, `text`, `cellText`) y siete entradas —incluida `"(en blanco)"`, que corresponde a los `NULL` que el SQL agrupa en `api/v1/metricas.py:636`.

La divergencia no es cosmética. Comparando entrada por entrada:

| Resultado | Color muerto (`RESULTADO_COLORS`, L895) | Color vivo (`CUENTA_RESULTADO_COLORES`, L1292) | ¿Coinciden? |
|---|---|---|---|
| `OK` | `#10b981` (emerald-500) | `#16a34a` (green-600) | **No** |
| `OK CON OBS.` | `#22c55e` (green-500) | `#eab308` (amber-500) | **No** |
| `NOK` | `#ef4444` (red-500) | `#dc2626` (red-600) | **No** |
| `POSTERGADA` | `#eab308` (amber-500) | `#ea580c` (orange-600) | **No** |
| `DESESTIMADA` | `#a855f7` (purple-500) | `#7c3aed` (violet-600) | **No** |
| `N/A` | `#94a3b8` (slate-400) | `#94a3b8` (slate-400) | Sí |
| `(en blanco)` | *no existe* | `#cbd5e1` (slate-300) | **No** |

Sólo `N/A` coincide. La consecuencia práctica es que **cualquiera que intente deducir la paleta "de la Cuenta de Resultado" leyendo `renderCuentaResultado()` implementará los colores equivocados**. La función está muerta — su identificador aparece **una sola vez en todo el proyecto** (su propia declaración) — así que hoy no rompe nada, pero es una trampa de mantenimiento: es el bloque más "documentado" de los dos (tiene los nombres autoexplicativos `RESULTADOS`, `RESULTADO_COLORS`) y por tanto el más probable que se lea por error.

Nótese además que el comentario en L215-218 y el bloque `{# … #}` de L848-855 explican la arquitectura con precisión: *"El contenedor `#cuenta-resultado-container` es propiedad exclusiva del loader dedicado `cargarCuentaResultado()`"*. La propia plantilla documenta que la otra ruta está obsoleta; simplemente nadie eliminó el código.

### 4.3 La triplicación de la tarjeta Kanban

El mismo componente visual —una tarjeta de ticket en una columna del tablero— existe en tres lugares con tres comportamientos distintos:

| Aspecto | `tarjeta.html` | `tarjeta.py` | `card.py` |
|---|---|---|---|
| Insignia SLA | Punto + texto (`bg-red-500` + `text-red-600`) | **Pastilla** (`bg-red-50 text-red-700 border border-red-200`) | Punto + texto |
| Insignia `data-tipo` | Sí (`ticket.tipo.value`) | **No** | **No** |
| Bloque «Listo en Prod» | Sí (L54-76) | **No** | **No** |
| Avatar del asignado | 2 iniciales (`ini`, L80) | 2 iniciales (`ini`, L67) | **1 inicial** (`nombre_completo[:1]`) |
| Etiquetas | Hasta 3 + contador `+N` | No | No |
| `title` del SLA | `"SLA vencido"` | `"SLA vencido: la fecha límite ya pasó"` | `"SLA vencido"` |

Esto significa que **el mismo ticket se ve distinto según por qué ruta se sirva**: la carga inicial del tablero (`kanban/index.html:218` → `tarjeta.html`) muestra un badge de "Listo en Prod" y dos iniciales; la respuesta HTMX tras un drag & drop (`card.py`) muestra un badge de SLA con otro estilo y una sola inicial; y el render de servidor (`tarjeta.py`) no muestra ni el tipo ni el bloque de producción. La divergencia del SLA es especialmente perceptible porque el usuario lo lee como "vencido" en un sitio y como una pastilla roja en otro.

Ninguna de las tres renderiza `resultado_pruebas`, lo que suma una cuarta divergencia: la tarjeta nunca muestra el resultado de pruebas.

### 4.4 Las funciones JS muertas: qué significan en el flujo de negocio

Las dos funciones muertas de `static/js/kanban.js` no son residuo inocuo; describen un flujo de drag & drop que **nunca se completó**.

`getTransicionInfo()` (L25-39) consulta `/api/v1/tickets/{id}/transicion-info/{estado}` con una caché en `transicionCache` y devuelve `{valida, motivo, requiere_comentario}`. Esa ruta **existe** (`api/v1/tickets.py:273`) y ya se consume desde el modal de detalle vía HTMX (`tickets/detalle_modal.py:611`). El cliente implementa, con una segunda caché y una segunda llamada HTTP, algo que el servidor ya resuelve — y no lo usa.

`pedirComentario()` (L42) construye el modal flotante de "Comentario obligatorio" con su `<textarea>`, sus botones y su `onSubmit`/`onCancel`. El flujo previsto era: al soltar una tarjeta, consultar si la transición exige comentario y, si es así, pedirlo. Lo que ocurre hoy es que `handleDrop()` (L151) llama directamente a `patchEstado(ticketId, estadoId, orden, comentario)` (L129) con `comentario` vacío.

La consecuencia es una **regla de negocio no aplicada en el Kanban**: si el servidor exige un comentario para la transición y el cliente no lo envía, la petición se rechaza y el contador no se actualiza — pero sin el modal explicativo que el código muerto sugiere que debería existir. En el modal de detalle la validación sí ocurre; en el tablero no. Esto es exactamente el tipo de divergencia que un usuario perceives como "a veces el tablero no me deja mover la tarjeta".

### 4.5 La capa de color: un mapa disperso

La prioridad se codifica **8 veces con 4 paletas distintas** y, en el caso de `media`, con **4 tonos distintos**:

| Ubicación | `critica` | `alta` | `media` | `baja` |
|---|---|---|---|---|
| `kanban/partials/tarjeta.html:21-24` | `bg-red-100 text-red-700` | `bg-orange-100 text-orange-700` | **`bg-yellow-100 text-yellow-700`** | `bg-slate-100 text-slate-600` |
| `kanban/partials/tarjeta.py:41-44` | `bg-red-100 text-red-700` | `bg-orange-100 text-orange-700` | **`bg-yellow-100 text-yellow-700`** | `bg-slate-100 text-slate-600` |
| `kanban/partials/card.py:29` | idem | idem | **`bg-yellow-100 text-yellow-700`** | idem |
| `tickets/list.html:115` | idem | idem | **`bg-yellow-100 text-yellow-700`** | idem |
| `vistas/tabla.html:90` | idem | idem | **`bg-amber-100 text-amber-700`** | idem |
| `vistas/timeline.html:113` | idem | idem | **`bg-amber-100 text-amber-700`** | idem |
| `tableros/publico.html:43` | idem | idem | **`bg-amber-100 text-amber-700`** | idem |
| `dashboard/index.html:819` | `#dc2626` | `#ea580c` | **`#eab308`** | `#64748b` |
| `main.py:1778` | `#ef4444` | `#f97316` | **`#f59e0b`** | `#94a3b8` |

`critica` y `alta` concuerdan en tono familiesco (rojo / naranja) en las 9 ubicaciones; `media` no: **amarillo** en Kanban y lista de tickets, **ámbar** en las vistas y tableros, y dos hex distintos (`#eab308` ≈ amber-500, `#f59e0b` ≈ amber-500 en otra convención) en dashboard y servidor. En Tailwind, `yellow` y `amber` son tonos visualmente distintos (amber es más anaranjado), de modo que un ticket de prioridad media cambia de color según la pantalla en la que se mire.

### 4.6 Variables solicitadas expresamente por el usuario

El brief nombró seis identificadores. La búsqueda fue exhaustiva sobre las 31 plantillas, todo el HTML (no sólo bloques `<script>`) y el código Python:

| Identificador | ¿Es variable Jinja? | Detalle |
|---|---|---|
| `resultado_pruebas` | **No** | 0 usos como variable. Es (a) el nombre de la **columna SQL de la tabla `Ticket`** (`api/v1/metricas.py:402`), (b) una **constante de tipo** en `api/v1/metricas.py:49`, y (c) texto en el dashboard (L217, L280, L1348, L1362) y en los `<select>` de `tickets/nuevo_modal.html` y `kanban/index.html:104`. |
| `dashboard` | **No** | 0 usos como variable. La ruta de la página es `/dashboard`; no existe una variable `dashboard`. |
| `tarjetas` | **No** | 0 usos como variable. El concepto existe (`ticket`), no el plural. |
| `ticket` | **Sí** | Únicamente en `kanban/partials/tarjeta.html` (L12, L57, L91). Se hereda del `{% include %}` de `kanban/index.html:218`. |
| `categoria` | **No** | **0 ocurrencias en todo el repositorio.** |
| `conteo` | **No** | 2 apariciones como **texto** en `roles_funciones/index.html`. No es variable. |

La conclusión relevante es que `resultado_pruebas` es un **dato de base de datos con un juego de valores rico** (OK, OK CON OBS., NOK, POSTERGADA, DESESTIMADA, N/A, más NULL→"(en blanco)"), modelado en `api/v1/metricas.py:83` como LOV completo. La aplicación ya lo consume y lo pivota en el dashboard; lo que **no** hace es exhibirlo en el tablero.

---

## 5. Localización específica solicitada (tarea 8)

### 5.1 La tarjeta Kanban y su zona inferior

**Ruta de la plantilla:** `/workspace/app/templates/kanban/partials/tarjeta.html` (112 líneas)
**Se incluye desde:** `kanban/index.html:218`
**Se arrastra con:** SortableJS, inicializado en `static/js/kanban.js` (`handleDrop`, L151)

#### 5.1.1 Insignia de prioridad — `tarjeta.html:20-26`

```jinja
20|      <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold
21|                   {% if ticket.prioridad.value == 'critica' %}bg-red-100 text-red-700
22|                   {% elif ticket.prioridad.value == 'alta' %}bg-orange-100 text-orange-700
23|                   {% elif ticket.prioridad.value == 'media' %}bg-yellow-100 text-yellow-700
24|                   {% else %}bg-slate-100 text-slate-600{% endif %}">
25|        {{ ticket.prioridad.value|upper }}
26|      </span>
```

#### 5.1.2 Zona inferior / "footer" de la tarjeta — `tarjeta.html:77-109`

Esta es la zona que el usuario consultó. Contiene tres bloques: avatar + nombre del asignado (izquierda), y etiquetas + indicador SLA (derecha).

```jinja
 77|  <div class="flex items-center justify-between text-[11px] text-slate-500">
 78|    <div class="flex items-center gap-1.5">
 79|      {% if ticket.asignado %}
 80|        {% set ini = ticket.asignado.nombre_completo.split(' ')[:2]|map('first')|join|upper %}
 81|        <span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold" title="{{ ticket.asignado.nombre_completo }}">
 82|          {{ ini }}
 83|        </span>
 84|        <span>{{ ticket.asignado.nombre_completo.split(' ')[0] }}</span>
 85|      {% else %}
 86|        <span class="italic opacity-60">sin asignar</span>
 87|      {% endif %}
 88|    </div>
 89|    <div class="flex items-center gap-1.5">
 90|      {% if ticket.etiquetas %}
 91|        {% for e in ticket.etiquetas[:3] %}
 92|          <span class="inline-block w-2 h-2 rounded-full" style="background-color: {{ e.color }}" title="{{ e.nombre }}"></span>
 93|        {% endfor %}
 94|        {% if ticket.etiquetas|length > 3 %}
 95|          <span class="text-[10px] text-slate-400">+{{ ticket.etiquetas|length - 3 }}</span>
 96|        {% endif %}
 97|      {% endif %}
 98|      {% if ticket.sla_cumplido == 0 %}
 99|        <span class="inline-block w-1.5 h-1.5 rounded-full bg-red-500" title="SLA vencido"></span>
100|        <span class="text-red-600">SLA</span>
101|      {% elif ticket.sla_cumplido == -1 and ticket.fecha_vencimiento_sla %}
102|        <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-500" title="SLA próximo"></span>
103|        <span class="text-amber-600">SLA</span>
104|      {% elif ticket.sla_cumplido == 1 %}
105|        <span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" title="SLA OK"></span>
106|        <span class="text-emerald-600">SLA</span>
107|      {% endif %}
108|    </div>
109|  </div>
```

**Observación clave:** la zona inferior es el lugar natural para una insignia de `resultado_pruebas` (entre L97 y L98 hay espacio libre, y el bloque derecho ya aloja un indicador semántico con punto de color). El patrón a seguir es el de las etiquetas (L92): un punto de 2×2 px con `style="background-color: {{ … }}"`, alimentado por `CUENTA_RESULTADO_COLORES`.

También se observa que el bloque de producción (L54-76) se renderiza **antes** del footer, de modo que en una tarjeta con estado "Producción OK" el footer queda visualmente desplazado:

```jinja
 63|    <div class="mb-2 flex items-center gap-1.5 rounded-md bg-emerald-50 border border-emerald-200 px-2 py-1 text-[10px] text-emerald-800"
 64|         title="Ticket verificado y desplegado en ambiente productivo">
 65|      <span class="text-[12px] leading-none">🚀</span>
 66|      <span class="font-semibold tracking-wide uppercase">Listo en Prod</span>
...
 75|    </div>
 76|  {% endif %}
```

### 5.2 La sección «Cuenta de Resultado» del dashboard

**Ruta:** `/workspace/app/templates/dashboard/index.html`
**Sección (marcado):** `dashboard/index.html:214-251`
**Sección (JS que la puebla):** `dashboard/index.html:1292-1435`
**Destino del drill-down:** `dashboard/index.html:497` → `<div id="modal-cuenta-resultado-root">`

#### 5.2.1 Marcado de la sección — `dashboard/index.html:214-251`

```jinja
214|      <!-- ===== FILA 4 — CUENTA DE RESULTADO (restaurada) ===== -->
215|      {# Tabla pivote "Cuenta de Resultado" (réplica del rango A64:H81
216|         de la hoja REPORTE del Excel UAT). Pivot módulo (filas) ×
217|         resultado_pruebas (columnas) con drill-down HTMX por celda,
218|         exportación CSV y filtro por ambiente (QA). #}
219|      <div class="bg-white border border-slate-200 rounded-xl p-4 mb-6">
220|        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
221|          <div class="flex items-center gap-2">
222|            <h3 class="text-sm font-semibold text-slate-700">Cuenta de Resultado</h3>
223|          </div>
224|          <div class="flex items-center gap-2">
225|            <button id="cuenta-resultado-export"
226|                    onclick="exportarCuentaResultado()"
227|                    class="px-2.5 py-1 text-[11px] font-medium rounded-md border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 flex items-center gap-1">
228|              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
229|                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a1 1 0 01-2-2V5a1 1 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a1 1 0 01-2 2z"/>
230|              </svg>
231|              Exportar CSV
232|            </button>
233|          </div>
234|        </div>
235|        <div id="cuenta-resultado-container" class="overflow-x-auto">
236|          <div id="cuenta-resultado-loading" class="text-center py-6 text-slate-400 text-xs">
237|            Cargando tabla pivote...
238|          </div>
239|          <table id="cuenta-resultado-table"
240|                 class="hidden w-full text-xs border-collapse"
241|                 aria-label="Tabla pivote Cuenta de Resultado">
242|            <thead id="cuenta-resultado-thead"></thead>
243|            <tbody id="cuenta-resultado-tbody"></tbody>
244|            <tfoot id="cuenta-resultado-tfoot"></tfoot>
245|          </table>
246|        </div>
247|        <p id="cuenta-resultado-footer"
248|           class="hidden mt-2 text-[10px] text-slate-400 italic">
249|          POSTERGADA = normalización del valor original "POSTERGADA A GARANTÍA" (migración UAT).
250|        </p>
251|      </div>
```

#### 5.2.2 El mapa de color VIVO — `dashboard/index.html:1292-1300`

```js
1292|  const CUENTA_RESULTADO_COLORES = {
1293|    "N/A":         { bg: '#94a3b8', text: '#ffffff', cellText: '#1f2937' },
1294|    "NOK":         { bg: '#dc2626', text: '#ffffff', cellText: '#1f2937' },
1295|    "OK":          { bg: '#16a34a', text: '#ffffff', cellText: '#1f2937' },
1296|    "OK CON OBS.": { bg: '#eab308', text: '#1f2937', cellText: '#1f2937' },
1297|    "POSTERGADA":  { bg: '#ea580c', text: '#ffffff', cellText: '#1f2937' },
1298|    "DESESTIMADA": { bg: '#7c3aed', text: '#ffffff', cellText: '#1f2937' },
1299|    "(en blanco)": { bg: '#cbd5e1', text: '#475569', cellText: '#1f2937' },
1300|  };
```

#### 5.2.3 El mapa de color MUERTO (divergente) — `dashboard/index.html:886-895`

```js
886|  // ============== CUENTA DE RESULTADO ==============
887|  function renderCuentaResultado(cuenta) {
888|    const cont = safeId('cuenta-resultado-container');
889|    if (!cont) return;
890|    if (!cuenta || cuenta.length === 0) {
891|      cont.innerHTML = '<p class="text-xs text-slate-400 text-center py-6">Sin incidencias cerradas con resultado de pruebas en el periodo</p>';
892|      return;
893|    }
894|    const RESULTADOS = ['OK', 'OK CON OBS.', 'NOK', 'POSTERGADA', 'DESESTIMADA', 'N/A'];
895|    const RESULTADO_COLORS = { 'OK': '#10b981', 'OK CON OBS.': '#22c55e', 'NOK': '#ef4444', 'POSTERGADA': '#eab308', 'DESESTIMADA': '#a855f7', 'N/A': '#94a3b8' };
```

Esta función **nunca se invoca**: la única llamada real es `cargarCuentaResultado()` (L1305), llamada desde L684 y L850.

#### 5.2.4 El cargador vigente — `dashboard/index.html:1305-1435` (extracto)

```js
1305|  function cargarCuentaResultado() {
…
1336|    // estado vacío
1337|    //   → mensaje: "Sin incidencias cerradas con resultado de pruebas en el periodo"
1348|    //   → (menciona «resultado_pruebas» en el texto del estado vacío)
…
1359|    // cabecera: title="Tickets con resultado_pruebas = '" + c + '"'
…
1373|    //   → usa CUENTA_RESULTADO_COLORES[c].bg / .text
…
1415|    // pie: usa CUENTA_RESULTADO_COLORES[…].bg
…
1432|    htmx.process(tbody);   // reprocesa el drill-down inyectado
```

Las celdas del drill-down (L1368-1408) hacen `hx-get` contra `/api/v1/metricas/cuenta-resultado/detalle?modulo=…&resultado=…&ambiente=…` con `hx-target="#modal-cuenta-resultado-root"`.

### 5.3 Definición actual de colores — mapa consolidado

| Contexto | Ubicación | Definición |
|---|---|---|
| **Resultado de pruebas (vivo)** | `dashboard/index.html:1292-1300` | `CUENTA_RESULTADO_COLORES` — 7 entradas × 3 canales |
| **Resultado de pruebas (muerto)** | `dashboard/index.html:895` | `RESULTADO_COLORS` — 6 entradas planas, **divergente** |
| **Prioridad (dashboard)** | `dashboard/index.html:819` | `prioColors = { critica: '#dc2626', alta: '#ea580c', media: '#eab308', baja: '#64748b' }` |
| **Prioridad (dashboard, badge)** | `dashboard/index.html:1511-1524` | `_prBadge`: `critica: { bg:'#fee2e2', fg:'#991b1b', dot:'#dc2626', label:'Crítica' }` |
| **Prioridad (dashboard, KPI)** | `dashboard/index.html:1035` | `_kpiPrioridadColor`: `critica → '#dc2626'` |
| **Prioridad (servidor)** | `main.py:1775-1780` | `PRIORIDAD_COLOR = {"critica":"#ef4444","alta":"#f97316","media":"#f59e0b","baja":"#94a3b8"}` |
| **Prioridad (tarjetas)** | `tarjeta.html:21-24`, `tarjeta.py:41-44`, `card.py:29` | Tailwind: `red-100/700`, `orange-100/700`, `yellow-100/700`, `slate-100/600` |
| **Prioridad (vistas)** | `vistas/tabla.html:90`, `vistas/timeline.html:113`, `tableros/publico.html:43` | Tailwind: `red-100/700`, `orange-100/700`, **`amber-100/700`**, `slate-100/600` |
| **SLA (tarjeta)** | `tarjeta.html:98-107` | `bg-red-500`+`text-red-600` / `bg-amber-500`+`text-amber-600` / `bg-emerald-500`+`text-emerald-600` |
| **SLA (tarjeta.py)** | `tarjeta.py:85-98` | Pastillas `bg-red-50 text-red-700 border-red-200` / `amber-50/700/200` / `emerald-50/700/200` |
| **Estado "Listo en Prod"** | `tarjeta.html:63` | `bg-emerald-50 border-emerald-200 text-emerald-800` |
| **Avatar asignado** | `tarjeta.html:81` | `bg-indigo-100 text-indigo-700` |
| **Etiquetas** | `tarjeta.html:92` | `background-color: {{ e.color }}` (dinámico, desde BD) |
| **Indicador hover** | `tarjeta.html:111` | `from-transparent via-indigo-500 to-transparent` |

### 5.4 Cómo se renderiza `resultado_pruebas` hoy

**En las tarjetas Kanban: no se renderiza.** Ni `tarjeta.html`, ni `tarjeta.py`, ni `card.py` contienen la cadena. La única evidencia de que el concepto se contempla en el tablero es el filtro `kanban/index.html:104` (`<option value="resultado_pruebas">Resultados de pruebas</option>`).

**En el dashboard: sí, y de dos maneras.** (a) Como **columna del pivote**, inyectada en el `<thead>` por `cargarCuentaResultado()` con un tooltip `title="Tickets con resultado_pruebas = '…'"` (L1362). (b) Como **texto del estado vacío** (L1348) y como **comentario descriptivo** en el bloque Jinja (L217).

**En el alta de tickets: como campo de formulario.** `tickets/nuevo_modal.html` lo ofrece en un `<select>` (L62, L192-193) para que el usuario capture el resultado de pruebas al crear el ticket.

**En el backend: como columna de la tabla `Ticket`**, consultada en `api/v1/metricas.py:402,408,411,619,636,766` y en `api/v1/admin_uat.py:185-251`, con el LOV completo definido en `api/v1/metricas.py:83`.

---

## 6. Todo lo verificado como correcto

Esta sección documenta lo que **no** requiere intervención, para evitar que una auditoría futura lo re-investigue.

**Enlaces y rutas.** Los 79 `href` internos extraídos de las 31 plantillas se resolvieron contra las 242 rutas registradas: **0 enlaces internos rotos**. Los `href` con `href="#"`, `href="javascript:…"`, URLs externas (http/https/mailto) y el único href dinámico (`notificaciones/index.html:55`, `href="{{ n.url }}"`) se clasificaron aparte y son correctos. Los `href` a `#` con ancla corresponden a IDs existentes.

**Endpoints HTMX.** Los 35 atributos `hx-get`/`hx-post`/`hx-patch` resuelven contra el router: **0 endpoints inexistentes**. Inventario completo de atributos `hx-*` en uso: `hx-swap`×32, `hx-target`×31, `hx-get`×20, `hx-post`×13, `hx-trigger`×4, `hx-encoding`×3, `hx-confirm`×2, `hx-patch`×1, `hx-indicator`×1. No hay `hx-delete` ni `hx-put`.

**Destinos `hx-target`.** Los 31 `hx-target` resuelven a un elemento existente. Los dos que usan selector dinámico (`kanban/index.html:191` y `:200`, `hx-target="#column-header-{{ estado.id }}"`) son **correctos**: el `id` se declara en `kanban/index.html:160`.

**Filtros y globals Jinja.** Los 3 filtros usados (`truncate_text`, `cl`, `cl_iso`) están registrados en `app/core/jinja_filters.py` (`ALL_FILTERS`, L129-131, L195-196) y conectados al entorno en `main.py:142-145`. **0 filtros no registrados.** El global `dev_inbox_enabled` se registra correctamente en `main.py:150` como **función** (`is_enabled`), no como booleano.

**Includes.** Los 4 `{% include %}` apuntan a archivos existentes: `kanban/index.html` → `kanban/partials/tarjeta.html`, `vistas/planner.html` → `vistas/_planner_sections.html`, y los de `base.html`.

**Plantillas huérfanas: 0.** Las dos que el análisis marcó inicialmente (`auth/cambiar_password_modal.html`, `usuarios/admin_reset_password_modal.html`) se sirven como lectura cruda de archivo desde `api/v1/auth.py:483-508` y `api/v1/usuarios.py:733-809`. No están huérfanas.

**Variables Jinja: 0 indefinidas reales.** 26 plantillas tienen su contexto completo. Las 5 restantes son **falsos positivos** del análisis estático, todos explicados:

| Plantilla | Variable señalada | Por qué no es un bug |
|---|---|---|
| `base.html` | `usuario` | Los 3 accesos están guardados: L117 `{% if usuario and usuario.rol.value … %}`, L182 `{% if usuario %}`, L237-238 `usuario.id if usuario else 1`. `tableros/publico.html` no lo pasa y **renderiza correctamente**. |
| `kanban/index.html` | `first_initial`, `resp_display`, `resp_initials`, `resp_nombre`, `resp_partes`, `second_initial` | Las 6 son `{% set %}` — Jinja las define en la propia plantilla. |
| `kanban/partials/tarjeta.html` | `ini`, `prod_hist` | `{% set %}` en L80 y L56. |
| `kanban/partials/tarjeta.html` | `ticket` | Contexto heredado del `{% include %}` de `kanban/index.html:218`. |
| `roles_funciones/index.html` | `usuarios_de_este_rol` | `{% set %}` en la propia plantilla. |
| `usuarios/admin_reset_password_modal.html` | `usuario` | Renderizada por `.replace()` manual; las 3 expresiones de la plantilla están cubiertas. |

**Compilación Jinja.** 30 de 31 plantillas compilan sin `TemplateSyntaxError`. La única que falla es `admin/reporte_entregas.html:508` (P0).

**Código Python vivo.** Los 4 módulos `.py` dentro de `templates/` están importados y en uso; ninguno es código muerto.

**Módulos JS estáticos.** `htmx.min.js` (biblioteca de terceros) y los 6 módulos de primera parte (`auth-events`, `command-palette`, `htmx-events`, `htmx-fallback`, `image-preview`, `kanban`) están cargados por `base.html`.

**Reproducción y drill-down.** La «Cuenta de Resultado» usa correctamente `htmx.process(tbody)` (L1432-1434) tras inyectar el `<tbody>`, requisito indispensable para que los botones de drill-down con `hx-get` funcionen en nodos insertados dinámicamente.

---

## 7. Limitaciones y supuestos del análisis

El análisis es **estático**: no se ejecutó la aplicación ni se verificó el render en navegador, por lo que los errores de runtime (p. ej. un `AttributeError` sobre un objeto SQLAlchemy) no están cubiertos. Las plantillas que renderizan el dashboard son casi enteramente **client-side** (`dashboard/index.html` recibe únicamente `usuario` como contexto y construye el resto vía `fetch`), por lo que su corrección depende del JSON de la API, no de Jinja.

La detección de JS muerto se basa en análisis textual de identificadores. Es concluyente para el patrón `function nombre(...)` (206 declaraciones revisadas, 3 con cero referencias externas), pero no detectaría una función invocada **indirectamente** (p. ej. `window['nombre']` o un `eval`) — se revisó el HTML completo, no sólo los bloques `<script>`, para cubrir los `onclick` y los `hx-on`.

El mapeo de variables cruzó `main.py` y `api/v1/*.py`, pero no `tasks/` (Celery/background), que podría renderizar plantillas en un contexto no inventariado. La revisión manual de `tasks/` no encontró ninguna llamada a `TemplateResponse`.

La tabla de "variables no proveyó por la vista" depende de que las vistas construyan su contexto de forma estática; las vistas que construyen el dict en una variable local (el caso de `main.py:1863-1869`, que usa `context = {…}` y lo pasa posicionalmente) ya están resueltas por el extractor.

---

## 8. Conclusiones

La capa de presentación de este proyecto está **notablemente bien conectada**: no hay un solo enlace roto, un solo endpoint HTMX inexistente, un solo include fallido, un solo filtro sin registrar ni una sola variable Jinja indefinida. Ese es el resultado de una disciplina de wiring notable y es el activo más valioso del repositorio — no conviene tocarlo.

Sobre esa base sólida, la auditoría identifica **un defecto bloqueante** y **tres problemas de diseño** que merecen atención. El P0 de `reporte_entregas.html:508` es trivial en su corrección (un carácter) y anula por completo una vista administrativa. Los dos P1 son de la misma familia: **código duplicado que ha divergido**. La tarjeta Kanban existe en tres variantes que ya no coinciden en el badge de SLA, en el bloque de producción ni en el número de iniciales del avatar; y la «Cuenta de Resultado» conserva un mapa de color fantasma que contradice al vigente en 5 de 6 entradas. En ambos casos el síntoma no es un crash sino una **inconsistencia silenciosa**: la misma entidad se ve distinta según la ruta por la que se sirva, y el código muerto es precisamente el más legible, lo que lo convierte en la fuente de error más probable para quien lo lea después.

Los dos P2 de JS muerto en `kanban.js` merecen atención aparte porque describen un **flujo de negocio ausente**, no simple residuo: el tablero nunca valida si una transición exige comentario, aunque el servidor lo expone (`api/v1/tickets.py:273`) y el modal de detalle sí lo aplica. El código muerto es la huella de una validación que se diseñó y no se conectó.

Finalmente, el hallazgo que responde directamente a la pregunta del usuario sobre `resultado_pruebas` es que **el dato existe en la base de datos, se pivota en el dashboard y se captura al crear un ticket, pero no se exhibe en el tablero**. La zona inferior de la tarjeta (`tarjeta.html:77-109`) tiene el espacio y el patrón visual exactos para hacerlo: un punto de color de 2×2 px como el de las etiquetas (L92), alimentado por el mapa `CUENTA_RESULTADO_COLORES` que ya existe en `dashboard/index.html:1292`. El inventario de colores muestra además que la prioridad `media` se renderiza en **amarillo** en el Kanban y en **ámbar** en las vistas, y que el código de color de la prioridad vive duplicado en 8 lugares: unificarlo en una constante compartida es la corrección de mayor rendimiento esfuerzo/beneficio de todo el informe.

---

## 9. Recomendaciones priorizadas

| # | Acción | Severidad que resuelve | Esfuerzo |
|---|---|---|---|
| 1 | `admin/reporte_entregas.html:508`: `{% endif}>` → `{% endif %}>` | **P0** | 1 carácter |
| 2 | Eliminar `dashboard/index.html:886-947` (`renderCuentaResultado` + `RESULTADO_COLORS`) | **P1** | ~60 líneas, riesgo nulo |
| 3 | Unificar la tarjeta Kanban en un único partial (`.html`) y hacer que `tarjeta.py`/`card.py` lo rendericen vía `Jinja2Templates` | **P1** | medio |
| 4 | Unificar el color de prioridad en una constante compartida y aplicarla en los 8 sitios | **P2** | medio |
| 5 | Decidir el destino de `getTransicionInfo()` y `pedirComentario()`: o se conectan al drag & drop, o se eliminan junto con `transicionCache` | **P2** | medio |
| 6 | Renderizar `usuarios/admin_reset_password_modal.html` y `auth/cambiar_password_modal.html` con `Jinja2Templates` | **P2** | bajo |
| 7 | Añadir la insignia de `resultado_pruebas` en el footer de la tarjeta (`tarjeta.html:89-107`) usando `CUENTA_RESULTADO_COLORES` | **P3** | bajo |
| 8 | Mover los 4 módulos `.py` fuera de `app/templates/` | **P3** | bajo |

> Nota de secuencia: la acción 3 debe ejecutarse **antes** de la 7, o la insignia nueva se replicará tres veces. La acción 2 debe ejecutarse antes de la 7 para no reintroducir una segunda paleta.

---

## 10. Anexo — Fuentes consultadas

Auditoría interna sobre el propio repositorio. Las "fuentes" son los archivos del proyecto examinados:

| # | Archivo | Contenido | Fiabilidad |
|---|---|---|---|
| 1 | `/workspace/app/main.py` (~2500 L) | Rutas raíz, `Jinja2Templates` (L137), registro de filtros (L142-145), global (L150), montaje de routers (L154), `PRIORIDAD_COLOR` (L1775-1780), contexto del planner (L1863-1869), rutas admin (L2191-2238) | Alta — fuente de verdad del servidor |
| 2 | `/workspace/app/api/v1/*.py` (22 módulos) | 242 rutas registradas; `tickets.py:273` (`transicion-info`), `tickets.py:80,253,419,521,675,741,1106` (imports de render) | Alta |
| 3 | `/workspace/app/api/v1/metricas.py` | Origen del campo `resultado_pruebas`: LOV (L83), pivote (L402-411, L619-636, L766-771), `cuenta-resultado` (L576-610) | Alta |
| 4 | `/workspace/app/api/v1/admin_uat.py` | SQL sobre `resultado_pruebas` (L185-251) | Alta |
| 5 | `/workspace/app/api/v1/usuarios.py:733-809` | Render manual del modal de reset (`.replace`) | Alta |
| 6 | `/workspace/app/api/v1/auth.py:483-508` | Render crudo del modal de contraseña | Alta |
| 7 | `/workspace/app/core/jinja_filters.py` | `ALL_FILTERS` = `truncate_text` (L129-131), `cl` (L195), `cl_iso` (L196) | Alta |
| 8 | `/workspace/app/templates/**` (31 HTML + 4 PY) | Corpus auditado | Alta |
| 9 | `/workspace/app/static/js/*.js` (7 archivos) | 206 funciones JS; 3 muertas | Alta |
| 10 | `/workspace/app/static/css/styles.css` | Clases Tailwind y componentes propios | Media — no auditado exhaustivamente |

**Artefactos de la auditoría** (generados, no forman parte del proyecto): `/workspace/tmp/audit/` contiene `extract_routes2.py`, `analyze2.py`, `vars.py`, `vars2.py`, `triage.py`, `undef_test.py`, `base_render.py`, `orphans_hx.py`, `deadjs2.py`, `deadjs3.py`, `colors_check.py`, `final_checks.py` y sus salidas JSON (`routes.json`, `vars2.json`, `orphans.json`).

---

*Fin del informe. Ningún archivo bajo `/workspace/app/` fue creado, modificado ni eliminado durante esta auditoría.*
