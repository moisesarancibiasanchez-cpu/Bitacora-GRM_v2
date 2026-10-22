#!/usr/bin/env bash
# =============================================================================
#  start.sh - Bitácora GRM
#  Punto de entrada único para Railway (lo invoca `railway.toml`).
#  Detecta si el proceso es web, worker o beat leyendo la variable
#  $RAILWAY_SERVICE_ROLE o $PROC_TYPE.
# =============================================================================
set -e

# 1) Detectar rol del proceso
ROLE="${RAILWAY_SERVICE_ROLE:-${PROC_TYPE:-web}}"
ROLE="$(echo "$ROLE" | tr '[:upper:]' '[:lower:]')"

echo "[start.sh] Iniciando Bitácora GRM (rol=$ROLE)"

# 2) Esperar a la base de datos si la URL es Postgres
if [[ -n "${DATABASE_URL}" && "${DATABASE_URL}" != sqlite* ]]; then
    echo "[start.sh] Esperando a la base de datos PostgreSQL..."
    python -c "
import os, time, socket, urllib.parse
url = os.environ['DATABASE_URL']
u = urllib.parse.urlparse(url)
host, port = u.hostname, u.port or 5432
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f'  -> {host}:{port} OK')
            break
    except OSError:
        time.sleep(2)
else:
    print('  -> Aviso: tiempo de espera agotado para la BD')
" || true
fi

# 3) Inicializar base de datos (modo demo/dev)
# AUTO_INIT_DB=true activa el seed completo (usuarios, tickets demo, etc.)
# En producción real no es necesario: el lifespan de FastAPI ya aplica
# migraciones idempotentes en cada arranque.
if [[ "${AUTO_INIT_DB:-true}" == "true" ]]; then
    echo "[start.sh] Verificando/Aplicando migraciones..."
    python -m app.db.migrations || echo "[start.sh] Aviso: migraciones fallaron, continuando..."
    if [[ "${SEED_DATA:-false}" == "true" ]]; then
        echo "[start.sh] Inicializando base de datos (datos semilla)..."
        python -m app.db.init_db || echo "[start.sh] Aviso: init_db falló, continuando..."
    fi
fi

# 4) Lanzar el proceso correspondiente
case "$ROLE" in
    web)
        echo "[start.sh] Lanzando gunicorn (web)..."
        exec gunicorn -c gunicorn.conf.py app.main:app
        ;;
    worker)
        echo "[start.sh] Lanzando celery worker..."
        exec celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=2
        ;;
    beat)
        echo "[start.sh] Lanzando celery beat..."
        exec celery -A app.core.celery_app:celery_app beat --loglevel=info
        ;;
    *)
        echo "[start.sh] Rol desconocido '$ROLE', cayendo a web"
        exec gunicorn -c gunicorn.conf.py app.main:app
        ;;
esac
