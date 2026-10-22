"""
FEATURE: Backfill de tickets ya en Producción OK para marcarlos como "listos"
y detener su SLA, alineando el estado de los tickets pre-existentes con el
nuevo side-effect del ``ticket_service.cambiar_estado()``.

Contexto
--------
Cuando un ticket CAE en el estado "Producción OK" (es_final=True,
categoria="produccion_ok"), el ``ticket_service`` ahora:

    - fecha_completado = ahora()          (si era NULL)
    - fecha_cumplida   = True
    - sla_cumplido     = 1                (forzar cumplimiento)

Este script aplica el mismo efecto retroactivamente a los tickets que YA
estaban en Producción OK antes de que el side-effect existiera.

Idempotencia
------------
El script es 100 % idempotente y SEGURO de correr múltiples veces:

    1. Salta tickets que ya tienen una auditoría previa con accion
       ``BACKFILL_PRODUCCION_OK_LISTO`` (defensa principal).
    2. Salta tickets que ya están "listos" en los tres campos:
           fecha_cumplida=True
           AND fecha_completado IS NOT NULL
           AND sla_cumplido = 1
       (defensa secundaria por si la auditoría se borró).
    3. Si el ticket estaba parcialmente marcado (ej. fecha_completado
       seteada pero sla_cumplido=0), sólo corrige los campos faltantes y
       registra auditoría.

Uso
---
::

    # 1) Ver qué cambiaría, sin tocar la BD:
    python tools/backfill_produccion_ok.py --dry-run

    # 2) Aplicar de verdad:
    python tools/backfill_produccion_ok.py

    # 3) Aplicar pero dejar el orden de los campos en JSON:
    python tools/backfill_produccion_ok.py --verbose
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import List, Tuple

# ----------------------------------------------------------------------
# Bootstrap del entorno: idéntico al patrón de tools/audit_db.py
# ----------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite:///./backfill_produccion_ok.db")
os.environ.setdefault("SECRET_KEY", "k")
os.environ.setdefault("AUTO_INIT_DB", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.auditoria import Auditoria  # noqa: E402
from app.models.estado import Estado  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("backfill_produccion_ok")


# Accion de auditoria exclusiva de este script. Si la encontramos en un
# ticket, significa que ya fue procesado por este backfill.
ACCION_BACKFILL = "BACKFILL_PRODUCCION_OK_LISTO"
CATEGORIA_PRODUCCION_OK = "produccion_ok"


def _resolver_estado_produccion_ok(db: Session) -> Estado | None:
    """Localiza el estado Producción OK por ``categoria`` (no por nombre).

    Esto sobrevive a renombrados del estado: si mañana se llama
    "Producción OK ✅" el backfill sigue funcionando.
    """
    return (
        db.query(Estado)
        .filter(Estado.categoria == CATEGORIA_PRODUCCION_OK)
        .first()
    )


def _ya_procesado(db: Session, ticket_id: int) -> bool:
    """True si ya hay una fila de auditoría con ACCION_BACKFILL para este ticket."""
    return (
        db.query(Auditoria)
        .filter(
            Auditoria.ticket_id == ticket_id,
            Auditoria.accion == ACCION_BACKFILL,
        )
        .first()
        is not None
    )


def _ya_esta_listo(ticket: Ticket) -> bool:
    """True si el ticket ya tiene los 3 campos en estado 'listo'."""
    return (
        ticket.fecha_cumplida is True
        and ticket.fecha_completado is not None
        and ticket.sla_cumplido == 1
    )


def _listar_tickets_a_procesar(
    db: Session, estado_prod_ok_id: int
) -> Tuple[List[Ticket], List[Tuple[int, str]]]:
    """Devuelve (tickets_a_actualizar, tickets_omitidos_con_motivo).

    Los omitidos se reportan como ``(ticket_id, motivo)`` para que el
    resumen sea transparente.
    """
    candidatos: List[Ticket] = (
        db.query(Ticket)
        .filter(Ticket.estado_id == estado_prod_ok_id)
        .all()
    )
    a_actualizar: List[Ticket] = []
    omitidos: List[Tuple[int, str]] = []
    for t in candidatos:
        if _ya_procesado(db, t.id):
            omitidos.append((t.id, "ya_procesado_por_backfill"))
            continue
        if _ya_esta_listo(t):
            omitidos.append((t.id, "ya_esta_listo"))
            continue
        a_actualizar.append(t)
    return a_actualizar, omitidos


def _aplicar_backfill_a_ticket(
    db: Session,
    ticket: Ticket,
    dry_run: bool,
    verbose: bool,
) -> dict:
    """Aplica los 3 cambios al ticket (o los simula si ``dry_run``).

    Retorna un dict con el detalle de qué cambió para mostrar en el
    resumen y, opcionalmente, en modo ``--verbose``.
    """
    cambios: dict = {}
    ahora = datetime.utcnow()

    if ticket.fecha_completado is None:
        cambios["fecha_completado"] = {
            "antes": None,
            "despues": ahora.isoformat(),
        }
        if not dry_run:
            ticket.fecha_completado = ahora
    else:
        if verbose:
            cambios["fecha_completado"] = {
                "antes": ticket.fecha_completado.isoformat(),
                "despues": ticket.fecha_completado.isoformat(),
                "preservado": True,
            }

    if not ticket.fecha_cumplida:
        cambios["fecha_cumplida"] = {
            "antes": False,
            "despues": True,
        }
        if not dry_run:
            ticket.fecha_cumplida = True
    else:
        if verbose:
            cambios["fecha_cumplida"] = {
                "antes": True,
                "despues": True,
                "preservado": True,
            }

    if ticket.sla_cumplido != 1:
        cambios["sla_cumplido"] = {
            "antes": ticket.sla_cumplido,
            "despues": 1,
        }
        if not dry_run:
            ticket.sla_cumplido = 1
    else:
        if verbose:
            cambios["sla_cumplido"] = {
                "antes": 1,
                "despues": 1,
                "preservado": True,
            }

    if cambios and not dry_run:
        # Auditoría del backfill (evento de sistema, usuario_id=None).
        db.add(
            Auditoria(
                ticket_id=ticket.id,
                usuario_id=None,
                accion=ACCION_BACKFILL,
                valor_anterior={
                    "fecha_completado": (
                        ticket.fecha_completado.isoformat()
                        if ticket.fecha_completado and "fecha_completado" in cambios
                        else (
                            ticket.fecha_completado.isoformat()
                            if ticket.fecha_completado
                            else None
                        )
                    ),
                    "fecha_cumplida": (
                        False
                        if "fecha_cumplida" in cambios
                        else bool(ticket.fecha_cumplida)
                    ),
                    "sla_cumplido": (
                        cambios.get("sla_cumplido", {}).get(
                            "antes", ticket.sla_cumplido
                        )
                    ),
                },
                valor_nuevo={
                    "origen": "backfill_produccion_ok",
                    "ts": ahora.isoformat(),
                    "campos_modificados": list(cambios.keys()),
                },
                comentario=(
                    "Backfill: ticket previamente en Producción OK; "
                    "marcado como listo y SLA congelado."
                ),
                ip_origen="system:backfill_produccion_ok",
            )
        )
    return cambios


def ejecutar(dry_run: bool = False, verbose: bool = False) -> int:
    """Función principal. Retorna el código de salida del script."""
    db = SessionLocal()
    try:
        estado = _resolver_estado_produccion_ok(db)
        if estado is None:
            logger.error(
                "No existe ningún estado con categoria='%s'. "
                "Verifica que init_db.py haya sido ejecutado.",
                CATEGORIA_PRODUCCION_OK,
            )
            return 2

        logger.info(
            "Estado Producción OK resuelto: id=%s nombre='%s' orden=%s",
            estado.id, estado.nombre, estado.orden,
        )

        a_actualizar, omitidos = _listar_tickets_a_procesar(db, estado.id)
        logger.info(
            "Tickets en Producción OK: %d total, %d a actualizar, %d omitidos",
            len(a_actualizar) + len(omitidos),
            len(a_actualizar),
            len(omitidos),
        )

        if not a_actualizar:
            logger.info("Nada que hacer. No se hicieron cambios.")
            return 0

        actualizados = 0
        for t in a_actualizar:
            cambios = _aplicar_backfill_a_ticket(db, t, dry_run, verbose)
            if cambios:
                actualizados += 1
                logger.info(
                    "[%s] ticket %s (%s) → %d campo(s) modificado(s): %s",
                    "DRY-RUN" if dry_run else "OK",
                    t.id,
                    t.codigo,
                    len(cambios),
                    ", ".join(sorted(cambios.keys())),
                )
                if verbose:
                    for campo, detalle in cambios.items():
                        logger.info("    · %s: %s", campo, detalle)

        if dry_run:
            # En modo dry-run revertimos para no contaminar la BD.
            db.rollback()
            logger.info(
                "DRY-RUN finalizado. Se habrían actualizado %d tickets. "
                "Transacción revertida.",
                actualizados,
            )
        else:
            db.commit()
            logger.info(
                "Backfill aplicado: %d tickets actualizados, %d omitidos.",
                actualizados,
                len(omitidos),
            )

        # Resumen final
        print("\n" + "=" * 72)
        print("RESUMEN DEL BACKFILL — Producción OK → Listo")
        print("=" * 72)
        print(f"Modo:                   {'DRY-RUN (sin cambios)' if dry_run else 'REAL (commit aplicado)'}")
        print(f"Estado Producción OK:   id={estado.id} '{estado.nombre}'")
        print(f"Tickets encontrados:    {len(a_actualizar) + len(omitidos)}")
        print(f"Tickets actualizados:   {actualizados}")
        print(f"Tickets omitidos:       {len(omitidos)}")
        if omitidos:
            print("Detalle de omitidos:")
            # Agrupar por motivo
            motivos: dict = {}
            for tid, motivo in omitidos:
                motivos.setdefault(motivo, []).append(tid)
            for motivo, ids in motivos.items():
                print(f"  · {motivo}: {len(ids)} ticket(s) → ids={ids[:10]}"
                      + (f" (+{len(ids) - 10} más)" if len(ids) > 10 else ""))
        print("=" * 72)
        return 0
    except Exception:
        logger.exception("Backfill falló; haciendo rollback de la transacción.")
        db.rollback()
        return 1
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill de tickets ya en Producción OK para marcarlos como "
            "listos y detener su SLA."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula los cambios sin tocar la base de datos.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Muestra detalle de cada campo modificado por ticket.",
    )
    args = parser.parse_args()
    sys.exit(ejecutar(dry_run=args.dry_run, verbose=args.verbose))


if __name__ == "__main__":  # pragma: no cover
    main()
