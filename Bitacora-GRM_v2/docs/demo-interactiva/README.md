# Demo Interactiva — Bitácora GRM v2

Esta carpeta contiene la **demo interactiva 100% cliente** de Bitácora GRM.
Es un único archivo HTML autocontenido (sin dependencias de build, sin
backend) que simula el comportamiento de la aplicación real.

## ¿Qué incluye?

- **Tablero Kanban** con drag & drop (SortableJS)
- **Modales de detalle** con 4 pestañas: Detalle, Comentarios, Adjuntos, Checklist
- **Creación de tickets** con validaciones LOV (módulo, ambiente, ítem, etc.)
- **Tipos de tickets**: Incidencia, Solicitud, Cambio, Problema, Resultado Pruebas
- **Vista Dashboard** con KPIs, gráfico de actividad, top agentes
- **Vista Tabla**, **Calendario**, **Cronograma**, **Panel (Trello)**
- **Sistema de etiquetas**, prioridades, asignaciones
- **Validaciones ITSM**: reglas de transición entre estados (la tarjeta
  "vuelve sola" a su columna origen si el movimiento no está permitido)
- **Filtros combinables**: texto, prioridad, asignado, etiqueta, estado
- **Auditoría**: cada acción queda registrada en una mini-bitácora
- **Notificaciones/toasts** al estilo HTMX

## ¿Cómo se usa?

1. Abrí el archivo `index.html` directamente en el navegador (doble clic),
   o servilo desde cualquier servidor estático.
2. Explorá el tablero, hacé click en una tarjeta para abrir el detalle,
   arrastrá una tarjeta a otra columna para simular un cambio de estado.
3. Abrí la consola del navegador para ver los `console.log` con cada acción
   registrada.

## Demo online

La versión más reciente está desplegada en:

- **Espacio mcode (oficial):** https://yxw2tv4akaiw.space.mcode.io

## Estructura del archivo

| Sección                  | Líneas aprox. | Descripción                              |
|--------------------------|---------------|------------------------------------------|
| `<style>`                | 12 – 34       | Estilos base (Tailwind + custom)         |
| Top bar                  | 39 – 53       | Encabezado con indicador de backend      |
| Kanban board             | 56 – 64       | Contenedor del tablero                   |
| Mock data                | 79 – 150      | Estado en memoria (tickets, estados…)    |
| Utilidades               | 155 – 163     | Helpers (escape, find, fmtBytes…)        |
| Toasts                   | 168 – 188     | Notificaciones tipo HTMX                 |
| Render Kanban            | 193 – 274     | Render de columnas y tarjetas            |
| Validación transición    | 277 – 286     | Simula la regla ITSM del backend         |
| Modal de detalle         | 291 – 700     | 4 pestañas + edición inline              |
| Vista Dashboard          | 720 – 900     | KPIs + Chart.js                          |
| Vista Tabla              | 910 – 1100    | Tabla densa con filtros                  |
| Vista Calendario         | 1110 – 1250   | Tickets agrupados por fecha              |
| Vista Cronograma         | 1260 – 1380   | Gantt con barras por ticket              |
| Vista Panel (Trello)     | 1390 – 1450   | Tableros múltiples estilo Kanban         |
| Bootstrap                | 1470 – 1477   | Inicialización (`DOMContentLoaded`)      |

## Diferencias con la app real

Esta demo es una **simulación visual**. En la app real:

- Los datos se persisten en PostgreSQL, no en memoria.
- El drag & drop dispara una llamada `PATCH /api/v1/tickets/{id}/estado`
  validada en el backend (matriz de transiciones + roles).
- Las notificaciones usan Celery + Redis (no `setTimeout`).
- Los adjuntos se suben a `/uploads/` (no inline en `<iframe>`).

Sirve para mostrar la **UX y el flujo** sin necesidad de desplegar el
backend completo.

## Cómo regenerarla

La demo se genera a partir del mismo set de plantillas + componentes
JS/CSS del backend. Para una versión actualizada:

1. Abrí la app real (`/kanban`, `/dashboard`, etc.).
2. Exportá el DOM renderizado con la extensión "SingleFile".
3. Reemplazá las llamadas a la API por simulaciones locales
   (ver sección "Mock data" del archivo).

O bien, usá esta versión como snapshot estable y actualizala cuando
salga una nueva release del backend.
