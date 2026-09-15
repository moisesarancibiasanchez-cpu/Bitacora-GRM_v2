"""Verifica que tras un cambio de estado existan rows en auditoría + notificación."""
import os
import sys
os.environ.setdefault('DATABASE_URL', 'sqlite:///./verify_audit.db')
os.environ.setdefault('SECRET_KEY', 'k')
os.environ.setdefault('AUTO_INIT_DB', 'true')
sys.path.insert(0, '.')

from app.db.session import SessionLocal
from app.db.init_db import init_database
from app.models.estado import Estado
from app.models.ticket import Ticket
from app.models.auditoria import Auditoria
from app.models.usuario import Usuario
from app.services.ticket_service import TicketService

init_database()
db = SessionLocal()

admin = db.query(Usuario).filter(Usuario.username == 'admin').first()
print(f'admin: id={admin.id} rol={admin.rol}')

# Pick first ticket
t = db.query(Ticket).first()
if not t:
    # crear uno
    from app.models.ticket import Ticket as T
    e1 = db.query(Estado).first()
    t = T(codigo='AUD-1', titulo='Audit test', estado_id=e1.id, creado_por_id=admin.id)
    db.add(t); db.commit(); db.refresh(t)

# Pick another estado
estados = db.query(Estado).all()
target = next((e for e in estados if e.id != t.estado_id), None)
print(f'orig estado={t.estado_id} -> nuevo estado={target.id}')

audit_before = db.query(Auditoria).filter(Auditoria.ticket_id == t.id).count()
print(f'auditoría rows antes: {audit_before}')

svc = TicketService(db)
from app.models.usuario import Usuario as U
actor = db.query(U).filter(U.is_active == True).first()
result = svc.cambiar_estado(
    ticket_id=t.id,
    nuevo_estado_id=target.id,
    actor=actor,
    comentario='Test auditoría',
    ip_origen='127.0.0.1',
)
print(f'cambiar_estado ok={result.get("ok")}')

audit_after = db.query(Auditoria).filter(Auditoria.ticket_id == t.id).count()
print(f'auditoría rows después: {audit_after}')
print(f'incremento: {audit_after - audit_before}')
last = db.query(Auditoria).filter(Auditoria.ticket_id == t.id).order_by(Auditoria.id.desc()).first()
print(f'última acción: {last.accion if last else None}')
