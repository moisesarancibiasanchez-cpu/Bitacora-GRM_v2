# Verificaciones reproducibles — Bitácora GRM

Scripts de verificación **sin mocks y sin datos falsos** que comprueban los
arreglos aplicados en la versión 1.002 (ver `README_V1.002_*.txt` en la raíz).

Todos se ejecutan contra datos propios: base de datos SQLite **en memoria**,
un servidor Starlette real o un sandbox de shell. Ninguno toca la base de
datos de producción ni la de Railway.

## Uso

```bash
# Desde la raíz del repositorio
python tools/verificacion/verificar_arranque.py
python tools/verificacion/verificar_migrations.py
python tools/verificacion/verificar_config.py
python tools/verificacion/verificar_cors.py
python tools/verificacion/verificar_sqlite_lower.py

# El de start.sh necesita bash (Git Bash en Windows / Linux / macOS)
bash tools/verificacion/verificar_secret_key.sh

# Contra el despliegue (requieren red)
python tools/verificacion/barrer_rutas.py [URL_BASE]
python tools/verificacion/inventariar_rutas.py [URL_BASE]
python tools/verificacion/esperar_redeploy.py
```

Cada script imprime una línea `PASA`/`FALLA` por comprobación y termina con
un resumen `RESULTADO ...`. El código de salida es `0` si todo pasa.

## Qué comprueba cada uno

| Script | Comprobaciones | Qué cubre |
|---|---|---|
| `verificar_arranque.py` | 16 | Arranque real de la aplicación (lifespan completo de FastAPI) contra una BD SQLite temporal: guard de configuración, migraciones aplicadas, `/health`, login real `admin/admin123`, `/kanban` con el badge `data-resultado-pruebas` y `/dashboard` con las islas JSON de la paleta. Comprueba además que en la BD quedan el estado `Producción OK` y sus 3 transiciones. |
| `verificar_migrations.py` | 15 | Aislamiento por `SAVEPOINT` de cada unidad de datos; comparador booleano por dialecto en `etiquetas.activo` (PostgreSQL `BOOLEAN` vs SQLite entero); creación del estado `Producción OK` y de sus 3 transiciones; idempotencia en el segundo arranque. |
| `verificar_config.py` | 11 | Derivación de `PUBLIC_BASE_URL` desde `RAILWAY_PUBLIC_DOMAIN` / `RAILWAY_STATIC_URL`; respeto del valor explícito; guard de HTTPS intacto; `CORS_ORIGINS='*'` no bloqueante en producción; `SECRET_KEY` vacía **sí** bloqueante; comodín en desarrollo **sí** bloqueante. |
| `verificar_cors.py` | 9 | Comportamiento real de Starlette con la configuración exacta de `app/main.py`: con el comodín no se emite `Access-Control-Allow-Credentials`, por lo que el navegador no puede leer respuestas autenticadas cross-origin. |
| `verificar_sqlite_lower.py` | 6 | `LOWER()` de SQLite sólo normaliza ASCII: `LOWER('Producción OK')` → `'producción ok'`. Demuestra por qué el literal SQL sin tilde no podía coincidir con el nombre canónico del estado. |
| `verificar_secret_key.sh` | 22 | Lógica de `start.sh`: generación, persistencia, idempotencia entre reinicios, rechazo de placeholders, permisos `600`, y que la clave **nunca** se escribe en el log. |
| `barrer_rutas.py` | 9 | Barrido de las 38 rutas contra el despliegue, con sesión iniciada: `/health`, login real, y 0 respuestas 5xx. Comprueba además que el dashboard sirve la paleta desde el servidor y que el JS no la re-declara (chequeo por identificador, no por valor de hex: `#16a34a` y `#94a3b8` coinciden con las paletas de prioridad y de etiquetas). |
| `inventariar_rutas.py` | 1 | Inventario real de rutas contra el esquema OpenAPI del despliegue, contraste con la lista de 38 rutas del README V1.001, y rastreo de enlaces internos rotos en las 13 páginas principales. |
| `esperar_redeploy.py` | 1 | Vigila `/health` hasta que responda 200 tras un push (30 s entre intentos) y, cuando la app levanta, valida el login y las rutas autenticadas. |

## Nota de plataforma

`verificar_secret_key.sh` informa el modo de permisos del archivo persistido.
En Windows con Git Bash sobre NTFS el comando `chmod` es un *no-op* (el
filesystem no representa el bit POSIX de otros-lectura), así que el modo
`600` **no es verificable ahí**; el script lo detecta y lo reporta en lugar
de fallar. En el contenedor de Railway (Linux) el `chmod 600` sí se aplica.

`_probe_config.py` es un módulo auxiliar: lo invoca `verificar_config.py` en
un subproceso por escenario, porque `Settings` es un singleton y cada
escenario necesita un `os.environ` limpio.
