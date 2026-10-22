"""
Tests del módulo ``app.core.timezone`` y de los filtros Jinja2 ``cl``/``cl_iso``.

Objetivo: garantizar que la conversión UTC → America/Santiago produce el
offset correcto (-03:00 en invierno austral, -04:00 en horario de verano)
y que los filtros toleran tanto datetimes como strings ISO 8601.

Se ejecuta con ``pytest`` o ``python -m unittest``.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

# Garantizar import de la app cuando se ejecuta fuera de pytest.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault("SECRET_KEY", "test-tz-cl-only")
os.environ.setdefault("AUTO_INIT_DB", "false")

from app.core.timezone import (
    now_utc,
    now_cl,
    to_cl,
    fmt_cl,
    fmt_cl_iso,
    CL_TZ,
)


class TimezoneCLTests(unittest.TestCase):
    """Verifica conversión UTC → America/Santiago."""

    def test_now_utc_es_naive(self):
        """``now_utc`` debe devolver un datetime naive (compatibilidad SQLAlchemy)."""
        u = now_utc()
        self.assertIsNotNone(u)
        self.assertIsNone(u.tzinfo)

    def test_now_cl_es_aware(self):
        """``now_cl`` debe ser tz-aware y vivir en America/Santiago."""
        c = now_cl()
        self.assertIsNotNone(c.tzinfo)
        self.assertEqual(str(c.tzinfo), str(CL_TZ))

    def test_diferencia_utc_cl_3_horas_invierno(self):
        """Chile mantiene UTC-3 todo el año desde la derogación del DST en 2019.
        En cualquier fecha, CL va ATRASADO 3h respecto a UTC."""
        # Forzamos un datetime en pleno invierno austral: 2026-10-05.
        utc = datetime(2026, 10, 5, 23, 0, 0, tzinfo=timezone.utc)
        cl = to_cl(utc)
        # CL debería ser 2026-10-05 20:00 con offset -03:00
        self.assertEqual(cl.hour, 20)
        self.assertEqual(cl.minute, 0)
        offset = cl.utcoffset()
        self.assertIsNotNone(offset)
        # -3h = -10800s
        self.assertEqual(offset, timedelta(hours=-3))

    def test_diferencia_utc_cl_3_horas_verano(self):
        """Aún en enero (antiguo horario de verano) Chile va solo -3h:
        el DST fue derogado en Chile en 2019, ya no se alterna."""
        # Forzamos pleno verano austral: 2026-01-15.
        utc = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        cl = to_cl(utc)
        # CL debería ser 2026-01-15 09:00 con offset -03:00
        self.assertEqual(cl.hour, 9)
        offset = cl.utcoffset()
        self.assertIsNotNone(offset)
        # -3h = -10800s
        self.assertEqual(offset, timedelta(hours=-3))

    def test_to_cl_con_naive_asume_utc(self):
        """Datetimes naive se interpretan como UTC."""
        naive = datetime(2026, 10, 5, 23, 0, 0)
        cl = to_cl(naive)
        self.assertEqual(cl.hour, 20)
        self.assertEqual(cl.utcoffset(), timedelta(hours=-3))

    def test_to_cl_none_retorna_none(self):
        """``None`` → ``None``."""
        self.assertIsNone(to_cl(None))

    def test_fmt_cl_formato_default(self):
        """``fmt_cl`` produce ``YYYY-MM-DD HH:MM`` en hora CL."""
        utc = datetime(2026, 10, 5, 23, 30, 0, tzinfo=timezone.utc)
        s = fmt_cl(utc)
        self.assertEqual(s, "2026-10-05 20:30")

    def test_fmt_cl_formato_custom(self):
        """``fmt_cl`` acepta strftime custom."""
        utc = datetime(2026, 10, 5, 23, 30, 0, tzinfo=timezone.utc)
        s = fmt_cl(utc, "%d/%m/%Y %H:%M")
        self.assertEqual(s, "05/10/2026 20:30")

    def test_fmt_cl_iso_incluye_offset(self):
        """``fmt_cl_iso`` devuelve ISO 8601 con offset (ej. ``-03:00``)."""
        utc = datetime(2026, 10, 5, 23, 0, 0, tzinfo=timezone.utc)
        iso = fmt_cl_iso(utc)
        self.assertIsNotNone(iso)
        # Debe contener -03:00 (invierno)
        self.assertIn("-03:00", iso)

    def test_fmt_cl_none_retorna_vacio(self):
        """``fmt_cl(None)`` → ``""``; ``fmt_cl_iso(None)`` → ``None``."""
        self.assertEqual(fmt_cl(None), "")
        self.assertIsNone(fmt_cl_iso(None))


class JinjaFiltersTests(unittest.TestCase):
    """Verifica que ``cl`` y ``cl_iso`` funcionan con datetimes y strings."""

    def setUp(self):
        from app.core.jinja_filters import cl, cl_iso

        self.cl = cl
        self.cl_iso = cl_iso

    def test_cl_con_datetime(self):
        utc = datetime(2026, 10, 5, 23, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(self.cl(utc), "2026-10-05 20:00")

    def test_cl_con_string_iso(self):
        s = "2026-10-05T23:00:00Z"
        self.assertEqual(self.cl(s), "2026-10-05 20:00")

    def test_cl_con_string_iso_con_offset(self):
        s = "2026-10-05T20:00:00-03:00"
        self.assertEqual(self.cl(s), "2026-10-05 20:00")

    def test_cl_con_none_retorna_vacio(self):
        self.assertEqual(self.cl(None), "")
        self.assertEqual(self.cl(""), "")

    def test_cl_con_string_invalida_retorna_original(self):
        self.assertEqual(self.cl("no-es-fecha"), "no-es-fecha")

    def test_cl_iso_con_datetime(self):
        utc = datetime(2026, 10, 5, 23, 0, 0, tzinfo=timezone.utc)
        iso = self.cl_iso(utc)
        self.assertIn("-03:00", iso)
        self.assertIn("20:00:00", iso)

    def test_filtros_registrados_en_main(self):
        """Verifica que ``ALL_FILTERS`` exporta los filtros."""
        from app.core.jinja_filters import ALL_FILTERS

        self.assertIn("cl", ALL_FILTERS)
        self.assertIn("cl_iso", ALL_FILTERS)
        self.assertIn("truncate_text", ALL_FILTERS)


if __name__ == "__main__":
    unittest.main(verbosity=2)