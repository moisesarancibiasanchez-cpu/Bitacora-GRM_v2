#!/usr/bin/env python3
"""
Backfill one-shot: setea fecha_completado = NOW() (UTC) a todos los tickets
no archivados que están en estado 'Producción OK' y aún tienen
fecha_completado = NULL.

Uso:
  python scripts/backfill_produccion_ok.py            # preview (no modifica nada)
  python scripts/backfill_produccion_ok.py --apply    # ejecuta el UPDATE

El script:
  - Lee DATABASE_URL del entorno (o RAILWAY_DATABASE_URL como fallback).
  - Calcula 'Producción OK' por categoria = 'produccion_ok' (mismo criterio
    que el side-effect en ticket_service.py).
  - Solo actualiza tickets con fecha_completado IS NULL (no sobrescribe).
  - Solo actualiza tickets no archivados (archivado = false).
  - Ejecuta en una transacción; commit solo si todo el batch se aplicó.
  - Loguea IDs antes y después, conteo de filas afectadas.
"""
import os
import sys
import argparse
from datetime import datetime, timezone
from sqlalchemy import create_engine, text


def get_db_url() -> str:
    url = os.environ.get('DATABASE_URL') or os.environ.get('RAILWAY_DATABASE_URL')
    if not url:
        print('ERROR: ni DATABASE_URL ni RAILWAY_DATABASE_URL están definidas.')
        sys.exit(1)
    return url


def preview(engine) -> list:
    """Devuelve los tickets que serían actualizados (sin modificar nada)."""
    sql = text("""
        SELECT
            t.id,
            t.codigo,
            t.titulo,
            t.fecha_vencimiento_sla,
            t.fecha_completado,
            t.sla_cumplido,
            t.archivado
        FROM tickets t
        JOIN estados e ON e.id = t.estado_id
        WHERE e.categoria = 'produccion_ok'
          AND t.archivado = false
          AND t.fecha_completado IS NULL
        ORDER BY t.id
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return [dict(r) for r in rows]


def total_produccion_ok(engine) -> tuple:
    """(total_prod_ok, sin_fecha_completado, con_fecha_completado) no archivados."""
    sql = text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE t.fecha_completado IS NULL) AS sin_completado,
            COUNT(*) FILTER (WHERE t.fecha_completado IS NOT NULL) AS con_completado
        FROM tickets t
        JOIN estados e ON e.id = t.estado_id
        WHERE e.categoria = 'produccion_ok' AND t.archivado = false
    """)
    with engine.connect() as conn:
        row = conn.execute(sql).one()
    return row.total, row.sin_completado, row.con_completado


def apply_backfill(engine) -> int:
    """Setea fecha_completado = NOW() (UTC) en una transacción.

    Devuelve el número de filas afectadas.
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC

    update_sql = text("""
        UPDATE tickets
        SET fecha_completado = :now_utc
        WHERE id IN (
            SELECT t.id FROM tickets t
            JOIN estados e ON e.id = t.estado_id
            WHERE e.categoria = 'produccion_ok'
              AND t.archivado = false
              AND t.fecha_completado IS NULL
        )
    """)

    with engine.begin() as conn:  # transacción
        result = conn.execute(update_sql, {'now_utc': now_utc})
    return result.rowcount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help='Ejecuta el UPDATE. Sin este flag solo muestra preview.')
    args = ap.parse_args()

    url = get_db_url()
    # Enmascarar password en el log
    masked = url.split('@')[-1] if '@' in url else url
    print(f'[conectando] host:port/db = {masked}')

    engine = create_engine(url, echo=False, future=True)

    print()
    print('=' * 70)
    print('PREVIEW: estado actual de tickets en "Producción OK" (no archivados)')
    print('=' * 70)
    total, sin, con = total_produccion_ok(engine)
    print(f'  Total en Producción OK:                {total}')
    print(f'  Con fecha_completado NULL (a backfill): {sin}')
    print(f'  Con fecha_completado seteada:           {con}')

    candidates = preview(engine)
    print()
    print(f'  Candidatos a actualizar: {len(candidates)}')
    for r in candidates[:20]:
        print(f'    - id={r["id"]:>4}  {r["codigo"]:<12}  '
              f'vencimiento_sla={r["fecha_vencimiento_sla"]}  '
              f'sla_cumplido={r["sla_cumplido"]}')
    if len(candidates) > 20:
        print(f'    ... y {len(candidates) - 20} más')

    if not candidates:
        print()
        print('Nada que actualizar — todos los tickets en Producción OK ya '
              'tienen fecha_completado seteada.')
        return 0

    if not args.apply:
        print()
        print('=' * 70)
        print('MODO PREVIEW (no se aplicó ningún cambio).')
        print('Para ejecutar el UPDATE, re-correr con --apply')
        print('=' * 70)
        return 0

    print()
    print('=' * 70)
    print('EJECUTANDO UPDATE ...')
    print('=' * 70)
    affected = apply_backfill(engine)
    print(f'  Filas actualizadas: {affected}')

    # Verificación post-update
    print()
    print('=' * 70)
    print('VERIFICACIÓN POST-UPDATE')
    print('=' * 70)
    total2, sin2, con2 = total_produccion_ok(engine)
    print(f'  Antes:   {sin} sin fecha_completado, {con} con')
    print(f'  Después: {sin2} sin fecha_completado, {con2} con')
    assert sin2 == 0, f'Quedan {sin2} tickets sin fecha_completado — REVISAR'
    print('  OK   cero tickets en Producción OK sin fecha_completado')

    # Verificación del KPI Tickets Vencidos
    print()
    print('KPI "Tickets vencidos" después del fix:')
    kpi_sql = text("""
        SELECT COUNT(*)
        FROM tickets t
        WHERE t.fecha_completado IS NULL
          AND t.fecha_vencimiento_sla IS NOT NULL
          AND t.fecha_vencimiento_sla < NOW()
          AND t.archivado = false
          AND (
            UPPER(t.tipo::text) = 'INCIDENCIA'
            OR t.codigo ILIKE 'INC-%'
            OR t.codigo ILIKE 'INC\\_%' ESCAPE '\\'
          )
    """)
    with engine.connect() as conn:
        kpi_vencidos = conn.execute(kpi_sql).scalar() or 0
    print(f'  tickets_vencidos = {kpi_vencidos}')
    print()
    print('Backfill completado exitosamente.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
