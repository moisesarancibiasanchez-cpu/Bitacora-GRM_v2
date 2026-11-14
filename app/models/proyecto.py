"""
Catalogo de proyectos (multi-tenancy) - V2.009.

Es la pieza ADITIVA del aislamiento por proyecto: hasta V2.008 la aplicacion
funcionaba con un unico proyecto implicito y el aislamiento se apoyaba en la
jerarquia Espacio -> Tablero -> Ticket, que no se aplicaba en las consultas de
tickets (el listado de /api/v1/tickets no filtraba por espacio).

Este modulo NO cambia el comportamiento de la aplicacion:

* ``proyecto_id`` se anade a las tablas de negocio como columna NULLABLE, con
  indice, y se rellena con el proyecto "Legacy" (id 1) en el backfill.
* La tabla ``proyectos`` se crea con una fila "Legacy" que representa
  exactamente los datos que ya existian.
* El filtro por proyecto (ORM) y las politicas RLS quedan PREPARADOS pero
  INERTES hasta que se active el flag ``AISLAMIENTO_PROYECTO_ACTIVO``, que es
  parte de la ventana V3 (el corte).

Ver ``app/core/proyecto.py`` para el contexto de proyecto.
"""
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Boolean, Table, Text,
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


#: Identificador del proyecto "Legacy": el que contiene todos los datos que
#: ya existian antes del aislamiento por proyecto. Es el destino del backfill
#: de la columna ``proyecto_id`` de todas las tablas de negocio.
PROYECTO_LEGACY_ID = 1

#: Nombre del proyecto "Legacy".
NOMBRE_PROYECTO_LEGACY = "Legacy"


# Tabla de asociacion many-to-many entre proyectos y usuarios.
# Las tablas de asociacion del repositorio usan ``created_at`` como
# ``String(50)`` (ver ``ticket_etiquetas`` y ``espacio_miembros``): se mantiene
# el mismo criterio para no introducir un tipo distinto en una tabla puente.
proyecto_usuarios = Table(
    "proyecto_usuarios",
    Base.metadata,
    Column("proyecto_id", Integer, ForeignKey("proyectos.id", ondelete="CASCADE"), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("rol", String(32), nullable=False, server_default="miembro"),
    Column("created_at", String(50), nullable=True),
)


class Proyecto(Base, TimestampMixin):
    """
    Proyecto (tenant) al que pertenecen los datos de negocio.

    "Legacy" (id 1) es el proyecto historico: contiene los 934 tickets y el
    resto de datos que ya existian. Los proyectos futuros se crean con filas
    nuevas; hasta la ventana de corte (V3) el aislamiento esta apagado y todos
    los proyectos comparten los mismos datos.
    """
    __tablename__ = "proyectos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(120), nullable=False, unique=True, index=True)
    descripcion = Column(Text, nullable=True)
    # Plan de suscripcion u organizacion (opcional, texto libre).
    plan = Column(String(40), nullable=True)
    # Color en formato hexadecimal (#FF0000), igual que en Etiqueta.
    color = Column(String(20), default="#6b7280", nullable=False)
    icono = Column(String(40), nullable=True)
    activo = Column(Boolean, default=True, nullable=False)

    # Propietario: el usuario responsable del proyecto. NULLABLE a proposito:
    # un proyecto sin propietario sigue siendo valido y el borrado de un
    # usuario no debe dejar projects huerfanos.
    propietario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )

    usuarios = relationship(
        "Usuario",
        secondary=proyecto_usuarios,
        back_populates="proyectos",
    )

    def __repr__(self) -> str:
        return f"<Proyecto {self.nombre} (id={self.id})>"
