"""
Smoke test CLI: ejecuta ``scripts/bulk_update_fechas_gar_ri_backlog.py``
como subproceso con argumentos reales (``--dry-run`` y ``--apply``).

Crea una BD temporal con fixtures, setea ``DATABASE_URL`` y ejecuta el
script directamente.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 1) BD temporal ANTES de cualquier import
TEST_DB = tempfile.mktemp(suffix=".sqlite", prefix="cli_smoke_")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("SEED_DEMO_USERS", "false")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 2) Importar modelos y sembrar
from app.core.security import hash_password  # noqa: E402
from app.db import base as db_base, session as db_session  # noqa: E402
from app.models import (  # noqa: E402
    Estado, Ticket, TipoIncidencia, Usuario, RolUsuario,
)

db_base.Base.metadata.create_all(bind=db_session.engine)

db = db_session.SessionLocal()
try:
    u = Usuario(
        username="cli_admin", email="cli_admin@test.local",
        nombre_completo="CLI Admin", rol=RolUsuario.ADMINISTRADOR,
        is_active=True, hashed_password=hash_password("test1234"),
    )
    db.add(u)
    db.flush()

    e_backlog = Estado(nombre="BACKLOG", categoria="planificacion",
                       orden=99, es_inicial=False, archivado=False)
    db.add(e_backlog)
    db.flush()

    # 3 tarjetas GAR_RI_* en BACKLOG
    for code in ["GAR_RI_CLI_1", "GAR_RI_CLI_2", "GAR_RI_CLI_3"]:
        db.add(Ticket(
            codigo=code, titulo=code, descripcion="cli smoke",
            tipo=TipoIncidencia.INCIDENCIA, prioridad="MEDIA",
            estado_id=e_backlog.id, creador_id=u.id, asignado_id=None,
            fecha_inicio=None, fecha_vencimiento_sla=None,
        ))
    db.commit()
    print(f"[cli_smoke] BD creada con 3 tickets GAR_RI_* en BACKLOG: {TEST_DB}")
finally:
    db.close()


def _run_cli(extra_args):
    cmd = [
        "/tmp/.venv/bin/python",
        "scripts/bulk_update_fechas_gar_ri_backlog.py",
        *extra_args,
    ]
    print(f"\n$ {' '.join(cmd)}")
    p = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy())
    return p.returncode, p.stdout, p.stderr


# 3) DRY-RUN (default: sin --apply)
rc, out, err = _run_cli([])
print(out)
if err:
    print("STDERR:", err)
assert rc == 0, f"dry-run rc={rc}"
assert "DRY-RUN" in out, "Marcador DRY-RUN presente"
assert "Candidatos a actualizar:    3" in out, "Cuenta 3 candidatos"
print("\n[cli_smoke] ✓ dry-run OK (modo default, sin --apply)")

# 4) APPLY (con --yes para evitar input interactivo)
rc, out, err = _run_cli(["--apply", "--yes"])
print(out)
if err:
    print("STDERR:", err)
assert rc == 0, f"apply rc={rc}"
assert "Cambios aplicados y auditados" in out, "Marcador APLICADO presente"

# 5) Verificar que la BD quedó con las fechas correctas
from app.models import Auditoria  # noqa: E402
db = db_session.SessionLocal()
try:
    t1 = db.query(Ticket).filter(Ticket.codigo == "GAR_RI_CLI_1").first()
    t2 = db.query(Ticket).filter(Ticket.codigo == "GAR_RI_CLI_2").first()
    t3 = db.query(Ticket).filter(Ticket.codigo == "GAR_RI_CLI_3").first()
    for t in (t1, t2, t3):
        assert t.fecha_inicio.year == 2026 and t.fecha_inicio.month == 10 and t.fecha_inicio.day == 2
        assert t.fecha_vencimiento_sla.year == 2026 and t.fecha_vencimiento_sla.month == 11 and t.fecha_vencimiento_sla.day == 19
    print("[cli_smoke] ✓ Las 3 tarjetas tienen fecha_inicio=2026-10-02 y sla=2026-11-19")

    auds = db.query(Auditoria).filter(
        Auditoria.accion == "bulk_update_fechas_backlog"
    ).all()
    assert len(auds) == 3, f"esperaba 3 auditoría, encontré {len(auds)}"
    print(f"[cli_smoke] ✓ {len(auds)} entradas de auditoría creadas")
finally:
    db.close()

# 6) Re-aplicar (idempotencia)
rc, out, err = _run_cli(["--apply", "--yes"])
assert rc == 0
assert "Ya con esas fechas:         3" in out, "Segunda pasada: ya todas OK"
print("\n[cli_smoke] ✓ Idempotencia OK (segunda pasada sin cambios)")

# Limpieza
try:
    os.remove(TEST_DB)
    print(f"\n[cli_smoke] ✓ BD temporal eliminada: {TEST_DB}")
except Exception:
    pass

print("\n" + "=" * 60)
print("  ✓✓✓ CLI SMOKE TEST PASÓ ✓✓✓")
print("=" * 60)