# Checklist de despliegue en Railway - Bitácora GRM

> **Objetivo:** verificar paso a paso el despliegue de `web`, `worker` y `beat`.
> **Fuentes de verdad:** `railway.toml:31-49`, `start.sh:221-269`, `start.sh:324-343` y `app/core/config.py`.
> **Resultado esperado:** los tres servicios desplegados, con los roles correctos y los endpoints de salud configurados según su función.

## 1. Preflight del repositorio

- [ ] Confirmar que el repositorio contiene `railway.toml`, `start.sh`, `Procfile`, `runtime.txt`, `gunicorn.conf.py`, `wsgi.py`, `requirements.txt` y `.env.example`.
- [ ] Confirmar que no se usa un `Dockerfile`: no existe en el repositorio y el build operativo es NIXPACKS.
- [ ] Confirmar que las variables sensibles se configuran en el panel y no se versionan.
- [ ] Confirmar que existe acceso al repositorio y a la cuenta de Railway con permisos mínimos.
- [ ] Confirmar que se dispone de credenciales de prueba distribuidas por canal privado; no hay credenciales de demostración publicadas en este documento.

Verificación opcional desde la raíz del repositorio:

```bash
test -f railway.toml && test -f start.sh && test -f Procfile && test -f requirements.txt && echo "preflight correcto"
```

Resultado esperado: `preflight correcto`.

## 2. Crear el proyecto y los datos

- [ ] Crear el proyecto desde el repositorio GitHub en [railway.app/new](https://railway.app/new).
- [ ] Añadir el plugin PostgreSQL y esperar a que esté activo.
- [ ] Añadir el plugin Redis y esperar a que esté activo.
- [ ] Adjuntar PostgreSQL y Redis al servicio `web`.
- [ ] Adjuntar PostgreSQL y Redis a los servicios `worker` y `beat`.
- [ ] Confirmar que Railway expone `DATABASE_URL` y `REDIS_URL` en cada servicio.

## 3. Configurar el build y las variables compartidas

### 3.1 Build settings

- [ ] Builder: `NIXPACKS`.
- [ ] Build Command: `pip install --upgrade pip && pip install -r requirements.txt`.

Fuentes: `railway.toml:31-33`.

### 3.2 Shared Variables y variables comunes

- [ ] `SECRET_KEY`: valor real y fuerte; no un placeholder y no un valor publicado.
- [ ] `PUBLIC_BASE_URL=https://bitacora-grmv2-production.up.railway.app`.
- [ ] `CORS_ORIGINS=["https://bitacora-grmv2-production.up.railway.app"]`.
- [ ] `DATABASE_URL`: referencia real al plugin PostgreSQL.
- [ ] `REDIS_URL`: referencia real al plugin Redis.
- [ ] `CELERY_BROKER_URL`: valor real de Redis para la cola, base 1.
- [ ] `CELERY_RESULT_BACKEND`: valor real de Redis para resultados, base 2.
- [ ] `DEBUG=false`.
- [ ] `USE_SQLITE=false`.
- [ ] `AUTO_INIT_DB=false`.
- [ ] `PYTHONUNBUFFERED=1`.
- [ ] `PYTHONDONTWRITEBYTECODE=1`.
- [ ] `APP_VERSION=0.1.0`.

`SECRET_KEY` puede generarse localmente con `openssl rand -hex 32`; el resultado no debe guardarse en el repositorio. `AUTO_INIT_DB=false` coincide con `app/core/config.py:126` y evita el seed de `app/main.py:68-78`. `CORS_ORIGINS` no debe usar `[*]` en producción. Si `CELERY_BROKER_URL` o `CELERY_RESULT_BACKEND` no se definen, `app/core/config.py:263-287` los deriva de `REDIS_URL` en las bases 1 y 2.

## 4. Configurar el servicio `web`

- [ ] Start Command: `bash start.sh`.
- [ ] Healthcheck Path: `/health`.
- [ ] Healthcheck Timeout: `60`.
- [ ] Restart Policy: `ON_FAILURE`.
- [ ] Maximum Retries: `5`.
- [ ] Generar o conservar el dominio `bitacora-grmv2-production.up.railway.app`.
- [ ] Definir `SECRET_KEY` real y montar un volumen persistente en `/data`.
- [ ] Aplicar las variables y desplegar.

Fuentes: `railway.toml:35-40`, `start.sh:22-31`.

## 5. Configurar el servicio `worker`

- [ ] Crear el servicio desde el mismo repositorio GitHub.
- [ ] Start Command: `bash start.sh`.
- [ ] Healthcheck Path: vacío.
- [ ] Variable de servicio: `PROC_TYPE=worker`.
- [ ] Aplicar las variables compartidas y desplegar.
- [ ] Confirmar en los logs `[start.sh] Iniciando Bitácora GRM (rol=worker)`.
- [ ] Confirmar en los logs que Celery queda `ready` y conecta con Redis y PostgreSQL.

Fuentes: `railway.toml:51-55`, `start.sh:221-269`, `start.sh:331-334`.

## 6. Configurar el servicio `beat`

- [ ] Crear el servicio desde el mismo repositorio GitHub.
- [ ] Start Command: `bash start.sh`.
- [ ] Healthcheck Path: vacío.
- [ ] Variable de servicio: `PROC_TYPE=beat`.
- [ ] `CELERY_BEAT_SCHEDULE_FILE=/tmp/celerybeat-schedule` o cualquier otra ruta escribible.
- [ ] Aplicar las variables compartidas y desplegar.
- [ ] Confirmar en los logs `[start.sh] Iniciando Bitácora GRM (rol=beat)`.
- [ ] Confirmar que solo existe una instancia de beat en el proyecto.

Fuentes: `railway.toml:56-58`, `start.sh:335-342`.

## 7. Inicializar la base de datos una sola vez

- [ ] Si la base de datos está vacía, ejecutar:

```bash
railway run --service web python -m app.db.init_db
```

- [ ] Resultado esperado: el comando termina sin error y el esquema queda inicializado.
- [ ] Mantener `AUTO_INIT_DB=false`; la aplicación aplica migraciones idempotentes al arrancar (`app/main.py:61-66`).
- [ ] Realizar el primer registro por la interfaz privada. Ese registro define la cuenta administradora; no publicar sus credenciales.

## 8. Desplegar y verificar

- [ ] Aplicar los cambios de variables mediante Deploy; un Restart no aplica cambios pendientes de Variables.
- [ ] Verificar el web:

```bash
curl -i https://bitacora-grmv2-production.up.railway.app/health
```

Resultado esperado: HTTP 200 y JSON con `status: ok`, `database: ok` y `redis: ok`.

- [ ] Verificar readiness, información y documentación:

```bash
curl -i https://bitacora-grmv2-production.up.railway.app/ready
curl -i https://bitacora-grmv2-production.up.railway.app/info
curl -i https://bitacora-grmv2-production.up.railway.app/docs
```

Resultado esperado: HTTP 200 en cada solicitud.

- [ ] Verificar la redirección inicial:

```bash
curl -i https://bitacora-grmv2-production.up.railway.app/
```

Resultado esperado sin sesión: HTTP 307 y `Location: /auth/login`. Con sesión válida, la ruta redirige a `/kanban` (`app/main.py:276-282`).
- [ ] Verificar los roles en los logs:

```bash
railway logs --service worker
railway logs --service beat
```

Resultado esperado: `rol=worker` y `rol=beat`, nunca `rol=web` en esos dos servicios.

- [ ] Ejecutar la comprobación local del diagnóstico de tickets:

```bash
python tools/verificacion/diagnostico_tickets.py
```

Resultado esperado: tres casos serializados correctamente. El script usa SQLite en memoria y no modifica la base de datos de producción (`tools/verificacion/diagnostico_tickets.py:30-33`).
- [ ] Iniciar sesión con las credenciales distribuidas por canal privado y comprobar el acceso al tablero Kanban.
- [ ] Verificar en el panel que PostgreSQL y Redis están activos y que no hay errores de conexión.

## 9. Acciones previas al 2026-12-01

Railway dejará de leer `railway.toml` el 2026-12-01. Completar esta lista antes de esa fecha.

| Ámbito | Ajuste | Valor que se replica | Comprobación |
|---|---|---|---|
| Build | Builder | `NIXPACKS` | [ ] Panel coincide con `railway.toml:31-32` |
| Build | Build Command | `pip install --upgrade pip && pip install -r requirements.txt` | [ ] Panel coincide con `railway.toml:33` |
| Deploy: web | Start Command | `bash start.sh` | [ ] Panel coincide con `railway.toml:35-36` |
| Deploy: web | Healthcheck Path | `/health` | [ ] Panel coincide con `railway.toml:37` |
| Deploy: web | Healthcheck Timeout | `60` | [ ] Panel coincide con `railway.toml:38` |
| Deploy: web | Restart Policy | `ON_FAILURE` | [ ] Panel coincide con `railway.toml:39` |
| Deploy: web | Maximum Retries | `5` | [ ] Panel coincide con `railway.toml:40` |
| Deploy: worker | Start Command | `bash start.sh` | [ ] Panel coincide con `railway.toml:51-55` |
| Deploy: worker | Healthcheck Path | Vacío | [ ] Panel coincide con `railway.toml:25-29` |
| Deploy: worker | Rol del proceso | `PROC_TYPE=worker` | [ ] Variable de servicio definida |
| Deploy: beat | Start Command | `bash start.sh` | [ ] Panel coincide con `railway.toml:56-58` |
| Deploy: beat | Healthcheck Path | Vacío | [ ] Panel coincide con `railway.toml:25-29` |
| Deploy: beat | Rol del proceso | `PROC_TYPE=beat` | [ ] Variable de servicio definida |
| Deploy: beat | Calendario | `CELERY_BEAT_SCHEDULE_FILE` en ruta escribible | [ ] Ruta writable verificada |
| Variables | `DEBUG` | `false` | [ ] Shared Variable definida |
| Variables | `USE_SQLITE` | `false` | [ ] Shared Variable definida |
| Variables | `PYTHONUNBUFFERED` | `1` | [ ] Shared Variable definida |
| Variables | `PYTHONDONTWRITEBYTECODE` | `1` | [ ] Shared Variable definida |
| Variables | `APP_VERSION` | `0.1.0` | [ ] Shared Variable definida |
| Shared Variable | `SECRET_KEY` | Valor real, no un placeholder | [ ] Panel contiene un valor real |
| Shared Variable | `PUBLIC_BASE_URL` | `https://bitacora-grmv2-production.up.railway.app` | [ ] Shared Variable definida |
| Shared Variable | `CORS_ORIGINS` | `["https://bitacora-grmv2-production.up.railway.app"]` | [ ] Shared Variable definida |
| Shared Variable | `DATABASE_URL` | Referencia real al plugin PostgreSQL | [ ] Plugin adjunto |
| Shared Variable | `REDIS_URL` | Referencia real al plugin Redis | [ ] Plugin adjunto |
| Shared Variable | `CELERY_BROKER_URL` | Valor real de Redis para la cola, base 1 | [ ] Shared Variable definida |
| Shared Variable | `CELERY_RESULT_BACKEND` | Valor real de Redis para resultados, base 2 | [ ] Shared Variable definida |

## 10. Endurecimiento posterior al despliegue

- [ ] Confirmar que `SECRET_KEY` es real y que el volumen `/data` está montado en el web.
- [ ] Confirmar que `CORS_ORIGINS` contiene solo el origen de producción.
- [ ] Confirmar que `DEBUG=false`, `USE_SQLITE=false` y `AUTO_INIT_DB=false`.
- [ ] Confirmar que no se activa `SEED_DEMO_USERS=true` en producción.
- [ ] Revisar logs del web, worker y beat en busca de errores de conexión o de configuración.
- [ ] Configurar copias de respaldo del plugin PostgreSQL.
- [ ] Mantener una sola instancia de `beat`.

## 11. Solución de problemas

| Síntoma | Causa | Comprobación y solución |
|---|---|---|
| `No start command detected` | Start Command ausente | Definir `bash start.sh` en Deploy settings |
| El web no arranca | `SECRET_KEY` ausente o insegura | Revisar Variables y el guard de `app/main.py:52-59` |
| El deployment falla en el healthcheck | `worker` o `beat` heredó `/health` | Vaciar Healthcheck Path |
| Los logs muestran `rol=web` | Falta `PROC_TYPE` | Definir `PROC_TYPE=worker` o `PROC_TYPE=beat` y desplegar |
| `psycopg2.OperationalError` | `DATABASE_URL` ausente o inválida | Adjuntar PostgreSQL y revisar `DATABASE_URL` |
| `redis.exceptions.ConnectionError` | `REDIS_URL` o Celery URLs ausentes | Adjuntar Redis y revisar las tres variables de Redis/Celery |
| `401 No autenticado` | No hay cookie `access_token` ni Bearer válido | Iniciar sesión o usar un JWT Bearer; el bypass por cabecera está cerrado |
| Celery beat no conserva el calendario | Ruta no escribible | Definir `CELERY_BEAT_SCHEDULE_FILE` en una ruta escribible |
| `/health` devuelve 503 | PostgreSQL no responde | Revisar logs y el estado del plugin PostgreSQL |
