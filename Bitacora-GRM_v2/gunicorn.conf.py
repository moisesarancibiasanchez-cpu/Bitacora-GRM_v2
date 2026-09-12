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

# === Process name (visible en `ps`) ===
proc_name = "bitacora-grm-web"

# === Preload para ahorrar memoria compartida ===
preload_app = True
