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
    Etiqueta, Checklist, ChecklistItem, Comentario, MencionUsuario, Adjunto,
    ReglaAutomatizacion,
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
        seed_etiquetas(db)
        seed_tickets_demo(db)
        seed_automatizaciones(db)
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
    etiquetas = {e.nombre: e for e in db.query(Etiqueta).all()}

    tickets_demo = [
        # titulo, desc, prio, estado, creador, asignado, etiquetas, checklists, comentarios
        ("Impresora de contabilidad no responde", "La impresora del piso 3 no está imprimiendo desde esta mañana.", "media",  "Nuevo",     "usuario1", None,
         ["Hardware"], [("Diagnóstico inicial", ["Verificar drivers", "Revisar tóner", "Probar con otro equipo"])], []),
        ("No puedo acceder al portal",            "Mi contraseña fue cambiada y no puedo entrar al portal.",      "alta",   "En curso",  "agente1",  "agente1",
         ["Acceso", "Red"], [("Pasos de recuperación", ["Resetear contraseña", "Notificar al usuario", "Validar acceso"])], [("agente1", "He reseteado la contraseña temporal, por favor intenta entrar @usuario1", False)]),
        ("Caída del CRM cada 5 min",              "El sistema se cae intermitentemente, aparentemente memoria.", "critica","En curso",  "lider",    "lider",
         ["Software", "Critico"], [("Investigación", ["Revisar logs de aplicación", "Monitorear memoria", "Escalar a infraestructura", "Aplicar hotfix"])], [("lider", "Subiendo memoria del servidor, @agente1 por favor valida con el usuario.", False)]),
        ("Solicitud de acceso VPN",               "Necesito acceso VPN para trabajo remoto.",                     "baja",   "Nuevo",     "usuario1", None,
         ["Acceso"], [("Configuración VPN", ["Crear usuario en VPN", "Generar credenciales", "Documentar entrega"])], []),
        ("Pantalla azul en equipo de diseño",     "BSOD al abrir Photoshop, ya reinicié 2 veces.",                "alta",   "En espera", "agente1",  "agente1",
         ["Hardware"], [("Resolución", ["Reinstalar drivers de video", "Probar con otro equipo", "Esperar repuesto"])], [("agente1", "Esperando repuesto de RAM del proveedor", False)]),
        ("Migración completada",                  "La migración de base de datos terminó con éxito.",             "media",  "Resuelto",  "lider",    "lider",
         ["Software"], [("Validación", ["Verificar integridad", "Pruebas de performance", "Cierre formal"])], [("lider", "Todo OK, listo para cerrar.", False)]),
        ("Configuración de correo en móvil",      "Configurar cuenta Exchange en iPhone corporativo.",            "baja",   "Cerrado",   "lider",    "lider",
         ["Software"], [], [("lider", "Configurado y verificado.", False)]),
        ("Reasignación de licencia Office",       "Liberar licencia del usuario saliente y asignar a nuevo.",     "media",  "En espera", "agente1",  "agente1",
         ["Software"], [("Tareas", ["Identificar licencia disponible", "Revocar al saliente", "Asignar al nuevo"])], []),
    ]
    contador = 1
    from datetime import timedelta
    for titulo, desc, prio, estado_nombre, creador_un, asignado_un, et_nombres, checklists_data, comentarios_data in tickets_demo:
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
        db.flush()
        # Etiquetas
        for en in et_nombres:
            if en in etiquetas:
                t.etiquetas.append(etiquetas[en])
        # Checklists
        for orden_cl, (titulo_cl, items) in enumerate(checklists_data):
            cl = Checklist(
                ticket_id=t.id, titulo=titulo_cl, orden=orden_cl, posicion=orden_cl,
            )
            db.add(cl)
            db.flush()
            for i, texto in enumerate(items):
                db.add(ChecklistItem(
                    checklist_id=cl.id, texto=texto, orden=i,
                    completado=(i < len(items) - 2 and estado_nombre == "Resuelto"),
                ))
        # Comentarios
        for username, texto, interno in comentarios_data:
            com = Comentario(
                ticket_id=t.id,
                usuario_id=usuarios[username].id,
                texto=texto,
                es_interno=interno,
            )
            db.add(com)
        contador += 1
    db.flush()
    print(f"  ✓ {len(tickets_demo)} tickets demo creados (con etiquetas/checklists/comentarios)")


def seed_etiquetas(db: Session):
    """Crea etiquetas estilo Trello: colores por categoría."""
    if db.query(Etiqueta).count() > 0:
        print("  · Etiquetas ya existen, saltando seed")
        return

    etiquetas = [
        # Urgencia
        ("Urgente",      "#ef4444", "urgencia", "Atención inmediata"),
        ("Alta",         "#f97316", "urgencia", "Resolver en < 4h"),
        ("Normal",       "#10b981", "urgencia", "SLA estándar"),
        ("Baja",         "#6b7280", "urgencia", "Sin apuro"),
        # Tipo
        ("Hardware",     "#8b5cf6", "tipo",     "Equipos físicos"),
        ("Software",     "#3b82f6", "tipo",     "Aplicaciones"),
        ("Red",          "#06b6d4", "tipo",     "Conectividad"),
        ("Acceso",       "#84cc16", "tipo",     "Cuentas y permisos"),
        ("Email",        "#ec4899", "tipo",     "Correo electrónico"),
        ("Critico",      "#dc2626", "tipo",     "Afecta producción"),
        # Área
        ("Ventas",       "#0ea5e9", "area",     "Departamento comercial"),
        ("Contabilidad", "#a855f7", "area",     "Finanzas"),
        ("RRHH",         "#f43f5e", "area",     "Recursos humanos"),
        # Impacto
        ("Producción",   "#facc15", "impacto",  "Afecta ambiente productivo"),
        ("QA",           "#22c55e", "impacto",  "Calidad"),
        ("Desarrollo",   "#94a3b8", "impacto",  "Entorno de desarrollo"),
    ]
    for nombre, color, categoria, descripcion in etiquetas:
        db.add(Etiqueta(
            nombre=nombre, color=color, categoria=categoria,
            descripcion=descripcion, activo=True,
        ))
    db.flush()
    print(f"  ✓ {len(etiquetas)} etiquetas creadas")


def seed_automatizaciones(db: Session):
    """Crea reglas Butler predefinidas."""
    if db.query(ReglaAutomatizacion).count() > 0:
        return

    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    reglas = [
        {
            "nombre": "Marcar tickets críticos como Urgente",
            "descripcion": "Cuando se crea un ticket con prioridad crítica, se etiqueta como Urgente",
            "disparador": "ticket_creado",
            "condiciones": [{"campo": "prioridad", "operador": "==", "valor": "CRITICA"}],
            "acciones": [{"tipo": "agregar_etiqueta", "parametros": {"etiqueta_id": 1}}],
            "prioridad": 10,
        },
        {
            "nombre": "Asignar tickets de Hardware a agente1",
            "descripcion": "Si el ticket es de tipo Hardware, asignarlo a María",
            "disparador": "ticket_creado",
            "condiciones": [],
            "acciones": [{"tipo": "crear_comentario", "parametros": {
                "texto": "🤖 [Butler] Ticket categorizado como Hardware, asignando a @agente1",
                "es_interno": True,
            }}],
            "prioridad": 20,
        },
        {
            "nombre": "Notificar cuando SLA está por vencer",
            "descripcion": "Alerta cuando quedan menos de 4h para el SLA",
            "disparador": "sla_por_vencer",
            "condiciones": [],
            "acciones": [
                {"tipo": "crear_comentario", "parametros": {
                    "texto": "⚠️ [Butler] El SLA está por vencer. Por favor priorizar.",
                    "es_interno": True,
                }},
                {"tipo": "agregar_etiqueta", "parametros": {"etiqueta_id": 1}},
            ],
            "prioridad": 5,
        },
        {
            "nombre": "Cierre automático con checklist completo",
            "descripcion": "Cuando todas las checklists están al 100% y se mueve a Resuelto, comentar",
            "disparador": "ticket_estado_cambiado",
            "condiciones": [
                {"campo": "estado.nombre", "operador": "==", "valor": "Resuelto"},
            ],
            "acciones": [
                {"tipo": "crear_comentario", "parametros": {
                    "texto": "✅ [Butler] Ticket marcado como Resuelto. Verificar checklist antes de cerrar.",
                    "es_interno": True,
                }},
            ],
            "prioridad": 30,
        },
    ]
    for r in reglas:
        db.add(ReglaAutomatizacion(creador_id=admin.id if admin else None, **r))
    db.flush()
    print(f"  ✓ {len(reglas)} reglas Butler creadas")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_database()
