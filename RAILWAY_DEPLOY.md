# Despliegue en Railway - Bitácora GRM

> **Estado:** despliegue de producción con servicios `web`, `worker` y `beat`.
> **Fuentes de verdad:** `railway.toml:31-49`, `start.sh:221-269`, `start.sh:324-343` y `app/core/config.py`.
> **Nota:** no existe `Dockerfile` en el repositorio; el build operativo usa NIXPACKS.

---

## 1. Alcance

El proyecto se despliega como tres servicios del mismo repositorio:

- `web`: FastAPI detrás de Gunicorn.
- `worker`: Celery worker.
- `beat`: Celery beat, con una sola instancia en el proyecto.

`start.sh` es el punto de entrada común. El rol se obtiene de `PROC_TYPE`, `APP_ROLE`, `RAILWAY_SERVICE_ROLE` o `RAILWAY_SERVICE_NAME`, en ese orden (`start.sh:221-269`). Para los servicios nuevos se debe definir `PROC_TYPE=worker` o `PROC_TYPE=beat`.

Los archivos de despliegue presentes son:

| Archivo | Función |
|---|---|
| `railway.toml` | Builder, comando de arranque, healthcheck, política de reinicio y variables por defecto |
| `start.sh` | Provisión de `SECRET_KEY`, detección del rol y lanzamiento del proceso |
| `Procfile` | Procesos web, worker y beat |
| `runtime.txt` | Versión de Python para el build |
| `gunicorn.conf.py` | Configuración de Gunicorn |
| `wsgi.py` | Reexportación de la aplicación ASGI |
| `requirements.txt` | Dependencias de Python |
| `.env.example` | Inventario de variables de entorno |

## 2. Preparar el proyecto y los datos

1. Crear el proyecto desde el repositorio GitHub en [railway.app/new](https://railway.app/new).
2. Añadir PostgreSQL y Redis como plugins del proyecto.
3. Adjuntar PostgreSQL y Redis al servicio `web` y a los servicios `worker` y `beat`.
4. Usar las referencias de variables que aparecen en la guía de `RAILWAY_DEPLOY.md` para `DATABASE_URL` y `REDIS_URL`.
5. No publicar credenciales en el repositorio, en la documentación ni en los logs.

El build que debe replicar el panel es:

| Ajuste | Valor |
|---|---|
| Builder | `NIXPACKS` |
| Build Command | `pip install --upgrade pip && pip install -r requirements.txt` |

## 3. Variables del panel

Definir las siguientes variables en el panel de Railway. Las comunes a los tres servicios pueden configurarse como Shared Variables.

| Variable | Valor de producción | Aplicación |
|---|---|---|
| `SECRET_KEY` | Valor real y fuerte, guardado solo en el panel | `web`, `worker`, `beat` |
| `PUBLIC_BASE_URL` | `https://bitacora-grmv2-production.up.railway.app` | `web`, `worker`, `beat` |
| `CORS_ORIGINS` | `["https://bitacora-grmv2-production.up.railway.app"]` | `web`, `worker`, `beat` |
| `DATABASE_URL` | Referencia real al plugin PostgreSQL | `web`, `worker`, `beat` |
| `REDIS_URL` | Referencia real al plugin Redis | `web`, `worker`, `beat` |
| `CELERY_BROKER_URL` | Valor real de Redis para la cola, base 1 | `worker`, `beat` |
| `CELERY_RESULT_BACKEND` | Valor real de Redis para resultados, base 2 | `worker`, `beat` |
| `DEBUG` | `false` | `web`, `worker`, `beat` |
| `USE_SQLITE` | `false` | `web`, `worker`, `beat` |
| `AUTO_INIT_DB` | `false` | `web`, `worker`, `beat` |
| `PYTHONUNBUFFERED` | `1` | `web`, `worker`, `beat` |
| `PYTHONDONTWRITEBYTECODE` | `1` | `web`, `worker`, `beat` |
| `APP_VERSION` | `0.1.0` | `web`, `worker`, `beat` |
| `PROC_TYPE` | `worker` o `beat`, según el servicio | Solo `worker` y `beat` |
| `CELERY_BEAT_SCHEDULE_FILE` | `/tmp/celerybeat-schedule` o otra ruta escribible | Solo `beat` |

`SECRET_KEY` puede generarse con `openssl rand -hex 32`; el resultado no debe copiarse a esta documentación. `AUTO_INIT_DB=false` coincide con el valor por defecto de `app/core/config.py:126` y evita el seed de `app/main.py:68-78`. `CORS_ORIGINS` debe ser explícito en producción; no se debe usar el comodín.

Si `CELERY_BROKER_URL` o `CELERY_RESULT_BACKEND` no se definen, `app/core/config.py:143-144` y `app/core/config.py:263-287` los derivan de `REDIS_URL` en las bases 1 y 2, respectivamente.

## 4. Configurar los servicios

### 4.1 Servicio `web`

| Ajuste del panel | Valor |
|---|---|
| Start Command | `bash start.sh` |
| Healthcheck Path | `/health` |
| Healthcheck Timeout | `60` |
| Restart Policy | `ON_FAILURE` |
| Maximum Retries | `5` |
| Dominio | `bitacora-grmv2-production.up.railway.app` |

El servicio web no necesita `PROC_TYPE`: si no se define ninguno, `start.sh` asume el rol `web` (`start.sh:263-269`). Debe usar `SECRET_KEY` real y se recomienda montar un volumen persistente en `/data` para estabilizar la clave entre reinicios (`start.sh:22-31`).

### 4.2 Servicio `worker`

| Ajuste del panel | Valor |
|---|---|
| Start Command | `bash start.sh` |
| Healthcheck Path | Vacío |
| Variable de servicio | `PROC_TYPE=worker` |
| Dominio público | No necesario |

El worker no sirve HTTP. Por eso su Healthcheck Path debe quedar vacío. El comando debe ser `bash start.sh`, no una invocación directa de Celery, para mantener la espera de PostgreSQL, la resolución del rol y la provisión de la clave (`start.sh:271-323`, `start.sh:324-343`).

### 4.3 Servicio `beat`

| Ajuste del panel | Valor |
|---|---|
| Start Command | `bash start.sh` |
| Healthcheck Path | Vacío |
| Variable de servicio | `PROC_TYPE=beat` |
| `CELERY_BEAT_SCHEDULE_FILE` | Ruta escribible, por defecto `/tmp/celerybeat-schedule` |
| Dominio público | No necesario |

Debe existir una sola instancia de `beat`; dos instancias dispararían cada tarea dos veces. No usar Cron Schedule de Railway para este servicio: Celery beat es un proceso permanente (`start.sh:218-219`, `start.sh:335-342`).

## 5. Config as Code: fin de soporte 2026-12-01

Railway dejará de leer `railway.toml` el 2026-12-01. Antes de esa fecha hay que replicar en el panel todos los ajustes que hoy viven en el archivo, mediante Shared Variables y Deploy settings.

| Ámbito | Ajuste que replicar | Valor en el panel | Fuente actual |
|---|---|---|---|
| Build | Builder | `NIXPACKS` | `railway.toml:31-32` |
| Build | Build Command | `pip install --upgrade pip && pip install -r requirements.txt` | `railway.toml:33` |
| Deploy: web | Start Command | `bash start.sh` | `railway.toml:35-36` |
| Deploy: web | Healthcheck Path | `/health` | `railway.toml:37` |
| Deploy: web | Healthcheck Timeout | `60` | `railway.toml:38` |
| Deploy: web | Restart Policy | `ON_FAILURE` | `railway.toml:39` |
| Deploy: web | Maximum Retries | `5` | `railway.toml:40` |
| Deploy: worker | Start Command | `bash start.sh` | `railway.toml:51-55` |
| Deploy: worker | Healthcheck Path | Vacío | `railway.toml:25-29` |
| Deploy: worker | Rol del proceso | `PROC_TYPE=worker` | `railway.toml:53-55` |
| Deploy: beat | Start Command | `bash start.sh` | `railway.toml:56-58` |
| Deploy: beat | Healthcheck Path | Vacío | `railway.toml:25-29` |
| Deploy: beat | Rol del proceso | `PROC_TYPE=beat` | `railway.toml:56-58` |
| Deploy: beat | Calendario | `CELERY_BEAT_SCHEDULE_FILE` en ruta escribible | `start.sh:335-342` |
| Variables | `DEBUG` | `false` | `railway.toml:44-49` |
| Variables | `USE_SQLITE` | `false` | `railway.toml:44-49` |
| Variables | `PYTHONUNBUFFERED` | `1` | `railway.toml:44-49` |
| Variables | `PYTHONDONTWRITEBYTECODE` | `1` | `railway.toml:44-49` |
| Variables | `APP_VERSION` | `0.1.0` | `railway.toml:44-49` |
| Shared Variable | `SECRET_KEY` | Valor real, no un placeholder y no documentado | `start.sh:22-32`, `start.sh:126-199` |
| Shared Variable | `PUBLIC_BASE_URL` | `https://bitacora-grmv2-production.up.railway.app` | `RAILWAY_DEPLOY.md`, sección 3 |
| Shared Variable | `CORS_ORIGINS` | `["https://bitacora-grmv2-production.up.railway.app"]` | `RAILWAY_DEPLOY.md`, sección 3 |
| Shared Variable | `DATABASE_URL` | Referencia real al plugin PostgreSQL | `RAILWAY_DEPLOY.md`, sección 3 |
| Shared Variable | `REDIS_URL` | Referencia real al plugin Redis | `RAILWAY_DEPLOY.md`, sección 3 |
| Shared Variable | `CELERY_BROKER_URL` | Valor real de Redis para la cola, base 1 | `app/core/config.py:143-144` |
| Shared Variable | `CELERY_RESULT_BACKEND` | Valor real de Redis para resultados, base 2 | `app/core/config.py:143-144` |

### Impacto si la migración no se realiza a tiempo

`start.sh` es quien genera o recupera `SECRET_KEY` antes de lanzar el proceso (`start.sh:22-32`, `start.sh:126-199`). Si el web deja de arrancar mediante `bash start.sh` y no existe una `SECRET_KEY` válida en el panel:

- Con `DEBUG=false`, el guard de `app/main.py:52-59` aborta el arranque: fallo cerrado, sin exponer la aplicación.
- Con `DEBUG=true`, la aplicación puede arrancar de forma degradada. La cookie de sesión se emite sin el atributo `Secure` porque `secure=not settings.DEBUG` (`app/api/v1/auth.py:65-70`), SQLAlchemy registra SQL porque `echo=settings.DEBUG` (`app/db/session.py:10-17`) y `app/main.py:68-78` ejecuta el seed en cada arranque.

La configuración del panel debe quedar replicada y verificada antes del 2026-12-01, no el mismo día del corte.

## 6. Inicializar y verificar la base de datos

La aplicación aplica migraciones idempotentes al arrancar (`app/main.py:61-66`). Para una instalación nueva se puede ejecutar explícitamente:

```bash
railway run --service web python -m app.db.init_db
```

No se debe activar `AUTO_INIT_DB=true` como procedimiento recurrente de producción. El primer registro define la cuenta administradora; las credenciales se distribuyen por un canal privado.

### 6.1 Comprobaciones HTTP

```bash
curl -i https://bitacora-grmv2-production.up.railway.app/health
```

Resultado esperado: HTTP 200 y un JSON con `status` `ok`, `database` `ok` y `redis` `ok`.

```bash
curl -i https://bitacora-grmv2-production.up.railway.app/ready
curl -i https://bitacora-grmv2-production.up.railway.app/info
curl -i https://bitacora-grmv2-production.up.railway.app/docs
```

Resultado esperado: HTTP 200 en los tres endpoints.

```bash
curl -i https://bitacora-grmv2-production.up.railway.app/
```

Resultado esperado sin sesión: HTTP 307 con `Location: /auth/login`. Con una sesión válida, la misma ruta redirige a `/kanban` (`app/main.py:276-282`).

### 6.2 Comprobación de los roles

```bash
railway logs --service worker
railway logs --service beat
```

En `worker`, los logs deben mostrar `[start.sh] Iniciando Bitácora GRM (rol=worker)` y `celery ready`. En `beat`, deben mostrar `[start.sh] Iniciando Bitácora GRM (rol=beat)` y el arranque de Celery beat. Si el rol resuelto es `web`, falta `PROC_TYPE` o su valor no llegó al servicio.

La comprobación local del diagnóstico de serialización de tickets es reproducible con:

```bash
python tools/verificacion/diagnostico_tickets.py
```

El script usa SQLite en memoria y no toca la base de datos de producción (`tools/verificacion/diagnostico_tickets.py:30-33`).

## 7. Autenticación y seguridad

- Las rutas API requieren un JWT Bearer o la cookie `access_token` (`app/api/v1/deps.py:4-6`, `app/api/v1/deps.py:45-62`).
- El antiguo bypass por cabecera `X-User-Id` está cerrado por defecto mediante `ALLOW_XUSER_HEADER`; no debe habilitarse en producción (`app/api/v1/deps.py:8-12`, `app/api/v1/deps.py:26-28`).
- `CORS_ORIGINS` debe contener el origen explícito de producción, nunca `[*]`.
- `SECRET_KEY` debe ser un valor real y fuerte; no se registra en los logs.
- El volumen montado en `/data` conserva la clave entre reinicios del web.
- No activar `SEED_DEMO_USERS=true` ni `AUTO_INIT_DB=true` en producción.

## 8. Solución de problemas

| Síntoma | Causa | Comprobación y solución |
|---|---|---|
| El web no arranca | Falta `SECRET_KEY` o la configuración es insegura | Revisar Variables y el error del guard de `app/main.py:52-59` |
| El deployment falla en el healthcheck | El servicio heredó `/health` pero no sirve HTTP | En `worker` o `beat`, vaciar Healthcheck Path |
| Los logs muestran `rol=web` | Falta `PROC_TYPE` | Definir `PROC_TYPE=worker` o `PROC_TYPE=beat` y desplegar |
| Error de conexión a Redis | Falta `REDIS_URL` o las variables de Celery | Adjuntar Redis y revisar `REDIS_URL`, `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND` |
| Celery beat no conserva el calendario | La ruta no es escribible | Definir `CELERY_BEAT_SCHEDULE_FILE` en una ruta escribible |
| `/api/v1/*` devuelve 401 | No hay cookie ni Bearer válido | Iniciar sesión o usar un JWT Bearer; el bypass por cabecera está cerrado |
| `/health` devuelve 503 | La base de datos no responde | Revisar logs, `DATABASE_URL` y el estado del plugin PostgreSQL |
| El build no instala dependencias | `requirements.txt` no se instaló | Revisar el Build Command y desplegar de nuevo |
