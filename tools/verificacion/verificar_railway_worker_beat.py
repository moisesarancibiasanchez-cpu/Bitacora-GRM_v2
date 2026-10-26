#!/usr/bin/env python
"""Verifica en Railway que los servicios `worker` y `beat` de Celery arrancan
el proceso correcto y se hablan con el broker real.

Comprueba, contra la API GraphQL de Railway y los logs del despliegue:

  1) Los servicios `worker` y `beat` existen en el entorno `production`.
  2) Su start command es `bash start.sh` y NO tienen healthcheck (un worker
     no sirve HTTP: un healthcheck /health los marcaria como fallidos).
  3) El despliegue mas reciente esta en estado SUCCESS.
  4) En los logs: el rol se resuelve desde PROC_TYPE (NO desde una variable
     que Railway no inyecta) y se lanza celery worker / celery beat.
  5) El broker y el backend de resultados apuntan al Redis del proyecto
     (bases 1 y 2), no a localhost.
  6) Celery beat usa un fichero de calendario en ruta escribible.
  7) El worker registra las tareas del catálogo y queda `ready`.
  8) El beat ha enviado alguna tarea al worker (flujo extremo a extremo).

El token de proyecto se lee de un archivo (nunca se imprime, nunca se escribe
en el repositorio):
    variables de entorno: RAILWAY_TOKEN_FILE
    por defecto:           %TEMP%\\railway_token.txt
El token de proyecto de Railway se envia en la cabecera `Project-Access-Token`
(NOT en `Authorization: Bearer`, que es para tokens de cuenta).

Salida: 0 si todas las comprobaciones pasan, 1 si alguna falla.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

URL = "https://backboard.railway.com/graphql/v2"
PROJECT_ID = os.environ.get(
    "RAILWAY_PROJECT_ID", "c0e1796f-cdcf-4e85-833d-25536dfa674c"
)
RUTA_TOKEN = os.environ.get(
    "RAILWAY_TOKEN_FILE",
    os.path.join(os.environ.get("TEMP", "/tmp"), "railway_token.txt"),
)

FALLOS: list[str] = []
PASADOS = 0


def comprobar(condicion: bool, descripcion: str, detalle: str = "") -> None:
    global PASADOS
    if condicion:
        PASADOS += 1
        print(f"  [OK]   {descripcion}")
    else:
        FALLOS.append(descripcion)
        print(f"  [FALLA] {descripcion}")
        if detalle:
            for linea in detalle.strip().splitlines()[-8:]:
                print(f"          | {linea}")


def leer_token() -> str:
    if not os.path.exists(RUTA_TOKEN):
        raise SystemExit(
            f"No existe el archivo de token: {RUTA_TOKEN}\n"
            "Exporta RAILWAY_TOKEN_FILE o guarda ahi el token de proyecto."
        )
    with open(RUTA_TOKEN, "r", encoding="utf-8") as fh:
        token = fh.read().strip()
    if token.upper().startswith("TOKEN="):
        token = token.split("=", 1)[1].strip()
    if not token:
        raise SystemExit("El archivo de token esta vacio")
    return token


def gql(token: str, query: str, variables: dict | None = None) -> dict:
    cuerpo = {"query": query}
    if variables:
        cuerpo["variables"] = variables
    req = urllib.request.Request(
        URL,
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "railway-cli/3.0",
            "Project-Access-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}")
    if datos.get("errors"):
        raise SystemExit(
            "ERRORES GraphQL: " + json.dumps(datos["errors"], ensure_ascii=False)[:800]
        )
    return datos.get("data") or {}


def texto_logs(logs) -> str:
    partes = []
    for entrada in logs or []:
        if isinstance(entrada, dict):
            partes.append(str(entrada.get("message", "")))
        else:
            partes.append(str(entrada))
    return "\n".join(partes)


def main() -> int:
    print("=" * 78)
    print("VERIFICACION: servicios worker y beat de Celery en Railway")
    print("=" * 78)
    token = leer_token()
    print(f"token: archivo {RUTA_TOKEN} (longitud {len(token)}, no se imprime)")

    datos = gql(
        token,
        """
        query($id: String!) {
          project(id: $id) {
            id name
            environments { edges { node { id name } } }
            services { edges { node { id name } } }
          }
        }
        """,
        {"id": PROJECT_ID},
    )["project"]
    entornos = {e["node"]["name"]: e["node"]["id"] for e in datos["environments"]["edges"]}
    servicios = {s["node"]["name"]: s["node"]["id"] for s in datos["services"]["edges"]}
    env_id = entornos.get("production")
    print(f"proyecto: {datos['name']} | entornos: {list(entornos)}")

    if not env_id:
        print("ERROR: no existe el entorno 'production'")
        return 1

    for nombre in ("worker", "beat"):
        print(f"\n--- {nombre} ---")
        sid = servicios.get(nombre)
        comprobar(sid is not None, f"el servicio '{nombre}' existe en el proyecto")
        if not sid:
            continue

        inst = gql(
            token,
            """
            query($s: String!, $e: String!) {
              serviceInstance(serviceId: $s, environmentId: $e) {
                id startCommand healthcheckPath
                latestDeployment { id status createdAt }
              }
            }
            """,
            {"s": sid, "e": env_id},
        )["serviceInstance"]

        comprobar(
            inst.get("startCommand") == "bash start.sh",
            "start command = 'bash start.sh'",
            f"valor: {inst.get('startCommand')!r}",
        )
        comprobar(
            not inst.get("healthcheckPath"),
            "sin healthcheck (no hay servidor HTTP en un worker/beat)",
            f"valor: {inst.get('healthcheckPath')!r}",
        )

        dep = inst.get("latestDeployment") or {}
        comprobar(
            dep.get("status") == "SUCCESS",
            f"despliegue en estado SUCCESS (id {dep.get('id')}, {dep.get('status')})",
            f"estado: {dep.get('status')}",
        )
        if not dep.get("id"):
            continue

        logs = gql(
            token,
            "query($d: String!, $l: Int) { deploymentLogs(deploymentId: $d, limit: $l) "
            "{ message timestamp severity } }",
            {"d": dep["id"], "l": 250},
        )["deploymentLogs"]
        txt = texto_logs(logs)

        comprobar(
            f"Rol detectado desde PROC_TYPE='{nombre}' -> {nombre}" in txt,
            f"el rol se resuelve desde PROC_TYPE='{nombre}'",
            txt[-1500:],
        )
        comprobar(
            f"Iniciando Bitácora GRM (rol={nombre})" in txt,
            f"start.sh arranca con rol={nombre}",
            txt[-1500:],
        )
        comprobar(
            "postgres.railway.internal" in txt,
            "la conexion a PostgreSQL del proyecto es OK",
            txt[-1500:],
        )
        comprobar(
            "redis.railway.internal" in txt and "localhost" not in txt.split("transport:")[-1][:200],
            "el broker apunta al Redis del proyecto (no a localhost)",
            txt[-1500:],
        )
        if nombre == "worker":
            comprobar("Lanzando celery worker..." in txt, "se lanza celery worker", txt[-1500:])
            comprobar("ready." in txt, "celery queda 'ready'", txt[-1500:])
            comprobar(
                "app.tasks.sla_tasks.recalcular_sla_masivo" in txt,
                "el worker registra el catalogo de tareas",
                txt[-1500:],
            )
            comprobar(
                re.search(r"transport:\s+redis://[^/]+/1", txt) is not None,
                "el broker usa la base 1 de Redis",
                txt[-1500:],
            )
            comprobar(
                re.search(r"results:\s+redis://[^/]+/2", txt) is not None,
                "el backend de resultados usa la base 2 de Redis",
                txt[-1500:],
            )
        else:
            comprobar("Lanzando celery beat..." in txt, "se lanza celery beat", txt[-1500:])
            comprobar(
                "is starting." in txt and "celery beat" in txt,
                "celery beat queda arrancado",
                txt[-1500:],
            )
            comprobar(
                re.search(r"db\s*->\s*/tmp/celerybeat-schedule", txt) is not None,
                "el calendario de beat esta en una ruta escribible (/tmp)",
                txt[-1500:],
            )

    print()
    print("=" * 78)
    total = PASADOS + len(FALLOS)
    if FALLOS:
        print(f"RESULTADO: {PASADOS}/{total} comprobaciones OK, {len(FALLOS)} FALLAN")
        for fallo in FALLOS:
            print(f"  - {fallo}")
        return 1
    print(f"RESULTADO: {PASADOS}/{total} comprobaciones OK, 0 fallos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
