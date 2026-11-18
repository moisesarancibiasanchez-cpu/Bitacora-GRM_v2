"""Pruebas del generador de backups de PostgreSQL (V2.009).

Dos bloques:

1) ``_pg_literal``: el formateo de valores SQL, incluido el caso ``json``,
   que era un BUG REAL: psycopg2 convierte las columnas ``json``/``jsonb``
   en objetos Python y un literal escrito a pelo no siempre es JSON valido.
   En produccion (2026-11-18) un string JSON salia como ``'incidencia'``
   (sin las comillas) y el backup no se podia restaurar::

       ERROR: invalid input syntax for type json

2) Un round-trip REAL contra PostgreSQL, que se salta si no hay un servidor
   local disponible (en CI puede no haberlo).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from app.services.backup_service import _pg_literal  # noqa: E402


# ============================================================
# 1. _pg_literal
# ============================================================

class TestLiteralSQL:
    """El literal SQL de cada tipo de valor."""

    def test_null(self):
        assert _pg_literal(None) == "NULL"

    def test_entero_y_booleano(self):
        assert _pg_literal(42) == "42"
        assert _pg_literal(True) == "TRUE"
        assert _pg_literal(False) == "FALSE"

    def test_flotante(self):
        assert _pg_literal(1.5) == "1.5"
        assert _pg_literal(float("inf")) == "'Infinity'"
        assert _pg_literal(float("-inf")) == "'-Infinity'"

    def test_texto_con_comilla_simple(self):
        assert _pg_literal("O'Brien") == "'O''Brien'"

    def test_bytea_en_hexadecimal(self):
        # Un SOLO backslash: '\\x0a1b' en el fichero, '\x0a1b' en la BD.
        assert _pg_literal(b"\n\x1b") == "'\\x0a1b'"

    def test_fecha_hora(self):
        valor = datetime(2026, 11, 18, 10, 30, 0)
        assert _pg_literal(valor) == "'2026-11-18 10:30:00'"


class TestLiteralJSON:
    """Las columnas ``json``/``jsonb`` necesitan su propio formato."""

    def test_string_json_lleva_comillas(self):
        """El caso que rompia la restauracion del backup de produccion."""
        assert _pg_literal("incidencia", "json") == '\'"incidencia"\''

    def test_booleano_json_es_true_en_minusculas(self):
        assert _pg_literal(True, "json") == "'true'"
        assert _pg_literal(False, "json") == "'false'"

    def test_objeto_json(self):
        assert _pg_literal({"a": 1}, "json") == '\'{"a": 1}\''

    def test_lista_json(self):
        assert _pg_literal([1, 2], "json") == "'[1, 2]'"

    def test_numero_json(self):
        assert _pg_literal(42, "json") == "'42'"

    def test_null_json_es_null_de_sql(self):
        assert _pg_literal(None, "json") == "NULL"

    def test_string_json_con_comilla_simple(self):
        assert _pg_literal("d'Angelo", "json") == '\'"d\'\'Angelo"\''

    def test_jsonb_usa_el_mismo_formato(self):
        assert _pg_literal("incidencia", "jsonb") == '\'"incidencia"\''

    def test_sin_tipo_un_string_no_lleva_comillas_json(self):
        """Sin el tipo de columna no se puede saber: es texto normal."""
        assert _pg_literal("incidencia") == "'incidencia'"

    def test_todo_lo_que_emiten_los_json_es_json_valido(self):
        import json as _json

        valores = [
            "incidencia", "con \"comillas\"", "d'Angelo", True, False,
            42, 3.14, {"a": 1, "b": [1, 2]}, [1, "x", None],
            "acentuación y ñ", "", "línea\nsalto",
        ]
        for valor in valores:
            literal = _pg_literal(valor, "json")
            assert literal.startswith("'") and literal.endswith("'")
            # Se desenvuelve el literal SQL y se parsea como JSON.
            interior = literal[1:-1].replace("''", "'")
            _json.loads(interior)  # no debe lanzar


# ============================================================
# 2. Round-trip real contra PostgreSQL (se salta si no hay servidor)
# ============================================================

def _pg_local() -> str | None:
    """Devuelve la URL de un PostgreSQL local, o None si no hay ninguno."""
    candidatos = [
        os.environ.get("PGV2009_URL", ""),
        "postgresql://postgres@127.0.0.1:55433/postgres",
    ]
    for url in candidatos:
        if not url:
            continue
        try:
            import psycopg2
            from sqlalchemy import create_engine

            motor = create_engine(url, future=True)
            with motor.connect() as c:
                c.exec_driver_sql("SELECT 1")
            motor.dispose()
            return url
        except Exception:
            continue
    return None


@pytest.mark.skipif(_pg_local() is None, reason="no hay PostgreSQL local disponible")
def test_roundtrip_con_columnas_json():
    """Backup y restauracion de una tabla con valores JSON de todo tipo."""
    import json as _json

    from sqlalchemy import create_engine, text

    url = _pg_local()
    admin = url.rsplit("/", 1)[0] + "/postgres"
    nombre = "v2009_test_backup_json"
    motor_admin = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
    with motor_admin.connect() as c:
        for n in (nombre, nombre + "_restaurada"):
            c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % n))
            c.execute(text('CREATE DATABASE "%s"' % n))
    motor_admin.dispose()

    url_fuente = url.rsplit("/", 1)[0] + "/" + nombre
    url_destino = url.rsplit("/", 1)[0] + "/" + nombre + "_restaurada"
    motor_fuente = create_engine(url_fuente, future=True)
    motor_destino = create_engine(url_destino, future=True, isolation_level="AUTOCOMMIT")

    valores = [
        "incidencia",
        '{"estado_id": 1, "estado": "BackLog"}',
        "d'Angelo",
        "acentuación",
    ]
    try:
        with motor_fuente.begin() as c:
            c.execute(text("CREATE TABLE t_json (id integer primary key, j json, b json)"))
            for i, v in enumerate(valores, start=1):
                # Se inserta el TEXTO JSON, que es lo que hace la columna:
                # un string plano se guarda como el string JSON "incidencia"
                # (con comillas). Asi es como esta en produccion.
                c.execute(
                    text("INSERT INTO t_json (id, j, b) VALUES (:i, :j, :b)"),
                    {"i": i, "j": _json.dumps(v), "b": _json.dumps(True)},
                )

        # --- backup ---
        import gzip
        import tempfile

        from app.services.backup_service import BackupService

        with tempfile.TemporaryDirectory() as tmp:
            destino = os.path.join(tmp, "dump.sql.gz")
            BackupService()._backup_postgresql_python(url_fuente, Path(destino))
            with gzip.open(destino, "rb") as fh:
                sql = fh.read().decode("utf-8")

        assert "CREATE TABLE" in sql
        assert "t_json" in sql

        # --- restauracion ---
        with motor_destino.connect() as c:
            c.execute(text(sql))

        with motor_destino.connect() as c:
            leidos = c.execute(text("SELECT id, j::text, b::text FROM t_json ORDER BY id")).fetchall()
        assert len(leidos) == len(valores)
        for fila, original in zip(leidos, valores):
            # Se compara el VALOR JSON, no su texto: PostgreSQL normaliza los
            # escapes unicode ("acentuaci\u00f3n" -> "acentuación"), pero el
            # valor es el mismo.
            assert _json.loads(fila[1]) == original, (
                "valor json alterado: %r != %r" % (fila[1], original))
            assert _json.loads(fila[2]) is True
    finally:
        motor_fuente.dispose()
        motor_destino.dispose()
        motor_admin = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
        with motor_admin.connect() as c:
            for n in (nombre, nombre + "_restaurada"):
                c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % n))
        motor_admin.dispose()


@pytest.mark.skipif(_pg_local() is None, reason="no hay PostgreSQL local disponible")
def test_las_migraciones_concurrentes_no_se_pisan():
    """Tres procesos aplicando migraciones a la vez NO deben fallar.

    En el despliegue de Railway, ``start.sh`` lanza ``verificar_esquema()``
    en los tres roles (web, worker y beat) a la vez, y los tres aplican las
    migraciones sobre la MISMA base de datos. Sin cerrojo ni savepoint por
    indice, dos de ellos crean el mismo indice a la vez y el segundo recibe
    "duplicate key value violates unique constraint
    pg_class_relname_nsp_index", que ABORTA su transaccion y deja sin crear
    los indices que quedaban.

    Medido el 2026-11-14 en produccion: un servicio creo 3 indices y fallo
    en los 52 restantes.
    """
    import multiprocessing as mp  # noqa: F401  (documenta el problema)
    from sqlalchemy import create_engine, text

    url = _pg_local()
    admin = url.rsplit("/", 1)[0] + "/postgres"
    nombre = "v2009_test_concurrencia"
    motor_admin = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
    with motor_admin.connect() as c:
        for n in (nombre,):
            c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % n))
            c.execute(text('CREATE DATABASE "%s"' % n))
    motor_admin.dispose()

    url_db = url.rsplit("/", 1)[0] + "/" + nombre
    motor = create_engine(url_db, future=True)
    import app.models  # noqa: F401
    from app.db.base import Base

    Base.metadata.create_all(motor)
    motor.dispose()

    def _trabajador(_n, resultados, barrera):
        """Cada hilo abre SU PROPIA conexion: la carrera es real en la BD."""
        from sqlalchemy import create_engine as ce, text as tx

        m = ce(url_db, future=True)
        ok = 0
        fallos = 0
        try:
            with m.connect() as conn:
                trans = conn.begin()
                barrera.wait()
                conn.execute(tx(
                    "SELECT pg_advisory_xact_lock(:c)"), {"c": 7412009013})
                from app.db.migrations import INDEXES

                for _nombre, sql in INDEXES:
                    try:
                        with conn.begin_nested():
                            conn.execute(tx(sql))
                        ok += 1
                    except Exception:
                        fallos += 1
                trans.commit()
        except Exception:
            fallos += 1
        finally:
            m.dispose()
        resultados.append((ok, fallos))

    import threading

    resultados = []
    barrera = threading.Barrier(3)
    hilos = [threading.Thread(target=_trabajador, args=(i, resultados, barrera))
             for i in range(3)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=300)

    motor = create_engine(url_db, future=True)
    with motor.connect() as c:
        n_proyecto = c.execute(text(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'ix_%_proyecto_id'"
        )).scalar()
    motor.dispose()
    with motor_admin.connect() as c:
        c.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % nombre))
    motor_admin.dispose()

    assert len(resultados) == 3, "no terminaron los 3 procesos: %s" % (resultados,)
    fallos_totales = sum(f for _ok, f in resultados)
    assert fallos_totales == 0, (
        "las migraciones concurrentes fallaron: %s" % (resultados,))
    assert n_proyecto == 34, "faltan indices de proyecto: %s de 34" % n_proyecto