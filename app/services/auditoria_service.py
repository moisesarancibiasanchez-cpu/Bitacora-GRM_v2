"""
Servicio de Auditoría: insert obligatorio tras cada acción crítica.
"""
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria
from app.models.usuario import Usuario


def registrar_auditoria(
    db: Session,
    ticket_id: int,
    usuario_id: int,
    accion: str,
    valor_anterior: Optional[Dict[str, Any]] = None,
    valor_nuevo: Optional[Dict[str, Any]] = None,
    comentario: Optional[str] = None,
    ip_origen: Optional[str] = None,
    commit: bool = True,
) -> Auditoria:
    """
    Inserta un registro inmutable en la tabla de auditoría.
    Es obligatorio llamarlo después de cualquier cambio de estado o edición.
    """
    registro = Auditoria(
        ticket_id=ticket_id,
        usuario_id=usuario_id,
        accion=accion,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        comentario=comentario,
        ip_origen=ip_origen,
    )
    db.add(registro)
    if commit:
        db.flush()  # Forzar el INSERT en la misma transacción
    return registro
