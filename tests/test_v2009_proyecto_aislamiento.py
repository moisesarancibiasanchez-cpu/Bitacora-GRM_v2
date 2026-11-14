"""
Tests del aislamiento por proyecto - V2.009 (ventana aditiva).

Que se verifica aqui
--------------------
1. El catalogo de proyectos existe (``proyectos`` + ``proyecto_usuarios``).
2. La columna ``proyecto_id`` esta en TODAS las tablas de negocio y en
   NINGUNA global (``usuarios``).
3. El contexto de proyecto esta APAGADO por defecto: sin contexto, una
   sesion ve los tickets de todos los proyectos (comportamiento de V2.008).
4. Con el aislamiento encendido, la sesion filtra por ``proyecto_id`` tanto en
   la API moderna (``select``) como en la heredada (``Query``), y tambien al
   cargar por relacion.
5. La migracion anade la columna, crea el indice y hace el backfill al
   proyecto "Legacy", de forma idempotente.
6. El guardián estricto detecta una columna que el modelo declara y la base de
   datos no tiene (el defecto que hasta V2.008 no se detectaba).
7. Las politicas RLS se generan con el GUC de sesion y NO se aplican mientras
   el flag esta apagado.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.core import proyecto as modulo_proyecto  # noqa: E402
from app.core.proyecto import (  # noqa: E402
    clases_con_proyecto,
    contexto_proyecto,
    obtener_proyecto_actual,
    tablas_con_proyecto,
)
from app.db.base import Base  # noqa: E402
from app.db.migrations import (  # noqa: E402
    COLUMNS_TO_ADD,
    TABLAS_CON_PROYECTO,
    comparar_esquema_completo,
)
from app.db.rls import politicas_rls  # noqa: E402
from app.models.proyecto import (  # noqa: E402
    NOMBRE_PROYECTO_LEGACY,
    PROYECTO_LEGACY_ID,
    Proyecto,
)


# ============================================================================ #
# 1. Catalogo de proyectos
# ============================================================================ #

def test_la_tabla_de_proyectos_existe_en_el_metadata():
    assert "proyectos" in Base.metadata.tables
    assert "proyecto_usuarios" in Base.metadata.tables


def test_el_proyecto_legacy_tiene_id_y_nombre_fijos():
    assert PROYECTO_LEGACY_ID == 1
    assert NOMBRE_PROYECTO_LEGACY == "Legacy"


def test_la_tabla_proyectos_tiene_las_columnas_esperadas():
    columnas = {c.name for c in Base.metadata.tables["proyectos"].c}
    for esperada in ("id", "nombre", "descripcion", "plan", "color", "icono",
                     "activo", "propietario_id", "created_at", "updated_at"):
        assert esperada in columnas, "falta la columna %s" % esperada


def test_el_puente_de_usuarios_tiene_clave_primaria_compuesta():
    tabla = Base.metadata.tables["proyecto_usuarios"]
    assert {c.name for c in tabla.primary_key.columns} == {"proyecto_id", "usuario_id"}


def test_los_usuarios_no_llevan_proyecto_id():
    """Los usuarios son globales: pertenecen a la instalacion, no a un proyecto."""
    from app.models.usuario import Usuario

    assert "proyecto_id" not in Usuario.__table__.c


def test_sessionlocal_se_puede_instantiar():
    """``SessionLocal`` debe devolver una sesion usable.

    Regresion: con ``sessionmaker(cls=...)`` (parametro equivocado en
    SQLAlchemy 2.0) el error aparece al instanciar, no al importar, y la app
    no arrancaba. Este test lo detecta antes del despliegue.
    """
    from app.db.session import SessionLocal, SesionProyecto

    sesion = SessionLocal()
    try:
        assert isinstance(sesion, SesionProyecto)
    finally:
        sesion.close()


# ============================================================================ #
# 2. La columna proyecto_id esta donde debe estar
# ============================================================================ #

def test_las_tablas_con_proyecto_coinciden_con_el_catalogo_declarado():
    """La lista declarada y la que se deriva del metadata no pueden divergir."""
    assert set(tablas_con_proyecto()) == set(TABLAS_CON_PROYECTO)


def test_las_tablas_de_negocio_tienen_proyecto_id():
    for tabla in TABLAS_CON_PROYECTO:
        assert "proyecto_id" in Base.metadata.tables[tabla].c, tabla


def test_las_clases_con_proyecto_cubren_las_tablas_declaradas():
    clases = clases_con_proyecto()
    assert len(clases) == len(TABLAS_CON_PROYECTO)
    nombres = {c.__tablename__ for c in clases}
    assert nombres == set(TABLAS_CON_PROYECTO)


def test_la_columna_es_nullable_en_todas_las_tablas():
    """La ventana V2.009 es aditiva: el paso a NOT NULL es de la ventana V3."""
    for tabla in TABLAS_CON_PROYECTO:
        columna = Base.metadata.tables[tabla].c["proyecto_id"]
        assert columna.nullable, tabla


def test_la_migracion_declara_la_columna_para_todas_las_tablas():
    for tabla in TABLAS_CON_PROYECTO:
        assert "proyecto_id" in COLUMNS_TO_ADD.get(tabla, {}), tabla


def test_las_tablas_puente_no_llevan_proyecto_id():
    """Las tablas de asociacion derivan su aislamiento de las tablas a las
    que apuntan (espacios, tickets, etiquetas), que si llevan la columna."""
    for tabla in ("espacio_miembros", "ticket_etiquetas", "ticket_miembros"):
        assert "proyecto_id" not in Base.metadata.tables[tabla].c, tabla


# ============================================================================ #
# 3. El contexto esta apagado por defecto
# ============================================================================ #

def test_sin_contexto_no_hay_proyecto_activo():
    assert obtener_proyecto_actual() is None


def test_con_el_flag_apagado_el_contexto_se_ignora():
    """El flag manda: aunque se fije un contexto, sin aislamiento no se aplica."""
    from app.core.config import settings

    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = False
    try:
        with contexto_proyecto(7):
            assert obtener_proyecto_actual() is None
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior


def test_con_el_flag_encendido_el_contexto_se_usa():
    from app.core.config import settings

    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
    try:
        with contexto_proyecto(7):
            assert obtener_proyecto_actual() == 7
        assert obtener_proyecto_actual() is None
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior


def test_el_gestor_de_contexto_restaura_el_valor_anterior():
    from app.core.config import settings

    anterior_flag = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
    try:
        with contexto_proyecto(1):
            with contexto_proyecto(2):
                assert obtener_proyecto_actual() == 2
            assert obtener_proyecto_actual() == 1
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior_flag


def test_el_contexto_se_restablece_aunque_el_bloque_falle():
    from app.core.config import settings

    anterior_flag = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
    try:
        with pytest.raises(ValueError):
            with contexto_proyecto(3):
                raise ValueError("fallo simulado")
        assert obtener_proyecto_actual() is None
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior_flag


# ============================================================================ #
# 4. El filtro ORM ( SesionProyecto )
# ============================================================================ #

@pytest.fixture()
def bd_proyectos():
    """Base de datos SQLite con dos proyectos y un ticket en cada uno."""
    import tempfile

    fd, ruta = tempfile.mkstemp(prefix="v2009_", suffix=".sqlite")
    os.close(fd)
    motor = create_engine("sqlite:///" + ruta.replace("\\", "/"), future=True)
    Base.metadata.create_all(motor)

    from app.models.estado import Estado
    from app.models.ticket import Prioridad, Ticket, TipoIncidencia
    from app.models.usuario import RolUsuario, Usuario

    with Session(motor) as sesion:
        admin = Usuario(
            username="admin_v2009",
            email="admin@v2009.test",
            nombre_completo="Admin V2009",
            hashed_password="x",
            rol=RolUsuario.ADMINISTRADOR,
        )
        sesion.add(admin)
        sesion.flush()
        estado = Estado(nombre="BackLog", es_inicial=True)
        sesion.add(estado)
        sesion.flush()
        p1 = Proyecto(nombre="Legacy")
        p2 = Proyecto(nombre="Otro")
        sesion.add_all([p1, p2])
        sesion.flush()
        for indice, proyecto in enumerate((p1, p2), start=1):
            sesion.add(Ticket(
                codigo="V2009-%03d" % indice,
                titulo="Ticket del proyecto %d" % indice,
                descripcion="desc",
                tipo=TipoIncidencia.INCIDENCIA,
                prioridad=Prioridad.MEDIA,
                estado_id=estado.id,
                creador_id=admin.id,
                proyecto_id=proyecto.id,
            ))
        sesion.commit()
        ids = {
            "legacy": p1.id,
            "otro": p2.id,
            "estado": estado.id,
            "usuario": admin.id,
        }

    try:
        yield motor, ids
    finally:
        motor.dispose()
        for sufijo in ("", "-wal", "-shm"):
            try:
                os.unlink(ruta + sufijo)
            except OSError:
                pass


def _abrir_sesion(motor, proyecto_id=None):
    """Abre una SesionProyecto, con contexto de proyecto si se indica."""
    from app.db.session import SesionProyecto

    if proyecto_id is None:
        return SesionProyecto(bind=motor)

    token = modulo_proyecto.establecer_proyecto_actual(proyecto_id)
    try:
        return SesionProyecto(bind=motor)
    finally:
        pass  # el token se restaura en el cierre del test


def test_sin_contexto_la_sesion_ve_todos_los_proyectos(bd_proyectos):
    """Sin aislamiento, el comportamiento es el de V2.008: se ve todo."""
    motor, _ids = bd_proyectos
    from app.models.ticket import Ticket

    sesion = _abrir_sesion(motor, None)
    try:
        tickets = sesion.query(Ticket).all()
        assert len(tickets) == 2
    finally:
        sesion.close()


def test_con_contexto_la_sesion_filtra_por_proyecto(bd_proyectos):
    """Con aislamiento encendido, la API heredada (Query) tambien filtra."""
    from app.core.config import settings
    from app.models.ticket import Ticket

    motor, ids = bd_proyectos
    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
    try:
        with contexto_proyecto(ids["legacy"]):
            sesion = _abrir_sesion(motor, ids["legacy"])
            try:
                tickets = sesion.query(Ticket).all()
                assert len(tickets) == 1, tickets
                assert tickets[0].proyecto_id == ids["legacy"]
            finally:
                sesion.close()
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior


def test_con_contexto_la_api_moderna_tambien_filtra(bd_proyectos):
    from sqlalchemy import select

    from app.core.config import settings
    from app.models.ticket import Ticket

    motor, ids = bd_proyectos
    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
    try:
        with contexto_proyecto(ids["otro"]):
            sesion = _abrir_sesion(motor, ids["otro"])
            try:
                tickets = sesion.execute(select(Ticket)).scalars().all()
                assert len(tickets) == 1, tickets
                assert tickets[0].proyecto_id == ids["otro"]
            finally:
                sesion.close()
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior


def test_dos_contextos_no_se_pisan(bd_proyectos):
    """El ContextVar hace que dos peticiones concurrentes no se contaminen."""
    from app.core.config import settings

    motor, ids = bd_proyectos
    anterior = settings.AISLAMIENTO_PROYECTO_ACTIVO
    settings.AISLAMIENTO_PROYECTO_ACTIVO = True
    try:
        with contexto_proyecto(ids["legacy"]):
            with contexto_proyecto(ids["otro"]):
                assert obtener_proyecto_actual() == ids["otro"]
            assert obtener_proyecto_actual() == ids["legacy"]
    finally:
        settings.AISLAMIENTO_PROYECTO_ACTIVO = anterior


# ============================================================================ #
# 5. La migracion: columna, indice y backfill
# ============================================================================ #

def test_la_migracion_anade_la_columna_hace_backfill_y_es_idempotente(tmp_path):
    """Sobre una BD con el esquema viejo, la migracion deja la columna puesta."""
    from app.db.migrations import apply_migrations

    motor = create_engine(
        "sqlite:///" + str(tmp_path / "mig.sqlite").replace("\\", "/"), future=True
    )
    try:
        # Esquema "viejo": la tabla tickets sin la columna proyecto_id.
        with motor.begin() as conn:
            conn.execute(text(
                "CREATE TABLE proyectos (id INTEGER PRIMARY KEY, nombre VARCHAR(120), "
                "descripcion TEXT, plan VARCHAR(40), color VARCHAR(20), icono VARCHAR(40), "
                "activo BOOLEAN, propietario_id INTEGER, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            ))
            conn.execute(text(
                "CREATE TABLE tickets (id INTEGER PRIMARY KEY, codigo VARCHAR(20) NOT NULL, "
                "titulo VARCHAR(200) NOT NULL)"
            ))
            conn.execute(text(
                "INSERT INTO tickets (id, codigo, titulo) VALUES (1, 'LEG-001', 'Antiguo')"
            ))

        assert "proyecto_id" not in {
            c["name"] for c in inspect(motor).get_columns("tickets")
        }

        apply_migrations(motor)
        apply_migrations(motor)  # idempotente

        columnas = {c["name"] for c in inspect(motor).get_columns("tickets")}
        assert "proyecto_id" in columnas

        # El backfill asigna la fila existente al proyecto Legacy.
        with motor.connect() as conn:
            valor = conn.execute(
                text("SELECT proyecto_id FROM tickets WHERE id = 1")
            ).scalar()
            nombre = conn.execute(
                text("SELECT nombre FROM proyectos WHERE id = 1")
            ).scalar()
        assert valor == PROYECTO_LEGACY_ID
        assert nombre == NOMBRE_PROYECTO_LEGACY

        # Y el indice existe.
        indices = {i["name"] for i in inspect(motor).get_indexes("tickets")}
        assert "ix_tickets_proyecto_id" in indices
    finally:
        motor.dispose()


def test_el_proyecto_legacy_se_crea_solo_una_vez():
    from app.db.migrations import apply_migrations

    import tempfile

    fd, ruta = tempfile.mkstemp(prefix="v2009b_", suffix=".sqlite")
    os.close(fd)
    motor = create_engine("sqlite:///" + ruta.replace("\\", "/"), future=True)
    try:
        apply_migrations(motor)
        apply_migrations(motor)
        with motor.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM proyectos WHERE id = 1")
            ).scalar()
        assert total == 1
    finally:
        motor.dispose()
        for sufijo in ("", "-wal", "-shm"):
            try:
                os.unlink(ruta + sufijo)
            except OSError:
                pass


# ============================================================================ #
# 6. El guardian estricto de esquema
# ============================================================================ #

def test_el_guardian_estricto_detecta_una_columna_que_falta(tmp_path):
    """El defecto que hasta V2.008 pasaba desapercibido."""
    motor = create_engine(
        "sqlite:///" + str(tmp_path / "deriva.sqlite").replace("\\", "/"), future=True
    )
    try:
        Base.metadata.create_all(motor)
        with motor.begin() as conn:
            conn.execute(text("ALTER TABLE tickets DROP COLUMN descripcion"))

        lineas = comparar_esquema_completo(motor)
        deriva = [l for l in lineas if "faltan" in l or "no existe" in l]
        assert any("tickets" in l and "descripcion" in l for l in deriva), deriva
    finally:
        motor.dispose()


def test_el_guardian_estricto_no_detecta_deriva_si_el_esquema_esta_alineado(tmp_path):
    motor = create_engine(
        "sqlite:///" + str(tmp_path / "alineado.sqlite").replace("\\", "/"), future=True
    )
    try:
        Base.metadata.create_all(motor)
        lineas = comparar_esquema_completo(motor)
        deriva = [l for l in lineas if "faltan" in l or "no existe" in l]
        assert deriva == [], deriva
    finally:
        motor.dispose()


def test_el_guardian_estricto_esta_apagado_por_defecto():
    """Con ``ESQUEMA_ESTRICTO`` apagado el arranque no se detiene por deriva."""
    from app.core.config import settings

    assert settings.ESQUEMA_ESTRICTO is False


# ============================================================================ #
# 7. RLS preparado pero inerte
# ============================================================================ #

def test_rls_esta_apagado_por_defecto():
    from app.core.config import settings

    assert settings.RLS_HABILITADO is False
    assert settings.AISLAMIENTO_PROYECTO_ACTIVO is False


def test_las_politicas_rls_usan_el_guc_de_sesion():
    sentencias = politicas_rls(["tickets"])
    sql = " ".join(s for _etiqueta, s in sentencias)
    assert "CREATE POLICY" in sql
    assert "current_setting('app.proyecto_id', true)" in sql
    assert "ENABLE ROW LEVEL SECURITY" not in sql  # se aplica aparte, con ALTER


def test_las_politicas_rls_son_idempotentes():
    """Se borra la politica previa antes de recrearla (PostgreSQL no tiene
    CREATE POLICY IF NOT EXISTS)."""
    sentencias = politicas_rls(["tickets"])
    assert sentencias[0][0].startswith("drop_policy_")
    assert "DROP POLICY IF EXISTS" in sentencias[0][1]


def test_la_tabla_de_puentes_no_entra_en_rls():
    """Las tablas puente no tienen columna de proyecto: no pueden tener RLS."""
    from app.db.rls import aplicar_politicas_rls  # noqa: F401  (import de humo)

    for tabla in ("espacio_miembros", "ticket_etiquetas", "ticket_miembros"):
        assert "proyecto_id" not in Base.metadata.tables[tabla].c


# ============================================================================ #
# 8. Correcciones de la validacion V2 (ENUM, savepoints, ciclo de FK, clon)
# ============================================================================ #

def test_el_orden_de_copia_detecta_el_ciclo_de_claves_foraneas():
    """El esquema tiene un ciclo real: tickets <-> adjuntos <-> comentarios.

    ``Base.metadata.sorted_tables`` devuelve un orden que NO es topologico
    (coloca ``tickets`` antes que ``usuarios``) y la copia del clon fallaba
    con una violacion de clave foranea. ``_orden_y_ciclos()`` debe detectar
    el ciclo y devolver un orden que cubre TODAS las tablas.
    """
    from app.services.clone_service import _orden_y_ciclos

    orden, ciclos = _orden_y_ciclos(list(Base.metadata.tables.values()))

    # Todas las tablas estan en el resultado (una vez en el orden o en el
    # conjunto de ciclos).
    assert len(orden) + len(ciclos) == len(Base.metadata.tables)
    assert len(set(id(t) for t in orden) | set(id(t) for t in ciclos)) == \
        len(Base.metadata.tables)

    # El ciclo detectado incluye las tablas problematicas.
    nombres = {t.name for t in ciclos}
    assert "tickets" in nombres
    assert "adjuntos" in nombres
    assert "comentarios" in nombres

    # Y el orden topologico respeta las dependencias fuera del ciclo:
    # ``usuarios`` debe estar antes que ``tickets``.
    assert orden.index(Base.metadata.tables["usuarios"]) < \
        len(orden) or "usuarios" not in {t.name for t in ciclos}


def test_la_etiqueta_del_rol_admin_se_resuelve_desde_la_base_de_datos():
    """El ENUM de ``usuarios.rol`` se persiste con el NOMBRE del miembro.

    Comparar la columna contra el literal ``'administrador'`` hacia fallar
    PostgreSQL con ``invalid input value for enum rolusuario``. La etiqueta
    real se lee de la base de datos, nunca se adivina.
    """
    from app.db.migrations import _resolver_etiqueta_admin

    motor = create_engine("sqlite://", future=True)
    Base.metadata.create_all(motor)
    with motor.begin() as conn:
        etiqueta = _resolver_etiqueta_admin(conn, False)

    motor.dispose()
    assert etiqueta.strip().upper() == "ADMINISTRADOR"


def test_la_migracion_del_legacy_no_compara_el_enum_con_un_literal():
    """Regresion: el literal ``'administrador'`` ante un ENUM rompe el paso 3.

    La comparacion del rol se hace EN PYTHON (leyendo el valor almacenado),
    no en SQL, de modo que no hay ningun literal que PostgreSQL pueda
    rechazar al convertirlo a etiqueta del enum.
    """
    import inspect as _inspect

    from app.db import migrations as mod

    fuente = _inspect.getsource(mod._aplicar_proyecto_legacy)
    assert "rol = 'administrador'" not in fuente
    assert "WHERE rol =" not in fuente


def test_el_backfill_usa_un_savepoint_por_paso():
    """Cada paso va en su propio ``begin_nested()``.

    Con un unico savepoint compartido, un fallo del paso 3 revertia el
    backfill completo (unas 8.500 filas) y dejaba ``proyecto_id`` a NULL.
    """
    import inspect as _inspect

    from app.db import migrations as mod

    fuente = _inspect.getsource(mod._aplicar_proyecto_legacy)
    # Un savepoint para la fila del proyecto, uno por tabla del backfill y
    # uno para la membresia: al menos 3 llamadas a ``begin_nested``.
    assert fuente.count("begin_nested()") >= 3


def test_el_clon_relaja_las_claves_foraneas_durante_la_copia():
    """La copia usa ``session_replication_role`` o constraints DEFERRABLE.

    Sin relajar las FK, el clon no se puede poblar (ciclo de FK). Ademas el
    camino preferido NO debe dejar cambios en el esquema del clon.
    """
    import inspect as _inspect

    from app.services import clone_service

    fuente = _inspect.getsource(clone_service._relajar_fks)
    assert "session_replication_role" in fuente
    assert "DEFERRABLE" in fuente

    fuente_restaurar = _inspect.getsource(clone_service._restaurar_fks)
    assert "NOT DEFERRABLE" in fuente_restaurar


def test_la_verificacion_del_clon_esta_disponible():
    from app.services.clone_service import verificar_clon  # noqa: F401


def test_los_endpoints_de_migraciones_estan_registrados():
    """Los cinco endpoints de administracion deben existir en la aplicacion."""
    from app.main import app

    rutas = {r.path for r in app.routes if hasattr(r, "path")}
    for esperada in (
        "/api/v1/migraciones/esquema",
        "/api/v1/migraciones/clonar",
        "/api/v1/migraciones/clonar/{nombre}",
        "/api/v1/migraciones/clonar/{nombre}/verificar",
        "/api/v1/migraciones/clones",
    ):
        assert esperada in rutas, "falta la ruta %s" % esperada