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

# Captura opcional de correos cuando no hay SMTP (Dev Inbox).
# No requiere dependencias nuevas; ver app/services/dev_inbox.py.
try:
    from app.services.dev_inbox import add as _dev_inbox_add
    _HAS_DEV_INBOX = True
except ImportError:  # pragma: no cover
    _HAS_DEV_INBOX = False


logger = logging.getLogger(__name__)

# Directorio donde se persisten los emails cuando SMTP no está disponible.
_LOG_DIR = Path("tmp")
_LOG_FILE = _LOG_DIR / "app.email.log"


def _ensure_log_dir() -> None:
    """
    Crea el directorio ``tmp/`` de forma idempotente, tolerando:

    1. Que el directorio ya exista (``exist_ok=True`` lo absorbe).
    2. Que ``tmp`` exista como **archivo** y no como directorio: en ese
       caso ``Path.mkdir(parents=True, exist_ok=True)`` reventaría con
       ``FileExistsError: [Errno 17] File exists: 'tmp'``. Detectamos
       ese caso y, en lugar de romper el endpoint, logueamos y
       dejamos que el ``send_email`` siga su curso (el open() del log
       ya está envuelto en su propio try/except, así que el correo
       simplemente no se persistirá pero el flujo del API continúa).
    3. Cualquier otra excepción de FS: se loguea y se continúa.
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        # 'tmp' existe pero NO es un directorio. En producción esto
        # podría pasar si un deploy anterior dejó un archivo con ese
        # nombre, o si una imagen montó tmp como archivo por error.
        # No podemos crear el directorio encima, pero tampoco debemos
        # romper el flujo: el resto de send_email maneja correctamente
        # la ausencia del directorio de log.
        logger.warning(
            "[email] 'tmp' existe pero no es un directorio (%s); "
            "se omite la persistencia del correo en log local.",
            exc,
        )
    except OSError as exc:
        # Permisos, read-only fs, etc.: no rompemos el endpoint.
        logger.warning(
            "[email] No se pudo crear/verificar el directorio 'tmp/' (%s); "
            "el correo se intentará por SMTP y, si falla, seguirá sin log local.",
            exc,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        # Cualquier otro error inesperado: log y seguir.
        logger.warning(
            "[email] Error inesperado al preparar 'tmp/' (%s); "
            "el flujo de envío continúa.",
            exc,
        )


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
        # Persistencia tradicional en archivo de texto (legado, conserva
        # el comportamiento original para quien ya dependa de leerlo).
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

        # Persistencia estructurada en el Dev Inbox (consultable por
        # HTTP en /dev/inbox). Es la ruta preferida para QA: permite ver
        # todos los correos enviados sin necesidad de SMTP real ni de
        # un dominio verificado en servicios como Resend.
        if _HAS_DEV_INBOX:
            try:
                _dev_inbox_add(
                    to=to,
                    subject=subject,
                    body=body,
                    html_body=html_body,
                    cc=cc,
                    transport="log",
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("[email] No se pudo capturar en Dev Inbox: %s", exc)

        logger.info("[email:log] -> %s | %s", to, subject)
        return EmailResult(False, "log", to, subject)

    # ---- Modo producción: SMTP real. ----
    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)

    # Resolución del modo TLS:
    #   - SMTP_USE_SSL=true  → SMTPS (TLS implícito, típico puerto 465 / Resend).
    #   - Si NO se define SMTP_USE_SSL, se autodetecta por puerto:
    #       * puerto 465  → SMTPS (implícito)
    #       * cualquier otro → SMTP plano + STARTTLS si SMTP_USE_TLS=true
    #   - SMTP_USE_TLS=true → STARTTLS sobre SMTP plano (típico puerto 587).
    # Esto evita el clásico bug "port 465 + STARTTLS" donde el servidor
    # espera el handshake TLS antes del primer comando SMTP.
    use_ssl_env = os.getenv("SMTP_USE_SSL")
    if use_ssl_env is not None and use_ssl_env != "":
        use_ssl = use_ssl_env.lower() == "true"
    else:
        use_ssl = (port == 465)
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
        if use_ssl:
            # SMTPS: TLS implícito desde el inicio (puerto 465 / Resend).
            logger.info(
                "[email:smtp] Conectando vía SMTPS (SSL implícito) a %s:%s",
                host, port,
            )
            with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            # SMTP plano (+ STARTTLS si está habilitado). Puerto típico: 587.
            logger.info(
                "[email:smtp] Conectando vía SMTP%s a %s:%s",
                "+STARTTLS" if use_tls else "", host, port,
            )
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


# === Descripciones de alcance por rol (para el email de credenciales) ======
# Estas descripciones son las que se muestran en el correo de bienvenida
# bajo la sección "Alcance de tu perfil:". Se basan en los roles
# definidos en app/models/usuario.py.

_ROL_ALCANCE = {
    "administrador": (
        "Como Administrador, cuentas con acceso total al sistema: gestión "
        "de usuarios, catálogos, configuración de estados y columnas, "
        "visualización de auditoría y reportería gerencial."
    ),
    "agente_senior": (
        "Como Agente Senior, dispones de privilegios operativos para "
        "gestionar el ciclo de vida completo de las incidencias, "
        "administrar asignaciones, actualizar estados, documentar "
        "resoluciones y monitorear el cumplimiento de SLAs."
    ),
    "agente": (
        "Como Agente, puedes atender tickets asignados: actualizar "
        "estados, registrar comentarios, adjuntar antecedentes de "
        "resolución y dar seguimiento al avance de tus incidencias."
    ),
    "solicitante": (
        "Como Solicitante, podrás ingresar nuevos tickets o "
        "requerimientos de incidencias, adjuntar antecedentes y dar "
        "seguimiento directo al estado y tiempos de atención de tus "
        "solicitudes."
    ),
    "observador": (
        "Como Observador, contarás con acceso de solo lectura al "
        "tablero e historial de incidencias para seguimiento, análisis "
        "de avance y reportería interna, sin permisos de edición "
        "operativa sobre los tickets."
    ),
}


def _alcance_por_rol(rol: str) -> str:
    """Devuelve la descripción del alcance del perfil según el rol."""
    return _ROL_ALCANCE.get(
        (rol or "").lower(),
        "Tu perfil fue habilitado en el sistema. Contacta al equipo de "
        "soporte si necesitas más detalles sobre los permisos "
        "asignados.",
    )


def _nombre_corto(nombre_completo: str) -> str:
    """Devuelve el primer nombre + segundo nombre (si existe) para
    personalizar el saludo. Si no hay segundo nombre, devuelve solo el
    primero. Si no hay nombre, devuelve 'usuario'."""
    if not nombre_completo:
        return "usuario"
    partes = [p for p in nombre_completo.strip().split() if p]
    if not partes:
        return "usuario"
    if len(partes) == 1:
        return partes[0]
    # Primer nombre + segundo nombre (opcional) si existe
    return f"{partes[0]} {partes[1]}" if len(partes) >= 2 else partes[0]


def email_credenciales_iniciales(
    *,
    nombre_completo: str,
    email_destino: str,
    username: str,
    password: str,
    rol: str,
    departamento: Optional[str] = None,
    url_sistema: str = "",
    remitente_nombre: str = "Equipo de Soporte y Operaciones GRM v2",
) -> tuple:
    """
    Devuelve (asunto, body_texto, body_html) para el correo de
    credenciales iniciales de un usuario recién creado o reactivado.

    Parameters
    ----------
    nombre_completo : str
        Nombre completo del destinatario.
    email_destino : str
        Email del destinatario (se incluye en el header del email).
    username : str
        Nombre de usuario para iniciar sesión.
    password : str
        Contraseña provisoria (en texto plano para incluir en el email).
    rol : str
        Rol del usuario (administrador, agente_senior, agente,
        solicitante, observador).
    departamento : str, opcional
        Departamento al que pertenece el usuario.
    url_sistema : str, opcional
        URL pública del sistema. Si está vacía se usa un placeholder.
    remitente_nombre : str, opcional
        Nombre del equipo que firma el correo.

    Returns
    -------
    tuple[str, str, str]
        (asunto, cuerpo_texto, cuerpo_html)
    """
    nombre_corto = _nombre_corto(nombre_completo)
    rol_legible = (rol or "").upper() or "USUARIO"
    depto = departamento or "No especificado"
    url = url_sistema or "[URL_DEL_SISTEMA]"

    subject = (
        f"Acceso a Sistema de Monitoreo de Incidencias GRM v2 - "
        f"Credenciales iniciales"
    )

    # ============== Cuerpo en texto plano ==============
    body = (
        f"Estimado/a {nombre_corto},\n\n"
        f"Junto con saludar, te informamos que se ha habilitado tu "
        f"acceso a la plataforma Sistema de Monitoreo de Incidencias "
        f"GRM v2.\n\n"
        f"A continuación, detallamos tus credenciales y datos de acceso:\n\n"
        f"  - URL de acceso: {url}\n"
        f"  - Usuario: @{username}\n"
        f"  - Contraseña provisoria: {password}\n"
        f"  - Departamento: {depto}\n"
        f"  - Perfil / Rol asignado: {rol_legible}\n\n"
        f"Alcance de tu perfil:\n\n"
        f"{_alcance_por_rol(rol)}\n\n"
        f"Seguridad y primeros pasos:\n\n"
        f"Al ingresar por primera vez, el sistema te solicitará "
        f"actualizar tu contraseña temporal por una de tu conocimiento "
        f"exclusivo.\n\n"
        f"Por políticas de seguridad, no compartas estas credenciales "
        f"con terceros.\n\n"
        f"Ante cualquier duda o problema con el ingreso, favor "
        f"responder directamente a este correo o canalizarlo a través "
        f"del equipo de soporte.\n\n"
        f"Saludos cordiales,\n\n"
        f"{remitente_nombre}\n"
    )

    # ============== Cuerpo en HTML ==============
    # Generamos una tabla HTML para que se vea bien en clientes de correo.
    # El escape de los valores se hace manualmente para evitar inyección.
    def _esc(s: str) -> str:
        return (
            (s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    rol_color = {
        "administrador": "#dc2626",   # red
        "agente_senior": "#7c3aed",   # purple
        "agente": "#2563eb",          # blue
        "solicitante": "#059669",     # green
        "observador": "#64748b",      # gray
    }.get((rol or "").lower(), "#0f172a")
    alcance = _esc(_alcance_por_rol(rol))

    html = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Credenciales GRM v2</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f1f5f9;padding:24px 0">
  <tr>
    <td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
        <!-- Header con marca -->
        <tr>
          <td style="background:#0f172a;color:#ffffff;padding:24px;text-align:center">
            <div style="font-size:22px;font-weight:700;letter-spacing:0.3px">
              Bitácora GRM v2
            </div>
            <div style="font-size:13px;opacity:0.8;margin-top:4px">
              Sistema de Monitoreo de Incidencias
            </div>
          </td>
        </tr>
        <!-- Saludo -->
        <tr>
          <td style="padding:24px 28px 8px 28px">
            <p style="margin:0 0 12px 0;font-size:15px;line-height:1.55">
              Estimado/a <b>{_esc(nombre_corto)}</b>,
            </p>
            <p style="margin:0 0 16px 0;font-size:14px;line-height:1.6;color:#334155">
              Junto con saludar, te informamos que se ha habilitado tu
              acceso a la plataforma <b>Sistema de Monitoreo de Incidencias
              GRM v2</b>.
            </p>
            <p style="margin:0 0 6px 0;font-size:14px;color:#334155">
              A continuación, detallamos tus credenciales y datos de acceso:
            </p>
          </td>
        </tr>
        <!-- Tabla de credenciales -->
        <tr>
          <td style="padding:8px 28px 8px 28px">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px">
              <tr>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569;width:38%">
                  URL de acceso
                </td>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:13px">
                  <a href="{_esc(url)}" style="color:#2563eb;text-decoration:none">{_esc(url)}</a>
                </td>
              </tr>
              <tr>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569">
                  Usuario
                </td>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:14px;font-weight:600;font-family:ui-monospace,Menlo,Consolas,monospace">
                  @{_esc(username)}
                </td>
              </tr>
              <tr>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569">
                  Contraseña provisoria
                </td>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:14px;font-weight:600;font-family:ui-monospace,Menlo,Consolas,monospace;color:#b45309">
                  {_esc(password)}
                </td>
              </tr>
              <tr>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569">
                  Departamento
                </td>
                <td style="padding:10px 14px;border-bottom:1px solid #e2e8f0;font-size:13px">
                  {_esc(depto)}
                </td>
              </tr>
              <tr>
                <td style="padding:10px 14px;font-size:13px;color:#475569">
                  Perfil / Rol
                </td>
                <td style="padding:10px 14px;font-size:13px">
                  <span style="display:inline-block;background:{rol_color};color:#ffffff;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:0.3px">
                    {_esc(rol_legible)}
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- Alcance del perfil -->
        <tr>
          <td style="padding:16px 28px 8px 28px">
            <p style="margin:0 0 6px 0;font-size:14px;font-weight:600;color:#0f172a">
              Alcance de tu perfil
            </p>
            <p style="margin:0;font-size:13.5px;line-height:1.6;color:#334155">
              {alcance}
            </p>
          </td>
        </tr>
        <!-- Seguridad y primeros pasos -->
        <tr>
          <td style="padding:16px 28px 8px 28px">
            <p style="margin:0 0 6px 0;font-size:14px;font-weight:600;color:#0f172a">
              Seguridad y primeros pasos
            </p>
            <ul style="margin:0;padding-left:20px;font-size:13.5px;line-height:1.6;color:#334155">
              <li>Al ingresar por primera vez, el sistema te solicitará
                actualizar tu contraseña temporal por una de tu
                conocimiento exclusivo.</li>
              <li>Por políticas de seguridad, no compartas estas
                credenciales con terceros.</li>
              <li>Ante cualquier duda o problema con el ingreso, favor
                responder directamente a este correo o canalizarlo a
                través del equipo de soporte.</li>
            </ul>
          </td>
        </tr>
        <!-- Botón CTA -->
        <tr>
          <td style="padding:20px 28px 8px 28px;text-align:center">
            <a href="{_esc(url)}" style="display:inline-block;background:#4f46e5;color:#ffffff;padding:12px 22px;border-radius:8px;font-size:14px;font-weight:600;text-decoration:none">
              Ingresar a GRM v2
            </a>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="padding:24px 28px;border-top:1px solid #e2e8f0;background:#f8fafc;text-align:center">
            <p style="margin:0 0 4px 0;font-size:13px;color:#475569">
              Saludos cordiales,
            </p>
            <p style="margin:0;font-size:13px;font-weight:600;color:#0f172a">
              {_esc(remitente_nombre)}
            </p>
            <p style="margin:12px 0 0 0;font-size:11px;color:#94a3b8">
              Este es un correo automático. Por favor, no responder a
              esta dirección.
            </p>
          </td>
        </tr>
      </table>
      <p style="font-size:11px;color:#94a3b8;margin-top:12px">
        Bitácora GRM v2 · Sistema de Monitoreo de Incidencias
      </p>
    </td>
  </tr>
</table>
</body>
</html>
"""

    return subject, body, html
