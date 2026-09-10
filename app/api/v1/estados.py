"""
Endpoints para gestionar el catálogo de estados y sus transiciones.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.estado import Estado, TransicionEstado
from app.models.usuario import Usuario, RolUsuario
from app.schemas.ticket import EstadoRead, TransicionEstadoRead


router = APIRouter(prefix="/estados", tags=["Estados"])


@router.get("", response_model=list[EstadoRead])
def listar_estados(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todos los estados del flujo, ordenados para el Kanban."""
    return db.query(Estado).order_by(Estado.orden.asc()).all()


@router.get("/transiciones", response_model=list[TransicionEstadoRead])
def listar_transiciones(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todas las transiciones válidas del flujo (lectura de la matriz)."""
    return db.query(TransicionEstado).all()


@router.post("", response_model=EstadoRead, status_code=201)
def crear_estado(
    payload: EstadoRead,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Crea un nuevo estado (solo administradores)."""
    existe = db.query(Estado).filter(Estado.nombre == payload.nombre).first()
    if existe:
        raise HTTPException(status_code=400, detail="Ya existe un estado con ese nombre.")
    estado = Estado(**payload.model_dump())
    db.add(estado)
    db.commit()
    db.refresh(estado)
    return estado


@router.post("/transiciones", status_code=201)
def crear_transicion(
    estado_origen_id: int,
    estado_destino_id: int,
    rol_requerido: str = "agente",
    requiere_comentario: bool = False,
    descripcion: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Crea una transición válida del flujo ITSM."""
    trans = TransicionEstado(
        estado_origen_id=estado_origen_id,
        estado_destino_id=estado_destino_id,
        rol_requerido=rol_requerido,
        requiere_comentario=requiere_comentario,
        descripcion=descripcion,
    )
    db.add(trans)
    db.commit()
    db.refresh(trans)
    return trans


# ===========================================================================
#  PATCH para editar título y responsable de una columna del Kanban
# ===========================================================================
class EstadoUpdate(BaseModel):
    """Payload para editar campos básicos de un estado desde el Kanban."""
    nombre: str | None = Field(default=None, max_length=80)
    responsable_id: int | None = Field(
        default=None,
        description="ID del usuario responsable. null = sin responsable",
    )


def _render_column_header(estado: Estado) -> str:
    """
    Renderiza el fragmento HTML del encabezado de una columna (título +
    responsable + contador). Se usa como respuesta de los PATCH para
    refrescar la cabecera con HTMX sin recargar la página.
    """
    # Iniciales del responsable
    resp = estado.responsable
    if resp is not None:
        nombre_completo = (resp.nombre_completo or resp.username or "").strip()
        partes = [p for p in nombre_completo.split() if p]
        if partes:
            initials = "".join(p[0].upper() for p in partes[:2]) or "?"
        else:
            initials = "?"
    else:
        initials = ""
        nombre_completo = ""

    responsable_html = ""
    if resp is not None:
        responsable_html = (
            f'<span class="inline-flex items-center gap-1 px-1.5 py-0.5 '
            f'rounded-full bg-indigo-50 border border-indigo-200 '
            f'text-[10px] text-indigo-700" '
            f'title="Responsable: {nombre_completo}">'
            f'<span class="inline-flex items-center justify-center w-4 h-4 '
            f'rounded-full bg-indigo-600 text-white text-[9px] font-bold">'
            f"{initials}</span>"
            f'<span class="font-medium truncate max-w-[7rem]">'
            f"{nombre_completo.split()[0] if nombre_completo else resp.username}</span>"
            f'<button type="button" '
            f'hx-patch="/api/v1/estados/{estado.id}" '
            f'hx-vals=\'{{"responsable_id": ""}}\' '
            f'hx-target="#column-header-{estado.id}" '
            f'hx-swap="outerHTML" '
            f'class="ml-0.5 text-indigo-400 hover:text-red-500" '
            f'title="Quitar responsable">×</button>'
            f"</span>"
        )
    else:
        responsable_html = (
            f'<button type="button" '
            f'hx-get="/api/v1/estados/{estado.id}/responsable-picker" '
            f'hx-target="#column-header-{estado.id}" '
            f'hx-swap="outerHTML" '
            f'class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full '
            f'border border-dashed border-slate-300 text-[10px] text-slate-500 '
            f'hover:bg-slate-50" '
            f'title="Asignar responsable a esta columna">'
            f'<svg class="w-3 h-3" fill="none" stroke="currentColor" '
            f'viewBox="0 0 24 24"><path stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-width="2" '
            f'd="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z">'
            f"</path></svg>responsable</button>"
        )

    # El nombre es editable: doble clic o botón "editar" -> muestra input
    # HTMX autosubmit. La edición se persiste con PATCH /estados/{id}.
    header_id = f"column-header-{estado.id}"
    # El contador de tickets se refresca con un endpoint separado;
    # aquí devolvemos solo el título + responsable + botón editar.
    return (
        f'<div id="{header_id}" '
        f'class="flex items-center justify-between gap-2 mb-3 px-1 '
        f'flex-shrink-0 flex-wrap">'
        f'<div class="flex items-center gap-2 min-w-0">'
        f'<span class="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0" '
        f'style="background-color: {estado.color}"></span>'
        # Título editable
        f'<div class="flex items-center gap-1 min-w-0" '
        f'id="title-wrap-{estado.id}">'
        f'<h3 class="font-semibold text-sm text-slate-700 uppercase '
        f'tracking-wide truncate" id="title-display-{estado.id}" '
        f'data-estado-id="{estado.id}" '
        f'onclick="window.editarTituloColumna({estado.id})">'
        f"{estado.nombre}</h3>"
        f'<button type="button" '
        f'onclick="window.editarTituloColumna({estado.id})" '
        f'class="text-slate-400 hover:text-indigo-600 p-0.5" '
        f'title="Editar título de la columna">'
        f'<svg class="w-3 h-3" fill="none" stroke="currentColor" '
        f'viewBox="0 0 24 24"><path stroke-linecap="round" '
        f'stroke-linejoin="round" stroke-width="2" '
        f'd="M15.232 5.232l3.536 3.536M9 11l3.536-3.536M3 21h6l11-11a2.5 '
        f'2.5 0 00-3.536-3.536L5 17v4z"></path></svg></button>'
        f"</div>"
        f"</div>"
        f'<div class="flex items-center gap-2 flex-shrink-0">'
        f"{responsable_html}"
        f'<span class="text-xs font-mono text-slate-500 bg-white px-2 py-0.5 '
        f'rounded-full border border-slate-200" '
        f'id="count-{estado.id}">{getattr(estado, "_count", "")}</span>'
        f"</div>"
        f"</div>"
    )


@router.patch("/{estado_id}", response_class=HTMLResponse)
def actualizar_estado(
    estado_id: int,
    payload: EstadoUpdate,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Edita el título y/o el responsable de una columna del Kanban.
    Devuelve el fragmento HTML del encabezado de la columna (HTMX swap).
    """
    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")

    # Permisos: admin o agente_senior pueden editar
    rol_legible = (
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    )
    jerarquia = {
        "observador": 1, "solicitante": 2, "agente": 3,
        "agente_senior": 4, "administrador": 5,
    }
    if jerarquia.get(rol_legible, 0) < jerarquia.get("agente_senior", 4):
        return HTMLResponse(
            content=(
                f'<div id="column-header-{estado_id}" '
                f'class="rounded-md border-2 border-red-300 bg-red-50 '
                f'px-2 py-1 text-xs text-red-700">'
                f"Sin permisos para editar la columna. "
                f"Se requiere agente_senior o administrador.</div>"
            ),
            status_code=403,
            headers={"HX-Trigger": "ticket-error"},
        )

    cambios = {}
    if payload.nombre is not None and payload.nombre.strip() != estado.nombre:
        nuevo = payload.nombre.strip()
        if not nuevo:
            return HTMLResponse(
                content=(
                    f'<div id="column-header-{estado_id}" '
                    f'class="rounded-md border-2 border-amber-300 bg-amber-50 '
                    f'px-2 py-1 text-xs text-amber-700">'
                    f"El nombre no puede estar vacío.</div>"
                ),
                status_code=400,
                headers={"HX-Trigger": "ticket-error"},
            )
        # Validar unicidad
        dup = (
            db.query(Estado)
            .filter(Estado.nombre == nuevo, Estado.id != estado.id)
            .first()
        )
        if dup:
            return HTMLResponse(
                content=(
                    f'<div id="column-header-{estado_id}" '
                    f'class="rounded-md border-2 border-amber-300 bg-amber-50 '
                    f'px-2 py-1 text-xs text-amber-700">'
                    f"Ya existe otra columna con el nombre «{nuevo}».</div>"
                ),
                status_code=400,
                headers={"HX-Trigger": "ticket-error"},
            )
        cambios["nombre"] = {"anterior": estado.nombre, "nuevo": nuevo}
        estado.nombre = nuevo

    # responsable_id: aceptar "" / null para limpiar
    raw_resp = payload.responsable_id
    if "responsable_id" in payload.model_fields_set:
        if raw_resp in (None,):
            if estado.responsable_id is not None:
                cambios["responsable_id"] = {
                    "anterior": estado.responsable_id,
                    "nuevo": None,
                }
                estado.responsable_id = None
        else:
            # validar que el usuario existe y está activo
            u = db.query(Usuario).filter(Usuario.id == raw_resp).first()
            if not u or not u.is_active:
                return HTMLResponse(
                    content=(
                        f'<div id="column-header-{estado_id}" '
                        f'class="rounded-md border-2 border-amber-300 bg-amber-50 '
                        f'px-2 py-1 text-xs text-amber-700">'
                        f"El usuario responsable no existe o está inactivo.</div>"
                    ),
                    status_code=400,
                    headers={"HX-Trigger": "ticket-error"},
                )
            if estado.responsable_id != u.id:
                cambios["responsable_id"] = {
                    "anterior": estado.responsable_id,
                    "nuevo": u.id,
                }
                estado.responsable_id = u.id

    if not cambios:
        # Sin cambios: devolver el header actual
        db.refresh(estado)
        return HTMLResponse(_render_column_header(estado))

    # Las ediciones de columna NO se registran en la tabla `auditorias`
    # porque esa tabla exige ticket_id NOT NULL (FK a tickets.id) y estos
    # cambios son de catálogo, no de un ticket específico. Se emiten a
    # los logs estándar para mantener trazabilidad.

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        return HTMLResponse(
            content=(
                f'<div id="column-header-{estado_id}" '
                f'class="rounded-md border-2 border-red-300 bg-red-50 '
                f'px-2 py-1 text-xs text-red-700">'
                f"Error al guardar: {exc}</div>"
            ),
            status_code=500,
            headers={"HX-Trigger": "ticket-error"},
        )
    db.refresh(estado)

    # Refrescar el responsable (relación) para que el header lo muestre
    if estado.responsable_id is not None:
        estado.responsable = (
            db.query(Usuario).filter(Usuario.id == estado.responsable_id).first()
        )

    return HTMLResponse(
        _render_column_header(estado),
        headers={"HX-Trigger": "column-updated"},
    )


@router.get("/{estado_id}/responsable-picker", response_class=HTMLResponse)
def responsable_picker(
    estado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Devuelve un mini-form con un <select> de usuarios activos para asignar
    como responsable de la columna. Pensado para HTMX (swap en el header).
    """
    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")

    # Listar usuarios activos (excluyendo observadores si quieres, pero por
    # simplicidad dejamos todos los activos y ordenados por nombre)
    usuarios = (
        db.query(Usuario)
        .filter(Usuario.is_active == True)  # noqa: E712
        .order_by(Usuario.nombre_completo.asc(), Usuario.username.asc())
        .all()
    )

    options = ['<option value="">— Sin responsable —</option>']
    for u in usuarios:
        nombre = u.nombre_completo or u.username
        selected = " selected" if estado.responsable_id == u.id else ""
        options.append(
            f'<option value="{u.id}"{selected}>{nombre} ({u.username})</option>'
        )

    header_id = f"column-header-{estado.id}"
    return HTMLResponse(
        f'<div id="{header_id}" '
        f'class="flex items-center gap-2 mb-3 px-1 flex-shrink-0">'
        f'<select name="responsable_id" '
        f'autofocus '
        f'onchange="this.form.requestSubmit()" '
        f'form="form-resp-{estado.id}" '
        f'class="text-xs border border-slate-300 rounded-md px-2 py-1 max-w-[14rem]">'
        + "".join(options) +
        f'</select>'
        f'<form id="form-resp-{estado.id}" '
        f'hx-patch="/api/v1/estados/{estado.id}" '
        f'hx-target="#column-header-{estado.id}" '
        f'hx-swap="outerHTML" '
        f'style="display:none"></form>'
        f'<button type="button" '
        f'hx-get="/api/v1/estados/{estado.id}/header" '
        f'hx-target="#column-header-{estado.id}" '
        f'hx-swap="outerHTML" '
        f'class="text-[10px] text-slate-500 hover:text-slate-700">cancelar</button>'
        f"</div>"
    )


@router.get("/{estado_id}/header", response_class=HTMLResponse)
def get_header(
    estado_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Devuelve SOLO el fragmento del header de la columna (modo lectura).
    Útil para cancelar el picker o refrescar tras un cambio.
    """
    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    if estado.responsable_id is not None:
        estado.responsable = (
            db.query(Usuario).filter(Usuario.id == estado.responsable_id).first()
        )
    return HTMLResponse(_render_column_header(estado))
