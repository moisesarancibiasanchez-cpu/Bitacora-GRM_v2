"""
Script de inicialización de la base de datos.
Crea las tablas y carga datos semilla:
- Estados por defecto del flujo ITSM
- Transiciones válidas
- Usuarios de ejemplo (SOLO si SEED_DEMO_USERS=true, por seguridad)
- Catálogos base
- Espacios, tableros, custom fields, butler (estilo Trello)

NOTA DE SEGURIDAD: Los usuarios demo con contraseñas hardcodeadas
(``admin/admin123``, etc.) SOLO se crean si la variable de entorno
``SEED_DEMO_USERS=true`` está definida. Por defecto NO se crean
para evitar cuentas de acceso público en producción.
"""
import json
import logging
import os
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
from app.models.espacio import Espacio, Tablero, PermisoTablero, espacio_miembros
from app.models.campo_personalizado import CampoPersonalizado, ValorCampo
from app.models.butler_extras import BotonTarjeta, ComandoProgramado
from app.models.watch import Notificacion, Watch, Reaccion


logger = logging.getLogger(__name__)

# Bandera de seguridad: por defecto NO se crean usuarios demo con
# contraseñas conocidas. Activar explícitamente con SEED_DEMO_USERS=true
# SOLO en entornos de desarrollo local.
SEED_DEMO_USERS_ENABLED = os.getenv("SEED_DEMO_USERS", "false").lower() == "true"


def init_database():
    """Crea todas las tablas, aplica migraciones pendientes y carga los datos iniciales."""
    print("=" * 60)
    print(f"Inicializando BD: {settings.get_database_url()}")
    print("=" * 60)

    # 1) Aplicar migraciones idempotentes (alinea columnas nuevas)
    try:
        from app.db.migrations import apply_migrations
        stats = apply_migrations()
        print(f"✓ Migraciones aplicadas (added={stats['applied']}, "
              f"skipped={stats['skipped']}, errors={stats['errors']})")
    except Exception as e:
        print(f"⚠ Migraciones: {e}")

    # 2) Crear todas las tablas (no-op si existen)
    Base.metadata.create_all(bind=engine)
    print("✓ Tablas verificadas")

    db = SessionLocal()
    try:
        seed_estados(db)
        seed_transiciones(db)
        seed_usuarios(db)
        seed_catalogos(db)
        seed_etiquetas(db)
        seed_espacios(db)
        seed_tableros(db)
        seed_custom_fields(db)
        seed_butler_extras(db)
        seed_notificaciones_demo(db)
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
    """Crea usuarios de ejemplo con distintos roles.

    SEGURIDAD: Esta función SOLO crea los usuarios demo (con contraseñas
    hardcodeadas) si la variable de entorno ``SEED_DEMO_USERS=true`` está
    definida. En cualquier otro caso, no hace nada: el primer usuario
    debe registrarse a través del flujo de ``/auth/registro`` y será
    automáticamente Administrador.
    """
    if db.query(Usuario).count() > 0:
        return

    if not SEED_DEMO_USERS_ENABLED:
        print(
            "  · Seed de usuarios demo DESHABILITADO "
            "(defina SEED_DEMO_USERS=true para crear admin/admin123, etc.)"
        )
        print("  · El primer usuario que se registre por /auth/registro será Administrador.")
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
    print(f"  ✓ {len(usuarios)} usuarios demo creados (SEED_DEMO_USERS=true)")


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
            codigo=f"INC-{contador:03d}",
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


def seed_espacios(db: Session):
    """Crea espacios de trabajo (workspaces) de ejemplo."""
    if db.query(Espacio).count() > 0:
        print("  · Espacios ya existen, saltando seed")
        return
    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    espacios = [
        Espacio(
            nombre="Operaciones TI",
            descripcion="Gestión de incidencias, problemas y cambios del área de tecnología.",
            plan="empresa",
            color="#6366f1",
            icono="🏢",
            es_publico=False,
            propietario_id=admin.id if admin else None,
        ),
        Espacio(
            nombre="Proyectos 2026",
            descripcion="Tableros para seguimiento de proyectos estratégicos del año.",
            plan="equipo",
            color="#10b981",
            icono="🚀",
            es_publico=True,
            propietario_id=admin.id if admin else None,
        ),
        Espacio(
            nombre="Atención al Cliente",
            descripcion="Solicitudes y consultas de clientes externos e internos.",
            plan="equipo",
            color="#f59e0b",
            icono="🎧",
            es_publico=False,
            propietario_id=admin.id if admin else None,
        ),
    ]
    for e in espacios:
        db.add(e)
    db.flush()
    # Agregar miembros a todos los espacios (admin + otros)
    if espacios and admin:
        otros = db.query(Usuario).limit(4).all()
        for e in espacios:
            for u in otros:
                db.execute(espacio_miembros.insert().values(
                    espacio_id=e.id, usuario_id=u.id
                ))
    print(f"  ✓ {len(espacios)} espacios creados")


def seed_tableros(db: Session):
    """Crea tableros dentro de los espacios."""
    if db.query(Tablero).count() > 0:
        print("  · Tableros ya existen, saltando seed")
        return
    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    espacios = db.query(Espacio).all()
    if not espacios:
        return
    tableros = [
        Tablero(
            nombre="Incidencias de Producción",
            descripcion="Tickets activos de sistemas en producción.",
            espacio_id=espacios[0].id,
            propietario_id=admin.id if admin else None,
            visibilidad="espacio",
            color_fondo="#1e293b",
            slug_publico="incidencias-prod",
        ),
        Tablero(
            nombre="Mantenimientos Programados",
            descripcion="Planificación y seguimiento de mantenimientos.",
            espacio_id=espacios[0].id,
            propietario_id=admin.id if admin else None,
            visibilidad="espacio",
            color_fondo="#0f766e",
            slug_publico="mantto-prog",
        ),
        Tablero(
            nombre="Roadmap Q1",
            descripcion="Iniciativas y entregables del primer trimestre.",
            espacio_id=espacios[1].id if len(espacios) > 1 else espacios[0].id,
            propietario_id=admin.id if admin else None,
            visibilidad="publico",
            color_fondo="#7c3aed",
            slug_publico="roadmap-q1",
        ),
        Tablero(
            nombre="Backlog de Mejoras",
            descripcion="Ideas y solicitudes de mejora pendientes.",
            espacio_id=espacios[1].id if len(espacios) > 1 else espacios[0].id,
            propietario_id=admin.id if admin else None,
            visibilidad="espacio",
            color_fondo="#ea580c",
        ),
        Tablero(
            nombre="Soporte Cliente",
            descripcion="Atención de tickets de clientes.",
            espacio_id=espacios[2].id if len(espacios) > 2 else espacios[0].id,
            propietario_id=admin.id if admin else None,
            visibilidad="privado",
            color_fondo="#be185d",
        ),
    ]
    for t in tableros:
        db.add(t)
    db.flush()
    # Crear permisos para tableros privados/espacio
    usuarios = db.query(Usuario).all()
    for t in tableros:
        if t.visibilidad in ("privado", "espacio") and admin:
            # Admin siempre
            existe = db.query(PermisoTablero).filter(
                PermisoTablero.tablero_id == t.id,
                PermisoTablero.usuario_id == admin.id
            ).first()
            if not existe:
                db.add(PermisoTablero(
                    tablero_id=t.id, usuario_id=admin.id,
                    rol_tablero="admin", notificar=True,
                ))
        # Agregar al menos 2 usuarios como editores
        for u in usuarios[1:3]:
            existe = db.query(PermisoTablero).filter(
                PermisoTablero.tablero_id == t.id,
                PermisoTablero.usuario_id == u.id
            ).first()
            if not existe:
                db.add(PermisoTablero(
                    tablero_id=t.id, usuario_id=u.id,
                    rol_tablero="editor" if t.visibilidad != "privado" else "lector",
                    notificar=True,
                ))
    print(f"  ✓ {len(tableros)} tableros creados con permisos")


def seed_custom_fields(db: Session):
    """Crea campos personalizados de ejemplo en los tableros."""
    if db.query(CampoPersonalizado).count() > 0:
        print("  · Campos personalizados ya existen, saltando seed")
        return
    tableros = db.query(Tablero).all()
    if not tableros:
        return
    campos = [
        # Tablero 0: Incidencias
        {"tablero_id": tableros[0].id, "nombre": "Sistema afectado", "tipo": "dropdown",
         "configuracion": {"opciones": ["SAP", "Portal Web", "CRM", "Email", "Otro"]},
         "requerido": True, "posicion": 0, "color": "#3b82f6"},
        {"tablero_id": tableros[0].id, "nombre": "Horas estimadas", "tipo": "numero",
         "configuracion": {"min": 0, "max": 999},
         "posicion": 1, "color": "#10b981"},
        {"tablero_id": tableros[0].id, "nombre": "Requiere rollback", "tipo": "checkbox",
         "posicion": 2, "color": "#ef4444"},
        # Tablero 1: Mantenimientos
        {"tablero_id": tableros[1].id, "nombre": "Ventana de mantenimiento", "tipo": "fecha",
         "posicion": 0, "color": "#f59e0b"},
        {"tablero_id": tableros[1].id, "nombre": "URL de runbook", "tipo": "url",
         "posicion": 1, "color": "#8b5cf6"},
        # Tablero 2: Roadmap
        {"tablero_id": tableros[2].id, "nombre": "Esfuerzo (story points)", "tipo": "numero",
         "configuracion": {"min": 0, "max": 100}, "posicion": 0, "color": "#06b6d4"},
    ]
    for c in campos:
        db.add(CampoPersonalizado(**c))
    db.flush()
    print(f"  ✓ {len(campos)} campos personalizados creados")


def seed_butler_extras(db: Session):
    """Crea botones y comandos programados de ejemplo."""
    if db.query(BotonTarjeta).count() == 0:
        admin = db.query(Usuario).filter(Usuario.username == "admin").first()
        tableros = db.query(Tablero).all()
        t0 = tableros[0] if tableros else None
        botones = [
            BotonTarjeta(
                nombre="Marcar como urgente",
                descripcion="Agrega etiqueta Urgente y notifica al asignado",
                ambito="tarjeta",
                tablero_id=t0.id if t0 else None,
                color="#ef4444",
                icono="🔥",
                acciones=[
                    {"tipo": "agregar_etiqueta", "parametros": {"etiqueta_nombre": "Urgente"}},
                    {"tipo": "crear_comentario", "parametros": {
                        "texto": "🔥 [Botón] Marcado como urgente",
                        "es_interno": False,
                    }},
                ],
                requiere_confirmacion=True,
                creador_id=admin.id if admin else None,
                posicion=0,
            ),
            BotonTarjeta(
                nombre="Asignar a líder",
                descripcion="Reasigna el ticket a Carlos Ramírez",
                ambito="tarjeta",
                tablero_id=t0.id if t0 else None,
                color="#3b82f6",
                icono="👤",
                acciones=[
                    {"tipo": "asignar_usuario", "parametros": {"username": "lider"}},
                    {"tipo": "crear_comentario", "parametros": {
                        "texto": "👤 [Botón] Asignado a @lider",
                        "es_interno": False,
                    }},
                ],
                creador_id=admin.id if admin else None,
                posicion=1,
            ),
            BotonTarjeta(
                nombre="Archivar todas las tarjetas completadas",
                descripcion="Mueve a archivo los tickets en estado Cerrado",
                ambito="tablero",
                tablero_id=t0.id if t0 else None,
                color="#6b7280",
                icono="📦",
                acciones=[
                    {"tipo": "archivar_estado", "parametros": {"estado_nombre": "Cerrado"}},
                ],
                requiere_confirmacion=True,
                creador_id=admin.id if admin else None,
                posicion=0,
            ),
        ]
        for b in botones:
            db.add(b)
        db.flush()
        print(f"  ✓ {len(botones)} botones Butler creados")

    if db.query(ComandoProgramado).count() == 0:
        admin = db.query(Usuario).filter(Usuario.username == "admin").first()
        comandos = [
            ComandoProgramado(
                nombre="Recordatorio diario de SLA",
                descripcion="Cada mañana notifica tickets con SLA por vencer",
                cron_expression="0 9 * * 1-5",
                timezone="America/Santiago",
                acciones=[
                    {"tipo": "crear_comentario", "parametros": {
                        "texto": "⏰ [Butler] Revisar tickets con SLA por vencer hoy",
                        "es_interno": True,
                    }},
                ],
                activo=True,
                creador_id=admin.id if admin else None,
            ),
            ComandoProgramado(
                nombre="Archivar tickets cerrados semanalmente",
                descripcion="Todos los viernes archiva tickets cerrados hace más de 30 días",
                cron_expression="0 18 * * 5",
                timezone="UTC",
                acciones=[
                    {"tipo": "archivar_antiguos", "parametros": {"estado_nombre": "Cerrado", "dias": 30}},
                ],
                activo=True,
                creador_id=admin.id if admin else None,
            ),
            ComandoProgramado(
                nombre="Reporte semanal",
                descripcion="Cada lunes genera resumen de actividad",
                cron_expression="0 8 * * 1",
                timezone="America/Santiago",
                acciones=[
                    {"tipo": "crear_comentario", "parametros": {
                        "texto": "📊 [Butler] Generando reporte semanal...",
                        "es_interno": True,
                    }},
                ],
                activo=True,
                creador_id=admin.id if admin else None,
            ),
        ]
        for c in comandos:
            db.add(c)
        db.flush()
        print(f"  ✓ {len(comandos)} comandos programados creados")


def seed_notificaciones_demo(db: Session):
    """Crea notificaciones de ejemplo para el admin."""
    if db.query(Notificacion).count() > 0:
        print("  · Notificaciones demo ya existen, saltando seed")
        return
    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    agente = db.query(Usuario).filter(Usuario.username == "agente1").first()
    if not admin:
        return
    notifs = [
        Notificacion(
            usuario_id=admin.id, tipo="mencion",
            titulo="@agente1 te mencionó en un comentario",
            mensaje="He reseteado la contraseña temporal, por favor @admin valida el acceso",
            url="/tickets", leida=False,
            origen_usuario_id=agente.id if agente else None,
        ),
        Notificacion(
            usuario_id=admin.id, tipo="asignacion",
            titulo="Nuevo ticket asignado a ti",
            mensaje="Impresora de contabilidad no responde",
            url="/tickets", leida=False,
        ),
        Notificacion(
            usuario_id=admin.id, tipo="sla_vencimiento",
            titulo="SLA por vencer en 2h",
            mensaje="El ticket INC-005 vence pronto",
            url="/tickets", leida=False,
        ),
        Notificacion(
            usuario_id=admin.id, tipo="watch",
            titulo="Cambio de estado en ticket que sigues",
            mensaje="CRM Salesforce pasó a En curso",
            url="/tickets", leida=True,
        ),
    ]
    for n in notifs:
        db.add(n)
    db.flush()
    # Crear también algunas reacciones demo
    if agente:
        tickets = db.query(Ticket).limit(3).all()
        emojis = ["👍", "🎉", "👀"]
        for i, t in enumerate(tickets):
            db.add(Reaccion(
                usuario_id=agente.id, tipo_objeto="ticket",
                objeto_id=t.id, emoji=emojis[i % len(emojis)],
            ))
    print(f"  ✓ {len(notifs)} notificaciones demo creadas")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_database()
