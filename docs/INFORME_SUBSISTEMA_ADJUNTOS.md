# Informe técnico exhaustivo — Subsistema de Adjuntos (Bitácora GRM v2)

**Objetivo del informe:** documentar de forma reproducible todo el subsistema de adjuntos del proyecto `Bitácora GRM v2` (FastAPI + SQLAlchemy + Jinja2 + HTMX) para poder replicar sus patrones al añadir carga de archivos a los comentarios.

> **Aviso importante — alcance de la asociación a entidad (HALLAZGO CRÍTICO):** el modelo `Adjunto` **NO es polimórfico**. Sólo se asocia con `tickets` mediante la FK `ticket_id`. No existe `owner_type`/`owner_id`/`comentario_id`. Si se quieren adjuntos en comentarios habrá que **modificar el modelo** (probablemente añadir `comentario_id` nullable o un patrón polimórfico). Ver §1.

---

## 0. Mapa rápido de archivos relevantes

| Capa | Ruta | Líneas relevantes |
|---|---|---|
| Modelo | `/workspace/app/models/adjunto.py` | 73 (archivo completo) |
| Modelo | `/workspace/app/models/auditoria.py` | 47 (completo) |
| Modelo (registro) | `/workspace/app/models/__init__.py` | línea 10 importa `Adjunto`, línea 5 importa `Auditoria` |
| Servicio de auditoría | `/workspace/app/services/auditoria_service.py` | 38 (completo) |
| Servicio adjuntos | `/workspace/app/services/features_service.py` | 1-30 (imports), 240-359 (clase `AdjuntoService`, constantes y todo el guardado) |
| Endpoints REST | `/workspace/app/api/v1/features.py` | router declarado en línea 51 `router = APIRouter(tags=["features"])`, sección adjuntos 744-981 |
| Auth/Roles helpers | `/workspace/app/api/v1/deps.py` | `get_current_user` (31-88), `require_admin` (103-110), `RolUsuario` (11-17 de `models/usuario.py`) |
| Schemas Pydantic | `/workspace/app/schemas/features.py` | `AdjuntoRead` (147-161), `AdjuntoBase` (143-144) |
| Templates | `/workspace/app/templates/tickets/detalle_modal.py` | panel adjuntos línea 676-827, hx-form 783-826 |
| JS upload/paste | `/workspace/app/static/js/htmx-events.js` | sección `setupAdjuntosDropzone` 299-612 |
| Config | `/workspace/app/core/config.py` | `Settings` 11-131 (sin claves específicas de upload — ver §6) |
| Migraciones | `/workspace/app/db/migrations.py` | `apply_migrations` 171-253, `COLUMNS_TO_ADD` 42-110 (entrada `"adjuntos"` 103-109), `INDEXES` 114-139 |
| Init | `/workspace/app/db/init_db.py` | `init_database` 47-87 (aplica migraciones) |
| Arranque | `/workspace/app/main.py` | `lifespan` 35-61 (aplica migraciones siempre) |
| Montaje router | `/workspace/app/api/v1/router.py` | `include_router(features.router)` línea 44 |
| Prefijo API | `/workspace/app/main.py` línea 123 | `app.include_router(api_router, prefix="/api/v1")` |

> **Prefijo final en producción:** `/api/v1`. Por ejemplo, `POST /api/v1/tickets/{ticket_id}/adjuntos`.

---

## 1. Modelo de datos — `Adjunto`

**Archivo:** `/workspace/app/models/adjunto.py` (73 líneas, archivo completo). `__tablename__ = "adjuntos"`.

### 1.1 Tabla de campos (nombre exacto, tipo, nullable, default, FK)

| Campo | Tipo SQLAlchemy | Nullable | Default | FK / ondelete | Índice | Comentario |
|---|---|---|---|---|---|---|
| `id` | `Integer`, PK, autoincrement | NO | — | — | PK | — |
| `ticket_id` | `Integer` | **NO** | — | `ForeignKey("tickets.id", ondelete="CASCADE")` | `index=True` | Asociación obligatoria a ticket |
| `usuario_id` | `Integer` | NO | — | `ForeignKey("usuarios.id", ondelete="RESTRICT")` | — | Autor de la subida |
| `nombre_original` | `String(255)` | NO | — | — | — | Nombre "humano" del archivo tal como llegó |
| `nombre_storage` | `String(255)` | NO | — | — | `unique=True` | Nombre interno: `{uuid.uuid4().hex}{ext}` |
| `ruta` | `String(500)` | NO | — | — | — | Path absoluto en disco o sentinela `"(db-only)..."` |
| `mime_type` | `String(100)` | SÍ (`nullable=True`) | `None` | — | — | Viene del `UploadFile.content_type` |
| `tamano_bytes` | `BigInteger` | NO | `0` | — | — | Tamaño exacto |
| `descripcion` | `Text` | SÍ | `None` | — | — | Nota opcional del usuario al subir |
| `contenido` | `LargeBinary` | SÍ | `None` | — | — | **Respaldo binario en BD (BYTEA/BLOB)** |
| `created_at` / `updated_at` | del mixin `TimestampMixin` | — | — | — | — | Heredados de `app/db/base.py` |

### 1.2 ¿A qué entidad se asocia?

**Solo a `tickets`.** No hay polimorfismo (`owner_type`/`owner_id`) ni `comentario_id`. La prueba:

```python
# /workspace/app/models/adjunto.py:25-28
ticket_id = Column(
    Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
    nullable=False, index=True
)
```

Si necesitas adjuntos en comentarios, hay dos caminos posibles (no implementados en este repo):

1. **Añadir columnas alternativas nullable** al mismo modelo: `comentario_id = Column(Integer, ForeignKey("comentarios.id", ondelete="CASCADE"), nullable=True, index=True)`. Forzar invariante "exactamente uno de los dos" en servicio o trigger.
2. **Tabla nueva separada** (p. ej. `comentario_adjuntos`) cuando el modelo crezca mucho.

### 1.3 Campos para tipo MIME, tamaño, hash, ruta en disco

| Atributo pedido | ¿Existe? | Campo / Implementación |
|---|---|---|
| **Tipo MIME** | ✅ | `mime_type = Column(String(100), nullable=True)` — se guarda desde `UploadFile.content_type` |
| **Tamaño** | ✅ | `tamano_bytes = Column(BigInteger, default=0, nullable=False)` |
| **Hash** | ❌ | **No se almacena hash ni se calcula** |
| **Nombre original** | ✅ | `nombre_original = Column(String(255), nullable=False)` |
| **Ruta en disco** | ✅ | `ruta = Column(String(500), nullable=False)` — puede contener el path absoluto o el sentinela `"(db-only)ticket_{id}/{uuid}{ext}"` |
| **Binario en BD** | ✅ | `contenido = Column(LargeBinary, nullable=True)` — respaldo que sobrevive a redeploys |

### 1.4 Relationships (SQLAlchemy)

```python
# /workspace/app/models/adjunto.py:44-45
ticket = relationship("Ticket", back_populates="adjuntos", foreign_keys=[ticket_id])
usuario = relationship("Usuario")
```

### 1.5 Propiedades calculadas (útiles para UI/serializer)

```python
# /workspace/app/models/adjunto.py:47-69
@property
def tamano_legible(self) -> str:      # "12.3 KB", "4.1 MB"...
    size = float(self.tamano_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

@property
def es_imagen(self) -> bool:           # (self.mime_type or "").startswith("image/")
    return (self.mime_type or "").startswith("image/")

@property
def disponible(self) -> bool:          # True si contenido en BD o archivo en disco
    if self.contenido:
        return True
    try:
        return bool(self.ruta) and os.path.exists(self.ruta)
    except Exception:
        return False
```

### 1.6 Registrado en el paquete de modelos

```python
# /workspace/app/models/__init__.py:10
from app.models.adjunto import Adjunto
...
# __all__ incluye "Adjunto" (línea 45)
```

---

## 2. Endpoints API de adjuntos

**Archivo:** `/workspace/app/api/v1/features.py` — `router = APIRouter(tags=["features"])` línea 51. Prefijo final: `/api/v1`. Router montado en `/workspace/app/api/v1/router.py:44` y luego con `prefix="/api/v1"` en `/workspace/app/main.py:123`.

### 2.1 Listado de endpoints

| # | Método | Path completo | Línea | Firma (resumida) |
|---|---|---|---|---|
| 1 | GET | `/api/v1/tickets/{ticket_id}/adjuntos` | 747-753 | `listar_adjuntos(ticket_id, db, _user)` → `List[AdjuntoRead]` |
| 2 | POST | `/api/v1/tickets/{ticket_id}/adjuntos` | 756-850 | `subir_adjunto(ticket_id, request, archivo=None, archivos=None, descripcion=None, active_tab=None, db, user)` |
| 3 | GET | `/api/v1/adjuntos/{adjunto_id}/descargar` | 853-908 | `descargar_adjunto(adjunto_id, db, _user)` |
| 4 | DELETE | `/api/v1/adjuntos/{adjunto_id}` | 911-981 | `eliminar_adjunto(adjunto_id, request, db, user)` (async) |

Los tres primeros exigen únicamente `get_current_user`. Solo `eliminar_adjunto` inspecciona el rol (lógica detallada en §3).

> **Acumulado:** los archivos de FastAPI: `APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request, Response` (línea 17-20). Importante: `UploadFile` y `File` se importan aquí (no en `tickets.py`).

### 2.2 Endpoint 2 (`POST .../adjuntos`) — patrón completo de subida

Características relevantes que ya están implementadas en el backend **y que se pueden reutilizar**:

```python
# /workspace/app/api/v1/features.py:756-850 (recortado)
@router.post("/tickets/{ticket_id}/adjuntos")
async def subir_adjunto(
    ticket_id: int,
    request: Request,
    archivo: Optional[UploadFile] = File(None),
    archivos: Optional[List[UploadFile]] = File(None),
    descripcion: Optional[str] = Form(None),
    active_tab: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Sube uno o varios archivos adjuntos al ticket.

    Acepta ``multipart/form-data`` con campo ``archivo`` (singular, compat)
    o ``archivos`` (plural, múltiples). Si la petición viene de HTMX,
    devuelve el modal re-renderizado.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    active_tab = (active_tab or "").strip()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        if is_htmx:
            return HTMLResponse(
                content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">Ticket no encontrado.</div>',
                status_code=404,
            )
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    # Normalizar: aceptar tanto 'archivo' (singular, retro-compat) como 'archivos' (plural, múltiples)
    files_to_upload: List[UploadFile] = []
    if archivos:
        files_to_upload.extend([f for f in archivos if f and f.filename])
    if archivo and archivo.filename:
        files_to_upload.append(archivo)
    # Quitar duplicados manteniendo orden
    seen = set()
    files_unique = []
    for f in files_to_upload:
        key = (f.filename, id(f))
        if key not in seen:
            seen.add(key)
            files_unique.append(f)
    files_to_upload = files_unique
```

Después, dentro del `for archivo_actual in files_to_upload:` (líneas 808-829):

```python
contenido = await archivo_actual.read()
if not contenido:
    errores.append(f"'{archivo_actual.filename}' está vacío")
    continue
adj, error = AdjuntoService(db).guardar_archivo(
    ticket=ticket,
    usuario=user,
    file_bytes=contenido,
    nombre_original=archivo_actual.filename or "archivo",
    mime_type=archivo_actual.content_type,
    descripcion=descripcion,
)
if error:
    errores.append(f"'{archivo_actual.filename}': {error}")
    continue
subidos.append(adj)
registrar_auditoria(db, ticket.id, user.id, "adjunto_subido", valor_nuevo={
    "adjunto_id": adj.id, "nombre": adj.nombre_original, "tamano": adj.tamano_bytes
})
```

Finalmente (línea 840-850), si viene de HTMX re-renderiza el modal completo con triggers para toasts:

```python
if is_htmx:
    html = _render_detalle_modal_response(db, ticket, user, active_tab=active_tab or "adjuntos")
    trigger_payload = {"adjunto-subido": {"count": len(subidos)}}
    if errores:
        trigger_payload["adjunto-error"] = {"errores": errores}
    return HTMLResponse(
        content=html, status_code=200,
        headers={"HX-Trigger": json.dumps(trigger_payload)},
    )
return subidos[0] if len(subidos) == 1 else subidos
```

### 2.3 **CONFIGURACIÓN DE SUBIDA** — claves para replicar en comentarios

Toda la configuración de tamaño/extensiones/almacenamiento vive en `AdjuntoService` (`/workspace/app/services/features_service.py`):

```python
# /workspace/app/services/features_service.py:242-265
# ==========================================
# ADJUNTOS
# ==========================================
# Raíz de uploads: SIEMPRE absoluta, anclada al project root. Railway tiene
# filesystem efímero (cada redeploy borra /app/uploads), por eso guardamos
# también una copia binaria en PostgreSQL (BYTEA) como respaldo persistente.
_UPLOAD_ROOT_RAW = os.environ.get("UPLOAD_DIR", "uploads")
if os.path.isabs(_UPLOAD_ROOT_RAW):
    UPLOAD_ROOT = _UPLOAD_ROOT_RAW
else:
    # Anclar al directorio raíz del proyecto (no al CWD del gunicorn,
    # que en Railway puede variar y romper rutas relativas guardadas en BD).
    _PROJECT_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
    )
    UPLOAD_ROOT = os.path.join(_PROJECT_ROOT, _UPLOAD_ROOT_RAW)
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".mp4", ".webm", ".mov",
}
```

Resumen operacional:

- **Tamaño máximo:** `MAX_FILE_SIZE = 25 * 1024 * 1024` = **25 MiB** por archivo.
- **Extensiones permitidas (allow-list, deny por defecto):** imágenes (`.png .jpg .jpeg .gif .webp .svg`), ofimática (`.pdf .doc .docx .xls .xlsx .ppt .pptx`), texto (`.txt .csv .log .json .xml .yaml .yml`), comprimidos (`.zip .rar .7z .tar .gz`), video (`.mp4 .webm .mov`).
- **MIME types permitidos:** **NO se valida una lista de MIME**. La validación actual es por **extensión** únicamente (`AdjuntoService._extension` → `os.path.splitext(nombre)[1].lower()` en `features_service.py:272-274`). El `mime_type` se guarda como metadato del `UploadFile.content_type` del cliente, sin comparación contra magic numbers. Esto es una vulnerabilidad ya identificada en el código (no se contrasta contenido real vs extensión).
- **Sanitización del nombre de archivo:** **NO se hace `secure_filename`/`werkzeug.utils.secure_filename`.** El campo `nombre_original` se guarda tal cual llega del cliente y es lo que se muestra al usuario (HTML-escaped en el template). El nombre en disco (`nombre_storage`) se genera como `{uuid.uuid4().hex}{ext}` (línea 306) — ahí SÍ se evita path traversal.
- **Ruta de almacenamiento:** `os.path.join(UPLOAD_ROOT, f"ticket_{ticket.id}")`. `UPLOAD_ROOT` por defecto = `<PROJECT_ROOT>/uploads` (relativo al project root, no al CWD del gunicorn). Override vía env `UPLOAD_DIR` (puede ser absoluto). Existe como comentario `.gitignore`: `# uploads/` en `/workspace/.gitignore`.
- **Validación de contenido real:** no implementada (sólo se valida la extensión). El archivo se abre con `open(ruta_abs, "wb")` sin re-encoding.
- **Persistencia dual:** siempre se guarda una copia binaria en la columna `contenido` (LargeBinary/BYTEA/BLOB) incluso si la escritura en disco falla, para sobrevivir al filesystem efímero de Railway.

Función `guardar_archivo` completa (`/workspace/app/services/features_service.py:276-334`):

```python
def guardar_archivo(
    self, ticket: Ticket, usuario: Usuario, file_bytes: bytes,
    nombre_original: str, mime_type: Optional[str] = None,
    descripcion: Optional[str] = None,
) -> Tuple[Optional[Adjunto], Optional[str]]:
    """Guarda el archivo en disco y en BD (respaldo) y registra el adjunto.

    Retorna (adjunto, error). El archivo binario siempre queda persistido
    en PostgreSQL/SQLite (``Adjunto.contenido``) de modo que sobreviva a
    reinicios del contenedor (Railway borra el filesystem en cada redeploy).
    """
    if not file_bytes:
        return None, "Archivo vacío"
    if len(file_bytes) > MAX_FILE_SIZE:
        mb = len(file_bytes) / (1024 * 1024)
        return None, f"Archivo demasiado grande: {mb:.1f}MB (máx 25MB)"
    ext = self._extension(nombre_original)
    if ext and ext not in ALLOWED_EXT:
        return None, f"Extensión no permitida: {ext}"

    # Crear estructura de carpetas (raíz siempre absoluta)
    dir_destino = os.path.join(UPLOAD_ROOT, f"ticket_{ticket.id}")
    try:
        os.makedirs(dir_destino, exist_ok=True)
    except OSError as e:
        # Si el filesystem está en modo read-only (caso típico Railway
        # sin volumen), seguimos: la copia en BD es la fuente de verdad.
        logger.warning(f"No se pudo crear {dir_destino}: {e}. Se omite copia en disco.")
        dir_destino = None

    nombre_storage = f"{uuid.uuid4().hex}{ext}"
    ruta_abs = (
        os.path.join(dir_destino, nombre_storage)
        if dir_destino else os.path.join(UPLOAD_ROOT, f"ticket_{ticket.id}", nombre_storage)
    )
    if dir_destino:
        try:
            with open(ruta_abs, "wb") as f:
                f.write(file_bytes)
        except OSError as e:
            logger.warning(f"No se pudo escribir {ruta_abs}: {e}. Se usará respaldo en BD.")
            ruta_abs = ""

    adj = Adjunto(
        ticket_id=ticket.id,
        usuario_id=usuario.id,
        nombre_original=nombre_original,
        nombre_storage=nombre_storage,
        ruta=ruta_abs or f"(db-only)ticket_{ticket.id}/{nombre_storage}",
        mime_type=mime_type,
        tamano_bytes=len(file_bytes),
        descripcion=descripcion,
        # Respaldo persistente en BD (sobrevive a redeploys).
        contenido=file_bytes,
    )
    self.db.add(adj)
    self.db.commit()
    self.db.refresh(adj)
    return adj, None
```

### 2.4 Endpoint 3 (`GET .../descargar`) — estrategia de descarga

**Archivo:** `/workspace/app/api/v1/features.py:853-908`. La idea es servir el archivo desde disco si existe, si no desde BD (BYTEA), si no devolver 410.

```python
@router.get("/adjuntos/{adjunto_id}/descargar")
def descargar_adjunto(adjunto_id: int, db, _user):
    """Descarga un adjunto.

    Estrategia de resolución (orden de preferencia):
    1. Disco físico (``adj.ruta``) — más rápido, sirve vía ``FileResponse``.
    2. Respaldo binario en BD (``adj.contenido``) — persiste entre redeploys
       de Railway aunque el filesystem se haya borrado.
    3. Si ninguno está disponible: 410 con detalle accionable.
    """
    from urllib.parse import quote
    adj = AdjuntoService(db).obtener(adjunto_id)
    if not adj:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    filename = adj.nombre_original or f"adjunto_{adjunto_id}"
    media_type = adj.mime_type or "application/octet-stream"

    # --- 1) Disco físico --------------------------------------------------
    ruta = adj.ruta or ""
    if ruta and not ruta.startswith("(db-only)") and os.path.exists(ruta):
        return FileResponse(path=ruta, filename=filename, media_type=media_type)

    # --- 2) Respaldo en BD ------------------------------------------------
    if adj.contenido:
        # Content-Disposition con UTF-8 RFC 5987 para preservar acentos/ñ.
        fallback = filename.encode("ascii", "replace").decode("ascii") or "adjunto"
        quoted = quote(filename, safe="")
        content_disp = (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quoted}"
        )
        return Response(
            content=adj.contenido, media_type=media_type,
            headers={"Content-Disposition": content_disp},
        )

    # --- 3) Sin fuente disponible ----------------------------------------
    raise HTTPException(
        status_code=410,
        detail=(
            "Archivo no disponible. Fue subido en una versión anterior del "
            "sistema y la copia física fue purgada del contenedor. "
            "Vuelve a subirlo para conservarlo."
        ),
    )
```

### 2.5 Endpoint 4 (`DELETE /adjuntos/{adjunto_id}`) — eliminar con auditoría

Flujo completo en `/workspace/app/api/v1/features.py:911-981`. Ver patrón completo en §7 (Auditoría).

---

## 3. Permisos de adjuntos — código TEXTUAL

**Hallazgo:** el proyecto **no define una función helper** tipo `_puede_gestionar_adjuntos(...)`. La regla está **inline** en el endpoint `eliminar_adjunto` y replicada en el template Jinja para ocultar el botón.

### 3.1 Backend — `features.py:937-943`

```python
if adj.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
    if is_htmx:
        return HTMLResponse(
            content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">No autorizado para eliminar.</div>',
            status_code=403,
        )
    raise HTTPException(status_code=403, detail="No autorizado para eliminar")
```

**Lectura de la regla:** puede eliminar **quien sea autor de la subida** (`adj.usuario_id == user.id`) **O** quien tenga rol `administrador`. Esta es la única comprobación de permisos que existe en los endpoints de adjuntos — `listar`, `subir` y `descargar` solo requieren `Depends(get_current_user)` (sin chequeo de rol).

`RolUsuario` está definido en `/workspace/app/models/usuario.py:11-17`:

```python
class RolUsuario(str, enum.Enum):
    """Roles disponibles con permisos predefinidos."""
    ADMINISTRADOR = "administrador"
    AGENTE_SENIOR = "agente_senior"
    AGENTE = "agente"
    SOLICITANTE = "solicitante"
    OBSERVADOR = "observador"
```

Helpers disponibles en `/workspace/app/api/v1/deps.py` (líneas 91-110):

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

def require_admin(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency que exige rol Administrador."""
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere rol Administrador.",
        )
    return usuario
```

### 3.2 Frontend — `detalle_modal.py:694-696` (gemelo de la regla de backend)

```jinja
{% set _es_admin  = (usuario is not none and usuario.rol is defined and (usuario.rol.value if usuario.rol is defined and usuario.rol is not string else usuario.rol) == 'administrador') %}
{% set _es_creador = (usuario is not none and a.usuario_id is defined and usuario.id == a.usuario_id) %}
{% set _puede_borrar = (_es_admin or _es_creador) %}
```

Y a partir de la línea 747:

```jinja
{% if _puede_borrar %}
    {% if _es_admin %}
        <span ... title="El administrador puede eliminar cualquier adjunto. Quedará registro en la pestaña Trazabilidad.">Admin</span>
    {% else %}
        <span ... title="Eres el autor de este adjunto, por eso puedes eliminarlo. Quedará registro en la pestaña Trazabilidad.">Creador</span>
    {% endif %}
    <button type="button"
            hx-delete="/api/v1/adjuntos/{{ a.id }}"
            hx-confirm="¿Eliminar el archivo &quot;{{ ... }}&quot;? Esta acción no se puede deshacer y quedará registrada en la trazabilidad del ticket."
            hx-target="#modal-root" hx-swap="innerHTML"
            hx-vals='{"active_tab": "adjuntos"}'
            ...>
        ...
    </button>
{% endif %}
```

> **Patrón recomendado al replicar a comentarios:** reutiliza la misma fórmula inline (`user.rol not in (RolUsuario.ADMINISTRADOR,)`) o crea un helper compartido tipo `puede_eliminar_adj(adj, user)`. **Lo importante es que la regla viva en backend**, y el template solo duplica para ocultar el botón.

---

## 4. Templates del panel de adjuntos

**Archivo:** `/workspace/app/templates/tickets/detalle_modal.py` (100 KB, contiene varios tabs; aquí sólo el panel "Adjuntos" — líneas 676-827). Se renderiza como HTML y se devuelve por la ruta interna `_render_detalle_modal_response(db, ticket, user, active_tab=...)` que aparece como helper en `features.py:61-143`.

> [!NOTE]
> El archivo se llama `detalle_modal.py` aunque contiene HTML puro (no es un builder Python): usa Jinja2 estático dentro de un template-string en Python. Esta es una peculiaridad del proyecto.

### 4.1 Estructura del dropzone / input

Líneas 783-826 — formulario HTMX completo:

```jinja
<form hx-post="/api/v1/tickets/{{ ticket.id }}/adjuntos"
      hx-target="#modal-root" hx-swap="innerHTML"
      hx-encoding="multipart/form-data"
      class="pt-3 border-t border-slate-100 space-y-2"
      id="adjuntos-form-{{ ticket.id }}">
  <input type="hidden" name="active_tab" value="adjuntos">

  {# ---- Dropzone visual (click + drag) ---- #}
  <div class="adjuntos-dropzone flex flex-col items-center justify-center w-full h-28
              border-2 border-dashed border-slate-300 rounded-lg cursor-pointer
              hover:border-indigo-400 hover:bg-indigo-50/30 transition-colors relative"
       data-ticket-id="{{ ticket.id }}">
    <svg class="w-6 h-6 text-slate-400 mb-1" ...><!-- upload cloud --></svg>
    <span class="text-xs text-slate-500">Click para seleccionar o arrastra y suelta aquí</span>
    <span class="text-[10px] text-slate-400 mt-0.5">Múltiples archivos permitidos</span>
    {# ---- NUEVO: hint de copy-paste (Ctrl+V) ---- #}
    <span class="text-[10px] text-indigo-600 font-medium mt-1 inline-flex items-center gap-1">
      ...
      También puedes pegar imágenes con
      <kbd>Ctrl</kbd>+<kbd>V</kbd>
    </span>
    <input id="adjunto-file-{{ ticket.id }}" name="archivos" type="file" multiple class="hidden">
  </div>

  {# ---- Preview existente (drag/drop/click) ---- #}
  <div id="adjuntos-preview-{{ ticket.id }}" class="hidden flex flex-wrap gap-1.5 ..."></div>

  {# ---- NUEVO: preview específico de archivos pegados (con thumbnail + X) ---- #}
  <div id="adjuntos-paste-list-{{ ticket.id }}" class="hidden space-y-1"></div>

  {# ---- NUEVO: descripción batch (opcional) ---- #}
  <textarea id="adjuntos-paste-desc-{{ ticket.id }}"
            name="descripcion"
            rows="2" maxlength="500"
            placeholder="Descripción opcional para los archivos pegados..."
            class="hidden ..." data-paste-desc></textarea>

  <div class="flex items-center justify-between">
    <span id="adjuntos-info-{{ ticket.id }}" class="text-[11px] text-slate-500"></span>
    <button type="submit" class="px-3 py-1.5 ... bg-indigo-600 hover:bg-indigo-700 text-white ...">
      Subir archivo(s)
    </button>
  </div>
</form>
```

**Atributos hx-* exactos:**
- `hx-post="/api/v1/tickets/{{ ticket.id }}/adjuntos"`
- `hx-target="#modal-root"` (re-renderiza todo el modal)
- `hx-swap="innerHTML"`
- `hx-encoding="multipart/form-data"` ← **obligatorio** para que htmx serialice archivos
- `id="adjuntos-form-{{ ticket.id }}"`
- El `<input type="file">` lleva `name="archivos" multiple class="hidden"` (usado por el JS para inyectar archivos pegados vía `DataTransfer`).

### 4.2 ¿Hay manejo de `paste` (Ctrl+V), drag & drop, previews?

**Sí, todos.** Implementado en `/workspace/app/static/js/htmx-events.js`, función `setupAdjuntosDropzone` (líneas 299-612). El listener global de `paste` se instala **una sola vez** por página (`_pasteGlobalInstalled`, línea 346-411):

```javascript
// /workspace/app/static/js/htmx-events.js:345-411
let _pasteGlobalInstalled = false;
function _installGlobalPasteHandler() {
  if (_pasteGlobalInstalled) return;
  _pasteGlobalInstalled = true;
  document.addEventListener('paste', function (e) {
    // No interceptar paste dentro de inputs de texto o textareas: dejar
    // que el navegador haga su trabajo normal (pegar texto donde el usuario
    // está escribiendo).
    const t = e.target;
    if (t) {
      const tag = (t.tagName || '').toUpperCase();
      if (tag === 'TEXTAREA') return;
      if (tag === 'INPUT') {
        const type = ((t.type || '') + '').toLowerCase();
        const texty = ['text','password','email','search','tel','url','number',
                       'date','datetime-local','month','week','time'].includes(type);
        if (texty) return;
      }
      if (t.isContentEditable) return;
    }
    const items = e.clipboardData && e.clipboardData.items;
    if (!items || items.length === 0) return;

    const ticketId = _activeAdjuntosTicketId();
    if (!ticketId) return; // no hay tab de adjuntos activo

    let added = 0;
    let rejectedSize = 0;
    const arr = _getPastedFiles(ticketId);
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind !== 'file' || !item.type || !item.type.startsWith('image/')) continue;
      const blob = item.getAsFile();
      if (!blob) continue;
      if (blob.size > MAX_PASTE_BYTES) {
        rejectedSize++;
        continue;
      }
      const ext = (item.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace('svg+xml', 'svg');
      const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15);
      const fname = 'paste-' + ts + '-' + (arr.length + added + 1) + '.' + ext;
      const file = new File([blob], fname, { type: item.type });
      const url = URL.createObjectURL(blob);
      const id = 'p' + Date.now().toString(36) + added;
      arr.push({ id: id, file: file, url: url });
      added++;
    }
    if (added === 0) {
      if (rejectedSize > 0 && typeof showToast === 'function') {
        showToast(rejectedSize + ' imagen(es) rechazada(s): exceden 25 MB', 'error');
      }
      return;
    }
    e.preventDefault();
    _renderPasteList(ticketId);
    _refreshCombinedFiles(ticketId);
    ...
  });
}
const MAX_PASTE_BYTES = 25 * 1024 * 1024; // mismo límite que backend
```

**Drag & drop** (líneas 550-580):

```javascript
// Drag visual feedback
['dragenter', 'dragover'].forEach(function (ev) {
  drop.addEventListener(ev, function (e) {
    e.preventDefault();
    e.stopPropagation();
    drop.classList.add('border-indigo-500', 'bg-indigo-50/50');
  });
});
['dragleave', 'drop'].forEach(function (ev) {
  drop.addEventListener(ev, function (e) {
    e.preventDefault();
    e.stopPropagation();
    drop.classList.remove('border-indigo-500', 'bg-indigo-50/50');
  });
});

// Soltar archivos
drop.addEventListener('drop', function (e) {
  const files = e.dataTransfer && e.dataTransfer.files;
  if (!files || !files.length) return;
  try {
    const dt = new DataTransfer();
    for (let i = 0; i < files.length; i++) dt.items.add(files[i]);
    fileInput.files = dt.files;
  } catch (err) {
    showToast('Tu navegador no soporta multi-drop. Selecciona manualmente.', 'info');
  }
  _refreshCombinedFiles(ticketId);
});
```

**Mezcla drag + paste vía `DataTransfer`** (líneas 459-486):

```javascript
function _refreshCombinedFiles(ticketId) {
  const fileInput = document.getElementById('adjunto-file-' + ticketId);
  if (!fileInput) return;
  const currentFiles = fileInput.files ? Array.from(fileInput.files) : [];
  const allPasted = _getPastedFiles(ticketId);
  const activePasted = allPasted.filter(function (p) { return !p.removed; });
  const allPastedFileSet = new Set(allPasted.map(function (p) { return p.file; }));
  const originalFiles = currentFiles.filter(function (f) { return !allPastedFileSet.has(f); });
  try {
    const dt = new DataTransfer();
    originalFiles.forEach(function (f) { dt.items.add(f); });
    activePasted.forEach(function (p) { dt.items.add(p.file); });
    fileInput.files = dt.files;
  } catch (err) {
    if (typeof showToast === 'function') {
      showToast('Tu navegador no soporta combinar archivos pegados con seleccionados.', 'info');
    }
  }
  fileInput.dispatchEvent(new Event('change'));
  ...
}
```

**Previews:** función `updatePreview()` (líneas 584-610) genera HTML inline con `formatBytes(n)` (líneas 302-307) y `escapeHtml(s)` (308-312). Para los pegados hay previsualización con miniatura (`<img src={URL.createObjectURL(blob)}>`) en `_renderPasteList` (líneas 413-454).

**Limpieza post-submit:** `_clearPastedAfterUpload(ticketId)` (líneas 501-507) revoca los `URL.createObjectURL(...)` para evitar memory leaks. Se dispara vía `form.addEventListener('htmx:afterRequest', ...)` cuando `ev.detail.successful` (línea 537-541).

**Toasts para eventos servidor:** catálogo `_evtMsgs` líneas 274-297 — incluye `adjunto-subido` y `adjunto-eliminado`. Mensaje personalizado: `e.detail.count + ' archivo(s) subido(s) correctamente'` (línea 293).

### 4.3 Visualización de adjuntos ya subidos (iconos por tipo, thumbnails)

Sección archivo /workspace/app/templates/tickets/detalle_modal.py:676-781. Resumen del patrón (entre líneas 681-730):

- Detección de tipo (líneas 680-683):
  ```jinja
  {% set _mime = (a.mime_type or '') %}
  {% set _ext = (a.nombre_original or a.filename or a.nombre or '').split('.')[-1].lower() ... %}
  {% set es_imagen = a.es_imagen if a.es_imagen is defined else (_mime.startswith('image/') or _ext in ['png','jpg','jpeg','gif','webp','bmp','svg','avif']) %}
  {% set _disponible = (a.disponible if a.disponible is defined else None) %}
  ```
- Si es imagen y está disponible → `<a href="/api/v1/adjuntos/{{ a.id }}/descargar" data-preview-image data-preview-title="...">` con un `<img loading="lazy" class="w-12 h-12 object-cover rounded ...">` (el atributo `data-preview-image` activa el lightbox en `/workspace/app/static/js/image-preview.js`).
- Si es imagen pero NO disponible → placeholder ámbar con icono de warning (`M12 9v2m0 4h.01M4.93 19h14.14c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.2 16c-.77 1.33.19 3 1.73 3z`).
- Si NO es imagen → icono "paperclip" SVG.
- Cada fila muestra: thumb/icon, nombre, `tamano_legible`, badge "No disponible" si aplica, link "Descargar" (oculto si no hay archivo), y botón eliminar sólo si `_puede_borrar` (lógica de §3.2).

---

## 5. Migraciones — `app/db/migrations.py`

Patrón ad-hoc (sin Alembic). Pensado para ser idempotente y correr en **cada arranque**.

### 5.1 Estructura de `app/db/migrations.py`

| Símbolo | Línea | Tipo | Descripción |
|---|---|---|---|
| `COLUMNS_TO_ADD` | 42-110 | `Dict[str, Dict[str, Tuple[str,str] | str]]` | Tabla → columna → (tipo_pg, tipo_sqlite). Si es `str`, se usa para ambos. |
| `INDEXES` | 114-139 | `List[Tuple[str, str]]` | `(nombre_logico, CREATE INDEX IF NOT EXISTS ...)` idempotente |
| `TABLES_REQUIRED` | 144-147 | `List[str]` | Set auxiliar para tooling externo |
| `_get_default_engine()` | 33-36 | helper | Import lazy del engine desde `app.db.session` |
| `_get_existing_columns(eng, table)` | 150-155 | helper | `set` con columnas; vacío si tabla no existe |
| `_resolve_type(eng, type_def)` | 158-163 | helper | `(pg, sqlite)` → string para el motor en uso |
| `_column_exists(eng, table, column)` | 166-168 | helper | Booleano portable |
| `apply_migrations(eng=None)` | 171-253 | función pública | Punto de entrada. Devuelve `Dict[str,int]` con `applied, skipped, indexes, errors, tables_created, data_migrated`. |
| `_apply_data_migrations(conn, eng)` | 256-... | helper interno | Migraciones de datos SQL idempotentes |
| `report_schema_drift(eng=None)` | 794 | función pública | Diagnóstico |

> **Convención** (`/workspace/app/db/migrations.py:1-19`): las definiciones de tipo **NO incluyen el nombre de la columna**; el script concatena `"nombre" TIPO`. Para FKs, la tabla referenciada debe existir (se crea antes con `Base.metadata.create_all`).

### 5.2 Entradas específicas para `adjuntos`

```python
# /workspace/app/db/migrations.py:103-109
"adjuntos": {
    # Respaldo binario persistente: Railway tiene filesystem efímero y los
    # archivos en ``/app/uploads`` se borran en cada redeploy. Esta columna
    # (BYTEA en PG, BLOB en SQLite) garantiza que la descarga siga
    # funcionando aunque el archivo físico haya desaparecido.
    "contenido": ("BYTEA", "BLOB"),
},
```

Y la FK inversa desde `tickets.portada_adjunto_id` (líneas 80-83):

```python
"portada_adjunto_id": (
    "INTEGER REFERENCES adjuntos(id) ON DELETE SET NULL",
    "INTEGER REFERENCES adjuntos(id) ON DELETE SET NULL",
),
```

> **Implicación para "adjuntos en comentarios":** si añades la columna `comentario_id`, **debes** añadir su entrada en `COLUMNS_TO_ADD["adjuntos"]["comentario_id"] = ("INTEGER REFERENCES comentarios(id) ON DELETE CASCADE", ...)` (tipo PG / tipo SQLite). No hay helper tipo `ensure_column`/`add_column_if_missing` separado; el patrón es: **añadir entrada al dict `COLUMNS_TO_ADD`** y `apply_migrations` la descubre.

### 5.3 Cabecera de `apply_migrations` y flujo interno

```python
# /workspace/app/db/migrations.py:171-253
def apply_migrations(eng: Optional[Engine] = None) -> Dict[str, int]:
    """
    Aplica migraciones pendientes para alinear el esquema con los modelos.

    - Idempotente: puede ejecutarse en cada arranque.
    - Segura: usa `engine.begin()` para transaccionar; si algo falla, hace rollback.
    - Retorna un dict con estadísticas {applied, skipped, indexes, errors}.
    """
    eng = eng or _get_default_engine()
    is_pg = eng.dialect.name == "postgresql"
    is_sqlite = eng.dialect.name == "sqlite"
    stats = {"applied": 0, "skipped": 0, "indexes": 0, "errors": 0,
             "tables_created": 0, "data_migrated": 0}

    # 1) Asegurar que todas las tablas existen (no-op si ya están).
    try:
        Base.metadata.create_all(bind=eng)
        ...
    except Exception as e:
        ...

    # 2) Añadir columnas faltantes
    with eng.begin() as conn:
        for table, columns in COLUMNS_TO_ADD.items():
            existing = _get_existing_columns(eng, table)
            for column, type_def in columns.items():
                if column in existing:
                    stats["skipped"] += 1
                    continue
                col_type = _resolve_type(eng, type_def)
                try:
                    if is_pg:
                        sql = f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                    elif is_sqlite:
                        # SQLite < 3.35 no soporta IF NOT EXISTS en ADD COLUMN.
                        sql = f'ALTER TABLE {table} ADD COLUMN "{column}" {col_type}'
                    else:
                        sql = f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                    conn.execute(text(sql))
                    ...
                    stats["applied"] += 1
                except Exception as e:
                    ...

        # 3) Crear índices faltantes (IF NOT EXISTS funciona en ambos motores)
        for name, sql in INDEXES:
            try:
                conn.execute(text(sql))
                stats["indexes"] += 1
            except Exception as e:
                ...

    # 4) Migraciones de datos (idempotentes): cambios de nomenclatura
    try:
        with eng.begin() as conn:
            stats["data_migrated"] = _apply_data_migrations(conn, eng)
    except Exception as e:
        ...
    ...
    return stats
```

### 5.4 ¿Se ejecutan automáticamente al arrancar? Dónde se invocan

**Sí, en cada arranque**, dos veces (paths diferentes):

- **`/workspace/app/main.py:35-61`** — el hook `lifespan` siempre corre `apply_migrations()`:
  ```python
  """Inicialización al arranque.

  1) SIEMPRE: aplicar migraciones pendientes (idempotente, rápido, seguro).
     Esto alinea el esquema de la BD con los modelos SQLAlchemy sin
     necesidad de Alembic. Se ejecuta en cada arranque para que un
     deploy que añada columnas no rompa la app en producción.

  2) SOLO SI AUTO_INIT_DB=true o DEBUG: ejecutar init_database() que crea
     tablas faltantes y carga datos semilla. En producción NO es
     necesario porque las migraciones del paso 1 ya garantizan el
     esquema; AUTO_INIT_DB solo se activa explícitamente.
  """
  # Paso 1: migraciones idempotentes (SIEMPRE)
  try:
      from app.db.migrations import apply_migrations
      apply_migrations()
  except Exception as e:
      logger.warning(f"[startup] No se pudieron aplicar migraciones: {e}")

  # Paso 2: init completo solo si está activado
  if settings.DEBUG or os.getenv("AUTO_INIT_DB", "false").lower() == "true":
      try:
          from app.db.init_db import init_database
          init_database()
      except Exception as e:
          logger.warning(f"[startup] No se pudo inicializar la BD automáticamente: {e}")
  yield
  ```

- **`/workspace/app/db/init_db.py:53-60`** — la función `init_database()` también lo invoca al inicializar manualmente:
  ```python
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
  ```

> **Conclusión para replicar:** añadir la nueva columna al `Adjunto` es suficiente. Con que actualices el modelo y añadas una entrada en `COLUMNS_TO_ADD["adjuntos"][...]`, el siguiente arranque la aplica (post-deploy). Si necesitas un índice, añade también tupla a `INDEXES`. **No hay CLI de Alembic** ni archivos versionados de migración; todo se ejecuta en arranque.

---

## 6. Almacenamiento

### 6.1 ¿Disco local, volume, servicio externo?

- **Primario: disco local** efímero de Railway (gestionado por el contenedor).
- **Respaldo: copia binaria en BD** (`Adjunto.contenido`, columna `LargeBinary`).
- **NO hay servicio externo** (S3/GCS/Azure) implementado en este código; los comentarios en `core/config.py:86-87` (`BACKUP_DIR`) mencionan que **en producción se recomienda apuntar a un volumen persistente o servicio externo**, pero sólo para backups, no para adjuntos.

### 6.2 Constantes / paths exactos

Definidas en `/workspace/app/services/features_service.py:242-257`:

```python
# Raíz de uploads: SIEMPRE absoluta, anclada al project root. Railway tiene
# filesystem efímero (cada redeploy borra /app/uploads), por eso guardamos
# también una copia binaria en PostgreSQL (BYTEA) como respaldo persistente.
_UPLOAD_ROOT_RAW = os.environ.get("UPLOAD_DIR", "uploads")
if os.path.isabs(_UPLOAD_ROOT_RAW):
    UPLOAD_ROOT = _UPLOAD_ROOT_RAW
else:
    # Anclar al directorio raíz del proyecto (no al CWD del gunicorn,
    # que en Railway puede variar y romper rutas relativas guardadas en BD).
    _PROJECT_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
    )
    UPLOAD_ROOT = os.path.join(_PROJECT_ROOT, _UPLOAD_ROOT_RAW)
```

Resumen:

| Variable | Valor por defecto | Override | Notas |
|---|---|---|---|
| `UPLOAD_DIR` (env) | — | `os.environ.get("UPLOAD_DIR", "uploads")` | Si es absoluta se respeta; si no se ancla a `<PROJECT_ROOT>/uploads` |
| `UPLOAD_ROOT` (runtime) | `<PROJECT_ROOT>/uploads` | sólo vía `UPLOAD_DIR` | Siempre absoluta |
| `dir_destino` por subida | `os.path.join(UPLOAD_ROOT, f"ticket_{ticket.id}")` | — | Una subcarpeta por ticket |
| `nombre_storage` | `f"{uuid.uuid4().hex}{ext}"` | — | Garantiza unicidad |

### 6.3 Estructura física actual (verificada en `/workspace/uploads/`)

```
uploads/
├── ticket_1/
└── ticket_16/
```

`.gitignore` (`/workspace/.gitignore`) excluye la carpeta `# uploads/`.

### 6.4 Comportamiento ante filesystem de sólo lectura

En `guardar_archivo` (líneas 297-317), si `os.makedirs(...)` lanza `OSError` (caso típico en Railway sin volumen persistente), se hace `logger.warning(...)` y se pone `dir_destino = None`. Si `open(ruta_abs, "wb")` también falla, se asigna `ruta_abs = ""` y luego se usa el sentinela `(db-only)ticket_{id}/{nombre_storage}`. **El INSERT en BD nunca falla porque `contenido` siempre trae los bytes**.

### 6.5 Endpoint de descarga — comportamiento en filesystem efímero

`descargar_adjunto` (`features.py:853-908`) implementa el patrón "disco → BD → 410":

1. Si `adj.ruta` existe y `os.path.exists(adj.ruta)` → `FileResponse(path=ruta, ...)`.
2. Si no, pero `adj.contenido` → `Response(content=adj.contenido, ..., headers={"Content-Disposition": content_disp})` con RFC 5987 para UTF-8.
3. Si no hay ninguna fuente → `HTTPException(410)` con mensaje accionable: *"Archivo no disponible. Fue subido en una versión anterior del sistema y la copia física fue purgada del contenedor. Vuelve a subirlo para conservarlo."*

### 6.6 Otras constantes útiles para comentarios

Si replicamos en `comentarios`, conviene replicar el patrón de columna `contenido` (respaldo). Por ahora `Adjunto` ya tiene `mime_type`/`tamano_bytes`/`nombre_original` que cubren lo necesario.

---

## 7. Auditoría

### 7.1 Modelo — `/workspace/app/models/auditoria.py`

Archivo completo (47 líneas):

```python
"""
Modelo Auditoria: registro obligatorio e inmutable de cada cambio relevante.
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Auditoria(Base, TimestampMixin):
    """
    Bitácora de auditoría del sistema. Se inserta un registro por:
    - Cambio de estado (drag & drop en Kanban)
    - Asignación
    - Edición de campos
    - Cierre
    """
    __tablename__ = "auditorias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ticket_id es NULLABLE: la tabla registra eventos tanto de tickets
    # (cambio de estado, asignación, cierre) como de usuarios/seguridad
    # (envío de credenciales, login, edición de perfil). Para los eventos
    # no asociados a un ticket, ticket_id queda en NULL.
    ticket_id = Column(
        Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    # ``usuario_id`` es NULL para eventos del sistema (deadline_notifier,
    # triggers automáticos).
    usuario_id = Column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=True, index=True
    )
    accion = Column(String(80), nullable=False, index=True)
    valor_anterior = Column(JSON, nullable=True)
    valor_nuevo = Column(JSON, nullable=True)
    comentario = Column(Text, nullable=True)
    ip_origen = Column(String(64), nullable=True)

    # Relaciones
    ticket = relationship("Ticket", back_populates="auditorias")
    usuario = relationship("Usuario", back_populates="auditorias")

    def __repr__(self) -> str:
        return f"<Auditoria ticket={self.ticket_id} accion={self.accion}>"
```

**Convención de `accion` (strings lowercase snake_case):** `"adjunto_subido"`, `"adjunto_eliminado"` (ver §7.3).

### 7.2 Helper `registrar_auditoria` — `/workspace/app/services/auditoria_service.py`

Archivo completo (38 líneas):

```python
"""
Servicio de Auditoría: insert obligatorio tras cada acción crítica.
"""
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria
from app.models.usuario import Usuario


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

**Firma exacta (referencia para replicar en comentarios):**
```python
registrar_auditoria(
    db: Session,
    ticket_id: int,
    usuario_id: int,
    accion: str,
    valor_anterior: Optional[Dict[str, Any]] = None,
    valor_nuevo: Optional[Dict[str, Any]] = None,
    comentario: Optional[str] = None,
    ip_origen: Optional[str] = None,
    commit: bool = True,
) -> Auditoria
```

**Detalle crítico:** el parámetro `commit=True` solo hace `db.flush()` — **no hace `db.commit()`**. Esto es importante porque `AdjuntoService.guardar_archivo()` ya hace `self.db.commit()` internamente y `eliminar_adjunto()` además hace su propio `db.commit()` (ver §7.3). Si NO se hace commit después de `registrar_auditoria(...)`, el registro se descarta cuando se cierra la sesión — esto fue un bug histórico, documentado en el propio código fuente.

### 7.3 Flujo de auditoría en adjuntos — código TEXTUAL

**Al subir (`features.py:827-829`):**

```python
subidos.append(adj)
registrar_auditoria(db, ticket.id, user.id, "adjunto_subido", valor_nuevo={
    "adjunto_id": adj.id, "nombre": adj.nombre_original, "tamano": adj.tamano_bytes
})
```

> El `db.commit()` aquí lo garantiza `AdjuntoService.guardar_archivo()` que termina con `self.db.commit(); self.db.refresh(adj)` (líneas 332-333).

**Al eliminar (`features.py:929-981`) — patrón completo, crítico:**

```python
@router.delete("/adjuntos/{adjunto_id}")
async def eliminar_adjunto(adjunto_id: int, request: Request, db, user):
    """Elimina un adjunto. Si viene de HTMX devuelve el modal re-renderizado;
    si no, devuelve 204.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    active_tab = "adjuntos"
    if is_htmx:
        try:
            form = await request.form()
            active_tab = (form.get("active_tab") or "adjuntos").strip() or "adjuntos"
        except Exception:
            pass
    adj = AdjuntoService(db).obtener(adjunto_id)
    if not adj:
        if is_htmx:
            return HTMLResponse(
                content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">Adjunto no encontrado.</div>',
                status_code=404,
            )
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    if adj.usuario_id != user.id and user.rol not in (RolUsuario.ADMINISTRADOR,):
        if is_htmx:
            return HTMLResponse(
                content='<div class="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700">No autorizado para eliminar.</div>',
                status_code=403,
            )
        raise HTTPException(status_code=403, detail="No autorizado para eliminar")
    ticket_id = adj.ticket_id
    # Capturar metadatos ANTES de eliminar: el ORM marca el objeto como
    # eliminado al hacer db.delete(), pero los atributos siguen accesibles
    # hasta el commit. Los preservamos para enriquecer la auditoría con
    # información útil para la trazabilidad (nombre, tamaño, mime, autor).
    adj_meta = {
        "adjunto_id":      adjunto_id,
        "nombre_original": adj.nombre_original,
        "nombre_storage":  adj.nombre_storage,
        "tamano_bytes":     adj.tamano_bytes,
        "mime_type":        adj.mime_type,
        "subido_por_id":    adj.usuario_id,
    }
    AdjuntoService(db).eliminar(adjunto_id)
    # FIX-TRAZABILIDAD-ADJUNTO (bug del usuario):
    #   ``AdjuntoService.eliminar()`` hace ``self.db.commit()`` internamente
    #   para persistir el DELETE, pero ``registrar_auditoria()`` solo hace
    #   ``db.flush()``. Sin un ``db.commit()`` posterior, el INSERT de la
    #   auditoría quedaba en la sesión y se DESCARTABA al cerrar ``get_db()``
    #   (que solo hace ``db.close()`` sin commit).
    #   Síntoma reportado: el adjunto SÍ se borraba del disco y de la BD,
    #   pero el evento NO aparecía en la pestaña Trazabilidad.
    registrar_auditoria(
        db, ticket_id, user.id, "adjunto_eliminado",
        valor_anterior=adj_meta,
        comentario=f"Archivo eliminado: {adj_meta['nombre_original']}",
    )
    db.commit()  # CRÍTICO: persiste la auditoría antes de cerrar la sesión
    if is_htmx:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if ticket:
            html = _render_detalle_modal_response(db, ticket, user, active_tab=active_tab)
            return HTMLResponse(
                content=html,
                status_code=200,
                headers={"HX-Trigger": "adjunto-eliminado"},
            )
    return Response(status_code=204)
```

**Lección clave replicable en comentarios:**

1. **Capturar metadatos ANTES** de `db.delete()` (los atributos siguen accesibles después del `delete()`, pero por seguridad se copian a un dict).
2. Llamar al servicio que elimina (hace su propio `commit()`).
3. Llamar a `registrar_auditoria(...)` (sólo hace `flush()`).
4. **Hacer `db.commit()` explícito al final** — sin esto la auditoría se pierde.

> Helper de la pestaña Trazabilidad (catálogo de labels legibles) vive en `features.py:1145-1152`:
> ```python
> "ADJUNTO_SUBIDO": "subió un adjunto",
> "ADJUNTO_ELIMINADO": "eliminó un adjunto",
> ```

---

## 8. Resumen ejecutivo — patrones a replicar en `comentarios`

Si vamos a adjuntar archivos a comentarios, los patrones exactos a copiar son:

| Componente | Dónde mirar | Acción concreta |
|---|---|---|
| **Modelo** | `/workspace/app/models/adjunto.py` | (a) `comentario_id = Column(Integer, ForeignKey("comentarios.id", ondelete="CASCADE"), nullable=True, index=True)` o (b) tabla nueva `comentario_adjuntos` |
| **Migración** | `/workspace/app/db/migrations.py:42-110` | Añadir entrada en `COLUMNS_TO_ADD["adjuntos"]["comentario_id"] = ("INTEGER REFERENCES comentarios(id) ON DELETE CASCADE", "INTEGER REFERENCES comentarios(id) ON DELETE CASCADE")` |
| **Constantes upload** | `/workspace/app/services/features_service.py:258-265` | Reutilizar `MAX_FILE_SIZE = 25*1024*1024` y `ALLOWED_EXT`; la función `_extension` (272-274) puede moverse a un módulo `app/core/uploads.py` para compartirla |
| **Storage dual** | `/workspace/app/services/features_service.py:297-330` | Patrón: intenta disco, si falla usa sentinela `(db-only)ticket_{X}/...`; siempre persiste bytes en `contenido` |
| **Endpoint subida** | `/workspace/app/api/v1/features.py:756-850` | Misma forma: `@router.post(".../comentarios/{comentario_id}/adjuntos")`, mismos campos (`archivo`/`archivos`/`descripcion`), HTMX re-render + `HX-Trigger`. Llamar a `AdjuntoService.guardar_archivo(comentario_id=...)` (refactor para aceptar ticket o comentario). |
| **Endpoint descarga** | `/workspace/app/api/v1/features.py:853-908` | Idéntico. |
| **Endpoint eliminar** | `/workspace/app/api/v1/features.py:911-981` | Misma regla de permisos: autor de la subida o Admin. Capturar metadatos antes de `db.delete()`. |
| **Auditoría** | `/workspace/app/services/auditoria_service.py` | Usar `registrar_auditoria(db, ticket_id=ticket_id_del_comentario, usuario_id=user.id, accion="comentario_adjunto_subido", valor_nuevo={...})`. **`db.commit()` obligatorio después.** |
| **Template** | `/workspace/app/templates/tickets/detalle_modal.py:676-827` | Reutilizar el bloque `<form hx-post ... hx-encoding="multipart/form-data">` con el mismo dropzone (clase `adjuntos-dropzone`, `data-ticket-id`, previews, etc.); cambiar el `data-ticket-id` por `data-comentario-id` y el `hx-post` para apuntar al endpoint nuevo. Reutilizar también el CSS de badges `Admin`/`Creador`. |
| **JS paste/drop** | `/workspace/app/static/js/htmx-events.js:299-612` | Generalizar `setupAdjuntosDropzone` parametrizando el prefijo de IDs (`adjuntos-form-{id}` → `comentario-form-{id}`). La lógica de `DataTransfer` es agnóstica del destino. Constante `MAX_PASTE_BYTES = 25*1024*1024` ya es reutilizable. |

### 8.1 Hallazgos a vigilar de cerca (deuda técnica)

1. **No hay validación magic-number / firma real del archivo.** Sólo se valida la extensión. Un usuario renombrando `evil.exe` → `malware.png` subiría sin problema. Para producción endurecer con `python-magic` o detectar magic-bytes.
2. **No se sanitiza `nombre_original`** con `werkzeug.utils.secure_filename`. El nombre se persiste tal cual y se muestra en HTML (escaped), pero igualmente confiar sólo en el escapado de Jinja es frágil.
3. **La persistencia dual disco+BD** funciona, pero siempre escribe el binario completo en `contenido` en cada subida: con adjuntos grandes la BD crece mucho. Considerar poner `contenido` opcional / limpiar tras confirmar que el disco es persistente (volume montado).
4. **`eliminar_adjunto` requiere `db.commit()` extra** posterior a `registrar_auditoria()`. Este bug histórico podría repetirse en el endpoint homónimo de comentarios; conviene crear un helper `audit_and_commit(db, ticket_id, user, accion, ...)` que centralice.
5. **No existe endpoint para listar adjuntos HUÉRFANOS / limpieza** — crecerá el filesystem sin control.

---

## 9. Apéndice — Inventario de archivos citados

| Ruta | Estado |
|---|---|
| `/workspace/app/models/adjunto.py` | leído completo (73 líneas) |
| `/workspace/app/models/auditoria.py` | leído completo (47 líneas) |
| `/workspace/app/models/__init__.py` | leído completo (62 líneas) |
| `/workspace/app/models/usuario.py` | parcial — sólo rol enum |
| `/workspace/app/services/auditoria_service.py` | leído completo (38 líneas) |
| `/workspace/app/services/features_service.py` | parcial (líneas 1-30 y 240-359) |
| `/workspace/app/api/v1/features.py` | parcial (líneas 1-60, 740-985) |
| `/workspace/app/api/v1/deps.py` | leído completo (111 líneas) |
| `/workspace/app/api/v1/router.py` | leído completo (65 líneas) |
| `/workspace/app/api/v1/tickets.py` | grep parcial (no contiene endpoints de adjunto — están todos en `features.py`) |
| `/workspace/app/schemas/features.py` | leído completo (283 líneas) |
| `/workspace/app/templates/tickets/detalle_modal.py` | parcial (líneas 676-827) |
| `/workspace/app/static/js/htmx-events.js` | parcial (líneas 260-612) |
| `/workspace/app/core/config.py` | leído completo (131 líneas) |
| `/workspace/app/db/migrations.py` | parcial (líneas 1-339) |
| `/workspace/app/db/init_db.py` | parcial (líneas 30-110) |
| `/workspace/app/main.py` | parcial (líneas 35-128) |
| `/workspace/uploads/` | directorio físico con `ticket_1/` y `ticket_16/` |
| `/workspace/.gitignore` | entrada `# uploads/` línea correspondiente |

---

*Documento generado para soportar la siguiente tarea: añadir carga de archivos a `Comentario` replicando los patrones de `Adjunto`.*
