# Muestras para Importar tickets

Archivos de ejemplo listos para subir a `/importar-exportar` y probar
los tres formatos soportados (CSV, JSON, TXT). Cada import asigna
automáticamente códigos con prefijo `INC-XXX` alineado con el resto del
proyecto.

## Archivos incluidos

| Archivo | Filas | Notas |
|---------|------:|-------|
| `tickets-ejemplo.csv` | 6 | Formato CSV estándar (UTF-8 con BOM si tu editor lo agrega) |
| `tickets-ejemplo.json` | 3 | Formato JSON con envoltorio `{"tickets": [...]}` |
| `tickets-ejemplo.txt` | 4 | Formato TXT con tabuladores como separador |

## Columnas reconocidas

| Columna | Tipo | Default | Notas |
|---------|------|---------|-------|
| `titulo` | string | **requerido** | Sin `titulo` la fila se reporta como error |
| `descripcion` | string | `""` (vacío) | La columna es NOT NULL en BD |
| `tipo` | enum | `incidencia` | Valores: `incidencia`, `mejora`, `cambio`, `problema` |
| `prioridad` | enum | `media` | Valores: `baja`, `media`, `alta`, `critica` |
| `asignado_username` | string | `null` | Si no existe, se busca por `nombre_completo` |
| `etiquetas` | string | `null` | Separador: `;` o `,` (se aceptan ambos) |

## Cómo probar

1. Inicia sesión como Administrador.
2. Ve a **Más → Importar / Exportar** (o directamente `/importar-exportar`).
3. En el panel **Importar tickets** selecciona uno de los archivos de
   esta carpeta y envíalo.
4. Marca **"Solo validar (no crear)"** la primera vez para ver cuántas
   filas se importarían sin tocar la BD (modo `dry_run`).
5. Si todo se ve bien, desmarca esa casilla y vuelve a enviar.
6. Los tickets creados aparecerán en el Kanban con códigos
   `INC-001`, `INC-002`, ... correlativos al último ID existente.

## Resultado esperado

Tras importar `tickets-ejemplo.csv` (6 filas) sobre una BD limpia, deberías
ver en el Kanban 6 tickets nuevos con códigos `INC-001` ... `INC-006`,
todos en el estado inicial del sistema (p.ej. "Nuevo").
