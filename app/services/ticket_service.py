"""
Servicio de Tickets: contiene TODA la lógica de negocio ITSM.

Reglas de validación (cumplen con ITIL/ITSM):
1. El usuario debe existir y estar activo.
2. El usuario debe tener el rol necesario para la transición.
3. La transición entre estados debe existir en `transiciones_estado`.
4. Si la transición requiere comentario, este debe ser provisto.
5. Todo cambio se registra en historial_estados y auditoria (obligatorio).
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.estado import Estado, TransicionEstado
from app.models.ticket import Ticket, HistorialEstado, Prioridad
from app.models.usuario import Usuario, RolUsuario
from app.services.auditoria_service import registrar_auditoria


class TransicionInvalidaError(Exception):
    """Error cuando una transición de estado no está permitida por las reglas de negocio."""
    def __init__(self, mensaje: str, codigo: str = "TRANSICION_INVALIDA"):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


class PermisoInsuficienteError(Exception):
    """Error cuando el usuario no tiene rol/permisos para la transición."""
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


class TicketService:
    """Lógica de negocio del módulo de Incidencias."""

    def __init__(self, db: Session):
        self.db = db

    # ----------------------------------------------------------------------
    #  Regla #1: el destino del cambio debe estar permitido por la tabla de
    #  transiciones, y el usuario debe tener el rol adecuado.
    # ----------------------------------------------------------------------
    def _validar_transicion(
        self,
        ticket: Ticket,
        estado_destino: Estado,
        usuario: Usuario,
        comentario: Optional[str] = None,
    ) -> TransicionEstado:
        """Aplica las reglas ITSM. Devuelve la TransicionEstado válida o lanza excepción."""
        # 1. El estado destino debe ser distinto al actual
        if ticket.estado_id == estado_destino.id:
            raise TransicionInvalidaError(
                "El ticket ya se encuentra en el estado solicitado.",
                codigo="MISMO_ESTADO",
            )

        # 2. Buscar la transición válida
        transicion = (
            self.db.query(TransicionEstado)
            .filter(
                TransicionEstado.estado_origen_id == ticket.estado_id,
                TransicionEstado.estado_destino_id == estado_destino.id,
            )
            .first()
        )
        if not transicion:
            raise TransicionInvalidaError(
                f"No existe una transición válida de '{ticket.estado.nombre}' "
                f"a '{estado_destino.nombre}'.",
                codigo="TRANSICION_NO_DEFINIDA",
            )

        # 3. Validar permisos por rol
        if not self._usuario_tiene_rol(usuario, transicion.rol_requerido):
            raise PermisoInsuficienteError(
                f"El rol '{usuario.rol.value}' no puede realizar esta transición. "
                f"Se requiere: {transicion.rol_requerido}."
            )

        # 4. Si la transición exige comentario, validarlo
        if transicion.requiere_comentario and not (comentario and comentario.strip()):
            raise TransicionInvalidaError(
                f"La transición a '{estado_destino.nombre}' requiere un comentario.",
                codigo="COMENTARIO_REQUERIDO",
            )

        return transicion

    @staticmethod
    def _usuario_tiene_rol(usuario: Usuario, rol_minimo: str) -> bool:
        """Verifica si el usuario cumple con el rol mínimo requerido."""
        jerarquia = {
            "observador": 1, "solicitante": 2, "agente": 3,
            "agente_senior": 4, "administrador": 5,
        }
        nivel_usuario = jerarquia.get(usuario.rol.value, 0)
        nivel_requerido = jerarquia.get(rol_minimo, 99)
        return nivel_usuario >= nivel_requerido

    # ----------------------------------------------------------------------
    #  Cambio de estado principal (drag & drop en Kanban)
    # ----------------------------------------------------------------------
    def cambiar_estado(
        self,
        ticket_id: int,
        estado_destino_id: int,
        usuario: Usuario,
        comentario: Optional[str] = None,
        orden: Optional[int] = None,
        ip_origen: Optional[str] = None,
    ) -> Tuple[Ticket, Optional[str]]:
        """
        Cambia el estado de un ticket respetando todas las reglas ITSM.
        Inserta registro en historial_estados y en auditoria.
        Dispara tarea Celery en segundo plano (sin bloquear el request).

        Returns:
            (ticket actualizado, id de la tarea celery lanzada)
        """
        # 1. Cargar ticket
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            raise TransicionInvalidaError(
                f"Ticket {ticket_id} no existe.", codigo="TICKET_NO_ENCONTRADO"
            )

        # 2. Cargar estado destino
        estado_destino = (
            self.db.query(Estado).filter(Estado.id == estado_destino_id).first()
        )
        if not estado_destino:
            raise TransicionInvalidaError(
                f"Estado {estado_destino_id} no existe.", codigo="ESTADO_NO_ENCONTRADO"
            )

        # 3. Validar transición (lanza excepción si falla)
        transicion = self._validar_transicion(
            ticket, estado_destino, usuario, comentario
        )

        # 4. Aplicar cambio
        estado_origen = ticket.estado
        valor_anterior = {"estado_id": estado_origen.id, "estado": estado_origen.nombre}
        ticket.estado_id = estado_destino.id
        if orden is not None:
            # Asegurar que datos_catalogo sea un dict (puede ser None o string antiguo)
            datos_actuales = ticket.datos_catalogo
            if not isinstance(datos_actuales, dict):
                datos_actuales = {}
            ticket.datos_catalogo = {
                **datos_actuales,
                "orden_columna": orden,
            }

        # 5. Recalcular SLA si el estado destino tiene un SLA definido
        if estado_destino.sla_horas:
            ticket.fecha_vencimiento_sla = datetime.utcnow() + timedelta(
                hours=estado_destino.sla_horas
            )
            ticket.sla_cumplido = -1  # pendiente
        if estado_destino.es_final:
            ticket.sla_cumplido = 1 if ticket.sla_cumplido == -1 else ticket.sla_cumplido

        # 6. Insertar historial (obligatorio)
        historial = HistorialEstado(
            ticket_id=ticket.id,
            estado_origen_id=estado_origen.id,
            estado_destino_id=estado_destino.id,
            usuario_id=usuario.id,
            comentario=comentario,
            origen=ip_origen or "web",
            fecha=datetime.utcnow(),
        )
        self.db.add(historial)

        # 7. Insertar auditoría (obligatorio)
        registrar_auditoria(
            db=self.db,
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            accion="CAMBIO_ESTADO",
            valor_anterior=valor_anterior,
            valor_nuevo={"estado_id": estado_destino.id, "estado": estado_destino.nombre},
            comentario=comentario,
            ip_origen=ip_origen,
            commit=False,
        )

        # 8. Commit transacción
        self.db.commit()
        self.db.refresh(ticket)

        # 9. Disparar tarea Celery (segundo plano) - no bloquea el request
        task_id = None
        try:
            from app.tasks.sla_tasks import recalcular_sla_ticket
            from app.tasks.notification_tasks import notificar_cambio_estado
            r1 = recalcular_sla_ticket.delay(ticket.id)
            r2 = notificar_cambio_estado.delay(
                ticket.id, estado_origen.nombre, estado_destino.nombre
            )
            task_id = f"sla={r1.id};notif={r2.id}"
        except Exception:
            # Si Redis no está disponible, no fallar el flujo principal
            task_id = None

        return ticket, task_id

    # ----------------------------------------------------------------------
    #  Crear ticket
    # ----------------------------------------------------------------------
    def crear_ticket(
        self,
        datos: dict,
        usuario: Usuario,
        ip_origen: Optional[str] = None,
    ) -> Ticket:
        """Crea un nuevo ticket, asignándole el estado inicial definido."""
        # Determinar estado inicial
        estado_inicial = (
            self.db.query(Estado).filter(Estado.es_inicial == True).first()
        )
        if not estado_inicial:
            raise TransicionInvalidaError(
                "No hay un estado inicial configurado en el sistema.",
                codigo="SIN_ESTADO_INICIAL",
            )

        # Generar código único
        codigo = self._generar_codigo_ticket()

        ticket = Ticket(
            codigo=codigo,
            titulo=datos["titulo"],
            descripcion=datos["descripcion"],
            tipo=datos.get("tipo", "incidencia"),
            prioridad=datos.get("prioridad", "media"),
            estado_id=estado_inicial.id,
            creador_id=usuario.id,
            asignado_id=datos.get("asignado_id"),
            catalogo_tipo_id=datos.get("catalogo_tipo_id"),
            datos_catalogo=datos.get("datos_catalogo"),
            sla_cumplido=-1,
        )
        if estado_inicial.sla_horas:
            ticket.fecha_vencimiento_sla = datetime.utcnow() + timedelta(
                hours=estado_inicial.sla_horas
            )
        self.db.add(ticket)
        self.db.flush()

        # Historial inicial
        self.db.add(HistorialEstado(
            ticket_id=ticket.id,
            estado_origen_id=None,
            estado_destino_id=estado_inicial.id,
            usuario_id=usuario.id,
            comentario="Ticket creado",
            origen=ip_origen or "web",
            fecha=datetime.utcnow(),
        ))

        # Auditoría obligatoria
        registrar_auditoria(
            db=self.db,
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            accion="TICKET_CREADO",
            valor_nuevo={
                "titulo": ticket.titulo,
                "estado_inicial": estado_inicial.nombre,
                "prioridad": ticket.prioridad.value,
            },
            ip_origen=ip_origen,
            commit=False,
        )
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def _generar_codigo_ticket(self) -> str:
        """Genera un código legible tipo GRM-INC-000123."""
        count = self.db.query(Ticket).count() + 1
        anio = datetime.utcnow().year
        return f"GRM-INC-{anio}-{count:06d}"

    # ----------------------------------------------------------------------
    #  Listar y obtener
    # ----------------------------------------------------------------------
    def listar_kanban(self) -> List[Estado]:
        """Devuelve los estados con sus tickets listos para el tablero Kanban."""
        return (
            self.db.query(Estado)
            .order_by(Estado.orden.asc())
            .all()
        )

    def listar_tickets_por_estado(self, estado_id: int) -> List[Ticket]:
        return (
            self.db.query(Ticket)
            .filter(Ticket.estado_id == estado_id)
            .order_by(Ticket.created_at.desc())
            .all()
        )

    def obtener_ticket(self, ticket_id: int) -> Optional[Ticket]:
        return self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
