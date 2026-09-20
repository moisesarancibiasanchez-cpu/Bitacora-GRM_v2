"""
Endpoints API para FEATURE 3: Dependencias Gantt + Import .mpp/XML.

Endpoints:
    POST   /api/v1/dependencias                  → crear
    GET    /api/v1/dependencias/ticket/{id}      → listar las de un ticket
    DELETE /api/v1/dependencias/{dep_id}         → eliminar
    POST   /api/v1/dependencias/importar-xml     → importar .mpp exportado
    GET    /api/v1/dependencias/xml-preview      → preview de import

Todos requieren sesión activa. La creación/eliminación/importación
requieren permiso ``configurar_butler`` o ser Administrador (el permiso
genérico para tocar configuración del sistema).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_current_user
from app.models.ticket import Ticket
from app.models.ticket_dependencia import (
    TIPO_DEPENDENCIA_NOMBRES, TicketDependencia, TipoDependencia,
)
from app.models.usuario import Usuario, RolUsuario
from app.services.dependencia_service import (
    DependenciaError, MSProjectXMLParser, TicketDependenciaService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dependencias", tags=["dependencias"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class DependenciaCreate(BaseModel):
    predecesor_id: int = Field(..., gt=0)
    sucesor_id: int = Field(..., gt=0)
    tipo: str = Field("fs", description="FS / SS / FF / SF")
    lag_dias: int = Field(0, ge=-365, le=365)
    nota: Optional[str] = None


class DependenciaRead(BaseModel):
    id: int
    predecesor_id: int
    predecesor_codigo: str
    predecesor_titulo: str
    sucesor_id: int
    sucesor_codigo: str
    sucesor_titulo: str
    tipo: str
    tipo_nombre: str
    lag_dias: int
    nota: Optional[str] = None

    class Config:
        from_attributes = True


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _requiere_admin_o_agente_senior(usuario: Usuario) -> None:
    """Sólo Admin y Agente Senior pueden crear/eliminar dependencias."""
    if usuario.rol not in (RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR):
        raise HTTPException(
            status_code=403,
            detail="Solo Administrador o Agente Senior pueden gestionar dependencias.",
        )


def _to_read(d: TicketDependencia) -> DependenciaRead:
    return DependenciaRead(
        id=d.id,
        predecesor_id=d.predecesor_id,
        predecesor_codigo=d.predecesor.codigo if d.predecesor else "?",
        predecesor_titulo=(d.predecesor.titulo if d.predecesor else "")[:80],
        sucesor_id=d.sucesor_id,
        sucesor_codigo=d.sucesor.codigo if d.sucesor else "?",
        sucesor_titulo=(d.sucesor.titulo if d.sucesor else "")[:80],
        tipo=d.tipo.value,
        tipo_nombre=TIPO_DEPENDENCIA_NOMBRES.get(d.tipo, d.tipo.value),
        lag_dias=d.lag_dias,
        nota=d.nota,
    )


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@router.post("", response_model=DependenciaRead, status_code=201)
def crear_dependencia(
    payload: DependenciaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Crea una nueva dependencia entre dos tickets."""
    _requiere_admin_o_agente_senior(usuario)
    svc = TicketDependenciaService(db)
    try:
        dep = svc.crear(
            predecesor_id=payload.predecesor_id,
            sucesor_id=payload.sucesor_id,
            tipo=payload.tipo,
            lag_dias=payload.lag_dias,
            nota=payload.nota,
        )
    except DependenciaError as e:
        raise HTTPException(status_code=400, detail={"codigo": e.codigo, "mensaje": e.mensaje})
    return _to_read(dep)


@router.get("/ticket/{ticket_id}", response_model=List[DependenciaRead])
def listar_dependencias_de_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista las dependencias (salientes + entrantes) de un ticket."""
    # Cualquier usuario autenticado puede VER las dependencias (necesario
    # para el Gantt).
    svc = TicketDependenciaService(db)
    deps = svc.listar_para_tickets([ticket_id])
    return [_to_read(d) for d in deps]


@router.get("/ticket-batch", response_model=List[DependenciaRead])
def listar_dependencias_para_batch(
    ids: str = Query(..., description="IDs separados por coma (ej: '1,2,3')"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lista todas las dependencias cuyo predecesor O sucesor esté en el set.

    Usado por el Gantt para alimentar las flechas de dependencia.
    """
    try:
        ids_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Lista de IDs inválida.")
    svc = TicketDependenciaService(db)
    deps = svc.listar_para_tickets(ids_list)
    return [_to_read(d) for d in deps]


@router.delete("/{dep_id}", status_code=204)
def eliminar_dependencia(
    dep_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    _requiere_admin_o_agente_senior(usuario)
    svc = TicketDependenciaService(db)
    ok = svc.eliminar(dep_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Dependencia no encontrada.")
    return None


# -----------------------------------------------------------------------------
# Importador .mpp / XML
# -----------------------------------------------------------------------------
class ImportarXMLRequest(BaseModel):
    """Petición para importar dependencias desde XML de MS Project.

    El XML puede venir:
        - Como string en el campo ``xml_content`` (útil para tests o
          integraciones que ya tienen el texto en memoria).
        - Como archivo subido en un endpoint separado
          (``/dependencias/importar-xml-file``).
    """
    xml_content: str = Field(..., description="Contenido del XML exportado de MS Project.")
    dry_run: bool = Field(
        True,
        description="Si True, NO crea dependencias; sólo devuelve el preview.",
    )
    crear_tickets_faltantes: bool = Field(
        False,
        description="Si True, crea tickets para las tareas del XML que NO "
                    "existan en Bitácora (match por codigo + HU).",
    )


class ImportarXMLResponse(BaseModel):
    preview: bool
    tareas_xml: int
    tareas_conocidas: int
    tareas_a_crear: List[dict]
    links_xml: int
    links_a_crear: List[dict]
    links_omitidos: List[dict]
    errores: List[str]


@router.post("/importar-xml", response_model=ImportarXMLResponse)
def importar_xml(
    payload: ImportarXMLRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Importa dependencias desde un XML de MS Project (.mpp exportado).

    Lógica:
        1. Parsea el XML.
        2. Para cada ``<Task>`` busca un ticket existente con el mismo
           ``UID`` (lo intentamos mapear por el campo ``hu_o_caso_prueba``
           que viene en los tickets GAR_, o por el código directo si
           ya lo tenemos guardado).
        3. Para cada ``<PredecessorLink>`` con predecesor y sucesor
           conocidos, crea la dependencia (con el tipo FS/SS/FF/SF).
        4. Si ``dry_run=True``, NO persiste; sólo reporta lo que haría.
    """
    _requiere_admin_o_agente_senior(usuario)

    # 1) Parsear
    parser = MSProjectXMLParser(payload.xml_content.encode("utf-8"))
    try:
        data = parser.parsear()
    except DependenciaError as e:
        raise HTTPException(status_code=400, detail={"codigo": e.codigo, "mensaje": e.mensaje})

    # 2) Indexar tickets existentes por UID-derivado:
    #    Si el ticket tiene un hu_o_caso_prueba que matchea el WBS del XML,
    #    o si su codigo empieza con GAR_<wbs>, lo asociamos.
    #    Para GAR_ los HU son del estilo "SC_5.4" o "MD_22".
    tickets = (
        db.query(Ticket)
        .filter(Ticket.archivado == False)  # noqa: E712
        .all()
    )

    def _match_ticket(tarea: dict) -> Optional[Ticket]:
        """Encuentra el ticket que corresponde a una tarea del XML."""
        # Estrategia 1: por hu_o_caso_prueba exacto (case-insensitive)
        hu_busqueda = (tarea.get("wbs") or tarea.get("name", "")).strip()
        for t in tickets:
            if t.hu_o_caso_prueba and t.hu_o_caso_prueba.strip().lower() == hu_busqueda.lower():
                return t
        # Estrategia 2: por código que contenga la WBS
        for t in tickets:
            if t.codigo and hu_busqueda and hu_busqueda.lower() in t.codigo.lower():
                return t
        return None

    # 3) Resolver tareas
    tareas_conocidas = 0
    mapa_uid_a_ticket = {}  # uid_xml → Ticket
    tareas_a_crear = []
    for tarea in data["tareas"]:
        t = _match_ticket(tarea)
        if t:
            mapa_uid_a_ticket[tarea["uid"]] = t
            tareas_conocidas += 1
        elif payload.crear_tickets_faltantes:
            tareas_a_crear.append({
                "uid": tarea["uid"],
                "name": tarea["name"],
                "wbs": tarea["wbs"],
                "start": tarea["start"],
                "finish": tarea["finish"],
                "duration_hours": tarea["duration_hours"],
            })

    # 4) Resolver links
    svc = TicketDependenciaService(db)
    links_a_crear = []
    links_omitidos = []
    errores = []
    for link in data["links"]:
        pred = mapa_uid_a_ticket.get(link["predecesor_uid"])
        suc = mapa_uid_a_ticket.get(link["sucesor_uid"])
        if not pred or not suc:
            links_omitidos.append({
                "predecesor_uid": link["predecesor_uid"],
                "sucesor_uid": link["sucesor_uid"],
                "motivo": "ticket_no_encontrado",
            })
            continue
        if payload.dry_run:
            links_a_crear.append({
                "predecesor_codigo": pred.codigo,
                "sucesor_codigo": suc.codigo,
                "tipo": link["tipo_str"],
                "lag_dias": link["lag_dias"],
            })
        else:
            try:
                dep = svc.crear(
                    predecesor_id=pred.id,
                    sucesor_id=suc.id,
                    tipo=link["tipo_str"],
                    lag_dias=link["lag_dias"],
                    nota=f"Importado XML MS Project (uid_pred={link['predecesor_uid']})",
                )
                links_a_crear.append({
                    "predecesor_codigo": pred.codigo,
                    "sucesor_codigo": suc.codigo,
                    "tipo": link["tipo_str"],
                    "lag_dias": link["lag_dias"],
                    "dep_id": dep.id,
                })
            except DependenciaError as e:
                errores.append(f"{pred.codigo}→{suc.codigo}: {e.mensaje}")

    return ImportarXMLResponse(
        preview=payload.dry_run,
        tareas_xml=len(data["tareas"]),
        tareas_conocidas=tareas_conocidas,
        tareas_a_crear=tareas_a_crear,
        links_xml=len(data["links"]),
        links_a_crear=links_a_crear,
        links_omitidos=links_omitidos,
        errores=errores,
    )


@router.post("/importar-xml-file", response_model=ImportarXMLResponse)
async def importar_xml_file(
    file: UploadFile = File(...),
    dry_run: bool = True,
    crear_tickets_faltantes: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Importa dependencias desde un archivo .xml/.mpp subido."""
    _requiere_admin_o_agente_senior(usuario)
    contenido = await file.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="Archivo vacío.")
    # Reusamos el endpoint interno simulando la request:
    payload = ImportarXMLRequest(
        xml_content=contenido.decode("utf-8", errors="replace"),
        dry_run=dry_run,
        crear_tickets_faltantes=crear_tickets_faltantes,
    )
    return importar_xml(payload, db=db, usuario=usuario)
