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

    def _parse_tareas(self) -> List[dict]:
        """Lee todos los nodos ``<Task>`` y extrae los datos relevantes.

        Detalle: en MS Project, las tareas "resumen" (OutlineLevel=1)
        agrupan un conjunto de tareas hijas. Las incluimos en el listado
        para que el importador pueda decidir si crear tickets también
        para los resúmenes o solo para las hojas (OutlineLevel>=2).
        """
        tareas = []
        contenedor = self._root.find(f"{self.NS}Tasks")
        if contenedor is None:
            return tareas
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
            tareas.append({
                "uid": uid_int,
                "wbs": (t.findtext(f"{self.NS}WBS") or "").strip(),
                "name": (t.findtext(f"{self.NS}Name") or "").strip(),
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
            })
        return tareas

    def _parse_links(self) -> List[dict]:
        """Lee los ``<PredecessorLink>`` y los mapea al enum interno."""
        links: List[dict] = []
        contenedor = self._root.find(f"{self.NS}Tasks")
        if contenedor is None:
            return links
        for t in contenedor.findall(f"{self.NS}Task"):
            for pl in t.findall(f"{self.NS}PredecessorLink"):
                p = (pl.findtext(f"{self.NS}PredecessorUID") or "").strip()
                s = (pl.findtext(f"{self.NS}SuccessorUID") or "").strip()
                if not p or not s:
                    continue
                try:
                    pred_uid = int(p)
                    suc_uid = int(s)
                except ValueError:
                    continue
                pred_type = (pl.findtext(f"{self.NS}PredecessorType") or "1").strip()
                # Por defecto FS si no se reconoce el código
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
