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
from typing import Optional, Tuple, List, Any, Dict

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
            rol_legible = (
                usuario.rol.value
                if hasattr(usuario.rol, "value")
                else usuario.rol
            )
            raise PermisoInsuficienteError(
                f"El rol '{rol_legible}' no puede realizar esta transición. "
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
        rol_legible = (
            usuario.rol.value
            if hasattr(usuario.rol, "value")
            else usuario.rol
        )
        nivel_usuario = jerarquia.get(rol_legible, 0)
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

        # 8.1) Notificar al responsable de la columna destino (in-app + email)
        #      Se hace ANTES de las tareas Celery para que, si la columna
        #      tiene responsable, la notificación quede persistida en la
        #      misma transacción lógica.
        try:
            from app.services.notificacion_responsable_service import (
                notificar_responsable_columna,
            )
            notificar_responsable_columna(
                self.db,
                ticket=ticket,
                estado_destino=estado_destino,
                estado_origen_nombre=estado_origen.nombre,
                actor=usuario,
            )
            self.db.commit()
        except Exception as exc:
            # No debe romper el flujo principal
            try:
                self.db.rollback()
            except Exception:
                pass
            import logging as _log
            _log.getLogger(__name__).warning(
                "notificar_responsable_columna falló (no crítico): %s", exc
            )

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

        # 10. Ejecutar reglas Butler (no afecta la transición ya confirmada)
        try:
            from app.services.butler_executor import on_ticket_cambio_estado
            on_ticket_cambio_estado(
                ticket.id, estado_origen.id, estado_destino.id, usuario
            )
        except Exception:
            # Butler no debe romper el flujo principal
            pass

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
                "prioridad": (
                    ticket.prioridad.value
                    if hasattr(ticket.prioridad, "value")
                    else ticket.prioridad
                ),
            },
            ip_origen=ip_origen,
            commit=False,
        )
        self.db.commit()
        self.db.refresh(ticket)

        # Disparar reglas Butler (no rompe el flujo si fallan)
        try:
            from app.services.butler_executor import on_ticket_creado
            on_ticket_creado(ticket.id, usuario)
        except Exception:
            pass

        return ticket

    def _generar_codigo_ticket(self) -> str:
        """Genera un código legible tipo ``INC-123`` (sin prefijo GRM ni año).

        Formato: ``INC-{N:03d}`` donde N es el siguiente correlativo basado
        en el ID máximo actual de la tabla. Esto reemplaza al antiguo
        ``GRM-INC-YYYY-NNNNNN`` y alinea con el formato compacto pedido.
        """
        from sqlalchemy import func
        max_id = self.db.query(func.max(Ticket.id)).scalar() or 0
        return f"INC-{(max_id + 1):03d}"

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

    # ----------------------------------------------------------------------
    #  Archivado / Desarchivado (soft-delete para tablero Kanban)
    # ----------------------------------------------------------------------
    def archivar(
        self,
        ticket_id: int,
        usuario: Usuario,
        ip_origen: Optional[str] = None,
        comentario: Optional[str] = None,
    ) -> Tuple[Optional[Ticket], Optional[str]]:
        """Marca un ticket como archivado (soft-delete).

        - El ticket **no** se elimina de la base de datos.
        - Desaparece de la vista Kanban por defecto.
        - Se inserta registro obligatorio en ``auditoria`` con la acción
          ``TICKET_ARCHIVADO``.
        - Solo roles ``agente_senior`` o ``administrador`` pueden archivar.
        """
        ticket = self.obtener_ticket(ticket_id)
        if not ticket:
            return None, "Ticket no encontrado"

        # Permisos: agente_senior (4) o administrador (5)
        if not self._usuario_tiene_rol(usuario, "agente_senior"):
            rol = usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
            return None, (
                f"El rol '{rol}' no puede archivar tickets. "
                "Se requiere 'agente_senior' o 'administrador'."
            )

        if ticket.archivado:
            return ticket, "El ticket ya estaba archivado"

        valor_anterior = {"archivado": False}
        ticket.archivado = True
        ticket.updated_at = datetime.utcnow()

        # Auditoría obligatoria
        registrar_auditoria(
            db=self.db,
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            accion="TICKET_ARCHIVADO",
            valor_anterior=valor_anterior,
            valor_nuevo={"archivado": True},
            comentario=comentario or "Ticket archivado desde el tablero",
            ip_origen=ip_origen,
            commit=False,
        )

        try:
            self.db.commit()
            self.db.refresh(ticket)
        except Exception as exc:
            self.db.rollback()
            return None, f"Error al archivar: {exc}"

        # Notificar a watchers en segundo plano (no bloquea)
        try:
            from app.tasks.notification_tasks import notificar_ticket_archivado
            notificar_ticket_archivado.delay(ticket.id, usuario.id)
        except Exception:
            pass

        return ticket, None

    def desarchivar(
        self,
        ticket_id: int,
        usuario: Usuario,
        ip_origen: Optional[str] = None,
        comentario: Optional[str] = None,
    ) -> Tuple[Optional[Ticket], Optional[str]]:
        """Restaura un ticket archivado para que vuelva a aparecer en el Kanban."""
        ticket = self.obtener_ticket(ticket_id)
        if not ticket:
            return None, "Ticket no encontrado"

        # Permisos: agente_senior o administrador
        if not self._usuario_tiene_rol(usuario, "agente_senior"):
            rol = usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
            return None, (
                f"El rol '{rol}' no puede desarchivar tickets. "
                "Se requiere 'agente_senior' o 'administrador'."
            )

        if not ticket.archivado:
            return ticket, "El ticket no estaba archivado"

        valor_anterior = {"archivado": True}
        ticket.archivado = False
        ticket.updated_at = datetime.utcnow()

        # Auditoría obligatoria
        registrar_auditoria(
            db=self.db,
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            accion="TICKET_DESAARCHIVADO",
            valor_anterior=valor_anterior,
            valor_nuevo={"archivado": False},
            comentario=comentario or "Ticket restaurado al tablero",
            ip_origen=ip_origen,
            commit=False,
        )

        try:
            self.db.commit()
            self.db.refresh(ticket)
        except Exception as exc:
            self.db.rollback()
            return None, f"Error al desarchivar: {exc}"

        return ticket, None

    # ----------------------------------------------------------------------
    #  Actualización de campos editables (modal de detalle)
    # ----------------------------------------------------------------------
    CAMPOS_EDITABLES = {
        "titulo", "descripcion", "prioridad", "asignado_id",
        "fecha_vencimiento", "catalogo_tipo_id", "datos_catalogo",
        # === Campos extendidos del módulo de Incidencias (LOVs) ===
        "modulo", "vista", "hu_o_caso_prueba", "nota_observacion", "resultado_pruebas",
        "ambiente", "item",
    }

    def actualizar_campos(
        self,
        ticket_id: int,
        cambios: Dict[str, Any],
        usuario: Usuario,
    ) -> Tuple[Optional[Ticket], Dict[str, Any], Dict[str, Any], Optional[str]]:
        """Actualiza múltiples campos del ticket en una sola transacción.

        Diseñado para evitar el bug donde múltiples auto-saves concurrentes
        se sobrescriben entre sí: ahora el modal envía TODOS los campos
        en un solo POST y se aplican atómicamente.

        Parameters
        ----------
        ticket_id : int
        cambios : Dict[str, Any]
            Mapa ``{nombre_campo: valor_nuevo}``. Solo se aceptan campos
            en :pyattr:`CAMPOS_EDITABLES`. Los campos cuyo valor no haya
            cambiado se omiten del log de auditoría.
        usuario : Usuario

        Returns
        -------
        ``(ticket, valores_anteriores, valores_nuevos, error)``.
        ``valores_anteriores`` y ``valores_nuevos`` son diccionarios con
        únicamente los campos que efectivamente cambiaron.
        """
        ticket = self.obtener_ticket(ticket_id)
        if not ticket:
            return None, {}, {}, "Ticket no encontrado"

        valores_anteriores: Dict[str, Any] = {}
        valores_nuevos: Dict[str, Any] = {}
        errores: List[str] = []

        # Procesar cada campo individualmente reutilizando la misma lógica
        # que ``actualizar_campo`` pero sin hacer flush/refresh hasta el
        # final (para asegurar atomicidad).
        for campo, valor in cambios.items():
            if campo not in self.CAMPOS_EDITABLES:
                errores.append(f"Campo '{campo}' no editable")
                continue

            # Calcular valor anterior legible
            if campo == "prioridad":
                anterior_raw = ticket.prioridad.value if hasattr(ticket.prioridad, "value") else ticket.prioridad
            elif campo == "fecha_vencimiento":
                anterior_raw = ticket.fecha_vencimiento_sla.isoformat() if ticket.fecha_vencimiento_sla else None
            elif campo == "asignado_id":
                anterior_raw = ticket.asignado_id
            else:
                anterior_raw = getattr(ticket, campo, None)

            # Calcular el nuevo valor
            try:
                if campo == "prioridad":
                    from app.models.ticket import Prioridad
                    nuevo_valor_enum = Prioridad(valor)
                    # Detectar cambio real
                    nuevo_legible = nuevo_valor_enum.value
                    if str(anterior_raw) == str(nuevo_legible):
                        continue  # sin cambio, no auditar
                    ticket.prioridad = nuevo_valor_enum
                elif campo == "fecha_vencimiento":
                    if valor in (None, "", "null"):
                        if anterior_raw is None:
                            continue  # ya estaba vacío
                        ticket.fecha_vencimiento_sla = None
                        nuevo_legible = None
                    else:
                        try:
                            v = str(valor).strip()
                            if "T" in v or (" " in v and ":" in v):
                                nuevo_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                            else:
                                nuevo_dt = datetime.strptime(v, "%Y-%m-%d")
                                nuevo_dt = nuevo_dt.replace(hour=23, minute=59)
                            if nuevo_dt.tzinfo is not None:
                                nuevo_dt = nuevo_dt.astimezone(tz=None).replace(tzinfo=None)
                            if ticket.fecha_vencimiento_sla and ticket.fecha_vencimiento_sla == nuevo_dt:
                                continue  # sin cambio
                            ticket.fecha_vencimiento_sla = nuevo_dt
                            nuevo_legible = nuevo_dt.isoformat()
                        except (ValueError, TypeError):
                            errores.append(f"Fecha inválida: {valor}")
                            continue
                elif campo == "asignado_id":
                    if valor in (None, "", "null", 0, "0"):
                        nuevo_legible = None
                        if anterior_raw is None:
                            continue  # ya estaba sin asignar
                        ticket.asignado_id = None
                    else:
                        try:
                            nuevo_id = int(valor)
                        except (ValueError, TypeError):
                            errores.append(f"asignado_id inválido: {valor}")
                            continue
                        if nuevo_id == anterior_raw:
                            continue  # sin cambio
                        ticket.asignado_id = nuevo_id
                        nuevo_legible = nuevo_id
                else:
                    # Campos simples (titulo, descripcion)
                    nuevo_legible = valor
                    if str(anterior_raw or "") == str(nuevo_legible or ""):
                        continue  # sin cambio
                    setattr(ticket, campo, valor)
            except Exception as exc:
                errores.append(f"Error al actualizar '{campo}': {exc}")
                continue

            valores_anteriores[campo] = anterior_raw
            valores_nuevos[campo] = nuevo_legible

        if errores:
            # Si hubo errores, NO commit: revertir todos los cambios
            self.db.rollback()
            return ticket, {}, {}, "; ".join(errores)

        if not valores_nuevos:
            # Nada que cambiar (todos los campos ya tenían el valor enviado)
            return ticket, {}, {}, None

        ticket.updated_at = datetime.utcnow()
        try:
            self.db.commit()
            self.db.refresh(ticket)
        except Exception as exc:
            self.db.rollback()
            return None, {}, {}, f"Error al guardar cambios: {exc}"

        return ticket, valores_anteriores, valores_nuevos, None

    def actualizar_campo(
        self,
        ticket_id: int,
        campo: str,
        valor: Any,
        usuario: Usuario,
    ) -> Tuple[Optional[Ticket], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
        """Actualiza un único campo del ticket.

        Devuelve ``(ticket, valor_anterior, valor_nuevo, error)``.
        Solo se permiten campos en :pyattr:`CAMPOS_EDITABLES`.
        """
        if campo not in self.CAMPOS_EDITABLES:
            return None, None, None, f"Campo '{campo}' no editable"
        ticket = self.obtener_ticket(ticket_id)
        if not ticket:
            return None, None, None, "Ticket no encontrado"

        # Calcular valor anterior legible
        if campo == "prioridad":
            anterior_raw = ticket.prioridad.value if hasattr(ticket.prioridad, "value") else ticket.prioridad
        elif campo == "fecha_vencimiento":
            anterior_raw = ticket.fecha_vencimiento_sla.isoformat() if ticket.fecha_vencimiento_sla else None
        elif campo == "asignado_id":
            anterior_raw = ticket.asignado_id
        else:
            anterior_raw = getattr(ticket, campo, None)
        valor_anterior = {campo: anterior_raw} if anterior_raw is not None else None

        try:
            if campo == "prioridad":
                from app.models.ticket import Prioridad
                nuevo_valor_enum = Prioridad(valor)
                ticket.prioridad = nuevo_valor_enum
                nuevo_legible = nuevo_valor_enum.value
            elif campo == "fecha_vencimiento":
                if valor in (None, "", "null"):
                    ticket.fecha_vencimiento_sla = None
                    nuevo_legible = None
                else:
                    try:
                        # Aceptar 'YYYY-MM-DD' o ISO con hora
                        v = str(valor).strip()
                        if "T" in v or " " in v and ":" in v:
                            nuevo_dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                        else:
                            nuevo_dt = datetime.strptime(v, "%Y-%m-%d")
                            nuevo_dt = nuevo_dt.replace(hour=23, minute=59)
                        # Convertir a naive UTC si tiene tzinfo
                        if nuevo_dt.tzinfo is not None:
                            nuevo_dt = nuevo_dt.astimezone(tz=None).replace(tzinfo=None)
                        ticket.fecha_vencimiento_sla = nuevo_dt
                        nuevo_legible = nuevo_dt.isoformat()
                    except (ValueError, TypeError) as exc:
                        return ticket, None, None, f"Fecha inválida: {valor}"
            elif campo == "asignado_id":
                if valor in (None, "", "null", 0, "0"):
                    ticket.asignado_id = None
                    nuevo_legible = None
                else:
                    try:
                        ticket.asignado_id = int(valor)
                    except (ValueError, TypeError):
                        return ticket, None, None, f"asignado_id inválido: {valor}"
                    nuevo_legible = ticket.asignado_id
            else:
                # Campos simples (titulo, descripcion)
                setattr(ticket, campo, valor)
                nuevo_legible = valor
        except Exception as exc:
            return ticket, None, None, f"Error al actualizar: {exc}"

        ticket.updated_at = datetime.utcnow()
        self.db.flush()
        self.db.refresh(ticket)
        valor_nuevo = {campo: nuevo_legible} if nuevo_legible is not None else {campo: None}
        return ticket, valor_anterior, valor_nuevo, None
