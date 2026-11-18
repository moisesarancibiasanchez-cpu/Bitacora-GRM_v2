"""
Endpoints one-shot para migraciones de datos.

Estos endpoints exponen migraciones idempotentes que ajustan datos legacy
sin necesidad de conectarse directamente a la base de datos.

Todas las migraciones son seguras de re-ejecutar.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
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


@router.get("/esquema")
def diagnostico_esquema(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Compara el metadata de SQLAlchemy con el esquema real de la base de datos.

    Diagnóstico de SOLO LECTURA: no aplica migraciones ni modifica nada.

    Devuelve tres bloques:

    * ``columnas_sincronizadas``: el estado de ``COLUMNS_TO_ADD`` (las
      columnas que las migraciones deben añadir si faltan).
    * ``comparacion_completa``: una línea por tabla del modelo, con las
      columnas que faltan en la base de datos.
    * ``deriva``: solo las tablas con deriva real (las que NO están OK).

    Y dos bloques más sobre ÍNDICES (V2.009), porque el guardian comparaba
    solo columnas y en producción fallaron 52 de los 55 índices declarados
    sin que nada lo dijera:

    * ``indices``: los índices declarados que NO están donde deben
      (``FALTA`` o ``COLISION``). Los que están bien no se reportan.
    * ``indices_faltantes`` / ``indices_colision``: los mismos, separados.

    Sirve para medir la deriva antes de encender el guardián estricto
    (``ESQUEMA_ESTRICTO``): un guardián fail-closed sobre el esquema completo
    puede tumbar los tres servicios si la base de datos arrastra una deriva
    heredada, así que primero se mide.

    Returns
    -------
    dict
        ``ok`` (bool), ``deriva`` (list[str]), ``comparacion_completa``
        (list[str]), ``columnas_sincronizadas`` (list[str]),
        ``tablas_modelo`` (int) y ``tablas_base_datos`` (int).
    """
    from sqlalchemy import inspect

    from app.db.migrations import (
        comparar_esquema_completo,
        comparar_indices_completo,
        report_schema_drift,
    )

    eng = db.get_bind()
    comparacion = comparar_esquema_completo(eng)
    deriva = [l for l in comparacion if "faltan" in l or "no existe" in l]
    indices = comparar_indices_completo(eng)
    try:
        tablas_bd = len(inspect(eng).get_table_names())
    except Exception:  # pragma: no cover
        tablas_bd = -1

    return {
        "ok": not deriva,
        "deriva": deriva,
        "comparacion_completa": comparacion,
        "indices": indices,
        "indices_faltantes": [l for l in indices if "FALTA" in l],
        "indices_colision": [l for l in indices if "COLISION" in l],
        "columnas_sincronizadas": report_schema_drift(eng),
        "tablas_modelo": len(comparacion),
        "tablas_base_datos": tablas_bd,
    }


# ----------------------------------------------------------------------- #
# Clon de la base de datos (validacion de migraciones)
# ----------------------------------------------------------------------- #
class ClonRequest(BaseModel):
    nombre: str = Field(
        default="railway_clon_v2009",
        max_length=63,
        description="Nombre de la base de datos del clon (solo letras, digitos y _)",
    )
    copiar_datos: bool = Field(
        default=True,
        description="Si False, solo se replica el esquema (util para validar DDL)",
    )


@router.post("/clonar")
def clonar_base_datos(
    datos: ClonRequest,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Crea un CLON de la base de datos en el mismo servidor PostgreSQL.

    Sirve para validar migraciones y cambios de esquema contra una copia de
    los datos reales, sin tocar la base de datos de produccion.

    - El clon se crea con el nombre indicado (``railway_clon_*`` por defecto).
    - Se replica el esquema desde el metadata de los modelos y se copian los
      datos fila a fila en orden de dependencias; las secuencias quedan
      alineadas con el maximo copiado.
    - Se devuelve la URL de conexion del clon (admin-only).

    Se revierte con ``DELETE /api/v1/migraciones/clonar/{nombre}``.
    """
    from app.core.config import settings
    from app.services.clone_service import ErrorClonado, clonar_base_datos as clonar

    try:
        resultado = clonar(
            settings.get_database_url(),
            datos.nombre,
            copiar_datos=datos.copiar_datos,
        )
    except ErrorClonado as exc:
        logger.warning("[migracion/clon] no se pudo clonar: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[migracion/clon] error inesperado al clonar")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al clonar la base de datos: {exc}",
        )
    logger.info("[migracion/clon] clon creado: %s", resultado.get("nombre"))
    return resultado


@router.delete("/clonar/{nombre}")
def borrar_clon(
    nombre: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Borra la base de datos del clon (operacion de reversion)."""
    from app.core.config import settings
    from app.services.clone_service import ErrorClonado, borrar_clon as borrar

    try:
        return borrar(settings.get_database_url(), nombre)
    except ErrorClonado as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[migracion/clon] error inesperado al borrar el clon")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al borrar el clon: {exc}",
        )


@router.get("/clones")
def listar_clones(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Lista las bases de datos de clon que existen en el servidor."""
    from app.core.config import settings
    from app.services.clone_service import ErrorClonado, listar_clones as listar

    try:
        return {"clones": listar(settings.get_database_url())}
    except ErrorClonado as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/clonar/{nombre}/verificar")
def verificar_clon(
    nombre: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Compara el clon con la base de datos de origen (SOLO LECTURA).

    Validacion de la ventana V2: comprueba que el clon es una copia fiel
    (mismas tablas, mismas columnas, mismo numero de filas) y que el
    backfill del aislamiento por proyecto quedo aplicado dentro del clon
    (ninguna fila de negocio con ``proyecto_id`` a NULL, proyecto "Legacy"
    existente y con miembros).

    No escribe nada ni en el origen ni en el clon.

    Returns
    -------
    dict
        ``ok`` (bool) y el detalle de la comparacion.
    """
    from app.core.config import settings
    from app.services.clone_service import ErrorClonado, verificar_clon as verificar

    try:
        return verificar(settings.get_database_url(), nombre)
    except ErrorClonado as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[migracion/clon] error inesperado al verificar el clon")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al verificar el clon: {exc}",
        )


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
