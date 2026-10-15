#!/usr/bin/env python3
"""
Reset seguro de la contraseña del usuario admin en producción.

Uso:
    # 1) Cargar el .env de Railway/producción (exporta DATABASE_URL, etc.)
    set -a; source .env; set +a

    # 2) Definir la NUEVA contraseña
    export NEW_ADMIN_PASSWORD='TuNuevaClaveSegura#2026'

    # 3) Ejecutar
    python scripts/reset_admin_password.py

El script:
  - usa el mismo bcrypt 12-rounds que la app (mismo formato de hash),
  - actualiza la fila del usuario 'admin' en PostgreSQL,
  - inserta un evento de auditoría para trazabilidad,
  - NO muestra ni registra la contraseña en claro (sólo el hash).
"""
import os
import sys
import getpass
import psycopg2
import psycopg2.extras
import bcrypt

# --- Constantes de la app: NO CAMBIAR (deben coincidir con app/core/security.py) ---
_BCRYPT_ROUNDS = 12
ADMIN_USERNAME = "admin"  # usuario al que se resetea la contraseña


def _to_bcrypt_bytes(password: str) -> bytes:
    """Igual que app.core.security._to_bcrypt_bytes: bcrypt <= 72 bytes."""
    if not isinstance(password, str):
        password = str(password)
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    """Igual que app.core.security.hash_password: bcrypt rounds=12."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_to_bcrypt_bytes(password), salt).decode("ascii")


def build_dsn() -> str:
    """
    Devuelve el DSN de PostgreSQL. Prioriza DATABASE_URL (formato Railway).
    Si no existe, lo construye a partir de POSTGRES_* (formato legacy).
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        # Railway usa 'postgres://' pero psycopg2 acepta 'postgresql://'.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    host = os.environ.get("POSTGRES_HOST")
    if host:
        user = os.environ.get("POSTGRES_USER", "postgres")
        pw = os.environ.get("POSTGRES_PASSWORD", "")
        db = os.environ.get("POSTGRES_DB", "railway")
        port = os.environ.get("POSTGRES_PORT", "5432")
        return f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    raise SystemExit(
        "ERROR: no se encontró DATABASE_URL ni POSTGRES_HOST en el entorno.\n"
        "Asegúrate de hacer 'source .env' o 'set -a; source .env; set +a' antes."
    )


def main():
    # 1) Validar que la nueva contraseña venga del entorno o prompt.
    new_pw = os.environ.get("NEW_ADMIN_PASSWORD")
    if not new_pw:
        new_pw = getpass.getpass(f"Nueva contraseña para '{ADMIN_USERNAME}': ")
        new_pw2 = getpass.getpass("Confírmala: ")
        if new_pw != new_pw2:
            raise SystemExit("Las contraseñas no coinciden.")
    if len(new_pw) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres.")
    if len(_to_bcrypt_bytes(new_pw)) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 bytes (UTF-8).")

    # 2) Generar hash con el mismo formato que la app.
    new_hash = hash_password(new_pw)
    print(f"  · Hash generado (bcrypt {_BCRYPT_ROUNDS} rounds), len={len(new_hash)}")

    # 3) Conectar a PostgreSQL.
    dsn = build_dsn()
    # Ocultar password del DSN para el log.
    safe_dsn = dsn
    if "@" in dsn and "://" in dsn:
        scheme, rest = dsn.split("://", 1)
        if "@" in rest:
            _, host_part = rest.split("@", 1)
            safe_dsn = f"{scheme}://***@{host_part}"
    print(f"  · Conectando a: {safe_dsn}")

    conn = psycopg2.connect(dsn, connect_timeout=15)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 4) Verificar que el usuario existe.
            cur.execute(
                "SELECT id, username, rol, email, activo FROM usuarios "
                "WHERE username = %s LIMIT 1;",
                (ADMIN_USERNAME,),
            )
            user = cur.fetchone()
            if not user:
                raise SystemExit(f"ERROR: no existe el usuario '{ADMIN_USERNAME}'.")
            print(f"  · Usuario encontrado: id={user['id']} rol={user['rol']} "
                  f"email={user.get('email')!r} activo={user.get('activo')}")

            # 5) Actualizar la contraseña.
            cur.execute(
                "UPDATE usuarios SET hashed_password = %s, "
                "password_actualizado_en = NOW() "
                "WHERE id = %s RETURNING id;",
                (new_hash, user["id"]),
            )
            updated_id = cur.fetchone()["id"]
            print(f"  · Contraseña actualizada en fila id={updated_id}")

            # 6) Trazabilidad mínima: insertar evento en auditoría si existe la tabla.
            try:
                cur.execute(
                    "INSERT INTO auditoria "
                    "(usuario_id, accion, valor_anterior, valor_nuevo, comentario, "
                    " ip_origen, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, NOW());",
                    (
                        user["id"],
                        "password_reset_script",
                        None,
                        None,
                        "Reset de contraseña ejecutado vía scripts/reset_admin_password.py",
                        os.environ.get("MY_IP", "127.0.0.1"),
                    ),
                )
                print("  · Evento de auditoría insertado.")
            except psycopg2.errors.UndefinedTable:
                conn.rollback()  # descartar el INSERT fallido
                # rehacer el UPDATE ya que el rollback lo borró
                cur.execute(
                    "UPDATE usuarios SET hashed_password = %s WHERE id = %s;",
                    (new_hash, user["id"]),
                )
                print("  · (Aviso: tabla 'auditoria' no existe, se omite trazabilidad.)")
            except Exception as e:
                conn.rollback()
                cur.execute(
                    "UPDATE usuarios SET hashed_password = %s WHERE id = %s;",
                    (new_hash, user["id"]),
                )
                print(f"  · (Aviso: no se pudo insertar en auditoría: {e})")

            conn.commit()

        # 7) Verificación final: comprobar que el hash coincide con la nueva pw.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT hashed_password FROM usuarios WHERE id = %s;",
                (updated_id,),
            )
            (db_hash,) = cur.fetchone()
        ok = bcrypt.checkpw(_to_bcrypt_bytes(new_pw), db_hash.encode("ascii"))
        print()
        print("=" * 60)
        if ok:
            print("✓ RESET COMPLETADO")
            print(f"  Usuario: {ADMIN_USERNAME}")
            print(f"  ID:      {updated_id}")
            print(f"  Verificación bcrypt: OK")
            print()
            print("Ya puedes iniciar sesión con la nueva contraseña en:")
            print("  https://bitacora-grmv2-production.up.railway.app/auth/login")
        else:
            print("✗ ERROR: la verificación final falló (revisar manualmente).")
            sys.exit(2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
