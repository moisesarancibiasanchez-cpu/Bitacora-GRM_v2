================================================================================
  README_V2.01 — ERROR_HANDLING_BUSCAR_KANBAN
  Bitácora GRM v2 · Changelog atómico incremental
================================================================================

Fecha              : 2026-10-18
Versión base       : 04c45f7 (docs: reporte de fix raíz del buscador superior)
Versión objetivo   : 132aaf2+1 (este commit)
Tipo de cambio     : FIX — Manejo de errores robusto en endpoints críticos
Severidad          : ALTA — Operacional / UX
Riesgo de regresión: BAJO — Solo agrega bloques try/except, no modifica lógica
Tickets asociados  : Mejora #4 del análisis estático (ratio error handling 0.50)
Automatizado por   : Agente worker (sub-agent mavis) — sesión bg_56b4c077

--------------------------------------------------------------------------------
 1. CÓDIGO MODIFICADO O PARCHE EXACTO
--------------------------------------------------------------------------------

A. app/api/v1/buscar.py
   - Línea 11 (imports): se agrega HTTPException a la importación de FastAPI.
       ANTES:  from fastapi import APIRouter, Depends, Query
       DESPUÉS: from fastapi import APIRouter, Depends, HTTPException, Query
   - Línea 37: el cuerpo del endpoint `busqueda_global` se envuelve con `try:`.
   - Después del `return` final (línea 179 aprox) se agrega:
       except HTTPException:
           raise
       except Exception as e:
           logger.exception("Error en /buscar: %s", e)
           raise HTTPException(status_code=500, detail=f"Error interno: {type(e).__name__}")
   - Total: 1 endpoint modificado, +9 líneas, 0 líneas de lógica modificadas.

B. app/api/v1/kanban.py
   - Línea 4 (imports): se agrega `import logging`.
   - Línea 5: se agrega HTTPException a la importación de FastAPI.
       ANTES:  from fastapi import APIRouter, Depends, Request
       DESPUÉS: from fastapi import APIRouter, Depends, HTTPException, Request
   - Línea 17: se agrega `logger = logging.getLogger(__name__)` antes del router.
   - Línea 37: el cuerpo de `tablero_kanban` se envuelve con `try:`.
   - Línea 76: el cuerpo de `columna_kanban` se envuelve con `try:`.
   - Cada función termina con:
       except HTTPException:
           raise
       except Exception as e:
           logger.exception("Error en /kanban: %s", e)  # o /kanban/columna/{estado_id}
           raise HTTPException(status_code=500, detail=f"Error interno: {type(e).__name__}")
   - Total: 2 endpoints modificados, +18 líneas, 0 líneas de lógica modificadas.

Archivos NO tocados: ninguno más (no se modificó app/main.py, ni modelos,
servicios, ni templates).

--------------------------------------------------------------------------------
 2. BASE / ESTADO PREVIO
--------------------------------------------------------------------------------

- Diagnóstico del análisis estático (2026-10-18):
    * `buscar.py`: 0 try / 0 except — endpoint crítico sin manejo de errores
    * `kanban.py`: 0 try / 0 except — el tablero entero se cae sin protección
    * Promedio app: 0.50 except por endpoint (objetivo: ≥3)

- Síntomas esperados en producción si esto falla:
    * Usuario recibe 500 Internal Server Error con stack trace HTML
    * Railway logs muestran traceback de Python (no mensaje legible)
    * Imposible hacer triage remoto sin acceso a logs

--------------------------------------------------------------------------------
 3. CAMBIO ÚNICO
--------------------------------------------------------------------------------

Agregar manejo de errores consistente a 3 endpoints críticos (`/buscar`,
`/kanban`, `/kanban/columna/{id}`) usando el patrón:

    try:
        # lógica de negocio intacta
    except HTTPException:
        raise                          # respetar errores HTTP bien formados
    except Exception as e:
        logger.exception("Error en <path>: %s", e)
        raise HTTPException(500, f"Error interno: {type(e).__name__}")

Esto convierte los 500 silenciosos en:
1. Mensajes JSON estructurados (FastAPI los serializa automáticamente)
2. Logs con traceback completo (vía logger.exception, no print)
3. HTTPException legibles para el frontend (con tipo de error)

--------------------------------------------------------------------------------
 4. QUÉ NO SE MODIFICÓ
--------------------------------------------------------------------------------

- Lógica de queries SQL (no se cambió ningún `.filter()`, `.order_by()`,
  `.limit()` ni `.ilike()`).
- Modelos (`app/models/*`).
- Servicios (`app/services/*`).
- Templates (`app/templates/*`).
- Frontend JS.
- Endpoints no cambiar.
- main.py.
- requirements.txt ni Procfile ni railway.toml.
- Configuración de deploy.
- Contrato del API (response shape intacto en éxito).

--------------------------------------------------------------------------------
 5. REQUERIMIENTOS DE DESPLIEGUE
--------------------------------------------------------------------------------

- ¿Requiere cambio de variables de entorno? **NO**.
- ¿Requiere migrar DB? **NO**.
- ¿Requiere cambio de Worker en Railway? **NO** (gunicorn/uvicorn levanta
  automáticamente con el nuevo código en el próximo deploy).
- ¿Requiere rebuild de imagen Docker? **NO** (auto).
- ¿Hay riesgo de downtime? **BAJO** (cambio aditivo, no cambia contrato).

Procedimiento operacional Railway:
1. Push al branch `main` de `moisesarancibiasanchez-cpu/Bitacora-GRM_v2`.
2. Railway detecta el push y redespliega automáticamente.
3. Verificar `/health` responde 200 en menos de 60 segundos.
4. Verificar `/api/v1/buscar?q=test` (sin auth) responde 401 (sin cambio).

--------------------------------------------------------------------------------
 6. PROCEDIMIENTO DE PRUEBA RECOMENDADO
--------------------------------------------------------------------------------

A. Validación estática (rápida, sin servidor):
   cmd> python -c "import ast; ast.parse(open('app/api/v1/buscar.py').read())"
   cmd> python -c "import ast; ast.parse(open('app/api/v1/kanban.py').read())"
   Esperado: ningún output (AST válido).

B. Test del test de regresión existente (command-palette):
   cmd> python test_validar_fix_command_palette_case.py
   Esperado: TODOS LOS CHECKS PASARON.

C. Smoke test post-deploy:
   1. Login válido contra `/api/v1/auth/login` → obtener Bearer token.
   2. GET `/api/v1/buscar?q=INC&limite=3` con Bearer → 200 con `tickets`,
      `espacios`, `tableros`, `usuarios`, `etiquetas`.
   3. GET `/kanban` con sesión de cookie → 200 HTML del tablero.
   4. GET `/kanban/columna/1` con sesión → 200 fragmento HTML.

D. Test de error path (validar el nuevo manejo):
   1. Bajar temporalmente la DB (cambiar DATABASE_URL a algo inválido).
   2. Llamar `/api/v1/buscar?q=test` → debe devolver 500 con detalle
      `{"detail": "Error interno: OperationalError"}` (no HTML de traceback).
   3. Verificar en Railway logs que aparece `logger.exception` con el
      traceback completo.

E. Test de no-regresión:
   1. Confirmar que el command-palette sigue cargando bien el modal de
      tickets (test ya automatizado en
      `test_validar_fix_command_palette_case.py`).

--------------------------------------------------------------------------------
 7. TRAZABILIDAD
--------------------------------------------------------------------------------

- Hash del commit se completará al hacer `git commit` (post-generación de este README).
- Sesión del sub-agent: mvs_902918ad1c5c47f988ea2423a008e19b
- Background task ID: bg_56b4c077-156b-466f-8e88-307a6512b474
- Output completo del sub-agent en conversación de MiniMax Mavis.
- Validación sintáctica confirmada por el sub-agent con:
    python -c "import ast; ast.parse(...)"  → sin errores

--------------------------------------------------------------------------------
 8. INSTRUCCIONES DE DESPLIEGUE OPERACIONAL (resumen ejecutivo)
--------------------------------------------------------------------------------

1. Commit (incluyendo este README_V2.01_*.txt):
    git add app/api/v1/buscar.py app/api/v1/kanban.py docs/README_V2.01_*.txt
    git commit -m "fix(api): agregar manejo de errores robusto en /buscar y /kanban"

2. Push:
    git push origin main

3. Verificación post-deploy (5 min):
    a. /health responde 200
    b. /api/v1/buscar sin auth responde 401 (sin cambio de comportamiento)
    c. Login válido → /api/v1/buscar?q=test responde 200 con resultados
    d. Railway logs no muestran tracebacks de Python en requests exitosos

4. Rollback (si falla):
    git revert HEAD
    git push origin main
    Railway redespliega la versión anterior automáticamente.

================================================================================
FIN README_V2.01
================================================================================