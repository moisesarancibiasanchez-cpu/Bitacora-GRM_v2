"""
Router HTTP para el Dev Inbox.

Endpoints:
  GET    /dev/inbox          → vista HTML con los últimos correos.
  GET    /dev/inbox.json     → lista JSON (útil para integraciones).
  GET    /dev/inbox/{id}     → detalle de un correo (texto plano + HTML).
  DELETE /dev/inbox          → limpia todos los correos capturados.
  GET    /dev/inbox/status   → diagnóstico (backend activo, conteo, etc.).

El router se registra SIEMPRE pero cada endpoint valida ``is_enabled()``
en runtime, así no es necesario tocar el wiring en producción.

Seguridad: en producción con SMTP configurado, los endpoints devuelven
``403 dev_inbox_disabled`` automáticamente. Adicionalmente, si se
define ``DEV_INBOX_REQUIRE_AUTH=true``, exige un JWT válido para
acceder (recomendable cuando se expone a internet).
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from app.services import dev_inbox


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/dev/inbox", tags=["dev-inbox"])


# === Guards ==================================================================

def _require_enabled() -> None:
    if not dev_inbox.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dev_inbox_disabled",
        )


def _require_auth_if_configured(request: Request) -> None:
    """Si ``DEV_INBOX_REQUIRE_AUTH=true``, exige un JWT válido.
    Esto se evalúa DESPUÉS de ``_require_enabled``."""
    if os.getenv("DEV_INBOX_REQUIRE_AUTH", "false").lower() != "true":
        return
    # Importación local para evitar ciclos y para tolerar fallos.
    try:
        from app.core.security import decode_access_token
        token = request.cookies.get("access_token")
        if not token:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth.split(None, 1)[1]
        if not token or not decode_access_token(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="dev_inbox_requires_auth",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="dev_inbox_requires_auth",
        )


# === Endpoints ===============================================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def inbox_view(
    request: Request,
    limit: int = 50,
) -> HTMLResponse:
    """Vista HTML con los correos capturados."""
    _require_enabled()
    _require_auth_if_configured(request)

    records = dev_inbox.list_recent(limit=max(1, min(limit, 200)))
    info = dev_inbox.backend_info()

    rows = []
    for r in records:
        ts = datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        recipient = html.escape(r.to)
        if r.cc:
            recipient += f' <span class="text-slate-500 text-xs">+{len(r.cc)} CC</span>'
        subject = html.escape(r.subject or "(sin asunto)")
        transport_badge = (
            '<span class="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800">log</span>'
            if r.transport == "log"
            else '<span class="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">smtp-failed</span>'
        )
        rows.append(f"""
        <tr class="border-b border-slate-200 hover:bg-slate-50">
          <td class="py-2 px-3 text-xs text-slate-500 whitespace-nowrap">{ts}</td>
          <td class="py-2 px-3 text-sm">{recipient}</td>
          <td class="py-2 px-3 text-sm font-medium">{subject}</td>
          <td class="py-2 px-3 text-center">{transport_badge}</td>
          <td class="py-2 px-3 text-center">
            <a href="/dev/inbox/{r.id}" class="text-indigo-600 hover:underline text-sm">ver</a>
          </td>
        </tr>
        """)

    backend_label = (
        f'<span class="px-2 py-1 rounded bg-emerald-100 text-emerald-800 text-xs">Redis</span>'
        if info["backend"] == "redis"
        else f'<span class="px-2 py-1 rounded bg-slate-100 text-slate-700 text-xs">filesystem (tmp/dev_inbox.jsonl)</span>'
    )
    enabled_reason = (
        "activado por DEV_INBOX_ENABLED=true"
        if info["explicitly_enabled"]
        else "activado automáticamente (no hay SMTP configurado)"
        if not info["smtp_configured"]
        else "activado a pesar de SMTP configurado"
    )

    body = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dev Inbox — Bitácora GRM</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
<div class="max-w-6xl mx-auto p-6">
  <header class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold">📬 Dev Inbox</h1>
      <p class="text-sm text-slate-600 mt-1">
        Bandeja de captura de correos para entornos de prueba.
        Backend activo: {backend_label}.
        Estado: <b>{enabled_reason}</b>.
      </p>
    </div>
    <div class="flex gap-2">
      <button onclick="location.reload()" class="px-3 py-2 bg-slate-200 hover:bg-slate-300 rounded text-sm">Refrescar</button>
      <button hx-delete="/dev/inbox" hx-confirm="¿Borrar todos los correos capturados?"
              hx-on::after-request="location.reload()"
              class="px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded text-sm">
        Limpiar bandeja
      </button>
    </div>
  </header>

  <div class="bg-white shadow rounded-lg overflow-hidden">
    <table class="w-full">
      <thead class="bg-slate-100 text-slate-700 text-sm">
        <tr>
          <th class="py-2 px-3 text-left">Fecha</th>
          <th class="py-2 px-3 text-left">Destinatario</th>
          <th class="py-2 px-3 text-left">Asunto</th>
          <th class="py-2 px-3 text-center">Tipo</th>
          <th class="py-2 px-3 text-center">Detalle</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="5" class="py-12 text-center text-slate-500">No hay correos capturados todavía.</td></tr>'}
      </tbody>
    </table>
  </div>

  <p class="text-xs text-slate-500 mt-4">
    Mostrando los últimos {len(records)} correos (máx. {info["max_records"]}).
    Endpoint JSON disponible en <a class="text-indigo-600 hover:underline" href="/dev/inbox.json">/dev/inbox.json</a>.
    Diagnóstico en <a class="text-indigo-600 hover:underline" href="/dev/inbox/status">/dev/inbox/status</a>.
  </p>
</div>
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
</body>
</html>"""
    return HTMLResponse(body)


@router.get("/json", response_class=JSONResponse)
async def inbox_json(
    request: Request,
    limit: int = 50,
) -> JSONResponse:
    """Lista de correos en formato JSON."""
    _require_enabled()
    _require_auth_if_configured(request)
    records = dev_inbox.list_recent(limit=max(1, min(limit, 200)))
    return JSONResponse({
        "count": len(records),
        "backend": dev_inbox.backend_info(),
        "items": [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "timestamp_iso": datetime.fromtimestamp(r.timestamp).isoformat(),
                "to": r.to,
                "cc": r.cc,
                "subject": r.subject,
                "transport": r.transport,
                "sender": r.sender,
                "body": r.body,
                "html_body": r.html_body,
            }
            for r in records
        ],
    })


@router.get("/status", response_class=JSONResponse)
async def inbox_status() -> JSONResponse:
    """Diagnóstico del Dev Inbox: backend activo, conteo, configuración."""
    return JSONResponse(dev_inbox.backend_info())


@router.get("/{record_id}")
async def inbox_detail(
    request: Request,
    record_id: str,
) -> HTMLResponse:
    """Detalle de un correo (texto plano + HTML, iframe para el HTML)."""
    _require_enabled()
    _require_auth_if_configured(request)

    record: Optional[dev_inbox.InboxRecord] = next(
        (r for r in dev_inbox.list_recent(limit=200) if r.id == record_id),
        None,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="record_not_found",
        )

    ts = datetime.fromtimestamp(record.timestamp).strftime("%Y-%m-%d %H:%M:%S")
    body_text = html.escape(record.body or "")
    cc_line = (
        f'<p class="text-xs text-slate-500"><b>CC:</b> {html.escape(", ".join(record.cc))}</p>'
        if record.cc else ""
    )
    iframe = (
        f'<iframe srcdoc="{html.escape(record.html_body, quote=True)}" '
        f'class="w-full border border-slate-200 rounded" style="height:480px"></iframe>'
        if record.html_body else
        '<p class="text-slate-500 italic">Sin contenido HTML.</p>'
    )

    html_doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(record.subject or "(sin asunto)")} — Dev Inbox</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
<div class="max-w-4xl mx-auto p-6">
  <a href="/dev/inbox" class="text-indigo-600 hover:underline text-sm">← volver a la bandeja</a>
  <h1 class="text-2xl font-bold mt-2">{html.escape(record.subject or "(sin asunto)")}</h1>
  <div class="mt-3 text-sm">
    <p><b>Para:</b> {html.escape(record.to)}</p>
    {cc_line}
    <p><b>De:</b> {html.escape(record.sender) or "(no especificado)"}</p>
    <p><b>Fecha:</b> {ts}</p>
    <p><b>Tipo:</b> <code>{html.escape(record.transport)}</code></p>
  </div>

  <h2 class="text-lg font-semibold mt-6 mb-2">Vista previa HTML</h2>
  <div class="bg-white rounded-lg p-4 shadow">
    {iframe}
  </div>

  <h2 class="text-lg font-semibold mt-6 mb-2">Texto plano</h2>
  <pre class="bg-slate-900 text-slate-100 p-4 rounded text-xs whitespace-pre-wrap overflow-auto">{body_text}</pre>
</div>
</body>
</html>"""
    return HTMLResponse(html_doc)


@router.delete("", response_class=JSONResponse)
@router.delete("/", response_class=JSONResponse)
async def inbox_clear(request: Request) -> JSONResponse:
    """Borra todos los correos capturados."""
    _require_enabled()
    _require_auth_if_configured(request)
    before = dev_inbox.count()
    dev_inbox.clear()
    return JSONResponse({"cleared": True, "removed": before})
