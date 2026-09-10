"""
Ejecutor de reglas Butler.

Este servicio se invoca desde el servicio de tickets cuando ocurren
eventos (creación, cambio de estado, asignación, etiquetado, comentario).

Lee todas las reglas activas con el disparador correspondiente,
evalúa sus condiciones y ejecuta sus acciones. Registra cada
ejecución en la tabla ``ejecuciones_automatizacion``.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.automacion import ReglaAutomatizacion, EjecucionAutomatizacion
from app.models.estado import Estado
from app.models.etiqueta import Etiqueta, ticket_etiquetas
from app.models.comentario import Comentario
from app.models.ticket import Ticket, Prioridad
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)


# ============== Evaluación de condiciones ==============
def _get_ticket_field(ticket: Ticket, campo: str) -> Any:
    """Resuelve un campo del ticket (soporta dot notation y casos especiales)."""
    # Casos directos
    if campo in {"prioridad", "tipo", "estado", "titulo", "descripcion",
                 "codigo", "archivado"}:
        if campo == "estado":
            return ticket.estado.nombre if ticket.estado else None
        if campo == "prioridad":
            if not ticket.prioridad:
                return None
            return (
                ticket.prioridad.value
                if hasattr(ticket.prioridad, "value")
                else ticket.prioridad
            )
        if campo == "tipo":
            if not ticket.tipo:
                return None
            return (
                ticket.tipo.value
                if hasattr(ticket.tipo, "value")
                else ticket.tipo
            )
        return getattr(ticket, campo, None)
    if campo == "asignado_id":
        return ticket.asignado_id
    if campo == "asignado_username":
        return ticket.asignado.username if ticket.asignado else None
    if campo == "creador_id":
        return ticket.creador_id
    if campo == "etiquetas":
        return [e.nombre for e in ticket.etiquetas]
    if campo == "sla_cumplido":
        return ticket.sla_cumplido
    if campo == "estado_id":
        return ticket.estado_id
    if campo == "tiene_descripcion":
        return bool(ticket.descripcion and ticket.descripcion.strip())
    return getattr(ticket, campo, None)


def _evaluar_condicion(cond: Dict[str, Any], ticket: Ticket) -> bool:
    """Evalúa una condición individual contra el ticket."""
    campo = cond.get("campo")
    operador = cond.get("operador", "==")
    valor = cond.get("valor")
    if campo is None:
        return False
    actual = _get_ticket_field(ticket, campo)
    try:
        if operador == "==":
            return actual == valor
        if operador == "!=":
            return actual != valor
        if operador == "in":
            if isinstance(valor, str):
                valor = [v.strip() for v in valor.split(",")]
            return actual in (valor or [])
        if operador == "not_in":
            if isinstance(valor, str):
                valor = [v.strip() for v in valor.split(",")]
            return actual not in (valor or [])
        if operador == "contains":
            if actual is None:
                return False
            return str(valor).lower() in str(actual).lower()
        if operador == "not_contains":
            if actual is None:
                return True
            return str(valor).lower() not in str(actual).lower()
        if operador == "gt":
            return actual is not None and actual > valor
        if operador == "gte":
            return actual is not None and actual >= valor
        if operador == "lt":
            return actual is not None and actual < valor
        if operador == "lte":
            return actual is not None and actual <= valor
        if operador == "is_true":
            return bool(actual)
        if operador == "is_false":
            return not actual
        if operador == "is_empty":
            return actual in (None, "", [], {})
    except Exception as e:
        logger.warning("Error evaluando condición %s: %s", cond, e)
        return False
    return False


def _cumple_condiciones(regla: ReglaAutomatizacion, ticket: Ticket) -> bool:
    """Evalúa todas las condiciones de una regla. Soporta 'all', 'any', o lista simple."""
    condiciones = regla.condiciones or []
    if isinstance(condiciones, dict):
        all_c = condiciones.get("all", [])
        any_c = condiciones.get("any", [])
        none_c = condiciones.get("none", [])
        if all_c and not all(_evaluar_condicion(c, ticket) for c in all_c):
            return False
        if any_c and not any(_evaluar_condicion(c, ticket) for c in any_c):
            return False
        if none_c and any(_evaluar_condicion(c, ticket) for c in none_c):
            return False
        return True
    if isinstance(condiciones, list):
        if not condiciones:
            return True
        return all(_evaluar_condicion(c, ticket) for c in condiciones)
    return True


# ============== Ejecución de acciones ==============
def _ejecutar_accion(db: Session, ticket: Ticket, accion: Dict[str, Any],
                     usuario_ejecutor: Optional[Usuario] = None) -> str:
    """Ejecuta una acción individual sobre el ticket. Devuelve un mensaje de resultado."""
    tipo = accion.get("tipo")
    params = accion.get("parametros") or {}

    if tipo == "set_estado":
        estado_nombre = params.get("estado")
        if not estado_nombre:
            return "falta parámetro 'estado'"
        estado = db.query(Estado).filter(Estado.nombre == estado_nombre).first()
        if not estado:
            return f"estado '{estado_nombre}' no existe"
        ticket.estado_id = estado.id
        return f"estado -> {estado_nombre}"

    if tipo == "cambiar_estado":
        # Alias de set_estado para compatibilidad
        return _ejecutar_accion(db, ticket, {"tipo": "set_estado", "parametros": params}, usuario_ejecutor)

    if tipo == "add_etiqueta" or tipo == "agregar_etiqueta":
        et_nombre = params.get("etiqueta") or params.get("nombre")
        if not et_nombre:
            return "falta parámetro 'etiqueta'"
        et = db.query(Etiqueta).filter(Etiqueta.nombre == et_nombre).first()
        if not et:
            return f"etiqueta '{et_nombre}' no existe"
        if et not in ticket.etiquetas:
            ticket.etiquetas.append(et)
        return f"etiqueta +{et_nombre}"

    if tipo == "remove_etiqueta" or tipo == "quitar_etiqueta":
        et_nombre = params.get("etiqueta") or params.get("nombre")
        if not et_nombre:
            return "falta parámetro 'etiqueta'"
        et = db.query(Etiqueta).filter(Etiqueta.nombre == et_nombre).first()
        if et and et in ticket.etiquetas:
            ticket.etiquetas.remove(et)
        return f"etiqueta -{et_nombre}"

    if tipo == "set_asignado" or tipo == "asignar_a":
        username = params.get("username") or params.get("usuario")
        uid = params.get("usuario_id")
        target = None
        if uid:
            target = db.query(Usuario).filter(Usuario.id == int(uid)).first()
        elif username:
            target = db.query(Usuario).filter(Usuario.username == username).first()
        if not target:
            return f"usuario '{username or uid}' no encontrado"
        ticket.asignado_id = target.id
        return f"asignado -> {target.username}"

    if tipo == "set_prioridad" or tipo == "marcar_prioridad":
        prio = (params.get("prioridad") or "").lower()
        try:
            ticket.prioridad = Prioridad(prio)
            return f"prioridad -> {prio}"
        except ValueError:
            return f"prioridad '{prio}' inválida"

    if tipo == "add_comentario" or tipo == "crear_comentario":
        texto = (params.get("texto") or "").strip()
        if not texto:
            return "falta parámetro 'texto'"
        autor_id = (usuario_ejecutor.id if usuario_ejecutor
                    else ticket.creador_id or ticket.asignado_id)
        if not autor_id:
            return "no hay autor para el comentario"
        c = Comentario(
            ticket_id=ticket.id,
            usuario_id=autor_id,
            texto=texto,
            es_interno=bool(params.get("interno", False)),
        )
        db.add(c)
        return "comentario agregado"

    if tipo == "archive" or tipo == "archivar":
        ticket.archivado = True
        return "archivado"

    if tipo == "unarchive" or tipo == "desarchivar":
        ticket.archivado = False
        return "desarchivado"

    if tipo == "notify" or tipo == "enviar_notificacion":
        # Stub: registrar en log. La UI puede leer de la tabla Notificacion.
        logger.info("[Butler] Notificación disparada para ticket %s: %s",
                    ticket.id, params)
        return "notify (logged)"

    if tipo == "set_titulo":
        nuevo = (params.get("titulo") or "").strip()
        if not nuevo:
            return "falta 'titulo'"
        ticket.titulo = nuevo[:200]
        return "titulo actualizado"

    if tipo == "set_descripcion":
        nuevo = params.get("descripcion") or ""
        ticket.descripcion = nuevo[:5000]
        return "descripcion actualizada"

    return f"tipo de acción '{tipo}' no reconocido"


# ============== Ejecución principal ==============
def ejecutar_reglas(db: Session, disparador: str, ticket: Ticket,
                    contexto: Optional[Dict[str, Any]] = None,
                    usuario_ejecutor: Optional[Usuario] = None) -> List[Dict[str, Any]]:
    """Ejecuta todas las reglas activas que coincidan con el disparador."""
    contexto = contexto or {}
    resultados: List[Dict[str, Any]] = []

    try:
        reglas = (
            db.query(ReglaAutomatizacion)
            .filter(
                ReglaAutomatizacion.disparador == disparador,
                ReglaAutomatizacion.activo == True,  # noqa: E712
            )
            .order_by(ReglaAutomatizacion.prioridad.asc())
            .all()
        )
    except Exception as e:
        logger.exception("Error consultando reglas Butler: %s", e)
        return resultados

    for regla in reglas:
        resultado_regla = {
            "regla_id": regla.id,
            "regla_nombre": regla.nombre,
            "disparador": disparador,
            "ticket_id": ticket.id,
            "condiciones_cumplidas": False,
            "acciones_ejecutadas": [],
            "exito": True,
            "detalle": None,
        }
        try:
            if not _cumple_condiciones(regla, ticket):
                resultado_regla["detalle"] = "condiciones no cumplidas"
                _registrar_ejecucion(db, regla, ticket, contexto, exito=False,
                                     detalle="condiciones no cumplidas")
                continue
            resultado_regla["condiciones_cumplidas"] = True

            for accion in (regla.acciones or []):
                try:
                    msg = _ejecutar_accion(db, ticket, accion, usuario_ejecutor)
                    resultado_regla["acciones_ejecutadas"].append({
                        "tipo": accion.get("tipo"),
                        "resultado": msg,
                    })
                except Exception as e:
                    logger.exception("Error en acción Butler: %s", e)
                    resultado_regla["acciones_ejecutadas"].append({
                        "tipo": accion.get("tipo"),
                        "error": str(e),
                    })
                    resultado_regla["exito"] = False

            db.flush()
            _registrar_ejecucion(
                db, regla, ticket, contexto,
                exito=resultado_regla["exito"],
                detalle=json.dumps(resultado_regla["acciones_ejecutadas"],
                                   ensure_ascii=False, default=str)[:1000],
            )
        except Exception as e:
            logger.exception("Error ejecutando regla Butler %s: %s", regla.id, e)
            resultado_regla["exito"] = False
            resultado_regla["detalle"] = str(e)
            try:
                _registrar_ejecucion(db, regla, ticket, contexto,
                                     exito=False, detalle=str(e)[:1000])
            except Exception:
                pass
        resultados.append(resultado_regla)

    return resultados


def _registrar_ejecucion(db: Session, regla: ReglaAutomatizacion, ticket: Ticket,
                          contexto: Dict[str, Any], exito: bool,
                          detalle: Optional[str] = None) -> None:
    """Registra la ejecución en la tabla ejecuciones_automatizacion."""
    try:
        ejec = EjecucionAutomatizacion(
            regla_id=regla.id,
            ticket_id=ticket.id,
            contexto=contexto or None,
            exito=1 if exito else 0,
            detalle=detalle,
        )
        db.add(ejec)
        db.flush()
    except Exception as e:
        logger.warning("No se pudo registrar ejecución Butler: %s", e)


# ============== Hooks (entrada desde otros servicios) ==============
def on_ticket_creado(ticket_id: int, usuario: Optional[Usuario] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return []
        resultados = ejecutar_reglas(db, "ticket_creado", ticket, {}, usuario)
        if any(r["exito"] for r in resultados):
            db.commit()
        else:
            db.rollback()
        return resultados
    except Exception as e:
        logger.exception("on_ticket_creado Butler: %s", e)
        try: db.rollback()
        except Exception: pass
        return []
    finally:
        db.close()


def on_ticket_cambio_estado(ticket_id: int, estado_anterior_id: Optional[int],
                             estado_nuevo_id: int,
                             usuario: Optional[Usuario] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return []
        contexto = {
            "estado_anterior_id": estado_anterior_id,
            "estado_nuevo_id": estado_nuevo_id,
        }
        resultados = ejecutar_reglas(db, "ticket_estado_cambiado", ticket, contexto, usuario)
        if any(r["exito"] for r in resultados):
            db.commit()
        else:
            db.rollback()
        return resultados
    except Exception as e:
        logger.exception("on_ticket_cambio_estado Butler: %s", e)
        try: db.rollback()
        except Exception: pass
        return []
    finally:
        db.close()


def on_ticket_etiquetado(ticket_id: int, etiqueta_id: int,
                          usuario: Optional[Usuario] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return []
        contexto = {"etiqueta_id": etiqueta_id}
        resultados = ejecutar_reglas(db, "ticket_etiquetado", ticket, contexto, usuario)
        if any(r["exito"] for r in resultados):
            db.commit()
        else:
            db.rollback()
        return resultados
    except Exception as e:
        logger.exception("on_ticket_etiquetado Butler: %s", e)
        try: db.rollback()
        except Exception: pass
        return []
    finally:
        db.close()


def on_ticket_comentado(ticket_id: int, comentario_id: int,
                         usuario: Optional[Usuario] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return []
        contexto = {"comentario_id": comentario_id}
        resultados = ejecutar_reglas(db, "ticket_comentado", ticket, contexto, usuario)
        if any(r["exito"] for r in resultados):
            db.commit()
        else:
            db.rollback()
        return resultados
    except Exception as e:
        logger.exception("on_ticket_comentado Butler: %s", e)
        try: db.rollback()
        except Exception: pass
        return []
    finally:
        db.close()


def on_sla_por_vencer(ticket_id: int) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return []
        resultados = ejecutar_reglas(db, "sla_por_vencer", ticket, {})
        if any(r["exito"] for r in resultados):
            db.commit()
        else:
            db.rollback()
        return resultados
    except Exception as e:
        logger.exception("on_sla_por_vencer Butler: %s", e)
        try: db.rollback()
        except Exception: pass
        return []
    finally:
        db.close()
