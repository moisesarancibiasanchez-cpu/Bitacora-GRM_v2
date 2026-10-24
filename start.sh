#!/usr/bin/env bash
# =============================================================================
#  start.sh - Bitácora GRM
#  Punto de entrada único para Railway (lo invoca `railway.toml`).
#  Detecta si el proceso es web, worker o beat leyendo la variable
#  $RAILWAY_SERVICE_ROLE o $PROC_TYPE.
# =============================================================================
set -e

# 0) SECRET_KEY
# -----------------------------------------------------------------------------
# `app/core/config.py::es_secreto_inseguro()` aborta el arranque de la app si
# la SECRET_KEY está vacía o es un placeholder. `start.sh` es el punto donde
# eso puede resolverse sin depender de que alguien configure el panel de
# Railway. Aquí:
#   1) se respeta la SECRET_KEY del entorno si es válida;
#   2) si no, se reusa la que quedó persistida en un archivo (idempotente
#      entre reinicios: nunca se regenera si ya existe una válida);
#   3) si no existe, se genera una fuerte (32 bytes) y se persiste con 600.
#
# Rutas de persistencia, en orden de preferencia:
#   $SECRET_KEY_FILE > /data/secret_key (volumen persistente de Railway)
#   > $HOME/.bitacora/secret_key > /app/.runtime/secret_key > ./.runtime/secret_key
#
# OJO: sin un volumen montado en /data el filesystem del contenedor es
# efímero, así que cada reinicio genera una clave nueva (las sesiones
# abiertas se invalidan, pero no se abre ninguna brecha de seguridad). Para
# que la clave sea estable hay que montar un volumen en /data (Railway ->
# Settings -> Volumes -> mount path /data) en los servicios web/worker/beat.
# La clave nunca se escribe en el log: sólo su longitud.

# Devuelve 0 (true) si el valor está vacío o es un placeholder conocido.
_secret_key_insegura() {
    local valor="${1:-}"
    local minusculas
    minusculas="$(printf '%s' "$valor" | tr '[:upper:]' '[:lower:]')"
    if [[ -z "$valor" || -z "$minusculas" ]]; then
        return 0
    fi
    case "$minusculas" in
        change-me*|changeme*|change_me*|secret|secret-key|secretkey|dev-secret*|devsecret*|dev_secret*|development|insecure|placeholder*|todo|cambiar*|x-key|xkey|your-secret*|your_secret*|1234567890|abc123|test-secret*)
            return 0
            ;;
    esac
    case "$minusculas" in
        *change-me*|*changeme*|*change_me*|*placeholder*|*your-secret*|*your_secret*|*insecure*|*dev-secret*|*devsecret*)
            return 0
            ;;
    esac
    return 1
}

# Genera una clave aleatoria fuerte: openssl si está, si no Python.
_generar_secret_key() {
    local clave=""
    if command -v openssl >/dev/null 2>&1; then
        clave="$(openssl rand -hex 32 2>/dev/null || true)"
    fi
    if [[ -z "$clave" ]] && command -v python >/dev/null 2>&1; then
        clave="$(python -c 'import secrets; print(secrets.token_urlsafe(48))' 2>/dev/null || true)"
    fi
    if [[ -z "$clave" ]] && command -v python3 >/dev/null 2>&1; then
        clave="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))' 2>/dev/null || true)"
    fi
    printf '%s' "$clave"
}

# Rutas candidatas donde puede vivir la clave persistida (una por línea).
_rutas_secret_key() {
    local rutas=()
    if [[ -n "${SECRET_KEY_FILE:-}" ]]; then
        printf '%s\n' "$SECRET_KEY_FILE"
        return 0
    fi
    rutas+=("/data/secret_key")
    if [[ -n "${HOME:-}" ]]; then
        rutas+=("${HOME}/.bitacora/secret_key")
    fi
    rutas+=("/app/.runtime/secret_key")
    rutas+=("$(pwd)/.runtime/secret_key")
    printf '%s\n' "${rutas[@]}"
}

# Persiste la clave en $1. Devuelve 0 si la escribió, 2 si ya existía
# (carrera con otro servicio) y 1 si no se pudo escribir.
_persistir_secret_key() {
    local destino="$1"
    local clave="$2"
    local dir tmp
    dir="$(dirname "$destino")"
    mkdir -p "$dir" 2>/dev/null || true
    if [[ ! -d "$dir" || ! -w "$dir" ]]; then
        return 1
    fi
    tmp="$(mktemp "${destino}.tmp.XXXXXX" 2>/dev/null || true)"
    if [[ -z "$tmp" ]]; then
        tmp="${destino}.tmp.$$"
    fi
    if ! printf '%s\n' "$clave" > "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    chmod 600 "$tmp" || true
    # `ln` es atómico: si otro proceso (p. ej. el servicio worker sobre el
    # mismo volumen) ya creó el archivo, NO se sobrescribe su clave.
    if ln "$tmp" "$destino" 2>/dev/null; then
        rm -f "$tmp"
        # `ln` puede resolver como copia (p. ej. en filesystems sin hard
        # links): se reafirma el 600 sobre el archivo final en cualquier caso.
        chmod 600 "$destino" 2>/dev/null || true
        return 0
    fi
    rm -f "$tmp"
    if [[ -f "$destino" ]]; then
        return 2
    fi
    return 1
}

# Deja SECRET_KEY lista (y exportada) para los procesos hijos.
_asegurar_secret_key() {
    local valor="${SECRET_KEY:-}"
    local clave=""
    local ruta=""
    local existente=""

    # 1) La del entorno manda si es válida.
    if ! _secret_key_insegura "$valor"; then
        echo "[start.sh] SECRET_KEY: se usa la definida en el entorno"
        return 0
    fi

    # 2) Reutilizar la clave ya persistida (idempotente entre reinicios).
    while IFS= read -r ruta; do
        if [[ -z "$ruta" || ! -f "$ruta" ]]; then
            continue
        fi
        clave="$(head -n 1 "$ruta" 2>/dev/null | tr -d '\r\n')"
        if [[ -n "$clave" && ${#clave} -ge 32 ]] && ! _secret_key_insegura "$clave"; then
            chmod 600 "$ruta" 2>/dev/null || true
            SECRET_KEY="$clave"
            export SECRET_KEY
            echo "[start.sh] SECRET_KEY reusada de $ruta (len=${#clave})"
            return 0
        fi
    done < <(_rutas_secret_key)

    # 3) Generar una nueva y persistirla.
    clave="$(_generar_secret_key)"
    if [[ -z "$clave" || ${#clave} -lt 32 ]]; then
        echo "[start.sh] ERROR: no se pudo generar una SECRET_KEY segura." >&2
        echo "[start.sh] Defina SECRET_KEY en el panel de Railway (o en el entorno)." >&2
        exit 1
    fi

    while IFS= read -r ruta; do
        if [[ -z "$ruta" ]]; then
            continue
        fi
        if _persistir_secret_key "$ruta" "$clave"; then
            echo "[start.sh] SECRET_KEY generado (len=${#clave}) y persistido en $ruta"
            SECRET_KEY="$clave"
            export SECRET_KEY
            return 0
        fi
        # Carrera con otro servicio: se adopta la clave que quedó.
        if [[ -f "$ruta" ]]; then
            existente="$(head -n 1 "$ruta" 2>/dev/null | tr -d '\r\n')"
            if [[ -n "$existente" && ${#existente} -ge 32 ]]; then
                SECRET_KEY="$existente"
                export SECRET_KEY
                echo "[start.sh] SECRET_KEY reusada de $ruta (len=${#existente})"
                return 0
            fi
        fi
    done < <(_rutas_secret_key)

    # No se pudo persistir en ninguna ruta. La clave generada SIGUE siendo
    # criptográficamente segura, así que la aplicación arranca con ella en
    # lugar de abortar: abortar aquí dejaría la web en 502 por un problema de
    # filesystem, que es un outage mucho peor que invalidar las sesiones
    # abiertas en el próximo reinicio. La clave NUNCA se escribe en el log:
    # sólo su longitud.
    echo "[start.sh] AVISO: no se pudo persistir la SECRET_KEY generada." >&2
    echo "[start.sh] AVISO: la app arranca con una clave efímera; las sesiones" >&2
    echo "[start.sh] AVISO: abiertas se invalidarán en el próximo reinicio." >&2
    echo "[start.sh] AVISO: monta un volumen en /data o define SECRET_KEY en el" >&2
    echo "[start.sh] AVISO: panel de Railway para que la clave sea estable." >&2
    SECRET_KEY="$clave"
    export SECRET_KEY
    return 0
}

_asegurar_secret_key

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
