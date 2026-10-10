"""Inicia o gateway permanente pelo mesmo Emily.exe empacotado."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


def iniciar(validar: bool = False) -> None:
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    pasta = raiz / "emily-gateway-service"
    if not pasta.is_dir():
        raise RuntimeError("gateway não entrou no pacote")
    sys.path.insert(0, str(pasta))
    spec = importlib.util.spec_from_file_location("emily_gateway_runtime", pasta / "emily_gateway.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("não consegui carregar o gateway")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    modulo._ler_env()
    if validar:
        return
    modulo.APP.run(host="0.0.0.0", port=modulo.PORTA,
                   debug=False, use_reloader=False, threaded=True)
