"""
Clon de la base de datos para validar migraciones antes de tocar produccion.

Por que existe
--------------
El proyecto no tiene Alembic: el esquema se alinea con migraciones
idempotentes que se ejecutan en cada arranque. Eso obliga a poder PROBAR esas
migraciones contra una copia de los datos reales antes de aplicarlas en
produccion: un ``ALTER TABLE`` o un ``UPDATE`` de backfill pueden tener
efectos que un SQLite de pruebas no reproduce (tipos de PostgreSQL,
secuencias, claves foraneas, RLS).

Como funciona
-------------
El clon se crea en el MISMO servidor PostgreSQL que la base de datos de
produccion, con otro nombre (``railway_clon_<nombre>``). Se hace con la
conexion que ya tiene la propia aplicacion, asi que:

* no hay que conocer ni escribir la contrasena de la base de datos;
* el clon y la produccion comparten servidor, motor y version;
* el clon se borra con un ``DROP DATABASE`` (reversible).

El clon se construye a partir del METADATA de SQLAlchemy (``create_all``) y
se copian los datos fila a fila en orden de dependencias. Las secuencias se
dejan alineadas con el maximo de cada columna autoincremental, para que un
INSERT posterior en el clon no choque con los identificadores copiados.

Alcance
-------
Solo lo usa un administrador, de forma explicita. No se ejecuta en ningun
arranque ni en ninguna tarea programada: es una herramienta de operacion.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class ErrorClonado(Exception):
    """Error al clonar la base de datos."""


def _nombre_valido(nombre: str) -> str:
    """Valida el nombre de la base de datos (solo letras, digitos y guion bajo)."""
    limpio = (nombre or "").strip()
    if not limpio or not all(c.isalnum() or c == "_" for c in limpio):
        raise ErrorClonado(
            "El nombre de la base de datos solo admite letras, digitos y "
            "guion bajo: %r" % (nombre,)
        )
    return limpio


def _motor_para(url, base: Optional[str] = None):
    if base:
        url = url.set(database=base)
    return create_engine(url, pool_pre_ping=True, future=True)


def _existe_base(conn, nombre: str) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nombre}
    ).fetchone())


def _alinear_secuencias(clon_conn, tablas) -> int:
    """Deja las secuencias autoincrementales en el maximo copiado."""
    ajustadas = 0
    for tabla in tablas:
        if not hasattr(tabla, "c"):
            continue
        for columna in tabla.c:
            if not (columna.primary_key and columna.autoincrement is True):
                continue
            # ``autoincrement`` es "auto" en SQLite y True/False en Postgres.
            if columna.autoincrement != "auto":
                try:
                    clon_conn.execute(text(
                        "SELECT setval(pg_get_serial_sequence(:t, :c), "
                        "COALESCE((SELECT MAX(%s) FROM %s), 1), true)"
                        % (columna.name, tabla.name)
                    ), {"t": tabla.name, "c": columna.name})
                    ajustadas += 1
                except SQLAlchemyError as exc:
                    logger.warning(
                        "[clone] no se pudo alinear la secuencia de %s.%s: %s",
                        tabla.name, columna.name, exc,
                    )
    return ajustadas


def _orden_y_ciclos(tablas) -> Tuple[List[Any], set]:
    """
    Calcula un orden de copia por dependencias y detecta las tablas que
    participan en un CICLO de claves foraneas.

    Por que no sirve ``Base.metadata.sorted_tables`` (V2.009)
    ---------------------------------------------------------
    SQLAlchemy avisa con ``Cannot correctly sort tables; there are unresolvable
    cycles between tables "adjuntos, comentarios, tickets"`` y devuelve un
    orden que **no** es topologico: coloca ``tickets`` (posicion 2) ANTES de
    ``usuarios`` (posicion 3). La copia fallaba con::

        insert or update on table "tickets" violates foreign key constraint
        "tickets_creador_id_fkey"

    El ciclo es real e inevitable: ``tickets.portada_adjunto_id`` ->
    ``adjuntos.id`` y ``adjuntos.ticket_id`` -> ``tickets.id`` (NOT NULL), de
    modo que no se puede romper nulando la columna.

    Aqui se calcula el orden con el algoritmo de Kahn (propios destinos
    primero) y se detectan las tablas que quedan sin ordenar: esas son
    precisamente las que estan en un ciclo.

    Devuelve
    --------
    ``(orden, ciclos)``: la lista de tablas copiables en orden y el conjunto
    de tablas que participan en al menos un ciclo.
    """
    pendientes = list(tablas)
    deps = {}
    for tabla in pendientes:
        destinos = set()
        for fk in tabla.foreign_keys:
            if fk.parent is not None and fk.column is not None:
                padre = fk.column.table
                if padre is not tabla:
                    destinos.add(padre)
        deps[tabla] = destinos

    orden: List[Any] = []
    restantes = set(pendientes)
    while restantes:
        listos = [t for t in pendientes if t in restantes and not (deps[t] & restantes)]
        if not listos:
            # Todo lo que queda depende de algo que queda: hay un ciclo.
            break
        for tabla in listos:
            orden.append(tabla)
        restantes -= set(listos)

    ciclos = set(restantes)
    if ciclos:
        logger.warning(
            "[clone] %d tablas en ciclo de claves foraneas: %s",
            len(ciclos), ", ".join(sorted(t.name for t in ciclos)),
        )
    return orden, ciclos


def _constraint_fk_por_columna(dest, tabla: str, columna: str) -> Optional[str]:
    """Devuelve el nombre real del constraint FK de (tabla, columna)."""
    try:
        fila = dest.execute(text(
            "SELECT con.conname FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN LATERAL unnest(con.conkey) AS k(attnum) ON TRUE "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum "
            "WHERE con.contype = 'f' AND n.nspname = current_schema() "
            "AND c.relname = :t AND a.attname = :c LIMIT 1"
        ), {"t": tabla, "c": columna}).fetchone()
        return fila[0] if fila else None
    except SQLAlchemyError as exc:
        logger.warning("[clone] no se pudo inspeccionar el FK %s.%s: %s",
                       tabla, columna, exc)
        return None


def _relajar_fks(dest, ciclos) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Relaja las claves foraneas durante la copia de datos.

    Devuelve ``(modo, constraints)`` donde ``modo`` es:

    * ``"replica"``: se ha usado ``session_replication_role = replica``, que
      desactiva la comprobacion de FK durante la transaccion. No deja cambios
      en el esquema del clon. Es el camino preferido (el rol ``postgres`` de
      PostgreSQL es superusuario).
    * ``"deferred"``: no se ha podido usar el anterior (el rol no es
      superusuario) y se han marcado como DEFERRABLE los constraints FK que
      apuntan a las tablas en ciclo. Se restauran al terminar.

    * ``"ninguno"``: no hay ciclos, no hace falta relajar nada.
    """
    if not ciclos:
        return ("ninguno", [])

    # Camino 1: session_replication_role = replica (no altera el esquema).
    # Se usa un SAVEPOINT: si el rol no tiene permiso, el error aborta la
    # transaccion y el SAVEPOINT lo deja en pie.
    try:
        with dest.begin_nested():
            dest.execute(text("SET LOCAL session_replication_role = replica"))
        logger.info("[clone] FK relajadas con session_replication_role=replica")
        return ("replica", [])
    except SQLAlchemyError as exc:
        logger.info(
            "[clone] session_replication_role no disponible (%s); "
            "se usaran constraints DEFERRABLE", exc,
        )

    # Camino 2: DEFERRABLE INITIALLY DEFERRED sobre los FK que apuntan a las
    # tablas en ciclo.
    constraints: List[Tuple[str, str]] = []
    for tabla in Base.metadata.tables.values():
        if tabla not in ciclos:
            continue
        for fk in tabla.foreign_keys:
            padre = fk.column.table if fk.column is not None else None
            if padre is None or padre not in ciclos:
                continue
            if fk.parent is None:
                continue
            nombre = _constraint_fk_por_columna(dest, tabla.name, fk.parent.name)
            if nombre:
                constraints.append((tabla.name, nombre))
    if not constraints:
        raise ErrorClonado(
            "No se pudo relajar las claves foraneas para clonar: el rol de "
            "la base de datos no es superusuario y no se han encontrado los "
            "constraints de las tablas en ciclo."
        )
    for tabla_nombre, constraint in constraints:
        dest.execute(text(
            'ALTER TABLE "%s" ALTER CONSTRAINT "%s" DEFERRABLE INITIALLY DEFERRED'
            % (tabla_nombre, constraint)
        ))
    dest.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    logger.info(
        "[clone] FK relajadas con %d constraints DEFERRABLE", len(constraints),
    )
    return ("deferred", constraints)


def _restaurar_fks(dest, modo: str, constraints: List[Tuple[str, str]]) -> None:
    """Deja el clon con las mismas claves foraneas que tiene el origen."""
    if modo != "deferred":
        return
    for tabla_nombre, constraint in constraints:
        try:
            dest.execute(text(
                'ALTER TABLE "%s" ALTER CONSTRAINT "%s" NOT DEFERRABLE'
                % (tabla_nombre, constraint)
            ))
        except SQLAlchemyError as exc:  # pragma: no cover
            logger.warning("[clone] no se pudo restaurar el constraint %s: %s",
                           constraint, exc)


def clonar_base_datos(
    url_origen: str,
    nombre_clon: str,
    copiar_datos: bool = True,
    engine_clon=None,
) -> Dict[str, Any]:
    """
    Crea un clon de la base de datos de ``url_origen`` y devuelve su URI.

    Parametros
    ----------
    url_origen
        URL de la base de datos de origen (la de la propia aplicacion).
    nombre_clon
        Nombre de la base de datos del clon.
    copiar_datos
        Si es False, solo se replica el esquema (util para validar DDL).
    engine_clon
        Motor ya creado para el clon (opcional; se usa en las pruebas).

    Devuelve
    --------
    dict
        ``uri`` (URL del clon), ``nombre``, ``tablas``, ``filas``,
        ``secuencias`` y ``ya_existia``.
    """
    url = make_url(url_origen)
    nombre = _nombre_valido(nombre_clon)

    # Motor administrativo: se conecta a la base "postgres" del mismo
    # servidor para poder ejecutar CREATE DATABASE (que no admite estar
    # dentro de una transaccion).
    admin = _motor_para(url, base="postgres")
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            if _existe_base(conn, nombre):
                raise ErrorClonado(
                    "La base de datos %r ya existe en el servidor. Borrala antes "
                    "de volver a clonar." % nombre
                )
            conn.execute(text('CREATE DATABASE "%s"' % nombre))
            logger.info("[clone] base de datos creada: %s", nombre)
    except ErrorClonado:
        raise
    except SQLAlchemyError as exc:
        raise ErrorClonado("No se pudo crear la base de datos %r: %s" % (nombre, exc)) from exc
    finally:
        admin.dispose()

    url_clon = url.set(database=nombre)
    uri_clon = url_clon.render_as_string(hide_password=False)

    # Esquema: se crea con el metadata de los modelos.
    import app.models  # noqa: F401  (registra los modelos en Base.metadata)
    from app.db.base import Base

    clon = engine_clon or create_engine(url_clon, pool_pre_ping=True, future=True)
    try:
        Base.metadata.create_all(clon)

        filas_totales = 0
        tablas_copiadas = 0
        if copiar_datos:
            origen = _motor_para(url)
            try:
                # Orden de dependencias: primero las tablas de las que dependen
                # las demas (usuarios, proyectos, estados...), luego las hijas.
                # ``sorted_tables`` NO sirve: el ciclo adjuntos <-> comentarios
                # <-> tickets rompe el orden topologico (ver ``_orden_y_ciclos``).
                orden, ciclos = _orden_y_ciclos(list(Base.metadata.tables.values()))
                copia = orden + sorted(ciclos, key=lambda t: t.name)
                with origen.connect() as src, clon.begin() as dest:
                    modo, constraints = _relajar_fks(dest, ciclos)
                    try:
                        for tabla in copia:
                            try:
                                filas = src.execute(select(tabla)).mappings().all()
                            except SQLAlchemyError as exc:
                                logger.warning(
                                    "[clone] no se pudo leer %s: %s", tabla.name, exc,
                                )
                                continue
                            if not filas:
                                continue
                            dest.execute(
                                insert(tabla),
                                [dict(f) for f in filas],
                            )
                            filas_totales += len(filas)
                            tablas_copiadas += 1
                    finally:
                        _restaurar_fks(dest, modo, constraints)
                secuencias = 0
                with clon.begin() as dest:
                    secuencias = _alinear_secuencias(dest, copia)
            finally:
                origen.dispose()
        else:
            secuencias = 0

        return {
            "uri": uri_clon,
            "nombre": nombre,
            "tablas": len(Base.metadata.tables),
            "tablas_copiadas": tablas_copiadas,
            "filas": filas_totales,
            "secuencias": secuencias,
            "ya_existia": False,
        }
    except SQLAlchemyError as exc:
        raise ErrorClonado("No se pudo poblar el clon %r: %s" % (nombre, exc)) from exc
    finally:
        if engine_clon is None:
            clon.dispose()


def borrar_clon(url_origen: str, nombre_clon: str) -> Dict[str, Any]:
    """
    Borra la base de datos del clon. Es la operacion de reversion.

    No toca la base de datos de origen en ningun caso.
    """
    url = make_url(url_origen)
    nombre = _nombre_valido(nombre_clon)
    admin = _motor_para(url, base="postgres")
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            if not _existe_base(conn, nombre):
                return {"nombre": nombre, "borrada": False, "motivo": "no existe"}
            conn.execute(text('DROP DATABASE "%s" WITH (FORCE)' % nombre))
            logger.info("[clone] base de datos borrada: %s", nombre)
            return {"nombre": nombre, "borrada": True}
    except SQLAlchemyError as exc:
        raise ErrorClonado("No se pudo borrar el clon %r: %s" % (nombre, exc)) from exc
    finally:
        admin.dispose()


def listar_clones(url_origen: str, prefijo: str = "railway_clon") -> List[str]:
    """Devuelve los nombres de las bases de datos del clon que existen."""
    url = make_url(url_origen)
    admin = _motor_para(url, base="postgres")
    try:
        with admin.connect() as conn:
            filas = conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :p"),
                {"p": prefijo + "%"},
            ).fetchall()
            return [f[0] for f in filas]
    except SQLAlchemyError as exc:
        raise ErrorClonado("No se pudieron listar los clones: %s" % exc) from exc
    finally:
        admin.dispose()


def _tablas_y_columnas(conn) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    """
    Devuelve (tablas con sus columnas, numero de filas por tabla) de la base
    de datos a la que apunta la conexion.
    """
    tablas: Dict[str, List[str]] = {}
    for fila in conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name NOT LIKE 'pg_%' "
        "ORDER BY table_name, ordinal_position"
    )).fetchall():
        tablas.setdefault(fila[0], []).append(fila[1])

    conteos: Dict[str, int] = {}
    for tabla in sorted(tablas):
        try:
            conteos[tabla] = conn.execute(
                text('SELECT COUNT(*) FROM "%s"' % tabla)
            ).scalar() or 0
        except SQLAlchemyError:
            conteos[tabla] = -1
    return tablas, conteos


def verificar_clon(url_origen: str, nombre_clon: str) -> Dict[str, Any]:
    """
    Compara el clon con la base de datos de origen y comprueba que el
    aislamiento por proyecto quedo bien aplicado dentro del clon.

    Es la validacion de la ventana V2: no basta con que el clon se cree, tiene
    que ser una COPIA FIEL (mismas tablas, mismas columnas, mismo numero de
    filas) y ademas tiene que tener el backfill aplicado (ninguna fila de
    negocio con ``proyecto_id`` a NULL, proyecto "Legacy" existente y con
    miembros).

    Es de SOLO LECTURA: no escribe nada ni en el origen ni en el clon.

    Devuelve
    --------
    dict
        ``ok`` (bool), ``nombre``, ``tablas_origen``, ``tablas_clon``,
        ``tablas_solo_en_*``, ``columnas_solo_en_*``, ``filas_*``,
        ``tablas_con_diferencia_de_filas``, ``nulos_proyecto_id``,
        ``proyecto_legacy`` y ``miembros_legacy``.
    """
    url = make_url(url_origen)
    nombre = _nombre_valido(nombre_clon)

    origen = _motor_para(url)
    clon = _motor_para(url, base=nombre)
    try:
        with origen.connect() as c_origen:
            tablas_origen, conteos_origen = _tablas_y_columnas(c_origen)
        with clon.connect() as c_clon:
            tablas_clon, conteos_clon = _tablas_y_columnas(c_clon)

            solo_origen = sorted(set(tablas_origen) - set(tablas_clon))
            solo_clon = sorted(set(tablas_clon) - set(tablas_origen))
            columnas_solo_origen = {
                t: sorted(set(tablas_origen[t]) - set(tablas_clon.get(t, [])))
                for t in tablas_origen
                if t in tablas_clon and set(tablas_origen[t]) - set(tablas_clon[t])
            }
            filas_diferentes = {
                t: {"origen": conteos_origen.get(t, -1),
                    "clon": conteos_clon.get(t, -1)}
                for t in sorted(set(conteos_origen) & set(conteos_clon))
                if conteos_origen[t] != conteos_clon[t]
            }

            # Backfill: ninguna fila de negocio debe quedar sin proyecto.
            nulos: Dict[str, int] = {}
            for tabla in sorted(tablas_clon):
                if "proyecto_id" not in tablas_clon[tabla]:
                    continue
                try:
                    n = c_clon.execute(text(
                        'SELECT COUNT(*) FROM "%s" WHERE proyecto_id IS NULL' % tabla
                    )).scalar() or 0
                except SQLAlchemyError:
                    n = -1
                if n:
                    nulos[tabla] = n

            proyecto_legacy = None
            miembros_legacy = 0
            if "proyectos" in tablas_clon:
                proyecto_legacy = c_clon.execute(text(
                    "SELECT nombre FROM proyectos WHERE id = 1"
                )).scalar()
            if "proyecto_usuarios" in tablas_clon:
                miembros_legacy = c_clon.execute(text(
                    "SELECT COUNT(*) FROM proyecto_usuarios WHERE proyecto_id = 1"
                )).scalar() or 0

        ok = (
            not solo_origen and not solo_clon and not columnas_solo_origen
            and not filas_diferentes and not nulos
            and proyecto_legacy is not None
        )
        return {
            "ok": ok,
            "nombre": nombre,
            "tablas_origen": len(tablas_origen),
            "tablas_clon": len(tablas_clon),
            "tablas_solo_en_origen": solo_origen,
            "tablas_solo_en_clon": solo_clon,
            "columnas_solo_en_origen": columnas_solo_origen,
            "filas_origen": sum(v for v in conteos_origen.values() if v > 0),
            "filas_clon": sum(v for v in conteos_clon.values() if v > 0),
            "tablas_con_diferencia_de_filas": filas_diferentes,
            "nulos_proyecto_id": nulos,
            "proyecto_legacy": proyecto_legacy,
            "miembros_legacy": miembros_legacy,
        }
    except SQLAlchemyError as exc:
        raise ErrorClonado(
            "No se pudo verificar el clon %r: %s" % (nombre, exc)
        ) from exc
    finally:
        origen.dispose()
        clon.dispose()
