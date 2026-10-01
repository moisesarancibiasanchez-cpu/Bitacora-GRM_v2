#!/usr/bin/env python3
"""
Test específico del FIX: asignación de responsable en columnas ANTIGUAS.

Escenario: existen columnas en la BD que fueron creadas ANTES de que se
añadiera la columna `responsable_id` al modelo. Estas columnas tienen
`responsable_id=NULL` y nunca han sido tocadas por la lógica del picker.

El test verifica que:
  1. El picker devuelve un <select> dentro de un <form> (NO usa atributo form="").
  2. El <select> usa hx-trigger="change" + hx-include="this" (no onchange JS).
  3. El wrapper tiene las clases correctas (flex-wrap + justify-between).
  4. PATCH funciona y persiste responsable_id.
  5. El contador de tickets se persiste en el header refrescado.
  6. Las iniciales son correctas para nombres de una sola palabra.
"""
import os, sys, tempfile, logging
logging.disable(logging.CRITICAL)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
import warnings
warnings.filterwarnings('ignore')

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['ALLOW_XUSER_HEADER'] = 'true'

from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.core.security import hash_password

# === SETUP ===
db = SessionLocal()
try:
    admin = Usuario(username='admin', email='admin@test.com',
                    nombre_completo='Administrador Sistema',
                    rol=RolUsuario.ADMINISTRADOR,
                    hashed_password=hash_password('test1234'),
                    is_active=True)
    db.add(admin); db.commit(); db.refresh(admin)

    # Usuario con nombre de una sola palabra (caso edge para iniciales)
    single_name = Usuario(username='solo', email='solo@test.com',
                          nombre_completo='Madonna',  # 1 sola palabra
                          rol=RolUsuario.AGENTE,
                          hashed_password=hash_password('x'),
                          is_active=True)
    db.add(single_name); db.commit(); db.refresh(single_name)

    # Usuario con nombre completo normal
    full_name = Usuario(username='full', email='full@test.com',
                        nombre_completo='Juan Pérez García',
                        rol=RolUsuario.AGENTE,
                        hashed_password=hash_password('x'),
                        is_active=True)
    db.add(full_name); db.commit(); db.refresh(full_name)

    # === COLUMNAS "ANTIGUAS" (creadas antes del feature responsable) ===
    # Se simula creando columnas con responsable_id=None explícito.
    # Estos son los casos que reporta el usuario: no se pueden asignar.
    columna_vieja_1 = Estado(nombre='BACKLOG', orden=1, color='#94a3b8',
                             categoria='abierto', responsable_id=None)
    columna_vieja_2 = Estado(nombre='EN CURSO', orden=2, color='#0ea5e9',
                             categoria='en_curso', responsable_id=None)
    columna_vieja_3 = Estado(nombre='BLOQUEADO', orden=3, color='#ef4444',
                             categoria='espera', responsable_id=None)
    db.add_all([columna_vieja_1, columna_vieja_2, columna_vieja_3])
    db.commit()
    for c in [columna_vieja_1, columna_vieja_2, columna_vieja_3]:
        db.refresh(c)

    # Agregar tickets a las columnas para verificar el count persistido
    from app.models.espacio import Espacio, Tablero
    esp = Espacio(nombre='Test Espacio', propietario_id=admin.id)
    db.add(esp); db.commit(); db.refresh(esp)
    tab = Tablero(nombre='Tablero Test', espacio_id=esp.id,
                  propietario_id=admin.id)
    db.add(tab); db.commit(); db.refresh(tab)

    # 3 tickets en BACKLOG, 1 en EN CURSO, 0 en BLOQUEADO
    for i, (codigo, estado) in enumerate([
        ('TKT-001', columna_vieja_1),
        ('TKT-002', columna_vieja_1),
        ('TKT-003', columna_vieja_1),
        ('TKT-004', columna_vieja_2),
    ]):
        t = Ticket(codigo=codigo, titulo=f'Ticket {codigo}',
                   descripcion='Test', prioridad=Prioridad.MEDIA,
                   tipo=TipoIncidencia.INCIDENCIA, estado_id=estado.id,
                   tablero_id=tab.id, creador_id=admin.id,
                   asignado_id=admin.id)
        db.add(t)
    db.commit()

    print(f"[setup] Columnas antiguas creadas: {[c.id for c in [columna_vieja_1, columna_vieja_2, columna_vieja_3]]}")
    print(f"[setup] Tickets creados: 3 en BACKLOG, 1 en EN CURSO, 0 en BLOQUEADO")
    print(f"[setup] Usuarios: admin={admin.id}, solo(1 nombre)={single_name.id}, full={full_name.id}")

    col_ids = {
        'backlog': columna_vieja_1.id,
        'en_curso': columna_vieja_2.id,
        'bloqueado': columna_vieja_3.id,
    }
finally:
    db.close()

# === TEST ===
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form',
                 data={'username': 'admin', 'password': 'test1234'},
                 follow_redirects=False)
assert r.status_code == 200, f"Login failed: {r.status_code}"
print(f"\n[PASS] Login admin OK")

# TEST 1: Verificar que el picker NO usa el patrón "atributo form=""
print("\n" + "="*70)
print("TEST 1: El picker NO usa el atributo HTML5 form=''")
print("="*70)
r = client.get(f'/api/v1/estados/{col_ids["backlog"]}/responsable-picker')
assert r.status_code == 200, f"Picker failed: {r.status_code}"
html = r.text
assert 'form="form-resp-' not in html, "REGRESIÓN: aún usa atributo form='' separado"
assert 'onchange="this.form.requestSubmit()"' not in html, "REGRESIÓN: aún usa onchange inline"
print(f"[PASS] Picker NO usa atributo form='' ni onchange inline")

# TEST 2: El <select> está DENTRO del <form>
print("\n" + "="*70)
print("TEST 2: El <select> está DENTRO del <form>")
print("="*70)
import re
# Buscar el form con id form-resp-X y verificar que contiene un <select>
m = re.search(r'<form[^>]*id="form-resp-\d+"[^>]*>(.*?)</form>', html, re.DOTALL)
assert m, "No se encontró el form del picker"
form_content = m.group(1)
assert '<select' in form_content, "REGRESIÓN: <select> no está dentro del <form>"
print(f"[PASS] <select> está dentro del <form>")

# TEST 3: El <select> usa hx-trigger="change" + hx-include="this"
print("\n" + "="*70)
print("TEST 3: <select> usa hx-trigger='change' + hx-include='this'")
print("="*70)
assert 'hx-trigger="change"' in html, "Falta hx-trigger='change' en el select"
assert 'hx-include="this"' in html, "Falta hx-include='this' en el select"
assert 'hx-get=' in html and '/picker-commit' in html, "Falta endpoint /picker-commit"
print(f"[PASS] Select usa HTMX nativo (hx-trigger + hx-include)")

# TEST 4: El wrapper tiene las clases correctas (flex-wrap + justify-between)
print("\n" + "="*70)
print("TEST 4: Wrapper del picker tiene flex-wrap y justify-between")
print("="*70)
assert 'flex-wrap' in html, "Falta flex-wrap en el wrapper del picker"
assert 'justify-between' in html, "Falta justify-between en el wrapper del picker"
print(f"[PASS] Wrapper tiene flex-wrap y justify-between")

# TEST 5: GET /picker-commit funciona como el nuevo endpoint
print("\n" + "="*70)
print("TEST 5: GET /picker-commit persiste responsable_id")
print("="*70)
r = client.get(f'/api/v1/estados/{col_ids["backlog"]}/picker-commit',
               params={'responsable_id': str(full_name.id)})
assert r.status_code == 200, f"picker-commit failed: {r.status_code}"

db2 = SessionLocal()
try:
    e = db2.query(Estado).filter_by(id=col_ids["backlog"]).first()
    assert e.responsable_id == full_name.id, f"responsable_id no se persistió: {e.responsable_id}"
    print(f"[PASS] responsable_id persistido correctamente: {e.responsable_id}")
finally:
    db2.close()

# TEST 6: El header refrescado tiene el contador de tickets persistido
print("\n" + "="*70)
print("TEST 6: Header refrescado persiste el contador de tickets")
print("="*70)
assert f'id="count-{col_ids["backlog"]}">3<' in r.text, \
    f"Falta el contador persistido en el header. Buscado: id=\"count-{col_ids['backlog']}\">3<"
print(f"[PASS] Contador persistido en el header (3 tickets)")

# TEST 7: Las iniciales se calculan correctamente para 1 sola palabra
print("\n" + "="*70)
print("TEST 7: Iniciales correctas para usuario con 1 sola palabra")
print("="*70)
# Limpiar responsable primero
client.get(f'/api/v1/estados/{col_ids["bloqueado"]}/picker-commit',
           params={'responsable_id': ''})
# Asignar usuario "solo" (nombre: Madonna)
r = client.get(f'/api/v1/estados/{col_ids["bloqueado"]}/picker-commit',
               params={'responsable_id': str(single_name.id)})
assert r.status_code == 200
# Debe mostrar "M" (solo la primera letra, no "M " con espacio)
# El render usa una sola letra para nombres de 1 palabra
assert '>M</span>' in r.text, "Las iniciales para 1 sola palabra son incorrectas"
assert 'Madonna' in r.text, "El nombre completo debe estar en el title"
print(f"[PASS] Iniciales correctas para 'Madonna' (1 sola palabra)")

# TEST 8: Las iniciales se calculan correctamente para nombre completo
print("\n" + "="*70)
print("TEST 8: Iniciales correctas para nombre completo")
print("="*70)
client.get(f'/api/v1/estados/{col_ids["en_curso"]}/picker-commit',
           params={'responsable_id': ''})
r = client.get(f'/api/v1/estados/{col_ids["en_curso"]}/picker-commit',
               params={'responsable_id': str(full_name.id)})
assert r.status_code == 200
# Juan Pérez García -> JP
assert '>JP</span>' in r.text, "Las iniciales para nombre completo son incorrectas"
assert 'Juan Pérez García' in r.text, "El nombre completo debe estar en el title"
print(f"[PASS] Iniciales correctas para 'Juan Pérez García' (JP)")

# TEST 9: Limpiar responsable (caso None)
print("\n" + "="*70)
print("TEST 9: Limpiar responsable (responsable_id='')")
print("="*70)
r = client.get(f'/api/v1/estados/{col_ids["en_curso"]}/picker-commit',
               params={'responsable_id': ''})
assert r.status_code == 200
db3 = SessionLocal()
try:
    e = db3.query(Estado).filter_by(id=col_ids["en_curso"]).first()
    assert e.responsable_id is None, f"responsable_id debería ser None: {e.responsable_id}"
    # El header debe mostrar el botón "responsable" (no el badge)
    assert 'Asignar responsable a esta columna' in r.text, \
        "Después de limpiar, debe mostrarse el botón 'responsable'"
    print(f"[PASS] Responsable limpiado correctamente")
finally:
    db3.close()

# TEST 10: hx-vals consistente en el header refrescado (siempre vacío, no null)
print("\n" + "="*70)
print("TEST 10: hx-vals usa string vacío consistente")
print("="*70)
# Re-asignar para tener badge
client.get(f'/api/v1/estados/{col_ids["en_curso"]}/picker-commit',
           params={'responsable_id': str(full_name.id)})
r = client.get(f'/api/v1/estados/{col_ids["en_curso"]}/header')
assert r.status_code == 200
# El botón "×" debe tener hx-vals='{"responsable_id": ""}'
assert 'hx-vals=\'{"responsable_id": ""}\'' in r.text, \
    "El botón '×' debe usar hx-vals con string vacío consistente"
assert 'hx-vals=\'{"responsable_id": null}\'' not in r.text, \
    "REGRESIÓN: el botón '×' usa 'null' en vez de string vacío"
print(f"[PASS] hx-vals consistente (siempre string vacío)")

print("\n" + "="*70)
print("[OK] Todos los tests pasaron - Bug FIX verificado")
print("="*70)
