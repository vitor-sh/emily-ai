"""Catálogo público e validação dos modelos oferecidos ao mod.

Este módulo nunca serializa chaves, URLs privadas ou o conteúdo bruto do .env.
"""

from __future__ import annotations

import os
from pathlib import Path

from .hollow_knight_permanente import gravador_catalogo, normalizador_modelo

def catalogo_modelos() -> dict:
    return gravador_catalogo(os.getenv)()


def normalizar_modelo(model_id: object) -> str:
    return normalizador_modelo(os.getenv)(model_id)


def gravar_catalogo(*destinos: Path) -> dict:
    return gravador_catalogo(os.getenv)(*destinos)