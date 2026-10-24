# -*- coding: utf-8 -*-
"""Verifica en PRODUCCION el estado terminal de "produccion ok" y el flujo
real alrededor de el.

Contexto
--------
La base de datos de produccion NO usa los estados del seed de
app/db/init_db.py: tiene un flujo propio configurado desde la UI (BackLog,
En desarrollo, Entregado, APROBADO QA, produccion ok, DESESTIMADA,
Despliegue PROD, UAT-QA, Analisis, Bloqueado!).

Lo que se comprueba es que el arreglo del bug de tildes NO alteró ese flujo:
  1. el estado terminal existe una sola vez (no hay duplicados);
  2. no se ha creado un estado homónimo con tilde;
  3. el estado es ALCANZABLE: hay alguna transicion que entra en el;
  4. el estado tiene alguna transicion de salida (se puede reabrir);
  5. el numero de transiciones coincide con el esperado (12).
"""
from __future__ import annotations

import httpx

BASE = "https://bitacora-grmv2-production.up.railway.app"
TRANSICIONES_ESPERADAS = 12

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
        estados = r.json()
        if isinstance(estados, dict):
            estados = estados.get("estados") or estados.get("items") or []
        por_id = {e["id"]: e for e in estados
                  if isinstance(e, dict) and "id" in e}
        nombres = [e.get("nombre") for e in por_id.values()]
        print("      estados en produccion (%d): %r" % (len(nombres), nombres))

        candidatos = [n for n in nombres if n and "producci" in n.lower()]
        _check("existe el estado terminal de produccion", len(candidatos) == 1,
               "encontrados=%r" % candidatos)
        if len(candidatos) == 1:
            _check("no hay un homonimo con tilde (sin duplicado por la migracion)",
                   sum(1 for n in nombres if n == "Producción OK") == 0,
                   "estado=%r" % candidatos[0])

        # --- Transiciones --------------------------------------------------
        r = c.get("/api/v1/estados/transiciones")
        _check("GET /api/v1/estados/transiciones responde 200", r.status_code == 200,
               "status=%s" % r.status_code)
        trans = r.json()
        if isinstance(trans, dict):
            trans = trans.get("transiciones") or trans.get("items") or []

        pares = []
        for t in trans:
            if not isinstance(t, dict):
                continue
            o = por_id.get(t.get("estado_origen_id"), {}).get("nombre")
            d = por_id.get(t.get("estado_destino_id"), {}).get("nombre")
            if o and d:
                pares.append((o, d, t.get("rol_requerido")))

        print("      transiciones reales: %d" % len(pares))
        for o, d, rol in sorted(pares, key=lambda x: (str(x[0]), str(x[1]))):
            print("        %-16r -> %-16r  rol=%s" % (o, d, rol))

        _check("el numero de transiciones es el esperado (%d)" % TRANSICIONES_ESPERADAS,
               len(pares) == TRANSICIONES_ESPERADAS, "n=%d" % len(pares))

        if candidatos:
            objetivo = candidatos[0]
            entradas = [p for p in pares if p[1] == objetivo]
            salidas = [p for p in pares if p[0] == objetivo]
            _check("el estado terminal es ALCANZABLE (tiene transiciones de entrada)",
                   bool(entradas), "entradas=%r" % [(p[0], p[2]) for p in entradas])
            _check("el estado terminal tiene salida (se puede reabrir)",
                   bool(salidas), "salidas=%r" % [(p[1], p[2]) for p in salidas])

    print("")
    if FALLOS:
        print("RESULTADO FLUJO PRODUCCION: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO FLUJO PRODUCCION: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
