# -*- coding: utf-8 -*-
"""Barrido FINAL de secretos e higiene del repositorio.

Comprueba:
  1. Que no haya ningun PAT / credencial completa en el working tree.
  2. Que .git/config no contenga ningun token en la URL del remote.
  3. Que el historial publicado no contenga secretos UTILIZABLES.
  4. Que no haya binarios de runtime versionados (uploads/, imgs/qa/).
  5. Que el arbol de trabajo este limpio y origin/main == HEAD.
  6. Que las variables sensibles esten ignoradas por .gitignore.
"""
from __future__ import annotations

import os
import re
import subprocess

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GIT = r"C:\Program Files\Git\cmd\git.exe"

PATRONES = [
    (r"github_pat_[A-Za-z0-9_]{20,}", "PAT de GitHub"),
    (r"ghp_[A-Za-z0-9]{30,}", "PAT clásico de GitHub"),
    (r"gho_[A-Za-z0-9]{30,}", "OAuth de GitHub"),
    (r"AKIA[0-9A-Z]{16}", "Access key de AWS"),
    (r"sk-[A-Za-z0-9]{32,}", "Clave de OpenAI"),
    (r"re_[A-Za-z0-9]{20,}", "Clave de Resend"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "Clave privada"),
    (r"(?i)authorization:\s*basic\s+[A-Za-z0-9+/=]{24,}", "Cabecera Authorization"),
]
COMPILED = [(re.compile(p), n) for p, n in PATRONES]

# Valores de ejemplo que NO son secretos: PLACEHOLDER, XXXXX..., 123456, etc.
PLACEHOLDERS = re.compile(
    r"(?i)^(x{4,}|0{4,}|1{4,}|a{6,}|z{6,}|example|test|fake|dummy|placeholder|"
    r"changeme|your[_-]?\w+|xxxx|abc123|123456|secret|token|key|"
    r"<[^>]+>|\{[^}]+\})"
)


def _es_placeholder(valor: str) -> bool:
    """True si el valor capturado es un ejemplo, no una credencial real.

    Sin este filtro, la documentacion que muestra el FORMATO de una variable
    de entorno (p. ej. ``RESEND_API_KEY=re_XXXXXXXXXXXXXXXXXXXXXXXXXX``) se
    reportaria como un secreto filtrado, que es un falso positivo.
    """
    limpio = valor.strip()
    if PLACEHOLDERS.match(limpio):
        return True
    # Una credencial real es aleatoria: tiene varios caracteres distintos.
    cuerpo = re.sub(r"^[A-Za-z0-9_]+_", "", limpio)
    if len(cuerpo) >= 8 and len(set(cuerpo)) <= 2:
        return True
    return False


FALLOS = []


def _check(nombre, condicion, detalle=""):
    if condicion:
        print("PASA " + nombre + (" :: " + detalle if detalle else ""))
    else:
        print("FALLA " + nombre + (" :: " + detalle if detalle else ""))
        FALLOS.append(nombre)


def _git(*args):
    return subprocess.run([GIT, "-C", RAIZ] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def main() -> int:
    # --- 1) Working tree -------------------------------------------------
    print("=== 1) Barrido del working tree ===")
    hallazgos = []
    n_ficheros = 0
    for root, dirs, files in os.walk(RAIZ):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "node_modules", "__pycache__", ".venv",
                                "dist", "docs/onboarding-demo-recuperada")]
        for f in files:
            p = os.path.join(root, f)
            n_ficheros += 1
            try:
                texto = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for rx, nombre in COMPILED:
                for m in rx.finditer(texto):
                    if _es_placeholder(m.group(0)):
                        continue
                    hallazgos.append((os.path.relpath(p, RAIZ), nombre,
                                      m.group(0)[:40]))
    print("      ficheros revisados: %d" % n_ficheros)
    for h in hallazgos:
        print("      HALLAZGO: %s :: %s :: %r" % h)
    _check("sin credenciales completas en el working tree (%d ficheros)" % n_ficheros,
           not hallazgos, "hallazgos=%d" % len(hallazgos))

    # --- 2) .git/config --------------------------------------------------
    print("")
    print("=== 2) .git/config ===")
    cfg = open(os.path.join(RAIZ, ".git", "config"), encoding="utf-8",
               errors="ignore").read()
    _check(".git/config no contiene ningun PAT", "github_pat_" not in cfg, "")
    remotos = re.findall(r"url\s*=\s*(\S+)", cfg)
    for r in remotos:
        _check("el remote '%s' no lleva credenciales en la URL" % r,
               "@" not in r.split("//", 1)[-1].split("/", 1)[0], r)

    # --- 3) Historial publicado ------------------------------------------
    print("")
    print("=== 3) Historial (git log --all -p) ===")
    salida = _git("--no-pager", "log", "--all", "-p", "--no-color")
    hist = []
    for rx, nombre in COMPILED:
        for m in rx.finditer(salida):
            if _es_placeholder(m.group(0)):
                continue
            hist.append((nombre, m.group(0)[:40]))
    _check("sin secretos UTILIZABLES en el historial publicado", not hist,
           "hallazgos=%r" % (hist[:3],))

    # --- 4) Binarios de runtime -----------------------------------------
    print("")
    print("=== 4) Higiene de binarios ===")
    ls = _git("ls-files")
    versionados = ls.splitlines()
    uploads = [f for f in versionados if f.startswith("uploads/")]
    imgs_qa = [f for f in versionados if f.startswith("imgs/qa/")]
    _check("no hay binarios versionados bajo uploads/", not uploads,
           "n=%d" % len(uploads))
    _check("no hay capturas versionadas bajo imgs/qa/", not imgs_qa,
           "n=%d" % len(imgs_qa))

    # --- 5) Estado del repo ----------------------------------------------
    print("")
    print("=== 5) Estado del repositorio ===")
    status = _git("--no-pager", "status", "--porcelain").strip()
    _check("el arbol de trabajo esta limpio", status == "",
           (status[:160] if status else "sin cambios pendientes"))
    head = _git("rev-parse", "HEAD").strip()
    origin = _git("rev-parse", "origin/main").strip()
    _check("HEAD == origin/main", head == origin, "HEAD=%s origin=%s" % (head[:12], origin[:12]))
    ahead = _git("rev-list", "--count", "origin/main..HEAD").strip()
    behind = _git("rev-list", "--count", "HEAD..origin/main").strip()
    _check("no hay commits sin publicar", ahead == "0", "ahead=%s" % ahead)
    _check("no hay commits remotos sin integrar", behind == "0", "behind=%s" % behind)
    print("      ficheros versionados: %d" % len(versionados))
    print("      commits en main: %s" % _git("rev-list", "--count", "HEAD").strip())

    # --- 6) .gitignore ---------------------------------------------------
    print("")
    print("=== 6) .gitignore ===")
    gi = _git("show", "HEAD:.gitignore")
    for regla, etiqueta in (
            ("**/.env*", "archivos .env"),
            ("!**/.env.example", "excepcion de .env.example"),
            ("/uploads/", "uploads/"),
            ("/imgs/", "imgs/ (artefactos de QA)"),
            ("/Bitacora-GRM_v2/", "clon anidado"),
            ("/tools/verificacion/_*.py", "diagnosticos de tools/")):
        _check(".gitignore cubre %s" % etiqueta, regla in gi, regla)

    print("")
    if FALLOS:
        print("RESULTADO HIGIENE: %d FALLOS -> %r" % (len(FALLOS), FALLOS))
        return 1
    print("RESULTADO HIGIENE: todas las comprobaciones superadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
