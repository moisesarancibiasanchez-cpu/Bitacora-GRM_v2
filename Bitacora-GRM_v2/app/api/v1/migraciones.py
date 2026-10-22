"""
Endpoints one-shot para migraciones de datos.

Estos endpoints exponen migraciones idempotentes que ajustan datos legacy
sin necesidad de conectarse directamente a la base de datos.

Todas las migraciones son seguras de re-ejecutar.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.deps import require_admin
from app.db.session import get_db
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/migraciones", tags=["Migraciones"])


@router.post("/gar-a-resultado-pruebas")
def ejecutar_migracion_gar(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Migra todos los tickets cuyo ``codigo`` empieza con ``GAR_`` al
    tipo ``resultado_pruebas``.

    - **Idempotente**: solo cambia tickets que aún no están en
      ``resultado_pruebas``.
    - **Auditado**: inserta un registro en ``auditoria`` por cada cambio
      con accion ``tipo_migrado_gar``.
    - **Admin only**: requiere rol ``administrador``.

    Returns
    -------
    dict
        Resumen de la migración con conteos y lista de IDs actualizados.
    """
    try:
        from scripts.migrar_gar_a_resultado_pruebas import ejecutar_migracion
        resumen = ejecutar_migracion()
        logger.info(
            "[migracion/gar] admin ejecutó migración: actualizados=%d",
            resumen["actualizados"],
        )
        return resumen
    except Exception as exc:
        logger.exception("[migracion/gar] Error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al ejecutar la migración: {exc}",
        )


@router.get("/gar-preview")
def preview_migracion_gar(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Devuelve cuántos tickets ``GAR_*`` serían modificados, SIN
    modificarlos. Útil para revisar antes de ejecutar.

    Returns
    -------
    dict
        Conteos: ``total_encontrados``, ``ya_en_resultado_pruebas``,
        ``serian_actualizados``.
    """
    from app.models.ticket import Ticket, TipoIncidencia

    tickets = (
        db.query(Ticket)
        .filter(Ticket.codigo.like("GAR_%"))
        .order_by(Ticket.id)
        .all()
    )
    total = len(tickets)
    ya_en_destino = 0
    por_tipo: dict = {}
    for t in tickets:
        tv = t.tipo.value if hasattr(t.tipo, "value") else str(t.tipo)
        por_tipo[tv] = por_tipo.get(tv, 0) + 1
        if tv == TipoIncidencia.RESULTADO_PRUEBAS.value:
            ya_en_destino += 1

    return {
        "prefix": "GAR_",
        "target_type": TipoIncidencia.RESULTADO_PRUEBAS.value,
        "total_encontrados": total,
        "ya_en_resultado_pruebas": ya_en_destino,
        "serian_actualizados": total - ya_en_destino,
        "distribucion_actual": por_tipo,
    }


# ----------------------------------------------------------------------- #
# Bulk update de fechas para tarjetas ``GAR_RI_*`` en BACKLOG
# ----------------------------------------------------------------------- #
@router.post("/gar-ri-fechas-backlog")
def ejecutar_bulk_update_gar_ri_fechas(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Aplica bulk update de ``fecha_inicio`` (2026-10-02) y
    ``fecha_vencimiento_sla`` (2026-11-19) a todas las tarjetas cuyo
    ``codigo`` empieza con ``GAR_RI_`` y están en estado ``BACKLOG``.

    - **Idempotente**: tickets que ya tienen esas dos fechas exactas se
      saltan (no se actualiza ni se insiere auditoría duplicada).
    - **Auditado**: cada cambio inserta un registro en ``auditoria`` con
      acción ``bulk_update_fechas_backlog`` y etiqueta
      ``bulk_update_fechas_backlog:v1`` para trazabilidad y reversión.
    - **Admin only**: requiere rol ``administrador``.
    - **No recalcula SLA en background**: si en el futuro se requiere,
      integrar con la tarea Celery ``recalcular_sla_ticket.delay``.

    Returns
    -------
    dict
        Resumen con conteos y los IDs tocados. Ver
        ``scripts.bulk_update_fechas_gar_ri_backlog.ejecutar_bulk_update``.
    """
    try:
        from scripts.bulk_update_fechas_gar_ri_backlog import ejecutar_bulk_update

        resumen = ejecutar_bulk_update(apply_changes=True)
        logger.info(
            "[migracion/gar-ri-fechas] admin ejecutó bulk update: actualizados=%d",
            resumen.get("actualizados", 0),
        )
        if resumen.get("errores"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "msg": "Errores durante el bulk update",
                    "errores": resumen["errores"],
                },
            )
        return resumen
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[migracion/gar-ri-fechas] Error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al ejecutar el bulk update: {exc}",
        )


@router.get("/gar-ri-fechas-backlog/preview")
def preview_bulk_update_gar_ri_fechas(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Devuelve cuántos tickets ``GAR_RI_*`` en BACKLOG serían modificados,
    SIN modificarlos. Útil para revisar antes de ejecutar.

    Returns
    -------
    dict
        Conteos: ``total_encontrados``, ``ya_con_fechas``,
        ``serian_actualizados``, ``estado_usado``, ``estado_id``.
    """
    try:
        from scripts.bulk_update_fechas_gar_ri_backlog import ejecutar_bulk_update

        return ejecutar_bulk_update(apply_changes=False)
    except Exception as exc:
        logger.exception("[migracion/gar-ri-fechas-preview] Error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en preview: {exc}",
        )
