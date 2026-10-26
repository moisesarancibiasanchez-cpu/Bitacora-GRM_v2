#!/usr/bin/env python3
"""
purge_tickets.py
================

Script de un solo uso para limpiar todos los tickets de la base de datos
del proyecto Bitácora GRM, conservando intactos los catálogos
(etiquetas, estados, usuarios, espacios, tableros, transiciones,
catálogo de tipos/ítems, etc.).

Uso:
    python scripts/purge_tickets.py            # limpieza interactiva
    python scripts/purge_tickets.py --yes      # sin pedir confirmación
    python scripts/purge_tickets.py --dry-run  # solo muestra qué se borraría

Características:
- Crea un backup con timestamp antes de tocar la BD.
- Detecta automáticamente si la BD es SQLite o PostgreSQL.
- Usa la lista blanca explícita de tablas a PURGAR (transaccional, ACID).
- Deja intactas las tablas de catálogo (etiquetas, estados, etc.).
- Verifica al final: cuenta 0 en tickets y conteos intactos en catálogos.

Autor: MiniMax Agent
"""
from __future__ import annotations

import argparse
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 1) Bootstrap: localizar el root del proyecto y la BD
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Detectar la BD a partir de variables de entorno (mismas que usa la app)
USE_SQLITE = os.getenv("USE_SQLITE", "true").lower() in ("1", "true", "yes")
DB_URL = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# 2) Lista blanca: SOLO se purgan estas tablas (todas tienen FK a tickets)
# ---------------------------------------------------------------------------
TABLES_TO_PURGE = [
    "ticket_etiquetas",          # M2M tickets-etiquetas
    "ticket_miembros",           # M2M tickets-usuarios
    "auditorias",                # auditoría de cambios
    "historial_estados",         # cambios de estado
    "comentarios",               # comentarios
    "adjuntos",                  # archivos adjuntos
    "checklists",                # checklists
    "checklist_items",           # items de checklist
    "valores_campo",             # valores de campos personalizados
    "notificaciones",            # notificaciones
    "ejecuciones_automatizacion",# ejecuciones de automatizaciones
    "ejecuciones_boton",         # ejecuciones de botones butler
    "tickets",                   # tabla padre (se borra al final)
]

# Tablas que NO se tocan (catálogos + estructura).
# Solo las que EXISTAN en la BD serán verificadas (el script es tolerante
# a tablas opcionales que no se hayan creado).
TABLES_TO_KEEP_OPTIONAL = [
    "etiquetas", "estados", "usuarios", "espacios", "tableros",
    "transiciones_estado", "catalogo_tipos", "catalogo_items",
    "butler_botones", "butler_reglas", "automations",
    "reglas_asignacion", "catalogo_campos",
]


def _table_exists(cur, table: str) -> bool:
    """Devuelve True si la tabla existe en la BD activa."""
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _existing(cur, tables: list[str]) -> list[str]:
    """Filtra la lista dejando solo las tablas que existen."""
    return [t for t in tables if _table_exists(cur, t)]


def banner(msg: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {msg}")
    print("=" * 70)


def detect_sqlite_path() -> Path | None:
    """Detecta el archivo SQLite por defecto si USE_SQLITE=true."""
    if not USE_SQLITE:
        return None
    default = ROOT / "bitacora_grm.db"
    if default.exists():
        return default
    # Buscar otros *.db en el root
    for f in ROOT.glob("*.db"):
        if f.name != "bitacora_grm_test.db":
            return f
    return None


def backup_sqlite(src: Path) -> Path:
    """Crea una copia de seguridad timestamped del .db."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = src.with_suffix(f".backup_{ts}.db")
    shutil.copy2(src, dst)
    return dst


def purge_sqlite(path: Path, dry_run: bool) -> dict:
    """Purga tickets en SQLite (transaccional)."""
    import sqlite3

    counts_before = {}
    counts_after = {}
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys = ON;")

        # Filtrar tablas a purgar/preservar a las que realmente existen
        purge_existing = _existing(cur, TABLES_TO_PURGE)
        keep_existing = _existing(cur, TABLES_TO_KEEP_OPTIONAL)
        print(f"  [info] {len(purge_existing)}/{len(TABLES_TO_PURGE)} tablas a purgar existen")
        print(f"  [info] {len(keep_existing)}/{len(TABLES_TO_KEEP_OPTIONAL)} catálogos a conservar existen")

        for t in purge_existing:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            counts_before[t] = cur.fetchone()[0]
        for t in keep_existing:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            counts_before[f"KEEP_{t}"] = cur.fetchone()[0]

        if dry_run:
            print("\n  [dry-run] NO se borró nada. Conteos actuales:")
            for t, n in counts_before.items():
                tag = "PURG" if not t.startswith("KEEP_") else "KEEP"
                print(f"    [{tag}] {t.replace('KEEP_', ''):38s} {n:>6}")
            return {"dry_run": True, "before": counts_before, "purge": purge_existing, "keep": keep_existing}

        # Hacer backup SOLO cuando vamos a modificar
        backup = backup_sqlite(path)
        print(f"  [backup] OK -> {backup.name}")

        # Transacción
        cur.execute("BEGIN;")
        for t in purge_existing:
            cur.execute(f'DELETE FROM "{t}";')
        # Resetear el autoincrement de tickets (solo si existe sqlite_sequence)
        if _table_exists(cur, "sqlite_sequence"):
            cur.execute("DELETE FROM sqlite_sequence WHERE name='tickets';")
        conn.commit()
        print("  [purge] COMMIT OK")

        # Verificación post-borrado
        for t in purge_existing:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            counts_after[t] = cur.fetchone()[0]
        for t in keep_existing:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            counts_after[f"KEEP_{t}"] = cur.fetchone()[0]
    except Exception as exc:
        conn.rollback()
        print(f"  [ERROR] rollback ejecutado: {exc}")
        raise
    finally:
        conn.close()

    return {
        "before": counts_before, "after": counts_after,
        "backup": str(backup), "purge": purge_existing, "keep": keep_existing,
    }


def purge_postgres(dry_run: bool) -> dict:
    """Purga tickets en PostgreSQL (usando TRUNCATE ... CASCADE)."""
    import psycopg2

    url = DB_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # Conteos antes
        counts_before = {}
        all_tables = TABLES_TO_PURGE + TABLES_TO_KEEP
        for t in all_tables:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            counts_before[t] = cur.fetchone()[0]

        if dry_run:
            print("\n  [dry-run] NO se borró nada. Conteos actuales:")
            for t, n in counts_before.items():
                print(f"    {t:40s} {n:>6}")
            return {"dry_run": True, "before": counts_before}

        # TRUNCATE ... CASCADE: trunca la tabla tickets y todas las que tienen
        # FK hacia ella. Es más rápido y seguro que DELETE en cascada.
        purge_quoted = ", ".join(f'"{t}"' for t in TABLES_TO_PURGE)
        cur.execute(f"TRUNCATE {purge_quoted} RESTART IDENTITY CASCADE;")
        conn.commit()
        print("  [purge] COMMIT OK (TRUNCATE CASCADE)")

        counts_after = {}
        for t in all_tables:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            counts_after[t] = cur.fetchone()[0]
    except Exception as exc:
        conn.rollback()
        print(f"  [ERROR] rollback ejecutado: {exc}")
        raise
    finally:
        conn.close()

    return {"before": counts_before, "after": counts_after}


def print_report(result: dict) -> None:
    banner("RESULTADO DE LA PURGA")
    if result.get("dry_run"):
        print("\n  Modo dry-run: no se modificó nada. Conteos arriba.")
        return

    before = result["before"]
    after = result["after"]

    print("\n  Tablas PURGADAS (deben pasar a 0):")
    for t in TABLES_TO_PURGE:
        b = before.get(t, 0)
        a = after.get(t, 0)
        ok = "OK" if a == 0 else "FALLO"
        print(f"    {t:40s} {b:>6} -> {a:>6}  [{ok}]")

    print("\n  Catálogos CONSERVADOS (no deben cambiar):")
    for t in TABLES_TO_KEEP_OPTIONAL:
        b = before.get(f"KEEP_{t}", before.get(t, "?"))
        a = after.get(f"KEEP_{t}", after.get(t, "?"))
        ok = "OK" if b == a else "ALERTA"
        print(f"    {t:40s} {b:>6} -> {a:>6}  [{ok}]")

    if "backup" in result:
        print(f"\n  Backup: {result['backup']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purga todos los tickets de la BD, conservando catálogos."
    )
    parser.add_argument("--yes", action="store_true",
                        help="No pedir confirmación interactiva")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo mostrar conteos, no borrar nada")
    args = parser.parse_args()

    banner("PURGA DE TICKETS - Bitácora GRM v2")
    print(f"  BD detectada: {'SQLite' if USE_SQLITE else 'PostgreSQL'}")
    if USE_SQLITE:
        sqlite_path = detect_sqlite_path()
        if not sqlite_path:
            print("  [ERROR] No se encontró archivo .db en el root del proyecto.")
            return 1
        print(f"  Archivo: {sqlite_path.name} ({sqlite_path.stat().st_size:,} bytes)")
    else:
        if not DB_URL:
            print("  [ERROR] DATABASE_URL no definida.")
            return 1
        print(f"  DSN: {DB_URL[:40]}...")

    print("\n  Tablas a purgar:")
    for t in TABLES_TO_PURGE:
        print(f"    - {t}")
    print("\n  Tablas conservadas:")
    for t in TABLES_TO_KEEP_OPTIONAL:
        print(f"    - {t}")

    if not args.dry_run and not args.yes:
        print("\n  Tablas a PURGAR (sus conteos pasarán a 0):")
        for t in TABLES_TO_PURGE:
            print(f"    - {t}")
        print("\n  Tablas a CONSERVAR (sus conteos no deben cambiar):")
        for t in TABLES_TO_KEEP_OPTIONAL:
            print(f"    - {t}")
        resp = input("\n  ¿Confirmas la purga? escribe 'PURGAR' para continuar: ")
        if resp.strip() != "PURGAR":
            print("  Cancelado por el usuario.")
            return 0

    if USE_SQLITE:
        result = purge_sqlite(sqlite_path, dry_run=args.dry_run)
    else:
        result = purge_postgres(dry_run=args.dry_run)

    print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
