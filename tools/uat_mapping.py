"""
================================================================================
MAPEO DE TRANSFORMACIÓN: Consolidado UAT → tabla `tickets` (31 cols)
================================================================================
Archivo origen:  Consolidado_UAT_Cruce_GARANTIA_v3.xlsx
Hoja origen:     CONSOLIDADO UAT  (913 filas × 19 columnas)
Hoja verdad:     REPORTE  rango A64:H81  (Tabla Pivote "Cuenta de Resultado")
Tabla destino:   tickets  (PostgreSQL via SQLAlchemy, 31 columnas)
Estrategia:      ETL Python con openpyxl + sqlalchemy
Modo por defecto: dry_run=True (NO escribe hasta confirmar)
================================================================================
"""

# ============================================================================
# 1. MAPEO COLUMNA → COLUMNA (19 origen → 30 destino, 1 autonum)
# ============================================================================
MAPEO = {
    # # = columna origen (letra Excel)
    # ORIGEN                            DESTINO                       TRANSFORMACIÓN
    "A_modulo":        ("modulo",          "str80(Módulo).strip()[:80]"),
    "B_hoja_origen":   ("datos_catalogo",  "json['Hoja Origen'] = str.strip()"),
    "C_codigo_hu":     ("datos_catalogo",  "json['Codigo HU'] = str.strip()"),
    "D_prioridad":     ("portada_color",   "ALTA→#FF0000 | MEDIA→#FFA500 | BAJA→#008000 | ''→#94a3b8"),
    "E_historia_usu":  ("datos_catalogo",  "json['Historia de Usuario'] = str.strip()"),
    "F_vista":         ("vista",           "str200(F).strip()[:200]"),
    "G_actores":       ("datos_catalogo",  "json['Actores'] = str.strip()"),
    "H_codigo_caso":   ("codigo",          "prefijo='GAR_' + codigo_caso[:12] + '-' + correlativo(3d); len<=20"),
    "H_codigo_caso":   ("hu_o_caso_prueba","H.strip()[:200]"),
    "I_caso_prueba":   ("titulo",          "CONCAT(H, ' - ', [RESUMEN_semantico(I)])[:200]"),
    "I_caso_prueba":   ("datos_catalogo",  "json['Caso de Prueba (Texto)'] = str.strip()"),
    "J_caso_nuevo":    ("datos_catalogo",  "json['Caso Nuevo?'] = bool(Si/Yes)"),
    "K_fecha_prueba":  ("created_at",      "datetime(K) or now()"),
    "K_fecha_prueba":  ("updated_at",      "datetime(K) or now()"),
    "L_resultado":     ("resultado_pruebas","normalize(L): 'POSTERGADA A GARANTIA'→'POSTERGADA' | 'N/A'|'OK'|'NOK'|'OK CON OBS.'|'DESESTIMADA'"),
    "M_categoria":     ("datos_catalogo",  "json['Categoria'] = str.strip()"),
    "N_criticidad":    ("datos_catalogo",  "json['Criticidad'] = str.strip()"),
    "O_detalle_inc":   ("datos_catalogo",  "json['Detalle Incidente'] = str.strip()"),
    "O_detalle_inc":   ("nota_observacion","O.strip() si no vacío"),
    "P_evidencia":     ("datos_catalogo",  "json['Evidencia?'] = bool(Si)"),
    "Q_resultado_h":   ("datos_catalogo",  "json['Resultado Historico'] = str.strip()"),
    "R_fecha_entrega": ("fecha_completado", "datetime(R) si L=OK else None"),
    "R_fecha_entrega": ("fecha_vencimiento_sla", "datetime(R) si L=OK and R else None"),
    "R_fecha_entrega": ("fecha_cumplida",   "True si L=OK and R else False"),
    "S_observaciones": ("nota_observacion", "S.strip() si O está vacío"),
    # Columnas FIJAS (no vienen del Excel)
    "_tipo":           ("tipo",            "TipoIncidencia.INCIDENCIA (default)"),
    "_prioridad":      ("prioridad",       "Prioridad.MEDIA (default)"),
    "_estado_id":      ("estado_id",       "estado_inicial_id()  (lookup o seed)"),
    "_creador_id":     ("creador_id",      "1 (usuario 'admin' / migrador UAT)"),
    "_asignado_id":    ("asignado_id",     "NULL"),
    "_catalogo_tipo_id":("catalogo_tipo_id","NULL"),
    "_tablero_id":     ("tablero_id",      "tablero_default_id()  (lookup o seed)"),
    "_sla_cumplido":   ("sla_cumplido",    "1 si L=OK else 1 (default)"),
    "_portada_adjunto_id":("portada_adjunto_id","NULL"),
    "_descripcion_md": ("descripcion_md",  "True (descripción usa markdown/etiquetas)"),
    "_posicion":       ("posicion",        "ROW_NUMBER() por hoja"),
    "_archivado":      ("archivado",       "False"),
    "_ambiente":       ("ambiente",        "'QA' (fijo por spec)"),
    "_item":           ("item",            "'Portal WEB APEX' (fijo por spec)"),
    "_descripcion":    ("descripcion",     "markdown con los 19 campos etiquetados"),
}


# ============================================================================
# 2. RESUMEN SEMÁNTICO  (no truncado mecánico)
# ============================================================================
"""
Estrategia para generar [RESUMEN]:
 1. Leer texto COMPLETO de "Caso de Prueba (Texto)" (col I)
 2. Eliminar prefijos irrelevantes: "Realizar prueba...", "Verificar que...",
    "Se debe comprobar que...", "Dentro de la pestaña ..."
 3. Mantener el sujeto principal (sustantivo + verbo)
 4. Eliminar palabras vacías (el, la, de, del, al, en, y, o, a)
 5. Comprimir a ~50 caracteres (máx 60)
 6. Si el texto queda < 15 chars o vacío → fallback a:
       6a. Código HU  (col C)
       6b. Historia de Usuario  (col E)
       6c. "[Sin descripción]" (último recurso)

 Implementación: tools/load_uat_consolidado.py::resumen_semantico()
"""


# ============================================================================
# 3. VALIDACIÓN DE TIPOS OBLIGATORIA (pre-carga)
# ============================================================================
VALIDACIONES = {
    "A_modulo":           {"tipo": "str", "min_len": 1, "max_len": 80,  "lovs": [
        "Control ERM", "Gobierno", "Incidencias", "Validación", "Auditoria",
        "Filiales", "Información Inventario", "Registro de Información",
        "Registro Información", "Documentación", "Mejoras Transversales",
        "Seguimiento y Control", "(en blanco)", None
    ]},
    "B_hoja_origen":      {"tipo": "str|None", "max_len": 80},
    "C_codigo_hu":        {"tipo": "str|None", "max_len": 80},
    "D_prioridad":        {"tipo": "str|None", "lovs": ["ALTA", "MEDIA", "BAJA", "Alta", "Media", "Baja", None]},
    "E_historia_usu":     {"tipo": "str", "min_len": 1, "max_len": 1000},
    "F_vista":            {"tipo": "str|None", "max_len": 200},
    "G_actores":          {"tipo": "str|None", "max_len": 200},
    "H_codigo_caso":      {"tipo": "str", "min_len": 1, "max_len": 12, "unique_en_caso": True},
    "I_caso_prueba":      {"tipo": "str|None", "max_len": 5000},
    "J_caso_nuevo":       {"tipo": "bool|None", "valores": ["Si", "Sí", "Yes", "No", None, ""]},
    "K_fecha_prueba":     {"tipo": "date|None", "iso8601": True},
    "L_resultado":        {"tipo": "str|None", "lovs": [
        "OK", "NOK", "N/A", "OK CON OBS.", "POSTERGADA A GARANTÍA",
        "POSTERGADA", "BLOQUEADO PARA EJECUTAR", "DESESTIMADA", None, ""
    ]},
    "M_categoria":        {"tipo": "str|None", "max_len": 40},
    "N_criticidad":       {"tipo": "str|None", "max_len": 40},
    "O_detalle_inc":      {"tipo": "str|None", "max_len": 5000},
    "P_evidencia":        {"tipo": "bool|None", "valores": ["Si", "Sí", "Yes", None, ""]},
    "Q_resultado_h":      {"tipo": "str|None", "max_len": 500},
    "R_fecha_entrega":    {"tipo": "date|None", "iso8601": True},
    "S_observaciones":    {"tipo": "str|None", "max_len": 5000},
}


# ============================================================================
# 4. REGLAS DE NEGOCIO  (producción OK → Bitácora GRM)
# ============================================================================
"""
La columna "produccion ok" de la Bitácora GRM se calcula:

    produccion_ok = (resultado_pruebas == 'OK')

Es decir, basta poblar `resultado_pruebas` correctamente para que el campo
derivado funcione.

Reglas de normalización de `resultado_pruebas`:
   "POSTERGADA A GARANTÍA"   → "POSTERGADA"
   "OK CON OBS."            → "OK CON OBS."   (sin cambios)
   "BLOQUEADO PARA EJECUTAR"→ "DESESTIMADA"   (≈ mismo significado operativo)
   "OK" / "NOK" / "N/A"     → sin cambios
   "" o None                → None

`produccion_ok` se almacena implícitamente en `fecha_cumplida` y
`fecha_completado` cuando `resultado_pruebas == 'OK'` y `Fecha Entrega`
está presente.
"""


# ============================================================================
# 5. CARDINALIDADES Y TOTALES ESPERADOS
# ============================================================================
TOTALES_ESPERADOS = {
    "total_general":     877,
    "por_columna": {
        "N/A":       130,
        "NOK":        10,
        "OK":        635,
        "OK CON OBS.": 18,
        "POSTERGADA": 84,
        "(en blanco)":  0,
    },
    "por_modulo": {
        "Auditoria":              (1, 0,   8,  0, 0, 0),  # 9
        "Control ERM":            (3, 0,  49,  0, 0, 0),  # 52
        "Documentación":          (6, 0,  25,  1, 0, 0),  # 32
        "Filiales":               (3, 0,  17,  3, 0, 0),  # 23
        "Gobierno":               (21,0,  26,  1, 0, 0),  # 48
        "Incidencias":            (8, 0,  28,  2, 0, 0),  # 38
        "Información Inventario": (16,0,  36,  2, 0, 0),  # 54
        "Mejoras Transversales":  (33,4,  38,  0,43, 0),  # 118
        "Registro Información":   (6, 0, 155,  0,27, 0),  # 188
        "Seguimiento y Control":  (5, 6, 109,  7,14, 0),  # 141
        "Validación":             (28,0, 144,  2, 0, 0),  # 174
    },
}
# Cada tupla: (N/A, NOK, OK, OK_CON_OBS, POSTERGADA, EN_BLANCO)


# ============================================================================
# 6. ORDEN EXACTO DE COLUMNAS PARA EL CSV DE AUDITORÍA (post-carga)
# ============================================================================
ORDEN_IMPORT = [
    # (orden, columna_destino,           fuente)
    ( 1, "codigo",                     "H_codigo_caso + correlativo"),
    ( 2, "titulo",                     "I_caso_prueba (resumen semantico)"),
    ( 3, "descripcion",                "concat 19 cols etiquetadas"),
    ( 4, "tipo",                       "TipoIncidencia.INCIDENCIA"),
    ( 5, "prioridad",                  "Prioridad.MEDIA"),
    ( 6, "estado_id",                  "estado_inicial (lookup)"),
    ( 7, "creador_id",                 "1"),
    ( 8, "asignado_id",                "NULL"),
    ( 9, "catalogo_tipo_id",           "NULL"),
    (10, "tablero_id",                 "tablero_default (lookup)"),
    (11, "datos_catalogo",             "JSON {19 campos originales}"),
    (12, "fecha_vencimiento_sla",      "R_fecha_entrega si OK"),
    (13, "sla_cumplido",               "1"),
    (14, "fecha_inicio",               "NOW()"),
    (15, "fecha_completado",           "R_fecha_entrega si OK"),
    (16, "fecha_cumplida",             "True si OK+R"),
    (17, "portada_color",              "D_prioridad → HEX"),
    (18, "portada_adjunto_id",         "NULL"),
    (19, "descripcion_md",             "True"),
    (20, "posicion",                   "ROW_NUMBER()"),
    (21, "archivado",                  "False"),
    (22, "modulo",                     "A_modulo"),
    (23, "ambiente",                   "'QA'"),
    (24, "item",                       "'Portal WEB APEX'"),
    (25, "vista",                      "F_vista"),
    (26, "hu_o_caso_prueba",           "H_codigo_caso"),
    (27, "nota_observacion",           "O_detalle + S_observaciones"),
    (28, "resultado_pruebas",          "L_resultado (normalizado)"),
    (29, "created_at",                 "K_fecha_prueba o NOW()"),
    (30, "updated_at",                 "K_fecha_prueba o NOW()"),
]
