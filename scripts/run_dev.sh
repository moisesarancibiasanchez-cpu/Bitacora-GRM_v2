#!/bin/bash
# ============================================================================
#  Script de arranque en modo desarrollo
#  - Crea BD SQLite con datos semilla
#  - Lanza FastAPI con auto-reload
# ============================================================================

set -e

cd "$(dirname "$0")/.."

echo "▶ Bitácora GRM - Modo desarrollo"
echo ""

# 1. Crear/actualizar BD
echo "1) Inicializando base de datos..."
USE_SQLITE=true python -m app.db.init_db

# 2. Arrancar API
echo ""
echo "2) Arrancando FastAPI en http://localhost:8000"
echo "   Documentación: http://localhost:8000/docs"
echo ""
USE_SQLITE=true uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
