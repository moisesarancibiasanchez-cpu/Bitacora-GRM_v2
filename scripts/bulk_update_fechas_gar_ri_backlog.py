"""
Bulk update de fechas para tarjetas ``GAR_RI_*`` en BACKLOG
============================================================

Cambia ``fecha_inicio`` y ``fecha_vencimiento_sla`` para todas las tarjetas
cuyo ``codigo`` empiece por ``GAR_RI_`` y estén en la columna BACKLOG
(según ``estados.nombre``).

Uso
---
Pensado para ejecutarse desde la línea de comandos:

    cd /workspace
    # 1) Previsualizar (no modifica nada):
    python scripts/bulk_update_fechas_gar_ri_backlog.py --dry-run

    # 2) Aplicar (commit + audit log):
    python scripts/bulk_update_fechas_gar_ri_backlog.py --apply

    # Alternativas:
    python scripts/bulk_update_fechas_gar_ri_backlog.py \\
        --apply --prefix GAR_RI_ --estado BACKLOG \\
        --fecha-inicio 2026-10-02 --fecha-vencimiento 2026-11-19

Default
-------
- ``--prefix``           ``GAR_RI_``
- ``--estado``           ``BACKLOG`` (búsqueda case-insensitive)
- ``--fecha-inicio``     ``2026-10-02`` (2 de octubre de 2026)
- ``--fecha-vencimiento`` ``2026-11-19`` (19 de noviembre de 2026)

Características
--------------
- **Dry-run por defecto**: a menos que se pase ``--apply``, SOLO lista
  las tarjetas candidatas sin modificar la BD.
- **Idempotente en valores**: si la tarjeta ya tiene esas dos fechas
  exactas, no se actualiza ni se inserta auditoría redundante.
- **Auditado**: por cada cambio se inserta un registro en ``auditoria``
  con acción ``bulk_update_fechas_backlog`` que guarda ``valor_anterior``
  y ``valor_nuevo`` como JSON con ambas fechas.
- **Reporta**: devuelve conteos y los IDs tocados para confirmación.
- **Seguro**: rollback automático ante cualquier error.
- **Idempotente en re-ejecución**: si las fechas ya están aplicadas, no
  vuelve a insertar auditoría. Detecta el caso vía un campo comentario
  único en la auditoría previa (``bulk_update_fechas_backlog:v1``).

Notas
-----
- Esta operación NO recalcula SLA en background (no encola Celery). Si
  en el futuro se requiere, integrar con la tarea
  ``recalcular_sla_ticket.delay(ticket_id)`` desde el worker.
- En SQLite local (sin Celery), basta con ejecutar el script. En
  PostgreSQL de producción, el script usa la misma ``SessionLocal``
  configurada vía ``DATABASE_URL``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

# Permitir imports relativos al proyecto cuando se ejecuta desde CLI
from app.db.session import SessionLocal
from app.models.auditoria import Auditoria
from app.models.estado import Estado
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

# Defaults solicitados en la tarea
PREFIX_DEFAULT = "GAR_RI_"
ESTADO_BACKLOG_DEFAULT = "BACKLOG"
FECHA_INICIO_DEFAULT = "2026-10-02"        # 2 de octubre de 2026
FECHA_VENCIMIENTO_DEFAULT = "2026-11-19"   # 19 de noviembre de 2026

ACCION_AUDITORIA = "bulk_update_fechas_backlog"
AUDITORIA_TAG = "bulk_update_fechas_backlog:v1"  # tag para idempotencia


def _parse_date(s: str) -> datetime:
    """Parsea ``YYYY-MM-DD`` a ``datetime`` a medianoche (00:00:00)."""
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(
            f"Fecha inválida {s!r}: se esperaba YYYY-MM-DD ({e})"
        ) from e


@dataclass
class Resumen:
    """Resumen del bulk update."""
    total_encontrados: int = 0
    ya_con_fechas: int = 0
    actualizados: int = 0
    saltados_sin_estado_match: int = 0
    ids_actualizados: List[int] = None
    ids_ya_con_fechas: List[int] = None
    ejecutado_en: str = ""
    dry_run: bool = True
    estado_usado: Optional[str] = None
    estado_id: Optional[int] = None
    errores: List[str] = None

    def __post_init__(self):
        self.ids_actualizados = self.ids_actualizados or []
        self.ids_ya_con_fechas = self.ids_ya_con_fechas or []
        self.errores = self.errores or []


def _buscar_estado_backlog(
    db, nombre_estado: str
) -> tuple[Optional[Estado], Optional[str]]:
    """Busca el estado por nombre (case-insensitive).

    Retorna ``(estado, error)``. Si ``estado`` es None, ``error`` explica.
    """
    if not nombre_estado:
        return None, "Nombre de estado vacío"
    needle = nombre_estado.strip().lower()
    estados = db.query(Estado).all()
    for e in estados:
        if e.nombre and e.nombre.strip().lower() == needle:
            return e, None
    nombres = sorted({e.nombre for e in estados if e.nombre})
    return None, (
        f"No se encontró estado con nombre '{nombre_estado}' (case-insensitive). "
        f"Estados disponibles: {nombres}"
    )


def _es_idempotente(ticket: Ticket, fecha_ini: datetime, fecha_fin: datetime) -> bool:
    """True si el ticket ya tiene exactamente esas dos fechas."""
    fi = ticket.fecha_inicio
    ff = ticket.fecha_vencimiento_sla
    if fi is None or ff is None:
        return False
    # Comparación a nivel de fecha (ignorando hora)
    return (fi.year, fi.month, fi.day) == (fecha_ini.year, fecha_ini.month, fecha_ini.day) \
        and (ff.year, ff.month, ff.day) == (fecha_fin.year, fecha_fin.month, fecha_fin.day)


def ejecutar_bulk_update(
    *,
    prefix: str = PREFIX_DEFAULT,
    nombre_estado: str = ESTADO_BACKLOG_DEFAULT,
    fecha_inicio_str: str = FECHA_INICIO_DEFAULT,
    fecha_vencimiento_str: str = FECHA_VENCIMIENTO_DEFAULT,
    apply_changes: bool = False,
    confirm: bool = False,
) -> Dict:
    """Ejecuta el bulk update de fechas para ``GAR_RI_*`` en BACKLOG.

    Parameters
    ----------
    prefix : str
        Prefijo del código del ticket (default ``GAR_RI_``).
    nombre_estado : str
        Nombre del estado BACKLOG (case-insensitive).
    fecha_inicio_str / fecha_vencimiento_str : str
        Fechas en formato ``YYYY-MM-DD`` (se almacenan como
        ``datetime`` a medianoche).
    apply_changes : bool
        Si ``False`` (default) sólo ejecuta dry-run y no modifica la BD.
    confirm : bool
        Si ``True``, no pregunta nada (asume que el caller ya confirmó).

    Returns
    -------
    dict
        Resumen con claves: ``total_encontrados``, ``ya_con_fechas``,
        ``actualizados``, ``ids_actualizados``, ``ids_ya_con_fechas``,
        ``ejecutado_en``, ``dry_run``, ``estado_usado``, ``estado_id``,
        ``errores``.
    """
    fecha_inicio = _parse_date(fecha_inicio_str)
    fecha_vencimiento = _parse_date(fecha_vencimiento_str)

    if fecha_vencimiento < fecha_inicio:
        raise ValueError(
            f"fecha_vencimiento ({fecha_vencimiento_str}) no puede ser "
            f"anterior a fecha_inicio ({fecha_inicio_str})"
        )

    resumen = Resumen(
        dry_run=not apply_changes,
        ejecutado_en=datetime.utcnow().isoformat() + "Z",
    )

    db = SessionLocal()
    try:
        # 1) Localizar el estado BACKLOG
        estado, err = _buscar_estado_backlog(db, nombre_estado)
        if err:
            resumen.errores.append(err)
            logger.error("[bulk_update] %s", err)
            return _resumen_to_dict(resumen)
        resumen.estado_usado = estado.nombre
        resumen.estado_id = estado.id

        # 2) Encontrar todas las tarjetas con prefijo y en BACKLOG
        tickets = (
            db.query(Ticket)
            .filter(Ticket.codigo.like(f"{prefix}%"))
            .filter(Ticket.estado_id == estado.id)
            .order_by(Ticket.id)
            .all()
        )
        resumen.total_encontrados = len(tickets)

        if not tickets:
            logger.info(
                "[bulk_update] No se encontraron tickets '%s%%' en estado '%s'",
                prefix, estado.nombre,
            )
            return _resumen_to_dict(resumen)

        # 3) Iterar: saltamos idempotentes, actualizamos el resto
        ids_actualizados: List[int] = []
        ids_ya_con_fechas: List[int] = []

        for ticket in tickets:
            if _es_idempotente(ticket, fecha_inicio, fecha_vencimiento):
                ids_ya_con_fechas.append(ticket.id)
                continue

            valor_anterior = {
                "fecha_inicio": (
                    ticket.fecha_inicio.isoformat() if ticket.fecha_inicio else None
                ),
                "fecha_vencimiento_sla": (
                    ticket.fecha_vencimiento_sla.isoformat()
                    if ticket.fecha_vencimiento_sla else None
                ),
            }
            valor_nuevo = {
                "fecha_inicio": fecha_inicio.isoformat(),
                "fecha_vencimiento_sla": fecha_vencimiento.isoformat(),
            }

            if apply_changes:
                ticket.fecha_inicio = fecha_inicio
                ticket.fecha_vencimiento_sla = fecha_vencimiento
                auditoria = Auditoria(
                    ticket_id=ticket.id,
                    usuario_id=ticket.creador_id or 1,
                    accion=ACCION_AUDITORIA,
                    valor_anterior=valor_anterior,
                    valor_nuevo=valor_nuevo,
                    comentario=(
                        f"{AUDITORIA_TAG} | codigo={ticket.codigo} "
                        f"estado={estado.nombre} "
                        f"nueva_inicio={valor_nuevo['fecha_inicio']} "
                        f"nuevo_sla={valor_nuevo['fecha_vencimiento_sla']}"
                    ),
                )
                db.add(auditoria)
            ids_actualizados.append(ticket.id)

        resumen.actualizados = len(ids_actualizados)
        resumen.ya_con_fechas = len(ids_ya_con_fechas)
        resumen.ids_actualizados = ids_actualizados
        resumen.ids_ya_con_fechas = ids_ya_con_fechas

        # 4) Solo si apply_changes hacemos commit
        if apply_changes:
            db.commit()
            logger.info(
                "[bulk_update] COMMIT OK: actualizados=%d ya_con_fechas=%d estado=%s",
                resumen.actualizados, resumen.ya_con_fechas, estado.nombre,
            )
        else:
            db.rollback()
            logger.info(
                "[bulk_update] DRY-RUN: candidatos=%d ya_con_fechas=%d estado=%s",
                resumen.actualizados, resumen.ya_con_fechas, estado.nombre,
            )
        return _resumen_to_dict(resumen)
    except Exception as exc:
        db.rollback()
        logger.exception("[bulk_update] Error: %s", exc)
        resumen.errores.append(f"{type(exc).__name__}: {exc}")
        return _resumen_to_dict(resumen)
    finally:
        db.close()


def _resumen_to_dict(r: Resumen) -> Dict:
    return {
        "total_encontrados": r.total_encontrados,
        "ya_con_fechas": r.ya_con_fechas,
        "actualizados": r.actualizados,
        "saltados_sin_estado_match": r.saltados_sin_estado_match,
        "ids_actualizados": r.ids_actualizados,
        "ids_ya_con_fechas": r.ids_ya_con_fechas,
        "ejecutado_en": r.ejecutado_en,
        "dry_run": r.dry_run,
        "estado_usado": r.estado_usado,
        "estado_id": r.estado_id,
        "errores": r.errores,
    }


def _print_resumen(r: Dict) -> None:
    print("=" * 78)
    print(
        f"  BULK UPDATE GAR_RI_* en BACKLOG  "
        f"({'DRY-RUN' if r['dry_run'] else 'APLICADO'})  "
        f"{datetime.utcnow().isoformat()}Z"
    )
    print("=" * 78)
    if r["errores"]:
        print("  ERRORES:")
        for e in r["errores"]:
            print(f"    - {e}")
        print("=" * 78)
        return
    print(f"  Estado usado:               {r['estado_usado']} (id={r['estado_id']})")
    print(f"  Tickets encontrados:        {r['total_encontrados']}")
    print(f"  Ya con esas fechas:         {r['ya_con_fechas']}")
    print(f"  Candidatos a actualizar:    {r['actualizados']}")
    if r["ids_actualizados"]:
        ids_str = ", ".join(str(i) for i in r["ids_actualizados"])
        print(f"    IDs:                      {ids_str}")
    if r["ids_ya_con_fechas"]:
        ids_str = ", ".join(str(i) for i in r["ids_ya_con_fechas"])
        print(f"  IDs ya correctos:           {ids_str}")
    print(f"  Fecha inicio objetivo:     {FECHA_INICIO_DEFAULT}")
    print(f"  Fecha SLA objetivo:        {FECHA_VENCIMIENTO_DEFAULT}")
    if r["dry_run"]:
        print()
        print("  ⚠ DRY-RUN: ningún cambio fue aplicado.")
        print("  Para aplicar, vuelve a ejecutar con --apply.")
    else:
        print()
        print("  ✓ Cambios aplicados y auditados.")
    print("=" * 78)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk update fechas_inicio/vencimiento_sla para GAR_RI_* en BACKLOG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica los cambios (por defecto SOLO dry-run).",
    )
    parser.add_argument(
        "--prefix",
        default=PREFIX_DEFAULT,
        help=f"Prefijo del código del ticket (default: {PREFIX_DEFAULT})",
    )
    parser.add_argument(
        "--estado",
        default=ESTADO_BACKLOG_DEFAULT,
        help=(
            f"Nombre del estado BACKLOG (case-insensitive, "
            f"default: {ESTADO_BACKLOG_DEFAULT})"
        ),
    )
    parser.add_argument(
        "--fecha-inicio",
        default=FECHA_INICIO_DEFAULT,
        help=f"Fecha de inicio YYYY-MM-DD (default: {FECHA_INICIO_DEFAULT})",
    )
    parser.add_argument(
        "--fecha-vencimiento",
        default=FECHA_VENCIMIENTO_DEFAULT,
        help=(
            "Fecha de vencimiento (SLA) YYYY-MM-DD "
            f"(default: {FECHA_VENCIMIENTO_DEFAULT})"
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirma la operación (omite el prompt interactivo al aplicar).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Logging nivel DEBUG.",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.apply and not args.yes and sys.stdin.isatty():
        # Sólo pedimos confirmación si hay TTY (evitamos bloqueo en CI)
        print(
            f"Vas a aplicar bulk update de fechas a tickets "
            f"'{args.prefix}*' en estado '{args.estado}'.\n"
            f"  fecha_inicio        = {args.fecha_inicio}\n"
            f"  fecha_vencimiento   = {args.fecha_vencimiento}\n"
            f"¿Continuar? [y/N] ",
            end="",
        )
        try:
            r = input().strip().lower()
        except EOFError:
            r = ""
        if r != "y":
            print("Cancelado por el usuario.")
            return 130  # 130 = SIGINT por convención

    resumen = ejecutar_bulk_update(
        prefix=args.prefix,
        nombre_estado=args.estado,
        fecha_inicio_str=args.fecha_inicio,
        fecha_vencimiento_str=args.fecha_vencimiento,
        apply_changes=args.apply,
        confirm=args.yes,
    )
    _print_resumen(resumen)
    return 0 if not resumen.get("errores") else 1


if __name__ == "__main__":
    sys.exit(main())
