"""
Migración one-shot: GAR_* → Resultado Pruebas
================================================

Cambia el campo ``tipo`` a ``resultado_pruebas`` para todas las tarjetas
cuyo ``codigo`` empiece por ``GAR_``.

Uso
---
Este script está pensado para ejecutarse a través del endpoint HTTP
``POST /api/v1/migraciones/gar-a-resultado-pruebas`` registrado en
``app.api.v1.migraciones``.

También puede invocarse manualmente desde la línea de comandos:

    cd /workspace/Bitacora-GRM_v2
    .venv/bin/python -m scripts.migrar_gar_a_resultado_pruebas

Características
--------------
- **Idempotente**: solo actualiza las tarjetas cuyo ``tipo`` aún no sea
  ``resultado_pruebas``. Re-ejecuciones no producen cambios.
- **Seguro**: no toca el ``codigo``, ``titulo``, ``descripcion`` ni
  ningún otro campo del ticket.
- **Auditado**: por cada cambio se inserta un registro en ``auditoria``
  con acción ``tipo_migrado_gar`` para mantener trazabilidad.
- **Reporta**: devuelve el conteo de filas actualizadas y los IDs
  modificados.
"""
import logging
import sys
from datetime import datetime
from typing import Dict, List

# Permitir imports relativos al proyecto cuando se ejecuta desde CLI
from app.db.session import SessionLocal
from app.models.ticket import Ticket, TipoIncidencia
from app.models.auditoria import Auditoria

logger = logging.getLogger(__name__)

PREFIX = "GAR_"
NUEVO_TIPO = TipoIncidencia.RESULTADO_PRUEBAS  # enum value: "resultado_pruebas"


def ejecutar_migracion() -> Dict:
    """Ejecuta la migración ``GAR_* → resultado_pruebas``.

    Returns
    -------
    dict
        Resumen con claves:
        - ``total_encontrados``: tickets con codigo que comienza con GAR_
        - ``ya_en_resultado_pruebas``: tickets que ya estaban en el tipo destino
        - ``actualizados``: tickets cuyo tipo fue modificado
        - ``ids_actualizados``: lista de IDs modificados
        - ``ejecutado_en``: timestamp ISO-8601 UTC
    """
    db = SessionLocal()
    resumen: Dict = {
        "total_encontrados": 0,
        "ya_en_resultado_pruebas": 0,
        "actualizados": 0,
        "ids_actualizados": [],
        "ejecutado_en": datetime.utcnow().isoformat() + "Z",
    }
    try:
        # 1) Encontrar todos los tickets GAR_*
        tickets = (
            db.query(Ticket)
            .filter(Ticket.codigo.like(f"{PREFIX}%"))
            .order_by(Ticket.id)
            .all()
        )
        resumen["total_encontrados"] = len(tickets)

        if not tickets:
            logger.info("[migracion] No se encontraron tickets con prefijo %s", PREFIX)
            return resumen

        ids_actualizados: List[int] = []
        for ticket in tickets:
            tipo_actual = (
                ticket.tipo.value
                if hasattr(ticket.tipo, "value")
                else str(ticket.tipo)
            )
            if tipo_actual == NUEVO_TIPO.value:
                resumen["ya_en_resultado_pruebas"] += 1
                continue

            tipo_anterior = tipo_actual
            ticket.tipo = NUEVO_TIPO

            # Insertar auditoría (campo `comentario` para el detalle legible)
            auditoria = Auditoria(
                ticket_id=ticket.id,
                usuario_id=ticket.creador_id or 1,
                accion="tipo_migrado_gar",
                valor_anterior=tipo_anterior,
                valor_nuevo=NUEVO_TIPO.value,
                comentario=(
                    f"Migración automática: codigo {ticket.codigo} "
                    f"comienza con {PREFIX}, tipo {tipo_anterior} -> {NUEVO_TIPO.value}"
                ),
            )
            db.add(auditoria)
            ids_actualizados.append(ticket.id)

        db.commit()
        resumen["actualizados"] = len(ids_actualizados)
        resumen["ids_actualizados"] = ids_actualizados

        logger.info(
            "[migracion] GAR_* → %s: encontrados=%d ya_en_destino=%d actualizados=%d",
            NUEVO_TIPO.value,
            resumen["total_encontrados"],
            resumen["ya_en_resultado_pruebas"],
            resumen["actualizados"],
        )
        return resumen
    except Exception as exc:
        db.rollback()
        logger.exception("[migracion] Error durante la migración: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("=" * 70)
    print(f"  MIGRACIÓN GAR_* → {NUEVO_TIPO.value}  ({datetime.utcnow().isoformat()}Z)")
    print("=" * 70)
    try:
        r = ejecutar_migracion()
        print(f"  Encontrados:               {r['total_encontrados']}")
        print(f"  Ya en resultado_pruebas:   {r['ya_en_resultado_pruebas']}")
        print(f"  Actualizados:              {r['actualizados']}")
        if r["ids_actualizados"]:
            print(f"  IDs actualizados:          {r['ids_actualizados']}")
        print("=" * 70)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
