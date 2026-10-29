"""
Datos del modal de detalle del ticket: comentarios y adjuntos.

Este módulo es la **fuente única de verdad** de las tres consultas que
necesita el modal de detalle (``app/templates/tickets/detalle_modal.py``),
para que **todos** los endpoints que lo re-renderizan muestren exactamente
lo mismo:

  * ``comentarios_visibles()``    -> comentarios del ticket, ocultando los
                                     INTERNOS a los solicitantes;
  * ``adjuntos_del_ticket()``     -> adjuntos que cuelgan del TICKET
                                     (``comentario_id IS NULL``);
  * ``adjuntos_por_comentario()`` -> adjuntos de cada comentario, en una
                                     sola consulta (precarga, sin N+1).

Por qué centralizarlo
---------------------
El modal de detalle se renderiza desde dos rutas distintas:

  * ``app/api/v1/tickets.py::detalle_html`` (la ruta normal: Kanban, lista
    de tickets, dashboard, timeline, Gantt y calendario),
  * ``app/api/v1/features.py::_render_detalle_modal_response`` (los
    re-renderes que ocurren tras crear, editar o borrar un comentario).

Cada una montaba sus propias consultas, y lo hacian de forma divergente:

  * ``detalle_html`` NO filtraba los comentarios internos, de modo que un
    solicitante podia leerlos (los comentarios internos son, por
    definicion, del equipo y no del solicitante);
  * ``detalle_html`` NO separaba los adjuntos del ticket de los adjuntos de
    cada comentario: los adjuntos de un comentario aparecian de rebote en
    la pestana "Adjuntos" y NO se veian dentro del comentario;
  * ``detalle_html`` no precargaba los adjuntos por comentario, asi que la
    miniatura de una imagen adjunta a un comentario no se renderizaba en la
    pestana "Comentarios" (solo aparecia tras postear el comentario, y
    desaparecia al reabrir el ticket).

Con este modulo, las dos rutas consumen las mismas reglas y el modal no
puede depender de por donde se haya abierto.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def comentarios_visibles(db, ticket_id: int, usuario: Any) -> List[Any]:
    """Comentarios del ticket que puede ver el usuario indicado.

    Los comentarios marcados como internos (``es_interno``) son del equipo y
    **nunca** se muestran a un solicitante, ni en el modal, ni en el JSON,
    ni en la respuesta HTMX.

    Parameters
    ----------
    db : Session
        Sesion SQLAlchemy.
    ticket_id : int
        Ticket cuyo historial de comentarios se quiere leer.
    usuario : Usuario
        Usuario que abre el modal (decide si se filtran los internos).

    Returns
    -------
    list[Comentario]
        Comentarios visibles, del mas antiguo al mas reciente.
    """
    from app.models.comentario import Comentario
    from app.models.usuario import RolUsuario

    q = db.query(Comentario).filter(Comentario.ticket_id == ticket_id)
    rol = getattr(usuario, "rol", None)
    if rol == RolUsuario.SOLICITANTE:
        q = q.filter(Comentario.es_interno == False)  # noqa: E712
    return q.order_by(Comentario.created_at.asc()).all()


def adjuntos_del_ticket(db, ticket_id: int) -> List[Any]:
    """Adjuntos que cuelgan del TICKET (no de un comentario).

    Los adjuntos de un comentario se renderizan inline dentro de su
    comentario (pestana "Comentarios"); no deben aparecer en la pestana
    "Adjuntos", que es la vista de los archivos del ticket.
    """
    from app.models.adjunto import Adjunto

    return (
        db.query(Adjunto)
        .filter(
            Adjunto.ticket_id == ticket_id,
            Adjunto.comentario_id.is_(None),
        )
        .order_by(Adjunto.created_at.desc())
        .all()
    )


def adjuntos_por_comentario(db, comentarios: Iterable[Any]) -> Dict[int, List[Any]]:
    """Agrupa los adjuntos de cada comentario en una sola consulta.

    Precarga (sin N+1): en lugar de disparar un SELECT por comentario al
    iterar en la plantilla, se resuelve todo de una vez y se devuelve un
    diccionario ``{comentario_id: [adjuntos]}``.

    Los comentarios sin adjuntos no aparecen en el diccionario; la
    plantilla usa ``.get(id) or []``.
    """
    from app.models.adjunto import Adjunto

    com_ids = [c.id for c in comentarios]
    resultado: Dict[int, List[Any]] = {}
    if not com_ids:
        return resultado
    filas = (
        db.query(Adjunto)
        .filter(Adjunto.comentario_id.in_(com_ids))
        .order_by(Adjunto.created_at.asc())
        .all()
    )
    for adjunto in filas:
        resultado.setdefault(adjunto.comentario_id, []).append(adjunto)
    return resultado
