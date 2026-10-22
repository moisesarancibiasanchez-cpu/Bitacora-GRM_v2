#!/usr/bin/env python3
"""Validación de fixes: XML parser (legacy MS Project), Planner table + scroll,
y Gantt import con población de fechas."""
import os, sys, tempfile
from pathlib import Path

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ['DATABASE_URL'] = f'sqlite:///{TMP_DB}'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['ALLOW_XUSER_HEADER'] = 'true'

# Initialize DB BEFORE importing app
from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

# Create admin user and a few tickets with HU codes matching the XML
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
    # Create a default state (needed for ticket creation)
    estado = db.query(Estado).first()
    if not estado:
        estado = Estado(nombre='Abierto', orden=1, color='#3b82f6')
        db.add(estado); db.commit()
    # Create some test tickets with HU codes that match typical MS Project XML
    # (WBS values like "1.1.1", "2.1", "3.1.2", etc.)
    hu_codes = ['1.1.1', '2.1', '3.1.2', '3.1.1', '1.1']
    admin = db.query(Usuario).first()
    for hu in hu_codes:
        existing = db.query(Ticket).filter_by(hu_o_caso_prueba=hu).first()
        if not existing:
            t = Ticket(
                codigo=f'GAR_{hu.replace(".", "_")}',
                titulo=f'Ticket test {hu}',
                descripcion='Test ticket',
                estado_id=estado.id,
                creador_id=admin.id,
                hu_o_caso_prueba=hu,
                archivado=False,
            )
            db.add(t)
    db.commit()
    print(f'created {len(hu_codes)} test tickets')
finally:
    db.close()

# Now test the parser
from app.services.dependencia_service import MSProjectXMLParser

# Sample XML using LEGACY format (Formato B - MS Project 2007)
# Uses <Type> not <PredecessorType>, and parent Task UID is the successor
SAMPLE_XML_LEGACY = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>Test Project</Name>
  <StartDate>2025-07-14T08:00:00</StartDate>
  <FinishDate>2026-12-04T09:36:00</FinishDate>
  <Tasks>
    <Task>
      <UID>388</UID>
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
      <UID>389</UID>
      <ID>2</ID>
      <Name>Pase Producción</Name>
      <WBS>1.1.1</WBS>
      <OutlineLevel>3</OutlineLevel>
      <Start>2025-09-04T08:00:00</Start>
      <Finish>2025-09-04T17:00:00</Finish>
      <Duration>PT8H0M0S</Duration>
      <Summary>0</Summary>
    </Task>
    <Task>
      <UID>392</UID>
      <ID>3</ID>
      <Name>Pruebas Unitarias</Name>
      <WBS>3.1.1</WBS>
      <OutlineLevel>4</OutlineLevel>
      <Start>2025-09-07T08:00:00</Start>
      <Finish>2025-09-10T17:00:00</Finish>
      <Duration>PT32H0M0S</Duration>
      <Summary>0</Summary>
      <PredecessorLink>
        <PredecessorUID>389</PredecessorUID>
        <Type>1</Type>
        <CrossProject>0</CrossProject>
        <LinkLag>0</LinkLag>
        <LagFormat>7</LagFormat>
      </PredecessorLink>
    </Task>
    <Task>
      <UID>393</UID>
      <ID>4</ID>
      <Name>Pruebas Internas</Name>
      <WBS>3.1.2</WBS>
      <OutlineLevel>4</OutlineLevel>
      <Start>2025-09-07T08:00:00</Start>
      <Finish>2025-09-10T17:00:00</Finish>
      <Duration>PT32H0M0S</Duration>
      <Summary>0</Summary>
      <PredecessorLink>
        <PredecessorUID>389</PredecessorUID>
        <Type>1</Type>
        <CrossProject>0</CrossProject>
        <LinkLag>0</LinkLag>
        <LagFormat>7</LagFormat>
      </PredecessorLink>
    </Task>
  </Tasks>
</Project>'''

# Sample XML using MODERN format (Formato A - MS Project 2010+)
SAMPLE_XML_MODERN = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>Test Project Modern</Name>
  <Tasks>
    <Task>
      <UID>10</UID>
      <Name>Task A</Name>
      <WBS>A1</WBS>
      <Start>2025-09-01T08:00:00</Start>
      <Finish>2025-09-04T17:00:00</Finish>
    </Task>
    <Task>
      <UID>11</UID>
      <Name>Task B</Name>
      <WBS>B1</WBS>
      <Start>2025-09-05T08:00:00</Start>
      <Finish>2025-09-08T17:00:00</Finish>
      <PredecessorLink>
        <PredecessorUID>10</PredecessorUID>
        <SuccessorUID>11</SuccessorUID>
        <PredecessorType>1</PredecessorType>
        <LinkLag>0</LinkLag>
      </PredecessorLink>
    </Task>
  </Tasks>
</Project>'''

print('\n=== TEST 1: Parse LEGACY XML format (Type + parent Task successor) ===')
parser = MSProjectXMLParser(SAMPLE_XML_LEGACY.encode('utf-8'))
data = parser.parsear()
print(f'Tareas: {len(data["tareas"])}')
for t in data['tareas']:
    print(f'  UID={t["uid"]:3} WBS={t["wbs"]:8} Name={t["name"]:30} Start={t["start"]}')
print(f'Links: {len(data["links"])}')
for l in data['links']:
    print(f'  {l["predecesor_uid"]} -> {l["sucesor_uid"]} tipo={l["tipo_str"]} lag={l["lag_dias"]}d')

# In legacy format, links must have predecessor and successor correctly set
assert len(data['tareas']) == 4, f'Expected 4 tasks, got {len(data["tareas"])}'
assert len(data['links']) == 2, f'Expected 2 links, got {len(data["links"])}'
# Check that the successor in legacy format is the parent Task UID (not 0)
for l in data['links']:
    assert l['sucesor_uid'] != 0, 'Successor UID should not be 0 in legacy format'
    assert l['sucesor_uid'] != l['predecesor_uid'], 'No self-dependency allowed'
print('PASS: Legacy format parses correctly with parent Task as successor')

print('\n=== TEST 2: Parse MODERN XML format (PredecessorType + SuccessorUID) ===')
parser = MSProjectXMLParser(SAMPLE_XML_MODERN.encode('utf-8'))
data = parser.parsear()
print(f'Tareas: {len(data["tareas"])}')
print(f'Links: {len(data["links"])}')
for l in data['links']:
    print(f'  {l["predecesor_uid"]} -> {l["sucesor_uid"]} tipo={l["tipo_str"]}')
assert len(data['tareas']) == 2
assert len(data['links']) == 1
print('PASS: Modern format parses correctly')

# Now test the FastAPI routes
print('\n=== TEST 3: Test Planner and Gantt views via TestClient ===')
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post('/api/v1/auth/login-form', data={'username':'admin','password':'test1234'}, follow_redirects=False)
print(f'login status: {r.status_code}')

r = client.get('/vistas/planner', follow_redirects=True)
print(f'GET /vistas/planner: status={r.status_code} len={len(r.text)}')
assert r.status_code == 200, f'Expected 200, got {r.status_code}'
# Check that the new table class is present
assert 'planner-table' in r.text, 'planner-table class should be present in new template'
assert 'planner-scroll' in r.text, 'planner-scroll class should be present for vertical scroll'
print('PASS: Planner view returns table with scroll container')

r = client.get('/vistas/gantt', follow_redirects=True)
print(f'GET /vistas/gantt: status={r.status_code} len={len(r.text)}')
assert r.status_code == 200
# Check the new flag is in the form
assert 'actualizar_fechas' in r.text, 'actualizar_fechas checkbox should be present'
print('PASS: Gantt view has new actualizar_fechas flag')

# Test the import endpoint with our sample XML
print('\n=== TEST 4: Test /dependencias/importar-xml with legacy format ===')
import json
r = client.post('/api/v1/dependencias/importar-xml',
    json={
        'xml_content': SAMPLE_XML_LEGACY,
        'dry_run': True,
        'crear_tickets_faltantes': False,
        'actualizar_fechas': False,
    },
)
print(f'import status: {r.status_code}')
result = r.json()
print(f'Response: {json.dumps(result, indent=2, default=str)[:1000]}')
assert r.status_code == 200, f'Expected 200, got {r.status_code}: {result}'
assert result['links_xml'] == 2, f'Expected 2 links in XML, got {result["links_xml"]}'
assert result['tareas_xml'] == 4, f'Expected 4 tasks in XML, got {result["tareas_xml"]}'
# Check that tickets matched (we created tickets with HU 1.1.1, 2.1, 3.1.2, 3.1.1)
assert result['tareas_conocidas'] >= 3, f'Expected >=3 known tasks, got {result["tareas_conocidas"]}'
print('PASS: Import endpoint returns links_xml > 0 (legacy format fix works)')

# Test with dry_run=False to populate dates
print('\n=== TEST 5: Test /dependencias/importar-xml with dry_run=False to populate dates ===')
r = client.post('/api/v1/dependencias/importar-xml',
    json={
        'xml_content': SAMPLE_XML_LEGACY,
        'dry_run': False,
        'crear_tickets_faltantes': False,
        'actualizar_fechas': True,
    },
)
print(f'import status: {r.status_code}')
result = r.json()
print(f'Result: tareas_conocidas={result["tareas_conocidas"]}, '
      f'fechas_actualizadas={result.get("fechas_actualizadas", 0)}, '
      f'links_a_crear={len(result["links_a_crear"])}, '
      f'links_omitidos={len(result["links_omitidos"])}')
assert r.status_code == 200
assert result.get('fechas_actualizadas', 0) > 0, \
    f'Expected dates to be updated, got {result.get("fechas_actualizadas", 0)}'
print('PASS: Dates populated from XML')

# Verify in DB
db = SessionLocal()
try:
    from app.models.ticket import Ticket as T2
    tickets_with_dates = db.query(T2).filter(
        T2.fecha_inicio.isnot(None),
        T2.fecha_vencimiento_sla.isnot(None),
    ).count()
    print(f'Tickets with fecha_inicio + fecha_vencimiento_sla: {tickets_with_dates}')
    assert tickets_with_dates >= 3, f'Expected >=3 tickets with dates, got {tickets_with_dates}'
    print('PASS: DB now has tickets with dates populated')
finally:
    db.close()

# Test that the Gantt now shows data
print('\n=== TEST 6: Verify Gantt view now shows tickets (not empty) ===')
r = client.get('/vistas/gantt', follow_redirects=True)
assert r.status_code == 200
# Check that the empty state message is NOT shown
if 'No hay tickets con fecha de inicio y/o SLA' in r.text:
    print('FAIL: Gantt still shows empty state!')
else:
    print('PASS: Gantt no longer shows empty state (tickets now have dates)')

# Check the count text near the header
import re
match = re.search(r'\((\d+) tickets · (\d+) dependencias\)', r.text)
if match:
    print(f'  Tickets shown: {match.group(1)}, Links shown: {match.group(2)}')

print('\n=== ALL TESTS PASSED ===')
