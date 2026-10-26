# -*- coding: utf-8 -*-
"""Verificacion REAL (sin mocks) de los arreglos de app/db/migrations.py.

Ejecuta ``_apply_data_migrations`` contra una base SQLite en memoria con el
esquema real de los modelos y comprueba:

1. Aislamiento por SAVEPOINT: un SQL invalido en un paso NO impide que los
   pasos posteriores se ejecuten.
2. 4.3 soft-delete de etiquetas prohibidas (con el literal correcto).
3. 4.6 inserta el estado 'Produccion OK' (con tilde) UNA SOLA VEZ y no
   intenta insertarlo de nuevo en el segundo arranque (bug de acentos).
4. 4.7 crea las 3 transiciones del flujo 'Produccion OK' (antes nunca se
   creaban por el mismo bug de acentos).
5. Idempotencia: la segunda ejecucion no crea duplicados.

No toca ninguna base de datos real: todo corre en memoria.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from sqlalchemy import create_engine, text  # noqa: E402

# ``app/db/__init__.py`` importa ``app.db.session``, que crea el engine real
# (PostgreSQL) y por tanto exige ``psycopg2`` (no instalado aqui). Se inyecta
# un paquete stub para que ``import app.db.base`` resuelva el submodulo sin
# ejecutar ese ``__init__``. No afecta a la logica probada.
import types  # noqa: E402

for _nombre, _ruta in (("app", os.path.join(RAIZ, "app")),
                       ("app.db", os.path.join(RAIZ, "app", "db"))):
    if _nombre not in sys.modules:
        _mod = types.ModuleType(_nombre)
        _mod.__path__ = [_ruta]
        sys.modules[_nombre] = _mod

spec_base = importlib.util.spec_from_file_location(
    "_base", os.path.join(RAIZ, "app", "db", "base.py")
)
base = importlib.util.module_from_spec(spec_base)
sys.modules["_base"] = base
spec_base.loader.exec_module(base)

spec_mig = importlib.util.spec_from_file_location(
    "_mig", os.path.join(RAIZ, "app", "db", "migrations.py")
)
mig = importlib.util.module_from_spec(spec_mig)
sys.modules["_mig"] = mig
spec_mig.loader.exec_module(mig)

FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def _crear_esquema(engine):
    ddl = [
        """CREATE TABLE estados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre VARCHAR(80) NOT NULL UNIQUE,
            descripcion TEXT,
            color VARCHAR(20),
            orden INTEGER,
            es_inicial BOOLEAN DEFAULT 0,
            es_final BOOLEAN DEFAULT 0,
            categoria VARCHAR(40),
            sla_horas INTEGER,
            archivado BOOLEAN DEFAULT 0,
            limite_wip INTEGER,
            es_entrega BOOLEAN DEFAULT 0,
            created_at VARCHAR(50),
            updated_at VARCHAR(50)
        )""",
        """CREATE TABLE transiciones_estado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estado_origen_id INTEGER NOT NULL,
            estado_destino_id INTEGER NOT NULL,
            rol_requerido VARCHAR(40),
            requiere_comentario BOOLEAN DEFAULT 0,
            descripcion TEXT,
            UNIQUE (estado_origen_id, estado_destino_id)
        )""",
        """CREATE TABLE etiquetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre VARCHAR(80) NOT NULL,
            descripcion TEXT,
            color VARCHAR(20),
            categoria VARCHAR(40),
            activo BOOLEAN NOT NULL DEFAULT 1,
            created_at VARCHAR(50),
            updated_at VARCHAR(50)
        )""",
        """CREATE TABLE auditorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            usuario_id INTEGER,
            accion VARCHAR(50),
            detalle TEXT,
            created_at VARCHAR(50)
        )""",
        """CREATE TABLE etapas_proyecto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo VARCHAR(40) NOT NULL UNIQUE,
            nombre VARCHAR(120) NOT NULL,
            orden INTEGER NOT NULL,
            color VARCHAR(7),
            activo INTEGER NOT NULL DEFAULT 1,
            created_at VARCHAR(50),
            updated_at VARCHAR(50)
        )""",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))
        # Estados base del flujo ITSM.
        for nombre, orden in (
            ("Nuevo", 1),
            ("En Curso", 2),
            ("En Revision", 3),
            ("Aprobado", 4),
            ("Rechazado", 5),
            ("Cerrado", 6),
        ):
            conn.execute(text(
                "INSERT INTO estados (nombre, descripcion, color, orden, es_inicial, "
                "es_final, categoria, sla_horas, archivado, limite_wip, created_at, updated_at) "
                "VALUES (:n, 'base', '#6b7280', :o, 0, 0, 'base', NULL, 0, NULL, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ), {"n": nombre, "o": orden})
        # Las 4 etiquetas prohibidas + una legitima.
        for nombre in ("Contabilidad", "Software", "Ventas", "RRHH", "Urgente"):
            conn.execute(text(
                "INSERT INTO etiquetas (nombre, descripcion, color, categoria, activo, "
                "created_at, updated_at) VALUES (:n, 'x', '#6b7280', 'general', 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ), {"n": nombre})


def _estados_prod_ok(conn):
    """Filas de 'estados' cuyo nombre normalizado es 'produccion ok'.

    Se filtra en Python y no en SQL a proposito: ``LOWER()`` de SQLite solo
    normaliza ASCII (``LOWER('Producción OK')`` -> ``'producción ok'``), que
    es justamente por lo que el literal sin tilde del codigo original nunca
    coincidia.
    """
    filas = conn.execute(text("SELECT id, nombre FROM estados")).fetchall()
    return [f for f in filas if mig._normalizar_texto(f[1]) == "produccion ok"]


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="[log] %(message)s")

    # --- 0) Helper de normalizacion --------------------------------------
    _check(
        "normalizar: 'Produccion OK' (sin tilde) == 'Produccion OK' (con tilde)",
        mig._normalizar_texto("Producción OK") == mig._normalizar_texto("Produccion OK"),
        "'%s' vs '%s'" % (
            mig._normalizar_texto("Producción OK"),
            mig._normalizar_texto("Produccion OK"),
        ),
    )
    _check(
        "normalizar: 'PRODUCCION  OK' (mayusculas + doble espacio) coincide",
        mig._normalizar_texto("PRODUCCION  OK") == "produccion ok",
        repr(mig._normalizar_texto("PRODUCCION  OK")),
    )

    engine = create_engine("sqlite://", echo=False)
    _crear_esquema(engine)

    # --- 1) Primera ejecucion ---------------------------------------------
    with engine.begin() as conn:
        total = mig._apply_data_migrations(conn, engine)
    print("[info] _apply_data_migrations devolvio total=%s" % total)

    with engine.connect() as conn:
        estados = _estados_prod_ok(conn)
        transiciones = conn.execute(text(
            "SELECT o.nombre, d.nombre, t.rol_requerido FROM transiciones_estado t "
            "JOIN estados o ON o.id = t.estado_origen_id "
            "JOIN estados d ON d.id = t.estado_destino_id "
            "ORDER BY o.nombre, d.nombre"
        )).fetchall()
        etiquetas = conn.execute(text(
            "SELECT nombre, activo FROM etiquetas ORDER BY nombre"
        )).fetchall()
        etapas = conn.execute(text(
            "SELECT COUNT(*) FROM etapas_proyecto"
        )).scalar()

    # --- 2) Estado 'Produccion OK' ---------------------------------------
    _check(
        "4.6: existe exactamente 1 estado 'Produccion OK'",
        len(estados) == 1,
        "encontrados=%r" % (estados,),
    )
    _check(
        "4.6: el nombre conserva el acento canonico",
        bool(estados) and estados[0][1] == "Producción OK",
        "nombre=%r" % (estados[0][1] if estados else None,),
    )

    # --- 3) Transiciones del flujo (el bug que nunca se creaba) ----------
    nombres = {(r[0], r[1]) for r in transiciones}
    esperadas = {
        ("Cerrado", "Producción OK"),
        ("Producción OK", "Cerrado"),
        ("Producción OK", "En Curso"),
    }
    _check(
        "4.7: se crearon las 3 transiciones del flujo 'Produccion OK'",
        esperadas.issubset(nombres),
        "encontradas=%r" % (sorted(nombres),),
    )

    # --- 4) Soft-delete de etiquetas (bug del literal booleano) ----------
    activos = {r[0]: r[1] for r in etiquetas}
    _check(
        "4.3: las 4 etiquetas prohibidas quedaron desactivadas",
        all(activos.get(n) in (0, False) for n in ("Contabilidad", "Software", "Ventas", "RRHH")),
        "activos=%r" % (activos,),
    )
    _check(
        "4.3: la etiqueta legitima 'Urgente' sigue activa",
        activos.get("Urgente") in (1, True),
        "activos=%r" % (activos,),
    )

    # --- 5) Etapas sembradas ---------------------------------------------
    _check("4.8: se sembraron las 10 etapas del proyecto", etapas == 10, "etapas=%s" % etapas)

    # --- 6) Idempotencia: segunda ejecucion ------------------------------
    with engine.begin() as conn:
        mig._apply_data_migrations(conn, engine)
    with engine.connect() as conn:
        estados2 = _estados_prod_ok(conn)
        transiciones2 = conn.execute(text(
            "SELECT COUNT(*) FROM transiciones_estado"
        )).scalar()
    _check(
        "idempotencia: NO se duplico el estado 'Produccion OK' en el 2do arranque",
        len(estados2) == 1,
        "encontrados=%r" % (estados2,),
    )
    _check(
        "idempotencia: NO se duplicaron las transiciones",
        transiciones2 == 3,
        "transiciones=%s" % transiciones2,
    )

    # --- 7) Aislamiento por SAVEPOINT ------------------------------------
    # Se parte de una BD donde la tabla 'etiquetas' NO existe: el paso 4.3
    # falla, pero 4.6/4.8/4.9 deben seguir ejecutandose.
    engine2 = create_engine("sqlite://", echo=False)
    with engine2.begin() as conn:
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
            """CREATE TABLE etapas_proyecto (id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo VARCHAR(40) NOT NULL UNIQUE, nombre VARCHAR(120) NOT NULL,
                orden INTEGER NOT NULL, color VARCHAR(7), activo INTEGER NOT NULL DEFAULT 1,
                created_at VARCHAR(50), updated_at VARCHAR(50))""",
        ):
            conn.execute(text(stmt))
        for nombre, orden in (("Cerrado", 6), ("En Curso", 2)):
            conn.execute(text(
                "INSERT INTO estados (nombre, descripcion, color, orden, es_inicial, "
                "es_final, categoria, sla_horas, archivado, limite_wip, created_at, updated_at) "
                "VALUES (:n, 'base', '#6b7280', :o, 0, 0, 'base', NULL, 0, NULL, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            ), {"n": nombre, "o": orden})
    # Sin tabla 'etiquetas' ni 'auditorias' -> 4.3 y 4.4 fallan.
    with engine2.begin() as conn:
        mig._apply_data_migrations(conn, engine2)
    with engine2.connect() as conn:
        estados3 = len(_estados_prod_ok(conn))
        transiciones3 = conn.execute(text(
            "SELECT COUNT(*) FROM transiciones_estado"
        )).scalar()
        etapas3 = conn.execute(text("SELECT COUNT(*) FROM etapas_proyecto")).scalar()
    _check(
        "SAVEPOINT: tras fallar 4.3/4.4 (tablas ausentes), 4.6 SIGUE funcionando",
        estados3 == 1,
        "estados 'Produccion OK'=%s" % estados3,
    )
    _check(
        "SAVEPOINT: tras fallar 4.3/4.4, 4.7 SIGUE funcionando",
        transiciones3 == 3,
        "transiciones=%s" % transiciones3,
    )
    _check(
        "SAVEPOINT: tras fallar 4.3/4.4, 4.8 SIGUE funcionando",
        etapas3 == 10,
        "etapas=%s" % etapas3,
    )

    print("")
    if FALLOS:
        print("RESULTADO MIGRACIONES: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO MIGRACIONES: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
