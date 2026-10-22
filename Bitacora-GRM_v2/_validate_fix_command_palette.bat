@echo off
REM ============================================================
REM Validacion del fix: command-palette case-sensitivity
REM ============================================================
setlocal EnableDelayedExpansion

set "EXIT=0"
set "JSFILE=app\static\js\command-palette.js"
set "BACKEND=app\api\v1\buscar.py"

echo === TEST 1: NO debe existir condicion rota ===
findstr /C:"sel.tipo === " "%JSFILE%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [FAIL] Aun existe sel.tipo === con string sin normalizar
    set EXIT=1
) else (
    echo [OK]  No se encontro condicion sin normalizar
)

echo.
echo === TEST 2: Debe existir .toLowerCase ===
findstr /C:".toLowerCase" "%JSFILE%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Se encontro .toLowerCase
) else (
    echo [FAIL] No se encontro .toLowerCase
    set EXIT=1
)

echo.
echo === TEST 3: Debe existir el if con la variable normalizada ===
findstr /C:"tipoLower ===" "%JSFILE%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Existe tipoLower ===
) else (
    echo [FAIL] No existe tipoLower ===
    set EXIT=1
)

echo.
echo === TEST 4: Las 3 estrategias deben estar presentes ===
findstr /C:"htmx.ajax" "%JSFILE%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Estrategia 1: htmx.ajax
) else (
    echo [FAIL] Falta Estrategia 1
    set EXIT=1
)

findstr /C:"fetch(sel.url" "%JSFILE%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Estrategia 2: fetch + innerHTML
) else (
    echo [FAIL] Falta Estrategia 2
    set EXIT=1
)

findstr /C:"/tickets" "%JSFILE%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Estrategia 3: contiene /tickets
) else (
    echo [FAIL] Falta /tickets
    set EXIT=1
)

echo.
echo === TEST 5: Backend emite tipo=ticket ===
findstr /C:"ticket" "%BACKEND%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Backend menciona ticket
) else (
    echo [FAIL] Backend NO menciona ticket
    set EXIT=1
)

echo.
echo === TEST 6: Backend apunta a detalle-html ===
findstr /C:"detalle-html" "%BACKEND%" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK]  Backend apunta a /detalle-html
) else (
    echo [FAIL] Backend no apunta a detalle-html
    set EXIT=1
)

echo.
echo === TEST 7: Tamano del archivo local ===
for %%A in ("%JSFILE%") do set SIZE=%%~zA
echo Tamano local: !SIZE! bytes
echo Tamano produccion: 12.911 bytes (sin el fix)

echo.
echo === RESUMEN ===
if !EXIT! EQU 0 (
    echo TODOS LOS CHECKS PASARON
) else (
    echo HAY CHECKS FALLIDOS
)
echo.
exit /b !EXIT!