================================================================================
  README_V2.02 — SECURITY_HEADERS_CACHE_MIDDLEWARE
  Bitácora GRM v2 · Changelog atómico incremental
================================================================================

Fecha              : 2026-10-18
Versión base       : 132aaf2+2 (tras aplicar README_V2.01)
Versión objetivo   : HEAD tras este commit
Tipo de cambio     : FEAT — Middleware de cabeceras de seguridad + caché
Severidad          : ALTA — Seguridad / Operación
Riesgo de regresión: BAJO — Solo agrega cabeceras a respuestas, no modifica
                     comportamiento de endpoints ni respuestas JSON en éxito
Tickets asociados  : Mejoras #1 (Cache-Control) y #2 (Security headers) del
                     análisis estático
Automatizado por   : Agente worker (sub-agent mavis) — sesión bg_ccebbd2d

--------------------------------------------------------------------------------
 1. CÓDIGO MODIFICADO O PARCHE EXACTO
--------------------------------------------------------------------------------

A. app/main.py
   - Líneas 82-110 (NUEVO bloque, sin @@ con otros textos):
       # === Middleware: cabeceras de seguridad + caché de estáticos ===
       @app.middleware("http")
       async def add_security_and_cache_headers(request: Request, call_next):
           """Cabeceras de seguridad en todas las respuestas y caché corta
           para /static/*.

           - Estáticos (/static/*): Cache-Control: public, max-age=300 (5 min,
             permite iterar rápido en desarrollo sin invalidación manual) +
             X-Content-Type-Options: nosniff para evitar MIME-sniffing.

           - Todas las respuestas: X-Frame-Options: DENY (anti-clickjacking),
             Referrer-Policy: strict-origin-when-cross-origin y
             X-Content-Type-Options: nosniff. Se usan setdefault para
             respetar cualquier cabecera ya fijada por un endpoint o middleware
             posterior (p.ej. WhiteNoise).
           """
           response = await call_next(request)
           path = request.url.path

           # Cabeceras de seguridad presentes en TODAS las respuestas
           response.headers.setdefault("X-Frame-Options", "DENY")
           response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
           response.headers.setdefault("X-Content-Type-Options", "nosniff")

           # Caché de 5 minutos + íes anti-sniffing explícito para estáticos
           if path.startswith("/static") or path.startswith("/onboarding"):
               response.headers["Cache-Control"] = "public, max-age=300"

           return response

   - Ubicación: insertado entre `CORSMiddleware(...)` (línea 80) y el
     comentario `# === Archivos estáticos ...` que antes estaba en línea 82.
   - Total: +29 líneas, 0 líneas existentes modificadas.

B. Import requerido
   - El middleware usa `Request` que YA estaba disponible en el import:
       from fastapi import FastAPI, Request, ...
     No se agregan imports nuevos.

Archivos NO tocados: ninguno más (no se modificó app/api/v1/*, modelos,
servicios, ni templates).

--------------------------------------------------------------------------------
 2. BASE / ESTADO PREVIO
--------------------------------------------------------------------------------

- Diagnóstico del análisis estático (2026-10-18):
    * Static files servidos SIN Cache-Control (header ausente en producción).
    * 0 headers de seguridad presentes (X-Frame-Options, CSP, HSTS, etc.).
    * Probable causa de "sigue apareciendo el mismo error" reportada por el
      usuario: navegadores aplicando heurística de caché que servía el JS
      viejo aunque el servidor ya tenía el fix.

- Headers observados en producción pre-fix:
    GET /static/js/command-palette.js
      Server: railway-hikari
      etag: "4e404efe18da04b5c162959319165580"
      last-modified: Mon, 19 Oct 2026 00:29:42 GMT
      (NO Cache-Control, NO Expires, NO Surrogate-Control)

--------------------------------------------------------------------------------
 3. CAMBIO ÚNICO
--------------------------------------------------------------------------------

Middleware HTTP único (`add_security_and_cache_headers`) que añade a TODAS
las respuestas:

| Header                          | Valor                                  | Aplicado a        |
|---------------------------------|----------------------------------------|-------------------|
| X-Frame-Options                 | DENY                                   | Todas             |
| Referrer-Policy                 | strict-origin-when-cross-origin        | Todas             |
| X-Content-Type-Options          | nosniff                                | Todas             |
| Cache-Control                   | public, max-age=300                    | /static/* + /onboarding/* |

Patrón clave: `setdefault` en los headers de seguridad globales para NO
sobrescribir cabeceras que un middleware posterior (p.ej. WhiteNoise con
configuración propia de caché) pueda haber fijado. Para `Cache-Control` se
usa asignación directa porque sólo este middleware debe fijarlo en /static.

--------------------------------------------------------------------------------
 4. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------

- Endpoints (no se cambió ninguna ruta, signature, query param o response).
- Lógica de autenticación (JWT, OAuth2 password flow intacto).
- CORS (CORSMiddleware ya estaba configurado arriba del nuevo middleware).
- WhiteNoise (si está activo, sigue siendo un mount aparte y puede añadir
  sus propios headers — el setdefault respeta esa jerarquía).
- Servicio de archivos estáticos (StaticFiles mount en /static intacto).
- main.py en todo lo demás: routers, scheduler, exception handlers, etc.
- requirements.txt, Procfile, railway.toml.
- Frontend JS / HTML / CSS.
- Variables de entorno.
- Modelo de datos.
- Contratos del API.

--------------------------------------------------------------------------------
 5. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

- ¿Requiere cambio de variables de entorno? **NO**.
- ¿Requiere migrar DB? **NO**.
- ¿Requiere cambio de Worker en Railway? **NO**. El middleware se monta
  sobre el `app` ASGI existente. El Procfile actual (`web: uvicorn ...` o
  similar) sigue funcionando sin cambios.
- ¿Requiere rebuild de imagen Docker? **NO** (auto-deploy desde repo).
- ¿Hay riesgo de downtime? **BAJO** (no cambia comportamiento de endpoints
  en éxito, solo añade headers).

Procedimiento operacional Railway:
1. Push al branch `main` de `moisesarancibiasanchez-cpu/Bitacora-GRM_v2`.
2. Railway detecta el push y redespliega automáticamente.
3. Verificar `/health` responde 200 en menos de 60 segundos.
4. Verificar headers con curl:
    curl -I https://bitacora-grmv2-production.up.railway.app/health
    curl -I https://bitacora-grmv2-production.up.railway.app/static/js/command-palette.js
   Deben aparecer X-Frame-Options, Referrer-Policy, X-Content-Type-Options.
   El segundo debe incluir Cache-Control: public, max-age=300.

--------------------------------------------------------------------------------
 6. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

A. Validación estática (rápida, sin servidor):
    cmd> python -c "import ast; ast.parse(open('app/main.py').read())"
    Esperado: ningún output (AST válido).

B. Test del test de regresión del command-palette:
    cmd> python test_validar_fix_command_palette_case.py
    Esperado: TODOS LOS CHECKS PASARON (no se rompió el fix anterior).

C. Smoke test de headers (post-deploy):

    cmd> python smoke_test.py
    Esperado: ver sección "Headers de seguridad" con todas las filas en ✓.

    O manual:
    curl -sI https://bitacora-grmv2-production.up.railway.app/health | grep -E "X-Frame|Referrer|X-Content"
    curl -sI https://bitacora-grmv2-production.up.railway.app/static/js/command-palette.js | grep -E "X-Frame|Referrer|X-Content|Cache-Control"

    Salida esperada:
    X-Frame-Options: DENY
    X-Content-Type-Options: nosniff
    Referrer-Policy: strict-origin-when-cross-origin

    Y para el segundo:
    X-Frame-Options: DENY
    X-Content-Type-Options: nosniff
    Referrer-Policy: strict-origin-when-cross-origin
    Cache-Control: public, max-age=300

D. Test funcional (regression test del command-palette):
    1. Login válido, abrir dashboard, Ctrl+K.
    2. Buscar "INC", click en un ticket → debe abrir modal (NO página rota).
    3. Hard reload (Ctrl+Shift+R) → command-palette sigue funcionando.

E. Test de no-regresión de caché:
    1. Visitar el dashboard, abrir command-palette, hacer búsqueda.
    2. Cerrar navegador completamente.
    3. Re-abrir el dashboard dentro de 5 minutos → debería servir desde
       caché (respuesta < 50ms, sin llamar a Railway para el JS estático).
    4. Re-abrir el dashboard después de 5 minutos → nueva request, etag
       validado, posiblemente 304 Not Modified.

--------------------------------------------------------------------------------
 7. TRAZABILIDAD
--------------------------------------------------------------------------------

- Hash del commit se completará al hacer `git commit` (post-generación de
  este README).
- Sesión del sub-agent: mvs_dfc5a3548e1d4ce09b7691f4159e1dc5
- Background task ID: bg_ccebbd2d-a911-4931-91e6-bd17c1f99381
- Output completo del sub-agent en conversación de MiniMax Mavis.
- Validación sintáctica confirmada por el sub-agent con:
    python -c "import ast; ast.parse(...)"  → sin errores

--------------------------------------------------------------------------------
 8. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL (resumen ejecutivo)
--------------------------------------------------------------------------------

1. Commit (incluyendo este README_V2.02_*.txt):
    git add app/main.py docs/README_V2.02_*.txt
    git commit -m "feat(security): middleware de headers de seguridad + cache"

2. Push:
    git push origin main

3. Verificación post-deploy (5 min):
    a. /health responde 200
    b. curl -sI /static/* muestra Cache-Control: public, max-age=300
    c. curl -sI /health muestra X-Frame-Options: DENY y Referrer-Policy
    d. Command-palette sigue funcionando (no regresión)
    e. Railway logs no muestran errores durante 5 minutos

4. Rollback (si falla):
    git revert HEAD
    git push origin main
    Railway redespliega la versión anterior automáticamente.

5. Monitoreo continuo:
    - Vigilar latencia p95 del endpoint /static/* (debería bajar ~30% por caché)
    - Vigilar errores 4xx/5xx en /api/* (no deberían cambiar)
    - Vigilar reports de clickjacking en security headers scanner

================================================================================
FIN README_V2.02
================================================================================