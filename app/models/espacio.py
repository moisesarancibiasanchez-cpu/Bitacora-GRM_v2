"""
Modelo Espacio (Workspace): agrupación lógica de tableros.
Representa un equipo, departamento o empresa. Permite gestionar
facturación, miembros y permisos globales de sus tableros.
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Boolean, Index, Table
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import and_

from app.db.base import Base, TimestampMixin


# Tabla de asociación muchos-a-muchos: usuarios miembros de un espacio
espacio_miembros = Table(
    "espacio_miembros",
    Base.metadata,
    Column("espacio_id", Integer, ForeignKey("espacios.id", ondelete="CASCADE"), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("rol_espacio", String(40), default="miembro", nullable=False),
    Column("created_at", String(50), nullable=True),
)


class Espacio(Base, TimestampMixin):
    """
    Espacio de trabajo (workspace). Agrupa tableros bajo un mismo contexto
    organizacional (equipo, departamento, empresa).
    """
    __tablename__ = "espacios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(120), nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    # Tipo de plan
    plan = Column(String(30), default="gratis", nullable=False)  # gratis, standard, enterprise
    # Si el espacio es visible públicamente
    es_publico = Column(Boolean, default=False, nullable=False)
    # Propietario del espacio (admin principal)
    propietario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    # Configuración visual (color, logo)
    color = Column(String(20), default="#6366f1", nullable=False)
    icono = Column(String(40), default="espacio", nullable=False)

    # Relaciones
    propietario = relationship("Usuario", foreign_keys=[propietario_id])
    miembros = relationship(
        "Usuario",
        secondary=espacio_miembros,
        backref="espacios",
    )
    tableros = relationship(
        "Tablero",
        back_populates="espacio",
        cascade="all, delete-orphan",
    )

    @property
    def total_miembros(self) -> int:
        return len(self.miembros) if self.miembros else 0

    @property
    def total_tableros(self) -> int:
        return len(self.tableros) if self.tableros else 0

    def __repr__(self) -> str:
        return f"<Espacio {self.nombre} ({self.plan})>"


class Tablero(Base, TimestampMixin):
    """
    Tablero Kanban. Pertenece a un espacio y puede tener distintos
    niveles de visibilidad (Privado / Espacio / Público).
    """
    __tablename__ = "tableros"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(120), nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    # FK al espacio
    espacio_id = Column(
        Integer, ForeignKey("espacios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # Propietario (creador)
    propietario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    # Visibilidad: 'privado' | 'espacio' | 'publico'
    visibilidad = Column(String(20), default="privado", nullable=False, index=True)
    # Color / imagen de fondo
    color_fondo = Column(String(20), default="#0ea5e9", nullable=False)
    imagen_fondo = Column(String(500), nullable=True)
    # Si el tablero está archivado
    archivado = Column(Boolean, default=False, nullable=False, index=True)
    # URL pública para tableros públicos
    slug_publico = Column(String(60), nullable=True, unique=True, index=True)

    # Relaciones
    espacio = relationship("Espacio", back_populates="tableros")
    propietario = relationship("Usuario", foreign_keys=[propietario_id])
    permisos = relationship(
        "PermisoTablero",
        back_populates="tablero",
        cascade="all, delete-orphan",
    )
    listas = relationship(
        "Estado",
        back_populates="tablero",
        cascade="all, delete-orphan",
        order_by="Estado.orden",
    )
    tickets = relationship(
        "Ticket",
        back_populates="tablero",
        cascade="all, delete-orphan",
    )
    # Suscriptores: se consultan a través de WatchService (polimórfico)
    campos_personalizados = relationship(
        "CampoPersonalizado",
        back_populates="tablero",
        cascade="all, delete-orphan",
    )
    comandos_programados = relationship(
        "ComandoProgramado",
        back_populates="tablero",
        cascade="all, delete-orphan",
    )

    def usuario_tiene_acceso(self, usuario) -> bool:
        """Verifica si un usuario puede ver/interactuar con el tablero."""
        if self.visibilidad == "publico":
            return True
        if self.propietario_id == usuario.id:
            return True
        if self.visibilidad == "espacio" and self.espacio:
            return usuario in self.espacio.miembros
        # Privado: solo el propietario y los miembros invitados vía PermisoTablero
        return any(p.usuario_id == usuario.id for p in self.permisos)

    def __repr__(self) -> str:
        return f"<Tablero {self.nombre} visibilidad={self.visibilidad}>"


class PermisoTablero(Base, TimestampMixin):
    """
    Permiso granular de un usuario sobre un tablero (incluso siendo privado).
    Roles: 'admin' (todo), 'editor' (modificar), 'lector' (solo ver).
    """
    __tablename__ = "permisos_tablero"
    __table_args__ = (
        Index("uq_permiso_tablero_usuario", "tablero_id", "usuario_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tablero_id = Column(
        Integer, ForeignKey("tableros.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # admin | editor | lector
    rol_tablero = Column(String(30), default="editor", nullable=False)
    # Si recibe notificaciones del tablero
    notificar = Column(Boolean, default=True, nullable=False)
    # Quién lo invitó
    invitado_por_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True
    )

    tablero = relationship("Tablero", back_populates="permisos")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    invitado_por = relationship("Usuario", foreign_keys=[invitado_por_id])

    def __repr__(self) -> str:
        return f"<PermisoTablero tablero={self.tablero_id} usuario={self.usuario_id} rol={self.rol_tablero}>"
