# 🚂 Despliegue en Railway - Bitácora GRM

> **Estado:** ✅ Todos los archivos de configuración listos, validados localmente con `gunicorn` y push a GitHub.
> **Último commit:** `729422b fix(railway): WhiteNoise ASGI compatibility`

---

## 📋 Resumen de lo implementado

| Archivo | Propósito | Estado |
|---|---|---|
| `Procfile` | Define 3 procesos: `web` (gunicorn), `worker` (celery), `beat` (celery beat) | ✅ |
| `railway.toml` | Configuración Railpack: healthcheck `/health`, restart policy, env vars | ✅ |
| `runtime.txt` | `python-3.12.5` para Railpack | ✅ |
| `gunicorn.conf.py` | Pool de 2 workers × 4 threads, preload, recycle, logs a stdout | ✅ |
| `wsgi.py` | Entry point ASGI re-exports `app` desde `app.main` | ✅ |
| `start.sh` | Detecta rol (`web`/`worker`/`beat`) por `$PROC_TYPE` > `$APP_ROLE` > `$RAILWAY_SERVICE_ROLE` > `$RAILWAY_SERVICE_NAME` | ✅ |
| `Dockerfile` | Build Python 3.12-slim, llama `start.sh` | ✅ |
| `requirements.txt` | + `gunicorn==23.0.0`, `whitenoise==6.7.0`, `alembic==1.13.3` | ✅ |
| `.env.example` | Documenta todas las variables de entorno (incl. Railway) | ✅ |
| `app/main.py` | `/health` robusto (DB+Redis), `/ready`, `/info`, WhiteNoise con fallback a StaticFiles | ✅ |

---

## 🔧 Paso a paso en Railway

### 1. Crear el proyecto en Railway

1. Ir a https://railway.app/new
2. **Deploy from GitHub repo** → seleccionar `moisesarancibiasanchez-cpu/Bitacora-GRM_v2`
3. Railway detectará automáticamente:
   - **Builder:** NIXPACKS (lee `runtime.txt`, `requirements.txt`, `railway.toml`)
   - **Start command:** `bash start.sh` (definido en `railway.toml`)

### 2. Crear los servicios de datos

En el mismo proyecto, agregar los plugins oficiales:

| Plugin | Costo | Notas |
|---|---|---|
| **PostgreSQL** | $5/mes después del trial | Clic "+ New" → Database → PostgreSQL |
| **Redis** | $5/mes después del trial | Clic "+ New" → Database → Redis |

Railway inyectará automáticamente estas variables en cualquier servicio del proyecto:
- `DATABASE_URL` (formato `postgresql://...`)
- `REDIS_URL` (formato `redis://...`)

### 3. Crear los 3 servicios del backend

Para cada servicio, ir a **"+ New" → GitHub Repo → mismo repo**.

> **Rol del proceso.** El rol NO se decide por el Start Command, sino por la
> variable `PROC_TYPE` del servicio. Motivo: mientras Railway lea el
> `railway.toml` del repo, su `startCommand = "bash start.sh"` tiene prioridad
> sobre el Start Command del panel, y `RAILWAY_SERVICE_ROLE` (la variable que
> el `start.sh` original usaba) **no la inyecta Railway** (la lista oficial de
> variables es exhaustiva y no la incluye). Con el código anterior, un
> servicio worker o beat caía en el rol `web` y arrancaba gunicorn: quedaba
> "activo" sin consumir ninguna tarea.

#### A) Servicio `web` (FastAPI) — ya existe
- **Start Command:** `bash start.sh` (lo impone `railway.toml`; el rol sale
  `web` por defecto porque no hay `PROC_TYPE`).
- **Variables de entorno** (pestaña "Variables"):
  ```
  APP_NAME=Bitácora GRM
  APP_VERSION=0.1.0
  DEBUG=false
  USE_SQLITE=false
  SECRET_KEY=<generar-con-secrets.token>
  CORS_ORIGINS=["https://bitacora-grmv2-production.up.railway.app"]
  PUBLIC_BASE_URL=https://bitacora-grmv2-production.up.railway.app
  ```
- **Networking:** dominio `bitacora-grmv2-production.up.railway.app`.
- **Healthcheck:** `/health` (viene de `railway.toml`).

#### B) Servicio `worker` (Celery worker) — crear
- **Start Command:** `bash start.sh`
- **Variable de servicio:** `PROC_TYPE=worker`
- **Variables de entorno:** las del servicio `web`, **más** las bases de datos.
  Lo más simple es usar *Shared Variables* del proyecto para `SECRET_KEY`,
  `DEBUG`, `USE_SQLITE` y `PUBLIC_BASE_URL`, y adjuntar los plugins:
  - `DATABASE_URL=${{Postgres.DATABASE_URL}}` (o el botón "Attach")
  - `REDIS_URL=${{Redis.REDIS_URL}}` (o el botón "Attach")
  - `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND` **no hacen falta**:
    `app/core/config.py` los deriva de `REDIS_URL` (bases 1 y 2) cuando no
    están definidos. Si se definen, mandan sobre el valor derivado.
- **No necesita dominio público** (es interno). Si se le deja
  "Healthcheck Path" vacío, no hay healthcheck que pueda fallar (un worker no
  tiene servidor HTTP).
- Beat debe ser **un solo servicio**: dos instancias dispararían cada tarea
  programada dos veces.

#### C) Servicio `beat` (Celery scheduler) — crear
- **Start Command:** `bash start.sh`
- **Variable de servicio:** `PROC_TYPE=beat`
- **Variables de entorno:** exactamente las del servicio `worker`.
- **No usar "Cron Schedule" de Railway** para este servicio: el Cron Job de
  Railway exige que el proceso termine (si no, se saltan las ejecuciones
  siguientes) y `celery beat` es un planificador permanente. El calendario lo
  lleva celery (`app/core/celery_app.py`).
- El fichero de calendario de celery beat se escribe en
  `/tmp/celerybeat-schedule` (ruta escribible); se puede cambiar con
  `CELERY_BEAT_SCHEDULE_FILE`.

### 3.1 Reiniciar el worker o el beat (sin recrearlos)

1. Proyecto → entorno `production` → clic en el servicio `worker` (o `beat`).
2. Pestaña **Deployments** → deployment **ACTIVE** → menú de tres puntos
   (`⋮`) → **Restart**. Railway redeploya la última imagen sin tocar la
   configuración.
   - Equivalente por CLI: `railway redeploy --service worker --environment production`.
3. En **Variables**, tras cambiar algo, los cambios quedan en *staged changes*:
   hay que pulsarlos (Deploy) para que se apliquen. Un "Restart" sin Deploy
   de los cambios previos no aplica las variables nuevas.

Comprobación: en los logs del servicio debe aparecer
`[start.sh] Iniciando Bitácora GRM (rol=worker)` (o `rol=beat`). Si aparece
`rol=web`, el `PROC_TYPE` no está llegando al contenedor.

### 3.2 Si el servicio worker/beat aparece "Failed"

| Síntoma | Causa | Solución |
|---|---|---|
| Deployment fallido con error de healthcheck | El servicio heredó `healthcheckPath = "/health"` de `railway.toml`, pero no hay servidor HTTP | Service → Settings → Healthcheck Path → vaciar |
| Logs con `Rol desconocido` o proceso `gunicorn` | Falta `PROC_TYPE` o tiene un valor inválido | Variables → `PROC_TYPE=worker` (o `beat`) → Deploy |
| `ConnectionError` contra `redis://localhost:6379` | Falta `REDIS_URL` en ese servicio | Adjuntar Redis (o `REDIS_URL=${{Redis.REDIS_URL}}`) → Deploy |
| El worker arranca pero no consume tareas | No hay `celery beat` (nadie encola las tareas periódicas) | Crear/arrancar el servicio `beat` |
| `celery beat` se reinicia solo | Dos instancias de beat sobre el mismo calendario | Dejar un único servicio `beat` |

### 4. Inicializar la base de datos

La primera vez, la BD estará vacía. Para sembrar los datos demo, ejecutar desde el shell del servicio `web`:

```bash
railway run --service web python -m app.db.init_db
```

O, si `AUTO_INIT_DB=true` está en variables, basta con redeploy.

### 5. Verificar

Abrir `https://tu-proyecto.up.railway.app/health` y comprobar:

```json
{
  "status": "ok",
  "app": "Bitácora GRM",
  "version": "0.1.0",
  "database": "ok",
  "redis": "ok"
}
```

Si todo es `ok`, ir a `/kanban` para ver el tablero.

Verificar además el worker y el beat (en los logs de cada servicio):

```
[start.sh] Iniciando Bitácora GRM (rol=worker)
[INFO] celery@<host> ready
```

```
[start.sh] Iniciando Bitácora GRM (rol=beat)
[INFO] celery beat v5.x starting
```

Si el rol resuelto no es el esperado, revisar la variable `PROC_TYPE` de ese
servicio. La matriz de resolución está verificada en
`tools/verificacion/verificar_rol_celery.py` (16/16 comprobaciones).

---

## 🔍 Variables de entorno detalladas

| Variable | Default | Descripción |
|---|---|---|
| `APP_NAME` | `Bitácora GRM` | Nombre mostrado en /docs |
| `APP_VERSION` | `0.1.0` | Versión |
| `DEBUG` | `true` | `false` en producción (desactiva hot-reload, activa WhiteNoise si está) |
| `USE_SQLITE` | `false` | `true` solo para demo sin BD externa |
| `SECRET_KEY` | (placeholder) | **OBLIGATORIO** cambiar en producción. Generar con `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | (Railway auto) | Inyectada por Railway al adjuntar PostgreSQL |
| `REDIS_URL` | (Railway auto) | Inyectada por Railway al adjuntar Redis |
| `CELERY_BROKER_URL` | derivado de `REDIS_URL` (db 1) | DB Redis para cola de tareas. Si **no** se define, `app/core/config.py` lo deriva de `REDIS_URL` (base 1) |
| `CELERY_RESULT_BACKEND` | derivado de `REDIS_URL` (db 2) | DB Redis para resultados. Si **no** se define, se deriva de `REDIS_URL` (base 2) |
| `PROC_TYPE` | (vacío) | Rol del proceso para `start.sh`: `web` \| `worker` \| `beat`. **Obligatorio** en los servicios worker y beat |
| `AUTO_INIT_DB` | `false` | Si `true`, ejecuta `init_db` al arranque (solo desarrollo) |
| `PORT` | (Railway auto) | Inyectada por Railway |
| `WEB_CONCURRENCY` | `2` | Workers de gunicorn |
| `WEB_THREADS` | `4` | Hilos por worker |
| `CORS_ORIGINS` | `["*"]` | Lista JSON de orígenes permitidos |

---

## 🧪 Validación local antes de subir a Railway

Se ejecutó `gunicorn` con todos los checks:

```bash
$ USE_SQLITE=true DEBUG=false PORT=18765 python -m gunicorn -c gunicorn.conf.py app.main:app
[INFO] Starting gunicorn 23.0.0
[INFO] Using worker: uvicorn.workers.UvicornWorker
[INFO] Booting worker with pid: 407
[INFO] Booting worker with pid: 408
[INFO] WhiteNoise instalado pero a2wsgi no disponible; sirviendo /static con StaticFiles de FastAPI
[INFO] Application startup complete.
```

| Endpoint | Resultado |
|---|---|
| `GET /health` | 200 — `{"status":"ok","database":"ok",...}` |
| `GET /ready` | 200 — `{"status":"ready",...}` |
| `GET /info` | 200 — `{"app":"Bitácora GRM","version":"0.1.0",...}` |
| `GET /` | 307 redirect a `/kanban` |
| `GET /kanban` | 200 — 20 879 bytes (HTML) |
| `GET /tickets` | 200 — 11 917 bytes (HTML) |
| `GET /catalogos` | 200 — 6 803 bytes (HTML) |
| `GET /static/css/styles.css` | 200 — 1 862 bytes |
| `GET /static/js/kanban.js` | 200 — 4 774 bytes |
| `GET /docs` | 200 — Swagger UI |
| `GET /api/v1/tickets` (X-User-Id: 1) | 200 — 8 tickets JSON |
| `GET /api/v1/estados` (X-User-Id: 1) | 200 — 6 estados JSON |
| `GET /api/v1/etiquetas` (X-User-Id: 1) | 200 — 16 etiquetas JSON |
| `PATCH /api/v1/tickets/1/estado` | 200 — fragmento HTML Kanban (HTMX) |

---

## 🛠 Solución de problemas

### "No start command detected" (Railpack)
- **Causa:** Falta `Procfile` o `railway.toml`.
- **Solución:** Ambos están en el repo. Si persiste, en el servicio ir a Settings → Deploy → Start Command y dejar `bash start.sh`.

### "Application failed to start" / exit code 1
- **Causa habitual:** Falta `DATABASE_URL` o `REDIS_URL`.
- **Solución:** Verificar que los plugins PostgreSQL y Redis están en el mismo proyecto. Las variables se inyectan de forma automática.

### Healthcheck falla (502/503)
- **Causa:** La BD o Redis no responden.
- **Solución:** Revisar logs del servicio (`railway logs --service web`). El endpoint `/health` distingue:
  - `database: error` → BD no accesible (revisar `DATABASE_URL`)
  - `redis: unavailable` → Redis no es crítico, pero si necesitas Celery requieres el plugin Redis.

### WhiteNoise no aparece en logs
- **Esperado:** WhiteNoise 6.x es WSGI-only. Se usa `StaticFiles` (nativo ASGI) en su reemplazo. Si más adelante requieres compresión brotli, instala `a2wsgi` y la integración se activará de forma automática.

### /api/v1/* devuelve `401 No autenticado`
- **Causa:** Las rutas API requieren header `X-User-Id: <id>` o `Authorization: Bearer <jwt>`.
- **Solución:** En pruebas, agregar `-H "X-User-Id: 1"`. En el frontend, ya está manejado por la capa de auth.

---

## 🔐 Notas de seguridad para producción

- [ ] Cambiar `SECRET_KEY` por uno aleatorio de 32+ caracteres
- [ ] Cambiar `CORS_ORIGINS` de `["*"]` al dominio real
- [ ] Cambiar las contraseñas de usuarios seed en el primer login
- [ ] Activar HTTPS (Railway lo hace por defecto)
- [ ] Configurar backups automáticos de PostgreSQL (Railway → plugin → Backups)

---

## 📦 Commit actual (en GitHub)

```
729422b fix(railway): WhiteNoise ASGI compatibility
32db5c1 Message 439726272630929 - 1788909530
d207f7a Message 439709695926615 - 1788906170
a491fff Message 439716025114763 - 1788906066
3d656db feat(trello): implementa Checklists, Etiquetas, Comentarios, Adjuntos, Búsqueda y motor Butler
```

Push a `https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2.git` confirmado.
