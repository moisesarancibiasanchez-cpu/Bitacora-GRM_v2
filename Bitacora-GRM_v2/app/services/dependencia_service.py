"""
TicketDependenciaService — Servicio de negocio para la FEATURE 3 (Gantt).

Encapsula la lógica CRUD y de validación de dependencias entre tickets:
- Crea dependencias (con detección de ciclos).
- Lista todas las dependencias de un set de tickets (para alimentar el Gantt).
- Elimina dependencias.
- Detecta ciclos en el grafo (BFS) ANTES de persistir, para evitar
  cadenas inválidas como A → B → C → A.

Este servicio está separado del ``TicketService`` porque la lógica de
dependencias es específica del Gantt y no participa en el flujo principal
de transiciones de estado.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.ticket_dependencia import TicketDependencia, TipoDependencia

logger = logging.getLogger(__name__)


class DependenciaError(Exception):
    """Errores de validación al crear/eliminar una dependencia."""

    def __init__(self, mensaje: str, codigo: str = "dependencia_invalida"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


class TicketDependenciaService:
    """Operaciones CRUD + validaciones para dependencias Gantt."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # CREAR
    # ------------------------------------------------------------------ #
    def crear(
        self,
        predecesor_id: int,
        sucesor_id: int,
        tipo: str = "fs",
        lag_dias: int = 0,
        nota: Optional[str] = None,
    ) -> TicketDependencia:
        """Crea una nueva dependencia entre dos tickets.

        Validaciones (en orden):
            1. Orientación básica (IDs distintos, positivos).
            2. Ambos tickets existen y NO están archivados.
            3. No se crea un ciclo en el grafo de dependencias.
            4. El tipo es uno de los permitidos (FS/SS/FF/SF).
            5. El ``lag_dias`` está dentro del rango permitido.

        Raises:
            DependenciaError: con ``codigo`` específico según el motivo.
        """
        # 1) Orientación
        motivo = TicketDependencia.validar_orientacion(predecesor_id, sucesor_id)
        if motivo:
            raise DependenciaError(motivo, codigo="orientacion_invalida")

        # 2) Tipo
        try:
            tipo_enum = TipoDependencia(tipo)
        except ValueError:
            raise DependenciaError(
                f"Tipo '{tipo}' no válido. Use uno de: fs, ss, ff, sf.",
                codigo="tipo_invalido",
            )

        # 3) Lag en rango
        if not (-365 <= int(lag_dias) <= 365):
            raise DependenciaError(
                "El lag debe estar entre -365 y 365 días.",
                codigo="lag_fuera_de_rango",
            )

        # 4) Existencia y estado de los tickets
        pred = self.db.query(Ticket).filter(Ticket.id == predecesor_id).first()
        if not pred or pred.archivado:
            raise DependenciaError(
                f"El ticket predecesor (id={predecesor_id}) no existe o está archivado.",
                codigo="predecesor_inexistente",
            )
        suc = self.db.query(Ticket).filter(Ticket.id == sucesor_id).first()
        if not suc or suc.archivado:
            raise DependenciaError(
                f"El ticket sucesor (id={sucesor_id}) no existe o está archivado.",
                codigo="sucesor_inexistente",
            )

        # 5) Detección de ciclos: si el sucesor (B) ya alcanza al
        #    predecesor (A) por alguna cadena existente (B → ... → A),
        #    entonces A → B cerraría un ciclo.
        if self._existe_camino(sucesor_id, predecesor_id):
            raise DependenciaError(
                f"Crear esta dependencia generaría un ciclo en el grafo "
                f"({sucesor.codigo} ya depende transitivamente de {pred.codigo}).",
                codigo="ciclo_detectado",
            )

        dep = TicketDependencia(
            predecesor_id=predecesor_id,
            sucesor_id=sucesor_id,
            tipo=tipo_enum,
            lag_dias=int(lag_dias),
            nota=(nota or None),
        )
        self.db.add(dep)
        try:
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            # Típicamente por el UniqueConstraint uq_dep_pred_suc_tipo
            if "uq_dep_pred_suc_tipo" in str(e.orig):
                raise DependenciaError(
                    "Ya existe esa misma dependencia entre los dos tickets.",
                    codigo="duplicado",
                )
            raise DependenciaError(
                f"Error de integridad al crear la dependencia: {e.orig}",
                codigo="integridad",
            )
        self.db.refresh(dep)
        return dep

    # ------------------------------------------------------------------ #
    # LEER
    # ------------------------------------------------------------------ #
    def listar_para_tickets(self, ticket_ids: List[int]) -> List[TicketDependencia]:
        """Devuelve TODAS las dependencias cuyo predecesor O sucesor esté
        en el set ``ticket_ids``. Útil para alimentar el Gantt."""
        if not ticket_ids:
            return []
        return (
            self.db.query(TicketDependencia)
            .filter(
                (TicketDependencia.predecesor_id.in_(ticket_ids))
                | (TicketDependencia.sucesor_id.in_(ticket_ids))
            )
            .all()
        )

    def obtener(self, dep_id: int) -> Optional[TicketDependencia]:
        return self.db.query(TicketDependencia).filter(
            TicketDependencia.id == dep_id
        ).first()

    # ------------------------------------------------------------------ #
    # ELIMINAR
    # ------------------------------------------------------------------ #
    def eliminar(self, dep_id: int) -> bool:
        """Elimina una dependencia por ID. Retorna True si se eliminó."""
        dep = self.obtener(dep_id)
        if not dep:
            return False
        self.db.delete(dep)
        self.db.commit()
        return True

    # ------------------------------------------------------------------ #
    # HELPERS
    # ------------------------------------------------------------------ #
    def _existe_camino(self, origen: int, destino: int) -> bool:
        """BFS: ¿Existe un camino ``origen`` → ``destino`` siguiendo
        aristas de la forma predecesor→sucesor?

        Usado para detección de ciclos. Como vamos a crear una arista
        ``pred → suc``, debemos asegurarnos de que NO exista ya un
        camino ``suc → pred`` (eso cerraría un ciclo).
        """
        if origen == destino:
            return True
        visitados: Set[int] = set()
        cola: deque[int] = deque([origen])
        # Pre-cargar adyacencias (predecesor → [sucesores])
        filas = self.db.query(
            TicketDependencia.predecesor_id, TicketDependencia.sucesor_id
        ).all()
        adyacencia: Dict[int, List[int]] = {}
        for p, s in filas:
            adyacencia.setdefault(p, []).append(s)

        while cola:
            nodo = cola.popleft()
            if nodo == destino:
                return True
            if nodo in visitados:
                continue
            visitados.add(nodo)
            for vecino in adyacencia.get(nodo, []):
                if vecino not in visitados:
                    cola.append(vecino)
        return False

    @staticmethod
    def validar_lag(lag: int) -> int:
        """Acota el lag al rango permitido."""
        return max(-365, min(365, int(lag)))


# ----------------------------------------------------------------------------
# Parser XML de Microsoft Project (.mpp exportado como XML)
# ----------------------------------------------------------------------------
class MSProjectXMLParser:
    """Parser tolerante para archivos XML exportados de MS Project.

    Lee la estructura estándar de MS Project XML (namespace
    ``http://schemas.microsoft.com/project``) y devuelve:

        - ``tareas``: lista de dicts con {uid, wbs, name, start, finish,
          duration_hours, is_summary, parent_uid, nivel_outline}.
        - ``links``:  lista de dicts con {predecesor_uid, sucesor_uid,
          tipo (fs/ss/ff/sf), lag_minutes, lag_dias}.
        - ``recursos``: lista de {uid, name}.
        - ``metadata``: {name, start_date, finish_date, currency}.

    No depende de paquetes externos (usa sólo ``xml.etree.ElementTree``
    de la stdlib) para mantener la app ligera y portable.

    Detalles del formato .mpp XML que asumimos:
        <Project>
          <Name>...</Name>
          <StartDate>YYYY-MM-DDTHH:MM:SS</StartDate>
          <FinishDate>...</FinishDate>
          <Tasks>
            <Task>
              <UID>1</UID>
              <Name>...</Name>
              <Start>...</Start>
              <Finish>...</Finish>
              <Duration>PT40H0M0S</Duration>  ← ISO 8601 duration
              <OutlineLevel>1</OutlineLevel>
              <PredecessorLink>
                <PredecessorUID>5</PredecessorUID>
                <SuccessorUID>6</SuccessorUID>
                <PredecessorType>0|1|2|3</PredecessorType>
                <LinkLag>0</LinkLag>  ← en décimas de minuto
              </PredecessorLink>
            </Task>
          </Tasks>
          <Resources>
            <Resource>
              <UID>1</UID>
              <Name>BCH</Name>
            </Resource>
          </Resources>
        </Project>
    """

    NS = "{http://schemas.microsoft.com/project}"

    # Mapeo PredecessorType → TipoDependencia
    # MS Project: 0=FF, 1=FS, 2=SF, 3=SS
    PRED_TYPE_MAP = {
        "0": TipoDependencia.FF,
        "1": TipoDependencia.FS,
        "2": TipoDependencia.SF,
        "3": TipoDependencia.SS,
    }

    def __init__(self, xml_bytes: bytes):
        self.xml_bytes = xml_bytes
        self._root = None

    def parsear(self) -> dict:
        """Parsea el XML y devuelve el dict con tareas, links y metadata."""
        import xml.etree.ElementTree as ET
        try:
            self._root = ET.fromstring(self.xml_bytes)
        except ET.ParseError as e:
            raise DependenciaError(
                f"XML inválido: {e}",
                codigo="xml_invalido",
            )
        return {
            "metadata": self._parse_metadata(),
            "tareas": self._parse_tareas(),
            "links": self._parse_links(),
            "recursos": self._parse_recursos(),
        }

    # ----- Secciones del XML ------------------------------------------------
    def _parse_metadata(self) -> dict:
        """Lee los metadatos del proyecto (Name, Start, Finish, etc.)."""
        meta = {}
        for campo in ("Name", "StartDate", "FinishDate", "Title", "Company"):
            el = self._root.find(f"{self.NS}{campo}")
            if el is not None and el.text:
                meta[campo.lower()] = el.text
        return meta

    # ---- Helpers para extraer códigos de HU/caso del nombre de la tarea ----
    # Patrones admitidos (estilo Bitácora GRM):
    #   - Rango:        "RI_63-67"       -> RI_63, RI_64, RI_65, RI_66, RI_67
    #   - Sub-variante: "RI_49 (RI_49.1)" -> RI_49, RI_49.1
    #   - Simple:       "MT_25", "IN_5.3"
    @staticmethod
    def _extraer_codigos_hu(name: str) -> List[str]:
        """Devuelve la lista de códigos individuales presentes en ``name``.

        Aplica tres pasadas en orden:
            1. Rangos explícitos (PREFIX_N-M).
            2. Sub-variantes entre paréntesis (PREFIX_X.Y).
            3. Códigos sueltos restantes.
        Devuelve los códigos deduplicados preservando el orden de aparición.
        """
        import re as _re
        if not name:
            return []
        text = _re.sub(r"\s+", " ", name.replace("SC_ ", "SC_")).strip()
        codes: List[str] = []
        # 1) Rangos explícitos
        for m in _re.finditer(r"\b([A-Z]{1,3})_(\d{1,3})-(\d{1,3})\b", text):
            prefix, start, end = m.group(1), int(m.group(2)), int(m.group(3))
            for n in range(start, end + 1):
                codes.append(f"{prefix}_{n}")
        # 2) Sub-variantes entre paréntesis: (RI_49.1) -> RI_49.1
        for m in _re.finditer(r"\(([A-Z]{1,3}_[\d.]+)\)", text):
            codes.append(m.group(1))
        # 3) Códigos sueltos (sobre el texto SIN los rangos ya consumidos)
        text_sin_rangos = _re.sub(r"\b([A-Z]{1,3})_\d{1,3}-\d{1,3}\b", "", text)
        for m in _re.finditer(
            r"\b([A-Z]{1,3})_(\d{1,3})(?:\.(\d{1,3}))?\b", text_sin_rangos
        ):
            prefix = m.group(1)
            a = m.group(2)
            b = m.group(3)
            codes.append(f"{prefix}_{a}" + (f".{b}" if b else ""))
        # Dedup preservando orden
        seen = set()
        unique: List[str] = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    @staticmethod
    def _parent_wbs(wbs: str) -> str:
        """Devuelve el WBS padre (sin la última pieza). Ej: '5.1.3' -> '5.1'."""
        if not wbs:
            return ""
        partes = [p for p in wbs.split(".") if p]
        return ".".join(partes[:-1]) if len(partes) > 1 else ""

    def _parse_tareas(self) -> List[dict]:
        """Lee todos los nodos ``<Task>`` y extrae los datos relevantes.

        Detalle: en MS Project, las tareas "resumen" (OutlineLevel=1)
        agrupan un conjunto de tareas hijas. Las incluimos en el listado
        para que el importador pueda decidir si crear tickets también
        para los resúmenes o solo para las hojas (OutlineLevel>=2).

        Adicionalmente, para cada tarea agregamos:
          - ``modulo``:  nombre de la tarea PADRE o ABUELA según el nivel
            de outline (categoría temática). Sirve para etiquetar cada
            ticket con su módulo (ej: ``Mejoras Transversales``, ``Registro
            de Información``) y poder filtrar en el Gantt.
          - ``hu_codes``:  lista de códigos individuales (HU o caso de
            prueba) extraídos del nombre mediante regex tolerante.

        Nota sobre el ``outline_level``: el campo ``<WBS>`` del XML puede
        NO codificar la jerarquía de forma consistente (ej: ``WBS="14"``
        para un task de nivel 4 sin punto en el WBS). Para resolver el
        nombre del padre correctamente hacemos un seguimiento de la pila
        de outline levels en orden de documento.
        """
        import re as _re
        tareas = []
        contenedor = self._root.find(f"{self.NS}Tasks")
        if contenedor is None:
            return tareas

        # Stack por outline_level: stack[L] = name del task vigente en nivel L.
        # Esto resuelve el problema de "WBS=14" sin punto (su padre es el
        # task vigente al outline_level anterior en orden de documento).
        stack_nombres: Dict[int, str] = {0: ""}

        for t in contenedor.findall(f"{self.NS}Task"):
            uid = (t.findtext(f"{self.NS}UID") or "").strip()
            if not uid:
                continue
            try:
                uid_int = int(uid)
            except ValueError:
                continue
            duration_str = (t.findtext(f"{self.NS}Duration") or "").strip()
            duration_hours = _parse_iso_duration_to_hours(duration_str)
            outline = (t.findtext(f"{self.NS}OutlineLevel") or "1").strip()
            try:
                outline_int = int(outline)
            except ValueError:
                outline_int = 1
            wbs = (t.findtext(f"{self.NS}WBS") or "").strip()
            name = (t.findtext(f"{self.NS}Name") or "").strip()

            # Resolución del módulo (categoría temática) con la pila:
            #   - Nivel 1 (root): modulo=""
            #   - Nivel 2 (phase): modulo = nombre del padre (root)
            #   - Nivel 3 (grupo temático): modulo = nombre del padre (phase)
            #   - Nivel >=4 (paquete/hoja):
            #       modulo = nombre del nivel 3 (grupo temático) si existe,
            #                sino nombre del nivel 2 (phase).
            # Esto etiqueta correctamente categorías como
            # "Mejoras Transversales" o "Seguimiento y Control" para que
            # el dropdown del Gantt filtre por módulo temático real.
            parent_name = stack_nombres.get(outline_int - 1, "") if outline_int >= 1 else ""
            if outline_int <= 1:
                modulo = ""
            elif outline_int == 2:
                modulo = parent_name  # phase: su "módulo" es el proyecto
            elif outline_int == 3:
                modulo = parent_name  # grupo temático: su "módulo" es la phase
            else:
                # level >= 4: usamos el nivel 3 si está en la pila;
                # sino el nivel 2 (phase).
                modulo = (
                    stack_nombres.get(3, "")
                    or stack_nombres.get(2, "")
                    or parent_name
                )
            # Limpiamos prefijos numéricos y mapeamos a la LOV.
            modulo = _limpiar_nombre_modulo(modulo)

            # Códigos individuales de HU / caso de prueba parseados del name.
            hu_codes = self._extraer_codigos_hu(name)

            # Actualizar pila: este task ahora es el vigente a su nivel.
            stack_nombres[outline_int] = name
            # Limpiar niveles más profundos (al subir/bajar el outline level
            # siempre se "cierran" los hijos).
            for lvl in list(stack_nombres.keys()):
                if lvl > outline_int:
                    stack_nombres.pop(lvl, None)

            tareas.append({
                "uid": uid_int,
                "wbs": wbs,
                "name": name,
                "start": (t.findtext(f"{self.NS}Start") or "").strip(),
                "finish": (t.findtext(f"{self.NS}Finish") or "").strip(),
                "duration_hours": duration_hours,
                "outline_level": outline_int,
                "is_summary": (
                    (t.findtext(f"{self.NS}Summary") or "0").strip() == "1"
                    or outline_int == 1
                ),
                "milestone": (t.findtext(f"{self.NS}Milestone") or "0").strip() == "1",
                # Recursos asignados (nombres)
                "recursos": [
                    (r.findtext(f"{self.NS}Name") or "").strip()
                    for r in t.findall(f"{self.NS}Resource")
                ],
                # === NUEVO: módulo temático + códigos HU/caso individuales ===
                "modulo": modulo.strip()[:80],
                "hu_codes": hu_codes,
            })
        return tareas

    def _parse_links(self) -> List[dict]:
        """Lee los ``<PredecessorLink>`` y los mapea al enum interno.

        Soporta DOS formatos de MS Project XML:

        Formato A (moderno, MP 2010+): el elemento incluye tanto
        ``<PredecessorUID>`` como ``<SuccessorUID>`` y ``<PredecessorType>``.
            <PredecessorLink>
              <PredecessorUID>5</PredecessorUID>
              <SuccessorUID>6</SuccessorUID>
              <PredecessorType>1</PredecessorType>
              <LinkLag>0</LinkLag>
            </PredecessorLink>

        Formato B (MP 2007/legacy): NO hay ``<SuccessorUID>`` (el sucesor
        es el Task padre del PredecessorLink) y el tipo se llama ``<Type>``.
            <PredecessorLink>
              <PredecessorUID>389</PredecessorUID>
              <Type>1</Type>
              <CrossProject>0</CrossProject>
              <LinkLag>0</LinkLag>
              <LagFormat>7</LagFormat>
            </PredecessorLink>

        En el formato B el ``<Task>`` que CONTIENE el ``<PredecessorLink>``
        es el sucesor; por eso necesitamos leer también el ``<UID>`` del
        padre. La función acepta ambos formatos transparentemente.
        """
        links: List[dict] = []
        contenedor = self._root.find(f"{self.NS}Tasks")
        if contenedor is None:
            return links
        for t in contenedor.findall(f"{self.NS}Task"):
            # Sucesor: primero intentamos leer el UID del Task padre
            # (válido en ambos formatos; en el formato A debe coincidir
            # con <SuccessorUID> si está presente).
            try:
                parent_uid = int((t.findtext(f"{self.NS}UID") or "0").strip())
            except ValueError:
                parent_uid = 0
            for pl in t.findall(f"{self.NS}PredecessorLink"):
                p = (pl.findtext(f"{self.NS}PredecessorUID") or "").strip()
                # Soporta ambos formatos: <SuccessorUID> (A) o parent UID (B).
                s = (pl.findtext(f"{self.NS}SuccessorUID") or "").strip()
                if not s:
                    s = str(parent_uid)
                if not p or not s:
                    continue
                try:
                    pred_uid = int(p)
                    suc_uid = int(s)
                except ValueError:
                    continue
                if pred_uid == suc_uid:
                    # Una tarea no puede depender de sí misma.
                    continue
                # Tipo: <PredecessorType> (formato A) o <Type> (formato B).
                # Ambos usan los mismos códigos: 0=FF, 1=FS, 2=SF, 3=SS.
                pred_type = (
                    (pl.findtext(f"{self.NS}PredecessorType") or "").strip()
                    or (pl.findtext(f"{self.NS}Type") or "").strip()
                    or "1"
                )
                tipo_enum = self.PRED_TYPE_MAP.get(pred_type, TipoDependencia.FS)
                lag_str = (pl.findtext(f"{self.NS}LinkLag") or "0").strip()
                try:
                    lag_min = int(float(lag_str))
                except ValueError:
                    lag_min = 0
                # MS Project almacena LinkLag en décimas de minuto (1 = 0.1 min).
                # Pasamos a días calendario enteros (redondeo).
                lag_dias = round(lag_min / 10 / 60 / 24)
                links.append({
                    "predecesor_uid": pred_uid,
                    "sucesor_uid": suc_uid,
                    "tipo": tipo_enum,
                    "tipo_str": tipo_enum.value,
                    "lag_minutes": lag_min,
                    "lag_dias": lag_dias,
                })
        return links

    def _parse_recursos(self) -> List[dict]:
        contenedor = self._root.find(f"{self.NS}Resources")
        if contenedor is None:
            return []
        recursos = []
        for r in contenedor.findall(f"{self.NS}Resource"):
            uid = (r.findtext(f"{self.NS}UID") or "").strip()
            name = (r.findtext(f"{self.NS}Name") or "").strip()
            if not uid:
                continue
            try:
                uid_int = int(uid)
            except ValueError:
                continue
            recursos.append({"uid": uid_int, "name": name})
        return recursos


def _parse_iso_duration_to_hours(duration_str: str) -> Optional[float]:
    """Parsea un ISO 8601 Duration (ej: ``PT40H30M15S``) a horas (float).

    Formato: ``P[nD][T[nH][nM][nS]]``. Si hay error, devuelve ``None``
    (no rompe el parseo global: el campo simplemente quedará sin valor).
    """
    if not duration_str or not duration_str.startswith("P"):
        return None
    import re
    match = re.match(
        r"^P(?:(\d+)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$",
        duration_str,
    )
    if not match:
        return None
    dias = float(match.group(1) or 0)
    horas = float(match.group(2) or 0)
    minutos = float(match.group(3) or 0)
    segundos = float(match.group(4) or 0)
    return dias * 24 + horas + minutos / 60 + segundos / 3600


# Mapeo tolerante entre los nombres "largos" que pone el PM en MS Project
# y la LOV permitida por ``Ticket.modulo`` (definida en app.schemas.ticket).
# Sólo lo aplicamos si la LOV contiene una clave explícita; si no, dejamos
# el nombre original tal cual (también es aceptado por la LOV porque "" lo
# es, y los valores fuera-de-LOV no rompen TicketRead).
_LOV_MODULOS = {
    "control erm": "Control ERM",
    "gobierno": "Gobierno",
    "incidencias": "Incidencias",
    "validacion": "Validación",
    "auditoria": "Auditoria",
    "filiales": "Filiales",
    "informacion inventario": "Información Inventario",
    "registro de informacion": "Registro de Información",
    # Variante común en archivos reales: "Registro Información" sin "de".
    "registro informacion": "Registro de Información",
    "documentacion": "Documentación",
    "mejoras transversales": "Mejoras Transversales",
    # Toleramos el typo común "trasnversales" presente en archivos reales
    "mejoras trasnversales": "Mejoras Transversales",
    "seguimiento y control": "Seguimiento y Control",
}


def _limpiar_nombre_modulo(nombre: str) -> str:
    """Limpia un nombre de módulo para alinearlo con la LOV del campo
    ``Ticket.modulo``.

    Pasos:
        1. Quitar prefijos numéricos tipo ``"1 Caso Gobierno OK con OBS"``
           o ``"27 Casos Mejoras trasnversales"`` -> ``"Gobierno OK con OBS"``
           / ``"Mejoras trasnversales"``.
        2. Buscar el término más representativo contra ``_LOV_MODULOS`` y,
           si hay match, devolver la versión canónica de la LOV.
        3. Si no hay match, devolver el nombre limpio (sin prefijo).

    El objetivo es que ``modulo`` sea FILTRABLE en el dropdown del Gantt
    sin obligar al usuario a renombrar las tareas del MPP.
    """
    import re as _re
    if not nombre:
        return ""
    # Normalización: minúsculas sin acentos para comparar contra la LOV
    def _norm(s: str) -> str:
        import unicodedata
        return "".join(
            c for c in unicodedata.normalize("NFD", s.lower())
            if unicodedata.category(c) != "Mn"
        )

    s = nombre.strip()
    # Quitar prefijo "<n> <palabra(s)>" inicial -- ej: "1 Caso Gobierno..." -> "Gobierno..."
    m_pref = _re.match(r"^\d+\s+[A-Za-zÁáÉéÍíÓóÚúÑñ]+\s+(.*)$", s)
    if m_pref:
        candidate = m_pref.group(1).strip()
    else:
        candidate = s

    # Si tras quitar el prefijo la cadena restante YA está en la LOV,
    # devolver su versión canónica.
    candidate_norm = _norm(candidate)
    for k, v in _LOV_MODULOS.items():
        if k in candidate_norm:
            return v

    # Si NO hay match pero la cadena ORIGINAL completa sí contiene una
    # clave de la LOV (ej: "1 Caso Mejoras trasnversales"),
    # igualmente devolvemos la versión canónica.
    full_norm = _norm(s)
    for k, v in _LOV_MODULOS.items():
        if k in full_norm:
            return v

    # Sin match: devolvemos la versión sin prefijo "1 Caso ...", que es
    # más útil para filtrar visualmente en el dropdown.
    return candidate[:80] if candidate else s[:80]
