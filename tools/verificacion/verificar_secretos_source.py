# -*- coding: utf-8 -*-
"""Control de secretos sobre el directorio que se va a subir como source_path."""
import os
import re

PATRONES = [
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)secret_key\s*[:=]\s*[\"'][^\"']{12,}",
    r"(?i)api[_-]?key\s*[:=]\s*[\"'][^\"']{12,}",
    r"(?i)password\s*[:=]\s*[\"'][^\"']{8,}",
    r"(?i)authorization:\s*basic\s+[A-Za-z0-9+/=]{20,}",
]

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(RAIZ, "docs", "onboarding-demo")


def main() -> int:
    compilados = [re.compile(p) for p in PATRONES]
    hits = 0
    revisados = 0
    for root, _, files in os.walk(BASE):
        for f in files:
            p = os.path.join(root, f)
            revisados += 1
            try:
                texto = open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for rx in compilados:
                for m in rx.finditer(texto):
                    print("POSIBLE SECRETO en %s :: %r" % (p, m.group(0)[:80]))
                    hits += 1
    print("source_path : %s" % os.path.abspath(BASE))
    print("ficheros revisados: %d" % revisados)
    print("posibles secretos: %d" % hits)
    print("RESULTADO SECRETOS: %s" % ("limpio" if hits == 0 else "REVISAR"))
    return 0 if hits == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
