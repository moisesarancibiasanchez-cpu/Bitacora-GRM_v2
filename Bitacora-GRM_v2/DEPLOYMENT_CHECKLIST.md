# ✅ Checklist de Despliegue - Bitácora GRM

> **Objetivo:** Guiar paso a paso el despliegue en Railway con todas las validaciones.

## 📦 Pre-requisitos

- [x] **Cuenta GitHub** con acceso a `moisesarancibiasanchez-cpu/Bitacora-GRM_v2`
- [x] **Cuenta Railway** (https://railway.app)
- [x] **Token de GitHub** con scope `repo` (ya configurado)
- [x] **Python 3.12.5** (indicado en `runtime.txt`)

## 📁 Archivos listos en el repo

| Archivo | Tamaño | Propósito |
|---|---|---|
| `Procfile` | 211 B | Procesos web/worker/beat |
| `railway.toml` | 1.1 KB | Healthcheck + restart policy |
| `runtime.txt` | 14 B | `python-3.12.5` |
| `gunicorn.conf.py` | 1.2 KB | WSGI config |
| `wsgi.py` | 197 B | Entry point |
| `start.sh` | 2.1 KB | Detect rol + launch |
| `Dockerfile` | 921 B | (alternativa Docker) |
| `requirements.txt` | 924 B | + gunicorn, whitenoise, alembic |
| `.env.example` | 1.2 KB | Variables documentadas |
| `RAILWAY_DEPLOY.md` | 6 KB | Guía detallada |
| `app/main.py` | 9.3 KB | /health, /ready, /info |

## 🚂 Despliegue en Railway

### Paso 1: Crear proyecto
- [ ] Ir a https://railway.app/new
- [ ] Click "Deploy from GitHub repo"
- [ ] Seleccionar `moisesarancibiasanchez-cpu/Bitacora-GRM_v2`
- [ ] Click "Deploy"

### Paso 2: Crear PostgreSQL
- [ ] "+ New" → "Database" → "PostgreSQL"
- [ ] Esperar a que el plugin esté "Active"
- [ ] Copiar el `DATABASE_URL` que Railway inyecta (opcional, no se ve en el panel del plugin)

### Paso 3: Crear Redis
- [ ] "+ New" → "Database" → "Redis"
- [ ] Esperar a que el plugin esté "Active"
- [ ] Railway inyectará `REDIS_URL` automáticamente

### Paso 4: Renombrar el primer servicio a `web`
- [ ] Click en el servicio auto-creado (que apunta a GitHub)
- [ ] Settings → Service Name → `web`
- [ ] Variables → agregar:
  - `APP_NAME=Bitácora GRM`
  - `APP_VERSION=0.1.0`
  - `DEBUG=false`
  - `USE_SQLITE=false`
  - `SECRET_KEY=<pegar-token-aleatorio>`
  - `CORS_ORIGINS=["*"]`
  - `AUTO_INIT_DB=true` (solo la primera vez, luego quitar)
- [ ] Settings → Deploy → Start Command:
  ```
  gunicorn -c gunicorn.conf.py app.main:app
  ```
- [ ] Settings → Networking → "Generate Domain" → guardar URL
- [ ] Verificar healthcheck:
  ```
  https://<tu-dominio>.up.railway.app/health
  ```
  → debe devolver `{"status":"ok","database":"ok",...}`

### Paso 5: Crear servicio `worker` (Celery)
- [ ] "+ New" → "GitHub Repo" → mismo repo
- [ ] Service Name → `worker`
- [ ] Variables → mismas que `web` (sin `CORS_ORIGINS` ni `AUTO_INIT_DB`)
- [ ] Start Command:
  ```
  celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=2
  ```

### Paso 6: Crear servicio `beat` (Celery Beat)
- [ ] "+ New" → "GitHub Repo" → mismo repo
- [ ] Service Name → `beat`
- [ ] Variables → mismas que `worker`
- [ ] Start Command:
  ```
  celery -A app.core.celery_app:celery_app beat --loglevel=info
  ```

### Paso 7: Validar
- [ ] `GET https://<dominio>/health` → 200
- [ ] `GET https://<dominio>/ready` → 200
- [ ] `GET https://<dominio>/info` → 200
- [ ] `GET https://<dominio>/kanban` → 200 (HTML)
- [ ] `GET https://<dominio>/docs` → 200 (Swagger)
- [ ] Login en `/kanban` con `admin@bitacora.local` / `admin123`
- [ ] Arrastrar una tarjeta entre columnas (SortableJS + HTMX)
- [ ] Verificar logs de `worker` muestran tareas ejecutándose cada 5 min (SLA)

### Paso 8: Endurecimiento (post-despliegue)
- [ ] Cambiar `SECRET_KEY`
- [ ] Cambiar `CORS_ORIGINS` al dominio real
- [ ] Cambiar contraseñas de los usuarios seed
- [ ] Revisar logs de `worker` y `beat`
- [ ] Configurar copias de respaldo de PostgreSQL

---

## 🧪 Validación local (ya ejecutada ✅)

```bash
$ pip install -r requirements.txt
$ USE_SQLITE=true python -m app.db.init_db
$ USE_SQLITE=true DEBUG=false PORT=18765 python -m gunicorn -c gunicorn.conf.py app.main:app
```

| Test | HTTP | Resultado |
|---|---|---|
| `GET /health` | 200 | `database:ok, redis:unavailable` ✓ |
| `GET /ready` | 200 | `status:ready` ✓ |
| `GET /info` | 200 | JSON con env vars ✓ |
| `GET /` | 307 | → `/kanban` ✓ |
| `GET /kanban` | 200 | HTML 20 879 B ✓ |
| `GET /static/css/styles.css` | 200 | 1 862 B ✓ |
| `GET /docs` | 200 | Swagger UI ✓ |
| `GET /api/v1/tickets` (X-User-Id: 1) | 200 | 8 tickets ✓ |
| `GET /api/v1/estados` (X-User-Id: 1) | 200 | 6 estados ✓ |
| `PATCH /api/v1/tickets/1/estado` | 200 | HTML parcial HTMX ✓ |

---

## 🐛 Solución de problemas rápida

| Síntoma | Causa | Solución |
|---|---|---|
| `No start command detected` | Falta Procfile/railway.toml | Verificar que están en la raíz del repo |
| `psycopg2.OperationalError` | `DATABASE_URL` no configurado | Adjuntar plugin PostgreSQL al proyecto |
| `redis.exceptions.ConnectionError` | `REDIS_URL` no configurado | Adjuntar plugin Redis |
| `401 No autenticado` | Falta header | Agregar `-H "X-User-Id: 1"` |
| `/health` retorna 503 | BD caída | Revisar logs, reiniciar servicio |
| `ModuleNotFoundError: whitenoise` | requirements.txt no se instaló | Revisar logs del build, redeploy |

---

## 📞 Soporte

- **Logs Railway:** `railway logs --service <nombre>`
- **Shell Railway:** `railway run --service web bash`
- **Repo:** https://github.com/moisesarancibiasanchez-cpu/Bitacora-GRM_v2
