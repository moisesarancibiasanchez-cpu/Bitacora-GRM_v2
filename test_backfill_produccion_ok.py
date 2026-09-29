"""
Suite de tests para la FEATURE: Producción OK → ticket listo automático.

Cubre DOS componentes relacionados:

    A) Side-effect en ``ticket_service.cambiar_estado()``:
        Cuando un ticket cae en el estado con ``categoria='produccion_ok'``,
        se auto-setan ``fecha_completado``, ``fecha_cumplida=True`` y
        ``sla_cumplido=1``.

    B) Script ``tools/backfill_produccion_ok.py``:
        Aplica el mismo efecto retroactivamente a los tickets que YA
        estaban en Producción OK antes de la nueva lógica, con dos capas
        de idempotencia.

Se ejecuta con stdlib unittest (no requiere pytest).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

# Nota: NO importamos ``app.models`` aquí; eso dispararía ``app.db.__init__``
# que a su vez intentaría crear el engine apuntando a PostgreSQL.
# Todos los imports de modelos se hacen DENTRO de cada test/helper.

# Forzar SQLite ANTES de importar la app
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-123456789012345678901234567890")
os.environ.setdefault("ALLOW_XUSER_HEADER", "true")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ----------------------------------------------------------------------
# Infraestructura de tests (mismo patrón que test_referencias_system.py)
# ----------------------------------------------------------------------
def _build_test_db():
    """Crea un esquema limpio de BD en SQLite para tests."""
    from app.db.base import Base
    from app.db import session as db_session
    # Importar modelos para que SQLAlchemy los registre en Base.metadata
    from app.models import (
        usuario, ticket, estado, auditoria,
        etiqueta, catalogo, espacio,
    )
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db_session.engine = engine
    db_session.SessionLocal = TestSession
    return TestSession


def _clean_db(db):
    """Purga todas las filas de las tablas para aislar tests."""
    from app.models.auditoria import Auditoria
    from app.models.ticket import Ticket
    from app.models.estado import Estado, TransicionEstado
    from app.models.usuario import Usuario
    db.query(Auditoria).delete()
    db.query(Ticket).delete()
    db.query(TransicionEstado).delete()
    db.query(Estado).delete()
    db.query(Usuario).delete()
    db.commit()


def _seed_minimo(db):
    """Crea los estados canónicos y un usuario admin."""
    from app.models.estado import Estado, TransicionEstado
    from app.models.usuario import Usuario, RolUsuario

    estados = {
        "nuevo": Estado(
            nombre="Nuevo", orden=1, es_inicial=True, es_final=False,
            categoria="abierto", sla_horas=24, color="#64748b",
        ),
        "en_curso": Estado(
            nombre="En curso", orden=2, es_inicial=False, es_final=False,
            categoria="abierto", sla_horas=48, color="#3b82f6",
        ),
        "cerrado": Estado(
            nombre="Cerrado", orden=5, es_inicial=False, es_final=True,
            categoria="cerrado", sla_horas=None, color="#475569",
        ),
        "prod_ok": Estado(
            nombre="Producción OK", orden=7, es_inicial=False, es_final=True,
            categoria="produccion_ok", sla_horas=None, color="#0d9488",
            descripcion="Corrección desplegada y verificada en ambiente productivo",
        ),
    }
    for e in estados.values():
        db.add(e)
    db.flush()

    # Transición necesaria para cambiar_estado (LIBRE pero igual la registramos)
    db.add(TransicionEstado(
        estado_origen_id=estados["nuevo"].id,
        estado_destino_id=estados["prod_ok"].id,
        rol_requerido="agente",
        requiere_comentario=False,
    ))

    admin = Usuario(
        username="admin", email="admin@test.local",
        nombre_completo="Admin Test", rol=RolUsuario.ADMINISTRADOR,
        hashed_password="x",  # tests no validan auth
        is_active=True,
    )
    db.add(admin)
    db.commit()

    return estados, admin


def _make_ticket(db, codigo, estado, **overrides):
    """Crea un ticket mínimo en el estado dado."""
    from app.models.ticket import Ticket
    defaults = dict(
        codigo=codigo,
        titulo=f"Ticket {codigo}",
        descripcion="test",
        estado_id=estado.id,
        creador_id=1,
        asignado_id=1,
        archivado=False,
        fecha_cumplida=False,
        sla_cumplido=-1,
    )
    defaults.update(overrides)
    t = Ticket(**defaults)
    db.add(t)
    db.flush()
    db.commit()  # commit para que sea visible por la sesión del backfill
    return t


# ----------------------------------------------------------------------
# Grupo A — Side-effect en ticket_service.cambiar_estado()
# ----------------------------------------------------------------------
class TestSideEffectCambiarEstado(unittest.TestCase):
    """Cubre el bloque 4.2 del side-effect en cambiar_estado()."""

    # ------------------------------------------------------------------
    # Patches para que ``ticket_service.cambiar_estado`` no intente
    # hablar con Celery (no hay broker en este entorno de tests).
    # ``.delay()`` retorna un objeto con un atributo ``id`` cualquiera.
    # ------------------------------------------------------------------
    _celery_patches = []

    @classmethod
    def setUpClass(cls):
        cls.TestSession = _build_test_db()
        from unittest.mock import patch, MagicMock
        cls._celery_patches = [
            patch(
                "app.tasks.sla_tasks.recalcular_sla_ticket.delay",
                MagicMock(return_value=MagicMock(id="fake-sla-id")),
            ),
            patch(
                "app.tasks.notification_tasks.notificar_cambio_estado.delay",
                MagicMock(return_value=MagicMock(id="fake-notif-id")),
            ),
        ]
        for p in cls._celery_patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._celery_patches:
            p.stop()

    def setUp(self):
        self.db = self.TestSession()
        _clean_db(self.db)
        self.estados, self.admin = _seed_minimo(self.db)

    def tearDown(self):
        self.db.close()

    # -------------------------- helpers --------------------------
    def _svc(self):
        from app.services.ticket_service import TicketService
        return TicketService(self.db)

    # -------------------------- tests ----------------------------
    def test_cambiar_a_prod_ok_marca_los_tres_campos(self):
        """Transición a Producción OK setea fc + fcc=True + sla=1."""
        t = _make_ticket(self.db, "A-001", self.estados["nuevo"])
        self.assertIsNone(t.fecha_completado)
        self.assertFalse(t.fecha_cumplida)
        self.assertEqual(t.sla_cumplido, -1)

        result = self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["prod_ok"].id,
            usuario=self.admin,
            comentario="Deploy verificado",
            ip_origen="127.0.0.1",
        )
        # cambiar_estado devuelve (ticket, celery_task_id)
        ticket_devuelto = result[0] if isinstance(result, tuple) else result
        self.assertIsNotNone(ticket_devuelto)
        self.db.refresh(t)

        self.assertIsNotNone(t.fecha_completado,
                             "fecha_completado debe quedar seteada")
        self.assertTrue(t.fecha_cumplida,
                        "fecha_cumplida debe quedar True")
        self.assertEqual(t.sla_cumplido, 1,
                         "sla_cumplido debe forzar cumplimiento (=1)")

    def test_cambiar_a_estado_no_prod_ok_no_toca_sla(self):
        """Una transición a 'En curso' NO debe activar el side-effect."""
        t = _make_ticket(self.db, "A-002", self.estados["nuevo"])
        self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["en_curso"].id,
            usuario=self.admin,
            comentario="Iniciando trabajo",
            ip_origen="127.0.0.1",
        )
        self.db.refresh(t)
        # En curso tiene sla_horas=48 → debe recalcular
        self.assertIsNotNone(t.fecha_vencimiento_sla)
        self.assertEqual(t.sla_cumplido, -1,
                         "En curso debe quedar pendiente, no cumplido")

    def test_prod_ok_preserva_fecha_completado_existente(self):
        """Si el ticket YA tenía fecha_completado, no se sobreescribe."""
        fecha_original = datetime.utcnow() - timedelta(days=2)
        t = _make_ticket(
            self.db, "A-003", self.estados["nuevo"],
            fecha_completado=fecha_original,
            fecha_cumplida=True,
            sla_cumplido=1,
        )
        self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["prod_ok"].id,
            usuario=self.admin,
            comentario="Rollback marcado",
            ip_origen="127.0.0.1",
        )
        self.db.refresh(t)
        self.assertEqual(
            t.fecha_completado.replace(microsecond=0),
            fecha_original.replace(microsecond=0),
            "fecha_completado preexistente NO debe sobreescribirse",
        )

    def test_prod_ok_normaliza_sla_cumplido_de_0_a_1(self):
        """Si el ticket estaba 'vencido' (sla=0), forzar cumplimiento a 1."""
        t = _make_ticket(
            self.db, "A-004", self.estados["nuevo"],
            sla_cumplido=0,  # estaba vencido
        )
        self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["prod_ok"].id,
            usuario=self.admin,
            comentario="Entrega tardía pero efectiva",
            ip_origen="127.0.0.1",
        )
        self.db.refresh(t)
        self.assertEqual(t.sla_cumplido, 1,
                         "Producción OK debe forzar sla_cumplido=1 aunque "
                         "estuviera vencido")

    def test_doble_transicion_a_prod_ok_es_idempotente(self):
        """Pasar de prod_ok → en_curso → prod_ok no debe duplicar efectos."""
        t = _make_ticket(self.db, "A-005", self.estados["prod_ok"])
        # Forzar valores que ya estén 'listos' para no romper el flujo LIBRE
        t.fecha_cumplida = True
        t.sla_cumplido = 1
        t.fecha_completado = datetime.utcnow() - timedelta(days=1)
        self.db.commit()

        # prod_ok → en_curso (válido por transición matriz)
        self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["en_curso"].id,
            usuario=self.admin,
            comentario="Reabrir",
            ip_origen="127.0.0.1",
        )
        self.db.refresh(t)
        # Al re-entrar a prod_ok, los campos ya seteados se preservan
        fecha_pre = t.fecha_completado
        self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["prod_ok"].id,
            usuario=self.admin,
            comentario="Re-deploy OK",
            ip_origen="127.0.0.1",
        )
        self.db.refresh(t)
        self.assertEqual(t.fecha_completado, fecha_pre,
                         "fecha_completado preexistente NO debe cambiar")
        self.assertTrue(t.fecha_cumplida)
        self.assertEqual(t.sla_cumplido, 1)

    def test_auditoria_cambio_estado_se_inserta_normal(self):
        """El side-effect NO reemplaza la auditoría del cambio de estado."""
        from app.models.auditoria import Auditoria
        t = _make_ticket(self.db, "A-006", self.estados["nuevo"])
        antes = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id
        ).count()

        self._svc().cambiar_estado(
            ticket_id=t.id,
            estado_destino_id=self.estados["prod_ok"].id,
            usuario=self.admin,
            comentario="OK",
            ip_origen="127.0.0.1",
        )
        self.db.commit()
        despues = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id
        ).count()
        self.assertEqual(despues, antes + 1,
                         "Debe haber 1 nueva fila de auditoría (CAMBIO_ESTADO)")
        # Y no debe haber BACKFILL_PRODUCCION_OK_LISTO (eso es del script)
        backfill = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id,
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO",
        ).count()
        self.assertEqual(backfill, 0,
                         "El side-effect NO debe crear auditoría BACKFILL")


# ----------------------------------------------------------------------
# Grupo B — Script tools/backfill_produccion_ok.py
# ----------------------------------------------------------------------
class TestBackfillProduccionOk(unittest.TestCase):
    """Cubre el script de migración retroactiva."""

    @classmethod
    def setUpClass(cls):
        cls.TestSession = _build_test_db()

    def setUp(self):
        self.db = self.TestSession()
        _clean_db(self.db)
        self.estados, self.admin = _seed_minimo(self.db)

    def tearDown(self):
        self.db.close()

    # -------------------------- helpers --------------------------
    def _cargar_backfill(self):
        """Importa (o reimporta) el módulo del backfill contra esta BD."""
        from tools import backfill_produccion_ok
        return backfill_produccion_ok

    # -------------------------- tests ----------------------------
    def test_resuelve_estado_por_categoria_no_por_nombre(self):
        b = self._cargar_backfill()
        estado = b._resolver_estado_produccion_ok(self.db)
        self.assertIsNotNone(estado, "Debe encontrar PROD OK")
        self.assertEqual(estado.categoria, "produccion_ok")
        self.assertTrue(estado.es_final)
        # Verificar que aunque renombremos, lo encuentra por categoria
        estado.nombre = "Producción OK ✅ Renombrado"
        self.db.commit()
        estado2 = b._resolver_estado_produccion_ok(self.db)
        self.assertEqual(estado2.id, estado.id,
                         "La búsqueda debe ser por categoria, no por nombre")

    def test_ticket_no_en_prod_ok_se_ignora(self):
        b = self._cargar_backfill()
        t = _make_ticket(self.db, "B-001", self.estados["nuevo"])
        a_actualizar, omitidos = b._listar_tickets_a_procesar(
            self.db, self.estados["prod_ok"].id
        )
        self.assertEqual(len(a_actualizar), 0)
        self.assertEqual(len(omitidos), 0,
                         "Tickets fuera de prod_ok no entran en omitidos "
                         "(ni en a_actualizar)")
        # Y no fue tocado
        self.db.refresh(t)
        self.assertIsNone(t.fecha_completado)

    def test_ticket_vacio_en_prod_ok_se_marca_completo(self):
        b = self._cargar_backfill()
        t = _make_ticket(self.db, "B-002", self.estados["prod_ok"])
        rc = b.ejecutar(dry_run=False)
        self.assertEqual(rc, 0)
        self.db.commit()
        self.db.refresh(t)

        self.assertIsNotNone(t.fecha_completado)
        self.assertTrue(t.fecha_cumplida)
        self.assertEqual(t.sla_cumplido, 1)

    def test_ticket_ya_listo_se_omite_por_idempotencia(self):
        """Si los 3 campos ya están 'listos', no se hace nada."""
        b = self._cargar_backfill()
        fecha_orig = datetime.utcnow() - timedelta(days=3)
        t = _make_ticket(
            self.db, "B-003", self.estados["prod_ok"],
            fecha_completado=fecha_orig,
            fecha_cumplida=True,
            sla_cumplido=1,
        )
        rc = b.ejecutar(dry_run=False)
        self.assertEqual(rc, 0)
        self.db.expire_all()
        from app.models.ticket import Ticket
        t = self.db.query(Ticket).filter(Ticket.id == t.id).first()
        # Ningún campo debe haber cambiado
        self.assertEqual(
            t.fecha_completado.replace(microsecond=0),
            fecha_orig.replace(microsecond=0),
        )
        # Y no debe haber auditoría BACKFILL nueva
        from app.models.auditoria import Auditoria
        n_audits = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id,
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO",
        ).count()
        self.assertEqual(n_audits, 0,
                         "Ticket ya listo: no debe generar auditoría BACKFILL")

    def test_ticket_con_backfill_previo_se_omite(self):
        """Si ya hay auditoría BACKFILL, se omite por idempotencia."""
        from app.models.auditoria import Auditoria
        b = self._cargar_backfill()
        t = _make_ticket(
            self.db, "B-004", self.estados["prod_ok"],
            fecha_completado=datetime.utcnow() - timedelta(days=1),
            fecha_cumplida=True,
            sla_cumplido=1,
        )
        # Insertar auditoría previa simulando un backfill anterior
        self.db.add(Auditoria(
            ticket_id=t.id,
            usuario_id=None,
            accion="BACKFILL_PRODUCCION_OK_LISTO",
            valor_nuevo={"origen": "backfill_produccion_ok"},
            comentario="Backfill previo",
            ip_origen="system:backfill_produccion_ok",
        ))
        self.db.commit()

        rc = b.ejecutar(dry_run=False)
        self.assertEqual(rc, 0)
        # No debe haberse insertado OTRA auditoría BACKFILL
        n_audits = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id,
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO",
        ).count()
        self.assertEqual(n_audits, 1,
                         "Debe seguir habiendo EXACTAMENTE 1 auditoría BACKFILL")

    def test_ticket_parcial_solo_corrige_campos_faltantes(self):
        """Si sólo fecha_completado está seteada, se corrige el resto."""
        b = self._cargar_backfill()
        fecha_orig = datetime.utcnow() - timedelta(days=2)
        t = _make_ticket(
            self.db, "B-005", self.estados["prod_ok"],
            fecha_completado=fecha_orig,
            fecha_cumplida=False,    # falta
            sla_cumplido=0,          # falta
        )
        rc = b.ejecutar(dry_run=False)
        self.assertEqual(rc, 0)
        self.db.refresh(t)

        # fecha_completado se preserva
        self.assertEqual(
            t.fecha_completado.replace(microsecond=0),
            fecha_orig.replace(microsecond=0),
            "fecha_completado preexistente NO debe cambiar",
        )
        # Los otros 2 se corrigen
        self.assertTrue(t.fecha_cumplida)
        self.assertEqual(t.sla_cumplido, 1)

        # Y se registra auditoría con sólo los campos modificados
        from app.models.auditoria import Auditoria
        aud = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id,
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO",
        ).first()
        self.assertIsNotNone(aud)
        campos = aud.valor_nuevo.get("campos_modificados", [])
        self.assertIn("fecha_cumplida", campos)
        self.assertIn("sla_cumplido", campos)
        self.assertNotIn("fecha_completado", campos,
                         "fecha_completado preexistente NO debe figurar "
                         "como modificado")

    def test_segunda_ejecucion_no_duplica_audits(self):
        """Correr dos veces no debe duplicar auditorías BACKFILL."""
        from app.models.auditoria import Auditoria
        b = self._cargar_backfill()
        t1 = _make_ticket(self.db, "B-006", self.estados["prod_ok"])
        t2 = _make_ticket(
            self.db, "B-007", self.estados["prod_ok"],
            fecha_completado=datetime.utcnow() - timedelta(days=1),
            fecha_cumplida=False,
            sla_cumplido=-1,
        )

        # Primera ejecución: ambos se actualizan
        b.ejecutar(dry_run=False)
        self.db.commit()

        n_audits_1 = self.db.query(Auditoria).filter(
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO"
        ).count()
        self.assertEqual(n_audits_1, 2,
                         "Primera ejecución: 2 auditorías BACKFILL nuevas")

        # Segunda ejecución: no debe agregar ninguna nueva
        b.ejecutar(dry_run=False)
        self.db.commit()

        n_audits_2 = self.db.query(Auditoria).filter(
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO"
        ).count()
        self.assertEqual(n_audits_2, 2,
                         "Segunda ejecución: NO debe agregar más auditorías")

    def test_dry_run_no_persiste_cambios(self):
        """--dry-run deja la BD exactamente como estaba."""
        b = self._cargar_backfill()
        t = _make_ticket(self.db, "B-008", self.estados["prod_ok"])
        rc = b.ejecutar(dry_run=True)
        self.assertEqual(rc, 0)
        # dry-run hace rollback; recargamos el ticket fresco de la BD.
        self.db.expire_all()
        from app.models.ticket import Ticket
        t = self.db.query(Ticket).filter(Ticket.id == t.id).first()

        # Ningún campo debe haber cambiado
        self.assertIsNone(t.fecha_completado)
        self.assertFalse(t.fecha_cumplida)
        self.assertEqual(t.sla_cumplido, -1)

        # Ninguna auditoría nueva
        from app.models.auditoria import Auditoria
        n = self.db.query(Auditoria).filter(
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO",
        ).count()
        self.assertEqual(n, 0, "dry-run NO debe insertar auditorías")

    def test_auditoria_tiene_accion_y_usuario_null(self):
        """La auditoría del backfill es evento del sistema (usuario_id=NULL)."""
        from app.models.auditoria import Auditoria
        b = self._cargar_backfill()
        t = _make_ticket(self.db, "B-009", self.estados["prod_ok"])
        b.ejecutar(dry_run=False)
        self.db.commit()

        aud = self.db.query(Auditoria).filter(
            Auditoria.ticket_id == t.id,
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO",
        ).first()
        self.assertIsNotNone(aud)
        self.assertEqual(aud.accion, "BACKFILL_PRODUCCION_OK_LISTO")
        self.assertIsNone(aud.usuario_id,
                          "Backfill es evento de sistema: usuario_id debe ser NULL")
        self.assertEqual(aud.ip_origen, "system:backfill_produccion_ok")
        self.assertIn("origen", aud.valor_nuevo)
        self.assertEqual(aud.valor_nuevo["origen"], "backfill_produccion_ok")

    def test_mezcla_de_escenarios_en_una_pasada(self):
        """Smoke-test integral: 4 tickets, cada uno en un escenario distinto."""
        from app.models.auditoria import Auditoria
        b = self._cargar_backfill()

        # 1. Ticket vacío en prod_ok → actualizar
        t1 = _make_ticket(self.db, "B-MIX-1", self.estados["prod_ok"])
        # 2. Ticket ya listo en prod_ok → omitir
        t2 = _make_ticket(
            self.db, "B-MIX-2", self.estados["prod_ok"],
            fecha_completado=datetime.utcnow() - timedelta(days=5),
            fecha_cumplida=True,
            sla_cumplido=1,
        )
        # 3. Ticket parcial en prod_ok → corregir 2 campos
        t3 = _make_ticket(
            self.db, "B-MIX-3", self.estados["prod_ok"],
            fecha_completado=datetime.utcnow() - timedelta(days=1),
            fecha_cumplida=False,
            sla_cumplido=-1,
        )
        # 4. Ticket fuera de prod_ok → ignorar totalmente
        t4 = _make_ticket(self.db, "B-MIX-4", self.estados["nuevo"])
        self.db.commit()

        rc = b.ejecutar(dry_run=False)
        self.assertEqual(rc, 0)
        self.db.commit()

        # Verificar cada uno
        self.db.refresh(t1)
        self.db.refresh(t2)
        self.db.refresh(t3)
        self.db.refresh(t4)

        # t1: actualizado completo
        self.assertIsNotNone(t1.fecha_completado)
        self.assertTrue(t1.fecha_cumplida)
        self.assertEqual(t1.sla_cumplido, 1)

        # t2: sin cambios
        self.assertEqual(
            t2.fecha_completado.replace(microsecond=0),
            (datetime.utcnow() - timedelta(days=5)).replace(microsecond=0),
        )
        self.assertTrue(t2.fecha_cumplida)
        self.assertEqual(t2.sla_cumplido, 1)

        # t3: parcial corregido
        self.assertTrue(t3.fecha_cumplida)
        self.assertEqual(t3.sla_cumplido, 1)

        # t4: intacto
        self.assertIsNone(t4.fecha_completado)
        self.assertFalse(t4.fecha_cumplida)
        self.assertEqual(t4.sla_cumplido, -1)

        # Auditorías BACKFILL: exactamente 2 (t1 y t3)
        n_audits = self.db.query(Auditoria).filter(
            Auditoria.accion == "BACKFILL_PRODUCCION_OK_LISTO"
        ).count()
        self.assertEqual(n_audits, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
