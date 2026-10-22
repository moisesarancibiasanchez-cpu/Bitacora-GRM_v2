# Bulk update de fechas para tarjetas `GAR_RI_*` en BACKLOG

## Resumen

Aplicar de forma masiva las fechas de planificación a todas las tarjetas del
prefijo `GAR_RI_` que estén en la columna `BACKLOG`:

- `fecha_inicio = 2026-10-02` (2 de octubre de 2026)
- `fecha_vencimiento_sla = 2026-11-19` (19 de noviembre de 2026)

## Archivos

| Archivo | Propósito |
|---------|-----------|
| `scripts/bulk_update_fechas_gar_ri_backlog.py` | Script CLI principal (dry-run por defecto, `--apply` para aplicar). |
| `app/api/v1/migraciones.py` | Endpoints `POST /gar-ri-fechas-backlog` y `GET /gar-ri-fechas-backlog/preview`. |
| `tests/test_bulk_update_gar_ri.py` | Test E2E con fixtures en BD temporal. |
| `tests/cli_smoke_test.py` | Smoke test del CLI vía `subprocess`. |

## Uso desde la línea de comandos

```bash
# 1) Previsualizar (no modifica nada):
python scripts/bulk_update_fechas_gar_ri_backlog.py
# Equivalente:  --dry-run (default)

# 2) Aplicar:
python scripts/bulk_update_fechas_gar_ri_backlog.py --apply --yes
```

Argumentos disponibles:

```
--prefix GAR_RI_               Prefijo del código del ticket (default: GAR_RI_)
--estado BACKLOG               Nombre del estado (case-insensitive, default: BACKLOG)
--fecha-inicio 2026-10-02      Fecha de inicio YYYY-MM-DD
--fecha-vencimiento 2026-11-19 Fecha SLA YYYY-MM-DD
--apply                        Aplica los cambios (default: dry-run)
--yes                          Omite el prompt interactivo al aplicar
--verbose                      Logging nivel DEBUG
```

## Uso vía API REST (admin only)

### Preview (no aplica cambios)

```http
GET /api/v1/migraciones/gar-ri-fechas-backlog/preview
Authorization: Bearer <admin_token>

200 OK
{
  "prefix": "GAR_RI_",
  "target_inicio": "2026-10-02",
  "target_sla": "2026-11-19",
  "estado_usado": "BACKLOG",
  "estado_id": 5,
  "total_encontrados": 12,
  "ya_con_fechas": 3,
  "serian_actualizados": 9,
  "errores": []
}
```

### Aplicar

```http
POST /api/v1/migraciones/gar-ri-fechas-backlog
Authorization: Bearer <admin_token>

200 OK
{
  "total_encontrados": 12,
  "ya_con_fechas": 3,
  "actualizados": 9,
  "ids_actualizados": [101, 102, 103, ...],
  "ids_ya_con_fechas": [201, 202, 203],
  "ejecutado_en": "2026-09-22T...",
  "dry_run": false,
  "estado_usado": "BACKLOG",
  "estado_id": 5,
  "errores": []
}
```

## Garantías

- **Idempotente**: tickets que ya tienen `fecha_inicio = 2026-10-02` Y `fecha_vencimiento_sla = 2026-11-19` se saltan (no se actualiza ni se insiere auditoría duplicada).
- **Auditado**: cada cambio inserta un registro en `auditoria` con:
  - `accion = "bulk_update_fechas_backlog"`
  - `comentario` incluye el tag `bulk_update_fechas_backlog:v1` para trazabilidad y reversión
  - `valor_anterior` y `valor_nuevo` con ambas fechas en JSON
- **Seguridad**: rollback automático ante cualquier error durante el commit.
- **Admin only**: la API requiere rol `administrador`. El CLI no tiene auth pero debe ejecutarse con acceso a la BD.

## Validación local

```bash
# Test E2E (BD temporal + fixtures + asserts):
python tests/test_bulk_update_gar_ri.py

# Smoke test del CLI (subprocess real):
python tests/cli_smoke_test.py
```

Ambos tests:

- Verifican conteos correctos (total_encontrados, ya_con_fechas, actualizados).
- Confirman que tickets fuera de scope NO se modifican (prefijo distinto, estado distinto).
- Validan la creación de auditoría (1 entrada por cambio, sin duplicados en re-ejecución).
- Cubren casos de error (estado inexistente, rango de fechas inválido).

## Limitaciones / Decisiones

- **No recalcula SLA en background**: si en el futuro se requiere, integrar
  con la tarea Celery `recalcular_sla_ticket.delay(ticket_id)` desde el worker.
- **Búsqueda de estado case-insensitive** pero sin normalización de espacios extra.
  Si hay un estado " BACKLOG " con espacios, no matcheará.
- **Búsqueda de prefijo usa `LIKE 'GAR_RI_%'`**: por diseño matchea también
  códigos como `GAR_RI_FOO` o `GAR_RI_001`. Si se necesita un prefijo más
  estricto, ajustar la query.