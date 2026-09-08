"""
Modelos para Checklists/Subtareas dentro de un ticket.
Permite dividir una incidencia en tareas más pequeñas con su propio estado.
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Checklist(Base, TimestampMixin):
    """Lista de tareas dentro de un ticket."""
    __tablename__ = "checklists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    titulo = Column(String(200), nullable=False)
    orden = Column(Integer, default=0, nullable=False)
    posicion = Column(Integer, default=0, nullable=False)

    items = relationship(
        "ChecklistItem",
        back_populates="checklist",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.orden",
    )
    ticket = relationship("Ticket", back_populates="checklists")

    @property
    def progreso(self) -> dict:
        """Devuelve el progreso de la checklist."""
        total = len(self.items) if self.items else 0
        completados = sum(1 for i in (self.items or []) if i.completado)
        porcentaje = (completados / total * 100) if total > 0 else 0
        return {
            "total": total,
            "completados": completados,
            "porcentaje": round(porcentaje, 1),
        }

    def __repr__(self) -> str:
        return f"<Checklist {self.titulo} ticket={self.ticket_id}>"


class ChecklistItem(Base):
    """Ítem individual de una checklist (subtarea)."""
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    checklist_id = Column(
        Integer, ForeignKey("checklists.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    texto = Column(String(500), nullable=False)
    completado = Column(Boolean, default=False, nullable=False, index=True)
    orden = Column(Integer, default=0, nullable=False)
    asignado_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )
    fecha_vencimiento = Column(String(50), nullable=True)

    checklist = relationship("Checklist", back_populates="items")
    asignado = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<ChecklistItem {self.texto[:30]} done={self.completado}>"
