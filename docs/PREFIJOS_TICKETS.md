# Prefijos de Tickets (Incidencias) — Bitácora GRM v2

**Fecha:** 2026-09-16
**Modelo:** `app/models/ticket.py` → `Ticket.codigo VARCHAR(20) UNIQUE NOT NULL`

---

## Resumen ejecutivo

Al crear un ticket, su `codigo` (legible, único, mostrado al usuario) sigue **uno de DOS formatos** según el `tipo` del ticket:

| # | Tipo de ticket | Formato del código | Ejemplo | Cuándo se usa |
|---|----------------|--------------------|---------|---------------|
| **1** | `incidencia`, `solicitud`, `cambio`, `problema` | `INC-<NNN>` | `INC-001`, `INC-042`, `INC-123` | Default (todos los tipos estándar) |
| **2** | `resultado_pruebas` | `GAR_<HU>_<NNN>` | `GAR_SC_5.4_001`, `GAR_HU12_002` | Cuando es resultado de un caso de prueba/HU específico |

> **Nota histórica:** existía un formato legacy `GRM-INC-YYYY-NNNNNN` (ej: `GRM-INC-2024-000001`) que se **auto-migra** al formato compacto `INC-NNN` en cada arranque (ver `app/db/migrations.py:249-269`).

---

## Detalle de los 2 prefijos activos

### Tipo 1: `INC-<NNN>` (default)

- **Aplicación:** Cualquier `tipo` excepto `resultado_pruebas`.
- **Formato:** `INC-` + correlativo de 3 dígitos (`%03d`).
- **Correlativo:** `max(Ticket.id) + 1` sobre la base. NO es independiente por tipo de ticket.
- **Lógica:** `app/main.py:614-617`

```python
# Formato compacto INC-NNN correlativo por id (igual que antes).
ultimo = db.query(func.max(Ticket.id)).scalar() or 0
codigo = f"INC-{(ultimo + 1):03d}"
```

- **Constraint:** `VARCHAR(20)` → soporta hasta `INC-999999999999999` (15 dígitos).
- **Race condition:** Existe (puede asignar el mismo NNN a dos requests concurrentes). Se mitiga con UNIQUE constraint en BD → el segundo INSERT falla con `IntegrityError`.

### Tipo 2: `GAR_<HU>_<NNN>` (resultado_pruebas)

- **Aplicación:** Solo cuando `tipo == TipoIncidencia.RESULTADO_PRUEBAS`.
- **Requisito:** El campo `hu_o_caso_prueba` es **obligatorio** y se usa como parte del código.
- **Formato:** `GAR_` + `<HU truncado a 12 chars>` + `_` + correlativo de 3 dígitos POR HU.
- **Correlativo:** cuenta cuántos tickets con `tipo=resultado_pruebas` y misma HU ya existen.
- **Lógica:** `app/main.py:559-613`

```python
if tipo_enum == TipoIncidencia.RESULTADO_PRUEBAS:
    # Contar tickets previos con la misma HU y tipo=resultado_pruebas
    count_prev = db.query(func.count(Ticket.id)).filter(
        Ticket.tipo == TipoIncidencia.RESULTADO_PRUEBAS,
        Ticket.hu_o_caso_prueba == hu_o_caso_prueba,
    ).scalar() or 0

    # Limitar el código al VARCHAR(20):
    #   "GAR_"   = 4 chars fijos
    #   "_NNN"   = 4 chars fijos
    #   → quedan 12 chars para la HU; el resto se trunca.
    hu_trunc = hu_o_caso_prueba[:12]
    for offset in range(5):
        candidato_num = count_prev + 1 + offset
        candidato = f"GAR_{hu_trunc}_{candidato_num:03d}"
        existe = db.query(Ticket).filter(Ticket.codigo == candidato).first()
        if not existe:
            codigo = candidato
            break
```

- **Constraint:** `VARCHAR(20)` → `GAR_(4) + HU(12) + _(1) + NNN(3) = 20 chars` exactos.
- **Race condition mitigada:** 5 reintentos incrementando el correlativo si hay conflicto.
- **Validación de HU faltante:** si tipo=resultado_pruebas y no hay HU, retorna HTMLResponse 400 con modal de error.

---

## Distinción por tipo de ticket (`TipoIncidencia` enum)

Definido en `app/models/ticket.py:30-35`:

```python
class TipoIncidencia(str, enum.Enum):
    INCIDENCIA = "incidencia"           # → INC-NNN
    SOLICITUD = "solicitud"             # → INC-NNN
    CAMBIO = "cambio"                   # → INC-NNN
    PROBLEMA = "problema"               # → INC-NNN
    RESULTADO_PRUEBAS = "resultado_pruebas"  # → GAR_<HU>_<NNN>
```

---

## Formato legacy (deprecado)

### `GRM-INC-YYYY-NNNNNN`

- **Origen:** Versiones iniciales del proyecto (ej: `GRM-INC-2024-000001`).
- **Estado:** Auto-migrado al formato `INC-NNN` compacto.
- **Lógica de migración:** `app/db/migrations.py:221-269`

```python
# 4.2) Renombrar codigos existentes GRM-INC-YYYY-NNNNNN → INC-NNN
#      Solo afecta a los codigos que aún tengan el prefijo antiguo.
SET codigo = 'INC-' || CAST(CAST(SUBSTRING(codigo FROM '([0-9]+)$') AS INTEGER) AS TEXT)
WHERE codigo ~ '^GRM-INC-[0-9]{4}-[0-9]+$'
```

- **Disparo:** Cada vez que la aplicación arranca, vía `apply_migrations()` (llamado desde `app/main.py:49-50`).

---

## Ejemplos visuales

### Crear ticket tipo `incidencia` (Tipo 1)

| Campo valor | Código generado |
|-------------|-----------------|
| max(id)=0 | `INC-001` |
| max(id)=41 | `INC-042` |
| max(id)=999 | `INC-1000` |

### Crear ticket tipo `resultado_pruebas` (Tipo 2)

| `hu_o_caso_prueba` | Pre-existentes con esa HU | Código generado |
|--------------------|----------------------------|------------------|
| `SC_5.4` | 0 | `GAR_SC_5.4_001` |
| `SC_5.4` | 2 | `GAR_SC_5.4_003` |
| `HU_muy_larga_2024_q1` (19 chars) | 0 | `GAR_HU_muy_larg_001` (HU truncada a 12) |
| (vacío) | — | **400 error**: "Falta HU o Caso de Prueba" |

---

## Reglas de validación

1. **Unicidad:** `codigo VARCHAR(20) UNIQUE NOT NULL` (`app/models/ticket.py:86`).
2. **Tipo=resultado_pruebas → HU obligatoria:** `app/main.py:560-575` retorna HTMLResponse 400 si falta.
3. **No-op en migración:** solo afecta `codigo` que matchean regex legacy `^GRM-INC-[0-9]{4}-[0-9]+$`.

---

## Archivos relevantes

| Archivo | Líneas | Responsabilidad |
|---------|--------|-----------------|
| `app/models/ticket.py` | 86 | Definición `codigo` (VARCHAR(20) UNIQUE) |
| `app/models/ticket.py` | 30-35 | Enum `TipoIncidencia` |
| `app/main.py` | 547-617 | Lógica principal de generación al crear ticket vía POST |
| `app/services/ticket_service.py` | 397-405 | Helper `generar_codigo()` (correlativo por id) |
| `app/api/v1/tickets.py` | 1145-1147 | Generación al duplicar ticket |
| `app/api/v1/import_export.py` | 269 | Generación al importar desde CSV |
| `app/db/init_db.py` | 278 | Generación al hacer seed |
| `app/db/migrations.py` | 221-269 | Migración automática del formato legacy |
