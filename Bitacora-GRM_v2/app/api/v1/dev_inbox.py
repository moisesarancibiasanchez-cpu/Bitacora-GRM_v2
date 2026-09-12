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
    q: str = "",
) -> HTMLResponse:
    """Vista HTML con los correos capturados. Soporta filtro ``q`` por
    substring del destinatario (case-insensitive)."""
    _require_enabled()
    _require_auth_if_configured(request)

    records = (
        dev_inbox.filter_by_recipient(q, limit=max(1, min(limit, 200)))
        if q else
        dev_inbox.list_recent(limit=max(1, min(limit, 200)))
    )
    info = dev_inbox.backend_info()
    stats = dev_inbox.stats()

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
          <td class="py-2 px-3 text-center">
            <button hx-delete="/dev/inbox/{r.id}"
                    hx-confirm="¿Eliminar este correo?"
                    hx-on::after-request="location.reload()"
                    class="text-red-600 hover:text-red-800 text-sm"
                    title="Eliminar este correo de la bandeja">✕</button>
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
      <button hx-post="/dev/inbox/test" hx-swap="none"
              hx-on::after-request="location.reload()"
              class="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-sm inline-flex items-center gap-1">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
        Enviar prueba
      </button>
      <a href="/dev/inbox/export.csv" class="px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-sm inline-flex items-center gap-1">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h6l2 2h7a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>
        CSV
      </a>
      <button hx-delete="/dev/inbox" hx-confirm="¿Borrar todos los correos capturados?"
              hx-on::after-request="location.reload()"
              class="px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded text-sm">
        Limpiar bandeja
      </button>
    </div>
  </header>

  <!-- Filtro por destinatario -->
  <form method="get" action="/dev/inbox" class="mb-4 flex gap-2 items-center">
    <input type="search" name="q" value="{html.escape(q)}"
           placeholder="Filtrar por destinatario (ej: @empresa-a.cl, juan, etc.)"
           class="flex-1 px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
    <button type="submit" class="px-3 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded text-sm">Filtrar</button>
    {f'<a href="/dev/inbox" class="px-3 py-2 text-slate-600 hover:text-slate-900 text-sm">Limpiar</a>' if q else ''}
  </form>

  <!-- Mini-stats -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-center text-xs">
    <div class="bg-white shadow rounded p-3">
      <div class="text-2xl font-bold text-slate-900">{stats["total"]}</div>
      <div class="text-slate-500">Total capturados</div>
    </div>
    <div class="bg-white shadow rounded p-3">
      <div class="text-2xl font-bold text-amber-600">{stats["by_transport"].get("log", 0)}</div>
      <div class="text-slate-500">Modo log</div>
    </div>
    <div class="bg-white shadow rounded p-3">
      <div class="text-2xl font-bold text-red-600">{stats["by_transport"].get("smtp-failed", 0)}</div>
      <div class="text-slate-500">SMTP falló</div>
    </div>
    <div class="bg-white shadow rounded p-3">
      <div class="text-2xl font-bold text-emerald-600">{len(stats["top_recipients"])}</div>
      <div class="text-slate-500">Empresas distintas</div>
    </div>
  </div>

  <div class="bg-white shadow rounded-lg overflow-hidden">
    <table class="w-full">
      <thead class="bg-slate-100 text-slate-700 text-sm">
        <tr>
          <th class="py-2 px-3 text-left">Fecha</th>
          <th class="py-2 px-3 text-left">Destinatario</th>
          <th class="py-2 px-3 text-left">Asunto</th>
          <th class="py-2 px-3 text-center">Tipo</th>
          <th class="py-2 px-3 text-center">Detalle</th>
          <th class="py-2 px-3 text-center">Eliminar</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="6" class="py-12 text-center text-slate-500">No hay correos capturados todavía. Haz clic en «Enviar prueba» para generar uno.</td></tr>'}
      </tbody>
    </table>
  </div>

  {f'''
  <div class="mt-4 grid md:grid-cols-2 gap-3 text-xs">
    <div class="bg-white shadow rounded p-3">
      <div class="font-semibold text-slate-700 mb-1">Top destinatarios (por dominio)</div>
      <ul class="text-slate-600 space-y-0.5">
        {"".join(f"<li>· {html.escape(item['domain'])}: <b>{item['count']}</b></li>" for item in stats["top_recipients"]) or "<li class='italic'>Sin datos</li>"}
      </ul>
    </div>
    <div class="bg-white shadow rounded p-3">
      <div class="font-semibold text-slate-700 mb-1">Top asuntos</div>
      <ul class="text-slate-600 space-y-0.5">
        {"".join(f"<li>· {html.escape(item['subject_prefix'])}: <b>{item['count']}</b></li>" for item in stats["top_subjects"]) or "<li class='italic'>Sin datos</li>"}
      </ul>
    </div>
  </div>
  ''' if stats["total"] > 0 else ''}

  <p class="text-xs text-slate-500 mt-4">
    Mostrando {len(records)} correos{f' (filtrado por «{html.escape(q)}»)' if q else ''} (máx. {info["max_records"]}).
    JSON: <a class="text-indigo-600 hover:underline" href="/dev/inbox.json">/dev/inbox.json</a>.
    Stats: <a class="text-indigo-600 hover:underline" href="/dev/inbox/stats">/dev/inbox/stats</a>.
    Diagnóstico: <a class="text-indigo-600 hover:underline" href="/dev/inbox/status">/dev/inbox/status</a>.
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


@router.get("/stats", response_class=JSONResponse)
async def inbox_stats() -> JSONResponse:
    """Estadísticas agregadas del Dev Inbox (para QA/dashboards)."""
    return JSONResponse(dev_inbox.stats())


@router.get("/export.csv")
async def inbox_export_csv(request: Request) -> PlainTextResponse:
    """Exporta todos los correos capturados a CSV (RFC 4180-ish)."""
    _require_enabled()
    _require_auth_if_configured(request)

    import csv
    import io

    records = dev_inbox.list_recent()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "timestamp_iso", "to", "cc", "subject",
        "transport", "sender", "body", "html_body",
    ])
    for r in records:
        writer.writerow([
            r.id,
            datetime.fromtimestamp(r.timestamp).isoformat(),
            r.to,
            "; ".join(r.cc),
            r.subject,
            r.transport,
            r.sender,
            (r.body or "").replace("\n", "\\n"),
            (r.html_body or "").replace("\n", "\\n"),
        ])

    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="dev_inbox_'
                f'{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
            ),
        },
    )


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


@router.delete("/{record_id}", response_class=JSONResponse)
async def inbox_delete_one(request: Request, record_id: str) -> JSONResponse:
    """Borra un correo específico por id."""
    _require_enabled()
    _require_auth_if_configured(request)
    removed = dev_inbox.delete(record_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="record_not_found",
        )
    return JSONResponse({"deleted": True, "id": record_id})


@router.post("/test", response_class=JSONResponse)
async def inbox_send_test(
    request: Request,
    to: Optional[str] = None,
    subject: Optional[str] = None,
) -> JSONResponse:
    """Envía un correo de prueba que cae en el Dev Inbox.

    Pensado para que QA pueda verificar la captura con un solo click
    desde la UI (botón «Enviar prueba») sin tener que recorrer todo el
    flujo de creación de usuario o movimiento de ticket.

    Query params opcionales:
      - to:      destinatario (default: qa-test@bitacora-grm.local)
      - subject: asunto (default: «[Dev Inbox] Correo de prueba»)
    """
    _require_enabled()
    _require_auth_if_configured(request)

    recipient = (to or "").strip() or "qa-test@bitacora-grm.local"
    subj = (subject or "").strip() or "[Dev Inbox] Correo de prueba"
    body_text = (
        f"Este es un correo de prueba generado por el endpoint "
        f"/dev/inbox/test.\n\n"
        f"Destinatario: {recipient}\n"
        f"Asunto: {subj}\n"
        f"Timestamp: {datetime.now().isoformat()}\n\n"
        f"Si ves esto en /dev/inbox, el flujo de captura funciona OK."
    )
    body_html = (
        f'<!doctype html><html><body style="font-family:sans-serif;'
        f'padding:24px;background:#f8fafc">'
        f'<div style="max-width:560px;margin:0 auto;background:#fff;'
        f'padding:24px;border-radius:12px;border:1px solid #e2e8f0">'
        f'<h1 style="color:#0f172a;margin:0 0 12px">📬 Dev Inbox — Prueba</h1>'
        f'<p style="color:#334155;margin:0 0 8px">'
        f'Este es un correo de prueba generado por '
        f'<code>/dev/inbox/test</code>.</p>'
        f'<p style="color:#334155;margin:0 0 8px">'
        f'<b>Destinatario:</b> {html.escape(recipient)}</p>'
        f'<p style="color:#334155;margin:0 0 16px">'
        f'<b>Asunto:</b> {html.escape(subj)}</p>'
        f'<p style="color:#64748b;font-size:12px;margin:0">'
        f'Si ves este correo en /dev/inbox, la captura funciona OK ✅</p>'
        f'</div></body></html>'
    )

    # Reusamos el flujo real de email_service para que el test cubra
    # también la lógica de fallback del email_service (no duplicamos código).
    from app.services.email_service import send_email
    result = send_email(
        to=recipient,
        subject=subj,
        body=body_text,
        html_body=body_html,
    )

    return JSONResponse({
        "sent": result.sent,
        "transport": result.transport,
        "to": result.to,
        "subject": result.subject,
        "detail": result.detail,
        "message": (
            "Correo capturado. Refresca /dev/inbox para verlo."
            if result.transport == "log"
            else f"Resultado: {result.detail or 'OK'}"
        ),
    })
