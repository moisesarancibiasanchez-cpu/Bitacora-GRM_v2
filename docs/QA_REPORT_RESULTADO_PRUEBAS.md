# Informe QA — Verificación de la migración de «Resultado de Pruebas» a SSOT

**Proyecto:** FastAPI + Jinja2 + HTMX + TailwindCSS — `/workspace`
**Fecha de ejecución:** 2026-10-24
**Alcance:** los 5 puntos solicitados sobre las modificaciones en `kanban/partials/tarjeta.html`, `dashboard/index.html`, `admin/reporte_entregas.html` y `app/core/resultado_pruebas.py`
**Restricción respetada:** no se modificó ningún archivo de `/workspace/app`. Todos los scripts viven en `/workspace/tmp/`.

---

## Resumen ejecutivo

| # | Verificación | Resultado | Volumen |
|---|---|---|---|
| 1 | Compilación Jinja2 de todas las plantillas | **PASS** | 31/31 compilan, 0 errores |
| 2 | Sintaxis JS inline + ámbito/TDZ | **PASS** | 24/24 bloques válidos, 0 TDZ, 0 usos no visibles |
| 3 | Enlaces internos vs. rutas registradas | **PASS** | 111/111 resuelven, 0 rotas, 0 desajustes de método |
| 4 | Duplicidad de paleta fuera del SSOT | **FAIL** | 1 hallazgo (7 redefiniciones en 1 archivo) |
| 5 | JS inline huérfano | **PASS** | 0 referencias huérfanas, 0 invocaciones |

**Veredicto:** 4 de 5 verificaciones pasan. El único FAIL es la **Verificación 4**: existe una segunda copia de la paleta de 7 colores canónicos en `app/api/v1/metricas.py:715-723`, fuera del módulo SSOT, y consumida en `app/api/v1/metricas.py:885`. No es una divergencia visual hoy (los `bg`/`text` coinciden exactamente con el SSOT), pero es una violation del invariante de fuente única.

---

## 1. Compilación Jinja2 de TODAS las plantillas — PASS

Se compilaron recursivamente los 31 archivos `.html` bajo `app/templates/` con dos entornos: uno sintético equivalente (`Environment(FileSystemLoader, autoescape=True)` + `app.core.jinja_filters.ALL_FILTERS`) y, de forma decisive, **el entorno real de la app** obtenido de `app.main` (`templates.env`, con `autoescape=select_autoescape` y los 62 filtros registrados).

Resultado: **31/31 OK con el entorno real, 0 con error.** Los tres globals nuevos (`resultado_info`, `resultado_info_ticket`, `badge_resultado`) están presentes en `templates.env.globals`.

Las variables que el análisis estático de Jinja marca como «no declaradas» son informativas, no fallos: son parámetros que cada ruta inyecta en su contexto. En particular, las dos que interesan a esta revisión están confirmadas en `app/main.py:2318-2319`, dentro del handler `GET /dashboard`:

```python
"cuenta_resultado_colores": paleta_js(),
"cuenta_resultado_acronimos": acronimos_js(),
```

El fix de `admin/reporte_entregas.html` (el `{% endif %}>` mal cerrado) queda validado: la plantilla compila y los cuatro `endif` de cierre de `<input>` están correctamente formados en `admin/reporte_entregas.html:299`, `:455`, `:499` y `:508`.

### Corroboración end-to-end del render real

Renderizando `dashboard/index.html` con el entorno real y el contexto real de la ruta (`/workspace/tmp/qa_02h_e2e.py`):

- Los dos `<script type="application/json">` aparecen en el HTML renderizado con los ids `cuenta-resultado-paleta` y `cuenta-resultado-acronimos` (`dashboard/index.html:258-259`).
- Ambos contienen JSON válido y **coinciden exactamente** con `paleta_js()` y `acronimos_js()` (7 claves cada uno).
- **0 placeholders `{{ }}` sin resolver** en el HTML renderizado.
- Los 5 bloques `<script>` JS del HTML renderizado pasan `node --check`.

---

## 2. Validación de JS inline — PASS

### 2.1 Sintaxis (`node --check`)

Se extrajeron **24 bloques `<script>` inline** de todas las plantillas (los `<script src=...>` y `type="application/json"` se excluyen del análisis de JS y se tratan aparte). Cada bloque se escribió a un `.js` temporal en `/workspace/tmp/` y se validó con `node --check` (Node v20.20.2).

**0 fallos de sintaxis en los 24 bloques.**

### 2.2 Ámbito y TDZ

El análisis estático no basta: un `const` usado antes de su declaración en el **mismo** ámbito produce `ReferenceError` en runtime, pero un uso dentro de una función anidada es diferido y seguro, y una `function` declarada se eleva (*hoisting*). Por eso se construyó la cadena de ámbitos (cuerpos de función nombrados, IIFE anónimos y *arrow functions* con cuerpo de bloque) y se clasificó cada uso de las sieteidentificadores clave.

| Identificador | Declaración | Ámbito | Usos | Clasificación |
|---|---|---|---|---|
| `CUENTA_RESULTADO_COLORES` | `const` (dashboard:1313) | IIFE raíz | 5 | 1 diferido en `renderCuentaResultado` + 3 diferidos en *arrow* + 1 declaración → **seguro** |
| `CUENTA_RESULTADO_ACRONIMOS` | `const` (dashboard:1321) | IIFE raíz | 2 | 1 diferido en `acronimoResultado` → **seguro** |
| `acronimoResultado` | `function` (dashboard:1328) | IIFE raíz | 3 | *hoisted* → **seguro** |
| `_escapeHtml` | `function` (dashboard:1522) | IIFE raíz | 19 | *hoisted* → **seguro** |
| `renderCuentaResultado` | `function` (dashboard:896) | IIFE raíz | 1 | *hoisted* → **seguro** |
| `cargarCuentaResultado` | `function` (dashboard:1335) | IIFE raíz | 2 | *hoisted* (uso en L693) → **seguro** |

**0 TDZ reales y 0 usos no visibles.** En particular, `cargarCuentaResultado()` se invoca en `dashboard/index.html:693`, muy por encima de su declaración en `:1335`, pero como es una *function declaration* se eleva y no produce `ReferenceError`.

### 2.3 Corroboración en runtime (Node `vm` + stub de DOM)

El análisis estático se validó ejecutando el script real del dashboard en un sandbox `node:vm` con un DOM simulado, replicando la semántica del navegador (el script se evalúa primero; los handlers `DOMContentLoaded` se despachan después):

- **Fase 1 — evaluación del script:** OK, sin excepción.
- **Fase 2 — despacho de `DOMContentLoaded`:** OK, 1 handler ejecutado sin excepción.
- `CUENTA_RESULTADO_COLORES` y `CUENTA_RESULTADO_ACRONIMOS` quedan **poblados** desde el JSON inyectado por el server (`vacio: false`, 7 claves cada uno).
- `acronimoResultado()` devuelve `OK`→`OK`, `N/A`→`N/A`, `OK CON OBS.`→`OBS`, `POSTERGADA`→`POST`, `DESESTIMADA`→`NOOK`, `NOK`→`NOK`, `(en blanco)`→`S/D`, y hace *fallback* al valor crudo para entradas desconocidas.
- `_escapeHtml()` escapa correctamente (`<script>` → `&lt;script&gt;`, `&` → `&amp;`).
- `RESULTADO_COLORES` **no existe** en runtime; `renderCuentaResultado` sí es función y no lanza.
- El `<thead>` renderizado muestra los acrónimos `N/A, NOK, OK, OBS, POST, NOOK, S/D` con los colores canónicos (`#94a3b8, #dc2626, #16a34a, #eab308, #ea580c, #7c3aed, #cbd5e1`) y los `title` con el valor largo (`'OK CON OBS.'`), confirmando que el encabezado de columnas cambió de valor largo a acrónimo.

> **Nota (artefacto del harness, no defecto de la app):** durante la fase 2 se registra `TypeError: Cannot read properties of undefined (reading 'total')` en `render()`. Proviene del *mock* de `fetch` del harness, que devuelve `{}` para `/api/v1/metricas/dashboard-completo` (el único endpoint mockeado es `/api/v1/metricas/cuenta-resultado`); el acceso es `d.totales.total` sobre `d = {}`. Es una limitación del stub, ajena al código modificado, y la propia app lo captura en su `try/catch` alrededor de `render()`.

---

## 3. Enlaces internos rotos — PASS

Se extrajeron las referencias internas absolutas de los 31 templates (`href="/..."`, `src="/..."`, `action="/..."`, `hx-get|post|put|delete|patch="/..."`), normalizando query strings y placeholders `{{ }}`, y se contrastaron contra el inventario de rutas.

Inventario de rutas: **198 paths** en el esquema OpenAPI (**125 exactos** + **81 con `{param}`**), más 2 *mounts* que sirven archivos (`/static`, `/onboarding`).

| Métrica | Valor |
|---|---|
| Referencias internas detectadas | **111** |
| Resuelven a una ruta registrada | **111** |
| **Rotas rotas** (sin ruta que las sirva) | **0** |
| **Desajustes de método HTTP** (`hx-*`/`action` vs. método de la ruta) | **0** |
| URLs dinámicas (informativo) | 34 |

Las 34 dinámicas (informativas, no contadas como rotas) son de dos tipos: placeholders Jinja (`/api/v1/tickets/{{ t.id }}/detalle-html`, `/vistas/tabla?espacio={{ espacio_actual.id }}`) y template literals JS (`/api/v1/butler/backup/download/${encodeURIComponent(b.filename)}`).

> **Caveat de herramienta:** en esta build de FastAPI, `app.routes` **no** aplana el router incluido vía `include_router` (`app/main.py:205`); los routers aparecen como `_IncludedRouter` sin atributo `.routes`, y `api_router.routes` directo es 0. La introspección inicial por `app.routes` produjo 48 falsos positivos de enlaces rotos. El inventario autoritativo se tomó de `app.openapi()["paths"]`, y el resultado corregido es 0 rotas.

---

## 4. Duplicidad de paleta — **FAIL**

### Regla aplicada

SSOT declarado: `app/core/resultado_pruebas.py`. Se buscaron en los **129 archivos** bajo `/workspace/app` los 7 hex canónicos (`#16a34a`, `#dc2626`, `#eab308`, `#ea580c`, `#7c3aed`, `#94a3b8`, `#cbd5e1`) y los identificadores `CUENTA_RESULTADO_COLORES` / `RESULTADO_COLORES`, distinguiendo **(a) redefinición de color** de **(b) mención del valor LOV en SQL/lógica**.

Volumen: **80 ocurrencias de hex canónicos** y **401 ocurrencias de valores LOV**.

### Hallazgo único (FAIL)

**Archivo:** `app/api/v1/metricas.py`
**Líneas:** `715-723`
**Símbolo:** `CUENTA_RESULTADO_COLORES_PARA_MODAL`

```
714  # Mapa de colores para el badge del modal (sincronizado con el front).
715  CUENTA_RESULTADO_COLORES_PARA_MODAL = {
716      "N/A":         {"bg": "#94a3b8", "text": "#ffffff"},
717      "NOK":         {"bg": "#dc2626", "text": "#ffffff"},
718      "OK":          {"bg": "#16a34a", "text": "#ffffff"},
719      "OK CON OBS.": {"bg": "#eab308", "text": "#1f2937"},
720      "POSTERGADA":  {"bg": "#ea580c", "text": "#ffffff"},
721      "DESESTIMADA": {"bg": "#7c3aed", "text": "#ffffff"},
722      "(en blanco)": {"bg": "#cbd5e1", "text": "#475569"},
723  }
```

Es una **copia completa de los 7 colores canónicos** (7 redefiniciones) definida fuera del SSOT. Se consume en `app/api/v1/metricas.py:885`:

```python
885  color_cfg = CUENTA_RESULTADO_COLORES_PARA_MODAL.get(resultado_filtro)
```

**Caracterización precisa del impacto** (verificado comparando en memoria `CUENTA_RESULTADO_COLORES_PARA_MODAL` contra `paleta_js()`):

- Mismas 7 claves, sin claves adicionales ni ausentes.
- `bg` y `text` **idénticos** al SSOT en las 7 entradas → **no hay divergencia visual hoy**.
- Única diferencia: el duplicado **no incluye la clave `cellText`** (`#1f2937`) que el SSOT sí expone. `metricas.py` no lee `cellText`, por lo que hoy no tiene efecto.
- `app/api/v1/metricas.py` **no importa** `app.core.resultado_pruebas` (verificado: no aparece `from app.core.resultado_pruebas` ni `import ... resultado_pruebas` en el módulo). La copia es autonomous, sin vínculo con el SSOT.

Es, por tanto, una **violación del invariante de fuente única con riesgo de deriva**, no un bug visible en el estado actual.

### Ocurrencias clasificadas como NO hallazgo

Las siguientes son **color genérico / otro dominio** o **mera mención del valor LOV en SQL/lógica**, y por definición no son hallazgo:

- `app/api/v1/buscar.py:64`, `app/api/v1/tickets.py:1240`, `app/services/trello_service.py:566,619,656`, `app/main.py:1303,1672,1681,1704,1830,1885,1903,2047,2062`, `app/models/estado.py:26`, `app/schemas/ticket.py:69`, `app/services/uat_import.py:124,132`, `app/api/v1/metricas.py:391,836,1105` → color por defecto de **estado/prioridad** (`#94a3b8` como *slate-400* genérico).
- `app/db/init_db.py:347,355,520,529` → paleta de **criticidad/impacto** del Tablero y `color_fondo` de tableros.
- `app/services/email_service.py:738,739,880,887` → paleta de **roles** en el HTML de emails.
- `app/static/css/styles.css:23,78,79`, `app/templates/admin/reporte_entregas.html:69,156`, `app/templates/dashboard/index.html:793,812,818,828` → CSS de scrollbar/bordes y `prioColors` de **prioridad** (no de Resultado de Pruebas).
- Las 401 menciones de valores LOV (`OK`, `NOK`, `OK CON OBS.`, `POSTERGADA`, `DESESTIMADA`, `N/A`, `(en blanco)`) en SQL de agregación, filtros, migraciones, modelos y schemas: son **valores de negocio**, no definiciones de color.

---

## 5. JS inline huérfano — PASS

### 5.1 `RESULTADO_COLORES` — 0 referencias

Búsqueda con **frontera de identificador** (`(?<![A-Za-z0-9_$])RESULTADO_COLORES(?![A-Za-z0-9_$])`) sobre los **128 archivos** de `/workspace/app`:

- **0 referencias** al identificador `RESULTADO_COLORES`.
- **0 apariciones en código vivo** (verificado con el lexer Jinja+JS: los 0 únicos hits están en comentarios/docstrings).

Las dos únicas menciones del *antiguo* nombre `RESULTADO_COLORS` (sin la "E") son texto histórico, no código:

- `app/core/resultado_pruebas.py:22` — docstring que documenta el mapa eliminado.
- `app/templates/dashboard/index.html:906` — comentario que explica que antes esa función declaraba su propio mapa divergente.

> **Precisión sobre subcadenas:** `CUENTA_RESULTADO_COLORES` **contiene** la subcadena `RESULTADO_COLORES`, pero es un identificador distinto y por tanto no computa como referencia al identificador eliminado. Sus apariciones (`app/templates/dashboard/index.html:909,1313,1393,1409,1451`; `app/core/resultado_pruebas.py:20,102`; `app/api/v1/metricas.py:715,885`) son todas lecturas del mapa compartido o la copia señalada en V4.

### 5.2 `renderCuentaResultado` — existe y NO es invocada

- **Definición:** 1 — `app/templates/dashboard/index.html:896` → `function renderCuentaResultado(cuenta) {`.
- **Invocaciones:** **0**, en ningún archivo (`.py`, `.html` o `.js`). Verificado por AST de Python (módulo `ast`, que distingue `def` de `Call`) y por el lexer JS.
- **Censo textual bruto:** exactamente **2 ocurrencias** en toda la app — la declaración (`dashboard/index.html:896`) y una mención en el docstring de `app/core/resultado_pruebas.py:23` (`"(paleta muerta dentro de ``renderCuentaResultado()``, que nunca se…"`). Al no existir ninguna tercera ocurrencia, es una prueba cerrada de que la función nunca se invoca.

En runtime, el harness confirma `renderCuentaResultado_es_funcion: true`, `lanzo: false` y `RESULTADO_COLORES_existe: false`.

### 5.3 Identificadores invocados sin declaración visible — 0

En los **24 bloques inline** de todas las plantillas: **0 identificadores** invocados sin declaración visible (ni local, ni en `base.html`, ni en `app/static/js/`), excluyendo los globals de navegador. El propio analizador se autovalida ejecutando `node --check` sobre el JS "stripped" de cada bloque: **OK en los 24 bloques**.

---

## Corroboración adicional: badge del Kanban

Renderizando `kanban/partials/tarjeta.html` con el entorno real y un ticket por cada valor del LOV (`/workspace/tmp/qa_05b_badge_e2e.py`), el badge emitido por `{{ badge_resultado(resultado_info_ticket(ticket)) }}` coincide **exactamente** con el SSOT en `bg`, `text` y acrónimo para las 7 entradas:

| Valor | bg | text | Acrónimo | Estado |
|---|---|---|---|---|
| `N/A` | `#94a3b8` | `#ffffff` | `N/A` | OK |
| `NOK` | `#dc2626` | `#ffffff` | `NOK` | OK |
| `OK` | `#16a34a` | `#ffffff` | `OK` | OK |
| `OK CON OBS.` | `#eab308` | `#1f2937` | `OBS` | OK |
| `POSTERGADA` | `#ea580c` | `#ffffff` | `POST` | OK |
| `DESESTIMADA` | `#7c3aed` | `#ffffff` | `NOOK` | OK |
| `(en blanco)` | `#cbd5e1` | `#475569` | `S/D` | OK |

Los valores vacíos (`None` / `''`) caen en `(en blanco)` con acrónimo `S/D`; un valor fuera del LOV se muestra en estilo neutro (`#e2e8f0`) con el texto crudo truncado; y para un tipo de ticket no aplicable (`solicitud`) con resultado vacío **no se emite badge**. La paleta del badge es idéntica a la inyectada al dashboard.

---

## Notas de metodología y limitaciones del instrumental

Estas notas documentan el *herramiental de QA*, no defectos de la aplicación:

1. **Lexer Jinja+JS de una sola pasada.** Los strippers ingenuos (`strip_jinja` con regex) borran código JS legítimo: un `{{` dentro de un literal o comentario elimina todo hasta el siguiente `}}`. Una versión previa del analizador de V5 producía por ello un **falso FAIL** ("`renderCuentaResultado` no existe") y dejaba en blanco los identificadores, con lo que los análisis de V2 eran **vacíos**. El lexer final (`/workspace/tmp/qa_jslex3.py`) tokeniza Jinja y JavaScript simultáneamente, reconoce delimitadores Jinja **sólo en posición de código**, soporta *template literals* con interpolaciones `${...}` anidadas y distingue regex de división por el token anterior. Se autovalida con `node --check` sobre su propia salida (preservando delimitadores y longitud), lo que garantiza que una desincronización del escáner se detectaría como JS inválido.
2. **Distinción regex vs. división.** Decidir por el carácter anterior producía falsos positivos con `a / b / c`; la decisión se toma sobre el token previo (`)`/`]`/`++`/`--` → división; identificador → sólo si es *keyword*).
3. **Inventario de rutas.** `app.routes` no aplana los routers incluidos por `include_router` en esta build; se usó `app.openapi()["paths"]` (198 paths) como fuente autoritativa.
4. **Clasificación semántica de la paleta.** La coincidencia de un hex canónico no implica redefinición: se aplicó el criterio «clave LOV → hex canónico en el mismo literal/mapa», que reduce los candidatos de 75 a 1.
5. **Alcance de V2.** La validación covers el JS inline de plantillas. Los ficheros estáticos de `app/static/js/` se usaron como fuente de declaraciones para el análisis de identificadores, pero no se re-validó su sintaxis en esta tanda.

## Inventario de scripts (todos bajo `/workspace/tmp/`, ninguno toca `/workspace/app`)

| Script | Función |
|---|---|
| `qa_01_compile_templates.py` | V1 — compilación Jinja2 con env sintético y env real |
| `qa_02f_js_check.py` | V2 — `node --check` + cadena de ámbitos/TDZ |
| `qa_02b_runtime.js`, `qa_02c_probe.js` | V2 — runtime `node:vm` + probe inyectado en el IIFE |
| `qa_02g_extract_runtime.py`, `qa_02h_e2e.py` | V2 — extracción del JS y E2E ruta→Jinja→JSON→JS |
| `qa_03_final2.py` | V3 — enlaces internos vs. OpenAPI |
| `qa_04_final.py`, `qa_04b_compare.py` | V4 — duplicidad de paleta y comparación contra el SSOT |
| `qa_05_final2.py`, `qa_05b_badge_e2e.py` | V5 — JS huérfano y E2E del badge |
| `qa_jslex3.py` | Lexer Jinja+JS (instrumental compartido) |

---

**Fin del informe.** Resultado global: **4 PASS / 1 FAIL**, con un único hallazgo en `app/api/v1/metricas.py:715-723`.
