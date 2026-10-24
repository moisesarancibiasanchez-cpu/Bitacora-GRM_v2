# -*- coding: utf-8 -*-
"""Verifica en PRODUCCION que el estado 'Produccion OK' (con tilde) existe y
que sus 3 transiciones se crearon.

Esta es la comprobacion directa del arreglo del bug de acentos: antes, el
pre-check de la migracion 4.6 nunca encontraba el estado (comparaba con
'produccion ok' sin tilde) y las transiciones de 4.7 nunca se insertaban.
"""
from __future__ import annotations

import sys

import httpx

BASE = "https://bitacora-grmv2-production.up.railway.app"
FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=40, follow_redirects=True) as c:
        r = c.post("/api/v1/auth/login",
                   json={"username": "admin", "password": "admin123"})
        _check("login admin/admin123", r.status_code == 200, "status=%s" % r.status_code)
        if r.status_code != 200:
            return 1

        # --- Estados ------------------------------------------------------
        r = c.get("/api/v1/estados")
        _check("GET /api/v1/estados responde 200", r.status_code == 200,
               "status=%s" % r.status_code)
        try:
            estados = r.json()
        except Exception:
            estados = []
        if isinstance(estados, dict):
            estados = estados.get("estados") or estados.get("items") or []
        nombres = [e.get("nombre") for e in estados if isinstance(e, dict)]

        print("      estados en produccion (%d): %r" % (len(nombres), nombres))
        _check("el estado 'Produccion OK' existe con el nombre canonico CON tilde",
               "Producción OK" in nombres,
               "encontrado=%r" % ("Producción OK" in nombres))
        _check("NO hay duplicados de 'Produccion OK'",
               nombres.count("Producción OK") == 1,
               "veces=%d" % nombres.count("Producción OK"))

        # --- Transiciones --------------------------------------------------
        r = c.get("/api/v1/estados/transiciones")
        _check("GET /api/v1/estados/transiciones responde 200", r.status_code == 200,
               "status=%s" % r.status_code)
        try:
            trans = r.json()
        except Exception:
            trans = []
        if isinstance(trans, dict):
            trans = trans.get("transiciones") or trans.get("items") or []

        pares = set()
        for t in trans:
            if not isinstance(t, dict):
                continue
            origen = t.get("estado_origen") or t.get("origen") or {}
            destino = t.get("estado_destino") or t.get("destino") or {}
            o = origen.get("nombre") if isinstance(origen, dict) else origen
            d = destino.get("nombre") if isinstance(destino, dict) else destino
            if o and d:
                pares.add((o, d))
        if not pares:
            # Formato plano: mostrar una muestra para poder diagnosticarlo.
            print("      muestra de transiciones: %r" % (trans[:2] if isinstance(trans, list) else trans))
        else:
            print("      transiciones con origen/destino: %d" % len(pares))

        esperadas = {
            ("Cerrado", "Producción OK"),
            ("Producción OK", "Cerrado"),
            ("Producción OK", "En Curso"),
        }
        faltan = sorted(esperadas - pares)
        _check("las 3 transiciones del flujo 'Produccion OK' existen en produccion",
               not faltan, "faltan=%r" % faltan)

    print("")
    if FALLOS:
        print("RESULTADO FLUJO PRODUCCION OK: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO FLUJO PRODUCCION OK: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
