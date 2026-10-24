# -*- coding: utf-8 -*-
"""Sonda de configuracion: imprime el resultado de Settings + validar().

Se ejecuta como proceso HIJO (subprocess) desde ``_verify_config_real.py``
para que cada escenario corra con un ``os.environ`` limpio: ``Settings`` es
un singleton (``lru_cache``) y ``_exportar_a_environ`` contamina el entorno.
"""
from __future__ import annotations

import json
import os
import sys

# El interprete embebido de Windows corre en modo aislado (._pth) e ignora
# PYTHONPATH, asi que se inserta la raiz del repo a mano.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


def main() -> int:
    from app.core.config import Settings

    s = Settings()
    avisos = s.validar()
    print("@@JSON@@" + json.dumps({
        "DEBUG": s.DEBUG,
        "PUBLIC_BASE_URL": s.PUBLIC_BASE_URL,
        "CORS_ORIGINS": list(s.CORS_ORIGINS or []),
        "SECRET_KEY_len": len(s.SECRET_KEY or ""),
        "avisos": avisos,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print("@@JSON@@" + json.dumps({
            "error": type(exc).__name__,
            "mensaje": str(exc),
        }, ensure_ascii=False))
        raise SystemExit(0)
