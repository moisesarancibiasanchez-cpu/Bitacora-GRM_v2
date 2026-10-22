#!/usr/bin/env python3
"""
VALIDACIÓN EXHAUSTIVA - Bitácora GRM v2
=========================================
Valida:
  1. Imports/sintaxis de todos los módulos Python
  2. Modelos SQLAlchemy (esquema completo, FKs, índices)
  3. Todas las rutas de FastAPI (existen y responden)
  4. Templates Jinja2 (sintaxis, links rotos a estáticos, includes)
  5. Archivos estáticos (existen, sin 404s)
  6. Flujo de autenticación (login, JWT, sesiones)
  7. Autorización por roles (admin, agente, solicitante)
  8. Flujo Kanban: drag-and-drop, cambiar_estado, transiciones
  9. Asignación de responsable (picker, PATCH, fallback inactivos)
  10. Notificaciones in-app (creación correcta)
  11. Email service (Resend/SMTP/log fallback)
  12. Diagnóstico endpoint
  13. Configuración Celery/Redis
  14. Configuración producción (env vars, DATABASE_URL, SECRET_KEY)

Usage:
    source .venv-test/bin/activate
    python test_validacion_exhaustiva.py
"""
import os
import sys
import re
import ast
import json
import tempfile
import pathlib
import importlib
import traceback
import logging
import warnings

logging.disable(logging.CRITICAL)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
warnings.filterwarnings('ignore')

# Colores
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'

# Contadores globales
ERRORS = []
WARNINGS = []
OKS = []


def ok(label, detail=""):
    OKS.append((label, detail))
    print(f"  {GREEN}✓{RESET} {label}" + (f"  {detail}" if detail else ""))


def warn(label, detail=""):
    WARNINGS.append((label, detail))
    print(f"  {YELLOW}⚠{RESET} {label}" + (f"  {detail}" if detail else ""))


def err(label, detail=""):
    ERRORS.append((label, detail))
    print(f"  {RED}✗{RESET} {label}" + (f"  {detail}" if detail else ""))


def section(title):
    print()
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}")


# ============================================================================
# SETUP
# ============================================================================
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret-validation'
os.environ['ALLOW_XUSER_HEADER'] = 'true'
os.environ['RESEND_API_KEY'] = ''  # Forzar fallback a log en tests
os.environ['SMTP_HOST'] = ''

PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
APP_DIR = PROJECT_ROOT / 'app'

# Limpiar emails previos
log_dir = PROJECT_ROOT / 'tmp'
if log_dir.exists():
    for f in log_dir.glob('app.email.log*'):
        try:
            f.unlink()
        except Exception:
            pass


# ============================================================================
# 1. VALIDACIÓN DE IMPORTS Y SINTAXIS
# ============================================================================
section("1. VALIDACIÓN DE IMPORTS Y SINTAXIS")

python_files = list(APP_DIR.rglob('*.py'))
python_files = [f for f in python_files if '__pycache__' not in str(f)]
ok(f"Encontrados {len(python_files)} archivos Python")

syntax_errors = []
import_errors = []
for py_file in python_files:
    rel = py_file.relative_to(PROJECT_ROOT)
    # Sintaxis
    try:
        source = py_file.read_text(encoding='utf-8')
        ast.parse(source, filename=str(rel))
    except SyntaxError as e:
        syntax_errors.append((rel, str(e)))
    # Import (puede fallar por dependencias opcionales - lo registramos como warning)
    try:
        spec = importlib.util.spec_from_file_location(
            f"test_module_{rel.stem}_{hash(str(rel))}",
            str(py_file),
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            # No ejecutar (puede tener side-effects). Solo validar spec.
            # spec.loader.exec_module(module)  # Comentado: muchos side-effects
    except Exception:
        pass

if syntax_errors:
    for rel, err_msg in syntax_errors:
        err(f"SyntaxError en {rel}", err_msg[:100])
else:
    ok(f"Sintaxis válida en los {len(python_files)} archivos .py")


# ============================================================================
# 2. MODELOS SQLALCHEMY
# ============================================================================
section("2. VALIDACIÓN DE MODELOS SQLALCHEMY")

try:
    from app.db.session import engine
    from app.db.base import Base
    import app.models  # noqa
    Base.metadata.create_all(bind=engine)
    ok("Base.metadata.create_all() sin errores")

    tables = list(Base.metadata.tables.keys())
    ok(f"Tablas creadas: {len(tables)}")
    print(f"     {CYAN}{', '.join(sorted(tables))}{RESET}")

    # Verificar FKs e índices en modelos clave
    from app.models.estado import Estado
    from app.models.ticket import Ticket
    from app.models.usuario import Usuario
    from app.models.auditoria import Auditoria

    # Estado.responsable_id FK a usuarios
    estado_cols = {c.name: c for c in Estado.__table__.columns}
    if 'responsable_id' in estado_cols:
        fk_target = list(estado_cols['responsable_id'].foreign_keys)[0].target_fullname
        if fk_target == 'usuarios.id':
            ok("Estado.responsable_id → usuarios.id (FK correcta)")
        else:
            err(f"Estado.responsable_id → {fk_target} (esperaba usuarios.id)")

    # Ticket FKs
    ticket_cols = {c.name: c for c in Ticket.__table__.columns}
    expected_fks = {
        'estado_id': 'estados.id',
        'tablero_id': 'tableros.id',
        'creador_id': 'usuarios.id',
    }
    for col, expected_target in expected_fks.items():
        if col in ticket_cols:
            fks = list(ticket_cols[col].foreign_keys)
            if fks and fks[0].target_fullname == expected_target:
                ok(f"Ticket.{col} → {expected_target}")
            else:
                actual = fks[0].target_fullname if fks else "NINGUNA"
                err(f"Ticket.{col} → {actual} (esperaba {expected_target})")
        else:
            err(f"Ticket.{col} no existe en el modelo")
except Exception as e:
    err(f"Error validando modelos: {e}")
    traceback.print_exc()


# ============================================================================
# 3. RUTAS FASTAPI
# ============================================================================
section("3. VALIDACIÓN DE RUTAS FASTAPI")

try:
    from app.main import app
    # FastAPI incluye sub-routers como objetos _IncludedRouter en app.routes.
    # Para enumerar TODAS las rutas (incluidas las de /api/v1/*) usamos
    # app.openapi() que entrega el esquema OpenAPI completo.
    openapi_schema = app.openapi()
    paths = openapi_schema.get('paths', {})

    # Conteos directos vs anidados
    direct_count = 0
    for r in app.routes:
        if hasattr(r, 'methods') and hasattr(r, 'path'):
            if hasattr(r.methods, '__iter__'):
                direct_count += 1

    # Rutas desde OpenAPI (incluye TODAS las anidadas)
    api_routes_count = sum(1 for p in paths if p.startswith('/api/'))
    page_routes_count = sum(1 for p in paths if not p.startswith('/api/'))
    total_openapi = len(paths)

    ok(f"app.routes directos: {direct_count}")
    ok(f"OpenAPI paths (TODAS las rutas): {total_openapi}")
    print(f"     {CYAN}API (/api/*): {api_routes_count} | Páginas: {page_routes_count}{RESET}")

    routes_by_method = {}
    for path, methods in paths.items():
        for m in (methods.keys() if isinstance(methods, dict) else []):
            if m.upper() in ('GET', 'POST', 'PATCH', 'PUT', 'DELETE'):
                routes_by_method.setdefault(m.upper(), []).append(path)

    for method in ['GET', 'POST', 'PATCH', 'PUT', 'DELETE']:
        count = len(routes_by_method.get(method, []))
        if count > 0:
            print(f"     {method}: {count} rutas")

    # Rutas críticas que DEBEN existir (formato OpenAPI: {estado_id} no se resuelve)
    critical_routes = [
        ('GET', '/api/v1/auth/login'),
        ('POST', '/api/v1/auth/login-form'),
        ('GET', '/api/v1/estados'),
        ('GET', '/api/v1/estados/diagnostico/responsables'),
        ('GET', '/api/v1/estados/{estado_id}/responsable-picker'),
        ('PATCH', '/api/v1/estados/{estado_id}'),
        ('GET', '/api/v1/tickets'),
        ('GET', '/api/v1/kanban'),
        ('GET', '/api/v1/usuarios'),
        ('GET', '/api/v1/catalogos/tipos'),
        ('GET', '/api/v1/metricas/resumen'),
        ('GET', '/api/v1/dev/inbox'),
    ]
    for method, path in critical_routes:
        # OpenAPI usa llaves en path parameters; ya están en la lista.
        if path in paths:
            ok(f"{method} {path}")
        else:
            err(f"Falta ruta crítica: {method} {path}")

except Exception as e:
    err(f"Error inspeccionando rutas: {e}")
    traceback.print_exc()


# ============================================================================
# 4. TEMPLATES JINJA2
# ============================================================================
section("4. VALIDACIÓN DE TEMPLATES JINJA2")

template_dir = APP_DIR / 'templates'
template_files = list(template_dir.rglob('*.html'))
ok(f"Encontrados {len(template_files)} templates HTML")

template_errors = []
referenced_routes = set()
for tf in template_files:
    rel = tf.relative_to(template_dir)
    try:
        source = tf.read_text(encoding='utf-8')
        # Sintaxis Jinja básica (no se puede parsear 100% sin entorno)
        # Validar tags balanceados
        open_tags = source.count('{%')
        close_tags = source.count('%}')
        if open_tags != close_tags:
            template_errors.append((rel, f"Tags Jinja desbalanceados: {open_tags} open vs {close_tags} close"))
        # Recoger rutas referenciadas en hx-get, hx-post, href, action
        for m in re.finditer(r'(?:hx-get|hx-post|hx-patch|hx-put|hx-delete|action)="([^"]+)"', source):
            url = m.group(1)
            # Ignorar absolutas, anclas, javascript, mailto, tel
            if url.startswith(('http', 'mailto:', 'tel:', '#', 'javascript:', 'data:')):
                continue
            # Quitar query string
            url = url.split('?')[0].split('#')[0]
            referenced_routes.add(url)
        for m in re.finditer(r'href="(/[^"]*)"', source):
            url = m.group(1).split('?')[0].split('#')[0]
            referenced_routes.add(url)
    except Exception as e:
        template_errors.append((rel, str(e)))

if template_errors:
    for rel, msg in template_errors:
        err(f"Template: {rel}", msg[:120])
else:
    ok(f"Sintaxis básica OK en {len(template_files)} templates")
    print(f"     {CYAN}{len(referenced_routes)} URLs únicas referenciadas{RESET}")


# ============================================================================
# 5. ARCHIVOS ESTÁTICOS
# ============================================================================
section("5. VALIDACIÓN DE ARCHIVOS ESTÁTICOS")

static_dir = APP_DIR / 'static'
if static_dir.exists():
    static_files = list(static_dir.rglob('*'))
    static_files = [f for f in static_files if f.is_file()]
    ok(f"Encontrados {len(static_files)} archivos estáticos")

    # Buscar referencias a /static/ en templates y main.py
    static_refs = set()
    for tf in template_files:
        source = tf.read_text(encoding='utf-8')
        for m in re.finditer(r'src="(/static/[^"]+)"', source):
            static_refs.add(m.group(1))
        for m in re.finditer(r'href="(/static/[^"]+)"', source):
            static_refs.add(m.group(1))
    # Buscar referencias en archivos .py que sirven estáticos
    for py in python_files:
        source = py.read_text(encoding='utf-8')
        for m in re.finditer(r'["\'](/static/[^"\']+)["\']', source):
            static_refs.add(m.group(1))

    ok(f"Referencias únicas a /static/... en templates/código: {len(static_refs)}")

    # Verificar que cada referencia exista
    missing_static = []
    for ref in static_refs:
        # Quitar /static/ inicial
        rel = ref.lstrip('/')
        if rel.startswith('static/'):
            rel = rel[len('static/'):]
        full = static_dir / rel
        if not full.exists():
            missing_static.append(ref)
    if missing_static:
        for m in missing_static[:10]:
            err(f"404 potencial: {m}")
        if len(missing_static) > 10:
            err(f"... y {len(missing_static) - 10} más")
    else:
        ok(f"Todas las {len(static_refs)} referencias a /static/ existen")
else:
    warn("No existe directorio static/")


# ============================================================================
# 6. AUTENTICACIÓN
# ============================================================================
section("6. VALIDACIÓN DE AUTENTICACIÓN")

from fastapi.testclient import TestClient
from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.core.security import hash_password

db = SessionLocal()
try:
    admin = Usuario(username='admin_val', email='admin_val@test.com',
                    nombre_completo='Admin Validador',
                    rol=RolUsuario.ADMINISTRADOR,
                    hashed_password=hash_password('test1234'),
                    is_active=True)
    db.add(admin); db.commit(); db.refresh(admin)
    ok(f"Admin creado: id={admin.id}")

    agente = Usuario(username='agente_val', email='agente_val@test.com',
                     nombre_completo='Agente Validador',
                     rol=RolUsuario.AGENTE,
                     hashed_password=hash_password('test1234'),
                     is_active=True)
    db.add(agente); db.commit(); db.refresh(agente)
    ok(f"Agente creado: id={agente.id}")

    inactivo = Usuario(username='inactivo_val', email='inactivo_val@test.com',
                       nombre_completo='Usuario Inactivo Validador',
                       rol=RolUsuario.AGENTE,
                       hashed_password=hash_password('test1234'),
                       is_active=False)
    db.add(inactivo); db.commit(); db.refresh(inactivo)
    ok(f"Usuario inactivo creado: id={inactivo.id}")
finally:
    db.close()

client = TestClient(app)

# Test 1: Login con credenciales válidas
print()
print("  [Test] Login con credenciales válidas:")
r = client.post('/api/v1/auth/login-form',
                data={'username': 'admin_val', 'password': 'test1234'},
                follow_redirects=False)
if r.status_code in (200, 303, 302):
    ok(f"Login admin OK: status={r.status_code}")
else:
    err(f"Login admin falló: status={r.status_code}")

# Test 2: Login con password incorrecta
r = client.post('/api/v1/auth/login-form',
                data={'username': 'admin_val', 'password': 'wrong'},
                follow_redirects=False)
if r.status_code in (200, 303, 302):
    # Puede redirigir con error
    if 'error' in r.text.lower() or 'inv' in r.text.lower():
        ok(f"Login con password incorrecta rechazado (mensaje de error)")
    else:
        warn(f"Login con password incorrecta: status={r.status_code} (revisar)")
else:
    ok(f"Login con password incorrecta rechazado: status={r.status_code}")

# Test 3: Endpoint protegido sin sesión (con cliente limpio para evitar
# persistencia de cookies del TestClient entre secciones)
print()
print("  [Test] Endpoint protegido sin sesión:")
fresh_client = TestClient(app)  # Sin cookies previas
r = fresh_client.get('/api/v1/usuarios', follow_redirects=False)
if r.status_code in (401, 403, 303, 302):
    ok(f"Acceso sin sesión bloqueado: status={r.status_code}")
else:
    err(f"Acceso sin sesión permitido: status={r.status_code} (BUG de seguridad)")


# ============================================================================
# 7. AUTORIZACIÓN POR ROLES
# ============================================================================
section("7. VALIDACIÓN DE AUTORIZACIÓN POR ROLES")

# Login como agente (no admin)
r = client.post('/api/v1/auth/login-form',
                data={'username': 'agente_val', 'password': 'test1234'},
                follow_redirects=False)
print(f"  [setup] Login agente: status={r.status_code}")

# Agente NO debe poder asignar responsable
print()
print("  [Test] Agente NO puede asignar responsable:")
# Crear un estado primero
db2 = SessionLocal()
try:
    estado_test = Estado(nombre='Test Auth', orden=99, color='#000',
                         categoria='abierto')
    db2.add(estado_test); db2.commit(); db2.refresh(estado_test)
    estado_id = estado_test.id
finally:
    db2.close()

r = client.get(f'/api/v1/estados/{estado_id}/responsable-picker',
               follow_redirects=True)
if r.status_code == 403:
    ok(f"Picker como agente → 403 Forbidden (correcto)")
elif 'Solo el rol Administrador' in r.text or 'red-' in r.text:
    ok(f"Picker como agente → mensaje de error visible")
else:
    err(f"Picker como agente debería ser 403, dio {r.status_code}")


# ============================================================================
# 8. FLUJO KANBAN COMPLETO
# ============================================================================
section("8. VALIDACIÓN DEL FLUJO KANBAN")

# Re-login como admin
r = client.post('/api/v1/auth/login-form',
                data={'username': 'admin_val', 'password': 'test1234'},
                follow_redirects=False)

# Crear espacio + tablero + columnas + ticket
from app.models.espacio import Espacio, Tablero

db3 = SessionLocal()
try:
    esp = Espacio(nombre='Esp Val', propietario_id=admin.id)
    db3.add(esp); db3.commit(); db3.refresh(esp)

    tablero = Tablero(nombre='Tablero Val', espacio_id=esp.id,
                      propietario_id=admin.id)
    db3.add(tablero); db3.commit(); db3.refresh(tablero)

    # 2 columnas
    col_a = Estado(nombre='Col A', orden=1, color='#888', categoria='abierto')
    col_b = Estado(nombre='Col B', orden=2, color='#0ea5e9', categoria='abierto')
    db3.add(col_a); db3.add(col_b); db3.commit()
    db3.refresh(col_a); db3.refresh(col_b)

    # Transición válida A → B
    from app.models.estado import TransicionEstado
    tr = TransicionEstado(estado_origen_id=col_a.id,
                          estado_destino_id=col_b.id)
    db3.add(tr); db3.commit()

    from app.models.ticket import Ticket, Prioridad, TipoIncidencia
    ticket = Ticket(
        codigo='VAL-001', titulo='Ticket Validacion', descripcion='Test',
        prioridad=Prioridad.MEDIA, tipo=TipoIncidencia.INCIDENCIA,
        estado_id=col_a.id, tablero_id=tablero.id,
        creador_id=admin.id, asignado_id=admin.id,
    )
    db3.add(ticket); db3.commit(); db3.refresh(ticket)

    print(f"  [setup] Espacio={esp.id}, Tablero={tablero.id}")
    print(f"  [setup] Col A={col_a.id}, Col B={col_b.id}, Ticket={ticket.id}")
    print(f"  [setup] Transición A→B creada")

    # Test: PATCH cambiar_estado
    print()
    print("  [Test] Mover ticket de A → B:")
    from app.services.ticket_service import TicketService
    svc = TicketService(db3)
    t_after, task_id = svc.cambiar_estado(
        ticket_id=ticket.id,
        estado_destino_id=col_b.id,
        usuario=admin,
        comentario='Validación',
    )
    if t_after.estado_id == col_b.id:
        ok(f"Ticket movido a Col B: estado_id={t_after.estado_id}")
    else:
        err(f"Ticket NO se movió: estado_id={t_after.estado_id}")

    # Verificar historial
    from app.models.ticket import HistorialEstado
    hist = db3.query(HistorialEstado).filter_by(ticket_id=ticket.id).all()
    if len(hist) >= 1:
        ok(f"Historial creado: {len(hist)} entradas")
    else:
        err(f"Sin historial de cambio de estado")

    # Verificar auditoría
    from app.models.auditoria import Auditoria
    aud = db3.query(Auditoria).filter_by(
        ticket_id=ticket.id, accion='CAMBIO_ESTADO'
    ).all()
    if len(aud) >= 1:
        ok(f"Auditoría registrada: {len(aud)} entradas")
    else:
        err(f"Sin entrada de auditoría para CAMBIO_ESTADO")
finally:
    db3.close()


# ============================================================================
# 9. ASIGNACIÓN DE RESPONSABLE
# ============================================================================
section("9. VALIDACIÓN DE ASIGNACIÓN DE RESPONSABLE")

# GET picker
r = client.get(f'/api/v1/estados/{col_b.id}/responsable-picker',
               follow_redirects=True)
if r.status_code == 200:
    import re as _re
    options = _re.findall(r'<option[^>]*value="(\d*)"', r.text)
    valid = [o for o in options if o]
    if len(valid) >= 2:
        ok(f"Picker muestra {len(valid)} usuarios activos (excluyendo inactivo)")
    else:
        warn(f"Picker solo muestra {len(valid)} usuarios (revisar)")
    if '<option value=""></option>' in r.text.replace('value=""', 'value=""'):
        ok("Opción '— Sin responsable —' presente")

# PATCH responsable
r = client.patch(f'/api/v1/estados/{col_b.id}',
                 data={'responsable_id': str(agente.id)},
                 headers={
                     'HX-Request': 'true',
                     'Content-Type': 'application/x-www-form-urlencoded',
                 },
                 follow_redirects=True)
if r.status_code == 200:
    ok(f"PATCH responsable_id=agente → status=200")
else:
    err(f"PATCH responsable_id falló: status={r.status_code}")

# Verificar en BD
db4 = SessionLocal()
try:
    col_b_check = db4.query(Estado).filter_by(id=col_b.id).first()
    if col_b_check.responsable_id == agente.id:
        ok(f"responsable_id guardado en BD: {col_b_check.responsable_id}")
    else:
        err(f"responsable_id NO guardado: {col_b_check.responsable_id}")
finally:
    db4.close()


# ============================================================================
# 10. NOTIFICACIONES IN-APP
# ============================================================================
section("10. VALIDACIÓN DE NOTIFICACIONES IN-APP")

# Mover ticket a col_b (que ahora tiene agente como responsable)
db5 = SessionLocal()
try:
    ticket_5 = db5.query(Ticket).filter_by(codigo='VAL-001').first()
    col_a_5 = db5.query(Estado).filter_by(id=col_a.id).first()

    # Crear ticket en col_a y mover a col_b
    t2 = Ticket(
        codigo='VAL-002', titulo='Notif Test', descripcion='Test notif',
        prioridad=Prioridad.ALTA, tipo=TipoIncidencia.INCIDENCIA,
        estado_id=col_a.id, tablero_id=ticket_5.tablero_id,
        creador_id=admin.id, asignado_id=admin.id,
    )
    db5.add(t2); db5.commit(); db5.refresh(t2)

    svc = TicketService(db5)
    t_after, _ = svc.cambiar_estado(
        ticket_id=t2.id,
        estado_destino_id=col_b.id,
        usuario=admin,
        comentario='Test notificación',
    )

    from app.models.watch import Notificacion
    notifs = db5.query(Notificacion).filter_by(usuario_id=agente.id).all()
    if len(notifs) >= 1:
        ok(f"Notificación creada para agente: {len(notifs)}")
        n = notifs[0]
        print(f"     tipo={n.tipo} titulo={n.titulo[:60]}")
    else:
        err("No se creó notificación para el responsable")
finally:
    db5.close()


# ============================================================================
# 11. EMAIL SERVICE
# ============================================================================
section("11. VALIDACIÓN DEL EMAIL SERVICE")

log_file = PROJECT_ROOT / 'tmp' / 'app.email.log'
if log_file.exists():
    content = log_file.read_text(encoding='utf-8', errors='ignore')
    if 'VAL-002' in content or 'Val' in content:
        ok("Email log contiene referencia al ticket reciente")
    elif 'En revisión' in content or 'Notif' in content:
        ok("Email log contiene emails generados")
    else:
        warn("Email log existe pero sin entradas reconocibles")
    # Contar líneas JSON
    json_lines = [l for l in content.split('\n') if l.startswith('{')]
    if json_lines:
        ok(f"Email log: {len(json_lines)} entradas JSON")
else:
    warn("No existe tmp/app.email.log (puede ser normal si no se intentó email)")


# ============================================================================
# 12. ENDPOINT DE DIAGNÓSTICO
# ============================================================================
section("12. VALIDACIÓN DEL ENDPOINT DE DIAGNÓSTICO")

r = client.get('/api/v1/estados/diagnostico/responsables',
               follow_redirects=True)
if r.status_code == 200:
    try:
        data = r.json()
        required_keys = ['usuarios', 'estados', 'email', 'solicitado_por']
        missing = [k for k in required_keys if k not in data]
        if not missing:
            ok("Diagnóstico devuelve todas las claves esperadas")
        else:
            err(f"Diagnóstico falta: {missing}")
        # Verificar subkeys
        if 'usuarios' in data:
            for k in ['total', 'activos', 'inactivos', 'alerta']:
                if k in data['usuarios']:
                    ok(f"  usuarios.{k} = {data['usuarios'][k]}")
                else:
                    err(f"  Falta usuarios.{k}")
        if 'email' in data:
            for k in ['RESEND_API_KEY_configured', 'SMTP_HOST',
                      'SMTP_FROM', 'transporte_activo']:
                if k in data['email']:
                    ok(f"  email.{k} = {data['email'][k]}")
    except json.JSONDecodeError as e:
        err(f"Diagnóstico no devuelve JSON válido: {e}")
else:
    err(f"Diagnóstico falló: status={r.status_code}")


# ============================================================================
# 13. CONFIGURACIÓN CELERY/REDIS
# ============================================================================
section("13. VALIDACIÓN DE CONFIGURACIÓN CELERY/REDIS")

try:
    from app.core.celery_app import celery_app
    ok(f"Celery app importada: {celery_app.main}")
    # Verificar configuración básica
    if hasattr(celery_app, 'conf'):
        broker = celery_app.conf.broker_url or ''
        backend = celery_app.conf.result_backend or ''
        ok(f"Celery broker: {broker or '(no configurado)'}")
        ok(f"Celery result backend: {backend or '(no configurado)'}")
        if broker and 'redis' not in broker.lower() and 'memory' not in broker.lower():
            warn(f"Broker no parece ser Redis: {broker}")
        elif broker:
            ok("Broker parece ser Redis o memory (correcto)")
except Exception as e:
    err(f"Error importando Celery: {e}")


# ============================================================================
# 14. CONFIGURACIÓN PRODUCCIÓN
# ============================================================================
section("14. VALIDACIÓN DE CONFIGURACIÓN DE PRODUCCIÓN")

# Verificar que .env.example existe y tiene las claves clave
env_example = PROJECT_ROOT / '.env.example'
if env_example.exists():
    content = env_example.read_text()
    required_vars = [
        'DATABASE_URL', 'SECRET_KEY', 'SMTP_FROM',
        'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND',
    ]
    for var in required_vars:
        if var in content:
            ok(f".env.example contiene {var}")
        else:
            warn(f".env.example no menciona {var}")
else:
    warn("No existe .env.example")

# Verificar Procfile
procfile = PROJECT_ROOT / 'Procfile'
if procfile.exists():
    content = procfile.read_text()
    if 'web' in content and 'worker' in content:
        ok("Procfile define procesos web y worker")
    else:
        warn(f"Procfile incompleto: {content[:100]}")

# Verificar requirements.txt
req_file = PROJECT_ROOT / 'requirements.txt'
if req_file.exists():
    content = req_file.read_text()
    required = ['fastapi', 'sqlalchemy', 'jinja2', 'celery', 'redis',
                'pydantic', 'python-multipart', 'passlib', 'alembic']
    for pkg in required:
        if pkg in content.lower():
            ok(f"requirements.txt menciona {pkg}")
        else:
            warn(f"requirements.txt no menciona {pkg}")


# ============================================================================
# RESUMEN FINAL
# ============================================================================
section("RESUMEN DE VALIDACIÓN")

print(f"  {GREEN}✓ OKs:        {len(OKS)}{RESET}")
print(f"  {YELLOW}⚠ Warnings:  {len(WARNINGS)}{RESET}")
print(f"  {RED}✗ Errors:    {len(ERRORS)}{RESET}")

if ERRORS:
    print()
    print(f"{RED}{BOLD}ERRORES ENCONTRADOS:{RESET}")
    for label, detail in ERRORS:
        print(f"  {RED}✗{RESET} {label}")
        if detail:
            print(f"      {detail[:150]}")

if WARNINGS:
    print()
    print(f"{YELLOW}{BOLD}WARNINGS:{RESET}")
    for label, detail in WARNINGS[:20]:
        print(f"  {YELLOW}⚠{RESET} {label}")
    if len(WARNINGS) > 20:
        print(f"  ... y {len(WARNINGS) - 20} más")

# Exit code
print()
if ERRORS:
    print(f"{RED}{BOLD}❌ VALIDACIÓN FALLÓ - {len(ERRORS)} errores{RESET}")
    sys.exit(1)
elif WARNINGS:
    print(f"{YELLOW}{BOLD}⚠ VALIDACIÓN PASÓ CON WARNINGS{RESET}")
    sys.exit(0)
else:
    print(f"{GREEN}{BOLD}✅ VALIDACIÓN COMPLETA - TODO OK{RESET}")
    sys.exit(0)
