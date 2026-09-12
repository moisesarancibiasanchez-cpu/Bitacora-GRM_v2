"""
Endpoints para gestionar el catálogo de estados y sus transiciones.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_role, require_admin
from app.db.session import get_db
from app.models.estado import Estado, TransicionEstado
from app.models.usuario import Usuario, RolUsuario
from app.schemas.ticket import EstadoCreate, EstadoRead, TransicionEstadoRead


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
    payload: EstadoCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Crea un nuevo estado (solo administradores)."""
    existe = db.query(Estado).filter(Estado.nombre == payload.nombre).first()
    if existe:
        raise HTTPException(status_code=400, detail="Ya existe un estado con ese nombre.")
    # Calcular orden automáticamente: siguiente al último
    if payload.orden == 0:
        max_orden = db.query(Estado).order_by(Estado.orden.desc()).first()
        payload.orden = (max_orden.orden + 1) if max_orden else 1
    estado = Estado(**payload.model_dump())
    db.add(estado)
    db.commit()
    db.refresh(estado)
    return estado


# ===========================================================================
#  Form HTML para crear nueva columna desde el Kanban
# ===========================================================================
@router.get("/nueva-columna-form", response_class=HTMLResponse)
def nueva_columna_form(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Devuelve un modal con el formulario para crear una nueva columna
    (estado) en el Kanban. Pensado para HTMX (swap en #modal-root).

    Permisos: SOLO el rol Administrador puede crear columnas nuevas.
    """
    # Permisos: SOLO Administrador
    rol_legible = (
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    )
    if str(rol_legible).lower() != "administrador":
        return HTMLResponse(
            content=(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="error">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Sin permisos</h3>'
                f'<p class="text-sm text-slate-600 mb-4">Solo el rol Administrador puede crear columnas nuevas.</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>'
            ),
            status_code=403,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Listar usuarios activos para asignar como responsable
    usuarios = (
        db.query(Usuario)
        .filter(Usuario.is_active == True)  # noqa: E712
        .order_by(Usuario.nombre_completo.asc(), Usuario.username.asc())
        .all()
    )

    # Calcular siguiente orden
    max_orden = db.query(Estado).order_by(Estado.orden.desc()).first()
    next_orden = (max_orden.orden + 1) if max_orden else 1

    usuarios_options = ['<option value="">— Sin responsable —</option>']
    for u in usuarios:
        nombre = u.nombre_completo or u.username
        usuarios_options.append(
            f'<option value="{u.id}">{nombre} ({u.username})</option>'
        )

    return HTMLResponse(
        f'''<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nueva-columna">
          <div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden flex flex-col">
            <div class="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
              <div>
                <h3 class="text-base font-semibold text-slate-800">Nueva columna del Kanban</h3>
                <p class="text-xs text-slate-500 mt-0.5">Agrega un estado al flujo de trabajo</p>
              </div>
              <button data-close-modal class="w-8 h-8 rounded-md flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
              </button>
            </div>
            <form hx-post="/api/v1/estados/crear-form"
                  hx-target="#modal-root" hx-swap="innerHTML"
                  hx-encoding="multipart/form-data"
                  class="px-5 py-4 space-y-3">
              <div>
                <label for="nc-nombre" class="block text-xs font-semibold text-slate-700 mb-1">Nombre <span class="text-red-500">*</span></label>
                <input type="text" id="nc-nombre" name="nombre" required maxlength="80"
                       placeholder="Ej: En revisión, Bloqueado, Re-abierto…"
                       class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500" />
              </div>
              <div>
                <label for="nc-descripcion" class="block text-xs font-semibold text-slate-700 mb-1">Descripción</label>
                <input type="text" id="nc-descripcion" name="descripcion" maxlength="200"
                       placeholder="Breve descripción del estado (opcional)"
                       class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500" />
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label for="nc-color" class="block text-xs font-semibold text-slate-700 mb-1">Color</label>
                  <input type="color" id="nc-color" name="color" value="#6366f1"
                         class="w-full h-9 border border-slate-300 rounded-md cursor-pointer" />
                </div>
                <div>
                  <label for="nc-orden" class="block text-xs font-semibold text-slate-700 mb-1">Orden</label>
                  <input type="number" id="nc-orden" name="orden" value="{next_orden}"
                         class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500" />
                </div>
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label for="nc-categoria" class="block text-xs font-semibold text-slate-700 mb-1">Categoría</label>
                  <select id="nc-categoria" name="categoria"
                          class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500">
                    <option value="abierto" selected>Abierto</option>
                    <option value="en_curso">En curso</option>
                    <option value="espera">En espera</option>
                    <option value="resuelto">Resuelto</option>
                    <option value="cerrado">Cerrado</option>
                    <option value="cancelado">Cancelado</option>
                  </select>
                </div>
                <div>
                  <label for="nc-sla" class="block text-xs font-semibold text-slate-700 mb-1">SLA (horas)</label>
                  <input type="number" id="nc-sla" name="sla_horas" min="0" placeholder="Opcional"
                         class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500" />
                </div>
              </div>
              <div>
                <label for="nc-responsable" class="block text-xs font-semibold text-slate-700 mb-1">Responsable</label>
                <select id="nc-responsable" name="responsable_id"
                        class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500">
                  {"".join(usuarios_options)}
                </select>
              </div>
              <div class="flex items-center gap-4 pt-1">
                <label class="inline-flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer">
                  <input type="checkbox" name="es_inicial" value="true"
                         class="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5" />
                  Marcar como estado inicial
                </label>
                <label class="inline-flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer">
                  <input type="checkbox" name="es_final" value="true"
                         class="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5" />
                  Marcar como estado final
                </label>
              </div>
              <div class="pt-3 flex items-center justify-end gap-2">
                <button type="button" data-close-modal
                        class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">
                  Cancelar
                </button>
                <button type="submit"
                        class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white inline-flex items-center gap-1.5">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                  </svg>
                  Crear columna
                </button>
              </div>
            </form>
          </div>
        </div>'''
    )


# ===========================================================================
#  POST /estados admin: crea nueva columna desde form (HTMX)
# ===========================================================================
@router.post("/crear-form", response_class=HTMLResponse)
def crear_estado_form(
    request: Request,
    nombre: str = Form(...),
    descripcion: str = Form(""),
    color: str = Form("#6366f1"),
    orden: int = Form(0),
    categoria: str = Form("abierto"),
    sla_horas: str = Form(""),
    responsable_id: str = Form(""),
    es_inicial: str = Form(""),
    es_final: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Crea una nueva columna (estado) a partir de un form HTML/HTMX.
    Devuelve un modal de éxito + un trigger HTMX para recargar el Kanban.

    Permisos: SOLO Administrador.
    """
    # Permisos: SOLO Administrador
    rol_legible = (
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    )
    if str(rol_legible).lower() != "administrador":
        return HTMLResponse(
            content=(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="error">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Sin permisos</h3>'
                f'<p class="text-sm text-slate-600 mb-4">Solo el rol Administrador puede crear columnas.</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>'
            ),
            status_code=403,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Validaciones
    nombre = (nombre or "").strip()
    if not nombre:
        return HTMLResponse(
            content=(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nueva-columna">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Falta el nombre</h3>'
                f'<p class="text-sm text-slate-600 mb-4">Debes ingresar un nombre para la nueva columna.</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>'
            ),
            status_code=400,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Verificar unicidad
    if db.query(Estado).filter(Estado.nombre == nombre).first():
        return HTMLResponse(
            content=(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nueva-columna">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Nombre duplicado</h3>'
                f'<p class="text-sm text-slate-600 mb-4">Ya existe una columna con el nombre «{nombre}».</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>'
            ),
            status_code=400,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Validar responsable_id si viene
    resp_id_int = None
    if responsable_id and responsable_id.strip() and responsable_id.strip() != "0":
        try:
            resp_id_int = int(responsable_id)
            u = db.query(Usuario).filter(Usuario.id == resp_id_int, Usuario.is_active == True).first()  # noqa: E712
            if not u:
                return HTMLResponse(
                    content=(
                        f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nueva-columna">'
                        f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                        f'<h3 class="text-lg font-semibold text-red-700 mb-2">Responsable inválido</h3>'
                        f'<p class="text-sm text-slate-600 mb-4">El usuario seleccionado no existe o está inactivo.</p>'
                        f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                        f'</div></div>'
                    ),
                    status_code=400,
                    headers={"HX-Trigger": "ticket-error"},
                )
        except (ValueError, TypeError):
            resp_id_int = None

    # Validar orden
    try:
        orden_int = int(orden) if orden else 0
    except (ValueError, TypeError):
        orden_int = 0
    if orden_int == 0:
        max_orden = db.query(Estado).order_by(Estado.orden.desc()).first()
        orden_int = (max_orden.orden + 1) if max_orden else 1

    # SLA
    sla_int = None
    if sla_horas and str(sla_horas).strip():
        try:
            sla_int = int(sla_horas)
        except (ValueError, TypeError):
            sla_int = None

    es_inicial_bool = str(es_inicial).lower() in ("true", "on", "1", "yes")
    es_final_bool = str(es_final).lower() in ("true", "on", "1", "yes")

    # Crear estado
    estado = Estado(
        nombre=nombre,
        descripcion=(descripcion or "").strip() or None,
        color=color or "#6366f1",
        orden=orden_int,
        es_inicial=es_inicial_bool,
        es_final=es_final_bool,
        categoria=categoria or "abierto",
        sla_horas=sla_int,
        responsable_id=resp_id_int,
    )
    db.add(estado)
    try:
        db.commit()
        db.refresh(estado)
    except Exception as exc:
        db.rollback()
        return HTMLResponse(
            content=(
                f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="nueva-columna">'
                f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6">'
                f'<h3 class="text-lg font-semibold text-red-700 mb-2">Error al guardar</h3>'
                f'<p class="text-sm text-slate-600 mb-4">{exc}</p>'
                f'<button data-close-modal class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">Cerrar</button>'
                f'</div></div>'
            ),
            status_code=500,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Devolver modal de éxito y trigger para recargar el Kanban
    import json as _json
    return HTMLResponse(
        content=(
            f'<div class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 modal-backdrop" data-modal="columna-creada-ok">'
            f'<div class="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 text-center">'
            f'<div class="w-12 h-12 rounded-full bg-emerald-100 mx-auto flex items-center justify-center mb-3">'
            f'<svg class="w-7 h-7 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>'
            f'</svg></div>'
            f'<h3 class="text-lg font-semibold text-slate-800 mb-1">Columna creada</h3>'
            f'<p class="text-sm text-slate-500 mb-3">La columna «<span class="font-semibold">{estado.nombre}</span>» se agregó al tablero.</p>'
            f'<div class="flex items-center justify-center gap-2">'
            f'<button data-close-modal hx-get="/kanban" hx-target="body" hx-swap="innerHTML" hx-push-url="true" '
            f'class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">'
            f'Ver en Kanban</button>'
            f'<button data-close-modal '
            f'class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100">'
            f'Cerrar</button>'
            f'</div></div></div>'
        ),
        headers={"HX-Trigger": _json.dumps({"columna-creada": {"estado_id": estado.id}})},
    )


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

    @field_validator("responsable_id", mode="before")
    @classmethod
    def _empty_string_to_none(cls, v):
        """HTMX envía '' cuando se quiere limpiar; lo convertimos a None."""
        if v == "" or v is None:
            return None
        # Si llega como string numérico, lo convertimos a int
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                # Si no es convertible, dejamos que Pydantic emita el error
                return v
        return v

    @field_validator("nombre", mode="before")
    @classmethod
    def _empty_nombre_to_none(cls, v):
        """Nombre vacío se interpreta como None (se validará luego en el endpoint)."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


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
async def actualizar_estado(
    estado_id: int,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Edita el título y/o el responsable de una columna del Kanban.
    Devuelve el fragmento HTML del encabezado de la columna (HTMX swap).

    Permisos: SOLO el rol Administrador puede editar columnas del catálogo.

    Acepta ``application/x-www-form-urlencoded`` (HTMX envía form-data
    desde la edición inline y desde el select de responsable). Campos
    opcionales:
      - ``nombre`` (str, 1-80 chars, único)
      - ``responsable_id`` (int, o ""/"null" para desasignar)
      - ``archivado`` (bool)
    """
    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")

    # Permisos: SOLO el rol Administrador puede editar el catálogo de columnas
    rol_legible = (
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    )
    if str(rol_legible).lower() != "administrador":
        return HTMLResponse(
            content=(
                f'<div id="column-header-{estado_id}" '
                f'class="rounded-md border-2 border-red-300 bg-red-50 '
                f'px-2 py-1 text-xs text-red-700">'
                f"Sin permisos para editar la columna. "
                f"Solo el rol Administrador puede modificar columnas del Kanban."
                f"</div>"
            ),
            status_code=403,
            headers={"HX-Trigger": "ticket-error"},
        )

    # ============================================================
    # FIX: leer form-data en lugar de un body JSON (Pydantic BaseModel).
    # El frontend (HTMX) envía application/x-www-form-urlencoded, por
    # lo que Pydantic no podía parsearlo y devolvía 422 que se
    # mostraba como "Error al guardar".
    # ============================================================
    try:
        form = await request.form()
    except Exception:
        form = {}

    # Parsear nombre (si viene)
    nombre_raw = form.get("nombre")
    if nombre_raw is not None:
        nombre_clean = str(nombre_raw).strip()
        if not nombre_clean:
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
        if len(nombre_clean) > 80:
            return HTMLResponse(
                content=(
                    f'<div id="column-header-{estado_id}" '
                    f'class="rounded-md border-2 border-amber-300 bg-amber-50 '
                    f'px-2 py-1 text-xs text-amber-700">'
                    f"El nombre no puede tener más de 80 caracteres.</div>"
                ),
                status_code=400,
                headers={"HX-Trigger": "ticket-error"},
            )

    # Parsear responsable_id (si viene)
    responsable_id_presente = "responsable_id" in form
    responsable_id_parsed = None
    if responsable_id_presente:
        resp_raw = form.get("responsable_id")
        # Normalizar: cadena vacía, "null", "None", "false" => None (desasignar)
        if resp_raw in (None, "", "null", "None", "false", "False", "0"):
            responsable_id_parsed = None
        else:
            try:
                responsable_id_parsed = int(resp_raw)
            except (ValueError, TypeError):
                return HTMLResponse(
                    content=(
                        f'<div id="column-header-{estado_id}" '
                        f'class="rounded-md border-2 border-amber-300 bg-amber-50 '
                        f'px-2 py-1 text-xs text-amber-700">'
                        f"responsable_id inválido.</div>"
                    ),
                    status_code=400,
                    headers={"HX-Trigger": "ticket-error"},
                )

    # Parsear archivado (si viene)
    archivado_parsed = None
    if "archivado" in form:
        ar_raw = form.get("archivado")
        archivado_parsed = str(ar_raw).lower() in ("true", "1", "on", "yes", "si", "sí")

    # Aplicar cambios
    cambios = {}

    if nombre_raw is not None:
        nuevo = str(nombre_raw).strip()
        if nuevo and nuevo != estado.nombre:
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

    if responsable_id_presente:
        if responsable_id_parsed is None:
            if estado.responsable_id is not None:
                cambios["responsable_id"] = {
                    "anterior": estado.responsable_id,
                    "nuevo": None,
                }
                estado.responsable_id = None
        else:
            # validar que el usuario existe y está activo
            u = db.query(Usuario).filter(Usuario.id == responsable_id_parsed).first()
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

    if archivado_parsed is not None and estado.archivado != archivado_parsed:
        cambios["archivado"] = {
            "anterior": estado.archivado,
            "nuevo": archivado_parsed,
        }
        estado.archivado = archivado_parsed

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

    Permisos: SOLO el rol Administrador puede asignar responsables.
    """
    estado = db.query(Estado).filter(Estado.id == estado_id).first()
    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")

    # Permisos: SOLO Administrador
    rol_legible = (
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    )
    if str(rol_legible).lower() != "administrador":
        return HTMLResponse(
            content=(
                f'<div id="column-header-{estado_id}" '
                f'class="rounded-md border-2 border-red-300 bg-red-50 '
                f'px-2 py-1 text-xs text-red-700">'
                f"Solo el rol Administrador puede asignar responsables de columna."
                f"</div>"
            ),
            status_code=403,
            headers={"HX-Trigger": "ticket-error"},
        )

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


# ===========================================================================
#  POST /estados/reordenar  (solo Administrador)
#  Recibe la lista de IDs en el nuevo orden y actualiza el campo `orden`.
#  Usado por SortableJS al arrastrar columnas horizontalmente.
# ===========================================================================
@router.post("/reordenar", response_class=HTMLResponse)
async def reordenar_columnas(
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Reordena las columnas del Kanban (drag&drop horizontal)."""
    # Permisos: SOLO Administrador
    rol_legible = (
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    )
    if str(rol_legible).lower() != "administrador":
        return HTMLResponse(
            content=(
                '<div class="text-xs text-red-600 px-2 py-1">'
                "Solo el rol Administrador puede reordenar columnas."
                "</div>"
            ),
            status_code=403,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Aceptar tanto application/json (fetch) como form-data (HTMX)
    ids: list[int] = []
    try:
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            data = await request.json()
            raw = data.get("ids", data.get("orden", []))
        else:
            form = await request.form()
            raw = form.get("ids") or form.get("orden") or form.get("payload") or ""
    except Exception:
        raw = ""

    # Normalizar raw a list[int]
    if isinstance(raw, list):
        ids = [int(x) for x in raw if str(x).isdigit()]
    elif isinstance(raw, str) and raw:
        try:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                ids = [int(x) for x in parsed if str(x).lstrip("-").isdigit()]
        except Exception:
            # CSV
            ids = [int(x) for x in raw.replace("[", "").replace("]", "")
                                  .replace('"', "").replace("'", "").split(",")
                   if x.strip().lstrip("-").isdigit()]

    if not ids:
        return HTMLResponse(
            content=(
                '<div class="text-xs text-amber-700 px-2 py-1">'
                "Lista de IDs vacía o inválida."
                "</div>"
            ),
            status_code=400,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Verificar que todos los IDs existan
    existentes = {
        e.id for e in db.query(Estado).filter(Estado.id.in_(ids)).all()
    }
    faltantes = [i for i in ids if i not in existentes]
    if faltantes:
        return HTMLResponse(
            content=(
                f'<div class="text-xs text-amber-700 px-2 py-1">'
                f"IDs no encontrados: {faltantes}"
                f"</div>"
            ),
            status_code=400,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Asignar el nuevo orden (1-based)
    try:
        for idx, estado_id in enumerate(ids, start=1):
            db.query(Estado).filter(Estado.id == estado_id).update(
                {"orden": idx}, synchronize_session=False
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        return HTMLResponse(
            content=(
                f'<div class="text-xs text-red-700 px-2 py-1">'
                f"Error al guardar: {exc}"
                f"</div>"
            ),
            status_code=500,
            headers={"HX-Trigger": "ticket-error"},
        )

    # Emitir trigger HTMX para que el frontend muestre confirmación
    import json as _json
    return HTMLResponse(
        content=(
            f'<div class="text-xs text-emerald-700 px-2 py-1" '
            f'id="reordenar-ok">Orden guardado ({len(ids)} columnas).</div>'
        ),
        headers={"HX-Trigger": _json.dumps(
            {"columnas-reordenadas": {"total": len(ids), "ids": ids}}
        )},
    )
