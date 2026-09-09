"""
Router API con todas las nuevas funcionalidades estilo Trello:
- Espacios (workspaces)
- Tableros y permisos
- Watch (suscripciones)
- Reacciones emoji
- Notificaciones
- Campos personalizados
- Botones Butler
- Comandos programados
- Vistas multidimensionales (tabla/timeline/calendario)
- Metadatos extendidos de tickets
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Response, Query, Body
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.ticket import Ticket
from app.models.espacio import Espacio, Tablero, PermisoTablero
from app.models.watch import Watch, Reaccion, Notificacion
from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
from app.models.butler_extras import (
    BotonTarjeta, EjecucionBoton, ComandoProgramado, EjecucionComando,
)
from app.schemas.trello import (
    EspacioCreate, EspacioUpdate, EspacioRead,
    TableroCreate, TableroUpdate, TableroRead,
    PermisoTableroCreate,
    WatchCreate,
    ReaccionCreate, ReaccionRead, ReaccionGrupo,
    CampoPersonalizadoCreate, CampoPersonalizadoUpdate, CampoPersonalizadoRead,
    ValorCampoCreate, ValorCampoRead,
    BotonTarjetaCreate, BotonTarjetaUpdate, BotonTarjetaRead,
    ComandoProgramadoCreate, ComandoProgramadoUpdate, ComandoProgramadoRead,
    NotificacionRead, TicketMetadataUpdate,
)
from app.services.trello_service import (
    MarkdownParser, WatchService, ReaccionService, NotificacionService,
    CampoPersonalizadoService, VistasService, EspacioService, TableroService,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trello"])


# ==========================================
# ESPACIOS (WORKSPACES)
# ==========================================
@router.get("/espacios", response_model=List[EspacioRead])
def listar_espacios(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return EspacioService(db).listar(user.id)


@router.post("/espacios", response_model=EspacioRead, status_code=201)
def crear_espacio(
    datos: EspacioCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return EspacioService(db).crear(datos.model_dump(), propietario_id=user.id)


@router.get("/espacios/{espacio_id}")
def detalle_espacio(
    espacio_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    espacio = db.query(Espacio).filter(Espacio.id == espacio_id).first()
    if not espacio:
        raise HTTPException(status_code=404, detail="Espacio no encontrado")
    if user not in espacio.miembros and not espacio.es_publico:
        raise HTTPException(status_code=403, detail="Sin acceso a este espacio")
    return {
        "id": espacio.id, "nombre": espacio.nombre, "descripcion": espacio.descripcion,
        "plan": espacio.plan, "es_publico": espacio.es_publico, "color": espacio.color,
        "icono": espacio.icono, "propietario_id": espacio.propietario_id,
        "total_miembros": espacio.total_miembros, "total_tableros": espacio.total_tableros,
        "miembros": [{"id": u.id, "username": u.username, "nombre_completo": u.nombre_completo,
                      "rol": u.rol.value if hasattr(u.rol, "value") else str(u.rol)}
                     for u in espacio.miembros],
        "tableros": [{"id": t.id, "nombre": t.nombre, "visibilidad": t.visibilidad,
                      "archivado": t.archivado} for t in espacio.tableros],
    }


@router.patch("/espacios/{espacio_id}", response_model=EspacioRead)
def actualizar_espacio(
    espacio_id: int,
    datos: EspacioUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    espacio = db.query(Espacio).filter(Espacio.id == espacio_id).first()
    if not espacio:
        raise HTTPException(status_code=404, detail="Espacio no encontrado")
    if espacio.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Solo el propietario puede editar el espacio")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(espacio, k, v)
    db.commit()
    db.refresh(espacio)
    return espacio


@router.post("/espacios/{espacio_id}/miembros/{usuario_id}", status_code=204)
def agregar_miembro_espacio(
    espacio_id: int, usuario_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    espacio = db.query(Espacio).filter(Espacio.id == espacio_id).first()
    if not espacio:
        raise HTTPException(status_code=404, detail="Espacio no encontrado")
    if espacio.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    if not EspacioService(db).agregar_miembro(espacio_id, usuario_id):
        raise HTTPException(status_code=400, detail="No se pudo agregar")
    return Response(status_code=204)


@router.delete("/espacios/{espacio_id}/miembros/{usuario_id}", status_code=204)
def quitar_miembro_espacio(
    espacio_id: int, usuario_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    espacio = db.query(Espacio).filter(Espacio.id == espacio_id).first()
    if not espacio:
        raise HTTPException(status_code=404, detail="Espacio no encontrado")
    if espacio.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    EspacioService(db).quitar_miembro(espacio_id, usuario_id)
    return Response(status_code=204)


# ==========================================
# TABLEROS
# ==========================================
@router.get("/tableros", response_model=List[TableroRead])
def listar_tableros(
    espacio_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    q = db.query(Tablero).filter(Tablero.archivado == False)  # noqa
    if espacio_id:
        q = q.filter(Tablero.espacio_id == espacio_id)
    tableros = q.all()
    # Filtrar por acceso
    return [t for t in tableros if t.usuario_tiene_acceso(user)]


@router.post("/tableros", response_model=TableroRead, status_code=201)
def crear_tablero(
    datos: TableroCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    espacio = db.query(Espacio).filter(Espacio.id == datos.espacio_id).first()
    if not espacio:
        raise HTTPException(status_code=404, detail="Espacio no encontrado")
    if user not in espacio.miembros and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin acceso al espacio")
    return TableroService(db).crear(datos.model_dump(), propietario_id=user.id)


@router.get("/tableros/{tablero_id}", response_model=TableroRead)
def detalle_tablero(
    tablero_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if not tablero.usuario_tiene_acceso(user):
        raise HTTPException(status_code=403, detail="Sin acceso al tablero")
    return tablero


@router.patch("/tableros/{tablero_id}", response_model=TableroRead)
def actualizar_tablero(
    tablero_id: int,
    datos: TableroUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if tablero.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(tablero, k, v)
    db.commit()
    db.refresh(tablero)
    return tablero


@router.post("/tableros/{tablero_id}/archivar", status_code=204)
def archivar_tablero(
    tablero_id: int, db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if tablero.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    TableroService(db).archivar(tablero_id)
    return Response(status_code=204)


@router.post("/tableros/{tablero_id}/restaurar", status_code=204)
def restaurar_tablero(
    tablero_id: int, db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if tablero.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    TableroService(db).restaurar(tablero_id)
    return Response(status_code=204)


# ==========================================
# PERMISOS DE TABLERO
# ==========================================
@router.get("/tableros/{tablero_id}/permisos")
def listar_permisos_tablero(
    tablero_id: int, db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if tablero.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    return [
        {
            "id": p.id, "tablero_id": p.tablero_id, "usuario_id": p.usuario_id,
            "rol_tablero": p.rol_tablero, "notificar": p.notificar,
            "usuario": {
                "id": p.usuario.id, "username": p.usuario.username,
                "nombre_completo": p.usuario.nombre_completo,
            } if p.usuario else None,
        }
        for p in tablero.permisos
    ]


@router.post("/tableros/{tablero_id}/permisos", status_code=201)
def invitar_a_tablero(
    tablero_id: int, datos: PermisoTableroCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if tablero.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    if datos.rol_tablero not in ("admin", "editor", "lector"):
        raise HTTPException(status_code=400, detail="Rol no válido")
    # Si ya existe, actualizar
    permiso = (
        db.query(PermisoTablero)
        .filter(PermisoTablero.tablero_id == tablero_id,
                PermisoTablero.usuario_id == datos.usuario_id)
        .first()
    )
    if permiso:
        permiso.rol_tablero = datos.rol_tablero
        permiso.notificar = datos.notificar
    else:
        permiso = PermisoTablero(
            tablero_id=tablero_id, usuario_id=datos.usuario_id,
            rol_tablero=datos.rol_tablero, notificar=datos.notificar,
            invitado_por_id=user.id,
        )
        db.add(permiso)
    db.commit()
    db.refresh(permiso)
    return {"id": permiso.id, "tablero_id": permiso.tablero_id, "usuario_id": permiso.usuario_id,
            "rol_tablero": permiso.rol_tablero, "notificar": permiso.notificar}


@router.delete("/tableros/{tablero_id}/permisos/{usuario_id}", status_code=204)
def revocar_permiso_tablero(
    tablero_id: int, usuario_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    tablero = db.query(Tablero).filter(Tablero.id == tablero_id).first()
    if not tablero:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    if tablero.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Sin permiso")
    permiso = (
        db.query(PermisoTablero)
        .filter(PermisoTablero.tablero_id == tablero_id,
                PermisoTablero.usuario_id == usuario_id)
        .first()
    )
    if permiso:
        db.delete(permiso)
        db.commit()
    return Response(status_code=204)


# ==========================================
# WATCH (SUSCRIPCIONES)
# ==========================================
@router.post("/watch", status_code=201)
def toggle_watch(
    datos: WatchCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Alterna la suscripción. Devuelve estado actual."""
    svc = WatchService(db)
    suscrito = svc.toggle(user.id, datos.tipo_objeto, datos.objeto_id, datos.canal)
    return {"suscrito": suscrito, "tipo_objeto": datos.tipo_objeto, "objeto_id": datos.objeto_id}


@router.get("/watch")
def listar_mis_suscripciones(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return [
        {
            "id": w.id, "tipo_objeto": w.tipo_objeto, "objeto_id": w.objeto_id,
            "canal": w.canal, "activo": w.activo,
        }
        for w in WatchService(db).listar_suscripciones(user.id)
    ]


# ==========================================
# REACCIONES
# ==========================================
@router.post("/reacciones/toggle")
def toggle_reaccion(
    datos: ReaccionCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        resultado = ReaccionService(db).toggle(
            user.id, datos.tipo_objeto, datos.objeto_id, datos.emoji
        )
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reacciones/{tipo_objeto}/{objeto_id}", response_model=List[ReaccionGrupo])
def listar_reacciones(
    tipo_objeto: str, objeto_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return ReaccionService(db).agrupar_por_emoji(tipo_objeto, objeto_id, user.id)


# ==========================================
# NOTIFICACIONES
# ==========================================
@router.get("/notificaciones", response_model=List[NotificacionRead])
def listar_notificaciones(
    solo_no_leidas: bool = False,
    limite: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return NotificacionService(db).listar(user.id, solo_no_leidas, limite)


@router.get("/notificaciones/contador")
def contar_notificaciones_no_leidas(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return {
        "no_leidas": NotificacionService(db).contar_no_leidas(user.id),
        "total": db.query(Notificacion).filter(Notificacion.usuario_id == user.id).count(),
    }


@router.post("/notificaciones/{notif_id}/leida", status_code=204)
def marcar_notif_leida(
    notif_id: int, db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    if not NotificacionService(db).marcar_leida(notif_id, user.id):
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    return Response(status_code=204)


@router.post("/notificaciones/marcar-todas-leidas")
def marcar_todas_leidas(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    count = NotificacionService(db).marcar_todas_leidas(user.id)
    return {"marcadas": count}


# ==========================================
# CAMPOS PERSONALIZADOS
# ==========================================
@router.get("/campos-personalizados", response_model=List[CampoPersonalizadoRead])
def listar_campos(
    tablero_id: int = Query(None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    svc = CampoPersonalizadoService(db)
    if tablero_id is None:
        return svc.listar_todos()
    return svc.listar_de_tablero(tablero_id)


@router.post("/campos-personalizados", response_model=CampoPersonalizadoRead, status_code=201)
def crear_campo(
    datos: CampoPersonalizadoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    try:
        return CampoPersonalizadoService(db).crear_campo(**datos.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/campos-personalizados/{campo_id}", response_model=CampoPersonalizadoRead)
def actualizar_campo(
    campo_id: int, datos: CampoPersonalizadoUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    campo = db.query(CampoPersonalizado).filter(CampoPersonalizado.id == campo_id).first()
    if not campo:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(campo, k, v)
    db.commit()
    db.refresh(campo)
    return campo


@router.delete("/campos-personalizados/{campo_id}", status_code=204)
def eliminar_campo(
    campo_id: int, db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    if not CampoPersonalizadoService(db).eliminar_campo(campo_id):
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    return Response(status_code=204)


@router.post("/tickets/{ticket_id}/campos")
def asignar_valor_campo(
    ticket_id: int, datos: ValorCampoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Asigna o actualiza el valor de un campo personalizado en un ticket."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    valor = CampoPersonalizadoService(db).asignar_valor(
        campo_id=datos.campo_id,
        ticket_id=ticket_id,
        valor_texto=datos.valor_texto,
        valor_numero=datos.valor_numero,
        valor_booleano=datos.valor_booleano,
        valor_fecha=datos.valor_fecha,
    )
    return {
        "id": valor.id, "campo_id": valor.campo_id, "ticket_id": valor.ticket_id,
        "valor_texto": valor.valor_texto, "valor_numero": valor.valor_numero,
        "valor_booleano": valor.valor_booleano, "valor_fecha": valor.valor_fecha,
    }


@router.get("/tickets/{ticket_id}/campos")
def listar_campos_con_valores(
    ticket_id: int, db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Lista todos los campos personalizados del tablero del ticket con sus valores."""
    return CampoPersonalizadoService(db).obtener_campos_con_valores(ticket_id)


# ==========================================
# BOTONES DE TARJETA / TABLERO
# ==========================================
@router.get("/botones", response_model=List[BotonTarjetaRead])
def listar_botones(
    tablero_id: Optional[int] = None,
    ambito: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    q = db.query(BotonTarjeta).filter(BotonTarjeta.activo == True)  # noqa
    if tablero_id is not None:
        q = q.filter((BotonTarjeta.tablero_id == tablero_id) | (BotonTarjeta.tablero_id.is_(None)))
    if ambito:
        q = q.filter(BotonTarjeta.ambito == ambito)
    return q.order_by(BotonTarjeta.posicion).all()


@router.post("/botones", response_model=BotonTarjetaRead, status_code=201)
def crear_boton(
    datos: BotonTarjetaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    boton = BotonTarjeta(creador_id=user.id, **datos.model_dump())
    db.add(boton)
    db.commit()
    db.refresh(boton)
    return boton


@router.patch("/botones/{boton_id}", response_model=BotonTarjetaRead)
def actualizar_boton(
    boton_id: int, datos: BotonTarjetaUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    boton = db.query(BotonTarjeta).filter(BotonTarjeta.id == boton_id).first()
    if not boton:
        raise HTTPException(status_code=404, detail="Botón no encontrado")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(boton, k, v)
    db.commit()
    db.refresh(boton)
    return boton


@router.delete("/botones/{boton_id}", status_code=204)
def eliminar_boton(
    boton_id: int, db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    boton = db.query(BotonTarjeta).filter(BotonTarjeta.id == boton_id).first()
    if not boton:
        raise HTTPException(status_code=404, detail="Botón no encontrado")
    db.delete(boton)
    db.commit()
    return Response(status_code=204)


@router.post("/botones/{boton_id}/ejecutar")
def ejecutar_boton(
    boton_id: int,
    datos: dict = Body(default={}),
    ticket_id: int = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Ejecuta un botón Butler sobre un ticket."""
    # Aceptar ticket_id desde body o query
    if ticket_id is None:
        ticket_id = datos.get("ticket_id")
    if ticket_id is None:
        raise HTTPException(status_code=400, detail="ticket_id requerido")
    boton = db.query(BotonTarjeta).filter(BotonTarjeta.id == boton_id).first()
    if not boton or not boton.activo:
        raise HTTPException(status_code=404, detail="Botón no encontrado o inactivo")
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    # Importar motor de automatizaciones existente
    from app.services.features_service import MotorAutomatizacion
    motor = MotorAutomatizacion(db)
    detalles = []
    exito = True
    for acc in (boton.acciones or []):
        try:
            detalle = motor._ejecutar_accion(ticket, acc)
            detalles.append({"accion": acc.get("tipo"), "detalle": detalle})
        except Exception as e:
            detalles.append({"accion": acc.get("tipo"), "error": str(e)})
            exito = False
    # Registrar ejecución
    ejec = EjecucionBoton(
        boton_id=boton.id, ticket_id=ticket.id, usuario_id=user.id,
        exito=exito, detalle=str(len(detalles)) + " acciones ejecutadas",
    )
    db.add(ejec)
    db.commit()
    return {"exito": exito, "detalles": detalles}


# ==========================================
# COMANDOS PROGRAMADOS
# ==========================================
@router.get("/comandos-programados", response_model=List[ComandoProgramadoRead])
def listar_comandos(
    tablero_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    q = db.query(ComandoProgramado).filter(ComandoProgramado.activo == True)  # noqa
    if tablero_id is not None:
        q = q.filter((ComandoProgramado.tablero_id == tablero_id) | (ComandoProgramado.tablero_id.is_(None)))
    return q.all()


@router.post("/comandos-programados", response_model=ComandoProgramadoRead, status_code=201)
def crear_comando(
    datos: ComandoProgramadoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    # Validar expresión cron (5 campos separados por espacio)
    partes = datos.cron_expression.split()
    if len(partes) != 5:
        raise HTTPException(
            status_code=400,
            detail="cron_expression debe tener 5 campos: min hora dia-mes mes dia-semana",
        )
    comando = ComandoProgramado(creador_id=user.id, **datos.model_dump())
    db.add(comando)
    db.commit()
    db.refresh(comando)
    return comando


@router.patch("/comandos-programados/{comando_id}", response_model=ComandoProgramadoRead)
def actualizar_comando(
    comando_id: int, datos: ComandoProgramadoUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    comando = db.query(ComandoProgramado).filter(ComandoProgramado.id == comando_id).first()
    if not comando:
        raise HTTPException(status_code=404, detail="Comando no encontrado")
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(comando, k, v)
    db.commit()
    db.refresh(comando)
    return comando


@router.delete("/comandos-programados/{comando_id}", status_code=204)
def eliminar_comando(
    comando_id: int, db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    comando = db.query(ComandoProgramado).filter(ComandoProgramado.id == comando_id).first()
    if not comando:
        raise HTTPException(status_code=404, detail="Comando no encontrado")
    db.delete(comando)
    db.commit()
    return Response(status_code=204)


@router.post("/comandos-programados/{comando_id}/ejecutar-ahora")
def ejecutar_comando_ahora(
    comando_id: int, db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR)),
):
    """Fuerza la ejecución inmediata de un comando."""
    comando = db.query(ComandoProgramado).filter(ComandoProgramado.id == comando_id).first()
    if not comando:
        raise HTTPException(status_code=404, detail="Comando no encontrado")
    from app.services.features_service import MotorAutomatizacion
    motor = MotorAutomatizacion(db)
    # Aplicar a todos los tickets del tablero (o todos si es global)
    q = db.query(Ticket)
    if comando.tablero_id is not None:
        q = q.filter(Ticket.tablero_id == comando.tablero_id)
    tickets = q.all()
    afectados = 0
    for t in tickets:
        for acc in (comando.acciones or []):
            try:
                motor._ejecutar_accion(t, acc)
                afectados += 1
            except Exception:
                pass
    db.commit()
    ej = EjecucionComando(
        comando_id=comando.id, exito=True,
        detalle=f"{afectados} acciones ejecutadas sobre {len(tickets)} tickets",
        tickets_afectados=len(tickets),
    )
    db.add(ej)
    comando.ultima_ejecucion = datetime.utcnow().isoformat()
    db.commit()
    return {"exito": True, "tickets_procesados": len(tickets), "acciones_ejecutadas": afectados}


# ==========================================
# METADATOS EXTENDIDOS DE TICKETS
# ==========================================
@router.patch("/tickets/{ticket_id}/metadata")
def actualizar_metadata_ticket(
    ticket_id: int, datos: TicketMetadataUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Actualiza metadatos extendidos: fechas, portada, miembros múltiples, archivado."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    payload = datos.model_dump(exclude_unset=True)
    miembros_ids = payload.pop("miembros_ids", None)
    for k, v in payload.items():
        setattr(ticket, k, v)
    if miembros_ids is not None:
        # Reemplazar miembros
        from app.models.usuario import Usuario as UsuarioModel
        nuevos_miembros = (
            db.query(UsuarioModel).filter(UsuarioModel.id.in_(miembros_ids)).all()
        )
        ticket.miembros = nuevos_miembros
    db.commit()
    db.refresh(ticket)
    return {
        "id": ticket.id, "codigo": ticket.codigo, "titulo": ticket.titulo,
        "fecha_inicio": ticket.fecha_inicio.isoformat() if ticket.fecha_inicio else None,
        "fecha_completado": ticket.fecha_completado.isoformat() if ticket.fecha_completado else None,
        "fecha_cumplida": ticket.fecha_cumplida,
        "portada_color": ticket.portada_color,
        "portada_adjunto_id": ticket.portada_adjunto_id,
        "descripcion_md": ticket.descripcion_md,
        "archivado": ticket.archivado,
        "posicion": ticket.posicion,
        "miembros": [{"id": m.id, "nombre": m.nombre_completo} for m in ticket.miembros],
    }


# ==========================================
# VISTAS MULTIDIMENSIONALES
# ==========================================
@router.get("/vistas/tabla")
def vista_tabla(
    tablero_id: Optional[int] = None,
    estados_ids: Optional[str] = None,
    asignados_ids: Optional[str] = None,
    etiquetas_ids: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Genera datos para vista de tabla (Excel-like)."""
    filtros = {}
    if estados_ids:
        filtros["estados_ids"] = [int(x) for x in estados_ids.split(",") if x.strip()]
    if asignados_ids:
        filtros["asignados_ids"] = [int(x) for x in asignados_ids.split(",") if x.strip()]
    if etiquetas_ids:
        filtros["etiquetas_ids"] = [int(x) for x in etiquetas_ids.split(",") if x.strip()]
    filas = VistasService(db).vista_tabla(tablero_id, filtros)
    return {"total": len(filas), "filas": filas}


@router.get("/vistas/calendario")
def vista_calendario(
    tablero_id: Optional[int] = None,
    mes: Optional[int] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Genera eventos para vista de calendario mensual."""
    return VistasService(db).vista_calendario(tablero_id, mes, anio)


@router.get("/vistas/timeline")
def vista_timeline(
    tablero_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Genera datos para vista Timeline (Gantt)."""
    items = VistasService(db).vista_timeline(tablero_id)
    return {"total": len(items), "items": items}


# ==========================================
# MARKDOWN (util)
# ==========================================
@router.post("/markdown/renderizar")
def renderizar_markdown(
    datos: dict = Body(default={}),
    texto: str = Query(None),
    _user: Usuario = Depends(get_current_user),
):
    """Renderiza texto Markdown a HTML seguro."""
    if texto is None:
        texto = datos.get("texto", "")
    return {"html": MarkdownParser.to_html(texto), "menciones": MarkdownParser.extraer_menciones(texto), "texto": texto}
