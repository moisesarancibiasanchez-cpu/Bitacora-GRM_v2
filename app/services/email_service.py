"""
Servicio de envío de emails para notificaciones de Bitácora GRM.

Soporta dos modos de operación según variables de entorno:

1) **Producción (SMTP real)**
   Si se definen ``SMTP_HOST`` y ``SMTP_FROM``, el servicio envía los
   correos usando ``smtplib`` con autenticación opcional
   (``SMTP_USER``/``SMTP_PASSWORD``) y ``STARTTLS`` si ``SMTP_USE_TLS=true``.

2) **Desarrollo / sin SMTP (fallback)**
   Si NO hay SMTP configurado, los correos se persisten en
   ``tmp/app.email.log`` y se devuelven como ``sent=False, transport="log"``
   para que el flujo de la aplicación nunca falle por falta de SMTP.

Este diseño es consistente con el patrón ya usado en
``app.tasks.notification_tasks`` (logger en lugar de SMTP real) y permite
que las pruebas funcionales y la demo local funcionen out-of-the-box.
"""
from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

# Directorio donde se persisten los emails cuando SMTP no está disponible.
_LOG_DIR = Path("tmp")
_LOG_FILE = _LOG_DIR / "app.email.log"


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _smtp_configured() -> bool:
    """Devuelve True si están las variables mínimas de SMTP."""
    return bool(
        os.getenv("SMTP_HOST")
        and os.getenv("SMTP_FROM")
    )


@dataclass
class EmailResult:
    """Resultado del intento de envío de un email."""
    sent: bool
    transport: str   # "smtp" | "log" | "disabled"
    to: str
    subject: str
    detail: Optional[str] = None


def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    html_body: Optional[str] = None,
    cc: Optional[list] = None,
) -> EmailResult:
    """
    Envía un email (o lo loguea si SMTP no está configurado).

    Parameters
    ----------
    to : str
        Dirección de destino.
    subject : str
        Asunto del correo.
    body : str
        Cuerpo en texto plano.
    html_body : str, opcional
        Cuerpo en HTML (se envía como alternative).
    cc : list[str], opcional
        Direcciones en copia.

    Returns
    -------
    EmailResult
        ``sent=True`` si se entregó, ``sent=False`` si solo se logueó
        (modo desarrollo).
    """
    if not to:
        return EmailResult(False, "disabled", to, subject, "destinatario_vacio")

    # ---- Modo desarrollo: persistir a archivo y devolver sent=False. ----
    if not _smtp_configured():
        _ensure_log_dir()
        try:
            with _LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write("=" * 72 + "\n")
                fh.write(f"Para:   {to}\n")
                fh.write(f"CC:     {', '.join(cc) if cc else '-'}\n")
                fh.write(f"Asunto: {subject}\n")
                fh.write("-" * 72 + "\n")
                fh.write(body)
                if html_body:
                    fh.write("\n--- HTML ---\n")
                    fh.write(html_body)
                fh.write("\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("[email] No se pudo escribir en log: %s", exc)
        logger.info("[email:log] -> %s | %s", to, subject)
        return EmailResult(False, "log", to, subject)

    # ---- Modo producción: SMTP real. ----
    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("[email:smtp] OK -> %s | %s", to, subject)
        return EmailResult(True, "smtp", to, subject)
    except Exception as exc:
        # Si falla el SMTP, hacer fallback al log (no romper el flujo).
        logger.exception("[email:smtp] FALLÓ -> %s: %s", to, exc)
        _ensure_log_dir()
        try:
            with _LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write("=" * 72 + "\n")
                fh.write(f"[FALLBACK SMTP FALLÓ] {exc}\n")
                fh.write(f"Para: {to} | Asunto: {subject}\n")
                fh.write(body + "\n")
        except Exception:
            pass
        return EmailResult(False, "log", to, subject, detail=str(exc))


# === Plantillas de email para Bitácora GRM ===================================

def email_ticket_en_columna(
    *,
    ticket_codigo: str,
    ticket_titulo: str,
    estado_origen: str,
    estado_destino: str,
    responsable_nombre: str,
    actor_nombre: str,
    url_ticket: str,
) -> tuple:
    """
    Devuelve (asunto, body_texto, body_html) para el email que se envía
    al responsable de la columna cuando un ticket cae en su columna.
    """
    subject = f"[{ticket_codigo}] Nuevo ticket en tu columna «{estado_destino}»"
    body = (
        f"Hola {responsable_nombre},\n\n"
        f"El ticket {ticket_codigo} acaba de caer en la columna "
        f"«{estado_destino}», que tienes asignada como responsable.\n\n"
        f"  - Titulo:    {ticket_titulo}\n"
        f"  - Origen:    {estado_origen}\n"
        f"  - Destino:   {estado_destino}\n"
        f"  - Movido por: {actor_nombre}\n\n"
        f"Puedes ver y atender el ticket aqui:\n  {url_ticket}\n\n"
        f"- Bitacora GRM\n"
    )
    html = (
        f"<p>Hola <b>{responsable_nombre}</b>,</p>"
        f"<p>El ticket <b>{ticket_codigo}</b> acaba de caer en la columna "
        f"«<b>{estado_destino}</b>», que tienes asignada como responsable.</p>"
        f"<ul>"
        f"  <li><b>Titulo:</b> {ticket_titulo}</li>"
        f"  <li><b>Origen:</b> {estado_origen}</li>"
        f"  <li><b>Destino:</b> {estado_destino}</li>"
        f"  <li><b>Movido por:</b> {actor_nombre}</li>"
        f"</ul>"
        f'<p><a href="{url_ticket}" '
        f'style="display:inline-block;background:#4f46e5;color:#fff;'
        f'padding:8px 14px;border-radius:6px;text-decoration:none">'
        f"Abrir ticket</a></p>"
        f'<p style="color:#64748b;font-size:12px">- Bitacora GRM</p>'
    )
    return subject, body, html
