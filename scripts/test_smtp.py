"""
Script de diagnóstico SMTP para Bitácora GRM.

Uso:
    python scripts/test_smtp.py                          # usa variables de .env
    python scripts/test_smtp.py --to tu@correo.cl       # destinatario explícito
    python scripts/test_smtp.py --to tu@correo.cl --subject "hola" --body "prueba"

NO requiere servidor web levantado. Conecta directo a Resend
(sea vía STARTTLS puerto 587 o SMTPS puerto 465, según la
configuración detectada) y reporta claramente qué pasa.

Es una herramienta de diagnóstico, no parte del flujo de la app.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

# Cargar .env si existe (best-effort, sin dependencia obligatoria).
try:
    from dotenv import load_dotenv  # type: ignore
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[test_smtp] Cargué variables desde {env_path}")
    else:
        print(f"[test_smtp] No hay .env en {env_path}; uso el entorno del shell")
except ImportError:
    print("[test_smtp] python-dotenv no instalado; uso solo variables del shell")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").lower() == "true"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--to", default=os.getenv("SMTP_TEST_TO", ""))
    p.add_argument("--subject", default="Prueba SMTP Bitácora GRM")
    p.add_argument("--body", default="Si lees esto, el SMTP está OK ✅")
    args = p.parse_args()

    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)

    if not args.to:
        print("\nERROR: no indicaste destinatario. Usa --to tu@correo.cl", file=sys.stderr)
        return 2

    if not host or not sender:
        print("\nERROR: faltan SMTP_HOST y/o SMTP_FROM en el entorno", file=sys.stderr)
        return 2

    # Misma lógica de autodetección que email_service.py.
    use_ssl_env = os.getenv("SMTP_USE_SSL")
    if use_ssl_env:
        use_ssl = use_ssl_env.lower() == "true"
    else:
        use_ssl = (port == 465)
    use_tls = _bool("SMTP_USE_TLS", True)

    print("=" * 72)
    print("DIAGNÓSTICO SMTP — Bitácora GRM")
    print("=" * 72)
    print(f"  HOST        : {host}")
    print(f"  PORT        : {port}")
    print(f"  USER        : {user}")
    print(f"  FROM        : {sender}")
    print(f"  TO          : {args.to}")
    print(f"  MODO        : {'SMTPS (SSL implícito)' if use_ssl else 'SMTP' + (' + STARTTLS' if use_tls else ' plano')}")
    print(f"  USE_TLS     : {use_tls}")
    print(f"  USE_SSL     : {use_ssl}")
    print("=" * 72)

    if sender.endswith("@resend.dev") and not args.to:
        print(
            "\n[ADVERTENCIA] onbording@resend.dev SOLO envía al dueño de la API key.\n"
            "  Si tu destinatario no es el mismo correo con que creaste la API,\n"
            "  Resend va a responder 'Can only send to your own email address'.\n",
            file=sys.stderr,
        )

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg.set_content(args.body)

    try:
        if use_ssl:
            print(f"\n[tls] Conectando SMTPS a {host}:{port} ...")
            with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
                smtp.set_debuglevel(1)
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            print(f"\n[tls] Conectando SMTP a {host}:{port} ...")
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.set_debuglevel(1)
                if use_tls:
                    smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)

        print("\n[OK] Correo enviado. Revisa la bandeja (y SPAM) de:", args.to)
        return 0
    except smtplib.SMTPAuthenticationError as e:
        print(f"\n[ERROR AUTH] {e.smtp_code} {e.smtp_error.decode(errors='replace')}", file=sys.stderr)
        print("  → Verifica que SMTP_USER sea 'resend' y SMTP_PASSWORD sea la API key completa (re_...)", file=sys.stderr)
        return 1
    except smtplib.SMTPRecipientsRefused as e:
        print(f"\n[ERROR RECIPIENTS] {e.recipients}", file=sys.stderr)
        print("  → Resend suele rechazar recipients con su dominio de prueba (onboarding@resend.dev)", file=sys.stderr)
        print("    si el destinatario NO es el dueño de la API key.", file=sys.stderr)
        return 1
    except smtplib.SMTPSenderRefused as e:
        print(f"\n[ERROR SENDER] {e.smtp_code} {e.smtp_error.decode(errors='replace')}", file=sys.stderr)
        print("  → Resend rechazó el FROM. Verifica que el dominio esté verificado en resend.com/domains", file=sys.stderr)
        return 1
    except smtplib.SMTPException as e:
        print(f"\n[ERROR SMTP] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"\n[ERROR RED] {type(e).__name__}: {e}", file=sys.stderr)
        print("  → Revisa firewall, salida a internet y que el puerto esté abierto", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
