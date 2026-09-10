"""
Script de limpieza inicial de la base de datos (EJECUTAR UNA SOLA VEZ).

Propósito
=========
Vaciar TODAS las tablas relacionadas con tickets para que el sistema
quede en estado limpio antes de pasar a producción.

⚠️  ADVERTENCIA
---------------
Este script está pensado para entornos de **pruebas/desarrollo** que
van a pasar a producción. **NO debe ejecutarse en producción**, ya que
borrará todos los tickets, auditoría, comentarios, adjuntos, etc.

Uso
---
$ python scripts/limpiar_tickets.py --confirmar

El flag ``--confirmar`` es obligatorio para evitar borrados accidentales.

Tablas que se vacían (en orden, para respetar claves foráneas)
--------------------------------------------------------------
1. auditoria           (registros de cambios de tickets)
2. comentarios         (comentarios de tickets)
3. checklist_items     (ítems de checklists)
4. checklists          (checklists de tickets)
5. adjuntos            (archivos adjuntos)
6. ticket_etiquetas    (relación N:M)
7. historial_estados   (historial de transiciones)
8. tickets             (la tabla principal)
9. etiquetas           (catálogo de etiquetas)
10. notificaciones     (notificaciones generadas)
11. watches            (suscripciones)

NO se vacían
------------
- usuarios             (cuentas de acceso)
- espacios, tableros   (estructura organizacional)
- estados              (columnas del Kanban)
- transiciones_estado  (reglas ITSM)
- catalogos            (catálogos del sistema)
- automatizaciones     (reglas Butler)
"""
import sys
from datetime import datetime

# Permitir imports relativos al proyecto
from app.db.session import SessionLocal
from app.models.ticket import Ticket, HistorialEstado
from app.models.auditoria import Auditoria
from app.models.comentario import Comentario
from app.models.checklist import Checklist, ChecklistItem
from app.models.adjunto import Adjunto
from app.models.etiqueta import Etiqueta, ticket_etiquetas
from app.models.watch import Watch, Notificacion


TABLAS_A_LIMPIAR = [
    ("auditoria",         Auditoria),
    ("comentarios",       Comentario),
    ("checklist_items",   ChecklistItem),
    ("checklists",        Checklist),
    ("adjuntos",          Adjunto),
    ("historial_estados", HistorialEstado),
    ("ticket_etiquetas",  ticket_etiquetas),  # tabla de relación
    ("tickets",           Ticket),
    ("etiquetas",         Etiqueta),
    ("notificaciones",    Notificacion),
    ("watches",           Watch),
]


def limpiar_tablas(confirmar: bool = False) -> dict:
    """Vacía las tablas indicadas en ``TABLAS_A_LIMPIAR``.

    Parameters
    ----------
    confirmar : bool
        Debe ser True para proceder. Si no, aborta sin hacer nada.

    Returns
    -------
    dict
        Resumen con el conteo de filas eliminadas por tabla.
    """
    if not confirmar:
        print("❌ Operación abortada: debe pasar --confirmar para limpiar la BD.")
        return {}

    db = SessionLocal()
    resumen = {}
    try:
        print("=" * 70)
        print(f"  LIMPIEZA DE TABLAS DE TICKETS - {datetime.utcnow().isoformat()}Z")
        print("=" * 70)
        print()
        print("Tablas a vaciar (en orden):")
        for nombre, _ in TABLAS_A_LIMPIAR:
            print(f"  · {nombre}")
        print()
        input("⚠️  Presione ENTER para confirmar o Ctrl+C para abortar... ")

        for nombre, modelo in TABLAS_A_LIMPIAR:
            try:
                # Tabla de asociación vs modelo ORM
                if hasattr(modelo, "__table__"):
                    count = db.query(modelo).count()
                    db.query(modelo).delete()
                else:
                    # Tabla de asociación: usar execute + delete
                    from sqlalchemy import delete
                    stmt = delete(modelo)
                    result = db.execute(stmt)
                    count = result.rowcount or 0
                db.commit()
                resumen[nombre] = count
                print(f"  ✓ {nombre:<22} eliminadas: {count:>6} filas")
            except Exception as exc:
                db.rollback()
                resumen[nombre] = f"ERROR: {exc}"
                print(f"  ✗ {nombre:<22} ERROR: {exc}")

        print()
        print("=" * 70)
        print("  ✓ LIMPIEZA COMPLETADA")
        print("=" * 70)
        print()
        print("El sistema está listo para producción.")
        print("Próximos pasos:")
        print("  1. Crear usuarios administradores desde /auth/registro")
        print("  2. Definir estados y transiciones en /catalogos/estados")
        print("  3. Crear etiquetas por defecto si las necesitas")
        print("  4. Empezar a crear tickets desde el Kanban")
        return resumen
    finally:
        db.close()


if __name__ == "__main__":
    if "--confirmar" in sys.argv:
        limpiar_tablas(confirmar=True)
    else:
        print("Uso: python scripts/limpiar_tickets.py --confirmar")
        print("⚠️  Este script BORRA TODAS las tarjetas y su historial.")
        print("    Solo debe ejecutarse en entornos de prueba antes de PROD.")
        sys.exit(0)
