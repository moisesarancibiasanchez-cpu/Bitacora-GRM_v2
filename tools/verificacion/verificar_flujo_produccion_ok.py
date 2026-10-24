# -*- coding: utf-8 -*-
"""Verifica el flujo de "Produccion OK" sobre una base SEMBRADA desde cero.

Este es el caso donde el bug de tildes mordia: el seed de
app/db/init_db.py inserta el estado con el nombre canonico "Produccion OK"
(CON tilde), mientras que el pre-check de la migracion 4.6 comparaba contra
'produccion ok' (SIN tilde). La comparacion nunca coincidia, de modo que la
migracion intentaba insertar un duplicado (chocando con el indice UNIQUE de
estados.nombre) y las 3 transiciones del flujo nunca se creaban.

El script monta una base SQLite en memoria con el esquema real, corre las
migraciones y comprueba el resultado del flujo.

Contrasta con verificar_flujo_produccion.py, que hace lo mismo pero contra
la base de PRODUCCION, donde el flujo es propio (estado "produccion ok" sin
tilde) y ya estaba configurado.

No toca ninguna base de datos real: todo corre en memoria.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
import types

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# ``app.db.__init__`` importa app.db.session, que crea el engine real
# (PostgreSQL) y exige psycopg2. Se inyecta un paquete stub para cargar
# ``app.db.base`` sin ejecutar ese __init__.
for _nombre, _ruta in (("app", os.path.join(RAIZ, "app")),
                       ("app.db", os.path.join(RAIZ, "app", "db"))):
    if _nombre not in sys.modules:
        _mod = types.ModuleType(_nombre)
        _mod.__path__ = [_ruta]
        sys.modules[_nombre] = _mod

from sqlalchemy import create_engine, text  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_base", os.path.join(RAIZ, "app", "db", "base.py"))
base = importlib.util.module_from_spec(_spec)
sys.modules["_base"] = base
_spec.loader.exec_module(base)

_spec_mig = importlib.util.spec_from_file_location(
    "_mig", os.path.join(RAIZ, "app", "db", "migrations.py"))
mig = importlib.util.module_from_spec(_spec_mig)
sys.modules["_mig"] = mig
_spec_mig.loader.exec_module(mig)

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def _esquema(engine):
    with engine.begin() as conn:
        for stmt in (
            """CREATE TABLE estados (id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre VARCHAR(80) NOT NULL UNIQUE, descripcion TEXT, color VARCHAR(20),
                orden INTEGER, es_inicial BOOLEAN DEFAULT 0, es_final BOOLEAN DEFAULT 0,
                categoria VARCHAR(40), sla_horas INTEGER, archivado BOOLEAN DEFAULT 0,
                limite_wip INTEGER, es_entrega BOOLEAN DEFAULT 0,
                created_at VARCHAR(50), updated_at VARCHAR(50))""",
            """CREATE TABLE transiciones_estado (id INTEGER PRIMARY KEY AUTOINCREMENT,
                estado_origen_id INTEGER NOT NULL, estado_destino_id INTEGER NOT NULL,
                rol_requerido VARCHAR(40), requiere_comentario BOOLEAN DEFAULT 0,
                descripcion TEXT, UNIQUE (estado_origen_id, estado_destino_id))""",
            """CREATE TABLE etiquetas (id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre VARCHAR(80) NOT NULL, descripcion TEXT, color VARCHAR(20),
                categoria VARCHAR(40), activo BOOLEAN NOT NULL DEFAULT 1,
                created_at VARCHAR(50), updated_at VARCHAR(50))""",
            """CREATE TABLE etapas_proyecto (id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo VARCHAR(40) NOT NULL UNIQUE, nombre VARCHAR(120) NOT NULL,
                orden INTEGER NOT NULL, color VARCHAR(7), activo INTEGER NOT NULL DEFAULT 1,
                created_at VARCHAR(50), updated_at VARCHAR(50))""",
        ):
            conn.execute(text(stmt))
        # Estados del SEED (app/db/init_db.py): nombres canonicos CON tilde.
        for nombre, orden, categoria, final in (
            ("Nuevo", 1, "abierto", 0),
            ("En Curso", 2, "abierto", 0),
            ("En Revisión", 3, "abierto", 0),
            ("Resuelto", 4, "cerrado", 0),
            ("Cerrado", 5, "cerrado", 1),
            ("Cancelado", 6, "cerrado", 1),
            ("Producción OK", 7, "produccion_ok", 1),
        ):
            conn.execute(text(
                "INSERT INTO estados (nombre, descripcion, color, orden, es_inicial, "
                "es_final, categoria, sla_horas, archivado, limite_wip, es_entrega, "
                "created_at, updated_at) VALUES (:n, 'seed', '#6b7280', :o, 0, :f, :c, "
                "NULL, 0, NULL, 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ), {"n": nombre, "o": orden, "c": categoria, "f": final})


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    engine = create_engine("sqlite://")
    _esquema(engine)

    with engine.begin() as conn:
        mig._apply_data_migrations(conn, engine)

    with engine.connect() as conn:
        estados = conn.execute(text(
            "SELECT id, nombre FROM estados WHERE LOWER(nombre) LIKE '%producci%'"
        )).fetchall()
        filas = conn.execute(text(
            "SELECT o.nombre, d.nombre FROM transiciones_estado t "
            "JOIN estados o ON o.id = t.estado_origen_id "
            "JOIN estados d ON d.id = t.estado_destino_id "
            "WHERE o.nombre LIKE '%roducci%' OR d.nombre LIKE '%roducci%'"
        )).fetchall()

    nombres = [f[1] for f in estados]
    print("      estados de produccion hallados: %r" % nombres)
    print("      transiciones del flujo: %r" % (sorted(filas),))

    _check("el estado 'Produccion OK' existe una sola vez",
           nombres.count("Producción OK") == 1, "veces=%d" % nombres.count("Producción OK"))
    _check("no se creo un homonimo sin tilde", "produccion ok" not in nombres, "")
    _check("no se creo un duplicado con otro nombre",
           len(nombres) == 1, "encontrados=%r" % nombres)

    esperados = {("Cerrado", "Producción OK"),
                 ("Producción OK", "Cerrado"),
                 ("Producción OK", "En Curso")}
    _check("las 3 transiciones del flujo se crearon", esperados.issubset(set(filas)),
           "faltan=%r" % sorted(esperados - set(filas)))

    # Idempotencia: una segunda pasada no debe duplicar nada.
    with engine.begin() as conn:
        mig._apply_data_migrations(conn, engine)
    with engine.connect() as conn:
        n_est = conn.execute(text(
            "SELECT COUNT(*) FROM estados WHERE LOWER(nombre) LIKE '%producci%'"
        )).scalar()
        n_tr = conn.execute(text(
            "SELECT COUNT(*) FROM transiciones_estado t "
            "JOIN estados o ON o.id = t.estado_origen_id "
            "JOIN estados d ON d.id = t.estado_destino_id "
            "WHERE o.nombre LIKE '%roducci%' OR d.nombre LIKE '%roducci%'"
        )).scalar()
    _check("idempotencia: no se duplica el estado en la 2da pasada", n_est == 1,
           "n=%s" % n_est)
    _check("idempotencia: no se duplican las transiciones", n_tr == 3, "n=%s" % n_tr)

    print("")
    if FALLOS:
        print("RESULTADO FLUJO SEMBRADO: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO FLUJO SEMBRADO: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
