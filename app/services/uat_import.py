"""
================================================================================
Servicio de Importación UAT → Bitácora GRM
================================================================================
Carga masiva del archivo "Consolidado_UAT_Cruce_GARANTIA_v3.xlsx" (hoja
"CONSOLIDADO UAT") hacia la tabla `tickets`.

Reutilizable desde:
  - CLI  (tools/load_uat_consolidado.py)
  - Endpoint HTTP admin (app/api/v1/admin_uat.py)
  - Tareas de Celery (futuro)

Decisiones de diseño:
  - Los nombres de funciones de transformación son puros (sin estado) ⇒
    testeables y serializables.
  - La lectura del Excel opera sobre bytes (no sobre path) para
    soportar archivos subidos vía multipart/form-data.
  - La orquestación (lectura + transformación + FK lookups + INSERT)
    se hace sobre un `Session` existente, por lo que el caller decide
    si la sesión es transaccional o read-only.
  - ON CONFLICT (codigo) DO NOTHING ⇒ idempotente: re-ejecuciones
    seguras.
================================================================================
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import openpyxl
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("uat_import")

HOJA = "CONSOLIDADO UAT"

# ============================================================================
# HEADER MAP (prefijo → header real del Excel con tildes)
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
    """Helper que devuelve el valor de una columna usando el prefijo A_/B_/..."""
    return row.get(HEADER_MAP[key])


# ============================================================================
# HELPERS — Tipos y normalización
# ============================================================================
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def to_bool(v: Any) -> Optional[bool]:
    """Si/Yes/No/False → True/False; vacío → None."""
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
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
    try:
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


def resumen_semantico(
    texto: str, fallback_hu: str = "", fallback_historia: str = ""
) -> str:
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

    t = texto.replace("\n", " ").replace("\r", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r'^[\"\'\u201c\u201d]', "", t)
    t = re.sub(r'[\"\'\u201c\u201d]$', "", t)

    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", t)

    out: List[str] = []
    char_count = 0
    for w in words:
        wl = w.lower()
        if wl in STOPWORDS and len(out) > 0:
            continue
        new_len = char_count + len(w) + (1 if out else 0)
        if new_len > 60:
            break
        out.append(w)
        char_count = new_len

    resumen = " ".join(out)

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
def lookup_estado_inicial(db: Session) -> int:
    """Devuelve el id del estado inicial del sistema (es_inicial=True)."""
    row = db.execute(text(
        "SELECT id FROM estados WHERE es_inicial = true ORDER BY orden LIMIT 1"
    )).first()
    if row:
        return row[0]
    row = db.execute(text("SELECT id FROM estados ORDER BY orden LIMIT 1")).first()
    if row:
        return row[0]
    raise RuntimeError("No hay estados creados. Ejecute el seed primero.")


def lookup_tablero_default(db: Session) -> Optional[int]:
    """Devuelve el id del primer tablero disponible."""
    row = db.execute(text(
        "SELECT id FROM tableros WHERE archivado = false ORDER BY id LIMIT 1"
    )).first()
    return row[0] if row else None


# ============================================================================
# MAPPING resultado_pruebas → estado (Tablero Incidencias de Producción)
# ============================================================================
# Reglas de negocio Bitácora GRM:
#   N/A          → Cancelado
#   OK           → produccion ok
#   OK CON OBS.  → APROBADO QA
#   POSTERGADA   → BackLog
#   NOK          → Analisis/Bloqueado
#   (en blanco)  → BackLog   (default = estado inicial)
RESULTADO_A_ESTADO_NOMBRE = {
    "N/A":         "Cancelado",
    "OK":          "produccion ok",
    "OK CON OBS.": "APROBADO QA",
    "POSTERGADA":  "BackLog",
    "NOK":         "Analisis/Bloqueado",
}


def lookup_estado_id_por_resultado(db: Session, resultado: Optional[str]) -> int:
    """Devuelve el ``estado_id`` apropiado para un valor de ``resultado_pruebas``.

    Si el resultado no está en el mapping o la BD no tiene el estado,
    devuelve el estado inicial del sistema (BackLog).
    """
    if resultado:
        nombre_estado = RESULTADO_A_ESTADO_NOMBRE.get(resultado.strip())
        if nombre_estado:
            row = db.execute(text(
                "SELECT id FROM estados WHERE nombre = :n LIMIT 1"
            ), {"n": nombre_estado}).first()
            if row:
                return row[0]
    return lookup_estado_inicial(db)


# ============================================================================
# DESCRIPCIÓN MARKDOWN
# ============================================================================
def descripcion_markdown(row: Dict[str, Any]) -> str:
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
    lines.append(
        f"_Importado desde hoja `{HOJA}` el "
        f"{datetime.now(timezone.utc).isoformat()}_"
    )
    return "\n".join(lines)


# ============================================================================
# TRANSFORMACIÓN — 19 columnas → 30 destino
# ============================================================================
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

    nota_observ = (
        truncate(H(raw, "O_detalle_inc"), 5000)
        or truncate(H(raw, "S_observaciones"), 5000)
    )

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
        "tipo": "INCIDENCIA",
        "prioridad": "MEDIA",
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
# LECTURA DEL EXCEL
# ============================================================================
def leer_excel_desde_bytes(excel_bytes: bytes) -> List[Dict[str, Any]]:
    """Lee la hoja CONSOLIDADO UAT desde bytes y devuelve lista de dicts crudos."""
    wb = openpyxl.load_workbook(
        filename=io.BytesIO(excel_bytes), data_only=True, read_only=True
    )
    ws = wb[HOJA]
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = list(row)
            continue
        if all(c is None or c == "" for c in row):
            continue
        rec = dict(zip(headers, row))
        rows.append(rec)
    log.info("Filas leídas: %d (encabezados=%d)", len(rows), len(headers))
    return rows


def validar_fila_cruda(idx: int, raw: Dict[str, Any]) -> List[str]:
    warnings = []
    if not H(raw, "A_modulo"):
        warnings.append(f"fila#{idx}: Módulo vacío")
    if not H(raw, "H_codigo_caso"):
        warnings.append(f"fila#{idx}: Código Caso Prueba vacío")
    if not H(raw, "E_historia_usu"):
        warnings.append(f"fila#{idx}: Historia de Usuario vacía")
    return warnings


# ============================================================================
# INSERCIÓN
# ============================================================================
def ejecutar_insercion(
    db: Session,
    transformed: List[Dict[str, Any]],
    batch_size: int = 100,
) -> Dict[str, Any]:
    """Inserta los registros en bloques usando ON CONFLICT DO NOTHING.

    Devuelve un dict con:
      - inserted   : cantidad de filas que se INTENTARON insertar
      - inserted_confirmed : diferencia antes/después (filas realmente nuevas)
      - by_resultado: conteo por resultado_pruebas (de los transformados)
      - by_modulo:     conteo por módulo (de los transformados)
    """
    # Resolver FKs (tablero + estado por mapping resultado_pruebas → estado)
    tablero_id = lookup_tablero_default(db)
    for t in transformed:
        t["tablero_id"] = tablero_id
        # Mapear resultado_pruebas al estado correcto del Tablero Incidencias
        t["estado_id"] = lookup_estado_id_por_resultado(db, t.get("resultado_pruebas"))

    # Snapshot antes de insertar para medir confirmaciones reales
    pre_total = db.execute(text("SELECT count(*) FROM tickets")).scalar() or 0

    by_resultado: Dict[str, int] = {}
    by_modulo: Dict[str, int] = {}
    for t in transformed:
        r = t.get("resultado_pruebas") or "(en blanco)"
        m = t.get("modulo") or "(en blanco)"
        by_resultado[r] = by_resultado.get(r, 0) + 1
        by_modulo[m] = by_modulo.get(m, 0) + 1

    inserted_attempts = 0
    try:
        for i in range(0, len(transformed), batch_size):
            batch = transformed[i:i + batch_size]
            for t in batch:
                # Serializar campos JSON/dict que psycopg2 no puede adaptar
                # directamente. datos_catalogo es JSONB.
                params = dict(t)
                if isinstance(params.get("datos_catalogo"), dict):
                    params["datos_catalogo"] = json.dumps(
                        params["datos_catalogo"], ensure_ascii=False, default=str
                    )

                cols = list(params.keys())
                placeholders = ", ".join([f":{c}" for c in cols])
                col_list = ", ".join(cols)
                sql = (
                    f"INSERT INTO tickets ({col_list}) VALUES ({placeholders}) "
                    f"ON CONFLICT (codigo) DO NOTHING"
                )
                db.execute(text(sql), params)
                inserted_attempts += 1
            log.info(
                "Insertados %d/%d",
                min(i + batch_size, len(transformed)),
                len(transformed),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    post_total = db.execute(text("SELECT count(*) FROM tickets")).scalar() or 0
    return {
        "inserted_attempts": inserted_attempts,
        "inserted_confirmed": max(0, post_total - pre_total),
        "pre_total": pre_total,
        "post_total": post_total,
        "by_resultado": by_resultado,
        "by_modulo": by_modulo,
    }


# ============================================================================
# ORQUESTADOR DE ALTO NIVEL
# ============================================================================
def run_import(db: Session, excel_bytes: bytes, dry_run: bool = False) -> Dict[str, Any]:
    """Lee + transforma + (opcionalmente) inserta el Excel UAT.

    Idempotente: si un `codigo` ya existe, se ignora (ON CONFLICT DO NOTHING).

    Retorna un reporte detallado.
    """
    # 1) Leer
    raw_rows = leer_excel_desde_bytes(excel_bytes)

    # 2) Validar
    all_warnings: List[str] = []
    for idx, raw in enumerate(raw_rows, start=2):
        all_warnings.extend(validar_fila_cruda(idx, raw))

    # 3) Transformar
    transformed: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_rows, start=1):
        try:
            t = transformar_fila(idx, raw)
            transformed.append(t)
        except Exception as e:
            log.exception("Error transformando fila idx=%d: %s", idx, e)

    # 4) Reporte básico (siempre)
    report: Dict[str, Any] = {
        "mode": "dry_run" if dry_run else "execute",
        "rows_leidas": len(raw_rows),
        "rows_transformadas": len(transformed),
        "warnings": len(all_warnings),
        "warnings_detalle": all_warnings[:20],
    }

    # 5) Inserción real (solo si NO dry_run)
    if dry_run:
        # Aún así exponer la estadística que tendría la inserción
        report["stats_que_tendria_insercion"] = _stats_por_campo(transformed)
        return report

    insert_stats = ejecutar_insercion(db, transformed)
    report.update(insert_stats)
    return report


def _stats_por_campo(transformed: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    by_modulo: Dict[str, int] = {}
    by_resultado: Dict[str, int] = {}
    for t in transformed:
        m = t.get("modulo") or "(en blanco)"
        r = t.get("resultado_pruebas") or "(en blanco)"
        by_modulo[m] = by_modulo.get(m, 0) + 1
        by_resultado[r] = by_resultado.get(r, 0) + 1
    return {"by_modulo": by_modulo, "by_resultado": by_resultado}
