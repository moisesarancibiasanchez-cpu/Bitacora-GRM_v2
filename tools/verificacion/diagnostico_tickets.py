#!/usr/bin/env python
"""Diagnóstico LOCAL de serialización de tickets con TicketRead.

Sustituye al endpoint temporal `/_diag/tickets`, que se retiró de la
aplicación el 2026-10-24 por estar expuesto sin autenticación en producción
y por iterar toda la tabla de tickets en cada petición.

Historia
--------
El endpoint `/_diag/tickets` se creó para encontrar qué campo provocaba un
500 en `/api/v1/tickets`. Quedó en producción sin autenticación y devolvía
`repr()` de los datos de todos los tickets: era una exposición de
información y un riesgo de rendimiento. Este script reproduce la misma
comprobación, pero en local y contra una base SQLite EN MEMORIA con casos
representativos (incluido `datos_catalogo` nulo, que fue el origen del 500).

Uso:
    python tools/verificacion/diagnostico_tickets.py
"""
from __future__ import annotations

import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Base en memoria: este script NUNCA toca una base de datos real.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("DEBUG", "false")


def main() -> int:
    from pydantic import ValidationError
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.models.estado import Estado
    from app.models.ticket import Ticket
    from app.models.usuario import RolUsuario, Usuario
    from app.schemas.ticket import TicketRead

    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    Sesion = sessionmaker(bind=engine)

    db = Sesion()
    try:
        estado = Estado(nombre="BackLog", orden=1)
        db.add(estado)
        db.flush()
        creador = Usuario(username="diag", email="diag@local.invalid",
                          nombre_completo="Diagnóstico",
                          hashed_password="x", rol=RolUsuario.ADMINISTRADOR)
        db.add(creador)
        db.flush()

        casos = [
            ("datos_catalogo nulo", None),
            ("datos_catalogo vacio", {}),
            ("datos_catalogo con datos", {"clave": "valor", "anidado": {"n": 1}}),
        ]
        for i, (descripcion, datos) in enumerate(casos, start=1):
            db.add(Ticket(
                codigo="DIAG-%03d" % i,
                titulo="Ticket de diagnostico %s" % descripcion,
                descripcion="Comprobacion de serializacion",
                estado_id=estado.id,
                creador_id=creador.id,
                datos_catalogo=datos,
            ))
        db.commit()

        tickets = db.query(Ticket).order_by(Ticket.id).all()
        resultado = {"total_tickets": len(tickets), "ok": 0, "errors": []}
        for t in tickets:
            try:
                TicketRead.model_validate(t)
                resultado["ok"] += 1
            except ValidationError as ve:
                resultado["errors"].append({
                    "ticket_id": t.id,
                    "ticket_codigo": t.codigo,
                    "datos_catalogo_type": type(t.datos_catalogo).__name__,
                    "errors": [
                        {"loc": list(e.get("loc", [])), "type": e.get("type"),
                         "msg": e.get("msg")}
                        for e in ve.errors()[:5]
                    ],
                })

        print("tickets de prueba : %d" % resultado["total_tickets"])
        print("serializados OK    : %d" % resultado["ok"])
        print("con error          : %d" % len(resultado["errors"]))
        if resultado["errors"]:
            print(json.dumps(resultado["errors"][0], ensure_ascii=False, indent=2))
            print("RESULTADO: FALLA la serializacion de tickets")
            return 1
        print("RESULTADO: TicketRead serializa correctamente los 3 casos "
              "(datos_catalogo nulo, vacio y con datos)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
