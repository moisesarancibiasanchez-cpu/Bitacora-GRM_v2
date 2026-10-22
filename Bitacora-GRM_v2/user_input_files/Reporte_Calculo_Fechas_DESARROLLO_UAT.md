# Cálculo de Fechas Individuales de DESARROLLO por Caso de Prueba UAT

**Proyecto:** PLAN-PMO-70418 GRM – HU Postergadas a Garantía (Inicio 11-Sep)
**Origen datos:**
- `Consolidado_UAT_Cruce_GARANTIA_v3.xlsx` → hoja **CONSOLIDADO UAT** (912 casos)
- `20260928-PLAN-PMO-70418 GRM.xml` → 160 tareas (OutlineLevel 0-5)

## Objetivo

Reemplazar la planificación Gantt **a nivel de módulo** por una asignación **caso por caso**: cada caso de prueba recibe una fecha de inicio y fin de DESARROLLO individual, calculada distribuyendo proporcionalmente el rango de fechas del HU-grupo (PMO 70418) al que pertenece.

## Algoritmo

1. **Parseo de HU-grupos (OutlineLevel 4)** del XML MS Project:
   - Extrae la lista de códigos HU del nombre del grupo, p.ej.
     `OK con OBS: G_12_ RI_49.2` → `['G_12', 'RI_49.2']`.
   - Para cada grupo, identifica la sub-tarea `Desarrollo` (OL=5) y toma
     su `Start` / `Finish` como rango canónico de DESARROLLO.
2. **Fallback a nivel módulo (OL=3)** cuando un caso no calza con ningún
   HU-grupo OL=4 — usa el rango del grupo del módulo correspondiente.
3. **Distribución uniforme** del rango `[dev_start, dev_finish]` entre los
   casos que comparten el mismo `CodigoHU` (peers):
   - `dias_por_caso = total_dias / N_peers`
   - Caso `i` recibe `[inicio + i·step, inicio + (i+1)·step − 1]`
   - Esto preserva la duración total planificada del PMO.
4. **Módulo derivado del prefijo del HU** (RI→Registro Información,
   V→Validación, SC→Seguimiento y Control, MT→Mejoras Transversales,
   G→Gobierno, D→Documentación, IN→Incidencias, II→Información
   Inventario, F→Filiales).

## Resultados globales

| Métrica | Valor |
|---|---:|
| Total casos UAT (XLSX) | 912 |
| Casos con fecha DESARROLLO asignada | 851 (93.3%) |
| Casos sin match (sin fecha) | 61 (6.7%) |
| HU-grupos (OL=4) detectados en XML | 22 |
| Grupos módulo-level (OL=3) usados como fallback | 9 |

## Distribución por módulo

| Módulo | Casos | Rango DESARROLLO | Duración prom. | HU-grupo base |
|---|---:|---|---:|---|
| Registro Información | 188 | 2026-10-02 → 2026-11-18 | 12.0 d | 27 Casos Registro Información |
| Validación | 174 | 2026-09-21 → 2026-10-01 | 3.2 d | 14 Casos Validación- OK con OBS |
| Seguimiento y Control | 148 | 2026-09-17 → 2026-11-03 | 15.2 d | 27 Casos Seguimiento y Control |
| Mejoras Transversales | 146 | 2026-09-23 → 2026-11-30 | 18.4 d | 47 Casos Mejoras trasnversales |
| Información Inventario | 54 | 2026-09-22 → 2026-09-28 | 2.2 d | 4 Casos Información inventario - OK con OBS |
| Gobierno | 48 | 2026-09-11 → 2026-09-22 | 3.2 d | 1 Caso Gobierno OK con OBS |
| Incidencias | 38 | 2026-09-04 → 2026-09-09 | 1.5 d | Atenciones de Incidencias PAP |
| Documentación | 32 | 2026-11-25 → 2026-12-03 | 2.0 d | Documentación Actualización |
| Filiales | 23 | 2026-09-11 → 2026-09-23 | 6.2 d | 3 Casos Filiales OK con OBS |

## HU-grupos (OL=3) efectivamente utilizados

- `1 Caso Gobierno OK con OBS`
- `14 Casos Validación- OK con OBS`
- `27 Casos Registro Información`
- `27 Casos Seguimiento y Control`
- `3 Casos Filiales OK con OBS`
- `4 Casos Información inventario - OK con OBS`
- `47 Casos Mejoras trasnversales`
- `Atenciones de Incidencias PAP`
- `Documentación Actualización`

## Observaciones importantes

- **Cobertura**: 851 de 912 casos (93.3%) reciben fecha. Los 61 casos
  sin match corresponden a HUs que no aparecen explícitamente en el
  XML PMO (p.ej. HU `Coordinacion PAP`, `Ejecución PAP`, sub-tareas
  individuales como `Pruebas Internas`, `Entrega y despliegue en QA`,
  `Reuniones de Revisión UAT`, etc., que NO son HUs funcionales).
- **Distribución uniforme**: el rango de fechas del HU-grupo se reparte
  equitativamente entre sus casos. No se aplica aún ponderación por
  Criticidad (ALTA/MEDIA/BAJA) — esa mejora se puede agregar
  posteriormente si se requiere granularidad por prioridad.
- **Módulo Gobierno** (48 casos) usa el rango del grupo OL=3
  `1 Caso Gobierno OK con OBS` (2026-09-11 → 2026-09-23). El HU-grupo
  OL=4 correspondiente (`OK con OBS: G_12_ RI_49.2`) tiene fechas
  idénticas, por lo que el resultado es equivalente.
- **Rangos OL=3 fuente**: el rango `[dev_start, dev_finish]` a nivel
  módulo se tomó del grupo OL=3 correspondiente, NO de la sub-tarea
  `Desarrollo` (puesto que a OL=3 no hay sub-tareas explícitas). Esto
  puede sobre-asignar días respecto al desarrollo puro, pero mantiene
  coherencia con el span planificado por módulo en el PMO.

## Artefactos

- **CSV por caso**: `/workspace/user_input_files/Calculo_Fechas_DESARROLLO_por_Caso_UAT.csv`
  - 851 filas + encabezado
  - Columnas: `['caso_idx', 'modulo', 'hu_group_pm70418', 'codigo_hu', 'codigo_caso', 'caso_prueba', 'resultado', 'prioridad', 'criticidad', 'fecha_dev_inicio', 'fecha_dev_fin', 'duracion_dias', 'hu_group_inicio', 'hu_group_fin', 'pos_entre_peers', 'peers_mismo_hu']`
  - Ordenado por: módulo → hu_group → fecha_inicio → codigo_caso
- **JSON bruto**: `/tmp/uat_case_dates.json` (estructura completa)

## Próximos pasos sugeridos

1. **Importar al modelo Ticket**: agregar un script que, leyendo este CSV,
   actualice los campos `fecha_inicio` / `fecha_vencimiento_sla` de los
   tickets cuya etiqueta coincide con `Codigo Caso Prueba`.
2. **Refinar distribución**: ponderar por Criticidad (ALTA→×1.5, MEDIA→×1,
   BAJA→×0.7) si se requiere granularidad por prioridad.
3. **Resolver los 61 casos sin match**: revisar manualmente o extender el
   parser de HUs para reconocer formatos adicionales (rangos `63-67`,
   HUs con sub-versiones, etc.).
4. **Integrar al PAGE Gantt**: la columna `hu_o_caso_prueba` del Ticket
   ya soporta este nivel de detalle; el frontend sólo debe renderizar
   cada caso como una sub-barra dentro del módulo.
