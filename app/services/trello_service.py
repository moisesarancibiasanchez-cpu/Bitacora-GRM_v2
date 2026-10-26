"""
Servicios para las nuevas funcionalidades estilo Trello:
- MarkdownParser: convierte Markdown a HTML seguro
- NotificacionService: gestiona la cola de notificaciones
- WatchService: alta/baja de suscripciones
- ReaccionService: agregar/quitar reacciones emoji
- CampoPersonalizadoService: CRUD de campos y valores
- VistasService: renderiza datos para vistas Tabla/Timeline/Calendario
"""
import re
import html
import secrets
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc

from app.models.usuario import Usuario
from app.models.espacio import Espacio, Tablero, PermisoTablero
from app.models.watch import Watch, Reaccion, Notificacion
from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
from app.models.ticket import Ticket
from app.models.comentario import Comentario, MencionUsuario


# ==========================================
# MARKDOWN PARSER (mínimo seguro, sin dependencias externas)
# ==========================================
class MarkdownParser:
    """
    Parser de Markdown a HTML limitado y seguro.
    Soporta: negritas (**texto**), itálicas (*texto*), código (`código`),
    enlaces [texto](url), listas (- item), headings (# a ######), blockquotes (>).
    Escapa HTML para evitar XSS.
    """

    @staticmethod
    def to_html(texto: str) -> str:
        if not texto:
            return ""
        # 1) Escapar HTML para evitar XSS
        texto = html.escape(texto)
        # 2) Code blocks ```...```
        texto = re.sub(
            r"```([\s\S]*?)```",
            lambda m: f"<pre class=\"md-codeblock\"><code>{m.group(1)}</code></pre>",
            texto
        )
        # 3) Inline code `...`
        texto = re.sub(r"`([^`\n]+)`", r"<code class=\"md-inline\">\1</code>", texto)
        # 4) Negritas **...**
        texto = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", texto)
        # 5) Itálicas *...*
        texto = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", texto)
        # 6) Enlaces [texto](url) - escapamos javascript: y data:
        def safe_link(m):
            label, url = m.group(1), m.group(2)
            if re.match(r"^(javascript|data|vbscript):", url, re.IGNORECASE):
                url = "#"
            return f"<a href=\"{url}\" class=\"md-link\" rel=\"noopener\" target=\"_blank\">{label}</a>"
        texto = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", safe_link, texto)
        # 7) Headings (# a ######)
        for i in range(6, 0, -1):
            texto = re.sub(
                rf"^{'#' * i}\s+(.+)$",
                rf"<h{i} class=\"md-h{i}\">\1</h{i}>",
                texto, flags=re.MULTILINE
            )
        # 8) Blockquotes > texto
        texto = re.sub(
            r"^&gt;\s+(.+)$",
            r"<blockquote class=\"md-quote\">\1</blockquote>",
            texto, flags=re.MULTILINE
        )
        # 9) Listas - item
        texto = re.sub(
            r"^- (.+)$",
            r"<li class=\"md-li\">\1</li>",
            texto, flags=re.MULTILINE
        )
        # Envolver secuencias de <li> en <ul>
        texto = re.sub(
            r"((?:<li class=\"md-li\">[^\n]+</li>\n?)+)",
            r"<ul class=\"md-ul\">\1</ul>",
            texto
        )
        # 10) Saltos de línea
        texto = texto.replace("\n\n", "</p><p class=\"md-p\">").replace("\n", "<br>")
        texto = f"<p class=\"md-p\">{texto}</p>"
        return texto

    @staticmethod
    def extraer_menciones(texto: str) -> List[str]:
        """Extrae usernames mencionados con @ del texto."""
        patron = r'@(\w+)'
        return list(set(re.findall(patron, texto or "")))


# ==========================================
# WATCH SERVICE
# ==========================================
class WatchService:
    """Gestiona suscripciones de usuarios a objetos del sistema."""

    def __init__(self, db: Session):
        self.db = db

    def suscribir(self, usuario_id: int, tipo_objeto: str, objeto_id: int,
                  canal: str = "all") -> Watch:
        """Suscribe un usuario a un objeto. Si ya existe, lo reactiva."""
        if tipo_objeto not in ("ticket", "tablero", "espacio", "lista"):
            raise ValueError(f"Tipo de objeto no soportado: {tipo_objeto}")
        watch = (
            self.db.query(Watch)
            .filter(and_(
                Watch.usuario_id == usuario_id,
                Watch.tipo_objeto == tipo_objeto,
                Watch.objeto_id == objeto_id,
            ))
            .first()
        )
        if watch:
            watch.activo = True
            watch.canal = canal
        else:
            watch = Watch(
                usuario_id=usuario_id, tipo_objeto=tipo_objeto,
                objeto_id=objeto_id, canal=canal, activo=True,
            )
            self.db.add(watch)
        self.db.commit()
        self.db.refresh(watch)
        return watch

    def desuscribir(self, usuario_id: int, tipo_objeto: str, objeto_id: int) -> bool:
        """Desactiva la suscripción (no la elimina, mantiene historial)."""
        watch = (
            self.db.query(Watch)
            .filter(and_(
                Watch.usuario_id == usuario_id,
                Watch.tipo_objeto == tipo_objeto,
                Watch.objeto_id == objeto_id,
            ))
            .first()
        )
        if not watch:
            return False
        watch.activo = False
        self.db.commit()
        return True

    def toggle(self, usuario_id: int, tipo_objeto: str, objeto_id: int, canal: str = "in_app") -> bool:
        """Alterna suscripción. Devuelve True si ahora está suscrito."""
        watch = (
            self.db.query(Watch)
            .filter(and_(
                Watch.usuario_id == usuario_id,
                Watch.tipo_objeto == tipo_objeto,
                Watch.objeto_id == objeto_id,
            ))
            .first()
        )
        if watch:
            watch.activo = not watch.activo
            if canal:
                watch.canal = canal
            self.db.commit()
            return watch.activo
        else:
            self.suscribir(usuario_id, tipo_objeto, objeto_id, canal)
            return True

    def esta_suscrito(self, usuario_id: int, tipo_objeto: str, objeto_id: int) -> bool:
        watch = (
            self.db.query(Watch)
            .filter(and_(
                Watch.usuario_id == usuario_id,
                Watch.tipo_objeto == tipo_objeto,
                Watch.objeto_id == objeto_id,
                Watch.activo == True,  # noqa
            ))
            .first()
        )
        return watch is not None

    def listar_suscripciones(self, usuario_id: int) -> List[Watch]:
        return (
            self.db.query(Watch)
            .filter(Watch.usuario_id == usuario_id, Watch.activo == True)  # noqa
            .order_by(Watch.created_at.desc())
            .all()
        )

    def obtener_suscriptores(self, tipo_objeto: str, objeto_id: int) -> List[int]:
        """Devuelve IDs de usuarios suscritos a un objeto."""
        watches = (
            self.db.query(Watch)
            .filter(and_(
                Watch.tipo_objeto == tipo_objeto,
                Watch.objeto_id == objeto_id,
                Watch.activo == True,  # noqa
            ))
            .all()
        )
        return [w.usuario_id for w in watches]


# ==========================================
# REACCION SERVICE
# ==========================================
class ReaccionService:
    """Gestiona reacciones emoji sobre comentarios o tickets."""

    EMOJIS_PERMITIDOS = {
        "👍", "👎", "❤️", "🎉", "😄", "🙌", "👏", "🚀", "👀", "🤔",
        "🔥", "⭐", "✅", "❌", "⚠️", "🛑", "💯", "🎯", "📌", "🔔",
    }

    def __init__(self, db: Session):
        self.db = db

    def toggle(self, usuario_id: int, tipo_objeto: str, objeto_id: int, emoji: str) -> dict:
        """Si el usuario ya reaccionó con este emoji, lo quita. Si no, lo agrega."""
        if emoji not in self.EMOJIS_PERMITIDOS:
            raise ValueError(f"Emoji no permitido: {emoji}")
        if tipo_objeto not in ("comentario", "ticket"):
            raise ValueError(f"Tipo no soportado: {tipo_objeto}")

        reaccion = (
            self.db.query(Reaccion)
            .filter(and_(
                Reaccion.usuario_id == usuario_id,
                Reaccion.tipo_objeto == tipo_objeto,
                Reaccion.objeto_id == objeto_id,
                Reaccion.emoji == emoji,
            ))
            .first()
        )
        if reaccion:
            self.db.delete(reaccion)
            accion = "removida"
        else:
            reaccion = Reaccion(
                usuario_id=usuario_id, tipo_objeto=tipo_objeto,
                objeto_id=objeto_id, emoji=emoji,
            )
            self.db.add(reaccion)
            accion = "agregada"
        self.db.commit()
        return {
            "accion": accion,
            "emoji": emoji,
            "total": self.contar_por_emoji(tipo_objeto, objeto_id, emoji),
        }

    def contar_por_emoji(self, tipo_objeto: str, objeto_id: int, emoji: str) -> int:
        return (
            self.db.query(func.count(Reaccion.id))
            .filter(and_(
                Reaccion.tipo_objeto == tipo_objeto,
                Reaccion.objeto_id == objeto_id,
                Reaccion.emoji == emoji,
            ))
            .scalar() or 0
        )

    def agrupar_por_emoji(self, tipo_objeto: str, objeto_id: int,
                          usuario_actual_id: Optional[int] = None) -> List[dict]:
        """Agrupa las reacciones por emoji con conteo y lista de usuarios."""
        reacciones = (
            self.db.query(Reaccion)
            .filter(and_(
                Reaccion.tipo_objeto == tipo_objeto,
                Reaccion.objeto_id == objeto_id,
            ))
            .all()
        )
        grupos = defaultdict(list)
        for r in reacciones:
            grupos[r.emoji].append(r)
        resultado = []
        for emoji, rs in grupos.items():
            resultado.append({
                "emoji": emoji,
                "total": len(rs),
                "usuarios": [r.usuario_id for r in rs],
                "yo_reaccione": any(r.usuario_id == usuario_actual_id for r in rs),
            })
        # Ordenar por total desc
        resultado.sort(key=lambda x: -x["total"])
        return resultado


# ==========================================
# NOTIFICACION SERVICE
# ==========================================
class NotificacionService:
    """Gestiona la cola de notificaciones de un usuario."""

    def __init__(self, db: Session):
        self.db = db

    def crear(self, usuario_id: int, tipo: str, titulo: str, mensaje: str,
              ticket_id: Optional[int] = None, url: Optional[str] = None,
              origen_usuario_id: Optional[int] = None) -> Notificacion:
        """Crea una notificación para un usuario."""
        notif = Notificacion(
            usuario_id=usuario_id, tipo=tipo, titulo=titulo,
            mensaje=mensaje, ticket_id=ticket_id, url=url,
            origen_usuario_id=origen_usuario_id,
        )
        self.db.add(notif)
        self.db.commit()
        self.db.refresh(notif)
        return notif

    def crear_lote(self, usuarios_ids: List[int], tipo: str, titulo: str,
                   mensaje: str, ticket_id: Optional[int] = None,
                   url: Optional[str] = None,
                   origen_usuario_id: Optional[int] = None) -> int:
        """Crea notificaciones para múltiples usuarios."""
        count = 0
        for uid in set(usuarios_ids):
            if uid == origen_usuario_id:
                continue  # No notificar al autor
            self.crear(
                usuario_id=uid, tipo=tipo, titulo=titulo, mensaje=mensaje,
                ticket_id=ticket_id, url=url, origen_usuario_id=origen_usuario_id,
            )
            count += 1
        return count

    def marcar_leida(self, notificacion_id: int, usuario_id: int) -> bool:
        notif = (
            self.db.query(Notificacion)
            .filter(Notificacion.id == notificacion_id, Notificacion.usuario_id == usuario_id)
            .first()
        )
        if not notif:
            return False
        notif.leida = True
        notif.leida_en = datetime.utcnow().isoformat()
        self.db.commit()
        return True

    def marcar_todas_leidas(self, usuario_id: int) -> int:
        count = (
            self.db.query(Notificacion)
            .filter(Notificacion.usuario_id == usuario_id, Notificacion.leida == False)  # noqa
            .update({"leida": True, "leida_en": datetime.utcnow().isoformat()})
        )
        self.db.commit()
        return count

    def listar(self, usuario_id: int, solo_no_leidas: bool = False,
               limite: int = 50) -> List[Notificacion]:
        q = self.db.query(Notificacion).filter(Notificacion.usuario_id == usuario_id)
        if solo_no_leidas:
            q = q.filter(Notificacion.leida == False)  # noqa
        return q.order_by(desc(Notificacion.created_at)).limit(limite).all()

    def contar_no_leidas(self, usuario_id: int) -> int:
        return (
            self.db.query(func.count(Notificacion.id))
            .filter(Notificacion.usuario_id == usuario_id, Notificacion.leida == False)  # noqa
            .scalar() or 0
        )

    def notificar_mencion(self, comentario: Comentario, mencionados: List[str]) -> int:
        """Crea notificaciones para usuarios mencionados en un comentario."""
        if not mencionados:
            return 0
        usuarios = (
            self.db.query(Usuario)
            .filter(Usuario.username.in_(mencionados))
            .all()
        )
        titulo = f"@{comentario.usuario.username} te mencionó"
        mensaje = (
            f"En el ticket del comentario: \"{comentario.texto[:100]}\""
            if len(comentario.texto) > 100 else
            f"Comentario: \"{comentario.texto}\""
        )
        return self.crear_lote(
            usuarios_ids=[u.id for u in usuarios],
            tipo="mencion",
            titulo=titulo,
            mensaje=mensaje,
            ticket_id=comentario.ticket_id,
            url=f"/tickets/{comentario.ticket_id}#comentario-{comentario.id}",
            origen_usuario_id=comentario.usuario_id,
        )

    def notificar_watchers(self, tipo_objeto: str, objeto_id: int, evento: str,
                           titulo: str, mensaje: str,
                           ticket_id: Optional[int] = None,
                           origen_usuario_id: Optional[int] = None) -> int:
        """Notifica a todos los watchers de un objeto."""
        watch_svc = WatchService(self.db)
        suscriptores = watch_svc.obtener_suscriptores(tipo_objeto, objeto_id)
        if tipo_objeto == "ticket" and ticket_id is None:
            ticket_id = objeto_id
        return self.crear_lote(
            usuarios_ids=suscriptores,
            tipo=f"watch_{evento}",
            titulo=titulo,
            mensaje=mensaje,
            ticket_id=ticket_id,
            url=f"/tickets/{ticket_id}" if ticket_id else None,
            origen_usuario_id=origen_usuario_id,
        )


# ==========================================
# CAMPO PERSONALIZADO SERVICE
# ==========================================
class CampoPersonalizadoService:
    """Gestiona definición de campos y sus valores en tickets."""

    TIPOS_VALIDOS = {"texto", "numero", "dropdown", "checkbox", "fecha", "url"}

    def __init__(self, db: Session):
        self.db = db

    def crear_campo(self, tablero_id: int, nombre: str, tipo: str,
                    configuracion: Optional[dict] = None,
                    requerido: bool = False, posicion: int = 0,
                    color: str = "#6366f1") -> CampoPersonalizado:
        if tipo not in self.TIPOS_VALIDOS:
            raise ValueError(f"Tipo no válido. Use uno de: {self.TIPOS_VALIDOS}")
        campo = CampoPersonalizado(
            tablero_id=tablero_id, nombre=nombre, tipo=tipo,
            configuracion=configuracion, requerido=requerido,
            posicion=posicion, color=color,
        )
        self.db.add(campo)
        self.db.commit()
        self.db.refresh(campo)
        return campo

    def listar_de_tablero(self, tablero_id: int) -> List[CampoPersonalizado]:
        return (
            self.db.query(CampoPersonalizado)
            .filter(CampoPersonalizado.tablero_id == tablero_id, CampoPersonalizado.activo == True)  # noqa
            .order_by(CampoPersonalizado.posicion)
            .all()
        )

    def listar_todos(self) -> List[CampoPersonalizado]:
        return (
            self.db.query(CampoPersonalizado)
            .filter(CampoPersonalizado.activo == True)  # noqa
            .order_by(CampoPersonalizado.tablero_id, CampoPersonalizado.posicion)
            .all()
        )

    def asignar_valor(self, campo_id: int, ticket_id: int,
                      valor_texto: Optional[str] = None,
                      valor_numero: Optional[float] = None,
                      valor_booleano: Optional[bool] = None,
                      valor_fecha: Optional[datetime] = None) -> ValorCampo:
        """Crea o actualiza el valor de un campo para un ticket."""
        valor = (
            self.db.query(ValorCampo)
            .filter(and_(ValorCampo.campo_id == campo_id, ValorCampo.ticket_id == ticket_id))
            .first()
        )
        if not valor:
            valor = ValorCampo(campo_id=campo_id, ticket_id=ticket_id)
            self.db.add(valor)
        valor.valor_texto = valor_texto
        valor.valor_numero = valor_numero
        valor.valor_booleano = valor_booleano
        valor.valor_fecha = valor_fecha
        self.db.commit()
        self.db.refresh(valor)
        return valor

    def obtener_valores_ticket(self, ticket_id: int) -> Dict[int, Any]:
        """Devuelve un dict {campo_id: valor} para todos los campos del ticket."""
        valores = (
            self.db.query(ValorCampo)
            .filter(ValorCampo.ticket_id == ticket_id)
            .all()
        )
        return {v.campo_id: v.valor for v in valores}

    def obtener_campos_con_valores(self, ticket_id: int) -> List[dict]:
        """Devuelve campos con sus valores ya formateados para UI."""
        ticket = self.db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket or not ticket.tablero_id:
            return []
        campos = self.listar_de_tablero(ticket.tablero_id)
        valores = {v.campo_id: v for v in (
            self.db.query(ValorCampo)
            .filter(ValorCampo.ticket_id == ticket_id)
            .all()
        )}
        resultado = []
        for campo in campos:
            valor = valores.get(campo.id)
            resultado.append({
                "id": campo.id,
                "nombre": campo.nombre,
                "tipo": campo.tipo,
                "color": campo.color,
                "requerido": campo.requerido,
                "configuracion": campo.configuracion,
                "valor_texto": valor.valor_texto if valor else None,
                "valor_numero": valor.valor_numero if valor else None,
                "valor_booleano": valor.valor_booleano if valor else None,
                "valor_fecha": valor.valor_fecha.isoformat() if (valor and valor.valor_fecha) else None,
                "valor": valor.valor if valor else None,
            })
        return resultado

    def eliminar_campo(self, campo_id: int) -> bool:
        campo = self.db.query(CampoPersonalizado).filter(CampoPersonalizado.id == campo_id).first()
        if not campo:
            return False
        campo.activo = False
        self.db.commit()
        return True


# ==========================================
# VISTAS SERVICE (Tabla / Timeline / Calendario)
# ==========================================
class VistasService:
    """Prepara datos para las vistas multidimensionales."""

    def __init__(self, db: Session):
        self.db = db

    def vista_tabla(self, tablero_id: Optional[int] = None,
                    filtros: Optional[dict] = None) -> List[dict]:
        """Genera filas para vista de tabla (tipo Excel)."""
        q = self.db.query(Ticket).filter(Ticket.archivado == False)  # noqa
        if tablero_id:
            q = q.filter(Ticket.tablero_id == tablero_id)
        if filtros:
            if filtros.get("estados_ids"):
                q = q.filter(Ticket.estado_id.in_(filtros["estados_ids"]))
            if filtros.get("asignados_ids"):
                q = q.filter(Ticket.asignado_id.in_(filtros["asignados_ids"]))
            if filtros.get("etiquetas_ids"):
                from app.models.etiqueta import ticket_etiquetas
                q = q.join(ticket_etiquetas, ticket_etiquetas.c.ticket_id == Ticket.id)
                q = q.filter(ticket_etiquetas.c.etiqueta_id.in_(filtros["etiquetas_ids"]))
        q = q.order_by(Ticket.estado_id, Ticket.posicion, Ticket.created_at.desc())
        tickets = q.all()

        campo_svc = CampoPersonalizadoService(self.db)
        filas = []
        for t in tickets:
            campos = campo_svc.obtener_campos_con_valores(t.id) if t.tablero_id else []
            campos_dict = {f["nombre"]: f["valor"] for f in campos}
            filas.append({
                "id": t.id,
                "codigo": t.codigo,
                "titulo": t.titulo,
                "prioridad": t.prioridad.value if hasattr(t.prioridad, "value") else str(t.prioridad),
                "estado": t.estado.nombre if t.estado else "—",
                "estado_color": t.estado.color if t.estado else "#94a3b8",
                "asignado": t.asignado.nombre_completo if t.asignado else None,
                "asignado_id": t.asignado_id,
                "fecha_vencimiento": t.fecha_vencimiento_sla.isoformat() if t.fecha_vencimiento_sla else None,
                "fecha_inicio": t.fecha_inicio.isoformat() if t.fecha_inicio else None,
                "fecha_completado": t.fecha_completado.isoformat() if t.fecha_completado else None,
                "etiquetas": [
                    {"id": e.id, "nombre": e.nombre, "color": e.color}
                    for e in (t.etiquetas or [])
                ],
                "progreso": t.progreso_checklists.get("porcentaje", 0),
                "miembros": [
                    {"id": u.id, "nombre": u.nombre_completo, "username": u.username}
                    for u in (t.miembros or [])
                ],
                "sla_cumplido": t.sla_cumplido,
                "campos_personalizados": campos_dict,
                "creador": t.creador.nombre_completo if t.creador else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return filas

    def vista_calendario(self, tablero_id: Optional[int] = None,
                         mes: Optional[int] = None,
                         anio: Optional[int] = None) -> dict:
        """Genera eventos para vista calendario (por mes)."""
        from calendar import monthrange
        hoy = datetime.utcnow()
        m = mes or hoy.month
        a = anio or hoy.year
        _, dias_mes = monthrange(a, m)
        inicio = datetime(a, m, 1)
        fin = datetime(a, m, dias_mes, 23, 59, 59)

        q = self.db.query(Ticket).filter(Ticket.archivado == False)  # noqa
        if tablero_id:
            q = q.filter(Ticket.tablero_id == tablero_id)
        # Tickets cuya fecha_vencimiento_sla cae en este mes
        q = q.filter(or_(
            and_(Ticket.fecha_vencimiento_sla >= inicio, Ticket.fecha_vencimiento_sla <= fin),
            and_(Ticket.fecha_inicio >= inicio, Ticket.fecha_inicio <= fin),
            and_(Ticket.fecha_completado >= inicio, Ticket.fecha_completado <= fin),
        ))
        tickets = q.all()
        eventos = []
        for t in tickets:
            # Evento principal: fecha de vencimiento
            if t.fecha_vencimiento_sla and inicio <= t.fecha_vencimiento_sla <= fin:
                eventos.append({
                    "ticket_id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                    "fecha": t.fecha_vencimiento_sla.date().isoformat(),
                    "tipo": "vencimiento",
                    "estado": t.estado.nombre if t.estado else None,
                    "color": t.estado.color if t.estado else "#94a3b8",
                    "prioridad": t.prioridad.value if hasattr(t.prioridad, "value") else str(t.prioridad),
                })
        return {
            "mes": m, "anio": a, "total_eventos": len(eventos),
            "eventos": eventos,
        }

    def vista_timeline(self, tablero_id: Optional[int] = None,
                       fecha_desde: Optional[datetime] = None,
                       fecha_hasta: Optional[datetime] = None) -> List[dict]:
        """Genera datos para vista Timeline (Gantt)."""
        q = self.db.query(Ticket).filter(Ticket.archivado == False)  # noqa
        if tablero_id:
            q = q.filter(Ticket.tablero_id == tablero_id)
        if fecha_desde:
            q = q.filter(or_(
                Ticket.fecha_vencimiento_sla >= fecha_desde,
                Ticket.fecha_inicio >= fecha_desde,
            ))
        if fecha_hasta:
            q = q.filter(or_(
                Ticket.fecha_vencimiento_sla <= fecha_hasta,
                Ticket.fecha_inicio <= fecha_hasta,
            ))
        q = q.order_by(Ticket.fecha_inicio.asc().nulls_last(), Ticket.created_at.asc())
        tickets = q.all()
        items = []
        for t in tickets:
            if not t.fecha_inicio and not t.fecha_vencimiento_sla:
                continue
            items.append({
                "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                "fecha_inicio": t.fecha_inicio.isoformat() if t.fecha_inicio else None,
                "fecha_fin": t.fecha_vencimiento_sla.isoformat() if t.fecha_vencimiento_sla else None,
                "fecha_completado": t.fecha_completado.isoformat() if t.fecha_completado else None,
                "estado": t.estado.nombre if t.estado else None,
                "estado_color": t.estado.color if t.estado else "#94a3b8",
                "progreso": t.progreso_checklists.get("porcentaje", 0),
                "asignado": t.asignado.nombre_completo if t.asignado else None,
                "prioridad": t.prioridad.value if hasattr(t.prioridad, "value") else str(t.prioridad),
            })
        return items


# ==========================================
# ESPACIO / TABLERO SERVICE
# ==========================================
class EspacioService:
    """Gestiona espacios de trabajo y sus tableros."""

    def __init__(self, db: Session):
        self.db = db

    def crear(self, datos: dict, propietario_id: int) -> Espacio:
        espacio = Espacio(propietario_id=propietario_id, **datos)
        self.db.add(espacio)
        self.db.flush()
        # El propietario es automáticamente miembro
        espacio.miembros.append(
            self.db.query(Usuario).filter(Usuario.id == propietario_id).first()
        )
        self.db.commit()
        self.db.refresh(espacio)
        return espacio

    def listar(self, usuario_id: int, incluir_publicos: bool = True) -> List[Espacio]:
        """Lista espacios accesibles para un usuario."""
        from app.models.espacio import espacio_miembros
        q = self.db.query(Espacio).join(
            espacio_miembros, espacio_miembros.c.espacio_id == Espacio.id
        ).filter(espacio_miembros.c.usuario_id == usuario_id)
        if incluir_publicos:
            # También los públicos
            publicos = self.db.query(Espacio).filter(Espacio.es_publico == True).all()  # noqa
            ids = {e.id for e in q.all()}
            ids.update(e.id for e in publicos)
            return self.db.query(Espacio).filter(Espacio.id.in_(ids)).all()
        return q.all()

    def agregar_miembro(self, espacio_id: int, usuario_id: int,
                        rol_espacio: str = "miembro") -> bool:
        espacio = self.db.query(Espacio).filter(Espacio.id == espacio_id).first()
        usuario = self.db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not espacio or not usuario:
            return False
        if usuario not in espacio.miembros:
            espacio.miembros.append(usuario)
            self.db.commit()
        return True

    def quitar_miembro(self, espacio_id: int, usuario_id: int) -> bool:
        espacio = self.db.query(Espacio).filter(Espacio.id == espacio_id).first()
        usuario = self.db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not espacio or not usuario:
            return False
        if usuario in espacio.miembros:
            espacio.miembros.remove(usuario)
            self.db.commit()
        return True

    def generar_slug(self, nombre: str) -> str:
        """Genera un slug URL-friendly."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", nombre.lower()).strip("-")
        slug = slug[:40] if slug else "espacio"
        # Asegurar unicidad
        base = slug
        i = 1
        while self.db.query(Espacio).filter(Espacio.nombre == slug).first():
            slug = f"{base}-{i}"
            i += 1
        return slug


class TableroService:
    """Gestiona tableros Kanban."""

    def __init__(self, db: Session):
        self.db = db

    def crear(self, datos: dict, propietario_id: int) -> Tablero:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", datos["nombre"].lower()).strip("-")[:50]
        # Unicidad de slug_publico
        if slug:
            base_slug = slug
            i = 1
            while self.db.query(Tablero).filter(Tablero.slug_publico == slug).first():
                slug = f"{base_slug}-{i}"
                i += 1
        tablero = Tablero(
            propietario_id=propietario_id,
            slug_publico=slug if datos.get("visibilidad") == "publico" else None,
            **datos,
        )
        self.db.add(tablero)
        self.db.commit()
        self.db.refresh(tablero)
        return tablero

    def archivar(self, tablero_id: int) -> bool:
        tablero = self.db.query(Tablero).filter(Tablero.id == tablero_id).first()
        if not tablero:
            return False
        tablero.archivado = True
        self.db.commit()
        return True

    def restaurar(self, tablero_id: int) -> bool:
        tablero = self.db.query(Tablero).filter(Tablero.id == tablero_id).first()
        if not tablero:
            return False
        tablero.archivado = False
        self.db.commit()
        return True

    def listar_por_espacio(self, espacio_id: int) -> List[Tablero]:
        return (
            self.db.query(Tablero)
            .filter(Tablero.espacio_id == espacio_id, Tablero.archivado == False)  # noqa
            .order_by(Tablero.nombre)
            .all()
        )
