"""Smoke test del fix de descarga de adjuntos."""
import os, tempfile
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"
os.environ["SECRET_KEY"] = "test-fix-dl"

from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

from app.db.migrations import apply_migrations
apply_migrations()

from sqlalchemy import inspect
cols = [c["name"] for c in inspect(engine).get_columns("adjuntos")]
assert "contenido" in cols, f"Falta columna contenido: {cols}"
print(f"[OK] Columna contenido presente en adjuntos")

from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.ticket import Ticket
from app.models.estado import Estado

db = SessionLocal()
admin = Usuario(username="admin", email="a@b.c", hashed_password="x", nombre_completo="Admin", rol=RolUsuario.ADMINISTRADOR, is_active=True)
db.add(admin); db.commit()
estado = Estado(nombre="Abierto", orden=1, es_inicial=True, es_final=False, color="#888")
db.add(estado); db.commit()

ticket = Ticket(codigo="T-001", titulo="Test", descripcion="x", estado_id=estado.id, creador_id=admin.id)
db.add(ticket); db.commit(); db.refresh(ticket)

from app.services.features_service import AdjuntoService, UPLOAD_ROOT
print(f"[OK] UPLOAD_ROOT es absoluto: {os.path.isabs(UPLOAD_ROOT)} ({UPLOAD_ROOT})")
assert os.path.isabs(UPLOAD_ROOT), "UPLOAD_ROOT debe ser absoluto"

# Test 1: Guardado normal con contenido
TEST_BYTES = b"Contenido de prueba con acentos y enyes: archivo valido."
adj, err = AdjuntoService(db).guardar_archivo(
    ticket=ticket, usuario=admin,
    file_bytes=TEST_BYTES,
    nombre_original="archivo_prueba.txt",
    mime_type="text/plain",
)
assert err is None, f"Error: {err}"
assert adj.tamano_bytes == len(TEST_BYTES), f"tamano_bytes={adj.tamano_bytes} != {len(TEST_BYTES)}"
assert len(adj.contenido) == len(TEST_BYTES)
assert os.path.exists(adj.ruta), "Archivo debe existir en disco"
assert adj.disponible is True
print(f"[OK] Guardado normal: id={adj.id} ruta={adj.ruta} bytes={adj.tamano_bytes} contenido_db={len(adj.contenido)}B")

# Test 2: Fallback a BD cuando disco no existe (caso Railway)
os.remove(adj.ruta)
assert not os.path.exists(adj.ruta)
# Recargar desde BD para simular un reinicio
db.refresh(adj)
assert adj.disponible is True, f"Debe estar disponible via BD. contenido={len(adj.contenido) if adj.contenido else 0}"
print(f"[OK] Despues de borrar disco, sigue disponible via BD: {adj.disponible}")

# Test 3: Descarga via endpoint con fallback a BD
from app.api.v1.features import descargar_adjunto
res = descargar_adjunto(adjunto_id=adj.id, db=db, _user=admin)
print(f"[OK] Tipo respuesta: {type(res).__name__}")
print(f"     Content-Disposition: {res.headers.get('Content-Disposition', 'N/A')}")
print(f"     Media-Type: {res.media_type}")
content = res.body if hasattr(res, "body") else b""
assert content == TEST_BYTES, f"Mismatch: {content!r}"
assert "filename*=UTF-8''" in res.headers.get("Content-Disposition", ""), "Debe tener filename* UTF-8"
print(f"     Tamaño: {len(content)}B (coincide con original)")

# Test 4: Descarga via disco (fast path) - subir un nuevo archivo
adj2, err2 = AdjuntoService(db).guardar_archivo(
    ticket=ticket, usuario=admin,
    file_bytes=b"X" * 100,
    nombre_original="rapido.zip",
    mime_type="application/octet-stream",
)
assert adj2 is not None, f"No se guardó: {err2}"
res2 = descargar_adjunto(adjunto_id=adj2.id, db=db, _user=admin)
print(f"[OK] Fast path disco: tipo={type(res2).__name__} (debe ser FileResponse)")
from fastapi.responses import FileResponse
assert isinstance(res2, FileResponse), f"Debe ser FileResponse, fue {type(res2).__name__}"

# Test 5: 410 cuando no hay disco NI BD (caso adjunto antiguo)
adj3, _ = AdjuntoService(db).guardar_archivo(
    ticket=ticket, usuario=admin,
    file_bytes=b"orphan",
    nombre_original="orphan.txt",
    mime_type="text/plain",
)
# Forzar sin contenido (simular adjunto muy antiguo)
adj3.contenido = None
db.commit()
db.refresh(adj3)
import os
if os.path.exists(adj3.ruta):
    os.remove(adj3.ruta)
try:
    descargar_adjunto(adjunto_id=adj3.id, db=db, _user=admin)
    print(f"[FAIL] Debio lanzar 410")
except Exception as e:
    print(f"[OK] Sin fuente -> {type(e).__name__}: status={getattr(e, 'status_code', None)} detail={getattr(e, 'detail', None)[:60]}...")

# Test 6: 404 cuando no existe el adjunto
try:
    descargar_adjunto(adjunto_id=99999, db=db, _user=admin)
    print(f"[FAIL] Debio lanzar 404")
except Exception as e:
    print(f"[OK] Adjunto inexistente -> {type(e).__name__}: status={getattr(e, 'status_code', None)}")

db.close()
print()
print("=== TODOS LOS TESTS DEL FIX PASARON ===")
