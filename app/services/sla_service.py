"""
Servicio de SLA: cálculo de vencimientos y estado de cumplimiento.
"""
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session

from app.models.ticket import Ticket


class SLAService:
    """Encapsula las reglas de cálculo de SLA."""

    def __init__(self, db: Session):
        self.db = db

    def recalcular_ticket(self, ticket_id: int) -> dict:
        """Recalcula el estado de SLA de un ticket individual."""
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return {"ok": False, "error": "ticket_no_existe"}

        ahora = datetime.utcnow()
        if ticket.estado.es_final:
            # En estado final: el SLA ya está cerrado
            ticket.sla_cumplido = 1 if ticket.sla_cumplido == 1 else 0
        elif ticket.fecha_vencimiento_sla:
            if ahora > ticket.fecha_vencimiento_sla:
                ticket.sla_cumplido = 0  # Vencido
            else:
                ticket.sla_cumplido = -1  # Pendiente
        self.db.commit()
        return {
            "ok": True,
            "ticket_id": ticket.id,
            "sla_cumplido": ticket.sla_cumplido,
            "fecha_vencimiento": (
                ticket.fecha_vencimiento_sla.isoformat()
                if ticket.fecha_vencimiento_sla else None
            ),
        }

    def tickets_proximos_vencer(self, horas: int = 4) -> List[Ticket]:
        """Devuelve tickets cuyo SLA vence en las próximas `horas` horas."""
        from datetime import timedelta
        limite = datetime.utcnow() + timedelta(hours=horas)
        return (
            self.db.query(Ticket)
            .filter(
                Ticket.fecha_vencimiento_sla.isnot(None),
                Ticket.fecha_vencimiento_sla <= limite,
                Ticket.sla_cumplido == -1,
            )
            .all()
        )

    def tickets_vencidos(self) -> List[Ticket]:
        """Tickets cuyo SLA ya venció y no están en estado final."""
        ahora = datetime.utcnow()
        return (
            self.db.query(Ticket)
            .filter(
                Ticket.fecha_vencimiento_sla.isnot(None),
                Ticket.fecha_vencimiento_sla < ahora,
                Ticket.sla_cumplido == -1,
            )
            .all()
        )
