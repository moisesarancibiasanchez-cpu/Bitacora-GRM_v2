# Subsistema de Comentarios — Bitácora GRM v2
## Informe técnico de exhaustividad para extensión

**Alcance:** lectura y documentación del subsistema de comentarios. No se modificó código.
**Fecha de lectura:** 2026-10-20. **Stack confirmado:** FastAPI + SQLAlchemy 2.x (declarativo) + Jinja2 + HTMX.

---

## Resumen ejecutivo

El subsistema de comentarios está concentrado en **cuatro archivos**: el modelo (`app/models/comentario.py`), los endpoints CRUD (`app/api/v1/features.py`, líneas 587-741), la capa de servicio (`app/services/features_service.py`, líneas 172-239) y un único template Python que genera el HTML del modal (`app/templates/tickets/detalle_modal.py`, líneas 624-673). El CRUD completo ya existe: `GET`, `POST`, `PATCH` y `DELETE` —contrario a la suposición inicial del encargo—. El flujo de UI es "modal completo": cada acción re-renderiza los 7 tabs del modal y reemplaza `#modal-root` entero.

Los tres hallazgos que condicionan cualquier extensión son: **(a)** el `POST` de creación **no usa el schema Pydantic** (parsea el body a mano), por lo que el `max_length=5000` del schema es letra muerta en la ruta de creación y no existe paginación en ningún punto; **(b)** ninguno de los 5 renderizadores del modal filtra `es_interno` por rol, de modo que los solicitantes ven comentarios internos en la UI aunque la API JSON sí los oculte; **(c)** no existe ningún parser `#ID` ni referencia entre comentarios —solo menciones `@usuario` y referencias ticket↔ticket—, y el servicio de notificaciones de menciones (`notificar_mencion`) es **código muerto**.

---

## 1. Modelo de datos

### 1.1 `Comentario` — `app/models/comentario.py`

Archivo completo (71 líneas). El bloque de definición del modelo ocupa las líneas 11-47:

```python
class Comentario(Base, TimestampMixin):
    """
    Comentario en un ticket. Soporta @menciones que notifican a usuarios.
    """
    __tablename__ = "comentarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    texto = Column(Text, nullable=False)
    # Si es True, el comentario es solo para el equipo (interno), no se muestra al solicitante
    es_interno = Column(Boolean, default=False, nullable=False)
    # Si fue edición, guarda el original
    editado = Column(Boolean, default=False, nullable=False)
    texto_original = Column(Text, nullable=True)

    ticket = relationship("Ticket", back_populates="comentarios")
    usuario = relationship("Usuario")
    menciones = relationship(
        "MencionUsuario",
        back_populates="comentario",
        cascade="all, delete-orphan",
    )

    def extraer_menciones(self) -> list:
        """Extrae los usernames mencionados con @ del texto del comentario."""
        patron = r'@(\w+)'
        return list(set(re.findall(patron, self.texto)))
```

Inventario campo por campo:

| # | Campo | Tipo SQLAlchemy | Tipo SQL | Null | Default | FK / ondelete | Index | Unique |
|---|-------|-----------------|----------|------|---------|---------------|-------|--------|
| 17 | `id` | `Integer` | `SERIAL` | PK | autoincrement | — | PK implícita | — |
| 18-21 | `ticket_id` | `Integer` | int | `False` | — | `tickets.id` / **CASCADE** | `True` | — |
| 22-25 | `usuario_id` | `Integer` | int | `False` | — | `usuarios.id` / **RESTRICT** | `True` | — |
| 26 | `texto` | `Text` | TEXT | `False` | — | — | no | — |
| 28 | `es_interno` | `Boolean` | bool | `False` | `False` | — | no | — |
| 30 | `editado` | `Boolean` | bool | `False` | `False` | — | no | — |
| 31 | `texto_original` | `Text` | TEXT | `True` | `None` | — | no | — |
| 16 (mixin) | `created_at` | `DateTime` | timestamp | `False` | `datetime.utcnow` | — | `True` | — |
| 19-24 (mixin) | `updated_at` | `DateTime` | timestamp | `False` | `datetime.utcnow`, `onupdate=datetime.utcnow` | — | no | — |

Observaciones críticas para la extensión:

- **No hay ningún `__table_args__`**: cero constraints, cero índices compuestos. No existe unicidad ni check de longitud en BD. `texto` es `Text` sin cota: la única defensa de longitud vive en Pydantic, y esa defensa no está conectada a la ruta de creación (ver §6).
- **Timestamps**: provienen de `TimestampMixin` en `app/db/base.py` líneas 14-24. Sí existe campo de "modificado": `updated_at` con `onupdate=datetime.utcnow`. Importante: se actualiza en **cualquier** UPDATE del ORM, no solo en ediciones de texto; por ejemplo `marcar_mencion_notificada` (que toca otra tabla) no lo altera, pero cualquier futura columna mutable added a `Comentario` activará el `onupdate`.
- **Campo de autor**: es `usuario_id` (FK escalar, `ondelete="RESTRICT"`) **más** la relación `usuario = relationship("Usuario")` (línea 34), que **no declara `back_populates`**. `Usuario` no tiene relación inversa a comentarios. Consecuencia práctica: borrar un usuario con comentarios está bloqueado por BD (`RESTRICT`), y no hay forma de navegar `usuario.comentarios`.
- **Relaciones declaradas**: `ticket` (bidireccional con `Ticket.comentarios`, línea 33), `usuario` (unidirectional, línea 34) y `menciones` (bidireccional con `MencionUsuario.comentario`, línea 35-39, con `cascade="all, delete-orphan"` — borrar el comentario borra sus menciones en cascada a nivel ORM).
- **`extraer_menciones()` (líneas 41-44)**: método de instancia (no `@staticmethod`, a diferencia del gemelo de `trello_service.py`) que usa la regex `r'@(\w+)'` sobre `self.texto`. Devuelve `list(set(...))`, es decir **orden no determinista** y **deduplicada**. `\w` incluye dígitos y guion bajo; no reconoce emails (`@correo.com` matchearía `correo`) ni menciones con punto.

### 1.2 `MencionUsuario` — mismo archivo, líneas 50-70

```python
class MencionUsuario(Base):
    """
    Relación usuario mencionado en un comentario.
    Se usa para enviar notificaciones.
    """
    __tablename__ = "menciones_usuario"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comentario_id = Column(
        Integer, ForeignKey("comentarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # Si ya se le notificó
    notificado = Column(Integer, default=0, nullable=False)  # 0=False, 1=True

    comentario = relationship("Comentario", back_populates="menciones")
    usuario = relationship("Usuario")
```

Puntos a retener: **no** hereda `TimestampMixin` (no tiene `created_at` ni `updated_at`), usa un `Integer` como booleano en lugar de `Boolean`, **no tiene `UniqueConstraint`** sobre `(comentario_id, usuario_id)` (puede haber filas duplicadas si se invoca dos veces la creación), y su FK a `usuarios.id` usa `CASCADE` —a diferencia del `RESTRICT` de `Comentario.usuario_id`—.

### 1.3 Exportación y registro

`app/models/__init__.py` línea 9: `from app.models.comentario import Comentario, MencionUsuario`; línea 44 los incluye en `__all__`.

### 1.4 Relación inversa en `Ticket` — `app/models/ticket.py` líneas 257-273

```python
    comentarios = relationship(
        "Comentario",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="Comentario.created_at.desc()",
    )
```

y la propiedad de conteo (líneas 271-273):

```python
    @property
    def total_comentarios(self) -> int:
        return len(self.comentarios) if self.comentarios else 0
```

**Contradicción de orden documentada**: la relación declara `created_at.desc()` (más reciente primero) mientras que las 5 consultas que alimentan el modal fuerzan `.order_by(Comentario.created_at.asc())` (más antiguo primero, orden cronológico de conversación) y el servicio `ComentarioService.listar_de_ticket` usa `.desc()`. Hay tres criterios de orden coexistiendo; el que ve el usuario en el modal es ASC.

### 1.5 Autor: modelo `Usuario` — `app/models/usuario.py` líneas 20-31

```python
class Usuario(Base, TimestampMixin):
    ...
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    nombre_completo = Column(String(200), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    rol = Column(Enum(RolUsuario), nullable=False, default=RolUsuario.SOLICITANTE, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
```

Los datos de autor disponibles para renderizar son `username` (clave de las menciones), `nombre_completo` (usado en el template) y `rol`. `RolUsuario` es el enum que gobierna el filtrado de `es_interno`.

### 1.6 Modelo hermano ya preparado para comentarios: `Reaccion` — `app/models/watch.py` líneas 43-70

Existe una tabla genérica de reacciones con soporte **ya declarado** para comentarios:

```python
class Reaccion(Base, TimestampMixin):
    """
    Reacción emoji sobre un comentario o ticket.
    Cada usuario puede reaccionar una vez por emoji a cada objeto.
    """
    __tablename__ = "reacciones"
    __table_args__ = (
        UniqueConstraint("usuario_id", "tipo_objeto", "objeto_id", "emoji", name="uq_reaccion_unica"),
    )
    ...
    # tipo_objeto: 'comentario' | 'ticket'
    tipo_objeto = Column(String(20), nullable=False, index=True)
    objeto_id = Column(Integer, nullable=False, index=True)
    # Emoji Unicode (👍 ❤️ 🎉 😄 🤔 👀 🚀 etc.)
    emoji = Column(String(16), nullable=False, index=True)
```

No hay FK a `comentarios.id` (es un puntero polimórfico por diseño, `objeto_id`), por lo que borrar un comentario deja reacciones huérfanas. Es el punto de extensión más avanzado que ya existe en el código y que **nadie usa todavía en la UI de comentarios**.

---

## 2. Endpoints API de comentarios

### 2.1 Prefijos y orden de registro

`app/main.py` línea 123: `app.include_router(api_router, prefix="/api/v1")`.

El router de comentarios es `features.router`, definido en `app/api/v1/features.py` línea 51 como `router = APIRouter(tags=["features"])` — **sin prefijo propio**, por lo que las rutas literales ya empiezan con `/tickets/...` y `/comentarios/...`.

El orden de registro en `app/api/v1/router.py` es relevante (comentario en líneas 22-38 que documenta un bug histórico de *shadowing*): `referencias.router_tickets` se registra en la línea 39 **antes** que `tickets.router` en la línea 40, porque `GET /api/v1/tickets/buscar` debe ganarle a `GET /api/v1/tickets/{ticket_id}`. `features.router` se registra en la línea 44. Cualquier endpoint nuevo bajo `/comentarios/{...}` en `features.py` es seguro frente a este shadowing.

### 2.2 Los cuatro endpoints CRUD (todos en `app/api/v1/features.py`)

#### (a) Listado — `GET /api/v1/tickets/{ticket_id}/comentarios`

`app/api/v1/features.py` líneas 590-600, texto literal:

```python
@router.get("/tickets/{ticket_id}/comentarios", response_model=List[ComentarioRead])
def listar_comentarios(
    ticket_id: int,
    incluir_internos: bool = True,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    # Solo agentes ven internos
    if incluir_internos and user.rol == RolUsuario.SOLICITANTE:
        incluir_internos = False
    return ComentarioService(db).listar_de_ticket(ticket_id, incluir_internos)
```

Devuelve **JSON** (`List[ComentarioRead]`). Dependencias: `get_db`, `get_current_user`. **No** usa `require_role`. Verifica existencia del ticket (implícitamente no: si el ticket no existe devuelve lista vacía, no 404). Orden resultante: `created_at.desc()` (ver servicio, §2.3).

#### (b) Creación — `POST /api/v1/tickets/{ticket_id}/comentarios`

`app/api/v1/features.py` líneas 603-677, texto literal completo:

```python
@router.post("/tickets/{ticket_id}/comentarios")
async def crear_comentario(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Crea un comentario en un ticket.

    Acepta ``application/x-www-form-urlencoded`` (formularios HTMX),
    ``multipart/form-data`` y ``application/json`` (clientes programáticos).
    Si la petición viene de HTMX (``HX-Request: true`` devuelve el modal
    re-renderizado con el nuevo comentario.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    content_type = request.headers.get("content-type", "")
    texto = ""
    es_interno = "false"
    active_tab = ""

    if content_type.startswith("application/json"):
        import json as _json
        try:
            body_bytes = await request.body()
            body = _json.loads(body_bytes.decode("utf-8") or "{}")
        except Exception:
            body = {}
        texto = (body.get("texto") or "").strip()
        es_interno = body.get("es_interno", False)
        active_tab = (body.get("active_tab") or "").strip()
    else:
        # form-data (HTMX)
        form = await request.form()
        texto = (form.get("texto") or "").strip()
        es_interno = form.get("es_interno", "false")
        active_tab = (form.get("active_tab") or "").strip()

    if not texto:
        if is_htmx:
            return HTMLResponse(
                content=(
                    f'<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">'
                    f'El texto del comentario no puede estar vacío.</div>'
                ),
                status_code=400,
            )
        raise HTTPException(status_code=400, detail="El texto del comentario no puede estar vacío")
    es_interno_bool = str(es_interno).lower() in ("true", "on", "1", "yes", "si", "sí")
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        if is_htmx:
            return HTMLResponse(
                content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">Ticket no encontrado.</div>',
                status_code=404,
            )
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    com = ComentarioService(db).crear(
        ticket_id=ticket_id,
        usuario_id=user.id,
        texto=texto,
        es_interno=es_interno_bool,
    )
    registrar_auditoria(db, ticket.id, user.id, "comentario_creado", valor_nuevo={"comentario_id": com.id})
    MotorAutomatizacion(db).disparar("ticket_comentado", ticket, {"comentario_id": com.id})

    if is_htmx:
        db.refresh(com)
        html = _render_detalle_modal_response(db, ticket, user, active_tab=active_tab or "comentarios")
        return HTMLResponse(
            content=html,
            status_code=200,
            headers={"HX-Trigger": "comentario-creado"},
        )
    return com
```

**Validación actual (resumen):** la única validación es `if not texto` (línea 640), un check de vacío post-`.strip()`. **No hay `response_model`**, **no se instancia `ComentarioCreate`**, por lo que no se aplica `max_length=5000`. Tampoco hay validación de longitud mínima real (el `required` del `<textarea>` es solo cliente), ni control de longitud máxima en BD, ni verificación de que el usuario tenga relación con el ticket (cualquier usuario autenticado puede comentar cualquier ticket, incluidos los internos aunque sea `SOLICITANTE`).

Devolución: si llega `HX-Request: true` → `HTMLResponse` con el **modal completo re-renderizado** y header `HX-Trigger: comentario-creado`. Si no → devuelve el objeto ORM `com` serializado por FastAPI sin `response_model` (serialización por `jsonable_encoder`, no por Pydantic: las relaciones no cargadas se omiten silenciosamente).

Efectos colaterales en la creación: `registrar_auditoria(...)` con acción `"comentario_creado"` (línea 666) y `MotorAutomatizacion(db).disparar("ticket_comentado", ticket, {"comentario_id": com.id})` (línea 667), que evalúa reglas Butler con disparador `ticket_comentado` (ver §5.4).

#### (c) Edición — `PATCH /api/v1/comentarios/{comentario_id}`

`app/api/v1/features.py` líneas 680-693, texto literal:

```python
@router.patch("/comentarios/{comentario_id}", response_model=ComentarioRead)
def editar_comentario(
    comentario_id: int,
    datos: ComentarioCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    com = db.query(Comentario).filter(Comentario.id == comentario_id).first()
    if not com:
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    if com.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
        raise HTTPException(status_code=403, detail="No autorizado para editar")
    com = ComentarioService(db).editar(comentario_id, datos.texto)
    return com
```

Devuelve **JSON** (`ComentarioRead`). Usa `ComentarioCreate` como body model —**no** `ComentarioUpdate` (que existe en schemas y está sin uso). Aquí sí se aplica `max_length=5000`, lo que produce un 422 automático de FastAPI. **No tiene rama HTMX**: si se invoca desde el navegador, devuelve JSON crudo donde el HTMX intentaría inyectarlo. Tampoco emite `HX-Trigger` ni registra auditoría.

Control de acceso: 404 si no existe; 403 si `com.usuario_id != user.id` y el rol no es exactamente `ADMINISTRADOR` (los `AGENTE_SENIOR` **no** pueden editar comentarios ajenos).

#### (d) Borrado — `DELETE /api/v1/comentarios/{comentario_id}`

`app/api/v1/features.py` líneas 696-741, texto literal:

```python
@router.delete("/comentarios/{comentario_id}")
async def eliminar_comentario(
    comentario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Elimina un comentario. Si viene de HTMX devuelve el modal
    re-renderizado; si no, devuelve 204.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    active_tab = "comentarios"
    if is_htmx:
        try:
            form = await request.form()
            active_tab = (form.get("active_tab") or "comentarios").strip() or "comentarios"
        except Exception:
            pass
    com = db.query(Comentario).filter(Comentario.id == comentario_id).first()
    if not com:
        if is_htmx:
            return HTMLResponse(
                content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">Comentario no encontrado.</div>',
                status_code=404,
            )
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    if com.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
        if is_htmx:
            return HTMLResponse(
                content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">No autorizado para eliminar.</div>',
                status_code=403,
            )
        raise HTTPException(status_code=403, detail="No autorizado para eliminar")
    ticket_id = com.ticket_id
    ComentarioService(db).eliminar(comentario_id)
    registrar_auditoria(db, ticket_id, user.id, "comentario_eliminado", valor_anterior={"comentario_id": comentario_id})
    if is_htmx:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if ticket:
            html = _render_detalle_modal_response(db, ticket, user, active_tab=active_tab)
            return HTMLResponse(
                content=html,
                status_code=200,
                headers={"HX-Trigger": "comentario-eliminado"},
            )
    return Response(status_code=204)
```

**Sí existe endpoint de DELETE.** Es HTMX-aware: devuelve el modal completo con `HX-Trigger: comentario-eliminado`, o `204` vacío para clientes JSON. Mismo criterio de permisos que la edición. Registra auditoría con `valor_anterior={"comentario_id": ...}`.

**Nota crítica para la UI**: el template actual (§3) **no contiene ningún botón que llame a este DELETE**. El endpoint está implementado y protegido en backend pero es inalcanzable desde la interfaz.

### 2.3 Capa de servicio — `app/services/features_service.py` líneas 172-239

```python
class ComentarioService:
    def __init__(self, db: Session):
        self.db = db

    def listar_de_ticket(self, ticket_id: int, incluir_internos: bool = True) -> List[Comentario]:
        q = self.db.query(Comentario).filter(Comentario.ticket_id == ticket_id)
        if not incluir_internos:
            q = q.filter(Comentario.es_interno == False)  # noqa: E712
        return q.order_by(Comentario.created_at.desc()).all()

    def crear(self, ticket_id: int, usuario_id: int, texto: str, es_interno: bool = False) -> Comentario:
        com = Comentario(
            ticket_id=ticket_id,
            usuario_id=usuario_id,
            texto=texto,
            es_interno=es_interno,
        )
        self.db.add(com)
        self.db.flush()
        # Procesar menciones @usuario
        usernames = com.extraer_menciones()
        if usernames:
            usuarios = (
                self.db.query(Usuario)
                .filter(Usuario.username.in_(usernames))
                .all()
            )
            for u in usuarios:
                m = MencionUsuario(
                    comentario_id=com.id,
                    usuario_id=u.id,
                    notificado=0,
                )
                self.db.add(m)
        self.db.commit()
        self.db.refresh(com)
        return com

    def editar(self, comentario_id: int, nuevo_texto: str) -> Optional[Comentario]:
        com = self.db.query(Comentario).filter(Comentario.id == comentario_id).first()
        if not com:
            return None
        if not com.editado:
            com.texto_original = com.texto
            com.editado = True
        com.texto = nuevo_texto
        self.db.commit()
        self.db.refresh(com)
        return com

    def eliminar(self, comentario_id: int) -> bool:
        com = self.db.query(Comentario).filter(Comentario.id == comentario_id).first()
        if not com:
            return False
        self.db.delete(com)
        self.db.commit()
        return True

    def marcar_mencion_notificada(self, mencion_id: int) -> bool:
        m = self.db.query(MencionUsuario).filter(MencionUsuario.id == mencion_id).first()
        if not m:
            return False
        m.notificado = 1
        self.db.commit()
        return True
```

Puntos de extensión: `crear()` centraliza el parseo de menciones (líneas 194-208), por lo que **cualquier** creación que pase por el servicio dispara el extractor; pero la creación desde el motor Butler (ver §5.4) **omite** el servicio y crea `Comentario(...)` directo, por lo que esas menciones nunca se registran. `editar()` guarda el texto original solo en la **primera** edición (`if not com.editado`), por lo que el historial es de una sola generación y `texto_original` se sobreescribe en cada edición posterior solo si `editado` ya era `True`... realmente no: la guarda solo la primera vez, luego el `original` queda congelado. Además `editar()` no re-procesa menciones del nuevo texto.

Existe además un helper de acceso (`features_service.py` líneas 665-666): `def get_comentario_service(db: Session) -> ComentarioService`.

### 2.4 Endpoints que renderizan la lista de comentarios (5 renderizadores + 1 JSON)

**El template que pinta la lista de comentarios es uno solo**: `DETALLE_TEMPLATE` en `app/templates/tickets/detalle_modal.py` (constante definida en la línea 32, función pública `render_detalle_modal` en las líneas 1462-1553). El bloque concreto está en las líneas 624-673 (§3).

Los endpoints que lo invocan:

| Endpoint | Archivo:líneas de la query de comentarios | Tipo de retorno |
|---|---|---|
| `GET /api/v1/tickets/{id}/detalle-html` | `tickets.py:332-438` (query en 358-363) | `HTMLResponse` (modal completo) |
| `PATCH /api/v1/tickets/{id}` (auto-save de campos) | `tickets.py:531…` (query en 629-634) | `HTMLResponse` con `HX-Swap: none` (renderiza y **descarta**) |
| `POST /api/v1/tickets/{id}/guardar` | `tickets.py:712-950` (query en 875-880) | `HTMLResponse` (modal completo) |
| `PATCH /api/v1/tickets/{id}/campos/{campo_id}` | `tickets.py:952-1186` (query en 1066-1069) | `HTMLResponse` (modal completo) |
| Helper `_render_detalle_modal_response` | `features.py:61-142` (query en 85-90) | `str` de HTML, usado por POST comentario y DELETE comentario |
| `GET /api/v1/tickets/{id}/detalle` | `features.py:1159-1264` (serialización en 1236-1250) | **JSON** con la lista de comentarios anidada |

El patrón de query es **idéntico y repetido 5 veces** (copiado, no reutilizado). Por ejemplo, en `tickets.py` líneas 358-363 y en `features.py` líneas 85-90:

```python
    comentarios = (
        db.query(Comentario)
        .filter(Comentario.ticket_id == ticket_id)
        .order_by(Comentario.created_at.asc())
        .all()
    )
```

**Ningún renderizador filtra `es_interno`.** La ruta JSON `GET /tickets/{id}/comentarios` sí lo hace (`features.py:597-599`), pero las 5 rutas que alimentan el modal HTML devuelven todos los comentarios, incluidos los internos, sin importar el rol del usuario que abre el modal. Dado que `es_interno` significa "no se muestra al solicitante" (comentario del propio modelo, línea 27), esto es una fuga de información a rol `SOLICITANTE` vía UI.

**Consecuencia arquitectónica para las nuevas features**: cualquier campo nuevo que se quiera mostrar en la lista de comentarios (por ejemplo, reacciones, referencias, estado de edición, menciones resueltas) debe añadirse en **5 sitios** de query + **5 llamadas** a `render_detalle_modal` + **1 template**. El helper `_render_detalle_modal_response` de `features.py` existe pero solo lo usan 2 de los 5 caminos.

### 2.5 Lo que **no** está en `tickets.py` ni `kanban.py`

- `app/api/v1/kanban.py` (79 líneas, leído completo): **cero referencias a comentarios**. Solo sirve el tablero y las columnas.
- `app/api/v1/referencias.py` (352 líneas): **cero referencias a comentarios**. Solo ticket↔ticket (§5).
- `app/api/v1/tickets.py`: ninguna ruta crea/edita/borra comentarios. Las apariciones de `comentario` en ese archivo son (a) el campo `comentario` de auditoría de `CambioEstadoRequest` (líneas 192, 830), (b) el flag `requiere_comentario` de las transiciones de estado (líneas 265-323, helper `transicion-info`), y (c) las 4 queries de re-render del modal documentadas arriba. Las líneas 1143-1144 son un diccionario de etiquetas de auditoría:
  ```python
        "COMENTARIO_CREADO": "agregó un comentario",
        "COMENTARIO_ELIMINADO": "eliminó un comentario",
  ```

### 2.6 Dependencias de autenticación (para referencia)

`app/api/v1/deps.py`: `get_current_user` (líneas 31-88) resuelve por `Authorization: Bearer` → cookie `access_token` → header `X-User-Id` (deshabilitado salvo `ALLOW_XUSER_HEADER=true`). `require_role(*roles)` (líneas 91-100) es la fábrica de dependencias por rol, y `require_admin` (líneas 103-110). **Ningún endpoint de comentarios usa `require_role`**: la autorización es "autenticado + dueño o administrador".

---

## 3. Templates

### 3.1 Inventario: un solo archivo

Búsqueda exhaustiva de "comentario" en `app/templates/`: los únicos aciertos son `app/templates/tickets/detalle_modal.py` (el bloque de comentarios y la auditoría) y dos coincidencias cosméticas en `app/templates/butler/index.html` (líneas 300 y 309: un `<option value="add_comentario">` y un ejemplo JSON de la API Butler) y una en `app/templates/tickets/nuevo_modal.html` (línea 226: `placeholder="Comentarios, contexto adicional o detalles relevantes…"` — es el placeholder de la **descripción** del ticket, no de comentarios).

**No existe ningún `.html` dedicado a comentarios.** El bloque se renderiza dentro de `DETALLE_TEMPLATE` (constante Jinja2 en `detalle_modal.py:32`), una string Python, no un archivo `.j2` del filesystem. Esto significa que Jinja2 se instancia directo (`from jinja2 import Template`, línea 25) sin el entorno de `app.main`, por lo que **los filtros custom registrados en `app/core/jinja_filters.py` NO están disponibles** dentro de este template (de ahí el `.strftime('%Y-%m-%d %H:%M')` inline en la línea 643 en lugar de un filtro).

### 3.2 Botón de la pestaña Comentarios — `detalle_modal.py` líneas 73-109

```html
    <!-- ============== TABS ============== -->
    {% set _active = active_tab or 'detalles' %}
    <div class="border-b border-slate-200 px-5 flex items-center gap-1 flex-shrink-0" role="tablist">
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'detalles' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="detalles">Detalles</button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'comentarios' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="comentarios">
        Comentarios
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ comentarios|length }}</span>
      </button>
      <button class="tab-btn px-3 py-2.5 text-xs font-medium border-b-2 {% if _active == 'adjuntos' %}border-indigo-600 text-indigo-700{% else %}border-transparent text-slate-500 hover:text-slate-700{% endif %}"
              data-tab="adjuntos">
        Adjuntos
        <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px]">{{ adjuntos|length }}</span>
      </button>
```

Existe, por tanto, la pestaña **Comentarios** y la pestaña **adjuntos**, ambas con contador tipo badge. El contador de comentarios usa `{{ comentarios|length }}` sobre la lista ya cargada en memoria (no un COUNT en BD), lo que hace que el badge sea consistente con el contenido solo porque ambos se renderizan en la misma pasada.

### 3.3 Implementación de las pestañas

Las 7 pestañas son `detalles`, `comentarios`, `adjuntos`, `checklist`, `etapas`, `trazabilidad`, `referencias` (botones en líneas 76-108, paneles con `data-panel` en las líneas 115, 625, 676, 830, 924, 1052, 1132). Cada panel se muestra/oculta server-side con la clase `hidden`, calculada por Jinja:

```html
      <div class="tab-panel {% if _active != 'comentarios' %}hidden{% endif %} p-5 space-y-3" data-panel="comentarios">
```

y la normalización del valor ocurre en `render_detalle_modal`, líneas 1532-1535:

```python
    # Normalizar active_tab a un valor seguro
    _tabs_validos = {"detalles", "comentarios", "adjuntos", "checklist", "etapas", "trazabilidad", "referencias"}
    if active_tab not in _tabs_validos:
        active_tab = "detalles"
```

El **toggle cliente** vive en `app/static/js/kanban.js` líneas 648-686, dentro de `initDetailModal()`, con delegación de eventos sobre `document.body` (el comentario en las líneas 643-647 explica por qué: el modal se inserta vía `innerHTML` y los `<script>` inline no se ejecutan):

```javascript
    // === TABS (click en .tab-btn) ===
    document.body.addEventListener('click', (e) => {
      const tabBtn = e.target.closest('.tab-btn');
      if (!tabBtn) return;
      // Buscar el modal raíz más cercano
      const modal = tabBtn.closest('[data-modal]');
      if (!modal) return;
      const target = tabBtn.dataset.tab;
      if (!target) return;

      // Marcar el tab activo en el propio modal (data-active-tab)
      modal.dataset.activeTab = target;

      // Actualizar todos los inputs hidden name="active_tab" en formularios
      // del modal para que, al hacer POST, el backend sepa qué tab mostrar.
      modal.querySelectorAll('input[name="active_tab"]').forEach((inp) => {
        inp.value = target;
      });
      ...
      modal.querySelectorAll('.tab-panel').forEach((p) => {
        if (p.dataset.panel === target) {
          p.classList.remove('hidden');
        } else {
          p.classList.add('hidden');
        }
      });
    });
```

Este detalle es el que hace posible el contrato `active_tab`: al cambiar de pestaña, el JS reescribe **todos** los `input[name="active_tab"]` del modal, de modo que el siguiente POST (incluido el de comentarios) devuelve el modal con la pestaña correcta visible.

### 3.4 Bloque de comentarios — HTML exacto, `detalle_modal.py` líneas 624-673

```html
      <!-- Tab: Comentarios -->
      <div class="tab-panel {% if _active != 'comentarios' %}hidden{% endif %} p-5 space-y-3" data-panel="comentarios">
        <!-- Listado -->
        <div class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
          {% if comentarios %}
            {% for c in comentarios %}
              {% set nc = (c.usuario.nombre_completo if c.usuario else '') %}
              {% set ini = (nc.split(' ')[:2]|map('first')|join|upper) if nc else '?' %}
              <div class="rounded-lg border border-slate-200 bg-slate-50/40 p-3">
                <div class="flex items-center justify-between mb-1">
                  <div class="flex items-center gap-1.5">
                    <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-semibold" title="{{ nc or 'Anónimo' }}">
                      {{ ini }}
                    </span>
                    <span class="text-xs font-medium text-slate-700">{{ nc or 'Anónimo' }}</span>
                    {% if c.es_interno %}
                      <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-semibold">INTERNO</span>
                    {% endif %}
                  </div>
                  <span class="text-[10px] text-slate-400">{{ c.created_at.strftime('%Y-%m-%d %H:%M') if c.created_at else '' }}</span>
                </div>
                <p class="text-xs text-slate-700 whitespace-pre-wrap">{{ c.texto }}</p>
              </div>
            {% endfor %}
          {% else %}
            <div class="text-center text-xs text-slate-400 italic py-6">No hay comentarios aún.</div>
          {% endif %}
        </div>

        <!-- Form nuevo comentario -->
        <form hx-post="/api/v1/tickets/{{ ticket.id }}/comentarios"
              hx-target="#modal-root" hx-swap="innerHTML"
              class="pt-3 border-t border-slate-100 space-y-2">
          <input type="hidden" name="active_tab" value="comentarios">
          <textarea name="texto" rows="3" required
                    placeholder="Escribe un comentario..."
                    class="w-full text-sm border border-slate-300 rounded-md px-3 py-2 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"></textarea>
          <div class="flex items-center justify-between">
            <label class="inline-flex items-center gap-1.5 text-[11px] text-slate-600">
              <input type="checkbox" name="es_interno" value="true"
                     class="h-3 w-3 text-indigo-600 focus:ring-indigo-500">
              Marcar como comentario interno
            </label>
            <button type="submit"
                    class="px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
              Agregar comentario
            </button>
          </div>
        </form>
      </div>
```

### 3.5 Inventario exacto de atributos HTMX del bloque

| Elemento | Atributo | Valor |
|---|---|---|
| `<form>` (línea 654) | `hx-post` | `/api/v1/tickets/{{ ticket.id }}/comentarios` |
| `<form>` (línea 655) | `hx-target` | `#modal-root` |
| `<form>` (línea 655) | `hx-swap` | `innerHTML` |
| `<form>` (línea 655) | `class` | `pt-3 border-t border-slate-100 space-y-2` |

Atributos que **no** están presentes en el bloque (y por tanto no existen): `hx-get`, `hx-vals`, `hx-confirm`, `hx-target` granular sobre la lista, `hx-trigger`, `hx-indicator`, `hx-swap-oob`, `hx-boost`. **La lista de comentarios no es un target independiente**: no hay ningún `hx-get` que la recargue; se regenera exclusivamente como parte del modal completo. Tampoco hay `maxlength` en el `<textarea>`, ni contador de caracteres, ni `hx-indicator` (sin spinner durante el envío).

### 3.6 Elementos ausentes del bloque de comentarios

En las líneas 624-673 **no existe**: botón de editar, botón de eliminar (el `DELETE` del backend no tiene UI), indicador de "editado",Expandir `texto_original`, reacciones emoji, menciones resueltas/resaltadas, referencias a otros tickets, adjuntos al comentario, ordenación o paginación de la lista, ni filtro "solo internos". La lista es un `max-h-72 overflow-y-auto` (18rem) con scroll interno: el límite visual es CSS, no de paginación.

### 3.7 JavaScript inline

**No hay JavaScript inline en el bloque de comentarios.** El único `<script>` inline del template (líneas 1315-1454, cerrado con `</script>` en 1454) pertenece exclusivamente a la pestaña de Referencias —autocompletar con `data-ticket-id`, apertura/cierre del dropdown, limpieza de selección en `input` (líneas 1436-1445)— y su comentario de cabecera (línea 1315) lo declara como "delegado, sin colisiones con otros tabs".

Para el bloque de comentarios, el único JS que interviene está fuera del template:
- `app/static/js/kanban.js` líneas 648-686: toggle de pestañas (§3.3).
- `app/static/js/htmx-events.js` líneas 275-276: mapeo de `HX-Trigger` a toasts:
  ```javascript
      'comentario-creado':   { msg: 'Comentario agregado correctamente',         type: 'success' },
      'comentario-eliminado':{ msg: 'Comentario eliminado',                      type: 'info' },
  ```
- `app/static/js/htmx-fallback.js`: **cero** menciones de comentarios.

### 3.8 Firma de la función de render

`app/templates/tickets/detalle_modal.py` líneas 1462-1553. La firma completa:

```python
def render_detalle_modal(
    ticket,
    estados: Iterable,
    comentarios: Iterable,
    adjuntos: Iterable,
    checklists: Iterable,
    auditorias: Iterable = (),
    usuario=None,
    ultima_modificacion: str = "",
    active_tab: str = "detalles",
    usuarios: Iterable = (),
    etiquetas_disponibles: Iterable = (),
    campos_personalizados: Iterable = (),
    etapas: Iterable = (),
    catalogo_etapas: Iterable = (),
    referencias: Iterable = (),
    tipos_referencia: Iterable = (),
) -> str:
```

`comentarios` es un parámetro **posicional y obligatorio** (tercero), sin default: cualquier llamada nueva debe pasarlo. El cuerpo final (líneas 1536-1553) hace `comentarios=list(comentarios)` antes de renderizar, es decir, el template **consume la lista completa ya materializada en memoria** (no hay `selectinload` ni paginación).

### 3.9 Auditoría de comentarios en la UI

La pestaña Trazabilidad (líneas 1051-1129) es el único otro lugar donde los comentarios aparecen en pantalla, a través de `Auditoria.comentario` (columna `Text` en `app/models/auditoria.py:38`) y de los badges `COMENTARIO_CREADO` / `COMENTARIO_ELIMINADO` (líneas 1067-1068 y 1082 del template; líneas 1143-1144 de `tickets.py`). No es parte del subsistema de comentarios, pero es el mecanismo de trazabilidad que las nuevas features querrán reutilizar.

---

## 4. DTOs / Schemas

Ubicación: **`app/schemas/features.py`**, sección "COMENTARIOS", líneas 98-137. Texto literal:

```python
# ==========================================
# COMENTARIOS
# ==========================================
class ComentarioBase(BaseModel):
    texto: str = Field(..., min_length=1, max_length=5000)
    es_interno: bool = False


class ComentarioCreate(ComentarioBase):
    pass


class ComentarioUpdate(BaseModel):
    texto: str = Field(..., min_length=1, max_length=5000)


class MencionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usuario_id: int
    notificado: int


class ComentarioRead(ComentarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    usuario_id: int
    editado: bool
    texto_original: Optional[str] = None
    menciones: List[MencionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None


class ComentarioReadWithAuthor(ComentarioRead):
    """Comentario con datos del autor para mostrar en UI."""
    autor_nombre: Optional[str] = None
    autor_username: Optional[str] = None
    autor_rol: Optional[str] = None
```

Detalle campo por campo:

| Schema | Campo | Tipo | Restricciones | Default |
|---|---|---|---|---|
| `ComentarioBase` (101-103) | `texto` | `str` | `min_length=1`, **`max_length=5000`** | — (requerido) |
| `ComentarioBase` | `es_interno` | `bool` | — | `False` |
| `ComentarioCreate` (106-107) | — | — | hereda todo `ComentarioBase` | — |
| `ComentarioUpdate` (110-111) | `texto` | `str` | `min_length=1`, `max_length=5000` | requerido |
| `MencionRead` (114-118) | `id` / `usuario_id` | `int` | `from_attributes` | — |
| `MencionRead` | `notificado` | `int` | — | — |
| `ComentarioRead` (121-130) | `id`, `ticket_id`, `usuario_id` | `int` | `from_attributes` | — |
| `ComentarioRead` | `editado` | `bool` | — | — |
| `ComentarioRead` | `texto_original` | `Optional[str]` | — | `None` |
| `ComentarioRead` | `menciones` | `List[MencionRead]` | — | `[]` |
| `ComentarioRead` | `created_at` | `datetime` | — | — |
| `ComentarioRead` | `updated_at` | `Optional[datetime]` | — | `None` |
| `ComentarioReadWithAuthor` (133-137) | `autor_nombre` / `autor_username` / `autor_rol` | `Optional[str]` | — | `None` |

Anomalías verificadas en el uso de estos DTOs:

1. **`ComentarioUpdate` está muerto**: se exporta en `app/schemas/__init__.py` (líneas 11 y 41) pero ningún endpoint lo importa. El `PATCH` usa `ComentarioCreate`.
2. **`ComentarioUpdate` no tiene `es_interno`**, mientras que `ComentarioCreate` sí. Con el uso actual (`PATCH` con `ComentarioCreate`) es posible mandar `es_interno` en el body de edición, pero el endpoint solo lee `datos.texto` y lo ignora: el cambio es silencioso.
3. **`ComentarioReadWithAuthor` nunca se puebla**: los tres campos `autor_*` no coinciden con ningún atributo del modelo y nadie construye este schema en el código. El detalle JSON real se arma a mano en `features.py` líneas 1236-1250 con `"autor": usuario_dict(c.usuario)` (un dict anidado, no campos planos).
4. `ComentarioRead` **no expone el autor**: quien llama a la API JSON tiene `usuario_id` pero debe hacer un JOIN aparte para obtener el nombre. `TicketDetalleRead` (`features.py` líneas 253-282) declara `comentarios: List[ComentarioReadWithAuthor]` en su línea 277, otro consumidor no cableado.

Exports en `app/schemas/__init__.py` línea 11 (import) y línea 41 (`__all__`):

```python
    ComentarioBase, ComentarioCreate, ComentarioUpdate, ComentarioRead, ComentarioReadWithAuthor,
```

`TicketDetalleRead` (líneas 253-282) es el schema agregado que incluye `comentarios: List[ComentarioReadWithAuthor]` (línea 277) y `total_comentarios: int = 0` (línea 279).

---

## 5. Referenciado entre comentarios

### 5.1 Respuesta corta

**No existe ningún mecanismo de referencia entre comentarios.** Un comentario solo se relaciona con (a) su ticket vía `ticket_id`, (b) su autor vía `usuario_id`, y (c) los usuarios mencionados vía la tabla `menciones_usuario`. No hay `comentario_id` autorreferencial, ni tabla puente, ni campo de texto parseado para referencias cruzadas.

### 5.2 Parser `#ID`: **no existe**

Búsqueda de regex con `#` en todo `app/**/*.py` (excluyendo `__pycache__`): **cero coincidencias**. No hay ningún `re.findall(r'#(\d+)')`, ni `#ticket`, ni `parsear_referencias`, ni post-procesado del `texto` al guardar. Si un usuario escribe `#42` en un comentario, queda como texto plano inerte.

### 5.3 Parser `@mención`: existe, es simple y está duplicado

Hay **dos implementaciones independientes** de la misma extracción:

1. `Comentario.extraer_menciones()` — `app/models/comentario.py` líneas 41-44 (método de instancia):
   ```python
   def extraer_menciones(self) -> list:
       """Extrae los usernames mencionados con @ del texto del comentario."""
       patron = r'@(\w+)'
       return list(set(re.findall(patron, self.texto)))
   ```
2. `NotificacionService.extraer_menciones()` — `app/services/trello_service.py` líneas 94-98 (staticmethod):
   ```python
    @staticmethod
    def extraer_menciones(texto: str) -> List[str]:
        """Extrae usernames mencionados con @ del texto."""
        patron = r'@(\w+)'
        return list(set(re.findall(patron, texto or "")))
   ```

Misma regex, misma semántica (`\w+`, dedup por `set`), misma limitación: matchea prefijos de email y cualquier `@palabra` en mitad de un texto más largo.

Flujo real de una mención: `POST /tickets/{id}/comentarios` → `ComentarioService.crear` → `db.flush()` (necesario para tener `com.id`) → `extraer_menciones()` → `SELECT Usuario WHERE username IN (...)` → un `MencionUsuario(notificado=0)` por usuario encontrado → `db.commit()`. Los usernames que no existen como `Usuario.username` se descartan silenciosamente.

**Las menciones nunca generan notificación.** Existe `NotificacionService.notificar_mencion()` (`trello_service.py` líneas 371-393), que crearía notificaciones con título `f"@{comentario.usuario.username} te mencionó"` y URL `f"/tickets/{comentario.ticket_id}#comentario-{comentario.id}"`, y existe `ComentarioService.marcar_mencion_notificada()` (`features_service.py` líneas 233-239) que pondría `notificado=1`. **Verificado por búsqueda en todo `app/`: ninguna de las dos funciones es llamada por ningún sitio.** Son código muerto: la tabla `menciones_usuario` se puebla pero la columna `notificado` queda siempre en `0`.

Además, la URL que usaría `notificar_mencion` apunta al ancla `#comentario-{id}`, pero **el bloque de comentarios del template no emite ningún `id="comentario-..."` en cada tarjeta** (líneas 632-646: el `<div>` raíz no tiene `id`). El enlace profundo no funcionaría aunque se activaran las notificaciones.

### 5.4 Referencias ticket↔ticket: `TicketReferencia` (FEATURE 5) — el modelo a imitar

`app/models/ticket_referencia.py` (177 líneas) es un modelo m2m autorreferencial sobre `tickets`, con enum de tipos (líneas 51-66):

```python
class TipoReferencia(str, enum.Enum):
    RELACIONADO = "relacionado"
    DUPLICADO = "duplicado"
    PADRE = "padre"
    HIJO = "hijo"
    BLOQUEA = "bloquea"
    BLOQUEADO_POR = "bloqueado_por"
```

con mapeo inverso (líneas 73-80) para evitar duplicados semánticos:

```python
TIPO_INVERSO = {
    TipoReferencia.RELACIONADO: TipoReferencia.RELACIONADO,
    TipoReferencia.DUPLICADO: TipoReferencia.DUPLICADO,
    TipoReferencia.PADRE: TipoReferencia.HIJO,
    TipoReferencia.HIJO: TipoReferencia.PADRE,
    TipoReferencia.BLOQUEA: TipoReferencia.BLOQUEADO_POR,
    TipoReferencia.BLOQUEADO_POR: TipoReferencia.BLOQUEA,
}
```

Campos (líneas 101-130): `id`, `ticket_origen_id` (FK CASCADE, index), `ticket_referenciado_id` (FK CASCADE, index), `tipo` (Enum nativo desactivado, `length=20`, default `RELACIONADO`), `nota` (Text nullable), `creado_por_id` (FK usuarios `SET NULL`), `created_at` (index). **Usa `Base` directo, no `TimestampMixin`** → no tiene `updated_at`.

Constraints (líneas 146-157), que son el mejor patrón disponible en el repo para una tabla puente:

```python
    __table_args__ = (
        UniqueConstraint(
            "ticket_origen_id", "ticket_referenciado_id", "tipo",
            name="uq_ref_orig_dest_tipo",
        ),
        CheckConstraint(
            "ticket_origen_id != ticket_referenciado_id",
            name="ck_ref_no_self_ref",
        ),
        Index("ix_ref_origen_tipo", "ticket_origen_id", "tipo"),
        Index("ix_ref_destino_tipo", "ticket_referenciado_id", "tipo"),
    )
```

Relaciones (líneas 133-143): `ticket_origen` y `ticket_referenciado` con `backref="referencias_salientes"` / `backref="referencias_entrantes"` — **no** hay un `Ticket.referencias` declarado en `ticket.py`; se crea por backref.

### 5.5 API de referencias — `app/api/v1/referencias.py`

Dos routers (líneas 35-38):
```python
router = APIRouter(prefix="/referencias", tags=["referencias-internas"])
# Segundo router para colgar el endpoint de autocompletar bajo ``/tickets``
# (mantiene coherencia con el prefijo REST estándar).
router_tickets = APIRouter(prefix="/tickets", tags=["referencias-internas"])
```

| Método | Path completo | Función (líneas) | Devuelve |
|---|---|---|---|
| POST | `/api/v1/tickets/{ticket_id}/referencias` | `agregar_referencia` (83-202) | `ReferenciaRead`, 201, JSON |
| GET | `/api/v1/tickets/{ticket_id}/referencias` | `listar_referencias_de_ticket` (205-222) | `List[ReferenciaRead]` JSON, bidireccional |
| GET | `/api/v1/tickets/{ticket_id}/referencias/resumen` | `resumen_referencias` (225-245) | dict con `total`/`salientes`/`entrantes`/`por_tipo` |
| DELETE | `/api/v1/referencias/{ref_id}` | `eliminar_referencia` (251-262) | `{"ok": True, "id": ref_id}` |
| GET | `/api/v1/referencias/tipos` | `listar_tipos_referencia` (265-270) | `List[TipoReferenciaCatalogo]` |
| GET | `/api/v1/tickets/buscar?q=&excluir=&limit=` | `buscar_tickets_autocompletar` (276-306) | **HTMX → HTML**, JSON → lista |

Los schemas locales (no en `app/schemas/`) están en el mismo archivo, líneas 44-77: `ReferenciaCreate` (`ticket_referenciado_id: int = Field(..., gt=0)`, `tipo: str` default `"relacionado"`, `nota: Optional[str] = Field(None, max_length=500)`), `ReferenciaRead`, `TicketBusquedaRead`, `TipoReferenciaCatalogo`.

Dos detalles de diseño muy relevantes para replicar en features de comentarios:

1. **Parser de body manual dual content-type** (líneas 105-130), idéntico en espíritu al de comentarios, pero mejor implementado: valida y devuelve errores de negocio (`{"codigo": ..., "mensaje": ...}`) con 409 para duplicados/auto-referencia (líneas 164-174) en vez del 422 genérico de Pydantic. Además **trunca** la nota en vez de rechazar: `if nota and len(nota) > 500: nota = nota[:500]` (líneas 152-153).
2. **Bifurcación HTMX/JSON en el mismo endpoint** (líneas 301-306), con un renderizador HTML propio `_render_search_results_html` (líneas 309-352) que emite `data-ticket-id` y `data-codigo-titulo` para que un listener delegado en el modal resuelva la selección. Este patrón es exactamente el que haría falta para un autocompletado `#ID` en comentarios.

El servicio `TicketReferenciaService` (`app/services/referencia_service.py`, 451 líneas) expone `agregar` (línea 68), `listar_para_ticket` (201, devuelve lista de dicts con `direccion` "saliente"/"entrante" y metadatos del ticket opuesto, usando doble alias del `Ticket.__table__`), `obtener` (300), `eliminar` (310), `buscar_tickets_para_autocompletar` (373), `tipos_validos` (434) y `tipo_inverso` (444). La excepción de dominio es `ReferenciaError(mensaje, codigo)` (línea 50).

La UI de referencias está implementada (pestaña 1132-1313 con su JS inline 1315-1454) y es el **mejor modelo a copiar** para cualquier UI de referencias dentro de comentarios.

### 5.6 Reacciones: soporte genérico ya existente

Endpoints en `app/api/v1/trello_features.py`:

```python
@router.post("/reacciones/toggle")
def toggle_reaccion(
    datos: ReaccionCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        resultado = ReaccionService(db).toggle(
            user.id, datos.tipo_objeto, datos.objeto_id, datos.emoji
        )
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
@router.get("/reacciones/{tipo_objeto}/{objeto_id}", response_model=List[ReaccionGrupo])
def listar_reacciones(
    tipo_objeto: str, objeto_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return ReaccionService(db).agrupar_por_emoji(tipo_objeto, objeto_id, user.id)
```
(líneas 356-380). El schema `ReaccionCreate` (`app/schemas/trello.py` líneas 132-135):
```python
class ReaccionCreate(BaseModel):
    tipo_objeto: str  # comentario | ticket
    objeto_id: int
    emoji: str = Field(..., max_length=16)
```
Estas rutas (`POST /api/v1/reacciones/toggle`, `GET /api/v1/reacciones/{tipo_objeto}/{objeto_id}`) **ya soportan comentarios** vía `tipo_objeto='comentario'`; falta únicamente la UI en el bloque de comentarios y una carga agrupada en el render del modal.

### 5.7 Automatizaciones sobre comentarios

`MotorAutomatizacion.disparar("ticket_comentado", ...)` (`features_service.py` líneas 614-653) es el gancho existente. La acción inversa `crear_comentario` (líneas 570-579) crea comentarios automáticos del Butler:

```python
            elif tipo == "crear_comentario":
                texto = params.get("texto", "🤖 [Butler] Acción automática")
                com = Comentario(
                    ticket_id=ticket.id,
                    usuario_id=params.get("usuario_id") or ticket.creador_id,
                    texto=texto,
                    es_interno=bool(params.get("es_interno", True)),
                )
                self.db.add(com)
                return "Comentario creado"
```

Nota: esta vía **omite `ComentarioService.crear`**, luego no procesa menciones ni emite auditoría. El catálogo de disparadores/acciones permitidos está en `app/models/automacion.py` línea 32. Además, `app/api/v1/butler.py` línea 27 expone un tipo de acciónlegacy `add_comentario` (distinto de `crear_comentario`), y `app/main.py` líneas 863-905 define el permiso `agregar_comentario` por rol.

---

## 6. Paginación y límites

### 6.1 Límite de longitud de texto

| Capa | Límite | ¿Activo? |
|---|---|---|
| Esquema Pydantic `ComentarioBase.texto` | `min_length=1, max_length=5000` | **Solo en `PATCH`** (usa `ComentarioCreate` como body) |
| Esquema `ComentarioUpdate.texto` | `min_length=1, max_length=5000` | No (schema sin uso) |
| `POST /tickets/{id}/comentarios` | Ninguno | **No** — parsea el body a mano (`features.py` 619-638) y solo valida `if not texto` |
| Modelo SQL `Comentario.texto` | `Text` sin cota | No |
| `<textarea name="texto">` | Ningún atributo `maxlength` | No |

Consecuencia: un POST puede insertar texto de longitud arbitraria. La unicidad de límites depende de qué ruta use el cliente, no del sistema.

### 6.2 Límite inferior

`min_length=1` en Pydantic no es efectivo en `POST` porque el parseo manual solo hace `.strip()` y valida `if not texto` (línea 640) — lo que sí cubre el caso "solo espacios", pero no aplica el `min_length` de Pydantic más allá de eso. En la UI, el atributo `required` del `<textarea>` (línea 658) cubre el caso vacío del lado cliente.

### 6.3 Paginación

**No existe paginación de comentarios en ninguna capa.** Verificado:

- `ComentarioService.listar_de_ticket` (líneas 179-183) termina en `.all()`, sin `limit` ni `offset`.
- Las 5 queries que alimentan el modal terminan en `.all()` sin `limit` (comparar con la query de auditoría, que sí usa `.limit(200)` en `tickets.py:381` y `features.py:107`: precedent existente para limitar).
- `render_detalle_modal` hace `comentarios=list(comentarios)` (línea 1539): materializa todo.
- El `GET /tickets/{id}/comentarios` acepta solo `incluir_internos: bool` como parámetro de consulta; no hay `limit`/`offset`/`page`.

El único control de volumen es visual: `max-h-72 overflow-y-auto` en el contenedor (línea 627), es decir, 18rem con scroll.

Existe un precedente de paginación en el mismo schema file para otros recursos: `FiltroTicket` (`app/schemas/features.py` líneas 189-190) declara `limite: int = Field(default=100, ge=1, le=500)` y `offset: int = Field(default=0, ge=0)`. Y `GET /api/v1/tickets/buscar` declara `limit: int = Query(15, ge=1, le=50)` (referencias.py línea 283).

### 6.4 Orden

Tres órdenes distintos conviven (ver §1.4): modal = `created_at.asc()`, API JSON = `created_at.desc()`, relación ORM = `created_at.desc()`. Ningún desempate por `id`, lo que hace el orden inestable para comentarios creados en el mismo microsegundo.

---

## 7. Checklist de verificación de hallazgos

| Afirmación | Verificación | Confianza |
|---|---|---|
| El CRUD completo existe (GET/POST/PATCH/DELETE) | Lectura directa `features.py:590-741` | Alta |
| El POST no aplica `max_length=5000` | Parseo manual líneas 619-638, sin schema | Alta |
| No hay paginación | `.all()` en las 6 ubicaciones revisadas | Alta |
| Los solicitantes ven comentarios internos en la UI | Ausencia de filtro `es_interno` en los 5 renderizadores + checkbox visible para todos | Alta |
| `DELETE` sin UI | Bloque 624-673 sin botones; grep de `comentarios/{` solo encuentra el backend | Alta |
| No hay parser `#ID` | Grep de regex con `#` en todo `app/**/*.py`: 0 resultados | Alta |
| `notificar_mencion` es código muerto | Grep de llamadas: solo su `def` | Alta |
| `ComentarioUpdate` sin uso | Se importa/exporta en `schemas/__init__.py`, ningún endpoint lo importa | Alta |
| `ComentarioReadWithAuthor` sin poblar | Sus 3 campos no existen en el modelo; el JSON real usa `"autor": {...}` | Alta |
| El anchor `#comentario-{id}` no existe en el DOM | Los `<div>` de comentario (líneas 632-646) no emiten `id` | Alta |
| `kanban.py` no toca comentarios | Archivo de 79 líneas leído completo | Alta |
| `referencias.py` no toca comentarios | 352 líneas leídas; solo ticket↔ticket | Alta |

---

## 8. Mapa de puntos de extensión para 3 features nuevas

Semantizado por dónde tocar, no por feature, porque las 3 features compartirán los mismos puntos:

**Creación de comentario**: `ComentarioService.crear` (`features_service.py:185-211`) es el único funnel de creación con menciones; si se añade parseo de referencias ahí, hay que decidir si se duplica en la rama Butler (`features_service.py:570-579`) que lo bypasea.

**Renderizado del bloque**: `detalle_modal.py:624-673`. Para evitar tocar 5 sitios, la vía correcta es migrar los 4 renderizadores de `tickets.py` al helper `_render_detalle_modal_response` ya existente en `features.py:61-142`, y luego enrichecer `_render_detalle_modal_response` con los datos nuevos.

**Target HTMX granular**: hoy el único target es `#modal-root` (swap completo). Cualquier feature que quiera refrescar solo la lista de comentarios necesita un `id="comentarios-lista"` nuevo + un endpoint que renderice solo ese fragmento (patrón `_render_search_results_html`, `referencias.py:309-352`).

**Carga de datos relacionados**: hoy el render no hace `joinedload` de `Comentario.usuario` (rely on lazy load) ni de `Reaccion`; el único `joinedload` explícito está en `features.py:1174-1175` (endpoint JSON detalle). Un `joinedload(Comentario.usuario)` en el helper evitaría N+1 al añadir autorización por comentario en el template.

**Escaleras de extensión ya disponibles sin escribir código nuevo**: `Reaccion` + `/reacciones/toggle` (§5.6), `TicketReferenciaService` + `/tickets/buscar` autocompletar (§5.5), `registrar_auditoria` (ya usado en crear/eliminar comentario), `MotorAutomatizacion.disparar("ticket_comentado")` (§5.7), y los `HX-Trigger` mapeados a toast en `htmx-events.js:275-276`.

---

## 9. Deuda técnica detectada (relevante para las features nuevas)

1. **Fuga de comentarios internos al rol SOLICITANTE en la UI** (`features.py:85-90`, `tickets.py:358-363`, `629-634`, `875-880`, `1066-1069`). El filtro existe solo en `features.py:597-599` para la ruta JSON.
2. **Sin control de longitud en creación** (§6.1) y **sin paginación** (§6.3): un ticket con 10.000 comentarios carga los 10.000 en cada POST de cualquier otro tab, porque cada acción re-renderiza el modal completo.
3. **Autorización de escritura laxa**: `POST` no verifica que el usuario tenga relación con el ticket; un `SOLICITANTE` autenticado puede comentar en cualquier ticket (y marcarlo `es_interno`).
4. **Menciones notificadas nunca** (§5.3) y **anchor inexistente** (§5.3): el subsistema de menciones está a medio implementar.
5. **Query duplicada 5 veces** sin filtro común y sin `joinedload` (§2.4).
6. **Imposibilidad de editar desde la UI** aunque el endpoint existe con control de permisos y preservation de `texto_original`.
7. **Reacciones a comentarios sin UI ni carga** pese a que el modelo y los endpoints las soportan.

---

## 10. Archivos Involvedrados (índice)

| Ruta | Rol en el subsistema |
|---|---|
| `app/models/comentario.py` (71 L) | Modelos `Comentario` y `MencionUsuario`, regex de menciones |
| `app/db/base.py` (24 L) | `TimestampMixin` (`created_at`, `updated_at`) |
| `app/models/ticket.py` L257-273 | Relación inversa `Ticket.comentarios` + `total_comentarios` |
| `app/models/usuario.py` L20-31 | Datos de autor (`username`, `nombre_completo`, `rol`) |
| `app/models/watch.py` L43-70 | `Reaccion` (soporta `tipo_objeto='comentario'`) |
| `app/models/__init__.py` L9, L44 | Registro de modelos |
| `app/schemas/features.py` L98-137 | DTOs de comentarios + menciones |
| `app/schemas/__init__.py` L11, L41 | Export de DTOs |
| `app/schemas/trello.py` L132-135 | `ReaccionCreate` |
| `app/api/v1/features.py` L61-142, 587-741, 1159-1264 | Helper de render, CRUD de comentarios, detalle JSON |
| `app/api/v1/router.py` L39-44 | Orden de registro de routers |
| `app/api/v1/deps.py` L31-110 | `get_current_user`, `require_role`, `require_admin` |
| `app/api/v1/tickets.py` L332-438, 531-700, 712-950, 952-1186 | 4 renderizadores del modal con comentarios |
| `app/services/features_service.py` L172-239, 570-579, 614-653 | `ComentarioService`, acción Butler, motor de reglas |
| `app/services/trello_service.py` L94-98, 371-393 | Parser duplicado + `notificar_mencion` (código muerto) |
| `app/models/ticket_referencia.py` (177 L) | Modelo de referencia a imitar |
| `app/api/v1/referencias.py` (352 L) | Patrón de endpoints HTMX/JSON duales + autocompletar |
| `app/services/referencia_service.py` L201-245 | Listado bidireccional reutilizable |
| `app/templates/tickets/detalle_modal.py` L32, 73-109, 624-673, 1315-1454, 1462-1553 | Template del modal, bloque de comentarios, JS de referencias, API de render |
| `app/static/js/kanban.js` L648-686 | Toggle de pestañas + sincronización de `active_tab` |
| `app/static/js/htmx-events.js` L275-276 | Toasts de `comentario-creado` / `comentario-eliminado` |
| `app/api/v1/trello_features.py` L356-380 | Endpoints de reacciones (genéricos, ya soportan comentarios) |
| `app/db/init_db.py` L29, 315-326 | Seed de comentarios demo |

---

*Fin del informe. Ningún archivo del repositorio fue modificado durante esta investigación.*