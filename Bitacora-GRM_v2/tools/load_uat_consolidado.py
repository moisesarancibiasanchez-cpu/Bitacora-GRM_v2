"""
================================================================================
ETL: Carga masiva de Consolidado UAT → tabla `tickets`
================================================================================
Hoja origen:   Consolidado_UAT_Cruce_GARANTIA_v3.xlsx  →  CONSOLIDADO UAT
Tabla destino: tickets  (PostgreSQL, 31 columnas)
Modo por defecto:  --dry-run  (NO escribe hasta confirmar)

Uso:
    # 1) Validar (no escribe nada)
    python tools/load_uat_consolidado.py --dry-run

    # 2) Cargar a Railway (producción) - DRY-RUN FORZADO sin --force
    python tools/load_uat_consolidado.py --target railway

    # 3) Limitar a N filas para probar
    python tools/load_uat_consolidado.py --dry-run --limit 50

Variables de entorno necesarias (en Railway o .env):
    DATABASE_URL  = postgresql://user:pass@host:5432/dbname

Dependencias:  openpyxl, sqlalchemy, psycopg2-binary
================================================================================
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import openpyxl
except ImportError:
    sys.stderr.write("Falta openpyxl.  pip install openpyxl\n")
    raise

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
except ImportError:
    sys.stderr.write("Falta sqlalchemy.  pip install sqlalchemy\n")
    raise

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
EXCEL_PATH = Path(os.environ.get(
    "UAT_EXCEL_PATH",
    "/workspace/user_input_files/Consolidado_UAT_Cruce_GARANTIA_v3.xlsx",
))
HOJA = "CONSOLIDADO UAT"

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / f"uat_load_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("uat_etl")


# ============================================================================
# HELPERS — Tipos y normalización
# ============================================================================
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def to_bool(v: Any) -> Optional[bool]:
    """Si/No/Yes/No → True/False; vacío → None."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("si", "sí", "yes", "true", "1"):
        return True
    if s in ("no", "false", "0"):
        return False
    return None


def to_date(v: Any) -> Optional[datetime]:
    """Acepta date/datetime/str ISO. Devuelve datetime UTC o None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
    if hasattr(v, "isoformat"):  # datetime.date
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    s = str(v).strip()
    if not FECHA_RE.match(s):
        # Intentar otros formatos comunes
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
    try:
        # "YYYY-MM-DD" o "YYYY-MM-DD HH:MM:SS"
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def truncate(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s[:n] if s else None


def portada_color_from_prioridad(p: Any) -> str:
    """ALTA→rojo | MEDIA→naranja | BAJA→verde | (vacío)→gris."""
    if not p:
        return "#94a3b8"
    s = str(p).strip().upper()
    if s.startswith("AL"):  # ALTA / Alto / Alta
        return "#FF0000"
    if s.startswith("ME"):  # MEDIA / Medio
        return "#FFA500"
    if s.startswith("BA"):  # BAJA / Bajo
        return "#008000"
    return "#94a3b8"


def normalize_resultado(v: Any) -> Optional[str]:
    """Normaliza 'Resultado' a valores LOV del modelo."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s_up = s.upper()
    if "POSTERGADA" in s_up or "POSTERG" in s_up:
        return "POSTERGADA"
    if "BLOQUEADO" in s_up or "BLOQ" in s_up:
        return "DESESTIMADA"
    mapping = {
        "OK": "OK",
        "NOK": "NOK",
        "N/A": "N/A",
        "OK CON OBS.": "OK CON OBS.",
        "OK CON OBS": "OK CON OBS.",
        "OK CON OBSERVACIONES": "OK CON OBS.",
        "DESESTIMADA": "DESESTIMADA",
    }
    return mapping.get(s_up) or mapping.get(s) or s


# ============================================================================
# RESUMEN SEMÁNTICO (no truncado mecánico)
# ============================================================================
STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "al", "a", "en", "por", "para",
    "y", "o", "u", "con", "sin", "que", "se", "es", "un", "una", "unos",
    "unas", "lo", "le", "les", "su", "sus", "mi", "mis", "tu", "tus",
    "este", "esta", "estos", "estas", "ese", "esa", "eso", "esos", "esas",
    "ser", "estar", "haber", "tener", "debe", "deben", "puede", "pueden",
    "realizar", "verificar", "comprobar", "validar", "confirmar", "revisar",
    "dentro", "donde", "cuando", "como", "si", "no", "tambien", "más", "menos",
    "botón", "campo", "campos", "sistema", "pantalla", "módulo", "modulo",
    "funcionalidad", "funcionalidades",
}

VERBOS_CLAVE = {
    "guardar", "calcular", "validar", "verificar", "cargar", "mostrar",
    "visualizar", "registrar", "controlar", "manejar", "generar", "enviar",
    "recibir", "crear", "editar", "eliminar", "notificar", "completar",
    "confirmar", "ejecutar", "asignar", "rechazar", "bloquear", "desbloquear",
    "cerrar", "abrir", "imprimir", "exportar", "importar", "filtrar", "ordenar",
    "permitir", "denegar", "reintentar", "loguear", "auditar",
}


def resumen_semantico(texto: str, fallback_hu: str = "", fallback_historia: str = "") -> str:
    """
    Genera un resumen semántico de ~50 caracteres (máx 60).
    Si no hay texto, usa fallback_hu → fallback_historia.
    """
    if not texto or not texto.strip():
        if fallback_hu:
            return truncate(fallback_hu, 60)
        if fallback_historia:
            return truncate(fallback_historia, 60)
        return "Sin descripción"

    # Limpiar
    t = texto.replace("\n", " ").replace("\r", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r'^[\"\'\u201c\u201d]', "", t)
    t = re.sub(r'[\"\'\u201c\u201d]$', "", t)

    # Tokenizar
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", t)

    # Construir frase compacta preservando orden
    out: List[str] = []
    char_count = 0
    has_verb = False
    for w in words:
        wl = w.lower()
        if wl in STOPWORDS and len(out) > 0:
            continue
        new_len = char_count + len(w) + (1 if out else 0)
        if new_len > 60:
            break
        out.append(w)
        char_count = new_len
        if wl in VERBOS_CLAVE:
            has_verb = True

    resumen = " ".join(out)

    # Si quedó muy corto, intentar agregar palabras clave desde el final
    if len(resumen) < 20:
        for w in reversed(words):
            if w.lower() not in STOPWORDS and w not in out:
                if char_count + len(w) + 1 <= 60:
                    resumen = w + " " + resumen
                    char_count += len(w) + 1
                else:
                    break
            if len(resumen) >= 20:
                break

    # Trim espacios redundantes
    resumen = re.sub(r"\s+", " ", resumen).strip()

    if not resumen:
        if fallback_hu:
            return truncate(fallback_hu, 60)
        if fallback_historia:
            return truncate(fallback_historia, 60)
        return "Sin descripción"

    return resumen[:60]


# ============================================================================
# LOOKUPS — Tablas relacionadas
# ============================================================================
def lookup_estado_inicial(db) -> int:
    """Devuelve el id del estado inicial del sistema (es_inicial=True)."""
    row = db.execute(text(
        "SELECT id FROM estados WHERE es_inicial = true ORDER BY orden LIMIT 1"
    )).first()
    if row:
        return row[0]
    # Fallback: el primer estado creado
    row = db.execute(text("SELECT id FROM estados ORDER BY orden LIMIT 1")).first()
    if row:
        return row[0]
    raise RuntimeError("No hay estados creados. Ejecute el seed primero.")


def lookup_tablero_default(db) -> Optional[int]:
    """Devuelve el id del primer tablero disponible."""
    row = db.execute(text(
        "SELECT id FROM tableros WHERE archivado = false ORDER BY id LIMIT 1"
    )).first()
    return row[0] if row else None


def codigo_exists(db, codigo: str) -> bool:
    row = db.execute(text("SELECT 1 FROM tickets WHERE codigo = :c"), {"c": codigo}).first()
    return row is not None


# ============================================================================
# MAPEO PREFIJO → HEADER REAL (los headers del Excel están en español con tildes)
# ============================================================================
HEADER_MAP = {
    "A_modulo":        "Módulo",
    "B_hoja_origen":   "Hoja Origen",
    "C_codigo_hu":     "Código HU",
    "D_prioridad":     "Prioridad",
    "E_historia_usu":  "Historia de Usuario",
    "F_vista":         "Vista",
    "G_actores":       "Actores",
    "H_codigo_caso":   "Código Caso Prueba",
    "I_caso_prueba":   "Caso de Prueba (Texto)",
    "J_caso_nuevo":    "Caso Nuevo?",
    "K_fecha_prueba":  "Fecha Prueba",
    "L_resultado":     "Resultado",
    "M_categoria":     "Categoría",
    "N_criticidad":    "Criticidad",
    "O_detalle_inc":   "Detalle Incidente",
    "P_evidencia":     "Evidencia?",
    "Q_resultado_h":   "Resultado Histórico",
    "R_fecha_entrega": "Fecha Entrega",
    "S_observaciones": "Observaciones",
}


def H(row: Dict[str, Any], key: str) -> Any:
    """Helper: devuelve el valor de la columna usando el prefijo A_/B_/..."""
    return row.get(HEADER_MAP[key])


# ============================================================================
# TRANSFORMACIÓN — 19 columnas → 30 destino
# ============================================================================
def descripcion_markdown(row: Dict[str, Any]) -> str:
    """Genera la descripción en markdown con los 19 campos etiquetados."""
    etiquetas = [
        ("Módulo",             H(row, "A_modulo")),
        ("Hoja Origen",        H(row, "B_hoja_origen")),
        ("Código HU",          H(row, "C_codigo_hu")),
        ("Prioridad",          H(row, "D_prioridad")),
        ("Historia de Usuario",H(row, "E_historia_usu")),
        ("Vista",              H(row, "F_vista")),
        ("Actores",            H(row, "G_actores")),
        ("Código Caso Prueba", H(row, "H_codigo_caso")),
        ("Caso de Prueba (Texto)", H(row, "I_caso_prueba")),
        ("Caso Nuevo?",        H(row, "J_caso_nuevo")),
        ("Fecha Prueba",       H(row, "K_fecha_prueba")),
        ("Resultado",          H(row, "L_resultado")),
        ("Categoría",          H(row, "M_categoria")),
        ("Criticidad",         H(row, "N_criticidad")),
        ("Detalle Incidente",  H(row, "O_detalle_inc")),
        ("Evidencia?",         H(row, "P_evidencia")),
        ("Resultado Histórico",H(row, "Q_resultado_h")),
        ("Fecha Entrega",      H(row, "R_fecha_entrega")),
        ("Observaciones",      H(row, "S_observaciones")),
    ]
    lines = ["## Datos de origen UAT", ""]
    for label, value in etiquetas:
        v = "" if value is None else str(value).strip()
        if v:
            lines.append(f"- **{label}:** {v}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_Importado desde hoja `{HOJA}` el {datetime.now(timezone.utc).isoformat()}_")
    return "\n".join(lines)


def transformar_fila(idx: int, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve un dict listo para insertar en `tickets` (sin FK lookups)."""
    h_codigo = truncate(H(raw, "H_codigo_caso"), 12)
    correlativo = f"{idx:03d}"
    codigo = f"GAR_{h_codigo}-{correlativo}" if h_codigo else f"GAR_SIN-{idx:05d}"
    codigo = codigo[:20]

    resumen = resumen_semantico(
        H(raw, "I_caso_prueba"),
        fallback_hu=truncate(H(raw, "C_codigo_hu"), 60) or "",
        fallback_historia=truncate(H(raw, "E_historia_usu"), 60) or "",
    )
    titulo = truncate(f"{h_codigo} - {resumen}", 200)

    resultado_norm = normalize_resultado(H(raw, "L_resultado"))
    fecha_prueba = to_date(H(raw, "K_fecha_prueba"))
    fecha_entrega = to_date(H(raw, "R_fecha_entrega"))

    es_ok = (resultado_norm == "OK")
    fecha_completado = fecha_entrega if es_ok and fecha_entrega else None
    fecha_vencimiento_sla = fecha_entrega if es_ok and fecha_entrega else None
    fecha_cumplida = bool(es_ok and fecha_entrega)

    nota_observ = truncate(H(raw, "O_detalle_inc"), 5000) or truncate(H(raw, "S_observaciones"), 5000)

    datos_catalogo = {
        "Hoja Origen":           truncate(H(raw, "B_hoja_origen"), 200),
        "Codigo HU":             truncate(H(raw, "C_codigo_hu"), 80),
        "Historia de Usuario":   truncate(H(raw, "E_historia_usu"), 1000),
        "Actores":               truncate(H(raw, "G_actores"), 200),
        "Caso de Prueba (Texto)":truncate(H(raw, "I_caso_prueba"), 5000),
        "Caso Nuevo?":           to_bool(H(raw, "J_caso_nuevo")),
        "Categoria":             truncate(H(raw, "M_categoria"), 40),
        "Criticidad":            truncate(H(raw, "N_criticidad"), 40),
        "Detalle Incidente":     truncate(H(raw, "O_detalle_inc"), 5000),
        "Evidencia?":            to_bool(H(raw, "P_evidencia")),
        "Resultado Historico":   truncate(H(raw, "Q_resultado_h"), 500),
        "Observaciones":         truncate(H(raw, "S_observaciones"), 5000),
    }
    datos_catalogo = {k: v for k, v in datos_catalogo.items() if v not in (None, "")}

    return {
        "codigo": codigo,
        "titulo": titulo,
        "descripcion": descripcion_markdown(raw),
        "tipo": "incidencia",
        "prioridad": "media",
        "estado_id": None,                 # Resuelto por lookup
        "creador_id": 1,                   # admin
        "asignado_id": None,
        "catalogo_tipo_id": None,
        "tablero_id": None,                # Resuelto por lookup
        "datos_catalogo": datos_catalogo,
        "fecha_vencimiento_sla": fecha_vencimiento_sla,
        "sla_cumplido": 1,
        "fecha_inicio": None,
        "fecha_completado": fecha_completado,
        "fecha_cumplida": fecha_cumplida,
        "portada_color": portada_color_from_prioridad(H(raw, "D_prioridad")),
        "portada_adjunto_id": None,
        "descripcion_md": True,
        "posicion": idx,
        "archivado": False,
        "modulo": truncate(H(raw, "A_modulo"), 80),
        "ambiente": "QA",
        "item": "Portal WEB APEX",
        "vista": truncate(H(raw, "F_vista"), 200),
        "hu_o_caso_prueba": truncate(H(raw, "H_codigo_caso"), 200),
        "nota_observacion": nota_observ,
        "resultado_pruebas": resultado_norm,
        "created_at": fecha_prueba or datetime.now(timezone.utc),
        "updated_at": fecha_prueba or datetime.now(timezone.utc),
    }


# ============================================================================
# DRIVER PRINCIPAL
# ============================================================================
def leer_excel(path: Path) -> List[Dict[str, Any]]:
    """Lee la hoja CONSOLIDADO UAT y devuelve lista de dicts crudos."""
    log.info("Abriendo Excel: %s", path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[HOJA]
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = list(row)
            continue
        if all(c is None or c == "" for c in row):
            continue  # Saltar filas vacías
        rec = dict(zip(headers, row))
        rows.append(rec)
    log.info("Filas leídas: %d (encabezados=%d)", len(rows), len(headers))
    return rows


def validar_fila_cruda(idx: int, raw: Dict[str, Any]) -> List[str]:
    """Devuelve lista de warnings/errores."""
    warnings = []
    if not H(raw, "A_modulo"):
        warnings.append(f"fila#{idx}: Módulo vacío")
    if not H(raw, "H_codigo_caso"):
        warnings.append(f"fila#{idx}: Código Caso Prueba vacío")
    if not H(raw, "E_historia_usu"):
        warnings.append(f"fila#{idx}: Historia de Usuario vacía")
    return warnings


def connect_db(url: Optional[str] = None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL no definida")
        return None, None
    engine = create_engine(url, pool_pre_ping=True, future=True)
    Session = sessionmaker(bind=engine, future=True)
    return engine, Session


def dry_run_report(transformed: List[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
    """Genera un reporte de validación sin escribir."""
    por_modulo: Dict[str, Dict[str, int]] = {}
    por_resultado: Dict[str, int] = {
        "OK": 0, "NOK": 0, "N/A": 0, "OK CON OBS.": 0,
        "POSTERGADA": 0, "DESESTIMADA": 0, "(en blanco)": 0,
    }
    codigos_vistos = set()
    codigos_duplicados = []
    for t in transformed:
        m = t.get("modulo") or "(en blanco)"
        r = t.get("resultado_pruebas") or "(en blanco)"
        por_modulo.setdefault(m, {k: 0 for k in por_resultado})[r] += 1
        por_resultado[r] = por_resultado.get(r, 0) + 1
        if t["codigo"] in codigos_vistos:
            codigos_duplicados.append(t["codigo"])
        codigos_vistos.add(t["codigo"])

    log.info("=" * 70)
    log.info("REPORTE DRY-RUN")
    log.info("=" * 70)
    log.info("Total de filas transformadas: %d", len(transformed))
    log.info("Warnings: %d", len(warnings))
    log.info("Códigos duplicados: %d", len(codigos_duplicados))
    log.info("")
    log.info("Por resultado (total):")
    for k, v in por_resultado.items():
        log.info("  %-15s = %d", k, v)
    log.info("")
    log.info("Por módulo:")
    for m, cnt in sorted(por_modulo.items()):
        total = sum(cnt.values())
        log.info("  %-30s total=%d   %s", m, total, cnt)

    return {
        "total_filas": len(transformed),
        "warnings": len(warnings),
        "warnings_detalle": warnings[:20],
        "codigos_duplicados": codigos_duplicados[:10],
        "por_resultado": por_resultado,
        "por_modulo": por_modulo,
    }


def ejecutar_insercion(transformed: List[Dict[str, Any]],
                        engine,
                        batch_size: int = 100) -> int:
    """Inserta los registros en bloques. Devuelve cantidad insertada."""
    inserted = 0
    with engine.begin() as conn:
        for i in range(0, len(transformed), batch_size):
            batch = transformed[i:i+batch_size]
            for t in batch:
                cols = list(t.keys())
                placeholders = ", ".join([f":{c}" for c in cols])
                col_list = ", ".join(cols)
                sql = (
                    f"INSERT INTO tickets ({col_list}) VALUES ({placeholders}) "
                    f"ON CONFLICT (codigo) DO NOTHING"
                )
                conn.execute(text(sql), t)
                inserted += 1
            log.info("Insertados %d/%d", min(i+batch_size, len(transformed)), len(transformed))
    return inserted


def main():
    parser = argparse.ArgumentParser(description="ETL UAT → tickets")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Solo validar (default: True).")
    parser.add_argument("--force", action="store_true",
                        help="Forzar inserción real (requiere --no-dry-run).")
    parser.add_argument("--target", choices=["local", "railway", "sqlite"], default="railway",
                        help="Destino de la conexión.")
    parser.add_argument("--limit", type=int, default=0, help="Limitar N filas (0=todas).")
    parser.add_argument("--excel", type=str, default=str(EXCEL_PATH),
                        help="Ruta al Excel.")
    args = parser.parse_args()

    if args.force:
        args.dry_run = False

    log.info("=" * 70)
    log.info("UAT ETL — Bitácora GRM v2")
    log.info("Excel:    %s", args.excel)
    log.info("Hoja:     %s", HOJA)
    log.info("Destino:  %s", args.target)
    log.info("Dry-run:  %s", args.dry_run)
    log.info("Límite:   %s", args.limit or "sin límite")
    log.info("Log file: %s", LOG_FILE)
    log.info("=" * 70)

    # 1) Leer Excel
    rows = leer_excel(Path(args.excel))
    if args.limit:
        rows = rows[:args.limit]

    # 2) Validar filas crudas
    all_warnings: List[str] = []
    for idx, raw in enumerate(rows, start=2):  # start=2 porque fila 1 = encabezados
        all_warnings.extend(validar_fila_cruda(idx, raw))
    if all_warnings:
        log.warning("Warnings de validación (%d):", len(all_warnings))
        for w in all_warnings[:30]:
            log.warning("  - %s", w)

    # 3) Transformar
    log.info("Transformando %d filas...", len(rows))
    transformed: List[Dict[str, Any]] = []
    for idx, raw in enumerate(rows, start=1):
        try:
            t = transformar_fila(idx, raw)
            transformed.append(t)
        except Exception as e:
            log.exception("Error transformando fila idx=%d: %s", idx, e)

    # 4) Resolver FKs (estado_id, tablero_id) — solo si vamos a escribir
    if not args.dry_run:
        engine, Session = connect_db()
        if engine is None:
            log.error("No se pudo conectar a la BD; abortando.")
            return 1
        with Session() as s:
            estado_id = lookup_estado_inicial(s)
            tablero_id = lookup_tablero_default(s)
        log.info("estado_id = %s   tablero_id = %s", estado_id, tablero_id)
        for t in transformed:
            t["estado_id"] = estado_id
            t["tablero_id"] = tablero_id
    else:
        engine = None

    # 5) Reporte dry-run
    report = dry_run_report(transformed, all_warnings)
    report_path = LOGS_DIR / f"uat_dryrun_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
    log.info("Reporte dry-run guardado en: %s", report_path)

    # 6) Inserción real
    if not args.dry_run:
        if not args.force:
            log.error("Para escribir en BD use --force")
            return 1
        log.warning("=" * 70)
        log.warning("INSERTANDO EN PRODUCCIÓN.  Este cambio NO es reversible.")
        log.warning("=" * 70)
        n = ejecutar_insercion(transformed, engine)
        log.info("Total insertados: %d", n)
        return 0

    log.info("Dry-run completado. No se escribió nada en la BD.")
    log.info("Para ejecutar la carga real use:")
    log.info("    python tools/load_uat_consolidado.py --no-dry-run --force")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
