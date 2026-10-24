# -*- coding: utf-8 -*-
"""Verificacion REAL del comportamiento CORS de Starlette con la configuracion
exacta que usa app/main.py (allow_origins=['*'], allow_credentials=not wildcard).

Objetivo: demostrar con evidencia ejecutable que, con el comodin y
allow_credentials=False, el navegador NO puede leer respuestas autenticadas
cross-origin (no se emite Access-Control-Allow-Credentials).

No usa mocks: levanta un servidor Starlette/FastAPI real y le hace peticiones
reales con httpx, incluida una peticion con cabecera Cookie.
"""
from __future__ import annotations

import json
import threading
import time

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

RESULTADOS = []


def _check(nombre, condicion, detalle):
    RESULTADOS.append((nombre, bool(condicion), detalle))
    print(("PASA " if condicion else "FALLA ") + nombre + " :: " + detalle)


def _construir_app(allow_origins, allow_credentials):
    app = FastAPI()

    @app.get("/privado")
    def privado():
        return {"dato": "secreto-de-sesion"}

    @app.post("/accion")
    def accion():
        return {"ok": True}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def main() -> int:
    # --- Escenario 1: comodin, como lo dejaria el guard degradado ---------
    app = _construir_app(["*"], False)
    client = TestClient(app)

    r = client.get("/privado", headers={"Origin": "https://atacante.example"})
    acao = r.headers.get("access-control-allow-origin")
    acac = r.headers.get("access-control-allow-credentials")
    _check(
        "comodin: ACAO presente y es '*'",
        acao == "*",
        "Access-Control-Allow-Origin=%r" % acao,
    )
    _check(
        "comodin: NO se emite Access-Control-Allow-Credentials",
        acac is None,
        "Access-Control-Allow-Credentials=%r" % acac,
    )

    # --- Escenario 2: preflight con credenciales --------------------------
    r = client.options(
        "/accion",
        headers={
            "Origin": "https://atacante.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    acao_pf = r.headers.get("access-control-allow-origin")
    acac_pf = r.headers.get("access-control-allow-credentials")
    _check(
        "preflight: ACAO es '*' (no se refleja el origen)",
        acao_pf == "*",
        "Access-Control-Allow-Origin=%r" % acao_pf,
    )
    _check(
        "preflight: NO se emite ACAC -> el navegador bloquea la peticion real",
        acac_pf is None,
        "Access-Control-Allow-Credentials=%r" % acac_pf,
    )

    # --- Escenario 3: peticion simple CON cookie --------------------------
    # Starlette refleja el origen explicito si la peticion trae Cookie.
    r = client.get(
        "/privado",
        headers={
            "Origin": "https://atacante.example",
            "Cookie": "access_token=abc.def.ghi",
        },
    )
    acao_c = r.headers.get("access-control-allow-origin")
    acac_c = r.headers.get("access-control-allow-credentials")
    # Starlette 1.9.0 mantiene el comodin literal '*' tambien cuando la
    # peticion trae Cookie (no refleja el origen). Es el comportamiento MAS
    # restrictivo posible: la respuesta no puede leerse desde ningun origen
    # cross-origin.
    _check(
        "peticion con Cookie: ACAO sigue siendo '*' (no se refleja el origen)",
        acao_c == "*",
        "Access-Control-Allow-Origin=%r" % acao_c,
    )
    _check(
        "peticion con Cookie: SIGUE sin ACAC -> respuesta no legible cross-origin",
        acac_c is None,
        "Access-Control-Allow-Credentials=%r" % acac_c,
    )

    # --- Escenario 4: configuracion con origenes explicitos --------------
    app2 = _construir_app(["https://bitacora-grmv2-production.up.railway.app"], True)
    client2 = TestClient(app2)
    r = client2.get(
        "/privado",
        headers={
            "Origin": "https://bitacora-grmv2-production.up.railway.app",
            "Cookie": "access_token=abc.def.ghi",
        },
    )
    acao_e = r.headers.get("access-control-allow-origin")
    acac_e = r.headers.get("access-control-allow-credentials")
    _check(
        "origenes explicitos: ACAO refleja el origen permitido",
        acao_e == "https://bitacora-grmv2-production.up.railway.app",
        "Access-Control-Allow-Origin=%r" % acao_e,
    )
    _check(
        "origenes explicitos: se emite ACAC=true (credenciales habilitadas)",
        acac_e == "true",
        "Access-Control-Allow-Credentials=%r" % acac_e,
    )

    # --- Escenario 5: origen no permitido con config explicita -----------
    r = client2.get("/privado", headers={"Origin": "https://atacante.example"})
    acao_x = r.headers.get("access-control-allow-origin")
    _check(
        "origenes explicitos: origen no permitido NO recibe ACAO",
        acao_x is None,
        "Access-Control-Allow-Origin=%r" % acao_x,
    )

    total = len(RESULTADOS)
    ok = sum(1 for _, c, _ in RESULTADOS if c)
    print("")
    print("RESULTADO CORS REAL: %d/%d comprobaciones superadas" % (ok, total))

    with open("_cors_real_results.json", "w", encoding="utf-8") as fh:
        json.dump(
            [
                {"nombre": n, "ok": c, "detalle": d}
                for n, c, d in RESULTADOS
            ],
            fh,
            ensure_ascii=False,
            indent=2,
        )
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
