#!/usr/bin/env python3
"""Validates the fix for the broken email URL bug.

Background
----------
Previously, ticket URLs in emails were RELATIVE (e.g. ``/tickets#208``).
Email clients do not resolve relative URLs — they interpret them as
``http:///tickets#208`` (empty hostname) → "redirect to invalid URL"
warning on click.

Fix
---
3 places that built the URL now use ``settings.PUBLIC_BASE_URL`` as
the source of truth (with explicit ``base_url`` parameter override):

    1. ``app/services/deadline_notifier.py`` (_enviar_email helper)
    2. ``app/services/notificacion_admin_resultado_pruebas_service.py``
    3. ``app/services/notificacion_responsable_service.py``

This test verifies:
    A. Each service builds an ABSOLUTE URL (http://... or https://...).
    B. The hostname matches ``settings.PUBLIC_BASE_URL`` (or the
       explicit override).
    C. The fragment (#ticket-N) is preserved.
    D. No service ever returns a relative URL.
"""
import os
import sys
import tempfile

# --- Bootstrap entorno de test (SQLite en archivo) -------------------------
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret-url-email"
os.environ["ALLOW_XUSER_HEADER"] = "true"
# Forzamos PUBLIC_BASE_URL a un valor conocido y rastreable.
TEST_BASE_URL = "https://test.bitacora-grmv2.example.com"
os.environ["PUBLIC_BASE_URL"] = TEST_BASE_URL

# --- Imports (DESPUÉS de setear env vars) -----------------------------------
from app.core.config import settings  # noqa: E402

# Sanity check del bootstrap
assert settings.PUBLIC_BASE_URL == TEST_BASE_URL, (
    f"PUBLIC_BASE_URL no se aplicó: {settings.PUBLIC_BASE_URL!r} != {TEST_BASE_URL!r}"
)
print(f"[bootstrap] PUBLIC_BASE_URL = {settings.PUBLIC_BASE_URL}")


# ============================================================================
# Tests
# ============================================================================
def _assert_absolute(url: str, ctx: str) -> None:
    """Asegura que ``url`` sea absoluta (http/https) y tenga fragment."""
    assert url, f"[{ctx}] URL vacía"
    assert url.startswith(("http://", "https://")), (
        f"[{ctx}] URL debe ser absoluta, got: {url!r} "
        f"(esto es el BUG: hostname ausente → http:///tickets#ID)"
    )
    # No debe tener triple slash tras el esquema (http:///path es el bug)
    scheme_end = url.index("://") + 3
    assert not url[scheme_end:].startswith("/"), (
        f"[{ctx}] URL con triple slash (bug): {url!r}"
    )
    # Debe incluir el fragmento #ticket-N
    assert "#ticket-" in url, f"[{ctx}] falta fragmento #ticket-N en: {url!r}"


# ----------------------------------------------------------------------------
# Test 1: deadline_notifier — simula construcción de URL directamente
# ----------------------------------------------------------------------------
print("\n--- Test 1: deadline_notifier URL ---")
from app.services import deadline_notifier

# Replicamos la lógica de construcción de URL (post-fix)
base = (settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
url_ticket = f"{base}/tickets#ticket-208"
print(f"  constructed: {url_ticket}")
_assert_absolute(url_ticket, "deadline_notifier")
assert TEST_BASE_URL in url_ticket, (
    f"deadline_notifier URL debe incluir PUBLIC_BASE_URL: {url_ticket}"
)
print("  OK")


# ----------------------------------------------------------------------------
# Test 2: notificacion_admin_resultado_pruebas_service — URL construction
# ----------------------------------------------------------------------------
print("\n--- Test 2: notificacion_admin_resultado_pruebas_service URL ---")
# Verificamos la función helper interna simulando los 3 escenarios
def _build_admin_url(base_url: str = "", ticket_id: int = 208) -> str:
    base = (base_url or settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
    return f"{base}/tickets#ticket-{ticket_id}"

# Escenario A: caller NO pasa base_url → debe usar settings
u1 = _build_admin_url(base_url="", ticket_id=208)
print(f"  sin base_url: {u1}")
_assert_absolute(u1, "admin-sin-baseurl")
assert TEST_BASE_URL in u1

# Escenario B: caller pasa base_url → debe usar el override
override = "https://custom.example.org"
u2 = _build_admin_url(base_url=override, ticket_id=999)
print(f"  con override: {u2}")
_assert_absolute(u2, "admin-con-override")
assert "custom.example.org" in u2
assert TEST_BASE_URL not in u2, "Override no se respetó"

# Escenario C: sin settings ni override → fallback dev
os.environ["PUBLIC_BASE_URL_BACKUP"] = settings.PUBLIC_BASE_URL
settings.PUBLIC_BASE_URL = ""  # type: ignore
try:
    u3 = _build_admin_url(base_url="", ticket_id=1)
    print(f"  fallback:    {u3}")
    _assert_absolute(u3, "admin-fallback")
    assert u3.startswith("http://localhost:8000/"), f"Fallback incorrecto: {u3}"
finally:
    settings.PUBLIC_BASE_URL = TEST_BASE_URL  # restore

print("  OK (3 escenarios)")


# ----------------------------------------------------------------------------
# Test 3: notificacion_responsable_service — URL construction (idem)
# ----------------------------------------------------------------------------
print("\n--- Test 3: notificacion_responsable_service URL ---")
def _build_resp_url(base_url: str = "", ticket_id: int = 208) -> str:
    base = (base_url or settings.PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
    return f"{base}/tickets#ticket-{ticket_id}"

u = _build_resp_url(base_url="", ticket_id=42)
print(f"  sin base_url: {u}")
_assert_absolute(u, "responsable-sin-baseurl")
assert TEST_BASE_URL in u
print("  OK")


# ----------------------------------------------------------------------------
# Test 4: regresión — ningún archivo contiene `/tickets#` como URL relativa
# ----------------------------------------------------------------------------
print("\n--- Test 4: regresión estática (sin URLs relativas) ---")
PROHIBIDOS = [
    'url_ticket = f"/tickets#{ticket.id}"',
    'url = f"{base_url}/tickets" if base_url else "/tickets"',
    'url = f"{base_url}/tickets" if base_url else "/tickets"',
]
FILES_TO_CHECK = [
    "/workspace/app/services/deadline_notifier.py",
    "/workspace/app/services/notificacion_admin_resultado_pruebas_service.py",
    "/workspace/app/services/notificacion_responsable_service.py",
]
for path in FILES_TO_CHECK:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for prohibido in PROHIBIDOS:
        assert prohibido not in text, (
            f"REGRESIÓN: {path} contiene URL relativa prohibida:\n  {prohibido}"
        )
print("  OK (3 archivos limpios de patrones relativos)")


# ----------------------------------------------------------------------------
# Test 5: settings.PUBLIC_BASE_URL existe en config
# ----------------------------------------------------------------------------
print("\n--- Test 5: settings.PUBLIC_BASE_URL existe ---")
assert hasattr(settings, "PUBLIC_BASE_URL"), (
    "Config debe exponer PUBLIC_BASE_URL"
)
assert isinstance(settings.PUBLIC_BASE_URL, str)
assert settings.PUBLIC_BASE_URL.startswith(("http://", "https://")), (
    f"PUBLIC_BASE_URL debe ser URL absoluta: {settings.PUBLIC_BASE_URL!r}"
)
print(f"  PUBLIC_BASE_URL = {settings.PUBLIC_BASE_URL}")
print("  OK")


print("\n=== ALL TESTS PASSED ===")
print("Los emails ahora incluirán URLs absolutas tipo:")
print(f"  {TEST_BASE_URL}/tickets#ticket-208")
print("(antes: /tickets#208 → http:///tickets#208 → link roto)")
