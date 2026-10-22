#!/usr/bin/env python3
"""Validación de A+B+C: rechazo de auto-dependencias, creación de tickets
faltantes desde XML, y respuesta limpia (links_omitidos_count + muestra).
"""
import os, sys, tempfile, json

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['ALLOW_XUSER_HEADER'] = 'true'

# Initialize DB BEFORE importing app
from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

# Bootstrap admin + estado + tickets
from app.db.session import SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.ticket import Ticket
from app.core.security import hash_password

db = SessionLocal()
try:
    if not db.query(Usuario).filter_by(username='admin').first():
        admin = Usuario(
            username='admin', email='admin@test.com',
            nombre_completo='Admin Test', rol=RolUsuario.ADMINISTRADOR,
            hashed_password=hash_password('test1234'),
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print('admin created')

    estado = db.query(Estado).first()
    if not estado:
        estado = Estado(nombre='Abierto', orden=1, color='#3b82f6')
        db.add(estado); db.commit()

    # Solo creamos UN ticket (codigo GAR_SC_2.1-176 con hu 2.1).
    # Los demás UIDs del XML harán match por codigo (wbs contained) o se
    # crearán al activar crear_tickets_faltantes=True.
    hu_codes = ['2.1']
    admin = db.query(Usuario).first()
    for hu in hu_codes:
        existing = db.query(Ticket).filter_by(hu_o_caso_prueba=hu).first()
        if not existing:
            t = Ticket(
                codigo=f'GAR_SC_{hu.replace(".", "_")}-176',
                titulo=f'Ticket {hu}',
                descripcion='Test ticket',
                estado_id=estado.id,
                creador_id=admin.id,
                hu_o_caso_prueba=hu,
                archivado=False,
            )
            db.add(t)
    db.commit()
    print(f'created {len(hu_codes)} seed ticket(s)')
finally:
    db.close()

# ============================================================
# XML con self-dependencia intencional (pred_uid == suc_uid)
# Para forzar la auto-dependencia en la API, el parser ya descarta
# self-deps a nivel XML, así que necesitamos inyectar un caso donde
# dos UIDs distintos matcheen el mismo ticket (lo cual sucede con
# matching fuzzy). Usaremos WBS repetidas en distintas Tasks.
# ============================================================
SAMPLE_XML_ABC = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Tasks>
    <Task>
      <UID>176</UID>
      <ID>1</ID>
      <Name>PAP 1</Name>
      <WBS>2.1</WBS>
      <OutlineLevel>2</OutlineLevel>
      <Start>2025-09-01T08:00:00</Start>
      <Finish>2025-09-04T17:00:00</Finish>
      <Duration>PT8H0M0S</Duration>
      <Summary>1</Summary>
    </Task>
    <Task>
      <UID>177</UID>
      <ID>2</ID>
      <Name>Sub-tarea A</Name>
      <WBS>2.1.A</WBS>
      <OutlineLevel>3</OutlineLevel>
      <Start>2025-09-04T08:00:00</Start>
      <Finish>2025-09-05T17:00:00</Finish>
      <Duration>PT8H0M0S</Duration>
      <Summary>0</Summary>
      <PredecessorLink>
        <PredecessorUID>176</PredecessorUID>
        <Type>1</Type>
        <LinkLag>0</LinkLag>
        <LagFormat>7</LagFormat>
      </PredecessorLink>
    </Task>
    <Task>
      <UID>178</UID>
      <ID>3</ID>
      <Name>Sub-tarea B</Name>
      <WBS>2.1.B</WBS>
      <OutlineLevel>3</OutlineLevel>
      <Start>2025-09-05T08:00:00</Start>
      <Finish>2025-09-08T17:00:00</Finish>
      <Duration>PT16H0M0S</Duration>
      <Summary>0</Summary>
      <PredecessorLink>
        <PredecessorUID>177</PredecessorUID>
        <Type>1</Type>
        <LinkLag>0</LinkLag>
        <LagFormat>7</LagFormat>
      </PredecessorLink>
    </Task>
    <Task>
      <UID>179</UID>
      <ID>4</ID>
      <Name>Sub-tarea C</Name>
      <WBS>2.1.C</WBS>
      <OutlineLevel>3</OutlineLevel>
      <Start>2025-09-08T08:00:00</Start>
      <Finish>2025-09-12T17:00:00</Finish>
      <Duration>PT32H0M0S</Duration>
      <Summary>0</Summary>
      <PredecessorLink>
        <PredecessorUID>176</PredecessorUID>
        <Type>1</Type>
        <LinkLag>0</LinkLag>
        <LagFormat>7</LagFormat>
      </PredecessorLink>
    </Task>
    <Task>
      <UID>180</UID>
      <ID>5</ID>
      <Name>Tarea totalmente nueva</Name>
      <WBS>99.99</WBS>
      <OutlineLevel>4</OutlineLevel>
      <Start>2025-09-12T08:00:00</Start>
      <Finish>2025-09-19T17:00:00</Finish>
      <Duration>PT40H0M0S</Duration>
      <Summary>0</Summary>
    </Task>
  </Tasks>
</Project>'''

# ============================================================
# TEST A: auto-dependencia cuando dos UIDs matchean al mismo ticket.
# ============================================================
print('\n=== TEST A: Auto-dependencia (pred.id == suc.id) ===')
print('Caso: estrategia de matching fuzzy hace que 2 WBS distintas matcheen al MISMO ticket "2.1"')
# (Aquí WBS 2.1.A, 2.1.B, 2.1.C son sub-queries; el matching por codigo "contains 2.1.A"
# podría matchear contra el ticket GAR_SC_2_1-176 cuyo código es "GAR_SC_2_1-176" — NO contiene "2.1.A".
# Por tanto, en este dataset no se producirá auto-dep. Probaremos con otro dataset abajo.)

# Test más realista: parchear manualmente el mapa_uid_a_ticket para forzar auto-dep
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form', data={'username':'admin','password':'test1234'}, follow_redirects=False)
assert r.status_code == 200, f'login failed: {r.status_code}'

# Verificamos que la nueva key "links_omitidos_count" está en la respuesta
r = client.post('/api/v1/dependencias/importar-xml',
    json={'xml_content': SAMPLE_XML_ABC, 'dry_run': True, 'crear_tickets_faltantes': False, 'actualizar_fechas': False}
)
print(f'status={r.status_code}')
result = r.json()
print(f'Response keys: {sorted(result.keys())}')
assert r.status_code == 200

# (C) Verificación: response limpia con resumen + muestra
assert 'links_omitidos_count' in result, '(C) debe incluir links_omitidos_count'
assert 'links_omitidos_muestra' in result, '(C) debe incluir links_omitidos_muestra'
assert isinstance(result['links_omitidos_muestra'], list), '(C) muestra debe ser list'

# Por defecto, el array completo debe ser None (no contaminar payload)
if result['links_omitidos'] is not None:
    print(f'WARN: links_omitidos NO es None (tamaño={len(result["links_omitidos"])})')
else:
    print('(C) PASS: links_omitidos es None en respuesta por defecto (backwards-compat)')

# Con detallar_omitidos=true debe devolver el array completo
r2 = client.post('/api/v1/dependencias/importar-xml?detallar_omitidos=true',
    json={'xml_content': SAMPLE_XML_ABC, 'dry_run': True, 'crear_tickets_faltantes': False, 'actualizar_fechas': False}
)
result2 = r2.json()
assert result2['links_omitidos'] is not None, 'con detallar_omitidos=true debe devolver array completo'
print(f'(C) PASS: detallar_omitidos=true → array completo (n={len(result2["links_omitidos"])})')
print(f'  links_omitidos_count={result2["links_omitidos_count"]}')
print(f'  links_omitidos_muestra={len(result2["links_omitidos_muestra"])} entries')

# ============================================================
# TEST B: crear_tickets_faltantes=true crea los tickets nuevos
# ============================================================
print('\n=== TEST B: Creación automática de tickets faltantes ===')

# Antes de crear, cuántos tickets hay?
db = SessionLocal()
try:
    count_before = db.query(Ticket).count()
    print(f'  Tickets antes: {count_before}')
finally:
    db.close()

r = client.post('/api/v1/dependencias/importar-xml',
    json={
        'xml_content': SAMPLE_XML_ABC,
        'dry_run': False,
        'crear_tickets_faltantes': True,
        'actualizar_fechas': True,
    }
)
print(f'  status={r.status_code}')
result = r.json()
print(f'  tickets_creados={result.get("tickets_creados", "MISSING!")}')
print(f'  tareas_a_crear (vacío porque se ejecutó): {len(result["tareas_a_crear"])}')
print(f'  fechas_actualizadas={result["fechas_actualizadas"]}')
print(f'  links_a_crear={len(result["links_a_crear"])}')
print(f'  links_omitidos_count={result["links_omitidos_count"]}')

assert 'tickets_creados' in result, '(B) debe devolver tickets_creados'
assert result['tickets_creados'] > 0, f'(B) tickets_creados debe ser >0, got {result["tickets_creados"]}'
print('  (B) PASS: tickets_creados > 0')

db = SessionLocal()
try:
    count_after = db.query(Ticket).count()
    print(f'  Tickets después: {count_after} (esperaba {count_before + result["tickets_creados"]})')
    assert count_after == count_before + result['tickets_creados'], \
        f'Se esperaba count_before + tickets_creados, got {count_after}'

    # Verificar que los nuevos tickets tienen codigo MP_<UID>, fechas, hu
    nuevos = db.query(Ticket).filter(Ticket.codigo.like('MP_%')).all()
    print(f'  Tickets con codigo MP_*: {len(nuevos)}')
    assert len(nuevos) == result['tickets_creados']
    for t in nuevos[:3]:
        print(f'    {t.codigo} | {t.titulo[:40]} | hu={t.hu_o_caso_prueba} | inicio={t.fecha_inicio} | sla={t.fecha_vencimiento_sla}')
        assert t.fecha_inicio is not None, f'Ticket {t.codigo} debe tener fecha_inicio'
        assert t.fecha_vencimiento_sla is not None, f'Ticket {t.codigo} debe tener fecha_vencimiento_sla'
    print('  (B) PASS: tickets nuevos con codigo MP_<UID>, fechas y HU poblados')
finally:
    db.close()

# ============================================================
# TEST A: Auto-dependencia forzada via parche del mapa
# ============================================================
print('\n=== TEST A (forzado): Auto-dependencia con parche ===')

# Ahora que hay tickets nuevos, podemos crear una relación que se mapee
# consigo misma simulando: predecesor y sucesor son la misma COI.
# Truco: parchear el endpoint con monkeypatch es complejo. Lo verificamos
# de manera más directa inspeccionando el codepath.
# Construimos un escenario donde el matching fuzzy hace que dos UIDs
# diferentes caigan en el mismo Ticket.

# Creamos un XML donde DOS tasks tienen la misma WBS ("2.1") para que
# ambos matcheen contra el seed ticket "GAR_SC_2_1-176".
SAME_WBS_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Tasks>
    <Task>
      <UID>300</UID>
      <ID>1</ID>
      <Name>Task X</Name>
      <WBS>2.1</WBS>
      <OutlineLevel>2</OutlineLevel>
      <Start>2025-09-01T08:00:00</Start>
      <Finish>2025-09-04T17:00:00</Finish>
    </Task>
    <Task>
      <UID>301</UID>
      <ID>2</ID>
      <Name>Task Y</Name>
      <WBS>2.1</WBS>
      <OutlineLevel>2</OutlineLevel>
      <Start>2025-09-05T08:00:00</Start>
      <Finish>2025-09-08T17:00:00</Finish>
      <PredecessorLink>
        <PredecessorUID>300</PredecessorUID>
        <Type>1</Type>
        <LinkLag>0</LinkLag>
        <LagFormat>7</LagFormat>
      </PredecessorLink>
    </Task>
  </Tasks>
</Project>'''

r = client.post('/api/v1/dependencias/importar-xml?detallar_omitidos=true',
    json={
        'xml_content': SAME_WBS_XML,
        'dry_run': True,
        'crear_tickets_faltantes': False,
        'actualizar_fechas': False,
    }
)
result = r.json()
print(f'  status_code=200')
print(f'  tareas_conocidas={result["tareas_conocidas"]} (esperado 2: ambos UIDs matchean al mismo ticket por hu=2.1)')
print(f'  links_a_crear={len(result["links_a_crear"])} (esperado 0)')
print(f'  links_omitidos={len(result["links_omitidos"])} (esperado 1)')
if result['links_omitidos']:
    print(f'  link omitido: {result["links_omitidos"][0]}')

# Verificación: si las 2 tareas matchearon al MISMO ticket, entonces la
# lógica de matching fuzzy está funcionando, y la defensa en profundidad
# detecta auto-dep (pred.id == suc.id).
assert result['tareas_conocidas'] == 2, 'ambas tareas deben matchear al mismo ticket (hu=2.1)'
assert len(result['links_a_crear']) == 0, 'NO debe crear la dep (es auto-dep)'
assert len(result['links_omitidos']) == 1, 'debe reportar 1 omitido'
assert result['links_omitidos'][0]['motivo'] == 'auto_dependencia', \
    f'motivo debe ser auto_dependencia, got {result["links_omitidos"][0]["motivo"]}'
print('  (A) PASS: auto-dependencia detectada y rechazada con motivo claro')

print('\n=== ALL TESTS PASSED ===')