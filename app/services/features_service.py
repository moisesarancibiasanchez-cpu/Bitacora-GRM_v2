"""
Servicios para las nuevas funcionalidades estilo Trello:
- Etiquetas
- Checklists
- Comentarios
- Adjuntos
- Búsqueda y filtros
- Automatizaciones
"""
import os
import re
import uuid
import json
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func, desc, asc

from app.models.ticket import Ticket
from app.models.usuario import Usuario
from app.models.etiqueta import Etiqueta
from app.models.checklist import Checklist, ChecklistItem
from app.models.comentario import Comentario, MencionUsuario
from app.models.adjunto import Adjunto
from app.models.automacion import ReglaAutomatizacion, EjecucionAutomatizacion

logger = logging.getLogger(__name__)


# ==========================================
# ETIQUETAS
# ==========================================
class EtiquetaService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self, categoria: Optional[str] = None, solo_activas: bool = True) -> List[Etiqueta]:
        q = self.db.query(Etiqueta)
        if solo_activas:
            q = q.filter(Etiqueta.activo == True)  # noqa: E712
        if categoria:
            q = q.filter(Etiqueta.categoria == categoria)
        return q.order_by(Etiqueta.categoria, Etiqueta.nombre).all()

    def obtener(self, etiqueta_id: int) -> Optional[Etiqueta]:
        return self.db.query(Etiqueta).filter(Etiqueta.id == etiqueta_id).first()

    def crear(self, datos: dict, creador_id: Optional[int] = None) -> Etiqueta:
        et = Etiqueta(**datos)
        self.db.add(et)
        self.db.commit()
        self.db.refresh(et)
        return et

    def actualizar(self, etiqueta_id: int, datos: dict) -> Optional[Etiqueta]:
        et = self.obtener(etiqueta_id)
        if not et:
            return None
        for k, v in datos.items():
            if v is not None:
                setattr(et, k, v)
        self.db.commit()
        self.db.refresh(et)
        return et

    def asignar_a_ticket(self, ticket: Ticket, etiqueta_id: int) -> bool:
        et = self.obtener(etiqueta_id)
        if not et or et in ticket.etiquetas:
            return False
        ticket.etiquetas.append(et)
        self.db.commit()
        return True

    def quitar_de_ticket(self, ticket: Ticket, etiqueta_id: int) -> bool:
        et = self.obtener(etiqueta_id)
        if not et or et not in ticket.etiquetas:
            return False
        ticket.etiquetas.remove(et)
        self.db.commit()
        return True


# ==========================================
# CHECKLISTS
# ==========================================
class ChecklistService:
    def __init__(self, db: Session):
        self.db = db

    def listar_de_ticket(self, ticket_id: int) -> List[Checklist]:
        from sqlalchemy.orm import joinedload
        return (
            self.db.query(Checklist)
            .options(joinedload(Checklist.items))
            .filter(Checklist.ticket_id == ticket_id)
            .order_by(Checklist.orden)
            .all()
        )

    def crear(self, ticket: Ticket, titulo: str, items: List[dict] = None) -> Checklist:
        max_orden = (
            self.db.query(func.coalesce(func.max(Checklist.orden), 0))
            .filter(Checklist.ticket_id == ticket.id).scalar()
        )
        cl = Checklist(
            ticket_id=ticket.id,
            titulo=titulo,
            orden=max_orden + 1,
            posicion=max_orden + 1,
        )
        self.db.add(cl)
        self.db.flush()
        for i, it in enumerate(items or []):
            ci = ChecklistItem(
                checklist_id=cl.id,
                texto=it.get("texto", ""),
                orden=i,
                asignado_id=it.get("asignado_id"),
                fecha_vencimiento=it.get("fecha_vencimiento"),
            )
            self.db.add(ci)
        self.db.commit()
        self.db.refresh(cl)
        return cl

    def agregar_item(self, checklist_id: int, texto: str, asignado_id: Optional[int] = None) -> Optional[ChecklistItem]:
        cl = self.db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not cl:
            return None
        max_orden = (
            self.db.query(func.coalesce(func.max(ChecklistItem.orden), 0))
            .filter(ChecklistItem.checklist_id == checklist_id).scalar()
        )
        item = ChecklistItem(
            checklist_id=checklist_id,
            texto=texto,
            orden=max_orden + 1,
            asignado_id=asignado_id,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def toggle_item(self, item_id: int) -> Optional[ChecklistItem]:
        item = self.db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
        if not item:
            return None
        item.completado = not item.completado
        self.db.commit()
        self.db.refresh(item)
        return item

    def eliminar_item(self, item_id: int) -> bool:
        item = self.db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
        if not item:
            return False
        self.db.delete(item)
        self.db.commit()
        return True

    def eliminar(self, checklist_id: int) -> bool:
        cl = self.db.query(Checklist).filter(Checklist.id == checklist_id).first()
        if not cl:
            return False
        self.db.delete(cl)
        self.db.commit()
        return True


# ==========================================
# COMENTARIOS + MENCIONES
# ==========================================
class ComentarioService:
    def __init__(self, db: Session):
        self.db = db

    def listar_de_ticket(self, ticket_id: int, incluir_internos: bool = True) -> List[Comentario]:
        q = self.db.query(Comentario).filter(Comentario.ticket_id == ticket_id)
        if not incluir_internos:
            q = q.filter(Comentario.es_interno == False)  # noqa: E712
        return q.order_by(Comentario.created_at.desc()).all()

    def crear(self, ticket_id: int, usuario_id: int, texto: str, es_interno: bool = False) -> Comentario:
        com = Comentario(
            ticket_id=ticket_id,
            usuario_id=usuario_id,
            texto=texto,
            es_interno=es_interno,
        )
        self.db.add(com)
        self.db.flush()
        # Procesar menciones @usuario
        usernames = com.extraer_menciones()
        if usernames:
            usuarios = (
                self.db.query(Usuario)
                .filter(Usuario.username.in_(usernames))
                .all()
            )
            for u in usuarios:
                m = MencionUsuario(
                    comentario_id=com.id,
                    usuario_id=u.id,
                    notificado=0,
                )
                self.db.add(m)
        self.db.commit()
        self.db.refresh(com)
        return com

    def editar(self, comentario_id: int, nuevo_texto: str) -> Optional[Comentario]:
        com = self.db.query(Comentario).filter(Comentario.id == comentario_id).first()
        if not com:
            return None
        if not com.editado:
            com.texto_original = com.texto
            com.editado = True
        com.texto = nuevo_texto
        self.db.commit()
        self.db.refresh(com)
        return com

    def eliminar(self, comentario_id: int) -> bool:
        com = self.db.query(Comentario).filter(Comentario.id == comentario_id).first()
        if not com:
            return False
        self.db.delete(com)
        self.db.commit()
        return True

    def marcar_mencion_notificada(self, mencion_id: int) -> bool:
        m = self.db.query(MencionUsuario).filter(MencionUsuario.id == mencion_id).first()
        if not m:
            return False
        m.notificado = 1
        self.db.commit()
        return True


# ==========================================
# ADJUNTOS
# ==========================================
UPLOAD_ROOT = os.environ.get("UPLOAD_DIR", "uploads")
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".mp4", ".webm", ".mov",
}


class AdjuntoService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _extension(nombre: str) -> str:
        return os.path.splitext(nombre)[1].lower()

    def guardar_archivo(
        self, ticket: Ticket, usuario: Usuario, file_bytes: bytes,
        nombre_original: str, mime_type: Optional[str] = None,
        descripcion: Optional[str] = None,
    ) -> Tuple[Optional[Adjunto], Optional[str]]:
        """Guarda el archivo en disco y registra el adjunto. Retorna (adjunto, error)."""
        if not file_bytes:
            return None, "Archivo vacío"
        if len(file_bytes) > MAX_FILE_SIZE:
            mb = len(file_bytes) / (1024 * 1024)
            return None, f"Archivo demasiado grande: {mb:.1f}MB (máx 25MB)"
        ext = self._extension(nombre_original)
        if ext and ext not in ALLOWED_EXT:
            return None, f"Extensión no permitida: {ext}"

        # Crear estructura de carpetas
        dir_destino = os.path.join(UPLOAD_ROOT, f"ticket_{ticket.id}")
        os.makedirs(dir_destino, exist_ok=True)
        nombre_storage = f"{uuid.uuid4().hex}{ext}"
        ruta_abs = os.path.join(dir_destino, nombre_storage)
        with open(ruta_abs, "wb") as f:
            f.write(file_bytes)

        adj = Adjunto(
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            nombre_original=nombre_original,
            nombre_storage=nombre_storage,
            ruta=ruta_abs,
            mime_type=mime_type,
            tamano_bytes=len(file_bytes),
            descripcion=descripcion,
        )
        self.db.add(adj)
        self.db.commit()
        self.db.refresh(adj)
        return adj, None

    def listar_de_ticket(self, ticket_id: int) -> List[Adjunto]:
        return (
            self.db.query(Adjunto)
            .filter(Adjunto.ticket_id == ticket_id)
            .order_by(Adjunto.created_at.desc())
            .all()
        )

    def obtener(self, adjunto_id: int) -> Optional[Adjunto]:
        return self.db.query(Adjunto).filter(Adjunto.id == adjunto_id).first()

    def eliminar(self, adjunto_id: int) -> bool:
        adj = self.obtener(adjunto_id)
        if not adj:
            return False
        try:
            if os.path.exists(adj.ruta):
                os.remove(adj.ruta)
        except OSError as e:
            logger.warning(f"No se pudo borrar archivo físico {adj.ruta}: {e}")
        self.db.delete(adj)
        self.db.commit()
        return True


# ==========================================
# BÚSQUEDA Y FILTROS AVANZADOS
# ==========================================
class BusquedaService:
    """Servicio de búsqueda con filtros combinables."""

    CAMPOS_ORDEN = {
        "created_at": Ticket.created_at,
        "updated_at": Ticket.updated_at,
        "prioridad": Ticket.prioridad,
        "fecha_vencimiento_sla": Ticket.fecha_vencimiento_sla,
        "codigo": Ticket.codigo,
        "titulo": Ticket.titulo,
    }

    def __init__(self, db: Session):
        self.db = db

    def buscar(self, filtros: dict) -> Tuple[List[Ticket], int]:
        """Retorna (tickets, total)."""
        q = self.db.query(Ticket)

        # Texto libre
        if filtros.get("texto"):
            texto = f"%{filtros['texto']}%"
            q = q.filter(or_(
                Ticket.titulo.ilike(texto),
                Ticket.descripcion.ilike(texto),
                Ticket.codigo.ilike(texto),
            ))

        # Estado(s)
        if filtros.get("estados"):
            q = q.filter(Ticket.estado_id.in_(filtros["estados"]))

        # Prioridad(es)
        if filtros.get("prioridades"):
            q = q.filter(Ticket.prioridad.in_([p.upper() for p in filtros["prioridades"]]))

        # Tipo(s)
        if filtros.get("tipos"):
            q = q.filter(Ticket.tipo.in_([t.upper() for t in filtros["tipos"]]))

        # Etiquetas OR
        if filtros.get("etiquetas"):
            from app.models.etiqueta import ticket_etiquetas
            q = q.join(
                ticket_etiquetas, ticket_etiquetas.c.ticket_id == Ticket.id
            ).filter(ticket_etiquetas.c.etiqueta_id.in_(filtros["etiquetas"]))

        # Etiquetas AND
        if filtros.get("etiquetas_all"):
            for et_id in filtros["etiquetas_all"]:
                sub = (
                    self.db.query(ticket_etiquetas.c.ticket_id)
                    .filter(ticket_etiquetas.c.etiqueta_id == et_id)
                )
                q = q.filter(Ticket.id.in_(sub))

        # Asignados
        if filtros.get("asignados"):
            q = q.filter(Ticket.asignado_id.in_(filtros["asignados"]))
        if filtros.get("solo_sin_asignar"):
            q = q.filter(Ticket.asignado_id.is_(None))

        # Creadores
        if filtros.get("creadores"):
            q = q.filter(Ticket.creador_id.in_(filtros["creadores"]))

        # Catálogos
        if filtros.get("catalogos"):
            q = q.filter(Ticket.catalogo_tipo_id.in_(filtros["catalogos"]))

        # Fechas
        if filtros.get("fecha_desde"):
            q = q.filter(Ticket.created_at >= filtros["fecha_desde"])
        if filtros.get("fecha_hasta"):
            q = q.filter(Ticket.created_at <= filtros["fecha_hasta"])

        # SLA
        if filtros.get("sla_cumplido") is not None:
            q = q.filter(Ticket.sla_cumplido == filtros["sla_cumplido"])

        # Con/sin relaciones
        if filtros.get("solo_con_comentarios"):
            from app.models.comentario import Comentario
            sub = self.db.query(Comentario.ticket_id).distinct()
            q = q.filter(Ticket.id.in_(sub))
        if filtros.get("solo_con_adjuntos"):
            from app.models.adjunto import Adjunto
            sub = self.db.query(Adjunto.ticket_id).distinct()
            q = q.filter(Ticket.id.in_(sub))

        # Total antes de paginar
        total = q.count()

        # Orden
        campo = self.CAMPOS_ORDEN.get(filtros.get("ordenar_por", "created_at"), Ticket.created_at)
        if filtros.get("orden") == "asc":
            q = q.order_by(asc(campo))
        else:
            q = q.order_by(desc(campo))

        # Paginación
        limite = min(filtros.get("limite", 100), 500)
        offset = filtros.get("offset", 0)
        q = q.limit(limite).offset(offset)

        return q.all(), total

    def estadisticas(self) -> dict:
        """Resumen estadístico para dashboard."""
        base = self.db.query(Ticket)
        return {
            "total": base.count(),
            "por_estado": dict(
                self.db.query(Ticket.estado_id, func.count(Ticket.id))
                .group_by(Ticket.estado_id).all()
            ),
            "por_prioridad": dict(
                self.db.query(Ticket.prioridad, func.count(Ticket.id))
                .group_by(Ticket.prioridad).all()
            ),
            "vencidos_sla": base.filter(Ticket.sla_cumplido == 0).count(),
            "sin_asignar": base.filter(Ticket.asignado_id.is_(None)).count(),
        }


# ==========================================
# MOTOR DE AUTOMATIZACIONES (BUTLER)
# ==========================================
class MotorAutomatizacion:
    """
    Evalúa reglas cuando ocurre un evento del ciclo de vida del ticket.
    Condiciones: {campo, operador, valor}
    Acciones: ver ReglaAutomatizacion docstring
    """

    def __init__(self, db: Session):
        self.db = db

    def _getattr_nested(self, obj, path: str):
        for part in path.split("."):
            if obj is None:
                return None
            obj = getattr(obj, part, None)
        return obj

    def _evaluar_condicion(self, ticket: Ticket, cond: dict) -> bool:
        campo = cond.get("campo", "")
        op = cond.get("operador", "==")
        valor = cond.get("valor")
        actual = self._getattr_nested(ticket, campo)
        # Enums -> str
        if hasattr(actual, "value"):
            actual = actual.value
        try:
            if op == "==":
                return actual == valor
            if op == "!=":
                return actual != valor
            if op == "in":
                return actual in (valor or [])
            if op == "not_in":
                return actual not in (valor or [])
            if op == "contains":
                return valor is not None and valor in str(actual or "")
            if op == "gt":
                return actual is not None and actual > valor
            if op == "lt":
                return actual is not None and actual < valor
        except Exception as e:
            logger.warning(f"Error evaluando condición {cond}: {e}")
        return False

    def _ejecutar_accion(self, ticket: Ticket, accion: dict) -> str:
        tipo = accion.get("tipo")
        params = accion.get("parametros", {}) or {}

        try:
            if tipo == "asignar_a":
                uid = params.get("usuario_id")
                if uid:
                    ticket.asignado_id = int(uid)
                    return f"Asignado a usuario {uid}"

            elif tipo == "cambiar_estado":
                eid = params.get("estado_id")
                if eid:
                    ticket.estado_id = int(eid)
                    return f"Estado cambiado a {eid}"

            elif tipo == "agregar_etiqueta":
                eid = params.get("etiqueta_id")
                if eid:
                    et = self.db.query(Etiqueta).filter(Etiqueta.id == eid).first()
                    if et and et not in ticket.etiquetas:
                        ticket.etiquetas.append(et)
                        return f"Etiqueta {et.nombre} agregada"

            elif tipo == "quitar_etiqueta":
                eid = params.get("etiqueta_id")
                if eid:
                    et = self.db.query(Etiqueta).filter(Etiqueta.id == eid).first()
                    if et and et in ticket.etiquetas:
                        ticket.etiquetas.remove(et)
                        return f"Etiqueta {et.nombre} quitada"

            elif tipo == "crear_comentario":
                texto = params.get("texto", "🤖 [Butler] Acción automática")
                com = Comentario(
                    ticket_id=ticket.id,
                    usuario_id=params.get("usuario_id") or ticket.creador_id,
                    texto=texto,
                    es_interno=bool(params.get("es_interno", True)),
                )
                self.db.add(com)
                return "Comentario creado"

            elif tipo == "agregar_checklist":
                titulo = params.get("titulo", "Tareas")
                items = params.get("items", [])
                cl = Checklist(
                    ticket_id=ticket.id,
                    titulo=titulo,
                    orden=99,
                )
                self.db.add(cl)
                self.db.flush()
                for i, it in enumerate(items):
                    self.db.add(ChecklistItem(
                        checklist_id=cl.id,
                        texto=str(it),
                        orden=i,
                    ))
                return f"Checklist '{titulo}' creada con {len(items)} items"

            elif tipo == "marcar_prioridad":
                nueva = params.get("prioridad")
                if nueva:
                    ticket.prioridad = nueva.upper()
                    return f"Prioridad cambiada a {nueva}"

            elif tipo == "enviar_notificacion":
                # En demo solo se registra
                return f"Notificación programada: {params.get('canal', 'email')}"

        except Exception as e:
            logger.exception(f"Error ejecutando acción {tipo}: {e}")
            return f"Error: {e}"
        return f"Acción {tipo} no ejecutada (parámetros faltantes)"

    def disparar(self, disparador: str, ticket: Ticket, contexto: Optional[dict] = None) -> List[dict]:
        """Evalúa todas las reglas activas para el disparador y las ejecuta."""
        reglas = (
            self.db.query(ReglaAutomatizacion)
            .filter(
                ReglaAutomatizacion.disparador == disparador,
                ReglaAutomatizacion.activo == True,  # noqa: E712
            )
            .order_by(ReglaAutomatizacion.prioridad)
            .all()
        )
        resultados = []
        for regla in reglas:
            # Evaluar condiciones (todas deben cumplirse)
            ok = all(self._evaluar_condicion(ticket, c) for c in (regla.condiciones or []))
            ej = EjecucionAutomatizacion(
                regla_id=regla.id,
                ticket_id=ticket.id,
                contexto={"disparador": disparador, **(contexto or {})},
                exito=0,
                detalle="",
            )
            if ok:
                detalles = []
                for acc in (regla.acciones or []):
                    det = self._ejecutar_accion(ticket, acc)
                    detalles.append(det)
                ej.exito = 1
                ej.detalle = " | ".join(detalles)
            else:
                ej.detalle = "Condiciones no cumplidas"
            self.db.add(ej)
            resultados.append({
                "regla_id": regla.id,
                "regla_nombre": regla.nombre,
                "exito": ej.exito,
                "detalle": ej.detalle,
            })
        self.db.commit()
        return resultados


# Helper de instancia
def get_etiqueta_service(db: Session) -> EtiquetaService:
    return EtiquetaService(db)


def get_checklist_service(db: Session) -> ChecklistService:
    return ChecklistService(db)


def get_comentario_service(db: Session) -> ComentarioService:
    return ComentarioService(db)


def get_adjunto_service(db: Session) -> AdjuntoService:
    return AdjuntoService(db)


def get_busqueda_service(db: Session) -> BusquedaService:
    return BusquedaService(db)


def get_motor_automatizacion(db: Session) -> MotorAutomatizacion:
    return MotorAutomatizacion(db)
