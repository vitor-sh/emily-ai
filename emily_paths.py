"""Caminhos persistentes da Emily, separados dos arquivos do programa."""

from __future__ import annotations

import os
from pathlib import Path


def pasta_dados() -> Path:
    configurada = os.getenv("EMILY_DATA_DIR", "").strip()
    if configurada:
        return Path(configurada).expanduser()
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Emily"
    return Path(__file__).resolve().parent


def arquivo_dados(nome: str) -> Path:
    return pasta_dados() / nome
