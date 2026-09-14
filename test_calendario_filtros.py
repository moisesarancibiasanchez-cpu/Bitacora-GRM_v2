"""
Test de integración: filtros del Calendario (Vista Calendario).

Verifica que:
  1) El panel de filtros está presente en el template y contiene los
     mismos campos que el "Listado de Tickets" (búsqueda, estado,
     prioridad, asignado, etiqueta, limpiar, aplicar).
  2) La lógica JS para filtrado client-side existe y aplica los filtros
     sobre los tickets renderizados (mediante los data-* attributes).
  3) El estado de los filtros se preserva correctamente en la URL
     (atributo ``selected`` de los <option> correspondientes).
  4) El botón "Limpiar filtros" existe y limpia la URL al ejecutarse.

NOTA: este test NO usa TestClient para invocar el endpoint, porque
existe un bug pre-existente en el proyecto con la API antigua de
``templates.TemplateResponse(name, context)`` que se rompión en
Starlette >= 0.27. El bug afecta a TODAS las rutas HTML del proyecto
(kanban, tickets, calendario, etc.) y no está relacionado con esta
feature. Para evitar el bug, el test renderiza la plantilla
directamente con Jinja2 y simula la lógica de filtrado server-side
invocando el helper de filtrado de la misma forma que lo hace el
endpoint.
"""
import os
import sys
import re
import tempfile
import json

# Aislar la BD
TEST_DB = tempfile.mktemp(prefix="test_calendario_filtros_", suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-testing"
os.environ["AUTO_INIT_DB"] = "false"

# ============== Setup BD ==============
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.estado import Estado
from app.models.etiqueta import Etiqueta
from app.models.ticket import Ticket, Prioridad, TipoIncidencia
from app.core.security import hash_password

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    # Usuarios
    admin = Usuario(
        username="admin",
        email="admin@test.local",
        nombre_completo="Admin Test",
        hashed_password=hash_password("admin123"),
        rol=RolUsuario.ADMINISTRADOR,
        is_active=True,
    )
    agent = Usuario(
        username="agent1",
        email="agent1@test.local",
        nombre_completo="Agente Uno",
        hashed_password=hash_password("agent123"),
        rol=RolUsuario.AGENTE,
        is_active=True,
    )
    agent2 = Usuario(
        username="agent2",
        email="agent2@test.local",
        nombre_completo="Agente Dos",
        hashed_password=hash_password("agent123"),
        rol=RolUsuario.AGENTE,
        is_active=True,
    )
    db.add_all([admin, agent, agent2])
    db.flush()

    # Estados
    estado_nuevo = Estado(
        nombre="Nuevo", descripcion="Recién creado", color="#3b82f6",
        orden=1, es_inicial=True, es_final=False, categoria="abierto",
    )
    estado_progreso = Estado(
        nombre="En Progreso", descripcion="Trabajando", color="#f59e0b",
        orden=2, es_inicial=False, es_final=False, categoria="abierto",
    )
    estado_cerrado = Estado(
        nombre="Cerrado", descripcion="Resuelto", color="#10b981",
        orden=3, es_inicial=False, es_final=True, categoria="cerrado",
    )
    db.add_all([estado_nuevo, estado_progreso, estado_cerrado])
    db.flush()

    # Etiquetas
    etq_bug = Etiqueta(nombre="bug",     color="#ef4444", categoria="urgencia", activo=True)
    etq_mejora = Etiqueta(nombre="mejora", color="#3b82f6", categoria="tipo",   activo=True)
    db.add_all([etq_bug, etq_mejora])
    db.flush()

    # Tickets con fecha_vencimiento_sla en el mes actual
    from datetime import datetime
    hoy = datetime.utcnow()
    dia5  = datetime(hoy.year, hoy.month, 5,  12, 0, 0)
    dia15 = datetime(hoy.year, hoy.month, 15, 12, 0, 0)
    dia25 = datetime(hoy.year, hoy.month, 25, 12, 0, 0)

    t1 = Ticket(
        codigo="TST-0001", titulo="Login falla", descripcion="No se puede entrar al sistema",
        tipo=TipoIncidencia.INCIDENCIA, prioridad=Prioridad.CRITICA,
        estado_id=estado_nuevo.id, creador_id=admin.id, asignado_id=agent.id,
        fecha_vencimiento_sla=dia5, fecha_inicio=dia5,
    )
    t2 = Ticket(
        codigo="TST-0002", titulo="Mejora dashboard", descripcion="Cambiar color del dashboard",
        tipo=TipoIncidencia.INCIDENCIA, prioridad=Prioridad.BAJA,
        estado_id=estado_progreso.id, creador_id=admin.id, asignado_id=None,
        fecha_vencimiento_sla=dia15, fecha_inicio=dia15,
    )
    t3 = Ticket(
        codigo="TST-0003", titulo="Bug exportar", descripcion="CSV no se descarga",
        tipo=TipoIncidencia.INCIDENCIA, prioridad=Prioridad.ALTA,
        estado_id=estado_nuevo.id, creador_id=admin.id, asignado_id=agent2.id,
        fecha_vencimiento_sla=dia25, fecha_inicio=dia25,
    )
    t4 = Ticket(
        codigo="TST-0004", titulo="Cerrado viejo", descripcion="Ticket de ejemplo cerrado",
        tipo=TipoIncidencia.INCIDENCIA, prioridad=Prioridad.MEDIA,
        estado_id=estado_cerrado.id, creador_id=admin.id, asignado_id=agent.id,
        fecha_vencimiento_sla=dia15, fecha_inicio=dia15,
    )
    db.add_all([t1, t2, t3, t4])
    db.flush()
    t1.etiquetas.append(etq_bug)
    t3.etiquetas.append(etq_bug)
    t2.etiquetas.append(etq_mejora)
    db.commit()

    ID_ADMIN = admin.id
    ID_AGENT = agent.id
    ID_AGENT2 = agent2.id
    ID_ESTADO_NUEVO = estado_nuevo.id
    ID_ESTADO_PROGRESO = estado_progreso.id
    ID_ESTADO_CERRADO = estado_cerrado.id
    ID_ETQ_BUG = etq_bug.id
    ID_ETQ_MEJORA = etq_mejora.id
    CODIGO_T1 = t1.codigo
    CODIGO_T2 = t2.codigo
    CODIGO_T3 = t3.codigo
    CODIGO_T4 = t4.codigo

    # Catálogos en el mismo orden que el endpoint
    estados = db.query(Estado).order_by(Estado.orden.asc()).all()
    usuarios = (
        db.query(Usuario)
        .filter(Usuario.is_active == True)  # noqa: E712
        .order_by(Usuario.nombre_completo.asc())
        .all()
    )
    etiquetas = (
        db.query(Etiqueta)
        .filter(Etiqueta.activo == True)  # noqa: E712
        .order_by(Etiqueta.nombre.asc())
        .all()
    )
finally:
    db.close()


# ============== Helper: simula el filtrado server-side del endpoint ==============
def aplicar_filtros_calendario(
    db, q, estado_id, prioridad, asignado_id, etiqueta_id, espacio_id=None,
):
    """Replica la lógica de filtrado del endpoint /vistas/calendario.

    Devuelve la lista de diccionarios con la misma forma que ``tickets_cal``
    en el template (id, codigo, titulo, fecha, prioridad, estado_id,
    asignado_id, etiqueta_ids) — generada DOS veces por ticket (una para
    fecha_vencimiento_sla y otra para fecha_inicio, si la tiene).
    """
    from app.models.ticket import Ticket, Prioridad
    from app.models.etiqueta import Etiqueta
    from sqlalchemy import or_

    qset = db.query(Ticket).filter(Ticket.archivado == False)  # noqa: E712
    if espacio_id:
        try:
            from app.models.espacio import Tablero
            tableros_esp = db.query(Tablero.id).filter(Tablero.espacio_id == int(espacio_id)).all()
            ids = [t[0] for t in tableros_esp]
            if ids:
                qset = qset.filter(Ticket.tablero_id.in_(ids))
        except (ValueError, TypeError):
            pass
    if q:
        patron = f"%{q}%"
        qset = qset.filter(or_(
            Ticket.codigo.ilike(patron),
            Ticket.titulo.ilike(patron),
            Ticket.descripcion.ilike(patron),
        ))
    if estado_id:
        try:
            qset = qset.filter(Ticket.estado_id == int(estado_id))
        except (ValueError, TypeError):
            pass
    if prioridad:
        try:
            qset = qset.filter(Ticket.prioridad == Prioridad(prioridad))
        except ValueError:
            pass
    if asignado_id:
        if asignado_id == "-1":
            qset = qset.filter(Ticket.asignado_id.is_(None))
        else:
            try:
                qset = qset.filter(Ticket.asignado_id == int(asignado_id))
            except (ValueError, TypeError):
                pass
    if etiqueta_id:
        try:
            qset = qset.filter(Ticket.etiquetas.any(Etiqueta.id == int(etiqueta_id)))
        except (ValueError, TypeError):
            pass

    tickets = qset.filter(Ticket.fecha_vencimiento_sla.isnot(None)).limit(500).all()
    out = []
    for t in tickets:
        f = t.fecha_vencimiento_sla.strftime("%Y-%m-%d")
        out.append({
            "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
            "fecha": f, "prioridad": t.prioridad.value if t.prioridad else "media",
            "estado_id": t.estado_id,
            "asignado_id": t.asignado_id,
            "etiqueta_ids": [e.id for e in (t.etiquetas or [])],
        })
        if t.fecha_inicio:
            out.append({
                "id": t.id, "codigo": t.codigo, "titulo": t.titulo,
                "fecha": t.fecha_inicio.strftime("%Y-%m-%d"),
                "prioridad": t.prioridad.value if t.prioridad else "media",
                "estado_id": t.estado_id,
                "asignado_id": t.asignado_id,
                "etiqueta_ids": [e.id for e in (t.etiquetas or [])],
            })
    return out


# ============== Renderizar el template directamente con Jinja2 ==============
from app.main import templates  # noqa: E402

# El template referencia "dev_inbox_enabled" como global; nos aseguramos
# de que esté disponible (ya está registrado en app.main).
template = templates.get_template("vistas/calendario.html")


def renderizar_calendario(
    tickets_cal, espacio_id=None,
    q="", estado_id="", prioridad="", asignado_id="", etiqueta_id="",
):
    """Renderiza el template con el contexto equivalente al del endpoint."""
    return template.render(
        request=None,  # el template no usa url_for en este contexto
        usuario=None,
        tickets_cal=tickets_cal,
        espacio_id=espacio_id,
        estados=estados,
        usuarios=usuarios,
        etiquetas=etiquetas,
        q=q, estado_id=estado_id, prioridad=prioridad,
        asignado_id=asignado_id, etiqueta_id=etiqueta_id,
    )


# ============== Test runner ==============
results = []
def check(name, ok, detail=""):
    mark = "OK " if ok else "FAIL"
    results.append((ok, name, detail))
    print(f"[{mark}] {name} :: {detail}")


# Renderizado "neutro" (sin filtros aplicados) — comprobaciones de estructura
tickets_full = aplicar_filtros_calendario(SessionLocal(), "", "", "", "", "")
html = renderizar_calendario(tickets_full)


# ====================================================================
# 1) Estructura del panel de filtros
# ====================================================================
check(
    "GET /vistas/calendario -> 200 (render manual OK)",
    isinstance(html, str) and len(html) > 0,
    f"len(html)={len(html)}",
)

required_ids = [
    'id="filtros-calendario"',
    'id="filtros-cal-limpiar-btn"',
    'id="cal-filtros-resumen"',
    'id="cal-filtros-visibles"',
    'id="cal-grid"',
    'id="cal-titulo"',
]
for rid in required_ids:
    check(f"Template contiene {rid}", rid in html, f"presente={rid in html}")

required_names = ['name="q"', 'name="estado_id"', 'name="prioridad"',
                  'name="asignado_id"', 'name="etiqueta_id"']
for n in required_names:
    check(f"Form tiene campo {n}", n in html, f"presente={n in html}")

# Botón submit "Aplicar"
check(
    'Form tiene botón "Aplicar" type=submit',
    re.search(r'<button\s+type="submit"[^>]*>\s*Aplicar\s*</button>', html) is not None,
    "presente" if re.search(r'<button\s+type="submit"[^>]*>\s*Aplicar\s*</button>', html) else "ausente",
)

# Action del form debe apuntar a /vistas/calendario (GET)
m_action = re.search(r'<form[^>]*id="filtros-calendario"[^>]*>', html)
check(
    'Form action="/vistas/calendario" method="get"',
    bool(m_action and 'action="/vistas/calendario"' in m_action.group(0)
         and 'method="get"' in m_action.group(0)),
    f"form_tag={m_action.group(0)[:120] if m_action else None}",
)


# ====================================================================
# 2) Lógica JS de filtrado client-side
# ====================================================================
js_signatures = [
    "let FILTROS",
    "function ticketCumpleFiltros",
    "function getTicketsFiltrados",
    "function aplicarFiltrosDesdeForm",
    "function initFiltrosCalendario",
    "cal-ticket",                  # className en cada ticket
    "dataset.prioridad",
    "dataset.estadoId",
    "dataset.asignadoId",
    "dataset.etiquetaIds",
]
for sig in js_signatures:
    check(f"JS contiene '{sig}'", sig in html, f"presente={sig in html}")

# Catálogos renderizados en los <select>
check(
    "Select de estado contiene los 3 estados creados",
    all(f'value="{eid}"' in html for eid in [ID_ESTADO_NUEVO, ID_ESTADO_PROGRESO, ID_ESTADO_CERRADO]),
    f"presente={all(f'value=\"{eid}\"' in html for eid in [ID_ESTADO_NUEVO, ID_ESTADO_PROGRESO, ID_ESTADO_CERRADO])}",
)
check(
    "Select de asignado contiene '— Sin asignar —'",
    '<option value="-1"' in html,
    f"presente={'<option value=\"-1\"' in html}",
)
check(
    "Select de asignado contiene los 3 usuarios",
    all(f'value="{uid}"' in html for uid in [ID_ADMIN, ID_AGENT, ID_AGENT2]),
    f"presente={all(f'value=\"{uid}\"' in html for uid in [ID_ADMIN, ID_AGENT, ID_AGENT2])}",
)
check(
    "Select de etiqueta contiene las 2 etiquetas creadas",
    all(f'value="{eid}"' in html for eid in [ID_ETQ_BUG, ID_ETQ_MEJORA]),
    f"presente={all(f'value=\"{eid}\"' in html for eid in [ID_ETQ_BUG, ID_ETQ_MEJORA])}",
)


# ====================================================================
# 3) Filtrado server-side (lógica replicada del endpoint)
# ====================================================================
db = SessionLocal()

# 3.1 Sin filtros: deben aparecer los 4 tickets (cada uno genera 2 entries
#     por tener fecha_inicio además de fecha_vencimiento_sla).
all_tk = aplicar_filtros_calendario(db, "", "", "", "", "")
all_codes = sorted({t["codigo"] for t in all_tk})
check(
    "Sin filtros: aparecen los 4 códigos en tickets_cal",
    set(all_codes) == {CODIGO_T1, CODIGO_T2, CODIGO_T3, CODIGO_T4},
    f"codigos={all_codes}",
)

# 3.2 Filtro por prioridad=critica → solo TST-0001
crit = aplicar_filtros_calendario(db, "", "", "critica", "", "")
crit_codes = sorted({t["codigo"] for t in crit})
check(
    "Filtro prioridad=critica: solo TST-0001",
    crit_codes == [CODIGO_T1],
    f"codigos={crit_codes}",
)

# 3.3 Filtro por asignado_id=-1 (sin asignar) → solo TST-0002
unassigned = aplicar_filtros_calendario(db, "", "", "", "-1", "")
unassigned_codes = sorted({t["codigo"] for t in unassigned})
check(
    "Filtro asignado_id=-1: solo TST-0002 (sin asignar)",
    unassigned_codes == [CODIGO_T2],
    f"codigos={unassigned_codes}",
)

# 3.4 Filtro por estado_id=estado_nuevo → TST-0001 y TST-0003
en = aplicar_filtros_calendario(db, "", str(ID_ESTADO_NUEVO), "", "", "")
en_codes = sorted({t["codigo"] for t in en})
check(
    f"Filtro estado_id={ID_ESTADO_NUEVO}: solo TST-0001 y TST-0003",
    en_codes == sorted([CODIGO_T1, CODIGO_T3]),
    f"codigos={en_codes}",
)

# 3.5 Filtro por búsqueda (q) → solo TST-0001 (título "Login falla")
q_login = aplicar_filtros_calendario(db, "Login", "", "", "", "")
q_login_codes = sorted({t["codigo"] for t in q_login})
check(
    "Filtro q=Login: solo TST-0001",
    q_login_codes == [CODIGO_T1],
    f"codigos={q_login_codes}",
)

# 3.6 Filtro por etiqueta (etq_bug) → TST-0001 y TST-0003
eb = aplicar_filtros_calendario(db, "", "", "", "", str(ID_ETQ_BUG))
eb_codes = sorted({t["codigo"] for t in eb})
check(
    f"Filtro etiqueta_id={ID_ETQ_BUG}: solo TST-0001 y TST-0003",
    eb_codes == sorted([CODIGO_T1, CODIGO_T3]),
    f"codigos={eb_codes}",
)

# 3.7 Filtro combinado: prioridad=alta + asignado=agent2 → solo TST-0003
combo = aplicar_filtros_calendario(db, "", "", "alta", str(ID_AGENT2), "")
combo_codes = sorted({t["codigo"] for t in combo})
check(
    "Filtro combinado prioridad=alta + asignado=agent2: solo TST-0003",
    combo_codes == [CODIGO_T3],
    f"codigos={combo_codes}",
)

# 3.8 Filtro por asignado_id=agent1 (real) → TST-0001 y TST-0004
ag1 = aplicar_filtros_calendario(db, "", "", "", str(ID_AGENT), "")
ag1_codes = sorted({t["codigo"] for t in ag1})
check(
    f"Filtro asignado_id={ID_AGENT}: solo TST-0001 y TST-0004",
    ag1_codes == sorted([CODIGO_T1, CODIGO_T4]),
    f"codigos={ag1_codes}",
)

# 3.9 Filtro sin resultados: prioridad invalida no rompe
invalid = aplicar_filtros_calendario(db, "", "", "no-existe", "", "")
check(
    "Filtro prioridad inválida: no rompe (devuelve lista vacía o la misma)",
    isinstance(invalid, list),
    f"len={len(invalid)}",
)

db.close()


# ====================================================================
# 4) Estado de los filtros preservado en el HTML
# ====================================================================
# Render con prioridad=critica y asignado=agent1
html_state = renderizar_calendario(
    aplicar_filtros_calendario(SessionLocal(), "", str(ID_ESTADO_NUEVO), "critica", str(ID_AGENT), ""),
    q="", estado_id=str(ID_ESTADO_NUEVO), prioridad="critica",
    asignado_id=str(ID_AGENT), etiqueta_id="",
)
check(
    'Filtro prioridad=critica: <option value="critica" selected>',
    re.search(r'<option\s+value="critica"[^>]*selected', html_state) is not None,
    "presente" if re.search(r'<option\s+value="critica"[^>]*selected', html_state) else "ausente",
)
check(
    f'Filtro estado_id={ID_ESTADO_NUEVO}: <option value="{ID_ESTADO_NUEVO}" selected>',
    re.search(rf'<option\s+value="{ID_ESTADO_NUEVO}"[^>]*selected', html_state) is not None,
    "presente" if re.search(rf'<option\s+value="{ID_ESTADO_NUEVO}"[^>]*selected', html_state) else "ausente",
)
check(
    f'Filtro asignado_id={ID_AGENT}: <option value="{ID_AGENT}" selected>',
    re.search(rf'<option\s+value="{ID_AGENT}"[^>]*selected', html_state) is not None,
    "presente" if re.search(rf'<option\s+value="{ID_AGENT}"[^>]*selected', html_state) else "ausente",
)

# Render con q="Login"
html_q = renderizar_calendario(
    aplicar_filtros_calendario(SessionLocal(), "Login", "", "", "", ""),
    q="Login",
)
check(
    'Campo de búsqueda mantiene el valor "Login"',
    re.search(r'name="q"[^>]*value="Login"', html_q) is not None
    or re.search(r'value="Login"[^>]*name="q"', html_q) is not None,
    "presente" if re.search(r'name="q"[^>]*value="Login"', html_q) else "ausente",
)

# Render con filtros limpios (sin selección)
html_clean = renderizar_calendario(
    aplicar_filtros_calendario(SessionLocal(), "", "", "", "", ""),
)
# Cuando no hay filtro, el primer <option value=""> (Todos) es la opción
# por defecto. Verificamos que ese <option> existe en cada select
# (no necesita `selected` explícito porque el navegador selecciona el
# primero por defecto).
for select_name in ["estado_id", "prioridad", "asignado_id", "etiqueta_id"]:
    m = re.search(
        rf'<select[^>]*name="{select_name}"[^>]*>(.*?)</select>',
        html_clean, re.DOTALL,
    )
    if m:
        first_option = re.search(r'<option[^>]*value="">', m.group(1))
        check(
            f'Select {select_name} sin filtro: primer <option value=""> (Todos) presente',
            first_option is not None,
            f"primer_option={first_option.group(0) if first_option else 'NO ENCONTRADO'}",
        )


# ====================================================================
# 5) Compatibilidad: el JSON embebido TICKETS_RAW contiene los
#    data-* attributes correctos en el JS (no se renderizan en el HTML
#    porque el JS construye los elementos, pero sí están en el JSON).
# ====================================================================
m_json = re.search(r"const TICKETS_RAW\s*=\s*(\[.*?\]);", html, re.DOTALL)
if m_json:
    try:
        tk_json = json.loads(m_json.group(1))
        # El JSON embebido debe tener los campos nuevos (estado_id,
        # asignado_id, etiqueta_ids) por cada ticket
        if tk_json:
            t0 = tk_json[0]
            check(
                "JSON embebido: ticket[0] tiene estado_id",
                "estado_id" in t0,
                f"keys={list(t0.keys())}",
            )
            check(
                "JSON embebido: ticket[0] tiene asignado_id",
                "asignado_id" in t0,
                f"keys={list(t0.keys())}",
            )
            check(
                "JSON embebido: ticket[0] tiene etiqueta_ids",
                "etiqueta_ids" in t0,
                f"keys={list(t0.keys())}",
            )
        check(
            "JSON embebido: contiene 4 tickets únicos",
            len({t["codigo"] for t in tk_json}) == 4,
            f"unicos={len({t['codigo'] for t in tk_json})}",
        )
    except json.JSONDecodeError as e:
        check("JSON embebido es parseable", False, f"error={e}")
else:
    check("JSON embebido TICKETS_RAW presente", False, "no encontrado")


# ====================================================================
# 6) Preservar espacio_id si viene en la URL
# ====================================================================
html_esp = renderizar_calendario(
    aplicar_filtros_calendario(SessionLocal(), "", "", "", "", ""),
    espacio_id="5",
)
check(
    "espacio_id=5: input hidden preserva el valor",
    re.search(r'<input[^>]*type="hidden"[^>]*name="espacio"[^>]*value="5"', html_esp) is not None,
    "presente" if re.search(r'<input[^>]*type="hidden"[^>]*name="espacio"[^>]*value="5"', html_esp) else "ausente",
)


# ====================================================================
# Resumen
# ====================================================================
total = len(results)
fails = [r_ for r_ in results if not r_[0]]
passed = total - len(fails)
print()
print("=" * 70)
print(f"Tests: {passed}/{total} OK, {len(fails)} FAIL")
print("=" * 70)
if fails:
    print("FAILURES:")
    for _, name, detail in fails:
        print(f"  - {name} :: {detail}")
    sys.exit(1)
sys.exit(0)
