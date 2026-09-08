"""
Script de inicialización de la base de datos.
Crea las tablas y carga datos semilla:
- Estados por defecto del flujo ITSM
- Transiciones válidas
- Usuarios de ejemplo
- Catálogos base
"""
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models import (
    Estado, TransicionEstado, Usuario, RolUsuario, Ticket,
    CatalogoTipo, CatalogoItem,
)
from app.models.ticket import Prioridad, TipoIncidencia


logger = logging.getLogger(__name__)


def init_database():
    """Crea todas las tablas y carga los datos iniciales."""
    print("=" * 60)
    print(f"Inicializando BD: {settings.get_database_url()}")
    print("=" * 60)

    # Crear todas las tablas
    Base.metadata.create_all(bind=engine)
    print("✓ Tablas creadas")

    db = SessionLocal()
    try:
        seed_estados(db)
        seed_transiciones(db)
        seed_usuarios(db)
        seed_catalogos(db)
        seed_tickets_demo(db)
        db.commit()
        print("✓ Datos semilla cargados")
    except Exception as e:
        db.rollback()
        print(f"✗ Error: {e}")
        raise
    finally:
        db.close()


def seed_estados(db: Session):
    """Crea el flujo estándar ITSM: Nuevo → En curso → En espera → Resuelto → Cerrado."""
    if db.query(Estado).count() > 0:
        print("  · Estados ya existen, saltando seed")
        return

    estados = [
        Estado(nombre="Nuevo",       color="#64748b", orden=1, es_inicial=True,  es_final=False, categoria="abierto",  sla_horas=24,  descripcion="Ticket recién creado, sin asignar"),
        Estado(nombre="En curso",    color="#3b82f6", orden=2, es_inicial=False, es_final=False, categoria="abierto",  sla_horas=48,  descripcion="Agente trabajando activamente"),
        Estado(nombre="En espera",   color="#f59e0b", orden=3, es_inicial=False, es_final=False, categoria="pausado",  sla_horas=72,  descripcion="Esperando información del solicitante o proveedor"),
        Estado(nombre="Resuelto",    color="#10b981", orden=4, es_inicial=False, es_final=False, categoria="cerrado",  sla_horas=24,  descripcion="Solución aplicada, pendiente de cierre formal"),
        Estado(nombre="Cerrado",     color="#475569", orden=5, es_inicial=False, es_final=True,  categoria="cerrado",  sla_horas=None, descripcion="Incidencia cerrada, SLA evaluado"),
        Estado(nombre="Cancelado",   color="#9ca3af", orden=6, es_inicial=False, es_final=True,  categoria="cerrado",  sla_horas=None, descripcion="Cancelado por el solicitante o duplicado"),
    ]
    for e in estados:
        db.add(e)
    db.flush()
    print(f"  ✓ {len(estados)} estados creados")


def seed_transiciones(db: Session):
    """Crea la matriz de transiciones válidas del flujo."""
    if db.query(TransicionEstado).count() > 0:
        return

    # Mapear nombre -> id
    estados = {e.nombre: e.id for e in db.query(Estado).all()}

    transiciones = [
        # De "Nuevo"
        ("Nuevo", "En curso",  "agente",        False, "Asignar y empezar a trabajar"),
        ("Nuevo", "Cancelado", "solicitante",   True,  "Cancelar antes de ser atendido"),
        # De "En curso"
        ("En curso", "En espera", "agente",      False, "Necesito más información"),
        ("En curso", "Resuelto",  "agente",      True,  "Solución aplicada"),
        ("En curso", "Cancelado", "agente_senior", True, "Cancelar con justificación"),
        # De "En espera"
        ("En espera", "En curso", "agente",       False, "Reanudar trabajo"),
        ("En espera", "Resuelto", "agente",       True,  "Resolver sin reanudar"),
        ("En espera", "Cancelado","agente_senior", True,  "Cancelar tras espera prolongada"),
        # De "Resuelto"
        ("Resuelto", "Cerrado",     "agente_senior", False, "Cierre formal del ticket"),
        ("Resuelto", "En curso",    "agente",      True,  "Reabrir por solución incompleta"),
        ("Resuelto", "Cancelado",   "administrador", True,  "Cancelar ticket resuelto"),
        # Desde Cerrado/Cancelado normalmente no se mueve, pero permitimos reapertura
        ("Cerrado", "En curso",     "administrador", True,  "Reabrir ticket cerrado"),
    ]
    for origen, destino, rol, comentario, desc in transiciones:
        db.add(TransicionEstado(
            estado_origen_id=estados[origen],
            estado_destino_id=estados[destino],
            rol_requerido=rol,
            requiere_comentario=comentario,
            descripcion=desc,
        ))
    db.flush()
    print(f"  ✓ {len(transiciones)} transiciones creadas")


def seed_usuarios(db: Session):
    """Crea usuarios de ejemplo con distintos roles."""
    if db.query(Usuario).count() > 0:
        return

    usuarios = [
        Usuario(
            username="admin", email="admin@bitacora.local",
            nombre_completo="Administrador General",
            hashed_password=hash_password("admin123"),
            rol=RolUsuario.ADMINISTRADOR,
            departamento="TI",
        ),
        Usuario(
            username="agente1", email="agente1@bitacora.local",
            nombre_completo="María González",
            hashed_password=hash_password("agente123"),
            rol=RolUsuario.AGENTE,
            departamento="Soporte Nivel 1",
        ),
        Usuario(
            username="lider", email="lider@bitacora.local",
            nombre_completo="Carlos Ramírez",
            hashed_password=hash_password("lider123"),
            rol=RolUsuario.AGENTE_SENIOR,
            departamento="Soporte Nivel 2",
        ),
        Usuario(
            username="usuario1", email="usuario1@bitacora.local",
            nombre_completo="Ana López",
            hashed_password=hash_password("user123"),
            rol=RolUsuario.SOLICITANTE,
            departamento="Ventas",
        ),
    ]
    for u in usuarios:
        db.add(u)
    db.flush()
    print(f"  ✓ {len(usuarios)} usuarios creados")


def seed_catalogos(db: Session):
    """Crea catálogos base para usar en los tickets."""
    if db.query(CatalogoTipo).count() > 0:
        return

    # Catálogo: Sistemas
    cat_sistemas = CatalogoTipo(
        nombre="Sistemas",
        descripcion="Sistemas y aplicaciones afectadas",
        esquema=[
            {"key": "version", "label": "Versión", "tipo": "string", "requerido": True},
            {"key": "ambiente", "label": "Ambiente", "tipo": "select", "opciones": ["Producción", "QA", "Desarrollo"], "requerido": True},
        ],
    )
    db.add(cat_sistemas)
    db.flush()

    items_sistemas = [
        CatalogoItem(catalogo_tipo_id=cat_sistemas.id, nombre="SAP ERP", datos={"version": "S/4HANA 2022", "ambiente": "Producción"}),
        CatalogoItem(catalogo_tipo_id=cat_sistemas.id, nombre="Portal Web", datos={"version": "v3.2", "ambiente": "Producción"}),
        CatalogoItem(catalogo_tipo_id=cat_sistemas.id, nombre="CRM Salesforce", datos={"version": "Spring '25", "ambiente": "Producción"}),
    ]
    for i in items_sistemas:
        db.add(i)

    # Catálogo: Categorías
    cat_cat = CatalogoTipo(
        nombre="Categorias",
        descripcion="Categoría de la incidencia",
        esquema=[{"key": "sla_horas", "label": "SLA horas", "tipo": "number", "requerido": True}],
    )
    db.add(cat_cat)
    db.flush()
    for nombre, sla in [("Hardware", 24), ("Software", 48), ("Red", 4), ("Acceso", 8), ("Email", 8)]:
        db.add(CatalogoItem(catalogo_tipo_id=cat_cat.id, nombre=nombre, datos={"sla_horas": sla}))

    db.flush()
    print(f"  ✓ Catálogos creados")


def seed_tickets_demo(db: Session):
    """Crea tickets de demostración para visualizar el tablero."""
    if db.query(Ticket).count() > 0:
        return

    estados = {e.nombre: e for e in db.query(Estado).all()}
    usuarios = {u.username: u for u in db.query(Usuario).all()}

    tickets_demo = [
        ("Impresora de contabilidad no responde", "La impresora del piso 3 no está imprimiendo desde esta mañana.", "media",  "Nuevo",     "usuario1", None),
        ("No puedo acceder al portal",            "Mi contraseña fue cambiada y no puedo entrar al portal.",      "alta",   "En curso",  "agente1",  "agente1"),
        ("Caída del CRM cada 5 min",              "El sistema se cae intermitentemente, aparentemente memoria.", "critica","En curso",  "lider",    "lider"),
        ("Solicitud de acceso VPN",               "Necesito acceso VPN para trabajo remoto.",                     "baja",   "Nuevo",     "usuario1", None),
        ("Pantalla azul en equipo de diseño",     "BSOD al abrir Photoshop, ya reinicié 2 veces.",                "alta",   "En espera", "agente1",  "agente1"),
        ("Migración completada",                  "La migración de base de datos terminó con éxito.",             "media",  "Resuelto",  "lider",    "lider"),
        ("Configuración de correo en móvil",      "Configurar cuenta Exchange en iPhone corporativo.",            "baja",   "Cerrado",   "lider",    "lider"),
        ("Reasignación de licencia Office",       "Liberar licencia del usuario saliente y asignar a nuevo.",     "media",  "En espera", "agente1",  "agente1"),
    ]
    contador = 1
    for titulo, desc, prio, estado_nombre, creador_un, asignado_un in tickets_demo:
        from datetime import timedelta
        estado = estados[estado_nombre]
        t = Ticket(
            codigo=f"GRM-INC-2026-{contador:06d}",
            titulo=titulo, descripcion=desc,
            tipo=TipoIncidencia.INCIDENCIA,
            prioridad=Prioridad(prio),
            estado_id=estado.id,
            creador_id=usuarios[creador_un].id,
            asignado_id=usuarios[asignado_un].id if asignado_un else None,
            fecha_vencimiento_sla=datetime.utcnow() + timedelta(hours=estado.sla_horas or 24),
            sla_cumplido=-1,
        )
        db.add(t)
        contador += 1
    db.flush()
    print(f"  ✓ {len(tickets_demo)} tickets demo creados")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_database()
