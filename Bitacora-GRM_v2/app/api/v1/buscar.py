"""
Búsqueda global estilo Trello (Command Palette / Ctrl+K).

Busca en múltiples entidades:
- Tickets (codigo, titulo, descripcion)
- Espacios
- Tableros
- Usuarios
"""
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.ticket import Ticket
from app.models.espacio import Espacio, Tablero
from app.models.usuario import Usuario
from app.models.etiqueta import Etiqueta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/buscar", tags=["Búsqueda global"])


@router.get("")
def busqueda_global(
    q: str = Query(..., min_length=1, max_length=200, description="Texto a buscar"),
    limit: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Búsqueda global en todas las entidades principales.

    Devuelve resultados agrupados por tipo para alimentar el command palette.
    """
    patron = f"%{q}%"

    # === Tickets ===
    tickets = (
        db.query(Ticket)
        .filter(
            or_(
                Ticket.codigo.ilike(patron),
                Ticket.titulo.ilike(patron),
                Ticket.descripcion.ilike(patron),
            ),
            Ticket.archivado == False,  # noqa: E712
        )
        .order_by(Ticket.updated_at.desc())
        .limit(limit)
        .all()
    )
    tickets_result = [
        {
            "tipo": "ticket",
            "id": t.id,
            "titulo": t.titulo,
            "subtitulo": t.codigo,
            "url": f"/api/v1/tickets/{t.id}/detalle-html",
            "metadata": {
                "estado": t.estado.nombre if t.estado else None,
                "estado_color": t.estado.color if t.estado else "#94a3b8",
                "prioridad": t.prioridad.value if t.prioridad else "media",
            },
        }
        for t in tickets
    ]

    # === Espacios ===
    espacios = (
        db.query(Espacio)
        .filter(or_(Espacio.nombre.ilike(patron), Espacio.descripcion.ilike(patron)))
        .limit(limit)
        .all()
    )
    espacios_result = [
        {
            "tipo": "espacio",
            "id": e.id,
            "titulo": e.nombre,
            "subtitulo": e.descripcion or "",
            "url": f"/espacios",
            "metadata": {"icono": e.icono, "color": e.color},
        }
        for e in espacios
    ]

    # === Tableros ===
    tableros = (
        db.query(Tablero)
        .filter(or_(Tablero.nombre.ilike(patron), Tablero.descripcion.ilike(patron)))
        .filter(Tablero.archivado == False)  # noqa: E712
        .limit(limit)
        .all()
    )
    tableros_result = [
        {
            "tipo": "tablero",
            "id": t.id,
            "titulo": t.nombre,
            "subtitulo": t.descripcion or "",
            "url": f"/kanban?tablero={t.id}",
            "metadata": {"visibilidad": t.visibilidad, "color": t.color_fondo},
        }
        for t in tableros
    ]

    # === Usuarios ===
    usuarios = (
        db.query(Usuario)
        .filter(
            or_(
                Usuario.username.ilike(patron),
                Usuario.nombre_completo.ilike(patron),
                Usuario.email.ilike(patron),
            )
        )
        .limit(limit)
        .all()
    )
    usuarios_result = [
        {
            "tipo": "usuario",
            "id": u.id,
            "titulo": u.nombre_completo,
            "subtitulo": f"@{u.username} · {u.rol.value if u.rol else ''}",
            "url": f"/kanban?asignado={u.id}",
            "metadata": {"departamento": u.departamento},
        }
        for u in usuarios
    ]

    # === Etiquetas ===
    etiquetas = (
        db.query(Etiqueta)
        .filter(Etiqueta.nombre.ilike(patron))
        .limit(limit)
        .all()
    )
    etiquetas_result = [
        {
            "tipo": "etiqueta",
            "id": e.id,
            "titulo": e.nombre,
            "subtitulo": f"Color: {e.color}",
            "url": f"/kanban?etiqueta={e.id}",
            "metadata": {"color": e.color},
        }
        for e in etiquetas
    ]

    total = (
        len(tickets_result)
        + len(espacios_result)
        + len(tableros_result)
        + len(usuarios_result)
        + len(etiquetas_result)
    )

    return {
        "query": q,
        "total": total,
        # Top-level keys (consumidos por el command palette y los tests).
        "tickets": tickets_result,
        "espacios": espacios_result,
        "tableros": tableros_result,
        "usuarios": usuarios_result,
        "etiquetas": etiquetas_result,
        # Alias anidado conservado por retro-compatibilidad.
        "resultados": {
            "tickets": tickets_result,
            "espacios": espacios_result,
            "tableros": tableros_result,
            "usuarios": usuarios_result,
            "etiquetas": etiquetas_result,
        },
    }
