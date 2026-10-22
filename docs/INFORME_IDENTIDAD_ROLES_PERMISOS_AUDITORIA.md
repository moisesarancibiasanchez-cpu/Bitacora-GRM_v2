# Bitácora GRM v2 — Subsistema de Identidad, Roles, Permisos y Auditoría

**Informe técnico de investigación (solo lectura, sin cambios de código)**
Fecha de análisis: 2026-10-21 · Repositorio: `/workspace` · Paquete: `/workspace/app`

---

## Resumen ejecutivo

El subsistema de identidad descansa sobre una única columna `Enum` (`Usuario.rol`) y **no existe ninguna propiedad ni campo `es_admin`**. El concepto de "administrador" se materializa exclusivamente como comparación contra el valor del enum, y esa comparación aparece repartida en **al menos seis sintaxis distintas** a lo largo del código (comparación directa de enum, comparación de string normalizada, pertenencia a tupla, comparación en Jinja2, comparación en JavaScript y dependencia `Depends(require_admin)`). No hay una forma canónica única.

El hallazgo más relevante para quien hereda el sistema es que **existen dos dependencias de usuario actual totalmente independientes y con comportamientos distintos**: `get_current_user` (API, acepta Bearer + cookie + header de prueba, lanza 401) y `_require_session_or_redirect` (páginas HTML, solo cookie, redirige 302). Confundirlas produce errores de autorización difíciles de detectar.

El tercer punto de riesgo es que **la "matriz de roles × funciones" es documentación, no un mecanismo de aplicación**: no existe tabla `RolFuncion` ni consulta de permisos en base de datos. La matriz vive hardcodeada en `app/main.py:882-912` y se renderiza en una pantalla de referencia. La única lógica de permisos realmente ejecutada es `Usuario.tiene_permiso_para()`, invocada en apenas dos rutas y únicamente para la acción `"cambiar_estado"`.

---

## 1. Modelo Usuario — `app/models/usuario.py` (68 líneas, leído completo)

### 1.1 Campos (líneas 20-45)

La clase `Usuario` hereda de `Base, TimestampMixin`:

| Línea | Campo | Tipo / declaración |
|---|---|---|
| 24 | `id` | `Integer`, PK, autoincrement |
| 25 | `username` | `String(64)`, unique, not null, index |
| 26 | `email` | `String(120)`, unique, not null, index |
| 27 | `nombre_completo` | `String(200)`, not null |
| 28 | `hashed_password` | `String(255)`, not null |
| 29 | `rol` | `Enum(RolUsuario)`, not null, default `SOLICITANTE`, index |
| 30 | `is_active` | `Boolean`, default `True`, not null |
| 31 | `departamento` | `String(120)`, nullable |

**Timestamps** — heredados de `TimestampMixin` en `app/db/base.py:14-24`:

```python
class TimestampMixin:
    """Mixin con timestamps automáticos."""
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
```

Sí hay timestamps de creación y actualización, en UTC naive.

**Campo activo**: se llama **`is_active`** (no `activo`), línea 30.

### 1.2 Cómo se representa el ROL

Es un **enum de Python persistido como `Enum` nativo de SQLAlchemy** — ni string libre, ni tabla de roles, ni lista de booleanos:

```python
# app/models/usuario.py:11-17
class RolUsuario(str, enum.Enum):
    """Roles disponibles con permisos predefinidos."""
    ADMINISTRADOR = "administrador"
    AGENTE_SENIOR = "agente_senior"
    AGENTE = "agente"
    SOLICITANTE = "solicitante"
    OBSERVADOR = "observador"
```

Al heredar de `str`, `RolUsuario.ADMINISTRADOR == "administrador"` es `True` en Python. Esto explica la coexistencia de las dos familias de comparaciones documentadas en §1.4: unas comparan contra el miembro del enum y otras contra el string crudo.

### 1.3 Cómo se determina si un usuario es ADMINISTRADOR

**No existe ningún helper.** Concretamente, en `app/models/usuario.py`:

- **NO** existe un campo `es_admin` ni `is_admin`.
- **NO** existe una propiedad `@property def es_admin`.
- **NO** existe una función module-level `es_admin(usuario)`.

El único método de permisos es `tiene_permiso_para`, y **no es la vía usada para admin**: su diccionario no tiene una clave `es_admin`, y la comprobación de administrador en todo el código se hace por comparación directa de `usuario.rol`.

```python
# app/models/usuario.py:47-64
    def tiene_permiso_para(self, accion: str) -> bool:
        """Verifica si el rol del usuario permite una acción dada."""
        permisos = {
            RolUsuario.ADMINISTRADOR: {"*"},
            RolUsuario.AGENTE_SENIOR: {
                "cambiar_estado", "reasignar", "cerrar_ticket",
                "editar_ticket", "ver_auditoria", "agregar_comentario",
            },
            RolUsuario.AGENTE: {
                "cambiar_estado", "agregar_comentario", "editar_ticket",
            },
            RolUsuario.SOLICITANTE: {"crear_ticket", "agregar_comentario"},
            RolUsuario.OBSERVADOR: {"ver_auditoria"},
        }
        return (
            "*" in permisos.get(self.rol, set())
            or accion in permisos.get(self.rol, set())
        )
```

### 1.4 TODAS las variantes de comprobación admin en el codebase

`RolUsuario.ADMINISTRADOR` aparece **57 veces**. Se agrupan en seis familias:

**Variante A — comparación directa contra el enum (la más extendida).** Es la forma dominante y la recomendada:

```python
# app/api/v1/deps.py:105
    if usuario.rol != RolUsuario.ADMINISTRADOR:

# app/api/v1/usuarios.py:46, 568, 647, 703, 722
    if usuario.rol != RolUsuario.ADMINISTRADOR:

# app/api/v1/import_export.py:40
    if usuario.rol != RolUsuario.ADMINISTRADOR:

# app/api/v1/trello_features.py:107, 125, 141, 173, 202, 219, 233, 250, 274, 310
    if espacio.propietario_id != user.id and user.rol != RolUsuario.ADMINISTRADOR:

# app/api/v1/features.py:690, 722, 937
    if com.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):

# app/main.py:825
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        return RedirectResponse(url="/kanban")
```

**Variante B — comparación contra string normalizado.** Convierte el enum a texto y compara; equivalente por la herencia de `str`, pero frágil frente a cambios de valor:

```python
# app/api/v1/estados.py:78-80 (repetido en 243, 581, 805, 944, 1126)
        usuario.rol.value if hasattr(usuario.rol, "value") else usuario.rol
    ...
    if str(rol_legible).lower() != "administrador":

# app/api/v1/reporte_entregas.py:61-65
    ...
    if rol.lower() != "administrador":

# app/main.py:2193
    if (rol or "").lower() != "administrador":
```

**Variante C — pertenencia a un conjunto de strings:**

```python
# app/api/v1/backups.py:111-112
    rol = (usuario.rol.value if hasattr(usuario.rol, "value") else str(usuario.rol)).lower()
    if rol not in {"administrador", "agente_senior"}:
```

**Variante D — comparación en plantilla Jinja2.** Requiere que el rol siga siendo enum (`.value`); si fuera string plano, fallaría:

```jinja
{# app/templates/base.html:117 #}
            {% if usuario and usuario.rol.value == 'administrador' %}

{# app/templates/base.html:135 #}
            {% if dev_inbox_enabled() and usuario and usuario.rol.value == 'administrador' %}

{# app/templates/vistas/gantt.html:264 #}
    {% if usuario and usuario.rol.value == 'administrador' %}

{# app/templates/kanban/index.html:229 — variante defensiva #}
      {% if usuario and (usuario.rol.value if usuario.rol is defined else usuario.rol) == 'administrador' %}
```

En `app/templates/tickets/detalle_modal.py:694` se encuentra la comprobación más defensiva del proyecto (intenta cubrir rol enum y rol string a la vez):

```jinja
{% set _es_admin  = (usuario is not none and usuario.rol is defined and (usuario.rol.value if usuario.rol is defined and usuario.rol is not string else usuario.rol) == 'administrador') %}
```

**Variante E — comparación en JavaScript del lado del cliente**, a partir de `window.CURRENT_USER_ROL` inyectado por la plantilla:

```javascript
// app/templates/kanban/index.html:395
    const esAdmin = (window.CURRENT_USER_ROL || '').toLowerCase() === 'administrador';
```

**Variante F — dependencia declarativa de FastAPI** (ver §2.3):

```python
dependencies=[Depends(require_admin)]          # app/api/v1/admin_uat.py:41
_: Usuario = Depends(require_admin)             # app/api/v1/dev_inbox.py:87
```

**Conclusión sobre cuál es la canónica:** no hay una única forma canónica. La **Variante A** (`usuario.rol == RolUsuario.ADMINISTRADOR`) es la mayoritaria y la única que no depende de conversiones de string. La **Variante D** es peligrosa porque `usuario.rol.value` lanza `AttributeError` si `rol` fuera un string; la **Variante E** es puramente client-side y no debe usarse como control de acceso.

---

## 2. Dependencias de autenticación / autorización

### 2.1 Corrección importante: `dependencias.py` NO es el archivo de dependencias de auth

El pedido mencionaba `app/api/v1/deps.py` y `app/api/v1/dependencias.py` como si ambos fueran archivos de dependencias. **Solo `deps.py` lo es.** `app/api/v1/dependencias.py` es un router APIRouter del módulo funcional de dependencias Gantt / importación MS Project:

```python
# app/api/v1/dependencias.py:39
router = APIRouter(prefix="/dependencias", tags=["dependencias"])
```

Su única pieza de autorización es un guard local:

```python
# app/api/v1/dependencias.py:96-102
def _requiere_admin_o_agente_senior(usuario: Usuario) -> None:
    """Sólo Admin y Agente Senior pueden crear/eliminar dependencias."""
    if usuario.rol not in (RolUsuario.ADMINISTRADOR, RolUsuario.AGENTE_SENIOR):
        raise HTTPException(
            status_code=403,
            detail="Solo Administrador o Agente Senior pueden gestionar dependencias.",
        )
```

### 2.2 `app/api/v1/deps.py` — todas las dependencias (111 líneas, leído completo)

**Configuración del esquema** (líneas 24-28):

```python
security = HTTPBearer(auto_error=False)

# Solo permitir el bypass de X-User-Id si se activa EXPLÍCITAMENTE
# mediante variable de entorno. Por defecto está cerrado.
ALLOW_XUSER_HEADER = os.getenv("ALLOW_XUSER_HEADER", "false").lower() == "true"
```

**Dependencia 1 — `get_current_user`** (firma exacta, líneas 31-35):

```python
def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Usuario:
```

Cadena de resolución de identidad (líneas 43-88), en orden de prioridad:

1. **Header `Authorization: Bearer <jwt>`** — decodifica el JWT y toma `payload["sub"]` como id (líneas 45-52).
2. **Cookie `access_token`** — mismo procedimiento (líneas 54-63).
3. **Header `X-User-Id`** — **deshabilitado por defecto**; solo si `ALLOW_XUSER_HEADER=true` (líneas 65-72).

```python
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Inicie sesión o proporcione credenciales válidas.",
        )

    usuario = db.query(Usuario).filter(
        Usuario.id == user_id, Usuario.is_active == True  # noqa: E712
    ).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
        )
    return usuario
```

Puntos clave: el filtro incluye `is_active == True`, por lo que **desactivar un usuario corta el acceso inmediatamente** aunque su JWT siga vigente. El JWT solo transporta `sub` (id); el rol **nunca** se lee del token para autorizar — siempre se relee de la base de datos.

**Dependencia 2 — `require_role`** (fábrica de dependencias, líneas 91-100):

```python
def require_role(*roles: RolUsuario):
    """Fabrica un dependency que exige uno de los roles dados."""
    def _checker(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requiere rol: {', '.join(r.value for r in roles)}",
            )
        return usuario
    return _checker
```

**Dependencia 3 — `require_admin`** (líneas 103-110):

```python
def require_admin(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency que exige rol Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere rol Administrador.",
        )
    return usuario
```

Uso observado: `Depends(require_admin)` en `admin_uat.py` (5), `dev_inbox.py` (9), `etapas.py` (3), `migraciones.py` (4); `Depends(require_role(RolUsuario.ADMINISTRADOR))` en `catalogos.py:32` y `estados.py:44,394`.

**Dependencia 4 — `get_db`**, definida en `app/db/session.py:24-30` (generador con cierre en `finally`). Nota: `dependencias.py:27` la importa desde `app.api.v1.deps`, que a su vez la reexporta.

### 2.3 El segundo (y divergente) mecanismo: páginas HTML en `main.py`

Las páginas server-rendered **no** usan `get_current_user`. Tienen su propio par de helpers:

```python
# app/main.py:127-155
def _get_usuario_actual(request: Request):
    """Resuelve el usuario actual a partir ÚNICAMENTE de la cookie ``access_token``.

    Retorna el ``Usuario`` autenticado o ``None`` si no hay sesión válida.
    NO hay fallback a 'primer admin' ni a 'modo demo' por seguridad:
    un usuario sin sesión debe ser redirigido a /auth/login.
    """
    ...
    token = request.cookies.get("access_token")
    if not token:
        return None
    ...
        return (
            db.query(Usuario)
            .filter(Usuario.id == uid, Usuario.is_active == True)  # noqa: E712
            .first()
        )
```

```python
# app/main.py:158-163
def _require_session_or_redirect(request: Request):
    """Devuelve (usuario, None) si hay sesión, o (None, redirect a /auth/login)."""
    usuario = _get_usuario_actual(request)
    if usuario is None:
        return None, RedirectResponse(url="/auth/login", status_code=302)
    return usuario, None
```

Patrón de uso uniforme en ~30 rutas de `main.py`:

```python
    usuario, redirect = _require_session_or_redirect(request)
    if redirect is not None:
        return redirect
```

### 2.4 Tabla comparativa de ambos mecanismos

| Aspecto | `get_current_user` (API) | `_require_session_or_redirect` (HTML) |
|---|---|---|
| Ubicación | `app/api/v1/deps.py:31` | `app/main.py:158` |
| Bearer JWT | Sí (prioridad 1) | **No** |
| Cookie `access_token` | Sí (prioridad 2) | Sí (único modo) |
| Header `X-User-Id` | Solo si `ALLOW_XUSER_HEADER=true` | **Nunca** |
| Sin sesión | `HTTPException 401` | `RedirectResponse 302` a `/auth/login` |
| Sesión de BD | `Depends(get_db)` | `SessionLocal()` propia con `finally: db.close()` |
| Filtra `is_active` | Sí | Sí |

**Respuesta directa a "¿qué pasa si no hay sesión?"**: en la API es **401** con el detalle `"No autenticado. Inicie sesión o proporcione credenciales válidas."`; en las páginas HTML es un **redireccionamiento 302** a `/auth/login`. Rol insuficiente es siempre **403**.

### 2.5 Emisión de la sesión

```python
# app/api/v1/auth.py:60-71
def _set_session_cookie(response: Response, user_id: int, rol: str) -> str:
    """Genera JWT, lo pone en cookie y devuelve el token."""
    token = create_access_token({"sub": str(user_id), "rol": rol})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 8,  # 8h
        samesite="lax",
        path="/",
    )
    return token
```

El claim `rol` viaja en el JWT pero **no se usa para autorizar** (solo se relee en `auth.py` para respuestas de la API). La expiración del JWT es de 8 h (`settings.JWT_EXPIRATION_MINUTES = 60 * 8`, `config.py:44`), y la cookie tiene `max_age` de 8 h; ambasvey en `secure=False` implícito (no se establece el flag).

---

## 3. Sistema de roles y funciones

### 3.1 NO existe una tabla de roles × funciones

Búsqueda exhaustiva: **no existe** modelo `RolFuncion`, ni tabla `roles_funciones`, ni tabla de permisos. La carpeta `app/templates/roles_funciones/` contiene un único archivo (`index.html`). El único router asociado vive directamente en `main.py`:

```python
# app/main.py:835-846
@app.get("/roles-funciones", response_class=HTMLResponse)
async def roles_funciones_page(request: Request):
    """Matriz de roles y funciones disponibles.

    Muestra una tabla con:
    - Cada rol del sistema y sus funciones habilitadas.
    - La cantidad de usuarios activos en cada rol.
    - Una descripción legible de cada función.

    Visible para cualquier usuario con sesión activa (es una página
    de referencia sobre los permisos del sistema).
    """
```

**La matriz es un diccionario literal hardcodeado** dentro del handler (líneas 882-912), con el comentario que lo declara explícitamente:

```python
    # Matriz de permisos por rol (alineada con Usuario.tiene_permiso_para).
    # Usamos listas (no sets) porque Jinja2 no expone el builtin set().
    matriz_permisos = {
        RolUsuario.ADMINISTRADOR: [
            "ver_kanban", "ver_detalle", "ver_auditoria",
            "crear_ticket", "agregar_comentario",
            "cambiar_estado", "reasignar", "editar_ticket", "cerrar_ticket", "archivar_ticket",
            "administrar_usuarios", "administrar_estados", "administrar_catalogos",
            "administrar_etiquetas", "administrar_tableros",
            "importar_exportar", "ver_dashboard", "configurar_butler",
        ],
        RolUsuario.AGENTE_SENIOR: [ ... ],
        RolUsuario.AGENTE: [ ... ],
        RolUsuario.SOLICITANTE: [ ... ],
        RolUsuario.OBSERVADOR: [ ... ],
    }
```

El catálogo descriptivo de las 18 funciones está en `main.py:856-878` (`catalogo_funciones`). Las conteas por rol y la lista de usuarios sí vienen de BD (`main.py:915-946`), pero **la matriz de permisos no**.

### 3.2 Cómo se consulta si un usuario tiene una permiso concreta

El único helper ejecutable es `Usuario.tiene_permiso_para(accion)` (§1.3). **Solo tiene 2 call-sites en toda la aplicación, y ambos para la misma acción:**

```
app/api/v1/tickets.py:304          if not usuario.tiene_permiso_para("cambiar_estado"):
app/services/ticket_service.py:202 if not usuario.tiene_permiso_para("cambiar_estado"):
```

El resto de los permisos de `matriz_permisos` (incluidos todos los `administrar_*`, `importar_exportar`, `configurar_butler`, `archivar_ticket`) **nunca se consultan por código**: la pantalla es puramente informativa. Los controles reales de esas operaciones se hacen con comparaciones de rol ad-hoc (§1.4).

**Helper EXACTO para "¿este usuario tiene este permiso?":**

```python
Usuario.tiene_permiso_para(self, accion: str) -> bool
# declarado en app/models/usuario.py:47
# se invoca como:  usuario.tiene_permiso_para("cambiar_estado")
```

Advertencia funcional: el diccionario de `tiene_permiso_para` cubre 6 acciones, mientras que `matriz_permisos` define 18. Por ejemplo `archivar_ticket` aparece en la matriz para AGENTE_SENIOR pero **no** en el diccionario del método, por lo que `tiene_permiso_para("archivar_ticket")` devolvería `False` para ese rol. Las dos fuentes de verdad **no están sincronizadas**.

### 3.3 Roles definidos en el seed — `app/db/init_db.py`

La función `seed_usuarios` (líneas 158-211) está **deshabilitada por defecto**:

```python
# app/db/init_db.py:41
SEED_DEMO_USERS_ENABLED = os.getenv("SEED_DEMO_USERS", "false").lower() == "true"
```

```python
# app/db/init_db.py:170-176
    if not SEED_DEMO_USERS_ENABLED:
        print(
            "  · Seed de usuarios demo DESHABILITADO "
            "(defina SEED_DEMO_USERS=true para crear admin/admin123, etc.)"
        )
        print("  · El primer usuario que se registre por /auth/registro será Administrador.")
        return
```

Si se habilita, crea 4 usuarios (líneas 178-207): `admin`/`admin123` → `ADMINISTRADOR`; `lider`/`lider123` → `AGENTE_SENIOR`; `agente1`/`agente123` → `AGENTE`; `usuario1`/`user123` → `SOLICITANTE`. **El rol `OBSERVADOR` no tiene usuario semilla.**

La promoción a administrador del primer usuario registrado ocurre en el endpoint de registro:

```python
# app/api/v1/auth.py:116-117
    es_primer_usuario = db.query(Usuario).count() == 0
    rol_asignado = RolUsuario.ADMINISTRADOR if es_primer_usuario else RolUsuario.SOLICITANTE
```

Como el seed está deshabilitado por defecto, en una instalación limpia el primer usuario que se registre por `/auth/registro` obtiene `ADMINISTRADOR` automáticamente.

`app/core/config.py:48-54` declara una lista `ROLES_DISPONIBLES` con los mismos 5 valores, pero es **decorativa**: no se usa para validar el enum en ningún punto del código.

---

## 4. Auditoría

### 4.1 Modelo `Auditoria` — `app/models/auditoria.py` (46 líneas, leído completo)

```python
class Auditoria(Base, TimestampMixin):
    __tablename__ = "auditorias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=True, index=True
    )
    accion = Column(String(80), nullable=False, index=True)
    valor_anterior = Column(JSON, nullable=True)
    valor_nuevo = Column(JSON, nullable=True)
    comentario = Column(Text, nullable=True)
    ip_origen = Column(String(64), nullable=True)

    ticket = relationship("Ticket", back_populates="auditorias")
    usuario = relationship("Usuario", back_populates="auditorias")
```

Mapeo frente a lo solicitado:

| Concepto pedido | Campo real | Línea | Tipo |
|---|---|---|---|
| entidad / entidad_id | **No existe como campo genérico.** Se especializó en `ticket_id` (nullable) | 25-28 | FK `tickets.id` ON DELETE CASCADE |
| usuario_id | `usuario_id` (nullable) | 31-34 | FK `usuarios.id` ON DELETE **RESTRICT** |
| accion | `accion` | 35 | `String(80)`, indexada |
| detalle | `valor_anterior` / `valor_nuevo` / `comentario` | 36-38 | `JSON`, `JSON`, `Text` |
| fecha | `created_at` (heredado del mixin) | — | `DateTime` UTC |
| IP | `ip_origen` | 39 | `String(64)` |

Dos comentarios del código explican por qué `ticket_id` y `usuario_id` son nullable (líneas 21-24 y 29-30): la tabla registra tanto eventos de tickets como eventos de seguridad (login, envío de credenciales, perfil), y los eventos del sistema (triggers automáticos, `deadline_notifier`) se registran sin usuario. El borrado de un ticket cascada a su auditoría; borrar un usuario, en cambio, está **restringido** mientras tenga registros.

**No existe campo `detalle`** con ese nombre; la información estructurada va en los dos campos JSON.

### 4.2 Helper centralizado — sí existe

`app/services/auditoria_service.py` (39 líneas). **Firma exacta:**

```python
def registrar_auditoria(
    db: Session,
    ticket_id: int,
    usuario_id: int,
    accion: str,
    valor_anterior: Optional[Dict[str, Any]] = None,
    valor_nuevo: Optional[Dict[str, Any]] = None,
    comentario: Optional[str] = None,
    ip_origen: Optional[str] = None,
    commit: bool = True,
) -> Auditoria:
    """
    Inserta un registro inmutable en la tabla de auditoría.
    Es obligatorio llamarlo después de cualquier cambio de estado o edición.
    """
    registro = Auditoria(
        ticket_id=ticket_id,
        usuario_id=usuario_id,
        accion=accion,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        comentario=comentario,
        ip_origen=ip_origen,
    )
    db.add(registro)
    if commit:
        db.flush()  # Forzar el INSERT en la misma transacción
    return registro
```

Se reexporta en `app/services/__init__.py:2,4`:

```python
from app.services.auditoria_service import registrar_auditoria
__all__ = ["registrar_auditoria"]
```

**Trampa de diseño importante**: el parámetro se llama `commit` pero **nunca hace `db.commit()`** — hace `db.flush()`. El INSERT queda dentro de la transacción abierta y se confirma o revierte con el `db.commit()` del llamador. Quien lea el nombre `commit=True` puede asumir erróneamente que el registro ya está persistido.

### 4.3 Distribución de las llamadas

| Archivo | Ocurrencias |
|---|---|
| `app/api/v1/features.py` | 13 |
| `app/services/reporte_entregas_service.py` | 10 |
| `app/services/ticket_service.py` | 5 |
| `app/api/v1/tickets.py` | 4 |
| `app/tasks/entregas.py` | 2 |
| `app/services/notificacion_responsable_service.py` | 2 |
| `app/services/notificacion_admin_resultado_pruebas_service.py` | 2 |

El total de llamadas deEffectivas es ~38 en 7 ficheros. Se importan de dos maneras: **import de módulo** (`app/api/v1/features.py:47`, `app/api/v1/tickets.py:28`, `app/services/ticket_service.py:22`) e **import local diferido dentro de la función** (los 4 ficheros de `services/` y `tasks/entregas.py`), probablemente para evitar ciclos de importación.

### 4.4 Tres ejemplos reales de uso (texto literal)

**Ejemplo 1 — `app/api/v1/features.py:232`** (llamada posicional mínima, solo valor nuevo):

```python
    registrar_auditoria(db, ticket.id, user.id, "etiqueta_asignada", valor_nuevo={"etiqueta_id": etiqueta_id})
```

**Ejemplo 2 — `app/services/ticket_service.py:338-347`** (todos los parámetros, incluida la IP, y `commit=False` para참여 la transacción):

```python
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
            historial_creado = historial
        # 8. Commit transacción
        self.db.commit()
```

Nótese la convención de `accion`: aquí es **MAYÚSCULAS** (`"CAMBIO_ESTADO"`), mientras que en `features.py` es **minúsculas** (`"etiqueta_asignada"`, `"checklist_item_toggle"`). `reporte_entregas_service.py` usa el formato `SCREAMING_SNAKE` (`"REPORTE_ENTREGAS_PLANTILLA_EDITADA"`). La columna es un `String(80)` libre, sin validación ni catálogo: conviven tres convenciones de nombrado en la misma tabla.

**Ejemplo 3 — `app/api/v1/tickets.py:606-613`** (mapeo dinámico de acción según el campo editado):

```python
    registrar_auditoria(
        db,
        ticket.id,
        usuario.id,
        ACCIONES_CAMBIO.get(campo, f"campo_editado:{campo}"),
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
    )
```

**Ejemplo 4 — `app/services/reporte_entregas_service.py:88-95`** (patrón "best-effort", con `ticket_id=None` y captura local):

```python
    # Auditoría (best-effort)
    try:
        from app.services.auditoria_service import registrar_auditoria
        registrar_auditoria(
            db=db,
            ticket_id=None,
            usuario_id=actor_id,
            accion="REPORTE_ENTREGAS_PLANTILLA_EDITADA",
            valor_anterior=None,
            valor_nuevo={
                "habilitado": pl.habilitado,
                ...
```

`features.py:958-966` contiene además un comentario que documenta el comportamiento del `flush()`:

```python
    #   para persistizar el DELETE, pero ``registrar_auditoria()`` solo hace
    ...
    registrar_auditoria(
```

### 4.5 Cobertura

La auditoría es **parcial**: hay entradas de estado, asignación, edición de campos, etiquetas, checklist, comentarios, adjuntos, plantilla del reporte y credenciales. **No se encontró registro de auditoría para login/logout** en `auth.py`, pese a que el docstring del modelo (`auditoria.py:12-16`) sugiere cobertura amplia. La fila `RolUsuario` sigue siendo la única fuente de identidad para el `usuario_id`.

---

## 5. Celery — `app/core/celery_app.py` (102 líneas, leído completo)

### 5.1 Configuración

```python
def make_celery() -> Celery:
    """Crea y configura la instancia de Celery."""
    celery_app = Celery(
        "bitacora_grm",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.tasks.sla_tasks",
            "app.tasks.notification_tasks",
            "app.tasks.deadline_tasks",
            "app.tasks.backup_tasks",
            "app.tasks.entregas",
        ],
    )
```

Broker y backend provienen de `app/core/config.py:38-40`:

```python
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:2"
```

Valores por defecto en `.env` (líneas 34-37, bajo el comentario `# === Redis / Celery (opcional en dev local) ===`): los mismos tres, con DB 0, 1 y 2 respectivamente.

Ajustes adicionales (líneas 32-43): serialización JSON en las tres direcciones, `timezone="UTC"` con `enable_utc=True`, `task_track_started=True`, límites de tiempo (`task_time_limit=300`, `task_soft_time_limit=240`), `worker_prefetch_multiplier=1` y `worker_max_tasks_per_child=1000`.

La instancia es un **singleton a nivel de módulo**: `celery_app = make_celery()` (línea 101).

### 5.2 Eager mode

**No hay eager mode en la aplicación.** Una búsqueda de `task_always_eager` / `task_eager_propagates` sobre `app/` no devuelve ninguna coincidencia. Las únicas apariciones están en el archivo de pruebas de nivel raíz `/workspace/test_backup_system.py` (líneas 419-420 y 492-493), que lo activan explícitamente para correr sin broker.

Consecuencia práctica: **con el código tal como está, si Redis no está levantado, cualquier encolado falla en el momento del `.delay()`**. La aplicación sobrevive solo porque todos los call-sites están envueltos en `try/except` (§5.4).

### 5.3 Tareas registradas

Módulos incluidos vía `include` y sus funciones:

| Función | Fichero:línea |
|---|---|
| `recalcular_sla_ticket` | `app/tasks/sla_tasks.py:16` |
| `recalcular_sla_masivo` | `app/tasks/sla_tasks.py:33` |
| `notificar_cambio_estado` | `app/tasks/notification_tasks.py:15` |
| `notificar_sla_proximo_vencer` | `app/tasks/notification_tasks.py:55` |
| `limpiar_notificaciones_antiguas` | `app/tasks/notification_tasks.py:74` |
| `revisar_deadlines_diario` | `app/tasks/deadline_tasks.py:88` |
| `revisar_deadlines_horario` | `app/tasks/deadline_tasks.py:122` |
| `backup_database_diario` | `app/tasks/backup_tasks.py:41` |
| `backup_database_manual` | `app/tasks/backup_tasks.py:94` |
| `registrar_entrega_diaria` | `app/tasks/entregas.py:49` |
| `generar_reporte_diario` | `app/tasks/entregas.py:223` |

`backup_tasks.py` declara además un tercer decorador `@celery_app.task` en la línea 121 (función de limpieza de backups antiguos).

Todas usan el decorador `@celery_app.task(...)`. Las de SLA y notificación declaran reintentos:

```python
# app/tasks/notification_tasks.py:14
@celery_app.task(name="app.tasks.notification_tasks.notificar_cambio_estado", bind=True, max_retries=3)

# app/tasks/sla_tasks.py:15
@celery_app.task(name="app.tasks.sla_tasks.recalcular_sla_ticket", bind=True, max_retries=3)
```

Beat schedule (líneas 46-96): `recalcular-sla-cada-5-min` (`*/5`), `notificar-sla-proximo` (`*/15`), `limpiar-tickets-inactivos` (`02:00`), `deadline-approaching-horario` (`min=0`), `deadline-triggers-diario` (`08:00`), `backup-diario` (hora configurable) y `reporte-entregas-diario` (configurable vía `REPORTE_ENTREGAS_HOUR/MINUTE`).

### 5.4 Patrón exacto de llamada y manejo de fallos

**Patrón dominante: `.delay()` con import diferido y `try/except` que traga la excepción.**

```python
# app/services/ticket_service.py:392-404
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
```

Aquí el `except Exception` **no registra ni traza nada** — si Redis está caído, el sistema lo ignora en silencio. Variante con logging en `ticket_service.py:414-424`:

```python
            try:
                from app.tasks.entregas import registrar_entrega_diaria
                r3 = registrar_entrega_diaria.delay(
                    ticket.id, historial_creado.id
                )
                task_id = (task_id or "") + f";entrega={r3.id}"
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "[ticket_service] No se pudo encolar registrar_entrega_diaria "
                    "para ticket %s (no crítico): %s", ticket.id, exc,
                )
```

Otros dos call-sites: `app/services/ticket_service.py:638` (`notificar_ticket_archivado.delay(ticket.id, usuario.id)`) y `app/services/reporte_entregas_service.py:478` (`r = generar_reporte_diario.delay(fecha_iso)`).

**Único uso de `apply_async`** — en `app/api/v1/backups.py:159-172`, con **fallback a ejecución síncrona**:

```python
    if datos.async_task:
        try:
            from app.tasks.backup_tasks import backup_database_manual
            async_result = backup_database_manual.apply_async(kwargs={"note": note})
            return BackupRunResponse(
                ok=True,
                started_at=__import__("datetime").datetime.utcnow().isoformat(),
                task_id=async_result.id,
            )
        except Exception as e:
            logger.exception("No se pudo encolar backup en Celery")
            # Caer a ejecución síncrona como fallback
            payload = run_backup_sync(note=note)
            return BackupRunResponse(**payload)
```

**No existe** ningún uso de `send_task()`. Todos los objetos de tarea se importan por su ruta de módulo Python y se invocan como métodos.

---

## 6. Configuración — `app/core/config.py` (132 líneas, leído completo)

### 6.1 Mecanismo

**`pydantic-settings`** con la clase `Settings(BaseSettings)` (no una clase `Config` clásica):

```python
class Settings(BaseSettings):
    """Configuración de la aplicación cargada desde .env o variables de entorno."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
```

### 6.2 Singleton

```python
@lru_cache
def get_settings() -> Settings:
    """Singleton de configuración."""
    return Settings()


settings = get_settings()
```

`@lru_cache` garantiza una única instancia en todo el proceso; `settings` es el objeto de módulo que se importa.

### 6.3 Patrón exacto de acceso

**Desde una ruta/módulo**, siempre import directo del módulo de configuración y atributo en mayúsculas:

```python
# app/api/v1/usuarios.py:30  (import a nivel de módulo)
from app.core.config import settings
...
# app/api/v1/usuarios.py:175
    info["public_base_url"] = settings.PUBLIC_BASE_URL

# app/core/celery_app.py:17-18
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,

# app/db/session.py:11-14
    url = settings.get_database_url()
    ...
        return {"connect_args": {"check_same_thread": False}, "echo": settings.DEBUG}
```

Cuando el import se hace diferido dentro de una función, se usa alias para no colisionar con una variable local `settings`:

```python
# app/api/v1/reporte_entregas.py:369
    from app.core.config import settings

# app/api/v1/tickets.py:837
                from app.core.config import settings as _settings
```

Para tipos no triviales se usa `getattr` con valor por defecto:

```python
# app/core/celery_app.py:92-93
                hour=int(getattr(settings, "REPORTE_ENTREGAS_HOUR", 18)),
                minute=int(getattr(settings, "REPORTE_ENTREGAS_MINUTE", 0)),
```

### 6.4 `ALGO_UPLOAD_DIR` NO existe

El ejemplo `settings.ALGO_UPLOAD_DIR` del encargo **no corresponde a ninguna variable de este proyecto**. No existe ningún campo `ALGO_*` en `Settings`. La configuración de uploads **evita `settings` por completo** y lee el entorno directamente:

```python
# app/services/features_service.py:248
_UPLOAD_ROOT_RAW = os.environ.get("UPLOAD_DIR", "uploads")
```

Existe una segunda desviación comparable en `deps.py:28` (`ALLOW_XUSER_HEADER = os.getenv(...)`) y en `init_db.py:41` (`SEED_DEMO_USERS_ENABLED = os.getenv(...)`): tres parámetros de control de identidad se leen con `os.getenv()` y por tanto **no aparecen en `Settings`, no se validan por tipo y no aparecen en `.env.example` como campos tipados**.

### 6.5 Construcción de la URL de base de datos

`get_database_url()` (líneas 112-122) tiene una regla particular: si `DATABASE_URL` conserva el valor por defecto y `USE_SQLITE != true`, construye una URL de PostgreSQL:

```python
    def get_database_url(self) -> str:
        """Devuelve la URL de BD; si no se configuró, construye la de PostgreSQL."""
        if self.DATABASE_URL and self.DATABASE_URL != "sqlite:///./bitacora_grm.db":
            return self.DATABASE_URL
        # Si se solicita SQLite explícitamente
        if os.getenv("USE_SQLITE", "false").lower() == "true":
            return "sqlite:///./bitacora_grm.db"
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
```

---

## 7. Hallazgos y riesgos

**R1 — No existe `es_admin`.** Cualquier consumidor que espere `usuario.es_admin` fallará con `AttributeError`. La forma correcta es `usuario.rol == RolUsuario.ADMINISTRADOR`. Existe el precedente invertido en `app/templates/tickets/detalle_modal.py:694`, donde una variable de plantilla **sí** se llama `_es_admin` — es una variable local de Jinja, no un atributo del modelo.

**R2 — Seis sintaxis distintas para la misma comprobación.** Añadir un camino nuevo de autorización exige decidir cuál imitar; no hay regla única. Las variantes B, D y E son especialmente frágiles.

**R3 — Dos mecanismos de "usuario actual" con semántica distinta.** `get_current_user` acepta Bearer; `_get_usuario_actual` no. Una ruta HTML con Token-only devolverá 302 a login aunque el cliente envíe un Bearer válido, y una ruta API sin sesión devolverá 401 en lugar de redirigir.

**R4 — La matriz de permisos es decorativa y desincronizada.** 18 permisos en la matriz vs. 6 en `tiene_permiso_para`, con solapamiento inconsistente (`archivar_ticket` falta en el método pese a estar en la matriz para AGENTE_SENIOR). Un cambio de rol en BD no altera la matriz, y viceversa.

**R5 — La auditoría no es transaccional ni completa.** El parámetro `commit=True` en realidad ejecuta `db.flush()`. Y no hay entradas de auditoría para login/logout.

**R6 — Fallo silencioso de Celery.** El `except Exception: task_id = None` de `ticket_service.py:402-404` no deja rastro. En producción, una caída de Redis hace que SLA, notificaciones y registro de entregas dejen de funcionar sin ninguna señal en los logs.

**R7 — Tres controles de seguridad fuera de `Settings`.** `ALLOW_XUSER_HEADER`, `SEED_DEMO_USERS` y `USE_SQLITE` se leen con `os.getenv()` y no están declarados en la clase `Settings`.

**R8 — Sin eager mode.** No hay degradación automática en desarrollo; sin Redis, todas las tareas asíncronas son no-ops silenciosos.

---

## 8. Anexo — Índice de referencias

| Elemento | Ruta | Líneas |
|---|---|---|
| Modelo Usuario + enum de roles + helper de permisos | `app/models/usuario.py` | 11-17, 20-45, 47-64 |
| `TimestampMixin` | `app/db/base.py` | 14-24 |
| Dependencias de auth (`get_current_user`, `require_role`, `require_admin`) | `app/api/v1/deps.py` | 24-28, 31-88, 91-100, 103-110 |
| `get_db` | `app/db/session.py` | 24-30 |
| Guard local de dependencias Gantt | `app/api/v1/dependencias.py` | 96-102 |
| `_get_usuario_actual` / `_require_session_or_redirect` | `app/main.py` | 127-155, 158-163 |
| Pantalla roles × funciones + matriz hardcodeada | `app/main.py` | 835-972 (matriz 882-912) |
| Emisión de cookie de sesión | `app/api/v1/auth.py` | 60-71 |
| Primer usuario → administrador | `app/api/v1/auth.py` | 116-117 |
| Modelo Auditoria | `app/models/auditoria.py` | 10-46 |
| Helper `registrar_auditoria` | `app/services/auditoria_service.py` | 11-38 |
| Reexport del helper | `app/services/__init__.py` | 2, 4 |
| Configuración Celery + beat | `app/core/celery_app.py` | 13-29, 32-43, 46-96 |
| Llamada Celery `.delay()` con fallback | `app/services/ticket_service.py` | 392-404, 414-424 |
| Llamada Celery `apply_async` con fallback síncrono | `app/api/v1/backups.py` | 159-172 |
| `Settings` (pydantic-settings) | `app/core/config.py` | 11-18, 112-122, 125-131 |
| Hashing y JWT | `app/core/security.py` | 29-32, 45-52, 55-60 |
| Seed de usuarios (deshabilitado por defecto) | `app/db/init_db.py` | 41, 158-211 |
| Helper de admin local duplicado | `app/api/v1/usuarios.py` | 43-48 |
| Variable de entorno fuera de `Settings` | `app/services/features_service.py` | 248 |