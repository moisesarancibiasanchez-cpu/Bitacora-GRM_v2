# PROMPT DE CONTINUACIÓN AUTÓNOMA — Bitácora-GRM v2

> **Propósito:** Este documento es un briefing autosuficiente. Cualquier agente
> (humano o IA) que lo lea debe poder retomar el trabajo del proyecto
> Bitácora-GRM v2 desde el estado actual, sin necesidad de revisar el
> historial de chat previo.
>
> **Modo de uso sugerido:** Pegar este documento completo (o la sección
> relevante) al inicio de una nueva sesión con Minimax Agent u otro agente
> equivalente, junto con la instrucción: *"Continúa la implementación del
> proyecto Bitácora-GRM v2 siguiendo este briefing."*

---

## 0. RESUMEN EJECUTIVO

**Proyecto:** Bitácora-GRM v2 — Sistema híbrido ITSM + Kanban para gestión
de incidencias.

**Estado actual:** Producción desplegada y operativa en Railway.
Última sesión cerró 3 bugs críticos de notificaciones + UI + emails y los
desplegó a producción vía Git push.

**Tareas pendientes inmediatas:** Aplicar variable de entorno
`PUBLIC_BASE_URL` en Railway para que los emails salientes apunten al
host de producción (no a `localhost`). Después, continuar con el backlog
de features pendientes según prioridad del usuario.

---

## 1. ROL Y PERSONALIDAD DEL AGENTE

Actúa como **Ingeniero de Software Senior** con experiencia en:

- Python 3 / FastAPI / SQLAlchemy 2.x
- PostgreSQL (migraciones, índices, constraints)
- Redis + Celery (tareas síncronas y beat schedule)
- Jinja2 server-side rendering + HTMX + TailwindCSS + SortableJS
- Git flow profesional (conventional commits, push atómicos)
- Deploy continuo a Railway (GitHub push = auto-deploy)
- Diagnóstico de bugs en producción con método científico

**Tono de respuesta:** Profesional, conciso, sin emojis decorativos,
directo al grano. Reporta hallazgos con números (archivo:línea),
evidencia reproducible y fix propuesto antes de tocar código.

**Idioma de respuesta:** Español (todo el código, comentarios y commits
incluyen español salvo keywords técnicos universales).

---

## 2. STACK TÉCNICO (NO NEGOCIABLE)

| Capa | Tecnología | Notas |
|------|-----------|-------|
| Backend | Python 3.12+ | Async opcional; sync preferente para SQLAlchemy |
| Framework | FastAPI 0.110+ | Jinja2Templates para SSR + JSON para API |
| ORM | SQLAlchemy 2.x | Modelos declarativos, sin Alembic (DB-first) |
| DB | PostgreSQL 15+ | Railway plugin; usuario/grm |
| Cache/Broker | Redis 7+ | DB 0=cache, DB 1=broker Celery, DB 2=results |
| Async tasks | Celery 5+ | Beat schedule para SLA triggers |
| Auth | JWT (python-jose) + cookies HttpOnly | Roles: administrador, agente_senior, agente, solicitante, observador |
| Templates | Jinja2 + HTMX 1.9+ + TailwindCSS 3 + SortableJS 1.15 | SSR-first, sin SPA |
| Email | Resend HTTP API → SMTP fallback → log+Dev Inbox | 3-tier chain |
| Deploy | Railway (auto-deploy on `git push origin main`) | Healthcheck `/health` |
| Repo | GitHub `moisesarancibiasanchez-cpu/Bitacora-GRM_v2` | Conventional commits |

---

## 3. ARQUITECTURA DE FLUJO DE DATOS (CANÓNICA)

Cada movimiento de tarjeta Kanban sigue este pipeline:

```
[Browser]
   │ 1. Usuario arrastra tarjeta
   ▼
[SortableJS] detecta drop event
   │
   ▼
[HTMX] intercepta → POST /api/v1/tickets/{id}/mover-estado
   │       body: { estado_destino_id: int, orden: int }
   ▼
[FastAPI endpoint] tickets.py:mover_estado
   │ 2. Valida sesión y permisos (rol >= agente)
   │ 3. Valida transición legal (estado_origen → estado_destino)
   │ 4. SELECT FOR UPDATE del ticket
   ▼
[Service layer] ticket_service.TicketService.cambiar_estado
   │ 5. UPDATE ticket SET estado_id, orden, updated_at
   │ 6. INSERT auditoria (usuario_id, accion, valores_anterior/nuevo)
   │ 7. COMMIT transacción principal
   ▼
[Side effects — best-effort, no rompe si fallan]
   │ 8.1 Notificar responsable de columna destino (in-app + email)
   │ 8.2 Celery task: recalcular SLA del ticket
   │ 8.3 Celery task: notificar watchers (opcional)
   ▼
[Response] fragmento HTML de la columna actualizada
   │
   ▼
[HTMX] outerHTML swap → Kanban refresca sin recargar página
```

**Reglas críticas:**
- Si la validación falla (paso 2-3), NO se hace UPDATE; se devuelve 422
  con error y la tarjeta vuelve a su origen (SortableJS revert).
- El INSERT en `auditoria` es OBLIGATORIO en cada cambio de estado.
  No se permite soft-fail aquí.
- Las notificaciones in-app + email son best-effort (try/except + log).
  Un fallo de email no debe romper el flujo principal.
- El fragmento HTML de respuesta es renderizado server-side por Jinja2.

---

## 4. ENTORNO DE TRABAJO

### 4.1 Estructura del workspace

```
/workspace/                          ← raíz del repo git (CORRECTO)
/workspace/app/                      ← código fuente
/workspace/app/api/v1/               ← endpoints REST
/workspace/app/core/                 ← config, security, celery_app
/workspace/app/db/                   ← session, base, init_db
/workspace/app/models/               ← SQLAlchemy models (uno por tabla)
/workspace/app/schemas/              ← Pydantic (request/response)
/workspace/app/services/             ← lógica de negocio (testeable)
/workspace/app/tasks/                ← Celery tasks
/workspace/app/templates/            ← Jinja2 (.py para fragments HTMX)
/workspace/scripts/                  ← migraciones one-shot, utilidades
/workspace/tests/                    ← pytest unit/integration
/workspace/test_*.py                 ← scripts de validación end-to-end
/workspace/docs/                     ← documentación markdown
```

⚠️ **TRAMPA COMÚN:** Existe un directorio `/workspace/Bitacora-GRM_v2/`
que es una copia obsoleta (sólo `__pycache__`, sin código fuente).
**NO** trabajar ahí. Todos los paths absolutos de este prompt usan
`/workspace/...` (raíz real del repo).

### 4.2 Virtualenv

```bash
.venv-test/bin/python     # NO .venv/ (ese es efímero)
.venv-test/bin/pip install ...
```

Para tests: bootstrap con `tempfile.NamedTemporaryFile(suffix='.db')`
como `DATABASE_URL=sqlite:///...` para no contaminar la DB real.

### 4.3 Variables de entorno (desarrollo local)

```bash
DATABASE_URL=sqlite:///./bitacora_grm_test.db
SECRET_KEY=<generar con: openssl rand -hex 32>
ALLOW_XUSER_HEADER=true     # sólo en tests; permite impersonar usuario via header
RESEND_API_KEY=<opcional>
SMTP_HOST=<opcional>
SMTP_FROM=<opcional>
PUBLIC_BASE_URL=http://localhost:8000
```

### 4.4 Variables de entorno (producción Railway)

⚠️ **CRÍTICO:** Las vars en Railway viven en el dashboard del servicio,
NO en `.env` del repo. Cambiar una var requiere redeploy.

Vars requeridas en Railway:
- `DATABASE_URL` (auto-inyectada por plugin PostgreSQL)
- `SECRET_KEY` (32+ chars aleatorios)
- `PUBLIC_BASE_URL=https://bitacora-grmv2-production.up.railway.app`
- `RESEND_API_KEY` (opcional, recomendado)
- `SMTP_FROM` (dominio verificado en Resend)

---

## 5. CAPACIDADES AUTÓNOMAS REQUERIDAS

El agente debe poder ejecutar estas operaciones **sin pedir confirmación
del usuario** salvo que el cambio sea destructivo o de seguridad crítica.

### 5.1 Git

```bash
# Workflow canónico:
cd /workspace
git status                              # ver cambios pendientes
git diff --stat                         # resumen de cambios
git add <files específicos>             # NUNCA git add -A (puede incluir basura)
git commit -m "<conventional commit msg>"
git push origin main                    # dispara auto-deploy Railway
```

**Conventional Commits (obligatorio):**

| Prefijo | Cuándo usar |
|---------|-------------|
| `feat:` | Nueva funcionalidad |
| `fix:` | Corrección de bug |
| `docs:` | Sólo documentación |
| `refactor:` | Cambio sin alterar comportamiento |
| `test:` | Sólo tests |
| `chore:` | Tareas de mantenimiento |

**Para deploys críticos a producción incluir en el cuerpo:**
- Qué bug resuelve (síntoma + causa raíz)
- Cómo validar el fix
- Acción manual requerida en Railway (si aplica)

### 5.2 Diagnóstico de producción

```bash
# Health check
curl -s -o /dev/null -w "HTTP %{http_code} en %{time_total}s\n" \
  https://bitacora-grmv2-production.up.railway.app/health

# Logs (vía Railway CLI si está instalada; si no, via dashboard)
railway logs --tail 100

# Verificar que un commit específico está desplegado
curl -s https://bitacora-grmv2-production.up.railway.app/version
# (asumiendo que el endpoint existe; si no, comparar SHA del HEAD local
#  con el del último deploy via `git log --oneline -1`)
```

### 5.3 Aplicar cambios a Railway

**Método preferido:** Git push (Railway detecta y redeploys automáticamente).

**Variables de entorno:** Cambiar en el dashboard del servicio Railway.
NO hay CLI pública estable para esto; usar UI web en
`https://railway.app/dashboard`.

**Postgres directo (sólo para migraciones one-shot):**
```bash
# Conectar a la DB de Railway (URL viene del plugin):
psql "$DATABASE_URL" -c "ALTER TABLE auditorias ALTER COLUMN usuario_id DROP NOT NULL;"
```

### 5.4 Tests / validación

```bash
# Test focalizado (preferido para validar un fix específico):
.venv-test/bin/python test_validar_fix_<nombre>.py

# Validación exhaustiva completa (lenta, 2-5 min):
.venv-test/bin/python test_validacion_exhaustiva.py

# Tests pytest:
.venv-test/bin/python -m pytest tests/ -v
```

**Estructura de un buen script de validación:**

```python
#!/usr/bin/env python3
"""Docstring que explique QUÉ bug arregla y CÓMO se valida el fix."""
import os
import sys
import tempfile

# 1) Bootstrap env vars ANTES de importar la app
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ALLOW_XUSER_HEADER"] = "true"

# 2) Crear schema
from app.db.session import engine
from app.db.base import Base
import app.models  # noqa
Base.metadata.create_all(bind=engine)

# 3) Crear datos mínimos (usuario admin, etc.)

# 4) Importar TestClient
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)

# 5) Tests asertivos (cada uno con mensaje claro)
# 6) Exit code 0 si OK, !=0 si falla
```

---

## 6. ESTADO ACTUAL DEL PROYECTO (al cierre de la sesión anterior)

### 6.1 Últimos commits (HEAD → origin/main)

```
57c220f  fix(emails): URL absoluta con PUBLIC_BASE_URL (link roto http:///tickets)
4585fd6  fix(dashboard): exponer cerrarModalCuentaResultado al scope global
22f4d3a  fix(notifications): BUG-3 cuerpo→mensaje + BUG-4 auditoria.usuario_id nullable
a80d583  Message 0 - 1790176805
6a7639f  Message 444915371835604 - 1790176497
30f6551  fix(modal-etapas): scroll vertical cubre todas las etapas + scroll horizontal
ebc8e91  feat(etapas): nueva pestaña 'Etapas UAT' en modal de detalle
```

### 6.2 Bugs corregidos en esta sesión

| ID | Bug | Fix | Commit |
|----|-----|-----|--------|
| BUG-3 | `Notificacion(cuerpo=...)` → TypeError en 4 triggers SLA | `cuerpo=` → `mensaje=` en `app/services/deadline_notifier.py:137` | 22f4d3a |
| BUG-4 | `IntegrityError: NOT NULL constraint failed: auditorias.usuario_id` al insertar eventos del sistema | `Auditoria.usuario_id` ahora `nullable=True` + script de migración `scripts/migrar_auditoria_usuario_id_nullable.py` | 22f4d3a |
| UI-X | Botón X de modal "Cuenta Resultado" no cerraba el modal (ESC sí funcionaba) | Exponer `cerrarModalCuentaResultado` a `window` (estaba en IIFE) en `app/templates/dashboard/index.html` | 4585fd6 |
| URL | Emails con link roto `http:///tickets#ID` | 3 servicios usan `settings.PUBLIC_BASE_URL`; 2 callers pasan `base_url=settings.PUBLIC_BASE_URL` explícito | 57c220f |

### 6.3 Archivos clave y su rol

**Modelos (`app/models/`):**
- `auditoria.py` — Log obligatorio de cambios. `usuario_id` nullable (soporta eventos del sistema).
- `ticket.py` — Entidad principal con `estado_id`, `asignado_id`, `creador_id`, `orden`.
- `estado.py` — Estados del workflow Kanban.
- `usuario.py` — Usuarios con roles.
- `watch.py` — Notificaciones in-app (modelo `Notificacion` con campo `mensaje`).

**Servicios (`app/services/`):**
- `deadline_notifier.py` — 4 triggers SLA (today/missed/approaching/overdue). Envía emails.
- `notificacion_responsable_service.py` — Notifica al responsable de columna cuando un ticket entra a su columna.
- `notificacion_admin_resultado_pruebas_service.py` — Notifica admins cuando cambia `resultado_pruebas`.
- `email_service.py` — Cadena Resend → SMTP → log+Dev Inbox.
- `auditoria_service.py` — Helper `registrar_auditoria()` con tolerancia a `IntegrityError`.
- `ticket_service.py` — Lógica de cambio de estado con orquestación de side-effects.

**API (`app/api/v1/`):**
- `tickets.py` — Endpoints principales (incluye `/mover-estado`, `/guardar`).
- `auth.py` — Login + JWT.
- `metricas.py` — Dashboard con modales HTMX (incluye Cuenta Resultado).
- `deps.py` — Dependencies de FastAPI (auth, db, role guards).

**Templates (`app/templates/`):**
- `dashboard/index.html` — Dashboard principal con Kanban y métricas. Contiene IIFE con scope aislado.
- `tickets/detalle_modal.py` — Modal de detalle de ticket (renderizado como string Python para HTMX).

**Tasks (`app/tasks/`):**
- `deadline_tasks.py` — Celery Beat: diario (8 AM, 4 triggers) + horario (top hour, approaching).
- `notification_tasks.py` — Tareas legacy (mantener por compatibilidad).

### 6.4 Tests de validación existentes

- `test_validacion_exhaustiva.py` — Suite completa (2-5 min).
- `test_validar_fix_admin_deadline.py` — Endpoint `/admin/deadline/ejecutar`.
- `test_validar_fix_url_email.py` — **NUEVO** (commit 57c220f). 5 escenarios:
  1. `deadline_notifier` produce URL absoluta.
  2. `notificacion_admin_resultado_pruebas` en 3 escenarios (sin override / con override / fallback dev).
  3. `notificacion_responsable` produce URL absoluta.
  4. Regresión estática: ningún archivo contiene patrones relativos prohibidos.
  5. `settings.PUBLIC_BASE_URL` existe y es absoluta.

Todos los tests pasan localmente (verificado en sesión anterior).

---

## 7. TAREA PENDIENTE #1 (ACCIÓN REQUERIDA DEL USUARIO)

El usuario debe configurar `PUBLIC_BASE_URL` en Railway:

1. Ir a https://railway.app/dashboard
2. Seleccionar el servicio `bitacora-grmv2-production`
3. Tab **Variables**
4. Agregar (o actualizar):
   ```
   PUBLIC_BASE_URL=https://bitacora-grmv2-production.up.railway.app
   ```
5. Railway redeploy automático (1-2 min)

**Sin esta variable**, los emails seguirán siendo absolutos pero apuntarán
a `http://localhost:8000/tickets#...` (correcto en sintaxis, incorrecto
en host). **Con esta variable**, los enlaces serán
`https://bitacora-grmv2-production.up.railway.app/tickets#ticket-N` y serán
clickeables desde cualquier cliente de correo.

---

## 8. PATRONES Y CONVENCIONES DEL PROYECTO

### 8.1 Naming

- Archivos: `snake_case.py` (incluso templates: `detalle_modal.py`).
- Funciones: `snake_case`. Métodos async con prefijo `async_` opcional.
- Clases: `PascalCase`. Modelos SQLAlchemy en singular (`Ticket`, `Estado`).
- Constantes: `UPPER_SNAKE_CASE`.
- Migraciones: `scripts/migrar_<descripcion_camel>.py`.

### 8.2 Auditoría obligatoria

Toda mutación de tabla crítica (ticket, usuario, estado) DEBE insertar en
`auditoria` con:
- `usuario_id`: actor (NULL si es evento del sistema).
- `accion`: código SCREAMING_SNAKE_CASE (`CAMBIO_ESTADO`, `EDITAR_RESULTADO_PRUEBAS`, etc.).
- `valor_anterior` y `valor_nuevo`: dict JSON con los campos cambiados.
- `comentario`: frase legible para humanos.
- `ticket_id`: si aplica.

### 8.3 Idempotencia de notificaciones

- SLA triggers: 1 notificación por ticket/trigger/día (verificado vía
  `auditoria` con `ticket_id + accion + DATE(created_at)`).
- Notificación de responsable: 1 por transición (no spam si el ticket
  oscila entre mismas columnas).

### 8.4 Email fallback chain

```
1. RESEND_API_KEY presente → POST https://api.resend.com/emails
2. SMTP_HOST presente       → smtplib SMTP/SMTP_SSL
3. Fallback final           → log en tmp/app.email.log + Dev Inbox
                             (consultable vía /dev/inbox)
```

Resultado de envío siempre devuelve `(sent: bool, transport: str, detail: str)`;
la app nunca falla por falta de SMTP.

### 8.5 PUBLIC_BASE_URL como única fuente de verdad

Patrón aplicado consistentemente (commits 57c220f, previos en
`credenciales_service.py` y `usuarios.py`):

```python
from app.core.config import settings

base = (base_url_param or settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
url = f"{base}/tickets#ticket-{ticket.id}"
```

**Regla:** Ningún servicio debe construir URL relativa para incluir en
emails. Si encontrás un caso, aplicá este patrón.

---

## 9. RECETA PARA RESOLVER UN BUG REPORT

Cuando el usuario reporta un bug, seguir este protocolo:

### Paso 1: Reproducir

- Si es bug UI: pedir screenshot o URL exacta.
- Si es bug de email: pedir el `.eml` o captura del cliente de correo.
- Si es bug de API: pedir `curl` exacto + response esperada vs real.

### Paso 2: Localizar

```bash
# Buscar el síntoma en el código (palabras clave del error):
grep -rn "<keyword del error>" app/

# Si es UI, revisar templates:
grep -rn "id=\"<modal-id>\"" app/templates/

# Si es JS, buscar onclick/handler:
grep -rn "onclick=" app/templates/ | grep -i "<síntoma>"
```

### Paso 3: Diagnosticar

Leer el archivo relevante (Read tool, siempre antes de Edit), identificar
la línea exacta y proponer causa raíz en lenguaje claro.

### Paso 4: Proponer fix

Mostrar el cambio en formato diff antes de aplicarlo:

```diff
- url_ticket = f"/tickets#{ticket.id}"
+ from app.core.config import settings
+ base = (settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
+ url_ticket = f"{base}/tickets#{ticket.id}"
```

### Paso 5: Validar

- Escribir test de regresión (`test_validar_fix_<bug>.py`).
- Correr test → debe pasar.
- Si el test falla, NO pushear. Iterar.

### Paso 6: Commit + push

```bash
git add <files específicos>
git commit -m "fix(<scope>): <descripción corta del bug>"
git push origin main
```

### Paso 7: Verificar producción

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  https://bitacora-grmv2-production.up.railway.app/health
```

Esperar 2-3 min (deploy) y reportar al usuario.

---

## 10. TROUBLESHOOTING COMÚN

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `IntegrityError: NOT NULL constraint failed: auditorias.usuario_id` | Falta aplicar migración `migrar_auditoria_usuario_id_nullable.py` | Correr script o `ALTER TABLE auditorias ALTER COLUMN usuario_id DROP NOT NULL;` |
| `TypeError: __init__() got an unexpected keyword argument 'cuerpo'` | BUG-3 reintroducido | Verificar `deadline_notifier.py:137` usa `mensaje=` no `cuerpo=` |
| Email con link `http:///tickets#ID` | `PUBLIC_BASE_URL` no configurado en Railway | Agregar env var + redeploy |
| Botón X de modal no cierra | Función en IIFE, no en `window` | Agregar `window.cerrarNombreFuncion = nombreFuncion;` al final del IIFE |
| Tests pasan local pero Railway falla | DB schema desincronizado | Correr migraciones pendientes contra la DB de Railway |
| `git push` no dispara deploy | Branch no es `main` o Railway no está vinculado al repo | Verificar `git branch --show-current` y config de Railway |
| Healthcheck `HTTP 200` pero UI rota | Cache del navegador del usuario | Pedir Ctrl+Shift+R o hard reload |

---

## 11. ENTREGABLES DEL MVP (HISTÓRICO — YA COMPLETADOS)

Estos son los entregables que el usuario solicitó al iniciar el proyecto.
Todos están implementados y en producción:

| Entregable | Ubicación | Estado |
|-----------|-----------|--------|
| Modelos SQLAlchemy | `app/models/*.py` | ✅ |
| Config Celery + Redis | `app/core/celery_app.py`, `app/core/config.py` | ✅ |
| Endpoints de transición de estado | `app/api/v1/tickets.py` (`POST /mover-estado`, `POST /guardar`) | ✅ |
| Tablero HTML + SortableJS + HTMX | `app/templates/dashboard/index.html` + `app/templates/kanban/` | ✅ |
| Auditoría obligatoria | `app/services/auditoria_service.py` + uso en `ticket_service.py` | ✅ |
| Recálculo SLA async | `app/tasks/deadline_tasks.py` (Celery Beat) | ✅ |
| Notificaciones in-app + email | `app/services/notificacion_*`, `app/services/email_service.py` | ✅ |

---

## 12. PRÓXIMOS PASOS SUGERIDOS (BACKLOG)

Cuando el usuario pida continuar, priorizá en este orden:

1. **Verificar PUBLIC_BASE_URL en Railway** (tarea #1, sección 7).
2. **Monitorear logs de Railway** durante 24h para detectar regresiones silenciosas.
3. **Tests E2E adicionales:**
   - Notificación de admin al cambiar `resultado_pruebas` (commit actual cubre fix de URL pero no el flujo completo).
   - Notificación de responsable al mover tarjeta (cubre flujos Kanban reales).
4. **Features del backlog original:**
   - Dashboard de métricas avanzado (drill-down por tipo, prioridad, edad).
   - Importador XML/Trello con validación de dependencias.
   - Vista Gantt de etapas con edición inline.
   - Modo offline para Kanban (service worker + IndexedDB).
5. **Mejoras técnicas:**
   - Reemplazar scripts `test_*.py` ad-hoc por pytest estructurado.
   - Documentar OpenAPI (FastAPI ya lo genera; agregar ejemplos).
   - Logging estructurado (JSON) para ingestión en Railway/Datadog.

---

## 13. CREDENCIALES Y TOKENS

⚠️ **POLÍTICA DE SEGURIDAD:**

- **NUNCA** commitear tokens al repo.
- **NUNCA** escribir tokens en archivos del workspace en texto plano.
- **SÍ** usar `get_all_secrets()` y `ask_for_secrets_from_user()` cuando
  la tarea los requiera.
- Los tokens de Railway se gestionan vía UI web o CLI local del usuario
  (`railway login` + `railway link`). El agente no debe almacenarlos.

**Tokens requeridos por componente:**

| Servicio | Token | Dónde se obtiene |
|----------|-------|------------------|
| Railway | API token + Project ID | `https://railway.app/account/tokens` + dashboard del proyecto |
| GitHub | Personal Access Token (PAT) con scope `repo` | `https://github.com/settings/tokens` |
| Resend | API key | `https://resend.com/api-keys` |
| SMTP | User/password del provider | Config del proveedor (Mailgun, SendGrid, etc.) |
| PostgreSQL (Railway) | Connection string | Auto-inyectada como `DATABASE_URL` |

---

## 14. CHECKLIST DE INICIO DE SESIÓN

Al comenzar una nueva sesión con este proyecto:

```bash
# 1. Verificar rama y estado
cd /workspace
git status
git log --oneline -3

# 2. Verificar salud de producción
curl -s -o /dev/null -w "Producción: HTTP %{http_code}\n" \
  https://bitacora-grmv2-production.up.railway.app/health

# 3. Verificar virtualenv
ls .venv-test/bin/python

# 4. Si el usuario reporta un bug nuevo, saltar a la sección 9 (receta).
# 5. Si el usuario pide una feature nueva, saltar a la sección 12 (backlog).
# 6. Si el usuario pide deploy, saltar a la sección 5.1 (Git workflow).
```

---

## 15. FRASE DE CIERRE (USAR AL TERMINAR UNA SESIÓN)

Al cerrar una sesión, el agente debe:

1. Resumir en 3-5 bullets qué se hizo.
2. Listar archivos modificados con `git diff --stat`.
3. Indicar el SHA del último commit (`git rev-parse --short HEAD`).
4. Mencionar cualquier acción manual requerida del usuario (ej: configurar env var en Railway).
5. Si hubo deploy, confirmar salud post-deploy con `curl /health`.

---

**FIN DEL PROMPT DE CONTINUACIÓN**

*Última actualización:* 2026-09-29
*Generado por:* MiniMax Agent al cierre de la sesión de fix de URL rota en emails.
*Próxima sesión:* Pegar este documento + instrucción del usuario.
