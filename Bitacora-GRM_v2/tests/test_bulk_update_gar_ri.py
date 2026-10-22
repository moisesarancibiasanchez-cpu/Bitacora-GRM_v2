"""
Test end-to-end para ``scripts.bulk_update_fechas_gar_ri_backlog``.

Crea una base de datos SQLite temporal con:
- Estado ``BACKLOG`` (case-insensitive)
- 4 tickets ``GAR_RI_*`` (3 en BACKLOG, 1 en Pendiente)
- 1 ticket ``GAR_OTRO_*`` (no debe ser tocado)
- 1 ticket ``GAR_RI_*`` que YA tiene las fechas objetivo (idempotencia)

Luego ejecuta el bulk update en modo ``apply_changes=True`` y verifica:
- Conteos correctos
- Fechas actualizadas
- Auditoría creada
- Idempotencia al re-ejecutar
- Que NO se tocaron tickets fuera del scope
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------- #
# 1. BD temporal ANTES de importar nada
# --------------------------------------------------------------------- #
TEST_DB = tempfile.mktemp(suffix=".sqlite", prefix="test_bulk_gar_ri_")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
# Forzar la BD en el config del proyecto
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("SEED_DEMO_USERS", "false")

# Asegurar que ``app`` esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --------------------------------------------------------------------- #
# 2. Importar la app (ya con la nueva DATABASE_URL)
# --------------------------------------------------------------------- #
from app.core.security import hash_password  # noqa: E402
from app.db import base as db_base  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.models import (  # noqa: E402
    Auditoria, Estado, Ticket, TipoIncidencia, Usuario, RolUsuario,
)

# Importar el script a testear
from scripts.bulk_update_fechas_gar_ri_backlog import (  # noqa: E402
    ejecutar_bulk_update,
)


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _crear_usuario_test(db, username="admin_test") -> Usuario:
    u = Usuario(
        username=username,
        email=f"{username}@test.local",
        nombre_completo="Admin Test",
        rol=RolUsuario.ADMINISTRADOR,
        is_active=True,
        hashed_password=hash_password("test1234"),
    )
    db.add(u)
    db.flush()
    return u


def _crear_estado(db, *, nombre: str, orden: int, es_inicial: bool = False) -> Estado:
    e = Estado(
        nombre=nombre,
        categoria="planificacion",
        orden=orden,
        es_inicial=es_inicial,
        archivado=False,
    )
    db.add(e)
    db.flush()
    return e


def _crear_ticket(
    db,
    *,
    codigo: str,
    estado_id: int,
    creador_id: int,
    fecha_inicio: datetime | None,
    fecha_vencimiento_sla: datetime | None,
    titulo: str = "Ticket de prueba",
) -> Ticket:
    t = Ticket(
        codigo=codigo,
        titulo=titulo,
        descripcion="Ticket de prueba",
        tipo=TipoIncidencia.INCIDENCIA,
        prioridad="MEDIA",
        estado_id=estado_id,
        creador_id=creador_id,
        asignado_id=None,
        fecha_inicio=fecha_inicio,
        fecha_vencimiento_sla=fecha_vencimiento_sla,
    )
    db.add(t)
    db.flush()
    return t


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  ✗ FAIL: {msg}")
        sys.exit(1)
    print(f"  ✓ {msg}")


# --------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------- #
def main() -> int:
    print("=" * 78)
    print("  TEST E2E: bulk_update_fechas_gar_ri_backlog")
    print("=" * 78)
    print(f"  BD temporal: {TEST_DB}")

    # 1. Crear todas las tablas
    db_base.Base.metadata.create_all(bind=db_session.engine)
    print("  ✓ Esquema creado")

    # 2. Sembrar fixtures
    tickets_ref: dict[str, Ticket] = {}
    db = db_session.SessionLocal()
    try:
        usuario = _crear_usuario_test(db)
        estado_backlog = _crear_estado(db, nombre="BACKLOG", orden=99)
        estado_pend = _crear_estado(db, nombre="Pendiente", orden=1, es_inicial=1)

        # A) GAR_RI_* en BACKLOG, fechas a actualizar
        tickets_ref["A1"] = _crear_ticket(
            db, codigo="GAR_RI_001", estado_id=estado_backlog.id,
            creador_id=usuario.id, fecha_inicio=None,
            fecha_vencimiento_sla=None, titulo="Card GAR_RI_001 sin fechas",
        )
        tickets_ref["A2"] = _crear_ticket(
            db, codigo="GAR_RI_002", estado_id=estado_backlog.id,
            creador_id=usuario.id,
            fecha_inicio=datetime(2026, 9, 1),
            fecha_vencimiento_sla=datetime(2026, 10, 1),
            titulo="Card GAR_RI_002 con fechas viejas",
        )
        tickets_ref["A3"] = _crear_ticket(
            db, codigo="GAR_RI_003", estado_id=estado_backlog.id,
            creador_id=usuario.id,
            fecha_inicio=datetime(2026, 8, 15),
            fecha_vencimiento_sla=datetime(2026, 11, 1),
            titulo="Card GAR_RI_003 con inicio mistico",
        )

        # B) GAR_RI_* YA con las fechas objetivo → idempotencia
        tickets_ref["B"] = _crear_ticket(
            db, codigo="GAR_RI_004", estado_id=estado_backlog.id,
            creador_id=usuario.id,
            fecha_inicio=datetime(2026, 10, 2),
            fecha_vencimiento_sla=datetime(2026, 11, 19),
            titulo="Card GAR_RI_004 ya con fechas objetivo",
        )

        # C) GAR_RI_* pero en Pendiente → NO debe tocarse
        tickets_ref["C"] = _crear_ticket(
            db, codigo="GAR_RI_005", estado_id=estado_pend.id,
            creador_id=usuario.id, fecha_inicio=None,
            fecha_vencimiento_sla=None,
            titulo="Card GAR_RI_005 fuera de BACKLOG",
        )

        # D) prefijo distinto → NO debe tocarse
        tickets_ref["D"] = _crear_ticket(
            db, codigo="GAR_OTRO_001", estado_id=estado_backlog.id,
            creador_id=usuario.id, fecha_inicio=None,
            fecha_vencimiento_sla=None,
            titulo="Card GAR_OTRO_001 con prefijo distinto",
        )

        db.commit()

        print("\n  --- Datos sembrados ---")
        for k, t in tickets_ref.items():
            print(
                f"    [{k}] id={t.id} codigo={t.codigo} estado_id={t.estado_id} "
                f"fecha_inicio={t.fecha_inicio} fecha_sla={t.fecha_vencimiento_sla}"
            )
    finally:
        db.close()

    tA1, tA2, tA3 = tickets_ref["A1"], tickets_ref["A2"], tickets_ref["A3"]
    tB, tC, tD = tickets_ref["B"], tickets_ref["C"], tickets_ref["D"]

    # --------------------------------------------------------------- #
    # 3. DRY-RUN
    # --------------------------------------------------------------- #
    print("\n" + "=" * 78)
    print("  DRY-RUN")
    print("=" * 78)
    resumen_dry = ejecutar_bulk_update(apply_changes=False)
    print(json.dumps(resumen_dry, indent=2, default=str))

    _assert(resumen_dry["dry_run"] is True, "dry_run=True")
    _assert(resumen_dry["total_encontrados"] == 4, "4 tickets GAR_RI_* en BACKLOG")
    _assert(resumen_dry["ya_con_fechas"] == 1, "1 ticket ya con fechas objetivo (idempotencia)")
    _assert(resumen_dry["actualizados"] == 3, "3 candidatos a actualizar")
    _assert(resumen_dry["errores"] == [], "Sin errores")
    _assert(
        sorted(resumen_dry["ids_actualizados"]) == sorted([tA1.id, tA2.id, tA3.id]),
        "IDs actualizados correctos",
    )
    _assert(resumen_dry["ids_ya_con_fechas"] == [tB.id], "ID ya con fechas correcto")
    _assert(resumen_dry["estado_usado"] == "BACKLOG", "Estado usado = BACKLOG")
    _assert(resumen_dry["estado_id"] == estado_backlog.id, "Estado id OK")

    # --------------------------------------------------------------- #
    # 4. APPLY (primera pasada)
    # --------------------------------------------------------------- #
    print("\n" + "=" * 78)
    print("  APPLY (primera pasada)")
    print("=" * 78)
    resumen_apply = ejecutar_bulk_update(apply_changes=True)
    print(json.dumps(resumen_apply, indent=2, default=str))

    _assert(resumen_apply["dry_run"] is False, "dry_run=False")
    _assert(resumen_apply["actualizados"] == 3, "3 tickets actualizados")
    _assert(resumen_apply["ya_con_fechas"] == 1, "1 ya_con_fechas")
    _assert(resumen_apply["errores"] == [], "Sin errores")

    # --------------------------------------------------------------- #
    # 5. Verificar persistencia
    # --------------------------------------------------------------- #
    print("\n" + "=" * 78)
    print("  VERIFICACIÓN POST-APPLY")
    print("=" * 78)
    db = db_session.SessionLocal()
    try:
        esperado_inicio = datetime(2026, 10, 2)
        esperado_sla = datetime(2026, 11, 19)

        for tid, codigo in [
            (tA1.id, "GAR_RI_001"),
            (tA2.id, "GAR_RI_002"),
            (tA3.id, "GAR_RI_003"),
        ]:
            t = db.query(Ticket).filter(Ticket.id == tid).first()
            assert t is not None, f"No se encontró {codigo}"
            assert t.fecha_inicio is not None, f"{codigo} sin fecha_inicio"
            assert t.fecha_vencimiento_sla is not None, f"{codigo} sin fecha_sla"
            _assert(
                t.fecha_inicio.year == esperado_inicio.year
                and t.fecha_inicio.month == esperado_inicio.month
                and t.fecha_inicio.day == esperado_inicio.day,
                f"{codigo} fecha_inicio = 2026-10-02",
            )
            _assert(
                t.fecha_vencimiento_sla.year == esperado_sla.year
                and t.fecha_vencimiento_sla.month == esperado_sla.month
                and t.fecha_vencimiento_sla.day == esperado_sla.day,
                f"{codigo} fecha_vencimiento_sla = 2026-11-19",
            )

        # Idempotente: GAR_RI_004 mantiene sus fechas
        t = db.query(Ticket).filter(Ticket.id == tB.id).first()
        assert t is not None
        _assert(
            t.fecha_inicio.year == 2026 and t.fecha_inicio.month == 10 and t.fecha_inicio.day == 2,
            "GAR_RI_004 mantiene fecha_inicio 2026-10-02",
        )

        # Fuera de scope: GAR_RI_005 NO debe haberse tocado
        t = db.query(Ticket).filter(Ticket.id == tC.id).first()
        assert t is not None
        _assert(
            t.fecha_inicio is None and t.fecha_vencimiento_sla is None,
            "GAR_RI_005 (fuera de BACKLOG) NO fue tocado",
        )

        # Fuera de scope: GAR_OTRO_001 NO debe haberse tocado
        t = db.query(Ticket).filter(Ticket.id == tD.id).first()
        assert t is not None
        _assert(
            t.fecha_inicio is None and t.fecha_vencimiento_sla is None,
            "GAR_OTRO_001 (prefijo distinto) NO fue tocado",
        )

        # Auditoría: 3 inserts (uno por cada cambio)
        auds = (
            db.query(Auditoria)
            .filter(Auditoria.accion == "bulk_update_fechas_backlog")
            .all()
        )
        _assert(len(auds) == 3, f"3 entradas de auditoría creadas (encontradas={len(auds)})")
        for a in auds:
            _assert(
                a.valor_anterior is not None and a.valor_nuevo is not None,
                f"Auditoría ticket_id={a.ticket_id} tiene valor_anterior y valor_nuevo",
            )
            _assert(
                "bulk_update_fechas_backlog:v1" in (a.comentario or ""),
                f"Auditoría ticket_id={a.ticket_id} tiene tag de idempotencia",
            )
            # Verificar que valor_nuevo tiene las fechas correctas
            vn = a.valor_nuevo
            if isinstance(vn, str):
                vn = json.loads(vn)
            _assert(
                vn["fecha_inicio"].startswith("2026-10-02"),
                f"Auditoría ticket_id={a.ticket_id} valor_nuevo.fecha_inicio OK",
            )
    finally:
        db.close()

    # --------------------------------------------------------------- #
    # 6. APPLY (segunda pasada) → idempotencia
    # --------------------------------------------------------------- #
    print("\n" + "=" * 78)
    print("  APPLY (segunda pasada — debe ser idempotente)")
    print("=" * 78)
    resumen_apply2 = ejecutar_bulk_update(apply_changes=True)

    _assert(resumen_apply2["actualizados"] == 0, "0 candidatos a actualizar (ya todos OK)")
    _assert(resumen_apply2["ya_con_fechas"] == 4, "4 ya con fechas objetivo")
    _assert(resumen_apply2["errores"] == [], "Sin errores")

    # La auditoría NO debe crecer (no debe haber duplicados)
    db = db_session.SessionLocal()
    try:
        auds = (
            db.query(Auditoria)
            .filter(Auditoria.accion == "bulk_update_fechas_backlog")
            .all()
        )
        _assert(len(auds) == 3, f"Sigue habiendo 3 entradas (no se duplicó) — encontradas={len(auds)}")
    finally:
        db.close()

    # --------------------------------------------------------------- #
    # 7. Test: estado inexistente debe reportar error sin tocar nada
    # --------------------------------------------------------------- #
    print("\n" + "=" * 78)
    print("  TEST EXTRA: estado inexistente")
    print("=" * 78)
    resumen_err = ejecutar_bulk_update(
        nombre_estado="NO_EXISTE_ESTE_ESTADO",
        apply_changes=False,
    )
    print(json.dumps(resumen_err, indent=2, default=str))
    _assert(
        len(resumen_err["errores"]) > 0,
        "Reporta error cuando el estado no existe",
    )

    # --------------------------------------------------------------- #
    # 8. Test: rango de fechas inválido
    # --------------------------------------------------------------- #
    print("\n" + "=" * 78)
    print("  TEST EXTRA: rango de fechas inválido")
    print("=" * 78)
    try:
        ejecutar_bulk_update(
            fecha_inicio_str="2026-11-19",
            fecha_vencimiento_str="2026-10-02",
            apply_changes=False,
        )
        _assert(False, "Debería haber lanzado ValueError")
    except ValueError as e:
        print(f"  ✓ Levantó ValueError correctamente: {e}")

    # --------------------------------------------------------------- #
    # Limpieza
    # --------------------------------------------------------------- #
    try:
        os.remove(TEST_DB)
        print(f"\n  BD temporal eliminada: {TEST_DB}")
    except Exception as exc:
        print(f"  Aviso: no se pudo eliminar {TEST_DB}: {exc}")

    print("\n" + "=" * 78)
    print("  ✓✓✓ TODOS LOS TESTS PASARON ✓✓✓")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())