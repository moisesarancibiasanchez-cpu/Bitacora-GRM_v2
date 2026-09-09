"""
Modelos para Botones de Tarjeta/Tablero y Comandos Programados (Butler).
- BotonTarjeta: macro personalizada que aparece en el menú de una tarjeta
  o tablero y ejecuta múltiples acciones con un solo clic.
- ComandoProgramado: automatización basada en tiempo (cron).
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Boolean, JSON, Index
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class BotonTarjeta(Base, TimestampMixin):
    """
    Botón de tarjeta o tablero: macro que ejecuta una lista de acciones.
    ambito: 'tarjeta' (aparece en menú de tarjeta) o 'tablero' (en menú del tablero)
    acciones: lista de acciones (igual que ReglaAutomatizacion)
    color: color del botón
    icono: emoji o texto corto para mostrar en el botón
    """
    __tablename__ = "botones_tarjeta"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(80), nullable=False)
    descripcion = Column(Text, nullable=True)
    # Ámbito: 'tarjeta' | 'tablero'
    ambito = Column(String(20), default="tarjeta", nullable=False, index=True)
    # Tablero al que pertenece (null = global, disponible en todos)
    tablero_id = Column(
        Integer, ForeignKey("tableros.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    # Color del botón (para UI)
    color = Column(String(20), default="#6366f1", nullable=False)
    # Icono (emoji)
    icono = Column(String(8), default="⚡", nullable=False)
    # Lista de acciones (mismo formato que ReglaAutomatizacion)
    acciones = Column(JSON, nullable=False, default=list)
    # Si requiere confirmación antes de ejecutarse
    requiere_confirmacion = Column(Boolean, default=False, nullable=False)
    # Si está activo
    activo = Column(Boolean, default=True, nullable=False)
    # Posición de aparición
    posicion = Column(Integer, default=0, nullable=False)
    # Quién lo creó
    creador_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )

    tablero = relationship("Tablero", backref="botones")
    creador = relationship("Usuario")
    ejecuciones = relationship(
        "EjecucionBoton",
        back_populates="boton",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<BotonTarjeta {self.icono} {self.nombre}>"


class EjecucionBoton(Base, TimestampMixin):
    """Registro de cada ejecución de un botón (auditoría)."""
    __tablename__ = "ejecuciones_boton"

    id = Column(Integer, primary_key=True, autoincrement=True)
    boton_id = Column(
        Integer, ForeignKey("botones_tarjeta.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )
    exito = Column(Boolean, default=True, nullable=False)
    detalle = Column(Text, nullable=True)

    boton = relationship("BotonTarjeta", back_populates="ejecuciones")

    def __repr__(self) -> str:
        return f"<EjecucionBoton boton={self.boton_id} ticket={self.ticket_id}>"


class ComandoProgramado(Base, TimestampMixin):
    """
    Comando Butler basado en tiempo (cron).
    Ejemplos:
    - "Todos los lunes a las 9:00 AM, archivar tarjetas en 'Hecho'"
    - "Cada día a las 18:00, notificar tickets sin asignar con SLA por vencer"
    """
    __tablename__ = "comandos_programados"
    __table_args__ = (
        Index("ix_comando_tablero_activo", "tablero_id", "activo"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(120), nullable=False)
    descripcion = Column(Text, nullable=True)
    # Tablero (null = global)
    tablero_id = Column(
        Integer, ForeignKey("tableros.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    # Expresión cron (5 campos: min hora dia-mes mes dia-semana)
    # Ejemplos: "0 9 * * 1" = lunes 9 AM, "0 18 * * *" = diario 18h
    cron_expression = Column(String(60), nullable=False)
    # Zona horaria (por defecto UTC)
    timezone = Column(String(40), default="UTC", nullable=False)
    # Acciones a ejecutar
    acciones = Column(JSON, nullable=False, default=list)
    # Si está activo
    activo = Column(Boolean, default=True, nullable=False)
    # Última ejecución
    ultima_ejecucion = Column(String(50), nullable=True)
    # Próxima ejecución calculada
    proxima_ejecucion = Column(String(50), nullable=True)
    # Quién lo creó
    creador_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )

    tablero = relationship("Tablero", back_populates="comandos_programados")
    creador = relationship("Usuario")
    ejecuciones = relationship(
        "EjecucionComando",
        back_populates="comando",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ComandoProgramado {self.nombre} cron='{self.cron_expression}'>"


class EjecucionComando(Base, TimestampMixin):
    """Registro de cada ejecución de un comando programado."""
    __tablename__ = "ejecuciones_comando"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comando_id = Column(
        Integer, ForeignKey("comandos_programados.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    exito = Column(Boolean, default=True, nullable=False)
    detalle = Column(Text, nullable=True)
    tickets_afectados = Column(Integer, default=0, nullable=False)
    duracion_ms = Column(Integer, default=0, nullable=False)

    comando = relationship("ComandoProgramado", back_populates="ejecuciones")

    def __repr__(self) -> str:
        return f"<EjecucionComando comando={self.comando_id} exito={self.exito}>"
