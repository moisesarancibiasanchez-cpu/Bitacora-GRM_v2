# Reporte de Seguridad — Bitácora GRM v2

**Fecha:** 2026-09-11
**Commit de fix:** `73f0154` — *fix(security): eliminar auto-login como admin y cerrar backdoors de autenticación*
**Repositorio:** https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git
**Severidad del hallazgo original:** **CRÍTICA**

---

## 1. Resumen ejecutivo

Se detectó una vulnerabilidad **crítica** de control de acceso: cada vez que un usuario
accedía a la plataforma se autenticaba **de forma automática como el primer Administrador
disponible**, sin necesidad de credenciales, entregando acceso total a todas las
funcionalidades administrativas (gestión de usuarios, dashboards, butler, etc.).

La causa de fondo fue un **"modo demo"** heredado del desarrollo que quedó activo en
producción. Se identificaron **5 vulnerabilidades** relacionadas y se aplicaron
**6 correcciones**.

Después de los fixes, la validación end-to-end confirmó:

| Escenario                                    | Resultado esperado   | Resultado real |
| -------------------------------------------- | -------------------- | -------------- |
| GET /kanban sin sesión                       | Redirect a /auth/login | **302 ✓**     |
| GET /usuarios sin sesión                     | Redirect a /auth/login | **302 ✓**     |
| POST /api/v1/auth/login (admin/admin123)     | 200 + cookie JWT     | **200 ✓**      |
| POST /api/v1/auth/login (password incorrecto)| 401                  | **401 ✓**      |
| GET /api/v1/usuarios con header X-User-Id: 1 | 401 (bypass cerrado) | **401 ✓**      |
| GET /usuarios como Solicitante               | Redirect (no admin)  | **307 → /kanban ✓** |
| GET /api/v1/usuarios como Solicitante        | 403                  | **403 ✓**      |
| GET /kanban como Administrador               | 200                  | **200 ✓**      |
| GET /dashboard, /espacios, /tableros, /butler, /notificaciones, /vistas/calendario, /importar-exportar (admin) | 200 | **200 ✓** |
| Primer registro vía /auth/registro           | Administrador        | **OK ✓**       |
| Segundo registro                             | Solicitante          | **OK ✓**       |

---

## 2. Vulnerabilidades detectadas

### V1 — Auto-login en rutas de página (CRÍTICA)

**Archivo:** `app/main.py`
**Causa:** La función auxiliar `_get_usuario_actual(request)` y la función
`_usuario_demo(db)` recurrían como fallback a "el primer usuario con rol
Administrador activo" cuando no encontraban una sesión válida. Esto significaba
que **cualquier visitante sin cookie ni credenciales quedaba autenticado como admin**.

Patrones afectados en `app/main.py`:

- `_get_usuario_actual()` con fallback a `db.query(Usuario).filter(rol=ADMIN).first()`
- Función `_usuario_demo(db)` (mismo fallback) usada por 8 rutas
- 3 patrones inline que replicaban el mismo fallback

**Impacto:** Acceso administrativo total sin autenticación. Cualquier persona con
conexión a la URL podía gestionar usuarios, ver datos sensibles y ejecutar
automatizaciones.

**Fix:** `_get_usuario_actual()` ahora retorna `None` si no hay sesión; todas las
rutas de página pasan por `_require_session_or_redirect()` que redirige a
`/auth/login` con HTTP 302. Se eliminó por completo `_usuario_demo()` y los
3 patrones inline.

**Rutas corregidas (todas requieren sesión válida):**

- `/kanban`
- `/usuarios`, `/usuarios/tabla`, `/usuarios/nuevo`, `/usuarios/{id}/editar`
- `/espacios`, `/tableros`
- `/vistas/tabla`, `/vistas/calendario`, `/vistas/timeline`
- `/dashboard`, `/butler`, `/notificaciones`
- `/tickets`, `/tickets/tabla`, `/tickets/nuevo`, `/tickets/crear`, `/tickets/exportar-csv`
- `/catalogos`
- `/importar-exportar`

### V2 — Login inicial NO usaba cuenta registrada

**Archivo:** `app/main.py` (rutas raíz)
**Causa:** Por la misma V1, el usuario entraba a `/` y se le autenticaba como
admin automáticamente, sin pasar nunca por la pantalla de login.

**Fix:** Cubierto por V1. La ruta `/` también requiere sesión válida; un visitante
es redirigido a `/auth/login` donde debe autenticarse con credenciales
registradas o crear una cuenta (el primer registro se vuelve Administrador
automáticamente).

### V3 — Seed de usuarios demo con contraseñas codificadas (ALTA)

**Archivo:** `app/db/init_db.py` → `seed_usuarios()`
**Causa:** Al inicializar la BD se creaban 4 cuentas con contraseñas de dominio público
(`admin/admin123`, `agente1/agente123`, `lider/lider123`, `usuario1/user123`).
Si la BD se inicializaba en producción sin que el operador lo advirtiera, quedaban
cuentas con credenciales conocidas dentro del sistema.

**Fix:** `seed_usuarios()` ahora **solo** crea los usuarios demo si la variable
de entorno `SEED_DEMO_USERS=true` está definida de forma explícita. Por defecto
(`false`) NO se crea ninguna cuenta demo; el operador debe registrar la primera
cuenta a través de `/auth/registro` (que asigna de manera automática el rol
Administrador al primer usuario).

```python
SEED_DEMO_USERS_ENABLED = os.getenv("SEED_DEMO_USERS", "false").lower() == "true"

def seed_usuarios(db: Session):
    if db.query(Usuario).count() > 0:
        return
    if not SEED_DEMO_USERS_ENABLED:
        print("  · Seed de usuarios demo DESHABILITADO ...")
        return
    # ... (solo si SEED_DEMO_USERS=true)
```

### V4 — Bypass X-User-Id header (CRÍTICA)

**Archivo:** `app/api/v1/deps.py` → `get_current_user()`
**Causa:** La dependencia de FastAPI aceptaba el header `X-User-Id` para resolver
el usuario actual. **Cualquier petición** con `X-User-Id: 1` quedaba autenticada como
el usuario con `id=1` (el admin) sin necesidad de cookie ni credencial.

**Fix:** La rama X-User-Id queda **DESHABILITADA por defecto**. Solo se activa
si se define de forma explícita `ALLOW_XUSER_HEADER=true` (uso exclusivo de
pruebas internas; NUNCA en producción). Validado: con la variable en `false`,
`GET /api/v1/usuarios` con `X-User-Id: 1` retorna **401** (backdoor cerrado).

```python
ALLOW_XUSER_HEADER = os.getenv("ALLOW_XUSER_HEADER", "false").lower() == "true"

# En get_current_user:
if user_id is None and ALLOW_XUSER_HEADER:
    x_user = request.headers.get("X-User-Id")
    # ...
```

### V5 — Incompatibilidad passlib/bcrypt (MEDIA → corregida)

**Archivo:** `app/core/security.py`
**Causa:** `passlib 1.7.4` es incompatible con `bcrypt>=4.0`. El `__about__`
deprecado y la función interna `detect_wrap_bug` (que supera los 72 bytes)
provocaban `AttributeError` y `ValueError` que rompían `verify_password()`.
Esto provocaba que **ningún login funcionara** después de actualizar dependencias
(los hashes generados por passlib devolvían `False` aunque la contraseña fuera
correcta).

**Fix:** Se reemplazó passlib por uso directo de `bcrypt` con truncamiento
explícito a 72 bytes (límite del algoritmo). Los hashes existentes generados
por passlib siguen siendo compatibles porque ambos usan el formato estándar
`$2b$...$` de bcrypt.

```python
import bcrypt
_BCRYPT_ROUNDS = 12

def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_to_bcrypt_bytes(password), salt).decode("ascii")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False
```

---

## 3. Cambios por archivo

| Archivo | Líneas +/- | Descripción |
| ------- | ---------- | ----------- |
| `app/main.py`              | +146 / −128 | `_get_usuario_actual` retorna None sin sesión. Eliminada `_usuario_demo`. Las 18 page routes usan `_require_session_or_redirect`. 3 patrones inline eliminados. |
| `app/api/v1/deps.py`       | +18 / −3    | Gate `ALLOW_XUSER_HEADER` (default false) cierra el bypass X-User-Id. |
| `app/core/security.py`     | +18 / −13   | Reemplazo de passlib por `bcrypt` directo. Truncamiento a 72 bytes. |
| `app/db/init_db.py`        | +25 / −7    | Gate `SEED_DEMO_USERS` (default false) evita crear cuentas demo. |
| **Total**                  | **+230 / −128** | **4 archivos, 358 líneas modificadas** |

Commit: `73f0154` (rama `main`, pusheado a `origin/main`).

---

## 4. Validación de roles y perfiles

El modelo de roles del sistema (`app/models/usuario.py`) define 5 roles:

| Rol               | Permisos clave |
| ----------------- | -------------- |
| `ADMINISTRADOR`   | Acceso total: gestión de usuarios, configuración, todos los tableros. |
| `AGENTE_SENIOR`   | Cerrar tickets, cancelar con justificación, supervisar agentes. |
| `AGENTE`          | Atender tickets asignados, transiciones operativas. |
| `SOLICITANTE`     | Crear tickets propios, comentar en sus tickets. Sin acceso a `/usuarios`. |
| `OBSERVADOR`      | Solo lectura. |

La validación confirmó:

- **Solicitante (usuario1)** puede iniciar sesión y acceder a `/kanban` (200), pero al
  intentar `/usuarios` recibe **HTTP 307 → /kanban** (redirect por no ser admin).
- **Solicitante** en endpoints solo-admin recibe **HTTP 403**.
- **Administrador** accede sin restricciones a todas las páginas (200).
- El **primer usuario que se registra** vía `/auth/registro` recibe
  de manera automática el rol `ADMINISTRADOR`.
- Los registros posteriores reciben `SOLICITANTE` por defecto.

---

## 5. Recomendaciones operativas

1. **No activar `ALLOW_XUSER_HEADER=true` en producción.** Esta variable está pensada
   solo para entornos de prueba internos. Verificar con:

   ```bash
   echo "ALLOW_XUSER_HEADER=$ALLOW_XUSER_HEADER"
   # Debe estar vacía o ser 'false'
   ```

2. **No activar `SEED_DEMO_USERS=true` en producción.** Si requieres
   `admin/admin123` y cuentas demo en local, hazlo en una base de datos
   aparte:

   ```bash
   # Solo para desarrollo local:
   USE_SQLITE=true SEED_DEMO_USERS=true python -m app.db.init_db
   ```

3. **El primer usuario que se registre en una instalación limpia será
   Administrador.** Asegúrate de que esa primera cuenta utilice una contraseña
   robusta (≥ 12 caracteres, combinación de tipos) y de que las cuentas
   siguientes se creen de manera explícita con el rol apropiado desde la
   consola de administración.

4. **Rotar la `SECRET_KEY` del JWT** de forma periódica (está en
   `app/core/config.py` → `settings.SECRET_KEY`). Al rotarla, todas las
   sesiones vigentes se invalidan, lo que forzará un nuevo inicio de sesión.

5. **Considerar agregar 2FA** (TOTP) para cuentas con rol Administrador en
   una próxima iteración.

6. **Habilitar HTTPS** (Let's Encrypt) y revisar que el flag
   `secure=True` de la cookie `access_token` esté activo en el proxy
   inverso de producción (actualmente `httponly=True, samesite="lax"`).

---

## 6. Resumen final

| Antes                                            | Después                                       |
| ------------------------------------------------ | --------------------------------------------- |
| Cualquier visitante → admin de forma automática  | Login obligatorio con credenciales registradas |
| `X-User-Id: 1` → admin (sin auth)                | 401 Unauthorized                               |
| `admin/admin123` sembrado por defecto            | Solo si `SEED_DEMO_USERS=true` (de forma explícita)   |
| `passlib` roto con `bcrypt>=4.0`                 | `bcrypt` directo, compatible con hashes antiguos |
| Login con credenciales correctas → 500           | Inicio de sesión funciona correctamente                  |
| Solicitante podía entrar a `/usuarios` (admin)   | 307 → /kanban / 403 en API                    |

**Severidad del fix:** cierra una vulnerabilidad **crítica** de control de acceso
(autenticación rota + escalación de privilegios).

**Verificación final:** todos los escenarios de la tabla de la sección 1
fueron validados con `curl` contra el servidor en `127.0.0.1:8768` el
2026-09-11 01:39 UTC.
