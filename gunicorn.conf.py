# =============================================================================
#  gunicorn.conf.py - Bitácora GRM (producción)
# =============================================================================
import os
import multiprocessing

# === Puerto y bind ===
# Railway expone la variable $PORT; en local cae a 8000.
bind = os.getenv("BIND", f"0.0.0.0:{os.getenv('PORT', '8000')}")

# === Workers ===
# 2 * CPU + 1 es la fórmula clásica; en Railway la cuota de CPU es compartida,
# por lo que 2 workers + 4 threads suele ser suficiente para un servicio web.
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = int(os.getenv("WEB_THREADS", "4"))
worker_class = "uvicorn.workers.UvicornWorker"

# === Timeouts ===
timeout = 60
graceful_timeout = 30
keepalive = 5

# === Reciclado de workers para evitar fugas de memoria ===
max_requests = 1000
max_requests_jitter = 50

# === Logs ===
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'

# === Cabeceras del proxy inverso ===
# Railway termina el TLS y reenvía la petición con `X-Forwarded-Proto: https`.
# Sin esto, uvicorn ignora esas cabeceras, la aplicación cree estar en HTTP
# y las redirecciones que genera degradan a `http://` (por ejemplo el 307 de
# `/onboarding`), rompiendo el bucle HTTPS -> HTTP -> HTTPS.
#
# `*` es seguro aquí porque el servicio solo es alcanzable a través del proxy
# de Railway (no hay puerto público) y el borde sobrescribe las cabeceras
# `X-Forwarded-*` que envía el cliente. Se puede restringir con la variable
# `FORWARDED_ALLOW_IPS` si el despliegue cambia de topología.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

# === Process name (visible en `ps`) ===
proc_name = "bitacora-grm-web"

# === Preload para ahorrar memoria compartida ===
preload_app = True
