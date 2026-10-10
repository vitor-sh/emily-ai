"""Entrada da versão pública: configuração isolada antes de iniciar a Emily."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def iniciar() -> None:
    from emily_primeiro_inicio import aplicar, carregar, configurar, pasta_perfil
    perfil = pasta_perfil()
    cfg = carregar(perfil)
    if cfg is None or "--configurar" in sys.argv:
        if not configurar(perfil):
            return
        # Um novo processo evita reaproveitar a WebView fechada do assistente.
        if getattr(sys, "frozen", False):
            argumentos = [sys.executable]
        else:
            argumentos = [sys.executable, str(Path(__file__).resolve())]
        os.execv(sys.executable, argumentos)
    aplicar(perfil, cfg)
    from emily_bootstrap import iniciar as iniciar_emily
    iniciar_emily()


if __name__ == "__main__":
    iniciar()
